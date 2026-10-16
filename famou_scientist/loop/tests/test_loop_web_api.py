# -*- coding: UTF-8 -*-
"""Loop Web 只读 API 冒烟测试。

测试会基于临时项目根目录启动真实的零构建 Node 服务。这里验证完整 HTTP
边界，而不只验证 ``loop-api.mjs`` 内部处理器，因为路由与鉴权分类定义在
``server.mjs`` 中。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from famou_scientist.loop import cli


NODE = shutil.which("node")
PACKAGE_DIR = Path(__file__).resolve().parents[2]
SERVER = PACKAGE_DIR / "assets" / "web" / "server.mjs"
GOAL_FILE = Path(__file__).resolve().parent / "fixtures" / "goals" / "dummy_algorithm_innovation.yaml"


def _free_port() -> int:
    """申请并返回一个当前可用的本地端口。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _get_json(base: str, path: str) -> tuple[int, dict]:
    """请求指定 API 并返回状态码和 JSON 响应。"""
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="Node.js is required for the Web server smoke test")
def test_loop_web_read_only_api(tmp_path: Path):
    """验证 Loop Web 只读 API 的路由、数据和路径保护。"""
    try:
        port = _free_port()
    except PermissionError:
        # Some managed test sandboxes disallow AF_INET sockets entirely.  The
        # pure handler is still syntax-tested separately; run this HTTP smoke
        # test in normal developer/CI environments where a local port is
        # available.
        pytest.skip("sandbox does not permit local TCP sockets")

    loop_root = tmp_path / ".famou" / "loop"
    assert cli.main([
        "run",
        "--goal-file",
        str(GOAL_FILE),
        "--root",
        str(loop_root),
        "--max-ticks",
        "5",
        "--reinit",
    ]) == 0

    env = os.environ.copy()
    env.pop("FAMOU_ACCESS_PASSWORD", None)
    env.update({
        "FAMOU_PROJECT_ROOT": str(tmp_path),
        "FAMOU_WORKSPACE_ROOT": str(tmp_path / ".famou" / "workspaces"),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "OC_TARGET": "http://127.0.0.1:1",
    })
    proc = subprocess.Popen(
        [NODE, str(SERVER)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 10
        while True:
            try:
                code, data = _get_json(base, "/loop/goals")
                if code == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                if proc.poll() is not None:
                    output = proc.stdout.read() if proc.stdout else ""
                    raise AssertionError(f"Web server exited early:\n{output}")
                if time.time() >= deadline:
                    raise AssertionError("Web server did not become ready")
                time.sleep(0.05)

        assert data["ok"] is True
        assert data["goals"][0]["goal_id"] == "dummy_algorithm_innovation"

        code, status = _get_json(base, "/loop/status?goal_id=dummy_algorithm_innovation")
        assert code == 200
        assert status["research_state"]["goal_id"] == "dummy_algorithm_innovation"
        assert "ideaspark" in status["queues"]

        code, artifacts = _get_json(base, "/loop/artifacts?goal_id=dummy_algorithm_innovation")
        assert code == 200
        assert artifacts["total"] >= 1
        assert artifacts["artifacts"]
        artifact_id = artifacts["artifacts"][0]["id"]

        code, artifact = _get_json(
            base,
            "/loop/artifact?goal_id=dummy_algorithm_innovation&artifact_id=" + artifact_id,
        )
        assert code == 200
        assert artifact["artifact"]["id"] == artifact_id

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                base + "/loop/status?goal_id=..%2Fetc",
                timeout=5,
            )
        assert exc_info.value.code == 400
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
