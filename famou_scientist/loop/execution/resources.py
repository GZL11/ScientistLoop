"""探测 fm-job 内实际可见的共享计算资源。"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from ..domain.resources import GPUDevice


def _visible_device_tokens() -> list[str]:
    """读取容器运行时注入的可见 GPU 标识。"""

    raw = os.environ.get("CUDA_VISIBLE_DEVICES") or os.environ.get(
        "NVIDIA_VISIBLE_DEVICES"
    )
    if not raw or raw.strip().lower() in {"none", "void"}:
        return []
    if raw.strip().lower() == "all":
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def discover_gpu_devices(*, expected_count: int | None = None) -> list[GPUDevice]:
    """使用 nvidia-smi 获取当前 fm-job 可见 GPU 及总显存。"""

    if expected_count is not None and int(expected_count) <= 0:
        return []
    binary = shutil.which("nvidia-smi")
    if binary is None:
        if expected_count:
            raise RuntimeError("fm-job 声明了 GPU，但容器内不存在 nvidia-smi")
        return []
    process = subprocess.run(
        [
            binary,
            "--query-gpu=index,name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if process.returncode != 0:
        if expected_count:
            raise RuntimeError(
                "无法探测 fm-job GPU: "
                + (process.stderr or process.stdout or "unknown error").strip()
            )
        return []
    rows: list[tuple[str, str, float]] = []
    for line in process.stdout.splitlines():
        parts = [item.strip() for item in line.split(",", 2)]
        if len(parts) != 3:
            continue
        try:
            memory_gib = float(parts[2]) / 1024.0
        except ValueError:
            continue
        rows.append((parts[0], parts[1], memory_gib))
    tokens = _visible_device_tokens()
    devices = [
        GPUDevice(
            # CUDA_VISIBLE_DEVICES 已经存在时必须沿用运行时 token；直接写宿主
            # index 可能越出容器获得的设备集合。
            device_id=(tokens[index] if index < len(tokens) else row[0]),
            name=row[1],
            total_memory_gib=row[2],
        )
        for index, row in enumerate(rows)
    ]
    if expected_count is not None and len(devices) != int(expected_count):
        raise RuntimeError(
            "fm-job GPU 数量与运行时探测不一致: "
            f"expected={int(expected_count)}, detected={len(devices)}"
        )
    return devices


def current_gpu_free_memory_gib() -> dict[str, float]:
    """返回当前可见 GPU 的实时空闲显存，并兼容 index、UUID 和运行时 token。"""

    binary = shutil.which("nvidia-smi")
    if binary is None:
        raise RuntimeError("容器内不存在 nvidia-smi，无法检查实时空闲显存")
    process = subprocess.run(
        [
            binary,
            "--query-gpu=index,uuid,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "无法探测 GPU 空闲显存: "
            + (process.stderr or process.stdout or "unknown error").strip()
        )
    tokens = _visible_device_tokens()
    free_by_device: dict[str, float] = {}
    for visible_index, line in enumerate(process.stdout.splitlines()):
        parts = [item.strip() for item in line.split(",", 2)]
        if len(parts) != 3:
            continue
        try:
            free_gib = float(parts[2]) / 1024.0
        except ValueError:
            continue
        aliases = {parts[0], parts[1]}
        if visible_index < len(tokens):
            aliases.add(tokens[visible_index])
        for alias in aliases:
            free_by_device[alias] = free_gib
    if not free_by_device:
        raise RuntimeError("nvidia-smi 未返回可解析的空闲显存")
    return free_by_device


def resource_envelope_dict(
    *,
    available_cpu: float | None,
    available_memory_gib: float | None,
    available_gpu: int | None,
) -> dict[str, Any]:
    """构造供 Goal、Agent 和 Resource Broker 共用的资源信封。"""

    expected_gpu = int(available_gpu) if available_gpu is not None else None
    # 未提供资源信封的普通本地调用保持兼容，不应意外借用宿主机全部 GPU；
    # fm-job 入口会始终显式传入调度器分配的 GPU 数量。
    devices = (
        discover_gpu_devices(expected_count=expected_gpu)
        if expected_gpu is not None
        else []
    )
    reserve = (
        min(device.total_memory_gib for device in devices) * 0.05
        if devices
        else 0.0
    )
    # 主存由 Candidate、Controller、Agent CLI 和文件缓存共享。Broker 只把 75%
    # 作为 Evaluation Pool 可装箱容量，剩余部分留给控制面；该保留量针对整个
    # Pool，而不是再按最大并发静态均分给每条 Candidate。
    host_memory_reserve = (
        float(available_memory_gib) * 0.25
        if available_memory_gib is not None
        else 0.0
    )
    allocatable_memory = (
        max(0.0, float(available_memory_gib) - host_memory_reserve)
        if available_memory_gib is not None
        else None
    )
    return {
        "available_cpu": available_cpu,
        "available_gpu": len(devices),
        "available_memory_gib": available_memory_gib,
        "allocatable_memory_gib": allocatable_memory,
        "host_memory_reserve_gib": host_memory_reserve,
        "gpu_devices": [
            {
                "device_id": device.device_id,
                "name": device.name,
                "total_memory_gib": device.total_memory_gib,
            }
            for device in devices
        ],
        "gpu_memory_reserve_gib": reserve,
        "dynamic_gpu_memory_admission": bool(devices),
        "resource_declarations_required": any(
            value is not None
            for value in (available_cpu, available_memory_gib, available_gpu)
        ),
    }


__all__ = [
    "current_gpu_free_memory_gib",
    "discover_gpu_devices",
    "resource_envelope_dict",
]
