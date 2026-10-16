"""SciModelingBench benchmark-managed launcher helpers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .prepare_problem import prepare_task_problem
from .task_catalog import DEFAULT_HF_REVISION


@dataclass(frozen=True)
class SciModelingBenchBootstrap:
    """Trusted bootstrap artifacts for one benchmark-managed run."""

    problem_dir: Path
    channel_dir: Path
    private_key: Path | None
    public_key: Path | None
    worker_log: Path | None
    revision: str


@dataclass
class ManagedEvaluatorWorker:
    """Handle a trusted evaluator worker subprocess."""

    process: subprocess.Popen[bytes]
    channel_dir: Path
    log_path: Path
    log_handle: Any | None = None

    def wait_for_drain(self, timeout_sec: float = 300.0) -> None:
        """Wait for CLIENT_DONE / EVALUATOR_DONE handshake, then join the worker."""

        deadline = time.monotonic() + float(timeout_sec)
        done_path = self.channel_dir / "EVALUATOR_DONE.json"
        while time.monotonic() < deadline:
            if done_path.is_file():
                break
            if self.process.poll() is not None:
                break
            time.sleep(0.5)
        if done_path.is_file():
            try:
                self.process.wait(timeout=max(1.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                self._terminate()
        elif self.process.poll() is None:
            self._terminate()
        if self.process.returncode and self.process.returncode != 0:
            self._close_log()
            raise RuntimeError(
                "SciModelingBench trusted worker exited with code "
                f"{self.process.returncode}; log={self.log_path}"
            )
        self._close_log()

    def _terminate(self) -> None:
        """Stop a hung worker after the graceful drain window."""

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
        self._close_log()

    def close(self) -> None:
        """Force-stop the worker when the controller aborts early."""

        self._terminate()

    def _close_log(self) -> None:
        """Close the worker log handle exactly once."""

        if self.log_handle is not None:
            try:
                self.log_handle.close()
            finally:
                self.log_handle = None


def prepare_scimodelingbench_problem(
    *,
    task_id: str,
    problem_dir: str | Path,
    cache_dir: str | Path | None = None,
    revision: str | None = None,
    task_loader: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Materialize the public SciModelingBench problem snapshot."""

    destination = Path(problem_dir).expanduser().resolve()
    report_path = destination / "prepare_report.json"
    if report_path.is_file() and not overwrite:
        return json.loads(report_path.read_text(encoding="utf-8"))
    return prepare_task_problem(
        task_id=task_id,
        problem_dir=destination,
        revision=revision or DEFAULT_HF_REVISION,
        cache_dir=cache_dir,
        task_loader=task_loader,
        overwrite=overwrite,
    )


def ensure_keypair(channel_dir: str | Path, *, overwrite: bool = False) -> tuple[Path, Path]:
    """Create or reuse a channel RSA keypair."""

    channel = Path(channel_dir).expanduser().resolve()
    channel.mkdir(parents=True, exist_ok=True)
    private_key = channel / "private_key.pem"
    public_key = channel / "public_key.pem"
    if private_key.exists() or public_key.exists():
        if not (private_key.is_file() and public_key.is_file()):
            raise FileExistsError(
                f"channel contains a partial keypair: {channel}"
            )
        if overwrite:
            private_key.unlink()
            public_key.unlink()
        else:
            return private_key, public_key
    _run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(private_key),
        ]
    )
    _run(
        [
            "openssl",
            "rsa",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ]
    )
    return private_key, public_key


def launch_evaluator_worker(
    *,
    task_id: str,
    workspace_dir: str | Path,
    channel_dir: str | Path,
    private_key: str | Path,
    cache_dir: str | Path | None = None,
    revision: str | None = None,
    task_loader: str | None = None,
    log_path: str | Path | None = None,
) -> ManagedEvaluatorWorker:
    """Start the trusted SciModelingBench evaluator worker."""

    channel = Path(channel_dir).expanduser().resolve()
    channel.mkdir(parents=True, exist_ok=True)
    _reset_channel_state(channel)
    responses = channel / "responses"
    requests = channel / "requests"
    responses.mkdir(parents=True, exist_ok=True)
    requests.mkdir(parents=True, exist_ok=True)
    log = (
        Path(log_path).expanduser().resolve()
        if log_path is not None
        else channel / "evaluator.log"
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    cmd = [
        sys.executable,
        "-m",
        "famou_scientist.loop.integrations.scimodelingbench.evaluator_worker",
        "--task-id",
        str(task_id),
        "--workspace-dir",
        str(Path(workspace_dir).expanduser().resolve()),
        "--channel-dir",
        str(channel),
        "--private-key",
        str(Path(private_key).expanduser().resolve()),
    ]
    if revision:
        cmd.extend(["--revision", revision])
    if cache_dir:
        cmd.extend(["--cache-dir", str(Path(cache_dir).expanduser().resolve())])
    if task_loader:
        cmd.extend(["--task-loader", task_loader])
    env = os.environ.copy()
    if cache_dir is not None:
        cache_home = Path(cache_dir).expanduser().resolve()
        env["HF_HOME"] = str(cache_home)
        env["HF_DATASETS_CACHE"] = str(cache_home / "datasets")
    process = subprocess.Popen(
        cmd,
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        _wait_for_ready(channel / "EVALUATOR_READY.json", process, log)
    except Exception:
        handle.close()
        raise
    return ManagedEvaluatorWorker(
        process=process,
        channel_dir=channel,
        log_path=log,
        log_handle=handle,
    )


def _reset_channel_state(channel: Path) -> None:
    """Clear stale file-channel state while preserving signing keys."""

    for name in ("CLIENT_DONE.json", "EVALUATOR_READY.json", "EVALUATOR_DONE.json"):
        (channel / name).unlink(missing_ok=True)
    for subdir in ("requests", "responses"):
        directory = channel / subdir
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() or path.is_symlink():
                path.unlink()


def bootstrap_scimodelingbench(
    *,
    task_id: str,
    run_dir: str | Path,
    problem_dir: str | Path,
    workspace_dir: str | Path,
    channel_dir: str | Path,
    cache_dir: str | Path | None = None,
    revision: str | None = None,
    task_loader: str | None = None,
    overwrite_problem: bool = False,
    overwrite_channel: bool = False,
) -> SciModelingBenchBootstrap:
    """Prepare the public problem and trusted channel for one run."""

    resolved_revision = revision or DEFAULT_HF_REVISION
    prepare_scimodelingbench_problem(
        task_id=task_id,
        problem_dir=problem_dir,
        cache_dir=cache_dir,
        revision=resolved_revision,
        task_loader=task_loader,
        overwrite=overwrite_problem,
    )
    private_key, public_key = ensure_keypair(channel_dir, overwrite=overwrite_channel)
    worker_log = Path(run_dir).expanduser().resolve() / "controller" / "scimodelingbench_evaluator.log"
    worker_log.parent.mkdir(parents=True, exist_ok=True)
    return SciModelingBenchBootstrap(
        problem_dir=Path(problem_dir).expanduser().resolve(),
        channel_dir=Path(channel_dir).expanduser().resolve(),
        private_key=private_key,
        public_key=public_key,
        worker_log=worker_log,
        revision=resolved_revision,
    )


def _run(cmd: list[str]) -> None:
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(
            f"failed to run {' '.join(cmd[:2])}: "
            f"{(process.stderr or process.stdout or 'unknown error').strip()}"
        )


def _wait_for_ready(ready_path: Path, process: subprocess.Popen[bytes], log: Path) -> None:
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if ready_path.is_file():
            return
        if process.poll() is not None:
            break
        time.sleep(0.2)
    tail = ""
    if log.is_file():
        try:
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        except OSError:
            tail = ""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
    raise RuntimeError(
        "SciModelingBench evaluator worker did not become ready"
        + (f"; log tail:\n{tail}" if tail else "")
    )


__all__ = [
    "ManagedEvaluatorWorker",
    "SciModelingBenchBootstrap",
    "bootstrap_scimodelingbench",
    "ensure_keypair",
    "launch_evaluator_worker",
    "prepare_scimodelingbench_problem",
]
