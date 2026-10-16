"""实现与实验命令使用的本地子进程沙箱。"""
from __future__ import annotations

import errno
import os
import secrets
import shutil
import signal
import subprocess
import shlex
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence, runtime_checkable


class SandboxError(RuntimeError):
    """表示沙箱配置或执行错误。"""


@dataclass(frozen=True)
class ExecutionIdentity:
    """描述不可信 Agent 或 Candidate 使用的非特权进程身份。"""

    uid: int
    gid: int
    prepare_root_owner: bool = False

    def __post_init__(self) -> None:
        """拒绝 root 和无效的用户、组编号。"""

        if int(self.uid) <= 0 or int(self.gid) <= 0:
            raise ValueError("非特权执行身份的 uid/gid 必须大于 0")


@dataclass(frozen=True)
class SandboxRunResult:
    """记录一次沙箱命令运行结果。"""
    command: tuple[str, ...]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int
    memory_limit_bytes: int | None = None
    memory_limit_exceeded: bool = False
    memory_limit_strategy: str | None = None
    memory_hard_limit_bytes: int | None = None
    memory_over_request: bool = False
    observed_memory_bytes: int | None = None
    termination_reason: str | None = None
    process_group_isolated: bool = False
    cuda_out_of_memory: bool = False
    # 由 ``cancel_file`` 触发的主动终止。**必须与"被信号打死"分开**：取消是我们
    # 自己发的 SIGTERM，不是方法失败，不该反馈给 Agent 说"你的脚本挂了"。
    cancelled: bool = False

    @property
    def valid(self) -> bool:
        """判断本次运行结果是否成功。"""
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.memory_limit_exceeded
            and not self.cuda_out_of_memory
        )

    def to_dict(self) -> dict[str, object]:
        """转换为可持久化的字典。"""
        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "memory_limit_bytes": self.memory_limit_bytes,
            "memory_limit_exceeded": self.memory_limit_exceeded,
            "memory_limit_strategy": self.memory_limit_strategy,
            "memory_hard_limit_bytes": self.memory_hard_limit_bytes,
            "memory_over_request": self.memory_over_request,
            "observed_memory_bytes": self.observed_memory_bytes,
            "termination_reason": self.termination_reason,
            "process_group_isolated": self.process_group_isolated,
            "cuda_out_of_memory": self.cuda_out_of_memory,
            "cancelled": self.cancelled,
            "valid": self.valid,
        }


@runtime_checkable
class ExecutionSandbox(Protocol):
    """定义执行沙箱接口。"""

    @property
    def root(self) -> Path:
        """返回当前沙箱根目录。"""
        ...

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        cancel_file: str | Path | None = None,
    ) -> SandboxRunResult:
        """执行当前组件的运行流程。"""
        ...

    def close(self) -> None:
        """关闭运行后端并释放资源。"""
        ...


def _inside(root: Path, candidate: Path) -> bool:
    """判断路径是否位于根目录内。"""
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


# 失败消息里带多少 stderr。够看清最后一个 traceback，又不至于把 record.json 撑爆。
_FAILURE_STDERR_TAIL_CHARS = 1200


def signal_name(returncode: int) -> str:
    """把负 returncode 翻译成信号名，翻不出来就退回编号。"""

    try:
        return signal.Signals(-int(returncode)).name
    except (ValueError, TypeError):
        return f"SIGNAL_{-int(returncode)}"


def process_failure_message(result: SandboxRunResult, *, subject: str) -> str:
    """给沙箱进程的非零退出配一句**带证据**的失败消息。

    以前各 Benchmark 这里恒为一句 "<subject> process failed"。真 stderr 只落在
    ``evidence/run.json``，而 ``expbank/<attempt>/record.json`` 里只剩这一句
    ——审计时 36 次 canonical 失败有一半根本无法归因，得逐个翻证据文件才知道
    到底是 Agent 的脚本挂了还是我们把目录设成了只读。
    """

    stderr = str(getattr(result, "stderr", "") or "").strip()
    base = f"{subject} process failed (returncode={getattr(result, 'returncode', '?')})"
    if not stderr:
        return base + "；进程未留下任何 stderr"
    tail = stderr[-_FAILURE_STDERR_TAIL_CHARS:]
    if len(stderr) > _FAILURE_STDERR_TAIL_CHARS:
        tail = "…" + tail
    return f"{base}: {tail}"


def _truncate(value: str, limit: int) -> str:
    """截断过长的命令输出。"""
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    # 保留尾部内容：异常栈和指标通常出现在末尾。
    tail = encoded[-limit:].decode("utf-8", errors="replace")
    return "[... output truncated ...]\n" + tail


class LocalSandbox:
    """使用本地子进程执行受限命令。"""

    def __init__(
        self,
        root: str | Path,
        *,
        output_limit_bytes: int = 256 * 1024,
        memory_limit_bytes: int | None = None,
        memory_hard_limit_bytes: int | None = None,
        termination_grace_sec: float = 5.0,
        identity: ExecutionIdentity | None = None,
        memory_limit_strategy: str = "auto",
        memory_monitor_interval_sec: float = 0.1,
    ):
        """初始化目录边界、输出上限和单个子进程的资源边界。

        ``memory_limit_bytes`` 是候选自己申报的额度，只用于记录是否超报；
        真正触发终止的是 ``memory_hard_limit_bytes``（默认等于申报值），
        由调用方按资源池实际余量给出。超报但仍在余量内的候选可以跑完。
        """
        self._root = Path(root).expanduser().resolve()
        if not self._root.is_dir():
            raise SandboxError(f"sandbox root is not a directory: {self._root}")
        self.output_limit_bytes = max(1024, int(output_limit_bytes))
        if memory_limit_bytes is not None and int(memory_limit_bytes) <= 0:
            raise SandboxError("memory_limit_bytes must be greater than 0")
        self.memory_limit_bytes = (
            int(memory_limit_bytes) if memory_limit_bytes is not None else None
        )
        if memory_hard_limit_bytes is not None and int(memory_hard_limit_bytes) <= 0:
            raise SandboxError("memory_hard_limit_bytes must be greater than 0")
        hard = (
            int(memory_hard_limit_bytes)
            if memory_hard_limit_bytes is not None
            else self.memory_limit_bytes
        )
        # 硬阈值不得低于申报值，否则软限额会比申报值更严格。
        if hard is not None and self.memory_limit_bytes is not None:
            hard = max(hard, self.memory_limit_bytes)
        self.memory_hard_limit_bytes = hard
        self.termination_grace_sec = max(0.1, float(termination_grace_sec))
        self.identity = identity
        strategy = str(memory_limit_strategy).strip().lower()
        if strategy == "auto":
            strategy = "address_space"
        if strategy not in {"address_space", "rss"}:
            raise SandboxError(
                "memory_limit_strategy 必须是 auto、address_space 或 rss"
            )
        self.memory_limit_strategy = strategy
        self.memory_monitor_interval_sec = max(
            0.02, float(memory_monitor_interval_sec)
        )

    @property
    def root(self) -> Path:
        """返回当前沙箱根目录。"""
        return self._root

    def _resolve_cwd(self, cwd: str | Path | None) -> Path:
        """解析并校验命令工作目录。"""
        if cwd is None:
            candidate = self._root
        else:
            raw = Path(cwd)
            candidate = raw if raw.is_absolute() else self._root / raw
            candidate = candidate.resolve()
        if not _inside(self._root, candidate) or not candidate.is_dir():
            raise SandboxError(f"sandbox cwd must be inside root: {candidate}")
        return candidate

    def _environment(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        """构建沙箱子进程环境。"""
        environment = os.environ.copy()
        # 避免把管理端虚拟环境和远程编辑器进程细节泄漏到独立分支命令中。
        environment.pop("VIRTUAL_ENV", None)
        for key in list(environment):
            if key.startswith("VSCODE_"):
                environment.pop(key)
        environment.update(
            {
                "FAMOU_SANDBOX_ROOT": str(self._root),
                "FAMOU_HIDDEN_EVALUATOR": "forbidden",
            }
        )
        if extra:
            environment.update({str(key): str(value) for key, value in extra.items()})
        return environment

    def _execution_argv(self, argv: tuple[str, ...]) -> list[str]:
        """使用 prlimit 和 setpriv 包装原始命令。"""

        wrapped = list(argv)
        if (
            self.memory_hard_limit_bytes is not None
            and self.memory_limit_strategy == "address_space"
        ):
            prlimit = shutil.which("prlimit")
            if prlimit is None:
                raise SandboxError("memory isolation requires the prlimit executable")
            wrapped = [
                prlimit,
                # 硬阈值来自资源池余量；仅超出自己申报值不应被内核直接杀掉。
                f"--as={self.memory_hard_limit_bytes}",
                "--",
                *wrapped,
            ]
        if self.identity is not None:
            setpriv = shutil.which("setpriv")
            if setpriv is None:
                raise SandboxError("privilege isolation requires the setpriv executable")
            wrapped = [
                setpriv,
                "--reuid",
                str(self.identity.uid),
                "--regid",
                str(self.identity.gid),
                "--clear-groups",
                "--no-new-privs",
                "--",
                *wrapped,
            ]
        return wrapped

    def _prepare_identity_root(self) -> None:
        """按配置把独立 Agent workspace 交给非特权身份。"""

        if self.identity is None or not self.identity.prepare_root_owner:
            return
        if os.geteuid() != 0:
            if os.geteuid() != self.identity.uid or os.getegid() != self.identity.gid:
                raise SandboxError("只有 root 可以准备不同 uid 的 Agent workspace")
            return
        paths = (self._root, *self._root.rglob("*"))
        owner_isolated = True
        for path in paths:
            try:
                os.chown(
                    path,
                    self.identity.uid,
                    self.identity.gid,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                # Agent workspace 可能包含并发更新的临时原子文件。
                continue
            except OSError as exc:
                if exc.errno not in {errno.EINVAL, errno.EPERM, errno.EOPNOTSUPP}:
                    raise
                owner_isolated = False
                break
        if owner_isolated:
            return

        # 某些 CFS 禁止容器内 chown。回退只作用于当前 Agent 专属 workspace，
        # 通过 other 位允许降权进程读写；绝不能对 run 根或 trusted/ 调用该逻辑。
        for path in (self._root, *self._root.rglob("*")):
            if path.is_symlink():
                continue
            try:
                mode = path.stat().st_mode & 0o777
                path.chmod(mode | (0o007 if path.is_dir() else 0o006))
            except FileNotFoundError:
                continue

    @staticmethod
    def _signal_process_group(process: subprocess.Popen[str], signum: int) -> None:
        """向候选独立进程组发送信号，避免遗留孙进程。"""
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return

    def _stop_process_group(
        self,
        process: subprocess.Popen[str],
    ) -> tuple[str, str]:
        """先终止再强杀整个候选进程组，并完整回收输出管道。"""
        self._signal_process_group(process, signal.SIGTERM)
        try:
            return process.communicate(timeout=self.termination_grace_sec)
        except subprocess.TimeoutExpired:
            self._signal_process_group(process, signal.SIGKILL)
            return process.communicate()

    @staticmethod
    def _process_group_rss_bytes(process_group_id: int) -> int:
        """汇总进程组当前的常驻主存，避免 CUDA 映射污染统计。"""

        page_size = os.sysconf("SC_PAGE_SIZE")
        total = 0
        try:
            entries = tuple(os.scandir("/proc"))
        except OSError:
            return 0
        for entry in entries:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                if os.getpgid(pid) != process_group_id:
                    continue
                fields = Path(entry.path, "statm").read_text(
                    encoding="utf-8"
                ).split()
                if len(fields) >= 2:
                    total += int(fields[1]) * page_size
            except (OSError, ValueError):
                # 进程可能恰好退出，或 /proc 对该进程不可读。
                continue
        return total

    def _start_memory_monitor(
        self,
        process: subprocess.Popen[str],
    ) -> tuple[threading.Event, threading.Thread | None, dict[str, object]]:
        """为 GPU Candidate 监控进程组 RSS，而不是限制虚拟地址空间。"""

        stop = threading.Event()
        state: dict[str, object] = {
            "peak": 0,
            "exceeded": False,
            "over_request": False,
        }
        limit = self.memory_hard_limit_bytes
        request = self.memory_limit_bytes
        if limit is None or self.memory_limit_strategy != "rss":
            return stop, None, state

        def monitor() -> None:
            """周期采样 RSS；越过资源池余量时才终止当前 Candidate 进程组。

            仅超出自己申报值不终止——只要余量还够，让它跑完比杀掉更划算；
            ``over_request`` 记录这一事实，供后续校准申报值。
            """

            peak = 0
            while not stop.is_set():
                usage = self._process_group_rss_bytes(process.pid)
                peak = max(peak, usage)
                if request is not None and usage > request:
                    state["over_request"] = True
                if usage > limit:
                    state["exceeded"] = True
                    self._signal_process_group(process, signal.SIGTERM)
                    break
                if stop.wait(self.memory_monitor_interval_sec):
                    break
            state["peak"] = peak

        thread = threading.Thread(
            target=monitor,
            name=f"famou-memory-monitor-{process.pid}",
            daemon=True,
        )
        thread.start()
        return stop, thread, state

    @staticmethod
    def _cuda_out_of_memory(*, stdout: str, stderr: str) -> bool:
        """识别 CUDA 分配失败，避免误报成主存超限。"""

        output = f"{stdout}\n{stderr}".lower()
        return "cuda out of memory" in output or (
            "torch.outofmemoryerror" in output and "cuda" in output
        )

    def _memory_limit_exceeded(
        self,
        *,
        returncode: int,
        stdout: str,
        stderr: str,
        timed_out: bool,
    ) -> bool:
        """根据受限进程的退出信号和标准错误识别内存边界失败。"""
        # 判据取实际生效的硬阈值：申报值可能为空（未声明资源），但只要
        # 硬阈值存在，prlimit 就已经在限制该进程。
        if self.memory_hard_limit_bytes is None or timed_out:
            return False
        output = f"{stdout}\n{stderr}".lower()
        if self._cuda_out_of_memory(stdout=stdout, stderr=stderr):
            return False
        markers = (
            "memoryerror",
            "cannot allocate memory",
            "unable to allocate",
            "out of memory",
            "std::bad_alloc",
            "arraymemoryerror",
        )
        return returncode in {-signal.SIGKILL, 128 + signal.SIGKILL} or any(
            marker in output for marker in markers
        )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        cancel_file: str | Path | None = None,
    ) -> SandboxRunResult:
        """执行当前组件的运行流程。"""
        if isinstance(command, (str, bytes)) or not command:
            raise SandboxError("sandbox command must be a non-empty argv sequence")
        argv = tuple(str(item) for item in command)
        execution_cwd = self._resolve_cwd(cwd)
        self._prepare_identity_root()
        started = time.monotonic()
        timed_out = False
        cancelled = False
        process: subprocess.Popen[str] | None = None
        memory_stop: threading.Event | None = None
        memory_thread: threading.Thread | None = None
        memory_state: dict[str, object] = {"peak": 0, "exceeded": False}
        try:
            process = subprocess.Popen(
                self._execution_argv(argv),
                cwd=str(execution_cwd),
                env=self._environment(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # 每条 Candidate 使用独立进程组；超时和取消必须清理完整子进程树。
                start_new_session=True,
            )
            memory_stop, memory_thread, memory_state = self._start_memory_monitor(
                process
            )
            deadline = (
                time.monotonic() + float(timeout_sec)
                if timeout_sec is not None
                else None
            )
            cancel_path = (
                Path(cancel_file).expanduser().resolve()
                if cancel_file is not None
                else None
            )
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_path is not None and cancel_path.is_file():
                        # 这是**我们自己**发的 SIGTERM（研究墙钟到点、任务被停）。
                        # 不记下来的话，下游只看到 returncode=-15 且 stderr 为空
                        # ——`_stop_process_group` 杀完进程组后 communicate 通常
                        # 什么都收不到——于是被当成"Agent 写的脚本挂了"。线上 13 次
                        # attempt 就是这样被误判成 canonical_process_failed 的。
                        cancelled = True
                        stdout, stderr = self._stop_process_group(process)
                        returncode = int(
                            process.returncode
                            if process.returncode is not None
                            else -signal.SIGTERM
                        )
                        break
                    if deadline is not None and time.monotonic() >= deadline:
                        timed_out = True
                        stdout, stderr = self._stop_process_group(process)
                        returncode = int(
                            process.returncode
                            if process.returncode is not None
                            else -signal.SIGKILL
                        )
                        break
            if process.returncode is not None:
                returncode = int(process.returncode)
        except BaseException:
            if process is not None and process.poll() is None:
                self._stop_process_group(process)
            raise
        finally:
            if memory_stop is not None:
                memory_stop.set()
            if memory_thread is not None:
                memory_thread.join(
                    timeout=max(1.0, self.memory_monitor_interval_sec * 2)
                )
        stdout = stdout or ""
        stderr = stderr or ""
        memory_limit_exceeded = bool(memory_state.get("exceeded", False)) or (
            self.memory_limit_strategy == "address_space"
            and self._memory_limit_exceeded(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
            )
        )
        cuda_out_of_memory = self._cuda_out_of_memory(
            stdout=stdout,
            stderr=stderr,
        )
        if timed_out:
            termination_reason = "timeout"
        elif cancelled:
            termination_reason = "cancelled"
        elif memory_limit_exceeded:
            termination_reason = "memory_limit_exceeded"
        elif cuda_out_of_memory:
            termination_reason = "cuda_out_of_memory"
        elif returncode < 0:
            termination_reason = f"signal_{-returncode}"
        elif returncode != 0:
            termination_reason = "nonzero_exit"
        else:
            termination_reason = "completed"
        duration_ms = int((time.monotonic() - started) * 1000)
        return SandboxRunResult(
            command=argv,
            cwd=str(execution_cwd),
            returncode=returncode,
            stdout=_truncate(stdout, self.output_limit_bytes),
            stderr=_truncate(stderr, self.output_limit_bytes),
            timed_out=timed_out,
            duration_ms=duration_ms,
            memory_limit_bytes=self.memory_limit_bytes,
            memory_limit_exceeded=memory_limit_exceeded,
            memory_limit_strategy=self.memory_limit_strategy,
            memory_hard_limit_bytes=self.memory_hard_limit_bytes,
            memory_over_request=bool(memory_state.get("over_request", False)),
            observed_memory_bytes=(
                int(memory_state.get("peak") or 0)
                if self.memory_hard_limit_bytes is not None
                and self.memory_limit_strategy == "rss"
                else None
            ),
            termination_reason=termination_reason,
            process_group_isolated=True,
            cuda_out_of_memory=cuda_out_of_memory,
            cancelled=cancelled,
        )

    def close(self) -> None:
        """关闭运行后端并释放资源。"""


class FmJobSandbox:
    """在 FMJob 独立容器中执行命令，并通过 CFS 交接 workspace。

    该 backend 不复制 workspace 内容，也不把 Controller 路径作为 Agent 输入；
    ``fm-job --subpath`` 负责让同一绝对 CFS 路径在容器内可见。命令生成保持
    argv/环境白名单，避免把控制面环境整体传入不可信容器。
    """

    def __init__(
        self,
        root: str | Path,
        *,
        image: str,
        fm_job_bin: str = "fm-job",
        prefix: str = "famou-terminal",
        cpu: str = "4",
        memory: str = "8Gi",
        gpu: int = 0,
        shm_size: str = "8Gi",
        subpath: str | Path | None = None,
        artifact_paths: Sequence[str] = (),
        artifact_export_root: str | Path | None = None,
        input_paths: Mapping[str, str | Path] | None = None,
        output_limit_bytes: int = 256 * 1024,
        persistent: bool = False,
        worker_poll_sec: float = 0.1,
    ):
        self._root = Path(root).expanduser().resolve()
        if not self._root.is_dir():
            raise SandboxError(f"fmjob sandbox root is not a directory: {self._root}")
        if not str(image).strip():
            raise SandboxError("fmjob sandbox requires a non-empty image")
        self.image = str(image)
        self.fm_job_bin = str(fm_job_bin)
        # fm-job names the Job ``<prefix>-<timestamp to the second>``; two
        # sandboxes launched in the same second under the same prefix collide
        # with "jobs.batch ... already exists". Give every sandbox instance its
        # own prefix so concurrent trials cannot share a Job name.
        self.prefix = f"{str(prefix)}-{secrets.token_hex(2)}"
        self.cpu = str(cpu)
        self.memory = str(memory)
        self.gpu = int(gpu)
        self.shm_size = str(shm_size)
        self.subpath = Path(subpath or self._root).expanduser().resolve()
        self.artifact_paths = tuple(str(item) for item in artifact_paths)
        if any(not item.startswith("/") for item in self.artifact_paths):
            raise SandboxError("fmjob artifact paths must be absolute container paths")
        self.artifact_export_root = (
            Path(artifact_export_root).expanduser().resolve()
            if artifact_export_root is not None
            else None
        )
        self.input_paths = {
            str(target): Path(source).expanduser().resolve()
            for target, source in (input_paths or {}).items()
        }
        if any(not target.startswith("/") for target in self.input_paths):
            raise SandboxError("fmjob input paths must use absolute container targets")
        self.output_limit_bytes = max(1024, int(output_limit_bytes))
        self.persistent = bool(persistent)
        self.worker_poll_sec = max(0.02, float(worker_poll_sec))
        self._worker_process: subprocess.Popen[bytes] | None = None
        # ``fm-job run --no-wait`` exits after submitting the remote Job.  Its
        # local client process is therefore not a liveness signal for the
        # long-running worker inside that Job.
        self._worker_submitted = False
        self._worker_lock = threading.Lock()
        self._worker_seq = 0
        self._worker_dir = self._root / ".fmjob-worker"
        self._worker_launch_stdout = self._worker_dir / "launch.stdout"
        self._worker_launch_stderr = self._worker_dir / "launch.stderr"

    def _fmjob_subpath(self) -> str:
        """Return the relative path expected by FMJob's CFS mount.

        FMJob resolves ``--subpath`` below the shared CFS ``/workspace``
        root.  Passing the host's ``/path/to/workspace`` prefix makes
        the Job start successfully but leaves the requested directory
        unmounted, which is particularly confusing for artifact handoff.
        Local/fake FMJob binaries still receive the original path.
        """

        marker = Path("/path/to/workspace")
        try:
            relative = self.subpath.relative_to(marker)
        except ValueError:
            return str(self.subpath)
        return str(relative)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve_cwd(self, cwd: str | Path | None) -> Path:
        candidate = self._root if cwd is None else Path(cwd).expanduser().resolve()
        if not _inside(self._root, candidate) or not candidate.is_dir():
            raise SandboxError(f"fmjob sandbox cwd must be inside root: {candidate}")
        return candidate

    def _remote_script(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        command_timeout_sec: float | None = None,
    ) -> str:
        lines = [f"cd {shlex.quote(str(cwd))}"]
        for target, source in self.input_paths.items():
            lines.extend(
                [
                    f"mkdir -p {shlex.quote(target)}",
                    f"if [ -d {shlex.quote(str(source))} ]; then cp -a {shlex.quote(str(source))}/. {shlex.quote(target)}/; "
                    f"elif [ -f {shlex.quote(str(source))} ]; then cp -a {shlex.quote(str(source))} {shlex.quote(target)}/; "
                    f"else echo 'Missing FMJob input: {target}' >&2; exit 66; fi",
                ]
            )
        for key, value in (env or {}).items():
            # AgentTurn 只传入 FAMOU_* 和显式运行时变量；拒绝 shell 注入型 key。
            name = str(key)
            if not name or not name.replace("_", "a").isalnum() or not name[0].isalpha():
                raise SandboxError(f"invalid fmjob environment key: {name!r}")
            lines.append(f"export {name}={shlex.quote(str(value))}")
        command_line = " ".join(shlex.quote(str(item)) for item in command)
        if command_timeout_sec is not None:
            timeout = max(0.1, float(command_timeout_sec))
            command_line = (
                f"timeout --signal=TERM --kill-after=10s {timeout:.3f}s "
                f"{command_line}"
            )
        export_dir = None
        if self.artifact_paths and self.artifact_export_root is not None:
            raw_round = str((env or {}).get("FAMOU_TERMINAL_ROUND") or "0")
            try:
                round_no = int(raw_round)
            except ValueError as exc:
                raise SandboxError(f"invalid terminal round: {raw_round!r}") from exc
            if round_no < 0:
                raise SandboxError(f"invalid terminal round: {raw_round!r}")
            export_dir = self.artifact_export_root / f"round_{round_no}"
            if round_no > 0:
                previous_export = self.artifact_export_root / f"round_{round_no - 1}"
                for artifact in self.artifact_paths:
                    previous = previous_export / artifact.lstrip("/")
                    target = Path(artifact)
                    lines.extend(
                        [
                            f"if [ -e {shlex.quote(str(previous))} ]; then",
                            f"  rm -rf -- {shlex.quote(str(target))}",
                            f"  mkdir -p {shlex.quote(str(target.parent))}",
                            f"  cp -a -- {shlex.quote(str(previous))} {shlex.quote(str(target))}",
                            "fi",
                        ]
                    )
            lines.extend(
                [
                    "set +e",
                    command_line,
                    "agent_rc=$?",
                    f"mkdir -p {shlex.quote(str(export_dir))}",
                ]
            )
            for artifact in self.artifact_paths:
                destination = export_dir / artifact.lstrip("/")
                lines.extend(
                    [
                        # The Solver's canonical artifact remains untouched.
                        # Replace only this round's CFS snapshot target so a
                        # replay cannot nest directories or retain stale files.
                        f"rm -rf -- {shlex.quote(str(destination))}",
                        f"mkdir -p {shlex.quote(str(destination.parent))}",
                        f"if [ -e {shlex.quote(artifact)} ]; then",
                        f"  cp -a -- {shlex.quote(artifact)} {shlex.quote(str(destination))}",
                        "else",
                        f"  echo 'Missing FMJob artifact: {artifact}' >&2",
                        "  artifact_missing=1",
                        "fi",
                    ]
                )
            lines.append("exit \"$agent_rc\"")
        else:
            lines.append("exec " + command_line)
        return "\n".join(lines)

    def _fmjob_args(self, script: str, *, no_wait: bool = False) -> list[str]:
        """Construct one FMJob invocation for a shell script."""
        args = [self.fm_job_bin, "run"]
        if no_wait:
            # The persistent worker is intentionally long-lived: requests are
            # exchanged through the task-scoped CFS directory. Waiting for the
            # worker Job to finish makes the fm-job client look failed while
            # the remote worker is still healthy, which can trigger a
            # duplicate worker and reuse the same Claude session.
            args.append("--no-wait")
        args.extend([
            "--prefix",
            self.prefix,
            "--image",
            self.image,
            "--gpu",
            str(self.gpu),
            "--cpu",
            self.cpu,
            "--memory",
            self.memory,
            "--shm-size",
            self.shm_size,
            "--subpath",
            self._fmjob_subpath(),
            "--",
            "bash",
            "-lc",
            script,
        ])
        return args

    def _worker_script(self) -> str:
        control = shlex.quote(str(self._worker_dir))
        return f"""set -eu
control={control}
mkdir -p "$control/requests" "$control/running" "$control/responses"
trap 'touch "$control/stop"' TERM INT
while [ ! -f "$control/stop" ]; do
  request=""
  for candidate in "$control"/requests/*.sh; do
    if [ -f "$candidate" ]; then request="$candidate"; break; fi
  done
  if [ -z "$request" ]; then sleep {self.worker_poll_sec:.3f}; continue; fi
  name="${{request##*/}}"
  id="${{name%.sh}}"
  running="$control/running/$name"
  mv "$request" "$running" 2>/dev/null || continue
  set +e
  bash "$running" >"$control/responses/$id.stdout" 2>"$control/responses/$id.stderr"
  rc=$?
  set -e
  printf '%s\\n' "$rc" >"$control/responses/$id.rc"
  touch "$control/responses/$id.done"
  rm -f "$running"
done
"""

    def _ensure_worker(self) -> None:
        if self._worker_submitted:
            return
        self._worker_dir.mkdir(parents=True, exist_ok=True)
        (self._worker_dir / "requests").mkdir(parents=True, exist_ok=True)
        (self._worker_dir / "running").mkdir(parents=True, exist_ok=True)
        (self._worker_dir / "responses").mkdir(parents=True, exist_ok=True)
        for stale in (self._worker_dir / "stop",):
            stale.unlink(missing_ok=True)
        script_path = self._worker_dir / "worker.sh"
        script_path.write_text(self._worker_script(), encoding="utf-8")
        script_path.chmod(0o700)
        with self._worker_launch_stdout.open("wb") as stdout_stream, self._worker_launch_stderr.open("wb") as stderr_stream:
            self._worker_process = subprocess.Popen(
                self._fmjob_args(
                    "cd "
                    + shlex.quote(str(self._root))
                    + "\nexec bash "
                    + shlex.quote(str(script_path)),
                    no_wait=True,
                ),
                cwd=str(self._root),
                stdout=stdout_stream,
                stderr=stderr_stream,
            )
        self._worker_submitted = True

    def _worker_launch_failure(self) -> str | None:
        """Return diagnostics when the FMJob client failed before submission."""

        process = self._worker_process
        if process is None:
            return "persistent FMJob worker process was not created"
        returncode = process.poll()
        # A zero exit may mean the client submitted with --no-wait semantics;
        # the remote worker remains authoritative after that point.
        if returncode is None or returncode == 0:
            return None
        stdout = _truncate(
            self._worker_launch_stdout.read_text(encoding="utf-8", errors="replace")
            if self._worker_launch_stdout.exists()
            else "",
            self.output_limit_bytes,
        )
        stderr = _truncate(
            self._worker_launch_stderr.read_text(encoding="utf-8", errors="replace")
            if self._worker_launch_stderr.exists()
            else "",
            self.output_limit_bytes,
        )
        detail = stderr.strip() or stdout.strip() or "no client diagnostics"
        return f"persistent FMJob worker launch failed (exit {returncode}): {detail}"

    def _run_persistent(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        timeout_sec: float | None,
    ) -> SandboxRunResult:
        """Run one request inside the task-scoped FMJob worker."""
        with self._worker_lock:
            self._ensure_worker()
            self._worker_seq += 1
            request_id = f"request-{os.getpid()}-{self._worker_seq}-{time.time_ns()}"
            request_path = self._worker_dir / "requests" / f"{request_id}.sh"
            response_dir = self._worker_dir / "responses"
            response_dir.mkdir(parents=True, exist_ok=True)
            script = self._remote_script(
                command,
                cwd=cwd,
                env=env,
                command_timeout_sec=timeout_sec,
            )
            temporary = request_path.with_suffix(".partial")
            temporary.write_text(script + "\n", encoding="utf-8")
            temporary.chmod(0o700)
            temporary.replace(request_path)
            started = time.monotonic()
            done = response_dir / f"{request_id}.done"
            rc_path = response_dir / f"{request_id}.rc"
            stdout_path = response_dir / f"{request_id}.stdout"
            stderr_path = response_dir / f"{request_id}.stderr"
            wait_limit = (float(timeout_sec) if timeout_sec is not None else 3600.0) + 60.0
            deadline = started + max(60.0, wait_limit)
            worker_restarts = 0
            while not done.exists():
                launch_failure = self._worker_launch_failure()
                if launch_failure is not None:
                    # A persistent FMJob can disappear while an Agent request is
                    # running (for example after a pod eviction). Recreate it once
                    # and replay the same request from the shared CFS workspace.
                    # A second failure is surfaced as infrastructure_error so the
                    # graph cannot enter an unbounded refine loop.
                    if worker_restarts == 0:
                        worker_restarts += 1
                        for source in (
                            self._worker_launch_stdout,
                            self._worker_launch_stderr,
                        ):
                            if source.exists():
                                shutil.copyfile(
                                    source,
                                    source.with_name(source.name + ".restart-1"),
                                )
                        running = self._worker_dir / "running" / request_path.name
                        if running.exists():
                            running.replace(request_path)
                        elif not request_path.exists():
                            temporary.write_text(script + "\n", encoding="utf-8")
                            temporary.chmod(0o700)
                            temporary.replace(request_path)
                        self._worker_process = None
                        self._worker_submitted = False
                        if "already exists" in launch_failure:
                            # Job-name collision: relaunching within the same
                            # second reproduces the same name. Wait past it.
                            time.sleep(1.5)
                        self._ensure_worker()
                        continue
                    return SandboxRunResult(
                        command=tuple(str(item) for item in command),
                        cwd=str(cwd),
                        returncode=70,
                        stdout="",
                        stderr=launch_failure,
                        timed_out=False,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        termination_reason="infrastructure_error",
                    )
                if time.monotonic() >= deadline:
                    return SandboxRunResult(
                        command=tuple(str(item) for item in command),
                        cwd=str(cwd),
                        returncode=-signal.SIGTERM,
                        stdout=stdout_path.read_text(encoding="utf-8", errors="replace")
                        if stdout_path.exists()
                        else "",
                        stderr="persistent FMJob request timeout",
                        timed_out=True,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        termination_reason="timeout",
                    )
                time.sleep(self.worker_poll_sec)
            try:
                returncode = int(rc_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                returncode = 70
            stdout = _truncate(
                stdout_path.read_text(encoding="utf-8", errors="replace")
                if stdout_path.exists()
                else "",
                self.output_limit_bytes,
            )
            stderr = _truncate(
                stderr_path.read_text(encoding="utf-8", errors="replace")
                if stderr_path.exists()
                else "",
                self.output_limit_bytes,
            )
            for path in (done, rc_path, stdout_path, stderr_path):
                path.unlink(missing_ok=True)
            return SandboxRunResult(
                command=tuple(str(item) for item in command),
                cwd=str(cwd),
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=returncode == 124,
                duration_ms=int((time.monotonic() - started) * 1000),
                termination_reason="timeout" if returncode == 124 else (
                    "completed" if returncode == 0 else "nonzero_exit"
                ),
            )

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_sec: float | None = None,
        cancel_file: str | Path | None = None,
    ) -> SandboxRunResult:
        if isinstance(command, (str, bytes)) or not command:
            raise SandboxError("fmjob sandbox command must be a non-empty argv sequence")
        if cancel_file is not None and Path(cancel_file).expanduser().is_file():
            return SandboxRunResult(
                command=tuple(str(item) for item in command),
                cwd=str(self._resolve_cwd(cwd)),
                returncode=-signal.SIGTERM,
                stdout="",
                stderr="cancelled before fmjob submission",
                timed_out=False,
                duration_ms=0,
                termination_reason="cancelled",
                cancelled=True,
            )
        execution_cwd = self._resolve_cwd(cwd)
        if self.persistent:
            return self._run_persistent(
                command,
                cwd=execution_cwd,
                env=env,
                timeout_sec=timeout_sec,
            )
        script = self._remote_script(command, cwd=execution_cwd, env=env)
        args = self._fmjob_args(script)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                cwd=str(self._root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=float(timeout_sec) if timeout_sec is not None else None,
            )
            timed_out = False
            returncode = int(proc.returncode)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -signal.SIGTERM
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            stderr += "\nfm-job client timeout; remote cancellation is backend-specific"
        duration_ms = int((time.monotonic() - started) * 1000)
        termination_reason = "timeout" if timed_out else (
            "completed" if returncode == 0 else "nonzero_exit"
        )
        return SandboxRunResult(
            command=tuple(str(item) for item in command),
            cwd=str(execution_cwd),
            returncode=returncode,
            stdout=_truncate(stdout, self.output_limit_bytes),
            stderr=_truncate(stderr, self.output_limit_bytes),
            timed_out=timed_out,
            duration_ms=duration_ms,
            termination_reason=termination_reason,
            process_group_isolated=False,
        )

    def close(self) -> None:
        """停止任务级 FMJob worker；兼容一次性模式的空操作。"""
        process = self._worker_process
        if process is None:
            return None
        (self._worker_dir / "stop").touch()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._worker_process = None
        self._worker_submitted = False


def sandbox_from_config(
    config: Mapping[str, object] | None,
    root: str | Path,
    *,
    fallback: Mapping[str, object] | None = None,
) -> ExecutionSandbox:
    """根据配置创建沙箱后端。

    ``fallback`` 保留对旧版 worker 调用约定的兼容性。显式 ``config`` 的
    值优先于 fallback，避免不同版本的 worker 与运行时镜像不一致时在
    收尾阶段直接抛出 ``unexpected keyword argument``。
    """

    cfg: dict[str, object] = {}
    if isinstance(fallback, Mapping):
        cfg.update(fallback)
    if isinstance(config, Mapping):
        cfg.update(config)
    backend = str(cfg.get("type") or "local").lower()
    if backend in {"local", "process", "subprocess"}:
        identity = None
        if cfg.get("run_as_uid") is not None or cfg.get("run_as_gid") is not None:
            if cfg.get("run_as_uid") is None or cfg.get("run_as_gid") is None:
                raise SandboxError("run_as_uid 和 run_as_gid 必须同时配置")
            identity = ExecutionIdentity(
                uid=int(cfg["run_as_uid"]),
                gid=int(cfg["run_as_gid"]),
                prepare_root_owner=bool(cfg.get("prepare_root_owner", False)),
            )
        return LocalSandbox(
            root,
            output_limit_bytes=int(cfg.get("output_limit_bytes") or 256 * 1024),
            memory_limit_bytes=(
                int(cfg["memory_limit_bytes"])
                if cfg.get("memory_limit_bytes") is not None
                else None
            ),
            termination_grace_sec=float(cfg.get("termination_grace_sec") or 5.0),
            identity=identity,
            memory_limit_strategy=str(
                cfg.get("memory_limit_strategy") or "auto"
            ),
            memory_monitor_interval_sec=float(
                cfg.get("memory_monitor_interval_sec") or 0.1
            ),
        )
    if backend == "docker":
        raise SandboxError(
            "DockerSandbox is not enabled in Loop V1; use type=local or add the "
            "container backend explicitly."
        )
    if backend in {"fmjob", "fm-job"}:
        return FmJobSandbox(
            root,
            image=str(cfg.get("image") or ""),
            fm_job_bin=str(cfg.get("fm_job_bin") or "fm-job"),
            prefix=str(cfg.get("prefix") or "famou-terminal"),
            cpu=str(cfg.get("cpu") or "4"),
            memory=str(cfg.get("memory") or "8Gi"),
            gpu=int(cfg.get("gpu") or 0),
            shm_size=str(cfg.get("shm_size") or "8Gi"),
            subpath=cfg.get("subpath") or root,
            output_limit_bytes=int(cfg.get("output_limit_bytes") or 256 * 1024),
            artifact_paths=tuple(str(item) for item in cfg.get("artifact_paths", ()) or ()),
            artifact_export_root=cfg.get("artifact_export_root"),
            persistent=bool(cfg.get("persistent", False)),
            worker_poll_sec=float(cfg.get("worker_poll_sec") or 0.1),
            input_paths=(
                cfg.get("input_paths")
                if isinstance(cfg.get("input_paths"), Mapping)
                else None
            ),
        )
    raise SandboxError(f"unsupported Loop sandbox backend: {backend!r}")
