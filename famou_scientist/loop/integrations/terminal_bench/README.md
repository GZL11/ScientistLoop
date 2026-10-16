# Terminal-Bench-Science Harbor 接入

`HarborBenchmarkFacility` 和 `HarborEvaluationFacility` 复用 Harbor trial 的
canonical 路径；Famou 只使用 `trial/famou/` 保存 graph/session/surrogate 状态。
不要在 core 中猜测 Harbor 私有目录名称，启动器应把 `--harbor-artifact-root`
传入本次 trial 的 artifact 根目录。

具体 Harbor/FMJob 启动器通过 `--harbor-backend module:Class` 注入一个实现
`HarborTaskBackend` 的对象：

- `export_artifacts`：从 Solver FMJob 容器 copy-out `task.toml` 声明的 artifacts；
  可复用 `copy_fmjob_artifacts` 将 `fmjob-agent/round_N` 转成 Harbor payload；
- `preflight` / `validate_artifact`：公开、无 GT 的检查；
- `public_evaluate`：SurrogateVerify 可使用的公开评测；
- `final_audit`：只在冻结 workspace 后调用 Harbor official verifier 一次。

候选轮次的 verifier 通过 `--candidate-verifier-mode` 切换：

- `proxy`（默认）：使用 VerifierAgent 生成并冻结的 proxy verifier；行为与旧版本一致。
- `gt_primary`：跳过 VerifierAgent，候选轮次直接调用官方 TBS GT verifier，并用其结果驱动
  SolverAgent refine；最终仍会单独执行一次 `FinalAudit`。
- `dual_shadow`：同一候选同时运行 proxy 和 GT，但只有 proxy 结果驱动 refine；GT 结果只作为
  对照记录，适合测量两者差异。

GT 候选校验需要额外提供官方 verifier image：

```text
--candidate-verifier-mode gt_primary \\
--gt-verifier-image <task-specific-tbs-verifier-image>
```

`--verifier-image` 仍表示 VerifierAgent 编译 proxy verifier 所用的 Agent image。若未提供
`--gt-verifier-image`，FMJob backend 为兼容旧调用会回退到 `--verifier-image`，但正式 GT
实验应始终显式指定 task-specific verifier image 和固定 digest。

GT 结果写入 Controller 私有的 `controller/candidate_gt_round_N/`，Agent 只能看到
`.famou/surrogate/round_N.json` 中的脱敏状态、reward 和错误摘要；hidden test、GT 路径和
完整日志不会进入 Agent view。

Solver/VerifierAgent 的 CLI 配置如果包含 `--solver-image` 或 `--verifier-image`，
会分别使用 `FmJobSandbox`。该 sandbox 通过 FMJob `--subpath` 访问 CFS，不把
Controller 或 Harbor 源码目录作为 Agent 输入。
