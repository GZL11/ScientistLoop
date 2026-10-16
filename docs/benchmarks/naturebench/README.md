# NatureBench 文档索引

NatureBench 的专项文档统一保存在本目录。通用 Loop 架构、插件接口和科研 Benchmark
调研仍保留在 `docs/` 根目录，因为它们不只服务于 NatureBench。

| 文档 | 内容 |
|---|---|
| [Agent 输入、挂载与 Prompt](AGENT_INPUTS_AND_PROMPTS_CN.md) | 原始 NatureBench task 输入和 Codex/Claude/Gemini instruction、当前 Famou Idea/Implement Agent 上下文、目录挂载以及 `initial_idea.md` 边界 |
| [接入与运行指南](INTEGRATION_AND_RUN_CN.md) | 官方规则、资源档位、权限隔离、Agent/Benchmark/Evaluator 适配、一键运行和 Leaderboard 导出 |
| [Search-v2 搜索策略与结果](SEARCH_POLICY_DESIGN_AND_RESULTS_CN.md) | ImplementAgent 在 refine、新 Idea 和 fusion 之间的搜索策略设计、证据格式、逐 case 决策序列和 Search-v2 结果 |
| [冲刺期 Idea 排序的可预测性](IDEA_RANKING_PREDICTABILITY_CN.md) | Judge 不执行就判优劣的实测（一致率 54.4%、排序前后第 1 名对比）、候选梯度诊断、与 ForeAgent / Meta AIRA 的对照和差距分析 |

相关实现位于：

- `famou_scientist/loop/integrations/naturebench/`：Benchmark、Evaluator、轨迹和 Judge 插件；
- `famou_scientist/loop/examples/naturebench/`：配置、导出工具和 fm-job 启动脚本。

运行产物（Run 证据、官方提交目录、分数与花费记录）不入库，跑起来后落在本机
`.famou/` 下。Run 的花费由 Loop Infra 原生写入
`artifacts/agent_usage.jsonl`、`artifacts/agent_trajectory.jsonl` 和
`controller/agent_usage_summary.json`；通用接口见
`docs/operations/LOOP_AGENT_OBSERVABILITY_CN.md`。

当前历史表使用 2026-08-11 确认的 GLM-5.2 单价：输入 `$1.40/M`、Cache Creation
`$1.40/M`、Cache Read `$0.26/M`、输出 `$4.40/M`。`reported_cost_usd` 是 CLI 原始
美元等价值；`calculated_*_cost_usd` 是按上述价格和四类 Token 独立重算的值，二者不能
混用。Validity Judge 的 Token/费用尚未包含在这些表中。
