"""提供内置、Python import path 与 entry point 三种 Adapter 注册方式。"""
from __future__ import annotations

import importlib
from importlib import metadata
from typing import Any


_ENTRY_POINT_GROUPS = {
    "agent": "famou_scientist.agent_adapters",
    "benchmark": "famou_scientist.benchmark_adapters",
    "evaluator": "famou_scientist.evaluator_adapters",
}

_BUILTIN_ADAPTERS = {
    ("agent", "cli"): (
        "famou_scientist.loop.plugins.builtins:CliAgentAdapter"
    ),
    ("benchmark", "naturebench"): (
        "famou_scientist.loop.integrations.naturebench.plugin:"
        "NatureBenchBenchmarkAdapter"
    ),
    ("evaluator", "naturebench"): (
        "famou_scientist.loop.integrations.naturebench.plugin:"
        "NatureBenchEvaluatorAdapter"
    ),
    ("benchmark", "scimodelingbench"): (
        "famou_scientist.loop.integrations.scimodelingbench.plugin:"
        "SciModelingBenchBenchmarkAdapter"
    ),
    ("evaluator", "scimodelingbench"): (
        "famou_scientist.loop.integrations.scimodelingbench.plugin:"
        "SciModelingBenchEvaluatorAdapter"
    ),
    ("benchmark", "terminal_bench_science"): (
        "famou_scientist.loop.integrations.terminal_bench_science.plugin:"
        "HarborBenchmarkScienceAdapter"
    ),
    ("evaluator", "terminal_bench_science"): (
        "famou_scientist.loop.integrations.terminal_bench_science.plugin:"
        "HarborBenchmarkScienceEvaluatorAdapter"
    ),
    # Backward-compatible alias for the initial prototype command.
    ("benchmark", "terminal_bench"): (
        "famou_scientist.loop.integrations.terminal_bench.plugin:"
        "HarborBenchmarkScienceAdapter"
    ),
    ("evaluator", "terminal_bench"): (
        "famou_scientist.loop.integrations.terminal_bench.plugin:"
        "HarborBenchmarkScienceEvaluatorAdapter"
    ),
}

_REGISTERED: dict[tuple[str, str], Any] = {}


def register_adapter(kind: str, name: str, provider: Any) -> None:
    """注册进程内 Adapter，主要供应用启动和测试注入使用。"""

    normalized_kind = _normalize_kind(kind)
    normalized_name = _normalize_name(name)
    key = (normalized_kind, normalized_name)
    if key in _REGISTERED and _REGISTERED[key] is not provider:
        raise ValueError(f"Adapter 已注册且 provider 不同: {kind}/{name}")
    _REGISTERED[key] = provider


def _normalize_kind(kind: str) -> str:
    """校验并归一化 Adapter 类型。"""

    value = str(kind).strip().lower()
    if value not in _ENTRY_POINT_GROUPS:
        raise ValueError(f"不支持的 Adapter 类型: {kind!r}")
    return value


def _normalize_name(name: str) -> str:
    """校验非空 Adapter 名称。"""

    value = str(name).strip()
    if not value:
        raise ValueError("Adapter 名称不能为空")
    return value


def _load_import_path(spec: str) -> Any:
    """加载 ``module:attribute`` 形式的 Adapter provider。"""

    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"Adapter import path 必须是 module:attribute: {spec!r}")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise ImportError(f"Adapter provider 不存在: {spec}") from exc


def _load_entry_point(kind: str, name: str) -> Any | None:
    """从已安装 Python 包的 entry point 中查找 Adapter。"""

    group = _ENTRY_POINT_GROUPS[kind]
    discovered = metadata.entry_points()
    selected = (
        discovered.select(group=group, name=name)
        if hasattr(discovered, "select")
        else [item for item in discovered.get(group, []) if item.name == name]
    )
    matches = list(selected)
    if not matches:
        return None
    if len(matches) > 1:
        raise RuntimeError(f"发现多个同名 Adapter entry point: {kind}/{name}")
    return matches[0].load()


def _instantiate(provider: Any) -> Any:
    """实例化 Adapter 类，同时允许直接注册单例对象。"""

    if isinstance(provider, type):
        return provider()
    return provider


def load_adapter(kind: str, name: str) -> Any:
    """按进程注册、内置、entry point、import path 的顺序加载 Adapter。"""

    normalized_kind = _normalize_kind(kind)
    normalized_name = _normalize_name(name)
    key = (normalized_kind, normalized_name)
    provider = _REGISTERED.get(key)
    if provider is None and key in _BUILTIN_ADAPTERS:
        provider = _load_import_path(_BUILTIN_ADAPTERS[key])
    if provider is None:
        provider = _load_entry_point(normalized_kind, normalized_name)
    if provider is None and ":" in normalized_name:
        provider = _load_import_path(normalized_name)
    if provider is None:
        raise LookupError(f"找不到 Adapter: {normalized_kind}/{normalized_name}")
    adapter = _instantiate(provider)
    declared_name = getattr(adapter, "name", None)
    if not isinstance(declared_name, str) or not declared_name.strip():
        raise TypeError(f"Adapter 缺少非空 name 属性: {normalized_kind}/{normalized_name}")
    return adapter


def available_adapters(kind: str) -> tuple[str, ...]:
    """返回当前进程可见的内置和显式注册 Adapter 名称。"""

    normalized_kind = _normalize_kind(kind)
    names = {
        name for adapter_kind, name in _BUILTIN_ADAPTERS if adapter_kind == normalized_kind
    }
    names.update(
        name for adapter_kind, name in _REGISTERED if adapter_kind == normalized_kind
    )
    return tuple(sorted(names))


__all__ = ["available_adapters", "load_adapter", "register_adapter"]
