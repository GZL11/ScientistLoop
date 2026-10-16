---
name: experimental-design
description: Best practices for designing reproducible ML experiments. Use when planning ablations, baselines, or controlled experiments.
metadata:
  category: experiment
  trigger-keywords: "experiment,ablation,baseline,control,hypothesis,reproducib"
  applicable-stages: "9,10,12"
  priority: "2"
  version: "1.0"
  author: researchclaw
  references: "Bouthillier et al., Accounting for Variance in ML Benchmarks, MLSys 2021"
---

## Experimental Design Best Practice
1. ALWAYS include meaningful baselines (not just random):
   - At least one classical method baseline
   - At least one recent SOTA method baseline
   - A simple-but-strong baseline (e.g., linear probe, k-NN)
   - 注：**具体选哪些 baseline 由 `baseline-profiling` 负责**——从检索到的文献里汇总（看近期 SOTA 论文
     自己在和谁比），覆盖经典+最新两档，并摸清每个 baseline 的 benchmark/协议以保证可比。本步直接**沿用
     `baseline-profiling` 选定并 profile 好的那组 baseline**对齐设计，不要在这里另起一套选取标准。
2. Use MULTIPLE random seeds (minimum 3, ideally 5)
3. Report mean +/- std across seeds
4. Design ablations that isolate EACH key component:
   - Remove one component at a time
   - Each ablation must be meaningfully different from baseline
5. Control variables: change only ONE thing per comparison
6. Use standard splits (train/val/test) — never test on training data
7. Report wall-clock time and memory usage alongside accuracy
8. 让实验**定期打印进度 + 核心指标**（每 epoch/每 N step 一行：`epoch 3/10`、`train_loss: 0.41`、
   主指标用 `metric: value` 格式）——别只在结尾打。好处：长实验后台跑时，心跳进度播报会把这些
   日志尾实时转达给用户（心里有数），超时/卡死也能从日志判断跑到哪。详见 `async-experiment-execution`。

## 📋 实现契约 / 实验清单（design.md 必含，逐条可核对）

`design.md` **必须**包含一个 **「实现契约（Implementation Contract）」** 小节，把"我们要求的**所有**
设置"**显式、逐条、可勾选**地列出来——这是后续 `code-plan-review` 静态审查、冒烟测试、数字核验门
**共同的硬基准**。别把要求埋在散文里让 reviewer 揣摩（那样必漏项）；要让人能拿它当 checklist 一条条打勾。

**至少枚举以下条目（每条给"期望值"，写成 `- [ ] xxx: <期望>` 形式）**：

- **数据**：数据集名 / 来源·路径 / **train·val·test 精确样本数** / 预处理步骤（归一化·滤波·分窗·增强…）/ 标签映射。
- **条件 & baseline**：**逐个**列每个 condition、每个 baseline 及其关键配置（对齐 `baseline-profiling` 的配置表）。
- **超参**：**每个**关键超参 + **具体取值**（lr / batch / epoch / 优化器 / 调度 / 正则 / 早停…）。
- **种子**：数量（≥3）+ 是否真随机化 + 取值。
- **评估**：主指标定义·方向·单位 / 切分与聚合方式 / 评估协议（怎么测、在哪个 split 测）。
- **期望事实 & 断言**：开跑应满足的 `assert`（如 `len(train)==N`、`num_conditions==K`）、首 batch 期望 `shape/dtype`。
- **可观测性要求**：进度条 / 每 epoch·N step 打印 `train_loss` + 主指标（`metric: value`）/ 开跑回显**生效**超参 / 首 batch sanity（shape·dtype·标签分布）。（规范见上 §8 与 `async-experiment-execution`，此处只是把它列为契约条目供核验。）

**紧凑模板（照填）**：
```markdown
## 实现契约（Implementation Contract）
### 数据
- [ ] 数据集: Nakanishi2015（路径 experiment/data/）
- [ ] 样本数: train=N1 / val=N2 / test=N3
- [ ] 预处理: 带通 [a,b]Hz → 分窗 Ls → z-score（按通道）
- [ ] 标签: 12 类（频率→类别映射见 …）
### 条件 & baseline
- [ ] 本方法: FPTA（频率先验 Transformer）
- [ ] baseline: FBCCA(…配置) / EEGNet(…配置)  ← 对齐 baseline-profiling
### 超参
- [ ] lr=…, batch=…, epochs=…, optimizer=…, scheduler=…
### 种子
- [ ] seeds=[s1,s2,s3]（≥3，真随机化）
### 评估
- [ ] 主指标: accuracy（↑，在 test split；被试内 k-fold 聚合 mean±std）
### 断言 & 期望
- [ ] assert len(train)==N1; assert num_conditions==K
- [ ] 首 batch: x.shape==(B,C,T), y.shape==(B,)
### 可观测性
- [ ] 进度条 + 每 epoch 打印 train_loss / val_acc；开跑回显生效超参；首 batch sanity
```

> **拿不准的条目标 `TBD` 并停下问用户**（如数据集到底用哪个、样本数多少）——**绝不留空靠猜**。
> 契约是"实验前不写论文/不烧算力"的源头基准：清单越明确，下游越无处可漏。
