# 阶段四 · 写论文技术文档

> famou-scientist 四阶段技术文档之四。本篇讲**从可信数字到可投稿的论文**：IMRAD 起草 → 出图（数据图 +
> 架构图）→ 同行评审 → 质量门 → 导出 LaTeX + 编译核验 + 引用核验，产出 `deliverables/` 全套成品。
>
> 配套阅读：
> - 流程编排总纲：`assets/opencode/AGENTS.md`（Stage 16-23）
> - 上游：[做实验](pipeline-3-experiment.md)（提供 `experiment/results.json`，论文所有数字的唯一来源）
> - 其余阶段：[论文调研](pipeline-1-deep-research.md) · [提出 idea](pipeline-2-ideation.md)
>
> 路径基准：`baidu/acg-fm/famou-scientist/famou_scientist/`。行号会漂移，**按符号名定位更稳**。

---

## 0. 一句话定位

写论文阶段的核心是**有据可查 + 可投稿**：论文每个数字必须来自 `results.json`（数字核验门强制），
每条引用必须核验过（引用核验门），图必须过出版规范体检（图版核验门），LaTeX 必须本地真编过（编译核验门）。
四道确定性 hook + 多个 skill（写作/出图/审稿/质量门/合规）共同把关。

```
experiment/results.json（可信数字）
  │ Stage 16  复核 venue → load latex-fmt（章节骨架/页数/引用风格/禁包）
  │ Stage 17  load scientific-writing → 写 deliverables/paper.md（IMRAD）
  │           load scientific-visualization → 出图（视觉反馈闭环）：
  │             数据图 arc_render_figure（matplotlib 从 results.json 取真值）→ read 真看 → 改
  │             架构图 arc_generate_schematic（gpt-image-2）→ read 对照方法段查幻觉模块 → 改
  │           ↑ 写 paper.md/.tex 触发【论文数字核验门】；图 FAIL 触发【图版核验门】
  │ Stage 18  load peer-review → 独立 reviewer 子 agent 模拟顶会评审 → reviews.md
  │           + scholar-evaluation 分维度打分 + citation-faithfulness 查承重引用支撑性
  │ Stage 19-20  按评审修订 → load quality-gate 打分卡 + 反造假交叉核对 + failure-mode-audit 复查 7 模式
  │ Stage 22  导出 paper.tex + references.bib → arc_fetch_latex_template 取官方 .cls →
  │           arc_latex_check 本地真编（【编译核验门】FAIL 拦）→ paper.pdf
  │ Stage 23  arc_verify_paper 核验每条引用存在性（【引用核验门】拦假引用）
  │           + citation-faithfulness 查支撑性 → citations.md
  ▼ deliverables/{paper.md, paper.tex, references.bib, reviews.md, citations.md, figures/, paper.pdf}
```

---

## 1. 在 AGENTS.md 里的流程位置

文件：`assets/opencode/AGENTS.md`，Stage 16-23（约 175-194 行）。

| 步骤 | Stage | 做什么 | skill / tool |
|---|---|---|---|
| 复核 venue + 提纲 | 16 | 读 `planning/venue` 按模板组织（B/C 起草前再确认一次） | latex-fmt |
| 起草 + 出图 | 17 | 写 paper.md（IMRAD）；数据图 + 方法/架构图都该有 | scientific-writing / scientific-visualization + arc_render_figure / arc_generate_schematic |
| 同行评审 | 18 | 独立 reviewer 子 agent 模拟顶会评审 | peer-review + scholar-evaluation + failure-mode-audit（Mode 4/7）+ citation-faithfulness |
| 修订 + 质量自检 | 19-20 | 按评审改；质量门打分 + 反造假交叉核对 | quality-gate + failure-mode-audit（全 7 模式） |
| 核验引用 | 23 | 每条引用验存在性 + 承重引用验支撑性 | arc_verify_citation / arc_verify_paper / arc_fetch_source + citation-faithfulness |
| 导出 | 22 | paper.tex + references.bib + 取官方模板 + 本地真编 | latex-fmt + arc_fetch_latex_template + arc_latex_check |

---

## 2. 方法论 Skill

### 2.1 scientific-writing — IMRAD 学术写作
`skill/writing/scientific-writing/SKILL.md`
- **IMRAD 结构**：Abstract → Introduction → Methods → Results → Discussion
- 段落级：单段一意、开篇论题句、结尾过渡、**避免 bullet points**（正文用散文）
- 引用：一级源 > 综述、按 venue 风格一致、每个陈述需引用、自引克制
- 报告规范：CONSORT（随机试验）/ STROBE（观察）/ PRISMA（综述）/ STARD（诊断）
- 修订清单：图表顺序、引用列表核对、摘要真实性、Methods 可复现、朗读校对

### 2.2 scientific-visualization — 出版级图 + 视觉反馈闭环
`skill/writing/scientific-visualization/SKILL.md`
- **核心工作流**：渲染 → **用 `read` 真看 PNG** → 按 rubric 自评 → 改代码 → 重渲（≤3 轮）
- **数据图**：数据务必从 `results.json` 取真值（防编图）；`arc_render_figure(code, out_path, kind="data", journal, results_path)`
  - rubric：数据正确性 / 信息清晰 / 标注完整（轴标签+单位、图例、误差棒 SEM/SD/95%CI）/ **配色无障碍**（Okabe-Ito/viridis，**绝不 jet/rainbow/hsv**）/ 美观规范
  - 栏宽：single 3.3-3.5in、double 6.5-7.1in；≥300 DPI；字号 ≥6pt(WARN)、≥5pt(FAIL)；统计数据用点图/箱线图 + 误差棒 + 显著性括号
- **方法/架构概览图（默认应产出一张）**：只用于 schematic，**数据图绝不用生图模型**（会编数字）
  - 路线 A（首选）：先读方法段写详尽英文提示词 → `arc_generate_schematic(prompt, out_path, size=1536x1024)`（gpt-image-2）→
    **read 真看 + 对照方法段逐模块/逐连线核对幻觉结构**（生图会自信画错，绝不盲信）→ 改提示词重出（≤3 轮）
  - 路线 B（备选）：TikZ / matplotlib patches（矢量），同样走视觉反馈闭环
- 图数据溯源：绘图代码从 results.json 读数、禁硬编码（lint advisory 提示但不硬拦）

### 2.3 latex-fmt — 15+ venue 模板与投稿合规
`skill/writing/latex-fmt/SKILL.md` + `references/venue-guide.md`
- 7 个 Phase：①定源版本+目标 venue ②`\documentclass` 替换 + 禁/必包 ③章节重组 ④页限核对 ⑤引用风格转换 ⑥匿名化（double-blind）⑦投稿前检查清单
- **venue 约束举例**（venue-guide.md）：
  | venue | documentclass | 页限 | 禁包 | 章节特点 |
  |---|---|---|---|---|
  | NeurIPS | neurips_2025 | 9（refs/附录除外） | fullpage/geometry/setspace | + Broader Impact + Checklist |
  | ICML | icml2025 | 8 | fullpage/geometry | — |
  | CVPR | — | 8（refs 不计） | geometry/setspace | — |
  | ACL/EMNLP | `[review]{acl}` | — | fullpage | + Limitations + Ethics |
  | ICLR | — | 无 | — | — |
  | IEEE | `[conference]{IEEEtran}` | — | — | — |
- 缺强制段（Broader Impact/Limitations）只**标记让用户补，绝不替写编造**

### 2.4 peer-review — 顶会审稿模拟
`skill/experiment/peer-review/SKILL.md`
- **优先起独立 reviewer 子 agent**（task 工具，fresh context，只给论文+清单），避免自审确认偏误
- 三视角：方法专家（新颖性/技术扎实）/ 领域专家（扣题/vs SOTA/贡献）/ 统计专家（实验充分/统计有效）
- **8 点强制清单**：①主题对齐 ②**声称-证据对齐**（每句都有 Results 支撑）③统计有效（CI/误差棒/n>1）④完整性 ⑤可复现 ⑥写作质量（散文无 bullet）⑦**图表**（≥2 张，零图=desk reject，有无方法概览图）⑧引用分布
- 同时 load failure-mode-audit 盯 Mode 4/7；承重引用过 citation-faithfulness；产出 `deliverables/reviews.md`

### 2.5 quality-gate — go/no-go 质量门 + 反造假
`skill/experiment/quality-gate/SKILL.md`
- 8 维评分（同 peer-review），LLM 打分 1-10、卡阈值（config 的 quality_threshold）；< 阈值打回 required_actions
- **🔴 反造假交叉核对（最硬纪律）**：论文 Results 每个数字与 `results.json` **逐一比对（容差 1%）**；
  实验失败却报数字 = 造假严扣；对不上 = 编造要删/改。与数字核验门 hook 形成**两道防线**

### 2.6 scholar-evaluation — 分维度量化打分
`skill/experiment/scholar-evaluation/SKILL.md`
- ScholarEval rubric 8 维（问题表述/文献/方法/数据/分析/结果/写作/引用）× 5 级打分
- 接入：Stage 18 补 peer-review 的定量分、Stage 20 质量门一并落 reviews.md；脚本 `scripts/calculate_scores.py` 纯计算

### 2.7 citation-faithfulness — 引用支撑性
`skill/experiment/citation-faithfulness/SKILL.md`（详见[调研文档](pipeline-1-deep-research.md) §2.5）
- 写作阶段对承重引用用 `arc_fetch_source` 抓摘要判 SUPPORTED/UNSUPPORTED/AMBIGUOUS → 落 citations.md

---

## 3. 真执行 Tool

定义文件：`assets/opencode/tool/arc.ts`。

### 3.1 arc_render_figure — 数据图渲染 + 体检（arc.ts L492-544）
- 入参：`code`（matplotlib 代码）、`out_path`、`kind="data"|"schematic"`、`journal="single"|"double"`、`results_path`
- 执行绘图 → 存 ≥300 DPI（矢量另存 PNG 供 read）→ 确定性 lint 体检 → 返回 `{rendered, image_path, vector_path, checks[], severity}`
- 后端 `scripts/figure_lint.py::render_and_lint()`（L112-284）：`BAD_CMAPS`（L44）jet/rainbow → FAIL；
  字号 <5pt FAIL/<6pt WARN；栏宽 band 检查；缺轴标签 WARN（kind=data）；`_hardcoded_data_suspected()`（L103）检测硬编码
- severity：ERROR（渲染失败）> FAIL（jet/rainbow、字号<5pt、缺轴标签）> WARN > PASS

### 3.2 arc_generate_schematic — 架构图生成（arc.ts L546-593）
- 入参：`prompt`（详尽英文描述）、`out_path`、`size="1536x1024"`
- 调生图模型（gpt-image-2），后端 `scripts/image_gen.py::generate()`（L72-155）
- **网关凭证（环境变量，绝不硬编码）**：优先 `FAMOU_IMAGE_API_BASE`+`FAMOU_IMAGE_API_KEY`，
  否则复用 `ANTHROPIC_BASE_URL`+`ANTHROPIC_AUTH_TOKEN`；缺凭证直接报错不静默；
  可选 `FAMOU_IMAGE_MODEL`（默认 gpt-image-2）、`FAMOU_IMAGE_SIZE`；代理 `ALL_PROXY`/`HTTPS_PROXY` urllib 自动识别
- POST `/v1/images/generations`（OpenAI 协议），优先 `data[0].b64_json` 否则下载 `data[0].url`

### 3.3 arc_fetch_latex_template — 取官方 .cls/.sty/.bst（arc.ts L466-490）
- 入参：`venue`、`dest_dir`（须在工作目录内）、`year=0`（自动探最新可用年）
- 后端 `scripts/latex_template.py::fetch()`（L221-279）：`resolve(venue, year)` → kind=zip 下载解压（只取 .cls/.sty/.bst/.clo/.bbx/.cbx）/ files 逐个下 / manual 无源给降级建议
- **白名单 host 防 SSRF**（L29-34：mirrors.ctan.org/media.neurips.cc/media.icml.cc/raw.githubusercontent.com）；
  带年份源自动探最新年（往回探 5 年）；`_safe_dest` 校验 dest 在 cwd 内、解压防 zip-slip
- 取不到 → 退回 article 类导出并如实标注

### 3.4 arc_latex_check — 本地真编 + 投稿前体检（arc.ts L595-630）
- 入参：`tex_path`、`venue`（页限核对用）
- 后端 `scripts/latex_check.py::check()`（L250-331）：PATH 前加 ~/.TinyTeX/bin → latexmk -pdf（fallback 2 遍 pdflatex）→ 解析 .log
- `parse_log()`（L94-149）抓：**未定义 ref/cite**（正文渲成 ??，FAIL）/ **缺图/文件**（FAIL）/ **编译报错** `!`（FAIL）/ **Overfull \hbox** 溢出（WARN）/ **超 venue 页数**（`VENUE_PAGE_LIMITS` L67-82，WARN）
- **"编出 PDF / 退出码 0 ≠ 没问题"**；severity FAIL 由编译核验门拦

### 3.5 arc_verify_paper — 批量引用存在性（arc.ts L403-433）
- 入参：`bib_text`；后端 `verify.py::verify_citations()` 三层（arXiv ID → CrossRef DOI → 标题搜 S2+arXiv）
- 返回 `{total, verified, suspicious, hallucinated, skipped}`；分类阈值见[调研文档](pipeline-1-deep-research.md) §4.3

### 3.6 arc_verify_citation / arc_fetch_source
- `arc_verify_citation`（L359-398）单条真伪；`arc_fetch_source`（L438-464）抓摘要——详见[调研文档](pipeline-1-deep-research.md) §3

> ⚠️ 改 `arc.ts`/plugins/scripts 需**重启 opencode**（port 4097）才生效。

---

## 4. 强制 Hook（四道确定性核验门）

文件：`assets/opencode/plugins/guardrails.ts`，均在 `tool.execute.after` 触发。

### 4.1 论文数字核验门（L244-278）
- 触发：`write`/`edit` 作用于 `deliverables/paper.md` 或任意 `.tex`
- `resolveResultsJson(paperPath)`（L328-344）：从论文路径反推 `<run>/experiment/results.json`
- 执行：`python scripts/verify_paper_cli.py --paper <fp> --results <resultsJson>`（L257-260）
  - 后端 `verify_paper_cli.py`（main L71-114）：`build_registry()` 把 results.json 数字注册白名单 →
    从论文 Results/表格抽数字 → 容差 1% 比对 → `{severity, strict_violations, unverified[]}`
- 判据：`severity==="REJECT"` → 前缀 `⚠️ 【论文数字核验门】` 列出无依据数字
- 与 quality-gate 的反造假交叉核对形成**两道防线**（hook 确定性强制 + skill 主动逐条）

### 4.2 图版核验门（L211-225）
- 触发：`arc_render_figure` 返回；判据 `rendered && severity==="FAIL"`
- 列出 FAIL 项（如 jet/rainbow colormap、字号不可读）+ "不得用于论文，修复重渲染"

### 4.3 编译核验门（L227-242）
- 触发：`arc_latex_check` 返回；判据 `severity==="FAIL"` 且 fails 非空
- 列出 FAIL 项（悬空 ref/cite、缺图、编译报错），必须改净再复编才导出

### 4.4 引用核验门（L194-209）
- 触发：`arc_verify_paper` 返回；判据 `hallucinated>0 || suspicious>0`
- 前缀 `⚠️ 【引用核验门】` + "${hallucinated} 条疑似编造、${suspicious} 条可疑"

### 4.5 配套：skill 加载门 + 孤儿论文门
- skill 加载门（L97-103）：`deliverables/paper.md`→`scientific-writing`、`*.tex`→`scientific-writing`；
  工具型 `arc_verify_paper`→`citation-faithfulness`、`arc_latex_check`→`latex-fmt`、`arc_render_figure`→`scientific-visualization`
- **孤儿论文门**（L280-296，`hasOrphanPaper()` L363-375）：写文件时若 deliverables/ 已有 paper.md/*.tex
  但 `experiment/results.json` 不存在 → 告警（防把别的研究遗留当本 run 成果）；会话级去重

---

## 5. 产出文件

```
research-runs/<topic>/deliverables/
├── paper.md            # IMRAD markdown（Stage 17 起草，scientific-writing）
├── paper.tex           # LaTeX（Stage 22 导出，按 venue 模板）
├── references.bib      # BibTeX（引用风格随 venue：natbib/IEEEtran/Nature numbered）
├── reviews.md          # 同行评审意见 + scholar-evaluation 分数（Stage 18，独立 reviewer 子 agent）
├── citations.md        # 引用核验两层报告：①存在性(arc_verify_paper) ②支撑性(SUPPORTED/UNSUPPORTED/AMBIGUOUS)
├── figures/
│   ├── fig1.pdf / .png # 数据图（矢量入论文 + PNG 供 read）
│   └── arch.png        # 方法/架构概览图（gpt-image-2 或 TikZ）
├── <venue>.cls/.sty/.bst  # 官方模板（arc_fetch_latex_template 落盘）
└── paper.pdf           # 最终编译产物（arc_latex_check 通过后）
```

| 文件 | 谁生成 | 何时 |
|---|---|---|
| paper.md | agent 手写（scientific-writing） | Stage 17 |
| paper.tex / references.bib | agent 手写（latex-fmt） | Stage 22 |
| reviews.md | 独立 reviewer 子 agent | Stage 18 |
| citations.md | arc_verify_paper + arc_fetch_source | Stage 23 |
| figures/*.pdf | arc_render_figure / arc_generate_schematic | Stage 17 |
| <venue>.cls 等 | arc_fetch_latex_template 下载 | Stage 22 |
| paper.pdf | latexmk（arc_latex_check） | Stage 22 |

---

## 6. 写论文全流程

```
Stage 16  复核 planning/venue → load latex-fmt（章节骨架/页数/引用风格/禁包）
Stage 17  load scientific-writing → 写 paper.md（IMRAD，数字来自 results.json）
          load scientific-visualization → 出图视觉反馈闭环：
            数据图：results.json 取真值 → arc_render_figure → read 真看 → rubric 批判 → 重渲（≤3）
            架构图：读方法段写提示词 → arc_generate_schematic → read 对照方法段查幻觉模块 → 重出（≤3）
          ↑【论文数字核验门】写 paper.md/.tex 时自动比对 results.json；【图版核验门】图 FAIL 拦
Stage 18  load peer-review → 独立 reviewer 子 agent（3 视角 + 8 点清单）→ reviews.md
          + scholar-evaluation 定量分 + failure-mode-audit（Mode 4/7）+ citation-faithfulness 查承重引用
Stage 19  按 reviews.md 修订 paper.md/.tex
Stage 20  load quality-gate 打分卡 + 反造假交叉核对（每个数字 vs results.json 容差 1%）
          + failure-mode-audit 复查全 7 模式（曾 SUSPECTED 须 CLEAR 或已 override）→ 不达标先改
Stage 23  arc_verify_paper 验每条引用存在性【引用核验门】+ citation-faithfulness 验支撑性 → citations.md
Stage 22  导出 paper.tex + references.bib → arc_fetch_latex_template 取官方 .cls →
          arc_latex_check 本地真编【编译核验门 FAIL 拦】→ 改净复编 → paper.pdf
          load latex-fmt Phase 7 投稿前合规检查（禁包/强制段，缺的只标记不替写）
```

---

## 7. 关键文件 / 行号速查

| 文件 | 行号 | 内容 |
|---|---|---|
| `AGENTS.md` | 175-194 | Stage 16-23 写论文流程 |
| `tool/arc.ts` | 492-544 / 546-593 | render_figure / generate_schematic |
| `tool/arc.ts` | 466-490 / 595-630 | fetch_latex_template / latex_check |
| `tool/arc.ts` | 403-433 | verify_paper |
| `scripts/figure_lint.py` | 112-284 / 44 | render_and_lint / BAD_CMAPS |
| `scripts/image_gen.py` | 46-69 / 72-155 | _resolve_gateway / generate |
| `scripts/latex_template.py` | 221-279 / 29-34 | fetch / 白名单 host |
| `scripts/latex_check.py` | 250-331 / 94-149 / 67-82 | check / parse_log / VENUE_PAGE_LIMITS |
| `scripts/verify_paper_cli.py` | 71-114 | 数字核验门后端 |
| `plugins/guardrails.ts` | 244-278 / 211-225 / 227-242 / 194-209 | 数字门 / 图版门 / 编译门 / 引用门 |
| `plugins/guardrails.ts` | 280-296 / 363-375 | 孤儿论文门 |
| `skill/writing/scientific-writing/SKILL.md` | 全文 | IMRAD 写作 |
| `skill/writing/scientific-visualization/SKILL.md` | 全文 | 视觉反馈闭环 |
| `skill/writing/latex-fmt/SKILL.md` + `references/venue-guide.md` | 全文 | venue 模板与合规 |
| `skill/experiment/peer-review/SKILL.md` | 全文 | 审稿 8 点清单 |
| `skill/experiment/quality-gate/SKILL.md` | 全文 | 质量门 + 反造假 |
