# Loop Prompts

本目录集中存放 Loop 中所有 Agent 和单次 LLM 节点的 instruction/prompt。

目录约定：

- `cli_agents/`：Claude Code、Codex、OpenCode 等工具型 Agent 的通用完整模板。
- `benchmark_managed/`：外部 benchmark 托管工作流使用的 Idea、Rank Judge 和 Implement instruction。
- `research/`：通用算法创新工作流中的 Idea、Gate、Rank Judge、Implement、Analyze 等节点 Prompt。

Python 代码只负责准备结构化上下文、填充模板变量和执行节点，不应内嵌角色职责、输出格式或行为规则。新增 Agent 节点时，必须先在本目录增加对应 Markdown 文件。
