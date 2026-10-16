#!/usr/bin/env python3
"""
Baseline template for TSP via local search (nearest-neighbor + 2-opt).

Designed as a generalized starting point for any `tsp_local_search` case:
- Single or multi-instance benchmarks
- Arbitrary input column names (adapt at marked hooks)
- Distance metric must match evaluator (default: Euclidean, no rounding)
"""

import csv
import math
import os
import random
import time
from typing import List, Tuple, Dict, Any, Optional


# ADAPT HERE: distance metric must match the evaluator exactly.
# Common variants: "euclidean" (float), "euclidean_int" (TSPLIB EUC_2D rounding),
# "manhattan", "haversine", "precomputed". Confirm against the evaluator spec
# before shipping.
DISTANCE_METRIC = "euclidean"

# If DISTANCE_METRIC == "precomputed", set this path (or pass via kwargs).
PRECOMPUTED_MATRIX_PATH: Optional[str] = None

# Earth radius (km) for haversine.
_EARTH_RADIUS_KM = 6371.0088


def compute_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    dx, dy = p1[0] - p2[0], p1[1] - p2[1]
    if DISTANCE_METRIC == "euclidean":
        return math.sqrt(dx * dx + dy * dy)
    if DISTANCE_METRIC == "euclidean_int":
        return int(round(math.sqrt(dx * dx + dy * dy)))
    if DISTANCE_METRIC == "manhattan":
        return abs(dx) + abs(dy)
    if DISTANCE_METRIC == "haversine":
        # Assumes p = (lon, lat) in degrees. Adapt order if evaluator differs.
        lon1, lat1 = math.radians(p1[0]), math.radians(p1[1])
        lon2, lat2 = math.radians(p2[0]), math.radians(p2[1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))
    raise ValueError(f"Unknown metric: {DISTANCE_METRIC}")


def load_precomputed_matrix(path: str) -> List[List[float]]:
    """Load a precomputed distance matrix (CSV, square, no header required).
    If a header row is present (non-numeric first cell), it is skipped."""
    M: List[List[float]] = []
    with open(path, "r") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if not row:
                continue
            try:
                vals = [float(x) for x in row]
            except ValueError:
                if i == 0:
                    continue  # skip header
                raise
            M.append(vals)
    n = len(M)
    for r in M:
        if len(r) != n:
            raise ValueError(f"Precomputed matrix not square: got row len {len(r)} for n={n}")
    return M


def build_dist_matrix(coords: List[Tuple[float, float]]) -> List[List[float]]:
    if DISTANCE_METRIC == "precomputed":
        if not PRECOMPUTED_MATRIX_PATH or not os.path.exists(PRECOMPUTED_MATRIX_PATH):
            raise FileNotFoundError(
                f"DISTANCE_METRIC=precomputed but PRECOMPUTED_MATRIX_PATH not found: "
                f"{PRECOMPUTED_MATRIX_PATH}"
            )
        M = load_precomputed_matrix(PRECOMPUTED_MATRIX_PATH)
        if len(M) != len(coords):
            raise ValueError(
                f"Precomputed matrix size {len(M)} != number of nodes {len(coords)}"
            )
        return M
    n = len(coords)
    M = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = compute_distance(coords[i], coords[j])
            M[i][j] = M[j][i] = d
    return M


def route_distance(route: List[int], D: List[List[float]]) -> float:
    total = 0.0
    n = len(route)
    for i in range(n):
        total += D[route[i]][route[(i + 1) % n]]
    return total


def nearest_neighbor(start: int, n: int, D: List[List[float]]) -> List[int]:
    visited = [False] * n
    route = [start]
    visited[start] = True
    for _ in range(n - 1):
        cur = route[-1]
        best, best_d = -1, float("inf")
        row = D[cur]
        for j in range(n):
            if not visited[j] and row[j] < best_d:
                best_d, best = row[j], j
        route.append(best)
        visited[best] = True
    return route


def two_opt(route: List[int], D: List[List[float]], time_limit: float = 30.0) -> List[int]:
    """Standard 2-opt local search until no improving swap or time exhausted."""
    n = len(route)
    if n < 4:
        return route
    t0 = time.time()
    improved = True
    while improved and (time.time() - t0) < time_limit:
        improved = False
        for i in range(1, n - 1):
            if time.time() - t0 > time_limit:
                break
            a, b = route[i - 1], route[i]
            for j in range(i + 1, n):
                c = route[j]
                d = route[(j + 1) % n]
                if a == c or b == d:
                    continue
                delta = (D[a][c] + D[b][d]) - (D[a][b] + D[c][d])
                if delta < -1e-12:
                    route[i:j + 1] = reversed(route[i:j + 1])
                    improved = True
                    break
            if improved:
                break
    return route


# CONSTRAINT-CHECK: If the evaluator requires the tour to explicitly close
# (i.e., last city == first city), set CLOSE_TOUR = True. Otherwise leave False.
CLOSE_TOUR = False


def solve_one_instance(coords: List[Tuple[float, float]],
                       ids: List[Any],
                       num_starts: int = 5,
                       time_limit: float = 60.0) -> Tuple[List[Any], float]:
    """Solve a single TSP instance. Returns (city_id_sequence, total_distance)."""
    n = len(coords)
    if n == 0:
        return [], 0.0
    if n == 1:
        return [ids[0]], 0.0

    D = build_dist_matrix(coords)

    num_starts = max(1, min(num_starts, n))
    starts = random.sample(range(n), num_starts) if num_starts < n else list(range(n))

    best_route, best_dist = None, float("inf")
    per_start_budget = max(1.0, time_limit / num_starts)
    for s in starts:
        r = nearest_neighbor(s, n, D)
        r = two_opt(r, D, time_limit=per_start_budget)
        d = route_distance(r, D)
        if d < best_dist:
            best_dist, best_route = d, r

    # CONSTRAINT-CHECK: Tour visits every city exactly once and returns to start
    # (Hamiltonian cycle). Verify and repair before emitting.
    assert len(best_route) == n, f"Route length {len(best_route)} != n={n}"
    assert len(set(best_route)) == n, "Route has duplicate cities"
    assert set(best_route) == set(range(n)), "Route missing some cities"

    id_route = [ids[i] for i in best_route]
    # If the evaluator requires explicit closure, append the start city.
    if CLOSE_TOUR:
        id_route = id_route + [ids[best_route[0]]]
    return id_route, best_dist


# ADAPT HERE: column-name aliases. Extend per benchmark or override via kwargs.
ID_COL_ALIASES = ["city_id", "id", "node_id", "index", "City", "ID", "NodeId"]
X_COL_ALIASES = ["x", "lon", "longitude", "X", "xcoord", "Xcoord", "x_coord"]
Y_COL_ALIASES = ["y", "lat", "latitude", "Y", "ycoord", "Ycoord", "y_coord"]
INSTANCE_COL_ALIASES = ["instance_id", "problem_id", "tsp_id", "instance", "group_id"]


def _pick(row: Dict[str, Any], aliases: List[str]) -> Optional[str]:
    for k in aliases:
        if k in row and row[k] not in (None, ""):
            return k
    return None


def _coerce_id(v: Any) -> Any:
    if v is None:
        return v
    s = str(v)
    return int(s) if s.lstrip("-").isdigit() else v


def group_by_instance(rows_path: str,
                      id_col: Optional[str] = None,
                      x_col: Optional[str] = None,
                      y_col: Optional[str] = None,
                      instance_col: Optional[str] = None
                      ) -> Dict[Any, Tuple[List[Tuple[float, float]], List[Any]]]:
    """
    Group rows by an instance key. Tries common aliases or accepts an override.
    Returns {instance_id: (coords, ids)} or {single_key: (coords, ids)} if no
    instance column is present. CRITICAL for multi-instance benchmarks: every
    instance_id present in the input MUST get a tour in the output.
    """
    # EVOLVED: multi-instance benchmarks require iterating ALL instance_ids, not just one.
    groups: Dict[Any, Tuple[List, List]] = {}
    order: List[Any] = []  # EVOLVED: preserve first-seen order of instance keys
    with open(rows_path, "r") as f:  # EVOLVED: complete the truncated open() call
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        resolved_id = id_col if id_col in fieldnames else None
        resolved_x = x_col if x_col in fieldnames else None
        resolved_y = y_col if y_col in fieldnames else None
        resolved_inst = instance_col if instance_col in fieldnames else None

        for line_no, row in enumerate(reader, start=2):
            if resolved_id is None:
                resolved_id = _pick(row, ID_COL_ALIASES)
            if resolved_x is None:
                resolved_x = _pick(row, X_COL_ALIASES)
            if resolved_y is None:
                resolved_y = _pick(row, Y_COL_ALIASES)
            if resolved_inst is None:
                resolved_inst = _pick(row, INSTANCE_COL_ALIASES)

            if resolved_x is None or resolved_y is None:
                raise ValueError(
                    f"Could not locate x/y in {rows_path}. Header: {fieldnames}."
                )
            try:
                x = float(row[resolved_x]); y = float(row[resolved_y])
            except (TypeError, ValueError) as e:
                raise ValueError(f"Bad x/y on line {line_no}: {e}")

            # EVOLVED: use sentinel "__single__" when no instance col, so single-
            # instance and multi-instance flows share one code path.
            inst_key = _coerce_id(row[resolved_inst]) if resolved_inst else "__single__"
            cid = row.get(resolved_id) if resolved_id else line_no - 2
            if inst_key not in groups:
                groups[inst_key] = ([], [])
                order.append(inst_key)
            groups[inst_key][0].append((x, y))
            groups[inst_key][1].append(_coerce_id(cid))
    # EVOLVED: return ordered dict-like via insertion order (Py3.7+ guaranteed).
    return {k: groups[k] for k in order}


def load_nodes_csv(path: str,
                   id_col: Optional[str] = None,
                   x_col: Optional[str] = None,
                   y_col: Optional[str] = None) -> Tuple[List[Tuple[float, float]], List[Any], Any]:
    """Single-instance loader. For multi-instance inputs, use group_by_instance."""
    # EVOLVED: delegate to group_by_instance to share parsing & avoid drift.
    groups = group_by_instance(path, id_col=id_col, x_col=x_col, y_col=y_col)
    if not groups:
        return [], [], None
    if len(groups) > 1:
        # EVOLVED: warn-by-raise so callers don't silently drop instances.
        raise ValueError(
            f"{path} contains {len(groups)} instances; use group_by_instance "
            f"and iterate ALL keys to avoid dropping tours."
        )
    key, (coords, ids) = next(iter(groups.items()))
    return coords, ids, None if key == "__single__" else key