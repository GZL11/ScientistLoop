"""
子类型 C — 资源约束排程 CP-SAT 起手模板
适用：手术室排程、岸桥/项目调度、人员排班（30–200 任务，多硬资源）
"""
from ortools.sat.python import cp_model


def build_or_schedule_model(surgeries, rooms, surgeons_avail, precedence,
                             time_limit_s=240, num_workers=4):
    """
    surgeries: list of dict {id, duration_min, room_type, surgeon, priority,
                              nurses_required, requires_laparoscopy, requires_icu,
                              is_infection_case, deadline_day}
    rooms: list of dict {id, room_type}
    surgeons_avail: dict surgeon -> set of available days (1..7)
    precedence: list of (i, j) meaning i must finish before j starts (different days OK)
    """
    model = cp_model.CpModel()

    DAYS = list(range(1, 8))     # Mon..Sun
    DAY_MIN = 1440               # 一天分钟数（用于跨天扩展）
    OPEN_MIN, CLOSE_MIN = 480, 1080
    HORIZON = 7 * DAY_MIN

    # ── 决策变量 ────────────────────────────────────────────────────────
    start, end, day_of, interval = {}, {}, {}, {}
    room_assign = {}  # binary[i, r]
    is_overtime = {}

    rooms_by_type = {}
    for r in rooms:
        rooms_by_type.setdefault(r['room_type'], []).append(r['id'])

    for s in surgeries:
        i = s['id']
        cand_rooms = rooms_by_type[s['room_type']]
        cand_days = sorted(surgeons_avail[s['surgeon']])

        start[i] = model.NewIntVar(0, HORIZON, f'start_{i}')
        end[i]   = model.NewIntVar(0, HORIZON, f'end_{i}')
        interval[i] = model.NewIntervalVar(start[i], s['duration_min'], end[i], f'op_{i}')

        # 房间分配
        for r in cand_rooms:
            room_assign[i, r] = model.NewBoolVar(f'asg_{i}_{r}')
        model.Add(sum(room_assign[i, r] for r in cand_rooms) == 1)

        # 选定房间外的房间不能用：用 OptionalIntervalVar 的标准做法
        # （此处简化：通过 disjunction 约束在 NoOverlap 下区分房间）

        # 医生可工作日约束
        day_of[i] = model.NewIntVar(1, 7, f'day_{i}')
        # day = floor(start / DAY_MIN) + 1
        model.AddDivisionEquality(day_of[i], start[i] + DAY_MIN, DAY_MIN)
        model.AddAllowedAssignments([day_of[i]], [(d,) for d in cand_days])

        # 同一天工作日的开放时段：start_in_day ∈ [480, 1080-dur]，但允许加班（end 超 1080）
        start_in_day = model.NewIntVar(0, DAY_MIN - 1, f'sid_{i}')
        model.Add(start_in_day == start[i] - (day_of[i] - 1) * DAY_MIN)
        model.Add(start_in_day >= OPEN_MIN)
        # end_in_day（可能超过 CLOSE_MIN，触发加班）
        end_in_day = model.NewIntVar(0, DAY_MIN - 1, f'eid_{i}')
        model.Add(end_in_day == end[i] - (day_of[i] - 1) * DAY_MIN)
        # 不允许跨天
        model.Add(end_in_day <= DAY_MIN - 1)

        # 加班分钟（≥0）
        is_overtime[i] = model.NewIntVar(0, DAY_MIN, f'ot_{i}')
        model.Add(is_overtime[i] >= end_in_day - CLOSE_MIN)

    # ── 房间不重叠 ──────────────────────────────────────────────────────
    for r in [r['id'] for r in rooms]:
        ints_in_room = []
        for s in surgeries:
            i = s['id']
            if (i, r) in room_assign:
                presence = room_assign[i, r]
                opt_int = model.NewOptionalIntervalVar(
                    start[i], s['duration_min'], end[i], presence, f'opi_{i}_{r}')
                ints_in_room.append(opt_int)
        model.AddNoOverlap(ints_in_room)

    # ── 医生不重叠 + 同医生两台间隔 ≥ 60 分钟 ───────────────────────────
    surgeons = {s['surgeon'] for s in surgeries}
    for sg in surgeons:
        ops = [s for s in surgeries if s['surgeon'] == sg]
        for i_idx, a in enumerate(ops):
            for b in ops[i_idx + 1:]:
                # 两两 disjunction：a 在 b 之前 OR b 在 a 之前，且间隔 ≥ 60
                a_before_b = model.NewBoolVar(f'ab_{a["id"]}_{b["id"]}')
                model.Add(end[a['id']] + 60 <= start[b['id']]).OnlyEnforceIf(a_before_b)
                model.Add(end[b['id']] + 60 <= start[a['id']]).OnlyEnforceIf(a_before_b.Not())

    # ── 腹腔镜每天 ≤ 2 台 ──────────────────────────────────────────────
    laparo_ids = [s['id'] for s in surgeries if s['requires_laparoscopy']]
    for d in DAYS:
        on_day = []
        for i in laparo_ids:
            b = model.NewBoolVar(f'lap_{i}_{d}')
            model.Add(day_of[i] == d).OnlyEnforceIf(b)
            model.Add(day_of[i] != d).OnlyEnforceIf(b.Not())
            on_day.append(b)
        model.Add(sum(on_day) <= 2)

    # ── ICU 床位每天 ≤ 4，每台 ICU 手术占用完成当天和次日 ──────────────
    icu_ids = [s['id'] for s in surgeries if s['requires_icu']]
    for d in DAYS:
        occupants = []
        for i in icu_ids:
            # 占用当天 (day_of == d) 或 次日 (day_of == d-1)
            on_d   = model.NewBoolVar(f'icu_{i}_{d}_d')
            on_dm1 = model.NewBoolVar(f'icu_{i}_{d}_dm1')
            model.Add(day_of[i] == d).OnlyEnforceIf(on_d)
            model.Add(day_of[i] != d).OnlyEnforceIf(on_d.Not())
            if d > 1:
                model.Add(day_of[i] == d - 1).OnlyEnforceIf(on_dm1)
                model.Add(day_of[i] != d - 1).OnlyEnforceIf(on_dm1.Not())
            else:
                model.Add(on_dm1 == 0)
            occupants.append(on_d)
            occupants.append(on_dm1)
        model.Add(sum(occupants) <= 4)

    # ── 护士每天工时 ≤ 8400 ─────────────────────────────────────────────
    for d in DAYS:
        nurse_minutes = []
        for s in surgeries:
            i = s['id']
            on_d = model.NewBoolVar(f'nur_{i}_{d}')
            model.Add(day_of[i] == d).OnlyEnforceIf(on_d)
            model.Add(day_of[i] != d).OnlyEnforceIf(on_d.Not())
            # 当天工时 = duration * nurses_required * on_d
            term = model.NewIntVar(0, s['duration_min'] * s['nurses_required'], f'nm_{i}_{d}')
            model.Add(term == s['duration_min'] * s['nurses_required']).OnlyEnforceIf(on_d)
            model.Add(term == 0).OnlyEnforceIf(on_d.Not())
            nurse_minutes.append(term)
        model.Add(sum(nurse_minutes) <= 8400)

    # ── precedence：i 完成日 ≤ j 开始日 ─────────────────────────────────
    for i, j in precedence:
        model.Add(day_of[i] < day_of[j])  # 严格不同天

    # ── 感控排该手术室当天最后：i 是感控 → 同房同日所有非 i 任务必须在 i 之前结束 ──
    inf_ids = {s['id'] for s in surgeries if s['is_infection_case']}
    for s_inf in surgeries:
        if s_inf['id'] not in inf_ids:
            continue
        i = s_inf['id']
        for s_other in surgeries:
            j = s_other['id']
            if j == i:
                continue
            # 仅当 j 与 i 同房 + 同日时强制 end[j] <= start[i]
            for r in rooms_by_type[s_inf['room_type']]:
                if (j, r) in room_assign and (i, r) in room_assign:
                    same_room_day = model.NewBoolVar(f'srd_{i}_{j}_{r}')
                    model.AddBoolAnd([room_assign[i, r], room_assign[j, r]]) \
                         .OnlyEnforceIf(same_room_day)
                    model.AddBoolOr([room_assign[i, r].Not(), room_assign[j, r].Not()]) \
                         .OnlyEnforceIf(same_room_day.Not())
                    same_day = model.NewBoolVar(f'sd_{i}_{j}')
                    model.Add(day_of[i] == day_of[j]).OnlyEnforceIf(same_day)
                    model.Add(day_of[i] != day_of[j]).OnlyEnforceIf(same_day.Not())
                    cond = model.NewBoolVar(f'cond_{i}_{j}_{r}')
                    model.AddBoolAnd([same_room_day, same_day]).OnlyEnforceIf(cond)
                    model.AddBoolOr([same_room_day.Not(), same_day.Not()]).OnlyEnforceIf(cond.Not())
                    model.Add(end[j] <= start[i]).OnlyEnforceIf(cond)

    # ── 目标函数：加班费 + 延迟罚款 ────────────────────────────────────
    overtime_cost = sum(is_overtime[i] for i in start) * 30  # $30/min
    delay_terms = []
    for s in surgeries:
        if s.get('deadline_day'):
            delay = model.NewIntVar(0, 7, f'dl_{s["id"]}')
            model.Add(delay >= day_of[s['id']] - s['deadline_day'])
            unit = 50 if s['priority'] == 1 else (30 if s['priority'] == 2 else 0)
            delay_terms.append(unit * delay)
    model.Minimize(overtime_cost + sum(delay_terms))

    # ── 求解 ────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = num_workers
    status = solver.Solve(model)
    print(f'Status: {solver.StatusName(status)}, Obj: {solver.ObjectiveValue()}')

    return solver, start, end, day_of, room_assign, is_overtime, status


def extract_results(solver, surgeries, rooms, start, end, day_of, room_assign, is_overtime):
    """从求解器读出结果，返回排程列表。"""
    out = []
    for s in surgeries:
        i = s['id']
        room = next(r['id'] for r in rooms if (i, r['id']) in room_assign
                    and solver.Value(room_assign[i, r['id']]) == 1)
        out.append({
            'surgery_id': i,
            'day':        solver.Value(day_of[i]),
            'room_id':    room,
            'start_time': solver.Value(start[i]),
            'end_time':   solver.Value(end[i]),
            'overtime_min': solver.Value(is_overtime[i]),
        })
    return out


# 用法：
#   surgeries = [...] 从 surgeries.csv 读
#   rooms     = [...] 从 operating_rooms.csv 读
#   surgeons_avail = {...} 从 surgeon_availability.csv 解析
#   precedence = [(3,10),(13,14),(5,23)]
#   solver, *vars_, status = build_or_schedule_model(...)
#   if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
#       result = extract_results(solver, surgeries, rooms, *vars_[:5])
#       pd.DataFrame(result).to_csv('schedule_result.csv', index=False)
