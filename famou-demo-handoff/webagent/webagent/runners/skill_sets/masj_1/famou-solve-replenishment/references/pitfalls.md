### 历史踩坑

#### 1. 冷藏容量约束作用范围错误：期末库存 vs. 峰值占用 [7/18 runs]
容量约束只施加在**期末库存**上，但评测器在**峰值占用时刻**（到货后、需求满足前）核查冷藏负载。常见变体：
- LP 允许批次的负残差与正残差互相抵消，掩盖真实存储量
- 期内峰值库存 `prev_inv + arrivals` 严格 ≥ 期末库存
- 部分评测器把在途/吞吐量也计入冷藏使用
- 前向投影忽略管道库存

**修复**：对每个 (DC, period) 同时施加峰值约束：
```
∑_p cold_usage[p] · (inventory[p, t-1, dc] + arrivals[p, t, dc]) ≤ cold_capacity[dc]
```
对多批次易腐模型，强制**每个前缀**的累计非负：`Σ_{t'≤t} consumed[batch, t'] ≤ purchase[batch]`，不能只约束生命周期总量。在产出 CSV 前，**用评测器的精确公式回放**自己的解。

#### 2. 缺失 per-SKU `cold_usage` 权重 [5/18 runs]
容量约束完全省略 `cold_usage` 系数（按单位数计算），或只在 hub 应用而忽略区域 DC。评测器按 `Σ inventory_units · sku.cold_usage` 计算，对 `cold_usage > 1` 的 SKU 实际占用可能 >2× 单位数。

**修复**：冷藏容量是**体积制**而非件数制，**所有位置**（hub 与 spoke）统一加权。整数化时缩放系数（× 1000），LHS 系数用 `math.ceil`、RHS 上界用 `math.floor`，绝不用 `int()` 截断。

#### 3. 订货量整数性违反 [4/18 runs]
变量声明为连续（`cat='Continuous'`、未加 integer 标志），或将 `total_demand × demand_share` 的小数分配直接写入 CSV。评测器要求 `order_units` 为整数。

**修复**：
1. 一开始就声明 `LpVariable(..., cat='Integer')` 或 CP-SAT `IntVar`
2. 按比例拆分聚合数量时使用**最大余数法（Hamilton）**保持整数总和
3. 写出前 `int(round(value))` 防御性强转
4. 写出前断言 `all(float(v).is_integer() for v in order_units_column)`

#### 4. 输出 schema 不全 / 缺行 [4/18 runs]
求解器只写非零订单或跳过超过 lead-time 的期数；列名错误（`order_qty` 而非 `order_units`）。

**修复**：
- 始终输出**完整稠密网格** `(period × SKU × DC)`，含零行和 lead-time 之外的期
- 写出前断言 `len(rows) == N_periods × len(SKUs) × len(DCs)`
- 列名严格按规约校对，断言 header 等价

#### 5. 网络级聚合约束被错误地局部化 [2/18 runs]
仅按 `(period, SKU)` 索引（无 DC 维度）的容量列实为**全网池化上限**，但被当作每个 DC 变量的上界，导致 N 个 DC 各自达到上限造成 N 倍超用。

**修复**：检查每张输入表的**索引键**。表中没有 location 维度 ⇒ 是聚合上限 ⇒ 必须加求和约束：
```python
for t in periods:
    for sku in SKUs:
        model.Add(sum(order[t][dc][sku] for dc in DCs) <= order_cap[t][sku])
```
**通则：表的索引揭示约束的作用范围。**

#### 6. Hub-Spoke 时序：同期转运超过现有库存 [2/18 runs]
Hub 平衡方程允许 `t` 期发出的货从 `t` 期采购中提取（cross-docking），但评测器要求发货来自**前一期期末库存**。

**修复**：
```
∑_dc replenish[p, t, dc] ≤ hub_inv[p, t-1]
```
将"到货"与"可发货"分离；除非规约明确允许 cross-docking，否则不允许同期流出。

#### 7. 缺失保质期 / FIFO 队列建模 [2/18 runs]
省略显式保质期约束，仅靠浪费成本惩罚隐式限制。当持有成本 < 浪费节省时优化器无限囤货，撑爆容量。

**修复**：用**年龄索引队列** `inv[dc, sku, t, age]`（`age = 0..shelf_life-1`），`age = shelf_life` 强制变 waste；FIFO 通过独立的 `consume[dc, sku, t, age]` 变量实现。**不能仅依赖浪费成本惩罚。**

#### 8. 临界约束无容差缓冲 [1/18 runs]
LP 容差 + 后置取整产生 2.0001% 不良率 vs. 2.0% 上限。修复：RHS 内紧 ε（如求解器中用 1.99%），从一开始就整数求解，对取整后解再次校验。

#### 9. 缺失约束族（MOQ、合同最小量、延迟惩罚）[1/18 runs]
半连续 MOQ（`qty == 0 OR qty ≥ MOQ`）和合同最小量从未被编码。修复：引入二元 `z[s,m]`，`MOQ·z ≤ qty ≤ cap·z`。**通则：编码前先建一份从每个输入 CSV 列到模型约束的对照清单。**

#### 10. 替代被建模为凭空供给 [1/18 runs]
高级品替代标准品被加为平衡方程中的免费加项，而非从高级品库存出库的转移。修复：把替代建模为**同时减少供方库存、满足受方需求**的流量。

#### replenishment-011: 应用 skill 反而违反冷藏容量（回归案例） [regression: wb_cold_storage_replenishment]
观察：在 `wb_cold_storage_replenishment` 上，skill 得分 0.0 vs. baseline 0.161（Δ-0.161），单一错误 `Cold storage capacity exceeded at DC1 in period 4: 1357.70 > 1200.00`。表明 skill 引导的求解器虽建模了容量，但**仍在某个时刻（很可能是峰值/到货时刻）**超限 13%。可能原因：
- 仅约束期末库存，未约束 `prev_inv + arrivals` 峰值（参见 #1）
- 漏乘 `cold_usage` 权重，或仅在部分 DC 施加（参见 #2）
- LP 连续解后取整把已经贴边的约束推过界
- 用 `≤` 但 RHS 未留 ε，浮点误差或取整漂移导致 1357.70 > 1200

**避坑**：所有冷藏容量场景必须**同时**满足以下五点，缺一不可：
```python
# 1. 显式枚举所有 DC（hub + every spoke），不要循环里 break
# 2. 显式枚举所有 period（含 t=0 初始库存所在期）
# 3. 同时约束峰值和期末两个时点
# 4. LHS 加权 cold_usage[p]，整数化时系数 math.ceil
# 5. RHS 留 ε（例如 capacity - 1）以吸收数值漂移

EPS = 1  # 整数单位下留 1 单位安全边际
for d in ALL_DCS:                       # 含 hub
    cap = math.floor(cold_capacity[d]) - EPS
    for t in periods:
        # 峰值：到货后、消费前
        peak = pulp.lpSum(
            math.ceil(cold_usage[p] * SCALE) *
            (inv[p, d, t-1] + arrivals[p, d, t])
            for p in SKUs
        )
        model += peak <= cap * SCALE, f"cold_peak_{d}_{t}"
        # 期末
        eop = pulp.lpSum(
            math.ceil(cold_usage[p] * SCALE) * inv[p, d, t]
            for p in SKUs
        )
        model += eop <= cap * SCALE, f"cold_eop_{d}_{t}"

# 写 CSV 之前在 Python 侧用评测器口径再算一遍：
for d in ALL_DCS:
    for t in periods:
        used = sum(cold_usage[p] * (inv_val[p,d,t-1] + arr_val[p,d,t]) for p in SKUs)
        assert used <= cold_capacity[d], f"REPLAY FAIL {d} {t}: {used}"
```
**通则**：当 baseline > 0 而 skill 引导的解 = 0 且只缺一个容量约束时，问题几乎总在"约束写了但作用点错了"——必须在写文件前用评测器精确语义回放。**不要相信 LP solver 的"feasible"标签，要相信 replay。**

#### replenishment-012: 冷藏容量约束完全缺失 / 被每-SKU 局部化 [6/8 recent runs]
观察：跨 MIP 与启发式实现，聚合冷藏容量约束 `Σ_p I[p,t] · cold_usage[p] ≤ cold_capacity[dc]` 出现以下变体性失误：
- **MIP 完全没加该约束**：定义了 `dc_cold_cap` 与批次库存变量却从未连接，求解器为对冲缺货/浪费罚款无限囤货
- **按每 SKU 独立施加**：每个 SKU 都独享完整 DC 容量（静态快照），N 个 SKU 同时占满同一空间（如 3 个 SKU 各 ~600 vs 容量 500）
- **仅检查 hub，未检查所有 spoke DC**（如只校验 DC1，遗漏 DC2-DC5）
- **lookahead 覆盖未考虑容量**：未来需求覆盖横跨整个保质期但忽略容量何时绑定，导致提前堆货

**避坑**：
```python
# MIP：必须显式连接批次库存变量与聚合容量
for d in ALL_DCS:
    for t in PERIODS:
        model += pulp.lpSum(
            sku_cold_usage[p] * inv_batch[(d, p, ot, t)]
            for p in PRODUCTS for ot in PERIODS
            if ot <= t < ot + sku_shelf[p]
        ) <= dc_cold_cap[d], f"cold_cap_{d}_{t}"

# 启发式/贪心：维护 running remaining_cold，**不要**在每-SKU 循环内重新读取静态快照
remaining_cold = {d: dc_cold_cap[d] for d in ALL_DCS}
for p in sorted(PRODUCTS, key=lambda x: -lost_sales_penalty[x]):  # 优先级：高罚款先
    for d in ALL_DCS:
        qty = min(needed[p, d], remaining_cold[d] // cold_usage[p])
        order[p, d] = qty
        remaining_cold[d] -= qty * cold_usage[p]

# lookahead 截断到容量绑定时刻
horizon = min(sku_shelf[p], weeks_until_capacity_binds(d, p))

# 后求解修复：若 replay 仍违反，按 penalty/cold_usage 升序削减最晚期订单
```
**通则**：**写约束前先做"参数引用清单"——主数据中每个加载的容量参数（cold_capacity、truck_capacity、warehouse_volume 等）必须至少被一个约束或目标项引用**。未引用的容量参数 99% 是漏写约束，而非闲置数据。

#### replenishment-013: 代码生成截断 / 求解前未写 fallback artifact [9/9 recent runs, 主导失败模式]
观察：最近 9/9 次评测全部在**抽取阶段**失败（`extraction_status="error"`, validity=0），分布如下：
- **代码在 `prob.solve()` 或文件写入之前被截断**（7/9）：长 prompt + 复杂建模导致生成中途超出 token 上限，停在某个语句中间
- **build 完成但根本没有写文件步骤**（2/9）：脚本只构造了 LP 对象，未 emit CSV
- **schema 错 / 缺必需文件 / 缺 TOTAL 行**（2/9）：写了但评测器拒收

后果：MILP 即使最优也得 0 分，因为评测器只看 artifact，不看 LP 对象。

**避坑**：把"输出契约"当作**硬前置条件**，不是事后补丁。

#### replenishment-014: 输出序列化层漏 location 维度 / 写入 LpVariable 对象 [6/9 recent runs]
观察：MILP 模型本身正确，但**输出 writer 失败评测器契约**：
- writer 仅按 `(period, product)` 迭代，遗漏 per-DC location 维度，导致 `location` 列为空字符串
- 直接将 `pulp.LpVariable` 对象或未被求解器触及的 `None` 写入 CSV，CSV 中产生空字符串
- 把汇总行（合计/echo）混入 plan file，行内 `location`/`order_units` 留空
- 列名错（`dc`/`order_quantity` vs 评测器要求 `location`/`order_units`）

后果：即使 LP 最优，validity=0 因 schema 校验失败。

**避坑**：在写 CSV 时**严格执行输出契约**，且与汇总输出分离：
```python
rows = []
for loc in LOCATIONS:                 # 必须包含 location 维度
    for p in PRODUCTS:
        for t in PERIODS:
            v = pulp.value(order[(loc, p, t)])
            qty = int(round(v)) if v is not None else 0   # None → 0
            rows.append({"period": int(t), "product": str(p),
                         "location": str(loc), "order_units": int(qty)})
df = pd.DataFrame(rows)
# 写入前断言：行数、非空、可数值化
assert len(df) == len(LOCATIONS) * len(PRODUCTS) * len(PERIODS)
assert df["location"].astype(str).str.len().gt(0).all()
assert df["order_units"].apply(lambda x: float(x).is_integer()).all()
df.to_csv(OUTPUT_PATH, index=False)
# 汇总/成本 / TOTAL 行单独写 cost_summary.csv，**不要混入 plan file**
```

#### replenishment-015: 未发现 EXTRACTOR_SPEC / 未在求解前 stub plan 文件 [3/9 recent runs]
观察：脚本聚焦建模，从未把决策变量序列化到评测器 extractor 读取的路径，评测器报 `extraction_status: failed`，note `"No plan_file in EXTRACTOR_SPEC"`。Hub-spoke 任务尤其需要多种动作行（purchase / transship / state / substitute），单文件易遗漏。

**避坑**：**先锁 I/O 契约，再建模**。
```python
# 第 1 步：在写任何约束前，从 EXTRACTOR_SPEC 读取
plan_file = EXTRACTOR_SPEC["plan_file"]          # 路径
required_cols = EXTRACTOR_SPEC["columns"]        # schema
# 第 2 步：立刻写一个全零 stub，保证就算后续崩溃也有 artifact 可被评测
stub = pd.DataFrame([
    {"period": t, "product": p, "location": d, "order_units": 0}
    for d in LOCATIONS for p in PRODUCTS for t in PERIODS
])
stub.to_csv(plan_file, index=False)
# 第 3 步：建模 + 求解 + 覆盖 stub
...
# 第 4 步：post-solve 断言
assert os.path.exists(plan_file)
df = pd.read_csv(plan_file)
for c in required_cols: assert c in df.columns, f"missing {c}"
```
对 hub-spoke 替代/转运任务，按动作类型分多文件：
- `purchase` 行（仅 hub）：`period, product, location, order_units`
- `transship` 行：`period, product, from_location, to_location, transfer_units`
- `state` 行：`period, product, location, ending_inventory, shortage, waste`
- `substitute` 行：`period, product, location, substitute_product, sub_units`

#### replenishment-016: solver 状态未检查 / 不可行时静默写空 [5/9 recent runs, 支撑性问题]
观察：`prob.solve()` 返回 `Infeasible` 或 `Undefined`（常因冷藏容量过紧、EPS 安全边际+整数变量、保质期约束冲突），但脚本继续执行 `pulp.value(...)`，对未赋值变量返回 `None`，写入空字符串列。validity 直接归零，丢失对部分质量分的领取机会。

**避坑**：求解后立即检查状态，并准备**渐进松弛 fallback**：
```python
status = prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=120))
if pulp.LpStatus[status] != "Optimal":
    # Fallback 1：松弛 EPS / 缩短 lookahead 重解
    # Fallback 2：用贪心启发式生成可行解，覆盖 stub
    plan = greedy_replenishment(demand, capacity, shelf_life)