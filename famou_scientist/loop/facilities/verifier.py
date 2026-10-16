"""Validity Verifier 的可注入 contract 和 verdict 校验。"""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class ValidityVerifier(Protocol):
    """检查候选是否符合公开任务约束的可注入 verifier。"""

    def verify_candidate(
        self,
        candidate: Mapping[str, Any],
        *,
        context: Mapping[str, Any],
        session_key: str,
        resume: bool,
    ) -> Mapping[str, Any]:
        """返回只包含 valid/invalid 的结构化 verdict。"""


def validate_validity_verdict(value: Mapping[str, Any]) -> dict[str, Any]:
    """严格校验 VerifierAgent verdict，避免把自然语言错误当成 invalid。"""

    if not isinstance(value, Mapping):
        raise ValueError("validity verdict 必须是 JSON object")
    status = value.get("status")
    if status not in {"valid", "invalid"}:
        raise ValueError("validity verdict.status 必须是 valid 或 invalid")
    reasons = value.get("reasons", [])
    if isinstance(reasons, str):
        reasons = [reasons]
    if not isinstance(reasons, list) or not all(
        isinstance(item, str) and item.strip() for item in reasons
    ):
        raise ValueError("validity verdict.reasons 必须是非空字符串列表")
    evidence_refs = value.get("evidence_refs", [])
    if isinstance(evidence_refs, str):
        evidence_refs = [evidence_refs]
    if not isinstance(evidence_refs, list) or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise ValueError("validity verdict.evidence_refs 必须是字符串列表")
    violations = value.get("violations", [])
    if not isinstance(violations, list):
        raise ValueError("validity verdict.violations 必须是列表")
    normalized_violations: list[dict[str, Any]] = []
    for item in violations:
        if not isinstance(item, Mapping):
            raise ValueError("validity verdict.violations 的元素必须是 object")
        normalized = {
            "rule": str(item.get("rule") or "").strip(),
            "evidence": str(item.get("evidence") or "").strip(),
            "evidence_refs": item.get("evidence_refs", []),
        }
        if not normalized["rule"] or not normalized["evidence"]:
            raise ValueError("每个 violation 必须包含 rule 和 evidence")
        refs = normalized["evidence_refs"]
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list) or not all(
            isinstance(ref, str) and ref.strip() for ref in refs
        ):
            raise ValueError("violation.evidence_refs 必须是字符串列表")
        normalized["evidence_refs"] = list(refs)
        normalized_violations.append(normalized)
    if status == "invalid" and not reasons:
        raise ValueError("invalid verdict 必须提供至少一个 reason")
    if status == "invalid" and not evidence_refs:
        raise ValueError("invalid verdict 必须提供至少一个 evidence_ref")
    return {
        "status": status,
        "reasons": list(reasons),
        "evidence_refs": list(evidence_refs),
        "violations": normalized_violations,
    }


__all__ = ["ValidityVerifier", "validate_validity_verdict"]
