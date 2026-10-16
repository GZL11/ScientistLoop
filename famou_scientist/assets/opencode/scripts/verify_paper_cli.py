#!/usr/bin/env python3
"""verify_paper_cli — 论文数字硬核验(OpenCode hook 调用)。

把论文(.tex / .md)里 strict 段(Results/Experiments/表格)出现的每个数字，
与「可信数字注册表」比对——注册表从约定的 results.json 精确建立。
论文里出现注册表里没有的数字(容差外) = 可能编造 → 报告。

这是 **确定性** 防造假:复用 ARC 的 paper_verifier / verified_registry 成熟逻辑
(数字抽取、section 识别、变体注册、容差比对),只把「白名单来源」换成
OpenCode 流程约定的 results.json。纯 stdlib，零 ARC 包依赖。

results.json 约定 schema（OpenCode 跑完实验后整理写入 run 目录）:
{
  "primary_metric": "accuracy",                 # 可选
  "results": {
    "<condition_name>": {                        # 每个实验条件
      "<metric>": <number>,                      # 如 "accuracy": 0.915
      "folds": [<number>, ...],                  # 可选:逐 fold/seed 的值
      ...
    },
    ...
  }
}
也兼容扁平结构 {"<condition>": {"<metric>": <number>, ...}}（无 "results" 包裹）。

用法:
  python verify_paper_cli.py --paper <deliverables/paper.md|paper.tex> --results <experiment/results.json>
输出: JSON {severity, passed, strict_violations, unverified:[{value,section,context}], summary}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 同目录的 ARC 核验逻辑(已改成自包含)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verified_registry import VerifiedRegistry  # noqa: E402
from paper_verifier import verify_paper  # noqa: E402


def _add_numbers(reg: VerifiedRegistry, obj, source: str) -> None:
    """递归把 results.json 里所有数字注册进白名单(连同来源)。"""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        reg.add_value(float(obj), source)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _add_numbers(reg, v, f"{source}.{k}" if source else str(k))
    elif isinstance(obj, list):
        for v in obj:
            _add_numbers(reg, v, source)


def build_registry(results: dict) -> VerifiedRegistry:
    reg = VerifiedRegistry()
    # 支持 {"results": {...}} 或扁平 {condition: {...}}
    payload = results.get("results", results) if isinstance(results, dict) else {}
    _add_numbers(reg, payload, "")
    # 登记 condition 名(paper_verifier 用于检测编造的 condition)
    if isinstance(payload, dict):
        for name in payload:
            if isinstance(name, str):
                reg.condition_names.add(name)
    return reg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="论文数字硬核验(防造假)")
    ap.add_argument("--paper", required=True, help="论文文件路径(.tex 或 .md)")
    ap.add_argument("--results", required=True, help="约定 schema 的 results.json 路径")
    ap.add_argument("--tolerance", type=float, default=0.01, help="相对容差(默认 1%)")
    args = ap.parse_args(argv)

    paper_path, results_path = Path(args.paper), Path(args.results)
    if not paper_path.exists():
        print(json.dumps({"error": f"paper not found: {paper_path}"}, ensure_ascii=False))
        return 2
    if not results_path.exists():
        # 没有 results.json → 无法核验，提示(不算通过也不算失败)
        print(json.dumps({
            "severity": "NO_RESULTS",
            "summary": f"未找到 results.json({results_path}) —— 无法核验论文数字。"
                       "请先把实验真实结果整理成约定 schema 的 results.json。",
        }, ensure_ascii=False))
        return 3

    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(json.dumps({"error": f"results.json 解析失败: {e}"}, ensure_ascii=False))
        return 2

    reg = build_registry(results)
    paper_text = paper_path.read_text(encoding="utf-8")
    res = verify_paper(paper_text, reg, tolerance=args.tolerance)

    out = {
        "severity": res.severity,           # PASS | WARN | REJECT
        "passed": res.passed,
        "strict_violations": res.strict_violations,
        "total_checked": res.total_numbers_checked,
        "registry_size": len(reg.values),
        "unverified": [
            {"value": u.value, "section": u.section, "context": u.context[:120]}
            for u in res.unverified_numbers[:30]
        ],
        "summary": res.summary,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
