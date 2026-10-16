# ScienceFlow 对齐批次诊断

## 批次口径

诊断批次：`scienceflow-dsv4flash-20260820-180500`，覆盖 ScienceFlow 页面中的 12 个任务，不包含 `cell_dag_nas`。

配置：`claude + deepseek-v4-flash`，2 小时/task，8 CPU、0 GPU、32 GiB，idea/implement/evaluation 并发均为 2，最多 20 次 benchmark attempt，单个 canonical candidate timeout 为 3600 秒。

这只对齐了模型、runtime、wall-clock 和申请资源，不是同构的研究算法。Famou 仍是 `idea -> implement -> evaluation` 队列，因此相同 wall-clock 不等于相同有效研究时间或提交次数。

## 总表

| task | 本批次 best | ScienceFlow | 差值 | 有效评测 | 诊断分类 |
|---|---:|---:|---:|---:|---|
| `tfbind8` | 0.439294 | 0.9769 | -0.537606 | 3 | 执行正常，策略错误 |
| `superconductor` | 0.479884 | 0.8583 | -0.378416 | 7 | 候选失败 + 排序泛化差 |
| `utr_mrl_egfp_unmodified` | 0.661207 | 0.7605 | -0.099293 | 3 | 排序质量/反馈不足 |
| `tfbind10_pho4` | 无 | 0.2543 | - | 0 | 外层 Job 终止 |
| `gfp` | 0.254711 | 0.2732 | -0.018489 | 1 | 中间结果，外层 Job 终止 |
| `hopper_controller` | 无 | 0.3756 | - | 0 | 超时前未提交 |
| `drugmatrix_mchc` | 0.744119 | 0.7220 | +0.022119 | 6 | 成功；有 evaluator bug |
| `drugmatrix_mch` | 0.348698 | 0.4793 | -0.130602 | 5 | endpoint 排序质量差 |
| `drugmatrix_creatinine` | 0.606404 | 0.6995 | -0.093096 | 3 | 反馈不足 |
| `drugmatrix_sodium` | 无 | 0.8488 | - | 0 | candidate 超时 |
| `drugmatrix_chloride` | 0.298849 | 0.5488 | -0.249951 | 2 | 执行快但排序差 |
| `drugmatrix_phosphorus` | 0.510999 | 0.5985 | -0.087501 | 5 | 有提升但未收敛 |

最终 10 个 Job `Succeeded`、2 个 `Failed`；正常停止的 loop 基本记录为 `wall_time_budget_exhausted`。

## 逐任务结论

### `tfbind8`

三个 candidate 都成功执行，每次约 6--8 秒，没有 candidate timeout 或 evaluator failure；三个 official evaluation 的 primary score 完全相同，为 `0.43929409980773926`。`run_evidence_tfbind8.json` 显示 Agent 把“公开 observation 内部 reverse-complement 闭合”错误解释成“公开集合已经确定完整 65536 空间”，设置 `gate(use_unseen)=false`，固定提交公开 top-32。

这是错误的全空间最优性假设。历史 run 已找到约 `0.977951` 的高分序列，而且这些序列不在本批次公开 observation 中。根因是没有复用同 task 历史 artifact，且廉价 evaluator 在 2 小时内只被调用 3 次。

### `superconductor`

两次 candidate 进程失败：`experiment_1787222149430_638f1595.json` 报 XGBoost `bad_malloc`；`experiment_1787225361743_07bc3349.json` 报 `libgomp: Thread creation failed`。其余 candidate 约 92--154 秒可完成，说明不是数据下载问题，而是 XGBoost/OpenMP 线程和内存没有服从 lease。

算法上，某候选公开伪 NDCG 为 `0.9993`，official score 只有 `0.479884`，说明 observation 内 CV 严重高估了对隐藏 candidate pool 的排序能力。

### `utr_mrl_egfp_unmodified`

7 次 attempt、3 次有效评测，执行约 64--132 秒且均成功。最佳公开 CV Spearman 约 `0.724`，official score `0.661207`。这是代理泛化和反馈轮数不足，不是设施失败。

### `tfbind10_pho4`

4 个 idea/attempt proposal 都没有形成 candidate。方案要处理约 208 万 observation 并扫描约 1048576 个 10-mer，未在截止前形成可执行 submission。preflight 成功且 `EVALUATOR_READY.json` 存在，但没有 `CLIENT_DONE.json`、`EVALUATOR_DONE.json`、candidate 或 official evaluation。只能确认外层 Job 在 Agent 完成前终止，当前 artifact 不能确认是 OOM、节点驱逐还是平台删除。

### `gfp`

唯一有效结果为 `normalized_enrichment=0.25471110721477425`、`global_ndcg=0.41443041626463645`。该 candidate 正常完成；之后第三个 implement actor 只有 request/prompt，没有 result artifact，`agent.log`/`agent.stderr.log` 为空，且没有 `CLIENT_DONE`/`EVALUATOR_DONE`。因此这是中间有效分数，不能视为完整搜索后的最终能力；底层 Job 退出码没有保留。

### `hopper_controller`

没有 candidate/evaluation。方案包含 5126 维 policy weight、PCA、kNN/label diffusion、GBDT、K-fold NDCG 和 rollout refinement，明显过重。问题是没有“先交可运行 baseline”的门槛，Agent 在第一版 submission 前耗尽时间，不是 evaluator 失败。

### `drugmatrix_mchc`

8 次 attempt、6 次有效评测，最佳 `0.744119`，超过 ScienceFlow。一次 evaluator 失败为 `official_eval_1787224611970_a69cf97a.json`，错误是 `AttributeError: 'str' object has no attribute 'get'`。后期 transductive condition matching/SMILES dose-response 路线有效；该 task 是本批次成功案例，但 evaluator schema 需要修复。

### `drugmatrix_mch`

8 次 attempt、5 次有效评测，每次约 26--30 秒，均执行正常。最佳 `0.348698`。最佳候选日志显示 390 个候选中 387 个主要使用 direct evidence，排序退化为直接 d3 effect 的绝对值排序，未充分处理 dose、study/vehicle 对照和跨 endpoint 结构共享。根因是 endpoint-specific 目标建模不足，不是运行慢。

### `drugmatrix_creatinine`

4 次 attempt、3 次有效评测，执行约 0.15--11 秒且均成功。matched-control、exact-dose、fold/lower/ULN/absolute severity 能输出有效提交，但反馈太少，尚未判断哪种组合真正有效；应提高迭代频率，不是继续堆单次模型复杂度。

### `drugmatrix_sodium`

两个 candidate 都经过 syntax/preflight，但均记录 `returncode=-15`、`timed_out=true`、`termination_reason=timeout`、`error_code=canonical_timeout`、`duration_ms=3600182`。问题是训练/推理超过 3600 秒，没有阶段 deadline 或低复杂度 fallback，导致两次机会都被长任务占满。

### `drugmatrix_chloride`

2 次 attempt、2 次有效评测，candidate 约 1 秒，没有执行或 evaluator 故障；最佳 `0.298849`。方法能快速输出 16 个候选，但 endpoint-specific 排序方向不足，且没有足够 feedback 触发有效 refine/new-idea/fuse。

### `drugmatrix_phosphorus`

7 次 attempt、5 次有效评测，单次约 0.2--1.2 秒且均成功。分数从约 `0.346` 提升到 `0.447`、再到 `0.510999`，说明 d3/d5 anchor 和 chemotype/Morgan-kNN 方向有用，但反馈内尚未收敛。

## 系统性根因与修复优先级

1. **有效搜索量不足**：`tfbind8=3`、UTR=3、MCHC=6、MCH=5、creatinine=3、chloride=2、phosphorus=5；`tfbind10`、`hopper`、`sodium` 为 0。应把“2 小时”转成有效 submission budget，而不是只限制 wall-clock。
2. **缺少 first-submission gate**：`tfbind10`、`hopper` 先做复杂研究再提交；`sodium` 两次都超时。剩余预算达到约 70% 仍无 candidate 时，应强制生成 schema-valid baseline。
3. **proxy CV 不可靠**：`superconductor` 的公开伪 NDCG `0.9993` 与 official `0.479884` 严重背离。需要按 candidate distribution、study/family、replicate 做更接近 evaluator 的切分。
4. **数值库线程失控**：统一设置 `OMP_NUM_THREADS`、`MKL_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`NUMEXPR_NUM_THREADS`，并显式设置 XGBoost/LightGBM `n_jobs`。
5. **canonical deadline 防护不足**：候选运行必须有阶段 deadline、先提交 baseline、接近 3600 秒时 fallback 到最近一次可运行结果。
6. **缺少同 task warm-start**：`tfbind8` 应复用历史高分候选和方法 artifact，不能每次从公开 top-32 假设重新开始；DrugMatrix endpoint 也应持久化已验证 baseline。
7. **Job 失败不可观测**：在 wrapper/`task_entrypoint.sh` 的 `TERM/INT/EXIT` trap 中写入不可变 `job_exit.json`，记录 exit code、signal、阶段、PID、时间戳和 `CLIENT_DONE`/`EVALUATOR_DONE` 状态，并保留 Pod termination reason。
8. **evaluator schema 防御不足**：修复 MCHC 的字符串/对象类型检查，把异常转成可重试的结构化错误。

## 证据目录

```text
.famou/scimodelingbench-fmjob-runs/<task>-scienceflow-dsv4flash-20260820-180500/
```

重点文件：`research_state.yaml`、`logs/orchestrator.log`、`artifacts/benchmark_attempt/*.json`、`artifacts/experiment_run/*.json`、`artifacts/evaluator_scores/official_eval_*.json`、`artifacts/method_specs/*.json` 和 `trusted/logs/*`。

本文只把 artifact 能直接证实的内容写成确定结论；对于 `gfp` 和 `tfbind10_pho4` 的底层 Pod 退出原因，目前只能定位到“外层 Job 终止”，不能冒充已经确认是 OOM 或节点问题。
