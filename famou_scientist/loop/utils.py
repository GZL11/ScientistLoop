"""端到端运行时使用的通用标准库工具。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4


def now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    """生成带前缀的唯一标识。"""
    return f"{prefix}_{now_ms()}_{uuid4().hex[:8]}"


def json_dumps(data: object, *, indent: int | None = 2) -> str:
    """以稳定格式序列化结构化数据。"""
    return json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=False)


def read_json(path: Path, default=None):
    """读取结构化数据文件。"""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_text(path: Path, text: str) -> None:
    """原子写入文本文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{uuid4().hex}")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: object) -> None:
    """原子写入结构化数据文件。"""
    atomic_write_text(path, json_dumps(data) + "\n")


def append_jsonl(path: Path, obj: dict) -> None:
    """向行式结构化日志追加记录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    """读取行式结构化日志记录。"""
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    """计算文件的哈希摘要。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(value: str) -> str:
    """将名称规范化为安全路径片段。"""
    s = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in value)
    s = s.strip("-.")
    return s or "item"
