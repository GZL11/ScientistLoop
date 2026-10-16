# 场景二：物流配送（`logistics_map`）

适用场景：配送路线规划、车辆追踪、多点装载分配、仓库到客户配送

## BMapGL SDK 引用（固定，直接复制，禁止替换 AK）

```html
<script src="https://api.map.baidu.com/api?v=1.0&type=webgl&ak=OyLmGLaGzgonCw3i6sgfe3ebGX1ixhLl&callback=_bmap_init"></script>
```

- **`<script>` 位置要求**：BMapGL SDK 的 `<script>` 标签**必须放在 `<body>` 内（`</body>` 结束标签之前）**，禁止放在 `<head>` 中。BMapGL API 内部会动态插入额外的 `getscript` 资源，若放在 `<head>` 内执行时 `document.body` 尚未解析，会抛出 `Cannot read properties of null (reading 'appendChild')`
- `_bmap_init` 回调**第一行**必须隐藏 loading：`document.getElementById("loading").style.display = "none";`
- AK 已配置为**不限制来源域名**，iframe 嵌入场景直接使用，无需修改
- **禁止使用 Leaflet、OpenLayers、Mapbox 等第三方地图库**，地图场景只能使用 BMapGL
- **加载失败兜底**：在 `_bmap_init` 外层加超时检测：
  ```js
  setTimeout(() => {
    if (typeof BMapGL === "undefined") {
      document.getElementById("map").innerHTML =
        '<div style="padding:40px;text-align:center;color:#DC2626">百度地图加载失败，请检查网络后刷新</div>';
    }
  }, 5000);
  ```

## 数据结构

```json
{
  "title": "配送路线总览",
  "nodes": [{ "id", "type": "warehouse|customer", "name", "lat", "lng", "info": {} }],
  "routes": [{
    "vehicle": "京A-12345",
    "stops": ["W001", "C001"],
    "status": "in_transit|delivered|delayed",
    "cargo": [{ "sku", "name", "qty", "weight_kg", "dest" }],
    "stats": { "total_km", "eta", "load_rate" }
  }]
}
```

## 布局

左侧 35%（路线列表 + 商品清单表格 + 汇总）+ 右侧 65%（BMapGL 地图）

## 渲染要点

### 地图区（BMapGL）

- 坐标输入为 WGS84，**必须转换为 BD09**：WGS84 → GCJ02 → BD09 两步转换（见 reference 中 `wgs84ToBd09` 函数）
- 仓库节点：`BMapGL.Icon` + SVG，**必须用 `encodeURIComponent` 编码**（禁止 `btoa`）
- 路线：`BMapGL.Polyline` 点对点直线，选中加粗（strokeWeight: 5），其余半透明
- **切换透明度必须用 `polyline.setStrokeOpacity(0.3)`，严禁调用 `polyline.setOpacity()`（BMapGL 不存在此方法，会抛 TypeError）**
- 路线颜色：`in_transit=#2563EB` / `delivered=#16A34A` / `delayed=#D97706`

### 左侧面板

路线列表点击切换高亮，商品清单表格，底部汇总里程/ETA/装载率

### Agent 交互点

- 路线点击 → `"车辆 ${vehicle} 路线 ${stops}，状态 ${status}，帮我分析或优化该路线"`

## 参考实现

完整可运行代码见 [../references/logistics_map.html](../references/logistics_map.html)
