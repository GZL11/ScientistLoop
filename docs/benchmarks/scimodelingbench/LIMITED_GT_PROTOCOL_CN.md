# SciModelingBench 有限 GT 访问协议 v1

新入口为 `--agent-graph scimodeling_budget`，协议名为
`scimodelingbench-limited-gt-v1`。每个 task 独立比较 **k=0/1/5/20**，
每次运行有 **2 小时研究墙钟预算**。Agent 预先知道 k 和截止时间，自己决定何时查询 GT，
可不使用全部额度。适用于现有 13 个 task，包括 3 个黑盒优化和 10 个候选池排序任务。

## 计数与时间

- **一次 GT 查询**是对一份完整 `submission.json` 调用一次可信评测器，不是单个候选的评测。
  候选数量、合法性和任务指标沿用各任务原有规则；返回脱敏的聚合指标，不返回逐候选隐藏标签。
- 研究期间至多 k 次查询。多个工作进程共享同一 controller 账本，不能各自获得 k 次。
- 公开 `(x,y)` 数据、代理模型训练、公开验证、候选搜索不限次数，但计入 2 小时。
  GT 请求的等待时间也计入；预算耗尽后仍可继续研究。
- 公开的文件/JSON/候选数量检查失败不扣 GT。请求通过预检查后，controller **先持久化扣额，再调用评测器**。
  GT 判定无效、调用报错、超时或崩溃导致结果不确定均不退款，也不自动重试。
- 2 小时从创建研究 session 开始，数据准备和可信服务启动在此前完成。
  截止时间是持久化的绝对时间，恢复运行不会补时；停机时间也会消耗剩余预算。
  同一个 run 不能同时启动两个研究 controller。
- 截止后不再激活 Agent。正在进行的 GT 可能在截止后才返回，但不会再向 Agent 提供反馈。
  Pod 额外预留的收尾时间仅用于可信评测及清理，不增加 Agent 研究时间。

## 最终结果

Agent 必须主动选择最终提交，controller 保存其只读快照。到时锁定的是
**最近一次在截止前成功 `select` 的结果**，不自动使用历史 GT 最高分。
Agent 可以选择未查询过的结果，也可以选择之前查询过的结果。

冻结后独立进行 **1 次最终审计，不计入 k**；审计结果不回传 Agent。
因此 k=0 也能得到最终分数，正常情况下总 GT 调用数最多为 k+1。
最终审计开始后崩溃不会自动重跑，记录为不确定/失败；没有最终选择则不执行审计，
记录 `no_final_submission`，分数为 null，不伪造为 0。

主要比较字段为 `final_score`，不是历史 `best_score`。历史曲线仅作诊断。
Agent 可提前 `finish`；2 小时是上限，未使用完的时间和查询额度不强制消耗。

## Agent 操作

一个持续研究会话复用现有 CLI runtime。每次激活提供预算、剩余秒数、绝对截止时间、
上一次操作反馈、公开题面和资源配置。Agent 在自己的 worktree 中训练模型、运行代码，
生成符合任务格式的 JSON 数组，然后向 `famou_scimodeling_result.json` 写入以下一种操作并结束当前 turn：

| 操作 | 示例 | 行为 |
|---|---|---|
| 保存最终选择 | `{"action":"select","submission":"outputs/submission.json"}` | 冻结已有文件，不扣 GT；之后仍可研究和更新选择 |
| 请求 GT | `{"action":"query","submission":"outputs/submission.json","reason":"验证代理选出的候选"}` | 扣一次查询并返回聚合反馈；不更改最终选择 |
| 继续 | `{"action":"continue"}` | 更新上下文并继续研究 |
| 提前结束 | `{"action":"finish"}` | 锁定已选择的提交并进入最终审计；必须先 select |

提交路径必须位于 worktree 内，不能使用绝对路径、`..` 或符号链接。
每次激活清理旧操作文件。操作只有在 Agent 退出当前 turn、controller 验证并接受后才生效。
**应尽早 select 一个可用结果**；超时留在工作目录中、尚未被接受的文件不算最终提交。
controller 不会在研究结束后重新执行 Agent 的代码。

## 批量运行

先预览一个任务的四个预算组，不准备数据、不提交作业：

```bash
MODEL=glm-5.2 TASKS=tfbind8 DRY_RUN=1 \
  bash famou_scientist/loop/examples/scimodelingbench/fmjob/submit_limited_gt.sh
```

提交全部 13 个 task、四个 k、每组 3 次独立重复，共 156 个作业：

```bash
MODEL=glm-5.2 REPEATS=3 BATCH_ID=limited-gt-v1-r3 \
  bash famou_scientist/loop/examples/scimodelingbench/fmjob/submit_limited_gt.sh
```

批量脚本固定研究预算为 2h，默认资源为 8 CPU、0 GPU、32 GiB，可用
`AGENT_CPU`、`AGENT_GPU`、`AGENT_MEMORY_GIB` 统一调整。
`TASKS`、`GT_BUDGETS` 可缩小实验范围；所有预算组使用相同模型、runtime 和资源配置。
run ID 包含 task、batch、k、repeat，每组使用独立工作目录、会话与 GT 账本，
不得读取其他组的历史结果或复用其模型。新实验应使用新的 BATCH_ID。
同一批次的重复运行是独立试验，不保证 CLI 模型的随机种子可控。

恢复**某一个**已有 run 时，使用原始模型、资源、时间及 k：

```bash
MODEL=glm-5.2 TASK_ID=tfbind8 AGENT_GRAPH=scimodeling_budget \
  OFFICIAL_GT_BUDGET=5 MAX_WALL_TIME_HOURS=2 \
  AGENT_CPU=8 AGENT_GPU=0 AGENT_MEMORY_GIB=32 \
  RUN_ID=tfbind8-limited-gt-v1-r3-k5-r1 RESUME=1 \
  bash famou_scientist/loop/examples/scimodelingbench/fmjob/submit_one_click.sh
```

公开输入 hash、模型、runtime、资源、k、总时间写入 session，恢复时要求一致。
已完成 run 的恢复不会再启动 Agent 或重复最终审计。

本地集成可以直接设置 `--agent-graph scimodeling_budget --official-gt-budget 5
--max-wall-time-hours 2`，并配置 SciModelingBench 的 benchmark/evaluator adapters。
新模式不接受 `--iterations`，因为 Agent 的操作次数与 GT 查询次数不是一回事。
旧 `sota_search` 的参数行为保持兼容；新协议固定执行独立最终审计，
不受旧入口的 `--no-finalize-evaluation` 开关影响。

## 记录与比较

- `controller/limited_gt/state.json`：可信账本，包括预扣额度、冻结选择、绝对截止时间和最终审计状态。
- `controller/limited_gt/turn_*.json`：每次 Agent 激活的结果和 telemetry。
- `controller/run_summary.json`：`official_gt_budget`、`official_gt_used`、`final_score`、`outcome`、最终 artifact 及实验配置。
- `limited_gt_agents/branches/researcher/`：持续研究会话、公开预算上下文、代码和日志。

汇总某次 batch 的已完成结果：

```bash
python docs/benchmarks/scimodelingbench/summarize_limited_gt.py \
  .famou/scimodelingbench-fmjob-runs/*limited-gt-v1-r3* \
  --output /tmp/limited-gt-v1-r3.csv
```

输出逐 run CSV，并按 task、k、实验配置输出分组统计（成功评分数、总数、均值、样本标准差、平均实际 GT 使用数）。
失败和未提交的 run 保留空分数；不能只挑最高分重复作为主要比较结果。
尚未写入 run_summary 的运行不计入统计，工具会提示缺失，需结合集群状态检查。
不同 task 的原始指标不直接求总平均。汇总工具也不会把不同模型/资源/公开输入的试验混为同组。

## 隔离与验证范围

正式实验沿用 FMJob 非 root Agent 与可信 controller/evaluator 的隔离：
隐藏缓存、私钥、评测通道、账本和冻结 artifact 不向 Agent 开放。
仅用同一 UID 在本机运行可以验证功能，但不构成对任意 Agent 代码的访问隔离。
评测请求在 worker 执行前持久化认领，重启不重复 GT；每个有限预算候选有独立固定输入，
避免超时旧请求误读下一份提交。

本次实现通过本地协议测试、模拟 CLI 集成测试及批量命令 dry-run。
