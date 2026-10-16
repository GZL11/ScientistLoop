"""
runners/workspace.py — 公共 workspace 准备与结果写入

共享逻辑：
  - prepare_workspace()    复制 case/data/ 到 workspace
  - build_instruction()    构建完整指令（从 instruction.md）
  - build_query()          构建澄清 query（从 queries/ 目录）
  - save_json()            写 JSON 到指定路径
  - write_result()         写评测结果 + 打印摘要
  - write_meta()           写实验 .meta.json
"""

import json
import shutil
from pathlib import Path


# ── workspace 准备 ────────────────────────────────────────────────────────────

def prepare_workspace(case: Path, workspace: Path) -> None:
    """创建 workspace 并复制 case/data/ 到 workspace/data/。"""
    workspace.mkdir(parents=True, exist_ok=True)
    src_data = case / "data"
    dst_data = workspace / "data"
    if src_data.is_dir():
        if dst_data.exists():
            shutil.rmtree(dst_data)
        shutil.copytree(src_data, dst_data)


# ── instruction / query 构建 ─────────────────────────────────────────────────

def _append_data_listing(text: str, workspace: Path) -> str:
    """在文本末尾追加 workspace/data/ 的文件列表。"""
    dst_data = workspace / "data"
    if dst_data.is_dir():
        data_files = sorted(p.name for p in dst_data.iterdir() if p.is_file())
        if data_files:
            file_list = "\n".join(f"  - {f}" for f in data_files)
            text += (
                f"\n\n## 工作目录\n"
                f"你的工作目录是 `{workspace}`。\n"
                f"- 数据文件位于 `{dst_data}/`：\n{file_list}\n"
                f"- 所有输出文件（结果、图表等）必须写入工作目录 `{workspace}` 下，不要写到其他位置。"
            )
    return text


def build_instruction(case: Path, workspace: Path) -> str:
    """读取 instruction.md，追加 data/ 文件列表。不注入任何行为引导。"""
    instruction = (case / "instruction.md").read_text(encoding="utf-8")
    instruction = _append_data_listing(instruction, workspace)
    return instruction


def build_query(case: Path, workspace: Path, variant: str = "default") -> str:
    """读取 queries/{variant}.md，追加 data/ 文件列表。不注入任何行为引导。"""
    query_file = case / "queries" / f"{variant}.md"
    if not query_file.is_file():
        raise FileNotFoundError(
            f"Query variant '{variant}' not found: {query_file}"
        )
    query = query_file.read_text(encoding="utf-8")
    query = _append_data_listing(query, workspace)
    return query


# ── JSON 写入 ────────────────────────────────────────────────────────────────

def save_json(path: Path, data) -> None:
    """写 JSON 文件，自动创建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def write_result(workspace: Path, result: dict) -> None:
    """写评测结果到 .eval/result.json 并打印摘要。"""
    result_path = workspace / ".eval" / "result.json"
    save_json(result_path, result)

    score = result.get("overall_score", 0.0)
    print(f"\n── Result ──────────────────────────────────────────")
    print(f"  overall_score:    {score:.4f}")
    print(f"  validity_score:   {result.get('validity_score', '-')}")
    print(f"  quality_score:    {result.get('quality_score', '-')}")
    print(f"  extraction_status: {result.get('extraction_status', '-')}")
    if result.get("extraction_notes"):
        print(f"  extraction_notes: {result['extraction_notes']}")
    if result.get("errors"):
        print(f"  errors:           {result['errors']}")
    print(f"\n  Full result: {result_path}")


def write_meta(batch_dir: Path, meta: dict) -> None:
    """写实验 .meta.json。"""
    save_json(batch_dir / ".meta.json", meta)
