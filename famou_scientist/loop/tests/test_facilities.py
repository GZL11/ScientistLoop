"""Agent、Bench、Evaluation 三设施解耦边界测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from famou_scientist.loop.agents.workers import (
    DummyWorkerSet,
    PromptWorkerSet,
    _sandbox_config,
)
from famou_scientist.loop.domain.status import LoopStatus
from famou_scientist.loop.execution.agent_runtime import ImplementResult
from famou_scientist.loop.facilities import (
    AdapterEvaluationFacility,
    ArtifactRef,
    CandidateRef,
    EvaluationRequest,
    RunnerBenchmarkFacility,
    WorkerAgentFacility,
)
from famou_scientist.loop.execution.cli_agent_wrapper import build_implement_prompt
from famou_scientist.loop.storage.candidates import CandidateStore


class _BundleRunner:
    """测试非 Python 源码包的最小 Runner。"""

    def preflight(self, branch):
        """确认通用 Candidate 不需要声明单一入口。"""

        return {"valid": branch.get("entrypoint") is None}

    def run(self, branch):
        """把源码包内容复制为一个测试提交产物。"""

        output = Path(branch["candidate_output_dir"]) / "answer.txt"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            (Path(branch["method_dir"]) / "method.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return {
            "id": "bundle-run",
            "valid": True,
            "artifact": str(output),
            "source": "bundle_runner",
        }


class _PublicAdapter:
    """测试 Bench Facility 的公开校验适配器。"""

    def validate_artifact(self, path):
        """只接受存在的普通文件。"""

        return {"valid": Path(path).is_file()}

    def run_public_eval(self, path):
        """返回不涉及隐藏数据的公开结果。"""

        return {"valid": Path(path).is_file(), "metrics": {"size": Path(path).stat().st_size}}

    def agent_view(self, result, *, source=None):
        """返回测试所需的最小公开视图。"""

        return {"valid": result.get("valid") is True, "source": source}


class _OfficialAdapter:
    """记录正式 evaluator 实际收到的路径。"""

    def __init__(self):
        """初始化调用记录。"""

        self.paths = []

    def run_official_eval(self, path):
        """记录经过 ArtifactRef 校验的正式提交路径。"""

        self.paths.append(path)
        return {"valid": True, "official_metrics": {"score": 1.0}}

    def agent_view(self, result, *, source=None):
        """返回脱敏测试视图。"""

        return {"valid": result.get("valid") is True, "source": source}


def test_artifact_ref_hash_is_stable_and_detects_changes(tmp_path: Path):
    """相同目录内容应产生稳定哈希，内容变化后 verify 必须失败。"""

    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "a.txt").write_text("a\n", encoding="utf-8")
    first = ArtifactRef.from_path(artifact, artifact_id="first")
    second = ArtifactRef.from_path(artifact, artifact_id="second")

    assert first.sha256 == second.sha256
    (artifact / "a.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="内容已变化"):
        first.verify()


def test_artifact_ref_rejects_symbolic_links(tmp_path: Path):
    """Artifact 不得通过符号链接引用受控目录外的数据。"""

    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "link.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="符号链接"):
        ArtifactRef.from_path(artifact, artifact_id="linked")


def test_candidate_and_benchmark_facility_do_not_require_python_entrypoint(
    tmp_path: Path,
):
    """通用 Candidate 可无入口，并能由非 Python Bench Facility 执行。"""

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "method.txt").write_text("bundle-result\n", encoding="utf-8")
    stored = CandidateStore(tmp_path).create(
        {"branch_id": "branch-bundle", "worktree": str(worktree)}
    )
    candidate = CandidateRef.from_payload(stored)
    facility = RunnerBenchmarkFacility(
        _BundleRunner(),
        _PublicAdapter(),
        task_id="bundle-task",
    )

    assert candidate.entrypoint is None
    assert facility.preflight(candidate, context=stored)["valid"] is True
    run = facility.run(candidate, context=stored)
    assert run.valid is True
    assert run.artifact_ref is not None
    assert facility.validate_artifact(run.artifact_ref)["valid"] is True


def test_candidate_store_recovers_entrypoint_from_method_manifest(tmp_path: Path):
    """分支元数据缺失时应从方法清单恢复入口，作为冻结前最后保底。"""

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (worktree / "method_manifest.json").write_text(
        '{"entrypoint": "run.py"}\n',
        encoding="utf-8",
    )

    stored = CandidateStore(tmp_path / "run").create(
        {"branch_id": "manifest-fallback", "worktree": str(worktree)}
    )

    assert stored["entrypoint"] == str(Path(stored["method_dir"]) / "run.py")


def test_evaluation_facility_accepts_only_controlled_artifact_ref(tmp_path: Path):
    """正式 evaluator 应由 EvaluationRequest 选定 Artifact，不能接收裸路径。"""

    artifact_path = tmp_path / "submission.json"
    artifact_path.write_text("{}\n", encoding="utf-8")
    artifact = ArtifactRef.from_path(artifact_path, artifact_id="submission")
    adapter = _OfficialAdapter()
    facility = AdapterEvaluationFacility(adapter)
    result = facility.evaluate(
        EvaluationRequest(
            task_id="task",
            attempt_id="attempt",
            artifact_ref=artifact,
        )
    )

    assert result.valid is True
    assert adapter.paths == [str(artifact_path.resolve())]
    with pytest.raises(AttributeError):
        facility.evaluate(str(artifact_path))  # type: ignore[arg-type]


def test_agent_facility_has_no_evaluator_dependency():
    """Agent Facility 的包装对象不应持有 evaluator 或 endpoint。"""

    facility = WorkerAgentFacility(DummyWorkerSet())
    assert not hasattr(facility, "evaluator")
    assert not hasattr(facility, "evaluator_endpoint")


def test_worker_sandbox_config_uses_goal_fallback_without_unknown_keyword():
    """Summary workers resolve the goal fallback before sandbox construction."""

    goal = {"infra": {"sandbox": {"type": "local", "run_as_uid": 10001}}}
    assert _sandbox_config({}, goal) == {
        "type": "local",
        "run_as_uid": 10001,
    }
    configured = {"sandbox": {"type": "local", "run_as_gid": 10002}}
    assert _sandbox_config(configured, goal) == {
        "type": "local",
        "run_as_gid": 10002,
    }


def test_experience_summary_agent_constructs_sandbox_and_returns_output(
    tmp_path: Path,
):
    """The summary Agent path must pass the sandbox root positionally."""

    class SummaryAgent:
        def implement(self, request):
            assert request.sandbox.root == request.workspace.root.resolve()
            return ImplementResult(
                status=LoopStatus.Implementation.IMPLEMENTED,
                branch_id=request.workspace.branch_id,
                workspace=str(request.workspace.root),
                worktree=str(request.workspace.worktree),
                output={"method_summary": "summary-agent-ok"},
            )

    workers = PromptWorkerSet(
        {
            "goal": {"id": "summary-test", "name": "summary-test"},
            "workflow": {"type": "benchmark_managed"},
            "infra": {"sandbox": {"type": "local"}},
            "workers": {"experience_summary": {"type": "single_call"}},
        },
        tmp_path,
        llm=object(),
    )
    workers.experience_summary_agent = SummaryAgent()

    assert workers.summarize_experience({"task_id": "task"}) == {
        "method_summary": "summary-agent-ok"
    }


def test_experience_summary_defaults_to_markdown_contract(tmp_path: Path):
    """Summary worker defaults to Markdown while preserving structured opt-in."""

    workers = PromptWorkerSet(
        {
            "goal": {"id": "summary-md", "name": "summary-md"},
            "workflow": {"type": "benchmark_managed"},
            "workers": {"experience_summary": {"type": "single_call"}},
        },
        tmp_path,
        llm=object(),
    )
    assert workers.experience_summary_config["format"] == "markdown"


def test_cli_agent_prompt_does_not_invent_an_entrypoint(tmp_path: Path):
    """任务契约未声明入口时，CLI Agent 指令不得擅自要求 method.py。"""

    prompt = build_implement_prompt(
        request={
            "metadata": {
                "implementation_contract": {
                    "entrypoint_must_be_executable": False,
                    "files_must_be_relative": True,
                }
            }
        },
        instruction="实现公开任务",
        output_path=tmp_path / "output.json",
        worktree_result_path=tmp_path / "worktree-result.json",
        worktree=tmp_path,
        max_turns=None,
        submit_candidate_command="python submit_candidate.py",
    )

    assert "--entrypoint" not in prompt
    assert "method.py" not in prompt
    assert "该任务未规定单一入口" in prompt
