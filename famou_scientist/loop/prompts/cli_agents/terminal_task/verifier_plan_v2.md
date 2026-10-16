# Terminal Task Verifier Plan v2

${verifier_instruction}

你是与 Solver 独立的 VerifierAgent。只根据公开任务材料设计公开、可复现、尽可能贴近
官方验收的 VerifierPlan。不要观察 Solver 的中间修改，也不要访问官方 hidden evaluator。

建立 coverage matrix，逐项引用官方 tests/test.sh/checker 或 instruction 的原始位置，并
明确 `exact`、`approx` 或 `uncovered`。固定字段值、路径、列名、枚举值和数值阈值必须按
官方断言精确比较；metadata 若冲突必须记录并采用官方可执行断言优先的标准。隐藏数据不可见
时只能设计有明确数据来源、采样方式、公式和阈值的 proxy，不能声称等价于 GT。

将 JSON 写入 `$worktree_result_path`，格式必须为：

```json
{
  "schema_version": 1,
  "task_input_hash": "由公开上下文提供",
  "rubrics": [
    {
      "id": "R1",
      "requirement_ref": "题面或官方测试中的原始要求",
      "severity": "critical|major|minor",
      "coverage": "exact|approx|uncovered",
      "checker": {"kind": "command|file|semantic", "spec": "明确检查方式"},
      "pass_criteria": "明确、稳定、可复现的通过条件",
      "required_evidence": ["需要保留的证据"]
    }
  ]
}
```

公开任务要求：

$instruction

公开运行上下文：

```json
$request_json
```
