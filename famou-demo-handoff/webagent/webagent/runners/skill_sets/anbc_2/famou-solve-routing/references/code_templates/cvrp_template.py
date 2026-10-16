"""
CVRP 起手模板（子类型 C）
适用:城市配送 CVRP 风格——多车载重 + 工作量均衡 + 经纬度 Haversine 距离
"""
import csv
import time
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from scipy.spatial.distance import cdist


# ── 数据加载(按用户提供的字段名调整)──────────────────────────────────────

def load_nodes(filepath, lon_col='门店经度', lat_col='门店纬度',
               demand_col='总重量', id_col='网点编码', depot_id=0):
    """
    第一行通常是仓库（demand 空或仓库 id）；其他行是客户。
    返回 depot dict, customers list of dict
    """
    df = pd.read_csv(filepath)
    df[demand_col] = pd.to_numeric(df[demand_col], errors='coerce').fillna(0)
    depot_row = df[df[id_col] == depot_id].iloc[0]
    customers = df[(df[id_col] != depot_id) & (df[demand_col] > 0)].copy()
    depot = {'id': int(depot_row[id_col]),
             'lon': float(depot_row[lon_col]),
             'lat': float(depot_row[lat_col]),
             'demand': 0}
    cust_list = [{'id': int(r[id_col]),
                   'lon': float(r[lon_col]),
                   'lat': float(r[lat_col]),
                   'demand': float(r[demand_col])} for _, r in customers.iterrows()]
    return depot, cust_list


# ── Haversine 距离矩阵（向量化）─────────────────────────────────────────

def haversine_matrix(coords_lon_lat):
    """
    计算 Haversine 距离矩阵。

    Args:
        coords_lon_lat: (n, 2) ndarray 经度、纬度

    Returns:
        (n, n) ndarray: 距离矩阵，单位 km
    """
    R = 6371.0
    lon = np.radians(coords_lon_lat[:, 0])
    lat = np.radians(coords_lon_lat[:, 1])
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# ── 容量感知 K-Means ────────────────────────────────────────────────────

def cluster_with_capacity(customers, n_vehicles, vehicle_capacity, n_init=20, seed_base=0):
    """
    容量感知的 K-Means 聚类。

    Args:
        customers: 客户列表
        n_vehicles: 车辆数量
        vehicle_capacity: 车辆容量
        n_init: 初始化次数
        seed_base: 随机种子基础值

    Returns:
        np.ndarray: 每个客户的聚类标签
    """
    coords = np.array([[c['lon'], c['lat']] for c in customers])
    demands = np.array([c['demand'] for c in customers])
    best_labels = None
    best_imbalance = float('inf')
    for s in range(n_init):
        km = KMeans(n_clusters=n_vehicles, random_state=seed_base + s, n_init=1)
        labels = km.fit_predict(coords)
        loads = np.array([demands[labels == k].sum() for k in range(n_vehicles)])
        if (loads <= vehicle_capacity).all() and (loads > 0).all():
            imb = float(loads.std())
            if imb < best_imbalance:
                best_imbalance, best_labels = imb, labels.copy()
    if best_labels is None:
        # 退化：跑一次默认 + 强制超载修复
        km = KMeans(n_clusters=n_vehicles, random_state=seed_base, n_init=10)
        best_labels = km.fit_predict(coords)
        best_labels = fix_overload(best_labels, customers, demands,
                                   n_vehicles, vehicle_capacity)
    return best_labels


def fix_overload(labels, customers, demands, n_vehicles, vehicle_capacity, max_iter=2000):
    """
    修复超载的聚类标签。

    Args:
        labels: 当前聚类标签
        customers: 客户列表
        demands: 需求量数组
        n_vehicles: 车辆数量
        vehicle_capacity: 车辆容量
        max_iter: 最大迭代次数

    Returns:
        np.ndarray: 修复后的聚类标签
    """
    coords = np.array([[c['lon'], c['lat']] for c in customers])
    for _ in range(max_iter):
        loads = np.array([demands[labels == k].sum() for k in range(n_vehicles)])
        over = np.where(loads > vehicle_capacity)[0]
        if len(over) == 0:
            break
        k = int(over[0])
        members = np.where(labels == k)[0]
        heaviest = int(members[np.argmax(demands[members])])
        # 找最近的未满 cluster
        centers = np.array([coords[labels == j].mean(axis=0)
                             if (labels == j).any() else np.array([np.nan, np.nan])
                             for j in range(n_vehicles)])
        d = np.linalg.norm(centers - coords[heaviest], axis=1)
        d[k] = np.inf
        for tgt in np.argsort(d):
            if loads[tgt] + demands[heaviest] <= vehicle_capacity:
                labels[heaviest] = int(tgt)
                break
        else:
            break
    return labels


# ── NN + 2-opt 限邻域 ──────────────────────────────────────────────────

def nearest_neighbor_in_cluster(member_indices, dist_matrix, depot_idx=0):
    """
    在单个 cluster 内使用最近邻算法构造路线。

    Args:
        member_indices: cluster 内的客户索引列表
        dist_matrix: 距离矩阵
        depot_idx: 仓库索引

    Returns:
        list: 路线（客户索引序列）
    """
    unvisited = list(member_indices)
    cur = depot_idx
    tour = []
    while unvisited:
        nxt = min(unvisited, key=lambda n: dist_matrix[cur, n])
        tour.append(nxt); unvisited.remove(nxt); cur = nxt
    return tour


def two_opt_limited(tour, dist_matrix, k=30, max_seconds=30):
    """
    限邻域 2-opt 局部搜索。

    Args:
        tour: 当前路线
        dist_matrix: 距离矩阵
        k: 考虑的最近邻数目
        max_seconds: 时间限制

    Returns:
        list: 优化后的路线
    """
    n = len(tour)
    if n < 4:
        return tour
    neigh = np.argsort(dist_matrix, axis=1)[:, :k + 1]
    pos = np.empty(dist_matrix.shape[0], dtype=int)
    pos[tour] = np.arange(n)
    deadline = time.time() + max_seconds
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            a = tour[i]; b = tour[i + 1]
            for c in neigh[a]:
                c = int(c)
                if c == a or c == b or c not in pos:
                    continue
                if pos[c] >= n or pos[c] <= i + 1:
                    continue
                j = int(pos[c])
                d = tour[(j + 1) % n] if (j + 1) < n else tour[0]
                gain = dist_matrix[a, b] + dist_matrix[c, d] - dist_matrix[a, c] - dist_matrix[b, d]
                if gain > 1e-9:
                    tour[i + 1:j + 1] = tour[i + 1:j + 1][::-1]
                    pos[tour] = np.arange(n)
                    improved = True
                    break
            if time.time() > deadline:
                return tour
    return tour


# ── 路线时间估算(典型城市配送口径,具体速度/服务时间以问题描述为准)────────

def estimate_route_time_min(tour, dist_matrix, depot_idx, mainline_kph=70,
                             intra_kph=35, service_sec=120):
    """tour: 客户索引序列（不含仓库）。返回总时长（分钟）。"""
    if not tour:
        return 0.0
    mainline_to_first = dist_matrix[depot_idx, tour[0]] / mainline_kph
    last_to_depot = dist_matrix[tour[-1], depot_idx] / mainline_kph
    intra = sum(dist_matrix[tour[i], tour[i + 1]] for i in range(len(tour) - 1)) / intra_kph
    travel_h = mainline_to_first + intra + last_to_depot
    service_h = len(tour) * service_sec / 3600
    return (travel_h + service_h) * 60


def total_distance_km(tour, dist_matrix, depot_idx):
    """
    计算路线总距离（km）。

    Args:
        tour: 路线（不含仓库）
        dist_matrix: 距离矩阵
        depot_idx: 仓库索引

    Returns:
        float: 总距离
    """
    if not tour:
        return 0.0
    return float(dist_matrix[depot_idx, tour[0]]
                 + sum(dist_matrix[tour[i], tour[i + 1]] for i in range(len(tour) - 1))
                 + dist_matrix[tour[-1], depot_idx])


# ── 工作量均衡微调（边界节点交换）──────────────────────────────────────

def balance_routes(routes, dist_matrix, customers, vehicle_capacity, depot_idx,
                   target_spread=0.20, max_iter=200):
    """
    routes: list[list[int]]，每条路线是 customers 在 dist_matrix 中的索引序列
    """
    for _ in range(max_iter):
        times = [estimate_route_time_min(r, dist_matrix, depot_idx) for r in routes]
        spread = (max(times) - min(times)) / max(times) if max(times) > 0 else 0
        if spread <= target_spread:
            break
        busy = int(np.argmax(times)); idle = int(np.argmin(times))
        if busy == idle or len(routes[busy]) <= 1:
            break
        # busy 路线的边界节点（距 idle 路线质心近的）
        idle_centroid = np.mean([[customers[i - 1]['lon'], customers[i - 1]['lat']]
                                  for i in routes[idle]], axis=0)
        best_node = None; best_d = float('inf')
        for n in routes[busy]:
            c = customers[n - 1]
            d = (c['lon'] - idle_centroid[0]) ** 2 + (c['lat'] - idle_centroid[1]) ** 2
            if d < best_d:
                # 检查转移后 idle 不超载
                idle_load = sum(customers[i - 1]['demand'] for i in routes[idle])
                if idle_load + customers[n - 1]['demand'] <= vehicle_capacity:
                    best_node, best_d = n, d
        if best_node is None:
            break
        routes[busy].remove(best_node)
        # 插入 idle 路线最佳位置
        best_pos = 0; best_inc = float('inf')
        for p in range(len(routes[idle]) + 1):
            tour_test = routes[idle][:p] + [best_node] + routes[idle][p:]
            inc = total_distance_km(tour_test, dist_matrix, depot_idx)
            if inc < best_inc:
                best_inc, best_pos = inc, p
        routes[idle].insert(best_pos, best_node)
        routes[idle] = two_opt_limited(routes[idle], dist_matrix, k=30, max_seconds=5)
        routes[busy] = two_opt_limited(routes[busy], dist_matrix, k=30, max_seconds=5)
    return routes


# ── 主流程 ──────────────────────────────────────────────────────────────

def solve_cvrp(depot, customers, n_vehicles, vehicle_capacity, total_time=240):
    """使用聚类+最近邻+2-opt 求解 CVRP 问题。"""
    start = time.time()
    all_nodes = [depot] + customers
    coords = np.array([[n['lon'], n['lat']] for n in all_nodes])
    dist = haversine_matrix(coords)        # km
    depot_idx = 0
    cust_indices = list(range(1, len(all_nodes)))

    # 阶段 1：聚类
    labels = cluster_with_capacity(customers, n_vehicles, vehicle_capacity, n_init=20)
    print(f'Cluster done, t={time.time() - start:.1f}s')

    # 阶段 2：每 cluster NN + 2-opt
    routes = [[] for _ in range(n_vehicles)]
    for k in range(n_vehicles):
        members = [cust_indices[i] for i, l in enumerate(labels) if l == k]
        if not members:
            continue
        tour = nearest_neighbor_in_cluster(members, dist, depot_idx)
        budget = max(5, (total_time * 0.3) / max(1, n_vehicles))
        tour = two_opt_limited(tour, dist, k=30, max_seconds=budget)
        routes[k] = tour
    print(f'NN+2opt done, t={time.time() - start:.1f}s')

    # 阶段 3：均衡
    routes = balance_routes(routes, dist, customers, vehicle_capacity, depot_idx)
    print(f'Balance done, t={time.time() - start:.1f}s')

    return routes, dist


# ── 验证 ────────────────────────────────────────────────────────────────

def validate(routes, customers, vehicle_capacity, dist, depot_idx):
    """校验路线的可行性，返回问题列表。"""
    issues = []
    visited = []
    for k, r in enumerate(routes):
        if not r:
            issues.append(f'V{k+1}: 空路线(若要求"全部投入"则不允许)')
            continue
        load = sum(customers[i - 1]['demand'] for i in r)
        if load > vehicle_capacity + 1e-6:
            issues.append(f'V{k+1}: 超载 {load:.1f} > {vehicle_capacity}')
        for n in r:
            visited.append(n)
    expected = set(range(1, len(customers) + 1))
    missing = expected - set(visited)
    duplicates = [n for n in visited if visited.count(n) > 1]
    if missing:
        issues.append(f'漏访问 {len(missing)} 个网点')
    if duplicates:
        issues.append(f'重复访问 {len(set(duplicates))} 个网点')
    times = [estimate_route_time_min(r, dist, depot_idx) for r in routes if r]
    if times:
        spread = (max(times) - min(times)) / max(times)
        print(f'工作量 spread = {spread:.1%}')
    return issues


if __name__ == '__main__':
    depot, customers = load_nodes('data/customers.csv')
    n_vehicles = 12; capacity = 7125
    routes, dist = solve_cvrp(depot, customers, n_vehicles, capacity, total_time=240)
    issues = validate(routes, customers, capacity, dist, depot_idx=0)
    if issues:
        print('VIOLATIONS:')
        for it in issues:
            print(' -', it)
    else:
        print('All hard constraints OK')
    # 写 CSV ——按用户提供的字段名(此处示例为中文)
    rows_detail = []
    rows_summary = []
    for k, r in enumerate(routes, 1):
        if not r:
            continue
        load = sum(customers[i - 1]['demand'] for i in r)
        d_km = total_distance_km(r, dist, depot_idx=0)
        t_min = estimate_route_time_min(r, dist, depot_idx=0)
        rows_summary.append({'车辆编号': k, '网点数量': len(r),
                             '货物总重量(kg)': round(load, 2),
                             '路线总距离(km)': round(d_km, 2),
                             '总配送时长(分钟)': round(t_min, 1)})
        for seq, idx in enumerate(r, 1):
            c = customers[idx - 1]
            rows_detail.append({'车辆编号': k, '网点编码': c['id'], '访问顺序': seq,
                                '门店经度': c['lon'], '门店纬度': c['lat'],
                                '总重量': c['demand']})
    pd.DataFrame(rows_detail).to_csv('routes_result.csv', index=False)
    pd.DataFrame(rows_summary).to_csv('route_summary.csv', index=False)
    print('Done.')
