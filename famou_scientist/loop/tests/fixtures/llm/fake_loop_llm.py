#!/usr/bin/env python3
"""供测试和示例使用的模拟 Loop LLM 命令后端。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """读取任务请求并写出确定性的模拟 LLM 响应。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--invalid", action="store_true")
    args = parser.parse_args()
    if args.invalid:
        Path(args.output).write_text("not-json", encoding="utf-8")
        return 0
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    task = payload.get("task")
    ctx = payload.get("context") or {}
    if task == "idea_generator":
        out = {
            "ideas": [
                {
                    "title": "LLM Prototype Router",
                    "mechanism": "Learn class prototypes and a sparse routing rule to improve interpretability.",
                    "expected_gain": ["interpretability", "latency"],
                    "risks": ["prototype collapse"],
                    "validation_plan": ["compare with baseline", "ablate routing", "measure latency"]
                },
                {
                    "title": "HPO-only grid search",
                    "mechanism": "Tune hyperparameters only.",
                    "expected_gain": ["accuracy"],
                    "risks": ["low novelty"],
                    "validation_plan": ["grid search"]
                }
            ]
        }
    elif task == "idea_gate":
        idea = ctx.get("idea") or {}
        low = "hpo" in str(idea.get("title", "")).lower() or "hyperparameter" in str(idea.get("mechanism", "")).lower()
        out = {
            "accept": not low,
            "decision": "reject" if low else "accept_to_ideaspark",
            "reasons": ["pure HPO is rejected"] if low else ["mechanism is concrete and not pure HPO"],
            "risks": [],
            "similar_prior_work": []
        }
    elif task == "method_designer":
        out = {
            "title": "LLM Prototype Router Method",
            "method_summary": (
                "Use a generated prototype-routing method as a runnable branch "
                "and emit a submission artifact."
            ),
            "entrypoint": "method.py",
            "files": [
                {
                    "path": "method.py",
                    "content": (
                        "import argparse\n"
                        "import json\n"
                        "from pathlib import Path\n"
                        "\n"
                        "parser = argparse.ArgumentParser()\n"
                        "parser.add_argument('--output', required=True)\n"
                        "args = parser.parse_args()\n"
                        "output = Path(args.output)\n"
                        "output.parent.mkdir(parents=True, exist_ok=True)\n"
                        "output.write_text(json.dumps({"
                        "'method': 'prototype_router', 'trained': True\n"
                        "}), encoding='utf-8')\n"
                    ),
                }
            ],
            "experiment_plan": ["execute generated entrypoint", "run public evaluator"],
            "limitations": ["fake benchmark only"],
        }
    elif task == "result_analyst":
        out = {
            "promote": True,
            "retry": False,
            "decision": "promote_to_analyze_spark",
            "reasons": ["public/official evidence is sufficient for smoke promotion"]
        }
    elif task == "deep_analyzer":
        out = {
            "paper_candidate": True,
            "claims": ["The branch has a traceable prototype-routing mechanism."],
            "limitations": ["Fake LLM example only; not a real scientific claim."]
        }
    else:
        out = {}
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
