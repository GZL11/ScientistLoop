"""canonical run 的完整 stdout/stderr 必须落盘。

result 里的 `stdout`/`stderr` 是给 agent 和索引看的**摘要**（尾部 3000/1500 字符），
不是证据。一次训练跑几小时，3000 字符大概就是最后二三十行；stderr 只留 1500 更要命
——报错的 traceback 一长就被从头切掉，留下一截无头调用栈。原件必须在磁盘上。
"""
from __future__ import annotations

from pathlib import Path

from famou_scientist.loop.evaluation.experiment import (
    RUN_DIR_HOST_FILES,
    RUN_LOG_MAX_BYTES,
    CommandExperimentRunner,
    _persist_stream,
)


def _runner(tmp_path: Path, script: str) -> CommandExperimentRunner:
    """构造一个直接执行给定 python 代码的 Runner。"""

    return CommandExperimentRunner(
        tmp_path,
        {"argv": ["python3", "-c", script], "timeout_sec": 60},
        cwd=tmp_path,
    )


def test_full_stdout_and_stderr_land_on_disk(tmp_path: Path) -> None:
    """摘要被截断，但原件一个字节不少。"""

    # 刻意超过 result 里 3000/1500 的摘要上限，才测得出「原件没被切」。
    script = (
        "import sys\n"
        "sys.stdout.write('O' * 20000)\n"
        "sys.stderr.write('E' * 20000)\n"
    )
    result = _runner(tmp_path, script).run({"branch_id": "b1", "artifact": ""})

    assert result["stdout_bytes"] == 20000
    assert result["stderr_bytes"] == 20000
    assert result["stdout_truncated"] is False
    assert result["stderr_truncated"] is False
    assert result["run_log_error"] is None

    stdout_log = Path(result["stdout_path"])
    stderr_log = Path(result["stderr_path"])
    assert stdout_log.read_text(encoding="utf-8") == "O" * 20000
    assert stderr_log.read_text(encoding="utf-8") == "E" * 20000

    # 摘要仍然是摘要——原件落盘不代表把 result 撑大。
    assert len(result["stdout"]) == 3000
    assert len(result["stderr"]) == 1500


def test_host_log_files_are_not_mistaken_for_the_artifact(tmp_path: Path) -> None:
    """日志写进 run_dir 之后，产物回退发现不能把它当成方案产物。

    `run()` 里有一条兼容分支：命令模板不向 stdout 返回 JSON 时，就在 run_dir /
    output_dir 里找「恰好一个文件」当产物。stdout.log / stderr.log 一旦漏进这个
    集合，那条判据立刻从「找到唯一产物」变成「找到三个，放弃」。
    """

    assert {"stdout.log", "stderr.log", "runner.log", "result.json"} == set(
        RUN_DIR_HOST_FILES
    )

    candidate_dir = tmp_path / "candidates" / "c1"
    (candidate_dir / "output").mkdir(parents=True)
    # 脚本里不能出现花括号：argv 模板走的是 str.format（`experiment.py:212`）。
    script = (
        "import pathlib, sys\n"
        f"pathlib.Path({str(candidate_dir / 'output' / 'pred.json')!r})"
        ".write_text('ok')\n"
        "sys.stdout.write('not json at all\\n')\n"
    )
    result = _runner(tmp_path, script).run(
        {"branch_id": "b1", "artifact": "", "candidate_dir": str(candidate_dir)}
    )

    assert Path(result["artifact"]).name == "pred.json"
    assert result["valid"] is True
    # 日志确实写在 run_dir 里——不是靠"没写"绕开这个坑的。
    assert Path(result["stdout_path"]).parent == Path(result["run_dir"])


def test_oversized_stream_keeps_the_tail_and_records_the_loss(tmp_path: Path) -> None:
    """超上限时切头留尾，并记明原始字节数——截断本身是读数，不能靠文件大小猜。"""

    path = tmp_path / "big.log"
    text = "x" * (RUN_LOG_MAX_BYTES + 5000)
    info = _persist_stream(path, text)

    assert info["truncated"] is True
    assert info["bytes"] == len(text)
    body = path.read_bytes()
    # 尾部保住了（报错的 traceback 在尾部）；头部那句说明了丢了多少。
    assert body.endswith(b"x" * 100)
    assert b"5000 \xe5\xad\x97\xe8\x8a\x82\xe5\xb7\xb2\xe6\x88\xaa\xe6\x96\xad" in body


def test_log_write_failure_does_not_kill_the_run(tmp_path: Path) -> None:
    """日志写不进去只记 error，绝不把 run 判死——日志是证据层，不是关键路径。"""

    unwritable = tmp_path / "nope" / "deep" / "x.log"  # 父目录不存在
    info = _persist_stream(unwritable, "hello")

    assert info["path"] is None
    assert info["error"]
    assert info["bytes"] == 5
