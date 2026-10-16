"""Graph 状态快照与节点事件的原子存储。"""
from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Iterable

from ..domain.graph import GraphState, NodeResult
from ..utils import append_jsonl, atomic_write_json, read_json


class GraphStateStore:
    """为一个 Run 保存可恢复的 Graph 状态。"""

    def __init__(self, run_dir: str | Path):
        self.root = Path(run_dir) / "controller" / "graph"
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"
        self.pending_root = self.root / "pending"
        self._lock = RLock()
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self) -> GraphState | None:
        """读取当前状态；不存在时返回 None。"""

        with self._lock:
            raw = read_json(self.state_path)
            return GraphState.from_dict(raw) if raw else None

    def initialize(self, state: GraphState) -> GraphState:
        """初始化状态，拒绝覆盖已有运行。"""

        with self._lock:
            existing = self.load()
            if existing is not None:
                return existing
            atomic_write_json(self.state_path, state.to_dict())
            append_jsonl(
                self.events_path,
                {"type": "graph_initialized", "state": state.to_dict()},
            )
            return state

    def commit(self, state: GraphState, results: Iterable[NodeResult]) -> GraphState:
        """原子保存状态并追加本批节点结果。"""

        result_list = list(results)
        with self._lock:
            previous = self.load()
            if previous is not None and state.revision < previous.revision:
                raise ValueError(
                    f"Graph revision 回退: current={state.revision}, previous={previous.revision}"
                )
            atomic_write_json(self.state_path, state.to_dict())
            for result in result_list:
                append_jsonl(
                    self.events_path,
                    {
                        "type": "node_completed",
                        "revision": state.revision,
                        "result": result.to_dict(),
                    },
                )
            return state

    def record_pending(self, result: NodeResult) -> None:
        """在批次栅栏提交前保存已完成的单节点结果。"""

        with self._lock:
            self.pending_root.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                self.pending_root / f"{result.invocation_id}.json",
                result.to_dict(),
            )

    def load_pending(self) -> dict[str, NodeResult]:
        """读取上次 Controller 中断前已返回、尚未归约的节点结果。"""

        if not self.pending_root.is_dir():
            return {}
        results: dict[str, NodeResult] = {}
        for path in sorted(self.pending_root.glob("*.json")):
            raw = read_json(path)
            if not isinstance(raw, dict):
                continue
            try:
                result = NodeResult.from_dict(raw)
            except (KeyError, TypeError, ValueError):
                continue
            results[result.invocation_id] = result
        return results

    def clear_pending(self, invocation_id: str) -> None:
        """节点已归约后清理其 pending 结果；重复清理是幂等的。"""

        path = self.pending_root / f"{invocation_id}.json"
        with self._lock:
            if path.is_file():
                path.unlink()

    def read_events(self) -> list[dict]:
        """读取事件日志，供审计和恢复测试使用。"""

        if not self.events_path.exists():
            return []
        from ..utils import read_jsonl

        return read_jsonl(self.events_path)


__all__ = ["GraphStateStore"]
