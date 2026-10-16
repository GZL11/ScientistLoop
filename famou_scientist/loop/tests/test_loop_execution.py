"""Loop 分支工作区、进程隔离和外部适配器测试。"""
from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

from famou_scientist.loop.agents.workers import (
    DummyWorkerSet,
    PromptWorkerSet,
    _implementation_contract,
    _implementation_goal_view,
)
from famou_scientist.loop import cli
from famou_scientist.loop.domain.goal import load_goal
from famou_scientist.loop.execution import (
    AgentWorkspace,
    CommandImplementAgent,
    ExecutionIdentity,
    ImplementRequest,
    LocalSandbox,
    SandboxError,
    WorkspacePathError,
    build_agent_preset_command,
    sandbox_from_config,
)
from famou_scientist.loop.execution.cli_agent_wrapper import (
    _failure_details,
    _transparent_resume_reason,
    _wait_for_agent,
    _wait_for_agent_event,
    _runtime_environment,
    build_cli_argv,
    build_idea_prompt,
    build_idea_rank_prompt,
    build_implement_prompt,
)
from famou_scientist.loop.execution.submit_candidate import (
    main as submit_candidate_main,
    submit as submit_candidate,
)
from famou_scientist.loop.evaluation import (
    adapter_from_goal,
    runner_from_goal,
)
from famou_scientist.loop.examples.naturebench.evaluate_task import (
    _normalize_metric_units,
    _validate_primary_scores,
    _validate_public_submission_contract,
)
from famou_scientist.loop.facilities import CandidateRef
from famou_scientist.loop.integrations.naturebench import (
    NatureBenchBenchmarkAdapter,
    NatureBenchEvaluatorAdapter,
)
from famou_scientist.loop.plugins import AdapterContext
from famou_scientist.loop.prompts import load_prompt
from famou_scientist.loop.storage.candidates import CandidateStore


LOOP_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLES = LOOP_DIR / "examples"


class _RequestTransport:
    """测试插件装配所需的最小可信 transport。"""

    def request(self, *, operation: str, attempt_id: str) -> dict[str, object]:
        """返回最小的可信响应。"""

        return {
            "request_id": f"{operation}-{attempt_id}",
            "attempt_id": attempt_id,
            "valid": True,
            "metrics": {},
        }

    def close(self) -> None:
        """结束测试 transport。"""


def test_commented_naturebench_goal_loads_as_standard_yaml():
    """验证带中文注释的 NatureBench YAML 可以直接加载。"""
    goal = load_goal(EXAMPLES / "naturebench" / "goal.yaml")
    assert goal["goal_id"] == "naturebench_s41592_022_01709_7"
    assert set(goal["goal"]) == {"id", "name"}
    assert goal["workflow"]["type"] == "benchmark_managed"
    assert goal["workers"]["implement"]["runtime"] == "claude"
    assert goal["workers"]["implement"]["model"] == "glm-5.2"
    assert goal["workers"]["idea_rank"]["model"] == "glm-5.2"
    assert goal["workers"]["implement"]["require_submit_candidate"] is True
    assert "experiment_runner" not in goal
    assert goal["infra"]["pipeline"] == "async"
    assert goal["infra"]["concurrency"] == {
        "ideas": 1,
        "implementations": 1,
        "evaluations": 3,
    }
    assert goal["infra"]["scheduling"]["time_aware_idea_ranking"] == {
        "enabled": True,
        "trigger_remaining_sec": 3600,
        "min_items": 3,
        "judge_timeout_sec": 1800,
    }
    assert goal["infra"]["scheduling"]["search_policy"] == {
        "type": "pairwise_improve",
        "enabled": True,
    }
    assert "max_benchmark_attempts" not in goal["constraints"]
    assert "max_evaluator_submissions" not in goal["constraints"]
    assert "max_official_evaluations_per_actor" not in goal["constraints"]
    assert goal["benchmarks"][0]["adapter"]["type"] == "naturebench"
    assert goal["benchmarks"][0]["official_metric"] == {
        "name": "aggregate_improvement",
        "direction": "higher_is_better",
    }


def test_missing_evaluator_fails_closed():
    """验证生产目标不会隐式回退到 Dummy evaluator。"""
    with pytest.raises(ValueError, match="拒绝使用隐式 Dummy"):
        adapter_from_goal({"benchmarks": []})


def test_benchmark_managed_goal_cannot_use_legacy_loop_factories():
    """验证 benchmark-managed 目标不会悄悄落到通用 Loop 工厂。"""
    goal = {"workflow": {"type": "benchmark_managed"}}
    with pytest.raises(ValueError, match="必须通过 agent run"):
        adapter_from_goal(goal)
    with pytest.raises(ValueError, match="必须通过 agent run"):
        runner_from_goal(goal, "/tmp/unused")


def test_naturebench_adapters_are_created_through_plugin_contract(tmp_path: Path):
    """验证 NatureBench 通过插件契约创建两类独立 Facility。"""
    run_dir = tmp_path / "run"
    problem_dir = run_dir / "problem"
    (problem_dir / "data").mkdir(parents=True)
    (problem_dir / "README.md").write_text("public task", encoding="utf-8")
    context = AdapterContext(
        task_id="case-1",
        run_dir=run_dir,
        problem_dir=problem_dir,
        workspace_dir=run_dir / "workspace",
    )

    benchmark = NatureBenchBenchmarkAdapter().create(context)
    evaluator = NatureBenchEvaluatorAdapter().create(context, _RequestTransport())

    assert benchmark.task_id == "case-1"
    assert evaluator.benchmark_name == "naturebench/case-1"
    score_interpretation = benchmark.task_view().metadata["score_interpretation"]
    assert score_interpretation["metric"] == "aggregate_improvement"
    assert score_interpretation["primary_target"] == [
        "match_sota",
        "surpass_sota",
    ]
    assert score_interpretation["levels"][-1]["condition"] == "value > 0.1"


def test_naturebench_scoring_targets_reach_cli_idea_agent(tmp_path: Path):
    """CLI Idea Agent 应能读取 Benchmark Facility 暴露的公开目标等级。"""

    problem_dir = tmp_path / "problem"
    problem_dir.mkdir()
    context = AdapterContext(
        task_id="case-criteria",
        run_dir=tmp_path / "run",
        problem_dir=problem_dir,
        workspace_dir=tmp_path / "workspace",
    )
    task_view = NatureBenchBenchmarkAdapter().create(context).task_view()
    goal_view = _implementation_goal_view(
        {
            "benchmark_task": {"contract": task_view.metadata},
            "benchmarks": [
                {
                    "name": "naturebench/case-criteria",
                    "official_metric": {
                        "name": "aggregate_improvement",
                        "direction": "higher_is_better",
                    },
                    "score_interpretation": task_view.metadata[
                        "score_interpretation"
                    ],
                }
            ],
        }
    )

    criteria = goal_view["benchmark_task"]["contract"][
        "score_interpretation"
    ]
    assert criteria["primary_target"] == ["match_sota", "surpass_sota"]
    assert goal_view["benchmarks"][0]["score_interpretation"] == criteria


def test_naturebench_runner_executes_frozen_candidate(tmp_path: Path):
    """验证插件 Runner 只执行 CandidateStore 冻结后的代码。"""
    run_dir = tmp_path / "run"
    problem_dir = run_dir / "problem"
    (problem_dir / "data").mkdir(parents=True)
    (problem_dir / "README.md").write_text("public task", encoding="utf-8")
    method_dir = tmp_path / "method"
    method_dir.mkdir()
    run_py = method_dir / "run.py"
    run_py.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "output = Path(os.environ['OUTPUT_DIR']) / 'instance-1'\n"
        "output.mkdir(parents=True, exist_ok=True)\n"
        "(output / 'matching.csv').write_text('source,target\\n0,0\\n')\n",
        encoding="utf-8",
    )
    stored = CandidateStore(run_dir).create(
        {
            "branch_id": "branch-1",
            "worktree": str(method_dir),
            "entrypoint": str(run_py),
        }
    )
    candidate = CandidateRef.from_payload(stored)
    context = AdapterContext(
        task_id="case-1",
        run_dir=run_dir,
        problem_dir=problem_dir,
        workspace_dir=run_dir / "workspace",
        options={"experiment_timeout_sec": 30},
    )
    facility = NatureBenchBenchmarkAdapter().create(context)

    result = facility.run(candidate, context=stored)

    assert result.valid is True
    assert result.artifact_ref is not None
    assert (
        Path(result.artifact_ref.storage_path) / "instance-1" / "matching.csv"
    ).is_file()
    public_result = facility.run_public_evaluation(result.artifact_ref)
    assert public_result["valid"] is True
    assert public_result["diagnostics_public"]["format_check"] == "passed"


@pytest.mark.skipif(shutil.which("prlimit") is None, reason="prlimit is unavailable")
def test_naturebench_runner_reports_memory_failure(tmp_path: Path):
    """NatureBench canonical run 超内存后应返回可路由的工程失败诊断。"""
    run_dir = tmp_path / "run"
    problem_dir = run_dir / "problem"
    (problem_dir / "data").mkdir(parents=True)
    method_dir = tmp_path / "method"
    method_dir.mkdir()
    run_py = method_dir / "run.py"
    run_py.write_text("bytearray(512 * 1024 * 1024)\n", encoding="utf-8")
    stored = CandidateStore(run_dir).create(
        {
            "branch_id": "branch-memory",
            "worktree": str(method_dir),
            "entrypoint": str(run_py),
        }
    )
    context = AdapterContext(
        task_id="case-memory",
        run_dir=run_dir,
        problem_dir=problem_dir,
        workspace_dir=run_dir / "workspace",
        options={
            "experiment_timeout_sec": 30,
            "experiment_memory_limit_bytes": 256 * 1024**2,
        },
    )
    facility = NatureBenchBenchmarkAdapter().create(context)

    result = facility.run(CandidateRef.from_payload(stored), context=stored).to_dict()

    assert result["valid"] is False
    assert result["error"] == "experiment exceeded canonical memory limit"
    assert result["memory_limit_exceeded"] is True
    assert result["termination_reason"] == "memory_limit_exceeded"
    assert result["process_group_isolated"] is True
    assert "MemoryError" in result["stderr"]


def test_naturebench_runner_reports_structured_timeout_failure(tmp_path: Path):
    """canonical 超时应返回足够原 ImplementActor 定向修复的公开诊断。"""

    run_dir = tmp_path / "run"
    problem_dir = run_dir / "problem"
    (problem_dir / "data").mkdir(parents=True)
    method_dir = tmp_path / "method"
    method_dir.mkdir()
    run_py = method_dir / "run.py"
    run_py.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    stored = CandidateStore(run_dir).create(
        {
            "branch_id": "branch-timeout",
            "worktree": str(method_dir),
            "entrypoint": str(run_py),
            "resource_request": {
                "cpu_cores": 1,
                "host_memory_gib": 1,
                "gpu": {"device_count": 0, "memory_gib_per_device": 0},
                "expected_runtime_sec": 0.01,
            },
        }
    )
    context = AdapterContext(
        task_id="case-timeout",
        run_dir=run_dir,
        problem_dir=problem_dir,
        workspace_dir=run_dir / "workspace",
        options={"experiment_timeout_sec": 0.05},
    )
    facility = NatureBenchBenchmarkAdapter().create(context)

    result = facility.run(CandidateRef.from_payload(stored), context=stored).to_dict()

    assert result["valid"] is False
    assert result["stage"] == "canonical_run"
    assert result["error_code"] == "canonical_timeout"
    assert result["timed_out"] is True
    assert result["timeout_sec"] == pytest.approx(0.05)
    assert result["retryable"] is True
    assert result["candidate_id"] == stored["candidate_id"]
    assert result["candidate_dir"] == stored["candidate_dir"]
    assert result["method_dir"] == stored["method_dir"]
    assert result["entrypoint"] == stored["entrypoint"]
    assert stored["entrypoint"] in result["command"]


def test_naturebench_runner_rejects_declared_runtime_above_limit(tmp_path: Path):
    """明显超过 canonical 契约的方案应立即退回，不占用一小时运行资源。"""

    run_dir = tmp_path / "run"
    problem_dir = run_dir / "problem"
    (problem_dir / "data").mkdir(parents=True)
    method_dir = tmp_path / "method"
    method_dir.mkdir()
    run_py = method_dir / "run.py"
    run_py.write_text("raise AssertionError('must not execute')\n", encoding="utf-8")
    stored = CandidateStore(run_dir).create(
        {
            "branch_id": "branch-over-budget",
            "worktree": str(method_dir),
            "entrypoint": str(run_py),
            "resource_request": {
                "cpu_cores": 1,
                "host_memory_gib": 1,
                "gpu": {"device_count": 0, "memory_gib_per_device": 0},
                "expected_runtime_sec": 120,
            },
        }
    )
    context = AdapterContext(
        task_id="case-over-budget",
        run_dir=run_dir,
        problem_dir=problem_dir,
        workspace_dir=run_dir / "workspace",
        options={"experiment_timeout_sec": 60},
    )
    facility = NatureBenchBenchmarkAdapter().create(context)

    result = facility.run(CandidateRef.from_payload(stored), context=stored).to_dict()

    assert result["valid"] is False
    assert result["error_code"] == "canonical_runtime_budget_exceeded"
    assert result["timeout_sec"] == 60
    assert result["expected_runtime_sec"] == 120
    assert result["duration_ms"] is None


def test_agent_workspace_has_private_branch_areas_and_manifest(tmp_path: Path):
    goal_workspace = tmp_path / "goal"
    workspace = AgentWorkspace.create(
        goal_workspace,
        "branch_1",
        public_payload={"baseline": "A"},
        metadata={"implementation_type": "test"},
    )

    assert workspace.root == goal_workspace.resolve() / "branches" / "branch_1"
    assert workspace.worktree.is_dir()
    assert workspace.public.is_dir()
    assert workspace.outputs.is_dir()
    assert workspace.logs.is_dir()
    assert workspace.manifest_path.is_file()
    assert (workspace.public / "context.json").is_file()
    assert workspace.resolve_worktree_path("nested/method.py").parent == (
        workspace.worktree / "nested"
    )

    reopened = AgentWorkspace.open(goal_workspace, "branch_1")
    assert reopened.worktree == workspace.worktree


@pytest.mark.parametrize(
    "relative_path",
    ["../escape.py", "/tmp/escape.py", "control/stop", "evaluator/grader.py"],
)
def test_agent_workspace_rejects_unsafe_paths(tmp_path: Path, relative_path: str):
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_1")
    with pytest.raises(WorkspacePathError):
        workspace.write_worktree_text(relative_path, "should not be written")
    assert not (tmp_path / "escape.py").exists()


def test_local_sandbox_runs_only_inside_root_and_records_timeout(tmp_path: Path):
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_1")
    sandbox = LocalSandbox(workspace.worktree)

    result = sandbox.run(
        [sys.executable, "-c", "print('sandbox-ok')"],
        timeout_sec=5,
    )
    assert result.valid
    assert "sandbox-ok" in result.stdout
    assert result.cwd == str(workspace.worktree)

    with pytest.raises(SandboxError):
        sandbox.run(
            [sys.executable, "-c", "print('outside')"],
            cwd=tmp_path,
        )

    timeout_result = sandbox.run(
        [sys.executable, "-c", "import time; time.sleep(0.2)"],
        timeout_sec=0.01,
    )
    assert timeout_result.timed_out is True
    assert timeout_result.valid is False
    assert timeout_result.termination_reason == "timeout"
    assert timeout_result.process_group_isolated is True


@pytest.mark.skipif(shutil.which("prlimit") is None, reason="prlimit is unavailable")
def test_local_sandbox_memory_limit_preserves_controller(tmp_path: Path):
    """候选超过内存上限时只应失败当前进程，Controller 仍能继续执行。"""
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_memory")
    sandbox = LocalSandbox(
        workspace.worktree,
        memory_limit_bytes=256 * 1024**2,
    )

    failed = sandbox.run(
        [sys.executable, "-c", "bytearray(512 * 1024 * 1024)"],
        timeout_sec=10,
    )

    assert failed.valid is False
    assert failed.memory_limit_exceeded is True
    assert failed.termination_reason == "memory_limit_exceeded"
    assert failed.memory_limit_bytes == 256 * 1024**2
    assert "MemoryError" in failed.stderr
    # 同一个 Controller 进程和 Sandbox 在资源失败后仍可运行下一条命令。
    recovered = sandbox.run(
        [sys.executable, "-c", "print('controller-alive')"],
        timeout_sec=5,
    )
    assert recovered.valid is True
    assert "controller-alive" in recovered.stdout


def test_local_sandbox_rss_mode_classifies_cuda_oom(tmp_path: Path):
    """RSS 主存监控不应把 CUDA 分配失败误报成主存超限。"""
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_cuda_oom")
    sandbox = LocalSandbox(
        workspace.worktree,
        memory_limit_bytes=256 * 1024**2,
        memory_limit_strategy="rss",
    )

    result = sandbox.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stderr.write('torch.OutOfMemoryError: CUDA out of memory\\n'); "
                "raise SystemExit(1)"
            ),
        ],
        timeout_sec=5,
    )

    assert sandbox.memory_limit_strategy == "rss"
    assert not any(
        Path(item).name == "prlimit"
        for item in sandbox._execution_argv((sys.executable, "-V"))
    )
    assert result.valid is False
    assert result.memory_limit_exceeded is False
    assert result.cuda_out_of_memory is True
    assert result.termination_reason == "cuda_out_of_memory"


def test_local_sandbox_rss_limit_stops_only_candidate(tmp_path: Path):
    """RSS 监控越界后只回收 Candidate，Controller 仍可继续执行。"""
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_rss")
    sandbox = LocalSandbox(
        workspace.worktree,
        memory_limit_bytes=64 * 1024**2,
        memory_limit_strategy="rss",
        memory_monitor_interval_sec=0.02,
    )

    failed = sandbox.run(
        [
            sys.executable,
            "-c",
            "import time; payload=bytearray(128 * 1024 * 1024); time.sleep(2)",
        ],
        timeout_sec=5,
    )

    assert failed.valid is False
    assert failed.memory_limit_exceeded is True
    assert failed.memory_limit_strategy == "rss"
    assert (failed.observed_memory_bytes or 0) > 64 * 1024**2
    assert failed.termination_reason == "memory_limit_exceeded"
    recovered = sandbox.run(
        [sys.executable, "-c", "print('controller-alive')"],
        timeout_sec=5,
    )
    assert recovered.valid is True


@pytest.mark.skipif(
    os.geteuid() != 0 or shutil.which("setpriv") is None,
    reason="非特权身份隔离测试需要 root 和 setpriv",
)
def test_local_sandbox_drops_privileges_and_cannot_read_trusted_tree(
    tmp_path: Path,
):
    """Agent 可写自己的 workspace，但不能读取 root-only evaluator 资源。"""

    # 允许非特权进程穿过测试根目录，使拒绝确实发生在 trusted 的 0700 边界。
    tmp_path.chmod(0o711)
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    secret = trusted / "ground_truth.txt"
    secret.write_text("hidden", encoding="utf-8")
    trusted.chmod(0o700)
    secret.chmod(0o600)
    agent_root = tmp_path / "agent-workspace"
    agent_root.mkdir()
    sandbox = LocalSandbox(
        agent_root,
        identity=ExecutionIdentity(
            uid=65534,
            gid=65534,
            prepare_root_owner=True,
        ),
    )
    code = (
        "import os, pathlib, sys; "
        "pathlib.Path('owned.txt').write_text(str(os.geteuid())); "
        "status = pathlib.Path('/proc/self/status').read_text(); "
        "assert 'NoNewPrivs:\\t1' in status; "
        f"secret = pathlib.Path({str(secret)!r}); "
        "denied = False; "
        "\ntry:\n secret.read_text()\nexcept PermissionError:\n denied = True\n"
        "assert denied"
    )

    result = sandbox.run([sys.executable, "-c", code], timeout_sec=10)

    assert result.valid is True, result.stderr
    assert (agent_root / "owned.txt").read_text(encoding="utf-8") == "65534"


@pytest.mark.skipif(
    os.geteuid() != 0 or shutil.which("setpriv") is None,
    reason="非特权身份隔离测试需要 root 和 setpriv",
)
def test_local_sandbox_falls_back_when_cfs_rejects_chown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """CFS 不支持 chown 时仍应只开放 Agent workspace 并完成降权执行。"""

    tmp_path.chmod(0o711)
    agent_root = tmp_path / "agent-workspace"
    agent_root.mkdir()

    def reject_chown(*args, **kwargs):
        """模拟 CFS 对容器内 chown 返回 EINVAL。"""

        del args, kwargs
        raise OSError(errno.EINVAL, "CFS rejects chown")

    monkeypatch.setattr(os, "chown", reject_chown)
    sandbox = LocalSandbox(
        agent_root,
        identity=ExecutionIdentity(
            uid=65534,
            gid=65534,
            prepare_root_owner=True,
        ),
    )

    result = sandbox.run(
        [
            sys.executable,
            "-c",
            "import os, pathlib; pathlib.Path('owned.txt').write_text(str(os.geteuid()))",
        ],
        timeout_sec=10,
    )

    assert result.valid is True, result.stderr
    assert agent_root.stat().st_mode & 0o007 == 0o007
    assert (agent_root / "owned.txt").read_text(encoding="utf-8") == "65534"


def test_local_sandbox_timeout_kills_candidate_process_group(tmp_path: Path):
    """超时必须清理 Candidate 创建的孙进程，不能泄漏到后续实验。"""
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_process_group")
    child_pid_path = workspace.worktree / "child.pid"
    code = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(30)"
    )
    sandbox = LocalSandbox(workspace.worktree, termination_grace_sec=0.2)

    result = sandbox.run([sys.executable, "-c", code], timeout_sec=0.2)

    assert result.timed_out is True
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    child_state = Path(f"/proc/{child_pid}/stat")
    for _ in range(50):
        if not child_state.exists() or child_state.read_text().split()[2] in {
            "X",
            "Z",
        }:
            break
        time.sleep(0.01)
    assert not child_state.exists() or child_state.read_text().split()[2] in {
        "X",
        "Z",
    }


def test_sandbox_backend_does_not_claim_docker_is_available():
    with pytest.raises(SandboxError, match="DockerSandbox"):
        sandbox_from_config({"type": "docker"}, "/tmp")


def test_sandbox_config_accepts_legacy_fallback_keyword(tmp_path: Path):
    """旧版 worker 的 fallback 调用不能阻断收尾 Agent。"""

    sandbox = sandbox_from_config(
        {},
        tmp_path,
        fallback={"type": "local"},
    )
    try:
        assert isinstance(sandbox, LocalSandbox)
    finally:
        sandbox.close()


def test_dummy_implementer_uses_a_dedicated_branch_workspace(tmp_path: Path):
    branch = DummyWorkerSet().implement(
        {"id": "idea_1", "title": "A", "mechanism": "B"},
        tmp_path / "goal",
    )
    branch_root = Path(branch["agent_workspace"])
    assert branch["isolation"] == "directory"
    assert branch_root.parent.name == "branches"
    assert Path(branch["artifact"]).is_relative_to(branch_root / "outputs")


def test_method_designer_does_not_receive_evaluator_commands(tmp_path: Path):
    captured: list[dict] = []

    class CapturingLLM:
        def complete_json(self, task, prompt, context):  # noqa: ARG002
            captured.append({"task": task, "context": context})
            return {
                "entrypoint": "method.py",
                "files": [
                    {
                        "path": "method.py",
                        "content": "print('method')\n",
                    }
                ],
            }

    goal = {
        "goal": {
            "id": "context_safety",
            "name": "context_safety",
        },
        "benchmarks": [
            {
                "name": "private_bench",
                "adapter": {
                    "public_eval_cmd": "SECRET_PUBLIC_EVAL_COMMAND",
                    "official_eval_cmd": "SECRET_OFFICIAL_EVAL_COMMAND",
                },
                "official_metric": {"name": "accuracy"},
            }
        ],
        "objective_brief": {"primary_goal": "write a method"},
    }
    worker = PromptWorkerSet(goal, tmp_path / "goal", llm=CapturingLLM())
    branch = worker.implement(
        {"id": "idea_1", "title": "A", "mechanism": "B"},
        tmp_path / "goal",
    )

    assert branch["status"] == "implemented"
    method_context = next(item["context"] for item in captured if item["task"] == "method_designer")
    serialized = json.dumps(method_context, ensure_ascii=False)
    assert method_context["goal"]["goal"] == {"name": "context_safety"}
    assert "SECRET_PUBLIC_EVAL_COMMAND" not in serialized
    assert "SECRET_OFFICIAL_EVAL_COMMAND" not in serialized


def test_benchmark_task_contract_stages_only_public_task_data(tmp_path: Path):
    """实现节点应看到公开任务和自定义入口契约，但看不到评测目录。"""
    public_dir = tmp_path / "task" / "problem"
    (public_dir / "data").mkdir(parents=True)
    (public_dir / "README.md").write_text("public instructions", encoding="utf-8")
    (public_dir / "data" / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    (public_dir / "evaluation").mkdir()
    (public_dir / "evaluation" / "secret.txt").write_text("hidden", encoding="utf-8")
    captured: list[dict] = []

    class BenchmarkLLM:
        def complete_json(self, task, prompt, context):  # noqa: ARG002
            captured.append(context)
            return {
                "entrypoint": "run.py",
                "files": [{"path": "run.py", "content": "print('run')\n"}],
            }

    goal = {
        "goal": {"id": "bench", "name": "bench"},
        "workflow": {"type": "benchmark_managed"},
        "benchmark_task": {
            "public_dir": str(public_dir),
            "entrypoint": "run.py",
            "entrypoint_interface": "DATA_DIR -> OUTPUT_DIR",
            "evaluator_dir": "SHOULD_NOT_LEAK",
        },
        "benchmarks": [{"name": "bench"}],
    }
    workspace = tmp_path / "goal"
    worker = PromptWorkerSet(goal, workspace, llm=BenchmarkLLM())
    branch = worker.implement(
        {"id": "attempt_1", "title": "attempt", "mechanism": "solve task"},
        workspace,
    )

    assert branch["status"] == "implemented"
    worktree = Path(branch["worktree"])
    assert (worktree / "run.py").is_file()
    assert (worktree / "benchmark_task" / "README.md").is_file()
    assert (worktree / "benchmark_task" / "data" / "sample.csv").is_file()
    assert not (worktree / "benchmark_task" / "evaluation").exists()
    serialized = json.dumps(captured, ensure_ascii=False)
    assert "DATA_DIR -> OUTPUT_DIR" in serialized
    assert "SHOULD_NOT_LEAK" not in serialized


def test_nested_benchmark_contract_reaches_implement_agent():
    """Harness 的 task contract 应生成固定入口和运行接口约束。"""

    contract = _implementation_contract(
        {
            "benchmark_task": {
                "type": "naturebench",
                "contract": {
                    "entrypoint": "run.py",
                    "input_environment": "DATA_DIR",
                    "output_environment": "OUTPUT_DIR",
                },
                "execution_limits": {"canonical_timeout_sec": 3600},
            }
        }
    )

    assert contract["entrypoint"] == "run.py"
    assert contract["entrypoint_must_be_executable"] is True
    assert contract["entrypoint_interface"] == "DATA_DIR -> OUTPUT_DIR"
    assert contract["canonical_timeout_sec"] == 3600


def test_submit_candidate_uses_contract_entrypoint_as_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Agent 省略 --entrypoint 时应采用 benchmark contract 并完成提交。"""

    worktree = tmp_path / "worktree"
    outputs = tmp_path / "outputs"
    worktree.mkdir()
    outputs.mkdir()
    (worktree / "run.py").write_text("print('ok')\n", encoding="utf-8")
    manager_result = outputs / "manager-result.json"
    worktree_result = worktree / "famou_agent_result.json"
    submission_event = outputs / "candidate-submission.json"
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_WORKTREE", str(worktree))
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_OUTPUT", str(manager_result))
    monkeypatch.setenv(
        "FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT",
        str(worktree_result),
    )
    monkeypatch.setenv("FAMOU_SUBMISSION_PATH", str(submission_event))
    monkeypatch.setenv("FAMOU_EXPECTED_ENTRYPOINT", "run.py")

    receipt = submit_candidate(
        Namespace(
            entrypoint=None,
            title="fallback",
            summary="contract fallback",
            file=[],
            experiment_plan=[],
            limitation=[],
        )
    )

    result = json.loads(manager_result.read_text(encoding="utf-8"))
    assert receipt["accepted"] is True
    assert receipt["entrypoint"] == "run.py"
    assert result["entrypoint"] == "run.py"
    assert result["entrypoint_source"] == "benchmark_contract"
    assert result["files"] == [{"path": "run.py"}]


def test_submit_candidate_rejects_invalid_python_before_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """错误入口应在 Agent 当前回合失败，不应发布 Candidate 事件。"""

    worktree = tmp_path / "worktree"
    outputs = tmp_path / "outputs"
    worktree.mkdir()
    outputs.mkdir()
    (worktree / "run.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_WORKTREE", str(worktree))
    monkeypatch.setenv(
        "FAMOU_IMPLEMENT_AGENT_OUTPUT",
        str(outputs / "manager-result.json"),
    )
    monkeypatch.setenv(
        "FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT",
        str(worktree / "famou_agent_result.json"),
    )
    submission_event = outputs / "candidate-submission.json"
    monkeypatch.setenv("FAMOU_SUBMISSION_PATH", str(submission_event))
    monkeypatch.setenv("FAMOU_EXPECTED_ENTRYPOINT", "run.py")

    with pytest.raises(ValueError, match="Python entrypoint 语法检查失败"):
        submit_candidate(
            Namespace(
                entrypoint=None,
                title=None,
                summary=None,
                file=[],
                experiment_plan=[],
                limitation=[],
            )
        )

    assert not submission_event.exists()


def test_submit_candidate_rejects_oversized_resource_request_before_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """资源超限应直接反馈当前 Agent；修正声明后可在原回合重提。"""

    worktree = tmp_path / "worktree"
    outputs = tmp_path / "outputs"
    worktree.mkdir()
    outputs.mkdir()
    (worktree / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (worktree / "method_manifest.json").write_text(
        json.dumps(
            {
                "entrypoint": "run.py",
                "files": ["run.py"],
                "resource_request": {
                    "cpu_cores": 16,
                    "host_memory_gib": 32,
                    "gpu": {
                        "device_count": 1,
                        "memory_gib_per_device": 70,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    manager_result = outputs / "manager-result.json"
    submission_event = outputs / "candidate-submission.json"
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_WORKTREE", str(worktree))
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_OUTPUT", str(manager_result))
    monkeypatch.setenv(
        "FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT",
        str(worktree / "famou_agent_result.json"),
    )
    monkeypatch.setenv("FAMOU_SUBMISSION_PATH", str(submission_event))
    monkeypatch.setenv("FAMOU_EXPECTED_ENTRYPOINT", "run.py")
    monkeypatch.setenv(
        "FAMOU_RESOURCE_ENVELOPE_JSON",
        json.dumps(
            {
                "available_cpu": 8,
                "allocatable_memory_gib": 24,
                "gpu_devices": [
                    {
                        "device_id": "GPU-private-uuid",
                        "total_memory_gib": 40,
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("FAMOU_RESOURCE_DECLARATIONS_REQUIRED", "1")

    rc = submit_candidate_main([])
    rejected = json.loads(capsys.readouterr().out)

    assert rc == 2
    assert rejected["accepted"] is False
    assert "超过任务总资源信封" in rejected["error"]
    assert "cpu_cores 请求 16" in rejected["error"]
    assert "host_memory_gib 请求 32" in rejected["error"]
    assert "每张 70" in rejected["error"]
    assert not submission_event.exists()
    assert not manager_result.exists()

    # 模拟原 Implement Agent 读取错误后降低资源声明，并在同一激活内重新提交。
    manifest = json.loads(
        (worktree / "method_manifest.json").read_text(encoding="utf-8")
    )
    manifest["resource_request"] = {
        "cpu_cores": 4,
        "host_memory_gib": 8,
        "gpu": {"device_count": 1, "memory_gib_per_device": 20},
    }
    (worktree / "method_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    rc = submit_candidate_main([])
    accepted = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert accepted["accepted"] is True
    assert submission_event.is_file()
    result = json.loads(manager_result.read_text(encoding="utf-8"))
    assert result["resource_request"]["host_memory_gib"] == 8


def test_submit_candidate_accepts_large_source_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Candidate 源码不应再受旧的单文件或总字节数阈值限制。"""

    worktree = tmp_path / "worktree"
    outputs = tmp_path / "outputs"
    worktree.mkdir()
    outputs.mkdir()
    large_source = "#" * (5 * 1024 * 1024) + "\nprint('ok')\n"
    (worktree / "run.py").write_text(large_source, encoding="utf-8")
    manager_result = outputs / "manager-result.json"
    submission_event = outputs / "candidate-submission.json"
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_WORKTREE", str(worktree))
    monkeypatch.setenv("FAMOU_IMPLEMENT_AGENT_OUTPUT", str(manager_result))
    monkeypatch.setenv(
        "FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT",
        str(worktree / "famou_agent_result.json"),
    )
    monkeypatch.setenv("FAMOU_SUBMISSION_PATH", str(submission_event))
    monkeypatch.setenv("FAMOU_EXPECTED_ENTRYPOINT", "run.py")

    receipt = submit_candidate(
        Namespace(
            entrypoint=None,
            title="large source",
            summary=None,
            file=["run.py"],
            experiment_plan=[],
            limitation=[],
        )
    )

    assert receipt["accepted"] is True
    result = json.loads(manager_result.read_text(encoding="utf-8"))
    submitted = Path(result["submitted_worktree"])
    assert submitted.joinpath("run.py").stat().st_size > 5 * 1024 * 1024


def test_prompt_worker_can_use_command_backed_implement_agent(tmp_path: Path):
    goal_file = FIXTURES / "goals" / "agent_worker_algorithm_innovation.yaml"
    rc = cli.main(
        [
            "run",
            "--goal-file",
            str(goal_file),
            "--root",
            str(tmp_path),
            "--max-ticks",
            "5",
            "--reinit",
        ]
    )
    assert rc == 0

    workspace = tmp_path / "agent_worker_algorithm_innovation"
    branches = list((workspace / "branches").glob("branch_*"))
    assert branches
    method_manifest = branches[0] / "worktree" / "method_manifest.json"
    manifest = json.loads(method_manifest.read_text(encoding="utf-8"))
    assert manifest["implementation_type"] == "command_agent"
    assert manifest["entrypoint"] == "method.py"
    assert (branches[0] / "public" / "IMPLEMENT_INSTRUCTIONS.md").is_file()
    assert list((branches[0] / "logs").glob("implement_agent_*.log"))

    records = []
    for line in (workspace / "artifacts" / "artifact_index.jsonl").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.strip():
            records.append(json.loads(line))
    worker_calls = [
        json.loads((workspace / record["path"]).read_text(encoding="utf-8"))
        for record in records
        if record["type"] == "worker_call"
    ]
    assert any(call.get("task") == "implement_agent" for call in worker_calls)


def test_prompt_worker_can_use_command_backed_idea_agent(tmp_path: Path):
    """Idea 节点可由独立 CLI Agent 运行并返回结构化候选。"""
    fake_agent = tmp_path / "fake_idea_agent.py"
    fake_agent.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAMOU_IMPLEMENT_AGENT_OUTPUT']).write_text(\n"
        "    json.dumps({'status': 'implemented', 'title': 'CLI idea', "
        "'method': 'read ExpBank and improve the baseline'}),\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    goal = {
        "goal": {"id": "idea-agent", "name": "idea-agent"},
        "workflow": {"type": "benchmark_managed"},
        "benchmarks": [{"name": "bench"}],
        "workers": {
            "idea": {
                "type": "agent",
                "cmd": f"{sys.executable} {fake_agent}",
                "timeout_sec": 30,
            }
        },
    }
    workspace = tmp_path / "workspace"
    worker = PromptWorkerSet(goal, workspace, llm=object())

    ideas = worker.generate_ideas(goal, [])

    assert len(ideas) == 1
    assert ideas[0]["title"] == "CLI idea"
    assert ideas[0]["mechanism"] == "read ExpBank and improve the baseline"
    idea_workspaces = list(
        (workspace / "idea_agent_workspaces" / "branches").glob("idea_agent_*")
    )
    assert len(idea_workspaces) == 1
    assert (idea_workspaces[0] / "public" / "IDEA_INSTRUCTIONS.md").is_file()


@pytest.mark.parametrize(
    ("target_level", "expected_count"),
    [("match_sota", 1), ("surpass_sota", 1), ("unsupported_level", 0)],
)
def test_prompt_worker_validates_idea_expected_return(
    tmp_path: Path,
    target_level: str,
    expected_count: int,
):
    """收益预测必须使用公开等级，且允许不编造数值区间。"""

    class _ExpectedReturnLLM:
        """返回包含收益预测的确定性 Idea。"""

        def complete_json(self, task, prompt, context):  # noqa: ANN001, ARG002
            """构造一条用于协议校验的 Idea。"""

            assert task == "idea_generator"
            return {
                "ideas": [
                    {
                        "title": "Evidence-guided candidate",
                        "mechanism": "Use the strongest ExpBank mechanism.",
                        "expected_return": {
                            "target_level": target_level,
                            "expected_metric": {
                                "name": "aggregate_improvement",
                                "range": None,
                            },
                            "confidence": "medium",
                            "basis": ["ExpBank best candidate improved the same failure mode."],
                            "assumptions": ["The public data distribution remains stable."],
                        },
                    }
                ]
            }

    criteria = {
        "metric": "aggregate_improvement",
        "levels": [
            {"name": "below_sota", "condition": "value < 0"},
            {"name": "match_sota", "condition": "0 <= value <= 0.1"},
            {"name": "surpass_sota", "condition": "value > 0.1"},
        ],
        "primary_target": ["match_sota", "surpass_sota"],
    }
    goal = {
        "goal": {"id": "expected-return", "name": "expected-return"},
        "workflow": {"type": "benchmark_managed"},
        "benchmark_task": {
            "contract": {"score_interpretation": criteria},
        },
        "benchmarks": [
            {
                "name": "naturebench/test",
                "official_metric": {"name": "aggregate_improvement"},
            }
        ],
    }
    worker = PromptWorkerSet(goal, tmp_path / "workspace", llm=_ExpectedReturnLLM())

    ideas = worker.generate_ideas(goal, [])

    assert len(ideas) == expected_count
    if ideas:
        expected_return = ideas[0]["expected_return"]
        assert expected_return["target_level"] == target_level
        assert expected_return["expected_metric"]["range"] is None
        assert "official_metrics" not in ideas[0]


def test_research_idea_agent_resumes_same_cli_session_across_gate_rounds(
    tmp_path: Path,
):
    """开放科研 IdeaAgent 应复用调研 Session，而不是每个 Idea 冷启动。"""

    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, sys",
                "continued = '--continue' in sys.argv",
                "pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_OUTPUT']).write_text(",
                "    json.dumps({",
                "        'status': 'proposed',",
                "        'title': 'refined idea' if continued else 'initial idea',",
                "        'method': 'reuse the same literature map and refine the mechanism',",
                "    }),",
                "    encoding='utf-8',",
                ")",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    goal = {
        "goal": {"id": "continuous-idea", "name": "continuous-idea"},
        "workflow": {"type": "research"},
        "workers": {
            "idea": {
                "type": "agent",
                "runtime": "opencode",
                "binary": str(fake_bin),
                "timeout_sec": 20,
            }
        },
    }
    workspace = tmp_path / "workspace"
    worker = PromptWorkerSet(goal, workspace, llm=object())

    first = worker.generate_ideas(goal, [])
    second = worker.generate_ideas(
        {
            **goal,
            "idea_runtime": {
                "last_review": {
                    "idea_id": first[0]["id"],
                    "review": {"verdict": "revise"},
                }
            },
        },
        [],
    )

    assert first[0]["title"] == "initial idea"
    assert second[0]["title"] == "refined idea"
    assert first[0]["idea_actor_id"] == second[0]["idea_actor_id"]
    branches = list(
        (workspace / "idea_agent_workspaces" / "branches").glob("idea_agent_*")
    )
    assert len(branches) == 1
    metas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in branches[0].joinpath("logs").glob("*.opencode_wrapper_meta.json")
    ]
    assert len(metas) == 2
    assert any("--continue" in meta["command"] for meta in metas)


def test_agent_runtime_preset_resolves_to_wrapper_command(tmp_path: Path):
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_1")
    request_path = workspace.logs / "request.json"
    output_path = workspace.outputs / "result.json"
    instruction_path = workspace.public / "instruction.md"

    argv = build_agent_preset_command(
        {
            "runtime": "codex",
            "binary": "/usr/local/bin/codex",
            "model": "test-model",
            "max_turns": 7,
            "process_memory_limit_bytes": 8 * 1024**3,
            "cancel_file": tmp_path / "controller" / "deadline.json",
            "auto_approve": False,
            "extra_args": ["--ignore-user-config"],
        },
        workspace=workspace,
        input_path=request_path,
        output_path=output_path,
        instruction_path=instruction_path,
    )

    assert argv[0] == sys.executable
    assert "cli_agent_wrapper.py" in argv[1]
    assert "--runtime" in argv and "codex" in argv
    assert "--binary" in argv and "/usr/local/bin/codex" in argv
    assert "--model" in argv and "test-model" in argv
    assert "--max-turns" in argv and "7" in argv
    assert "--memory-limit-bytes" in argv and str(8 * 1024**3) in argv
    assert "--no-auto-approve" in argv
    assert "--extra-arg" in argv and "--ignore-user-config" in argv
    assert "--cancel-file" in argv


def test_kimi_code_preset_defaults_to_kimi_binary(tmp_path: Path):
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_kimi")
    argv = build_agent_preset_command(
        {
            "runtime": "kimi-code",
            "model": "kimi-k3",
        },
        workspace=workspace,
        input_path=workspace.logs / "request.json",
        output_path=workspace.outputs / "result.json",
        instruction_path=workspace.public / "instruction.md",
    )
    assert "--runtime" in argv and "kimi-code" in argv
    binary_index = argv.index("--binary") + 1
    assert argv[binary_index] == "kimi"


def test_claude_preset_can_disable_context_overflow_compaction(tmp_path: Path):
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_claude_compact")
    common = {
        "runtime": "claude",
        "binary": "claude",
        "model": "deepseek-v4-pro",
        "compact_on_context_overflow": False,
    }
    argv = build_agent_preset_command(
        common,
        workspace=workspace,
        input_path=workspace.logs / "request.json",
        output_path=workspace.outputs / "result.json",
        instruction_path=workspace.public / "instruction.md",
    )
    assert "--no-compact-on-context-overflow" in argv
    assert "--compact-on-context-overflow" not in argv


def test_kimi_code_wrapper_uses_prompt_stream_json_and_session_resume(tmp_path: Path):
    base = Namespace(
        runtime="kimi-code",
        binary="kimi",
        worktree=tmp_path,
        title="test",
        model="kimi-k3",
        agent=None,
        profile=None,
        auto_approve=True,
        extra_arg=[],
        role="implement",
    )
    first = build_cli_argv(base, "first prompt", tmp_path / "last.txt")
    assert first == [
        "kimi",
        "--output-format",
        "stream-json",
        "--model",
        "kimi-k3",
        "--prompt",
        "first prompt",
    ]
    resumed = build_cli_argv(
        base,
        "resume prompt",
        tmp_path / "last.txt",
        resume_session=True,
        session_id="kimi-session-1",
    )
    assert resumed == [
        "kimi",
        "--output-format",
        "stream-json",
        "--session",
        "kimi-session-1",
        "--model",
        "kimi-k3",
        "--prompt",
        "resume prompt",
    ]


def test_kimi_code_wrapper_uses_branch_local_home_and_copies_config(tmp_path: Path, monkeypatch):
    logs_dir = tmp_path / "logs"
    config = tmp_path / "source-config.toml"
    config.write_text('[models."kimi-k3"]\nmax_context_size = 131072\n', encoding="utf-8")
    monkeypatch.setenv("KIMI_CODE_CONFIG", str(config))
    env = _runtime_environment(
        Namespace(runtime="kimi-code", logs_dir=str(logs_dir))
    )
    assert env["HOME"] == str(logs_dir / "kimi-code_home")
    assert (logs_dir / "kimi-code_home").is_dir()
    copied = logs_dir / "kimi-code_home" / ".kimi-code" / "config.toml"
    assert copied.read_text(encoding="utf-8") == config.read_text(encoding="utf-8")


def test_cli_agent_wrapper_stops_process_when_controller_cancels(
    tmp_path: Path,
):
    """研究截止文件应终止 Agent 进程组，并与单次调用超时区分。"""

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    cancel_file = tmp_path / "research_deadline_reached.json"
    cancel_file.write_text("{}\n", encoding="utf-8")

    returncode, timed_out, submission, parked, cancelled = _wait_for_agent(
        process,
        timeout_sec=10,
        submission_path=None,
        submission_grace_sec=0,
        cancel_file=cancel_file,
    )

    assert returncode != 0
    assert timed_out is False
    assert submission is None
    assert parked is False
    assert cancelled is True


def test_cli_agent_wrapper_zero_timeout_expires_immediately(tmp_path: Path):
    """心跳恢复时剩余预算为零，必须立即超时而不是取消 DDL。"""

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    started = time.monotonic()

    returncode, timed_out, submission, parked, cancelled = _wait_for_agent(
        process,
        timeout_sec=0,
        submission_path=None,
        submission_grace_sec=0,
    )

    assert time.monotonic() - started < 2
    assert returncode != 0
    assert timed_out is True
    assert submission is None
    assert parked is False
    assert cancelled is False


def test_cli_agent_wrapper_stops_only_agent_group_on_memory_limit(tmp_path: Path):
    """Agent 工具进程超出 RSS 上限时应结束该激活并保留控制进程。"""

    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; payload = bytearray(96 * 1024 * 1024); time.sleep(30)",
        ],
        start_new_session=True,
    )
    memory_state: dict[str, object] = {}

    result = _wait_for_agent_event(
        process,
        timeout_sec=10,
        submission_path=None,
        submission_grace_sec=0,
        memory_limit_bytes=32 * 1024**2,
        memory_state=memory_state,
    )

    returncode, timed_out, submission, parked, cancelled, heartbeat = result
    assert returncode != 0
    assert timed_out is False
    assert submission is None
    assert parked is False
    assert cancelled is False
    assert heartbeat is False
    assert memory_state["exceeded"] is True
    assert int(memory_state["peak_bytes"]) > 32 * 1024**2


def test_deadline_heartbeat_does_not_resume_after_submission(tmp_path: Path):
    """提交事件与心跳同时到达时应 park，不能重复恢复已提交 Session。"""

    submission_path = tmp_path / "submission.json"
    submission_path.write_text(
        json.dumps({"submission_id": "submission-race"}),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )

    result = _wait_for_agent_event(
        process,
        timeout_sec=10,
        submission_path=submission_path,
        submission_grace_sec=0,
        heartbeat_after_sec=0,
    )

    returncode, timed_out, submission, parked, cancelled, heartbeat = result
    assert returncode != 0
    assert timed_out is False
    assert submission == {"submission_id": "submission-race"}
    assert parked is True
    assert cancelled is False
    assert heartbeat is False


@pytest.mark.parametrize(
    ("returncode", "timed_out", "cancelled", "stdout", "stderr", "error_code"),
    [
        (143, True, False, "", "", "agent_timeout_before_submit"),
        (
            1,
            False,
            False,
            "",
            "Session ID abc is already in use",
            "agent_session_in_use",
        ),
        (
            1,
            False,
            False,
            '{"is_error":true,"terminal_reason":"api_error","result":"Connection closed mid-response"}',
            "",
            "agent_api_error",
        ),
        (
            143,
            False,
            False,
            '{"is_error":true,"terminal_reason":"aborted_tools"}',
            "",
            "agent_tools_aborted",
        ),
        # SIGKILL 的细分取决于运行环境的 cgroup 证据（有 OOM 记录则归为
        # agent_killed_by_cgroup_oom），故不在此断言；见
        # test_signal_kill_attribution.py，那里对 cgroup 读取做了打桩。
        (-15, False, False, "", "", "agent_terminated_by_signal"),
        (0, False, False, "", "", "missing_explicit_submit"),
        (143, False, True, "", "", "agent_cancelled_by_research_deadline"),
    ],
)
def test_cli_failure_details_classify_nonzero_rc(
    returncode: int,
    timed_out: bool,
    cancelled: bool,
    stdout: str,
    stderr: str,
    error_code: str,
):
    """CLI 的退出码、超时和控制器取消必须形成不同的可路由诊断。"""

    failure = _failure_details(
        returncode=returncode,
        timed_out=timed_out,
        submitted=False,
        cancelled_by_controller=cancelled,
        result_valid=False,
        result_error="missing explicit submit_candidate event",
        stdout=stdout,
        stderr=stderr,
    )

    assert failure is not None
    assert failure["error_code"] == error_code
    assert failure["return_code"] == returncode
    if returncode == -9:
        assert failure["signal"] == "SIGKILL"


def test_cli_failure_details_identify_agent_memory_limit():
    """进程级内存保护必须形成可恢复、带峰值证据的独立错误码。"""

    failure = _failure_details(
        returncode=-15,
        timed_out=False,
        submitted=False,
        cancelled_by_controller=False,
        result_valid=False,
        result_error="missing explicit submit_candidate event",
        stdout="",
        stderr="",
        memory_limit_exceeded=True,
        memory_limit_bytes=8 * 1024**3,
        observed_memory_bytes=9 * 1024**3,
    )

    assert failure is not None
    assert failure["error_code"] == "agent_memory_limit_exceeded"
    assert failure["retryable"] is True
    assert failure["memory_limit_bytes"] == 8 * 1024**3
    assert failure["observed_memory_bytes"] == 9 * 1024**3


def test_command_implement_agent_resumes_same_session_after_deadline_heartbeat(
    tmp_path: Path,
):
    """DDL 心跳应恢复同一 Session，并在剩余预算内显式提交。"""

    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, subprocess, sys, time",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "if '--continue' not in sys.argv:",
                "    time.sleep(30)",
                "    raise SystemExit(0)",
                "(worktree / 'run.py').write_text(\"print('ok')\\n\", encoding='utf-8')",
                "subprocess.run([",
                "    sys.executable, os.environ['FAMOU_SUBMIT_CANDIDATE'],",
                "    '--entrypoint', 'run.py',",
                "    '--title', 'heartbeat candidate',",
                "    '--summary', 'submitted after session resume',",
                "    '--file', 'run.py',",
                "], check=True)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_heartbeat")
    request = ImplementRequest(
        goal={"goal": {"name": "heartbeat"}},
        idea={"id": "idea_heartbeat", "title": "A", "mechanism": "B"},
        workspace=workspace,
        sandbox=LocalSandbox(workspace.root),
        instruction="实现后显式提交。",
        metadata={"implementation_contract": {"entrypoint": "run.py"}},
    )
    agent = CommandImplementAgent(
        {
            "runtime": "opencode",
            "binary": str(fake_bin),
            "timeout_sec": 10,
            "submission_grace_sec": 0.1,
            "require_submit_candidate": True,
            "deadline_heartbeat": {
                "enabled": True,
                "trigger_after_sec": 0.4,
            },
        }
    )

    result = agent.implement(request)

    assert result.status == "implemented"
    meta = json.loads(
        next(workspace.logs.glob("*.opencode_wrapper_meta.json")).read_text(
            encoding="utf-8"
        )
    )
    heartbeat = meta["deadline_heartbeat"]
    assert heartbeat["enabled"] is True
    assert len(heartbeat["events"]) == 1
    assert len(meta["activation_commands"]) == 2
    assert "--continue" in meta["activation_commands"][1]
    assert meta["session"]["resume_count"] == 1
    assert list(workspace.logs.glob("*.deadline_heartbeat_prompt.md"))


@pytest.mark.parametrize("terminal_reason", ["api_error", "aborted_tools"])
def test_claude_transient_interruption_resumes_immediately_without_explanation(
    tmp_path: Path,
    terminal_reason: str,
):
    """API/工具突发应在 wrapper 内透明恢复，不进入 Controller 失败链路。"""

    fake_bin = tmp_path / "claude"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, subprocess, sys",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "if '--resume' not in sys.argv:",
                "    print(json.dumps({",
                "        'is_error': True,",
                f"        'terminal_reason': {terminal_reason!r},",
                "        'result': 'synthetic transient interruption',",
                "    }))",
                "    raise SystemExit(1)",
                "(worktree / 'resume_prompt.txt').write_text(sys.argv[-1], encoding='utf-8')",
                "(worktree / 'run.py').write_text(\"print('ok')\\n\", encoding='utf-8')",
                "subprocess.run([",
                "    sys.executable, os.environ['FAMOU_SUBMIT_CANDIDATE'],",
                "    '--entrypoint', 'run.py',",
                "    '--title', 'transparently resumed candidate',",
                "    '--file', 'run.py',",
                "], check=True)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    workspace = AgentWorkspace.create(
        tmp_path / "goal",
        f"branch_{terminal_reason}",
    )
    request = ImplementRequest(
        goal={"goal": {"name": "transparent resume"}},
        idea={"id": "idea_resume", "title": "A", "mechanism": "B"},
        workspace=workspace,
        sandbox=LocalSandbox(workspace.root),
        instruction="实现后显式提交。",
        metadata={"implementation_contract": {"entrypoint": "run.py"}},
    )
    agent = CommandImplementAgent(
        {
            "runtime": "claude",
            "binary": str(fake_bin),
            "timeout_sec": 10,
            "submission_grace_sec": 0,
            "require_submit_candidate": True,
        }
    )

    result = agent.implement(request)

    assert result.status == "implemented"
    assert result.failure == {}
    assert workspace.worktree.joinpath("resume_prompt.txt").read_text(
        encoding="utf-8"
    ) == "继续当前任务。"
    meta = json.loads(
        next(workspace.logs.glob("*.claude_wrapper_meta.json")).read_text(
            encoding="utf-8"
        )
    )
    assert len(meta["activation_commands"]) == 2
    assert "--resume" in meta["activation_commands"][1]
    events = meta["transparent_session_resume"]["events"]
    assert [event["terminal_reason"] for event in events] == [terminal_reason]
    assert meta["session"]["resume_count"] == 1


def test_claude_context_overflow_compacts_before_resume(tmp_path: Path):
    """上下文超限时先执行独立 /compact，再恢复任务。"""

    fake_bin = tmp_path / "claude"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, subprocess, sys",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "prompt = sys.stdin.read() if not sys.argv[-1].startswith('/') else sys.argv[-1]",
                "counter = worktree / 'activation_count'",
                "count = int(counter.read_text()) if counter.exists() else 0",
                "counter.write_text(str(count + 1))",
                "if '--resume' not in sys.argv:",
                "    print(json.dumps({'is_error': True, 'terminal_reason': 'completed',",
                "        'result': 'API Error: maximum context length exceeded'}))",
                "    raise SystemExit(1)",
                "if prompt == '/compact':",
                "    print(json.dumps({'type': 'result', 'subtype': 'success'}))",
                "    raise SystemExit(0)",
                "(worktree / 'compacted_then_resumed.txt').write_text('yes')",
                "(worktree / 'run.py').write_text(\"print('ok')\\n\")",
                "subprocess.run([",
                "    sys.executable, os.environ['FAMOU_SUBMIT_CANDIDATE'],",
                "    '--entrypoint', 'run.py', '--title', 'after compact', '--file', 'run.py',",
                "], check=True)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)
    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_context_compact")
    request = ImplementRequest(
        goal={"goal": {"name": "context compact"}},
        idea={"id": "idea_context", "title": "A", "mechanism": "B"},
        workspace=workspace,
        sandbox=LocalSandbox(workspace.root),
        instruction="实现后显式提交。",
        metadata={"implementation_contract": {"entrypoint": "run.py"}},
    )
    agent = CommandImplementAgent(
        {
            "runtime": "claude",
            "binary": str(fake_bin),
            "timeout_sec": 10,
            "submission_grace_sec": 0,
            "require_submit_candidate": True,
        }
    )

    result = agent.implement(request)

    assert result.status == "implemented"
    assert workspace.worktree.joinpath("compacted_then_resumed.txt").exists()
    meta = json.loads(
        next(workspace.logs.glob("*.claude_wrapper_meta.json")).read_text(
            encoding="utf-8"
        )
    )
    assert len(meta["activation_commands"]) == 3
    assert meta["context_compaction"]["requested"] is True
    assert meta["context_compaction"]["completed"] is True
    assert meta["context_compaction"]["events"][0]["status"] == "succeeded"
    session_state = json.loads(
        next(workspace.logs.glob("claude_*_session.json")).read_text(
            encoding="utf-8"
        )
    )
    assert "context_compact_pending" not in session_state
    assert _transparent_resume_reason(
        json.dumps(
            {
                "is_error": True,
                "terminal_reason": "completed",
                "result": "maximum context length exceeded",
            }
        )
    ) == "context_overflow"


def test_agent_runtime_rejects_unknown_preset():
    with pytest.raises(ValueError, match="unsupported implement agent runtime"):
        CommandImplementAgent({"runtime": "unknown_agent"})


def test_codex_wrapper_places_approval_flags_before_exec(tmp_path: Path):
    argv = build_cli_argv(
        Namespace(
            runtime="codex",
            binary="codex",
            worktree=tmp_path,
            title="test",
            model="gpt-test",
            agent=None,
            profile=None,
            auto_approve=True,
            extra_arg=[],
        ),
        "prompt",
        tmp_path / "last.txt",
    )
    assert argv[:4] == [
        "codex",
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
    ]
    assert argv[4] == "never"
    assert "exec" in argv
    assert argv.index("--ask-for-approval") < argv.index("exec")
    assert "--ephemeral" not in argv


def test_codex_wrapper_resumes_actor_local_session(tmp_path: Path):
    """后续 ImplementActor 激活应恢复隔离 CODEX_HOME 中的最近会话。"""
    argv = build_cli_argv(
        Namespace(
            runtime="codex",
            binary="codex",
            worktree=tmp_path,
            title="test",
            model="gpt-test",
            agent=None,
            profile=None,
            auto_approve=True,
            extra_arg=[],
        ),
        "repair the previous candidate",
        tmp_path / "last.txt",
        resume_session=True,
    )

    assert argv[5:8] == ["exec", "resume", "--last"]
    assert "--ephemeral" not in argv

    exact = build_cli_argv(
        Namespace(
            runtime="codex",
            binary="codex",
            worktree=tmp_path,
            title="test",
            model="gpt-test",
            agent=None,
            profile=None,
            auto_approve=True,
            extra_arg=[],
        ),
        "repair the previous candidate",
        tmp_path / "last.txt",
        resume_session=True,
        session_id="019f-test-thread",
    )
    assert "019f-test-thread" in exact
    assert "--last" not in exact


def test_all_loop_agent_prompts_are_centralized_and_loadable():
    """所有生产 Agent/LLM 节点都必须从统一 Prompt 目录加载。"""
    prompt_names = [
        "cli_agents/idea_agent.md",
        "cli_agents/idea_agent_v2.md",
        "cli_agents/idea_agent_v3.md",
        "cli_agents/idea_rank_judge.md",
        "cli_agents/implement_agent.md",
        "cli_agents/implement_agent_v2.md",
        "cli_agents/implement_agent_v3.md",
        "benchmark_managed/idea_agent.md",
        "benchmark_managed/idea_agent_v2.md",
        "benchmark_managed/idea_agent_v3.md",
        "benchmark_managed/idea_rank_judge.md",
        "benchmark_managed/implement_agent.md",
        "benchmark_managed/implement_agent_v2.md",
        "benchmark_managed/implement_agent_v3.md",
        "research/idea_generator.md",
        "research/idea_gate.md",
        "research/idea_rank_judge.md",
        "research/implement_agent.md",
        "research/method_designer.md",
        "research/result_analyst.md",
        "research/deep_analyzer.md",
    ]
    for name in prompt_names:
        assert load_prompt(name)


def test_cli_agent_prompt_templates_render_runtime_context(tmp_path: Path):
    """通用 CLI Agent 模板应完整填充动态路径、契约和请求。"""
    common = {
        "request": {"goal": {"task_id": "case-1"}},
        "instruction": "执行外部 instruction。",
        "output_path": tmp_path / "manager-result.json",
        "worktree": tmp_path / "worktree",
        "max_turns": "12",
    }
    idea = build_idea_prompt(
        **common,
        worktree_result_path=tmp_path / "worktree" / "famou_idea_result.json",
    )
    implement = build_implement_prompt(
        **common,
        worktree_result_path=tmp_path / "worktree" / "famou_agent_result.json",
    )
    idea_rank = build_idea_rank_prompt(
        **common,
        worktree_result_path=(
            tmp_path / "worktree" / "famou_idea_rank_result.json"
        ),
    )

    assert "case-1" in idea and "执行外部 instruction" in idea
    assert "case-1" in implement and "执行外部 instruction" in implement
    assert "case-1" in idea_rank and "执行外部 instruction" in idea_rank
    assert "建议最多进行 12" in idea and "建议最多进行 12" in implement
    assert "最多使用 12" in idea_rank
    assert "${" not in idea and "${" not in implement and "${" not in idea_rank


def test_cli_agent_prompt_v3_adds_validity_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """V3 必须同时约束 Idea 和 Implement 的 evaluator 使用边界。"""
    monkeypatch.setenv("FAMOU_IDEA_PROMPT_VERSION", "v3")
    monkeypatch.setenv("FAMOU_IMPLEMENT_PROMPT_VERSION", "v3")
    common = {
        "request": {"goal": {"task_id": "case-1"}},
        "instruction": "执行外部 instruction。",
        "output_path": tmp_path / "manager-result.json",
        "worktree": tmp_path / "worktree",
        "max_turns": "12",
    }
    idea = build_idea_prompt(
        **common,
        worktree_result_path=tmp_path / "worktree" / "famou_idea_result.json",
    )
    implement = build_implement_prompt(
        **common,
        worktree_result_path=tmp_path / "worktree" / "famou_agent_result.json",
    )

    assert "V3 定向合规边界" in idea
    assert "边界示例" in idea
    assert "解析测试文件名中的标识符" in idea
    assert "s41592-023-01940-w" not in idea
    assert "V3 定向合规边界" in implement
    assert "手工标记阈值" in implement
    assert "s42256-022-00518-z" not in implement


def test_benchmark_managed_worker_prompt_v3_is_selectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """非 CLI benchmark worker 也必须按环境变量选择 V3。"""
    monkeypatch.setenv("FAMOU_IDEA_PROMPT_VERSION", "v3")
    monkeypatch.setenv("FAMOU_IMPLEMENT_PROMPT_VERSION", "validity-v3")
    worker = PromptWorkerSet(
        {
            "goal": {"id": "prompt-v3", "name": "prompt-v3"},
            "workflow": {"type": "benchmark_managed"},
        },
        tmp_path / "workspace",
        llm=object(),
    )

    assert "V3 定向合规边界" in worker._prompt("idea_generator")
    assert "V3 定向合规边界" in worker._prompt("implement_agent")


def test_prompt_worker_missing_prompt_fails_closed(tmp_path: Path):
    """Prompt 文件缺失时不得静默回退为泛化任务文本。"""
    worker = PromptWorkerSet(
        {"goal": {"id": "missing-prompt", "name": "missing-prompt"}},
        tmp_path / "workspace",
        llm=object(),
        prompt_dir=tmp_path / "prompts",
    )
    with pytest.raises(FileNotFoundError, match="Prompt 文件不存在"):
        worker._prompt("idea_generator")


def test_prompt_worker_runs_cli_idea_rank_agent(tmp_path: Path):
    """Idea Rank Judge 应通过独立 Agent 角色返回结构化全序。"""

    goal = {
        "goal": {"id": "rank-agent", "name": "rank-agent"},
        "workflow": {"type": "benchmark_managed"},
        "workers": {
            "idea_rank": {
                "type": "agent",
                "runtime": "claude",
                "binary": str(FIXTURES / "agents" / "fake_role_cli.py"),
                "model": "test-model",
                "timeout_sec": 10,
                "max_turns": 5,
            }
        },
    }
    worker = PromptWorkerSet(goal, tmp_path / "workspace", llm=object())
    result = worker.rank_ideas(
        goal,
        [
            {"queue_item_id": "queue-a", "idea_id": "idea-a", "idea": {}},
            {"queue_item_id": "queue-b", "idea_id": "idea-b", "idea": {}},
        ],
        {"remaining_wall_time_sec": 1800, "resources": {"available_cpu": 4}},
    )

    assert [entry["queue_item_id"] for entry in result["ranking"]] == [
        "queue-a",
        "queue-b",
    ]
    assert list((tmp_path / "workspace" / "idea_rank_workspaces").glob("branches/*"))


def test_claude_wrapper_limits_idea_agent_tools(tmp_path: Path):
    """Idea 节点不能通过 Bash 越权执行实现或重型实验。"""
    common = {
        "runtime": "claude",
        "binary": "claude",
        "worktree": tmp_path,
        "title": "test",
        "model": "glm-5.2",
        "agent": None,
        "profile": None,
        "auto_approve": True,
        "extra_arg": [],
    }

    idea_argv = build_cli_argv(
        Namespace(**common, role="idea"),
        "prompt",
        tmp_path / "idea-last.txt",
    )
    idea_rank_argv = build_cli_argv(
        Namespace(**common, role="idea_rank"),
        "prompt",
        tmp_path / "idea-rank-last.txt",
    )
    implement_argv = build_cli_argv(
        Namespace(**common, role="implement"),
        "prompt",
        tmp_path / "implement-last.txt",
    )

    assert "--allowedTools=Read,Edit" in idea_argv
    assert "--allowedTools=Read,Edit" in idea_rank_argv
    assert "--allowedTools=Read,Write,Edit,Bash" in implement_argv
    assert "--no-session-persistence" not in implement_argv

    resumed_argv = build_cli_argv(
        Namespace(**common, role="implement"),
        "fix the previous candidate",
        tmp_path / "implement-resumed-last.txt",
        resume_session=True,
        session_id="00000000-0000-0000-0000-000000000001",
    )
    assert "--resume" in resumed_argv
    assert "00000000-0000-0000-0000-000000000001" in resumed_argv


def test_codex_wrapper_uses_branch_local_home_when_needed(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    logs_dir = tmp_path / "logs"
    env = _runtime_environment(
        Namespace(runtime="codex", logs_dir=str(logs_dir))
    )
    assert env["CODEX_HOME"] == str(logs_dir / "codex_home")
    assert (logs_dir / "codex_home").is_dir()


def test_command_implement_agent_can_run_opencode_preset_with_fake_binary(tmp_path: Path):
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, sys",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "(worktree / 'method.py').write_text(",
                "    \"import argparse, json\\n\"",
                "    \"parser = argparse.ArgumentParser()\\n\"",
                "    \"parser.add_argument('--output', required=True)\\n\"",
                "    \"args = parser.parse_args()\\n\"",
                "    \"json.dump({'prediction': 1}, open(args.output, 'w'))\\n\",",
                "    encoding='utf-8',",
                ")",
                "pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_OUTPUT']).write_text(",
                "    json.dumps({",
                "        'status': 'implemented',",
                "        'title': 'fake opencode method',",
                "        'method_summary': 'created by fake opencode preset binary',",
                "        'entrypoint': 'method.py',",
                "        'files': [{'path': 'method.py'}],",
                "        'experiment_plan': ['run public eval'],",
                "        'limitations': ['fake binary'],",
                "    }),",
                "    encoding='utf-8',",
                ")",
                "print(json.dumps({'fake_cli_args': sys.argv}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)

    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_1")
    request = ImplementRequest(
        goal={
            "goal": {"name": "safe_goal"},
            "benchmarks": [{"name": "public_only"}],
        },
        idea={"id": "idea_1", "title": "A", "mechanism": "B"},
        workspace=workspace,
        sandbox=LocalSandbox(workspace.root),
        instruction="Implement a tiny method.",
    )
    agent = CommandImplementAgent(
        {
            "runtime": "opencode",
            "binary": str(fake_bin),
            "model": "fake-model",
            "timeout_sec": 20,
        }
    )

    result = agent.implement(request)
    resumed_result = agent.implement(request)

    assert result.status == "implemented"
    assert resumed_result.status == "implemented"
    assert result.output["entrypoint"] == "method.py"
    assert (workspace.worktree / "method.py").is_file()
    request_files = list(workspace.logs.glob("implement_agent_*.request.json"))
    assert request_files
    serialized_request = request_files[0].read_text(encoding="utf-8")
    assert "hidden_evaluator" in serialized_request
    assert "official_eval_cmd" not in serialized_request
    assert list(workspace.logs.glob("*.opencode_implement_prompt.md"))
    wrapper_meta = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in workspace.logs.glob("*.opencode_wrapper_meta.json")
    ]
    assert any("--continue" in item["command"] for item in wrapper_meta)
    session = json.loads(
        (workspace.logs / "opencode_implement_session.json").read_text(
            encoding="utf-8"
        )
    )
    assert session["resume_count"] == 1


def test_command_implement_agent_can_resume_kimi_code_session_with_fake_binary(
    tmp_path: Path,
):
    fake_bin = tmp_path / "kimi"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, sys",
                "args = sys.argv[1:]",
                "assert '--output-format' in args and 'stream-json' in args",
                "assert '--prompt' in args and '--print' not in args",
                "assert '--auto' not in args",
                "marker = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE']) / 'kimi_args.json'",
                "marker.write_text(json.dumps(args), encoding='utf-8')",
                "pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_OUTPUT']).write_text(",
                "    json.dumps({",
                "        'status': 'implemented',",
                "        'title': 'fake kimi method',",
                "        'method_summary': 'created by fake kimi code',",
                "        'entrypoint': 'method.py',",
                "        'files': [{'path': 'method.py'}],",
                "        'experiment_plan': ['run public eval'],",
                "        'limitations': ['fake binary'],",
                "    }),",
                "    encoding='utf-8',",
                ")",
                "print(json.dumps({'type': 'session.started', 'session_id': 'kimi-session-1'}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)

    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_kimi")
    request = ImplementRequest(
        goal={"goal": {"name": "safe_goal"}, "benchmarks": [{"name": "public_only"}]},
        idea={"id": "idea_1", "title": "A", "mechanism": "B"},
        workspace=workspace,
        sandbox=LocalSandbox(workspace.root),
        instruction="Implement a tiny method.",
    )
    agent = CommandImplementAgent(
        {
            "runtime": "kimi-code",
            "binary": str(fake_bin),
            "model": "kimi-k3",
            "timeout_sec": 20,
        }
    )

    first = agent.implement(request)
    second = agent.implement(request)

    assert first.status == "implemented"
    assert second.status == "implemented"
    session = json.loads(
        (workspace.logs / "kimi-code_implement_session.json").read_text(
            encoding="utf-8"
        )
    )
    assert session["session_id"] == "kimi-session-1"
    assert session["resume_count"] == 1
    metas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(workspace.logs.glob("*.kimi-code_wrapper_meta.json"))
    ]
    assert len(metas) == 2
    assert "--session" in metas[1]["command"]
    assert "kimi-session-1" in metas[1]["command"]
    assert "--print" not in metas[0]["command"]


def test_command_implement_agent_parks_after_explicit_submission(tmp_path: Path):
    """显式提交后应冻结本回合结果并尽快释放 Implement 进程。"""

    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import os, pathlib, subprocess, sys, time",
                "worktree = pathlib.Path(os.environ['FAMOU_IMPLEMENT_AGENT_WORKTREE'])",
                "(worktree / 'method.py').write_text('print(1)\\n', encoding='utf-8')",
                "subprocess.run([",
                "    sys.executable, os.environ['FAMOU_SUBMIT_CANDIDATE'],",
                "    '--entrypoint', 'method.py',",
                "    '--title', 'explicit candidate',",
                "    '--summary', 'submitted before the agent exits',",
                "    '--file', 'method.py',",
                "], check=True)",
                "(worktree / 'method.py').write_text('print(2)\\n', encoding='utf-8')",
                "time.sleep(30)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)

    workspace = AgentWorkspace.create(tmp_path / "goal", "branch_submit")
    request = ImplementRequest(
        goal={"goal": {"name": "safe_goal"}},
        idea={"id": "idea_submit", "title": "A", "mechanism": "B"},
        workspace=workspace,
        sandbox=LocalSandbox(workspace.root),
        instruction="提交一个最小方法。",
        metadata={"implementation_contract": {"entrypoint": "method.py"}},
    )
    agent = CommandImplementAgent(
        {
            "runtime": "opencode",
            "binary": str(fake_bin),
            "timeout_sec": 20,
            "submission_grace_sec": 0.2,
            "require_submit_candidate": True,
        }
    )

    started = time.monotonic()
    result = agent.implement(request)
    elapsed = time.monotonic() - started

    assert result.status == "implemented"
    assert result.output["submission_id"].startswith("submission_")
    assert result.output["entrypoint"] == "method.py"
    submitted_worktree = Path(result.output["submitted_worktree"])
    assert submitted_worktree.joinpath("method.py").read_text(encoding="utf-8") == "print(1)\n"
    assert workspace.worktree.joinpath("method.py").read_text(encoding="utf-8") == "print(2)\n"
    assert elapsed < 5
    wrapper_meta = json.loads(
        next(workspace.logs.glob("*.opencode_wrapper_meta.json")).read_text(
            encoding="utf-8"
        )
    )
    assert wrapper_meta["submitted"] is True
    assert wrapper_meta["parked_after_submission"] is True
    assert wrapper_meta["returncode"] != 0
    assert wrapper_meta["deadline_heartbeat"]["enabled"] is False
    assert len(wrapper_meta["activation_commands"]) == 1


def test_naturebench_run_and_public_check_adapters(tmp_path: Path):
    """NatureBench 薄适配器应遵守环境变量和公开格式契约。"""
    adapter_dir = EXAMPLES / "naturebench"
    task_dir = tmp_path / "s41592-022-01709-7"
    problem_dir = task_dir / "problem"
    (problem_dir / "data").mkdir(parents=True)
    (problem_dir / "README.md").write_text("public task", encoding="utf-8")
    method_dir = tmp_path / "method"
    method_dir.mkdir()
    method_dir.joinpath("run.py").write_text(
        "import csv, os\n"
        "from pathlib import Path\n"
        "for name in ('bone_marrow','cross_species','murine_spleen','pbmc'):\n"
        "    path = Path(os.environ['OUTPUT_DIR']) / name / 'matching.csv'\n"
        "    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    with path.open('w', newline='') as f:\n"
        "        writer = csv.writer(f); writer.writerow(['x_index','y_index']); writer.writerow([0,0])\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    run_script = adapter_dir / "run_task.py"
    process = subprocess.run(
        [
            sys.executable,
            str(run_script),
            "--task-dir",
            str(task_dir),
            "--method-dir",
            str(method_dir),
            "--run-dir",
            str(run_dir),
            "--runtime",
            "local",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    run_result = json.loads(process.stdout.strip().splitlines()[-1])
    assert run_result["valid"] is True

    check_script = adapter_dir / "check_submission.py"
    process = subprocess.run(
        [
            sys.executable,
            str(check_script),
            "--task-dir",
            str(task_dir),
            "--submission-dir",
            run_result["artifact"],
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    check_result = json.loads(process.stdout.strip().splitlines()[-1])
    assert check_result["valid"] is True
    assert check_result["diagnostics_public"]["checked_items"] == 4


def test_naturebench_public_contract_uses_staged_problem_dir(tmp_path: Path):
    """Run-root evaluator calls must validate IDs below ``problem/``."""
    run_dir = tmp_path / "s42256-023-00628-2"
    test_dir = run_dir / "problem" / "data" / "band_gap" / "test"
    test_dir.mkdir(parents=True)
    ids = [f"structure_{index:04d}" for index in range(2037)]
    for structure_id in ids:
        (test_dir / f"{structure_id}.graphdata").touch()
    submission_dir = tmp_path / "submission"
    prediction_dir = submission_dir / "band_gap"
    prediction_dir.mkdir(parents=True)
    (prediction_dir / "predictions.json").write_text(
        json.dumps({structure_id: 0.0 for structure_id in ids}),
        encoding="utf-8",
    )

    assert _validate_public_submission_contract(run_dir, submission_dir) == []


def test_naturebench_official_adapter_reuses_benchmark_scoring(tmp_path: Path):
    """正式适配器应直接返回 NatureBench 的 AutoSOTA 聚合指标。"""
    naturebench_root = Path(
        "/path/to/workspace/opensource/NatureBench"
    )
    task_dir = (
        naturebench_root
        / "data"
        / "naturebench_data"
        / "tasks"
        / "s41592-022-01709-7"
    )
    if not task_dir.is_dir():
        pytest.skip("本机没有 NatureBench 测试任务")

    submission = tmp_path / "submission"
    for instance in ("bone_marrow", "cross_species", "murine_spleen", "pbmc"):
        path = submission / instance / "matching.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x_index,y_index\n0,0\n", encoding="utf-8")

    script = EXAMPLES / "naturebench" / "evaluate_task.py"
    process = subprocess.run(
        [
            sys.executable,
            str(script),
            "--task-dir",
            str(task_dir),
            "--submission-dir",
            str(submission),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout.strip().splitlines()[-1])
    assert result["valid"] is True
    assert isinstance(result["official_metrics"]["aggregate_improvement"], float)
    assert result["diagnostics_public"]["scoring"] == "naturebench_autosota"
    assert result["diagnostics_public"]["evaluation_completed"] is True
    assert result["diagnostics_public"]["score_available"] is True
    assert result["diagnostics_public"]["validity_judge"] == (
        "not_run_in_numeric_evaluator"
    )
    assert result["extra_public"]["task_name"] == "s41592-022-01709-7"
    assert result["extra_public"]["aggregate_improvement"] == (
        result["official_metrics"]["aggregate_improvement"]
    )
    assert set(result["extra_public"]["per_instance_improvement"]) == {
        "bone_marrow",
        "cross_species",
        "murine_spleen",
        "pbmc",
    }
    assert set(result["extra_public"]["raw_scores"]) == {
        "bone_marrow",
        "cross_species",
        "murine_spleen",
        "pbmc",
    }


def test_naturebench_percentage_metric_is_normalized_without_mutating_raw(
    tmp_path: Path,
):
    """百分比 SOTA 不得直接和 evaluator 返回的准确率小数比较。"""

    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "performance_entries": [
                    {
                        "dataset_name": "classification",
                        "metrics": [
                            {
                                "name": "Accuracy",
                                "is_primary": True,
                                "unit": "%",
                            }
                        ],
                    },
                    {
                        "dataset_name": "regression",
                        "metrics": [
                            {
                                "name": "MSE",
                                "is_primary": True,
                                "unit": None,
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    raw_scores = {
        "classification": {"Accuracy": 0.9934},
        "regression": {"MSE": 0.08},
    }

    normalized, records = _normalize_metric_units(
        raw_scores,
        {
            "classification": {"metric": "Accuracy", "sota": 99.72},
            "regression": {"metric": "MSE", "sota": 0.65},
        },
        metadata,
    )

    assert raw_scores["classification"]["Accuracy"] == pytest.approx(0.9934)
    assert normalized["classification"]["Accuracy"] == pytest.approx(99.34)
    assert normalized["regression"]["MSE"] == pytest.approx(0.08)
    assert records == [
        {
            "instance": "classification",
            "metric": "Accuracy",
            "from_unit": "fraction",
            "to_unit": "%",
            "original_value": pytest.approx(0.9934),
            "normalized_value": pytest.approx(99.34),
        }
    ]


def test_naturebench_incomplete_primary_instances_are_not_valid_candidates():
    """实例缺失、错误或主指标为空时不能用失败罚分参与最佳选择。"""

    failures = _validate_primary_scores(
        {
            "complete": {"Primary Score": 0.8},
            "errored": {"Primary Score": None, "error": "missing output.csv"},
            "missing_metric": {"secondary": 1.0},
        },
        {
            "complete": {"metric": "primary_score", "sota": 0.9},
            "errored": {"metric": "primary_score", "sota": 0.9},
            "missing_metric": {"metric": "primary_score", "sota": 0.9},
            "missing_instance": {"metric": "primary_score", "sota": 0.9},
        },
    )

    assert [failure["kind"] for failure in failures] == [
        "instance_error",
        "missing_primary_metric",
        "missing_instance",
    ]
    assert failures[0]["errors"][0]["error"] == "missing output.csv"
