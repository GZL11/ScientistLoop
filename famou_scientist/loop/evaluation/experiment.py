"""实验队列使用的实验执行器。"""
from __future__ import annotations

import ast
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..utils import atomic_write_json, new_id, now_ms, safe_name

#: canonical run 的完整 stdout/stderr 落盘上限（单流）。超过只保尾部，但必须在
#: result 里记明原始字节数和截断标记——「被截断了」本身是读数，不能靠文件大小猜。
#: 64 MiB 足够装下几小时训练的全部输出；设上限只为防死循环刷屏写满 CFS。
RUN_LOG_MAX_BYTES = 64 * 1024 * 1024

#: 写进 run_dir 的宿主文件名。产物回退发现（见 `run()`）必须排除它们，否则
#: 「目录里恰好只有一个文件」这条判据会把日志当成方案产物。
RUN_DIR_HOST_FILES = frozenset({"runner.log", "result.json", "stdout.log", "stderr.log"})


def _persist_stream(path: Path, text: str) -> dict[str, Any]:
    """把一条完整输出流落盘，返回字节数与截断读数。

    切尾而不是切头：报错的 traceback 在尾部，日志爆量时最该留下的也是尾部。
    """

    raw = (text or "").encode("utf-8", errors="replace")
    truncated = len(raw) > RUN_LOG_MAX_BYTES
    body = raw[-RUN_LOG_MAX_BYTES:] if truncated else raw
    prefix = (
        f"[... 前 {len(raw) - len(body)} 字节已截断，原始 {len(raw)} 字节 ...]\n".encode(
            "utf-8"
        )
        if truncated
        else b""
    )
    try:
        path.write_bytes(prefix + body)
    except OSError as exc:  # 日志写不进去绝不能把 run 判死
        return {"path": None, "bytes": len(raw), "truncated": truncated, "error": str(exc)}
    return {"path": str(path), "bytes": len(raw), "truncated": truncated, "error": None}


class ExperimentRunner:
    """定义实验执行器接口。"""

    def preflight(self, branch: dict[str, Any]) -> dict[str, Any]:
        """在正式提交前执行不访问隐藏数据的确定性代码门禁。"""
        entrypoint_value = branch.get("entrypoint")
        if not entrypoint_value:
            # 兼容直接提交现成 artifact 的第三方 Runner；有代码入口的 Agent 分支
            # 必须通过下面的路径和语法检查。
            return {
                "valid": True,
                "skipped": True,
                "reason": "branch does not declare an executable entrypoint",
            }

        entrypoint = Path(str(entrypoint_value)).expanduser().resolve()
        method_dir = Path(
            str(branch.get("method_dir") or entrypoint.parent)
        ).expanduser().resolve()
        checks = {
            "entrypoint_exists": entrypoint.is_file(),
            "entrypoint_in_method_dir": False,
            "python_syntax": None,
        }
        try:
            entrypoint.relative_to(method_dir)
            checks["entrypoint_in_method_dir"] = True
        except ValueError:
            pass

        error = None
        if not checks["entrypoint_exists"]:
            error = f"entrypoint 不存在: {entrypoint}"
        elif not checks["entrypoint_in_method_dir"]:
            error = "entrypoint 不在当前方法目录中"
        elif entrypoint.suffix == ".py":
            try:
                # ast.parse 不执行用户代码，也不会生成 __pycache__，适合作为提交门禁。
                ast.parse(entrypoint.read_text(encoding="utf-8"), filename=str(entrypoint))
                checks["python_syntax"] = True
            except (OSError, SyntaxError, UnicodeError) as exc:
                checks["python_syntax"] = False
                error = repr(exc)

        return {
            "valid": error is None,
            "source": "experiment_runner_preflight",
            "entrypoint": str(entrypoint),
            "method_dir": str(method_dir),
            "checks": checks,
            "error": error,
        }

    def run(self, branch: dict[str, Any]) -> dict[str, Any]:
        """执行冻结的分支或 Candidate，并返回可持久化结果。"""
        raise NotImplementedError


class NoopExperimentRunner(ExperimentRunner):
    """提供默认的空实验执行器。"""

    def __init__(self, workspace: str | Path):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)

    def run(self, branch: dict[str, Any]) -> dict[str, Any]:
        """执行当前组件的运行流程。"""
        branch_id = str(branch.get("branch_id") or branch.get("id") or new_id("branch"))
        artifact = Path(str(branch.get("artifact", "")))
        run_id = new_id("run")
        run_dir = self.workspace / "artifacts" / "runs" / branch_id / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        result = {
            "id": run_id,
            "branch_id": branch_id,
            "source": "noop_experiment_runner",
            "valid": artifact.exists(),
            "returncode": 0 if artifact.exists() else 2,
            "artifact": str(artifact),
            "run_dir": str(run_dir),
            "created_at": now_ms(),
        }
        atomic_write_json(run_dir / "result.json", result)
        (run_dir / "runner.log").write_text(
            f"noop runner: artifact={artifact} exists={artifact.exists()}\n",
            encoding="utf-8",
        )
        result["result_path"] = str(run_dir / "result.json")
        result["log_path"] = str(run_dir / "runner.log")
        return result


class CommandExperimentRunner(ExperimentRunner):
    """通过外部命令运行分支实验。"""

    def __init__(self, workspace: str | Path, config: dict[str, Any], *, cwd: str | Path | None = None):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)
        self.config = config
        self.cwd = Path(cwd).resolve() if cwd else None
        self.cmd_template = str(config.get("cmd") or "")
        raw_argv = config.get("argv")
        if raw_argv is not None and (
            not isinstance(raw_argv, list)
            or not raw_argv
            or not all(isinstance(item, str) for item in raw_argv)
        ):
            raise ValueError("experiment_runner.argv 必须是非空字符串列表")
        self.argv_template = list(raw_argv) if isinstance(raw_argv, list) else []
        self.timeout_sec = int(config.get("timeout_sec") or 3600)
        self.source = str(config.get("source") or "command_experiment_runner")

    def run(self, branch: dict[str, Any]) -> dict[str, Any]:
        """执行当前组件的运行流程。"""
        branch_id = str(branch.get("branch_id") or branch.get("id") or new_id("branch"))
        input_artifact = str(branch.get("artifact") or "")
        run_id = new_id("run")
        candidate_dir_value = branch.get("candidate_dir")
        candidate_dir = (
            Path(str(candidate_dir_value)).expanduser().resolve()
            if candidate_dir_value
            else None
        )
        if candidate_dir is not None:
            try:
                candidate_dir.relative_to(self.workspace.resolve() / "candidates")
            except ValueError as exc:
                raise ValueError("candidate_dir 不在当前目标的 candidates 目录中") from exc
            run_dir = candidate_dir / "evidence" / "runs" / run_id
            output_dir = candidate_dir / "output"
        else:
            # 兼容尚未使用 CandidateStore 的直接 Runner 调用和第三方扩展。
            run_dir = self.workspace / "artifacts" / "runs" / safe_name(branch_id) / run_id
            output_dir = run_dir / "output"
        run_dir.mkdir(parents=True, exist_ok=True)
        if candidate_dir is not None and output_dir.exists():
            # 同一 Candidate 的本地重跑不能误用上一次留下的半成品。只清理经过
            # candidates 根目录校验的 output，冻结 code 和历史 evidence 不受影响。
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "runner.log"
        result_path = run_dir / "result.json"

        if not self.cmd_template and not self.argv_template:
            return NoopExperimentRunner(self.workspace).run(branch)

        method_dir = str(branch.get("method_dir") or Path(input_artifact).parent)
        entrypoint = str(branch.get("entrypoint") or "")
        execution_cwd = Path(str(branch.get("workdir") or self.cwd or Path.cwd())).resolve()
        values = {
            "artifact": input_artifact,
            "method_dir": method_dir,
            "branch_dir": method_dir,
            "entrypoint": entrypoint,
            "workdir": str(execution_cwd),
            "run_dir": str(run_dir),
            "output_dir": str(output_dir),
            "candidate_dir": str(candidate_dir) if candidate_dir else "",
            "candidate_id": str(branch.get("candidate_id") or ""),
            "branch_id": branch_id,
            "config_dir": str(self.cwd or Path.cwd()),
            "goal_dir": str(self.cwd or Path.cwd()),
        }
        if self.argv_template:
            invocation: str | list[str] = [
                item.format(**values) for item in self.argv_template
            ]
            command_display = shlex.join(invocation)
            use_shell = False
        else:
            quoted_values = {key: shlex.quote(value) for key, value in values.items()}
            invocation = self.cmd_template.format(**quoted_values)
            command_display = invocation
            use_shell = True
        started = now_ms()
        try:
            proc = subprocess.run(
                invocation,
                shell=use_shell,
                cwd=str(execution_cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_sec,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            proc = None
            timed_out = True
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        else:
            stdout = proc.stdout
            stderr = proc.stderr

        # 完整原件先落盘，再谈摘要。result 里那两截尾巴是给 agent 和索引看的，
        # 不是证据本身——3000/1500 字符装不下一次训练，报错的 traceback 一长
        # 就会被从头切掉，留下一截无头调用栈。原件在，事后才查得动。
        stdout_log = _persist_stream(run_dir / "stdout.log", stdout)
        stderr_log = _persist_stream(run_dir / "stderr.log", stderr)

        parsed: dict[str, Any] = {}
        parse_error = None
        if stdout.strip():
            try:
                parsed = json.loads(stdout.strip().splitlines()[-1])
            except json.JSONDecodeError as exc:
                parse_error = repr(exc)

        returncode = -1 if proc is None else proc.returncode
        output_artifact = parsed.get("artifact") or parsed.get("output_artifact")
        if not output_artifact and candidate_dir is not None:
            # 兼容旧命令模板只把产物写到 {run_dir}、但不向 stdout 返回 JSON 的
            # 情况。只在当前 Candidate 的受信任目录中查找，且必须唯一。
            produced = [
                path
                for root in (output_dir, run_dir)
                for path in root.iterdir()
                if path.name not in RUN_DIR_HOST_FILES
            ]
            if len(produced) == 1:
                output_artifact = str(produced[0])
        output_artifact = output_artifact or input_artifact
        output_path = Path(str(output_artifact))
        if not output_path.is_absolute():
            output_path = execution_cwd / output_path
        output_path = output_path.resolve()
        workspace_root = self.workspace.resolve()
        try:
            output_path.relative_to(workspace_root)
            artifact_in_workspace = True
        except ValueError:
            artifact_in_workspace = False
        artifact_in_candidate_output = True
        if candidate_dir is not None:
            try:
                output_path.relative_to(candidate_dir)
            except ValueError:
                artifact_in_candidate_output = False
        valid = (
            (returncode == 0)
            and (not timed_out)
            and artifact_in_workspace
            and artifact_in_candidate_output
            and output_path.exists()
        )
        result = {
            "id": run_id,
            "branch_id": branch_id,
            "candidate_id": branch.get("candidate_id"),
            "source": self.source,
            "valid": valid,
            "returncode": returncode,
            "timed_out": timed_out,
            "command": command_display,
            "artifact": str(output_path),
            "input_artifact": input_artifact,
            "method_dir": method_dir,
            "entrypoint": entrypoint,
            "workdir": str(execution_cwd),
            "artifact_in_workspace": artifact_in_workspace,
            "artifact_in_candidate_output": artifact_in_candidate_output,
            "run_dir": str(run_dir),
            "output_dir": str(output_dir),
            "stdout": stdout[-3000:],
            "stderr": stderr[-1500:],
            # 上面两截是摘要；下面这几项指向原件，并说明原件完不完整。
            "stdout_path": stdout_log["path"],
            "stderr_path": stderr_log["path"],
            "stdout_bytes": stdout_log["bytes"],
            "stderr_bytes": stderr_log["bytes"],
            "stdout_truncated": stdout_log["truncated"],
            "stderr_truncated": stderr_log["truncated"],
            "run_log_error": stdout_log["error"] or stderr_log["error"],
            "parsed": parsed,
            "parse_error": parse_error,
            "error": (
                None
                if artifact_in_workspace and artifact_in_candidate_output
                else (
                    "experiment artifact is outside the goal workspace"
                    if not artifact_in_workspace
                    else "experiment artifact is outside the candidate directory"
                )
            ),
            "started_at": started,
            "finished_at": now_ms(),
        }
        log_path.write_text(
            f"[command]\n{command_display}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n",
            encoding="utf-8",
        )
        atomic_write_json(result_path, result)
        result["result_path"] = str(result_path)
        result["log_path"] = str(log_path)
        return result


def runner_from_goal(goal_doc: dict[str, Any], workspace: str | Path, *, cwd: str | Path | None = None) -> ExperimentRunner:
    """根据目标配置创建实验执行器。"""
    workflow = goal_doc.get("workflow")
    if isinstance(workflow, dict) and workflow.get("type") == "benchmark_managed":
        raise ValueError(
            "benchmark_managed 目标必须通过 agent run 和 Benchmark Adapter 启动，"
            "不支持 loop run 的隐式实验 Runner"
        )
    cfg = goal_doc.get("experiment_runner") or goal_doc.get("experiment") or {}
    if isinstance(cfg, dict) and cfg.get("type") == "command":
        return CommandExperimentRunner(workspace, cfg, cwd=cwd)
    return NoopExperimentRunner(workspace)
