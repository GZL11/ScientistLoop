"""Agent Facility 接口及现有 WorkerSet 兼容实现。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class AgentFacility(Protocol):
    """定义研究智能体可执行的动作，不向其暴露 evaluator。"""

    def generate_ideas(
        self,
        goal: dict[str, Any],
        experience: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """生成研究想法；开放科研的长生命周期 Actor 每回合只返回一条。"""

        ...

    def idea_gate(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        experience: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """按 Goal Contract 与 Rubric 执行开放科研 Idea Gate。"""

        ...

    def rank_ideas(
        self,
        goal: dict[str, Any],
        ideas: list[dict[str, Any]],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        """结合剩余时间、资源和历史证据对待实现 Idea 排序。"""

        ...

    def implement(self, idea: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
        """实现一个想法并提交候选版本。"""

        ...

    def analyze_result(
        self,
        branch: dict[str, Any],
        results: dict[str, Any],
    ) -> dict[str, Any]:
        """分析脱敏后的实验结果。"""

        ...

    def analyze_deep(self, branch: dict[str, Any]) -> dict[str, Any]:
        """执行面向论文候选的深入分析。"""

        ...

    def summarize_experience(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """在 Loop 结束后提炼可跨任务复用的公开经验。"""

        ...


class WorkerAgentFacility:
    """把现有 WorkerSet 包装成 Agent Facility。"""

    def __init__(self, workers: Any):
        """保存已有 WorkerSet；包装层不接收 evaluator 或其 endpoint。"""

        self.workers = workers

    def generate_ideas(
        self,
        goal: dict[str, Any],
        experience: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """委托已有 Idea Worker 生成想法。"""

        return self.workers.generate_ideas(goal, experience)

    def idea_gate(
        self,
        goal: dict[str, Any],
        idea: dict[str, Any],
        experience: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """委托已有 Gate Worker 判断新颖性。"""

        return self.workers.idea_gate(goal, idea, experience)

    def rank_ideas(
        self,
        goal: dict[str, Any],
        ideas: list[dict[str, Any]],
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        """委托已有 Judge Worker 对待实现 Idea 进行资源感知排序。"""

        return self.workers.rank_ideas(goal, ideas, runtime_context)

    def implement(self, idea: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
        """委托已有 Implement Worker 实现候选。"""

        return self.workers.implement(idea, workspace)

    def analyze_result(
        self,
        branch: dict[str, Any],
        results: dict[str, Any],
    ) -> dict[str, Any]:
        """委托已有 Result Worker 分析结果。"""

        return self.workers.analyze_result(branch, results)

    def analyze_deep(self, branch: dict[str, Any]) -> dict[str, Any]:
        """委托已有 Deep Analyze Worker 深入分析。"""

        return self.workers.analyze_deep(branch)

    def summarize_experience(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """委托已有 Summary Worker 复盘完整演化过程。"""

        return self.workers.summarize_experience(context)


__all__ = ["AgentFacility", "WorkerAgentFacility"]
