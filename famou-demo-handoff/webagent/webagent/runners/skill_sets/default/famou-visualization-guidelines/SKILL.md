---
name: famou-visualization-guidelines
description: >
  famou 可视化规范指南。定义所有可视化 HTML 输出的统一色彩、字体、渲染策略和图表选型规则。
  famou 的能力边界涵盖：排程与调度（生产排程、插单重排、扰动响应）、预测与预警（需求预测、故障预警、延期风险）、
  资源优化（产能/库存/路径/装载多目标优化）、工艺优化（配方比例、多方案对比、参数评分）、方案解释（多方案对比、瓶颈归因）。
  以上任意场景需要输出可视化结果时，必须引用本 skill 的规范，包括 famou-builder 生成图表、可视化规格扩展、前端代码生成等。
  只要上下文出现"生成 HTML"、"可视化"、"图表"、"甘特"、"热力图"、"负载"、"地图"、"配送"、"预测"、"趋势"、"置信区间"、"配方"、"雷达图"、"工艺"等关键词，立即引用本 skill。
---

# famou 可视化规范

---

## 每次生成 HTML 的强制流程

> 不论任务大小，每次生成可视化 HTML **必须**按此顺序执行，缺少任一步骤均视为未完成：

```
① 写 data.json（数据 > 50 条 / 5 KB 时）
② 写 chart.html（模板，占位符 __DATA_PLACEHOLDER__）
③ 执行 Python 内联合并 → 生成自包含 HTML
④ python3 $SKILL_DIR/validate_html.py <html文件> --runtime
   → exit code 1：读修复建议 → 改 HTML → 回到④
   → exit code 0：才可交付给用户
```

> `$SKILL_DIR` = validate_html.py 所在目录（与 SKILL.md 同级）

---

## 色彩系统

| 用途          | 色值      | 使用场景                       |
| ------------- | --------- | ------------------------------ |
| 主色          | `#2563EB` | 普通任务、进行中状态、主要元素 |
| 强调色（VIP） | `#DC2626` | 优先级高的任务、警报、VIP 标签 |
| 成功色        | `#16A34A` | 已完成状态、达成目标           |
| 警告色        | `#D97706` | 延误风险、临界状态             |
| 背景色        | `#F8FAFC` | 页面背景                       |
| 卡片背景      | `#FFFFFF` | 内容卡片区域                   |
| 文字主色      | `#1E293B` | 主要文字、标题                 |
| 文字副色      | `#64748B` | 次要文字、标签、辅助信息       |
| 边框色        | `#E2E8F0` | 分割线、边框                   |

---

## 字体规范

```css
font-family:
  Inter,
  -apple-system,
  BlinkMacSystemFont,
  sans-serif;
```

| 层级        | 字号 | 字重 |
| ----------- | ---- | ---- |
| 标题 h1     | 18px | 600  |
| 副标题      | 13px | 400  |
| 正文        | 14px | 400  |
| 小字 / 标签 | 12px | 400  |

---

## 间距与形状

```css
padding: 16px;
border-radius: 8px; /* 普通圆角 */
border-radius: 12px; /* 卡片圆角 */
box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
```

---

## 渲染策略

| 数据条数  | 渲染方案               |
| --------- | ---------------------- |
| < 1000 条 | CSS / SVG 渲染         |
| ≥ 1000 条 | Canvas 渲染 + 虚拟滚动 |

---

## 支持的图表类型

各垂直场景的数据结构、布局、渲染要点和参考实现详见 `scenarios/` 目录，**遇到对应场景时必须加载对应文件**：

| 场景       | 关键词                                   | 文件                                                                         |
| ---------- | ---------------------------------------- | ---------------------------------------------------------------------------- |
| 排程与调度 | 甘特、排程、负载、热力图、插单、扰动     | [scenarios/01_gantt_scheduling.md](scenarios/01_gantt_scheduling.md)         |
| 物流配送   | 配送、路线、地图、车辆、装载             | [scenarios/02_logistics_map.md](scenarios/02_logistics_map.md)               |
| 预测与预警 | 预测、预警、趋势、置信区间、延期风险     | [scenarios/03_forecast_chart.md](scenarios/03_forecast_chart.md)             |
| 工艺优化   | 配方、工艺、雷达图、多方案对比、参数评分 | [scenarios/04_process_optimization.md](scenarios/04_process_optimization.md) |

---

## 输出要求

### HTML 基础规范

1. **纯 HTML 输出**：不包含 markdown 代码块标记
2. **自包含**：可直接在浏览器中打开，无需服务器
3. **CDN 来源**：外部库统一使用 **BootCDN**（`cdn.bootcdn.net`），禁止使用 `cdnjs.cloudflare.com`
4. **语言**：`<html lang="zh">`，`<meta charset="UTF-8">`
5. **禁止外部跳转链接** `[自动检测]`：不生成 `<a href="...">` 跳转外部 URL；如需展示 URL，用 `<span>` 或 `<code>` 纯文本
6. **大数据量可读性**：行数 > 20 时启用虚拟滚动或分页，行高 ≥ 28px、字号 ≥ 11px

### JS 安全规范

7. **括号与引号配对**：每个 `'` / `"` / `` ` `` / `{}` / `()` / `[]` 必须闭合；CSS 颜色值如 `'rgba(0,0,0,0.3)'` 极易漏掉闭合 `'`；对象字面量最后一个属性后不留尾逗号
8. **外部库加载检测**：使用 ECharts/D3 等库时，脚本第一行必须检测：
   ```js
   if (typeof echarts === "undefined") {
     document.body.innerHTML =
       '<div style="padding:40px;text-align:center">图表库加载失败，请刷新重试</div>';
     throw new Error("ECharts not loaded");
   }
   ```

> 其余 JS 安全问题（字面换行、Tooltip、判空等）由 `validate_html.py` 和 `--runtime` 自动兜底，无需预防性文档。

### Agent 交互规范

12. **Agent 回调接口**：所有可视化 HTML **必须包含** `sendToAgent` 函数，并在关键交互元素上绑定点击事件：

    ```js
    function sendToAgent(message, context) {
      window.parent.postMessage(
        { type: "famou-agent-query", message, context },
        "*",
      );
    }
    ```

    各场景具体的交互点见对应 `scenarios/` 文件。

### 滚动条样式

只对实际溢出滚动的容器添加：

```css
::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}
::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
```

### 基础结构要求

- `<!DOCTYPE html>`，`<html lang="zh">`，`<meta charset="UTF-8">`，`<meta name="viewport">`
- `body`：背景 `#F8FAFC`，字体 Inter/-apple-system/sans-serif，`color: #1E293B`
- 卡片：`background:#fff; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,.1); padding:16px`
- **统计卡**：`background:#fff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,.08); padding:12px 16px; flex:1; min-width:120px`，数值字号 **22px/600**，标签 12px `#64748B`
- **页面标题区（page-header）**：`background:#fff; border-bottom:1px solid #E2E8F0; padding:16px`，标题 `color:#1E293B`，副标题 `color:#64748B`。**严禁**使用渐变色、深色背景或 hero banner 样式——任何 `linear-gradient`、`background:#2563EB` 等彩色背景均不符合规范。
- **浮动 Tooltip 标准实现**（需要 HTML 内容时必须使用此模式）：用 `position:fixed` 浮层 + `data-tip` 属性存储内容，事件中读取 `this.dataset.tip`。
- **Tab 切换标准实现**：`.tab-panel { display:none }` + `.tab-panel.active { display:block }`，`switchTab(key, btn)` 切换 active 类。

## 数据内联（禁止交付依赖外部 JSON 的 HTML）`[自动检测]`

当业务数据行数 > 50 条或 JSON 体积 > 5 KB 时，**必须**按以下三步写出，最终交付**自包含单文件 HTML**（禁止交付依赖外部 JSON 的 HTML）：

1. 先写 `data.json`（纯数据，结构紧凑）
2. 再写 HTML 模板文件（命名与最终产物一致，如 `route_visualization.html`），内容中用占位符 `__DATA_PLACEHOLDER__` 代替数据
3. 最后执行 Python 内联脚本，将数据合并进 HTML，**覆盖写入同名的模板文件**（禁止生成新文件名如 `dashboard.html`，确保最终只保留一个 HTML 文件）

```python
# 第 3 步：内联合并（固定写法，必须执行）
import json, pathlib
html_file = pathlib.Path("<html文件>")  # 与第 2 步模板同名
data = json.loads(pathlib.Path("data.json").read_text())
html = html_file.read_text()
inlined = html.replace(
    "const DATA = '__DATA_PLACEHOLDER__';",
    f"const DATA = {json.dumps(data, ensure_ascii=False)};"
)
html_file.write_text(inlined)
```

```js
// HTML 模板中的占位写法（第 2 步模板固定格式）
const DATA = "__DATA_PLACEHOLDER__"; // 将被 Python 脚本替换为真实数据
render(DATA);
```

**理由**：分步写出规避单次 `write_file` 超时；内联合并后 HTML 自包含，在 iframe、BOS、本地等任何环境下均可直接打开，无需配套 JSON 文件。

## 交付前验证（exit code 0 才可交付）

**禁止在验证脚本返回 exit code 0 之前向用户交付 HTML。** 验证-修复是强制自循环，不是可选步骤。

**自修复循环**：

1. 运行验证（静态 + Playwright 运行时双层检测）：
   ```bash
   python3 $SKILL_DIR/validate_html.py <生成的HTML文件路径> --runtime
   ```
2. 若 exit code = 1：读取输出中的"修复"建议 → 直接修改 HTML → 回到步骤 1
3. 若 exit code = 0：验证通过，才可交付

验证覆盖：BMapGL API 误用、fetch 加载外部 JSON、SVG btoa 编码、渐变背景、缺少 HiDPI 适配、formatter 字面换行。

### 小屏适配（iframe 嵌入场景）

所有可视化 HTML 默认展示宽度约为 **420px**（嵌入 chat UI 的 iframe 宽度），必须在此宽度下可用：

- `body` 使用 `padding: 12px`，不写死宽度
- 布局优先 `flex-direction: column`，左右分栏（如地图 35/65、预测图 80/20）在小屏下自动折叠为上下
- 统计卡用 `flex-wrap: wrap; min-width: 100px`，自动换行
- 表格超宽时容器加 `overflow-x: auto`，禁止表格撑破布局
- SVG / Canvas 宽度用 `100%` 或 `clientWidth` 动态计算，不写死 px
- 字号不低于 11px，行高不低于 1.4，确保小屏可读

```css
/* 小屏折叠示例 */
.layout {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.chart-col {
  flex: 1;
  min-width: 280px;
} /* 小于 280px 时折叠 */
.metrics-col {
  width: 100%;
} /* 折叠后独占一行 */
```

---

## 错误兜底

当数据不完整或图表类型不支持时，输出居中白卡提示：标题"暂不支持该图表类型"（16px，`#1E293B`），副文字说明支持场景（14px，`#64748B`）。

---

## 快速对照

| 场景       | 典型业务                               | 图表类型                        | 关键字段                             |
| ---------- | -------------------------------------- | ------------------------------- | ------------------------------------ | ---------------------------------------------------- |
| 排程与调度 | 生产排程、插单重排、设备占用、扰动响应 | 甘特图 + 负载热力图（Tab 切换） | `tasks`, `load`, `time_range`, `now` | [scenarios/01](scenarios/01_gantt_scheduling.md)     |
| 物流配送   | 配送路线、车辆追踪、装载分配           | 物流地图 + 商品清单面板         | `nodes`, `routes`, `cargo`           | [scenarios/02](scenarios/02_logistics_map.md)        |
| 预测与预警 | 需求预测、故障预警、延期风险           | 复合图（折线/柱/置信区间）      | `layers[]`, `metrics`                | [scenarios/03](scenarios/03_forecast_chart.md)       |
| 工艺优化   | 配方比例、多方案参数对比、工艺评分     | 环形图 + 雷达图 + 参数表        | `recipe`, `radar`, `params`          | [scenarios/04](scenarios/04_process_optimization.md) |
