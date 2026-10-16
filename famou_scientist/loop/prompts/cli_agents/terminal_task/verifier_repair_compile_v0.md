# Terminal Task Verifier Compile Repair v1

继续同一个 VerifierAgent session，修复上一次生成的 verifier bundle。不要重新设计任务
标准，也不要读取 Solver 的实现；只处理公开上下文 `compile_errors` 中列出的静态检查、
接口、文件完整性或自测记录问题。

任务要求：

$instruction

在同一个 `$worktree` 中修正 `verifier.py`、`verifier_spec.md`、
`tests/test_verifier.py`、fixtures 和 `.verifier_self_test.json`。修正后重新运行自测并更新
自测记录，然后自然退出。不得访问 hidden evaluator、私有 GT 或 Controller 私有目录。

公开运行上下文：

```json
$request_json
```
