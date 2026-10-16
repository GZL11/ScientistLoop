"""供 Implement Agent 显式提交当前代码版本的本地命令。"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

# Agent 通过绝对脚本路径执行本文件；显式补充项目根，复用统一资源契约。
if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from famou_scientist.loop.domain.resources import (  # noqa: E402
    ResourceBroker,
    ResourceEnvelope,
    ResourceRequest,
)


_SNAPSHOT_EXCLUDES = {
    ".git",
    ".famou",
    "__pycache__",
    "benchmark_task",
    "famou_agent_result.json",
    "famou_idea_result.json",
    "output",
    "outputs",
    "logs",
}


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """在同一目录原子写入 JSON，避免 wrapper 读取半个提交事件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _required_env(name: str) -> str:
    """读取 wrapper 注入的受控环境变量。"""

    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"缺少受控环境变量 {name}")
    return value


def _relative_path(value: str, *, field: str) -> str:
    """校验 Agent 提交的相对源码路径。"""

    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    parts = [part for part in path.parts if part not in {"", "."}]
    if not raw or path.is_absolute() or not parts or ".." in parts:
        raise ValueError(f"{field} 必须是 worktree 内的相对路径: {value!r}")
    return "/".join(parts)


def _load_manifest(worktree: Path) -> dict[str, Any]:
    """读取 Agent 可选写入的方法清单。"""

    path = worktree / "method_manifest.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("method_manifest.json 必须是 JSON 对象")
    return raw


def _collect_files(
    worktree: Path,
    *,
    entrypoint: str | None,
    requested: list[str],
    manifest: dict[str, Any],
) -> list[dict[str, str]]:
    """收集并校验本次提交声明的源码文件。"""

    raw_files: list[Any] = list(requested)
    if not raw_files:
        manifest_files = manifest.get("files")
        if isinstance(manifest_files, list):
            raw_files = manifest_files

    paths: list[str] = []
    for index, item in enumerate(raw_files):
        if isinstance(item, str):
            raw_path = item
        elif isinstance(item, dict):
            raw_path = item.get("path")
        else:
            raise ValueError(f"files[{index}] 必须是路径或包含 path 的对象")
        paths.append(_relative_path(str(raw_path or ""), field=f"files[{index}]"))
    if entrypoint and entrypoint not in paths:
        paths.append(entrypoint)

    files: list[dict[str, str]] = []
    for relative in dict.fromkeys(paths):
        target = (worktree / relative).resolve()
        try:
            target.relative_to(worktree)
        except ValueError as exc:
            raise ValueError(f"提交文件越出 worktree: {relative}") from exc
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(f"提交文件不存在或是符号链接: {relative}")
        files.append({"path": relative})
    return files


def _validate_entrypoint(worktree: Path, entrypoint: str | None) -> None:
    """在发布提交事件前校验入口存在，并对 Python 入口执行语法检查。"""

    if not entrypoint:
        return
    target = (worktree / entrypoint).resolve()
    try:
        target.relative_to(worktree)
    except ValueError as exc:
        raise ValueError(f"entrypoint 越出 worktree: {entrypoint}") from exc
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError(f"entrypoint 不存在或是符号链接: {entrypoint}")
    if target.suffix == ".py":
        try:
            ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        except (SyntaxError, UnicodeError) as exc:
            raise ValueError(f"Python entrypoint 语法检查失败: {entrypoint}: {exc}") from exc


def _json_env(name: str) -> dict[str, Any]:
    """读取 wrapper 注入的 JSON 对象；未配置时返回空对象。"""

    raw = os.environ.get(name)
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} 必须是 JSON 对象")
    return value


def _validated_resource_request(
    manifest: dict[str, Any],
    *,
    search_decision: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """在发布提交事件前校验 Implement 的最终资源声明。"""

    envelope_value = _json_env("FAMOU_RESOURCE_ENVELOPE_JSON")
    idea_request = _json_env("FAMOU_IDEA_RESOURCE_REQUEST_JSON")
    opportunity = _json_env("FAMOU_SEARCH_OPPORTUNITY_JSON")
    override = manifest.get("resource_request")
    offered = opportunity.get("offered_idea")
    offered_request = (
        offered.get("resource_request")
        if isinstance(offered, dict)
        and isinstance(offered.get("resource_request"), dict)
        else None
    )
    default_request = (
        offered_request
        if search_decision
        and search_decision.get("action") == "switch"
        and offered_request is not None
        else idea_request
    )
    request_value = override if isinstance(override, dict) else default_request
    require_explicit = os.environ.get(
        "FAMOU_RESOURCE_DECLARATIONS_REQUIRED",
        "0",
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not request_value and not require_explicit:
        return None

    request = ResourceRequest.from_mapping(
        request_value,
        require_explicit=require_explicit,
    )
    if envelope_value:
        broker = ResourceBroker(ResourceEnvelope.from_mapping(envelope_value))
        broker.require_can_ever_fit(request)
    return request.to_dict()


def _validated_search_decision(args: argparse.Namespace) -> dict[str, Any] | None:
    """校验 Improve 回合的 refine/switch/fuse 显式选择。"""

    opportunity = _json_env("FAMOU_SEARCH_OPPORTUNITY_JSON")
    action = str(getattr(args, "search_action", None) or "")
    reason = str(getattr(args, "search_reason", None) or "").strip()
    if not opportunity:
        if action or reason:
            raise ValueError("当前回合没有 Search Opportunity，不能提交 search action")
        return None
    allowed = {
        str(value)
        for value in opportunity.get("allowed_actions") or []
        if value
    }
    if action not in allowed:
        raise ValueError(
            "Improve 回合必须通过 --search-action 选择 refine、switch 或 fuse"
        )
    if not reason:
        raise ValueError("Improve 回合必须通过 --search-reason 说明选择依据")
    offered = opportunity.get("offered_idea")
    offered_id = (
        str(offered.get("id") or "") if isinstance(offered, dict) else ""
    )
    current = opportunity.get("current_idea")
    current_id = (
        str(current.get("id") or "") if isinstance(current, dict) else ""
    )
    return {
        "action": action,
        "reason": reason,
        "current_idea_id": current_id,
        "offered_idea_id": offered_id,
    }


def _snapshot_worktree(worktree: Path, destination: Path) -> None:
    """在发布提交事件前复制代码，固定 Agent 调用提交时的版本。"""

    def ignore(directory: str, names: list[str]) -> set[str]:
        """排除公开数据链接、运行产物和所有符号链接。"""

        return {
            name
            for name in names
            if name in _SNAPSHOT_EXCLUDES
            or name.startswith(".git")
            or name.endswith(".pyc")
            or (Path(directory) / name).is_symlink()
        }

    shutil.copytree(worktree, destination, symlinks=False, ignore=ignore)


def _parser() -> argparse.ArgumentParser:
    """构建显式提交命令的参数解析器。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entrypoint",
        help="可选的运行入口；具体 benchmark 可以通过任务契约强制要求",
    )
    parser.add_argument("--title", help="本版本的方法标题")
    parser.add_argument("--summary", help="本版本的核心修改与机制摘要")
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="需要纳入方法清单的源码文件，可重复",
    )
    parser.add_argument(
        "--experiment-plan",
        action="append",
        default=[],
        help="建议由 canonical runner 执行的实验说明",
    )
    parser.add_argument(
        "--limitation",
        action="append",
        default=[],
        help="当前版本已知限制，可重复",
    )
    parser.add_argument(
        "--search-action",
        choices=("refine", "switch", "fuse"),
        help="Improve 配对回合选择继续当前方案、切换或融合",
    )
    parser.add_argument(
        "--search-reason",
        help="选择 refine、switch 或 fuse 的证据化理由",
    )
    return parser


def submit(args: argparse.Namespace) -> dict[str, Any]:
    """校验当前版本，先写标准结果，再发布唯一提交事件。"""

    worktree = Path(_required_env("FAMOU_IMPLEMENT_AGENT_WORKTREE")).resolve()
    manager_result = Path(_required_env("FAMOU_IMPLEMENT_AGENT_OUTPUT")).resolve()
    worktree_result = Path(
        _required_env("FAMOU_IMPLEMENT_AGENT_WORKTREE_OUTPUT")
    ).resolve()
    submission_path = Path(_required_env("FAMOU_SUBMISSION_PATH")).resolve()
    if submission_path.exists():
        raise RuntimeError("本次 Implement 激活已经提交过 Candidate")

    manifest = _load_manifest(worktree)
    explicit_entrypoint = (
        _relative_path(args.entrypoint, field="entrypoint") if args.entrypoint else None
    )
    manifest_value = manifest.get("entrypoint")
    manifest_entrypoint = (
        _relative_path(str(manifest_value), field="method_manifest.entrypoint")
        if manifest_value
        else None
    )
    expected_value = os.environ.get("FAMOU_EXPECTED_ENTRYPOINT")
    expected_entrypoint = (
        _relative_path(expected_value, field="benchmark contract entrypoint")
        if expected_value
        else None
    )
    # 显式参数优先，其次采用 Agent 的方法清单；两者都省略时，Benchmark
    # contract 是安全的确定性默认值。这样遗漏 --entrypoint 不再浪费一个 Actor
    # 回合，但显式提交了错误入口时仍会立即失败并要求原 Agent 当场修正。
    entrypoint = explicit_entrypoint or manifest_entrypoint or expected_entrypoint
    entrypoint_source = (
        "explicit"
        if explicit_entrypoint
        else "method_manifest"
        if manifest_entrypoint
        else "benchmark_contract"
        if expected_entrypoint
        else None
    )
    if expected_entrypoint and entrypoint != expected_entrypoint:
        raise ValueError(
            f"benchmark 要求入口为 {expected_entrypoint!r}，实际为 {entrypoint!r}"
        )
    _validate_entrypoint(worktree, entrypoint)
    # 资源 override 必须在 Agent 仍活跃时拒绝。只有校验成功后才冻结代码并发布
    # submission event，因此 Agent 能直接根据 accepted=false 调整声明后重提。
    search_decision = _validated_search_decision(args)
    resource_request = _validated_resource_request(
        manifest,
        search_decision=search_decision,
    )
    files = _collect_files(
        worktree,
        entrypoint=entrypoint,
        requested=list(args.file or []),
        manifest=manifest,
    )
    submission_id = f"submission_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    submitted_worktree = submission_path.parent / f"{submission_id}.code"
    _snapshot_worktree(worktree, submitted_worktree)
    result = {
        "status": "implemented",
        "submission_id": submission_id,
        "title": str(args.title or manifest.get("title") or "submitted_candidate"),
        "method_summary": str(
            args.summary
            or manifest.get("method_summary")
            or manifest.get("summary")
            or ""
        ),
        "entrypoint": entrypoint,
        "entrypoint_source": entrypoint_source,
        "files": files,
        "experiment_plan": list(
            args.experiment_plan or manifest.get("experiment_plan") or []
        ),
        "limitations": list(
            args.limitation or manifest.get("limitations") or []
        ),
        # Implement 可以根据代码和 Smoke Test 修正 Idea 阶段的估算；Controller
        # 会在进入 Evaluation Queue 前重新校验，Agent 不能自行选择具体设备。
        "resource_request": resource_request,
        "search_decision": search_decision,
        # Controller 后续只从该提交时快照执行 preflight 和 canonical run；Actor
        # worktree 在 park 前即使继续变化，也不会污染已经提交的 Candidate。
        "submitted_worktree": str(submitted_worktree),
    }
    # result 文件必须先于事件可见。wrapper 只有看到最后写入的 submission_path，
    # 才会把当前 CLI Agent 激活视为已提交并开始 park。
    _atomic_write_json(worktree_result, result)
    _atomic_write_json(manager_result, result)
    event = {
        "schema_version": 1,
        "submission_id": submission_id,
        "entrypoint": entrypoint,
        "entrypoint_source": entrypoint_source,
        "submitted_worktree": str(submitted_worktree),
        "result_path": str(manager_result),
        "worktree_result_path": str(worktree_result),
        "search_decision": search_decision,
        "created_at": int(time.time() * 1000),
    }
    _atomic_write_json(submission_path, event)
    return {
        "accepted": True,
        "action": "park",
        "submission_id": submission_id,
        "entrypoint": entrypoint,
        "entrypoint_source": entrypoint_source,
        "search_action": (
            search_decision.get("action") if search_decision else None
        ),
        "message": "Candidate 已登记；请结束当前回合，等待异步评测反馈。",
    }


def main(argv: list[str] | None = None) -> int:
    """执行显式 Candidate 提交命令。"""

    try:
        receipt = submit(_parser().parse_args(argv))
    except Exception as exc:  # noqa: BLE001 - 命令行需要给 Agent 可修复的明确错误
        print(json.dumps({"accepted": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
