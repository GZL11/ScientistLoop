"""与业务 Graph 解耦的持久化节点执行器。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time
from typing import Mapping

from ..domain.graph import (
    AgentGraph,
    GraphContext,
    GraphOutput,
    NodeInvocation,
    NodeResult,
    NodeRunner,
)
from ..storage.graph_state import GraphStateStore


@dataclass(frozen=True)
class GraphExecutorConfig:
    """Graph Executor 的通用调度限制。"""

    max_workers: int = 2
    max_steps: int = 10_000

    def normalized(self) -> "GraphExecutorConfig":
        return GraphExecutorConfig(
            max_workers=max(1, int(self.max_workers)),
            max_steps=max(1, int(self.max_steps)),
        )


class GraphExecutor:
    """执行任意实现了 AgentGraph contract 的 DAG。"""

    def __init__(
        self,
        graph: AgentGraph,
        runners: Mapping[str, NodeRunner],
        *,
        state_store: GraphStateStore,
        config: GraphExecutorConfig | None = None,
    ) -> None:
        self.graph = graph
        self.runners = dict(runners)
        self.state_store = state_store
        self.config = (config or GraphExecutorConfig()).normalized()

    def run(self, context: GraphContext) -> GraphOutput:
        """运行 Graph；已有状态会从 checkpoint 恢复。"""

        state = self.state_store.load()
        if state is None:
            state = self.state_store.initialize(self.graph.initialize(context))
        if state.graph_name != self.graph.name or state.graph_version != self.graph.version:
            raise ValueError(
                "Graph 版本与已有 checkpoint 不匹配: "
                f"stored={state.graph_name}/{state.graph_version}, "
                f"requested={self.graph.name}/{self.graph.version}"
            )

        steps = 0
        while not state.terminal:
            steps += 1
            if steps > self.config.max_steps:
                raise RuntimeError("Graph 超过 max_steps，疑似存在无界状态循环")
            invocations = [
                item
                for item in self.graph.ready(state)
                if not state.is_completed(item.invocation_id)
            ]
            if not invocations:
                raise RuntimeError(
                    f"Graph 在非终态没有可执行节点: phase={state.phase}, revision={state.revision}"
                )
            pending = self.state_store.load_pending()
            pending_results = {
                item.invocation_id: pending[item.invocation_id]
                for item in invocations
                if item.invocation_id in pending
            }
            to_run = [
                item for item in invocations if item.invocation_id not in pending_results
            ]
            fresh_results = self._run_batch(to_run, context) if to_run else []
            result_by_id = {
                result.invocation_id: result
                for result in (*pending_results.values(), *fresh_results)
            }
            results = [result_by_id[item.invocation_id] for item in invocations]
            for result in results:
                state = self.graph.apply(state, result)
                state = state.mark_completed(result.invocation_id)
            self.state_store.commit(state, results)
            for result in results:
                self.state_store.clear_pending(result.invocation_id)
        return self.graph.output(state)

    def _run_batch(
        self,
        invocations: list[NodeInvocation],
        context: GraphContext,
    ) -> list[NodeResult]:
        """并行执行本批节点，并将异常转换为结构化失败。"""

        if len(invocations) == 1:
            result = self._run_one(invocations[0], context)
            self.state_store.record_pending(result)
            return [result]
        results: dict[str, NodeResult] = {}
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures = {
                pool.submit(self._run_one, invocation, context): invocation
                for invocation in invocations
            }
            for future in as_completed(futures):
                invocation = futures[future]
                result = future.result()
                self.state_store.record_pending(result)
                results[invocation.invocation_id] = result
        return [results[item.invocation_id] for item in invocations]

    def _run_one(self, invocation: NodeInvocation, context: GraphContext) -> NodeResult:
        runner = self.runners.get(invocation.kind)
        if runner is None:
            return NodeResult(
                invocation_id=invocation.invocation_id,
                kind=invocation.kind,
                status="failed",
                error=f"没有注册节点 runner: {invocation.kind}",
            )
        started = time.monotonic()
        try:
            result = runner(invocation, context)
            if result.invocation_id != invocation.invocation_id:
                raise ValueError(
                    "NodeRunner 返回了错误 invocation_id: "
                    f"expected={invocation.invocation_id}, actual={result.invocation_id}"
                )
            return result
        except Exception as exc:  # noqa: BLE001 - 节点边界必须结构化失败
            return NodeResult(
                invocation_id=invocation.invocation_id,
                kind=invocation.kind,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )


__all__ = ["GraphExecutor", "GraphExecutorConfig"]
