"""基于文件的端到端任务队列。"""
from __future__ import annotations

import itertools
import threading
from pathlib import Path
from typing import Any

from ..utils import append_jsonl, atomic_write_json, new_id, now_ms, read_json
from ..domain.status import LoopStatus


class JsonlQueue:
    """提供基于文件的轻量任务队列。"""
    #: 消费顺序。weighted = 先按 priority 降序、同级 FIFO；equal = 纯 FIFO。
    ORDERINGS = frozenset({"weighted", "equal"})

    def __init__(
        self,
        workspace: str | Path,
        name: str,
        *,
        ordering: str = "weighted",
    ):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)
        self.name = name
        ordering = str(ordering or "weighted").strip().lower()
        if ordering not in self.ORDERINGS:
            raise ValueError(
                f"unsupported queue ordering: {ordering!r}; "
                f"expected one of {', '.join(sorted(self.ORDERINGS))}"
            )
        self.ordering = ordering
        # created_at 只有毫秒精度，同一 tick 内连续 push 会拿到相同时间戳，
        # 而条目文件名带随机后缀，仅按 (priority, created_at) 排序时同级顺序
        # 不确定。seq 是进程内单调序号，用作最后一级 tie-break，使同优先级
        # 真正 FIFO（跨进程仍回退到 created_at）。
        self._seq = itertools.count()
        self._seq_lock = threading.Lock()
        self.dir = self.workspace / "queues"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{name}.jsonl"
        self.items_dir = self.dir / f"{name}_items"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "queue_events.jsonl"
        # 主 JSONL 只记录队列事件，当前状态以 items_dir 下每个 item 的快照为准。
        # 这样更新状态不需要重写不断增长的事件日志。
        self.path.touch(exist_ok=True)

    def _next_seq(self) -> int:
        """返回进程内单调递增的入队序号。"""
        with self._seq_lock:
            return next(self._seq)

    def _item_path(self, item_id: str) -> Path:
        """返回队列条目文件路径。"""
        return self.items_dir / f"{item_id}.json"

    def _write_item(self, item: dict[str, Any]) -> None:
        """写入队列条目文件。"""
        # atomic_write_json 使用临时文件替换，进程中断时不会留下半截 JSON。
        atomic_write_json(self._item_path(item["id"]), item)

    def _event(self, event: str, item: dict[str, Any]) -> None:
        """记录队列事件。"""
        append_jsonl(self.events_path, {"ts": now_ms(), "queue": self.name, "event": event, "item_id": item.get("id"), "status": item.get("status")})

    def push(self, payload: dict[str, Any], *, item_type: str, priority: int = 0, evidence_refs: list[str] | None = None) -> dict[str, Any]:
        """向队列追加待处理条目。"""
        # payload 保存业务对象；input/output/evidence refs 单独维护证据关系，避免
        # worker 直接修改调度元数据。
        item = {
            "id": new_id(f"{self.name}_item"),
            "type": item_type,
            "status": LoopStatus.Queue.QUEUED,
            "priority": priority,
            "seq": self._next_seq(),
            "created_at": now_ms(),
            "updated_at": now_ms(),
            "payload": payload,
            "input_refs": evidence_refs or [],
            "output_refs": [],
            "evidence_refs": evidence_refs or [],
            "retry_count": 0,
        }
        self._write_item(item)
        # push 日志用于审计完整历史，item 快照用于高效读取当前状态。
        append_jsonl(self.path, {"ts": now_ms(), "item_id": item["id"], "event": "push"})
        self._event("push", item)
        return item

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        """列出队列条目。"""
        items = []
        for p in sorted(self.items_dir.glob("*.json")):
            item = read_json(p)
            if not isinstance(item, dict):
                continue
            if status is None or item.get("status") == status:
                items.append(item)
        def _fifo(item: dict[str, Any]) -> tuple[int, int, str]:
            return (
                int(item.get("created_at") or 0),
                int(item.get("seq") if item.get("seq") is not None else 1 << 30),
                str(item.get("id") or ""),
            )

        if self.ordering == "equal":
            # 纯 FIFO：priority 仍然记录在条目上，但不参与消费顺序，
            # 用于对照实验时把"插队"这一项单独关掉。
            items.sort(key=_fifo)
        else:
            # 先按优先级降序，再按 FIFO，保证同优先级严格先进先出。
            items.sort(key=lambda x: (-int(x.get("priority") or 0), *_fifo(x)))
        return items

    def size(self, status: str | None = None) -> int:
        """统计队列条目数量。"""
        return len(self.list(status=status))

    def get(self, item_id: str) -> dict[str, Any]:
        """按 ID 读取最新队列条目。"""

        item = read_json(self._item_path(str(item_id)))
        if not isinstance(item, dict):
            raise FileNotFoundError(f"queue item not found: {item_id}")
        return item

    def has_queued(self) -> bool:
        """判断队列中是否存在待处理条目。"""
        return any(
            self.size(status) > 0
            for status in (
                LoopStatus.Queue.QUEUED,
                LoopStatus.Queue.LEASED,
                LoopStatus.Queue.WAITING_RESOURCES,
            )
        )

    def claim(self, item: dict[str, Any]) -> dict[str, Any]:
        """领取指定的排队或资源等待条目并标记为运行中。"""

        current = read_json(self._item_path(str(item.get("id") or "")))
        if not isinstance(current, dict):
            raise FileNotFoundError(f"queue item not found: {item.get('id')}")
        if current.get("status") not in {
            LoopStatus.Queue.QUEUED,
            LoopStatus.Queue.WAITING_RESOURCES,
        }:
            raise ValueError(
                f"queue item is not claimable: {current.get('status')!r}"
            )
        current["status"] = LoopStatus.Queue.RUNNING
        current["updated_at"] = now_ms()
        current.pop("resource_wait", None)
        self._write_item(current)
        self._event("claim", current)
        return current

    def lease(
        self,
        item: dict[str, Any] | str,
        *,
        owner_id: str,
        purpose: str,
    ) -> dict[str, Any]:
        """临时租用一个排队条目，但不把它计为正在实现。"""

        item_id = item if isinstance(item, str) else item.get("id")
        current = self.get(str(item_id or ""))
        if current.get("status") != LoopStatus.Queue.QUEUED:
            raise ValueError(
                f"queue item is not leasable: {current.get('status')!r}"
            )
        leased_at = now_ms()
        current["status"] = LoopStatus.Queue.LEASED
        current["lease"] = {
            "owner_id": str(owner_id),
            "purpose": str(purpose),
            "leased_at": leased_at,
        }
        current["updated_at"] = leased_at
        self._write_item(current)
        self._event("lease", current)
        return current

    def replay_tail(
        self,
        item: dict[str, Any],
        *,
        owner_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """释放租约并把原条目重放到同优先级队尾。"""

        current = self.get(str(item.get("id") or ""))
        lease = current.get("lease") if isinstance(current.get("lease"), dict) else {}
        if current.get("status") != LoopStatus.Queue.LEASED:
            raise ValueError(
                f"queue item is not leased: {current.get('status')!r}"
            )
        if str(lease.get("owner_id") or "") != str(owner_id):
            raise ValueError("queue lease owner mismatch")
        # created_at 是同优先级 FIFO 的排序键。重放时移动到当前所有条目的末尾，
        # 但保留原 item_id、payload 和证据链，避免制造一条重复 Idea。
        queued = self.list(LoopStatus.Queue.QUEUED)
        tail = max(
            [int(value.get("created_at") or 0) for value in self.list()] or [0]
        )
        replayed_at = max(now_ms(), tail + 1)
        previous_priority = int(current.get("priority") or 0)
        if queued:
            current["priority"] = min(
                int(value.get("priority") or 0) for value in queued
            )
        current["status"] = LoopStatus.Queue.QUEUED
        current["created_at"] = replayed_at
        current["updated_at"] = replayed_at
        current["offer_count"] = int(current.get("offer_count") or 0) + 1
        current["last_replayed_at"] = replayed_at
        current["last_defer_reason"] = str(reason)
        current["last_replay_previous_priority"] = previous_priority
        current.pop("lease", None)
        self._write_item(current)
        self._event("replay_tail", current)
        return current

    def finish_lease(
        self,
        item: dict[str, Any],
        *,
        owner_id: str,
        resolution: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """消费已租用条目，并记录 switch/fuse 的决策证据。"""

        current = self.get(str(item.get("id") or ""))
        lease = current.get("lease") if isinstance(current.get("lease"), dict) else {}
        if current.get("status") != LoopStatus.Queue.LEASED:
            raise ValueError(
                f"queue item is not leased: {current.get('status')!r}"
            )
        if str(lease.get("owner_id") or "") != str(owner_id):
            raise ValueError("queue lease owner mismatch")
        current["status"] = LoopStatus.Queue.FINISHED
        current["lease_resolution"] = str(resolution)
        current["lease_finished_at"] = now_ms()
        current["updated_at"] = current["lease_finished_at"]
        current.pop("lease", None)
        if evidence_refs:
            current.setdefault("evidence_refs", []).extend(evidence_refs)
        self._write_item(current)
        self._event("finish_lease", current)
        return current

    def pop(self) -> dict[str, Any] | None:
        """取出一个待处理条目并标记运行中。"""
        queued = self.list(status=LoopStatus.Queue.QUEUED)
        if not queued:
            return None
        # 先持久化 running，再把 item 返回给调用方。即使随后进程崩溃，重启时也能
        # 识别这是一个中断任务，而不是误认为从未领取。
        item = self.claim(queued[0])
        self._event("pop", item)
        return item

    def recover_running(self) -> list[dict[str, Any]]:
        """恢复被中断的运行中条目。"""
        recovered: list[dict[str, Any]] = []
        # workspace lock 保证恢复期间没有另一个调度器仍在执行这些 running 条目。
        for status in (LoopStatus.Queue.RUNNING, LoopStatus.Queue.LEASED):
            for item in self.list(status=status):
                item["status"] = LoopStatus.Queue.QUEUED
                item["updated_at"] = now_ms()
                item["recovery_count"] = int(item.get("recovery_count") or 0) + 1
                item["last_recovered_at"] = item["updated_at"]
                item.pop("lease", None)
                self._write_item(item)
                self._event("recover", item)
                recovered.append(item)
        return recovered

    def wait_for_resources(
        self,
        item: dict[str, Any],
        *,
        request: dict[str, Any],
        broker_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """把暂时无法装箱的条目标记为资源等待并保留诊断。"""

        previous_wait = (
            item.get("resource_wait")
            if isinstance(item.get("resource_wait"), dict)
            else {}
        )
        checked_at = now_ms()
        # 调度器会高频尝试重新装箱；资源快照没有变化时，无需每个 tick 都追加
        # waiting_resources 事件。领取逻辑仍照常执行，因此不会延迟资源释放后的派发。
        if (
            item.get("status") == LoopStatus.Queue.WAITING_RESOURCES
            and previous_wait.get("request") == request
            and previous_wait.get("broker") == broker_snapshot
            and checked_at - int(previous_wait.get("last_checked_at") or 0) < 30_000
        ):
            return item
        first_waiting_at = previous_wait.get("first_waiting_at")
        item["status"] = LoopStatus.Queue.WAITING_RESOURCES
        item["resource_wait"] = {
            "first_waiting_at": first_waiting_at or checked_at,
            "last_checked_at": checked_at,
            "request": request,
            "broker": broker_snapshot,
        }
        item["updated_at"] = checked_at
        self._write_item(item)
        self._event("waiting_resources", item)
        return item

    def update(self, item: dict[str, Any], *, status: str | None = None, output_refs: list[str] | None = None, evidence_refs: list[str] | None = None) -> dict[str, Any]:
        """更新队列条目状态。"""
        if status:
            item["status"] = status
        if output_refs:
            item.setdefault("output_refs", []).extend(output_refs)
        if evidence_refs:
            # 保留累计证据链，不用最新阶段的引用覆盖 Idea/实现阶段已有引用。
            item.setdefault("evidence_refs", []).extend(evidence_refs)
        item["updated_at"] = now_ms()
        self._write_item(item)
        self._event("update", item)
        return item

    def archive_queued(self, *, reason: str) -> list[dict[str, Any]]:
        """归档尚未启动的条目，并保留其原始任务内容。"""
        archived: list[dict[str, Any]] = []
        # waiting_resources 仍然是“尚未启动”的任务。用户停止 Loop 时必须和
        # queued 一起归档，否则它会作为非终态条目残留并在恢复后意外执行。
        for status in (
            LoopStatus.Queue.QUEUED,
            LoopStatus.Queue.LEASED,
            LoopStatus.Queue.WAITING_RESOURCES,
        ):
            for item in self.list(status=status):
                item["status"] = LoopStatus.Queue.ARCHIVED
                item["archive_reason"] = reason
                item["updated_at"] = now_ms()
                self._write_item(item)
                self._event("archive", item)
                archived.append(item)
        return archived

    def cancel_unfinished(self, *, reason: str) -> list[dict[str, Any]]:
        """终止尚未完成的条目，并保留输入和取消原因。"""

        cancelled: list[dict[str, Any]] = []
        for status in (
            LoopStatus.Queue.QUEUED,
            LoopStatus.Queue.LEASED,
            LoopStatus.Queue.WAITING_RESOURCES,
            LoopStatus.Queue.RUNNING,
        ):
            for item in self.list(status=status):
                item["status"] = LoopStatus.Queue.CANCELLED
                item["cancel_reason"] = reason
                item["updated_at"] = now_ms()
                self._write_item(item)
                self._event("cancel", item)
                cancelled.append(item)
        return cancelled

    def mark_not_executed(
        self,
        *,
        reason: str,
        include_running: bool = False,
    ) -> list[dict[str, Any]]:
        """将截止时不会再执行的条目标为未执行，并保留完整输入。"""

        # 资源等待条目尚未真正执行，但已经进入调度队列；墙钟截止时应明确
        # 标记 not_executed，而不是让它无限停留在 waiting_resources。
        statuses = [
            LoopStatus.Queue.QUEUED,
            LoopStatus.Queue.LEASED,
            LoopStatus.Queue.WAITING_RESOURCES,
        ]
        if include_running:
            statuses.append(LoopStatus.Queue.RUNNING)
        marked: list[dict[str, Any]] = []
        for status in statuses:
            for item in self.list(status=status):
                item["status"] = LoopStatus.Queue.NOT_EXECUTED
                item["not_executed_reason"] = reason
                item["updated_at"] = now_ms()
                self._write_item(item)
                self._event("not_executed", item)
                marked.append(item)
        return marked

    def requeue_for_resume(self, *, reason_prefix: str) -> list[dict[str, Any]]:
        """Requeue deadline-cancelled work for an explicit task resume."""
        resumed: list[dict[str, Any]] = []
        for item in self.list(status=LoopStatus.Queue.NOT_EXECUTED):
            reason = str(item.get("not_executed_reason") or "")
            if not reason.startswith(reason_prefix):
                continue
            item["status"] = LoopStatus.Queue.QUEUED
            item["updated_at"] = now_ms()
            item["resume_count"] = int(item.get("resume_count") or 0) + 1
            item["last_resumed_at"] = item["updated_at"]
            item["last_resume_reason"] = reason
            self._write_item(item)
            self._event("resume", item)
            resumed.append(item)
        return resumed


class QueueSet:
    """聚合端到端循环使用的多个队列。"""
    def __init__(self, workspace: str | Path, *, ordering: str = "weighted"):
        """初始化对象并保存必要配置。"""
        # benchmark-managed 使用 benchmark_attempt；开放科研使用 ideaspark；两者
        # 后续共享 experiment。analyze 只服务开放科研的深度分析阶段。
        # ordering 只作用于待实现队列：评测队列按提交先后消费，不参与优先级实验。
        self.ideaspark = JsonlQueue(workspace, "ideaspark", ordering=ordering)
        self.benchmark_attempt = JsonlQueue(
            workspace, "benchmark_attempt_queue", ordering=ordering
        )
        self.evaluation = JsonlQueue(workspace, "evaluation_queue")
        self.analyze = JsonlQueue(workspace, "analyze_spark")

    def summary(self) -> dict[str, dict[str, int]]:
        """汇总队列状态。"""
        out = {}
        for name, q in [
            ("ideaspark", self.ideaspark),
            ("benchmark_attempt_queue", self.benchmark_attempt),
            ("evaluation_queue", self.evaluation),
            ("analyze_spark", self.analyze),
        ]:
            out[name] = {status.value: q.size(status) for status in LoopStatus.Queue}
        return out

    def recover_running(self) -> dict[str, list[dict[str, Any]]]:
        """恢复被中断的运行中条目。"""
        return {
            "ideaspark": self.ideaspark.recover_running(),
            "benchmark_attempt_queue": self.benchmark_attempt.recover_running(),
            "evaluation_queue": self.evaluation.recover_running(),
            "analyze_spark": self.analyze.recover_running(),
        }

    def requeue_for_resume(self, *, reason_prefix: str) -> dict[str, list[dict[str, Any]]]:
        """Requeue work explicitly cancelled by a resumable task boundary."""
        return {
            "ideaspark": self.ideaspark.requeue_for_resume(reason_prefix=reason_prefix),
            "benchmark_attempt_queue": self.benchmark_attempt.requeue_for_resume(
                reason_prefix=reason_prefix
            ),
            "evaluation_queue": self.evaluation.requeue_for_resume(
                reason_prefix=reason_prefix
            ),
            "analyze_spark": self.analyze.requeue_for_resume(
                reason_prefix=reason_prefix
            ),
        }

    def archive_queued(self, *, reason: str) -> dict[str, list[dict[str, Any]]]:
        """归档所有队列中尚未启动的条目。"""
        return {
            "ideaspark": self.ideaspark.archive_queued(reason=reason),
            "benchmark_attempt_queue": self.benchmark_attempt.archive_queued(reason=reason),
            "evaluation_queue": self.evaluation.archive_queued(reason=reason),
            "analyze_spark": self.analyze.archive_queued(reason=reason),
        }

    def cancel_unfinished(self, *, reason: str) -> dict[str, list[dict[str, Any]]]:
        """取消整个任务图中所有尚未完成的队列条目。"""

        return {
            "ideaspark": self.ideaspark.cancel_unfinished(reason=reason),
            "benchmark_attempt_queue": self.benchmark_attempt.cancel_unfinished(
                reason=reason
            ),
            "evaluation_queue": self.evaluation.cancel_unfinished(reason=reason),
            "analyze_spark": self.analyze.cancel_unfinished(reason=reason),
        }
