# Agent 演化搜索方向 —— 专利与竞对全景

> 版本：2026-09-20 初版
> 范围：全球（CN / US / EP / WO），方向涵盖 **LLM + 组合优化、LLM + ML（AI4AI/AutoML）、AI4Science、RSI（自改进）**，
> 外加与我们正面重合的创业公司画像（专利 + 技术路线 + 融资）。
> 配套：`patents.csv`（专利清单，2012 条）。采集脚本与原始数据都在 `tooling/` 下，复跑办法见 §9。

---

## 0. 先说这份报告的可信边界

三件事必须先讲清楚，否则下面的数字会被误读。

| 项 | 情况 |
| --- | --- |
| **数据源** | 只用了**公开渠道**：Google Patents 公开检索接口、**WIPO PATENTSCOPE**、WIPO/CNIPA 官方发布、公开媒体报道。**没有** Derwent / incoPat / 智慧芽等付费库。 |
| **专利清单完整度** | **`patents.csv`：2012 条去重**（US 1083 / CN 412 / WO 356 / EP 65 / 其余 96）。PATENTSCOPE 链路 78/78 跑完；Google Patents 链路因出口 IP 反复限流只跑完 **48/78**，**CN 仍是欠采的**（详见 §9）。 |
| **必须双库交叉** | §3.1 的结论在初版里**是错的**，原因就是只用了 Google Patents —— 它的相关度排序把本方向最关键的一份文件（WO/2025/093772）排到了看不见的位置，而 PATENTSCOPE 把它排第 1。**任何"没人做"的结论，两个库都跑过才能下。** |
| **未读权利要求** | 本报告所有对"射程"的判断都基于**标题+摘要**，没有读到任何一份权利要求全文（Claims 页需 JSF POST，爬不到）。**摘要的射程通常远小于权利要求书**，§7 的白地结论因此只是初判。 |
| **18 个月公开期** | 2025 年之后申请的专利**大部分还没公开**。本方向最热的一批申请（2025H1 起）预计 2026H2–2027 才陆续可见。**现在检索到的"空白"，有相当一部分是"还没公开"而不是"没人做"。** |


本报告里凡是**具体专利号**，都来自 Google Patents / WIPO PATENTSCOPE 接口的原始返回，可直接核验；凡是**融资/估值**，都来自公开报道，且多源有出入时已标注。

---

## 1. 一句话结论

> **DeepMind 把"LLM 当算子 + 评估函数验证 + 演化搜索候选程序"这个核心机制申请了 PCT，2025-05-08 公开，优先权 2023-11-03，指定国包含中国。**
> **也就是说：核心层不是空的，是被 Google 从根上圈了。我们能打的只剩"让这套东西在真实规模下跑起来"的工程机制层。**

关键文献（本报告最重要的一条）：

| 项 | 内容 |
| --- | --- |
| **公开号** | **WO/2025/093772** |
| 标题 | SEARCHING THROUGH CANDIDATE COMPUTER PROGRAMS FOR PERFORMING A TASK USING A LANGUAGE MODEL NEURAL NETWORK |
| 申请人 | **GDM HOLDING LLC**（Google DeepMind 美国持股主体） |
| 发明人 | ROMERA-PAREDES Bernardino、**NOVIKOV Alexander**、BAREKATAIN Mohammadamin、BALOG Matej、MUDIGONDA Pawan Kumar、DUPONT Emilien、RODRIGUEZ RUIZ Francisco Jesus、FAWZI Alhussein |
| **优先权** | **US 63/596,229，2023-11-03**（临时申请） |
| PCT 申请 | PCT/EP2024/081072，国际申请日 2024-11-04 |
| 公开日 | **2025-05-08**（比 AlphaEvolve 官宣早 6 天） |
| IPC | **G06F 8/30**（源代码的创建/生成）、G06F 8/35 |
| 指定国 | **含 CN、US、JP、KR、IN、BR 等，基本全球** |
| 代理 | Fish & Richardson P.C. |

**摘要原文（决定性的一段）**：

> "…determining a final computer program for performing a task by **searching through a space of candidate computer programs**. That is, by starting with an initial computer program and using an **evolutionary search procedure that uses a pre-trained language model to generate new candidate computer programs** in conjunction with an **evaluation function to verify the quality** of the new candidate computer programs…"

发明人名单同时覆盖 **FunSearch（Nature 2023）的作者**和 **AlphaEvolve 的第一作者 Novikov** —— 这是一条把两代系统一起圈进去的母案。

**对我们的含义，三条：**

1. **"LLM 生成候选程序 → 评估函数打分 → 演化搜索"这个骨架已经不可能作为我们的独立权利要求。** 它的优先权早到 2023-11-03，早于我们 loop 的任何设计文档。FTO 上这是**第一顺位要读全文的文件**。
2. **但它圈的是"搜索候选程序"这件事本身，圈不住"怎么把搜索工程化"。** 我们 §7 的六条（队列租约、验证器冻结、多父带分数 DAG、GT 隔离、跨任务经验库、护栏 hook）**都不在这条摘要的射程内** —— 它们解决的是并发、可复现、防泄漏、防幻觉，不是"如何搜索"。这个判断在读到权利要求全文前只是初判。
3. **它指定了中国。** 意味着 Google 大概率会走中国国家阶段。我们在国内申请时，**审查员手里会有这份对比文件**。交底书必须从一开始就把区别特征写在"工程机制"上，不能写成"一种基于大模型的演化搜索方法"——那样必被这条打掉。

**次要但同方向的两条**（同一批检索命中）：

| 公开号 | 申请人 | 标题 | 公开日 |
| --- | --- | --- | --- |
| US20240273371A1 | Google LLC | Code-level neural architecture search using language models（EvoPrompting） | 2024-08-15（优先权 2023-02-02） |
| US20250147810A1 | DeepMind Technologies Limited | Scheduling jobs using scored computational resources and efficient scheduling algorithms | 2025-05-08 |
| US20250111147A1 / WO2025068771 / US20260260061A1 | Microsoft | Automatic language model (LM) input optimization using **textual gradients** | 2025-04-03 起 |

微软这一族是 **TextGrad 式的提示词自动优化**被专利化 —— 意味着"**用文本反馈自动改 prompt**"这条路也已经有人圈。我们 loop 里如果有 prompt 自优化的打算，这族要单独看。


---

## 2. 大盘：这个池子有多大、谁在里面

### 2.0 DeepMind / Google 在我们这条线上的专利墙

这不是零散布局，是**沿着自家论文一篇一篇往下申的**。按优先权排：

| # | 公开号 | 申请人 | 标题 | 优先权 / 公开 | 对应的公开工作 |
| --- | --- | --- | --- | --- | --- |
| 1 | US20240273371A1 | Google LLC | Code-level neural architecture search using language models | 优先权 **2023-02-02** | **EvoPrompting** |
| 2 | **WO/2025/068601**（EP4740141A1） | **GDM HOLDING LLC** | **EVOLVING PROMPTS FOR NEURAL NETWORKS** | 优先权 **2023-09-28** | **Promptbreeder** |
| 3 | **WO/2025/093772** | **GDM HOLDING LLC** | **Searching through candidate computer programs … using a language model neural network** | 优先权 **2023-11-03** | **FunSearch / AlphaEvolve** |
| 4 | US20250147810A1 | DeepMind | Scheduling jobs using scored computational resources and efficient scheduling algorithms | 公开 2025-05-08 | — |
| 5 | US20250322254A1 | DeepMind | Training a **population** of adversarial neural networks to improve a base neural network | 公开 2025-10-16 | 群体式训练 |
| 6 | **US20260140723A1** | Google LLC | **AUTOMATICALLY OPTIMIZING COMPUTER CODE AT SCALE USING GENERATIVE NEURAL NETWORKS** | 公开 **2026-05-21** | AlphaEvolve 规模化落地（Spanner / 编译器 / TPU） |
| 7 | **WO/2026/169816** | Google LLC | **MULTI-AGENT SCIENTIFIC RESEARCH SYSTEM** | 公开 **2026-08-13** | **AI Co-Scientist** |

**#2 的细节值得单列**（摘要原文）：

> "An **evolutionary process** is used to **evolve prompts** that increasingly improve the extraction of knowledge from a machine learned model. … implementations of the described techniques are configured to use **parallel processing** in a way that … makes efficient use of these resources."

发明人 FERNANDO Chrisantha、BANARSE Dylan、MICHALEWSKI Henryk、OSINDERO Simon、ROCKTÄSCHEL Tim —— Promptbreeder 原班人马。IPC 落在 **G06N 3/086（遗传/演化计算）**。
注意它摘要里主动把技术效果写成"**并行处理、高效利用计算资源**"—— 这正是中国客体审查要的那句话（§8）。**这是可以直接抄的写法。**

> **整体判断**：从"演化提示词"(#2) → "演化候选程序"(#3) → "规模化代码优化"(#6) → "多智能体科研系统"(#7)，
> **我们 loop 的四层，Google 各申了一条。** 这不是白地问题，是**要在别人的墙里找缝**的问题。

### 2.1 GenAI 专利大盘

来自 WIPO《生成式人工智能专利态势报告》（2026 年版）与 2024 年版的对照：

| 指标 | 数值 |
| --- | --- |
| 2024 + 2025 两年新公开同族专利 | **超过此前 10 年总和** |
| 2025 年新公开同族 | 3.78 万项 |
| GenAI 占全部 AI 同族比例 | 4.2%（2017）→ **8.7%（2025）** |
| 中国 2024+2025 公开同族 | **>43,000 族**；2023–2025 CAGR **64%** |
| 前 10 申请人中中国占 | **6 家** |

**申请人排名（2024–2025 新增）**：软银（近 3000 族，第一）→ 腾讯 → 平安 → **百度** → 中科院 → 国家电网 →（第八）浙江大学；Alphabet / 微软 / IBM 亦在前十。

**2024 年版（数据截至 2023）**：腾讯 2074 / 平安 1564 / **百度 1234** / 中科院 607 / IBM 601 / 阿里 571 / 三星 468 / Alphabet 443 / 字节 418 / 微软 377。

> **对我们的直接含义**：百度在 GenAI/智能体专利上本来就是国内第一梯队（据《2025 人工智能创新与专利白皮书》，百度生成式 AI、智能体专利中国第一，大模型专利申请量全球第二）。也就是说**我们不缺申请通道和代理资源，缺的是把 loop 里的机制翻译成权利要求的人**。这是个内部协作问题，不是外部壁垒问题。

WIPO 同时明确点名：**多模态系统与 AI agents 是接下来专利申请会迅速增长的领域**。窗口正在关。

---

## 3. 五条技术轴上的专利现状

> ⚠️ 本节的"命中量"来自 `patents.csv`（2012 条去重）。**CN 侧仍欠采**（见 §9），所以凡涉及国内申请人的数量判断都不作数。

### 3.1 轴一：LLM + 演化搜索 / 算法发现（我们的正面）

**这一轴的结论在 2026-09-20 当天被推翻过一次，过程记在这里，因为它说明了检索方法的问题：**

> 只用 Google Patents 检索时，这一轴看起来是"核心机制稀疏、大厂走开源"。换到 WIPO PATENTSCOPE 检索 `EN_ALLTXT:("evolutionary search" AND "language model" AND "candidate")` 后，**第 1 条命中就是 WO/2025/093772（GDM HOLDING = Google DeepMind）**，直接覆盖核心机制。
> **教训：单一数据库的结论不能当结论。** Google Patents 的相关度排序把这条排在了看不见的位置，而 PATENTSCOPE 排第一。后续检索必须双库交叉。

**已核实的关键条目：**

| 公开号 | 申请人 | 标题 | 优先权 / 公开 |
| --- | --- | --- | --- |
| **WO/2025/093772** | **GDM HOLDING LLC**（Google DeepMind） | Searching through candidate computer programs for performing a task using a language model neural network | **优先权 2023-11-03**；公开 2025-05-08；**指定国含 CN** |
| US20240273371A1 | Google LLC | Code-level neural architecture search using language models（EvoPrompting） | 优先权 2023-02-02；公开 2024-08-15 |
| US20250147810A1 | DeepMind Technologies Limited | Scheduling jobs using scored computational resources and efficient scheduling algorithms | 公开 2025-05-08 |

WO/2025/093772 的完整著录项目与摘要见 **§1**。要点重复一次：**它把"起始程序 + LLM 生成新候选 + 评估函数验证质量 + 演化搜索"整条骨架写进了摘要，发明人覆盖 FunSearch 全班人马加 AlphaEvolve 第一作者。**

**同轴的其他发现：**

- FunSearch 的**代码**按 Apache-2.0、**材料**按 CC BY 4.0 开源，配 Nature 论文 —— 但**开源代码不等于放弃专利**。WO/2025/093772 正是这种"论文+开源做声誉、专利做排他"的标准组合打法。我在初版报告里把开源姿态误读成了没有专利布局，**这是本次最大的一处判断失误**。
- AlphaEvolve 本身是闭源白皮书，技术细节披露极少 —— 现在看，**闭源 + 同期公开 PCT 是一致的策略，不是巧合**。
- 窄短语 `"population of candidate programs"` 全库仅 **31 条**，主要是 2020 年前的遗传编程老专利（Alipay US11222179B2 / US11182678B2、Perceiver AI US20230334335A1、东芝 GB2465382A）。**这些是有用的先验技术** —— 它们可以用来打 WO/2025/093772 的创造性，也会用来打我们的。

> **修正后的判断**：这一轴**不是白地，是 Google 的主场**。我们在这一轴上只能做**从属层面的改进**，独立权利要求必须挪到 §7 的工程机制上。


### 3.2 轴二：LLM + 组合优化 / 启发式设计

学术侧极度拥挤（EoH / ReEvo / LLaMEA / HeurAgenix / RedAHD / CALM…，ICML/NeurIPS/KDD 都有），**专利侧极度稀疏**。

窄短语 `"automatic heuristic design"` 全库只有 **2 条**，且都是中国高校 2025 年申请：

| 公开号 | 申请人 | 标题 | 优先权日 |
| --- | --- | --- | --- |
| CN120832937B | 安徽大学 | 基于大语言模型的自动启发式算法规划方法 | 2025-09-18 |
| CN120450571B | 合肥工业大学 | 基于大语言模型的智能路径规划方法及系统 | 2025-07-11 |

**商业侧的在位者动作（比专利更值得看）：**
- **Gurobi**（2026-07）推出 **Intelligence Hub**：Modeler（业务问题 → 生产级模型，带迭代澄清需求/验证假设/生成验收测试）、Explainer（不可行性诊断 + 自然语言交互）、Gurobot，并开放 **Local MCP server**。
- **Quantagonia**（solver orchestration + AI 决策）已于 2025-08 被 **Strangeworks 收购** —— 这条赛道有退出先例。

> **判断**：**这是本报告发现的最明显的一块白地**。学术方案满天飞但没人申请，在位厂商刚开始做产品化。注意 Gurobi 的 Modeler 里那个"生成验收测试"环节 —— **跟我们的 verifier compiler 是同一个发明动机**。

### 3.3 轴三：AI4AI（AutoML / NAS / ML 工程 agent）

**这条轴是五条里被圈得最严实的**，因为 NAS 专利族从 2017 年就开始堆了，且全是 Google/DeepMind 系：

| 公开号 | 内容 |
| --- | --- |
| US20210295163A1 / WO2018081563A1 / EP3688673B1 | Neural architecture search —— controller 网络产出子网络架构序列 → 训练 → 评估 → 用性能指标更新 controller。**这是 NAS 的母专利族。** |
| US20190026639A1 | NAS for CNN（卷积 cell 复用以限制搜索空间） |
| US20220019869A1 → **US12131244B2**（2024-10 授权） | Hardware-optimized NAS |
| US20250265473A1 | NAS 的 fine-tuning（SubNet 采样 + 权重微调） |
| US12050991B1 | Connectomics-based NAS（GAN 生成生物网络 motif 约束搜索空间） |

⚠️ **这个母专利族的权利要求结构 —— "生成候选 → 训练 → 评估得到性能指标 → 用指标决定下一批候选" —— 在字面上跟任何"带评分回灌的候选搜索"都高度相似。做 FTO 时这是第一个要读全文的族。** 我们的区别点在于：候选是**代码/方案**而非网络架构，选择由 **agent 判断**而非 controller 梯度，且有**多父融合**。这些区别要在权利要求里写死。

创业公司侧：**Weco AI**（$8M seed，Golden Ventures 领投）把 AIDE 做成产品 —— 「把 ML 工程建模成代码空间的树搜索」，MLE-Bench / RE-Bench 上 SOTA（o1-preview + AIDE 让 medal rate 涨 5 倍；RE-Bench 上首个超过顶尖人类研究员的自主系统）。**规模小，但方向和我们的 search policy 正面对撞。**

### 3.4 轴四：AI4Science / 自驱动实验室

专利侧的主力不在"agent"而在**实验室自动化硬件 + 生成式分子/材料设计**（Insilico、Recursion、Schrödinger 这一批有厚专利墙，但那是化学/生物的墙，不是搜索算法的墙）。

**大厂的姿态同样偏开源**：
- 微软 **MatterGen**（Nature 2025）：源码 **MIT 许可**开源，训练/微调数据集一并放出；配 MatterSim 做稳定性筛选，接 Azure Quantum Elements。
- Google **AlphaFold/GNoME** 系亦以论文+数据为主。

**真正的竞争在产品化，不在专利**：Google 2026 已经把 **AlphaEvolve + Co-Scientist 作为 Gemini Enterprise 的 agent 商业化**，客户名单公开：BASF（供应链优化，规划/预测模型改善 >80%）、Klarna（ML 模型）、Daiichi Sankyo、Bayer Crop Science、美国能源部国家实验室（Genesis Mission）、Coolblue、ORNL（Frontier 超算）、Old Dominion University。内部 ROI 也公开了：AlphaEvolve 提出的电路设计已进入下一代 TPU 硅片、Spanner 写放大降低 20%、编译器优化让软件存储占用降近 9%。

I/O 2026 的 **Gemini for Science** 里两个工具直接对应我们的两条腿：
- **Computational Discovery**（ERA + AlphaEvolve）：**并行生成并打分数千个代码变体** ← 这就是我们的 loop
- **Hypothesis Generation**（Co-Scientist）：多 agent **"idea tournament"** 生成/辩论/评估假设 ← 这就是我们的 IdeaSpark + 演化图

> **判断**：AI4S 这条轴上，**我们的差异化不可能是"能做科研"，必须是"搜索机制本身"**。因为"能做科研"这件事，Google 已经在卖了。

### 3.5 轴五：RSI / 自演化 agent

**学术侧 2025–2026 井喷**：Darwin Gödel Machine（Sakana + UBC + Vector，2025-05，SWE-bench 20%→50%，Polyglot 14.2%→30.7%）、Gödel Agent、STOP、AgentSquare（模块化设计空间 + 演化算法搜组合）、GENOME（直接对 LoRA 参数做演化算子）、Self-Evolving Agents 综述（普林斯顿/清华/上交）。

**专利侧几乎为零**：窄短语 `"self-evolving agent"` 全库 **18 条**，且绝大多数是 **2010–2018 年的老专利**（东华理工 CN102663552B 动态工作流引擎、ETRI US20190171942A1 基于仿真的自演化 agent、KIST、Insight Enterprise JP2011258166A）。**LLM 时代唯一一条像样的是 CN120276712B（北京九章云极，2025-06-10，"实现智能体自进化的方法与系统"）。**

资本侧则在疯抢：Recursive（Richard Socher，传闻约 $4B）、Ricursive（$4B，AlphaChip 出身）、Prime Intellect（$130M @ $1B，Recursive Language Models + 生产环境持续改进）。

> **判断**：**这是第二块明显的白地**，而且窗口最短 —— 因为学术开源的速度远快于专利公开的速度。

---

## 4. 头部公司逐个看

| 公司 | 在这条路线上的资产 | 专利姿态 | 对我们的威胁 |
| --- | --- | --- | --- |
| **Google / DeepMind** | FunSearch、AlphaEvolve、Co-Scientist、EvoPrompting、NAS 母专利族、Gemini for Science | **混合**：NAS 走专利（族很厚）、FunSearch 走开源、AlphaEvolve 走闭源白皮书 | **最高**。技术、专利、产品、客户四条腿都在。 |
| **微软** | MatterGen / MatterSim（MIT 开源）、Azure Quantum Elements、TRAIN（医疗 AI 治理，与本方向无关） | 偏开源 | 中。材料侧强，算法演化侧未见布局。 |
| **NVIDIA** | Eureka（LLM 演化式 reward 设计，29 个 RL 环境上 83% 超人类专家）、2026 GPU kernel 优化 agent（含 DSL + speed-of-light 引导） | 未见 Eureka 相关专利 | 中，但**资本侧卡位极狠**：NVentures 同时投了 Periodic Labs、CuspAI、Orbital、Ricursive、Prime Intellect、Reflection AI。**它在买整条赛道。** |
| **IBM** | AutoML 老专利族 | 传统专利大户 | 中低 |
| **软银 / 腾讯 / 平安 / 百度** | GenAI 专利量前四 | 强专利导向 | 数量大但方向未必在演化搜索上 |
| **OpenAI / Anthropic** | Altman 公开说 2028-03 前做出"真正的自动化 AI 研究员" | 历史上极少申请专利 | 叙事威胁 > 专利威胁 |

---

## 5. 创业公司竞对

全部 24 家按**与我们的重合度**降序如下；投资人一列因为太长没放进表，需要时见 §6 与各家展开。

| 公司 | 地区 | 赛道 | 最新轮次 | 估值 | 技术路线 | 与我们的重合点 | 重合度 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sakana AI | 日本 | 演化搜索 / RSI / AI4AI | Series B $135M（2025-11，后扩至约 $200M） | $2.65B | Evolutionary Model Merge（Nature MI）、AI Scientist v1/v2、Darwin Gödel Machine（自改代码+谱系存档）、ShinkaEvolve（island + novelty 拒绝采样 + meta-agent 回灌）、ALE-Bench | 几乎逐条对应：种群/岛屿、算子、archive、meta 经验回灌、自动评测 | 极高 |
| Weco AI | 英国 | AI4AI / ML 工程 agent | Seed $8M | 未披露 | AIDE —— 把 ML 工程建模成「代码空间树搜索」，复用并精修高分解，MLE-Bench / RE-Bench SOTA | 与我们的 search policy + ExpBank 正面对标；规模小但方向最像 | 极高 |
| Google DeepMind | 美国 | 演化搜索 / AI4S（非创业公司） | — | — | FunSearch（2023，Apache-2.0 开源）→ AlphaEvolve（2025，program database + 演化框架）→ Co-Scientist；2026 在 Gemini Enterprise 商业化 | 同一条技术路线的源头与最强对手；已进入商业交付 | 极高 |
| 深势科技 DP Technology | 中国 | AI4S 全栈 | C 轮 >8 亿元（2025-12） | 未披露 | 玻尔平台（1.7 亿英文文献+2 亿专利+8000 万中文文献）、Uni-Lab OS（百余款仪器）、通用科研智能体 SciMaster、科学基座模型 Innovator | 国内最直接的对标；文献+计算+实验+智能体全栈 | 极高（国内） |
| 上海赛兰德 / 上交大 | 中国 | 通用科研智能体 | — | — | SciMaster：全学科「搜读算做写」闭环；称 6 小时≈资深理论物理博士 1–3 个月工作量 | 与 famou-scientist 的产品定位几乎一致 | 极高（国内） |
| Edison Scientific | 美国 | AI4S 文献/数据型 co-scientist | Seed $70M（2025-12） | 约 $250M | Kosmos：并行多 agent + 结构化问题空间世界模型，一次 run 出全引用报告（$200/run） | 与我们的文献检索 + 引用核验 + 报告产出直接重合 | 高 |
| 晶泰科技 XtalPi | 中国 | AI4S 药物/材料 | 港股上市 | — | AI+机器人+Multi-Agent 飞轮；Multi-Agent 当「智能项目经理」自主拆解调度；牵头国家科技重大专项「科学智能体平台」课题 | 多 agent 编排 + 自动实验，与我们的 loop 控制面重合 | 高（国内） |
| 深度原理 Deep Principle | 中国 | AI4Materials | A2 轮 | 未披露 | AI Scientist 平台 Mira：自主拆解科研任务、实验设计、执行、复盘、持续优化 | 与我们 loop 的任务分解+迭代同构 | 高（国内） |
| Periodic Labs | 美国 | AI4S 物理科学全栈 | Seed $300M（2025-09） | 约 $1.5B（种子轮）；中文源称后续升至约 $70 亿美元（待核实） | 闭环：AI 提假设 → 机器人做实验 → 谱仪分析 → 模型吃掉结果（含负例）；创始人来自 OpenAI（Liam Fedus）与 Google Brain（Cubuk，GNoME/A-Lab） | 搜索闭环同构，但落在物理实验而非算法 | 中高 |
| Lila Sciences | 美国 | AI4S 全栈自驱动实验室 | Series A（累计 $550M） | $1.3B（2025-10）；2026 传闻按 $8.5B 融资 | AI Science Factory + Lila Iris 推理模型；宣称已闭环数十万次实验 | 闭环搜索同构；壁垒押在自产实验数据 | 中高 |
| CuspAI | 英国 | AI 材料发现 | Series B $450M / €393.2M（2026-07） | $2.6B | MIRA 平台；开源 UMA（Meta）原子级 + 自研 kUPS 分子级 | 同为闭环发现，但不碰算法演化 | 中 |
| Harmonic | 美国 | 形式化数学 / 可验证推理 | Series C $120M（2025-11）；Nvidia 2026-01 加入 | $1.45B | Aristotle + Lean 4；IMO 金牌级、MiniF2F 90% | 「可验证 reward」这条腿跟我们的 verifier compiler 同源 | 中 |
| Axiom Math | 美国 | 形式化数学 | Series A $200M（2026-03） | >$1.6B | AxiomProver；2025-12 Putnam 12/12；称已破解 4 个未解问题 | 同上；证明搜索 = 带验证器的演化搜索 | 中 |
| Prime Intellect | 美国 | 开放超智能栈 / 持续学习 | Series A $130M（2026-07-08） | $1B | 分布式 RL + Recursive Language Models + 生产环境持续改进；称 6000 客户、>$100M ARR | 「模型在生产中持续自改进」与 RSI 叙事重合 | 中 |
| Reflection AI | 美国 | 代码研究 agent / 前沿模型 | $2.5B 轮（2026-03） | $27.5B | Asimov —— 面向大型代码库的代码理解 agent | agent harness 侧重合，不做演化搜索 | 中低 |
| Potato | 美国 | 实验执行层 / 可复现性 | Seed $4.5M（2025-04） | 未披露 | Tater co-scientist + Optimizer（多变量实验设计→Opentrons 脚本）；自称「可复现性公司」 | 把「设计→可执行」这一跳做成产品，对我们的 verifier 有参考 | 中低 |
| Isomorphic Labs | 英国 | AI 药物设计 | Series B $2.1B（2026-05） | 未披露（二级市场约 $3B，另有榜单估 $20B） | Drug Design Engine；称在蛋白-配体结构泛化基准上翻倍于 AlphaFold 3 | 垂直科学，不碰算法演化 | 低 |
| Chai Discovery | 美国 | 抗体/蛋白设计 | Series C $400M | $3.8B | Chai-1/Chai-2；纯授权模式（不自研管线） | 垂直科学 | 低 |
| EvolutionaryScale | 美国 | 蛋白基础模型 | 已被 Chan Zuckerberg Initiative 收购（2025-11） | — | ESM3 | 已退出独立赛道 | 低 |
| Gurobi | 美国 | LLM + 组合优化（在位厂商） | — | — | 2026-07 Intelligence Hub：Modeler（业务问题→生产级模型）、Explainer（不可行诊断）、Gurobot，并开 Local MCP server | LLM+CO 商业化的标杆形态 | 参考 |
| Quantagonia | 德国 | LLM + 组合优化 | 被 Strangeworks 收购（2025-08） | — | solver orchestration + AI 决策 | 已被整合，赛道有退出先例 | 参考 |
| Recursive（Richard Socher） | 美国 | RSI | 传闻融资中 | 约 $4B | 目标「无需人类反馈即可自改进的超智能」；8 位联创 | 叙事正面重合，技术细节未公开 | 待观察 |
| Ricursive | 美国 | RSI | — | $4B（launch 后两月） | 源自 AlphaChip（RL 做芯片布局，已用于四代 TPU） | 「用搜索做设计」同源。注意与 Recursive 是两家不同公司 | 待观察 |
| Radical Numerics | 美国 | 生物基础模型（早期曾以 Automated AI Research Factory 叙事出现） | Seed $50M（2026-06） | — | 2026-06 官宣定位为 general biological intelligence（DNA/RNA/蛋白）；早期 RISA-1「AI 造 AI」叙事与之不一致，需核实 | 叙事有冲突，暂不列为直接竞对 | 待核实 |

下面挑**重合度极高**的四家展开。

### 5.1 Sakana AI —— 最像我们的那家（日本，$2.65B）

技术谱系几乎和我们的 loop 逐条对应：

| Sakana | 我们 |
| --- | --- |
| Evolutionary Model Merge（Nature MI，参数空间 + 数据流空间双重演化） | — |
| **Darwin Gödel Machine**：自改代码 + **不断扩张的 agent 变体谱系存档** + 从存档里选节点做自修改 | **演化图 v2**（多父 DAG + 节点带分数 + 从前沿选节点） |
| **ShinkaEvolve**：**island 间知识迁移的存档**、novelty 拒绝采样、bandit 式 LLM 集成、**meta-agent 把洞见合成为建议追加进变异 prompt** | **Cross-task ExpBank**（经验回灌）+ **§5.2 四段自足索引表** |
| AI Scientist v1/v2（agentic tree search 自动出 workshop 级论文） | famou-scientist 主线 |
| ALE-Bench | NatureBench / ACGBenchmark / TBS |

融资：Series B $135M @ $2.65B（2025-11），2026 初扩至约 $200M，Google 2026-01 战略投资并合作推 Gemini 在日落地。Tracxn 记 $379M / PitchBook 记 $444M（口径不一）。日本最值钱独角兽。

> **要害**：**它把我们正在设计的东西开源了**。ShinkaEvolve 是 Apache-2.0，含实现细节和可视化工具。这对我们的专利工作是**双向影响** —— 它挡住了我们对这几个机制的独占，但也把它们变成了公共先验，我们只需要绕开它写更窄的权利要求。**§7 的白地判断已经把 ShinkaEvolve 的公开内容排除在外了。**

### 5.2 Weco AI —— 最小但最正面（英国，$8M）

AIDE：把 ML 工程建模成**代码空间的树搜索**，策略性复用和精修高分解，用算力换性能。产品形态是"你指给它代码和评测，它提改动、跑你的指标、留下赢的、循环"。用户场景明确包括 **agent harness、prompt、ML pipeline、GPU kernel**。

> **要害**：体量只有我们的一个零头，但**产品定义跟我们的 loop 几乎是同一句话**。融资少意味着它大概率没有专利预算 —— 这对我们是机会窗。

### 5.3 深势科技 —— 国内最直接对标（C 轮 >8 亿元）

玻尔平台（1.7 亿英文文献 + 2 亿专利 + 8000 万中文文献）、Uni-Lab OS（接入百余款实验仪器）、**通用科研智能体 SciMaster**、科学基座模型 Innovator（支持 20+ 科学模态、万级工具调度）、垂直 AI 科学家 PharmMaster/MatMaster。北京国资三支基金同时进（力度大于此前对智谱的支持）。

政策背书：2025-08 国务院《关于深入实施"人工智能+"行动的意见》把"人工智能+科学研究"放在**首位**。

### 5.4 晶泰科技 —— 唯一盈利的（港股上市）

2025 年营收翻三倍，港股首家盈利 AI4S 企业。飞轮是 **AI + 机器人 + Multi-Agent**，其中 **Multi-Agent 当「智能项目经理」自主拆解研发目标、调度全流程资源** —— 这跟我们 loop 的控制面是同一件事。牵头 2025 年度"新一代人工智能国家科技重大专项"中的**科学智能体平台**课题。

> **国内格局提示**：SciMaster（上海赛兰德/上交）宣称"6 小时成果≈资深理论物理博士 1–3 个月饱和工作量"。这类**对外口径**会直接影响我们汇报时的基准线 —— 建议我们自己的对外数字一律绑死可复跑的 benchmark，不做同类比喻。

---

## 6. 资本面：谁在买整条赛道

2025–2026 这条赛道的融资密度（单位：美元）：

| 公司 | 轮次 | 估值 |
| --- | --- | --- |
| Reflection AI | $2.5B（2026-03） | $27.5B |
| Isomorphic Labs | $2.1B（2026-05） | 未披露 |
| Lila Sciences | 累计 $550M | $1.3B → 传闻 $8.5B |
| CuspAI | $450M（2026-07） | $2.6B |
| Chai Discovery | $400M | $3.8B |
| Periodic Labs | $300M seed（2025-09） | ~$1.5B（后续传闻更高） |
| Axiom Math | $200M（2026-03） | >$1.6B |
| Prime Intellect | $130M（2026-07） | $1B |
| Harmonic | $120M（2025-11） | $1.45B |
| Edison Scientific | $70M（2025-12） | ~$250M |
| Orbital Industries | $50M（2026-05） | 未披露 |
| Weco AI | $8M | 未披露 |
| Potato | $4.5M（2025-04） | 未披露 |

**两个值得记的观察：**

1. **钱的分布和技术重合度是反比的**。跟我们技术上最像的两家（Sakana $2.65B、Weco $8M）都不是这个榜单的头部；头部的钱（Reflection、Isomorphic、Chai、CuspAI）全在**垂直科学/代码理解**，不在**通用演化搜索**。
2. **执行现实远落后于叙事**。公开报道明确指出：Lila 的实验室在近期探访时**基本是空的**、正在搬更大场地；Periodic 刚开始搭 SF 实验室，**先手工合成 + AI 预测指导，高通量机器人在路线图上**。PitchBook 也在质疑 AI 材料发现的 VC 回报路径。**这对我们是好消息 —— 窗口没有看上去那么窄。**

---

## 7. 我们手里有什么可专利的（白地）

> 下面每一条都做了同一件事：**从 loop 的代码/设计里挑出"只有真跑过大规模 run 才会遇到、且公开文献没写"的机制**。凡是 FunSearch / AlphaEvolve / DGM / ShinkaEvolve 已公开的，一律不列。

> ⚠️ **WO/2025/093772 出现后，本节的前提变了，必须按新前提读：**
>
> 1. **没有一条可以写成"一种基于大模型的演化搜索方法"。** 那个上位概念已经被 GDM 的母案占住（优先权 2023-11-03，指定国含 CN）。每一条的独立权利要求都必须把**主题词落在具体的工程机制上**（队列调度 / 验证器编译 / 图索引渲染 / 数据隔离），把演化搜索写成**应用环境**而不是发明点。
> 2. **本节的"白地"判断目前只基于 WO/2025/093772 的摘要**，没读到权利要求全文。摘要的射程通常远小于权利要求书。**在读到 claim 1 之前，下面每条的"白地"结论都只是初判**（取回路径见 §9）。
> 3. 好消息是：这六条解决的问题 —— 并发安全、可复现、防泄漏、防幻觉 —— **和"如何搜索"是正交的**。母案摘要里没有任何一个词触及它们。


### A. 队列租约式的配对改进派发（最强，建议优先）

**对应代码**：`famou_scientist/loop/search/policy.py` —— `PairwiseImproveSearchPolicy`

机制：在 Improve 回合，不是由调度器决定"继续精修还是换方案"，而是**同时把当前方案和队首新 Idea 交给 agent，让 agent 在 `refine / switch / fuse` 里选**；关键在于**队列侧的原子性处理**：

- 派发前对候选 Idea 走 `lease()` **租约**（带 owner_id + purpose），防止并发 Improve 回合抢同一条；
- agent 选 `refine` → `replay_tail()` **把没被采用的 Idea 原子地放回队尾**（不消费）；
- 选 `switch`/`fuse` → `finish_lease()` **正式消费**并挂 evidence_refs；
- agent 返回非法选择时**安全回退 refine**（`controller_fallback`），绝不误消费；
- **信息对等约束**：offered_idea 给完整 payload，current_idea 同样给完整方案描述 **外加它独有的实测结果**（current_score / current_level / last_run）—— 否则 agent 无法"比较二者上限"。

**为什么是白地**：公开的演化框架（FunSearch/AlphaEvolve/ShinkaEvolve）都是**调度器决定选择**（MAP-Elites / island / bandit），**没有把"选择权交给 LLM 且用租约保证并发安全"**这一层。这是分布式系统机制，不是算法机制，**恰好符合 CNIPA 对"技术方案"的客体要求**（见 §8）。

**可写的独立权利要求骨架**：一种多候选并发演化搜索的任务派发方法，其特征在于 —— 租用 + 信息对等载荷 + agent 决策 + 按决策原子化重放或消费 + 非法决策安全回退。

### B. 带分数的多父演化 DAG + 算子-父节点互校验

**对应设计**：`docs/design/EVOLUTION_GRAPH_V2_CN.md`

机制：节点带**海拔（实测分数）**、支持**多父**、算子词表（`innovate / exploit / cross`）**与 parents 互相校验**（选了 cross 就必须给 ≥2 个父，选了 exploit 必须给 1 个已出分的父）、宿主做**确定性图遍历**、agent 只做判断、渲染出**四段自足索引表**（每行不依赖其他行即可读懂，父节点用「标题+分数」称呼而非 hex id，「最该接着挖的」按父节点最好分降序）。

**为什么是白地**：DGM 有谱系存档但是**树**（单父）；ShinkaEvolve 有 island 存档但**节点不带我们这种多目标海拔**；两者都没有"**算子与父节点数量互为校验条件**"这个约束，也没有"**把图渲染成 agent 可单行读懂的表**"这个表示层发明。§1.4 的实测还给出了**支持性证据**：图的形状与结果相关（唯一 Match 来自深 3 层层上升的链；最差的是深度 1 出度 8 的纯星形）。

### C. 任务专属验证器的编译-冻结流水线

**对应设计**：`docs/design/TERMINAL_TASK_VERIFIER_COMPILER_DESIGN_CN.md`

机制：**把"生成验证器"和"每轮判定"彻底拆开** —— VerifierAgent 只负责产出一个 task-specific verifier；宿主做静态检查 + 同环境运行时探针 + **最多五次同 Session 编译修复** + **bundle 冻结**；此后每轮由系统**执行冻结的验证器**给确定性反馈，**不让 LLM 参与每轮判定**；正式成绩仍由官方 verifier 在 FinalAudit 给。

**为什么是白地**：这是**反 LLM-as-judge** 的设计。公开文献里 verifier 要么是人写死的，要么是 LLM judge。"LLM 写验证器 → 宿主编译冻结 → 之后纯确定性执行"这条**三段式**没见有人申请。而且 Gurobi Intelligence Hub 的 Modeler 里那个"生成验收测试"说明**在位厂商正在往这个方向走** —— 抢时间。

### D. 跨任务经验库的自排除 + 领域隔离 + 确定性兜底

**对应设计**：`docs/design/CROSS_TASK_EXPBANK_DESIGN_CN.md`

机制：任务结束时把公开演化轨迹压缩成一条可检索经验，按官方领域归档；下个任务读同领域历史时**排除当前 Run 防自读与重复传播**；写入**幂等、可并发、可恢复**；**总结 Agent 失败时仍保留调度器生成的确定性基础总结**；集群任务只拿共享经验快照，**不给其他 Run 的完整工作区 / GT / evaluator 私有内容**。

**为什么是白地**：ShinkaEvolve 的 meta-agent 只做"把洞见合成建议追加进 prompt"，**没有跨任务、没有领域隔离、没有自排除、没有确定性兜底**。后三条都是"真的跑多任务才会撞上的坑"。

### E. Agent 评测中的 GT 泄漏隔离

**对应**：NatureBench 链路上已落地的**可信侧源码快照排除、原始 evaluator 证据隔离、Agent 结果脱敏强校验**；以及按任务的评测配额与 GT 预算（`gt_budget`）。

**为什么是白地**：随着 agent benchmark 成为基础设施，"**如何在让 agent 拿到足够反馈的同时不泄漏 ground truth**"会变成刚需。目前公开方案基本是"把 GT 藏起来"，**没有人把"有限次 GT 预算 + 脱敏强校验 + 证据隔离"做成一套可主张的机制**。

### F. 强制触发的质量护栏 hook

**对应**：`assets/opencode/registry/plugins/guardrails/` —— 防编造数据、防幻觉引用，做成 **hook 强制触发，agent 跳不过**。

**为什么是白地**：这条相对弱（guardrail 专利很多），但**"护栏与 agent 编排解耦、以 hook 形式强制插入且 agent 无法绕过"**这个架构点，配合具体的科研场景（引用核验），仍有写窄的空间。**建议作为从属权利要求挂在 A 或 C 下面，不单独申请。**

### 优先级建议

> ⚠️ **采集跑完后（2012 条去重），上面 D 和 C 各被打到一条对比文件，必须降级：**
>
> | 我们的条目 | 打到它的对比文件 | 影响 |
> | --- | --- | --- |
> | **D（跨任务经验库）** | **US20260119479A1 / US20260259874A1，QpiAI India，"Multi-agent artificial intelligence system with **shared experience repository**"**（2026-04-30 / 2026-09-03） | **标题就撞名**。D 从 P2 降为**暂不单独申请**，先读这两篇的权利要求，确认"领域隔离+自排除+确定性兜底"是否还在射程外 |
> | **C（验证器编译冻结）** | **US20260127418A1 / WO/2026/102059，Deep Forest Sciences，"Recursive generative planning system with **verification modules** and user feedback"**（2026-05-07） | 名字近但机制未必同（它是"规划+验证模块"，我们是"生成验证器→编译冻结→纯确定性执行"）。**C 保持 P0，但交底书必须把"冻结"和"不让 LLM 参与每轮判定"写成区别特征** |
> | 相关 | US20260111363A1 / WO/2026/089797，微软，"Hierarchical multi-layer **action store** for agent-based task execution" | 技能库/动作库方向已被微软占，F 更没有单独申请价值 |
> | 相关 | US20260093459A1，NVIDIA，"**Iterative code generation and debugging pipeline** using language models" | 迭代生成-调试管线已被占，C 的"迭代修复"那一段不能当发明点 |
> | 相关 | US20250335773A1，Intuit，"LLM **prompt optimization with evolutionary algorithm and gradient descent**" | 提示词演化除 DeepMind 外还有第二家在圈 |

| 优先级 | 条目 | 理由 |
| --- | --- | --- |
| **P0** | **A（队列租约配对派发）** | **全库 2012 条里没有撞到任何对比文件**。最独特、最像"技术方案"、最容易过客体关 |
| **P0** | **C（验证器编译冻结）** | 仍然值得打，但要绕开 Deep Forest 和 NVIDIA 两条，区别特征写在"冻结 + 不参与每轮判定" |
| P1 | B（多父带分数 DAG + 算子互校验） | 未撞到对比文件；但 DGM/ShinkaEvolve 的存档会被拿来打创造性，权利要求要写窄 |
| P1 | E（GT 隔离 / 有限 GT 预算） | 未撞到对比文件，白地最干净；需先补实测数据 |
| ~~P2~~ **暂缓** | ~~D（跨任务经验库）~~ | **被 QpiAI 两篇正面撞上**，先读权利要求再决定 |
| ~~P2~~ **不单独申** | ~~F（guardrail hook）~~ | 微软 action store 已占相邻位置，挂从属即可 |


---

## 8. 中国申请要过的那道客体关

这一节是**写交底书之前必须看的**。

**依据文件**：
- 2023 版《专利审查指南》第二部分第九章新增 **第 6 节**"包含算法特征或商业规则和方法特征的发明专利申请审查相关规定"
- **2024-12-31 CNIPA《人工智能相关发明专利申请指引（试行）》**（六章：常见类型 / 发明人身份 / 客体标准 / 充分公开 / 创造性 / 伦理）
- 2025 年《专利审查指南》修改进一步把第 6 节标题改为"涉及人工智能、**大数据**等包含算法特征……"

**两条要害：**

1. **客体判据（指南 6.1.2）**：算法改进要能落到"**与计算机系统内部结构存在特定技术关联**"，解决"**如何提升硬件运算效率或执行效果**"的技术问题（减少数据存储量、减少数据传输量、提高硬件处理速度等）。
   > **对我们的含义**：**A（租约队列）和 C（验证器冻结）天然好写** —— 它们本来就是并发控制与执行流水线，直接指向"减少重复执行 / 提高吞吐 / 避免无效计算"。**B（图结构）最难写**，必须绑到"减少 agent 跨行 join 的上下文读取量 / 降低无效派发次数"这类可量化的系统效果上，不能只说"agent 决策更好"。

2. **不得割裂技术特征与算法特征**：审查应把权利要求记载的**所有内容作为一个整体**分析技术手段/技术问题/技术效果。
   > **对我们的含义**：交底书里必须把**实测数据**写进去（§1.4 的谱系审计、A/B 的 Δ 中位数与符号检验、图节点数对比），用来支撑"技术效果"。**我们恰好有这些数据，这是相对其他申请人的优势。**

3. **人工智能不具备发明人主体资格** —— 发明人署名必须是自然人。（我们的 loop 产出的方案如果要申请，署名必须是人。）

---

## 9. 采集链路状态与如何续跑

**两条链路，必须双库交叉** —— §3.1 那次翻案就是单库检索害的。

| 链路 | 脚本 | 状态 | 强项 / 弱项 |
| --- | --- | --- | --- |
| **WIPO PATENTSCOPE** | `tooling/harvest_patentscope.py` → `tooling/raw_ps/` | ✅ **78/78 跑完，1842 条** | 强：排序准（母案排第 1）、不限流、含 WO 族。弱：每页固定 10 条、**无优先权日**、**英文全文对 CN 覆盖不全** |
| **Google Patents** | `tooling/harvest.py` → `tooling/raw/` | ⚠️ **跑完 48/78**。出口 IP 间歇性限流，靠长退避一点点磨出来的 | 强：**CN 覆盖好**、一页 ~27 条、字段全（含优先权日）。弱：相关度排序会把关键文件排到看不见的位置；共享代理出口极易被封 |

**合并结果**：`patents.csv` **2012 条**（两库交叉去重，`sources` 列标明来源 —— 其中 113 条两库都有；`norm_key` 列是去掉 kind code 的归一化号）。

> **这份清单最大的缺口仍是 CN。** CN 412 条，但 Google 链路只跑完 48/78。
> 原因：PATENTSCOPE 英文全文对中国专利覆盖不全，而覆盖好的 Google Patents 链路被封。
> **国内竞对（百度/腾讯/阿里/华为/字节/深势/智谱/上海 AI Lab/之江）的专利必须补采后才能下结论**，
> 现在 `x09`–`x13`、`x23`–`x29` 这些按申请人的检索式在 CN 侧都是欠采的。
> 补采办法：换一个没被封的出口 IP 跑链路一，或者把检索式改写成中文投给 Google Patents。

**续跑：**

```bash
export ALL_PROXY=http://<user>:<pass>@<host>:<port>      # 换成你自己的代理，勿提交
export https_proxy=$ALL_PROXY http_proxy=$ALL_PROXY

# 链路一（Google Patents，注意 25s 间隔、单进程）
GP_SLEEP=25 python3 docs/patents/tooling/harvest.py --queries docs/patents/tooling/queries.json \
        --out docs/patents/tooling/raw --max-pages 2     # 已有结果自动跳过

# 链路二（PATENTSCOPE，不限流）
PS_SLEEP=4 python3 docs/patents/tooling/harvest_patentscope.py --queries docs/patents/tooling/queries.json \
        --out docs/patents/tooling/raw_ps --pages 3

# 合并（两个 raw 目录都传进去）
python3 docs/patents/tooling/build_csv.py --raw docs/patents/tooling/raw_ps --raw docs/patents/tooling/raw --out docs/patents/patents.csv
```

**怎么取回 WO/2025/093772 的权利要求全文**（§10 第 1 项）：

- 最省事：等 Google 解封后开 `https://patents.google.com/patent/WO2025093772A1/en`，claims 是纯文本，可直接复制。
- PATENTSCOPE 路径：`detail.jsf?docId=WO2025093772`，**Claims 页签走 JSF POST，爬不到**，需要人工在浏览器里点开。
- 或直接下 PCT 公开文本 PDF（PATENTSCOPE 详情页 Documents 页签）。
- 同族追踪：优先权 **US 63/596,229 (2023-11-03)**、PCT **PCT/EP2024/081072** —— 用这两个号去查 US 同族的审查历史（OA、已授权权利要求），那是最能看出"审查员认为哪些特征新"的材料。

`tooling/queries.json` 里是 **78 条窄短语检索式**，分六组：
`e*` LLM+演化/AI4AI · `r*` RSI · `s*` AI4Science · `c*` LLM+组合优化 · `a*` agent 基础设施 · `x*` 按申请人（DeepMind/Google/微软/IBM/NVIDIA/华为/百度/腾讯/阿里/字节/Sakana/OpenAI/Anthropic/Insilico/Recursion/Schrödinger/Isomorphic/Lila/Emerald/智谱/深势/月之暗面/深度求索/稀宇/上海人工智能实验室/之江实验室/西门子）。

> **踩过的坑，别重踩：**
> 1. **单库检索会得出错误结论**。同一个机制，Google Patents 排序里看不见，PATENTSCOPE 排第 1。**两个库都要跑。**
> 2. **宽布尔检索没用**。`("large language model") ("evolutionary" OR …) ("program" OR …)` 命中 1424 条，前 20 条全是噪声 —— `"program"` 被 `computer program product` 这种套话命中。**必须用窄短语。**
> 3. **`AB=` / `CL=` 字段限定语法 Google 这个接口不认**（返回 `total_num_results: null`）；PATENTSCOPE 用 `EN_ALLTXT:` / `PA:`。
> 4. **Google 别并发**。一个进程、25s 间隔，否则整站封出口 IP（本次就是并发了 3 个进程触发的，封了 1 小时以上）。


---

## 10. 建议的下一步

| # | 动作 | 谁 | 为什么现在做 |
| --- | --- | --- | --- |
| **1** | **取回 WO/2025/093772 的权利要求全文并精读 claim 1** | 需要能读权利要求的人（建议走法务/代理） | **最高优先级**。它决定了 §7 六条里哪几条真的在射程外。取回路径见 §9。 |
| 2 | 按"**工程机制做主题词、演化搜索做应用环境**"的写法，把 **A（队列租约）和 C（验证器冻结）** 写成交底书 | 我们 + 代理 | 这两条离母案摘要最远、客体最好过 |
| 3 | 查 WO/2025/093772 的**中国国家阶段是否已进入**、以及 US 同族的审查历史（OA / 已授权权利要求） | 法务/代理 | 指定国含 CN；审查历史会暴露审查员认为哪些特征是新的 |
| 4 | 读 **NAS 母专利族（US20210295163A1 / WO2018081563A1 / EP3688673B1）的 claim 1** | 同上 | "生成候选→训练→评估→用指标决定下一批"在字面上同样可能覆盖我们 |
| 5 | 把 §7 每条的**实测数据补齐**（Δ、p 值、节点数、耗时） | 我们 | CNIPA 要"技术效果"；§7-E 的秒数尚未实测 |
| 6 | 盯 Sakana 的开源节奏 + 微软 textual gradients 族 | 我们 | 前者压缩白地，后者圈了 prompt 自优化 |
| 7 | 核实两处冲突数据 | 谁跑这份报告 | Periodic Labs 最新估值（$1.5B vs 中文源 ~$70 亿）、Radical Numerics 定位（RSI vs 生物基础模型） |


---

## 附：主要信息源

**专利/政策**
- WIPO《生成式人工智能专利态势报告》（2026 版 / 2024 版）
- CNIPA《人工智能相关发明专利申请指引（试行）》（2024-12-31）、《专利审查指南》第二部分第九章第 6 节
- Google Patents 公开检索接口（本报告所有具体专利号的来源）

**技术**
- FunSearch（Nature 2023，Apache-2.0）· AlphaEvolve（arXiv:2506.13131）· Darwin Gödel Machine（arXiv:2505.22954）· ShinkaEvolve（arXiv:2509.19349）· AIDE（arXiv:2502.13138）· Eureka（arXiv:2310.12931）· EoH（ICML 2024）· LLaMEA（arXiv:2405.20132）· Self-Evolving Agents 综述（arXiv:2507.21046）

**公司/融资**
- TechCrunch、Bloomberg、Fortune、Forbes、SiliconANGLE、BusinessWire、PitchBook、Tracxn、Crunchbase
- Google Cloud Blog（AlphaEvolve 商业化）、Google DeepMind Blog、Gurobi BusinessWire（Intelligence Hub）
- 量子位、新浪财经、中国日报、上海交大新闻网（国内 AI4S）
