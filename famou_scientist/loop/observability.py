"""Loop 级 Agent 轨迹、Token 与费用观测设施。"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:  # pragma: no cover - Windows 仅使用进程内追加语义
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from .utils import atomic_write_json, new_id, now_ms


SCHEMA_VERSION = 1
TOKEN_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
PRICING_FIELDS = {
    "input_tokens": "input",
    "cache_creation_input_tokens": "cache_creation",
    "cache_read_input_tokens": "cache_read",
    "output_tokens": "output",
}


def _non_negative_int(value: Any) -> int | None:
    """把供应商数值转换为非负整数，缺失或非法值保持为空。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def _finite_number(value: Any) -> float | None:
    """读取有限浮点数，不对缺失费用做价格推断。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _json_objects(text: str) -> list[dict[str, Any]]:
    """从 CLI JSON/JSONL 输出中读取顶层对象，忽略普通文本行。"""

    objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        value = line.strip()
        if not value or not value.startswith("{"):
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects


@dataclass(frozen=True)
class AgentTokenUsage:
    """保存供应商明确上报的 Token 字段。"""

    input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentTokenUsage":
        """兼容 Claude、Codex 和常见 OpenAI usage 字段。"""

        return cls(
            input_tokens=_non_negative_int(
                value.get("input_tokens", value.get("inputTokens"))
            ),
            cache_creation_input_tokens=_non_negative_int(
                value.get(
                    "cache_creation_input_tokens",
                    value.get("cacheCreationInputTokens"),
                )
            ),
            cache_read_input_tokens=_non_negative_int(
                value.get(
                    "cache_read_input_tokens",
                    value.get(
                        "cached_input_tokens",
                        value.get("cacheReadInputTokens"),
                    ),
                )
            ),
            output_tokens=_non_negative_int(
                value.get("output_tokens", value.get("outputTokens"))
            ),
        )

    @property
    def reported_total_tokens(self) -> int | None:
        """返回已上报字段之和；所有字段缺失时返回空值。"""

        values = [getattr(self, name) for name in TOKEN_FIELDS]
        known = [value for value in values if value is not None]
        return sum(known) if known else None

    def to_dict(self) -> dict[str, int | None]:
        """转换为稳定的序列化结构。"""

        return asdict(self)


@dataclass(frozen=True)
class TokenPricingPolicy:
    """定义四类 Token 的每百万单位价格及其审计来源。"""

    currency: str
    input_per_million: float
    cache_creation_per_million: float
    cache_read_per_million: float
    output_per_million: float
    source: str | None = None
    effective_at: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TokenPricingPolicy":
        """从 Goal 中的 ``infra.observability.pricing`` 构造价格策略。"""

        rates = value.get("per_million_tokens")
        if not isinstance(rates, Mapping):
            raise ValueError("pricing.per_million_tokens 必须是 object")
        parsed: dict[str, float] = {}
        for name in PRICING_FIELDS.values():
            amount = _finite_number(rates.get(name))
            if amount is None or amount < 0:
                raise ValueError(
                    f"pricing.per_million_tokens.{name} 必须是非负有限数字"
                )
            parsed[name] = amount
        currency = str(value.get("currency") or "").strip().upper()
        if not currency:
            raise ValueError("pricing.currency 不能为空")
        return cls(
            currency=currency,
            input_per_million=parsed["input"],
            cache_creation_per_million=parsed["cache_creation"],
            cache_read_per_million=parsed["cache_read"],
            output_per_million=parsed["output"],
            source=(str(value["source"]).strip() if value.get("source") else None),
            effective_at=(
                str(value["effective_at"]).strip()
                if value.get("effective_at")
                else None
            ),
        )

    @property
    def rates(self) -> dict[str, float]:
        """返回与配置 schema 一致的每百万 Token 价格。"""

        return {
            "input": self.input_per_million,
            "cache_creation": self.cache_creation_per_million,
            "cache_read": self.cache_read_per_million,
            "output": self.output_per_million,
        }

    def to_dict(self) -> dict[str, Any]:
        """生成可写入摘要的稳定价格策略。"""

        return {
            "currency": self.currency,
            "per_million_tokens": self.rates,
        }

    def calculate(self, usage: Mapping[str, Any]) -> dict[str, Any]:
        """按四类 Token 独立计价，避免把缓存读取误算为普通输入。"""

        breakdown: dict[str, float] = {}
        for token_name, price_name in PRICING_FIELDS.items():
            tokens = _non_negative_int(usage.get(token_name)) or 0
            breakdown[price_name] = tokens * self.rates[price_name] / 1_000_000
        return {
            "amount": sum(breakdown.values()),
            "currency": self.currency,
            "breakdown": breakdown,
            "source": "configured_pricing",
        }


def _sum_usage(values: Iterable[Mapping[str, Any]]) -> AgentTokenUsage:
    """合并同一次 wrapper 内多个实际 CLI 激活的用量。"""

    totals: dict[str, int | None] = {name: None for name in TOKEN_FIELDS}
    for value in values:
        usage = AgentTokenUsage.from_mapping(value)
        for name in TOKEN_FIELDS:
            amount = getattr(usage, name)
            if amount is not None:
                totals[name] = int(totals[name] or 0) + amount
    return AgentTokenUsage(**totals)


def _runtime_usage_objects(
    runtime: str,
    objects: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """选择不会重复计数的供应商 usage 对象。"""

    normalized = runtime.strip().lower()
    if normalized == "claude":
        # ``claude --output-format json`` 每次激活只产生一个 result；其中顶层
        # usage 已是本次激活总量，不能再累加 modelUsage 或 iterations。
        return [item["usage"] for item in objects if isinstance(item.get("usage"), Mapping)]
    if normalized == "codex":
        # Codex JSONL 的 turn.completed 是每次 exec/resume 的唯一汇总事件。
        selected = [
            item["usage"]
            for item in objects
            if item.get("type") == "turn.completed"
            and isinstance(item.get("usage"), Mapping)
        ]
        if selected:
            return selected
    # OpenCode 或自定义兼容端只读取顶层 usage；递归搜索容易把同一响应重复累计。
    return [item["usage"] for item in objects if isinstance(item.get("usage"), Mapping)]


def normalize_cli_telemetry(
    *,
    runtime: str,
    stdout: str,
    model: str | None,
) -> dict[str, Any]:
    """把 CLI 供应商输出归一化为 usage/cost/model 元数据。"""

    objects = _json_objects(stdout)
    usages = _runtime_usage_objects(runtime, objects)
    token_usage = _sum_usage(usages)
    provider_turns = 0
    reported_cost = 0.0
    cost_seen = False
    discovered_models: list[str] = []
    for item in objects:
        turns = _non_negative_int(item.get("num_turns"))
        if turns is not None:
            provider_turns += turns
        elif item.get("type") == "turn.completed" and isinstance(
            item.get("usage"), Mapping
        ):
            provider_turns += 1
        cost = _finite_number(item.get("total_cost_usd", item.get("cost_usd")))
        if cost is not None:
            reported_cost += cost
            cost_seen = True
        model_usage = item.get("modelUsage")
        if isinstance(model_usage, Mapping):
            discovered_models.extend(
                str(name)
                for name in model_usage
                if str(name).strip() and str(name) != "<synthetic>"
            )
        event_model = item.get("model")
        if isinstance(event_model, str) and event_model.strip() != "<synthetic>":
            discovered_models.append(event_model)

    selected_model = str(model).strip() if model else None
    if not selected_model and discovered_models:
        selected_model = ",".join(dict.fromkeys(discovered_models))
    return {
        "model": selected_model,
        "provider_turns": provider_turns or None,
        "token_usage": token_usage.to_dict(),
        "reported_total_tokens": token_usage.reported_total_tokens,
        "cost": {
            "amount": reported_cost if cost_seen else None,
            "currency": "USD" if cost_seen else None,
            "source": "cli_reported" if cost_seen else None,
        },
    }


def normalize_command_telemetry(value: Mapping[str, Any]) -> dict[str, Any]:
    """读取自定义 Agent/LLM 命令主动返回的标准 telemetry。"""

    telemetry = value.get("__telemetry__")
    if isinstance(telemetry, Mapping):
        result = dict(telemetry)
        usage = result.get("token_usage", result.get("usage"))
    else:
        result = {}
        usage = value.get("__usage__")
    token_usage = AgentTokenUsage.from_mapping(usage if isinstance(usage, Mapping) else {})
    result["token_usage"] = token_usage.to_dict()
    result["reported_total_tokens"] = token_usage.reported_total_tokens
    result.setdefault("model", None)
    result.setdefault("provider_turns", None)
    cost = result.get("cost")
    if not isinstance(cost, Mapping):
        amount = _finite_number(result.get("total_cost_usd", result.get("cost_usd")))
        cost = {
            "amount": amount,
            "currency": "USD" if amount is not None else None,
            "source": "provider_reported" if amount is not None else None,
        }
    result["cost"] = dict(cost)
    return result


def normalize_trajectory_telemetry(
    path: str | Path,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """在 CLI 没有最终 result 时从本次增量轨迹恢复 Token 用量。"""

    source = Path(path)
    if not source.is_file():
        return normalize_command_telemetry({})
    usage_records: list[Mapping[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    discovered_model = model
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, dict):
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            continue
        message = payload.get("message")
        if isinstance(message, Mapping) and isinstance(message.get("usage"), Mapping):
            usage = message["usage"]
            message_model = message.get("model")
            key = (
                envelope.get("session_id"),
                message.get("id") or payload.get("uuid"),
                message_model,
                *(
                    _non_negative_int(
                        usage.get(
                            name,
                            usage.get("cached_input_tokens")
                            if name == "cache_read_input_tokens"
                            else None,
                        )
                    )
                    for name in TOKEN_FIELDS
                ),
            )
            if key not in seen:
                seen.add(key)
                usage_records.append(usage)
            if not discovered_model and isinstance(message_model, str):
                discovered_model = message_model
        elif payload.get("type") == "turn.completed" and isinstance(
            payload.get("usage"), Mapping
        ):
            usage = payload["usage"]
            key = (
                envelope.get("session_id"),
                payload.get("turn_id") or payload.get("id") or envelope.get("event_id"),
                *(
                    _non_negative_int(
                        usage.get(
                            name,
                            usage.get("cached_input_tokens")
                            if name == "cache_read_input_tokens"
                            else None,
                        )
                    )
                    for name in TOKEN_FIELDS
                ),
            )
            if key not in seen:
                seen.add(key)
                usage_records.append(usage)
    token_usage = _sum_usage(usage_records)
    return {
        "model": discovered_model,
        "provider_turns": len(usage_records) or None,
        "token_usage": token_usage.to_dict(),
        "reported_total_tokens": token_usage.reported_total_tokens,
        "cost": {"amount": None, "currency": None, "source": None},
    }


def snapshot_jsonl_files(roots: Iterable[str | Path]) -> dict[str, int]:
    """记录原生 Session JSONL 当前字节偏移，用于 Resume 增量导出。"""

    cursors: dict[str, int] = {}
    for root_value in roots:
        root = Path(root_value)
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            try:
                cursors[str(path.resolve())] = path.stat().st_size
            except OSError:
                continue
    return cursors


def export_incremental_trajectory(
    *,
    output_path: str | Path,
    roots: Iterable[str | Path],
    cursors: Mapping[str, int],
    call_id: str,
    role: str,
    runtime: str,
    session_id: str | None,
    stdout: str = "",
) -> dict[str, Any]:
    """导出本次激活新增的原生事件，并包装成 benchmark 无关轨迹。"""

    records: list[dict[str, Any]] = []
    native_refs: list[str] = []
    sequence = 0
    discovered: set[Path] = set()
    for root_value in roots:
        root = Path(root_value)
        if root.is_dir():
            discovered.update(path.resolve() for path in root.rglob("*.jsonl"))
    for path in sorted(discovered, key=str):
        try:
            start = max(0, int(cursors.get(str(path), 0)))
            size = path.stat().st_size
            if size <= start:
                continue
            with path.open("rb") as stream:
                stream.seek(start)
                chunk = stream.read()
        except OSError:
            continue
        native_refs.append(str(path))
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_id": f"{call_id}:{sequence}",
                    "call_id": call_id,
                    "role": role,
                    "runtime": runtime,
                    "session_id": session_id,
                    "sequence": sequence,
                    "event_type": str(
                        payload.get("type")
                        or (payload.get("message") or {}).get("role")
                        or "provider_event"
                    ),
                    "timestamp": payload.get("timestamp"),
                    "source": {"kind": "native_session", "path": str(path)},
                    "payload": payload,
                }
            )
            sequence += 1

    # 某些 CLI 或失败路径不落原生 Session。此时至少保留 stdout 中的 JSON
    # 事件，确保调用结果、usage 和终止原因仍能被统一导出。
    if not records:
        for payload in _json_objects(stdout):
            records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_id": f"{call_id}:{sequence}",
                    "call_id": call_id,
                    "role": role,
                    "runtime": runtime,
                    "session_id": session_id,
                    "sequence": sequence,
                    "event_type": str(payload.get("type") or "provider_result"),
                    "timestamp": payload.get("timestamp"),
                    "source": {"kind": "cli_stdout"},
                    "payload": payload,
                }
            )
            sequence += 1

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    return {
        "normalized_path": str(target),
        "records": len(records),
        "native_refs": native_refs,
        "resume_delta": True,
    }


@dataclass
class AgentUsageRecord:
    """描述一次 Agent 激活的统一可计量记录。"""

    call_id: str
    role: str
    adapter: str
    runtime: str
    status: str
    started_at_ms: int | None
    finished_at_ms: int | None
    duration_ms: int | None
    model: str | None = None
    session_id: str | None = None
    resumed: bool = False
    returncode: int | None = None
    provider_turns: int | None = None
    token_usage: dict[str, int | None] = field(default_factory=dict)
    reported_total_tokens: int | None = None
    cost: dict[str, Any] = field(default_factory=dict)
    native_trajectory_refs: list[str] = field(default_factory=list)
    normalized_trajectory_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """转换为可追加到 usage ledger 的记录。"""

        return asdict(self)


class ObservabilityStore:
    """并发安全地保存 Run 级 Agent usage 与统一轨迹。"""

    def __init__(
        self,
        workspace: str | Path,
        *,
        pricing: TokenPricingPolicy | Mapping[str, Any] | None = None,
    ):
        """初始化稳定产物路径，并恢复可选的配置价格策略。"""

        self.workspace = Path(workspace).expanduser().resolve()
        self.artifacts_dir = self.workspace / "artifacts"
        self.controller_dir = self.workspace / "controller"
        self.usage_path = self.artifacts_dir / "agent_usage.jsonl"
        self.trajectory_path = self.artifacts_dir / "agent_trajectory.jsonl"
        self.summary_path = self.controller_dir / "agent_usage_summary.json"
        self.lock_path = self.artifacts_dir / ".observability.lock"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.controller_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(pricing, TokenPricingPolicy):
            self.pricing = pricing
        elif isinstance(pricing, Mapping):
            self.pricing = TokenPricingPolicy.from_mapping(pricing)
        else:
            self.pricing = self._pricing_from_research_state()

    def _pricing_from_research_state(self) -> TokenPricingPolicy | None:
        """从持久化 Goal 恢复价格，使离线导出沿用运行时口径。"""

        state_path = self.workspace / "research_state.yaml"
        if not state_path.is_file():
            return None
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        research = state.get("research_state") if isinstance(state, Mapping) else None
        goal = research.get("goal") if isinstance(research, Mapping) else None
        infra = goal.get("infra") if isinstance(goal, Mapping) else None
        observability = (
            infra.get("observability") if isinstance(infra, Mapping) else None
        )
        pricing = (
            observability.get("pricing")
            if isinstance(observability, Mapping)
            else None
        )
        return (
            TokenPricingPolicy.from_mapping(pricing)
            if isinstance(pricing, Mapping)
            else None
        )

    def _relative_ref(self, value: Any) -> Any:
        """把 Run 内绝对路径转换为可移植的相对引用。"""

        if not isinstance(value, str) or not value:
            return value
        try:
            return str(Path(value).resolve().relative_to(self.workspace))
        except (OSError, ValueError):
            return value

    def _append_locked(self, target: Path, records: Iterable[Mapping[str, Any]]) -> None:
        """在跨线程/进程文件锁内完成整行追加。"""

        rows = [json.dumps(dict(record), ensure_ascii=False) + "\n" for record in records]
        if not rows:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                with target.open("a", encoding="utf-8") as stream:
                    stream.writelines(rows)
                    stream.flush()
            finally:
                if fcntl is not None:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def record_agent_call(
        self,
        call: Mapping[str, Any],
        *,
        task: str,
        role: str,
        valid: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把任意 Agent Adapter 的调用元数据写入统一 ledger。"""

        run = call.get("run") if isinstance(call.get("run"), Mapping) else {}
        telemetry = (
            dict(call.get("telemetry"))
            if isinstance(call.get("telemetry"), Mapping)
            else {}
        )
        session = call.get("session") if isinstance(call.get("session"), Mapping) else {}
        token_usage = AgentTokenUsage.from_mapping(
            telemetry.get("token_usage")
            if isinstance(telemetry.get("token_usage"), Mapping)
            else {}
        )
        duration = telemetry.get("duration_ms", run.get("duration_ms"))
        started_at = telemetry.get("started_at_ms", call.get("created_at"))
        finished_at = telemetry.get("finished_at_ms")
        if finished_at is None and isinstance(started_at, (int, float)) and isinstance(
            duration, (int, float)
        ):
            finished_at = int(started_at) + int(duration)
        trajectory = (
            telemetry.get("trajectory")
            if isinstance(telemetry.get("trajectory"), Mapping)
            else {}
        )
        native_refs = [
            self._relative_ref(value)
            for value in trajectory.get("native_refs", [])
            if isinstance(value, str)
        ]
        status = str(telemetry.get("status") or ("succeeded" if valid else "failed"))
        record = AgentUsageRecord(
            call_id=str(call.get("id") or new_id("agent_call")),
            role=role,
            adapter=str(telemetry.get("adapter") or "cli"),
            runtime=str(telemetry.get("runtime") or call.get("runtime") or "command"),
            status=status,
            started_at_ms=(int(started_at) if isinstance(started_at, (int, float)) else None),
            finished_at_ms=(
                int(finished_at) if isinstance(finished_at, (int, float)) else None
            ),
            duration_ms=(int(duration) if isinstance(duration, (int, float)) else None),
            model=(str(telemetry["model"]) if telemetry.get("model") else None),
            session_id=(str(session.get("session_id")) if session.get("session_id") else None),
            resumed=bool(session.get("resumed_this_call", telemetry.get("resumed"))),
            returncode=(
                int(telemetry.get("returncode", run.get("returncode")))
                if isinstance(
                    telemetry.get("returncode", run.get("returncode")),
                    (int, float),
                )
                else None
            ),
            provider_turns=(
                int(telemetry["provider_turns"])
                if isinstance(telemetry.get("provider_turns"), (int, float))
                else None
            ),
            token_usage=token_usage.to_dict(),
            reported_total_tokens=token_usage.reported_total_tokens,
            cost=(dict(telemetry["cost"]) if isinstance(telemetry.get("cost"), Mapping) else {}),
            native_trajectory_refs=native_refs,
            normalized_trajectory_ref=self._relative_ref(
                trajectory.get("normalized_path")
            ),
            metadata={"task": task, **dict(metadata or {})},
        ).to_dict()
        self._append_locked(self.usage_path, [record])

        normalized_path = trajectory.get("normalized_path")
        if isinstance(normalized_path, str) and Path(normalized_path).is_file():
            events: list[dict[str, Any]] = []
            for line in Path(normalized_path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    event["metadata"] = {
                        **dict(event.get("metadata") or {}),
                        "task": task,
                        **dict(metadata or {}),
                    }
                    source = event.get("source")
                    if isinstance(source, dict) and source.get("path"):
                        source["path"] = self._relative_ref(source["path"])
                    events.append(event)
            self._append_locked(self.trajectory_path, events)
        return record

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        """读取完整 JSONL，忽略并发写入时尚未完成的尾行。"""

        if not path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def usage_records(self) -> list[dict[str, Any]]:
        """按 call_id 去重读取用量记录，保留最后写入版本。"""

        by_call: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for record in self._read_jsonl(self.usage_path):
            call_id = str(record.get("call_id") or "")
            if not call_id:
                continue
            if call_id not in by_call:
                order.append(call_id)
            by_call[call_id] = record
        return [by_call[call_id] for call_id in order]

    def trajectory_records(self) -> list[dict[str, Any]]:
        """按 event_id 去重读取统一轨迹。"""

        by_event: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for record in self._read_jsonl(self.trajectory_path):
            event_id = str(record.get("event_id") or "")
            if not event_id:
                continue
            if event_id not in by_event:
                order.append(event_id)
            by_event[event_id] = record
        return [by_event[event_id] for event_id in order]

    def build_summary(self) -> dict[str, Any]:
        """按角色、运行时和模型汇总时长、Token 与两类费用。"""

        records = self.usage_records()

        def empty_bucket() -> dict[str, Any]:
            """创建一个可累加的统计桶。"""

            return {
                "calls": 0,
                "duration_ms": 0,
                "provider_turns": 0,
                **{name: 0 for name in TOKEN_FIELDS},
                "reported_total_tokens": 0,
                "reported_cost": {},
                "cli_reported_cost": {},
                "calls_with_token_usage": 0,
                "calls_with_reported_cost": 0,
                "calls_with_calculated_cost": 0,
            }

        total = empty_bucket()
        groups: dict[str, dict[str, dict[str, Any]]] = {
            "role": {},
            "runtime": {},
            "model": {},
        }

        def add(bucket: dict[str, Any], record: Mapping[str, Any]) -> None:
            """把一条调用记录累加到统计桶。"""

            bucket["calls"] += 1
            bucket["duration_ms"] += int(record.get("duration_ms") or 0)
            bucket["provider_turns"] += int(record.get("provider_turns") or 0)
            usage = record.get("token_usage")
            usage_seen = False
            if isinstance(usage, Mapping):
                for name in TOKEN_FIELDS:
                    value = _non_negative_int(usage.get(name))
                    if value is not None:
                        bucket[name] += value
                        usage_seen = True
            if usage_seen:
                bucket["calls_with_token_usage"] += 1
            bucket["reported_total_tokens"] = sum(
                int(bucket[name]) for name in TOKEN_FIELDS
            )
            cost = record.get("cost")
            if isinstance(cost, Mapping):
                amount = _finite_number(cost.get("amount"))
                currency = cost.get("currency")
                if amount is not None and currency:
                    key = str(currency).upper()
                    bucket["reported_cost"][key] = (
                        float(bucket["reported_cost"].get(key, 0.0)) + amount
                    )
                    bucket["cli_reported_cost"][key] = (
                        float(bucket["cli_reported_cost"].get(key, 0.0)) + amount
                    )
                    bucket["calls_with_reported_cost"] += 1

        def finalize(bucket: dict[str, Any]) -> None:
            """在 Token 累加结束后计算配置价格，不改写 CLI 原始费用。"""

            if self.pricing is None:
                bucket["calculated_cost"] = None
                bucket["calculated_cost_breakdown"] = None
                return
            calculated = self.pricing.calculate(bucket)
            currency = self.pricing.currency
            bucket["calculated_cost"] = {currency: calculated["amount"]}
            bucket["calculated_cost_breakdown"] = {
                currency: calculated["breakdown"]
            }
            bucket["calls_with_calculated_cost"] = bucket[
                "calls_with_token_usage"
            ]

        for record in records:
            add(total, record)
            for dimension in groups:
                key = str(record.get(dimension) or "unknown")
                bucket = groups[dimension].setdefault(key, empty_bucket())
                add(bucket, record)
        finalize(total)
        for dimension in groups.values():
            for bucket in dimension.values():
                finalize(bucket)
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at_ms": now_ms(),
            "workspace": str(self.workspace),
            "usage_ledger": str(self.usage_path),
            "trajectory_ledger": str(self.trajectory_path),
            "trajectory_events": len(self.trajectory_records()),
            "total": total,
            "by_role": groups["role"],
            "by_runtime": groups["runtime"],
            "by_model": groups["model"],
            "pricing_policy": self.pricing.to_dict() if self.pricing else None,
            "pricing_source": self.pricing.source if self.pricing else None,
            "pricing_effective_at": (
                self.pricing.effective_at if self.pricing else None
            ),
            "cost_policy": (
                "保留 Agent CLI/Adapter 原始费用，并按显式配置价格独立重算。"
                if self.pricing
                else "仅汇总 Agent CLI/Adapter 明确返回的费用；缺失价格不估算。"
            ),
        }

    def write_summary(self) -> dict[str, Any]:
        """生成并持久化当前 Run 的观测摘要。"""

        summary = self.build_summary()
        atomic_write_json(self.summary_path, summary)
        return summary

    def export(self, output_dir: str | Path) -> Path:
        """导出 JSONL、CSV 和摘要，供外部平台或 benchmark adapter 使用。"""

        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        usage_records = self.usage_records()
        trajectory_records = self.trajectory_records()
        summary = self.write_summary()
        (destination / "agent_usage.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in usage_records),
            encoding="utf-8",
        )
        (destination / "agent_trajectory.jsonl").write_text(
            "".join(
                json.dumps(item, ensure_ascii=False) + "\n"
                for item in trajectory_records
            ),
            encoding="utf-8",
        )
        atomic_write_json(destination / "agent_usage_summary.json", summary)
        columns = [
            "call_id",
            "role",
            "adapter",
            "runtime",
            "model",
            "status",
            "session_id",
            "resumed",
            "started_at_ms",
            "finished_at_ms",
            "duration_ms",
            "returncode",
            "provider_turns",
            *TOKEN_FIELDS,
            "reported_total_tokens",
            "cost_amount",
            "cost_currency",
            "cost_source",
            "calculated_cost_amount",
            "calculated_cost_currency",
            "calculated_input_cost",
            "calculated_cache_creation_cost",
            "calculated_cache_read_cost",
            "calculated_output_cost",
        ]
        with (destination / "agent_usage.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for record in usage_records:
                usage = record.get("token_usage") or {}
                cost = record.get("cost") or {}
                row = {name: record.get(name) for name in columns}
                for name in TOKEN_FIELDS:
                    row[name] = usage.get(name)
                row["cost_amount"] = cost.get("amount")
                row["cost_currency"] = cost.get("currency")
                row["cost_source"] = cost.get("source")
                calculated = self.pricing.calculate(usage) if self.pricing else {}
                breakdown = calculated.get("breakdown") or {}
                row["calculated_cost_amount"] = calculated.get("amount")
                row["calculated_cost_currency"] = calculated.get("currency")
                row["calculated_input_cost"] = breakdown.get("input")
                row["calculated_cache_creation_cost"] = breakdown.get(
                    "cache_creation"
                )
                row["calculated_cache_read_cost"] = breakdown.get("cache_read")
                row["calculated_output_cost"] = breakdown.get("output")
                writer.writerow(row)
        return destination


__all__ = [
    "AgentTokenUsage",
    "AgentUsageRecord",
    "ObservabilityStore",
    "TokenPricingPolicy",
    "TOKEN_FIELDS",
    "export_incremental_trajectory",
    "normalize_cli_telemetry",
    "normalize_command_telemetry",
    "normalize_trajectory_telemetry",
    "snapshot_jsonl_files",
]
