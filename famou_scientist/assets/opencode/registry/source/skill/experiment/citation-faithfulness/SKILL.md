---
name: citation-faithfulness
description: Check whether a cited source actually supports the claim you attribute to it — not just that the reference exists. For key cited claims, fetch the source abstract via arc_fetch_source and judge SUPPORTED / UNSUPPORTED / AMBIGUOUS, recording verdicts in citations.md. Advisory (abstract-level only); pairs with arc_verify_citation (existence) and peer-review.
metadata:
  category: experiment
  trigger-keywords: "citation faithfulness,引用支撑,claim support,引用是否支撑,misquote,误引,引用核验,cite correctly,source supports claim,引用审计,faithfulness"
  applicable-stages: "18,23"
  priority: "2"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

论文里每条引用,有两个层次的真伪:

1. **存在性**——这篇被引论文真的存在吗?(由 `arc_verify_citation` / `arc_verify_paper` + 引用核验门 hook 覆盖)
2. **支撑性(faithfulness)**——这篇真的**说了**你拿它支撑的那句话吗?**← 这个 skill 管这一层**

第二层是引用的头号真实失败模式:**用一篇真实存在的文献,去支撑它根本没下过的结论**
(Zhao et al. 2026 审计 1.11 亿条引用,估计 2025 一年就有约 14.7 万条这类"真引用、假支撑")。
存在性核验完全发现不了它——论文是真的,只是被引错了。

**在两个时机 load**:
- **Stage 18 同行评审时**:对关键论点的支撑引用抽查(配合 `peer-review`)。
- **Stage 23 引用核验时**:在跑完 `arc_verify_citation` 存在性核验之后,补这一层内容核对。

---

## 怎么做:抓摘要 → 判三态 → 落盘

### 1. 选哪些引用查(抽查,不必全量)
全量逐条 faithfulness 成本高,**优先查"承重引用"**:
- 支撑**核心论点 / 动机 / 对比基线**的引用(被你拿来论证关键主张的);
- 带**具体数字或定量断言**的引用("[X] 报告了 92% 准确率""[Y] 证明 A 优于 B");
- 出现在**摘要 / 引言贡献句 / 结论**里的引用(读者最当真的地方)。
装饰性的"相关工作综述"类引用可略过。

### 2. 抓被引文献摘要
对每条要查的引用,调 **`arc_fetch_source(title=..., arxiv_id=..., doi=...)`** 取回真实摘要。
- `found=false` → 这条可能查无此文,退回 `arc_verify_citation` 走存在性流程(可能是 Mode 2 幻觉引用)。
- `abstract_available=false` → 拿不到摘要(部分文献无摘要),判定记 **AMBIGUOUS / 证据不足**,别硬判。

### 3. 判定三态(对照你论文里那句话)
拿摘要内容 vs. 你给这条引用安的论点:

| 判定 | 含义 | 处置 |
|------|------|------|
| ✅ **SUPPORTED** | 摘要明确支持你的论点(方向、对象、量级都对得上) | 保留 |
| ❌ **UNSUPPORTED** | 摘要**不支持**、甚至与你的论点矛盾,或讲的根本是另一回事 | **改写论点 / 换更贴切的引用 / 删掉这条** |
| 🟡 **AMBIGUOUS** | 摘要相关但不足以判定(摘要太略、需正文才说得清、拿不到摘要) | 标注存疑;能找正文/更明确出处则升级判定,否则弱化措辞 |

**判定纪律**:
- **只凭摘要,不脑补**。摘要没说的就是"摘要无法确认",判 AMBIGUOUS,别因为"听起来像会支持"就判 SUPPORTED。
- 尤其盯**定量断言**:你写"[X] 报告 92%",摘要里没有这个数 → UNSUPPORTED 或 AMBIGUOUS,不能放过。
- 方向必须对:你说"[X] 证明 A 提升 B",摘要若说的是"A 对 B 无显著影响"→ UNSUPPORTED(这正是最该抓的误引)。

### 4. 落盘 `deliverables/citations.md`
在已有的存在性核验报告之后,追加一张 faithfulness 表:

```markdown
## 引用支撑性审计(claim-faithfulness,摘要级)

| 引用 | 你论文里的论点 | 判定 | 依据(摘要要点) | 处置 |
|------|---------------|------|----------------|------|
| [Vaswani 2017] | "Transformer 去除了循环结构" | ✅ SUPPORTED | 摘要明确"dispensing with recurrence entirely" | 保留 |
| [Foo 2024] | "报告 92% 准确率" | ❌ UNSUPPORTED | 摘要无此数字,报告的是 F1=0.81 | 改数字或换引用 |
```

---

## 🔴 局限要如实说(别假装这是硬核验)

- **只能拿到摘要,正文常付费墙** —— 摘要级判定是 **advisory(仅供参考)**,不是确定性核验。
  摘要判 SUPPORTED 不代表正文细节都对;摘要判 UNSUPPORTED 是强信号,值得回去查正文确认。
- **因此本 skill 不设硬 block**:UNSUPPORTED 是要你**主动改**的警示,不是 hook 那种强制拦截
  (这也对齐业界把 claim 审计定位成 "advisory risk signal" 的做法)。
- 真要确认深层断言,得读正文——本 skill 把"明显的误引"用低成本摘要级筛出来,已能挡住大多数。

---

## 与其它 skill / tool 的关系

- **接在 `arc_verify_citation` 之后**:先确认引用**存在**,再用本 skill 确认它**支撑论点**——两层互补。
- **是 `failure-mode-audit` Mode 2 的内容层**:存在性 hook + 本 skill 一起,把"幻觉引用"从"查无此文"
  扩到"真文假引"。
- **配 `peer-review`**:审稿人最爱挑"这条引用根本不支持你的说法",定稿前先自己用本 skill 筛一遍。
- **工具**:`arc_fetch_source`(抓摘要)是本 skill 的执行手脚。

> 一句话:引用真不真,分两层——"这篇存在吗"(verify_citation)和"这篇真这么说吗"(本 skill)。
> 第二层最容易出错、也最少被查,用摘要级抽查低成本挡住绝大多数误引。
