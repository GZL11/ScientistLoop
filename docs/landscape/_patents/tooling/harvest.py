#!/usr/bin/env python3
"""从 Google Patents 的公开 XHR 检索接口采集专利条目。

用法:
    export ALL_PROXY=...   # 需要代理时
    python3 docs/patents/harvest.py --queries docs/patents/queries.json \
            --out docs/patents/raw

每条 query 单独落一份 JSONL，便于分轴复核；合并去重交给 build_csv.py。
接口是 patents.google.com 前端自己调的公开接口，无需 key；这里限速 1 req/s。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://patents.google.com/xhr/query"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SLEEP = float(os.environ.get("GP_SLEEP", "8"))


def build_url(query: str, *, page: int = 0, extra: dict[str, str] | None = None) -> str:
    """拼出 xhr/query 的 url 参数（内层用 + 代空格，整体再 quote 一次）。"""

    parts = [f"q={query.replace(' ', '+')}"]
    for key, value in (extra or {}).items():
        parts.append(f"{key}={value.replace(' ', '+')}")
    if page:
        parts.append(f"page={page}")
    inner = "&".join(parts)
    return f"{ENDPOINT}?url={urllib.parse.quote(inner, safe='')}&exp="


def fetch(url: str, *, retries: int = 12) -> dict:
    """带长退避的 GET。

    Google 对共享出口 IP 会整站返回 503 "unusual traffic"，封禁通常持续
    几十分钟；所以 503 走分钟级退避并多试几轮，让长任务能自己熬过去。
    """

    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last = error
            wait = min(600, 90 * (attempt + 1)) if error.code in (429, 503) else 10
            print(f"    HTTP {error.code}，等 {wait}s 重试", file=sys.stderr, flush=True)
            time.sleep(wait)
        except Exception as error:  # noqa: BLE001 - 网络层什么都可能抛
            last = error
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}") from last


def iter_results(payload: dict):
    """把 xhr 响应里嵌套的 cluster/result 拍平成 patent 字典。"""

    for cluster in (payload.get("results") or {}).get("cluster") or []:
        for row in cluster.get("result") or []:
            patent = row.get("patent")
            if patent:
                yield patent


def harvest(
    name: str,
    query: str,
    extra: dict[str, str],
    max_pages: int,
    out_dir: pathlib.Path,
    axis: str = "",
) -> int:
    """抓一条 query 的前 max_pages 页，写 raw/<name>.jsonl，返回条数。"""

    seen: set[str] = set()
    rows: list[dict] = []
    total = None
    for page in range(max_pages):
        try:
            payload = fetch(build_url(query, page=page, extra=extra))
        except RuntimeError as error:
            print(f"  ! {name} page={page} {error}", file=sys.stderr)
            break
        results = payload.get("results") or {}
        if total is None:
            total = results.get("total_num_results")
        batch = list(iter_results(payload))
        if not batch:
            break
        for patent in batch:
            number = patent.get("publication_number")
            if not number or number in seen:
                continue
            seen.add(number)
            patent["_axis"] = axis or name
            patent["_query_name"] = name
            patent["_query"] = query
            rows.append(patent)
        if page + 1 >= (results.get("total_num_pages") or 0):
            break
        time.sleep(SLEEP)

    path = out_dir / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  {name}: {len(rows)} 条落盘 (接口报总命中 {total})")
    return len(rows)


def main() -> int:
    """读 queries.json，逐条采集。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--only", default="", help="只跑名字包含该子串的 query")
    parser.add_argument("--force", action="store_true", help="已有结果也重抓")
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
            print(f"[{name}] 已有结果，跳过（--force 可重抓）")
            continue
        print(f"[{name}] {spec['q']}", flush=True)
        grand += harvest(
            name,
            spec["q"],
            spec.get("extra") or {},
            spec.get("max_pages") or args.max_pages,
            out_dir,
            axis=spec.get("axis") or "",
        )
        time.sleep(SLEEP)
    print(f"合计 {grand} 条（未跨 query 去重）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
