---
name: novelty-gate
description: Before presenting a new or revised research direction (a new hypothesis, or a REFINE/PIVOT follow-up after a failed attempt), self-review whether it is genuinely innovative rather than an incremental tweak or a rehash of prior/already-tried ideas. Stops the agent from reflexively proposing low-novelty follow-ups that waste the user's patience.
metadata:
  category: experiment
  trigger-keywords: "novelty,innovation,创新,新意,incremental,增量,follow-up,后续想法,改进方向,next idea,contribution,MPU,rehash,重复,换个参数,pivot direction,值不值得做"
  applicable-stages: "8,15"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

每当你要**向用户抛出一个"新方向"**时，先过这道门。两个高发时刻：

1. **失败后的后续方向**（最关键）：上个想法效果不好，你在 `research-decision` 判了
   REFINE/PIVOT、要给"下一步规划"——**别反射式地随手抛一个改进想法**。
2. **初始假设**（Stage 8）：`hypothesis-formulation` 生成候选假设后，筛一遍新意。

> 痛点：agent 在一个想法跑砸后，很容易顺手提一个**创新性不足**的跟进（换个超参、换个
> 数据集、加一层、调一下），看似"还在推进"，实则在用一连串小修小补**消耗用户的耐心**。
> 这道门就是拦住这种反射式增量提案——**没新意的方向，不许直接甩给用户**。

---

## 新意与可改进空间判据

1. **机制级差异**：新方向是不是在**机制/原理**上真的不同？还是只是
   超参 / 规模 / 数据集 / 加一层 这种**参数级小修小补**？——tweak 不是 idea。
2. **不与历史重复**：是不是本 run 里**已经试过/已经否掉**的方向换个说法又来了？
   对照 `experiment/reflection.md` 的轮次历史——别绕圈。
3. **相对文献的位置清楚**：是不是只是**复述已有工作**？还是同一问题域下的新机制、
   新设置、新评价、更低成本、更强泛化或更清楚的理论解释？对照 `planning/literature.md`
   和 `literature_map.md`。别重新发明轮子，也别把"有人做过相关方向"误判成"完全不可做"。
4. **针对失败根因**：新方向有没有**真正回应上次失败的归因**（见 `research-reflection`）？
   还是没搞清为什么失败、就无脑换个参数再试一次？
5. **达到最小贡献单元（MPU）**：**即便它成功了**，这个结果够不够成为一个
   值得做、值得写的贡献？还是顶多是个边角料？
6. **成本可承受**：实验是否需要不可接受的训练、评估或人工标注成本？如果贵，是否有可信的
   proxy、small-scale 或分阶段验证方案？

## 每个 idea 的文献核查要求

在把 idea 提给用户前，先做一次针对性核查。不要只依赖已有 field map，也不要用一次空搜下结论。

至少覆盖这些 query 类型：
- exact idea query；
- method-level query；
- application/task query；
- baseline or limitation query；
- survey/benchmark query when available。

输出必须包含：
- competing papers；
- overlap matrix；
- improvement opportunity；
- compute/time/data cost estimate；
- confidence；
- go / revise / reject。

如果检索结果为空，只能写"未发现直接覆盖"，不能写"没有人做"。

---

## 判定与行动

| 判定 | 含义 | 怎么做 |
|------|------|--------|
| ✅ **OPEN GAP** | 未发现直接覆盖，且证据链足够 | 可以提给用户，但标明置信度 |
| 🟢 **IMPROVABLE BASELINE** | 已有工作存在明确缺陷，可做得更好 | 重点说明改进点、baseline、预期收益和成本 |
| 🟡 **OVERLAP BUT DIFFERENT** | 问题相似，但机制/对象/场景不同 | 不直接丢弃；先做 overlap matrix，再让用户判断是否值得深挖 |
| 🟠 **INCREMENTAL** | 只是参数级小改 / 边角贡献 | 明确标成增量，不包装成强创新 |
| 🔴 **DUPLICATE** | 核心问题、方法、实验设置都高度重合 | 放弃或只作为 baseline/复现目标 |

### 诚实出口（这条最重要，直击"消耗耐心"）

当你深挖后**确实只剩增量**，**不要硬凑一个"创新方向"包装给用户**。如实说，给真判断：

- 「我评估了几个跟进方向，坦白说都偏增量、创新有限。可选：(a) 做一个**大改**——
  换一个根本不同的机制/问题设定（我有 X 想法）；(b) **停在这里**，把已有结果
  （哪怕是负面/有限结果）如实写清——负面结果也有价值；(c) 你来定方向。」
- **增量也要明示**：如果某些场景下增量本身合理（例如纯工程改进、补一个消融），
  **标注清楚"这是增量而非创新"**，让用户**知情决策**，而不是把它说成创新。
- **相关不等于重复**：已有论文覆盖同一领域时，先判断它留下的缺陷和可改进空间；
  只有核心贡献和实验设置都重合时才判 DUPLICATE。

> 一句话纪律：**宁可诚实说"这条路新意见底了、建议换/停"，也不要用一串小修小补
> 假装在推进。** 真实性优先不仅是数据，也包括对"想法价值"的诚实。

---

## 配合其它 skill / 流程

- **接在 `research-reflection` 之后**：reflection 做完归因、要写"下一步规划"时，
  那个"下一步"先过 novelty-gate，再写进 `reflection.md` 的第 6 块、再提给用户。
- **接在 `research-decision` 的 REFINE/PIVOT 之后**：判定要回退重来时，新方向过这道门。
- **配 `hypothesis-formulation`（Stage 8）**：候选假设生成后筛新意。
- **依赖 `literature-search` / `baseline-profiling` 的产物**：判据 3 要对照
  `literature.md`、`literature_map.md`、`paper_cards.jsonl`。
- **C 逐步 / A·B 在 PIVOT 这种大变向时**：把 novelty 判定 + 依据一并展示给用户
  （呼应 research-decision 的关键停顿点）。

> 目标不是打压探索，而是**保证每次提给用户的新方向都对得起用户的时间**——
> 要么有真新意，要么诚实承认见底。
