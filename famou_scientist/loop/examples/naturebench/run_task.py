#!/usr/bin/env python3
"""在 NatureBench 提供的任务环境中执行一个 Famou 分支实现。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _copy_method(method_dir: Path, workspace_dir: Path) -> None:
    """复制实现代码到单次运行目录并排除管理端产物。"""
    blocked = {
        "benchmark_task",
        "famou_agent_result.json",
        "method_manifest.json",
        "output",
        "outputs",
        "logs",
        "__pycache__",
    }

    def ignore(directory: str, names: list[str]) -> set[str]:
        """返回当前目录中不应复制的名称。"""
        del directory
        return {
            name
            for name in names
            if name in blocked or name.startswith(".git") or name.endswith(".pyc")
        }

    shutil.copytree(method_dir, workspace_dir, dirs_exist_ok=True, ignore=ignore)


def _run_local(task_dir: Path, workspace_dir: Path, output_dir: Path) -> subprocess.CompletedProcess:
    """使用当前 Python 环境运行任务，主要用于适配器测试。"""
    environment = dict(os.environ)
    environment["DATA_DIR"] = str(task_dir / "problem" / "data")
    environment["OUTPUT_DIR"] = str(output_dir)
    return subprocess.run(
        [sys.executable, "run.py"],
        cwd=str(workspace_dir),
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _run_docker(
    task_dir: Path,
    workspace_dir: Path,
    output_dir: Path,
    *,
    image: str,
    network: str,
) -> subprocess.CompletedProcess:
    """使用 NatureBench 镜像和只读公开任务挂载运行实现。"""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "-v",
        f"{(task_dir / 'problem').resolve()}:/task/problem:ro",
        "-v",
        f"{workspace_dir.resolve()}:/workspace",
        "-v",
        f"{output_dir.resolve()}:/output",
        "-w",
        "/workspace",
        "-e",
        "DATA_DIR=/task/problem/data",
        "-e",
        "OUTPUT_DIR=/output",
        image,
        "python",
        "run.py",
    ]
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _tail(text: str, limit: int = 16_000) -> str:
    """保留子进程输出尾部，避免结果文件无限增长。"""
    return text if len(text) <= limit else "[... truncated ...]\n" + text[-limit:]


def main(argv: list[str] | None = None) -> int:
    """解析参数、运行任务并输出 ExperimentRunner 结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--method-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--output-dir",
        help="独立 Candidate 的提交目录；省略时兼容使用 run-dir/output",
    )
    parser.add_argument("--runtime", choices=["docker", "local"], default="docker")
    parser.add_argument("--image", default="naturebench-base:v3")
    parser.add_argument("--network", default="none")
    args = parser.parse_args(argv)

    task_dir = Path(args.task_dir).expanduser().resolve()
    method_dir = Path(args.method_dir).expanduser().resolve()
    run_dir = Path(args.run_dir).expanduser().resolve()
    workspace_dir = run_dir / "workspace"
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else run_dir / "output"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    error = None
    process = None
    try:
        if not (task_dir / "problem" / "README.md").is_file():
            raise FileNotFoundError(f"NatureBench 任务目录无效: {task_dir}")
        if not (method_dir / "run.py").is_file():
            raise FileNotFoundError(f"实现缺少 run.py: {method_dir}")
        _copy_method(method_dir, workspace_dir)
        if args.runtime == "docker":
            process = _run_docker(
                task_dir,
                workspace_dir,
                output_dir,
                image=args.image,
                network=args.network,
            )
        else:
            process = _run_local(task_dir, workspace_dir, output_dir)
    except Exception as exc:  # noqa: BLE001 - 错误需要转换成可持久化结果
        error = repr(exc)

    returncode = process.returncode if process is not None else -1
    result = {
        "valid": error is None and returncode == 0 and output_dir.exists(),
        "artifact": str(output_dir),
        "returncode": returncode,
        "runtime": args.runtime,
        "image": args.image if args.runtime == "docker" else None,
        "task_id": task_dir.name,
        "workspace": str(workspace_dir),
        "stdout": _tail(process.stdout or "") if process is not None else "",
        "stderr": _tail(process.stderr or "") if process is not None else "",
        "error": error,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
