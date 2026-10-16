# 场景三：预测与预警（`forecast_chart`）

适用场景：需求预测、故障预警、延期风险、时序趋势、多指标叠加分析

## 数据结构

```json
{
  "title": "需求预测分析",
  "x_label": "日期", "y_label": "数量（件）",
  "layers": [
    { "type": "bar",       "name", "color", "data": [{ "x", "y" }] },
    { "type": "line",      "name", "color", "dash": false, "data": [{ "x", "y" }] },
    { "type": "area",      "name", "color", "opacity": 0.15, "upper": [], "lower": [] },
    { "type": "threshold", "name", "value", "color" }
  ],
  "metrics": [{ "label", "value", "status": "good|warning|danger" }]
}
```

## 布局

左侧 80% SVG 复合图 + 右侧 20% 指标摘要卡

## 渲染要点

- 纯 SVG 渲染，图层叠加顺序：`area` → `bar` → `line` → `threshold`
- `threshold` 层：水平虚线 `#D97706`，右端标注名称
- 历史与预测区段用竖虚线分隔
- 右侧指标卡：`good`→成功色，`warning`→警告色，`danger`→强调色
- hover 交叉准线：显示所有系列在该 x 点数值

### Agent 交互点

- 数据点点击 → `"${x} 实际值 ${y} 偏离预测 ${X}%，请分析偏差原因"`（偏差 > 5% 的圆点渲染为红色并放大）

## 参考实现

完整可运行代码见 [../references/forecast_chart.html](../references/forecast_chart.html)
