# NatureBench Agent 输入、挂载与 Prompt 说明

本文说明三件容易混淆的内容：

1. NatureBench task package 给 coding-agent 提供哪些任务文件；
2. 原始 NatureBench Codex/Claude/Gemini 使用哪套 instruction；
3. 当前 Famou Loop 的 Idea Agent、Implement Agent 实际收到什么上下文，以及运行时看到哪些目录。

本文以源码和实际 run 产物为准，特别区分“prompt 中要求读取的文件”和“运行时确实挂载的文件”。

## 1. 两套运行路径

当前存在两套不同的 agent workflow：

| 路径 | 主要入口 | Idea/实现关系 |
|---|---|---|
| 原始 NatureBench | `NatureBench/solve.py` + `NatureBench/agent/{codex,claude,gemini}.py` | 一个 CLI agent 自己完成理解、实现、执行和评估循环 |
| 当前 Famou Loop | `famou_scientist/loop` 的 `benchmark_managed` workflow | Idea Agent 提出 Idea，Implement Agent 实现，Controller 负责 canonical run 和 evaluator |

不能把原始 NatureBench 的 instruction 直接当成当前 Famou Loop 的 system prompt。

## 2. NatureBench Task Package

原始 task package 的结构是：

```text
tasks/<case_id>/
├── problem/
│   ├── README.md
│   ├── data_description.md
│   └── data/
├── evaluation/
│   ├── evaluator.py
│   └── ground truth / evaluator assets
├── environment/
│   └── Dockerfile.v3
├── licenses/
└── metadata.json
```

来源：[NatureBench task-packages.md](/path/to/workspace/opensource/NatureBench/docs/task-packages.md)

### 2.1 Agent 可见的公开任务内容

在标准 end-to-end code submission 模式中，agent 主要使用：

| 容器路径 | 内容 | 用途 |
|---|---|---|
| `/task/problem/README.md` | 任务目标、指标、输出格式和入口协议 | 理解任务和提交格式 |
| `/task/problem/data_description.md` | 数据结构、字段、文件格式和数据语义 | 理解输入数据 |
| `/task/problem/data/` | 可见训练、验证和测试输入 | 训练和推理 |
| `/workspace/` | agent 自己的代码和输出目录 | 写 `run.py`、模型和提交产物 |

`evaluation/`、hidden ground truth 和 evaluator 私有数据不应暴露给 agent。

大数据任务可能先以 `problem/data_archives/*.tar.gz` 提供，下载器会解压成
`problem/data/`，agent 最终使用的仍是 `/task/problem/data/`。

### 2.2 `metadata.json`

task package 中的 `metadata.json` 包含 task 名称、领域、资源需求以及每个 instance 的论文 SOTA/baseline 参考记录。标准 solve 容器只挂载 `problem/`，因此不能把宿主上的完整 `metadata.json` 自动等同于 agent 可见输入。

官方 evaluator 使用论文 SOTA 数值计算 `aggregate_improvement`；普通 baseline 和 SOTA 参考值不是 agent 最终提交代码。

## 3. `initial_idea.md` 的位置和含义

### 3.1 原始 agent 代码中的声明

`agent/codex.py`、`agent/claude.py` 和 `agent/gemini.py` 中都保留了一套
`*_REFERENCE_PROMPT`，其中写着：

```text
Read /task/initial_idea.md
This describes a high-quality SOTA approach. Use this as a starting point or inspiration.
```

这段文字表达的设计意图是：`initial_idea.md` 是高质量、SOTA-oriented 的方法参考，
不是普通弱 baseline，也不是保证可直接运行的论文官方实现。

### 3.2 官方标准运行的实际边界

官方发布版 `solve.py` 的标准 Docker mount 明确包含：

```text
<task>/problem -> /task/problem:ro
<run workspace> -> /workspace
```

只有 `reproduce` 模式额外挂载：

```text
<task>/*.pdf -> /task/paper.pdf:ro
<task>/preprocessed/text.md -> /task/paper.md:ro
```

而且官方发布版命令行的 `--mode` 只有 `base` 和 `reproduce`，没有
`reference` 选项。`solve.py` 也没有任何 `initial_idea.md` 的 mount；当前本地
NatureBench task package 目录中同样没有该文件。因此应区分：

- agent 源码中**保留了**要求读取 `/task/initial_idea.md` 的 reference prompt；
- 这不是官方标准 `base`/`reproduce` 运行链路的输入；
- 除非某个外部 fork 或自定义 launcher 额外挂载它，否则正常官方 run 中该路径不存在；
- 不能仅凭这段残留 prompt 证明某次 run 实际读取到了该文件。

## 4. 原始 NatureBench Codex/Claude/Gemini instruction

这些 instruction 不是独立 Markdown 文件，而是 Python 文件中的 prompt 常量。

| agent | 源文件 | 主要 prompt 常量 |
|---|---|---|
| Codex | [`agent/codex.py`](/path/to/workspace/opensource/NatureBench/agent/codex.py) | `CODEX_BASE_PROMPT`、`CODEX_REFERENCE_PROMPT`、`CODEX_REPRODUCE_PROMPT` |
| Claude | [`agent/claude.py`](/path/to/workspace/opensource/NatureBench/agent/claude.py) | `CLAUDE_BASE_PROMPT`、`CLAUDE_REFERENCE_PROMPT`、`CLAUDE_REPRODUCE_PROMPT` |
| Gemini | [`agent/gemini.py`](/path/to/workspace/opensource/NatureBench/agent/gemini.py) | `GEMINI_BASE_PROMPT`、`GEMINI_REFERENCE_PROMPT`、`GEMINI_REPRODUCE_PROMPT` |

模式差异：

- `base`：官方标准模式，读取公开题面和数据，自己设计方法；
- `reference`：agent 源码中存在的旧/未接入 prompt 变体，不是官方 `solve.py` 的可选模式；
- `reproduce`：官方可选模式，额外挂载论文 PDF/文本，要求尽量复现论文方法。

通用单次 LLM agent 还使用 [`agent/base.py`](/path/to/workspace/opensource/NatureBench/agent/base.py)。它会从 task 字典读取：

```text
task_description
data_description
initial_idea
```

只有 `mode="reference"` 时才把 `initial_idea` 拼进 system prompt。

## 5. 当前 Famou Loop 的目标视图

当前 NatureBench Facility 的 `TaskView` 只返回公开 problem 路径、入口协议和评分解释：

[NatureBenchBenchmarkFacility.task_view](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/integrations/naturebench/benchmark.py:516)

公开评分契约包含：

```text
aggregate_improvement < 0       -> below_sota
0 <= aggregate_improvement <= .1 -> match_sota
aggregate_improvement > .1       -> surpass_sota
```

当前 Famou 的公开目标是先达到 Match-SOTA，再争取 Surpass-SOTA；预测值不能替代正式 evaluator 结果。

## 6. 当前 Idea Agent 的输入和 system prompt

当前 `benchmark_managed` Idea Agent 使用：

[benchmark_managed/idea_agent.md](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/prompts/benchmark_managed/idea_agent.md)

它的主要要求是：

- 先读 `expbank_dir/INDEX.md`，再按需读历史 Markdown、代码和证据；
- 读取公开 `benchmark_task.contract.score_interpretation`；
- 结合 `benchmark_runtime.previous_best`、ExpBank 和公开分项证据提出下一条 Idea；
- 只能基于公开信息，不能读取 hidden evaluator 或 hidden labels；
- 输出结构化 Idea，包括 `title`、`hypothesis`、`method`、`rationale`、`implementation_plan`、`expected_return`、`resource_request` 和 `risks`；
- 每个回合只提交一条 Idea。

Idea Agent 的上下文主要包含：

```json
{
  "goal": {...},
  "experience": [...],
  "expbank_dir": ".../expbank",
  "lineage": {...}
}
```

经过 `_implementation_goal_view` 筛选后，公开目标视图包含：

```text
goal
objective_brief
baselines
benchmarks
constraints
benchmark_task
infra.resources
lineage
```

当前 prompt 和实际请求中没有显式的 `initial_idea` 字段，也没有明确要求 Idea Agent 读取 `/task/initial_idea.md`。

## 7. 当前 Implement Agent 的输入和 system prompt

当前 `benchmark_managed` Implement Agent 使用：

[benchmark_managed/implement_agent.md](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/prompts/benchmark_managed/implement_agent.md)

它的主要要求是：

- 先读 ExpBank 和本回合的 feedback mailbox；
- 根据当前 Idea 实现完整方法，不得只根据 Idea 标题猜测；
- 遵守公开 benchmark contract 和资源声明；
- 只能使用公开数据；
- 在提交前做轻量 smoke test，检查所有官方 instance 的输出格式和非空性；
- 通过 `submit_candidate` 提交，不直接手工写完成状态；
- Controller 异步运行 canonical experiment 和 evaluator；
- evaluator 返回后恢复同一 Implement Agent Session，继续 refine、repair 或提交下一版。

Implement Agent 的请求包含：

```text
公开目标视图 + 当前 Idea + ExpBank 路径 + feedback mailbox + search opportunity
```

其中当前 Idea 是 Idea Agent 的直接输出，因此当前实现 lineage 是：

```text
Idea Agent Idea -> Implement Agent branch -> Candidate -> canonical run -> evaluator
```

## 8. 当前 Famou Candidate 运行时的目录视图

实际执行候选代码的 Docker 入口在：

[run_task.py](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/examples/naturebench/run_task.py:55)

当前 Docker mount 是：

```text
<task_dir>/problem -> /task/problem:ro
<candidate workspace> -> /workspace
<candidate output dir> -> /output
工作目录：/workspace
```

环境变量是：

```text
DATA_DIR=/task/problem/data
OUTPUT_DIR=/output
```

因此候选 Implement Agent 运行时能看到：

```text
/task/problem/README.md
/task/problem/data_description.md
/task/problem/data/
/workspace/run.py 以及候选源码
/output/                          # 写入提交产物
```

不能从当前 `run_task.py` 看到 `/task/initial_idea.md` 的显式挂载。

## 9. Famou Agent Workspace 目录

Idea/Implement command agent 还有一层由 Famou Controller 管理的分支目录：

```text
<loop workspace>/
└── branches/<branch_id>/
    ├── worktree/   # agent 写代码或方法文件
    ├── public/     # Controller 筛选后的公开上下文和 instruction
    ├── outputs/    # agent 返回的结构化结果/候选提交
    └── logs/       # prompt、stdout、stderr、session metadata
```

`public/context.json` 只承载筛选后的公开上下文，不是完整 goal/control/evaluator 状态。

实际 run 示例：

[Implement instructions](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/.famou/naturebench-runs/20260811-search-v2-s42256-024-00815-9/branches/actor_branch_1786428683313_dd059c8b/public/IMPLEMENT_INSTRUCTIONS.md)

## 10. `initial_idea.md` 的当前结论

当前应使用以下口径：

1. 官方 task package 说明只把 `problem/` 定义为 agent-visible 内容，没有 `initial_idea.md`；
2. 官方标准 `solve.py` 只支持 `base` 和 `reproduce`，两者都没有挂载 `initial_idea.md`；
3. agent 源码中的 `*_REFERENCE_PROMPT` 和 `BaseAgent` 的 `initial_idea` 字段属于保留的 reference/单次 Agent 路径，不能当作标准官方输入；
4. 当前 Famou `benchmark_managed` Idea/Implement prompt 也没有这条要求；
5. 当前实际 task mount 只明确包含 `/task/problem`、`/workspace` 和 `/output`；
6. 因此当前 Famou 实验的第一个 Idea 不能审计性地证明是基于 `initial_idea.md` 产生的；
7. 当前最终方案通常是 Idea Agent + ExpBank + evaluator feedback 演化的结果，不等于 `initial_idea.md` 原样实现。

如果要让这条链路可审计，建议后续把 `initial_idea.md` 作为公开输入显式传入 Idea Agent，并在首个 Idea 记录中保存：

```text
initial_idea_path
initial_idea_sha256
initial_idea_used: true/false
```

这样才能逐 task 判断最终方案究竟是复现、改写还是另起路线。

## 11. 关键源码索引

- NatureBench task package 说明：[docs/task-packages.md](/path/to/workspace/opensource/NatureBench/docs/task-packages.md)
- 原始 solve mount：[solve.py](/path/to/workspace/opensource/NatureBench/solve.py:1578)
- 原始 Codex prompt：[agent/codex.py](/path/to/workspace/opensource/NatureBench/agent/codex.py)
- 原始 Claude prompt：[agent/claude.py](/path/to/workspace/opensource/NatureBench/agent/claude.py)
- 原始 Gemini prompt：[agent/gemini.py](/path/to/workspace/opensource/NatureBench/agent/gemini.py)
- Famou NatureBench Facility：[loop/integrations/naturebench/benchmark.py](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/integrations/naturebench/benchmark.py)
- Famou Idea prompt：[loop/prompts/benchmark_managed/idea_agent.md](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/prompts/benchmark_managed/idea_agent.md)
- Famou Implement prompt：[loop/prompts/benchmark_managed/implement_agent.md](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/prompts/benchmark_managed/implement_agent.md)
- Famou candidate mount：[loop/examples/naturebench/run_task.py](/path/to/workspace/workspace/famou-scientist/baidu/acg-fm/famou-scientist/famou_scientist/loop/examples/naturebench/run_task.py)
