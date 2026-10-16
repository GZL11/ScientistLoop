# Famou-Bench 实验方案

## 目标

评估 opencode_famou 的核心能力，优先级排序：

1. **快且有效**（P0）：agent 能否在合理时间内产出有效方案（validity=1）
2. **澄清能力**（P0）：给定最简提问，agent 能否通过澄清补齐信息差
3. **解题质量**（P1）：方案的优化质量；quality 的上限可交给 evolve loop 拔高

## 实验设计

### 实验总览

| 编号 | 实验名称 | runner | prompt | answerer | 说明 |
|---|---|---|---|---|---|
| A | 天花板 | `cc_native` | instruction.md | `api` | 最强 agent + 完整信息，质量上限 |
| B | 端到端能力 | `opencode_famou` | instruction.md | `api` | opencode_famou 完整信息下的执行能力 |
| C | 澄清+执行 | `opencode_famou` | query | `api` | 通过澄清补齐信息后的端到端效果 |
| D | 澄清下限 | `opencode_famou` | query | `default-value` | 不澄清（全部默认值）时的执行效果 |

### 运行命令

```bash
# A. 天花板
python -m webagent.runners.cli.run_b3 --case all --runner cc_native --answerer api --runs 3

# B. 端到端能力
python -m webagent.runners.cli.run_b3 --case all --runner opencode_famou --answerer api --runs 3

# C. 澄清+执行
python -m webagent.runners.cli.run_b3 --case all --runner opencode_famou --answerer api --query-variant default --runs 3

# D. 澄清下限
python -m webagent.runners.cli.run_b3 --case all --runner opencode_famou --answerer default-value --query-variant default --runs 3
```

### 运行参数

- case：所有有澄清体系的 case（有 gt.json + queries/default.md 的，共 19 个）
- runs：每组 3 次，取均值消除随机性

## 指标定义

### 直接指标

| 指标 | 来源 | 优先级 | 说明 |
|---|---|---|---|
| validity_rate | B3 result.json | **P0** | 有效方案比例（validity_score=1 的 run 数 / 总 run 数） |
| duration | agent_run.json | **P0** | 运行时长（started_at → finished_at） |
| coverage_score | eval_clarify.py | **P0** | 澄清覆盖率，(covered + 0.5×partial) / total_keys |
| quality_score | B3 result.json | **P1** | 端到端执行质量（validity × quality） |
| rounds | dialog.json | 辅助 | 澄清对话轮数 |

### 对比指标

| 指标 | 计算方式 | 含义 |
|---|---|---|
| 有效性差距 | B.validity_rate − A.validity_rate | opencode_famou 与天花板的有效性差距 |
| 速度比 | A.duration / B.duration | opencode_famou 相对天花板的速度 |
| 信息恢复率 | (C.quality − D.quality) / (B.quality − D.quality) | 澄清补回了多少信息差 |
| 澄清增益 | C.quality − D.quality | 澄清相比不澄清的质量提升 |
| 澄清有效性增益 | C.validity_rate − D.validity_rate | 澄清对有效性的提升 |

## 实验对比与分析

### 对比 1：有效性与速度（B vs A）— P0

**看什么**：opencode_famou 在完整信息下能否快速产出有效方案。

**指标**：
- validity_rate：A 和 B 各自多少比例的 run 产出了有效方案
- duration 中位数：平均耗时对比

**解读**：
- validity_rate ≥0.8 + 速度更快：核心目标达成，quality 可交给 loop 优化
- validity_rate <0.6：有效性本身就有问题，需要优先排查 agent 的理解和执行能力

### 对比 2：澄清对有效性的影响（C vs D vs B）— P0

**看什么**：澄清是否帮 agent 产出了更多有效方案。

**指标**：
- B.validity_rate（完整信息） vs C.validity_rate（澄清后） vs D.validity_rate（不澄清）
- C.duration vs D.duration：澄清带来的额外时间开销

**解读**：
- C.validity >> D.validity：澄清对有效性有直接贡献
- C.validity ≈ D.validity：澄清没帮上忙，要么问的不对，要么 agent 本来就能猜对约束
- C.duration − D.duration：这是澄清的时间代价，需要和有效性增益权衡

### 对比 3：澄清覆盖率（C 组）— P0

**看什么**：agent 通过提问覆盖了多少 gt.json 中的信息点。

**指标**：coverage_score（C 组每个 case）

**解读**：
- coverage 高 + validity 高：澄清到位且执行有效
- coverage 高 + validity 低：问对了但没用好（执行层面问题）
- coverage 低 + validity 低：没问到关键约束，导致方案不合法

### 对比 4：解题质量（P1，仅在有效方案上看）

**看什么**：在有效方案中，quality 水平如何。

**指标**：
- 执行能力比 = B.quality / A.quality
- 信息恢复率 = (C.quality − D.quality) / (B.quality − D.quality)

**注意**：quality 只在 validity=1 的 run 上有意义。quality 的提升是 P1 目标，可通过 evolve loop 迭代优化。

**示例**：
```
B.quality = 0.85（完整信息，有效方案均值）
C.quality = 0.72（澄清后，有效方案均值）
D.quality = 0.45（不澄清，有效方案均值）

信息恢复率 = (0.72 − 0.45) / (0.85 − 0.45) = 67.5%
→ 澄清补回了 67.5% 的信息差
```

### 按 case 分析

对每个 case 输出：

| case | A.valid | B.valid | C.valid | D.valid | coverage | B.time | C.time | B.quality | C.quality |
|---|---|---|---|---|---|---|---|---|---|
| 05_city_delivery_routing | 3/3 | 3/3 | 2/3 | 1/3 | 0.83 | 8m | 12m | 0.88 | 0.76 |
| ... | | | | | | | | | |

重点关注：
- **B.valid 高但 C.valid 低** 的 case：澄清没帮上忙，需要看 coverage 找缺失的关键约束
- **B.valid 低** 的 case：执行能力本身不足，与澄清无关
- **D.valid 就很高** 的 case：问题简单，不依赖澄清，可考虑从澄清评测集中排除
- **C.time 远大于 B.time** 的 case：澄清轮次过多或效率低

## 扩展实验（低优先级）

以下实验在核心实验完成后按需进行：

| 编号 | 实验 | 说明 |
|---|---|---|
| E | `opencode_native` + instruction | 对比基线：看 famou 双 agent 架构相比原生的增益 |
| F | `opencode_famou` + query + `api:minimal` | 简短回答风格：测 agent 从有限信息中提取关键点的能力 |
| G | B2 纯澄清 | 只跑澄清不执行，快速迭代 agent 的澄清 prompt |
