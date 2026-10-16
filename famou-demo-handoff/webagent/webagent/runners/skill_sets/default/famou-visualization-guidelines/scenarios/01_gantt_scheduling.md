# 场景一：排程与调度（`gantt` + `load_heatmap`）

适用场景：生产排程、设备占用、项目进度、插单重排、扰动响应、资源负载分析

## 数据结构

```json
{
  "title": "string",
  "time_range": { "start": "HH:MM", "end": "HH:MM" },
  "now": "HH:MM",
  "tasks": [{ "id", "name", "resource", "start", "end", "status": "done|normal|vip|warning", "predecessors": [], "successors": [] }],
  "baseline_tasks": [],
  "load": {
    "resources": ["机器A"],
    "slots": ["08:00", "09:00"],
    "data": [[0.8, 0.9]],
    "thresholds": { "overload": 0.9, "idle": 0.2 }
  }
}
```

## 布局

标题 + 副标题 → Tab（📋 甘特图 / 🌡️ 负载热力图）→ 各 Tab 面板，甘特和热力图通过 Tab 切换，避免机器数多时热力图被推出视口。

## 渲染要点

### 甘特图

- 任务色：`done=#16A34A` / `normal=#2563EB` / `vip=#DC2626` / `warning=#D97706`
- 今日线：`#DC2626` 2px 竖线，顶部标"现在"
- 对比模式：`baseline_tasks` 存在时，原排程渲染为灰色半透明底条（`rgba(100,116,139,0.25)`），新排程叠加其上
- **横向缩放**：必须提供缩放控制栏（`−` / `1×` / `+` / `重置`），`zoomLevel` 范围 0.5 ~ 4，步长 0.5；缩放时时间轴宽度等比拉伸，容器水平滚动；刻度粒度随缩放自动调整（1× → 天，2× → 12h，4× → 6h）

### 负载热力图

- 颜色：`0%→#16A34A` → `60%→#D97706` → `100%→#DC2626` 线性插值
- 行高 32px，与甘特图行高对齐
- hover tooltip：`{时间段} {负载率%}`

### Agent 交互点

- 任务条点击 → `"任务'${name}'排在${resource} ${start}~${end}，状态${status}，请分析或建议重排方案"`
- 过载格（≥ 0.9）点击 → `"${resource} 在 ${slot} 时段负载 ${X}%，超出阈值，如何缓解过载"`

## 参考实现

完整可运行代码见 [../references/gantt_heatmap.html](../references/gantt_heatmap.html)
