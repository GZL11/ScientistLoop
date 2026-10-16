"""
runners/eval.py — 公共 eval 逻辑：extractor + evaluator

所有需要运行 eval 的入口（run_b3、run_b3_stability、run_eval_batch）统一调用此模块。
"""

import json
import subprocess
import sys
import time
from pathlib import Path

# Extractor（CC SDK）启动失败后的重试配置
_EXTRACTOR_MAX_RETRIES = 3
_EXTRACTOR_RETRY_DELAY = 5  # seconds


def _parse_json_output(text: str) -> dict | None:
    """从 stdout 中解析 JSON，容忍前后混入的非 JSON 内容（如 warning 日志）。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取第一个 {...} 块
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _run_extractor(
    extractor: Path, evaluator: Path, workspace: Path, output_dir: Path,
) -> subprocess.CompletedProcess:
    """运行 extractor，遇到 CLI 资源竞争错误时自动重试。"""
    for attempt in range(_EXTRACTOR_MAX_RETRIES + 1):
        r = subprocess.run(
            [sys.executable, str(extractor),
             "--evaluator", str(evaluator),
             "--workspace", str(workspace),
             "--output",    str(output_dir)],
            capture_output=True, text=True,
        )
        # 正常退出或有有效输出 → 不重试
        if r.returncode == 0 and r.stdout.strip():
            return r
        # 检测 CLI 资源竞争错误（Fatal error in message reader 等）
        is_cli_error = (
            "Fatal error" in r.stderr
            or "message reader" in r.stderr
            or "EADDRINUSE" in r.stderr
        )
        if not is_cli_error or attempt >= _EXTRACTOR_MAX_RETRIES:
            return r
        print(
            f"  [extractor] CLI resource error (attempt {attempt + 1}), "
            f"retrying in {_EXTRACTOR_RETRY_DELAY}s...",
            file=sys.stderr,
        )
        time.sleep(_EXTRACTOR_RETRY_DELAY)
    return r  # unreachable, but keeps type checker happy


def run_eval(case: Path, workspace: Path, output_dir: Path | None = None) -> dict:
    """
    运行 extractor + evaluator，返回 result dict。

    Parameters
    ----------
    case : Path
        case 目录（含 tests/extractor_agent.py、tests/evaluator.py、data/）
    workspace : Path
        agent 工作目录（extractor 从中提取产物）
    output_dir : Path | None
        normalized 文件写入目录。None 时使用 workspace/.eval/normalized

    Returns
    -------
    dict
        包含 overall_score、validity_score、quality_score、extraction_status 等字段。
        调用方自行决定写文件、打印。
    """
    extractor = case / "tests" / "extractor_agent.py"
    evaluator = case / "tests" / "evaluator.py"
    data_dir = case / "data"

    if output_dir is None:
        output_dir = workspace / ".eval" / "normalized"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Extractor ─────────────────────────────────────────────────────
    r = _run_extractor(extractor, evaluator, workspace, output_dir)

    if r.returncode != 0 or not r.stdout.strip():
        return {
            "overall_score": 0.0, "validity_score": 0.0, "quality_score": 0.0,
            "extraction_status": "error",
            "extraction_notes": f"extractor exited with code {r.returncode}. stderr: {r.stderr[:500]}",
        }

    extraction = _parse_json_output(r.stdout)
    if extraction is None:
        return {
            "overall_score": 0.0, "validity_score": 0.0, "quality_score": 0.0,
            "extraction_status": "error",
            "extraction_notes": f"extractor output is not valid JSON: {r.stdout[:200]}",
        }

    status = extraction.get("status", "failed")
    if status != "success":
        return {
            "overall_score": 0.0, "validity_score": 0.0, "quality_score": 0.0,
            "extraction_status": status,
            "extraction_notes": extraction.get("notes", ""),
        }

    # ── Step 2: Evaluator ─────────────────────────────────────────────────────
    r = subprocess.run(
        [sys.executable, str(evaluator),
         "--data-dir",       str(data_dir),
         "--submission-dir", str(output_dir)],
        capture_output=True, text=True,
    )

    if r.returncode != 0 or not r.stdout.strip():
        return {
            "overall_score": 0.0, "validity_score": 0.0, "quality_score": 0.0,
            "extraction_status": "success",
            "extraction_notes": extraction.get("notes", ""),
            "eval_error": f"evaluator exited with code {r.returncode}. stderr: {r.stderr[:500]}",
        }

    result = _parse_json_output(r.stdout)
    if result is None:
        return {
            "overall_score": 0.0, "validity_score": 0.0, "quality_score": 0.0,
            "extraction_status": "success",
            "extraction_notes": extraction.get("notes", ""),
            "eval_error": f"evaluator output is not valid JSON: {r.stdout[:200]}",
        }

    result["extraction_status"] = "success"
    result["extraction_notes"] = extraction.get("notes", "")
    return result
