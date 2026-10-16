# 科研智能体 PRD — MoonLog（知识编译日志）

> **Owner**: 刘丹宇
> **Date**: 2026-06-30
> **Status**: Draft
> **参考实现**: `PRDdraft/demo/static/wiki_demo.html`

---

## 1. 功能定位

MoonLog 是**夜间定时编译**的知识日志。系统每天在设定时间自动扫描当日所有研究活动（对话、产物、知识库变更），编译为一份结构化的知识库文档，带版本号和变更记录。

**不是**：

- 不是用户主动触发的功能（区别于 Skill）
- 不是实时文档（区别于聊天中的 MD 报告）
- 不是知识库本身（区别于 KB 项目管理）

**是**：

- 一份定期快照：把碎片化的研究过程沉淀为可检索、可跳转的结构化知识
- 一本自动更新的实验室笔记

---

## 2. 编译流程

### 2.1 触发时机

- 每日定时（默认凌晨 2:00，可配置）
- 条件：当日存在新对话 / 新产物 / KB 变更时才触发，无活动则跳过

### 2.2 编译输入

| 输入源         | 内容                | 说明                                     |
| -------------- | ------------------- | ---------------------------------------- |
| 对话历史       | 当日新增/更新的会话 | 包括用户消息、Agent 回复、工具调用、产物 |
| 实验台产物     | 新增的 bench files  | CSV、图片、代码、交互 HTML 等            |
| 知识库变更     | 新增/删除的 KB 文件 | 含文献 literature 条目                   |
| 上一版 MoonLog | 前一天的编译结果    | 用于增量更新而非全量重建                 |

### 2.3 编译输出

一份完整的 HTML 文档（独立页面，可 iframe 嵌入主界面）。

---

## 3. 文档结构（三层架构）

### L1：固定分类框架

Sidebar 的 5 大分类**不由 LLM 生成**，前端硬编码：

| 分类                             | 图标       | 收录内容                                                |
| -------------------------------- | ---------- | ------------------------------------------------------- |
| **Overview**               | 网格       | 全局摘要 + 探索路径图谱 + 各主题导航表                  |
| **Research Object**        | 人物       | 研究对象页：描述"研究什么"，如分子、数据集、生物系统    |
| **Method**                 | 扳手       | 方法页：描述"怎么做"，如工作流、算法 pipeline、实验协议 |
| **Experiments & Analysis** | 剪贴板     | 实验页：描述"做了什么"，具体执行记录、参数、结果        |
| **Question & Decision**    | 三角感叹号 | 决策页：描述"遇到什么问题、怎么决定的"，含待解决问题    |
| **Log**                    | 时钟       | 编译日志：每次编译的变更记录                            |

### L2：LLM 生成条目

每个分类下的具体条目（标题、数量、层级）由 LLM 在编译时生成。

**LLM 输出 JSON Schema**：

```json
{
  "date": "2026-06-23",
  "compile_source": "3 轮新对话",
  "compile_time_s": 12,
  "overview": {
    "title": "Molecular Property Calculation and Wavefunction Analysis Knowledge Base",
    "summary": "This knowledge base encompasses...",
    "topic_tables": [
      {
        "topic": "Boiling Point Prediction and Branching Effect",
        "summary": "Starting from pentane isomers...",
        "links": {
          "research_object": "obj-pentane",
          "method": "method-mpa",
          "experiment": "exp-pentane",
          "question": "qd-bias"
        },
        "ref_count": 4
      }
    ]
  },
  "explore_map": {
    "root": "KNOWLEDGE",
    "branches": [
      {
        "label": "Boiling Point Prediction",
        "meta": "pentane isomers",
        "status": "done",
        "children": [
          { "label": "MPA Model Verified", "status": "done" }
        ]
      },
      {
        "label": "RNA-Seq Differential Expression",
        "meta": "DESeq2 pipeline",
        "status": "done",
        "children": [
          { "label": "Batch Effect Correction", "status": "active" }
        ],
        "abandoned": [
          { "label": "Rank Truncation", "status": "abandoned" }
        ]
      }
    ]
  },
  "research_objects": [
    {
      "id": "obj-benzyl",
      "title": "Benzyl Alcohol Electronic Structure",
      "content_html": "<p>Benzyl alcohol (SMILES: <code>OCC1=CC=CC=C1</code>)...</p>",
      "links": ["method-cube", "exp-benzyl"],
      "ref_count": 2
    }
  ],
  "methods": [
    {
      "id": "method-cube",
      "title": "Cube File Generation Workflow",
      "content_html": "<p>This workflow converts...</p><div class='flowchart'>...</div>",
      "links": ["obj-benzyl", "exp-benzyl"],
      "ref_count": 2
    }
  ],
  "experiments": [
    {
      "id": "exp-benzyl",
      "title": "Benzyl Alcohol Cube File Generation Experiment",
      "content_html": "<p>This experiment takes benzyl alcohol...</p>",
      "links": ["method-cube"],
      "ref_count": 3
    }
  ],
  "questions_decisions": [
    {
      "id": "qd-batch",
      "title": "Batch Effect Correction in RNA-Seq Models",
      "content_html": "<p>The RNA-Seq dataset includes batch metadata...</p>",
      "status": "pending",
      "ref_count": 1
    }
  ],
  "changelog": [
    { "type": "added", "content": "RNA-Seq Analysis 研究对象页", "source": "Session #7" },
    { "type": "updated", "content": "Overview 增加 RNA-Seq 主题摘要", "source": "自动合并" },
    { "type": "abandoned", "content": "Rank Truncation 方法", "source": "Session #6 决策" }
  ]
}
```

### L3：全文内容

编译时 LLM 直接生成每个条目的 `content_html`（全文），写入 JSON。前端渲染时直接插入，无需二次调用 LLM。

**选择全文生成而非摘要+展开的理由**：

- MoonLog 是离线编译，不受实时延迟约束
- 用户打开后应该能直接阅读，不等 loading
- 内容是编译时刻的快照，不需要"最新"

---

## 4. 前端结构

### 4.1 整体布局

两栏式：Sidebar（260px）+ 主内容区（flex:1，max-width 720px 居中）。

```
┌──────────────────────────────────────────────┐
│ MoonLog  2026.06.23 ▾  自动编译·10h前   ✎ ⚙ × │  ← Topbar 44px
├──────────┬───────────────────────────────────┤
│ 搜索...   │                                   │
│          │  Molecular Property Calculation   │
│ Overview │  and Wavefunction Analysis KB     │
│          │                                   │
│ ▾Research │  ┌─ 探索路径 ──────────────────┐  │
│   Benzyl │  │ ● KNOWLEDGE                  │  │
│   Pentane│  │  ├─● Boiling Point [完成]    │  │
│   ...    │  │  ├─● Wavefunction  [完成]    │  │
│          │  │  ├─● Pine Nematode [完成]    │  │
│ ▾Method  │  │  └─● RNA-Seq      [完成]    │  │
│   Cube.. │  │       └─○ Batch Effect [进行中]│  │
│   ...    │  └───────────────────────────────┘  │
│          │                                   │
│ ▾Exper.. │  ## Boiling Point Prediction      │
│ ▾Q & D   │  Starting from pentane isomers... │
│ ▾Log     │  [Research Object] [Method] ...   │
│  06.23   │                                   │
│  06.22   │                                   │
└──────────┴───────────────────────────────────┘
```

### 4.2 Topbar

| 元素                 | 说明                                 |
| -------------------- | ------------------------------------ |
| **品牌名**     | "MoonLog"，accent 色（#e8590c）      |
| **版本选择器** | 日期 pill + 下拉列表，可切换历史版本 |
| **编译时间**   | "自动编译 · 10小时前"               |
| **操作按钮**   | ✎ 编辑 / ⚙ 设置 / × 关闭          |

### 4.3 Sidebar

- **搜索框**：全文搜索
- **Overview**：固定首项，类似首页
- **5 大分类**：可折叠 section，每个 section 下列出具体条目
- 条目文字截断（text-overflow: ellipsis）
- 活跃条目橙色高亮（accent-light 底色）

### 4.4 内容区

每个条目是一个独立页面（`page-screen`），包含：

- **← 返回按钮**：回到 Overview
- **标题**：h1
- **正文**：段落、列表、表格、代码块、链接
- **流程图**（Method 页）：纵向 flowchart 组件
- **交叉引用**：条目间互相链接（`<a onclick="showPage('xxx')">`）
- **引用计数 badge**：右浮动，显示被其他条目引用的次数

### 4.5 Overview 页

特殊页面，包含：

1. **全局标题 + 摘要**：一段话概括整个知识库
2. **探索路径图谱**：树形结构，显示所有研究主题及其状态
3. **主题导航表**：每个主题一张表，列出 Research Object / Method / Experiment / Q&D 的链接

### 4.6 探索路径图谱

树形可视化，节点状态：

| 状态   | 圆点样式           | 连接线样式     | 标签                         |
| ------ | ------------------ | -------------- | ---------------------------- |
| 完成   | 实心绿 #297a3a     | 实线绿 #86efac | 完成（绿 badge）             |
| 进行中 | 空心橙边框 #b45309 | 虚线黄 #fde68a | 进行中（黄 badge）           |
| 放弃   | 实心灰 #e5e7eb     | 虚线灰 #e5e7eb | 放弃（红 badge），标题删除线 |

### 4.7 编译日志页（Log）

按日期倒序排列，每个版本显示：

- 日期 + "最新" badge（仅最新版）
- 元信息："基于 N 轮新对话 · 编译耗时 Ns"
- 变更表格：

| 变更类型 | 颜色       | 符号        |
| -------- | ---------- | ----------- |
| 新增     | 绿 #297a3a | + 新增      |
| 更新     | 蓝 #0068d6 | ↑ 更新     |
| 标记放弃 | 橙 #e8590c | ✕ 标记放弃 |

每行含：变更内容（可点击跳转）+ 来源（Session # / 自动合并 / 用户操作）

---

## 5. 与主界面的集成

### 5.1 入口

MoonLog 在主界面以**实验台卡片**的形式出现：

- 卡片类型：`type: 'log'`
- 卡片名称：`MoonLog · {知识库名}`
- 卡片样式：橙色渐变背景（`#fff7ed → #fef3c7`），📊 图标
- 点击打开：iframe 嵌入 `/static/wiki_demo.html`

### 5.2 与对话的关系

- MoonLog 编译的来源是对话，但不在对话中生成
- 用户在对话中可以引用 MoonLog 内容（通过链接跳转）
- Agent 不会主动建议生成 MoonLog（因为是定时任务），但可以说："这些内容会在今晚的 MoonLog 编译中自动整理"

### 5.3 与知识库（KB）的关系

- MoonLog 是知识库的"视图层"——把 KB 中的文件、文献、对话产物组织成可读的文档
- KB 项目是存储层（localStorage），MoonLog 是展示层（HTML）
- 同一个 KB 项目可以有多个版本的 MoonLog（按日期）

---

## 6. 版本管理

| 属性     | 说明                                  |
| -------- | ------------------------------------- |
| 版本号   | 日期格式 YYYY.MM.DD                   |
| 存储     | 每个版本一份完整 JSON + 渲染后的 HTML |
| 切换     | Topbar 版本下拉列表，点击切换         |
| Diff     | 编译日志（Log section）记录每次变更   |
| 保留策略 | 保留最近 30 天（可配置）              |

---

## 7. 编译策略详细设计

### 7.1 增量编译

非全量重建，而是基于上一版 MoonLog 做增量更新：

1. **扫描新活动**：识别自上次编译以来的新对话、新产物、KB 变更
2. **分类归档**：LLM 判断每条新内容属于哪个分类（Research Object / Method / Experiment / Q&D）
3. **合并或新建**：如果已有相关条目则更新，否则新建条目
4. **更新 Overview**：重新生成全局摘要和探索路径
5. **写入 changelog**：记录本次编译的所有变更

### 7.2 LLM Prompt 要点

编译 prompt 需要：

- 提供 L1 分类框架定义（让 LLM 理解每个分类的含义）
- 提供上一版 MoonLog JSON（作为基线）
- 提供当日新增活动的原始内容
- 要求输出符合 §3 JSON Schema 的增量更新
- 约束：content_html 只使用 p/ul/ol/li/table/code/a/strong/em 标签，不引入自定义组件

### 7.3 错误处理

- JSON 解析失败 → 重试 1 次，仍失败则跳过本次编译，Log 中记录失败
- 部分条目内容为空 → 保留标题，content_html 显示"内容待编译"
- 编译超时（>60s）→ 截断未完成的条目，Log 中标记

---

## 附录 A：产物类型与触发规范

定义所有产物的触发条件、格式和前端承载方式。具体生成逻辑（prompt 设计等）由算法侧负责。

### A.1 产物格式分工原则

- **MD 文档**：线性阅读为主的内容（报告、论文段落、实验方案、分析结论）
- **HTML 交互**：需要操作/探索/翻转/切换的内容（可视化、Quiz、应用、PPT、MoonLog）
- **图片**：静态图（生成的示意图、图表截图）
- **数据文件**：CSV、JSON、代码文件

### A.2 各产物触发条件与格式

#### 用户主动触发（按钮/Skill）

| 触发入口                    | 用户动作                                | 产物格式                              | 在实验台中的卡片类型 |
| --------------------------- | --------------------------------------- | ------------------------------------- | -------------------- |
| 深度研究按钮                | 点击"深度研究" → 输入问题 → 确认 Plan | MD（报告）+ 文献卡片 + references.bib | normal               |
| @famou-data-analysis        | 在输入框 @提及                          | MD（分析结论）+ CSV/图片              | normal               |
| @famou-result-visualization | 在输入框 @提及                          | **HTML**（交互图表）            | interactive          |
| @famou-experiment-manager   | 在输入框 @提及                          | MD（实验记录）+ 代码/数据             | normal               |
| @famou-artifact-generator   | 在输入框 @提及                          | **HTML**（完整应用）            | interactive          |
| @famou-ppt-generator        | 在输入框 @提及                          | **HTML**（幻灯片）              | interactive          |
| 图像生成按钮                | 点击"图像生成"                          | **图片**                        | normal（图片）       |
| 设计实验按钮                | 点击"设计实验"                          | MD（实验方案表格）                    | normal               |
| 写论文按钮                  | 点击"写论文"                            | MD（论文段落）                        | normal               |

#### Agent 主动建议触发

Agent 在特定场景下**建议**（非自动）生成产物，用户确认后才执行。

| 触发场景                             | 建议的产物    | 格式           | 卡片类型    |
| ------------------------------------ | ------------- | -------------- | ----------- |
| 完成文献综述/调研（涉及 ≥3 篇文献） | Quiz 翻卡速学 | **HTML** | quiz        |
| 完成数据分析并输出了数值结果         | 交互式可视化  | **HTML** | interactive |
| 完成实验方案设计                     | 实验管理文档  | MD             | normal      |
| 完成较长报告/综述                    | 汇报 PPT      | **HTML** | interactive |

**约束**：

- 只建议不自动执行，等用户确认
- 每次回复最多建议 1 种产物

#### 系统自动触发

| 触发条件                         | 产物                 | 格式           | 卡片类型 |
| -------------------------------- | -------------------- | -------------- | -------- |
| 每日定时（凌晨，当日有新活动时） | MoonLog 知识编译日志 | **HTML** | wiki     |

---

## 附录 B：色彩系统

MoonLog 使用独立于主界面的色彩变量（accent 为橙色而非墨绿色）：

| 变量                  | 值          | 用途             |
| --------------------- | ----------- | ---------------- |
| `--accent`          | `#e8590c` | MoonLog 主色·橙 |
| `--accent-light`    | `#fff4f0` | 浅底高亮         |
| `--blue`            | `#0070f3` | 更新状态         |
| `--green`           | `#297a3a` | 完成状态         |
| `--fg`              | `#171717` | 正文             |
| `--fg2` ~ `--fg4` | 灰阶        | 次要文字         |
