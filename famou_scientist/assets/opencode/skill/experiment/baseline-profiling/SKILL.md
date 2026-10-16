---
name: baseline-profiling
description: Select which baselines to compare against (aggregated from retrieved literature — covering both classic/seminal methods and recent SOTA), then extract the exact benchmark, data processing, and training configuration of each so your experiment compares on the SAME basis. Use when selecting baselines or surveying prior work for fair comparison, before designing experiments.
metadata:
  category: experiment
  trigger-keywords: "baseline,compare,benchmark,prior work,reproduce,fair comparison,SOTA,实验设置,超参,数据处理,对比"
  applicable-stages: "5,6,9"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 为什么需要这个 skill

选 baseline 时，**只抽到「方法 + 数据集名」是不够的**——公平对比建立在「同 benchmark、同数据处理、同评估协议」之上。
论文的方法写在显眼处（摘要/intro），但**实验配置藏在 "Implementation Details"、附录、GitHub README 里**，
不被显式要求就会漏。漏了的后果：你的实验和 baseline 用了不同的划分/增强/超参/epoch，**数字无法对比，审稿人一眼看穿**。

> 范围：这个 skill 管「**先选定要对比哪些 baseline**，再逐篇精读它们的实验配置」。综述方法论走
> `literature-search`，设计自己的实验走 `experimental-design`。三者配合：先选+profile baseline → 再对齐设计 → 再跑。

## 第 0 步：选哪些 baseline（从检索到的文献里汇总，别凭空想）

profile 之前先定"和谁比"。**baseline 不是 agent 拍脑袋列的，要从 `literature-search`/`systematic-review`
检索到的文献里汇总出来**——尤其看那几篇近期 SOTA 论文**自己在和谁对比**：它们 experiments 表里反复出现的方法，
就是这个领域公认的对比对象。把这些汇总起来，按下面两类都要覆盖来选：

- **经典 / 奠基方法**：该问题上被反复引用、当作起点的代表性方法（哪怕不是最强，是"地基线"，读者要看到你没回避它）。
- **最新 SOTA**：近 1~2 年最强的几个（你真正要超越/对标的对象）。文献里被最多近期论文当 baseline 引用的，优先选。
- （可选但推荐）**simple-but-strong**：一个简单却不弱的对照（如 linear probe / k-NN / 强 naive 基线），用来证明复杂度换来的收益是真的。

> 怎么落地：翻你检索到的几篇核心论文的对比表，把它们共同对比的方法做个**频次汇总**——出现得多 = 领域事实标准的
> baseline。经典的那档 + 最新 SOTA 那档各挑代表，凑成你的 baseline 集合。这和选 benchmark 同理：**跟随相关工作
> 普遍的对比对象**，而不是自己发明一套没人用的对照。数量上至少满足 `research-decision` 的 ≥2 baseline 门槛。

选定这组 baseline 后，再对每一篇执行下面的强制抽取表。

## 强制抽取表（每篇候选 baseline 逐项填，填不到标「未报告」）

不要只读摘要/方法。**翻到 Experiments / Implementation Details / 附录 / 代码仓库**，逐项填这张表：

| 维度　　　　　　　　　 | 要抽什么　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| ------------------------| -------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Benchmark / 数据集** | 名称 + **版本/子集** + 任务设定（如 CIFAR-100 不是 CIFAR-10；ImageNet-1k vs 21k）　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| **数据划分**　　　　　 | train/val/test 划分协议、比例、是否标准 split、有无 cross-validation、seed　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| **数据处理**　　　　　 | 预处理（resize/归一化/tokenize）、数据增强（哪些、强度）、清洗/过滤规则　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| **模型规模**　　　　　 | 参数量、架构变体、是否预训练 + 预训练来源　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| **训练配置**　　　　　 | optimizer、learning rate + schedule、warmup、batch size、epochs/steps、weight decay、loss（如果是需要训练的方法），其他方法也要关注论文中提到的实验参数配置 |
| **评估协议**　　　　　 | 指标的**精确定义**（top-1? macro-F1? 怎么算）、seed 数、报告方式（mean±std?）、有无显著性检验　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| **报告的关键数字**　　 | 论文里那个用来对比的主结果（连同它的实验条件）　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　|
| **算力/硬件**（可选）　| GPU 型号/数量、训练时长——评估复现成本　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |

## 🔴 复现风险标注（最有价值的一步）

填表时，**显式列出「论文没报告的项」**。这些是复现失败的高发区：
- 常见缺失：lr warmup 细节、数据清洗规则、随机种子、确切的 val 划分、早停条件
- 对每个缺失项判断：能否从开源代码补全？能否合理默认？还是「无法对齐，对比需谨慎」？
- 缺失太多的 baseline → 标记为「弱可比」，对比时明确声明差异，别假装同基准

## 对齐规则（profile 完之后怎么用）

1. **选定 baseline 后，你的实验必须和它对齐**：同一 benchmark + 同一数据划分 + 同一评估协议
2. 任何不能对齐的维度（如你没那么多算力跑同样 epoch）→ **在论文里明确声明差异**，不要隐瞒
3. 多个 baseline 之间若用了不同 benchmark → 不能直接放同一张表比；要么统一重跑，要么分组报告
4. 把 profile 表存入 `planning/literature.md`，设计实验（`experimental-design`）时直接引用它对齐

## 配合流程

- **Stage 5-6 文献**：对入选的候选 baseline 逐篇 profile，产出对比就绪的配置表 → `planning/literature.md`
- **Stage 9 实验设计**：load `experimental-design`，**以 profile 表为准对齐** baseline 的 benchmark/协议
- **Stage 15 决策**：`research-decision` 的 PROCEED 门槛要求 ≥2 baseline——这里确保它们不仅存在、而且**配置可对比**

> 一句话：baseline 不仅要「选对」，还要「摸清它怎么跑的」并「对齐着跑」，否则对比无效。
