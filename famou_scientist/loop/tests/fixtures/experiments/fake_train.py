#!/usr/bin/env python3
"""供 Loop 实验运行器示例和测试使用的模拟训练命令。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """读取模拟训练输入并输出实验产物和指标。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fail", action="store_true")
    args = parser.parse_args()
    if args.fail:
        print("fake training failure requested")
        return 3
    inp = Path(args.input)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"trained": True, "input_exists": inp.exists(), "input": str(inp)}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"artifact": str(out), "metrics": {"train_loss": 0.123}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
