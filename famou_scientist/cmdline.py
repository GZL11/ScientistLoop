# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""命令行入口：体检 → 拉起 OpenCode 研究台。

famou-scientist 是 OpenCode 的科研能力插件。本命令做三件事：
1. 体检（doctor）：确认 opencode / python3 就绪，软提示模型配置。
2. 定位资产 + 注入环境（launcher）：把随包分发的 tool/hook/skill/AGENTS.md
   告诉 OpenCode。
3. 用 execvp 拉起 OpenCode TUI，当前进程被替换，用户进入研究台对话。

用法：
    famou-scientist                 # 体检 → 交互式初始菜单 → 进入研究台
    famou-scientist --no-intro      # 跳过菜单，直达研究台（脚本/老手；FAMOU_NO_INTRO=1 同效）
    famou-scientist --bs            # 消融实验模式：断外网只留百度专线，对比有无外网的科研效果（见 bs_toggle.py）
    famou-scientist --model <m>     # 透传 --model 等参数给 opencode（带参数即跳过菜单）
    famou-scientist web [...]       # 起 Web 研究台（网页对话 + 产物查看；后端 serve + 零构建前端）
    famou-scientist web --bs        # Web 研究台的消融实验模式（同上，断外网只留百度专线）
    famou-scientist serve [...]     # 只起 opencode serve（HTTP/SSE 后端，供前端/脚本接入）
    famou-scientist doctor          # 只体检，不启动
    famou-scientist trace [sid]     # 列会话 / 把某会话轨迹导成 JSONL（只读）
    famou-scientist assets ...      # 查看/校验 prompt、skill、tool、plugin 资产 registry
    famou-scientist agent run ...   # 由外部 benchmark harness 直接托管自主优化循环
    famou-scientist loop ...        # 启动或管理自主科研循环
    famou-scientist --mode loop ... # 兼容参数式启动自主科研循环
    famou-scientist update          # 一键更新到最新代码（git pull；editable 安装即时生效）
    famou-scientist --version       # 打印版本

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import sys

__all__ = [
    "main",
]


def main(args=None):
    """主程序入口。

    Args:
        args: 命令行参数列表（默认从 ``sys.argv`` 读取，去掉程序名）。

    Returns:
        int 退出码，0 表示成功。execvp 成功时进程已被替换、不返回。
    """
    if args is None:
        args = sys.argv[1:]
    args = list(args)

    # --version：直接打印包版本后退出。
    if args and args[0] in ("--version", "-V", "version"):
        from . import __version__
        print(f"famou-scientist {__version__}")
        return 0

    # 子命令 trace：把 opencode 某会话轨迹导成 JSONL / 起 web 可视化（只读，不体检不启动 TUI）。
    if args and args[0] == "trace":
        from .vis import trace
        return trace.main(args[1:])

    # 子命令 assets：本地资产 registry 管理（只读查看/校验/diff；不影响 OpenCode 加载）。
    if args and args[0] == "assets":
        from . import assets
        return assets.main(args[1:])

    # 子命令 update：一键更新到最新代码（git clone + pip install -e . 装的，封装 git pull，像 `claude update`）。
    if args and args[0] == "update":
        from . import updater
        return updater.main(args[1:])

    # 子命令 web：起 Web 研究台（后端 opencode serve + 零构建前端，网页里对话+看产物）。
    if args and args[0] == "web":
        from . import web
        return web.main(args[1:])

    # 子命令 loop：自主科研循环（不依赖 OpenCode TUI 启动）。
    if args and args[0] == "agent":
        from .loop.harness import cli as agent_cli
        return agent_cli.main(args[1:])

    # 子命令 loop：自主科研循环（不依赖 OpenCode TUI 启动）。
    if args and args[0] == "loop":
        from .loop import cli
        return cli.main(args[1:])

    # 兼容旧版 e2e 子命令；运行时和工作空间统一使用 loop 命名。
    if args and args[0] == "e2e":
        from .loop import cli
        return cli.main(args[1:])

    # 参数式入口：--mode loop 为正式名称，e2e 仅作向后兼容。
    if "--mode" in args:
        try:
            mode_idx = args.index("--mode")
            mode = args[mode_idx + 1] if mode_idx + 1 < len(args) else ""
        except ValueError:
            mode = ""
        if mode in {"loop", "e2e"}:
            from .loop import cli
            return cli.run_from_mode_flags(args)
    for arg in args:
        if arg.startswith("--mode=") and arg.split("=", 1)[1] in {"loop", "e2e"}:
            from .loop import cli
            return cli.run_from_mode_flags(args)

    from . import doctor, launcher

    # 子命令 serve：拉起 opencode serve（HTTP/SSE 后端，供 arc-web 等前端通过 /oc 代理接入）。
    # 与 TUI 走同一套资产注入（OPENCODE_CONFIG_DIR / ARC_ROOT / ARC_PYTHON），所以 serve 出来的
    # 后端同样加载 AGENTS.md / skill / tool / hook；剩余参数（--port / --hostname 等）透传给 opencode。
    if args and args[0] == "serve":
        if not doctor.check(verbose=True):
            print(
                "✗ 体检未通过（缺少 opencode）。修复上面标 [✗] 的项后重试。",
                file=sys.stderr,
            )
            return 1
        print("正在拉起 OpenCode serve（HTTP/SSE 后端）……（Ctrl+C 停止）\n")
        # args 以 "serve" 开头 → execvp 成 `opencode serve ...`。
        return launcher.launch(extra_args=args, isolate_cwd=False)

    # 子命令 doctor：只体检，不启动。
    if args and args[0] == "doctor":
        ok = doctor.check(verbose=True)
        if ok:
            print("体检通过，可运行 `famou-scientist` 进入研究台。")
        return 0 if ok else 1

    # 默认：体检 →（交互式 TTY 下）呈现 famou 初始菜单 → 拉起 TUI。
    from . import intro
    clean_args, no_intro, bs = intro.strip_flags_ext(args)

    if not doctor.check(verbose=True):
        print(
            "✗ 体检未通过（缺少 opencode）。修复上面标 [✗] 的项后重试。",
            file=sys.stderr,
        )
        return 1

    if intro.should_show(clean_args, no_intro or bs):
        action, extra = intro.run_menu()
        if action == "quit":
            return 0
        if action == "web":
            from . import web
            return web.main(["--bs"] if bs else [])
        clean_args = extra  # action == "tui"：透传菜单产出的参数（如 --continue）

    # --bs：消融实验模式（断外网只留百度专线），逻辑与主启动路径完全分离，见 bs_toggle.py。
    if bs:
        from . import bs_toggle
        return bs_toggle.run(extra_args=clean_args)

    print("正在拉起 Famou-Scientist 研究台……（输入 /exit 退出）\n")
    # execvp 替换进程：成功则不返回，剩余 args 透传给 opencode。
    return launcher.launch(extra_args=clean_args)
