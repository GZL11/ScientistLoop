"""方案演化图 v2：图结构 + 算子库 + 带海拔的节点。

设计文档：`docs/design/EVOLUTION_GRAPH_V2_CN.md`

上一批（`20260915-idea-graph-ab-10x2`）的结论是「图接通了，agent 也确实在读，但
读完没有改变它的行为」——Δ 中位数 +0.0061，符号检验 p=0.7539，10 题无一走出噪声。
最能说明问题的 `s41587-024-02428-4` 沿着图挖了九层，**全程没有任何信号告诉它这个
方向在变好还是变坏**。v2 要补的就是那个信号。

三条边界，逐条有测：

1. **对照臂必须逐字节不变**。v1 是上一批的对照臂配置，`make_idea_graph` 默认返回
   v1，且 v1 绝不创建 `expbank/graph/`。否则配对实验失去意义。
2. **20 个调用点不能静默断链**。v2 把 v1 的八个公开方法签名逐字实现，用
   `inspect.signature` 卡死。
3. **图绝不能杀 run**。算子非法只能 coerce + 记账，不能抛异常让 attempt 排不进
   队列。4 小时的作业不该死在一个辅助索引上。
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
from pathlib import Path

import pytest

from famou_scientist.loop.storage.evolution_graph import (
    BRIEF_LIMIT,
    _width,
    DEFAULT_GRAPH_VERSION,
    ROOT_ID,
    SEQ_WIDTH,
    EvolutionGraphStore,
    IdeaGraphV1Facade,
    format_seq,
    make_idea_graph,
    validate_operator,
)
from famou_scientist.loop.runtime.orchestrator import (
    OPERATOR_RETRY_LIMIT,
    Orchestrator,
    OrchestratorConfig,
)
from famou_scientist.loop.harness.cli import _build_parser
from famou_scientist.loop.harness.runtime import HarnessConfig
from famou_scientist.loop.storage.expbank import ExpBank
from famou_scientist.loop.storage.idea_graph import IdeaGraphStore

#: `harness/cli.py` 的 run 子命令必填参数，凑够它才谈得上校验别的 flag。
BASE_ARGS = [
    "run",
    "--task-id",
    "t",
    "--run-dir",
    "/tmp/x",
    "--evaluator-channel",
    "/tmp/ch",
]

#: v1 的八个公开方法。v2 必须逐字同签名，否则 orchestrator 里那 20 个调用点会在
#: v2 臂上静默断链——而图的写入全都裹在 `except Exception` 里，断了不会报错，
#: 只会安静地少写节点。
V1_METHODS = (
    "submit",
    "begin_review",
    "admit_without_review",
    "record_review",
    "read",
    "latest_review",
    "link_attempt",
    "record_implementation",
)


def _v2(tmp_path) -> EvolutionGraphStore:
    return make_idea_graph(tmp_path / "ws", version="v2")


def _seed(store: EvolutionGraphStore) -> None:
    """A ← B（利用），C 另开一个方向，D 融合 B+C。

    每个都带 `mechanism`——`_valid_idea()` 强制它非空，索引里那一句话就取自它。
    """

    store.submit({"id": "A", "title": "全新算法", "mechanism": "换一套损失函数",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "B", "title": "微调 A", "mechanism": "把 A 的核宽调成自适应",
                  "operator": "exploit", "parents": ["A"]})
    store.submit({"id": "C", "title": "另一个方向", "mechanism": "改走测地距离",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "D", "title": "融合 B+C", "mechanism": "预测级加权平均",
                  "operator": "cross", "parents": ["B", "C"]})


# --- 保护对照臂 -----------------------------------------------------------


def test_factory_defaults_to_v1(tmp_path):
    """默认开 v2 会静默改变后续一切 run 的行为。"""

    store = make_idea_graph(tmp_path / "ws")
    assert DEFAULT_GRAPH_VERSION == "v1"
    assert isinstance(store, IdeaGraphStore)
    assert not isinstance(store, EvolutionGraphStore)


def test_v1_never_creates_graph_dir(tmp_path):
    """v1 臂的磁盘布局必须与改动前一致。"""

    workspace = tmp_path / "ws"
    store = make_idea_graph(workspace, version="v1")
    store.submit({"title": "x", "mechanism": "y"})
    assert not (workspace / "expbank" / "graph").exists()
    assert not (workspace / "expbank" / "GRAPH.md").exists()
    assert (workspace / "expbank" / "IDEAS.md").is_file()


def test_v2_never_touches_v1_layout(tmp_path):
    """v2 与 v1 物理隔离：`IDEAS.md` / `ideas/` 一个字节都不碰。"""

    workspace = tmp_path / "ws"
    store = make_idea_graph(workspace, version="v2")
    _seed(store)
    assert not (workspace / "expbank" / "IDEAS.md").exists()
    assert not (workspace / "expbank" / "ideas").exists()
    assert (workspace / "expbank" / "graph" / f"{ROOT_ID}.json").is_file()


def test_v1_facade_noops_never_raise(tmp_path):
    """新调用点在 v1 臂上也要能无条件调用，不必在 orchestrator 里手抄版本判断。"""

    store = make_idea_graph(tmp_path / "ws", version="v1")
    assert isinstance(store, IdeaGraphV1Facade)
    assert store.record_attempt_result("x", "0001", score=1.0) == {}
    assert store.register_weights("x", "0001", {"dir": "d"}) == {}
    assert store.top_scored(5) == []
    assert store.frontier() == []
    assert store.fusable_attempts("x") == []


def test_unknown_version_raises(tmp_path):
    """非法值在 harness 层抛错、orchestrator 层钳默认，走到工厂就是代码 bug。"""

    with pytest.raises(ValueError):
        make_idea_graph(tmp_path / "ws", version="v3")


# --- 防 20 个调用点静默断链 -----------------------------------------------


@pytest.mark.parametrize("name", V1_METHODS)
def test_v2_matches_v1_signature(name):
    assert inspect.signature(getattr(EvolutionGraphStore, name)) == inspect.signature(
        getattr(IdeaGraphStore, name)
    )


# --- 虚拟 root 与多父 ------------------------------------------------------


def test_root_is_a_real_node(tmp_path):
    """ROOT 写成真实节点文件，不是特判的保留字。"""

    store = _v2(tmp_path)
    root = store.read(ROOT_ID)
    assert root["operator"] is None and root["parents"] == []


def test_root_branch_follows_the_first_innovate(tmp_path):
    store = _v2(tmp_path)
    _seed(store)
    assert store.read("A")["root_branch"] == "A"
    assert store.read("B")["root_branch"] == "A"
    # 交叉节点确实同时属于多个方向，硬塞一个会误导「这条方向走通了」的判断
    assert store.read("D")["root_branch"] == "A+C"


def test_cross_keeps_every_parent(tmp_path):
    """v1 的 `parent_idea_id` 是单字符串，图永远塌成树。"""

    store = _v2(tmp_path)
    _seed(store)
    assert store.parents("D") == ["B", "C"]


# --- 算子校验 --------------------------------------------------------------


@pytest.mark.parametrize(
    "idea",
    [
        {"operator": "innovate", "parents": [ROOT_ID]},
        {"operator": "exploit", "parents": ["A"]},
        {"operator": "cross", "parents": ["A", "B"]},
    ],
)
def test_legal_operators_pass(idea):
    assert validate_operator(idea, {ROOT_ID, "A", "B"}).ok


@pytest.mark.parametrize(
    "idea",
    [
        {"parents": ["A"]},                                   # operator 缺失
        {"operator": "refine", "parents": ["A"]},             # 不在词表里
        {"operator": "innovate", "parents": ["A"]},           # 创新带父
        {"operator": "exploit", "parents": []},               # 利用 0 父
        {"operator": "exploit", "parents": ["A", "B"]},       # 利用 2 父
        {"operator": "cross", "parents": ["A"]},              # 交叉 1 父
        {"operator": "exploit", "parents": ["NOPE"]},         # 父不存在
    ],
)
def test_illegal_operators_are_rejected(idea):
    check = validate_operator(idea, {ROOT_ID, "A", "B"})
    assert not check.ok and check.reason


def test_self_reference_is_rejected():
    check = validate_operator(
        {"operator": "exploit", "parents": ["X"]}, {ROOT_ID, "X"}, node_id="X"
    )
    assert not check.ok and "指向自己" in check.reason


def test_cycle_is_rejected_at_write_time(tmp_path):
    """环路在写入时拒绝，不在事后剪枝——事后剪等于图里本来就存着脏数据。"""

    store = _v2(tmp_path)
    _seed(store)
    assert store.would_cycle("A", ["B"]) == ["B"]      # B 的祖先里有 A
    assert store.would_cycle("A", ["C"]) == []
    check = validate_operator(
        {"operator": "exploit", "parents": ["B"]},
        store._known_ids(),
        node_id="A",
        cycle_probe=store.would_cycle,
    )
    assert not check.ok and "成环" in check.reason


def test_illegal_operator_is_rejected_not_rewritten(tmp_path):
    """宿主不替 agent 改算子。

    改了它就永远不知道自己填错了，下次照错；图上还会多出一条它没打算建立的边，
    后来读图的人分不出哪些边是 agent 真提的。合法性由 orchestrator 在提交时保证，
    所以走到 store 的非法值是调用方的 bug，该响。
    """

    store = _v2(tmp_path)
    _seed(store)
    with pytest.raises(ValueError, match="算子非法"):
        store.submit({"id": "E", "title": "自称交叉", "operator": "cross",
                      "parents": ["A"]})
    # 抛了就不能留下半条记录
    with pytest.raises(FileNotFoundError):
        store.read("E")


def test_v7_shaped_idea_still_lands_a_real_edge(tmp_path):
    """版本阶梯漂移过一次；v7 的单父字段进来时，别把整张图拍平成创新节点。"""

    store = _v2(tmp_path)
    _seed(store)
    node = store.submit({"id": "E", "title": "老格式", "parent_idea_id": "A"})
    assert node["operator"] == "exploit" and node["parents"] == ["A"]


def test_v7_fallback_is_not_silent(tmp_path):
    """回退命中要留在节点上——v8 下命中即说明某处提示词或调用点没跟上。

    只打日志不行：日志跑完散在容器 stdout 里，审计脚本没法按节点把它数出来。
    """

    from famou_scientist.loop.storage.evolution_graph import (
        LEGACY_PARENT_FIELD_NOTE,
    )

    store = _v2(tmp_path)
    _seed(store)
    legacy = store.submit({"id": "E", "title": "老格式", "parent_idea_id": "A"})
    assert LEGACY_PARENT_FIELD_NOTE in legacy["operator_notes"]
    # 合法的 v8 载荷不该被打上这个标记——它是链路读数，不是算子读数。
    fresh = store.submit(
        {"id": "F", "title": "新格式", "operator": "exploit", "parents": ["A"]}
    )
    assert LEGACY_PARENT_FIELD_NOTE not in fresh["operator_notes"]


def test_node_record_has_no_v1_mirror_fields(tmp_path):
    """顶层不留 idea_id / parent_idea_id / relation 三个副本。

    完整载荷已经原样存在 `record["idea"]` 里，所以删掉它们零信息损失；留着的
    代价是实打实的——`relation` 在 v1 里从不校验、没有任何代码读取，上一批却
    拿它的分布写进了结论。**自报又无人读的字段会被后来者误当成证据。**
    """

    store = _v2(tmp_path)
    _seed(store)
    node = store.submit(
        {
            "id": "E",
            "title": "带遗留字段",
            "operator": "exploit",
            "parents": ["A"],
            "relation": "alternative_to",
        }
    )
    for field in ("idea_id", "parent_idea_id", "relation"):
        assert field not in node, f"节点顶层不该再有 {field}"
    # 但 agent 原样写的那一块必须一字不动地留着——包括我们不信任的 relation。
    assert node["idea"]["relation"] == "alternative_to"
    assert node["node_id"] == "E" and node["parents"] == ["A"]

    root = store.read("ROOT")
    for field in ("idea_id", "parent_idea_id"):
        assert field not in root, f"ROOT 也不该有 {field}"


# --- 分数与前沿 ------------------------------------------------------------


def test_score_backfill_updates_best_score(tmp_path):
    store = _v2(tmp_path)
    _seed(store)
    store.link_attempt("B", "0003")
    assert store.read("B")["best_score"] is None
    store.record_attempt_result("B", "0003", status="evaluated", score=0.0653)
    assert store.read("B")["best_score"] == pytest.approx(0.0653)


def test_retries_upsert_into_one_node(tmp_path):
    """`[失败, 失败, 0.0653]` 是「这条路试了三次才通」，不是三个方案。

    上一批 `s42256-025-01003-z`：16 个图节点 / 13 条 attempt / 实际只有 7 个方案。
    """

    store = _v2(tmp_path)
    _seed(store)
    for attempt, score in (("0003", None), ("0004", -0.1), ("0005", 0.0653)):
        store.link_attempt("B", attempt)
        store.record_attempt_result("B", attempt, status="evaluated", score=score)
    store.record_attempt_result("B", "0005", status="evaluated", score=0.0900)
    record = store.read("B")
    assert [item["attempt_id"] for item in record["attempts"]] == ["0003", "0004", "0005"]
    assert record["best_score"] == pytest.approx(0.0900)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), True, "0.5", None])
def test_non_finite_scores_never_become_best_score(tmp_path, score):
    """`SR` / `CR` 混不得：不是有限数值分就不算出过分。"""

    store = _v2(tmp_path)
    _seed(store)
    store.record_attempt_result("B", "0003", status="evaluated", score=score)
    assert store.read("B")["best_score"] is None


def test_frontier_is_proposed_but_never_implemented(tmp_path):
    store = _v2(tmp_path)
    _seed(store)
    store.link_attempt("B", "0003")
    assert [item["node_id"] for item in store.frontier()] == ["A", "C", "D"]
    assert ROOT_ID not in {item["node_id"] for item in store.frontier()}


def test_top_scored_ranks_by_best_score(tmp_path):
    store = _v2(tmp_path)
    _seed(store)
    store.record_attempt_result("B", "0003", status="evaluated", score=0.01)
    store.record_attempt_result("C", "0004", status="evaluated", score=0.90)
    assert [item["node_id"] for item in store.top_scored(2)] == ["C", "B"]


def _section(text: str, title: str) -> str:
    """取出 `## <title>` 到下一个 `##`（或文件尾）之间的正文。"""

    assert f"## {title}" in text, f"缺少段落：{title}\n{text}"
    body = text.split(f"## {title}", 1)[1]
    return body.split("\n## ", 1)[0]


def _rows(text: str) -> list[str]:
    """方案区里的方案行——不含它下面缩进的描述行和 id 行。

    行首是四位编号，这也是这一区唯一的对齐锚点：描述和 id 都缩进，所以
    「顶格 + 数字开头」足以把方案行挑干净。
    """

    return [
        line
        for line in _section(text, "方案").splitlines()
        if line[:SEQ_WIDTH].isdigit()
    ]


def _routes(text: str) -> list[str]:
    """路线区里的路线行。行首是 A / B / … 的行内编号。"""

    return [
        line
        for line in _section(text, "路线").splitlines()
        if re.match(r"^[A-Z]+ {2}", line)
    ]


def _row(text: str, title: str) -> str:
    """按标题取一行方案行。标题也会出现在别处（比如路线说明），所以只在方案区找。"""

    return next(line for line in _rows(text) if title in line)


# --- 索引：agent 真正读到的那张表 -----------------------------------------


def test_index_has_two_zones(tmp_path):
    """路线给方向，方案给细节入口。只有这两区，中间没有第三层。"""

    store = _v2(tmp_path)
    _seed(store)
    store.record_attempt_result("B", "0003", status="evaluated", score=0.0653)
    text = store.index_path.read_text()
    assert "## 路线" in text
    assert "## 方案" in text
    assert "+0.0653" in text          # 上一批六列里一个分数都没有
    # ROOT 只作为「没有父」的含义存在，自己不占一行
    assert not [line for line in _rows(text) if ROOT_ID in line]


def test_seq_is_assigned_at_submit_and_persisted(tmp_path):
    """编号在提出时分配、落盘、终身不变。

    渲染期现算的号看起来也能稳定，但任何改变排序的因素都会让它整体漂移一位——
    Agent 上一回合记住的 0002 下一回合指向别人。这种错不报错，只会悄悄建错边。
    """

    store = _v2(tmp_path)
    _seed(store)
    assert [store.read(node)["seq"] for node in ("A", "B", "C", "D")] == [1, 2, 3, 4]

    # 后来的节点不影响先来的号
    store.submit({"id": "E", "title": "再来一个", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    assert store.read("A")["seq"] == 1
    assert store.read("E")["seq"] == 5
    assert format_seq(store.read("E")["seq"]) == "0005"


def test_next_seq_takes_the_max_not_the_count(tmp_path):
    """下一个号是「已用最大值 + 1」，不是「节点个数 + 1」。

    按个数算的话，任何一次读取失败都会撞上已经发出去的号——而号是 Agent 拿来
    指父节点的，撞号等于改边。
    """

    store = _v2(tmp_path)
    _seed(store)
    (store.expbank_root / "graph" / "B.json").unlink()
    store.submit({"id": "E", "title": "补一个", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    assert store.read("E")["seq"] == 5      # 不是 4（那会和 D 撞号）


def test_parents_accept_the_short_number(tmp_path):
    """索引上显示的是 `NNNN`，Agent 抄下来填进 `parents` 必须能用。

    两种写法都是真地址，宿主统一解析成 node_id 再落盘——磁盘上只有一种主键。
    """

    store = _v2(tmp_path)
    _seed(store)
    store.submit({"id": "E", "title": "接着挖 A", "mechanism": "m",
                  "operator": "exploit", "parents": ["0001"]})
    assert store.read("E")["parents"] == ["A"]

    # 长 id 照样收
    store.submit({"id": "F", "title": "也接着挖 A", "mechanism": "m",
                  "operator": "exploit", "parents": ["A"]})
    assert store.read("F")["parents"] == ["A"]

    # 解析不出来的不许静默丢——走正常的「父节点不存在」校验
    with pytest.raises(ValueError, match="父节点不存在: 9999"):
        store.submit({"id": "G", "title": "指向不存在的号", "mechanism": "m",
                      "operator": "exploit", "parents": ["9999"]})


def test_routes_list_every_root_to_leaf_path(tmp_path):
    """多父节点同时属于多条路线，在每条里各出现一次。

    图结构只由这一区承载。把多父压成一条路线就等于把图压成树，而多父成立正是
    v2 相对 v1 补上的三处缺口之一。
    """

    store = _v2(tmp_path)
    _seed(store)                       # A→B→D，C→D（D 是 B+C 的 cross）
    routes = _routes(store.index_path.read_text())
    chains = [line.split("  最好")[0].split("  未出分")[0] for line in routes]
    assert any("0001 → 0002 → 0004" in chain for chain in chains)
    assert any("0003 → 0004" in chain for chain in chains)
    assert len(routes) == 2


def test_routes_rank_by_the_best_score_on_the_chain(tmp_path):
    """按链上最高分降序，没出分的沉底（不是当成 0 分插到中间）。"""

    store = _v2(tmp_path)
    store.submit({"id": "lo", "title": "低分支", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "hi", "title": "高分支", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "none", "title": "没分支", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.record_attempt_result("lo", "0001", status="evaluated", score=0.1)
    store.record_attempt_result("hi", "0002", status="evaluated", score=0.9)

    routes = _routes(store.index_path.read_text())
    assert "+0.9000" in routes[0]
    assert "+0.1000" in routes[1]
    assert "未出分" in routes[2]


def test_route_note_says_what_walking_it_further_means(tmp_path):
    """路线末尾那句是宿主算的，说的是末端的状态。

    一条链值不值得接着挖，取决于末端是「提了还没做」「做了跑挂了」还是「上一跳
    还在涨」——这三种的处置方向完全不同，不能共用一句话。
    """

    store = _v2(tmp_path)
    store.submit({"id": "p", "title": "根", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "k", "title": "子", "mechanism": "m",
                  "operator": "exploit", "parents": ["p"]})
    store.record_attempt_result("p", "0001", status="evaluated", score=0.10)

    # 末端提了还没实现
    assert "末端 0002 未实现" in _routes(store.index_path.read_text())[0]

    # 末端出了分 → 报最后一跳的涨幅，Agent 不必自己去减
    store.record_attempt_result("k", "0002", status="evaluated", score=0.30)
    assert "末端 0002 最后一跳 +0.2000" in _routes(store.index_path.read_text())[0]

    # 链上只有一个节点出分时不许写成一跳——那是在报一个不存在的差值
    lone = _v2(tmp_path / "lone")
    lone.submit({"id": "p", "title": "根", "mechanism": "m",
                 "operator": "innovate", "parents": [ROOT_ID]})
    lone.record_attempt_result("p", "0001", status="evaluated", score=0.10)
    note = _routes(lone.index_path.read_text())[0]
    assert "这条链上只有它出过分" in note and "最后一跳" not in note


def test_three_run_states_are_three_different_words(tmp_path):
    """「没跑过」/「还在跑」/「跑了没出分」必须是三个词。

    混了就等于把「还没试」说成「试了不行」，而「还没试」恰恰是最该接着挖的。
    """

    store = _v2(tmp_path)
    _seed(store)

    assert _row(store.index_path.read_text(), "微调 A").endswith("未实现")

    # link_attempt 只建空壳，还没有 status → 在跑，不是失败
    store.link_attempt("B", "0003")
    assert _row(store.index_path.read_text(), "微调 A").endswith("running")

    store.record_attempt_result("B", "0003", status="failed", score=None)
    assert _row(store.index_path.read_text(), "微调 A").endswith("failed×1")

    store.record_attempt_result("B", "0003", status="evaluated", score=0.0653)
    row = _row(store.index_path.read_text(), "微调 A")
    assert row.endswith("scored") and "+0.0653" in row


def test_unscored_is_never_rendered_as_zero(tmp_path):
    """没有分就说没有分。渲染成 0 会让它在排序里插到负分方案前面。"""

    store = _v2(tmp_path)
    _seed(store)
    assert "未出分" in _row(store.index_path.read_text(), "微调 A")
    assert "0.0000" not in store.index_path.read_text()


def test_multi_parent_rows_carry_their_parents_inline(tmp_path):
    """只有多父算子在行尾写 `← NNNN, NNNN`。

    单父的父子关系由路线区完整表达，行内再抄一遍是冗余；多父的那条边在任何一条
    路线里都只看得到一半，所以必须在行内补齐。
    """

    store = _v2(tmp_path)
    _seed(store)
    text = store.index_path.read_text()
    assert _row(text, "融合 B+C").endswith("← 0002, 0003")
    assert "←" not in _row(text, "微调 A")        # exploit 是单父


def test_every_row_carries_a_brief_and_the_long_id(tmp_path):
    """只给标题等于没给，只给编号等于打不开。

    `PROJ-Velo` 这种 agent 自编缩写三个回合之后它自己也认不出来——分数说明「这条
    路走通了」，描述才说明「走的是哪条路」。长 id 是 `graph/<id>.json` 的文件名，
    单独占一行，不混进上面那行把对齐好的列冲散。
    """

    store = _v2(tmp_path)
    _seed(store)
    lines = _section(store.index_path.read_text(), "方案").splitlines()
    for mechanism in ("换一套损失函数", "把 A 的核宽调成自适应",
                      "改走测地距离", "预测级加权平均"):
        assert f"      {mechanism}" in lines
    for node_id in ("A", "B", "C", "D"):
        assert f"      [{node_id}]" in lines


def test_the_row_itself_carries_no_bare_long_id(tmp_path):
    """方案行上只有编号，长 id 只在下面那行的方括号里。

    真实 id 形如 `idea_1789461440881_de36ffeb`，一串三十字的十六进制放进行内会
    把对齐冲散，而它对「下一步挖哪个」这个决策不提供任何信息。
    """

    store = _v2(tmp_path)
    pid, cid = "idea_1789461440881_de36ffeb", "idea_1789461440999_d871cedd"
    store.submit({"id": pid, "title": "全新算法", "mechanism": "换一套损失函数",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.link_attempt(pid, "0001")
    store.record_attempt_result(pid, "0001", status="evaluated", score=0.5)
    store.submit({"id": cid, "title": "微调核宽", "mechanism": "改成自适应",
                  "operator": "exploit", "parents": ["0001"]})
    text = store.index_path.read_text()

    for line in _rows(text) + _routes(text):
        assert pid not in line and cid not in line, line
    assert f"      [{pid}]" in text and f"      [{cid}]" in text


def test_brief_is_truncated_by_the_host_and_says_so(tmp_path):
    """截断是宿主做的，必须看得出来——而且 agent 不能靠写长描述撑爆索引。

    一句被切掉一半的 mechanism 如果读起来像完整句子，agent 会把半句话当成方案
    全貌。所以超长一律以 `…` 收尾。
    """

    store = _v2(tmp_path)
    store.submit({"id": "A", "title": "长机制", "mechanism": "机" * 5000,
                  "operator": "innovate", "parents": [ROOT_ID]})
    line = next(
        ln for ln in store.index_path.read_text().splitlines() if "机机" in ln
    )
    assert len(line.strip()) == BRIEF_LIMIT
    assert line.rstrip().endswith("…")
    # 全文仍在节点文件里，渐进式披露而不是丢信息
    assert len(store.read("A")["idea"]["mechanism"]) == 5000


def test_a_long_title_never_pushes_the_other_rows_off_screen(tmp_path):
    """标题列的对齐宽度有上限，但超宽的标题本身不截——那一行的主语就是它。

    20260915 真实标题中位 250 字符。拿它去撑别人的缩进会把整列推到屏幕外。
    """

    store = _v2(tmp_path)
    store.submit({"id": "long", "title": "超长标题" * 60, "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "short", "title": "短", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    text = store.index_path.read_text()
    assert "超长标题" * 60 in text                      # 主语一个字都不少
    assert len(_row(text, "0002  短")) < 80             # 别人没被它撑开


def test_cjk_titles_stay_in_one_column(tmp_path):
    """按显示宽度对齐，中文算两格。用 `len()` 对齐会让整列错开，等于没有列。"""

    store = _v2(tmp_path)
    store.submit({"id": "cjk", "title": "中文标题", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    store.submit({"id": "ascii", "title": "abcdefgh", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    rows = _rows(store.index_path.read_text())
    # 按**显示宽度**比，不是按字符数——后者恒不相等，测试会假失败
    columns = [_width(row.split("未出分")[0]) for row in rows]
    assert columns[0] == columns[1], rows


def test_the_structure_diagram_is_gone(tmp_path):
    """mermaid 删掉：拓扑由路线区承载，而 agent 读的是线性列表，不做图遍历。

    它对人有用，但那份用途已经被路线区覆盖，而它实测占 `GRAPH.md` 的 27%
    ——比全部描述加起来还多。
    """

    store = _v2(tmp_path)
    _seed(store)
    text = store.index_path.read_text()
    assert "mermaid" not in text and "<details>" not in text


def test_index_collapses_newlines_in_titles(tmp_path):
    """换行会把「一个方案一行」的格式撑断。

    `|` 不再转义——两区都是列表而不是表格，`|` 没有结构含义了。
    """

    store = _v2(tmp_path)
    store.submit({"id": "A", "title": "a|b\nc", "mechanism": "m",
                  "operator": "innovate", "parents": [ROOT_ID]})
    assert "0001  a|b c" in store.index_path.read_text()


# --- 融合门槛 --------------------------------------------------------------


def test_fusable_requires_finite_score_and_non_failed_status(tmp_path):
    """宿主提供引用和门槛，不生产结果——与「绝不 host 侧改分」同一条纪律。"""

    store = _v2(tmp_path)
    _seed(store)
    store.record_attempt_result("B", "0003", status="evaluated", score=0.06)
    store.record_attempt_result("B", "0004", status="failed", score=0.99)
    store.record_attempt_result("B", "0005", status="evaluated", score=None)
    assert [item["attempt_id"] for item in store.fusable_attempts("B")] == ["0003"]


def test_weights_path_is_part_of_the_node(tmp_path):
    """路径要写清楚在方案的记录里——这也属于 node 的一部分信息。"""

    store = _v2(tmp_path)
    _seed(store)
    store.link_attempt("B", "0003")
    store.register_weights("B", "0003", {"dir": "expbank/0003/weights",
                                         "framework": "torch", "files": []})
    assert store.read("B")["attempts"][0]["weights"]["dir"] == "expbank/0003/weights"


# --- 图绝不能杀 run --------------------------------------------------------


def test_duplicate_submit_refuses_to_overwrite(tmp_path):
    """撞 id 要能被上层感知并改发 id，不能静默覆盖原始提案。"""

    store = _v2(tmp_path)
    _seed(store)
    with pytest.raises(FileExistsError):
        store.submit({"id": "A", "title": "撞车", "operator": "innovate",
                      "parents": [ROOT_ID]})


def test_garbage_operator_does_not_kill_the_run(tmp_path):
    """4 小时的作业不能死在一个辅助索引上。

    store 现在对非法算子抛异常（不替 agent 改），所以"不死"这件事改由调用点负责：
    每一处 `idea_graph.submit()` 都必须在异常保护之内。这条断言守的是调用点。
    """

    store = _v2(tmp_path)
    with pytest.raises(ValueError):
        store.submit({"id": "Z", "title": "全是垃圾", "operator": 42,
                      "parents": {"weird": "shape"}})

    module = importlib.import_module(Orchestrator.__module__)
    tree = ast.parse(inspect.getsource(module))

    def submits(node) -> list[int]:
        return [
            item.lineno
            for item in ast.walk(node)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "submit"
            and ast.unparse(item.func.value) == "self.idea_graph"
        ]

    guarded = {
        line for block in ast.walk(tree) if isinstance(block, ast.Try)
        for line in submits(block)
    }
    unguarded = sorted(set(submits(tree)) - guarded)
    assert not unguarded, f"这些 submit 没有异常保护，会带着整个 run 一起死: {unguarded}"


# --- 身份归一（attempt ↔ 节点） -------------------------------------------


def test_attempt_records_its_node(tmp_path):
    """在此之前 record.json 没有 `idea_id`，一个方案在系统里没有唯一身份。"""

    bank = ExpBank(tmp_path / "ws")
    attempt_id = bank.create_attempt(idea={"title": "T"}, lineage_id="L", idea_id="A")
    assert bank.read_attempt(attempt_id)["idea_id"] == "A"


def test_index_node_column_appears_only_with_ids(tmp_path):
    """v1 从不写 `idea_id`，所以 v1 臂的 INDEX.md 逐字节不变。"""

    bank = ExpBank(tmp_path / "ws")
    bank.create_attempt(idea={"title": "T"}, lineage_id="L")
    v1_text = bank.index_path.read_text()
    assert "| ID | Idea / 方法 | 主要结果 | 分数 | 状态 | Parent |" in v1_text
    assert "节点" not in v1_text
    assert "(./IDEAS.md)" in v1_text and "GRAPH.md" not in v1_text

    bank.create_attempt(idea={"title": "U"}, lineage_id="L", idea_id="A")
    v2_text = bank.index_path.read_text()
    assert "| ID | 节点 | Idea / 方法 | 主要结果 | 分数 | 状态 | Parent |" in v2_text
    # 图换了版本，索引里的入口链接也要跟着换，否则 Agent 被指向一个不存在的文件
    assert "(./GRAPH.md)" in v2_text and "IDEAS.md" not in v2_text


def test_index_rows_stay_aligned_when_node_column_is_on(tmp_path):
    bank = ExpBank(tmp_path / "ws")
    bank.create_attempt(idea={"title": "T"}, lineage_id="L", idea_id="A")
    bank.create_attempt(idea={"title": "U"}, lineage_id="L")
    rows = [
        line for line in bank.index_path.read_text().splitlines()
        if line.startswith("| [")
    ]
    assert len(rows) == 2
    assert all(line.count("|") == 8 for line in rows)
    assert rows[0].split("|")[2].strip() == "A"
    assert rows[1].split("|")[2].strip() == "-"      # 没有节点的 attempt 留空位


# --- orchestrator 侧的接线 ------------------------------------------------


def test_orchestrator_defaults_to_v1():
    assert OrchestratorConfig().idea_graph_version == "v1"


def test_orchestrator_clamps_unknown_version():
    """宿主层抛错、orchestrator 层钳默认，是这里的既有双重校验风格。"""

    assert OrchestratorConfig(idea_graph_version="v9").idea_graph_version == "v1"
    assert OrchestratorConfig(idea_graph_version="V2").idea_graph_version == "v2"


def _orchestrator(tmp_path, version):
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.workspace = tmp_path / "ws"
    orchestrator.benchmark_managed = True
    orchestrator.config = OrchestratorConfig(
        idea_graph_enabled=True, idea_graph_version=version
    )
    orchestrator.idea_graph = make_idea_graph(orchestrator.workspace, version=version)
    return orchestrator


def test_evolution_graph_predicate_is_the_only_version_check(tmp_path):
    assert _orchestrator(tmp_path / "a", "v1")._evolution_graph() is None
    assert isinstance(
        _orchestrator(tmp_path / "b", "v2")._evolution_graph(), EvolutionGraphStore
    )


def test_evolution_graph_predicate_respects_the_master_switch(tmp_path):
    orchestrator = _orchestrator(tmp_path, "v2")
    orchestrator.config = OrchestratorConfig(
        idea_graph_enabled=False, idea_graph_version="v2"
    )
    assert orchestrator._evolution_graph() is None


def test_score_backfill_is_hooked_at_the_evaluation_write_site():
    """分数只有评测完才存在，所以 `link_attempt` 处回填拿不到分——上一批的未决问题。"""

    source = inspect.getsource(Orchestrator._process_evaluation_result)
    assert "record_attempt_result(" in source
    assert "_evolution_graph()" in source
    # 图是上下文层，不是关键路径：回填失败只能记日志
    assert "except Exception" in source


def test_identity_is_written_only_on_v2():
    source = inspect.getsource(Orchestrator._run_implementation_item)
    assert "idea_id=idea_id if self._evolution_graph() else None" in source


# --- 算子校验两段式 --------------------------------------------------------


class _Facility:
    """记录每次 generate_ideas 的上下文，并按脚本依次返回 Idea。"""

    def __init__(self, *batches):
        self.batches = [list(batch) for batch in batches]
        self.contexts: list[dict] = []

    def generate_ideas(self, context, experience):
        del experience
        self.contexts.append(context)
        if not self.batches:
            return []
        return self.batches.pop(0)


def _wired(tmp_path, version, *batches):
    orchestrator = _orchestrator(tmp_path, version)
    orchestrator.agent_facility = _Facility(*batches)
    orchestrator.logs: list[str] = []
    orchestrator.log = orchestrator.logs.append
    return orchestrator


_ILLEGAL = {"id": "E", "title": "自称交叉", "operator": "cross", "parents": ["A"]}
_LEGAL = {"id": "E", "title": "改一改", "operator": "exploit", "parents": ["A"]}


def test_illegal_operator_triggers_a_reprompt(tmp_path):
    """改对了就停——重提是给机会，不是走满次数。"""

    orchestrator = _wired(tmp_path, "v2", [_ILLEGAL], [_LEGAL])
    orchestrator.idea_graph.submit(
        {"id": "A", "title": "根", "operator": "innovate", "parents": [ROOT_ID]}
    )
    result = orchestrator._run_benchmark_idea_request({"idea_context": {}})
    assert len(orchestrator.agent_facility.contexts) == 2
    assert result["ideas"] == [_LEGAL]


def test_reprompt_carries_the_reason_back_to_the_agent(tmp_path):
    """只说「不合法」而不说哪里不合法，第二次大概率还是错的。"""

    orchestrator = _wired(tmp_path, "v2", [_ILLEGAL], [_LEGAL])
    orchestrator.idea_graph.submit(
        {"id": "A", "title": "根", "operator": "innovate", "parents": [ROOT_ID]}
    )
    orchestrator._run_benchmark_idea_request({"idea_context": {}})
    violation = orchestrator.agent_facility.contexts[1]["benchmark_runtime"][
        "operator_violation"
    ]
    assert any("cross" in reason for reason in violation["reasons"])
    assert "innovate" in violation["instruction"]
    # 第一次请求不能被污染，否则「有没有重提过」在事后就分不出来了
    assert "operator_violation" not in orchestrator.agent_facility.contexts[0].get(
        "benchmark_runtime", {}
    )


def test_legal_operator_never_costs_a_second_call(tmp_path):
    orchestrator = _wired(tmp_path, "v2", [_LEGAL], [_LEGAL])
    orchestrator.idea_graph.submit(
        {"id": "A", "title": "根", "operator": "innovate", "parents": [ROOT_ID]}
    )
    orchestrator._run_benchmark_idea_request({"idea_context": {}})
    assert len(orchestrator.agent_facility.contexts) == 1


def test_empty_reprompt_stops_asking(tmp_path):
    """重提返回空说明 Agent 这一轮不再产出，继续要下去只是空转。"""

    orchestrator = _wired(tmp_path, "v2", [_ILLEGAL], [])
    orchestrator.idea_graph.submit(
        {"id": "A", "title": "根", "operator": "innovate", "parents": [ROOT_ID]}
    )
    result = orchestrator._run_benchmark_idea_request({"idea_context": {}})
    assert len(orchestrator.agent_facility.contexts) == 2
    assert result["ideas"] == []


def test_reprompt_stops_at_the_limit_and_drops_the_idea(tmp_path):
    """到上限仍非法就丢弃——丢一条提案，好过在图里留一条假边。"""

    batches = [[_ILLEGAL] for _ in range(OPERATOR_RETRY_LIMIT + 1)]
    orchestrator = _wired(tmp_path, "v2", *batches)
    orchestrator.idea_graph.submit(
        {"id": "A", "title": "根", "operator": "innovate", "parents": [ROOT_ID]}
    )
    result = orchestrator._run_benchmark_idea_request({"idea_context": {}})
    # 首次调用 + OPERATOR_RETRY_LIMIT 次重提，最后一次的回答也要被校验
    assert len(orchestrator.agent_facility.contexts) == OPERATOR_RETRY_LIMIT + 1
    assert result["ideas"] == []
    assert any("仍非法" in line for line in orchestrator.logs)


def test_a_late_fix_still_counts(tmp_path):
    """第 3 次才改对也算数——重提的意义就是给它改的机会。"""

    orchestrator = _wired(tmp_path, "v2", [_ILLEGAL], [_ILLEGAL], [_LEGAL])
    orchestrator.idea_graph.submit(
        {"id": "A", "title": "根", "operator": "innovate", "parents": [ROOT_ID]}
    )
    result = orchestrator._run_benchmark_idea_request({"idea_context": {}})
    assert result["ideas"] == [_LEGAL]


def test_v1_arm_never_validates_operators(tmp_path):
    """对照臂多打一次 Idea Agent 就不再是 20260915 的那个配置了。"""

    orchestrator = _wired(tmp_path, "v1", [_ILLEGAL], [_LEGAL])
    result = orchestrator._run_benchmark_idea_request({"idea_context": {}})
    assert len(orchestrator.agent_facility.contexts) == 1
    assert result["ideas"] == [_ILLEGAL]
    assert orchestrator._check_operators([_ILLEGAL])[1] == []


# --- 提示词 v8 -------------------------------------------------------------

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


@pytest.mark.parametrize(
    "path",
    ["cli_agents/idea_agent_v8.md", "benchmark_managed/idea_agent_v8.md"],
)
def test_v8_defines_the_three_operators(path):
    """算子词表从未定义，是上一批 44%/63% 分布唯一合理的解释。"""

    text = (PROMPTS / path).read_text(encoding="utf-8")
    for operator in ("innovate", "exploit", "cross"):
        assert f"`{operator}`" in text
    assert "ROOT" in text and "operator_violation" in text
    # 「没跑过」和「跑了没出分」混为一谈，就等于把「还没试」说成「试了不行」。
    # 渲染侧把它们放进两个物理分开的段，提示词必须教到这一点。
    assert "最该接着挖的" in text and "试过但还没有分的" in text
    assert "「还没试」和「试了不行」不是一回事" in text


@pytest.mark.parametrize(
    "path",
    ["cli_agents/idea_agent_v8.md", "benchmark_managed/idea_agent_v8.md"],
)
def test_v8_still_describes_the_four_section_index_it_shipped_with(path):
    """v8 是**历史版本**，按它当时那个四段渲染器写的，逐字冻结。

    ⚠️ 渲染器已经换成两区（路线 / 方案），所以 **v8 提示词描述的索引现在不存在
    了**——`FAMOU_IDEA_PROMPT_VERSION=v8` 再派发，agent 会去找四个找不到的段落。
    v8 只用来复现 20260919 那批，不要拿它开新 run；新 run 用 v9。

    这条测试卡住的是「v8 别被人顺手改了」，不是「v8 和渲染器一致」——后者由
    `test_v9_describes_the_two_zones_the_renderer_actually_writes` 承担。
    """

    text = (PROMPTS / path).read_text(encoding="utf-8")
    for section in ("现在爬到哪了", "最该接着挖的", "试过但还没有分的", "全部方案"):
        assert section in text, section
    for gone in ("高分榜", "## 全图"):
        assert gone not in text, gone
    assert "节点 id 只出现在每行末尾的方括号里" in text
    assert "[自己的 id ← 父的 id…]" in text
    assert "一句话说明" in text


def test_v8_replaces_the_v7_fields():
    text = (PROMPTS / "cli_agents/idea_agent_v8.md").read_text(encoding="utf-8")
    assert '"operator"' in text and '"parents"' in text
    assert "parent_idea_id" not in text
    assert "derived_from" not in text


@pytest.mark.parametrize(
    "module, needle",
    [
        ("famou_scientist.loop.agents.workers", '"v8", "8", "operator-v8"'),
        (
            "famou_scientist.loop.execution.cli_agent_wrapper",
            "cli_agents/idea_agent_v8.md",
        ),
    ],
)
def test_both_version_ladders_know_v8(module, needle):
    """版本阶梯在两个文件里各有一份，且已经漂移过一次——这里卡死。"""

    source = Path(__import__(module, fromlist=["__file__"]).__file__).read_text(
        encoding="utf-8"
    )
    assert needle in source


# --- 开关六跳贯通 ----------------------------------------------------------

FMJOB = Path(__file__).resolve().parents[1] / "examples" / "naturebench" / "fmjob"


@pytest.mark.parametrize(
    "name, needles",
    [
        (
            "submit_one_click.sh",
            (
                # 跳 1：默认必须是 v1，这是所有历史批次共用的提交入口
                'IDEA_GRAPH_VERSION="${IDEA_GRAPH_VERSION:-v1}"',
                # 跳 2：导出给 task_entrypoint，并写进 run-config（臂标识的唯一可靠来源）
                'FAMOU_IDEA_GRAPH_VERSION="${IDEA_GRAPH_VERSION}"',
                '"idea_graph_version": os.environ.get("IDEA_GRAPH_VERSION")',
            ),
        ),
        (
            # 跳 3：转成 CLI 参数
            "task_entrypoint.sh",
            ('--idea-graph-version "${FAMOU_IDEA_GRAPH_VERSION:-v1}"',),
        ),
    ],
)
def test_shell_hops_are_connected(name, needles):
    """漏接一层就会静默退回 v1，而要跑满 4 小时才看得出来。"""

    text = (FMJOB / name).read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, f"{name} 漏接：{needle}"


def test_cli_hop_offers_only_the_two_known_versions():
    parser = _build_parser()
    assert parser.parse_args(BASE_ARGS).idea_graph_version == "v1"
    assert (
        parser.parse_args([*BASE_ARGS, "--idea-graph-version", "v2"]).idea_graph_version
        == "v2"
    )
    with pytest.raises(SystemExit):
        parser.parse_args([*BASE_ARGS, "--idea-graph-version", "v3"])


def test_cli_hop_passes_it_into_harness_config():
    source = inspect.getsource(
        __import__("famou_scientist.loop.harness.cli", fromlist=["_build_parser"])
    )
    assert "idea_graph_version=args.idea_graph_version" in source


def _harness_config(**changes):
    return HarnessConfig(
        task_id="t",
        run_dir="/tmp/x",
        problem_dir="/tmp/x/problem",
        workspace_dir="/tmp/x/workspace",
        agent_runtime="claude",
        **changes,
    )


def test_harness_hop_defaults_to_v1_and_rejects_garbage():
    """宿主层抛错：拼错的版本号安静跑成对照臂会毁掉整批配对实验。

    校验落在 `HarnessConfig.validate()`（不是 `__post_init__`——这个 dataclass 的
    既有风格就是显式 validate）。那个方法还要求 problem_dir 真实存在等一堆前置，
    所以这里断言校验确实写在它里面，再单独验默认值。
    """

    assert _harness_config().idea_graph_version == "v1"
    assert _harness_config(idea_graph_version="v2").idea_graph_version == "v2"
    source = inspect.getsource(HarnessConfig.validate)
    assert "self.idea_graph_version not in GRAPH_VERSIONS" in source
    assert "raise ValueError" in source.split(
        "self.idea_graph_version not in GRAPH_VERSIONS", 1
    )[1]


def test_harness_hop_hands_it_to_the_orchestrator():
    source = inspect.getsource(
        __import__(
            "famou_scientist.loop.harness.runtime", fromlist=["BenchmarkHarness"]
        )
    )
    assert "idea_graph_version=self.config.idea_graph_version" in source




# --- ensemble 算子（v9） ---------------------------------------------------


def test_ensemble_has_the_same_parent_arity_as_cross():
    """两者在图上是同一种边；父约束必须逐字相同，差别只在节点自己做了什么。"""

    known = {ROOT_ID, "A", "B"}
    for operator in ("cross", "ensemble"):
        assert validate_operator(
            {"operator": operator, "parents": ["A", "B"]}, known
        ).ok
        # 1 个父、带 ROOT、0 个父，三种都不行
        for parents in (["A"], ["A", ROOT_ID], []):
            check = validate_operator(
                {"operator": operator, "parents": parents}, known
            )
            assert not check.ok and operator in check.reason


def test_ensemble_lands_a_real_multi_parent_node(tmp_path):
    """集成节点要真的挂在多个父上——只有边在，后面才查得到该加载谁的权重。"""

    store = _v2(tmp_path)
    _seed(store)
    node = store.submit(
        {"id": "E", "title": "两路 stacking", "operator": "ensemble",
         "parents": ["A", "B"]}
    )
    assert node["operator"] == "ensemble" and node["parents"] == ["A", "B"]


def test_v7_fallback_never_invents_ensemble(tmp_path):
    """v7 提示词里没有集成这个概念，回退不能替它造一个。

    回退只在 `operator` 完全缺席时按父数补，补的是 v7 当时就有的语义。
    多父回退成 `cross`（重新实现）而不是 `ensemble`（加载权重）——后者要求
    父真的存了 ckpt，凭空断言这一点会让实现方去加载一个不存在的目录。
    """

    from famou_scientist.loop.storage.evolution_graph import (
        apply_legacy_prompt_shape,
    )

    payload = {"id": "E", "parent_idea_id": ["A", "B"]}
    apply_legacy_prompt_shape(payload)
    assert payload["operator"] == "cross"


# --- 父产物路径注入 --------------------------------------------------------


def test_parent_artifacts_only_lists_directories_that_exist(tmp_path):
    """路径是宿主实测，不是 agent 自报——不存在的目录一个都不许出现在请求里。

    给出一个不存在的路径，实现方会照着它去加载，然后在评测里挂掉；那时候
    盘上找不到任何证据说明是宿主给错了路。
    """

    orchestrator = _orchestrator(tmp_path, "v2")
    store = orchestrator.idea_graph
    store.submit({"id": "A", "title": "甲", "operator": "innovate",
                  "parents": [ROOT_ID]})
    store.submit({"id": "B", "title": "乙", "operator": "innovate",
                  "parents": [ROOT_ID]})

    real = tmp_path / "real_output" / "submission"
    real.mkdir(parents=True)
    weights = real.parent / "weights"
    weights.mkdir()
    (weights / "model.pt").write_text("x", encoding="utf-8")

    def attach(node_id: str, output: Path, code: Path) -> None:
        record = store.read(node_id)
        record["attempts"] = [{
            "attempt_id": "0001", "status": "best", "score": 0.5,
            "paths": {"output": str(output), "code": str(code)},
        }]
        record["best_score"] = 0.5
        (store.root / f"{node_id}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )

    attach("A", real, tmp_path / "nowhere_code")
    attach("B", tmp_path / "nowhere_output" / "submission", tmp_path / "gone")

    entries = {
        item["node_id"]: item
        for item in orchestrator._parent_artifacts(["A", "B", ROOT_ID])
    }
    # A 的 output 和 weights 都在盘上，code 不在
    assert entries["A"]["output"] == str(real)
    assert entries["A"]["weights"] == str(weights)
    assert "code" not in entries["A"]
    # B 一个目录都不存在，只剩身份信息，不带任何路径
    assert "output" not in entries["B"] and "weights" not in entries["B"]
    # ROOT 不是方案，不该出现
    assert ROOT_ID not in entries


def test_empty_weights_dir_is_not_advertised(tmp_path):
    """空的 weights/ 等于没存。报给实现方会让它白跑一趟加载逻辑。"""

    orchestrator = _orchestrator(tmp_path, "v2")
    store = orchestrator.idea_graph
    store.submit({"id": "A", "title": "甲", "operator": "innovate",
                  "parents": [ROOT_ID]})
    output = tmp_path / "out" / "submission"
    output.mkdir(parents=True)
    (output.parent / "weights").mkdir()          # 建了目录但什么都没存

    record = store.read("A")
    record["attempts"] = [{"attempt_id": "0001", "status": "best", "score": 0.1,
                           "paths": {"output": str(output)}}]
    (store.root / "A.json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    entry = orchestrator._parent_artifacts(["A"])[0]
    assert "weights" not in entry


# --- 提示词 v9 -------------------------------------------------------------


def test_v9_defines_four_operators_and_triggers_for_each():
    """exploit 100%、cross 0% 的根因是触发条件只写给了 exploit。

    v8 给 exploit 写了"这是默认选择"外加两条定位指引，给 cross 只有一句定义。
    v9 必须让每个多父算子都有一条"什么时候该用它"的可执行判据。
    """

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    for operator in ("innovate", "exploit", "cross", "ensemble"):
        assert f"`{operator}`" in text
    # 两个多父算子各自有触发条件
    assert text.count("触发条件") >= 2
    # exploit 的默认地位要有退出条件，否则它还是吃掉全部提案
    assert "退出条件" in text


def test_v9_separates_ensemble_from_cross_by_cost():
    """两者父约束相同，Agent 只能靠"要不要重训"来分——这一点必须写明。"""

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    assert "机制" in text and "重训" in text
    # 集成不能被读成"只有加权投票"
    for method in ("stacking", "boosting", "model soup"):
        assert method in text


def test_v9_tells_the_agent_where_weights_live():
    """索引故意不标谁有权重，那提示词就必须说清楚去哪找、为什么要自己找。"""

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    assert "weights/" in text
    assert "parent_artifacts" in text
    # 跨方案可读是存权重的全部意义，不能只写给父子
    assert "不限于自己的父节点" in text


def test_v9_describes_the_two_zones_the_renderer_actually_writes():
    """提示词描述的索引必须和渲染器真的写出来的对得上。

    对不上的话 agent 会去找一个不存在的段落，然后自己脑补一个——v8 描述的四段
    索引现在就是这个状态（见 `test_v8_still_describes_the_four_section_index_...`）。
    """

    from famou_scientist.loop.storage.evolution_graph import EvolutionGraphStore

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    rendered = inspect.getsource(EvolutionGraphStore)
    for zone in ("## 路线", "## 方案"):
        assert zone in text, zone
        assert zone in rendered, zone
    # 四段索引已经不存在，提示词里不许再提
    for gone in ("现在爬到哪了", "最该接着挖的", "试过但还没有分的", "全部方案"):
        assert gone not in text, gone
    # 结局词表两边一致
    for word in ("未实现", "running", "scored"):
        assert word in text and word in rendered, word


def test_v9_has_exactly_one_top_level_heading():
    """一个文件只能有一个 H1。

    v2 起这批提示词都是两份文档拼起来的，第二个「# Famou Loop 构思智能体任务」
    出现在正文中段——模型读到那里会看见「任务开始」第二次出现，等于在一次推理里
    被重新起了一次头。v9 起并成一个；v8 及更早是冻结的历史版本，不动。
    """

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    heads = [line for line in text.splitlines() if line.startswith("# ")]
    assert heads == ["# Famou Loop 构思智能体任务"], heads


def test_v9_puts_the_task_and_the_request_last():
    """真正的任务和请求数据放在最后，规则放在前面。

    v2 起这批提示词把 `${instruction}` / `${request_json}` 夹在中段，后面还压着
    270 多行通用守则——等于先给任务，再给一大段规则，模型读到任务时还不知道按什么
    规则做。v9 起把注入点挪到末尾。

    两个占位符必须原样保留：名字改了 `render_prompt` 不会报错，只会把一个没替换
    的 `${...}` 字面量发给模型。
    """

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    for placeholder in ("${instruction}", "${request_json}"):
        assert text.count(placeholder) == 1, placeholder
    rules_end = text.index("## 三、一句话版")
    assert text.index("${instruction}") > rules_end
    assert text.index("${request_json}") > text.index("${instruction}")


def test_v9_teaches_the_real_status_vocabulary():
    """索引里印的是实测状态本身，提示词必须教全那份词表。

    只教 `failed` 的话，agent 读到 `not_executed×1` 会当成没见过的东西——而这两者
    处置方向**相反**：超时是方案太重要减配，失败是代码有 bug 要修。把超时读成失败
    就会去修一份根本没错的代码。
    """

    from famou_scientist.loop.domain.status import LoopStatus

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    # 未出分时会被印进索引的那几个状态，一个都不能漏
    for status in ("failed", "engineering_failed", "not_executed",
                   "implementing", "implemented"):
        assert getattr(LoopStatus.ExpBank, status.upper()).value == status
        assert f"`{status}×N`" in text, status
    assert "超时被掐" in text and "代码有 bug" in text


def test_v9_tells_the_agent_the_number_is_the_address():
    """编号是 agent 唯一要抄的东西。不说清楚它就会去抄长 id，或者干脆编一个。"""

    text = (PROMPTS / "cli_agents/idea_agent_v9.md").read_text(encoding="utf-8")
    assert "四位数字就是方案的地址" in text
    assert "`parents` 填长 id 一样认" in text
    # 没出分不能被读成 0 分
    assert "**不是 0**" in text


def test_v5_implement_prompt_pins_the_weight_location():
    """存哪由宿主定。位置漂了，后面所有方案都加载不到。"""

    text = (PROMPTS / "cli_agents/implement_agent_v5.md").read_text(
        encoding="utf-8"
    )
    assert "$OUTPUT_DIR/weights/" in text
    # 跑挂的也要存，否则最有诊断价值的那一半 ckpt 全丢了
    assert "跑挂的那次也要存" in text
    # 产物优先级不能被集成逻辑翻转
    assert "不能因此交不出产物" in text


def test_v8_prompts_are_untouched_by_v9():
    """v8 有 10 个 run 在跑，原地改它等于把已派发批次的变量改掉。"""

    v8 = (PROMPTS / "cli_agents/idea_agent_v8.md").read_text(encoding="utf-8")
    assert "ensemble" not in v8 and "parent_artifacts" not in v8


def test_new_prompt_versions_are_selectable():
    """提示词放进目录但没接到版本开关上，等于没上线。"""

    from famou_scientist.loop.execution import cli_agent_wrapper

    source = inspect.getsource(cli_agent_wrapper)
    assert "cli_agents/idea_agent_v9.md" in source
    assert "cli_agents/implement_agent_v5.md" in source
