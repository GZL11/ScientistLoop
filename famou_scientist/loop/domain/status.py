"""集中定义科研循环中不同作用域的状态值。"""
from __future__ import annotations

from enum import Enum


class _StatusValue(str, Enum):
    """提供可直接持久化为字符串的状态枚举基类。"""

    def __str__(self) -> str:
        """返回持久化时使用的原始字符串。"""
        return self.value

    @classmethod
    def values(cls) -> frozenset[str]:
        """返回当前作用域允许使用的全部字符串值。"""
        return frozenset(item.value for item in cls)


class LoopStatus:
    """统一收纳 Loop 状态，并通过子类型隔离不同业务作用域。"""

    class ExpBank(_StatusValue):
        """描述一次不可变实验版本在 ExpBank 中的生命周期。"""

        IMPLEMENTING = "implementing"
        IMPLEMENTED = "implemented"
        NOT_EXECUTED = "not_executed"
        ENGINEERING_FAILED = "engineering_failed"
        EVALUATED = "evaluated"
        BEST = "best"
        FAILED = "failed"

    class Idea(_StatusValue):
        """描述原始 Idea 从提交到进入实现前的生命周期。"""

        SUBMITTED = "submitted"
        UNDER_REVIEW = "under_review"
        ACCEPTED = "accepted"
        REVISION_REQUESTED = "revision_requested"
        NEEDS_EVIDENCE = "needs_evidence"
        REJECTED = "rejected"
        IMPLEMENTING = "implementing"
        IMPLEMENTED = "implemented"
        IMPLEMENTATION_FAILED = "implementation_failed"

    class Queue(_StatusValue):
        """描述持久化队列条目的调度状态。"""

        QUEUED = "queued"
        LEASED = "leased"
        WAITING_RESOURCES = "waiting_resources"
        RUNNING = "running"
        FINISHED = "finished"
        FAILED = "failed"
        ARCHIVED = "archived"
        CANCELLED = "cancelled"
        NOT_EXECUTED = "not_executed"

    class Research(_StatusValue):
        """描述整个研究目标的运行状态。"""

        RUNNING = "running"
        PAUSED = "paused"
        STOPPED = "stopped"
        COMPLETED = "completed"
        FAILED = "failed"

    class Implementation(_StatusValue):
        """描述 Implement Agent 归一化后的执行结果。"""

        IMPLEMENTED = "implemented"
        FAILED = "implementation_failed"

    class Actor(_StatusValue):
        """描述长生命周期 ImplementActor 的调度状态。"""

        READY = "ready"
        RUNNING = "running"
        WAITING = "waiting"
        WAITING_EVALUATION = "waiting_evaluation"
        REPAIR_READY = "repair_ready"
        REFINE_READY = "refine_ready"
        EXHAUSTED = "exhausted"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"

    class Candidate(_StatusValue):
        """描述冻结 Candidate 从提交到评测完成的状态。"""

        QUEUED = "queued"
        WAITING_RESOURCES = "waiting_resources"
        RUNNING = "running"
        CANCELLED = "cancelled"
        RUN_FAILED = "run_failed"
        VALIDATION_FAILED = "validation_failed"
        EVALUATION_FAILED = "evaluation_failed"
        VERIFIER_FAILED = "validity_verifier_failed"
        BUGGY = "buggy_solution"
        EVALUATED = "evaluated"

    class Branch(_StatusValue):
        """描述 ResearchState 中面向用户展示的分支进度。"""

        BENCHMARK_ATTEMPT_QUEUED = "benchmark_attempt_queued"
        EVALUATION_QUEUED = "evaluation_queued"
        WAITING_RESOURCES = "waiting_resources"
        EVALUATION_RUNNING = "evaluation_running"
        ANALYSIS_QUEUED = "analysis_queued"
        RETRY_QUEUED = "retry_queued"
        EVALUATED = "evaluated"
        ARCHIVED = "archived"
        ENGINEERING_FAILED = "engineering_failed"
        FAILED = "failed"
        PAPER_CANDIDATE = "paper_candidate"
        ANALYZED = "analyzed"
        CANCELLED = "cancelled"

    class Outcome(_StatusValue):
        """描述经验池中一次研究决策的结果标签。"""

        EVALUATED = "evaluated"
        PROMOTED = "promoted"
        FAILED = "failed"

    class Workspace(_StatusValue):
        """描述 Agent 分支工作区自身的初始化状态。"""

        CREATED = "created"

    # 终态集合供同步和异步调度器共用，避免各处分别维护不同版本。
    RESEARCH_TERMINAL = frozenset(
        {
            Research.PAUSED,
            Research.STOPPED,
            Research.COMPLETED,
            Research.FAILED,
        }
    )
    RESEARCH_EXTERNAL_CONTROL = frozenset({Research.PAUSED, Research.STOPPED})


__all__ = ["LoopStatus"]
