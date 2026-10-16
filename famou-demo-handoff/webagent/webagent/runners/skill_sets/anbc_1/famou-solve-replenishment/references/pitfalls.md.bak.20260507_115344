# 补货 / 采购常见坑 + 退出自检清单

> 本文件中的具体数字(如"5 DC × 3 SKU × 20 周 = 300 行"、"占比 ≤ 40%")
> 都是**典型样貌**,用于说明踩坑形态。**真正的约束以用户提供的问题描述为准**——
> 可能是 7 仓 4 SKU 12 期、占比上限 30%、其他字段名。读 pitfall 时关注**形态**而非具体数字。

## 通用坑

### 坑 0:库存守恒方程写错符号 / 漏项

最常见的 bug。建议在脚本里**先用注释把方程写出来**,每个 +/- 项都标注:

```python
# inv[t] = inv[t-1]
#        + arrival[t]              # 到货(提前期=0 即 order[t],否则 order[t-L])
#        - demand[t]
#        + short[t]                # 占位变量:未满足的需求(注意是 + 不是 -)
#        - waste[t]                # 损耗
#        + sub_in[t] - sub_out[t]  # 替代品双向(仅与 SKU 相关)
#        + transferred_in[t] - transferred_out[t]  # 调拨双向(Hub-Spoke)
```

再实现。**`short` 是加号不是减号**——它代表"未消耗的部分"。

### 坑 1:交付字段名/文件名/行数不匹配

若问题描述写"N DC × M SKU × T 期 = N×M×T 行(不含表头)",必须刚好匹配。
零下单的也要写出来(`order_qty=0`、`end_inventory` 计算正确)。
中英文字段名(如 `网点编码`、`期初库存`、`order_qty`)逐字保留。

### 坑 2:MILP "Optimal" 不等于建模正确

求解器在你写下的约束里最优。运行后**用独立验证**(另写一段函数 / 另写一脚本 / 不同实现思路)逐 `(dc, sku, t)` 验证守恒、容量、合同、占比。

### 坑 3:big-M 设置太大(数值不稳)

`big_M = 1e9` 在 CBC 里常导致 LP relaxation 数值漂浮。
合理值:`big_M = total_demand * 1.5` 或同量级常量。

---

## 子族 A 专属坑(多 DC 独立)

### 坑 A1:替代方向反了

通常是 **Premium 替代 Basic**(高替低)。
错误建模:`sub_in[basic, t]` 来自 `sub_out[basic, t]`(自己替自己——荒唐但常见)
正确:`sub_in[basic, t] == sub_out[premium, t]`,且 `sub_out[premium, t] <= inv[premium, t]`。

**Hub-Spoke 额外检查**:若问题同时含 Hub-Spoke 结构,替代的 `sub_in / sub_out` 项必须同时出现在**中央仓**和**地区仓**的守恒方程中——只在其中一层加,会产生虚空库存。

### 坑 A2:保质期约束太松或太紧

- 近似法 `inv[t] <= sum(demand[t..t+shelf-1])` 容易过紧(不允许任何安全库存)
- 精确批次法 `batch[..., t_arr, t]` 变量数会爆(数百 → 数千)
- 折中:用近似法 + 在目标里加大损耗惩罚,让求解器自然规避囤积

**短保质期场景（shelf_life - lead_time ≤ 2 期）额外注意**:

- 该近似约束可能在低需求 DC（如需求份额 ≤ 15%）中过紧，迫使安全库存为零、引发可避免缺货。
  可放宽为 `inv[dc,sku,t] <= sum(demand[dc,sku,t..t+shelf_life]) * 1.05`（仅对短保 SKU）。
- 约束必须**按 DC 分别施加**，而非全网汇总——地区仓需求与中央仓独立，汇总约束会掩盖局部过剩。
- "零废弃"出现在 4 周保质期 SKU 的验证结果里是**危险信号**，需检查约束是否失效，而非视为优化成功。

### 坑 A3:产能"全网合计"误写为"每 DC"

问题描述写"全网所有 DC 同 SKU 总采购 ≤ X 件/周"。
错:`sum_t order[dc, sku, t] <= X`(按 DC 限)
对:`sum_dc order[dc, sku, t] <= X`(每周按 SKU 跨 DC 求和)

**产能约束符号**:使用 `<=` 而非 `<`。验证时容差设为 `1e-4`，不得用 `1.0`——精度过松会放过真实违反。

### 坑 A4:DC 容量按"件数"还是"加权占用"

冷藏/体积场景需用 `usage_per_unit[sku]`(不同 SKU 占空间不同)。
错:`sum_sku inv[dc, sku, t] <= cap[dc]`
对:`sum_sku inv[dc, sku, t] * usage_per_unit[sku] <= cap[dc]`

**建模前强制步骤**:在代码注释中逐字写出加权容量约束，并核查 `cold_usage` 字典是否包含全部 SKU 的正确值（例如：普通品 1.0、优质品 3.0、短保品 1.2）。写出后再实现，防止字典遗漏或数值填错。

### ⚠️ 坑 A5：批次追踪 MIP + FIFO 仿真 = 冷藏容量隐性违反（高频、全零）

**这是最高优先级的禁止项。违反此条必定导致评分为零。**

**现象**：求解器报 Optimal，agent 自验"零容量违反"，最终评分 0.0，评估器报大量
`Cold storage capacity exceeded at DC_X in period Y`。
另一诊断信号：agent 自报持仓成本 X，评估器计算出的持仓成本 Y ≈ 1.5–2× X，
说明 FIFO 仿真比 MIP 保留了更多库存，容量违反在所难免。

**根本原因**：

批次追踪 MIP 引入了连续流变量 `flow[dc, sku, batch_tau, t]`，求解器用**最优流分配**
（把某期消耗量拆给多个批次）满足容量约束——但这套分配是"数学最优"，物理上
**不遵循 FIFO**。随后用 FIFO 仿真重放同一份下单计划时，批次消耗顺序不同，
库存剖面（inventory profile）也不同，容量约束就会被突破。

而且 agent 的自验函数通常调用 MIP 内部的 `inv` 变量值（已按 MIP 最优分配），
不调用 FIFO 仿真的结果，所以自验会通过但评估器会失败。

**强制规则（硬性禁止，无例外）**：

> **NEVER** 使用批次追踪 MIP（即带 `flow[dc, sku, batch_tau, t]` 变量的模型）。
> **ALWAYS** 使用聚合库存模型（单一 `inv[dc,sku,t]` 变量，不拆批次）。
> 若代码中出现任何形如 `flow[..., batch_tau, ...]` 的变量，**必须重写**。

**正确做法：使用 aggregate inventory 模型**（参见 `code_templates/replenishment_milp_template.py`）：

```python
# ============================================================
# 强制建模前检查：在此处写出完整约束形式，再实现
# ============================================================
# 聚合库存（单变量，不拆批次）
# inv[dc, sku, t] >= 0

# 库存守恒（arrival 用提前期偏移）
# inv[dc,sku,t] == inv[dc,sku,t-1] + arrival(dc,sku,t)
#               - demand[dc,sku,t] + short[dc,sku,t]
#               - waste[dc,sku,t]
#               + sub_in[dc,sku,t] - sub_out[dc,sku,t]

# 冷藏容量约束（加权占用，覆盖所有 DC 包括地区仓）
# sum_sku inv[dc, sku, t] * cold_usage[sku] <= capacity[dc]   ∀ dc, t

# 保质期用近似约束（不拆批次）
# inv[dc, sku, t] <= sum(demand[dc, sku, t..t+shelf_life-1])
# ============================================================

# 示例实现：
inv = {(dc, sku, t): model.addVar(...) for dc in DCs for sku in SKUs for t in periods}

for dc in DCs:
    for t in periods:
        model += (
            lpSum(inv[dc, sku, t] * cold_usage[sku] for sku in SKUs)
            <= capacity[dc]
        )
```

**聚合库存模型中 MIP 约束的 `inv[dc,sku,t]` 与任何 FIFO 仿真使用的库存值完全相同**
（单一聚合量，没有"流分配"歧义），约束保证有效。

**保质期近似约束偏紧时的调整**：若求解器无法找到可行解，可放宽为：
`inv[dc, sku, t] <= sum(demand[dc, sku, t..t+shelf_life]) * 1.1`（容忍 10% 安全库存）
并在目标函数里增大损耗惩罚权重，让求解器自然规避囤积。

**FIFO 独立仿真（强制门控，缺此步不得提交）**：

```python
def independent_fifo_simulation(order_csv_path, demand_data, cold_usage, capacity):
    """
    仅从输出 CSV 读取 order_qty，不引用任何 MIP 变量。
    逐期重放库存，验证冷藏容量约束。
    """
    orders = pd.read_csv(order_csv_path)
    inv = {(dc, sku): initial_inv[dc, sku] for dc in DCs for sku in SKUs}
    violations = []
    for t in periods:
        # 到货（考虑提前期偏移）
        for dc in DCs:
            for sku in SKUs:
                arrival = orders[(orders.dc==dc)&(orders.sku==sku)&
                                 (orders.period==t-lead_time[sku])]['order_qty'].sum()
                inv[(dc,sku)] = inv[(dc,sku)] + arrival - demand[dc,sku,t]
                inv[(dc,sku)] = max(inv[(dc,sku)], 0)  # 缺货截断
        # 检查容量
        for dc in DCs:
            load = sum(inv[(dc,sku)] * cold_usage[sku] for sku in SKUs)
            if load > capacity[dc] + 1e-6:
                violations.append((dc, t, load, capacity[dc]))
    return violations

# 调用并断言
violations = independent_fifo_simulation(...)
assert len(violations) == 0, f"FIFO 仿真发现容量违反: {violations[:5]}"

# 额外：比较 FIFO 持仓成本与 MIP 持仓成本
assert abs(fifo_holding_cost - mip_holding_cost) / mip_holding_cost < 0.05, \
    "持仓成本差距 > 5%，怀疑批次追踪 MIP 歧义，请用聚合库存模型重写"
```

**Hub-Spoke 场景额外要求**：独立仿真必须覆盖**所有 DC（含地区仓 DC2–DC5）**。
建模完成后，显式列出模型中所有容量约束，逐一确认每个 DC 都有对应约束行，不得遗漏地区仓。

---

## 子族 B 专属坑(Hub-Spoke)

### 坑 B1:忘记"调拨量 ≤ 中央仓当期可用库存"

否则 MILP 会无限调拨,地区仓库存够而中央仓变负。
等价的两种正确建模:
1. 显式:`sum_dc allocate[dc, sku, t] <= inv_central[sku, t-1] + purchase[sku, t]`
2. 用 `inv_central` 守恒 + 非负约束(`inv_central[t] >= 0` 隐含此条)

### 坑 B2:地区仓"采购"未禁

若地区仓不可直采,必须 `order[dc, sku, t] == 0  for dc != central`。

### 坑 B3:调拨费按量 vs 按批次

"X 元/件"是按量。若问题描述给"固定费 + 变动费",需引入 `ship[dc, t]` 二元变量。

### ⚠️ 坑 B4:调拨时机过晚导致高峰缺货（Hub-Spoke 时序优化）

**现象**：MILP 返回 Optimal，缺货惩罚占总成本 > 25%，而中央仓存有足量库存。

**根本原因**：MILP 默认延迟调拨（推迟持仓成本），但高峰