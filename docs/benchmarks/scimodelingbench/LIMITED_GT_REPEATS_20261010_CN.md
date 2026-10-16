# SciModelingBench 有限 GT：三次重复实验与补评记录

更新日期：2026-10-10。首轮设计、三张诊断图与任务说明见[首轮报告](LIMITED_GT_EXPERIMENT_20261009_CN.md)。

三个黑盒任务 × 四个预算 k=0/1/5/20 × 三次独立重复，共 36 个运行。第 2、3 次新增 24 个作业均已提交并结束研究。模型、提示协议、数据快照及资源沿用首轮：glm-5.2、Claude CLI / Famou Loop、8 CPU、0 GPU、32 GiB，每次最多 2 小时。各次均从独立工作目录开始。

## 统一结果口径：best-score

本实验的主结果、曲线和跨重复统计统一使用 **best-score**，即每次运行所有有效研究 GT 查询的主指标与最终审计主指标中的最大值；k=0 使用最终审计。已有有效查询分数不因最终 `select` 失败或选择了更差批次而失效。不对未经评测的遗留文件事后遍历挑优。

这里是在**不同提交批次之间**取主指标最大值，不是评测器 `metrics.best_score` 表示的单批次最佳候选值。原始 CSV 的 `best_score` 是本文主指标；`protocol_final_score`、`reported_score` 只保留为最终选择与历史汇总的追溯字段，不用于本文主结果比较。

36 次运行中，31 次有该口径的 best-score，4 次 NAS 运行没有任何有效分数，另 1 次 Pho4-k5-r1 只有事后补评 −0.035707。该补评分数在表中以 †、图中以空心菱形展示：它是对遗留文件的有效评测，但没有研究查询或被接受的最终审计分数，故保留 `supplemental_score` 来源，不混入 `best_score` 均值。缺失不填零；未完成最终选择本身不是丢弃已有 GT 最高分的理由。

## 三次重复的最高分曲线

![三个任务的三次独立重复，横向 1×3 排列](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/docs/benchmarks/scimodelingbench/limited_gt_blackbox_20261009/three_repeats_best_score_1x3_styled.png)

[直接打开图片](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/docs/benchmarks/scimodelingbench/limited_gt_blackbox_20261009/three_repeats_best_score_1x3_styled.png)

**图注：** 三个黑盒优化任务，每个预算组独立运行三次，每次研究最多 2 小时。

每个任务一个子图，青绿圆点、玫红方点、蓝色三角分别表示第 1、2、3 次重复。点旁同色数字为实际研究 GT 次数（含无效调用，不含最终审计及补评），不是分数；分数读取纵轴。横轴为预算 k=0/1/5/20，按预算组等距排列，各子图纵轴范围独立。

图与下表统一使用 **best-score**。例如 Pho4-k20-r3 记录 **0.280391**；其最终选择审计为 0.071343，仅作为交接问题的过程记录，不替代主结果。各预算组独立运行，曲线不代表同一运行逐步增加预算。

NAS 的有效分数连成折线，跨过无效 k=1 的区段用虚线连接；虚线仅关联已有有效结果，不表示无效点有分数。NAS-k1 三次与 NAS-k20-r2 的 GT 次数后用 × 表示提交无效；第二次折线止于 k=5，因为 k=20 没有有效终点。Pho4-k5-r1 的 −0.035707 以空心菱形单列，表示仅有补评。TFBind8-k20-r3 的 0.973723 按统一 best-score 规则纳入；星号只提示其没有已接受的最终选择，不表示它使用另一种计分规则。各预算组分数不保证单调上升。

[高清 PNG](limited_gt_blackbox_20261009/three_repeats_best_score_1x3_styled.png) · [矢量 PDF](limited_gt_blackbox_20261009/three_repeats_best_score_1x3_styled.pdf) · [绘图脚本](plot_limited_gt_repeats.py)

## 全部运行结果

下表为 **best-score**。★ 表示已有研究 GT 最高分但没有已接受的最终选择；† 表示仅有补评的附列数值，不作为 best-score；— 表示没有有效分数。

| 任务 | k | 第 1 次 | 第 2 次 | 第 3 次 | 实际研究 GT 次数（r1/r2/r3） |
|---|---:|---:|---:|---:|---|
| tfbind8 | 0 | 0.921183 | 0.948268 | 0.950439 | 0 / 0 / 0 |
| tfbind8 | 1 | 0.975609 | 0.937468 | 0.957453 | 1 / 1 / 1 |
| tfbind8 | 5 | 0.963992 | 0.975751 | 0.970678 | 5 / 5 / 5 |
| tfbind8 | 20 | 0.977710 | 0.968214 | 0.973723★ | 15 / 16 / 4 |
| tfbind10_pho4 | 0 | 0.040566 | 0.261773 | 0.109933 | 0 / 0 / 0 |
| tfbind10_pho4 | 1 | 0.145511 | 0.129138 | 0.079535 | 1 / 1 / 1 |
| tfbind10_pho4 | 5 | -0.035707† | 0.179990 | 0.118690 | 0 / 5 / 5 |
| tfbind10_pho4 | 20 | 0.055380 | 0.106005 | 0.280391 | 3 / 5 / 16 |
| cell_dag_nas | 0 | 0.900775 | 0.900775 | 0.900775 | 0 / 0 / 0 |
| cell_dag_nas | 1 | — | — | — | 1 / 1 / 1 |
| cell_dag_nas | 5 | 0.937854 | 0.932706 | 0.931677 | 5 / 5 / 5 |
| cell_dag_nas | 20 | 0.933681 | — | 0.926282 | 16 / 2 / 4 |

## TFBind10 第二次重复：为什么 k=0 最高

**这次 k=0 运行发现并采用了效果更好的候选选择策略：利用公开数据的低亲和力划分，训练“公开／未公开”分类器。其他预算组走了不同的回归或邻域搜索路径，因此不能把这条曲线解释为增加 GT 导致分数下降。** 以下分析依据控制器记录、实际工具调用和冻结提交，不只依据 Agent 的最终自述。

### 分数与候选核对

四组公开 `observations.jsonl` 的 SHA-256 均为 `d3649e1a243219388468ba8c79c86032cd4cdc36efd8b5ccc21c4ccb35498a74`，输入数据相同；整份运行目录的摘要会受路径和预算信息影响，不能代替观测文件比较。

| k  | 实际研究 GT 次数 |   best-score | 最终整批官方效用均值 | 最终候选策略                                                        |
| -- | ---------------: | -----------------: | -------------------: | ------------------------------------------------------------------- |
| 0  |                0 | **0.261773** |   **0.440565** | 公开／未公开划分的逻辑回归分类器，选预测概率最高的 128 条未公开序列 |
| 1  |                1 |           0.129138 |             0.230124 | 回归集成查询后，改为高分公开序列的突变邻居与位置模式候选混合        |
| 5  |                5 |           0.179990 |             0.310807 | 逐步转向前 8 个公开亲本的单点突变邻居，按亲本质量为主筛选           |
| 20 |                5 |           0.106005 |             0.193421 | 对数富集度的 Ridge + LightGBM 回归集成；最终保留早期已接受的选择    |

本节第二次重复的四组 best-score 恰好都与最终审计相同，所以下述最终候选分析也对应各组最高分。四份冻结的最终提交均为 **0 条公开、128 条未公开序列**。k=0 的高分并非直接提交公开训练集中的已知高分答案；控制器 `queries=[]`，仅在选择锁定后做最终审计，未向 Agent 提供研究 GT 反馈。

### TFBind10 k=0 实际采用了什么方法

Agent 起初也训练了 Ridge、LightGBM、成对特征回归和神经网络，随后转向另一种信号。公开 manifest 明确说明观测来自可信后验亲和力的较低一半；10 个碱基的完整空间又可以直接枚举（`4^10 = 1,048,576`）。Agent 从公开文件读出 **524,300** 个不同序列，再用全集减去公开集得到 **524,276** 个未公开序列，以“公开=0、未公开=1”构造分类标签。

最终方法用 40 维碱基位置 one-hot 特征训练逻辑回归（`C=1.0`、`max_iter=1000`），按预测属于未公开组的概率排序，选前 128 条。冻结提交与 `submission_lr_only.json` 完全一致，前三条为 `CCCGGCCCCA`、`CCCGGCCCCC`、`CCAGGCCCCA`。这些候选中 C 占 66.72%、G 占 19.45%；k=20 最终批次则 C 占 2.66%、G 占 65.47%，说明两次搜索落在明显不同的序列区域。碱基比例仅描述这两批候选，不表示 C 越多必然越好。

**机制解释：按目标值筛选公开数据，使“是否被公开”本身携带了与官方目标相关的粗粒度监督信号。** k=0 限制的是研究阶段 GT 接口调用，并没有移除公开划分所透露的信息。分类器可以学习这条划分边界，即使没有获得任何隐藏的逐序列真实分数，也有机会找到较好的候选。这是当前数据划分的一项可利用性质，应在解释“零 GT”结果时明确记录。

分类概率不等于亲和力值；即使知道一个序列处于较高分组，也不能直接知道它在该组内的真实排名。因此这一机制提供了合理解释，并不证明分类器必然优于回归。Agent 自述的“没有外推问题”也过强：对极端高分区域的排序仍需最终 GT 检验。

### 更多 GT 为什么没有在这次超过它

**GT 在 k=1、k=5 的各自运行内实际帮助了改进。** k=1 首次查询的 G-rich 回归候选得分 0.072956，收到反馈后改变候选策略，最终审计为 0.129138。k=5 五次查询依次为：

```text
0.051871 → 0.132945 → 0.166647 → 0.162805 → 0.179990
```

k=5 从回归集成转向公开高分亲本的邻域搜索，最终选用了第五次查询的候选。它相对于自身首批明显改善，只是未达到另一独立运行中分类器找到的 0.261773。这也说明“增加一次查询后产生的新批次”可以变差；只有同一运行的累计最高分才保证不下降。

**k=20 是允许最多 20 次，实际只有 5 次。** 其查询依次为：

```text
0.106005 → 0.039585 → 0.087742 → 0.084887 → 0.091400
```

后续尝试了公开／未公开候选混合、多样性筛选、近邻与模型候选混合，均未超过第一批。截止前保留的选择与首次查询内容一致，补充最终审计得到同样的 0.106005。因此本组低分既不能解释成“用了 20 次仍更差”，也不是最终误选了低于历史最高分的批次。

还有两个会限制 GT 收益的具体因素。第一，GT 只返回整批聚合指标，不返回 128 条序列各自的真实标签；几次查询不足以直接训练一个有大量新标注的代理模型。第二，公开的平均 DDG、简单读数比值与官方后验效用并不完全相同，且公开数据按较低亲和力截断，公开集上的回归表现不能保证极端候选的质量。k=5 后期还多次把提高辅助指标 `prefix_k_mean` 作为查询理由；主指标实际取全部 128 条的平均效用，**仅改变相同候选的顺序不会提高主分数**。这些查询也改变了候选集合，因此观察到的主分数变化不能归因于重排本身。

### k>0 是否利用 GT 修正了代理模型

**第二次重复的 k=1、5、20 都在收到 GT 后调整过代理建模或候选策略，也确实重训过模型。** 但要区分“GT 反馈促使 Agent 改建模方案”和“把 GT 数据直接加入代理训练”：从这些运行的训练代码和工具轨迹看，重训标签仍来自公开观测，未发现将查询得到的聚合 GT 分数直接写入训练标签、校准损失或批次约束。

| 第二次重复 | GT 后的代理模型修改                                                                                             | GT 后的候选选择修改                                                                           |
| ---------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| k=1        | 首次 GT 为 0.072956 后，从 DDG 预测改试直接预测公开读数计算的富集度，重训 LightGBM 与 Ridge                     | 新模型仍偏向原有 G-rich 模式，最终转向公开高分序列的突变邻居与位置模式候选；最终审计 0.129138 |
| k=5        | 首次 GT 为 0.051871 后，比较平均／最小 DDG、对数富集度等目标，加入读数权重，再增加三碱基、成对及 C 含量特征重训 | 后续主要调整亲本范围、邻域和模型预测权重；GT 用于比较整批方案，最后选用 0.179990 的第五批     |
| k=20       | 首次 GT 为 0.106005 后，改试经平滑修正的富集度目标、四碱基特征，重训 Ridge 与 LightGBM；还尝试多个训练目标      | 依次比较混合公开候选、多样性约束、近邻及模型／近邻混合；后续均未超过第一批，最终保留第一批    |

因此，这些运行存在“GT 反馈 → Agent 修改目标／特征／搜索方法 → 用公开数据重训 → 再比较候选”的闭环。它们没有形成已核实的“GT 返回每条序列标签 → 将新 `(x,y)` 加入训练集”的主动学习流程，因为接口不返回逐候选标签。理论上也可用批次均值构造聚合监督损失，或训练批次级代理，但本次这三个运行未见这种实现，不能把它们的模型修改描述为直接用隐藏 GT 拟合代理。

k=0 的分类器在这次最终候选选择上更有效，并不意味着它的整体预测误差已被证明更小；其输出是划分概率，而其他模型主要预测 DDG 或富集度，训练目标不同。这里能够比较的是冻结候选的最终官方得分。

代码与时序依据：[k=1 富集度重训](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k1-r2/limited_gt_agents/branches/researcher/worktree/train_enrichment_model.py)、[k=5 多目标与读数加权训练](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k5-r2/limited_gt_agents/branches/researcher/worktree/build_model_v2.py)、[k=5 特征修改](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k5-r2/limited_gt_agents/branches/researcher/worktree/build_model_v3.py)、[k=20 平滑目标与四碱基特征](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k20-r2/limited_gt_agents/branches/researcher/worktree/run_v3.py)、[k=20 多目标模型](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k20-r2/limited_gt_agents/branches/researcher/worktree/run_v4.py)。模型改动发生在收到反馈后的 CLI 轮次；k=20 的 MLP 尝试因训练慢而转为 Ridge + LightGBM，不能把脚本中所有定义的模型都算作最终使用的模型。

### 能得出什么结论

本次证据支持“搜索策略差异、数据划分信号以及 GT 的实际使用方式共同影响结果”。它不支持“GT 越少越好”的因果结论：同一重复编号下的四组是四个独立 Agent 运行，没有共享同一初始候选、同一模型或同一搜索轨迹；固定的是时间上限，并非实际投入时长或算法。

三次重复也显示较大波动：k=0 的分数分别为 **0.040566、0.261773、0.109933**；k=20 第三次的历史最高分为 **0.280391**，超过这里的 k=0 第二次。按图中最高分口径，k=0 的三次均值±样本标准差为 **0.137424±0.113137**，k=20 为 **0.147259±0.118042**（均为 n=3）。这些描述统计统一使用 best-score，尚不足以确认预算收益。

复核入口：

- [公开数据划分说明](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k0-r2/problem/manifest.json)；[GT 反馈契约](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k0-r2/problem/metric_contract.json)。
- [k=0 实际工具轨迹](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k0-r2/limited_gt_agents/branches/researcher/outputs/implement_agent_1791555728573_641bd52a.result.claude_agent_trajectory.jsonl)：`sequence=182` 构造完整公开／未公开分类数据并生成 LR 候选，`sequence=217` 将 LR 候选复制为最终提交。最终分类器来自这些内联命令，不能只读遗留 `run.py` 来判断方法。
- [k=0 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k0-r2/controller/limited_gt/state.json)、[k=1 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k1-r2/controller/limited_gt/state.json)、[k=5 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k5-r2/controller/limited_gt/state.json)、[k=20 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k20-r2/controller/limited_gt/state.json)。
- [k=5 最终邻域筛选代码](../../../.famou/scimodelingbench-fmjob-runs/tfbind10_pho4-limited-gt-huayan-20261009-k5-r2/limited_gt_agents/branches/researcher/worktree/create_final_v3.py)；[三次重复统计](limited_gt_blackbox_20261009/all_repeats_grouped.csv)。

复核时另发现，Agent 自述将约 0.876 的 AUC 归给了逻辑回归；实际早期日志中的 LR AUC 为 0.8544，0.8765 属于 LightGBM 分类器，最终按完整公开集合重训的 LR 没有单独报告新的交叉验证 AUC。本分析不使用该自述数值来论证最终候选质量。

## TFBind8 与 NAS：GT 后是否调整了代理模型或搜索

以下逐项核查范围为**第二次重复（r2）的 k=1/5/20**，与上文 TFBind10 的过程分析一致，不代表三次重复都采用相同方法。模型重训、候选搜索调整和修复无效提交是不同操作；发生过调整，不等于代理模型的预测精度已经提高。

| 任务        |  k | 实际 GT 次数（有效次数） | 收到 GT 后的模型或搜索调整                                                                                          | 已验证结果                                                                    |
| ----------- | -: | -----------------------: | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| TFBind8     |  1 |                   1（1） | 重训更大的 Ridge／LightGBM／XGBoost 集成，尝试新候选及高斯过程建模                                                  | 新候选没有剩余额度验证；最终选回原先已通过 GT 的批次，分数 0.937468           |
| TFBind8     |  5 |                   5（5） | 主要利用 GT 比较序列模式、反向互补配对和候选组合，逐步调整 GATA 相关候选的搜索范围；不能据此断言每轮都重训模型      | 首次 0.973832，最终采用 0.975751                                              |
| TFBind8     | 20 |                 16（16） | 收到反馈后尝试模型调整，随后主要通过候选分组查询、单点／双点突变邻域搜索和批次替换寻找更好的序列组合                | 首次 0.922032，最终采用 0.968214                                              |
| CellDAG-NAS |  1 |                   1（0） | 查询前已训练代理并搜索未公开架构；唯一查询无效后，改回公开候选，没有准确率反馈用于校准代理                          | 最终仍因重复架构无效，没有有效分数                                            |
| CellDAG-NAS |  5 |                   5（4） | 首次无效后先修复重复架构；获得有效基线后训练 XGBoost 代理，扩大并聚焦架构候选搜索，结合 GT 比较混合批次与纯搜索批次 | 有效分数依次为 0.900775 → 0.930722 → 0.932392 → 0.932706，最终采用最后一批 |
| CellDAG-NAS | 20 |                   2（0） | 两次查询均无效，后续排查规范图去重，并尝试改用规范图特征建模；没有有效准确率反馈验证这些调整                        | 最终快照 32 项仅 14 个不同规范架构，补评仍无效                                |

**TFBind8 的有效反馈主要帮助 Agent 改进候选搜索和批次选择；NAS-k5 则经历了提交修复、代理建模和搜索改进。** NAS-k1 与 NAS-k20 没有拿到有效分数，不能描述为“GT 分数驱动的代理优化成功”。特别是 NAS-k1 的 Agent 曾把无效反馈解释成未公开架构无法评估，但无效提交不能支持这个结论，实际还存在重复架构问题。

这些 GT 调用仍只返回整批聚合指标，不返回逐候选标签。TFBind8-k20 的分组查询是在尝试从不同批次的分数差异推断哪些候选更好；这类推断不等于直接获得了每条序列的真实标签，也不应仅凭 Agent 的自述认定其定位准确。表中的分数提升能够证明最终候选批次更好，不能单独证明代理模型的整体预测误差下降。

复核入口：

- TFBind8：[k=1 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind8-limited-gt-huayan-20261009-k1-r2/controller/limited_gt/state.json)、[GT 后的集成模型代码](../../../.famou/scimodelingbench-fmjob-runs/tfbind8-limited-gt-huayan-20261009-k1-r2/limited_gt_agents/branches/researcher/worktree/run_improved.py)、[k=5 查询与选择记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind8-limited-gt-huayan-20261009-k5-r2/controller/limited_gt/state.json)、[k=20 分组与邻域查询记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind8-limited-gt-huayan-20261009-k20-r2/controller/limited_gt/state.json)。
- NAS：[k=1 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/cell_dag_nas-limited-gt-huayan-20261009-k1-r2/controller/limited_gt/state.json)、[k=5 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/cell_dag_nas-limited-gt-huayan-20261009-k5-r2/controller/limited_gt/state.json)、[k=5 代理搜索代码](../../../.famou/scimodelingbench-fmjob-runs/cell_dag_nas-limited-gt-huayan-20261009-k5-r2/limited_gt_agents/branches/researcher/worktree/search.py)、[k=5 扩展候选代码](../../../.famou/scimodelingbench-fmjob-runs/cell_dag_nas-limited-gt-huayan-20261009-k5-r2/limited_gt_agents/branches/researcher/worktree/generate_more.py)、[k=20 控制器记录](../../../.famou/scimodelingbench-fmjob-runs/cell_dag_nas-limited-gt-huayan-20261009-k20-r2/controller/limited_gt/state.json)。

## 最高分与最终交接的区别

- **Pho4-k20-r3：主结果为 0.280391。** 第 13 次查询取得该分数。Agent 随后在同一 CLI 回合先写 `select`，又用 `query` 覆盖动作文件，控制器没有接受新的选择；最后 `finish` 锁定早期第二次查询对应的批次，审计为 0.071343。这个交接失败不抹除已经验证的最高分。
- **Pho4-k5-r1：只有补评 −0.035707。** 研究 GT 使用 0 次，Agent 写 `select` 后未结束回合交接，超时前没有被接受的最终快照。之后只补评它指定的遗留文件，数值本身有效；负分表示低于参考平均效用。它以“仅补评”来源附列，而不是因为负分被删除。

## 补评状态

- `tfbind8-k20-r3`：研究 GT 最高分 0.97372284 按统一 best-score 规则记录，没有新 GT 调用。
- `tfbind10_pho4-k0-r3`：补评完成，0.10993307。
- `tfbind10_pho4-k20-r2`：补评完成，0.10600528。
- `cell_dag_nas-k20-r2`：补评完成，32 项仅 14 个不同架构，仍无效。
- `cell_dag_nas-k20-r3`：补评完成，0.92628205。

## 统计与复核

每组使用 `best_score` 报告均值、样本标准差及有效样本数，不把缺失分数填零，不从三次重复中只挑最好的一次。分组 CSV 中本文使用 `n_best_score`、`mean_best_score`、`std_best_score` 列；其他分数列仅供追溯。统计不包含仅补评的 Pho4-k5-r1，因此该组 n=2。所有 36 次研究 GT 使用量均未超过各自 k。

| 任务 | k | best-score 均值 ± 样本标准差 | 有效运行数 / 3 |
|---|---:|---:|---:|
| tfbind8 | 0 | 0.939963 ± 0.016301 | 3 / 3 |
| tfbind8 | 1 | 0.956843 ± 0.019078 | 3 / 3 |
| tfbind8 | 5 | 0.970140 ± 0.005898 | 3 / 3 |
| tfbind8 | 20 | 0.973216 ± 0.004768 | 3 / 3 |
| tfbind10_pho4 | 0 | 0.137424 ± 0.113137 | 3 / 3 |
| tfbind10_pho4 | 1 | 0.118061 ± 0.034355 | 3 / 3 |
| tfbind10_pho4 | 5 | 0.149340 ± 0.043346 | 2 / 3 |
| tfbind10_pho4 | 20 | 0.147259 ± 0.118042 | 3 / 3 |
| cell_dag_nas | 0 | 0.900775 ± 0.000000 | 3 / 3 |
| cell_dag_nas | 1 | — | 0 / 3 |
| cell_dag_nas | 5 | 0.934079 ± 0.003309 | 3 / 3 |
| cell_dag_nas | 20 | 0.929981 ± 0.005232 | 2 / 3 |

- [逐运行完整结果](limited_gt_blackbox_20261009/all_repeats_results.csv)
- [分组均值、标准差及有效样本数](limited_gt_blackbox_20261009/all_repeats_grouped.csv)
- [汇总脚本](summarize_blackbox_repeats.py)
- [新增 24 个作业清单](../../../.famou/scimodelingbench-batches/blackbox-huayan-20261009-r2-r3/manifest.json)
- [四个恢复审计作业](../../../.famou/scimodelingbench-batches/blackbox-huayan-20261009-r2-r3/recovery_manifest.json)
- [TFBind8 用户指定最高分的来源记录](../../../.famou/scimodelingbench-fmjob-runs/tfbind8-limited-gt-huayan-20261009-k20-r3/controller/reporting_override.json)
