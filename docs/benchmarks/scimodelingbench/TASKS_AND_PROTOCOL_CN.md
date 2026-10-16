# SciModelingBench 任务与评测协议

本文件说明当前 Famou 适配器使用的 13 个 SciModelingBench 任务：任务背景、Agent 可见输入、提交结果格式、候选数量和主评测指标。

## Benchmark 总览

SciModelingBench 是一个面向科学发现 Agent 的多领域评测基准。它不要求 Agent 只回答一个自然语言问题，也不直接评价 Agent 写出的算法代码；它要求 Agent 阅读公开的科学数据，建立自己的分析、预测、检索或搜索流程，最后**提交一组符合领域定义、可以被可信评测器重新计算的科学候选**，并由可信评测器使用隐藏目标重新打分。

这里的“可解释”只表示候选本身是一个有明确领域语义的对象，例如 DNA 序列、蛋白序列、材料组成、控制策略或药物处理条件；它不表示 benchmark 会检查 Agent 的推理过程、因果解释或科学假设。**候选池排序任务确实主要是从给定候选中筛选和重新排列，黑盒优化任务则是在合法设计空间中生成候选**；两者的科学价值都由最终隐藏目标分数衡量。

当前适配器覆盖 13 个任务，涉及：

- DNA/转录因子结合序列设计：`tfbind8`、`tfbind10_pho4`
- 神经网络架构搜索：`cell_dag_nas`
- 超导材料发现：`superconductor`
- 强化学习控制策略筛选：`hopper_controller`
- RNA 翻译调控和蛋白工程：`utr_mrl_egfp_unmodified`、`gfp`
- 药物毒理临床病理预测：6 个 `drugmatrix_*` 任务

这些任务分成两种核心问题：

1. **黑盒优化**：Agent 根据历史观测自行设计新的序列、架构或其他候选，再提交指定数量的候选。`tfbind8` 的最终答案就是 32 条新的 DNA sequence，而不是一段“设计 DNA 的算法”代码。
2. **候选池排序**：benchmark 已经给出一个不含目标标签的有限候选池，Agent 需要预测候选质量，从中选择并排序；评测器只评分排序结果的前 `N` 个候选。

因此，一个完整的 Agent run 是：

```text
读取公开观测/候选池
    -> 建立预测、检索或搜索策略
    -> 生成新候选或筛选候选池
    -> 写出 submission.json
    -> trusted evaluator 使用隐藏目标评分
```

Benchmark 的核心难点在于：公开数据可以用于建模，但最终候选的真实目标值隐藏；Agent 在运行过程中通常只能得到提交批次的聚合反馈，不能逐候选读取 hidden score。不同任务分别使用 `best_k_mean`、`normalized_enrichment` 和 `global_ndcg`，它们衡量的是高质量候选发现、批次整体质量或候选排序质量，而不是统一的单一准确率。

## 统一运行协议

每个任务的公开数据目录通过 `BENCHMARK_TASK_DIR` 或 `DATA_DIR` 暴露给 Agent。Agent 需要生成 `run.py`，读取这些目录中的公开数据，并写出：

```text
OUTPUT_DIR/submission.json
```

`submission.json` 必须是 JSON 数组。官方评测器在可信进程中执行，公开目录不会包含隐藏标签、目标函数输出或评测器缓存。每次有效提交只返回聚合分数，不返回每个候选的隐藏真实分数。

指标默认都是 `higher_is_better`。

## 两种任务形态

### 黑盒优化

**只适用于 `tfbind8`、`tfbind10_pho4` 和 `cell_dag_nas`。** 这类任务没有一个要求 Agent 从中挑选答案的 `data/candidates.jsonl`。**Agent 根据公开历史观测，在任务定义的可评分空间中自行生成或搜索候选**。必须提交指定数量的互不重复且合法的候选。“黑盒优化”描述的是 Agent 对目标函数的访问方式，不代表可以提交任意表外设计，也不保证候选具有科学新颖性。例如 CellDAG-NAS 只接受冻结 NASBench-101 表中的架构，允许提出公开观测中未出现的架构，但表外架构无效。评测的是最终提交的候选质量，不是 Agent 编写的搜索算法或预测模型代码本身；`run.py` 只是产生最终候选的执行方式。

### 候选池排序

**只适用于 Superconductor、Hopper、UTR、GFP 和 6 个 DrugMatrix 任务。** 公开任务目录提供 `data/candidates.jsonl`，其中列出了本次允许排序的全部候选，但没有给出这些候选的目标标签或真实分数。**Agent 不能任意发明池外候选，而应从这个有限集合中选择候选，并按照预测质量从高到低写入提交结果**。至少提交指定的前缀数量 `N`；评测器只评分前 `N` 个，后缀忽略。

### 公开观测与公开候选池的区别

| 数据                                   | 含义                                                                       | Agent 如何使用                                             |
| -------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `data/observations.jsonl` 等公开观测 | 历史样本及其公开实验/性能信息，相当于训练和建模依据                        | 学习序列、材料、架构或处理条件与目标性质之间的关系         |
| `data/candidates.jsonl` 公开候选池   | 一组有限的待排序对象；对象本身和描述特征公开，但本次评测使用的目标标签隐藏 | 预测每个候选的质量，从池中选择并排序；只用于候选池排序任务 |

因此两句话并不描述同一个任务：黑盒优化是“自己生成合法答案”，候选池排序是“从给定答案集合中挑选和排序”。

## Agent 实际要做什么

Agent 的工作通常包括：读取历史观测或公开候选、建立一个预测/检索/搜索策略、生成或筛选候选、按照任务要求写出 `submission.json`。但 benchmark 最终验收的是这个文件中的设计或排序结果：

- `tfbind8` 不是让 Agent 提交一个“设计算法”，而是让 Agent 利用历史 TF-DNA 结合数据设计并直接提交 32 条新的 8-mer DNA 序列；算法只是一种产生序列的手段。
- `tfbind10_pho4` 和 `cell_dag_nas` 同理，最终分别验收 128 条 DNA 序列和 32 个神经网络架构。
- Superconductor、Hopper、UTR、GFP 和 DrugMatrix 不要求 Agent 发明候选，而是从公开候选池中筛选并排序，提交排好序的候选列表。
- 评测器会在可信环境中使用隐藏目标重新评估提交结果；Agent 不能读取逐候选隐藏分数，也不能把算法代码本身作为 benchmark 输出。

## 评分指标

### `best_k_mean`

对提交结果中的候选用隐藏目标重新评估，取真实分数最高的 `K` 个候选的平均值。当前 `tfbind8` 和 `cell_dag_nas` 的 `K=5`。

### `normalized_enrichment`

计算提交批次的平均质量，并相对于参考分布和参考分布中最优的同规模候选批次做归一化。它不是只取一个最高分；大量低质量候选会拉低结果。当前 `tfbind10_pho4`、UTR 和 GFP 使用该主指标。

### `global_ndcg`

评价前 `N` 个候选的选择质量和排序质量。高质量候选排得越靠前，NDCG 越高。当前 Superconductor、Hopper 和全部 DrugMatrix 指标任务使用该主指标。

当前 evaluator 使用的是基于归一化效用值的 `global_ndcg`。设提交结果前 `N` 个候选的真实分数为 `s_1, ..., s_N`，目标方向转换后的效用为 `u_i`，参考候选池中所有候选的效用最小值和最大值分别为 `u_min`、`u_max`，则：

```text
g_i = (u_i - u_min) / (u_max - u_min)

DCG@N = Σ(i=1..N) g_i / log2(i + 1)

IDCG_global@N = Σ(i=1..N) g_ref_(i) / log2(i + 1)
```

其中 `g_ref_(i)` 是参考候选池中按真实效用从高到低排序后的前 `N` 个归一化效用。最终：

```text
global_ndcg@N = DCG@N / IDCG_global@N
```

这意味着：

- `DCG@N` 使用 Agent 提交列表的顺序；第 1 位的折扣因子最大，第 `N` 位的折扣因子更小；
- `IDCG_global@N` 使用整个参考候选池中最优的前 `N` 个候选，代表全局理想上限，而不是把 Agent 自己提交的候选重新排序后作为分母；
- 如果 Agent 选中了高质量候选但排序靠后，分数会下降；如果高质量候选排在前面，分数会上升；
- 当前各任务的 `N` 分别是 Superconductor/Hopper 的 32，以及每个 DrugMatrix endpoint 的 16。

代码实现还会报告 `reranking_ndcg`，它用于衡量 Agent 选中的候选内部排序质量，但当前 benchmark 主指标是 `global_ndcg`。

## 任务总表

| Task                        | 任务描述 / 科学意义                                                            | Agent 要做什么                                                                                         | 领域 / 目标                                      | 形态       | Agent 可见输入                                                                                                                          | 输出候选字段                                                                                                                            |               数量要求 | 主指标                      |
| --------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------ | ---------- | --------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------: | --------------------------- |
| `tfbind8`                 | 学习 TF-DNA 结合规律并设计高亲和力 8-mer；衡量序列设计对转录调控机制的建模能力 | 读取历史序列和结合数据，建立预测/搜索策略，最终直接提交 32 条新的 8-mer DNA sequence；不评算法代码本身 | DNA binding / TF sequence design；8-mer 序列     | 黑盒优化   | `observations.jsonl`，32,768 条；序列和公开 normalized E-score                                                                        | `sequence`：长度 8，字符集 `A/C/G/T`                                                                                                |             exactly 32 | `best_k_mean`，top 5 均值 |
| `tfbind10_pho4`           | 发现 Pho4 转录因子偏好的 DNA motif；研究结合位点设计和实验富集信号预测         | 从历史 Pho4 结合数据中学习 motif 或富集规律，生成并提交 128 条新的 DNA sequence                        | Pho4 transcription-factor binding；10 个可变碱基 | 黑盒优化   | `observations.jsonl`，2,087,323 条；sequence、replicate/read-count context、公开 observed signal                                      | 必填`sequence`：长度 10，`A/C/G/T`；可带 `replicate_id`、`bound_count`、`input_count`、`bound_fraction`、`input_fraction` |            exactly 128 | `normalized_enrichment`   |
| `cell_dag_nas`            | 搜索高准确率的神经网络 cell 图结构；研究自动神经架构设计和性能-结构关系        | 根据历史观测，在冻结 NASBench-101 空间中搜索 32 个规范身份不同的合法架构；最终提交架构编码      | NASBench-101 cell architecture search            | 黑盒优化   | `observations.jsonl`，419,803 条；架构和 3 次 108-epoch test accuracy                                                                 | `architecture`：长度 31 的 int token list；合法 NASBench-101 grammar，最多 9 edges                                                    |             exactly 32 | `best_k_mean`，top 5 均值 |
| `superconductor`          | 从材料组成中寻找高临界温度候选；支持超导材料发现和组成-性质建模                | 读取历史材料组成和性质，从公开候选池选择并按预测临界温度从高到低排序，提交前 32 个                     | 材料组成 / superconducting critical temperature  | 候选池排序 | `observations.jsonl` 16,795 条；`candidates.jsonl` 2,985 条；组成向量 86 维、formula context                                        | `composition`：长度 86 的数值向量；`representative_formula`                                                                         |   至少 32；只评分前 32 | `global_ndcg`             |
| `hopper_controller`       | 选择能获得高回报的控制策略；衡量黑盒策略性能预测和控制器筛选能力               | 读取策略参数和公开 rollout context，从候选池选择策略并按预测回报排序，提交前 32 个 policy              | Hopper-v5 policy ranking                         | 候选池排序 | `observations.jsonl` 1,920 条；`candidates.jsonl` 1,280 条；可见 policy parameters 和 500 条 frozen rollout context                 | `policy_weights`：长度 5,126 的 finite float vector，对应 11-64-64-3 tanh Gaussian policy                                             |   至少 32；只评分前 32 | `global_ndcg`             |
| `utr_mrl_egfp_unmodified` | 设计能提升翻译效率的 5-prime UTR；研究 RNA 调控序列与蛋白表达之间的关系        | 从历史 ribosome-load 数据中学习表达规律，从候选池中筛选并排序，提交前 128 条 UTR sequence              | 5-prime UTR translation design                   | 候选池排序 | `observations.jsonl` 76,877 条；`candidates.jsonl` 5,043 条；50-nt UTR 和 ribosome-load observations                                | `sequence`：长度 50 的 `A/C/G/T` 字符串                                                                                             | 至少 128；只评分前 128 | `normalized_enrichment`   |
| `gfp`                     | 设计更高荧光亮度的 GFP 蛋白序列；衡量蛋白工程和序列-功能预测能力               | 综合 protein/nucleotide/barcode 历史数据，从候选蛋白序列池中筛选并按预测亮度排序，提交前 128 条        | GFP protein brightness                           | 候选池排序 | `protein_observations` 41,372 条；`nucleotide_observations` 42,943 条；`barcode_observations` 45,577 条；`candidates` 10,343 条 | 必填`sequence`：长度 237 的 amino-acid sequence；可带 `protein_id`、`aa_mutations`、`mutation_count`                            | 至少 128；只评分前 128 | `normalized_enrichment`   |
| `drugmatrix_mchc`         | 预测处理条件对红细胞平均血红蛋白浓度的影响；用于毒理临床病理风险筛选           | 根据历史毒理数据对 treatment conditions 按 MCHC 预测结果排序，提交前 16 个条件                         | toxicology clinical pathology / MCHC             | 候选池排序 | 共用 DrugMatrix`observations.jsonl` 9,442 条和 `candidates.jsonl` 390 条；候选为 five-day maximum-dose treatment condition          | `condition_id`、`casrn`、`dose`、`duration_days`、`vehicle`、`sex`、`route`、`study_id`；`canonical_smiles` 可选      |   至少 16；只评分前 16 | `global_ndcg`             |
| `drugmatrix_mch`          | 预测处理条件对单个红细胞血红蛋白量的影响；用于血液学毒性筛选                   | 根据历史毒理数据对 treatment conditions 按 MCH 预测结果排序，提交前 16 个条件                          | toxicology clinical pathology / MCH              | 候选池排序 | 同上；hidden target 为 MCH                                                                                                              | 同上                                                                                                                                    |   至少 16；只评分前 16 | `global_ndcg`             |
| `drugmatrix_creatinine`   | 预测处理条件对肌酐水平的影响；作为肾功能和潜在肾毒性的临床病理信号             | 根据历史毒理数据对 treatment conditions 按 creatinine 预测结果排序，提交前 16 个条件                   | toxicology clinical pathology / creatinine       | 候选池排序 | 同上；hidden target 为 creatinine                                                                                                       | 同上                                                                                                                                    |   至少 16；只评分前 16 | `global_ndcg`             |
| `drugmatrix_sodium`       | 预测处理条件对血钠水平的影响；反映电解质稳态和全身毒理风险                     | 根据历史毒理数据对 treatment conditions 按 sodium 预测结果排序，提交前 16 个条件                       | toxicology clinical pathology / sodium           | 候选池排序 | 同上；hidden target 为 sodium                                                                                                           | 同上                                                                                                                                    |   至少 16；只评分前 16 | `global_ndcg`             |
| `drugmatrix_chloride`     | 预测处理条件对血氯水平的影响；反映电解质和酸碱平衡异常                         | 根据历史毒理数据对 treatment conditions 按 chloride 预测结果排序，提交前 16 个条件                     | toxicology clinical pathology / chloride         | 候选池排序 | 同上；hidden target 为 chloride                                                                                                         | 同上                                                                                                                                    |   至少 16；只评分前 16 | `global_ndcg`             |
| `drugmatrix_phosphorus`   | 预测处理条件对血磷水平的影响；反映矿物质代谢和器官毒理变化                     | 根据历史毒理数据对 treatment conditions 按 phosphorus 预测结果排序，提交前 16 个条件                   | toxicology clinical pathology / phosphorus       | 候选池排序 | 同上；hidden target 为 phosphorus                                                                                                       | 同上                                                                                                                                    |   至少 16；只评分前 16 | `global_ndcg`             |

## 任务细节

### TFBind8

目标是从公开的 8-mer DNA 结合观测中学习序列到结合强度的关系，并提出 32 个新序列。每个序列必须是长度 8 的 `A/C/G/T` 字符串。公开数据的 `normalized_e_score` 是目标相关的上下文信息，不能当作评测器对新候选的反馈。

### TFBind10 Pho4

每个候选是 10 个可变碱基，固定实验模板为：

```text
NNNNNCACGTGNNNNN
```

提交结果必须有 128 个序列。`replicate_id` 和 read-count 字段属于可选上下文；新设计的核心必填字段仍是 `sequence`。

### CellDAG-NAS

每个候选是一个长度 31 的 NASBench-101 cell token 编码。token 语法和有效图约束由任务契约定义；不能随意提交任意长度的邻接矩阵。评测器以 3 次 108 轮训练的测试准确率计算 top-5 均值。

这里是**固定离散空间中的黑盒架构搜索**。完整冻结表包含 423,624 个规范图，Agent 默认只看到分数最低的 40% 图对应的观测。Agent 可以通过修改边或操作产生未见过的编码，评测器将其规范化后查表；不现场训练网络。公开观测中已有的架构并未被禁止提交，表外架构则返回 `out_of_table_graph`。因此“新候选”可以指 Agent 未见过或新提出的候选，不等于 NASBench-101 之外的新架构。

### Superconductor

Agent 对公开候选组成进行排序。`composition` 是 86 维归一化元素组成向量，`representative_formula` 是可读的材料化学式。排序首位不应只依赖化学式字符串，而应结合组成向量、历史临界温度观测和相似组成分组。

### Hopper Controller

Agent 对策略参数向量排序。每个向量长度固定为 5,126，对应 11-64-64-3 的 tanh Gaussian policy。公开观测中有冻结 rollout 上下文，但隐藏评测器使用未公开的候选结果；不能把公开 500 条 rollout 的均值当成新候选的正式分数。

### UTR MRL

每个候选是 50 nt 的可变 UTR 片段。它位于固定 25-nt leader 和固定 eGFP 起始密码子 `ATG` 之间，`T` 表示转录 RNA 中的 `U`。Agent 对留出的生物学组合候选池排序，前 128 个进入评分。

### GFP

每个候选是长度 237 的 avGFP 变体蛋白序列。公开数据分为 protein、nucleotide 和 barcode 三层观测；候选提交的核心是蛋白 `sequence`。`aa_mutations` 和 `mutation_count` 是辅助上下文，不是必须由 Agent 重新推导的目标标签。

### DrugMatrix

6 个任务共用同一批处理条件，每个任务只更换一个临床病理指标：`mchc`、`mch`、`creatinine`、`sodium`、`chloride`、`phosphorus`。候选由完整处理条件字段标识；排序指标是对应指标的 `global_ndcg`。一次提交至少 16 个条件，只有前 16 个参与评分。

## Agent 实现注意事项

1. 必须根据 `submission_schema.json` 生成 JSON 数组；字段名、字符串长度、向量长度和数量约束都由校验器检查。
2. 黑盒优化任务应遵守各自的设计空间与可评分性约束，不能从“生成候选”的表述推断出必须排除所有公开观测；例如 CellDAG-NAS 允许提交已有观测架构。候选池排序任务必须从 `data/candidates.jsonl` 中选择并排序。
3. 评测器只返回聚合指标。Agent 不能依赖逐候选隐藏分数做下一轮更新；当前 loop 的反馈粒度是每次提交的聚合分数。
4. `summary_size` 是 evaluator 的辅助汇总参数，不等于 submission 数量；当前 TFBind8/CellDAG-NAS 的主指标是 top-5 mean，TFBind10/UTR/GFP 的主指标是 normalized enrichment，排名类主指标是 global NDCG。
5. 官方 task contract 没有统一规定 wall-clock、CPU/GPU、内存或 Agent 调用预算。当前项目的 `4h/6h`、`16 CPU`、`0 GPU` 和 actor attempt 上限属于本地 harness 配置。

## 官方资料与论文

### 官方项目与数据

- 官方 GitHub：[xukp20/sci-modeling-bench](https://github.com/xukp20/sci-modeling-bench)
- 官方文档：[docs](https://github.com/xukp20/sci-modeling-bench/tree/main/docs)
- Design-Bench 任务套件：[Design-Bench README](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/README.md)
- HuggingFace 数据集：[sci-modeling-bench/design-bench](https://huggingface.co/datasets/sci-modeling-bench/design-bench)
- PyPI 包：[sci-modeling-bench](https://pypi.org/project/sci-modeling-bench/)

### 各任务官方说明

- [TFBind8](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/tfbind8.md)
- [TFBind10 Pho4](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/tfbind10-pho4.md)
- [CellDAG-NAS](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/cell-dag-nas.md)
- [Superconductor](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/superconductor.md)
- [Hopper Controller](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/hopper-controller.md)
- [UTR MRL](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/utr-mrl.md)
- [GFP](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/gfp.md)
- [DrugMatrix](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/drugmatrix.md)

### 论文状态

截至 2026-08-17，在官方仓库的 README、文档、目录和 arXiv 检索中，尚未找到一篇以 SciModelingBench 为标题或正式名称发布的独立论文、arXiv 页面或 BibTeX citation。

ScienceFlow 的公开页面是成绩和实验结果页面，不是 SciModelingBench 的论文：[ScienceFlow results](https://huawei-noah.github.io/noah-research/ScienceFlow/website/)。
