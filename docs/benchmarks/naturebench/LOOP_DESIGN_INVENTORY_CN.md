# Famou Loop 现有设计清单（NatureBench 口径）

> 更新时间：2026-08-30 CST
> 用途：在讨论新优化前先确认现状，避免重复提出已实现的机制。
> 每条注明**代码位置**与**是否有实测效果数据**。

---

## 一、总体架构

```
IdeaAgent ──push──> IdeaSpark/benchmark_attempt_queue ──lease──> ImplementActor
                              ↑                                       │
                         replay_tail                            submit_candidate
                              │                                       ↓
                    SearchPolicy(offer)                    evaluation_queue
                              │                                       ↓
                         feedback_mailbox <──── Evaluator Pool（可信进程）
                                                                      ↓
                                                ExpBank ──> cross_task_expbank
```

- **Orchestrator** 长生命周期 tick 循环，`runtime/orchestrator.py`（约 8000 行）
- **ImplementActor** 长生命周期、可 resume；一个 lineage 对应一个 actor
- **Evaluator** 在可信进程内运行，Agent 不可见 GT 与 evaluator 代码

### 并发与预算（`examples/naturebench/goal.yaml`）

| 项 | 默认 | 实跑常用 |
|---|---|---|
| `max_wall_time_hours` | 4 | 4（bench 硬约束） |
| `max_implement_lifetime_sec` | 14400 | — |
| `max_implement_turns_per_actor` | 3 | 3 |
| `max_run_attempts_per_actor` | 4 | 6 |
| `max_repairs_per_revision` | 1 | 1 |
| `idea_queue_high_watermark` | 3 | 4~5 |
| `evaluation_queue_capacity` | 3 | 5 |
| idea/implement/eval 并发 | — | 2/2/5，m2s 批 2/3/5 |

**实测占用**（29 个 opus run）：Idea slot 利用率 13.7%、81% 完全空闲；
Implement 77.2%、8% 空闲；Evaluator 15.8%。单次 idea 中位 5.2 分，
单次 implement 29.9 分，**产销比约 1:6**。

---

## 二、Idea 阶段

### 2.1 输出契约（`prompts/cli_agents/idea_agent_v3.md`）

强制 JSON 字段：`title` / `hypothesis` / `method` / `rationale` /
`implementation_plan` / `risks`，以及两块结构化声明：

- **`expected_return`**：`target_level`、`expected_metric.range`、`confidence`、
  `basis`（至少一条可核查依据）、`assumptions`。有 `score_interpretation` 时必填。
- **`resource_request`**：CPU 核数、主存、GPU 设备数与每设备显存、
  `expected_runtime_sec`。CPU 任务须显式写 `device_count=0`。

还有 `parent_idea_id` 与 `relation`（`derived_from` / `alternative_to` / `combines`）。

### 2.2 已写入 prompt 的算法设计指导（v2 段，L87-96）

- 必须使用**逐实例、逐子指标**反馈，不得只看聚合分
- **`worst_submetric` 与提升最小的实例列为一等目标**；改善最弱区域的同时不得让其余区域出现不可接受回退
- 按差距分型给出方向：
  - 所有子指标都略低 → 新建模假设/骨干/预训练信号/残差学习/多模型互补
  - 仅个别子指标明显更差 → 任务专属输出头、困难样本挖掘、按数据状态的专家混合、输出校准、按实例门控融合
- 每条 Idea 必须声明：预期失败模式、目标子指标或实例、可证伪的验证信号、相对已有方案的定位
- `refine`/`switch`/`fuse` 的最终选择**不由 Idea Agent 做**，由 Implement Agent 拿到实测结果后决定

### 2.3 跨任务经验库（v2 段，L81-85）

- Agent 侧只读快照挂在 `<expbank_dir>`，来源为项目级 `.famou/cross_task_expbank`
- **分层访问**：先读 `INDEX.md`，再按 `summary_path` 按需打开单篇 Markdown
- request 中**不内联正文、不内联路径**（实测 request 16266 字符全为任务本身）
- 要求把每条经验当作待验证假设，说明可迁移/不可迁移条件；`rationale` 或
  `expected_return.basis` 中至少引用一条实际可访问的 `summary_path`
- 失败经验同样要读，避免重复低收益路线

**索引结构**：`index.jsonl` 每条只含 `{domain, best_score, result,
evolution_summary, summary_path}`；正文按 6 个 domain 分目录存放。
注入时按 domain 过滤并排除本任务。

### 2.4 工具权限

Idea / idea_rank / experience_summary 角色只有 `Read,Edit`（无 Bash，不能执行）。
Implement 有 `Read,Write,Edit,Bash`。联网工具默认关闭，需显式
`--allow-network-tools`（NatureBench 禁止联网）。

---

## 三、搜索策略

### 3.1 PairwiseImproveSearchPolicy（`search/policy.py`）

评测完成后的续跑回合，同时提供：

- **`current_idea`**：与 `offered_idea` **信息对等**的完整 payload，外加
  `current_score` / `current_level` / `current_is_run_best` / `last_run`
- **`offered_idea`**：IdeaSpark 队首的新 idea
- Agent 选择 `refine` / `switch` / `fuse`，须给证据化理由

被拒的 offered idea 通过 `replay_tail` 回到队尾（不淘汰）。

### 3.2 refine_diagnostics（`orchestrator.py:797`）

非 repair 回合注入，字段：

```
schema_version, metric, direction, current_score, current_level,
run_best_score, run_best_attempt_id, current_is_run_best,
evaluated_attempts, target_level, target_score,
worst_submetric{instance, value, instance_count, others_mean, above_target_count},
last_run{...}
```

**刻意不含** `gap_to_target` 与 `steps_to_target`（判定为过度设计）。

### 3.3 last_run 实证（`orchestrator.py:737`）

`candidate_id`、`status`、`error`、`returncode`、`timed_out`、`duration_ms`、
`observed_memory_bytes`、`memory_limit_exceeded`、`cuda_out_of_memory`、
`termination_reason`、`expected_runtime_sec`，以及 `paths` 三个产物目录
（`code` / `output` / `evidence`）。**不含 stdout/stderr 正文**，Agent 需要时自行去目录查。

### 3.4 工程失败与研究决策分离

工程失败走 `repair` 分支（`is_repair=True`），**不下发 search_opportunity**。
实测 329 次 search_decision **全部**发生在"评测完成有分数"之后
（refine 46% / switch 7% / fuse 47%），工程失败触发 0 次。

### 3.5 冲刺期 Idea 排序（`_maybe_rank_queued_ideas`）

剩余 ≤1 小时时用独立 Judge Agent 对未实现 idea 重排，一次性、失败不重试。
本轮修正：触发门槛 `min_items` 2→**3**、超时 600→**1800 秒**、
新增独立的 `idea_rank_min_remaining_sec=900`（不再随超时上限联动）、
Judge 未声明 runtime/model/端点时**继承 Idea Agent 配置**。

### 3.6 Idea Judge 辩论（`_idea_debate_directive`，**本轮新增，默认关闭**）

与 3.5 对称：那个是"剩余 ≤1h 才开"，这个是"已跑 ≥1h **且**已有 in-task 证据才开"。
但**不是一次性的**——开启后每条新 Idea 都走，`activated_at` 只记首次。

**双闸门**（`scheduling.idea_debate.activation`）：

| 项 | 默认 | 依据 |
|---|---|---|
| `min_elapsed_sec` | 3600 | 兜底。实测每 run 中位产 11 条 idea，8 条落在头 1 小时，故此闸门本身挡掉约 **66%** |
| `min_evaluated_attempts` | 1 | 主闸门。开跑 45 分钟时 **65/79** 个 run 零评测结果，60 分钟时仍有 **54/79** 为零——时间是证据的糟糕代理 |
| `allow_cross_task_only` | false | 打开后可在无 in-task 证据时启用，Judge 只准引用跨任务经验 |

证据口径复用 `_finite_attempt_score`：只有 `evaluation.valid is True` 且分数有限的
attempt 才算证据，工程失败与被拒候选不算。

**两种模式**（`mode`）：

- `respond`（默认）：Judge 只出反馈，**resume 同一个 Idea Agent 分支**让作者回应，
  作者**有权拒绝**（原样重交即视为坚持，且立即结束不再纠缠）
- `rewrite`：Judge 直接给出改写后的完整 Idea

默认 `max_rounds: 1`。未知 mode 一律回落 `respond`（rewrite 影响更大，不能因配置写错被静默启用）。

**防同质化是这套设计的核心约束。** 实测刷新 run best 的 attempt 里
**56.1% 来自全新起头、与当时最优毫无血缘的路线**，**48.6% 的 run 最终最好的那版从未被改进过**。
因此两份提示词都**显式禁止**"要求 Idea 向当前最优靠拢"这类意见，`respond` 作默认。

**契约**：每条反对意见必须绑定可核查对象（实例名/子指标/`expbank/00NN`/
跨任务 `summary_path`/题面路径），`evidence_refs` 为空的意见在代码层被丢弃
（`_material_objections`）；必须允许 `has_material_objection: false`；不评分、不排序、不比较。
理由是实测 Judge **不会排序**——同题首发方案盲评 46 对里命中 76.1%，而"闭眼猜同一个模型"是 78.3%。

**失败降级**：Judge 调用失败、改写不合法、作者回应失败，一律退回上一版可用 Idea。
辩论是增益环节，不得成为 Idea 生产的新故障点。

判官模型走配置（`workers.idea_judge`），未声明时继承 Idea Agent 的 runtime/model/端点/凭据。
⚠️ 若配成非同厂模型（如 gpt-5.5），提交包的 `model` 字段需如实改为混合声明。

产物：`artifacts/idea_debate/*.md`（反馈正文）与 `*.json`（逐轮结论）；
成本单列 `idea_judge` 角色（`summarize_agent_costs.py`）。

---

## 四、Implement 阶段

### 4.1 显式提交协议（`implement_agent_v3.md` L16-32）

- 轻量 smoke test 后调 `submit_candidate.py`，声明 entrypoint / title / summary / files
- 返回 `accepted=true, action=park` 后**立即结束本回合**
- 拒绝时必须在**当前回合**修复重提，不得直接退出
- 提交后进程 park，评测结果回来时 resume 同一 session

**park 实现**：提交后 20 秒宽限，然后 `_stop_process_group`（SIGTERM，5 秒不退转
SIGKILL）。进程终止但 session_id 保留，后续 `--resume` 恢复上下文。

### 4.2 算法实现指导（v2 段 L58-64）

- 异质子指标须分别处理归一化、输出头、损失权重、校准
- 防数值尺度爆炸：提交前检查预测范围、均值标准差、缺失值行为、截断/逆变换、公开实例覆盖
- **弱实例策略须实现有界困难样本加权，并显式检查非目标实例是否回退**
- 专家混合/融合的门控须确定、内存有界、可复现
- 残差学习须先确认基线与残差同尺度

### 4.3 DDL 心跳

`deadline_heartbeat.trigger_after_sec=2400`（40 分钟）。到点中断当前激活、
resume 同一 session 并注入提醒。单次激活上限 `timeout_sec=3600`
（实传 `--timeout-sec 3570`）。

**实测无效**：31 次 `agent_timeout_before_submit` 全部跑满 59.5 分钟上限，
且全部已收到心跳提醒。

---

## 五、评测与合规

### 5.1 双层评测

- **公开预检** `run_public_eval`：只校验产物格式，不算分、不碰隐藏答案。
  实测 0 次触发（格式问题更早被 `artifact_validation` 拦下，后者也是 0 次）
- **正式评测**：可信进程内执行，返回 `aggregate_improvement` 与逐实例
  `raw_scores` / `per_instance_improvement` / `normalized_raw_scores`

### 5.2 Agent 视图脱敏（`_agent_view`）

只暴露安全字段；`valid is not True` 时透传 `error`。
`extra_public` 由可信 adapter 显式生成时允许保留 instance→metric 的有限嵌套。

### 5.3 Validity Judge

`JUDGE_MODEL=gpt-5.5`，容器内运行，结论写 `controller/judge_verdict.json`。
本轮修正：补齐 OpenAI 分支凭据别名与 base_url、启用时**启动即校验凭据**、
跨任务经验同步改为读补判批次结论（按 mtime 取最新确定性结论）。

### 5.4 V3 定向合规边界（两个 prompt 各一份，L98/L66）

三条禁止，均有历史违规依据：

1. 不得从文件名/标识符、其他划分或实例、公开目标值表、验证集目标值、
   伪 bulk 或 eQTL 轨迹、检索模板中**直接复制或恢复目标值**
2. 不得利用 evaluator 反馈**反解**固定测试输出、逐行增量、常量输出模式、
   评分公式或归一化悬崖
3. 不得让手写规则、固定映射表、领域模板、同位素技巧、参考结果或回退值
   **替代数据拟合的预测路径**

每条附**违规/合规对照示例**。明确允许：完整 evaluator 反馈、历史有效模型复用、
预训练组件、检索结果作输入特征、模型融合、科学约束。

**实测违规率**：deepseek 26.3%、glm-5.2 8.7%、opus-5 5.4%。

---

## 六、资源与健壮性

| 机制 | 实现 | 状态 |
|---|---|---|
| 主存软限额 | 超申报值只记录（`memory_over_request`），超容器上限才杀；`prlimit --as` 作硬限 | 已实现 |
| GPU 显存 | 由 `resource_request` 声明设备数与每设备显存，不指定卡号 | 已实现 |
| 资源准入 | 超任务总资源确定性拒绝；暂无余量进 `waiting_resources`，不算失败 | 已实现 |
| 进程组终止 | `_stop_process_group` SIGTERM→SIGKILL | 已实现 |
| 信号归因 | SIGKILL+cgroup OOM 计数 → `agent_killed_by_cgroup_oom`；无证据 → `agent_killed_sigkill`；SIGTERM → `agent_terminated_by_signal`。证据落 `failure.signal_evidence` | **本轮新增** |
| 超长 prompt | 超过 128 KiB 单参数上限时改走 stdin（后台线程写入） | **本轮新增** |
| 跨任务经验回流 | sync 读补判批次结论，opus 70 条已入池（53→128） | **本轮修复** |

---

## 七、ExpBank

每个 attempt 一条不可变记录：

```
attempt_id, lineage_id, parent_attempt_id, branch_id, idea, implementation,
search_decision, evaluation, status, score, promoted, failure, error,
conclusion, next_step, evidence_refs, paths, created_at, updated_at
```

配套 `SUMMARY.md`、`code/`、`evidence/`。

**记账规则**：`score` 取本次评测指标，与排行榜无关（每条 attempt 记自己的成绩，
不再错误地只给被提升为 best 的那条打分）。

**`SUMMARY.md` 的 `## 结果` 段（本轮新增逐实例视图）**：此前只有一个聚合标量的
JSON 块。聚合分是各实例 improvement 的算术平均，单个差实例就能把它压到达标线
以下，而"是哪个实例"在标量里完全不可见。实测 79 个 opus run 的 1109 份
SUMMARY.md 中含逐实例的是 **0 份**；而数据本来就在同目录的 `record.json`（855 份）
与 `evidence/evaluation.json`（830 份）里 —— Idea Agent 读 `SUMMARY.md` 的比例是
**83.4%**，读 `evaluation.json` 只有 **16.8%**。现在该段直接给出：

- 聚合指标 + "各实例算术平均"的口径说明
- **已达标实例数 / 实例总数**（improvement ≥ 0 即该实例达到 SOTA）
- **最差实例是谁、值多少、其余实例均值**
- 逐实例表：按 improvement 升序、最差实例加粗置顶，附该实例的原始子指标与达标标记

提取与"最差实例"归纳逻辑（`extract_per_instance_improvement` /
`worst_instance_summary`，`storage/expbank.py`）与 orchestrator 的
`refine_diagnostics.worst_submetric` **共用同一实现**，两处口径不允许漂移；
在 1916 条历史记录上验证重构前后逐条一致（0 处差异）。

> 只影响新写入的摘要。历史 run 的 `SUMMARY.md` 属于不可变证据，不回填。

**跨任务层**：run 结束时由 experience_summary agent 复盘，写
`cross_task_experience_record.json`，宿主机侧 sync 合并进
`.famou/cross_task_expbank`，按 domain 分目录 + `index.jsonl`。
`agent_visible` 仅在 gpt-5.5 判定 Valid 时为真。

---

## 八、已实测但效果不明或无效的机制

| 机制 | 实测结果 |
|---|---|
| refine_diagnostics 下发 | **行为显著改变**：switch 率 42%→7%、fuse 率 17%→47%（无 diagnostics 261 条 vs 有 329 条）。`current_is_run_best` 严格生效——是全场最优时 switch **0%**（142 次），非最优时 12%。<br>**但不按距目标差距分层**：gap ≤0.05 / 0.05–0.2 / 0.2–0.6 三档的 refine 率为 44%/41%/47%，无趋势（>0.6 档 refine 75% 但 n=24）。<br>⚠️ 前后对比跨批次，无 diagnostics 的样本多来自更早的 `old-policy-search-v4`、`20260811-search-v2`，同时存在模型与 prompt 版本差异，**因果未受控** |
| IdeaSpark 容量 4→5 | 无可见影响；产销比 1:6，队列深度非瓶颈 |
| DDL 心跳（40 分钟） | 31/31 超时案例均已触发心跳仍未交付 |
| 冲刺期 idea 排序 | 修正前真正生效仅 35%（34% 调用失败、31% 待选不足）；修正后未做对照 |
| 更多 attempt / 更多 lineage | attempt 数 r=0.055、lineage 数 r=-0.035，**均与成绩无关** |

---

## 九、已知未解决

1. **重复流程失败不改变后续行为**：31 次超时、21 次漏提交，系统无任何自适应
2. **26% 的 idea 到点作废**：373/373 全部发生在 4 小时截止那一刻，是产销比的必然结果
3. **25% 的 attempt 拿不到分数**：代码报错 13%、资源超限 15%、未按协议交付 21%、
   正式评测拒绝 28%、无法归因 13%
4. **数据暂存缺陷**：`s41592-025-02662-x` 官方 9 个实例只暂存 4 个，历史全部快照皆然
5. **`PROBLEM_SNAPSHOT_LINK` 有 bug**：符号链接指向容器挂载区外，故一直用全量拷贝

---

## 十、当前成绩

```
Match-SOTA  51/90 = 56.67%   （Surpass 22 + Match 29）
未 Match     35
Judge Invalid 1 / 数值不可信 1 / 无正式结果 2
```

剩余 35 个中，**12 个差距在 0.09 以内**（最近的 `s42256-024-00795-w` 仅差 0.0038），
其中 26/35 已被 opus 跑过。
