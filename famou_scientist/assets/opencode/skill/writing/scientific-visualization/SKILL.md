---
name: scientific-visualization
description: Publication-quality scientific figures via a render→look→critique→fix visual-feedback loop. Statistical data plots use matplotlib from results.json (arc_render_figure); architecture/overview/concept schematics use an image model gpt-image-2 (arc_generate_schematic). Use when making any figure for a paper — never draw blind, never let the image model draw data plots.
metadata:
  category: writing
  trigger-keywords: "figure,plot,chart,visualization,matplotlib,seaborn,colorblind,publication,出图,图表,可视化,架构图,概览图,示意图,diagram,tikz,gpt-image,生图,architecture diagram,schematic,视觉反馈"
  applicable-stages: "14,17,18,20,22"
  priority: "2"
  version: "2.0"
  author: researchclaw
  references: "MatPlotAgent (arXiv 2402.11453), PlotGen (arXiv 2502.00988), PaperOrchestra (arXiv 2604.05018); checklist adapted from K-Dense-AI/claude-scientific-skills"
---

## 何时用这个 skill

任何要给论文/报告出图的时候 —— 分析阶段画结果图（Stage 14）、写作阶段配图（Stage 17）、
评审/质量门核对图（Stage 18/20）、导出定稿图（Stage 22）。

> **核心理念：绝不盲画。** 写完 matplotlib 代码不等于画好图。领域里被验证最有效的做法
> （MatPlotAgent / PlotGen）是一个闭环：**渲染 → 真看渲染结果 → 批判 → 改代码 → 重渲染**。
> famou 得天独厚——能用 `arc_render_figure` 真渲染、宿主又能 `read` 图——所以这个闭环必须走。

---

## 🔁 视觉反馈闭环（核心工作流，每张图都走）

```
写绘图代码(数据从 results.json 取真值)
   │
   ▼ arc_render_figure(code, out_path, kind, journal, results_path)
拿到 image_path(png) + lint 确定性体检
   │
   ▼ 用原生 read 工具【真看那张 png】 ← 不是看代码，是看图
按 rubric + lint 自评 → 有问题？
   │ 是                              │ 否
   ▼ 改代码 → 重渲染(≤3 轮)          ▼ 定稿：确保矢量 .pdf 进论文
```

**逐步：**

1. **写绘图代码**。数据**必须从 `experiment/results.json` 取真值**（见下「图数据溯源」），
   把 `results_path` 传给工具。savefig 目标放 `deliverables/figures/figN.pdf`（矢量）。
2. **调 `arc_render_figure`**：传 `code` / `out_path` / `kind`（data 或 schematic）/ `journal`
   （single 或 double）/ `results_path`。拿回 `image_path`（png）+ `checks`/`severity`/`advisories`。
3. **用 `read` 工具真看 `image_path` 那张 png**。这一步不可省 —— 你要像审稿人一样**看图本身**，
   不是看代码自我想象。
4. **按下面 rubric + lint 结果自评**。lint 已替你确定性查了硬规范（DPI/字号/colormap/画布/标签）；
   你补查代码查不出的部分：信息是否清晰、有无 overplotting、配色是否好看、message 是否一眼可读。
5. **有问题就改代码重渲染**，最多 3 轮。`severity=FAIL`（如 jet colormap、字号不可读）会被
   **图版核验门 hook 强制拦截**，必须改到不 FAIL。WARN/advisory 你权衡处理。
6. **定稿**：论文里用矢量图（.pdf/.svg），png 只用于你看图。

---

## 📋 评分 rubric（看图时逐条过）

看 png 时，对照这几维给自己挑刺（MatPlotBench 式维度）：

- **数据正确性**：画的就是 results.json 的真值吗？坐标范围/单位对吗？没有误导性截断坐标轴吗？
- **信息清晰**：一眼能看懂这张图在说什么吗？有没有 overplotting（点/线糊成一团）？
- **标注完整**：x/y 轴标签 + 单位、图例或直接标注、误差棒类型（在 caption 注明 SEM/SD/95%CI）。
- **配色无障碍**：色盲友好（不靠颜色单独区分；蓝-橙优于红-绿）；灰度打印仍可分辨。
- **美观/规范**：去 chartjunk（无多余网格/3D/背景）；去 top/right 边框；字号在最终印刷尺寸可读。

### 规范速查（出图前/改图时参照）

**画布尺寸**：single 栏 3.3–3.5in 宽；1.5 栏 4.5–5.5in；double / 整宽 6.5–7.1in。≥300 DPI，优先矢量。
**配色**：用 colorblind / Okabe-Ito / viridis / cividis；**绝不用 jet/rainbow/hsv**（感知不均、非色盲友好，会被图版核验门判 FAIL）；不靠颜色单独区分（配形状/线型/纹理）。
**多面板**：左上角粗体 (A)(B)(C)；同类数据共轴；`plt.subplots(constrained_layout=True)` 自动排版。
**统计标注**：小 n 用点图/箱线图（**别用柱状图**）；带误差棒；显著性括号 `* p<.05 ** p<.01 *** p<.001`。
**导出**：线条图存 PDF/SVG，照片存 TIFF/PNG；嵌入字体；轴标签带单位 `Time (s)`；caption 解释所有符号/缩写/面板。
> seaborn 不一定装了；缺则纯 matplotlib（`ax.spines[...].set_visible(False)` 去边框，手设 colorblind 调色板）。

---

## 🏗 概念图 / 架构示意图（不是数据图）

PaperOrchestra 把图分两类，统计数据图之外还有**概念/方法/架构示意图**（pipeline 流程、模型结构、
机制对比）。**这类图实践中最常被漏画**——很多论文只有数据对比图、没有一张"30 秒看懂方法"的
架构/概览图。**起草时应当主动产出一张方法/架构概览图**（放 Method 或 intro）。

> ⚠️ **铁律：此节只适用于 schematic（架构/概览/流程/概念示意，无真实数据）。**
> 统计**数据图（柱/线/散点/热图）绝不用生图模型**——必须走上面的 `arc_render_figure` +
> matplotlib 从 `results.json` 画。生图模型会把柱高/曲线"编"得像而错，等同造数据。

### 路线 A（首选）：生图模型出图 —— `arc_generate_schematic`

架构图/概览图用代码（TikZ/matplotlib）很难画好看；改由生图模型（gpt-image-2）出，布局/配色更省心。
**关键：你先读懂方法、把"画什么"想清楚写成提示词，模型只负责把它画出来。** 四步：

1. **通读方法**：读 `deliverables/paper.md` 的 Method 段 + `planning/design.md`，逐模块弄清
   每个模块在做什么、模块间的数据怎么流。
2. **撰写详尽英文提示词**（照下面模板填）：明确列出每个模块、模块间箭头/数据流、整体布局、
   配色、风格、留白。
3. **调 `arc_generate_schematic(prompt, out_path, size)`**：`out_path` 建议
   `research-runs/<主题>/deliverables/figures/arch.png`；`size` 横版架构图用 `1536x1024`。
4. **视觉反馈闭环（必做）**：用 `read` 工具**真看那张 png**，**对照方法段逐模块/逐连线核对**——
   模块齐不齐？连线对不对？**有没有画出论文里根本不存在的模块、或编错的结构？** 有出入就
   改提示词重出（≤3 轮）。**生图模型会"自信地画错"，绝不盲信，必须核对幻觉结构。**

**提示词模板（照填，英文给模型效果更好）：**
```
A clean, flat schematic diagram for an academic paper, <horizontal left-to-right | top-to-bottom> layout,
muted professional color palette (soft blues/grays), no photorealism, plenty of white space for labels.
Show these modules connected by arrows indicating data flow:
(1) <模块1：名字 + 一句话作用>
(2) <模块2：…>
(3) <模块3：… → 输出>
Use simple rounded rectangles for modules, thin arrows for flow, clear readable labels. Minimalist,
publication-ready figure. <可选：highlight <某模块> as the core contribution.>
```
> 网关：`arc_generate_schematic` 复用 opencode 启动配置的通用网关（无需额外配）；缺凭证会如实报错，
> 这时退回路线 B。

### 路线 B（备选）：代码画 —— 无网关 / 要矢量随论文编译时

- **TikZ（写进 `paper.tex`）**：纯文本、随论文一起编译、矢量、可版本管理。在 `deliverables/paper.tex`
  里写 `\begin{tikzpicture}...\end{tikzpicture}`。适合简单框图/流程图，且要严格矢量可复现时。
- **matplotlib patches**：用 `Rectangle`/`FancyArrowPatch`/`annotate`（或 graphviz，若装了）画，
  再 `arc_render_figure(code, kind="schematic", ...)` 渲染（`kind="schematic"` 放宽体检：只查
  画布/DPI/导出，不查坐标轴标签/colormap）。

路线 B 同样走视觉反馈闭环：渲染 → `read` 看 → 框是否对齐、箭头是否清楚、文字是否可读 → 改。

---

## 🔢 图数据溯源（防"造图"）

图里画的曲线/柱子若是编的，和编造论文数字一样严重。纪律：

- 绘图代码**从 `experiment/results.json` 读数**，不要硬编码数值数组；把 `results_path` 传给
  `arc_render_figure`。
- lint 会做 **advisory 提示**（检出大段硬编码数值且未引用 results.json 时），但**这是软提示、
  不硬拦**——图里曲线 vs results.json 无法像正文数字那样确定性比对（呼应 `citation-faithfulness`
  的 advisory 定位）。所以纪律靠你自觉：数据进图前先确认来自真实实验。

---

## 配合 / 关系

- **`scientific-writing`**：图要和正文/LaTeX 拼版一致；caption 写全。
- **`statistical-reporting`**：图上的误差棒/显著性标注要和正文统计口径一致（SEM/SD/CI 别混）。
- **`peer-review` / `quality-gate`**：两者都查「至少 2 张图，零图 = desk reject」「图表质量」——
  出图阶段就按本 skill 把图做到位，省得评审被打回。
- **图版核验门 hook**：`arc_render_figure` 出 `severity=FAIL` 会被强制拦截（jet colormap、字号不可读等），
  必须改到不 FAIL 才能用。

> 一句话：别盲画。渲染出来、**亲眼看那张图**、像审稿人一样挑刺、改到好看又规范——这才叫画好了一张科研图。
