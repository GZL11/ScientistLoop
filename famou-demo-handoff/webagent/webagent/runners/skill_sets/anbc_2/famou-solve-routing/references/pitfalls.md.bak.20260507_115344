# 路径规划常见坑 + 退出自检清单

> 本文件中的具体数字(节点数、车数、容量值、半径...)都是**典型样貌**——
> 用于说明踩坑形态。**真正的约束以用户提供的问题描述为准**。

## 通用坑

### 坑 0:交付字段名/文件名不匹配

字段名(尤其中英文 `网点编码`/`门店经度`/`总重量`)逐字保留。
最后用 `pd.read_csv` 重读自己输出对照需求清单打勾。

**⚠️ 补充——输出格式与评估器严格对齐**：
- 若评估器要求 CSV 则不能输出 JSON；若要求特定字段顺序（如 `instance_id, city_id, step_order`）则必须逐字段核对。
- 建议在生成输出后立即用 `pd.read_csv` 重读，打印 `df.columns.tolist()` 与需求清单逐项比对。

### 坑 1:节点漏访问 / 重复访问

- 验证:`set(visited) == set(must_visit)` 且 `len(visited) == len(set(visited))`
- 仓库节点(id=0、demand 空、坐标特殊标记)按问题描述判断是否计入"必访客户"
- 多实例每实例的 `city_id` 都从 1 开始但坐标系不同,不能合到同一矩阵

### 坑 2:多车要求"全部投入"被违反

若问题描述硬要求"K 辆车全部投入,每辆至少服务 1 个节点":
- K-Means K=K 一般保证非空 cluster,但均衡微调中要强制每 cluster ≥ 1 节点
- 否则均衡微调可能腾空某 cluster

---

## 子族 A/B 专属坑(TSP / mTSP)

### 坑 A1:单起点 NN 质量差异巨大（已强化）

单起点 NN 解长度方差很大，会系统性低估解质量约 5–10%。

**强制要求：多起点（≥5–10 个随机起点）取最优**再做局部搜索，不允许只用单起点。

```python
best_tour, best_dist = None, float('inf')
for start in random.sample(range(n), min(10, n)):
    tour = nearest_neighbor(dist_matrix, start)
    d = total_distance(tour, dist_matrix)
    if d < best_dist:
        best_dist, best_tour = d, tour
# 再对 best_tour 执行 2-opt
```

多起点 + 限邻域 2-opt 是 n=500 规模的**标准配置**，单起点 NN + 全邻域 2-opt 会系统性低估解质量。

### 坑 A2:2-opt 没限邻域，n=500 就超时（已强化）

完整 O(n²) 单轮约 25 万次评估，需要数十轮才收敛。
**预计算每节点最近 30 邻居**，仅检查邻居对（伪 LK 风格），单轮压到 O(nk)。

**n≥200 实例强制要求**：
1. 预计算 k=30 近邻表（一次性开销）
2. 2-opt 运行直到**完全收敛**（一整轮无改善为止），而非固定轮数
3. n=500 规模下，限邻域 2-opt 完全收敛通常需要 20–50 轮，单实例 <1s

```python
# 预计算近邻表
neighbors = {}
for i in range(n):
    dists = [(dist_matrix[i][j], j) for j in range(n) if j != i]
    neighbors[i] = [j for _, j in sorted(dists)[:30]]

# 限邻域 2-opt，运行至收敛
improved = True
while improved:
    improved = False
    for i in range(n):
        for j in neighbors[i]:           # 只检查邻居对
            if two_opt_gain(tour, i, j, dist_matrix) > 1e-9:
                tour = apply_two_opt(tour, i, j)
                improved = True
```

对于 [0,1]² 均匀分布的 500 城市 TSP，归一化坐标下最优解总距离通常在 **5.5–6.5** 之间；若使用原始未归一化坐标，需结合坐标范围换算后验证量级。

### 坑 A3:多实例坐标互相串通

每实例的 `city_id` 都从 1 开始，但**坐标系不同**。
必须按 `instance_id` 切分，每实例独立计算距离矩阵和路线。

### 坑 A4:tour 闭合处理

报告路径时通常要求"末步返回起点"——CSV 最后一行 city_id 与第一行相同。
计算总距离时不要忘 `dist[tour[-1], tour[0]]`（回程段）。

### ⚠️ 坑 A5：距离/路程数量级合理性校验（高频）

**现象**：求解完成后总距离异常偏小（如 <100），或与同批次其他实例数量级相差 10 倍以上。

**根本原因**：坐标被错误归一化、单位换算错误、索引方式错误（如行列转置）。

**检查方法**：
- 对均匀分布的 n 城市 TSP，理论最优解估算：`L ≈ 0.7124 × sqrt(n × Area)`，其中 Area 为坐标范围面积（如 [0,100]² 则 Area=10000）。
- 每次求解后立即打印单实例总距离，与理论估算对比：

```python
import math
x_range = coords[:, 0].max() - coords[:, 0].min()
y_range = coords[:, 1].max() - coords[:, 1].min()
area = x_range * y_range
theoretical = 0.7124 * math.sqrt(n * area)
print(f"实际总距离: {total_dist:.2f}, 理论估算: {theoretical:.2f}, 比值: {total_dist/theoretical:.2f}")
# 若比值 < 0.5 或 > 3.0，必须排查
```

- 若任何实例总距离数量级与理论预期偏差超过 **10 倍**，**禁止提交**，必须回溯排查坐标读取、距离计算、索引方式。

### ⚠️ 坑 A6：解质量异常均匀——过于完美的红旗（新增）

**现象**：多实例批量求解后，各实例总距离标准差极小（如 <0.1% 均值），或所有实例的值几乎相同。

**根本原因**：距离矩阵被归一化到固定范围、结果被截断、或所有实例用了同一套坐标。

**处理**：随机抽取 3–5 对节点，手动计算距离并与代码输出对比，误差 <0.1% 方可继续。

---

## 子族 C 专属坑(CVRP)

### 坑 C1:K-Means 仅按地理坐标，超载严重

仅用经纬度聚类的结果常常某 cluster 总需求 > 容量。
**容量感知 K-Means**：多次随机种子（`n_init=20`）筛"全部不超载且 std(loads) 最小"的方案。
都超载时再"超载修复"——把超载 cluster 最重的节点移到最近未满 cluster。

### 坑 C2:工作量均衡过度修补

强行把城区密集 cluster 的节点拨给郊区 = 路线交叉、总时长反而更长。
**接受地理决定的天然差异**，spread ≤ 用户上限通常足够。
均衡微调只动**边界节点**（距其他 cluster 质心比当前 cluster 质心更近的）。

**强制执行步骤**（完成初始 K-Means + NN 构路后，必须继续执行以下步骤再退出）：
1. **多起点 NN**：每 cluster 至少 5 个随机起点，取最优路线（对应坑 A1）
2. **限邻域 2-opt**：预计算每节点最近 20 邻居，仅检查邻居对（对应坑 A2）
3. **边界节点均衡微调**：将时长最长车辆中"距其他 cluster 质心更近的边界节点"移入相邻 cluster，循环直到 max-min 时长差 < 120 分钟或无可移动边界节点

上述三步在策略步骤中应**明确列出，作为必做而非可选项**。

**退出优化的质量门槛**：不仅要求硬约束全部满足，还需满足"已执行至少一轮 2-opt 局部搜索"且"各车时长标准差 < 60 分钟，或已连续 3 轮优化无改善"方可停止。

### 坑 C3:经纬度直接欧式

经纬度的"1 度"在不同纬度上对应不同实际距离。
小范围近似（纬度 20–50°）：`Δlon × 111000 × cos(lat)`，`Δlat × 111000`，单位米。
跨大区或精确算用 Haversine（向量化版本见 algorithm_playbook.md）。

**强制执行**：在距离矩阵计算函数开头添加断言：
```python
assert use_haversine, "必须使用 Haversine，禁止直接欧式距离（经纬度数据）"
```

**Sanity check**：随机抽取 5 对节点，对比 Haversine 距离与欧式距离，若差异 >5% 则报警并中止使用欧式距离。

### 坑 C4:服务时间被忽略

每节点服务时间（几十秒到几分钟）。CV 计算和工时上限若仅算行驶时间会低估 10–30%。
`total_h = travel_h + n_stops * service_seconds / 3600`

**时长计算完整性检查**：总时长必须包含三部分：
- 行驶时间（干线 + 支线，按速度分类）
- 服务时间（节点数 × service_seconds / 3600）
- 返回仓库时间

**验证方式**：手动计算至少 1 辆车的时长，与代码输出对比，误差 <1%。

### ⚠️ 坑 C5：多车"全部投入"被违反

若问题描述要求"全部投入"，均衡微调过程中强制每 cluster 至少保留 1 节点。

### ⚠️ 坑 C6：过于完美均衡结果的红旗（新增）

**现象**：多目标优化后各车时长标准差 <2 分钟或极差 <5 分钟（对于 100+ 节点/车的规模）。

**根本原因**：这是强烈的异常信号，通常说明距离被归一化、时长被截断，或均衡计算本身有逻辑错误。

**处理**：必须停下来检查计算逻辑，手动抽查 2 辆车的时长计算全过程，确认距离/速度/服务时间口径正确后方可继续。

### ⚠️ 坑 C7：路线地理集中度验证（新增）

**现象**：某辆车的路线节点同时覆盖地图东西两端，存在大范围交叉。

**检查方法**：
```python
for v_id, route_nodes in routes.items():
    lons = [nodes[n]['lon'] for n in route_nodes]
    lats = [nodes[n]['lat'] for n in route_nodes]
    lon_spread = max(lons) - min(lons)
    lat_spread = max(lats) - min(lats)
    total_spread = lon_spread + lat_spread
    if total_spread > global_spread * 0.5:  # 跨越全局范围 50% 以上
        print(f"警告：车辆 {v_id} 路线地理跨度异常大，建议人工审查")
```

---

## 子族 D 专属坑(VRPTW)

### 坑 D1:插入后未传播 arrival 时间

Solomon 插入一个新节点后，其后续所有节点的 arrival 时间都要向后传播校正。
忘记传播会让"时间窗满足"看似成立，实际下游全部违反。

### 坑 D2:服务时间是否纳入时间窗判定

`arrival[i] + service[i] = departure[i]`，`arrival[i+1] = departure[i] + travel(i, i+1)`。
是否要求 `arrival[i] + service[i] <= latest[i]`（在窗内完成服务）还是仅 `arrival[i] <= latest[i]`（在窗内到达即可）？以问题描述为准。

---

## 子族 E 专属坑(危化品 / 多约束)

### 坑 E1:路网与完全图混用

路网是有限边集，不是完全图。
两节点间距离 = Dijkstra 最短路，不是欧式直线。
不同车型走不同路网（A 级避 school_zone；装 explosive 还要避黑名单），
**预计算每车型对应的距离/风险矩阵**。

###