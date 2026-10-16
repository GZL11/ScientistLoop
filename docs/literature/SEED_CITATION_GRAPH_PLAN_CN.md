# Seed + Citation Graph 文献调研改造方案

> 目标：把当前“关键词搜论文”的流程，升级为“种子论文驱动的图谱构建”流程，解决召回不足、相关性不稳、缺口判断过快的问题。

## 1. 问题定义

当前文献调研的主要问题不是“能不能搜到论文”，而是：

1. 只做关键词检索，容易漏掉奠基作、后续改进作、系统名论文和同类方法。
2. 搜到之后没有继续做引用扩展，导致知识图谱不完整。
3. 过滤和聚类偏弱，相关论文混入太多无关论文。
4. 缺口判断太快，常在图谱没立住时就开始给方向和 idea。

所以需要把流程改成：

```text
用户问题
  -> 种子发现
  -> 前向/后向引用扩展
  -> 平行相关论文补全
  -> 子领域聚类
  -> 证据链式 gap 判断
  -> idea 候选池 + novelty check
```

## 2. 设计原则

1. **先种子，后扩展**：先找到少量高质量种子论文，再围绕种子扩展。
2. **先证据，后结论**：没有足够引用证据时，只能说“尚未确认”，不能说“没人做过”。
3. **先图谱，后 idea**：没有稳定图谱前，不做强结论和方向排序。
4. **检索与综合解耦**：`literature-search` 只负责检索执行，`literature-research` 负责综合和图谱。
5. **版本化留痕**：每次流程调整都要保留版本和 changelog，方便回溯。

## 3. 目标流程

### 3.1 输入类型分流

#### A. 用户给了明确论文

例如：
- 论文标题
- arXiv ID
- DOI
- 作者名

流程：
1. 先锁定这篇论文作为 seed paper。
2. 做 backward citations：它引用了谁。
3. 做 forward citations：谁引用了它。
4. 做 sibling search：同任务、同方法、同 benchmark 的平行论文。
5. 做 follow-up search：显式改进它的后续论文。
6. 再进入聚类、gap、idea 阶段。

#### B. 用户只给主题或领域

例如：
- “Search-R1 方向”
- “LLM Evolve”
- “科研智能体文献调研”

流程：
1. 先找 seed set：
   - 综述
   - benchmark
   - 奠基作
   - 代表系统
   - 近两年高影响论文
2. 对 seed set 逐个做 citation expansion。
3. 合并去重后，再做聚类和 gap 判断。

## 4. 核心模块

### 4.1 Seed Discovery

职责：
- 从用户问题中找出核心概念、系统名、任务名、benchmark 名。
- 发现 seed paper。

输入来源：
- `websearch`
- `webfetch`
- `arc_search_literature`

输出对象：
- `seed_papers.jsonl`

推荐字段：
- `title`
- `year`
- `authors`
- `doi`
- `arxiv_id`
- `url`
- `seed_reason`
- `seed_type`：`paper` / `survey` / `benchmark` / `system` / `method`
- `confidence`

### 4.2 Citation Expansion

职责：
- 围绕 seed 做前向和后向扩展。
- 补齐同主题、同方法、同 benchmark 的平行论文。

输出对象：
- `candidate_papers.jsonl`
- `evidence_edges.jsonl`
- `queries.jsonl`

建议边类型：
- `cites`
- `cited_by`
- `extends`
- `compares_with`
- `same_task`
- `same_method_family`
- `uses_benchmark`
- `survey_of`

### 4.3 Relevance Filtering

职责：
- 把候选论文分成：
  - accepted
  - rejected
  - uncertain

过滤标准建议至少包括：
1. 问题相关。
2. 方法相关。
3. 任务或应用相关。
4. 评测相关。
5. 不是纯版本号/年份/关键词碰撞。

输出对象：
- `paper_cards.jsonl`
- `rejected_papers.jsonl`
- `search_diagnostics.jsonl`

### 4.4 Graph Synthesis

职责：
- 把论文、引用、反例、子方向组织成图。
- 支持从论文列表升级到领域地图。

输出对象：
- `literature_map.md`
- `field_map.md`
- `gap_map.yaml`

图谱至少要回答：
1. 核心 cluster 是什么。
2. 每个 cluster 的代表论文是谁。
3. 每条主线的演化顺序是什么。
4. 哪些地方证据足够，哪些地方证据薄弱。
5. 哪些 gap 已有反例，哪些还没被覆盖。

### 4.5 Gap / Idea Audit

职责：
- gap 必须绑定 supporting papers 和 counterexamples。
- idea 必须绑定 source gap 和 novelty check。

输出对象：
- `claim_cards.jsonl`
- `gap_map.yaml`
- `idea_bank.yaml`

建议加入的校验：
- `novelty_check`
- `citation_check`
- `coverage_check`
- `counterexample_check`

## 5. 技术拆分建议

### 5.1 新增或强化的 skill

1. `literature-search`
   - 只负责检索执行。
   - 增强 seed 发现、citation expansion、query 设计。

2. `literature-research`
   - 负责图谱合成、gap 判断、idea 排序。
   - 内部调用 `literature-search`，但不替代它。

3. `novelty-gate`
   - 负责 idea 的前向/后向引用核查。
   - 防止“已有工作已覆盖”的方向继续被当成新 idea。

### 5.2 新增或强化的 tool

优先考虑保留原有 tool，只增加更明确的子职责：

- `arc_search_literature`
- `arc_fetch_source`
- `websearch`
- `webfetch`

如果后续需要再拆，可增加：
- citation expansion tool
- graph build tool
- novelty check tool

但第一版不建议过度拆分，先把流程跑顺。

### 5.3 新增或强化的 hook

建议先只保留最少的流程钩子：

1. `search_diagnostic`
   - 记录检索来源、接受数、拒绝数、失败模式。

2. `gap_gate`
   - 在 gap / idea 输出前做证据检查。

3. `novelty_gate`
   - 在 idea 进入候选池前做引用扩展和冲突检查。

## 6. 版本化要求

这次改造不要直接覆盖旧逻辑，建议按版本保存：

- `seed-discovery-v1`
- `citation-expansion-v1`
- `graph-synthesis-v1`
- `gap-audit-v1`
- `idea-novelty-v1`

每个版本至少保存：
- 版本说明
- 触发条件
- 输入输出对象
- 失败模式
- 回滚策略

## 7. 最小落地顺序

建议先做四步：

1. 先把 seed 发现做稳。
2. 再做前向 / 后向引用扩展。
3. 然后做图谱合成和聚类。
4. 最后再接 gap / idea 审计。

不要一开始就把所有机制都塞进去，否则很难定位问题。

## 8. 预期收益

这套改造完成后，应该能明显改善：

- 关键论文召回不足。
- 无关文献混入太多。
- 研究缺口判断太快。
- idea 过早下结论。
- 图谱不完整、证据链不稳。

同时也更适合后续做 benchmark，因为每一步都有可记录对象：
- 找到了哪些种子
- 扩展了哪些引用
- 哪些论文被接受 / 拒绝
- 哪些 gap 有证据
- 哪些 idea 通过 novelty check

