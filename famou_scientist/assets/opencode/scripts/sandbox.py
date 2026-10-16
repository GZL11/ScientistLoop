"""Sandbox environment for safe experiment code execution."""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

# ─────────────────────────────────────────────────────────────────────────
# 以下 SandboxConfig / is_metric_name 原本 import 自 researchclaw.config /
# researchclaw.hardware。为让本脚本自包含（不依赖 ARC 包），将它们内联于此。
# 来源：researchclaw/config.py (DEFAULT_PYTHON_PATH, SandboxConfig)、
#       researchclaw/hardware.py (LOG_WORDS, _MAX_METRIC_NAME_WORDS, is_metric_name)
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_PYTHON_PATH = (
    ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python3"
)


@dataclass(frozen=True)
class SandboxConfig:
    """Configuration for the experiment sandbox (inlined from researchclaw.config)."""

    python_path: str = DEFAULT_PYTHON_PATH
    gpu_required: bool = False
    allowed_imports: tuple[str, ...] = (
        "math",
        "random",
        "json",
        "csv",
        "numpy",
        "torch",
        "sklearn",
    )
    max_memory_mb: int = 4096


# Words that indicate a stdout line is a log message, not a "name: value" metric.
LOG_WORDS: frozenset[str] = frozenset({
    "running", "loading", "saving", "processing", "starting",
    "finished", "completed", "initializing", "downloading",
    "training", "evaluating", "epoch", "step", "iteration",
    "experiment", "warning", "error", "info", "debug",
    "experiments", "using", "setting", "creating", "building",
    "computing", "reading", "writing", "opening", "closing",
})

# Maximum word count for a plausible metric name
_MAX_METRIC_NAME_WORDS = 6


def is_metric_name(name: str) -> bool:
    """Return True if *name* looks like a metric name rather than a log line.

    Used to filter stdout lines when parsing ``name: value`` metric output.
    (Inlined from researchclaw.hardware.)
    """
    words = name.lower().split()
    if len(words) > _MAX_METRIC_NAME_WORDS:
        return False
    if any(w in LOG_WORDS for w in words):
        return False
    return True


logger = logging.getLogger(__name__)


def validate_entry_point(entry_point: str) -> str | None:
    """Validate *entry_point* syntax (no filesystem access needed).

    Returns an error message if invalid, ``None`` if valid.
    Call this **before** copying files to fail fast on obviously bad input.
    """
    if not entry_point or not entry_point.strip():
        return "Entry point is empty"
    ep = Path(entry_point)
    posix_ep = PurePosixPath(entry_point)
    windows_ep = PureWindowsPath(entry_point)
    if ep.is_absolute() or posix_ep.is_absolute() or windows_ep.is_absolute():
        return f"Entry point must be a relative path, got: {entry_point}"
    if ".." in ep.parts:
        return f"Entry point must not contain '..': {entry_point}"
    return None


def validate_entry_point_resolved(staging: Path, entry_point: str) -> str | None:
    """Validate that *entry_point* resolves inside *staging*.

    Returns an error message if invalid, ``None`` if valid.
    Call this **after** copying files so that symlinks are resolved against
    the real staging contents.
    """
    resolved = (staging / entry_point).resolve()
    staging_resolved = staging.resolve()
    if not resolved.is_relative_to(staging_resolved):
        return f"Entry point escapes staging directory: {entry_point}"
    return None

# Matches both plain "metric: value" and "condition=xxx metric: value" formats
_FLOAT_RE = r"[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?"
_METRIC_PATTERN = re.compile(
    rf"^(?:\S+=\S+\s+)?(\w[\w.]*)\s*:\s*({_FLOAT_RE})\s*$"
)
# R17: Extract per-condition metrics with optional extra tags:
#   "condition=<name> [regime=<r>] [H=<h>] [seed=<s>] metric: value"
# Captures: (condition_name, extra_tags_string, metric_name, value)
_CONDITION_METRIC_PATTERN = re.compile(
    rf"^condition=(\S+)\s+((?:\S+=\S+\s+)*)(\w[\w.]*)\s*:\s*({_FLOAT_RE})\s*$"
)
# R16-1: Ratio format with optional extra tags
_CONDITION_RATIO_PATTERN = re.compile(
    r"^condition=(\S+)\s+((?:\S+=\S+\s+)*)(\w[\w.]*)\s*:\s*(\d+)/(\d+)\s*$"
)
# BUG-181: Parse SUMMARY lines: "SUMMARY condition=X metric=Y mean=M std=S [success_rate=R]"
_SUMMARY_PATTERN = re.compile(
    r"^SUMMARY\s+condition=(\S+)\s+metric=(\S+)\s+mean=("
    + _FLOAT_RE
    + r")\s+std=("
    + _FLOAT_RE
    + r")"
)
# BUG-181: Multi-metric condition line: extract all "metric: value" pairs
_CONDITION_MULTI_METRIC_RE = re.compile(
    r"(\w[\w.]*)\s*:\s*(" + _FLOAT_RE + r")"
)


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def parse_metrics(stdout: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in stdout.splitlines():
        stripped = line.strip()

        # BUG-181: Parse SUMMARY lines first (most reliable, one metric per line)
        # Format: "SUMMARY condition=X metric=Y mean=M std=S [success_rate=R]"
        summary_match = _SUMMARY_PATTERN.match(stripped)
        if summary_match:
            cond_name, metric_name, mean_str, std_str = summary_match.groups()
            if is_metric_name(metric_name):
                try:
                    mean_val = float(mean_str)
                    std_val = float(std_str)
                except ValueError:
                    continue
                if not (math.isnan(mean_val) or math.isinf(mean_val)):
                    metrics[f"{cond_name}/{metric_name}"] = mean_val
                    metrics[f"{cond_name}/{metric_name}_mean"] = mean_val
                    metrics[f"{cond_name}/{metric_name}_std"] = std_val
                    metrics[metric_name] = mean_val
            continue

        # R16-1: Try ratio format first: "condition=X [tags] metric: N/M"
        ratio_match = _CONDITION_RATIO_PATTERN.match(stripped)
        if ratio_match:
            cond_name, extra_tags, name, num, den = ratio_match.groups()
            if is_metric_name(name):
                try:
                    val = float(num) / float(den) if float(den) != 0 else 0.0
                except (ValueError, ZeroDivisionError):
                    continue
                # Build composite key from condition + extra tags
                tag_parts = [cond_name]
                for tag in extra_tags.strip().split():
                    if "=" in tag:
                        tag_parts.append(tag.split("=", 1)[1])
                composite_key = "/".join(tag_parts)
                metrics[f"{composite_key}/{name}"] = val
                metrics[f"{cond_name}/{name}"] = val
                metrics[name] = val
            continue

        # Try condition-prefixed format: "condition=X [tags] metric: value"
        cond_match = _CONDITION_METRIC_PATTERN.match(stripped)
        if cond_match:
            cond_name, extra_tags, name, value = cond_match.groups()
            if is_metric_name(name):
                try:
                    val = float(value)
                except ValueError:
                    continue
                if math.isnan(val) or math.isinf(val):
                    logger.warning("Skipping non-finite metric %s=%s", name, value)
                    continue
                # Build composite key from condition + extra tags
                tag_parts = [cond_name]
                for tag in extra_tags.strip().split():
                    if "=" in tag:
                        tag_parts.append(tag.split("=", 1)[1])
                composite_key = "/".join(tag_parts)
                metrics[f"{composite_key}/{name}"] = val
                metrics[f"{cond_name}/{name}"] = val
                metrics[name] = val
            continue

        # BUG-181: Multi-metric condition line fallback
        # Handles: "condition=X seed=S metric1: v1 metric2: v2 ..."
        # (lines not matched by _CONDITION_METRIC_PATTERN due to multiple metrics)
        if stripped.startswith("condition="):
            _parts = stripped.split()
            _cond = _parts[0].split("=", 1)[1] if "=" in _parts[0] else None
            _seed = None
            for _p in _parts[1:]:
                if _p.startswith("seed="):
                    _seed = _p.split("=", 1)[1]
                    break
            if _cond:
                for _mm in _CONDITION_MULTI_METRIC_RE.finditer(stripped):
                    _mname, _mval_str = _mm.groups()
                    if is_metric_name(_mname):
                        try:
                            _mval = float(_mval_str)
                        except ValueError:
                            continue
                        if math.isnan(_mval) or math.isinf(_mval):
                            continue
                        if _seed is not None:
                            metrics[f"{_cond}/{_seed}/{_mname}"] = _mval
                        metrics[f"{_cond}/{_mname}"] = _mval
                        metrics[_mname] = _mval
                continue

        # Plain format: "metric: value"
        match = _METRIC_PATTERN.match(stripped)
        if match is None:
            continue
        name, value = match.groups()
        if not is_metric_name(name):
            continue
        try:
            val = float(value)
        except ValueError:
            continue
        # R5-3: Skip NaN/Inf values — they indicate divergence
        if math.isnan(val) or math.isinf(val):
            logger.warning("Skipping non-finite metric %s=%s", name, value)
            continue
        metrics[name] = val
    return metrics


def extract_paired_comparisons(stdout: str) -> list[dict[str, object]]:
    """R18-1: Extract PAIRED statistical comparison lines from stdout.

    Matches: PAIRED: <method> vs <baseline> [regime=<r>] mean_diff=<v> ...
    Returns a list of dicts with method, baseline, regime, and stats.
    """
    results: list[dict[str, object]] = []
    pattern = re.compile(
        r"^PAIRED:\s+(\S+)\s+vs\s+(\S+)\s*(.*?)mean_diff=([+-]?\d+\.?\d*)"
        r".*?std_diff=([+-]?\d+\.?\d*)"
        r".*?t_stat=([+-]?\d+\.?\d*)"
        r".*?p_value=([+-]?\d+\.?\d*)"
    )
    for line in stdout.splitlines():
        m = pattern.match(line.strip())
        if m:
            method, baseline, tags, mean_diff, std_diff, t_stat, p_value = m.groups()
            entry: dict[str, object] = {
                "method": method,
                "baseline": baseline,
                "mean_diff": float(mean_diff),
                "std_diff": float(std_diff),
                "t_stat": float(t_stat),
                "p_value": float(p_value),
            }
            # Extract regime if present
            regime_m = re.search(r"regime=(\S+)", tags)
            if regime_m:
                entry["regime"] = regime_m.group(1)
            # Extract CI if present
            ci_m = re.search(r"ci95=\(([^,]+),([^)]+)\)", line)
            if ci_m:
                entry["ci95_low"] = float(ci_m.group(1))
                entry["ci95_high"] = float(ci_m.group(2))
            results.append(entry)
    return results


def detect_nan_divergence(stdout: str, stderr: str) -> str | None:
    """Check stdout/stderr for NaN/Inf/divergence indicators.

    Returns a description of the issue if detected, None otherwise.
    """
    issues: list[str] = []
    combined = (stdout or "") + "\n" + (stderr or "")
    lower = combined.lower()

    # Check for NaN indicators
    if "nan" in lower:
        for pattern in ("loss: nan", "nan loss", "math domain error", "loss is nan"):
            if pattern in lower:
                issues.append(f"NaN detected: '{pattern}' found in output")
                break
        else:
            # Generic NaN mention — could be a false positive but worth flagging
            if re.search(r"\bnan\b", lower):
                issues.append("Possible NaN detected in output")

    # Check for Inf indicators
    if "inf" in lower:
        if re.search(r"\binf\b", lower) and "info" not in lower.split("inf")[0][-4:]:
            issues.append("Possible Inf value detected in output")

    # Check for divergence (loss > 100 is a common fast-fail threshold)
    for line in stdout.splitlines():
        match = _METRIC_PATTERN.match(line.strip())
        if match:
            name, value = match.groups()
            try:
                val = float(value)
                if math.isnan(val) or math.isinf(val):
                    issues.append(f"Non-finite metric: {name}={value}")
                elif "loss" in name.lower() and val > 100:
                    issues.append(f"Diverging loss: {name}={val} (>100)")
            except ValueError:
                pass

    return "; ".join(issues) if issues else None


@dataclass(frozen=True)
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float
    metrics: dict[str, object]
    timed_out: bool = False


class SandboxProtocol(Protocol):
    """Structural type for sandbox backends (ExperimentSandbox, DockerSandbox)."""

    def run(self, code: str, *, timeout_sec: int = 300, log_path: "str | Path | None" = None) -> SandboxResult: ...

    def run_project(
        self,
        project_dir: Path,
        *,
        entry_point: str = "main.py",
        timeout_sec: int = 300,
        args: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> SandboxResult: ...


class ExperimentSandbox:
    def __init__(self, config: SandboxConfig, workdir: Path) -> None:
        self.config: SandboxConfig = config
        self.workdir: Path = workdir.resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._run_counter: int = 0

    def run(self, code: str, *, timeout_sec: int = 300, log_path: "str | Path | None" = None) -> SandboxResult:
        script_path = self._next_script_path()
        self._write_script(script_path, code)

        start = time.monotonic()
        command = self._build_command(script_path)
        logger.debug("Running sandbox command: %s", command)

        result: SandboxResult
        if log_path is not None:
            # 流式（异步长跑）：把子进程 stdout/stderr 逐行 tee 到 log_path（实时，可被
            # heartbeat / arc_experiment_status 随时 tail），同时在内存留全量供 parse_metrics。
            result = self._run_streaming(
                command, timeout_sec=timeout_sec, start=start, cwd=self.workdir, log_path=Path(log_path)
            )
            if self._should_cleanup(result):
                self._cleanup_script(script_path)
            return result

        try:
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                cwd=self.workdir,
                env=env,
                check=False,
            )
            result = self._result_from_completed(
                completed, elapsed_sec=time.monotonic() - start
            )
        except subprocess.TimeoutExpired as exc:
            result = self._result_from_timeout(
                exc, timeout_sec=timeout_sec, elapsed_sec=time.monotonic() - start
            )
        except Exception as exc:  # noqa: BLE001
            result = self._result_from_exception(
                exc, elapsed_sec=time.monotonic() - start
            )

        if self._should_cleanup(result):
            self._cleanup_script(script_path)

        return result

    def _run_streaming(
        self,
        command: list[str],
        *,
        timeout_sec: int,
        start: float,
        cwd: Path,
        log_path: Path,
    ) -> SandboxResult:
        """Run *command*, teeing child stdout/stderr to *log_path* line-by-line.

        Unlike the ``subprocess.run(capture_output=True)`` path — which buffers
        all output in memory until the process exits, leaving ``runner.log``
        empty for the whole run — this writes each line to *log_path* (with
        flush) as it arrives, so the log is live-tailable, while still
        accumulating full stdout/stderr in memory for ``parse_metrics`` and
        ``result.json``.

        The child stays in this process's group (no ``start_new_session``) so
        ``arc_cancel_experiment``'s ``killpg`` of the runner group still reaches
        the experiment and its DataLoader/multiprocessing workers.
        """
        import threading

        out_chunks: list[str] = []
        err_chunks: list[str] = []
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            logf = open(log_path, "a", encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            logf = None

        def _pump(stream, sink: list[str]) -> None:
            try:
                for line in iter(stream.readline, ""):
                    sink.append(line)
                    if logf is not None:
                        try:
                            logf.write(line)
                            logf.flush()
                        except Exception:  # noqa: BLE001
                            pass
            finally:
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=cwd,
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            if logf is not None:
                try:
                    logf.close()
                except Exception:  # noqa: BLE001
                    pass
            return self._result_from_exception(exc, elapsed_sec=time.monotonic() - start)

        t_out = threading.Thread(target=_pump, args=(proc.stdout, out_chunks), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, err_chunks), daemon=True)
        t_out.start()
        t_err.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning("Sandbox (streaming) execution timed out after %ss", timeout_sec)
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass

        # 等读取线程把残余输出排空（进程已退出 → readline 很快返回 EOF）
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        if logf is not None:
            try:
                if timed_out:
                    logf.write(f"\n[sandbox] experiment timed out after {timeout_sec}s — killed\n")
                logf.flush()
                logf.close()
            except Exception:  # noqa: BLE001
                pass

        stdout = "".join(out_chunks)
        stderr = "".join(err_chunks)
        metrics = parse_metrics(stdout)
        rc = proc.returncode if proc.returncode is not None else -1
        return SandboxResult(
            returncode=-1 if timed_out else rc,
            stdout=stdout,
            stderr=stderr,
            elapsed_sec=time.monotonic() - start,
            metrics={key: value for key, value in metrics.items()},
            timed_out=timed_out,
        )

    def run_project(
        self,
        project_dir: Path,
        *,
        entry_point: str = "main.py",
        timeout_sec: int = 300,
        args: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Run a multi-file experiment project in the sandbox.

        Copies all ``.py`` files from *project_dir* into the sandbox work
        directory and executes *entry_point*.
        """
        import shutil

        # BUG-DA8-06: Use unique dir name to prevent races under concurrent calls
        self._run_counter += 1
        sandbox_project = self.workdir / f"_project_{self._run_counter}"
        if sandbox_project.exists():
            shutil.rmtree(sandbox_project)
        sandbox_project.mkdir(parents=True, exist_ok=True)

        # Pre-copy syntax validation — fail fast before any I/O
        err = validate_entry_point(entry_point)
        if err:
            return SandboxResult(
                returncode=-1, stdout="", stderr=err,
                elapsed_sec=0.0, metrics={},
            )

        # R5-4: Inject immutable experiment harness before copying project files
        self._inject_harness(sandbox_project)

        # Copy all project files (will NOT overwrite harness — harness name is unique)
        for src_file in project_dir.iterdir():
            if src_file.is_file():
                dest = sandbox_project / src_file.name
                # Do not allow project to overwrite the harness
                if dest.name == "experiment_harness.py":
                    logger.warning("Project contains experiment_harness.py — skipping (immutable)")
                    continue
                dest.write_bytes(src_file.read_bytes())
            elif src_file.is_dir() and not src_file.name.startswith("."):
                import shutil as _shutil_proj
                dest_dir = sandbox_project / src_file.name
                _shutil_proj.copytree(src_file, dest_dir, dirs_exist_ok=True)

        # Post-copy resolve check — catches symlink-based escapes
        err = validate_entry_point_resolved(sandbox_project, entry_point)
        if err:
            return SandboxResult(
                returncode=-1, stdout="", stderr=err,
                elapsed_sec=0.0, metrics={},
            )

        entry = sandbox_project / entry_point
        if not entry.exists():
            return SandboxResult(
                returncode=-1,
                stdout="",
                stderr=f"Entry point {entry_point} not found in project",
                elapsed_sec=0.0,
                metrics={},
            )

        start = time.monotonic()
        command = self._build_command(entry, args=args)
        logger.debug("Running project sandbox command: %s (cwd=%s)", command, sandbox_project)

        result: SandboxResult
        try:
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            if env_overrides:
                env.update(env_overrides)
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                cwd=sandbox_project,
                env=env,
                check=False,
            )
            result = self._result_from_completed(
                completed, elapsed_sec=time.monotonic() - start
            )
        except subprocess.TimeoutExpired as exc:
            result = self._result_from_timeout(
                exc, timeout_sec=timeout_sec, elapsed_sec=time.monotonic() - start
            )
        except Exception as exc:  # noqa: BLE001
            result = self._result_from_exception(
                exc, elapsed_sec=time.monotonic() - start
            )

        return result

    @staticmethod
    def _inject_harness(target_dir: Path) -> None:
        """Copy the immutable experiment harness into the target directory."""
        harness_src = Path(__file__).parent / "harness_template.py"
        if harness_src.exists():
            dest = target_dir / "experiment_harness.py"
            dest.write_text(harness_src.read_text(encoding="utf-8"), encoding="utf-8")
            logger.debug("Injected experiment harness into %s", target_dir)
        else:
            logger.warning("Harness template not found at %s", harness_src)

    def _next_script_path(self) -> Path:
        self._run_counter += 1
        return self.workdir / f"_experiment_{self._run_counter}.py"

    @staticmethod
    def _write_script(script_path: Path, code: str) -> None:
        _ = script_path.write_text(code, encoding="utf-8")

    def _build_command(
        self,
        script_path: Path,
        *,
        args: list[str] | None = None,
    ) -> list[str]:
        # Convert relative python_path to absolute WITHOUT resolving symlinks.
        # Using .resolve() would follow venv symlinks to the system Python binary,
        # which loses the venv context (site-packages like numpy become unavailable).
        python = self.config.python_path
        python_path = Path(python)
        if not python_path.is_absolute() and python != "python":
            python_path = Path.cwd() / python_path
        # -u: unbuffered stdout/stderr so subprocess.run captures all output
        command = [str(python_path), "-u", str(script_path)]
        if args:
            command.extend(args)
        return command

    @staticmethod
    def _result_from_completed(
        completed: subprocess.CompletedProcess[str], *, elapsed_sec: float
    ) -> SandboxResult:
        metrics = parse_metrics(completed.stdout)
        return SandboxResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_sec=elapsed_sec,
            metrics={key: value for key, value in metrics.items()},
        )

    @staticmethod
    def _result_from_timeout(
        exc: subprocess.TimeoutExpired,
        *,
        timeout_sec: int,
        elapsed_sec: float,
    ) -> SandboxResult:
        stdout = _to_text(exc.stdout)
        stderr = _to_text(exc.stderr)
        metrics = parse_metrics(stdout)
        logger.warning("Sandbox execution timed out after %ss", timeout_sec)
        return SandboxResult(
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            elapsed_sec=elapsed_sec,
            metrics={key: value for key, value in metrics.items()},
            timed_out=True,
        )

    @staticmethod
    def _result_from_exception(exc: Exception, *, elapsed_sec: float) -> SandboxResult:
        logger.exception("Sandbox execution failed: %s", exc)
        return SandboxResult(
            returncode=-1,
            stdout="",
            stderr=str(exc),
            elapsed_sec=elapsed_sec,
            metrics={},
        )

    @staticmethod
    def _should_cleanup(result: SandboxResult) -> bool:
        return result.returncode == 0 and not result.timed_out

    @staticmethod
    def _cleanup_script(script_path: Path) -> None:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete temporary file: %s", script_path)
