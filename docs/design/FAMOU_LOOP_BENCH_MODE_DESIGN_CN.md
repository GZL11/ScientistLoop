# Famou-Scientist `--mode loop`：端到端自主打科研 Benchmark 设计

> **状态说明（2026-08）**：本文记录的是 Famou 主动接入 benchmark 的
> adapter-first 方案。对于 NatureBench、Terminal-Bench 等支持自定义 Agent 或
> 命令启动的 Harness，当前主方案已调整为 Harness-first，请优先阅读
> [Famou Benchmark Agent CLI 设计](./FAMOU_BENCHMARK_AGENT_CLI_DESIGN_CN.md)。
> 本文仅作为无 Agent Harness benchmark 的回退设计和历史决策记录。

> 目标：让 Famou-Scientist 像 AutoResearch 一样，不只是“回答/写报告”，而是能在给定 benchmark 上 **自主读任务 → 搭环境 → 复现 baseline → 设计改进 → 训练/仿真/求解 → 本地评估 → 迭代刷分 → 打包提交**。

---

## 1. 我们要解决什么

前面调研的科学 agent / benchmark 大多可以抽象成两类：

1. **SOTA/leaderboard 型**：Matbench、Matbench Discovery、OC20、Qiskit HumanEval、PDEBench、CFD surrogate、MLE-bench 等。  
   核心是：给数据、协议、metric，agent 自主构造方法，刷更高分。
2. **研究产物/rubric 型**：ResearchClawBench、PaperBench、MLReplicate、FIRE-Bench 等。  
   核心是：给任务指令，agent 自主产出 report/paper/code，再由 judge/rubric 评分。

`--mode loop` 的定位是把这两类统一到同一套运行和证据底座，但不强行使用同一张循环图。对于任务契约完整的 benchmark，Famou 只托管实现 agent 和运行过程；benchmark adapter 拥有任务、数据、环境、提交协议和 evaluator，不需要 master agent 或额外 agent judge。

完整 benchmark 的实际链路是：

```text
Benchmark Task Adapter
  → implement agent
  → benchmark runtime
  → trusted benchmark evaluator
  → official leaderboard
  → 下一轮实现或预算结束
```

只有开放式科研目标才使用 `Human ↔ MasterBridge ↔ Research Loop`，并按用户偏好判断创新性、可解释性等非 benchmark 指标。

---

## 2. 和当前 AutoResearch 范式的关系

当前 Famou 的 AutoResearch 流程是：

```text
文献 → 假设 → 实验设计 → 写代码 → 跑实验 → 分析 → 写论文 → 自评
```

`--mode loop` 不是另起炉灶，而是把目标函数换掉：

```text
读 benchmark 合约 → 复现官方 baseline → 设计改进方法 → 跑评测 → 迭代刷分 → 打包提交 → 复盘报告
```

对应关系：

| AutoResearch | E2E Bench |
|---|---|
| 研究问题 | benchmark task / leaderboard objective |
| 文献综述 | 读 benchmark 论文、榜单、baseline repo、SOTA 方法 |
| 假设 | “什么改动可能提升 metric” |
| 实验设计 | ablation / seed / validation protocol / resource budget |
| 可信数字 `results.json` | benchmark score registry |
| 论文草稿 | submission artifact + benchmark report |
| quality gate | evaluator + leakage guard + reproducibility check |

所以实现上应复用现有 skill：`literature-search`、`baseline-profiling`、`benchmark-selection`、`experimental-design`、`code-plan-review`、`async-experiment-execution`、`experiment-repair`、`statistical-reporting`、`quality-gate`。

---

## 3. 用户入口

### 3.1 推荐 CLI

```bash
# 交互式进入 Loop benchmark 模式
famou-scientist --mode loop

# headless：给一个 benchmark task，让 agent 自主跑完
famou-scientist run --mode loop --bench matbench --task dielectric

# 外部 benchmark：用本地 spec 描述协议和 evaluator
famou-scientist run --mode loop --bench-spec /path/to/benchmark.yaml

# 兼容 ResearchClawBench 这类外部 harness
famou-scientist run --mode loop "$(cat INSTRUCTIONS.md)"
```

### 3.2 CLI 解析原则

当前 `cmdline.py` 会把未知参数透传给 opencode。新增 `--mode loop` 时要在 Famou 层先 strip 掉，不要让 opencode 误解析：

```text
cmdline.main(args)
  ├─ loop.cli.run_from_mode_flags(args)
  │    ├─ mode = "loop"
  │    ├─ bench / task / bench_spec / budget / max_trials ...
  │    └─ clean_args = 去掉 Famou 专属参数后留给 opencode 的参数
  ├─ 写入 env：FAMOU_MODE=loop, FAMOU_LOOP_CONFIG_JSON=...
  └─ launcher.launch(extra_args=clean_args)
```

---

## 4. Instruction 注入设计

### 4.1 文件位置

新增：

```text
famou_scientist/assets/opencode/modes/loop/instruction.md
famou_scientist/assets/opencode/modes/loop/instruction.template.md
famou_scientist/assets/opencode/_generated_mode_instruction.md
```

修改 `opencode.json`：

```json
{
  "instructions": [
    "AGENTS.md",
    "_generated_baidu_search.md",
    "_generated_mode_instruction.md"
  ]
}
```

`launcher.build_env()` 根据 `FAMOU_MODE` 生成 `_generated_mode_instruction.md`：

- 普通模式：写空文件；
- `loop`：写入 `modes/loop/instruction.md`，并追加当前 bench config 摘要。

### 4.2 Loop instruction.md 核心内容

`instruction.md` 要非常明确，因为 headless benchmark 没人可以追问：

```markdown
# E2E Benchmark Mode

你现在处于 Famou-Scientist E2E benchmark 模式。

目标：
1. 最大化当前 benchmark 的官方 metric；
2. 严格遵守 benchmark 协议；
3. 不能读取 test label / hidden answer / 评分器私有答案；
4. 所有分数必须来自 evaluator 或官方脚本；
5. 自主迭代，直到达到预算或没有明显提升；
6. 最终必须产出 submission artifact、score.json、report.md。

工作流：
1. 读取 INSTRUCTIONS.md / benchmark.yaml / README / baseline repo；
2. 提取 benchmark contract；
3. 建立 run 目录；
4. 先跑官方 baseline 或最小 baseline，得到可复现起点；
5. 调研 SOTA / 方法库，提出 3-5 个可试改进；
6. 每轮只改一个主要因素，跑 evaluator，登记 score；
7. 选择 best checkpoint/submission；
8. 打包最终产物。

无人模式：
- 不向用户提问；
- 遇到缺省配置，用 benchmark.yaml 或 reasonable default；
- 失败自动修复最多 N 次；
- 预算耗尽就提交当前 best。
```

---

## 5. Benchmark 包格式

每个 benchmark 用一个自描述目录表示：

```text
benchmarks/<bench_id>/
├── benchmark.yaml          # 机器可读合约
├── instruction.md          # 给 agent 的任务说明，可模板化
├── evaluator.py            # 本 benchmark 的本地评分器
├── tasks/
│   ├── task1.yaml
│   └── task2.yaml
├── starter/                # 可选：starter code / baseline config
└── README.md
```

### 5.1 `benchmark.yaml` schema

```yaml
id: matbench_dielectric
name: Matbench dielectric
domain: materials
paradigm: ml_surrogate       # ml_surrogate | mixed_physics_ml | mechanistic | workflow_judge
objective: maximize_score

official:
  paper: "..."
  repo: "..."
  leaderboard: "..."

data:
  root: data/
  download: manual_or_command
  train: train.csv
  valid: valid.csv
  test: test.csv
  hidden_labels: true

submission:
  format: csv
  required_files:
    - submission.csv
    - report.md

metric:
  name: mae
  direction: minimize
  primary: true
  public_validation: true

evaluator:
  type: python
  entry: evaluator.py
  command: "python evaluator.py --submission {submission} --split valid --out {out}"

budget:
  max_trials: 20
  walltime_hours: 8
  gpu_hours: 16
```

---

## 6. Evaluator 设计

评估器是这个模式的关键。它不应该替 agent 搜索方法，只做四件事：

1. **validate**：检查提交格式、文件完整性、是否越权使用 test label；
2. **score**：调用官方 metric / 单元测试 / 仿真核验 / judge rubric；
3. **compare**：和 baseline、历史 best 比较；
4. **pack**：把 best artifact 打包成可提交目录。

### 6.0 评测工具必须是“可信边界”

这点我同意，而且应该定成硬原则：

- **agent 不直接评测自己**；
- **agent 不接触 hidden test / hidden label / hidden rubric**；
- **benchmark 的官方评估逻辑只在可信 evaluator 里运行**；
- **agent 只能提交 artifact，不能看见评分器内部实现**。

可以把系统切成两层：

```text
Agent / Master
  ├─ 读公开数据、训练、生成提交
  └─ 调用评测工具，但不执行评测逻辑

Trusted Evaluator
  ├─ 读取 hidden test / private rubric
  ├─ 运行官方 metric / judge / unit test
  └─ 只回传受控结果（score.json）
```

这样做的好处是：

1. **彻底降低泄漏风险**；
2. **统一所有 benchmark 接口**；
3. **评测可以独立容器化/远程化**；
4. **数值型和 rubric 型任务都能接**。

### 6.1 统一命令

建议提供一个统一 CLI：

```bash
famou-scientist loop eval \
  --spec benchmark.yaml \
  --submission runs/.../submission.csv \
  --split valid \
  --out runs/.../score.json
```

也可以在 agent 侧暴露为工具，但工具本身只是**远程调用可信 evaluator**，不是本地重新实现评测：

```text
arc_benchmark_eval(spec_path, submission_path, split, out_path)
arc_benchmark_pack(spec_path, run_dir, out_dir)
```

MVP 可以先用 CLI，后续再封成 tool。

### 6.2 `score.json` 标准格式

```json
{
  "benchmark_id": "matbench_dielectric",
  "task_id": "dielectric",
  "split": "valid",
  "metric": {
    "name": "mae",
    "direction": "minimize",
    "value": 0.1234
  },
  "baseline": {
    "name": "official_baseline",
    "value": 0.1567
  },
  "improvement": {
    "absolute": -0.0333,
    "relative_percent": 21.25,
    "is_better": true
  },
  "valid": true,
  "leakage_check": "pass",
  "artifacts": {
    "submission": "submission.csv",
    "log": "eval.log"
  }
}
```

### 6.3 不同 benchmark 的 evaluator 类型

| 类型 | 例子 | evaluator 做什么 |
|---|---|---|
| ML 预测/排序 | Matbench、OpenPoly、MLE-bench | 读 prediction → 算 MAE/AUC/leaderboard percentile |
| 材料发现/生成 | Matbench Discovery、MatterGen | 稳定性、novelty、uniqueness、top-k hit、DFT/MLIP relaxation 接口 |
| 量子编程 | Qiskit HumanEval、QCircuitBench | 运行 unit tests、QASM 语法、线路语义、gate/depth/shot |
| PDE/CFD surrogate | PDEBench、AirfRANS、CFDBench | 场误差、rollout stability、物理量误差、守恒/边界条件 |
| 机理/方程发现 | AI Feynman、SRBench、NewtonBench | 公式等价、复杂度、外推误差、物理维度/定律一致性 |
| rubric/judge | RCB、PaperBench | 产物完整性 + LLM judge/rubric，必要时人工校验 |

---

## 7. E2E run 目录

建议不要混用 `research-runs/`，而是新增：

```text
benchmark-runs/<bench_id>/<task_id>-<timestamp>-<shortid>/
├── INSTRUCTIONS.md
├── benchmark.yaml
├── planning/
│   ├── benchmark_contract.md
│   ├── baseline_profile.md
│   ├── method_ideas.md
│   └── experiment_plan.md
├── workspace/
│   ├── data/
│   ├── code/
│   ├── checkpoints/
│   └── submissions/
├── eval/
│   ├── baseline_score.json
│   ├── trials.jsonl
│   ├── best_score.json
│   └── leakage_report.md
└── final/
    ├── submission.*
    ├── score.json
    ├── report.md
    └── reproduce.sh
```

其中 `eval/trials.jsonl` 是核心轨迹：

```jsonl
{"trial":1,"change":"official baseline","score":0.1567,"status":"ok"}
{"trial":2,"change":"add crystal graph features","score":0.1412,"status":"ok"}
{"trial":3,"change":"ensemble 5 seeds","score":0.1280,"status":"ok","best":true}
```

---

## 8. Agent 自主循环

E2E mode 的 agent 工作流可以固定为下面的 state machine：

```text
INIT
  ↓
READ_CONTRACT          # 读 benchmark.yaml / INSTRUCTIONS / README
  ↓
SETUP_ENV              # 安装依赖、准备数据、跑 sanity
  ↓
BASELINE               # 必须先跑通 baseline
  ↓
IDEATE                 # 文献/SOTA/baseline profiling，提出改进
  ↓
IMPLEMENT              # 改代码/训练/仿真/生成候选
  ↓
EVALUATE               # 调 evaluator，写 score.json
  ↓
DECIDE
  ├─ score 提升且预算未耗尽 → IDEATE/IMPLEMENT
  ├─ 无提升但还有可解释方向 → IMPLEMENT
  └─ 预算耗尽/无方向 → PACKAGE
  ↓
PACKAGE                # best submission + reproduce.sh + report.md
```

关键约束：

- **必须先 baseline**：否则不知道自己有没有真正接通协议；
- **每轮一个主改动**：避免无法归因；
- **所有分数都进 `trials.jsonl`**；
- **始终保留 best artifact**；
- **预算耗尽提交 best，不空跑**。

---

## 9. 防作弊 / 防幻觉规则

E2E benchmark 很容易出现“刷分作弊”或“假跑通”，所以 evaluator 和 instruction 要双重约束。

### 9.1 必须禁止

- 读取 hidden labels / answer key；
- 用文件名、样本顺序、checksum 等泄露特征反推标签；
- 把 test set 当 validation 反复调参；
- 让 agent 直接读取 test 文件或 hidden rubric；
- 没跑 evaluator 就声称分数；
- 修改 evaluator 或 benchmark 官方数据；
- 伪造 submission / score.json；
- 使用 synthetic/mock data 替代真实 benchmark data，除非 benchmark 本身就是 synthetic。

### 9.2 evaluator 应检查

- submission 行数、id 集合、字段、dtype；
- train/valid/test split 是否被污染；
- 是否访问 forbidden path；
- score 是否可复现；
- report 里的数字是否来自 `score.json` / `trials.jsonl`。

---

## 10. 和现有 ResearchClawBench 适配器的关系

当前已有：

```text
benchmark/researchclawbench/
├── famou_rcb.py
├── register_famou.py
└── run_eval.sh
```

这已经证明了一个最小链路：

```text
外部 harness → 创建 workspace/INSTRUCTIONS.md → famou run → 搬产物 → scorer
```

但 README 里也写得很清楚：当前 RCB 接入更像“基线能力”，会被 RCB 的 `INSTRUCTIONS.md` 覆盖，不完全体现 Famou 的 AutoResearch 流程。

`--mode loop` 可以把它升级成通用范式：

1. RCB 仍作为一个 `workflow_judge` benchmark adapter；
2. Famou 不再被外部 prompt 完全牵着走，而是由 `loop/instruction.md` 统一约束；
3. 产物映射逻辑从 `famou_rcb.py` 抽象成 `BenchmarkAdapter.pack()`；
4. 其他 benchmark 复用同一套 `benchmark.yaml + evaluator.py + instruction.md`。

---

## 11. 代码改动建议

### 11.1 最小改动

```text
famou_scientist/
├── cmdline.py                 # strip --mode loop / --bench / --task / --bench-spec
├── launcher.py                # 生成 _generated_mode_instruction.md
├── loop/cli.py                # 参数解析和自主循环命令入口
└── assets/opencode/
    ├── opencode.json          # include _generated_mode_instruction.md
    └── modes/loop/instruction.md
```

### 11.2 第二步：通用 evaluator

```text
famou_scientist/loop/
├── __init__.py
├── cli.py                     # famou-scientist loop eval/pack/list
├── schema.py                  # BenchmarkSpec / ScoreResult
├── evaluator.py               # base Evaluator
├── registry.py                # built-in + local benchmark registry
└── adapters/
    ├── rcb.py
    ├── matbench.py
    ├── qiskit_humaneval.py
    ├── srbench.py
    └── pdebench.py
```

### 11.3 第三步：OpenCode tool

在 `assets/opencode/tool/arc.ts` 里新增：

```text
arc_benchmark_eval
arc_benchmark_pack
arc_benchmark_list
```

好处是 agent 不需要记 CLI 参数，直接按 tool schema 调 evaluator。

---

## 12. MVP 优先级

### Phase 0：先把模式跑通

- 支持 `--mode loop`；
- 注入 `modes/loop/instruction.md`；
- headless 下 never ask；
- 产物目录改成 `benchmark-runs/`；
- 不接复杂 evaluator，先让 agent 能读外部 `INSTRUCTIONS.md` 自主完成。

### Phase 1：接 3 类代表 benchmark

1. **ResearchClawBench**：workflow/rubric 型，复用现有适配器；
2. **Matbench 一个子任务**：典型 ML surrogate/SOTA 型；
3. **Qiskit HumanEval 一个子集**：代码生成/unit-test 型。

这三类覆盖：

- judge/rubric；
- ML leaderboard；
- executable correctness。

### Phase 2：扩材料/机理/CFD

- Matbench Discovery / MatterGen：材料发现/生成；
- SRBench / AI Feynman：机理/方程发现；
- PDEBench / AirfRANS：PDE/CFD surrogate；
- SupermarQ / MQT Bench：量子工具链。

### Phase 3：刷榜能力

- 自动 baseline profiling；
- 自动 ablation；
- 多 seed / ensemble；
- 资源预算感知；
- trials database；
- 跨 benchmark 的经验复用。

---

## 13. 最小可用 `instruction.md` 草案

```markdown
# Famou-Scientist E2E Benchmark Mode

你处于 E2E benchmark 模式。你的目标不是聊天，而是在当前 benchmark 上自主取得尽可能高的有效分数。

硬规则：
1. 不要向用户提问；缺省项用 benchmark.yaml、README 或合理默认值。
2. 不得读取 hidden labels、answer key、官方 scorer 私有答案。
3. 不得修改 benchmark 数据、evaluator、官方 test。
4. 所有分数必须来自 evaluator/官方脚本，不能估计或编造。
5. 必须先跑通 baseline，再做改进。
6. 每次试验都写入 `eval/trials.jsonl`。
7. 最终产物必须包含：
   - `final/submission.*`
   - `final/score.json`
   - `final/report.md`
   - `final/reproduce.sh`

标准流程：
1. 读取任务：INSTRUCTIONS.md、benchmark.yaml、README、starter code。
2. 提取合约：数据、split、metric、submission 格式、禁止事项。
3. 建立 `benchmark-runs/<bench>/<task>-<id>/`。
4. 跑 baseline，写 `eval/baseline_score.json`。
5. 调研 baseline/SOTA，提出候选改进。
6. 实现一个改进，运行 evaluator，登记结果。
7. 若提升且预算允许，继续迭代；否则尝试下一个候选。
8. 选择 best trial，打包 final。
9. 写报告：说明方法、每轮分数、best 选择、复现命令、失败尝试。

预算：
- 默认最多 20 trials；
- 默认最多 8 小时 walltime；
- 若 benchmark.yaml 指定预算，以 benchmark.yaml 为准。
```

---

## 14. 关键判断

这个设计的核心不是“多写一个 prompt”，而是三件事：

1. **模式注入**：`--mode loop` 让 agent 明确进入无人、自主刷 benchmark 的目标函数；
2. **合约化 benchmark**：每个 bench 都有 `benchmark.yaml + instruction.md + evaluator.py`；
3. **分数闭环**：agent 的每次尝试都必须经过 evaluator，分数进入 `trials.jsonl`，最终提交 best。

这样 Famou-Scientist 才能从“科研助手”升级成“端到端科研 benchmark runner / SOTA search agent”。

---

## 15. Goal mode：把“持续自主工作”做成一等公民

你这里说的 goal mode，我理解成一种**持续存在、可被打断、可并发推进、可由 master agent 接管**的长期目标对象。

### 15.1 参考 Codex / ChatGPT 的现成范式

从公开资料看，Codex 已经在往这个方向走：

- **多任务并行**：每个 task 在独立 sandbox/worktree 里跑，可并行推进；
- **持续后台工作**：可以把 routine work 挂到后台；
- **同一对话续跑**：scheduled task 可以回到同一 chat，保留上下文；
- **控制面与执行面分离**：Symphony 这类编排把 issue board 变成 control plane，agent 连续运行，human 只审结果。

所以我们不必发明一个“只会跑分的黑盒 agent”，而是做成：

> **Goal = 一个持久化目标对象；Master agent = 目标控制器；Worker = 可并发的执行单元；Human = 可随时介入的外部控制者。**

### 15.2 目标对象（Goal）应该长什么样

建议把 goal 设计成一等数据结构：

```yaml
goal_id: g_20260728_xxx
type: benchmark_e2e | research_project | maintenance | review
status: pending | running | blocked | paused | done | cancelled
objective: maximize_matbench_score
mode: loop | research | chat
owner_session: ses_xxx
master_agent: famou-master
workers:
  - worker_id: w1
    role: baseline_runner
  - worker_id: w2
    role: literature_scout
  - worker_id: w3
    role: evaluator
constraints:
  budget:
    walltime_hours: 8
    gpu_hours: 16
    max_trials: 20
  policy:
    ask_human_on: [goal_change, budget_overrun, evaluator_failure]
    never_ask_on: [routine_retry, minor_fix]
artifacts:
  run_dir: benchmark-runs/...
  best_score: 0.1234
  best_artifact: final/submission.csv
```

### 15.3 Master agent 的职责

Master agent 不是执行所有事情，而是：

1. **解释 human intent**：把用户自然语言转成 goal；
2. **维护目标状态机**：pending/running/blocked/paused/done；
3. **调度 worker**：并发派发 baseline、文献、调参、评测；
4. **整合证据**：把 worker 的 logs/score/artifacts 汇总成统一视图；
5. **做中断判断**：什么时候该继续、什么时候该停、什么时候该问人；
6. **充当 bridge**：人说的话都先到 master，再由 master 影响 goal。

这就和你说的“human 和 goal 系统之间的 bridge”一致。

### 15.4 Human 什么时候可以随时对话

要做到“goal 在后台跑，但人随时能说话”，关键是：

- **对话通道和执行通道分离**：聊天永远可用；
- **goal 不能独占会话**：它只是一个后台状态；
- **用户输入分层处理**：
  - 普通闲聊 → 只是影响上下文；
  - 明确指令 → 变更 goal；
  - 打断/暂停/恢复 → 改 goal 状态；
  - 查看进展 → 读 goal 事件流和 artifacts。

也就是说，用户可以一边看着 goal 跑，一边随时插话：

- “先别跑这个，改成材料 benchmark”
- “预算减半”
- “刚才那个 baseline 先保留”
- “把并发从 4 调成 2”

### 15.5 并发 worker 的正确姿势

这里**不建议**一个 goal 只绑一个永久 agent。更像：

```text
master goal controller
  ├─ worker A: baseline / reproduction
  ├─ worker B: literature / method scouting
  ├─ worker C: evaluation / packing
  └─ worker D: repair / retry
```

原则：

- worker **短命、专职、可重启**；
- master **长命、状态集中、负责调度**；
- worker 间共享**只读状态**和**产物仓库**，不要共享隐式内存；
- 每个 worker 完成后必须把结果写回 goal event log。

### 15.6 一个统一状态机

```text
NEW
  ↓
ACTIVE
  ├─ running workers
  ├─ human can interject
  └─ master keeps scheduling
  ↓
BLOCKED / NEEDS_HUMAN
  ↓                ↘
RESUMED            PAUSED
  ↓                ↘
ACTIVE              CANCELLED
  ↓
DONE
```

### 15.7 对 famou 的落地建议

我建议把 `--mode loop` 和 goal mode 合并成同一底座：

- `--mode loop`：启动时自动创建一个 benchmark goal；
- 对话中 `/goal ...`：创建、查看、编辑、暂停、恢复、清除 goal；
- 后台 worker：并发跑 baseline / 调参 / 评测；
- master agent：负责把 human 指令转成 goal 修改；
- 统一落盘：`goal.json + events.jsonl + artifacts/ + score.json`。

这样就不会有“两套系统”：

> **goal mode = 长期运行的控制平面；e2e = goal 的一种具体任务类型。**

---

## 16. CC / Codex 的 `/goal`：准确参考

这里之前写得不准确：**Claude Code 和 Codex 都确实有 `/goal`**，而且它不是普通“计划模式”，而是一个**跨 turn 持续工作的 session-scoped 目标循环**。

### 16.1 Claude Code `/goal`

Claude Code 官方文档的核心语义：

- `/goal` 设置一个**完成条件**，Claude 会跨多个 turn 持续工作，直到条件满足；
- 每个 turn 结束后，一个**小型快速模型 evaluator** 判断条件是否满足；
- 如果 evaluator 判定未满足，就自动启动下一个 turn，而不是把控制权还给用户；
- 如果条件满足，goal 自动清除；
- `/goal` 是 **session-scoped shortcut**，当前 session 内最多一个 active goal；
- `/goal`、`/goal clear`、`/goal` 无参数分别用于设置、清除、查看状态；
- active goal 可随 `--resume` / `--continue` 恢复；
- `/goal` 也可用于 non-interactive mode，例如 `claude -p "/goal ..."`。

这说明 `/goal` 的本质是：

```text
turn finishes
  ↓
goal evaluator checks completion condition
  ├─ yes → clear goal, return control
  └─ no  → feed evaluator reason into next turn, continue working
```

而不是：

- 只是一个 todo；
- 只是一个后台 shell job；
- 只是把 prompt 写长；
- 只是 auto-approve。

Claude Code 还明确区分：

| 机制 | 下一个 turn 何时开始 | 停止条件 |
|---|---|---|
| `/goal` | 前一个 turn 完成后 | evaluator 判断目标条件满足 |
| `/loop` | 时间间隔到达 | 用户停止，或 Claude 判断完成 |
| Stop hook | 前一个 turn 完成后 | 用户脚本或 prompt 判断 |
| auto mode | 不自动开启新 turn | 只是在单个 turn 内减少工具审批 |

关键启发：

1. **goal 需要一个独立 evaluator**，不能由主 agent 自己说“我完成了”；
2. **goal condition 必须可验证**，例如 test pass、build exit 0、文件数量、队列为空；
3. **goal 是 session 级状态**，不是全局 daemon；
4. **goal 可被用户清除/恢复/查看**；
5. **auto mode 和 goal mode 是互补关系**：auto 解决 per-tool approval，goal 解决 per-turn continuation。

### 16.2 Codex `/goal`

Codex 官方文档也有 `/goal`：

- `/goal <objective>` 设置 goal；
- `/goal` 查看当前 goal；
- `/goal edit` 修改目标；
- `/goal pause` / `/goal resume` / `/goal clear` 控制生命周期；
- goal attached to active chat；
- objective 非空，最多 4,000 字符；
- 如果说明更长，应放到文件里，然后让 goal 指向该文件；
- 典型用途是有明确 success condition 和 validation loop 的长任务、迁移、大重构、实验等。

Codex 的 use case 文档还强调：

- `/goal` 适合“durable objective for long-running work”；
- 需要明确 stopping condition；
- 适合 experiments / prototypes / long-running coding work；
- 可以独立工作数小时；
- 应该通过 `/goal` 查看状态，通过 pause/resume/clear 控制运行。

所以我们应该直接学习这个接口，而不是发明一套完全不同的 `/loop` 对话语义。

### 16.3 对 Famou 的正确抽象

Famou 的 goal mode 应该对齐成：

```text
/goal <objective>
  ↓
创建/替换 active goal
  ↓
立刻启动一个 master turn
  ↓
turn 完成后 goal evaluator 判断：
  ├─ 完成 → mark done / clear active goal
  ├─ 未完成 → 生成下一步 reason，继续下一 turn
  ├─ 阻塞 → mark blocked，等人或外部状态变化
  └─ 被用户暂停/清除 → pause / clear
```

### 16.4 和 e2e benchmark 的关系

`--mode loop` 不应该只是“启动时换 prompt”，而应该等价于自动设置一个 goal：

```bash
famou-scientist --mode loop --bench matbench --task dielectric
```

等价内部目标：

```text
/goal 在 Matbench dielectric 上自主寻优，直到：
1. official validation evaluator 得到 best score；
2. 达到 max_trials / walltime / gpu budget；
3. final/submission.*、final/score.json、final/report.md、final/reproduce.sh 全部产出；
4. 评测工具确认 submission 合法且无泄漏。
```

用户在正常对话中也可以手动触发：

```text
/goal 在当前 benchmark-runs/matbench/dielectric 下继续优化，直到 valid MAE 低于 baseline 10% 或 20 次 trial 用完
```

### 16.5 Famou 不应完全照搬的一点

Claude Code 的 `/goal` evaluator 是一个**轻量模型 evaluator**，它不读文件、不跑命令，只判断“对话里是否证明条件满足”。这对 coding task 合理，但对科研 benchmark 不够。

开放式科研 goal 可以需要两层判断，但完整 benchmark 只需要官方评测器：

```text
开放式 research workflow
  └─ Goal Evaluator
  ├─ 判断 goal 是否应该继续 / 完成 / 阻塞
  └─ 可以读 conversation + goal event log + 受控 score summary

benchmark_managed workflow
  └─ Trusted Benchmark Evaluator
  ├─ 真正读取 hidden test / hidden label / hidden rubric
  ├─ 运行官方 metric / unit test / judge
  └─ 只返回 score.json
```

也就是说：

- **Goal evaluator** 只服务于开放式科研目标；
- **Benchmark evaluator** 决定“submission 得多少分”；
- **完整 benchmark 的下一轮与停止**由尝试次数、墙钟时间、提交预算等确定性规则决定；
- agent / master 不能越过 benchmark evaluator 自己打分。

这是 Famou 相比 CC/Codex 需要增强的地方。

### 16.6 Famou 组件架构图

```text
Human
  │
  │  /goal set/edit/pause/resume/clear/status
  ▼
Master Agent / Goal Controller
  ├─ goal.json                 # active goal + condition + status
  ├─ events.jsonl              # turn/evaluator/worker/score event log
  ├─ goal evaluator            # 判断是否继续下一 turn
  ├─ worker scheduler          # 并发调度
  ├─ human policy gate         # 何时必须问人
  └─ evaluator proxy           # 只能拿 score summary
       │
       ├─ Worker A: baseline / reproduction
       ├─ Worker B: method scouting / literature
       ├─ Worker C: training / ablation / search
       └─ Worker D: repair / packaging
                │
                ▼
        Trusted Benchmark Evaluator
          ├─ hidden test / label / rubric
          ├─ official metric / judge / unit test
          └─ score.json only
```

### 16.7 对应到我们的实现接口

建议 Famou 支持：

```text
/goal <objective>          # 设置/替换 active goal，并立即启动
/goal                      # 查看状态：condition、turns、elapsed、tokens、best score、last reason
/goal edit <objective>     # 修改 objective
/goal pause                # 暂停，不再自动开启下一 turn
/goal resume               # 恢复
/goal clear                # 清除 active goal
/goal inject <note>        # 用户把新约束/偏好注入 active goal
```

CLI：

```bash
famou-scientist --mode loop --bench <bench> --task <task>
famou-scientist run --mode loop --bench-spec benchmark.yaml
famou-scientist run '/goal ...'
```

持久化：

```text
.famou/goals/<goal_id>/
├── goal.json
├── events.jsonl
├── status.json
├── workers/
├── evaluator/
└── artifacts -> benchmark-runs/...
```

### 16.8 收紧版：Famou `/goal` 运行循环

Famou 的 `/goal` 不应该只是把一个 objective 写进 prompt，而应该是下面这条闭环：

```text
User sets goal
  │
  ▼
Goal Store
  ├─ goal.json: objective / success_condition / budget / status
  └─ events.jsonl: turn, worker, evaluator, human events
  │
  ▼
Master Turn
  ├─ 读 goal 状态
  ├─ 决定本轮 next actions
  ├─ 启动/等待/取消 workers
  ├─ 调 trusted evaluator proxy
  └─ 写回 events
  │
  ▼
Goal Evaluator
  ├─ COMPLETE  → mark done, stop auto-continuation
  ├─ CONTINUE  → inject reason, start next master turn
  ├─ BLOCKED   → stop, wait for human/external state
  ├─ PAUSED    → stop until /goal resume
  └─ CANCELLED → cleanup, stop
```

#### 每轮 master turn 的输入

```text
1. 当前用户消息；
2. active goal 的 goal.json；
3. events.jsonl 的最近窗口；
4. worker 状态摘要；
5. trusted evaluator 返回的 score summary；
6. budget / policy / human gate 配置。
```

#### 每轮 master turn 的输出

```text
1. 新的 events；
2. 需要启动/停止的 worker；
3. 需要调用的 evaluator；
4. 需要呈现给用户的摘要；
5. 给 goal evaluator 的 completion evidence。
```

#### goal evaluator 的输入和输出

Goal evaluator 不直接跑实验，也不直接读 hidden test。它只判断“这个 goal loop 是否应该继续”：

```yaml
input:
  objective: "..."
  success_condition: "..."
  latest_events: [...]
  artifacts:
    best_score: ...
    final_files: [...]
  budget:
    turns_used: ...
    walltime_used: ...
    trials_used: ...
  blockers: [...]

output:
  decision: COMPLETE | CONTINUE | BLOCKED | PAUSED | CANCELLED
  reason: "..."
  next_prompt: "..."      # CONTINUE 时注入下一 turn
```

这和 trusted benchmark evaluator 分开：

| 组件 | 能看到什么 | 负责什么 | 不能做什么 |
|---|---|---|---|
| Master Agent | 用户消息、公开数据、goal log、score summary | 调度与决策 | 不能看 hidden test |
| Worker | 被分配的公开任务与产物目录 | 实现、训练、修复、打包 | 不能绕过 evaluator |
| Goal Evaluator | objective、events、score summary、artifact manifest | 判断是否继续下一 turn | 不能给 benchmark 打分 |
| Trusted Benchmark Evaluator | submission、hidden test/rubric、官方 metric | 真实评分与防泄漏 | 不参与方法搜索 |

### 16.9 收紧版：Human → Master → Workers → Evaluator

```text
                         ┌──────────────────────┐
                         │        Human         │
                         │  chat / /goal cmds   │
                         └──────────┬───────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────┐
│                 Master Agent / Goal Controller               │
│                                                              │
│  - interpret human intent                                    │
│  - maintain active goal                                      │
│  - schedule workers                                          │
│  - summarize progress                                        │
│  - apply human policy gates                                  │
│  - invoke evaluator proxy                                    │
└──────────────┬───────────────────────┬───────────────────────┘
               │                       │
               ▼                       ▼
     ┌─────────────────┐      ┌─────────────────┐
     │ Goal Store      │      │ Worker Runtime  │
     │ goal.json       │      │ concurrent jobs │
     │ events.jsonl    │      │ isolated dirs   │
     │ status.json     │      │ logs/artifacts  │
     └─────────────────┘      └───────┬─────────┘
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │ Submission Artifact │
                           └──────────┬──────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ Trusted Benchmark Eval   │
                         │ hidden test/rubric only  │
                         │ official metric/judge    │
                         └──────────┬───────────────┘
                                    │
                                    ▼
                           score.json / eval event
```

这个图里最重要的边界：

- Human 不直接控制 worker，只通过 master 改 goal；
- Master 不直接评测 benchmark，只调 trusted evaluator；
- Worker 只产出 artifact，不知道 hidden test；
- Goal evaluator 只判断是否继续，不负责 benchmark 分数。

### 16.10 收紧版：`--mode loop` 和 `/goal` 的统一语义

`--mode loop` 本质上只是 `/goal` 的启动快捷方式：

```bash
famou-scientist --mode loop --bench matbench --task dielectric
```

等价于：

```text
/goal 在 Matbench dielectric benchmark 上自主寻优。
成功条件：
1. 已通过 trusted evaluator 得到 best valid score；
2. 已完成 baseline score 和至少一个改进 trial；
3. final/submission.*、final/score.json、final/report.md、final/reproduce.sh 存在；
4. evaluator 判定 submission 格式合法且无泄漏；
5. 达到预算上限或连续若干轮无提升。
```

交互式正常启动时，用户也可以随时创建 goal：

```text
/goal 继续当前材料发现 benchmark，目标是在 12 小时内把 valid F1 提升到 baseline 以上 5%，并保留可复现脚本
```

这时 master agent 要：

1. 创建 active goal；
2. 启动第一轮 master turn；
3. 根据每轮 goal evaluator 的结果自动继续；
4. 允许用户随时 `/goal pause/edit/resume/clear`；
5. 对普通聊天保持响应，不让 goal 独占对话。

### 16.11 参考链接

- Claude Code `/goal`: https://code.claude.com/docs/en/goal
- Claude Code commands: https://code.claude.com/docs/en/commands
- Codex `/goal` use case: https://learn.chatgpt.com/use-cases/follow-goals
- Codex developer commands / slash commands: https://learn.chatgpt.com/docs/developer-commands?surface=cli
- ChatGPT Scheduled Tasks: https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt
