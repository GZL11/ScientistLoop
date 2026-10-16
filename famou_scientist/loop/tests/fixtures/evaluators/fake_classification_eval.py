#!/usr/bin/env python3
"""供 Loop 测试和示例使用的模拟分类 benchmark evaluator。

脚本读取模拟提交产物，并向标准输出写入一个 JSON 对象；命令型评测适配器
会解析标准输出的最后一行。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    """评测模拟提交并输出公开或正式评测结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--mode", choices=["public", "official"], default="public")
    args = parser.parse_args()

    submission = Path(args.submission)
    valid = submission.exists()
    if args.mode == "official":
        out = {
            "valid": valid,
            "official_metrics": {"accuracy": 0.812},
            "diagnostics_public": {"format_check": "passed" if valid else "missing_submission"},
            "extra": {"split": "official", "submission_exists": valid},
        }
    else:
        out = {
            "valid": valid,
            "metrics": {"accuracy": 0.821, "latency_ms": 1.7},
            "diagnostics_public": {"format_check": "passed" if valid else "missing_submission"},
            "extra": {"split": "public", "submission_exists": valid},
        }
    print(json.dumps(out, ensure_ascii=False))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
