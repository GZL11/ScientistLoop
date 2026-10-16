---
name: research-reflection
description: After analysis, check whether the experiment conclusion actually supports the ORIGINAL hypothesis. If not, diagnose the root cause and write a reflection document (hypothesis recap, results, observed phenomena, alignment verdict, root-cause analysis, next-step plan). Pairs with research-decision (which issues PROCEED/REFINE/PIVOT) to keep the agent from drifting away from the original question.
metadata:
  category: experiment
  trigger-keywords: "reflection,复盘,反思,归因,root cause,hypothesis support,conclusion supports hypothesis,结论支撑假设,假设对齐,pivot,refine,drift,跑偏,next plan,下一步规划"
  applicable-stages: "14,15"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

实验跑完、数据**已经可信**（崩了/NaN/近随机先走 `experiment-repair`）、分析也做完，
**在 `research-decision` 给出 PROCEED/REFINE/PIVOT 判定的同一时刻**，load 这个 skill 做
一件最容易被略过、却最防跑偏的事：

> **把最后的实验结论，拿回去对照"最开始那个假设"——它到底支不支持？**

agent 跑久了很容易"忘记初心"：实验越做越细，结论却悄悄漂到一个**不是当初要回答的问题**上。
这个 skill 强制你回到 `planning/hypotheses.md`，逐条核对，并把**对照过程、归因、下一步**
全部落盘成 `experiment/reflection.md`，让跑偏无所遁形。

> 分工：`research-decision` 出**判定**（PROCEED/REFINE/PIVOT 三选一）；本 skill 出
> **判定背后的深度归因 + 反思文档 + 下一步规划**。两者同一岔路口配合使用——
> 先 reflection 想清楚"支不支持、为什么、接下来怎么办"，再用 research-decision 落成判定。

---

## 核心问题：结论 ⇄ 假设 对齐三态

打开 `planning/hypotheses.md`，找到**当时选定的主假设**（H1 及其 H0、证伪条件、预测方向/量级）。
拿本次实验的**真实结论**逐条比，得出三态之一：

| 对齐态 | 含义 | 对应决策 |
|--------|------|---------|
| ✅ **SUPPORTS（支持）** | 结论在**方向和量级上**都兑现了 H1 的预测，达到证伪 H0 的门槛 | → **PROCEED** 写论文 |
| 🟡 **PARTIAL（部分/不足）** | 方向对，但证据不够硬（不显著/方差大/条件或种子不够/量级没到） | → **REFINE** 同假设补实验 |
| ❌ **CONTRADICTS（矛盾）** | 结论与 H1 的预测**方向相反**，或满足了当初写下的**证伪条件** | → **PIVOT** 换假设 |

**判定纪律**：
- 必须对照"**最初写下的预测**"，不能临时把假设改宽松来迁就结果（那叫 HARKing，造假的近亲）。
- 量级也算数：方向对但效应远小于当初声称的"显著提升"，是 PARTIAL 不是 SUPPORTS。
- 只跑了自己的方法、没有 baseline 对比 → 任何"支持"都不成立，直接 PARTIAL/REFINE。

---

## 不支持时：归因定位（PARTIAL / CONTRADICTS 必做）

只要不是 SUPPORTS，就**必须给出具体归因**——别只写"假设不成立"一句话收尾。
逐项排查，定位到底是哪一层出了问题（这也直接决定 REFINE 还是 PIVOT）：

| 归因类别 | 典型证据 | 倾向决策 |
|---------|---------|---------|
| **执行/实现问题**（前提：已过 experiment-repair 仍残留的隐患） | 某条件没真正接进代码、超参没对齐、数据划分错 | REFINE（修了重跑）|
| **证据强度不足** | 趋势对但不显著、种子<3、方差吞掉效应、样本/条件太少 | REFINE（加种子/条件/baseline）|
| **基准/对比不公平** | baseline 配置和 `baseline-profiling` 表对不上、benchmark 太易/太难 | REFINE（换/对齐基准）|
| **指标选错** | 主指标测不到假设关心的效应、代理指标偏离 | REFINE（换指标，必要时回设计）|
| **混淆变量** | 效应可能来自没控住的第三变量 | REFINE（加控制）或 PIVOT |
| **假设本身错** | 方向系统性相反、机制被数据明确否定、多轮 REFINE 仍矛盾 | **PIVOT**（换假设）|

> **REFINE vs PIVOT 的分界**还是那句话：**假设还活着吗？** 活着只是没喂饱 → REFINE；
> 数据明确反对它 → PIVOT。配合 `research-decision` 的"退化循环规则"：多轮 REFINE 后
> 指标饱和/不变，别再 REFINE，改判 PROCEED+caveat 或 PIVOT。

---

## 🔴 必须落盘：`experiment/reflection.md`（本 skill 的硬产出）

每到这个岔路口，**追加**一段复盘到 `experiment/reflection.md`（按轮次累积，形成复盘日志，
别覆盖——历史轮次是判断"是否在死循环"的依据）。固定六块，缺一不可：

```markdown
## 复盘 Round <N> — <日期/轮次说明>

### 1. 假设回顾
- 主假设 H1：<从 hypotheses.md 原样抄来，含预测方向/量级>
- H0 与证伪条件：<当初写下的，不许临时改>

### 2. 实验结果（真值，引 results.json）
- 主指标：<condition 对比，关键数字，注明来自 experiment/results.json>
- 统计：<种子数、置信区间/显著性>

### 3. 观察到的现象
- <实验中看到的事实，尤其是**预期之外**的：哪条件异常、哪里反直觉、
  哪个 trade-off 出现了——现象先于解释，照实记>

### 4. 结论 ⇄ 假设 对齐判定
- 判定：SUPPORTS / PARTIAL / CONTRADICTS
- 说理：<逐条对照 H1 的预测，方向对不对、量级够不够、是否触发证伪条件>

### 5. 归因反思（PARTIAL/CONTRADICTS 必填）
- 根因类别：<执行/证据不足/基准/指标/混淆/假设本身>
- 具体分析：<为什么不支持——基于上面的现象和数据说理，定位到具体哪一步>

### 6. 下一步规划
- 决策：PROCEED / REFINE / PIVOT（与 research-decision 一致）
- 具体动作：
  - PROCEED → 进入写论文；列出要在论文里如实写明的局限
  - REFINE  → 改什么实验、加几个种子/条件、回第 4-5 步重跑
  - PIVOT   → 放弃哪个假设、换成哪个新假设、回第 3 步
```

**为什么逼着落盘**：①让用户随时翻阅、直接改文件干预（等价 ARC 的 edit gate）；
②跨轮次留痕，REFINE 第几轮、改了什么、有没有收敛一目了然，防止 agent 自己绕圈；
③论文 Discussion/Limitations 段可直接取材于此（观察现象 + 反思）。

---

## 与其它 skill / hook 的关系

- **前提是数据可信**：技术性失败（报错/全 0/NaN）先走 `experiment-repair`，那是"实验对不对"；
  本 skill 处理"结论说明什么"。
- **同时 load `failure-mode-audit`**：本 skill 是它**跑后关卡**的驱动。第 3 块「观察现象」+ 第 5 块
  「归因」要显式核对 **Mode 1（数字异常：可疑整齐数、各 run 方差雷同）/ Mode 3（幻觉结果：每个数字
  都能回溯 results.json）/ Mode 5（反预期现象先怀疑是不是 bug，再当发现写）**——任一 SUSPECTED 就停。
- **配 `research-decision`**：本 skill 想清楚归因与下一步，research-decision 落成正式判定。
- **下一步先过 `novelty-gate`**：第 6 块「下一步规划」里若是 REFINE/PIVOT 的新方向，
  先 load `novelty-gate` 自检创新性——别把"换个超参再试"这种增量当成新方向写进规划、提给用户。
- **喂给 `quality-gate` / `peer-review`**：reflection.md 里诚实记下的局限和反预期现象，
  正是质量门"声称-证据对齐"和审稿人会盯的地方——提前写清，论文更扛审。
- **数字核验门 hook 仍兜底**：reflection.md 和论文里的数字一律从 `results.json` 取真值。

---

## 配合 AGENTS.md 的节奏

- 这是 AGENTS.md 第 7 步"分析 + 研究决策（Stage 14-15）"的一部分，**关键停顿点**。
- **C 逐步**，以及 **PARTIAL→REFINE / CONTRADICTS→PIVOT 这种推倒重来**：必须停下、
  展示 reflection.md 的判定+归因+下一步、等用户确认（重大方向变更属硬问题，A/B 全自动也不跳过）。
- **SUPPORTS→PROCEED**：A/B 节奏下可在展示复盘摘要后直接进入写论文。

> 一句话：写论文之前，先逼自己回答"我最初想验证什么、现在验证到了没、没到是为什么、接下来怎么办"，
> 并把答案写下来。这是防 agent 跑偏、保证"结论真能支撑这篇论文"的最后一道**主动**关口。
