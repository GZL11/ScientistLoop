---
name: famou-visualization-guidelines
description: >
  famou 可视化规范指南。定义所有可视化 HTML 输出的统一色彩、字体、渲染策略和图表选型规则。
  famou 的能力边界涵盖：排程与调度（生产排程、插单重排、扰动响应）、预测与预警（需求预测、故障预警、延期风险）、
  资源优化（产能/库存/路径/装载多目标优化）、方案解释（多方案对比、瓶颈归因）。
  以上任意场景需要输出可视化结果时，必须引用本 skill 的规范，包括 famou-builder 生成图表、可视化规格扩展、前端代码生成等。
  只要上下文出现"生成 HTML"、"可视化"、"图表"、"甘特"、"趋势图"、"对比图"、"地图路线"等关键词，立即引用本 skill。
---

# famou 可视化规范

本 skill 定义 famou 所有可视化输出的统一规范，确保排程、预测、优化、方案解释等各类场景下的视觉一致性。

---

## 职责边界

- **本 skill 负责**：样式规范、图表选型、渲染策略、错误兜底
- **本 skill 不负责**：优化求解、数据清洗、业务逻辑判断、方案决策

---

## 色彩系统

所有颜色必须严格使用下表色值，不得自行发挥：

| 用途 | 色值 | 使用场景 |
|---|---|---|
| 主色 | `#2563EB` | 普通任务、进行中状态、主要元素 |
| 强调色（VIP） | `#DC2626` | 优先级高的任务、警报、VIP 标签 |
| 成功色 | `#16A34A` | 已完成状态、达成目标 |
| 警告色 | `#D97706` | 延误风险、临界状态 |
| 背景色 | `#F8FAFC` | 页面背景 |
| 卡片背景 | `#FFFFFF` | 内容卡片区域 |
| 文字主色 | `#1E293B` | 主要文字、标题 |
| 文字副色 | `#64748B` | 次要文字、标签、辅助信息 |
| 边框色 | `#E2E8F0` | 分割线、边框 |

---

## 字体规范

```css
font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif;
```

| 层级 | 字号 | 字重 |
|---|---|---|
| 标题 | 16px | 600 |
| 副标题 | 14px | 500 |
| 正文 | 14px | 400 |
| 小字 / 标签 | 12px | 400 |

---

## 间距与形状

```css
padding: 16px;           /* 标准内边距 */
border-radius: 8px;      /* 普通圆角 */
border-radius: 12px;     /* 卡片圆角 */
box-shadow: 0 1px 3px rgba(0,0,0,0.1);  /* 卡片阴影 */
```

---

## 渲染策略

数据量决定渲染方式，不可混用：

| 数据条数 | 渲染方案 |
|---|---|
| < 1000 条 | CSS / SVG 渲染 |
| ≥ 1000 条 | Canvas 渲染 + 虚拟滚动 |

---

## 支持的图表类型

### 甘特图（`gantt`）
适用场景：生产排程、设备占用、项目进度

核心数据字段：
- `tasks[]`：任务列表，每项含 `id`, `name`, `machine/resource`, `start`, `end`, `priority`, `status`
- `time_range`：时间轴范围 `{ start, end }`

渲染要点：
- 横轴为时间，纵轴按资源/机器分组
- VIP 任务用强调色 `#DC2626`，普通任务用主色 `#2563EB`，已完成用成功色 `#16A34A`
- 时间标签等间距显示于顶部
- 任务条宽度 = `(end - start) / total_range * 100%`

### 物流地图（`logistics_map`）
适用场景：配送路线、仓库到客户、车辆轨迹

核心数据字段：
- `routes[]`：路线列表，每项含 `vehicle`, `from`, `to`, `lat_from`, `lng_from`, `lat_to`, `lng_to`, `status`

渲染要点：
- 使用 Leaflet（`cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/`）+ OpenStreetMap 瓦片
- 在途路线用主色 `#2563EB`，已送达用成功色 `#16A34A`，延误用警告色 `#D97706`
- 起终点用 `circleMarker` 标注，polyline 连线
- 地图下方附路线列表卡片，含状态 badge

### 折线图（`line_chart`）
适用场景：需求预测、趋势分析、时序数据

核心数据字段：
- `series[]`：数据系列，每项含 `name`, `data[]`（`{ x, y }` 对）
- `x_label`, `y_label`：轴标签

渲染要点：
- 纯 SVG 渲染，无需外部库
- 多系列用主色系区分（主色 → 成功色 → 警告色 循环）
- 必须含坐标轴、网格线、图例
- hover 时显示精确数值 tooltip

### 柱状图（`bar_chart`）
适用场景：方案对比、库存分析、分类统计

核心数据字段：
- `categories[]`：X 轴分类标签
- `series[]`：数据系列，含 `name`, `values[]`

渲染要点：
- 纯 SVG 渲染
- 单系列用主色 `#2563EB`，多系列按主色系区分
- 柱顶显示数值标签
- 支持分组和堆叠两种模式

---

## 输出要求

### HTML 文件规范

1. **纯 HTML 输出**：不包含 markdown 代码块标记（不用 ` ```html ` 包裹）
2. **自包含**：可直接在浏览器中双击打开，无需服务器
3. **CDN 来源**：外部库统一从 `cdnjs.cloudflare.com` 加载
4. **语言**：`<html lang="zh">`，`<meta charset="UTF-8">`

### 基础 HTML 骨架

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{图表标题}}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Inter, -apple-system, sans-serif; background: #F8FAFC; color: #1E293B; padding: 16px; }
    .card { background: #FFFFFF; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 16px; }
    h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
    /* 按图表类型补充专属样式 */
  </style>
</head>
<body>
  <div class="card">
    <h2>{{图表标题}}</h2>
    <!-- 图表主体 -->
  </div>
  <!-- 数据和渲染逻辑写在此处 -->
</body>
</html>
```

---

## 错误兜底

当输入数据不完整，或请求的图表类型不在支持范围内时，输出以下友好提示页面，不强行生成：

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: Inter, sans-serif; background: #F8FAFC; display: flex; align-items: center; justify-content: center; min-height: 200px; }
    .card { background: #fff; border-radius: 12px; padding: 24px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
    h3 { font-size: 16px; color: #1E293B; margin-bottom: 8px; }
    p { font-size: 14px; color: #64748B; }
  </style>
</head>
<body>
  <div class="card">
    <h3>暂不支持该图表类型</h3>
    <p>当前不支持「{{图表类型}}」，支持的类型：甘特图、物流地图、折线图、柱状图</p>
  </div>
</body>
</html>
```

---

## 快速对照

| 能力域 | 典型业务场景 | 推荐图表类型 | 关键字段 |
|---|---|---|---|
| 排程与调度 | 生产排程、插单重排、设备占用、扰动响应 | 甘特图 | `tasks`, `time_range` |
| 资源优化 | 配送路线、车辆追踪、装载分配 | 物流地图 | `routes`, 坐标 |
| 预测与预警 | 需求预测、故障预警、延期风险、趋势报告 | 折线图 | `series`, 时序数据 |
| 方案解释 | 多方案对比、产能/库存分析、瓶颈归因 | 柱状图 | `categories`, `series` |
