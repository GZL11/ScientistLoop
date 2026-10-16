# 百度伐谋（famou-scientist）前端界面 PRD

> **用途**：完整描述当前 demo 已落地的界面结构、交互与功能
> **参考实现**：`PRDdraft/demo/static/index.html` + `PRDdraft/demo/server.py`
> **Owner**: 刘丹宇
> **Date**: 2026-06-30
> **端口**: 5080

---

## 1. 整体布局

三栏式布局，从左到右依次为：**侧边栏 → 主聊天区 → 右侧面板**。

```
┌─────────┬──┬──────────────────────┬──┬──────────────┐
│ Sidebar │G │    Chat Column       │R │ Right Panel  │
│ 240px   │u │    flex:1            │e │ 520px        │
│         │t │                      │s │              │
│         │t │  ┌────────────────┐  │i │  文献 │ 实验台│
│ Logo    │e │  │  Chat Messages │  │z │              │
│ Nav     │r │  │                │  │e │  Source Cards│
│ 知识库   │  │  │                │  │  │  Bench Cards│
│ 最近     │  │  └────────────────┘  │  │              │
│         │  │  ┌────────────────┐  │  │              │
│ User    │  │  │  Input + Tools │  │  │              │
└─────────┴──┴──────────────────────┴──┴──────────────┘
```

### 色彩系统

| 变量                           | 值          | 用途           |
| ------------------------------ | ----------- | -------------- |
| `--primary`                  | `#0d7c66` | 主色·墨绿     |
| `--primary-light`            | `#ecfdf5` | 浅底高亮       |
| `--primary-border`           | `#a7f3d0` | 主色边框       |
| `--gray-50` ~ `--gray-900` | 标准灰阶    | 文字/背景/边框 |
| `--green`                    | `#10b981` | 完成状态       |
| `--orange`                   | `#f59e0b` | 警告/运行中    |

---

## 2. 侧边栏（Sidebar）

宽度 240px，支持拖拽折叠至 56px（二态 snap，阈值 160px）。

### 2.1 结构（从上到下）

| 区域             | 内容                                         | 展开态      | 折叠态       |
| ---------------- | -------------------------------------------- | ----------- | ------------ |
| **Logo**   | 绿色 SVG logo + "百度伐谋"                   | logo + 文字 | 仅 logo 居中 |
| **导航**   | "新任务"（edit icon）、"资产"（folder icon） | icon + 文字 | 仅 icon      |
| **知识库** | 标题 + ＋号 + 项目列表                       | 完整        | 隐藏         |
| **最近**   | 会话历史列表                                 | 完整        | 隐藏         |
| **用户**   | 头像(D) + "Danyella" + Demo 标签             | 完整        | 仅头像       |

### 2.2 导航项

- **新任务**：`onclick="newConversation()"` — 清空聊天、重置右侧面板，创建空白会话
- **资产**：`onclick="window.open('/static/knowledge_base.html','_blank')"` — 新窗口打开资产管理页

### 2.3 知识库项目列表

- 每个项目显示：文件夹 icon + 项目名 + 文件数量
- 点击项目 → 中间区域切换为**项目详情视图**（见 §5）
- ＋号按钮 → 弹出新建知识库 Modal（输入名称）
- 当前打开的项目高亮（`.project-item.active`，绿色底）

### 2.4 会话历史

- 每条：状态圆点（蓝色运行中/橙色已完成/灰色空） + 标题（省略溢出） + hover 显示 `···` 菜单
- `···` 菜单含："重命名"、"删除"（红色）
- 活跃会话绿色高亮

### 2.5 折叠手柄

侧边栏右侧 4px 宽的 `.sidebar-gutter`，拖拽折叠/展开：

- 鼠标拖过 160px 阈值 → snap 折叠
- 鼠标拖回 → snap 展开

---

## 3. 顶栏（Topbar）

高度 52px，水平居中显示当前标题 + 右侧 `⋯` 操作按钮。

- 默认标题：空
- 打开会话后：会话标题（如 "RNA-Seq 差异表达分析"）
- 打开知识库项目后：项目名称

---

## 4. 聊天区（Chat Column）

### 4.1 欢迎页

首次进入或新建对话时显示，居中布局：

- 标题 "百度伐谋"
- 副标题 "描述你的需求，我来帮你完成。"
- 3 个示例按钮（点击即发送）：
  - "帮我复现这篇GNN风阻预测论文的方法，用DrivAer数据集验证"
  - "调研强化学习在润滑油配方优化中的最新进展，给我一份综述"
  - "PEM电解槽仿真数据的故障诊断方法对比，需要文献支撑"

### 4.2 消息类型

| 类型       | 样式                     | 说明                           |
| ---------- | ------------------------ | ------------------------------ |
| 用户消息   | 右对齐，绿色浅底圆角气泡 | `max-width: 80%`             |
| Agent 文本 | 左对齐，无背景           | 支持完整 Markdown 渲染         |
| Plan 卡片  | 白底卡片，含步骤列表     | 可编辑步骤、开始/取消按钮      |
| 工具调用   | 折叠卡片，灰底           | 显示工具名+count，点击展开详情 |
| 文件产物   | 带图标的横条卡片         | 点击在右侧实验台预览           |
| 思考过程   | 折叠区域，灰色小字       | `▸ 思考中...` 可展开        |
| 跟进问题   | 一列按钮                 | Agent 生成的推荐问题           |
| 图片       | 缩略图网格               | 点击可下载                     |

### 4.3 Plan 卡片（研究计划）

- **结构**：标题 + 意图 badge（deep_research/auto_research）+ 步骤列表 + 操作按钮
- **步骤编辑**：每个步骤可 contenteditable 编辑
- **状态**：
  - 初始：显示"开始研究"+"取消"按钮
  - 运行中：步骤逐个标记 running（spinner）→ done（✓），底部进度条 + 停止按钮
  - 完成：卡片降低透明度，显示"已完成"

### 4.4 输入区

#### 输入框

- 白底圆角框，focus 时绿色边框 + 阴影
- placeholder: "描述你的科研问题，例如：调研岩爆预测领域的主流ML方法"
- Enter 发送，Shift+Enter 换行（当前为 input，非 textarea）

#### 文件上传

- 支持拖放上传（`.chat-input-area.dragover` 绿色虚线框）
- 已选文件显示为 chip 条（icon + 名称 + 大小 + ✕ 移除）

#### 工具栏（input-toolbar）

输入框下方的按钮行，从左到右：

| 按钮               | 图标                   | 行为                                  |
| ------------------ | ---------------------- | ------------------------------------- |
| **上传文件** | ＋号 24px              | 触发 file input                       |
| **深度研究** | 放大镜 + "深度研究"    | 切换 Deep Research 模式（高亮时激活） |
| **技能**     | 网格 + "技能"          | 弹出技能列表弹窗                      |
| **图像生成** | 图片 icon + "图像生成" | 独立按钮                              |
| **设计实验** | 烧杯 icon + "设计实验" | 独立按钮                              |
| **写论文**   | 笔 icon + "写论文"     | 独立按钮                              |

#### 技能弹窗（Skills Popover）

从"技能"按钮上方弹出，包含 5 个 skill：

| Skill                      | 图标     |
| -------------------------- | -------- |
| famou-artifact-generator   | 应用布局 |
| famou-data-analysis        | 钱包     |
| famou-experiment-manager   | 烧杯     |
| famou-result-visualization | 柱状图   |
| famou-ppt-generator        | 显示器   |

点击 skill → 在输入框插入 `@skill-name` 文本。

---

## 5. 知识库项目详情视图

点击侧边栏知识库项目后，聊天区和右侧面板隐藏，中间区域切换为项目详情。

### 5.1 结构

```
┌──────────────────────────────┐
│ ← 返回  📁 项目名称          │  ← header (gap:6px)
├──────────────────────────────┤
│ 📄 文件1.csv              ✕ │  ← 文件列表
│ 📊 heatmap.png             ✕ │
│ 📖 DESeq2: differential... ✕ │  ← 文献条目（带作者/状态）
│   Love MI, Huber W...       │
│ ...                          │
├──────────────────────────────┤
│ [基于此知识库开始新对话...] ↑ │  ← chat 输入框
└──────────────────────────────┘
```

### 5.2 文件列表

每个条目包含：

- **图标**：根据文件类型/扩展名自动匹配（图片/CSV/Python/HTML/MD/JSON/文献/默认）
- **文件名**
- **文献元数据**（仅 literature 类型）：作者、期刊、精读/浏览状态 badge
- **✕ 删除按钮**：始终可见（非 hover 显示），点击需 `confirm()` 确认
- 点击文件 → 右侧面板弹出，显示实验台预览（KB bench mode）

### 5.3 文件类型

| type           | 来源                     | 图标      | 在 KB 中的展示                       |
| -------------- | ------------------------ | --------- | ------------------------------------ |
| 实验台文件     | 从实验台"添加到知识库"   | 按扩展名  | 文件名                               |
| `literature` | 从文献面板"添加到知识库" | 书本 icon | 标题 + 作者 + 期刊 + 精读/浏览 badge |

### 5.4 Chat 输入框

底部固定区域，输入后：

1. 关闭项目详情视图
2. 新建对话
3. topbar 显示 "项目名 · 新对话"
4. 自动发送输入的消息

### 5.5 KB Bench Mode

从项目详情点击文件时，右侧面板进入 KB 专属模式：

- "文献" tab 隐藏，只显示"实验台" tab
- 实验台数量改为 KB 文件数
- 网格只显示该 KB 项目的文件卡片（非全量 bench 文件）
- 文献类型卡片：绿色渐变背景，显示作者/期刊/状态
- 返回时退出 KB mode，恢复正常实验台

### 5.6 预置数据

初始化时自动为已有知识库项目注入 3 篇 mock 文献：

- DESeq2 (Love MI et al., Genome Biology 2014) — 精读
- Moderated estimation of fold change (Love MI et al., bioRxiv 2014) — 精读
- RNA-Seq workflow (Law CW et al., F1000Research 2016) — 浏览

---

## 6. 右侧面板（Right Panel）

宽度 520px，左侧有 4px 拖拽手柄（`resize-handle`）。两个 Tab：**文献** | **实验台**。

### 6.1 文献 Tab

#### 摘要行

"文献列表 · N 篇文献" + 片段统计 badge

#### 文献源卡片（Source Card）

每篇论文一张卡片：

- **编号圆点**：绿色底圆形，序号
- **标题**：论文名，加粗
- **精读/浏览 badge**：精读=绿色底，浏览=灰色底
- **作者 · 期刊**：灰色小字
- **添加到知识库按钮**：文件夹 icon，点击弹出 KB 选择 dropdown
- **摘要片段**：折叠展示，点击展开

#### 预置数据

初始 RNA-Seq 会话自动填充 5 篇 mock 论文（DESeq2、edgeR、limma 等），含摘要片段。

### 6.2 实验台 Tab（Bench）

#### 文件网格

2 列网格布局，每张卡片：

```
┌──────────────────────┐
│ icon  文件名   [操作] │  ← head
├──────────────────────┤
│                      │  ← body（预览内容）
│   图片/表格/代码...   │
└──────────────────────┘
```

**5 种卡片类型**：

| 类型      | body 内容                        | 特殊样式            |
| --------- | -------------------------------- | ------------------- |
| 图片      | `<img>` 缩略图                 | —                  |
| CSV 表格  | `<table>` 数据预览             | —                  |
| Quiz 翻卡 | 🧬 + "Active Recall · 翻卡学习" | 紫色渐变底 + 紫边框 |
| 交互/Wiki | 📊 + "交互解读" 或 Wiki 样式     | 橙色渐变底          |
| 代码      | 代码预览                         | 紫色边框            |

**卡片操作（hover 显示）**：

1. 📁+ 添加到知识库 → dropdown 选择
2. ⬇ 下载
3. ↗ 展开预览

**文件名重命名**：hover 卡片时文件名变为 contenteditable，虚线下划线，编辑后鼠标移出自动保存。同步更新 KB 项目中同名文件。

#### 预览模式

点击卡片 → 网格隐藏，显示预览面板：

- 返回按钮 + 文件名 + 最大化按钮
- 内容区：图片/表格/iframe（Quiz/Wiki/交互）/代码块
- 最大化 → 全屏浮层预览

#### Mock 数据

3 组 bench 会话，通过 `switchDemoSession()` 切换：

- **rnaseq**：10 个文件（CSV、图片、Quiz、交互、Wiki、代码）
- **rockburst**：5 个文件
- **paradigms**：5 个文件

---

## 7. Deep Research 流程

### 7.1 触发

1. 点击工具栏"深度研究"按钮（高亮激活）
2. 输入问题并发送
3. Agent 返回 Plan 卡片

### 7.2 Plan 卡片

显示在聊天区，包含：

- 标题 + `deep_research` badge
- N 个可编辑步骤（LLM 返回多少步就渲染多少）
- 操作按钮：编辑 / 取消 / 开始

### 7.3 研究执行

点击"开始研究"后：

**右侧面板**：

- 切换到"文献" Tab（隐藏"轨迹" Tab）
- 进度条 + 运行时间

**聊天区**：

- Plan 卡片步骤逐个 running → done，底部状态文字 + 进度条 + 暂停按钮
- 展示工具调用过程（tool_call / tool_result）
- 思考过程（可折叠）
- 最终输出 Markdown 报告

**文献面板**：

- 逐篇添加论文卡片
- 自动统计片段和文献数

**实验台**：

- 生成产物卡片（references.bib、精读笔记、综述报告等）

### 7.4 Mock Agent 后端

`server.py` 提供纯 mock 模式：

- `/api/agent/status` → `{"status":"online","mode":"mock"}`
- `/api/agent/sessions` POST → 返回 `mock_` 前缀 session_id
- `/api/agent/sessions/<sid>/send` POST → SSE 流：4 步 tool_call/tool_result（search_literature → read_paper → analyze_data → write_report）+ qianfan LLM 生成报告文本

---

## 8. 知识库系统

### 8.1 数据存储

`localStorage` 键 `famou_projects`，JSON 数组：

```json
[{
  "id": 1719000000000,
  "name": "RNA-Seq 差异表达",
  "created": "2026-06-29T...",
  "files": [
    { "name": "normalized_counts.csv", "type": "csv", "added": "..." },
    { "name": "DESeq2: differential...", "type": "literature", "authors": "Love MI...", "venue": "Genome Biology, 2014", "status": "精读", "added": "..." }
  ]
}]
```

### 8.2 添加文件到知识库

**从实验台**：卡片 hover → 📁+ 按钮 → KB dropdown → 选择项目

**从文献面板**：文献卡片作者行 → 📁 按钮 → KB dropdown → 选择项目

Dropdown 结构：

- 标题 "添加到知识库"
- 已有项目列表
- 分隔线
- "+ 新建知识库"

### 8.3 新建知识库

Modal 弹窗：

- 标题 "新建知识库"
- 说明文字
- 名称输入框
- 取消/创建按钮

---

## 9. 交互细节

### 9.1 研究执行中的时间线

右侧文献面板在 Deep Research 运行时展示详细时间线：

- **阶段分组**：每个 phase 一个折叠区域
- **时间线 item**：彩色圆点 + 连接线 + 操作描述 + 时间
- 圆点颜色：检索(蓝)/阅读(绿)/推理(黄)/编码(绿)/验证(红)/执行(青)
- 活跃 item：圆点呼吸动画 + 连接线流动动画
- 详情卡片：点击展开，活跃时彩虹边框 shimmer 动画

### 9.2 状态栏

研究运行中，聊天区显示 mini 状态条：

- 绿色呼吸圆点 + 当前阶段名 + 描述

### 9.3 引用链接

报告正文中的引用标记 `[1]` `[2]` 可点击：

- 右侧文献面板滚动到对应论文
- 对应卡片高亮闪烁

### 9.4 跟进问题

研究完成后，Agent 在报告下方推荐 3 个跟进问题按钮，点击自动发送。

---

## 10. 技术栈

| 组件 | 技术                                     |
| ---- | ---------------------------------------- |
| 前端 | 单文件 HTML（CSS + HTML + JS，~3800 行） |
| 后端 | Flask（Python），`server.py`           |
| 端口 | 5080                                     |
| LLM  | 千帆 API（OpenAI 兼容接口）             |
| 存储 | localStorage（会话、知识库项目）         |
| SSE  | Mock agent 流式输出                      |

---

## 附录 A：页面级状态变量

| 变量                    | 类型         | 说明                                            |
| ----------------------- | ------------ | ----------------------------------------------- |
| `sessions`            | Array        | 所有会话列表                                    |
| `currentSessionKey`   | String       | 当前会话 key                                    |
| `_activeProject`      | Number\|null | 当前打开的 KB 项目索引                          |
| `_kbBenchMode`        | Boolean      | 右侧面板是否处于 KB 专属模式                    |
| `projects`            | Array        | localStorage 中的知识库项目数据                 |
| `sourcesData`         | Array        | 当前会话的文献列表                              |
| `currentBenchSession` | String       | 当前 bench 数据集（rnaseq/rockburst/paradigms） |
| `isDeepResearch`      | Boolean      | 是否处于 Deep Research 模式                     |
| `pendingPlan`         | Object\|null | 待确认的研究计划                                |

## 附录 B：关键 JS 函数清单

| 函数                               | 说明                            |
| ---------------------------------- | ------------------------------- |
| `newConversation()`              | 新建空白会话                    |
| `sendMessage()`                  | 发送用户消息                    |
| `triggerDeepResearch()`          | 切换 Deep Research 模式         |
| `confirmPlan()`                  | 确认并执行研究计划              |
| `addSource()`                    | 添加文献到右侧面板              |
| `addTraceStep()`                 | 添加时间线步骤                  |
| `addArtifact()`                  | 添加产物到实验台                |
| `renderBenchCards()`             | 渲染实验台文件网格              |
| `openProject(idx)`               | 打开知识库项目详情              |
| `closeProject()`                 | 关闭项目详情回到聊天            |
| `renderProjectFiles(idx)`        | 渲染项目文件列表                |
| `startProjectChat()`             | 从知识库发起新对话              |
| `openKBFile(name)`               | 点击 KB 文件打开右侧预览        |
| `enterKBBenchMode(project)`      | 进入 KB 专属实验台模式          |
| `exitKBBenchMode()`              | 退出 KB 专属模式                |
| `renderKBBenchGrid(project)`     | 渲染 KB 专属文件网格            |
| `addFileToKB(fileIdx, projIdx)`  | 从实验台添加文件到 KB           |
| `addSourceToKB(srcIdx, projIdx)` | 从文献面板添加论文到 KB         |
| `showAddToKB(e, idx)`            | 显示 KB 选择 dropdown（实验台） |
| `showAddSourceToKB(e, srcIdx)`   | 显示 KB 选择 dropdown（文献）   |
| `renameBenchFile(idx, newName)`  | 重命名实验台文件（同步 KB）     |
| `removeFromKB(projIdx, fileIdx)` | 从 KB 移除文件（需确认）        |
| `switchTab(tab)`                 | 切换右侧面板 Tab                |
| `switchDemoSession(key)`         | 切换 bench 数据集               |
| `fileTypeIcon(name, type)`       | 根据文件名/类型返回 SVG icon    |
