#!/usr/bin/env python3
"""
HTML 验证脚本 — 两层检测：
  Layer 1 静态：正则扫描已知错误模式 + 复合规则（~0ms）
  Layer 2 动态：Playwright 运行 HTML，捕获 JS 运行时错误（~3-5s）

用法:
  python3 validate_html.py path/to/output.html           # 静态 + 运行时（默认）
  python3 validate_html.py path/to/output.html --no-runtime  # 仅静态
退出码:
  0 = 通过
  1 = 发现错误（需要修复）
"""
import re
import sys
import time
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Layer 1-A：单一模式 — 出现即报错
# 格式：(正则, 错误描述, 修复建议)
# ─────────────────────────────────────────────────────────────
BAD_PATTERNS = [
    # BMapGL API 错误
    (
        r'\.setOpacity\s*\(',
        "BMapGL.Polyline 无 setOpacity() 方法",
        "改为 polyline.setStrokeOpacity(n)"
    ),
    # BMapGL script 位置错误
    (
        r'<head>.*api\.map\.baidu\.com.*</head>',
        "BMapGL SDK `<script>` 放在 `<head>` 内，API 内部动态插入资源时 document.body 为 null",
        "将 BMapGL 的 `<script>` 移到 `<body>` 结束标签之前"
    ),
    (
        r'\.setColor\s*\(',
        "BMapGL.Polyline 无 setColor() 方法",
        "改为 polyline.setStrokeColor(color)"
    ),
    (
        r'\.setWidth\s*\(',
        "BMapGL.Polyline 无 setWidth() 方法",
        "改为 polyline.setStrokeWeight(n)"
    ),
    (
        r'\bnew\s+BMap\.',
        "使用了旧版 BMap 命名空间",
        "改为 BMapGL.（如 new BMapGL.Point(...)）"
    ),
    # 数据加载错误
    (
        r'''fetch\s*\(\s*['"]\.\/[^'"]+\.json['"]''',
        "使用 fetch 加载外部 JSON，在 BOS / 独立打开时会失败",
        "使用 Python 内联合并脚本将数据嵌入 HTML（见 SKILL.md §数据与模板分离）"
    ),
    # SVG 编码错误
    (
        r'''btoa\s*\([^)]*svg''',
        "SVG 图标使用 btoa() 编码（中文字符会抛 InvalidCharacterError）",
        "改为 'data:image/svg+xml;utf8,' + encodeURIComponent(svgStr)"
    ),
    # ECharts formatter 字符串字面换行
    (
        r"formatter\s*:\s*'[^'\n]*\n",
        "ECharts formatter 字符串中包含字面换行符（JS 语法错误）",
        r"将换行改为转义字符 \n，例如 formatter: '前半\n后半'"
    ),
    # onclick 中使用 JSON.stringify（双引号会提前关闭 HTML 属性）
    (
        r'onclick\s*=\s*"[^"]*JSON\.stringify',
        "onclick 属性中使用了 JSON.stringify（产生的 \" 会提前关闭属性，导致 JS 语法错误）",
        "改用全局数组 + 数字索引：_clickData[i]=ctx; html+=`<div onclick=\"onItemClick(${i})\">`"
    ),
    # 外部跳转链接
    (
        r'''<a\s+href\s*=\s*['"]https?://''',
        "页面包含外部跳转链接（用户点击后离开页面）",
        "用 <span> 或 <code> 展示 URL，不要生成可点击的外链"
    ),
    # 渐变背景
    (
        r'linear-gradient',
        "页面使用了渐变背景色",
        "页面背景/标题区使用纯色（如 #1E3A5F），禁止渐变"
    ),
]


# ─────────────────────────────────────────────────────────────
# Layer 1-B：复合规则 — "有 A 但缺 B" 才报错
# 格式：(触发正则 A, 必须同时存在的正则 B, 错误描述, 修复建议)
# ─────────────────────────────────────────────────────────────
COMPOUND_CHECKS = [
    (
        r'canvas\.getContext\s*\(',                 # A：使用了 canvas 绘制
        r'devicePixelRatio',                         # B：必须有 HiDPI 适配
        "Canvas 绘制未做 HiDPI 适配（Retina 屏下模糊）",
        "获取 dpr = window.devicePixelRatio || 1，设置 canvas.width/height *= dpr，调用 ctx.scale(dpr, dpr)"
    ),
]


# ─────────────────────────────────────────────────────────────
# 运行时噪音过滤（第三方 SDK 内部报错，非我们代码的问题）
# ─────────────────────────────────────────────────────────────
RUNTIME_IGNORE = [
    r'BMapGL.*api',
    r'favicon\.ico',
    r'ERR_FILE_NOT_FOUND.*api\?',
    r'Content Security Policy',
    r"reading 'coordType'",
    r"reading '_rd'",
    r"setting 'FeatureStyledefault'",
    r"reading 'getZoom'",
    r"Cannot read properties of null.*BMap",
]

# 系统 Chrome 路径（按平台优先级）
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]


# ─────────────────────────────────────────────────────────────
# Layer 1：静态检测
# ─────────────────────────────────────────────────────────────

def static_check(html_path: Path) -> list[tuple[str, str, str]]:
    """返回 [(描述, 修复建议, 片段), ...] 列表，空列表表示通过。"""
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    errors = []

    # 1-A：单一模式
    for pattern, desc, fix in BAD_PATTERNS:
        matches = re.findall(pattern, html, re.I)
        if matches:
            errors.append((desc, fix, matches[0][:80]))

    # 1-B：复合规则
    for trigger, required, desc, fix in COMPOUND_CHECKS:
        if re.search(trigger, html, re.I) and not re.search(required, html, re.I):
            # 找触发片段用于展示
            m = re.search(trigger, html, re.I)
            snippet = html[max(0, m.start() - 10):m.start() + 40].replace('\n', ' ')
            errors.append((desc, fix, snippet[:80]))

    return errors


# ─────────────────────────────────────────────────────────────
# Layer 2：运行时检测（Playwright）
# ─────────────────────────────────────────────────────────────

def _find_chrome() -> str | None:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return None


def runtime_check(html_path: Path, timeout_ms: int = 4000) -> list[str]:
    """
    用 Playwright + 系统 Chrome 打开 HTML，收集 JS 运行时错误。
    返回错误消息列表，空列表表示无运行时错误。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [
            "playwright 未安装 → 执行: python3 -m pip install playwright",
            "然后执行: python3 -m playwright install chromium",
        ]

    chrome_path = _find_chrome()
    runtime_errors = []
    url = html_path.resolve().as_uri()

    try:
        with sync_playwright() as p:
            launch_options = {
                "args": ["--no-sandbox", "--disable-web-security",
                         "--allow-file-access-from-files"]
            }
            if chrome_path:
                launch_options["executable_path"] = chrome_path

            browser = p.chromium.launch(**launch_options)
            page = browser.new_page()
            page.on("pageerror", lambda e: runtime_errors.append(f"PageError: {e}"))
            page.on("console", lambda m: runtime_errors.append(f"ConsoleError: {m.text}")
                    if m.type == "error" else None)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(min(timeout_ms, 2000))
            browser.close()
    except Exception as e:
        return [
            f"浏览器启动失败: {e}",
            "→ 执行: python3 -m playwright install chromium",
        ]

    filtered = []
    for err in runtime_errors:
        if not any(re.search(p, err, re.I) for p in RUNTIME_IGNORE):
            filtered.append(err)
    return filtered


# ─────────────────────────────────────────────────────────────
# 输出格式化
# ─────────────────────────────────────────────────────────────

def print_result(html_path: Path, static_errors, runtime_errors, elapsed: float):
    """Print validation result and return True if passed, False otherwise."""
    # 只有 [SKIP] / [WARN] 前缀的才忽略；其他都视为真实错误
    real_rt = [e for e in runtime_errors if not e.startswith(("[SKIP", "[WARN]"))]
    total = len(static_errors) + len(real_rt)
    if total == 0:
        skips = [e for e in runtime_errors if e.startswith(("[SKIP", "[WARN]"))]
        skip_note = f"  ({skips[0]})" if skips else ""
        print(f"✓ PASS  {html_path.name}  [{elapsed:.1f}s]{skip_note}")
        return True

    print(f"✗ FAIL  {html_path.name}  — 发现 {total} 个问题  [{elapsed:.1f}s]\n")
    idx = 1
    if static_errors:
        print("  ── 静态检测 ──")
        for desc, fix, snippet in static_errors:
            print(f"  [{idx}] {desc}")
            print(f"      片段: {snippet!r}")
            print(f"      修复: {fix}")
            print()
            idx += 1
    if real_rt:
        print("  ── 运行时错误（JS）──")
        for err in real_rt:
            print(f"  [{idx}] {err}")
            idx += 1
        print()
    return False


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    """Entry point: parse CLI args, run validation, exit with code 0 or 1."""
    args = sys.argv[1:]
    run_runtime = "--runtime" in args or "--no-runtime" not in args  # 默认启用，--no-runtime 禁用
    paths = [a for a in args if not a.startswith("--")]

    if not paths:
        print("用法: python3 validate_html.py <html_file> [--no-runtime]")
        sys.exit(2)

    html_path = Path(paths[0])
    if not html_path.exists():
        print(f"[ERROR] 文件不存在: {html_path}")
        sys.exit(2)

    t0 = time.time()
    static_errors = static_check(html_path)
    rt_errors = runtime_check(html_path) if run_runtime else ["[SKIP] 未启用运行时检测（加 --runtime 开启）"]
    elapsed = time.time() - t0
    passed = print_result(html_path, static_errors, rt_errors, elapsed)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
