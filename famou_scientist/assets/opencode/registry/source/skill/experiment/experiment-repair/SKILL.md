---
name: experiment-repair
description: Diagnose WHY an experiment failed and fix it yourself. Use when arc_run_experiment errors, times out, returns all-zero/empty metrics, or produces suspicious results (e.g. near-random accuracy), before retrying.
metadata:
  category: experiment
  trigger-keywords: "experiment failed,traceback,error,OOM,NaN,no module,diagnose,repair,retry,fix experiment"
  applicable-stages: "12,13"
  priority: "1"
  version: "1.1"
  author: researchclaw
---

## 何时用这个 skill

实验跑出问题时——`arc_run_experiment` 报错 / 超时 / metrics 全 0 或为空 / 结果异常
（如准确率接近随机）——load 这个 skill 拿到 ARC 沉淀的**修复方法论**，然后**你自己**
读 stderr、改代码、重跑。修实验是你（coding agent）的主场，这里给的是 know-how，不是约束。

> 范围：这个 skill 只管"**让当前实验产出可信数据**"（修 bug + 修技术缺陷）。
> 如果实验本身没毛病、数据可信但**不支持假设**（如"动量法并没更快"），那不是修复问题，
> 是科学决策——走 `research-decision` 的 PROCEED/PIVOT/REFINE，别在这死改代码。

## 失败根因分类 + 标准修法（ARC 的经验 checklist）

失败有固定的几类根因，每类有对应标准修法。**先归类再针对性修，别盲目重写**：

| 根因类别 | 典型信号 | 标准修法 |
|---------|---------|---------|
| 缺依赖 | `ModuleNotFoundError` | 加进 requirements，重跑 |
| 权限/下载被拦 | `PermissionError` / 403 / HF 模型下载失败 | 预缓存模型 or 换小模型（distilgpt2 替 gpt2）|
| GPU OOM | `CUDA out of memory` | batch size 砍半 / 梯度检查点 |
| 数据集不可用 | `DatasetNotFoundError` / 文件不存在 | 只用预缓存数据集（CIFAR/MNIST），下载移到 setup 阶段 |
| 合成数据回退 | 日志出现 "using synthetic data" | 修真实数据加载，**别用随机数据假装跑通** |
| 超参问题 | loss NaN / loss 发散 / 准确率近随机 | 学习率降 10×、加梯度裁剪、检查归一化与前向传播 |
| 时间守卫杀条件 | TIME_GUARD 杀掉 >50% 条件 | 减条件数、减 epoch、减种子 |
| 条件雷同 | ablation 各条件输出完全相同 | 检查区分参数是否真的接进了前向传播（不只是被 log）|
| 种子不足 | 某条件只有 1 个种子 | 至少 2 个种子才有方差估计 |

## 不显然的硬判据（容易被忽略，务必应用）

这些是 ARC 踩坑沉淀的反直觉规则——光看"跑通了"会漏判：

- **准确率 < 15%（分类任务）= 模型根本没学会**，不是"结果一般"。当成失败处理：查学习率、数据归一化、前向传播是否把梯度传到所有参数。
- **完成条件 < 3，或每条件种子 < 2 → 统计上不足以写正式论文**。别拿 1 个种子的结果当定论。
- **ablation 条件输出雷同 → 区分参数八成没接进代码**（只是被记录了）。这会让"消融实验"变成假的。
- **日志里有"synthetic/random data fallback" → 实验偷偷用了假数据**，结果无效，必须修真实数据加载。
- **同一类根因连续修 3 轮还复现 → 判定不可修复，停下告诉用户**，别无限重试烧算力。

## 修复循环（节奏跟 AGENTS.md 走）

1. 读 `arc_run_experiment` 返回的 stderr/stdout，按上面 checklist **归类根因**
2. **针对性改** `experiment/experiment.py`（改根因，别全部重写），重新调 `arc_run_experiment`
3. 仍失败：重复 1-2，**最多 3 次**；3 次仍败 → 按 AGENTS.md「自愈循环」底线停下如实报告
4. 节奏为 **C 逐步** 时：第 1 次失败就把根因+修法展示给用户，等他定
5. 节奏为 **A 全自动 / B 关键节点** 时：自己迭代修，不打扰用户（修不好才停）

> 这复刻了 ARC `experiment_repair.py` 的 `run_repair_loop` 思路，但循环由你（OpenCode）
> 在对话里执行、bug 由你自己改——ARC 的价值在上面那份 checklist 和硬判据，不在代码约束。
