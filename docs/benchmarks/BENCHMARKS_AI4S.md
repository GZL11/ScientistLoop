# AI4S / 科研 Agent Benchmark 总览

> 用途：为 famou-scientist 选评测对标。重点是**测得到我们真正声称的能力**（文献 → 假设 → 实验设计 → 真跑代码 → 结果 → 论文 → 引用核验），而非只刷指标的工程题。
> 本文按**我们科研流水线的环节**组织——每段对应若干 benchmark，标注**评什么 / 评测标准 /
> 怎么评 / 与我们能力的映射**，以及**科研 vs 刷分**取向。

---

## 0. 先建两个判别坐标（选 bench 前必须分清）

### 坐标一：开放式研究 vs 论文复现（任务类型本质不同）
- **开放式研究 / 发现**：**没有参考答案**，目标是探索 / 产出新东西。只能靠 scoring function、
  rubric/LLM 裁判、或对标人类来量质量。
- **论文 / 实验复现**：**金标 = 论文已发表的结果**，目标是重建并对齐已知结论，评"是否复现出原结果"。

### 坐标二："金标"≠"scoring function"（都让你看到分数，但不是一回事）
- **金标（参考答案 / 参考解）**：题目预先有"标准正确解"，产出拿去**对齐**它（复现类、Kaggle 类有）。
- **scoring function（质量度量）**：只是一把**尺子**量你解得多好，**但没有已知最优解、没有答案可抄**（RE-Bench 这种）。

> 所以**"开放"不等于"没有分数"**。区分"开放式研究"与"工程刷分"的**硬判据**：
> **把网上的标准解抄一份进来能不能拿高分？** 能（MLE-bench：旧 Kaggle 题、解法公开）→ 刷分；
> 不能（RE-Bench：题全新、无公开解、上限未知）→ 真探索。

### 坐标三：自主度光谱——"谁选题、谁提 idea"决定了还能不能客观评分

把"做科研"拆成**五个自主度维度**。benchmark 把哪几维交给 agent，直接决定它**还有没有金标可对**：

| 自主度维度 | ARC-Bench | AstaBench · E2E | 完全自主（AI Scientist v2 档） |
|---|---|---|---|
| ① 选研究方向 / 课题 | 给定 | 给定 | **agent** |
| ② 提具体 idea / 假设 | 给定（含预期结论） | 给定（写在 problem_description） | **agent** |
| ③ 实现方法 + 真跑实验 | agent | agent | agent |
| ④ 分析 + 写论文 | agent（止于 claims） | agent | agent |
| **⑤ 评分锚** | **金标 / 参考值**（物理对论文数、生物对 FBA 经典值） | **rubric 核对②是否被忠实实现** | **无金标可对** |

**核心规律：越往①②放开，越没有"标准答案"可对齐 → 第⑤步评分只能退守两条路，且都做不成干净的 leaderboard：**

- **路 A：LLM 模拟同行评审打分。** 但 LLM 审稿有系统盲区——过度看重"技术正确"、**严重低估新颖性**、与专家判断偏离；且存在"**新颖性悖论**"：初筛觉得新颖的 idea，实现后往往不如人类 idea，且生成越多越**趋同**。
- **路 B：真投会议，用人类录用与否当指标。** 终极测试，但**一次性、不可复现、不可批量**——做不成榜。

所以**"agent 自己选题 → 独立科研 → 出论文"这一极，目前只活在系统 / demo 里（见 §3），没有带 held-out 金标的标准 benchmark**——这不是"还没人做"，而是**"自主选题"与"客观评分"在结构上互斥**。本表 §Ⅴ 的 ARC-Bench / AstaBench-E2E / ResearchClawBench **全都停在"②给定"那一档**，正是为了让⑤可评。

> **对 famou-scientist 的含义（务实双轨）**：我们的产品愿景（你提课题 → agent 自主科研 → 成稿）对应**①②也放手的"完全自主"档**，恰恰是没有 gold 榜可刷的那一档。因此：
> **(a) 对外刷榜** → 用"②给定"的档（ARC-Bench / AstaBench-E2E / ResearchClawBench，可比、有名次）；
> **(b) 完全自主档** → 对标 AI Scientist v2 玩法：用**我们自己的评审护栏**（`peer-review` 模拟顶会 + `quality-gate` 放行 + `code-plan-review` 防 Hidden Pitfalls 那类静默偏离/造数据）**替代不存在的客观评分**，并以"真跑通一两个自选课题、甚至真投 workshop"作**能力 demo**，而非刷榜。

---

## 1. 全景表：按科研流水线环节分类

| # | 环节（对应我们能力） | benchmark | 任务类型 | 取向 |
|---|------|-----------|---------|------|
| **Ⅰ** | **想法 / 假设生成**（"提假设"） | IdeaBench、ResearchBench、LiveIdeaBench、AI Idea Bench 2025、ResearcherBench、Scientist-Bench(L2) | 开放·无答案 | ★★★ |
| **Ⅱ** | **数据驱动发现 / 分析**（"假设+结果分析"） | DiscoveryBench、BLADE、BixBench、BaisBench、ScienceAgentBench | 半开放 | ★★★ |
| **Ⅲ** | **科学代码实现**（"写代码"） | SciCode | 有金标（功能正确） | ★★ |
| **Ⅳ** | **实验执行 / 复现**（"真跑"+对齐已知） | EXP-Bench、SUPER、PaperBench、CORE-Bench | 复现·有金标 | ★★★ |
| **Ⅴ** | **端到端开放式研究**（全流程，无答案——最难） | **ARC-Bench（多领域）**、ResearchClawBench、RE-Bench、MLGym、MLAgentBench、Curie、AstaBench(E2E)、DiscoveryWorld（模拟） | 开放·无答案 | ★★★ |
| **Ⅵ** | **领域科学专项**（化学/生物/材料垂直） | ChemBench、LAB-Bench(2)、BioCoder、MatBench Discovery、**LifeSciBench** | 多为有金标（LifeSciBench=专家 rubric 自由作答） | ★★ |
| **Ⅶ** | **ML 工程刷分**（能力下限，别当科研成绩） | MLE-bench、MLAgentBench、DSBench | 金标·可抄 | ☆ |
| **Ⅷ** | **综合套件 / 基础设施 / 诚信** | AstaBench、**SGI-Bench**（PIM 四环·跨 Ⅰ/Ⅱ/Ⅳ/Ⅵ+多模态）、HAL Leaderboard、SciIntegrity-Bench、AblationBench | 框架 / 专项 | — |

> 同一 benchmark 可能跨环节（如 ScienceAgentBench 既测分析又测代码、MLAgentBench 既是 Ⅴ 也算 Ⅶ）。
> AI Scientist / AI Scientist-v2 / AI co-scientist / Agent Laboratory / AI-Researcher 是**系统**而非 benchmark，
> 各自自带评测（多用 Ⅴ 的方式），见 §3。

---

## 2. 逐环节详解

### Ⅰ. 想法 / 假设生成（开放·无答案；评的是"点子"好不好）

> 共性难点：**新颖性最难自动评**。Si et al. 招了 100+ NLP 研究者做人评，发现 LLM 当裁判与专家一致性偏低；且"同一想法换种说法，新颖性打分会矛盾"。所以这类多用**多裁判取平均 + 接文献做接地**。

- **IdeaBench**（KDD'25）：**8 领域 2374 篇高影响论文 + 29408 篇引用**作上下文，把 LLM 设定成领域研究者
  生成想法，用**参考导向指标**（与人评对齐）排名。结论：**LLM 想法够新但常不可行**，宜做"扩展思路空间"而非直接落地。
- **ResearchBench**（2025）：**inspiration-based 任务分解**——把发现拆成背景知识、灵感检索/整合、假设生成等子任务
  分别评（IdeaBench 只评单步生成假设）。发现 LLM 能做"分布外灵感检索"，可当"假设矿"。
- **LiveIdeaBench**：评**最小上下文下的发散思维**；originality 由**多个 LLM"评审"对每个想法取均值**度量，多维自动评。
- **AI Idea Bench 2025**：**3495 篇 2023-10 后的 AI 会议论文** + 灵感论文，量化对比 LLM 生成的想法。
- **ResearcherBench**（GAIR-NLP）：评 **deep research 系统**在**前沿开放问题**上的表现，**65 道专家精选题、34 个 AI 子领域**；
  要跨论文综合、专家判断、细腻推理。贴近"深度调研/综述"能力。
- **Scientist-Bench**（AI-Researcher 配套）：**L1 给明确指令**（执行既定想法）/ **L2 不给指令**（自主提研究方向），
  22 篇论文，多 LLM 裁判。有趣发现：系统在 **L2 开放探索反而比 L1 受指导实现做得好**。
- **映射**：直接打我们"提假设"这一段。但注意——这些大多评"点子文本"，**不要求真跑验证**；我们的差异化是
  假设之后还能真做实验，所以这类作"假设质量"单点检验，别当全能力证明。

### Ⅱ. 数据驱动发现 / 分析（半开放；给数据→推结论，AI4S 内核）

- **DiscoveryBench**（AllenAI，ODC-BY）：给数据集 + 自然语言发现目标，推出假设 `h = ψ(context, variables, relationship)`。
  **6 领域**（社会学/工程/生物/史学…），264 真实任务（论文反推）+ 903 合成任务（可控难度），分 DB-REAL / DB-SYNTH。
  评测：**预测假设 vs 金标在 context/variables/relationship 三要素上的语义蕴含**（GPT-4 裁判）。最好系统 ~25%，极难。
  → 我们"提假设"唯一能被严肃量化、且明确反刷分的地方。
- **BLADE**（EMNLP'24）：评**分析决策**——给研究问题+数据，agent 产出"概念变量 + 数据变换函数 + 统计建模函数"整套分析。
  金标来自**多位专家独立分析**；评测用**数据流图匹配**（变换）+**语义等价**（变量），容忍"多条合理路径"。最佳 F1 仅 **44.8%**。
- **BixBench**（2025）：**计算生物开放式数据分析**第一个 benchmark。53 个真实 capsule（数据文件+开放问答），296 题，
  做完合法分析才答得出，多步长轨迹。发现 o1/R1 在长上下文+结构化工具调用上吃力、**看图能力差**——正好压测我们绘图闭环。
- **BaisBench**：评 AI scientist 通过**数据分析 + 结合外部知识推理**做出**生物学发现**的能力。
- **ScienceAgentBench**（OSU-NLP，ICLR'25）：从 **44 篇同行评审论文**抽 **102 个任务**，覆盖**生信/计算化学/GIS/心理认知神经**；
  每个是真实工作流的**自足阶段**（故意先评单步，反对过早宣称端到端）。评：代码**执行成功率 + 结果正确性 + 成本**，9 位专家验题。
  **容器化 harness**，8 线程约 30 分钟跑完 102 题（已并入 OpenHands）。最强 ~33%（任务专用 scaffold）→ 换通用 scaffold 掉到 ~10%。
  → **★首选**：领域全、好跑、有专家金标、迭代快。

### Ⅲ. 科学代码实现（有金标=功能正确；写"做科研的代码"）

- **SciCode**（NeurIPS'24）：科学家策展，**物理/数学/化学/生物/材料 16 个子领域**，从**真实科研脚本**（多数进过论文）转化而来，
  **80 道主问题拆成 338 个子问题**，每子问题要写一个 Python 函数再集成；可选给科学背景说明。
  极难：**最强的 Claude 3.5 Sonnet 在最真实设定下只解出 4.6%**。
  → 打我们"把方法翻译成正确科研代码"的硬实力，领域广，适合做能力雷达。

### Ⅳ. 实验执行 / 复现（复现·有金标；目标是"对齐已知结果"）

> 难度梯度：**给齐 repo 跑通（SUPER）< 给不全的 starter code 复现实验（EXP-Bench）< 从零复现整篇（PaperBench）**。

- **SUPER**（AllenAI'24）：测 agent **配环境+跑通 research repo**——装依赖、改配置、修过时依赖、找对执行命令。
  **45 端到端 + 152 子问题 + 602 自动生成**；偏"**生成命令而非写代码**"。SUPER-Expert 是最难档（无提示从零复现）。
- **EXP-Bench**（ICLR'26，Curie 团队）：给**研究问题 + 不完整 starter code**，agent 要**提假设→设计→实现→执行→分析**完整实验。
  **461 个任务、51 篇顶会论文**（NeurIPS/ICLR）。结果触目：单项（设计/实现正确性）偶达 20–35%，但**完整可执行实验成功率仅 0.5%**。
  瓶颈定位清晰：设计变量错配 16.1%、缺关键实现 39.7%、环境/依赖或脚本错 ~29%/~24%。→ 极贴合我们"真跑实验"。
- **PaperBench**（OpenAI）：给 20 篇 ICML'24 Spotlight/Oral，**从零**理解贡献→写整套代码库→干净环境跑→对齐论文结果（不给原码）。
  每篇配作者认可**分层 rubric 共 8316 个原子评分点**，**LLM-as-judge** 逐点判。→ 对标我们整条 文献→实验→论文 链，rubric 契合质量门哲学。
- **CORE-Bench**：给齐代码+数据+环境，测能否**复现已发表的计算分析**（比 PaperBench 容易，专测"复现"本身）。
  → 呼应我们的引用核验门 / 数字核验门。

### Ⅴ. 端到端开放式研究（全流程，无参考答案——最难，自动化最不成熟）

> 共性：**没有答案可对齐**，要跑完整研究循环。两种风味：**研究*工程***（优化某指标）vs **科学*发现***（产出新结论）。
> 全行业现状：完成完整项目所有步骤的概率极低（AstaBench ~1%、EXP-Bench 0.5%）。

- **ARC-Bench**（🤗 AIMING-Lab-UNC/ARC-Bench；**AutoResearchClaw 自己的 benchmark**）：
  **55 topic / 5 领域——ML(25)、高能物理(10)、量子(10)、生物(7)、统计(3)**，覆盖面是本表里对我们最全的。
  只给**研究问题（不给方法）**+ 一份 manifest（synthesis / conditions / metrics / datasets / hypotheses），框架自己走完
  **code → measurements → claims → writeup**（PaperBench submission 布局）。**与 PaperBench 的关键区别**：不是复现已知论文，
  而是**从一个问题做实验问题求解**——"更像研究生真实在做的事"。已对比基线：AIDE / AI Scientist v2 / Agent Laboratory / rc_full / rc_copilot(HITL)。
  - **领域执行器（按 domain 自动路由——"真跑实验"在每个学科落到该领域的真实工具，不靠一个 ML 沙箱通吃）**：
    - **HEP = ColliderAgent**：跑高能物理 MC 链 `Lagrangian → FeynRules → MadGraph5（事件生成）→ Delphes（快速探测器模拟）→ 重建/分析`；
    - **生物 = COBRApy**：基因组尺度代谢建模 / 通量平衡分析（FBA）；
    - **统计 = simulation agent**：模拟研究——已知参数下生成合成数据，检验方法的覆盖率/功效/偏差等；
    - **化学·材料 = Docker**：通用兜底沙箱，agent 自行装 RDKit/ASE/pymatgen 等任意包跑。
  - **评测标准（多准则 rubric 审计，框架无关）**：
    - **层级加权 rubric 树**：root → 分桶（**代码开发 / 代码执行 / 结果分析 / writeup**；物理·生物·统计是 4 桶，多一个 **repro 复现**，ML·量子 3 桶）
      → 每桶下若干**加权叶子**（~8 个），每叶带 `task_category` + 细分类，按权重汇总成**加权 rubric 分**。
    - **每个叶子判什么**（来自 EXPERIMENT_DESIGN）：① 代码开发=对每个 condition 写**方法忠实**的代码；② 代码执行=产出含**声明 metric 键、跨声明 seed**
      的 `metrics.json`；③ 结果分析=`claims.json` 里**每条假设**给 `expected/observed/verdict` 三元组且**有 metrics 证据支撑**；
      ④ writeup=`README.md` 内 400–1200 字、含 Method/Results/Verdict/Limitations。
    - **判分基调**：judge 被要求**看科学实质与方向正确性**，给部分分，**不因措辞/命名不符扣分**；定量叶子按**容差分级**
      （如物理：相对误差 <3% 给 100%、<10% 给 67%、<30% 给 33%，否则 0）。
    - **两道 judge**：auto-judge（LLM，results-only）+ judge_manual（Claude/Codex/人工审计派发）；另有一份**共享论文质量 meta-rubric**
      （paper-content / code-orchestration / visual-layout / content-accuracy，**人工评**不自动跑）。
    - **范围**：注入 stage 10（代码生成）→ 停在 stage 14（结果分析）→ `paperbench_finalize.py` 收尾；**不含 stage 15–23 的成稿**（在别处评）。
  - **防编造内置**：claims 须 metrics 证据支撑——与我们数字核验门同源。
  → **首要 dogfood 目标**：领域最全、评分契合我们整条链与诚信门；接入需写 famou-scientist 适配器（类似它给 AIDE 等写的 adapter），
    纯 ML 子集（ML01–ML25）可直接用我们现有沙箱，其余领域需对接对应 executor。
- **ResearchClawBench**（arXiv 2606.07591，**上海 AI Lab / InternScience**——与 ARC-Bench 是**不同团队的不同 benchmark**）：
  **40 任务 / 10 学科（10×4，含天文、化学…）**。每个任务**锚定一篇真实已发表论文**，给相关文献 + 原始数据，但**评测时把目标论文藏起来**
  （防泄漏）——看 agent 能否从原始数据独立得出**同样或更好的科学结论**。两阶段：**自主研究 → 同行评审式打分**；**专家标注多模态 rubric**
  拆成加权准则；定位 **re-discovery（复现发现）→ new-discovery（新发现）**，故跨 Ⅳ/Ⅴ。
  **有第三方在线 leaderboard + 可提交**（GitHub/HF space）；统一协议评了 **7 个自主 agent + 17 个 LLM**（经其轻量 ResearchHarness）。
  现状普遍很低（满分 100）：最强自主 agent **Claude Code 21.5**、最强 LLM **Claude-Opus-4.7 20.7**、LLM 前沿均值 **26.5**。
  → **最适合"对外背书"**：第三方公开榜、目标论文隐藏防泄漏、且把 **Claude Code 当基线**（我们也是 Claude 系，直接可比）。
  **同团队姊妹作 SGI-Bench**（见 §Ⅷ）是其"单步多任务能力雷达"版（PIM 四环分任务评，非端到端），两者可搭配用。
- **RE-Bench**（METR V1）：**7 个全新手工 ML 研究工程环境**（拟合 scaling law、写 GPU 前缀和 kernel、微调 GPT-2 做 QA…），
  8h + 最多 6×H100。**精确 scoring function、无金标解、不靠裁判**（取 score log 最高分，Scaling Law 取最终提交）。
  **对标 61 位人类专家的 71 次 8h 尝试**。核心发现：**2h AI 是人类 4×，8h 人类略胜，32h 人类 2× AI**；某 agent 写的 Triton kernel 比所有专家都快。
  → 开放式研究**工程**（非科学发现），作我们的工程能力下限 / 长程提升曲线自测。
- **MLGym / MLGym-Bench**（Meta）：**首个 Gym 接口**的 AI 研究 agent 框架，**13 个开放式 AI 研究任务**（CV/NLP/RL/博弈论/SAT），
  含 6 级自主性框架（bench 聚焦 L1）。发现：模型主要靠**调超参**改进基线，**生不出新假设/新算法/新架构**。
- **MLAgentBench**：最早的 AI 研究 agent benchmark，**13 个 ML 任务**（图像分类→语言建模），最难任务当时 SOTA **0% 成功**。
- **Curie**（+ 自带 benchmark）：强调**实验严谨性**（intra/inter-agent rigor + 知识模块）；benchmark **46 题、4 个 CS 领域**，
  源自有影响论文与开源项目；比最强基线（OpenHands / Magentic）**正确作答提升 3.4×**。
- **AstaBench · E2E Discovery**（AllenAI）：**输入只是一个想法 / 研究目标**——**不给方法、不给目标论文、没有标准答案**；
  agent 要**自主当研究员把整个项目做完**：自己**设计实验 → 真跑 → 分析 → 产出"研究报告 + 配套代码/产物"**（怎么做全由它决定，不是照 spec 实现）。
  **评的就是这套最终产物**（report / code / artifacts）：**每题专属 rubric + 分步 LLM 裁判**逐条打分。变体 **E2E-Bench-Hard** 从研究趋势/
  未充分探索问题**自动生成**、只做可行性检查不简化。**单步 ~70% 但全项目 ~1%**（卡在长程把事情从头串到尾，非单点能力）。它是 §Ⅷ AstaBench 套件的一部分。
  **与 ResearchClawBench 的区别**：AstaBench E2E **没有隐藏的标准答案**（rubric 只描述"好项目长什么样"，纯开放）；
  ResearchClawBench 有**藏起来的真实论文**作参照（判"追平/超越"）。故前者纯 Ⅴ、后者跨 Ⅳ/Ⅴ。
- **DiscoveryWorld**（NeurIPS'24，AI2+MSR）：**模拟虚拟环境**里跑完整发现循环（提假设→设计→跑→分析→下结论）。
  **120 个任务 / 8 主题 / 3 难度**（放射性测年、火箭、蛋白质组学…）；3 个自动指标：**二元完成 / 细粒度流程报告卡 / 发现知识的准确率**。
  低保真但**强基线也普遍做不动**——便宜的"发现能力代理评测"。
- **映射**：最贴近我们"全流程自动科研"的终极声明，但短期天花板太低；作**远期标杆 / 长程编排压测**，别当主指标。

### Ⅵ. 领域科学专项（垂直深，看特定学科）

- **ChemBench**（《Are LLMs superhuman chemists?》）：**2700+ 化学问答**，最强模型**平均超过参与研究的人类化学家**（已发 Nature Chemistry）。
  **LAB-Bench / LAB-Bench2**：2400+ 道实操生物研究 **MCQ**（文献推理、读图、数据库、DNA/蛋白序列）；
  易自动评但偏"会不会"非"做不做得到"。**BioCoder**：生信代码生成与函数调用。**BioLP-Bench**：实验室协议。
- **LifeSciBench**（OpenAI，2026-06-17，配合 GPT-Rosalind 发布；**173 位 PhD 级生物/药企科学家**共建）：刻意区别于"教科书式 MCQ"，
  直击"科学家要在不完美证据里做判断"这一真实工作流。**750 道自由作答任务**，覆盖 **7 类研究工作流 × 7 个生物领域**
  （基因组学 / 药物化学 / 临床转化…）；每题配 prompt + **科研产物**（基因组序列文件、化学结构文件、实验图表，共 **1062 件**）+
  **专家手写 rubric（平均 25 条准则，合计 19020 条）**；平均需 **4 步推理、53% 要综合多个产物**。**单轮评测、允许联网检索。**
  结果极低：最强 **~36%**（GPT-Rosalind 独占领先 386/750、Gemini 3.1 Pro 214/750），部分口径仅 **28%**。OpenAI 明确定位为
  "**测量计划的起点而非终点**"，并强调"**单轮 rubric 打分 ≠ 自主研究伙伴**"。
  → **与我们的关系**：它评的是"**科研判断 / 推理 + 读科研产物**"的单步硬实力（偏 Ⅱ/Ⅵ，**非 Ⅴ 端到端**），
  且其 **rubric 哲学（专家手写、按准则逐条判、看判断而非标准答案）与我们的质量门同源**；生命科学正好补我们的覆盖盲区。
  但注意它**单轮、非 agentic**——别拿它证明端到端自主能力。
- **MatBench Discovery**（材料）：从静态预测转向**发现导向**——用 MLIP 对**留出结构**给稳定性候选**排序**的能力。
  已有"全 agentic LLM 发现策略（ReAct 控制环）"与之对比，权衡探索多样性 vs 效率。

### Ⅶ. ML 工程刷分（看能力**下限**，别当科研指标）

- **MLE-bench**（OpenAI）：离线 Kaggle 竞赛环境，**奖牌制**（按真人百分位发铜/银/金）+ 标准指标。
  报告规矩：**≥3 seed，报 Any-Medal% 的 mean ± 1 SEM**；多次尝试涨分明显（o1-preview pass@1 16.9% → pass@8 34.1%）。
  **为何只是下限**：题旧、解法公开、标准实现就能拿牌。**DSBench / MLAgentBench**同类。

### Ⅷ. 综合套件 / 基础设施 / 诚信

- **AstaBench**（AllenAI）：把科研全流程打包，**11 个子 bench / 4 大类**（文献理解、代码执行、数据分析、端到端发现），**2400+ 题**。
  评 **57 个 agent / 22 类**，**统一工具集**做公平对比；**关键创新**：不只记准确率，还**记算力/成本并画 Pareto**，全程记 commit/模型版本保可复现。
- **SGI-Bench**（arXiv 2512.16969，2025-12；**InternScience / 上海交大——与 ResearchClawBench 同团队**）：提出 **Scientific General
  Intelligence(SGI)** 概念，用 **Practical Inquiry Model(PIM)** 把科研拆成 **Deliberation / Conception / Action / Perception** 四环，
  对应**四族单步任务**：① 深度调研（多跳检索/综合/meta-analysis 式推理，指标 **EM / SLA** 步级对齐）② 想法生成（结构化 ideation + 多维对比，
  Implementation Similarity）③ 干/湿实验（代码生成 **PassAll@k / SER** + 实验室 protocol 核验）④ 实验推理（过程/观测/模拟/可视化**多模态图像推理**，**MCA / RV**）。
  **1000+ 专家精选样本 / 10 学科**，灵感取自《Science》125 Big Questions；造题 100+ 硕博 + expert-in-loop，**难度过滤**剔除被 >50% 强模型答对的样本；
  HF 数据集 **gated 防网搜泄漏**。配 **agentic 评测框架**（选题→指标定制→预测&评→报告生成，工具池含 web 搜索/PDF 解析/Python/file reader/metric 函数，
  指标可加 rigor/feasibility）。另提 **TTRL**（Test-Time RL）：GRPO 在 Qwen3-8B 上**无标签**优化检索增强的新颖性奖励（novelty 49.36 → 62.06）。
  结果普遍低（满分~100）：最强 **Gemini-3-Pro SGI 33.83、Claude-Sonnet-4.5 32.16、Qwen3-Max 31.97**，结论"局部能力强但远未达整合/数值可靠/方法学严谨"。
  已并入 VLMEvalKit / SciEvalKit，有 **SGI-Bench-Lite** 快评版。
  - **与 ResearchClawBench 的区别（同团队但定位不同）**：后者是**端到端自主**（给原始数据→独立得结论→同行评审打分，落 §Ⅴ）；
    SGI-Bench 是**按 PIM 拆成单步分任务评的"跨环节能力雷达"**——横跨 Ⅰ(想法)/Ⅱ(深度调研·分析)/Ⅳ(干实验代码)/Ⅵ(湿实验协议)，
    并补一个我们较薄的**多模态实验图像推理(Perception)**维（类似 BixBench 的看图压测）。
  → **对我们**：覆盖全链各环节、公开榜上 **Claude-Sonnet-4.5 排第二可直接对比**、多模态读图正好压测绘图/读图闭环——**适合做对内能力雷达 / 多维诊断**；
    但**单步非端到端**，第一轴（自主科研契合度）失分，别拿它证明端到端自主能力（那档仍是 AstaBench / ResearchClawBench）。
- **HAL（Holistic Agent Leaderboard）**：跨模型 × scaffold 的统一评测基础设施（SAB 的 19 次评测即出自它）。
- **SciIntegrity-Bench**（arXiv 2605.10246）：评 **AI scientist 系统的学术诚信**——**33 个场景 / 11 类陷阱**，
  采用"两难"范式：每个场景**只有"诚实承认失败"才算对，而"完成任务"必然要不端**。231 次评测、7 个 SOTA 模型，
  整体诚信问题率 **34.2%，无一模型零失败**；最刺眼的是**缺数据场景下 7 个模型全部生成合成数据**（只是披不披露的差别）。
  prompt 消融显示：去掉"完成压力"能把"未披露的编造"从 20.6% 压到 3.2%，但底层合成倾向不变。
  → **直接对标我们的防编造数据 / 防幻觉引用护栏**，是我们最该拿来证明差异化的诚信维度。
- **SciIntBench**（arXiv 2605.29468）：评 LLM 在**对抗性 framing** 下对科研诚信规范的遵守——810 个 prompt、
  10 类 RCR、3 个学科，每个含 Overt/Covert/Benign 三版。发现诚信对齐**强烈受 framing 影响**：显式不端易拒、
  **隐蔽（伪装成"压力下的捷径"）就守不住**。
- **Hidden Pitfalls of AI Scientist Systems**（CMU，arXiv 2509.08713）：用受控合成任务 + LLM 审计框架，量化
  AI scientist 系统的**四大隐患——① 不当 benchmark 选择（挑有利数据集）② 数据泄漏 ③ 指标误用 ④ 事后选择偏差**。
  对两个主流开源 AI scientist 系统的审计发现这些失败普遍存在、易被忽略；建议**交全流程日志做审计**。
  → 给我们的"质量门"列了一张明确的"要防什么"清单。
- **AblationBench**：评在实证 AI 研究中做**消融实验计划**的能力（niche，但贴近实验设计）。

---

## 3. 系统（非 benchmark，但定义了"自主科研"该长啥样）

> 这些是端到端 **AI Scientist 系统**，各自带评测（多用 §Ⅴ 的 rubric/裁判），可作架构参照与对手。

- **The AI Scientist / AI Scientist-v2**（Sakana）：完整流水线——头脑风暴想法→评新颖性→改代码实现→跑实验→写论文→**自动同行评审**；
  v2 用 **agentic 树搜索**做到 workshop 级自动发现。
- **AI co-scientist**（Google，arXiv 2502.18864）：多 agent "共同科学家"。
- **Agent Laboratory**：PhD/Postdoc/ML工程师/教授等角色协作，三段式 文献综述→实验→写报告；支持**全自主**与 **co-pilot**（关键节点人审）两种模式。
- **AI-Researcher**（NeurIPS'25）：全自动从概念到成稿，配 Scientist-Bench（见 §Ⅰ）。
- **怎么评这些系统（没有金标，呼应 §0 坐标三）**：只能走两条路——**LLM 自动审稿**（v2 自带 AI reviewer，但有"低估新颖性"盲区）
  或**真投会议**（v2 三篇投 ICLR workshop，一篇过人类评审、已发 *Nature*，**史上首次** AI 全自动论文过同行评审）。
  且需警惕**自生成 idea 的退化**：对 v2 生成的 1000 个 idea 审计发现明显**挑 SOTA 高的"软柿子"benchmark**、缺数据时**合成数据集**
  （Hidden Pitfalls，见 §Ⅷ）——这正是"完全自主"档最需要 `code-plan-review` 兜底之处。
- **现实检查**：《Why LLMs Aren't Scientists Yet》（2601.03315）等系统评估泼冷水——超出 demo 的真实科研任务，当前框架仍很脆。

---

## 4. 评测"方式 / 标准"五种范式（选 bench 先看它用哪种）

| 范式 | 怎么打分 | 优点 / 陷阱 | 用在 |
|------|---------|-----------|------|
| **奖牌 / 百分位** | 对齐真人 leaderboard 发牌 | 客观；但有公开解 → 刷分 | MLE-bench |
| **精确 scoring function** | 任务自带连续度量（无金标解也能打分） | 无裁判偏差；要能写出度量 | RE-Bench、DiscoveryWorld |
| **rubric + LLM 裁判** | 作者认可的分层 rubric 逐原子点判 | 能评长程/开放产物；裁判需校准 | PaperBench、AstaBench-E2E、EXP-Bench、LifeSciBench |
| **结构化语义匹配** | 预测 vs 金标在 变量/关系/变换图 上匹配 | 抓住"发现/分析"本质；依赖裁判语言判定 | DiscoveryBench、BLADE |
| **多裁判取均值（新颖性）/ MCQ** | 多 LLM 评审平均 / 选对算对 | 易自动；新颖性裁判可靠性存疑、MCQ 偏"会不会" | LiveIdeaBench、LAB-Bench |

> 范式必须配任务类型：**开放式研究**（无金标）只能用 scoring function / rubric / 对标人类 / 多裁判；
> **复现**（有金标）才能用"对齐原结果"。选错范式 = 评不到真能力。

**报告硬规矩**：① 多 seed + 均值 ± SEM（高方差）；② 报 pass@k 而非只 pass@1；
③ 固定工具集 + 记成本、画成本-准确率 Pareto（AstaBench 范式）；④ 记 commit / 模型版本。

---

## 5. 给 famou-scientist 的对标优先级

按"测得到我们真正声称的能力 + 可操作性"排序：

0. **ARC-Bench**（Ⅴ，★首选）：AutoResearchClaw 自己的 benchmark，**5 领域 55 topic**（含 HEP/量子/生物/统计，非纯 ML）、
   从问题做完整实验、多准则 rubric 审计、claims 须 metrics 证据支撑——覆盖最全、最贴合我们整条链与诚信门。接入需写 famou-scientist 适配器。
1. **ResearchClawBench**（Ⅳ/Ⅴ，★对外背书首选）：上海 AI Lab 的独立 benchmark，**40 任务 / 10 学科**、藏目标论文防泄漏、
   **有第三方在线榜可提交**、以 **Claude Code（21.5）为基线**——是我们拿"第三方可验证名次"对外背书的最佳选择。
2. **ScienceAgentBench**（Ⅱ，★外部首选）：领域全、容器化好跑、单步严谨、有专家金标；30 分钟一轮，迭代快。
3. **DiscoveryBench**（Ⅱ）：打**假设生成 / 数据驱动发现**，明确反刷分。
4. **EXP-Bench**（Ⅳ）：打**真跑实验**全链（提假设→设计→实现→执行→分析），瓶颈定位细，直击我们核心声明。
5. **PaperBench / CORE-Bench**（Ⅳ）：**论文复现 / 可复现性**，rubric 契合我们质量门；CORE 呼应核验门。
6. **SciCode**（Ⅲ）：跨 16 学科的**科研代码**硬实力雷达。
7. **BLADE / BixBench**（Ⅱ）：**开放式数据分析 + 看图**，压测分析决策与绘图闭环。
8. **IdeaBench / ResearcherBench**（Ⅰ）：单点检验**假设质量 / 深度调研**（注意它们不要求真验证，别当全能力证明）。

**作下限 / 远期标杆，不当科研主成绩**：
- **MLE-bench（Ⅶ）、RE-Bench / MLGym（Ⅴ 工程）**——工程能力下限；
- **AstaBench E2E / DiscoveryWorld（Ⅴ 发现）**——端到端开放科研，全行业 <1%，远期天花板。

> **覆盖盲区（本文尚薄，后续补）**：数学 / 定理证明、天文、临床医学、自动驾驶实验室（self-driving lab）、社会科学等领域的
> 自主科研 benchmark 本文覆盖不足；本列表不追求穷尽，接入前按需再扫这些方向。

**额外关注**：**SciIntegrity-Bench / SciIntBench / Hidden Pitfalls** 直接对标我们的防编造 / 防幻觉护栏与质量门
（缺数据时编造、对抗 framing 下失守、benchmark 挑选/数据泄漏/指标误用/事后偏差），是"诚信"维度最该拿来证明差异化的一组。

---

## 6. 链接与许可

| Benchmark / 系统 | 链接 | 备注 |
|-----------|------|------|
| **ARC-Bench** | https://huggingface.co/datasets/AIMING-Lab-UNC/ARC-Bench · 上游 AutoResearchClaw `experiments/arc_bench/` · [paper](https://arxiv.org/abs/2605.20025) | **5 领域 55 topic**；问题→实验；rubric 审计；无在线榜 |
| **ResearchClawBench**（独立·上海 AI Lab） | https://arxiv.org/abs/2606.07591 · [repo](https://github.com/InternScience/ResearchClawBench) · [HF](https://huggingface.co/datasets/InternScience/ResearchClawBench) | **40 任务 / 10 学科**；藏目标论文；**有在线榜可提交**；Claude Code 21.5 |
| **SGI-Bench**（InternScience·同 ResearchClawBench 团队） | https://arxiv.org/abs/2512.16969 · [repo](https://github.com/InternScience/SGI-Bench) · [site](https://internscience.github.io/SGI-Page/) · [HF](https://huggingface.co/collections/InternScience/sgi-bench) | 2025-12；**PIM 四环 / 1000+ 题 / 10 学科**；单步多任务能力雷达+多模态；HF gated；榜首 Gemini-3-Pro 33.83、Claude-Sonnet-4.5 32.16 |
| ScienceAgentBench | https://github.com/OSU-NLP-Group/ScienceAgentBench · [OpenReview](https://openreview.net/forum?id=6z4YKr0GK6) | ICLR'25；容器化 harness；**任务 CC BY 4.0 + 代码 MIT** |
| DiscoveryBench | https://arxiv.org/abs/2407.01725 · [repo](https://github.com/allenai/discoverybench) | **ODC-BY** |
| BLADE | https://arxiv.org/abs/2408.09667 · [repo](https://github.com/behavioral-data/BLADE) | EMNLP'24；数据分析 |
| BixBench | https://arxiv.org/pdf/2503.00096 | 计算生物开放式分析 |
| BaisBench | https://github.com/EperLuo/BaisBench | 生物发现 |
| SciCode | https://scicode-bench.github.io/ · [repo](https://github.com/scicode-bench/SciCode) | NeurIPS'24；16 学科；见 repo LICENSE |
| EXP-Bench | https://arxiv.org/abs/2505.24785 · [repo](https://github.com/Just-Curieous/Curie/tree/main/benchmark/exp_bench) | ICLR'26；461 任务 |
| SUPER | https://arxiv.org/abs/2409.07440 · [repo](https://github.com/allenai/super-benchmark) | 配环境+跑 repo |
| PaperBench | https://arxiv.org/pdf/2504.01848 | OpenAI；8316 rubric 点 |
| CORE-Bench | https://arxiv.org/abs/2409.11363 | 可复现性 |
| RE-Bench | https://metr.org/blog/2024-11-22-evaluating-r-d-capabilities-of-llms/ · [repo](https://github.com/METR/RE-Bench) | METR；对标人类专家 |
| MLGym | https://arxiv.org/abs/2502.14499 · [site](https://sites.google.com/view/mlgym) | Meta；Gym 接口 |
| MLAgentBench | https://openreview.net/forum?id=N9wD4RFWY0 | 最早 AI 研究 agent bench |
| Curie | https://arxiv.org/abs/2502.16069 · [repo](https://github.com/Just-Curieous/Curie) | 严谨实验；46 题 |
| DiscoveryWorld | https://arxiv.org/abs/2406.06769 · [site](https://allenai.github.io/discoveryworld/) | NeurIPS'24；模拟发现 |
| AstaBench | https://allenai.org/asta/bench · [paper](https://arxiv.org/pdf/2510.21652) · [repo](https://github.com/allenai/asta-bench) | 套件；成本-准确率 Pareto |
| MLE-bench | https://arxiv.org/abs/2410.07095 · [repo](https://github.com/openai/mle-bench) | OpenAI；Kaggle 奖牌 |
| IdeaBench | https://arxiv.org/abs/2411.02429 | KDD'25；想法生成 |
| ResearchBench | https://arxiv.org/abs/2503.21248 | 灵感分解 |
| LiveIdeaBench | [emergentmind](https://www.emergentmind.com/topics/liveideabench) | 发散思维；多裁判 |
| AI Idea Bench 2025 | https://arxiv.org/abs/2504.14191 | 3495 篇论文 |
| ResearcherBench | https://github.com/GAIR-NLP/ResearcherBench | 深度调研；65 题 |
| Scientist-Bench / AI-Researcher | https://github.com/hkuds/ai-researcher | NeurIPS'25；L1/L2 |
| MatBench Discovery | https://matbench-discovery.materialsproject.org/ | 材料稳定性排序 |
| ChemBench / LAB-Bench | https://arxiv.org/abs/2404.01475 · [LAB-Bench](https://arxiv.org/abs/2407.10362) | 化学（超人类，Nature Chem）/ 生物 |
| **LifeSciBench**（OpenAI） | https://openai.com/index/introducing-life-sci-bench/ | 2026-06；750 任务/7 工作流×7 领域；自由作答+专家 rubric（均 25 条/共 19020）；单轮；最强 ~36% |
| SciIntegrity-Bench | https://arxiv.org/abs/2605.10246 | AI scientist 学术诚信；33 场景 |
| SciIntBench | https://arxiv.org/abs/2605.29468 | 对抗 framing 下的诚信遵守 |
| Hidden Pitfalls | https://arxiv.org/abs/2509.08713 | CMU；4 大失败模式审计 |
| AblationBench | https://github.com/ai-scientist-bench/ablation-bench | 消融计划 |
| HAL Leaderboard | https://arxiv.org/pdf/2510.11977 | 评测基础设施 |
| AI Scientist (v1/v2) | https://sakana.ai/ai-scientist/ | Sakana；系统 |
| AI co-scientist | https://arxiv.org/abs/2502.18864 | Google；系统 |
| Agent Laboratory | https://arxiv.org/abs/2501.04227 · [repo](https://github.com/SamuelSchmidgall/AgentLaboratory) | 角色协作；系统（EMNLP'25 Findings） |
| AI Idea Bench 2025 | https://arxiv.org/abs/2504.14191 · [repo](https://github.com/yansheng-qiu/AI_Idea_Bench_2025) | 3495 篇论文 |
| 综述（EMNLP'25） | https://github.com/HKUST-KnowComp/Awesome-LLM-Scientific-Discovery | LLM 科学发现全景 |

> 数据为 2026-06 核实；表中 arXiv 编号与 license（ScienceAgentBench=任务 CC BY 4.0+代码 MIT、DiscoveryBench=ODC-BY、
> AI Idea Bench 2504.14191 / Agent Laboratory 2501.04227 / ChemBench 2404.01475 / SciIntegrity-Bench 2605.10246 等）
> 均已逐一核对。本领域演进极快（EXP-Bench/ICLR'26、SciIntegrity-Bench 等为近作），接入前仍以各 repo 最新版与 LICENSE 文件为准。

---

## 7. 对外背书 Top-3 推荐（评判标准 + 评分 + 结论）

> 这一章回答一个具体问题：**若只挑少数 benchmark 对外证明 famou-scientist 的能力，选哪几个？**
> 全程用三条轴 + 明确依据推出，最后给排名与取舍。

### 7.1 评判三轴（按重要性排序）

1. **自主做科研契合度**（第一轴，权重最高）：是否评"**端到端自主研究**"——给目标/想法后，自己设计→真跑→分析→产出报告/代码。
   纯工程刷分（Kaggle）、只评单步、只评工程优化的，这一轴失分。
2. **知名度**：出品方权威性 + 业界引用/认知度（决定"对外背书"的说服力）。
3. **榜单完善度**：是否有**公开、可提交、条目丰富、记成本/可复现**的 leaderboard（决定名次是否第三方可验证）。

### 7.2 评分矩阵（★强 / ◐中 / ○弱）

| Bench | 自主科研契合 | 知名度 | 榜单完善度 | 依据（关键事实） |
|---|---|---|---|---|
| **AstaBench** | ★ | ★ | ★ | AllenAI 旗舰科学 agent；11 子bench/4大类 2400+题含 E2E Discovery；评 57 agent/22 类、成本-准确率 Pareto、记 commit/版本 |
| **ResearchClawBench** | ★ | ◐ | ★ | 上海 AI Lab；端到端、给原始数据产报告、10 学科、re-discovery→new-discovery；有在线榜可提交、已评 7 agent+17 LLM；2026-05 刚出认知爬坡 |
| **PaperBench** | ★ | ★ | ◐ | OpenAI；从零复现整篇（真建库+真跑）；8316 原子 rubric+LLM 裁判；非活跃提交竞榜 |
| **MLE-bench** | ◐ | ★ | ★ | OpenAI、极有名；Kaggle 奖牌生态成熟；**但本质 ML 工程刷分，非做科研** |
| **ScienceAgentBench** | ◐ | ◐ | ◐ | ICLR'25、进 OpenHands/HAL；**刻意只评单步、不评端到端** |
| **RE-Bench** | ◐ | ★ | ◐ | METR、有人类专家基线；**研究*工程*非科学发现**、非提交榜 |
| **ARC-Bench（自家）** | ★ | ○ | ○ | 契合度满分（上游、5领域、问题→实验）；**无在线榜、知名度低**——内部 dogfood，不参与本轮"知名度/榜单"评比 |

### 7.3 Top-3 结论与依据

1. **AstaBench（AllenAI）— 全能冠军，唯一三轴全 ★**
   - 知名度：AllenAI 出品、Asta 公开产品线，曝光高；
   - 榜单：本榜最成熟基建——统一工具集公平对比 + 成本-准确率 Pareto + 记 commit/版本（可复现）；
   - 契合：E2E Discovery 直接评"想法→完整研究项目→报告+代码"，整套件覆盖我们整条链。
   - → **对外背书第一选择**。

2. **ResearchClawBench（上海 AI Lab）— 最贴我们定位 + 有活跃可提交榜**
   - 契合：给原始数据从头做到发表级报告、藏目标论文、10 学科、re-discovery→new-discovery——与"自主做科研"几乎一一对应；
   - 榜单：在线 leaderboard 可提交、统一评 7 agent+17 LLM，且**以 Claude Code 为基线**（我们同系，直接可比）；
   - 知名度：唯一扣分项（2026-05 才出，认知上升中）。
   - → 最贴定位；赌其知名度会涨即可作主力对外榜。

3. **PaperBench（OpenAI）— 认知度背书 + 真做研究**
   - 知名度：OpenAI 出品，业内认知极高；
   - 契合：从零理解论文→建整套代码库→真跑→对齐结果（虽偏复现），8316 点 rubric+裁判与我们质量门同源；
   - 榜单：rubric/judge 开源、有多模型结果，但非持续提交实时榜（扣分项）。

### 7.4 取舍依据（为什么不是别的）

- **第 3 名替补 = MLE-bench**：其"知名度★+榜单★"甚至强过 PaperBench，但**自主科研契合度只有 ◐（Kaggle 工程，非做科研）**。
  因"自主做科研"是第一轴，让它给 PaperBench 让位；**若更看重成熟可提交的榜，可把第 3 换成 MLE-bench**。
- **ARC-Bench 不进 Top-3**：自主科研契合度其实最高，但**无公开榜、知名度低**，在后两轴垫底。正确角色是**内部 dogfood 开发标尺**，
  与"对外背书"分工不同。**建议组合用：Top-3 对外背书 + ARC-Bench 对内迭代。**
- **ScienceAgentBench / RE-Bench 落选**：前者**故意只评单步、非端到端**，后者是**研究工程非科学发现**，都在第一轴失分。
- **LifeSciBench 不进 Top-3**：知名度极高（OpenAI），但**单轮、非 agentic**——评的是"科研判断/读产物"的单步硬实力，第一轴（自主科研契合度）失分。
  正确角色是**生命科学领域的单步能力雷达 + rubric 哲学参照**，与"端到端自主背书"分工不同。

### 7.5 一句话结论
**对外**按 **AstaBench（全能）> ResearchClawBench（最贴定位、榜新）> PaperBench（认知背书）** 排；**对内**用 **ARC-Bench** 做开发标尺。
核心逻辑：**把"自主做科研"放第一轴 → 压下纯工程（MLE-bench）与只评单步（ScienceAgentBench）→ 顶上真正端到端做研究的三个。**
