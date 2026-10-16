"""
TSP / 多实例 TSP 起手模板（子类型 A）
适用：纯 TSP、多独立实例（每实例单车）
"""
import numpy as np
import pandas as pd
import time
import random


# ── 距离矩阵 ────────────────────────────────────────────────────────────

def build_distance_matrix(coords):
    """coords: (n, 2) array of (x, y) 平面坐标，欧式距离"""
    from scipy.spatial.distance import cdist
    return cdist(coords, coords)


# ── NN 构造（向量化）───────────────────────────────────────────────────

def nearest_neighbor(dist, start=0):
    n = len(dist)
    visited = np.zeros(n, dtype=bool)
    tour = [start]; visited[start] = True
    cur = start
    for _ in range(n - 1):
        d = dist[cur].copy(); d[visited] = np.inf
        nxt = int(np.argmin(d))
        tour.append(nxt); visited[nxt] = True
        cur = nxt
    return tour


def multi_start_nn(dist, n_starts=10, seed=42):
    rng = random.Random(seed)
    n = len(dist)
    best_tour, best_len = None, float('inf')
    starts = rng.sample(range(n), min(n_starts, n))
    for s in starts:
        t = nearest_neighbor(dist, s)
        L = tour_length(t, dist)
        if L < best_len:
            best_len, best_tour = L, t
    return best_tour, best_len


# ── 总长度（含闭合段）─────────────────────────────────────────────────

def tour_length(tour, dist):
    return float(sum(dist[tour[i], tour[(i + 1) % len(tour)]] for i in range(len(tour))))


# ── 2-opt 限邻域 ────────────────────────────────────────────────────────

def two_opt_limited(tour, dist, k=30, max_seconds=60):
    n = len(tour)
    if n < 4:
        return tour
    neigh = np.argsort(dist, axis=1)[:, :k]
    pos = np.empty(n, dtype=int); pos[tour] = np.arange(n)
    tour_arr = np.array(tour, dtype=int)
    deadline = time.time() + max_seconds
    improved = True
    while improved:
        improved = False
        for ii in range(n - 1):
            a = int(tour_arr[ii]); b = int(tour_arr[ii + 1])
            for c in neigh[a]:
                c = int(c)
                if c == a or c == b:
                    continue
                jj = int(pos[c])
                if jj <= ii + 1:
                    continue
                d = int(tour_arr[(jj + 1) % n])
                gain = dist[a, b] + dist[c, d] - dist[a, c] - dist[b, d]
                if gain > 1e-9:
                    tour_arr[ii + 1:jj + 1] = tour_arr[ii + 1:jj + 1][::-1]
                    pos[tour_arr] = np.arange(n)
                    improved = True
                    break
            if time.time() > deadline:
                return tour_arr.tolist()
    return tour_arr.tolist()


# ── ILS：扰动（random 3-opt） + 2-opt ──────────────────────────────────

def perturb_3opt(tour):
    n = len(tour)
    if n < 6:
        return tour[:]
    i, j, k = sorted(random.sample(range(n), 3))
    return tour[:i] + tour[j:k] + tour[i:j] + tour[k:]


def solve_tsp(coords, total_time=60, seed=42):
    """coords: (n, 2) array. 返回 (tour, total_distance)."""
    random.seed(seed); np.random.seed(seed)
    dist = build_distance_matrix(coords)
    start = time.time()
    tour, L = multi_start_nn(dist, n_starts=10, seed=seed)
    print(f'  NN init: L={L:.4f}')
    tour = two_opt_limited(tour, dist, k=30, max_seconds=total_time * 0.4)
    L = tour_length(tour, dist)
    print(f'  After 2-opt: L={L:.4f} (t={time.time()-start:.1f}s)')

    best = tour[:]; best_L = L; no_imp = 0
    while time.time() - start < total_time - 1:
        cand = perturb_3opt(best)
        cand = two_opt_limited(cand, dist, k=30,
                               max_seconds=min(10, total_time - (time.time() - start)))
        cL = tour_length(cand, dist)
        if cL < best_L - 1e-9:
            best_L, best = cL, cand
            no_imp = 0
            print(f'  ILS improved: L={best_L:.4f} (t={time.time()-start:.1f}s)')
        else:
            no_imp += 1
            if no_imp >= 8:
                break
    return best, best_L


# ── 多实例处理 ─────────────────────────────────────────────────────────

def solve_multi_instance(df, instance_col='instance_id', x_col='x', y_col='y',
                          time_per_instance=30, source_label=''):
    """
    df: DataFrame with columns instance_id, city_id, x, y
    返回 list of dict {instance_source, instance_id, total_distance, route}
    """
    out = []
    for inst_id, sub in df.groupby(instance_col):
        sub = sub.sort_values('city_id').reset_index(drop=True)
        coords = sub[[x_col, y_col]].values
        cid = sub['city_id'].values
        print(f'[Instance {inst_id}] n={len(sub)}')
        tour, L = solve_tsp(coords, total_time=time_per_instance)
        # 旋转到从 city_id=1 出发(常见默认)
        start_idx = int(np.where(cid == 1)[0][0])
        si = tour.index(start_idx)
        tour = tour[si:] + tour[:si]
        out.append({
            'instance_source': source_label,
            'instance_id': inst_id,
            'total_distance': L,
            'route': [int(cid[i]) for i in tour] + [int(cid[tour[0]])]   # 闭合
        })
    return out


if __name__ == '__main__':
    # 示例:多实例 TSP(每个 instance 独立坐标系)
    df_large = pd.read_csv('data/instance_cities.csv')
    df_small = pd.read_csv('data/instance_small_cities.csv')

    results = []
    results += solve_multi_instance(df_large, source_label='instance_cities',
                                     time_per_instance=30)
    results += solve_multi_instance(df_small, source_label='instance_small_cities',
                                     time_per_instance=60)

    # 写结果
    summary = pd.DataFrame([{'instance_source': r['instance_source'],
                              'instance_id':    r['instance_id'],
                              'total_distance': round(r['total_distance'], 6)}
                             for r in results])
    summary.to_csv('tsp_results.csv', index=False)

    rows = []
    for r in results:
        for step, city in enumerate(r['route'], 1):
            rows.append({'instance_source': r['instance_source'],
                         'instance_id':    r['instance_id'],
                         'step':           step,
                         'city_id':        city})
    pd.DataFrame(rows).to_csv('tsp_routes.csv', index=False)
    print('Done.')
