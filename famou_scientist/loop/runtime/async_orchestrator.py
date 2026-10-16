"""端到端科研循环的异步生产者消费者调度器。"""
from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
import time
from typing import Any

from ..domain.resources import ResourceRequest
from ..domain.status import LoopStatus
from ..utils import atomic_write_json, now_ms
from .orchestrator import Orchestrator
from ..storage.workspace import WorkspaceRunLock


class AsyncOrchestrator(Orchestrator):
    """以生产者消费者方式运行端到端循环。"""

    @staticmethod
    def _is_wall_time_drain(state: dict[str, Any]) -> bool:
        """判断当前是否处于研究截止后的评测排空阶段。"""

        research = state.get("research_state", {})
        return (
            research.get("status") == LoopStatus.Research.STOPPED
            and research.get("termination_reason") == "wall_time_budget_exhausted"
        )

    @staticmethod
    def _is_master_stop(state: dict[str, Any]) -> bool:
        """判断是否为控制面终止，而不是可恢复的墙钟截止。"""

        research = state.get("research_state", {})
        return (
            research.get("status") == LoopStatus.Research.STOPPED
            and research.get("termination_reason") != "wall_time_budget_exhausted"
        )

    def _begin_wall_time_drain(
        self,
        state: dict[str, Any],
        pending_ideas: dict[Future, dict[str, Any]],
        pending_implementations: dict[Future, dict[str, Any]],
    ) -> None:
        """截止 Idea/Implement，并冻结需要继续排空的 Evaluation Queue。"""

        reason = "research_wall_time_budget_exhausted"
        cancel_path = self._research_deadline_path()
        atomic_write_json(
            cancel_path,
            {
                "reason": reason,
                "created_at": now_ms(),
            },
        )

        # 先标记内存中的 running item，使 Future 返回时不会被当作工程失败或
        # 继续送入评测池；取消文件会让 CLI wrapper 终止对应进程组。
        implementation_queue = self._implementation_queue()
        not_executed = list(pending_implementations.values())
        for future, item in list(pending_implementations.items()):
            item["not_executed_reason"] = reason
            implementation_queue.update(
                item,
                status=LoopStatus.Queue.NOT_EXECUTED,
            )
            future.cancel()
        not_executed.extend(
            implementation_queue.mark_not_executed(
                reason=reason,
                include_running=True,
            )
        )
        for future in pending_ideas:
            future.cancel()

        # 截止快照只冻结“已经进入 Evaluation Queue”的集合。之后 Implement
        # 结果即使迟到也不会再扩充该集合，排空阶段只消费这些 ID。
        evaluation_items = [
            *self.queues.evaluation.list(LoopStatus.Queue.QUEUED),
            *self.queues.evaluation.list(LoopStatus.Queue.WAITING_RESOURCES),
            *self.queues.evaluation.list(LoopStatus.Queue.RUNNING),
        ]
        research = state.setdefault("research_state", {})
        research.setdefault("shutdown", {}).update({
            "phase": "draining_evaluations",
            "research_finished_at": now_ms(),
            "agent_cancel_file": str(cancel_path),
            "evaluation_item_ids_at_cutoff": [
                str(item.get("id")) for item in evaluation_items
            ],
            "not_executed_item_ids": sorted(
                {
                    str(item.get("id"))
                    for item in not_executed
                    if item.get("id")
                }
            ),
        })
        self._checkpoint(state, "draining_evaluations")
        self.log(
            "research deadline reached; "
            f"drain_evaluations={len(evaluation_items)} "
            f"not_executed={len(not_executed)}"
        )

    def _record_not_executed_implementation(
        self,
        state: dict[str, Any],
        item: dict[str, Any],
        branch: dict[str, Any],
    ) -> None:
        """保存截止后返回的 Agent 证据，但不把它解释成工程失败。"""

        branch_ref = self.artifacts.save_json(
            "branch_not_executed",
            branch,
            refs=item.get("evidence_refs", []),
        )
        attempt_id = str(branch.get("expbank_attempt_id") or "")
        if attempt_id:
            self.expbank.update_attempt(
                attempt_id,
                status=LoopStatus.ExpBank.NOT_EXECUTED,
                implementation=branch,
                conclusion="研究时间截止前未进入评测池，不形成方法或工程结论。",
                next_step="如需继续，应在新的研究运行中恢复该方案。",
                evidence_refs=[branch_ref],
            )
        actor_id = str(branch.get("actor_id") or "")
        if actor_id:
            self.actors.update(
                actor_id,
                status=LoopStatus.Actor.EXHAUSTED,
                termination_reason="research_wall_time_budget_exhausted",
            )
        self._upsert_branch_state(
            state,
            branch,
            LoopStatus.Branch.ARCHIVED,
            evidence_refs=[branch_ref],
        )
        self.artifacts.record_decision(
            {
                "decision": "not_executed_after_research_deadline",
                "branch_id": branch.get("branch_id"),
                "queue_item_id": item.get("id"),
                "reasons": ["candidate was not in evaluation queue at cutoff"],
            },
            refs=[branch_ref],
        )

    def _record_wall_time_drain_progress(
        self,
        state: dict[str, Any],
        pending: dict[Future, dict[str, Any]],
        *,
        force: bool = False,
    ) -> bool:
        """周期记录截止快照的排空状态，避免长任务看起来像调度死锁。"""

        research = state.setdefault("research_state", {})
        shutdown = research.setdefault("shutdown", {})
        recorded_at = now_ms()
        if (
            not force
            and recorded_at - int(shutdown.get("last_drain_progress_at") or 0)
            < 60_000
        ):
            return False
        cutoff_ids = {
            str(item_id)
            for item_id in shutdown.get("evaluation_item_ids_at_cutoff") or []
        }
        status_counts = {status.value: 0 for status in LoopStatus.Queue}
        for item in self.queues.evaluation.list():
            if cutoff_ids and str(item.get("id") or "") not in cutoff_ids:
                continue
            status = str(item.get("status") or "")
            if status in status_counts:
                status_counts[status] += 1
        inflight_ids = [
            str((metadata.get("item") or {}).get("id") or "")
            for metadata in pending.values()
            if not cutoff_ids
            or str((metadata.get("item") or {}).get("id") or "") in cutoff_ids
        ]
        progress = {
            "recorded_at": recorded_at,
            "total_at_cutoff": len(cutoff_ids),
            "queued": status_counts[LoopStatus.Queue.QUEUED.value],
            "waiting_resources": status_counts[
                LoopStatus.Queue.WAITING_RESOURCES.value
            ],
            "running": status_counts[LoopStatus.Queue.RUNNING.value],
            "finished": status_counts[LoopStatus.Queue.FINISHED.value],
            "failed": status_counts[LoopStatus.Queue.FAILED.value],
            "inflight": len(inflight_ids),
            "inflight_item_ids": inflight_ids,
        }
        shutdown["last_drain_progress_at"] = recorded_at
        shutdown["evaluation_drain_progress"] = progress
        self._checkpoint(state, "draining_evaluations")
        self.log(
            "evaluation drain progress "
            f"total={progress['total_at_cutoff']} "
            f"finished={progress['finished']} failed={progress['failed']} "
            f"queued={progress['queued']} "
            f"waiting_resources={progress['waiting_resources']} "
            f"running={progress['running']} inflight={progress['inflight']}"
        )
        return True

    def _submit_benchmark_ideas(
        self,
        state: dict[str, Any],
        executor: ThreadPoolExecutor,
        pending: dict[Future, dict[str, Any]],
    ) -> int:
        """在独立 Idea 线程池中提交有界的 benchmark Idea 请求。"""

        if not self.benchmark_managed:
            return 0
        submitted = 0
        while len(pending) < self.config.max_parallel_ideas:
            request = self._prepare_benchmark_idea_request(
                state,
                reserved=len(pending),
            )
            if request is None:
                break
            future = executor.submit(self._run_benchmark_idea_request, request)
            pending[future] = request
            submitted += 1
        if submitted:
            self._checkpoint(state, "idea_agent")
            self.log(
                "async submitted idea slots="
                f"{submitted}/{self.config.max_parallel_ideas}"
            )
        return submitted

    def _collect_completed_ideas(
        self,
        pending: dict[Future, dict[str, Any]],
    ) -> int:
        """收集后台 Idea 结果，并由主线程写入实现队列。"""

        completed = [
            (future, request)
            for future, request in pending.items()
            if future.done()
        ]
        if not completed:
            return 0

        state = self.state_store.load()
        self._checkpoint(state, "idea_result")
        scheduled = 0
        for future, request in completed:
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - 单次 Idea 失败不能终止流水线
                self.artifacts.save_json(
                    "worker_call",
                    {
                        "task": "benchmark_idea_generator",
                        "valid": False,
                        "error": repr(exc),
                    },
                )
            else:
                terminal = self._control_status() or state.get(
                    "research_state",
                    {},
                ).get("status")
                if terminal not in LoopStatus.RESEARCH_TERMINAL:
                    scheduled += self._enqueue_benchmark_idea_result(state, result)
            pending.pop(future, None)

        self._preserve_external_control(state)
        self._checkpoint(state, "idle")
        self.log(
            "async collected idea results="
            f"{len(completed)} scheduled={scheduled}"
        )
        return len(completed)

    def _claim_idea_items(
        self,
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """从想法队列领取实现任务。"""
        implementation_queue = self._implementation_queue()
        self._maybe_rank_queued_ideas(state)
        # Judge 是同步调度节点；如果它在冲刺阶段用尽最后预算，不再派发新实现。
        if self._wall_time_exhausted(state):
            return []
        # running 数来自持久化队列而不是仅看内存 Future，因此恢复运行后也不会
        # 超过实现并发上限。
        running = implementation_queue.size(LoopStatus.Queue.RUNNING)
        capacity = max(0, self.config.max_parallel_implementations - running)
        evaluation_backlog = self.queues.evaluation.size(
            LoopStatus.Queue.QUEUED
        ) + self.queues.evaluation.size(
            LoopStatus.Queue.WAITING_RESOURCES
        ) + self.queues.evaluation.size(LoopStatus.Queue.RUNNING)
        # Implement 的产出速度受统一 Evaluation 队列容量约束。把仍在运行的
        # Implement 也视为潜在 Candidate，避免慢评测前堆积过多版本。
        capacity = min(
            capacity,
            max(
                0,
                self.config.evaluation_queue_capacity
                - evaluation_backlog
                - running,
            ),
        )
        items: list[dict[str, Any]] = []
        for _ in range(capacity):
            # pop 会先把 queued 持久化为 running，再交给线程池；同一 workspace
            # 只有持锁的调度主线程执行领取，因此不会被两个消费者重复取走。
            item = self._claim_implementation_item()
            if not item:
                break
            items.append(item)
        if items:
            self._checkpoint(state, "implement_agent")
            self.log(
                "async submitted implementation slots="
                f"{len(items)}/{self.config.max_parallel_implementations}"
            )
        return items

    def _claim_evaluation_items(
        self,
        state: dict[str, Any],
        *,
        inflight: int = 0,
    ) -> list[dict[str, Any]]:
        """从统一队列领取运行加评分任务。"""
        capacity = max(
            0,
            self.config.max_parallel_evaluations - int(inflight),
        )
        items: list[dict[str, Any]] = []
        candidates = [
            *self.queues.evaluation.list(LoopStatus.Queue.QUEUED),
            *self.queues.evaluation.list(LoopStatus.Queue.WAITING_RESOURCES),
        ]
        candidates.sort(
            key=lambda item: (
                -int(item.get("priority") or 0),
                int(item.get("created_at") or 0),
            )
        )
        for item in candidates:
            if len(items) >= capacity:
                break
            payload = item.get("payload") or {}
            try:
                request = ResourceRequest.from_mapping(
                    payload.get("resource_request")
                    if isinstance(payload, dict)
                    else None,
                    require_explicit=self.resource_declarations_required,
                )
                lease = self.resource_broker.try_acquire(
                    request,
                    owner_id=str(item.get("id") or "evaluation"),
                )
            except ValueError as exc:
                # 总资源永远无法满足的声明不能无限 hold。仍把条目交给统一结果
                # 路由，使原 ImplementActor 收到可修复的确定性资源诊断。
                claimed = self.queues.evaluation.claim(item)
                claimed_payload = dict(claimed.get("payload") or {})
                claimed_payload["resource_admission_error"] = {
                    "kind": "insufficient_task_resources",
                    "error": str(exc),
                    "request": payload.get("resource_request"),
                    "broker": self.resource_broker.snapshot(),
                }
                claimed["payload"] = claimed_payload
                self.queues.evaluation.update(claimed)
                items.append(claimed)
                continue
            if lease is None:
                self.queues.evaluation.wait_for_resources(
                    item,
                    request=request.to_dict(),
                    broker_snapshot=self.resource_broker.snapshot(),
                )
                candidate_id = str(payload.get("candidate_id") or "")
                if candidate_id:
                    self.candidates.update(
                        candidate_id,
                        status=LoopStatus.Candidate.WAITING_RESOURCES,
                        resource_request=request.to_dict(),
                    )
                self._upsert_branch_state(
                    state,
                    payload,
                    LoopStatus.Branch.WAITING_RESOURCES,
                )
                continue

            claimed = self.queues.evaluation.claim(item)
            claimed_payload = dict(claimed.get("payload") or {})
            claimed_payload["resource_request"] = request.to_dict()
            claimed_payload["resource_lease"] = lease.to_dict()
            claimed["payload"] = claimed_payload
            lease_ref = self.artifacts.save_json(
                "resource_lease",
                {
                    **lease.to_dict(),
                    "broker_after_acquire": self.resource_broker.snapshot(),
                },
            )
            claimed.setdefault("evidence_refs", []).append(lease_ref)
            self.queues.evaluation.update(claimed)
            candidate_id = str(claimed_payload.get("candidate_id") or "")
            if candidate_id:
                self.candidates.update(
                    candidate_id,
                    status=LoopStatus.Candidate.RUNNING,
                    resource_request=request.to_dict(),
                    resource_lease=lease.to_dict(),
                    evidence_refs=[lease_ref],
                )
            items.append(claimed)
            # 分支状态是面向用户的视图，队列 item 才是调度权威；两者在领取时同步。
            self._upsert_branch_state(
                state,
                item.get("payload") or {},
                LoopStatus.Branch.EVALUATION_RUNNING,
            )
        if items:
            self._checkpoint(state, "evaluation_worker")
            self.log(
                "async submitted evaluation slots="
                f"{len(items)}/{self.config.max_parallel_evaluations}"
            )
        return items

    def _collect_completed_implementations(
        self,
        pending: dict[Future, dict[str, Any]],
    ) -> int:
        """收集已完成的实现任务。"""
        completed = [
            (future, item)
            for future, item in pending.items()
            if future.done()
        ]
        if not completed:
            return 0

        state = self.state_store.load()
        self._checkpoint(state, "implementation_result")
        for future, item in completed:
            if item.get("status") == LoopStatus.Queue.CANCELLED:
                try:
                    future.result()
                except (CancelledError, Exception) as exc:  # noqa: BLE001 - cancel audit only
                    self.artifacts.save_json(
                        "worker_call",
                        {
                            "task": "implementation_cancelled_by_stop",
                            "queue_item_id": item.get("id"),
                            "valid": False,
                            "error": repr(exc),
                        },
                    )
                pending.pop(future, None)
                continue
            if item.get("status") == LoopStatus.Queue.NOT_EXECUTED:
                try:
                    branch = future.result()
                except CancelledError:
                    branch = None
                except Exception as exc:  # noqa: BLE001 - 截止证据不能阻断收尾
                    self.artifacts.save_json(
                        "worker_call",
                        {
                            "task": "implementation_cancelled_at_deadline",
                            "valid": False,
                            "error": repr(exc),
                        },
                    )
                    branch = None
                if isinstance(branch, dict):
                    self._record_not_executed_implementation(state, item, branch)
                pending.pop(future, None)
                continue
            # worker 异常已在 _run_implementation_item 内转换成失败 branch，正常情况
            # 下这里不会因为单个 Idea 失败而中断整个调度器。
            branch = future.result()
            self._process_implementation_result(state, item, branch)
            pending.pop(future, None)

        self._preserve_external_control(state)
        self._checkpoint(state, "idle")
        self.log(f"async collected implementation results={len(completed)}")
        return len(completed)

    def _reserve_official_slot(
        self,
        state: dict[str, Any],
        item: dict[str, Any],
        pending: dict[Future, dict[str, Any]],
    ) -> tuple[bool, str]:
        """为即将执行的 EvaluationJob 预留正式评分预算。"""
        budget = state.get("research_state", {}).get("evaluator_budget", {})
        max_submissions = budget.get("max_submissions")
        used_submissions = int(budget.get("used_submissions") or 0)
        globally_reserved = sum(
            1 for meta in pending.values() if meta.get("official_reserved")
        )
        actor_id = str((item.get("payload") or {}).get("actor_id") or "")
        actor_reserved = sum(
            1
            for meta in pending.values()
            if meta.get("official_reserved") and meta.get("actor_id") == actor_id
        )
        actor_allowed = self._actor_official_budget_available(
            item.get("payload") or {}
        )
        if actor_id and actor_allowed:
            actor = self.actors.read(actor_id)
            actor_budget = actor.get("budget") or {}
            actor_limit = actor_budget.get("max_official_evaluations")
            actor_allowed = actor_limit is None or (
                int(actor_budget.get("used_official_evaluations") or 0)
                + actor_reserved
                < int(actor_limit)
            )
        allowed = (
            (
                max_submissions is None
                or used_submissions + globally_reserved < int(max_submissions)
            )
            and actor_allowed
        )
        return allowed, actor_id

    def _run_evaluation_job(
        self,
        item: dict[str, Any],
        *,
        allow_official: bool,
    ) -> dict[str, Any]:
        """在同一 worker 中依次运行代码、检查产物并调用 evaluator。"""
        payload = item.get("payload") or {}
        admission_error = (
            payload.get("resource_admission_error")
            if isinstance(payload, dict)
            else None
        )
        if isinstance(admission_error, dict):
            run_result = {
                "id": f"resource_rejected_{item.get('id')}",
                "branch_id": payload.get("branch_id") or payload.get("id"),
                "source": "resource_broker",
                "valid": False,
                "returncode": -1,
                "error": str(admission_error.get("error") or "resource rejected"),
                "failure_kind": str(
                    admission_error.get("kind") or "insufficient_task_resources"
                ),
                "resource_admission": admission_error,
                "created_at": now_ms(),
            }
        else:
            run_result = self._run_experiment_item(item)
            if isinstance(payload, dict):
                run_result["resource_request"] = payload.get("resource_request")
                run_result["resource_lease"] = payload.get("resource_lease")
        artifact = str(run_result.get("artifact") or "")
        evaluation_bundle = None
        if run_result.get("valid") and artifact:
            evaluation_bundle = self._run_evaluator_item(
                item,
                run_result,
                allow_official=allow_official,
            )
        return {
            "run_result": run_result,
            "evaluation_bundle": evaluation_bundle,
        }

    def _collect_completed_evaluations(
        self,
        pending: dict[Future, dict[str, Any]],
    ) -> int:
        """串行提交 EvaluationJob 结果，避免状态和预算发生竞争。"""
        completed = [
            (future, metadata)
            for future, metadata in pending.items()
            if future.done()
        ]
        if not completed:
            return 0
        state = self.state_store.load()
        self._checkpoint(state, "evaluation_result")
        for future, metadata in completed:
            lease_id = str(metadata.get("resource_lease_id") or "")
            released = self.resource_broker.release(lease_id) if lease_id else None
            item = metadata["item"]
            if released is not None:
                release_ref = self.artifacts.save_json(
                    "resource_release",
                    {
                        "lease": released.to_dict(),
                        "released_at": now_ms(),
                        "broker_after_release": self.resource_broker.snapshot(),
                    },
                )
                item.setdefault("evidence_refs", []).append(release_ref)
            if item.get("status") == LoopStatus.Queue.CANCELLED:
                try:
                    future.result()
                except (CancelledError, Exception) as exc:  # noqa: BLE001 - cancel audit only
                    self.artifacts.save_json(
                        "evaluation_cancelled",
                        {
                            "queue_item_id": item.get("id"),
                            "valid": False,
                            "error": repr(exc),
                        },
                    )
                pending.pop(future, None)
                continue
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - 单个评测不能中断资源回收
                payload = item.get("payload") or {}
                result = {
                    "run_result": {
                        "id": f"evaluation_worker_failed_{item.get('id')}",
                        "branch_id": payload.get("branch_id") or payload.get("id"),
                        "source": "async_evaluation_worker",
                        "valid": False,
                        "returncode": -1,
                        "error": repr(exc),
                        "created_at": now_ms(),
                    },
                    "evaluation_bundle": None,
                }
            self._process_evaluation_result(
                state,
                item,
                result["run_result"],
                evaluation_bundle=result.get("evaluation_bundle"),
            )
            pending.pop(future, None)
        self._complete_benchmark_if_done(state)
        self._preserve_external_control(state)
        self._checkpoint(state, "async_waiting" if pending else "idle")
        self.log(f"async collected evaluation results={len(completed)}")
        return len(completed)

    @staticmethod
    def _cancel_futures(
        pending_ideas: dict[Future, dict[str, Any]],
        pending_implementations: dict[Future, dict[str, Any]],
        pending_evaluations: dict[Future, dict[str, Any]],
    ) -> None:
        """请求取消尚未完成的后台任务；外部子进程由取消文件终止。"""

        for future in (
            *pending_ideas.keys(),
            *pending_implementations.keys(),
            *pending_evaluations.keys(),
        ):
            future.cancel()

    @staticmethod
    def _mark_pending_cancelled(
        pending_implementations: dict[Future, dict[str, Any]],
        pending_evaluations: dict[Future, dict[str, Any]],
        *,
        reason: str,
    ) -> None:
        """同步更新 Future 元数据，避免晚到结果重新进入流水线。"""

        for item in pending_implementations.values():
            item["status"] = LoopStatus.Queue.CANCELLED
            item["cancel_reason"] = reason
        for metadata in pending_evaluations.values():
            item = metadata.get("item")
            if isinstance(item, dict):
                item["status"] = LoopStatus.Queue.CANCELLED
                item["cancel_reason"] = reason

    def run(self) -> dict[str, Any]:
        """执行当前组件的运行流程。"""
        with WorkspaceRunLock(self.workspace):
            # 同一 goal workspace 同时只允许一个调度器进程修改队列和 ResearchState。
            self.resume_task()
            self._recover_interrupted_items()
            pending_ideas: dict[Future, dict[str, Any]] = {}
            pending_implementations: dict[Future, dict[str, Any]] = {}
            pending_evaluations: dict[Future, dict[str, Any]] = {}
            cycles = 0
            drain_cycles = 0
            wall_time_drain_started = False
            # 与同步 orchestrator 保持一致：max_ticks=0 只验证和初始化配置，
            # 不创建实现任务，也不启动外部 Agent。
            max_cycles = int(self.config.max_ticks)

            def admission_budget_available() -> bool:
                """判断是否仍可启动新的调度周期；负数表示持续运行。"""
                return max_cycles < 0 or cycles < max_cycles

            with ThreadPoolExecutor(
                max_workers=self.config.max_parallel_ideas,
                thread_name_prefix="loop-async-idea",
            ) as idea_executor, ThreadPoolExecutor(
                max_workers=self.config.max_parallel_implementations,
                thread_name_prefix="loop-async-implement",
            ) as implement_executor, ThreadPoolExecutor(
                max_workers=self.config.max_parallel_evaluations,
                thread_name_prefix="loop-async-evaluation",
            ) as evaluation_executor:
                # 线程池生命周期覆盖整个调度过程，避免每个 tick 重建线程并丢失
                # 在途 Future；pending 字典保存 Future 与持久化 queue item 的对应关系。
                while True:
                    # 在收割 Agent Future 之前检查研究截止。否则 Agent 恰好在截止后、
                    # 下一次 tick 前返回时，可能被误送入 Evaluation Queue。
                    state = self.state_store.load()
                    if self._is_master_stop(state):
                        self._cancel_futures(
                            pending_ideas,
                            pending_implementations,
                            pending_evaluations,
                        )
                        self._mark_pending_cancelled(
                            pending_implementations,
                            pending_evaluations,
                            reason=str(
                                state.get("research_state", {}).get(
                                    "termination_reason"
                                )
                                or "stopped_by_user"
                            ),
                        )
                    status_before_collect = state.get("research_state", {}).get(
                        "status"
                    )
                    if (
                        status_before_collect not in LoopStatus.RESEARCH_TERMINAL
                        and self._wall_time_exhausted(state)
                    ):
                        self._stop_for_wall_time(state)
                        state = self.state_store.load()
                    if self._is_wall_time_drain(state) and not wall_time_drain_started:
                        self._begin_wall_time_drain(
                            state,
                            pending_ideas,
                            pending_implementations,
                        )
                        wall_time_drain_started = True

                    # 先收割上一轮已完成的 Future。EvaluationJob 已在同一个 worker
                    # 内顺序完成 run.py 和 evaluator，主线程只提交状态与预算。
                    self._collect_completed_ideas(pending_ideas)
                    self._collect_completed_implementations(pending_implementations)
                    self._collect_completed_evaluations(pending_evaluations)
                    state = self.state_store.load()

                    # 即使 stop/pause 标记已经让 admission 关闭，也要继续消费
                    # commands.jsonl。否则旧版 CLI 写入的控制标记会生效，但对应
                    # command_applied/handoff 回执永远不会生成。
                    self._consume_control_commands(state)
                    state = self.state_store.load()
                    # stop command 可能刚刚在本轮被消费；在 admission 和 worker
                    # 提交之前再次取消，确保正在运行的任务不再回流。
                    if self._is_master_stop(state):
                        self._cancel_futures(
                            pending_ideas,
                            pending_implementations,
                            pending_evaluations,
                        )
                        self._mark_pending_cancelled(
                            pending_implementations,
                            pending_evaluations,
                            reason=str(
                                state.get("research_state", {}).get(
                                    "termination_reason"
                                )
                                or "stopped_by_user"
                            ),
                        )
                    status = state.get("research_state", {}).get("status")
                    control = self._control_status()
                    if self._is_wall_time_drain(state) and not wall_time_drain_started:
                        self._begin_wall_time_drain(
                            state,
                            pending_ideas,
                            pending_implementations,
                        )
                        wall_time_drain_started = True
                        state = self.state_store.load()
                        status = state.get("research_state", {}).get("status")
                    admission_open = (
                        admission_budget_available()
                        and status not in LoopStatus.RESEARCH_TERMINAL
                        and control is None
                    )
                    progressed = False
                    if admission_open:
                        # 生产者侧只推进状态、生成 Idea 和填充持久化队列，不等待
                        # 后台 Implement/Experiment Future 完成。
                        progressed = self.tick(
                            # benchmark Idea 由独立线程池生产；开放科研暂时保留原有
                            # 主线程 novelty-gate 流程。
                            run_ideas=not self.benchmark_managed,
                            run_implementations=False,
                            run_evaluations=False,
                        )
                        # 等待 future 的空轮询不消耗研究周期；只有实际推进，或当前没有
                        # 后台任务可等待时，才把这次 admission 计为一个调度 tick。
                        if progressed or not (
                            pending_evaluations
                            or pending_implementations
                            or pending_ideas
                        ):
                            cycles += 1
                        state = self.state_store.load()
                        status_after_tick = state.get("research_state", {}).get(
                            "status"
                        )
                        if (
                            self._is_wall_time_drain(state)
                            and not wall_time_drain_started
                        ):
                            self._begin_wall_time_drain(
                                state,
                                pending_ideas,
                                pending_implementations,
                            )
                            wall_time_drain_started = True
                            state = self.state_store.load()
                            status_after_tick = state.get("research_state", {}).get(
                                "status"
                            )
                        if status_after_tick not in LoopStatus.RESEARCH_TERMINAL:
                            # Idea 生成与 Implement 使用不同线程池；即使各自并发度都是
                            # 1，第二条 Idea 也能与第一条 Implement 同时运行。
                            submitted_ideas = self._submit_benchmark_ideas(
                                state,
                                idea_executor,
                                pending_ideas,
                            )
                            progressed = progressed or submitted_ideas > 0
                            # Implement/Evaluation 线程池只消费持久化队列项。进程异常退出后，
                            # recover_running() 可以把 running 条目重新放回 queued。
                            for item in self._claim_idea_items(state):
                                future = implement_executor.submit(
                                    self._run_implementation_item,
                                    item,
                                )
                                pending_implementations[future] = item
                            for item in self._claim_evaluation_items(
                                state,
                                inflight=len(pending_evaluations),
                            ):
                                allow_official, actor_id = self._reserve_official_slot(
                                    state,
                                    item,
                                    pending_evaluations,
                                )
                                future = evaluation_executor.submit(
                                    self._run_evaluation_job,
                                    item,
                                    allow_official=allow_official,
                                )
                                pending_evaluations[future] = {
                                    "item": item,
                                    "official_reserved": allow_official,
                                    "actor_id": actor_id,
                                    "resource_lease_id": str(
                                        (
                                            (item.get("payload") or {}).get(
                                                "resource_lease"
                                            )
                                            or {}
                                        ).get("lease_id")
                                        or ""
                                    ),
                                }
                        if (
                            pending_evaluations
                            or pending_implementations
                            or pending_ideas
                        ):
                            state = self.state_store.load()
                            self._checkpoint(state, "async_waiting")

                    if wall_time_drain_started:
                        # 研究预算只约束 Agent run。截止前已进入统一评测池的全部
                        # Candidate 继续领取、运行和正式评分，直到队列彻底排空。
                        state = self.state_store.load()
                        for item in self._claim_evaluation_items(
                            state,
                            inflight=len(pending_evaluations),
                        ):
                            allow_official, actor_id = self._reserve_official_slot(
                                state,
                                item,
                                pending_evaluations,
                            )
                            future = evaluation_executor.submit(
                                self._run_evaluation_job,
                                item,
                                allow_official=allow_official,
                            )
                            pending_evaluations[future] = {
                                "item": item,
                                "official_reserved": allow_official,
                                "actor_id": actor_id,
                                "resource_lease_id": str(
                                    (
                                        (item.get("payload") or {}).get(
                                            "resource_lease"
                                        )
                                        or {}
                                    ).get("lease_id")
                                    or ""
                                ),
                            }
                        # canonical run 和官方 evaluator 都可能持续较久。按分钟记录
                        # 截止快照的状态，便于区分正常长任务、资源等待和真实卡死。
                        state = self.state_store.load()
                        self._record_wall_time_drain_progress(
                            state,
                            pending_evaluations,
                        )

                    collected_after_tick = self._collect_completed_ideas(pending_ideas)
                    collected_after_tick += self._collect_completed_implementations(
                        pending_implementations
                    )
                    collected_after_tick += self._collect_completed_evaluations(
                        pending_evaluations
                    )
                    state = self.state_store.load()
                    status = state.get("research_state", {}).get("status")
                    if (
                        pending_evaluations
                        or pending_implementations
                        or pending_ideas
                    ):
                        # 有后台任务时不能因本轮没有新队列项而退出；等待 Future 完成后
                        # 再由顶部收集结果。
                        time.sleep(self.config.interval_sec)
                        continue
                    if (
                        wall_time_drain_started
                        and self.queues.evaluation.has_queued()
                    ):
                        # 上一批结果刚释放并发槽时，下一轮继续领取截止快照中的候选。
                        time.sleep(self.config.interval_sec)
                        continue
                    # future 可能恰好在本轮 tick 之后完成。此时先进入下一轮，让刚写入的
                    # Evaluation 结果能够驱动新的 benchmark 尝试或普通科研任务。
                    if (
                        collected_after_tick
                        and admission_budget_available()
                        and status not in LoopStatus.RESEARCH_TERMINAL
                    ):
                        time.sleep(self.config.interval_sec)
                        continue
                    if admission_open and admission_budget_available():
                        summary = self.queues.summary()
                        # 队列中仍有 queued/running 工作时继续调度。
                        # 使 Implement 完成后新产生的 Evaluation 不会被提前遗留。
                        has_queued_work = any(
                            value.get(LoopStatus.Queue.QUEUED.value, 0)
                            or value.get(LoopStatus.Queue.LEASED.value, 0)
                            or value.get(
                                LoopStatus.Queue.WAITING_RESOURCES.value,
                                0,
                            )
                            or value.get(LoopStatus.Queue.RUNNING.value, 0)
                            for value in summary.values()
                        )
                        if progressed or has_queued_work:
                            time.sleep(self.config.interval_sec)
                            continue
                    # Evaluation 任务清空后，即使达到周期上限，也给分析池一次串行冲刷机会。
                    # benchmark-managed 不使用 AnalyzeSpark，此分支主要服务开放科研模式。
                    if (
                        not admission_open
                        and status
                        not in {
                            LoopStatus.Research.PAUSED,
                            LoopStatus.Research.STOPPED,
                            LoopStatus.Research.FAILED,
                        }
                        and drain_cycles < 2
                        and self.queues.analyze.has_queued()
                    ):
                        drain_cycles += 1
                        self.tick(run_evaluations=False)
                        time.sleep(self.config.interval_sec)
                        continue
                    break
            state = self.state_store.load()
            if wall_time_drain_started:
                self._record_wall_time_drain_progress(
                    state,
                    pending_evaluations,
                    force=True,
                )
                state = self.state_store.load()
                shutdown = state.setdefault("research_state", {}).setdefault(
                    "shutdown",
                    {},
                )
                shutdown["phase"] = "evaluation_drain_completed"
                shutdown["evaluation_drain_finished_at"] = now_ms()
                self._checkpoint(state, "evaluation_drain_completed")
                self.log("evaluation drain completed")
            state = self.state_store.load()
            self.finalize_cross_task_experience(state)
            return self.state_store.load()
