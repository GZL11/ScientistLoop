"""通用 Agent DAG 的稳定领域 contract。

这个模块只描述状态、节点调用和结果，不包含 NatureBench 或 Terminal-Bench
的业务逻辑。具体 Graph 通过 :class:`AgentGraph` 注入到统一执行器。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class GraphContext:
    """Graph 可用的公共运行上下文。"""

    run_id: str
    run_dir: Path
    workspace_dir: Path
    task_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回可审计的上下文，不主动展开隐藏设施对象。"""

        value = asdict(self)
        value["run_dir"] = str(self.run_dir)
        value["workspace_dir"] = str(self.workspace_dir)
        value["metadata"] = dict(self.metadata)
        return value


@dataclass(frozen=True)
class GraphState:
    """可恢复的 Graph 状态快照。"""

    graph_name: str
    graph_version: str
    phase: str
    status: str = "running"
    revision: int = 0
    data: Mapping[str, Any] = field(default_factory=dict)
    completed_nodes: tuple[str, ...] = ()

    @property
    def terminal(self) -> bool:
        """判断 Graph 是否已经进入终态。"""

        return self.status in {"completed", "failed", "stopped", "timed_out"}

    def is_completed(self, invocation_id: str) -> bool:
        """判断一次节点调用是否已经成功提交过。"""

        return invocation_id in self.completed_nodes

    def mark_completed(self, invocation_id: str) -> "GraphState":
        """以幂等方式标记节点完成。"""

        if self.is_completed(invocation_id):
            return self
        return replace(
            self,
            completed_nodes=(*self.completed_nodes, invocation_id),
            revision=self.revision + 1,
        )

    def with_updates(self, **updates: Any) -> "GraphState":
        """创建更新后的状态，并自动递增 revision。"""

        updates.setdefault("revision", self.revision + 1)
        return replace(self, **updates)

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典。"""

        value = asdict(self)
        value["data"] = dict(self.data)
        value["completed_nodes"] = list(self.completed_nodes)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GraphState":
        """从持久化快照恢复状态。"""

        return cls(
            graph_name=str(value["graph_name"]),
            graph_version=str(value.get("graph_version") or "1"),
            phase=str(value.get("phase") or "created"),
            status=str(value.get("status") or "running"),
            revision=int(value.get("revision") or 0),
            data=dict(value.get("data") or {}),
            completed_nodes=tuple(str(item) for item in value.get("completed_nodes", ())),
        )


@dataclass(frozen=True)
class NodeInvocation:
    """一次可调度的节点调用。"""

    invocation_id: str
    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典。"""

        value = asdict(self)
        value["payload"] = dict(self.payload)
        return value

@dataclass(frozen=True)
class NodeResult:
    """节点执行结果，允许 Graph 自己决定失败如何转移。"""

    invocation_id: str
    kind: str
    status: str
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典。"""

        value = asdict(self)
        value["output"] = dict(self.output)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NodeResult":
        """从 pending/checkpoint 文件恢复节点结果。"""

        return cls(
            invocation_id=str(value["invocation_id"]),
            kind=str(value["kind"]),
            status=str(value.get("status") or "failed"),
            output=dict(value.get("output") or {}),
            error=value.get("error"),
            duration_ms=(
                int(value["duration_ms"])
                if value.get("duration_ms") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class GraphOutput:
    """Graph 结束时交给 Harness 的领域无关结果。"""

    status: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON 兼容字典。"""

        value = asdict(self)
        value["payload"] = dict(self.payload)
        return value


class AgentGraph(Protocol):
    """可插拔 Agent DAG 的最小 contract。"""

    name: str
    version: str

    def initialize(self, context: GraphContext) -> GraphState:
        """创建初始状态。"""

    def ready(self, state: GraphState) -> Sequence[NodeInvocation]:
        """返回当前可以并行调度的节点。"""

    def apply(self, state: GraphState, result: NodeResult) -> GraphState:
        """将一个节点结果归约到 Graph 状态。"""

    def output(self, state: GraphState) -> GraphOutput:
        """构造最终输出。"""


class NodeRunner(Protocol):
    """节点执行器；Infra 负责调度，Graph 不直接管理进程。"""

    def __call__(
        self,
        invocation: NodeInvocation,
        context: GraphContext,
    ) -> NodeResult:
        """执行一次节点调用。"""


__all__ = [
    "AgentGraph",
    "GraphContext",
    "GraphOutput",
    "GraphState",
    "NodeInvocation",
    "NodeResult",
    "NodeRunner",
]
