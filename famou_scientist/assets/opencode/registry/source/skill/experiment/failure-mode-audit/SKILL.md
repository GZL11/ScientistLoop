---
name: failure-mode-audit
description: Systematically rule out the 7 AI-research failure modes (Lu et al., The AI Scientist, Nature 2026) at three integrity checkpoints — before running code, after results are in, and before exporting the paper. For each mode, return CLEAR / SUSPECTED / INSUFFICIENT EVIDENCE; SUSPECTED blocks until resolved or user-overridden. The shared integrity checklist that code-plan-review, research-reflection, peer-review and quality-gate all draw on.
metadata:
  category: experiment
  trigger-keywords: "failure mode,失败模式,诚信门,integrity gate,hallucinated result,幻觉结果,shortcut,捷径,捷径特征,methodology fabrication,方法学造假,frame-lock,bug as insight,bug当洞见,AI Scientist,7模式,造假排查"
  applicable-stages: "12,14,20"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

这是 famou 的**统一诚信审查清单**——把 *The AI Scientist*(Lu et al., *Nature* 2026,
首个通过盲审的全自主 AI 科研系统)在 Limitations 里点名的 **7 种 AI 科研失败模式**做成
可逐项排除的 checklist。这些失败之所以危险,是因为**它们看起来都像扎实的工作**:一篇含
幻觉结果的论文,读起来和含真实结果的论文一模一样。

在**三个诚信关卡**各 load 一次,核对**与该阶段相关的模式**:

| 关卡 | 时机 | 重点核对的模式 | 谁驱动 |
|------|------|---------------|--------|
| **跑前** | 代码写完、`arc_run_experiment` 之前 | 1(实现 bug)、4(捷径)、6(方法学造假) | `code-plan-review` |
| **跑后** | 拿到真实结果、做完分析时 | 1(数字异常)、3(幻觉结果)、5(bug 当洞见) | `research-reflection` |
| **定稿前** | 导出论文之前 | 2(幻觉引用)、4(捷径)、7(frame-lock),复查全部 7 项 | `quality-gate` / `peer-review` |

> 不是新流程,是给已有三道审查 skill 提供**同一份权威 taxonomy**,免得各处口径不一。

---

## famou 相对纯写作系统的结构性优势(先说清,别白做功)

ARS 这类系统**不跑实验**,只能靠"用户能不能拿出实验日志"来盘问 Mode 1/3/6。**famou 真跑实验**:
- 每个数字都来自 sandbox 真执行,登记进 `experiment/results.json`(可信数字注册表);
- **数字核验门 hook** 在你写 `paper.md`/`.tex` 时自动比对,无依据的数字强制拦截;
- **实验质量门 hook** 自动拦 returncode≠0 / 全 0 metric / 超时。

所以 **Mode 3(幻觉实验结果)和 Mode 6 里的"数字对不上"在 famou 里已被 hook 硬覆盖**——
本 skill 在这两项上主要做 hook 之外的**软判断**(下面每条标注了 famou 现状)。

---

## 7 种失败模式 + 检测问句

逐项给三态之一:**CLEAR**(有证据排除,记一句证据)/ **SUSPECTED**(检测问句命中,必须上报)/
**INSUFFICIENT**(没有材料判定)。

### Mode 1 — 实现 bug 通过了 AI 自审
代码有 bug(off-by-one、错变量、静默除零、类型强转、标志位写反),跑出**数值上看着合理、
科学上错误**的结果,AI 一看"没明显问题"就采信。
- 关键数字有没有对应的、退出码 0 且零警告的运行日志?(famou:对照 `runner.log` + results.json)
- 有没有**可疑的整齐数字**(恰好 0.5、恰好 2× baseline、各 run 方差恰好为 0)?常是常量从坏管道漏出来的信号。
- 误差棒/置信区间在不同条件间**是否真的有差异**,还是诡异地完全一致?
- **famou 现状**:跑前由 `code-plan-review` 的 assertion 自证;跑后由本清单 + 实验质量门兜底。

### Mode 2 — 幻觉引用
引用不存在、张冠李戴(年份/期刊/作者错)、或被安上一个它根本没有的发现。
- **famou 现状**:`arc_verify_paper` + 引用核验门 hook 查**存在性**;`citation-faithfulness` skill +
  `arc_fetch_source` 查**内容是否真支撑论点**(claim 级)。本模式基本已被这两层覆盖,定稿前确认跑过即可。

### Mode 3 — 幻觉实验结果
报告了**任何真实实验都没产出过的数字**("we observed a 12% improvement",但没有一次 run 得到过 12%)。
- 每个"X% 提升 / Y% 下降 / 超过 baseline Z"都能在 `results.json` 找到来源吗?
- 论文表格和 `results.md` / `results.json` 对得上吗?"跑了 N 个种子"和实际 run 数一致吗?
- **famou 现状**:**数字核验门 hook 已硬覆盖**——这是 famou 最强的一项。本清单只需确认 hook 没被绕过(数字全来自 results.json)。

### Mode 4 — 捷径依赖(shortcut reliance)
结果是真的,但模型靠**虚假特征**而非预期的泛化达成(经典:靠背景色而非数字形状在彩色 MNIST 上拿 99%)。
- 有没有**控制实验/消融**排除掉最显眼的捷径特征?(在去掉捷径特征的数据变体上还成立吗?)
- 论文的"消融"是真在消融**所声称的机制**,还是只在调无关超参?
- baseline 够不够强,以至于打赢它**必须靠提出的机制**而不只是更多算力?
- **famou 现状**:未被任何 hook 覆盖,纯软判断。跑前在 `code-plan-review` 标记"需补反捷径消融",定稿前由 `peer-review` 的 Reviewer 盯。**flag 为主,不强制 block**。

### Mode 5 — bug 被重新包装成"新发现"
管道因 bug 产出意外结果,写作阶段却把这个**bug 导致的异常**叙述成"我们发现 X 在 Y 下表现反常"。
论文因此读起来**比没 bug 时更有趣**——最危险的一类(Mode 1 + 叙事诱惑的复合)。
- 草稿里有没有"surprisingly / unexpectedly / counterintuitively / 与假设相反"这类措辞?
  每一处:**有没有文献会预测相反结果**?若没有任何文献支持这个"反常",它可能不是发现,是 bug。
- 这个惊人结果是**第一次跑就出现**,还是调试很多轮后才冒出来?首次出现的"惊喜"高危。
- 有没有在**全新环境**里从头复现过这个惊人结果?
- **famou 现状**:跑后在 `research-reflection` 第 3 块「观察现象」+ 第 5 块「归因」专门处理——反预期现象必须先怀疑是不是 bug,再当发现写。

### Mode 6 — 方法学造假
Methods 描述的实验/超参/数据集/流程,**不是管道实际跑的那套**——AI 按"一个合理版本应该长啥样"
编了段听着对的 Methods,和真实跑的配置脱节。
- Methods 里每个数字(学习率/batch/epoch/数据集大小/划分)都能在真实代码/配置里找到吗?
- Methods 描述的预处理步骤,代码里都有吗?
- **famou 现状**:跑前 `code-plan-review` 查代码⇄规划一致;Methods 里的数字同样受数字核验门约束。本清单核对 Methods 叙述与 `experiment.py` / `design.md` 不脱节。

### Mode 7 — 早期 frame-lock(框定锁死)
早期阶段一个错误承诺(研究问题框定、方法选择、超参方向),后续阶段因为**结构上在它下游**而无法回退,
最终论文执行得很好,却**在回答错的问题 / 用根本不合适的方法**。
- 如果能带着现在的认知回到 Stage 1,你会改研究问题或方法吗?
- Discussion 里有没有"in hindsight / 事后才意识到"这类 frame-lock 的尾巴?
- 这篇的贡献,是**因为**当初的框定而成立,还是**尽管**框定如此仍成立?
- **famou 现状**:部分被 `novelty-gate`(假设阶段)和 `research-decision` 的 PIVOT 判据覆盖;本清单在定稿前再问一次"是否答错了题"。SUSPECTED 则提供回 Stage 3 重新框定的选项。

---

## 三态怎么处置(block 规则)

- **任一模式 = SUSPECTED → 阻断**:停下、上报用户。用户三选一:① 确认问题,回上一阶段修;
  ② 给理由 override(理由记入 `reflection.md` / 过程记录);③ 改对应段落后重跑本检查。
- **Mode 1 / 3 / 5 / 6 = INSUFFICIENT → 也要阻断**:这四项靠"拿不出证据"就放过等于裸奔,
  必须补出执行级证据(日志/results.json/复现)才能判 CLEAR。
- **Mode 2 / 4 / 7 = INSUFFICIENT → 可带 warning 放行**,但留到定稿前关卡复查。
- **定稿前关卡**:在 2.5(跑后)曾 SUSPECTED 的模式,必须在此解决(CLEAR 或已 override),
  否则**拒绝导出**——再多修订轮也跳不过这一条。

> 落盘:跑后的判定并入 `experiment/reflection.md`(归因那块);定稿前的判定并入
> `deliverables/reviews.md` 或质量门记录。让"这次防住了哪些失败模式"成为永久过程记录。

---

## 与其它 skill / hook 的关系

- **被 `code-plan-review` 调用**(跑前):核对 Mode 1/4/6,写进 `experiment/code-review.md`。
- **被 `research-reflection` 调用**(跑后):核对 Mode 1/3/5,并入 `reflection.md` 第 5 块归因。
- **被 `peer-review` / `quality-gate` 调用**(定稿前):复查全部 7 项,Mode 2 借 `citation-faithfulness`、
  Mode 4/7 由审稿视角盯。
- **hook 是硬底线**:Mode 3 / Mode 1 数字异常 / Mode 6 数字脱节,数字核验门 + 实验质量门已自动拦;
  本 skill 做 hook 覆盖不到的**软判断**(捷径/叙事/框定),两者叠加才完整。

> 一句话:这 7 种失败"看起来都像好工作",所以必须在跑前、跑后、定稿前**显式逐项排除**,
> 而不是等顶会审稿人(或论文上线后)替你发现。
