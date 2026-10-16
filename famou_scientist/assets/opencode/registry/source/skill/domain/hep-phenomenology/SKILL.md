---
name: hep-phenomenology
description: Best practices for high-energy-physics phenomenology research (BSM models, collider & dark-matter studies, cross-section / exclusion-limit analyses). Use when the topic involves particle physics, mediators, dark matter, ATLAS/CMS, or beyond-Standard-Model searches.
metadata:
  category: domain
  trigger-keywords: "HEP,particle physics,collider,dark matter,BSM,cross section,exclusion limit,ATLAS,CMS,Drell-Yan,phenomenology,mediator,dilepton,EFT,relic density"
  applicable-stages: "8,9,10,14"
  priority: "2"
  version: "1.0"
  author: researchclaw
  references: "ATLAS/CMS Run-2/3 results; LZ 2024; XENONnT; PandaX-4T; PDG"
---

## HEP 唯象研究方法论（领域知识）

研究 BSM/暗物质/对撞机唯象时 load 这个 skill。HEP 高度专业，**通用知识容易出错**——
这里是 ARC 沉淀的领域规范，务必遵守。

## 实验设计：在 sandbox 里怎么算

- **用解析公式 + Python 参数扫描，不要调外部 MC 生成器**（sandbox 跑不了 MadGraph/Pythia）。
  MadGraph/ROOT 只作为参考基准引用，实际计算用解析截面公式 + numpy 扫描。
- **条件命名必须是物理标签，从假设派生**——直接进最终 JHEP/PRD 论文：
  - ❌ `baseline_1` / `model_variant_2` / 通用 ML 名（`ppo_policy`）
  - ✅ `scalar_portal_tree` / `vector_mediator_schannel` / `majorana_dm_velocity_dep` / `dim6_effective` / `nlo_correction` / `mono_jet_recast`
- **baseline 必须用当前(2022+)实验结果**：ATLAS/CMS Run-2 或 Run-3、LZ 2024、XENONnT、PandaX-4T——不要用过时的限。

## 假设：什么样的 HEP 假设算好

每个假设必须满足：
- **NOVEL**：不复刻已发表的 recast 或现有 collaboration 排除
- **GAP-FILLING**：针对文献综合里识别出的具体盲点
- **物理可测**：解析截面公式 / 参数空间扫描 / 已发表实验数据 recast 三者之一可评估
- **可证伪**：有自然单位下的明确数值阈值，违反即否定假设
  （例：`σ_SI > 2·10⁻⁴⁶ cm² for m_DM = 40 GeV is excluded by LZ`）
- **物理有趣**：至少一个挑战常规假设（干涉效应、偶然抵消、非热产生、速度依赖截面）

## 指标与单位（硬规范）

- **引用实验输出的精确数字，绝不编造**
- **一律用自然单位**：GeV、pb、fb、cm²、Ω h²
- **明确标注置信水平**：95% CL 是 HEP 惯例

## 结果分析：解读前必做的 sanity check

拿到参数扫描输出，**先做这 6 项检查再解读**：

1. **单调性**：截面应在恰当极限单调（固定质量下 σ ∝ g⁴；大 mediator 质量下 σ 随其增大而减小）。非单调 → 标记数值问题（溢出、干涉 dip 处理错误）
2. **SM 基准**：无新物理时必须重现已知树级结果，与 PDG 报道的基准点截面对比
3. **跨区间一致性**：标量 vs 矢量 mediator 在大质量 EFT 极限下应给出可比的限；差异巨大 → 疑似 bug
4. **区间覆盖**：若结果来自单一 (m_DM, m_med) 网格 + 单一 mediator 自旋，**明确声明结论仅限该区间，不要外推**
5. **ablation 隔离**：同一网格点上两个条件给出**相同截面** = ablation 没改到计算，RED FLAG，查代码路径
6. **指标定义检查**：找 `METRIC_DEF:` 行，确认指标方向/单位明确

## 常见坑

- 在 sandbox 里试图调 MC 生成器 → 跑不动；改解析+扫描
- 用通用 ML 名命名物理条件 → 论文质量直接掉档
- 编造截面数字或不标 CL → 反造假核对会拦（见 `quality-gate`）
- 单网格结果外推到全参数空间 → 审稿人必拒

> 配合：实验失败走 `experiment-repair`，结果决策走 `research-decision`，
> 定稿核对走 `quality-gate`——本 skill 只提供 HEP 领域知识。
