"""独立于 Controller 的 New Idea 与 Improve 配对策略。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..domain.status import LoopStatus


class SearchQueue(Protocol):
    """定义 Search Policy 使用的最小持久化队列端口。"""

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        """列出指定状态的条目。"""

    def lease(
        self,
        item: dict[str, Any],
        *,
        owner_id: str,
        purpose: str,
    ) -> dict[str, Any]:
        """临时租用一个 New Idea。"""

    def get(self, item_id: str) -> dict[str, Any]:
        """读取队列条目最新快照。"""

    def update(self, item: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """更新主派发条目。"""

    def replay_tail(
        self,
        item: dict[str, Any],
        *,
        owner_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """将未采用 Idea 重放到队尾。"""

    def finish_lease(
        self,
        item: dict[str, Any],
        *,
        owner_id: str,
        resolution: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """消费被 switch/fuse 采用的 Idea。"""


@dataclass(frozen=True)
class SearchSettlement:
    """描述一次 Improve 配对的最终队列处理结果。"""

    decision: dict[str, Any] | None
    offered_item_id: str | None = None
    replayed: bool = False
    consumed: bool = False
    ignored: bool = False


class SearchPolicy(Protocol):
    """定义可注入 Controller 的搜索策略接口。"""

    def prepare_dispatch(
        self,
        item: dict[str, Any],
        queue: SearchQueue,
    ) -> dict[str, Any]:
        """在 Implement 派发前选择并租用可选 Idea。"""

    def normalize_decision(
        self,
        item: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """把 Agent 选择转换为稳定的策略决策。"""

    def settle(
        self,
        item: dict[str, Any],
        result: Mapping[str, Any],
        queue: SearchQueue,
        *,
        evidence_refs: list[str] | None = None,
    ) -> SearchSettlement:
        """消费或重放临时租用的 Idea。"""


class PairwiseImproveSearchPolicy:
    """在 Improve 回合同时提供当前 Refine 和一条 New Idea。"""

    _NEW_ITEM_TYPES = frozenset({"idea", "benchmark_attempt"})
    _ACTIONS = frozenset({"refine", "switch", "fuse"})

    def __init__(self, *, enabled: bool = False):
        """保存开关；关闭时保持原有单 Idea 派发行为。"""

        self.enabled = bool(enabled)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PairwiseImproveSearchPolicy":
        """从独立配置段创建策略。"""

        config = value if isinstance(value, Mapping) else {}
        return cls(enabled=config.get("enabled") is True)

    @staticmethod
    def _is_improve(item: Mapping[str, Any]) -> bool:
        """只有获得有效评测反馈的 continuation 才参与配对。"""

        payload = item.get("payload")
        return (
            item.get("type") == "actor_continuation"
            and isinstance(payload, Mapping)
            and payload.get("continuation_reason") == "evaluated"
        )

    @classmethod
    def _eligible_new_items(
        cls,
        queue: SearchQueue,
    ) -> list[dict[str, Any]]:
        """返回尚未实现、未被其他 Improve 回合租用的 New Idea。"""

        return [
            item
            for item in queue.list(LoopStatus.Queue.QUEUED)
            if item.get("type") in cls._NEW_ITEM_TYPES
            and not (item.get("payload") or {}).get("continuation_reason")
        ]

    def prepare_dispatch(
        self,
        item: dict[str, Any],
        queue: SearchQueue,
    ) -> dict[str, Any]:
        """为 Improve 回合租用队首 New Idea，并把完整 Idea 交给 Agent。"""

        if not self.enabled or not self._is_improve(item):
            return item
        candidates = self._eligible_new_items(queue)
        if not candidates:
            return item
        leased = queue.lease(
            candidates[0],
            owner_id=str(item.get("id") or ""),
            purpose="improve_choice",
        )
        payload = dict(item.get("payload") or {})
        # 两侧必须信息对等：offered_idea 是完整 payload，current_idea 若只给
        # 摘要，Agent 无法"比较二者上限"。除同样的方案描述外，再附上本方案
        # 已有的实测结果——这是 offered_idea 尚不具备、而当前方案独有的证据。
        diagnostics = payload.get("refine_diagnostics") or {}
        current_idea = {
            key: payload.get(key)
            for key in (
                "id",
                "title",
                "hypothesis",
                "method",
                "mechanism",
                "rationale",
                "implementation_plan",
                "risks",
                "expected_return",
                "resource_request",
            )
            if payload.get(key) is not None
        }
        current_idea["revision"] = payload.get("revision")
        for key in ("current_score", "current_level", "current_is_run_best"):
            if diagnostics.get(key) is not None:
                current_idea[key] = diagnostics[key]
        if diagnostics.get("last_run"):
            current_idea["last_run"] = diagnostics["last_run"]
        payload["search_opportunity"] = {
            "schema_version": 1,
            "mode": "refine_or_new_idea",
            "current_idea": current_idea,
            "offered_idea": dict(leased.get("payload") or {}),
            "offered_queue_item_id": leased.get("id"),
            "allowed_actions": ["refine", "switch", "fuse"],
            "refine_replays_offered_idea_to_tail": True,
            # 量化处境由 Controller 计算后随 continuation 一同下发；策略层只做
            # 透传，不重新解释指标语义。
            "diagnostics": diagnostics or None,
        }
        item["payload"] = payload
        queue.update(item)
        return item

    def normalize_decision(
        self,
        item: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """校验 Agent 选择；非标准 Adapter 缺失时安全回退为 Refine。"""

        payload = item.get("payload")
        opportunity = (
            payload.get("search_opportunity")
            if isinstance(payload, Mapping)
            else None
        )
        if not isinstance(opportunity, Mapping):
            return None
        current = opportunity.get("current_idea")
        offered = opportunity.get("offered_idea")
        current_id = str(current.get("id") or "") if isinstance(current, Mapping) else ""
        offered_id = str(offered.get("id") or "") if isinstance(offered, Mapping) else ""
        raw = result.get("search_decision")
        action = str(raw.get("action") or "") if isinstance(raw, Mapping) else ""
        reason = str(raw.get("reason") or "").strip() if isinstance(raw, Mapping) else ""
        declared_offered = (
            str(raw.get("offered_idea_id") or "")
            if isinstance(raw, Mapping)
            else ""
        )
        valid = (
            action in self._ACTIONS
            and bool(reason)
            and (not declared_offered or declared_offered == offered_id)
        )
        if not valid:
            action = "refine"
            reason = "Agent Adapter 未返回合法选择；为避免误消费 New Idea，安全回退 Refine。"
            source = "controller_fallback"
        else:
            source = "agent"
        lineage_idea_ids = (
            [offered_id]
            if action == "switch"
            else [current_id, offered_id]
            if action == "fuse"
            else [current_id]
        )
        return {
            "action": action,
            "reason": reason,
            "source": source,
            "current_idea_id": current_id,
            "offered_idea_id": offered_id,
            "offered_queue_item_id": opportunity.get("offered_queue_item_id"),
            "lineage_idea_ids": [value for value in lineage_idea_ids if value],
        }

    def settle(
        self,
        item: dict[str, Any],
        result: Mapping[str, Any],
        queue: SearchQueue,
        *,
        evidence_refs: list[str] | None = None,
    ) -> SearchSettlement:
        """Refine 时队尾重放；Switch/Fuse 时正式消费租用 Idea。"""

        decision = self.normalize_decision(item, result)
        if decision is None:
            return SearchSettlement(decision=None, ignored=True)
        offered_item_id = str(decision.get("offered_queue_item_id") or "")
        try:
            offered = queue.get(offered_item_id)
        except FileNotFoundError:
            return SearchSettlement(
                decision=decision,
                offered_item_id=offered_item_id,
                ignored=True,
            )
        lease = offered.get("lease") if isinstance(offered.get("lease"), dict) else {}
        owner_id = str(item.get("id") or "")
        if (
            offered.get("status") != LoopStatus.Queue.LEASED
            or str(lease.get("owner_id") or "") != owner_id
        ):
            return SearchSettlement(
                decision=decision,
                offered_item_id=offered_item_id,
                ignored=True,
            )
        if decision["action"] == "refine":
            queue.replay_tail(
                offered,
                owner_id=owner_id,
                reason=str(decision.get("reason") or "refine_selected"),
            )
            return SearchSettlement(
                decision=decision,
                offered_item_id=offered_item_id,
                replayed=True,
            )
        queue.finish_lease(
            offered,
            owner_id=owner_id,
            resolution=str(decision["action"]),
            evidence_refs=evidence_refs,
        )
        return SearchSettlement(
            decision=decision,
            offered_item_id=offered_item_id,
            consumed=True,
        )


def search_policy_from_mapping(
    value: Mapping[str, Any] | None,
) -> SearchPolicy:
    """根据配置创建搜索策略，避免 Controller 依赖具体策略实现。"""

    config = value if isinstance(value, Mapping) else {}
    policy_type = str(config.get("type") or "pairwise_improve")
    if policy_type == "pairwise_improve":
        return PairwiseImproveSearchPolicy.from_mapping(config)
    raise ValueError(f"不支持的 Search Policy: {policy_type}")


__all__ = [
    "PairwiseImproveSearchPolicy",
    "SearchPolicy",
    "SearchSettlement",
    "search_policy_from_mapping",
]
