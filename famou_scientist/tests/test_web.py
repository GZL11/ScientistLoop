# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""Web 研究台相关单元测试：命令分发、端口预检和数据目录解析。

除显式 socket 用例外均可离线判定，不启动真实 Web 或 OpenCode 服务。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import socket
from pathlib import Path

from famou_scientist import launcher, web


def test_web_dispatches_slash_commands_to_opencode_command_api():
    """Web 输入框应把 /goal 等命令交给 command API，而不是当普通消息发送。"""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")

    assert "function parseSlashCommand(text)" in source
    assert 'fetch(OC + "/command")' in source
    assert '"/session/" + sessionID + "/command"' in source
    assert "sendCommand(sid, slashCommand.command, slashCommand.arguments)" in source
    assert '"command.executed"' in source
    assert 'className="slash-menu"' in source
    assert "menu.scrollTop = itemBottom - menu.clientHeight + 6" in source
    assert "inferCommandDisplay(raw, commands)" in source



def test_permission_recovery_prefers_current_opencode_api():
    """OpenCode 1.18 的 /permission 应先于旧版 v2 fallback，避免每 4 秒产生 schema rejection。"""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")
    start = source.index("async function listPendingPermissions")
    end = source.index("// 本地编译论文", start)
    block = source[start:end]

    assert block.index('OC + "/permission"') < block.index(
        'OC + "/api/session/" + sessionID + "/permission/request"'
    )
    assert "return a.filter((p) => !p.sessionID || p.sessionID === sessionID)" in block


def test_session_status_query_is_workspace_scoped():
    """状态接口必须带 session 目录，否则 workspace session 会被误判为没有状态。"""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")

    assert 'getSessionStatus(sessionID, directory = "")' in source
    assert 'withDirectory(OC + "/session/status", directory)' in source
    assert '"x-famou-session-id": sessionID' in source
    assert "getSessionStatus(sid, directory)" in source


def test_chat_distinguishes_waiting_for_agent_from_active_processing():
    """首个可见输出前只展示真实连接状态，不假装 Agent 已经开始思考。"""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")

    assert '"请求已提交，等待模型响应…"' in source
    assert '"研究助手正在处理…"' in source
    assert 'runtimeStatus.type === "submitted"' in source
    assert 'case "session.next.text.started":' in source






def test_workspace_root_is_session_cwd_not_message_derived():
    """Workspace root must be the persisted OpenCode session cwd."""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")

    assert "function deriveRunDir" not in source
    assert "const currentWorkspaceDir = currentSessionDir ||" in source
    assert "workspaceDir={currentWorkspaceDir}" in source
    assert 'workspaceDir.replace(/\\/+$/, "") + "/research-runs"' in source
    assert "loadRunDir(" not in source
    assert "saveRunDir(" not in source
    assert "res.status >= 500 || res.status === 404" in source


def test_new_web_session_workspace_is_an_independent_git_root():
    """OpenCode must resolve the allocated session directory as its worktree."""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "server.mjs"
    ).read_text(encoding="utf-8")
    start = source.index("async function allocateWorkspace")
    end = source.index("function sessionIDFromPath", start)
    block = source[start:end]

    assert 'execFile("git", ["init", "--quiet", dir]' in block
    assert block.index('execFile("git"') < block.index("return dir")
    create_start = source.index("async function proxyCreateSession")
    create_end = source.index("// Proxy /oc/*", create_start)
    create_block = source[create_start:create_end]
    assert 'const workspace = await allocateWorkspace(body.title || "新对话")' in create_block
    assert "requestedWorkspace" not in create_block
    assert "delete upstreamBody.famouWorkspace" in create_block


def test_process_panel_uses_one_canonical_status_per_experiment_job():
    """Heartbeat messages stay internal; the Process panel renders backend job state once."""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")

    assert "function heartbeatProcEvent" not in source
    assert 'id: "process-" + job.job_id' in source
    assert 'const visibleEvents = events.filter((e) => e.kind !== "experiment")' in source
    assert "visibleEvents.map((e) => <ProcRow" in source


def test_process_api_synthesizes_terminal_progress_without_snapshot():
    """A failed/done job remains visible even when heartbeat never wrote progress.json."""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "server.mjs"
    ).read_text(encoding="utf-8")
    start = source.index("async function serveProcessProgress")
    end = source.index("function serveCompile", start)
    block = source[start:end]

    assert 'readFile(join(dir, "result.json"' in block
    assert '["done", "failed", "timed_out", "cancelled", "aborted"].includes(state)' in block
    assert "progress," in block
    assert "progress && progress.updated_at ? progress : null" not in block


def test_heartbeat_wakeups_are_async_and_do_not_wait_for_agent_turns():
    """Accepted wakeups are marked sent without waiting for the full Agent response."""
    root = Path(__file__).parents[1] / "assets" / "opencode"
    for path in (
        root / "plugins" / "heartbeat.ts",
        root / "registry" / "source" / "plugins" / "heartbeat.ts",
    ):
        source = path.read_text(encoding="utf-8")
        assert source.count("client.session.promptAsync(") == 2
        assert "await client.session.prompt({" not in source


def test_chat_streams_only_canonical_message_deltas():
    """Canonical message deltas stream monotonically; candidate streams stay hidden."""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")

    assert "const appendPartDelta = useCallback" in source
    assert "appendPartDelta(evSid, ev.properties || {})" in source
    assert "requestAnimationFrame" in source
    assert 'case "session.next.text.delta":' in source


def test_trailing_internal_messages_keep_assistant_run_visible():
    """A hidden trailing heartbeat must not remove the prior assistant run anchor."""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")
    start = source.index("let isRunEnd = true")
    end = source.index("const runMessages = assistantRun", start)
    block = source[start:end]

    assert "isCompactionContinue(n)" in block
    assert "isInternalSystemNote(txt)" in block

def test_new_session_creation_is_guarded_and_keeps_clicked_project():
    """慢创建请求期间应禁止重复点击，并按点击时的项目持久化归属。"""
    source = (
        Path(__file__).parents[1] / "assets" / "web" / "src" / "app.tsx"
    ).read_text(encoding="utf-8")
    start = source.index("async function newResearch()")
    end = source.index("function switchTo", start)
    block = source[start:end]

    assert "if (creatingSessionRef.current) return" in block
    assert "const targetProject = curProj || UNARCHIVED" in block
    assert "[s.id]: targetProject" in block
    assert "void saveProjectState(nextState)" in block
    assert "disabled={creatingSession}" in source
    assert "创建中…" in source
    assert "新会话创建失败，请稍后重试。" in source


def test_build_env_famou_data_dir_maps_to_xdg():
    env = launcher.build_env({"FAMOU_DATA_DIR": "/tmp/famou_u1"})
    assert env["XDG_DATA_HOME"] == "/tmp/famou_u1"


def test_build_env_no_famou_data_dir_does_not_force_xdg():
    env = launcher.build_env({})
    assert "XDG_DATA_HOME" not in env  # 不设 FAMOU_DATA_DIR 就不强加


def test_build_env_famou_data_dir_expands_user():
    # ~ 按运行时真实 HOME 展开（expanduser 语义）；这里只验证已被展开成绝对路径
    env = launcher.build_env({"FAMOU_DATA_DIR": "~/famoudata"})
    xdg = env["XDG_DATA_HOME"]
    assert "~" not in xdg and xdg.startswith("/") and xdg.endswith("/famoudata")


def test_make_session_workspace_under_base(tmp_path):
    ws = launcher.make_session_workspace(tmp_path, label="paper qa")
    assert ws.is_dir()
    assert ws.parent == tmp_path
    assert "paper-qa" in ws.name


def test_existing_session_args_disable_new_workspace():
    assert launcher.has_existing_session_arg(["--session", "ses_x"]) is True
    assert launcher.has_existing_session_arg(["--session=ses_x"]) is True
    assert launcher.has_existing_session_arg(["--continue"]) is True
    assert launcher.has_existing_session_arg(["--model", "m"]) is False


def test_explore_agent_override_exists():
    p = launcher.opencode_config_dir() / "agent" / "explore.md"
    text = p.read_text(encoding="utf-8")
    assert "mode: subagent" in text
    assert "/tool-output/" in text
    assert "never read the whole file" in text


def test_opencode_data_dir_xdg():
    assert web._opencode_data_dir({"XDG_DATA_HOME": "/x"}) == Path("/x/opencode")


def test_opencode_data_dir_home_default():
    assert web._opencode_data_dir({"HOME": "/home/u"}) == Path("/home/u/.local/share/opencode")


def test_port_in_use_detects_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        assert web._port_in_use(port) is True
    finally:
        s.close()
    # 关闭监听后端口应判为空闲
    assert web._port_in_use(port) is False


def test_network_fs_type_local_path_is_none(tmp_path):
    # 本地/tmpfs 路径不应被判成网络盘（nfs/cifs/9p/fuse）
    assert web._network_fs_type(tmp_path) is None


def test_wait_backend_ignores_proxy(monkeypatch):
    # 守护"后端在听却因代理判不就绪"那个 bug：设黑洞代理，socket 探测仍应判就绪
    import threading

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    threading.Thread(target=lambda: [srv.accept() for _ in range(8)], daemon=True).start()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(var, "http://10.255.255.1:9")  # 指向黑洞，urllib 会卡死
    try:
        assert web._wait_backend(port, timeout=3) is True
    finally:
        srv.close()


def test_wait_backend_short_circuits_on_dead_proc():
    # 后端进程已退出 → 立刻放弃，不傻等到超时
    class _Dead:
        def poll(self):
            return 1

    # 选一个大概率空闲的端口（无监听）；有 proc 死亡判定应快速返回 False
    assert web._wait_backend(59999, timeout=5, proc=_Dead()) is False


def test_find_free_port_returns_start_when_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    free = s.getsockname()[1]
    s.close()  # 立刻释放 → 该端口空闲
    assert web._find_free_port(free) == free


def test_find_free_port_skips_occupied():
    # 占住一个端口，_find_free_port 从它开始应跳到后面的空闲端口
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen()
    taken = s.getsockname()[1]
    try:
        got = web._find_free_port(taken)
        assert got is not None and got != taken and got > taken
    finally:
        s.close()


def test_find_free_port_respects_avoid():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    free = s.getsockname()[1]
    s.close()
    got = web._find_free_port(free, avoid={free})
    assert got is not None and got != free


def test_prompt_ports_enter_uses_auto():
    # 回车 → 用自动空闲端口
    assert web._prompt_ports(4096, 4097, 4099, 4098, read=lambda _p: "") == (4099, 4098)


def test_prompt_ports_quit_returns_none():
    assert web._prompt_ports(4096, 4097, 4099, 4098, read=lambda _p: "q") is None


def test_prompt_ports_eof_returns_none():
    def _raise(_p):
        raise EOFError
    assert web._prompt_ports(4096, 4097, 4099, 4098, read=_raise) is None


def test_prompt_ports_custom_port(monkeypatch):
    # 用户输入自定义前端口 → 校验空闲后，后端取相邻空闲口
    monkeypatch.setattr(web, "_port_in_use", lambda *a, **k: False)  # 自定义口视为空闲
    monkeypatch.setattr(web, "_find_free_port", lambda start, **k: start)  # 后端取 req_oc
    assert web._prompt_ports(4096, 4097, 4099, 4098, read=lambda _p: "5000") == (5000, 4097)


def test_prompt_ports_retries_on_taken_then_auto(monkeypatch):
    # 输入一个被占端口 → 提示重输 → 再回车用自动
    monkeypatch.setattr(web, "_port_in_use", lambda *a, **k: True)  # 任何自定义口都判占用
    it = iter(["6000", ""])  # 先试被占的 6000，再回车
    assert web._prompt_ports(4096, 4097, 4099, 4098, read=lambda _p: next(it)) == (4099, 4098)
