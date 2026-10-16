### 历史踩坑

#### 1. Hazmat 道路限制未完整执行 [7/12 runs]
- **硬编码单一限制类型**：仅过滤 `blacklist_explosive`，忽略 `school_zone`、`tunnel_ban`、`residential_restricted`、`weight_limit` 等其他类型，或将其降级为软成本乘子。
- **方向性查找漏洞**：限制以 `(from, to)` 存储，反向 `(to, from)` 通行未被拦截。
- **成本矩阵掩码不一致**：仅对 distance 矩阵置 `INF`，risk 或合并矩阵未掩码，Dijkstra 在未掩码矩阵上中转重新引入禁行边。
- **作用域假设错误**：将禁令绑定到车辆 ID 白名单而非货物危险品类别;或假设按类别区分但实际对所有 hazmat 通用。
- **软回退输出非法边**："就近选择并标记违规" 直接产出禁行边——可行性 = 0 分。
- **教训**：限制必须在构造、局部搜索的每一步检查，而非仅最终校验;扩展后的 hop-by-hop 路径需用原始限制集再校验一次。

#### 2. 单车单 hazmat 类别约束被违反 [4/12 runs]
- **资格 vs. 同载兼容性混淆**：`classes_needed.issubset(vehicle.allowed_classes)` 只检查认证范围,未禁止认证多类别的车一次拉多类。
- **教训**：ADR/DOT 类隔离要求每趟仅 1 个 hazmat class，与认证宽度无关。应先按 `hazmat_class` 划分客户池，再在池内独立路由。

#### 3. 多实例输出 schema 未遵守 [2/12 runs]
- **未枚举实例**：`*_multi` 数据集需输出 128 条 tour，但解算器硬编码单输入文件，仅产出 1 条。
- **教训**：先列举数据集 → 断言实例数 → 循环求解 → 校验 `len(solution)==N` 且每条 tour 是 `range(N)` 的排列后再写出。

#### 4. 硬约束缺失于路由构造阶段 [2/12 runs]
- **仅事后校验**：构造时只是 `[depot] + customers + [depot]`，无边可行性、无风险累计、无距离排序;`can_use_edge` 等辅助函数从未在贪心中被调用。
- **直查距离默认值 9999**：未走 Dijkstra over restricted subgraph，导致漏掉合法多跳路径并虚增成本。
- **教训**：所有约束（边可行性、风险上限、容量）必须嵌入插入逻辑，违规即拒绝插入。

#### 5. 错误优化目标 / 局部搜索过弱 [1/12 runs]
- K-means 按原坐标聚类 + 10 邻居 2-opt 窗口 → tour 缠绕、凸包侵入。
- 局部搜索优化时间方差而非距离;路间移动用 `append` 而非 cheapest-insertion。
- **教训**：CVRP 用 sweep/角度聚类比 K-means 更具空间内聚性;先优化总距，再考虑均衡。

#### routing-006: school_zone 等通用 hazmat 禁令被错误地视为类别条件 [回归: wb_hazmat_transport, skill 0.0 vs baseline 0.326]
- **观察**：错误 `Vehicle V5 uses school zone banned segment (4,8).`——技能版引入了更复杂的限制处理，反而比无技能基线更差。说明派发表错误地把 `school_zone` 当作仅对 `explosive`/特定类别生效，而实际数据中 `school_zone` 对所有 hazmat 通用。
- **根因**：构造 `FORBIDDEN_BY_TYPE` 时只读 `restriction_type` 字段中明确写出的 class，对未列出 class 的 `school_zone` 默认为"无限制"而非"对所有 hazmat 禁行"。
- **避坑代码**：
  ```python
  # 默认所有 hazmat class 都禁；仅 blacklist_<class> 才按类别条件化
  HAZMAT_CLASSES = set(df_customers['hazmat_class'].dropna().unique())
  FORBIDDEN = defaultdict(set)  # edge -> set of forbidden hazmat classes
  for _, r in df_restrictions.iterrows():
      u, v, rtype = r['from'], r['to'], r['restriction_type']
      if rtype.startswith('blacklist_'):
          banned_classes = {rtype.split('_', 1)[1]}
      else:
          # school_zone, tunnel_ban, residential_restricted, weight_limit, ...
          banned_classes = HAZMAT_CLASSES  # 全类禁行
      for edge in [(u,v), (v,u)]:
          FORBIDDEN[edge] |= banned_classes
  ```
- **教训**：未知/通用类型的限制 **默认对所有 hazmat 禁行**（fail-closed），仅当 `restriction_type` 显式编码了某个 class 才条件化。任何"派发表 miss → 放行"的写法都会引入比无技能基线还差的回归。

#### routing-007: 技能版多实例处理引入回归 [回归: wb_tsp_multi, skill 0.318 vs baseline 0.936]
- **观察**：基线 0.936 → 技能 0.318，下降 0.618。技能引导了额外的"多实例枚举/per-instance 时间预算/局部搜索"逻辑，但实现质量低于基线的朴素解法。可能成因：
  - per-instance 时间预算分配过紧（128 实例 × 500 城市），2-opt 早停在远离收敛点。
  - 多实例循环中复用了脏状态（距离矩阵、neighbor list 未重置）。
  - 输出虽然枚举完整但每条 tour 质量差于基线 NN/greedy。
- **避坑代码**：
  ```python
  # 1) 时间预算下限保护
  per_inst_budget = max(total_time / num_instances, MIN_2OPT_BUDGET_S)
  # 2) 每实例完全隔离
  for iid in sorted(df['instance_id'].unique()):
      sub = df[df['instance_id'] == iid].reset_index(drop=True)
      D = build_dist_matrix(sub)            # 重新构建
      tour = nn_then_2opt(D, time_limit=per_inst_budget)
      assert sorted(tour) == list(range(len(sub)))
      tours[iid] = tour
  # 3) 兜底：若 2-opt 未收敛或 cost 比 NN 还差，退回 NN
  if cost(tour_2opt) > cost(tour_nn): tour = tour_nn
  ```
- **教训**：任何"复杂版"路径都必须有 **NN/贪心兜底比较**；若优化结果比简单基线差则回退。多实例下尤其要做 per-instance 的 sanity check，不能让整体时间预算榨干单实例质量。

#### 跨切面元教训
- **校验器对齐**：内部 validator 必须逐条复现 evaluator 检查;未被代码枚举的约束即被静默违反。
- **硬约束在构造期生效**：用 `INF` 掩码所有成本矩阵，使优化器永不提出非法移动。
- **schema/scope 从数据读取**：不要硬编码限制适用的 ID/class;直接解析 `restriction_type` 与 scope 列。
- **先对齐 evaluator 输出 schema**：实例数、文件名、键结构、索引约定确认无误后再优化成本。
- **fail-closed 默认**：未知限制类型 / 未匹配派发表项一律按"禁行"处理，绝不静默放行。
- **始终保留基线兜底**：复杂解算器必须与朴素基线 (NN, greedy) 比较，更差则回退。

---

### 退出前自检

**通用项**
- [ ] 已枚举数据集中所有实例/约束类型，未硬编码任意子集（如仅 `blacklist_explosive`）。
- [ ] 内部 validator 与 evaluator 检查项逐条对齐，跑通后再提交。
- [ ] 输出 schema 与 evaluator 期望完全一致：文件名、顶层键（如 `"tours"`）、索引基（0-indexed）、实例数。
- [ ] 所有硬约束在构造与局部搜索的每一步检查，而非仅最终校验。
- [ ] 所有相关成本矩阵（distance、risk、combined）一致掩码为 `INF`，Dijkstra 调用均使用受限子图。
- [ ] 不输出"已标记违规"的非法回退;无可行解时改为重路由或拆单。
- [ ] solution 通过结构性自检：每个输出非空、长度匹配、元素覆盖完整集合。
- [ ] **限制派发表 fail-closed**：未列于 `blacklist_<class>` 的限制类型（如 `school_zone`、`tunnel_ban`）默认对所有 hazmat class 禁行，而非默认放行。
- [ ] **基线兜底**：复杂解算器输出与 NN/贪心基线对比，若更差则按实例回退到基线，避免技能版回归。

**tsp_local_search 子型**
- [ ] 若数据集名含 `_multi`，已 enumerate 全部 instance 并 per-instance 求解，输出 tour 数 == 实例数。
- [ ] 每条 tour 是 `range(N)` 的完整排列且不重复 depot/起点。
- [ ] 求解器与 evaluator 使用同一距离度量与舍入规则。
- [ ] 已分配 per-instance 时间预算，确保 2-opt/Or-opt 能收敛而非超时截断；同时 per-instance budget 有下限保护。
- [ ] 多实例循环中距离矩阵 / neighbor list / 全局状态在每次迭代重置，避免脏状态污染。

**cvrp_cluster_then_route 子型**
- [ ] 每车 load ≤ capacity;路线数 ≤ 可用车辆数;每客户恰被服务一次,每条路径起止于 depot。
- [ ] 聚类用 sweep/角度法或 capacity-constrained K-means；边界客户在违反容量/侧约束时再均衡到最近可行簇。
- [ ] 路间移动用 cheapest-insertion，而非 `append`。
- [ ] 主目标为总距离/时间，均衡为次要目标（除非任务明确要求方差最小）。

**带 hazmat / 道路限制的 CVRP 子型**
- [ ] 限制以 `frozenset({u,v})` 等无向结构存储，正反向均拦截。
- [ ] `FORBIDDEN_BY_TYPE[restriction_type] → set(hazmat_classes)` 由数据动态构建；未知类型默认对所有 hazmat 禁行。
- [ ] `school_zone` / `tunnel_ban` / `residential_restricted` 等通用类型显式映射为"全 hazmat class 禁行"，仅 `blacklist_<class>` 才按类别条件化。
- [ ] 同车单 hazmat class 检查先于认证检查执行;客户已按 `hazmat_class` 预先分池，跨池不合并路线。
- [ ] 风险上限在插入时实时累计并据此拒绝违规插入。
- [ ] Dijkstra 展开后的 hop-by-hop 路径再次用原始限制集校验，且最终输出包含完整 hop 序列以便 evaluator 验证一致。