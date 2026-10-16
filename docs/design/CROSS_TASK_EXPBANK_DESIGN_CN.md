# Cross-task ExpBank 设计与用法

> 状态：已实现。本文描述 Famou Loop 中跨任务科研经验库的设计、生命周期、权限边界和 NatureBench/fm-job 的使用方式。

## 1. 背景与目标

Loop 原有的 ExpBank 记录单个研究任务中的 Idea、attempt、评测结果和失败轨迹。它适合在同一 Run 内继续搜索、refine 和恢复，但不能直接回答“同一科研领域的其他任务以前尝试过什么”。

Cross-task ExpBank 在任务结束时把当前 Run 的公开演化轨迹压缩为一条可检索的经验总结，并按 NatureBench 官方领域归档。下一个任务的 Idea Agent 可以读取同领域历史，获得方法启发和失败边界，同时排除当前 Run，避免自读和重复传播。

设计目标是：

- 经验必须来自可追溯的公开 ExpBank 证据；
- 经验按领域隔离，减少跨领域的错误迁移；
- 写入幂等、可并发、可恢复；
- 总结 Agent 失败时仍保留调度器生成的确定性基础总结；
- 集群任务只获得共享经验快照，不获得其他 Run 的完整工作区、GT 或 evaluator 私有内容。

## 2. 两层 ExpBank

| 层次 | 作用 | 典型位置 |
| --- | --- | --- |
| 单任务 ExpBank | 保存本 Run 的 attempt、Idea、分数、失败和 artifact 引用，供当前 Loop 搜索和收尾 | `<run_dir>/expbank/`、`<run_dir>/shared_experience_pool/` |
| Cross-task ExpBank | 保存每个已结束 Run 的结构化演化总结，供同领域后续任务检索 | 项目级 `.famou/cross_task_expbank/`，或 Run 内的共享快照 |

跨任务库不是原始实验日志的替代品。它只保存总结和证据路径；需要追溯细节时，仍应回到对应 Run 的公开 artifact 和 ExpBank。

## 3. 存储结构

项目级库由 `CrossTaskExpBank` 自动初始化：

```text
.famou/cross_task_expbank/
├── README.md
├── index.jsonl
├── cellular_omics/
├── protein_biology/
├── biomedical_modeling/
├── physical_modeling/
├── molecular_design/
└── relational_reasoning/
```

`index.jsonl` 是轻量目录，不是完整实验记录。完整系统记录放在库目录外的宿主侧
`.cross_task_expbank.system.jsonl`，不随 Agent 快照传播。

六个目录对应 NatureBench 官方领域：

| 领域显示名 | 目录 slug |
| --- | --- |
| Cellular Omics | `cellular_omics` |
| Protein Biology | `protein_biology` |
| Biomedical Modeling | `biomedical_modeling` |
| Physical Modeling | `physical_modeling` |
| Molecular Design | `molecular_design` |
| Relational Reasoning | `relational_reasoning` |

`index.jsonl` 每行只保存用于筛选和定位的目录信息；领域目录中对应保存 Agent 生成的可读 Markdown，例如：

```text
cellular_omics/<task_id>--<run_id>.md
```

目录条目只包含 `domain`、`task_summary`、`result`、`best_score` 和 `summary_path`。
Agent 先用这些字段判断任务是否相关，再按 `summary_path` 查看具体演化总结。

目录名、领域名和连字符形式都会被规范化为同一个官方 slug。NatureBench 任务若没有在 Goal 中显式声明领域，则从 `famou_scientist/loop/examples/naturebench/leaderboard/case_metadata.csv` 的 `case_id -> domain` 映射解析。

## 4. 记录模型

系统完整记录仍保留以下字段（列表字段可为空），但不写入 Agent 目录索引：

```json
{
  "task_id": "任务 ID",
  "goal_id": "Goal ID",
  "run_id": "Run ID",
  "domain": "cellular_omics",
  "task_summary": "任务公开目标的短摘要",
  "result": "completed|stopped|failed",
  "attempt_count": 3,
  "best_attempt_id": "attempt-2",
  "best_score": 0.81,
  "method_summary": "最佳方法及核心机制",
  "successful_ideas": ["有正式分数支持的方案"],
  "failed_ideas": ["失败方案及公开可确认的原因"],
  "refine_summary": ["refine 是否提升及边界"],
  "engineering_failures": ["工程、资源或进程故障；为空时省略"],
  "evaluator_observations": ["公开 evaluator 暴露的指标和覆盖信息；无额外观察时省略"],
  "transferable_experiences": [
    {
      "summary": "带适用条件的可迁移结论",
      "kind": "method|failure|evaluation",
      "tags": ["检索标签"],
      "related_domains": ["可能相关的领域 slug"],
      "conditions": ["适用条件"],
      "evidence_refs": ["expbank/attempt-2/record.json"]
    }
  ],
  "negative_transfer": ["不应直接迁移的做法或条件"],
  "evidence_refs": ["expbank/attempt-1/record.json"],
  "created_at": 0,
  "updated_at": 0
}
```

写入时 `experience_id` 默认由 `task_id--run_id` 生成，并经过安全文件名规范化；显式提供同名 ID 也会覆盖同一条记录。因此重复同步不会产生重复经验。

Markdown 总结固定包含：任务概述、方法总结、有效经验、失败经验、Refine 结论、可跨任务经验和不应迁移的经验。
原始 Run 路径和 `evidence_refs` 只留在系统记录，不渲染进 Agent-facing Markdown；除非证据已复制到当前共享快照，否则不能把历史 Run 相对路径当作 Agent 可访问路径。

当前默认模式是 Markdown：总结 Agent 直接编辑 `EVOLUTION.md`，其正文作为跨任务经验的权威内容。旧的结构化 JSON 总结仍然保留，可通过 `workers.experience_summary.format: structured_json` 选择，主要用于兼容已有 Worker、索引和统计代码。

系统完整记录还会保留但不暴露给 Agent 的运行元数据：

```json
{
  "source_run_dir": ".famou/naturebench-runs/<run_id>",
  "task_output_dir": ".famou/naturebench-runs/<run_id>/workspace/output",
  "task_id": "...",
  "run_id": "...",
  "result": "completed"
}
```

这些字段用于幂等、审计、宿主同步和定位完整任务输出。Idea Agent 只接收轻量目录字段和当前共享快照内可访问的 `summary_path`；不会接收 `source_run_dir`、`task_output_dir` 或历史 Run 的原始 `evidence_refs`。

## 5. 一次 Loop 的生命周期

```text
Idea/Implement/Evaluation
        |
        v
当前 Run ExpBank 累积 attempt 和公开 evaluator 结果
        |
        v
研究状态进入 completed / stopped / failed
        |
        v
调度器生成确定性基础总结
        |
        v
experience_summary Agent 复盘并补充迁移边界
        |
        v
写 Run-local outbox
        |
        +--> 写项目级 Cross-task ExpBank（本地可直接写时）
        |
        +--> fm-job 由宿主后续合并 outbox，再给新 Run 注入快照
```

收尾入口是 `orchestrator.finalize_cross_task_experience(state)`；同步调度器和异步调度器都会在运行结束后调用它。该入口具有幂等 marker：`controller/cross_task_experience.json` 已标记 `written` 时不会重复总结。

### 5.1 状态触发规则

只有以下研究状态会触发总结：

| 状态 | 是否写跨任务总结 | 原因 |
| --- | ---: | --- |
| `completed` | 是 | 任务自然完成，有终局结果 |
| `stopped` | 是 | 任务被墙钟截止或控制面停止，仍应保留已完成轨迹 |
| `failed` | 是 | 记录可诊断的失败和工程边界 |
| `paused` | 否 | 暂停不是任务结束，后续 resume 仍可能产生新证据 |
| `running` | 否 | 任务仍在进行 |

`stopped` 与 `failed` 不代表方法失败。总结中必须分别标记算法失败、实现失败、资源失败和 evaluator 失败，不能把基础设施故障包装成算法结论。

### 5.2 收尾的容错顺序

1. 从当前 Run ExpBank 读取全部 attempt。
2. 解析领域并生成不依赖 LLM 的基础总结：最佳有限分数、成功/失败 attempt、refine 关系和证据引用。
3. 调用 `experience_summary` Agent，补充方法机制、可迁移条件和 negative transfer。
4. 只合并允许的公开字段；`task_id`、`run_id`、领域、正式分数和输出目录仍由调度器掌握。
5. 先写 `controller/cross_task_experience_record.json`，形成宿主可收集的 outbox。
6. 再尝试写共享库，并写 `controller/cross_task_experience.json` marker。

Agent 调用异常或共享库故障会被记录在 marker/outbox 中，不改变主 Loop 的任务结果。没有 attempt 或无法解析领域时，marker 为 `skipped`，不会写入空经验。

## 6. `experience_summary` Agent

默认提示词位于 `famou_scientist/loop/prompts/cli_agents/evolution_summarizer.md`；legacy JSON 模式仍使用 `experience_summarizer.md`。Agent 是“结束后的复盘器”，不再提出或实现新方案，也不运行训练或评测。

### 可读取内容

- 公开 Goal 和任务契约；
- ResearchState 的状态、计数器、排行榜摘要和 shutdown 摘要；
- 当前 Run 的 ExpBank attempt 记录；
- 已记录的公开 evaluator 结果。

### 禁止内容

- hidden test、GT；
- 私有 evaluator 源码或未公开内部信号；
- 凭据、私有 endpoint；
- 任何未出现在请求上下文或公开 ExpBank 中的推断性分数。

默认模式下，Agent 通过 Edit 工具把 `EVOLUTION.md` 写到指定结果文件。Markdown 应覆盖演化路线、关键发现、出乎意料的发现、最佳方法、When to use、When not to use、失败方向以及证据与置信度。调度器把正文封装进系统 outbox；若 Agent 没有输出或输出失败，则使用确定性基础总结继续收尾。legacy JSON 模式仍校验原有 schema。

## 7. 后续任务如何使用经验

Idea 阶段会把当前任务 ExpBank 搜索结果与同领域历史合并：

```python
records = bank.search(
    domain=domain,
    exclude_run_id=current_run_id,
    limit=20,
)
```

检索只返回相同领域的轻量目录，系统内部按 `updated_at` 倒序，默认最多 20 条，并排除当前 Run；`updated_at`、当前 Run 排除所需的 `run_id` 和幂等所需的 `experience_id` 不返回给 Agent。Idea Agent 先根据 `task_summary`、领域、结果和分数筛选，再按当前共享快照内的 `summary_path` 查看具体 Markdown；完整系统记录、输出目录和历史 Run 的原始 `evidence_refs` 不进入 Agent 上下文。

经验不是无条件策略库。跨任务复用时应先检查：任务目标和数据形态是否相近、评价方向是否一致、记录中的适用条件是否满足，以及结论是否只有单次证据。`negative_transfer` 用来明确提示“看起来相似但不应照搬”的方法。

## 8. 本地 Loop 的路径

当 Goal 没有特别配置时，`experience_bank_root(workspace)` 会沿父目录定位 `.famou`，使用项目级：

```text
.famou/cross_task_expbank/
```

也可以在 Goal 的 `infra.shared_experience.cross_task_expbank_root` 中显式配置路径。此配置由 harness 传入时通常指向本 Run 的只读/共享快照；Loop 不需要访问整个项目 `.famou`。

示意配置：

```yaml
infra:
  shared_experience:
    cross_task_expbank_root: /path/to/run/shared_experience_pool/cross_task_expbank
```

## 9. NatureBench/fm-job 的持久化与同步

fm-job 默认只挂载一个 Run 目录，容器内不能可靠地直接更新项目级 `.famou/cross_task_expbank`。因此采用“Run-local outbox + 宿主同步 + 新 Run 快照”的流程：

```text
旧 Run/controller/cross_task_experience_record.json
        |
        v
宿主合并到 .famou/cross_task_expbank/
        |
        v
复制到新 Run/shared_experience_pool/cross_task_expbank/
        |
        v
新 Run 的 Idea Agent 读取该快照
```

脚本：`famou_scientist/loop/examples/naturebench/fmjob/sync_cross_task_expbank.py`。

合并已有 Run：

```bash
python famou_scientist/loop/examples/naturebench/fmjob/sync_cross_task_expbank.py \
  --runs-root .famou/naturebench-runs \
  --bank-root .famou/cross_task_expbank
```

合并后给新 Run 注入快照：

```bash
python famou_scientist/loop/examples/naturebench/fmjob/sync_cross_task_expbank.py \
  --runs-root .famou/naturebench-runs \
  --bank-root .famou/cross_task_expbank \
  --seed-run .famou/naturebench-runs/<run_id>
```

`submit_one_click.sh` 已在准备阶段自动执行：先合并旧 outbox，再创建 Run，最后 seed 快照。快照只包含跨任务公开总结，不把其他 Run 的工作目录暴露给 Agent。

## 10. 一致性、并发与恢复

- `CrossTaskExpBank.upsert_summary()` 以 `task_id--run_id` 幂等更新。
- 全局 `index.jsonl` 更新使用项目级锁 `.cross_task_expbank.lock` 和原子写入，避免并发提交互相覆盖。
- 先写 outbox 再发布共享库，即使容器退出或项目级挂载不可写，宿主仍可在下一次同步时补发。
- `controller/cross_task_experience.json` 是收尾审计 marker，状态包括 `written`、`skipped` 和 `failed`。
- 系统 outbox/index 保留 `source_run_dir` 和 `task_output_dir`，但这两个路径不进入 Agent-facing projection。
- 旧 Run 若只有旧版 marker、没有完整 `cross_task_experience_record.json`，不会被安全地反推成新总结；这会导致当前共享库仍为空，属于预期限制。

## 11. 权限与信息泄漏边界

跨任务库只传播公开研究经验。经验总结 Agent 和 Idea Agent 不应通过路径遍历、共享父目录或私有 evaluator 接口获取额外信息。特别是：

- 不写入 GT、hidden test 具体答案或私有评分实现；
- 不写入凭据、token、私有 endpoint；
- 不将内部 trusted 目录作为 Agent workspace 或上下文；
- evaluator 只通过公开、脱敏的结果进入 ExpBank。

## 12. 当前实现状态与限制

当前实现已覆盖：六领域分区、领域解析、幂等索引、文件锁、收尾 Agent、Run-local outbox、NatureBench 宿主同步和新 Run 快照注入。相关回归测试最近通过 `98 passed`，同步脚本 smoke test、`bash -n`、`py_compile` 和 `git diff --check` 也已通过。

已知限制：

- 项目级库是否能在任务容器内直接写入取决于挂载方式；NatureBench 应使用宿主同步流程。
- 领域无法解析或没有公开 attempt 时不会生成可检索记录。
- 当前索引是 JSONL 快照，检索按领域和更新时间过滤，不提供全文语义检索。
- 旧版 Run 没有 outbox 时不会自动重建完整演化总结。

## 13. 相关代码索引

- `famou_scientist/loop/storage/cross_task_expbank.py`：领域、目录、索引、写入、检索和 NatureBench 映射。
- `famou_scientist/loop/runtime/orchestrator.py`：领域解析、Idea 上下文、收尾和容错。
- `famou_scientist/loop/agents/workers.py`：`experience_summary` Agent 创建、sandbox 和调用。
- `famou_scientist/loop/prompts/cli_agents/experience_summarizer.md`：复盘 Agent 的输入边界和输出 schema。
- `famou_scientist/loop/harness/runtime.py`：把 Run-local 共享库路径注入 Goal。
- `famou_scientist/loop/examples/naturebench/fmjob/sync_cross_task_expbank.py`：outbox 合并和快照 seed。
- `famou_scientist/loop/examples/naturebench/fmjob/submit_one_click.sh`：提交前自动同步流程。
- `famou_scientist/loop/tests/test_expbank.py`、`test_loop.py`：存储、触发和幂等行为测试。
