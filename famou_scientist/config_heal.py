# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""启动前自愈：补齐自定义 provider 所需的容量兼容配置。

为什么需要：OpenCode 的自动 compact 按「token >= limit.context * ~0.9」触发。
**自定义 provider**（配置里带 ``npm`` / ``options.baseURL`` 的，如自建网关）在
models.dev 目录里匹配不到，若模型定义漏写 ``limit`` → OpenCode 视上下文上限为 0
→ auto-compact 永不触发 → 上下文一路涨到被网关硬拒、模型逐轮吐空（实测故障）。

新手手写 ``opencode.jsonc`` 几乎不会想到 ``limit`` 这一项，故在启动主路径上
**顺手补全**：只对「自定义 provider 且模型完全没有 limit 字段」的项回填一个安全默认，
用户写了任何 limit 都不碰；官方 provider（无 npm/baseURL，走 models.dev）也不碰。

自定义 Anthropic 网关还可能对单个输入字段施加比 OpenCode 默认值更小的字符限制。
OpenCode 默认允许 5 MiB 图片 base64；当前网关只接受 1 MiB，读取一张普通 PNG 就会
让下一轮请求失败。未显式配置附件限制时，回填 256 KiB 上限，让 OpenCode 在图片进入
模型上下文前自动缩放；用户已有 ``attachment`` 配置时不覆盖。

实现纪律：
- **不整文件重写**（会毁注释/格式）：先解析定位缺项，再在对应模型块的 ``}`` 前**定点插入**。
- 写前**备份**为 ``<name>.bak``；**幂等**（已补过再跑不重复插入）；任何异常都**静默跳过**，绝不阻断启动。
- 不碰 key、不碰 provider 结构，延续 doctor「不写凭证」的红线——只补一个非敏感的容量数字。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["heal_config", "DEFAULT_CONTEXT", "DEFAULT_OUTPUT", "DEFAULT_IMAGE_MAX_BASE64_BYTES"]

# 回填默认值：这套自建网关常见模型（claude / glm 系）实测窗口 ~20 万 token，
# 取保守下限 200000 留余量；用户可在 opencode.jsonc 自行覆盖。
DEFAULT_CONTEXT = 200000
DEFAULT_OUTPUT = 32000
DEFAULT_IMAGE_MAX_BASE64_BYTES = 256 * 1024

_CONFIG_CANDIDATES = (
    Path.home() / ".config" / "opencode" / "opencode.jsonc",
    Path.home() / ".config" / "opencode" / "opencode.json",
    Path.home() / ".config" / "opencode" / "config.json",
)


def _strip_jsonc(text: str) -> str:
    """去掉 // 行注释与 /* */ 块注释，便于 json.loads 解析（仅用于**分析**，不回写）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # 去行注释：保守起见只删「整行以可选空白 + // 开头」与「空白 + //」到行尾，
    # 避免误伤字符串里的 //（本配置 URL 用 {env:...} 占位，通常不含裸 //）。
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r"\s//[^\n]*$", "", text, flags=re.M)
    return text


def _is_custom_provider(pv: dict) -> bool:
    """自定义 provider 判定：带 npm 或 options.baseURL（自建/OpenAI 兼容网关）。

    官方 provider（anthropic/openai 等，靠 models.dev 给 limit）不在此列，不回填。
    """
    if not isinstance(pv, dict):
        return False
    if pv.get("npm"):
        return True
    opts = pv.get("options")
    return isinstance(opts, dict) and bool(opts.get("baseURL"))


def _models_needing_limit(cfg: dict) -> list[str]:
    """返回「自定义 provider 下、缺 limit.context」的模型 id 列表。"""
    need: list[str] = []
    providers = cfg.get("provider")
    if not isinstance(providers, dict):
        return need
    for _pid, pv in providers.items():
        if not _is_custom_provider(pv):
            continue
        models = pv.get("models")
        if not isinstance(models, dict):
            continue
        for mid, mv in models.items():
            limit = mv.get("limit") if isinstance(mv, dict) else None
            has_ctx = isinstance(limit, dict) and limit.get("context")
            if not has_ctx:
                need.append(mid)
    return need


def _inject_limit(text: str, model_id: str) -> tuple[str, bool]:
    """在原始文本里给 ``"model_id": { ... }`` 块的 ``}`` 前定点插入 limit 字段。

    保留注释/缩进；找不到或已含 limit 则不动。返回 (新文本, 是否改动)。
    """
    # 匹配 "model_id" : { ...(块内无嵌套花括号，模型块都是扁平的)... }
    pat = re.compile(
        r'("' + re.escape(model_id) + r'"\s*:\s*\{)([^{}]*?)(\})'
    )
    m = pat.search(text)
    if not m:
        return text, False
    body = m.group(2)
    if '"limit"' in body:  # 已有 limit，幂等跳过
        return text, False
    inserted = (
        f'"limit": {{ "context": {DEFAULT_CONTEXT}, "output": {DEFAULT_OUTPUT} }}'
    )
    trimmed = body.rstrip()
    # 块内已有字段（如 "name"）→ 在其后补逗号再加 limit；空块直接放进去。
    if trimmed.rstrip().endswith(",") or not trimmed.strip():
        new_body = f"{trimmed} {inserted} "
    else:
        new_body = f"{trimmed}, {inserted} "
    new_text = text[: m.start()] + m.group(1) + new_body + m.group(3) + text[m.end():]
    return new_text, True


def _needs_anthropic_image_cap(cfg: dict) -> bool:
    """自定义 Anthropic 网关且用户未配置附件策略时，需要保守图片上限。"""
    if isinstance(cfg.get("attachment"), dict):
        return False
    providers = cfg.get("provider")
    if not isinstance(providers, dict):
        return False
    return any(
        isinstance(pv, dict)
        and pv.get("npm") == "@ai-sdk/anthropic"
        and isinstance(pv.get("options"), dict)
        and bool(pv["options"].get("baseURL"))
        for pv in providers.values()
    )


def _inject_image_cap(text: str) -> tuple[str, bool]:
    """在 JSONC 顶层追加 attachment.image；仅用于确认不存在 attachment 的配置。"""
    stripped = text.rstrip()
    if not stripped.endswith("}") or '"attachment"' in stripped:
        return text, False
    head = stripped[:-1].rstrip()
    comma = "" if head.endswith("{") or head.endswith(",") else ","
    block = (
        f'{comma}\n  "attachment": {{\n'
        f'    "image": {{ "auto_resize": true, "max_base64_bytes": {DEFAULT_IMAGE_MAX_BASE64_BYTES} }}\n'
        "  }\n}"
    )
    return head + block + text[len(stripped):], True


def heal_config(verbose: bool = True) -> int:
    """回填缺失的兼容配置；返回改动项数（0 = 无需处理或失败静默跳过）。

    全程异常吞掉：自愈是锦上添花，绝不能让它阻断 famou 启动。
    """
    try:
        cfg_path = next((p for p in _CONFIG_CANDIDATES if p.exists()), None)
        if cfg_path is None:
            return 0  # 没有全局配置（可能走方式 A auth.json）→ 不插手
        raw = cfg_path.read_text(encoding="utf-8")
        try:
            cfg = json.loads(_strip_jsonc(raw))
        except (json.JSONDecodeError, ValueError):
            return 0  # 解析不了（注释结构特殊等）→ 宁可不动，不冒险毁配置
        need = _models_needing_limit(cfg)

        new_text = raw
        healed: list[str] = []
        for mid in need:
            new_text, changed = _inject_limit(new_text, mid)
            if changed:
                healed.append(mid)
        image_cap = False
        if _needs_anthropic_image_cap(cfg):
            new_text, image_cap = _inject_image_cap(new_text)
        if not healed and not image_cap:
            return 0

        # 写前备份（只备份一次，已存在 .bak 不覆盖，保住最初原貌）
        bak = cfg_path.with_suffix(cfg_path.suffix + ".bak")
        if not bak.exists():
            bak.write_text(raw, encoding="utf-8")
        cfg_path.write_text(new_text, encoding="utf-8")

        if verbose:
            if healed:
                print(
                    f"  [自愈] 已为自定义 provider 模型补默认上下文上限"
                    f"（context={DEFAULT_CONTEXT}）：{', '.join(healed)}"
                )
            if image_cap:
                print(
                    f"  [自愈] 已限制自定义 Anthropic 网关图片输入为 "
                    f"{DEFAULT_IMAGE_MAX_BASE64_BYTES} bytes，避免 base64 超过网关单项限制。"
                )
            print(f"         可在 {cfg_path} 调整；原配置已备份为 {bak.name}。")
        return len(healed) + int(image_cap)
    except Exception:  # noqa: BLE001 — 自愈绝不阻断启动
        return 0
