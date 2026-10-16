# AutoResearchBench 与 ResearcherBench 说明

> 目的：把两个最相关的“深度调研 / 文献发现”bench 单独拎出来，方便后续给 Famou Scientist 选评测基准。

## 1. 一句话区分

- **AutoResearchBench**：测“**能不能把关键论文找全、找准**”。
- **ResearcherBench**：测“**能不能基于文献做出有洞察、且被引用支撑的研究分析**”。

前者偏检索链，后者偏调研总结链。

## 2. 快速对照

| 项目 | AutoResearchBench | ResearcherBench |
|---|---|---|
| 论文名 | AutoResearchBench: Benchmarking AI Agents on Complex Scientific Literature Discovery | ResearcherBench: Evaluating Deep AI Research Systems on the Frontiers of Scientific Inquiry |
| arXiv ID | 2604.25256 | 2507.16280 |
| 首发时间 | 2026-04-28 | 2025-07-22 |
| 目标 | 科学文献发现 | 前沿科研调研与综合 |
| 核心任务 | Deep Research / Wide Research | Technical Details / Literature Review / Open Consulting |
| 主要评测 | Accuracy / IoU | Rubric Coverage / Faithfulness / Groundedness |
| 适合测什么 | 召回、相关性、覆盖率、引用扩展 | 洞察质量、证据支撑、引用准确性 |

来源：
- AutoResearchBench: https://github.com/CherYou/AutoResearchBench
- AutoResearchBench 页面: https://cheryou.github.io/autoresearchbench.github.io/
- ResearcherBench: https://github.com/GAIR-NLP/ResearcherBench
- ResearcherBench 页面: https://researcherbench.github.io/

## 3. AutoResearchBench

### 3.1 它是什么

AutoResearchBench 是一个专门面向 **autonomous scientific literature discovery** 的 benchmark。  
它不是普通网页搜索 benchmark，而是把“查科学论文”当成一个复杂研究任务来评。

它强调三件事：

1. **研究导向**：要求理解科学概念，而不是只匹配关键词。
2. **文献导向**：要求利用论文中的细粒度信息。
3. **开放式**：可行答案数目不固定，需要持续 reasoning 和搜索。

### 3.2 任务类型

AutoResearchBench 有两个互补任务：

#### A. Deep Research

给定一个目标论文，要求 agent 通过多轮 probing 逐步把它找出来。

这类题更像：
- 先看到一批弱线索
- 再根据线索继续追
- 最后定位到唯一目标论文

它主要测：
- 线索利用能力
- 多跳检索能力
- 目标论文定位能力

#### B. Wide Research

给定条件，要求 agent 尽可能完整地收集满足条件的一组论文。

这类题更像：
- 找某个方向的代表作
- 找满足某类条件的论文集合
- 还要尽量少漏、少错

它主要测：
- 召回率
- 覆盖率
- 过滤能力
- 集合完整性

### 3.3 数据规模

官方页面给出的规模大致是：

- **1000+ questions**
- **195 research topics**
- **2 task paradigms**
- **50,000+ papers covered**

这说明它不是单点论文查找，而是一个较大规模的科学文献发现基准。

### 3.4 评测方法

AutoResearchBench 的评测比较直接。

#### Deep Research

评测指标是 **Accuracy**：
- agent 是否最终找到目标论文
- 找到记对，没找到记错

#### Wide Research

评测指标是 **IoU**（交并比）：
- 预测论文集合
- 标准答案论文集合
- 计算二者重叠程度

这个设计很适合测“有没有把相关论文找全”，而不只是“答得像不像”。

### 3.5 公开结果

公开结果里，强模型在这个 benchmark 上也很低：

- Deep Research 约 **9.39% Accuracy**
- Wide Research 约 **9.31% IoU**

这说明它确实在压“文献发现”这件事，而不是简单网页问答。

### 3.6 对我们的意义

它最适合评我们这几类能力：

1. seed paper 能否锁定正确
2. 前向 / 后向引用能否扩展到位
3. 同类论文能否补全
4. 无关论文能否过滤掉
5. 文献图谱能否覆盖核心 cluster

也就是说，AutoResearchBench 很适合评我们新加的：
- `seed discovery`
- `citation expansion`
- `paper recall`
- `relevance filtering`

### 3.7 局限

- 更偏“找论文”。
- 不直接评“这些论文归纳得好不好”。
- 不直接评“gap 判断准不准”。

所以它不能单独代表完整的 literature research 能力。

---

## 4. ResearcherBench

### 4.1 它是什么

ResearcherBench 评的是 **Deep AI Research Systems (DARS)**，也就是深度研究系统，而不是普通 retrieval agent。

它关心的问题不是“有没有搜到论文”，而是：

- 回答有没有洞察
- 引用是否真支撑论断
- 能否处理前沿科学问题

### 4.2 数据集

官方数据大致是：

- **65 个研究问题**
- 来自真实科研场景
- 覆盖 **35 个 AI subjects**
- 分成 3 类：
  - Technical Details
  - Literature Review
  - Open Consulting

这说明它更像“前沿科研问答 / 调研”benchmark。

### 4.3 评测框架

ResearcherBench 有两个主评测：

#### A. Rubric Assessment

这是洞察质量评测。

流程是：
1. 专家给每个问题设计 rubric
2. 每个 rubric item 有权重
3. 模型回答是否覆盖这些关键 insight
4. 汇总成 weighted coverage score

它衡量的是：
- 是否抓到了重点
- 是否覆盖了专家认为真正重要的 insight

#### B. Factual Assessment

这是证据和引用评测。

流程是：
1. 从回答里抽取 factual claims
2. 找这些 claims 对应的 citation URL
3. 抓 citation 内容
4. 判断 citation 是否真的支持 claim

输出两个关键分数：

- **Faithfulness**：引用是否真的支持对应论断
- **Groundedness**：回答整体有多少内容被引用覆盖

### 4.4 这个设计的价值

ResearcherBench 的强项是把“研究性回答”拆成两层：

1. **懂不懂**
2. **证据真不真**

这点对我们很重要，因为很多调研系统的问题不是不会写，而是：
- 结论太快
- 引用不稳
- 证据链不完整

### 4.5 公开结果

官方页面里，表现较强的系统包括：
- OpenAI Deep Research
- Gemini Deep Research
- Claude Research

它们在 rubric coverage 上比较高，但 groundedness / faithfulness 不一定同步很高。  
这说明“有洞察”不等于“引用严谨”。

### 4.6 对我们的意义

ResearcherBench 很适合评我们这几类输出：

1. `field_map.md`
2. `gap_map.yaml`
3. `idea_bank.yaml`
4. `claim_cards.jsonl`

尤其适合看：
- 是否真的覆盖关键 insight
- 是否把 gap 说准了
- 是否每个结论都有引用支撑

### 4.7 局限

- 更偏 AI 前沿问题，不是通用全学科。
- 更偏“调研 / 综合输出”，不是纯检索。
- 不直接测 citation expansion 的召回。

所以它不能替代 AutoResearchBench。

---

## 5. 怎么搭配使用

如果我们要验证这次文献调研改造，建议这么配：

### 第一层：AutoResearchBench

测检索链：
- seed 是否找对
- 引用扩展是否完整
- 关键论文是否漏掉
- 无关论文是否混入

### 第二层：ResearcherBench

测综合链：
- 论述是否有洞察
- gap 是否证据化
- 引用是否真的支撑结论
- 调研是否覆盖关键问题

### 实操上

可以按下面的顺序测：

1. 先跑 AutoResearchBench，看检索和召回
2. 再跑 ResearcherBench，看调研总结和证据支撑
3. 最后再接我们自己的 novelty / gap / idea gate

这样最能对齐我们现在的目标：
- 找全
- 讲准
- 说得有证据
- 不乱下结论

