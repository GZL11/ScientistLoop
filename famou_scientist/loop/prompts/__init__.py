"""集中加载和渲染 Loop 中所有智能体提示词。"""
from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any


PROMPT_ROOT = Path(__file__).resolve().parent


def prompt_path(relative_path: str | Path) -> Path:
    """解析 Prompt 相对路径并拒绝目录穿越。"""
    path = (PROMPT_ROOT / relative_path).resolve()
    try:
        path.relative_to(PROMPT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Prompt 路径越界: {relative_path}") from exc
    return path


def load_prompt(relative_path: str | Path) -> str:
    """读取指定 Prompt；缺失时直接失败，避免静默使用低质量默认值。"""
    path = prompt_path(relative_path)
    if not path.is_file():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt(relative_path: str | Path, **values: Any) -> str:
    """使用严格的 ``string.Template`` 变量渲染指定 Prompt。"""
    variables = {name: str(value) for name, value in values.items()}
    return Template(load_prompt(relative_path)).substitute(variables)
