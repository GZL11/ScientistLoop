"""
runners/defaults.py — 共享常量

所有需要引用 runner 类型 → agent 配置目录映射的模块统一从此导入。
"""

from pathlib import Path

CONFIGS_DIR = Path(__file__).parent / "configs"

DEFAULT_AGENT_CONFIG: dict[str, Path | None] = {
    "cc_native":       None,
    "cc_famou":        CONFIGS_DIR / ".claude",
    "cc_single":       CONFIGS_DIR / ".claude-single",
    "opencode_native": None,
    "opencode_famou":  CONFIGS_DIR / ".opencode",
    "opencode_single": CONFIGS_DIR / ".opencode-single",
}

RUNNER_CHOICES = list(DEFAULT_AGENT_CONFIG)

# ── 模型别名 ─────────────────────────────────────────────────────────────────
# CLI --model 接受别名或完整 model ID。别名由各 backend 翻译为平台格式。
# 完整 ID（不在别名表中的值）原样透传给对应平台。

MODEL_ALIASES: dict[str, dict[str, str]] = {
    "sonnet":   {"cc": "claude-sonnet-4-6",  "opencode": "anthropic/claude-sonnet-4-6"},
    "opus":     {"cc": "claude-opus-4-6",    "opencode": "anthropic/claude-opus-4-6"},
    "haiku":    {"cc": "claude-haiku-4-5",   "opencode": "anthropic/claude-haiku-4-5"},
}


def resolve_model(alias: str | None, runner_type: str) -> str | None:
    """将 model 别名解析为平台特定的 model ID。

    - None → None（使用平台默认）
    - 已知别名 → 对应平台 ID
    - 其他值 → 原样透传
    """
    if alias is None:
        return None
    platform = "opencode" if runner_type.startswith("opencode") else "cc"
    entry = MODEL_ALIASES.get(alias)
    if entry:
        return entry[platform]
    return alias
