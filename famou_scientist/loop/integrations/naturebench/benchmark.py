"""NatureBench 公开任务、候选执行与 Artifact 生成适配。"""
from __future__ import annotations

import ast
import errno
import os
import shlex
import shutil
import sys
from itertools import islice
from pathlib import Path
from typing import Any, Mapping

from ...utils import new_id, now_ms
from ...execution.sandbox import (
    ExecutionIdentity,
    LocalSandbox,
    process_failure_message,
    signal_name,
)
from ...facilities import CandidateRef, RunnerBenchmarkFacility, TaskView

# 空提交诊断里最多列几个文件名，以及最多扫描多少个文件（暂存区可能有几十万个缓存文件）。
_HINT_MAX_NAMES = 8
_HINT_SCAN_LIMIT = 200


def _empty_submission_hint(staging_submission: Path, scratch: Path) -> str:
    """脚本退出码为 0 却没提交东西时，补一句**它到底把文件写哪去了**。

    以前只有干巴巴一句 "experiment produced an empty submission"，既不说
    ``OUTPUT_DIR`` 是哪个路径，也不说暂存区里其实堆着产物——而绝大多数空提交
    正是「写到了 cwd / TMPDIR，没写 OUTPUT_DIR」。这两个目录马上就要被删，
    所以必须在删之前把线索抓出来喂回 Agent。
    """

    parts = [f"OUTPUT_DIR={staging_submission}"]
    try:
        stray_dirs = sorted(
            path.name for path in staging_submission.iterdir() if path.is_dir()
        )
    except OSError:
        stray_dirs = []
    if stray_dirs:
        # 只有空目录、没有文件：目录建了，内容没落盘。
        parts.append("其中只有空目录：" + "、".join(stray_dirs[:_HINT_MAX_NAMES]))
    else:
        parts.append("该目录为空")
    try:
        # 暂存区里可能躺着几十万个缓存文件，只取够写一句话的量就停。
        scratch_files = [
            path
            for path in islice(scratch.rglob("*"), _HINT_SCAN_LIMIT)
            if path.is_file()
        ]
    except OSError:
        scratch_files = []
    if scratch_files:
        names = sorted(str(path.relative_to(scratch)) for path in scratch_files)
        parts.append(
            f"但 FAMOU_SCRATCH_DIR 下有文件（{'、'.join(names[:_HINT_MAX_NAMES])}）"
            "——产物很可能写进了暂存区而不是 OUTPUT_DIR"
        )
    return "；" + "；".join(parts)


def attempt_id_from_artifact(run_dir: Path, artifact_path: str) -> str:
    """从 NatureBench 受控提交目录提取稳定 Candidate 编号。"""

    artifact = Path(artifact_path).expanduser().resolve()
    try:
        relative = artifact.relative_to(run_dir / "candidates")
    except ValueError as exc:
        raise ValueError("submission artifact is outside the run candidates") from exc
    if len(relative.parts) != 3 or relative.parts[1:] != (
        "output",
        "submission",
    ):
        raise ValueError("submission artifact does not follow the candidate output contract")
    return relative.parts[0]


def _safe_scalar_metrics(value: Any) -> dict[str, Any]:
    """仅保留可以安全回传给 Agent 的标量字段。"""

    if not isinstance(value, dict):
        return {}
    blocked_tokens = (
        "example",
        "sample",
        "label",
        "prediction",
        "trace",
        "raw",
        "stdout",
        "stderr",
        "debug",
    )
    safe: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if any(token in name.lower() for token in blocked_tokens):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[name] = item
    return safe


def _safe_public_data(value: Any, *, depth: int = 0) -> Any:
    """完整保留可信 worker 已批准的 JSON 数据结构。"""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if depth >= 16:
        raise ValueError("benchmark public response nesting is too deep")
    if isinstance(value, list):
        return [_safe_public_data(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _safe_public_data(item, depth=depth + 1)
            for key, item in value.items()
        }
    raise TypeError(
        f"benchmark public response contains non-JSON value: {type(value).__name__}"
    )


def _agent_view(result: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """将公开或正式结果转换成不泄漏详细样本的 Agent 视图。"""

    actual_source = str(source or result.get("source") or "")
    is_official = actual_source == "official_evaluator"
    metric_key = "official_metrics" if is_official else "metrics"
    metric_value = result.get(metric_key)
    if is_official and not isinstance(metric_value, dict):
        # 兼容 transport 的统一协议仍只返回 metrics 的实现；官方性质由
        # operation/source 确定，不应因为字段命名差异丢掉正式分数。
        metric_value = result.get("metrics")
    safe: dict[str, Any] = {
        "benchmark": result.get("benchmark"),
        "source": actual_source,
        "valid": result.get("valid") is True,
        metric_key: _safe_scalar_metrics(metric_value),
        "redacted_for_agent": True,
    }
    for key in ("execution_id", "agent_log_dir", "stdout_path", "stderr_path"):
        if isinstance(result.get(key), str):
            safe[key] = result[key]
    diagnostics = result.get("diagnostics_public")
    if isinstance(diagnostics, dict):
        safe["diagnostics_public"] = _safe_scalar_metrics(diagnostics)
    extra_public = result.get("extra_public")
    if isinstance(extra_public, dict) and extra_public:
        # extra_public 只能由可信 benchmark adapter 显式生成，因此允许保留
        # instance -> metric 的有限嵌套结构。
        safe["extra"] = _safe_public_data(extra_public)
    else:
        extra = result.get("extra")
        metadata = result.get("metadata")
        already_redacted = result.get("redacted_for_agent") is True or (
            isinstance(metadata, dict)
            and metadata.get("redacted_for_agent") is True
        )
        if isinstance(extra, dict):
            safe["extra"] = (
                _safe_public_data(extra)
                if already_redacted
                else _safe_scalar_metrics(extra)
            )
    if result.get("valid") is not True and result.get("error"):
        safe["error"] = str(result["error"])
    return safe


class NatureBenchExperimentRunner:
    """按 NatureBench E2E Code Submission 契约运行冻结候选。"""

    def __init__(
        self,
        run_dir: str | Path,
        problem_dir: str | Path,
        *,
        task_id: str,
        timeout_sec: float,
        memory_limit_bytes: int | None = None,
        agent_uid: int | None = None,
        agent_gid: int | None = None,
    ):
        """保存公开数据、任务标识以及单次候选的时间和内存预算。"""

        self.run_dir = Path(run_dir).expanduser().resolve()
        self.problem_dir = Path(problem_dir).expanduser().resolve()
        self.task_id = str(task_id)
        self.timeout_sec = float(timeout_sec)
        self.memory_limit_bytes = (
            int(memory_limit_bytes) if memory_limit_bytes is not None else None
        )
        self.agent_identity = (
            ExecutionIdentity(
                uid=int(agent_uid),
                gid=int(agent_gid),
                prepare_root_owner=False,
            )
            if agent_uid is not None and agent_gid is not None
            else None
        )

    def preflight(self, branch: dict[str, Any]) -> dict[str, Any]:
        """在不访问隐藏数据的前提下检查入口文件和 Python 语法。"""

        entrypoint_value = branch.get("entrypoint")
        if not entrypoint_value:
            return {
                "valid": False,
                "source": "naturebench_runner_preflight",
                "error": "NatureBench candidate must declare run.py",
            }
        entrypoint = Path(str(entrypoint_value)).expanduser().resolve()
        method_dir = Path(
            str(branch.get("method_dir") or entrypoint.parent)
        ).expanduser().resolve()
        checks: dict[str, Any] = {
            "entrypoint_exists": entrypoint.is_file(),
            "entrypoint_in_method_dir": False,
            "python_syntax": None,
        }
        try:
            entrypoint.relative_to(method_dir)
            checks["entrypoint_in_method_dir"] = True
        except ValueError:
            pass

        error: str | None = None
        if not checks["entrypoint_exists"]:
            error = f"entrypoint 不存在: {entrypoint}"
        elif not checks["entrypoint_in_method_dir"]:
            error = "entrypoint 不在当前候选代码目录中"
        elif entrypoint.suffix == ".py":
            try:
                ast.parse(
                    entrypoint.read_text(encoding="utf-8"),
                    filename=str(entrypoint),
                )
                checks["python_syntax"] = True
            except (OSError, SyntaxError, UnicodeError) as exc:
                checks["python_syntax"] = False
                error = repr(exc)
        return {
            "valid": error is None,
            "source": "naturebench_runner_preflight",
            "entrypoint": str(entrypoint),
            "method_dir": str(method_dir),
            "checks": checks,
            "error": error,
        }

    def run(self, branch: dict[str, Any]) -> dict[str, Any]:
        """运行根目录 ``run.py`` 并形成分支内不可变 submission。"""

        branch_id = str(branch.get("branch_id") or branch.get("id") or "")
        candidate_id = str(branch.get("candidate_id") or "")
        candidate_root = Path(str(branch.get("candidate_dir") or "")).resolve()
        worktree = Path(
            str(branch.get("method_dir") or branch.get("worktree") or "")
        ).resolve()
        entrypoint = Path(str(branch.get("entrypoint") or "")).resolve()
        outputs_dir = Path(
            str(branch.get("candidate_output_dir") or branch.get("outputs_dir") or "")
        ).resolve()
        expected_candidate = self.run_dir / "candidates" / candidate_id
        valid_layout = (
            bool(candidate_id)
            and candidate_root == expected_candidate.resolve()
            and worktree == candidate_root / "code"
            and outputs_dir == candidate_root / "output"
        )
        sandbox_root = candidate_root
        try:
            entrypoint.relative_to(worktree)
        except ValueError:
            valid_layout = False
        if not valid_layout or not entrypoint.is_file():
            return {
                "id": new_id("run_failed"),
                "branch_id": branch_id,
                "source": "naturebench_experiment_runner",
                "valid": False,
                "returncode": 2,
                "artifact": "",
                "error": "invalid branch workspace or missing entrypoint",
                "stage": "canonical_run",
                "error_code": "canonical_invalid_workspace",
                "retryable": True,
                "timeout_sec": self.timeout_sec,
                "candidate_dir": str(candidate_root),
                "method_dir": str(worktree),
                "entrypoint": str(entrypoint),
                "created_at": now_ms(),
            }

        resource_request = (
            branch.get("resource_request")
            if isinstance(branch.get("resource_request"), dict)
            else {}
        )
        expected_runtime_sec = resource_request.get("expected_runtime_sec")
        if (
            expected_runtime_sec is not None
            and float(expected_runtime_sec) > self.timeout_sec
        ):
            # Agent 已经明确声明无法在 canonical 上限内完成时，立即把契约错误
            # 退回原 Actor。继续真实执行只会白白占满资源直到必然超时。
            return {
                "id": new_id("run_failed"),
                "branch_id": branch_id,
                "candidate_id": candidate_id or None,
                "source": "naturebench_experiment_runner",
                "valid": False,
                "returncode": 2,
                "timed_out": False,
                "artifact": "",
                "error": (
                    "declared runtime exceeds canonical time limit: "
                    f"{float(expected_runtime_sec):g}s > {self.timeout_sec:g}s"
                ),
                "stage": "canonical_run",
                "error_code": "canonical_runtime_budget_exceeded",
                "retryable": True,
                "timeout_sec": self.timeout_sec,
                "expected_runtime_sec": float(expected_runtime_sec),
                "command": shlex.join([sys.executable, str(entrypoint)]),
                "candidate_dir": str(candidate_root),
                "method_dir": str(worktree),
                "entrypoint": str(entrypoint),
                "resource_request": resource_request,
                "created_at": now_ms(),
            }

        # Candidate 只写临时目录。进程退出后由可信 Runner 复制为只读 submission，
        # 避免后台子进程或可变 worktree 在 Artifact 哈希生成后继续改写正式输入。
        submission = outputs_dir / "submission"
        staging_submission = outputs_dir / ".staging_submission"
        # canonical 复现跑在 `code/` 里，而 `code/` 是**冻结的只读快照**——
        # `code_snapshot.files` 的哈希就是拿它算的，让它可写等于放弃这份取证。
        # 但脚本天然会往自己旁边写缓存（`os.makedirs("_cache")`、
        # `open("diagnostics.json", "w")`），于是直接 PermissionError(13) 死掉：
        # 线上 8 次 attempt 全是这个签名（`code/_cache`、`code/.seam_cache`、
        # `code/monomer_cache.h5`、`code/diagnostics.json`、`output/logs`…）。
        # 所以显式给一个可写暂存区，并通过 `FAMOU_SCRATCH_DIR` / `TMPDIR` 告诉它。
        scratch = candidate_root / "scratch"
        for path in (submission, staging_submission, scratch):
            if path.exists():
                shutil.rmtree(path)
        staging_submission.mkdir(parents=True)
        scratch.mkdir(parents=True)
        if self.agent_identity is not None:
            if os.geteuid() != 0:
                raise PermissionError("非特权 Candidate staging 需要 root Supervisor")
            for path in (staging_submission, scratch):
                try:
                    os.chown(
                        path,
                        self.agent_identity.uid,
                        self.agent_identity.gid,
                    )
                except OSError as exc:
                    if exc.errno not in {errno.EINVAL, errno.EPERM, errno.EOPNOTSUPP}:
                        raise
                    # CFS 不支持 chown 时，仅对本 Candidate 的这两个目录开放写权限。
                    path.chmod(0o707)
                else:
                    path.chmod(0o700)
        requested_memory = resource_request.get("host_memory_gib")
        requested_memory_bytes = (
            int(float(requested_memory) * 1024**3)
            if requested_memory is not None
            else None
        )
        # 申报值只用于记录是否超报，不作为终止阈值：候选低估内存但资源池仍
        # 有余量时，让它跑完比杀掉更划算（历史 OOM 多为超出申报值 1%~9%）。
        # 真正的终止线取容器进程级上限。
        memory_limit_bytes = requested_memory_bytes
        memory_hard_limit_bytes = self.memory_limit_bytes or requested_memory_bytes
        gpu_request = (
            resource_request.get("gpu")
            if isinstance(resource_request.get("gpu"), dict)
            else {}
        )
        uses_gpu = int(gpu_request.get("device_count") or 0) > 0
        sandbox = LocalSandbox(
            sandbox_root,
            memory_limit_bytes=memory_limit_bytes,
            memory_hard_limit_bytes=memory_hard_limit_bytes,
            identity=self.agent_identity,
            # GPU 显存声明只用于 Resource Broker admission，不是 Candidate
            # 运行时硬上限。GPU 任务仅用 RSS 监控实际主存，避免 RLIMIT_AS
            # 把 CUDA 映射误判为主存占用。
            memory_limit_strategy="rss" if uses_gpu else "address_space",
        )
        try:
            result = sandbox.run(
                [sys.executable, str(entrypoint)],
                cwd=worktree,
                env={
                    "DATA_DIR": str(self.problem_dir / "data"),
                    "OUTPUT_DIR": str(staging_submission),
                    # 唯一可写的暂存区。`code/` 是只读快照，`output/` 除
                    # staging 外也只读，缓存/日志/中间产物必须落在这里。
                    # 顺带把 TMPDIR 也指过来：不少库（joblib、matplotlib、
                    # h5py 的临时文件）不看我们的环境变量，只看 TMPDIR。
                    "FAMOU_SCRATCH_DIR": str(scratch),
                    "TMPDIR": str(scratch),
                    "FAMOU_TASK_ID": self.task_id,
                    "FAMOU_ATTEMPT_ID": branch_id,
                    "CUDA_VISIBLE_DEVICES": str(
                        ((branch.get("resource_lease") or {}).get(
                            "cuda_visible_devices"
                        ))
                        or ""
                    ),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                timeout_sec=self.timeout_sec,
                cancel_file=self.run_dir / "agent_control" / "research_stop_requested.json",
            )
        finally:
            sandbox.close()
        unsafe_files = [
            path
            for path in staging_submission.rglob("*")
            if path.is_symlink() or (not path.is_file() and not path.is_dir())
        ]
        nonempty = any(path.is_file() for path in staging_submission.rglob("*"))
        # 两个暂存区在下面就被删了，空提交的诊断信息只能**在删除之前**取。
        empty_submission_hint = (
            "" if nonempty else _empty_submission_hint(staging_submission, scratch)
        )
        if result.valid and nonempty and not unsafe_files:
            shutil.copytree(staging_submission, submission, symlinks=False)
            for path in (submission, *submission.rglob("*")):
                path.chmod(0o555 if path.is_dir() else 0o444)
        shutil.rmtree(staging_submission, ignore_errors=True)
        # scratch 顾名思义是一次性的：缓存动辄几个 GB，90 题 × 十几次 attempt
        # 留着会把 CFS 撑爆。要留证据请写进 stdout 或 submission。
        shutil.rmtree(scratch, ignore_errors=True)
        error_code: str | None = None
        if result.valid and nonempty:
            error = None if not unsafe_files else "submission contains unsafe files"
            if unsafe_files:
                error_code = "canonical_unsafe_submission"
        elif result.cancelled:
            # 研究墙钟到点 / 任务被停时**是我们自己**给 canonical 进程发的 SIGTERM。
            # 这不是方法失败，不能进 ExpBank 当作"你的脚本挂了"喂回 Agent。
            error = "canonical run cancelled by controller (research stop)"
            error_code = "canonical_cancelled_by_controller"
        elif result.memory_limit_exceeded:
            error = "experiment exceeded canonical memory limit"
            error_code = "canonical_memory_limit_exceeded"
        elif result.cuda_out_of_memory:
            error = "experiment failed with CUDA out of memory"
            error_code = "canonical_cuda_out_of_memory"
        elif result.timed_out:
            error = "experiment exceeded canonical time limit"
            error_code = "canonical_timeout"
        elif result.valid:
            error = "experiment produced an empty submission" + empty_submission_hint
            error_code = "canonical_empty_submission"
        elif result.returncode < 0:
            # 非取消、非超时、非内存上限的信号死亡：外部（pod 抢占、内核 OOM
            # killer、容器重启）把进程打掉了。以前一律并进
            # `canonical_process_failed`，而这类死亡**通常连 stderr 都没有**
            # ——`_stop_process_group` 之后 communicate 收不到东西——于是记录里
            # 只剩一句 "experiment process failed"，事后完全无法诊断。
            killer = signal_name(result.returncode)
            error = f"canonical run killed by {killer}"
            error_code = "canonical_killed_by_signal"
        else:
            error = process_failure_message(result, subject="experiment")
            error_code = "canonical_process_failed"
        return {
            "id": new_id("experiment"),
            "branch_id": branch_id,
            "candidate_id": candidate_id or None,
            "source": "naturebench_experiment_runner",
            "valid": result.valid and nonempty and not unsafe_files,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "artifact": str(submission),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": error,
            "stage": "canonical_run",
            "error_code": error_code,
            "retryable": error is not None,
            "timeout_sec": self.timeout_sec,
            "expected_runtime_sec": expected_runtime_sec,
            "command": shlex.join([sys.executable, str(entrypoint)]),
            "candidate_dir": str(candidate_root),
            "method_dir": str(worktree),
            "entrypoint": str(entrypoint),
            "duration_ms": result.duration_ms,
            "memory_limit_bytes": result.memory_limit_bytes,
            "memory_limit_exceeded": result.memory_limit_exceeded,
            "memory_limit_strategy": result.memory_limit_strategy,
            "observed_memory_bytes": result.observed_memory_bytes,
            "termination_reason": result.termination_reason,
            "process_group_isolated": result.process_group_isolated,
            "cuda_out_of_memory": result.cuda_out_of_memory,
            "resource_request": resource_request,
            "resource_lease": branch.get("resource_lease"),
            "unsafe_submission_files": [str(path) for path in unsafe_files],
            "finished_at": now_ms(),
        }


class _NatureBenchPublicAdapter:
    """实现 NatureBench 不接触 GT 的提交快照检查。"""

    def __init__(self, *, run_dir: str | Path, benchmark_name: str):
        """保存当前 run 的受控候选目录。"""

        self.run_dir = Path(run_dir).expanduser().resolve()
        self.benchmark_name = str(benchmark_name)

    def validate_artifact(self, artifact_path: str) -> dict[str, Any]:
        """检查提交位于受控目录且至少包含一个普通文件。"""

        try:
            attempt_id = attempt_id_from_artifact(self.run_dir, artifact_path)
            artifact = Path(artifact_path).resolve()
            nonempty = artifact.is_dir() and any(
                path.is_file() for path in artifact.rglob("*")
            )
        except (OSError, ValueError) as exc:
            return {"valid": False, "error": str(exc), "artifact": artifact_path}
        return {
            "valid": nonempty,
            "artifact": artifact_path,
            "diagnostics_public": {
                "format_check": "passed" if nonempty else "empty_submission",
                "attempt_id": attempt_id,
            },
            "error": None if nonempty else "submission directory is empty",
        }

    def run_public_eval(self, artifact_path: str) -> dict[str, Any]:
        """返回公开预检，不读取 evaluator、metadata 或隐藏答案。"""

        validation = self.validate_artifact(artifact_path)
        return {
            "benchmark": self.benchmark_name,
            "source": "naturebench_public_preflight",
            "valid": validation.get("valid") is True,
            "metrics": {},
            "diagnostics_public": validation.get("diagnostics_public") or {},
            "extra": {},
            "stdout": "",
            "stderr": "",
            "artifact": artifact_path,
            "error": validation.get("error"),
            "created_at": now_ms(),
        }

    def run_official_eval(self, artifact_path: str) -> dict[str, Any]:
        """拒绝从公开 Benchmark Adapter 绕过可信评分设施。"""

        raise RuntimeError("NatureBench Benchmark Adapter 不提供 hidden/official 评分")

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """只向 Agent 暴露公开结果的安全字段。"""

        return _agent_view(result, source=source)


class NatureBenchBenchmarkFacility(RunnerBenchmarkFacility):
    """NatureBench 的公开 Task 与 E2E Code Submission Facility。"""

    def __init__(
        self,
        runner: NatureBenchExperimentRunner,
        *,
        run_dir: str | Path,
        benchmark_name: str,
        task_id: str,
    ):
        """组合候选 Runner 与公开提交检查器。"""

        super().__init__(
            runner,
            _NatureBenchPublicAdapter(
                run_dir=run_dir,
                benchmark_name=benchmark_name,
            ),
            task_id=task_id,
        )

    def task_view(self) -> TaskView:
        """返回只包含 NatureBench 公开 problem 的 TaskView。"""

        public_contract: dict[str, Any] = {}
        if self.task_id == "s42256-023-00628-2":
            test_dir = self.runner.problem_dir / "data" / "band_gap" / "test"
            test_count = len(
                [
                    path
                    for path in test_dir.glob("*.graphdata")
                    if path.is_file()
                ]
            )
            public_contract = {
                "band_gap": {
                    "prediction_file": "band_gap/predictions.json",
                    "id_source": "DATA_DIR/band_gap/test/*.graphdata",
                    "expected_test_count": test_count,
                    "require_exact_ids": True,
                }
            }

        return TaskView(
            task_id=self.task_id,
            public_path=str(self.runner.problem_dir),
            instructions="读取公开题面，并按 NatureBench 输出协议生成提交产物。",
            metadata={
                "entrypoint": "run.py",
                "entrypoint_interface": "读取 DATA_DIR，并把提交产物写入 OUTPUT_DIR",
                "input_environment": "DATA_DIR",
                "output_environment": "OUTPUT_DIR",
                "scratch_environment": "FAMOU_SCRATCH_DIR",
                # canonical 复现时**代码目录是只读快照**（要拿它算 code_snapshot
                # 哈希），`OUTPUT_DIR` 之外的输出目录同样只读。往自己旁边写缓存
                # 会直接 PermissionError(13) 把整次 attempt 打掉——线上出过 8 次。
                "writable_paths_contract": (
                    "run.py 所在目录只读，不要在其中创建缓存、日志或中间文件。"
                    "唯一可写的暂存目录是 FAMOU_SCRATCH_DIR（TMPDIR 也已指向它），"
                    "正式提交产物写 OUTPUT_DIR。FAMOU_SCRATCH_DIR 在本次 canonical "
                    "run 结束后会被清空，不要把需要留存的证据放在那里。"
                ),
                "public_output_contract": public_contract,
                # 这些都是 NatureBench 公开评分口径。Idea Agent 可以据此预测
                # 方案能否达到目标，但预测值不能替代正式 evaluator 结果。
                "score_interpretation": {
                    "metric": "aggregate_improvement",
                    "levels": [
                        {
                            "name": "below_sota",
                            "label": "未达到 SOTA",
                            "condition": "value < 0",
                        },
                        {
                            "name": "match_sota",
                            "label": "Match-SOTA",
                            "condition": "0 <= value <= 0.1",
                        },
                        {
                            "name": "surpass_sota",
                            "label": "Surpass-SOTA",
                            "condition": "value > 0.1",
                        },
                    ],
                    "primary_target": ["match_sota", "surpass_sota"],
                    "target_instruction": (
                        "首先达到 Match-SOTA，并在可行时继续争取 Surpass-SOTA；"
                        "正式结论只以 evaluator 返回值为准。"
                    ),
                },
            },
        )

    def preflight(
        self,
        candidate: CandidateRef,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """校验 NatureBench 当前版本要求的根目录 ``run.py``。"""

        expected = (Path(candidate.code_path) / "run.py").resolve()
        actual = Path(candidate.entrypoint).resolve() if candidate.entrypoint else None
        if actual != expected or not expected.is_file():
            return {
                "valid": False,
                "source": "naturebench_task_contract",
                "checks": {"required_entrypoint": "run.py"},
                "error": "NatureBench task requires candidate entrypoint run.py",
            }
        return super().preflight(candidate, context=context)


__all__ = [
    "NatureBenchBenchmarkFacility",
    "NatureBenchExperimentRunner",
    "attempt_id_from_artifact",
]
