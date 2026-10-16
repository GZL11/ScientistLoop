# 端到端科研智能体与评测基准调研（2026-07）

> 调研时间：2026-07-28  
> 范围：端到端科研 Agent、垂直领域科研 Agent、自动科研/论文复现/实验闭环 benchmark。  
> 说明：本领域更新很快，部分系统只有预印本、官网、代码或第三方索引。本文把“已核验公开论文/代码/官网”和“待进一步核验”的条目标出，避免把宣传口径和可复现实证混在一起。

---

## 0. 如何定义“端到端科研智能体”

本文把科研 Agent 的端到端程度分成 5 档：

| 档位 | 定义 | 典型能力 |
|---|---|---|
| L0 | 科学问答 / 单点工具 | 文献问答、公式解释、数据库查询 |
| L1 | 多步工具型 Agent | 搜文献、调用工具、执行代码，但不形成完整研究闭环 |
| L2 | 研究工作流 Agent | 文献 → 假设 / 方案 → 分析 / 报告，有部分自动执行 |
| L3 | 可执行科研 Agent | 能写代码、跑实验、产出结果、写报告/论文，含自检/修复 |
| L4 | 实验闭环 / 真实发现 Agent | 连接真实实验、机器人、仪器或真实材料/生物验证，能迭代发现 |

调研重点是 **L2-L4**。

---

## 1. 总体格局

当前市面和论文圈的端到端科研 Agent 大致分为六类：

1. **通用 deep research / co-scientist**：偏文献综合、假设生成、研究计划与科学推理。
2. **ML 自动科研 / 自动论文生成**：idea → code → experiment → figure → paper → review。
3. **论文复现 / paper-to-code**：给论文，自动还原代码、实验、结果。
4. **生命科学 / 生物医学 Agent**：组学、药研、罕见病、单细胞、多模态生物医学。
5. **化学 / 材料 / 实验室自动化 Agent**：合成规划、机器人实验、材料筛选、仪器控制。
6. **脑科学 / 神经影像 / BCI Agent**：脑信号分析、fMRI/神经影像 workflow、脑科学任务 benchmark。

---

## 2. 通用 / 准通用端到端科研 Agent

| 系统 | 提出时间 | 机构/来源 | 领域 | 范式 / 类型 | 端到端程度 | 典型能力 | Benchmark / 评测 | 公开状态 |
|---|---:|---|---|---|---:|---|---|---|
| Google **AI co-scientist** | 2025 | Google / Nature | 生物医学为主，可泛化 | 假设生成 / 研究协作 Agent | L2-L3 | 文献 grounding、假设生成、反思、排名、实验建议 | 203 个研究目标 Elo 排序；专家目标；盲评开放问题；药物重定位、靶点发现、抗菌机制案例 | 已有 Nature 论文与 Google 介绍 |
| FutureHouse **Robin** | 2025 | FutureHouse / Nature | 生物医学 | 实验反馈闭环 / 多 Agent | L3-L4 | 搜文献、生成假设、建议实验、分析结果、迭代新假设 | 干性 AMD 药物重定位案例；实验验证；多 Agent 系统 | 已有 Nature 论文 / 官方材料 |
| OpenAI **Deep Research** | 2025 | OpenAI | 通用研究报告 | deep research / 报告型 Agent | L2 | 多源检索、计划、引用报告 | 官方产品能力展示；未见公开绑定学术科研 benchmark | 官方产品文档 |
| **The AI Scientist** | 2024 | Sakana AI 等 | ML 自动科研 | 端到端自动论文 / ML 科研 | L3 | idea → code → experiment → figure → paper → review | 3 个 ML 子领域；自动 reviewer；成本/产出评估 | arXiv / 代码 |
| **The AI Scientist v2** | 2025 | Sakana AI 等 | ML 自动科研 | 端到端自动论文 / workshop submission | L3 | 更完整论文生成与 workshop submission | 自动生成 workshop 级论文案例 | arXiv / blog |
| **CycleResearcher** | 2024/2025 | 学术预印本 | ML / 自动论文 | review-loop 自动科研 | L3 | 自动研究、自动 review、基于 review 的循环优化 | Research-14k / Review-5k；模拟 peer-review 评分 | Paper: https://arxiv.org/abs/2411.00816；Code: https://github.com/zhu-minjun/Researcher |
| **Agent Laboratory** | 2025 | 学术预印本 | ML 研究助手 | 多角色科研工作流 | L3 | 文献综述、实验、报告写作 | 人类评估；MLReplicate 中被评 | Project: https://agentlaboratory.github.io/；Paper: https://arxiv.org/abs/2501.04227；Code: https://github.com/SamuelSchmidgall/AgentLaboratory |
| **AI-Researcher** | 2025 | 学术预印本 | ML 自动科研 | 自动科研 / 论文生成 | L3 | 研究任务自动探索与论文生成 | Scientist-Bench / MLReplicate | Project: https://autoresearcher.github.io/；Paper: https://arxiv.org/abs/2505.18705；Code/bench: https://github.com/HKUDS/AI-Researcher |
| **R&D-Agent** | 2025 | Microsoft | ML / 数据科学 R&D | ML 工程 / Kaggle 式寻优 | L3 | 数据、模型、特征、实验自动迭代 | MLE-bench / Kaggle 式任务 | GitHub 开源 |
| **PaperCoder / Paper2Code** | 2025 | 学术项目 | paper-to-code | 论文复现 / repo-level coding | L3 | 论文到 repo-level 实现 | Paper2CodeBench / PaperBench Code-Dev | Paper: https://arxiv.org/abs/2504.17192；Code/Data: https://github.com/going-doer/Paper2Code |
| **AlphaEvolve / OpenEvolve 类** | 2025 | DeepMind / 开源复现 | 算法、数学、工程优化 | 进化式程序搜索 / 自动 evaluator | L3-L4 | 程序搜索、算法发现、自动 evaluator、进化式优化 | 50+ 数学/算法问题；矩阵乘法、kernel、调度等自动验证 | 官方 blog / 论文或技术报告 |
| **PiEvo** | 2026 | 预印本 | 原理演化式科学发现 | 原理演化 / uncertainty minimization | L3 | principle evolution + uncertainty minimization | 多个科学发现 benchmark；看 solution quality / convergence | Paper: https://arxiv.org/abs/2602.06448；Code: https://github.com/amair-lab/PiEvo |
| **Hyra / 腾讯混元 Research Agent** | 2026-07 | Tencent Hunyuan | 通用研究 / AI4AI / AI4S | 递归自我改进式研究 Agent | L2-L3？ | 公开口径强调递归自我改进式 research / engineering task optimizer | AI4AI、AI4Science、数学、工程、创意设计等；公开 demo/results repo；详见 [Hyra Benchmark / Result 汇总](./HYRA_BENCHMARKS_CN.md) | Official: https://hy.tencent.com/research/hyra；Results: https://github.com/Tencent-Hunyuan/hyra-results |

---

## 3. 生命科学 / 生物医学 Agent

| 系统 | 提出时间 | 领域 | 范式 / 类型 | 端到端程度 | 核心能力 | Benchmark / 评测 | 备注 |
|---|---:|---|---|---:|---|---|---|
| **Biomni** | 2025 | 通用生物医学 | 工具增强 / biomedical action space | L3 | 统一 biomedical action space；工具/数据库/软件检索；代码执行；协议设计 | Biomni-Eval1：433 instances、10 类任务；LAB-Bench；HLE 生物医学子集；真实 case studies | Stanford SNAP，开源 |
| **STELLA** | 2025 | 生物医学 | self-evolving tool/template Agent | L3 | Manager / Dev / Critic / Tool Creation；自演化模板库和工具库 | HLE Biomedicine、LAB-Bench DBQA/LitQA；Tool Creation Benchmark | Paper: https://arxiv.org/abs/2507.02004；Code: https://github.com/zaixizhang/STELLA；PyPI: https://pypi.org/project/stella-agent/ |
| **Agentomics** | 2026 | 生物医学 ML | ML 自动实验 / leaderboard 型 | L3-L4 | 输入 biomedical dataset，自动做 ML 实验，输出模型、脚本、报告 | 20 个数据集：Protein Engineering、Drug Discovery、Regulatory Genomics；3 replicates × 8h；leaderboard percentile / test metric / success rate | ISMB/Bioinformatics 版本；容器化，强调防 test leakage |
| **BioClaw** | 2025/2026? | 生信工作流 | 生信工具工作流 Agent | L2-L3 | BLAST、FastQC、PDB/PyMOL、PubMed、gel/blot 图像分析等工具协作 | 公开更偏生态/系统展示，硬 benchmark 需补 | 待进一步核验 |
| **SPARK** | 2025/2026 | 病理/肿瘤 | 多 Agent 病理 / 空间组学 | L3 | 多 Agent 病理 / 空间组学分析 | 18 个队列、5400+ 患者；预后/预测与空间生物学任务 | 领域垂直 |
| **TxAgent / TxGemma 相关** | 2024/2025 | 药研 / therapeutics | 药物研发知识 / repurposing Agent | L2-L3 | 药物研发知识、靶点、repurposing、临床/药物任务 | 通常用 drug discovery / therapeutic QA / repurposing benchmark | 需按具体版本核验 |
| **Kosmos / AI biomedical scientist 类** | 2025/2026? | 组学/精准医学 | 文献 + omics hypothesis Agent | L2-L3 | 文献 + omics 数据分析 + hypothesis | 多以 case study、复现发现、专家评审为主 | 名称和实现较分散 |

### 生物医学 Agent 的评测特点

- 不只看 QA accuracy，还会看：
  - 是否能调用真实生物软件 / 数据库；
  - 是否能写并执行分析代码；
  - 是否能避免 test leakage；
  - 产物是否可复现；
  - 输出 hypothesis / protocol 是否可实验验证。

---

## 4. 脑科学 / 神经影像 / BCI Agent

| 系统 | 提出时间 | 领域 | 范式 / 类型 | 端到端程度 | 核心能力 | Benchmark / 评测 | 备注 |
|---|---:|---|---|---:|---|---|---|
| **BrainPilot** | 2026 | 脑科学研究 | 多 Agent 脑科学工作流 | L3 | PI agent 协调专家 agent；知识库；skill library；Graph of Trace；Auditor | Agents’ Last Exam 中 3 个脑科学任务；BrainPilotBench-v0；end-to-end case studies | 公开数据见 BrainPilot-Bench HF |
| **BrainAgent** | 2026 | 脑信号 / BCI | 脑信号分析 pipeline Agent | L3 | 自然语言意图 → 脑信号分析 pipeline；多 Agent 分解和执行 | 系统性脑信号 Agent benchmark；Task Completion Rate 等 | arXiv:2606.25400 |
| **NeuroClaw** | 2026 | 神经影像 | 神经影像可复现工作流 Agent | L3 | 原始 neuroimaging 数据 → BIDS/预处理 → 模型执行 → 可复现产物 | NeuroBench：executability、artifact validity、reproducibility readiness | 开源 / 技术报告 |
| **BrainAgent / NeuroGraphs 类** | 2025/2026? | 脑网络 | connectome / 图分析 Agent | L2-L3 | connectome 分析、图结构描述、检索、反思 | 公开 rs-fMRI 数据集 | 名称易混，需按论文区分 |

### BrainPilotBench-v0 已知任务形态

公开数据集中可见任务包括：

- `neuro-rsc-place-cell`：小鼠 RSC Ca²⁺ imaging + VR belt behavior；
- `tops-fmri`：tonic-pain functional connectivity；
- `bciciv-2a`：BCI Competition IV 2a EEG；
- `sleep-edf`：Sleep-EDF PSG + hypnogram。

这类 benchmark 的关键优点是：**不是纯问答，而是要处理真实数据文件、执行分析、生成可评分产物**。

---

## 5. 化学 / 材料 / 实验室自动化 Agent

| 系统 | 提出时间 | 领域 | 范式 / 类型 | 端到端程度 | 核心能力 | Benchmark / 评测 | 备注 |
|---|---:|---|---|---:|---|---|---|
| **Coscientist** | 2023 | 化学实验 | 机器人实验闭环 Agent | L4 | 搜索、代码、文档、机器人 API、真实实验执行 | 6 类化学任务；合成规划评分；Suzuki/Sonogashira 真实实验；优化任务 | Nature 论文，强端到端代表 |
| **ChemCrow** | 2023 | 化学工具 Agent | 工具增强化学 Agent | L2-L3 | 18 个专家工具；合成、性质、安全、检索 | 化学任务 + 专家评估；执行 4 个合成案例 | 早期代表 |
| **AutoLabs** | 2024/2025 | 自驱化学实验 | 自驱实验 / liquid-handling Agent | L4 | 自然语言 → liquid-handling protocol → 实验 → 自纠错 | 5 个 benchmark experiments；20 个 agent 配置；10 次重复；F1 / nRMSE | 实验闭环 |
| **ORGANA** | 2025/2026 | 机器人化学助手 | embodied lab assistant | L4 | 自然语言到机器人实验规划、执行和报告 | 溶解度、pH、重结晶、电化学等；user study | 强 embodied lab assistant |
| **Robotic AI Chemist / ChemAgents** | 2024/2025 | 化学机器人 | 多 Agent + 机器人平台 | L4 | 多 Agent + 机器人平台；on-demand chemical research | 多个真实化学任务；critic ablation；机器人 API 成功率 | JACS 方向 |
| **CACTUS** | 2024/2025 | cheminformatics | 化学工具 / 分子分析 Agent | L2-L3 | LLM + 化学工具，分子性质/结构分析 | 工具调用任务、分子分析任务 | 偏工具增强 |
| **MOOSE-Chem** | 2025 | 化学假设发现 | 假设发现 / rediscovery benchmark | L2-L3 | background + inspiration corpus → hypothesis ranking | 51 篇 2024 高水平化学论文；看能否 rediscover unseen hypotheses | 假设发现 benchmark 代表 |
| **MOOSE-Chem3** | 2025/2026 | 化学假设排序 | 实验反馈驱动 hypothesis ranking | L2-L3 | simulated experimental feedback 指导 hypothesis ranking | 30 组化学问题、124 个 hypothesis-performance pairs；Spearman rank 等 | 加入“实验反馈” |
| **OSDA Agent** | 2025 | 沸石 / 分子设计 | Actor-Evaluator-Self-reflector 设计 Agent | L3 | Actor-Evaluator-Self-reflector 闭环设计 OSDA | zeolite frameworks；和实验验证 OSDA 一致性 | ICLR 2025 |
| **El Agente Q** | 2025/2026 | 量子化学 | 量子化学 workflow Agent | L3 | 自然语言 → quantum chemistry workflow → DFT/计算化学软件执行 | 大学级 exercises；一级/二级任务成功率；case studies | 强计算实验 |
| **ChatMOF** | 2024/2025 | MOF | MOF 预测/生成与工具调用 | L2-L3 | MOF 预测/生成与工具调用 | MOF 任务评测 | 是否“端到端发现”需看具体任务 |
| **ElementsClaw** | 2026-04 | 超导材料 | LAM + LLM 材料发现 Agent | L3-L4? | LAM + LLM agent 融合；材料候选筛选；实验验证 | SuperCon3D 外 rediscovery、2.4M stable crystals screening、68k high-confidence candidates、4 个新超导体实验验证 | Project: https://elementsclaw.org/；Paper: https://arxiv.org/abs/2604.23758 |

### 化学/材料 Agent 的评测特点

强评测通常看：

- 是否产生真实可执行的合成 / 实验协议；
- 是否能调用机器人 / 仪器 API；
- 是否得到真实产物或物性验证；
- 是否能在失败后自纠错；
- 是否有 ablation：无工具、无 critic、无检索、无实验反馈时性能下降多少。

---

## 6. ML 自动科研 / paper-to-code / 论文复现系统

| 系统 | 提出时间 | 范式 / 类型 | 端到端范围 | Benchmark / 评测 | 评测重点 |
|---|---:|---|---|---|---|
| The AI Scientist / v2 | 2024 / 2025 | ML 自动科研 / 自动论文 | idea → code → experiment → paper → review | 自建 ML 子领域任务、workshop submission、自动 reviewer | 研究新颖性、实验正确性、论文质量、成本 |
| Agent Laboratory | 2024/2025 | 多角色 ML research assistant | 文献 → 实验 → 报告 | MLReplicate / 人类评估 | 是否能完成研究报告与实验 |
| AI-Researcher | 2024/2025 | 自动科研 / 论文生成 | 自动科研 | Scientist-Bench / MLReplicate | 是否能从任务走到可评研究产物 |
| CycleResearcher | 2025/2026 | review-loop 自动科研 | 研究生成 + review 循环 | Research-14k / Review-5k | review 驱动的论文质量提升 |
| R&D-Agent | 2025 | ML R&D / Kaggle 式寻优 | ML R&D 自动化 | MLE-bench | Kaggle competition score / percentile / medal |
| PaperCoder / Paper2Code | 2024/2025 | paper-to-code | paper → code repo | Paper2CodeBench、PaperBench Code-Dev | repo-level implementation fidelity |
| Tiny Scientist | 2025 | 轻量自动科研 baseline | 轻量自动科研 | MLReplicate 中常作 baseline | 端到端弱基线 |

---

## 7. 核心 Benchmark / 评测基准汇总

### 7.0 Benchmark 范式分类

为了避免把“领域”“任务内容”“评测方式”混在一起，这里先把 benchmark 的**范式**统一成下面几类：

| 范式 | 核心问题 | 典型评测 | 例子 |
|---|---|---|---|
| **刷分型 / Leaderboard** | agent 能否在固定数据、固定 metric 上做出更高分 submission | hidden/public test score、percentile、medal、leaderboard rank | MLE-bench、BioML-bench、Matbench、Matbench Discovery |
| **Workflow 型** | agent 能否把多步科研/工程流程完整跑通 | success rate、artifact validity、executability、reproducibility | Biomni-Eval1、BrainPilotBench、NeuroBench、sim-benchmark、OpenFOAM cases |
| **复现型 / Replication** | agent 能否复现论文/方法/结果 | replication score、rubric tree、代码/结果一致性 | PaperBench、Paper2CodeBench、MLReplicate、NatureBench |
| **开放 Rubric 型** | 没有单一标准答案，评最终研究产物质量 | expert/LLM rubric、insight、factuality、novelty、plausibility | ResearcherBench、LifeSciBench、AstaBench E2E、RCB |
| **工具能力型** | agent 能否正确调用工具、写代码、生成可执行 artifact | tool success、unit test、code executability、format validity | SciAgentBench、Qiskit HumanEval、CFDLLMBench |
| **问答 / 检索型** | agent 能否找到事实、论文、答案并可靠引用 | accuracy、IoU、factual faithfulness、grounding | AutoResearchBench、LAB-Bench、HLE |
| **机理 / 方程发现型** | agent/模型能否恢复公式、定律或控制方程 | symbolic exactness、complexity、外推误差、物理一致性 | AI Feynman、SRBench、ERBench、NewtonBench |

一个 benchmark 可以有副属性，比如 “Workflow 型 + Rubric” 或 “刷分型 + ML 代理模型”。表格里的“范式”优先标**主范式**。

### 7.1 论文复现 / paper-to-code

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **PaperBench** | 2025 | **复现型 / Replication** | AI 论文复现 | 20 篇 ICML 2024 Spotlight/Oral；8,316 个子任务；层级 rubric；LLM judge + 人工验证 | https://openai.com/index/paperbench/ |
| **PaperBench Code-Dev** | 2025 | **复现型 / 代码实现** | 论文实现开发 | implementation requirement tree；按节点给 replication score | https://openai.com/index/paperbench/ |
| **Paper2CodeBench** | 2025 | **复现型 / paper-to-code** | ML paper → 完整代码仓库 | 90 篇 ICLR/ICML/NeurIPS 2024；reference-free + reference-based judge + human author study | Paper: https://arxiv.org/abs/2504.17192；Code/Data: https://github.com/going-doer/Paper2Code |
| **MLReplicate** | 2026 | **复现型 / 自主论文复现** | 自主系统复现 ML 论文 | ICML 2025 outstanding papers 改写成任务；自动 review + human expert review | Paper: https://arxiv.org/abs/2605.16616 |
| **NatureBench** | 2026 | **复现型 / SOTA 复现** | Nature-family paper SOTA 复现 | 90 个 Nature-family scientific ML tasks；333 eval instances；web-search-disabled、source-method-hidden；containerized task packages；以 SOTA-normalized improvement / g>0.1 判断是否超越论文 SOTA | Paper: https://arxiv.org/abs/2606.24530；Code: https://github.com/FrontisAI/NatureBench；Dataset: https://huggingface.co/datasets/FrontisAI/NatureBench；Traces: https://huggingface.co/datasets/FrontisAI/NatureBench-traces |

### 7.2 ML research / R&D

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **MLE-bench** | 2024 | **刷分型 / Leaderboard** | ML engineering / Kaggle 任务 | 75 个 Kaggle competitions；submission score、percentile、medal；截至 2026-07-30 有公开 leaderboard，但官方 GitHub 说明暂不接收新 leaderboard submissions | Official: https://openai.com/index/mle-bench/；Leaderboard: https://www.mlebench.com/；Code: https://github.com/openai/mle-bench |
| **RE-Bench** | 2024 | **开放 Rubric 型 / 人类对比** | Frontier AI R&D capability | 7 个 ML research engineering environments；固定时间预算下和人类专家对比；任务如 scaling law fitting、GPU kernel optimization 等 | Blog/Paper: https://evals.alignment.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/；Site: https://metr.github.io/re-bench/；Code: https://github.com/METR/RE-Bench |
| **AIRS-Bench** | 2026 | **Workflow 型 / ML 论文任务** | AI research science agent | 20 个 ML 论文任务；problem、dataset、metric 三元组；normalized score、valid submission rate、Elo | Paper: https://arxiv.org/abs/2602.06855；Code: https://github.com/facebookresearch/airs-bench |
| **Scientist-Bench** | 2025 | **开放 Rubric 型 / 自动科研创新** | 自动科研创新 | guided innovation / open-ended exploration；来自真实 AI 论文任务 | Paper: https://arxiv.org/abs/2505.18705；Project: https://autoresearcher.github.io/；Leaderboard: https://autoresearcher.github.io/leaderboard.html；Code/bench: https://github.com/HKUDS/AI-Researcher |
| **MLS-Bench** | 2026 | **刷分型 / ML 方法发明** | 发明更好 ML 方法 | 140 个任务、12 个域；看跨 setting / seed / dataset / scale 泛化 | Project: https://mls-bench.com/；Paper: https://arxiv.org/abs/2605.08678；Code: https://github.com/Imbernoulli/MLS-Bench |

### 7.2b AIforAI Benchmark：自主做 AI 研究 / 改进 AI 系统本身

这里的 **AIforAI** 指 agent 或自动化系统把目标放在“改进 AI/ML 系统本身”，例如自动做 ML 工程、发明新模型/训练方法、优化 GPU kernel、做 NAS/HPO/AutoML、复现 AI 论文、写 AI research paper。它属于自主科研，但和材料/生物/CFD 的区别是：**研究对象本身就是 AI 方法、AI 系统或 AI 工程栈**。

| Benchmark / 环境 | 提出时间 | 范式 / 类型 | AIforAI 子方向 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **MLE-bench** | 2024 | **刷分型 / ML engineering leaderboard** | Kaggle 式 ML 工程 | agent 能否完成真实 ML competition：数据处理、特征工程、训练、调参、submission | Kaggle public/private leaderboard score、percentile、medal；75 competitions；适合“端到端托管刷分” | Official: https://openai.com/index/mle-bench/；Leaderboard: https://www.mlebench.com/；Code: https://github.com/openai/mle-bench |
| **MLAgentBench** | 2023 | **Workflow 型 / ML experimentation** | 自动 ML 实验 | 给定 dataset + ML task description，agent 读代码、跑实验、改模型，提升 baseline | 13 个 ML engineering tasks；hidden eval scripts；success rate，是否相对 starter baseline 提升 >10%；average improvement | Paper: https://arxiv.org/abs/2310.03302；Code: https://github.com/snap-stanford/MLAgentBench |
| **RE-Bench** | 2024 | **开放任务 / 人类专家对比** | frontier AI R&D engineering | 真实 ML research engineering 环境，如 scaling law、GPU kernel optimization 等 | 7 environments；给 agent/human 电脑和 scoring function；固定时间预算下和 71 个 human expert attempts 对比；score / human percentile | Blog/Paper: https://evals.alignment.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/；Code: https://github.com/METR/RE-Bench |
| **MLE-Dojo** | 2025 | **Gym 型 / 交互式 MLE agent 训练评测** | ML engineering agent RL/SFT | 让 LLM agent 在可执行 ML workflow 中反复实验、debug、refine | 200+ real-world Kaggle challenges；Gym-style interactive feedback；支持 SFT/RL agent training；看 iterative improvement、valid submission、score | Paper: https://proceedings.neurips.cc/paper_files/paper/2025/hash/0603c69125ad4b964bc9c4832f7b9f8f-Abstract-Datasets_and_Benchmarks_Track.html |
| **AIRS-Bench** | 2026 | **Workflow 型 / AI research science** | AI 论文任务复现与超越 | 从 SOTA ML papers 抽取 problem / dataset / metric / SOTA value，agent 需开发 solution | 20 tasks；normalized score、valid submission rate、Elo；和 published SOTA 比 | Paper: https://arxiv.org/abs/2602.06855；Code: https://github.com/facebookresearch/airs-bench |
| **MLR-Bench** | 2025 | **开放 Rubric 型 / ML research e2e** | 开放式 ML 研究 | agent 完成 idea generation、proposal、experimentation、paper writing | 201 workshop research tasks；MLR-Judge 用 LLM reviewers + rubric 评研究质量；支持 stepwise 与 end-to-end 论文评测；人工评估验证 judge | Project: https://chchenhui.github.io/mlrbench/；NeurIPS: https://papers.nips.cc/paper_files/paper/2025/hash/ab8dd000d6f87f40061a73f8bca7fae4-Abstract-Datasets_and_Benchmarks_Track.html |
| **MLRC-Bench** | 2025 | **刷分型 / ML research competitions** | 机器学习研究竞赛 | agent 提出并实现新 ML research 方法，挑战真实 research competition task | 7 competition tasks；objective metrics；看 agent closing gap between baseline and top human participant；也分析 LLM judge innovation 与真实 performance 的错位 | NeurIPS: https://proceedings.neurips.cc/paper_files/paper/2025/hash/82c96f3c90741ef2c9b248e65d9b5db0-Abstract-Datasets_and_Benchmarks_Track.html；Leaderboard/Code: https://huggingface.co/spaces/launch/MLRC_Bench |
| **MLS-Bench** | 2026 | **刷分型 / 方法发明与泛化** | building better AI / method invention | AI system 能否提出可泛化、可扩展的 ML 方法，而不是只调单个任务 | 140 tasks、12 domains：LM、vision/generation、RL、robotics、ML systems、AI4S、optimization、time series、causal 等；normalized task metric；Lite leaderboard | Project: https://mls-bench.com/；Paper: https://arxiv.org/abs/2605.08678；Code: https://github.com/Imbernoulli/MLS-Bench |
| **PaperBench / PaperBench Code-Dev** | 2025 | **复现型 / AI paper replication** | AI 论文复现 | agent 能否复现 ICML 2024 Spotlight/Oral 论文的代码、实验与结果 | 20 papers；8,316 subtasks；hierarchical rubric；LLM judge + human validation；Code-Dev 更偏 implementation tree | Official: https://openai.com/index/paperbench/ |
| **Paper2CodeBench** | 2025 | **复现型 / paper-to-code** | AI paper → repo | agent 根据 ML 论文实现完整代码仓库 | 90 篇 ICLR/ICML/NeurIPS 2024 papers；reference-free + reference-based judge + human author study | Paper: https://arxiv.org/abs/2504.17192；Code/Data: https://github.com/going-doer/Paper2Code |
| **NatureBench** | 2026 | **复现型 / SOTA 科学 ML** | scientific ML SOTA reproduction | agent 复现/超越 Nature-family scientific ML papers；很多任务本质是 AIforScience 模型方法 | 90 tasks、333 eval instances；source-method-hidden；containerized packages；SOTA-normalized improvement / g>0.1 | Paper: https://arxiv.org/abs/2606.24530；Code: https://github.com/FrontisAI/NatureBench；Dataset: https://huggingface.co/datasets/FrontisAI/NatureBench |
| **KernelBench** | 2025 | **工具能力型 / AI systems optimization** | GPU kernel generation / ML systems | LLM/agent 把 PyTorch operators 转成正确且更快的 CUDA/DSL kernel | 250 tasks；correctness vs PyTorch reference；speedup；`fast_p` = 正确且超过 speedup threshold p 的比例 | Code: https://github.com/ScalingIntelligence/KernelBench；Paper/OpenReview: https://openreview.net/forum?id=yeoN1iQT1x；HF: https://huggingface.co/datasets/ScalingIntelligence/KernelBench |
| **TritonBench / TritonGym** | 2025 / 2026 | **工具能力型 / agentic GPU kernel optimization** | Triton operator generation | 生成/优化 Triton GPU kernels；TritonGym 更强调多步 agent loop、compile/verify/profile feedback | TritonBench：184 real-world operators；functional correctness + efficiency；TritonGym：164 operators、standard/OOD/DSL splits，Pass@1 / Perf@1 | TritonBench paper/code: https://github.com/thunlp/TritonBench；TritonGym: https://tritongym.picasso-lab.com/ |
| **NAS-Bench-101 / NAS-Bench-201** | 2019 / 2020 | **刷分型 / NAS 搜索算法** | neural architecture search | 新 NAS 算法能否高效找到好架构 | 查询式 tabular benchmark；NAS-Bench-101 含 423k unique CNN architectures、5M+ trained models；看 best validation/test accuracy vs query budget / wall-clock | NAS-Bench-101: https://proceedings.mlr.press/v97/ying19a.html；NASLib: https://automl.github.io/NASLib/ |
| **JAHS-Bench-201** | 2022 | **刷分型 / NAS + HPO** | joint architecture and hyperparameter search | 同时搜索模型结构和超参数，兼顾多目标、多保真、成本 | surrogate benchmark；约 161M datapoints、20 metrics、3 DL tasks；看 validation error / hypervolume vs runtime / evaluations | Paper: https://proceedings.neurips.cc/paper_files/paper/2022/hash/fd78f2f65881c1c7ce47e26b040cf48f-Abstract-Datasets_and_Benchmarks.html；Docs: https://automl.github.io/jahs_bench_201/；PyPI: https://pypi.org/project/jahs-bench/ |
| **HPOBench / YAHPO Gym / PD1** | 2021 / 2021 / 2024 | **刷分型 / HPO & black-box optimization** | hyperparameter optimization / Bayesian optimization | 自动调参/黑盒优化算法能否用少量预算找到高性能配置 | 多保真、多目标、surrogate/tabular benchmark；看 regret、best-so-far、hypervolume、runtime-normalized performance | HPOBench: https://github.com/automl/HPOBench；YAHPO Gym: https://slds-lmu.github.io/yahpo_gym/；PD1/HyperBO: https://github.com/google-research/hyperbo |

#### AIforAI / Post-training / Alignment benchmark

这一组更接近你说的 **AI4AI**：不是让 agent 做一个 Kaggle 任务，而是让 AI 系统直接改进 LLM / agent / reward model / judge / tool-use model 本身。典型 artifact 是：post-trained checkpoint、LoRA adapter、preference dataset、reward model、judge prompt、decoding policy、tool-calling policy、RLVR/SFT/DPO/GRPO 训练脚本等。

| Benchmark / 环境 | 提出时间 | 范式 / 类型 | AI4AI 子方向 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **PostTrainBench** | 2026 | **Workflow 型 / post-training agent benchmark** | 自动 post-training / alignment | agent 拿到 base LLM、1 张 H100、10 小时，需自主选择 SFT、DPO、GRPO、RFT、数据生成/过滤、解码配置等，让模型在目标 benchmark 上提升 | 4 个 base models：Qwen3-1.7B、Qwen3-4B、SmolLM3-3B、Gemma-3-4B；7 个目标 benchmarks：AIME 2025、Arena Hard、BFCL、GPQA Main、GSM8K、HealthBench、HumanEval；weighted average；v1.1 有 contamination / API-usage / benchmark-lookup judges 和 model identity check | Site/Leaderboard/Traces: https://posttrainbench.com/；GitHub: https://github.com/aisa-group/PostTrainBench |
| **RewardBench / RewardBench 2** | 2024 / 2025 | **刷分型 / reward model evaluation** | reward modeling / DPO implicit reward | 评 reward model、DPO/KTO 等 implicit reward、generative RM / LLM-as-judge 是否能选出 chosen over rejected | Chat、Chat Hard、Safety、Reasoning 等 preference subsets；accuracy / section scores；RewardBench 2 增加 best-of-4、ties 等更强 reward-model evaluation | Code: https://github.com/allenai/reward-bench；Dataset: https://huggingface.co/datasets/allenai/reward-bench；Paper v1: https://arxiv.org/abs/2403.13787；Paper v2: https://arxiv.org/abs/2506.01937 |
| **PPE: Preference Proxy Evaluations** | 2024 | **开放/刷分型 / reward & judge proxy validation** | reward model / LLM judge selection | 评 preference proxy 是否能预测真实 post-RLHF 下游效果；服务于选择 reward model / judge / best-of-N reranker | 16,038 Chatbot Arena human preference pairs；2,555 prompts × 32 responses correctness preference sets；12 metrics、12 domains；看 accuracy、Spearman/Kendall、Brier、separability、best-of-K correctness 等，并验证和 downstream RLHF Arena score 的相关性 | Blog: https://arena.ai/blog/preference-proxy-evaluations/；Code: https://github.com/lmarena/PPE；Paper: https://arxiv.org/abs/2410.14872 |
| **RM-Bench** | 2024 | **刷分型 / reward model robustness** | reward model sensitivity / style bias | reward model 能否识别细微内容差异、抵抗 verbosity / style / formatting 偏置 | Chat、Code、Math、Safety 等域；测 subtle content difference sensitivity、style bias robustness；用于选择 RLHF / inference-time scaling 的 reward model | Paper: https://arxiv.org/abs/2410.16184；Project/GitHub: https://github.com/THU-KEG/RM-Bench |
| **AlpacaEval 2 / LC-AlpacaEval** | 2023 / 2024 | **刷分型 / instruction-following win-rate** | SFT/DPO/RLHF 结果快速评估 | post-trained chat model 相对 reference model 的用户偏好胜率 | 自动 LLM judge pairwise win-rate；length-controlled win-rate 降低长度偏置；和 Chatbot Arena 高相关；低成本快速评估 alignment 迭代 | Code: https://github.com/tatsu-lab/alpaca_eval；Paper LC: https://arxiv.org/abs/2404.04475 |
| **MT-Bench / Chatbot Arena** | 2023 | **开放偏好型 / human & LLM judge** | chat alignment / instruction tuning | MT-Bench 测多轮聊天质量；Chatbot Arena 用匿名 human battles 评真实偏好 | MT-Bench：80 curated multi-turn questions、GPT-4 judge；Arena：crowdsourced pairwise votes、Bradley-Terry / Elo style leaderboard | FastChat/MT-Bench: https://github.com/lm-sys/FastChat/tree/main/fastchat/llm_judge；Arena: https://lmarena.ai/ |
| **Arena-Hard / Arena-Hard-Auto v2** | 2024 / 2025 | **刷分型 / hard preference eval** | post-training model selection | 从 Chatbot Arena logs 自动构造更 hard、更可分离的 open-ended prompts，快速估计模型在 Arena 中的相对表现 | v2 含 500 hard real-world queries + 250 creative writing queries；automatic judges GPT-4.1 / Gemini-2.5；看 win-rate、separability、human preference agreement | Code: https://github.com/lmarena/arena-hard-auto；Blog: https://lmsys.org/blog/2024-04-19-arena-hard/ |
| **IFEval** | 2023 | **程序化 / instruction-following** | instruction following post-training | 模型能否遵循可验证格式/内容约束，如字数、关键词、格式、语言等 | 约 500 prompts、25 类 verifiable instructions；programmatic checker；常用于 SFT/DPO 后评 instruction-following 是否提升 | Paper: https://arxiv.org/abs/2311.07911；Eval harness: https://github.com/EleutherAI/lm-evaluation-harness/tree/main/lm_eval/tasks/ifeval |
| **WildBench** | 2024 | **开放 Rubric / real-user instruction eval** | open-ended chat alignment | 从真实用户任务中评模型面对复杂、开放、真实 query 的表现 | LLM judge + checklist；WB-Score / WB-Elo；v2 引入 checklist 和长度偏置缓解；适合评 post-training 后真实任务质量 | Code: https://github.com/allenai/WildBench；Dataset/Leaderboard: https://huggingface.co/spaces/allenai/WildBench |
| **BFCL / Berkeley Function-Calling Leaderboard** | 2024 / 2026 v4 | **工具能力型 / function calling & agentic eval** | tool-use / function-calling post-training | 评模型选择工具、生成函数参数、schema adherence、多轮 tool-use、agentic web search / memory / format sensitivity | AST / executable checks、tool-call accuracy、latency/cost；v4 增加 agentic、multi-turn、live / memory / web-search 等子项 | Leaderboard: https://gorilla.cs.berkeley.edu/leaderboard；Code/Data: https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard |
| **HealthBench** | 2025 | **开放 Rubric / domain alignment** | high-impact domain post-training | 评 health/medical assistant 的有用性、安全性、可信性；常作为 post-training 目标或安全能力验证 | 5,000 realistic health conversations；48,562 physician-written rubric criteria；model-based grader；看 normalized rubric score、worst-case reliability、context seeking 等 | Official: https://openai.com/index/healthbench/；Code/Data: https://github.com/openai/simple-evals |
| **SWE-bench Verified** | 2024 / 2026 Harbor | **Workflow 型 / coding-agent post-training eval** | coding agent / software engineering | 评模型/agent 能否修复真实 GitHub issue；常用于 code/post-training/agent scaffolding 优化 | 500 human-validated tasks；repo checkout + issue + hidden tests；patch correctness by tests | Official: https://www.swebench.com/；Code: https://github.com/SWE-bench/SWE-bench；Harbor adapter: https://hub.harborframework.com/datasets/swe-bench/swe-bench-verified |

#### AIforAI benchmark 的性质判断

- **刷分 / leaderboard 型**：MLE-bench、AIRS-Bench、MLRC-Bench、MLS-Bench、NAS/HPO 类；最适合 Famou 的 `--mode loop` 自动寻优，因为有明确 metric 和 hidden/public evaluator。
- **Workflow 型**：MLAgentBench、MLE-Dojo、RE-Bench；更像真实 AI 研究/工程环境，需要反复实验、debug、调参、提交 artifact。
- **复现型**：PaperBench、Paper2CodeBench、NatureBench；评论文复现、repo-level implementation、实验 fidelity。
- **AI systems optimization**：KernelBench、TritonBench/TritonGym；对象不是“模型准确率”，而是 AI 基础设施性能，如 GPU kernel latency / speedup。
- **Post-training / alignment 型**：PostTrainBench、RewardBench、PPE、AlpacaEval、Arena-Hard、IFEval、WildBench、BFCL、HealthBench；核心不是训练一个新架构，而是通过数据、SFT/DPO/RLVR/RLHF、reward model、judge、decoding、tool-use 等改进现有模型行为。
- **传统 AutoML/NAS/HPO**：NAS-Bench、JAHS-Bench、HPOBench、YAHPO、PD1；这些不是 agent benchmark，但非常适合作为 agent 的“自动算法设计/优化”底座，因为 evaluator 清晰、泄漏边界容易控制。
- 对 Famou 来说，AIforAI 是最优先接入的方向之一：任务产物可以是 `submission.csv`、完整 repo、paper reproduction artifact、new ML method patch、controller/policy、kernel code 或 NAS/HPO search trace，统一交给 trusted evaluator 打分。

### 7.3 Deep research / 科学问答 / 研究报告

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **ResearcherBench** | 2026 | **开放 Rubric 型 / Deep Research** | 科学 deep research | 65 个真实科研问题；35 个 AI research subjects；Technical Details / Literature Review / Open Consulting；rubric assessment + faithfulness / groundedness | Project/Paper/Code/Dataset/Leaderboard: https://researcherbench.github.io/ |
| **AutoResearchBench** | 2026-04 | **问答 / 检索型** | 文献发现 | 1,000 questions；Deep Research 找唯一目标论文或判空；Wide Research 找完整论文集合；accuracy / IoU；基于 DeepXiv full-text corpus 和统一 ReAct/search 评测 | Project/Leaderboard/Dataset/Code: https://cheryou.github.io/autoresearchbench.github.io/；Paper: https://arxiv.org/abs/2604.25256 |
| **HeurekaBench** | 2026 | **开放 Rubric 型 / 数据分析** | co-scientist / 数据分析问题 | 从真实论文+代码仓库生成开放式问题；看 answer quality 和 critic 改善 | Project: https://brbiclab.epfl.ch/projects/heurekabench/；Paper: https://openreview.net/forum?id=Y7xCdFuFw7；Code: https://github.com/mlbio-epfl/HeurekaBench |
| **FrontierScience** | 2025 | **问答 / 推理型** | 专家级科学推理 | 物理/化学/生物开放式科研题；专家答案/评分 | https://epoch.ai/frontier-science |
| **Humanity’s Last Exam (HLE)** | 2025 | **问答 / 推理型** | 通用高难知识/推理 | 多领域 expert-level 问题；常被 biomedical/scientific agent 抽子集使用 | https://lastexam.ai/ |

### 7.4 生物医学

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **Biomni-Eval1** | 2025 | **Workflow 型 / biomedical action** | 生物 reasoning/action | 433 instances、10 类任务：GWAS causal gene、rare disease、CRISPR delivery 等 | https://github.com/snap-stanford/Biomni |
| **BioAgent Bench** | 2026 | **Workflow 型 / 生信端到端 Agent** | 常见 bioinformatics workflow：RNA-seq、single-cell RNA-seq、comparative genomics、variant calling、metagenomics、transcript quantification 等 | 10 个 curated end-to-end tasks；agent 需产出 VCF/CSV/TSV/QC report 等 artifact；LLM grader 评 pipeline progress / outcome validity，并做 corrupted inputs、decoy files、prompt bloat 等鲁棒性 stress test | https://github.com/bioagent-bench/bioagent-bench |
| **LAB-Bench** | 2024 | **问答 / 检索型** | 生物医学 QA / DBQA / LitQA | 多选或文献/数据库 grounding；accuracy | https://github.com/Future-House/LAB-Bench |
| **BioML-bench** | 2025/2026 | **刷分型 / Leaderboard** | 生物医学 ML | Protein Engineering、Drug Discovery、Regulatory Genomics；leaderboard percentile / held-out metric | https://agentomicsml.com/ |
| **LifeSciBench** | 2026-06 | **开放 Rubric 型 / Workflow** | 生命科学研究任务 | 750 个专家题；7 workflow、7 biological domains；1,062 artifacts；19,020 rubric criteria；normalized rubric score + 70% pass threshold | Official: https://openai.com/index/introducing-life-sci-bench/ |
| **GeneBench-Pro** | 2026-06 | **开放 Rubric 型 / 生物统计推理** | 基因组/定量生物/转化医学多阶段判断 | 129 evaluations；10 primary domains / 21 terminal subdomains；synthetic DGP；复杂数据探索、estimand 判断、分析路径选择；公开 10 题 case studies，部分 held-out | Official: https://openai.com/index/introducing-genebench-pro/；Paper: https://www.biorxiv.org/content/10.64898/2026.06.29.735386v1 |

### 7.5 Agents' Last Exam (ALE)：跨领域专业工作流 benchmark

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **Agents' Last Exam (ALE)** | 2026-06 | **Workflow 型 / 专业数字工作流** | 长程、真实、经济价值导向的 professional computer work；不是单一科学 benchmark，但 science / engineering 覆盖很大 | agent 进入 Windows/Linux sandbox，自主完成任务；每个 task 有 instruction、真实输入数据、hidden reference；结束后由 deterministic grader 或 judge-based grader 评分；公开 release 约 150 tasks，整体语料 1,000+ tasks，目标 55 subdomains / 13 clusters | https://agents-last-exam.org/；https://agents-last-exam.org/docs/ale/index.html；https://agents-last-exam.org/taxonomy |

ALE 的定位不是“科学问答”或“MMLU/HLE 类知识题”，而是 **真实软件环境里的端到端工作流**。对 Famou e2e mode 来说，它的价值在于：任务环境、输入数据、hidden reference、外部 grader 和 trajectory/artifact 记录都比较接近我们要的 trusted evaluator 形态。

#### ALE 中 science / engineering 相关领域

| ALE 大类 / cluster | science 相关子域 / workflow 方向 | 典型软件 / 任务形态 | 链接 |
|---|---|---|---|
| **Engineering & Architecture** | Chemical & Process Engineering；Aerospace Engineering；Mechanical Engineering；Civil & Structural Engineering；Power Systems Engineering；Mining & Geological Engineering；Semiconductor / EDA；Marine & Naval Engineering；Urban / Transportation；Robotics & Autonomous Systems | Aspen / Cantera / ChemSep / IDAES；OpenFOAM / SU2 / GMAT / Orekit；Ansys / COMSOL / Code_Aster；OpenDSS / pandapower；Yosys / OpenROAD / OpenSTA；ROS2 / Kalibr / OpenVINS / CARLA；SUMO / QGIS 等 | https://agents-last-exam.org/taxonomy |
| **Physical Sciences** | Physics；Plasma & Fluid Dynamics Research；Computational Chemistry & Materials Science；Computational Materials Science；Astronomy & Astrophysics；Earth & Atmospheric Science | OpenMC / MCNP / SCALE / ROOT；ORCA / RDKit / GROMACS / Quantum ESPRESSO / AiiDA；AstroDrizzle / iSpec / CIAO / TOPCAT / GADGET-4；WRF / SeisComP / Grond / ROMS / CESM | https://agents-last-exam.org/taxonomy |
| **Life Sciences** | Computational Drug Discovery；Structural Biology & Protein Engineering；Synthetic Biology；Genomics & Bioinformatics；Cell Biology & Bioimaging；Systems Biology & Pathway Modeling；Microbiome & Metagenomic Analysis | PDBFixer / fpocket；AutoDock Vina / gnina；RDKit / ZINCPharmer；ColabFold / MolProbity / DockQ；ProteinMPNN / OpenFold；BWA-MEM2 / GATK / Sniffles2 / Mutect2 | https://agents-last-exam.org/taxonomy |
| **Health & Medicine** | Medical Imaging；Anatomic & Digital Pathology；Clinical Laboratory Science；Biomedical Engineering | FreeSurfer / Freeview；TotalSegmentator / 3D Slicer；ANTs / FSL FLIRT；OpenSim / motion analysis；clinical / research imaging registration、segmentation、quantification | https://agents-last-exam.org/taxonomy |
| **Psychology & Neuroscience** | Computational Neuroscience；Behavioral / cognitive experiment and analysis workflow | NWB / BIDS；Suite2p；NEURON；NEST；The Virtual Brain；fMRI / EEG / calcium imaging / connectomics / circuit modeling | https://agents-last-exam.org/taxonomy |
| **Computing, Data & Mathematical Sciences** | Data Science & Statistics；Computer Science Research；Mathematical Sciences；Operations Research & Optimization；Quantum Computing | data / statistics workflow；formal math / optimization；Qiskit / PySCF / PennyLane / Stim / MQT Bench；quantum chemistry and materials simulation | https://agents-last-exam.org/taxonomy |
| **Transportation & Safety Operations** | Fire Science & Safety Engineering；部分 aviation / maritime / safety simulation workflow | FDS / CFAST / Pathfinder / ALOHA / MARPLOT / OpenFOAM；fire, smoke, evacuation, hazardous-atmosphere risk modeling | https://agents-last-exam.org/taxonomy |
| **Agriculture & Environment** | Environmental Modeling & Assessment；Environmental Engineering & Water Resources；Precision Agriculture | WRF / hydrology / GIS / QGIS / geospatial agronomy / remote sensing / prescription workflows | https://agents-last-exam.org/taxonomy |
| **Social Sciences** | Computational Social Science；Social Science & Economics | Stata / IPUMS CPS / PyBLP / Dynare / X-13ARIMA-SEATS / openICPSR；policy evaluation、econometrics、network analysis、survey methodology、replication packages | https://agents-last-exam.org/taxonomy |

定位判断：ALE 更偏 **Workflow 型 / 专业数字工作流**，不是“刷 SOTA 的模型榜”，也不是纯科学 benchmark。它适合用来评 agent 能不能在真实工具链里把科研/工程 workflow 跑完，并把 artifact 交给外部 trusted evaluator。

### 7.6 Terminal-Bench Science (TB-Science)：终端科学工作流 benchmark

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **Terminal-Bench Science (TB-Science)** | 2026-02 / 2026-05 | **Workflow 型 / 终端科学计算** | 真实科学研究中的 computational workflow；目标 100+ tasks | 基于 Terminal-Bench / Harbor；每个 task 是 containerized terminal environment；agent 在终端中完成任务；用程序化 verification / deterministic pytest-style tests / artifact checks 评估；强调 real workflow 而不是 textbook QA | https://github.com/harbor-framework/terminal-bench-science；https://www.tbench.ai/news/tb-science-announcement |

TB-Science 是 Terminal-Bench 的 science 扩展，定位是“在终端环境中评估 AI agents 完成真实科学计算 workflow 的能力”。它不是开放式假设生成 benchmark，也不是纯 ML leaderboards，而是要求任务可容器化、可程序化验证，和 Famou 的 trusted evaluator 方向高度一致。

注：repo citation 里标注 2026-02，官网公开 announcement 是 2026-05-20；这里同时保留两者，避免后续引用时混淆。

#### TB-Science 领域覆盖

| 大类 | 覆盖领域 | 当前状态备注 |
|---|---|---|
| **Life Sciences** | Biology、Ecology、Medicine、Neuroscience | 截至 2026-07-29，公开 README task count：Biology 1、Medicine 1、Neuroscience 2、Ecology 0 |
| **Physical Sciences** | Astronomy、Chemistry、Materials Science、Physics | 截至 2026-07-29，公开 README task count：Astronomy 0、Chemistry 1、Materials Science 2、Physics 3 |
| **Earth Sciences** | Atmospheric Sciences、Environmental Sciences、Geosciences、Ocean Sciences | 截至 2026-07-29，公开 README task count：Atmospheric Sciences 0、Ocean Sciences 0、Geosciences 2、Environmental Sciences 0 |
| **Mathematical Sciences** | Applied Mathematics、Formal Mathematics、Operations Research、Statistics | 截至 2026-07-29，公开 README task count：Applied Mathematics 2、Formal Mathematics 2、Operations Research 1、Statistics 1 |
| **Engineering Sciences** | Chemical Engineering、Civil Engineering、Electrical Engineering、Mechanical Engineering | 截至 2026-07-29，公开 README task count：四个 field 当前均为 0；仍是官方目标覆盖方向 |

截至 2026-07-29，TB-Science 公开 README 统计的 current task count 合计为 18。这个数字应视为动态状态，不应写死进评估框架，只应作为调研快照。

定位判断：TB-Science 比 ALE 更窄，但更接近我们要的 **“scientific workflow in terminal + deterministic trusted evaluator”**。如果要给 Famou e2e mode 选第一批非刷榜 benchmark，它优先级很高。

### 7.7 脑科学 / 神经影像

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **BrainPilotBench-v0** | 2026 | **Workflow 型 / 端到端数据分析** | 脑科学端到端任务 | calcium imaging、fMRI pain connectivity、BCI EEG、sleep staging 等；containerized execution + ground truth | https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public |
| **NeuroBench** | 2026 | **Workflow 型 / 可复现性** | 神经影像 workflow | executability、artifact validity、reproducibility readiness | https://github.com/CUHK-AIM-Group/NeuroClaw |
| **BrainAgent benchmark** | 2026 | **Workflow 型 / 分析型** | 脑信号分析 Agent | Task Completion Rate、工具负载稳定性、复杂 workflow 成功率 | https://arxiv.org/abs/2606.25400 |

注：BrainPilot 使用过 ALE 中的 3 个脑科学任务，但 ALE 本身已在 7.5 单独列出。

### 7.8 科学工具使用 / 可视化 / 开放科学任务

| Benchmark | 提出时间 | 范式 / 类型 | 测什么 | 评测方式 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **SciAgentBench / SciAgentGym** | 2026-02 | **工具能力型 / 长程任务** | 科学 tool-use | 1,780+ 科学工具；Physics / Chemistry / Materials Science / Life Science / Astronomy；多步工具调用、长程 workflow success | Paper: https://arxiv.org/abs/2602.12984；Code/Data: https://github.com/CMarsRover/SciAgentGYM |
| **SciVisAgentBench** | 2026-03 | **工具能力型 / 科学可视化** | 科学可视化 | 108 expert-crafted cases；8 domains；5 data types；14 visualization operations；LLM judge + image metrics + code/rule/case-specific verifiers | Project: https://scivisagentbench.github.io/；Paper: https://arxiv.org/abs/2603.29139；Code: https://github.com/KuangshiAi/SciVisAgentBench；Dataset: https://huggingface.co/datasets/SciVisAgentBench/SciVisAgentBench-tasks |
| **Matter to Mechanism** | 2026-06 | **机理 / 假设生成型** | 材料/电池机制推理 | 2,645 problem-hypothesis pairs；BatteryHypoBench metrics：reasoning fidelity、problem alignment、mechanistic specificity、novelty、plausibility、decomposition | Paper: https://arxiv.org/abs/2606.02258；Dataset: https://huggingface.co/datasets/Boson20/matter-to-mechanism |
| **FIRE-Bench** | 2026-02 | **Workflow 型 / insight rediscovery** | 科学 insight rediscovery | 30 个来自 ICLR/ICML/NeurIPS/Nature 等论文的 research rediscovery tasks；Plan→Implement→Execute→Analyze；claim-level precision/recall/F1 | Project: https://firebench.github.io/；Paper: https://arxiv.org/abs/2602.02905；Code: project page 标注 coming soon |


### 7.9 材料学 Benchmark：ML 代理模型 / 机理建模 / 生成设计

| Benchmark / 数据集 | 提出时间 | 范式 | 子方向 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **Matbench** | 2020 | **刷分型 / ML 代理模型** | 材料性质预测 | 13 个监督学习任务，覆盖形成能、带隙、弹性、介电、声子、2D exfoliation、合金强度等 | 回归任务多用 MAE/RMSE，分类任务用 ROC-AUC 等；固定 split + leaderboard | https://github.com/materialsproject/matbench |
| **Matbench Discovery** | 2023/2024 | **刷分型 / 候选排序发现** | 新稳定晶体发现 / universal potential 评测 | 模拟高通量材料发现：从未弛豫结构预测形成能 / hull distance / 稳定性，并排序候选 | F1、precision/recall、formation-energy MAE、hull-distance MAE、Discovery Acceleration Factor (DAF)、top-k 稳定材料命中率；DFT reference convex hull 评稳定性 | https://github.com/janosh/matbench-discovery |
| **JARVIS-Leaderboard** | 2024 | **刷分型 / 多任务材料 Leaderboard** | 综合材料设计 | AI、电子结构、力场、实验、量子计算等多类材料 benchmark | 单性质预测 MAE、分类指标、MLFF 能量/力误差、电子结构与实验对比、QC eigensolver 误差等；要求提交代码、数据和元数据 | https://pages.nist.gov/jarvis_leaderboard/ |
| **Open Catalyst Project / OC20 / OC22** | 2020 / 2022 | **刷分型 / 物理启发 ML** | 催化材料 / 吸附能 | 催化剂表面 + adsorbate 的能量与力预测、弛豫后能量、吸附能全局最小搜索 | S2EF：Energy MAE、Force MAE、EFwT；IS2RE：Energy MAE / EwT；challenge 还评 global-minimum adsorption energy success rate | https://opencatalystproject.org/ |
| **OMat24** | 2024 / 2026 article | **刷分型 / ML 势能面** | inorganic materials | 1.1 亿+ DFT calculations，用于训练/评测开放材料基础势模型 | Matbench-Discovery F1、formation energy MAE、phonon / thermal conductivity task 等 | Paper: https://arxiv.org/abs/2410.12771；Nature: https://www.nature.com/articles/s43588-026-00996-w；Dataset: https://huggingface.co/datasets/facebook/OMAT24；Models: https://huggingface.co/facebook/OMAT24；Code: https://github.com/facebookresearch/fairchem |
| **MGB: Material Generation Benchmark** | 2025 | **刷分型 / 生成设计** | 材料生成 / CSP / MOF / OOD | 晶体结构预测、de novo material generation、MOF structure prediction、OOD generation | structural accuracy、chemical validity、distributional coverage、physical plausibility、efficiency；专门构造 OOD test sets | OpenReview: https://openreview.net/forum?id=K15Dqxm0ge；代码/权重：作者称整理中 |
| **MatterGen benchmark** | 2025 | **刷分型 / 生成设计** | 无机材料生成 | 属性约束生成和 de novo 晶体生成 | % Stable、% Unique、% Novel、% S.U.N.、RMSD；常用 MatterSim / DFT relaxation 评估 | https://github.com/microsoft/mattergen |
| **LeMat-GenBench** | 2025 / 2026 | **刷分型 / 生成设计** | 晶体生成 | 无条件 / 条件 / limited-budget crystal generation 的统一评测 | validity、stability、novelty、uniqueness、SUN/MSUN、diversity、distribution、efficiency；HF public leaderboard + verified submissions | OpenReview: https://openreview.net/forum?id=ZfPGcTfDWn；Paper: https://arxiv.org/abs/2512.04562；Code: https://github.com/LeMaterial/lemat-genbench；Leaderboard: https://huggingface.co/spaces/LeMaterial/LeMat-GenBench |
| **matbench-genmetrics** | 2024 | **刷分型 / 生成设计** | 晶体生成 | 基于 Materials Project time split 的生成评测 | validity、coverage、novelty、uniqueness；固定 split + Python metrics library | Docs: https://matbench-genmetrics.readthedocs.io/；Code: https://github.com/sparks-baird/matbench-genmetrics；JOSS: https://joss.theoj.org/papers/10.21105/joss.05618；PyPI: https://pypi.org/project/matbench-genmetrics/ |
| **MOFX-DB / MOF DB / hMOF-ML** | 2020-2024 | **刷分型 / ML 代理模型** | MOF / 多孔材料 | MOF 气体吸附、H2/CH4/CO2 等吸附与 textural properties | 吸附量预测误差、screening rank、GCMC reference；MOFX-DB 含 300 万+ simulated adsorption datapoints | https://www.mofdb.com/ |
| **OpenPoly** | 2025 | **刷分型 / ML 代理模型** | 聚合物材料 | 26 个聚合物性质预测 | 多编码方式 + 多模型统一 benchmark；稀疏实验数据下比较 MAE/RMSE/R² 等 | Paper/DB: https://www.cjps.org/en/article/doi/10.1007/s10118-025-3402-y/ |
| **2DMatPedia / JARVIS-2D** | 2019-2024 | **刷分型 / ML 代理模型** | 二维材料 | 2D exfoliation energy、decomposition energy、bandgap 等 | 与 DFT / 已知 exfoliable materials 对比；常作为训练/验证数据源 | 2DMatPedia: http://www.2dmatpedia.org/；JARVIS: https://jarvis.nist.gov/；ColabFit JARVIS_2DMatPedia: https://materials.colabfit.org/id/DS_hdv6si8yu2mv_0 |
| **BatteryMat / JARVIS-Battery 类** | 2020-2025 | **刷分型 / 候选发现** | 电池材料 | 电极平均电压、容量、稳定性、离子迁移 barrier | 与 DFT / 已知 LFP、LMO、LCO、NMC 等参考对比；voltage error、capacity error、候选筛选命中 | JARVIS-Leaderboard: https://pages.nist.gov/jarvis_leaderboard/；JARVIS databases: https://pages.nist.gov/jarvis/databases/ |
| **SuperCon / JARVIS-SuperConDB / SuperCon3D** | 2018-2026 | **刷分型 / 候选发现** | 超导材料 | Tc 预测、超导候选筛选、3D/2D 超导材料 | 回归 Tc error、rediscovery 已知超导体、实验验证新候选 | SuperConDB: https://jarvis.nist.gov/supercon；JARVIS-Leaderboard AI supercon tasks: https://pages.nist.gov/jarvis_leaderboard/AI/ |

#### 材料学 benchmark 的评测要点

- **材料预测**：通常是结构/组成 → 性质，指标以 MAE/RMSE/R²/ROC-AUC 为主。
- **新材料发现**：不能只看 formation energy MAE，更要看 thermodynamic stability / hull distance / top-k stable hit / DAF。
- **生成模型**：常用 validity、coverage、novelty、uniqueness，但这些容易被 reference set 和 structure matcher 影响；更硬的指标是 **S.U.N. = Stable + Unique + Novel**，最好接 DFT / MLIP relaxation。
- **催化 / MOF / 电池**：更接近应用，需要 adsorption energy、voltage、capacity、barrier、GCMC adsorption 等物理任务指标。
- **Agent 评测建议**：如果评“材料科研 Agent”，应让 agent 完成“检索 → 候选生成/筛选 → 用 MLIP/DFT 验证 → 排名 → 写报告”，而不是只做单模型 property prediction。

### 7.10 量子计算 Benchmark：量子编程 / 量子线路 / 量子软件工具

| Benchmark / 工具 | 提出时间 | 范式 / 类型 | 子方向 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **Qiskit HumanEval / QHE Hard** | 2024 | **工具能力型 / 代码生成** | 量子代码生成 | LLM 生成 Qiskit 代码 | 约 150 个 Qiskit 任务；canonical solution + unit tests；basic/intermediate/difficult；Hard 版去掉 import/signature 等提示 | https://github.com/qiskit-community/qiskit-human-eval |
| **QCoder Benchmark** | 2025 | **工具能力型 / 反馈编程** | 量子编程 + 模拟硬件反馈 | 从自然语言生成可运行量子程序，并用量子 simulator 反馈 | accuracy、circuit depth、execution time、error classification；可和真实人类 contest submissions 对比 | https://qcoder-bench.github.io/ |
| **QCircuitBench** | 2025 | **工具能力型 / 算法设计** | LLM 驱动量子算法设计 | 量子算法 → quantum circuit code + classical post-processing | 3 大任务套件、25 类算法、120k+ datapoints；QASM/Python 语法验证、语义验证、gate count、shot count、运行开销 | https://github.com/EstelYang/QCircuitBench |
| **MQT Bench** | 2023 | **刷分型 / 工具链 benchmark** | 量子软件栈 / circuit benchmark | 编译器、模拟器、SDK、硬件 target 的跨层评测 | 70k+ benchmark circuits；算法级、target-independent、native gates、mapped levels；GHZ、QAOA、QFT、Grover、Shor 等 | https://github.com/munich-quantum-toolkit/bench |
| **QASMBench** | 2020 | **刷分型 / 线路 benchmark** | NISQ 低层线路 benchmark | OpenQASM 线路集合，评硬件/编译器/模拟器 | 小/中/大规模 circuits；gate density、retention lifespan、measurement density、entanglement variance；也看 fidelity / simulator performance | https://github.com/pnnl/QASMBench |
| **SupermarQ** | 2022 | **刷分型 / workload benchmark** | hardware-agnostic quantum benchmark | 应用级 quantum workload 覆盖和硬件表现 | 6 维特征：communication、critical depth、entanglement ratio、parallelism、liveness、measurement；GHZ/QAOA/VQE/Hamiltonian simulation 等任务有各自 benchmark score | Paper: https://arxiv.org/abs/2202.11045；Code: https://github.com/Infleqtion/client-superstaq；Zoo: https://quantumbenchmarkzoo.org/content/benchmarking-tools/benchmark-suites/Supermarq |
| **Benchpress** | 2025 | **刷分型 / SDK benchmark** | Quantum SDK benchmark | Qiskit / TKET / Cirq / Braket / BQSKit 等 SDK 构建与 transpile 表现 | 1,000+ tests；completion、runtime、two-qubit gate count、fidelity proxy；pytest-based suite；7 个 SDK 横向比较 | Code: https://github.com/Qiskit/benchpress；Paper: https://arxiv.org/abs/2409.08844；Nature: https://www.nature.com/articles/s43588-025-00792-y；Results data: https://zenodo.org/records/14977295 |
| **JARVIS-Leaderboard QC / AtomQC** | 2024 | **机理 / 方程发现型** | 材料相关量子计算 | quantum eigensolver / VQE / Hamiltonian simulation for materials | EigenSolver 误差、MULTIMAE；VQE 参数、optimizer、ansatz、basis、noise model 等比较 | https://pages.nist.gov/jarvis_leaderboard/QC/EigenSolver/ |

#### 量子计算 benchmark 的评测要点

- **LLM/Agent 量子编程**：不能只看代码能不能运行，还要看电路语义是否正确、测量后处理是否正确、线路深度/门数/shot 数是否合理。
- **量子算法设计**：QCircuitBench 比 Qiskit HumanEval 更偏“算法设计”，因为它要求 quantum circuit + classical post-processing 一起正确。
- **量子软件工具**：MQT Bench / QASMBench / SupermarQ 更适合评编译器、SDK、模拟器和硬件；不是科研 Agent 专用，但可以作为 Agent 的执行环境 benchmark。
- **材料 + 量子计算交叉**：JARVIS QC / AtomQC 更贴近“材料体系 Hamiltonian 的 quantum eigensolver / VQE”，适合评 quantum-for-materials agent。

### 7.11 流体力学 / CFD：Agent 与 Benchmark

#### 7.11.1 CFD / OpenFOAM Agent

| 系统 | 提出时间 | 性质 | 端到端程度 | 主要能力 | 评测 / 结果 | 代码 / 站点 |
|---|---:|---|---:|---|---|---|
| **MetaOpenFOAM** | 2024 | 工作流型 / 仿真型 | L3 | 自然语言到 OpenFOAM 仿真，多智能体分工，RAG 辅助 | 8 个 CFD 任务；pass rate 85%；平均 $0.22 / case | https://arxiv.org/abs/2407.21320 |
| **FoamPilot** | 2024 | 工作流型 / 分析型 | L2-L3 | FireFOAM 代码理解、case 配置、HPC 执行、结果分析 | 简单任务表现较好；复杂任务仍不足 | https://arxiv.org/abs/2412.17146 |
| **OpenFOAMGPT** | 2025 | 工作流型 / 修复型 | L3 | RAG 增强的 OpenFOAM agent；自动修改边界条件、湍流模型、代码翻译 | 多任务成功；iterative correction 处理单/多相流、热传递、RANS、LES | https://arxiv.org/abs/2501.06327 |
| **CFDagent** | 2025 | 端到端仿真型 | L4 | 文本/图像 → 几何 → 网格 → 求解 → 后处理 | 球绕流等 canonical case；drag/lift 与参考一致 | https://arxiv.org/abs/2507.23693 |
| **ChatCFD** | 2026 | 端到端仿真型 | L4 | 结构化知识 + 精确错误定位 + 反思式 OpenFOAM 自动化 | 315 benchmark cases；82.1% execution success；68.12% physical fidelity；97.4% summary fidelity | https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/aidi.202500174 |
| **IteraSim RAG** | 2026 | 工作流型 / 端到端仿真型 | L3-L4 | 多阶段检索增强 OpenFOAM 后端，Architect/InputWriter/Reviewer 分工 | 28-case benchmark；mean retrieval coverage 77.9%；全部 6 个 reference configurations 跑通 | https://arxiv.org/abs/2607.20346 |

#### 7.11.2 含 CFD cases 的 Agent Benchmark / 榜单

这里不要求整个 benchmark 都是 CFD；只要包含 OpenFOAM / CFD / CAE 仿真 case，就对 Famou 的 e2e benchmark mode 有参考价值。

| Benchmark / 榜单 | 提出时间 | 性质 | CFD 覆盖 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **sim-benchmark** | 2025/2026 | CAE / EDA 真实仿真工作流 agent benchmark | suite 中含 **11 个 OpenFOAM CFD cases**，另有 LTspice / EDA 等仿真任务 | agent 是否能从任务说明完成真实工程仿真：准备 case、运行 solver、产出 artifact | artifact-grounded scoring；不主要依赖 LLM judge；有 public leaderboard；适合类 MLE-bench 的“提交产物 → 评分器打分”范式 | https://svdailab.com/blog/sim-benchmark |
| **CFDLLMBench** | 2025 | CFD 领域 LLM / agent 能力套件 | CFDQuery / CFDCodeBench / FoamBench | CFD 知识、数值/物理推理、OpenFOAM 工作流实现 | code executability、solution accuracy、numerical convergence；更像能力评测套件，非成熟 leaderboard | Paper: https://arxiv.org/abs/2509.20374；Code/Data: https://github.com/NREL-Theseus/cfdllmbench/ |
| **ChatCFD benchmark cases** | 2026 | OpenFOAM agent 论文 benchmark | 315 OpenFOAM benchmark cases | 自然语言到 OpenFOAM 仿真、错误定位、物理可信度、总结 fidelity | execution success、physical fidelity、summary fidelity；论文内部 benchmark/对比，不是通用开放榜单 | https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/aidi.202500174 |
| **MetaOpenFOAM benchmark tasks** | 2024 | OpenFOAM 多智能体论文 benchmark | 8 个 CFD simulation tasks | 自然语言生成 OpenFOAM case 并运行 | pass rate、成本/case；论文内部 benchmark，不是 MLE-bench 式成熟开放榜 | https://arxiv.org/abs/2407.21320 |

#### 7.11.3 CFD / 流体 ML Benchmark

| Benchmark | 提出时间 | 性质 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|
| **PDEBench** | 2022 | 通用科学机器学习 PDE 基准 | 多种 PDE time-dependent simulation；forward / inverse problems | 泛化误差、rollout 稳定性、不同 PDE / 初边值 / 参数外推；baseline 包括 FNO、U-Net、PINN | Paper: https://arxiv.org/abs/2210.07182；Code: https://github.com/pdebench/PDEBench；HF: https://huggingface.co/pdebench |
| **AirfRANS** | 2022 | 翼型 RANS surrogate | 2D steady incompressible RANS；NACA airfoils；OpenFOAM raw data / processed point-cloud data | velocity/pressure/turbulent-viscosity field error；lift/drag force coefficient；边界层、Re/AoA extrapolation | Paper: https://arxiv.org/abs/2212.07564；Docs/Data loader: https://airfrans.readthedocs.io/en/latest/ |
| **CFDBench** | 2023 | CFD 神经算子泛化 | lid-driven cavity、tube boundary layer、step dam、Kármán vortex street | velocity/pressure 误差、multi-step inference、autoregressive error accumulation；baseline 包括 FNO / DeepONet / U-Net 等 | Paper: https://arxiv.org/abs/2310.05963；Code/Data: https://github.com/luo-yining/CFDBench |
| **FlowBench** | 2024 | 复杂几何流动 | parametric / non-parametric complex geometry；2D/3D；steady/transient；forced/free convection | velocity/pressure/temperature；lift/drag/Nusselt；FNO/CNO/WNO/DeepONet；复杂几何泛化 | Paper: https://arxiv.org/abs/2409.18032；HF data: https://huggingface.co/datasets/BGLab/FlowBench；Code: https://github.com/baskargroup/GeometryMatters |
| **The Well** | 2024 | 多物理仿真集合 | 16 个物理数据集，15TB，含 fluid dynamics、MHD、acoustic、reaction-diffusion、astrophysics 等 | 统一 PyTorch dataset API；VRMSE / MAE / Pearson 等 metrics；可作 broad physics benchmark suite | Paper: https://arxiv.org/abs/2412.00568；Code: https://github.com/PolymathicAI/the_well；Docs: https://polymathic-ai.org/the_well/ |

#### 7.11.4 CFD benchmark 的评测要点

- **传统 CFD surrogate**：主要看 PDE 解误差、rollout 稳定性、参数外推、复杂几何泛化。
- **含 CFD cases 的 agent benchmark**：sim-benchmark 这类最接近 MLE-bench，因为它要求 agent 在真实仿真工作流里产出 artifact，再由外部评分器评估；缺点是 CFD case 数量还不大，而且不是纯 CFD 榜。
- **OpenFOAM / agentic CFD**：不仅看能不能跑通，还要看：
  - 能否选对 solver / turbulence model；
  - 边界条件、几何、网格、后处理是否一致；
  - convergence 与 physical fidelity；
  - 是否能在错误后自动修复；
  - 是否能复现 literature case。
- **LLM benchmark**：CFDLLMBench 这类更适合评 agent 的知识、推理和工作流实现；而 sim-benchmark / MetaOpenFOAM / OpenFOAMGPT / ChatCFD / CFDagent 更接近“端到端仿真 Agent”。

### 7.12 控制系统 / 动力系统 / 强化学习控制 Benchmark

控制领域的 benchmark 很多，但大部分不是“发现新科学”的 agent benchmark，而是测 **控制器 / 策略 / 算法** 在一个动力系统仿真环境中的表现。它们对 Famou e2e mode 的价值是：可以让 agent 自动建模、调参、训练控制器、和 MPC/LQR/NMPC baseline 比较，并把最终 policy 或 controller artifact 交给外部 evaluator。

| Benchmark / 环境 | 提出时间 | 范式 / 类型 | 子方向 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **ControlBench** | 2024 | **问答 / 设计推理型** | 经典控制理论 / 控制工程 LLM 评测 | LLM 解本科控制题：block diagram、root locus、frequency response、state-space、stability、controller design 等 | 147 个开放题 + 100 个多选版 ControlBench-C；human expert annotation；ACC / self-check ACC；更像控制理论 reasoning，不是仿真闭环控制 | https://agi4engineering.github.io/LLM4Control/ |
| **Controlgym** | 2024 | **刷分型 / 控制策略学习** | 工业控制 + PDE 控制 | 36 个 industrial control settings + 10 个 infinite-dimensional PDE control problems；Gym/Gymnasium 接口 | RL policy 的 reward / regulation performance / tracking / stability / scalability；支持 stable-baselines3 等算法；重点看学习控制策略在高维/无限维系统上的表现 | https://proceedings.mlr.press/v242/zhang24b.html；https://github.com/xiangyuan-zhang/controlgym |
| **safe-control-gym** | 2021 | **安全控制 / RL vs 传统控制** | 安全 learning-based control | cart-pole、1D/2D quadrotor；stabilization、trajectory tracking；显式模型、约束、扰动 | control performance、data efficiency、constraint violation / safety；可比较 LQR、MPC、RL、learning-based control | https://github.com/utiasDSL/safe-control-gym |
| **Safety Gym** | 2019 | **安全 RL / 连续控制** | 安全探索 / constrained RL | Point、Car、Doggo 等机器人连续控制任务，带 hazards / constraints | episodic return、episodic cost、average cost over training；评 safe exploration 和 constrained RL | https://openai.com/index/safety-gym/ |
| **Safety-Gymnasium** | 2023 | **安全 RL / 多智能体控制** | 安全连续控制 / 视觉输入 / 多智能体 | Safety Gym 的扩展和现代化环境；single-agent / multi-agent；vector / vision input | return + cost / constraint violation；配套 SafePO 算法库，含多种 SafeRL SOTA baseline | https://github.com/PKU-Alignment/safety-gymnasium |
| **PDEControlGym** | 2024 | **机理仿真 / PDE 控制** | 分布参数系统控制 | 1D/2D PDE control environments，面向 control theory 与 RL | RL/Gym 式 policy evaluation；看 PDE 状态调节、控制代价、稳定性、泛化；比普通 ODE 控制更接近流体/热传导/反应扩散等机理系统 | https://pdecontrolgym.readthedocs.io/；https://github.com/lukebhan/PDEControlGym |
| **PC-Gym** | 2024 / 2026 | **工业过程控制 / RL vs NMPC** | 化工过程控制 | CSTR、four-tank、multistage extraction、crystallization 等非线性化工过程；有扰动、约束、reward 设计 | 累计 reward、setpoint tracking、constraint violation、control effort；把 RL 和 NMPC oracle / baseline 比较 | https://github.com/MaximilianB2/pc-gym；https://doi.org/10.1016/j.compchemeng.2025.109363 |
| **BOPTEST** | 2019-2022 | **建筑控制 / 真实仿真 API** | 建筑 HVAC / 能源控制 / FDD | simulated buildings + standard API；操控 sensor / actuator control points；比较 advanced control strategies | energy use、thermal comfort、cost、emissions、peak demand、grid interaction、fault detection performance 等 | https://www.energy.gov/cmei/buildings/boptest-building-operations-testing-framework |
| **CityLearn / CityLearn Challenge** | 2019 / 2020-2021 / 2023 v2 | **多智能体能源控制 / Leaderboard** | 城市建筑群 demand response | 多建筑 micro-grid，控制热水/冷水/电池储能，削峰填谷和负荷平滑 | peak demand、ramping、load factor、cost、emission / comfort 等多目标指标；Challenge 有 leaderboard | https://www.citylearn.net/；https://github.com/intelligent-environments-lab/CityLearn |
| **Grid2Op / L2RPN** | 2020 | **电网控制 / 竞赛型** | 电力系统拓扑控制 / 调度 | sequential decision making for power grid operations；redispatching、curtailment、storage、topology actions，防止线路过载和 blackout | L2RPN competition score、survival time、operational cost、constraint violation、blackout avoidance；真实非线性 power-flow simulator | https://grid2op.readthedocs.io/；https://github.com/Grid2op/grid2op；https://l2rpn.chalearn.org/ |
| **DeepMind Control Suite / MuJoCo Gymnasium** | 2018 / 持续维护 | **连续控制 RL 基准** | 机器人/物理连续控制 | cartpole、cheetah、walker、humanoid、manipulator 等 MuJoCo 物理任务 | episode return、success、sample efficiency；更偏 RL algorithm benchmark，不是控制工程专用 | https://github.com/google-deepmind/dm_control；https://gymnasium.farama.org/environments/mujoco/ |
| **Meta-World / RLBench / RoboSuite** | 2019-2020 | **机器人控制 / 多任务 manipulation** | 机械臂控制 / imitation / RL | 多任务机器人操作、视觉引导操作、meta-RL / multi-task RL | success rate、return、generalization to unseen tasks；适合机器人 agent，但离经典控制理论较远 | https://github.com/Farama-Foundation/Metaworld；https://github.com/stepjam/RLBench；https://github.com/ARISE-Initiative/robosuite |

#### 控制 benchmark 的评测要点

- **和材料/CFD benchmark 不同**：控制 benchmark 的核心 artifact 通常不是一个预测模型，而是一个 **controller / policy / planner**。
- **机制 vs ML**：Controlgym、PDEControlGym、PC-Gym、BOPTEST、Grid2Op 都有明确动力学/仿真机制；但评测时常让 RL/ML 方法去学习控制策略，因此属于 **机理仿真 + 策略学习混合型**。
- **纯控制理论推理**：ControlBench 更像“控制工程考试题”，评公式推导、稳定性分析和控制器设计，不要求闭环仿真。
- **安全控制**：safe-control-gym、Safety Gym、Safety-Gymnasium 不只看 reward，还看 constraint violation / cost，适合评 agent 是否能避免“刷分但不安全”。
- **最适合 Famou e2e 的形态**：
  1. 给 agent 一个动态系统、约束、目标；
  2. agent 自动选择 LQR/MPC/PID/RL/NMPC 等方法；
  3. 训练或求解 controller；
  4. 生成 policy/controller artifact；
  5. hidden evaluator 在未暴露测试场景、扰动、初值上跑闭环仿真，返回 score。

### 7.13 数学 Benchmark：解题 / 证明 / 形式化证明 / 数学发现

数学领域 benchmark 很丰富，而且和 Famou e2e mode 很契合：数学题通常有明确答案或 proof checker，可以做 trusted evaluator；但也要区分 **竞赛/leaderboard 型解题**、**自然语言证明**、**形式化证明**、**研究级开放问题**，这几类评测泄漏风险和 evaluator 形态差别很大。

收录标准：这里尽量只列 **benchmark / evaluation protocol / leaderboard / verifier environment**。像 GSM8K、MATH、MATH-500 这类主要作为静态题库/数据集使用的条目，不单独列入本节；只有当它们被 PostTrainBench、MathArena、AIMO 等上层评测协议引用时，才作为目标子任务出现。

| Benchmark / 平台 | 提出时间 | 范式 / 类型 | 数学子方向 | 测什么 | 评测方式 / 指标 | 代码 / 站点 |
|---|---:|---|---|---|---|---|
| **AIME / AIMO Progress Prize** | 2024 / 2025 / 2026 | **竞赛型 / Leaderboard** | 奥数级答案型解题 | AIMO Kaggle competitions 用原创/竞赛级数学题推动 open-source math reasoning；AIMO3 110 题，覆盖 algebra、combinatorics、geometry、number theory | Kaggle hidden/public leaderboard；输出整数/短答案；notebook sandbox、禁网、固定 compute budget；Proof Pilot 开始试验 proof-based grading | AIMO Prize: https://aimoprize.com/；AIMO3: https://www.kaggle.com/c/ai-mathematical-olympiad-progress-prize-3/；Proof Pilot: https://www.kaggle.com/competitions/ai-mathematical-olympiad-proof-pilot |
| **OlympiadBench** | 2024 | **问答 / 多模态奥赛** | 中英双语数学 + 物理奥赛，含图像 | 8,476 math/physics problems；open-ended + theorem-proof；text-only + multimodal | open-ended 自动评分 pipeline；proof 题抽样人工评估；报告 math / physics / multimodal 分项 accuracy | Paper: https://arxiv.org/abs/2402.14008；Code/Data: https://github.com/OpenBMB/OlympiadBench |
| **Omni-MATH** | 2024 / ICLR 2025 | **问答 / 奥数级大规模 benchmark** | 纯数学奥赛 | 4,428 competition-level problems；33+ subdomains；10 difficulty levels | GPT-4o evaluation 或 Omni-Judge；也提供 rule-based evaluation data/code；按 domain/difficulty 报 accuracy | Paper: https://arxiv.org/abs/2410.07985；Code/Data: https://github.com/KbsdJames/Omni-MATH；ICLR: https://proceedings.iclr.cc/paper_files/paper/2025/hash/f9e1e8b56c7e363985ebeb0e9dd1a85c-Abstract-Conference.html |
| **OlymMATH** | 2025 | **问答 / 双语奥数级** | 中英双语 AIME/更高难度奥数题 | 200 curated problems；English/Chinese parallel；easy/hard 两档；覆盖 algebra、geometry、number theory、combinatorics | rule-based answer verification；pass@1 / consistency；另有 OlymMATH-eval 58 万+ model reasoning traces 用于分析 | Paper: https://arxiv.org/abs/2503.21380；Code: https://github.com/RUCAIBox/OlymMATH；HF: https://huggingface.co/datasets/RUC-AIBOX/OlymMATH |
| **AMO-Bench** | 2025 / 2026 ACL | **问答 / 原创高难奥数** | IMO-level 或更高难度高中数学竞赛 | 50 human-crafted original problems；专家交叉验证，降低泄漏；只要求 final answer 以便自动评分 | answer-only automatic grading；leaderboard；强调 token efficiency 与高难原创题 | Project: https://amo-bench.github.io/ |
| **MathArena / LiveAoPSBench** | 2025 / 2026 | **动态 Leaderboard / contamination-resistant** | 最新数学竞赛 / AoPS 在线题 | MathArena 持续评最新 AIME/HMMT/SMT/USAMO/IMO/Putnam/Project Euler/arXivMath 等；LiveAoPSBench 利用在线奥数题构造动态评测 | rule-based parser + judge verification；leaderboard with confidence intervals；按比赛/难度/时间切分，强调新题抗污染 | MathArena: https://matharena.ai/；Code: https://github.com/eth-sri/matharena；HF: https://huggingface.co/MathArena；LiveAoPSBench: https://livemathbench.github.io/leaderboard.html |
| **FrontierMath Tiers 1-4** | 2024 / 2025 | **研究级 / 专家数学推理** | 高等数学 / 研究级数学 | 350 original unpublished problems；Tier 1-3 从高级本科到博士探索级，Tier 4 为研究级；由数学家编写/评审 | Python-enabled iterative solving；答案通常可程序化验证；部分问题/solutions held-out；版本化 benchmark | Main: https://epoch.ai/frontiermath；About: https://epoch.ai/frontiermath/tiers-1-4/about；Paper: https://arxiv.org/abs/2411.04872 |
| **FrontierMath Open Problems** | 2026 | **开放问题 / 数学发现型** | 未解决研究数学问题 | pilot 14 个未解决 open problems；解决任一题可能构成真实数学进展 | proposed solutions 由程序化 verifier / 专家流程验证；solved problems 会移出 benchmark；verifier 访问受控 | https://epoch.ai/frontiermath/open-problems/about |
| **IMO-Bench / DeepMind superhuman math eval** | 2025 / 2026 | **竞赛型 / 鲁棒数学推理** | IMO / IMO shortlist 风格 | Google DeepMind 用于评 robust mathematical reasoning 的 IMO-level suites；AIMO3 社区也有改编版 | answer extraction / proof or integer-format scoring；用于 AIMO local validation 与高级数学推理系统评估 | Project: https://imobench.github.io/；Repo: https://github.com/google-deepmind/superhuman |
| **HARDMath** | 2024 | **问答 / 应用数学高难题** | 研究生级应用数学 / 渐近方法 | 1,466 difficult graduate-level applied mathematics problems inspired by Harvard asymptotic methods course | final answer / approximate reasoning evaluation；看 leading LLM 在 advanced applied math 上的 accuracy | OpenReview: https://openreview.net/forum?id=gt6prlTEGL |
| **TheoremQA / Lila** | 2022 / 2023 | **问答 / theorem application** | 定理驱动 QA / 综合数学推理 | TheoremQA：800 QA，350+ STEM theorems；Lila：23 diverse math reasoning tasks，统一成 Python-program solution 格式 | exact answer / WolframAlpha / program execution；更偏 theorem application 和多任务数学 reasoning | TheoremQA: https://github.com/wenhuchen/TheoremQA；Lila: https://github.com/allenai/lila；HF: https://huggingface.co/datasets/allenai/lila |
| **MathVista / MathVerse** | 2023 / 2024 | **多模态数学 / VLM benchmark** | 图表、几何图、视觉数学 | MathVista 6,141 visual-context math tasks；MathVerse 2,612 visual math problems × 多种信息版本，检验是否真正读图 | answer extraction + accuracy；MathVerse 还做不同 text/vision variants 和 CoT step scoring | MathVista: https://github.com/lupantech/MathVista；MathVerse: https://github.com/ZrrSkywalker/MathVerse |
| **MathConstruct** | 2025 | **构造性证明 / verifier 型** | constructive proof / 构造数学对象 | 126 challenging constructive-proof problems；要求构造满足性质的数学对象 | 自动 verifier 检查构造是否正确；还可生成 problem variations 测鲁棒性 | Project: https://www.sri.inf.ethz.ch/publications/balunovic2025mathconstruct；Code: https://github.com/eth-sri/mathconstruct；Paper: https://arxiv.org/abs/2502.10197 |
| **IneqMath** | 2025 | **自然语言证明 / 过程可靠性** | Olympiad-level inequality proofs | 不等式证明题，强调 final answer 对但 proof 可能错的问题 | final-answer accuracy + overall proof soundness；LLM judge / expert-style step checking；评估推理是否可靠 | Project: https://ineqmath.github.io/；Paper: https://arxiv.org/abs/2506.07927 |
| **miniF2F** | 2021 | **形式化证明 / proof checker** | 奥数级 formal theorem proving | 244 test + 244 valid；Lean / Isabelle / Metamath / HOL Light 版本；来自 AMC/AIME/IMO/课程题 | 由 proof assistant compiler/checker 验证；指标为 solved rate / pass@k；当前已逐渐饱和但仍是标准基准 | Paper: https://arxiv.org/abs/2109.00110；Code/Data: https://github.com/facebookresearch/miniF2F |
| **ProofNet** | 2023 | **autoformalization + formal proving** | 本科数学 Lean 形式化 | 371 examples；自然语言 theorem statement + proof + Lean formal statement；real/complex analysis、linear algebra、algebra、topology 等 | typecheck rate、semantic correctness、formal proof success；Lean 3 原版，Lean 4 ports 需另查 | Paper: https://arxiv.org/abs/2302.12433；Code/Data: https://github.com/zhangir-azerbayev/ProofNet |
| **PutnamBench** | 2024 | **形式化证明 / 多语言 theorem proving** | Putnam 本科竞赛数学 | 1962-2025 Putnam problems；1,724 manually-crafted formalizations：Lean 4 / Isabelle / Coq；也含 informal statements | proof assistant checker；solved count / pass@k；leaderboard 接收带论文的评测结果 | Project: https://trishullab.github.io/PutnamBench/；Code/Data: https://github.com/trishullab/PutnamBench；Paper: https://arxiv.org/abs/2407.11214 |
| **LeanDojo Benchmark / LeanDojo-v2** | 2023 / 2025 | **工具环境 / theorem-proving gym** | Lean theorem proving / premise retrieval | 从 mathlib/mathlib4 抽取 proof states、tactics、premises；LeanDojo Benchmark 98,734 theorems，LeanDojo Benchmark 4 122,517 theorems | prover 与 Lean 交互，生成 tactic/proof；compiler check；random / novel-premises split；适合 agent/RL theorem proving | Project: https://leandojo.org/leandojo.html；Code: https://github.com/lean-dojo/LeanDojo |
| **FormalMATH** | 2025 | **形式化数学推理 / Lean4** | 大规模 formal math | 5,560 formally verified Lean4 statements；多领域、多难度；human-in-the-loop pipeline | Lean4 proof generation + compiler verification；Pass@K；FormalMATH-All / FormalMATH-Lite | Paper: https://arxiv.org/abs/2505.02735；Code: https://github.com/Sphere-AI-Lab/FormalMATH-Bench |
| **Lean Eval / Comparator benchmark** | 2026 | **形式化证明 / trusted comparator** | Lean formal math eval infrastructure | benchmark authors 写 trusted problem statements，tooling 生成 comparator workspaces | submission 只有被 comparator 接受才算 solved；适合 hidden evaluator 防泄漏 | https://github.com/leanprover/lean-eval |

#### 数学 benchmark 的评测要点

- **竞赛 / leaderboard 型答案数学**：AIMO、MathArena、LiveAoPSBench、Omni-MATH、OlymMATH、AMO、FrontierMath Core 多数可自动核答案，适合刷分；但静态题库容易污染或饱和，所以优先动态/原创/带协议的 bench。
- **Proof 型数学**：USAMO/IMO proof、IneqMath、AIMO Proof Pilot 等需要检查证明过程；如果只看 final answer，会高估模型能力。
- **形式化证明**：miniF2F、PutnamBench、LeanDojo、FormalMATH、Lean Eval 最干净，因为 proof checker 是 deterministic evaluator；非常适合 Famou 的 trusted evaluator 设计。
- **数学发现型**：FrontierMath Open Problems 是最接近“真正自主科研”的数学 benchmark；但成本高、题量少、verifier 访问受控，而且解出题会改变 benchmark 本身。
- **动态抗污染**：MathArena / LiveAoPSBench / AIMO 原创题对抗 data contamination 更好，适合长期评估 post-training / inference-time search 的真实进步。
- **对 Famou e2e 的接入建议**：
  1. 第一优先：miniF2F / PutnamBench / Lean Eval / FormalMATH，因 evaluator 清晰且不需要 LLM judge；
  2. 第二优先：MathArena / AIMO / Omni-MATH / OlymMATH，适合 answer-only 自动评分；
  3. 第三优先：FrontierMath / MathConstruct / IneqMath，适合评长期数学研究和 proof reliability。

### 7.14 bench 的“性质”：ML 代理模型、生成设计、机理/数学建模型

**大部分所谓科学 benchmark，本质上还是在测一个 ML 方法**，比如监督预测、拟合 surrogate、做生成式设计、或做代码/论文复现。  
如果你更关心的是“**机理还是 ML 模型**”，那比“预测/发现”更有用的划分是：

1. **ML 代理模型 / surrogate**：输出是数值/标签，但不要求可解释机理；
2. **生成设计**：从分布里生成结构/配方，核心还是统计学习；
3. **机理 / 数学建模**：要恢复公式、定律、PDE/ODE，或至少显式体现物理规律；
4. **混合型**：表面上是 ML，但评测强依赖物理一致性、守恒、稳定性、可解释性。

更直接地说，可以先按下面三类看：

| 类别 | 你可以怎么理解 | 典型 bench |
|---|---|---|
| **纯 ML** | 主要是在做预测、分类、回归、排序、生成 | Matbench、OpenPoly、MOFX-DB、Matbench Discovery、MatterGen benchmark |
| **混合型** | ML 里带明显物理约束、仿真流程、工作流或守恒要求 | OC20/OC22、JARVIS-Leaderboard、PDEBench、AirfRANS、CFDBench、FlowBench、The Well |
| **纯机理 / 数学建模** | 目标是恢复公式、发现定律、识别控制方程 | AI Feynman、SRBench、SRBench++、ERBench、NewtonBench |

真正偏“纯机理”或“数学建模”的 bench **有，但少很多**，而且常集中在：

1. **符号回归 / 方程发现**：从数据恢复解析公式；
2. **科学定律发现**：交互式实验里发现隐藏物理规律；
3. **PDE / ODE 机理建模**：求解或识别控制方程；
4. **可解释建模**：要求输出可读公式或低复杂度模型，而不只是高分数黑盒。

| 类型 | 代表 bench | 提出时间 | 核心性质 | 为什么更“机理” |
|---|---|---:|---|---|
| **ML 代理模型** | Matbench、OC20/OC22、AirfRANS、Biomni-Eval1 | 2019-2024 | 预测性质/状态/标签 | 主要是 supervised ML / surrogate，通常不要求显式机理 |
| **生成设计** | MatterGen benchmark、MGB、LeMat-GenBench | 2025-2026 | 生成稳定/新颖材料结构 | 偏设计空间搜索，不直接学机理 |
| **方程发现型** | **AI Feynman**、**SRBench**、**SRBench++**、**ERBench** | **2020 / 2021 / 2024 / 2026** | 从数据恢复解析式 | 直接要求恢复公式，最接近“数学建模” |
| **定律发现型** | **NewtonBench** | **2025/2026** | 交互式发现隐藏物理规律 | 不是静态拟合，而是主动实验探索 |
| **PDE/物理建模型** | **PDEBench**、CFDBench、FlowBench、The Well | 2022-2024 | 物理场/流体/多物理仿真 | 明确面对控制方程和时空演化 |

#### 纯机理 / 数学建模 benchmark 重点例子

- **AI Feynman (2020)**：从 100 个 Feynman 物理方程中恢复解析式，带有维度分析、对称性、可分离性等物理先验。  
- **SRBench (2021)**：符号回归 living benchmark，252 个回归问题，包含真实数据和合成公式恢复任务。  
- **SRBench++ (2024)**：在 SRBench 上增加特征选择、噪声局部极值、外推、专家可解释性等轨道。  
- **ERBench (2026)**：专门面向 equation discovery / symbolic regression 的 benchmark 与 testsuite。  
- **NewtonBench (2026)**：面向 LLM agent 的科学定律发现，强调交互式实验而不是静态曲线拟合。  
- **PDEBench (2022)**：PDE time-dependent simulation benchmark，适合评纯物理建模/神经算子。  

#### 结论

- 如果你要的是 **“纯机理/数学建模”**，最对口的是：
  - **symbolic regression / equation discovery**；
  - **scientific law discovery**；
  - **PDE/ODE 建模与求解**。
- 如果你要的是 **“科学 Agent”**，大多数 benchmark 还是偏：
  - 预测；
  - 生成；
  - 文献/代码/实验流程自动化。
- 所以可以把科研 Agent benchmark 分成两条主线：
  - **应用型科学 ML benchmark**；
  - **机理型科学发现 benchmark**。

---

## 8. 评测协议的共性

### 8.1 “有标准答案”的任务

常用指标：

- accuracy / exact match；
- F1 / AUROC / AUPRC / MAE / Pearson / Spearman；
- leaderboard percentile；
- pass@1 / success rate；
- task completion rate；
- runtime / cost。

适合：

- 数据分析；
- paper-to-code；
- Kaggle 式 ML；
- 生物医学分类/回归；
- 仪器对齐/物理参数恢复。

### 8.2 开放式科研任务

常用评估：

- 专家 rubric；
- LLM judge；
- blind review；
- Elo tournament；
- groundedness / faithfulness；
- novelty / usefulness / plausibility；
- claim-level citation faithfulness。

问题：

- LLM judge 容易偏；
- novelty 难自动打分；
- rubric 污染和 benchmark 泄漏风险高。

### 8.3 真实验闭环任务

最有说服力的评测：

- 机器人/仪器是否真实执行；
- 实验产物是否满足目标；
- 失败后能否自修复；
- 和人工专家/传统 pipeline 对比；
- 多次独立运行的稳定性；
- 是否能发现新材料、新靶点、新机制。

---

## 9. 当前系统的主要失败模式

1. **文献幻觉**：引用不存在或引用不支撑论点。
2. **结果幻觉**：未运行实验却写 metrics。
3. **代码-设计漂移**：实验代码没有忠实实现设计。
4. **数据泄漏**：尤其 ML / biomedical ML benchmark。
5. **LLM judge 偏差**：自动评审高估结果。
6. **不可复现**：缺环境、缺数据、缺随机种子、缺运行日志。
7. **短链路过拟合**：QA 很强，但长链路 tool-use 崩。
8. **开放式 novelty 难评**：容易把小修小补当新发现。
9. **真实实验安全性**：机器人/化学/生物实验需要权限、安全和审计。

---

## 10. 对 famou-scientist 的启发

### 10.1 可以对标的能力链

建议把 famou 的能力链对齐到：

1. 文献检索与 citation faithfulness；
2. 假设生成与 novelty gate；
3. 实验设计与实现契约；
4. 代码保真审查；
5. 真实执行与异步实验；
6. 结果注册表；
7. 论文写作；
8. 论文数字核验；
9. trace-based reproducibility；
10. benchmark harness。

### 10.2 可以借鉴的 benchmark 设计

最适合 famou 的 benchmark 组合：

| 目标 | 推荐 benchmark 思路 |
|---|---|
| 文献检索 | AutoResearchBench / ResearcherBench 风格 |
| 论文复现 | PaperBench / MLReplicate 风格 |
| ML 科研 | MLE-bench / AIRS-Bench / Scientist-Bench |
| 生物医学 | Biomni-Eval1 / BioML-bench |
| 脑科学 | BrainPilotBench / NeuroBench |
| trace 评测 | 自建 ClawBench：按工具轨迹、文件产物、实验结果打分 |

### 10.3 famou 可以做的差异化

- **硬护栏**：实验质量门、引用核验门、数字核验门、图版核验门；
- **trace-first**：把每一步 tool call、文件、结果注册表纳入评测；
- **真实执行优先**：文献、实验、图、LaTeX 都实际执行；
- **多领域可插拔**：用 skill/tool 方式覆盖 ML、化学、生物、脑科学；
- **benchmark-friendly**：每个 run 输出标准化 `results.json`、`trace.jsonl`、`paper.md`、`review.md`。

---

## 11. 待继续核验清单

以下系统用户提到或社区出现频繁，但本文还需要补原始论文/官方 benchmark 细节：

| 系统 | 当前状态 | 需要补什么 |
|---|---|---|
| Hyra / 腾讯混元 Research Agent | 已知存在官方宣传/发布材料，但未核到完整论文与 benchmark 协议 | 官方论文/PDF、代码、benchmark 名称、评分细节 |
| ElementClaw | 有第三方索引和公开口径，疑似材料/超导发现 Agent | 原始论文、实验验证细节、SuperCon3D/筛选流程 |
| BrainAgent 细分版本 | 已核到 arXiv 2606.25400，但名称可能和其它 BrainAgent 项目重名 | 代码仓库、完整 benchmark 定义 |
| BioClaw / MedClaw 类 | 有生态/项目页 | 是否有硬 benchmark、真实执行能力 |
| Kosmos / disease-specific biomedical scientist | 论文/系统名称分散 | 精确系统边界、评测协议 |

---

## 12. 主要来源链接

### 通用 / 自动科研

- Google AI co-scientist: <https://www.nature.com/articles/s41586-026-10644-y>
- Google AI co-scientist blog: <https://blog.google/feed/google-research-ai-co-scientist/>
- OpenAI Deep Research: <https://help.openai.com/en/articles/10500283-deep-research>
- PaperBench: <https://openai.com/index/paperbench/>
- The AI Scientist: <https://arxiv.org/abs/2408.06292>
- PiEvo: <https://arxiv.org/abs/2602.06448>
- R&D-Agent: <https://github.com/microsoft/rd-agent>
- AlphaEvolve: <https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/>

### 生物医学

- Biomni paper: <https://pmc.ncbi.nlm.nih.gov/articles/PMC12157518/>
- Biomni GitHub: <https://github.com/snap-stanford/Biomni>
- Agentomics paper: <https://www.biorxiv.org/content/10.64898/2026.01.27.702049v1>
- Agentomics Oxford/Bioinformatics: <https://academic.oup.com/bioinformatics/article/42/Supplement_1/btag250/8726289>
- Agentomics site: <https://agentomicsml.com/>
- STELLA arXiv mirror/summary: <https://papers.cool/arxiv/2507.02004>
- STELLA PyPI / benchmark notes: <https://pypi.org/project/stella-agent/>
- Biological AI agents survey: <https://pmc.ncbi.nlm.nih.gov/articles/PMC12936789/>

### 脑科学

- BrainPilot: <https://www.alphaxiv.org/abs/2607.15079>
- BrainPilotBench public data: <https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public>
- BrainAgent: <https://www.alphaxiv.org/overview/2606.25400v1>
- BrainAgent arXiv mirror: <https://studio-pilates.biz/?_=%2Fabs%2F2606.25400%23P%2Fto5ze3YR%2FcgWH8GBGZpDA%3D>
- NeuroClaw: <https://github.com/CUHK-AIM-Group/NeuroClaw>

### 化学 / 材料 / 实验室

- Coscientist: <https://www.nature.com/articles/s41586-023-06792-0>
- ChemCrow: <https://arxiv.org/abs/2304.05376>
- ORGANA: <https://ac-rad.github.io/organa/>
- El Agente Q: <https://www.sciencedirect.com/science/article/pii/S2590238525003066>
- MOOSE-Chem ICLR 2025: <https://proceedings.iclr.cc/paper_files/paper/2025/hash/51fd9a7d1706023cb9f8210cc6ac357c-Abstract-Conference.html>
- ElementClaw third-party index: <https://jglobal.jst.go.jp/detail?JGLOBAL_ID=202602208115162970>

### 机理 / 数学建模 / 方程发现

- AI Feynman: <https://www.science.org/doi/10.1126/sciadv.aay2631>
- SRBench: <https://openreview.net/forum?id=ESrCwLnYdHd>
- SRBench++: <https://openreview.net/forum?id=O0KkGajx6T>
- ERBench: <https://arxiv.org/abs/2606.18707>
- NewtonBench: <https://arxiv.org/abs/2604.08741>
- PDEBench: <https://arxiv.org/abs/2210.07182>

### 12.1 提出时间速查（系统 / 论文）

| 系统 | 提出时间 | 备注 |
|---|---:|---|
| Deep Research | 2025 | OpenAI 产品能力公开 |
| AI co-scientist | 2025 | Nature 论文/Google blog |
| Robin | 2025 | FutureHouse 生物医学 agent |
| The AI Scientist | 2024 | 自动 ML 科研 |
| The AI Scientist-v2 | 2025 | 更完整论文生成/投稿 |
| CycleResearcher | 2025 | 自动研究 + 自动 review |
| Agent Laboratory | 2025 | 研究助手/报告生成 |
| AI-Researcher | 2025 | 自动科研系统 |
| Biomni | 2025 | 通用生物医学 agent |
| STELLA | 2025 | 自演化 biomedical agent |
| Agentomics | 2026 | 生物医学 ML 自动实验 |
| Coscientist | 2023 | 化学实验 Agent |
| ChemCrow | 2023 | 化学工具 Agent |
| MOOSE-Chem | 2025 | 化学假设发现 |
| BrainPilot | 2026 | 脑科学 agent |
| BrainAgent | 2026 | 脑信号理解/BCI agent |
| NeuroClaw | 2026 | 神经影像 workflow agent |
| MetaOpenFOAM | 2024 | CFD / OpenFOAM Agent |
| FoamPilot | 2024 | CFD / FireFOAM Agent |
| OpenFOAMGPT | 2025 | CFD / OpenFOAM Agent |
| CFDagent | 2025 | 端到端 CFD agent |
| ChatCFD | 2026 | 端到端 CFD agent |
| IteraSim RAG | 2026 | RAG 驱动 OpenFOAM agent |
| Hyra / 腾讯混元 Research Agent | 2026 | 官方页 + results repo；评测细节仍需以后续论文/技术报告为准；详见 [Hyra Benchmark / Result 汇总](./HYRA_BENCHMARKS_CN.md) |

## 13. 公开代码库汇总

> 只列这次能核到的公开代码库；没找到稳定公开仓库的，我没硬编。

### 13.1 通用 / 自动科研

| 系统 | 代码库 |
|---|---|
| The AI Scientist | https://github.com/SakanaAI/AI-Scientist |
| The AI Scientist-v2 | https://github.com/SakanaAI/AI-Scientist-v2 |
| Open Coscientist | https://github.com/jataware/open-coscientist |
| FutureHouse Robin | https://github.com/Future-House/robin |
| FutureHouse PaperQA2 | https://github.com/Future-House/paper-qa |
| OpenAGS / OpenAGS Desktop | https://github.com/openags/auto-research-ui |
| R&D-Agent | https://github.com/microsoft/rd-agent |
| OpenAGS 论文/资源索引 | https://github.com/openags/Awesome-AI-Scientist-Papers |
| Agent Laboratory | https://github.com/SamuelSchmidgall/AgentLaboratory |
| CycleResearcher | https://github.com/zhu-minjun/Researcher |
| AI-Researcher / Scientist-Bench | https://github.com/HKUDS/AI-Researcher |
| PiEvo | https://github.com/amair-lab/PiEvo |
| NatureBench | https://github.com/FrontisAI/NatureBench |
| MLAgentBench | https://github.com/snap-stanford/MLAgentBench |
| AIRS-Bench | https://github.com/facebookresearch/airs-bench |
| MLE-Dojo | NeurIPS page: https://proceedings.neurips.cc/paper_files/paper/2025/hash/0603c69125ad4b964bc9c4832f7b9f8f-Abstract-Datasets_and_Benchmarks_Track.html |
| MLR-Bench | https://chchenhui.github.io/mlrbench/ |
| MLRC-Bench | https://huggingface.co/spaces/launch/MLRC_Bench |
| MLS-Bench | https://github.com/Imbernoulli/MLS-Bench |
| ResearcherBench | https://researcherbench.github.io/ |
| Hyra results | https://github.com/Tencent-Hunyuan/hyra-results |
| KernelBench | https://github.com/ScalingIntelligence/KernelBench |
| TritonBench | https://github.com/thunlp/TritonBench |
| TritonGym | https://tritongym.picasso-lab.com/ |
| PostTrainBench | https://github.com/aisa-group/PostTrainBench |
| RewardBench | https://github.com/allenai/reward-bench |
| PPE | https://github.com/lmarena/PPE |
| RM-Bench | https://github.com/THU-KEG/RM-Bench |
| AlpacaEval | https://github.com/tatsu-lab/alpaca_eval |
| MT-Bench / FastChat judge | https://github.com/lm-sys/FastChat/tree/main/fastchat/llm_judge |
| Arena-Hard-Auto | https://github.com/lmarena/arena-hard-auto |
| WildBench | https://github.com/allenai/WildBench |
| BFCL | https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard |
| SWE-bench | https://github.com/SWE-bench/SWE-bench |
| NASLib / NAS benchmarks | https://automl.github.io/NASLib/ |
| HPOBench | https://github.com/automl/HPOBench |
| YAHPO Gym | https://slds-lmu.github.io/yahpo_gym/ |
| miniF2F | https://github.com/facebookresearch/miniF2F |
| PutnamBench | https://github.com/trishullab/PutnamBench |
| LeanDojo | https://github.com/lean-dojo/LeanDojo |
| ProofNet | https://github.com/zhangir-azerbayev/ProofNet |
| FormalMATH-Bench | https://github.com/Sphere-AI-Lab/FormalMATH-Bench |
| Lean Eval | https://github.com/leanprover/lean-eval |
| Omni-MATH | https://github.com/KbsdJames/Omni-MATH |
| OlympiadBench | https://github.com/OpenBMB/OlympiadBench |
| OlymMATH | https://github.com/RUCAIBox/OlymMATH |
| MathArena | https://github.com/eth-sri/matharena |
| MathConstruct | https://github.com/eth-sri/mathconstruct |
| MathVista | https://github.com/lupantech/MathVista |
| MathVerse | https://github.com/ZrrSkywalker/MathVerse |

### 13.1b Benchmark 数据集 / 评测资源

| Benchmark | 数据 / 评测资源 |
|---|---|
| NatureBench | https://huggingface.co/datasets/FrontisAI/NatureBench |
| NatureBench trajectories | https://huggingface.co/datasets/FrontisAI/NatureBench-traces |
| KernelBench | https://huggingface.co/datasets/ScalingIntelligence/KernelBench |
| PostTrainBench | https://posttrainbench.com/ |
| RewardBench dataset | https://huggingface.co/datasets/allenai/reward-bench |
| WildBench leaderboard/data | https://huggingface.co/spaces/allenai/WildBench |
| Chatbot Arena | https://lmarena.ai/ |
| BFCL leaderboard | https://gorilla.cs.berkeley.edu/leaderboard |
| HealthBench | https://openai.com/index/healthbench/ |
| SWE-bench Verified | https://www.swebench.com/ |
| OlymMATH | https://huggingface.co/datasets/RUC-AIBOX/OlymMATH |
| MathArena | https://matharena.ai/；https://huggingface.co/MathArena |
| LiveAoPSBench | https://livemathbench.github.io/leaderboard.html |
| FrontierMath | https://epoch.ai/frontiermath |
| FrontierMath Open Problems | https://epoch.ai/frontiermath/open-problems/about |
| AMO-Bench | https://amo-bench.github.io/ |
| MLS-Bench | https://mls-bench.com/ |
| MLRC-Bench | https://huggingface.co/spaces/launch/MLRC_Bench |
| BrainPilotBench-v0 | https://huggingface.co/datasets/BrainPilot-Bench/Tasks-Data-Public |
| SciVisAgentBench tasks | https://huggingface.co/datasets/SciVisAgentBench/SciVisAgentBench-tasks |
| Matter to Mechanism | https://huggingface.co/datasets/Boson20/matter-to-mechanism |
| Terminal-Bench Science | https://github.com/harbor-framework/terminal-bench-science |
| Agents' Last Exam | https://agents-last-exam.org/docs/ale/index.html |

### 13.2 生物医学 / 生命科学

| 系统 | 代码库 |
|---|---|
| Biomni | https://github.com/snap-stanford/Biomni |
| BioDiscoveryAgent | https://github.com/snap-stanford/BioDiscoveryAgent |
| OpenBioMed | https://github.com/PharMolix/OpenBioMed |
| BioAgents | https://github.com/bio-xyz/BioAgents |
| NeuroClaw | https://github.com/CUHK-AIM-Group/NeuroClaw |
| BioAgent Bench | https://github.com/bioagent-bench/bioagent-bench |
| STELLA | https://github.com/zaixizhang/STELLA |

### 13.3 化学 / 材料 / 实验室自动化

| 系统 | 代码库 |
|---|---|
| Coscientist | https://github.com/gomesgroup/coscientist |
| MOOSE-Chem | https://github.com/ZonglinY/MOOSE-Chem |
| MOOSE | https://github.com/ZonglinY/MOOSE |
| MatterGen | https://github.com/microsoft/mattergen |
| LeMat-GenBench | https://github.com/LeMaterial/lemat-genbench |
| matbench-genmetrics | https://github.com/sparks-baird/matbench-genmetrics |
| Fair-Chem / OMat24 models | https://github.com/facebookresearch/fairchem |
| ORGANA | 暂未核到稳定公开 GitHub 仓库 |
| ElementsClaw | 暂未核到稳定公开 GitHub 仓库；project: https://elementsclaw.org/ |
| ChatMOF | 暂未核到稳定公开 GitHub 仓库 |

### 13.3b 科学工具 / 可视化 benchmark 代码

| 系统 / Benchmark | 代码库 |
|---|---|
| SciAgentGym | https://github.com/CMarsRover/SciAgentGYM |
| SciVisAgentBench | https://github.com/KuangshiAi/SciVisAgentBench |
| HeurekaBench | https://github.com/mlbio-epfl/HeurekaBench |
| FIRE-Bench | project page 标注 code coming soon：https://firebench.github.io/ |

### 13.4 其他参考实现 / 相关平台

| 系统 | 代码库 |
|---|---|
| Awesome-AI-Scientist-Papers | https://github.com/openags/Awesome-AI-Scientist-Papers |
| Awesome-Agent-Scientists | https://github.com/AgenticScience/Awesome-Agent-Scientists |
| Awesome LLM Scientific Discovery | https://github.com/HKUST-KnowComp/Awesome-LLM-Scientific-Discovery |
| Future-House Aviary | https://github.com/Future-House/aviary |
| Future-House LDP | https://github.com/Future-House/ldp |

### 暂未核到稳定公开代码仓库

- BrainPilot
- BrainAgent（脑科学方向的那个具体系统）
- 其它仅有官网/论文/二手索引、但未见明确 GitHub 仓库的条目

---

## 14. 简短结论

当前最值得重点追踪的端到端科研 Agent：

1. **AI co-scientist / Robin**：科研假设与生物实验闭环。
2. **Coscientist / AutoLabs / ORGANA**：化学真实实验闭环。
3. **ElementClaw**：材料发现与实验验证，需补原始论文。
4. **BrainPilot / NeuroClaw / BrainAgent**：脑科学垂直 Agent 和 benchmark 体系。
5. **Biomni / STELLA / Agentomics**：生物医学 Agent 目前最强的一批。
6. **AI Scientist v2 / CycleResearcher / Agent Laboratory / MLReplicate**：ML 自动科研与论文复现主线。
7. **AlphaEvolve / PiEvo**：偏算法/原理发现，但 scientific discovery 含金量高。
8. **Hyra**：用户已知的重要系统；目前应作为单独专题继续核验。
