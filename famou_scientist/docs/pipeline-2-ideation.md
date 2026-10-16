# 阶段二 · 提出 Idea / 生成假设技术文档

> famou-scientist 四阶段技术文档之二。本篇讲**从研究空白到可证伪假设**：开放式发散 → 创新性自检
> → 结构化成 H0/H1/证伪条件，产出 `planning/hypotheses.md`。
>
> 配套阅读：
> - 流程编排总纲：`assets/opencode/AGENTS.md`（Stage 7-8）
> - 上游：[论文调研](pipeline-1-deep-research.md)（提供 `planning/literature.md` + 研究空白）
> - 下游：[做实验](pipeline-3-experiment.md) · [写论文](pipeline-4-paper-writing.md)
>
> 路径基准：`baidu/acg-fm/famou-scientist/famou_scientist/`。行号会漂移，**按符号名定位更稳**。

---

## 0. 一句话定位

主题已定、研究空白已识别后，agent 走**发散 → 筛新意 → 结构化**三步：
`scientific-brainstorming`（产候选方向）→ `novelty-gate`（机制级筛新意）→ `hypothesis-formulation`
（写成 If-then-because 可证伪假设）。写 `planning/hypotheses.md` 前没 load `hypothesis-formulation`
会被 **skill 加载门** hook 强制警告。最终展示假设、问用户倾向哪个（关键停顿点）。

```
planning/literature.md（研究空白）
  │ load scientific-brainstorming → 五阶段对话产候选方向 → planning/ideas.md（草稿）
  │ load novelty-gate → 五条判据筛新意（机制级差异 / 不重复 / 达 MPU）
  │   └─ 结合 planning/venue 校准：新颖度/量级够不够该 venue 接收门槛、选题在不在范围
  │ load hypothesis-formulation → 3-5 个可证伪假设（H0 + H1 + 证伪条件）
  ▼
planning/hypotheses.md  ← skill 加载门 hook 守护
  │ 展示 + 问用户倾向哪个  ← 关键停顿点
```

---

## 1. 在 AGENTS.md 里的流程位置

文件：`assets/opencode/AGENTS.md`，Stage 7-8（约 130-136 行）。

| 子步骤 | Stage | 做什么 |
|---|---|---|
| ① 综合 | 7 | 把文献聚类成主题，**明确指出研究空白在哪** |
| ② 假设 | 8 | **先 load `hypothesis-formulation`（skill 门会查）**，生成 3-5 个可证伪假设（含 H0、证伪条件） |
| ③ 创新性自检 | 8 | load `novelty-gate` 筛新意；**结合 `planning/venue` 校准**够不够该 venue 门槛、对不对口 |
| 产出 | — | 写 `planning/hypotheses.md`，**必须展示，问用户倾向哪个** ← 关键停顿点 |

发散阶段（开放式产方向）在正式写假设前，对应 `scientific-brainstorming`（AGENTS.md 能力地图第 46 行登记）。

---

## 2. 方法论 Skill

skill 目录根：`assets/opencode/skill/experiment/`。

### 2.1 scientific-brainstorming — 开放式发散
`scientific-brainstorming/SKILL.md`
- **触发**：主题已定但无具体假设时（"first idea"阶段）；发散后**必须过 novelty-gate 收敛**
- **五阶段工作流**：①理解上下文 → ②发散探索 → ③连接模式 → ④批判评估 → ⑤综合与后续
- **发散技术**：跨域类比（Cross-Domain Analogies）· 假设反演（Assumption Reversal）· 尺度变换（Scale Shifting）· 约束增删（Constraint Removal/Addition）· 跨学科融合 · 技术推测
- **关键原则**：对话式协作（科学家说 50%+ 的话）、好奇心驱动、跨学科意识、结构化但灵活
- **纪律**：别把原始脑暴点直接当假设——必须过 novelty-gate + hypothesis-formulation
- 产出暂存 `planning/ideas.md`（候选方向草稿）

### 2.2 hypothesis-formulation — 结构化成可证伪假设
`hypothesis-formulation/SKILL.md`
- **触发**：Stage 8，候选方向已生成，需系统化
- **框架**：从观察/模式开始 → 检查文献已有机制 → 识别已知/未知 → 写成 **"If…then…because"** → 定义证伪条件
- **每个假设必含**：
  - **H0（零假设）**：无效应/无差异
  - **H1（备选）**：If [自变量操纵] then [预测结果] because [机制]
  - **证伪条件**：什么结果会推翻 H1
  - **预测方向与量级**：定向差异 + 预期效应大小
- **竞争假设**：≥2-3 个可竞争解释，各有独特预测、实验能区分
- **防 HARKing**：必须对照最初预测，不许事后改宽松；**量级也算**——方向对但远小于声称 = 部分支持而非成立

### 2.3 novelty-gate — 创新性自检
`novelty-gate/SKILL.md`
- **何时触发**：①初始假设（Stage 8）筛新意 ②失败后提新方向（REFINE/PIVOT）前必检
- **五条判据（全过才算新意）**：
  1. **机制级差异**：真正不同的原理，非超参/规模/数据集小修小补
  2. **不与历史重复**：本 run 已试过/否掉的不重复（对照 `experiment/reflection.md`）
  3. **相对文献有新意**：不复述已有工作（对照 `planning/literature.md`）
  4. **针对失败根因**：新方向回应归因，而非无脑换参数
  5. **达 MPU（最小贡献单元）**：即便成功也值得做/写
- **判定三态**：✅ NOVEL ENOUGH · 🟡 INCREMENTAL（深挖或诚实告知）· 🔴 REPETITIVE（放弃回找真空白）
- **诚实出口（最关键）**：深挖后只剩增量时，**不硬凑"创新方向"包装给用户**，应如实给选项
  （大改 / 停在这里也有价值 / 你来定），别用一串增量提案耗尽用户耐心

### 2.4 research-decision — 后期判据反向约束初始筛选
`research-decision/SKILL.md`（Stage 15 才正式判 PROCEED/REFINE/PIVOT，但其判据约束这里的创新性筛选）
- **PROCEED 硬门槛**：≥2 baseline + 自己方法都有结果 · 主指标定义明确 · 每条件 ≥3 种子 · 种子数值不雷同 · 分析自评 ≥4/10
- **REFINE vs PIVOT 分界**：假设还活着吗？REFINE=证据不足补实验；PIVOT=数据明确反对换假设

### 2.5 scientific-critical-thinking — 文献证据分级
`scientific-critical-thinking/SKILL.md`（详见[调研文档](pipeline-1-deep-research.md) §2.6）
- 在本阶段用途：用 GRADE/Cochrane ROB 评判已有工作质量，甄别哪些扎实、哪些有缺陷，
  直接影响"研究空白识别"的准确性。

---

## 3. 强制 Hook：skill 加载门

文件：`assets/opencode/plugins/guardrails.ts`（约 388 行）。在 `tool.execute.after` 事件触发。

### 3.1 跟踪机制（L124-157）
- 每次调内置 `skill` 工具，把参数追加到**会话级 blob**（`loadedSkills: Map<sessionID, blob>`）
- 检查时用 `blob.includes(skillName)` 判定——稳健，不依赖 skill arg 结构

### 3.2 文件型 gate（L97-103，本阶段相关那条）
```ts
{ re: /planning\/hypotheses\.md$/, skill: "hypothesis-formulation", action: "写 hypotheses.md（构建假设）" }
```
- 触发（L298-318）：当 `write`/`edit` 写入 `planning/hypotheses.md` 且 blob 未含 `hypothesis-formulation`
  → 用 `wrapSkillGateWarning()`（L112-120）包警告，原始返回照常透出（不阻断，强提醒）
- 同一文件多条只提示一个（break）

### 3.3 警告文本（L112-120）
```
⚠️ 【skill 加载门 - 强制护栏】
你正在「写 hypotheses.md（构建假设）」，但本会话未检测到 load 过 `hypothesis-formulation` skill。
请先 load `hypothesis-formulation` 拿到 ARC 沉淀的方法论，再按它的 checklist 重做这一步。
```

> 其他文件型 gate（design.md→experimental-design、experiment.py→code-plan-review、paper.md/.tex→scientific-writing）
> 和工具型 gate 见对应阶段文档。

---

## 4. 产出文件

### 4.1 planning/ideas.md（中间草稿，发散后、筛新意前）
```markdown
# 候选研究方向（脑暴产物）
## Idea 1: [方向标题]
- 来源：[跨域类比/假设反演/…]
- 概述：[想法核心]
- 潜在新意：[为什么可能有新意]
- 初步可行性：[粗略难度/资源]
## Idea 2: …
```

### 4.2 planning/hypotheses.md（Stage 8 正式产物，hook 守护）
```markdown
# 研究假设（可证伪）
## 背景
[来自 planning/literature.md 的哪个研究空白]

## H1（主假设）
- H0：[无效应表述]
- H1：If [自变量 A 变化], then [预期结果 B], because [机制 M]
- 证伪条件：[什么观察会推翻 H1]
- 预测方向与量级：↑ 准确率，预期 Δ≈8-12%
- 依据 / 相对文献新意：[机制级创新，对照已有工作]

## H2（备选假设） …

## 创新性自检（novelty-gate 结论）
- 机制级差异：✅ … / 不与历史重复：✅ … / 达 MPU：✅ …
- 结论：NOVEL ENOUGH → 推荐 H1

## 用户选择
[展示后记录用户倾向的假设编号]
```

---

## 5. Venue 对创新性判断的影响

venue 在**开场就问**并写入 `planning/venue`（详见 AGENTS.md「交互节奏」venue 段，约 227-241 行）。
它在本阶段的作用（AGENTS.md L134-135）：

| 决策 | 影响 |
|---|---|
| 想法/选题 | 这个想法**够不够发、在不在该 venue 接收范围**；不够或不对口 → 建议深挖到位或换更匹配 venue |
| 校准逻辑 | load novelty-gate 时**结合 `planning/venue`**：判断新颖度/贡献量级够不够该 venue 门槛、选题在不在领域范围 |

- **默认按领域、不默认 AI 顶会**：用户选「还没定，等后续看」时，按**问题所属领域**的顶级标准
  （化学顶刊、物理顶会、生医顶刊……AI 方向才用 CCF-A），Stage 16 起草前再确认一次。
- 落地：`planning/venue` 一行（如 `venue: NeurIPS` 或 `venue: TBD (领域默认: 顶级AI会议)`），
  供下游文献调研、创新性判断、润色、导出全读得到。

---

## 6. 流程时序与关键停顿点

```
Stage 7  文献综合 → 研究空白识别
Stage 7-8  load scientific-brainstorming → 五阶段对话 → planning/ideas.md（草稿）
           逐个候选过 novelty-gate（结合 venue 校准）
Stage 8  load hypothesis-formulation [skill 加载门守护]
           → 3-5 个可证伪假设（H0+H1+证伪条件）
           → write planning/hypotheses.md
           → 展示假设 + 问用户选主假设  ← 关键停顿点
           → 记录用户选择
[Stage 9+ 进入实验设计 → 见做实验文档]
```

**防错链**：skill 加载门前置 load → novelty-gate 筛创新（含诚实出口）→ hypothesis-formulation 规范化
→ 后期 research-reflection（Stage 14）对照最初假设，矛盾则 PIVOT。

---

## 7. 关键文件 / 行号速查

| 文件 | 行号 | 内容 |
|---|---|---|
| `AGENTS.md` | 130-136 | 假设生成流程 + 停顿点 |
| `AGENTS.md` | 227-241 | venue 开场问 + 领域默认 + 创新性校准 |
| `skill/experiment/scientific-brainstorming/SKILL.md` | 全文 | 五阶段发散工作流 |
| `skill/experiment/hypothesis-formulation/SKILL.md` | 全文 | If-then-because + H0 + 证伪条件 |
| `skill/experiment/novelty-gate/SKILL.md` | 全文 | 五条判据 + 诚实出口 |
| `skill/experiment/research-decision/SKILL.md` | 全文 | PROCEED/REFINE/PIVOT 判据 |
| `plugins/guardrails.ts` | 97-120 | skill 加载门配置 + 警告包装 |
| `plugins/guardrails.ts` | 298-318 | 文件型/工具型 gate 检查逻辑 |
