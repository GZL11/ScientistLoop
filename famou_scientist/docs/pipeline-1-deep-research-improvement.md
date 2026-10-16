# 改善 Deep Research（文献调研）效果的方案

> 本篇是 `pipeline-1-deep-research.md`（讲现状）的姊妹篇，讲**改进方案**。
> 聚焦"效果"，不谈前后端实现拆分。按 arc 现有 DR 流程（AGENTS.md Stage 3-6 + skill）
> 逐环节说明：**现状薄弱点 → 可借鉴的 SOTA 技术（附论文/项目） → 预期效果**。

---

## 0. Context（为什么做）

入口 bad case：搜 `IntenAgent1.5`（实为 `InternAgent1.5`）返回一堆同名 `xxx1.5`（SeedPro 1.5 / Longcat 1.5）、搜不到对的那篇、不反问z用户是否打错、还列了一堆不知相不相关的文献。

深挖后发现这不是单点 bug，而是 arc 的 DR 在**六个能力维度上系统性偏弱**：query 理解、迭代检索、噪声过滤、结构化综合、跨学科洞察、检索源广度。当前 DR 本质是"一次性宽查询 → 按引用数排序 → 平铺列表 → 靠 LLM 自觉筛"，缺乏现代 deep-research agent 的核心机制。

一个来自信息检索(IR)领域的**通用背景**（非 arc 实测，用于论证"去噪值得做"）：据 AFR-Rank（*Information Processing & Management*, 2025）motivation 部分转述的测量，**通用一阶段检索器**（BM25 / 稠密检索等）返回的 top-100 中，在 TREC DL 基准上平均 **>60% 不相关**；在更专门的语料（Signal、SciFact 等特定数据集）上 **>90% 不相关**（[AFR-Rank](https://www.sciencedirect.com/science/article/abs/pii/S0306457325001736)）。

⚠️ 边界与出处：① 这是对**一阶段检索器在特定 IR 基准上**的刻画，**不等于** arc 三源检索的噪声率——arc 自己的真实噪声率**尚未实测**（见文末评测节，需用 DBLP/LitSearch/bad-case 回归建立）；SciFact 是科学事实核查数据集，不代表"所有科学检索"。② 上述数字为本 session 经 WebSearch 获取的**二手转述**（环境限制未能抓取原文表格），精确值请引用前再核 AFR-Rank 原文。

结论仍成立但需限定：**去噪/重排是现代检索的通用刚需**，对以相关性为目标的 DR 尤其重要；而"扩大检索源"若不先解决过滤，只会放大噪声。

### 根因（读源码确认，见 pipeline-1-deep-research.md 对应行号）
1. **最后按 `citation_count` 硬重排**（`search.py:228`）——各源按 relevance 排好的结果被引用数覆盖，新论文（引用≈0）被系统性压到看不见。这是"搜到一堆 1.5、就是看不到对的那篇"的直接原因。
2. **全链路没有相关性/置信度信号**——`search_papers` 只吐论文列表，上层 agent 无从判断"到底搜没搜到"，自然不反问。
3. **全链路没有任何学科/类别字段**——`Paper`（`models.py` L40-51）只有书目基础字段；OpenAlex 明明返回 `concepts`/`topics`/`relevance_score`，但 `openalex_client.py` 的 `select=`（L95-99）根本没请求，解析时全丢；S2 没请求 `s2FieldsOfStudy`；arXiv 的 `primary_category` 被折进 `venue` 扔掉。
4. **文献栏是纯 query 分组平铺列表**（`app.tsx` `groupLiterature` L1968），颜色（`LIT_HUES` L1859）只按分组序号循环、无任何语义。

---

## 现状实录 · arc 当前的检索 / 聚类 / 排序方法

> 按数据流顺序列出当前每一步**实际在做什么**（附 file:line），供评估。均以核过的源码为准，非推测。

### 1. 检索输入与 query 处理
- 工具 `arc_search_literature`（`arc.ts` `search_literature` L70-112）入参 `query: string` + `limit`（默认 **15**）。
- **query 原样透传**给后端 `search_papers`，无拼写纠错、无实体识别、无 query 分解/改写、无同义词扩展。
- "分子方向多次检索"只靠 AGENTS.md/skill 提示词引导 agent 自觉，**工具层不强制**。

### 2. 多源并查（`search.py` `search_papers` L104-230）
- 固定三源、**顺序串行**：OpenAlex → （sleep 0.5s）→ Semantic Scholar → （sleep 1.0s）→ arXiv。
- 每源各自 `limit`（默认 20；arc 调用时传 15）。
- 任一源抛错 → 降级读本地缓存（L188-210），无缓存则跳过该源。
- 死代码：`search_papers_multi_query`（L233，多 query + 全局去重）**无工具暴露**。

### 3. 每源各自的排序（进入合并前）
- **OpenAlex**：`search=` 全文相关性序（`openalex_client.py` L92）。
- **Semantic Scholar**：请求参数只有 `query/limit/fields/year`，**无 sort** → API 默认相关性序（`semantic_scholar.py` L185-188）。
- **arXiv**：`sort_by="relevance"`（`arxiv_client.py` L145）。
- → 三源**都按相关性返回**，但这个相关性序在第 5 步被覆盖。

### 4. 去重（`_deduplicate` L279-383）
- 三级优先：**DOI → arXiv ID → 模糊标题**。
- 模糊标题 = `_normalise_title`（L272-276）：仅小写 + 去标点 + 压空格后**做完全相等匹配**（不是编辑距离/相似度，差一个字母即视为两篇）。
- 冲突时**高引用者胜**，`_enrich` 回填缺失字段（arxiv_id/doi/url/更长摘要）。

### 5. 全局排序 ★（`search.py` L228）
```python
all_papers.sort(key=lambda p: (p.citation_count, p.year), reverse=True)
```
- **只按引用数、再按年份，降序**。第 3 步各源的相关性序在此被完全丢弃。
- 无 query→结果相关性评分，无相关性地板过滤，无置信度信号。

### 6. 回给模型的整形（`arc.ts` L86-107）
- 每篇只吐：`title` / `authors`（前 4 + "et al."）/ `year` / `doi` / `arxiv_id` / `url` / `abstract`（截前 280 字）。
- **丢弃**：`citation_count`、`venue`、`source`、`paper_id`——即排序依据的引用数本身都不回给模型。

### 7. web 端聚类（`app.tsx`）
- `collectLiterature`（L1808）：扫全会话，按 `doi||title` 去重，给每篇打一个 `_query`（产生它的检索词）标签。
- `groupLiterature`（L1968）：**唯一聚类轴 = `_query`**，组内按年份倒序。无跨文献关系、无主题/学科聚类、无图结构。
- 检索词经 `LIT_GLOSSARY`/`translateLitLabel`（L1862/1958）做英→中显示翻译（硬编码术语表，偏 BCI/EEG/ML）。

### 8. web 端上色（`app.tsx` L1859/L2022）
- `LIT_HUES` 10 色调色板，`hue = LIT_HUES[idx % 10]`——**按分组在列表里的序号循环取色**，与主题/学科/相关性**无任何关联**（换个检索顺序同一主题就换色）。

### 9. 缓存（`cache.py`）
- 查询级缓存（SHA256 键）；分源 TTL：arXiv 24h / S2 3 天 / OpenAlex 3 天 / 引用核验 365 天。

---

## 能力 1 · Query 理解与 known-item 消歧（修 bad case 的根）

**现状**：`arc_search_literature` 把 query 原样丢给三源全文检索，无实体识别、无拼写纠错、无消歧、无置信度信号。用户点名要某个特定系统（known-item）时，被同名噪声淹没且无反问。

**可借鉴技术**：
- **实体链接 + 名称消歧**：候选生成 → 消歧排序的经典管线；[Scholar Name Disambiguation with Search-enhanced LLM](https://arxiv.org/abs/2411.17102) 证明"搜索引擎（查询改写/意图识别）+ LLM"做消歧很有效。对应到 arc：先判定 query 里是否含"命名实体"（模型名/方法名/系统名），用它做**精确/受限匹配**而非全文宽查询。
- **Query 分解**：[FAIR-RAG](https://arxiv.org/html/2510.22344v1) 把复杂 query 语义分解成 ≤4 个关键词化、语义独立的子查询；DMQR-RAG 做多粒度改写保覆盖。对应 arc Stage 3 "定检索策略"——从"靠提示词自觉分子方向"升级为工具/流程强制分解。
- **known-item 校验 + did-you-mean**：命名目标若不在结果里 → 给低置信度信号 → 反问"你是不是指 InternAgent1.5?"（复用已有 `question` 机制），而非硬列。

**预期效果**：打错/生僻命名也能命中或明确反问；不再返回"看似相关实则噪声"的一堆。挂载点：**Stage 3 + literature-search skill**。

---

## 能力 2 · 迭代式检索（一次查不全就补查）

**现状**：单轮检索，查完即止，不看"还缺什么"。

**可借鉴技术**：自适应查询精化——[FAIR-RAG](https://arxiv.org/html/2510.22344v1) / RA-ISF 分析"证据缺口"再生成新子查询，直到证据充分；[递归 DeepResearch](https://arxiv.org/pdf/2601.03261) 用可控的 breadth/depth 参数做"广探索→深挖"循环，并把中间的子查询/learnings 暴露出来指导下一轮。arc 的死代码 `search_papers_multi_query`（pipeline-1 §缺口 A）正好是这个循环的一半基建。

**预期效果**：覆盖度从"单次宽查询"升级为"缺口驱动的多轮补查"，直接改善 Stage 5-6 "研究空白"的准确性（没查到的方向 ≠ 不存在的方向）。挂载点：**Stage 4 + systematic-review skill**。

---

## 能力 3 · 噪声过滤与重排（去掉无关论文）★核心

**现状**：合并后**只按 `citation_count` 排序**（这是 bad case 里"对的那篇被引用≈0 压没"的直接原因），无 query→结果相关性评分，无过滤，噪声全量回灌上下文。

**可借鉴技术**：
- **[AFR-Rank](https://www.sciencedirect.com/science/article/abs/pii/S0306457325001736)** 的三段式 **Assessor → Filter → Reranker：先滤掉不相关文档再重排**。关键红利：LLM **listwise 重排零样本即可**，无需训练、无需 embedding 基建——完美契合 arc（LLM 驱动、无向量库）。
- 排序不再纯看引用数：纳入源自带的 relevance 信号（OpenAlex `relevance_score` 当前被丢弃）；known-item / 弱结果场景 relevance 优先。
- 相关性地板过滤 + **透明返回"已过滤 N 篇低相关"**（不静默截断）。

> **📎 AFR-Rank 机制速览**（输入/输出/评测）
> - **定位**：接在一阶段检索之后的"精加工"，本身不检索。**输入** = query + 一阶段的 **top-100**；**输出** = 重排后的有序列表（最终精排 **top-20**）。
> - **三段式**：① **Assessor**——top-100 分组、逐组 LLM 打相关性分，只留高分项；② **Filter**——按相关性分 + 原始排名重新分组、组内降序，进一步去边缘项；③ **Reranker**——对留下的 **top-20** 做 LLM listwise 精排。要点：先粗筛去噪（100→20）再花算力精排 = 又准又省。
> - **评测**：主指标 **nDCG@10**（前 10 排序质量）；标准数据集为 **TREC DL + BEIR**（后者含 SciFact/Signal 等）。⚠️ 具体子集/分数在原文付费墙后，引用前需核。
> - **TREC DL**：NIST 办的年度 IR 排序评测（黄金标准），底座数据 = MS MARCO（真实 Bing query + 百万级文档），核心是 **qrels**（"某文档对某 query 相不相关"的人工分级标注）；每年出全新测试 query、提交在标注生成前，防过拟合。§0 那句 ">60%/>90% 不相关" 即用 TREC DL/BEIR 的 qrels 去核一阶段检索 top-100 的不相关占比——**基准实测，非 arc 实测**。
> - **对 arc 的意义**：arc 现状 ≈ 只有一阶段检索、无 Assessor/Filter/Reranker；AFR-Rank 证明"LLM listwise + 先滤后排"**零样本即可用**（不训练、不需向量库），契合 arc 无 embedding 基建的现状。

**预期效果**：在结果列表中以 query→结果相关性为主排序、过滤明显不相关项，减少"引用高但与 query 无关"的条目（如 bad case 中被同名高引论文挤占的现象；具体改善幅度待评测量化）；同时是"扩大检索源"的前置条件。挂载点：**Stage 5**，可增强/替代当前 `scientific-critical-thinking` 的 GRADE 人工筛。

---

## 能力 4 · 知识图谱化综合（结构化理解 + 找 gap）★核心

**现状**：文献是按 query 分组的平铺列表，"研究空白"靠 LLM 读列表脑补，无跨文献聚合。

**可借鉴技术**：**GraphRAG**（[Edge et al. 2024](https://arxiv.org/abs/2404.16130)）——实体抽取 → 社区发现 → 社区摘要 → 全局综合，在"综合/找主题/找 gap"这类问题上比普通 RAG **准 3.4×、能回答此前答不了的问题**。效率变体 [LightRAG/LeanRAG/HippoRAG](https://github.com/DEEP-PolyU/Awesome-GraphRAG)（PageRank 多跳）可降成本。
- **类别骨架用 OpenAlex `topics`/`domain` 层级**（domain 4 类 → field 26 → subfield → topic）：OpenAlex 已接入、免费自带，只是当前 `select` 没请求。它一个字段同时喂饱"节点分类/上色 + 跨学科检测信号"。
- 知识图谱**不只是可视化，更是让综合和找 gap 变强的底座**——节点=论文/概念，边=共享 topic/引用，社区=子领域，社区摘要=每个子领域现状，社区之间的空隙=研究空白。

**预期效果**：Stage 6 从"平铺列表 + 脑补 gap"升级为"学科社区图 + 结构化 gap 识别"；文献栏自然呈现为按学科上色的知识图谱状态（可视化是这个底座的下游产物）。挂载点：**Stage 6 + 新的图谱综合能力**。

---

## 能力 5 · 跨学科洞察（insights）

**现状**：无任何跨域机制。

**可借鉴技术**（清晰谱系，越往后越强）：
- [SciMON](https://arxiv.org/html/2405.17044v2)：平铺检索灵感 + 迭代优化新颖性。
- ResearchAgent：实体中心 KG + 组合式创造（跨论文概念组合）。
- [Graph2Idea](https://arxiv.org/pdf/2606.09105)：图结构多跳检索"概念上远"的灵感。
- **跨域种子合成 / [Idea-Catalyst](https://arxiv.org/abs/2603.12226)**：把目标问题**改写成 N 个不同学科的词汇再检索**，强制跳出本学科舒适区（呼应"伪跨学科"——不加约束时 LLM 嘴上跨学科、实际 947 次全缩在 CS）。
- [类比推理](https://arxiv.org/html/2605.11258v1)：跨域类比生成的方案，多样性+新颖性均显著高于基线（人评确认）。

**预期效果**：能主动产出"从 X 学科借来的机制可用于本问题"这类跨域连接，而非同领域改良。结构上用能力 4 的图谱检测"跨 ≥2 domain 的桥节点"作为洞察锚点。挂载点：**Stage 1-2 选题 + Stage 6**，可新增 cross-domain ideation skill（借 openscience `scientific-brainstorming`）。

---

## 能力 6 · 扩大检索源（前置依赖能力 3）

**现状**：OpenAlex + S2 + arXiv 三源。**可借鉴**：openscience 的统一 `Connector` 抽象 + 7 个 key-free client（补 PubMed / Europe PMC / Crossref / CORE / bioRxiv）。**必须挂在能力 3 的过滤之后**——多源=多噪声，无过滤则得不偿失。

---

## 附录 A · 近 1-2 年科研智能体的 DR / 文献检索方法（横向盘点）

> 上面各"能力"是按技术点拆的；这里按**系统**横切，看近 1-2 年论文各自怎么做文献调研/DR、arc 能借什么。
> 共性观察：主流已从"平铺检索"走向 **query 理解/分解 → 引用跟随扩展 → retrieve-then-rerank → 知识图谱/结构化组织 → 多轮迭代**，
> 并开始正视"每次从零构建知识"的瓶颈。

> 🔴 **bad-case 实锤**：用户那次搜不到的 **InternAgent-1.5**（[2602.08990](https://arxiv.org/abs/2602.08990)，2026）是**真实且高度相关**的论文——
> 它本身就是个长程自主科研智能体，内部有 **Survey Agent 专做文献综述** + Idea Innovation Agent + Orchestration Agent。
> arc 的检索连"用户点名的、真实存在的、还正好同领域"的这篇都没捞到，直接坐实了能力 1（query 理解/known-item）的缺失。

### A.1 专做文献检索的 agent（最贴 arc 的能力 1-3，优先精读）
| 系统 | DR / 文献检索方法 | arc 可借鉴点 |
|---|---|---|
| **PaSa**（[2501.10120](https://arxiv.org/abs/2501.10120)，ACL 2025） | **Crawler + Selector** 双 agent，RL 训练：自主调搜索工具、**跟着引用扩展**、读论文、筛选；自带 AutoScholarQuery（35k 合成 query）/ RealScholarQuery 基准。recall@20 比 Google+GPT-4o 高 ~38% | 标杆作。"搜索→跟引用扩展→筛选"的多步 agent 化，是 arc 能力 1+2 的直接蓝本 |
| **SPAR** | query 理解 + **多源检索** + 引用探索 + **重排**，免训练 | 几乎就是 arc 能力 1+3+6 的整合蓝图 |
| **PaperScout** | 提升工具使用自主性：让 agent 按当前检索状态自行决定何时/如何调搜索与扩展 | 迭代检索（能力 2）的编排参考 |
| **Chain of Ideas**（[2410.13185](https://arxiv.org/html/2410.13185v3)） | 文献按时间组织成 **idea 链**；Novelty Checker 用两阶段 **retrieve-then-rerank**（关键词/片段 → embedding 过滤 → **facet-based LLM 重排**） | 印证能力 3；"按时间演进的 idea 链"是 KG 之外另一种组织骨架 |

### A.2 端到端 AI Scientist（内含 DR / Survey 环节）
| 系统 | 文献/DR 环节做法 | arc 可借鉴点 |
|---|---|---|
| **InternAgent-1.5**（[2602.08990](https://arxiv.org/abs/2602.08990)） | 闭环多 agent：**Survey Agent 做文献综述** → Idea Innovation → Orchestration | bad-case 目标本身；Survey Agent 的职责划分值得对照 arc 的 Stage 3-6 |
| **ResearchAgent**（[2404.07738](https://arxiv.org/abs/2404.07738)） | **学术知识图谱 + 引用网络 + 实体中心存储**做检索，多 agent 模拟同行评审迭代 | 印证能力 4；实体中心存储 = OpenAlex topics 之外另一条 KG 路径 |
| **AI-Researcher**（[2505.18705](https://arxiv.org/html/2505.18705v1)） | 检索 agent 从科学库**同时抓论文 + 代码仓库**；用户给 10-15 篇种子起步 | "论文+代码一起检索"对 baseline-profiling（精读实现）很有用 |
| **AI Scientist v2**（[2504.08066](https://arxiv.org/abs/2504.08066)） | agentic **tree search** 做工作坊级自主发现 | 探索-利用搜索（呼应 ScientistOne） |
| **DeepScientist**（[2509.26603](https://arxiv.org/abs/2509.26603)）/ **EvoScientist**（[2603.08127](https://arxiv.org/pdf/2603.08127)）/ **Kosmos**（2025.11） | 长程 / 多 agent 演化式端到端发现 | 长程编排参考 |
| **AI co-scientist**（DeepMind, Nature 2026） | 分层多 agent **辩论**：generate/reflect/rank/evolve/proximity/meta-review | 筛选/排序可从"单次打分"升级为"多 agent 辩论"（呼应 LLM-as-a-Verifier） |
| **SciAgents**（[2409.05556](https://arxiv.org/abs/2409.05556)）/ **HypoAgents**（[2508.01746](https://arxiv.org/pdf/2508.01746)） | 图推理 / 贝叶斯-熵 多 agent 假设生成 | 假设生成阶段参考 |

### A.3 开源 Deep Research 框架（报告合成角度）
STORM（多视角模拟对话写维基式长文）、GPT-Researcher、**WebThinker**（Deep Web Explorer + 起草/核验/编辑）、ByteDance **DeerFlow**、阿里 **Tongyi WebAgent**（WebDancer/WebSailor/WebShaper）、HF **Open DeepResearch/smolagents**、**Cognitive Kernel-Pro**（[2508.00414](https://arxiv.org/pdf/2508.00414)）。清单持续更新见 [Awesome-Deep-Research](https://github.com/DavidZWZ/Awesome-Deep-Research)。

### A.4 已详析（本 session 前文）
**ScientistOne**（[2605.26340](https://arxiv.org/abs/2605.26340)，Chain-of-Evidence + 引用核验）、**Idea-Catalyst**（[2603.12226](https://arxiv.org/abs/2603.12226)，跨域重构，见能力 5）、**Intern-Atlas**（[2604.28158](https://arxiv.org/pdf/2604.28158)，点出"每次从零建知识"通病 → 主张**跨会话持久化**、方法粒度知识库）。

### A.5 综述 / 资源库（追踪长尾）
[From Automation to Autonomy（HKUST-KnowComp, EMNLP 2025）](https://github.com/HKUST-KnowComp/Awesome-LLM-Scientific-Discovery)、[From AI for Science to Agentic Science](https://arxiv.org/pdf/2508.14111)、[Towards Scientific Intelligence](https://arxiv.org/pdf/2503.24047)、[A Survey on Hypothesis Generation](https://arxiv.org/html/2504.05496v1)、[Autonomous Agents for Scientific Discovery](https://arxiv.org/html/2510.09901v2)。

> ⚠️ SPAR / PaperScout / Kosmos / AI co-scientist 等未逐一核到 arXiv ID 的以文字标注出处；引用前再核原文。

---

## 如何验证"效果"变好（评测抓手）

### 选型总表（任务类型 / 输入 / 输出 / 主指标 / 可用性）

> ⚠️ 除特别标注外，以下细节均来自本 session 的 WebSearch 二手摘要（环境限制未能抓取原文/表格），
> 具体数据规模、许可证、指标精确定义**引用/落地前需核对各自主页或 repo**。

| Benchmark | 测什么（任务类型） | 输入 | 输出/度量 | 主指标 | 对应能力 | 可用性 |
|---|---|---|---|---|---|---|
| **LitSearch**（princeton-nlp, EMNLP'24） | 文献检索召回 | 597 条真实 query | query→gold 论文列表比对 | **Recall@k** | 能力 1/3 | 直接可用；但底层语料与 arc 三源未必重合，"没检回"需拆分**排序问题 vs 覆盖率问题** |
| **DBLP-ACM / DBLP-Scholar**（Leipzig） | **实体匹配/记录去重**（非检索） | 标注的记录**成对**清单（title/authors/venue/year） | 每对判 match / non-match，与标注比对 | **Precision / Recall / F1** | 去重（`_deduplicate`） | 离线秒级、可做单测；老数据、偏 CS、不覆盖 DOI 级匹配。详见下方"用法" |
| **CoverageBench**（SIGIR'26, [2603.20034](https://arxiv.org/abs/2603.20034)） | 一组结果的**信息点/侧面覆盖**是否全面 | topic + 检索结果排序列表 | 覆盖了多少 **nugget**（预标注的关键信息点）、多快覆盖 | **α-nDCG@10**（覆盖类） | 能力 4（多样性/覆盖） | 数据开源（HF `hltcoe/coveragebench`），但需自接 α-nDCG 计算；测**通用主题侧面**，非"学科多样性" |
| **TaxoBench / Synthesis Gap**（[2601.12369](https://arxiv.org/abs/2601.12369)） | **检索 + 组织成专家分类树**两件事 | 综述主题（agent 去检索+组织） | 检回论文 vs 专家该引；论文归到分类树类目 | Recall/P/F1（检索）+ **ARI / V-measure / TED**（组织） | 能力 4（综合/找 gap） | **有开源代码**（[TaxoBench](https://github.com/KongLongGeFDU/TaxoBench)，Apache-2.0），可用性较实在；标题 "Retrieve/Find and Organize" 同篇不同修订 |
| **ScholarQuest**（[2606.20235](https://arxiv.org/pdf/2606.20235)） | 主题分类树引导的检索 | taxonomy 化 query 集 | query→gold 比对 | Recall/Precision | 能力 1/3 | 比 LitSearch 覆盖更系统；需搭环境 |
| **PaSa RealScholarQuery / AutoScholarQuery**（[2501.10120](https://arxiv.org/abs/2501.10120)） | 细粒度学术检索 | 50 真实 + 35k 合成细粒度 query | query→标注论文集比对 | Recall@k / Precision | 能力 1/2/3 | PaSa 配套；真实集小、合成集大 |
| **ScholarGym**（[2601.21654](https://arxiv.org/pdf/2601.21654)） | DR **信息采集阶段**能力 | DR 任务 | 采集质量评估 | 多维 | 能力 2/3 | 新，协议需核 |
| **CiteME** | 检索**鲁棒性**（API 不稳/断链致失败） | 引用溯源任务 | 能否定位到正确文献 | 成功率 | 三源熔断/缓存降级 | 对 arc 容错是好压力测试 |
| **LiveIdeaBench**（[Nature Comms'26](https://www.nature.com/articles/s41467-026-70245-1)） | 跨学科 **idea 质量** | 单关键词 prompt | LLM 评审团打分 | originality/feasibility/fluency/flexibility/clarity 五维 | 能力 5 | 只在做到能力 5 时才需要；与检索本身无关 |
| **CSFCube**（[NeurIPS'21](https://ar5iv.labs.arxiv.org/html/2103.12906)） | **faceted** 相关性（按 objective/method/result 分面） | 查询论文 + 指定 facet | 分面分级相关性判定 | 分面 nDCG | 能力 3 细化 | 50 查询、专家标注 |
| **🔴 bad-case 回归集**（自建） | arc **真实失败模式** | InternAgent-1.5（[2602.08990](https://arxiv.org/abs/2602.08990)）等 typo/生僻命名 | "对的那篇"排名 + 是否触发反问 | 排名位次 / 反问命中 | 能力 1/3 | **信噪比最高**：直接对着产品的具体病，公开 bench 测不到 |

### DBLP-ACM / DBLP-Scholar 用法（离线单测，最易落地）
- **数据集**：DBLP-ACM（DBLP×ACM，标注 2224 对匹配）、DBLP-Scholar（DBLP×Google Scholar，标注 5347 对，噪声更大更难）。每条 4 字段：title/authors/venue/year。
- **评测流程**：把标注 pair 的两条记录各构造成 `Paper` → 喂给 `_deduplicate`/`_normalise_title` 的匹配逻辑 → 输出 match/non-match → 与标注比对算 **P/R/F1**。不打 API、可复现。
- **能暴露什么**：① **漏合**（伤 Recall）——同一篇但标题带副标题/差一词，归一化后不等 → 判成两篇；② **误合**（伤 Precision）——不同篇但标题高度相似（如 bad case 的一堆 `xxx 1.5`）归一化后恰好相等 → 判成同一篇。直接回答"去重阈值太松还是太紧"。
- **边界**：老数据、偏 CS；测的是**模糊标题匹配的判别力**（去重第三级），不覆盖 DOI/arXiv ID 级匹配（第一、二级）与跨语言/非 CS 变体。

### 轻量自测（无需外部标注数据）
- **领域多样性**：直接用 OpenAlex 返回的 `domain`/`field` 字段，对一次检索结果算**学科分布 entropy / unique-domain 数**——不需要标注集就能得一个多样性基线数字（能力 4 的廉价代理）。

### 建议落地顺序（评测本身也别一次全上）
1. **bad-case 回归集 + DBLP 去重单测** — 离线、1-2 天、直接对着已知的病，给"改了有没有修好"的即时反馈。
2. **LitSearch** — 建立"平均检索质量"的 Recall@k 基线。
3. **OpenAlex domain entropy** — 顶着多样性维度，别急着啃 CoverageBench。
4. 需要严格的综合/组织评测时再上 **TaxoBench**（有 repo，最实在）；能力 5 做出来后再上 **LiveIdeaBench**。

---

## 落地优先级（效果/成本比排序）

1. **能力 3（去噪重排）+ 能力 1 的排序修复** — 最低成本、直接修 bad case、且是一切的前置。
2. **能力 4 的 OpenAlex topics 打通** — 一个字段解锁分类/上色/跨学科信号，改动极小。
3. **能力 1 完整版（实体消歧 + did-you-mean）+ 能力 2（迭代补查）**。
4. **能力 4 的 GraphRAG 综合 + 图谱化**。
5. **能力 5（跨学科）+ 能力 6（多源）**。

---

## 明确不做
- 不引入 embedding/向量重排（arc 无基建；LLM listwise 重排已够，见能力 3）。
- 扩源不先行（必须在能力 3 之后）。
- 本方案只定"做什么/预期效果"，前后端实现细节暂略。
