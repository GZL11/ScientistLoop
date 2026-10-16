# 与 SciModelingBench 评测方式相近的 Benchmark

本文整理与 SciModelingBench 在“读取公开数据或候选空间、产生/筛选科学候选、交给 oracle 或隐藏标签评测”这一协议上相近的 benchmark。它们并不都是同构任务：有些要求生成新候选，有些只允许从有限候选池排序，有些允许在查询预算内反复调用 oracle，还有一些主要评测监督模型的预测相关性。

本文把“排行榜”和“结果表”严格区分：只有 benchmark 官方维护、可按统一协议提交或比较结果的页面才标为“公开排行榜”；论文中的实验表、GitHub README 中的历史结果以及模型仓库中的示例结果，统一标为“论文/仓库结果表”，不把它们称为 leaderboard。链接和榜单状态以 2026-08-24 核验为准；数据集、代码和榜单若有版本，应以对应版本的 release 或 commit 为准。

## 对比口径

可以把这类 benchmark 抽象为：

```text
公开观测/设计空间/候选池
    -> 模型或 Agent 生成、筛选或排序候选
    -> 隐藏 oracle、预计算真实值或独立测试集
    -> 标量分数
```

本文中的“候选”是有领域语义的对象，例如分子、蛋白序列、材料结构、神经网络架构或控制策略；这不等于 benchmark 会检查自然语言推理、因果机制解释或实验可复现性。

## 总表

| Benchmark | 论文首次公开 | 领域 | 是否允许生成池外新候选 | 是否只能筛选/排序 | 是否有多轮 oracle 反馈 | 主要评测方式 | 公开排行榜/结果页 | 与 SciModelingBench 的关系 |
|---|---|---|---|---|---|---|---|---|---|
| [Design-Bench](https://github.com/rail-berkeley/design-bench) | 2022-02-17，论文 [arXiv:2202.08450](https://arxiv.org/abs/2202.08450) | 离线模型驱动设计，含生物序列、材料、控制等任务 | 是；输出合法的新设计 | 否；不是固定候选池提交 | 原始协议主要是离线 oracle/数据集评估，不是统一在线逐轮协议 | trusted oracle 对提交设计计算目标，常用 top-k、均值或归一化指标 | 无统一官方在线排行榜；见[论文结果](https://arxiv.org/abs/2202.08450)和[仓库](https://github.com/rail-berkeley/design-bench) | SciModelingBench 黑盒设计任务的直接上游和协议参照 |
| [PMO](https://github.com/wenhao-gao/mol_opt) | 2022-06-22，论文 [arXiv:2206.12411](https://arxiv.org/abs/2206.12411) | 分子黑盒优化 | 是；输出新的分子 SMILES | 否；目标是在预算内发现高分分子 | 是；按查询或轮次获得性质 oracle 反馈 | 固定查询预算下比较最高分、均值、达到阈值的速度和样本效率 | 无统一在线排行榜；见[仓库结果表](https://github.com/wenhao-gao/mol_opt#results)和论文 | 接近黑盒优化；更强调多轮查询预算，不是候选池排序 |
| [GuacaMol](https://github.com/BenevolentAI/guacamol) | 2018-11-22，论文 [arXiv:1811.09621](https://arxiv.org/abs/1811.09621) | 从头分子生成 | 是；输出分子 SMILES 集合 | 否；不是从固定池中挑选 | 通常不是逐轮真实实验反馈，而是调用固定性质函数/评分函数 | 有效性、唯一性、新颖性、目标达成率、分布匹配和多目标分数 | 无持续在线排行榜；见[仓库 benchmark results](https://github.com/BenevolentAI/guacamol#benchmark-results) | 都把生成对象交给程序化 evaluator；GuacaMol 更偏生成质量和分布匹配 |
| [Matbench Discovery](https://matbench-discovery.materialsproject.org/) | 2023-08-28，论文 [arXiv:2308.14920](https://arxiv.org/abs/2308.14920) | 稳定晶体材料发现 | 通常否；提交模型对固定候选晶体的预测，可据此排序 | 是筛选/排序的一部分，但主要是材料预测文件评测，不是 Agent 提交候选列表 | 否；通常一次性提交预测，参考值来自独立 DFT 数据 | 与 DFT 参考值比较，使用 F1、精确率、召回率、MAE 等发现指标 | [官方 leaderboard](https://matbench-discovery.materialsproject.org/) | 最接近有限候选池筛选；但通常评测材料模型，不是长程 Agent |
| [ProteinGym](https://github.com/OATML-Markslab/ProteinGym) | 2023，论文/项目资料见 [ProteinGym](https://proteingym.org/) | 蛋白突变适应度预测 | 否；预测固定测试突变的 fitness | 可以形成突变排序，但不是候选发现任务 | 否；固定 assay 测试集一次性评测 | 跨 assay 的 Spearman、Pearson、NDCG 等相关性/排序指标 | [官方 leaderboard](https://proteingym.org/leaderboard) | 与蛋白候选排序相近，但主要是预测模型 benchmark |
| [FLIP](https://github.com/dataforager/FLIP) | 2022，论文/项目说明见 [仓库](https://github.com/dataforager/FLIP) | 蛋白序列-功能/适应度预测 | 否；输出固定 held-out sequence 的 fitness 预测 | 可以用于排序，但不是固定批次候选提交 | 否；测试集标签在评测时一次性比较 | Spearman/Pearson、RMSE 等，关注分布外泛化 | 无统一官方在线排行榜；见[仓库](https://github.com/dataforager/FLIP) | 和 ProteinGym 类似，强调预测质量而不是候选生成循环 |
| [NAS-Bench-101](https://github.com/google-research/nasbench) / [NAS-Bench-201](https://github.com/D-X-Y/NAS-Bench-201) / [NAS-Bench-301](https://github.com/automl/nasbench301) | 2019-02-25 / 2020-01-02 / 2020-08-21；论文分别为 [101](https://arxiv.org/abs/1902.09635)、[201](https://arxiv.org/abs/2001.00326)、[301](https://arxiv.org/abs/2008.09777) | 神经网络架构搜索 | 是；搜索器可提出架构，也可预测架构性能 | 不是只能排序；搜索器通常按性能查询结果迭代选择 | 是；搜索过程中可查询表格或 surrogate，不是统一的最终一次提交协议 | 真实训练结果、表格查询或 surrogate 查询准确率/损失，同时评价搜索成本、regret 和排名相关性 | 无统一官方在线排行榜；各仓库主要提供数据、查询 API 和论文结果 | SciModelingBench 的 `cell_dag_nas` 使用相同的“架构候选 + 隐藏性能”思想，但提交契约更小 |
| [Therapeutics Data Commons](https://tdcommons.ai/) | 2021-02-18，论文 [arXiv:2102.09548](https://arxiv.org/abs/2102.09548) | 药物发现与开发数据任务集合 | 依子任务而定；预测任务否，生成任务是 | 部分任务可排序，但没有统一候选池协议 | 通常否；是标准数据集上的训练/测试评估，不是统一在线 oracle | ROC-AUC、PR-AUC、RMSE、MAE、Spearman 等 | 无统一官方 leaderboard；见[官网任务页](https://tdcommons.ai/overview/) | 是任务集合而非单一候选生成协议；DrugMatrix 类任务可借鉴其数据划分和排序评测 |

日期口径：优先采用论文在 arXiv 的首次公开日期；只有项目论文日期不明确时，写论文/项目首次公开年份，不把仓库最近一次 commit 日期误当发布日期。

### 如何读这张表

- “是否允许生成池外新候选”回答 Agent 能否提出固定集合之外的新对象；“是”并不等于 benchmark 评测完整的科学假设或实验方案。
- “是否只能筛选/排序”只在候选被预先固定时标为“是”；固定测试集预测虽然可以产生排序，但仍然是监督预测 benchmark，不等于候选池发现任务。
- “多轮 oracle”表示 Agent 或搜索器在运行中能否查询候选的性质/性能并据此继续搜索；一次性提交后由 evaluator 评分，不算多轮反馈。
- “公开排行榜/结果页”中的论文表和仓库结果只用于复现实验，不代表存在可持续提交、统一版本和统一评分的 leaderboard。当前明确的公开 leaderboard 是 Matbench Discovery 和 ProteinGym；ScienceFlow 的页面是公开成绩/项目页面，协议上不应与标准 leaderboard 混用。

## 2025-2026 年的新近基准

上一节的 benchmark 多数是 2018-2023 年建立的经典数据和协议。2025-2026 年的新工作明显转向两个方向：一是用更真实的物理/生物 oracle 评测候选发现，二是把 Agent 的中间状态、工具调用和最终文件放进可验证的长程环境。以下项目更接近当前要建设的下一代 loop。

| Benchmark / 项目 | 首次公开 | 输入与输出 | 评测方式 | 公开排行榜/结果页 | 与当前任务的关系 |
|---|---|---|---|---|
| [NMO Benchmark](https://arxiv.org/abs/2606.30170) | 2026-06-29 | 输入纳米技术分子设计空间和结构约束；输出分子候选 | 用量子模拟替代简单性质代理 oracle，检查结构约束和物理 fitness，并比较固定协议下的发现质量 | 无统一公开排行榜；见论文 | 这是近年与黑盒候选生成最同构的基准，适合借鉴“真实 oracle + 严格结构约束” |
| [AssayBench](https://arxiv.org/abs/2605.10876) | 2026-05-11 | 输入一个细胞 assay 和候选基因；输出该 assay 的基因排序 | 对 1,920 个 CRISPR screen 计算 adjusted nDCG，跨异质 assay 汇总 | 无统一公开排行榜；见论文 | 与候选池排序和 `global_ndcg` 高度相似，尤其适合借鉴跨任务归一化排名指标 |
| [VibeProteinBench](https://arxiv.org/abs/2605.10978) | 2026-05-09 | 输入自然语言蛋白设计意图；按任务子类输出识别结果、工程修改或新蛋白 sequence | 使用机制依据和多维 in-silico validation 检查生物合理性，分 recognition、engineering、generation 三阶段 | 无统一公开排行榜；见论文 | 与 `gfp` 的序列候选不同，它把自然语言接口和生成后的生物验证纳入协议 |
| [ChemCoTBench-V2](https://arxiv.org/abs/2606.03660) | 2026-06-02 | 输入化学问题或分子优化目标；输出最终分子以及模板化中间状态 | 用确定性化学规则、参考轨迹和可由 oracle 验证的状态约束检查最终答案、格式和逐步状态 | 无统一公开排行榜；见论文 | 对当前 loop 的最大启发是：在最终提交前增加可验证的中间状态，而不是只看最终分数 |
| [TxBench-PP](https://arxiv.org/abs/2606.19245) | 2026-06-17 | 输入真实小分子临床前药理 workflow snapshot 和文件；输出结构化药理结论 | 100 个 evaluation，使用确定性 grader；评估 MoA、PD、target engagement、安全性和转化疗效判断 | 无统一公开排行榜；见论文 | 与候选排序不完全同构，但非常接近 Terminal-Bench 式长程任务：最终 structured answer 由 verifier 判定 |
| [MDArena](https://arxiv.org/abs/2608.02642) | 2026-07-31 | 输入容器化分子动力学代码任务和项目文件；输出可运行的分析/模拟产物 | 50 个真实 MD workflow task，以 Strict-Pass@1、部分正确性和过程奖励评分 | 无统一公开排行榜；见论文 | 与 SciModelingBench 的科学候选输出不同，但直接参考 terminal agent 的容器、测试和最终 verifier 设计 |
| [SciDisco](https://arxiv.org/abs/2607.28990) | 2026-07-31 | 输入假设、数据集、隐藏证据图和分析环境；输出可验证的统计结论及分析轨迹 | 通过 DAG-grounded verifier 检查每一步是否产生可验证证据，并提供 turn-level credit | 无统一公开排行榜；见论文 | 最贴近“在线诊断 + RSI”：把科学结论拆成可验证中间证据，支持过程级反馈和训练信号 |
| [ScienceFlow](https://arxiv.org/abs/2608.14354) | 2026-08-14 | 输入科研问题、文献/数据和执行环境；输出研究产物和实验结果 | 长程 Agent loop 通过研究产物、实验执行和最终结果评估；具体协议需以项目发布版本为准 | [公开成绩页/项目网站](https://huawei-noah.github.io/noah-research/ScienceFlow/website/)，不等同于通用在线 leaderboard | 与当前 Famou loop 直接相关，可作为从候选优化扩展到完整科研 Agent 的近期参照，但不是单一候选池 benchmark |

### 这些新 benchmark 的共同变化

1. **oracle 更接近真实科学验证。** NMO 使用量子模拟，VibeProteinBench 使用结构和功能验证，AssayBench 使用真实 CRISPR screen 标签；这比只用简单 proxy property 更能防止 benchmark overfitting。
2. **从最终答案转向中间状态。** ChemCoTBench-V2 和 SciDisco 不只问最终答案是否正确，而是检查中间分子状态、证据节点、统计结论和约束是否成立。这正是当前 loop 引入 RSI 和在线诊断时需要补的能力。
3. **Agent benchmark 开始采用真实 workflow。** TxBench-PP 和 MDArena 让 Agent 操作文件、代码和工具，最后由确定性 grader 或严格测试判断成败；它们与 Terminal-Bench 的评测方式更接近，而不是传统的候选列表评分。
4. **排序指标仍然重要。** AssayBench 的 adjusted nDCG 说明新 benchmark 仍然大量使用“对候选集合排序，再看前部质量”的协议；区别在于它对不同 assay 的规模和难度做了更细的归一化。

### 对我们设计新 loop 的优先借鉴

若目标是 SciModelingBench 当前任务，优先参考 **NMO + AssayBench**：前者解决可信 oracle 和候选约束，后者解决候选池排序和跨任务指标。若目标是 Terminal-Bench 式长程科研任务，优先参考 **TxBench-PP + MDArena + SciDisco + ChemCoTBench-V2**：任务中间暴露文件级、状态级和证据级 verifier，最终再由严格 grader 汇总，而不是等待任务结束后才获得唯一反馈。

## 逐项说明

### 1. Design-Bench

- **官方链接**： [GitHub](https://github.com/rail-berkeley/design-bench)。SciModelingBench 当前任务仓库也明确使用 Design-Bench 任务套件和数据协议。
- **论文与发布日期**： [Design-Bench: Benchmarks for Data-Driven Offline Model-Based Optimization](https://arxiv.org/abs/2202.08450)，首次公开 2022-02-17。
- **意义**：评价模型能否仅依赖离线数据，在不能持续访问真实实验的情况下提出高质量设计。它覆盖序列、材料和控制等多种设计空间，核心是“离线 observations -> 新设计 -> oracle 评价”。
- **输入**：历史设计及其目标值、设计空间约束，有些任务还有离线数据集和预定义 oracle。
- **输出**：合法的新设计，例如 DNA/protein sequence、材料组成或控制策略。输出不是搜索算法源代码；算法只是产生设计的手段。
- **评测**：可信 oracle 对提交设计重新计算目标，常见指标包括 top-k 最优均值、批次均值、归一化提升和约束满足率。不同任务的候选数量和指标不同。
- **与 SciModelingBench**：这是最接近的参照。SciModelingBench 目前的 `tfbind8`、`tfbind10_pho4`、`cell_dag_nas` 等黑盒优化任务采用相同的基本思想；SciModelingBench 在 Agent 运行、公开视图、submission schema 和聚合反馈方面增加了自己的 harness。
- **关键差异**：Design-Bench 的原始使用方式通常是研究离线优化算法；SciModelingBench 把它封装成 Agent 最终写 `submission.json` 的任务，要求更明确地隔离 hidden evaluator。

### 2. PMO（Practical Molecular Optimization）

- **官方链接**： [GitHub](https://github.com/wenhao-gao/mol_opt)。
- **论文与发布日期**： [Sample Efficiency Matters: A Benchmark for Practical Molecular Optimization](https://arxiv.org/abs/2206.12411)，首次公开 2022-06-22。
- **意义**：研究分子黑盒优化在有限 oracle 查询预算下的实用效果。它特别关注算法需要花多少次性质评估，才能找到高分分子，而不是只看无限预算下的最终最好值。
- **输入**：分子表示、优化目标、历史查询和固定查询预算；oracle 可以是性质预测器或公开分子性质函数。
- **输出**：新分子，通常以 SMILES 表示；算法可以按轮次提出分子并获取 oracle 分数。
- **评测**：比较固定预算下的最高分、平均分、达到阈值的速度和样本效率，通常重复多个随机种子。这里的 oracle 反馈是逐查询或逐轮可见的，和 SciModelingBench 的一次最终隐藏评测不同。
- **与 SciModelingBench**：与 `tfbind8` 等黑盒优化任务都要求生成合法的新候选并由程序化目标评分。
- **关键差异**：PMO 是多轮主动查询过程，强调 query budget；SciModelingBench 当前 submission 通常是一次提交固定数量候选，Agent 不应假设能获得每个候选的隐藏分数。

### 3. GuacaMol

- **官方链接**： [GitHub](https://github.com/BenevolentAI/guacamol)。
- **论文与发布日期**： [GuacaMol: Benchmarking Models for De Novo Molecular Design](https://arxiv.org/abs/1811.09621)，首次公开 2018-11-22；期刊版本为 [JCIM DOI](https://doi.org/10.1021/acs.jcim.8b01156)。
- **意义**：为从头分子生成提供统一的程序化任务和评测器，避免只展示少数成功分子。它关注目标优化、分布学习、有效性、唯一性和新颖性。
- **输入**：目标函数、参考分子分布或 scaffold/性质约束。
- **输出**：一批合法分子 SMILES。
- **评测**：生成器提交分子后，由 evaluator 计算分子有效性、唯一性、新颖性、目标函数值、分布相似度或 multi-objective score。很多任务没有真实实验，而是调用固定计算性质函数。
- **与 SciModelingBench**：共同点是“最终候选文件由独立程序 evaluator 重新打分”，而不是以自然语言解释作为主分数。
- **关键差异**：GuacaMol 主要是分子生成质量 benchmark，通常允许生成任意合法分子；SciModelingBench 还包含候选池排序、架构和控制器任务，且提交数量与隐藏标签隔离更严格。

### 4. Matbench Discovery

- **官方链接**： [Matbench Discovery leaderboard](https://matbench-discovery.materialsproject.org/) 和 [GitHub](https://github.com/janosh/matbench-discovery)。
- **论文与发布日期**： [Matbench Discovery -- A framework to evaluate machine learning crystal stability predictions](https://arxiv.org/abs/2308.14920)，首次公开 2023-08-28。
- **意义**：评估机器学习模型能否从候选晶体中识别可能稳定、值得进一步计算或实验验证的材料。重点不是材料文本生成，而是高代价材料稳定性筛选。
- **输入**：候选晶体结构、模型对形成能/稳定性的预测；参考值来自 DFT 计算和稳定性判据。
- **输出**：每个候选的稳定性预测，或按预测稳定性排序的候选清单。
- **评测**：使用发现导向指标，如稳定/不稳定分类的 precision、recall、F1，以及形成能等回归误差；榜单通常按固定数据版本、结构集合和预测文件协议比较模型。
- **与 SciModelingBench**：与 `superconductor` 的候选池排序最接近，都是从一组候选中优先找出高价值对象，并由隐藏或独立参考值验证。
- **关键差异**：Matbench Discovery 主要评测一个材料模型的预测文件和泛化能力，通常不是让 Agent 在运行时做多轮搜索；SciModelingBench 的主分数更直接作用于提交列表的前 N 个候选。

### 5. ProteinGym

- **官方链接**： [ProteinGym](https://proteingym.org/) 和 [GitHub](https://github.com/OATML-Markslab/ProteinGym)。
- **论文与发布日期**：项目资料以 2023 年公开版本为基准，入口见 [ProteinGym 项目页](https://proteingym.org/)。不同数据版本可能有不同 release date，使用时应同时记录 commit、assay 版本和数据版本。
- **意义**：在大量真实蛋白 DMS assay 上比较蛋白语言模型、监督模型和零样本方法预测突变 fitness 的能力，特别关注跨蛋白、跨 assay 泛化。
- **输入**：野生型蛋白序列、突变序列或 mutation representation，以及 assay 上下文；训练时可见部分突变 fitness，测试标签隐藏。
- **输出**：测试突变的 fitness 预测分数，天然也形成突变排序。
- **评测**：常见为 Spearman/Pearson 相关性，也可以计算 NDCG、top-k 命中或按 assay 汇总的平均排名。它通常是固定测试集上的预测评测，而不是 Agent 提交一批候选后再拿到 hidden oracle。
- **与 SciModelingBench**：和 `gfp` 都涉及蛋白序列与隐藏功能值之间的排序/筛选关系；ProteinGym 的 assay 规模和跨任务泛化可用于设计更严格的数据切分。
- **关键差异**：ProteinGym 的基本输出是每个测试样本的预测值，SciModelingBench `gfp` 的基本输出是候选池中排好序的 sequence 列表。

### 6. FLIP

- **官方链接**： [GitHub](https://github.com/dataforager/FLIP)。
- **论文与发布日期**：FLIP 作为蛋白 fitness prediction benchmark 在 2022 年公开；项目入口见 [GitHub 仓库](https://github.com/dataforager/FLIP)。由于项目有多个数据和代码版本，建议在实验记录中同时写明仓库 commit 与数据 split。
- **意义**：评价蛋白序列模型在真实 fitness 数据上的预测质量，尤其强调 random、scaffold、按序列相似度或分布外切分下的泛化差异。
- **输入**：蛋白序列和训练集 fitness 标签；测试集序列不提供目标值。
- **输出**：测试序列的 fitness 预测。
- **评测**：以 Spearman/Pearson、RMSE 等指标衡量预测和真实 fitness 的一致性；由于 fitness 常用于筛选，相关性也可解释为候选排序能力。
- **与 SciModelingBench**：可为 `gfp` 等任务提供蛋白序列建模、切分和排序指标设计参考。
- **关键差异**：FLIP 更像标准监督学习评测，不要求输出固定大小的候选集，也不要求生成合法的新序列。

### 7. NAS-Bench-101、NAS-Bench-201 和 NAS-Bench-301

- **官方链接**： [NAS-Bench-101](https://github.com/google-research/nasbench)、[NAS-Bench-201](https://github.com/D-X-Y/NAS-Bench-201)、[NAS-Bench-301](https://github.com/automl/nasbench301)。
- **论文与发布日期**：
  - NAS-Bench-101：[arXiv:1902.09635](https://arxiv.org/abs/1902.09635)，2019-02-25；
  - NAS-Bench-201：[arXiv:2001.00326](https://arxiv.org/abs/2001.00326)，2020-01-02；
  - NAS-Bench-301：[arXiv:2008.09777](https://arxiv.org/abs/2008.09777)，2020-08-21。
- **意义**：把神经架构搜索从昂贵、难复现的现场训练转化为可复现的架构空间和性能查询问题，支持比较搜索算法、样本效率和搜索成本。
- **输入**：合法架构编码；部分设置还提供架构-性能历史观测。
- **输出**：架构候选，或对架构性能的预测/排序。
- **评测**：NAS-Bench-101/201 主要通过表格查询真实训练结果；NAS-Bench-301 使用 surrogate performance model。可报告最高验证/测试准确率、搜索过程 regret、rank correlation 和搜索成本。
- **与 SciModelingBench**：`cell_dag_nas` 直接采用“合法架构编码 -> 隐藏性能 -> top-k 质量”的核心结构，并且同样强调固定架构 grammar 和可信性能查询。
- **关键差异**：NAS-Bench 系列通常服务于 NAS 算法研究，允许搜索器反复查询性能表；SciModelingBench 只把公开 observations 和最终 submission 暴露给 Agent，最终验收固定数量架构。

### 8. Therapeutics Data Commons（TDC）

- **官方链接**： [TDC 官网](https://tdcommons.ai/)、[GitHub](https://github.com/mims-harvard/TDC)。
- **论文与发布日期**： [Therapeutics Data Commons: Machine Learning Datasets and Tasks for Drug Discovery and Development](https://arxiv.org/abs/2102.09548)，首次公开 2021-02-18。
- **意义**：提供药物发现与开发阶段的一组标准数据集、任务、划分和评价接口，覆盖 ADME、毒性、药物-靶点相互作用、分子生成和临床结果等。
- **输入**：依子任务可以是分子结构、蛋白序列、药物/靶点对、临床条件或历史实验样本。
- **输出**：分类/回归预测、药物-靶点配对分数，或候选排序；部分生成任务输出新分子。
- **评测**：分类通常用 ROC-AUC/PR-AUC，回归常用 RMSE/MAE，排序或关联任务可用 Spearman 等。TDC 是任务集合，不是单一 submission schema。
- **与 SciModelingBench**：DrugMatrix 的临床病理 endpoint 可以借鉴 TDC 的任务拆分、数据泄漏防护和标准指标；两者都适合将候选条件按隐藏目标排序。
- **关键差异**：TDC 主要是监督学习数据和任务平台，许多任务的模型输出是测试样本预测值，并不要求 Agent 生成固定数量候选，也不统一采用 `global_ndcg`。

## 与 SciModelingBench 的对应关系

| SciModelingBench 任务形态 | 最接近的参照 | 可借鉴的设计 |
|---|---|---|
| 黑盒生成新的 DNA sequence | Design-Bench、PMO、GuacaMol | 合法设计空间、oracle 隔离、查询/提交预算、top-k 与批次质量指标 |
| 黑盒生成新的 NAS architecture | NAS-Bench-101/201/301、Design-Bench | 固定 grammar、查表式可信 evaluator、搜索成本和 regret 记录 |
| 从材料候选池中排序 | Matbench Discovery | 候选池冻结、独立参考值、发现导向 precision/recall 与 top-N 指标 |
| 蛋白序列候选筛选 | ProteinGym、FLIP | 跨 assay/分布外切分、相关性与 top-k 排序并列报告 |
| 控制器候选排序 | Design-Bench 中的控制任务 | 固定策略表示、隐藏 rollout 或独立 evaluator、约束和稳定性检查 |
| DrugMatrix 条件排序 | TDC | 标准数据划分、任务级指标、避免 treatment 条件和标签泄漏 |

## 结论

1. **最接近 SciModelingBench 的不是单一 benchmark。** Design-Bench 提供离线黑盒设计的直接上游范式；Matbench Discovery 更接近候选池排序；PMO/GuacaMol 更接近“生成候选后调用 oracle”；ProteinGym/FLIP 和 TDC 更偏固定数据集上的预测与排序。
2. **核心差异是反馈协议。** PMO 等 benchmark 往往允许多轮逐查询反馈；ProteinGym、FLIP 和 TDC 通常一次性在隐藏测试集上评测；SciModelingBench 当前更接近“Agent 运行期间只看公开数据，最后提交一次候选列表，由 trusted evaluator 统一评分”。
3. **对长程 Agent loop 最有用的借鉴是 evaluator 设计。** 应冻结公开候选池和数据 revision，隔离隐藏目标，记录提交数量、候选合法性、查询/运行预算，并同时报告 top-k 质量、整体批次质量和排序质量。
4. **不要把预测 benchmark 的分数直接等同于科研发现能力。** 相关性高只说明模型能预测 held-out label；候选发现还需要检查候选是否真正进入合法设计空间、是否重复、是否满足约束，以及 top-N 候选在独立 oracle 上是否有效。
