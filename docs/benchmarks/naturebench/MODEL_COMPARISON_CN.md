# Opus-5 与 GLM-5.2 / DeepSeek 的能力对照分析

> 更新时间：2026-08-30 CST（全量复核，修正 glm-5.2 侧 21 处过期数字）
>
> ⚠️ **数据快照口径**：本文所有统计基于统计时点 `.famou/naturebench-runs/` 的全部 run。
> glm-5.2 的 run 数在本文首版之后仍有增长（138→154 个已判定 run、2368→2499 份方案），
> 因此凡涉及 glm 侧的绝对数需以本文更新时间为准。opus-5 与 deepseek 的批次已终止，
> 数字稳定。同题对照的 70 组配对未受影响（新增 run 未改变各题最好成绩）。
> 数据来源：`.famou/naturebench-runs/` 全部 run 的 `expbank/*/record.json` 与
> `controller/run_summary.json`；盲评产物见
> `.famou/naturebench-judge-reruns/blind-method-review-swap-20260827/`
> 复现脚本：`.famou/naturebench-judge-reruns/blind_method_review_swap.py`

---

## 零、结果对照

### 同题对照（70 组，各取该模型最好成绩）

| 等级 | 基线 glm/ds | opus-5 |
|---|---:|---:|
| Surpass（g > 0.1） | 3 (4%) | **13 (19%)** |
| Match（0 ≤ g ≤ 0.1） | 25 (36%) | 28 (40%) |
| 未 Match（g < 0） | 42 (60%) | **29 (41%)** |
| **达标合计** | **28 (40%)** | **41 (59%)** |

```
分数中位   基线 -0.0607      opus +0.0130
逐题领先   opus 55/70 = 79%
```

**Surpass 数量是基线的 4.3 倍**（3 → 13），达标率从 40% 提到 59%。

> 70 组 = 90 个 case 中两侧都有可信分数的子集。剔除的 20 个里，11 个是基线原本
> 就达 Surpass、未安排 opus 重跑的题（计入会抬高基线一侧），另 9 个是 opus 无有效
> 分或指标爆炸。筛选链路见 2.1 节。

### 对官方 90-case 事实表的影响

按「gpt-5.5 Judge Valid 且分数最高」口径合并 Opus 七个批次（79 个 case）后：

| | 更新前 | 更新后 |
|---|---:|---:|
| Surpass | 11 (12.22%) | **22 (24.44%)** |
| Match | 27 (30.00%) | 29 (32.22%) |
| **Match-SOTA** | **38 (42.22%)** | **51 (56.67%)** |
| Judge Invalid | 4 | 1 |
| 数值不可信 | 2 | 1 |
| 无正式结果 | 2 | 2 |

**Surpass 占比翻倍，Match-SOTA 净增 13 道。**

### 三项行为差异

| | glm-5.2 | deepseek | opus-5 |
|---|---:|---:|---:|
| 单次 implement 时长中位 | 10.8 分 | 20.3 分 | **29.6 分** |
| 每 run attempt 数中位 | 14 | 16 | **13** |
| 违规率（gpt-5.5 判定） | 9.7% | **26.3%** | **5.4%** |
| 方案篇幅（估计 token 中位） | 958 | 614 | **1596** |

**Opus 做得最少、最慢、写得最长、最合规。** 详细口径与局限见下文各节。

---

## 一、结论摘要

在 74 组同题对照下，Opus-5 相对 GLM-5.2 / DeepSeek 的优势可归结为一句话：

**模型间的差距在首次提交时就已确定，迭代不改变胜负格局。**

⚠️ 这是关于**模型对照**的结论，不等于"迭代无用"——绝对成绩仍有相当部分靠迭代
取得，见 1.1 节。

| 指标 | 基线 glm/ds | opus-5 |
|---|---:|---:|
| 首个 attempt 分数中位 | -0.2637 | **-0.0867** |
| 最佳 attempt 分数中位 | -0.0607 | **+0.0130** |
| 迭代贡献（best − first）中位 | **+0.0779** | +0.0612 |
| 首发即崩坏（g < -0.5） | 34% | **19%** |
| 首发即可用（g > -0.1） | 34% | **54%** |
| 逐题首发领先率 | — | **80%** |
| 逐题最终领先率 | — | **79%** |

三点值得注意：

1. **首发领先 +0.1771，到最终收窄到 +0.0737** —— 迭代机制在削弱而非放大 Opus 的优势。
2. **Opus 的迭代贡献反而低于基线**（+0.061 vs +0.078）—— 基线起点差、迭代空间大。
3. **首发领先率 80% 与最终领先率 79% 几乎相同** —— 迭代没有改变模型间的胜负格局。
   但逐题看有 **21/70（30%）发生了胜负翻转**，只是两个方向数量相近（11 vs 10）
   而相互抵消。

---

## 1.1 迭代的实际贡献

上节结论只适用于模型对照。就单个 run 的绝对成绩而言，**迭代贡献显著**（68 个
opus run）：

| 观测 | 值 |
|---|---:|
| 靠迭代跨过 Match 线（首发 < 0，最好 ≥ 0） | **18/68 = 26%** |
| 首发即最好（迭代零增益） | 9/68 = 13% |
| 迭代增益 p25 / p50 / p75 / p90 | +0.011 / +0.051 / +0.192 / **+0.553** |
| 首发分与最终最好分相关 | Pearson r = **0.814** |

`r = 0.814` 意味着首发能解释约 66% 的方差，**另外 34% 由后续尝试决定**。

跨线幅度很大，不可能是调参所致：

| run | 首发 | 最好 | 增益 |
|---|---:|---:|---:|
| `s42256-022-00464-w` | **-3.2552** | +0.2304 | +3.49 |
| `s43588-024-00732-2` | -0.8058 | +0.5150 | +1.32 |
| `s43588-025-00872-z` | -0.6905 | +0.0997 | +0.79 |
| `s41467-025-63418-x` | -0.5768 | +0.0901 | +0.67 |
| `s41592-025-02983-x` | -0.5021 | +0.0506 | +0.55 |

最终计入正式表的 22 个 Surpass 中，多个 run 的首发是崩坏的
（`s42256-022-00464-w` 首发 -3.26）。按"首发定生死"的逻辑，这些成绩会被放弃。

### 但"多试"本身无效

| 关系 | Pearson r |
|---|---:|
| 已评测 attempt 数 ↔ 最好成绩 | **0.055** |
| 独立 lineage 数 ↔ 最好成绩 | **-0.035** |

| 评测次数 | n | 最好成绩中位 |
|---|---:|---:|
| 6–9 | 25 | +0.0128 |
| 10–13 | 20 | +0.0154 |
| 14+ | 15 | +0.0243 |

跑 6 次与跑 14 次的中位成绩只差 +0.011。**决定成绩的是"试对了"，不是"试得多"**
——这与 idea 之间重合度低、后续 idea 常带来质变的观察一致：那些 +0.55 以上的
迭代增益来自换思路，而非在原方案上调参。

### 对改进方向的含义

不应把预算从迭代转向首发（两者并发槽位本就解耦，缩短 implement 单次时长也不会
增加 idea 容量，反而产出半成品）。**应使每一次尝试——无论首发还是迭代——更可能
"试对"**：显式下发底层指标结构、强制声明目标-指标对齐、先导实验验证可行性、
以及重新设计 IdeaSpark 排序判据（该判据直接决定"下一个试什么"，实测其选择与
距目标差距无相关性）。

---

## 二、对照口径

### 2.1 样本：90 → 70 的筛选

```
正式表 case 总数                90
  ├─ opus 无有效分数            16   剔除
  └─ 两侧都有有效分数            74   配对
       └─ 指标爆炸 |g| ≥ 10      4   剔除
          最终对照              70
```

每侧取该 task 下**同模型的最高分 run**，best-vs-best 对照。

**剔除的 16 个（opus 无有效分数）**

其中 11 个 opus 从未跑过 —— 它们**原本就是 Surpass**（已是最高档，无提升空间，
未安排 opus 重跑）：`s41587-025-02688-8`、`s42256-025-01016-8`、
`s43588-024-00703-7`、`s41592-023-02148-8`、`s42256-022-00518-z`、
`s43588-025-00842-5`、`s43588-025-00798-6`、`s43588-024-00689-2`、
`s41551-024-01312-5`、`s41592-025-02776-2`、`s42256-023-00619-3`。

另 5 个 opus 跑过但未产出有效分：

| case | 原因 |
|---|---|
| `s41592-025-02662-x` | 数据快照只暂存 4/9 个官方实例（本方缺陷） |
| `s41592-024-02580-4` | 官方 GT 缺失 |
| `s43588-025-00878-7` | evaluator 缺陷 |
| `s42256-023-00712-7` | rerun-v3 未跑完 |
| `s41587-025-02585-0` | 排空阶段容器 Failed；ExpBank 有 -0.0618 但无 `run_summary.json` |

**剔除的 4 个（指标爆炸）**

| case | opus | 基线 |
|---|---:|---:|
| `s43588-025-00872-z` | +0.0997 | **+230365325.99** |
| `s43588-024-00730-4` | -499.15 | -119.78 |
| `s41592-025-02893-y` | -98.77 | -199.80 |
| `s41592-025-02886-x` | -56.45 | -12.36 |

第一项系指标除零，非真实分数。此类值会彻底带偏均值（未剔除时全样本均值为
`-3113049`），故按 `|g| ≥ 10` 统一剔除，统计一律使用中位数与逐题胜负。

**这 70 组的构成对 opus 偏严**：被剔除的 11 个原本就是基线的 Surpass 成绩，
计入会抬高基线一侧；但同时 opus 也没有在这些题上得分的机会。因此 70 组代表
"**两个模型都实际尝试过、且分数可信**"的可比子集。

### 2.2 已知混淆

本对照**不是严格受控实验**，以下因素未能对齐：

| 因素 | 说明 |
|---|---|
| 并发 | 基线多为 2/2/4，opus 为 2/2/5，m2s 批次（25个）为 2/3/5 |
| 跨任务经验 | opus 各批读到的都是 deepseek 时代的 53 条；opus 自己的经验因
| | judge 缺 key 未回流（该缺陷已修`） |

因此下述数字应理解为"**同 loop 架构下换模型的端到端效果差**"，而非纯模型能力差。

---

## 三、优势随基线水平的分布

| 基线区间 | n | 中位提升 | opus 赢率 |
|---|---:|---:|---:|
| g < -0.5 | 12 | **+0.7571** | **92%** |
| -0.5 ~ -0.1 | 16 | +0.0785 | 81% |
| -0.1 ~ 0 | 14 | +0.0571 | 93% |
| 0 ~ 0.1（Match） | 25 | +0.0077 | 72% |
| **> 0.1（已 Surpash）** | 3 | **-0.2677** | **0%** |

**Opus 的价值在"救回崩掉的方案"，不在"把好方案变更好"。** 已达 Surpass 的 3 组全输。

等级迁移：**升级 21 道，降级 4 道**。

---

## 四、行为差异

| model | runs | attempt/run | 单次 implement 时长 | 模型交互轮次 | 工程失败率 |
|---|---:|---:|---:|---:|---:|
| glm-5.2 | 165 | 14.0 | 10.8 分 | 31 | 14% |
| deepseek | 46 | 16.0 | 20.3 分 | 35 | 16% |
| **opus-5** | 78 | **13.0** | **29.6 分** | **39** | **23%** |

**Opus attempt 最少、单次最久、失败率最高，却赢 79%** —— 差异在单次质量而非数量。

两列的口径：

- **模型交互轮次** = `agent_usage.jsonl` 的 `provider_turns`（来自 CLI 自报的
  `num_turns`）。是 agent 与模型来回的对话轮数，**不等于工具调用次数** —— 一轮
  可并发调多个工具。实测同一次调用 `provider_turns=59` 而 `tool_use≈119`。
- **工程失败率** = `status == "engineering_failed"` 的 attempt 占全部 attempt 的
  比例。**这不是"代码写错了"的比例** —— 见下节。

---

## 4.1 工程失败到底是什么

`engineering_failed` 是**多个阶段的合并标签**（`orchestrator.py` 里七处赋值）。
把它当代码质量指标会读错。下表按 `failure.error_code` 归因，**分类合计与
`engineering_failed` 总数逐模型校验一致**。

### 归因分布

| 归因 | glm-5.2 | deepseek | opus-5 |
|---|---:|---:|---:|
| **代码报错**（非零退出/抛异常） | 33 (9%) | **25 (20%)** | 32 (13%) |
| **资源超限**（超时/主存/显存） | 82 (23%) | 29 (24%) | 38 (15%) |
| **agent 未按协议交付** | 14 (4%) | 15 (12%) | **52 (21%)** |
| 进程被外部终止 | 6 (2%) | 6 (5%) | 16 (6%) |
| CLI/API 运行时故障 | 10 (3%) | 4 (3%) | 10 (4%) |
| **正式评测拒绝** | 78 (22%) | **43 (35%)** | 69 (28%) |
| 无法归因（`implementation`） | 3 (1%) | — | 33 (13%) |
| 未落盘·CLI 失败 | 53 (16%) | — | — |
| 未落盘·无法归类 | 80 (24%) | — | — |
| **合计** | **359** | **122** | **250** |

⚠️ **glm-5.2 有 37% 的失败观测缺失**（`bio-all-v2-*` 批次的代码还没做 `failure`
结构化落盘，只有 error 字符串）。**glm 与另两者不可逐项比较**；可比的只有
「正式评测拒绝」一项。

### 各类的确切含义

**代码报错** —— `canonical_process_failed`。提交的代码正式跑了一遍，非零退出或
抛异常。**这才是"实现真的有 bug"。**

**资源超限** —— `canonical_timeout` / `canonical_memory_limit_exceeded` /
`canonical_cuda_out_of_memory`。代码跑得动，但跑不完或装不下。

`canonical_run` 这个 stage 合计 243 例，内部构成：

| error_code | 数量 | 占比 |
|---|---:|---:|
| `canonical_process_failed` | 90 | 37% |
| `canonical_timeout` | 72 | 30% |
| `canonical_memory_limit_exceeded` | 62 | 26% |
| `canonical_cuda_out_of_memory` | 17 | 7% |
| 其他 | 2 | 1% |

**即 `canonical_run` 里只有 37% 是"代码写错了"，62% 是资源估计与算法复杂度
问题** —— 方案可能是对的，只是没控住峰值内存或单例耗时。

**agent 未按协议交付** —— 两种性质不同的失败，合计占 opus 的
`engineering_failed` 21%（52/250），占其全部 attempt 的 **4.7%**（52/1101）。
注意 21% 是占比而非条数。

| error_code | opus 次数 | 含义 |
|---|---:|---|
| `agent_timeout_before_submit` | 31 | 单次激活跑到 DDL 仍未提交 —— **没做完** |
| `missing_explicit_submit` | 21 | 正常退出（rc=0）但没调 `submit_candidate` —— **做完了没交** |

**这 52 次不等于 52 个方案损失。** 失败后 orchestrator 会 resume 同一 actor：
涉及的 50 个 actor 中 **36 个（72%）后续产出了已评测候选**，14 个没有。

### `missing_explicit_submit`：resume 有效

三项核查：

1. 失败那一轮 `submitted=False`，10/10 全部如此
2. 8/10 在本轮开始前已收到新反馈（`evaluated` / `evaluation_failed` /
   `run_failed`），本来就该产出新版本
3. resume 回来后 agent 自己说明并补交：
   > "The failure was `missing_explicit_submit` — the previous session exited
   > cleanly but never called `submit_candidate.py`. Submitting now."
   > …"Submission accepted. `action: park` — the turn is complete."

**这是 agent 自身的失误，恢复机制能覆盖。**

注意区分证据：`submitted` 标志是**本次调用**的结果；actor 状态里的
`last_candidate_id` 可能来自该 actor 生命周期内更早的 attempt。原生 session 文件
包含该 session 的全部轮次（resume 复用同一 session_id），读取轨迹尾部得到的是
**最后一轮**，不是失败那一轮。

### `agent_timeout_before_submit`：现有恢复机制无效

相关配置（`goal.yaml` → wrapper 实参）：

| 参数 | 值 | 说明 |
|---|---|---|
| `timeout_sec` | 3600 → `--timeout-sec 3570` | 单次激活上限 59.5 分（留 30 秒收尾） |
| `deadline_heartbeat.trigger_after_sec` | 2400 → 40 分 | 中断并 resume，注入"该提交了"提醒 |
| `max_turns` | 400 | |

opus 全批次 31 次超时的实测：

```
时长中位 59.5 分，最大 59.6 分
跑满上限（>58 分）:  31/31
心跳已触发（激活>1）: 31/31
```

**31/31 全部跑满上限，且全部已经收到过 40 分钟心跳提醒** —— 不是"差一点没提交"，
而是收到提醒后又跑了 19.5 分钟仍未交付。

失败高度集中在少数 case：

| run | 超时次数 |
|---|---:|
| `opus5-v5-*-s43588-024-00730-4` | 4 |
| `opus5-v5-*-s43588-025-00872-z` | 4 |
| `opus5-m2s-*-s41592-024-02316-4` | 4 |
| `opus5-v5-*-s43588-025-00878-7` | 2 |

两类失败对恢复机制的响应完全不同：

| | 现象 | resume 效果 |
|---|---|---|
| `missing_explicit_submit` | rc=0 退出，忘了调 submit | **有效** —— agent 补交即可 |
| `agent_timeout_before_submit` | 跑满 59.5 分被中断 | **无效** —— 不是忘了，是做不完；resume 只会再消耗一小时 |

单次激活 59.5 分钟占 4 小时研究预算的 **25%**，超时 2~3 次即耗去大半。可改进方向：
心跳提前（40 分 → 20~25 分，使提醒落在还来得及收尾的时刻）、把心跳措辞从建议改为
"立即提交当前可运行的最小版本"、以及对同一 actor 连续超时提前终止。

**进程被外部终止** —— `agent_process_killed`，全模型合计 28 例。证据只能支持
"外部终止"，**不足以断定容器 OOM**：

| 观测 | 结果 |
|---|---|
| 进程自身内存 / 限额 | 中位 **0.7%**，最大 6.5% —— 排除进程级超限 |
| signal | SIGKILL 16 例、**SIGTERM 12 例** |
| `timed_out` | 全部 False —— 排除超时 |
| 同一 run 内 2 秒内成对被杀 | **仅 7 次，涉及 6/17 个 run** |

成对同时被杀是容器级 cgroup OOM 的判据（曾在 `s42256-024-00892-w` 上确证：
两次 SIGKILL 间隔 0.0 秒，该题数据 25 GB、两个 implement agent 并发各加载一份
超出容器 64 GiB）。但**其余 11 个 run 是单独被杀，原因未确证**；SIGTERM 那 12 例
更不符合内核 OOM killer 的行为（后者用 SIGKILL）。

**正式评测拒绝** —— `official_evaluation_failed`。最常见是"主实例评测不完整"。
**不全是方案的责任**：opus5-v1 那 12 例全部来自 `s41592-025-02662-x`：

```
NatureBench 主实例评测不完整: synthetic_simple, synthetic_complex,
smfish, telomeres, terra, synthetic_3d
```

后查明官方数据集有 9 个实例，**我们的快照只暂存了 4 个**（smfish 还只有 78/129
个文件），且全部历史快照都一样 —— 这道题从第一次跑起就物理上不可能达标。agent 在
拿到的 4 个实例上 F1 做到 0.95/0.81/0.82。

### 零发生的 stage

| stage | 说明 |
|---|---|
| `artifact_validation` | 产物格式校验失败 —— **0 次** |
| `public_evaluation` | 提交前公开预检，只校验格式、不算分（`benchmark.py:460`）—— **0 次** |
| `evaluation_infrastructure` | 评测设施自身异常 —— **0 次** |

三者代码里有分支但**在全部 4214 个 attempt 中一次都没触发**，不构成实际问题。
`artifact_validation` 为 0 说明产物格式问题都在 agent 自查阶段解决了；
`public_evaluation` 因此也不会被触及。

### 怎么读

**① Opus 失败率 23% 最高，代码类占比最低（代码报错 13% + 资源超限 15% = 28%）。**

**② Opus 的额外失败主要是"未按协议交付"21%（52/250，占全部 attempt 4.7%）。**
与它"单次跑 29.6 分钟、模型交互 39 轮"的行为一致：做得深，更容易撞上单次激活的
59.5 分钟上限。DeepSeek 该项 12%，glm 因观测缺失（3%，实际更高）无法比较。

但该占比不等同于成果损失：涉及的 50 个 actor 中 72% 通过 resume 产出了已评测候选。
其中 `missing_explicit_submit`（21 次）恢复机制有效，`agent_timeout_before_submit`
（31 次）无效 —— 后者 31/31 跑满上限且均已收到心跳提醒（详见 4.1 节）。

**③ DeepSeek 代码报错 20% 最高**，是三者中实现质量最弱的。

**④ 明确可修的只有一项：按数据量下调 implement 并发。**
`missing_explicit_submit` 属 agent 失误，方向是强化收尾约束（prompt 层面），
不是改判据；容器 OOM 只在 6/17 个 run 上确证，其余外部终止原因未明。

---

## 4.2 方案文本长度

直接比较字符数会得出错误结论，因为三个模型的书写语言分布差异很大。

### 语言分布：单篇内中英混杂，不是"有的中文有的英文"

中文字符占比的分布（占该模型全部方案的百分比）：

| 占比区间 | 0–10% | 30–40% | 40–50% | 50–60% | 60–70% | >70% |
|---|---:|---:|---:|---:|---:|---:|
| glm-5.2 | 88% | 1% | 7% | 3% | 0% | **0** |
| deepseek | 51% | 14% | 25% | 7% | 0% | **0** |
| opus-5 | 37% | 2% | 18% | 39% | 3% | **0** |

**没有任何一篇中文占比超过 70%** —— 纯中文文本（含标点数字）通常落在 70–90%。
这说明不存在"整篇用中文写"的方案：**中文用于论述与判断，技术术语、字段名、
路径、指标名始终保持英文**。

实例（opus，中文占比 55%）：

> 主指标 `backbone_recall` 是「参考核苷酸的糖/磷酸原子与最近预测核苷酸的匹配
> 平均距离 ≤ 5 Å」…而核酸骨架在 3-5 Å 密度里最稳健的可观测量不是可分辨的单个
> `C1'/P` 峰，而是一条管状密度脊

因此：

| model | 书写风格 |
|---|---|
| glm-5.2 | 88% 基本纯英文 |
| deepseek | 约一半纯英文，一半中英混写 |
| **opus-5** | **63% 中英混写**，中文占比集中在 40–60% |

### 原始字符数（有误导性）

| model | n | title | hypothesis | mechanism | 合计中位 |
|---|---:|---:|---:|---:|---:|
| glm-5.2 | 2499 | 113 | 868 | 2666 | **3688** |
| deepseek | 754 | 119 | 515 | 1069 | 1706 |
| opus-5 | 1101 | 99 | 700 | 2420 | **3193** |

按此看 Opus（3193）比 glm（3688）**短 13%** —— 但中文单字信息密度远高于英文，
而 Opus 有 63% 的方案含大量中文，该比较不成立。

### 按语言分层

| model | 语言 | n | 字符中位 | token 中位 |
|---|---|---:|---:|---:|
| glm-5.2 | 英文 | 2210 | 3924 | 981 |
| glm-5.2 | 中文混写 | 289 | 1419 | 858 |
| deepseek | 英文 | 383 | 2431 | 608 |
| deepseek | 中文混写 | 371 | 1113 | 620 |
| **opus-5** | **英文** | 411 | **6652** | **1663** |
| **opus-5** | 中文混写 | 690 | 2365 | 1520 |

**同为英文时 Opus 6652 字符 vs glm 3924 —— 长 70%。**

### 归一后（估计 token 数）

| model | n | p25 | p50 | p75 |
|---|---:|---:|---:|---:|
| glm-5.2 | 2499 | 772 | **958** | 1194 |
| deepseek | 754 | 535 | **614** | 684 |
| **opus-5** | 1101 | 1252 | **1596** | 2012 |

```
opus vs glm-5.2    1.67 倍
opus vs deepseek   2.60 倍
```

⚠️ token 数为估算：逐字符加权，中文 1 字 ≈ 1 token、英文 4 字符 ≈ 1 token。
中英混杂文本的真实分词更复杂（英文术语在中文语境中可能切得更碎），精确值需要跑
真实 tokenizer。量级关系不受影响。

### 两点观察

**篇幅随题目复杂度变化**。Opus 的字符数 p10–p90 为 1558–7974，跨度 5.1 倍；
glm 为 1735–5835，跨度 3.4 倍。Opus 不是固定套模板。

**长的是推理不是修饰**。Opus 的 `title` 中位 99 字符，反而比 glm（113）和
deepseek（119）**更短**；增量集中在 `hypothesis` 与 `mechanism`。

---

## 五、合规性

| model | 已判定 | Valid | Invalid | 违规率 |
|---|---:|---:|---:|---:|
| deepseek | 38 | 28 | 10 | **26.3%** |
| glm-5.2 | 154 | 139 | 15 | 9.7% |
| **opus-5** | 74 | 70 | 4 | **5.4%** |

DeepSeek 每四次有一次靠不合规手段拿分。Opus 违规率最低，且它跑的多为难题
（难题诱惑更大）。

---

## 六、方案质量盲评

### 6.1 方法

采用**顺序对消**设计：每对评两次并互换 A/B。

该设计是必需的 —— 单轮评判存在强位置偏好：在单轮实验中评判选 A 的比例达 70%
（而 opus 只有 49% 在 A 位），opus 在 A 位胜率 88%、B 位仅 49%，相差
**40 个百分点**。单轮结果无法反映方案质量，故不采用。

- 两次指向**同一份方案** → 一致判定，计入胜负
- 两次指向**同一个位置** → 位置驱动，丢弃

### 6.2 gpt-5.5 的完整 context

单条 user message，无 system prompt，无多轮对话。实测约 4774 字符。

```
You are reviewing two candidate research plans (A and B) written
independently for the SAME benchmark task. Each was the author's
FIRST submission for that task.

Judge which plan is more likely to score better on the task's official
metric. You do not know the actual outcome. Ignore writing style, length,
and language (one may be in Chinese) — judge only the substance of the
approach. Do not favour a plan merely because it appears first.

TASK ID: {task}

=== PLAN A ===
{a}

=== PLAN B ===
{b}

Return ONLY one JSON object, no prose:
{"winner": "A" | "B", "confidence": "low" | "medium" | "high",
  "primary_reason": one of {reasons},
  "justification": "<= 40 words, concrete and specific to these plans"}
```

`{a}` / `{b}` 只取 `record.json` 的 `idea.title` / `idea.hypothesis` /
`idea.mechanism`，两侧同样截断到 3000 字符。截断是必要的：在这 74 组配对的最佳
attempt 上，Opus 方案原始字符中位 4268 vs 基线 3001，不截会引入长度优势。
（该数字未做语言归一，全量口径见第 4.2 节。）

**泄漏检查逐项为"无"**：分数、模型名、run 路径、`aggregate_improvement`
数值、评测结论均未出现。

**局限**：只给 task id，**不给题面**。因此判定依据是"方案读起来是否合理"，
而非"是否契合该题具体要求"。

### 6.3 结果

```
顺序一致（保留）      46/69 = 67%
顺序翻转（丢弃）      23/69 = 33%   其中锁 A 位 21 例、锁 B 位 2 例
```

一致判定内：

| | |
|---|---:|
| 盲评认为 opus 更好 | **41/46 = 89%** |
| 该子集真实首发 opus 更高 | 36/46 = 78% |
| **盲评与真实分数一致率** | **35/46 = 76%** |

**opus 胜出时的主因分布**（含两次判定，n=82）：

| 主因 | 占比 |
|---|---:|
| **`metric_alignment`（训练目标与评测指标对齐）** | **65%** |
| `structural_prior`（不变性/结构先验） | 18% |
| `problem_diagnosis` | 6% |
| 其他 | 11% |

**基线胜出时的主因**（n=10）完全不同：

| 主因 | 占比 |
|---|---:|
| `resource_realism`（资源可行性更实际） | 50% |
| `structural_prior` | 40% |

即：**基线偶尔赢是因为方案更保守、更跑得动，不是思路更对。**

### 6.4 关于位置偏好是否解决

**保留的 46 题已解决** —— "一致"的定义即"换位后指向同一份方案"，这些判定与
顺序无关。

**但 89% 是筛选后子集上的数字，不能外推到全部 69 题。** 筛选方向是保守的：

| | n | \|分差\|中位 | opus 实际更好 |
|---|---:|---:|---:|
| 保留（一致） | 46 | 0.0887 | 78% |
| 丢弃（位置驱动） | 23 | 0.1028 | **87%** |

丢弃标准完全不看"谁是 opus"；且丢弃组里 opus 实际更优的比例**更高**，纳入只会
抬高胜率。

**准确表述**：在评判能给出顺序无关判定的 46 题中（占 67%），89% 指向 opus，
与真实分数一致率 76%（显著高于随机 50%）。剩余 33% 因判定由位置决定不予采信。

---

## 七、典型案例

### 案例 1：`s43588-024-00732-2` —— 损失函数对齐评测指标

**PDE 解算子学习。首发 opus -0.8058 vs glm-5.2 -8.8224（Δ+8.02，全场最大）**

glm-5.2：
> Geometry-Aware Fourier Neural Operator (GeoFNO) with Reference-Domain
> Spectral Layers —— FNO 在参考域上做谱卷积，通过 cross-attention 与 FiLM
> 调制注入几何条件

opus-5：
> 参考域 POD 降基 + **相对 L2 对齐训练**的几何依赖 PDE 解算子（每实例专属头）
>
> …直接用**逐样本相对 L2 作为损失**（而不是全局 MSE）…因为相对 L2 按样本能量
> 归一化，**低能量样本在 MSE 下被系统性忽视，正是聚合指标的主要损失来源**

盲评（两个顺序均判 opus，`metric_alignment`）：
> "A directly optimizes sample-wise relative L2 and exploits low-dimensional
> POD structure on fixed reference grids, with per-instance heads. B is a
> generic FNO with MSE and less tailored handling of the benchmark's target."

**要点**：官方指标是相对 L2，glm 用 MSE 训练；两者在低能量样本上的权重差异
巨大。Opus 在假设阶段就点明了这一点。

后续 opus 最终跑到 **+0.5150**（Surpass），glm 最好 +0.0710。

---

### 案例 2：`s41592-023-01955-3` —— 指标定义在什么几何上

**scRNA-seq 对比表示学习。首发 opus +1.1762 vs glm-5.2 -0.9424（Δ+2.12）**

glm-5.2：
> Contrastive VAE with Instance-Conditioned Encoder and Salient-Only KL
> Annealing —— 共享 encoder + 条件 one-hot，latent 分为 shared / salient，
> 只对 salient 施加 KL

opus-5：
> …**公开指标（ASW 为主，另有 ARI/NMI）直接在 target cells 的 salient 隐空间
> 的欧氏几何上计算**。因此 aggregate_improvement 由三个可分离因素驱动：
> (a) 忠实复现对比 count-VAE 的建模假设（原始 counts 上的负二项似然、
> library-size 缩放、shared latent 在 target 与 background 上同时拟合、
> salient latent 对 background 强制为零）…

盲评（`metric_alignment`，其中一次 confidence=high）：
> "A better matches a contrastive scRNA-seq metric on target-cell latent
> geometry: raw-count NB cVAE, explicit shared/background latent structure,
> leakage penalties, active-unit pruning, and multi-seed alignment."

**要点**：Opus 从"指标在哪个空间上算"反推建模约束，glm 停留在架构选择。

后续 opus 最终 **+1.4353** —— 全 benchmark 最高分之一，起点仅 +0.0063。

---

### 案例 3：`s43588-025-00917-3` —— 构造正确的不变性

**纳米颗粒发光预测，train 0-2 壳层 → test 4 壳层的外推任务。**
**首发 opus +0.3925 vs glm-5.2 -2.3555（Δ+2.75）**

glm-5.2：
> 物理特征工程（层体积、掺杂浓度与空间分布、层间能量转移代理量、光谱重叠
> 指标）压成**固定长度、壳层数无关的特征向量** + LightGBM/CatBoost/MLP 集成

opus-5：
> …UCNP 的发光由每种镧系元素的**连续径向浓度剖面 c_e(r)** 和外半径决定，
> 而非离散层索引或壳层数。因此把颗粒表示为**绝对网格上的定分辨率径向剖面**
> …使模型**对"同一均匀区域如何切分成层"完全不变**，从而把 4 壳层的外推问题
> 消解掉

盲评（**位置驱动，两次都选 B 位，判为不可判定**）：
> order1（B=基线）："B uses feasible fixed-length, shell-invariant tabular
> features…A relies on an impractical full-radius grid using test-set maxima"
> order2（B=opus）："B uses a shell-count-invariant radial profile that
> directly matches the physics and OOD arity gap"

**要点**：这是**位置偏好的典型受害者**。两次都选 B 位，但两次的理由都在赞美
放在 B 位的那份方案 —— 说明评判在读内容，只是无法克服位置锚定。

真实结果站在 opus 一侧（首发 +0.39 vs -2.36，最终 +0.7005 Surpass）。

---

### 案例 4：`s42256-022-00464-w` —— 方案对但首次实现崩了

**首发 opus -3.2552 vs glm-5.2 -0.6560（opus 落后 2.60）**
**盲评却一致判 opus 更好**

opus-5：
> Neutral-mode quotienting for effective dynamics —— …两个实例的长时程分数
> 都由动力学中**唯一那个边缘稳定（"中性"）方向**主导，而不是由收缩/扩张方向
> 主导；而 latent RNN、储备池和 PDE 辨识流程**都把容量花在后者上**

盲评（`metric_alignment` / `problem_diagnosis`）：
> "A targets the key long-horizon failure modes: FHN phase drift and KS
> attractor stability/correlation. B's autoregressive ESN with ensemble
> averaging is likely to phase-drift on FHN and collapse/smooth chaotic KS
> forecasts."

**要点**：这是 11 例判错中**唯一实质性的一例**。方案诊断是对的（最终 opus 跑到
**+0.2304**，glm 最好 -0.6085），但首次实现出了问题导致 -3.26。

**说明方案质量与首发分数不是一回事** —— 盲评看方案看对了，看结果就错了。

---

### 案例 5：`s42256-025-01042-6` —— 基线赢在保守

**首发 opus -0.2028 vs 基线 -0.4289（opus 实际更好）**
**但盲评一致判基线更好，主因 `resource_realism`**

盲评：
> "B relies on a proven ProteinMPNN-style baseline with separate
> cath_4_2/cath_4_3 training and feasible hyperparameters. A is more novel
> and metric-aware, but its CMLM/BLOSUM refinements add risk and complexity
> under the 1× budget."

**要点**：基线胜出的 5 例里有一半是这个模式 —— **评判认为 opus 的方案更冒险**。
在 4 小时硬预算下这个担忧是合理的，只是这一题没有兑现。

---

### 案例 6：判错集中在分差极小处

11 例判错中有 4 例首发分差在 0.003 以内：

| task | opus 首发 | 基线首发 | 分差 |
|---|---:|---:|---:|
| `s42256-022-00459-7` | +0.0093 | +0.0080 | 0.0013 |
| `s42256-023-00611-x` | +0.0136 | +0.0160 | 0.0024 |
| `s43588-024-00716-2` | -0.0900 | -0.0897 | 0.0003 |
| `s42256-025-01019-5` | -1.0000 | -1.0000 | 0.0000 |

这种量级读方案本来判不出来，属噪声。**76% 的一致率应扣除这部分再理解。**

---

## 八、可信度分层

| 结论 | 证据强度 | 依据 |
|---|---|---|
| 首发崩坏率 34% → 19%，可用率 34% → 54% | **强** | 分数分布，不依赖任何模型判定 |
| 80% 的题首发即领先，中位 +0.1771 | **强** | 同题逐对比较 |
| 优势随基线变差而增大（g<-0.5 时 +0.757/92%） | **强** | 分档统计，n=12~25 |
| 违规率 5.4% vs 26.3%(ds) / 8.7%(glm) | **强** | gpt-5.5 判定结果 |
| 已 Surpass 的题 opus 无优势 | **中** | 方向明确但 n=3 |
| 方案质量差异主要在"目标↔指标对齐" | **中** | 盲评 65%，位置偏好已剔除但样本经筛选 |
| 模型间差距在首发确定，迭代不改变胜负格局 | **强** | 首发领先率 80% ≈ 最终 79%（70 组） |
| 迭代对绝对成绩贡献显著（26% 靠迭代跨线） | **强** | 68 个 run，r=0.814 留 34% 方差 |
| ~~"多试"提升成绩~~ | **已否证** | attempt 数 r=0.055、lineage 数 r=-0.035 |
| Opus 方案篇幅约为 glm 的 1.7 倍、deepseek 的 2.6 倍 | **中** | 全量 4354 份方案，但 token 数为逐字符估算（见 4.2 节） |
| 三模型均为单篇内中英混杂，无整篇中文方案 | **强** | 中文占比分布无一超过 70%（4.2 节） |
| 关键词匹配可识别方案质量差异 | **否** | 关键词统计 14% vs 16%（方向相反），而语义盲评 65% —— 该属性无法用关键词度量 |

### 度量方式的选择

同一个假设（"opus 更善于对齐目标与指标"），两种度量给出相反结果：

| 度量方式 | 结果 |
|---|---|
| 关键词正则匹配方案文本 | 基线 14% vs opus 16% —— 无差异 |
| gpt-5.5 语义盲评（顺序对消） | opus 胜出主因 65% 为该项 |

"训练目标是否对齐评测指标"是语义属性，同一含义可有上百种表述，**关键词匹配无法
度量**。评估此类属性应使用语义判定，并配合位置对消与准确率校验。

---

## 九、工程含义

1. **提升单次尝试的命中率，而非调整首发与迭代之间的预算配比。**
   首发解释约 66% 的方差（r=0.814），另 34% 由后续尝试决定，26% 的 run 靠迭代
   跨过 Match 线 —— 两者都重要。同时"多试"本身无效（attempt 数 r=0.055），
   决定成绩的是"试对了"。Idea 与 Implement 的并发槽位相互独立，缩短 implement
   单次时长不会增加 idea 容量，只会产出半成品。

2. **Idea 阶段是唯一有闲置容量的环节** —— slot 利用率 13.7%、81% 时间完全空闲，
   而 Implement 是 77.2%。可承载先导验证（light experiment agent，见
   arXiv:2608.13940 的 agentic RPM，实证 0.684 → 0.729）而不与 Implement 抢时间。

3. **Idea Agent 拿不到底层指标定义。** 请求中的 `score_interpretation` 只给出
   `aggregate_improvement` 的分档规则（<0 / 0~0.1 / >0.1），底层指标（相对 L2、
   ASW/ARI/NMI 等）只存在于 `problem/` 题面中，需 Agent 自行挖掘。而盲评显示
   Opus 首发优势的 65% 来自目标-指标对齐 —— 该能力目前依赖模型自觉，未被系统
   约束或支持。

4. **IdeaSpark 排序判据需要重新设计。** 实测排序选择与"距目标差距"无相关性
   （refine 占比在各 gap 段为 63%/47%/75%/100%，无趋势）；唯一有效信号是
   `current_is_run_best`（是最优时 switch 0%，非最优时 16%）。该判据直接决定
   "下一个试什么"，而 34% 的方差正由后续尝试决定。

5. **超时失败的可改点在心跳，不在总时长。** 31 次 `agent_timeout_before_submit`
   全部跑满 59.5 分钟上限，且全部已收到 40 分钟心跳提醒仍未交付 —— 说明问题不是
   时间不够，而是提醒无效。可改心跳措辞（建议 → "立即提交当前可运行的最小版本"）
   与时机，以及对连续超时的 actor 提前终止；缩短总时长会牺牲正常完成的回合。

---

## 十、数据位置

- 同题配对与首发分数：`/tmp/pairs.json`、`/tmp/first.json`（重跑本文脚本可再生成）
- 盲评 v1（位置偏好污染，仅留档）：
  `.famou/naturebench-judge-reruns/blind-method-review-20260827/results.json`
- 盲评 v2（顺序对消，本文采用）：
  `.famou/naturebench-judge-reruns/blind-method-review-swap-20260827/results.json`
- 盲评脚本：`.famou/naturebench-judge-reruns/blind_method_review_swap.py`
- 各 run 的方案原文：`<run>/expbank/<NNNN>/record.json` 的 `idea` 字段
