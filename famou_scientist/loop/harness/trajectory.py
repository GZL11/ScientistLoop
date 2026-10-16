"""Benchmark Harness 的可追溯事件日志。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import append_jsonl, now_ms


class TrajectoryWriter:
    """按 JSONL 追加保存 Harness 全链路事件。"""

    def __init__(self, path: str | Path):
        """初始化轨迹文件路径。"""
        self.path = Path(path)

    def record(self, event: str, **payload: Any) -> None:
        """追加一条带时间戳的轨迹事件。"""
        append_jsonl(
            self.path,
            {
                "event": event,
                "timestamp_ms": now_ms(),
                **payload,
            },
        )
