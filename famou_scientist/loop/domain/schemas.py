"""保留端到端第一版结构约定的兼容导出。"""
from __future__ import annotations

from .status import LoopStatus


# 旧调用方仍可读取这两个集合；状态的唯一事实来源已经迁移到 LoopStatus。
QUEUE_STATUSES = LoopStatus.Queue.values()
GOAL_STATUSES = LoopStatus.Research.values()
