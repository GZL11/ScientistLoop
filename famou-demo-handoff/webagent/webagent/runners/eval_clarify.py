"""
runners/eval_clarify.py — 澄清覆盖率评估（B2 / B3 共享）

读取 dialog.json（澄清对话）和 gt.json（信息差基准），
通过 LLM 逐 key 判定覆盖情况，输出覆盖率得分。
"""

from __future__ import annotations

import json
from pathlib import Path


def _build_judge_prompt(gt: dict, dialog: list[dict]) -> str:
    """拼装 LLM judge 的 prompt。"""

    dialog_lines: list[str] = []
    for turn in dialog:
        role = turn.get("role", "?")
        content = turn.get("content", "")
        if role == "agent":
            dialog_lines.append(f"[Agent]: {content}")
        elif role == "operator":
            dialog_lines.append(f"[业务方]: {content}")
        elif role == "user":
            dialog_lines.append(f"[用户]: {content}")
    dialog_text = "\n\n".join(dialog_lines)

    keys_block = json.dumps(gt, ensure_ascii=False, indent=2)

    return (
        "你是一个评估专家。下面是一段技术团队（Agent）与业务方之间的澄清对话，"
        "以及一份该业务场景的关键信息点清单（JSON 格式，每个 key 代表一个信息点，value 是该信息点的正确内容）。\n\n"
        "请判断：对话过程中，Agent 是否通过提问成功获取了每个信息点的内容。\n\n"
        f"## 信息点清单\n```json\n{keys_block}\n```\n\n"
        f"## 澄清对话\n{dialog_text}\n\n"
        "## 评判要求\n"
        "对每个信息点（JSON key），判断是否被对话覆盖：\n"
        '- "covered"：Agent 的提问触及了该信息点，且业务方的回答中包含了相关内容\n'
        '- "partial"：Agent 触及了该话题但获取的信息不完整\n'
        '- "uncovered"：对话中完全没有涉及该信息点\n\n'
        "注意：\n"
        "- Agent 的一个问题可能同时覆盖多个信息点\n"
        "- 只要信息点的核心内容在对话中出现即可，不要求措辞完全一致\n\n"
        "请严格按以下 JSON 格式输出，不要输出任何其他内容：\n"
        "```json\n"
        "{\n"
        '  "judgments": {\n'
        '    "<key名称>": {"status": "covered|partial|uncovered", "reason": "简要理由"},\n'
        "    ...\n"
        "  }\n"
        "}\n"
        "```"
    )


def _parse_judge_response(text: str) -> dict | None:
    """从 LLM 输出中解析 JSON。"""
    text = text.strip()
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    return None


def run_clarify_eval(
    case: Path,
    workspace: Path,
    *,
    model: str | None = None,
) -> dict:
    """
    澄清覆盖率评估，B2 和 B3 共享。

    Parameters
    ----------
    case : Path
        case 目录（含 gt.json）
    workspace : Path
        agent 工作目录（含 .eval/dialog.json）
    model : str | None
        LLM judge 使用的模型，None 时使用 bench_config 中的 answerer model

    Returns
    -------
    dict
        包含 coverage_score、judgments、统计信息等。
    """
    from .bench_config import ANSWERER_API_BASE_URL, ANSWERER_AUTH_TOKEN, ANSWERER_MODEL

    gt_path = case / "gt.json"
    dialog_path = workspace / ".eval" / "dialog.json"

    if not gt_path.is_file():
        return {"error": f"gt.json not found: {gt_path}", "coverage_score": 0.0}
    if not dialog_path.is_file():
        return {"error": f"dialog.json not found: {dialog_path}", "coverage_score": 0.0}

    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    dialog = json.loads(dialog_path.read_text(encoding="utf-8"))

    if not gt:
        return {"error": "gt.json is empty", "coverage_score": 0.0}

    # 有澄清轮次才评估（operator 代表业务方回答了至少一次）
    has_clarify = any(t.get("role") == "operator" for t in dialog)
    if not has_clarify:
        return {
            "coverage_score": 0.0,
            "total_keys": len(gt),
            "covered": 0,
            "partial": 0,
            "uncovered": len(gt),
            "rounds": 0,
            "note": "no clarification rounds in dialog",
        }

    # ── LLM judge ────────────────────────────────────────────────────────────
    import os
    import anthropic

    judge_model = model or ANSWERER_MODEL
    auth_token = ANSWERER_AUTH_TOKEN
    base_url = ANSWERER_API_BASE_URL

    if not auth_token:
        return {"error": "answerer auth_token 未配置", "coverage_score": 0.0}

    prompt = _build_judge_prompt(gt, dialog)

    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        client = anthropic.Anthropic(auth_token=auth_token, base_url=base_url)
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved

    message = client.messages.create(
        model=judge_model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = ""
    for block in message.content:
        if hasattr(block, "text"):
            response_text = block.text
            break

    parsed = _parse_judge_response(response_text)
    if parsed is None:
        return {
            "error": f"LLM judge output is not valid JSON: {response_text[:300]}",
            "coverage_score": 0.0,
        }

    judgments = parsed.get("judgments", {})

    # ── 统计 ─────────────────────────────────────────────────────────────────
    total = len(gt)
    covered = sum(1 for v in judgments.values() if v.get("status") == "covered")
    partial = sum(1 for v in judgments.values() if v.get("status") == "partial")
    uncovered = total - covered - partial

    coverage_score = (covered + 0.5 * partial) / total if total > 0 else 0.0
    rounds = sum(1 for t in dialog if t.get("role") == "operator")

    return {
        "coverage_score": round(coverage_score, 4),
        "total_keys": total,
        "covered": covered,
        "partial": partial,
        "uncovered": uncovered,
        "rounds": rounds,
        "judgments": judgments,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _find_workspaces(batch: Path, case_filter: str | None = None):
    """找到 batch 下所有含 dialog.json 的 workspace。"""
    for case_dir in sorted(batch.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("."):
            continue
        if case_filter and case_dir.name != case_filter:
            continue
        run_dirs = sorted(case_dir.glob("run_[0-9][0-9]"))
        if not run_dirs:
            run_dirs = [case_dir]
        for run_dir in run_dirs:
            if (run_dir / ".eval" / "dialog.json").is_file():
                yield case_dir.name, run_dir


def _print_result(case_name: str, workspace: Path, result: dict):
    """打印单个 workspace 的 clarify eval 结果。"""
    if "error" in result:
        print(f"  [ERROR] {case_name}: {result['error']}")
        return

    print(f"  coverage: {result['coverage_score']:.2f}  "
          f"({result['covered']}✓ {result['partial']}△ {result['uncovered']}✗ "
          f"/ {result['total_keys']} keys)  rounds: {result['rounds']}")

    for key, j in result.get("judgments", {}).items():
        status = j.get("status", "?")
        reason = j.get("reason", "")
        mark = {"covered": "✓", "partial": "△", "uncovered": "✗"}.get(status, "?")
        print(f"    {mark} {key}: {reason}")

    out_path = workspace / ".eval" / "clarify_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_path}\n")


def main():
    """
    用法：
        # 单个 workspace
        python -m webagent.runners.eval_clarify --case 05_city_delivery_routing --workspace /path/to/workspace

        # 整个 batch 目录
        python -m webagent.runners.eval_clarify --batch /path/to/b2_batch

        # batch 中指定 case
        python -m webagent.runners.eval_clarify --batch /path/to/b2_batch --case 05_city_delivery_routing
    """
    import argparse
    from .bench_config import resolve_case, CASES_DIR

    parser = argparse.ArgumentParser(description="澄清覆盖率评估（B2/B3 共用）")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="单个 workspace 路径（含 .eval/dialog.json）")
    parser.add_argument("--batch", type=Path, default=None,
                        help="batch 目录，自动查找所有含 dialog.json 的 workspace")
    parser.add_argument("--case", default=None,
                        help="case 名称（--workspace 时必填，--batch 时可选过滤）")
    parser.add_argument("--model", default=None,
                        help="LLM judge 模型（默认使用 bench_config 中的 answerer model）")
    parser.add_argument("--force", action="store_true",
                        help="强制重跑（覆盖已有 clarify_result.json）")
    args = parser.parse_args()

    if not args.workspace and not args.batch:
        parser.error("必须指定 --workspace 或 --batch")

    # ── 单 workspace 模式 ──
    if args.workspace:
        if not args.case:
            parser.error("--workspace 模式下必须指定 --case")
        case = resolve_case(args.case)
        print(f"[clarify eval] {args.case} — {args.workspace}")
        result = run_clarify_eval(case, args.workspace, model=args.model)
        _print_result(args.case, args.workspace, result)
        return

    # ── batch 模式 ──
    batch = args.batch.resolve()
    if not batch.exists():
        print(f"[ERROR] batch 目录不存在: {batch}", file=sys.stderr)
        raise SystemExit(1)

    results = []
    for case_name, ws in _find_workspaces(batch, args.case):
        # 跳过已有结果（除非 --force）
        existing = ws / ".eval" / "clarify_result.json"
        if existing.is_file() and not args.force:
            r = json.loads(existing.read_text(encoding="utf-8"))
            print(f"[SKIP] {case_name}/{ws.name} — 已有 (coverage={r.get('coverage_score', '?')})")
            results.append({"case": case_name, **r})
            continue

        case_dir = CASES_DIR / case_name
        if not case_dir.exists() or not (case_dir / "gt.json").is_file():
            print(f"[SKIP] {case_name}/{ws.name} — 无 case 或 gt.json")
            continue

        print(f"[clarify eval] {case_name}/{ws.name}")
        result = run_clarify_eval(case_dir, ws, model=args.model)
        _print_result(case_name, ws, result)
        if "error" not in result:
            results.append({"case": case_name, **result})

    if results:
        avg = sum(r["coverage_score"] for r in results) / len(results)
        print(f"══ Summary: {len(results)} workspaces, avg coverage: {avg:.2f} ══")


if __name__ == "__main__":
    main()
