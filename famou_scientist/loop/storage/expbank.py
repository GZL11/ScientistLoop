"""面向 Agent 和研究者的扁平实验经验库。"""
from __future__ import annotations

import json
import shutil
import statistics
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 回退
    fcntl = None

from ..utils import (
    atomic_write_json,
    atomic_write_text,
    now_ms,
    read_json,
    safe_name,
    sha256_file,
)
from ..domain.status import LoopStatus


_CODE_EXCLUDES = {
    "__pycache__",
    "benchmark_task",
    "famou_agent_result.json",
    "famou_idea_result.json",
    "output",
    "outputs",
}


def _markdown_cell(value: Any) -> str:
    """把值转换成不会破坏 Markdown 表格的单行文本。"""
    text = "" if value is None else str(value)
    return " ".join(text.replace("|", "\\|").split())


def _fmt_number(value: float) -> str:
    """用有效数字格式化指标，兼顾接近 0 与无界的两种量纲。"""
    return f"{value:.6g}"


def _numeric_mapping(value: Any) -> dict[str, float]:
    """把 ``{名称: 数值}`` 映射里的有限数值挑出来。"""
    if not isinstance(value, Mapping):
        return {}
    return {
        str(name): float(item)
        for name, item in value.items()
        # bool 是 int 的子类，但它不是指标。
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    }


def extract_per_instance_improvement(evaluation: Any) -> dict[str, float]:
    """从评测记录中定位逐实例 improvement。

    评测回执按 adapter 不同会把它放在 ``extra``、``diagnostics_public`` 或顶层，
    三处都要找，且必须与 orchestrator 的诊断口径完全一致。
    """

    if not isinstance(evaluation, Mapping):
        return {}
    for key in ("extra", "diagnostics_public"):
        block = evaluation.get(key)
        if isinstance(block, Mapping):
            found = _numeric_mapping(block.get("per_instance_improvement"))
            if found:
                return found
    return _numeric_mapping(evaluation.get("per_instance_improvement"))


def worst_instance_summary(per_instance: Mapping[str, float]) -> dict[str, Any] | None:
    """定位拖累主指标的实例。

    主指标是各实例的算术平均，最差实例主导全局，因此它是提升杠杆最大的目标；
    但平均之后这个信息在标量分数里就看不见了。
    """

    numeric = _numeric_mapping(per_instance)
    if not numeric:
        return None
    name = min(numeric, key=numeric.__getitem__)
    others = [value for key, value in numeric.items() if key != name]
    return {
        "instance": name,
        "value": numeric[name],
        "instance_count": len(numeric),
        "others_mean": statistics.mean(others) if others else None,
        # improvement >= 0 即该实例已达到 SOTA。
        "above_target_count": sum(1 for value in numeric.values() if value >= 0),
    }


def _raw_score_cell(raw_scores: Any, instance: str) -> str:
    """把某个实例的原始子指标渲染成一个表格单元。"""
    if not isinstance(raw_scores, Mapping):
        return "-"
    entry = raw_scores.get(instance)
    if isinstance(entry, Mapping):
        parts = [
            f"{name}={_fmt_number(float(value))}"
            for name, value in entry.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        return "; ".join(parts) if parts else "-"
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        return _fmt_number(float(entry))
    return "-"


def _result_lines(evaluation: Mapping[str, Any], metrics: Mapping[str, Any]) -> list[str]:
    """生成 ``## 结果`` 段。

    此前这一段只有聚合指标的 JSON 块。聚合分是各实例的算术平均，单个差实例就能
    把它压到达标线以下，而"是哪个实例"在标量里完全不可见 —— Idea Agent 读的正是
    这份摘要（逐实例数据虽然在 record.json 与 evidence/evaluation.json 里，
    但它实测很少去翻）。因此这里直接把逐实例视图摊开。
    """

    per_instance = extract_per_instance_improvement(evaluation)
    lines = ["## 结果", ""]
    if not per_instance:
        lines.extend(["```json", json.dumps(metrics, ensure_ascii=False, indent=2), "```", ""])
        return lines

    worst = worst_instance_summary(per_instance)
    aggregate = metrics.get("aggregate_improvement")
    if not isinstance(aggregate, (int, float)) or isinstance(aggregate, bool):
        aggregate = statistics.mean(per_instance.values())
    others_mean = worst["others_mean"] if worst else None
    extra = evaluation.get("extra") if isinstance(evaluation.get("extra"), Mapping) else {}
    raw_scores = extra.get("raw_scores") or evaluation.get("raw_scores")

    lines.extend(
        [
            f"- 聚合指标：`{_fmt_number(float(aggregate))}`（各实例 improvement 的算术平均）",
            "- 已达标实例：`{n} / {total}`（improvement ≥ 0 即该实例达到 SOTA）".format(
                n=worst["above_target_count"], total=worst["instance_count"]
            ),
            "- 最差实例：`{name}`，improvement `{value}`，其余实例均值 `{mean}`".format(
                name=_markdown_cell(worst["instance"]),
                value=_fmt_number(worst["value"]),
                mean=_fmt_number(others_mean) if others_mean is not None else "-",
            ),
            "",
            "| 实例 | improvement | 原始子指标 | 达标 |",
            "|---|---:|---|:---:|",
        ]
    )
    for name, value in sorted(per_instance.items(), key=lambda item: item[1]):
        label = _markdown_cell(name)
        if worst and name == worst["instance"]:
            # 加粗最差实例，避免它在长表里被读漏。
            label = f"**{label}**"
        lines.append(
            "| {label} | {value} | {raw} | {ok} |".format(
                label=label,
                value=_fmt_number(value),
                raw=_markdown_cell(_raw_score_cell(raw_scores, name)),
                ok="✓" if value >= 0 else "✗",
            )
        )
    lines.extend(["", "```json", json.dumps(metrics, ensure_ascii=False, indent=2), "```", ""])
    return lines



def _summary_text(record: Mapping[str, Any]) -> str:
    """根据结构化记录生成单次尝试的可浏览摘要。"""
    idea = record.get("idea") if isinstance(record.get("idea"), Mapping) else {}
    implementation = (
        record.get("implementation")
        if isinstance(record.get("implementation"), Mapping)
        else {}
    )
    evaluation = (
        record.get("evaluation")
        if isinstance(record.get("evaluation"), Mapping)
        else {}
    )
    title = (
        idea.get("title")
        or implementation.get("title")
        or implementation.get("method_summary")
        or "未命名方法"
    )
    method = (
        implementation.get("method_summary")
        or idea.get("method")
        or idea.get("mechanism")
        or "尚未记录方法描述。"
    )
    conclusion = record.get("conclusion") or "尚未形成结论。"
    score = record.get("score")
    metrics = evaluation.get("metrics") or evaluation.get("official_metrics") or {}
    paths = record.get("paths") if isinstance(record.get("paths"), Mapping) else {}
    lines = [
        f"# {record.get('attempt_id', '')} - {title}",
        "",
        f"- 状态：`{record.get('status', 'unknown')}`",
        f"- Lineage：`{record.get('lineage_id', '')}`",
        f"- Parent：`{record.get('parent_attempt_id') or '-'}`",
        f"- 分支：`{record.get('branch_id') or '-'}`",
        f"- 正式分数：`{score if score is not None else '-'}`",
        f"- 是否当前最佳：`{bool(record.get('promoted'))}`",
        "",
        "## Idea",
        "",
        str(idea.get("hypothesis") or idea.get("rationale") or idea.get("title") or "未记录。"),
        "",
        "## 方法",
        "",
        str(method),
        "",
        *_result_lines(evaluation, metrics),
        "## 结论",
        "",
        str(conclusion),
        "",
        "## 具体位置",
        "",
        f"- 冻结代码：`{paths.get('code') or 'code/'}`",
        f"- 执行证据：`{paths.get('run') or 'evidence/run.json'}`",
        f"- 评测证据：`{paths.get('evaluation') or 'evidence/evaluation.json'}`",
        f"- 提交产物：`{paths.get('output') or '-'}`",
        f"- 完整记录：`record.json`",
        "",
    ]
    error = record.get("error")
    if error:
        lines.extend(["## 问题", "", str(error), ""])
    failure = (
        record.get("failure")
        if isinstance(record.get("failure"), Mapping)
        else implementation.get("failure")
        if isinstance(implementation.get("failure"), Mapping)
        else {}
    )
    if failure:
        lines.extend(
            [
                "## 失败诊断",
                "",
                f"- 阶段：`{failure.get('failure_stage') or '-'}`",
                f"- 错误码：`{failure.get('error_code') or '-'}`",
                f"- 返回码：`{failure.get('return_code') if failure.get('return_code') is not None else '-'}`",
                f"- 信号：`{failure.get('signal') or '-'}`",
                f"- 是否超时：`{bool(failure.get('timed_out'))}`",
                f"- 是否已提交：`{bool(failure.get('submitted'))}`",
                f"- 是否可重试：`{bool(failure.get('retryable'))}`",
                f"- 诊断：{failure.get('message') or '-'}",
                f"- 建议：{failure.get('suggested_action') or '-'}",
                "",
            ]
        )
        diagnostics = (
            failure.get("diagnostics")
            if isinstance(failure.get("diagnostics"), Mapping)
            else {}
        )
        if diagnostics:
            lines.extend(
                [
                    "### 运行细节",
                    "",
                    "```json",
                    json.dumps(diagnostics, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
    next_step = record.get("next_step")
    if next_step:
        lines.extend(["## 下一步", "", str(next_step), ""])
    validity = record.get("validity_verdict")
    if isinstance(validity, Mapping):
        lines.extend(
            [
                "## Validity Verifier",
                "",
                f"- 状态：`{validity.get('status') or 'unknown'}`",
                f"- 原因：{'; '.join(str(item) for item in (validity.get('reasons') or [])) or '-'}",
                f"- 证据：{', '.join(str(item) for item in (validity.get('evidence_refs') or [])) or '-'}",
                "",
            ]
        )
    return "\n".join(lines)


class ExpBank:
    """以 ``INDEX.md + 编号目录`` 保存全部可公开研究尝试。"""

    def __init__(self, workspace: str | Path):
        """初始化 ExpBank 根目录和浏览索引。"""
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = self.workspace / "expbank"
        self.index_path = self.root / "INDEX.md"
        self.lock_path = self.root / ".lock"
        self.root.mkdir(parents=True, exist_ok=True)
        # INDEX.md 是 Agent 的默认入口；record.json 才是程序读取的结构化权威。
        if not self.index_path.exists():
            self._write_index()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """串行化编号分配与索引更新。"""
        # Implement 可以并发完成，编号分配和 INDEX 重建必须使用跨线程/进程文件锁，
        # 否则两个版本可能同时拿到相同的四位编号。
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _records(self) -> list[dict[str, Any]]:
        """按编号读取全部尝试记录。"""
        records: list[dict[str, Any]] = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or not directory.name.isdigit():
                # .lock、临时文件等不属于科研尝试，不能出现在 Agent 浏览索引中。
                continue
            record = read_json(directory / "record.json")
            if isinstance(record, dict):
                records.append(record)
        return records

    def all_attempts(self) -> list[dict[str, Any]]:
        """返回供收尾总结使用的全部公开尝试记录。"""

        return self._records()

    def _write_index(self) -> None:
        """从记录重建紧凑的根目录索引。"""
        # 索引始终由 record.json 全量重建，而不是增量拼接，避免并发更新后出现
        # 重复行或状态长期停留在旧值。
        records = self._records()
        # 「节点」列只在演化图 v2 下出现——判据是数据本身：v1 从不往 record.json
        # 里写 `idea_id`，所以 v1 臂的 INDEX.md 逐字节不变，不需要再往 ExpBank
        # 里塞一个版本开关。v2 写了，列就出现，attempt→方案 从此可以直接 join，
        # 不必再靠审计脚本替 Agent 拼（上一批正是这么拼出来的）。
        has_node = any(record.get("idea_id") for record in records)
        graph_link = (
            "[方案演化图](./GRAPH.md)" if has_node else "[Idea Graph](./IDEAS.md)"
        )
        lines = [
            "# ExpBank",
            "",
            "这里保存完整研究记忆。未实现 Idea、演化关系和 Gate 诊断见 "
            f"{graph_link}；已经进入实现、执行或评测阶段的方法列在下表。",
            "",
        ]
        if has_node:
            lines += [
                "| ID | 节点 | Idea / 方法 | 主要结果 | 分数 | 状态 | Parent |",
                "|---|---|---|---|---:|---|---|",
            ]
        else:
            lines += [
                "| ID | Idea / 方法 | 主要结果 | 分数 | 状态 | Parent |",
                "|---|---|---|---:|---|---|",
            ]
        if not records:
            lines.append(
                "| - | - | 暂无尝试 | - | - | - | - |"
                if has_node
                else "| - | 暂无尝试 | - | - | - | - |"
            )
        for record in records:
            idea = record.get("idea") if isinstance(record.get("idea"), Mapping) else {}
            implementation = (
                record.get("implementation")
                if isinstance(record.get("implementation"), Mapping)
                else {}
            )
            title = idea.get("title") or implementation.get("title") or "未命名方法"
            conclusion = record.get("conclusion") or record.get("error") or "待完成"
            score = record.get("score")
            # v1 下这里只是 ID 单元格的右边界；v2 下还要再闭合一个「节点」单元格，
            # 少一根竖线会让节点 id 和标题挤进同一列，表头与数据行就此错位。
            node_cell = (
                f"| {_markdown_cell(record.get('idea_id') or '-')} | " if has_node else "| "
            )
            lines.append(
                "| [{attempt}](./{attempt}/SUMMARY.md) {node}{title} | {conclusion} | {score} | {status} | {parent} |".format(
                    attempt=_markdown_cell(record.get("attempt_id")),
                    node=node_cell,
                    title=_markdown_cell(title),
                    conclusion=_markdown_cell(conclusion),
                    score=_markdown_cell(score if score is not None else "-"),
                    status=_markdown_cell(record.get("status") or "unknown"),
                    parent=_markdown_cell(record.get("parent_attempt_id") or "-"),
                )
            )
        lines.append("")
        atomic_write_text(self.index_path, "\n".join(lines))

    def _next_attempt_id(self) -> str:
        """返回下一个四位递增编号。"""
        # 该方法只能在 _lock() 内调用；四位编号用于浏览，不承载 lineage 关系。
        numbers = [
            int(path.name)
            for path in self.root.iterdir()
            if path.is_dir() and path.name.isdigit()
        ]
        return f"{(max(numbers) if numbers else 0) + 1:04d}"

    def create_attempt(
        self,
        *,
        idea: Mapping[str, Any],
        lineage_id: str,
        branch_id: str | None = None,
        parent_attempt_id: str | None = None,
        status: str = LoopStatus.ExpBank.IMPLEMENTING,
        metadata: Mapping[str, Any] | None = None,
        idea_id: str | None = None,
    ) -> str:
        """创建一个新的不可变提交版本记录并返回编号。

        `idea_id` 是方案在演化图上的节点身份（v2 才传）。在此之前 record.json 只
        把整个 idea 按值内嵌，**一个方案在系统里没有唯一身份**：上一批
        `s42256-025-01003-z` 的 16 个图节点 / 13 条 attempt 实际只对应 7 个方案，
        同一方案两套 id、两套父指针。写上它，attempt→node 就是显式 id，
        node→attempt 是 `attempts[]`，双向可 join。

        纯增量：不传就是 `None`，v1 读者不受影响。
        """
        with self._lock():
            # 先建立 evidence 目录和最小 record，再启动 Implement。失败版本因此也有
            # 稳定地址，不会只剩散落日志。
            attempt_id = self._next_attempt_id()
            directory = self.root / attempt_id
            (directory / "evidence").mkdir(parents=True)
            record = {
                "attempt_id": attempt_id,
                "idea_id": str(idea_id) if idea_id else None,
                "lineage_id": str(lineage_id),
                "parent_attempt_id": parent_attempt_id,
                "branch_id": branch_id,
                "status": status,
                "idea": dict(idea),
                "implementation": {},
                "evaluation": {},
                "failure": {},
                "score": None,
                "promoted": False,
                "conclusion": None,
                "error": None,
                "paths": {
                    # 大文件不重复嵌入 record；统一记录可追溯路径，代码另附逐文件哈希。
                    "summary": f"expbank/{attempt_id}/SUMMARY.md",
                    "record": f"expbank/{attempt_id}/record.json",
                    "code": f"expbank/{attempt_id}/code",
                    "run": f"expbank/{attempt_id}/evidence/run.json",
                    "evaluation": f"expbank/{attempt_id}/evidence/evaluation.json",
                },
                "metadata": dict(metadata or {}),
                "created_at": now_ms(),
                "updated_at": now_ms(),
            }
            atomic_write_json(directory / "record.json", record)
            atomic_write_text(directory / "SUMMARY.md", _summary_text(record))
            self._write_index()
            return attempt_id

    def read_attempt(self, attempt_id: str) -> dict[str, Any]:
        """读取指定编号的完整结构化记录。"""
        path = self.root / safe_name(attempt_id) / "record.json"
        record = read_json(path)
        if not isinstance(record, dict):
            raise FileNotFoundError(f"ExpBank 尝试不存在: {attempt_id}")
        return record

    def update_attempt(self, attempt_id: str, **changes: Any) -> dict[str, Any]:
        """更新尝试状态并同步摘要与根索引。"""
        with self._lock():
            directory = self.root / safe_name(attempt_id)
            record = self.read_attempt(attempt_id)
            record.update(changes)
            record["updated_at"] = now_ms()
            # record、单版本摘要和根索引在同一锁区间内更新，对 Agent 呈现一致状态。
            atomic_write_json(directory / "record.json", record)
            atomic_write_text(directory / "SUMMARY.md", _summary_text(record))
            self._write_index()
            return record

    def write_evidence_json(
        self,
        attempt_id: str,
        name: str,
        payload: Mapping[str, Any],
    ) -> Path:
        """在固定 evidence 目录写入结构化证据。"""
        # name 必须经过 safe_name，禁止用 ../ 把证据写到其他 attempt。
        path = self.root / safe_name(attempt_id) / "evidence" / f"{safe_name(name)}.json"
        atomic_write_json(path, dict(payload))
        return path

    def write_evidence_text(
        self,
        attempt_id: str,
        name: str,
        content: str,
    ) -> Path:
        """在固定 evidence 目录写入日志文本。"""
        path = self.root / safe_name(attempt_id) / "evidence" / f"{safe_name(name)}.log"
        atomic_write_text(path, content)
        return path

    def freeze_code(self, attempt_id: str, source: str | Path) -> Path:
        """复制并冻结本次提交的代码，同时记录逐文件哈希。"""
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_dir():
            raise FileNotFoundError(f"待冻结代码目录不存在: {source_path}")
        destination = self.root / safe_name(attempt_id) / "code"
        with self._lock():
            # 同一 attempt 的 code/ 只允许创建一次；覆盖会破坏“指标对应哪版代码”
            # 这一科研证据不变量。
            if destination.exists():
                raise FileExistsError(f"ExpBank 代码快照已经冻结: {destination}")
            shutil.copytree(
                source_path,
                destination,
                symlinks=False,
                ignore=shutil.ignore_patterns(*sorted(_CODE_EXCLUDES), "*.pyc"),
            )
            files = [
                {
                    "path": str(path.relative_to(destination)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in sorted(destination.rglob("*"))
                if path.is_file()
            ]
            # 哈希清单用于导出证据或最终提升时核验代码没有被静默修改。
            record = self.read_attempt(attempt_id)
            record["code_snapshot"] = {"path": str(destination), "files": files}
            record["updated_at"] = now_ms()
            atomic_write_json(destination.parent / "record.json", record)
            atomic_write_text(destination.parent / "SUMMARY.md", _summary_text(record))
            self._write_index()
        return destination


__all__ = [
    "ExpBank",
    "extract_per_instance_improvement",
    "worst_instance_summary",
]
