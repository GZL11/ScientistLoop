"""Terminal task verifier 的计划兼容层和源码 bundle 工具。"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from ...facilities.contracts import artifact_sha256
from ...utils import atomic_write_json, read_json


_SEVERITIES = {"critical", "major", "minor"}
_CHECKER_KINDS = {"command", "file", "semantic"}

_REQUIRED_VERIFIER_FILES = ("verifier.py", "verifier_spec.md", "tests/test_verifier.py")
_FORBIDDEN_IMPORTS = {
    "socket",
    "subprocess",
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "ftplib",
}
_FORBIDDEN_CALLS = {"eval", "exec", "__import__", "system", "popen"}


def _python_files(root: Path) -> list[Path]:
    """返回 verifier 源码、其顶层辅助模块和测试 Python 文件。"""

    # Generated verifiers are allowed to split pure helper code into local
    # modules (for example ``dicom_mini.py``).  Freeze those modules too;
    # otherwise static validation succeeds but isolated execution fails with
    # ``ModuleNotFoundError``.
    files = sorted(root.glob("*.py"))
    tests = root / "tests"
    if tests.is_dir():
        files.extend(sorted(tests.rglob("*.py")))
    return [path for path in files if path.is_file()]


def _static_python_check(path: Path, *, enforce_security: bool = True) -> list[str]:
    """编译并按文件角色执行最小静态检查，不执行候选代码。

    ``tests/`` 是 VerifierAgent 的自测代码，不是最终 verifier 的执行面；
    这些测试需要能够导入 ``subprocess`` 或动态加载候选来做隔离和变异测试。
    生产 verifier 及其辅助模块仍必须通过完整的禁止导入/调用检查。
    """

    errors: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        compile(tree, str(path), "exec")
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [f"{path.name}: Python 语法或编码错误: {exc}"]
    if not enforce_security:
        return errors
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top in _FORBIDDEN_IMPORTS:
                    errors.append(f"{path.name}: 禁止导入 {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".", 1)[0]
            if top in _FORBIDDEN_IMPORTS:
                errors.append(f"{path.name}: 禁止导入 {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                errors.append(f"{path.name}: 禁止调用 {node.func.id}()")
            if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_CALLS:
                errors.append(f"{path.name}: 禁止调用 .{node.func.attr}()")
    return errors


def validate_verifier_source(source_root: str | Path) -> dict[str, Any]:
    """静态检查 VerifierAgent 产物，并读取可选的自测记录。

    第一版不运行 task-specific 测试，也不判断 fixture 语义；自测结果仅记录 Agent
    在 workspace 中提交的 ``.verifier_self_test.json``。
    """

    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        return {"status": "failed", "errors": [f"verifier workspace 不存在: {root}"]}
    errors: list[str] = []
    for relative in _REQUIRED_VERIFIER_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f"缺少必需文件: {relative}")
    tests_root = root / "tests"
    for path in _python_files(root):
        # Self-tests are bundled for auditability but never executed as the
        # production verifier. Check their syntax without rejecting legitimate
        # isolation helpers used only by the tests themselves.
        in_tests = tests_root.is_dir() and tests_root in path.parents
        errors.extend(_static_python_check(path, enforce_security=not in_tests))

    verifier_path = root / "verifier.py"
    if verifier_path.is_file():
        try:
            tree = ast.parse(verifier_path.read_text(encoding="utf-8"), filename=str(verifier_path))
            functions = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for required in ("describe", "verify"):
                if required not in functions:
                    errors.append(f"verifier.py 缺少顶层接口: {required}()")
        except (OSError, SyntaxError, UnicodeError):
            # 语法错误已由 _static_python_check 报告。
            pass

    self_test: dict[str, Any] = {
        "status": "not_run",
        "runner": "verifier_agent",
    }
    self_test_path = root / ".verifier_self_test.json"
    if self_test_path.is_file() and not self_test_path.is_symlink():
        try:
            value = json.loads(self_test_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("必须是 JSON object")
            status = str(value.get("status") or "").strip().lower()
            if status not in {"passed", "partial", "failed", "not_run"}:
                raise ValueError("status 必须是 passed/partial/failed/not_run")
            self_test = {
                "status": f"agent_reported_{status}" if status != "partial" else "partial",
                "runner": "verifier_agent",
                "case_count": int(value.get("case_count") or 0),
                "exit_code": value.get("exit_code"),
                "command": str(value.get("command") or ""),
                "log_ref": str(value.get("log_ref") or ""),
            }
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f".verifier_self_test.json 无效: {exc}")
            self_test = {"status": "invalid", "runner": "verifier_agent"}

    return {
        "status": "passed" if not errors else "failed",
        "source_root": str(root),
        "files": [str(path.relative_to(root)) for path in _python_files(root)],
        "errors": errors,
        "self_test": self_test,
    }


class VerifierBundleStore:
    """冻结 VerifierAgent 源码、测试和自测记录。"""

    def __init__(self, run_dir: str | Path):
        self.root = Path(run_dir) / "controller" / "verifier"
        self.bundle_root = self.root / "bundle"
        self.manifest_path = self.root / "manifest.json"

    def freeze_source(
        self,
        source_root: str | Path,
        *,
        task_id: str,
        task_input_hash: str,
        verifier_agent_session_ref: str | None = None,
        controller_runtime_check: Mapping[str, Any] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        """静态检查并冻结 source；不执行 verifier 或 task-specific 测试。"""

        report = validate_verifier_source(source_root)
        if report["status"] != "passed":
            raise ValueError("VerifierAgent verifier 静态检查失败: " + "; ".join(report["errors"]))
        self_test_status = str(report.get("self_test", {}).get("status") or "")
        if self_test_status not in {"agent_reported_passed", "partial"}:
            raise ValueError(
                "VerifierAgent 自测记录无效或未完成: "
                f"status={self_test_status or 'missing'}"
            )
        source = Path(source_root).expanduser().resolve()
        temporary = self.bundle_root.with_name(self.bundle_root.name + ".partial")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True, exist_ok=True)
        files_to_copy = {
            path.relative_to(source)
            for path in _python_files(source)
            if path.is_file() and not path.is_symlink()
        }
        files_to_copy.update(Path(relative) for relative in _REQUIRED_VERIFIER_FILES)
        for relative in sorted(files_to_copy):
            src = source / relative
            if not src.is_file() or src.is_symlink():
                continue
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        fixtures = source / "fixtures"
        if fixtures.is_dir() and not fixtures.is_symlink():
            shutil.copytree(fixtures, temporary / "fixtures")
        self_test_record = source / ".verifier_self_test.json"
        if self_test_record.is_file() and not self_test_record.is_symlink():
            shutil.copy2(self_test_record, temporary / ".verifier_self_test.json")
            try:
                raw_self_test = json.loads(self_test_record.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw_self_test = {}
            log_ref = raw_self_test.get("log_ref") if isinstance(raw_self_test, dict) else None
            if isinstance(log_ref, str) and log_ref:
                log_path = source / log_ref
                if log_path.is_file() and not log_path.is_symlink():
                    target_log = temporary / log_ref
                    target_log.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(log_path, target_log)
        for path in temporary.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"verifier bundle 不能包含符号链接: {path}")
        bundle_hash = artifact_sha256(temporary)
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 2,
            "task_id": str(task_id),
            "task_input_hash": str(task_input_hash),
            "verifier_bundle_hash": f"sha256:{bundle_hash}",
            "verifier_agent_session_ref": verifier_agent_session_ref,
            "files": report["files"],
            "static_check": {"status": report["status"], "errors": report["errors"]},
            "self_test": report["self_test"],
            "controller_runtime_check": dict(controller_runtime_check or {
                "status": "not_run",
            }),
            "frozen": True,
        }
        if self.manifest_path.exists():
            existing = read_json(self.manifest_path)
            if isinstance(existing, dict) and existing.get("verifier_bundle_hash") == manifest["verifier_bundle_hash"]:
                shutil.rmtree(temporary)
                return self.bundle_root, existing
            raise ValueError("verifier bundle 已冻结，不能在当前 run 中替换")
        temporary.replace(self.bundle_root)
        self.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for path in sorted(self.bundle_root.rglob("*"), reverse=True):
            path.chmod(path.stat().st_mode & ~0o222)
        self.manifest_path.chmod(self.manifest_path.stat().st_mode & ~0o222)
        return self.bundle_root, manifest

    def load_manifest(self) -> dict[str, Any]:
        value = read_json(self.manifest_path)
        if not isinstance(value, dict):
            raise FileNotFoundError(f"verifier manifest 不存在: {self.manifest_path}")
        return value


def validate_verifier_plan(
    value: Mapping[str, Any],
    *,
    expected_task_input_hash: str,
) -> dict[str, Any]:
    """严格校验 VerifierAgent 生成的固定 rubric。"""

    if int(value.get("schema_version") or 0) != 1:
        raise ValueError("VerifierPlan.schema_version 必须为 1")
    actual_hash = str(value.get("task_input_hash") or "")
    if actual_hash != expected_task_input_hash:
        raise ValueError(
            "VerifierPlan.task_input_hash 不匹配: "
            f"expected={expected_task_input_hash}, actual={actual_hash}"
        )
    rubrics = value.get("rubrics")
    if not isinstance(rubrics, list) or not rubrics:
        raise ValueError("VerifierPlan.rubrics 必须是非空数组")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rubrics):
        if not isinstance(raw, dict):
            raise ValueError(f"VerifierPlan.rubrics[{index}] 必须是对象")
        rubric_id = str(raw.get("id") or "").strip()
        if not rubric_id or rubric_id in seen:
            raise ValueError(f"VerifierPlan rubric id 缺失或重复: {rubric_id!r}")
        seen.add(rubric_id)
        severity = str(raw.get("severity") or "").strip().lower()
        if severity not in _SEVERITIES:
            raise ValueError(f"VerifierPlan rubric {rubric_id} severity 非法")
        requirement_ref = str(raw.get("requirement_ref") or "").strip()
        pass_criteria = str(raw.get("pass_criteria") or "").strip()
        checker = raw.get("checker")
        if not requirement_ref or not pass_criteria or not isinstance(checker, dict):
            raise ValueError(f"VerifierPlan rubric {rubric_id} 缺少 requirement/checker/pass_criteria")
        checker_kind = str(checker.get("kind") or "").strip().lower()
        if checker_kind not in _CHECKER_KINDS:
            raise ValueError(f"VerifierPlan rubric {rubric_id} checker.kind 非法")
        normalized.append(
            {
                **raw,
                "id": rubric_id,
                "severity": severity,
                "requirement_ref": requirement_ref,
                "pass_criteria": pass_criteria,
                "checker": dict(checker),
                "required_evidence": [
                    str(item) for item in raw.get("required_evidence", [])
                ],
            }
        )
    return {
        "schema_version": 1,
        "task_input_hash": actual_hash,
        "rubrics": normalized,
    }


class VerifierPlanStore:
    """保存第一轮前冻结、后续只读的 VerifierPlan。"""

    def __init__(self, run_dir: str | Path):
        self.path = Path(run_dir) / "controller" / "verifier" / "plan.json"

    def freeze(self, plan: Mapping[str, Any], *, task_input_hash: str) -> Path:
        normalized = validate_verifier_plan(
            plan,
            expected_task_input_hash=task_input_hash,
        )
        if self.path.exists():
            existing = read_json(self.path)
            if existing != normalized:
                raise ValueError("VerifierPlan 已冻结，不能在后续轮次修改")
            return self.path
        atomic_write_json(self.path, normalized)
        self.path.chmod(self.path.stat().st_mode & ~0o222)
        return self.path

    def load(self) -> dict[str, Any]:
        value = read_json(self.path)
        if not isinstance(value, dict):
            raise FileNotFoundError(f"VerifierPlan 不存在: {self.path}")
        return value


__all__ = [
    "VerifierBundleStore",
    "VerifierPlanStore",
    "validate_verifier_plan",
    "validate_verifier_source",
]
