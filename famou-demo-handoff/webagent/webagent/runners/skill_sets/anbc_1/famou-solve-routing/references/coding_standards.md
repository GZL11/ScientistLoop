# 路径规划编码与规范

汇总 SKILL.md Step 1(业务清单提取)/ Step 5(编码运行) 的细节。本文件可独立修改而不动 SKILL.md。

> **关键原则**:所有文件名、字段名、产物形态都以**用户提供的任务描述为准**。
> 本文件给出的是**数据形态分类 / 编码思路 / 常见组合**,不是固定命名约定。

## 1. 业务清单提取(Step 1)

无论用户以什么形式提供问题(单个文档 / 对话描述 / 多个 spec),开始建模前必须把以下条目逐项抄到脚本顶部注释中。

### 1.1 业务清单

- **目标函数**:总距离 / 总时长 / 总成本(距离费 + 风险罚款 + 保险费 等)/ 工作量均衡度。是单目标还是加权多目标?
- **硬约束**:容量上限、时间窗、车辆数(是否要求"全部投入"?)、车辆类别(危化品准入)、路网禁令、应急站覆盖。
- **距离/时间口径**:欧式 vs Haversine vs 路网最短路;干线速度 vs 网点间速度;服务时间是否计入工时。
- **必访节点集合**:抄到验证脚本里——漏一个网点 = 整套交付报废。仓库节点(通常 id=0 或 demand=空)按问题描述判断是否计入。
- **多实例?**:若 `instance_id` 字段存在,每实例的坐标系是独立的(city_id 都从 1 开始但坐标不同),必须按 instance 切分。

### 1.2 数据清单

按用途分类:

| 数据类型 | 用途 | 典型字段方向 |
|---------|------|------------|
| 节点主数据 | 坐标、需求、时间窗、类别 | id / lon-lat / demand / [earliest, latest] / hazmat_class |
| 车辆主数据 | 载重、类别准入、起点 | vehicle_id / capacity / allowed_classes / depot |
| 路段(若路网图)| 路网拓扑、距离、风险 | from / to / dist / density / restriction |
| 距离矩阵(若直接给)| 节点对距离 | source / dest / dist |
| 应急站(若有)| 站坐标 + 覆盖半径 | station_id / lon-lat / radius_km |
| 路网禁令 | 哪段路 / 哪类车不能走 | segment_id / class / restriction_type |

### 1.3 交付清单

- 每个产物文件的**确切文件名**与**字段名**(中英文大小写空格逐字保留,如 `网点编码`/`门店经度`/`总重量`)。
- 通常 CSV 包含两类:每节点一行(route_detail)+ 每车一行(route_summary)。
- 可视化要求:**按用户指定走**——若用户要求 Leaflet/OpenStreetMap、SVG、Plotly,按要求选;若没指定,选与坐标类型匹配的最朴素呈现。

## 2. 编码规范(Step 5)

### 距离计算

- 大规模(n > 500)必须**预计算距离矩阵**并缓存。
- 经纬度小范围近似:先平面化再 cdist
  ```python
  projected = coords.copy()
  projected[:, 0] = coords[:, 0] * 111000 * np.cos(np.radians(coords[:, 1].mean()))
  projected[:, 1] = coords[:, 1] * 111000
  dist_m = cdist(projected, projected)
  ```
- 跨大区或要求精确:Haversine 向量化版(见 algorithm_playbook.md)。
- n=2000 矩阵 ~32 MB(float64),OK;n=10000 ~800 MB,需降精度或分块。

### 聚类(K-Means / 容量感知)

- `from sklearn.cluster import KMeans; KMeans(n_clusters=K, n_init=20)`
- CVRP 必须做**容量感知**:多种子筛"全部不超载且 std(loads) 最小";都超载启动超载修复(把最重节点移到最近未满 cluster)。
- 若问题描述要求"K 辆车全部投入",K-Means K=K 一般保证非空 cluster,但均衡微调中要强制每 cluster ≥ 1 节点。

### 构造算法

- **多起点最近邻 (NN)**:5–10 个起点取最优。
- **节约算法 (Clarke-Wright)**:`saving[i,j] = d[0,i] + d[0,j] - d[i,j]`,按 saving 降序合并,适合 CVRP。
- **Solomon 插入(VRPTW)**:每次挑插入代价最小且时间窗可行的节点,插入后必须把后续 arrival 时间向后传播校正。

### 改进算法

- **2-opt 限邻域**(必备):
  ```python
  neighbors[i] = np.argsort(dist[i])[:30]
  # 仅检查邻居对,O(nk) 而非 O(n²)
  ```
  用 `pos` 数组避免 `tour.index()` 的 O(n) 开销。
- **Or-opt**:跨路线节点交换(均衡微调)。

### 危化品 / 路网图

- 路网用 Dijkstra,**按车型分别预计算**距离/风险矩阵:
  - 默认图(去 school_zone 等通用禁令)
  - explosive 图(再去 explosive 黑名单)
  - 不同车型查不同图。
- 节点先按 hazmat_class 分组,再用车型兼容矩阵装载——不要先地理聚类再修类别。
- 应急站覆盖判定:**节点 vs 站点欧式距离 ≤ R**(不是路网距离),"被该车经过"= 该车路线访问的客户节点(不含中间转运经过的非客户节点)。

### 服务时间与工时

服务时间不能被忽略:`total_h = travel_h + n_stops * service_seconds / 3600`。
工时上限/CV 计算若仅算行驶时间会低估 10–30%。

### 强制休息(若有)

`floor(driving_dist / 160) × 0.5` 小时之类的规则要纳入工时——忽略会让"时长 ≤ 上限"看起来满足,验证脚本立即打脸。

### 工作量均衡

- 接受地理决定的天然差异,spread ≤ 用户给定上限(常见 10–20%)即可。
- 强行均衡密集 cluster 给稀疏 cluster = 路线交叉、总时长反而更长。
- 均衡微调只动**边界节点**(距其他 cluster 质心比当前 cluster 质心更近的),保地理连片。
