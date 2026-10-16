# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""轨迹查询与可视化（vis）—— 只读 opencode 会话库，导轨迹 / 起 web 页面。

- ``trace``      ：CLI + 数据逻辑（列会话、按 rowid 拼 message+part 成 JSONL）。
- ``trace_web``  ：纯 stdlib 本地 web 服务（复用 trace 的数据逻辑）。
- ``trace_viewer.html``：单文件前端（深色终端风，无构建无外链）。

由 ``famou-scientist trace [--web]`` 子命令驱动（见 ``famou_scientist/cmdline.py``）。
详见 ``docs/operations/TRAJECTORY_OBSERVABILITY.md``。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations
