先读取请求中 `expbank_dir` 指向目录的 `INDEX.md`，并按需查看当前 best、相似历史方法的代码和失败证据。如果请求包含 `feedback_mailbox`，还必须读取其中已有的 evaluator 脱敏反馈，判断本回合应修复、改进、做变体还是消融。然后在当前 worktree 实现请求中指定的完整 Idea；不得只根据标题猜测。严格遵守请求中的 `implementation_contract` 和 benchmark 公开题面；只有契约明确指定入口、环境变量或产物位置时才使用这些约定，不得自行假设必须是 Python 或 `run.py`。

如果请求包含 `search_opportunity`，这不是 Debug 回合，而是 Improve 选择：同时比较
`current_idea`、最新 evaluator 反馈和 `offered_idea`。可以继续 `refine` 当前方案、切换为
`switch` 新方案，或用 `fuse` 融合二者；应选择在剩余预算内更可能达到公开目标等级的路线，
并按通用提交协议显式给出 action 和理由。选择 `refine` 不会淘汰新 Idea，它会被重放到
IdeaSpark 队尾。不得为了消费 Idea 而做没有机制依据的表面融合。

如果请求包含 `prior_loop_dirs`，先阅读其中的 `handoff.md`，再按需查看旧
Loop 的 ExpBank、公开代码和失败证据。旧 Loop 与 `experience_sources` 均为只读
输入，当前实现只能写入当前 branch workspace，不能覆盖历史产物。

提交前只能使用公开数据完成轻量 Smoke Test，至少验证题面规定的执行接口、输出目录和基本格式。必须根据公开 README 或 data description 列出所有官方 instance，并逐一确认每个 instance 都会生成非空、格式正确的输出；如果公开测试数据位于 archive 中，必须确认解压后的路径确实被主推理流程使用。不要在 Agent 内运行全部 case、参数搜索或重复确定性实验。不得接触 evaluator 或隐藏标签。完成后必须调用通用 instruction 中给出的 `submit_candidate` 命令；若命令拒绝提交，必须根据错误在当前回合修复并重试。正式运行和评测由 Loop Controller 异步执行。提交后当前进程会 park，结果返回时系统会恢复同一 Session；如果 mailbox 中是工程错误，应修复原方案，不得把该错误解释为 Idea 无效，也不得覆盖 ExpBank 中已有的最佳有效版本。

`resource_request.host_memory_gib` 是当前 Candidate 的主存硬边界。实现时必须使用
分块、流式或稀疏算法控制峰值内存，不能构造与大样本笛卡尔积同阶的 Python 对象
列表。若 mailbox 返回 `memory_limit_exceeded`，先结合 `memory_limit_bytes`、stdout
和 stderr 修复当前版本的内存复杂度，再提交新 revision；该错误属于工程失败，
不代表 Idea 的科研结论无效。

若 mailbox 返回 `error_code=canonical_timeout` 或
`canonical_runtime_budget_exceeded`，必须把 `timeout_sec` 当作单次 Candidate 的硬
上限，结合 stdout 最后完成的位置缩短算法内部预算、限制单 case 时间并给写盘和校验
留出余量，然后提交修复版本。不能只提高 `expected_runtime_sec`，也不能把研究总墙钟
当作 canonical 上限。

必须继承 Idea 的 `resource_request`。如果实现后的公开 Smoke Test 证明估算不准确，
在 `method_manifest.json` 中提交修正后的请求；只声明设备数量和每设备显存，不选择
具体 GPU。资源暂时不足会由 Infra hold，不要在 Agent 内轮询 GPU。

## Algorithm implementation guidance v2

Implement the complete Idea, including its target submetric/instance, expected failure mode, validation signal, and refine/switch/fuse choice. Preserve the Idea's scope; do not replace it with an unrelated heuristic merely because the smoke test is convenient.

When the Idea targets heterogeneous submetrics, keep normalization, output heads, loss weighting, and calibration task-specific where appropriate. Guard against scale explosions: inspect prediction range, mean/std, missing-value behavior, clipping or inverse transforms, and the public instance coverage before submitting. Finite output and valid JSON alone do not prove a sound prediction.

For weak-instance or weak-submetric strategies, implement bounded hard-example weighting and explicit regression checks on non-target instances. For mixture-of-experts or fusion, make the gating/fusion rule deterministic, memory-bounded, and reproducible. For residual learning, verify the baseline and residual are in the same scale before combining them. Keep peak memory and runtime within `resource_request`; use streaming, chunks, or sparse structures for large data.

