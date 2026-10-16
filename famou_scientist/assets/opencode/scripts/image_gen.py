#!/usr/bin/env python3
"""image_gen —— 调生图模型（gpt-image-2）出**架构/概览/示意图**，存盘。

定位：科研论文的**架构图 / 方法概览图 / 概念示意图**用代码（TikZ/matplotlib）
很难画好看，改由生图模型出。配 scientific-visualization skill 的"读方法→写提示词
→出图→read 真看核对→重出"闭环；由 arc.ts 的 arc_generate_schematic 工具调用。

红线（与 famou "真实性优先"一致）：
- **只画 schematic**（架构/概览/流程/概念示意，无真实数据）；**数据图（柱/线/散点）
  绝不走这里**——那必须 matplotlib 从 results.json 画，生图模型会把数值"编"得像而错。
- 出图后由上层 agent `read` 真看 + 对照方法段核对幻觉模块，本内核只负责 prompt→png。

网关（复用 opencode 启动配置的那套通用网关，用户无需额外配）：
- 默认读 `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`（opencode 配的，所有调模型处通用，
  实测是个内部多模型 router、以 OpenAI 协议也提供 gpt-image-2）。
- 这两个变量只覆盖"provider 配置走 `{env:VAR}` 模板"这一种情况——opencode 还有一套完全独立、
  不落地到任何环境变量的凭证机制（`auth.json` / `OPENCODE_AUTH_CONTENT`，按 providerID 存取）。
  聊天能跑只说明"某一套"生效了，不代表这两个变量真的有值。两个环境变量都读不到时，会再直接
  解析 opencode 自己实际在用的 provider 配置（`opencode.json`/`.jsonc`，含 `OPENCODE_CONFIG_DIR`
  那份），取它给聊天用的同一个 baseURL/apiKey——而不是猜它用的是哪个环境变量名。
- 可选覆盖：`FAMOU_IMAGE_API_BASE` / `FAMOU_IMAGE_API_KEY`（想用另一个图像端点时才设）。
- `FAMOU_IMAGE_MODEL`（默认 gpt-image-2）、`FAMOU_IMAGE_SIZE`（默认 1536x1024）。

设计要点：
- 纯 stdlib（urllib），无第三方依赖，仿 latex_template.py。
- 以 **OpenAI 协议** POST `{base}/v1/images/generations`，body {model,prompt,size,n:1}，
  header Authorization: Bearer <token>。
- 响应优先取 data[0].b64_json（base64 解码落盘）；无则回退下载 data[0].url。
- 走环境代理（urllib 自动识别 ALL_PROXY/HTTPS_PROXY）；内部 IP 网关通常不需代理、直连即可。
- 缺凭证 / 网关不可达 / 没返回图：一律返回 {"error":...}，**如实报错不静默**。

CLI:  python image_gen.py --prompt-file <f> --out <png> [--size 1536x1024]
      → 打印 JSON：{"generated","image_path","model","size","note"} 或 {"error":...}
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# 默认模型 / 尺寸（可被环境变量覆盖）。
_DEFAULT_MODEL = "gpt-image-2"
_DEFAULT_SIZE = "1536x1024"
_TIMEOUT = 180  # 出图可能较慢，给足超时

_ENV_TEMPLATE = re.compile(r"\{env:([^}]+)\}")


def _strip_jsonc(text: str) -> str:
    """去掉 JSONC 的 `//`/`/* */` 注释，走字符级状态机而不是正则。

    opencode 的 opencode.jsonc 允许注释；但 baseURL 这类字段的值本身常含 `//`
    （如 "https://..."），naive 正则会把字符串里的 `//` 也当成行注释切掉，必须
    先认字符串边界（含转义引号）再判断是否在注释里。
    """
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _load_jsonc(path: Path) -> dict:
    try:
        return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _opencode_config_files() -> list[Path]:
    """opencode 会合并加载配置的目录（对应源码 ConfigPaths.directories 的其中两项）：
    全局 config dir（$XDG_CONFIG_HOME/opencode，未设则 ~/.config/opencode）+
    OPENCODE_CONFIG_DIR（famou-scientist 启动时指向自己 assets/opencode，通常没有
    provider 字段，但一并试一遍无害）。真正定义自定义 provider 的多半是前者。"""
    xdg_config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    dirs = [Path(xdg_config) / "opencode"]
    extra = os.environ.get("OPENCODE_CONFIG_DIR")
    if extra:
        dirs.append(Path(extra))
    return [d / name for d in dirs for name in ("opencode.json", "opencode.jsonc")]


def _substitute_env(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _ENV_TEMPLATE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _auth_credential(provider_id: str) -> str:
    """opencode 自己的凭证库：auth.json（$XDG_DATA_HOME/opencode/auth.json，未设则
    ~/.local/share/opencode/auth.json）或 OPENCODE_AUTH_CONTENT 环境变量（同结构的 JSON），
    按 providerID 存取。这套跟 `{env:VAR}` 模板是两条独立路径，很多自定义 provider（尤其
    走 `opencode auth login` 或由平台直接注入凭证的）只走这条，压根不落地到任何环境变量。
    """
    raw = os.environ.get("OPENCODE_AUTH_CONTENT")
    if not raw:
        data_dir = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        try:
            raw = (Path(data_dir) / "opencode" / "auth.json").read_text(encoding="utf-8")
        except OSError:
            return ""
    try:
        entry = json.loads(raw).get(provider_id) or {}
    except json.JSONDecodeError:
        return ""
    return str(entry.get("key") or entry.get("access") or "").strip()


def _resolve_from_opencode_config() -> tuple[str, str]:
    """兜底：直接读 opencode 实际在用的 provider 配置，取它给聊天用的同一份 baseURL/apiKey，
    而不是猜它具体用哪个环境变量名（见模块顶部说明）。"""
    for path in _opencode_config_files():
        providers = _load_jsonc(path).get("provider") or {}
        for provider_id, definition in providers.items():
            options = (definition or {}).get("options") or {}
            base = _substitute_env(options.get("baseURL", "")).strip()
            token = _substitute_env(options.get("apiKey", "")).strip() or _auth_credential(provider_id)
            if base and token:
                return base, token
    return "", ""


def _resolve_gateway() -> tuple[str, str]:
    """解析网关 base + token。

    顺序：FAMOU_IMAGE_*（专用覆盖）→ ANTHROPIC_*（opencode 常见的 `{env:VAR}` 模板场景）→
    直接解析 opencode 的 provider 配置（覆盖 auth.json/OPENCODE_AUTH_CONTENT 这条不经过环境
    变量的路径）。base 统一规整成不带尾部 /v1 的裸 base（请求时再补 /v1/images/generations）。

    Returns:
        (base, token)；两条路径都没找到则 base/token 为空串，由调用方判错。
    """
    base = (
        os.environ.get("FAMOU_IMAGE_API_BASE")
        or os.environ.get("ANTHROPIC_BASE_URL")
        or ""
    ).strip()
    token = (
        os.environ.get("FAMOU_IMAGE_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or ""
    ).strip()
    if not base or not token:
        cfg_base, cfg_token = _resolve_from_opencode_config()
        base = base or cfg_base
        token = token or cfg_token
    # 规整：去掉尾部斜杠与可能的 /v1（opencode 配的是 {base}/v1，env 里多为裸 base，统一）。
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base, token


def generate(prompt: str, out_path: str, size: str = "") -> dict:
    """调生图模型出一张图、落盘到 out_path。返回结果 dict（含 error 字段表示失败）。"""
    base, token = _resolve_gateway()
    if not base or not token:
        return {
            "error": (
                "未配置出图网关：ANTHROPIC_BASE_URL+ANTHROPIC_AUTH_TOKEN 环境变量、"
                "opencode 自己的 provider 配置（含 auth.json/OPENCODE_AUTH_CONTENT）都没找到"
                "可用的 baseURL+apiKey，或显式设 FAMOU_IMAGE_API_BASE+FAMOU_IMAGE_API_KEY。"
                "凭证只走环境变量/opencode 自身配置，不写入文件。"
            )
        }

    model = (os.environ.get("FAMOU_IMAGE_MODEL") or _DEFAULT_MODEL).strip()
    size = (size or os.environ.get("FAMOU_IMAGE_SIZE") or _DEFAULT_SIZE).strip()
    url = f"{base}/v1/images/generations"

    body = json.dumps(
        {"model": model, "prompt": prompt, "size": size, "n": 1}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # noqa: PERF203
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        return {"error": f"网关 HTTP {e.code}：{e.reason}. {detail}", "url": url, "model": model}
    except Exception as e:  # noqa: BLE001 — 网络/超时/解析等一律如实报错
        return {"error": f"请求网关失败：{e!r}", "url": url, "model": model}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"网关返回非 JSON：{raw[:300]}", "url": url, "model": model}

    data = payload.get("data") or []
    if not data:
        # 有的网关把错误塞在 error 字段里。
        err = payload.get("error") or payload
        return {"error": f"网关未返回图像：{json.dumps(err, ensure_ascii=False)[:400]}", "model": model}

    item = data[0]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 优先 b64_json；否则回退下载 url。
    b64 = item.get("b64_json")
    if b64:
        try:
            out.write_bytes(base64.b64decode(b64))
        except Exception as e:  # noqa: BLE001
            return {"error": f"解码 b64 图像失败：{e!r}", "model": model}
    else:
        img_url = item.get("url")
        if not img_url:
            return {"error": "网关返回项既无 b64_json 也无 url", "model": model}
        try:
            with urllib.request.urlopen(img_url, timeout=_TIMEOUT) as ir:
                out.write_bytes(ir.read())
        except Exception as e:  # noqa: BLE001
            return {"error": f"下载图像 url 失败：{e!r}", "url": img_url, "model": model}

    return {
        "generated": True,
        "image_path": str(out),
        "model": model,
        "size": size,
        "note": (
            "schematic 由生图模型生成——务必用 read 工具真看这张图，"
            "对照论文方法段逐模块核对有无幻觉结构，有出入改提示词重出。"
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="调生图模型出架构/概览/示意图")
    ap.add_argument("--prompt-file", required=True, help="提示词文件路径（避免命令行转义/超长）")
    ap.add_argument("--out", required=True, help="输出 png 路径")
    ap.add_argument("--size", default="", help="尺寸如 1536x1024（默认走环境/内置）")
    args = ap.parse_args(argv)

    try:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    except OSError as e:
        print(json.dumps({"error": f"读提示词文件失败：{e!r}"}, ensure_ascii=False))
        return 1

    if not prompt:
        print(json.dumps({"error": "提示词为空"}, ensure_ascii=False))
        return 1

    res = generate(prompt, args.out, size=args.size)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("generated") else 1


if __name__ == "__main__":
    raise SystemExit(main())
