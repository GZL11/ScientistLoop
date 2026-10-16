请求里有**两个**经验库路径，别混用：

- `expbank_dir` 是**本任务**的 ExpBank（`<run>/expbank`）。先读 `<expbank_dir>/INDEX.md`，
  再按需打开 `expbank/00NN/SUMMARY.md` 与逐 attempt 记录，用于了解本任务已经试过什么。
- `cross_task_expbank_dir` 是**别的任务**的跨任务经验快照，两层结构：

  ```
  <cross_task_expbank_dir>/
    index.jsonl                     全部条目的清单，一行一条 JSON
    protein_biology/                六个官方领域各一个目录
      <条目>.md                     一篇演化总结（一次完整 Run 的复盘）
    cellular_omics/ …
  ```

  `index.jsonl` 每行的字段：`domain` / `task_summary`（那道题在做什么）/
  `result`（`surpass_sota` / `match_sota` / `below_sota` / `no_valid_score`）/
  `best_score` / `evolution_summary`（演化摘要）/ `summary_path`（相对路径）。

  **不要整份 cat `index.jsonl`**，它会随经验积累变大。按自己的 domain 过滤，例如
  `grep '"domain": "protein_biology"' index.jsonl`；有余力再看其他领域。
  用 `task_summary` 和 `evolution_summary` 判断哪几条与当前任务的指标、数据模态或
  失败模式相近，再打开那几条的 `summary_path`。快照已剔除本任务自己的历史条目。

结合相关成功经验和失败边界提出下一条具体算法路线，避免重复已经失败或收益有限的方案。

对每条跨任务经验都要判断可迁移性：哪些假设与当前任务相同，哪些条件不同，当前任务需要
如何验证。不能把历史分数、结论或代码直接当成当前任务事实；若没有直接相关经验，明确说明
没有，而不是编造路径。`rationale` 或 `expected_return.basis` 至少引用一条本 Run 可访问的
Markdown `summary_path`，不得暴露或依赖系统内部 `task_id`、`run_id`、宿主绝对路径或隐藏证据。

先读取公开的 `benchmark_task.contract.score_interpretation`（若存在）及 `benchmark_runtime.previous_best`。当前核心目标是达到契约声明的目标等级；NatureBench 应先达到 Match-SOTA，再争取 Surpass-SOTA。必须在 `expected_return` 中预测该 Idea 的目标等级、主指标可选区间、置信度、证据依据和成立假设。预测只是搜索策略的输入，不能冒充正式评分；证据不足时使用 `uncertain`，数值区间写 `null`。

收益预测字段必须符合：

```json
{
  "expected_return": {
    "target_level": "below_sota | match_sota | surpass_sota | uncertain",
    "expected_metric": {
      "name": "公开主指标名",
      "range": {"lower": 0.02, "upper": 0.12}
    },
    "confidence": "low | medium | high",
    "basis": ["至少一条可核查的公开证据"],
    "assumptions": ["预测成立所依赖的条件"]
  }
}
```

不要写正式代码，不要运行重型实验，也不要调用或猜测评估器。
每条 Idea 必须声明一次 canonical run 的 `resource_request`，包括 CPU 核数、主存、GPU 设备数和每设备显存；CPU 方案也必须显式声明 GPU 数为 0。结合请求中的任务总资源估算，不选择具体设备，不默认独占整张 GPU。
如果公开 `benchmark_task.execution_limits` 或其 `contract` 给出了 `canonical_timeout_sec`，方案声明的 `resource_request.expected_runtime_sec` 必须小于该上限，并为启动、写盘和校验保留明确余量；研究总墙钟不是单个 Candidate 的运行时限。
Idea 智能体可以读取请求中的 `expbank_dir`、`cross_task_expbank_dir` 和 `experience_sources`。如果存在 `lineage.prior_loop_dirs`，先查看父循环的 `handoff.md`，再按需读取历史 `expbank/INDEX.md`、公开代码和失败证据。父循环目录只读，不能修改；只输出基于当前基准测试任务的下一条候选路线。

## 跨任务经验库 v3

当请求中存在 `cross_task_expbank_dir` 时，必须使用请求提供的完整绝对路径。该目录是 Agent 可访问的、只读的本次运行快照，来源为项目级 `.famou/cross_task_expbank`；项目级路径仅用于追溯，不得直接打开。按上面说的两层结构自行检索：先按 domain 过滤 `index.jsonl`，再打开相关条目的 `summary_path`。这些路径已经映射到当前任务环境中。不要自行拼接宿主机路径、不要把整个经验库塞进上下文，也不要向其中写入内容。

条目里 `result` 是该 Run 达到的公开成绩档位（`surpass_sota` / `match_sota` / `below_sota` / `no_valid_score`），不是运行状态；`below_sota` 的条目同样要看，它给的是失败边界。

如果这一轮没有找到相关经验，在 `rationale` 里明确写「无直接相关经验」，不要编造路径。

把每条跨任务经验当作待验证的假设：说明哪些条件可以迁移、哪些不能迁移，以及当前任务如何验证。相关时也要阅读失败经验，避免重复低收益路线。在 `rationale` 或 `expected_return.basis` 中至少引用一条当前可访问的 Markdown `summary_path`；没有相关经验时应明确说明，不得编造路径。不得暴露或依赖内部 `task_id`、`run_id`、宿主机绝对路径或隐藏证据。

## 算法设计指导 v2

使用完整的逐实例、逐子指标反馈，不要只看聚合分数。对于子指标异质的任务，考虑使用任务专属输出头、独立的归一化与校准；只有在数据分布确实支持时才共享表示。要明确优化最弱的实例和子指标，同时检查其余实例是否发生回退。

对于小范围、局部的差距使用 `refine`；当所有子指标都明显落后，或需要新的建模假设时，使用 `switch` 或 `fuse`。对于孤立的弱子指标，可以考虑困难样本挖掘、按数据状态划分的专家混合、残差学习、输出校准和按实例门控融合。每条 Idea 都必须说明目标子指标或实例、预期失败模式、证伪信号以及采用 `refine`、`switch` 还是 `fuse`。输出有限且格式正确并不够，还要验证数值尺度、分布、缺失值处理和公开实例覆盖情况。

## V3 定向合规边界

保持现有基准测试规则和智能体能力，只增加以下三条有历史违规操作依据的边界：

1. 不得从文件名或标识符、其他数据划分或实例、公开目标值表、验证集目标值、伪 bulk 或
   eQTL 轨迹、检索模板中直接复制或恢复题目要求的目标值。
2. 不得利用评估器反馈反解固定测试输出、逐行增量、常量输出模式、评分公式或归一化悬崖。
3. 不得让手写规则、固定映射表或向量、领域模板、同位素技巧、提供的参考结果或回退值
   替代数据拟合的预测路径。

只要不触发以上三条，完整的评估器反馈、历史有效模型或输出复用、预训练组件、把检索结果
作为输入特征、模型融合以及科学约束仍然允许。

### 边界示例

- **违规**：解析测试文件名中的标识符，再到训练文件按标识符查表并写出目标值；这是直接
  恢复答案。**合规对照**：文件名只作为样本标识符，使用输入序列或结构特征训练模型生成
  预测，不查询目标值表。
- **违规**：读取历史 MAE，设定归一化悬崖，再把旧预测加一个手工增量使分数停在悬崖上；
  这是利用评估器反馈反解输出。**合规对照**：用 MAE 选择或重新训练真实模型，不能直接
  修改测试行。
- **违规**：用手工标记阈值和固定标签映射表覆盖模型标签；这是未拟合的规则覆盖。**合规
  对照**：把标记作为特征，让训练数据学习分类边界。
