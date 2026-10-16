# Loop Prompt 版本台账

> 用途：记录 `famou_scientist/loop/prompts/` 下各角色提示词的版本、切换方式、
> 每版改了什么、以及**改动是否有实测支撑**。
> 规矩：**提示词一律新增版本，不原地改**。已跑过批次的版本必须逐字保留，
> 否则历史 run 的产物无法复现（run 目录只 stage 源码，不存提示词快照）。

---

## 一、两层结构

每个角色的提示词分两层，**改动时要分清改哪一层**：

| 层 | 目录 | 内容 | 谁渲染 |
|---|---|---|---|
| **instruction** | `benchmark_managed/` | 领域规则：评价口径、算法指导、合规边界 | `PromptWorkerSet._prompt()` |
| **wrapper** | `cli_agents/` | 执行协议：输出契约、写文件位置、工具边界、请求载荷 | `cli_agent_wrapper.build_prompt()` |

wrapper 层必须包含 `${request_json}` 占位符，否则**请求载荷不会下发给模型**
（历史故障：`cli_agents/idea_judge.md` 初版漏了它，判官在完全看不到待评 Idea 和
ExpBank 路径的情况下连续给出"无实质缺陷"，跑了 4 轮探测才定位）。
回归测试见 `tests/test_idea_debate.py::test_no_prompt_template_silently_drops_a_placeholder`。

---

## 二、版本切换

| 角色 | 环境变量 | 取值 |
|---|---|---|
| Idea Agent | `FAMOU_IDEA_PROMPT_VERSION` | `v1`(默认) / `v2` / `v3` / `v4` / **`v5`**(跨任务) / **`v6`**(同任务自身) / `v7`(作业守则) / **`v8`**(算子 + 演化图 v2) |
| Implement Agent | `FAMOU_IMPLEMENT_PROMPT_VERSION` | `v1`(默认) / `v2` / `v3` |

别名：`v8` = `8` = `operator-v8`；`v7` = `7` = `rules-v7`；`v6` = `6` = `selftask-v6`；
`v5` = `5` = `expbank-v5`；`v4` = `4` = `debate-v4`；
`v3` = `3` = `validity-v3`；`v2` = `2` = `expbank-v2` = `algorithm-v2`（Idea 侧）。

解析在两处，**加新版本必须同时改**：

- `famou_scientist/loop/execution/cli_agent_wrapper.py` → `build_idea_prompt()`
- `famou_scientist/loop/agents/workers.py` → `PromptWorkerSet._prompt()`

fmjob 提交侧通过 `IDEA_PROMPT_VERSION` / `IMPLEMENT_PROMPT_VERSION` 透传。

---

## 三、Idea Agent 版本历史

### v1 `idea_agent.md`
初版。结构化 JSON 输出契约。

### v2 `idea_agent_v2.md`
新增两块：

- **算法设计指导**：要求使用逐实例、逐子指标反馈，不得只看聚合分；
  `worst_submetric` 与提升最小的实例列为一等目标
- **跨任务经验库**：分层访问（先读 `INDEX.md` 再按 `summary_path` 开单篇），
  要求 `rationale` 或 `expected_return.basis` 至少引用一条可访问的 `summary_path`

### v3 `idea_agent_v3.md`
新增**定向合规边界**：三条禁止（不得恢复目标值 / 不得反解 evaluator 反馈 /
不得让规则替代数据拟合），每条附违规与合规对照示例。

实测违规率：deepseek 26.3% → glm-5.2 8.7% → opus-5 5.4%。

### v4 `idea_agent_v4.md`（2026-09-03）

只改 wrapper 层的「回应 Idea Judge 的反馈」一节；instruction 层与 v3 逐字相同。

**动机**：v3 的措辞虽然写了"你保留作者权，可以拒绝修改"，但实测
**拒绝率为 0**——v4 批次作者被唤醒 4 次全部改写，配对批次 55 次改写、
`author_kept` 0 次。一个从未被行使的权利等于不存在。

复盘出三个措辞缺陷：

1. **只给二元选择**（"成立就改 / 不成立就原样重交"），没有"前提不成立但
   看着有可取之处"这一格。作者于是自创第三条路——先写
   `Partial rebuttal: the objection's premise ... is corrected`，
   再写 `Accepted kernel of the objection`，然后照改。
2. **"原样重交"有心理成本**：要求原封不动重交整份 JSON，看着像没干活，
   而"加一层 guard"既回应了判官又有交付感。
3. **`severity` 是单向压力**：没有告诉作者 `blocking`/`major` 也可以被驳回。

**v4 的改动**：

- 二元 → **四种处置**（改 / 驳回-前提不成立 / 驳回-不是瓶颈 / 部分改），每种给明确判据
- **禁止一**：驳回前提后不得再为"回应判官"加改动，并点名禁止
  "premise is corrected + accepted kernel" 这种写法
- **禁止二**：`current_score >= 0`（已达标）时只有 `blocking` 级意见才允许改动
- `rationale` 必须以处置声明开头：`DEBATE: modified` /
  `declined_premise` / `declined_not_bottleneck` / `partial`，便于事后统计
- 驳回时**方案主体必须与上一版逐字相同**

**支撑数据**（写进提示词是为了让模型知道代价，不是修辞）：

| 口径 | 结论 |
|---|---|
| idea 级配对，`origin >= 0` 分层 | n=6，改善 1 / 变差 4 / 相同 1，Δ均值 **−0.0329** |
| search-policy，父=当时最优 | refine 改善率 **52.9%**（≈抛硬币），delta 中位 +0.00002 |

**尚未验证**：v4 还没跑过批次。要验的是两件事——
拒绝率是否从 0 上升；以及 `origin >= 0` 那一层的负效应是否消失。

⚠️ 但即使拒绝率上去了，**也不能据此断定辩论有效**：配对实验的两条臂是
两次独立实现，Δ 里混着 run 间方差且无法分离（`s43588-024-00757-7` 7 对全在
±0.034 内，而只有 1–2 对的任务动辄 ±0.15，更像噪声主导）。

更正（2026-09-09）：此处此前写"要分离得补第三条臂测实现方差基线"。实现方差后来
实测出来了——同一条 idea 实现两次的绝对差值**中位只有 0.017**，比 σ 0.119 小近一个
数量级，不是 Δ 的主要来源。大头是 Idea 生成的多样性，即 run 间方差本身。
详见 `docs/benchmarks/naturebench/LOOP_ABLATION_STUDIES_CN.md` 5.2/5.3。

### v5 `idea_agent_v5.md`（2026-09-09，跨任务经验臂的当前版本）

两层都改：v4 的全部内容（含四种处置的辩论协议）逐字保留，只修跨任务经验库这一段
的**事实错误**。

**动机**：v1–v4 都写着「`expbank_dir` 是项目级 `.famou/cross_task_expbank` 为本 Run
准备的只读快照」，并让 Agent 先读 `<expbank_dir>/INDEX.md` 按 domain 筛选。三处与
实际不符：

1. `expbank_dir` 指向的是**本任务**的 `<run>/expbank`，不是跨任务快照；
2. 跨任务快照此前**根本没有作为目录下发**，Agent 只拿到 `experience[]` 里的
   20 条绝对路径；
3. 跨任务快照的清单文件是 `index.jsonl`（JSONL），不是 `INDEX.md`。

**实测后果**：2026-09-06 A/B 的 20 个 w/ 臂 run，**没有一个打开过跨任务目录的
清单**（0 次）。它们只能盲开载荷里给的路径——而当时载荷里 20 条经验的
`domain` 相同、`result` 全是 `stopped`、`task_summary` 全是 `null`，无法区分。
222/224 次 Idea 调用确实读了库，打开 148 个 Markdown，有内容的 12 个（8.1%）。

**v5 的改动**：

- 明确区分两个库：`expbank_dir`（本任务，`INDEX.md` + 逐 attempt 记录）与
  `cross_task_expbank_dir`（别的任务的快照）
- 把跨任务快照的**两层结构**直接写进提示词：外层 `index.jsonl` + 六个官方领域
  目录，每个领域目录下是一篇篇演化总结 Markdown；并给出索引每行的字段
- 明确检索方式：**不要整份 cat `index.jsonl`**（会随经验积累变大），按自己的
  domain grep，再打开相关条目的 `summary_path`；有余力再看其他领域
- 说明 `result` 是公开成绩档位（`surpass_sota` / `match_sota` / `below_sota` /
  `no_valid_score`）而不是运行状态，并要求同样阅读 `below_sota` 的失败边界

**同时删掉了「调度器替 Agent 预选」这一步**。原先 `search()` 会按同领域取最多
20 条塞进 `experience[]`。删掉的理由：

1. 那个窗口是自己发明的，而且正是出错的地方（按写入时间排序 → 同题重跑连成
   一片 → 有内容的条目被挤出窗口）；
2. 筛选本来就是 Agent 的活——库就在它工作区里，两层结构 + 索引足够它自己挑；
3. 唯一不能交给 Agent 的自任务屏蔽**不在 `search()` 里**：`seed_run` 拷快照时
   删索引条目并**物理删除对应的 .md**，Agent 绕过索引 `ls` 也读不到自己的解法。

**配套的代码改动**（提示词单独改没用，缺一处就白改）：

| 位置 | 改了什么 |
|---|---|
| `agents/workers.py::generate_ideas` | 载荷新增 `cross_task_expbank_dir`（现在是唯一的跨任务通道） |
| `runtime/orchestrator.py::_idea_experience` | 删掉跨任务条目预选，只保留本任务经验 |
| `storage/cross_task_expbank.py` | 删 `search()` / `read_summary()`，换成 `domain_counts()` 只做计数 |
| `runtime/orchestrator.py::_base_experience_summary` | 从公开题面写入 `task_summary` |
| `storage/cross_task_expbank.py::catalog_projection` | `result` 按分数派生，目录带 `evolution_summary` |

**尚未验证**：v5 还没跑过批次。要验的是 Agent 是否真的先按 domain 过滤索引、
再选择性打开（用 trajectory 统计「打开几篇 / 其中几篇相关」），以及补库之后
同领域条目数是否够（`run_summary.json` 的 `cross_task_expbank.same_domain_entries`）。

**补记（2026-09-11，v5 已跑完 `20260909-xtask-expbank-ab2-20x3`）**：上面那两条都验了，
**都是通过的**——82.2% 的 idea agent 调用打开过 ≥1 篇 `.md`，0/60 个 run 从未打开过，
每个 run 打开的不同 `.md` 中位 6 篇；补库后同领域条目数也够了。但 A/B 结果是 null
（14 个任务 8 正 5 负 1 平，p=0.581）。安慰剂对照的迁移检验显示内容确实进了方法字段
（净迁移 +19.0，57/1，p<1e-4），采纳率也确实抬起来了（leave-self-out 18% vs 对照臂
**0%**），但采纳不换分数（OOF n=24 p=0.541），剂量-响应全平（ρ≈+0.09）。
**结论是「别人的经验迁不过来」，不是「提示词没把库讲清楚」**——v5 要解决的问题解决了，
所以 v6 的方向不是继续改投递格式。

### v6 `idea_agent_v6.md`（2026-09-11）

两层都改：v5 的全部内容（含 v4 的辩论协议）逐字保留，只把跨任务口径翻成**同任务
自身经验**口径。**不是 v5 的替代，是并列的另一条臂**——`CROSS_TASK_EXPBANK_SCOPE=cross`
用 v5，`=self` 用 v6。

**动机**：跨任务那轮测出来是 null（见上），所以把迁移距离缩到最短再测一次——快照里
只放这道题自己前几轮的复盘（seed 侧 `--only-task-id`），剂量最大、匹配度最高。
批次 `20260911-selftask-expbank-ab-15x3`。

v5 在这条臂上有三处是**反向指令**，必须改：

1. 「`cross_task_expbank_dir` 是**别的任务**的跨任务经验快照……快照已剔除本任务
   自己的历史条目」——事实相反。
2. 「按自己的 domain 过滤 `index.jsonl`」——自身条目全在同一个领域里，过滤不掉
   任何东西；条目只有 2–9 条，直接读完更省事。
3. 「不能把跨任务结论、分数或代码直接当作当前任务事实；必须写明可迁移的假设」——
   讲的就是这道题，不需要论证可迁移性。

**v6 换上的那一条**，直接对准诊断出的根因：run 内 **62% 的「刷新最佳」幅度小于该
任务自身的重复噪声**（提升中位 0.0208 vs 噪声下界中位 0.0366，329 次刷新 / 17 个
任务），而 Agent 没有任何手段自行发现——978 个 attempt **0 个重复 `code_snapshot`**，
没有候选被重测过，`official_metrics` 只有一个聚合分。所以 v6 明写：复盘里 0.0x 量级
的提升可能落在噪声里，被多轮独立复现过或幅度明显大于噪声的方向才值得继续叠，
一次性的小幅提升不要当成已经站住的台阶。

**配套的代码改动**：

| 位置 | 改了什么 |
|---|---|
| `fmjob/sync_cross_task_expbank.py::seed_run` | 新增 `only_task_id`，与 `exclude_task_id` 互斥；新增镜像断言 `_assert_only_task_included`；manifest 记 `included_task_id` |
| `fmjob/submit_one_click.sh` | 新增 `CROSS_TASK_EXPBANK_SCOPE=cross\|self`，按它在 `--exclude-task-id` / `--only-task-id` 之间二选一 |
| `harness/runtime.py::_cross_task_dose` | self 臂的 `low_dose` 改按 `same_task_entries < 2` 判（`same_domain` 对自身经验恒等于总数） |

**尚未验证**：v6 还没跑过批次。

### v7 `idea_agent_v7.md`

本台账**没有 v7 的条目**（加版本时漏记）。它在两层都存在，内容是 v3 的合规边界之上
加了一份「从 83 道题、1253 次 attempt 蒸馏的作业守则」。批次
`20260915-idea-graph-ab-10x2` 的两臂都用它。

### v8 `idea_agent_v8.md`（2026-09-18）

两层都改。v7 的全部内容逐字保留，只替换与方案图有关的那几句。

**动机**：`20260915-idea-graph-ab-10x2` 的结论是「图接通了，agent 也确实在读，但读完
没有改变它的行为」——Δ 中位数 +0.0061，符号检验 p=0.7539，10 题无一走出噪声。最能
说明问题的 `s41587-024-02428-4` 沿着图挖了九层，**全程没有任何信号告诉它这个方向在
变好还是变坏**。v8 配合演化图 v2（`docs/design/EVOLUTION_GRAPH_V2_CN.md`）把那个
信号补上。

改了三处：

1. **schema**：`parent_idea_id`(str) + `relation`(可选) → **`operator`(必填枚举) +
   `parents`(数组)**。多父从此在结构上可能——v1 的单字符串父指针让图永远塌成树。
2. **把三个算子逐条定义清楚**（`innovate` / `exploit` / `cross`，各自的 `parents`
   基数与适用场景）。上一批实测的 `alternative_to` 占比 44%(处理臂) / 63%(对照臂)
   **不构成任何证据**：词表从未定义、字段从不校验，那个分布只是自报噪声。
3. **说明 `GRAPH.md` 的四段结构**（现在爬到哪了 / 最该接着挖的 / 试过但还没有分的 /
   全部方案）各自该拿来做什么决策。每一行都自足：父节点写成「标题」(分数)，节点下面
   缩进那行是宿主截断过的一句话说明（全文在 `graph/<节点 id>.json`）。「最该接着挖的」
   已按父节点的分数排好，**第 1 行就是默认答案**；节点 id 只在「全部方案」段行尾的方括号里。
   明写「还没试」（第 2 段）与「试了不行」（第 3 段）物理分开，不许混读。

**位置不动**：图那段仍在原处，不移到提示词最前——「把规则块移到最前」是另一个已批准
但尚未执行的独立变量，混进来就没法归因。

**配套的代码改动**：`operator` / `parents` 由 `storage/evolution_graph.py` 的
`validate_operator` 校验；非法时回一条 `benchmark_runtime.operator_violation` 重提
**一次**，仍非法则 coerce 并记一条 `operator_coerced` decision artifact——**被 coerce
的条数是事前登记的合规读数**，它决定「算子分布」那张表能不能当证据用。

**尚未验证**：v8 还没跑过批次（计划 `20260920-graph-v2-ab-10x2`）。

**2026-09-20 原地改写过第 3 条**（三段 → 四段 + 每节点一句话描述）。「不原地改」那条
规矩保护的是**已产出过 run 的版本**；v8 当时 0 个 run 用过，所以原地改是安全的，开 v9
反而要再同步两处版本阶梯（`workers.py` / `cli_agent_wrapper.py`），多一次漂移机会。
**⑥ 一旦派发，这个窗口就关了**，之后只能开 v9。

---

## 四、Judge 类提示词

| 角色 | instruction | wrapper | 版本 |
|---|---|---|---|
| Idea Judge（辩论） | `benchmark_managed/idea_judge.md` | `cli_agents/idea_judge.md` | 未版本化 |
| Idea Rank Judge（冲刺期排序） | `benchmark_managed/idea_rank_judge.md` | `cli_agents/idea_rank_judge.md` | 未版本化 |
| Validity Verifier | `benchmark_managed/validity_verifier.md` | — | 未版本化 |

**这三个还没有版本机制**，改动是原地改的。Idea Judge 已经原地改过一次
（初版无必答清单 → 加 7 项 checklist + "无缺陷也要出示证据"），
所以 v1/v2 批次的判官行为与 v3/v4 批次**不可直接比较**。

待办：给这三个也建版本切换（`FAMOU_IDEA_JUDGE_PROMPT_VERSION` 等），
否则同类问题会再犯一次。

---

## 五、Terminal-Bench Verifier Agent 版本

Terminal verifier 的 compiler、repair 和 diagnose wrapper 通过
`FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION` 切换，默认使用 `v1`：

| 版本 | 文件 | 说明 |
|---|---|---|
| `v0`（兼容旧批次） | `cli_agents/terminal_task/verifier_compile_v0.md`、`verifier_repair_compile_v0.md`、`verifier_diagnose_v0.md`、`verifier_plan_v0.md` | 原有 Verifier Compiler/Plan/Diagnose v1 内容逐字保留，仅将版本标识纳入兼容层 |
| `v1`（当前默认） | `verifier_instruction_v1.md` + `verifier_compile_v1.md`、`verifier_repair_compile_v1.md`、`verifier_diagnose_v1.md` | 统一基础指令覆盖三类检查（format/contract、behavior/safety、value/quality）；实际运行模板分别承载初次 `compile_plan`、`repair_compile`、`diagnose` 协议；强调官方断言逐项对齐、固定字面量精确比较、instruction/metadata 冲突记录、`exact`/`approx`/`uncovered`、真实公开数据 mutation test，并禁止用 synthetic fixture 冒充 hidden GT 覆盖 |
| `v2`（质量强化，显式切换） | `verifier_instruction_v2.md` + 对应的 `*_v2.md` 阶段模板 | 在 v1 基础上明确 value/quality 质量门槛：独立参考、指标同构、分布覆盖、最差实例、动态真实性、离线校准和不确定性；要求动态检查在受限 verifier sandbox 中执行，不能在 Controller 进程直接执行候选 |

别名：`v0` = `0` = `legacy`；其他值默认使用当前 `v1`。历史任务可显式设置
`FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION=v0`，新任务默认使用 `v1`。
需要启用质量强化版时设置 `FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION=v2`；在完成动态
sandbox 和历史候选校准前，v2 保持显式切换，不自动改变已有实验的默认口径。

这次版本升级由多任务对比共同驱动，而不只针对 `ode-law-discovery`：

- ODE：Proxy 曾将 `time_variable="time"` 当作任意非空字符串，并把 hidden
  rollout/stress/vector-field 门槛误解为已覆盖；
- 两个定位任务：公开/合成定位检查通过，但 hidden damage localization 仍失败；
- MRI：结构、编码、测量和证据自洽不等于主要病变综合分通过；
- TAMP：静态计划检查不等于 100 个实例真实回放，并暴露了 Proxy 额外强制官方未要求
  产物的风险；
- 多个任务还显示路径解析和官方 runtime/safety 语义必须按 task 的 tests/checker
  逐项核对，不能凭 TBS 惯例推断。

因此 v1 统一要求：格式契约精确对齐、静态与动态分层、hidden value 使用 coverage
manifest 并标记 `uncovered`、不把额外产物作为 blocking 条件、报告拆分
`format_pass`/`behavior_pass`/`value_proxy_pass`。升级不改变 verifier 的安全边界，
也不声称能从无 hidden 数据中精确重建 GT。

其中 `verifier_instruction_v1.md` 是实际三个运行阶段模板共用的基础指令。历史保留的
`verifier_plan_v1.md` 是早期独立 Plan 模板，目前不由 wrapper 单独加载；Graph 的
`verifier_plan` 节点实际使用 `phase=compile_plan`。任务自己的官方
`instruction.md` 仍由 Controller 通过 `$instruction` 注入，不能把任务题面复制进公共文件。

## 六、Skill / 其他资产

`famou_scientist/assets/opencode/` 下的 skill、plugin、prompt 有独立的
版本机制（`registry/registry.json` + `release-log.jsonl` + 各自的
`CHANGELOG.md` + `prompts/PROMPT_CHANGELOG.md`），**与本文档无关**。
loop 侧提示词此前没有任何等价机制，本文档即为补齐。
