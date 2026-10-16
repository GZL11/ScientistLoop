---
name: cluster-experiment-execution
description: Submit and monitor real scientific experiments on the cluster through arc_cluster_job, which wraps fm-job-new. Use when an experiment is beyond a local smoke test: training, batch evaluation, GPU jobs, long simulations, large data processing, multi-seed/ablation/grid runs. Local shell/arc_run_experiment is only for quick dry-run or smoke test; formal experiments must be submitted asynchronously with arc_cluster_job(action="submit").
metadata:
  category: experiment
  trigger-keywords: "cluster,fm-job,fm-job-new,集群,提交任务,实验提交,训练任务,批量评测,GPU任务,长实验,simulation,仿真,job,status,logs,pending,running,kill,resource,异步实验,后台实验"
  applicable-stages: "experiment,execution,evaluation,simulation,training"
  priority: "1"
  version: "1.0"
  author: famou-scientist
---

## 何时使用这个 skill

当任务已经进入**正式实验执行**阶段时使用本 skill。正式实验包括：

- 训练、微调、批量评测；
- GPU / 多进程 / 分布式任务；
- 大规模数据处理；
- 数值仿真、长时间 simulation；
- 多 seed、多 condition、多 ablation、多 baseline、多超参组合；
- 任何预估超过 1-2 分钟、或可能阻塞对话的实验。

**原则：本地只做轻量检查，正式实验必须通过 `arc_cluster_job` 走集群。**

| 场景 | 执行方式 |
|---|---|
| 语法检查、路径检查、几秒级 smoke test | 可以在当前 workspace 本地跑 |
| 1 epoch / 1 batch 的快速 dry-run | 可以本地跑，确认脚本可启动 |
| 正式训练、正式评测、长仿真、大数据处理 | 必须用 `arc_cluster_job(action="submit")` 提交集群；该 tool 底层调用 `fm-job` |
| 多 seed / 多 ablation / 多 baseline | 默认拆成多个 cluster job，结果隔离后合并 |

不要用 AGENTS.md 硬编码本规则；本规则由 skill 自身承担，方便独立版本管理、启停和回滚。

---

## 1. 提交前必须检查

正式提交前，先完成以下 checklist：

1. **确认工作目录**：在当前 session 的独立 workspace 内准备脚本、配置和输出目录。
2. **确认脚本路径**：容器内能访问启动脚本，不要引用本地临时路径。
3. **确认数据/模型路径**：数据、checkpoint、输出目录都应是集群容器可访问的持久路径。
3.5 **确认是否在纠正错误执行方式**：标准流程是正式实验必须用 `arc_cluster_job(action="submit")` 提交。如果发现**agent 自己在没有用户干预/授权的情况下**误用本地进程跑了正式实验，应先停止这个违规本地进程，再用 `arc_cluster_job` 规范重提；但如果用户已经介入、询问、要求保留、或这个进程可能是用户主动启动/确认过的，必须先说明情况并等待用户确认，不能直接 kill。
4. **确认镜像**：明确 `--image`；如果用户/项目已有默认镜像，优先沿用。
5. **确认资源**：用 `arc_cluster_job(action="resource")` 查看资源余量。
6. **确认 prefix**：使用可追溯命名，例如 `<topic>-<task>-<MMDD>-<shortid>`。
7. **确认日志与产物**：脚本要定期打印进度和指标，并把结果落盘到唯一输出文件。

查询资源：

```text
arc_cluster_job(action="resource")
```

---

## 2. 标准提交方式

优先调用 tool，不要让 agent 自己拼长 bash 命令：

```text
arc_cluster_job(
  action="submit",
  prefix="<job-prefix>",
  image="<image>",
  gpu=<gpu-num>,
  cpu="<cpu-num>",
  memory="<memory>",
  shm_size="<shm-size>",
  command="<command> <args>"
)
```

该 tool 底层会强制生成等价命令，并自动加 `--no-wait`：

```bash
fm-job run ... --no-wait -- /bin/bash -lc "<command> <args>"
```

关键要求：

- **tool 会强制加 `--no-wait`**：提交后立即返回，避免阻塞 agent 对话。
- `--` 后面才是容器内真正执行的命令。
- 长任务不要本地同步等待。
- 任务提交后记录完整 job name、prefix、命令、资源、输出路径。

示例：

```text
arc_cluster_job(
  action="submit",
  prefix="llm-evolve-ablation-0726-a1b2",
  image="<你的镜像仓库>/famou/ar:py312-cuda124-v1",
  gpu=1,
  cpu="16",
  memory="64Gi",
  shm_size="8Gi",
  command="/bin/bash scripts/run_ablation.sh --seed 0 --condition baseline"
)
```

---

## 3. 提交后如何查看状态

先用 prefix 找完整 job 名：

```text
arc_cluster_job(action="list", prefix="<job-prefix>")
```

然后查日志：

```text
arc_cluster_job(action="logs", job_name="<full-job-name>")
```

必要时查 Pod IP：

```text
arc_cluster_job(action="pod_ip", job_name="<full-job-name>")
```

状态含义：

| 状态 | 含义 | 行动 |
|---|---|---|
| Pending | 已提交但未调度 | 查资源；若长时间 Pending，再看调度事件 |
| Running | 正在运行 | 只在自然断点查日志，不要 busy-poll |
| Completed | 正常结束 | 读取产物，核验指标，再分析 |
| Failed | 失败 | 查 logs，定位根因，修复后重提 |

---

## 4. 异步纪律：不要 busy-poll

`arc_cluster_job(action="submit")` 会通过底层 `fm-job-new run --no-wait` 保证任务异步。Agent 应该：

- 提交后把 job prefix / job name / 输出路径告诉用户；
- 在自然断点查看一次状态；
- 用户追问或进入结果分析时再查状态/日志；
- `Running` 时不要连续循环查询；
- 结果没完成前不要写 Results、Discussion、结论或研究决策。

正确节奏：

```text
提交 job -> list 确认 job name -> 告知用户已提交 -> 继续做不依赖结果的工作 -> 自然断点查一次 -> 完成后读取产物并分析
```

错误节奏：

```text
提交 job -> 每几秒 list/logs 一次 -> 阻塞对话 -> 结果没出来就下结论
```

---

## 5. 多实验并行：拆分、隔离、合并

多 seed、多 ablation、多 baseline、多数据分片默认是独立轴，优先拆成多个 cluster job。

### 5.1 拆分原则

| 条件 | 处理 |
|---|---|
| seed / condition / baseline 独立 | 拆成多个 job |
| 单 job 资源 × 并发数超过资源余量 | 降低并发或分批提交 |
| 分片间有依赖 | 依赖轴串行，独立轴仍可并行 |
| 每片只有几秒 | 不拆，避免调度开销大于收益 |

### 5.2 结果隔离

每个 job 必须写唯一结果文件，例如：

```text
outputs/<run_id>/results_seed0_baseline.json
outputs/<run_id>/results_seed1_baseline.json
outputs/<run_id>/results_seed0_methodA.json
```

不要让多个 job 同时写同一个：

```text
outputs/results.json
```

这会造成并发覆盖，属于静默数据损坏。

### 5.3 完成后合并

只有所有必要分片都 `Completed` 后，才能合并：

```text
results_*.json -> aggregate_results.json -> tables/figures/report
```

如果某个分片失败，只重跑失败分片，不要无脑整批重跑。

---

## 6. 日志和产物要求

实验脚本必须定期输出：

- step / epoch / progress；
- loss / accuracy / main metric；
- 当前配置、seed、condition；
- 输出路径；
- 错误堆栈不要吞掉。

推荐日志格式：

```text
epoch 3/10 train_loss: 0.412 val_acc: 0.781 elapsed_sec: 532
```

产物要求：

- 原始结果保存为 JSON/CSV；
- 聚合结果单独保存；
- 图表和表格从结果文件生成，不手写数字；
- checkpoint、cache、preprocessed data 写到可复用持久路径；
- 最终分析只引用真实落盘结果。

---

## 7. 失败处理

失败后按以下顺序排查：

1. 查完整 job 名：

```text
arc_cluster_job(action="list", prefix="<job-prefix>")
```

2. 查日志：

```text
arc_cluster_job(action="logs", job_name="<full-job-name>")
```

3. 重点看：

- 路径不存在；
- 脚本无执行权限；
- 镜像缺依赖；
- 数据未挂载；
- OOM；
- NCCL timeout；
- CUDA / driver 问题；
- Python Traceback；
- `/dev/shm` 不够。

4. 修复后重提，prefix 加后缀以便追溯，例如：

```text
llm-evolve-ablation-0726-a1b2-r2
```

---

## 8. 取消/纠正任务

取消分两类，必须区分：

### 8.1 纠正 agent 自己的违规本地实验

如果满足全部条件，可以自行停止并规范重提：

1. 这是**正式实验**，按本 skill 应该走 `arc_cluster_job`；
2. 当前却是 agent 自己误用本地 `subprocess` / shell / `arc_run_experiment` 启动；
3. 用户此前没有明确要求保留该本地进程，也没有介入确认该进程继续运行；
4. 停止后会立即用 `arc_cluster_job(action="submit")` 重新提交，且保留/说明已有日志和产物状态。

这种情况下，停止本地违规进程属于**纠正 agent 自己的执行错误**，可以执行，但必须在回复中透明说明：原先哪里不规范、停止了什么、重新提交了什么。

### 8.2 用户介入后或用户/外部任务的取消

如果用户已经介入，或者任务可能是用户主动启动/确认过的，默认不要主动取消。只有在用户明确说“取消 / 停止 / kill / 别跑了”时，或用户已明确同意取消方案后，才能执行：

```text
arc_cluster_job(action="kill", job_name="<full-job-name>", confirmed=true)
```

注意：

- `--job` 需要完整 job 名，不是 prefix；
- 如果这是用户介入后、用户主动启动、或来源不确定的任务，**没有明确同意不要调用 kill，先追问确认**；
- kill 前确认重要产物是否已落盘；
- kill 后日志和 Pod 可能被清理，必要时先保存日志。

---

## 9. 和其他 skill 的边界

| skill | 负责什么 | 不负责什么 |
|---|---|---|
| `experimental-design` | 设计实验变量、对照组和指标 | 不提交集群任务 |
| `resource-planning` | 估算 GPU/CPU/内存/时间 | 不执行实验 |
| `code-plan-review` | 跑前检查代码是否符合实验设计 | 不负责长任务调度 |
| `cluster-experiment-execution` | 指导用 `arc_cluster_job` 提交、查看、取消正式实验 | 不设计实验、不编造结果 |
| `experiment-repair` | 实验失败后的诊断和修复 | 不替代集群提交规则 |
| `research-decision` | 基于完成后的真实结果做决策 | 不在结果未完成时判断 |

---

## 10. 最重要的硬规则

1. 正式实验必须走 `arc_cluster_job`；该 tool 底层调用 `fm-job`。
2. 提交正式实验必须异步；`arc_cluster_job(action="submit")` 会强制 `--no-wait`。
3. 本地只允许 smoke test / dry-run / 脚本准备。
4. Running 状态下不 busy-poll。
5. 结果未完成前不分析、不写结论、不做研究决策。
6. 多 job 必须结果隔离，完成后再合并。
7. 发现 agent 自己误用本地方式跑正式实验时，可以停止该违规本地进程并用 `arc_cluster_job` 重提；但用户介入或来源不确定时必须先问。
8. 所有 job name、prefix、命令、资源、输出路径都要可追溯。
