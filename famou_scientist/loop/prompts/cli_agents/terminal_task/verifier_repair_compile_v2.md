# Terminal Task Verifier Compile Repair v2

${verifier_instruction}

继续同一个 VerifierAgent session，修复上一次生成的 verifier bundle。不要改变任务标准，
不要读取或修改 Solver workspace；只处理公开上下文 `compile_errors` 中的问题，并补齐
官方断言覆盖缺口。

修复时必须重新检查 `verifier_spec.md` 的 coverage matrix：官方 tests、test.sh、checker
和 instruction 中的固定字段值、路径、列名、枚举值及阈值必须精确对齐。不得用“非空”、
“大致相等”或更宽松阈值替代明确断言。若 metadata 与 instruction/官方测试冲突，记录冲突
并按可执行官方测试优先、instruction 次之的规则处理。

对 hidden 检查必须优先构造公开 holdout、边界初值、扰动和多次重采样 proxy；禁止因为无法
访问 hidden 数据就把 value/quality 检查留成 `unknown`/`uncovered`。如果仍没有可辩护的
proxy，继续修改 verifier 设计，不能冻结 bundle。新增或修改检查后，为每个关键字段和阈值
补一个最小 mutation test，并在真实任务公开数据上运行。

在 `$worktree` 中修正 `verifier.py`、`verifier_spec.md`、`tests/test_verifier.py`、
fixtures 和 `.verifier_self_test.json`，然后重新运行自测并自然退出。

任务要求：

$instruction

公开运行上下文：

```json
$request_json
```
