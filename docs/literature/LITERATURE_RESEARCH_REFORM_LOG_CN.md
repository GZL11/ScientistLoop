# 论文调研链路改动记录

> 目的：记录我们围绕“论文检索 + 文献调研 + 研究方向识别”做过的版本化改动，便于后续追溯、回滚和继续收紧边界。

## 1. 这次改动的核心

我们把论文相关能力拆成了三层：

1. **具体论文查找**：优先原生 `websearch` / `webfetch`，再做学术元数据补充。
2. **文献调研检索**：`arc_search_literature` 负责 topic-level 检索、候选扩展、筛选与来源核验。
3. **研究综合**：`literature-research` 负责领域理解、子方向聚类、缺口识别、方向推荐和 idea 排序。

同时，`literature-search` 只保留检索执行，不再承担研究综合。

## 2. Skill 和 Tool 的关系

这里要先区分两个层级：

- **Skill 是方法论 / 工作流**：告诉 agent 应该如何判断任务、如何拆步骤、何时停止、什么时候问用户、如何筛选和综合结果。
- **Tool 是执行器 / 数据源**：真正去搜索、抓网页、查论文元数据、核验引用、读取文件。

因此它们不是并列替代关系，而是上下游关系：

```text
用户意图
  -> skill 判断任务类型与流程
  -> skill 决定调用哪些 tool
  -> tool 返回真实数据
  -> skill 根据流程筛选、核验、组织输出
```

举例：

- `literature-search` 是 skill；它会决定单篇论文先走 `websearch/webfetch`，主题检索再走 `arc_search_literature`。
- `arc_search_literature` 是 tool；它只负责从 OpenAlex / Semantic Scholar / arXiv 拉真实论文候选。
- `literature-research` 是 skill；它可以调用 `literature-search` 做检索子流程，也可以使用 `arc_search_literature` 返回的候选，但它的任务是 field map / gap map / idea bank，不是单纯“搜论文”。

一句话：

- **skill 管“怎么做、做到哪一步、什么时候停”**
- **tool 管“去哪里查、查回来什么”**

## 3. `literature-search` 和 `literature-research` 的核心区别

这两个名字容易混，因为都和文献有关。最明确的边界是：

- **`literature-search`：检索执行 skill**
- **`literature-research`：研究综合 skill**

| 维度 | `literature-search` | `literature-research` |
|---|---|---|
| 关注问题 | “我要找到哪些论文？” | “这些论文说明这个领域是什么状态？” |
| 输入 | 论文名、模糊标题、关键词、topic、systematic review 请求、已有 corpus | 一个研究领域、方向、问题、想找缺口/热点/idea 的需求 |
| 核心动作 | 查找、query 设计、候选召回、筛选、来源核验 | 定范围、建 seed corpus、扩展候选、聚类、找 gap、排 idea |
| 主要 tool | `websearch`、`webfetch`、`arc_search_literature`、必要时 citation/source 工具 | 可以调用 `literature-search` 作为子流程，再用其结果做综合 |
| 主要产出 | 论文候选、筛选语料、检索记录、确认问题 | `field_map.md`、`gap_map.yaml`、`idea_bank.yaml`、调研总结 |
| 不应该做 | 不应该产出 field map / gap map / idea bank | 不应该只返回一堆论文列表就结束 |
| 何时停止 | 找到目标论文、得到候选集、或需要用户补充线索 | 完成领域结构/缺口/idea 总结后，等待用户选择方向 |

判断口诀：

- 用户要“找论文 / 查相关工作 / 做检索” -> `literature-search`
- 用户要“理解领域 / 聚类热点 / 找缺口 / 想 idea” -> `literature-research`

具体例子：

| 用户请求 | 应该进入 |
|---|---|
| “InterAgent-1.5 这篇论文找一下” | `literature-search` |
| “找几篇和 LLM multi-agent collaboration 相关的论文” | `literature-search` |
| “帮我调研一下 LLM multi-agent collaboration 这个方向有哪些子方向” | `literature-research` |
| “这个方向还有哪些没解决的问题？” | `literature-research` |
| “给我几个值得做的研究 idea” | `literature-research`，后续 idea 还要过 `novelty-gate` |

## 4. 相关 skill

### `literature-search`

- 位置：`famou_scientist/assets/opencode/registry/source/skill/experiment/literature-search/SKILL.md`
- 作用：论文检索、query 设计、候选筛选、来源核验
- 当前边界：
  - 负责：具体论文查找、模糊查找、主题检索、systematic review protocol、语料扩展
  - 不负责：field map、gap map、idea bank

#### 流程

`literature-search` 的流程是“先判意图，再选检索路径，再做筛选”：

1. **先判断任务类型**
   - 单篇论文查找
   - 模糊论文名确认
   - 主题检索
   - systematic review protocol
   - corpus reading
2. **再选检索路径**
   - 单篇/模糊论文：先 `websearch`，再 `webfetch`
   - 主题检索：用 `arc_search_literature`
   - 如果网页证据不够，再把 `arc_search_literature` 作为学术元数据补充
3. **做候选筛选**
   - 只保留标题核心词、作者、年份、URL 证据匹配的候选
   - 不接受只靠数字、版本号、年份、泛词命中的结果
4. **输出给上层**
   - 返回可追溯的候选论文
   - 如果置信度不够，就要求用户补充 DOI / arXiv ID / 作者 / 机构 / 主题线索

#### 典型输出

- 论文候选列表
- 检索词和变体
- 命中证据
- 需要用户确认的候选
- 综述检索时的筛选后语料

### `literature-research`

- 位置：`famou_scientist/assets/opencode/registry/source/skill/experiment/literature-research/SKILL.md`
- 作用：研究综合
- 当前边界：
  - 负责：领域结构梳理、子方向聚类、证据驱动的缺口识别、研究方向推荐、idea 排序
  - 可以把 `literature-search` 当作子流程

#### 流程

`literature-research` 的流程是“先定范围，再做种子检索，再做证据综合”：

1. **先定范围**
   - 明确领域边界
   - 明确时间范围
   - 明确输出类型：field map / gap map / idea bank
   - 如果范围太大，先追问收敛
2. **做种子检索**
   - 从最近综述、benchmark、代表性系统、奠基作、用户给定种子开始
   - 必要时调用 `literature-search` 先补齐检索面
3. **做扩展与核验**
   - 沿引用、被引、related work、方法名、数据集名扩展
   - 每个候选都要核验标题、作者、年份、来源、相关性
4. **聚类成 field map**
   - 按问题 / 方法 / 数据任务 / 应用 / 评测聚类
   - 每个 cluster 写清核心问题、代表论文、进展和瓶颈
5. **提炼 gap map**
   - 每个 gap 需要有证据、对照和置信度
   - 不能只凭关键词印象下结论
6. **生成 idea bank**
   - 只从已验证的 gap 出发
   - 给出 novelty、feasibility、validation plan、risk、priority
7. **交付总结**
   - 输出 field map / gap map / idea bank
   - 保留查询和候选痕迹，方便回溯

#### 典型输出

- `scope.md`
- `queries.jsonl`
- `seed_papers.jsonl`
- `candidate_papers.jsonl`
- `field_map.md`
- `gap_map.yaml`
- `idea_bank.yaml`

## 5. 相关 tool

### `arc_search_literature`

- 位置：`famou_scientist/assets/opencode/tool/arc.ts`
- 作用：多源学术检索，底层真查 OpenAlex / Semantic Scholar / arXiv
- 当前定位：
  - 适合 topic-level 调研
  - 适合 related work / survey
  - 不再作为具体论文查找的第一步

#### 流程

`arc_search_literature` 是一个“真检索工具”，它不做语义综合，只做学术候选拉取：

1. 输入一个 query
2. 走多源学术检索
   - OpenAlex
   - Semantic Scholar
   - arXiv
3. 把结果压缩成可读摘要
   - 标题
   - 作者
   - 年份
   - DOI / arXiv ID
   - 截断后的摘要
4. 返回给 skill 做筛选、聚类或补充阅读

#### 适合做什么

- 找相关论文
- 扩充候选库
- 按子方向拆开检索
- 给综述和调研提供真实候选

#### 边界

它只回答一件事：**“给我一批真实论文候选”**。

它不回答这些问题：

- 这个领域怎么分层
- 哪些子方向更重要
- 哪些方向有缺口
- 哪个 idea 值不值得做
- 哪些论文该归到同一个主题簇里

你可以把它理解成“学术检索引擎 + 候选返回器”，不是“研究综合器”。

### `arc_lookup_paper`

- 位置：`famou_scientist/assets/opencode/tool/arc.ts`
- 作用：具体论文查找的学术候选补充
- 当前定位：
  - 用于补充学术元数据和候选
  - 不能只靠版本号、数字或泛词返回“看起来相关”的候选
  - 需要和原生 `websearch` / `webfetch` 的证据一起看

#### 流程

1. 输入用户原始论文名、缩写、近似标题、arXiv ID 或 DOI
2. 先尝试用网页证据补充候选
3. 再做学术元数据匹配
4. 给出候选、置信度和是否需要确认
5. 如果证据不够，必须回问用户

#### 适合做什么

- 具体论文名的候选补充
- 近似标题或拼写偏差的容错
- 学术元数据核验
- 不适合做大范围主题检索

### `websearch` / `webfetch`

- 位置：OpenCode 原生工具
- 作用：
  - `websearch`：先找网页证据
  - `webfetch`：再核验标题、作者、摘要、ID
- 当前定位：
  - 具体论文查找优先走这条链路

#### 流程

1. 先用 `websearch` 搜用户原话或少量变体
2. 找到可信页面后，用 `webfetch` 抓正文
3. 用页面标题、作者、摘要、ID 反证是否是目标论文
4. 再决定是否需要补充学术检索

#### 适合做什么

- 论文名模糊匹配
- 官网 / arXiv / OpenReview / DOI 页面核验
- 最新信息和网页证据确认

## 5.1 `arc_search_literature` 和 `literature-research` 的边界

这里还有一个容易混的点：`arc_search_literature` 是 tool，`literature-research` 是 skill。它们不是同一层级。

最简单的判断方式还是看**输出形态**。

| 任务 | 应该用谁 | 产出 |
|---|---|---|
| 找几篇相关论文 | `arc_search_literature` | 论文列表、摘要、DOI、arXiv ID |
| 查某个 benchmark / 领域的相关工作 | `arc_search_literature` | 可筛选的候选集 |
| 需要把论文按方向分组 | `literature-research` | field map |
| 需要找研究缺口 | `literature-research` | gap map |
| 需要推荐下一步做什么 | `literature-research` | idea bank |

再粗暴一点说：

- **`arc_search_literature` = 检索答案**
- **`literature-research` = 解释这些检索结果，并据此做研究判断**

所以边界不是“都能搜论文”这么宽，而是：

- `arc_search_literature` 负责“搜到什么”
- `literature-research` 负责“这些搜到的东西说明了什么”

更准确地说：

- `arc_search_literature` 给 `literature-research` 提供候选论文和摘要；
- `literature-research` 读取这些候选后，负责决定怎么聚类、哪些是证据、哪些是 gap、哪些 idea 值得继续。

## 6. 当前版本化改动

### 6.1 论文查找从“lookup-first”改成“web-first”

我们先后做过几轮版本化调整：

- `20260713-001-paper-lookup`
- `20260713-002-parallel-paper-lookup`
- `20260714-001-web-first-paper-lookup`
- `20260715-002-disable-lookup-paper-fallback`
- `20260715-003-web-first-unified-routing`
- `20260716-001-retrieval-boundary`

这些版本共同指向同一个方向：

- 具体论文查找不能直接把 `arc_search_literature` 当第一入口；
- 不能只因标题里有数字、版本号、缩写就把不相关论文当候选；
- 命中网页证据后再做学术元数据补充；
- 检索和研究综合必须分层。

### 6.2 `literature-research` 的新增

- `20260715-001-literature-research-workflow`
- `20260716-001-research-boundary`

这两版把“文献调研”里的后半段单独抽成了 `literature-research`：

- 先收集足够的证据；
- 再做 field map / gap map；
- 最后产出方向推荐和 idea 排序。

## 7. 相关 prompt 版本

和这条链路直接相关的 prompt / registry 版本包括：

- `AGENTS.20260714-002-agents-web-first-paper-lookup.md`
- `AGENTS.20260714-003-agents-literature-skill-delegation.md`
- `AGENTS.20260715-001-agents-paper-lookup-load-skill.md`
- `AGENTS.20260715-002-agents-remove-paper-lookup-skill-gate.md`
- `AGENTS.20260716-001-literature-skill-boundary.md`

这些版本的方向是一致的：

- `AGENTS.md` 不再承担细粒度策略；
- skill 负责检索策略和边界；
- tool 负责真实执行；
- prompt 负责路由，不负责把所有策略写死。

## 8. 现在的推荐流程

### 单篇论文

`websearch` -> `webfetch` -> 必要时 `arc_lookup_paper` / `arc_search_literature`

### 主题检索 / 综述

`literature-search` -> `arc_search_literature` -> 筛选 / 核验

### 领域理解 / 缺口 / idea

`literature-research` -> 必要时调用 `literature-search` 作为子流程

## 9. 这次改动的总结

- `literature-search` 从“宽泛文献入口”收回到“检索执行”
- `literature-research` 作为独立研究综合 skill 新增
- `arc_search_literature` 继续做多源学术检索，但不抢具体论文查找入口
- `arc_lookup_paper` 作为学术候选补充，不再单独承担第一步
- `websearch / webfetch` 回到具体论文查找的第一链路

## 10. 备注

这份记录只覆盖论文调研链路，不覆盖实验执行、写作、前端或多租户改动。
