"""异步实验后台 runner（detached 进程入口，自包含内核）。

由 tool/arc.ts 的 run_experiment(async=true) 以 detached 子进程方式拉起：

    python async_runner.py <job_dir> <timeout_sec>

它脱离 OpenCode 的生命周期独立运行，把实验真跑完，并把状态/结果**落盘到持久
job 目录**，供 arc_experiment_status 工具事后读取（信号文件 done-file 模式）：

    <job_dir>/code.py        # 待执行的用户实验代码（由 arc.ts 预先写入）
    <job_dir>/status.json    # {state: running|done|failed, pid, start, end, returncode, ...}
    <job_dir>/result.json    # 终态结果：returncode/timed_out/metrics/stdout/stderr/elapsed_sec
    <job_dir>/.done          # 哨兵文件（内容为 returncode），出现即代表跑完
    <job_dir>/work/          # ExperimentSandbox 的持久工作目录

设计要点：
- 复用 sandbox.py 的 ExperimentSandbox（其 subprocess.run(timeout=) 即本进程的硬超时）。
- **持久 workdir**（不是 sync 路径的 TemporaryDirectory）——否则进程退出目录被清，异步拿不到结果。
- 全程 try/except 兜底：无论如何 status 都会落到 done/failed 终态，绝不留 running 僵尸。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _write_json(path: Path, data: dict) -> None:
    """原子写 JSON（先写临时文件再 rename，避免 status 工具读到半截）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _lifecycle(job_dir: Path, event: str, **fields) -> None:
    """追加一行 job 生命周期事件到 <job>/lifecycle.jsonl（JSONL，带毫秒级 epoch ts）。

    这是端到端审计链的**系统层**：与 heartbeat 插件落的 _audit/{heartbeat,events}.jsonl（agent 层）
    按统一的毫秒 ts 归并，即可拼出「实验 start/end → agent 在不在生成 → 心跳看到什么、注入没」。
    ts 用毫秒与 heartbeat 的 Date.now() 对齐。审计落盘失败绝不影响实验主流程。
    """
    try:
        rec = {"ts": int(time.time() * 1000), "event": event, "pid": os.getpid(), **fields}
        with (job_dir / "lifecycle.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 审计软项，出错就当没记
        pass


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: async_runner.py <job_dir> <timeout_sec>", file=sys.stderr)
        return 2

    job_dir = Path(sys.argv[1]).resolve()
    try:
        timeout_sec = int(sys.argv[2])
    except ValueError:
        timeout_sec = 300

    job_dir.mkdir(parents=True, exist_ok=True)
    status_path = job_dir / "status.json"
    result_path = job_dir / "result.json"
    done_path = job_dir / ".done"

    started = time.time()
    _write_json(status_path, {"state": "running", "pid": os.getpid(), "start": started})
    _lifecycle(job_dir, "start", timeout_sec=timeout_sec, start=started)

    try:
        code = (job_dir / "code.py").read_text(encoding="utf-8")

        # 复用内核 sandbox（cwd 已是 scripts/，可直接 import）
        from sandbox import ExperimentSandbox, SandboxConfig

        python_path = os.environ.get("ARC_PYTHON") or sys.executable
        cfg = SandboxConfig(python_path=python_path)
        sb = ExperimentSandbox(cfg, job_dir / "work")
        # 实时把实验 stdout/stderr 逐行 tee 到 runner.log（同时内存留全量供 parse_metrics）。
        # 否则 subprocess.run(capture_output=True) 会把输出全憋在内存，跑完前 runner.log 一直为空，
        # heartbeat / arc_experiment_status 都 tail 不到进度（这正是用户遇到的"日志为空"）。
        runner_log = job_dir / "runner.log"
        print(f"[runner] start pid={os.getpid()} timeout={timeout_sec}s", flush=True)
        r = sb.run(code, timeout_sec=timeout_sec, log_path=runner_log)
        print(
            f"[runner] end rc={r.returncode} timed_out={r.timed_out} elapsed={round(r.elapsed_sec, 1)}s",
            flush=True,
        )

        result = {
            "returncode": r.returncode,
            "timed_out": r.timed_out,
            "metrics": r.metrics,
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-1500:],
            "elapsed_sec": round(r.elapsed_sec, 3),
        }
        _write_json(result_path, result)

        ok = r.returncode == 0 and not r.timed_out
        _write_json(status_path, {
            "state": "done" if ok else "failed",
            "pid": os.getpid(),
            "start": started,
            "end": time.time(),
            "returncode": r.returncode,
            "timed_out": r.timed_out,
        })
        done_path.write_text(str(r.returncode), encoding="utf-8")
        _lifecycle(
            job_dir, "end",
            state="done" if ok else "failed",
            returncode=r.returncode,
            timed_out=r.timed_out,
            elapsed_sec=round(r.elapsed_sec, 3),
        )
        return 0

    except Exception as exc:  # noqa: BLE001 — 任何失败都要落终态，绝不留 running
        _write_json(result_path, {
            "returncode": -1,
            "timed_out": False,
            "metrics": {},
            "stdout": "",
            "stderr": f"async_runner crashed: {exc!r}",
            "elapsed_sec": round(time.time() - started, 3),
        })
        _write_json(status_path, {
            "state": "failed",
            "pid": os.getpid(),
            "start": started,
            "end": time.time(),
            "returncode": -1,
            "error": repr(exc),
        })
        done_path.write_text("-1", encoding="utf-8")
        _lifecycle(
            job_dir, "end",
            state="failed",
            returncode=-1,
            error=repr(exc),
            elapsed_sec=round(time.time() - started, 3),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
