# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""`famou-scientist web` —— 一键起 Web 研究台（后端 opencode serve + 零构建前端）。

和 `famou-scientist`(TUI)、`famou-scientist serve`、`famou-scientist trace` 同一条命令线。
本模块做三件事：

1. 起**后端**：`opencode serve`，用 ``launcher.build_env()`` 注入插件资产环境
   （OPENCODE_CONFIG_DIR / ARC_ROOT / ARC_PYTHON），所以后端加载 AGENTS.md / skill / tool / hook
   ——和 TUI 完全同一套能力。退到内部端口（默认 4097，无需 SSH 转发）。
2. 起**前端**：随包分发的零构建 Node 服务（assets/web/server.mjs），占对外端口
   （默认 4096，用户通常已转发的口），把 ``/oc`` 反代到内部后端。前端零构建：浏览器从 CDN 拉
   React + Babel 在浏览器内转译，无需 npm install（首屏需联网）。
3. 守着两个子进程；Ctrl+C 或任一退出时，killpg 收尾，不留残留。

后端 cwd 沿用用户当前工作目录（``research-runs/`` 落在那里，与 launcher「不改 cwd」一致）。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import launcher

__all__ = ["web_assets_dir", "serve_web", "main"]


def web_assets_dir() -> Path:
    """随包分发的前端资产目录（assets/web，含 server.mjs / public / src）。"""
    return launcher.assets_dir() / "web"


def _wait_backend(oc_port: int, timeout: float = 60.0, proc: "subprocess.Popen | None" = None,
                  host: str = "127.0.0.1") -> bool:
    """轮询后端 serve 是否就绪——用**原始 TCP 连接**，不用 HTTP。

    关键：``urllib`` 会读 ``ALL_PROXY``/``HTTPS_PROXY`` 等环境代理，连 ``127.0.0.1`` 也可能被
    误导到代理服务器（代理回不到本机回环）→ 后端明明在听却永远"未就绪"。原始 socket 连接
    天然绕开代理。能 accept 即视为就绪（opencode 一旦接受 TCP，HTTP 也已可用）。

    传入 ``proc`` 时，发现后端进程已退出就立刻放弃（不傻等到超时）。
    """
    deadline = time.time() + timeout
    waited = 0.0
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False  # 后端进程已退出，别再等
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex((host, oc_port)) == 0:
                return True
        time.sleep(0.5)
        waited += 0.5
        if waited and waited % 10 == 0:
            print(f"[famou-web] 等待后端就绪…（{int(waited)}s）", flush=True)
    return False


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """该端口本机是否已有监听者（连得上即视为占用）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _find_free_port(start: int, host: str = "127.0.0.1", avoid: "set[int] | None" = None,
                    span: int = 200) -> int | None:
    """从 ``start`` 往上找第一个空闲端口（跳过 ``avoid`` 集合）。找不到返回 None。"""
    avoid = avoid or set()
    for p in range(start, min(start + span, 65536)):
        if p in avoid or _port_in_use(p, host):
            continue
        return p
    return None


def _interactive() -> bool:
    """stdin/stdout 是否都是交互式终端（决定撞端口时是询问还是静默自动避让）。"""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _prompt_ports(req_web: int, req_oc: int, auto_web: int, auto_oc: int, *, read=input):
    """撞端口时交互式询问。回车=用自动空闲口；输入端口号=用作前端口（后端自动取相邻空闲）；q=退出。

    Returns:
        (web_port, oc_port) 或 None（用户退出）。
    """
    print(f"[famou-web] ⚠️ 端口被占用：前端 {req_web} 或 后端 {req_oc} 已被占（同机/容器 --network host 常见）。",
          flush=True)
    print(f"  • 回车  → 自动用空闲端口：前端 {auto_web} / 后端 {auto_oc}")
    print(f"  • 端口号 → 用作前端口（如 5000；后端自动取相邻空闲口）")
    print(f"  • q     → 退出")
    while True:
        try:
            ans = read("  选择 ▸ ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if ans == "":
            return (auto_web, auto_oc)
        if ans in ("q", "quit", "exit"):
            return None
        if ans.isdigit():
            w = int(ans)
            if not (1 <= w <= 65535):
                print("  端口需在 1–65535，重输")
                continue
            if _port_in_use(w):
                print(f"  {w} 也被占用了，换一个")
                continue
            o = _find_free_port(req_oc, avoid={w})
            if o is None:
                print("  附近找不到空闲后端口，换个前端口")
                continue
            return (w, o)
        print("  请输入端口数字 / 回车 / q")


def _opencode_data_dir(env: dict) -> Path:
    """opencode 会话库所在目录：$XDG_DATA_HOME/opencode 或 $HOME/.local/share/opencode。"""
    xdg = env.get("XDG_DATA_HOME")
    if xdg:
        base = Path(xdg).expanduser()
    else:
        base = Path(env.get("HOME") or str(Path.home())) / ".local" / "share"
    return base / "opencode"


def _network_fs_type(path: Path) -> str | None:
    """若 path（或其最近的已存在父目录）落在网络/共享文件系统上，返回 fstype，否则 None。"""
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        target = os.path.realpath(str(p))
        mounts = Path("/proc/mounts").read_text().splitlines()
    except Exception:
        return None
    best = None  # (mountpoint_len, fstype)
    for line in mounts:
        parts = line.split()
        if len(parts) < 3:
            continue
        mp, fstype = parts[1], parts[2]
        if target == mp or target.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) > best[0]:
                best = (len(mp), fstype)
    if best and any(best[1].startswith(pfx) for pfx in ("nfs", "cifs", "9p", "fuse")):
        return best[1]
    return None


def _terminate(proc: subprocess.Popen | None) -> None:
    """终止子进程整个进程组（detached 后端/前端各自成组），尽力而为。"""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


def _inject_egress_proxy(env: dict, *, verbose: bool = True) -> bool:
    """把 egress 正向代理注入 env（**原地修改**，前后端共享）；返回是否注入了代理。

    跳板机直连外网极慢/不通（实测拉 arXiv PDF 直连 ~45s 撞超时，经代理 ~0.6s）。前端 server.mjs
    的 /paper 全文 + /_esm CDN 镜像要它；后端 agent 的 Python 工具（走 urllib）也要它。凭证只从
    环境读（HTTPS_PROXY/ALL_PROXY，或本机私有 FAMOU_EGRESS_PROXY）——**不落盘、不进 git**。
    只在**确实配置了代理**时才生效；没配则一切照旧（不改默认直连行为）。
    NO_PROXY 通用放行：本机环回 + 所有**内部网关**（扫 *_BASE_URL / *GATEWAY* 环境变量的 host）——
    LLM / judge 等网关调用必须直连，**绝不能塞进 egress 代理**，否则打挂。

    verbose=False 时不打印（供脚本/后台启动时静默）。
    """
    _egress = (
        env.get("HTTPS_PROXY") or env.get("https_proxy")
        or env.get("ALL_PROXY") or env.get("all_proxy")
        or env.get("FAMOU_EGRESS_PROXY")
    )
    if _egress:
        import urllib.parse as _urlparse
        _bypass = ["127.0.0.1", "localhost", "::1"]
        for _k, _v in env.items():
            ku = _k.upper()
            if not (ku.endswith("_BASE_URL") or "GATEWAY" in ku or ku.endswith("_API_BASE")):
                continue
            try:
                _h = _urlparse.urlparse(_v if "://" in (_v or "") else "http://" + (_v or "")).hostname
            except Exception:
                _h = None
            if _h and _h not in _bypass:
                _bypass.append(_h)
        _old_np = env.get("NO_PROXY") or env.get("no_proxy") or ""
        _np = ",".join(([_old_np] if _old_np else []) + _bypass)
        # 后端 Python 工具：urllib 认 http_proxy/https_proxy（不认 all_proxy），故都设上。
        for _k, _v in (("HTTPS_PROXY", _egress), ("https_proxy", _egress),
                       ("HTTP_PROXY", _egress), ("http_proxy", _egress),
                       ("NO_PROXY", _np), ("no_proxy", _np)):
            env[_k] = _v
        if verbose:
            print("[famou-web] egress 经正向代理（文献全文 / CDN / 会议类文件下载走代理；"
                  f"LLM 等内部网关 + 本机环回直连，NO_PROXY={_np}）", flush=True)
        return True
    if verbose:
        print(
            "[famou-web] ⚠️ 未检测到 egress 代理（HTTPS_PROXY / ALL_PROXY / FAMOU_EGRESS_PROXY 均未设）；"
            "若本机不能直连外网，文献全文 / CDN 依赖 / 会议类文件下载会很慢甚至失败。"
            "可在启动前 export FAMOU_EGRESS_PROXY=http://用户:密码@主机:端口",
            flush=True,
        )
    return False



def serve_web(
    web_port: int = 4096,
    oc_port: int = 4097,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    auto_port: bool = True,
    bs: bool = False,
) -> int:
    """起后端 + 前端，阻塞守护直到 Ctrl+C 或任一子进程退出。

    Args:
        web_port: 前端对外端口（浏览器/SSH 转发的就是它）。
        oc_port: 后端 opencode serve 内部端口（前端代理目标，无需转发）。
        host: 前端绑定地址；默认 127.0.0.1 仅本机。0.0.0.0 对外（会话含对话内容，谨慎）。
        open_browser: 是否自动打开浏览器。
        auto_port: 端口被占用时自动往上找空闲端口（默认开）。关掉则占用即报错退出。
        bs: 消融实验模式——启动前断外网（仅留百度专线），进程退出（含 Ctrl+C/异常/信号）
            时恢复。逻辑复用 ``bs_toggle``，与 TUI 的 ``--bs``（``bs_toggle.run()``）共享同一套
            断/复网原语，但这里由 ``serve_web`` 自己管两个子进程的生命周期，故只借用
            ``toggle_off``/``install_restore_guard``/``restore_now`` 三个原语，不复用 ``run()``。

    Returns:
        退出码（0 正常）。
    """
    opencode = shutil.which("opencode")
    if not opencode:
        print(
            "✗ 未找到 opencode 可执行文件。请先安装：npm i -g opencode-ai\n"
            "  然后 opencode auth login 配好一个模型。",
            file=sys.stderr,
        )
        return 127
    node = shutil.which("node")
    if not node:
        print(
            "✗ 未找到 node。Web 研究台的零构建前端需要 Node.js（opencode 本身也依赖它）。\n"
            "  装好 node 后重试。",
            file=sys.stderr,
        )
        return 127
    server_mjs = web_assets_dir() / "server.mjs"
    if not server_mjs.exists():
        print(f"✗ 找不到前端资产：{server_mjs}（包损坏？重装 famou-scientist）。", file=sys.stderr)
        return 1

    if bs:
        from . import bs_toggle

        ready, script = bs_toggle.script_ready()
        if not ready:
            print(
                f"✗ --bs 需要网络切换脚本，但未找到或不可执行：{script}\n"
                "  可通过环境变量 FAMOU_TOGGLE_NETWORK_SCRIPT 指定实际路径。",
                file=sys.stderr,
            )
            return 1
        bs_toggle.install_restore_guard()
        if not bs_toggle.toggle_off():
            print("✗ 断网失败，取消启动（避免造成'看似隔离但实际仍联网'的假实验条件）。", file=sys.stderr)
            return 1

    project_root = Path.cwd().resolve()
    workspace_root = project_root / ".famou" / "workspaces"

    # Web 与 TUI 必须使用同一套 OpenCode 配置自愈。否则图片附件限制只在 TUI 生效，
    # Web 长任务读取生成图时仍可能把超大 base64 送进网关。
    try:
        from . import config_heal

        config_heal.heal_config()
    except Exception:  # noqa: BLE001 — 自愈失败不能阻断 Web 启动
        pass
    env = launcher.build_env()

    # ── egress 正向代理（前后端共享）─────────────────────────────────────────────
    # 详见 _inject_egress_proxy 文档；凭证只从环境读、不落盘、只在配了代理时生效。
    _inject_egress_proxy(env)
    # ───────────────────────────────────────────────────────────────────────────

    # 端口预检 + 避让：被占用时——交互式终端**先问你**（回车用自动空闲口 / 自己输端口 / q 退出），
    # 非交互（脚本/headless）才静默自动避让。换到自己独立端口既起得来，又不会串到别人的后端/会话。
    if auto_port:
        req_web, req_oc = web_port, oc_port
        auto_oc = _find_free_port(oc_port)
        auto_web = _find_free_port(web_port, avoid={auto_oc} if auto_oc else None)
        if auto_oc is None or auto_web is None:
            print("✗ 附近找不到空闲端口（200 个都被占？）。请手动指定：famou-scientist web --port <P> --oc-port <Q>。",
                  file=sys.stderr)
            return 1
        if (auto_web, auto_oc) != (req_web, req_oc):  # 发生了占用
            if _interactive():
                chosen = _prompt_ports(req_web, req_oc, auto_web, auto_oc)
                if chosen is None:
                    print("[famou-web] 已取消。")
                    return 0
                web_port, oc_port = chosen
            else:
                web_port, oc_port = auto_web, auto_oc
                print(
                    f"[famou-web] ⚠️ 原端口被占用，自动改用空闲端口："
                    f"前端 {req_web}→{web_port}，后端 {req_oc}→{oc_port}"
                    f"（跳板机记得转发新前端口 {web_port}；想固定用 --port/--oc-port）",
                    flush=True,
                )
        else:
            web_port, oc_port = auto_web, auto_oc  # 没占用，原样
    else:
        # 严格模式：占用即报错退出（--no-auto-port）
        for label, port in (("后端 oc-port", oc_port), ("前端 port", web_port)):
            if _port_in_use(port):
                print(
                    f"✗ {label} {port} 已被占用。\n"
                    f"  多半是同机/同节点上已有另一个 famou 在跑（尤其容器用了 --network host，\n"
                    f"  此时整节点共用一套 127.0.0.1 端口）。若继续，你会**连到别人的后端、看到别人的会话**。\n"
                    f"  解决：换唯一端口启动 —— famou-scientist web --port <P> --oc-port <Q>；\n"
                    f"  或去掉 --no-auto-port 让它自动避让；或容器别用 --network host。",
                    file=sys.stderr,
                )
                return 1

    # 会话存储位置（让用户看清各存各的）；落在 NFS/共享盘会告警，否则可能多容器共用一个库。
    data_dir = _opencode_data_dir(env)
    print(f"[famou-web] 会话/数据目录：{data_dir}", flush=True)
    netfs = _network_fs_type(data_dir)
    if netfs:
        print(
            f"[famou-web] ⚠️ 该目录在网络/共享文件系统({netfs})上——多容器若挂载同一份会**共用会话库**。\n"
            f"  想各存各的：设 FAMOU_DATA_DIR 指到各自**私有**目录（容器本地盘，非 CFS/NFS）。",
            file=sys.stderr,
        )

    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    tracesync: subprocess.Popen | None = None
    backend_log = None
    try:
        # 1. 后端：opencode serve（注入资产环境），独立进程组便于整组收尾。
        #    注意：opencode 新版 serve 会在 :{oc_port} 上**自带一个 opencode 原生 web 页面**，
        #    并打印 "opencode server listening on http://127.0.0.1:{oc_port}"——这会**误导**用户去开后端口、
        #    看到的是 opencode 自己的界面而非 Famou 研究台。故把后端输出重定向到日志文件，不让那行 URL 抢戏。
        backend_log_path = project_root / ".famou" / "logs" / f"famou-web-backend-{oc_port}.log"
        backend_log_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[famou-web] 启动后端（内部 API，仅本机 127.0.0.1:{oc_port}）… 日志：{backend_log_path}", flush=True)
        backend_log = open(backend_log_path, "w")
        backend = subprocess.Popen(
            [opencode, "serve", "--port", str(oc_port), "--hostname", "127.0.0.1"],
            env=env,
            cwd=project_root,
            start_new_session=True,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
        )
        if not _wait_backend(oc_port, proc=backend):
            print("✗ 后端 serve 未在预期时间内就绪，放弃。后端日志末尾：", file=sys.stderr)
            try:
                print(backend_log_path.read_text(errors="replace")[-2000:], file=sys.stderr)
            except Exception:
                pass
            return 1

        # 2. 前端：零构建 Node 服务（这才是 Famou 研究台）
        web_url = f"http://localhost:{web_port}"
        if host == "0.0.0.0":
            print(f"[famou-web] ⚠️ 前端绑定 0.0.0.0（对外可达）——会话含对话内容，注意访问控制。")
            if not os.environ.get("FAMOU_ACCESS_PASSWORD"):
                print("[famou-web] ⚠️ 未设 FAMOU_ACCESS_PASSWORD：任何人可直接访问。"
                      "建议 export FAMOU_ACCESS_PASSWORD=<口令> 开启登录墙。")
        front_env = dict(env)
        front_env["PORT"] = str(web_port)
        front_env["HOST"] = host
        front_env["OC_TARGET"] = f"http://127.0.0.1:{oc_port}"
        front_env["FAMOU_PROJECT_ROOT"] = str(project_root)
        front_env["FAMOU_WORKSPACE_ROOT"] = str(workspace_root)
        # 注：egress 代理 + NO_PROXY 已在上面注入到共享 env，front_env 直接继承——
        # server.mjs 的 proxyEnv() 据此为 /paper 全文 + CDN 镜像走 HTTP CONNECT 隧道，
        # 本机环回（/oc）由 NO_PROXY 放行（且 /oc 转发本就不经 egress，双保险）。
        frontend = subprocess.Popen(
            [node, str(server_mjs)],
            env=front_env,
            cwd=project_root,
            start_new_session=True,
        )

        # 2.5 轨迹转存（可选·零侵入）：把本容器 opencode.db 定期一致快照到 CFS 的**每容器独立**
        #     路径，供事后收集分析、迭代改进。设 FAMOU_TRACE_OFF=1 关闭；FAMOU_TRACE_DEST 改目标根。
        #     它是独立进程，只读源库、只写 CFS，不碰后端/前端；退出时随 _terminate 一并收尾
        #     （收到 SIGTERM 会 force 兜底同步一次）。启动失败绝不影响研究台主流程。
        if os.environ.get("FAMOU_TRACE_OFF", "").strip().lower() not in ("1", "true", "yes", "on"):
            trace_sync_mjs = web_assets_dir() / "trace-sync.mjs"
            if trace_sync_mjs.exists():
                try:
                    trace_env = dict(env)
                    trace_env["FAMOU_TRACE_DB"] = str(data_dir / "opencode.db")
                    tracesync = subprocess.Popen(
                        [node, str(trace_sync_mjs)],
                        env=trace_env,
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    print(
                        f"[famou-web] 轨迹转存已启动 → {trace_env.get('FAMOU_TRACE_DEST', '默认 CFS 路径')}"
                        f"（关闭：设 FAMOU_TRACE_OFF=1）",
                        flush=True,
                    )
                except Exception as e:  # noqa: BLE001 — 转存是可选增值，任何失败都不该拖垮研究台
                    print(f"[famou-web] 轨迹转存启动失败（忽略）：{e}", file=sys.stderr)

        if open_browser:
            try:
                webbrowser.open(web_url)
            except Exception:
                pass

        # 显著提示开哪个口（避免开成 opencode 自带的后端页面）
        bar = "─" * 60
        print("\n" + bar)
        print(f"  ✅ Famou 研究台 → {web_url}    ← 浏览器开这个")
        print(f"  ⛔ {oc_port} 是内部后端（opencode 自带页面），别直接打开")
        print(f"  跳板机：把本地某端口转发到服务器 {web_port}，再开本地那个口")
        print(bar + "\n", flush=True)

        # 3. 守护：任一子进程退出即收尾
        while True:
            for name, p in (("后端 serve", backend), ("前端", frontend)):
                rc = p.poll()
                if rc is not None:
                    print(f"[famou-web] {name} 退出（rc={rc}），停止研究台。")
                    return rc or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[famou-web] 收到 Ctrl+C，停止后端与前端 …")
        return 0
    finally:
        _terminate(tracesync)
        _terminate(frontend)
        _terminate(backend)
        if backend_log is not None:
            try:
                backend_log.close()
            except Exception:
                pass
        if bs:
            from . import bs_toggle

            bs_toggle.restore_now()


def main(argv: list[str] | None = None) -> int:
    """`famou-scientist web` 入口（参数解析 + 起服务）。"""
    ap = argparse.ArgumentParser(
        prog="famou-scientist web",
        description="起 Web 研究台：后端 opencode serve（注入插件资产）+ 零构建前端。",
    )
    ap.add_argument("--port", type=int, default=4096, help="前端对外端口（默认 4096）")
    ap.add_argument("--oc-port", type=int, default=4097, help="后端 serve 内部端口（默认 4097）")
    ap.add_argument("--host", default="127.0.0.1", help="前端绑定地址（默认 127.0.0.1 仅本机；0.0.0.0 对外）")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--no-auto-port", action="store_true",
                    help="端口被占用时直接报错退出（默认会自动往上找空闲端口）")
    ap.add_argument("--bs", action="store_true",
                    help="消融实验模式：启动前断外网仅留百度专线，退出（含 Ctrl+C/异常）时恢复")
    ns = ap.parse_args(argv)
    return serve_web(
        web_port=ns.port,
        oc_port=ns.oc_port,
        host=ns.host,
        open_browser=not ns.no_open,
        auto_port=not ns.no_auto_port,
        bs=ns.bs,
    )
