"""端到端运行的证据与产物存储。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..utils import append_jsonl, atomic_write_json, new_id, now_ms, safe_name, sha256_file


_KIND_DIR = {
    "idea": "ideas",
    "idea_review": "reviews",
    "method_spec": "method_specs",
    "branch": "code_patches",
    "code_patch": "code_patches",
    "public_eval": "evaluator_scores",
    "official_eval": "evaluator_scores",
    "evaluator_agent_view": "evaluator_scores",
    "artifact_validation": "validation_reports",
    "analysis_report": "analysis_reports",
    "deep_analysis": "analysis_reports",
    "worker_call": "worker_calls",
    "decision": "decisions",
}


class ArtifactStore:
    """保存证据、产物与决策记录。"""
    def __init__(self, workspace: str | Path):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)
        self.root = self.workspace / "artifacts"
        self.index_path = self.root / "artifact_index.jsonl"
        self.decision_path = self.root / "decision_log.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir_for(self, kind: str) -> Path:
        """返回指定证据类型的存储目录。"""
        d = self.root / _KIND_DIR.get(kind, safe_name(kind))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _record(self, *, artifact_id: str, kind: str, path: Path, refs: list[str] | None, meta: dict | None) -> str:
        """登记证据索引记录。"""
        rec = {
            "id": artifact_id,
            "type": kind,
            "path": str(path.relative_to(self.workspace)),
            "checksum": sha256_file(path) if path.exists() and path.is_file() else None,
            "created_at": now_ms(),
            "input_refs": refs or [],
            "metadata": meta or {},
        }
        append_jsonl(self.index_path, rec)
        return artifact_id

    def save_json(self, kind: str, obj: dict[str, Any], *, refs: list[str] | None = None, meta: dict | None = None) -> str:
        """保存结构化证据。"""
        artifact_id = str(obj.get("id") or new_id(kind))
        path = self._dir_for(kind) / f"{safe_name(artifact_id)}.json"
        obj = dict(obj)
        obj.setdefault("id", artifact_id)
        atomic_write_json(path, obj)
        return self._record(artifact_id=artifact_id, kind=kind, path=path, refs=refs, meta=meta)

    def save_text(self, kind: str, text: str, *, refs: list[str] | None = None, meta: dict | None = None, suffix: str = ".md") -> str:
        """保存文本证据。"""
        artifact_id = new_id(kind)
        path = self._dir_for(kind) / f"{safe_name(artifact_id)}{suffix}"
        path.write_text(text, encoding="utf-8")
        return self._record(artifact_id=artifact_id, kind=kind, path=path, refs=refs, meta=meta)

    def save_file(self, kind: str, source: str | Path, *, refs: list[str] | None = None, meta: dict | None = None) -> str:
        """复制并登记文件证据。"""
        src = Path(source)
        artifact_id = new_id(kind)
        path = self._dir_for(kind) / f"{safe_name(artifact_id)}-{safe_name(src.name)}"
        shutil.copyfile(src, path)
        return self._record(artifact_id=artifact_id, kind=kind, path=path, refs=refs, meta=meta)

    def record_decision(self, decision: dict[str, Any], *, refs: list[str] | None = None) -> str:
        """记录一次调度或评审决策。"""
        decision = dict(decision)
        decision.setdefault("id", new_id("decision"))
        decision.setdefault("created_at", now_ms())
        decision.setdefault("evidence_refs", refs or decision.get("evidence_refs") or [])
        artifact_id = self.save_json("decision", decision, refs=refs)
        append_jsonl(self.decision_path, decision)
        return artifact_id
