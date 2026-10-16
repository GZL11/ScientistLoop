# 路径规划算法手册

## 子类型 A：纯 TSP（单车巡回）

### 算法骨架
```
1. 多随机起点 NN 构造初始解（5–10 起点取最优）
2. 2-opt 改进
   - n < 300：完整 O(n²) 扫描
   - n ≥ 300：限邻域 30（每节点最近 30 邻居）
3. ILS：扰动（3-opt 或随机翻转 3–8 段） + 2-opt 修复
4. 时间到期保留历史最优
```

### NN 构造（向量化版）
```python
def nearest_neighbor(dist, start=0):
    n = len(dist)
    visited = np.zeros(n, dtype=bool)
    tour = [start]; visited[start] = True
    cur = start
    for _ in range(n - 1):
        d = dist[cur].copy(); d[visited] = np.inf
        nxt = int(np.argmin(d))
        tour.append(nxt); visited[nxt] = True; cur = nxt
    return tour
```

### 2-opt 限邻域（用 pos 数组避免 list.index）
```python
def two_opt_limited(tour, dist, k=30, deadline=None):
    n = len(tour)
    neigh = np.argsort(dist, axis=1)[:, :k]      # (n, k)
    pos = np.empty(n, dtype=int); pos[tour] = np.arange(n)
    improved = True
    while improved:
        improved = False
        for ii in range(n - 1):
            a, b = tour[ii], tour[ii + 1]
            for c in neigh[a]:
                if c == a or c == b: continue
                jj = pos[c]
                if jj <= ii + 1: continue
                d = tour[(jj + 1) % n]
                gain = dist[a, b] + dist[c, d] - dist[a, c] - dist[b, d]
                if gain > 1e-9:
                    tour[ii + 1:jj + 1] = tour[ii + 1:jj + 1][::-1]
                    pos[tour] = np.arange(n)
                    improved = True
                    break
            if deadline and time.time() > deadline: return tour
    return tour
```

---

## 子类型 B：mTSP

### 算法骨架
```
1. K-Means 聚类（K = 车数, n_init=20）
2. 节点数严重不均（差 > 2×）则重聚类 / 转移边界节点
3. 每 cluster 独立 NN + 2-opt
4. 跨 cluster 均衡：把最忙 cluster 的边界节点（距其他 cluster 质心近）转给最闲
5. 转移后重跑接收 cluster 的 2-opt
```

---

## 子类型 C：CVRP

### 完整流程
```
阶段 1 — 容量感知 K-Means（≤30s）
  for seed in range(20):
      labels = KMeans(K, random_state=seed, n_init=1).fit_predict(coords)
      if all(load(c) <= cap for c in clusters):
          score = std(loads)  # 越小越均衡
          keep best
  fallback: 强制超载修复（把最重节点移到最近未满 cluster）

阶段 2 — 每 cluster 路线构建（30–60s）
  for cluster:
      tour = NN(cluster_nodes, start=depot)
      tour = two_opt_limited(tour, k=30)

阶段 3 — 工作量均衡（60–120s）
  while CV(times) > 0.10 and not improved-fail:
      最忙 cluster 边界节点 → 最闲 cluster
      重跑接收 cluster 的 2-opt
      验证容量未超

阶段 4 — Or-opt 全局精修（剩余预算）
  跨 cluster 移动单点/2/3 连续节点到最优位置
```

### 时间计算(典型城市配送口径)
```python
travel_h = (mainline_to_first / V_mainline + intra_distance / V_intra + last_to_depot / V_mainline)
service_h = n_stops * service_seconds / 3600
total_min = (travel_h + service_h) * 60
```
速度参数(干线 vs 网点间)、服务时间以问题描述为准。

### Haversine（地球半径 6371 km）
```python
def haversine(lon1, lat1, lon2, lat2):
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat/2)**2 + np.cos(p1)*np.cos(p2)*np.sin(dlon/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))
```

向量化（节点数 1000+ 时必备）：
```python
lat = np.radians(coords[:, 1]); lon = np.radians(coords[:, 0])
dlat = lat[:, None] - lat[None, :]
dlon = lon[:, None] - lon[None, :]
a = np.sin(dlat/2)**2 + np.cos(lat[:, None])*np.cos(lat[None, :])*np.sin(dlon/2)**2
dist_km = 2 * 6371.0 * np.arcsin(np.sqrt(a))
```

---

## 子类型 D：VRPTW（Solomon 插入）

```
1. 取时间窗最紧（latest - earliest 最小）的节点作种子，开新路线
2. 反复挑选"插入代价最小且时间窗可行"的节点插入到当前路线最佳位置
   插入代价 = α×Δdistance + β×(latest - arrival)
3. 没有节点可加 → 开新路线
4. 全部插入完 → 2-opt + Or-opt 改进，时间窗可行性内嵌评估
```

**关键：插入后必须把后续所有节点的 arrival 时间向后传播校正。**

---

## 子类型 E:多约束 VRP(危化品 / 路网图风格)

### 路网最短路预计算（Dijkstra）
```python
import networkx as nx
G_default = nx.DiGraph()
G_no_explosive = nx.DiGraph()
G_no_school = nx.DiGraph()  # school_zone 路段禁
for seg in segments:
    if seg.restriction != 'school_zone':
        G_default.add_edge(seg.from_node, seg.to_node,
                           dist=seg.distance, risk=seg.distance*seg.density*seg.risk_mul)
    if seg.restriction not in ('school_zone', 'blacklist_explosive'):
        G_no_explosive.add_edge(...)  # 给 explosive 类车用
    # ...
# 对每对节点预计算最短路（按距离 + 风险加权）
shortest_dist = {(i, j): nx.dijkstra_path_length(G_default, i, j, weight='dist')
                 for i in nodes for j in nodes}
shortest_route = {...}  # 真实路径（经过的中间节点）用于风险/距离汇总
```

**车型对应不同路网**：
- A 级（V0/V4，全类别）→ G_no_school
- 装 explosive 时 → G_no_explosive ∩ G_no_school
- 不同车型查不同图，距离矩阵分别预计算

### 装载与路线构造
```
1. 按 hazmat_class 把节点分组(每节点单一类别)
2. 兼容矩阵:每节点 → 哪些车可运(class ∈ allowed_classes)
3. 贪心:按 demand 降序逐节点装入"剩余容量最大且兼容"的车(hazmat 不混装:同车单一类别)
4. 每车在它对应的路网最短路距离矩阵上做 NN + 2-opt
5. 评估:里程费 + 风险罚款 + 保险等(具体单价以问题描述为准)
6. 时间窗以问题描述为准。若有强制休息:
   total_h = travel_dist / V + floor(travel_dist / D_rest_trigger) * t_rest
7. 风险上限:超限触发节点抽换
8. 应急站覆盖:每站半径 R 内需有客户节点被某车访问 → 事后检查 + 修复
```

### 应急站覆盖修复
```python
def check_coverage(routes, stations, nodes_xy):
    covered = set()
    for route in routes:
        for n in route.nodes:
            for s_id, sx, sy, r in stations:
                if dist((sx, sy), nodes_xy[n]) <= r:
                    covered.add(s_id)
    return covered

# 若某站未被覆盖：
# 1. 找该站附近未访问/可重新分配的节点
# 2. 把节点抽到最近、可装该类别、容量足的车
# 3. 重跑该车的 2-opt
```

---

## 时间预算分配

| 规模 | 阶段 1 构造 | 阶段 2 局部搜索 | 阶段 3 均衡/精修 | 总计 |
|------|------------|----------------|----------------|------|
| < 200 节点 | 5s | 30s | 60s | ~100s |
| 200–1000 | 10s | 60s | 150s | ~220s |
| 1000–2000 | 20s | 100s | 140s | ~260s |
| > 2000 | 30s | 120s | 120s | ~270s |

## 距离矩阵预计算（必备）

```python
from scipy.spatial.distance import cdist
# 平面坐标
dist = cdist(coords, coords)
# 经纬度（小范围）：先按纬度近似平面化
projected = coords.copy()
projected[:, 0] = coords[:, 0] * 111000 * np.cos(np.radians(coords[:, 1].mean()))
projected[:, 1] = coords[:, 1] * 111000
dist_m = cdist(projected, projected)
```

n=2000 时矩阵占用 ~32MB（float64），可接受；n=10000 时 800MB，要降精度或分块。

## 工作量均衡评估

```python
times = [estimate_route_time(r) for r in routes]
spread = (max(times) - min(times)) / max(times)  # 常见口径
cv = np.std(times) / np.mean(times)              # 也常用
```
具体口径(spread vs CV)和上限(10–20%)以问题描述为准。
