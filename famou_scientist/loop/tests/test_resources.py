"""Evaluation Pool 资源声明、装箱和等待状态测试。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou_scientist.loop.domain.resources import (
    GPUDevice,
    GPUResourceRequest,
    ResourceBroker,
    ResourceEnvelope,
    ResourceRequest,
)
from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.evaluation.evaluator import DummyEvaluatorAdapter
from famou_scientist.loop.evaluation.experiment import NoopExperimentRunner
from famou_scientist.loop.execution import resources as execution_resources
from famou_scientist.loop.runtime import AsyncOrchestrator, OrchestratorConfig
from famou_scientist.loop.storage import CandidateStore, JsonlQueue, ResearchState


def _request(
    memory_gib: float,
    *,
    devices: int = 1,
    cpu_cores: float = 1,
    host_memory_gib: float = 2,
) -> ResourceRequest:
    """构造测试使用的细粒度资源请求。"""

    return ResourceRequest(
        cpu_cores=cpu_cores,
        host_memory_gib=host_memory_gib,
        gpu=GPUResourceRequest(
            device_count=devices,
            memory_gib_per_device=memory_gib if devices else 0,
        ),
    )


def test_single_80g_gpu_packs_20_20_30_and_holds_next_20() -> None:
    """单张 80 GiB 卡扣除安全余量后应按显存声明共享。"""

    broker = ResourceBroker(
        ResourceEnvelope(
            cpu_cores=16,
            host_memory_gib=96,
            gpu_devices=(GPUDevice("0", 80, "test-gpu"),),
            gpu_memory_reserve_gib=4,
        )
    )
    leases = [
        broker.try_acquire(_request(memory), owner_id=f"job-{index}")
        for index, memory in enumerate((20, 20, 30), start=1)
    ]

    assert all(lease is not None for lease in leases)
    assert broker.try_acquire(_request(20), owner_id="job-4") is None
    assert broker.snapshot()["used"]["gpu_memory_gib"] == {"0": 70.0}

    released = broker.release(leases[0].lease_id)  # type: ignore[union-attr]
    resumed = broker.try_acquire(_request(20), owner_id="job-4")

    assert released is not None
    assert resumed is not None
    assert resumed.cuda_visible_devices == "0"


def test_resource_broker_holds_until_observed_gpu_memory_is_free() -> None:
    """逻辑租约有余量但当前物理空闲显存不足时必须等待。"""

    observed_free = {"0": 18.0}
    broker = ResourceBroker(
        ResourceEnvelope(
            cpu_cores=8,
            host_memory_gib=32,
            gpu_devices=(GPUDevice("0", 80, "test-gpu"),),
            gpu_memory_reserve_gib=4,
        ),
        gpu_free_memory_provider=lambda: observed_free,
    )

    assert broker.try_acquire(_request(20), owner_id="waiting") is None
    snapshot = broker.snapshot()
    assert snapshot["gpu_observation"]["status"] == "ok"
    assert snapshot["gpu_observation"]["free_memory_gib"] == {"0": 18.0}

    observed_free["0"] = 30.0
    lease = broker.try_acquire(_request(20), owner_id="admitted")

    assert lease is not None
    assert lease.gpu_assignments[0]["observed_free_memory_gib_at_acquire"] == 30.0
    assert lease.gpu_assignments[0]["admission_free_memory_gib"] == 26.0


def test_resource_broker_holds_when_gpu_probe_fails() -> None:
    """动态显存探测失败不能回退到静态总显存并冒险派发。"""

    def failed_probe() -> dict[str, float]:
        """模拟 nvidia-smi 暂时不可用。"""

        raise RuntimeError("probe failed")

    broker = ResourceBroker(
        ResourceEnvelope(
            gpu_devices=(GPUDevice("0", 80),),
            gpu_memory_reserve_gib=4,
        ),
        gpu_free_memory_provider=failed_probe,
    )

    assert broker.try_acquire(_request(20), owner_id="waiting") is None
    assert broker.snapshot()["gpu_observation"]["status"] == "query_failed"


def test_current_gpu_free_memory_maps_runtime_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """实时显存探测结果应能按 CUDA_VISIBLE_DEVICES 的 UUID 查找。"""

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-runtime-token")
    monkeypatch.setattr(execution_resources.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(
        execution_resources.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="0, GPU-physical-uuid, 40960\n",
            stderr="",
        ),
    )

    observed = execution_resources.current_gpu_free_memory_gib()

    assert observed["0"] == 40.0
    assert observed["GPU-physical-uuid"] == 40.0
    assert observed["GPU-runtime-token"] == 40.0


def test_resource_broker_supports_cpu_only_and_multi_gpu() -> None:
    """同一 Broker 模型应覆盖无 GPU、单卡和多卡请求。"""

    cpu_broker = ResourceBroker(
        ResourceEnvelope(cpu_cores=4, host_memory_gib=8)
    )
    cpu_lease = cpu_broker.try_acquire(
        _request(0, devices=0, cpu_cores=2, host_memory_gib=4),
        owner_id="cpu",
    )
    assert cpu_lease is not None
    with pytest.raises(ValueError, match="总资源"):
        cpu_broker.try_acquire(_request(1), owner_id="gpu-on-cpu-job")

    multi_broker = ResourceBroker(
        ResourceEnvelope(
            cpu_cores=16,
            host_memory_gib=64,
            gpu_devices=(GPUDevice("0", 80), GPUDevice("1", 80)),
            gpu_memory_reserve_gib=4,
        )
    )
    both = multi_broker.try_acquire(_request(30, devices=2), owner_id="two-gpu")
    assert both is not None
    assert both.cuda_visible_devices == "0,1"
    assert multi_broker.try_acquire(
        _request(50, devices=1),
        owner_id="held",
    ) is None


def test_explicit_resource_request_rejects_malformed_gpu_object() -> None:
    """显式声明不能用 null 或字符串绕过 GPU 字段校验。"""

    with pytest.raises(ValueError, match="gpu 必须是对象"):
        ResourceRequest.from_mapping(
            {
                "cpu_cores": 1,
                "host_memory_gib": 2,
                "gpu": None,
            },
            require_explicit=True,
        )


def test_public_resource_envelope_redacts_device_ids() -> None:
    """提供给 Agent 的资源信封只能包含容量，不能泄露设备 UUID。"""

    public = ResourceEnvelope(
        cpu_cores=8,
        host_memory_gib=48,
        gpu_devices=(
            GPUDevice("GPU-private-uuid", 80, "A800"),
            GPUDevice("MIG-private-token", 20, "MIG"),
        ),
        gpu_memory_reserve_gib=4,
    ).to_public_dict()

    serialized = json.dumps(public, sort_keys=True)
    assert public["available_cpu"] == 8
    assert public["allocatable_memory_gib"] == 48
    assert public["gpu_device_count"] == 2
    assert public["gpu_devices"][0]["allocatable_memory_gib"] == 76
    assert "GPU-private-uuid" not in serialized
    assert "MIG-private-token" not in serialized


def test_resource_fit_violations_are_actionable() -> None:
    """不可能装入总资源的请求应同时列出 CPU、RAM 和 GPU 冲突。"""

    broker = ResourceBroker(
        ResourceEnvelope(
            cpu_cores=8,
            host_memory_gib=24,
            gpu_devices=(GPUDevice("0", 40),),
            gpu_memory_reserve_gib=4,
        )
    )

    violations = broker.fit_violations(
        _request(70, cpu_cores=16, host_memory_gib=32)
    )

    assert len(violations) == 3
    assert any("cpu_cores 请求 16" in item for item in violations)
    assert any("host_memory_gib 请求 32" in item for item in violations)
    assert any("每张 70" in item for item in violations)


def test_queue_terminal_operations_include_resource_waiters(tmp_path: Path) -> None:
    """停止和墙钟截止不能遗留 waiting_resources 条目。"""

    archive_queue = JsonlQueue(tmp_path / "archive", "evaluation")
    archive_item = archive_queue.push({"id": "a"}, item_type="candidate")
    archive_queue.wait_for_resources(
        archive_item,
        request={"cpu_cores": 1},
        broker_snapshot={},
    )
    archived = archive_queue.archive_queued(reason="user_stop")
    assert [item["status"] for item in archived] == [LoopStatus.Queue.ARCHIVED]

    cutoff_queue = JsonlQueue(tmp_path / "cutoff", "evaluation")
    cutoff_item = cutoff_queue.push({"id": "b"}, item_type="candidate")
    cutoff_queue.wait_for_resources(
        cutoff_item,
        request={"cpu_cores": 1},
        broker_snapshot={},
    )
    marked = cutoff_queue.mark_not_executed(reason="wall_time")
    assert [item["status"] for item in marked] == [
        LoopStatus.Queue.NOT_EXECUTED
    ]


def test_resource_wait_events_are_throttled(tmp_path: Path) -> None:
    """相同资源快照的高频重试不应持续膨胀队列事件日志。"""

    queue = JsonlQueue(tmp_path, "evaluation")
    item = queue.push({"id": "candidate"}, item_type="candidate")
    request = {"cpu_cores": 8, "host_memory_gib": 16, "gpu": {}}
    broker = {"available_cpu_cores": 0}
    queue.wait_for_resources(item, request=request, broker_snapshot=broker)
    event_count = len(queue.events_path.read_text(encoding="utf-8").splitlines())

    queue.wait_for_resources(item, request=request, broker_snapshot=broker)

    assert len(queue.events_path.read_text(encoding="utf-8").splitlines()) == event_count


def test_orchestrator_marks_candidate_waiting_until_lease_is_available(
    tmp_path: Path,
) -> None:
    """资源 hold 状态应同步到 Queue、Candidate 和后续租约。"""

    workspace = tmp_path / "run"
    goal = {
        "goal_id": "resource-hold",
        "goal": {"id": "resource-hold", "name": "resource-hold"},
        "workflow": {"type": "benchmark_managed"},
        "benchmarks": [
            {
                "name": "dummy",
                "official_metric": {
                    "name": "score",
                    "direction": "higher_is_better",
                },
            }
        ],
        "infra": {
            "pipeline": "async",
            "resources": {
                "available_cpu": 8,
                "allocatable_memory_gib": 32,
                "gpu_devices": [
                    {"device_id": "0", "total_memory_gib": 80},
                ],
                "gpu_memory_reserve_gib": 4,
                "resource_declarations_required": True,
            },
        },
    }
    ResearchState(workspace).init(goal)
    orchestrator = AsyncOrchestrator(
        workspace,
        goal,
        evaluator=DummyEvaluatorAdapter(),
        experiment_runner=NoopExperimentRunner(workspace),
        config=OrchestratorConfig(
            min_ideas=0,
            max_parallel_evaluations=1,
        ),
    )
    occupied = orchestrator.resource_broker.try_acquire(
        _request(60),
        owner_id="already-running",
    )
    assert occupied is not None

    source = tmp_path / "source"
    source.mkdir()
    (source / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "method_manifest.json").write_text(
        json.dumps({"entrypoint": "run.py"}),
        encoding="utf-8",
    )
    candidate = CandidateStore(workspace).create(
        {
            "id": "branch-1",
            "branch_id": "branch-1",
            "worktree": str(source),
            "entrypoint": str(source / "run.py"),
        }
    )
    request = _request(20).to_dict()
    orchestrator.queues.evaluation.push(
        {
            **candidate,
            "resource_request": request,
        },
        item_type="candidate",
    )
    state = ResearchState(workspace).load()

    assert orchestrator._claim_evaluation_items(state) == []
    manifest = CandidateStore(workspace).read(candidate["candidate_id"])
    assert manifest["status"] == LoopStatus.Candidate.WAITING_RESOURCES
    assert orchestrator.queues.evaluation.size(
        LoopStatus.Queue.WAITING_RESOURCES
    ) == 1

    orchestrator.resource_broker.release(occupied.lease_id)
    claimed = orchestrator._claim_evaluation_items(state)
    assert len(claimed) == 1
    assert claimed[0]["status"] == LoopStatus.Queue.RUNNING
    assert claimed[0]["payload"]["resource_lease"][
        "cuda_visible_devices"
    ] == "0"
    running_manifest = CandidateStore(workspace).read(candidate["candidate_id"])
    assert running_manifest["status"] == LoopStatus.Candidate.RUNNING
    assert running_manifest["resource_lease"]["lease_id"]
