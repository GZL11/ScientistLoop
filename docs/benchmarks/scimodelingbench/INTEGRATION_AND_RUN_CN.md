# SciModelingBench 接入 Famou Loop 设计与实跑记录

> 有限 GT 升级：2h 研究预算、k=0/1/5/20、Agent 自主决定查询时机、独立最终审计，见 [LIMITED_GT_PROTOCOL_CN.md](./LIMITED_GT_PROTOCOL_CN.md)。使用新 graph `scimodeling_budget`；下文原始流程对应 `sota_search`。

> 状态：已安装 `sci-modeling-bench==0.10.0`，已固定 HF dataset revision `d8b9ea3c78ed33edf0869a427940a0651eb49f52`，已导出 13 个 task 的 agent-visible problem，`tfbind8` 已通过 canonical runner + signed trusted evaluator 真实评分 smoke。

> 结果登记：完整 run registry 见 [RESULTS_REGISTRY_CN.md](./RESULTS_REGISTRY_CN.md)，机器可读主表见 [RESULTS_REGISTRY.csv](./RESULTS_REGISTRY.csv)。登记表保留外层 `fm-job` 状态、loop 内部状态、分数、promoted 输出目录、轨迹、usage、token 和 cost 等字段。

## 1. 接入目标

SciModelingBench 的任务产物是候选列表，不是论文复现代码仓库。因此接入 Famou Loop 时，目标不是让 Agent 直接调用 `Task.evaluate()`，而是：

1. Agent 读取公开 `benchmark_task/`。
2. Agent 写 `run.py`。
3. canonical runner 执行 `run.py`，只允许写 `OUTPUT_DIR/submission.json`。
4. BenchmarkAdapter 冻结 submission artifact 并做公开格式检查。
5. EvaluatorAdapter 把 artifact 发布到固定 evaluator 输入路径。
6. trusted evaluator worker 才加载 `sci_modeling_bench` 和 hidden Objective，调用 `Task.evaluate(submission)`。
   fm-job 启动时会在同一个 Pod 内先执行 dataset preflight；preflight 使用提交时
   的代理补齐 run-local HF cache，成功后 evaluator 才切换到 offline 模式。
7. 返回只含 aggregate metrics 的签名、脱敏响应。

## 2. 已实现文件

| 文件 | 职责 |
|---|---|
| `famou_scientist/loop/integrations/scimodelingbench/task_catalog.py` | 13 个 scored task 的公开 metadata：submission size、primary metric、task form |
| `famou_scientist/loop/integrations/scimodelingbench/benchmark.py` | 公开 BenchmarkFacility：`run.py` 执行、`submission.json` 冻结、格式检查、公开 agent view |
| `famou_scientist/loop/integrations/scimodelingbench/evaluation.py` | EvaluatorFacility：校验 artifact hash，发布到固定 `workspace/output/submission/`，通过 trusted transport 请求评分 |
| `famou_scientist/loop/integrations/scimodelingbench/evaluator_worker.py` | signed file channel 可信 worker，默认或自定义 loader 构造 SciModelingBench Task |
| `famou_scientist/loop/integrations/scimodelingbench/prepare_problem.py` | trusted setup：加载 package task，调用 `build_input()`，只导出 agent-visible problem |
| `famou_scientist/loop/integrations/scimodelingbench/plugin.py` | `BenchmarkAdapter` / `EvaluatorAdapter` 入口 |
| `famou_scientist/loop/plugins/registry.py` | 内置注册 `scimodelingbench` adapter |

## 3. 隔离边界

| 层 | 可见 | 不可见 / 不可做 |
|---|---|---|
| Infra / Harness | run dir、problem dir、workspace、队列、预算、artifact hash、签名公钥 | hidden labels、完整 Objective、私钥 |
| Agent | `benchmark_task/` 公开题面、visible data、manifest、submission schema、脱敏 aggregate feedback | 完整 HF cache、provenance、hidden candidate labels、`Task.evaluate()` |
| BenchmarkAdapter | Agent 代码、公开题面、`submission.json` artifact | SciModelingBench trusted Objective、hidden label、正式分数 |
| EvaluatorAdapter | artifact hash、固定 workspace output、trusted transport | 直接执行 Agent 代码、接受 Agent 指定路径 |
| Evaluator worker | 完整 package、HF revision、trusted cache、hidden Objective、签名私钥 | Agent 写权限、未签名响应、per-candidate hidden score 泄漏 |

## 4. Agent 输出契约

Agent 必须提交根目录 `run.py`：

```python
import json
import os

task_dir = os.environ["BENCHMARK_TASK_DIR"]
output_dir = os.environ["OUTPUT_DIR"]

# 读取 benchmark_task/ 下的公开数据和 schema，自行生成候选。
submission = [
    {"sequence": "AAAAAAAA"},
    # ...
]

os.makedirs(output_dir, exist_ok=True)
with open(os.path.join(output_dir, "submission.json"), "w", encoding="utf-8") as f:
    json.dump(submission, f)
```

公开 runner 会把输出冻结为：

```text
run/candidates/<candidate_id>/output/submission/submission.json
```

然后 `ArtifactRef` 会记录目录 hash。artifact 变化会导致正式评分前失败。

## 5. Task ID

当前 adapter 展平为 13 个 scored tasks：

| Task ID | Submission | Primary metric |
|---|---:|---|
| `tfbind8` | 32 | `best_k_mean` |
| `tfbind10_pho4` | 128 | `normalized_enrichment` |
| `cell_dag_nas` | 32 | `best_k_mean` |
| `superconductor` | 32 prefix | `global_ndcg` |
| `hopper_controller` | 32 prefix | `global_ndcg` |
| `utr_mrl_egfp_unmodified` | 128 prefix | `normalized_enrichment` |
| `gfp` | 128 prefix | `normalized_enrichment` |
| `drugmatrix_mchc` | 16 prefix | `global_ndcg` |
| `drugmatrix_mch` | 16 prefix | `global_ndcg` |
| `drugmatrix_creatinine` | 16 prefix | `global_ndcg` |
| `drugmatrix_sodium` | 16 prefix | `global_ndcg` |
| `drugmatrix_chloride` | 16 prefix | `global_ndcg` |
| `drugmatrix_phosphorus` | 16 prefix | `global_ndcg` |

## 6. 安装与数据准备

当前环境已完成安装。worker image 需要和准备端保持一致的 HF 栈：
`datasets==4.8.5`、`huggingface_hub==1.15.0`、`pyarrow==24.0.0`。
否则宿主机生成的 Arrow cache 可能无法被 Pod 内旧版 `datasets` 读取。

```bash
env ALL_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HTTPS_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HTTP_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  python3 -m pip install sci-modeling-bench
```

单 task 准备命令：

```bash
env ALL_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HTTPS_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HTTP_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HF_HOME=.famou/scimodelingbench/hf_home \
  HF_DATASETS_CACHE=.famou/scimodelingbench/hf_home/datasets \
  python3 -m famou_scientist.loop.integrations.scimodelingbench.prepare_problem \
  --task-id tfbind8 \
  --problem-dir .famou/scimodelingbench/runs/tfbind8/problem \
  --cache-dir .famou/scimodelingbench/trusted_cache \
  --overwrite
```

当前 13 个 task 均已准备到 `.famou/scimodelingbench/runs/<task_id>/problem`：

正式 fm-job 提交必须在提交 shell 中设置 `ALL_PROXY`、`HTTPS_PROXY` 和
`HTTP_PROXY`。准备阶段允许通过这些代理访问 HuggingFace；Pod 内的 preflight
完成后，实际 Agent/evaluator loop 使用 run-local cache 和 offline flags，不会在
评分过程中临时下载数据。

| Task ID | Public views |
|---|---|
| `tfbind8` | observations: 32768 |
| `tfbind10_pho4` | observations: 2087323 |
| `cell_dag_nas` | observations: 419803 |
| `superconductor` | observations: 16795; candidates: 2985 |
| `hopper_controller` | observations: 1920; candidates: 1280 |
| `utr_mrl_egfp_unmodified` | observations: 76877; candidates: 5043 |
| `gfp` | protein_observations: 41372; nucleotide_observations: 42943; barcode_observations: 45577; candidates: 10343 |
| `drugmatrix_mchc` | observations: 9442; candidates: 390 |
| `drugmatrix_mch` | observations: 9442; candidates: 390 |
| `drugmatrix_creatinine` | observations: 9442; candidates: 390 |
| `drugmatrix_sodium` | observations: 9442; candidates: 390 |
| `drugmatrix_chloride` | observations: 9442; candidates: 390 |
| `drugmatrix_phosphorus` | observations: 9442; candidates: 390 |

每个 problem 目录包含：

```text
problem/
  task.md
  manifest.json
  metric_contract.json
  submission_schema.json
  tables.json
  context.json
  prepare_report.json
  data/*.jsonl
```

## 7. 运行方式

### 7.1 fm-job 提交

和 NatureBench 一样，正式集群运行推荐走 `fm-job`：

```bash
export ALL_PROXY=http://<用户名>:<密码>@<代理主机>:<端口>
export HTTPS_PROXY=http://<用户名>:<密码>@<代理主机>:<端口>
export HTTP_PROXY=http://<用户名>:<密码>@<代理主机>:<端口>

TASK_ID=tfbind8 \
MODEL=<model> \
AGENT_RUNTIME=claude \
AGENT_CPU=16 \
AGENT_GPU=0 \
AGENT_MEMORY_GIB=64 \
FM_JOB_BIN=/path/to/workspace/lihuaiming/fm-job \
bash famou_scientist/loop/examples/scimodelingbench/fmjob/submit_one_click.sh
```

Kimi Code 续跑使用同一个 `RUN_DIR`，并显式传入 Kimi CLI 的真实 binary：

```bash
RUN_DIR=.famou/scimodelingbench-fmjob-runs/tfbind8-20260811-234519 \
AGENT_RUNTIME=kimi-code \
AGENT_BINARY=/root/.kimi-code/bin/kimi \
MODEL=kimi-k3 \
bash famou_scientist/loop/examples/scimodelingbench/fmjob/submit_one_click.sh
```

当前 Kimi Code CLI（0.29.x）使用 `--prompt` + `--output-format stream-json`，不是
`--print`。`kimi-code` runtime 会把 `HOME` 隔离到每个 Actor 的 branch 日志目录，
并保存原生 session id；同一 Actor 的后续激活会使用 `--session <id>`，没有可解析
session id 时回退到 `--continue`。`z-code` 在本项目中指百度 Comate Zulu，实际使用
`zulu run --query ...`，不复用 Kimi 的 `--prompt` 协议；镜像同时提供 `zulu` 和
`z-code` 命令名。`cli-runtimes-v1` 镜像包含 `claude`、OpenAI `codex`、`opencode`、
Kimi Code `kimi` 以及 Comate Zulu `zulu`/`z-code`。所有 CLI 凭证都在 Job 运行时通过
环境变量或挂载目录提供，不写入镜像。

提交脚本会执行三步：

1. `prepare_run.py`：创建 `run_dir`，复制 public runtime / trusted runtime，导出公开 `problem/`，把 HF cache 放进 `trusted/scimodelingbench/hf_home`。
2. 生成 evaluator 响应签名密钥：私钥在 `trusted/private_key.pem`，公钥在 `controller/evaluator_channel/public_key.pem`。
3. `fm-job run -- ... task_entrypoint.sh`：在同一个 Pod 内启动 trusted evaluator worker 和 `famou-scientist agent run`。

可先 dry-run，不提交集群任务：

```bash
DRY_RUN=1 \
TASK_ID=tfbind8 \
MODEL=<model> \
bash famou_scientist/loop/examples/scimodelingbench/fmjob/submit_one_click.sh
```

默认输出目录：

```text
.famou/scimodelingbench-fmjob-runs/<task_id>-<timestamp>/
  problem/                         # Agent 可见，只读
  famou-scientist/                 # public runtime，不含 trusted-only scimodelingbench helper
  trusted/
    famou-scientist/               # trusted runtime，含 evaluator_worker
    scimodelingbench/hf_home/      # trusted HF cache
    private_key.pem
  controller/evaluator_channel/
    public_key.pem
    requests/
    responses/
  workspace/
  results/
```

内层 `task_entrypoint.sh` 会对 `agent run` 显式传：

```bash
--benchmark-adapter scimodelingbench
--evaluator-adapter scimodelingbench
--no-scimodelingbench-managed-evaluator
--no-scimodelingbench-prepare-problem
```

这样 fm-job supervisor 是唯一的 evaluator 进程管理者；Famou core 只通过签名 file channel 调用评分。

### 7.2 本地 / 手工通道

Trusted evaluator worker 侧：

```bash
env ALL_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HTTPS_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HTTP_PROXY=http://<用户名>:<密码>@<代理主机>:<端口> \
  HF_HOME=.famou/scimodelingbench/hf_home \
  HF_DATASETS_CACHE=.famou/scimodelingbench/hf_home/datasets \
  python3 -m famou_scientist.loop.integrations.scimodelingbench.evaluator_worker \
  --task-id tfbind8 \
  --workspace-dir .famou/scimodelingbench/runs/tfbind8/workspace \
  --channel-dir .famou/scimodelingbench/runs/tfbind8/channel \
  --private-key .famou/scimodelingbench/runs/tfbind8/channel/private_key.pem \
  --cache-dir .famou/scimodelingbench/trusted_cache
```

Controller / Agent 侧仍通过 plugin 隔离接入：

```bash
famou-scientist agent run \
  --task-id tfbind8 \
  --benchmark-adapter scimodelingbench \
  --evaluator-adapter scimodelingbench \
  --run-dir .famou/scimodelingbench/runs/tfbind8 \
  --problem-dir .famou/scimodelingbench/runs/tfbind8/problem \
  --workspace-dir .famou/scimodelingbench/runs/tfbind8/workspace \
  --evaluator-channel .famou/scimodelingbench/runs/tfbind8/channel \
  --evaluator-public-key .famou/scimodelingbench/runs/tfbind8/channel/public_key.pem \
  --scimodelingbench-managed-evaluator \
  --scimodelingbench-cache-dir .famou/scimodelingbench/trusted/scimodelingbench/hf_home \
  --scimodelingbench-revision d8b9ea3c78ed33edf0869a427940a0651eb49f52
```

默认行为：

- `benchmark_adapter=scimodelingbench` 时，CLI 会先把公开 `problem/` 准备好。
- 开启 `--scimodelingbench-managed-evaluator` 时，CLI 会自动生成 channel keypair 并启动 trusted worker。
- 如果你已有外部 trusted worker，可以显式加 `--no-scimodelingbench-managed-evaluator`，继续用自己的 channel。

如果外部 `sci_modeling_bench` package 的 task class 名称和 adapter 默认映射不一致，用可信 loader 覆盖：

```bash
python3 -m famou_scientist.loop.integrations.scimodelingbench.evaluator_worker \
  ... \
  --task-loader trusted_smb_loader:load_task
```

`load_task(task_id: str, revision: str | None, cache_dir: str | Path | None)` 返回带 `evaluate(submission)` 方法的 task 对象即可。

## 8. 已验证

本地测试：

```bash
python3 -m pytest \
  famou_scientist/loop/tests/test_scimodelingbench_integration.py \
  famou_scientist/loop/tests/test_plugins.py
```

覆盖点：

- adapter registry 可加载 `scimodelingbench`。
- `TaskView` 只暴露公开 submission contract。
- BenchmarkAdapter 可检查 `submission.json`，但拒绝官方评分。
- runner 会冻结 `submission.json` artifact。
- EvaluatorFacility 会二次过滤 `raw_candidate_scores`、`hidden_label_*`、`hidden_target_*` 等字段。

真实 smoke：

- `tfbind8` problem 已从 package `Task.build_input()` 导出，public observations 32768 条。
- smoke candidate 通过 canonical runner，artifact 为 `.famou/scimodelingbench/runs/tfbind8/candidates/candidate-smoke/output/submission`。
- signed file-channel trusted evaluator 已完成评分，`valid=true`。
- 返回指标：`score=0.43929409980773926`，`best_k_mean=0.43929409980773926`，`normalized_enrichment=-0.046492266306412934`，`global_ndcg=0.44207626773941616`。
- 响应只含 aggregate scalar metrics，未返回 per-candidate hidden score、hidden label 或 Objective output。

## 9. 后续缺口

1. 为 13 个 task 建批量运行脚本和 All Score 汇总器。
2. 当前公开表统一导出 JSONL，`tfbind10_pho4` 较大；后续可增加 parquet 模式提升大表导出和读取效率。
3. 明确对外评测预算：wall-clock、LLM calls/tokens、official evaluations、CPU/GPU。
