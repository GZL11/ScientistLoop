"""方案演化图 v2：把方案图从「只有拓扑的旁路索引」升级成带海拔的 DAG。

设计文档：`docs/design/EVOLUTION_GRAPH_V2_CN.md`

与 v1（`storage/idea_graph.py`）的关系
------------------------------------
v1 是上一批 A/B 的对照臂配置，**必须能一键回去**，所以这里不改它、不包装它的
逻辑，只在 `make_idea_graph()` 里按版本二选一。v2 把 v1 的八个公开方法签名逐字
实现，于是 orchestrator 里那 20 个 `idea_graph.*` 调用点一行都不用改。

v2 相对 v1 补上的三处结构性缺口（上一批的 null 结果指向的正是这三处）：

1. **图上有分数了**：`attempts[]` 每条带 `score`，节点带 `best_score`，索引里直接
   出现「最好分」列。上一批 `IDEAS.md` 六列一个分数都没有，agent 沿着图挖了九层
   全程没有任何信号告诉它方向在变好还是变坏。
2. **方案有唯一身份**：`node_id` 是方案的身份，同一方案的多次实现 upsert 进同一个
   `attempts[]`。上一批 16 个图节点对应 7 个真实方案。
3. **多父在结构上成立**：`parents` 是数组，`cross` 节点可以有 ≥2 个父。上一批
   `parent_idea_id` 是单字符串，图永远塌成树。

纪律
----
- 写入时拒绝非法边（父不存在 / 指向自己 / 成环），**不事后剪枝**——事后剪等于
  图里本来就存着脏数据。
- 非法就抛，**不替 agent 改**。宿主把算子改成"最近的合法形态"是替它做了一个它
  没做的决定：它下次照错，图上还会多出一条它没打算建立的边。合法性由 orchestrator
  在提交时保证（带原因退回重提，几次仍非法整条丢弃），所以到这里的非法是调用方
  的 bug。调用点已经包了 try/except，抛异常不会让 4 小时的作业死掉。
- 算子校验只有一份（`validate_operator`），orchestrator 与 store 共用。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Iterable, Iterator, Mapping, MutableMapping
from unicodedata import east_asian_width

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None

from ..domain.status import LoopStatus
from ..utils import (
    atomic_write_json,
    atomic_write_text,
    new_id,
    now_ms,
    read_json,
    safe_name,
)
from .idea_graph import IdeaGraphStore

SCHEMA_VERSION = "evolution-graph-v2"

#: 虚拟根写成**真实节点文件**，不是一个特判的保留字。这样「每个节点都至少有一条
#: 入边」字面成立，「一个分支代表一个方向」= 「root 的每条出边是一个方向」，
#: `root_branch` 可计算，谱系代码也不必为创新节点开特例分支。
ROOT_ID = "ROOT"

#: 算子库。可扩展。算子挂在**节点**上，不挂在边上——有了多父之后，
#: 一个交叉节点的身份就是「它是怎么被造出来的」，入边只负责列出父节点。
OPERATOR_INNOVATE = "innovate"
OPERATOR_EXPLOIT = "exploit"
OPERATOR_CROSS = "cross"
#: `ensemble` 与 `cross` 在图上是同一种边（多父），分开是因为**代价差一个数量级**：
#: cross 拿走父的*想法*，要从头重训；ensemble 直接吃父的*产物*（ckpt / 预测），
#: 多数情况只需训一个很小的结合器。「这次要花多少时间」对 Agent 是决定性的，
#: 混在一个词里它判断不了。
#:
#: 不叫 `fuse`：Search Policy 早有一个同名动作（implement 阶段的
#: refine/switch/fuse，见 `search/policy.py:94`），那个 fuse 合并的是 Idea 文本，
#: 与这里复用已训产物不是一回事，重名会让两边的日志和提示词互相污染。
OPERATOR_ENSEMBLE = "ensemble"
OPERATORS: tuple[str, ...] = (
    OPERATOR_INNOVATE,
    OPERATOR_EXPLOIT,
    OPERATOR_CROSS,
    OPERATOR_ENSEMBLE,
)

#: 父节点数 ≥2 的算子。两者的父约束逐字相同，差别只在节点自己做了什么。
MULTI_PARENT_OPERATORS: frozenset[str] = frozenset({OPERATOR_CROSS, OPERATOR_ENSEMBLE})

#: 每个算子的中文名与父节点数量约束，用于校验信息和提示词回灌。
OPERATOR_SPEC: dict[str, dict[str, Any]] = {
    OPERATOR_INNOVATE: {
        "label": "创新",
        "parents": "恰好 [\"ROOT\"]",
        "summary": "提出全新算法，开一个新方向，不是局部微调",
    },
    OPERATOR_EXPLOIT: {
        "label": "利用",
        "parents": "恰好 1 个已存在节点",
        "summary": "基于某节点（通常是高分节点）做调整",
    },
    OPERATOR_CROSS: {
        "label": "交叉",
        "parents": "≥2 个已存在节点",
        "summary": "取多个节点各自的机制，重新实现成一个新方案",
    },
    OPERATOR_ENSEMBLE: {
        "label": "集成",
        "parents": "≥2 个已存在节点",
        "summary": "直接复用多个节点已训好的产物（ckpt / 预测）做集成",
    },
}

#: 不可用于融合的 attempt 状态。与「绝不 host 侧改分」同一条纪律：宿主只提供
#: 引用和门槛，不生产结果。
UNFUSABLE_STATUSES = frozenset(
    {
        str(LoopStatus.ExpBank.FAILED),
        str(LoopStatus.ExpBank.ENGINEERING_FAILED),
    }
)


def _oneline(value: Any) -> str:
    """压成单行。换行会把「一个节点一行」的格式撑断。

    以前这里还会转义 `|`，那是三张 markdown 表格时代的遗留；现在四段都是列表
    而不是表格（表格逼着每行填满所有列，自足性就得靠宽度换），`|` 不再有结构
    含义，转义只会在正文里留下一个多余的反斜杠。
    """

    return " ".join(str("" if value is None else value).split())


def _finite(value: Any) -> float | None:
    """只接受有限数值分；bool、NaN、inf、字符串一律当作没有分数。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


#: 索引里那一句话描述的字符上限。
BRIEF_LIMIT = 100


def _brief(value: Any, limit: int = BRIEF_LIMIT) -> str:
    """把 `mechanism` 压成索引里的一行。

    取 `mechanism` 而不是新开一个 `summary` 字段，是因为 `_valid_idea()`
    （`agents/workers.py:494`）只强制 `title` + `mechanism` 两个字段——它保证
    非空，不需要兜底分支，也**不必让 agent 多填一个字段**。

    超长就截断并**显式**以 `…` 收尾：截断是宿主做的，必须看得出来。一句被切掉
    一半的 mechanism 如果读起来像完整句子，agent 会把半句话当成方案全貌。这条
    上限同时封死「agent 写一段 5000 字的 mechanism 把索引撑爆」。
    """

    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _width(text: str) -> int:
    """按终端显示宽度算，CJK 算两格。

    索引是**给人和 Agent 一起读的等宽文本**，用 `len()` 对齐会让中文标题整列
    错开——错开的列没法一眼扫，等于没有列。
    """

    return sum(2 if east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    """右侧补空格到指定显示宽度。超宽不截——截的是引用，不是主语。"""

    return text + " " * max(0, width - _width(text))


#: 路线枚举的硬上限。多父节点会让「根→叶」路径数按组合增长，实测一个 run
#: 路线数中位 7、最大 11，离这个数很远；它是防呆，不是排名截尾——撞上时索引里
#: 会明写，不静默少列几条。
ROUTE_LIMIT = 200

#: 方案区标题列的对齐宽度上限。超宽的标题不截（那一行的主语就是它），只是不再
#: 拿它去撑别人的缩进——一个 500 字的标题会把整列推到屏幕外。
TITLE_COLUMN_LIMIT = 40


def _route_letter(pos: int) -> str:
    """路线的行内编号：A…Z、AA…。**不持久化**，只供同一次阅读里互相指代。"""

    letters = ""
    pos += 1
    while pos:
        pos, rem = divmod(pos - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


#: 方案编号的位宽。四位够用：实测一个 run 的节点中位数 9、最大 14，
#: 上到四位是给"一个 run 跑很久"留的余量，不是当前需要。
SEQ_WIDTH = 4


def format_seq(seq: Any) -> str:
    """把方案序号渲染成 `NNNN`。拿不到序号时返回空串，**不编一个**。

    编号是 Agent 填 `parents` 时唯一要抄的东西，渲染一个不存在的号会让它
    提交一个挂不上的父节点，而错误要到提交校验时才暴露。
    """

    try:
        value = int(seq)
    except (TypeError, ValueError):
        return ""
    return str(value).zfill(SEQ_WIDTH) if value > 0 else ""


def _score_text(value: float | None) -> str:
    """节点的最好分。没有分就说没有分，不要写成 0。"""

    return "未出分" if value is None else f"{value:+.4f}"


def _str_list(value: Any) -> list[str]:
    """把任意入参归一成去重保序的字符串列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        items: Iterable[Any] = [value]
    elif isinstance(value, Mapping):
        items = list(value.keys())
    elif isinstance(value, Iterable):
        items = value
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def read_parents(idea: Mapping[str, Any]) -> list[str]:
    """从 idea 载荷里取父节点列表，并兼容 v7 提示词的单父字段。

    v8 产出 `parents` 数组；但 v2 存储也可能被 v7 提示词喂到（版本阶梯漂移过
    一次，见 `PROMPT_VERSIONS_CN.md:36-39`）。这时把 `parent_idea_id` 当成一个
    父节点，好过把整张图拍平成创新节点。

    **回退命中不是正常路径**，所以它不是静默的：`submit()` 会用
    `used_legacy_parent_field()` 检出并把 `LEGACY_PARENT_FIELD_NOTE` 记进节点的
    `operator_notes`。v8 下出现即说明某处提示词或调用点没跟上。
    """

    parents = _str_list(idea.get("parents"))
    if parents:
        return parents
    return _str_list(idea.get("parent_idea_id"))


#: 回退命中时记进节点 `operator_notes` 的固定文案。落在节点上而不是只打日志，
#: 是因为日志跑完就散在容器 stdout 里，而这条必须能被审计脚本按节点数出来。
LEGACY_PARENT_FIELD_NOTE = (
    "parents 取自 v7 的 parent_idea_id 回退路径；v8 下命中即说明"
    "提示词或调用点没跟上，不是正常路径"
)


def used_legacy_parent_field(idea: Mapping[str, Any]) -> bool:
    """`read_parents` 这一次是不是走了 v7 的 `parent_idea_id` 回退。"""

    return not _str_list(idea.get("parents")) and bool(
        _str_list(idea.get("parent_idea_id"))
    )


def apply_legacy_prompt_shape(payload: MutableMapping[str, Any]) -> None:
    """v7 载荷完全没有 `operator` 字段时，按父的个数补一个。

    这**不是**替 agent 改算子。v7 提示词里根本没有算子这个概念，agent 没做过
    "填 exploit"这个决定，也就无从说它填错；补不上的话，v7 一旦喂进 v2 存储，
    每条提案都会因为"operator 缺失"被丢掉，整个 run 颗粒无收。

    只在 `operator` 完全缺席、且父来自 v7 单父字段时生效。agent 自己写了算子的，
    哪怕写错也原样送去校验——那才是它做过的决定。命中会记进 `operator_notes`。
    """

    if str(payload.get("operator") or "").strip():
        return
    if not used_legacy_parent_field(payload):
        return
    payload["operator"] = (
        OPERATOR_CROSS if len(read_parents(payload)) > 1 else OPERATOR_EXPLOIT
    )


@dataclass(frozen=True)
class OperatorCheck:
    """一次算子校验的结论。`violations` 为空即合法。"""

    operator: str | None
    parents: tuple[str, ...]
    violations: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        """是否完全合法。"""

        return not self.violations

    @property
    def reason(self) -> str:
        """拼成一句可直接塞进 `benchmark_runtime.operator_violation` 的说明。"""

        return "；".join(self.violations)


def validate_operator(
    idea: Mapping[str, Any],
    known_ids: Collection[str],
    *,
    node_id: str | None = None,
    cycle_probe: Any = None,
) -> OperatorCheck:
    """校验 idea 自报的 `operator` + `parents`，返回全部违规原因。

    这是**唯一一份**校验实现，orchestrator 的两段式重提和 store 的写入都走它。
    `_idea_graph_active()` 的 docstring 已经把教训写在那里了：三个关口靠手抄副本
    保持同步，迟早漂移。

    参数
    ----
    known_ids
        当前图上已存在的节点 id（含 `ROOT`）。
    node_id
        待写入节点自己的 id，用于「不得指向自己」。
    cycle_probe
        可选的 `callable(node_id, parents) -> list[str]`，返回会成环的父节点。
        由 store 提供（`EvolutionGraphStore.would_cycle`）；纯校验场景可不给。
    """

    operator_raw = idea.get("operator")
    operator = str(operator_raw).strip() if operator_raw is not None else ""
    parents = read_parents(idea)
    known = {str(item) for item in known_ids}
    violations: list[str] = []

    if not operator:
        violations.append(
            f"operator 缺失，必填，合法值：{'/'.join(OPERATORS)}"
        )
    elif operator not in OPERATORS:
        violations.append(
            f"operator 非法: {operator!r}，合法值：{'/'.join(OPERATORS)}"
        )

    if node_id and node_id in parents:
        violations.append(f"parents 指向自己: {node_id}")

    missing = [
        item for item in parents if item != node_id and item not in known
    ]
    if missing:
        violations.append("父节点不存在: " + ", ".join(missing))

    if operator == OPERATOR_INNOVATE and parents != [ROOT_ID]:
        violations.append(
            f"{OPERATOR_INNOVATE} 的 parents 必须恰好 [\"{ROOT_ID}\"]，"
            f"实际 {parents or '[]'}"
        )
    elif operator == OPERATOR_EXPLOIT:
        real = [item for item in parents if item != ROOT_ID]
        if len(parents) != 1 or len(real) != 1:
            violations.append(
                f"{OPERATOR_EXPLOIT} 的 parents 必须恰好 1 个已存在节点"
                f"（不能是 {ROOT_ID}），实际 {parents or '[]'}"
            )
    elif operator in MULTI_PARENT_OPERATORS:
        real = [item for item in parents if item != ROOT_ID]
        if len(real) < 2 or len(real) != len(parents):
            violations.append(
                f"{operator} 的 parents 必须 ≥2 个已存在节点"
                f"（不能含 {ROOT_ID}），实际 {parents or '[]'}"
            )

    if cycle_probe is not None and parents:
        try:
            looping = list(cycle_probe(node_id, parents) or [])
        except Exception:  # pragma: no cover - 校验本身不许杀流程
            looping = []
        if looping:
            violations.append("parents 会成环: " + ", ".join(str(x) for x in looping))

    return OperatorCheck(
        operator=operator or None,
        parents=tuple(parents),
        violations=tuple(violations),
    )


class EvolutionGraphStore:
    """在 ExpBank 内维护方案演化 DAG，与 v1 物理隔离。

    磁盘布局（`IDEAS.md` / `ideas/` 是 v1 的，一个字节都不碰）::

        workspace/expbank/
        ├── IDEAS.md, ideas/*.json     ← v1
        ├── GRAPH.md                   ← v2 索引，agent 真正读到的那张表
        └── graph/
            ├── ROOT.json
            ├── <node_id>.json
            └── .graph.lock
    """

    def __init__(self, workspace: str | Path):
        """初始化图目录、虚拟根、索引和跨进程文件锁。"""

        self.workspace = Path(workspace).expanduser().resolve()
        self.expbank_root = self.workspace / "expbank"
        self.root = self.expbank_root / "graph"
        self.index_path = self.expbank_root / "GRAPH.md"
        self.lock_path = self.root / ".graph.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_root()
        if not self.index_path.exists():
            self._write_index()

    # ---------------------------------------------------------------- 基础设施

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """串行化节点写入与索引重建。沿用 v1 的 `fcntl.flock` 范式。"""

        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, idea_id: str) -> Path:
        """返回经过路径校验的节点文件。"""

        value = str(idea_id or "")
        if not value or value != safe_name(value):
            raise ValueError(f"非法 node_id: {idea_id!r}")
        return self.root / f"{value}.json"

    def _ensure_root(self) -> None:
        """把虚拟根写成真实节点文件。"""

        path = self.root / f"{ROOT_ID}.json"
        if path.exists():
            return
        created_at = now_ms()
        atomic_write_json(
            path,
            {
                "schema_version": SCHEMA_VERSION,
                "node_id": ROOT_ID,
                "operator": None,
                "parents": [],
                "root_branch": None,
                "idea": {"id": ROOT_ID, "title": "研究目标（虚拟根）"},
                "attempts": [],
                "attempt_ids": [],
                "best_score": None,
                "status": LoopStatus.Idea.ACCEPTED,
                "actor_id": None,
                "goal_contract_version": None,
                "artifact_refs": [],
                "reviews": [],
                "admission": {"mode": "virtual_root", "decision": "always_present"},
                "created_at": created_at,
                "updated_at": created_at,
            },
        )

    def _records(self) -> list[dict[str, Any]]:
        """按创建时间读取全部节点（含 ROOT）。"""

        records = [
            value
            for path in sorted(self.root.glob("*.json"))
            if isinstance((value := read_json(path)), dict)
        ]
        return sorted(
            records,
            key=lambda item: (
                int(item.get("created_at") or 0),
                str(item.get("node_id") or ""),
            ),
        )

    def _next_seq(self) -> int:
        """下一个方案序号。只在写锁内调用。

        取「已用最大值 + 1」而不是「节点个数 + 1」：后者在任何一次读取失败时
        都会撞上已经发出去的号，而号是 Agent 拿来指父节点的，撞号等于改边。
        """

        used = [
            int(value)
            for record in self._records()
            if isinstance((value := record.get("seq")), int) and value > 0
        ]
        return (max(used) + 1) if used else 1

    def seq_aliases(self) -> dict[str, str]:
        """`NNNN` → `node_id` 的映射，供解析 Agent 填的父节点编号。"""

        aliases: dict[str, str] = {}
        for record in self._records():
            node_id = str(record.get("node_id") or "")
            label = format_seq(record.get("seq"))
            if node_id and label:
                aliases[label] = node_id
        return aliases

    def resolve_parents_in_place(self, payload: MutableMapping[str, Any]) -> None:
        """把载荷里的父节点编号就地解析成 node_id，再交给校验。

        不解析的话，Agent 照着索引抄下来的合法 `NNNN` 会被判成「父节点不存在」。

        **写回原来那个字段**：v7 形状用的是 `parent_idea_id`，把它挪进 `parents`
        会让 `used_legacy_parent_field()` 失灵——回退命中就不再记进
        `operator_notes`，而那条记录正是「某处提示词或调用点没跟上」的唯一凭据。
        """

        field = "parents" if _str_list(payload.get("parents")) else "parent_idea_id"
        current = read_parents(payload)
        if current:
            payload[field] = self.resolve_parents(current)

    def resolve_parents(self, parents: Iterable[Any]) -> list[str]:
        """把 Agent 填的父节点统一解析成 `node_id`。

        索引上显示的是 `NNNN`，但磁盘主键是 `node_id`，两者都是真地址，所以
        两种写法都收。解析不了的原样返回——让它走正常的「父节点不存在」校验，
        在那里 Agent 会收到一份合法编号清单，比在这里悄悄丢掉一个父强。
        """

        aliases = self.seq_aliases()
        out: list[str] = []
        for raw in parents or []:
            text = str(raw or "").strip()
            if not text:
                continue
            resolved = aliases.get(text.zfill(SEQ_WIDTH), text)
            if resolved not in out:
                out.append(resolved)
        return out

    def _known_ids(self) -> set[str]:
        """当前图上已存在的节点 id（含 ROOT）。"""

        ids = {
            path.stem
            for path in self.root.glob("*.json")
            if path.stem and path.stem != ".graph"
        }
        ids.add(ROOT_ID)
        return ids

    def known_ids(self) -> set[str]:
        """`_known_ids` 的公开别名，供 orchestrator 的两段式重提调用。

        校验实现只有一份（`validate_operator`），但它需要「图上现在有谁」这个
        输入；没有公开入口的话调用点就会去摸私有方法，或者自己重建一份 id 集合
        ——那就是 `_idea_graph_active()` docstring 里警告过的手抄副本。
        """

        return self._known_ids()

    def _parents_of(self, node_id: str) -> list[str]:
        """直接读磁盘拿某节点的父列表；节点不存在时返回空。"""

        record = read_json(self.root / f"{safe_name(str(node_id))}.json")
        if not isinstance(record, dict):
            return []
        return _str_list(record.get("parents"))

    def would_cycle(self, node_id: str | None, parents: Iterable[str]) -> list[str]:
        """返回会导致成环的父节点：即那些能沿着父边回到 `node_id` 的父。

        环路**在写入时拒绝**，不在事后剪枝——v1 的 `lineage.py:147-161` 是事后
        剪掉闭环那条边，等于图里本来就存着脏数据。
        """

        target = str(node_id or "")
        if not target:
            return []
        looping: list[str] = []
        for parent in _str_list(parents):
            if parent == target:
                looping.append(parent)
                continue
            seen: set[str] = set()
            stack = [parent]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                if current == target:
                    looping.append(parent)
                    break
                stack.extend(self._parents_of(current))
        return looping

    def _root_branch(self, parents: Iterable[str], node_id: str) -> str | None:
        """所属方向 = 回溯到的第一层创新节点。

        `cross` 跨方向时把涉及的方向都列出来（排序后用 `+` 连接），因为一个交叉
        节点确实同时属于多个方向，硬塞一个会误导「这条方向走通了」的判断。
        """

        parent_list = _str_list(parents)
        if parent_list == [ROOT_ID] or not parent_list:
            return node_id if parent_list == [ROOT_ID] else None

        branches: set[str] = set()
        seen: set[str] = set()
        stack = list(parent_list)
        while stack:
            current = stack.pop()
            if current in seen or current == ROOT_ID:
                continue
            seen.add(current)
            ups = self._parents_of(current)
            if ups == [ROOT_ID] or not ups:
                branches.add(current)
            else:
                stack.extend(ups)
        if not branches:
            return None
        return "+".join(sorted(branches))

    # ---------------------------------------------------------------- 索引渲染

    def _summary(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """抽出索引与外部读取共用的节点摘要。

        `mechanism` 在这里就被截成一句话——索引放**一句话**，全文留在
        `graph/<节点>.json`。渐进式披露：agent 先按这一句判断值不值得细看，
        要细节自己 Read。
        """

        idea = record.get("idea") if isinstance(record.get("idea"), Mapping) else {}
        attempts = record.get("attempts") if isinstance(record.get("attempts"), list) else []
        statuses = [
            text
            for item in attempts
            if isinstance(item, Mapping) and (text := str(item.get("status") or ""))
        ]
        return {
            "node_id": str(record.get("node_id") or ""),
            "seq": record.get("seq"),
            "title": _oneline(idea.get("title")) or "未命名方案",
            "brief": _brief(idea.get("mechanism")),
            "operator": record.get("operator"),
            "parents": _str_list(record.get("parents")),
            "root_branch": record.get("root_branch"),
            "attempts": len(attempts),
            "statuses": statuses,
            # `link_attempt` 只建空壳（那时还没有结果），`record_attempt_result`
            # 才写状态。所以「有 attempt 但一个状态都没有」= 还在跑，不是跑完
            # 没出分。这两者必须分开，和榜单口径里 `SR` / `CR` 必须分开同理。
            "settled": bool(statuses),
            "best_score": _finite(record.get("best_score")),
            "status": str(record.get("status") or "unknown"),
        }

    @staticmethod
    def _label(item: Mapping[str, Any]) -> str:
        """一个方案在索引上的地址。

        提交时分到的 `seq` 渲染成 `NNNN`；`seq` 之前写下的老图没有这个字段，
        退回长 id。**不在渲染期补号**——号是 Agent 拿来指父节点的，渲染期现算
        的号会随排序漂移，上一回合记住的 0007 下一回合指向别人，而这种错不报
        错，只会悄悄建错边。
        """

        return format_seq(item.get("seq")) or str(item.get("node_id") or "")

    def _ref(self, node_id: str, by_id: Mapping[str, Mapping[str, Any]]) -> str:
        """引用一个父节点时写它的编号。读不出来就说读不出来。"""

        if node_id == ROOT_ID:
            return ROOT_ID
        item = by_id.get(node_id)
        return self._label(item) if item is not None else f"{node_id}（读不出）"

    @staticmethod
    def _outcome(item: Mapping[str, Any]) -> str:
        """这个方案最后怎么了。

        「没跑过」和「跑了没出分」必须是两个词——混了就等于把「还没试」说成
        「试了不行」，而「还没试」恰恰是最该接着挖的。「还在跑」也单独一个词：
        `link_attempt` 只建空壳、`record_attempt_result` 才写状态，所以「有
        attempt 但一个状态都没有」是在跑，不是失败。
        """

        if item["attempts"] == 0:
            return "未实现"
        if item["best_score"] is not None:
            return "scored"
        if not item["settled"]:
            return "running"
        tally = Counter(item["statuses"])
        return "、".join(f"{name}×{count}" for name, count in tally.most_common())

    @staticmethod
    def _rank_key(score: float | None) -> tuple[int, float]:
        """按分降序排，没有分的一律沉底（而不是当成 0 分插到中间）。"""

        return (0, -score) if score is not None else (1, 0.0)

    def _routes(
        self, nodes: list[dict[str, Any]], by_id: Mapping[str, Mapping[str, Any]]
    ) -> tuple[list[list[dict[str, Any]]], bool]:
        """枚举全部「根 → 叶」世系链。

        图结构只由这一区承载，方案区是扁平的——Agent 从头到尾读线性列表，不做
        图遍历。多父节点同时属于多条链，在每条里各出现一次，这正是不把图压成树
        的地方。

        返回的 bool 说明有没有撞上 `ROUTE_LIMIT`。实测一个 run 的路线数中位 7、
        最大 11，离上限很远；上限是防组合爆炸把渲染卡死，撞上时**显式写出来**，
        不静默截断。
        """

        children: dict[str, list[str]] = {}
        roots: list[str] = []
        for item in nodes:
            ups = [p for p in item["parents"] if p != ROOT_ID and p in by_id]
            if not ups:
                roots.append(item["node_id"])
            for parent in ups:
                children.setdefault(parent, []).append(item["node_id"])

        routes: list[list[dict[str, Any]]] = []
        truncated = False

        def walk(path: list[str]) -> None:
            nonlocal truncated
            if len(routes) >= ROUTE_LIMIT:
                truncated = True
                return
            kids = [kid for kid in children.get(path[-1], ()) if kid not in path]
            if not kids:
                routes.append([by_id[node_id] for node_id in path])
                return
            for kid in kids:
                walk(path + [kid])

        for root in roots:
            walk([root])
        return routes, truncated

    @staticmethod
    def _route_best(route: Iterable[Mapping[str, Any]]) -> float | None:
        scores = [
            item["best_score"] for item in route if item["best_score"] is not None
        ]
        return max(scores) if scores else None

    def _route_note(self, route: list[dict[str, Any]]) -> str:
        """这条链接着走是什么。**宿主算的，不是 Agent 写的。**

        说的全是末端的状态：一条链值不值得接着挖，取决于它的末端是「提了还没做」
        「做了跑挂了」还是「上一跳还在涨」，这三种处置方向完全不同。
        """

        tip = route[-1]
        label = self._label(tip)
        outcome = self._outcome(tip)
        if tip["best_score"] is None:
            return f"末端 {label} {outcome}"
        scored = [item for item in route if item["best_score"] is not None]
        if len(scored) < 2:
            return f"末端 {label} {tip['best_score']:+.4f}，这条链上只有它出过分"
        delta = tip["best_score"] - scored[-2]["best_score"]
        return f"末端 {label} 最后一跳 {delta:+.4f}"

    def _section_routes(
        self, nodes: list[dict[str, Any]], by_id: Mapping[str, Mapping[str, Any]]
    ) -> list[str]:
        """第 1 区：图长什么样、哪条在涨。**全部列出，不截断、不排名截尾。**"""

        lines = ["## 路线（根到叶的完整世系，按链上最好分从高到低；全部列出）", ""]
        routes, truncated = self._routes(nodes, by_id)
        if not routes:
            return lines + ["暂无方案。", ""]
        routes.sort(key=lambda route: self._rank_key(self._route_best(route)))
        chains = [
            " → ".join(self._label(item) for item in route) for route in routes
        ]
        chain_width = max(_width(text) for text in chains)
        for pos, (route, chain) in enumerate(zip(routes, chains)):
            best = self._route_best(route)
            score = "未出分" if best is None else f"最好 {best:+.4f}"
            lines.append(
                f"{_route_letter(pos)}  {_pad(chain, chain_width)}  "
                f"{_pad(score, 12)}  {self._route_note(route)}"
            )
        if truncated:
            lines.append("")
            lines.append(f"（路线数超过 {ROUTE_LIMIT} 条，这里只列了前 {ROUTE_LIMIT} 条）")
        return lines + [""]

    def _section_nodes(
        self, nodes: list[dict[str, Any]], by_id: Mapping[str, Mapping[str, Any]]
    ) -> list[str]:
        """第 2 区：一个方案一条，按编号升序——顺序稳定，多次读到的排列一致。

        单父的父子关系由路线区表达，这里不重复；只有多父算子在行尾写
        `← NNNN, NNNN`，因为那条边在任何一条路线里都只看得到一半。
        """

        lines = ["## 方案（按编号升序）", ""]
        if not nodes:
            return lines + ["暂无方案。", ""]
        ordered = sorted(nodes, key=self._label)
        title_width = min(
            max(_width(item["title"]) for item in ordered), TITLE_COLUMN_LIMIT
        )
        for item in ordered:
            tail = ""
            if str(item["operator"] or "") in MULTI_PARENT_OPERATORS:
                refs = [
                    self._ref(parent, by_id)
                    for parent in item["parents"]
                    if parent != ROOT_ID
                ]
                if refs:
                    tail = "  ← " + ", ".join(refs)
            lines.append(
                "{seq}  {title}  {score}  {outcome}{tail}".format(
                    seq=self._label(item),
                    title=_pad(item["title"], title_width),
                    score=_pad(_score_text(item["best_score"]), 8),
                    outcome=self._outcome(item),
                    tail=tail,
                )
            )
            if item["brief"]:
                lines.append("      " + item["brief"])
            # 长 id 单独一行：它是 `graph/<id>.json` 的文件名，也是 grep 把手。
            # 不混进上面那行——上面那行是给人扫的，一串三十字的十六进制会把
            # 对齐好的列冲散。
            lines.append(f"      [{item['node_id']}]")
        return lines + [""]

    def _write_index(self) -> None:
        """重建 `GRAPH.md`——Agent 真正读到的那张表。

        两区：**路线**给方向，**方案**给细节入口。图结构只在路线区，方案区是
        扁平的、方案之间不互相指，所以 Agent 从头到尾读的都是线性列表。

        三条硬规矩：

        1. **编号是唯一地址。** 行首 `NNNN` 就是填进 `parents` 的东西，也是
           方案目录名。长 id 只在缩进行的方括号里当 grep 把手。
        2. **每个方案都有一句话说清它是什么。** 只给标题等于没给——`PROJ-Velo`
           这种自编缩写，三个回合之后 Agent 自己也认不出来。分数说明「这条路走
           通了」，描述才说明「走的是哪条路」。
        3. **长度由宿主控制。** 描述在宿主侧截断，截断痕迹（`…`）必须可见。

        全文（mechanism 全文 / implementation_plan / risks / 评测细节）不进索引，
        留在 `graph/<节点>.json` 按需读——渐进式披露。
        """

        nodes = [
            self._summary(record)
            for record in self._records()
            if str(record.get("node_id") or "") != ROOT_ID
        ]
        by_id = {item["node_id"]: item for item in nodes}
        scored = [item for item in nodes if item["best_score"] is not None]
        best = max((item["best_score"] for item in scored), default=None)

        lines = [
            "# 方案演化图 —— {total} 个方案，{n} 个出过分{tail}".format(
                total=len(nodes),
                n=len(scored),
                tail="" if best is None else f"，最好 {best:+.4f}",
            ),
            "",
            "行首四位数字是方案编号，提新方案时 `parents` 里填的就是它"
            "（填缩进行方括号里的长 id 也认）。缩进那行是这个方案在做什么，"
            "全文见 `graph/<长 id>.json`。算子："
            + "、".join(
                f"`{name}`（{OPERATOR_SPEC[name]['label']}，"
                f"父节点 {OPERATOR_SPEC[name]['parents']}）"
                for name in OPERATORS
            )
            + "。",
            "",
        ]
        lines += self._section_routes(nodes, by_id)
        lines += self._section_nodes(nodes, by_id)
        lines.append("")
        atomic_write_text(self.index_path, "\n".join(lines))

    # ------------------------------------------------- 与 v1 同签名的八个方法

    def submit(
        self,
        idea: Mapping[str, Any],
        *,
        actor_id: str | None = None,
        artifact_refs: list[str] | None = None,
        goal_contract_version: str | None = None,
    ) -> dict[str, Any]:
        """持久化一个方案节点。签名与 `IdeaGraphStore.submit` 逐字一致。

        算子非法时**抛 `ValueError`**，不替 agent 改。宿主把算子填成"最近的合法
        形态"等于替它做了一个它没做的决定：agent 永远不知道自己填错了，下次照错；
        而图上会多出一条它没打算建立的边，后来读图的人分不出哪些边是 agent 提的。

        合法性由 orchestrator 在提交时保证——非法就带着原因退回重提，重提几次仍
        非法的整条丢弃，不会走到这里。所以这里的非法是调用方的 bug，该响。
        """

        payload = dict(idea)
        node_id = str(payload.get("id") or new_id("idea"))
        payload["id"] = node_id
        path = self._path(node_id)
        with self._lock():
            if path.exists():
                raise FileExistsError(f"节点已存在，不能覆盖原始提案: {node_id}")
            known = self._known_ids()
            apply_legacy_prompt_shape(payload)
            self.resolve_parents_in_place(payload)
            check = validate_operator(
                payload, known, node_id=node_id, cycle_probe=self.would_cycle
            )
            if not check.ok:
                raise ValueError(f"算子非法，不予登记: {node_id} — {check.reason}")
            operator = str(check.operator)
            parents = list(check.parents)
            notes: list[str] = []
            # 回退命中要留在节点上——它是「链路有没有跟上版本」的读数，
            # 跟算子合不合法是两回事。
            if used_legacy_parent_field(payload):
                notes.append(LEGACY_PARENT_FIELD_NOTE)
            payload["operator"] = operator
            payload["parents"] = list(parents)
            created_at = int(payload.get("created_at") or now_ms())
            record = {
                "schema_version": SCHEMA_VERSION,
                "node_id": node_id,
                # 提出时分配，终身不变。渲染期现算的号看似也能稳定，但任何
                # 改变排序的因素都会让它整体漂移一位——Agent 上一回合记住的
                # 0007 到下一回合指向别人，这种错不会报错，只会悄悄建错边。
                "seq": self._next_seq(),
                "operator": operator,
                "parents": list(parents),
                "root_branch": self._root_branch(parents, node_id),
                "actor_id": actor_id or payload.get("idea_actor_id"),
                "status": LoopStatus.Idea.SUBMITTED,
                "goal_contract_version": goal_contract_version,
                "idea": payload,
                "attempts": [],
                "attempt_ids": [],
                "best_score": None,
                "reviews": [],
                "artifact_refs": list(artifact_refs or []),
                "operator_notes": notes,
                "created_at": created_at,
                "updated_at": created_at,
            }
            atomic_write_json(path, record)
            self._write_index()
            return record

    def begin_review(self, idea_id: str) -> dict[str, Any]:
        """把已提交方案标记为正在同步评审。"""

        return self._update(idea_id, status=LoopStatus.Idea.UNDER_REVIEW)

    def admit_without_review(
        self,
        idea_id: str,
        *,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Gate 关闭时直接准入，并明确记录未经过 Judge。"""

        with self._lock():
            record = self.read(idea_id)
            refs = list(record.get("artifact_refs") or [])
            for ref in artifact_refs or []:
                if ref not in refs:
                    refs.append(ref)
            record.update(
                {
                    "status": LoopStatus.Idea.ACCEPTED,
                    "admission": {
                        "mode": "gate_disabled",
                        "decision": "enqueue_without_gate",
                        "created_at": now_ms(),
                    },
                    "artifact_refs": refs,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def record_review(
        self,
        idea_id: str,
        review: Mapping[str, Any],
        *,
        artifact_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """追加 Gate 结果，并把 verdict 映射到稳定状态。

        ⚠️ benchmark 路径上这个方法**从不被调用**（没有 Judge）。run 内拿不到
        Judge 有效性，所以融合门槛只能用数值有效性代替——这是已登记的欠账。
        """

        verdict = str(review.get("verdict") or "reject")
        status_by_verdict = {
            "pass": LoopStatus.Idea.ACCEPTED,
            "revise": LoopStatus.Idea.REVISION_REQUESTED,
            "reject": LoopStatus.Idea.REJECTED,
            "needs_evidence": LoopStatus.Idea.NEEDS_EVIDENCE,
        }
        with self._lock():
            record = self.read(idea_id)
            reviews = list(record.get("reviews") or [])
            reviews.append(dict(review))
            refs = list(record.get("artifact_refs") or [])
            for ref in artifact_refs or []:
                if ref not in refs:
                    refs.append(ref)
            record.update(
                {
                    "status": status_by_verdict.get(verdict, LoopStatus.Idea.REJECTED),
                    "reviews": reviews,
                    "artifact_refs": refs,
                    "updated_at": now_ms(),
                }
            )
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def read(self, idea_id: str) -> dict[str, Any]:
        """读取指定节点的完整记录。"""

        value = read_json(self._path(idea_id))
        if not isinstance(value, dict):
            raise FileNotFoundError(f"演化图节点不存在: {idea_id}")
        return value

    def latest_review(self, *, actor_id: str | None = None) -> dict[str, Any] | None:
        """返回指定 actor 最近一次 Gate 反馈。"""

        records = [
            item
            for item in self._records()
            if str(item.get("node_id") or "") != ROOT_ID
        ]
        if actor_id:
            records = [item for item in records if item.get("actor_id") == actor_id]
        reviewed = [item for item in records if item.get("reviews")]
        if not reviewed:
            return None
        record = max(reviewed, key=lambda item: int(item.get("updated_at") or 0))
        return {
            # 这个 key 是 v1 `latest_review` 的返回契约（§7.2 的同签名要求），
            # 不是节点上的存储字段——节点上的权威身份只有 node_id。
            "idea_id": record.get("node_id"),
            "status": record.get("status"),
            "review": dict(record["reviews"][-1]),
        }

    def link_attempt(self, idea_id: str, attempt_id: str) -> dict[str, Any]:
        """建立 node↔attempt 的关联。

        ⚠️ **这里拿不到分数**——分数是评测完才出的。上一批 README §七.5 把
        「`link_attempt` 回填分数的时序」列为未决，答案就是拿不到。所以这里只建
        空壳，海拔由 `record_attempt_result` 在评测落盘处补。
        """

        return self._upsert_attempt(idea_id, attempt_id, {}, status=LoopStatus.Idea.IMPLEMENTING)

    def record_implementation(
        self,
        idea_id: str,
        *,
        succeeded: bool,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        """按实现结果更新节点，但不把工程失败解释为科研失败。"""

        status = (
            LoopStatus.Idea.IMPLEMENTED
            if succeeded
            else LoopStatus.Idea.IMPLEMENTATION_FAILED
        )
        if attempt_id:
            return self._upsert_attempt(idea_id, attempt_id, {}, status=status)
        return self._update(idea_id, status=status)

    # ---------------------------------------------------------- v2 新增的能力

    def record_attempt_result(
        self,
        idea_id: str,
        attempt_id: str,
        *,
        status: Any = None,
        score: Any = None,
        conclusion: str | None = None,
        paths: Mapping[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """把评测结果回填到节点，并更新 `best_score`——给图装上海拔。

        挂在评测结果落盘处（`orchestrator.py:4598-4636`）。同一个 `attempt_id`
        是 **upsert**，不是追加：重试的多条 attempt 挂到同一节点，不新建节点。
        `[失败, 失败, 0.0653]` 说的是「这条路试了三次才通」，不是三个方案。
        """

        patch: dict[str, Any] = {}
        if status is not None:
            patch["status"] = str(status)
        if score is not None:
            patch["score"] = _finite(score)
        if conclusion is not None:
            patch["conclusion"] = str(conclusion)
        if paths is not None:
            patch["paths"] = dict(paths)
        if evidence_refs is not None:
            patch["evidence_refs"] = _str_list(evidence_refs)
        return self._upsert_attempt(idea_id, attempt_id, patch)

    def register_weights(
        self,
        idea_id: str,
        attempt_id: str,
        weights: Mapping[str, Any],
    ) -> dict[str, Any]:
        """登记 agent 自己落盘的权重位置。宿主只登记，不搬运。

        `weights` 形如 `{"dir": ..., "framework": ..., "files": [{path, sha256,
        bytes}]}`。校验（存在、不越界、大小上限）在调用方做——这里只负责让路径
        成为节点的一部分信息。
        """

        return self._upsert_attempt(
            idea_id, attempt_id, {"weights": dict(weights)}
        )

    def parents(self, idea_id: str) -> list[str]:
        """返回某节点的父节点列表（入边）。"""

        try:
            return _str_list(self.read(idea_id).get("parents"))
        except (FileNotFoundError, ValueError):
            return []

    def frontier(self) -> list[dict[str, Any]]:
        """返回「提了没做」的节点摘要——图上的前沿。"""

        return [
            item
            for record in self._records()
            if str(record.get("node_id") or "") != ROOT_ID
            and (item := self._summary(record))["attempts"] == 0
        ]

    def top_scored(self, k: int = 5) -> list[dict[str, Any]]:
        """返回最好分最高的 k 个节点摘要——最该被「利用」的那些。"""

        scored = [
            item
            for record in self._records()
            if str(record.get("node_id") or "") != ROOT_ID
            and (item := self._summary(record))["best_score"] is not None
        ]
        scored.sort(key=lambda item: -item["best_score"])
        return scored[: max(0, int(k))]

    def fusable_attempts(self, idea_id: str) -> list[dict[str, Any]]:
        """返回可用于融合的 attempt：有有限分，且状态不在失败集合里。

        `cross` 的融合代码由 agent 自己写，宿主只递引用和门槛——这条边界和
        「绝不 host 侧改分」是同一条纪律。
        """

        try:
            record = self.read(idea_id)
        except (FileNotFoundError, ValueError):
            return []
        out = []
        for attempt in record.get("attempts") or []:
            if not isinstance(attempt, Mapping):
                continue
            if _finite(attempt.get("score")) is None:
                continue
            if str(attempt.get("status") or "") in UNFUSABLE_STATUSES:
                continue
            out.append(dict(attempt))
        return out

    # ---------------------------------------------------------------- 内部写入

    def _upsert_attempt(
        self,
        idea_id: str,
        attempt_id: str,
        patch: Mapping[str, Any],
        *,
        status: Any = None,
    ) -> dict[str, Any]:
        """按 `attempt_id` upsert 一条 attempt，并重算 `best_score`。"""

        key = str(attempt_id or "")
        if not key:
            raise ValueError("attempt_id 不能为空")
        with self._lock():
            record = self.read(idea_id)
            attempts = [
                dict(item)
                for item in (record.get("attempts") or [])
                if isinstance(item, Mapping)
            ]
            for entry in attempts:
                if str(entry.get("attempt_id") or "") == key:
                    entry.update(patch)
                    break
            else:
                entry = {"attempt_id": key}
                entry.update(patch)
                attempts.append(entry)
            scores = [
                value
                for item in attempts
                if (value := _finite(item.get("score"))) is not None
            ]
            record["attempts"] = attempts
            record["attempt_ids"] = [
                str(item.get("attempt_id") or "") for item in attempts
            ]
            record["best_score"] = max(scores) if scores else None
            if status is not None:
                record["status"] = status
            record["updated_at"] = now_ms()
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record

    def _update(self, idea_id: str, **changes: Any) -> dict[str, Any]:
        """原子更新一个节点并同步索引。"""

        with self._lock():
            record = self.read(idea_id)
            record.update(changes)
            record["updated_at"] = now_ms()
            atomic_write_json(self._path(idea_id), record)
            self._write_index()
            return record


class IdeaGraphV1Facade(IdeaGraphStore):
    """v1 存储原样 + v2 新增方法的 no-op 兜底。

    行为与 `IdeaGraphStore` **逐字节一致**（只加方法，不覆写任何已有方法，也不动
    `idea_graph.py`）；`isinstance(store, IdeaGraphStore)` 仍然成立。加 no-op 的
    目的只有一个：`record_attempt_result` / `register_weights` 这些新调用点在 v1
    臂上也能无条件调用，不必在 orchestrator 里再手抄一份版本判断——那正是
    `_idea_graph_active()` 的 docstring 警告过的事。
    """

    def record_attempt_result(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """v1 图上没有分数，这里什么都不做。"""

        return {}

    def register_weights(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """v1 不登记权重。"""

        return {}

    def parents(self, idea_id: str) -> list[str]:
        """v1 只有单父字符串，按列表口径返回。"""

        try:
            return _str_list(self.read(idea_id).get("parent_idea_id"))
        except (FileNotFoundError, ValueError):
            return []

    def frontier(self) -> list[dict[str, Any]]:
        """v1 无法区分「提了没做」和「跑了没出分」。"""

        return []

    def top_scored(self, k: int = 5) -> list[dict[str, Any]]:
        """v1 图上没有分数，排不出高分榜。"""

        return []

    def fusable_attempts(self, idea_id: str) -> list[dict[str, Any]]:
        """v1 不支持融合。"""

        return []

    def known_ids(self) -> set[str]:
        """v1 不做算子校验，返回空集合即让两段式重提整体短路。"""

        return set()


#: 允许的图版本。非法值在 harness 层抛错、在 orchestrator 层钳到默认，所以走到
#: 工厂时不该再出现——真出现了就是代码 bug，直接抛。
GRAPH_VERSIONS: tuple[str, ...] = ("v1", "v2")
DEFAULT_GRAPH_VERSION = "v1"


def make_idea_graph(
    workspace: str | Path,
    *,
    version: str = DEFAULT_GRAPH_VERSION,
) -> IdeaGraphStore | EvolutionGraphStore:
    """按版本选择方案图实现。

    **默认必须是 v1**：`submit_one_click.sh` 是所有历史批次共用的提交脚本，默认
    开 v2 会静默改变后续一切 run 的行为。

    ⚠️ 两个版本的构造都**有副作用**（mkdir + 写空索引），所以「`GRAPH.md` 是空的」
    不能用来区分两臂——臂标识必须落在 run-config JSON 里。
    """

    value = str(version or DEFAULT_GRAPH_VERSION)
    if value not in GRAPH_VERSIONS:
        raise ValueError(
            f"未知的方案图版本: {version!r}，合法值：{'/'.join(GRAPH_VERSIONS)}"
        )
    if value == "v2":
        return EvolutionGraphStore(workspace)
    return IdeaGraphV1Facade(workspace)


__all__ = [
    "BRIEF_LIMIT",
    "DEFAULT_GRAPH_VERSION",
    "GRAPH_VERSIONS",
    "LEGACY_PARENT_FIELD_NOTE",
    "OPERATORS",
    "MULTI_PARENT_OPERATORS",
    "OPERATOR_CROSS",
    "OPERATOR_EXPLOIT",
    "OPERATOR_ENSEMBLE",
    "OPERATOR_INNOVATE",
    "OPERATOR_SPEC",
    "ROUTE_LIMIT",
    "SEQ_WIDTH",
    "TITLE_COLUMN_LIMIT",
    "ROOT_ID",
    "SCHEMA_VERSION",
    "UNFUSABLE_STATUSES",
    "EvolutionGraphStore",
    "IdeaGraphV1Facade",
    "OperatorCheck",
    "apply_legacy_prompt_shape",
    "format_seq",
    "make_idea_graph",
    "read_parents",
    "used_legacy_parent_field",
    "validate_operator",
]
