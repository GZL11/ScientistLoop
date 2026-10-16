"""ACPClient 修复的单元测试：死锁防护、BrokenPipe 处理、close 清理。"""

import json
import subprocess
import threading
import time

from webagent.runners.backends.opencode_acp import ACPClient


def _make_proc_with_script(script: str) -> subprocess.Popen:
    """启动一个 Python 子进程作为 mock ACP server。"""
    return subprocess.Popen(
        ["python3", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_call_normal_response():
    """正常 RPC 调用应返回 result。"""
    # Mock server: 读一行请求，返回一行响应
    script = r'''
import sys, json
line = sys.stdin.buffer.readline()
req = json.loads(line)
resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}}
sys.stdout.write(json.dumps(resp) + "\n")
sys.stdout.flush()
# keep alive briefly so client can read
import time; time.sleep(0.5)
'''
    proc = _make_proc_with_script(script)
    client = ACPClient(proc)
    try:
        result, text = client.call("test/method", {"x": 1})
        assert result == {"ok": True}
        assert text == ""
    finally:
        client.close()


def test_call_subprocess_dies_no_deadlock():
    """子进程立即退出时，call() 应抛异常而非死锁。"""
    # Mock server: 立即退出，不响应
    script = "import sys; sys.exit(0)"
    proc = _make_proc_with_script(script)
    client = ACPClient(proc)

    try:
        client.call("test/method", {})
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "ACP" in str(e)
    finally:
        client.close()


def test_send_broken_pipe():
    """子进程已死时 _send 应抛 RuntimeError 而非 BrokenPipeError。"""
    script = "import sys; sys.exit(0)"
    proc = _make_proc_with_script(script)
    client = ACPClient(proc)
    proc.wait()  # 确保进程已死
    time.sleep(0.1)

    try:
        client._send({"test": True})
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "disconnected" in str(e)
    finally:
        client.close()


def test_dead_flag_prevents_call():
    """_dead 标志位应阻止后续 call()。"""
    script = "import sys; sys.exit(0)"
    proc = _make_proc_with_script(script)
    client = ACPClient(proc)
    proc.wait()
    time.sleep(0.2)  # 等 reader 线程检测到 EOF

    try:
        client.call("test/method", {})
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "no longer running" in str(e)
    finally:
        client.close()


def test_close_joins_threads():
    """close() 后 reader 线程应已退出。"""
    script = "import time; time.sleep(10)"  # 长运行，等 terminate
    proc = _make_proc_with_script(script)
    client = ACPClient(proc)
    client.close()

    assert not client._reader.is_alive()
    assert not client._stderr_reader.is_alive()
