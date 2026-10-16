# 科学计算、科学推理与科学发现 Agent / Benchmark 调研

> 初始目标：整理“ML 预测 vs 数值计算、物理模拟、第一性原理、符号/解析方法”的科学计算 benchmark。  
> 扩展目标：补齐科学推理问答、文献/科研判断、数据驱动发现、假设与机理发现、端到端科学发现，以及承担这些任务的代表性 Agent。  
> 最后更新：2026-08-10。时间按论文首次公开或 benchmark 正式发布的较早者记录。  
> 相关总汇：[端到端科研智能体与评测基准调研](./END_TO_END_SCIENTIFIC_AGENTS_SURVEY_CN.md)；[AI4S Benchmark 总览](./BENCHMARKS_AI4S.md)。

## 1. 为什么这类 benchmark 和常见 AI4S benchmark 不一样

很多 AI4S benchmark 主要评测的是“给定科学数据，训练一个 ML 模型做预测”，例如材料性质预测、分子性质预测、蛋白质任务等。它们通常把 DFT、实验、模拟结果当作标签，但不一定显式比较 ML 方法与传统科学计算方法。

这里关注的是另一类问题：

1. **同一个科学问题可以由多类方法求解**：
   - ML 预测 / surrogate model；
   - 数值 PDE/ODE solver；
   - CFD、NWP、DFT、量子化学等领域模拟；
   - 符号回归、方程发现、解析近似；
   - hybrid / physics-informed 方法。
2. **评测不只看预测误差**，还应看：
   - 计算成本；
   - 泛化能力；
   - 物理一致性；
   - 稳定性；
   - 可解释性；
   - 是否能恢复科学规律。
3. **ground truth 往往来自高精度数值模拟、第一性原理计算或真实观测**，而不是普通标注数据。

因此，这类 benchmark 更适合回答：

> 对一个科学问题，什么时候应该用 ML，什么时候应该用数值计算，什么时候应该用可解释的数学模型，什么时候应该做混合建模？

---

## 2. 总览表

### 2.1 类型标签口径

后文每个 benchmark 可以同时带多个标签。这里的标签不是学科分类，而是说明“它到底在测什么能力”：

| 类型标签 | 含义 | 典型判断 |
|---|---|---|
| **SOTA / Leaderboard** | 有固定 metric、公开榜单或明确和 prior best / SOTA 对比 | 适合看模型或 Agent 是否超过已有最好结果 |
| **Prediction / Surrogate** | 给定结构、场、序列或数据，预测性质、能量、力、轨迹或标签 | 适合评 ML 能否近似昂贵计算或实验标签 |
| **Scientific Computing** | 直接比较 solver、数值方法、物理模拟或计算成本 | 适合评精度-成本-稳定性 |
| **Discovery** | 要恢复隐藏规律、提出候选、发现关系、机制或 insight | 适合评科学发现能力，但需区分已知再发现和开放发现 |
| **Optimization / Inverse Design** | 给定历史设计和分数，提出更优候选；常见于蛋白、分子、材料、结构设计 | 适合评候选搜索和样本效率，但通常不等于完整科研 Agent |
| **Simulation Loop** | Agent 在仿真环境里多轮 propose→evaluate→refine | 最接近 AInstein 这类“封闭仿真沙箱” |
| **Workflow** | Agent 调工具、跑代码、处理数据、生成 artifact | 适合评科研执行能力，不等于证明新发现 |
| **Reproduction** | 复现论文、仓库、实验结果或超过论文基线 | 适合评科研工程闭环和结果可靠性 |
| **QA / Research** | 问答、检索、综述、引用和科研判断 | 适合评知识、证据综合和 grounded answer |
| **Wet-lab Case** | 有真实实验、机器人或样品验证 | 证据最强，但通常不是统一可提交 benchmark |

### 2.2 方向总览

| 方向 | 类型标签 | 代表 benchmark | 传统科学方法 | ML / 数据驱动方法 | 核心评测问题 |
|---|---|---|---|---|---|
| PDE / 物理场预测 | Prediction / Surrogate；Scientific Computing；SOTA | PDEBench | 数值 PDE solver | FNO、U-Net、PINN、DeepONet 等 | ML 能否逼近或加速 PDE 求解？ |
| 科学计算求解器 | Scientific Computing；Workflow | SciMLBenchmarks.jl | ODE/PDE/SDE/DAE 数值求解器 | Neural ODE、PINN、UDE、surrogate | 精度-成本-稳定性如何权衡？ |
| 天气预报 | Prediction / Surrogate；SOTA | WeatherBench / WeatherBench 2 | 数值天气预报模型 | GraphCast、Pangu-Weather、FourCastNet 等 | ML 能否和物理天气模型同台比较？ |
| 流体力学 / CFD | Prediction / Surrogate；Scientific Computing | CFDBench、PDEBench 中 CFD-like 任务 | CFD solver | Neural Operator、GNN、Transformer 等 | ML surrogate 能否替代部分 CFD 计算？ |
| 材料 / 催化 | Prediction / Surrogate；SOTA；Discovery | Open Catalyst Project | DFT 结构弛豫、能量/力计算 | GNN、Equivariant GNN、ML 势函数 | ML 能否加速 DFT？ |
| 材料性质预测 | Prediction / Surrogate；SOTA | Matbench | DFT / 实验测量 | 图神经网络、descriptor + ML | ML 能否预测材料属性？ |
| 离线设计优化 / inverse design | Optimization / Inverse Design；Discovery | Design-Bench；Sci Modeling Bench / design-bench | 真实实验、仿真或 learned oracle | offline MBO、Bayesian optimization、生成模型、梯度优化 | 只用已有数据，能否提出更高分候选设计？ |
| 分子动力学 / 量子化学 | Prediction / Surrogate；Scientific Computing | QM9、MD17、rMD17、MD22 等 | DFT、量子化学、分子动力学 | SchNet、DimeNet、MACE、NequIP 等 | ML 势函数能否近似量子化学计算？ |
| 方程发现 / 符号回归 | Discovery；Scientific Computing | SRBench、SRBench++、LLM-SRBench | 符号回归、稀疏回归、数学建模 | 神经符号方法、LLM-based equation discovery | 能否恢复显式公式或科学规律？ |
| ODE / 动力系统发现 | Discovery；Scientific Computing | ODEBench、SINDy 系列任务、ODEFormer | 数值拟合、SINDy、稀疏辨识 | Neural ODE、Transformer、神经符号模型 | 能否从轨迹恢复 governing equations？ |
| 科研 terminal 工作流 | Workflow；Scientific Computing | Terminal-Bench Science | 科学代码、数值实验、数据处理、simulation pipeline | terminal-based AI agent | Agent 能否在真实终端环境中完成可验证科学任务？ |
| 科学推理问答 | QA / Research | FrontierScience、HLE、ChemBench、LAB-Bench、ControlBench、SciAgentGym | 专家知识、公式推导、科研判断、科学工具调用 | LLM / tool-using agent | 能否对专家级科学问题给出正确且有依据的答案？ |
| Deep Research / 科研判断 | QA / Research；Workflow | ScholarQABench、LitQA2、ResearcherBench、AutoResearchBench、LifeSciBench、AstaBench | 文献检索、跨文献综合、科研产物阅读 | search / code / multimodal agent | 能否找到证据、综合科研材料并作出可靠判断？ |
| 数据驱动发现 | Discovery；Workflow | DiscoveryBench、BLADE、BixBench、BAISBench | 统计分析、变量构造、数据变换、假设检验 | data-analysis agent | 能否从原始数据恢复论文级关系、分析路径或结论？ |
| 假设 / 机理发现 | Discovery | IdeaBench、MOOSE-Chem、Matter to Mechanism、AI Feynman、SRBench | 灵感检索、假设生成、方程恢复、机制解释 | hypothesis agent / symbolic discovery | 假设或方程是否具体、可验证，并能恢复已知关系或由实验支持？ |
| 科学代码 / 论文复现 | Workflow；Reproduction；SOTA | SciCode、SUPER、CORE-Bench、PaperBench、NatureBench、SciVisAgentBench | 科研代码、仓库执行、论文复现、SOTA 对齐、科学可视化 | coding / research agent | Agent 能否真实运行并复现已知科学结果？ |
| 端到端科学发现 | Discovery；Workflow；Simulation Loop | DiscoveryWorld、Curie、AstaBench E2E、ARC-Bench、ResearchClawBench、FIRE-Bench、MLR-Bench、MADE | 问题→方案→实现→实验→分析→报告 | autonomous research agent | Agent 能否形成可执行、可复现、有证据的完整发现闭环？ |
| 真实实验闭环 | Wet-lab Case；Discovery | Coscientist、Robin、ElementsClaw 等系统实证 | 机器人、仪器、湿实验、真实样品 | embodied / lab agent | 结论能否由真实测量复现？目前多为 case study，统一榜很少 |

---

## 3. PDE / 物理场预测类

### 3.1 PDEBench

- 论文：PDEBench: An Extensive Benchmark for Scientific Machine Learning，NeurIPS 2022 Datasets and Benchmarks Track  
- 论文页：https://proceedings.neurips.cc/paper_files/paper/2022/hash/0a9747136d411fb83f0cf81820d44afb-Abstract-Datasets_and_Benchmarks.html  
- GitHub：https://github.com/pdebench/PDEBench

#### 它评测什么

PDEBench 面向 time-dependent PDE simulation tasks。其特点是：

- 用经典数值模拟生成数据和参考解；
- 提供多类 PDE、多组初始条件、边界条件和物理参数；
- 同时提供 ML baseline，例如 FNO、U-Net、PINN、Gradient-Based Inverse Method；
- 支持 forward problem 和 inverse problem。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 初始条件、边界条件、PDE 参数、部分历史状态 |
| 输出 | 后续时间步的物理场，例如速度、压力、密度、标量场等 |
| 标准答案 | 由数值 PDE solver 生成的高精度模拟结果 |
| 典型任务 | Burgers、Advection、Diffusion-Reaction、Darcy Flow、Shallow Water、Compressible Navier-Stokes 等 |

#### 评测指标

PDEBench 不只看单一误差，而是希望更完整评估 SciML 模型，包括：

- normalized RMSE / relative error；
- 空间误差和时间误差；
- 频谱误差；
- 物理量相关误差；
- 不同 PDE 参数、初始条件、边界条件下的泛化能力。

#### 适合借鉴的点

PDEBench 很适合用来设计“科学问题求解 benchmark”的基本模板：

1. 固定科学问题和物理方程；
2. 固定初始条件、边界条件、参数分布；
3. 数值 solver 生成参考解；
4. 允许 ML、数值方法、混合方法参赛；
5. 同时比较精度、泛化和计算成本。

---

## 4. 科学计算求解器类

### 4.1 SciMLBenchmarks.jl

- GitHub：https://github.com/SciML/SciMLBenchmarks.jl  
- 结果页：https://docs.sciml.ai/SciMLBenchmarksOutput/

#### 它评测什么

SciMLBenchmarks.jl 覆盖范围比 PDEBench 更广，不只是 ML 模型，而是整个 scientific computing / scientific machine learning 生态。它包括：

- equation solver benchmarks；
- parameter estimation / inverse problem；
- Neural ODE；
- Universal Differential Equation；
- PINN；
- surrogate model；
- DeepONet、FNO 等 neural operator。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 方程、初值、参数、误差容忍度、求解区间 |
| 输出 | 数值解、预测轨迹、参数估计值、误差-成本曲线 |
| 传统方法 | Runge-Kutta、BDF、Rosenbrock、CVODE、LSODA 等数值求解器 |
| ML 方法 | Neural ODE、PINN、UDE、surrogate model 等 |

#### 评测方式

它的核心评测思想是 **work-precision**：

> 比较不同方法在达到相同误差水平时需要多少计算成本，或者在相同计算预算下能达到多少精度。

常见指标包括：

- wall-clock time；
- function evaluation 次数；
- Jacobian evaluation 次数；
- memory；
- error tolerance；
- convergence failure rate；
- work-precision diagram。

#### 适合借鉴的点

如果我们关心的不只是“谁预测得更准”，而是科学计算中真正重要的：

- 精度；
- 速度；
- 稳定性；
- 对 stiff system 的鲁棒性；
- 参数估计能力；
- 在不同误差容忍度下的性能曲线；

那么 SciMLBenchmarks.jl 的评测范式比普通 ML leaderboard 更合适。

---

## 5. 天气 / 气候类

### 5.1 WeatherBench / WeatherBench 2

- WeatherBench 2 官网：https://sites.research.google/gr/weatherbench/  
- 文档：https://weatherbench2.readthedocs.io/  
- WeatherBench 2 论文页：https://research.google/pubs/weatherbench-2-a-benchmark-for-the-next-generation-of-data-driven-global-weather-models/  
- WeatherBench 2020 论文：https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2020MS002203

#### 它评测什么

WeatherBench 2 是非常典型的“数据驱动 ML 模型 vs 传统数值天气预报模型”的 benchmark。

它提供：

- 公开的 ground truth 和 baseline 数据；
- 开源评测代码；
- 持续更新的榜单；
- 可比较 data-driven 和 physics-based weather forecasting models 的统一框架。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 当前大气状态变量，例如温度、湿度、风速、位势高度、气压等 |
| 输出 | 未来 1–15 天的全球天气场 |
| 传统方法 | ECMWF IFS、HRES 等数值天气预报系统 |
| ML 方法 | GraphCast、Pangu-Weather、FourCastNet 等 |
| ground truth | ERA5 等再分析数据 |

#### 评测指标

常见指标包括：

- RMSE；
- ACC；
- SEEPS；
- 不同变量、不同垂直层、不同 lead time 的分层指标；
- headline scores。

#### 适合借鉴的点

WeatherBench 2 的价值在于：

1. 它不只评测 ML 模型，也把传统数值天气模型纳入同一个评价体系；
2. 它区分不同变量和不同 forecast lead time；
3. 它强调和气象业务中心已有评测习惯对齐；
4. 它不仅有论文，还维护实时榜单和公开评测工具。

这对我们设计“科学领域综合调研与方法选择 benchmark”很有启发：benchmark 不应只看单点准确率，而应看不同时间尺度、变量、场景和科学使用需求下的表现。

---

## 6. 流体力学 / CFD 类

### 6.1 CFDBench

- 论文入口：https://huggingface.co/papers/2310.05963

#### 它评测什么

CFD 类 benchmark 关注的是：

> 给定几何、边界条件、初始状态，预测流体系统中的速度场、压力场、涡量等。

传统方法是 CFD solver，ML 方法通常是 neural operator、GNN、Transformer 或其他 surrogate model。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 几何、网格、边界条件、流体参数、初始状态 |
| 输出 | 速度场、压力场、涡量、阻力/升力等 |
| 传统方法 | CFD 数值模拟 |
| ML 方法 | FNO、DeepONet、MeshGraphNet、Transformer 等 |

#### 评测指标

- 场变量误差；
- 关键物理量误差，例如 drag/lift；
- 对新几何、新边界条件、新雷诺数的泛化；
- 推理速度相对于 CFD solver 的加速比；
- 守恒律或物理约束误差。

#### 适合借鉴的点

CFD benchmark 特别适合评估：

- surrogate model 是否真的能服务工程；
- 只在分布内有效，还是能泛化到新几何/新边界；
- 是否能保留工程上关心的物理量，而不是只优化平均场误差。

---

## 7. 材料 / 催化 / 量子化学类

### 7.1 Open Catalyst Project

- 官网：https://opencatalystproject.org/  
- Challenge：https://opencatalystproject.org/challenge.html  
- Leaderboard：https://opencatalystproject.org/leaderboard.html

#### 它评测什么

Open Catalyst Project 关注催化材料中的吸附结构、能量和力。传统方法是 DFT(Density Functional Theory, 密度泛函理论, 它是一种量子化学/凝聚态物理计算方法，用电子密度而不是完整多电子波函数来近似求体系能量、结构、能带、力、反应能垒等)，ML 方法学习近似 DFT 的势能面。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 催化剂表面结构、吸附物、原子坐标、元素类型 |
| 输出 | relaxed energy、forces、relaxed structure |
| 传统方法 | DFT 结构弛豫和能量计算 |
| ML 方法 | GNN、equivariant GNN、ML potential |

#### 评测指标

- Energy MAE；
- Force MAE；
- Energy within Threshold；
- Relaxation success；
- 推理速度；
- 对未见材料/吸附物组合的泛化能力。

#### 适合借鉴的点

Open Catalyst 是“ML 加速昂贵科学计算”的典型场景：

- DFT 是慢但相对可靠的科学计算方法；
- ML 是快但可能有偏差的近似器；
- benchmark 需要同时关注能量、力、结构弛豫结果以及泛化。

---

### 7.2 Matbench

- 论文：https://www.nature.com/articles/s41524-020-00406-3  
- Materials Project 文档：https://docs.materialsproject.org/services/ml-and-ai-applications/matbench

#### 它评测什么

Matbench 是材料性质预测 benchmark。它包含多个材料属性预测任务，数据来自 DFT 计算和实验。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 材料组成、晶体结构 |
| 输出 | 光学、热力学、电子、弹性、机械等材料性质 |
| 标签来源 | DFT 或实验数据 |
| ML 方法 | descriptor-based model、Random Forest、CGCNN、MEGNet、其他图模型 |

#### 评测指标

- MAE；
- RMSE；
- 分类任务准确率；
- 跨任务平均排名；
- leaderboard 表现。

#### 和我们目标的关系

Matbench 本身更偏 ML 预测 benchmark，不一定直接比较“ML vs DFT 的计算过程”。但它仍然属于：

> 用 ML 近似原本需要 DFT 或实验才能获得的材料性质。

因此它适合纳入材料方向的“科学方法对照 benchmark”体系中，但需要额外补充计算成本和物理一致性评估。

---

### 7.3 QM9 / MD17 / rMD17 / MD22

- MD17 介绍：https://paperswithcode.com/dataset/md17

#### 它们评测什么

这类数据集关注分子性质、能量、力和分子动力学轨迹。

| Benchmark | 主要任务 | 传统方法 | ML 方法 |
|---|---|---|---|
| QM9 | 小分子性质预测 | 量子化学 / DFT | 分子图模型、3D GNN |
| MD17 | 分子能量和力预测 | DFT 轨迹数据 | SchNet、DimeNet、PaiNN、MACE、NequIP 等 |
| rMD17 | 修订版 MD17 | DFT | ML potential |
| MD22 | 更大分子系统 | DFT / MD | ML potential |

#### 评测指标

- Energy MAE / RMSE；
- Force MAE / RMSE；
- 分子动力学稳定性；
- 长期轨迹稳定性；
- 计算加速比；
- 对未见构象或未见分子的泛化能力。

#### 适合借鉴的点

这类 benchmark 对我们有两个启发：

1. 不应只评估单步预测误差，还要评估长期 rollout 是否稳定；
2. 对科学模拟来说，forces、energy conservation、trajectory stability 往往比普通 MAE 更关键。

---

### 7.4 量子化学 Benchmark 扩展

上面列的 QM9 / MD17 / rMD17 / MD22 是最常见入口，但如果目标是系统整理“量子化学 / 计算化学 / ML 势函数”benchmark，还应把下面几类分开。

这些量子化学 benchmark 基本都是“干实验 / 计算评测”：用公开 reference label、固定 split、官方 evaluator 或 leaderboard 比较，不需要重新做湿实验。少数标签可能源自实验数据库，但参赛/评测本身仍是离线计算。

| Benchmark / 数据集 | 主要任务 | 标签 / 参考方法 | 评测方式 | 是否自带评测 / 是否需要湿实验 | 链接 |
|---|---|---|---|---|---|
| **QM7 / QM8 / QM9** | 小分子量子性质预测 | DFT / TD-DFT 等量子化学计算 | MAE / RMSE；HOMO-LUMO gap、偶极矩、极化率、能量等 | 有公开标签和常用 split / metric；不需要湿实验 | QM9: https://paperswithcode.com/dataset/qm9 |
| **PCQM4Mv2** | 给定 2D 分子图预测 DFT HOMO-LUMO gap | PubChemQC / DFT | MAE；OGB-LSC evaluator / leaderboard submission | 有 OGB-LSC evaluator / leaderboard；不需要湿实验 | https://ogb.stanford.edu/docs/lsc/pcqm4mv2/ |
| **QMugs** | 药物样小分子 3D 构象和量子性质 | 半经验方法 + DFT | 分子性质误差、构象/3D 表征泛化 | 有公开数据和计算标签；通常离线评测，不需要湿实验 | https://www.nature.com/articles/s41597-022-01390-7 |
| **ANI-1x / ANI-1ccx** | 有机分子构象的能量和力 | DFT / coupled-cluster quality reference | Energy / force MAE；ML potential 泛化 | 有公开 reference energy / force；不需要湿实验 | https://github.com/isayev/ANI1_dataset |
| **SPICE** | drug-like molecules、蛋白配体片段、离子、氨基酸等的相互作用势 | high-level quantum chemistry | Energy / force / multipole 误差；force-field / ML potential 训练与测试 | 有公开量子化学 reference；不需要湿实验 | https://github.com/openmm/spice-dataset |
| **ISO17** | 同分异构体分子动力学轨迹 | DFT-MD | 未见分子 / 未见构象上的 energy / force 泛化 | 有公开 DFT-MD 标签；不需要湿实验 | https://paperswithcode.com/dataset/iso17 |
| **Transition1x / 过渡态数据集** | 反应路径、过渡态和反应能垒 | DFT reaction path / transition state calculation | 过渡态结构 RMSD、能垒误差、路径可行性 | 有计算 reference，可离线评测；不需要湿实验，但 evaluator 可能不如 QM9/OGB 标准化 | https://github.com/atomistic-machine-learning/transition1x |
| **Open Catalyst Project** | 催化吸附结构、能量和力 | DFT relaxation / adsorption energy | Energy MAE、Force MAE、EFwT、relaxation success | 有官方任务、split、metric 和 leaderboard；不需要湿实验 | https://opencatalystproject.org/ |
| **JARVIS-Leaderboard / QC 子任务** | 材料、电子结构、quantum eigensolver 等 | DFT / quantum eigensolver reference | MAE、MULTIMAE、eigensolver error 等 | 有 leaderboard / metadata / submission 口径；通常不需要湿实验 | https://pages.nist.gov/jarvis_leaderboard/ |

#### 怎么理解这些 benchmark 的层级

| 层级 | 代表 | 它真正测什么 | 局限 |
|---|---|---|---|
| 小分子性质预测 | QM7 / QM8 / QM9 / PCQM4Mv2 | 分子图或 3D 结构能否预测量子化学标量性质 | 多数不要求长期动力学稳定 |
| 能量 / 力 / ML 势函数 | MD17 / rMD17 / MD22 / ANI / SPICE / ISO17 | ML potential 能否近似 DFT 或更高精度势能面 | 单步误差低不代表 rollout 稳定 |
| 反应与过渡态 | Transition1x / NatureBench 过渡态任务 | 能否建模化学反应路径、能垒、过渡态结构 | 数据稀缺，评测通常更难自动化 |
| 材料 / 催化 | Open Catalyst / Matbench / JARVIS | ML 能否加速材料 DFT、催化吸附和电子结构任务 | 常依赖固定数据划分，和真实发现仍有距离 |
| workflow agent | El Agente Q、ALE computational chemistry、TB-Science chemistry | Agent 能否调用 ORCA / PySCF / Quantum ESPRESSO / RDKit 等工具完成计算化学流程 | 目前统一榜单较少，更多是工作流成功率和 case study |

#### 这些任务为什么有意义

如果不是这个领域，可以把量子化学 benchmark 理解成一组“昂贵实验 / 昂贵计算的替身任务”。真实化学研发中，我们经常想知道一个分子或材料：

- 稳不稳定；
- 会不会导电、发光、吸光；
- 和蛋白、催化剂表面或其他分子结合得强不强；
- 反应要跨过多高的能垒；
- 原子在一段时间内会怎样运动。

这些答案本来要靠实验、DFT、coupled-cluster、分子动力学或量子化学软件求解，成本从分钟到数天甚至更久不等。benchmark 的作用是检查 ML 或 Agent 能不能用更低成本给出足够可靠的近似，并知道什么时候不能偷懒。

| 任务类型 | 通俗问题 | 现实应用 | 为什么能测能力 |
|---|---|---|---|
| 分子性质预测 | 这个分子像不像一个好材料 / 好药物片段？ | 药物早筛、有机电子材料、电池电解液、光伏/发光材料 | 测模型能否从结构推断电子性质和基础物理化学性质 |
| HOMO-LUMO gap / 激发态 | 分子容易吸光、发光或导电吗？ | OLED、太阳能电池、光敏药物、分子传感器 | 测模型能否近似电子能级和激发态相关量 |
| 能量和力预测 | 这些原子这样摆放稳不稳，会往哪里动？ | 分子动力学、蛋白构象、材料热稳定性、反应模拟 | 力决定原子运动；只会预测能量但力不准，模拟会很快跑偏 |
| ML 势函数 | 能不能用 ML 代替昂贵量子化学算很多步？ | 大规模分子动力学、材料缺陷、溶液/界面模拟 | 测长期 rollout 是否稳定，不能只看单步 MAE |
| 反应过渡态 / 能垒 | 这个化学反应容易发生吗，路径是什么？ | 催化剂设计、有机合成路线、酶反应、燃烧/大气化学 | 测模型是否理解反应路径，而不是只会静态性质预测 |
| 催化吸附 | 分子贴在材料表面强不强，反应会不会被催化？ | CO2 还原、氢能、电催化、工业催化剂 | 测模型能否处理表面、吸附物、结构弛豫和能量排序 |
| workflow agent | 能不能自己把计算化学流程跑完？ | 自动写 ORCA / PySCF / QE 输入、跑任务、解析日志、判断结果 | 测 Agent 的科学工具使用、排错和证据保存能力 |

#### 对科研 Agent 的意义

量子化学 benchmark 很适合做三类评测：

1. **模型能力**：预测分子性质、能量、力或吸附能。
2. **科学计算能力**：能否正确配置 DFT / semi-empirical / MD / docking / transition-state workflow。
3. **方法选择能力**：能否判断什么时候用 DFT，什么时候用 ML potential，什么时候必须做结构弛豫、频率分析或反应路径搜索。

如果要评 Famou 这类科研智能体，单独让它刷 QM9/MD17 意义有限；更合理的是给一个化学问题，让 agent 选择合适 benchmark / reference method，执行计算，保存输入文件、日志、结构、能量和结论。

---

### 7.5 量子生物相关 Benchmark / 数据集

量子生物目前没有像 QM9、Open Catalyst、Matbench 那样成熟的统一 leaderboard。更准确的判断是：

> 量子生物有很多可计算模型、实验数据和机制案例，但缺少标准化、可提交、跨模型比较的公开 benchmark suite。

原因是量子生物关心的是“量子效应是否真的影响生物功能”，例如光合作用激子转移、酶催化中的质子/氢隧穿、radical-pair 磁感应、DNA 电荷/质子转移。这些问题通常需要联合量子动力学、分子环境、实验谱学和生物功能验证，难以压成一个单一 MAE 排行榜。

#### 可作为近似评测的几类 proxy

量子生物这里要谨慎：下表不是都等价于成熟 benchmark。PDBbind / CASF 这类有明确 evaluator 和指标，不需要新湿实验；光合作用、radical-pair、酶隧穿、DNA 电荷转移等更多是“公开实验数据 + 文献模型”的离线复现任务，通常不需要自己做新湿实验，但也不一定自带统一 evaluator。

| 方向 | 可用数据 / benchmark proxy | 测什么 | 评测方式 | 是否自带评测 / 是否需要湿实验 | 链接 |
|---|---|---|---|---|---|
| 光合作用激子转移 | FMO、LH2、LHCII 等 light-harvesting complex 模型和谱学数据 | 激子能量转移、退相干、谱线、population dynamics | 与 ultrafast spectroscopy、HEOM / open quantum system reference、published simulation 对比 | 通常不是统一 leaderboard；可用公开谱学/文献参数离线复现；不需要新湿实验，但标准 evaluator 需要自己定义 | Quantum biology review: https://pmc.ncbi.nlm.nih.gov/articles/PMC7124948/；Dryad light-harvesting data: https://doi.org/10.5061/dryad.sj3tx96fn |
| radical-pair / 磁感应 | cryptochrome / radical-pair model case studies | 自旋动力学、磁场效应、反应产率 | 与实验磁场响应、spin dynamics simulation 或文献参数复现实验对比 | 通常不是成熟 benchmark；可离线复现实验曲线/文献模型；不需要新湿实验，但 evaluator 不统一 | Quantum biology mechanisms review: https://doi.org/10.3390/quantum3010006 |
| 酶催化隧穿 | enzyme kinetic isotope effect、BRENDA、SABIO-RK 等酶动力学数据 | 氢/质子转移、KIE、温度依赖、反应速率 | KIE、activation energy、rate constant 拟合；通常不是统一 ML leaderboard | 多为公开动力学数据 + case study；不需要新湿实验，但需要自定义拟合/机制判据 | BRENDA: https://www.brenda-enzymes.org/；SABIO-RK: https://sabiork.h-its.org/ |
| DNA / 蛋白质电荷转移 | DNA charge transport、redox protein、electron-transfer case studies | 电子转移路径、coupling、Marcus rate、结构环境影响 | 与实验 rate / potential / spectroscopy 或高精度 QM/MM 对比 | 多为论文级复现；不需要新湿实验，但没有统一榜单和标准 scorer | Quantum biology review: https://pmc.ncbi.nlm.nih.gov/articles/PMC2839811/ |
| 蛋白-配体结合 / 药物设计 | PDBbind、CASF、D3R、binding affinity / docking benchmark | 结合亲和力、pose、scoring、screening | scoring / ranking / docking / screening power；RMSE、Pearson/Spearman、Top-k | PDBbind / CASF 有明确 benchmark 和指标；不需要新湿实验；但它只是结合 proxy，不直接证明量子生物机制 | PDBbind/CASF: http://www.pdbbind.org.cn/；CASF-2016 paper: https://doi.org/10.1021/acs.jcim.8b00545 |
| 生物大分子量子化学局部问题 | QM/MM、active-site cluster、metalloenzyme、chromophore benchmark | 活性位点电子结构、反应能垒、光谱、氧化还原性质 | 与实验光谱、反应能垒、high-level quantum chemistry 或 curated case studies 对比 | 多为 curated case / workflow；一般不需要新湿实验，但任务定义和 scorer 往往要自己整理 | 更常见于论文级 case study，少有统一 leaderboard |

#### 这些 proxy 为什么有意义

量子生物的核心不是“把生物问题都变成量子计算”，而是判断某些生命过程里，普通经典模型是否不够，需要电子态、自旋、隧穿、相干或量子动力学才能解释。它的 benchmark 意义更接近“机制归因”。

| 方向 | 通俗问题 | 现实应用 | 为什么难评测 |
|---|---|---|---|
| 光合作用激子转移 | 植物/细菌怎么把光能高效送到反应中心？ | 人工光合作用、太阳能材料、能量传输材料设计 | 生物环境很嘈杂，必须区分真正功能性量子相干和普通热噪声效应 |
| radical-pair 磁感应 | 鸟类或生物分子是否能感应地磁场？ | 生物导航机制、磁场对生物反应影响、安全性研究 | 自旋态很难直接观测，实验信号弱，模型参数不唯一 |
| 酶催化隧穿 | 酶为什么能把反应加速很多，质子/氢是否“穿墙”？ | 酶工程、药物代谢、同位素实验解释、生物催化设计 | 速率变化可能来自构象、溶剂、温度等多因素，不容易只归因于隧穿 |
| DNA / 蛋白电荷转移 | 电子如何沿 DNA 或蛋白传递？ | DNA 损伤修复、呼吸链、光敏蛋白、生物电子器件 | 结构波动、溶剂和局部电子结构都会影响转移路径 |
| 蛋白-配体结合 | 一个候选药物能不能稳稳结合靶点？ | 药物发现、虚拟筛选、分子优化 | docking 分数只是 surrogate，和真实细胞/体内药效差距很大 |
| 活性位点 QM/MM | 酶或金属蛋白反应中心到底怎么反应？ | 酶机制解释、金属酶设计、催化剂仿生设计 | 需要同时处理量子活性区和巨大蛋白环境，计算贵且设置敏感 |

所以，量子生物相关 benchmark 的用途通常不是直接给出“模型第一名”，而是帮助判断：

- 一个机制假设是否被实验和计算同时支持；
- Agent 是否能找到正确证据，而不是把普通生物相关性误说成量子机制；
- 某个近似模型是否足以解释观测，还是必须升级到 QM/MM、spin dynamics 或 open quantum system simulation。

#### 量子生物和普通生物 benchmark 的区别

| 类型 | 例子 | 是否量子生物 | 说明 |
|---|---|---|---|
| 生物医学 QA | LAB-Bench、LifeSciBench | 通常不是 | 测科研判断、文献理解、数据库使用，不直接测量子机制 |
| 生信 workflow | BioAgent Bench、Biomni-Eval1 | 通常不是 | 测 RNA-seq、single-cell、GWAS、variant calling 等流程 |
| 蛋白/药物 ML | PDBbind、CASF、BioML-bench、NatureBench Molecular Design | 部分相关 | 可涉及分子相互作用和物理化学，但通常不验证量子效应本身 |
| 量子化学 / QM/MM | active-site、chromophore、reaction barrier case studies | 可能相关 | 如果问题明确是电子结构、隧穿、激子、spin dynamics，就接近量子生物 |
| 真实机制验证 | 光合作用、磁感应、酶隧穿实验 | 是 | 但目前多为论文 case study，不是统一 benchmark |

#### 对科研 Agent 的意义

量子生物更适合做 **workflow / mechanism evaluation**，而不是刷榜式 benchmark：

1. 给定一个机制假设，例如“某酶反应是否存在质子隧穿贡献”。
2. Agent 需要检索文献和实验数据，选择 KIE / QM/MM / rate model / isotope substitution 等证据。
3. 执行可复现计算或抽取实验参数。
4. 输出机制判断，并明确证据强弱和替代解释。

也就是说，量子生物 benchmark 如果要做，应该更像 ResearcherBench / LifeSciBench / ALE 的专家 workflow 任务，而不是单纯的分子性质 MAE。

---

### 7.6 SciModelingBench / Design-Bench：离线科学设计优化

- SciModelingBench GitHub：https://github.com/xukp20/sci-modeling-bench  
- SciModelingBench PyPI：https://pypi.org/project/sci-modeling-bench/  
- 数据入口：https://huggingface.co/datasets/sci-modeling-bench/design-bench  
- Design-Bench Suite 文档：https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/README.md  
- 原始 Design-Bench 代码：https://github.com/brandontrabucco/design-bench  
- 原始 Design-Bench 论文：https://arxiv.org/abs/2202.08450

SciModelingBench 是面向 **scientific modeling and design agents** 的 benchmark/package。它把科学观测数据、Agent 可见输入、可信 Objective、提交契约和任务指标分开管理。当前公开的 Design-Bench suite 覆盖 8 个任务，数据托管在 Hugging Face，package 提供 validators、Protocols、Objectives、Tasks 和 metrics。

它需要和原始 Design-Bench 区分：

- 原始 Design-Bench 是 offline model-based optimization benchmark。
- SciModelingBench 复用了 Design-Bench 方向，但更强调 provenance、Agent-visible protocol、trusted objective、submission contract 和可复现任务封装。
- 它自己不提供统一 agent runner、query budget、进程隔离或排行榜；受控 Agent 评测需要外部 harness 隔离完整数据集、缓存、源码和网络。

#### 它评测什么

SciModelingBench / Design-Bench 不是 AIRS-Bench、NatureBench 那类“读论文、写代码、跑实验、提交结果”的 workflow benchmark。它的核心是：

> 给定一批已有设计样本和对应分数，算法或 Agent 能不能在受控可见信息内提出分数更高的新候选设计。

这里的“设计”可以是：

- DNA / RNA 序列；
- 蛋白质序列；
- 材料组成；
- 毒理学观测条件；
- 神经网络 cell DAG；
- 机器人控制策略。

它更接近 **科学候选设计 / 黑盒优化 / pool ranking benchmark**。如果由 Agent 来跑，Agent 需要在 Protocol 暴露的信息内建模、搜索候选、按契约提交，由 trusted Objective 评分。

#### 当前公开任务

| Config | 科学对象 | 行数 | 评测设定 |
|---|---|---:|---|
| `tfbind8` | SIX6 DNA 8-mer binding landscape | 65,536 | exact lookup；free-form black-box optimization |
| `tfbind10_pho4` | Pho4 BET-seq raw count observations | 4,160,533 | replicate-count posterior；black-box optimization |
| `utr_mrl_egfp_unmodified` | synthetic 50-nt 5' UTR | 318,468 | measured MRL；compositional pool ranking |
| `gfp` | GFP protein genotypes | 51,715 | measured median brightness；pool ranking |
| `superconductor` | normalized elemental compositions | 15,164 | measured group-median critical temperature；pool ranking |
| `drugmatrix_clinical_pathology` | rat toxicology observations | 10,605 | matched-control measured endpoints；pool ranking |
| `cell_dag_nas` | NASBench-101 cell DAGs | 423,624 | official repeated NAS records；black-box optimization |
| `hopper_controller` | PPO policy checkpoints | 3,200 | 500 frozen Hopper-v5 rollouts per policy；pool ranking |

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | `task.build_input()` 生成的 Agent-visible bundle；通常包含可见观测、候选 pool 或低分区历史数据、manifest、字段语义和可选知识资源 |
| 输出 | 符合 Task submission contract 的候选列表；通常是有序 top-N 候选 |
| 可信评分端 | Objective 保留隐藏标签、exact lookup、measured aggregate、posterior-derived score 或 frozen rollout 结果 |
| 约束 | Protocol 决定哪些字段对 Agent 可见；是否禁网、是否限制查询次数、是否隔离完整 HF cache 由外部 harness 执行 |
| 方法 | offline MBO、Bayesian optimization、生成模型、扩散/自回归设计模型、梯度优化、保守模型、ensemble uncertainty 等 |

#### 评测方式和指标

典型指标不是普通分类准确率，而是“最后提交的候选有多好”：

| 指标 | 含义 |
|---|---|
| `best_score` | 提交候选中真实分数最高的一个 |
| `best_k_mean` | 提交候选里真实 top-k 的平均分；TFBind8、CellDAG-NAS 等黑盒优化任务常用作 primary metric |
| `batch_mean` | 整个提交 batch 的平均真实分数 |
| `global_ndcg` / `reranking_ndcg` | 排序质量；Superconductor 等候选池排序任务常用 `global_ndcg` |
| `normalized_enrichment` | 相对随机或候选池基线的富集程度 |
| Regret / gap to oracle | 距离已知最优或 oracle 最优还有多远 |
| Validity / constraint satisfaction | 候选是否满足序列、结构、化学或工程约束 |

#### 这个 benchmark 的意义

对非领域读者，可以把它理解成“只看历史实验记录，设计下一个更好的分子/蛋白/材料/策略”。

现实研发中经常遇到这种情况：

- 真实验贵，不能随便试几万次；
- DFT、MD、湿实验、动物实验或仿真 rollout 都可能很慢；
- 历史数据有偏，只覆盖一小块设计空间；
- 高分候选常常在训练数据分布之外。

所以这类 benchmark 主要测：

1. 模型是否能从有限历史数据中学到可靠的性能函数；
2. 优化器是否会过度相信错误 surrogate，从而生成虚假高分候选；
3. 生成的候选是否真的有效、满足约束；
4. 在固定评测预算下，谁能更快找到高分设计。

#### Trust model / 是否需要湿实验

它不要求参评者重新做湿实验。评分来自已冻结的数据、实验观测聚合、精确查表、posterior-derived 目标或固定仿真 rollout。

SciModelingBench 明确区分几类 objective：

| Objective 类型 | 例子 | 说明 |
|---|---|---|
| Exact | TFBind8 | 完整表格或解析映射，查表可得确定分数 |
| Measured | GFP、Superconductor、DrugMatrix、Hopper | 来自保留实验观测或重复仿真结果 |
| Posterior-derived | TFBind10 Pho4 | 从 raw replicate counts 确定性聚合得到评分 |
| Legacy learned surrogate | 原始 Design-Bench 某些任务 | 需要显式标注，不能把 learned oracle 默认为真实实验真值 |

但要注意：这些数据和文档多数是公开的。`task.build_input()` 能隐藏 evaluator labels，但不能防止 Agent 从外部网络、HF cache 或源码中直接查答案。因此严格评测时必须由外部 harness 断网、隔离缓存、固定 revision、限制查询预算。

#### 是否有排行榜

截至当前公开资料，SciModelingBench 本身没有维护一个类似 AIRS-Bench / NatureBench 的统一公开 leaderboard。部分任务文档给了 random audit 和 data-only reference baselines，但这些是任务审计或参考基线，不是正式排行榜。

#### 资源和时间要求

SciModelingBench 官方没有规定统一的 wall-clock time、GPU hours、LLM token budget、query budget 或 agent workflow。官方 package 只定义 Dataset、Protocol、Objective、Task、submission contract 和 metrics；真正的运行时限制、禁网、缓存隔离、并发度和模型调用预算需要外部 harness 自己规定。

评测端本身偏轻量：多数 Task 是 frozen table lookup、posterior aggregation 或候选池排序，不要求参评者重新做湿实验、重新训练 NAS 模型、重新跑 MuJoCo rollout 或重新做 DFT。GPU 是否需要主要取决于参评方法本身，例如是否训练深度 surrogate / 生成模型，而不是 benchmark evaluator 的硬要求。

| Task / endpoint | Submission 规模 | 官方主指标 | 评分端资源 | Agent 侧可能资源 |
|---|---:|---|---|---|
| `tfbind8` | 32 | `best_k_mean` | CPU 查完整 8-mer 表；exact lookup | 很轻；枚举 `4^8=65,536` 序列即可，CPU 足够 |
| `tfbind10_pho4` | 128 | `normalized_enrichment` | CPU 读取 10-mer 观测和 posterior-derived objective；数据最大，4,160,533 行 | 中等；可 CPU/内存建模，深度序列模型可用 GPU |
| `cell_dag_nas` | 32 | `best_k_mean` | CPU 查 NASBench-101 frozen records；不重新训练 CNN | 中等；可做图特征/搜索，GPU 非必须 |
| `superconductor` | 32 | `global_ndcg` | CPU 查 measured candidate pool；文档明确是 CPU-friendly | 轻到中等；表格/材料特征建模，CPU 足够 |
| `hopper_controller` | 32 | `global_ndcg` | CPU 查 500 frozen Hopper-v5 rollouts per policy 的聚合结果；不现场跑 MuJoCo | 中等；如果只排序 checkpoint，CPU 足够；自建策略模型可用 GPU |
| `utr_mrl_egfp_unmodified` | 128 | `normalized_enrichment` | CPU 查 measured MRL / 候选池 | 中等；序列建模可 CPU 或 GPU |
| `gfp` | 128 | `normalized_enrichment` | CPU 查 measured median brightness / 候选池 | 中等；蛋白序列模型可用 GPU |
| `drugmatrix_clinical_pathology` 6 个 endpoint | 每 endpoint 16 | `global_ndcg` | CPU 查 finite toxicology pool 和 matched-control endpoints | 轻到中等；表格/药物特征建模，CPU 足够 |

如果要对外证明某个 Agent 在 SciModelingBench 上有效，建议报告：

| 项目 | 建议记录 |
|---|---|
| 版本 | `sci-modeling-bench` package version、HF dataset revision、任务 ID |
| 预算 | 每个 task 的 wall-clock 上限、最大 LLM calls / tokens、最大 evaluator queries、CPU/GPU 型号 |
| 隔离 | 是否禁网、是否隔离完整 HF cache / provenance / hidden labels / source checkout |
| 重复 | 每个 task 的 seed 数、trial 数、均值和标准差 |
| 成本 | 总 token、API cost、CPU/GPU hours、失败/invalid submission 数 |

ScienceFlow 页面展示的 Sci Modeling Bench 对比表属于第三方自建评测结果：它写明 8 groups、13 tasks、All Score，但没有看到 SciModelingBench 官方统一时间/资源预算或官方 leaderboard。

#### 和 Agent / Discovery benchmark 的关系

| 维度 | Sci Modeling Bench / Design-Bench | AIRS-Bench / NatureBench | AInstein / MADE / DiscoveryWorld |
|---|---|---|---|
| 主要对象 | 候选设计算法 / Agent-visible optimization protocol | 科研 workflow agent | 闭环发现 agent |
| 任务形式 | 给定可见观测或候选池，提交高分有序候选 | 给定科研任务，写代码训练/复现/超越 SOTA | 多轮 propose→simulate/evaluate→refine |
| 是否需要写代码调试 | package 可被 Agent 调用，但 benchmark 不自带完整 coding harness | 是核心能力 | 取决于环境，通常有工具/仿真调用 |
| 是否有仿真反馈闭环 | Task/Objective 可评分，但 query budget 和反馈策略由外部 harness 定义 | 通常按任务执行代码和 hidden evaluator | 是核心设定 |
| 是否需要湿实验 | 不需要；评测用已有 oracle / 标签 / surrogate | 不需要；评测用隐藏测试集或官方 evaluator | 通常不需要；ground truth 来自仿真器或离线 oracle |
| 排行榜含义 | 若建榜，主要排候选设计 / 优化方法或受控 agent protocol 表现 | 排 agent / agent workflow | 排闭环搜索或发现 agent |

因此，如果我们要把它纳入 Famou / Hyra 这类科研智能体评测，可以有两种用法：

1. **作为算法 benchmark**：直接比较候选生成/优化模块，不评 Agent 的科研执行链路。
2. **包装成 workflow benchmark**：让 Agent 读任务说明、选择 offline MBO 方法、训练 surrogate、生成候选、调用 evaluator、写报告。这样才接近 AIRS-Bench 的 agent 评测口径。

---

## 8. 方程发现 / 符号回归类

### 8.1 SRBench

- 官网：https://cavalab.org/srbench/user-guide/  
- 论文介绍：https://pmc.ncbi.nlm.nih.gov/articles/PMC11074949/

#### 它评测什么

SRBench 是 symbolic regression 的 benchmark。目标不是训练黑盒预测器，而是从数据中恢复显式数学表达式。

#### 输入输出

| 项目 | 内容 |
|---|---|
| 输入 | 数据点 $(x, y)$ 或多变量观测 |
| 输出 | 显式公式 / symbolic expression |
| 传统方法 | genetic programming、稀疏回归、启发式搜索 |
| ML 方法 | 神经符号方法、Transformer-based symbolic regression |

#### 评测指标

- 预测误差；
- 表达式复杂度；
- 是否恢复 ground-truth form；
- 公式简洁性；
- 可解释性；
- 运行时间。

#### 适合借鉴的点

SRBench 对“科学发现”很关键，因为它不是只问：

> 模型能不能预测？

而是问：

> 模型能不能给出人类可理解的规律？

---

### 8.2 SRBench++

- 论文：https://pmc.ncbi.nlm.nih.gov/articles/PMC12321164/

SRBench++ 在 SRBench 基础上更强调 domain-expert interpretation。它指出，符号表达式的可解释性不能只靠表达式长度衡量，还需要领域专家判断。

#### 适合借鉴的点

对于科研智能体来说，idea 或规律的价值不能只靠自动指标判断。SRBench++ 提醒我们：

- 公式短不一定科学上有意义；
- 预测准不一定可解释；
- 领域专家评估仍然重要；
- benchmark 可以加入专家解释维度。

---

### 8.3 LLM-SRBench

- 论文：https://arxiv.org/pdf/2504.10415  
- GitHub：https://github.com/deep-symbolic-mathematics/llm-srbench  
- 数据集：https://huggingface.co/datasets/nnheui/llm-srbench

LLM-SRBench 是面向 **LLM-based scientific equation discovery** 的 benchmark。它不是完整科研智能体 benchmark，而是专门评估 LLM 或 LLM-guided search system 能否从科学背景和数值样本中发现显式数学方程。

#### 输入是什么

一个任务通常包含：

| 字段 | 含义 |
|---|---|
| `name` | 问题 ID，例如 `BPG0`、`CKR2`、`MatSci0` |
| `symbols` | 方程里出现的变量和常数 |
| `symbol_descs` | 每个变量的科学含义 |
| `symbol_properties` | 变量/常数的类型或属性说明 |
| training data | 输入变量和输出变量的数值样本 |
| test data | in-domain 测试数据 |
| OOD test data | 部分任务包含 out-of-domain 测试数据 |
| scientific context | 领域背景，例如生物增长、反应动力学、材料应力等 |

因此它的输入不是纯自然语言，也不是纯数值表，而是：

```text
科学背景 + 变量说明 + 数值样本 + 任务指令
```

#### 输出是什么

输出是一个**显式数学方程**，可以表现为：

1. 数学表达式；
2. Python function；
3. expression tree；
4. equation program。

例如输出可能是：

```python
def equation(t, A, params):
    return params[0] * A + params[1] * A**2 + params[2] * A**3
```

它不是让模型回答解释性文字，而是要求模型输出可执行、可评测的数学假设。

#### 是单次调用还是 ReAct-loop agent

LLM-SRBench 不是标准的 ReAct-loop agent benchmark。更准确地说，它比较的是多种 **LLM-guided equation discovery methods**：

| 方法类型 | 机制 |
|---|---|
| Direct Prompting / DataBlind | 主要根据科学上下文生成方程，接近单轮或少量采样 baseline |
| LLM-SR | LLM 生成 Python 方程骨架，再结合多岛进化搜索、数据反馈和参数优化 |
| LaSR | LLM 抽象科学概念，再结合 PySR / evolutionary search |
| SGA | LLM 生成结构，PyTorch 做连续参数优化 |

论文中主要方法不是简单单次调用，而是“LLM + 搜索/优化循环”。为了公平，不同 discovery framework 通常设置调用预算，例如每个问题约 1k LLM calls。

#### 评测方式

主要评测三类能力：

| 指标 | 含义 |
|---|---|
| `Accτ` / `Acc0.1` | 预测相对误差是否低于阈值，常用 `Acc0.1` |
| `NMSE` | normalized mean squared error |
| Symbolic Accuracy | 判断预测方程和 ground-truth 方程是否符号等价 |

其中 Symbolic Accuracy 不是简单字符串匹配，因为两个表达式写法不同也可能数学等价。论文使用 GPT-4o 作为 evaluator 判断表达式在忽略常数/参数差异后的等价性，并对一部分样本做了人工核验。

#### 任务来源和类别

LLM-SRBench 总计约 239 个问题，分为两类：

| 子集 | 数量 | 说明 |
|---|---:|---|
| LSR-Transform | 111 | 从 Feynman equations 变换而来，例如把原方程中的某个输入变量变成目标输出，减少直接背公式的可能 |
| LSR-Synth | 128 | 合成但科学上合理的问题，覆盖 chemistry、biology、physics、material science |

LSR-Synth 中的领域分布大致为：

| 领域 | 数量 |
|---|---:|
| Chemistry | 36 |
| Biology | 24 |
| Physics | 43 |
| Material Science | 25 |

#### 例子 1：Feynman 公式变换

原始 harmonic oscillator energy 可以写成：

```text
E = 1/4 * m * x^2 * (omega^2 + omega_0^2)
```

LSR-Transform 可能把目标变量改成质量 `m`，要求模型发现：

```text
m = 4E / (x^2 * (omega^2 + omega_0^2))
```

这个设计的目的不是测试模型是否背过原公式，而是测试它能否根据变量关系和数据重新发现变换后的公式。

#### 例子 2：生物种群增长

任务可能要求发现 population growth 的微分方程。

变量包括：

```text
t: time
P(t): population size
r: growth rate
K0: carrying capacity
```

目标方程可能在 logistic growth 基础上加入额外非线性项，例如：

```text
dP/dt = r * (1 - P(t)/K0) * P(t) + r * P(t)^0.33
```

这个任务测试模型是否能识别常见增长机制，并从数据中发现额外项。

#### 例子 3：化学反应动力学

任务可能要求发现 concentration `A(t)` 的变化率：

```text
dA/dt = f(t, A)
```

方程可能组合了二阶衰减、时间调制和非线性扰动，例如：

```text
dA/dt = -k * A(t)^2 - k * A(t) * exp(-ks * t) + kp * sin(omega * A(t))
```

这个任务测试模型是否能从数值样本中识别 reaction decay、time modulation 和 nonlinear perturbation。

#### 例子 4：材料科学中的应力-应变关系

任务可能要求发现 stress `sigma` 与 strain `epsilon`、temperature `T` 的关系：

```text
sigma = E0 * epsilon * (1 - alpha_T * (T - T0))
        + H * epsilon^3
        + eta * (T - T0) * sin(epsilon)
```

这个任务测试模型能否结合材料力学中的线性弹性项、温度修正项、非线性硬化项和合成交互项。

#### 和我们目标的关系

LLM-SRBench 对我们有价值，但它覆盖的是科研流程中的一个局部能力：

| 我们要评测的能力 | LLM-SRBench 是否覆盖 |
|---|---|
| 科学问题理解 | 部分覆盖 |
| 数值数据建模 | 覆盖 |
| 方程发现 | 强覆盖 |
| 物理/科学可解释性 | 部分覆盖 |
| 文献检索 | 不覆盖 |
| gap identification | 不覆盖 |
| idea novelty 判断 | 不覆盖 |
| agent 轨迹质量 | 不覆盖 |

因此它适合作为科研智能体 benchmark 的“建模/规律发现”子模块，而不是完整科研智能体 benchmark。

#### 适合借鉴的点

1. 科学发现 benchmark 需要防止模型直接记忆已知公式；
2. 需要区分“知道公式”和“能从数据/现象推导规律”；
3. 输出应该是可执行、可评测的 hypothesis，而不只是自然语言解释；
4. 可以把 in-domain、OOD、符号等价、计算成本结合起来评估；
5. 对科研智能体而言，它可以作为文献调研之后、实验建模阶段的一个局部任务。

---

## 9. ODE / 动力系统发现类

### 9.1 SINDy 系列任务

SINDy，即 Sparse Identification of Nonlinear Dynamics，是从动力系统轨迹中恢复控制方程的一类方法。

#### 任务形式

| 项目 | 内容 |
|---|---|
| 输入 | 系统状态时间序列，例如 $x(t)$、$y(t)$、$z(t)$ |
| 输出 | ODE 右端项，例如 $\dot{x}=f(x,y,z)$ |
| 传统方法 | 数值微分 + 候选函数库 + 稀疏回归 |
| ML 方法 | Neural ODE、autoencoder + SINDy、Transformer equation discovery |

#### 评测指标

- 方程项恢复率；
- 参数误差；
- 轨迹预测误差；
- 对噪声的鲁棒性；
- 对稀疏采样和不规则采样的鲁棒性；
- 长期预测稳定性。

#### 适合借鉴的点

SINDy 方向很适合构造“科学推理 + 数学建模”任务，因为模型不仅要拟合数据，还要恢复机制。

---

### 9.2 ODEFormer / ODEBench 类任务

这类工作通常把 ODE 发现问题转成 sequence-to-expression 或 symbolic regression 问题。

#### 任务形式

- 输入：一条或多条动力系统轨迹；
- 输出：显式 ODE 方程；
- 评价：方程恢复、轨迹预测、泛化到新初值、新参数、新噪声水平。

#### 和普通预测任务的区别

普通模型只需要预测未来状态；ODE 发现类任务要求模型输出可解释的控制方程。因此它更贴近“数学推导”和“科学规律发现”。

---

## 10. 科研 terminal 工作流类

### 10.1 Terminal-Bench Science / TB-Science

- GitHub：https://github.com/harbor-framework/terminal-bench-science  
- 公告：https://www.tbench.ai/news/tb-science-announcement

Terminal-Bench Science 是 Terminal-Bench 的科学版。它不是传统的 ML benchmark，也不是单纯的数值方法 benchmark，而是评估 **AI agent 能否在真实 terminal 环境中完成复杂科学计算 workflow**。

#### 它评测什么

它关注的是科研执行能力，例如：

- 阅读已有代码和数据；
- 理解科学任务；
- 修改脚本或配置；
- 运行 simulation；
- 处理实验或模拟数据；
- 拟合模型参数；
- debug scientific pipeline；
- 生成指定结果文件；
- 通过自动化测试。

因此它更像科研版的 SWE-bench / Terminal-Bench，而不是 PDEBench 那种固定输入输出的模型 leaderboard。

#### 输入是什么

每个任务通常是一个完整 workspace，包含任务说明、代码、数据、测试脚本和环境配置。典型结构类似：

```text
tasks/<domain>/<field>/<task-name>/
  task.toml
  Dockerfile 或 docker-compose.yaml
  run-tests.sh
  tests/
  data/
  code/
  solution.sh 或参考解
```

Agent 进入这个 workspace 后，通过 terminal 执行多步操作。任务指令可能是：

```text
修复这个科学计算 pipeline，使其正确处理输入数据并生成指定结果。
```

或者：

```text
给定实验数据和已有脚本，拟合模型参数，并输出能通过测试的结果文件。
```

#### 输出是什么

输出不是一段自然语言解释，而是最终 workspace 状态，例如：

- 正确生成的数据文件；
- 修复后的科学代码；
- 指定格式的分析结果；
- 模拟结果；
- 图表或参数文件；
- 能通过验证脚本的产物。

#### 如何评测

核心是 **programmatic verification**，即用自动测试验证最终结果是否正确。每个任务通常包含：

| 组成 | 作用 |
|---|---|
| `task.toml` | 任务元信息和配置 |
| `run-tests.sh` | 统一测试入口 |
| `tests/` | 验证逻辑 |
| reference solution | 参考解法或 oracle |

它强调 outcome verification：主要评价最终产物是否正确，而不是强制规定 agent 必须采用哪条路径。

#### 任务设计原则

TB-Science 的任务通常强调：

| 原则 | 含义 |
|---|---|
| verifiable | 结果必须可以程序化验证 |
| outcome_verified | 评估最终结果，而不是只看过程描述 |
| novel | 避免训练集中常见 cookbook 题 |
| agentic | 需要多步 terminal 操作，不能单轮回答解决 |
| scientifically_grounded | 来自真实科学研究流程 |
| essential_difficulty | 难点应来自科学推理、方法选择和科学执行，而不是格式陷阱 |

#### 覆盖领域

根据项目介绍，TB-Science 面向多个自然科学和工程方向，包括：

- life sciences；
- physical sciences；
- earth sciences；
- mathematical sciences；
- engineering sciences。

当前公开任务规模仍在发展中，不是一个已经非常成熟的大规模 benchmark。

#### 和“ML vs 数值/解析方法”的关系

TB-Science 不直接比较 ML 方法和数值方法的 leaderboard 分数，但它可以容纳这类任务。比如一个任务可以要求 agent：

1. 检查已有 ML surrogate 和数值 solver；
2. 在给定误差和时间预算下运行二者；
3. 比较精度、速度和稳定性；
4. 修复 pipeline；
5. 输出可验证结果。

所以它更适合评测：

> Agent 能不能真正执行科学计算任务，而不是只会讨论方法。

#### 对我们的借鉴价值

1. **任务必须尽量落到可验证 artifact**  
   文献调研、gap identification、idea generation 很开放，但后续实验/建模阶段应尽量有可测试产物。

2. **评估结果而不是规定过程**  
   不必强制 agent 必须用某个工具，而是验证最终结果是否满足科学任务要求。

3. **强调真实科研 workflow**  
   任务应来自 simulation、数据处理、参数拟合、scientific code debugging、结果复现等真实流程。

4. **适合作为科研智能体后半段 benchmark**  
   它不适合直接评测前期文献检索，但非常适合评测 idea 确定之后的科学执行能力。

#### 在科研流程中的定位

| 阶段 | 是否适合 TB-Science |
|---|---|
| 文献检索 | 不太适合，除非任务可以程序化验证 |
| 领域知识图谱 | 不太适合，验证较难 |
| gap identification | 不太适合，偏开放 |
| idea generation | 不太适合，偏开放 |
| 数值实验 / simulation | 很适合 |
| 数据处理 pipeline | 很适合 |
| 模型训练与拟合 | 很适合 |
| 科学代码 debug | 很适合 |
| 结果复现 | 很适合 |

### 10.2 Agents' Last Exam（ALE）

- 提出时间：2026-06  
- 官网：https://agents-last-exam.org/  
- 评测说明：https://agents-last-exam.org/docs/ale/index.html  
- 领域分类：https://agents-last-exam.org/taxonomy

ALE 不是纯科学 benchmark，而是覆盖 13 个专业 cluster、55 个子领域的长程数字工作
benchmark。其 science / engineering 部分包含物理、等离子体与流体、计算化学、材料、
天文、地球与大气、生命科学和工程等任务。Agent 在 Windows/Linux sandbox 中操作真实
软件和输入文件，最后提交修改后的 workspace 或指定 artifact。

| 评测组成 | 如何评测 |
|---|---|
| 任务完成度 | 每个任务使用 deterministic grader 或 judge-based grader 检查隐藏 reference 与最终 artifact |
| 长程执行 | 审计 Agent 的计算机操作轨迹、文件修改和最终软件状态，而不是只读自然语言答案 |
| 科学覆盖 | 通过 taxonomy 分领域报告；科学任务只是 ALE 的子集，不能把 ALE 总分解释成纯科学发现分数 |
| 可信边界 | hidden reference 和 grader 与 Agent 隔离；但它主要证明专业 workflow 执行能力，不直接证明产生了新科学结论 |

ALE 与 TB-Science 都属于 **W1 工作流型**：前者覆盖更广的专业桌面/终端环境，后者更
聚焦可程序化验证的科学 terminal 任务。

---

## 11. 先区分科学推理、科学发现和工作流

下列任务经常都被称为“科研 benchmark”，但它们要求的能力和可信评测方式不同：

| 层级 | 任务形态 | 输入 | 输出 | 主要评测 | 是否证明端到端科研 |
|---|---|---|---|---|---|
| Q0 闭卷科学问答 | 回答有明确答案的科学题 | 题目，可能含图表 | 选项、数值、短答案、推导 | exact match、accuracy、专家判分 | 否，只证明单点推理能力 |
| Q1 可检索科研判断 | 搜文献并综合证据 | 开放问题、论文库、科研产物 | 带引用答案、分析报告 | recall、IoU、groundedness、rubric | 否，但更接近科研前半段 |
| D1 已知发现再发现 | 从数据恢复隐藏规律或结论 | 数据、背景、观测接口 | 方程、结构化假设、claim | 与隐藏公式/假设/claim 匹配 | 部分，答案仍然已知 |
| D2 开放数据分析 | 自主选择变量、变换、统计路线 | 原始数据、研究问题 | 分析代码、模型、结论 | 数据流图、结果正确性、专家路径集合 | 部分，覆盖“做分析→得结论” |
| W1 科研工作流 | 在真实软件环境完成明确任务 | instruction、代码、数据、工具环境 | 文件、代码、模拟或分析 artifact | 自动测试、artifact validity、任务成功率 | 否，证明执行能力而非新发现 |
| R1 科研复现 | 重建论文方法、代码或结果 | 论文、数据、部分/空代码库 | 可运行代码、实验结果、复现报告 | 隐藏测试、层级 rubric、与论文结果一致性 | 否，目标是已知工作，但最接近科研工程闭环 |
| D3 端到端数字科研 | 自主规划、实现、运行、分析和写报告 | 研究目标、数据和环境 | code、metrics、claims、report | artifact + rubric + evaluator | 是，数字环境内的端到端 |
| D4 真实实验闭环 | 连接机器人、仪器或湿实验 | 目标、实验资源、安全约束 | 实验动作、真实样品和测量 | 实验成功、物性/机制验证、重复性 | 最强，但成本和安全门槛最高 |

因此，不能用科学 QA accuracy 证明 Agent 会做科研，也不能因为 workflow 能通过测试就声称产生了新发现。后续表格会明确写出每个 benchmark 落在哪一层。

---

## 12. 科学推理问答、检索与科研判断

### 12.1 代表 Benchmark 总表

| Benchmark | 提出时间 | 层级 / 范式 | 评测内容 | 如何评测 | 论文 / 代码 / 数据 / 榜单 |
|---|---:|---|---|---|---|
| **FrontierScience** | 2026-08 | Q0，专家级科学推理 | 两条赛道：Olympiad 为国际奥赛级短答案；Research 为物理、化学、生物 PhD 研究子问题。公开 gold set 共 160 题（100 + 60），其余题留出监测污染 | Olympiad 对数值、代数式或短语做等价判定；Research 每题有 10 分原子 rubric，由 GPT-5 judge 逐项计分，`>=7/10` 记成功；论文分别做 20/30 次独立试验后汇总准确率 | Official: https://openai.com/index/frontierscience/；Paper: https://cdn.openai.com/pdf/2fcd284c-b468-4c21-8ee0-7a783933efcc/frontierscience-paper.pdf；Data: https://huggingface.co/datasets/openai/frontierscience |
| **GPQA** | 2023-11 | Q0，题集型能力探针 | 生物、物理、化学专家编写的 448 道 graduate-level、Google-proof 四选一题 | 固定答案 accuracy；同时报告 PhD 专家和可联网非专家基线。只测单题推理，不是 Agent loop 或科学发现 harness | Paper: https://arxiv.org/abs/2311.12022；Data/Code: https://github.com/idavidrein/gpqa |
| **SciBench** | 2023-07 / ICML 2024 | Q0，大学级科学解题套件 | 数学、化学、物理的大学教材题，强调多步公式推导、数值计算和单位处理 | 从自由作答中抽取最终答案，做数值容差/表达式匹配并汇总 overall score；另按 10 类解题错误做人类诊断 | Paper: https://arxiv.org/abs/2307.10635；Code/Data: https://github.com/mandyyyyii/scibench |
| **SciEval** | 2023-08 / AAAI 2024 | Q0，科学研究能力分层评测 | 基于 Bloom taxonomy 覆盖记忆、理解、应用、分析等层级，含客观题、主观题和按科学原理动态生成的防泄漏子集 | 客观题自动正确率；主观题按参考答案/评分协议判分；分别报告静态、动态和不同认知层级结果，不能只看总 accuracy | Paper: https://arxiv.org/abs/2308.13149；Code/Data: https://github.com/OpenDFM/SciEval |
| **Humanity's Last Exam (HLE)** | 2025 | Q0，跨领域高难问答 | 多学科专家撰写的高难 MCQ 与短答案，科学领域只是其中一部分 | MCQ/短答案正确率；短答案使用受控自动判分；同时报告 calibration / confidence 类指标 | Site: https://lastexam.ai/；Paper: https://arxiv.org/abs/2501.14249；Data: https://huggingface.co/datasets/cais/hle |
| **ChemBench** | 2024 | Q0，化学推理问答 | 2,700+ 化学题，覆盖知识、计算、实验理解和安全等能力，并与人类化学家比较 | 结构化题/选择题自动 accuracy；按能力类别和难度分项统计；人类专家基线 | Paper: https://arxiv.org/abs/2404.01475；Nature Chemistry: https://www.nature.com/articles/s41557-024-01649-1；Code/Data: https://github.com/lamalab-org/chembench |
| **LAB-Bench** | 2024 | Q0/Q1，生物研究 QA | 文献推理、数据库查询、图表理解、DNA/蛋白序列与实验流程等实验室任务 | 多选题 accuracy；按 LitQA、DBQA、FigQA、SeqQA 等子集报告；部分任务要求检索或数据库 grounding | Paper: https://arxiv.org/abs/2407.10362；Code/Data: https://github.com/Future-House/LAB-Bench |
| **ControlBench** | 2024 | Q0，控制理论设计推理 | block diagram、root locus、频域、状态空间、稳定性和控制器设计 | 147 个开放题由专家标注；100 个 ControlBench-C 多选题自动 ACC；另报告 self-check ACC | Project: https://agi4engineering.github.io/LLM4Control/；Paper: https://arxiv.org/abs/2404.03647 |
| **LitQA2 / PaperQA2** | 2024-09 | Q1，科学文献检索问答 | 248 道必须从科研文献检索证据才能回答的多选题；系统可以选择 insufficient information，并需给出来源 DOI | `precision` 只看作答题中的正确比例，`accuracy` 看全部题正确比例，`recall` 看是否检索/归因到标注 DOI；答案选项自动判定，检索与引用单独诊断，另有人类专家对照 | Paper: https://arxiv.org/abs/2409.13740；Code: https://github.com/Future-House/paper-qa；LitQA2 public split: https://github.com/Future-House/LAB-Bench/tree/main/LitQA2 |
| **ScholarQABench / OpenScholar** | 2024-11 | Q1，跨论文科学综述 | 2,967 个专家问题、208 个专家长答案，覆盖计算机、物理、神经科学和生物医学；还纳入 SciFact、PubMedQA、QASA 等单论文任务 | 短答案用 accuracy，QASA 用 ROUGE-L；长答案按问题专属 rubric 或五级量表评正确性、覆盖、相关性和组织；引用另做 entailment/citation correctness，并以专家盲评校准 | Paper: https://arxiv.org/abs/2411.14199；Code/Benchmark: https://github.com/AkariAsai/ScholarQABench；Agent: https://github.com/AkariAsai/OpenScholar |
| **BioASQ Challenge** | 2013 起，每年更新 | Q1，生物医学检索与问答挑战 | 从 PubMed/MeSH 做语义标引、文献与 snippet 检索，并回答 yes/no、factoid、list 和 ideal-answer 问题 | 检索阶段使用 MAP、GMAP、F1 等；yes/no 用 accuracy/F1，factoid/list 用 MRR、strict/lenient accuracy、F1；理想长答案使用 ROUGE 和人工专家评价。年度 test 答案在提交期保持隐藏 | Official/Tasks/Results: https://www.bioasq.org/ |
| **AstaBench 完整套件** | 2025-10 | Q1/W1/D2/D3，综合科学 Agent 套件 | 2,400+ 样例、11 个 benchmark，覆盖 PaperFinding、ScholarQA2、LitQA2、ArxivDIGESTables、CORE-Bench-Hard、SUPER、DiscoveryBench 和 E2E Discovery | 每个子任务调用独立 scorer：论文检索看召回/排名，QA 看答案与引用，代码看执行结果，Discovery 看专属 rubric；统一记录成功率、token/美元成本和版本，并比较 cost-quality Pareto；solve 与 score 可解耦 | Site: https://allenai.org/asta/bench；Paper: https://arxiv.org/abs/2510.21652；Code: https://github.com/allenai/asta-bench |
| **ResearcherBench** | 2026 | Q1，科学 Deep Research | 65 个真实科研问题、约 35 个 AI research subjects；包含 Technical Details、Literature Review、Open Consulting | 对最终研究报告做 rubric assessment；同时评引用 faithfulness、证据 groundedness 和问题覆盖 | Project/Paper/Code/Data/Leaderboard: https://researcherbench.github.io/ |
| **AutoResearchBench** | 2026-04 | Q1，科学文献发现 | 1,000 个问题；Deep Research 找唯一目标论文或判空，Wide Research 找完整相关论文集合 | Deep Research 用目标论文命中/判空 accuracy；Wide Research 用集合 IoU、precision/recall；统一 DeepXiv corpus 和 ReAct/search 协议 | Project/Leaderboard/Code/Data: https://cheryou.github.io/autoresearchbench.github.io/；Paper: https://arxiv.org/abs/2604.25256 |
| **LifeSciBench** | 2026-06 | Q1，生命科学科研判断 | 750 个自由作答任务；7 类 workflow × 7 个生命科学领域；附 1,062 个序列、结构、图表等科研产物 | 173 位专家编写 19,020 条 rubric criteria；逐准则判分并归一化，70% 为单题通过阈值；允许检索，但它仍是单轮评测 | Official: https://openai.com/index/introducing-life-sci-bench/ |
| **AARRI-Bench** | 2026-06 | Q1/W1，研究助理行为与研究生命周期 | 82 个容器化任务，4 类场景：context、mindset、hands-on、interaction；聚焦研究实习生在论文阅读、实验审计、协作沟通、纠错与决策上的细粒度行为 | Classic 0/1 reward；任务通过 Harbor 容器运行；当前最佳公开组合是 Mini-SWE-Agent + Claude Opus 4.7，overall 68.3%。它更像“研究行为质量”评测，而不是开放发现榜 | Site: https://aarr-bench.com/；Paper: https://arxiv.org/abs/2606.07462；GitHub: https://github.com/AARR-bench/AARRI-bench |
| **SGI-Bench** | 2025-12 | Q1/D1，科研四环能力雷达 | 1,000+ 专家任务、10 学科；Deliberation、Conception、Action、Perception，含检索、想法、代码和多模态实验推理 | 不同子任务使用 EM、step-level alignment、Implementation Similarity、PassAll@k、实验核验、多模态正确性等；按四环汇总 | Paper: https://arxiv.org/abs/2512.16969；Site: https://internscience.github.io/SGI-Page/；Code: https://github.com/InternScience/SGI-Bench；Data: https://huggingface.co/collections/InternScience/sgi-bench |
| **HeurekaBench** | 2026 | Q1/D2，co-scientist 数据分析问答 | 从真实论文和代码仓库构造开放数据分析问题，要求理解数据、方法与论文结论 | 对 answer quality、事实正确性和分析 critic 带来的改进进行 rubric/对照评估 | Project: https://brbiclab.epfl.ch/projects/heurekabench/；Paper: https://openreview.net/forum?id=Y7xCdFuFw7；Code: https://github.com/mlbio-epfl/HeurekaBench |

### 12.2 这类评测的可信度边界

1. **题集型 benchmark 只是能力探针**：GPQA、SciBench 等比通用考试题更科学化，但仍是固定题集，不是能让自主 Loop 持续提交实验的 evaluator/harness。
2. **自动正确率最可靠，但覆盖最窄**：MCQ、数值答案和短答案容易稳定评分，却无法证明 Agent 会设计和执行实验。
3. **检索题必须固定语料快照**：否则搜索引擎更新会导致结果不可复现，也容易通过网页直接找到答案。
4. **带引用不等于有依据**：需要单独检查 citation correctness、entailment 和 source quality。
5. **开放科研判断依赖 rubric**：LifeSciBench、ResearcherBench 的价值在于专家逐项 rubric，而不是让一个 LLM 给笼统总分。
6. **多模态科研推理需要核对原始 artifact**：只检查最终文本会漏掉图表误读、单位错误和统计口径错误。

Agents' Last Exam 和 Terminal-Bench Science 没放在本节，因为它们是长程软件/终端工作流，不是科学问答；二者已经在第 10 节说明。

---

## 13. 科学发现 Benchmark

### 13.1 想法与假设生成

| Benchmark | 提出时间 | 层级 / 范式 | 评测内容 | 如何评测 | 论文 / 代码 / 数据 |
|---|---:|---|---|---|---|
| **IdeaBench** | 2024-10 / KDD 2025 | D1，研究想法生成 | 8 个领域、2,374 篇高影响论文及其引用作为上下文，要求生成研究想法 | 两阶段评测：先由 GPT-4o 按用户指定的 novelty、feasibility 等质量维度做相对排序，再计算 rank-based `Insight Score`；不要求真正实现 Idea | Paper: https://arxiv.org/abs/2411.02429 |
| **ResearchBench** | 2025 | D1，灵感驱动假设生成 | 将科学发现拆为背景理解、灵感检索、灵感整合和假设生成 | 分阶段评检索命中、灵感相关性和假设质量；最终假设用参考发现与评审标准比较 | Paper: https://arxiv.org/abs/2503.21248 |
| **AI Idea Bench 2025** | 2025 | D1，AI 研究想法生成 | 基于 3,495 篇 2023-10 之后的 AI 论文及 inspiration papers 生成研究想法 | 与后续真实论文想法做匹配，并用 LLM/人工维度评 novelty、feasibility、effectiveness | Paper: https://arxiv.org/abs/2504.14191；Code: https://github.com/yansheng-qiu/AI_Idea_Bench_2025 |
| **Scientist-Bench** | 2025-05 | D1/D3，AI 科研创新 | 用真实 AI 论文构造 guided innovation（给方向）和 open-ended exploration（自主探索）两档任务，产出实现与论文 | 分开检查实现成功率和最终论文质量，并使用多模型裁判/人工对照评价贡献、实验和写作；开放档没有唯一 gold，不能视作纯客观榜分 | Paper: https://arxiv.org/abs/2505.18705；Project/Leaderboard: https://autoresearcher.github.io/；Code/Bench: https://github.com/HKUDS/AI-Researcher |
| **MOOSE-Chem** | 2025 | D1，化学假设再发现 | 给 background 和 inspiration corpus，要求恢复 51 篇未暴露的 2024 年高水平化学论文中的核心 hypothesis | 比较生成假设与隐藏论文假设的匹配；分解 background/inspiration/hypothesis quality，并结合专家或 LLM 评审 | ICLR: https://proceedings.iclr.cc/paper_files/paper/2025/hash/51fd9a7d1706023cb9f8210cc6ac357c-Abstract-Conference.html；Code: https://github.com/ZonglinY/MOOSE-Chem |
| **Matter to Mechanism / BatteryHypoBench** | 2026-06 | D1，材料/电池机制假设 | 2,645 个 problem-hypothesis pairs，要求从材料问题提出具体机制假设 | reasoning fidelity、problem alignment、mechanistic specificity、novelty、plausibility、decomposition 等多维评分 | Paper: https://arxiv.org/abs/2606.02258；Data: https://huggingface.co/datasets/Boson20/matter-to-mechanism |

这些 benchmark 主要评“Idea 文本是否像一个好假设”，并不自动证明 Idea 能跑通或能产生真实发现。要进入端到端科研评测，还必须继续经过实现、实验和结果证据验证。

### 13.2 数据驱动发现与开放分析

| Benchmark | 提出时间 | 层级 / 范式 | 评测内容 | 如何评测 | 论文 / 代码 / 数据 |
|---|---:|---|---|---|---|
| **DiscoveryBench** | 2024 | D1/D2，结构化数据发现 | 6 个领域；264 个真实论文反推任务 + 903 个合成任务；从数据和目标推出 context-variable-relationship 假设 | 将预测假设与隐藏金标在 context、variables、relationship 三部分做语义蕴含/结构化匹配，报告分项和总体正确率 | Paper: https://arxiv.org/abs/2407.01725；Code/Data: https://github.com/allenai/discoverybench |
| **BLADE** | 2024 | D2，分析决策发现 | 给研究问题和数据，Agent 选择 conceptual variables、data transformations 和 statistical model | 用专家多路径金标；变量做语义等价匹配，数据变换做 data-flow graph 匹配，模型函数做结构/执行比较，汇总 precision/recall/F1 | Paper: https://arxiv.org/abs/2408.09667；Code: https://github.com/behavioral-data/BLADE |
| **BixBench** | 2025-02 | D2，计算生物开放分析 | 论文初版为 50+ data capsules、近 300 题；当前 v1.5 仓库为 60 个真实 notebook/data capsules、205 个开放或多选问题，Agent 需写并运行 Jupyter 分析 | Agent 轨迹保留最终答案和 notebook；开放答案由 LLM grader 对参考答案判分，MCQ 用 exact match，并可对 5 次 replica 做 majority vote。主指标本质仍是答案 accuracy，不等价于对整份 notebook 的科学有效性审计 | Paper: https://arxiv.org/abs/2503.00096；Code: https://github.com/Future-House/BixBench；Data: https://huggingface.co/datasets/futurehouse/BixBench |
| **BAISBench** | 2025-05 | D1/D2，单细胞生物发现 | 两部分：15 个专家标注 scRNA-seq 数据集上的 cell type annotation；41 篇研究导出的 193 道 biological discovery MCQ | 注释任务使用考虑 cell-type hierarchy 的专用指标；发现任务要求分析相应数据后选择答案，以 193 题 accuracy 计分，并有人类 bioinformatician 基线。它不是隐藏开放结论评分 | Paper: https://arxiv.org/abs/2505.08341；Code: https://github.com/EperLuo/BAISBench；Data: https://huggingface.co/datasets/EperLuo/BaisBench |
| **Matbench Discovery** | 2023 / 2024 | D1，材料候选排序；ML 发现型 | 用通用机器学习势（MLIP）从未弛豫候选结构预测形成能、凸包距离和稳定性，模拟高通量稳定晶体发现 | 对 DFT reference 比较 formation-energy / hull-distance MAE；对稳定材料排序计算 F1、precision/recall、top-k 命中和 Discovery Acceleration Factor。它评的是 ML 候选筛选，不评显式机理发现 | Site/Leaderboard: https://matbench-discovery.materialsproject.org/；Code/Data: https://github.com/janosh/matbench-discovery |
| **ScienceAgentBench** | 2024 / ICLR 2025 | D2/Workflow，科研代码与分析阶段 | 从 44 篇同行评审论文抽取 102 个真实任务，覆盖生信、计算化学、GIS、心理与认知神经 | 容器化执行；评代码执行成功率、结果正确性和成本；任务由领域专家验证 | Paper: https://openreview.net/forum?id=6z4YKr0GK6；Code: https://github.com/OSU-NLP-Group/ScienceAgentBench |
| **FIRE-Bench** | 2026-02 | D2/D3，科学 insight 再发现 | 30 个来自 ICLR、ICML、NeurIPS、Nature 等论文的任务；要求 Plan→Implement→Execute→Analyze | 从 Agent 报告抽取 claims，与隐藏 reference insights 做 claim-level precision、recall、F1；同时检查可执行实验链 | Project: https://firebench.github.io/；Paper: https://arxiv.org/abs/2602.02905；Code: 项目页标注 coming soon |

### 13.3 机理、方程与科学定律发现

第 8、9 节已经详细介绍 SRBench、LLM-SRBench、SINDy 和 ODE discovery。这里补齐更偏 Agent 和主动发现的代表：

| Benchmark | 提出时间 | 层级 / 范式 | 评测内容 | 如何评测 | 论文 / 代码 / 数据 |
|---|---:|---|---|---|---|
| **AI Feynman** | 2020 | D1，物理方程恢复 | 从约 100 个 Feynman 物理方程的数值样本恢复解析表达式，利用量纲、对称性和可分离性等物理先验 | symbolic exact recovery；数值误差；表达式是否等价；在噪声或不同采样下的恢复率 | Paper: https://www.science.org/doi/10.1126/sciadv.aay2631；Code: https://github.com/SJ001/AI-Feynman |
| **SRBench / SRBench++** | 2021 / 2024 | D1，符号回归 | 真实回归与合成公式恢复；SRBench++ 增加噪声、外推、特征选择和解释性轨道 | test/OOD error、symbolic accuracy、表达式复杂度、运行时间；部分轨道加入 expert interpretability | SRBench: https://github.com/cavalab/srbench；SRBench++: https://openreview.net/forum?id=O0KkGajx6T |

这一方向目前最成熟的仍是“给定静态样本恢复已知方程”。真正允许 Agent 主动设计观测、
按实验预算交互并发现隐藏 governing law 的公开统一 benchmark 仍很少；不能把普通轨迹
拟合或符号回归数据集包装成“主动机理发现”。

### 13.4 科学代码、实验执行与论文复现

这类 benchmark 位于 W1/R1：它们要求真实执行并保留 artifact，但目标通常是实现或复现
已知工作，不应和“产生新科学发现”混为一谈。

| Benchmark | 提出时间 | 层级 / 范式 | 评测内容 | 如何评测 | 论文 / 代码 / 数据 / 榜单 |
|---|---:|---|---|---|---|
| **SciCode** | 2024-07 / NeurIPS 2024 | W1，科学代码生成 | 80 个主问题拆成 338 个子问题，覆盖物理、数学、材料、生物、化学等 16 个子领域；来源于真实科研计算、数值方法和模拟代码 | 在隔离环境执行 scientist-authored unit tests；分别报告 subproblem resolve rate 和只有全部子问题均通过才计成功的 main-problem resolve rate，可比较是否提供科学背景 | Site/Leaderboard: https://scicode-bench.github.io/；Paper: https://arxiv.org/abs/2407.13168；Code: https://github.com/scicode-bench/SciCode；Data: https://huggingface.co/datasets/SciCode1/SciCode |
| **SUPER** | 2024-09 | W1/R1，科研仓库执行 | 45 个端到端 research-repo 任务、152 个专家子任务、602 个自动生成任务；安装依赖、找命令、改配置并跑出论文仓库结果 | 有 gold solution 时执行自动检查任务成功与进度；无完整 gold 时用近似 progress measures；分别报告 end-to-end success 和 scenario/subproblem 成功率 | Paper: https://arxiv.org/abs/2409.07440；Code: https://github.com/allenai/super-benchmark |
| **CORE-Bench** | 2024-09 | R1，计算可复现性 | 90 篇计算机科学、社会科学、医学论文构造 270 个三级难度任务；给代码和数据，要求复现论文结果 | 并行 evaluator 对 Agent 输出和论文 reference result 做任务级正确性检查，支持纯文本和视觉-文本产物；报告各难度 accuracy | Paper: https://arxiv.org/abs/2409.11363；Code: https://github.com/siegelz/core-bench |
| **PaperBench** | 2025-04 | R1，从零论文复现 | 从零复现 20 篇 ICML 2024 Spotlight/Oral：理解贡献、建立代码库并执行实验，不提供作者代码 | 作者共同制定层级 rubric，共 8,316 个可判定节点；LLM judge 逐节点给 replication score，并用独立 judge benchmark 与人工评分校准；另有人类 ML PhD 基线 | Official: https://openai.com/index/paperbench/；Paper: https://arxiv.org/abs/2504.01848；Code: https://github.com/openai/frontier-evals |
| **Paper2CodeBench / PaperCoder** | 2025-04 / ICLR 2026 | R1，paper-to-repository | 从 ML 论文生成结构完整、可运行且忠实于论文的代码仓库 | 以作者仓库（若有）为参照做 model-based 与人工评价，并邀请论文作者评价实现忠实度；同时在 PaperBench/Code-Dev 口径上比较 | Paper: https://arxiv.org/abs/2504.17192；Code/Data: https://github.com/going-doer/Paper2Code |
| **NatureBench** | 2026-06 | R1 + 刷分型，科学 ML SOTA 复现/超越 | 90 个来自 Nature-family 论文的跨学科任务；禁用 web search、隐藏源方法，每题提供标准化容器、公开训练数据和无标签测试输入 | 冻结 `run.py` 后在隐藏 GT 上运行每题官方 evaluator；按论文 SOTA 做相对 improvement，多实例取均值，`>0.1` 计 Surpass-SOTA；最后对最佳提交做 post-hoc validity judge 排除泄漏/硬编码 | Paper: https://arxiv.org/abs/2606.24530；Code: https://github.com/FrontisAI/NatureBench；Data: https://huggingface.co/datasets/FrontisAI/NatureBench |
| **Aviary scientific environments** | 2024-12 | W1/D1，交互式科学环境 | 将 Agent 形式化为 language decision process；科学环境包括分子克隆 DNA 操作、科研文献问答和蛋白稳定性工程 | 每个环境提供可执行 action/observation API 和 task-specific reward/evaluator，比较成功率、累计 reward、推理/工具调用成本以及训练前后性能；比一次性 QA 更适合多步 Agent | Paper: https://arxiv.org/abs/2412.21154；Code: https://github.com/Future-House/aviary |
| **SciAgentGym** | 2026-02 | Q1/W1，多步科学工具调用 | 259 个任务、1,134 个子问题；Agent 在隔离实例中调用 1,780+ 个物理、化学、材料、生命科学和天文工具，含文本与多模态任务 | 环境校验函数参数并保存完整轨迹；从最终 `boxed` 答案抽取结果，与数值/结构化 gold 做灵活匹配并汇总正确率，也可比较禁用工具基线。当前主分仍偏最终答案，不等于评估开放发现 | Paper: https://arxiv.org/abs/2602.12984；Code/Data/Tools: https://github.com/CMarsRover/SciAgentGYM |
| **SciVisAgentBench** | 2026-03 | W1，科学可视化 Agent | 用自然语言驱动 ParaView、napari、VMD/GROMACS 和拓扑工具，完成体数据、生物图像、分子与拓扑可视化 action/workflow | 在隐藏 GT、隔离容器中检查输出文件；文本/视觉结果用逐项 LLM rubric，图像用三视角 PSNR、SSIM、LPIPS；scaled 指标乘以任务完成率，避免只完成少数简单题却得到虚高画质分 | Paper: https://arxiv.org/abs/2603.29139；Project: https://scivisagentbench.github.io/；Code: https://github.com/KuangshiAi/SciVisAgentBench；Data: https://huggingface.co/datasets/SciVisAgentBench/SciVisAgentBench-tasks |
| **Biomni-Eval1** | 2025 | W1/Q1，生物医学 action/reasoning | 433 个实例、10 类任务，含 GWAS causal gene、rare disease、CRISPR delivery、lab-bench QA 等 | 调用官方 `BiomniEval1.evaluate(task, id, answer)` 做任务特定的结构化答案比较并汇总得分；它覆盖工具增强推理，但多数任务不是完整湿实验执行 | Paper: https://www.biorxiv.org/content/10.1101/2025.05.30.656746v1；Code: https://github.com/snap-stanford/Biomni；Data: https://huggingface.co/datasets/biomni/Eval1 |
| **BioAgent Bench** | 2024 起持续更新 | W1，生信 pipeline | 10 个真实/模拟生信任务，含 RNA-seq、单细胞、variant calling、comparative genomics、metagenomics、transcript quantification 等 | 每题输出 VCF/CSV/TSV 等指定 artifact，与模拟 truth、GIAB 等可信 reference 或复现结果比较；不同任务 evaluator 尚未完全统一，仓库也明确提醒部分“truth”并非严格 ground truth | Code/Tasks: https://github.com/bioagent-bench/bioagent-bench |

### 13.5 端到端数字科学发现

| Benchmark | 提出时间 | 层级 / 范式 | 评测内容 | 如何评测 | 论文 / 代码 / 数据 / 榜单 |
|---|---:|---|---|---|---|
| **DiscoveryWorld** | 2024 | D3，模拟科学发现 | 120 个任务、8 个主题、3 个难度；在虚拟世界中观察、实验、提出并验证假设 | 三类自动指标：任务是否完成、细粒度流程/报告卡、发现知识的准确率；环境状态提供可信 evaluator | Paper: https://arxiv.org/abs/2406.06769；Site/Code: https://allenai.github.io/discoveryworld/ |
| **Curie Experimentation Benchmark** | 2025-02 | D3，计算实验验证 | 46 个来自论文和开源项目的计算机科学实验问题，要求形成假设、实现可复现 workflow、真实执行并从结果得到结论 | LLM verifier 读取问题、隐藏结论和完整实验日志，分别检查实验设计、执行可运行性、实现与设计一致性、结论正确性，全部通过才判 Correct；因此比只比较最终回答更严格，但裁判仍是模型 | Paper: https://arxiv.org/abs/2502.16069；Code: https://github.com/Just-Curieous/Curie |
| **AstaBench E2E Discovery** | 2025 | D3，开放端到端发现 | 输入一个研究想法/目标，不给方法或目标论文；Agent 自主设计实验、执行、分析并提交 report、code、artifacts | 每题专属分层 rubric，由分步 LLM judge 逐项检查最终产物；同时记录成本、模型/commit 版本并画 cost-quality Pareto | Site: https://allenai.org/asta/bench；Paper: https://arxiv.org/abs/2510.21652；Code: https://github.com/allenai/asta-bench |
| **ARC-Bench** | 2026-05 | D3，多领域问题→实验 | 当前仓库 55 topics / 5 领域：ML、高能物理、量子、生物、统计；只给研究问题和 manifest，要求 code→measurements→claims→writeup（论文主实验使用其中 25 topics） | 层级 rubric 检查代码开发、代码执行、结果分析、writeup；定量项按容差给部分分；claims 必须由 metrics 支撑；auto judge + manual audit | Paper: https://arxiv.org/abs/2605.20025；Code: https://github.com/aiming-lab/AutoResearchClaw/tree/main/experiments/arc_bench；Data: https://huggingface.co/datasets/AIMING-Lab-UNC/ARC-Bench |
| **ResearchClawBench** | 2026-06 | D3，再发现→新发现 | 40 个任务、10 学科；给相关文献和原始数据，但隐藏目标论文，要求独立得到相同或更好的结论 | 专家标注多模态 rubric + 同行评审式评分；以隐藏论文为参照评分析、证据、结论和报告；支持在线 leaderboard | Paper: https://arxiv.org/abs/2606.07591；Code: https://github.com/InternScience/ResearchClawBench；Data: https://huggingface.co/datasets/InternScience/ResearchClawBench |
| **EXP-Bench** | 2025 / ICLR 2026 | D3，计算实验闭环 | 461 个任务、51 篇论文；给研究问题和不完整 starter code，要求假设→设计→实现→执行→分析 | 分阶段检查实验设计、实现忠实度、可执行性和结论；最终以完整实验成功率衡量长链路闭环 | Paper: https://arxiv.org/abs/2505.24785；Code: https://github.com/Just-Curieous/Curie/tree/main/benchmark/exp_bench |
| **FIRE-Bench** | 2026-02 | D3，研究洞察再发现 | 完整执行 Plan→Implement→Execute→Analyze，从真实论文任务恢复隐藏 insight | claim-level precision/recall/F1；只有实际执行并被证据支持的 claim 才应命中 | Project: https://firebench.github.io/；Paper: https://arxiv.org/abs/2602.02905 |
| **MLR-Bench** | 2025 / NeurIPS 2025 | D3，开放式 AI 科研 | 201 个 workshop 级 ML 研究任务，要求完成 idea、proposal、实验和论文，可按阶段或端到端运行 | MLR-Judge 用多名 LLM reviewer 按研究问题、方法、实验、写作等 rubric 评分，并用人工专家判断校准；没有唯一 gold metric，因此应同时保留代码和实验 artifact | Project: https://chchenhui.github.io/mlrbench/；Paper: https://papers.nips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html |
| **MLRC-Bench** | 2025 / NeurIPS 2025 | D3 + 刷分型，ML 方法创新 | 7 个真实 ML research competition，Agent 需提出并实现方法，缩小 starter baseline 与顶尖人类提交之间的差距 | 代码在每题官方 objective evaluator 上运行，报告相对 baseline、top-human gap closure 和有效提交率；另用 LLM judge 评价创新性并分析其与真实分数的不一致 | Paper: https://proceedings.neurips.cc/paper_files/paper/2025/hash/82c96f3c90741ef2c9b248e65d9b5db0-Abstract-Datasets_and_Benchmarks_Track.html；Code/Leaderboard: https://huggingface.co/spaces/launch/MLRC_Bench |
| **MADE** | 2026 | D3，闭环材料发现 / oracle search | 面向材料发现的预算受限闭环环境；Agent 在候选空间中提出材料或结构候选，调用 evaluator / oracle 获得性质反馈，再迭代搜索更优候选 | 以固定预算下的 top-k 命中、best-found property、sample efficiency / oracle calls 等衡量；更像 AInstein Track B 的“实体候选发现”，ground truth 来自离线 oracle / 仿真或数据库，不是新湿实验 | Paper/OpenReview: https://openreview.net/forum?id=nrXxVDYMMF |

### 13.6 类型速查：SOTA / Discovery / Workflow

这张表是给非领域读者快速判断用的。一个 benchmark 可以同时属于多类，例如 NatureBench 同时是
Reproduction 和 SOTA；AstaBench 同时覆盖 QA、Workflow、Discovery。

| 类型 | 代表 benchmark / 系统 | 主要看什么 | 边界 |
|---|---|---|---|
| **SOTA / Leaderboard** | NatureBench、Open Catalyst、Matbench、Matbench Discovery、JARVIS-Leaderboard、MLRC-Bench、ResearchClawBench、AutoResearchBench | 是否在固定 evaluator / leaderboard 上超过 prior best、论文 SOTA 或人类/强基线 | 分数高通常证明任务内有效，不自动证明开放科学发现 |
| **Prediction / Surrogate** | PDEBench、WeatherBench 2、CFDBench、QM9、MD17、rMD17、MD22、PCQM4Mv2、QMugs、SPICE、ANI、Matbench | ML 是否能近似 PDE、DFT、MD、实验或观测标签 | 需要额外看 OOD、物理一致性、长期稳定性和计算成本 |
| **Scientific Computing** | SciMLBenchmarks.jl、PDEBench、CFDBench、Open Catalyst、MD17/MD22、Transition1x、Terminal-Bench Science | 科学计算是否准确、稳定、可执行、成本合理 | 主要证明计算或模拟能力，不一定要求新假设 |
| **Workflow** | Terminal-Bench Science、ScienceAgentBench、SciCode、SUPER、SciAgentGym、SciVisAgentBench、Biomni-Eval1、BioAgent Bench、Aviary、AstaBench、AARRI-Bench | Agent 能否调工具、跑代码、处理数据并留下 artifact | workflow 成功不等于发现新规律；要看输出 claim 是否被证据支持 |
| **Reproduction** | CORE-Bench、PaperBench、Paper2CodeBench、NatureBench、SUPER、ResearchClawBench、FIRE-Bench | 能否复现论文、仓库、隐藏结果或论文级 insight | 多数是“已知答案再发现”，可评分但不是纯开放创新 |
| **Discovery：数据/关系** | DiscoveryBench、BLADE、BixBench、BAISBench、HeurekaBench | 能否从数据中恢复变量、变换、统计关系或论文结论 | 通常依赖隐藏 gold 或专家路径，不等于真实新发现 |
| **Discovery：假设/机理/方程** | IdeaBench、ResearchBench、MOOSE-Chem、Matter to Mechanism、BatteryHypoBench、AI Feynman、SRBench、LLM-SRBench、ODEBench | 能否提出可验证假设、恢复方程、解释机制 | 文本假设质量和真实可验证性要分开看 |
| **Optimization / Inverse Design** | Design-Bench、Sci Modeling Bench / design-bench、Matbench Discovery、MADE | 能否在有限数据或有限 oracle 预算下提出更优候选 | 要区分纯离线优化、可查询 oracle 的闭环优化，以及完整科研 workflow |
| **Discovery：端到端数字闭环** | DiscoveryWorld、Curie、AstaBench E2E、ARC-Bench、ResearchClawBench、EXP-Bench、FIRE-Bench、MLR-Bench、MADE | 能否规划、执行、分析并提交带证据的结论或候选 | 评分要读 code、logs、metrics、claims、report，不能只看最终文本 |
| **Simulation Loop / 最像 AInstein** | MADE、DiscoveryWorld、Aviary scientific environments、Curie、ARC-Bench、AstaBench E2E | 是否有封闭环境、可调用 oracle / simulator、多轮反馈和预算约束 | MADE 最接近材料候选发现；DiscoveryWorld 更偏通用模拟科学；Curie/ARC 更偏代码实验闭环 |
| **Wet-lab Case** | Coscientist、ChemCrow、Robin、ElementsClaw、OpenAI wet-lab protocol evaluation | 是否由真实实验、样品、机器人或湿实验结果验证 | 证据强，但通常是系统 case study，不是统一 benchmark suite |

如果只问“最像 AInstein Bench”的公开方向，优先看 **MADE、DiscoveryWorld、Aviary、Curie、ARC-Bench、AstaBench E2E**：

| Benchmark | 像 AInstein 的地方 | 不同点 |
|---|---|---|
| **MADE** | 材料发现、候选搜索、oracle 反馈、预算约束，接近 Track B 实体候选发现 | 重点是候选优化，不一定要求输出完整科学原理或数学形式 |
| **DiscoveryWorld** | 封闭模拟世界、观察-实验-假设-验证闭环，有自动 evaluator | 领域更通用，不专门面向凝聚态/材料/分子系统 |
| **Aviary scientific environments** | 多步 action/observation 环境，支持 reward/evaluator 和工具调用轨迹 | 是环境框架集合，不是单一材料或量子发现榜 |
| **Curie / EXP-Bench** | 要提出假设、写代码、执行实验、读结果并形成结论 | 主要是计算实验和论文/代码任务，不是内置物理仿真沙箱 |
| **ARC-Bench** | 给研究问题和 manifest，要求 code→measurements→claims→writeup | 更像多领域自动研究复现/发现，不一定固定为材料候选 oracle |
| **AstaBench E2E** | 开放研究目标、端到端产物、分层 rubric 和成本记录 | 更依赖 rubric / judge，不一定有统一物理 simulator ground truth |

### 13.7 真实实验闭环：目前更多是系统实证，不是统一 Benchmark

真实实验最接近 D4，但实验材料、仪器、安全审批、批次差异和周期很难标准化，所以当前
更常见的是系统论文中的真实 case study，而不是可反复提交的公共 leaderboard。

| 系统 / 实证 | 提出时间 | 真实实验内容 | 如何验证 | 证据与边界 | 链接 |
|---|---:|---|---|---|---|
| **Coscientist** | 2023 | LLM 调用搜索、代码、文档和机器人 API，完成 Suzuki / Sonogashira 等化学实验与条件优化 | 专家评价合成规划；机器人真实执行；以反应是否成功和测量结果为准 | 是强 D4 证据，但任务数有限且硬件平台专有，不是标准 leaderboard | Nature: https://www.nature.com/articles/s41586-023-06792-0；Code: https://github.com/gomesgroup/coscientist |
| **ChemCrow** | 2023 | 通过 18 个化学工具完成有机合成、药物和材料任务，并规划/执行驱虫剂、3 个有机催化剂及新 chromophore 的实验 | 化学专家与 LLM 分别盲评任务答案；真实合成以产物和实验结果验证。论文同时发现 GPT-4 judge 无法可靠区分明显错误答案，说明专家/实验层不可省 | 属于工具增强和少量实验案例，不是统一可提交 benchmark | Paper: https://arxiv.org/abs/2304.05376；Nature Machine Intelligence: https://www.nature.com/articles/s42256-023-00788-7 |
| **Robin** | 2025 | 围绕干性 AMD 做文献检索、药物重定位假设、实验建议、接收湿实验结果后继续迭代 | 用真实生物实验结果支持或否定候选，形成跨轮反馈 | 证明单个发现闭环可行；不能用一个疾病案例替代覆盖多任务的 benchmark | Paper: https://arxiv.org/abs/2505.13400；Code: https://github.com/Future-House/robin |
| **ElementsClaw** | 2026-04 | 从 240 万稳定晶体筛选超导候选，合成并验证 4 个新超导体 | 实际合成；测得转变温度 `Tc`；同时在 SuperCon3D 外做已知材料再发现 | 实验验证是最强证据；大规模筛选主要仍由 ML/LAM 完成，不等于统一机理发现 benchmark | Paper: https://arxiv.org/abs/2604.23758；Project: https://elementsclaw.org/ |
| **OpenAI wet-lab protocol evaluation** | 2026-08 | 用 AI 优化 molecular cloning protocol，并在真实实验室比较工作流 | 按真实实验成功、耗时和实验过程指标比较 AI 辅助与对照流程 | 是现实评测框架/案例，不是已开放任务集或可提交 leaderboard | Official: https://openai.com/index/accelerating-biological-research-in-the-wet-lab/ |

### 13.8 端到端发现的评测为什么更难

1. **有隐藏论文不等于纯开放发现**：ResearchClawBench、FIRE-Bench 更接近 rediscovery；优势是可评分，局限是答案事实上已知。
2. **纯开放任务没有唯一正确答案**：AstaBench E2E 只能依靠任务 rubric、产物证据和 judge 校准，无法像 classification 一样给绝对 ground truth。
3. **必须把工程失败和科学结论分开**：代码未运行不能推导为 hypothesis 错误；应分别记录 implementation validity 和 scientific result。
4. **最终文本不能代替实验产物**：可靠评测必须读取 code、environment、run logs、metrics、figures、claims 和引用证据。
5. **发现结论必须可追溯**：每个 claim 应关联数据、分析代码、随机种子和 evaluator 输出，避免“写出一个像论文的故事”获得高分。

---

## 14. 代表性科学发现 Agent 及其评测

下面列的是系统，不应和 benchmark 混为一谈。它们的评测通常组合公开 benchmark、专家评审和案例/真实实验验证。

| Agent / 系统 | 提出时间 | 端到端层级 | 主要科学任务 | 使用了什么评测、如何评测 | 论文 / 代码 / 项目 |
|---|---:|---:|---|---|---|
| **Google AI co-scientist** | 2025；Nature 2026 | L2-L3 | 文献 grounding、假设生成、反思、辩论与排序，生物医学为主 | 对 203 个研究目标做候选假设 Elo tournament；专家/盲评开放问题；另用药物重定位、靶点和抗菌机制案例验证 | Paper: https://www.nature.com/articles/s41586-026-10644-y；Preprint: https://arxiv.org/abs/2502.18864 |
| **OpenScholar** | 2024-11 | L2 | 从 4,500 万篇开放论文检索证据，生成带引用的跨论文科学综述 | ScholarQABench 评正确性、覆盖、相关性、组织与 citation correctness；另由领域专家对系统答案和专家答案做盲选偏好 | Paper: https://arxiv.org/abs/2411.14199；Code: https://github.com/AkariAsai/OpenScholar；Benchmark: https://github.com/AkariAsai/ScholarQABench |
| **PaperQA2** | 2024 | L2 | 科学文献检索、证据汇总、带引用回答和矛盾发现 | LitQA2 上评 precision/accuracy/正确 DOI recall；WikiCrow 由领域专家盲评 statement correctness 与 citation support；ContraCrow 的矛盾由人工专家验证 | Paper: https://arxiv.org/abs/2409.13740；Code: https://github.com/Future-House/paper-qa |
| **ResearchAgent** | 2024-04 / NAACL 2025 | L2 | 从种子论文沿学术图谱和跨论文概念检索，生成问题、方法和实验设计，并由 ReviewingAgents 迭代修改 | 在多学科论文上由人类和模型分别评价 idea 的 novelty、clarity、validity 等；它评的是研究构想质量，没有执行实验来证明 idea 有效 | Paper: https://arxiv.org/abs/2404.07738 |
| **FutureHouse Robin** | 2025 | L3-L4 | 文献检索→假设→实验建议→结果分析→继续迭代 | 干性 AMD 药物重定位案例；最终依赖真实生物实验反馈，不只由 LLM judge 自评 | Paper: https://arxiv.org/abs/2505.13400；Code: https://github.com/Future-House/robin |
| **Coscientist** | 2023 | L4 | 化学检索、合成规划、代码与机器人实验 | 6 类化学任务；合成规划专家评估；Suzuki/Sonogashira 等真实机器人实验和优化任务，以实验是否成功及真实测量为准 | Nature: https://www.nature.com/articles/s41586-023-06792-0；Code: https://github.com/gomesgroup/coscientist |
| **Biomni** | 2025 | L3 | 通用生物医学 action space：数据库、软件、代码、实验方案与假设 | Biomni-Eval1 的 433 个结构化任务；LAB-Bench/HLE 生物子集；另用真实研究 case study。正式 benchmark 结果和案例证据应分开报告 | Paper: https://www.biorxiv.org/content/10.1101/2025.05.30.656746v1；Code: https://github.com/snap-stanford/Biomni |
| **BrainPilot** | 2026-07 | L3 | PI Agent 协调脑科学专家 Agent，结合知识库、skill library、Graph of Trace 与审计器 | Agents' Last Exam 的 3 个脑科学任务、BrainPilotBench-v0 和端到端案例；检查任务结果、成本、可追踪证据和 fabrication audit | Paper: https://arxiv.org/abs/2607.15079；Data: https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public |
| **BrainAgent** | 2026-06 | L3 | 将自然语言脑信号分析目标转成可执行的多 Agent pipeline | 自建系统性脑信号 benchmark，重点报告端到端 task completion / pipeline reliability 等；目前主要是系统配套评测，第三方可提交榜成熟度有限 | Paper: https://arxiv.org/abs/2606.25400 |
| **MOOSE-Chem** | 2025 | L2-L3 | 从背景和 inspiration corpus 生成化学假设 | 在 51 篇隐藏高水平化学论文上做 hypothesis rediscovery，比较生成假设与真实核心发现 | ICLR: https://proceedings.iclr.cc/paper_files/paper/2025/hash/51fd9a7d1706023cb9f8210cc6ac357c-Abstract-Conference.html；Code: https://github.com/ZonglinY/MOOSE-Chem |
| **PiEvo** | 2026 | L3 | principle-evolvable discovery，通过 uncertainty minimization 演化科学原理/解法 | 在多个科学/算法发现任务上使用可执行 evaluator，比较 solution quality、收敛过程和 principle evolution；不是只做文本 novelty 评分 | Paper: https://arxiv.org/abs/2602.06448；Code: https://github.com/amair-lab/PiEvo |
| **Curie** | 2025-02 | L3 | 假设→实验设计→代码→执行→分析，强调可靠性、对照和可复现性 | 自建 46 题实验 benchmark；verifier 对日志逐项检查设计、执行、实现一致性与结论；后续又在 EXP-Bench 的 461 个任务上评完整实验成功率 | Paper: https://arxiv.org/abs/2502.16069；Code: https://github.com/Just-Curieous/Curie；EXP-Bench: https://arxiv.org/abs/2505.24785 |
| **ScientistOne** | 2026-05 | L3 | 文献综述、solution discovery、代码实验和论文写作全程维护 Chain-of-Evidence | 对 5 个系统、5 个 frontier task 的 75 篇论文做 CoE Audit：score 可复验、规范违规、引用真实性、method-code alignment；另在 MLE-Bench、Parameter Golf 等 6 个外部任务验证泛化 | Project: https://scientist-one.github.io/；Paper: https://arxiv.org/abs/2605.26340；Artifacts: https://github.com/scientist-one/generated-artifacts |
| **SciAgents** | 2024-09 | L2-L3 | 材料学本体知识图谱 + 多 Agent 推理，生成跨领域材料假设、机制和设计原则 | 主要用生物启发材料 case studies、模型批评和人工定性审查展示假设；没有隐藏 evaluator、统一任务集或真实材料合成，因此属于发现系统证据而非 benchmark 成绩 | Paper: https://arxiv.org/abs/2409.05556 |
| **ElementsClaw** | 2026-04 | L3-L4 | 超导材料候选筛选与发现 | 在 SuperCon3D 外做 rediscovery；筛选 2.4M 稳定晶体、得到高置信候选；最终用 4 个新超导体的实验验证作为最强证据 | Project: https://elementsclaw.org/；Paper: https://arxiv.org/abs/2604.23758 |
| **Agent Laboratory** | 2025-01 | L3 | 人给研究 Idea，系统完成文献、实验和报告，可在阶段间接受人类反馈 | 多位研究者评价最终论文；比较不同 LLM 与 human-feedback ablation；代码结果也与既有方法/SOTA 比较，但没有统一第三方 discovery benchmark | Project: https://agentlaboratory.github.io/；Paper: https://arxiv.org/abs/2501.04227；Code: https://github.com/SamuelSchmidgall/AgentLaboratory |
| **AI-Researcher** | 2025-05 | L3 | 文献→假设→算法实现→实验→论文的 AIforAI 自主科研 | 配套 Scientist-Bench 的 guided/open exploration；评实现成功和多裁判/人工论文质量，也在 MLReplicate 等复现口径比较 | Project: https://autoresearcher.github.io/；Paper: https://arxiv.org/abs/2505.18705；Code: https://github.com/HKUDS/AI-Researcher |
| **The AI Scientist / v2** | 2024 / 2025 | L3 | ML idea→code→experiment→figure→paper→review | 在多个 ML 子领域运行完整研究；自动 reviewer 和 workshop submission 评论文质量、实验结果与成本；本质是 AIforAI，不是自然科学实验 | v1: https://arxiv.org/abs/2408.06292；Code: https://github.com/SakanaAI/AI-Scientist；v2: https://github.com/SakanaAI/AI-Scientist-v2 |
| **Hyra** | 2026 | L2-L3 | 通用 research/engineering，覆盖 AI4AI、AI4S、数学和工程 | 公开 results repo 展示不同领域任务结果；当前更适合作系统案例和架构参考，正式统一 benchmark 协议仍需以论文/技术报告为准；详见 [Hyra Benchmark / Result 汇总](./HYRA_BENCHMARKS_CN.md) | Official: https://hy.tencent.com/research/hyra；Results: https://github.com/Tencent-Hunyuan/hyra-results |

真实发现最可信的证据层级通常是：**隐藏 evaluator / 已知规律再发现 < 专家 rubric < 独立实验复现 < 新材料、新药物或新机制的真实实验验证**。系统论文中的 case study 可以证明可行性，但不能替代覆盖面足够的第三方 benchmark。

---

## 15. 可以如何用于我们自己的科研智能体 benchmark

如果我们要评测一个科研智能体，不只是评测它“会不会找论文”，而是评测它能不能判断某个科学问题适合哪类方法，可以设计如下任务。

### 15.1 任务输入

给智能体一个科学问题，例如：

- 给定流体边界条件，预测流场；
- 给定化学结构，预测吸附能；
- 给定动力系统轨迹，发现控制方程；
- 给定天气初始状态，预测未来 7 天；
- 给定实验观测，判断应该用 ML surrogate、数值 solver 还是符号建模。

### 15.2 允许的解法类型

1. **ML prediction**：训练或调用模型进行预测；
2. **数值求解**：使用 PDE/ODE/CFD/DFT/MD solver；
3. **解析或符号方法**：推导公式、符号回归、方程发现；
4. **混合方法**：PINN、Neural ODE、UDE、ML-corrected solver；
5. **文献方法选择**：通过文献调研判断当前领域中最优实践。

### 15.3 统一评测维度

| 维度 | 含义 | 示例指标 |
|---|---|---|
| 准确性 | 结果是否接近 ground truth | MAE、RMSE、relative error、field error |
| 计算成本 | 求解是否高效 | wall-clock time、GPU hours、function evaluations |
| 泛化性 | 是否能跨参数、边界、分布泛化 | OOD error、new geometry error、new material error |
| 物理一致性 | 是否满足守恒律/约束 | mass conservation error、energy drift、force consistency |
| 稳定性 | 长期 rollout 是否发散 | long-horizon error、trajectory stability |
| 可解释性 | 是否输出科学上可理解的机制 | equation recovery、expression complexity、expert score |
| 方法选择质量 | 是否选对解法路线 | expert preference、cost-quality tradeoff |
| 推理正确性 | 科学结论、公式和单位是否正确 | exact match、expert correctness、calculation checks |
| 证据忠实度 | 回答和 claim 是否由文献/数据/实验支撑 | citation entailment、claim-evidence coverage |
| 发现质量 | 假设或 insight 是否具体、有价值且非重复 | hypothesis match、novelty rubric、claim precision/recall |
| 执行完整性 | 研究是否真实运行并留下可复现产物 | executable rate、artifact validity、workflow success |

### 15.4 可能的 gold workflow

一个理想智能体面对科学问题时，不应该直接套 ML，而应走：

1. **问题分类**：这是 PDE、ODE、材料性质、量子化学、天气、方程发现，还是实验数据建模？
2. **传统科学方法识别**：该领域的 standard solver / baseline 是什么？
3. **ML 方法识别**：是否已有 neural operator、surrogate、foundation model 或 ML potential？
4. **混合方法识别**：是否存在 physics-informed 或 solver-in-the-loop 方法？
5. **benchmark 对齐**：有没有已有 benchmark 可用？如果没有，应该构造什么评价集？
6. **评测指标选择**：不能只选 MAE，应包含成本、稳定性、物理一致性等。
7. **推荐方法路线**：根据科学目标选择“数值优先 / ML 加速 / 混合建模 / 符号发现”。

---

## 16. 初步结论

1. **科学 benchmark 不能只分成刷分和 workflow。**  
   至少还应单独区分闭卷科学问答、可检索科研判断、数据驱动发现、假设/机理再发现、端到端数字科研和真实实验闭环。

2. **最贴近“ML vs 数值求解”的是 PDEBench、SciMLBenchmarks.jl、WeatherBench 2。**  
   这三类明确允许或鼓励数据驱动方法和传统科学计算方法同台比较。

3. **最贴近“ML vs 第一性原理计算”的是 Open Catalyst、Matbench、QM9/MD17/PCQM4Mv2/QMugs/SPICE。**  
   它们体现了用 ML 近似昂贵科学计算的典型路线。量子化学 benchmark 已经相对成熟，但要区分小分子性质预测、ML 势函数、反应过渡态、催化/材料和 workflow agent 这几层。

4. **最贴近“ML vs 数学推导/科学规律发现”的是 SRBench、SRBench++、LLM-SRBench、SINDy/ODE discovery。**  
   这类任务不是只预测，而是要求给出可解释公式或机制。

5. **科学推理与科研判断也必须拆开看。**  
   FrontierScience 诊断闭卷专家推理；ScholarQABench、LitQA2 和 BioASQ 诊断检索、综述与引用；ResearcherBench、LifeSciBench 和 SGI-Bench 使用更细的专家 rubric。AstaBench 则把其中多类任务放进统一 Agent harness，但这些能力仍不能单独证明 Agent 完成了发现闭环。

6. **最贴近数据/假设发现的是 DiscoveryBench、BLADE、BAISBench、MOOSE-Chem 和 Matter to Mechanism。**  
   它们比普通预测 benchmark 更强调关系、机制和证据，但大多数仍属于“隐藏答案再发现”。

7. **科研执行/复现必须单独报告。**  
   SciCode、SciAgentGym、SciVisAgentBench、SUPER、CORE-Bench、PaperBench 和 NatureBench 分别证明代码、工具、可视化、仓库执行或复现能力；它们的目标工作或答案通常已知，不能直接算作新发现。

8. **最贴近端到端数字科学发现的是 DiscoveryWorld、Curie、AstaBench E2E、ARC-Bench、ResearchClawBench、EXP/FIRE-Bench、MLR-Bench 和 MADE。**  
   MLRC-Bench 提供了更客观的执行分数，但研究空间更接近固定竞赛；MADE 更接近材料候选发现的 closed-loop oracle search。开放研究则必须联合检查代码、执行结果、claims、报告和证据链，不能只让 LLM 阅读最终答案后给一个总分。

9. **如果我们设计自己的科研智能体 benchmark，需要把方法选择也纳入评测。**  
   也就是说，不只是看最终预测误差，而是看智能体是否知道：什么时候查文献，什么时候用数值 solver，什么时候用 ML surrogate，什么时候应该做方程发现，什么时候应该做混合建模。

10. **真实实验仍是新发现最强的验证。**  
   AI co-scientist、ChemCrow、Robin、Coscientist、ElementsClaw 等系统的强证据来自专家或真实实验；但 case study 覆盖有限，仍应和第三方 benchmark 分开报告。

11. **量子生物目前更像机制验证任务，不像成熟刷分榜。**  
    光合作用激子转移、酶/质子隧穿、radical-pair 磁感应和 DNA 电荷转移都有模型与实验数据，但缺少统一 leaderboard。更适合设计成“文献证据 + 实验数据 + QM/MM 或 open-system simulation + 机制判断”的 workflow benchmark。

---

## 17. 推荐下一步重点阅读

| 优先级 | Benchmark | 为什么优先 |
|---|---|---|
| P0 | PDEBench | 最直接体现 ML vs 数值 PDE solver |
| P0 | SciMLBenchmarks.jl | 最贴近科学计算本身，重视 work-precision |
| P0 | WeatherBench 2 | 真实科学领域中 ML vs 物理模型的成熟对比 |
| P0 | FrontierScience / ScholarQABench / LitQA2 | 分别诊断专家级闭卷推理、跨论文综述与带来源检索 |
| P0 | AARRI-Bench | 研究实习生式行为评测，强调研究流程中的判断、协作和纠错 |
| P0 | AstaBench / ResearcherBench / LifeSciBench | 统一 Agent harness、科学证据综合和专家科研判断 |
| P0 | DiscoveryBench / BLADE | 数据驱动发现与分析决策，区别于单纯刷预测分 |
| P0 | ARC-Bench / ResearchClawBench | 多领域端到端研究产物和隐藏证据评测 |
| P0 | AstaBench E2E / DiscoveryWorld | 开放式与模拟式完整发现闭环 |
| P0 | MADE | 最接近 AInstein Track B 的材料候选发现 / oracle search 闭环 |
| P0 | SciCode / PaperBench / NatureBench | 科学代码、论文复现和科学 ML SOTA 三种可执行能力 |
| P1 | SciAgentGym / SciVisAgentBench | 多步科学工具调用与可验证科学可视化产物 |
| P1 | Curie / EXP-Bench | 从实验问题到代码、执行、结论的计算实验闭环 |
| P1 | MLR-Bench / MLRC-Bench | 对照开放 rubric 与客观竞赛指标两种 AI 科研评法 |
| P1 | Open Catalyst Project | ML 加速 DFT 的典型大规模 benchmark |
| P1 | Design-Bench / Sci Modeling Bench | 离线科学设计优化 / inverse design，适合评候选生成和 surrogate 可靠性 |
| P1 | PCQM4Mv2 / QMugs / SPICE / ANI | 量子化学性质、药物样分子和高精度 ML 势函数扩展 |
| P1 | SRBench / SRBench++ | 方程发现和可解释科学规律 benchmark |
| P1 | LLM-SRBench | 面向 LLM 科学方程发现，和科研智能体更相关 |
| P1 | MOOSE-Chem / Matter to Mechanism | 假设与机制生成，观察文本 Idea 评测的边界 |
| P1 | FIRE-Bench | 以 claim precision/recall/F1 评 insight rediscovery |
| P1 | SGI-Bench | 科研四环和多模态能力雷达，不等同于端到端闭环 |
| P2 | Matbench | 材料性质预测标准 benchmark |
| P2 | MD17 / rMD17 / MD22 | ML 势函数与量子化学/分子动力学对比 |
| P2 | PDBbind / CASF / enzyme kinetics proxy | 量子生物相关 proxy；更适合机制/workflow 评测而非统一刷榜 |
| P2 | CFDBench | CFD surrogate 评测，可作为 PDEBench 补充 |
