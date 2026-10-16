"""装配 NatureBench 原生 Judge，并调用 benchmark-specific 轨迹适配器。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ...utils import atomic_write_json
from .trajectory_adapter import NatureBenchTrajectoryAdapter


def _find_naturebench_root(task_dir: Path) -> Path:
    """从任务目录向上查找包含官方 Judge 实现的 NatureBench 根目录。"""

    for parent in (task_dir, *task_dir.parents):
        if (parent / "judge_core" / "runner.py").is_file() and (
            parent / "eval_service.py"
        ).is_file():
            return parent
    raise FileNotFoundError(f"无法从任务目录找到 NatureBench 根目录: {task_dir}")


def _register_famou_agent_adapter() -> None:
    """在 NatureBench 官方注册表中把 Famou 声明为一个独立 Agent。"""

    from agent.adapter import REGISTRY, AgentAdapter  # type: ignore[import-not-found]

    if REGISTRY.has("famou"):
        return

    class FamouAgentAdapter(AgentAdapter):
        """让官方 Judge 从 benchmark-native ``famou.jsonl`` 读取轨迹。"""

        name = "famou"

        def system_prompt(self, ctx: Any) -> str:
            """Judge-only 适配器不负责启动 Famou Agent。"""

            del ctx
            raise RuntimeError("Famou Judge Adapter 不提供 Agent 启动能力")

        def build_command(self, ctx: Any) -> list[str]:
            """Judge-only 适配器不构造容器内命令。"""

            del ctx
            raise RuntimeError("Famou Judge Adapter 不提供 Agent 启动能力")

        def transcript_path(self, task_out_dir: Path) -> Path | None:
            """返回 TrajectoryAdapter 生成的 benchmark-native 轨迹。"""

            path = task_out_dir / "famou.jsonl"
            return path if path.is_file() else None

    REGISTRY.register(FamouAgentAdapter())


class NatureBenchJudgeAdapter:
    """组合证据投影和官方 ``judge_task``，不参与数值评分。"""

    name = "naturebench"

    def __init__(
        self,
        trajectory_adapter: NatureBenchTrajectoryAdapter | None = None,
    ):
        """允许测试或外部插件替换纯转换层。"""

        self.trajectory_adapter = (
            trajectory_adapter or NatureBenchTrajectoryAdapter()
        )

    def judge(
        self,
        *,
        task_dir: str | Path,
        run_dir: str | Path,
        best_attempt_id: str,
        agent_runtime: str,
        request_id: str,
        model: str | None = None,
        submissions_path: str | Path | None = None,
        submission_map_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """生成官方输入，调用 Judge，并把 verdict 与证据版本绑定。"""

        resolved_task = Path(task_dir).expanduser().resolve()
        resolved_run = Path(run_dir).expanduser().resolve()
        naturebench_root = _find_naturebench_root(resolved_task)
        root_text = str(naturebench_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)

        # 导入官方 runner 会注册 Claude/Codex/Gemini；Famou 作为独立的
        # AgentAdapter 仅声明 transcript 路径，不侵入其启动实现。
        from judge_core.runner import judge_task  # type: ignore[import-not-found]

        _register_famou_agent_adapter()
        manifest = self.trajectory_adapter.project(
            task_id=resolved_task.name,
            run_dir=resolved_run,
            best_attempt_id=best_attempt_id,
            agent_runtime=agent_runtime,
            request_id=request_id,
            submissions_path=submissions_path,
            submission_map_path=submission_map_path,
        )
        verdict = judge_task(
            resolved_task.name,
            Path(str(manifest["task_out_dir"])),
            agent_name=str(manifest["trace"]["judge_agent"]),
            model=model,
            task_problem_dir=resolved_task / "problem",
        )
        if not isinstance(verdict, dict):
            raise TypeError("NatureBench judge_task 必须返回 JSON 对象")
        enriched = {
            **verdict,
            "task_id": resolved_task.name,
            "score_attempt": manifest["score_attempt"],
            "expbank_attempt_id": best_attempt_id,
            "best_aggregate_improvement": manifest["best_score"],
            "trajectory_adapter": self.trajectory_adapter.name,
            "evidence_manifest": str(
                resolved_run
                / "controller"
                / "naturebench_judge"
                / request_id
                / "judge_input_manifest.json"
            ),
        }
        atomic_write_json(
            resolved_run
            / "controller"
            / "naturebench_judge"
            / request_id
            / "judge_verdict.json",
            enriched,
        )
        return enriched


def _build_parser() -> argparse.ArgumentParser:
    """构建可信 Judge Adapter 子进程参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--best-attempt-id", required=True)
    parser.add_argument("--agent-runtime", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--model")
    parser.add_argument("--submissions-path")
    parser.add_argument("--submission-map-path")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行官方 Judge，并在标准输出末行写出结构化 verdict。"""

    args = _build_parser().parse_args(argv)
    model = None if args.model in (None, "", "-") else str(args.model)
    try:
        verdict = NatureBenchJudgeAdapter().judge(
            task_dir=args.task_dir,
            run_dir=args.run_dir,
            best_attempt_id=str(args.best_attempt_id),
            agent_runtime=str(args.agent_runtime),
            request_id=str(args.request_id),
            model=model,
            submissions_path=args.submissions_path,
            submission_map_path=args.submission_map_path,
        )
    except Exception as exc:  # noqa: BLE001 - Judge 故障也必须形成结构化证据
        verdict = {
            "is_valid": None,
            "reason": f"judge_error: {type(exc).__name__}: {exc}",
            "model": model,
            "expbank_attempt_id": str(args.best_attempt_id),
        }
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if type(verdict.get("is_valid")) is bool else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["NatureBenchJudgeAdapter", "main"]
