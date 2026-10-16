# Validity Verifier Loop

## 作用

这是 SOTA Search Loop 的可选候选合规校验层，默认关闭。它不替代 benchmark
evaluator，也不产生官方分数；只在 evaluator 返回的候选即将成为 `new_best_solution`
时唤醒 VerifierAgent。

VerifierAgent 读取公开 task README/data description、candidate snapshot 和脱敏的
evaluator view，返回：

```json
{
  "status": "valid|invalid",
  "reasons": ["..."],
  "evidence_refs": ["..."],
  "violations": [
    {
      "rule": "...",
      "evidence": "...",
      "evidence_refs": ["..."]
    }
  ]
}
```

`invalid` 必须有原因和证据；VerifierAgent 不输出 `uncertain`、`recommended_action`
或 evaluator score。VerifierAgent 自身调用失败、输出 schema 错误或证据不存在，记为
`verifier_error`，不冒充 `invalid`。

## 配置

在 goal 中开启：

```yaml
constraints:
  validity_verifier_enabled: true

workers:
  validity_verifier:
    type: agent
    adapter: cli
    runtime: claude
    model: <verifier-model>
```

缺省不配置或设置为 `false` 时，现有 SOTA loop 行为不变。Verifier 使用固定
`session_key=validity_verifier`；后续 new-best 校验会把 `resume=true` 传给 verifier，
并保留同一会话状态。

## 状态流转

1. Controller 先 dry-run 判断 evaluator 结果是否超过当前 leaderboard。
2. 只有可能成为 new best 的候选触发 VerifierAgent。
3. `valid`：提交 leaderboard，并继续现有 Actor/evaluator 流程。
4. `invalid`：不更新 leaderboard；Candidate 标记为 `buggy_solution`，ExpBank 标记
   `failed`，自动以 `validity_failed` 反馈恢复原 ImplementActor 做 refine。
5. IdeaAgent 在下一次生成请求的 `benchmark_runtime.validity_verifier` 中看到最近的
   status、原因和证据指针，用于避免重复提出同类方案。

## 持久化

- 全局 verdict：`artifacts/validity_verdict/<artifact_id>.json`
- Candidate verdict：`candidates/<candidate_id>/evidence/validity_verdict.json`
- ExpBank verdict：`expbank/<attempt_id>/evidence/validity_verdict.json`
- ExpBank 记录：`record.json` 和 `SUMMARY.md` 的 `validity_verdict`
- Loop 状态：`research_state.yaml.research_state.validity_verifier`
- CLI verifier workspace：`validity_verifier_workspace/branches/validity_verifier/`

当前默认 prompt 位于：
`famou_scientist/loop/prompts/benchmark_managed/validity_verifier.md`。
