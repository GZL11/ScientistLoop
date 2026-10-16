#!/usr/bin/env python3
"""模拟 Claude/Codex 类命令行 Agent，供 Harness 测试使用。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, value: dict[str, object]) -> None:
    """写入测试 Agent 的结构化结果。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def main() -> int:
    """按照环境中的节点角色生成想法或最小实现。"""
    role = os.environ.get("FAMOU_AGENT_ROLE", "implement")
    output_path = Path(os.environ["FAMOU_IMPLEMENT_AGENT_OUTPUT"])
    worktree = Path(os.environ["FAMOU_IMPLEMENT_AGENT_WORKTREE"])
    if role == "idea":
        request = json.loads(
            Path(os.environ["FAMOU_IMPLEMENT_AGENT_INPUT"]).read_text(
                encoding="utf-8"
            )
        )
        debate = (request.get("metadata") or {}).get("idea_debate") or {}
        if debate.get("role") == "author_response":
            # 作者收到判官反馈后的回应回合：接受意见并改写标题，供测试断言采纳链路。
            current = dict(debate.get("current_idea") or {})
            current.update(
                {
                    "status": "proposed",
                    "title": "作者按判官意见改后的方案",
                    "rationale": "接受意见: "
                    + "; ".join(
                        str(item.get("statement"))
                        for item in debate.get("objections") or []
                    ),
                }
            )
            current.setdefault("method", "读取公开输入并生成确定性提交。")
            _write_json(output_path, current)
            return 0
        _write_json(
            output_path,
            {
                "status": "proposed",
                "title": "公开数据上的确定性基线",
                "hypothesis": "先建立可复现基线可验证完整链路。",
                "method": "读取公开输入并生成确定性提交。",
                "rationale": "最小闭环测试不依赖隐藏信息。",
                "implementation_plan": ["读取输入", "写出提交"],
                "expected_return": {
                    "target_level": "match_sota",
                    "expected_metric": {
                        "name": "aggregate_improvement",
                        "range": None,
                    },
                    "confidence": "low",
                    "basis": ["该测试 Agent 只验证完整基础设施链路。"],
                    "assumptions": ["测试 evaluator 返回预设分数。"],
                },
                "risks": ["仅用于基础设施测试"],
            },
        )
        return 0
    if role == "idea_judge":
        request = json.loads(
            Path(os.environ["FAMOU_IMPLEMENT_AGENT_INPUT"]).read_text(
                encoding="utf-8"
            )
        )
        metadata = request.get("metadata") or {}
        idea = metadata.get("idea") or {}
        _write_json(
            output_path,
            {
                "idea_id": idea.get("id"),
                "has_material_objection": True,
                "objections": [
                    {
                        "kind": "metric_alignment",
                        "statement": "未说明如何对齐主指标",
                        "evidence_refs": ["problem/README.md"],
                        "severity": "major",
                    }
                ],
                "feedback_markdown": "## 反馈\n\n请说明指标对齐方式。",
                "summary": "指标对齐缺失",
            },
        )
        return 0
    if role == "idea_rank":
        request = json.loads(
            Path(os.environ["FAMOU_IMPLEMENT_AGENT_INPUT"]).read_text(
                encoding="utf-8"
            )
        )
        ideas = (request.get("metadata") or {}).get("ideas") or []
        _write_json(
            output_path,
            {
                "ranking": [
                    {
                        "queue_item_id": idea["queue_item_id"],
                        "idea_id": idea["idea_id"],
                        "rank": index,
                        "reason": "fake rank",
                        "scores": {
                            "score_potential": 3,
                            "feasibility": 3,
                            "time_fit": 3,
                            "resource_fit": 3,
                        },
                        "risks": [],
                    }
                    for index, idea in enumerate(ideas, start=1)
                ]
            },
        )
        return 0
    (worktree / "run.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "out = Path(os.environ['OUTPUT_DIR'])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'submission.txt').write_text(os.environ.get('FAMOU_ATTEMPT_ID', 'ok'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    submit_command = os.environ.get("FAMOU_SUBMIT_CANDIDATE")
    if submit_command:
        search_opportunity = json.loads(
            os.environ.get("FAMOU_SEARCH_OPPORTUNITY_JSON") or "{}"
        )
        search_args = (
            [
                "--search-action",
                "refine",
                "--search-reason",
                "测试 Agent 保持当前实现，并将备选 Idea 重放到队尾。",
            ]
            if search_opportunity
            else []
        )
        subprocess.run(
            [
                sys.executable,
                submit_command,
                "--entrypoint",
                "run.py",
                "--title",
                "测试实现",
                "--summary",
                "生成最小提交",
                "--file",
                "run.py",
                "--experiment-plan",
                "运行公开测试",
                "--limitation",
                "仅用于测试",
                *search_args,
            ],
            check=True,
        )
    else:
        # 兼容不经过统一 CLI wrapper 的旧单元测试。
        _write_json(
            output_path,
            {
                "status": "implemented",
                "title": "测试实现",
                "method_summary": "生成最小提交",
                "entrypoint": "run.py",
                "files": [{"path": "run.py"}],
                "experiment_plan": ["运行公开测试"],
                "limitations": ["仅用于测试"],
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
