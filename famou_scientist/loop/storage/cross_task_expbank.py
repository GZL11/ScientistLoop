"""按 NatureBench 官方六领域组织的跨任务经验库。"""
from __future__ import annotations

import csv
import json
import math
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None

from ..utils import atomic_write_text, now_ms, read_json, safe_name


OFFICIAL_DOMAIN_SLUGS: dict[str, str] = {
    "Cellular Omics": "cellular_omics",
    "Protein Biology": "protein_biology",
    "Biomedical Modeling": "biomedical_modeling",
    "Physical Modeling": "physical_modeling",
    "Molecular Design": "molecular_design",
    "Relational Reasoning": "relational_reasoning",
}

_DOMAIN_ALIASES = {
    **{name.lower(): slug for name, slug in OFFICIAL_DOMAIN_SLUGS.items()},
    **{slug: slug for slug in OFFICIAL_DOMAIN_SLUGS.values()},
    "cellular-omics": "cellular_omics",
    "protein-biology": "protein_biology",
    "biomedical-modeling": "biomedical_modeling",
    "physical-modeling": "physical_modeling",
    "molecular-design": "molecular_design",
    "relational-reasoning": "relational_reasoning",
}


def normalize_experience_domain(value: Any) -> str | None:
    """把官方领域名称或 slug 规范化为目录名。"""

    text = str(value or "").strip().lower()
    if not text:
        return None
    return _DOMAIN_ALIASES.get(text.replace(" ", "_")) or _DOMAIN_ALIASES.get(text)


def achievement_level(best_score: Any) -> str:
    """把最佳分数映射成 NatureBench 公开成绩档位。

    这是 ``result`` 字段的**唯一口径**，Orchestrator 写入侧和目录投影侧都调它。
    历史上写入侧存的是 Loop 生命周期状态（``stopped`` 等），跑满墙钟正常收尾一律
    是 ``stopped``，实测 58/58 条目全同——既零信息量，又误导：Agent 看到
    ``result: "stopped"`` 挨着 ``best_score: -1.0``，很容易读成「这个 Run 崩了」。

    投影时派生而非读存量值，是为了让口径变更不需要数据迁移：旧记录的
    ``result`` 留在系统层做审计，Agent 看到的永远是按当前阈值算出来的档位。

    阈值与 ``integrations/naturebench/benchmark.py`` 的 ``score_interpretation``
    保持一致；那里是下发给 Idea Agent 的公开口径，两处必须同源。
    """

    if isinstance(best_score, bool) or not isinstance(best_score, (int, float)):
        return "no_valid_score"
    if not math.isfinite(float(best_score)):
        return "no_valid_score"
    if best_score > 0.1:
        return "surpass_sota"
    if best_score >= 0:
        return "match_sota"
    return "below_sota"


def public_task_summary(public_dir: str | Path | None) -> str | None:
    """从公开题面 README 提取一句话任务说明。

    这是目录里唯一能让 Agent 判断「这条经验和我的任务像不像」的字段。历史上
    Loop 侧从来没写过它，只有离线补写脚本会填，而那批记录又被内容闸门排除了——
    实测结果是该字段**永远是 null**，Idea Agent 拿到的同领域 20 条因此完全无法
    区分，只能盲开文件。

    取值只用公开题面（标题 + 「任务目标」段），不碰隐藏测试、GT 与私有
    evaluator。Orchestrator 写入侧和存量回填脚本共用本函数，避免两处解析漂移。
    """

    if not public_dir:
        return None
    readme = Path(str(public_dir)).expanduser() / "README.md"
    try:
        text = readme.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    title = ""
    objective_lines: list[str] = []
    collecting = False
    objective_heading = re.compile(
        r"^#{1,3}\s*(?:\d+\.\s*)?(?:task\s+objective|objective|任务目标)\s*$",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if objective_heading.match(stripped):
            collecting = True
            continue
        if collecting:
            if stripped.startswith("#"):
                break
            if stripped:
                objective_lines.append(stripped)
            elif objective_lines:
                break
    objective = " ".join(" ".join(objective_lines).split())
    summary = "；".join(part for part in (title, objective) if part)
    return summary[:400] if summary else None


def experience_bank_root(workspace: str | Path) -> Path:
    """从任意 Loop 工作空间定位项目级 ``.famou`` 经验库。"""

    resolved = Path(workspace).expanduser().resolve()
    for parent in (resolved, *resolved.parents):
        if parent.name == ".famou":
            return parent / "cross_task_expbank"
    return resolved.parent / "cross_task_expbank"


def _jsonl_records(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL，忽略空行并拒绝非对象记录。"""

    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"跨任务经验索引只能包含 JSON object: {path}")
        records.append(value)
    return records


def _markdown_list(values: Any, *, empty: str = "无") -> list[str]:
    """把字符串列表渲染为紧凑 Markdown。"""

    if not isinstance(values, list) or not values:
        return [f"- {empty}"]
    rendered: list[str] = []
    for value in values:
        if isinstance(value, dict):
            summary = value.get("summary") or value.get("claim") or value.get("title")
            rendered.append(f"- {summary or json.dumps(value, ensure_ascii=False)}")
        else:
            rendered.append(f"- {value}")
    return rendered


def _summary_markdown(record: Mapping[str, Any]) -> str:
    """将结构化演化总结渲染成人和 Agent 都便于浏览的 Markdown。"""

    lines = [
        "# 演化总结",
        "",
        f"- 领域：`{record.get('domain')}`",
        f"- 状态：`{record.get('result')}`",
        f"- 最佳尝试：`{record.get('best_attempt_id') or '无'}`",
        f"- 最佳分数：`{record.get('best_score') if record.get('best_score') is not None else '无'}`",
        f"- 尝试数量：`{record.get('attempt_count', 0)}`",
        "",
        "## 方法总结",
        "",
        str(record.get("method_summary") or "未形成可验证的方法总结。"),
        "",
        "## 有效经验",
        "",
        *_markdown_list(record.get("successful_ideas")),
        "",
        "## 失败经验",
        "",
        *_markdown_list(record.get("failed_ideas")),
        "",
        "## Refine 结论",
        "",
        *_markdown_list(record.get("refine_summary")),
        "",
    ]
    return "\n".join(lines)


def _agent_markdown(record: Mapping[str, Any]) -> str:
    """优先使用 Agent 原生 Markdown，并兼容旧结构化总结。"""

    value = record.get("evolution_markdown")
    if isinstance(value, str) and value.strip():
        return value.strip() + "\n"
    return _summary_markdown(record)


def _evolution_summary(record: Mapping[str, Any]) -> str:
    """Extract a short Agent-authored summary for the lightweight catalog."""

    explicit = record.get("evolution_summary")
    if isinstance(explicit, str) and explicit.strip():
        return " ".join(explicit.split())[:400]

    markdown = record.get("evolution_markdown")
    if isinstance(markdown, str) and markdown.strip():
        heading = re.compile(
            r"^#{1,3}\s*(?:evolution summary|演化摘要|简要演化总结|一句话总结)\s*$",
            re.IGNORECASE,
        )
        collecting = False
        parts: list[str] = []
        for line in markdown.splitlines():
            stripped = line.strip()
            if heading.match(stripped):
                collecting = True
                continue
            if collecting and stripped.startswith("#"):
                break
            if collecting and stripped:
                parts.append(re.sub(r"^[-*]\s+", "", stripped))
        if parts:
            return " ".join(" ".join(parts).split())[:400]

    fallback = record.get("method_summary")
    if isinstance(fallback, str) and fallback.strip():
        return " ".join(fallback.split())[:400]
    return ""


def _is_judge_valid(record: Mapping[str, Any]) -> bool:
    """只有明确的 Judge Valid 记录才能进入 Agent-facing 经验库。"""

    verdict = record.get("judge_verdict")
    if verdict is True:
        return True
    if isinstance(verdict, str):
        return verdict.strip().lower() == "valid"
    if isinstance(verdict, Mapping):
        return verdict.get("is_valid") is True or str(
            verdict.get("status") or ""
        ).strip().lower() == "valid"
    return False


def _has_agent_summary(record: Mapping[str, Any]) -> bool:
    """总结是否由复盘 Agent 亲手写成，而不是机器罗列。

    要排除两类机器产物：

    1. **控制器兜底**：复盘 Agent 失败时 ``_base_experience_summary`` 产出
       「方法标题 + 分数 + refine 血缘」，没有 ``evolution_markdown``。
    2. **离线补写**：``offline_cross_task_summary.py`` 事后从 run 目录拼出的
       Markdown。它有 ``evolution_markdown``，所以光看字段存在性挡不住它，
       但实测 34/34 都没有 ``When to use`` / ``When not to use``，可迁移经验
       字段也只有两句按分数拼的模板话。用 ``offline_generated`` 标记排除。

    两类对读它的下游 Agent 都是纯负价值——占 token、占注意力，还让它以为
    自己在读经验。
    """

    value = record.get("evolution_markdown")
    if not (isinstance(value, str) and value.strip()):
        return False
    return not record.get("offline_generated")


def is_agent_visible(record: Mapping[str, Any]) -> bool:
    """Agent 可见 = 合规通过 **且** 有实际内容。

    两道闸门是正交的，缺一不可：

    - ``_is_judge_valid``：解法没作弊。作弊方案的「经验」传播出去有害。
    - ``_has_agent_summary``：总结真有内容。

    历史上只有第一道，结果目录里 107 条有 90 条是兜底残次品，而 39 条
    Agent 手写的好总结因为缺一张合规票据被挡在外面——过滤器与质量正交，
    且恰好是反的。
    """

    return _is_judge_valid(record) and _has_agent_summary(record)


CATALOG_FIELDS = (
    "domain",
    "task_summary",
    "result",
    "best_score",
    "summary_path",
    "evolution_summary",
)


def catalog_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    """把系统记录投影成 Agent 目录条目。

    写入（``upsert_summary``）和重建（``rebuild_catalog``）必须走同一个函数，
    否则两条路径会长出不同的字段集——历史上就是这么漏掉 ``evolution_summary``
    的：目录里有，下发给 Idea Agent 的载荷里没有。

    ``result`` 在这里**派生**，不读存量值；理由见 ``achievement_level``。
    """

    item = {
        key: record[key]
        for key in CATALOG_FIELDS
        if key in record and record[key] is not None
    }
    item["result"] = achievement_level(record.get("best_score"))
    summary = _evolution_summary(record)
    if summary:
        item["evolution_summary"] = summary
    else:
        item.pop("evolution_summary", None)
    return item


class CrossTaskExpBank:
    """维护六领域目录、任务演化总结和全局 JSONL 索引。"""

    def __init__(self, root: str | Path):
        """初始化目录结构；锁文件放在库目录外，保持库内结构简洁。"""

        self.root = Path(root).expanduser().resolve()
        self.index_path = self.root / "index.jsonl"
        # Keep the complete system/audit record outside the Agent catalog. The
        # public index is intentionally small so a search never loads the full
        # evolution trajectory for every historical Run.
        self.system_index_path = self.root.parent / f".{self.root.name}.system.jsonl"
        self.lock_path = self.root.parent / ".cross_task_expbank.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        for slug in OFFICIAL_DOMAIN_SLUGS.values():
            (self.root / slug).mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            atomic_write_text(self.index_path, "")
        readme = self.root / "README.md"
        if not readme.exists():
            atomic_write_text(readme, self._readme())

    @classmethod
    def for_workspace(cls, workspace: str | Path) -> "CrossTaskExpBank":
        """从 Loop 工作空间创建项目级跨任务经验库。"""

        return cls(experience_bank_root(workspace))

    @staticmethod
    def _readme() -> str:
        """返回六领域经验库的固定说明。"""

        domains = "\n".join(
            f"- `{slug}/`：{name}"
            for name, slug in OFFICIAL_DOMAIN_SLUGS.items()
        )
        return (
            "# Cross-task ExpBank\n\n"
            "该目录保存 Loop 在任务结束时生成的、已通过 Judge Valid 筛选的可追溯"
            "演化总结。经验按 NatureBench 官方六领域归档；`index.jsonl` 是供 Agent "
            "筛选的轻量目录，完整系统记录保存在库目录外。\n\n"
            "Judge Invalid、判定未知或缺少 Judge 结果的总结不会发布到本目录。\n\n"
            f"{domains}\n\n"
            "每条总结必须引用原 Run 的公开 ExpBank 证据。禁止写入 hidden test、"
            "GT、私有 evaluator 源码、凭据或私有 endpoint。\n"
        )

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """串行化跨进程索引更新。"""

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def upsert_summary(self, summary: Mapping[str, Any]) -> dict[str, Any]:
        """幂等写入单个 Run，并分别更新轻量目录和系统完整记录。"""

        domain = normalize_experience_domain(summary.get("domain"))
        if domain is None:
            raise ValueError(f"不支持的 NatureBench 领域: {summary.get('domain')!r}")
        task_id = str(summary.get("task_id") or summary.get("goal_id") or "").strip()
        run_id = str(summary.get("run_id") or "").strip()
        if not task_id or not run_id:
            raise ValueError("跨任务经验必须包含 task_id/goal_id 和 run_id")

        experience_id = safe_name(
            str(summary.get("experience_id") or f"{task_id}--{run_id}")
        )
        relative_path = Path(domain) / f"{experience_id}.md"
        record = dict(summary)
        record.update(
            {
                "experience_id": experience_id,
                "domain": domain,
                "summary_path": relative_path.as_posix(),
                "agent_visible": is_agent_visible(record),
                "updated_at": now_ms(),
            }
        )

        catalog_record = catalog_projection(record)

        with self._lock():
            catalog_records = _jsonl_records(self.index_path)
            system_records = _jsonl_records(self.system_index_path)
            # Migrate pre-slim-index data on the first write without losing
            # fields that existing callers use through records().
            if not system_records:
                system_records = catalog_records
            by_id = {
                str(item.get("summary_path") or item.get("experience_id")): {
                    key: item[key]
                    for key in CATALOG_FIELDS
                    if key in item and item[key] is not None
                }
                for item in catalog_records
                if item.get("experience_id") or item.get("summary_path")
            }
            if record["agent_visible"]:
                by_id[str(catalog_record["summary_path"])] = catalog_record
            else:
                by_id.pop(str(catalog_record["summary_path"]), None)
            system_by_id = {
                str(item.get("experience_id")): item
                for item in system_records
                if item.get("experience_id")
            }
            system_by_id[experience_id] = record
            ordered = sorted(
                by_id.values(),
                key=lambda item: (
                    str(item.get("domain") or ""),
                    str(item.get("task_summary") or ""),
                    str(item.get("summary_path") or ""),
                ),
            )
            text = "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in ordered
            )
            atomic_write_text(self.index_path, text)
            system_ordered = sorted(
                system_by_id.values(),
                key=lambda item: (
                    str(item.get("domain") or ""),
                    str(item.get("task_id") or ""),
                    str(item.get("run_id") or ""),
                ),
            )
            atomic_write_text(
                self.system_index_path,
                "".join(
                    json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                    for item in system_ordered
                ),
            )
            published_path = self.root / relative_path
            if record["agent_visible"]:
                atomic_write_text(published_path, _agent_markdown(record))
            elif published_path.is_file():
                published_path.unlink()
        return record

    def records(self) -> list[dict[str, Any]]:
        """返回当前系统完整记录快照（不是 Agent-facing 目录）。"""

        records = _jsonl_records(self.system_index_path)
        return records or _jsonl_records(self.index_path)

    def rebuild_catalog(self) -> int:
        """Rebuild the Agent-facing projection from the system index.

        This also upgrades catalogs written by older versions when a new
        lightweight field is introduced.
        """

        with self._lock():
            records = _jsonl_records(self.system_index_path)
            if not records:
                records = _jsonl_records(self.index_path)
            projected: list[dict[str, Any]] = []
            for record in records:
                if not record.get("summary_path") or not is_agent_visible(record):
                    continue
                projected.append(catalog_projection(record))
            projected.sort(
                key=lambda item: (
                    str(item.get("domain") or ""),
                    str(item.get("task_summary") or ""),
                    str(item.get("summary_path") or ""),
                )
            )
            atomic_write_text(
                self.index_path,
                "".join(
                    json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                    for item in projected
                ),
            )
            # 清掉不在投影里的 Markdown。upsert_summary 只会撤回它当次写的那一篇，
            # 所以口径收紧（例如新增内容闸门）之后，旧的已发布文件会留在库里成为
            # 孤儿——实测一次收紧后磁盘 88 篇、目录只收录 58 篇。Run 快照那边
            # seed_run 会物理删除未收录文件，所以孤儿不会被 Agent 读到，但它们
            # 会在事后诊断时误导（本次就先被那 30 篇离线补写带偏过一轮）。
            kept = {str(item.get("summary_path")) for item in projected}
            for markdown in self.root.glob("*/**/*.md"):
                relative = markdown.relative_to(self.root).as_posix()
                if relative not in kept:
                    markdown.unlink()
            return len(projected)

    def domain_counts(self) -> dict[str, int]:
        """统计目录里每个领域有多少条经验。

        取代原来的 ``search()``。``search()`` 的职责是「替 Idea Agent 决定这轮
        看哪 20 条」——那既不必要也出过事：

        - 不必要：Idea Agent 是带 Read/Grep/Glob 的 CLI Agent，库就在它工作区
          里（外层 ``index.jsonl`` + 六个领域目录，目录下一篇篇演化总结），
          按自己的 domain grep 一下索引就能挑，不需要调度器代劳。
        - 出过事：按 ``updated_at`` 倒序取前 20，同一任务的多次重跑会连成一片。
          2026-09-06 那批 A/B 里 cellular_omics 有 33 条同领域条目、其中有内容
          的 3 条，前 20 条里一条都没有——那 4 个任务的处理臂等价于对照臂。
        - 自任务屏蔽这唯一不能交给 Agent 的事，也不在 ``search()`` 里：
          ``seed_run`` 拷快照时会删索引条目**并物理删除对应的 .md**。

        剩下要的只是「这个 run 拿到了多少经验」这个可观测量，就是本函数。
        """

        counts: dict[str, int] = {}
        for record in _jsonl_records(self.index_path):
            domain = normalize_experience_domain(record.get("domain"))
            if domain is None:
                continue
            counts[domain] = counts.get(domain, 0) + 1
        return dict(sorted(counts.items()))


def load_naturebench_domain(task_id: str) -> str | None:
    """从仓库内官方 90-case 映射快照解析 NatureBench 领域。"""

    metadata_path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "naturebench"
        / "leaderboard"
        / "case_metadata.csv"
    )
    if not metadata_path.is_file():
        return None
    with metadata_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("case_id") or "").strip() == str(task_id).strip():
                return normalize_experience_domain(row.get("domain"))
    return None


def resolve_experience_domain(goal_doc: Mapping[str, Any]) -> str | None:
    """从 Goal 公开契约或 NatureBench case 映射中解析经验领域。"""

    task = goal_doc.get("benchmark_task")
    task = task if isinstance(task, Mapping) else {}
    contract = task.get("task_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    for value in (
        contract.get("domain"),
        task.get("domain"),
        goal_doc.get("experience_domain"),
    ):
        normalized = normalize_experience_domain(value)
        if normalized:
            return normalized
    if str(task.get("type") or "").lower() == "naturebench":
        return load_naturebench_domain(str(task.get("task_id") or ""))
    return None


__all__ = [
    "CATALOG_FIELDS",
    "CrossTaskExpBank",
    "OFFICIAL_DOMAIN_SLUGS",
    "achievement_level",
    "catalog_projection",
    "experience_bank_root",
    "is_agent_visible",
    "load_naturebench_domain",
    "normalize_experience_domain",
    "public_task_summary",
    "resolve_experience_domain",
]
