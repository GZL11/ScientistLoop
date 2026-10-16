# 场景四：工艺优化（`process_optimization`）

适用场景：配方比例展示、多方案参数对比、工艺参数评分、原料成分分析

## 数据结构

```json
{
  "title": "工艺方案对比",
  "schemes": ["方案A", "方案B"],
  "active_scheme": "方案A",
  "recipe": { "方案A": [{ "name", "ratio": 0.45, "unit": "45%" }] },
  "radar": { "axes": ["强度", "韧性", "耐热", "成本", "加工性"], "方案A": [85, 70, 90, 60, 75] },
  "params": [{ "name", "方案A", "方案B", "optimal": "方案A", "unit" }]
}
```

## 布局

方案切换 Tab → 左 50%（环形图 + 成分列表）+ 右 50%（雷达图）→ 底部参数对比表格

## 渲染要点

### 环形图

纯 SVG，`stroke-dasharray` 实现分段，颜色按 `#2563EB` / `#16A34A` / `#D97706` / `#64748B` 循环

### 雷达图

纯 SVG，等分角度多边形网格，各方案半透明叠加，轴线 `#E2E8F0`

### 参数表

最优方案列 `#16A34A` 高亮；Tab 切换时环形图和参数表同步更新，雷达图显示全部方案

### Agent 交互点

- 参数行点击 → `"${param} 方案A=${valA} vs 方案B=${valB}，哪个更优"`

## 参考实现

完整可运行代码见 [../references/process_optimization.html](../references/process_optimization.html)
