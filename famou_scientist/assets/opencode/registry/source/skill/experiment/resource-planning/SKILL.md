---
name: resource-planning
description: Estimate the compute/memory/time each experiment needs, present it to the user, and check it against the user's available resources before running. Use after designing experiments, before writing/running code.
metadata:
  category: experiment
  trigger-keywords: "resource,compute,GPU,memory,VRAM,显存,算力,budget,OOM,how long,training time,资源,跑不动"
  applicable-stages: "11"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

实验设计完（知道有哪些 condition、模型规模、数据集、跑几个 seed）之后、写代码/跑之前。
目的：**先估清每个实验要多少资源 → 给用户看 → 确认资源够不够**，别闷头写完代码才发现跑不动。

## 估算每个实验的资源

对**每个 condition × seed** 估这几项，做成一张表：

| 维度 | 怎么估 |
|------|--------|
| **GPU 显存** | 首选**类比 baseline**（`baseline-profiling` 抽的硬件字段）；补充粗算：fp32 Adam 训练模型态显存 ≈ 参数量(B) × 16 GB，再加激活（随 batch × 分辨率/序列长 增长）。混合精度约减半。 |
| **GPU 时长** | 首选**参考 baseline 报告的训练时长**；或 epochs × (数据量/batch) × 每 step 估时。 |
| **运行数** | condition 数 × seed 数 = 总运行数 → 累加得**总 GPU 小时** |
| **存储** | 数据集大小 + checkpoint（模型参数 × 存档次数） |

> **优先类比 baseline 的已知算力**（它在什么卡上、训多久）——比从参数量硬推可靠。
> 粗算公式只在没有 baseline 硬件信息时兜底。

## 问用户可用资源（关键停顿点）

把估算表给用户看，**同时问清他的可用资源**，别假设：

1. 有几张什么 GPU？单卡显存多少？（如 1×A100-40G / 4×3090-24G）
2. 大概能用多久 / 有没有截止时间？
3. 是本地 sandbox 还是有远程 GPU 集群？

## 对比判断 + 降规模方案

把「估算」对上「可用」，明确给结论：**能跑 / 紧张 / 跑不动**。跑不动时按性价比给降规模手段：

1. **复用 baseline 数字**（回 `benchmark-selection`）——能借就不跑，最省
2. **混合精度**（fp16/bf16，显存≈减半，几乎不损精度）
3. **减 batch + 梯度累积**（降显存，保持等效 batch）
4. **梯度检查点**（显存换时间，大模型有效）
5. **减 epoch / 用数据子集 / 减 seed（≥2 仍要保）/ 减 condition**（降时间，但注意别破坏统计有效性——见 `research-decision` 的种子门槛）
6. **换更小模型变体**（如 ResNet-50→18、ViT-B→S）——但要在论文声明规模差异

## 配合流程

- 上游 `experimental-design`：提供 condition/模型/数据 → 才能估
- 上游 `baseline-profiling`：提供 baseline 硬件/时长 → 估算的最佳参照
- 本步：估算 + 问用户资源 + 判断能否跑 → **不够则回设计调整（减规模/复用结果）**，够则进入写代码
- 把资源估算表 + 用户可用资源 + 最终决定，记入 `planning/design.md`

> 一句话：跑之前先算账、给用户看、对齐可用资源——别让实验跑到一半 OOM 或超时才发现。
