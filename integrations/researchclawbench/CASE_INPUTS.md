# ResearchClawBench 十个 case 的完整输入（2026-06-21 测评用）

> 配套 `EVAL_2026-06-21.md`（测评结果）。本文只记录**喂给 agent 的完整输入**,供复核/复现。
>
> **RCB 给 agent 的输入 = 一个研究工作区**,包含三部分:
> 1. **任务说明**（`task_info.json` 的 `task` 字段,经 `instructions_tmpl.py` 包成 `INSTRUCTIONS.md`:全自主、产出 `report/report.md`）;
> 2. **数据**（`data/`,只读）——下面逐文件列出 RCB 提供的官方描述与实际文件大小;
> 3. **参考文献**（`related_work/`,只读 PDF）——只给数量与体积(内容不在此展开)。
>
> ⚠️ **数据文件异常**已就地标注(空文件 / 4KB 占位索引等)——其中几处直接影响了得分,见各 case 注。

---

## 0. RCB 通用输入指令（`INSTRUCTIONS.md` 模板,所有 agent 共用)

每个 case 真正喂给 agent 的 `INSTRUCTIONS.md`,是 RCB 用 `evaluation/instructions_tmpl.py` 的下述模板,
填入三个占位符生成的:

- `{task_desc}` ← 该 case 的**任务全文**（即下文各 case 的「任务（全文)」段）;
- `{data_text}` ← 该 case 的**数据文件清单**（即各 case 「数据 `data/`」表,格式化成 `- **名字** [type] (\`路径\`): 描述`）;
- `{workspace}` ← 该次运行的**绝对工作区路径**。

模板本体（逐字,**所有领域完全相同**,这就是 RCB 自身的统一指令)：

````markdown
## Role

You are an autonomous scientific research agent. Your mission is to independently complete a research task from start to finish:

1. **Read & Understand** — Study the related work and data to build domain context.
2. **Think & Design** — Formulate your research idea, hypothesis, and analysis plan.
3. **Code & Execute** — Implement the analysis, generate figures, and iterate until results are solid.
4. **Analyze & Report** — Interpret the results and produce a publication-quality research report.

---

## Research Task

### Task Description
{task_desc}

### Available Data Files
{data_text}

---

## Execution Protocol

**There is no human on the other end.** No one will answer questions, grant permissions, or provide clarification. You are fully on your own. If you encounter difficulties, confusion, or unexpected errors — do not ask for help, do not pause, and do not interrupt the task. Make your best judgment and keep going.

Your primary goal is to complete the research task and produce a high-quality `report/report.md`. Your implicit secondary goal is equally important: **ensure the session is never accidentally terminated before the task is done.**

If you are operating as a ReAct-style agent (Reasoning + Acting), note that a response containing only text with no tool call will be interpreted as task completion. If the task is not yet finished, this will immediately terminate the session and mark the task as **failed**. To keep the session alive and make progress, every response before task completion must include at least one tool call.

### Strictly Forbidden
- Outputting only a research plan or summary without calling any tool
- Asking questions, requesting clarification, or seeking confirmation
- Text-only reasoning responses that contain no tool call (causes accidental termination)
- Declaring the task complete before `report/report.md` is written
- Stopping or giving up due to errors, missing data, or uncertainty

### Rules
1. **Always act**: Unless the final report is fully written and all deliverables are complete, every response must include at least one tool call. Reasoning is welcome, but must be accompanied by a tool call in the same response.
2. **Never ask**: Do not pose questions, request clarification, or ask for permission. If something is ambiguous, make a reasonable assumption and proceed.
3. **Push through difficulties**: If a script fails, debug it. If data is unclear, make reasonable assumptions. If a package is missing, install it. Never stop because something is hard.
4. **Never finish early**: The task is only complete when `report/report.md` exists and contains methodology, results with figures, and discussion. Do not stop before then.

---

## Workspace

Your workspace is: `{workspace}`

- All file reads and writes must stay inside this directory.
- `data/` and `related_work/` are read-only — do not modify them.

### Layout
- `data/` — Input datasets (read-only)
- `related_work/` — Reference papers (read-only)
- `code/` — Write your analysis code here
- `outputs/` — Save intermediate results
- `report/` — Write your final report here
- `report/images/` — Save all figures here as **PNG files** (`.png` only)

### Deliverables
1. Analysis code in `code/`
2. Intermediate results in `outputs/`
3. A comprehensive research report as `report/report.md`:
   - Methodology, results, and discussion
   - Academic writing style
   - **Figures are mandatory** — generate plots and save to `report/images/`, reference them with relative paths: `images/figure_name.png`
   - Include at minimum: data overview, main results, and validation/comparison plots

### Technical Notes
- Install Python packages as needed before using them.
- Use matplotlib, seaborn, or any suitable visualization library. Save all figures as **PNG files** (`.png`). Do not use uncommon formats such as PPM, BMP, TIFF, or EPS — these cannot be rendered in the report viewer.
- Ensure code is reproducible.

---

Now proceed step by step with actions (tool calls) until `report/report.md` is complete.
````

> **中文对照译文（仅供阅读,非实际下发）**——RCB 实际喂给 agent 的是上面的英文原版;下面这份逐节对应的中译仅为方便理解,占位符 `{task_desc}`/`{data_text}`/`{workspace}` 保持原样不译。

````markdown
## 角色

你是一个**自主科研 agent**。你的使命是从头到尾独立完成一项研究任务:

1. **阅读与理解** —— 研读相关文献与数据,建立领域背景认知。
2. **思考与设计** —— 形成你的研究思路、假设与分析方案。
3. **编码与执行** —— 实现分析、生成图表,反复迭代直到结果可靠。
4. **分析与撰写** —— 解读结果,产出一份达到可发表水平的研究报告。

---

## 研究任务

### 任务描述
{task_desc}

### 可用数据文件
{data_text}

---

## 执行协议

**对面没有任何人。** 没有人会回答你的问题、授予权限或提供澄清。你完全靠自己。如果遇到困难、困惑或意外报错——不要求助、不要暂停、不要中断任务。自行做出最佳判断,继续推进。

你的首要目标是完成研究任务并产出一份高质量的 `report/report.md`。你的隐性次要目标同样重要:**确保会话在任务完成前绝不被意外终止。**

如果你以 ReAct 式(推理 + 行动)的 agent 模式运行,请注意:**一条只有文本、不含任何工具调用的回复,会被判定为任务完成**。若任务尚未结束,这将立即终止会话并把任务标记为**失败**。为了让会话存活并持续推进,任务完成之前的每一条回复都必须至少包含一次工具调用。

### 严格禁止
- 只输出研究计划或总结,却不调用任何工具
- 提问、请求澄清或寻求确认
- 不含任何工具调用的纯文本推理回复(会导致意外终止)
- 在 `report/report.md` 写好之前就宣布任务完成
- 因报错、缺数据或不确定而停下或放弃

### 规则
1. **始终行动**:除非最终报告已完整写好、所有交付物均已完成,否则每条回复都必须至少包含一次工具调用。欢迎推理,但必须与工具调用同处一条回复中。
2. **绝不提问**:不要提出问题、请求澄清或索要许可。若有歧义,做出合理假设并继续。
3. **顶住困难**:脚本失败就调试它;数据不清就做合理假设;缺包就装上。绝不因为事情难做就停下。
4. **绝不提前收工**:只有当 `report/report.md` 存在、且包含方法、带图的结果与讨论时,任务才算完成。在此之前不得停止。

---

## 工作区

你的工作区是:`{workspace}`

- 所有文件读写都必须限定在该目录内。
- `data/` 与 `related_work/` 为只读 —— 不得修改。

### 目录结构
- `data/` —— 输入数据集(只读)
- `related_work/` —— 参考论文(只读)
- `code/` —— 在此编写你的分析代码
- `outputs/` —— 保存中间结果
- `report/` —— 在此撰写你的最终报告
- `report/images/` —— 所有图表都以 **PNG 文件**(仅 `.png`)保存于此

### 交付物
1. `code/` 中的分析代码
2. `outputs/` 中的中间结果
3. 一份完整的研究报告 `report/report.md`:
   - 含方法、结果与讨论
   - 学术写作风格
   - **图表为强制项** —— 生成图并保存到 `report/images/`,用相对路径引用:`images/figure_name.png`
   - 至少包含:数据概览、主要结果、以及验证/对比图

### 技术说明
- 用到的 Python 包请先安装再使用。
- 使用 matplotlib、seaborn 或任何合适的可视化库。所有图表都保存为 **PNG 文件**(`.png`)。不要使用 PPM、BMP、TIFF、EPS 等不常见格式——这些无法在报告查看器中渲染。
- 确保代码可复现。

---

现在,一步一步地以行动(工具调用)推进,直到 `report/report.md` 完成。
````

**这层统一指令的几个硬性约束（直接决定 agent 行为)**：
1. **全自主、无人可问**:遇到困难/歧义/报错都不许停、不许问,自行假设继续;
2. **每个回合必须带至少一个工具调用**:纯文本无工具调用 = 被判任务完成 → 提前终止判失败;
3. **唯一硬交付 = `report/report.md`**(含方法/结果/图/讨论),**图是强制项**,存 `report/images/*.png`;
4. **沙箱边界**:只在工作区内读写,`data/`、`related_work/` 只读;`code/`、`outputs/`、`report/` 可写。

> 这正是 §EVAL 里「famou 被带成通用自主 agent、没走自己 23 阶段流程」的根因——**这份强自包含指令盖过了 famou 的 AGENTS.md 编排**:
> 它把"全自主写出 report/report.md"设为唯一目标,且明令 never ask,于是 famou 直接照此执行,没有触发 peer-review 子 agent / quality-gate。

---

## Astronomy_000 — 超轻玻色子约束（黑洞超辐射 + 贝叶斯）

**任务（全文)**：
> To constrain the properties of ultralight bosons (ULBs) by developing and applying a novel Bayesian statistical framework. This framework translates the physics of black hole superradiance into a probabilistic model that ingests the full posterior distributions (not just point estimates) of black hole mass and spin measurements. The goal is to derive statistically rigorous upper limits on ULB masses and self-interaction coupling strengths, thereby using astrophysical data to probe fundamental particle physics.

**任务（中文译文）**：
> 通过开发并应用一套全新的贝叶斯统计框架来约束超轻玻色子(ULB)的性质。该框架把黑洞超辐射的物理机制转化为一个概率模型,该模型摄入黑洞质量与自旋测量的**完整后验分布**(而非仅点估计)。目标是导出对 ULB 质量与自相互作用耦合强度在统计意义上严格的上限,从而用天体物理数据探测基础粒子物理。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `IRAS_09149-6206_samples.dat` | feature_data | 312 KB | 超大质量黑洞 IRAS 09149-6206 的质量与无量纲自旋后验分布样本（超大质量黑洞区段的约束输入）。 |
| `M33_X-7_samples.dat` | feature_data | 57 KB | X 射线双星 M33 X-7 中恒星级黑洞的质量与自旋后验样本（演示/应用贝叶斯框架的主数据集）。 |

**参考文献 `related_work/`**：4 篇 PDF（paper_000–003）。

---

## Chemistry_000 — KA-GNN 分子性质预测

**任务（全文)**：
> The task of this study is to design and evaluate a novel graph neural network architecture, termed Kolmogorov–Arnold Graph Neural Networks (KA-GNNs), for molecular property prediction by representing molecules as graphs with atom-level and bond-level features (including both covalent and non-covalent interactions) as input, and producing predictions of molecular properties such as toxicity, bioactivity, and physiological effects as output; the overarching scientific objective is to enhance predictive accuracy, computational efficiency, and interpretability by replacing conventional MLP-based transformations in graph neural networks with Fourier-based Kolmogorov–Arnold network modules that provide stronger expressive power and theoretical approximation guarantees.

**任务（中文译文）**：
> 本研究的任务是设计并评估一种全新的图神经网络架构——Kolmogorov–Arnold 图神经网络(KA-GNN),用于分子性质预测:以图的形式表示分子(节点为原子级、边为键级特征,涵盖共价与非共价相互作用)作为输入,输出毒性、生物活性、生理效应等分子性质的预测;总体科学目标是用基于傅里叶的 Kolmogorov–Arnold 网络模块替代图神经网络中传统的 MLP 变换——后者具有更强的表达能力与理论逼近保证——从而提升预测精度、计算效率与可解释性。

**数据 `data/`**（MoleculeNet 五个数据集,SMILES + 二分类标签）：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `bace.csv` | structure_data | 114 KB | BACE:小分子 SMILES + 是否抑制人 β-分泌酶 1 (BACE-1) 的二分类标签。 |
| `bbbp.csv` | structure_data | 142 KB | BBBP:化合物能否穿透血脑屏障的二分类。 |
| `clintox.csv` | structure_data | 101 KB | ClinTox:临床试验毒性结局 + FDA 批准状态,多任务二分类。 |
| `hiv.csv` | structure_data | 2.3 MB | HIV:能否抑制 HIV 复制的二分类。 |
| `muv.csv` | structure_data | 6.6 MB | MUV:大规模、高度类不平衡的多任务虚拟筛选基准。 |

**参考文献**：4 篇 PDF。

---

## Earth_000 — 全球冰川质量变化重建（GlaMBIE）

**任务（全文)**：
> Input: 233 sets of mass change estimates for 19 global glacial regions, derived from four observational methods (glaciological measurements, DEM differencing, altimetry, gravimetry) and hybrid methods.
> Output: 2000–2023 regional and global glacial mass change time series (annual resolution), including uncertainties, expressed as specific mass change (m w.e.) and total mass change (Gt).
> Scientific Objective: Reconcile diverse observational methods to deliver a consistent and high-confidence assessment of global glacial mass change, and establish an observational benchmark for IPCC reports and climate model calibration.

**任务（中文译文）**：
> 输入:全球 19 个冰川区域的 233 组质量变化估计,来自四种观测方法(冰川学实测、DEM 差分、测高、重力测量)及混合方法。
> 输出:2000–2023 年区域级与全球级冰川质量变化时间序列(年分辨率),含不确定度,以比质量变化(m w.e.)与总质量变化(Gt)表示。
> 科学目标:调和不同观测方法,给出对全球冰川质量变化一致且高置信度的评估,并为 IPCC 报告与气候模型校准建立观测基准。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `glambie` | sequence_data | **4 KB** ⚠️ | 汇集 4 类观测 + 综合方法的区域估计,称含 35 个团队、约 450 位贡献者的 **233 组**冰川质量变化估计。 |

> ⚠️ **数据注**:`glambie` 实际只有 4 KB——是索引/清单而非 233 组完整数据本身。agent 拿到的实物远小于任务描述暗示的规模。

**参考文献**：5 篇 PDF。

---

## Energy_000 — 锂电池参数辨识（MMGA）

**任务（全文)**：
> Input: Experimental macroscopic data (voltage, temperature, and capacity curves under discharge conditions) and a multi-parameter search space defined by Latin Hypercube Sampling (LHS).
> Output: A set of identified high-fidelity internal parameters (such as particle radius, reaction rates, and thermal coefficients) for the electrochemical-aging-thermal (ECAT) coupled model.
> Scientific Goal: To develop a rapid and accurate parameter identification framework (MMGA) that uses an Artificial Neural Network (ANN) meta-model to replace computationally expensive physical simulations, thereby solving the trade-off between model complexity and calculation efficiency for Lithium-ion battery digital twins.

**任务（中文译文）**：
> 输入:实验宏观数据(放电工况下的电压、温度、容量曲线),以及由拉丁超立方采样(LHS)定义的多参数搜索空间。
> 输出:为电化学-老化-热(ECAT)耦合模型辨识出的一组高保真内部参数(如颗粒半径、反应速率、热系数)。
> 科学目标:开发一套快速且准确的参数辨识框架(MMGA),用人工神经网络(ANN)代理模型替代计算昂贵的物理仿真,从而解决锂离子电池数字孪生在模型复杂度与计算效率之间的权衡难题。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `NASA PCoE Dataset Repository` | structure_data | **4 KB** ⚠️ | NASA PCoE 18650 电池老化数据（CC 放电的电压/电流/温度）。 |
| `CS2_36` | sequence_data | **4 KB** ⚠️ | 马里兰 CALCE 商用 NCM 18650 循环寿命数据（1C CC 放电,参数辨识主参考）。 |
| `Oxford Battery Degradation Dataset` | feature_data | **4 KB** ⚠️ | 牛津 740mAh 软包电池动态城市工况退化数据（验证泛化）。 |

> ⚠️ **数据注**:三份均为 4 KB——是数据集**指针/说明占位**,并非实测电池曲线本身。要真做需按指针去下载对应公开数据集。

**参考文献**：4 篇 PDF。

---

## Information_000 — 统一多模态自回归框架（解耦视觉编码）

**任务（全文)**：
> Build a unified autoregressive framework that decouples visual encoding to perform both multimodal understanding (e.g., visual question answering) and visual generation (e.g., text-to-image generation) within a single Transformer architecture.

**任务（中文译文）**：
> 构建一个统一的自回归框架,通过**解耦视觉编码**,在单一 Transformer 架构内同时完成多模态理解(如视觉问答)与视觉生成(如文生图)。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `equation.png` | sequence_data | 30 KB | 含数学公式的图,测 OCR + 公式转 LaTeX 能力。 |
| `doge.png` | sequence_data | 268 KB | "Swole Doge vs. Cheems" 梗图（嵌入文字 "Decoupling Visual Encoding" vs "Single Visual Encoder"）,测高层语义/幽默理解。 |

> 注:`task_info.json` 里 name 写作 `doge.jpg`,实际文件为 `doge.png`（path 也是 .png）。

**参考文献**：4 篇 PDF。
> 注:本任务**没有训练数据**——只给两张测试图,等于要 agent「实现/演示一个 Janus 式统一模型」并在这两张图上展示理解+生成。这是个偏「实现+演示」的开放题。

---

## Life_000 — 超强水下粘合水凝胶从头设计

**任务（全文)**：
> Input is protein sequence features converted to monomer compositions; Output is hydrogel adhesive strength. To de novo design synthetic hydrogels that achieve robust underwater adhesion (>1 MPa) by statistically replicating the sequence features of natural adhesive proteins.

**任务（中文译文）**：
> 输入是转化为单体配比的蛋白质序列特征;输出是水凝胶的粘接强度。目标是通过统计性地复刻天然粘附蛋白的序列特征,从头设计出能实现稳健水下粘接(>1 MPa)的合成水凝胶。

**数据 `data/`**（多批实验数据 xlsx + 一份 README）：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `Original Data_ML_20220829.xlsx` | feature_data | 29 KB | Batch 1:180 个仿生水凝胶的单体配比 + 粘接强度（训练基模型）。 |
| `Original Data_ML_20221031.xlsx` | feature_data | 40 KB | Batch 2:同上。 |
| `Original Data_ML_20221129.xlsx` | feature_data | 52 KB | Batch 3:同上。 |
| `184_verified_Original Data_ML_20230926.xlsx` | feature_data | 47 KB | 清洗校验后的 184 个配方,是 `rfr_gp.py` 训练初始 ML 模型的主输入。 |
| `ML_ei&pred (1&2&3rounds)_20240408.xlsx` | feature_data | 32 KB | 汇总 1/2/3 轮优化结果,用于分析优化轨迹/验证性能。 |
| `ML_ei&pred_20240213.xlsx` | feature_data | 23 KB | 另一批最终优化数据汇总。 |
| `README.md` | — | 6 KB | 数据/脚本说明（随数据提供）。 |

**参考文献**：3 篇 PDF。

---

## Material_000 — AI 发现交替磁体（altermagnet）

**任务（全文)**：
> The scientific objective of this work is to develop an AI-powered search engine that accelerates the discovery of new altermagnetic materials with targeted physical properties. The input consists of crystal structure data (represented as graphs) from databases such as the Materials Project, including a large unlabeled set for pre-training and a small labeled set of known altermagnets (148 positive samples) for fine-tuning. The output is a list of candidate materials predicted to be altermagnets with high probability, along with their electronic structure properties confirmed by first-principles calculations (e.g., 50 newly discovered altermagnets with classifications such as metal/insulator and d/g/i-wave anisotropy).

**任务（中文译文）**：
> 本工作的科学目标是开发一个 AI 驱动的搜索引擎,加速发现具有目标物理性质的新型交替磁体材料。输入为来自 Materials Project 等数据库的晶体结构数据(以图表示),包括一个用于预训练的大规模无标注集合,以及一个用于微调的小规模已知交替磁体标注集(148 个正样本)。输出为一份被高概率预测为交替磁体的候选材料清单,并附第一性原理计算确认的电子结构性质(例如 50 个新发现的交替磁体,带金属/绝缘体、d/g/i 波各向异性等分类)。

**数据 `data/`**（PyTorch `.pt` 晶体图数据集）：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `pretrain_data.pt` | structure_data | 12 MB | 5,000 个无标注晶体结构图,用于自监督预训练。 |
| `finetune_data.pt` | structure_data | 4.8 MB | 2,000 个带二分类标签的晶体图（仅 5% 正样本:100 正/1900 负,模拟已知交替磁体稀缺）。 |
| `candidate_data.pt` | structure_data | 2.4 MB | 1,000 个未知候选材料;内部藏约 50 个真阳性用于评测发现准确率。 |

**参考文献**：4 篇 PDF。

---

## Math_000 — 拥挤场景多目标跟踪（SparseTrack）

**任务（全文)**：
> input: Consecutive image frames and object detections per frame (including bounding box coordinates and confidence scores).
> output: Complete trajectories for each target, i.e., identity labels (IDs) and corresponding bounding box sequences across video frames.
> scientific targets: To effectively handle occlusions and improve multi-object tracking performance in crowded scenes by decomposing dense target sets into sparse subsets via pseudo-depth estimation and performing hierarchical association.

**任务（中文译文）**：
> 输入:连续图像帧,以及每帧的目标检测结果(含边界框坐标与置信度分数)。
> 输出:每个目标的完整轨迹,即跨视频帧的身份标签(ID)及对应的边界框序列。
> 科学目标:通过伪深度估计把密集目标集分解为稀疏子集,并进行层级关联,从而有效处理遮挡、提升拥挤场景下的多目标跟踪性能。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `simulated_sequence.json` | structured_data | 6.4 MB | 受控模拟视频序列（40 帧、20 目标、85% 检出率、20% 遮挡重叠阈值）:含真值轨迹 + 带置信度与遮挡标记的检测框,用于可复现地比较 SparseTrack 与 ByteTrack。 |

**参考文献**：4 篇 PDF。

---

## Neuroscience_000 — SimBA 式行为分类复现

**任务（全文)**：
> Input: pose-derived frame-level feature tables and aligned behavior labels (Attack, Sniffing) from the official SimBA sample project. Output: trained supervised classifiers, quantitative evaluation reports, precision-recall diagnostics, confusion matrices, and feature-importance tables. Scientific objective: verify, on open data and executable code, whether the SimBA-style workflow can reproducibly transform tracked behavior features into transparent and auditable behavior classification evidence.

**任务（中文译文）**：
> 输入:来自 SimBA 官方样例工程的、由姿态衍生的帧级特征表,以及对齐的行为标签(Attack 攻击、Sniffing 嗅探)。输出:训练好的监督分类器、定量评估报告、精确率-召回率诊断、混淆矩阵与特征重要性表。科学目标:在开放数据与可执行代码上,验证 SimBA 式工作流能否可复现地把跟踪到的行为特征转化为透明、可审计的行为分类证据。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `Together_1_features_extracted.csv` | feature_data | 889 KB | SimBA 官方样例工程里由姿态信号衍生的帧级特征,作为两个行为标签的输入矩阵 X。 |
| `Together_1_targets_inserted.csv` | sequence_data | 747 KB | 与帧对齐的 Attack/Sniffing 标注,作为监督目标 y。 |
| `Together_1_machine_results_reference.csv` | feature_data | 1.7 MB | 样例工程自带的参考输出表,作为对照辅料。 |

**参考文献**：5 篇 PDF。

> 注:得分最低（1.0)。rubric 要的是**六种条件下的 PR 曲线 + Lab1/Lab2、雌雄、RI/CSDS 的 SHAP 对比**等论文里非常具体的诊断图;但**输入只给了 SimBA 样例的单一工程数据**(`Together_1`),并不含那些跨条件/跨实验室的数据——输入与 rubric 之间存在客观落差。

---

## Physics_003 — 石墨烯 Floquet-Bloch 态（tr-ARPES）

**任务（全文)**：
> Input: Monolayer epitaxial graphene samples and mid-infrared pump excitation parameters (wavelength: 5 μm, intensity, polarization angle). Output: Direct, energy- and momentum-resolved observation of Floquet-Bloch states (replica bands of the Dirac cone) via time-resolved and angle-resolved photoemission spectroscopy (tr-ARPES). Scientific Goal: To experimentally confirm the existence of Floquet-Bloch states in a paradigmatic 2D material and elucidate the underlying scattering mechanism involving photon-dressed Volkov final states.

**任务（中文译文）**：
> 输入:单层外延石墨烯样品,以及中红外泵浦激发参数(波长 5 μm、强度、偏振角)。输出:通过时间分辨与角分辨光电子能谱(tr-ARPES),对 Floquet-Bloch 态(Dirac 锥的复制带)进行直接的、能量与动量分辨的观测。科学目标:在一种典型二维材料中实验确认 Floquet-Bloch 态的存在,并阐明其背后涉及光子缀饰 Volkov 末态的散射机制。

**数据 `data/`**：
| 文件 | type | 大小 | 官方描述 |
|---|---|---|---|
| `raw_trARPES_data.h5` | structure_data | 1.9 MB | 原始未处理 4D 数据（energy, kx/ky, time delay）。 |
| `processed_band_data.json` | feature_data | 34 KB | 已处理:主 Dirac 锥与复制带的位置与强度。 |
| `polarization_dependence_data.csv` | sequence_data | **0 KB** ⚠️ | 各泵浦偏振角 θp 下复制带强度的表格数据。 |

> ⚠️ **数据注**:`polarization_dependence_data.csv` 实际为**空文件(0 KB)**(同目录另有 `polarization_dependence.png` 206 KB)。这解释了为何 famou 的偏振依赖分析(criterion 1)拟合几乎是平的——**它本就没拿到真正的偏振数值数据**。尽管如此 Physics 仍是 10 个里最高分(47.6),因为另两条 rubric(画出 Dirac 锥+复制带、点明 Volkov 机制)定性、且被覆盖。

**参考文献**：4 篇 PDF。

---

## 附:数据完整性小结（影响测评解读）

| case | 数据状态 | 对得分的影响 |
|---|---|---|
| Physics_003 | 偏振 CSV **0 KB 空文件** | 偏振分析(criterion 1)无真值可用,拟合偏平 |
| Earth_000 | `glambie` 仅 **4 KB**(索引非全量) | 难以复现 233 组级别的全量重建 |
| Energy_000 | 三个数据集均 **4 KB**(指针/说明占位) | 无实测电池曲线,需按指针自行下载 |
| Neuroscience_000 | 仅 SimBA 单工程样例,**无跨条件数据** | rubric 要的跨 Lab/性别/环境 SHAP 对比缺输入支撑 |
| 其余 6 个 | 数据实体齐全 | 输入完整 |

> 这些数据缺口是**理解低分的重要前提**:部分领域的低分不全是 agent 能力问题,也有「输入实体 < rubric 要求」的客观成分。正式刷榜前应先核对各任务 `data/` 是否需要按指针补全数据。

---

## 附:方法学分布与 benchmark 选择偏置

> 这 10 个 case **不是清一色的 ML/DL**,而是「**能在沙箱里用 `data/`+`code/` 复现、且可对隐藏论文打分**」的**计算型科研**。
> 按方法本质归类如下(便于理解 RCB 到底在测什么能力)。

| case | 方法本质 | 是否 ML/DL |
|---|---|---|
| **Chemistry** KA-GNN | 设计新 GNN 架构(Fourier-KAN 替代 MLP) | ✅ 纯 DL,设计算法 |
| **Information** 统一多模态 | 设计 Transformer 架构(解耦视觉编码) | ✅ 纯 DL,设计算法 |
| **Material** 交替磁体发现 | GNN 预训练 + 微调筛材料 | ✅ 纯 DL,设计算法 |
| **Energy** MMGA 锂电池 | ANN 代理模型 + 遗传算法,辨识**电化学物理模型**参数 | 🟡 ML+优化(内核是物理模型) |
| **Life** 水凝胶设计 | ML 回归 + 贝叶斯优化配方 | 🟡 ML 辅助的实验设计 |
| **Neuroscience** SimBA | 随机森林等**监督分类** | 🟡 经典 ML(非深度) |
| **Math** SparseTrack | 伪深度分解 + 层级关联**跟踪算法**(检测已给) | 🟡 CV 算法 |
| **Astronomy** ULB 约束 | **贝叶斯统计框架**(后验摄入超辐射物理) | ❌ 统计推断,非 ML |
| **Earth** GlaMBIE | 多源观测**调和/数据同化** | ❌ 统计集成,非 ML |
| **Physics** Floquet-Bloch | tr-ARPES **实验数据分析**(拟合能带/偏振依赖) | ❌ 物理数据分析,无 ML |

**归并后**:
- **3 个**「设计深度学习算法」(Chemistry / Information / Material);
- **4 个**「ML/算法**辅助**领域问题」(Energy / Life / Neuroscience / Math)——算法是手段,内核是领域物理/化学/生物;
- **3 个**根本不是 ML(Astronomy 贝叶斯、Earth 数据同化、Physics 实验数据分析)。

### 真正的共性 = benchmark selection bias

10 个任务的共性**不是 ML/DL,而是 in-silico、可复现、可对隐藏论文逐条打分**。这天然筛掉了三类研究:

1. **需要真做实验**的湿实验/材料合成 —— 只能给已有数据让 agent 分析(Physics 的偏振 CSV 甚至是空的);
2. **纯理论/数学证明**型研究 —— 没有可量化 rubric;
3. **需要自主提出全新研究方向**的开放发现 —— RCB 把**课题与数据都给定**了(对应「自主度光谱」里②被 given 的那一档,见 `docs/benchmarks/BENCHMARKS_AI4S.md §0`)。

换言之,RCB 测的是**「给定课题 + 给定数据,自主完成一篇计算型论文」**的能力,偏向数据驱动 / 算法 / 计算建模型科研——这与它「藏真实论文当金标 + 沙箱可复现 + live leaderboard」的设计目标一致(必须可复现、可打分才能上榜)。解读 famou 得分时应记得:**这只覆盖了科研的一个切片,不等于「完全自主科学发现」**。
