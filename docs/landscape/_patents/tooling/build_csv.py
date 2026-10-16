#!/usr/bin/env python3
"""把 raw/*.jsonl 合并去重成一张可排序的 CSV，并给一个粗排相关度。

用法:
    python3 docs/patents/build_csv.py --raw docs/patents/raw --out docs/patents/patents.csv

相关度只是**粗排线索**，不是结论：它数的是标题/摘要里出现了多少个我们关心的
主题词。真正要不要看权利要求，人来定。
"""
from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import pathlib
import re

# 每组里命中任意一个词算 1 分；分组是为了避免同义词堆叠虚高分数。
SIGNAL_GROUPS = {
    "llm": ("large language model", "language model", "llm", "generative model", "foundation model", "大模型", "大语言模型"),
    "evolution": ("evolutionary", "genetic algorithm", "mutation", "crossover", "population", "offspring", "fitness", "进化", "演化", "遗传"),
    "search": ("search", "candidate", "iterativ", "explore", "exploit", "select", "搜索", "候选"),
    "agent": ("agent", "autonomous", "multi-agent", "智能体", "自主"),
    "code": ("code", "program", "algorithm", "heuristic", "代码", "程序", "算法", "启发式"),
    "science": ("scientific", "hypothesis", "experiment", "laboratory", "research", "科研", "实验", "假设"),
    "optimization": ("optimization", "optimiz", "solver", "combinatorial", "scheduling", "优化", "求解"),
    "eval": ("evaluat", "verifier", "benchmark", "score", "reward", "feedback", "评测", "验证", "奖励"),
    "selfimprove": ("self-improv", "self-evolv", "recursive", "self-modif", "自进化", "自演化", "自改进"),
}

TAG_RE = re.compile(r"<[^>]+>")
KIND_RE = re.compile(r"[A-Z]\d?$")


def normalize(number: str) -> str:
    """把两个库的公开号归一化成同一个去重 key。

    Google Patents 给 `US20240273371A1`；PATENTSCOPE 给 `US20240273371`、
    WO 还会拼成 `WOWO/2025/093772`。去掉分隔符和末尾 kind code 后才能对上。
    """

    value = number.strip().upper().replace("/", "").replace("-", "").replace(" ", "")
    if value.startswith("WOWO"):
        value = value[2:]
    return KIND_RE.sub("", value)


def clean(text: str | None) -> str:
    """去掉接口返回里的 <b> 高亮和 &hellip; 实体。"""

    if not text:
        return ""
    return html.unescape(TAG_RE.sub("", text)).replace("…", "…").strip()


def score(text: str) -> tuple[int, str]:
    """按信号分组数命中数，返回 (分数, 命中的组名)。"""

    lowered = text.lower()
    hits = [name for name, words in SIGNAL_GROUPS.items() if any(word in lowered for word in words)]
    return len(hits), "|".join(hits)


def main() -> int:
    """合并、去重、打分、落 CSV。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, action="append",
                        help="原始 JSONL 目录，可重复传多个（两条采集链路各一个）")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    merged: dict[str, dict] = {}
    axes: dict[str, set[str]] = collections.defaultdict(set)
    queries: dict[str, set[str]] = collections.defaultdict(set)
    sources: dict[str, set[str]] = collections.defaultdict(set)

    for raw_dir in args.raw:
        for path in sorted(pathlib.Path(raw_dir).glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                number = row.get("publication_number")
                if not number:
                    continue
                key = normalize(number)
                if not key:
                    continue
                axes[key].add(row.get("_axis") or "")
                queries[key].add(row.get("_query_name") or path.stem)
                sources[key].add(row.get("_source") or "google_patents")
                existing = merged.get(key)
                if existing is None:
                    merged[key] = row
                else:
                    # 两个库的字段各有缺口：Google 有优先权日、PATENTSCOPE 标题更全。
                    # 合并时按"空的才补"，不覆盖已有值。
                    for field_name, value in row.items():
                        if value and not existing.get(field_name):
                            existing[field_name] = value

    rows = []
    for key, row in merged.items():
        title = clean(row.get("title"))
        snippet = clean(row.get("snippet"))
        relevance, tags = score(f"{title} {snippet}")
        rows.append(
            {
                "publication_number": row.get("publication_number", key),
                "norm_key": key,
                "country": key[:2],
                "title": title,
                "assignee": clean(row.get("assignee")),
                "inventor": clean(row.get("inventor")),
                "priority_date": row.get("priority_date") or "",
                "filing_date": row.get("filing_date") or "",
                "publication_date": row.get("publication_date") or "",
                "axes": "|".join(sorted(a for a in axes[key] if a)),
                "queries": "|".join(sorted(q for q in queries[key] if q)),
                "sources": "|".join(sorted(sources[key])),
                "signal_score": relevance,
                "signal_tags": tags,
                "url": f"https://patents.google.com/patent/{row.get('publication_number', key)}/en",
                "snippet": snippet,
            }
        )

    rows.sort(key=lambda item: (-item["signal_score"], item["publication_date"]))

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} 条去重后写入 {out}")
    by_country = collections.Counter(item["country"] for item in rows)
    print("按局：", dict(by_country.most_common(10)))
    by_axis = collections.Counter(axis for item in rows for axis in item["axes"].split("|") if axis)
    print("按轴：", dict(by_axis.most_common()))
    by_source = collections.Counter(item["sources"] for item in rows)
    print("按源：", dict(by_source.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
