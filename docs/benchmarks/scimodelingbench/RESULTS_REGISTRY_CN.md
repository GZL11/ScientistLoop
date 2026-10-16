# SciModelingBench 结果登记表

本文件是 SciModelingBench 实跑结果的人工查阅入口；机器可读主表是
[RESULTS_REGISTRY.csv](./RESULTS_REGISTRY.csv)。表中路径均相对于仓库根目录，
实际运行产物位于 `.famou/`，不复制进 git。

当前 registry 共包含 15 个正式进入 benchmark loop 并生成
`run_summary.json` 的 run，覆盖全部 13 个 task。其中 `tfbind8` 有 3 次正式
run；其余 task 各有 1 个当前正式 run。另有 7 个启动失败、中断或 CLI 冒烟
目录，不计入正式结果数量。

## 13 个任务当前结果

除 `tfbind8` 的历史 mixed run 外，其余结果均使用 Claude Code 运行时和
`deepseek-v4-pro`。所有主指标方向均为 `higher_is_better`。

| task | run | 主指标 | effective score | attempts | 预算 | cost | loop outcome |
|---|---|---|---:|---:|---|---:|---|
| `tfbind8` | `tfbind8-20260811-234519` | `best_k_mean` | `0.977951169013977` | 78 / 3 | 历史多阶段 resume | `$209.187917` | `best_candidate_found` |
| `tfbind10_pho4` | `tfbind10_pho4-20260814-230416` | `normalized_enrichment` | `0.2584928388391788` | 57 / 5 | 4h + 6h + 4h resume | `$104.212924` | `best_candidate_found` |
| `cell_dag_nas` | `cell_dag_nas-20260815-114514` | `best_k_mean` | `0.9367988785107931` | 9 / 5 | 4h | `$27.348549` | `best_candidate_found` |
| `superconductor` | `superconductor-20260815-114514` | `global_ndcg` | `0.8854523179062505` | 26 / 3 | 4h | `$60.217958` | `best_candidate_found` |
| `hopper_controller` | `hopper_controller-20260815-114516` | `global_ndcg` | `0.9988496842068979` | 11 / 4 | 4h | `$24.555282` | `best_candidate_found` |
| `utr_mrl_egfp_unmodified` | `utr_mrl_egfp_unmodified-20260814-230416` | `normalized_enrichment` | `0.7707625364397788` | 25 / 4 | 4h | `$52.871095` | `best_candidate_found` |
| `gfp` | `gfp-20260815-114515` | `normalized_enrichment` | `0.25671023841811164` | 55 / 4 | 4h + 4h resume | `$106.869445` | `best_candidate_found` |
| `drugmatrix_mchc` | `drugmatrix_mchc-20260814-231050` | `global_ndcg` | `0.6715582143226477` | 39 / 4 | 4h + 4h resume | `$103.113500` | `best_candidate_found` |
| `drugmatrix_mch` | `drugmatrix_mch-20260814-231053` | `global_ndcg` | `0.3389750196964854` | 86 / 5 | 4h + 6h + 4h resume | `$193.652554` | `best_candidate_found` |
| `drugmatrix_creatinine` | `drugmatrix_creatinine-20260814-231052` | `global_ndcg` | `0.7688727614361732` | 74 / 3 | 4h + 6h + 4h resume | `$192.513421` | `best_candidate_found` |
| `drugmatrix_sodium` | `drugmatrix_sodium-20260814-231051` | `global_ndcg` | `0.2442836509938763` | 90 / 5 | 4h + 6h + 4h resume | `$188.917365` | `best_candidate_found` |
| `drugmatrix_chloride` | `drugmatrix_chloride-20260814-231051` | `global_ndcg` | `0.5621364637911708` | 31 / 3 | 4h | `$80.158791` | `best_candidate_found` |
| `drugmatrix_phosphorus` | `drugmatrix_phosphorus-20260814-231053` | `global_ndcg` | `0.529320954117503` | 36 / 4 | 4h + 4h resume | `$104.694704` | `best_candidate_found` |

`attempts` 列为 `completed / not_executed`。4 个历史 6h resume run 和本次 7 个 4h
resume 的 attempts、usage 和 cost 均按同一 run 目录累计；`run_summary` 中保留最终
promoted candidate 和完整 usage ledger。

## CellDAG-NAS 官方参考 baseline

`cell_dag_nas` 没有出现在 ScienceFlow 的公开 12-task Agent 成绩表中，因此
ScienceFlow 页面没有 Claude Code、Codex、OpenCode 或 Pi 的对应列。SciModelingBench
官方后来在 CellDAG-NAS 任务说明中补充了同一 `N=32, K=5` 协议下的 data-only
reference baselines；它们使用公开 token 位置和公开的三次可见 repeat 均值，不使用
隐藏标签、隐藏 hash 或 evaluator 反复试分。该参考表来自 SciModelingBench 0.7.0
任务文档，不能当作 Agent leaderboard：

| 参考方法 | `best_k_mean` | `batch_mean` | `global_ndcg` | 性质 |
|---|---:|---:|---:|---|
| Random audit mean | 0.928730 | - | 0.947100 | 随机参考，当前 `N=32` 协议 |
| Fixed Ridge, alpha=1 | **0.934322** | 0.924569 | **0.980915** | 公开数据 surrogate baseline |
| CV-selected histogram gradient boosting | 0.933954 | **0.925418** | 0.979659 | 三折 group CV 的公开数据 baseline |
| 本地 Agent run | **0.936799** | 未登记 | 未登记 | DeepSeek-V4-Pro + Claude Code，正式 evaluator 分数 |

官方还报告了一个早期 `N=128` model audit，但它与当前 `N=32` 提交契约不可直接
比较；历史 Design-Bench 的 `NAS = 1.079 +/- 0.059` 则属于不同的 ResidualConfig-NAS
任务，也不是 CellDAG-NAS baseline。

来源：[官方 CellDAG-NAS 任务说明](https://github.com/xukp20/sci-modeling-bench/blob/main/docs/suites/design-bench/cell-dag-nas.md)，
尤其是其中的 “Current data-only reference baselines” 和 metric audit 小节。

## 最佳提交目录

| task | best attempt | promoted output |
|---|---:|---|
| `tfbind8` | `0072` | `.famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519/candidates/candidate_1786685052927_18443aed/output/submission` |
| `tfbind10_pho4` | `0040` | `.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-20260814-230416/candidates/candidate_1786788702335_af9ac09e/output/submission` |
| `cell_dag_nas` | `0006` | `.famou/scimodelingbench-fmjob-runs/cell_dag_nas-20260815-114514/candidates/candidate_1786776866548_3054a8b1/output/submission` |
| `superconductor` | `0015` | `.famou/scimodelingbench-fmjob-runs/superconductor-20260815-114514/candidates/candidate_1786776977839_1a6255e5/output/submission` |
| `hopper_controller` | `0009` | `.famou/scimodelingbench-fmjob-runs/hopper_controller-20260815-114516/candidates/candidate_1786776906076_e2a54005/output/submission` |
| `utr_mrl_egfp_unmodified` | `0005` | `.famou/scimodelingbench-fmjob-runs/utr_mrl_egfp_unmodified-20260814-230416/candidates/candidate_1786725107133_1123b8fe/output/submission` |
| `gfp` | `0004` | `.famou/scimodelingbench-fmjob-runs/gfp-20260815-114515/candidates/candidate_1786768913015_dc90b1be/output/submission` |
| `drugmatrix_mchc` | `0013` | `.famou/scimodelingbench-fmjob-runs/drugmatrix_mchc-20260814-231050/candidates/candidate_1786730824459_d978feec/output/submission` |
| `drugmatrix_mch` | `0064` | `.famou/scimodelingbench-fmjob-runs/drugmatrix_mch-20260814-231053/candidates/candidate_1787023998808_fc49d4ac/output/submission` |
| `drugmatrix_creatinine` | `0034` | `.famou/scimodelingbench-fmjob-runs/drugmatrix_creatinine-20260814-231052/candidates/candidate_1786775938273_1030d512/output/submission` |
| `drugmatrix_sodium` | `0008` | `.famou/scimodelingbench-fmjob-runs/drugmatrix_sodium-20260814-231051/candidates/candidate_1786726029983_696bf0fe/output/submission` |
| `drugmatrix_chloride` | `0013` | `.famou/scimodelingbench-fmjob-runs/drugmatrix_chloride-20260814-231051/candidates/candidate_1786729644149_8a6d7c73/output/submission` |
| `drugmatrix_phosphorus` | `0001` | `.famou/scimodelingbench-fmjob-runs/drugmatrix_phosphorus-20260814-231053/candidates/candidate_1786721599150_0f5deb4e/output/submission` |

## TFBind8 其他正式 run

| run | 模型 | loop outcome | score | attempts | cost | 备注 |
|---|---|---|---:|---:|---:|---|
| `tfbind8-20260811-235953` | `glm-5.2` | `best_candidate_found` | `0.974384605884552` | 15 / 2 | `$34.698710` | 正常完成并 promote |
| `tfbind8-20260811-172005` | `glm-5.2` | `no_valid_candidate` | 无 | 19 / 0 | `$47.867469` | 没有有效候选和正式分数 |

分数比较时看 `effective_score`；方向由 `problem/metric_contract.json` 决定。
所有当前 best run 的 `final_evaluation` 都是 `null`，不能把它当成 score 的别名。

## 非正式产物目录

以下目录保留在磁盘上用于排查，但不作为正式结果记录：

| 目录 | 分类 | 结果 |
|---|---|---|
| `tfbind8-20260811-160306` | `bootstrap_incomplete` | 未生成 `controller/run_summary.json` |
| `tfbind8-20260811-161359` | `bootstrap_incomplete` | 未生成 `controller/run_summary.json` |
| `tfbind8-20260811-161606` | `bootstrap_incomplete` | 未生成 `controller/run_summary.json` |
| `tfbind8-20260811-162238` | `bootstrap_incomplete` | 未生成 `controller/run_summary.json` |
| `tfbind8-20260811-163407` | `interrupted_without_finalization` | `research_state.yaml` 停留在 `running`，没有正式评分 |
| `tfbind8-20260811-225435` | `bootstrap_incomplete` | 未生成 `controller/run_summary.json` |
| `tfbind8-kimi-smoke` | `adapter_smoke_no_benchmark_result` | Kimi CLI 冒烟，没有进入正式 benchmark loop |

## 字段约定

- `fm_job_status`：外层 `fm-job` 状态；如果没有可靠 job 记录则留空。
- `loop_status` / `loop_outcome`：Famou Loop 自己的最终状态和 outcome。
- `result_class`：便于筛选的归类，不替代原始状态字段。
- `configured_models`：run 配置中的模型；`observed_runtime` 和 `observed_models` 来自 usage 汇总，可能与配置不同。
- `best_score`：loop 记录的最佳正式分数；`effective_score`：用于排序和 promote 的有效分数。
- `code_dir` / `output_dir`：promoted candidate 的代码和 submission 目录；没有 promoted candidate 时留空。
- `trajectory_path` / `usage_path`：控制器轨迹和 Agent usage ledger。
- `input_tokens` / `output_tokens` / `reported_total_tokens` / `cache_read_input_tokens`：usage 汇总中的 token 字段；`idea_calls`、`implement_calls` 及对应 cost 用于分角色分析。
- `reported_cost_usd`：只记录 CLI/adapter 明确上报的费用，不对缺失价格做估算。
- `final_evaluation`：最终化阶段的独立评估字段；当前记录为 `null` 不代表最佳分数为零。

## 更新规则

每次新的 SciModelingBench run 完成后：

1. 从 `controller/run_summary.json` 读取 loop 字段、计数、时间和 usage 汇总。
2. 从 `controller/promoted_best.json` 读取 promoted code/output 路径。
3. 从 `problem/metric_contract.json` 读取 metric、方向和 submission size。
4. 将外层 job id/status 单独写入 `fm_job_id` / `fm_job_status`。
5. 追加或更新 CSV 对应 `record_id`，同时更新本文件的“当前结果”和“正式 Loop 结果”。

标准原始证据路径：

```text
.famou/scimodelingbench-fmjob-runs/<run_id>/controller/run_summary.json
.famou/scimodelingbench-fmjob-runs/<run_id>/controller/promoted_best.json
.famou/scimodelingbench-fmjob-runs/<run_id>/controller/trajectory.jsonl
.famou/scimodelingbench-fmjob-runs/<run_id>/artifacts/agent_usage.jsonl
.famou/scimodelingbench-fmjob-runs/<run_id>/artifacts/agent_trajectory.jsonl
```
