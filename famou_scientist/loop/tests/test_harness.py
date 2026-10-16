"""外部 benchmark Agent Harness 的隔离闭环测试。"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

from famou_scientist import cmdline
from famou_scientist.loop.utils import atomic_write_json
from famou_scientist.loop.harness.evaluator import (
    EvaluatorError,
    FileEvaluatorClient,
    HttpEvaluatorClient,
)
from famou_scientist.loop.harness.runtime import (
    BenchmarkHarness,
    HarnessConfig,
    _summary_status,
)
from famou_scientist.loop.integrations.naturebench import evaluator_worker
from famou_scientist.loop.integrations.naturebench.trajectory_adapter import (
    NatureBenchTrajectoryAdapter,
)
from famou_scientist.loop.examples.naturebench.fmjob.prepare_run import prepare_run
from famou_scientist.loop.examples.scimodelingbench.fmjob.prepare_run import (
    _stage_claude_settings as stage_scimodelingbench_claude_settings,
)
from famou_scientist.loop.storage.state import ResearchState


def test_drained_wall_time_budget_is_successful_completion():
    assert _summary_status(
        {
            "status": "stopped",
            "termination_reason": "wall_time_budget_exhausted",
            "shutdown": {"phase": "evaluation_drain_completed"},
        }
    ) == "completed"
    assert _summary_status(
        {"status": "stopped", "termination_reason": "stopped_by_user"}
    ) == "stopped"


FIXTURES = Path(__file__).parent / "fixtures"


class SequenceEvaluator:
    """按顺序返回固定分数的测试 evaluator。"""

    def __init__(
        self,
        scores: list[float],
        *,
        judge_verdict: dict[str, object] | None = None,
    ):
        """保存待返回分数序列。"""
        self.scores = list(scores)
        self.index = 0
        self.closed = False
        self.judge_verdict = judge_verdict or {
            "is_valid": True,
            "reason": "测试方案由真实拟合方法生成。",
            "model": "fake-judge",
        }

    def evaluate(self, *, attempt_id: str) -> dict[str, object]:
        """返回当前 attempt 对应的下一条固定分数。"""
        score = self.scores[self.index]
        self.index += 1
        return {
            "request_id": f"request-{self.index}",
            "attempt_id": attempt_id,
            "valid": True,
            "metrics": {"aggregate_improvement": score},
            "stdout": "",
            "stderr": "",
            "extra": {},
        }

    def request(self, *, operation: str, attempt_id: str) -> dict[str, object]:
        """实现 Evaluator Adapter 使用的统一可信操作接口。"""
        if operation == "evaluate":
            return self.evaluate(attempt_id=attempt_id)
        if operation == "validity_judge":
            return self.validity_judge(attempt_id=attempt_id)
        raise ValueError(f"unknown evaluator operation: {operation}")

    def close(self) -> None:
        """记录 Harness 已正常关闭 evaluator。"""
        self.closed = True

    def validity_judge(self, *, attempt_id: str) -> dict[str, object]:
        """返回与最佳 ExpBank 编号绑定的固定 Judge verdict。"""
        return {
            "request_id": "judge-request",
            "attempt_id": attempt_id,
            "valid": True,
            "judge": {**self.judge_verdict, "expbank_attempt_id": attempt_id},
        }


def test_harness_does_not_invent_evaluation_limits(tmp_path: Path):
    """Bench 未声明次数上限时应仅依靠墙钟预算和队列背压。"""
    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="unlimited-task",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        max_wall_time_hours=4,
        pricing={
            "currency": "USD",
            "per_million_tokens": {
                "input": 1.4,
                "cache_creation": 1.4,
                "cache_read": 0.26,
                "output": 4.4,
            },
            "source": "user_confirmed",
            "effective_at": "2026-08-11",
        },
    )
    harness = BenchmarkHarness(config, SequenceEvaluator([]))

    goal = harness._goal_doc()
    summary_worker = goal["workers"]["experience_summary"]
    assert summary_worker["role"] == "experience_summary"
    assert summary_worker["max_turns"] == 30
    assert summary_worker["timeout_sec"] == 600
    assert "cancel_file" not in summary_worker
    constraints = goal["constraints"]
    assert "max_benchmark_attempts" not in constraints
    assert "max_evaluator_submissions" not in constraints
    assert constraints["max_official_evaluations_per_actor"] is None
    assert goal["benchmark_task"]["execution_limits"]["canonical_timeout_sec"] == 3600
    criteria = goal["benchmark_task"]["contract"]["score_interpretation"]
    assert criteria["metric"] == "aggregate_improvement"
    assert criteria["primary_target"] == ["match_sota", "surpass_sota"]
    assert "Match-SOTA" in goal["objective_brief"]["primary_goal"]
    assert goal["benchmarks"][0]["score_interpretation"] == criteria
    assert goal["infra"]["scheduling"]["search_policy"] == {
        "type": "pairwise_improve",
        "enabled": True,
    }
    assert goal["infra"]["observability"]["pricing"][
        "per_million_tokens"
    ]["cache_read"] == 0.26

    state = ResearchState(config.run_dir).init(goal)
    assert state["research_state"]["evaluator_budget"] == {
        "max_submissions": None,
        "used_submissions": 0,
    }
    assert state["research_state"]["goal"]["infra"]["observability"] == goal[
        "infra"
    ]["observability"]


def test_harness_uses_dynamic_candidate_memory_requests(tmp_path: Path):
    """主存应由 Broker 动态装箱，不能按最大评测并发静态均分。"""
    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="memory-isolation",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        max_parallel_evaluations=5,
        available_memory_gib=128,
    )

    harness = BenchmarkHarness(config, SequenceEvaluator([]))

    resources = harness._goal_doc()["infra"]["resources"]
    assert harness.adapter_context.options["experiment_memory_limit_bytes"] is None
    assert harness.benchmark_facility.runner.memory_limit_bytes is None
    assert resources["available_memory_gib"] == 128
    assert resources["host_memory_reserve_gib"] == pytest.approx(32)
    assert resources["allocatable_memory_gib"] == pytest.approx(96)
    assert resources["agent_process_memory_limit_gib"] == pytest.approx(12.8)
    assert harness._agent_config(role="idea")[
        "process_memory_limit_bytes"
    ] == int(12.8 * 1024**3)
    assert harness._agent_config(role="implement")[
        "process_memory_limit_bytes"
    ] == int(12.8 * 1024**3)
    assert "canonical_memory_limit_gib" not in resources


def test_harness_allows_explicit_agent_process_memory_limit(tmp_path: Path):
    """特殊任务可以显式覆盖自动计算的单 Agent 主存上限。"""

    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="explicit-agent-memory",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        available_memory_gib=256,
        agent_process_memory_limit_gib=24,
    )

    harness = BenchmarkHarness(config, SequenceEvaluator([]))

    assert harness._goal_doc()["infra"]["resources"][
        "agent_process_memory_limit_gib"
    ] == 24
    assert harness._agent_config(role="implement")[
        "process_memory_limit_bytes"
    ] == 24 * 1024**3


def test_implement_activation_budget_is_independent_of_other_roles(tmp_path: Path):
    """加长 Implement 激活不得顺带加长 idea/idea_rank —— 那是另一个变量。

    20260920 实测 3600 秒下 43/181 次 attempt 是跑满被掐的，所以要把 Implement
    单独放到 80 分钟；但 idea agent 通常几分钟就结束，跟着放大没有收益，还会让
    「这批改了什么」变成两件事。
    """

    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="implement-budget",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        agent_timeout_sec=3600,
        implement_agent_timeout_sec=4800,
        implement_deadline_heartbeat=True,
        implement_deadline_heartbeat_after_sec=3200,
    )
    config.validate()

    harness = BenchmarkHarness(config, SequenceEvaluator([]))

    assert harness._agent_config(role="implement")["timeout_sec"] == 4800
    assert harness._agent_config(role="idea")["timeout_sec"] == 3600
    # 心跳阈值只需小于 Implement 的上限；3200 > agent_timeout_sec 不该被拒。
    assert harness._agent_config(role="implement")["deadline_heartbeat"][
        "trigger_after_sec"
    ] == 3200


def test_implement_activation_budget_defaults_to_shared_timeout(tmp_path: Path):
    """不显式配置时必须逐字回落到 agent_timeout_sec，不能悄悄换默认值。"""

    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="implement-budget-default",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        agent_timeout_sec=1234,
    )
    config.validate()

    harness = BenchmarkHarness(config, SequenceEvaluator([]))

    assert harness._agent_config(role="implement")["timeout_sec"] == 1234


def test_deadline_heartbeat_must_fit_inside_implement_activation(tmp_path: Path):
    """心跳晚于 Implement 上限等于没有心跳，必须在配置期就拒掉。"""

    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="implement-budget-invalid",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        agent_timeout_sec=7200,
        implement_agent_timeout_sec=3000,
        implement_deadline_heartbeat=True,
        implement_deadline_heartbeat_after_sec=3200,
    )

    with pytest.raises(ValueError, match="implement_deadline_heartbeat_after_sec"):
        config.validate()


def test_cli_harness_requires_explicit_agent_model(tmp_path: Path):
    """正式 CLI Agent 运行不得静默使用产品默认模型。"""

    problem = tmp_path / "run" / "problem"
    problem.mkdir(parents=True)
    config = HarnessConfig(
        task_id="explicit-model",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
    )

    with pytest.raises(ValueError, match="显式指定模型"):
        config.validate()


def test_prepare_run_copies_only_public_problem(tmp_path: Path):
    """验证 Agent run 使用真实公开副本且不包含 evaluator 或 GT。"""
    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data" / "naturebench_data" / "tasks" / "case-1"
    (task / "problem" / "data").mkdir(parents=True)
    (task / "problem" / "README.md").write_text("public", encoding="utf-8")
    (task / "problem" / "data" / "input.txt").write_text("x", encoding="utf-8")
    (task / "evaluation" / "ground_truth").mkdir(parents=True)
    (task / "evaluation" / "ground_truth" / "answer.txt").write_text(
        "secret", encoding="utf-8"
    )
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )
    (naturebench / "judge_core").mkdir()
    (naturebench / "judge_core" / "runner.py").write_text(
        "# trusted judge\n", encoding="utf-8"
    )
    (naturebench / "agent").mkdir()
    (naturebench / "agent" / "adapter.py").write_text(
        "# trusted adapter registry\n", encoding="utf-8"
    )
    famou_source = tmp_path / "source"
    (famou_source / "famou_scientist").mkdir(parents=True)
    (famou_source / "famou_scientist" / "__init__.py").write_text("", encoding="utf-8")
    for trusted_only in (
        "evaluator_worker.py",
        "evaluate_task.py",
        "judge_adapter.py",
        "trajectory_adapter.py",
    ):
        (famou_source / "famou_scientist" / trusted_only).write_text(
            "raise RuntimeError('trusted only')\n",
            encoding="utf-8",
        )
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_AUTH_TOKEN": "test-secret",
                "ANTHROPIC_BASE_URL": "https://example.invalid",
                    "JUDGE_MODEL": "judge-model",
                    "JUDGE_API_KEY": "judge-secret",
                    "UNRELATED_SECRET": "must-not-copy",
                },
                "hooks": {"must": "not-copy"},
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "run-1"
    trusted_judge_settings = run_dir / "trusted" / "judge_settings.json"

    prepare_run(
        naturebench_root=naturebench,
        task_id="case-1",
        famou_source=famou_source,
        run_dir=run_dir,
        claude_settings=claude_settings,
        judge_settings_source=claude_settings,
        trusted_judge_settings=trusted_judge_settings,
    )

    assert (run_dir / "problem" / "README.md").read_text() == "public"
    public_snapshot = run_dir / "famou-scientist"
    assert not list((run_dir / "problem").rglob("ground_truth"))
    assert not list((run_dir / "problem").rglob("evaluation"))
    assert not list(public_snapshot.rglob("evaluator_worker.py"))
    assert not list(public_snapshot.rglob("evaluate_task.py"))
    assert not list(public_snapshot.rglob("judge_adapter.py"))
    assert not list(public_snapshot.rglob("trajectory_adapter.py"))
    # 隐藏 evaluator 与 GT 保留在同一 fm-job 的 root-only 可信目录中。
    trusted_root = run_dir / "trusted"
    assert (trusted_root / "naturebench/eval_service.py").is_file()
    assert (trusted_root / "naturebench/judge_core/runner.py").is_file()
    assert (trusted_root / "naturebench/agent/adapter.py").is_file()
    assert (
        trusted_root
        / "naturebench/data/naturebench_data/tasks/case-1/evaluation/ground_truth/answer.txt"
    ).read_text(encoding="utf-8") == "secret"
    assert list(trusted_root.rglob("evaluator_worker.py"))
    assert trusted_root.stat().st_mode & 0o777 == 0o700
    assert (run_dir / "controller").stat().st_mode & 0o777 == 0o700
    assert (run_dir / "agent_control").stat().st_mode & 0o777 == 0o755
    manifest = json.loads(
        (run_dir / "controller" / "public_problem_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert {item["path"] for item in manifest["files"]} == {
        "README.md",
        "data_description.md",
        "data/input.txt",
    }
    staged_settings_path = run_dir / "agent_home/.claude/settings.json"
    staged_settings = json.loads(staged_settings_path.read_text(encoding="utf-8"))
    assert staged_settings == {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "test-secret",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
        }
    }
    assert staged_settings_path.stat().st_mode & 0o777 == 0o600
    assert (run_dir / "agent_home").stat().st_mode & 0o777 == 0o700
    if os.geteuid() == 0:
        assert (run_dir / "agent_home").stat().st_uid == 10001
    trusted_settings = json.loads(trusted_judge_settings.read_text(encoding="utf-8"))
    assert trusted_settings == {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "test-secret",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "JUDGE_MODEL": "judge-model",
            "JUDGE_API_KEY": "judge-secret",
        }
    }
    assert trusted_judge_settings.stat().st_mode & 0o777 == 0o600


def test_prepare_run_reuses_audited_read_only_problem_snapshot(tmp_path: Path):
    """超大任务可共享旧 Run 的公开快照，而不重复遍历或复制数据树。"""

    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data" / "naturebench_data" / "tasks" / "case-large"
    (task / "problem").mkdir(parents=True)
    (task / "evaluation" / "ground_truth").mkdir(parents=True)
    (task / "evaluation" / "ground_truth" / "answer.txt").write_text(
        "secret", encoding="utf-8"
    )
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )
    famou_source = tmp_path / "source"
    (famou_source / "famou_scientist").mkdir(parents=True)
    (famou_source / "famou_scientist" / "__init__.py").write_text(
        "", encoding="utf-8"
    )

    prior_run = tmp_path / "runs" / "prior"
    snapshot = prior_run / "problem"
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "README.md").write_text("large public task", encoding="utf-8")
    (snapshot / "data_description.md").write_text("public data", encoding="utf-8")
    (snapshot / "data" / "input.bin").write_bytes(b"public")
    snapshot.chmod(0o555)
    manifest = prior_run / "controller" / "public_problem_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "problem_dir": "problem",
                "files": [
                    {"path": "README.md", "size": 17},
                    {"path": "data/input.bin", "size": 6},
                ],
            }
        ),
        encoding="utf-8",
    )

    run_dir = prior_run / "reruns" / "run-2"
    prepare_run(
        naturebench_root=naturebench,
        task_id="case-large",
        famou_source=famou_source,
        run_dir=run_dir,
        problem_staging_mode="auto",
        problem_snapshot_source=snapshot,
        problem_snapshot_manifest=manifest,
    )

    assert not (run_dir / "problem").is_symlink()
    assert (run_dir / "problem" / "data" / "input.bin").read_bytes() == b"public"
    assert (run_dir / "problem" / "data" / "input.bin").stat().st_ino == (
        snapshot / "data" / "input.bin"
    ).stat().st_ino
    assert (run_dir / "controller" / "public_problem_manifest.json").read_text() == (
        manifest.read_text()
    )
    staging = json.loads((run_dir / "controller" / "staging.json").read_text())
    assert staging["problem_staging_mode"] == "snapshot_hardlink"
    assert staging["archive_materialization"]["status"] == "shared_audited_snapshot"
    trusted_task = (
        run_dir
        / "trusted/naturebench/data/naturebench_data/tasks/case-large"
    )
    assert (trusted_task / "problem").is_symlink()
    assert (trusted_task / "evaluation/ground_truth/answer.txt").read_text() == "secret"


def test_agent_snapshot_loads_naturebench_without_trusted_modules(tmp_path: Path):
    """Agent 快照移除可信模块后仍应能加载公开 NatureBench 插件。"""
    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data" / "naturebench_data" / "tasks" / "case-1"
    (task / "problem").mkdir(parents=True)
    (task / "problem" / "README.md").write_text("public", encoding="utf-8")
    (task / "evaluation").mkdir()
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )

    run_dir = tmp_path / "runs" / "run-1"
    source_root = Path(__file__).resolve().parents[3]
    prepare_run(
        naturebench_root=naturebench,
        task_id="case-1",
        famou_source=source_root,
        run_dir=run_dir,
    )

    snapshot_root = run_dir / "famou-scientist"
    assert (run_dir / "agent_home").is_dir()
    assert (run_dir / "agent_home").stat().st_mode & 0o777 == 0o700
    assert not list(snapshot_root.rglob("judge_adapter.py"))
    assert not list(snapshot_root.rglob("trajectory_adapter.py"))
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from famou_scientist.loop.plugins.registry import load_adapter; "
                "assert load_adapter('benchmark', 'naturebench').name == 'naturebench'"
            ),
        ],
        cwd=run_dir,
        env={**os.environ, "PYTHONPATH": str(snapshot_root)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr


def test_prepare_run_hardlinks_large_public_problem_once(tmp_path: Path):
    """同盘超大题面应复用 inode，GT 与 evaluator 仍只存在于 trusted。"""

    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data/naturebench_data/tasks/case-hardlink"
    (task / "problem/data").mkdir(parents=True)
    public_readme = task / "problem/README.md"
    public_input = task / "problem/data/input.txt"
    public_readme.write_text("public", encoding="utf-8")
    public_input.write_text("x", encoding="utf-8")
    (task / "evaluation/ground_truth").mkdir(parents=True)
    source_gt = task / "evaluation/ground_truth/answer.txt"
    source_gt.write_text("secret", encoding="utf-8")
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )
    famou_source = tmp_path / "source"
    (famou_source / "famou_scientist").mkdir(parents=True)
    (famou_source / "famou_scientist/__init__.py").write_text(
        "", encoding="utf-8"
    )
    run_dir = naturebench / "runs/run-hardlink"

    prepare_run(
        naturebench_root=naturebench,
        task_id="case-hardlink",
        famou_source=famou_source,
        run_dir=run_dir,
        problem_staging_mode="auto",
        manifest_hash_max_file_bytes=2,
        manifest_hash_total_budget_bytes=2,
    )

    public_staged = run_dir / "problem/README.md"
    trusted_problem = (
        run_dir
        / "trusted/naturebench/data/naturebench_data/tasks/case-hardlink/problem/README.md"
    )
    trusted_gt = (
        run_dir
        / "trusted/naturebench/data/naturebench_data/tasks/case-hardlink/evaluation/ground_truth/answer.txt"
    )
    assert trusted_problem.parent.is_symlink()
    assert trusted_problem.parent.resolve() == (run_dir / "problem").resolve()
    assert public_readme.stat().st_ino == public_staged.stat().st_ino
    assert public_readme.stat().st_ino == trusted_problem.stat().st_ino
    assert source_gt.stat().st_ino != trusted_gt.stat().st_ino
    assert not (run_dir / "problem/evaluation").exists()
    assert run_dir.joinpath("problem").stat().st_mode & 0o777 == 0o555
    assert run_dir.joinpath("trusted").stat().st_mode & 0o777 == 0o700
    assert public_staged.stat().st_mode & 0o002 == 0

    staging = json.loads(
        (run_dir / "controller/staging.json").read_text(encoding="utf-8")
    )
    assert staging["problem_staging_mode"] == "hardlink"
    assert staging["trusted_problem_mode"] == "symlink_to_public_snapshot"
    manifest = json.loads(
        (run_dir / "controller/public_problem_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    records = {item["path"]: item for item in manifest["files"]}
    assert records["README.md"]["sha256"] is None
    assert records["README.md"]["hash_status"] == "skipped_file_size"
    assert records["data/input.txt"]["hash_status"] == "hashed"


def test_prepare_run_repairs_packaged_evaluator_binary_execute_bit(tmp_path: Path):
    """可信快照应恢复上游 ELF evaluator 工具遗漏的 owner execute 位。"""

    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data/naturebench_data/tasks/case-binary"
    (task / "problem").mkdir(parents=True)
    (task / "problem/README.md").write_text("public", encoding="utf-8")
    (task / "evaluation").mkdir()
    binary = task / "evaluation/qvina02"
    binary.write_bytes(b"\x7fELFfake-binary")
    binary.chmod(0o644)
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )
    famou_source = tmp_path / "source"
    (famou_source / "famou_scientist").mkdir(parents=True)
    (famou_source / "famou_scientist/__init__.py").write_text("", encoding="utf-8")
    run_dir = tmp_path / "run"

    prepare_run(
        naturebench_root=naturebench,
        task_id="case-binary",
        famou_source=famou_source,
        run_dir=run_dir,
    )

    trusted_binary = (
        run_dir
        / "trusted/naturebench/data/naturebench_data/tasks/case-binary/evaluation/qvina02"
    )
    assert trusted_binary.stat().st_mode & stat.S_IXUSR
    staging = json.loads(
        (run_dir / "controller/staging.json").read_text(encoding="utf-8")
    )
    assert staging["repaired_trusted_evaluator_executables"] == ["qvina02"]


def test_prepare_run_materializes_archive_and_repairs_public_judge_context(
    tmp_path: Path,
):
    """压缩数据只在 Run 中展开，且 Agent 与 Judge 共享同一公开快照。"""

    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data/naturebench_data/tasks/case-archive"
    archive_dir = task / "problem/data_archives"
    archive_dir.mkdir(parents=True)
    (task / "problem/README.md").write_text(
        "# Public task\n\nDataset details are public.\n",
        encoding="utf-8",
    )
    payload = tmp_path / "payload/data"
    payload.mkdir(parents=True)
    (payload / "input.txt").write_text("public-data", encoding="utf-8")
    with tarfile.open(archive_dir / "data.tar.gz", "w:gz") as archive:
        archive.add(payload, arcname="data")
    (task / "evaluation").mkdir()
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )
    famou_source = tmp_path / "source"
    (famou_source / "famou_scientist").mkdir(parents=True)
    (famou_source / "famou_scientist/__init__.py").write_text("", encoding="utf-8")
    run_dir = naturebench / "runs/run-archive"

    prepare_run(
        naturebench_root=naturebench,
        task_id="case-archive",
        famou_source=famou_source,
        run_dir=run_dir,
        problem_staging_mode="auto",
    )

    public_data = run_dir / "problem/data/input.txt"
    trusted_data = (
        run_dir
        / "trusted/naturebench/data/naturebench_data/tasks/case-archive/problem/data/input.txt"
    )
    assert public_data.read_text(encoding="utf-8") == "public-data"
    assert public_data.stat().st_ino == trusted_data.stat().st_ino
    assert not (run_dir / "problem/data_archives").exists()
    assert not trusted_data.parents[1].joinpath("data_archives").exists()
    assert (task / "problem/data_archives/data.tar.gz").is_file()
    assert not (task / "problem/data").exists()
    description = run_dir / "problem/data_description.md"
    assert "Famou staging fallback" in description.read_text(encoding="utf-8")

    staging = json.loads(
        (run_dir / "controller/staging.json").read_text(encoding="utf-8")
    )
    assert staging["archive_materialization"]["status"] == "extracted"
    assert staging["archive_materialization"]["materialized"] is True
    assert staging["task_context"]["data_description"] == "generated_from_public_readme"


def test_prepare_run_rejects_judge_settings_outside_trusted_root(tmp_path: Path):
    """Judge 凭据不能通过自定义路径落入 Agent 可读目录。"""

    naturebench = tmp_path / "NatureBench"
    task = naturebench / "data/naturebench_data/tasks/case-1"
    (task / "problem").mkdir(parents=True)
    (task / "problem/README.md").write_text("public", encoding="utf-8")
    (task / "evaluation").mkdir()
    (naturebench / "eval_service.py").write_text("# trusted\n", encoding="utf-8")
    (naturebench / "_evaluator_runner.py").write_text(
        "# trusted\n", encoding="utf-8"
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"env": {"JUDGE_API_KEY": "secret"}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trusted/"):
        prepare_run(
            naturebench_root=naturebench,
            task_id="case-1",
            famou_source=Path(__file__).resolve().parents[3],
            run_dir=tmp_path / "run",
            judge_settings_source=settings,
            trusted_judge_settings=tmp_path / "public-judge-settings.json",
        )


def test_task_entrypoint_waits_for_task_local_evaluator_drain(tmp_path: Path):
    """Controller 结束后 Supervisor 应等待 evaluator 正常写出完成标记。"""

    run_dir = tmp_path / "run"
    channel = run_dir / "controller" / "evaluator_channel"
    trusted = run_dir / "trusted"
    trusted_task = (
        trusted / "naturebench/data/naturebench_data/tasks/case-1"
    )
    channel.mkdir(parents=True)
    trusted_task.mkdir(parents=True)
    trusted.chmod(0o700)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
channel=""
mode="controller"
for arg in "$@"; do
    if [[ "$arg" == "famou_scientist.loop.integrations.naturebench.evaluator_worker" ]]; then
        mode="evaluator"
    fi
done
while [[ $# -gt 0 ]]; do
    case "$1" in
        --channel-dir|--evaluator-channel)
            channel="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done
if [[ "$mode" == "evaluator" ]]; then
    printf '{}\n' >"${channel}/EVALUATOR_READY.json"
    while [[ ! -f "${channel}/CLIENT_DONE.json" ]]; do sleep 0.05; done
    sleep 0.2
    printf '{}\n' >"${channel}/EVALUATOR_DONE.json"
else
    printf '{}\n' >"${channel}/CLIENT_DONE.json"
fi
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    entrypoint = (
        Path(__file__).resolve().parents[1]
        / "examples/naturebench/fmjob/task_entrypoint.sh"
    )
    command = [
        "bash",
        str(entrypoint),
        str(run_dir),
        "case-1",
        "claude",
        "test-model",
        "-",
        "0.01",
        "1",
        "1",
        "1",
        "1",
        "1",
        "1",
        "1",
        "0",
        "10",
        "0",
        "1",
        "test-model",
        "1",
        "10",
        "2",
        "0",
        "4",
        "10",
        "10",
        "10001",
        "10001",
        "-",
    ]

    process = subprocess.run(
        command,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "EVALUATOR_DRAIN_TIMEOUT_SEC": "5",
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert (channel / "EVALUATOR_DONE.json").is_file()
    assert (trusted / "logs/evaluator.log").is_file()
    assert not (run_dir / "results/evaluator.log").exists()


@pytest.mark.parametrize("graph,budget", [("sota_search", 1), ("scimodeling_budget", 0), ("scimodeling_budget", 5)])
def test_scimodelingbench_task_entrypoint_resets_stale_evaluator_handshake(
    tmp_path: Path, graph: str, budget: int,
):
    """Resume must start a new evaluator session in an existing channel."""

    run_dir = tmp_path / "run"
    channel = run_dir / "controller" / "evaluator_channel"
    trusted = run_dir / "trusted"
    channel.mkdir(parents=True)
    (run_dir / "problem").mkdir()
    trusted.mkdir()
    trusted.chmod(0o700)
    (trusted / "claude_settings.json").write_text(
        '{"env":{"ANTHROPIC_BASE_URL":"https://example.invalid"}}\n',
        encoding="utf-8",
    )
    for name in ("CLIENT_DONE.json", "EVALUATOR_READY.json", "EVALUATOR_DONE.json"):
        (channel / name).write_text('{"stale": true}\n', encoding="utf-8")
    for directory in (channel / "requests", channel / "responses"):
        directory.mkdir()
        (directory / "stale.json").write_text("{}\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
# Package probe and dataset preflight do not use the controller channel.
[[ "${1:-}" != "-" ]] || exit 0
for arg in "$@"; do
    [[ "$arg" != "famou_scientist.loop.integrations.scimodelingbench.preflight" ]] || exit 0
done
channel=""
graph=""
budget=""
mode="controller"
for arg in "$@"; do
    if [[ "$arg" == "famou_scientist.loop.integrations.scimodelingbench.evaluator_worker" ]]; then
        mode="evaluator"
    fi
done
while [[ $# -gt 0 ]]; do
    case "$1" in
        --channel-dir|--evaluator-channel)
            channel="$2"
            shift 2
            ;;
        --agent-graph)
            graph="$2"
            shift 2
            ;;
        --official-gt-budget)
            budget="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done
if [[ "$mode" == "evaluator" ]]; then
    [[ ! -f "${channel}/CLIENT_DONE.json" ]]
    [[ -z "$(find "${channel}/requests" -type f -print -quit)" ]]
    [[ -z "$(find "${channel}/responses" -type f -print -quit)" ]]
    printf '{"session":"resumed"}\n' >"${channel}/EVALUATOR_READY.json"
    while [[ ! -f "${channel}/CLIENT_DONE.json" ]]; do sleep 0.05; done
    printf '{"session":"resumed"}\n' >"${channel}/EVALUATOR_DONE.json"
else
    [[ "$graph" == "$FAMOU_AGENT_GRAPH" ]]
    [[ "$budget" == "$FAMOU_OFFICIAL_GT_BUDGET" ]]
    [[ -f "${HOME}/.claude/settings.json" ]]
    printf '{"session":"resumed"}\n' >"${channel}/CLIENT_DONE.json"
fi
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    entrypoint = (
        Path(__file__).resolve().parents[1]
        / "examples/scimodelingbench/fmjob/task_entrypoint.sh"
    )
    command = [
        "bash",
        str(entrypoint),
        str(run_dir),
        "tfbind8",
        "claude",
        "test-model",
        "-",
        "0.01",
        "1",
        "1",
        "1",
        "1",
        "1",
        "1",
        "1",
        "10",
        "0",
        "10",
        "test-model",
        "1",
        "10",
        "2",
        "0",
        "4",
        "10",
        "10001",
        "10001",
        "-",
    ]

    process = subprocess.run(
        command,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "EVALUATOR_DRAIN_TIMEOUT_SEC": "5",
            "FAMOU_AGENT_GRAPH": graph,
            "FAMOU_OFFICIAL_GT_BUDGET": str(budget),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads((channel / "EVALUATOR_READY.json").read_text()) == {
        "session": "resumed"
    }
    assert json.loads((channel / "EVALUATOR_DONE.json").read_text()) == {
        "session": "resumed"
    }


def test_scimodelingbench_claude_settings_are_filtered_and_durable(tmp_path: Path):
    source = tmp_path / "settings.json"
    source.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_AUTH_TOKEN": "test-secret",
                    "ANTHROPIC_BASE_URL": "https://example.invalid",
                    "API_TIMEOUT_MS": "600000",
                    "UNRELATED_SECRET": "must-not-copy",
                },
                "hooks": {"must": "not-copy"},
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"

    stage_scimodelingbench_claude_settings(source, run_dir)

    expected = {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "test-secret",
            "ANTHROPIC_BASE_URL": "https://example.invalid",
            "API_TIMEOUT_MS": "600000",
        }
    }
    durable = run_dir / "trusted/claude_settings.json"
    staged = run_dir / "agent_home/.claude/settings.json"
    assert json.loads(durable.read_text(encoding="utf-8")) == expected
    assert json.loads(staged.read_text(encoding="utf-8")) == expected
    assert durable.stat().st_mode & 0o777 == 0o600
    assert staged.stat().st_mode & 0o777 == 0o600


def test_trajectory_adapter_uses_exact_official_best_attempt(tmp_path: Path):
    """ExpBank 编号不等于官方 attempt 时仍必须审查正确代码和分数窗口。"""
    run_dir = tmp_path / "run"
    for attempt, official_attempt, score, code in (
        ("0001", 1, 0.1, "print('first')\n"),
        ("0002", 3, 0.4, "print('best')\n"),
        ("0003", 2, 0.2, "print('last')\n"),
    ):
        attempt_dir = run_dir / "expbank" / attempt
        (attempt_dir / "code").mkdir(parents=True)
        (attempt_dir / "code" / "run.py").write_text(code, encoding="utf-8")
        atomic_write_json(
            attempt_dir / "record.json",
            {
                "attempt_id": attempt,
                "score": score,
                "evaluation": {
                    "valid": True,
                    "evaluated_at": 1_700_000_000_000 + int(attempt),
                    "extra": {
                        "attempt": official_attempt,
                        "raw_scores": {"case": {"metric": score}},
                        "per_instance_improvement": {"case": score},
                        "aggregate_improvement": score,
                    },
                },
                "updated_at": 1_700_000_000_000 + int(attempt),
            },
        )
    session = (
        run_dir
        / "branches/branch-2/logs/claude_home/.claude/projects/project/session.jsonl"
    )
    session.parent.mkdir(parents=True)
    session.write_text(
        json.dumps(
            {
                "timestamp": "2023-11-14T22:13:20.000Z",
                "message": {
                    "content": [
                        {"type": "text", "text": "trained a regression model"}
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = NatureBenchTrajectoryAdapter().project(
        task_id="case-1",
        run_dir=run_dir,
        best_attempt_id="0002",
        agent_runtime="claude",
        request_id="judge-1",
    )

    task_out = Path(manifest["task_out_dir"])
    assert (task_out / "workspace" / "run.py").read_text() == "print('best')\n"
    summary = json.loads((task_out.parent / "run_summary.json").read_text())
    assert summary["results"][0]["best_attempt"] == 3
    submissions = [
        json.loads(line)
        for line in (task_out / "submissions.jsonl").read_text().splitlines()
    ]
    assert [item["attempt"] for item in submissions] == [1, 2, 3]
    assert manifest["score_attempt"] == 3
    assert manifest["trace"]["records"] == 1
    assert manifest["trace"]["judge_agent"] == "famou"


def test_default_judge_adapter_runs_as_package_module(tmp_path: Path):
    """可信 worker 的默认 Judge 子进程必须能保留包导入并调用官方接口。"""

    naturebench = tmp_path / "NatureBench"
    task_dir = naturebench / "data" / "tasks" / "case-1"
    (task_dir / "problem").mkdir(parents=True)
    (task_dir / "problem" / "README.md").write_text("task", encoding="utf-8")
    (task_dir / "problem" / "data_description.md").write_text(
        "data", encoding="utf-8"
    )
    (naturebench / "eval_service.py").write_text("# fake service\n", encoding="utf-8")
    (naturebench / "judge_core").mkdir()
    (naturebench / "judge_core" / "__init__.py").write_text("", encoding="utf-8")
    (naturebench / "judge_core" / "runner.py").write_text(
        "import json\n"
        "def judge_task(task_name, task_out_dir, agent_name='claude', **kwargs):\n"
        "    \"\"\"验证适配后的官方输入并返回固定 verdict。\"\"\"\n"
        "    summary = json.loads((task_out_dir.parent / 'run_summary.json').read_text())\n"
        "    assert summary['results'][0]['best_attempt'] == 1\n"
        "    assert agent_name == 'famou'\n"
        "    assert (task_out_dir / 'famou.jsonl').is_file()\n"
        "    assert (task_out_dir / 'workspace' / 'run.py').is_file()\n"
        "    return {'is_valid': True, 'reason': 'official fake accepted', 'model': 'fake'}\n",
        encoding="utf-8",
    )
    (naturebench / "agent").mkdir()
    (naturebench / "agent" / "__init__.py").write_text("", encoding="utf-8")
    (naturebench / "agent" / "adapter.py").write_text(
        "class AgentAdapter:\n"
        "    \"\"\"测试用官方 AgentAdapter 基类。\"\"\"\n"
        "    pass\n"
        "class Registry:\n"
        "    \"\"\"测试用 Agent 注册表。\"\"\"\n"
        "    def __init__(self):\n"
        "        \"\"\"初始化空注册表。\"\"\"\n"
        "        self.items = {}\n"
        "    def has(self, name):\n"
        "        \"\"\"判断名称是否存在。\"\"\"\n"
        "        return name in self.items\n"
        "    def register(self, adapter):\n"
        "        \"\"\"登记一个适配器。\"\"\"\n"
        "        self.items[adapter.name] = adapter\n"
        "REGISTRY = Registry()\n",
        encoding="utf-8",
    )

    run_dir = tmp_path / "run"
    attempt = run_dir / "expbank" / "0001"
    (attempt / "code").mkdir(parents=True)
    (attempt / "code" / "run.py").write_text("print('fit')\n", encoding="utf-8")
    atomic_write_json(
        attempt / "record.json",
        {
            "attempt_id": "0001",
            "score": 0.2,
            "evaluation": {
                "valid": True,
                "extra": {"attempt": 1, "aggregate_improvement": 0.2},
            },
        },
    )
    (run_dir / "controller").mkdir(parents=True)
    (run_dir / "controller" / "trajectory.jsonl").write_text(
        json.dumps({"event": "candidate_scored", "timestamp_ms": 1_700_000_000_000})
        + "\n",
        encoding="utf-8",
    )
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    submissions = trusted / "submissions.jsonl"
    submissions.write_text(
        json.dumps(
            {
                "type": "success",
                "attempt": 1,
                "timestamp": 1_700_000_000.0,
                "raw_scores": {},
                "per_instance_improvement": {},
                "aggregate_improvement": 0.2,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    verdict, stdout, stderr, returncode = evaluator_worker._judge(
        judge_script=None,
        task_dir=task_dir,
        run_dir=run_dir,
        best_attempt_id="0001",
        request_id="judge-1",
        agent_runtime="claude",
        model=None,
        timeout_sec=30,
        submissions_path=submissions,
        submission_map_path=trusted / "submission_map.jsonl",
    )

    assert returncode == 0, stderr
    assert verdict["is_valid"] is True
    assert verdict["score_attempt"] == 1
    assert "official fake accepted" in stdout


def _unsigned_evaluator(channel: Path) -> None:
    """消费一个测试请求并写入无需签名的固定分数。"""
    requests = channel / "requests"
    responses = channel / "responses"
    deadline = time.monotonic() + 180
    responded: set[str] = set()
    while time.monotonic() < deadline:
        candidates = sorted(requests.glob("*.json"))
        for request_path in candidates:
            if request_path.name in responded:
                continue
            request = json.loads(request_path.read_text(encoding="utf-8"))
            atomic_write_json(
                responses / request_path.name,
                {
                    "request_id": request["request_id"],
                    "attempt_id": request["attempt_id"],
                    "valid": True,
                    "metrics": {"aggregate_improvement": 0.125},
                    "stdout": "official evaluator stdout",
                    "stderr": "",
                    "extra": {"raw_scores": {"case": {"ARI": 0.8}}},
                },
            )
            responded.add(request_path.name)
        if (channel / "CLIENT_DONE.json").is_file() and responded:
            return
        time.sleep(0.01)
    raise AssertionError("Harness did not submit an evaluator request")


def test_http_evaluator_returns_promptly_when_task_is_stopped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """远端 HTTP 阻塞时，stop 仍应立即释放本地 Evaluation worker。"""

    unblock = threading.Event()

    def blocking_urlopen(*args, **kwargs):
        del args, kwargs
        unblock.wait(timeout=5)
        raise TimeoutError("remote request still running")

    monkeypatch.setattr(
        "famou_scientist.loop.harness.evaluator.urllib.request.urlopen",
        blocking_urlopen,
    )
    cancel_file = tmp_path / "research_stop_requested.json"
    client = HttpEvaluatorClient(
        "http://trusted-evaluator.invalid",
        timeout_sec=60,
        poll_interval_sec=0.01,
        cancel_file=cancel_file,
    )
    errors: list[Exception] = []

    def evaluate() -> None:
        try:
            client.evaluate(attempt_id="0001")
        except Exception as exc:  # noqa: BLE001 - 由主线程断言错误类型
            errors.append(exc)

    worker = threading.Thread(target=evaluate)
    started_at = time.monotonic()
    worker.start()
    time.sleep(0.05)
    cancel_file.write_text("{}\n", encoding="utf-8")
    worker.join(timeout=1)
    unblock.set()

    assert not worker.is_alive()
    assert time.monotonic() - started_at < 1
    assert len(errors) == 1
    assert isinstance(errors[0], EvaluatorError)
    assert "cancelled by task stop" in str(errors[0])


def test_benchmark_harness_runs_minimal_role_pipeline(tmp_path: Path):
    """验证 Idea、Implement、Evaluation、ExpBank 和提升链路。"""
    problem = tmp_path / "run" / "problem"
    (problem / "data").mkdir(parents=True)
    (problem / "README.md").write_text("公开测试任务", encoding="utf-8")
    channel = tmp_path / "run" / "controller" / "evaluator_channel"
    client = FileEvaluatorClient(
        channel,
        timeout_sec=10,
        poll_interval_sec=0.01,
        allow_unsigned=True,
    )
    evaluator_thread = threading.Thread(
        target=_unsigned_evaluator,
        args=(channel,),
        daemon=True,
    )
    evaluator_thread.start()
    fake_agent = FIXTURES / "agents" / "fake_role_cli.py"
    config = HarnessConfig(
        task_id="fake-task",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        agent_binary=str(fake_agent),
        iterations=1,
        agent_timeout_sec=10,
        experiment_timeout_sec=10,
    )
    summary = BenchmarkHarness(config, client).run()
    evaluator_thread.join(timeout=2)

    assert summary["best_score"] == 0.125
    assert summary["scheduler"] == "AsyncOrchestrator"
    assert summary["best_branch"].startswith("actor_branch_")
    assert (config.workspace_dir / "run.py").is_file()
    assert (
        config.workspace_dir / "output" / "submission.txt"
    ).read_text() == summary["best_branch"]
    expbank = json.loads(
        (config.run_dir / "expbank" / "0001" / "record.json").read_text(
            encoding="utf-8"
        )
    )
    assert expbank["promoted"] is True
    assert expbank["evaluation"]["redacted_for_agent"] is True
    assert "stdout" not in expbank["evaluation"]
    assert (config.run_dir / "expbank" / "0001" / "code" / "run.py").is_file()
    assert (config.run_dir / "expbank" / "0001" / "evidence" / "run.json").is_file()
    assert "公开数据上的确定性基线" in (config.run_dir / "expbank" / "INDEX.md").read_text(
        encoding="utf-8"
    )
    artifact_index = [
        json.loads(line)
        for line in (config.run_dir / "artifacts" / "artifact_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    official_record = next(item for item in artifact_index if item["type"] == "official_eval")
    official_evidence = json.loads(
        (config.run_dir / official_record["path"]).read_text(encoding="utf-8")
    )
    # Evaluator 结果写入 Agent 可见 artifacts 前已经是脱敏视图；原始输出只能由
    # 可信 evaluator 自己写入 run 外 evidence store（本测试使用无签名 fake transport）。
    assert official_evidence["stdout"] == ""
    assert "raw_scores" not in json.dumps(official_evidence)
    assert (channel / "CLIENT_DONE.json").is_file()


def test_harness_restores_best_output_after_lower_score(tmp_path: Path):
    """验证后续低分候选不会污染 canonical 最终提交。"""
    problem = tmp_path / "run" / "problem"
    (problem / "data").mkdir(parents=True)
    (problem / "README.md").write_text("公开测试任务", encoding="utf-8")
    evaluator = SequenceEvaluator([0.5, 0.1])
    config = HarnessConfig(
        task_id="fake-task",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        agent_binary=str(FIXTURES / "agents" / "fake_role_cli.py"),
        iterations=2,
        agent_timeout_sec=10,
        experiment_timeout_sec=10,
    )

    summary = BenchmarkHarness(config, evaluator).run()

    assert summary["best_score"] == 0.5
    assert summary["best_branch"].startswith("actor_branch_")
    final_submission = (config.workspace_dir / "output" / "submission.txt").read_text()
    assert final_submission == summary["best_branch"]
    assert evaluator.closed is True


def test_harness_discards_effective_score_when_judge_rejects(tmp_path: Path):
    """Judge 判 invalid 时保留原始最好分数，但官方有效分数必须为空。"""
    problem = tmp_path / "run" / "problem"
    (problem / "data").mkdir(parents=True)
    (problem / "README.md").write_text("公开测试任务", encoding="utf-8")
    evaluator = SequenceEvaluator(
        [0.5],
        judge_verdict={
            "is_valid": False,
            "reason": "提交使用了硬编码测试答案。",
            "model": "fake-judge",
        },
    )
    config = HarnessConfig(
        task_id="fake-task",
        run_dir=tmp_path / "run",
        problem_dir=problem,
        workspace_dir=tmp_path / "run" / "workspace",
        agent_runtime="claude",
        model="test-model",
        agent_binary=str(FIXTURES / "agents" / "fake_role_cli.py"),
        iterations=1,
        agent_timeout_sec=10,
        experiment_timeout_sec=10,
        finalize_evaluation=True,
    )

    summary = BenchmarkHarness(config, evaluator).run()

    assert summary["best_score"] == 0.5
    assert summary["effective_score"] is None
    assert summary["best_attempt_id"] == "0001"
    assert summary["final_evaluation"]["is_valid"] is False
    verdict = json.loads(
        (config.run_dir / "controller" / "judge_verdict.json").read_text()
    )
    assert verdict["reason"] == "提交使用了硬编码测试答案。"


def test_agent_run_cli_uses_unified_async_orchestrator(tmp_path: Path, capsys):
    """外部 benchmark CLI 应直接进入统一异步调度器。"""
    run_dir = tmp_path / "run"
    problem = run_dir / "problem"
    (problem / "data").mkdir(parents=True)
    (problem / "README.md").write_text("公开测试任务", encoding="utf-8")
    channel = run_dir / "controller" / "evaluator_channel"
    client_thread = threading.Thread(
        target=_unsigned_evaluator,
        args=(channel,),
        daemon=True,
    )
    client_thread.start()

    rc = cmdline.main(
        [
            "agent",
            "run",
            "--task-id",
            "cli-fake-task",
            "--run-dir",
            str(run_dir),
            "--evaluator-channel",
            str(channel),
            "--allow-unsigned-evaluator",
                "--agent-runtime",
                "claude",
                "--model",
                "test-model",
                "--agent-binary",
            str(FIXTURES / "agents" / "fake_role_cli.py"),
            "--iterations",
            "1",
            "--agent-timeout-sec",
            "10",
            "--experiment-timeout-sec",
            "10",
        ]
    )
    client_thread.join(timeout=2)

    assert rc == 0
    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["scheduler"] == "AsyncOrchestrator"
    assert summary["attempts_completed"] == 1
    assert (run_dir / "queues" / "benchmark_attempt_queue.jsonl").is_file()
    assert (run_dir / "workspace" / "run.py").is_file()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is unavailable")
def test_file_evaluator_rejects_forged_response(tmp_path: Path):
    """验证共享 CFS 中无可信私钥的伪造分数无法通过验签。"""
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "channel" / "public_key.pem"
    public_key.parent.mkdir(parents=True)
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(private_key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    client = FileEvaluatorClient(
        public_key.parent,
        public_key=public_key,
        timeout_sec=2,
        poll_interval_sec=0.01,
    )

    def forge_response() -> None:
        """写入伪造响应和无效签名。"""
        for _ in range(100):
            requests = sorted((public_key.parent / "requests").glob("*.json"))
            if requests:
                request = json.loads(requests[0].read_text(encoding="utf-8"))
                response = public_key.parent / "responses" / requests[0].name
                atomic_write_json(
                    response,
                    {
                        "request_id": request["request_id"],
                        "valid": True,
                        "metrics": {"aggregate_improvement": 999.0},
                    },
                )
                response.with_suffix(".sig").write_bytes(b"forged")
                return
            time.sleep(0.01)

    thread = threading.Thread(target=forge_response, daemon=True)
    thread.start()
    with pytest.raises(EvaluatorError, match="signature verification failed"):
        client.evaluate(attempt_id="attempt-forged")


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is unavailable")
def test_file_evaluator_pins_public_key_before_agents_run(tmp_path: Path):
    """验证 Agent 不能替换 run 目录公钥并用自己的私钥伪造分数。"""
    channel = tmp_path / "channel"
    channel.mkdir()
    trusted_private = tmp_path / "trusted.pem"
    attacker_private = tmp_path / "attacker.pem"
    public_key = channel / "public_key.pem"
    attacker_public = tmp_path / "attacker-public.pem"
    for private, public in (
        (trusted_private, public_key),
        (attacker_private, attacker_public),
    ):
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(private)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl",
                "pkey",
                "-in",
                str(private),
                "-pubout",
                "-out",
                str(public),
            ],
            check=True,
            capture_output=True,
        )
    client = FileEvaluatorClient(
        channel,
        public_key=public_key,
        timeout_sec=2,
        poll_interval_sec=0.01,
    )

    def replace_key_and_sign() -> None:
        """模拟恶意 Agent 替换公钥并用自有私钥签署伪造响应。"""
        for _ in range(100):
            requests = sorted((channel / "requests").glob("*.json"))
            if requests:
                request = json.loads(requests[0].read_text(encoding="utf-8"))
                public_key.write_bytes(attacker_public.read_bytes())
                response = channel / "responses" / requests[0].name
                atomic_write_json(
                    response,
                    {
                        "request_id": request["request_id"],
                        "valid": True,
                        "metrics": {"aggregate_improvement": 999.0},
                    },
                )
                subprocess.run(
                    [
                        "openssl",
                        "dgst",
                        "-sha256",
                        "-sign",
                        str(attacker_private),
                        "-out",
                        str(response.with_suffix(".sig")),
                        str(response),
                    ],
                    check=True,
                    capture_output=True,
                )
                return
            time.sleep(0.01)

    thread = threading.Thread(target=replace_key_and_sign, daemon=True)
    thread.start()
    with pytest.raises(EvaluatorError, match="public key changed"):
        client.evaluate(attempt_id="attempt-key-swap")


def test_naturebench_worker_accepts_only_permission_isolated_in_run_evidence(
    tmp_path: Path,
):
    """验证同一运行树内只有 root-only trusted/ 可保存可信评测证据。"""
    run_dir = tmp_path / "run"
    trusted_root = run_dir / "trusted"
    trusted_root.mkdir(parents=True)
    trusted_root.chmod(0o700)

    evaluator_worker._validate_trusted_evidence_dir(
        trusted_root / "raw_evaluator_artifacts",
        run_dir=run_dir,
    )
    with pytest.raises(ValueError, match="must be below trusted"):
        evaluator_worker._validate_trusted_evidence_dir(
            run_dir / "results" / "raw_evaluator_artifacts",
            run_dir=run_dir,
        )

    trusted_root.chmod(0o755)
    with pytest.raises(PermissionError, match="group/other"):
        evaluator_worker._validate_trusted_evidence_dir(
            trusted_root / "raw_evaluator_artifacts",
            run_dir=run_dir,
        )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is unavailable")
def test_naturebench_worker_returns_signed_standard_result(tmp_path: Path):
    """验证公共响应脱敏且可信目录保留完整 stdout、stderr、extra。"""
    private_key = tmp_path / "trusted" / "private.pem"
    public_key = tmp_path / "channel" / "public_key.pem"
    private_key.parent.mkdir(parents=True)
    public_key.parent.mkdir(parents=True)
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(private_key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    task_dir = tmp_path / "trusted" / "task"
    output_dir = tmp_path / "run" / "workspace" / "output"
    trusted_evidence_dir = tmp_path / "trusted" / "raw-evaluator-artifacts"
    task_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    adapter = tmp_path / "trusted" / "fake_adapter.py"
    adapter.write_text(
        "import json\n"
        "print('adapter diagnostic')\n"
        "print(json.dumps({'valid': True, "
        "'official_metrics': {'aggregate_improvement': 0.25}, "
        "'diagnostics_public': {'scoring': 'fake'}, "
        "'extra': {'raw_scores': {'ARI': 0.9}}, "
        "'extra_public': {'task_name': 'fake-task', "
        "'raw_scores': {'case_a': {'ARI': 0.9}}, "
        "'per_instance_improvement': {'case_a': 0.25}, "
        "'aggregate_improvement': 0.25, "
        "'private_field': 'must-not-pass'}, 'error': None}))\n",
        encoding="utf-8",
    )
    errors: list[BaseException] = []

    def run_worker() -> None:
        """在测试线程中运行一次可信 evaluator worker。"""
        try:
            evaluator_worker.main(
                [
                    "--task-dir",
                    str(task_dir),
                    "--output-dir",
                    str(output_dir),
                    "--channel-dir",
                    str(public_key.parent),
                    "--private-key",
                    str(private_key),
                    "--trusted-evidence-dir",
                    str(trusted_evidence_dir),
                    "--adapter-script",
                    str(adapter),
                    "--idle-timeout-sec",
                    "10",
                    "--poll-interval-sec",
                    "0.01",
                    "--min-requests",
                    "2",
                ]
            )
        except BaseException as exc:  # noqa: BLE001 - 转交主测试线程断言
            errors.append(exc)

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    client = FileEvaluatorClient(
        public_key.parent,
        public_key=public_key,
        timeout_sec=5,
        poll_interval_sec=0.01,
    )
    result = client.evaluate(attempt_id="attempt-signed-1")
    second_result = client.evaluate(attempt_id="attempt-signed-2")
    client.close()
    worker_thread.join(timeout=5)

    assert not errors
    assert result["valid"] is True
    assert result["metrics"]["aggregate_improvement"] == 0.25
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["redacted_for_agent"] is True
    raw_response = json.loads(
        (trusted_evidence_dir / result["request_id"] / "response.json").read_text(
            encoding="utf-8"
        )
    )
    assert "adapter diagnostic" in (
        trusted_evidence_dir / result["request_id"] / "stdout.txt"
    ).read_text(encoding="utf-8")
    assert raw_response["extra"]["adapter_extra"]["raw_scores"]["ARI"] == 0.9
    assert result["extra"] == {
        "task_name": "fake-task",
        "attempt": 1,
        "raw_scores": {"case_a": {"ARI": 0.9}},
        "per_instance_improvement": {"case_a": 0.25},
        "aggregate_improvement": 0.25,
        "best_aggregate_improvement": 0.25,
        "best_attempt": 1,
    }
    assert second_result["extra"]["attempt"] == 2
    assert second_result["extra"]["best_aggregate_improvement"] == 0.25
    assert second_result["extra"]["best_attempt"] == 1
    submissions = [
        json.loads(line)
        for line in (trusted_evidence_dir / "submissions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [item["attempt"] for item in submissions] == [1, 2]
    assert all(item["type"] == "success" for item in submissions)
    assert submissions[0]["raw_scores"] == {"ARI": 0.9}
    assert submissions[0]["aggregate_improvement"] == 0.25
    submission_map = [
        json.loads(line)
        for line in (trusted_evidence_dir / "submission_map.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert submission_map[0]["candidate_id"] == "attempt-signed-1"
    assert submission_map[0]["attempt"] == 1
    restored = evaluator_worker._load_evaluation_session(
        trusted_evidence_dir / "submissions.jsonl"
    )
    assert restored == {
        "attempt": 2,
        "best_aggregate_improvement": 0.25,
        "best_attempt": 1,
    }
    assert "private_field" not in json.dumps(result)
    assert result["extra"]["raw_scores"] == {"case_a": {"ARI": 0.9}}
    run_visible = tmp_path / "run"
    visible_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in run_visible.rglob("*")
        if path.is_file()
    )
    assert "adapter diagnostic" not in visible_text
    assert (public_key.parent / "EVALUATOR_DONE.json").is_file()


def test_naturebench_native_history_records_failed_evaluation(tmp_path: Path):
    """正式 evaluator 执行失败也必须进入官方提交历史和 Candidate 映射。"""

    submissions = tmp_path / "trusted" / "submissions.jsonl"
    mapping = tmp_path / "trusted" / "submission_map.jsonl"
    evaluator_worker._append_native_submission(
        submissions_path=submissions,
        submission_map_path=mapping,
        request={"request_id": "eval-2", "attempt_id": "candidate-2"},
        response={
            "request_id": "eval-2",
            "valid": False,
            "official_metrics": {"aggregate_improvement": None},
            "diagnostics_public": {"evaluation_completed": False},
            "extra_public": {"attempt": 2},
            "extra": {"adapter_extra": {}},
            "stderr": "trusted traceback",
            "error": "evaluation crashed",
            "evaluated_at": 1_700_000_000_000,
        },
    )

    record = json.loads(submissions.read_text(encoding="utf-8"))
    assert record == {
        "type": "failure",
        "attempt": 2,
        "timestamp": 1_700_000_000.0,
        "raw_scores": None,
        "per_instance_improvement": None,
        "aggregate_improvement": None,
        "error": "evaluation crashed",
        "traceback": "trusted traceback",
    }
    map_record = json.loads(mapping.read_text(encoding="utf-8"))
    assert map_record["candidate_id"] == "candidate-2"
    assert map_record["attempt"] == 2


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is unavailable")
def test_naturebench_worker_returns_signed_judge_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """验证 Validity Judge 也只能通过可信 worker 的签名响应返回。"""
    # worker 在启用 judge 时会前置校验凭据；本例用桩 adapter，不会真的调用 API。
    monkeypatch.setenv("JUDGE_API_KEY", "test-judge-key")
    private_key = tmp_path / "trusted" / "private.pem"
    public_key = tmp_path / "channel" / "public_key.pem"
    private_key.parent.mkdir(parents=True)
    public_key.parent.mkdir(parents=True)
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-out", str(private_key)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    task_dir = tmp_path / "trusted" / "task"
    output_dir = tmp_path / "run" / "workspace" / "output"
    trusted_evidence_dir = tmp_path / "trusted" / "raw-evaluator-artifacts"
    task_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    adapter = tmp_path / "trusted" / "unused_eval.py"
    adapter.write_text("print('{}')\n", encoding="utf-8")
    judge = tmp_path / "trusted" / "fake_judge.py"
    judge.write_text(
        "import json\n"
        "print(json.dumps({'is_valid': False, "
        "'reason': 'hard-coded outputs', 'model': 'fake-judge', "
        "'score_attempt': 2}))\n",
        encoding="utf-8",
    )
    errors: list[BaseException] = []

    def run_worker() -> None:
        """在测试线程中运行一次支持 Judge 的可信 worker。"""
        try:
            evaluator_worker.main(
                [
                    "--task-dir",
                    str(task_dir),
                    "--output-dir",
                    str(output_dir),
                    "--channel-dir",
                    str(public_key.parent),
                    "--private-key",
                    str(private_key),
                    "--trusted-evidence-dir",
                    str(trusted_evidence_dir),
                    "--adapter-script",
                    str(adapter),
                    "--run-dir",
                    str(tmp_path / "run"),
                    "--validity-judge-script",
                    str(judge),
                    "--idle-timeout-sec",
                    "10",
                    "--poll-interval-sec",
                    "0.01",
                    "--min-requests",
                    "1",
                ]
            )
        except BaseException as exc:  # noqa: BLE001 - 转交主测试线程断言
            errors.append(exc)

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    client = FileEvaluatorClient(
        public_key.parent,
        public_key=public_key,
        timeout_sec=5,
        poll_interval_sec=0.01,
    )
    result = client.request(operation="validity_judge", attempt_id="0002")
    client.close()
    worker_thread.join(timeout=5)

    assert not errors
    assert result["kind"] == "validity_judge"
    assert result["valid"] is True
    assert result["attempt_id"] == "0002"
    assert result["judge"]["is_valid"] is False
    assert result["judge"]["reason"] == "hard-coded outputs"
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert (trusted_evidence_dir / result["request_id"] / "response.json").is_file()
