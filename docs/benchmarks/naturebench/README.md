# NatureBench 文档索引

NatureBench 的专项文档统一保存在本目录。通用 Loop 架构、插件接口和科研 Benchmark
调研仍保留在 `docs/` 根目录，因为它们不只服务于 NatureBench。

| 文档 | 内容 |
|---|---|
| [Agent 输入、挂载与 Prompt](AGENT_INPUTS_AND_PROMPTS_CN.md) | 原始 NatureBench task 输入和 Codex/Claude/Gemini instruction、当前 Famou Idea/Implement Agent 上下文、目录挂载以及 `initial_idea.md` 边界 |
| [接入与运行指南](INTEGRATION_AND_RUN_CN.md) | 官方规则、资源档位、权限隔离、Agent/Benchmark/Evaluator 适配、一键运行和 Leaderboard 导出 |

相关实现位于：

- `famou_scientist/loop/integrations/naturebench/`：Benchmark、Evaluator、轨迹和 Judge 插件；
- `famou_scientist/loop/examples/naturebench/`：配置、导出工具和 fm-job 启动脚本。

运行产物不入库。Run 证据、官方提交目录、分数与花费记录跑起来后落在本机 `.famou/` 下；
花费由 Loop Infra 原生写入 `artifacts/agent_usage.jsonl`、
`artifacts/agent_trajectory.jsonl` 和 `controller/agent_usage_summary.json`，
通用接口见 `docs/operations/LOOP_AGENT_OBSERVABILITY_CN.md`。实验报告与消融结论同样
属于运行产物，不在本仓库维护。
