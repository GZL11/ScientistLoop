# 环境隔离设计

## 背景与动机

当前 benchmark runners 直接在宿主机上运行 agent，无文件系统隔离。主要风险：

1. **漏题** — agent 可通过 Bash 访问 `tests/evaluator.py` 和 `reference_metrics.json`，看到评分逻辑和标准答案
2. **串 workspace** — agent 可读取其他 case 的数据或产物，也可读取同 batch 其他 run 的结果
3. **CC guard hook 不完整** — 当前 hook 只覆盖 Read/Write/Edit/Glob/Grep，未覆盖 Bash（等于完全开放）
4. **OpenCode 无路径级隔离** — permission 系统只能 allow/deny 整个工具，不能限制路径

## 三层隔离方案

| 层级 | 方案 | 隔离级别 | macOS | Linux | 适用场景 |
|------|------|---------|-------|-------|---------|
| L0 | 无隔离（现状） | 无 | ✓ | ✓ | 本地快速调试 |
| L1 | srt (sandbox-runtime) | 内核级文件系统隔离 | ✓ | ✓ | 本地正式评测 |
| L2 | Docker (Harbor) | 完整内核隔离 | ✓ | ✓ | 大规模生产评测 |

## L1: srt 本地沙箱（推荐方案）

### 概述

使用 Anthropic 开源的 [sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime) (srt)，在 OS 层面限制 agent 子进程的文件系统访问。macOS 用 Seatbelt，Linux 用 bubblewrap，**内核级强制，Bash 也逃不出去**。

### 安装

```bash
npm install -g @anthropic-ai/sandbox-runtime
```

### 隔离策略

**targeted deny**：deny 敏感目录，allowRead 当前 workspace。

```json
{
  "filesystem": {
    "denyRead": [
      "<CASES_DIR>",
      "<BATCH_DIR>"
    ],
    "allowRead": [
      "<workspace>"
    ],
    "allowWrite": [
      "<workspace>",
      "~/.local/share/opencode",
      "~/.claude",
      "/tmp"
    ],
    "denyWrite": []
  },
  "network": {
    "allowedDomains": ["<从配置自动提取的 API 地址>"],
    "deniedDomains": []
  }
}
```

**优先级规则**：
- `allowRead` > `denyRead`（可在 deny 大范围内 allow 小范围）
- `denyWrite` > `allowWrite`（可在 allow 大范围内 deny 小范围）

### deny 范围说明

| denyRead 路径 | 保护内容 |
|---|---|
| `<CASES_DIR>` (benchmark/cases/) | evaluator.py、reference_metrics.json、gt.json、information.md 等所有 case 文件 |
| `<BATCH_DIR>` (results/当前 batch/) | 同 batch 其他 case/run 的数据和产物 |

| allowRead 路径 | 用途 |
|---|---|
| `<workspace>` | 当前 run 的工作目录（数据 + 产物） |

注意：`allowRead > denyRead`，所以 workspace 即使在 batch 目录下也能正常读取。

### allowWrite 说明

| 路径 | 用途 |
|---|---|
| `<workspace>` | agent 产物输出 |
| `~/.local/share/opencode` | opencode 运行时数据库（SQLite WAL） |
| `~/.claude` | claude code 运行时状态 |
| `/tmp` | 临时文件 |

这些是 opencode/claude 的**运行时必需目录**，不给写权限进程会直接报错退出。

### 网络配置

srt 默认禁止所有出站网络，必须显式白名单：
- 不支持 `"*"` 通配所有域名
- 支持 IP 地址（如 `"211.23.3.237"`）
- 支持通配子域名（如 `"*.anthropic.com"`）
- runner 启动时自动从 `~/.config/opencode/opencode.json` 和 `bench_config.toml` 提取 API 地址

### 已验证的能力（2026-04-23 测试）

| 测试项 | 结果 |
|---|---|
| srt + opencode run，JSON 事件流正常 | ✓ |
| denyRead 阻止 cat 读文件 | ✓ |
| denyRead 阻止 python open() | ✓ |
| denyRead 阻止 ls 列目录 | ✓ |
| allowRead 的文件正常可读 | ✓ |
| denyRead glob 通配符（`cases/*/tests`） | ✗ macOS/Linux 均不支持 |
| 具体路径 deny | ✓ |
| IP 地址放 allowedDomains | ✓ |
| agent 看到的错误是"文件不存在"而非"权限拒绝" | ✓（agent 不会意识到被沙箱了） |

### 集成方式

CLI 增加 `--sandbox` 参数：

```bash
# 无沙箱（本地调试，默认）
python -m webagent.runners.cli.run_b3 --case 05_city_delivery_routing --runner opencode_famou --answerer api

# 有沙箱（正式评测）
python -m webagent.runners.cli.run_b3 --case 05_city_delivery_routing --runner opencode_famou --answerer api --sandbox
```

实现层次：

```
RunnerConfig 新增 sandbox: bool = False
    ↓
Runner.start() 生成 .srt-settings.json 到 workspace
    ↓
Session._run() 构建 cmd 时加 srt 包装：
  ["srt", "-s", settings_path, "--", "opencode", "run", ...]
    ↓
run_bench.py CLI 新增 --sandbox 参数
```

### 限制

- **glob 不可用**：denyRead/allowRead 不支持通配符，需枚举具体路径
- **网络必须白名单**：无法完全禁用网络限制，必须列出 API 地址
- **opencode 运行时目录需 allow**：`~/.local/share/opencode` 等必须可写

## L2: Docker / Harbor（大规模评测）

### 核心思路

B3 cases 已按 Harbor task 标准构建。通过自定义 Harbor Agent 类，将实验维度（prompt_variant、skill_set）作为 Agent 参数，运行时动态注入配置。

### 隔离保证

Docker 容器内 agent 只能看到：
- `/app/` — workspace（instruction.md + data/ + agent 配置）
- `/tests/` — Harbor 在验证阶段才挂载，agent 运行时不可见
- 系统目录 — 只有 Dockerfile 安装的依赖

agent 无法访问：
- 其他 case 的数据
- tests/evaluator.py 和 reference_metrics.json
- 宿主机文件系统

### 自定义 FamouAgent

```python
from harbor.agents.base import BaseAgent

class FamouAgent(BaseAgent):
    def __init__(self, prompt_variant="baseline", skill_set="default",
                 runner_type="cc_famou", max_turns=200, **kwargs):
        super().__init__(**kwargs)
        self.prompt_variant = prompt_variant
        self.skill_set = skill_set
        self.runner_type = runner_type
        self.max_turns = max_turns

    async def setup(self, environment):
        tmp_config = generate_agent_config(
            runner_type=self.runner_type,
            prompt_variant=self.prompt_variant,
            skill_set=self.skill_set,
        )
        config_subdir = ".claude" if self.runner_type.startswith("cc_") else ".opencode"
        await environment.upload_dir(tmp_config, f"/app/{config_subdir}/")

    async def run(self, instruction, environment, context):
        if self.runner_type.startswith("cc_"):
            cmd = (f"claude -p {shlex.quote(instruction)} "
                   f"--output-format stream-json "
                   f"--permission-mode bypassPermissions "
                   f"--max-turns {self.max_turns} --cwd /app")
        else:
            cmd = f"opencode run --cwd /app -p {shlex.quote(instruction)}"
        await environment.exec(cmd, timeout_sec=context.timeout_sec)
```

### agent_builder 复用

| 函数 | 作用 | Harbor 模式调用方式 |
|------|------|-------------------|
| `copy_base_config()` | 复制 settings.json / opencode.jsonc | setup() 生成后 upload_dir() |
| `assemble_agents()` | 合并 frontmatter + prompt body | 同上 |
| `copy_skills()` | 复制 skill set 文件 | 同上 |

## 实施路径

### Phase 1: 当前（本地调试）— 已完成
- 维持现有 runners 不变
- 评测链路已打通

### Phase 2: srt 本地沙箱 — 进行中
- 集成 srt 到 opencode_run.py 和 native_cc.py
- CLI 增加 `--sandbox` 参数
- 自动提取 API 地址配置网络白名单

### Phase 3: Harbor 适配
- 实现 `FamouAgent` 类
- 在 `agent_builder.py` 中加 `generate_agent_config()` 包装函数
- 编写 Harbor YAML 配置模板
- 验证 Docker 环境下 CC CLI / OpenCode 运行正常

### Phase 4: 大规模评测
- 配置并发编排（n_concurrent_trials）
- 跑全量 cases × 多实验组合
