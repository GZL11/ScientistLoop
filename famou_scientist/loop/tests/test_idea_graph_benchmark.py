"""`--idea-graph`：benchmark 工作流里的 Idea 图（idea→idea 派生边）。

背景：20260915 作业守则首测发现 10/10 题 `expbank/IDEAS.md` 都是「暂无 Idea」。
根因不是 bug，而是两条工作流的有意分叉——`benchmark_managed=True` 的 run 在读
（`_research_idea_context`）与写（`submit` / `link_attempt` / `record_implementation`）
四处都被 `not self.benchmark_managed` 显式排除，于是提示词里「如果请求包含
`idea_runtime.idea_graph_dir`，先读 IDEAS.md」是一条条件永不成立的死分支。

现由 `--idea-graph` 控制，默认仍关闭。两条边界：

1. **默认必须不变**。关闭时的行为要与改动前逐字节一致，否则 A/B 的对照臂就不是
   20260915 的那个配置了，整个配对实验失去意义。
2. **图绝不能杀 run**。它是上下文层：写失败、id 撞车都只能降级，不能让这次
   attempt 排不进队列。4 小时的作业不该死在一个辅助索引上。
"""
from __future__ import annotations

import argparse
import inspect

import pytest

from famou_scientist.loop.harness.cli import _build_parser
from famou_scientist.loop.harness.runtime import HarnessConfig
from famou_scientist.loop.runtime.orchestrator import Orchestrator, OrchestratorConfig


BASE = [
    "run",
    "--task-id",
    "t",
    "--run-dir",
    "/tmp/x",
    "--evaluator-channel",
    "/tmp/ch",
]


# --- 开关贯通 -------------------------------------------------------------


def test_cli_defaults_to_off():
    """默认开会静默改变此前所有 NatureBench 批次的行为。"""

    assert _build_parser().parse_args(BASE).idea_graph is False


def test_cli_flag_turns_it_on():
    assert _build_parser().parse_args([*BASE, "--idea-graph"]).idea_graph is True
    assert _build_parser().parse_args([*BASE, "--no-idea-graph"]).idea_graph is False


def test_harness_and_orchestrator_default_to_off():
    config = HarnessConfig(
        task_id="t",
        run_dir="/tmp/x",
        problem_dir="/tmp/x/problem",
        workspace_dir="/tmp/x/workspace",
        agent_runtime="claude",
    )
    assert config.idea_graph is False
    assert OrchestratorConfig().idea_graph_enabled is False


def test_every_hop_of_the_chain_is_connected():
    """漏接一层就会静默退回默认，而要跑满 4 小时才看得出来。"""

    cli_source = inspect.getsource(
        __import__("famou_scientist.loop.harness.cli", fromlist=["_build_parser"])
    )
    assert "idea_graph=args.idea_graph" in cli_source

    runtime_source = inspect.getsource(
        __import__(
            "famou_scientist.loop.harness.runtime", fromlist=["BenchmarkHarness"]
        )
    )
    assert "idea_graph_enabled=self.config.idea_graph" in runtime_source


# --- 判据 -----------------------------------------------------------------


def _orchestrator(*, benchmark_managed: bool, enabled: bool):
    obj = Orchestrator.__new__(Orchestrator)
    obj.config = OrchestratorConfig(idea_graph_enabled=enabled)
    obj.benchmark_managed = benchmark_managed
    return obj


@pytest.mark.parametrize("enabled", [True, False])
def test_research_workflow_is_never_gated_by_the_flag(enabled):
    """开放科研路径一直有图，这个开关只管 benchmark 那条分叉。"""

    assert _orchestrator(benchmark_managed=False, enabled=enabled)._idea_graph_active()


def test_benchmark_workflow_follows_the_flag():
    assert not _orchestrator(benchmark_managed=True, enabled=False)._idea_graph_active()
    assert _orchestrator(benchmark_managed=True, enabled=True)._idea_graph_active()


def test_all_graph_call_sites_share_one_predicate():
    """四处判据必须共用 _idea_graph_active，漏改一处就等于图半通。

    跨任务经验库那次「三个关口靠手抄副本保持同步」的教训：靠注释维系的不变量
    会在下一次改动里悄悄裂开。这里改成源码级断言。
    """

    source = inspect.getsource(Orchestrator)
    for call in ("link_attempt(", "record_implementation("):
        for idx in _positions(source, call):
            window = source[max(0, idx - 400) : idx]
            assert "self._idea_graph_active()" in window, (
                f"{call} 的守卫不是 _idea_graph_active，图会在这一处半通"
            )
            assert "if not self.benchmark_managed:" not in window.rsplit(
                "self._idea_graph_active()", 1
            )[-1]


def _positions(text: str, needle: str) -> list[int]:
    out: list[int] = []
    start = 0
    while (idx := text.find(needle, start)) >= 0:
        out.append(idx)
        start = idx + 1
    assert out, f"没找到 {needle}，测试需要跟着源码同步"
    return out


# --- 读：idea_runtime 是否进请求 -------------------------------------------


class _Queue:
    def __init__(self, size: int = 0):
        self._size = size

    def size(self, status=None):
        del status
        return self._size

    def list(self, status=None):
        del status
        return []


class _Queues:
    def __init__(self):
        self.benchmark_attempt = _Queue()
        self.ideaspark = _Queue()


class _ExplodingGraph:
    """关闭时一旦被碰到就炸，用来证明对照臂真的零改动。"""

    expbank_root = "/should/not/be/read"
    index_path = "/should/not/be/read"

    def __getattr__(self, name):
        raise AssertionError(f"关闭 Idea 图后不应调用 idea_graph.{name}")


class _FakeGraph:
    def __init__(self, submit_error: Exception | None = None):
        self.submit_error = submit_error
        self.submitted: list[dict] = []
        self.admitted: list[str] = []
        self.expbank_root = "/ws/expbank"
        self.index_path = "/ws/expbank/IDEAS.md"

    def submit(self, idea, **kwargs):
        del kwargs
        if self.submit_error is not None and not self.submitted:
            self.submitted.append(dict(idea))
            error, self.submit_error = self.submit_error, None
            raise error
        self.submitted.append(dict(idea))
        return {}

    def admit_without_review(self, idea_id, **kwargs):
        del kwargs
        self.admitted.append(idea_id)
        return {}

    def latest_review(self, *, actor_id=None):
        del actor_id
        return None


class _Artifacts:
    def __init__(self):
        self.decisions: list[dict] = []

    def record_decision(self, payload, refs=None):
        del refs
        self.decisions.append(dict(payload))
        return f"decision:{len(self.decisions)}"

    def save_json(self, kind, payload):
        del payload
        return f"{kind}:1"


def _request_orchestrator(enabled: bool, graph):
    obj = Orchestrator.__new__(Orchestrator)
    obj.config = OrchestratorConfig(idea_graph_enabled=enabled)
    obj.benchmark_managed = True
    obj.queues = _Queues()
    obj.goal_doc = {"constraints": {}}
    obj.idea_graph = graph
    obj._benchmark_attempt_limit = lambda state: None
    obj._idea_experience = lambda top_k=5: []
    obj._idea_debate_directive = lambda state: None

    class _ExpBank:
        root = "/ws/expbank"

    obj.expbank = _ExpBank()
    return obj


def test_request_omits_idea_runtime_when_disabled():
    """对照臂：请求里不能出现 idea_runtime，提示词那条分支才保持不成立。"""

    obj = _request_orchestrator(False, _ExplodingGraph())
    request = obj._prepare_benchmark_idea_request({})

    assert request is not None
    assert "idea_runtime" not in request["idea_context"]


def test_request_carries_the_graph_paths_when_enabled():
    obj = _request_orchestrator(True, _FakeGraph())
    request = obj._prepare_benchmark_idea_request({})

    runtime = request["idea_context"]["idea_runtime"]
    assert runtime["idea_graph_dir"] == "/ws/expbank"
    assert runtime["idea_graph_index"] == "/ws/expbank/IDEAS.md"
    assert runtime["actor_id"] == "idea_agent_main"
    # benchmark 没有 Judge，record_review 从不被调用，这一项恒为 None。
    assert runtime["last_review"] is None


# --- 写：排程时是否落节点 --------------------------------------------------


def _node_orchestrator(enabled: bool, graph):
    obj = Orchestrator.__new__(Orchestrator)
    obj.config = OrchestratorConfig(idea_graph_enabled=enabled)
    obj.benchmark_managed = True
    obj.idea_graph = graph
    obj.artifacts = _Artifacts()
    obj.log = lambda msg: None
    obj._goal_contract_version = lambda: "v-test"
    return obj


def test_node_is_not_written_when_disabled():
    obj = _node_orchestrator(False, _ExplodingGraph())
    attempt = {"id": "idea-1", "title": "t"}

    obj._record_benchmark_idea_node(attempt)

    assert attempt["id"] == "idea-1"
    assert obj.artifacts.decisions == []


def test_node_is_submitted_and_admitted_when_enabled():
    """benchmark 无 Gate：走 admit_without_review，不伪造 verdict=pass。"""

    graph = _FakeGraph()
    obj = _node_orchestrator(True, graph)
    attempt = {"id": "idea-1", "title": "t"}

    obj._record_benchmark_idea_node(attempt)

    assert [i["id"] for i in graph.submitted] == ["idea-1"]
    assert graph.admitted == ["idea-1"]
    assert obj.artifacts.decisions[0]["decision"] == "enqueue_without_gate"


def test_duplicate_id_is_reissued_instead_of_dropping_the_attempt():
    """图一旦可见，Agent 就可能照抄一个已存在的 id。"""

    graph = _FakeGraph(submit_error=FileExistsError("dup"))
    obj = _node_orchestrator(True, graph)
    attempt = {"id": "idea-1", "title": "t"}

    obj._record_benchmark_idea_node(attempt)

    assert attempt["id"] != "idea-1", "撞车后必须换号"
    assert graph.admitted == [attempt["id"]]


def test_graph_failure_never_propagates():
    """图写不进去也不能影响排程——4 小时的作业不该死在一个辅助索引上。"""

    class _AlwaysFails(_FakeGraph):
        def submit(self, idea, **kwargs):
            raise RuntimeError("disk full")

    obj = _node_orchestrator(True, _AlwaysFails())
    attempt = {"id": "idea-1", "title": "t"}

    obj._record_benchmark_idea_node(attempt)  # 不抛

    assert attempt["id"] == "idea-1"


def test_node_is_recorded_before_the_attempt_is_serialized():
    """撞车改号必须发生在 artifact / 队列拿到 id 之前，否则两边对不上。"""

    source = inspect.getsource(Orchestrator._schedule_one_benchmark_idea)
    node_at = source.find("_record_benchmark_idea_node")
    save_at = source.find('save_json("benchmark_attempt"')
    push_at = source.find("queue.push(")

    assert node_at > 0 and save_at > 0 and push_at > 0
    assert node_at < save_at < push_at
