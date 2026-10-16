# Loop 测试目录

该目录存放 Loop 自主科研运行时的测试代码。

```text
tests/
├── test_loop.py             # 调度、状态、评测和 CLI
├── test_loop_execution.py   # 分支工作区、进程隔离和外部适配器
├── test_loop_web_api.py     # Web 只读 API
└── fixtures/                # 仅供测试使用的确定性夹具
    ├── agents/
    ├── evaluators/
    ├── experiments/
    ├── goals/
    └── llm/
```

`fixtures/` 中的代码和 goal 不是真实 benchmark 示例，不随 wheel 分发。真实
benchmark 示例放在相邻的 `examples/` 目录。
