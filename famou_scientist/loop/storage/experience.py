"""共享经验池的轻量持久化实现。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import append_jsonl, new_id, now_ms, read_jsonl


_TYPE_FILE = {
    "external_baseline": "external_baselines.jsonl",
    "literature_method": "literature_methods.jsonl",
    "attempted_idea": "attempted_ideas.jsonl",
    "failure_case": "failure_cases.jsonl",
    "reusable_artifact": "reusable_artifacts.jsonl",
}


class ExperienceStore:
    """保存和检索共享经验记录。"""
    def __init__(
        self,
        workspace: str | Path,
        *,
        source_roots: list[str | Path] | None = None,
    ):
        """初始化对象并保存必要配置。"""
        self.root = Path(workspace) / "shared_experience_pool"
        self.root.mkdir(parents=True, exist_ok=True)
        self.source_roots = [
            Path(source).expanduser().resolve()
            for source in (source_roots or [])
            if Path(source).expanduser().resolve() != self.root.resolve()
        ]
        for filename in set(_TYPE_FILE.values()):
            (self.root / filename).touch(exist_ok=True)

    def _path_for(self, record_type: str) -> Path:
        """返回经验记录文件路径。"""
        return self.root / _TYPE_FILE.get(record_type, "attempted_ideas.jsonl")

    def upsert(self, record: dict[str, Any]) -> str:
        """新增或更新经验记录。"""
        rec = dict(record)
        rec.setdefault("id", new_id("exp"))
        rec.setdefault("type", "attempted_idea")
        rec.setdefault("created_at", now_ms())
        append_jsonl(self._path_for(str(rec["type"])), rec)
        return str(rec["id"])

    def all_records(self) -> list[dict[str, Any]]:
        """读取全部经验记录。"""
        rows = []
        seen: set[str] = set()
        for source_index, root in enumerate([self.root, *self.source_roots]):
            if not root.is_dir():
                continue
            for p in sorted(root.glob("*.jsonl")):
                for record in read_jsonl(p):
                    record_id = str(record.get("id") or "")
                    dedupe_key = record_id or f"{source_index}:{p}:{len(rows)}"
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    if source_index:
                        record = dict(record)
                        record.setdefault("source_pool", str(root))
                    rows.append(record)
        return rows

    def search(self, query: str, filters: dict | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        """检索共享经验记录。"""
        filters = filters or {}
        terms = {t.lower() for t in query.replace("/", " ").replace("_", " ").split() if len(t) > 2}
        scored = []
        for rec in self.all_records():
            if filters.get("type") and rec.get("type") != filters["type"]:
                continue
            text = json.dumps(rec, ensure_ascii=False).lower()
            score = sum(1 for t in terms if t in text)
            if score or not terms:
                scored.append((score, rec))
        scored.sort(key=lambda x: (-x[0], str(x[1].get("created_at", ""))))
        return [r for _, r in scored[:top_k]]
