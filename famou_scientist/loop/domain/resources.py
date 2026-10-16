"""定义任务级资源信封、候选资源请求和动态租约。"""
from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from ..utils import new_id, now_ms


def _nonnegative_float(value: object, *, name: str) -> float:
    """把输入转换为有限非负浮点数。"""

    try:
        number = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} 必须是有限非负数")
    return number


@dataclass(frozen=True)
class GPUResourceRequest:
    """描述一次运行需要的 GPU 数量和每张卡的显存额度。"""

    device_count: int = 0
    memory_gib_per_device: float = 0.0
    exclusive_compute: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "GPUResourceRequest":
        """从 Idea 或 Candidate 的结构化声明构造 GPU 请求。"""

        raw = value if isinstance(value, Mapping) else {}
        try:
            device_count = int(raw.get("device_count") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("gpu.device_count 必须是整数") from exc
        if device_count < 0:
            raise ValueError("gpu.device_count 不能为负数")
        memory = _nonnegative_float(
            raw.get("memory_gib_per_device"),
            name="gpu.memory_gib_per_device",
        )
        if device_count == 0 and memory > 0:
            raise ValueError("声明 GPU 显存时 device_count 必须大于 0")
        if device_count > 0 and memory <= 0:
            raise ValueError("使用 GPU 时必须声明每张卡所需显存")
        return cls(
            device_count=device_count,
            memory_gib_per_device=memory,
            exclusive_compute=bool(raw.get("exclusive_compute", False)),
        )


@dataclass(frozen=True)
class ResourceRequest:
    """描述 Idea 或 Candidate 对一次正式运行的细粒度资源需求。"""

    cpu_cores: float = 1.0
    host_memory_gib: float = 1.0
    gpu: GPUResourceRequest = field(default_factory=GPUResourceRequest)
    expected_runtime_sec: float | None = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        require_explicit: bool = False,
    ) -> "ResourceRequest":
        """解析资源请求；需要显式声明时拒绝缺失字段。"""

        if require_explicit and not isinstance(value, Mapping):
            raise ValueError("Idea 必须声明 resource_request")
        raw = value if isinstance(value, Mapping) else {}
        if require_explicit:
            missing = [
                name
                for name in ("cpu_cores", "host_memory_gib", "gpu")
                if name not in raw
            ]
            if missing:
                raise ValueError(
                    "resource_request 缺少字段: " + ", ".join(missing)
                )
            if not isinstance(raw.get("gpu"), Mapping):
                raise ValueError("resource_request.gpu 必须是对象")
        cpu = _nonnegative_float(raw.get("cpu_cores", 1), name="cpu_cores")
        memory = _nonnegative_float(
            raw.get("host_memory_gib", 1),
            name="host_memory_gib",
        )
        if cpu <= 0 or memory <= 0:
            raise ValueError("cpu_cores 和 host_memory_gib 必须大于 0")
        expected = raw.get("expected_runtime_sec")
        expected_runtime = (
            _nonnegative_float(expected, name="expected_runtime_sec")
            if expected is not None
            else None
        )
        if expected_runtime == 0:
            raise ValueError("expected_runtime_sec 必须大于 0")
        return cls(
            cpu_cores=cpu,
            host_memory_gib=memory,
            gpu=GPUResourceRequest.from_mapping(
                raw.get("gpu") if isinstance(raw.get("gpu"), Mapping) else None
            ),
            expected_runtime_sec=expected_runtime,
        )

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化字典。"""

        return asdict(self)


@dataclass(frozen=True)
class GPUDevice:
    """描述 fm-job 内可见的一张物理卡或 MIG 设备。"""

    device_id: str
    total_memory_gib: float
    name: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, index: int) -> "GPUDevice":
        """从运行时探测结果构造设备。"""

        return cls(
            device_id=str(value.get("device_id") or value.get("id") or index),
            total_memory_gib=_nonnegative_float(
                value.get("total_memory_gib") or value.get("memory_gib"),
                name="gpu.total_memory_gib",
            ),
            name=str(value["name"]) if value.get("name") else None,
        )


@dataclass(frozen=True)
class ResourceEnvelope:
    """描述一个 fm-job 可由所有节点共享的总资源。"""

    cpu_cores: float | None = None
    host_memory_gib: float | None = None
    gpu_devices: tuple[GPUDevice, ...] = ()
    gpu_memory_reserve_gib: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ResourceEnvelope":
        """从 Goal 的 infra.resources 构造资源信封。"""

        raw = value if isinstance(value, Mapping) else {}
        device_values = raw.get("gpu_devices")
        devices: list[GPUDevice] = []
        if isinstance(device_values, list):
            devices = [
                GPUDevice.from_mapping(item, index=index)
                for index, item in enumerate(device_values)
                if isinstance(item, Mapping)
            ]
        cpu_value = raw.get("available_cpu")
        # available_memory_gib 是 fm-job 总量；运行时可以通过
        # allocatable_memory_gib 为 Controller/Agent 保留统一余量。
        memory_value = raw.get("allocatable_memory_gib")
        if memory_value is None:
            memory_value = raw.get("available_memory_gib")
        return cls(
            cpu_cores=(
                _nonnegative_float(cpu_value, name="available_cpu")
                if cpu_value is not None
                else None
            ),
            host_memory_gib=(
                _nonnegative_float(memory_value, name="available_memory_gib")
                if memory_value is not None
                else None
            ),
            gpu_devices=tuple(devices),
            gpu_memory_reserve_gib=_nonnegative_float(
                raw.get("gpu_memory_reserve_gib"),
                name="gpu_memory_reserve_gib",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化字典。"""

        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        """返回可提供给不可信 Agent 的脱敏资源信封。"""

        return {
            "available_cpu": self.cpu_cores,
            "allocatable_memory_gib": self.host_memory_gib,
            "gpu_device_count": len(self.gpu_devices),
            "gpu_devices": [
                {
                    # 不暴露物理 UUID；Agent 只需要容量，具体设备由 Broker 分配。
                    "name": device.name,
                    "total_memory_gib": device.total_memory_gib,
                    "allocatable_memory_gib": max(
                        0.0,
                        device.total_memory_gib - self.gpu_memory_reserve_gib,
                    ),
                }
                for device in self.gpu_devices
            ],
            "gpu_memory_reserve_gib": self.gpu_memory_reserve_gib,
        }


@dataclass(frozen=True)
class ResourceLease:
    """记录 Resource Broker 为一个 EvaluationJob 原子保留的资源。"""

    lease_id: str
    owner_id: str
    request: ResourceRequest
    gpu_assignments: tuple[dict[str, Any], ...]
    acquired_at: int

    @property
    def cuda_visible_devices(self) -> str:
        """返回 Candidate 进程应看到的 GPU 设备列表。"""

        return ",".join(str(item["device_id"]) for item in self.gpu_assignments)

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化字典。"""

        value = asdict(self)
        value["cuda_visible_devices"] = self.cuda_visible_devices
        return value


class ResourceBroker:
    """在单个 fm-job 内根据资源余量为 EvaluationJob 动态装箱。"""

    def __init__(
        self,
        envelope: ResourceEnvelope,
        *,
        gpu_free_memory_provider: Callable[[], Mapping[str, float]] | None = None,
    ):
        """初始化共享资源容量和活动租约表。"""

        self.envelope = envelope
        self._gpu_free_memory_provider = gpu_free_memory_provider
        self._gpu_observation: dict[str, Any] = {
            "status": "not_configured" if gpu_free_memory_provider is None else "not_checked",
            "free_memory_gib": {},
        }
        self._leases: dict[str, ResourceLease] = {}
        self._lock = threading.RLock()

    def _observe_gpu_free_memory(self) -> dict[str, float] | None:
        """读取设备当前空闲显存；探测失败时按暂时不可调度处理。"""

        if self._gpu_free_memory_provider is None:
            return None
        try:
            observed = {
                str(device_id): max(0.0, float(free_memory))
                for device_id, free_memory in self._gpu_free_memory_provider().items()
            }
        except Exception as exc:  # noqa: BLE001 - 资源探测失败应进入 hold，而非终止 Loop
            self._gpu_observation = {
                "status": "query_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "free_memory_gib": {},
                "observed_at": now_ms(),
            }
            return {}
        self._gpu_observation = {
            "status": "ok",
            "free_memory_gib": observed,
            "observed_at": now_ms(),
        }
        return observed

    def _usage(self) -> tuple[float, float, dict[str, float], set[str]]:
        """汇总当前全部活动租约的资源占用。"""

        cpu = 0.0
        memory = 0.0
        gpu_memory = {item.device_id: 0.0 for item in self.envelope.gpu_devices}
        exclusive: set[str] = set()
        for lease in self._leases.values():
            cpu += lease.request.cpu_cores
            memory += lease.request.host_memory_gib
            for assignment in lease.gpu_assignments:
                device_id = str(assignment["device_id"])
                gpu_memory[device_id] = gpu_memory.get(device_id, 0.0) + float(
                    assignment["memory_gib"]
                )
                if lease.request.gpu.exclusive_compute:
                    exclusive.add(device_id)
        return cpu, memory, gpu_memory, exclusive

    def can_ever_fit(self, request: ResourceRequest) -> bool:
        """判断请求是否可能在空闲的任务总资源中运行。"""

        return not self.fit_violations(request)

    def fit_violations(self, request: ResourceRequest) -> list[str]:
        """说明请求为何不可能装入任务总资源；空列表表示可以装入。"""

        violations: list[str] = []
        if self.envelope.cpu_cores is not None and request.cpu_cores > self.envelope.cpu_cores:
            violations.append(
                "cpu_cores 请求 "
                f"{request.cpu_cores:g}，超过可用上限 {self.envelope.cpu_cores:g}"
            )
        if (
            self.envelope.host_memory_gib is not None
            and request.host_memory_gib > self.envelope.host_memory_gib
        ):
            violations.append(
                "host_memory_gib 请求 "
                f"{request.host_memory_gib:g} GiB，超过可用上限 "
                f"{self.envelope.host_memory_gib:g} GiB"
            )
        required = request.gpu.device_count
        if required == 0:
            return violations
        usable = [
            device
            for device in self.envelope.gpu_devices
            if (
                device.total_memory_gib - self.envelope.gpu_memory_reserve_gib
                >= request.gpu.memory_gib_per_device
            )
        ]
        if len(usable) < required:
            capacities = [
                max(
                    0.0,
                    device.total_memory_gib
                    - self.envelope.gpu_memory_reserve_gib,
                )
                for device in self.envelope.gpu_devices
            ]
            violations.append(
                "gpu 请求 "
                f"{required} 张、每张 {request.gpu.memory_gib_per_device:g} GiB；"
                f"当前仅 {len(usable)} 张满足，逐卡可分配显存为 {capacities} GiB"
            )
        return violations

    def require_can_ever_fit(self, request: ResourceRequest) -> None:
        """请求超过资源信封时抛出包含可操作诊断的异常。"""

        violations = self.fit_violations(request)
        if violations:
            raise ValueError(
                "resource_request 超过任务总资源信封：" + "；".join(violations)
            )

    def try_acquire(
        self,
        request: ResourceRequest,
        *,
        owner_id: str,
    ) -> ResourceLease | None:
        """资源足够时原子创建租约，否则返回 ``None``。"""

        with self._lock:
            self.require_can_ever_fit(request)
            cpu_used, memory_used, gpu_used, exclusive = self._usage()
            if (
                self.envelope.cpu_cores is not None
                and cpu_used + request.cpu_cores > self.envelope.cpu_cores
            ):
                return None
            if (
                self.envelope.host_memory_gib is not None
                and memory_used + request.host_memory_gib
                > self.envelope.host_memory_gib
            ):
                return None

            observed_gpu_free = (
                self._observe_gpu_free_memory()
                if request.gpu.device_count > 0
                else None
            )
            candidates: list[tuple[float, GPUDevice]] = []
            for device in self.envelope.gpu_devices:
                used = gpu_used.get(device.device_id, 0.0)
                logical_free = (
                    device.total_memory_gib
                    - self.envelope.gpu_memory_reserve_gib
                    - used
                )
                if observed_gpu_free is None:
                    admission_free = logical_free
                    observed_free = None
                else:
                    observed_free = observed_gpu_free.get(device.device_id)
                    if observed_free is None:
                        # 已启用动态探测却拿不到该设备的数据时必须 fail closed。
                        continue
                    admission_free = min(
                        logical_free,
                        max(
                            0.0,
                            observed_free - self.envelope.gpu_memory_reserve_gib,
                        ),
                    )
                if device.device_id in exclusive:
                    continue
                if request.gpu.exclusive_compute and used > 0:
                    continue
                if admission_free >= request.gpu.memory_gib_per_device:
                    candidates.append((admission_free, device))
            candidates.sort(key=lambda item: (item[0], item[1].device_id))
            if len(candidates) < request.gpu.device_count:
                return None
            selected = candidates[: request.gpu.device_count]
            assignments = tuple(
                {
                    "device_id": device.device_id,
                    "device_name": device.name,
                    "memory_gib": request.gpu.memory_gib_per_device,
                    "device_total_memory_gib": device.total_memory_gib,
                    "observed_free_memory_gib_at_acquire": (
                        observed_gpu_free.get(device.device_id)
                        if observed_gpu_free is not None
                        else None
                    ),
                    "admission_free_memory_gib": free,
                }
                for free, device in selected
            )
            lease = ResourceLease(
                lease_id=new_id("resource_lease"),
                owner_id=str(owner_id),
                request=request,
                gpu_assignments=assignments,
                acquired_at=now_ms(),
            )
            self._leases[lease.lease_id] = lease
            return lease

    def release(self, lease_id: str) -> ResourceLease | None:
        """释放完成或失败 EvaluationJob 持有的资源。"""

        with self._lock:
            return self._leases.pop(str(lease_id), None)

    def snapshot(self) -> dict[str, Any]:
        """返回当前资源容量、余量和活动租约的审计快照。"""

        with self._lock:
            cpu_used, memory_used, gpu_used, exclusive = self._usage()
            return {
                "envelope": self.envelope.to_dict(),
                "used": {
                    "cpu_cores": cpu_used,
                    "host_memory_gib": memory_used,
                    "gpu_memory_gib": gpu_used,
                    "exclusive_gpu_devices": sorted(exclusive),
                },
                "gpu_observation": dict(self._gpu_observation),
                "leases": [
                    lease.to_dict()
                    for lease in sorted(
                        self._leases.values(),
                        key=lambda item: item.acquired_at,
                    )
                ],
            }


__all__ = [
    "GPUDevice",
    "GPUResourceRequest",
    "ResourceBroker",
    "ResourceEnvelope",
    "ResourceLease",
    "ResourceRequest",
]
