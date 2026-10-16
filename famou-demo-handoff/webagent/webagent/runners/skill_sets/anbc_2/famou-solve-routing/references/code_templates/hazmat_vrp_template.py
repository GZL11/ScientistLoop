"""
危化品多约束 VRP 起手模板（子类型 E）
适用:危化品多约束 VRP 风格——多类别车辆 + 路网禁令 + 应急站覆盖 + 风险/费用复合目标

依赖：networkx, scipy
"""
import csv
import math
import numpy as np
import networkx as nx
import pandas as pd


# ── 数据加载 ────────────────────────────────────────────────────────────

def load_data(work_dir):
    """
    加载危化品 VRP 问题数据。

    Args:
        work_dir: 数据目录路径

    Returns:
        (pts, veh, seg, sta, rst) 元组：配送点、车辆、路段、应急站、道路限制
    """
    pts = pd.read_csv(f'{work_dir}/data/delivery_points.csv')
    veh = pd.read_csv(f'{work_dir}/data/vehicles.csv')
    seg = pd.read_csv(f'{work_dir}/data/segments.csv')
    sta = pd.read_csv(f'{work_dir}/data/emergency_stations.csv')
    rst = pd.read_csv(f'{work_dir}/data/road_restrictions.csv')

    # 解析 allowed_classes（分号分隔）
    veh['allowed'] = veh['allowed_classes'].str.split(';')
    return pts, veh, seg, sta, rst


# ── 路网构建（按车型分别构图）──────────────────────────────────────────

def build_graph(seg, rst, exclude=('school_zone',)):
    """
    exclude: 要禁止通行的 restriction_type 集合
    返回有向图（distance + risk 双权重）
    """
    restrict = {(r['from_node'], r['to_node']): r['restriction_type'] for _, r in rst.iterrows()}
    G = nx.DiGraph()
    for _, s in seg.iterrows():
        key = (s['from_node'], s['to_node'])
        rtype = restrict.get(key)
        if rtype in exclude:
            continue
        risk = s['distance_km'] * s['population_density'] * s['risk_multiplier']
        G.add_edge(s['from_node'], s['to_node'],
                   distance=s['distance_km'], risk=risk, restriction=rtype)
    return G


def build_per_class_graphs(seg, rst):
    """各 hazmat_class 对应的可用图。explosive 还要避 blacklist_explosive 段。"""
    graphs = {}
    for cls in ['flammable', 'corrosive', 'toxic']:
        graphs[cls] = build_graph(seg, rst, exclude=('school_zone',))
    graphs['explosive'] = build_graph(seg, rst, exclude=('school_zone', 'blacklist_explosive'))
    return graphs


# ── 最短路矩阵（按车型）────────────────────────────────────────────────

def all_pairs_dist_risk(G, nodes, weight='distance'):
    """
    计算所有节点对之间的距离和风险矩阵。

    Args:
        G: 有向图
        nodes: 节点列表
        weight: 权重属性名

    Returns:
        (D, R, paths) 元组：距离矩阵、风险矩阵、最短路径
    """
    n = len(nodes); idx = {n: i for i, n in enumerate(nodes)}
    D = np.full((n, n), np.inf); R = np.full((n, n), np.inf)
    paths = {}
    for src in nodes:
        try:
            lengths, parents = nx.single_source_dijkstra(G, src, weight=weight)
        except nx.NodeNotFound:
            continue
        for dst, p in parents.items():
            if dst not in idx:
                continue
            D[idx[src], idx[dst]] = lengths[dst]
            risk_sum = 0.0
            for k in range(len(p) - 1):
                risk_sum += G[p[k]][p[k + 1]]['risk']
            R[idx[src], idx[dst]] = risk_sum
            paths[(src, dst)] = p
    return D, R, paths


# ── 装载与路线（贪心兼容性 + NN + 2-opt）──────────────────────────────

def assign_nodes_to_vehicles(pts, veh, capacity=25):
    """
    按 hazmat_class 分组并分配节点到兼容车辆。

    Args:
        pts: 配送点 DataFrame
        veh: 车辆 DataFrame
        capacity: 默认容量

    Returns:
        dict: 每辆车的分配信息
    """
    """按 hazmat_class 分组 → 兼容车辆 → 贪心装载（同车单一类别）"""
    pts_by_class = {c: pts[pts['hazmat_class'] == c].sort_values('demand_tons', ascending=False)
                    for c in pts['hazmat_class'].unique()}
    veh_by_class = {c: [v for _, v in veh.iterrows() if c in v['allowed']]
                    for c in pts['hazmat_class'].unique()}
    assignments = {row['vehicle']: {'class': None, 'nodes': [], 'load': 0.0}
                   for _, row in veh.iterrows()}

    for cls, points in pts_by_class.items():
        cands = veh_by_class[cls]
        for _, p in points.iterrows():
            # 选剩余容量最大的兼容车（已用过同类的优先）
            cands_sorted = sorted(
                cands,
                key=lambda v: (
                    0 if assignments[v['vehicle']]['class'] in (None, cls) else 1,
                    -(capacity - assignments[v['vehicle']]['load']),
                ),
            )
            for v in cands_sorted:
                a = assignments[v['vehicle']]
                if a['class'] not in (None, cls):
                    continue
                if a['load'] + p['demand_tons'] > capacity:
                    continue
                a['class'] = cls
                a['nodes'].append(int(p['node']))
                a['load'] += float(p['demand_tons'])
                break
            else:
                raise RuntimeError(f"Node {p['node']} ({cls}) 无车可装")
    return assignments


def nearest_neighbor_route(D, idx_of, member_nodes, depot=0):
    """
    使用最近邻算法构造路线。

    Args:
        D: 距离矩阵
        idx_of: 节点到索引的映射
        member_nodes: 客户节点集合
        depot: 仓库节点

    Returns:
        list: 路线（含仓库）
    """
    cur = depot; tour = [depot]
    remaining = set(member_nodes)
    while remaining:
        nxt = min(remaining, key=lambda n: D[idx_of[cur], idx_of[n]])
        tour.append(nxt); remaining.remove(nxt); cur = nxt
    tour.append(depot)
    return tour


def two_opt(tour, D, idx_of, max_iter=200):
    """
    2-opt 局部搜索优化路线。

    Args:
        tour: 当前路线
        D: 距离矩阵
        idx_of: 节点到索引的映射
        max_iter: 最大迭代次数

    Returns:
        list: 优化后的路线
    """
    improved = True; iters = 0
    while improved and iters < max_iter:
        improved = False; iters += 1
        for i in range(1, len(tour) - 2):
            for j in range(i + 1, len(tour) - 1):
                a, b = idx_of[tour[i - 1]], idx_of[tour[i]]
                c, d = idx_of[tour[j]], idx_of[tour[j + 1]]
                if D[a, b] + D[c, d] > D[a, c] + D[b, d] + 1e-9:
                    tour[i:j + 1] = tour[i:j + 1][::-1]
                    improved = True
    return tour


# ── 时间窗口（含强制休息）──────────────────────────────────────────────

def total_time_h(driving_dist_km, speed_kph=40, mandatory_rest_per_km=160, rest_h=0.5):
    """
    计算总行驶时间（含强制休息）。

    Args:
        driving_dist_km: 行驶距离（km）
        speed_kph: 行驶速度（km/h）
        mandatory_rest_per_km: 强制休息间隔（km）
        rest_h: 每次休息时长（小时）

    Returns:
        float: 总时间（小时）
    """
    travel = driving_dist_km / speed_kph
    rests = math.floor(driving_dist_km / mandatory_rest_per_km) * rest_h
    return travel + rests


# ── 应急站覆盖检查 ─────────────────────────────────────────────────────

def emergency_coverage(routes, pts, sta, radius=25):
    """检查路线对应急站的覆盖情况。"""
    pts_xy = {int(r['node']): (r['x'], r['y']) for _, r in pts.iterrows()}
    covered = set()
    for route in routes:
        for n in route['nodes']:
            if n == 0:
                continue
            for _, s in sta.iterrows():
                d = math.hypot(pts_xy[n][0] - s['x'], pts_xy[n][1] - s['y'])
                if d <= radius:
                    covered.add(s['station_id'])
    return covered


# ── 主流程 ──────────────────────────────────────────────────────────────

def solve(work_dir, capacity=25, time_limit_h=10, risk_limit=1500):
    """危化品 VRP 主流程：加载数据、建图、求解、验证并输出结果。"""
    pts, veh, seg, sta, rst = load_data(work_dir)
    pts_with_demand = pts[pts['demand_tons'] > 0]

    graphs = build_per_class_graphs(seg, rst)
    nodes_all = [0] + list(pts_with_demand['node'].astype(int))
    idx_of = {n: i for i, n in enumerate(nodes_all)}

    # 各类别预计算最短路矩阵
    D_by_class, R_by_class, P_by_class = {}, {}, {}
    for cls, G in graphs.items():
        D_by_class[cls], R_by_class[cls], P_by_class[cls] = all_pairs_dist_risk(G, nodes_all)

    # 贪心装载
    assignments = assign_nodes_to_vehicles(pts_with_demand, veh, capacity=capacity)

    # 每车构造路线（NN + 2-opt）
    routes = []
    for vid, info in assignments.items():
        if not info['nodes']:
            continue
        cls = info['class']
        D = D_by_class[cls]; R = R_by_class[cls]
        tour = nearest_neighbor_route(D, idx_of, info['nodes'], depot=0)
        tour = two_opt(tour, D, idx_of)
        # 汇总
        dist = sum(D[idx_of[tour[i]], idx_of[tour[i + 1]]] for i in range(len(tour) - 1))
        risk = sum(R[idx_of[tour[i]], idx_of[tour[i + 1]]] for i in range(len(tour) - 1))
        routes.append({
            'vehicle': vid,
            'hazmat_class': cls,
            'nodes': tour,
            'load_tons': info['load'],
            'distance_km': dist,
            'risk': risk,
            'time_h': total_time_h(dist),
            'mileage_cost': dist,                       # 1 $/km
            'risk_penalty': 50 * risk,                  # 50 $/单位
            'insurance':    0.5 * risk,                 # 0.5 $/单位
            'total_cost':   dist + 51.5 * risk,
        })
    return routes, sta, pts


# ── 验证 ────────────────────────────────────────────────────────────────

def validate(routes, pts, sta, capacity=25, risk_limit=1500, time_limit_h=10):
    """校验路线的可行性（载重、风险、时间限制），返回问题列表。"""
    issues = []
    visited = []
    for r in routes:
        for n in r['nodes']:
            if n != 0:
                visited.append(n)
        if r['load_tons'] > capacity + 1e-6:
            issues.append(f"V{r['vehicle']}: 超载 {r['load_tons']:.2f} > {capacity}")
        if r['risk'] > risk_limit + 1e-6:
            issues.append(f"V{r['vehicle']}: 风险 {r['risk']:.2f} > {risk_limit}")
        if r['time_h'] > time_limit_h + 1e-6:
            issues.append(f"V{r['vehicle']}: 时长 {r['time_h']:.2f}h > {time_limit_h}h")
    expected = set(pts[pts['demand_tons'] > 0]['node'].astype(int))
    missing = expected - set(visited)
    duplicates = [n for n in visited if visited.count(n) > 1]
    if missing:
        issues.append(f'漏访问节点: {sorted(missing)}')
    if duplicates:
        issues.append(f'重复访问节点: {set(duplicates)}')
    cov = emergency_coverage(routes, pts, sta)
    if cov != set(sta['station_id']):
        issues.append(f'应急站未覆盖: {set(sta["station_id"]) - cov}')
    return issues


if __name__ == '__main__':
    work_dir = '.'
    routes, sta, pts = solve(work_dir)
    issues = validate(routes, pts, sta)
    if issues:
        print('约束违反：')
        for it in issues:
            print(' -', it)
    else:
        print('全部硬约束满足')
    total = sum(r['total_cost'] for r in routes)
    print(f'总费用: {total:.2f}')
