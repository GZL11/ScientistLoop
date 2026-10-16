#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""famou_rcb —— 作为 ResearchClawBench(RCB) 评测的 agent 入口（评测套件本体，非 famou 包的一部分）。

RCB（InternScience/ResearchClawBench）用**子进程**驱动自主 agent：它在
`evaluation/agents.json` 注册一行 `cmd`，对每个任务建好 workspace（含 data/、
related_work/、INSTRUCTIONS.md），以 cwd=<workspace> 把 agent 当子进程拉起，
跑完去 `<workspace>/report/report.md` + `report/images/*.png` 取产物打分。

famou 与这个契约有两处错位，本脚本负责弥合：
  1. RCB 要「非交互、跑完退出」——本脚本用子进程跑 `python -m famou_scientist run`
     （透传成 `opencode run`，headless、跑完即退）。
  2. RCB 要产物落在 `report/report.md` + `report/images/`——famou 写到
     `research-runs/<主题>/deliverables/paper.md` + `figures/*.png`，本脚本跑完
     把论文搬成 `report/report.md`、把图搬进 `report/images/`，并把 markdown 里
     `figures/` 的图链接重写成 `images/`（这样在 report/ 下能解析）。

它是**评测套件的一部分**（住在 benchmark/researchclawbench/，随仓库 clone，不进 pip 包）——
评测本来就要 clone 本仓库拿 run_eval.sh/register_famou.py，所以适配器放这里最合适。
RCB 的 agents.json 由同目录 `register_famou.py` 程序化写入，`cmd` 指向本脚本的绝对路径。

用法：
    python famou_rcb.py -w <WORKSPACE>      # 通常由 RCB 经 agents.json 调起，无需手动跑

env：
    FAMOU_RCB_MODEL   可选 "provider/model"，覆盖 opencode 默认模型。

退出码：有 `report/report.md` → 0；无 → 1（并打印警告，便于上游识别「没产出」而非静默 0 分）。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

__all__ = [
    "main",
]


def _parse_workspace(args: list[str]) -> str:
    """从 args 解析 -w/--workspace（缺省用当前目录）。其余参数忽略（与旧壳脚本一致）。"""
    ws = ""
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-w", "--workspace"):
            ws = args[i + 1] if i + 1 < len(args) else ""
            i += 2
            continue
        if a.startswith("-w=") or a.startswith("--workspace="):
            ws = a.split("=", 1)[1]
        i += 1
    return ws or os.getcwd()


def _rewrite_fig_links(md_text: str) -> str:
    """把 markdown 里 `](figures/...)` / `](./figures/...)` 的图链接重写成 `](images/...)`。

    纯函数（便于单测）。只动 markdown 图/链接语法里的 `figures/` 前缀，等价旧壳脚本的
    `sed -E 's#\\]\\((\\.?/)?figures/#](images/#g'`。
    """
    return re.sub(r"\]\((\.?/)?figures/", "](images/", md_text)


def _pick_paper(deliverables: Path) -> Path | None:
    """选论文文件：优先 paper.md；兜底取 deliverables 下排除 reviews/citations 的最新 .md。"""
    primary = deliverables / "paper.md"
    if primary.is_file():
        return primary
    try:
        cands = [
            p for p in deliverables.glob("*.md")
            if not re.search(r"(reviews|citations)\.md$", p.name)
        ]
    except OSError:
        return None
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _latest_run_dir(workspace: Path) -> Path | None:
    """workspace 下最新的 research-runs/<主题>/ 目录（按 mtime）。"""
    runs = [p for p in workspace.glob("research-runs/*") if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def _map_deliverables(workspace: Path) -> bool:
    """把 famou 产物搬进 RCB 的 report/ 布局。返回是否成功写出非空 report/report.md。

    步骤：找最新 run → 选 paper → 拷成 report/report.md（重写图链接）→ 把 run 下所有 *.png 拷进 report/images/。
    全程不抛裸异常（文件操作失败也只让最终自检判为「无 report」）。
    """
    report_dir = workspace / "report"
    images_dir = report_dir / "images"
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    run_dir = _latest_run_dir(workspace)
    if run_dir is None:
        return False

    paper = _pick_paper(run_dir / "deliverables")
    if paper is not None and paper.is_file():
        try:
            md = paper.read_text(encoding="utf-8", errors="replace")
            (report_dir / "report.md").write_text(_rewrite_fig_links(md), encoding="utf-8")
        except OSError:
            pass

    # run 目录下所有 PNG（图无论落在 figures/ 还是别处）拷进 report/images/
    for png in run_dir.rglob("*.png"):
        try:
            shutil.copy2(png, images_dir / png.name)
        except OSError:
            continue

    report_md = report_dir / "report.md"
    return report_md.is_file() and report_md.stat().st_size > 0


def _run_famou(workspace: Path, prompt: str) -> int:
    """子进程跑 famou（非交互）。返回子进程退出码。

    用 `sys.executable -m famou_scientist run <prompt>` 而非 import：famou 的 run 内部是
    os.execvpe 替换进程映像（见 launcher.launch），**不能在同进程 import 调**，否则会把
    当前进程换成 opencode。`python -m` 一定跑当前解释器里装的那份 famou 包。
    """
    cmd = [sys.executable, "-m", "famou_scientist", "run"]
    model = os.environ.get("FAMOU_RCB_MODEL", "").strip()
    if model:
        cmd += ["-m", model]
    cmd.append(prompt)
    print(f"famou-rcb: launching famou in {workspace}", file=sys.stderr, flush=True)
    try:
        r = subprocess.run(cmd, cwd=str(workspace))
        return r.returncode
    except Exception as exc:  # noqa: BLE001 — 启动失败也要继续走搬运/自检，给上游明确信号
        print(f"famou-rcb: failed to launch famou: {exc!r}", file=sys.stderr)
        return 1


def main(args=None) -> int:
    """`famou_rcb.py -w <WORKSPACE>` 入口。"""
    if args is None:
        args = sys.argv[1:]
    args = list(args)

    workspace = Path(_parse_workspace(args)).resolve()
    if not workspace.is_dir():
        print(f"famou-rcb: workspace not a directory: {workspace}", file=sys.stderr)
        return 2
    instr = workspace / "INSTRUCTIONS.md"
    if not instr.is_file():
        print(f"famou-rcb: {instr} not found (是否在 RCB 任务 workspace 里运行？)", file=sys.stderr)
        return 2

    try:
        prompt = instr.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"famou-rcb: cannot read INSTRUCTIONS.md: {exc!r}", file=sys.stderr)
        return 2

    rc = _run_famou(workspace, prompt)
    print(f"famou-rcb: famou exited rc={rc}", file=sys.stderr, flush=True)

    ok = _map_deliverables(workspace)
    if ok:
        report_md = workspace / "report" / "report.md"
        n_img = len(list((workspace / "report" / "images").glob("*"))) if (workspace / "report" / "images").is_dir() else 0
        print(
            f"famou-rcb: report/report.md OK ({report_md.stat().st_size} bytes, {n_img} image(s))",
            file=sys.stderr,
        )
        return 0
    print(
        "famou-rcb: WARNING no report/report.md produced — scorer will report 'No report found'",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
