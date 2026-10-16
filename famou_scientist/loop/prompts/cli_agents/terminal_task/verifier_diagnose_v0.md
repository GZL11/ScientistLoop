# Terminal Task Verifier Diagnose v1

继续当前 Verifier session。根据已经冻结的 VerifierPlan、当前轮只读 workspace 快照和公开检查证据，
诊断本轮实现。不得修改 rubric、Solver workspace 或官方 evaluator。

任务要求：

$instruction

将 JSON 写入 `$worktree_result_path`，格式必须为：

```json
{
  "status": "passed|repair_required|verifier_error",
  "checks": [
    {
      "rubric_id": "R1",
      "status": "passed|failed|unknown",
      "summary": "基于证据的结论",
      "evidence_refs": ["Agent 可访问的公开证据路径"]
    }
  ],
  "repair_instructions": ["只针对 failed/unknown 项的具体修正建议"]
}
```

最多使用 $max_turns 个自主回合。

公开运行上下文：

```json
$request_json
```
