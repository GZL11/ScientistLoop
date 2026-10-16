# -*- coding: UTF-8 -*-
"""把 famou 注册进 ResearchClawBench 的 evaluation/agents.json（幂等）。

RCB 用 agents.json 的一行 `cmd`（经 subprocess shell 运行）来驱动一个 agent。本脚本把
famou 项写进去，`cmd` 指向**同目录的适配器脚本** `famou_rcb.py` 的绝对路径（用当前 Python
解释器跑它，绑定到装了 famou 的那个环境）。agents.json 在使用者本机、从不提交，写绝对路径没问题。

用法：
    python register_famou.py --rcb /path/to/ResearchClawBench
    # 或：RCB_HOME=/path/to/ResearchClawBench python register_famou.py

幂等：已存在 famou 项且等于目标值则跳过；否则按目标值更新（不重复添加）；其余 agent 项保持不动。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 适配器脚本（评测套件本体，随本仓库 clone；不进 pip 包）。
ADAPTER = Path(__file__).resolve().parent / "famou_rcb.py"


def _famou_preset() -> dict:
    """构造 famou 的 agents.json 预设项。cmd 指向本地适配器脚本的绝对路径。

    用 sys.executable 跑脚本 → 绑定到「装了 famou 的那个 Python 环境」，不依赖 PATH/exec 位。
    <WORKSPACE> 是 RCB 自己替换的占位符，原样保留。
    """
    return {
        "label": "Famou-Scientist",
        "icon": "F",
        "logo": "/static/logos/researchclaw.svg",
        "cmd": f"{sys.executable} {ADAPTER} -w <WORKSPACE>",
    }


def _rcb_home(cli_value: str | None) -> Path:
    home = cli_value or os.environ.get("RCB_HOME", "")
    if not home:
        print(
            "register_famou: 未提供 RCB 路径。用 --rcb <path> 或设 RCB_HOME 环境变量。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Path(home).expanduser().resolve()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Register famou into ResearchClawBench agents.json (idempotent).")
    ap.add_argument("--rcb", default=None, help="ResearchClawBench 仓库路径（或设 RCB_HOME 环境变量）")
    ns = ap.parse_args(argv)

    rcb = _rcb_home(ns.rcb)
    agents_path = rcb / "evaluation" / "agents.json"
    if not agents_path.is_file():
        print(
            f"register_famou: 找不到 {agents_path}\n"
            f"  确认 --rcb 指向的是 ResearchClawBench 仓库根（应含 evaluation/agents.json）。",
            file=sys.stderr,
        )
        return 2

    try:
        data = json.loads(agents_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"register_famou: 读取/解析 {agents_path} 失败：{exc!r}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"register_famou: {agents_path} 顶层不是对象，无法注册。", file=sys.stderr)
        return 1

    preset = _famou_preset()
    if data.get("famou") == preset:
        print(f"register_famou: famou 已注册且为最新（{agents_path}）。")
        return 0

    data["famou"] = preset
    try:
        agents_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"register_famou: 写入 {agents_path} 失败：{exc!r}", file=sys.stderr)
        return 1
    print(f"register_famou: 已注册 famou → {agents_path}\n  cmd = {preset['cmd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
