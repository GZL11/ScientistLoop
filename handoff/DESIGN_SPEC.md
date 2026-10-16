# AutoResearch Demo 设计规范

> 基于 2026-06-23 ~ 06-24 迭代记录提取，对应 `static/index.html` 单文件实现。

---

## 1. 整体布局

三栏 Flex 布局，`100vh` 全屏。

| 区域 | CSS class | 默认宽度 | 说明 |
|------|-----------|---------|------|
| 左侧栏 | `.sidebar` | 240px 固定 | `flex-shrink:0`，右边框 1px `--gray-200` |
| 主内容 | `.main` | flex:1 | 包含 topbar + 内容区 |
| 聊天列 | `.chat-col` | flex:1 | 背景 `--gray-50` |
| 拖拽手柄 | `.resize-handle` | 4px | 聊天列与右侧面板之间，hover 时变 `--primary-border` |
| 右侧面板 | `.right-panel` | **520px** | `flex-shrink:0`，左边框 1px |

**拖拽调整**：右侧面板可拖拽，范围 **320px ~ 1200px**。

**Topbar**：高度 52px，底边框 1px，居中文字，右侧 actions 绝对定位 `right:20px`。

**右侧面板 Tab**：2 个 tab —— **证据链(sources)** + **实验台(artifacts)**。证据链为默认激活 tab。

---

## 2. 色彩体系

主色从紫色(#4f46e5)切换为**墨绿/青绿色(#0d7c66)**，全面清除紫色残留。

### CSS 变量

```css
:root {
  --bg: #f7f8fa;
  --sidebar-bg: #fff;
  --chat-bg: #fff;
  --panel-bg: #fff;
  --primary: #0d7c66;          /* 主色 - 墨绿 */
  --primary-light: #ecfdf5;    /* 主色浅底 */
  --primary-border: #a7f3d0;   /* 主色边框 */
  --green: #10b981;            /* 成功/完成 */
  --green-light: #ecfdf5;
  --orange: #f59e0b;           /* 警告/思考 */
  --red: #ef4444;              /* 错误 */
  --gray-50: #f9fafb;
  --gray-100: #f3f4f6;
  --gray-200: #e5e7eb;         /* 边框 */
  --gray-300: #d1d5db;         /* 禁用 */
  --gray-400: #9ca3af;         /* 占位文字/提示 */
  --gray-500: #6b7280;         /* 次要文字 */
  --gray-600: #4b5563;         /* 正文 */
  --gray-700: #374151;         /* 强正文 */
  --gray-800: #1f2937;         /* 标题/深色强调 */
  --gray-900: #111827;         /* 最深文字/CTA 按钮底色 */
  --radius: 12px;
  --radius-sm: 8px;
}
```

### 语义色（时间轴圆点）

| 类型 | 颜色 |
|------|------|
| search | `#3b82f6` 蓝 |
| read | `var(--primary)` 墨绿 |
| think | `#f59e0b` 琥珀 |
| code | `#10b981` 绿 |
| eval | `#ef4444` 红 |
| run | `#06b6d4` 青 |

### 工具调用徽章色

| 类型 | 背景 | 文字 |
|------|------|------|
| memory | `#fef3c7` | `#92400e` |
| skill | `#dbeafe` | `#1e40af` |
| bash | `#d1fae5` | `#065f46` |
| read | `var(--primary-light)` | `var(--primary)` |

### 渐变

- 进度条：`linear-gradient(90deg, var(--primary), #34d399)`
- 活跃卡片闪光边框：同上渐变

---

## 3. 字体与排版

### 字体栈

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
```

代码字体：`'SF Mono', Consolas, monospace`（行内），`'SF Mono', 'Fira Code', monospace`（代码块）。

### 基础

- body: `14px`, `line-height: 1.6`
- `.msg-agent-text`: `line-height: 1.8`
- `.msg-user`: `line-height: 1.7`

### 各组件字号

| 组件 | 字号 | 字重 |
|------|------|------|
| 侧边栏 Logo | 16px | 700 |
| 侧边栏导航 | 14px | - |
| 会话项 | 13px | - |
| 分区标题 | 11px | 600, uppercase, letter-spacing 0.5px |
| Topbar | 14px | 500 |
| 聊天输入 | 14px | - |
| 输入提示 | 11px | - |
| 工具栏 | 12px | - |
| Plan Card 标题 | 16px | 700 |
| Plan 步骤 | 14px | - |
| Plan 意图徽章 | 9px | 600 |
| 工具调用头部 | 12px | - |
| 工具调用名称 | 11px | - |
| 工具调用 IO | 10px | - |
| 思考块头部/正文 | 11px | - |
| 思考流式 | 13px（流中）→ 11px（最终） | - |
| 时间轴圆点 | 7px | - |
| 时间轴动作 | 12px | 500 |
| 证据链标题 | 13px | 600 |
| 证据链序号 | 11px | 700 |
| 证据链摘要 | 12px | - |
| 产物卡片名 | 13px | 600 |
| 欢迎标题 | 24px | - |
| 弹窗标题 | 17px | 700 |
| 预览标题 | 15px | 700 |

### Markdown 渲染标题

| 级别 | 字号 | 字重 | 颜色 | 上下间距 |
|------|------|------|------|---------|
| H1 | 17px | 700 | `--gray-900` | 24px / 12px |
| H2 | 15px | 700 | `--gray-800` | 20px / 10px |
| H3 | 14px | 600 | `--gray-700` | 16px / 8px |

---

## 4. 组件规范

### 4.1 侧边栏

- 固定 240px，白底，flex column
- Logo：SVG 图标（绿色圆角矩形 + 菱形）+ "百度伐谋" 文字
- 导航项：图标 + 文字，padding `10px 12px`，`--radius-sm` 圆角
- 激活态：`--primary-light` 底，`--primary` 文字，weight 500
- 会话项：状态圆点(8px) + 截断标题 + hover 显示 "更多" 按钮
- 会话状态圆点：done=`#f97316` 橙、running=`#3b82f6` 蓝(脉冲动画)、empty=`--gray-300`
- 右键菜单：shadow `0 8px 24px rgba(0,0,0,.12)`，圆角 10px，`menuIn` 入场动画

### 4.2 聊天消息

- **用户消息**：`--primary-light` 底，`--primary-border` 边框，圆角 `12px 12px 4px 12px`，max-width 80%，右对齐
- **Agent 消息**：max-width 85%，左对齐，无显式背景
- 入场动画：`msgIn` — opacity 0→1，translateY 8px→0，0.3s ease

### 4.3 欢迎页

- 垂直居中，描述区 max-width 480px
- 标题："百度伐谋"，24px
- 描述："描述你的需求，我来帮你完成。"
- 示例按钮：白底，1px `--gray-200` 边框，hover 变 `--primary-light` 底 + `--primary-border` 边框

### 4.4 Plan Card（研究计划卡片）

- 白底，1px `--gray-200` 边框，12px 圆角，24px padding，阴影 `0 1px 3px rgba(0,0,0,.06)`
- 头部：标题(16px bold) + 操作按钮(编辑/取消/开始)
- 步骤：编号圆圈(24px，1.5px 边框)，文字 14px
- 步骤状态：pending(灰边) → running(旋转边框) → done(填充深色底+白色对勾)
- 进度条：3px 高，`--gray-200` 轨道，`--gray-800` 填充，transition 0.8s
- 停止按钮：24px 圆形，1px `--gray-300` 边框，内含 11px 方形停止符号
- 意图徽章：药丸形，9px 字号，"Deep Research" = `--primary-light` 底 / `--primary` 文字

### 4.5 思考块

- **流式中**：脉冲圆圈(12px，`--primary`，`areaPulse` 动画) + "深度思考中..." + 流式文字(13px `--gray-500`，max-height 60px overflow hidden)
- **完成后**：折叠块 "已完成深度思考 ▸"(11px `--gray-400`)，无 emoji 图标，点击展开/收起，内容 11px
- **空内容**：若思考文本 trim 后为空，整个块不创建

### 4.6 工具调用卡片

- `--gray-50` 底，1px `--gray-100` 边框，`--radius-sm` 圆角，margin 14px 0
- 头部：链接图标(SVG) + "N 次工具调用" 计数 + 展开箭头 "▸"
- 折叠内容：默认隐藏，点击展开。工具名徽章(按类型着色) + 输入预览(截断 60 字符)
- 连续工具调用**合并到同一张卡片**

### 4.7 文件产物卡片（聊天内联）

- Flex 行：图标(36px 方形，8px 圆角，`--primary-light` 底) + 文件信息(名称 13px bold + 状态 11px) + 箭头
- 写入中状态：opacity 0.6，"写入中..." `--orange`
- 完成后：opacity 1，"EXT . 点击查看"
- 点击在右侧面板产物 tab 打开

### 4.8 输入区域

参考 **agent.famou.com** 设计，三层结构：

1. **文件预览区** `file-preview-area`：Flex wrap，gap 6px。文件 chip：类型图标(28px) + 名称(max 180px 截断) + 大小 + 删除按钮
2. **输入框** `chat-input-box`：白底，1px `--gray-200` 边框，12px 圆角，10px 12px padding。Focus：`--primary-border` 边框 + `0 0 0 3px rgba(13,124,102,.1)` 光晕
3. **发送按钮**：32px 方形，8px 圆角，`--primary` 底，白色向上箭头。禁用态：`--gray-300`
4. **工具栏** `input-toolbar`：Flex 行，margin-top 6px。按钮 30px 高，`--gray-400` 色，hover `--gray-100` 底。包含：
   - 上传(+) 按钮
   - "深度研究" 文字按钮（切换模式，激活态 `--primary-light` 底）
   - "Skills" 文字按钮 + 弹出层

### 4.9 Skills 弹出层

- 绝对定位于工具栏按钮上方(bottom:100%, margin-bottom 8px)
- 白底，1px `--gray-200` 边框，10px 圆角，shadow `0 8px 24px rgba(0,0,0,.12)`
- `menuIn` 入场动画
- 标题：11px uppercase "技能"
- 5 个技能项：artifact-generator、data-analysis、experiment-manager、result-visualization、ppt-generator
- 点击插入 `/skill-name ` 到输入框

### 4.10 证据链（右侧面板）

- 来源卡片：1px `--gray-200` 边框，`--radius-sm`，14px padding，间距 10px
- 序号圆圈：22px，`--primary-light` 底，`--primary` 文字
- 状态徽章：药丸形 — "精读"=`--primary-light`/`--primary`，"扫描"=`--gray-100`/`--gray-500`
- 引用联动：正文中 `[N]` → 上标，`--primary` 色，点击滚动到对应来源卡并高亮(2s)
- 统计徽章："N 片段 . M 文献"，`--primary-light` 底

**文献自动检测**：工具名匹配 `search_literature`/`arc_search`/`arxiv`/`search+paper`/`search+liter` 时自动解析结果并加入证据链。前 3 篇标记 "精读"，其余 "扫描"。

### 4.11 产物/实验台（右侧面板）

- 产物卡片：flex 行，12px 14px padding，1px `--gray-200` 边框
- Hover：`--primary-border` 边框，`--gray-50` 底
- 预览模式：Markdown 渲染，含返回按钮 + 最大化按钮
- 最大化弹窗：80vw x 85vh，16px 圆角，shadow `0 20px 60px rgba(0,0,0,.3)`

### 4.12 弹窗/遮罩

- 遮罩：全屏 fixed，`rgba(0,0,0,.4)`（新建项目）/ `rgba(0,0,0,.5)`（预览）
- 新建弹窗：440px 宽，14px 圆角，28px 32px padding
- 主按钮：`--gray-900` 底（近黑），白文字。Hover：纯 `#000`
- 输入框 focus：`--primary` 边框 + `0 0 0 3px rgba(13,124,102,.1)` 光晕

### 4.13 滚动条

- 宽度 5px，轨道透明，滑块 `--gray-300`，3px 圆角

---

## 5. 动画与交互

### 动画定义

| 名称 | 时长 | 效果 |
|------|------|------|
| `pulse` | 1.5s infinite | opacity 1→0.4→1（会话状态圆点） |
| `areaPulse` | 2s cubic-bezier | scale 0.7/opacity 0.4 → scale 1/opacity 0.65（思考脉冲） |
| `blink` | 1s step-end | 50% 处 opacity 0（流式光标） |
| `spin` | 0.8s linear infinite | rotate(360deg)（加载旋转） |
| `phaseGlow` | 2s infinite | box-shadow 0→8px 主色渐隐（活跃阶段图标） |
| `msgIn` | 0.3s ease | opacity 0 + translateY(8px) → 1 + 0（消息入场） |
| `menuIn` | 0.15s ease | opacity 0 + translateY(-4px) → 1 + 0（下拉/弹出） |
| `planStatusFade` | 2s ease-in-out infinite | opacity 0.6→1→0.6（计划状态文字） |
| `activeDotPulse` | 2s ease-in-out infinite | scale(1)→(1.2)（活跃时间轴圆点） |
| `ringExpand` | 2s ease-out infinite | scale(0.8)/opacity 0.6 → scale(2)/opacity 0（扩散环） |
| `flowDown` | 1.5s linear infinite | top -100%→100%（流动连接线） |
| `shimmerBorder` | 2s linear infinite | background-position 0%→200%（闪光边框） |

### 过渡默认值

大部分交互元素使用 `transition: all .15s` 或 `all .12s`。

### 流式渲染策略

- **增量 DOM 追加**，非全量 innerHTML 替换
- 维护 `currentBlock` 引用，`onText` 直接追加 chunk
- `onToolCall` 时：结束当前块（如需折叠为思考块）→ 创建工具卡片 → 创建新文字块
- 两个渲染函数：`renderMd()`（聊天内联，去代码围栏、去 `---`）、`renderMdFull()`（预览，保留代码块/水平线）

### Deep Research 流程

1. 用户点击 "深度研究" 工具栏按钮（toggle 激活）
2. 输入主题 → `callSessionLLM` 调千帆生成 plan JSON
3. 渲染 Plan Card（编辑/取消/开始按钮）
4. 点击"开始" → `runAgentTask()` 发送 prompt 到 agent 后端
5. Agent 流式输出：思考 → 工具调用 → 文字 → 工具调用 → 文字 → 完成
6. 检测文献检索工具调用 → 解析论文数据 → 推送到证据链面板
7. 检测文件写入工具调用 → 插入内联文件产物卡片
8. 进度条每次 tool_result +8%，上限 90%

### 拖拽上传

整个 `chatInputArea` 为 drop zone，拖入时：`--primary-light` 底 + 2px dashed `--primary` 边框。

---

## 6. 图标系统

**Vercel 风格 SVG 单色图标**，stroke-based，使用 `currentColor`。

所有图标 16x16 viewBox，`stroke-width: 1.5`，`stroke-linecap: round`，`stroke-linejoin: round`。

13 个内置图标：`file`、`code`、`table`、`json`、`image`、`pdf`、`globe`、`report`、`book`、`edit`、`plus`、`folder`、`clip`。

`fileIcon(ext)` 函数按文件扩展名映射图标。

---

## 7. 后端 SSE 协议

### 模型

`qwen3-vl-235b-a22b-thinking`（千帆 OpenAI 兼容接口）

### SSE 事件类型

| type | payload | 说明 |
|------|---------|------|
| `thinking` | `{type:"thinking", content:"..."}` | qwen3 `reasoning_content` 字段 |
| `text` | `{type:"text", content:"..."}` | 正文增量 |
| `plan` | `{type:"plan", content:{...}}` | 检测到 JSON 计划块 |
| `tool_call` | `{type:"tool_call", tool:"name", tool_input:"..."}` | Agent 工具调用 |
| `tool_result` | `{type:"tool_result", content:"..."}` | 工具执行结果 |
| `info` | `{type:"info", content:"..."}` | 状态消息（过滤 session_id 前缀、reason= 前缀、[...] 系统标记） |
| `done` | `{type:"done"}` | 流结束 |
| `error` | `{type:"error", content:"..."}` | 错误 |

### 端口

| 服务 | 默认端口 |
|------|---------|
| Demo Flask | 5050 |
| WebAgent 后端 | 8765 |

---

## 8. 品牌

- 侧边栏 Logo + 欢迎页标题：**百度伐谋**
- Topbar：**AutoResearch**
- 完整品牌：**百度伐谋 . AutoResearch**
- Logo SVG：圆角矩形 `fill="#0d7c66"`，内含菱形 `#a7f3d0` + 白色
