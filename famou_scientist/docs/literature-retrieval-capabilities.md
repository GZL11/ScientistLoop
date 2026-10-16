# 论文检索能力汇总（Literature Retrieval Capability Map）

> 盘点 famou-scientist 当前与「论文检索」相关的全部能力：方法论 skill、可调用 tool、
> 后端检索脚本、缓存、Web 端文献处理。每条带**精确代码位置**（文件 + 行号，行号以盘点时为准，
> 改动后可能漂移，按符号名定位更稳）。
>
> 路径基准（LIVE 工作区根）：
> `baidu/acg-fm/famou-scientist/famou_scientist/`
> 下文相对路径均以此为根。

---

## 0. 总览：检索一篇论文会经过哪几层

```
研究助手（master agent）
   │  ① 方法论：load skill（怎么搜才全/才准）
   │       literature-search · systematic-review · baseline-profiling · citation-faithfulness
   │
   │  ② 检索 tool：arc_search_literature（真·多源 API）
   ▼
search.py  search_papers()
   │  并查 3 源 → 去重 → 按引用数排序
   ├── openalex_client.search_openalex()
   ├── semantic_scholar.search_semantic_scholar()
   └── arxiv_client.search_arxiv()
   │  （cache.py：7 天 / arXiv 24h 本地缓存，省重复 API）
   ▼
返回 [{title, authors, year, doi, arxiv_id, url, abstract}]
   │
   │  ③ 下游核验 tool（取全文摘要 / 验真伪 / 验支撑性）
   │       arc_fetch_source · arc_verify_citation · arc_verify_paper
   ▼
④ Web 端：按检索 query 聚类成小领域 + ★收藏资产 + 🔍深入解读
       collectLiterature → groupLiterature → LiteratureList / AssetsPanel
```

---

## 1. 方法论 Skill（指导“怎么搜”，agent 按需 load）

skill 目录根：`assets/opencode/skill/`
在 `assets/opencode/AGENTS.md` 的「技能库」与「Stage 流程」里登记/触发。

| Skill | 作用 | SKILL.md 位置 | 在 AGENTS.md 的登记/触发 |
|---|---|---|---|
| **literature-search** | 检索策略（PICO、同义词/布尔、≥3 库）、纳排标准、PRISMA、筛选、综合 | `skill/experiment/literature-search/SKILL.md` | 登记 `AGENTS.md:59`；Stage 4 实操 `AGENTS.md:118-121` |
| **systematic-review** | PRISMA 系统综述，**专讲全面性**：多库 / 宽窄查询都做 / 每子主题≥1 篇奠基作 / 近年高引优先 | `skill/experiment/systematic-review/SKILL.md` | 登记 `AGENTS.md:63`（⚠️ 见缺口 B：Stage 4 未强制 load） |
| **baseline-profiling** | baseline 必须从检索文献里抽（经典+SOTA），逐篇抽 benchmark/数据划分/超参/评估协议 | `skill/experiment/baseline-profiling/SKILL.md` | 登记 `AGENTS.md:60`；Stage 4⑤ `AGENTS.md:124` |
| **citation-faithfulness** | 不止查引用真伪，更查“这条引用是否真支撑论点”：抓被引摘要判 SUPPORTED/UNSUPPORTED/AMBIGUOUS | `skill/experiment/citation-faithfulness/SKILL.md` | 登记 `AGENTS.md:69`；Stage 23 核验 `AGENTS.md:183` |

> `literature-search` 上次新增了「按子方向分多次检索」最佳实践（搭配 web 端 query 聚类）。

---

## 2. 可调用 Tool（agent 真执行的检索/核验工具）

定义文件：`assets/opencode/tool/arc.ts`
工具在 AGENTS.md 的工具表 `AGENTS.md:31-37`、可用工具清单 `AGENTS.md:325`。

| Tool | 作用 | arc.ts 位置 | 入参 | 后端脚本 |
|---|---|---|---|---|
| **arc_search_literature** | 主检索：多源真实 API 拿论文列表 | `arc.ts:49` (`export const search_literature`) | `query, limit=15` | → `search.py` `search_papers()` |
| **arc_fetch_source** | 抓被引文献**摘要**做 claim 级审计（取全文摘要，正文常付费墙） | `arc.ts:438` (`export const fetch_source`) | `title, arxiv_id, doi` | → `source_text.py` `fetch_source()` (`:47`) |
| **arc_verify_citation** | 核验单条引用**真伪/存在性**（防编造引用） | `arc.ts:359` (`export const verify_citation`) | `title, arxiv_id, doi` | → `verify.py` `verify_by_arxiv_id/doi/openalex` (`:183/:358/:454`) |
| **arc_verify_paper** | 论文定稿前**批量**核验整篇 BibTeX（核验门 hook 强制拦假引用） | `arc.ts:403` (`export const verify_paper`) | `bib_text` | → `paper_verifier.py` `verify_paper()` (`:153`) |

> ⚠️ 改 `arc.ts` 需**重启 opencode**（port 4097）才生效；skill/AGENTS 的 .md 改动对**新会话**生效。

---

## 3. 后端检索脚本（真实 API 调用层）

脚本目录：`assets/opencode/scripts/`

### 3.1 检索聚合器 `search.py`（389 行）
| 符号 | 行号 | 说明 |
|---|---|---|
| `_DEFAULT_SOURCES` | `search.py:36` | `("openalex", "semantic_scholar", "arxiv")` 默认三源 |
| `search_papers()` | `search.py:104` | **单 query 多源并查 + 去重 + 按引用排序**（arc_search_literature 调的就是它） |
| `search_papers_multi_query()` | `search.py:233` | **多 query 跑、全局去重、按引用+年份排序**。⚠️ **死代码：没有任何 tool 暴露它**（见缺口 A） |
| `_deduplicate()` | `search.py:279` | 三级去重：DOI → arXiv ID → 模糊标题（`_normalise_title` `:272`） |
| `papers_to_bibtex()` | `search.py:386` | Paper → BibTeX |

### 3.2 三个数据源 client
| 源 | 文件 | 检索函数 | API endpoint |
|---|---|---|---|
| **OpenAlex** | `openalex_client.py` (356 行) | `search_openalex()` `:49` | `https://api.openalex.org/works` (`:35`) |
| **Semantic Scholar** | `semantic_scholar.py` (405 行) | `search_semantic_scholar()` `:148` | `https://api.semanticscholar.org/graph/v1/paper/search` (`:34`)，限速 1 req/s、重试 3 次 |
| **arXiv** | `arxiv_client.py` (490 行) | `search_arxiv()` `:141` | `export.arxiv.org/api/query` Atom API，每次最多 100 篇 |

### 3.3 核验/取源脚本
| 文件 | 关键函数 | 说明 |
|---|---|---|
| `source_text.py` | `fetch_source()` `:47` | 按 title/arxiv_id/doi 在三源检索，返回最佳匹配的摘要 |
| `verify.py` | `verify_by_arxiv_id/doi/openalex/title_search` `:183/:358/:454/:577` | 多渠道核验引用存在性（arXiv/CrossRef/DataCite/OpenAlex） |
| `paper_verifier.py` | `verify_paper()` `:153`, `verify_paper_file()` `:287` | 整篇论文级核验（未报告数字/编造条件检测） |

### 3.4 缓存 `cache.py`
| 符号 | 行号 | 说明 |
|---|---|---|
| 缓存目录 | `cache.py:19` | `.researchclaw_cache/literature/` |
| 默认 TTL | `cache.py:20` | 7 天（S2 / OpenAlex） |
| 分源 TTL | `cache.py:24` | arXiv 24h（每日午夜更新） |
| `cache_key()` / `get_cached()` | `cache.py:38/:44` | 查询级缓存键 + 命中/过期判定 |

---

## 4. Web 端文献处理（展示 + 收藏 + 解读）

文件：`assets/web/src/app.tsx`

| 能力 | 函数 | 位置 |
|---|---|---|
| 从会话聚合检索结果（带 `_query` 来源标签） | `collectLiterature()` | `app.tsx:1106` |
| 按检索 query 聚类成小领域（类内年份倒序） | `groupLiterature()` | `app.tsx:1266` |
| 检索词中文化术语表 | `LIT_GLOSSARY` / `translateLitLabel()` | `app.tsx`（LIT_HUES 附近） |
| 右栏「文献」Tab 渲染 | `LiteratureList()` | `app.tsx:1356` |
| 左栏「⭐ 资产」收藏库（全局 localStorage） | `AssetsPanel()` | `app.tsx:1384` |
| 「🔍 深入解读」prompt 拼装（发后端完整，气泡显示精简） | `deepDivePrompt()` / `deepDiveDisplay()` | `app.tsx:335` 附近 |

后端检索工具的对应说明在 `assets/opencode/AGENTS.md` 的 Stage 4「文献综述」`AGENTS.md:117-124`。

---

## 5. 已知缺口（全面性可补强处）

- **缺口 A — multi-query 引擎未接线**：`search.py:233` 的 `search_papers_multi_query()`（多 query + 全局去重）
  写好了但**无 tool 暴露**。接上后，全面检索可从“靠提示词自觉”升级为“工具层一次并查多 query”。
- **缺口 B — systematic-review 未在检索阶段强制 load**：Stage 4 (`AGENTS.md:118`) 只 load `literature-search`，
  `systematic-review` 的 8 条全面性纪律（宽窄查询、子主题奠基作、近年高引）未被强制触发。

> 建议（待定，未实施）：A 接 multi-query 工具 + B 在 Stage 4 同时 load systematic-review。
> 改 arc.ts 需重启 opencode，动手前先确认。
