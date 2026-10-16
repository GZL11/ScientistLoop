`expbank_dir` 是项目级 `.famou/cross_task_expbank` 为本 Run 准备的只读快照。先读取
`<expbank_dir>/INDEX.md`，根据当前任务的 domain、task_summary、目标指标和数据模态筛选
相关记录，再按需打开记录中的 Markdown `summary_path`；不要遍历整个目录，也不要写回该目录。
结合相关成功经验和失败边界提出下一条具体算法路线，避免重复已经失败或收益有限的方案。

对每条跨任务经验都要判断可迁移性：哪些假设与当前任务相同，哪些条件不同，当前任务需要
如何验证。不能把历史分数、结论或代码直接当成当前任务事实；若没有直接相关经验，明确说明
没有，而不是编造路径。`rationale` 或 `expected_return.basis` 至少引用一条本 Run 可访问的
Markdown `summary_path`，不得暴露或依赖系统内部 `task_id`、`run_id`、宿主绝对路径或隐藏证据。

先读取公开 `benchmark_task.contract.score_interpretation`（若存在）及`benchmark_runtime.previous_best`。当前核心目标是达到契约声明的目标等级；NatureBench应先达到 Match-SOTA，再争取 Surpass-SOTA。必须在 `expected_return` 中预测该 Idea 的目标等级、主指标可选区间、置信度、证据依据和成立假设。预测只是 Search Policy 的输入，不能冒充正式评分；证据不足时使用 `uncertain`，数值区间写 `null`。

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

不要写正式代码，不要运行重型实验，也不要调用或猜测 evaluator。
每条 Idea 必须声明一次 canonical run 的 `resource_request`，包括 CPU 核数、主存、GPU 设备数和每设备显存；CPU 方案也必须显式声明 GPU 数为 0。结合请求中的任务总资源估算，不选择具体设备，不默认独占整张 GPU。
如果公开 `benchmark_task.execution_limits` 或其 `contract` 给出了 `canonical_timeout_sec`，方案声明的 `resource_request.expected_runtime_sec` 必须小于该上限，并为启动、写盘和校验保留明确余量；研究总墙钟不是单个 Candidate 的运行时限。
Idea Agent 可以读取请求中的 `expbank_dir` 和 `experience_sources`。如果存在 `lineage.prior_loop_dirs`，先查看父 Loop 的 `handoff.md`，再按需读取历史 `expbank/INDEX.md`、公开代码和失败证据。父 Loop 目录只读，不能修改；只输出基于当前 benchmark 任务的下一条候选路线。
