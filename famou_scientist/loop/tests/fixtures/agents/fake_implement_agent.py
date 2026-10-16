#!/usr/bin/env python3
"""供 Loop 测试和示例使用的模拟命令型实现智能体。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """读取实现请求，在分支工作区生成模拟方法并写出结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fail", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    worktree = Path(payload["worktree"])
    if args.fail:
        Path(args.output).write_text(
            json.dumps(
                {
                    "status": "implementation_failed",
                    "error": "fake agent failure requested",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return 0

    method = worktree / "method.py"
    method.write_text(
        "import argparse\n"
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--output', required=True)\n"
        "args = parser.parse_args()\n"
        "out = Path(args.output)\n"
        "out.parent.mkdir(parents=True, exist_ok=True)\n"
        "out.write_text(json.dumps({"
        "'method': 'agent_prototype_router', 'trained': True"
        "}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    result = {
        "status": "implemented",
        "title": "Fake Agent Prototype Router",
        "method_summary": "A command-backed implement agent wrote this runnable method.",
        "entrypoint": "method.py",
        "files": [{"path": "method.py"}],
        "experiment_plan": ["run the generated entrypoint", "evaluate submission"],
        "limitations": ["fake implement agent only"],
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
