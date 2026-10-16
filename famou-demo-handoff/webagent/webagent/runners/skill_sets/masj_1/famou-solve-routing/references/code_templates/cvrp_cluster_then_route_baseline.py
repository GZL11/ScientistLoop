#!/usr/bin/env python3
"""
Baseline template: CVRP via cluster-then-route.
Generic for cvrp_cluster_then_route subtype. ADAPT marked hooks per case.
"""
import math
import json
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Any, Optional


# ADAPT HERE: default parameters; override via kwargs/CSV.
DEFAULT_NUM_VEHICLES = 10
DEFAULT_CAPACITY = 5000.0
DEFAULT_TRUNK_SPEED_KMH = 70.0     # depot <-> first/last customer
DEFAULT_LOCAL_SPEED_KMH = 35.0     # between customers
DEFAULT_SERVICE_TIME_S = 120.0     # per stop


class InfeasibleError(Exception):
    """Raised when the problem cannot be solved feasibly under given constraints."""
    pass


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    """计算两个经纬度坐标之间的球面距离（公里）。"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(a))


def build_dist_matrix(points: List[Dict]) -> np.ndarray:
    """
    构建距离矩阵。

    Args:
        points: 点列表，每个点包含 lon, lat

    Returns:
        np.ndarray: 距离矩阵
    """
    n = len(points)
    M = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(points[i]['lon'], points[i]['lat'],
                             points[j]['lon'], points[j]['lat'])
            M[i, j] = M[j, i] = d
    return M


# Module-level forbidden mapping populated from CSV / kwargs
FORBIDDEN_BY_TYPE: Dict[str, set] = {}


def edge_feasible(u: int, v: int, points: List[Dict], forbidden: set) -> bool:
    """
    检查边 (u, v) 是否可行。

    Args:
        u: 起点索引
        v: 终点索引
        points: 点列表
        forbidden: 禁止边的集合

    Returns:
        bool: 是否可行
    """
    # CONSTRAINT-CHECK: case-specific edge feasibility (segregation/restrictions)
    # forbidden stored as frozenset({u,v}) -> undirected.
    fs = frozenset({u, v})
    if fs in forbidden:
        return False
    # Also check both directional tuples just in case caller stored tuples
    if (u, v) in forbidden or (v, u) in forbidden:
        return False

    # Restriction-type based checks: if either endpoint has a restriction_type
    # that is registered in FORBIDDEN_BY_TYPE, apply it.
    pu = points[u] if 0 <= u < len(points) else {}
    pv = points[v] if 0 <= v < len(points) else {}
    for p_other_idx, p in ((v, pu), (u, pv)):
        rt = p.get('restriction_type') if isinstance(p, dict) else None
        if rt is None:
            continue
        banned = FORBIDDEN_BY_TYPE.get(rt)
        if banned is None:
            # Unknown restriction type -> ban for all (conservative)
            if rt != '' and rt is not False:
                # Only treat as banned-for-all if explicitly flagged unknown
                if rt not in ('', 'none', 'None', None):
                    # Conservative: forbid edge
                    return False
        else:
            if p_other_idx in banned:
                return False
    return True


def route_feasible(route: List[int], points: List[Dict], forbidden: set) -> bool:
    """逐边检查路线是否满足危化品通行约束。"""
    # Check every edge in the route (hop-by-hop), not just at validation.
    for a, b in zip(route[:-1], route[1:]):
        if not edge_feasible(a, b, points, forbidden):
            return False
    return True


def route_load(route: List[int], demands: np.ndarray) -> float:
    """
    计算路线总载重。

    Args:
        route: 路线（索引列表）
        demands: 需求量数组

    Returns:
        float: 总载重
    """
    return float(sum(demands[i] for i in route if i != 0))


def route_time_seconds(route: List[int], dist: np.ndarray,
                       trunk_kmh: float, local_kmh: float, service_s: float) -> float:
    """
    计算路线总时间（秒）。

    Args:
        route: 路线
        dist: 距离矩阵
        trunk_kmh: 干线速度 (km/h)
        local_kmh: 本地速度 (km/h)
        service_s: 每站服务时间（秒）

    Returns:
        float: 总时间（秒）
    """
    # CONSTRAINT-CHECK: travel time uses spec speeds & service time consistently.
    if len(route) < 2:
        return 0.0
    total = 0.0
    for idx in range(len(route) - 1):
        a, b = route[idx], route[idx + 1]
        d = dist[a, b]
        if a == 0 or b == 0:
            total += d / trunk_kmh * 3600.0
        else:
            total += d / local_kmh * 3600.0
    # service time at each non-depot stop
    total += service_s * sum(1 for x in route if x != 0)
    return total


def capacity_aware_kmeans(coords: np.ndarray, demands: np.ndarray,
                          k: int, capacity: float, max_iter: int = 300) -> List[List[int]]:
    """
    容量感知的 K-Means 聚类。

    Args:
        coords: 坐标数组
        demands: 需求量数组
        k: 聚类数量
        capacity: 容量限制
        max_iter: 最大迭代次数

    Returns:
        List[List[int]]: 每个聚类的客户索引列表
    """
    from sklearn.cluster import KMeans
    n = len(coords)
    k = max(1, min(k, n))
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = km.fit_predict(coords)
    clusters = [[] for _ in range(k)]
    for i, lb in enumerate(labels):
        clusters[lb].append(i)
    weights = [sum(demands[i] for i in c) for c in clusters]

    # CONSTRAINT-CHECK: per-vehicle load <= capacity (rebalance overloaded clusters)
    for _ in range(max_iter):
        over = [i for i, w in enumerate(weights) if w > capacity]
        if not over:
            break
        progressed = False
        for ci in over:
            excess = weights[ci] - capacity
            centers = [coords[c].mean(axis=0) if c else np.array([0.0, 0.0]) for c in clusters]
            members = sorted(clusters[ci], key=lambda x: -demands[x])
            for cust in members:
                if excess <= 0:
                    break
                best_t, best_d = -1, float('inf')
                for tj in range(len(clusters)):
                    if tj == ci:
                        continue
                    if weights[tj] + demands[cust] > capacity:
                        continue
                    d = np.linalg.norm(coords[cust] - centers[tj])
                    if d < best_d:
                        best_d, best_t = d, tj
                if best_t >= 0:
                    clusters[ci].remove(cust)
                    clusters[best_t].append(cust)
                    weights[ci] -= demands[cust]
                    weights[best_t] += demands[cust]
                    excess -= demands[cust]
                    progressed = True
        if not progressed:
            break
    return [c for c in clusters if c]


def two_opt(route: List[int], dist: np.ndarray, points: List[Dict],
            forbidden: set, trunk_kmh: float, local_kmh: float, service_s: float) -> List[int]:
    """
    2-opt 局部搜索优化路线。

    Args:
        route: 初始路线
        dist: 距离矩阵
        points: 点列表
        forbidden: 禁止边集合
        trunk_kmh: 干线速度
        local_kmh: 本地速度
        service_s: 服务时间

    Returns:
        List[int]: 优化后的路线
    """
    best = route[:]
    best_t = route_time_seconds(best, dist, trunk_kmh, local_kmh, service_s)
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                # CONSTRAINT-CHECK: edges valid in 2-opt move (filter at every stage)
                if not route_feasible(cand, points, forbidden):
                    continue
                t = route_time_seconds(cand, dist, trunk_kmh, local_kmh, service_s)
                if t + 1e-6 < best_t:
                    best, best_t = cand, t
                    improved = True
    return best


def nearest_neighbor_route(cluster_idx: List[int], dist: np.ndarray,
                           points: List[Dict], forbidden: set) -> Optional[List[int]]:
    """
    使用最近邻算法构建可行路线。

    Args:
        cluster_idx: 聚类内客户索引列表
        dist: 距离矩阵
        points: 点列表
        forbidden: 禁止边集合

    Returns:
        Optional[List[int]]: 可行路线或 None
    """
    # depot index is 0; cluster_idx are point indices (>=1)
    # Returns a feasible route or None if no feasible route can be built.
    route = [0]
    remaining = set(cluster_idx)
    cur = 0
    while remaining:
        nxt, best = -1, float('inf')
        for c in remaining:
            if not edge_feasible(cur, c, points, forbidden):
                continue
            if dist[cur, c] < best:
                best, nxt = dist[cur, c], c
        if nxt < 0:
            # No feasible continuation; signal failure (no silent fallback).
            return None
        route.append(nxt)
        remaining.discard(nxt)
        cur = nxt

    # Verify depot-return feasibility before closing the route
    if not edge_feasible(cur, 0, points, forbidden):
        # Try reordering via constrained 2-opt to find a feasible depot-return tail
        trial = route + [0]
        # Attempt simple swap: try moving any tail customer earlier so cur changes
        for i in range(1, len(route)):
            cand = route[:i] + route[i + 1:] + [route[i]]
            if edge_feasible(cand[-1], 0, points, forbidden):
                full = cand + [0]
                if route_feasible(full, points, forbidden):
                    return full
        return None
    route.append(0)
    return route


def _try_build_route(cluster: List[int], dist: np.ndarray, points: List[Dict],
                     forbidden: set, trunk: float, local: float, service: float) -> Optional[List[int]]:
    """
    尝试构建可行路线。

    Args:
        cluster: 客户索引列表
        dist: 距离矩阵
        points: 点列表
        forbidden: 禁止边集合
        trunk: 干线速度
        local: 本地速度
        service: 服务时间

    Returns:
        Optional[List[int]]: 可行路线或 None
    """
    r = nearest_neighbor_route(cluster, dist, points, forbidden)
    if r is None:
        return None
    r = two_opt(r, dist, points, forbidden, trunk, local, service)
    if not route_feasible(r, points, forbidden):
        return None
    return r


def solve(**kwargs) -> Dict[str, Any]:
    """集群后路由策略求解 CVRP，返回路线结果字典。"""
    # ADAPT HERE: input schema. Expect either `data_file` (CSV) or explicit `points` list.
    data_file = kwargs.get('data_file')
    num_vehicles = int(kwargs.get('num_vehicles', DEFAULT_NUM_VEHICLES))
    capacity = float(kwargs.get('capacity', DEFAULT_CAPACITY))
    trunk = float(kwargs.get('trunk_speed_kmh', DEFAULT_TRUNK_SPEED_KMH))
    local = float(kwargs.get('local_speed_kmh', DEFAULT_LOCAL_SPEED_KMH))
    service = float(kwargs.get('service_time_s', DEFAULT_SERVICE_TIME_S))
    forbidden_edges = set(kwargs.get('forbidden_edges', set()))  # frozenset({u,v}) entries

    # Allow caller to populate FORBIDDEN_BY_TYPE explicitly
    global FORBIDDEN_BY_TYPE
    FORBIDDEN_BY_TYPE = dict(kwargs.get('forbidden_by_type', {}))

    if data_file:
        df = pd.read_csv(data_file)
        # ADAPT HERE: column names. Defaults below; override via kwargs.
        lon_col = kwargs.get('lon_col', '门店经度')
        lat_col = kwargs.get('lat_col', '门店纬度')
        dem_col = kwargs.get('demand_col', '总重量')
        rt_col = kwargs.get('restriction_col', 'restriction_type')
        # row 0 = depot by convention
        def _get_rt(row):
            if rt_col in df.columns:
                v = row[rt_col]
                try:
                    if pd.isna(v):
                        return None
                except Exception:
                    pass
                return v
            return None
        points = [{'id': 0, 'lon': float(df.iloc[0][lon_col]),
                   'lat': float(df.iloc[0][lat_col]), 'demand': 0.0,
                   'restriction_type': _get_rt(df.iloc[0])}]
        for i in range(1, len(df)):
            points.append({'id': i, 'lon': float(df.iloc[i][lon_col]),
                           'lat': float(df.iloc[i][lat_col]),
                           'demand': float(df.iloc[i][dem_col]),
                           'restriction_type': _get_rt(df.iloc[i])})
    else:
        points = kwargs['points']  # list of {id, lon, lat, demand}; index 0 = depot

    n = len(points)
    demands = np.array([p['demand'] for p in points])
    coords = np.array([[p['lon'], p['lat']] for p in points])
    dist = build_dist_matrix(points)

    # Cluster customers (indices 1..n-1)
    cust_idx = list(range(1, n))
    cust_coords = coords[1:]
    cust_demands = demands[1:]
    local_clusters = capacity_aware_kmeans(cust_coords, cust_demands,
                                           num_vehicles, capacity)
    clusters = [[cust_idx[i] for i in c] for c in local_clusters]

    # CONSTRAINT-CHECK: number of routes <= number of vehicles
    # Replace hard truncation with feasibility-aware merging.
    if len(clusters) > num_vehicles:
        clusters.sort(key=lambda c: sum(demands[i] for i in c))
        changed = True
        while len(clusters) > num_vehicles and changed:
            changed = False
            small = clusters[0]
            small_load = sum(demands[i] for i in small)
            # try merging into another cluster respecting capacity AND feasibility
            for j in range(1, len(clusters)):
                target = clusters[j]
                target_load = sum(demands[i] for i in target)
                if target_load + small_load > capacity:
                    continue
                merged = target + small
                trial = _try_build_route(merged, dist, points, forbidden_edges,
                                         trunk, local, service)
                if trial is not None:
                    clusters[j] = merged
                    clusters.pop(0)
                    changed = True
                    break
            if not changed:
                break
        if len(clusters) > num_vehicles:
            raise InfeasibleError(
                f"Cannot fit {len(clusters)} clusters into {num_vehicles} vehicles "
                f"under capacity/edge feasibility constraints."
            )

    # CONSTRAINT-CHECK: per-vehicle load (final guard)
    final_clusters = []
    for c in clusters:
        load = sum(demands[i] for i in c)
        if load > capacity + 1e-6:
            c_sorted = sorted(c, key=lambda x: -demands[x])
            cur, cur_load = [], 0.0
            for x in c_sorted:
                if cur_load + demands[x] > capacity:
                    final_clusters.append(cur); cur, cur_load = [], 0.0
                cur.append(x); cur_load += demands[x]
            if cur:
                final_clusters.append(cur)
        else:
            final_clusters.append(c)

    if len(final_clusters) > num_vehicles:
        # try the same feasibility-aware merge on final_clusters
        final_clusters.sort(key=lambda c: sum(demands[i] for i in c))
        changed = True
        while len(final_clusters) > num_vehicles and changed:
            changed = False
            small = final_clusters[0]
            small_load = sum(demands[i] for i in small)
            for j in range(1, len(final_clusters)):
                target = final_clusters[j]
                target_load = sum(demands[i] for i in target)
                if target_load + small_load > capacity:
                    continue
                merged = target + small
                trial = _try_build_route(merged, dist, points, forbidden_edges,
                                         trunk, local, service)
                if trial is not None:
                    final_clusters[j] = merged
                    final_clusters.pop(0)
                    changed = True
                    break
            if not changed:
                break
        if len(final_clusters) > num_vehicles:
            raise InfeasibleError(
                f"Capacity split produced {len(final_clusters)} clusters; "
                f"cannot fit into {num_vehicles} vehicles."
            )

    clusters = final_clusters

    # Build & optimize routes
    routes: List[List[int]] = []
    unrouted: List[int] = []
    for c in clusters:
        if not c:
            continue
        r = _try_build_route(c, dist, points, forbidden_edges, trunk, local, service)
        if r is None:
            # Could not build a feasible route for this cluster as-is.
            # Mark customers for repair via insertion into other routes.
            unrouted.extend(c)
            continue
        assert r[0] == 0 and r[-1] == 0
        routes.append(r)

    # Repair pass: try to insert unrouted customers into existing routes feasibly.
    def _try_insert(route: List[int], cust: int) -> Optional[List[int]]:
        cur_load = route_load(route, demands)
        if cur_load + demands[cust] > capacity + 1e-9:
            return None
        best_route, best_inc = None, float('inf')
        base_t = route_time_seconds(route, dist, trunk, local, service)
        for pos in range(1, len(route)):
            cand = route[:pos] + [cust] + route[pos:]
            if not route_feasible(cand, points, forbidden_edges):
                continue
            t = route_time_seconds(cand, dist, trunk, local, service)
            inc = t - base_t
            if inc < best_inc:
                best_inc, best_route = inc, cand
        return best_route

    still_unrouted = []
    for m in unrouted:
        placed = False
        # try existing routes ordered by current load (least loaded first)
        order = sorted(range(len(routes)), key=lambda i: route_load(routes[i], demands))
        for ri in order:
            new_r = _try_insert(routes[ri], m)
            if new_r is not None:
                routes[ri] = new_r
                placed = True