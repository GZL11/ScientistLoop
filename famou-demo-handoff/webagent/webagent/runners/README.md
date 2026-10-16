# runners

Famou-Bench 评测运行框架。

## 目录结构

```
runners/
  backends/            # Runner 实现
    base.py            # 抽象基类（AgentRunner / AgentSession / RunnerConfig）
    factory.py         # runner_from_config() 工厂函数
    cc_cli.py          # CCCLIRunner / CCCLINativeRunner — Claude Code via CLI 子进程
    opencode_run.py    # OpenCodeRunner / OpenCodeNativeRunner — OpenCode via `opencode run --format json`
  cli/                 # 所有评测入口脚本
    run_bench.py       # 统一评测入口（--benchmark b2 澄清 / b3 端到端）
    run_b2.py          # B2 薄封装（等价 run_bench --benchmark b2）
    run_b3.py          # B3 薄封装（等价 run_bench --benchmark b3）
    run_b3_stability.py  # B3 extractor 稳定性测试入口
    run_eval_batch.py  # 批量 eval 入口
  configs/             # Agent 配置模板
    .claude/           # CC 双 agent（famou-master + famou-build）
    .claude-single/    # CC 单 agent（famou-single，master+build 合一）
    .opencode/         # OpenCode 双 agent
    .opencode-single/  # OpenCode 单 agent
  prompt_variants/     # Prompt 正文（default 及各变体），缺失文件自动继承 default
  skill_sets/          # 可注入的 skill 集合（none 表示不注入）
  ui/                  # Trace Viewer & Experiment Dashboard
    server.py          # FastAPI 只读后端（挂载 chat_api router）
    chat_api.py        # 交互式聊天 API（创建会话、SSE 流式消息、trace 收集）
    static/            # 单页前端
      index.html       # 实验 Dashboard + Trace Viewer
      chat.html        # Interactive Chat 页面
  docs/                # 设计文档
  sandbox.py           # 跨平台文件系统沙箱（macOS sandbox-exec / Linux bwrap）
  defaults.py          # 共享常量（DEFAULT_AGENT_CONFIG 等）
  workspace.py         # 公共 workspace 准备、instruction 构建、结果写入
  agent_builder.py     # 组装 frontmatter + prompt 写入 workspace，复制 skill_sets
  answerer.py          # 澄清回答策略（HumanAnswerer / DefaultValueAnswerer / ApiAnswerer）
  eval_clarify.py      # B2/B3 澄清覆盖率评估（LLM judge）
  trace_converter.py   # trace 收集 + 转换为统一 schema
  bench_config.py      # 读取 bench_config.toml，提供路径解析
  eval.py              # extractor + evaluator 公共逻辑
  bench_config.toml          # 本机路径配置（gitignored）
  bench_config.toml.example  # 配置模板
```

## 快速开始

### 1. 安装 Agent 脚手架

框架通过外部 CLI 工具驱动 agent，根据使用的 runner 类型安装对应工具：

**Claude Code**（cc_native / cc_famou / cc_single）：

```bash
# 推荐：原生安装（自动更新，无需 Node.js）
curl -fsSL https://claude.ai/install.sh | sh

# 或通过 npm（需要 Node.js 18+）
npm install -g @anthropic-ai/claude-code
```

安装后需要登录或配置 API key，详见 [Claude Code 文档](https://code.claude.com/docs/en/setup)。

**OpenCode**（opencode_native / opencode_famou / opencode_single）：

```bash
# 推荐：curl 安装
curl -fsSL https://opencode.ai/install | bash

# 或通过 npm（需要 Node.js 18+）
npm install -g opencode-ai

# 或通过 Homebrew（macOS）
brew install anomalyco/tap/opencode
```

安装后需要配置 API provider。如果使用 Anthropic 兼容接口（如内部代理），在全局配置 `~/.config/opencode/opencode.json`（或 `.jsonc`）中添加：

```jsonc
{
  "provider": {
    "anthropic": {
      "options": {
        "apiKey": "{env:ANTHROPIC_API_KEY}",
        "baseURL": "https://your-api-proxy.example.com"
      }
    }
  },
  "model": "anthropic/claude-sonnet-4-6"
}
```

`apiKey` 支持 `{env:VAR_NAME}` 读取环境变量或 `{file:~/.secrets/key}` 读取文件。详见 [OpenCode 配置文档](https://opencode.ai/docs/config/)。

**文件系统沙箱**（`--sandbox` 参数，可选）：

```bash
# macOS: 系统自带 sandbox-exec，无需安装

# Linux: 安装 bubblewrap
apt install bubblewrap
```

### 2. 安装 Python 依赖

```bash
pip install -r runners/requirements.txt
```

### 3. 配置本机路径

复制并填写本机配置：

```bash
cp runners/bench_config.toml.example runners/bench_config.toml
# 编辑 bench_config.toml，填入 benchmark_cases / results 的绝对路径
# 如需使用 API 自动回答，还需配置 [answerer] 段
# 如需使用 Interactive Chat，可选配置 [paths] interactive 字段（默认 results 同级 interactive_sessions/）
```

`bench_config.toml` 配置说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `[paths].benchmark_cases` | 路径 | 是 | 统一 benchmark case 目录 |
| `[paths].results` | 路径 | 是 | 实验结果目录 |
| `[paths].interactive` | 路径 | 否 | Chat 会话目录（默认 `results/../interactive_sessions`） |
| `[answerer].api_base_url` | URL | 否 | 自动回答 API 地址 |
| `[answerer].auth_token` | 字符串 | 否 | API key / auth token |
| `[answerer].model` | 字符串 | 否 | 回答模型（默认 glm-5） |
| `[sandbox].extra_deny_read` | 字符串列表 | 否 | 额外的读黑名单（合并到内置 deny） |
| `[sandbox].extra_allow_write_dirs` | 字符串列表 | 否 | 额外的写白名单目录 |
| `[sandbox].extra_allow_write_files` | 字符串列表 | 否 | 额外的写白名单单文件 |

## 运行前提

必须使用 `python -m` 方式运行，否则相对导入会失败。

统一入口为 `run_bench.py`，通过 `--benchmark b2/b3` 区分模式；也可用 `run_b2.py` / `run_b3.py` 快捷调用（自动注入 `--benchmark`）：

```bash
cd /path/to/webagent/webagent

# 统一入口
python -m runners.cli.run_bench --benchmark b3 --case ... --runner ...
python -m runners.cli.run_bench --benchmark b2 --case ... --runner ...

# 快捷入口（等价）
python -m runners.cli.run_b3 --case ... --runner ...
python -m runners.cli.run_b2 --case ... --runner ...
```

## 运行命令

### B3 端到端评测

```bash
# 单 case（人工回答澄清，默认）
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou

# API 自动回答澄清
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --answerer api

# 多 case
python -m webagent.runners.cli.run_b3 --case city_delivery_routing replenishment_with_lead_time --runner cc_famou --answerer api

# 全量（所有有 instruction.md 和 tests/ 的 case）
python -m webagent.runners.cli.run_b3 --case all --runner cc_famou --answerer api

# 每个 case 跑 3 次
python -m webagent.runners.cli.run_b3 --case all --runner cc_famou --answerer api --runs 3

# 只跑 agent，跳过评估
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --no-eval

# 启用文件系统沙箱（deny benchmark cases + 同 batch 其他 run）
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --answerer api --sandbox

# 首次执行后触发深度演化（25 轮）
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner opencode_famou --answerer api --evolve 25

# 使用指定 prompt variant（默认 default）
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --prompt-variant v2

# 注入指定 skill 集（默认 default；none 表示不注入）
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --skill-set my_skills

# 使用 query 变体代替 instruction.md（对应 queries/{variant}.md）
# 不指定时默认使用 instruction.md 作为初始 prompt
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --query-variant default

# 指定 agent 模型（默认 sonnet；支持别名 sonnet/opus/haiku 或完整 model ID）
python -m webagent.runners.cli.run_b3 --case city_delivery_routing --runner cc_famou --model opus
```

Prompt 文件存放在 `prompt_variants/<variant>/` 下，缺失的文件自动继承 `default/`。

Skill 集存放在 `skill_sets/<name>/` 下，运行时会被复制到 `workspace/.claude/skills/`（CC）或 `workspace/.opencode/skills/`（OpenCode）。`none` 表示不注入任何 skill。

### B2 澄清阶段评测

```bash
# 单 case，人工回答（默认）
python -m webagent.runners.cli.run_b2 --case city_delivery_routing --runner cc_famou

# API 自动回答（基于 case/gt.json 背景知识，由 LLM 自动生成回答）
python -m webagent.runners.cli.run_b2 --case city_delivery_routing --runner cc_famou --answerer api

# 多 case 批量（需配合 --answerer api）
python -m webagent.runners.cli.run_b2 --case city_delivery_routing harbor_scheduling --runner cc_famou --answerer api

# 全量
python -m webagent.runners.cli.run_b2 --case all --runner cc_famou --answerer api

# 每个 case 跑 3 次
python -m webagent.runners.cli.run_b2 --case all --runner cc_famou --answerer api --runs 3

# 手动指定背景文件（覆盖默认的 case/gt.json）
python -m webagent.runners.cli.run_b2 --case harbor_scheduling --runner cc_famou --answerer api --background path/to/bg.json
```

`--answerer` 支持以下类型：

| answerer | 说明 |
|---|---|
| `human` | 终端交互，人工输入回答（默认） |
| `api` | LLM 自动回答，基于 instruction + gt.json + information.md 知识 |
| `api:minimal` | LLM 简短回答风格，模拟忙碌的业务方 |
| `default-value` | 所有澄清问题一律回复"使用默认值"，用作 baseline |

`--answerer api` 时需要在 `bench_config.toml` 中配置 `[answerer]` 段（API 地址、auth token、模型）。

ApiAnswerer 知识优先级：instruction.md + gt.json（主要） > information.md（补充参考，不主动透露评估公式等技术细节）。

### B3 Extractor 稳定性测试

对已有的 agent workspace 重复运行 extractor + evaluator，统计评分分布：

```bash
# --run 填 results/ 下的实验目录名
python -m webagent.runners.cli.run_b3_stability \
    --case city_delivery_routing \
    --run  cc_famou_20260401_001646 \
    --runs 5
```

输出写入 `workspace/.eval/stability/summary.json`。

### 批量 Eval

```bash
# 对整个 batch 目录统一 eval（跳过已有 result.json 的）
python -m webagent.runners.cli.run_eval_batch --batch /path/to/cc_native_20260403_002448

# 强制重跑
python -m webagent.runners.cli.run_eval_batch --batch /path/to/cc_native_20260403_002448 --force
```

## Web UI

```bash
cd /path/to/webagent
python -m webagent.runners.ui.server
# 打开 http://localhost:8765
```

**Dashboard**（`/`）— 查看所有实验的评分汇总，支持多实验对比，可展开查看每个 case 的详细评分和 trace 统计。

**Trace Viewer** — 从 Dashboard 点击 "View Trace" 进入，按 session 浏览每一轮的 thinking、tool 调用及 token 用量。

**Interactive Chat**（`/chat.html`）— 与 agent 交互式对话，适合调试 prompt 或自由任务：选择 runner / variant / skill-set，上传数据文件，发送消息后实时流式展示输出，关闭会话后自动保存 trace。

## Runner 类型

| runner | 说明 |
|---|---|
| `cc_native` | Claude Code CLI，不注入 agent 配置（支持 skill 注入） |
| `cc_famou` | Claude Code CLI + Famou 双 agent（`.claude/` 配置注入） |
| `cc_single` | Claude Code CLI + Famou Single Agent（`.claude-single/` 配置注入，master+build 合一） |
| `opencode_native` | OpenCode CLI (`opencode run --format json`)，不注入配置，走内置 build agent |
| `opencode_famou` | OpenCode CLI，注入 Famou 双 agent 配置，路由到 famou-master |
| `opencode_single` | OpenCode CLI，注入 Single agent 配置，路由到 famou-single（master+build 合一） |

## 文件系统沙箱

`--sandbox` 参数启用内核级文件隔离，防止 agent 读取 benchmark evaluator、gt.json、其他 batch/session 的产物，以及用户敏感文件（`.ssh`、`Documents` 等）。

### 平台支持

| 平台 | 工具 | 隔离模型 | 错误表现 | 安装 |
|---|---|---|---|---|
| macOS | sandbox-exec (Seatbelt) | 黑名单 deny 指定路径 | EACCES (Operation not permitted) | 系统自带 |
| Linux | bubblewrap (bwrap) | 整 root 只读绑定 + 受限路径 tmpfs 覆盖 | ENOENT (No such file) | `apt install bubblewrap` |

### 用法

```bash
# B2/B3 评测启用 sandbox
python -m webagent.runners.cli.run_b2 --case xxx --runner cc_famou --answerer api --sandbox
python -m webagent.runners.cli.run_b3 --case xxx --runner opencode_famou --answerer api --sandbox
```

Interactive Chat（`chat_api.py`）**默认**启用 sandbox，无需手动开启。

### 隔离规则

**读：黑名单**（默认全部可读，仅 deny 指定路径；workspace 在 deny 范围内仍可读）
- 内置 deny：`CASES_DIR`、`RESULTS_DIR`、`INTERACTIVE_DIR`
- 可通过 `bench_config.toml` 的 `[sandbox].extra_deny_read` 扩展

**写：白名单**（默认全部不可写，仅允许列表内路径）
- 内置允许：workspace、`~/.claude`、`~/.local`、`~/.config`、`~/.cache`、`~/.npm`、`~/.bun`、opencode 安装目录、`/tmp`、`~/.claude.json`
- 可通过 `bench_config.toml` 的 `[sandbox].extra_allow_write_dirs` / `extra_allow_write_files` 扩展

**网络：完全不限制**

### 配置示例

`bench_config.toml`：

```toml
[sandbox]
# 防止 agent 看到本机敏感目录（即使 agent 故意 find 也搜不到）
extra_deny_read = [
    "/Users/youruser/.ssh",
    "/Users/youruser/.aws",
    "/Users/youruser/Documents",
    "/Users/youruser/Downloads",
    "/path/to/other_project",
]
extra_allow_write_dirs = []
extra_allow_write_files = []
```

## Benchmark Case 澄清体系

每个支持澄清评测的 case 包含以下四件套：

| 文件 | 说明 |
|---|---|
| `instruction.md` | 完整的自然业务语言问题描述，完成该问题的最小文本描述 |
| `queries/default.md` | 使用者可能提出的最简提问，只包含基础信息和要做什么 |
| `gt.json` | instruction 与 query 之间的信息差，结构化为 `{类别}·{话题}: 内容`；用于评估澄清覆盖率 |
| `information.md` | 完整参考信息（业务背景 + 数据说明 + 评估逻辑），供 answerer 准确回答澄清问题 |

gt.json 的 key 命名规范：`{类别}·{话题}`，类别包括 `目标`、`约束`、`参数`、`逻辑`。

## 澄清覆盖率评估

`eval_clarify.py` 提供 B2 / B3 共享的澄清覆盖率评估：

```python
from webagent.runners.eval_clarify import run_clarify_eval
result = run_clarify_eval(case_path, workspace_path)
# result: {coverage_score, total_keys, covered, partial, uncovered, rounds, judgments}
```

通过 LLM judge 逐 key 判定 dialog.json 中的澄清对话是否覆盖了 gt.json 中的每个信息点（covered / partial / uncovered），计算覆盖率得分。
