#!/usr/bin/env python3
"""从 WIPO PATENTSCOPE 采集专利条目（Google Patents 被限流时的第二条链路）。

用法:
    export ALL_PROXY=...
    python3 docs/patents/harvest_patentscope.py --queries docs/patents/queries.json \
            --out docs/patents/raw_ps

输出 schema 与 harvest.py 对齐，build_csv.py 可以直接把两边合起来去重。

两处和 Google Patents 的差别，用之前要知道：
- PATENTSCOPE 每页固定 10 条，靠 &currentNavigationRow=N 翻页；
- 它的英文全文对 CN 专利覆盖不全（CN 全文多为中文），所以 CN 那部分仍要靠
  Google Patents 或中文检索式补，不能只看这一路的结果就下"没人做"的结论。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://patentscope.wipo.int/search/en/result.jsf"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SLEEP = float(os.environ.get("PS_SLEEP", "4"))

PHRASE_RE = re.compile(r'"([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")
BLOCK_RE = re.compile(r'<div id="resultListForm:resultTable:\d+:patentResult".*?(?=<div id="resultListForm:resultTable:\d+:patentResult"|$)', re.S)
NUMBER_RE = re.compile(r'patent-number">([^<]+)<')
TITLE_RE = re.compile(r'ps-patent-result--title--title content--text-wrap">(.*?)</div>', re.S)
COUNTRY_RE = re.compile(r'ctr-pubdate"><span class="notranslate">([A-Z]{2})</span>')
PUBDATE_RE = re.compile(r'ColumnPubDate" class="notranslate">([\d.]+)<')
TOTAL_RE = re.compile(r"([0-9][0-9,]*)\s+results")


def text(fragment: str) -> str:
    """去标签 + 反转义 + 压空白。"""

    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def field(block: str, label: str) -> str:
    """抓 'Applicant' / 'Inventor' 这类 label 后面的值。"""

    match = re.search(re.escape(label) + r"\s*</span>(.*?)</span>\s*</span>", block, re.S)
    if not match:
        match = re.search(re.escape(label) + r"(.{0,400}?)(?:Inventor|Int\.Class|Abstract|$)", block, re.S)
    return text(match.group(1))[:200] if match else ""


def to_patentscope(query: str, extra: dict[str, str]) -> str:
    """把 Google 风格的窄短语检索式翻成 PATENTSCOPE 检索式。

    `"a" "b"` 在 Google 是隐式 AND；PATENTSCOPE 必须写显式 AND，且要指定字段。
    """

    assignee = extra.get("assignee")
    phrases = PHRASE_RE.findall(query)
    parts = []
    if phrases:
        joined = " AND ".join(f'"{phrase}"' for phrase in phrases)
        parts.append(f"EN_ALLTXT:({joined})")
    if assignee:
        parts.append(f'PA:("{assignee}")')
    return " AND ".join(parts) if parts else 'EN_ALLTXT:("large language model")'


def fetch(url: str, *, retries: int = 4) -> str:
    """带退避的 GET，返回 HTML。"""

    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8", errors="ignore")
        except Exception as error:  # noqa: BLE001 - 网络层什么都可能抛
            last = error
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}") from last


def parse(page: str) -> list[dict]:
    """从结果页 HTML 里抠出条目。"""

    rows = []
    for block in BLOCK_RE.findall(page):
        number = NUMBER_RE.search(block)
        if not number:
            continue
        country = COUNTRY_RE.search(block)
        title = TITLE_RE.search(block)
        pubdate = PUBDATE_RE.search(block)
        raw_date = pubdate.group(1) if pubdate else ""
        # PATENTSCOPE 是 DD.MM.YYYY，统一成 ISO 方便和 Google 那路对齐
        iso = ""
        if raw_date.count(".") == 2:
            day, month, year = raw_date.split(".")
            iso = f"{year}-{month}-{day}"
        rows.append(
            {
                "publication_number": f"{country.group(1) if country else ''}{number.group(1).strip()}",
                "title": text(title.group(1)) if title else "",
                "assignee": field(block, "Applicant"),
                "inventor": field(block, "Inventor"),
                "publication_date": iso,
                "priority_date": "",
                "filing_date": "",
                "snippet": "",
                "_source": "patentscope",
            }
        )
    return rows


def harvest(name: str, query: str, pages: int, out_dir: pathlib.Path, axis: str) -> int:
    """抓一条 query 的前 pages 页（每页 10 条），落 JSONL。"""

    seen: set[str] = set()
    rows: list[dict] = []
    total = None
    for page_index in range(pages):
        params = {"query": query}
        if page_index:
            params["currentNavigationRow"] = str(page_index + 1)
        url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
        try:
            page = fetch(url)
        except RuntimeError as error:
            print(f"  ! {name} page={page_index} {error}", file=sys.stderr, flush=True)
            break
        if total is None:
            match = TOTAL_RE.search(page)
            total = match.group(1) if match else "?"
        batch = parse(page)
        if not batch:
            break
        for row in batch:
            if row["publication_number"] in seen:
                continue
            seen.add(row["publication_number"])
            row["_axis"] = axis or name
            row["_query_name"] = name
            row["_query"] = query
            rows.append(row)
        time.sleep(SLEEP)

    path = out_dir / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(rows)} 条落盘 (接口报总命中 {total})", flush=True)
    return len(rows)


def main() -> int:
    """读 queries.json，翻译检索式，逐条采集。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--only", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = json.loads(pathlib.Path(args.queries).read_text(encoding="utf-8"))

    grand = 0
    for spec in specs:
        name = spec["name"]
        if args.only and args.only not in name:
            continue
        path = out_dir / f"{name}.jsonl"
        if path.exists() and path.stat().st_size > 0 and not args.force:
            print(f"[{name}] 已有结果，跳过")
            continue
        query = to_patentscope(spec["q"], spec.get("extra") or {})
        print(f"[{name}] {query}", flush=True)
        grand += harvest(name, query, args.pages, out_dir, spec.get("axis") or "")
    print(f"合计 {grand} 条（未跨 query 去重）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
