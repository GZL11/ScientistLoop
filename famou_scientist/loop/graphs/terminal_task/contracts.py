"""TerminalTaskGraph 的节点输入输出 contract。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TerminalTaskConfig:
    """单任务 Agent loop 的边界。"""

    # Deprecated compatibility field. Refine is now bounded only by
    # max_agent_wall_time_sec; this value is retained for old callers/checkpoints.
    max_refine_rounds: int = 0
    max_agent_wall_time_sec: int = 4 * 60 * 60
    # Proxy 触发的 Solver refine 上限；初始 solve 不计入。
    max_proxy_refine_rounds: int = 10
    # 候选轮次的校验来源；proxy 保持现有默认行为。
    candidate_verifier_mode: str = "proxy"
    # gt_budget 模式下 Solver 运行期间可主动申请的官方 GT 评测次数。
    # FinalAudit 单独计算，不占用该预算。
    official_gt_budget: int = 1

    def normalized(self) -> "TerminalTaskConfig":
        return TerminalTaskConfig(
            max_refine_rounds=max(0, int(self.max_refine_rounds)),
            max_agent_wall_time_sec=max(1, int(self.max_agent_wall_time_sec)),
            max_proxy_refine_rounds=max(0, int(self.max_proxy_refine_rounds)),
            candidate_verifier_mode=str(self.candidate_verifier_mode or "proxy").strip().lower(),
            official_gt_budget=max(0, int(self.official_gt_budget)),
        )


@dataclass(frozen=True)
class VerifierPlan:
    """在 Solver 修改前由 VerifierAgent 生成并冻结的检查计划。"""

    schema_version: int
    task_input_hash: str
    rubrics: tuple[Mapping[str, Any], ...]
    plan_ref: str | None = None


@dataclass(frozen=True)
class SurrogateReport:
    """针对一个 workspace snapshot 的公开检查结果。"""

    round: int
    status: str
    checks: tuple[Mapping[str, Any], ...] = ()
    repair_instructions: str = ""
    artifact_ref: str | None = None
    coverage: float | None = None
    report_ref: str | None = None


def output_map(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """复制节点 output，避免 Graph 状态引用外部可变字典。"""

    return dict(value or {})


__all__ = ["SurrogateReport", "TerminalTaskConfig", "VerifierPlan", "output_map"]
