# Terminal Task Verifier Diagnose v1

${verifier_instruction}

继续当前 Verifier session。根据冻结的 verifier、当前轮公开候选快照和公开检查证据，
诊断本轮实现。不得修改 Solver workspace、官方 evaluator 或 verifier 的标准。

输出诊断时，先按 coverage matrix 区分：

- `exact`：官方断言/公式/阈值可直接复现；
- `approx`：使用公开数据或扰动数据的明确代理；
- `uncovered`：需要 hidden reference、hidden labels 或私有运行语义，当前无法验证。

每个失败项都给出实际值、期望值、最差实例和证据路径。Proxy 通过不能覆盖
`uncovered` 的 hidden gate；不要把“公开检查通过”写成“官方 GT 通过”。如果发现
instruction、metadata 和官方测试之间的冲突，单独列出冲突及采用的来源，不要静默吞掉。

任务要求：

$instruction

公开运行上下文：

```json
$request_json
```

将 JSON 写入 `$worktree_result_path`，格式必须为：

```json
{
  "status": "passed|repair_required|verifier_error",
  "checks": [
    {
      "rubric_id": "R1",
      "status": "passed|failed|unknown",
      "coverage": "exact|approx|uncovered",
      "summary": "基于证据的结论",
      "evidence_refs": ["Agent 可访问的公开证据路径"]
    }
  ],
  "repair_instructions": ["只针对 failed/unknown 项的具体修正建议"]
}
```
