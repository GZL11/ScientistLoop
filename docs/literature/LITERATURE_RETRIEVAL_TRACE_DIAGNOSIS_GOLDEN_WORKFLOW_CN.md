# 论文检索与调研的轨迹诊断金标 Workflow

> 目标：为论文检索、文献调研、领域缺口识别建立一套可观测、可评分、可归因的金标流程。以后每个 session 都能按这个 workflow 复盘：问题出在意图识别、skill 路由、query 设计、tool 调用、候选筛选、证据核验，还是 synthesis 自作主张。

## 1. 背景

我们已经完成了第一版论文检索改造：

- 单篇论文查找优先 `websearch` / `webfetch`
- 主题文献检索使用 `arc_search_literature`
- 领域理解、缺口识别、idea 排序使用 `literature-research`
- `literature-search` 收窄为检索执行 skill
- tool / skill / prompt 版本开始解耦管理

下一步要解决的是质量诊断问题：不能只看最终有没有答对，而要看 agent 在每一步是否做了正确动作。

## 2. 可参考的论文和项目

### Agent 轨迹级评估

1. [AgentEval: DAG-Structured Step-Level Evaluation for Agentic Workflows with Error Propagation Tracking](https://arxiv.org/abs/2604.23581)

   这篇最贴近我们的需求。它把 agent execution 建成 DAG，每个节点有 typed quality metrics，并做 error propagation 和 root cause attribution。

   对我们的启发：
   - 不只评最终答案；
   - 每一步都有质量指标；
   - 上游错误会传播到下游；
   - 诊断结果要能指出 root cause。

2. [AgentBoard: An Analytical Evaluation Board of Multi-turn LLM Agents](https://arxiv.org/abs/2401.13178)

   AgentBoard 强调 multi-turn agent 不应该只看 success rate，而要看 fine-grained progress rate。

   对我们的启发：
   - 论文检索也应该有阶段性 progress；
   - 例如“识别出这是单篇论文查找”就是一个 progress；
   - “搜到目标论文但没有核验”是部分成功，不应和完全失败混在一起。

3. [Agent-as-a-Judge: Evaluate Agents with Agents](https://arxiv.org/abs/2410.10934)

   这篇提出用 agentic judge 评估 agentic system，强调 intermediate feedback。

   对我们的启发：
   - 可以做一个诊断 agent，专门读 trace；
   - 诊断 agent 不替代规则检查，而是补充语义判断；
   - 对“是否自作主张升级任务”“候选是否真的相关”这类问题很有用。

### Trace / Observability 平台

1. [LangSmith Evaluation](https://docs.langchain.com/langsmith/evaluation)

   适合作为工程形态参考：run / thread / trace / dataset / evaluator / annotation queue。

2. [Langfuse Observability & Application Tracing](https://langfuse.com/docs/observability/overview)

   它强调 application tracing 需要记录 prompt、model response、token usage、latency、tool 和 retrieval steps。

   对我们的启发：
   - 每次论文检索都要保留 tool input/output；
   - 每个步骤要能按 session 追溯；
   - 成本、耗时、失败原因也应该进入 trace。

3. [Arize Phoenix](https://arize.com/docs/phoenix)

   Phoenix 提供 tracing、evaluation、datasets、experiments，并支持对 traces / spans 打分。

   对我们的启发：
   - 我们可以把一次论文检索拆成多个 span；
   - 每个 span 有独立 score；
   - 新版本 skill/tool 可以在同一批 gold cases 上做 regression。

4. [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)

   适合作为 trace schema 标准化参考。

### 检索与 RAG 评估

1. [BEIR](https://github.com/beir-cellar/beir)

   经典信息检索 benchmark，适合参考 recall@k、MRR、nDCG。

2. [Ragas Agent Metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/agents/)

   Ragas 有 agent / tool use 相关指标，适合参考 tool call accuracy、tool call F1、agent goal accuracy。

## 3. 我们的金标 Workflow

### Step 1: Intent Classification

判断用户到底在要什么。

典型意图：
- 找单篇论文
- 模糊论文名确认
- 找相关论文列表
- 做 topic-level 文献检索
- 做 systematic review protocol
- 做领域理解 / 缺口识别 / idea 推荐
- 读取用户给定的论文 corpus

质量标准：
- 不把单篇论文查找升级成领域调研；
- 不把领域调研降级成简单论文列表；
- 不在用户没要求时主动做深度对比、idea 生成或下一步规划。

Trace 信号：
- 是否加载了正确 skill；
- 是否出现不必要的 `literature-research`；
- 是否在没有用户授权时进入 gap / idea 阶段。

失败归因：
- prompt 路由问题；
- skill 描述边界不清；
- agent 自主扩展过强。

### Step 2: Skill Routing

选择正确的 skill。

金标路由：
- 单篇论文 / 模糊论文名 / 相关论文列表：`literature-search`
- 领域结构 / 热点聚类 / 缺口 / idea：`literature-research`
- 引用核验：`citation-faithfulness`
- baseline 配置抽取：`baseline-profiling`

质量标准：
- skill 与用户意图一致；
- `literature-search` 只做检索执行；
- `literature-research` 只在用户需要 synthesis 时出现。

Trace 信号：
- `skill` tool 的调用参数；
- skill 加载时间点；
- 后续 tool 是否符合 skill 边界。

失败归因：
- skill 描述不互斥；
- AGENTS 主 prompt 干预过强；
- skill 没有被加载或加载过晚。

### Step 3: Query Planning

设计检索 query。

单篇论文：
- 先保留用户原话；
- 最多加 1-2 个聚焦变体，例如 `"<query>" arxiv`、`"<query>" paper`；
- 不要把具体论文名改写成宽泛主题。

主题调研：
- 拆成多个子方向；
- 每个子方向单独 query；
- query 用英文更利于召回；
- 记录每个 query 的目的。

质量标准：
- query 和意图一致；
- 没有过度扩展；
- 子方向拆分合理；
- 能覆盖核心概念、同义词、缩写和代表系统。

Trace 信号：
- websearch query；
- `arc_search_literature.query`；
- `user_query` 是否保留原话；
- 是否有 `queries.jsonl`。

失败归因：
- query rewriting 错误；
- 没有保留原始用户表达；
- 子方向拆分过粗或过细。

### Step 4: Retrieval Execution

执行检索。

金标工具链：

单篇论文：
1. `websearch`
2. `webfetch`
3. 必要时 `arc_search_literature` 做学术元数据补充

主题检索：
1. `literature-search`
2. 多次 `arc_search_literature`
3. 必要时 `websearch` 补充网页证据

领域调研：
1. `literature-research`
2. 调用 `literature-search` 作为子流程
3. 形成 seed / candidate / rejected corpus

质量标准：
- 单篇论文不能一上来只走 `arc_search_literature`；
- 主题调研不能只搜一个宽泛 query；
- 每个检索 tool 都要有明确目的；
- 不应出现大量无关 bash 指令替代检索工具。

Trace 信号：
- tool 调用顺序；
- tool input/output；
- websearch provider 是否可见；
- `arc_search_literature.mode`。

失败归因：
- 原生 `websearch` 未暴露；
- tool 描述误导；
- provider/model 配置问题；
- agent 没遵守 skill 流程。

### Step 5: Candidate Filtering

过滤候选。

质量标准：
- 只匹配数字、年份、版本号、泛词的候选必须剔除；
- 单篇论文候选要匹配核心标题词或明确缩写/拼写变体；
- topic 候选要和子方向相关；
- 不确定候选进入 uncertain，不直接展示成正确结果。

候选状态：
- `accepted`
- `rejected`
- `uncertain`

Trace 信号：
- rejected candidates 是否被记录；
- agent 是否解释筛掉原因；
- 是否有明显噪声继续进入后续 synthesis。

失败归因：
- tool scoring 过松；
- agent 质量门弱；
- 缺少 hard guardrail。

### Step 6: Evidence Verification

核验证据。

必须核验：
- title
- authors
- year
- venue/source
- DOI / arXiv ID / URL
- abstract 或正文片段

质量标准：
- 不能只凭搜索结果标题下结论；
- 必须使用 `webfetch` 或可信学术 API 输出核验；
- 需要区分网页证据、学术元数据、LLM 推断。

Trace 信号：
- 是否出现 `webfetch`;
- 是否有 DOI / arXiv ID；
- 是否引用了来源 URL；
- 是否把推断标注为推断。

失败归因：
- 只检索不核验；
- 没有抓正文；
- 引用来源不可信。

### Step 7: Corpus Construction

构建可追溯语料。

推荐产物：
- `queries.jsonl`
- `seed_papers.jsonl`
- `candidate_papers.jsonl`
- `rejected_papers.jsonl`
- `field_map.md`
- `gap_map.yaml`
- `idea_bank.yaml`

质量标准：
- accepted / rejected / uncertain 分开；
- 每篇论文有来源和加入原因；
- rejected 论文有拒绝原因；
- 后续 field map 只能基于 accepted corpus。

Trace 信号：
- 是否写入 workspace；
- 文件是否在当前 session workspace；
- 是否出现跨 session 路径错乱。

失败归因：
- cwd 隔离问题；
- agent 没保存中间产物；
- synthesis 直接跳过 corpus。

### Step 8: Synthesis Boundary

控制何时进入综合。

质量标准：
- 用户只要求找论文，就不要输出 gap map / idea bank；
- 用户要求领域调研，才进入 `literature-research`;
- idea 必须来自 verified gap；
- 不允许“当前进度”“下一步推进”式自说自话。

Trace 信号：
- 是否加载 `literature-research`;
- 是否生成 field map / gap map / idea bank；
- 用户是否明确要求这些输出。

失败归因：
- synthesis 边界弱；
- compact / auto-continue 后 agent 自行续写；
- prompt 中“全流程”倾向过强。

## 3.1 配套 Skills 和 Hooks

上面的 8 步是主链路，但论文调研不是只有 `literature-search` / `literature-research`。真正的质量闭环还需要一组配套 skill 和 hook。

### 主链路 Skills

| Skill | 作用 | 何时用 | 质量诊断点 |
|---|---|---|---|
| `literature-search` | 检索执行：论文查找、query 设计、候选筛选、来源核验 | 单篇论文、相关论文、topic 检索、systematic protocol | 是否正确区分单篇查找和主题检索 |
| `literature-research` | 研究综合：field map、gap map、idea bank | 用户要领域结构、缺口、方向、idea | 是否有证据支撑 gap / idea |
| `systematic-review` | PRISMA 式全面检索方法 | 用户要求系统综述、完整纳排标准 | 是否定义 protocol、纳排标准、检索范围 |

### 文献质量与候选筛选 Skills

| Skill | 作用 | 何时用 | 质量诊断点 |
|---|---|---|---|
| `scientific-critical-thinking` | 证据质量分级、偏倚/混淆/方法学风险检查 | 文献筛选、候选论文质量评估 | 是否把低质量论文直接当强证据 |
| `scholar-evaluation` | 用 ScholarEval rubric 给论文 / baseline / 草稿打分 | 候选论文需要量化质量比较时 | 是否有 structured score，而不是只凭印象 |
| `citation-faithfulness` | 检查引用是否支撑论点，不只是引用是否存在 | 承重引用、核心论点、定稿前 | 是否出现“真引用、假支撑” |

### Baseline / Benchmark 配套 Skills

| Skill | 作用 | 何时用 | 质量诊断点 |
|---|---|---|---|
| `baseline-profiling` | 从检索到的文献里选 baseline，并抽 benchmark、数据划分、训练配置、评估协议 | 文献调研后、实验设计前 | 是否只列方法名而没抽实验配置 |
| `benchmark-selection` | 基于 baseline × benchmark 矩阵选择评测数据集 | baseline profile 后 | 是否选择了领域共用且可比的 benchmark |

### Idea / Novelty 配套 Skills

| Skill | 作用 | 何时用 | 质量诊断点 |
|---|---|---|---|
| `scientific-brainstorming` | 开放式发散候选方向 | 用户明确要求 idea / 研究方向时 | 是否在没有证据时过度发散 |
| `novelty-gate` | 新方向/假设的创新性自检 | 生成 idea 后、失败后提出下一步前 | 是否只是小修小补、重复文献或重复本 run |
| `hypothesis-formulation` | 把方向转成可证伪假设 | idea 被选中后 | 是否形成 H0、证伪条件、变量和实验预期 |

### Hooks / Plugins

当前与论文检索和调研质量相关的主要 hook/plugin 是：

| Hook / Plugin | 作用 | 对应诊断点 |
|---|---|---|
| `guardrails.ts` 论文候选质量门 | 当具体论文查找返回内容与 query 核心词几乎不匹配时，提示不要展示为候选 | 噪声候选过滤 |
| `guardrails.ts` 检索升级门 | 用户像是在找单篇论文，但 agent 做 broad literature search 时提醒收紧 | 防止单篇查找升级成综述 |
| `guardrails.ts` 引用核验门 | 论文引用未核验时拦截或提醒 | 防幻觉引用 |
| `guardrails.ts` 参考文献完整性门 | 正文用了 cite 但缺 references.bib 时提醒 | 防悬空引用 |
| `compaction-policy.ts` | 控制 compact 后续写体验，避免 summary 暴露或错误续写 | 防 compact 造成上下文/展示污染 |
| `language.ts` | 输出语言策略 | 保持中文体验 |
| `heartbeat.ts` | 后台任务状态提示 | 长任务过程可观测 |

这些配套能力应该进入诊断，而不是只诊断 `arc_search_literature`。例如：

- 如果候选论文低质但没被剔除，可能归因到 `literature-search` 筛选规则或 `guardrails.ts`；
- 如果推荐 idea 很增量，应该归因到 `novelty-gate` 未触发或执行不充分；
- 如果 baseline 对比不可比，应该归因到 `baseline-profiling` / `benchmark-selection` 缺失；
- 如果引用看似真实但不支撑论点，应该归因到 `citation-faithfulness` 缺失。

## 3.2 Web 端“检索文献”是什么

Web 端进程/工具卡里显示的 **“检索文献”** 是前端对 tool 名的中文映射。

真实 tool 是：

```text
arc_search_literature
```

映射位置：

```text
famou_scientist/assets/web/src/app.tsx
```

对应逻辑是：

```ts
case "arc_search_literature": return { icon: "book", label: "检索文献" }
```

所以在 trace 或 Web 进程里看到“检索文献”，本质上就是 agent 调用了 `arc_search_literature`，也就是 OpenAlex / Semantic Scholar / arXiv 的多源学术检索工具。

## 4. 诊断评分表

| 阶段 | 自动规则 | LLM Judge | 主要归因 |
|---|---|---|---|
| Intent | 任务类型是否匹配用户话语 | 是否误升级任务 | prompt / skill |
| Skill | skill 是否正确加载 | skill 边界是否合理 | skill registry |
| Query | 是否保留原话、是否拆子方向 | query 是否覆盖核心概念 | skill |
| Retrieval | tool 顺序是否正确 | tool 使用是否有目的 | tool / provider |
| Filtering | 噪声是否剔除 | 候选是否真的相关 | tool scoring / guardrail |
| Verification | 是否有 URL/DOI/arXiv 核验 | 证据是否充分 | tool / agent |
| Corpus | 是否保存 accepted/rejected | corpus 是否可复盘 | workspace / trace |
| Synthesis | 是否越界综合 | gap/idea 是否有证据 | prompt / skill |

## 5. Trace Schema 建议

每一步建议抽成一个诊断 span：

```json
{
  "session_id": "...",
  "turn_id": "...",
  "step": "candidate_filtering",
  "intent": "specific_paper_lookup",
  "skill": "literature-search",
  "tool": "websearch",
  "input": {},
  "output_ref": "...",
  "quality": {
    "score": 0.0,
    "pass": false,
    "failure_type": "noise_candidate_not_filtered",
    "root_cause": "tool_scoring"
  },
  "evidence": {
    "urls": [],
    "paper_ids": [],
    "workspace_files": []
  }
}
```

## 6. 第一批 Gold Cases

建议先做 20-30 个小而硬的 cases。

### 单篇论文查找

- 用户给完整标题
- 用户给缩写
- 用户给拼错标题
- 用户给版本号标题，例如 `InterAgent-1.5`
- 用户给 arXiv ID
- 用户给 DOI

### 主题文献检索

- 明确领域 + 时间范围
- 模糊领域
- benchmark landscape
- related work for one method

### 领域调研

- “这个方向有哪些子方向”
- “这个领域还有哪些缺口”
- “帮我找几个有价值 idea”

### 反例

- 用户只让读论文，agent 不应自动做深度对比
- 用户只问某篇论文，agent 不应进入 field map
- 用户给 corpus，agent 不应擅自扩展新论文

## 7. 落地计划

1. 固化 gold workflow 文档。
2. 把 OpenCode trace 转成统一 span schema。
3. 为每一步写 rule-based checker。
4. 为语义判断写 LLM judge rubric。
5. 在管理平台里展示每个 session 的 step score。
6. 支持按 skill/tool/prompt/provider 维度聚合失败。
7. 每次发布 skill/tool/prompt 新版本后，跑同一批 gold cases 做 regression。

## 8. 我们优先实现的最小版本

第一版不要做太复杂，先实现这些：

1. 自动识别用户 intent。
2. 检查 skill 是否正确。
3. 检查 tool 调用顺序是否符合金标。
4. 检查候选是否包含明显噪声。
5. 检查是否有 evidence verification。
6. 标出 root cause：prompt / skill / tool / provider / workspace / agent behavior。

这已经足够解释我们近期遇到的主要问题：

- agent 不用 websearch；
- `arc_search_literature` 被误用于单篇论文；
- 噪声候选进入回答；
- `literature-search` 和 `literature-research` 边界不清；
- agent 自作主张从检索升级到调研和 idea。
