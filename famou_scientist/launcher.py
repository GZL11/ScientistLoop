# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""定位插件资产、注入环境变量、拉起 OpenCode 研究台。

设计：famou-scientist 是 OpenCode 的能力插件。本模块负责把随包分发的资产
（assets/opencode/ —— 含 opencode.json / AGENTS.md / tool / plugins / skill /
scripts）告诉 OpenCode，然后用 ``os.execvp`` 把当前进程替换为 ``opencode``。

关键机制（均经实测确认，见 docs）：
- ``OPENCODE_CONFIG_DIR`` 指向资产目录 → OpenCode 从中加载 opencode.json、
  AGENTS.md（instructions）、28 个 skill、tool/arc.ts、plugins/guardrails.ts��
- ``ARC_ROOT`` / ``ARC_PYTHON`` 注入给 tool/hook 的 TS 外壳 → 它们据此定位
  自包含的 Python 内核（scripts/*.py）与执行实验用的解释器。
- 新研究默认进入独立 cwd：每个新会话在启动目录下分配 ``.famou/workspaces/<id>/``，
  避免不同 session 的 ``research-runs/``、上传文件和临时产物相互串目录；OpenCode 会话库
  仍按 ``XDG_DATA_HOME/opencode/opencode.db`` 集中存放。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

__all__ = [
    "assets_dir",
    "opencode_config_dir",
    "build_env",
    "has_existing_session_arg",
    "make_session_workspace",
    "sync_baidu_search_instruction",
    "launch",
]


def assets_dir() -> Path:
    """返回随包分发的 assets 目录绝对路径。

    资产与本模块同包（famou_scientist/assets/），用 ``__file__`` 定位即可，
    无论包安装在 site-packages 还是以 ``-e`` 可编辑模式安装都成立。
    """
    return Path(__file__).resolve().parent / "assets"


def opencode_config_dir() -> Path:
    """资产里那个充当 OpenCode config dir 的目录（assets/opencode）。"""
    return assets_dir() / "opencode"


def build_env(base: dict | None = None) -> dict:
    """构造拉起 OpenCode 所需的环境变量（在调用方环境基础上叠加）。

    Args:
        base: 基础环境，默认 ``os.environ``。

    Returns:
        新的环境字典（不原地修改入参）。
    """
    env = dict(os.environ if base is None else base)
    cfg_dir = opencode_config_dir()

    # OpenCode 从此目录加载 opencode.json / AGENTS.md / tool / plugins / skill。
    env["OPENCODE_CONFIG_DIR"] = str(cfg_dir)

    # tool/hook 的 TS 外壳据此定位自包含 Python 内核（scripts/）。
    # 注意：ARC_ROOT 指向 config dir 自身（scripts 在其下），不是用户工作区。
    env["ARC_ROOT"] = str(cfg_dir)

    # 执行实验/内核脚本用的 python3：优先复用当前解释器，保证版本一致。
    env.setdefault("ARC_PYTHON", sys.executable or shutil.which("python3") or "python3")

    # 会话存储隔离：opencode 把所有会话存在 $XDG_DATA_HOME/opencode/opencode.db
    # （未设则 $HOME/.local/share/opencode）。多人同机/同节点（尤其 --network host）时，
    # 想各存各的，设 FAMOU_DATA_DIR 指到**各自私有**目录即可（别指到 NFS/CFS 共享盘，否则照样共用）。
    famou_data = env.get("FAMOU_DATA_DIR")
    if famou_data:
        env["XDG_DATA_HOME"] = str(Path(famou_data).expanduser())

    # 只用本插件自带的 skill，屏蔽用户 ~/.claude 里的 skill 干扰研究流程。
    env.setdefault("OPENCODE_DISABLE_CLAUDE_CODE_SKILLS", "1")

    # OpenCode only exposes the native websearch tool to non-opencode providers
    # when a websearch backend flag is enabled. Famou relies on native
    # websearch/webfetch for lightweight paper lookup, so enable Exa by default
    # while still allowing callers to override the flag in their shell.
    env.setdefault("OPENCODE_ENABLE_EXA", "1")

    # 百度搜索工具（arc_web_search）默认不注册（tool/arc.ts 里未设 AI_SEARCH_KEY 时该
    # export 为 undefined，opencode 的工具发现会跳过它）。但 AGENTS.md 是静态文件、跟
    # 工具是否真的注册完全脱钩——若仍在其中描述这个工具，agent 会"读到"一个实际不存在
    # 的工具名。做法：把这段描述从 AGENTS.md 主文抽到一个单独的、每次启动按开关状态
    # 重新生成的 include 文件（_generated_baidu_search.md，已在 opencode.json 的
    # instructions 里列出、且已加进 .gitignore）——没配 key 就写空，配了就写真实描述，
    # 让 agent 看到的文档跟工具实际可用性始终一致。
    sync_baidu_search_instruction(cfg_dir, enabled=bool(env.get("AI_SEARCH_KEY")))

    return env


def has_existing_session_arg(args: list[str] | None) -> bool:
    """判断这次启动是否是在续已有会话。

    续会话不能贸然切到新 workspace，否则老会话里相对路径会失效；新研究才分配独立 cwd。
    """
    if not args:
        return False
    existing_flags = {"--session", "-s", "--continue", "--resume"}
    for arg in args:
        if arg in existing_flags:
            return True
        if arg.startswith("--session="):
            return True
    return False


def make_session_workspace(base: Path | str | None = None, *, label: str = "session") -> Path:
    """在启动目录下创建一个新的 session workspace。

    Args:
        base: workspace 根目录；默认是当前 cwd 下的 ``.famou/workspaces``。
        label: 目录名前缀，仅用于可读性。

    Returns:
        已创建好的绝对路径。
    """
    root = Path(base).expanduser() if base is not None else Path.cwd() / ".famou" / "workspaces"
    root = root.resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in label).strip("-") or "session"
    for _ in range(10):
        name = f"{ts}-{safe_label}-{uuid4().hex[:8]}"
        path = root / name
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"无法创建 session workspace: {root}")


def sync_baidu_search_instruction(cfg_dir: Path, *, enabled: bool) -> None:
    """按 ``enabled`` 重新生成百度搜索工具的 AGENTS 补充说明（见 ``build_env`` 里的注释）。

    Args:
        cfg_dir: OpenCode config dir（``assets/opencode``），源模板与生成文件都在其下。
        enabled: 是否已配置 ``AI_SEARCH_KEY``（决定生成文件写真实描述还是写空）。

    异常静默：这是锦上添花的一致性同步，写失败不该阻断启动——顶多是文档描述与工具实际
    可用性短暂不一致，不是功能性故障。
    """
    try:
        generated = cfg_dir / "_generated_baidu_search.md"
        if enabled:
            template = cfg_dir / "_baidu_search_snippet.md"
            generated.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            generated.write_text("", encoding="utf-8")
    except OSError:
        pass


def launch(extra_args: list[str] | None = None, *, isolate_cwd: bool | None = None) -> int:
    """用 execvp 把当前进程替换为 opencode TUI。

    Args:
        extra_args: 透传给 opencode 的额外参数（如 ``--model xxx``）。
        isolate_cwd: 是否给本次新研究分配独立 cwd；None 表示自动判断（续会话不切）。

    Returns:
        仅在 execvp 失败时返回非 0；成功时进程已被替换，不会返回。
    """
    opencode = shutil.which("opencode")
    if not opencode:
        # 正常情况下 doctor 已先行拦截；这里兜底，防止被直接调用。
        print(
            "✗ 未找到 opencode 可执行文件。请先安装：npm i -g opencode-ai\n"
            "  然后 opencode auth login 配好一个模型。",
            file=sys.stderr,
        )
        return 127

    argv = ["opencode"]
    if extra_args:
        argv.extend(extra_args)

    # 自愈：给自定义 provider 模型回填缺失的 limit.context（防 auto-compact 不触发、
    # 长会话上下文撑爆）。锦上添花、异常静默，绝不阻断启动。
    try:
        from . import config_heal

        config_heal.heal_config()
    except Exception:  # noqa: BLE001
        pass

    env = build_env()
    if isolate_cwd is None:
        isolate_cwd = not has_existing_session_arg(extra_args)
    if isolate_cwd:
        workspace = make_session_workspace()
        print(f"[famou] 本次研究 workspace：{workspace}", flush=True)
        os.chdir(workspace)
    # execvpe：替换进程映像，opencode 接管终端（真正的 TUI 体验）。
    os.execvpe(opencode, argv, env)
    # execvpe 成功则不会执行到这；执行到说明失败。
    return 1  # pragma: no cover
