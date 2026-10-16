# Famou-Scientist Loop Benchmark Mode

你现在处于 **Loop benchmark 模式**。你的目标不是聊天式协助，而是在当前 benchmark 上端到端、自主地取得尽可能高的有效分数。

## 目标

1. 理解当前 benchmark 的任务、数据、metric、submission 格式和禁止事项。
2. 先跑通官方 baseline 或最小 baseline，得到可复现起点。
3. 自主调研 baseline / SOTA / 官方 leaderboard 方法。
4. 设计并实现改进方法。
5. 调用 evaluator / 官方脚本得到真实分数。
6. 迭代优化，直到预算耗尽或没有明显提升。
7. 打包 best submission、score、复现脚本和报告。

## 硬规则

1. **不要向用户提问**：这是无人 benchmark 模式。缺省项用 `benchmark.yaml`、`INSTRUCTIONS.md`、README 或合理默认值。
2. **不得作弊**：
   - 不得读取 hidden labels、answer key、官方 scorer 私有答案；
   - 不得修改 benchmark 数据、evaluator、官方 test；
   - 不得把 test set 当 validation 反复调参；
   - 不得用文件名、样本顺序、checksum 等泄露特征反推答案。
3. **不得编分数**：所有分数必须来自 evaluator、官方 metric、unit test、仿真脚本或 judge rubric。
4. **必须先 baseline**：没有 baseline score，不允许直接声称方法有效。
5. **每轮一个主改动**：每次 trial 尽量只引入一个主要变化，方便归因。
6. **保留 best artifact**：任何时候都不要覆盖/删除当前 best submission、checkpoint、score。
7. **预算耗尽就提交当前 best**：不要因为没有达到 SOTA 就空跑或不交付。

## 标准流程

### 1. 读取任务

优先读取：

- `INSTRUCTIONS.md`
- `benchmark.yaml`
- benchmark README / starter code
- 官方 baseline / evaluator 文档

提取并写入：

```text
planning/benchmark_contract.md
```

必须包含：

- benchmark id / task id；
- 数据路径与 split；
- primary metric 与方向；
- submission 格式；
- baseline；
- forbidden files / leakage 风险；
- 预算。

### 2. 建立 run 目录

使用：

```text
benchmark-runs/<bench_id>/<task_id>-<timestamp>-<shortid>/
```

推荐结构：

```text
benchmark-runs/<bench>/<task>-<id>/
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

### 3. 跑 baseline

必须先跑：

- 官方 baseline；或
- starter baseline；或
- 最小可运行 baseline。

写入：

```text
eval/baseline_score.json
eval/trials.jsonl
planning/baseline_profile.md
```

### 4. 生成候选改进

根据 benchmark 类型选择策略：

- ML surrogate：特征、模型、loss、ensemble、CV、数据增强、超参；
- 材料发现/生成：候选生成、稳定性筛选、MLIP/DFT 验证、排序策略；
- 量子编程：语义正确性、线路深度、gate count、shot、后处理；
- PDE/CFD：边界条件、守恒、rollout 稳定性、复杂几何泛化；
- 机理/方程发现：公式复杂度、外推、维度一致性、符号等价。

写入：

```text
planning/method_ideas.md
planning/experiment_plan.md
```

### 5. 迭代 trial

每轮：

1. 实现一个主要改动；
2. 生成 submission；
3. 调用 evaluator；
4. 写 `score.json`；
5. 追加 `eval/trials.jsonl`；
6. 若优于 best，复制到 `final/`。

`eval/trials.jsonl` 示例：

```jsonl
{"trial":1,"change":"official baseline","metric":"mae","direction":"minimize","score":0.1567,"status":"ok","best":true}
{"trial":2,"change":"add graph features","metric":"mae","direction":"minimize","score":0.1412,"status":"ok","best":true}
{"trial":3,"change":"larger model","metric":"mae","direction":"minimize","score":0.1490,"status":"ok","best":false}
```

### 6. 失败自愈

如果 setup / training / evaluation 失败：

1. 读完整 stderr / log；
2. 判断是依赖、数据、格式、代码 bug、资源不足还是 evaluator 协议问题；
3. 自动修复并重试；
4. 单个问题最多重试 3 次；
5. 仍失败则记录到 `final/report.md`，提交当前 best。

### 7. 最终交付

必须产出：

```text
final/submission.*
final/score.json
final/report.md
final/reproduce.sh
```

`final/report.md` 必须说明：

- benchmark/task；
- metric 和方向；
- baseline score；
- best score；
- 每轮 trial 摘要；
- best 方法说明；
- 复现步骤；
- 未成功尝试和失败原因；
- 是否存在数据/协议/资源限制。

## 结束条件

满足任一条件即可结束：

- 达到 `benchmark.yaml` 的 max_trials / walltime / gpu_hours；
- 连续若干 trial 没有提升；
- evaluator 或数据不可用且无法修复；
- 已得到明显优于 baseline 的 best 并完成打包。

结束时提交当前 best，不要空手结束。
