#!/usr/bin/env python3
"""在全部 90 道题上验证官方评测环境（/opt/pyeval）能不能跑起 evaluator。

## 为什么必须有这一步

评测器改走独立解释器（见 `evaluator_worker._resolve_eval_python`）之后，**少装一个
包的后果不是报错，是一次静默的 −1**：`eval_service.run_evaluator` 用
`capture_output=True` 拉起子进程，失败时只把一个字符串塞进 `error` 字段，
evaluator 打印的 traceback 直接被丢掉。所以缺包会表现成「这道题分很低」，
而不是「这道题挂了」——这正是 s42256-023-00712-7 被 meeko 坑了 14 次都没人发现
的原因。

因此换环境**必须先离线把 90 个 evaluator 全部 import 一遍**，把缺包在上线前
暴露出来。

## 判据

只做 import，不跑评测：逐个 `exec_module` 每道题的 `evaluation/evaluator.py`，
cwd 设为该题的 `evaluation/` 目录（有几道题会 `import sascorer` / `metrics` /
`utils` 这种同目录本地模块，不切 cwd 会误报缺包）。

**import 成功 ≠ 评测一定能跑通**（运行期还可能缺数据文件或外部二进制，
例如 qvina02），但 import 失败一定跑不通。这是成本最低的一道闸。

用法（在任务镜像里跑）::

    python3 verify_eval_env.py \\
        --python /opt/pyeval/bin/python \\
        --tasks-root /nb/data/naturebench_data/tasks

也可以用 `--python $(which python)` 跑一遍任务解释器做对照，看这次换环境
到底换掉了什么。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# 在子解释器里执行的探针。单独写成常量而不是内联，是为了能一眼看清
# 我们到底在子进程里跑了什么。
PROBE = """
import importlib.util, json, os, sys, traceback
path = sys.argv[1]
os.chdir(os.path.dirname(path))
sys.path.insert(0, os.path.dirname(path))
try:
    spec = importlib.util.spec_from_file_location("probe_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(json.dumps({"ok": True}))
except BaseException as exc:
    missing = getattr(exc, "name", None) if isinstance(exc, ImportError) else None
    print(json.dumps({
        "ok": False,
        "type": type(exc).__name__,
        "missing": missing,
        "message": str(exc)[:300],
        "tail": traceback.format_exc()[-400:],
    }))
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default="/opt/pyeval/bin/python")
    parser.add_argument(
        "--tasks-root",
        default="/nb/data/naturebench_data/tasks",
        help="NatureBench 的 data/naturebench_data/tasks 目录",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    root = Path(args.tasks_root)
    evaluators = sorted(root.glob("*/evaluation/evaluator.py"))
    if not evaluators:
        print(f"在 {root} 下没找到任何 evaluation/evaluator.py", file=sys.stderr)
        return 2

    ok: list[str] = []
    bad: list[tuple[str, dict]] = []
    for path in evaluators:
        task = path.parent.parent.name
        try:
            process = subprocess.run(
                [args.python, "-c", PROBE, str(path)],
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
            line = (process.stdout or "").strip().splitlines()
            result = json.loads(line[-1]) if line else {
                "ok": False, "type": "NoOutput", "message": (process.stderr or "")[-300:],
            }
        except subprocess.TimeoutExpired:
            result = {"ok": False, "type": "Timeout", "message": f">{args.timeout}s"}
        except (json.JSONDecodeError, OSError) as exc:
            result = {"ok": False, "type": type(exc).__name__, "message": str(exc)[:200]}
        (ok.append(task) if result.get("ok") else bad.append((task, result)))
        print(f"{'OK  ' if result.get('ok') else 'FAIL'} {task}", flush=True)

    print()
    print(f"{args.python}: {len(ok)}/{len(evaluators)} 个 evaluator 可导入")
    if bad:
        print("\n导入失败的题（上线前必须清零）：")
        missing = sorted({r.get("missing") for _, r in bad if r.get("missing")})
        for task, result in bad:
            print(f"  {task:<24} {result.get('type')}: {result.get('message', '')[:160]}")
        if missing:
            print(f"\n缺的包：{' '.join(missing)}")
            print("把它们补进 fmjob/Dockerfile.evalenv 后重新构建 evalenv 镜像。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
