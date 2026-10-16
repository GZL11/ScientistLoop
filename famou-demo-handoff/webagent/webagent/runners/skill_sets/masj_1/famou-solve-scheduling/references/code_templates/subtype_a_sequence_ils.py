"""
子类型 A — 单机序列优化（ILS）起手模板
适用：aircraft landing, single machine scheduling, 惩罚最小化
"""
import csv, math, random, time
import numpy as np

# ── 1. 数据加载（按实际字段名修改）──────────────────────────────────────────

def load_data(tasks_path, sep_path=None):
    """加载任务数据和间隔矩阵"""
    tasks = []
    with open(tasks_path) as f:
        for row in csv.DictReader(f):
            tasks.append({
                'id':       int(row['task_id']),
                'earliest': int(row['earliest']),
                'target':   int(row['target']),
                'latest':   int(row['latest']),
                'pen_early': float(row['penalty_early']),
                'pen_late':  float(row['penalty_late']),
            })
    n = len(tasks)
    sep = np.zeros((n, n), dtype=np.int32)
    if sep_path:
        with open(sep_path) as f:
            for i, row in enumerate(csv.DictReader(f)):
                for j in range(n):
                    sep[i, j] = int(row[f'sep_{j+1}'])
    return tasks, sep

def build_arrays(tasks):
    """将任务列表转换为 numpy 数组以加速计算。"""
    n = len(tasks)
    earliest = np.array([t['earliest'] for t in tasks], dtype=np.int64)
    target   = np.array([t['target']   for t in tasks], dtype=np.int64)
    latest   = np.array([t['latest']   for t in tasks], dtype=np.int64)
    pe       = np.array([t['pen_early'] for t in tasks], dtype=np.float64)
    pl       = np.array([t['pen_late']  for t in tasks], dtype=np.float64)
    return earliest, target, latest, pe, pl

# ── 2. 调度评估（向量化）────────────────────────────────────────────────────

def compute_times(order, earliest, latest, sep):
    """按给定顺序计算各任务的实际执行时间。"""
    n = len(order)
    times = np.zeros(n, dtype=np.int64)
    t = int(earliest[order[0]])
    times[0] = t
    for k in range(1, n):
        idx = order[k]
        min_t = int(times[k - 1]) + int(sep[order[k - 1], idx])
        t = max(int(earliest[idx]), min_t)
        if t > int(latest[idx]):
            return times, False
        times[k] = t
    return times, True

def compute_cost(order, times, target, pe, pl):
    """计算给定调度方案的加权惩罚代价。"""
    dev = times - target[order]
    early = np.where(dev < 0, -dev, 0)
    late  = np.where(dev > 0,  dev, 0)
    return float(np.dot(pe[order], early) + np.dot(pl[order], late))

def total_cost(order, earliest, latest, target, pe, pl, sep):
    """计算给定顺序的总代价，不可行时返回 inf。"""
    times, feasible = compute_times(order, earliest, latest, sep)
    if not feasible:
        return math.inf
    return compute_cost(order, times, target, pe, pl)

# ── 3. 初始解────────────────────────────────────────────────────────────────

def greedy_initial(tasks):
    """
    基于目标时间最早的贪心初始解。

    Args:
        tasks: 任务列表

    Returns:
        np.ndarray: 按 target 排序的索引数组
    """
    return np.array(sorted(range(len(tasks)), key=lambda i: tasks[i]['target']), dtype=np.int32)

# ── 4. 局部搜索：swap────────────────────────────────────────────────────────

def swap_pass(order, earliest, latest, target, pe, pl, sep, deadline, start):
    """
    Swap 局部搜索：通过交换 pair 寻找更优解。

    Args:
        order: 当前解
        earliest/latest/target/pe/pl/sep: 问题数据
        deadline: 时间限制
        start: 开始时间

    Returns:
        (best, best_cost): 最优解及代价
    """
    n = len(order)
    best = order.copy()
    best_cost = total_cost(best, earliest, latest, target, pe, pl, sep)
    improved = True
    while improved and time.time() - start < deadline:
        improved = False
        for i in range(n - 1):
            if time.time() - start > deadline:
                break
            for j in range(i + 1, min(i + 30, n)):
                new = best.copy()
                new[i], new[j] = new[j], new[i]
                c = total_cost(new, earliest, latest, target, pe, pl, sep)
                if c < best_cost - 1e-9:
                    best_cost, best = c, new
                    improved = True
                    break
            if improved:
                break
    return best, best_cost

# ── 5. 局部搜索：or-opt (单任务重定位)────────────────────────────────────────

def or_opt_pass(order, earliest, latest, target, pe, pl, sep, deadline, start):
    """
    Or-opt 局部搜索：移动单个任务到新位置。

    Args:
        order: 当前解
        earliest/latest/target/pe/pl/sep: 问题数据
        deadline: 时间限制
        start: 开始时间

    Returns:
        (best, best_cost): 最优解及代价
    """
    n = len(order)
    best = order.copy()
    best_cost = total_cost(best, earliest, latest, target, pe, pl, sep)
    improved = True
    while improved and time.time() - start < deadline:
        improved = False
        positions = list(range(n))
        random.shuffle(positions)
        for i in positions:
            if time.time() - start > deadline:
                break
            plane = best[i]
            candidate = np.delete(best, i)
            for j in range(len(candidate) + 1):
                new_order = np.insert(candidate, j, plane)
                c = total_cost(new_order, earliest, latest, target, pe, pl, sep)
                if c < best_cost - 1e-9:
                    best_cost, best = c, new_order
                    improved = True
                    break
            if improved:
                break
    return best, best_cost

# ── 6. ILS 主循环────────────────────────────────────────────────────────────

def solve(tasks, sep, total_time=280.0):
    """使用 ILS 算法求解单机序列调度问题。"""
    start = time.time()
    earliest, target, latest, pe, pl = build_arrays(tasks)

    order = greedy_initial(tasks)
    best_cost = total_cost(order, earliest, latest, target, pe, pl, sep)
    best = order.copy()
    print(f"Initial: {best_cost:.2f} (t={time.time()-start:.1f}s)")

    # 阶段1：swap
    order, cost = swap_pass(order, earliest, latest, target, pe, pl, sep,
                            deadline=start + total_time * 0.20, start=start)
    if cost < best_cost:
        best_cost, best = cost, order.copy()
    print(f"After swap: {best_cost:.2f} (t={time.time()-start:.1f}s)")

    # 阶段2：or-opt
    order, cost = or_opt_pass(best, earliest, latest, target, pe, pl, sep,
                              deadline=start + total_time * 0.55, start=start)
    if cost < best_cost:
        best_cost, best = cost, order.copy()
    print(f"After or-opt: {best_cost:.2f} (t={time.time()-start:.1f}s)")

    # 阶段3：ILS 扰动重启
    no_improve = 0
    while time.time() - start < total_time - 3:
        remaining = total_time - (time.time() - start)
        if remaining < 5:
            break
        k = 3 if no_improve < 5 else random.randint(5, 12)
        # 扰动：随机翻转 k 段
        perturbed = best.copy()
        n = len(perturbed)
        for _ in range(k):
            i, j = sorted(random.sample(range(n), 2))
            perturbed[i:j + 1] = perturbed[i:j + 1][::-1]

        p, pc = swap_pass(perturbed, earliest, latest, target, pe, pl, sep,
                          deadline=start + (time.time() - start) + min(20, remaining * 0.35), start=start)
        p, pc = or_opt_pass(p, earliest, latest, target, pe, pl, sep,
                            deadline=start + (time.time() - start) + min(12, remaining * 0.25), start=start)
        if pc < best_cost - 1e-9:
            best_cost, best = pc, p.copy()
            no_improve = 0
            print(f"  ILS improved: {best_cost:.2f} (t={time.time()-start:.1f}s)")
        else:
            no_improve += 1

    final_times, _ = compute_times(best, earliest, latest, sep)
    print(f"\nFinal cost: {best_cost:.2f}")
    return best, final_times, best_cost

# ── 7. 输出────────────────────────────────────────────────────────────────

def write_results(order, times, tasks, out_path):
    """
    将调度结果写入 CSV 文件。

    Args:
        order: 任务顺序
        times: 各任务执行时间
        tasks: 任务列表
        out_path: 输出文件路径
    """
    target = np.array([t['target'] for t in tasks])
    pe     = np.array([t['pen_early'] for t in tasks])
    pl     = np.array([t['pen_late'] for t in tasks])
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['rank', 'task_id', 'time', 'target', 'deviation', 'cost'])
        for rank, (idx, t) in enumerate(zip(order, times), 1):
            tgt = tasks[idx]['target']
            dev = int(t) - tgt
            cost = pe[idx] * max(0, -dev) + pl[idx] * max(0, dev)
            w.writerow([rank, tasks[idx]['id'], int(t), tgt, dev, f'{cost:.4f}'])
    print(f"Results written to {out_path}")

if __name__ == '__main__':
    import os
    base = '.'  # 修改为实际工作目录
    tasks, sep = load_data(
        os.path.join(base, 'data', 'tasks.csv'),
        os.path.join(base, 'data', 'separation_matrix.csv')
    )
    random.seed(42)
    np.random.seed(42)
    order, times, cost = solve(tasks, sep, total_time=280.0)
    write_results(order, times, tasks, os.path.join(base, 'result.csv'))
