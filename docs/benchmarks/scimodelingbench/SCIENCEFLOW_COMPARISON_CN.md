# SciModelingBench 与 ScienceFlow 公开成绩对比

来源：ScienceFlow 公开页面（访问日期：2026-08-15）

<https://huawei-noah.github.io/noah-research/ScienceFlow/website/>

## 口径

ScienceFlow 页面公开的是 SciModelingBench 的 12 个任务、7 个 group，页面标注完成日期为 2026-07-22，指标方向为 higher is better。其表中 Agent 列使用 DeepSeek-V4-Flash-Preview；Group-balanced score 将 Random 映射为 0、可达到的最优值映射为 100，并对 7 个 group 等权。论文第 3.3.1 节和附录 E 进一步明确给出这批实验的运行配置：2 小时、8 个逻辑 CPU、无加速卡、峰值 RSS 小于 32 GiB；每个 system-task 只运行一次，任务级 batch query quota 为 8-20，由两个同质 worker 分摊。

### 7-group 的定义与任务划分

ScienceFlow 官网将 12 个 SciModelingBench 任务汇总为 7 个 group：

| Group | 包含的 task |
|---|---|
| TFBind8 | `tfbind8` |
| Superconductor | `superconductor` |
| UTR MRL | `utr_mrl_egfp_unmodified` |
| TFBind10 | `tfbind10_pho4` |
| GFP | `gfp` |
| Hopper | `hopper_controller` |
| DrugMatrix | `drugmatrix_mchc`、`drugmatrix_mch`、`drugmatrix_creatinine`、`drugmatrix_sodium`、`drugmatrix_chloride`、`drugmatrix_phosphorus` |

这里的任务族依据来自 SciModelingBench 的数据组织：6 个 DrugMatrix endpoint 使用同一类 DrugMatrix 临床病理数据和候选条件空间，只是预测 endpoint 不同。因此 ScienceFlow 把它们视为一个 group，而不是让 DrugMatrix 的 6 个 endpoint 占据总分的一半。

但 **7-group Group-balanced Score 这一总分口径是 ScienceFlow 的报告指标，不是 SciModelingBench package 要求所有使用者必须采用的官方总分**。SciModelingBench 主要规定单 task 的输入、候选提交协议和 evaluator 指标；ScienceFlow 在此基础上定义了跨 task 的分组汇总。

归一化后的 task 分数为：

```text
normalized_t = 100 * (score_t - random_t)
                       / (attainable_optimum_t - random_t)
```

其中 Random 映射为 0，可达到的最优值映射为 100。先对 6 个 DrugMatrix endpoint 求平均得到 DrugMatrix group 分数，再对 7 个 group 求等权平均：

```text
Group-balanced = (6 个 standalone task 分数 + DrugMatrix group 分数) / 7
```

所以每个 standalone task 的权重是 `1/7`，整个 DrugMatrix group 的权重也是 `1/7`，每个 DrugMatrix endpoint 的权重是 `1/42`。例如 ScienceFlow 公开值满足：`(54.16 * 6 + 55.91) / 7 = 54.41`。

需要区分 ScienceFlow 的 12-task 表和当前本地任务集合：本地还包含 `cell_dag_nas`，因此本地是 13 个 task。`cell_dag_nas` 不在 ScienceFlow 公开表中；若要把它纳入同样的任务族等权原则，应作为额外 group，形成 8-group 汇总，而不能继续直接称为 ScienceFlow 的 7-group score。

本地结果使用 run 的 `effective_score`，即同一 task evaluator 的正式 best score。当前本地 8 个已完成结果使用 `claude + deepseek-v4-pro`；`tfbind8` 使用的是历史 mixed run（包含 Claude/Kimi/GLM/DeepSeek），因此不能视为单一 Agent 配置的严格对照。`cell_dag_nas` 不在 ScienceFlow 公开的 12-task 表中。

`Delta vs public Claude Code` 只是和 ScienceFlow 表中的 Claude Code 列做数值比较，不是严格的模型归因实验：本地使用 DeepSeek-V4-Pro，ScienceFlow 页面说明其表中 Agent 使用 DeepSeek-V4-Flash-Preview。

`cell_dag_nas` 只有本地 Agent 结果，是因为 ScienceFlow 公开面板只包含 12 个任务，
没有该任务。SciModelingBench 官方在 2026-07-23 之后的 CellDAG-NAS 任务文档中才
补充了当前 `N=32, K=5` 协议的 data-only reference baselines；这些不是 ScienceFlow
的 Agent 成绩，不能放进下面的 Agent 列直接横比。

## 完整任务表

| Task | ScienceFlow | Claude Code | Codex | OpenCode | Pi | Random | 本地结果 | Delta vs Claude Code | 本地状态 | 本地 run 目录 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `tfbind8` | 0.9769 | 0.9648 | 0.9718 | 0.9764 | 0.9730 | 0.7533 | **0.977951** | +0.013151 | completed；历史 mixed run | `.famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519` |
| `superconductor` | 0.8583 | 0.8132 | 0.8188 | 0.4929 | **0.8671** | 0.2800 | **0.885452** | +0.072252 | completed；新镜像重跑 | `.famou/scimodelingbench-fmjob-runs/superconductor-20260815-114514` |
| `utr_mrl_egfp_unmodified` | **0.7605** | 0.7367 | 0.7424 | 0.6523 | 0.7533 | -0.0006 | **0.770763** | +0.034063 | completed | `.famou/scimodelingbench-fmjob-runs/utr_mrl_egfp_unmodified-20260814-230416` |
| `tfbind10_pho4` | 0.2543 | **0.3197** | 0.2024 | 0.2467 | 0.2473 | 0.0000 | **0.258493** | -0.061207 | completed；6h resume | `.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-20260814-230416` |
| `gfp` | **0.2732** | 0.1977 | 0.2586 | 0.2600 | 0.2692 | 0.0001 | **0.256710** | +0.059010 | completed；新镜像重跑 | `.famou/scimodelingbench-fmjob-runs/gfp-20260815-114515` |
| `hopper_controller` | 0.3756 | 0.3718 | 0.3755 | **0.3917** | 0.3248 | 0.1698 | **0.998850** | +0.627050 | completed；新镜像重跑 | `.famou/scimodelingbench-fmjob-runs/hopper_controller-20260815-114516` |
| `drugmatrix_mchc` | 0.7220 | 0.6503 | 0.6178 | **0.7344** | 0.3720 | 0.1733 | **0.671558** | +0.021258 | completed | `.famou/scimodelingbench-fmjob-runs/drugmatrix_mchc-20260814-231050` |
| `drugmatrix_mch` | **0.4793** | 0.3623 | 0.4242 | 0.4147 | 0.3673 | 0.2669 | **0.338975** | -0.140325 | completed；6h + 4h resume | `.famou/scimodelingbench-fmjob-runs/drugmatrix_mch-20260814-231053` |
| `drugmatrix_creatinine` | 0.6995 | **0.8038** | 0.5681 | 0.6081 | 0.7638 | 0.1955 | **0.768873** | -0.034927 | completed；6h resume | `.famou/scimodelingbench-fmjob-runs/drugmatrix_creatinine-20260814-231052` |
| `drugmatrix_sodium` | 0.8488 | **0.8498** | 0.7696 | 0.7619 | 0.8283 | 0.1519 | **0.244284** | -0.605516 | completed；6h resume未提升 | `.famou/scimodelingbench-fmjob-runs/drugmatrix_sodium-20260814-231051` |
| `drugmatrix_chloride` | 0.5488 | 0.5397 | **0.5589** | 0.5106 | 0.4551 | 0.1689 | **0.562136** | +0.022436 | completed | `.famou/scimodelingbench-fmjob-runs/drugmatrix_chloride-20260814-231051` |
| `drugmatrix_phosphorus` | **0.5985** | 0.3999 | 0.3749 | 0.4130 | 0.4917 | 0.2040 | **0.529321** | +0.129421 | completed | `.famou/scimodelingbench-fmjob-runs/drugmatrix_phosphorus-20260814-231053` |
| `cell_dag_nas` | - | - | - | - | - | - | **0.936799** | - | completed；ScienceFlow 表未列出 | `.famou/scimodelingbench-fmjob-runs/cell_dag_nas-20260815-114514` |

### CellDAG-NAS 参考基线

| 方法 | `best_k_mean` | `batch_mean` | `global_ndcg` |
|---|---:|---:|---:|
| Random audit mean | 0.928730 | - | 0.947100 |
| Fixed Ridge, alpha=1 | **0.934322** | 0.924569 | **0.980915** |
| CV-selected histogram gradient boosting | 0.933954 | **0.925418** | 0.979659 |
| 本地 Agent run | **0.936799** | 未登记 | 未登记 |

这些数值来自官方 [CellDAG-NAS 任务说明](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/cell-dag-nas.md)。
Ridge 和 histogram gradient boosting 只使用公开 token/重复观测，属于 data-only
surrogate reference；本地 Agent 分数则由 trusted evaluator 对最终 32 个架构重新评估，
二者可以作任务级参考，但不能解读为同一 Agent leaderboard。

## ScienceFlow 总表

| Group / summary | ScienceFlow | Claude Code | Codex | OpenCode | Pi | Random |
|---|---:|---:|---:|---:|---:|---:|
| Standalone Design（6） | 54.16 | 51.65 | 51.49 | 43.84 | 52.77 | 0.00 |
| Rat Clinical Pathology（6） | 55.91 | 49.64 | 43.79 | 46.44 | 43.12 | 0.00 |
| Group-balanced Score | **54.41** | 51.37 | 50.39 | 44.21 | 51.39 | 0.00 |
| 7-group Avg. Rank（lower is better） | **1.55** | 3.69 | 3.64 | 3.33 | 2.79 | - |
| Task Wins | **5/12** | 3/12 | 1/12 | 2/12 | 1/12 | - |

本地 Group-balanced Score 尚未填入：虽然 13 个 task 都已有结果，但本地多出 `cell_dag_nas`，不能直接套用 ScienceFlow 的 12-task/7-group 分母。后续应先分别计算 12-task 可比口径，再单独报告包含 `cell_dag_nas` 的 13-task/8-group 扩展口径。

## 运行限制口径

SciModelingBench package 本身不规定这些资源预算，但 ScienceFlow 论文为本次对比实验通过 external harness 固定了运行配置。

官方规定的是 submission/evaluation contract：

| Task form | 官方约束 |
|---|---|
| Black-box optimization | 必须提交 exactly configured number 的 distinct、valid candidates |
| Candidate-pool ranking | 至少提交 configured prefix size `N`；只评分前 `N` 个，超出的 suffix 忽略 |
| 当前 submission size | TFBind8 `32`、TFBind10 `128`、CellDAG-NAS `32`、Superconductor/Hopper `32`、UTR/GFP `128`、每个 DrugMatrix endpoint `16` |

论文 Table A8 的任务级配置为：TFBind8 32/5/20；TFBind10 Pho4 128/16/20；Superconductor 32/5/20；UTR MRL 128/16/20；GFP 128/16/20；Hopper 32/5/10；DrugMatrix 每个 endpoint 16/5/8。N/K/Q 分别是提交候选数、shared diagnostics summary size 和 batch query 总数，Q 由两个 worker 共同分摊。

官网页面本身没有展示资源配置；论文正文已经补充了 SciModelingBench 的正式实验约束，不能只依据网页判断为“未公开”。网页中出现的 `Running Time (hours)` 仍属于同页的 MLE-bench 面板，不是 SciModelingBench。

本项目当前使用的 `4h` 初始运行、`6h` resume、`16 CPU / 0 GPU / 64 GiB`、actor run-attempt 上限和 evaluator queue timeout 都是 Famou Loop/fm-job 的实验预算，不能称为 benchmark 官方要求。当前任务使用预计算/缓存的 trusted evaluator 数据，Hopper 文档中的 `500 frozen rollouts per policy` 是任务证据规模，不是 Agent 必须现场运行 500 次 rollout 的资源要求。

## 当前判断

- ScienceFlow 的公开结果在 `tfbind8`、`UTR MRL`、`MCHC`、`Chloride`、`Phosphorus` 等任务上提供了明确参照；本地当前 best 在 `tfbind8`、`UTR MRL`、`MCHC`、`Chloride`、`Phosphorus` 上高于其公开 Claude Code 列。
- 本地 `tfbind10_pho4`、`drugmatrix_mch`、`drugmatrix_creatinine`、尤其 `drugmatrix_sodium` 明显低于 ScienceFlow 公开 Claude Code 结果，这些是当前最需要诊断的任务。
- `superconductor`、`gfp`、`hopper_controller` 的旧 run 因 Pod HF 依赖不兼容没有有效分数；新镜像重跑已经通过 Pod 内 dataset preflight 并生成正式结果。
- ScienceFlow 的 `54.41` 是其 12-task/7-group 汇总分，不等于任意单任务分数的简单平均；本地最终汇总应复刻其 group normalization 后再比较。
