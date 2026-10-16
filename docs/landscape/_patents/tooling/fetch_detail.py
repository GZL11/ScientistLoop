#!/usr/bin/env python3
"""按标题短语取回 PATENTSCOPE 详情页的摘要与著录项目。

用法:
    python3 docs/patents/fetch_detail.py "evolving prompts for neural networks" ...

只取**摘要 + 著录项目**。权利要求全文在 PATENTSCOPE 上走 JSF POST，爬不到，
必须人工在浏览器里打开 Claims 页签，或等 Google Patents 可用时看那边的纯文本。
"""
from __future__ import annotations

import html
import http.cookiejar
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://patentscope.wipo.int/search/en/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

FIELDS = (
    "Publication Number",
    "Publication Date",
    "International Application No",
    "International Filing Date",
    "Priority Data",
    "Applicants",
    "Inventors",
)


def opener() -> urllib.request.OpenerDirector:
    """带 cookie 的 opener —— detail.jsf 需要搜索会话。"""

    jar = http.cookiejar.CookieJar()
    handler = urllib.request.HTTPCookieProcessor(jar)
    built = urllib.request.build_opener(handler)
    built.addheaders = [("User-Agent", UA), ("Referer", BASE + "result.jsf")]
    return built


def flatten(page: str) -> str:
    """去 script/标签，压成一行，方便按 label 定位。"""

    page = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def fetch(title_phrase: str, client: urllib.request.OpenerDirector) -> dict[str, str]:
    """按标题短语检索，再取第一条的详情页。

    注意：PATENTSCOPE 不认 `PN:` / `WO:` / `DP:` 这类公开号字段（实测 0 命中），
    只有 `EN_TI:` 这种全文/标题字段有效，所以这里用标题短语定位。
    """

    query = urllib.parse.urlencode({"query": f'EN_TI:("{title_phrase}")'})
    with client.open(f"{BASE}result.jsf?{query}", timeout=60) as response:
        listing = response.read().decode("utf-8", errors="ignore")
    match = re.search(r'href="(detail\.jsf[^"]+)"', listing)
    if not match:
        return {"error": f"{title_phrase}: 检索页里没有 detail 链接"}
    with client.open(BASE + html.unescape(match.group(1)), timeout=60) as response:
        detail = response.read().decode("utf-8", errors="ignore")

    flat = flatten(detail)
    out: dict[str, str] = {"query": title_phrase}
    for label in FIELDS:
        index = flat.find(label)
        if index >= 0:
            out[label] = flat[index + len(label) : index + len(label) + 150].strip()
    abstract = re.search(r"Abstract \(EN\)(.*?)(?:\(FR\)|\(DE\)|\(ES\)|$)", flat, re.S)
    out["abstract"] = abstract.group(1).strip()[:1800] if abstract else ""
    title = re.search(r"Title \(EN\)(.*?)(?:\(FR\)|Abstract)", flat, re.S)
    out["title"] = title.group(1).strip()[:300] if title else ""
    return out


def main() -> int:
    """逐个取回并打印。"""

    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    client = opener()
    for phrase in sys.argv[1:]:
        record = fetch(phrase, client)
        print("=" * 100)
        for key, value in record.items():
            print(f"{key}: {value}")
        print()
        time.sleep(4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
