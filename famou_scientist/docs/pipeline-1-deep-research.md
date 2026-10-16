# 阶段一 · 论文调研（Deep Research）技术文档

> famou-scientist 四阶段技术文档之一。本篇讲**文献检索 / 深度调研**：从研究问题到一份带
> 真实文献、baseline 配置表、研究空白的 `planning/literature.md`。

---

## 0. 一句话定位

研究助手（master agent）按 AGENTS.md 的 Stage 3-6 主导调研，**每步先 load 方法论 skill，再调真执行 tool**：
skill 决定「怎么搜才全/才准」，tool（`arc_search_literature` 等）真去 OpenAlex / Semantic Scholar / arXiv
拉真实论文，后端脚本做多源并查 + 去重 + 缓存。最终产出 `planning/literature.md`。

```
master agent
  │ ① load skill：literature-search / systematic-review / baseline-profiling
  │                / benchmark-selection / citation-faithfulness / scientific-critical-thinking
  │ ② 调 tool：arc_search_literature（多源真 API）
  ▼
search.py  search_papers()
  ├── openalex_client.search_openalex()
  ├── semantic_scholar.search_semantic_scholar()
  └── arxiv_client.search_arxiv()
  │  去重(_deduplicate) → 按引用/年份排序 →（cache.py 本地缓存）
  ▼
[{title, authors, year, doi, arxiv_id, url, abstract, citation_count, ...}]
  │ ③ 下游核验：arc_fetch_source（取摘要）/ arc_verify_citation（验真伪）
  ▼
④ web 端按检索 query 聚类成小领域 + ★收藏 + 🔍深入解读
```

---

## 1. 在 AGENTS.md 里的流程位置

文件：`assets/opencode/AGENTS.md`，Stage 3-6（约 117-128 行）。四个子步骤**都要做、别跳**：

| 子步骤 | Stage | 做什么 | 关键约束 |
|---|---|---|---|
| ① 定检索策略 | 3 | 列关键词/数据库/时间范围/纳入排除标准 | **读 `planning/venue` 锚定调研重心**：主攻该领域顶会顶刊，优先近 2-3 年高引 + 每子方向≥1 篇奠基作 |
| ② 搜 | 4 | 调 `arc_search_literature` 拿真实论文 | **必须按子方向分多次检索**（一个子方向一次 query，英文写），右栏正是按 query 聚类成小领域 |
| ③ 筛选 | 5 | 按相关性/质量/是否核心工作筛 | 淘汰的简述理由；用 `scientific-critical-thinking` 的 GRADE/证据分级判可信度 |
| ④ 抽取 | 6 | 抽关键方法/发现/数据/局限 | + **profile baseline**：逐篇抽 benchmark/数据划分/超参/评估协议 |

产出：`planning/literature.md`（含 baseline 配置表）→ 展示摘要 + 提炼研究空白 → 问用户"最关注哪个方向"。

> **venue 是贯穿全程的"目标函数"**：开场就问（和 A/B/C 节奏一起，走 `question` 工具），写入 `planning/venue`。
> 它决定调研重心——投哪个领域就主攻那个领域的顶级标准，不把跨领域/不入流论文当主线。

---

## 2. 方法论 Skill（指导"怎么搜"）

agent 按需 load；写关键产物前没 load 会被 **skill 加载门** hook 警告。

### 2.1 literature-search — 检索主方法论
`skill/experiment/literature-search/SKILL.md`（applicable-stages: 3,4,5,6；改编自 K-Dense-AI/claude-scientific-skills，通用模板未针对本代码库定制）
- **检索策略**：PICO 框架 → 核心概念 → 同义词/缩写扩展 → 布尔逻辑 → ≥3 库选择（**⚠️ 这里列的是生物医学/CS/跨学科通用的库名单**如 PubMed/Scopus/DBLP，但 ARC 真正能调的 `arc_search_literature` 只有 OpenAlex+Semantic Scholar+arXiv 三源，其余库没有接入代码——skill 文本本身没跟着改，见 §7 缺口 C）
- **关键纪律**：**按子方向分多次检索**（搭配 web 端 query 聚类），而非单次宽泛查询
- **纳入/排除**：时间范围、语言、出版类型、研究设计、领域过滤
- **PRISMA 流程**：去重前计数 → 去重 → 标题/摘要筛 → 全文审 → 流程图
- **质量评估**：按研究类型选工具（RCT 用 Cochrane RoB，观察性研究用 Newcastle-Ottawa，ML 论文查复现性/数据有效性/统计严谨性）
- **综合**：叙述综合 vs meta 分析 vs gap 分析、冲突识别、**研究空白陈述**

### 2.2 systematic-review — 系统综述，专讲全面性
`skill/experiment/systematic-review/SKILL.md`（applicable-stages: 3,4,5,6；引用 PRISMA 2020 正式指南 Page et al., BMJ 2021）
- 8 条精简清单，PRISMA 包含/排除前置定义；**多库**（**这里点名的是 ARC 实际有的三源**：Semantic Scholar + arXiv + OpenAlex，比 2.1 的通用学科清单更贴合本代码库真实能力）；**宽窄查询都做**
- 标题/摘要 → 全文两级筛；抽取方法/数据集/指标/关键发现
- **每子题至少一篇奠基作 + 近年高引优先**
- 跟 2.1 的关系：内容大量重叠（同讲 PRISMA/多库/两级筛选），本 skill 更像是"全面性"这一件事的加强检查表，不是独立方法论——真正补充的是"奠基作"和"宽查询也要做"这两条 literature-search 没显式写的纪律
- ⚠️ 见缺口 B：Stage 4 当前只强制 load `literature-search`，未强制 load 本 skill（但"奠基作"这条 AGENTS.md Stage 3 自己文字里也兜了一句，实际漏掉的主要是"宽查询"这一条）

### 2.3 baseline-profiling — baseline 必须从文献抽，不是拍脑袋列
`skill/experiment/baseline-profiling/SKILL.md`（applicable-stages: 5,6,9）
- **定位边界**：综述方法论走 `literature-search`；本 skill 管"先选定要对比哪些 baseline，再逐篇精读它们的实验配置"；自己的实验设计走 `experimental-design`——三者接力：选+profile baseline → 对齐设计 → 跑
- **第 0 步选 baseline（从检索到的文献汇总，别凭空想）**：翻近期 SOTA 论文自己在跟谁比、汇总出现频次 → 两类都要覆盖：**经典/奠基方法**（哪怕不是最强，是"地基线"）+ **最新 SOTA**（近 1-2 年最强的几个）；可选再加一个 **simple-but-strong** 对照；数量至少满足 `research-decision` 的 ≥2 baseline 门槛
- **强制抽取表**（逐篇，翻 Implementation Details/附录/代码仓库，不能只读摘要）：benchmark/数据集（含版本/子集）· 数据划分协议（train/val/test、CV、seed）· 数据处理（预处理/增强/清洗）· 模型规模 · 训练配置（optimizer/lr/warmup/batch/epoch/weight decay/loss）· 评估协议（指标精确定义、报告方式）· 报告的关键数字 · 算力/硬件（可选）
- **复现风险标注**（最有价值的一步）：显式列论文没报告的项 → 判断能否从开源代码补全/合理默认 → 缺失太多标记「弱可比」，对比时明确声明差异
- **对齐规则**：选定后实验必须同 benchmark + 同数据划分 + 同评估协议；不能对齐的维度要在论文里声明差异，不要隐瞒；不同 baseline 用了不同 benchmark 不能直接放同一张表比

### 2.4 benchmark-selection — 选哪个 benchmark + 数据怎么来
`skill/experiment/benchmark-selection/SKILL.md`（applicable-stages: 9,11；上游接 baseline-profiling 的结果）
- **第 0 步（必做）baseline×benchmark 覆盖矩阵**：行=baseline、列=benchmark、格=报告数字，一次解决三件事——哪些 benchmark 领域共用（列 N 大）、你必须在哪些上有数才能同台对比、哪些格已有现成数字可直接复用
- **选几个 benchmark：数量跟随 baseline 惯例，不凭空定**：读矩阵"每行用了几个"——baseline 普遍用 2-3 个你也用 2-3 个，普遍只用 1 个标准 benchmark 你用 1 个也可以；常见错误是选得比惯例还少（只挑一个交差）
- **每个 benchmark 按两点取舍**：覆盖度（被多少候选 baseline 使用）+ 任务贴近度，优先"多个 baseline 共用 + 与任务贴近"
- **省力关键点**：benchmark 上若 baseline 已有公开报告结果且评估协议一致 → 直接引用（"as reported in [cite]"），不必自己复现该 baseline，只跑自己的方法即可；协议不一致才需要对齐重跑
- **数据获取（关键停顿点，必须问用户）**：下载到哪（默认 `experiment/data/`）/ 有没有自己的数据集（给路径） / 有没有推荐的数据集（给名字自行检索）——下载走 `ALL_PROXY` 代理，凭证只走环境变量不落盘

### 2.5 citation-faithfulness — 不止真伪，更查"是否真支撑论点"
`skill/experiment/citation-faithfulness/SKILL.md`（applicable-stages 官方标的是 **18,23**——同行评审与引用核验阶段，调研期只是提前热身/预习，不是这个 skill 的正式接入点）
- 两层：①存在性（`arc_verify_citation`/`arc_verify_paper`）②**支撑性/faithfulness（本 skill）**——一篇引用真实存在，但根本没下过你拿它支撑的那个结论，是最容易漏查的误引模式
- **抽查不必全量**：优先查"承重引用"——支撑核心论点/动机/对比基线的、带具体数字或定量断言的、出现在摘要/引言贡献句/结论里的；纯"相关工作综述"式装饰性引用可略过
- 抓摘要：`arc_fetch_source(title, arxiv_id, doi)`；`abstract_available=false` 时判 AMBIGUOUS，别硬判
- 三态判定（只凭摘要，不脑补）：✅ SUPPORTED（方向/对象/量级都对）· ❌ UNSUPPORTED（不支持/矛盾/讲别的，尤其抓定量断言对不上号）· 🟡 AMBIGUOUS（相关但不足判定）
- 局限：只有摘要（正文常付费墙）→ **advisory 级，不设硬 block**——UNSUPPORTED 是要你主动改的警示，不是强制拦截

### 2.6 scientific-critical-thinking — 证据质量与批判性思维（七大能力）
`skill/experiment/scientific-critical-thinking/SKILL.md`（applicable-stages: 5,18,20；改编自 K-Dense-AI/scientific-agent-skills）
- **方法学批判**：研究设计是否匹配问题、内部/外部/构念/统计结论效度、对照与盲法是否到位
- **偏倚检测**：认知偏倚（确认偏倚/HARKing/发表偏倚/摘樱桃）· 选样偏倚（抽样/志愿者/失访/幸存者）· 测量偏倚（观察者/回忆/社会期许/工具）· 分析偏倚（p-hacking/结果置换/选择性报告/亚组挖掘）· 混淆变量
- **统计评估**：样本量与检验力、统计检验适配性、多重比较校正、p 值正确解读、效应量与置信区间、缺失数据处理、回归/建模常见陷阱
- **证据质量分级（GRADE）**：起点按研究设计类型（RCT 高/观察性低）→ 降级（偏倚/不一致/间接/不精确/发表偏倚）→ 升级（大效应/剂量反应/混淆会削弱而非增强效应）；外加证据汇聚判断（多独立复现/不同方法趋同 → 更强）
- **逻辑谬误识别**：因果类（事后归因/相关当因果）· 概括类（草率概括/摘樱桃）· 权威类（诉诸权威/人身攻击）· 统计类（基础率忽视/德州快枪手）· 结构类（假二元/循环论证）· 科学特有（伽利略赌注/不可证伪性）
- **研究设计指导**：帮你自己设计新研究时用——问题精化、设计选型、偏倚最小化策略、样本规划（含功效分析）、测量策略、分析预注册、透明度与报告规范
- **论点评估**：识别论点强度（proven/likely/suggested）→ 评估证据是否匹配这个强度 → 检查逻辑连接有无跳跃 → 红旗清单（相关性数据却用因果语言、"证明"式绝对断言、摘樱桃引用、忽略矛盾证据）
- **famou 接入点**：Stage 5-6 文献筛选时判可信度、淘汰低质工作（直接影响"研究空白识别"准不准）；Stage 18 同行评审时系统找方法学缺陷/偏倚（配 `peer-review`、`failure-mode-audit` Mode 1/4/6）；Stage 20 质量门定稿前证据强度自评（配 `quality-gate`）

### 2.7 meta-analysis（按需）
`skill/experiment/meta-analysis/SKILL.md`（applicable-stages: 7,14）：报告效应量而非仅 p 值、跨研究用标准化指标、account for 异质性（不同设置/数据集/种子）、置信区间随点估计一起报、森林图可视化跨研究对比、识别并讨论异常值、解读汇总结果时考虑发表偏倚。

---

## 3. 真执行 Tool

定义文件：`assets/opencode/tool/arc.ts`（约 880 行——比早期盘点时的 ~629 行多出的部分主要是
百度网页搜索 `arc_web_search`、示意图生成 `arc_generate_schematic` 等不属于本阶段的能力，
挤进了同一个文件；本节只关心跟文献调研相关的四个 tool）。

### 3.1 arc_search_literature — 主检索（arc.ts L70-112）
- 入参：`query: string`、`limit: number`（默认 15）
- 调后端 `search.py` 的 `search_papers(query, limit)`，多源真 API
- 返回按 `citation_count` 降序的论文列表：`{title, authors[], year, doi, arxiv_id, url, abstract}`
- **⚠️ 上下文截断（arc.ts L86-108，2026-06 加）**：交回模型前在 Python 片段里瘦身——
  `abstract` 只回前 **280 字**（`_trunc`）、`authors` 截前 **4 个 + "et al."**、输出去掉 `indent`（compact JSON）。
  目的：单次返回从 ~49K 字符压到 ~9K（降 ~80%），防止多次检索把上下文吹爆（见 §8）。
  承重文献要全文摘要时，用 `arc_fetch_source` 按需取（§3.2）——不常驻上下文。
  - 历史教训：曾因 `abstract` 全量 + 5 作者 + `indent=2`，6+ 次检索堆出 ~25 万字符，
    叠加自定义 provider 未配 `limit.context` 致 auto-compact 不触发，最终上下文撑爆、模型逐轮吐空。

### 3.2 arc_fetch_source — 抓被引文献摘要（arc.ts L470-497）
- 入参：`title` / `arxiv_id` / `doi`（至少一项）
- 调 `source_text.py` 的 `fetch_source()`：通过 `search_papers()` 检索最佳匹配
- 匹配优先级：arxiv_id / DOI 精确（score=1.0）→ 标题 Jaccard 重叠；阈值 ≥0.5 才算 found
- 返回：`{found, title, abstract, abstract_available, year, venue, doi, arxiv_id, source, match_similarity}`

### 3.3 arc_verify_citation — 单条引用真伪（arc.ts L391-431）
- 入参：`title` / `arxiv_id` / `doi`
- 三层核验（`verify.py`）：arXiv ID 直查 → CrossRef DOI → OpenAlex 标题搜索
- 返回 verified 状态 + matched_title + source

> `arc_verify_paper`（批量整篇 BibTeX，arc.ts L435-466）主要在写论文阶段定稿核验时用，见
> [写论文文档](pipeline-4-paper-writing.md)。

> ⚠️ 改 `arc.ts` 需**重启 opencode 后端进程**才生效（端口因实例而异，`ps aux | grep "opencode serve"`
> 查当前用的是哪个）；skill/AGENTS 的 `.md` 改动对**新会话**生效，不用重启进程。

---

## 4. 后端检索脚本

脚本目录：`assets/opencode/scripts/`。

### 4.1 search.py — 检索聚合器（约 389 行）
| 符号 | 行号 | 说明 |
|---|---|---|
| `_DEFAULT_SOURCES` | L36 | `("openalex","semantic_scholar","arxiv")` |
| `search_papers(query, limit, sources, year_min, deduplicate, s2_api_key)` | L104-230 | **单 query 多源并查 + 去重 + 排序**（arc_search_literature 调它）。源顺序 OpenAlex→S2→arXiv；OpenAlex 后 0.5s、S2 后 1.0s 间隔；API 失败降级读缓存（L188-210）；末尾 `_deduplicate` + 按 `(citation_count, year)` 降序 |
| `search_papers_multi_query(queries, limit_per_query, ...)` | L233-264 | **多 query 跑 + 全局去重 + 排序**。⚠️ **死代码：无 tool 暴露**（见缺口 A） |
| `_deduplicate(papers)` | L279-383 | 三级去重：DOI → arXiv ID → 模糊标题（`_normalise_title` L272-276）；冲突时高引用胜，`_enrich()` 回填缺失字段 |
| `papers_to_bibtex(papers)` | L386-389 | Paper → BibTeX |

### 4.2 三个数据源 client
| 源 | 文件 | 检索函数 | endpoint / 限速 |
|---|---|---|---|
| OpenAlex | `openalex_client.py`（~356 行） | `search_openalex()` L49-119 | `https://api.openalex.org/works`（L35）；polite email；单请求 ≤50；重试 3 次；内部 200ms 间隔；全局锁串行化并发 |
| Semantic Scholar | `semantic_scholar.py`（~405 行） | `search_semantic_scholar()` L148 | `.../graph/v1/paper/search`（L34）；free 1 req/s（内部 1.5s 保守）；**三态熔断器**（CLOSED/OPEN/HALF_OPEN，连续 3 个 429 跳闸，冷却 120s→600s） |
| arXiv | `arxiv_client.py`（~490 行） | `search_arxiv()` L141 | `export.arxiv.org/api/query` Atom；1/3s；优先用 arxiv pip 库否则 stdlib XML；同款熔断器（冷却 180s→600s） |

### 4.3 核验/取源脚本
| 文件 | 关键函数 | 说明 |
|---|---|---|
| `source_text.py` | `fetch_source()` L47-102；`_title_overlap()` L38-44 | 三源检索取最佳匹配摘要；Jaccard 词重叠 |
| `verify.py` | `verify_by_arxiv_id/doi/openalex/title_search` L183/L358/L454/L577 | 多渠道核验存在性；`VerifyStatus`（L43-49）：相似度 ≥0.80=VERIFIED、0.50-0.80=SUSPICIOUS、<0.50=HALLUCINATED、无法验=SKIPPED；验证结果缓存 365 天 |

### 4.4 cache.py — 缓存
| 项 | 行号 | 值 |
|---|---|---|
| 缓存目录 | L19 | `.researchclaw_cache/literature/` |
| 默认 TTL | L20 | 7 天 |
| 分源 TTL | L24-28 | arXiv 24h · S2 3 天 · OpenAlex 3 天 · citation_verify 365 天 |
| `cache_key()` / `get_cached()` / `put_cache()` | L38 / L44-84 / L98-119 | 查询级缓存键（SHA256）+ 命中/过期判定 |

---

## 5. Web 端文献处理

文件：`assets/web/src/app.tsx`。聚类锚点 = 产生该文献的 `arc_search_literature` 检索 query。

| 能力 | 函数 | 位置 |
|---|---|---|
| 聚合会话检索结果（附 `_query` 来源标签） | `collectLiterature()` | app.tsx:1808 |
| 按检索 query 聚类成小领域（类内年份倒序） | `groupLiterature()` | app.tsx:1968 |
| 检索词中文化术语表 | `LIT_GLOSSARY` / `translateLitLabel()` | app.tsx:1862 / 1958 |
| 右栏「文献」Tab | `LiteratureList()` | app.tsx:2056 |
| 「🔍 深入解读」prompt 拼装 | `deepDivePrompt()` / `deepDiveDisplay()` | app.tsx:527 / 551 |

> ⚠️ **收藏功能已经重构过，不再是独立的 `AssetsPanel()` 面板**（旧版文档写的那个符号名已经不存在）。
> 现状：收藏状态 `starredKeys`/`starred` 挪到了 `App()` 组件顶层用 localStorage 管理（app.tsx:3601 附近），
> 作为 props 逐层传给 `LiteratureList`/`KbDocsAndPapers`/`ResearchPanel` 等好几个组件，星标按钮渲染在
> **「知识库」全屏覆盖层**（`KnowledgeBaseBody`）和右栏「文献」Tab 里，不再是一个独立的左栏面板。
>
> 另外要注意：**现在 UI 上"资产"这个词已经指向一个完全不同的功能**——浏览"哪些历史对话产出过
> workspace 产物"（`WorkspaceAssetsEntry`/`WorkspaceAssetsBody`，app.tsx:2536 起），跟本节讲的
> 文献收藏没有关系，别搞混。

> 聚类细不细取决于 agent 是否分子方向多次检索——已在 AGENTS.md（Stage 4）和
> `literature-search/SKILL.md` 加了「按子方向分多次检索」引导。

---

## 6. 一次完整调研的数据流

```
用户研究问题
  → agent load literature-search（+ systematic-review 全面性纪律）
  → 拆子方向，每个子方向一次 arc_search_literature(query)
      arc.ts:search_literature → search.py:search_papers
        → openalex / semantic_scholar / arxiv 并查（限速 + 熔断 + 缓存降级）
        → _deduplicate（DOI→arXiv→模糊标题）→ 按引用/年份排序
      返回真实论文列表 → web 端按 query 聚类
  → load scientific-critical-thinking：GRADE/证据分级筛选，淘汰低质（Stage 5）
  → 抽取关键方法/发现/局限（Stage 6）
  → load baseline-profiling：逐篇抽 baseline 配置表
  → load benchmark-selection：覆盖矩阵选 benchmark
  →（承重引用）arc_fetch_source 抓摘要 + citation-faithfulness 判 SUPPORTED/UNSUPPORTED
  → 写 planning/literature.md（综述 + baseline 配置表 + 研究空白）→ 展示 + 问用户关注方向
```

---

## 7. 已知缺口（全面性可补强处）

- **缺口 A — multi-query 引擎未接线**：`search.py:233` 的 `search_papers_multi_query()`（多 query + 全局去重）
  写好了但**无 tool 暴露**。接上后，全面检索可从"靠提示词自觉"升级为"工具层一次并查多 query"。
- **缺口 B — systematic-review 未在检索阶段强制 load**：Stage 4 只 load `literature-search`，
  `systematic-review` 的全面性纪律（宽窄查询、子主题奠基作、近年高引）未被强制触发。
- **缺口 C — literature-search 的数据库清单跟 ARC 实际能力脱节**：`literature-search/SKILL.md` §Search
  Strategy Design 按学科列了 PubMed/Scopus/Web of Science/DBLP/ACL Anthology/Google Scholar，但
  `arc_search_literature` 底层 `search.py` 只真接了 OpenAlex + Semantic Scholar + arXiv 三源——
  PubMed/DBLP/ACL Anthology 只能靠 OpenAlex 自身聚合**间接**捞到一部分，Scopus/Web of Science/
  Google Scholar **完全没有覆盖路径**（前两个是订阅库无免费 API，后者没有官方 API、爬取违反 ToS，
  基本可判定为"做不了"而不是"还没做"）。agent 读到这段清单容易误以为自己能按学科切数据库，
  实际手里永远只有那三源。建议给这段清单加一句"实际可用数据源见 §3.1"之类的纠偏说明。

> 改 arc.ts 需重启 opencode，动手前先确认。

---

## 8. 上下文预算与工具截断（避免检索把上下文吹爆）

文献检索是**最容易撑爆上下文**的环节：每次 `arc_search_literature` 的返回会原样进入对话上下文，
并在之后**每一轮**随历史重发。一次宽查询（15 篇 × 全量摘要）就可能塞进数万字符，几次累积即逼近模型上限。

### 8.1 两道防线（互补，缺一不可）
| 防线 | 在哪 | 作用 |
|---|---|---|
| ① 工具输出截断 | `arc.ts` `search_literature`（L86-108）+ `headTail()`（L60） | **从源头少灌**：摘要 280 字、作者 4+et al.、compact JSON；实验 stdout 走 head+tail |
| ② 模型 `limit.context` + auto-compact | opencode 配置 `provider.*.models.<id>.limit` | **撑大后兜底**：到 `context×~0.9` 自动 summarize 压缩历史 |

- 截断让上下文**涨得慢**、每轮重发的 token 少（更省钱更快）；compact 是**真到上限时**的安全阀。
- ⚠️ **自定义 provider（如 `anthropic-gateway`）必须在配置里显式写 `limit.context`**：
  它在 models.dev 里匹配不到，缺 `limit` 则 opencode 视上限为 0 → auto-compact 永不触发 → 裸奔到撞墙。

### 8.2 承重摘要按需取，不常驻
判相关性/选篇只需短摘要（280 字够）；真要逐句核对支撑性时，对**承重引用**单独调
`arc_fetch_source`（§3.2）取全文摘要。这样全文摘要只在需要的瞬间进上下文，用完即走，不长期占用。

### 8.3 实践提示
- 分子方向多次窄查询（本就推荐，§2.1）比一次超宽查询更省上下文，且聚类更细（§5）。
- 长会话里若发现回复变短/变空，优先怀疑上下文接近上限——查模型 `limit` 是否配置、是否触发过 compact。
