# NatureBench 实验运行记录

本文档按批次追加 NatureBench 实验过程、对比、失败诊断和审计证据，不作为实时结果主表。
每个 case 的当前正式结果和实时进度统一查看
[`CURRENT_RESULTS_CN.md`](CURRENT_RESULTS_CN.md)；重跑闭环后修改主表对应行，不在本文追加一份
新的“当前快照”。

本文保留各批次运行结果、产物入口、官方数值 evaluator 响应和 Validity Judge 状态。
正式结果只统计具有有限 `best_score` 且 Judge 返回严格布尔结论的运行；Judge 基础设施错误
不会被伪写成 `invalid`。

当前正式进度入口是 [`CURRENT_RESULTS_CN.md`](CURRENT_RESULTS_CN.md)，实验审计记录是本文，官方提交包入口是
[`famou-glm52-official-current`](../../../.famou/naturebench-submissions/famou-glm52-official-current/)；该包已于 2026-08-21 按
「GPT-5.5 Valid 且分数最高」口径全量重建，Run 与判定严格取自主表，上一版归档为
`famou-glm52-official-pre-v3-20260821`。
带日期的 v8/v9/v10 目录只保留作历史审计，不再作为当前结果引用。

## NatureBench 单次结果口径

按官方提交格式，`results.csv` 对每个 `case_id` 只保留一行最终结果，榜单不是把多个
独立 Run 的分数做平均。单个 Famou Run 内可以提交多个 candidate，Controller 会完成
这些 candidate 的评测并记录该 Run 的最佳有效 `best_score`；多次独立重跑只用于修复
设施、补齐缺失结果或验证新版本，不能把不同 Run 的分数拼成一个平均值。正式提交时
必须预先确定每个 case 使用哪一个完整 Run，重跑对比表只用于审计和分析。

## 固定统计口径与当前快照

从 2026-08-12 起，本文只使用下面三种互不混用的统计口径：

1. **NatureBench 主表**：固定以官方 `90` 个唯一 `case_id` 为分母，每个 case 只选择
   一个完整 Run。严格可信结果必须同时满足：具有有限官方数值分数、最终 Validity Judge
   为 `valid`、覆盖全部官方实例、所有关键指标有限、`raw_scores` 不含实例级
   `error`/`partial_errors`，并且不存在已确认的数据或 evaluator blocker。仅有 Judge
   `valid` 不能再被统计为可信完成；`invalid`、无正式结果和数值评测不完整分别统计。
2. **Search-v2 批次**：固定指 2026-08-11 预先提交的 `15` 个
   `20260811-search-v2-*` Run。后续 `code-refresh`、`configfix`、`required-rerun` 和
   `rerun2/3` 即使也启用了 `pairwise_improve`，也不能混入这个策略效果分母。
3. **运行队列**：按 fm-job 的实时 Job 数统计，只表示当前运行状态，不参与主表和
   Search-v2 的 Match/Surpass 指标计算。

截至 **2026-08-21 CST**，在 v9 基础上合并 old-policy、Search-v2、2026-08-17/18
Claude Code + `deepseek-v4-pro` 重跑、2026-08-20 Opus-5 对照批次和 2026-08-20
invalid-v3 合规重跑的已完成结果，并按上述条件逐项核对最佳 attempt；全部有正式 Run 的
case 均已用 NatureBench 官方 Judge 流程以 `gpt-5.5` 复核，采用口径为「GPT-5.5 Valid 且
分数最高」。本地 90-case 严格主表快照为：

| 状态 | Case 数 | 占全部 90 个 task |
|---|---:|---:|
| **严格可信完成** | **82** | **91.11%** |
| Judge Valid，但数值结果不可信 | 2 | 2.22% |
| Judge Invalid | 4 | 4.44% |
| 尚无最终正式结果 | 2 | 2.22% |
| 可信且未达到 Match（`g < 0`） | 44 | 48.89% |
| 可信 Match-only（`0 <= g <= 0.1`） | 27 | 30.00% |
| 可信 Surpass-SOTA（`g > 0.1`） | 11 | 12.22% |
| 可信 Match-SOTA（包含 Surpass） | 38 | 42.22% |

当前主表有 `84` 个 Judge Valid，其中 `2` 个 case 的实例或关键指标不完整，不能作为可信
结果计入，因此严格完成数是 `84 - 2 = 82`。另有 `4` 个 Judge Invalid 和 `2` 个无正式
结果，所以当前总问题数为 `8`，即 `90 - 82 = 8`。当前严格口径为 `Match-SOTA=42.22%`、
`Surpass-SOTA=12.22%`。若只在 `82` 个严格可信完成的 case 内计算，Match-SOTA 为
`38/82=46.34%`；`42.22%` 则是官方固定的 `90` case 分母口径。

需要说明的是，严格可信数从 `79` 升到 `82` 主要来自 invalid-v3 合规重做把 11 个原
Judge Invalid case 转为 Valid，而这 11 个里只有 2 个达到 Match 及以上，9 个仍为负分。
换言之，此前那批 case 之所以被排除在分母外，是因为它们用不合规手段取得了较高分数；把
它们按合规方式重做并计入后，官方 90 分母口径从 `35.56%` 升至 `42.22%`，这才是真实水平
的更诚实反映。若以 2026-08-20 那次全量补判后的中间状态（`71` 严格可信、`35` Match-SOTA、
可信集内 `49.30%`）为参照，可信集内比例实际是下降的（`46.34%`），原因同样是新计入的 9 个
未 Match case 摊薄了分子占比。

当前必须从可信统计中剔除的 case：

| Case | 问题 | 当前动作 |
|---|---|---|
| `s41592-024-02580-4` | Judge Valid，但 6 个实例中 4 个隐藏 GT 目录缺失，另有 1 个实例输出键数量错误 | benchmark blocker；补齐官方 GT 前不计入 |
| `s41592-025-02870-5` | Judge Valid，但 `real_scrna_seq` 含 `partial_errors`，一个子集预测 0 个细胞而预期 4930 个 | 需要完整输出后重跑 |
| `s43588-025-00878-7` | 历史 Run 的 GTEx 全部分桶和聚合指标均为空，evaluator 返回 `issubclass() arg 1 must be a class` | 当前包无正式结果，重跑返修中 |
| `s43588-025-00872-z` | 无最终正式分数和最终 Judge | 重跑尚未闭环，不计入 |
| `s42256-022-00556-7` | invalid-v3 重做仍 Judge Invalid：融合 `frozen/` 下的预计算 `.npy` 预测产物 | 不计入；需重新设计合规方法 |
| `s42256-023-00636-2` | invalid-v3 重做仍 Judge Invalid：tanimoto 输出由随机等价 SMILES 填充 | 不计入；需重新设计合规方法 |
| `s42256-023-00712-7`、`s43588-024-00730-4` | invalid-v3 重跑未完成，无 judge 证据，保留原 GPT-5.5 Invalid 结论 | 不计入；需重投重跑 |

以下历史问题已经由完整补跑修复，当前可以计入 82 个可信结果（分数以主表为准，下列为
各自最新采用 Run 的值）：

- `s41592-025-02886-x`：完整覆盖 `mskcc_confocal` 和 `nih_ls`，invalid-v3 合规重做后
  `g=-75.615132`；
- `s42256-025-01003-z`：5/5 实例完整，invalid-v3 合规重做后 `g=-0.076714`；
- `s43588-024-00757-7`：invalid-v3 合规重做后 Judge 转 Valid，`g=-0.299699`；
- `s42256-023-00639-z` 和 `s42256-023-00654-0`：补齐原无结果 case，分别为
  `g=0.044115` 和 `g=-0.199075`，已合并到当前正式提交包。
- `s42256-023-00628-2`：2037-ID 输出契约修复后 3/3 实例完整，`g=-0.067133`。

`s42256-023-00712-7` 的正式 `g` 仍为修复 qvina/Meeko evaluator 后的 `-0.021930`（主表
此前误记为 `-1.000000`，2026-08-21 已按该 Run 的 `run_summary`/`promoted_best` 订正）；
但其当前采用 Run 的 GPT-5.5 结论为 Invalid，invalid-v3 重跑又未完成，故仍不计入可信结果。

## 2026-08-21 GPT-5.5 Invalid 重跑批次重判（invalid-v3）

本节记录 2026-08-20 提交的 `20260820-invalid-v3-deepseek-15` 批次的补判。该批针对当时
全部 `15` 个 Judge Invalid case 用 Claude Code + `deepseek-v4-pro` 做合规重做，`12` 个
Run 正常跑完（4–7 小时），但随 FMJob 收尾的 Judge 全部返回
`judge_error: no API key (set JUDGE_OPENAI_API_KEY or JUDGE_API_KEY)`，`19` 条 verdict
记录无一得到布尔结论，成果一直没有入账。

本次补判只复用这些 Run 已有的 judge 证据，不重新运行 Agent 或官方 evaluator。判官仍为
`gpt-5.5`，因此与既有 `73` 条结论口径一致、可比；改动只在于访问网关——原
`run_formal_gpt55_rejudge.py` 固定使用的 OneAPI 网关当时上游整体不可用（`gpt-5.5` 与
`gpt-5.6-terra` 均返回 `502 Upstream service temporarily unavailable`），改走可用网关的
同一 `gpt-5.5` 模型完成。补判脚本为
[`run_invalid_v3_rejudge.py`](../../../.famou/naturebench-judge-reruns/run_invalid_v3_rejudge.py)。

`s42256-024-00836-4` 的 `retry4` 在补判前刚写出 judge 证据，故实际判定 `13` 个而非 `12` 个。

| Case | 原正式 g | invalid-v3 最佳 g | 数值变化 | GPT-5.5 Judge | 采用结论 | Run |
|---|---:|---:|---:|---|---|---|
| `s41592-023-02148-8` | 0.255722 | **0.279872** | +0.024150 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-023-02148-8-20260820/) |
| `s41592-025-02854-5` | -0.883331 | -0.583355 | +0.299976 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-025-02854-5-20260820/) |
| `s41592-025-02886-x` | -12.363253 | -75.615132 | -63.251879 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-025-02886-x-20260820/) |
| `s41592-025-02893-y` | -199.799066 | -200.249463 | -0.450397 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-025-02893-y-20260820/) |
| `s41592-025-02926-6` | 0.337544 | -0.716138 | -1.053682 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s41592-025-02926-6-20260820/) |
| `s42256-022-00518-z` | 0.261313 | **0.201018** | -0.060295 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-022-00518-z-20260820/) |
| `s42256-022-00556-7` | 0.161643 | 0.184137 | +0.022494 | **Invalid (GPT-5.5)** | 不采用，保留原 Invalid | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-022-00556-7-20260820/) |
| `s42256-023-00636-2` | 0.020453 | -0.321796 | -0.342249 | **Invalid (GPT-5.5)** | 不采用，保留原 Invalid | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-023-00636-2-20260820/) |
| `s42256-023-00712-7` | -0.021930 | — | — | 未执行 | 重跑未完成，保留原 Invalid | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-023-00712-7-20260820/) |
| `s42256-024-00836-4` | -0.209367 | -0.238936 | -0.029569 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-024-00836-4-20260820-retry4/) |
| `s42256-024-00916-5` | -0.636999 | -0.476436 | +0.160563 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-024-00916-5-20260820/) |
| `s42256-025-01003-z` | -0.365484 | -0.076714 | +0.288770 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-025-01003-z-20260820/) |
| `s42256-025-01019-5` | -0.999816 | -0.989893 | +0.009923 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s42256-025-01019-5-20260820/) |
| `s43588-024-00730-4` | -119.777793 | — | — | 未执行 | 重跑未完成，保留原 Invalid | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s43588-024-00730-4-20260820/) |
| `s43588-024-00757-7` | -0.301818 | -0.299699 | +0.002119 | **Valid (GPT-5.5)** | 采用，覆盖正式结果 | [Run](../../../.famou/naturebench-runs/invalid-v3-claude-deepseek-s43588-024-00757-7-20260820/) |

`11` 个 Run 转为 GPT-5.5 Valid 并覆盖对应正式结果，`2` 个仍判 Invalid，`2` 个重跑未完成。
11 个采用的 Run 均通过数值完整性检查（`status=completed`、`outcome=best_candidate_found`、
分数有限、无 `error`/`partial_errors`）。仍 Invalid 的原因是：

- `s42256-022-00556-7`：工作区保留 `frozen/` 目录下按实例存放的 `.npy` 预测产物，提交代码显式融合这些冻结结果；
- `s42256-023-00636-2`：执行轨迹显示 tanimoto 输出由随机生成的等价 SMILES 填充，并经确定性校验可解析回目标分子。

数值层面 `6` 个提升、`5` 个下降，但只有 `2` 个达到 Match 及以上，`9` 个仍为负分。此前这
`15` 个 case 的较高分数多由不合规手段取得——例如 `s41592-025-02926-6` 原 `0.337544`
（Surpass）被判 Invalid，合规重做后为 `-0.716138`。因此本批的意义是把账做实，而非提分。

本批 verdict 保存在各 Run 的
`controller/naturebench_judge/gpt-5.5-rejudge-invalid-v3-20260821/judge_verdict.json`，
不覆盖旧的 `controller/judge_verdict.json`；批次汇总见
[`gpt-5.5-rejudge-invalid-v3-20260821`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-invalid-v3-20260821/)。

### 采用口径复核与提交包重建

结合本批结果，按「GPT-5.5 Valid 且分数最高」口径复核了全部 `90` 个 case（分析脚本
[`analyze_best_valid_runs.py`](../../../.famou/naturebench-judge-reruns/analyze_best_valid_runs.py)，
结果见 `best-valid-run-analysis-20260821.json`）。除本批 11 个外，仅
`s43588-025-00920-8` 需要改采 Run：其 Opus-5 Run（`0.013787`）高于原采用的
`code-refresh` Run（`-0.186163`），改采后新增一个 Match。该 Run 的两次 GPT-5.5 判定分歧
（`-strict` 为 Invalid、`-retry-providerfit` 为 Valid），按约定取 Valid。

同时发现官方提交包长期使用 `claude-sonnet-4-6` verdict（`87` Valid），从未纳入 GPT-5.5
补判，且其 Run 选择按 `finished_at` 最新自动决定，与主表人工采用记录在 `32` 个 case 上
不一致。为此给导出器新增 `--adopted-runs` 参数：给定采用清单时严格按清单选 Run 与 Judge
结论（不给则行为不变）。清单由
[`build_adopted_runs.py`](../../../.famou/naturebench-judge-reruns/build_adopted_runs.py)
从主表投影生成，判定理由取各 Run 自身的 GPT-5.5 verdict 原文。旧包归档为
`famou-glm52-official-pre-v3-20260821`，`famou-glm52-official-current` 按 GPT-5.5 口径
重建。

## 2026-08-20 GPT-5.5 全量正式结果补判

此前正式主表中尚未有 GPT-5.5 结论的当前采用 Run 已全部执行 post-hoc
Validity Judge。该批次只复用已有 Run 的 `README.md`、`data_description.md`、
SCORE_ATTEMPT 时间线、Agent 轨迹和最终 workspace，不重新运行 Agent 或官方 evaluator，
也不覆盖旧的 Sonnet `controller/judge_verdict.json`。

- 目标：当前主表中有正式 Run、且同一 Run 尚无 GPT-5.5 布尔 verdict 的 case；
- 结果：全部 `88` 个有正式 Run 的 case 现在都有 GPT-5.5 结论，其中 `73` 个 Valid、
  `15` 个 Invalid；另有 `2` 个 case 没有正式 Run；
- 严格可信口径：GPT-5.5 Valid 且通过数值完整性检查的 `71` 个 case；另有 `2` 个
  GPT-5.5 Valid 但数值/实例不完整的 case；
- 二次判定：`s42256-024-00815-9` 首轮 GPT-5.5 为 Invalid，第二次独立复核为
  Valid，按多次判定规则采用最新复核结论；
- 审计目录：[`gpt-5.5-formal-rejudge-20260820`](../../../.famou/naturebench-judge-reruns/gpt-5.5-formal-rejudge-20260820/)。

从本节开始，`CURRENT_RESULTS_CN.md` 的 Judge 列全部使用 GPT-5.5 口径；旧
`claude-sonnet-4-6` 和 `deepseek-v4-pro` verdict 仅作为历史审计证据，不再参与可信统计。

## 2026-08-19 GPT-5.5 Match/Surpass 全量重判

本批次对主表原有 38 个 Match/Surpass case 全部执行 NatureBench 官方 post-hoc
Validity Judge，模型改为 `gpt-5.5`。不重跑 Agent，不重跑 NatureBench 数值 evaluator，
原始分数和旧 `controller/judge_verdict.json` 均保留。最终 32 个 Valid、6 个 Invalid、
0 个基础设施错误；其中 Match 为 23/25 Valid，Surpass 为 9/13 Valid。

6 个 Invalid case 为：`s41592-023-02148-8`、`s41592-025-02926-6`、
`s42256-022-00518-z`、`s42256-022-00556-7`、`s42256-023-00636-2`、
`s42256-024-00815-9`。判定摘要和逐 case reason 见
[`gpt-5.5-rejudge-20260819/README_CN.md`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-20260819/README_CN.md)。

批次机器可读汇总：
[`summary.json`](../../../.famou/naturebench-judge-reruns/gpt-5.5-rejudge-20260819/summary.json)。
每个正式 run 下的独立新 verdict 位于
`controller/naturebench_judge/gpt-5.5-rejudge-20260819/judge_verdict.json`，不会覆盖旧
`controller/judge_verdict.json`。

## 2026-08-19 v2g Claude Code + DeepSeek V4 Pro 提升结果

本批 11 个 case 使用 Claude Code + `deepseek-v4-pro`，Idea/Implement 并发为
`2/2`，Evaluator 并发为 `4`。数值结果来自 NatureBench 官方 evaluator；本批新增结果
随后使用 `gpt-5.5` 官方 Validity Judge 复核。7 个相对原正式结果提升的 case 中，6 个
通过复核并覆盖当前正式结果，1 个因目标提取/公开答案查找被判 Invalid，不覆盖旧结果。

| Case | 原正式 g | v2g 最佳 g | 差值 | GPT-5.5 Judge | 采用结论 | Run |
|---|---:|---:|---:|---|---|---|
| `s41592-024-02523-z` | -0.181671 | -0.059667 | +0.122004 | Valid | 提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-02523-z-20260819/) |
| `s41592-025-02665-8` | -0.214212 | -0.000582 | +0.213630 | Valid | 提升，接近 Match | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-02665-8-20260819/) |
| `s41592-025-02854-5` | -0.883331 | -0.265813 | +0.617518 | **Invalid** | 不采用；公开 pseudobulk/eQTL 目标提取 | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-02854-5-20260819/) |
| `s42256-022-00541-0` | -0.261998 | -0.145824 | +0.116174 | Valid | 提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-00541-0-20260819/) |
| `s42256-023-00627-3` | -0.189847 | **0.041588** | +0.231435 | Valid | **新增 Match-SOTA** | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-00627-3-20260819/) |
| `s42256-024-00892-w` | -0.509220 | -0.033598 | +0.475622 | Valid | 提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-00892-w-20260819/) |
| `s42256-025-01042-6` | -0.565097 | -0.354403 | +0.210694 | Valid | 提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2g-claude-deepseek-01042-6-20260819/) |

其余 4 个 case 的本批结果为回退或没有有效候选，保留在本批 Run 目录和运行审计中，
不覆盖当前正式结果。所有 6 个采用的 Run 都有完整主实例、有限数值和无
`error`/`partial_errors` 的官方 evaluator 结果。

## 2026-08-20 Claude Code + Claude Opus 5 对照批次

本批针对 8 个当前可信但未达到 Match 的 case，使用 Claude Code + `claude-opus-5`，
Idea/Implement/Evaluator 并发为 `2/2/4`，每个任务独立 Run。下表只记录官方 evaluator
产生的数值结果，不将其提前写入当前正式主表。首次随 FMJob 收尾时因 Trusted Evaluator
没有收到 `JUDGE_OPENAI_API_KEY`/`JUDGE_API_KEY` 而返回 Judge 基础设施错误；随后从已验证
的 OneAPI 配置补跑 GPT-5.5，并对大请求使用官方证据的压缩上下文策略。

| Case | 原正式 g | Opus-5 最佳 g | 数值变化 | 数值结论 | GPT-5.5 Judge | Run |
|---|---:|---:|---:|---|---|---|
| `s41592-023-01940-w` | -1.146056 | **0.599386** | +1.745442 | 数值 Surpass | **Invalid (GPT-5.5)** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-01940-w-20260820/) |
| `s41592-025-02820-1` | -0.958356 | -0.445322 | +0.513034 | 数值未 Match | **Valid (GPT-5.5)** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-02820-1-20260820/) |
| `s42256-022-00526-z` | -0.865006 | -0.091079 | +0.773926 | 数值未 Match | **Valid (GPT-5.5)** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-00526-z-20260820/) |
| `s42256-023-00654-0` | -0.233053 | -0.199075 | +0.033978 | 数值未 Match | **Valid (GPT-5.5)** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-00654-0-20260820/) |
| `s42256-023-00712-7` | -1.000000 | — | — | 无有效候选 | 未执行 | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-00712-7-20260820/) |
| `s42256-024-00790-1` | -0.094688 | **0.020292** | +0.114981 | 数值 Match | **Valid (GPT-5.5)** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-00790-1-20260820/) |
| `s42256-025-01010-0` | -1.424118 | -1.098003 | +0.326116 | 数值未 Match | **Valid (GPT-5.5)** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-01010-0-20260820/) |
| `s43588-025-00920-8` | -0.186163 | **0.013787** | +0.199951 | 数值 Match | **判定分歧，取 Valid** | [Run](../../../.famou/naturebench-runs/rerun-v3-claude-opus-00920-8-20260820/) |

本批 7 个 Run 产生有限数值，3 个数值上达到 Match/Surpass；其中 5 个通过 GPT-5.5
Validity Judge，`s41592-023-01940-w` Invalid，`s43588-025-00920-8` 两次判定分歧，
`s42256-023-00712-7` 没有有效候选。

- `s41592-023-01940-w`：从既有“certified anchor”预测和官方 MAE/SHAs 出发，结合 evaluator 反馈手工调整 delta，属于分数反馈利用；Invalid，不采用。
- `s43588-025-00920-8`：`-strict` 批次判 Invalid，理由是加载既有预测向量并使用官方测试集 R2/RMSE 反馈估计误差协方差、优化 blend 权重；`-retry-providerfit` 批次判 Valid，理由是 `aho_main` 确实由 `aho_te.py` 训练（OOF target encoding + LightGBM），只有五个 `cpa_*` 文件来自早前评测输出的凸组合。按「判定分歧取 Valid」的约定，2026-08-21 复核时采用该 Run 并新增一个 Match，详见上方 invalid-v3 节。

补测 verdict 分别保存在各 Run 的
`controller/naturebench_judge/gpt-5.5-opus-rejudge-20260820-compact/` 或
`...-compact-r2/`、`...-strict/` 目录中；压缩策略只减少提交给 Judge 的轨迹和源文件上下文，不改变候选代码或 evaluator 数值结果。

## 2026-08-17/18 Claude Code + DeepSeek V4 Pro 重跑

本批共核对 10 个重跑结果，配置为 Claude Code + `deepseek-v4-pro`。所有最佳候选均完成
官方数值评测、覆盖全部主实例且最终 Validity Judge 为 `valid=true`。其中 8 个相对当前
正式结果提升并进入主表，2 个回退结果只保留作实验记录，不覆盖旧正式最佳。

| Case | 更新前正式 g | 本批最佳 g | 差值 | 采用结论 | Run |
|---|---:|---:|---:|---|---|
| `s41592-025-02926-6` | -1.000000（不可信） | 0.337544 | +1.337544 | 新增 Surpass；4/4 实例完整 | [Run](../../../.famou/naturebench-runs/rerun-final-v15-claude-deepseek-s02926-20260817/) |
| `s42256-023-00628-2` | -0.348310（不可信） | -0.067133 | +0.281177 | 修复为可信结果，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-final-v18-claude-deepseek-s00628-20260817/) |
| `s42256-022-00518-z` | -0.104211 | 0.261313 | +0.365524 | 新增 Surpass | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-00518-20260818/) |
| `s41592-023-02035-2` | -0.048132 | 0.001451 | +0.049583 | 新增 Match | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-02035-20260818/) |
| `s42256-022-00534-z` | -0.001537 | 0.000434 | +0.001971 | 新增 Match | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-00534-20260818/) |
| `s41467-025-64512-w` | -0.099760 | -0.026591 | +0.073169 | 提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-64512-20260818/) |
| `s42256-025-01003-z` | -1.495937 | -0.365484 | +1.130453 | 提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-01003-20260818/) |
| `s41592-025-02886-x` | -67.354972 | -12.363253 | +54.991719 | 大幅提升，仍未 Match | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-02886-20260818/) |
| `s41592-025-02662-x` | -0.077484 | -0.097490 | -0.020006 | 回退；保留旧正式最佳 | [Run](../../../.famou/naturebench-runs/rerun-v2c-claude-deepseek-02662-20260818/) |
| `s42256-024-00836-4` | -0.209367 | -0.212826 | -0.003459 | 回退；保留旧正式最佳 | [Run](../../../.famou/naturebench-runs/rerun-v2e-claude-deepseek-00836-20260818/) |

本批带来 2 个新增 Match 和 2 个新增 Surpass。`s02926`、`s00628` 的旧结果从“不可信”
转为严格可信，因此严格可信完成数从 83 增至 85；当前无 NatureBench FMJob 在运行。

## 2026-08-13 old-policy-search-v4-2x2x5：Judge Valid 提升结果

本节只记录本批次相对提交前历史最佳分数确实提升、且最终 Validity Judge 返回严格
`valid=true` 的结果。当前提交包已统一合并 old-policy 与 Search-v2 的有效结果；v10
目录仅作为历史审计版本。

| Case | 历史最佳 | 本批次最佳 | 提升 | 结果 | Run |
|---|---:|---:|---:|---|---|
| `s41592-024-02191-z` | -0.373177 | -0.168248 | +0.204929 | 未达到 Match | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s41592-024-02191-z-20260813/) |
| `s41592-024-02257-y` | -0.334106 | -0.299714 | +0.034391 | 未达到 Match | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s41592-024-02257-y-20260813/) |
| `s41592-024-02316-4` | 0.028785 | 0.030928 | +0.002143 | Match-SOTA（刷新） | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s41592-024-02316-4-20260813/) |
| `s41592-025-02826-9` | -0.226803 | -0.178774 | +0.048029 | 未达到 Match | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s41592-025-02826-9-20260813/) |
| `s42256-022-00518-z` | -0.182478 | -0.104211 | +0.078267 | 未达到 Match | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s42256-022-00518-z-20260813/) |
| `s42256-022-00534-z` | -0.001775 | -0.001537 | +0.000238 | 未达到 Match | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s42256-022-00534-z-20260813/) |
| `s43588-024-00698-1` | -0.005174 | 0.002358 | +0.007532 | 新 Match-SOTA | [Run](../../../.famou/naturebench-runs/old-policy-search-v4-2x2x5-s43588-024-00698-1-20260813/) |

排除项：`s42256-024-00838-2` 的 Judge 请求返回 HTTP 502，结论为 `valid=null`，因此
仍保留 v9 结果；`s41592-025-02893-y` 的 `-321.675` 来自已确认的 evaluator 坐标单位
问题，不是可用的 benchmark 结果，也不进入本次更新。批次汇总为 7 个有效提升、1 个
新增 Match-SOTA、1 个已有 Match-SOTA 刷新、0 个新增 Surpass-SOTA。

## 2026-08-11 历史合并快照（v9）

历史正式提交产物为
[`famou-glm52-reviewed-20260811-v9`](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260811-v9/)。
它从全部本地 Run 中为每个 case 选择最新的“有限 `best_score` + 严格布尔 Validity Judge”
结果；invalid Run 也按官方格式保留，但不计入 Completion Rate。官方校验结果为
`0 warning / 0 error`，计分预览见
[`score_report.json`](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260811-v9/score_report.json)。

| 统计项 | 数量 | 占全部 90 个 task |
|---|---:|---:|
| 已有官方数值分数 | 86 | 95.56% |
| Judge=valid | 85 | 94.44% |
| Judge=invalid | 1 | 1.11% |
| 未达到 Match（valid 且 `g < 0`） | 57 | 63.33% |
| Match-only（valid 且 `0 <= g <= 0.1`） | 17 | 18.89% |
| Surpass-SOTA（valid 且 `g > 0.1`） | 11 | 12.22% |
| 尚无数值分数 | 4 | 4.44% |

官方预览为 `Score Rate=95.56%`、`Completion Rate=94.44%`、
`Match-SOTA=31.11%`、`Surpass-SOTA=12.22%`。官方 `Match-SOTA` 包含 Surpass，
因此共有 28 个 valid task 达到 Match 或更高水平。v9 相比 v8 将
`s43588-024-00733-1` 从 evaluator 错误分 `-1` 修复为 `0.004987`，并纳入新完成的
`s41592-025-02926-6`；后者当前 `g=-1`，Judge 虽为 Valid，但 12 次评分的四个实例都发生
H5AD `encoding_type=null` 兼容错误，不能作为方法结论。

## 2026-08-11 Search-v2 重跑结果（已合并到当前正式提交包）

本节记录 v9 生成后完成的自主搜索重跑，完整精度和 Run ID 见
[`RERUN_COMPARISON_20260811.csv`](RERUN_COMPARISON_20260811.csv)。这里的“提升/回退”
只比较 v9 当时选中的分数与本次重跑分数，不覆盖 v9，也不把基础设施失败解释成方法失败。

15 个 Search-v2 任务中，13 个正常完成且 Validity Judge 均为 `valid`，2 个未进入
Task 入口。13 个有效对比中有 9 个提升、4 个回退；4 个达到 Match-SOTA，没有
Surpass-SOTA。这 4 个有效 Match 结果已经合并到当前正式提交包；其中
`s41592-024-02316-4` 采用更高的 old-policy 分数 `0.030928`，Search-v2 分数
`0.028785` 仍保留在本节作为实验记录。

| Case | v9 分数 | 重跑分数 | 差值 | 对比 | 结果 | Run |
|---|---:|---:|---:|---|---|---|
| `s41467-025-64512-w` | -0.099760 | -0.100050 | -0.000290 | 回退 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41467-025-64512-w/) |
| `s41467-025-65557-7` | -0.017470 | 0.023407 | +0.040877 | 提升 | Match-SOTA | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41467-025-65557-7/) |
| `s41587-024-02428-4` | -0.065649 | -0.151769 | -0.086120 | 回退 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41587-024-02428-4/) |
| `s41592-023-02035-2` | -0.048132 | -0.003958 | +0.044174 | 提升 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-023-02035-2/) |
| `s41592-024-02316-4` | -0.011249 | 0.028785 | +0.040034 | 提升 | Match-SOTA | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-024-02316-4/) |
| `s41592-025-02886-x` | -67.354972 | -60.721113 | +6.633859 | 提升 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-025-02886-x/) |
| `s41592-025-02983-x` | -0.020552 | 0.015539 | +0.036091 | 提升 | Match-SOTA | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-025-02983-x/) |
| `s42256-022-00534-z` | -0.025721 | -0.001775 | +0.023946 | 提升 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-022-00534-z/) |
| `s42256-024-00795-w` | -0.060859 | -0.098318 | -0.037459 | 回退 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-024-00795-w/) |
| `s42256-024-00815-9` | -0.491554 | 0.023436 | +0.514990 | 提升 | Match-SOTA | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-024-00815-9/) |
| `s42256-025-01003-z` | -1.495937 | -1.280602 | +0.215335 | 提升 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-025-01003-z/) |
| `s43588-024-00698-1` | -0.026021 | -0.005174 | +0.020847 | 提升 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s43588-024-00698-1/) |
| `s43588-024-00716-2` | -0.089730 | -0.211417 | -0.121687 | 回退 | 未达到 Match | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s43588-024-00716-2/) |

以下两个 Search-v2 目录只有公开题面，没有 `research_state.yaml`、Agent 轨迹、ExpBank
或正式评测，不纳入提升/回退统计，后续需要重新提交 fm-job：

- `s41592-025-02926-6`；
- `s42256-023-00628-2`。

### v9 后完成的缺失 Case 重跑

| Case | 重跑分数 | Judge | 结果 | Run |
|---|---:|---|---|---|
| `s42256-023-00639-z` | 0.044115 | valid | Match-SOTA | [Run](../../../.famou/naturebench-runs/rerun2-s42256-023-00639-z-20260811-102654/) |
| `s42256-023-00654-0` | -0.233053 | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/rerun2-s42256-023-00654-0-20260811-104020/) |
| `s43588-025-00878-7` | -1.000000 | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/rerun3-s43588-025-00878-7-20260811-1130/) |

这两个有效 Run 已在当前正式提交包中导出，不需要再次执行实验。`s43588-025-00878-7`
的历史结果仍不可信；`s43588-025-00872-z` 仍无正式评测：Implement 启动约 20 分钟后进程突然
停止，没有 Agent 错误、canonical 结果、Evaluator 调用或正常收尾证据，暂归类为外部
Pod/进程异常中断，需要重新运行，不能形成方法结论。

### Search-v2 是否有效

配对统计证据已单独保存到
[`SEARCH_V2_EVIDENCE_20260812.json`](SEARCH_V2_EVIDENCE_20260812.json)，只使用 13 个
同时具有 v9 分数和 Search-v2 分数的 case：

- 9 个提升、4 个回退，提升比例为 `69.23%`；
- 分数增量中位数为 `+0.03609`，中位数绝对增量为 `0.04088`；
- 按当前 Match 阈值，Match 数从 `0/13` 增加到 `4/13`；
- 没有 case 达到 Surpass-SOTA；
- 均值增量为 `+0.56343`，但受到一个 `+6.63386` 极端 case 影响，不能单独作为证据；
- 13 个配对 case 的单侧符号检验 `p=0.1334`，当前样本量下不能声称统计显著的普遍提升。

因此，Search-v2 可以被描述为“在当前样本上有方向性收益、但具有任务依赖性”：它在
多数配对任务上改善了分数，并将 4 个任务推过 Match 阈值，但仍有 4 个任务回退，不能
宣称对 NatureBench 普遍有效。后续应重点分析回退 case 的 idea 分布、资源消耗和
Evaluator 失败类型，再决定是否扩大 Search-v2 的默认策略。

### 2026-08-12 必须重跑任务状态

第一次提交的三个 Job 因系统代码缺少 `experience_bank_root` 导入，在 Agent 启动后
触发 `NameError`，属于 Famou 基础设施故障，不计为任务结果。修复并通过 Loop 测试后，
已使用新的 Run ID 重新提交，目前三个 Job 均为 `Running`：

| Case | 官方档位 | 新 Run | 当前状态 |
|---|---|---|---|
| `s43588-024-00757-7` | `gpu_low` | `required-rerun-s43588-024-00757-7-20260812-2` | Running |
| `s43588-025-00872-z` | `gpu_high` | `required-rerun-s43588-025-00872-z-20260812-2` | Running |
| `s41592-025-02926-6` | `gpu_low` | `required-rerun-s41592-025-02926-6-20260812-2` | Running |

### v8 未达到 SOTA 的统一诊断

本节以 `v9/results.csv` 中 `Judge=valid` 且 `g < 0` 的 57 个 case 为唯一口径，并逐个核对
`raw-results/<case_id>/submissions.jsonl`、最佳 `workspace/method_manifest.json` 和官方
evaluator 返回的分项指标。它取代下文基于 `v5/v7` 的历史诊断；补数据前的旧结论不能覆盖
这里的新 Run 证据。

Validity Judge 的 `valid` 只表示候选确实由公开数据上的科研/训练流程产生，不表示每个官方
实例都成功评分。因此必须先检查 `raw_scores` 中的 `error`、`null` 和实例覆盖率，再讨论算法
能力。当前分类如下：

| 类别 | 数量 | 解释 | 默认处置 |
|---|---:|---|---|
| 当前结果不可直接归因 | 7 | evaluator 环境错误、隐藏 GT 不完整、候选缺实例，或不完整候选被错误选为最佳 | 先修设施/产物选择，再重评或重跑 |
| 近 SOTA | 13 | `-0.1 <= g < 0`，产物完整且分项可解释 | 针对拖后腿实例做低成本 refine |
| 明确方法/训练差距 | 37 | 产物完整，但官方分项显示模型、优化或实现明显落后 | 修改组件或方法范式后再跑，原配置重复运行价值低 |

#### 当前结果不可直接归因的 7 个 case

| Case | 当前 `g` | 确定性证据 | 根因与处置 |
|---|---:|---|---|
| `s41592-024-02580-4` | `-0.997676` | 6 个实例中，`livecell/plantseg_ovules/lucchi/vnc` 的隐藏 GT 目录不存在；复核官方 task 包后确认这 4 份 GT 在上游包内即缺失，不是本地下载截断。`deepbacs` 还存在 `35` 个预测对 `4` 个 GT 的 key 数量不匹配。 | 标记为上游 benchmark blocker，当前不重跑 Agent。待官方补齐 4 份隐藏 GT 后重评；届时若只有 `deepbacs` 仍不合规，再针对输出映射修复。当前分数不作分割方法结论。 |
| `s41592-025-02886-x` | `-67.354972` | 当前最佳 attempt 的 `nih_ls` 评测失败并被记为 `-1`；完整的 attempt 6 实际为 `-108.684430`。缺失实例反而让聚合分更高。 | Candidate 输出/折叠验证失败叠加最佳选择策略缺陷。改为“实例完整优先、分数次优先”，先选择完整 attempt 6；方法本身的 FP/FN 仍很差，修复跟踪产物后再重跑。 |
| `s41592-025-02926-6` | `-1.000000` | 12 次提交的四个实例都返回 `No read method registered for IOSpec(encoding_type='null', ...)`，PCC/SSIM/CMD 全部为空；旧评分层仍将聚合 `-1` 记为成功。 | Candidate H5AD 输出与官方 evaluator 的 anndata 读取契约不兼容。需要新版严格 evaluator 把实例级错误回传给 ImplementActor，修复 writer 后整任务重跑；已提交新 Run。 |
| `s42256-023-00628-2` | `-0.348310` | 11 次提交的 `band_gap` 均不完整；最佳提交预期 `2037` 个结构，却产生 `64485` 行并漏掉 `90` 个结构。另两个实例分别为 `+0.0204/-0.0654`。 | MOF ID 展开、去重和输出契约错误，聚合分不是三任务算法结论。增加严格 ID 集合校验，补齐 `band_gap` 后重跑；已有氢吸附/扩散分项可作为局部证据保留。 |
| `s42256-023-00712-7` | `-1.000000` | 9 次提交的 QED/SA/Diversity 均正常，但 Vina 全部为 `null`。逐阶段诊断确认有两个 evaluator 环境错误：随任务提供的 `qvina02` 为 `0644`；修复执行位后，镜像中的 `meeko==0.6.0` wheel 又缺少 `data/params/ad4_types.json`，`MoleculePreparation()` 初始化失败。 | 不重跑 Agent。可信侧已将 `qvina02` 修为 `0700`，并使用固化的 `meeko==0.5.1` 兼容 wheel；单分子官方链路已得到 `-9.3 kcal/mol`。9 个现有 Candidate 正以 3 并发重评，完成后补跑 Judge。 |
| `s42256-024-00815-9` | `-0.491554` | 最佳候选仅输出 `zinc/casf`，两者 improvement 为 `-0.0164/+0.0502`；`geom/pockets` 的 `output.smi` 均不存在并各记 `-1`。 | Candidate 实例遍历/收尾不完整。先增加四实例输出断言，再让原 Actor 修复或重跑；当前聚合分不能说明 linker 方法整体落后。 |
| `s42256-025-01003-z` | `-1.495937` | 当前最佳候选的 `custom_nanopore` 预期 `109976` 行、实际 `199976` 行，被记为 `-1`；完整候选存在，但最佳完整 attempt 10 为 `-2.712282`。 | 同时存在输出数量错误和“失败封顶为 `-1`”导致的不完整候选择优。先按完整性重选/重评；Illumina 已较接近，Nanopore failure rate 仍高，修复契约后需要替换 Nanopore 共识算法。 |

这 7 个 case 还暴露了统一评分层的一个规则缺口：官方进程返回 `valid=true` 不足以判定候选
完整。候选选择必须同时检查“预期实例全部存在、关键指标有限、无实例级 error”，不完整候选
不能因为失败值被封顶而击败完整候选。

原清单中的 `s43588-024-00733-1` 已从该类别移出：NumPy pickle 兼容修复后，8 个历史
Candidate 均完成重评，最佳 `g=0.004987`，官方 Judge 为 Valid，结果等级为 Match-only。

#### 近 SOTA 的 13 个 case

| Case | `g` | 主要差距 | 建议的下一轮 |
|---|---:|---|---|
| `s41467-025-64512-w` | `-0.099760` | 8 个 PPI 场景中 E. coli/Bernett 已略超参考线；`mutation_effect=-0.3181` 和 virus-human/cross-species 是主要拖累。 | 保留 BilinearPPI 主干，只重构 mutation-effect 的位点表征、校准和 domain adaptation，不再平均增加所有场景模型容量。 |
| `s41467-025-65557-7` | `-0.017470` | 4 个 SMLM 场景中 1 个为正，其余仅 `-0.0278` 至 `-0.0341`；固定密度阈值对 blinking/椭圆簇略过拟合。 | leave-one-FOV-out 选参，并消融 SNN、持久性合并和 Mahalanobis 边界。 |
| `s41587-024-02428-4` | `-0.065649` | AUROC=`.733` 尚可，但 F1=`.064`、Recall=`.034`；逐残基 ESM+LightGBM 缺少 partner-specific 结构交互。 | 加入成对 cross-attention、溶剂暴露/界面邻域特征，分别优化 AUROC 与阈值指标。 |
| `s41592-023-02035-2` | `-0.048132` | pancreas/PBMC 接近参考线，lung Weighted/Macro-F1=`.659/.519`，是主要域偏移。 | 只针对 lung 和 PBMC 长尾类做 query adaptation、类别重加权与混淆矩阵分析。 |
| `s41592-024-02316-4` | `-0.011249` | 5 个模拟实例 ARI 均为 `.954-.963`，每项只差 `.007-.017`。 | 对 WNN 权重、邻居数、平滑步数和 GMM 初始化做小网格搜索，不换方法。 |
| `s41592-025-02662-x` | `-0.077484` | 9 个实例已完整；synthetic_3d 为 `+0.0673`，hybiss=`-0.2852`、dna_fish=`-0.1618`、terra=`-0.1320` 是主要差距。 | 保留 Attention U-Net，按成像平台学习阈值/尺度与背景模型，优先 refine hybiss、dna_fish、terra。 |
| `s41592-025-02870-5` | `-0.036581` | 重跑后两个实例均完整；real scRNA 为 `+0.0233`，simulated DLA tree 为 `-0.0965`。 | 保留真实数据分支，只针对模拟树的分支拓扑、根叶锚点和 milestone graph 做结构消融。 |
| `s41592-025-02983-x` | `-0.020552` | junction AUC=`.924`，三行为 Pearson=`.779/.906/.807`，差距均较小。 | embryo-level CV 下消融 tension、组织位置、加速度和 ensemble，继续 refine。 |
| `s42256-022-00534-z` | `-0.025721` | 三个 pancreas cohort Macro-F1=`.956-.989`；Xin 仅 `.730`。 | 增加 cohort-aware normalization/域适配，单独处理 Xin，不重构已经稳定的三个分支。 |
| `s42256-024-00790-1` | `-0.094688` | XRD 去噪 PSNR=`32.60`、MS-SSIM=`.939`、MAE=`.0172`，产物完整但仍略低参考线。 | 使用 peak-preserving/频域损失和强度标定，围绕现有 NAFNet 做小范围训练策略 refine。 |
| `s42256-024-00795-w` | `-0.060859` | Swiss-Prot MFO/CCO 较近；Swiss-Prot BPO=`-0.1249` 是最大单项差距，neXtProt 两项约 `-0.063`。 | 强化 GO 层级一致性和 BPO 长尾标签传播，保留已有 ESM2 kNN/MLP ensemble。 |
| `s43588-024-00698-1` | `-0.026021` | 7 个扰动集仅 k562-essential 为正；k562-gw PR-AUC=`.057`、perturb-cite Pearson=`.429`。 | 分离 dataset-specific head，按分类/回归和单/双基因扰动做分组训练，减少共享主干负迁移。 |
| `s43588-024-00716-2` | `-0.089730` | s669/s571 Spearman=`.545/.473`，s571 RMSE=`9.288`；序列可接受性不能充分表示三维稳定性变化。 | 加结构接触、溶剂暴露和 assay-specific 校准，采用按蛋白分组 CV 与 ranking loss。 |

“近 SOTA”只描述聚合分数，不保证简单调参就能过线。按当前分项证据，进一步分为：

- **较可能通过定向 refine 解决（6 个）**：`s41467-025-65557-7`、
  `s41592-024-02316-4`、`s41592-025-02870-5`、`s41592-025-02983-x`、
  `s42256-022-00534-z`、`s43588-024-00698-1`。这些 case 的差距约为 `.011-.037`，
  且主要是少量超参数、单一数据域或单一分支拖累。
- **有机会，但需要组件级 refine（4 个）**：`s41592-023-02035-2`、
  `s41592-025-02662-x`、`s42256-024-00790-1`、`s42256-024-00795-w`。它们不能只做
  学习率/epoch 调整，需要分别重做 lung 域适配、密集 spot 后处理、峰形保持损失或 GO-BPO
  层级分支。
- **不应预期靠普通 refine 解决（3 个）**：`s41467-025-64512-w` 的 mutation-effect
  单项为 `-0.3181`；`s41587-024-02428-4` 缺少 partner-specific 结构交互；
  `s43588-024-00716-2` 缺少三维稳定性特征。三者虽然聚合 `g` 在 `-0.1` 内，但需要 New
  Idea、switch 或 fuse，而不是沿当前实现继续微调。

这 13 个结果也不是同一版 Search Policy 产生的。`pairwise_improve` 于 2026-08-10 接入，
只有以下 3 个当前最佳 Run 开启了“当前 Refine + 一条 New Idea 同时交给 ImplementAgent，
由其选择 `refine/switch/fuse`”的策略：

| Case | 最佳 ExpBank | 最佳候选的实际选择 | 结论 |
|---|---:|---|---|
| `s41592-025-02662-x` | `0003` | `switch` | 比较当前 U-Net refine 与新 Attention U-Net/Wavelet Idea 后，切换到新 Idea；不是纯 refine。 |
| `s41592-025-02870-5` | `0013` | `switch` | 当前 MST refine 连续退化后，切换到 root/leaf milestone anchoring 新 Idea。 |
| `s42256-024-00790-1` | `0008` | `refine` | 比较 NAFNet 与队列中的 Restormer Idea 后，基于历史分数选择继续训练 NAFNet。 |

其余 10 个近 SOTA 结果均来自 2026-08-07/08 的旧 Run：
`s41467-025-64512-w`、`s41467-025-65557-7`、`s41587-024-02428-4`、
`s41592-023-02035-2`、`s41592-024-02316-4`、`s41592-025-02983-x`、
`s42256-022-00534-z`、`s42256-024-00795-w`、`s43588-024-00698-1`、
`s43588-024-00716-2`。旧版 continuation 只向 ImplementAgent 提供当前方案和 evaluator 反馈；
New Idea 由另一条队列独立消费，不会在同一回合中做 pairwise 比较。因此，这 10 个使用新
Search Policy 重跑的价值高于 3 个已经覆盖新策略的 case，但是否过线仍只能由官方 evaluator
确认。

#### 2026-08-11 Search Policy 重跑与异常修复状态

本批新 Run 统一使用 `glm-5.2`、Idea/Implement/Evaluator 并发 `1/2/3`、Idea/Evaluation
队列容量 `3/3`、4 小时研究预算，并开启 `pairwise_improve` 和 time-aware Idea ranking。
4 小时只停止新的 Idea/Implement admission；截止前已经进入 Evaluation Queue 的 Candidate
仍会完成 canonical run 和官方评分。

| Case | 类型 | 当前动作 | 产物入口 | 当前状态 |
|---|---|---|---|---|
| `s41467-025-64512-w` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41467-025-64512-w/) | fm-job 已提交，等待 GPU |
| `s41467-025-65557-7` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41467-025-65557-7/) | fm-job 已提交，等待 GPU |
| `s41587-024-02428-4` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41587-024-02428-4/) | fm-job 已提交，等待 GPU |
| `s41592-023-02035-2` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-023-02035-2/) | fm-job 已提交，等待 GPU |
| `s41592-024-02316-4` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-024-02316-4/) | fm-job 已提交，等待 GPU |
| `s41592-025-02983-x` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-025-02983-x/) | 已分配 GPU，Controller 已启动 |
| `s42256-022-00534-z` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-022-00534-z/) | fm-job 已提交，等待 GPU |
| `s42256-024-00795-w` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-024-00795-w/) | fm-job 已提交，等待 GPU |
| `s43588-024-00698-1` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s43588-024-00698-1/) | fm-job 已提交，等待 GPU |
| `s43588-024-00716-2` | 旧策略近 SOTA | 新策略整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s43588-024-00716-2/) | fm-job 已提交，等待 GPU |
| `s41592-025-02886-x` | 结果不可归因 | 修复完整性选择后整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s41592-025-02886-x/) | fm-job 已提交，等待 GPU |
| `s41592-025-02926-6` | 新完成结果不可归因 | 修复 H5AD writer 契约后整任务重跑 | [Run](../../../.famou/naturebench-runs/bio-all-v3-s41592-025-02926-6-glm52-20260808-175527/reruns/20260811-search-v2-s41592-025-02926-6/) | fm-job 已提交，等待 GPU |
| `s42256-024-00815-9` | 结果不可归因 | 强制四实例输出后整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-024-00815-9/) | 已分配 GPU；3 个 Candidate 已提交，首个 canonical 超时已回传 Actor，另 2 个评测中 |
| `s42256-025-01003-z` | 结果不可归因 | 修复输出数量契约后整任务重跑 | [Run](../../../.famou/naturebench-runs/20260811-search-v2-s42256-025-01003-z/) | 已分配 GPU，首个 ImplementActor 运行中 |
| `s42256-023-00628-2` | 结果不可归因 | 复用只读题面快照，整任务重跑 | [Run](../../../.famou/naturebench-runs/nb-final-s42256-023-00628-2-glm52-20260809-all-remaining-v1/reruns/20260811-search-v2-s42256-023-00628-2/) | fm-job 已提交，等待 GPU |
| `s43588-024-00733-1` | evaluator 环境错误 | 直接重评 8 个历史 Candidate 并补 Judge | [Run](../../../.famou/naturebench-runs/bio-all-v3-s43588-024-00733-1-glm52-20260808-175527/) | 已完成，`g=0.004987`，Judge Valid |
| `s42256-023-00712-7` | evaluator 环境错误 | 修复 qvina/Meeko 后重评 9 个历史 Candidate | [Run](../../../.famou/naturebench-runs/nb-final-s42256-023-00712-7-glm52-20260809-all-remaining-v1/) | 第二次可信重评已成功，结果与 Judge 证据已落盘 |
| `s41592-024-02580-4` | 官方隐藏 GT 不完整 | 不重跑，等待上游补齐 evaluator 数据 | [Run](../../../.famou/naturebench-runs/required-rerun-s41592-024-02580-4-20260810-2100/) | benchmark blocker |

截至 2026-08-11 15:37，本批共提交 `15` 个 GPU Run（10 个旧策略近 SOTA、5 个必须由
Agent 修复的不可归因 case）：`3` 个已经分配 GPU 并运行，`12` 个等待 GPU。另有
`s42256-023-00712-7` 的 CPU 可信重评独立运行，不占上述 GPU Run；其 9 个历史 Candidate
按 3 并发执行完整 docking，单个 Candidate 接近 50 分钟时，在首批结果落盘前日志长时间
没有进度事件属于预期行为。

截至 2026-08-11 17:38 的 fm-job 控制面快照，15 个计划 GPU Run 仍全部在控制面中，
没有漏提：`9` 个已经分配 Pod/GPU，`6` 个处于 `Running` 但尚无 Pod IP 的资源等待状态。

- 已分配：`s41592-023-02035-2`、`s41592-025-02886-x`、
  `s41592-025-02983-x`、`s42256-022-00534-z`、`s42256-024-00795-w`、
  `s42256-024-00815-9`、`s42256-025-01003-z`、`s43588-024-00698-1`、
  `s43588-024-00716-2`；
- 等待资源：`s41467-025-64512-w`、`s41467-025-65557-7`、
  `s41587-024-02428-4`、`s41592-024-02316-4`、`s41592-025-02926-6`、
  `s42256-023-00628-2`。

两个 evaluator/Judge 修复任务也已结束：`s43588-024-00733-1` Judge 成功，
`s42256-023-00712-7` 第二次可信重评成功。需要单独保留的未闭环项是
`s43588-025-00872-z`：256 GiB 重跑 Job 已提交但最终失败，Run 停在首个 Implement
激活且没有正式 evaluator 结果，因此“已提交”不能视为“已解决”；下一次提交前仍需确认
Pod 终止原因。`s41592-024-02580-4` 因官方隐藏 GT 不完整，按计划不提交重跑。

`s42256-023-00712-7` 的依赖 wheel、逐 Candidate 重评、修复前快照和最终报告统一保存在
该 Run 的 `trusted/repairs/`；单分子逐阶段排障可使用
[`diagnose_docking.py`](../../../famou_scientist/loop/examples/naturebench/diagnose_docking.py)。

#### 产物完整但仍明显落后的 37 个 case

下表中的“重跑”均指**先完成所列方法变化，再启动新 Run**；不建议用相同代码和相同搜索
空间机械重跑。

| Case | `g` | 官方分项与根因 | 下一步 |
|---|---:|---|---|
| `s41467-025-63418-x` | `-0.240325` | hippocampus/breast-cancer ARI=`.495/.320`；固定空间图与生物图在模拟乳腺场景传播了错误邻域。 | 改为可学习 modality/edge gating 和双分支图融合，分实例做图边消融。 |
| `s41587-024-02414-w` | `-0.113559` | promoter Pearson/Spearman=`.729/.792`；Idea 声称 pairwise-difference loss，实际最佳代码仍以 SmoothL1 为主，关键设想未落地。 | 先修复 Idea/Implement 一致性，真正加入 SNV/motif pair 差分目标，再比较普通序列和 pair 子集。 |
| `s41587-025-02585-0` | `-0.509462` | CODEX 三实例 F1=`.486/.606/.339`，大图最差；线性 FISTA 解混无法表达 5→22 欠定压缩中的非线性串扰和空间先验。 | 换监督卷积/生成式解混网络，使用稀疏支持集损失和大图分块训练。 |
| `s41587-025-02654-4` | `-0.464847` | 单域/多域 TM-score=`.514/.363`；单序列 ESMFold recycle 无法补足 MSA/template 和多域相对取向。 | 引入 MSA/template 或更强结构模型，并单独做 domain assembly/refinement。 |
| `s41592-022-01709-7` | `-0.132892` | bone-marrow=`.934`，但 cross-species=`.668`、spleen=`.768`；线性 CCA/Procrustes 不能处理跨物种 marker 和比例偏移。 | 显式 ortholog 映射、cell-type-aware OT 和非线性对比对齐，优先攻 cross-species。 |
| `s41592-023-01878-z` | `-0.995935` | 两个 cryo-ET 实例 F1=`.0067/0`；多方向 NCC 对旋转、噪声和坐标标定仍近乎失效。 | 先做坐标/符号单元测试，再换旋转等变 3D 检测器或可学习模板库。 |
| `s41592-023-01940-w` | `-1.146056` | Completeness/Contamination MAE=`5.365/1.673`；早期大量预算耗在 25 亿 nnz 的 int32 溢出、SIGSEGV 和 RAM 超限，最终流式子采样 LightGBM 丢失大量信息。 | 先建立 int64+分块全量可运行基线，再做 marker-aware、层级目标和 residual 模型；单纯扩 RAM 无法修复数据结构。 |
| `s41592-023-02032-5` | `-0.655801` | benchmark/SARS-CoV-2 backbone recall=`.384/.197`，sequence recall=`.147/.091`；手工峰检测和局部追踪缺少全局链与序列约束。 | 换 learned density-to-backbone + 全局图优化/序列配准，保留局部几何 refinement。 |
| `s41592-024-02191-z` | `-0.373177` | frog/zebrafish 双向 Accuracy=`.538/.471`、F1=`.219/.214`；ortholog bridge+MNN 未形成可分离跨物种表示。 | 审计 ortholog 覆盖和标签混淆，使用一对多 orthology、层级标签与 reference mapping。 |
| `s41592-024-02257-y` | `-0.334106` | DLPFC/HER2 ARI=`.426/.222`，HER2=`-0.472`；GAT 平滑在肿瘤异质边界上过强。 | 针对 HER2 使用多分辨率图、边界保持损失和组织学/表达联合特征。 |
| `s41592-024-02372-w` | `-3.072213` | 130 个样本均评出，但 PWM MAE=`.407`；距离池化几何 Transformer 丢失碱基位置依赖，输出尺度/校准也明显落后。 | 使用 PWM/序列位置感知输出头、同源 motif prior 和严格标度校准，而不是继续调当前 pooled regressor。 |
| `s41592-024-02523-z` | `-0.181671` | 19 个基因组任务中仅 DeepSTARR 为正；splice-sites-all=`-0.438`、H3K9me3=`-0.364`，通用短程 SE-ResNet 跨任务不稳。 | 使用预训练 genomic encoder，并按 histone/promoter/splice 分成专用 head、感受野和类别损失。 |
| `s41592-025-02665-8` | `-0.214212` | 2D/3D 扩散分段 Macro-F1=`.677/.708`；Conv-Transformer+HMM 未显式建模扩散系数和 changepoint 似然。 | 引入物理扩散状态 likelihood、轨迹级归一化和 duration-aware semi-Markov/变点模型。 |
| `s41592-025-02820-1` | `-0.958356` | 三实例 DockQ 仅 `.0155/.0166/.0064`；独立折叠后 Kabsch+约束梯度没有形成正确复合物界面。 | 换 multimer 结构模型，在推理中直接注入 restraint、clash/能量和界面优化。 |
| `s41592-025-02826-9` | `-0.226803` | MIBI/CODEX F1=`.842/.607`；共享 marker/分位数阈值无法跨平台校准，CODEX 是主瓶颈。 | 平台特异归一化、marker-wise calibration 和弱监督阈值学习。 |
| `s41592-025-02854-5` | `-0.883331` | hematopoiesis 跨基因/细胞相关=`.143/.071`，eQTL Spearman=`.030`；pseudobulk+motif 特征几乎未捕获序列调控和细胞状态。 | 换预训练调控序列模型，联合 chromatin/cell context，并对 variant effect 单独建模。 |
| `s41592-025-02893-y` | `-244.524692` | df3d/human/rat7m/mice RMSE=`.184/.916/7.893/21.662`，后两者 PCK=`0`；长缺口、跨动物尺度和 mask 映射失效。 | 修复真实 mask 分布，按数据集归一化，使用时空运动学+骨长约束和长缺口 curriculum。 |
| `s41592-025-02924-8` | `-0.291670` | migration F1=`.583`、seeding-clone F1=`.228`；VAF 阈值+硬 parsimony 对树不确定性和器官标签过于刚性。 | 使用概率 clone-tree/迁移图推断，显式优化 seeding clone，并传播树结构不确定性。 |
| `s42256-022-00464-w` | `-0.608523` | FHN MNAD=`.00395`，KS MNAD=`.190` 且 Correlation=`.016`；POD-reservoir 长期自回归发生相位漂移。 | 换稳定 Koopman/neural operator 或多步稳定损失，重点解决 KS 长期动力学。 |
| `s42256-022-00501-8` | `-0.112899` | 9 个分子任务中 tox21/bindingdb 为正，lipophilicity 近线；ESOL/Freesolv 各约 `-0.43`、toxcast=`-0.113`。 | 按回归/分类拆模型，引入 3D/预训练分子表征，重点重做溶剂化回归。 |
| `s42256-022-00518-z` | `-0.182478` | atlas mapping ACC=`.981` 已持平；unseen ACC=`.765`、integration ASW/kBET=`.361/.386` 拉低总分。 | 三实例拆成专用方案：开放集/层级分类处理 unseen，scVI/scArches 或图模型处理 integration。 |
| `s42256-022-00526-z` | `-0.865006` | USPTO Top-1/5 exact match=`.123/.145`；小型迁移初始化 Transformer 没学到可靠反应中心和化学语法。 | 使用预训练 reaction Transformer、原子映射/反应中心监督和受约束 beam search。 |
| `s42256-022-00541-0` | `-0.261998` | PDTC/diagnosis/relapse AUROC=`.429/.569/.547`；简单 CORAL/对抗域适配未建立临床可迁移药物响应信号。 | 引入肿瘤/药物多模态表征、分层域适配和 cohort-level 校准，分别验证三场景。 |
| `s42256-023-00627-3` | `-0.189847` | cystic-fibrosis mean SCC=`.460`，IBD/soil=`.254/.201`，soil=`-0.392`；逐代谢物 LightGBM 缺少组成和通路结构。 | 使用零膨胀组成模型、微生物-代谢通路图和跨 cohort 多任务学习，优先 soil。 |
| `s42256-023-00630-8` | `-0.883162` | RAVEN/I-RAVEN Accuracy=`8.06%/12.49%`，接近或低于 8 选 1 随机水平；训练 loss 约 `ln(8)`。 | 先做小样本过拟合和按 constellation 诊断；训练链路可学后再加入对象属性解析/显式关系推理。 |
| `s42256-024-00836-4` | `-0.209367` | RNA 分类 F1=`.992` 已为正，二级结构 archiveII/TS0 F1=`.680/.493`。 | 保留分类器，替换结构分支为全局配对约束的 folding model/动态规划解码。 |
| `s42256-024-00838-2` | `-0.702107` | CAMEO recovery=`.179`、BLOSUM=`.070`；ProteinMPNN 候选少，ESM refine 受 1 小时限制实际关闭。 | 提升结构条件生成主干和批量多样化采样效率，再做 structure-aware rerank。 |
| `s42256-024-00892-w` | `-0.509220` | mask F1=`.438`、Recall=`.396`，但 trace Pearson=`.849`；时间迹恢复尚可，细胞检测/分割是主要瓶颈。 | 用 U-Net/Cellpose/CNMF 类实例分割替换 center-heatmap+局部相关 mask，保留 trace denoiser。 |
| `s42256-024-00916-5` | `-0.636999` | DRD2/QED SR@.4/.5/.6=`.228/.110/.056`，ADMET overall=`.268`，组合 hERG+ESOL=`.0042`。 | 换可约束生成/编辑策略，以 oracle 反馈迭代，并按 Pareto/约束满足率选样。 |
| `s42256-024-00956-x` | `-0.528262` | 1200K/dihedral 为正，但 300K=`-2.118`、600K=`-0.346`；第二阶段高温/OOD 微调破坏低温精度。 | 做温度均衡采样、分温度 head/ensemble 和 energy-force 多目标权衡，重点恢复 300K。 |
| `s42256-025-01010-0` | `-1.424118` | transition1x mean/median RMSD=`.238/.168`；多先验融合没有显式反应坐标和高质量 TS 几何约束。 | 使用 reactant-product 条件的等变 TS 模型，加入原子映射、反应中心和 NEB/能量约束。 |
| `s42256-025-01019-5` | `-0.999816` | 四实例 peptide accuracy=`0-.00032`，氨基酸 recall 仅 `.045-.074`；当前 Transformer/解码基本未学会 de novo sequencing。 | 先验证 token/mass 对齐和训练可收敛，再换预训练谱图编码器+质量守恒 beam search；属于训练失败主导。 |
| `s42256-025-01042-6` | `-0.565097` | 四数据集 recovery=`26.4%-30.0%`，BLOSUM=`44.9-48.8`，一致性落后说明不是单一 split 问题。 | 使用 ProteinMPNN/ESM-IF 等更强预训练 inverse-folding 主干，多温度采样并按结构/LM 联合 rerank。 |
| `s43588-024-00730-4` | `-119.777793` | atomic=`135.25 mHa`、biradical gap=`13.76 kcal/mol`、excited-state=`10.48 mHa`；PBE0/UMP2/TDA 及经验 fallback 达不到高精度量子化学参考。 | 按实例采用 CCSD(T)/basis extrapolation、multireference/CASPT2 和更可靠 excited-state 方法；这是机理求解层级不足。 |
| `s43588-025-00903-9` | `-0.356136` | 13 个聚合物性质中 OPV/MAR 为正，EA/EAT/IP 约 `-1.03` 至 `-1.17`；通用 fingerprint 对电子结构性质失效。 | 按性质拆模型，为共轭/电子性质加入重复单元图、3D/量子描述符和不确定性校准。 |
| `s43588-025-00917-3` | `-0.775381` | UCNP IID/OOD MSE×1e3=`18.82/53.49`；Beer-Lambert+DeepSets 在壳层组合 OOD 上明显失效。 | 引入能级跃迁/能量传递速率方程或壳层图模型，按 OOD 壳层结构做验证。 |
| `s43588-025-00920-8` | `-0.186163` | 多数 CPA 分项接近，catalyst 为正；CPA-thiol R2=`.034`、improvement=`-0.949` 是主拖累。 | 保留已有 GBDT 分支，单独为 thiol 使用 3D 催化剂-底物/过渡态描述符和小样本迁移。 |

综合优先级是：先修复并重评 7 个不可归因结果；随后并行推进 13 个近 SOTA 的定向 refine；
37 个明确差距 case 中，优先处理可验证的训练/实现失败（`s41587-024-02414-w`、
`s41592-023-01940-w`、`s42256-023-00630-8`、`s42256-025-01019-5`），其余应扩展方法
搜索空间后再启动新 Run。

### 2026-08-10/11 补数据与代码刷新批次

该批次按 `glm-5.2`、Idea/Implement/Evaluator 并发 `1/1/3`、Idea/Evaluation 队列容量
`3/3` 和 4 小时 Agent 预算运行。25 个 task 中已有 23 个完成；下表记录全部完成结果，
`s43588-025-00872-z` 和 `s43588-025-00878-7` 已于 2026-08-11 启动独立重跑，见下文。

| Case | 领域 | `g` | Judge | 结果等级 | 完整 Run |
|---|---|---:|---|---|---|
| `s41551-024-01257-9` | Biomedical Modeling | `0.005697` | valid | Match-only | [Run](../../../.famou/naturebench-runs/configfix-s41551-024-01257-9-20260810-2120/) |
| `s41592-023-01878-z` | Biomedical Modeling | `-0.995935` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/configfix-s41592-023-01878-z-20260810-2120/) |
| `s41592-023-02032-5` | Biomedical Modeling | `-0.655801` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/datafix-r2-s41592-023-02032-5-20260810-192136/) |
| `s41592-023-02148-8` | Cellular Omics | `0.255722` | valid | Surpass-SOTA | [Run](../../../.famou/naturebench-runs/code-refresh-s41592-023-02148-8-20260810-1955/) |
| `s41592-024-02580-4` | Biomedical Modeling | `-0.997676` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/required-rerun-s41592-024-02580-4-20260810-2100/) |
| `s41592-025-02662-x` | Biomedical Modeling | `-0.077484` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s41592-025-02662-x-20260810-1955/) |
| `s41592-025-02820-1` | Protein Biology | `-0.958356` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/datafix-r2-s41592-025-02820-1-20260810-192136/) |
| `s41592-025-02870-5` | Cellular Omics | `-0.036581` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/required-rerun-s41592-025-02870-5-20260810-2100/) |
| `s41592-025-02924-8` | Cellular Omics | `-0.291670` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s41592-025-02924-8-20260810-1955/) |
| `s42256-022-00447-x` | Molecular Design | `0.024445` | valid | Match-only | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-022-00447-x-20260810-1955/) |
| `s42256-022-00501-8` | Molecular Design | `-0.112899` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-022-00501-8-20260810-1955/) |
| `s42256-022-00526-z` | Molecular Design | `-0.865006` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-022-00526-z-20260810-1955/) |
| `s42256-023-00611-x` | Relational Reasoning | `0.017577` | valid | Match-only | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-023-00611-x-20260810-1955/) |
| `s42256-023-00636-2` | Molecular Design | `0.020453` | valid | Match-only | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-023-00636-2-20260810-1955/) |
| `s42256-024-00790-1` | Physical Modeling | `-0.094688` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-024-00790-1-20260810-1955/) |
| `s42256-024-00815-9` | Molecular Design | `-0.491554` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-024-00815-9-20260810-1955/) |
| `s42256-024-00833-7` | Relational Reasoning | `0.012496` | valid（补 Judge） | Match-only | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-024-00833-7-20260810-1955/) |
| `s42256-024-00836-4` | Cellular Omics | `-0.209367` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-024-00836-4-20260810-1955/) |
| `s42256-025-01010-0` | Molecular Design | `-1.424118` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s42256-025-01010-0-20260810-1955/) |
| `s43588-024-00757-7` | Physical Modeling | `-0.301818` | invalid | 不计分 | [Run](../../../.famou/naturebench-runs/configfix-s43588-024-00757-7-20260810-2120/) |
| `s43588-025-00798-6` | Biomedical Modeling | `0.175259` | valid | Surpass-SOTA | [Run](../../../.famou/naturebench-runs/configfix-s43588-025-00798-6-20260810-2120/) |
| `s43588-025-00917-3` | Physical Modeling | `-0.775381` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s43588-025-00917-3-20260810-1955/) |
| `s43588-025-00920-8` | Physical Modeling | `-0.186163` | valid | 未达到 Match | [Run](../../../.famou/naturebench-runs/code-refresh-s43588-025-00920-8-20260810-1955/) |

#### Judge 异常与 invalid 诊断

- `s42256-024-00833-7`：首次 Judge 已正常收到同一最佳 attempt `0002` 的完整轨迹、源码和
  submission history，但模型输出了长篇自然语言分析，没有给出可解析的两字段 JSON，官方
  `_extract_json()` 因此返回 `unparseable output`。这属于 Judge 输出协议错误，不是候选无效。
  2026-08-11 使用相同官方 rubric、`claude-sonnet-4-6` 和相同证据补跑，得到严格结论
  `is_valid=true`。原 verdict 保存在
  `controller/judge_verdict.pre-rerun-20260811.json`，成功补跑证据位于
  `controller/naturebench_judge/judge_rerun_20260811_03/`。
- `s43588-024-00757-7`：Judge invalid 有充分代码和轨迹证据，不是解析或网络故障。最佳
  attempt `0011` 根据此前多轮 evaluator 分数反推固定预测模式
  `[1,0,1,1,0,1,1,1]`，并把同一常量输出用于 1033 个测试样本；主预测没有使用分子特征、
  图结构或训练标签。该做法属于利用评测反馈反解目标，不是对公开训练数据拟合科研方法，
  因此 `invalidate_primary_score=true`，在 `v8` 中以 invalid 留存且不计入 Completion Rate。

#### 五个无正式分数 task 的处置进度

`v8` 中的“尚无数值分数 5”不是统一含义：一个 task 已补齐 Judge，但 evaluator
环境错误使分数不能作为算法结论；两个 task 正在首次有效重跑；另两个 task 的 128 GiB
重跑被 Kubernetes 明确判定为 `OOMKilled`，已用修复后的进程隔离和 256 GiB 容器再次启动。

| Case | 当前 Run | fm-job / 状态 | 配置与处置 |
|---|---|---|---|
| `s41592-025-02926-6` | [Run](../../../.famou/naturebench-runs/bio-all-v3-s41592-025-02926-6-glm52-20260808-175527/) | 补 Judge 完成 | `is_valid=true`；`g=-1` 来自 evaluator 的 `anndata` 版本无法读取参考 `.h5ad`，暂记设施问题，不作算法效果结论。 |
| `s42256-023-00639-z` | [Run](../../../.famou/naturebench-runs/rerun2-s42256-023-00639-z-20260811-102654/) | `famou-nb-s42256-023-00639-z-20260811-104010`，Running | `1/1/3`，队列 `3/3`，4h，30 CPU，128 GiB，1 GPU。 |
| `s42256-023-00654-0` | [Run](../../../.famou/naturebench-runs/rerun2-s42256-023-00654-0-20260811-104020/) | `famou-nb-s42256-023-00654-0-20260811-104126`，Running | `1/1/3`，队列 `3/3`，4h，30 CPU，128 GiB，1 GPU。 |
| `s43588-025-00872-z` | [Run](../../../.famou/naturebench-runs/rerun3-s43588-025-00872-z-20260811-1120/) | `famou-nb-s43588-025-00872-z-20260811-112952`，Running | 30 CPU、256 GiB、1 GPU；canonical pool 192 GiB，单 CLI Agent RSS 上限约 17.07 GiB。 |
| `s43588-025-00878-7` | [Run](../../../.famou/naturebench-runs/rerun3-s43588-025-00878-7-20260811-1130/) | `famou-nb-s43588-025-00878-7-20260811-113033`，Running | 30 CPU、256 GiB、1 GPU；canonical pool 192 GiB，单 CLI Agent RSS 上限约 17.07 GiB。 |

`00872-z` 的旧重跑 Pod 从 `2026-08-11T01:55:14Z` 运行到 `02:34:32Z`，`00878-7`
从 `01:56:18Z` 运行到 `02:24:52Z`；两者容器终止原因均为 `OOMKilled`、退出码 `137`。
当时 Implement CLI 的 stdout/stderr 尚未完成落盘，故不能进一步把峰值归因到某条具体 Bash
命令。修复后 CLI wrapper 会监控 Agent 及其工具进程组 RSS；超限只结束当前激活，写入
`agent_memory_limit_exceeded`、峰值和上限，并把反馈路由回同一个 ImplementActor 修复，
不会再终止整个 Task Pod。所有新 Run 均保留旧失败 Run，不覆盖历史证据。

## 2026-08-10 历史合并快照（v7）

当时的正式提交产物为
[`famou-glm52-reviewed-20260810-v7`](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/)，
从全部本地 Run 中为每个 case 选择最新的“有限 `best_score` + 严格布尔 Validity Judge”结果，
共收录 `62/90` 个 task。NatureBench 官方脚本校验结果为 `0 warning / 0 error`，计分预览见
[`score_report.json`](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/score_report.json)。

| 统计项 | 数量 | 占全部 90 个 task |
|---|---:|---:|
| 已有官方数值分数且 Judge=valid | 62 | 68.89% |
| 未达到 Match（`g < 0`） | 40 | 44.44% |
| Match-only（`0 <= g <= 0.1`） | 13 | 14.44% |
| Surpass-SOTA（`g > 0.1`） | 9 | 10.00% |
| 达到 Match（Match-only + Surpass） | 22 | 24.44% |
| 尚无可上报结论 | 28 | 31.11% |

官方 `compute_scores.py` 给出的 `Score Rate` 和 `Completion Rate` 均为 `68.89%`，
`Match-SOTA=24.44%`、`Surpass-SOTA=10.00%`。这里官方 `Match-SOTA` 包含 Surpass，
因此对应上表的 22 个“达到 Match”；`Match-only` 是为了分析额外拆出的互斥类别。

### v7 新增的 5 个有效结果

| Case | 领域 | `g` | 结果等级 | Run | 提交证据 |
|---|---|---:|---|---|---|
| `s43588-025-00842-5` | Physical Modeling | `0.197531` | Surpass-SOTA | [Run](../../../.famou/naturebench-runs/nb-final-s43588-025-00842-5-glm52-20260809-all-remaining-v1/) | [raw-results](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/raw-results/s43588-025-00842-5/) |
| `s43588-024-00732-2` | Physical Modeling | `0.071009` | Match-only | [Run](../../../.famou/naturebench-runs/nb-final-s43588-024-00732-2-glm52-20260809-all-remaining-v1/) | [raw-results](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/raw-results/s43588-024-00732-2/) |
| `s42256-023-00628-2` | Physical Modeling | `-0.348310` | 未达到 Match | [Run](../../../.famou/naturebench-runs/nb-final-s42256-023-00628-2-glm52-20260809-all-remaining-v1/) | [raw-results](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/raw-results/s42256-023-00628-2/) |
| `s42256-023-00627-3` | Cellular Omics | `-0.189847` | 未达到 Match | [Run](../../../.famou/naturebench-runs/bio-all-v3-s42256-023-00627-3-glm52-20260808-175527/) | [raw-results](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/raw-results/s42256-023-00627-3/) |
| `s42256-022-00541-0` | Biomedical Modeling | `-0.261998` | 未达到 Match | [Run](../../../.famou/naturebench-runs/bio-all-v3-s42256-022-00541-0-glm52-20260808-175527/) | [raw-results](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v7/raw-results/s42256-022-00541-0/) |

### 两个 Judge 解析失败的诊断与处置

`s42256-023-00627-3` 和 `s42256-022-00541-0` 的数值 evaluator 均正常出分，首次
Validity Judge 请求也正常到达 `claude-sonnet-4-6`，不是网络、超时、代码运行或评测失败。
失败发生在官方 `judge_core.runner._extract_json()`：模型没有遵守“只返回两字段 JSON”的
系统指令，而是先输出了长篇自然语言分析，完整响应中没有可解析的 `is_valid` JSON 对象，
因此官方 runner 返回 `judge_error: unparseable output`。官方证据只保留原始回答前 1000 个
字符，无法进一步区分模型最终主动停止还是触及 `4096` token 输出上限；可以确定的是错误属于
Judge 输出协议不稳定，不属于候选方案无效。

两个 case 均使用完全相同的官方 rubric、最佳 attempt、`submissions.jsonl`、完整轨迹和源码
投影做了一次 post-hoc 重跑，结果都为 `is_valid=true`。根级 canonical verdict 已指向
`judge_rerun_20260810_01`，并通过 `supersedes_request_id` 关联原失败请求；原始失败响应和新
Judge 投影均保留在各自 Run 的 `trusted/raw_evaluator_artifacts/` 与
`controller/naturebench_judge/` 中，没有删除或覆盖审计证据。

## 2026-08-09 历史合并快照（v5）

当时的合并结果为 [famou-glm52-reviewed-20260809-v5](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/)，
`v5` 从当时所有本地 Run 中按 task 选择最新且
同时满足“有限 `best_score` + 严格布尔 Validity Judge”的运行，共收录 `40/90` 个 task。

| 统计项 | 数量 | 占全部 90 个 task |
|---|---:|---:|
| 已有官方数值分数且 Judge=valid | 40 | 44.44% |
| 未达到 Match（`g < 0`） | 26 | 28.89% |
| Match-only（`0 <= g <= 0.1`） | 8 | 8.89% |
| Surpass-SOTA（`g > 0.1`） | 6 | 6.67% |
| 达到 Match（Match-only + Surpass） | 14 | 15.56% |
| 尚未运行或没有可上报结论 | 50 | 55.56% |

这里的“达到 Match”包含 Surpass；“Match-only”专指没有超过 `g=0.1` 的结果。`v5/results.csv`
包含全部 90 个官方 case ID，`raw-results/<case_id>/` 包含每个 case 的 `result.json`、
 `submissions.jsonl`、轨迹文件；40 个有效 case 另有 `judge_verdict.json` 和 Judge 使用的
 workspace 快照。当前已核对的是 leaderboard submission 包的 90 个 case 目录、40 个非空轨迹和
 0 个 submission 必需文件缺失；这不代表本地 NatureBench task 数据包已经完整，后者见下文的
 文件清单审计。

### 每个 case 的 Idea、Implement 与评测数量

下表只统计 `v5` 选中的 40 个 Judge-valid Run，统计口径如下：

- `Ideas`：Idea 队列中唯一 `payload.id` 的数量。同一 Idea 被重新派发、refine 或实现多次时只计
  一个 Idea。
- `Implement`：ExpBank 中除 `not_executed` 外的记录数；包含成功实现和工程失败的实现尝试，
  不等同于 Implement Agent 会话数。
- `Evaluation 尝试/出分`：前者是进入正式 Evaluation Queue 的 Candidate 数，后者是官方数值
  evaluator 成功返回有限 `aggregate_improvement` 的次数。评测失败计入前者但不计入后者。
- `Best ExpBank index`：`result.json.best_attempt_id`，用于定位最佳代码、产物和完整证据。
- `Best evaluator index`：`result.json.final_evaluation.score_attempt`，即提交给官方 evaluator 的
  顺序编号。工程失败或相同 Candidate 多次提交会使它与 ExpBank index 不一致。

| Case | Ideas | Implement | Evaluation 尝试/出分 | Best ExpBank index | Best evaluator index | Best score |
|---|---:|---:|---:|---:|---:|---:|
| `s41467-025-63412-3` | 9 | 21 | 21/20 | `0021` | `20` | `0.037324` |
| `s41467-025-63418-x` | 9 | 19 | 19/19 | `0017` | `17` | `-0.240325` |
| `s41467-025-65557-7` | 7 | 13 | 13/13 | `0002` | `2` | `-0.017470` |
| `s41551-024-01312-5` | 10 | 20 | 19/19 | `0019` | `18` | `0.139884` |
| `s41551-025-01528-z` | 7 | 12 | 11/11 | `0011` | `10` | `0.008425` |
| `s41587-024-02414-w` | 8 | 14 | 14/13 | `0007` | `7` | `-0.113559` |
| `s41587-024-02428-4` | 8 | 15 | 15/12 | `0015` | `12` | `-0.065649` |
| `s41587-025-02585-0` | 6 | 8 | 8/6 | `0006` | `4` | `-0.509462` |
| `s41587-025-02654-4` | 6 | 7 | 7/4 | `0005` | `4` | `-0.464847` |
| `s41587-025-02688-8` | 8 | 17 | 17/16 | `0017` | `16` | `1.335312` |
| `s41592-022-01709-7` | 8 | 14 | 13/13 | `0012` | `11` | `-0.132892` |
| `s41592-023-01940-w` | 6 | 15 | 14/4 | `0015` | `4` | `-1.146056` |
| `s41592-023-01955-3` | 8 | 11 | 11/10 | `0010` | `9` | `0.006291` |
| `s41592-023-02032-5` | 8 | 11 | 9/9 | `0007` | `5` | `-0.808923` |
| `s41592-023-02035-2` | 8 | 11 | 11/11 | `0001` | `1` | `-0.048132` |
| `s41592-023-02124-2` | 9 | 21 | 21/21 | `0001` | `1` | `0.050415` |
| `s41592-023-02148-8` | 7 | 8 | 5/4 | `0008` | `5` | `0.219432` |
| `s41592-024-02191-z` | 8 | 20 | 20/20 | `0011` | `11` | `-0.373177` |
| `s41592-024-02257-y` | 9 | 20 | 20/19 | `0018` | `17` | `-0.334106` |
| `s41592-024-02316-4` | 8 | 11 | 11/10 | `0004` | `4` | `-0.011249` |
| `s41592-025-02662-x` | 6 | 11 | 11/11 | `0005` | `5` | `-0.702313` |
| `s41592-025-02776-2` | 7 | 13 | 13/13 | `0010` | `10` | `0.139697` |
| `s41592-025-02826-9` | 6 | 9 | 8/6 | `0007` | `3` | `-0.226803` |
| `s41592-025-02870-5` | 9 | 16 | 14/14 | `0010` | `8` | `-0.152714` |
| `s41592-025-02893-y` | 8 | 14 | 14/14 | `0013` | `13` | `-244.524692` |
| `s41592-025-02924-8` | 6 | 15 | 15/15 | `0010` | `10` | `-0.331263` |
| `s41592-025-02983-x` | 8 | 16 | 16/13 | `0007` | `8` | `-0.020552` |
| `s42256-022-00459-7` | 8 | 13 | 13/13 | `0003` | `4` | `0.012041` |
| `s42256-022-00468-6` | 9 | 15 | 15/15 | `0012` | `13` | `0.059942` |
| `s42256-022-00518-z` | 6 | 10 | 8/6 | `0010` | `6` | `-0.182478` |
| `s42256-022-00534-z` | 7 | 6 | 2/2 | `0006` | `2` | `-0.025721` |
| `s42256-022-00556-7` | 9 | 16 | 16/16 | `0015` | `15` | `0.161643` |
| `s42256-023-00630-8` | 6 | 6 | 6/4 | `0006` | `4` | `-0.883162` |
| `s42256-023-00640-6` | 10 | 18 | 18/18 | `0015` | `15` | `0.027606` |
| `s42256-024-00838-2` | 6 | 9 | 8/8 | `0009` | `8` | `-0.702107` |
| `s42256-024-00916-5` | 7 | 10 | 10/9 | `0010` | `9` | `-0.636999` |
| `s42256-025-01002-0` | 10 | 23 | 23/23 | `0016` | `20` | `0.017035` |
| `s43588-024-00689-2` | 9 | 16 | 16/15 | `0013` | `11` | `0.158822` |
| `s43588-024-00698-1` | 6 | 8 | 8/6 | `0002` | `2` | `-0.026021` |
| `s43588-024-00716-2` | 7 | 10 | 8/5 | `0001` | `1` | `-0.089730` |
| **合计** | **307** | **542** | **521/480** | - | - | - |

#### 截止时未实现的 New Idea

下面按最终队列状态统计普通 New Idea：`benchmark_attempt` 状态为 `finished` 表示已经进入过
Implement；状态为 `not_executed` 表示研究墙钟截止前没有形成实际实现。已评测 lineage 的
`actor_continuation` 是 Refine/Repair 机会，不重复计作 New Idea，单独列在最后一列。

| Task | New Idea 总数 | 已进入 Implement | 未实现 New Idea | 未执行 Continuation |
|---|---:|---:|---:|---:|
| `s41467-025-63412-3` | 9 | 7 | 2 | 1 |
| `s41467-025-63418-x` | 9 | 7 | 2 | 1 |
| `s41467-025-65557-7` | 7 | 5 | 2 | 1 |
| `s41551-024-01312-5` | 10 | 7 | 3 | 0 |
| `s41551-025-01528-z` | 7 | 4 | 3 | 1 |
| `s41587-024-02414-w` | 8 | 6 | 2 | 0 |
| `s41587-024-02428-4` | 8 | 5 | 3 | 0 |
| `s41587-025-02585-0` | 6 | 4 | 2 | 1 |
| `s41587-025-02654-4` | 6 | 4 | 2 | 1 |
| `s41587-025-02688-8` | 8 | 6 | 2 | 1 |
| `s41592-022-01709-7` | 8 | 6 | 2 | 2 |
| `s41592-023-01940-w` | 6 | 4 | 2 | 1 |
| `s41592-023-01955-3` | 8 | 5 | 3 | 1 |
| `s41592-023-02032-5` | 8 | 5 | 3 | 1 |
| `s41592-023-02035-2` | 8 | 5 | 3 | 1 |
| `s41592-023-02124-2` | 9 | 8 | 1 | 2 |
| `s41592-023-02148-8` | 7 | 4 | 3 | 0 |
| `s41592-024-02191-z` | 8 | 7 | 1 | 0 |
| `s41592-024-02257-y` | 9 | 7 | 2 | 1 |
| `s41592-024-02316-4` | 8 | 5 | 3 | 0 |
| `s41592-025-02662-x` | 6 | 4 | 2 | 1 |
| `s41592-025-02776-2` | 7 | 5 | 2 | 0 |
| `s41592-025-02826-9` | 6 | 3 | 3 | 1 |
| `s41592-025-02870-5` | 9 | 6 | 3 | 1 |
| `s41592-025-02893-y` | 8 | 6 | 2 | 1 |
| `s41592-025-02924-8` | 6 | 5 | 1 | 0 |
| `s41592-025-02983-x` | 8 | 6 | 2 | 0 |
| `s42256-022-00459-7` | 8 | 6 | 2 | 2 |
| `s42256-022-00468-6` | 9 | 7 | 2 | 1 |
| `s42256-022-00518-z` | 6 | 3 | 3 | 1 |
| `s42256-022-00534-z` | 7 | 4 | 3 | 1 |
| `s42256-022-00556-7` | 9 | 7 | 2 | 2 |
| `s42256-023-00630-8` | 6 | 4 | 2 | 2 |
| `s42256-023-00640-6` | 10 | 7 | 3 | 2 |
| `s42256-024-00838-2` | 6 | 4 | 2 | 1 |
| `s42256-024-00916-5` | 7 | 4 | 3 | 1 |
| `s42256-025-01002-0` | 10 | 9 | 1 | 2 |
| `s43588-024-00689-2` | 9 | 6 | 3 | 2 |
| `s43588-024-00698-1` | 6 | 4 | 2 | 2 |
| `s43588-024-00716-2` | 7 | 5 | 2 | 2 |
| **合计** | **307** | **216** | **91** | **41** |

40 个 Run 中，4 个最终遗留 1 个未实现 New Idea，21 个遗留 2 个，15 个遗留 3 个；没有
残留 `queued/running/waiting_resources` 状态。它们的历史配置全部是
`idea_queue_high_watermark=3`、Idea/Implement/Evaluation 并发 `1/1/3`。高水位限制的是
待实现队列的瞬时积压，不限制整个任务累计生成的 Idea 数量。

从消费阶段继续拆分，91 个未实现 New Idea 中有 77 个从未被 ImplementAgent 领取，14 个已经
被领取但在研究墙钟截止前没有提交 Candidate。二者在截止收尾时均被确定性转为
`not_executed`，所以最终队列汇总显示 `queued/running/waiting_resources=0`；Idea 原文、历史
队列事件和未执行原因仍然保留。这里的 `not_executed` 不表示 Idea 或方法失败，也不应写成
负面的科研结论。表中的 41 个未执行 Continuation 则属于已有 lineage 的 Refine/Repair 机会，
不是新的 Idea。

此前使用 `Idea/Implement/Evaluation=2/2/5`、队列容量 `5` 的运行是单独的
`nb-s41592-i2-impl2-e5-q5-glm52-20260807-012707`，不属于本次 `v5` 选中的 40 个 Run。

#### 为什么 Implement 多于 Idea

`Ideas` 统计唯一研究想法，`Implement` 统计冻结到 ExpBank 的 Candidate 实现尝试，因此两者
不是一一对应关系。同一个 Idea 可以依次产生首次实现、工程返修、有效分数后的微调、参数变体、
消融或替代实现。当前 40 个 Run 的具体构成为：

| 统计项 | 数量 | 含义 |
|---|---:|---|
| 唯一 Idea | 307 | Idea 队列中唯一 `payload.id`。 |
| 真正进入实现的 Idea lineage | 216 | 至少产生过一个非 `not_executed` ExpBank 记录。 |
| Implement | 542 | 包含成功实现和工程失败的实际实现尝试。 |
| 首次实现以外的后续实现 | 326 | 同一 lineage 的第二个及以后 Candidate。 |
| 带 `parent_attempt_id` 的明确后续版本 | 312 | 可以确定地关联到直接父版本的 refine 或返修。 |
| `engineering_failed` 实现 | 61 | 包含代码、输出契约、canonical 运行、超时或资源等工程失败；不能全部解释为 Idea 失败。 |

216 条已实现 lineage 中有 172 条被实现了不止一次，单条 lineage 最多产生 6 个 Implement。
因此 `Implement > Ideas` 主要来自“一条 Idea 对应多个 Candidate”的长生命周期设计，bug 返修
只是后续实现的一部分。

#### Implement Agent 的反馈恢复链路

正常情况下，微调、参数变体、消融和替代实现都由 Implement Agent 完成。每个 Idea 首次实现时
创建一个逻辑 `ImplementActor`；Candidate 提交后 Agent 不同步等待 evaluator，而是 park 并释放
并发槽。Controller 完成 canonical run 和正式评测后，把脱敏结果写入该 Actor 的
`feedback_mailbox`，再恢复同一个逻辑 Actor Session：

```text
Implement Agent 提交 Candidate
  -> park 并释放并发槽
  -> Controller 执行 canonical run + evaluator
  -> 结果写入 feedback mailbox
  -> 恢复同一个 ImplementActor Session
  -> Agent 选择修复、微调、变体或消融
  -> 提交下一版 Candidate
```

逻辑 Session 和操作系统进程需要区分：底层 CC/Codex CLI 进程可以重新启动，但会 resume 原
Session，并继续使用同一个 branch worktree；每次 `submit_candidate` 都冻结独立 Candidate
快照，因此后续修改不会覆盖已经评测的代码和产物。实现位置见
[orchestrator.py](../../../famou_scientist/loop/runtime/orchestrator.py) 的
`_schedule_actor_continuation()`，以及
[workers.py](../../../famou_scientist/loop/agents/workers.py) 的 `implement()`。

Continuation 不是无条件创建。研究时间已耗尽、Actor 预算用完、同一 Actor 仍有 Candidate 在途，或 Implement/Evaluation 队列达到背压上限时，调度器不会继续派发；工程修复的队列优先级高于正常 refine，但不会抢占已经运行的 Agent。

#### Implement Agent 实际 Instruction

最终 Prompt 由两层组成：

- [通用 CLI Implement Prompt](../../../famou_scientist/loop/prompts/cli_agents/implement_agent.md)：
  规定 workspace 隔离、显式提交、park/resume、异步评测和 Actor 预算。
- [Benchmark-managed Implement Prompt](../../../famou_scientist/loop/prompts/benchmark_managed/implement_agent.md)：
  规定读取 ExpBank、历史最佳方案、失败证据和 feedback mailbox，并针对 NatureBench 的公开
  题面、全部 instance、资源和 canonical 上限完成实现与 Smoke Test。

Agent 在每个恢复回合必须先读取最新反馈，再自行判断当前应该修复、改进、做变体还是消融；
`submit_candidate` 返回 `accepted=true, action=park` 后必须结束当前回合，正式运行和 evaluator
统一由 Controller 执行。内存超限、canonical 超时、输出格式错误等必须被当作工程问题返修，
不能直接写成 Idea 无效的科研结论。

#### Implement DDL 心跳、资源反馈与 ExpBank 诊断

从 2026-08-10 起，单次 Implement 激活支持可配置 DDL 心跳。NatureBench 默认配置为：

```yaml
workers:
  implement:
    timeout_sec: 3600
    deadline_heartbeat:
      enabled: true
      trigger_after_sec: 2400
```

Agent 连续运行 40 分钟仍未提交时，wrapper 会结束当前 CLI 激活、保留 Actor Session 和
worktree，再恢复同一 Session 注入“剩余约 20 分钟”的真实消息。提醒只触发一次；恢复后应停止
完整 benchmark、长参数搜索和依赖安装，只做轻量 Smoke Test 并调用 `submit_candidate`。关闭
`enabled` 后仍是原来的单次激活流程。fm-job 可通过
`FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT=0/1` 和
`FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC=<秒>` 覆盖默认值。

提供给 Implement Agent 的资源信封已经脱敏，只包含可用 CPU、可分配主机 RAM、GPU 数量和
逐卡可分配显存，不含 GPU UUID、其他任务利用率、Evaluator 路径或调度租约。Implement 可在
`method_manifest.json.resource_request` 修正 Idea 的估算；若 CPU、RAM、GPU 数量或单卡显存
超过任务信封，`submit_candidate` 会立即返回 `accepted=false` 和逐项上限差异，不生成
submission event，也不 park Agent。Agent 可在同一回合降低声明并重新提交；Controller 仍保留
第二层确定性校验，覆盖自定义 Agent Adapter。

Candidate 不再设置单文件 512 KiB 或总量 4 MiB 的容量阈值。大源码、模型配置和必要资产可以
直接冻结到 CFS。路径越界、符号链接、保留目录、Python 入口语法以及最多 64 个显式源码文件的
结构安全校验仍然保留；证据导出工具的日志截断/打包阈值也不等同于 Candidate 大小限制。

ExpBank 的每个失败版本现在统一保存 `failure` 对象，核心字段包括
`failure_stage`、`error_code`、`return_code`、`signal`、`timed_out`、`submitted`、
`retryable`、`message`、`suggested_action`、`evidence_refs` 和 `diagnostics`。Implement CLI、
canonical run、artifact validation、public evaluator 和 evaluator 基础设施失败采用同一结构；
`SUMMARY.md` 展示短诊断，`record.json` 和 `evidence/` 保留完整细节。后续 Idea/Implement Agent
可以据此区分工程返修和方法结论。

#### 40 个入选 Run 的 CLI 返回码复核

`rc` 是 OS 进程返回码，不等价于 Candidate 成败。对 `v5` 入选的 40 个 Run 下全部 Implement
wrapper 元数据重新分类后，结果如下：

| 情况 | 次数 | 判断与处理 |
|---|---:|---|
| `rc=143`，已提交且 `parked_after_submission=true` | 64 | 正常流程。Controller 收到提交后发送 `SIGTERM` 释放槽位，不记工程失败。 |
| `rc=143`，`cancelled_by_controller=true` | 30 | 4h 研究墙钟结束后的正常收尾；版本记为 `not_executed`，不形成方法失败结论。 |
| `rc=143`，`timed_out=true` | 7 | 单次 Implement DDL 耗尽且未提交；Agent 主要仍在全数据测试、参数搜索或依赖准备。新 DDL 心跳用于提前收敛到可提交版本。 |
| `rc=1`，`terminal_reason=api_error` | 2 | `s41592-023-02032-5`、`s41592-023-02148-8` 均为 `Connection closed mid-response`，属于 API 传输中断，应恢复原 Session。 |
| `rc=1`，Session 已占用 | 4 | 出现在 `s41592-023-02032-5`、`s41592-023-02148-8`、`s41592-025-02870-5`、`s43588-024-00716-2`；这些是旧实现把突发错误交回 Controller 后再次派发产生的历史现象。新 wrapper 会在原调用内立即透明 Resume，不主动等待，也不向 Agent 解释中断原因。 |
| `rc=143`，未提交且 `aborted_tools` | 1 | `s41592-025-02870-5` 在约 20 分钟、66 turns 后工具执行被中止；不是 Implement DDL，也没有有效提交，按可重试 Agent runtime 失败记录。 |
| `rc=-9` | 1 | `s43588-024-00716-2` 被外部 `SIGKILL`；轨迹包含 OpenFold/ESMFold 安装、模型加载、网络重试和大范围 CFS 扫描，疑似资源压力，但没有 cgroup OOM 证据，不能写成已确认 OOM。 |
| `rc=0` 但没有显式提交 | 2 | `s41551-024-01312-5`、`s41592-022-01709-7` 的 CLI 正常退出但违反提交协议，应恢复原 Session 要求调用 `submit_candidate`。 |

7 次真正的单回合超时分布为：`s41551-025-01528-z` 1 次、
`s41592-023-02148-8` 1 次、`s41592-025-02826-9` 1 次、
`s42256-022-00518-z` 2 次、`s42256-022-00534-z` 2 次。新的失败分类会把上述情况分别记录为
`agent_timeout_before_submit`、`agent_api_error`、`agent_session_in_use`、
`agent_tools_aborted`、`agent_process_killed`、`missing_explicit_submit` 和
`agent_cancelled_by_research_deadline`，不再使用一个笼统的 `failed`。

#### Refine 是否带来提升

下面只统计 `continuation_reason=evaluated`，即父 Candidate 已获得有效分数后，结果回传给同一
ImplementActor 所产生的后续版本；工程失败后的 repair 单独处理，不混入该统计。40 个入选
Run 中共有 297 条这类 continuation 记录，其中 18 条在研究截止前没有执行，不能形成分数
比较；其余 279 条中有 271 条父子版本均获得有效分数，8 条发生工程失败或没有出分。

| Refine 相对直接父版本的结果 | 数量 | 占成功出分 refine |
|---|---:|---:|
| 分数提升 | 187 | 69.0% |
| 分数下降 | 78 | 28.8% |
| 分数相同 | 6 | 2.2% |
| 工程失败或未出分 | 8 | - |
| 已执行合计 | 279 | 271 次成功出分，8 次未出分 |
| 截止前未执行 | 18 | 不进入提升率分母 |

最终 40 个最佳结果中，24 个来自有效分数后的 refine，1 个来自 `run_failed` 后的工程返修，
其余 15 个来自各自 Idea lineage 的首次实现。后者不表示 refine 过程中生成了 15 个新 Idea。
由此可以确认，refine 在当前批次中确实产生了实质收益；但分数下降或持平也很常见，因此
ExpBank 必须始终保留历史 best，不能用最新版本覆盖最佳版本。

#### 三轮生命周期与逐轮趋势

当前 NatureBench 的 `max_implement_turns_per_actor=3`。这里的三轮是“首次实现 + 最多两次
研究/refine”，不是首次实现后再 refine 三次；纯工程修复不占研究轮次。`v5` 运行时另有
`max_run_attempts_per_actor=6` 的 canonical 工程尝试预算，这由批量启动参数覆盖得到；它和
研究轮次是两个独立限制。仓库当前 `goal.yaml` 模板中的 canonical 默认值为 4。

40 个入选 Run 中有 202 个 ImplementActor 至少获得过一次有效正式评分，其有效评分数分布为：

| 单个 Actor 的有效评分数 | Actor 数 | 占有效 Actor |
|---|---:|---:|
| 1 次 | 47 | 23.3% |
| 2 次 | 32 | 15.8% |
| 3 次 | 123 | 60.9% |
| 合计 | 202 | 100.0% |

按同一 Actor 的有效评分时间序列相邻比较，跨过纯工程 repair 后仍连接该 Actor 的前后有效
版本，共得到 278 次有效转移：

| 相邻有效评分趋势 | 数量 | 比例 |
|---|---:|---:|
| 上升 | 192 | 69.1% |
| 下降 | 80 | 28.8% |
| 持平 | 6 | 2.2% |

提升概率随轮次略有下降，但没有出现断崖式衰减：

- 第 1 次到第 2 次评分：155 个可比较 Actor 中 110 个上升，提升率为 71.0%；
- 第 2 次到第 3 次评分：123 个可比较 Actor 中 82 个上升，提升率为 66.7%。

“三次都在上升”在当前三轮预算下，准确含义是三个评分点严格满足
`score_1 < score_2 < score_3`，即两次相邻 refine 都提升。跑满三次有效评分的 123 个 Actor
中，完整轨迹如下：

| 三轮趋势 | Actor 数 | 占三轮 Actor |
|---|---:|---:|
| 连续上升 `↑↑` | 49 | 39.8% |
| 先升后降 `↑↓` | 33 | 26.8% |
| 先降后升 `↓↑` | 32 | 26.0% |
| 连续下降 `↓↓` | 4 | 3.3% |
| 包含持平 | 5 | 4.1% |

49 个连续上升 Actor 分布在 25/40 个 case 中，并非由少数任务集中贡献。代表性序列包括：

- `s41592-025-02776-2`：`0.103969 -> 0.120665 -> 0.126554`；
- `s42256-022-00468-6`：`-0.019114 -> 0.036153 -> 0.054147`；
- `s41551-024-01312-5`：`-0.715460 -> -0.083934 -> 0.045962`。

从净效果看，三轮 Actor 中有 99/123（80.5%）的第三次评分高于第一次，21/123（17.1%）
低于第一次，3/123（2.4%）相同。因此当前数据支持保留三轮预算：refine 总体有效，第二次
refine 仍有明显收益；但连续上升只占约四成，调度器仍必须保留历史最佳版本，不能默认最后
一轮最好。

#### New Idea 与 Refine 的增益对比

两者没有天然相同的父版本，不能直接用“相对父 Candidate 的变化”比较。这里采用两个互补
口径：

- 统一突破口径：两者都和该次正式评分前 ExpBank 中的全局最佳分数比较；
- 最终贡献口径：按 case 统计最终最佳方案来源，并把从首个有效方案到最终 best 的提升归因给
  每次刷新全局 best 的 New Idea、Refine 或工程 repair。

New Idea 指一个 ImplementActor 首次获得有效评分的原始研究方案；如果首次有效评分来自
`run_failed` 等失败后的修复，则归入 repair。Refine 指该 Actor 在获得有效分数后，基于
evaluator feedback 进行的下一研究轮。纯工程 repair 始终单列，不计入二者。

| 统一对比指标 | New Idea | Refine |
|---|---:|---:|
| 可与评分前全局 best 比较的次数 | 143 | 271 |
| 超过评分前全局 best | 40（28.0%） | 68（25.1%） |
| 成功突破时的单次增益中位数 | `+0.02477` | `+0.01095` |
| 40 个 case 的最终最佳方案来源 | 15 | 24 |
| 对 case 最终提升贡献更大 | 15 | 22 |

其余 3 个 case 的 New Idea 与 Refine 贡献相同；另有 1 个 case 的最终最佳方案来自工程
repair。New Idea 和 Refine 超过当时全局 best 的成功率接近，但 New Idea 成功时的单次增益
中位数约为 Refine 的 2.3 倍，表现为“更少见但幅度更大的跳跃”。Refine 的单次突破较小，
但尝试次数更多，能够连续累积改进，因此最终有 24/40 个最佳方案来自 Refine。

为避免不同 NatureBench task 的分数量级差异污染总体均值，只在每个 case 内把“首个有效
方案到最终 best 的总提升”归一化为 100%，再对 37 个确实发生净提升的 case 取平均贡献：

| 最终提升来源 | 按 case 归一化后的平均贡献 |
|---|---:|
| Refine | 53.8% |
| New Idea | 38.4% |
| 工程 repair | 7.8% |

Refine 相对自身直接父版本的提升率为 69.0%，说明它对既有方法进行局部优化时较稳定；这个
数字的基线是“自己的父版本”，而 New Idea 的 28.0% 使用的是更严格的“当前全局 best”，
两者不能直接用百分比判断优劣。统一基线后的结果说明：当前批次中 Refine 是累计收益和最终
best 的主要来源，New Idea 则承担较大幅度的方法空间跳跃。

这些统计是异步调度下的观察结果，不是等预算随机对照实验：Refine 有 271 次可比较机会，
New Idea 只有 143 次，而且不同方案的实现成本并不完全相同。因此它支持的调度结论是前中期
保持 New Idea 探索以建立多条 lineage，中后期逐步把资源倾斜给高分 lineage 的 Refine；不能
据此删除其中任何一类。若要形成因果结论，应在相同 task、实现时间和评测次数预算下，对
“生成新 Idea”和“继续 Refine”做成对随机实验。

#### New Idea 重叠度与方法多样性审计

本节使用 2026-08-10 的
[`famou-glm52-reviewed-20260810-v6`](../../../.famou/naturebench-submissions/famou-glm52-reviewed-20260810-v6/)
作为该次审计快照，覆盖其中全部 57 个 `Judge=valid` task。它与上文基于 `v5` 的 40 个 Run
收益统计是两个不同批次，本节只回答 IdeaAgent 产生的 New Idea 是否大量重复，不重新计算
New Idea/Refine 的分数贡献。

57 个入选 Run 共保留 422 条唯一 New Idea，每个 task 为 6-10 条。重叠分析使用加权后的
`title + hypothesis`：标题重复三次，使核心算法词高于任务背景；使用英文停用词过滤和
1-2 gram TF-IDF cosine。没有直接以完整 `mechanism` 作为主指标，因为数据读取、输出格式、
资源预算和 Smoke Test 等公共模板会系统性虚高同一 task 内的相似度。以下阈值只用于批内
近邻筛查，不是通用的语义创新性标准：

- cosine 不低于 `0.35`：明显近似，通常属于同一基础模型上的小变体；
- `0.25 <= cosine < 0.35`：中度同方法族，通常保留主干但替换部分组件；
- cosine 低于 `0.25`：文本证据显示核心假设或方法描述差异较大。

| 审计项 | 结果 |
|---|---:|
| Judge-valid task | 57 |
| 唯一 New Idea | 422 |
| 同 task 内两两组合 | 1,397 |
| 字面完全相同的标题 | 0 |
| 明显近似 pair（`>=0.35`） | 5（0.4%） |
| 中度同方法族 pair（`0.25-0.35`） | 63（4.5%） |
| 弱相似 pair（`<0.25`） | 1,329（95.1%） |
| 至少存在一个中度以上近邻的 Idea | 111/422（26.3%） |
| 至少存在一个中度以上近邻的 task | 35/57 |
| 存在明显近似 pair 的 task | 5/57 |

因此从批内重叠看，当前 New Idea 不是由大量参数微调、标题改写或重复提案构成：约四分之三
的 Idea 没有中度以上文本近邻，明显近似 pair 只占 0.4%。但这不表示所有 Idea 都完全正交；
35 个 task 至少有一对同方法族方案，说明 IdeaAgent 会在保留探索跨度的同时，围绕有希望的
基础模型生成局部变体。

Idea 的显式关系也支持这一判断：

| `relation` | 数量 | 含义 |
|---|---:|---|
| 根 Idea | 51 | 当前 Run 中没有声明直接父 Idea。 |
| `derived_from` | 209 | 使用父方案或评测证据继续设计，不必然表示小改动。 |
| `alternative_to` | 146 | 面向同一目标提出替代路线。 |
| `combines` | 16 | 合并两个或多个已有机制。 |

可解析到直接父 Idea 的 174 个 `derived_from` 父子对中，只有 10 对进入 `>=0.25` 的中度以上
相似区间。因此当前 `derived_from` 更接近“利用历史证据继续设计”的 lineage 关系，不能直接
解释为参数微调。该字段尚未结构化表达核心组件到底是保留、替换还是新增。

方法跨度较大的代表性 task：

- `s41592-024-02316-4`：同时探索多模态 VAE、WNN+GMM、空间 iNMF、对比学习、联合因子
  分解、SpaGCN+MRF 和空间约束层次聚类，核心表示学习与聚类引擎均有明显变化；
- `s42256-022-00556-7`：同时包含 Transformer、GRU、CNN、闭式 XOR、TCN、FastText 和
  多个任务专用模型，属于跨方法族搜索；
- `s41592-025-02665-8`：除两个 LightGBM+HMM 近似方案外，还包含 TCN+BiGRU、
  Conv-Transformer 和纯 HMM，局部利用与方法探索同时存在。

同方法族重叠较明显的代表性 task：

- `s41592-023-01940-w`：多数方案以 Raw KEGG + LightGBM 为主干，主要变化是采样、目标变换、
  bagging、SVD 和二阶段残差；
- `s41587-025-02654-4`：主要围绕 ESMFold/AlphaFold2、recycle、domain decomposition 和
  置信度路由变化；
- `s41592-023-02032-5`：方案集中在密度峰、骨架追踪、模板放置和局部密度优化这一方法族；
- `s42256-024-00838-2`：主要围绕 ProteinMPNN + ESM-2 LM-Design，以及解析、解码和候选
  选择修复；
- `s41587-024-02414-w`：主要围绕 CNN/Transformer、反向互补增强、SWA 和 ensemble 变化。

综合结论是：当前 IdeaAgent 的**批内方法多样性足够支撑搜索**，重复提案不是当前主要瓶颈；
少数 task 会受强基础模型或任务结构约束，形成多个同族变体，这些变体仍可能通过工程可靠性、
训练目标或关键组件变化带来有效提升，不应只因同族而直接淘汰。这里衡量的是当前 Run 内的
相对多样性，不等同于对公开论文、代码和已有 SOTA 的外部新颖性判决；论文级“创新性”仍需
结合文献检索、相似方法对照和消融证据单独确认。

#### Refine 与新 Idea 的关系

对最终入选的 25 个后续版本逐一比较直接父版本，结果如下：

| 检查项 | 结果 |
|---|---:|
| 父子 `idea_id` 相同 | 25/25 |
| 父子 `lineage_id` 相同 | 25/25 |
| 小幅代码修改 | 15 |
| 中等规模修改 | 10 |
| 接近全量重写 | 0 |
| 父子源码行哈希 Jaccard 相似度中位数 | 0.739 |

代码改动规模的辅助分档为：Jaccard 相似度不低于 `0.70` 记为小幅修改，`0.35-0.70`
记为中等修改，低于 `0.35` 记为接近全量重写。该统计衡量的是代码变动规模，不能直接等同于
语义创新程度。

当前 refine 的实际链路是：

```text
原始 Idea
+ parent_attempt_id / parent_candidate_id
+ evaluator feedback_mailbox
+ 原 ImplementActor Session / worktree
-> 同一 ImplementAgent 继续修改
```

小幅修改通常包括 epoch、阈值、PCA 维度、采样量和 ensemble seed 调整，以及数值、路径、
内存问题修复。中等修改通常包括引入或替换部分组件、合并历史最佳模块，以及调整
per-instance 路由、特征或模型集成。实证上这些版本都沿用原 `idea_id` 和 `lineage_id`，属于
同一方法方向内的迭代，而不是由 IdeaAgent 产生的全新 Idea。

当前证据结构还没有把“参数微调、工程修复、组件变化、消融、方法替换”记录为独立的结构化
类型。这些信息可以从方法描述、代码和完整轨迹中审计，但无法可靠地按类型聚合。后续应在
Candidate manifest 和 ExpBank 中增加 `change_type`、`change_summary`，并保留
`parent_attempt_id` 作为对照版本索引。`change_type` 建议至少包含：

- `parameter_tuning`：参数或搜索范围调整；
- `bug_fix`：不改变方法意图的工程修复；
- `component_change`：替换或增加局部组件；
- `ablation`：用于验证贡献的受控删减或对照；
- `method_replacement`：核心机制发生替换。

真正的新方向仍应由 IdeaAgent 产生并进入 IdeaSpark。若 ImplementAgent 在 refine 中完全替换
核心机制，应将其升级为 derived Idea，重新进入 Idea 记录、可选 Idea Gate 和调度流程，避免
把方法创新错误地统计为原 Idea 的微调。

### 历史 v5 快照：26 个未达 SOTA case 的统一诊断

下面分析历史 `v5` 快照中 `g < 0` 的 26 个 case。这是当时批次的诊断记录，
不是当前 90-case 结果的实时未 Match 数量；当前数量请以
[`CURRENT_RESULTS_CN.md`](CURRENT_RESULTS_CN.md) 为准。需要先区分两个概念：

- NatureBench 的数值 `g < 0` 只表示当前提交低于论文参考 SOTA；
- `Validity Judge=valid` 只证明方案真实执行且没有明显查表、硬编码或泄漏，不证明本地公开
  数据完整，也不证明提交覆盖了全部实例。

因此，26 个负分不能全部解释为“算法失败”。本节把官方 evaluator 的 `raw_scores`、输出校验
错误、最佳 ExpBank 代码和运行日志作为确定性证据；对“为什么某种方法表达能力不足”的解释，
若没有专门消融实验，则标记为根因诊断而不是已证明的因果结论。

| 诊断类别 | 数量 | 定义 |
|---|---:|---|
| 当前分数不可归因于方法 | 4 | 公开输入快照或最佳提交不完整，必须先修复契约并重跑。 |
| 实现或搜索过程失败 | 3 | 最终候选可以评分，但 Idea 没有被完整实现、训练未收敛，或大部分预算消耗在工程失败上。 |
| 近 SOTA 方法差距 | 8 | 内部分析口径为 `-0.1 <= g < 0`；不是 NatureBench 的官方分档。 |
| 明确的方法能力差距 | 11 | 完整候选在关键实例上明显落后，当前方法范式本身需要改变。 |
| 合计 | 26 | 排除前 4 个不可归因结果后，有 22 个可用于分析当前方法能力。 |

#### 当前分数不可归因于方法

| Case | `g` | 确定性证据 | 为什么不能作为方法结论 | 处理 |
|---|---:|---|---|---|
| `s41592-023-02032-5` | `-0.808923` | cryo-EM 任务旧公开快照只有 `980/1548` 个官方文件；现有结果中 benchmark/SARS-CoV-2 的 backbone recall 仅 `.212/.110`，sequence recall 仅 `.063/.030`。 | 当前手工骨架追踪确实表现弱，但旧 Run 的输入也不完整，无法分离“方法弱”和“缺输入”的影响。 | 数据已补齐并校验；以新 Run 的完整输入结果替换旧分数。 |
| `s41592-025-02662-x` | `-0.702313` | 9 个实例只有 dna_fish、hybiss、merfish 产生完整分数；smfish 只有 `78/129` 个文件，另 5 个实例无 CSV，6 个实例被记为 `-1` improvement。 | 低 aggregate 主要由本地下载器分页缺陷直接造成，不是 spot detector 的整体性能。 | 数据已补齐；必须整任务重跑。 |
| `s41592-025-02870-5` | `-0.152714` | 14 次 evaluator attempt 均未完整覆盖 `oligodendrocyte-differentiation-subclusters_marques`；最佳提交仍带 `partial_errors` 和缺失输出目录。 | Judge 只能确认轨迹推断方法真实执行；partial aggregate 不能代表完整 benchmark 表现。 | 标记 `agent_artifact_incomplete`；先加全实例输出 smoke test 和 fallback，再重跑。 |
| `s41592-025-02924-8` | `-0.331263` | 旧 Run 的 `multi_region_simulated` 公开目录只同步了部分文件；现有 migration graph F1=`.550`、seeding clone F1=`.278`。 | 树拓扑/器官标签方法可能也弱，但输入快照不完整使当前分数无法成为最终算法结论。 | 数据已补齐并校验；等待新 Run 替换旧结果。 |

这 4 个 case 虽然在 `v5` 中具有 `Judge=valid`，正式提交 leaderboard 前仍应使用重跑结果替换；
若重跑未完成，应在发布版 `results.csv` 中按未形成可信结论处理。

#### 实现或搜索过程失败

| Case | `g` | 官方/运行证据 | 直接原因 | 根因诊断与下一步 |
|---|---:|---|---|---|
| `s41587-024-02414-w` | `-0.113559` | yeast promoter Pearson=`.729`、Spearman=`.792`；最佳方案标题声明 auxiliary pairwise-difference loss，但实际训练方法仍是 `SmoothL1Loss`。 | 高权重 SNV、motif pair 子集要求预测表达差值，Idea 的核心目标没有进入损失函数。 | 属于 Idea/Implement 一致性失败。实现真实的 paired-difference objective，并分别报告普通序列与 pair 子集消融。 |
| `s41592-023-01940-w` | `-1.146056` | microbial genome quality 的 Completeness MAE=`5.365`、Contamination MAE=`1.673`；多个候选发生约 `2.51B` nnz 的 `int32` 溢出、SIGSEGV 或主机 RAM 超限。 | 大量预算消耗在不可运行的稀疏矩阵实现上；最终只能用流式子采样 LightGBM，稀有 marker 与完整特征联合信息损失明显。 | 先固定 `int64`/分块稀疏读取和全量可运行基线，再比较 marker-aware、层级目标和 residual 模型；扩 RAM 不能替代数据结构修复。 |
| `s42256-023-00630-8` | `-0.883162` | RAVEN Accuracy=`8.06%`，I-RAVEN=`12.49%`；8 选 1 随机水平为 `12.5%`，训练 loss 约为 `ln(8)`。 | 最终输出完整，但 Grid Transformer 基本没有学到关系规则；早期 i_raven 空文件只是已修复的次要工程问题。 | 属于训练/优化失败而非有效算法比较。先验证可过拟合小样本和分 constellation 准确率，再引入对象属性解析或显式关系推理。 |

#### 近 SOTA 方法差距

这里的“近 SOTA”仅是为了安排后续实验，定义为 `-0.1 <= g < 0`；官方仍统一计为未达到
SOTA。

| Case | `g` | 关键子指标 | 为什么没有达到 SOTA | 优先实验 |
|---|---:|---|---|---|
| `s41467-025-65557-7` | `-0.017470` | 4 个 SMLM 场景中 scenario_8_blinking 为 `+0.0216`，其余 3 个为 `-0.0278` 至 `-0.0341`。 | SNN/DBSCAN 只用每场景 3 个标注 FOV 校准，固定邻域与密度阈值对椭圆簇、背景密度和 blinking 的变化仍有轻微过拟合。 | 做 leave-one-FOV-out 参数选择，并消融 SNN、持久性合并和 Mahalanobis 边界扩展。 |
| `s41587-024-02428-4` | `-0.065649` | PPI interface AUROC=`.733`、AUPR=`.324`、F1=`.064`、Recall=`.034`。 | PCA 压缩后的 ESM 表征加逐残基 LightGBM 主要学习单蛋白局部特征，缺少可靠的 partner-specific 三维/共进化交互；阈值校准不能改善主指标 AUROC。 | 加入成对 cross-attention、结构暴露度和界面邻域特征；单独报告 AUROC 与阈值指标，避免只调 F1。 |
| `s41592-023-02035-2` | `-0.048132` | pancreas Weighted/Macro F1=`.961/.952`，PBMC=`.878/.641`，lung=`.659/.519`。 | scVI/scANVI 在 pancreas 已接近参考线，主要差距来自 lung 的跨研究分布偏移和稀有细胞类型，PBMC macro-F1 也暴露长尾类别问题。 | 做按数据集/细胞类型混淆矩阵、rare-class reweighting 与 query-specific adaptation。 |
| `s41592-024-02316-4` | `-0.011249` | 5 个 simulation 的 ARI 均为 `.954-.963`，每个 improvement 仅 `-.0071` 至 `-.0169`。 | 输出和聚类都稳定，差距属于 WNN 权重、空间平滑与 GMM 选择在参考线附近的小幅偏差。 | 围绕 WNN 权重、图邻居数、平滑步数和聚类初始化做小规模网格消融。 |
| `s41592-025-02983-x` | `-0.020552` | junction-loss AUC=`.924`；三个行为回归 Pearson=`.779/.906/.807`。 | 手工力学/时序特征的 boosting ensemble 已较强，但只有少量训练胚胎，局部特征和子采样仍限制跨胚胎泛化。 | 做 tension、组织位置、时间加速度和 ensemble 的逐项消融，并采用 embryo-level 交叉验证。 |
| `s42256-022-00534-z` | `-0.025721` | Baron/Segerstolpe/Muraro Macro-F1=`.969/.989/.956`，Xin=`.730`。 | 简化 marker + Logistic Regression 在三个平台稳定，但 SMARTer/Xin 的跨实验室分布偏移明显，固定 marker 和归一化不足以对齐该域。 | 增加 cohort-aware normalization/域适配；单独针对 Xin 做错误类型和 marker dropout 分析。 |
| `s43588-024-00698-1` | `-0.026021` | 7 个扰动数据集仅 k562_essential 为正 improvement；k562_gw PR-AUC=`.057`，perturb_cite_seq Pearson=`.429`，prjna551220 improvement=`-.0766`。 | 共享多任务网络能迁移部分信号，但任务间标签稀疏度、单/双基因扰动和测量平台差异过大，共享表示带来负迁移。 | 比较共享 backbone 与 dataset-specific head/独立模型，按 PR-AUC 与回归损失分别加权，并做单/双基因分组评测。 |
| `s43588-024-00716-2` | `-0.089730` | s669/s571 Spearman=`.545/.473`；s571 RMSE=`9.288`。 | 低同源测试集要求结构环境和 assay 校准，序列 ESM masked-marginal + 生化特征只能捕获演化可接受性，难以表示具体三维稳定性变化。 | 加结构接触/溶剂暴露特征、按 DDG/DTm 分离校准，并使用 group-by-protein CV 与 ranking loss。 |

#### 明确的方法能力差距

| Case | `g` | 关键子指标 | 当前方法为什么明显落后 | 需要的方向变化 |
|---|---:|---|---|---|
| `s41467-025-63418-x` | `-0.240325` | human hippocampus ARI=`.495`，simulated breast cancer ARI=`.320`。 | hybrid spatial-biological graph + DEC 虽优于同 Run 早期候选，但两个实例仍低；模拟乳腺布局破坏了空间与生物相似性的对应，当前图构造和两模态融合仍传播了错误邻域。 | 学习式 modality/edge gating、空间图与生物图分支融合，并对两个实例分别做图边消融。 |
| `s41587-025-02585-0` | `-0.509462` | CODEX in-silico/small/large F1=`.486/.606/.339`，large-scale 最差。 | NNLS/FISTA 的线性逐像素解混在 5→22 的欠定压缩和真实染色串扰下缺乏非线性与空间先验；高 SSIM 不等于阳性像素恢复，稀疏 F1 仍很低。 | 使用带空间卷积/生成先验的监督解混网络，并针对 F1 做稀疏支持集损失和大图分块训练。 |
| `s41587-025-02654-4` | `-0.464847` | single-domain TM-score=`.514`，multi-domain full-chain=`.363`。 | 最佳提交已完整输出；瓶颈是单序列 ESMFold 对 hard target 和多域相对取向能力不足，置信度门控 recycle 不能补足 MSA/template 信息。 | 引入 MSA/template 或更强结构模型；多域任务增加 domain assembly/refinement，而不是继续只调 recycle。 |
| `s41592-022-01709-7` | `-0.132892` | bone marrow matching=`.934`，PBMC=`.819`，murine spleen=`.768`，cross-species=`.668`。 | rank/CCA/Procrustes 在同物种数据有效，但跨物种 marker 对应、细胞类型比例和非线性平台差异无法由线性共享子空间稳定对齐。 | 显式 ortholog/marker 映射、cell-type-aware optimal transport 和非线性对比对齐；优先攻 cross_species。 |
| `s41592-024-02191-z` | `-0.373177` | zebrafish→frog Accuracy/F1=`.538/.219`，frog→zebrafish=`.471/.214`。 | ESM ortholog bridge + MNN + 对比学习没有建立可分离的跨物种细胞表示，两个方向都低，不是单向标签偏差。 | 先审计 ortholog 覆盖率和标签混淆，再使用一对多 orthology、层级标签和跨物种 reference mapping。 |
| `s41592-024-02257-y` | `-0.334106` | DLPFC ARI=`.426`，HER2 ARI=`.222`，HER2 improvement=`-.472`。 | GAT autoencoder/GMM 在 DLPFC 尚可，但 HER2 的低基因数、肿瘤异质性和复杂空间边界使局部平滑先验过强，域边界被混合。 | 针对 HER2 使用多分辨率空间图、边界保持损失和组织学/表达联合特征。 |
| `s41592-025-02826-9` | `-0.226803` | MIBI breast F1=`.842`，CODEX colon F1=`.607`。 | 同一 marker/阈值分类逻辑不能覆盖 MIBI 与 CODEX 的强度分布和银标准标签差异，CODEX colon 的跨平台校准是主要瓶颈。 | 做平台特异归一化、marker-wise calibration 和弱监督阈值学习，避免共享固定阈值。 |
| `s41592-025-02893-y` | `-244.524692` | df3d/human/rat7m/mice_2d RMSE=`.184/.916/7.893/21.662`，后两者 PCK=`0`。 | Transformer + bone prior 对长缺口和跨动物骨架失效；human 还出现 mask mapping 失败后退化为 uniform masking。极端负分主要来自 rat7m/mice_2d，而非 evaluator 异常。 | 先修复 mask 分布，再采用时空运动学/骨长约束、按数据集归一化和长缺口 curriculum；必须分实例验证。 |
| `s42256-022-00518-z` | `-0.182478` | hp_mapping ACC=`.981` 且 improvement 约 `0`；PBMC unseen ACC=`.765`，integration ASW/kBET=`.361/.386`。 | 监督 atlas mapping 已达到参考线，负分来自 unseen CD8 subtype 和多技术 integration；marker 规则、Scanorama/Harmony 无法同时发现新类型并保留生物结构。 | 将三个实例拆成专用方法：开放集/层级分类处理 unseen，scVI/scArches 或更强图模型处理 integration。 |
| `s42256-024-00838-2` | `-0.702107` | CAMEO sequence recovery=`.179`，BLOSUM=`.070`。 | ProteinMPNN 单/少量采样加 ESM-2 rerank 覆盖的候选空间过窄；受 1 小时 canonical 限制，预期中的大规模 refinement 实际被关闭或缩减。 | 优先提升结构条件模型和 batched 多样化采样效率，再使用 structure-aware energy/LM ensemble rerank。 |
| `s42256-024-00916-5` | `-0.636999` | DRD2/QED SR@`.4/.5/.6`=`.228/.110/.056`；ADMET overall=`.268`，hERG+ESOL=`.0042`。 | 相似训练对的编辑迁移和规则突变主要在局部化学空间搜索，严格相似度与多属性约束下候选覆盖不足，组合 ADMET 目标尤其失败。 | 使用可约束生成模型/编辑策略，按 oracle 反馈迭代，并以 Pareto/约束满足率而非单纯相似度排序。 |

总体上，当前最值得优先处理的不是 26 个任务全部重跑：先替换 4 个不可归因结果；修复 3 个
实现/搜索失败；对 8 个近 SOTA case 做低成本定向消融；剩余 11 个需要方法范式变化，直接增加
同类候选数量通常收益有限。

### 当前 fm-job 状态

以下是 `fm-job-new list --prefix famou-nb` 的实时快照。它统计的是当前提交的 Job，和上面的
跨历史 Run 汇总不是同一个口径。

| 状态 | 数量 | 说明 |
|---|---:|---|
| `Succeeded` | 31 | Job 已结束；是否进入官方有效结果仍需看 Run 的 evaluator/Judge 产物 |
| `Running` 且已有 Pod | 8 | 正在实际执行 |
| `Running` 但无 Pod | 1 | 已提交但正在等待资源分配 |
| `Failed` | 1 | `s43588-025-00878-7`，Implement Agent 超时且没有显式提交候选 |
| 合计 | 41 | 31 + 8 + 1 + 1 |

### 当前需要重跑的 task

| Task | 重跑原因 | 重跑前置条件 |
|---|---|---|
| `s41592-025-02662-x` | 旧 Run 使用了不完整的本地公开数据：远端有 9 个实例，当时本地只有 4 个，因此旧分数不可作方法结论。 | 下载器已修复，数据已补齐且二次校验为 `missing_files 0`；下一步创建新 Run 并重跑，环境镜像无需重建。 |
| `s41592-025-02870-5` | 14 次正式评测都没有覆盖完整输出，属于 Agent 产物契约问题。 | 修复实例遍历、输出目录/文件校验和 fallback；这是结果覆盖率重跑，不是硬件重跑。 |
| `s43588-025-00872-z` | 128 GiB 重跑在首个 Implement 激活期间被 Pod cgroup 终止；Kubernetes 记录 `OOMKilled`、`exitCode=137`。 | 已增加 CLI Agent 进程组 RSS 上限与可恢复错误路由，并用 256 GiB 容器重跑。 |
| `s43588-025-00878-7` | 早期 Run 曾出现 Agent 超时；2026-08-11 的 128 GiB 重跑进一步由 Kubernetes 明确记录为 `OOMKilled`、`exitCode=137`。 | 已增加 CLI Agent 进程组 RSS 上限与可恢复错误路由，并用 256 GiB 容器重跑。 |

2026-08-09 23:21 已修复下载器的 Hugging Face `Link: rel="next"` 分页逻辑，并补齐以下 8 个
task。补下载后重新拉取完整远端清单、逐文件检查存在性和官方 size，结果为
`missing_files 0`。任务数据位于 CFS，不进入环境镜像；旧 Run 中已经准备好的数据快照不会自动
更新，使用旧数据产生的分数仍不作为方法结论：

| Task | 修复前问题 | 当前状态 |
|---|---|---|
| `s41592-025-02662-x` | 缺少 5 个公开实例及大量实例文件。 | 已补齐并通过 size 校验；使用新 Run 重跑。 |
| `s41592-023-02148-8` | RNA family 的公开 FASTA/资源文件不完整。 | 已补齐并通过 size 校验；旧分数需剔除后重跑。 |
| `s41592-025-02924-8` | `multi_region_simulated` 只同步了部分目录。 | 已补齐并通过 size 校验；旧分数需剔除后重跑。 |
| `s41592-024-02580-4` | `livecell` 等公开图像文件只同步了部分内容。 | 已补齐并通过 size 校验；使用新 Run 运行。 |
| `s41592-025-02820-1` | Agent 可见的完整 `problem/` 未同步。 | 已下载并解压公开数据归档，通过 size 校验；可直接使用已有环境镜像启动新 Run。 |
| `s42256-024-00836-4` | Agent 可见的完整 `problem/` 未同步。 | 已下载并解压公开数据归档，通过 size 校验；可直接使用已有环境镜像启动新 Run。 |
| `s41592-023-02032-5` | cryo-EM 公开输入目录只同步了部分文件。 | 已补齐并通过 size 校验；旧分数需剔除后重跑。 |
| `s42256-024-00892-w` | Agent 可见的完整 `problem/` 未同步。 | 已下载并解压 26 GB 公开数据归档，通过 size 校验；可直接使用已有环境镜像启动新 Run。 |

这 8 个是“数据已修复、等待新 Run/重跑”，与 Agent 代码失败、算法效果低分是两类问题；
旧 Run 不能混入普通方法失败统计。此前分页风险名单中的 `s41587-025-02654-4` 和
`s41587-025-02585-0` 已完成远端/本地清单校验，不需要因下载问题重跑。

`s41592-023-01940-w`、`s41592-025-02826-9`、`s42256-023-00630-8`、
`s41592-025-02983-x` 和 `s42256-022-00518-z` 都出现过单次 Candidate 的主机 RAM
超限，但各自已有完整 Candidate，因此不进入强制重跑清单。它们如果要做方法改进可以另行
重跑，不能把资源失败 attempt 当成整个 task 失败。

### 新增 18 个已完成结果

| Case | 官方领域 | `g` | 结果等级 | 私有完整 Run | v5 raw-results |
|---|---|---:|---|---|---|
| `s41551-025-01528-z` | Cellular Omics | `0.008425` | Match-only | [Run](../../.famou/naturebench-runs/bio-all-v3-s41551-025-01528-z-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41551-025-01528-z/) |
| `s41592-024-02191-z` | Cellular Omics | `-0.373177` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s41592-024-02191-z-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-024-02191-z/) |
| `s41592-024-02257-y` | Cellular Omics | `-0.334106` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s41592-024-02257-y-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-024-02257-y/) |
| `s41592-024-02316-4` | Cellular Omics | `-0.011249` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s41592-024-02316-4-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-024-02316-4/) |
| `s41592-025-02662-x` | Biomedical Modeling | `-0.702313` | 本地公开数据包不完整，分数不可作方法结论 | [Run](../../.famou/naturebench-runs/bio-all-v3-s41592-025-02662-x-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-025-02662-x/) |
| `s41592-025-02776-2` | Protein Biology | `0.139697` | Surpass-SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s41592-025-02776-2-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-025-02776-2/) |
| `s41592-025-02826-9` | Biomedical Modeling | `-0.226803` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v2-s41592-025-02826-9-glm52-20260808-130737/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-025-02826-9/) |
| `s41592-025-02893-y` | Biomedical Modeling | `-244.524692` | 未达到 SOTA，长缺口场景失效 | [Run](../../.famou/naturebench-runs/bio-all-v3-s41592-025-02893-y-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-025-02893-y/) |
| `s41592-025-02983-x` | Cellular Omics | `-0.020552` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v2-s41592-025-02983-x-glm52-20260808-130737/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-025-02983-x/) |
| `s42256-022-00459-7` | Protein Biology | `0.012041` | Match-only | [Run](../../.famou/naturebench-runs/bio-all-v3-s42256-022-00459-7-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-022-00459-7/) |
| `s42256-022-00518-z` | Cellular Omics | `-0.182478` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s42256-022-00518-z-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-022-00518-z/) |
| `s42256-022-00534-z` | Cellular Omics | `-0.025721` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v2-s42256-022-00534-z-glm52-20260808-130737/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-022-00534-z/) |
| `s42256-023-00640-6` | Molecular Design | `0.027606` | Match-only | [Run](../../.famou/naturebench-runs/bio-all-v3-s42256-023-00640-6-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-023-00640-6/) |
| `s42256-024-00838-2` | Protein Biology | `-0.702107` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s42256-024-00838-2-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-024-00838-2/) |
| `s42256-024-00916-5` | Molecular Design | `-0.636999` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s42256-024-00916-5-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-024-00916-5/) |
| `s42256-025-01002-0` | Protein Biology | `0.017035` | Match-only | [Run](../../.famou/naturebench-runs/bio-all-v3-s42256-025-01002-0-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s42256-025-01002-0/) |
| `s43588-024-00698-1` | Cellular Omics | `-0.026021` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s43588-024-00698-1-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s43588-024-00698-1/) |
| `s43588-024-00716-2` | Protein Biology | `-0.089730` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v3-s43588-024-00716-2-glm52-20260808-175527/) | [raw](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s43588-024-00716-2/) |

### 新增未达 Match 的诊断

以下结论来自官方 evaluator 的 `raw_scores` 和最佳 ExpBank attempt，不是额外的 LLM 总结。
其中“工程/输出问题”表示当前 `g` 不能直接作为算法结论；“方法问题”表示产物完整且
Validity Judge 通过，但官方子任务指标确实低于参考线。

| Case | 官方子任务证据 | 诊断 | 结论/建议 |
|---|---|---|---|
| `s41592-024-02191-z` | frog/zebrafish 双向 Accuracy=`0.538/0.471`，F1=`0.219/0.214` | 代码和输出有效，但跨物种 ortholog 对齐、MNN 和对比学习没有形成稳定的可迁移表示，两个方向都低。 | 方法问题；优先做 ortholog 覆盖率、细胞类型混淆矩阵和跨物种对齐消融。 |
| `s41592-024-02257-y` | dlpfc ARI=`0.426`，her2 ARI=`0.222`；her2 的 improvement=`-0.472` | 输出完整；DLPFC 已接近，但低基因数、强空间异质的 her2 是主要瓶颈，空间坐标增强仍不足以恢复域边界。 | 方法问题；单独围绕 her2 做空间先验、分辨率和聚类数消融。 |
| `s41592-024-02316-4` | 五个 simulation 的 ARI=`0.954-0.963`，每个 improvement 均为小幅负值 | 五个实例都正常输出且指标很高，差距集中在官方参考线附近，不是工程故障。 | 近 Match 方法问题；做 WNN 权重、空间平滑步数和 GMM 选择的精调。 |
| `s41592-025-02662-x` | 9 个实例中，本地 `problem/data/` 实际只有 dna_fish、hybiss、merfish、smfish；前 3 个有 F1，smfish 只有本地已有的 `78/129` 张 test 图像。其余 5 个实例没有本地输入目录。 | 最佳 Candidate 只对本地可见输入生成了 CSV。官方 Hugging Face task 树实际包含 9 个实例；本地缺失来自下载器截断递归文件清单，且 smfish 也因此只下载了部分文件。 | 本地数据同步问题，不是 ImplementAgent 漏写；当前 aggregate 不应作为方法结论。修复分页下载、补齐文件并重跑。 |
| `s41592-025-02826-9` | mibi_breast F1=`0.842`，codex_colon F1=`0.607` | 两个实例均有完整输出；codex_colon 明显拉低 aggregate，空间强度特征和银标准标签在跨平台场景泛化不足。 | 方法问题；针对 codex_colon 做 marker、阈值和跨平台校准。 |
| `s41592-025-02893-y` | df3d RMSE=`0.184`，human=`0.916`，rat7m=`7.893`，mice_2d=`21.662`；后两者 PCK=`0` | 四个数组均 shape 正确、finite 且 canonical 正常完成；但骨架先验 + Transformer 对长缺口和跨动物缺失恢复失败，human 还有 `mask mapping failed` 后退化为 uniform masking。 | 方法问题，伴随一个可修复的 mask 配置问题；不是资源超限或 evaluator 失效。优先修复 mask mapping，并对 rat7m/mice_2d 做长缺口分层评测。 |
| `s41592-025-02983-x` | junction_loss AUC=`0.924`；multi_task Pearson=`0.779/0.906/0.807` | 输出完整，三个回归子任务已有较强相关性，但整体仍略低于参考线，局部特征集和小样本泛化不足。 | 近 Match 方法问题；围绕 junction_loss 和 invagination/rearrangement 做针对性特征消融。 |
| `s42256-022-00518-z` | hp_mapping ACC=`0.981`；pbmc unseen ACC=`0.765`；hp_integration ASW=`0.361`、kBET=`0.386` | hp_mapping 基本达到参考水平，跨技术 novel projection 和 integration 两个子任务拖低 aggregate。 | 方法问题；重点补充 unseen subtype 的 protein/RNA 映射和批次整合消融。 |
| `s42256-022-00534-z` | Baron/Segerstolpe/Muraro Macro-F1=`.969/.989/.956`，Xin=`.730` | 三个数据集表现高，Xin 的跨实验室/平台分布偏移是主瓶颈；不是运行失败。 | 方法问题；需要独立的 Xin 域适配或更稳健的 label transfer。 |
| `s42256-024-00838-2` | cameo Sequence Recovery=`0.179`，BLOSUM=`0.070` | 产物完整且 ProteinMPNN/ESM-2 真正执行，但当前单轮设计采样和 rerank 没有覆盖足够好的序列空间。 | 方法问题；围绕采样温度、候选数、结构约束和 rerank 做搜索消融。 |
| `s42256-024-00916-5` | drd2_qed `SR@0.4/.5/.6=.228/.110/.056`，admet `SRA_overall=.268` | 产物完整；基于训练集指纹近邻的 retrieval/rerank 对新分子空间探索不足，hERG-ESOL 等组合目标尤其弱。 | 方法问题；需要生成式候选、oracle 预算分配和多目标 Pareto 筛选。 |
| `s43588-024-00698-1` | k562_gw PR-AUC=`.057`、k562_essential PR-AUC=`.207`，perturb_cite_seq Pearson=`.429` | 7 个数据集输出完整但跨数据集表现不均匀；低样本/强不平衡和 perturbation 回归子任务拖低 aggregate。 | 方法问题；做按数据集的共享预训练与独立 head、PR-AUC 加权和回归损失消融。 |
| `s43588-024-00716-2` | s669 Spearman=`.545`，s571=`.473` | 两个实例均有效，但突变效应排序相关性不足；ESM-2 + 生化特征的回归校准没有泛化到两个测试分布。 | 方法问题；优先做按 assay 分层的 ranking loss、零样本基线和特征消融。 |

新增 13 个未达 Match 中，`s41592-025-02662-x` 属于明确的本地公开数据包问题；其余 12 个
当前没有发现 evaluator、资源或文件隔离故障。`s41592-024-02316-4`、`s41592-025-02983-x`
和 `s43588-024-00698-1` 距离 Match 较近，适合优先重跑；`s41592-025-02893-y` 的极端
aggregate 主要由 rat7m/mice_2d 的真实大误差造成，不是单纯的分数解析异常。

## 数据包与 Benchmark 问题

这里严格区分官方 Benchmark 问题和本地数据准备问题。当前没有证据表明 NatureBench
官方 evaluator 或 task 契约有缺陷；此前唯一被标成“Benchmark 数据不完整”的 case，实际
是本地公开数据包没有同步完整。

| Case | 影响 | 证据 | 当前处理 |
|---|---|---|---|
| `s41592-025-02662-x` | 官方 task 的 `problem/README.md` 和 evaluator 都要求 9 个实例；旧 Run 的 `problem/data/` 只有 `dna_fish`、`hybiss`、`merfish`、`smfish`，其中 `smfish` 只有 `78/129` 张 test 图像。对照 Hugging Face 官方任务树，远端实际包含 9 个实例目录；首屏响应长度为 1000 且带 `Link: rel="next"`，旧下载器没有跟随下一页。 | [旧 Run 公开数据目录](../../.famou/naturebench-runs/bio-all-v3-s41592-025-02662-x-glm52-20260808-175527/problem/data/)、[staging.json](../../.famou/naturebench-runs/bio-all-v3-s41592-025-02662-x-glm52-20260808-175527/controller/staging.json)、[官方逐实例结果](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260809-v5/raw-results/s41592-025-02662-x/submissions.jsonl) | 这是本地下载器分页缺陷，不是官方数据缺失。源数据现已补齐并校验；环境镜像无需重建，创建新 Run 后重新运行和评分。 |

### 容易误判为 Benchmark 问题的案例

以下案例确实暴露了资源或输出压力，但目前证据不能归因于 benchmark 自身导致低分：

| Case | 实际原因 | 判断 |
|---|---|---|
| `s41592-023-01940-w` | 任务本身规模很大：约 `1.8-3.1M` 样本、`21K` 特征，元数据给出的完整训练时间约 `4-8` 小时。部分候选因稀疏矩阵 `int32` 溢出或内存超限失败；最佳有效候选仍完成了 evaluator，但 `Completeness_MAE=5.365`、`Contamination_MAE=1.673`。 | Benchmark 的资源需求高，但当前低分还包含真实方法能力问题；不能把 `-1.1461` 全部归因于 bench。 |
| `s41592-025-02870-5` | `oligodendrocyte-differentiation-subclusters_marques` 的缺失目录/空 `milestone_network.csv` 来自 Agent 的任务遍历和 fallback 输出问题；公开数据目录和 evaluator 都包含该数据集。 | Agent 输出契约问题，不是 benchmark 数据缺失。 |
| `s42256-023-00630-8` | `i_raven/predictions.csv` 为空，其他 `raven` 输出实际生成了约 `14000` 条预测。 | Agent 产物问题，不能据此形成算法结论。 |
| `s41592-025-02983-x`、`s42256-022-00518-z` | 分别缺少 `multi_task` 的 frame 3、`pbmc_unseen_projection/predictions.npy`。 | Agent 输出覆盖率问题。 |
| `s42256-024-00838-2` | `protein_0292` 预测长度与要求不符。 | Agent 输出校验/修复问题，不能直接视为方法失败。 |

因此当前结论是：`s41592-025-02662-x` 应从方法效果统计中剔除或标记为
`local_data_incomplete`；补齐本地数据并重跑后再纳入比较。其余低分 case 暂按方法问题或
Agent 工程问题处理，不能泛化为 Benchmark 缺陷。

## 资源终止明细与重跑判定

这里把资源类型精确区分为主机内存（RAM）、GPU 显存、CPU 和运行时间。当前核对到的
`memory_limit_exceeded` 均由 canonical runner 的**主机 RAM 限额**触发，不是 GPU
显存不足。相关记录没有出现 `CUDA out of memory`，也没有 Candidate 因“CPU 核数不足”
被终止；CPU 数量只可能影响运行速度。部分 Candidate 同时申请了 GPU，但终止信号仍来自
主机 RAM 监控器。

| Task | 失败 Candidate 与资源配置 | 精确原因 | 同任务后续结果 | 是否因资源强制重跑 |
|---|---|---|---|---|
| `s41592-023-01940-w` | `0007/0010`：16 CPU、48 GiB RAM、无 GPU；`0008/0012`：16 CPU、64 GiB RAM、1 GPU/20 GiB 显存；`0009`：16 CPU、80 GiB RAM、无 GPU。 | 五次均为**主机 RAM 超限**；`0008/0012` 监测到约 `64.06/64.02 GiB`。另有 `0003-0006` 因约 `2.51B` nnz 的 `int32` 溢出后触发 `SIGSEGV`，不是 CUDA OOM。 | `0011/0013/0014/0015` 已正常完成，最佳 `0015` 只使用 8 CPU、32 GiB RAM、无 GPU，约 `1259s`。 | 否。失败与 Candidate 构造超大稀疏矩阵有关，不是集群硬件不足；扩容只能容纳低效实现，`int64`/流式处理才是正确修复。 |
| `s41592-025-02826-9` | `0003`：16 CPU、8 GiB RAM、无 GPU。 | **主机 RAM 超限**；Candidate 只声明了 8 GiB。没有 CUDA 路径。 | 多个 32/48 GiB Candidate 已完成，最终两个实例输出完整。 | 否。属于单个 Candidate 资源声明过低，当前任务已有正式结果。 |
| `s42256-023-00630-8` | 历史 Run `nb-rel-v3` 的 `0002/0005`：4 CPU、16 GiB RAM、1 GPU/16 GiB 显存；`0003`：4 CPU、32 GiB RAM、1 GPU/20 GiB 显存。 | `0002/0005` 是**主机 RAM 超限**；日志无 CUDA OOM。`0003` 是 canonical 运行超时，不是内存终止。 | 最终 `nb-rerun-v5` 的 Candidate 使用 32 GiB RAM、1 GPU/16-24 GiB 显存，均未发生资源终止；完整结果仍为 `-0.8832`。 | 否。当前低分是模型训练接近随机，不是现有硬件阻塞。 |
| `s41592-025-02983-x` | `0002`：12 CPU、32 GiB RAM、无 GPU；`0004`：8 CPU、32 GiB RAM、无 GPU。 | 两次均为**主机 RAM 超限**，不存在 GPU 显存问题。 | 其余多个同为 32 GiB 的 Candidate 已完成，最佳完整结果为 `-0.0206`。 | 否。是实现相关的峰值 RAM 差异，已有正式结果。 |
| `s42256-022-00518-z` | `0004/0006`：8 CPU、32 GiB RAM、无 GPU。 | 两次均为**主机 RAM 超限**。 | 48 GiB CPU Candidate 和 64 GiB RAM + 1 GPU/20 GiB 显存的 Candidate 均完成；后者实际 RAM 峰值约 `47.9-51.8 GiB`，最佳结果完整。 | 否。已有正式结果；若以后复用同类实现，应声明至少 64 GiB RAM。 |

因此，当前已经完成并有正式结果的 task 中，没有一个被证明是“集群 CPU/GPU/RAM
硬件不足导致无法评测”。以上失败 Candidate 作为 Agent 搜索过程的工程证据保留，不触发
基础设施重跑。增加 RAM 可以让其中部分实现跑完，但不会自动提高官方分数。

上述 Candidate 的原始证据分别位于以下 Run 的 `expbank/<candidate>/evidence/run.json`：

- `bio-rerun-v1-s41592-023-01940-w-glm52-20260808-012031`；
- `bio-all-v2-s41592-025-02826-9-glm52-20260808-130737`；
- `nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100`；
- `bio-all-v2-s41592-025-02983-x-glm52-20260808-130737`；
- `bio-all-v3-s42256-022-00518-z-glm52-20260808-175527`。

### 已修复、需创建新 Run 重跑的本地数据问题

| Task | 阻塞类型 | 当前处理 |
|---|---|---|
| `s41592-025-02662-x` | 修复前本地任务树只有 4/9 个 `problem/data` 实例；旧下载器未处理 `Link: rel="next"`，漏掉 `synthetic_simple`、`synthetic_complex`、`synthetic_3d`、`telomeres`、`terra`。 | 分页下载器已修复，5 个实例已补齐，二次清单/size 校验通过；下一步创建新 Run、重跑，环境镜像不受影响。 |

同一下载器审计还发现以下 task 的首屏也达到 1000 条，存在同类分页风险：
`s41592-023-02148-8`、`s41592-025-02924-8`、`s41592-024-02580-4`、
`s41592-025-02820-1`、`s42256-024-00836-4`、`s41587-025-02654-4`、
`s41592-023-02032-5`、`s41587-025-02585-0`、`s42256-024-00892-w`。
逐 task 完整清单比对结果如下：

| Task | 远端文件数 | 修复前本地文件数 | 当前缺失文件数 | 当前结论 |
|---|---:|---:|---:|---|
| `s41592-025-02662-x` | 4021 | 949 | 0 | 数据已完整；必须创建新 Run 重跑 |
| `s41592-023-02148-8` | 1072 | 988 | 0 | 数据已完整；已有旧分数需剔除并重跑 |
| `s41592-025-02924-8` | 2296 | 968 | 0 | 数据已完整；已有旧分数需剔除并重跑 |
| `s41592-024-02580-4` | 8266 | 960 | 0 | 数据已完整；必须创建新 Run 运行 |
| `s41592-025-02820-1` | 4664 | 973 | 0 | 数据已完整；可使用已有环境镜像运行 |
| `s42256-024-00836-4` | 5225 | 991 | 0 | 数据已完整；可使用已有环境镜像运行 |
| `s41592-023-02032-5` | 1548 | 980 | 0 | 数据已完整；已有旧分数需剔除并重跑 |
| `s42256-024-00892-w` | 2924 | 993 | 0 | 数据已完整；可使用已有环境镜像运行 |
| `s41587-025-02654-4` | 2857 | 2857 | 0 | 已核对完整，不因分页风险重跑 |
| `s41587-025-02585-0` | 6634 | 6634 | 0 | 已核对完整，不因分页风险重跑 |

原先风险名单中的 8 个缺失任务现已补齐。表中的“修复前本地文件数”保留为审计证据；
“当前缺失文件数”来自修复后重新获取完整分页清单并逐文件校验 size。任务包包含
`problem`、`evaluation`、`environment`、`metadata` 等文件；Agent 仍只挂载 `problem/`，
隐藏的 `evaluation/ground_truth` 不会进入 Agent 工作区。环境镜像不包含任务数据，因此无需
重建；旧 Run 中已经准备的数据快照不会因为源目录补齐而自动变更，必须创建新 Run、重新运行
后才允许形成新的方法结论。

`s41592-025-02870-5` 不属于 Benchmark 或硬件问题，而是 Agent 没有生成覆盖全部实例的
合规产物。按当前记录策略将其保留为 `agent_artifact_incomplete`；只有需要补齐 leaderboard
覆盖率时才修复 Agent 输出检查并重跑，不列入基础设施修复队列。

### 5 个任务的产物完整性

需要特别区分“某次提交失败”和“整个 task 没有任何合规候选”：

| Task | 是否所有尝试都不完整 | 结论 |
|---|---|---|
| `s41592-025-02870-5` | 是。14 次 evaluator attempt 都在 `oligodendrocyte-differentiation-subclusters_marques` 上有缺失目录、空网络、细胞数不匹配等问题；其他数据集大部分正常。 | 记录为 `agent_artifact_incomplete`，当前分数不作为方法结论；不进入基础设施重跑队列，只有需要补齐 leaderboard 覆盖率时才修复 Agent 并重跑。 |
| `s42256-023-00630-8` | 否。前 3 次 `i_raven` 为空，第 4 次完整。 | 最终低分可作为完整候选的方法结果，但前 3 次只能记录为工程失败。 |
| `s41592-025-02983-x` | 否。前 12 次完整，第 13 次缺 frame 3；最佳候选是完整的第 8 次。 | 当前 `-0.0206` 可以作为完整候选结果，缺帧尝试单独标记失败。 |
| `s42256-022-00518-z` | 否。第 4 次缺 `predictions.npy`，其余尝试完整；最佳候选完整。 | 当前 `-0.1825` 可以作为完整候选结果。 |
| `s42256-024-00838-2` | 否。第 1、3 次有序列长度错误，其余尝试完整；最佳候选完整。 | 当前 `-0.7021` 可以作为完整候选的方法结果，错误尝试单独记录。 |

## 2026-08-09 累计未达 Match 的历史诊断摘要

旧批次的 13 个未达 Match 也纳入 `v5`，其诊断结论如下；每个 task 的完整 attempt、源码、
stdout/stderr 和 evaluator 原始响应仍以 `v5/raw-results/<case_id>/` 及私有 Run 为准。

| Case | `g` | 诊断摘要 | 当前判断 |
|---|---:|---|---|
| `s41467-025-63418-x` | `-0.240325` | SPADEC/图 VAE 是真实训练流程，但聚类表示和空间域划分没有超过参考线。 | 方法问题 |
| `s41467-025-65557-7` | `-0.017470` | DBSCAN/HDBSCAN 参数校准结果接近参考线但仍有小幅差距。 | 近 Match 方法问题 |
| `s41587-024-02414-w` | `-0.113559` | Idea 声称 pairwise-difference loss，代码实际主要是 `SmoothL1Loss`，Idea/实现不一致。 | 研究实现一致性问题 |
| `s41587-024-02428-4` | `-0.065649` | 主指标 AUROC 低于 baseline（约 `.7325` 对 `.736`），调 F1 阈值不能解决主指标差距。 | 方法问题 |
| `s41587-025-02585-0` | `-0.509462` | FISTA-L1 稀疏解压缩流程有效，但线性重建范式对该蛋白结构任务表达能力不足。 | 方法问题 |
| `s41587-025-02654-4` | `-0.464847` | ESMFold 推理有效，但历史最佳候选曾缺少 `benchmark_i` 的部分结构输出，需区分覆盖率问题和模型能力。 | 输出覆盖率 + 方法问题 |
| `s41592-022-01709-7` | `-0.132892` | matching pipeline 正常，部分实例较强，但跨实例匹配质量不稳定。 | 方法问题 |
| `s41592-023-01940-w` | `-1.146056` | 超大稀疏矩阵任务中大量候选因格式、int32 溢出和内存问题失败，剩余有效候选的 LightGBM 子采样方案仍弱。 | 搜索阶段工程损耗 + 方法问题 |
| `s41592-023-02032-5` | `-0.808923` | cryo-EM 密度上的手工骨架/核苷酸追踪虽真实执行，但对复杂密度结构的表达能力有限。 | 方法问题 |
| `s41592-023-02035-2` | `-0.048132` | scVI/scANVI 真实训练且接近参考线，但批次校正和标签迁移仍有小幅差距。 | 近 Match 方法问题 |
| `s41592-025-02870-5` | `-0.152714` | 轨迹推断流程有效；历史记录中的 `milestone_network.csv` 空文件来自 Agent 对 `oligodendrocyte-differentiation-subclusters_marques` 的输出/fallback 处理，不是公开数据缺失。 | Agent 输出契约问题 + 方法问题 |
| `s41592-025-02924-8` | `-0.331263` | 克隆树推断在部分模式使用 fallback，整体树拓扑与器官趋向性预测仍弱。 | 方法问题 |
| `s42256-023-00630-8` | `-0.883162` | RAVEN 训练 loss 约为 `ln(8)`、准确率接近随机，说明模型没有学到有效关系；早期还有 `i_raven` 空提交问题。 | 工程问题已暴露，当前方法结果仍失败 |

## 2026-08-08 已通过 Validity Judge 的结果

当前共有 22 个 case 形成可上报结果，全部 `judge_verdict=valid`。表中“结果等级”采用
NatureBench 口径：`g < 0` 为未达到 SOTA，`0 <= g <= 0.1` 为 Match-SOTA，`g > 0.1`
为 Surpass-SOTA。每个 Run 根目录保留 Agent、Candidate、ExpBank、canonical run、官方
evaluator、Judge 和完整原始轨迹；“公开证据”指经过脱敏的官方提交视图。

| Case | 官方领域 | `g` | 结果等级 | 私有完整 Run | Leaderboard 公开证据 |
|---|---|---:|---|---|---|
| `s41467-025-63412-3` | Protein Biology | `0.037324` | Match-SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41467-025-63412-3-glm52-20260808-001501/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41467-025-63412-3/) |
| `s41467-025-63418-x` | Cellular Omics | `-0.240325` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41467-025-63418-x-glm52-20260808-001501/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41467-025-63418-x/) |
| `s41467-025-65557-7` | Biomedical Modeling | `-0.017470` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41467-025-65557-7-glm52-20260808-001501/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41467-025-65557-7/) |
| `s41551-024-01312-5` | Cellular Omics | `0.139884` | Surpass-SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41551-024-01312-5-glm52-20260808-001501/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41551-024-01312-5/) |
| `s41587-024-02414-w` | Cellular Omics | `-0.113559` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41587-024-02414-w-glm52-20260808-001501/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41587-024-02414-w/) |
| `s41587-024-02428-4` | Protein Biology | `-0.065649` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41587-024-02428-4-glm52-20260808-002848/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41587-024-02428-4/) |
| `s41587-025-02585-0` | Biomedical Modeling | `-0.509462` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41587-025-02585-0-glm52-20260808-002848/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v3/raw-results/s41587-025-02585-0/) |
| `s41587-025-02654-4` | Protein Biology | `-0.464847` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41587-025-02654-4-glm52-20260808-002848/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41587-025-02654-4/) |
| `s41587-025-02688-8` | Cellular Omics | `1.335312` | Surpass-SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41587-025-02688-8-glm52-20260808-002848/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41587-025-02688-8/) |
| `s41592-022-01709-7` | Cellular Omics | `-0.132892` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41592-022-01709-7-glm52-20260807-230900/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41592-022-01709-7/) |
| `s41592-023-01940-w` | Cellular Omics | `-1.146056` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41592-023-01940-w-glm52-20260808-012031/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41592-023-01940-w/) |
| `s41592-023-01955-3` | Cellular Omics | `0.006291` | Match-SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41592-023-01955-3-glm52-20260808-012031/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41592-023-01955-3/) |
| `s41592-023-02032-5` | Biomedical Modeling | `-0.808923` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v2-s41592-023-02032-5-glm52-20260808-130737/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v3/raw-results/s41592-023-02032-5/) |
| `s41592-023-02035-2` | Cellular Omics | `-0.048132` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41592-023-02035-2-glm52-20260808-012031/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41592-023-02035-2/) |
| `s41592-023-02124-2` | Cellular Omics | `0.050415` | Match-SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41592-023-02124-2-glm52-20260808-012031/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41592-023-02124-2/) |
| `s41592-023-02148-8` | Cellular Omics | `0.219432` | Surpass-SOTA | [Run](../../.famou/naturebench-runs/bio-all-v2-s41592-023-02148-8-glm52-20260808-130737/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v4/raw-results/s41592-023-02148-8/) |
| `s41592-025-02870-5` | Cellular Omics | `-0.152714` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s41592-025-02870-5-glm52-20260807-230900/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s41592-025-02870-5/) |
| `s41592-025-02924-8` | Cellular Omics | `-0.331263` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/bio-all-v2-s41592-025-02924-8-glm52-20260808-130737/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v3/raw-results/s41592-025-02924-8/) |
| `s42256-022-00468-6` | Relational Reasoning | `0.059942` | Match-SOTA | [Run](../../.famou/naturebench-runs/nb-rerun-v5-s42256-022-00468-6-glm52-20260807-202616/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s42256-022-00468-6/) |
| `s42256-022-00556-7` | Relational Reasoning | `0.161643` | Surpass-SOTA | [Run](../../.famou/naturebench-runs/nb-rerun-v5-s42256-022-00556-7-glm52-20260807-202616/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s42256-022-00556-7/) |
| `s42256-023-00630-8` | Relational Reasoning | `-0.883162` | 未达到 SOTA | [Run](../../.famou/naturebench-runs/nb-rerun-v5-s42256-023-00630-8-glm52-20260807-202616b/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s42256-023-00630-8/) |
| `s43588-024-00689-2` | Cellular Omics | `0.158822` | Surpass-SOTA | [Run](../../.famou/naturebench-runs/bio-rerun-v1-s43588-024-00689-2-glm52-20260807-230900/) | [raw-results](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v2/raw-results/s43588-024-00689-2/) |

按完整 90-task 榜单分母计算，当前官方预览为：Score Rate `24.44%`、Completion Rate
`24.44%`、Match-SOTA `10.00%`（9/90）、Surpass-SOTA `5.56%`（5/90）。22 个有效
结果内部共有 9 个达到或超过 SOTA，其中 5 个达到官方 Surpass-SOTA 阈值。

## 已结束但未形成可上报结论

以下运行不写入 `results.csv` 的数值行，也不会伪造 `invalid`；它们在当前官方包中按
`not_run/not_applicable` 处理，私有证据仍完整保留。

| Case | 已有数值分数 | 诊断 | 处理 |
|---|---:|---|---|
| `s41592-023-01878-z` | 无 | 5 个候选均为工程失败。公开数据只存在 `problem/data_archives/data.tar.gz`，但 canonical run 收到的 `DATA_DIR=problem/data` 不存在；候选随后尝试向只读 `problem/` 解包，触发 `Permission denied`，因此没有进入官方数值 evaluator。 | 属于公开数据 staging/运行契约问题，不是算法无效；先把 archive 物化到独立只读数据目录，再整任务重跑。 |

`s42256-023-00611-x` 和 `s42256-024-00833-7` 原先因旧版 Judge 无法定位 task
根目录而处于未决状态，已于 2026-08-10 使用修复后的 task root 和
`claude-sonnet-4-6` 补判，二者均为 `is_valid=true`。旧判定文件保留为
`controller/judge_verdict.pre-rerun-20260810.json`，没有覆盖审计历史。

## 历史官方 Leaderboard 提交草案（v4）

当前严格格式目录为
[famou-glm52-reviewed-20260808-v4](../../.famou/naturebench-submissions/famou-glm52-reviewed-20260808-v4/)：

- `submission.yaml`：模型、Agent、预算、计算资源、Judge 和偏离说明；
- `results.csv`：全部 90 个官方 ID，22 个 Valid 数值结果和 68 个 `not_run`；
- `raw-results/<case_id>/result.json`：全部 90 个 case 均存在；
- `submissions.jsonl`：Valid case 保留全部官方 evaluator attempts，未运行 case 为空文件；
- `judge_verdict.json`：22 个 Valid case 均含严格布尔 `is_valid` 和原始 Judge reason；
- `trajectory.famou.jsonl`：22 个 Valid case 的完整多智能体轨迹；其余 case 有明确非空占位轨迹；
- `workspace/`：Validity Judge 实际查看的最佳 attempt 文本源码快照；
- `export_manifest.json` 和 `score_report.json`：来源 Run、计数、脱敏统计和官方分数预览。

已使用 2026-08-08 下载的 NatureBench 官方校验脚本验证：`0 warning / 0 error`。公开
包额外经过凭据、内网 endpoint 和 CFS 绝对路径扫描；共完成 `177445` 处脱敏替换，私有
Run 中的原始证据未修改。当前 `submission.yaml.url` 是内部 ICode 地址，正式邮件发送前
仍应替换成收件人可访问的公开 model/agent/project 稳定链接。

## 判定口径

对 `aggregate_improvement` 使用当前项目的报告口径：

- `< 0`：未达到 SOTA；
- `0 <= score <= 0.1`：Match-SOTA；
- `> 0.1`：Surpass-SOTA。

但是，只有 evaluator 契约正确、产物完整且任务正常收尾时，分数才可以用于最终科研结论。
历史 evaluator 响应中的 `valid=true` 只表示数值计算完成，不代表 Validity Judge 已通过；
正式上报必须另有 `judge_verdict.json.is_valid=true/false`。

## 历史 Relational 首轮结果（已被最新结果表更新）

| Task | Run 状态 | 最佳 ExpBank | 官方 aggregate | 当前结论 | 官方 Validity Judge | 后续动作 |
|---|---|---:|---:|---|---|---|
| `s42256-023-00611-x` | `stopped / evaluation_drain_completed` | `0015` | `0.0238104682` | Match-SOTA | 首轮 `valid=null`；2026-08-10 补判 `is_valid=true` | 已完成，无需整任务重跑 |
| `s42256-024-00833-7` | `stopped / evaluation_drain_completed` | `0007` | `0.0049914482` | Match-SOTA | 首轮 `valid=null`；2026-08-10 补判 `is_valid=true` | 已完成，无需整任务重跑 |
| `s42256-022-00556-7` | `stopped / evaluation_drain_completed` | `0011` | `-0.6187311389` | 当前分数不可用于排名，存在 Accuracy 单位错误；归一化后估计约 `+0.15965`，潜在 Surpass-SOTA | `valid=null`，Judge 找不到 task 根目录 | 修复单位规范化后重跑官方 evaluator 和 Judge |
| `s42256-023-00630-8` | `stopped / evaluation_drain_completed` | `0004` | `-0.7527690992` | 数值结果未达到，但主要是 `i_raven` 提交为空，属于工程失败，不能形成算法结论 | `valid=null`，Judge 找不到 task 根目录 | 修复数据路径和输出 smoke test 后重跑 |
| `s42256-022-00468-6` | `running` 残留，实际进程已退出 | 无 | 无 | 未形成 SOTA 结论；前 3 个候选 canonical 超时，后续候选未完成评测收尾 | 未生成 | 修复运行收尾后重新运行 |

该首轮当时可以确认的分类：

- Match-SOTA：2 个，`s42256-023-00611-x`、`s42256-024-00833-7`；
- 已确认 Surpass-SOTA：0 个；
- 潜在 Surpass-SOTA：1 个，`s42256-022-00556-7`，需要先修复 Accuracy 单位问题并重跑确认；
- 需要重跑：3 个，`s42256-022-00556-7`、`s42256-023-00630-8`、`s42256-022-00468-6`。

## 2026-08-07 重跑任务

以下任务已使用修复后的 Accuracy 单位规范化、完整 Validity Judge runtime 和提交输出检查重新启动。表中状态是提交后的初始状态，最终结论以本轮官方 evaluator 与 Judge 产物为准。

| Task | fm-job | Run ID | 配置 | 初始状态 |
|---|---|---|---|---|
| `s42256-022-00556-7` | `famou-nb-s42256-022-00556-7-20260807-230607` | `nb-rerun-v5-s42256-022-00556-7-glm52-20260807-202616` | `glm-5.2`；GPU 1；Idea/Implement/Eval=`1/1/3`；4h | `Running`，Evaluator Ready |
| `s42256-023-00630-8` | `famou-nb-s42256-023-00630-8-20260807-230622` | `nb-rerun-v5-s42256-023-00630-8-glm52-20260807-202616b` | `glm-5.2`；GPU 1；Idea/Implement/Eval=`1/1/3`；4h | `Running`，Evaluator Ready |
| `s42256-022-00468-6` | `famou-nb-s42256-022-00468-6-20260807-230635` | `nb-rerun-v5-s42256-022-00468-6-glm52-20260807-202616` | `glm-5.2`；GPU 1；Idea/Implement/Eval=`1/1/3`；4h | `Running`，Evaluator Ready |

本轮统一配置：IdeaSpark 容量 `3`、Evaluation Queue 容量 `3`、单次 canonical 与 evaluator 上限均为 `3600` 秒、Validity Judge 开启、剩余研究时间 1 小时时触发 Idea ranking、正式评测次数不设额外上限。

## 2026-08-07 Biology 批次

NatureBench 本地元数据中共有 `57` 个 `primary_domain=Biology` 的 task，而不是十几个：`3` 个 CPU、`44` 个 `gpu_low`、`10` 个 `gpu_high`。提交前逐一核验 `famou-public` 镜像仓库，当前只有 3 个 CPU task 的 `v1` 镜像存在，其余 54 个 task 镜像返回 404，不能直接提交。

| Task | fm-job | Run ID | 资源 | 初始状态 |
|---|---|---|---|---|
| `s41592-022-01709-7` | `famou-nb-s41592-022-01709-7-20260807-232557` | `bio-rerun-v1-s41592-022-01709-7-glm52-20260807-230900` | CPU 30；GPU 0；128 GiB | Controller 心跳正常，Evaluator Ready |
| `s41592-025-02870-5` | `famou-nb-s41592-025-02870-5-20260807-232557` | `bio-rerun-v1-s41592-025-02870-5-glm52-20260807-230900` | CPU 30；GPU 0；128 GiB | Controller 心跳正常，Evaluator Ready |
| `s43588-024-00689-2` | `famou-nb-s43588-024-00689-2-20260807-232557` | `bio-rerun-v1-s43588-024-00689-2-glm52-20260807-230900` | CPU 30；GPU 0；128 GiB | `Running`，Evaluator Ready |

尚未提交的 44 个 Biology task 需要先通过 `publish_task_images.sh` 构建并推送 task-specific 镜像。当前 Docker data root 是 `/var/lib/docker`；批次发布必须在推送后清理本地 task 镜像，并在批次之间检查根盘。

### Biology 镜像批次 01

以下 5 个 `gpu_low` 镜像已在第一批构建并推送，发布清单为 `.famou/naturebench-images/biology-batch01-20260807.json`，五个本地 task tag 均已清理：

| Task | fm-job | Run ID | 状态 |
|---|---|---|---|
| `s41467-025-63412-3` | `famou-nb-s41467-025-63412-3-20260808-002309` | `bio-rerun-v1-s41467-025-63412-3-glm52-20260808-001501` | 已提交，Evaluator Ready |
| `s41467-025-63418-x` | `famou-nb-s41467-025-63418-x-20260808-002309` | `bio-rerun-v1-s41467-025-63418-x-glm52-20260808-001501` | 已提交，等待资源/启动 |
| `s41467-025-65557-7` | `famou-nb-s41467-025-65557-7-20260808-002309` | `bio-rerun-v1-s41467-025-65557-7-glm52-20260808-001501` | 已提交，Evaluator Ready |
| `s41551-024-01312-5` | `famou-nb-s41551-024-01312-5-20260808-002309` | `bio-rerun-v1-s41551-024-01312-5-glm52-20260808-001501` | 已提交，等待资源/启动 |
| `s41587-024-02414-w` | `famou-nb-s41587-024-02414-w-20260808-002309` | `bio-rerun-v1-s41587-024-02414-w-glm52-20260808-001501` | 已提交，等待资源/启动 |

本批完成后，尚有 `49` 个 Biology task 需要构建镜像；根盘可用空间约 `202 GiB`。

### Biology 镜像批次 02

第二批 5 个镜像已完成构建、推送和本地 tag 清理，发布清单为 `.famou/naturebench-images/biology-batch02-20260808.json`：

| Task | 资源档位 | fm-job | Run ID |
|---|---|---|---|
| `s41587-024-02428-4` | `gpu_low` | `famou-nb-s41587-024-02428-4-20260808-011257` | `bio-rerun-v1-s41587-024-02428-4-glm52-20260808-002848` |
| `s41587-025-02585-0` | `gpu_low` | `famou-nb-s41587-025-02585-0-20260808-011257` | `bio-rerun-v1-s41587-025-02585-0-glm52-20260808-002848` |
| `s41587-025-02654-4` | `gpu_high` | `famou-nb-s41587-025-02654-4-20260808-011257` | `bio-rerun-v1-s41587-025-02654-4-glm52-20260808-002848` |
| `s41587-025-02688-8` | `gpu_low` | `famou-nb-s41587-025-02688-8-20260808-011257` | `bio-rerun-v1-s41587-025-02688-8-glm52-20260808-002848` |
| `s41592-023-01878-z` | `gpu_low` | `famou-nb-s41592-023-01878-z-20260808-011257` | `bio-rerun-v1-s41592-023-01878-z-glm52-20260808-002848` |

本批完成后，尚有 `44` 个 Biology task 需要构建镜像。

### Biology 镜像批次 03

第三批 5 个镜像已完成构建、推送和本地 task tag 清理，发布清单为 `.famou/naturebench-images/biology-batch03-20260808.json`。5 个 fm-job 均已提交并进入 `Running`：

| Task | 资源档位 | 镜像 | fm-job | Run ID | 初始状态 |
|---|---|---|---|---|---|
| `s41592-023-01940-w` | `gpu_low` | `naturebench-s41592-023-01940-w:v1` | `famou-nb-s41592-023-01940-w-20260808-012031-20260808-013927` | `bio-rerun-v1-s41592-023-01940-w-glm52-20260808-012031` | `Running` |
| `s41592-023-01955-3` | `gpu_low` | `naturebench-s41592-023-01955-3:v1` | `famou-nb-s41592-023-01955-3-20260808-012031-20260808-013948` | `bio-rerun-v1-s41592-023-01955-3-glm52-20260808-012031` | `Running` |
| `s41592-023-02032-5` | `gpu_low` | `naturebench-s41592-023-02032-5:v1` | `famou-nb-s41592-023-02032-5-20260808-012031-20260808-014023` | `bio-rerun-v1-s41592-023-02032-5-glm52-20260808-012031` | `Running` |
| `s41592-023-02035-2` | `gpu_low` | `naturebench-s41592-023-02035-2:v1` | `famou-nb-s41592-023-02035-2-20260808-012031-20260808-014041` | `bio-rerun-v1-s41592-023-02035-2-glm52-20260808-012031` | `Running` |
| `s41592-023-02124-2` | `gpu_low` | `naturebench-s41592-023-02124-2:v1` | `famou-nb-s41592-023-02124-2-20260808-012031-20260808-014055` | `bio-rerun-v1-s41592-023-02124-2-glm52-20260808-012031` | `Running` |

本批完成后，尚有 `39` 个 Biology task 需要构建镜像。每个任务的 Agent 研究预算为 4h；官方 evaluator 和最终 Judge 按队列排空策略在研究预算之后继续收尾。

## 详细证据入口

### `s42256-023-00611-x`

- 完整 Run 输出：[nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/)
- ExpBank 最佳方案：[expbank/0015](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/expbank/0015/)
- 完整冻结代码：[expbank/0015/code](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/expbank/0015/code/)
- 最佳提交产物：[candidate output/submission](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/candidates/candidate_1786098288616_ce8fe018/output/submission/)
- ExpBank 运行证据：[run.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/expbank/0015/evidence/run.json)
- ExpBank 评测证据：[evaluation.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/expbank/0015/evidence/evaluation.json)
- 官方数值 evaluator：[official_eval_1786098450178_12f8d6ba.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/artifacts/evaluator_scores/official_eval_1786098450178_12f8d6ba.json)
- Validity Judge：[judge_verdict.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/controller/judge_verdict.json)
- Judge 补跑证据：[judge_rerun_20260810_v3](../../.famou/naturebench-runs/nb-rel-v4-s42256-023-00611-x-glm52-20260807-141700/controller/naturebench_judge/judge_rerun_20260810_v3/)
- Judge 结果：`is_valid=true`；模型为 `claude-sonnet-4-6`，判定对象是 score attempt `15`、ExpBank attempt `0015`。旧版 `valid=null` 结果已单独备份。
- 主要瓶颈：`twin_mortality` 的 per-instance improvement 为负，拖低 aggregate。

### `s42256-024-00833-7`

- 完整 Run 输出：[nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/)
- ExpBank 最佳方案：[expbank/0007](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/expbank/0007/)
- 完整冻结代码：[expbank/0007/code](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/expbank/0007/code/)
- 最佳提交产物：[candidate output/submission](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/candidates/candidate_1786096884544_0c391d8f/output/submission/)
- ExpBank 运行证据：[run.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/expbank/0007/evidence/run.json)
- ExpBank 评测证据：[evaluation.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/expbank/0007/evidence/evaluation.json)
- 官方数值 evaluator：[official_eval_1786098508078_3b968270.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/artifacts/evaluator_scores/official_eval_1786098508078_3b968270.json)
- Validity Judge：[judge_verdict.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/controller/judge_verdict.json)
- Judge 补跑证据：[judge_rerun_20260810](../../.famou/naturebench-runs/nb-rel-v4-s42256-024-00833-7-glm52-20260807-143000/controller/naturebench_judge/judge_rerun_20260810/)
- Judge 结果：`is_valid=true`；模型为 `claude-sonnet-4-6`，判定对象是 score attempt `4`、ExpBank attempt `0007`。旧版 `valid=null` 结果已单独备份。
- 主要结果：官方 aggregate 只有轻微正提升，主要计入的 `ndc_hypergraph_maxcut` cut size 为 `28792`。

### `s42256-022-00556-7`

- 完整 Run 输出：[nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/)
- ExpBank 最佳方案：[expbank/0011](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/expbank/0011/)
- 完整冻结代码：[expbank/0011/code](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/expbank/0011/code/)
- 最佳提交产物：[candidate output/submission](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/candidates/candidate_1786093913349_e50a1d12/output/submission/)
- ExpBank 运行证据：[run.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/expbank/0011/evidence/run.json)
- ExpBank 评测证据：[evaluation.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/expbank/0011/evidence/evaluation.json)
- 官方数值 evaluator：[official_eval_1786097368524_97575c52.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/artifacts/evaluator_scores/official_eval_1786097368524_97575c52.json)
- Validity Judge：[judge_verdict.json](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00556-7-glm52-20260807-141700/controller/judge_verdict.json)
- Judge 结果：`valid=null`，原因是 Judge 侧找不到对应 task 根目录；`invalidate_primary_score=false`。
- 评测问题：分类 Accuracy 元数据单位是 `%`，官方 evaluator 返回 `[0, 1]` 小数，导致当前 aggregate 被错误压低。
- 需要保留的原始信息：`raw_scores`、`per_instance_improvement`、`stdout`、`stderr` 和 evaluator 原始响应均在 Run 目录中。

### `s42256-023-00630-8`

- 完整 Run 输出：[nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/)
- ExpBank 最佳方案：[expbank/0004](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/expbank/0004/)
- 完整冻结代码：[expbank/0004/code](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/expbank/0004/code/)
- 最佳提交产物：[candidate output/submission](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/candidates/candidate_1786094826482_bc621507/output/submission/)
- Agent 完整 stdout：[stdout.log](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/expbank/0004/evidence/stdout.log)
- ExpBank 运行证据：[run.json](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/expbank/0004/evidence/run.json)
- ExpBank 评测证据：[evaluation.json](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/expbank/0004/evidence/evaluation.json)
- 官方数值 evaluator：[official_eval_1786096453177_ea8f97c1.json](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/artifacts/evaluator_scores/official_eval_1786096453177_ea8f97c1.json)
- Validity Judge：[judge_verdict.json](../../.famou/naturebench-runs/nb-rel-v3-s42256-023-00630-8-glm52-20260807-134100/controller/judge_verdict.json)
- Judge 结果：`valid=null`，原因是 Judge 侧找不到对应 task 根目录。
- 工程问题：`raven` 写入了 14000 条预测，但 `i_raven/predictions.csv` 为空，不能据此判断模型算法无效。

### `s42256-022-00468-6`

- 完整 Run 输出：[nb-rel-v4-s42256-022-00468-6-glm52-20260807-141700](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00468-6-glm52-20260807-141700/)
- ExpBank：[expbank](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00468-6-glm52-20260807-141700/expbank/)
- 运行状态：[research_state.yaml](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00468-6-glm52-20260807-141700/research_state.yaml)
- 调度日志：[orchestrator.log](../../.famou/naturebench-runs/nb-rel-v4-s42256-022-00468-6-glm52-20260807-141700/logs/orchestrator.log)
- 官方数值 evaluator：未生成。
- Validity Judge：未生成。
- 当前队列：3 个 `failed`、1 个 `running`、2 个 `waiting_resources`。
- 结论：任务状态是异常残留的 `running`，没有官方分数，不能归类为未达到 SOTA；需要修复收尾逻辑后重跑。

## 当前全量未 Match 诊断（2026-08-17）

本节是基于 [`CURRENT_RESULTS_CN.md`](CURRENT_RESULTS_CN.md) 的当前快照，覆盖当前主表中全部
49 个“可信未 Match” case；它取代“历史 v5 快照：26 个”作为当前诊断入口。任务 ID、domain、
正式 `g`、Judge、当前采用 Run 和当前动作均直接以当前主表对应行作为准确信息，避免在本日志中
复制另一份容易过期的结果表。

### 诊断口径

这 49 个 case 均满足有限官方分数、完整实例覆盖和 Judge Valid，因此当前证据支持的结论是：
**现有 Agent solution 在该任务上没有达到 Match-SOTA**。这不是说已经证明数据或 evaluator
绝对没有问题；若某个 case 存在外部证据（官方 GT 缺失、`partial_errors`、实例缺失、提交合同
不完整），它不会被纳入这 49 个可信未 Match，而会留在当前表的“数值不可信”或“待重跑”状态。

### 按优先级的诊断

| 诊断级别 | 判定 | 处置 |
|---|---|---|
| 严重落后 | `g <= -1`，或已知单项指标出现灾难性退化 | 优先检查子指标/实例分解；默认考虑换方法或 fuse，不把低收益 refine 作为唯一动作 |
| 明显落后 | `-1 < g <= -0.3` | 检查最差实例、最差子指标和候选完整性，再决定 refine 或 switch |
| 轻度落后 | `-0.3 < g < 0` | 优先做针对最差子指标的局部修正，并保留当前最佳候选作为回退 |

当前主表的 49 行就是本诊断的完整 case 清单；每一行的“当前动作”记录了该 case 是否已闭环、
是否需要重跑以及当前采用的 Run。对于“已闭环”但没有进一步子指标证据的 case，本节只下“可信
方法差距”结论，不臆造具体算法根因。下一轮诊断应从对应 Run 的
`controller/final_evaluation.json`、`artifacts/evaluator_scores/` 和
`per_instance_improvement` 补齐最差实例与子指标原因，并回写到本日志的新增批次小节。

历史 v5 的 26-case 逐项文字分析继续保留，作为其中一部分的详细证据，不再作为当前全量统计。

### 当前 49 个 case 的子指标证据



### 当前 49 个 case 的子指标证据

下表直接来自当前采用 Run 的 `official.extra.per_instance_improvement`。`最差` 是该任务中
相对 SOTA 最落后的实例/子指标，`最好` 是相对表现最高的实例/子指标；差距用于判断是否是
单个子指标拖累 aggregate。所有数值均为相对 SOTA 的 improvement，负数越小表示越差。
“指标是否有效”依据 numeric evaluator 的 `all_primary_instances_valid`、有限分数和错误字段判断；
这 49 个 case 都是可信结果，因此该列均为“是”。

| Case | 最差实例/子指标 | 最好实例/子指标 | 子指标差距 | 指标是否有效 |
|---|---|---|---:|---|
| `s41467-025-63418-x` | `human_hippocampus` -0.601 | `simulated_breast_cancer` -0.428 | 0.173 | 是 |
| `s41467-025-64512-w` | `mutation_effect` -0.656 | `bernett` -0.016 | 0.640 | 是 |
| `s41587-024-02414-w` | `yeast_promoter` -0.492 | `yeast_promoter` -0.492 | 0.000 | 是 |
| `s41587-024-02428-4` | `ppi_interface_benchmark` -0.090 | `ppi_interface_benchmark` -0.090 | 0.000 | 是 |
| `s41587-025-02585-0` | `codex_large_scale` -0.912 | `codex_small_scale` -0.770 | 0.142 | 是 |
| `s41587-025-02654-4` | `benchmark_ii` -0.494 | `benchmark_i` -0.437 | 0.058 | 是 |
| `s41592-022-01709-7` | `cross_species` -0.284 | `bone_marrow` -0.026 | 0.258 | 是 |
| `s41592-023-01878-z` | `simulated_validation` -1.000 | `simulated_generalization` -0.992 | 0.008 | 是 |
| `s41592-023-01940-w` | `refseq_r202` -1.316 | `refseq_r202` -1.316 | 0.000 | 是 |
| `s41592-023-02032-5` | `benchmark` -0.774 | `sars_cov2` -0.754 | 0.020 | 是 |
| `s41592-023-02035-2` | `lung` -0.122 | `pancreas` -0.009 | 0.113 | 是 |
| `s41592-024-02191-z` | `frog_zebrafish` -0.797 | `frog_zebrafish` -0.797 | 0.000 | 是 |
| `s41592-024-02257-y` | `her2` -0.841 | `dlpfc` -0.309 | 0.532 | 是 |
| `s41592-024-02372-w` | `benchmark` -3.478 | `benchmark` -3.478 | 0.000 | 是 |
| `s41592-024-02523-z` | `splice_sites_all` -0.671 | `H3K4me3` -0.096 | 0.575 | 是 |
| `s41592-025-02662-x` | `dna_fish` -0.571 | `synthetic_simple` -0.013 | 0.558 | 是 |
| `s41592-025-02665-8` | `sim_diffusion_3d` -0.503 | `sim_diffusion_2d` -0.486 | 0.018 | 是 |
| `s41592-025-02820-1` | `contact_rpr_ir` -1.000 | `experimental_dms` -0.983 | 0.017 | 是 |
| `s41592-025-02826-9` | `codex_colon` -0.418 | `mibi_breast` -0.093 | 0.325 | 是 |
| `s41592-025-02854-5` | `onek1k_eqtl` -0.957 | `neurips_hematopoiesis` -0.861 | 0.097 | 是 |
| `s41592-025-02886-x` | `mskcc_confocal` -174.912 | `nih_ls` -1.000 | 173.912 | 是 |
| `s41592-025-02893-y` | `mice_2d` -2190.070 | `df3d` -1.368 | 2188.702 | 是 |
| `s41592-025-02924-8` | `multi_region_simulated` -0.682 | `multi_region_simulated` -0.682 | 0.000 | 是 |
| `s42256-022-00464-w` | `ks_l22` -0.984 | `fhn` -0.328 | 0.655 | 是 |
| `s42256-022-00501-8` | `freesolv` -0.567 | `bindingdb` +0.007 | 0.574 | 是 |
| `s42256-022-00518-z` | `hp_integration` -0.571 | `hp_mapping` +0.000 | 0.571 | 是 |
| `s42256-022-00526-z` | `uspto_480k` -0.933 | `uspto_480k` -0.933 | 0.000 | 是 |
| `s42256-022-00534-z` | `pancreas_xin` -0.306 | `pancreas_muraro` -0.015 | 0.290 | 是 |
| `s42256-022-00541-0` | `pdtc` -0.412 | `clinical_diagnosis` -0.184 | 0.229 | 是 |
| `s42256-023-00627-3` | `ibd` -0.434 | `cystic_fibrosis` -0.153 | 0.281 | 是 |
| `s42256-023-00630-8` | `i_raven` -1.000 | `raven` -0.908 | 0.092 | 是 |
| `s42256-023-00654-0` | `qm9` -0.911 | `tox21` -0.016 | 0.896 | 是 |
| `s42256-023-00712-7` | `crossdock` -0.107 | `crossdock` -0.107 | 0.000 | 是 |
| `s42256-024-00790-1` | `xrd_cdw` -0.231 | `xrd_cdw` -0.231 | 0.000 | 是 |
| `s42256-024-00795-w` | `uniprotkb_swissprot_bpo` -0.192 | `uniprotkb_swissprot_cco` -0.060 | 0.132 | 是 |
| `s42256-024-00836-4` | `ts0` -0.485 | `nrc` +0.033 | 0.518 | 是 |
| `s42256-024-00838-2` | `cameo` -1.000 | `cameo` -1.000 | 0.000 | 是 |
| `s42256-024-00892-w` | `simulated` -0.985 | `simulated` -0.985 | 0.000 | 是 |
| `s42256-024-00916-5` | `drd2_qed` -0.697 | `admet` -0.648 | 0.048 | 是 |
| `s42256-024-00956-x` | `3bpa_300k` -3.970 | `3bpa_dihedral` +0.274 | 4.244 | 是 |
| `s42256-025-01003-z` | `custom_nanopore` -18.211 | `erlich_illumina` -0.042 | 18.169 | 是 |
| `s42256-025-01010-0` | `transition1x` -3.108 | `transition1x` -3.108 | 0.000 | 是 |
| `s42256-025-01019-5` | `hc_pt` -1.000 | `hc_pt` -1.000 | 0.000 | 是 |
| `s42256-025-01042-6` | `ts50` -0.660 | `cath_4_3` -0.605 | 0.054 | 是 |
| `s43588-024-00716-2` | `s669` -0.106 | `s571` -0.074 | 0.032 | 是 |
| `s43588-024-00730-4` | `atomic_spectra` -297.564 | `biradical_st_gap` -30.277 | 267.287 | 是 |
| `s43588-025-00903-9` | `eat` -1.167 | `mar1` +0.111 | 1.279 | 是 |
| `s43588-025-00917-3` | `sunset_1` -2.355 | `sunset_1` -2.355 | 0.000 | 是 |
| `s43588-025-00920-8` | `cpa_thiol` -3.024 | `cpa_catalyst` -0.008 | 3.016 | 是 |

这张表给出了“哪里差”的细粒度证据，但不把它误写成“为什么差”。例如 `s41592-025-02893-y`
的 `mice_2d=-2190.070` 属于单项灾难性拖累，应优先检查该子任务的输出格式、数值尺度和
预测分布；而 `s41587-024-02414-w` 的唯一子任务本身为 `-0.492`，属于整体方法差距，不能
归因于指标不均衡。后续算法诊断必须在此表基础上结合 solution、原始预测和 evaluator 日志，
逐项标注“算法能力不足 / 输出格式或尺度 / 数据覆盖 / evaluator 外部问题”。

### `-1.0` 的解释

表中的 improvement 恰好为 `-1.0` 不能单独判定指标无效。它可能是一个有效的归一化结果，
也可能在某些官方聚合字段中表示缺失实例的哨兵值；必须同时看 evaluator 的 validity、实例
覆盖和 raw score。当前这 49 个 case 已经过可信筛选，表中出现的 `-1.0` 均标为“指标是否
有效=是”，表示指标有效但结果很差。若是缺失实例、NaN/Inf、格式错误或 evaluator error，
候选会被标为无效，不会进入当前 49 个可信未 Match 集合。

## 2026-08-18 Idea/Implement Prompt v2 典型 case 结果

配置：Claude Code + `deepseek-v4-pro`，Idea/Implement 均使用 prompt v2，并发 `2/2/4`，
研究墙钟预算 4 小时。三条 Run 均正常完成 evaluation drain 和最终 Judge；fm-job 显示
`Failed` 是 Harness 将正常的墙钟预算结束保留为 `stopped`、CLI 随后返回 1 的状态映射问题，
不是实验或 evaluator 失败。

| Case | v2 数值 g | Judge | 与当前正式结果比较 | 采纳结论 | Run |
|---|---:|---|---|---|---|
| `s41592-025-02893-y` | -199.799066 | Valid | 旧值 -244.524692，提升 44.725626 | 采纳 v2；仍未 Match | `rerun-v2b-claude-deepseek-02893-20260817` |
| `s41592-024-02372-w` | +0.369267 | Invalid | 数值看似 Surpass，但通过文件名 PWM ID 映射训练标签，属于 target extraction | 不采纳；保留旧值 -3.072213 | `rerun-v2b-claude-deepseek-02372-20260817` |
| `s42256-024-00956-x` | -1.249800 | Valid | 低于当前正式最佳 -0.528262 | 不采纳；保留旧最佳 | `rerun-v2d-claude-deepseek-00956-20260817` |

`s41592-025-02893-y` 的 v2 方法由训练数据拟合 multi-expert skeleton imputation，包含
双向 GRU、skeleton GCN residual、pose autoencoder、trajectory PCA 和 iterated SVD；Judge
确认不是硬编码或 target extraction。虽然可信提升明显，`mice_2d` 与 `rat7m` 仍是主要短板。

## 统一证据结构

每个任务的完整 Run 根目录应作为审计入口，重点目录含义如下：

| 路径 | 内容 |
|---|---|
| `research_state.yaml` | 任务状态、预算、并发和最终生命周期 |
| `problem/` | Agent 可见的公开题面和公开数据视图 |
| `expbank/` | 每个 Idea、实现版本、结论和证据汇总 |
| `candidates/` | Candidate 冻结代码运行后的 canonical output |
| `artifacts/experiment_run/` | canonical run 的 stdout、stderr、资源和终止原因 |
| `artifacts/evaluator_scores/` | 官方 evaluator 原始响应和 Agent 脱敏视图 |
| `controller/final_evaluation.json` | 最终 Judge 汇总；历史运行可能记录旧版 task 根目录定位错误 |
| `controller/judge_verdict.json` | Validity Judge 判定及是否否决主分数 |
| `controller/trajectory.jsonl` | 完整 Controller/Agent/提交/评测轨迹，若该 Run 已生成 |
| `logs/` | Controller、Agent 和调度日志 |

## 修复状态与剩余项

1. **已明确：三类时间预算相互独立。** NatureBench 官方代码规定每份 solution 的数值 evaluator 子进程上限为 `3600s`。ImplementAgent 单次激活时间和 Candidate canonical run 时间均由 Famou 独立配置，不是 NatureBench 的官方限制；当前配置可以同为 `3600s`，也可以按任务调整。canonical 上限已进入 Agent request，并会拒绝 Agent 明确声明的超限实现。
2. **已完成：指标单位与反馈。** Adapter 已按公开 metadata 统一 Accuracy 的 `%` 与 `[0, 1]`，同时保留 `raw_scores` 和 `normalized_raw_scores`。ImplementActor mailbox 会收到分项原始指标、`per_instance_improvement`、`aggregate_improvement`、历史最佳总分和最佳 attempt；Idea Agent 可通过 ExpBank 读取同一批历史证据。
3. **按设计保持：Smoke Test 属于 Agent 行为。** ImplementAgent 根据 instruction 自行决定并执行轻量 Smoke Test，完整 CLI 轨迹、命令输出和分支日志只用于事后审计。Controller 不增加专门的 Smoke Test gate，也不要求 `submit_candidate` 证明 Agent 执行过测试；`submit_candidate` 只负责显式提交、基础契约校验和冻结 Candidate，真正的运行结果由后续 canonical run 与官方 evaluator 给出。
4. **已完成：两条旧 Judge 失败补判。** `s42256-023-00611-x` 与 `s42256-024-00833-7` 均已使用正确 task root 和 `claude-sonnet-4-6` 补判为 `is_valid=true`，新旧证据均已留存。后续提交包需要纳入新 verdict。
5. **部分完成：Controller 异常退出恢复。** 这里的“异常退出”特指顶层 Loop Controller 因 `SIGKILL`、容器或节点退出、机器重启、未捕获异常等原因终止，不是 Agent CLI 非零返回、canonical 失败或 evaluator 失败。再次启动同一 Run 时，现有恢复逻辑会把遗留 `running` 条目重新入队，`waiting_resources` 会继续等待资源；剩余缺口是永久不再恢复时，尚无独立 finalizer 统一记录中断原因、终结残留状态并生成最终 `run_summary.json`。
