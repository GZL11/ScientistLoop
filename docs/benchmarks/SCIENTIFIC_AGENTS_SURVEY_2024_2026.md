# 2024-2026 科研智能体论文与系统调研

> 目标：梳理近一两年科研智能体（scientific agents / AI scientist / AI co-scientist）的主要方向、代表系统、能力边界和研究缺口，服务后续 Famou Scientist 的文献调研、热点聚类、缺口定位和评测设计。

## 1. 总览

当前科研智能体方向可以粗分为 7 个热点簇：

1. 文献发现与综述智能体：找论文、读论文、用引用支撑回答，减少引用幻觉。
2. 假设生成 / AI Co-Scientist：生成、辩论、演化和排序科学假设。
3. 端到端 AI Scientist：从 idea 到实验、代码、结果、写论文、评审的闭环。
4. 实验执行 / Lab-in-the-loop / Robotic Scientist：连接真实实验设备、湿实验或人类实验员。
5. 数据分析 / 建模 / Algorithm Discovery Agent：面向有明确评估器的算法、模型、数据分析任务。
6. 评测与基准：评估科研智能体的检索、编码、实验、审计和发现能力。
7. 综述 / 框架化研究：总结 agentic science 的能力版图、风险和未来方向。

一个初步判断是：现有系统要么擅长找文献，要么擅长生成假设，要么擅长跑代码，但很少有系统能把“完整文献地图 -> 子领域聚类 -> 缺口证据链 -> 可验证研究计划 -> 实验闭环”做成可审计、可复现的一条链。

更关键的是，Famou Scientist 需要关注的不是“这些系统属于哪一类”，而是它们如何完成三件事：

1. 如何检索论文：从用户问题、种子论文或研究目标出发，怎样召回、去重、验证和组织文献。
2. 如何识别缺口：怎样判断已有工作覆盖了什么、没有覆盖什么，以及这个判断是否有证据链。
3. 如何提出有价值 idea：怎样从缺口生成候选方向，并用新颖性、可行性、证据充分性和可验证性筛掉弱 idea。

## 2. 核心机制对比：检索、缺口、idea

| 系统 / 论文 | 论文检索如何做 | 缺口方向如何识别 | 有价值 idea 如何提出 / 筛选 | 对我们的启发 |
|---|---|---|---|---|
| PaperQA2 | 面向问题检索论文和段落，强调带引用回答；核心是从论文库中找能支撑答案的证据，而不是开放式生成研究方向 | 主要通过回答中的证据、矛盾和缺失信息暴露知识空白；不是专门的缺口挖掘系统 | 不直接负责提出新研究 idea，更偏“给定问题 -> 找证据 -> 合成答案” | 适合作为“证据回答层”：每个结论必须能回溯到论文段落和引用 |
| OpenScholar | 使用大规模开放论文库和检索增强模型，从开放论文中检索相关段落并生成带引用回答 | 通过多篇文献综合回答问题，可以发现已有答案不一致或证据不足的区域；但缺口识别不是显式主目标 | 不主要做 idea generation；重点是提高科学问答正确性和引用准确性 | 适合参考它的“检索库 + 引用支撑 + 自反馈生成”结构，但我们还需要额外的缺口层 |
| AutoResearchBench | 把文献发现拆成 Deep Research 和 Wide Research 任务，评估 agent 是否能找全关键论文 | 它本身是评测，不是提出缺口的方法；但可以用来暴露系统在召回、覆盖和相关性上的缺陷 | 不生成 idea；用于判断 agent 的文献发现能力是否可靠 | 我们需要类似 benchmark：测关键论文召回、不相关过滤、子领域覆盖，而不是只看回答是否流畅 |
| Google AI co-scientist | 给定科学家提供的研究目标和上下文，检索公开论文和数据库作为背景证据；检索服务于假设生成 | 通过多 agent 生成、反思、批评和排序，寻找已有知识中的未解释机制、潜在靶点或药物重定位机会 | 采用 generate、debate、evolve：多个 agent 生成假设，互相批评，锦标赛式排序和演化；专家/实验再验证 | 对我们最有价值的是“多候选 idea + 批评 + 排序”，但必须建立在可追溯文献证据上 |
| ResearchAgent | 从一篇核心论文出发，沿学术图谱扩展相关论文，并引入跨论文共享概念构成的知识库 | 通过核心论文、相关论文和跨领域概念连接，寻找可迁移的方法、未解决问题和跨领域组合机会 | 自动定义新问题、提出方法和实验，再由多个 ReviewingAgents 迭代评审和修改 | 很适合我们的“种子论文 -> 相关图谱 -> 跨领域 idea”模式；缺点是对图谱质量依赖强 |
| The AI Scientist | 主要面向机器学习任务，检索/读取已有研究作为 idea 生成和论文写作背景；核心不在系统性文献检索 | 缺口更多来自已有模板、研究主题和自动实验空间，而不是严格的领域地图 | 自动生成 idea、写代码、跑实验、写论文，再用自动 reviewer 评估 | 可以参考端到端实验闭环，但不应照搬到文献调研阶段；它的缺口识别不够可审计 |
| Agent Laboratory | 接受人类给定研究 idea，流程分为 literature review、experimentation、report writing，并允许用户每阶段反馈 | 缺口主要在 literature review 阶段由 agent 总结已有工作后推导；人类反馈显著提升质量 | 从用户 idea 出发细化实验和报告，不是完全从零发现方向；每阶段可由用户纠偏 | 说明“人类确认关口”很重要：文献综述、实验计划、报告写作不应自动一路推进 |
| ScientistOne | 在 literature review、solution discovery、paper writing 全流程维护 Chain-of-Evidence，要求论断、引用、分数、方法都可追溯 | 缺口和方案发现必须绑定证据链；同时用 CoE Audit 检查引用、分数、规范违反、方法-代码一致性 | 通过 solution discovery 生成候选方案，但每个方案必须被证据链约束，并经审计检查 | 这是最值得我们吸收的机制：缺口和 idea 不能只是一段自然语言，要有证据链和审计项 |
| Robin / FutureHouse | 集成文献检索 agent 和数据分析 agent，围绕疾病/药物问题检索背景、生成假设、提出实验 | 通过文献背景 + 实验结果迭代发现新的治疗策略和机制，例如从 dAMD 到 phagocytosis、ROCK inhibitor、ABCA1 | 生成治疗假设、实验计划、分析结果，再根据实验反馈更新假设 | 说明高价值 idea 往往来自“文献 + 数据 + 实验反馈”的闭环；单靠文献总结很难验证价值 |
| SciAgents | 用本体知识图谱和多智能体推理组织材料科学知识，检索更像图谱查询和概念连接 | 缺口来自知识图谱中概念、材料、性质、机制之间的潜在连接 | 通过图推理和多 agent 协作生成可解释假设 | 对结构化学科有参考价值：如果领域可构图，缺口可以是图中的未连接边或弱连接区域 |
| Coscientist / ChemCrow | 检索论文、设备文档和化学数据库，并调用领域工具完成实验设计或合成规划 | 缺口更多来自任务目标和实验可行性，而不是通用文献地图 | 结合工具规划实验步骤，真实实验结果用于验证 | 对我们主要启发是“工具验证”：idea 最终要落到可执行实验或可运行评估器 |

## 3. 机制归纳：从论文检索到有价值 idea

### 3.1 论文检索不是单次搜索，而是证据构建

这些系统里，检索大致有四种范式：

1. 问题驱动检索：PaperQA2、OpenScholar。输入是科学问题，输出是带引用证据的回答。
2. 种子论文扩展：ResearchAgent。从核心论文出发，沿相关论文、引用图和共享概念扩展。
3. 目标驱动检索：Google AI co-scientist、Robin。输入是研究目标或疾病/机制目标，检索服务于假设生成。
4. 流程阶段检索：Agent Laboratory、The AI Scientist。文献检索只是完整科研流程的第一阶段。

对我们来说，文献调研不能只返回论文列表，应该至少保存：

- 查询词和检索源。
- 命中的论文、段落和元数据。
- 被保留 / 被拒绝的理由。
- 每篇论文支持了哪个结论、反驳了哪个结论、对应哪个子领域。
- 哪些关键问题仍然没有足够证据。

### 3.2 缺口识别需要从“总结式缺口”升级为“证据式缺口”

很多 agent 容易写出看似合理的缺口，例如“现有方法缺乏泛化性”或“缺少系统评测”，但这类说法如果没有证据链，价值很低。

更可靠的缺口应该包含：

| 字段 | 含义 |
|---|---|
| gap_statement | 缺口的具体表述 |
| covered_by_prior_work | 已有工作已经覆盖到哪里 |
| missing_or_weak_part | 仍缺什么，或者哪里证据弱 |
| supporting_papers | 支撑这个缺口判断的论文 |
| possible_counterexamples | 可能已经解决该问题的反例论文 |
| gap_type | 子领域内部缺口 / 子领域之间缺口 / 方法缺口 / 评测缺口 / 数据缺口 / 工程落地缺口 |
| confidence | 高 / 中 / 低，取决于证据覆盖和反例检查 |

ScientistOne 的 Chain-of-Evidence 对这里最关键：缺口不是一句总结，而是可审计对象。

### 3.3 有价值 idea 不是直接生成，而是候选池 + 批评 + 排序

Google AI co-scientist、ResearchAgent 和 ScientistOne 的共同点是：idea 不是一次性生成一个最终答案，而是先生成多个候选，再通过批评、评审、排序、演化或证据审计筛选。

一个更适合我们的 idea 对象应该包含：

| 字段 | 含义 |
|---|---|
| idea | 研究想法 |
| source_gap | 来自哪个缺口 |
| evidence_chain | 支撑该 idea 的论文和数据证据 |
| novelty_check | 与已有工作的区别 |
| feasibility | 是否能实验、是否有数据、是否有代码或评估器 |
| risk | 可能失败在哪里 |
| validation_plan | 如何验证 |
| expected_contribution | 如果成功，贡献是什么 |
| reviewer_objections | 模拟 reviewer 可能如何质疑 |
| priority_score | 综合新颖性、重要性、可行性、证据强度后的排序 |

这比“给我 5 个 idea”更慢，但更接近真实科研。

## 4. 代表系统与论文

| 类别 | 代表系统 / 论文 | 年份 | 核心能力 | 主要局限 |
|---|---:|---:|---|---|
| 文献发现与综述 | PaperQA2 | 2024 | 文献检索、基于引用的问答、矛盾检测 | 依赖检索召回；更偏问答，不直接构建完整领域地图 |
| 文献发现与综述 | OpenScholar | 2024 | 基于开放论文库的科学问答，带引用证据 | 问答导向强，缺口聚类和研究规划能力有限 |
| 文献发现评测 | AutoResearchBench | 2026 | Deep Research / Wide Research 文献发现评测 | 暴露检索能力短板，但不直接提供完整系统方案 |
| 假设生成 | Google AI co-scientist | 2025 | 多智能体生成、辩论、演化假设 | 假设新颖性和可验证性仍依赖专家评估 |
| 假设生成 | SciAgents | 2024 | 本体知识图谱 + 多智能体推理 | 领域知识工程重，泛化成本高 |
| 端到端 | The AI Scientist | 2024 | 自动 idea、实验、论文写作、评审 | 研究深度和新颖性判断有限 |
| 端到端 | Agent Laboratory | 2025 | LLM agents 作为研究助理，覆盖研究流程 | 更像流程自动化，质量控制仍依赖外部审查 |
| 端到端 / 审计 | ScientistOne | 2026 | Chain-of-Evidence，贯穿综述、发现、写作和审计 | 新系统，实际泛化效果仍需更多验证 |
| 端到端 / 生物医学 | Robin / FutureHouse | 2025 | 文献、假设、实验设计、数据分析，用于 dAMD 药物重定位 | 湿实验仍有人在环，领域化较强 |
| 实验执行 | Coscientist | 2023/2024 | 读设备文档、写控制代码、操作自动化化学平台 | 实验室自动化成本高，安全和泛化边界明显 |
| 化学工具 Agent | ChemCrow | 2023 | LLM + 化学工具，支持 synthesis / drug / materials | 工具和领域绑定强 |
| 数据 / 算法发现 | AlphaEvolve | 2025 | LLM + evolutionary search 发现算法 | 适合有明确评估器的问题 |
| 评测 | ScienceAgentBench | 2024 | 从真实论文抽取数据驱动发现任务，要求生成可运行 Python | 主要测编码 / 数据驱动任务，不覆盖完整文献地图 |
| 评测 | ML Research Benchmark | 2024 | ML research / competition-like tasks | 偏 ML 实验与指标，不覆盖跨领域科研全过程 |

## 5. 热点簇详解

### 5.1 文献发现与综述智能体

这一类最贴近 Famou Scientist 当前要优化的“文献调研与搜集”。核心问题不是能不能总结一篇论文，而是能否高召回、高精度地找到关键论文，并把证据组织成可信的领域地图。

代表工作：

- PaperQA2：面向 scientific literature search 和基于引用的回答，强调减少幻觉，并支持矛盾检测。
- OpenScholar：基于大规模开放论文库做科学问答，回答需要引用支撑。
- AutoResearchBench：专门评估 scientific literature discovery，区分 Deep Research 和 Wide Research。
- FutureHouse Falcon / Owl / Crow：面向科学家的不同检索和问答智能体，例如深度文献综述、prior-art 查询、通用科学问答。

主要进展：

- 从普通 RAG 摘要走向基于引用的综合归纳。
- 开始强调矛盾检测、论断验证和文献发现评测。
- 系统开始针对“有没有人做过 X”“这个方向有哪些关键工作”这类真实科研问题优化。

主要缺口：

- 召回仍然弱，尤其是模糊题名、跨领域关键词、冷门论文、公司系统名和机制名。
- 很多系统能总结已找到的论文，但不能证明没有漏掉关键论文。
- 对缺口的判断常常缺少证据链。
- 缺少“子领域聚类 -> 每个子领域进展 -> 子领域内缺口 -> 子领域之间缺口”的结构化输出。

### 5.2 假设生成 / AI Co-Scientist

这一类系统的目标是帮助科学家生成、辩论、改进和排序假设，而不是完全替代科学家写论文。

代表工作：

- Google AI co-scientist：基于 Gemini 2.0 的多智能体系统，给定研究目标后生成假设，通过辩论、批评、锦标演化提升质量，在 biomedical 场景验证。
- SciAgents：结合本体知识图谱和多智能体推理，用于材料发现。
- AstroAgents：从质谱数据和文献生成 astrobiology 假设。

主要进展：

- 从单次 idea 生成变成多智能体讨论和演化。
- 开始用测试时计算提升假设质量。
- 在生物医学、材料、天体生物学等领域出现真实案例。

主要缺口：

- 假设新颖性很难自动判断。
- 多数系统需要专家事后确认。
- 从“合理假设”到“可执行验证计划”之间仍有断层。
- 缺少对假设背后文献证据和反证的系统追踪。

### 5.3 端到端 AI Scientist

这一类追求完整科研闭环：idea 生成、实验设计、代码实现、运行实验、分析结果、写论文、自动评审。

代表工作：

- The AI Scientist：Sakana AI 提出的端到端 ML research agent。
- Agent Laboratory：LLM agents as research assistants，覆盖文献、实验、写作等流程。
- ScientistOne：提出 Chain-of-Evidence，把证据链贯穿文献综述、方案发现和论文写作。
- Robin：FutureHouse 的生物医学 research agent，用于 dAMD 药物重定位。
- Aleks：面向 plant science 的数据驱动科研 agent。

主要进展：

- 端到端流程已经可以跑通。
- 开始出现自动评审、自动写论文和自动实验迭代。
- ScientistOne 这类工作开始把“审计”作为一等能力，而不只是最终产出论文。

主要缺口：

- 流程能跑通不等于研究有价值。
- 容易出现伪造引用、不可复现实验分数、方法与代码不一致。
- 自动新颖性判断仍然弱。
- 需要类似 Chain-of-Evidence / CoE Audit 的机制来审计每个论断、分数、引用和方法-代码一致性。

### 5.4 实验执行 / Lab-in-the-loop / Robotic Scientist

这类系统尝试把智能体接入真实实验世界，尤其是化学、生物和材料方向。

代表工作：

- Coscientist：读硬件文档、写控制代码、操作自动化化学实验平台。
- ChemCrow：LLM 结合化学工具做 synthesis、drug discovery 和 materials 任务。
- Robin：人类执行湿实验，智能体负责假设、实验设计和结果分析。

主要进展：

- 智能体不再只停留在文本和代码层面，而是开始连接实验设备和真实实验数据。
- 化学和生物医学方向最活跃，因为工具、数据库、实验流程相对明确。

主要缺口：

- 真正闭环湿实验自动化成本高。
- 安全、合规和可控性要求高。
- 多数系统仍是 lab-in-the-loop，不是完全自动实验室。
- 实验失败后的自修复、异常归因和下一步实验规划仍弱。

### 5.5 数据分析 / 建模 / Algorithm Discovery Agent

这类系统适合有明确评估器的问题，例如算法优化、机器学习任务、数据分析流程。

代表工作：

- AlphaEvolve：LLM 生成算法变体，进化搜索选择更优方案。
- AI Co-Scientist for Ranking：面向搜索排序研究的 idea generation、代码实现和 GPU job scheduling。
- ERA / Empirical Research Assistant：偏自动构建和测试 computational models。

主要进展：

- 当任务有清晰指标 / 评估器时，智能体可以快速迭代。
- LLM 负责生成候选，程序化评估器负责筛选，形成强闭环。

主要缺口：

- 适合有明确评价函数的问题，不适合开放式科学问题。
- 容易优化基准，而不是产生真实科学洞见。
- 对实验设计合理性、因果解释和科学价值的判断仍弱。

### 5.6 评测与基准

评测方向正在快速增长，因为“科研智能体到底会不会科研”不能只看 demo。

代表工作：

- ScienceAgentBench：从真实同行评审论文中抽取数据驱动发现任务，要求智能体生成可运行 Python。
- ML Research Benchmark：评估 ML research / competition-like tasks。
- AutoResearchBench：评估文献发现能力。
- ScientistOne CoE Audit：审计分数验证、规范违反、引用验证、方法-代码一致性。

主要进展：

- 评测开始覆盖文献发现、代码执行、实验复现和审计。
- 从最终答案基准逐渐转向过程审计。

主要缺口：

- 现有基准分裂：检索、编码、实验、审计通常分开测。
- 新颖性、缺口质量、科学价值仍难自动打分。
- 很多评测只看最终答案，不审计证据链。

### 5.7 综述 / 框架化研究

这一类工作开始给 agentic science 画地图。

代表：

- From AI for Science to Agentic Science
- Agentic AI for Scientific Discovery
- From Automation to Autonomy
- How Far Are AI Scientists from Changing the World?
- Autonomous Agents for Scientific Discovery

共同观点：

- 科研智能体正在从工具增强和问答助手走向更自主的智能体。
- 可靠性、验证、新颖性、实验闭环、安全和治理是核心瓶颈。
- 高质量科研智能体需要把文献、假设、实验、写作和审计连成闭环。

## 6. 对 Famou Scientist 的启发

### 6.1 文献调研能力应该服务“领域地图”，不只是论文列表

我们的目标不是简单返回 20 篇论文，而是形成：

1. 领域核心问题。
2. 子方向聚类。
3. 每个子方向的代表论文和技术路线。
4. 每个子方向的进展脉络。
5. 每个子方向内部缺口。
6. 子方向之间的连接和空白。
7. 可验证的研究机会。

这意味着文献检索的输出应该从平铺列表升级成结构化地图。

### 6.2 检索应该是种子扩展，而不是一次查询

一次泛搜容易漏 Google AI co-scientist、ScientistOne、FutureHouse 这类系统名。更好的检索流程应该是：

1. 用宽泛查询找综述 / 基准 / 奠基系统。
2. 从综述 / 基准中抽系统名和任务名。
3. 对系统名逐个定向检索。
4. 反查 related work、引用和被引用。
5. 合并去重后再聚类。

### 6.3 缺口定位必须绑定证据链

缺口不能只是智能体的自然语言判断。每个缺口至少要记录：

- 支撑该 gap 的论文证据。
- 已有方法覆盖到了哪里。
- 哪些问题明确未解决。
- 是否有反例论文已经解决该 gap。
- gap 是子领域内部 gap，还是子领域之间的连接 gap。

ScientistOne 的 Chain-of-Evidence 和 CoE Audit 很适合作为参考。

### 6.4 评测需要覆盖检索、聚类、缺口和证据

后续如果做 benchmark，不能只测“有没有找到某篇论文”。更应该测：

- 关键论文召回率。
- 不相关论文过滤率。
- 子领域聚类质量。
- 每个子领域代表论文覆盖率。
- 缺口是否真实、具体、可验证。
- 缺口是否有引用 / 证据支撑。
- 是否识别已有工作已经解决的问题。

### 6.5 建议产品流程

面向“全面了解领域、聚类热点、定位缺口、提出有价值 idea”的任务，建议 Famou Scientist 使用下面的固定流程：

1. 范围确认：确认领域边界、时间范围、应用场景、用户目标和可接受深度。
2. 种子检索：先找综述、基准、代表系统、近期高影响论文。
3. 种子扩展：从引用、被引用、相关工作、数据集、方法名、系统名继续扩展。
4. 候选验证：每篇候选论文必须验证标题、作者、年份、来源和相关性。
5. 子领域聚类：按问题、方法、数据、任务、应用场景聚类，而不是只按关键词聚类。
6. 进展链梳理：每个子领域整理“早期代表 -> 近期突破 -> 当前瓶颈”。
7. 缺口对象化：每个缺口都绑定证据、反例检查和置信度。
8. idea 候选生成：每个 idea 必须来自某个缺口，并说明为什么现在可做。
9. idea 批评排序：从新颖性、重要性、可行性、验证成本、潜在贡献排序。
10. 用户确认：进入深读、实验设计或写作前，必须让用户确认方向。

## 7. 建议优先深挖的论文

第一优先级：直接影响文献调研能力。

- PaperQA2: High accuracy retrieval-augmented generation for answering scientific questions
- OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs
- AutoResearchBench: A Benchmark for Scientific Literature Discovery
- ScientistOne: Towards Human-Level Autonomous Research via Chain-of-Evidence

第二优先级：影响假设生成和缺口发现。

- Towards an AI co-scientist
- SciAgents: Automating scientific discovery through multi-agent intelligent graph reasoning
- AstroAgents

第三优先级：端到端科研流程参考。

- The AI Scientist
- Agent Laboratory
- Robin
- Coscientist

第四优先级：评测设计参考。

- ScienceAgentBench
- ML Research Benchmark
- CoE Audit in ScientistOne

## 8. 参考链接

- The AI Scientist: https://arxiv.org/abs/2408.06292
- Agent Laboratory: https://arxiv.org/abs/2501.04227
- Towards an AI co-scientist: https://arxiv.org/abs/2502.18864
- ScientistOne: https://arxiv.org/abs/2605.26340
- PaperQA2: https://arxiv.org/abs/2409.13740
- OpenScholar: https://arxiv.org/abs/2411.14199
- AutoResearchBench: https://arxiv.org/abs/2604.25256
- ScienceAgentBench: https://arxiv.org/abs/2410.05080
- ML Research Benchmark: https://arxiv.org/abs/2410.22553
- ChemCrow: https://arxiv.org/abs/2304.05376
- Coscientist: https://www.nature.com/articles/s41586-023-06792-0
- SciAgents: https://arxiv.org/abs/2409.05556
- AstroAgents: https://arxiv.org/abs/2503.23170
- Robin: https://arxiv.org/abs/2505.13400
- AlphaEvolve white paper: https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/AlphaEvolve.pdf
- AI Co-Scientist for Ranking: https://arxiv.org/abs/2603.22376
- ResearchAgent: https://arxiv.org/abs/2404.07738
- From AI for Science to Agentic Science: https://arxiv.org/abs/2508.14111
- Agentic AI for Scientific Discovery: https://arxiv.org/abs/2503.08979
- From Automation to Autonomy: https://arxiv.org/abs/2505.13259
- How Far Are AI Scientists from Changing the World?: https://arxiv.org/abs/2507.23276
