# Runner 配置重构：Agent 拓扑与 Runner 代码解耦

## 现状问题

### 1. runner_type 混合了两个维度

当前 `runner_type` 把"运行平台"和"agent 架构"耦合在一起：

```
cc_native       = 平台(CC)   + 架构(native，无配置)
cc_famou        = 平台(CC)   + 架构(master+build)
cc_single       = 平台(CC)   + 架构(single)
opencode_native = 平台(OC)   + 架构(native)
opencode_famou  = 平台(OC)   + 架构(master+build)
opencode_single = 平台(OC)   + 架构(single)
```

每新增一种 agent 架构（如 master + multi-build），需要：
- 在 `run_b3.py` 的 `_DEFAULT_AGENT_CONFIG` 加映射
- 在 `factory.py` 的 `_REGISTRY` 加注册
- 新建一个 `configs/.claude-xxx/` 目录
- 新建一个 `configs/.opencode-xxx/` 目录

实际上 runner 代码（CCFamouRunner / OpenCodeACPRunner）对 single 和 famou **完全相同** — factory.py 已经在复用同一个 Runner 类了。

### 2. agent 拓扑完全由配置决定

Runner 代码只做三件事：
1. 复制配置到 workspace（`copy_base_config` + `assemble_agents` + `copy_skills`）
2. 启动 agent 进程
3. 发送 instruction

它 **不关心** workspace 里有几个 agent、谁调用谁。拓扑完全由以下三样东西定义：

| 配置项 | 定义什么 | 举例 |
|--------|---------|------|
| `frontmatter/*.txt` | 有哪些 agent，各自的工具和能力 | master 有 Task，build 没有 |
| `settings.json` / `opencode.jsonc` | 入口 agent、权限矩阵 | `"agent": "famou-master"` |
| `prompts/*.md` | 每个 agent 的行为指令 | master 写 PLAN.md，build 执行 |

### 3. 配置目录命名不一致

```
configs/
  .claude/            # 名字看不出是 famou 双 agent
  .claude-single/     # 这个看得出
  .opencode/          # 同上
  .opencode-single/
```

## 重构方案

两个方案共享相同的核心变化（拆分 platform/topology、Factory 简化、Runner 合并），区别在于 prompt 管理方式。

---

### 方案 A：自包含拓扑 + prompt_variants 覆盖

**核心原则：**
1. 拆分 platform 和 topology
2. 拓扑目录自包含（frontmatter + prompts + settings）
3. `prompt_variants/` 提供实验性 prompt 覆盖层

**适用场景：** 需要跨多个拓扑共享 prompt 实验，或 prompt 实验量非常大时。

**已知问题：**
- 同名 agent 跨拓扑时，variant 覆盖会影响所有拓扑（除非按拓扑再分子目录，增加复杂度）
- 一个 variant 目录可能混合多个拓扑的 prompt，语义不清晰

---

### 方案 B：纯自包含拓扑，无覆盖机制（推荐）

**核心原则：**
1. 拆分 platform 和 topology
2. 拓扑目录完全自包含，没有任何覆盖/查找链
3. prompt 实验 = fork 拓扑目录（`cp -r configs/cc/famou configs/cc/famou-v2`）

**适用场景：** 拓扑数量少且稳定（当前实际只有 famou/single/native），主要迭代 prompt 和 skills。

**优势：**
- 零概念开销：一个目录 = 一个完整可运行的配置，没有覆盖优先级、没有查找链
- 操作直觉：复制目录改文件就能实验，git 跟踪变更
- 前端友好：扫描 `configs/{platform}/*/` 即可列出所有配置，CRUD 直接操作目录
- 不同 prompt 版本天然隔离：`famou-v2/` 和 `famou/` 互不干扰

**代价：**
- fork 时不变的文件会重复（但配置文件总共就几 KB，可接受）
- 如果 baseline prompt 更新，需要同步到所有 fork（可用脚本辅助）

---

以下先按**方案 B（推荐）**详述，方案 A 的差异点在文末附录说明。

### 核心变化：拆分 platform 和 topology

**Before:**
```
runner_type = "cc_famou"  →  隐含 platform=CC, config=.claude/
```

**After:**
```
platform  = "cc"       →  决定用哪个 Runner 类
topology  = "famou"    →  决定用哪个配置目录
```

### 目录结构

每个拓扑目录是**自包含的**，包含 frontmatter、prompts、平台设置：

```
runners/
  configs/
    cc/                              # CC 平台
      native/                        # 无配置（空目录或不存在）
      famou/                         # master + build
        frontmatter/
          famou-master.txt
          famou-build.txt
        prompts/
          famou-master.md
          famou-build.md
        settings.json
      single/                        # single agent
        frontmatter/
          famou-single.txt
        prompts/
          famou-single.md
        settings.json
      multi-build/                   # master + 多 build（新增架构示例）
        frontmatter/
          famou-master.txt
          famou-build-code.txt
          famou-build-viz.txt
        prompts/
          famou-master.md
          famou-build-code.md
          famou-build-viz.md
        settings.json

    opencode/                        # OpenCode 平台
      native/
      famou/
        frontmatter/
          famou-master.txt
          famou-build.txt
        prompts/
          famou-master.md
          famou-build.md
        opencode.jsonc
      single/
        frontmatter/
          famou-single.txt
        prompts/
          famou-single.md
        opencode.jsonc
```

没有 `prompt_variants/` 目录。Prompt 实验通过 fork 拓扑目录实现：

```bash
# 想试新的 master prompt？
cp -r configs/cc/famou configs/cc/famou-v2
vim configs/cc/famou-v2/prompts/famou-master.md
python -m runners.run_b3 --platform cc --topology famou-v2
```

### RunnerConfig

```python
@dataclass
class RunnerConfig:
    platform: str                           # "cc" | "opencode"
    topology: str = "famou"                 # configs/{platform}/ 下的目录名
    skill_set: str = "default"
    model: str | None = None
    max_turns: int = 200

    @property
    def topology_dir(self) -> Path | None:
        """解析为实际的配置目录路径。native 返回 None。"""
        if self.topology == "native":
            return None
        return _CONFIGS_DIR / self.platform / self.topology

    @property
    def runner_type(self) -> str:
        """向后兼容的 runner_type 字符串。"""
        return f"{self.platform}_{self.topology}"
```

没有 `prompt_variant` 字段——不同的 prompt 就是不同的 topology 名。

### Factory 简化

```python
# factory.py
from .cc_runner import CCRunner
from .opencode_runner import OpenCodeRunner

_PLATFORM_REGISTRY = {
    "cc":       CCRunner,
    "opencode": OpenCodeRunner,
}

def runner_from_config(config: RunnerConfig) -> AgentRunner:
    cls = _PLATFORM_REGISTRY.get(config.platform)
    if cls is None:
        raise ValueError(f"Unknown platform: '{config.platform}'")
    return cls(config)
```

只有两个 Runner 类，不再随 agent 架构增长。

### Runner 实现（合并后）

```python
# cc_runner.py — 合并 NativeCCRunner + CCFamouRunner
class CCRunner(AgentRunner):
    async def start(self, workspace: Path) -> AgentSession:
        workspace.mkdir(parents=True, exist_ok=True)
        if self.config.topology_dir:
            from ..agent_builder import copy_base_config, assemble_agents, copy_skills
            copy_base_config(self.config.topology_dir, workspace)
            assemble_agents(self.config.topology_dir, workspace)
            copy_skills(self.config.skill_set, self.config.topology_dir, workspace)
        return CCSession(workspace, self.config)


# opencode_runner.py — 合并 OpenCodeACPRunner + OpenCodeNativeRunner
class OpenCodeRunner(AgentRunner):
    async def start(self, workspace: Path) -> AgentSession:
        workspace.mkdir(parents=True, exist_ok=True)
        if self.config.topology_dir:
            from ..agent_builder import copy_base_config, assemble_agents, copy_skills
            copy_base_config(self.config.topology_dir, workspace)
            assemble_agents(self.config.topology_dir, workspace)
            copy_skills(...)
        client, session_id = await _start_acp(workspace)
        return OpenCodeSession(client, session_id)
```

### CLI 入口

```bash
# Before: runner_type 耦合了平台和架构
python -m runners.run_b3 --case all --runner cc_famou

# After: 明确分开
python -m runners.run_b3 --case all --platform cc --topology famou

# prompt 实验 = 不同的 topology 名
python -m runners.run_b3 --case all --platform cc --topology famou-v2

# 新增架构无需改代码
python -m runners.run_b3 --case all --platform cc --topology multi-build

# 向后兼容 shorthand（可选）
python -m runners.run_b3 --case all --runner cc_famou   # 自动拆分为 platform=cc, topology=famou
```

## 新增 Agent 架构的流程

以 "master + code-build + viz-build" 为例，只需操作一个目录：

### Step 1: 复制已有拓扑作为起点

```bash
cp -r configs/cc/famou configs/cc/multi-build
```

### Step 2: 修改 frontmatter

```yaml
# frontmatter/famou-master.txt（修改 description）
---
name: famou-master
description: Master Agent - 规划并分派任务给 code-build 和 viz-build
tools: [Read, Glob, Grep, Write, Edit, TodoWrite, TodoRead, Task]
---
```

```yaml
# frontmatter/famou-build-code.txt（新建）
---
name: famou-build-code
description: Code Build Agent - 编写优化算法、数据处理代码
tools: [Read, Write, Edit, Bash, Glob, Grep, TodoWrite, TodoRead]
maxTurns: 100
---
```

```yaml
# frontmatter/famou-build-viz.txt（新建）
---
name: famou-build-viz
description: Viz Build Agent - 生成可视化图表和 dashboard
tools: [Read, Write, Edit, Bash, Glob, Grep, TodoWrite, TodoRead]
maxTurns: 50
---
```

### Step 3: 编写 prompt

在同一个目录下的 `prompts/` 中编写：

```
configs/cc/multi-build/prompts/
  famou-master.md           # master 的行为指令（何时委派给哪个 build）
  famou-build-code.md       # code build 的行为指令
  famou-build-viz.md        # viz build 的行为指令
```

### Step 4: 运行

```bash
python -m runners.run_b3 --case all --platform cc --topology multi-build
```

**零代码改动。所有配置在一个目录内完成。**

## 其他可能的架构

此方案不限于 master+build 模式，任何 CC/OpenCode 的 Task 工具支持的拓扑都可以配置：

| 架构 | frontmatter 目录 | 说明 |
|------|-----------------|------|
| single | `famou-single.txt` | 一个 agent 全做 |
| master + build | `famou-master.txt` + `famou-build.txt` | 当前默认 |
| master + N builds | master + build-code + build-viz + ... | 专业化分工 |
| pipeline | A + B + C（A 调 B，B 调 C） | 链式处理 |
| hierarchical | master → sub-master → builds | 多层编排 |
| peer | agents 互相调用 | 需要平台支持双向 Task |

## agent_builder 改动

`agent_builder.py` **不需要改动核心逻辑**。它已经从 `frontmatter/*.txt` 自动发现 agent 名称。

需要适配两处：

### 1. `_platform_dir()` — 目录结构变化

```python
# Before: 从目录名推断平台
def _platform_dir(agent_config_dir: Path) -> str:
    name = agent_config_dir.name  # ".claude" / ".claude-single"
    if name.startswith(".claude"): return ".claude"
    if name.startswith(".opencode"): return ".opencode"

# After: 从父目录名推断平台
def _platform_dir(agent_config_dir: Path) -> str:
    platform = agent_config_dir.parent.name  # "cc" / "opencode"
    return ".claude" if platform == "cc" else ".opencode"
```

### 2. `assemble_agents()` — 简化 prompt 读取

```python
def assemble_agents(topology_dir: Path, workspace: Path) -> None:
    """组装 agent：frontmatter + prompt → CLAUDE.md / agent .md"""
    for fm_file in (topology_dir / "frontmatter").glob("*.txt"):
        agent_name = fm_file.stem
        frontmatter = fm_file.read_text()

        # prompt 直接从拓扑目录读取，没有查找链
        prompt_file = topology_dir / "prompts" / f"{agent_name}.md"
        if not prompt_file.exists():
            raise FileNotFoundError(
                f"No prompt found for agent '{agent_name}' at {prompt_file}"
            )
        prompt = prompt_file.read_text()

        _write_agent_md(workspace, agent_name, frontmatter, prompt)
```

没有 `_resolve_prompt`，没有查找优先级——一个目录里什么都有。

## 前端支持

此文件结构天然支持前端管理界面，前端作为**自包含目录的视图层**，无需额外的 library 或 registry：

| 前端操作 | 后端实现 |
|---------|---------|
| 列出所有配置 | 扫描 `configs/{platform}/*/` 目录 |
| 查看配置详情 | 读取目录内的 frontmatter + prompts + settings |
| 创建新拓扑 | 复制已有目录到新名字，或从零创建目录 |
| Fork 拓扑做实验 | `cp -r` 一个目录，修改其中的 prompt |
| 编辑 prompt | 直接写对应目录下的 `.md` 文件 |
| 对比两个配置 | diff 两个目录 |
| 删除实验配置 | 删除目录 |

## 迁移路径

### Phase 1: 目录重组（无功能变化）

```bash
# 创建新目录结构
mkdir -p configs/cc/famou/prompts configs/cc/single/prompts
mkdir -p configs/opencode/famou/prompts configs/opencode/single/prompts

# 移动 frontmatter + settings
mv configs/.claude/frontmatter    configs/cc/famou/frontmatter
mv configs/.claude/settings.json  configs/cc/famou/settings.json
mv configs/.claude-single/frontmatter    configs/cc/single/frontmatter
mv configs/.claude-single/settings.json  configs/cc/single/settings.json
# ... opencode 同理

# 将 baseline prompt 移入各拓扑目录
mv prompt_variants/baseline/famou-master.md  configs/cc/famou/prompts/
mv prompt_variants/baseline/famou-build.md   configs/cc/famou/prompts/
mv prompt_variants/baseline/famou-single.md  configs/cc/single/prompts/
# ... opencode 同理（cc 和 opencode 的 prompt 相同时可用 cp）

# 删除已废弃的 prompt_variants/ 目录
rm -rf prompt_variants/
```

### Phase 2: 改 RunnerConfig + Factory

- RunnerConfig 拆分 `platform` + `topology`
- Factory 简化为两个 Runner
- Runner 合并（NativeCCRunner + CCFamouRunner → CCRunner）

### Phase 3: 改 agent_builder

- `_platform_dir()` 适配新目录结构
- `assemble_agents()` 简化为直接从拓扑目录读取 prompt（无查找链）

### Phase 4: 改 CLI 入口

- `run_b3.py` / `run_b2.py` 支持 `--platform` + `--topology`
- 去掉 `--prompt-variant`（不同 prompt = 不同 topology 名）
- 可选：保留 `--runner cc_famou` 作为 shorthand 向后兼容

### Phase 5: 新增架构实验

- `cp -r` 已有拓扑目录，修改 frontmatter + prompts
- 直接运行，无需改代码

---

## 附录：方案 A 差异点

方案 A 在方案 B 基础上增加一个 `prompt_variants/` 覆盖层：

### 额外的目录

```
prompt_variants/
  v2/
    famou-master.md        # 覆盖任何拓扑中的 famou-master prompt
```

### RunnerConfig 差异

```python
@dataclass
class RunnerConfig:
    # ... 与方案 B 相同 ...
    prompt_variant: str | None = None   # 方案 A 额外字段
```

### Prompt 查找顺序

1. `prompt_variants/{variant}/{agent}.md` — variant 覆盖
2. `configs/{platform}/{topology}/prompts/{agent}.md` — 拓扑默认

### CLI 差异

```bash
# 方案 A 支持 --prompt-variant
python -m runners.run_b3 --platform cc --topology famou --prompt-variant v2
```

### 已知问题：同名 agent 跨拓扑冲突

`famou` 和 `multi-build` 拓扑都可能有一个叫 `famou-master` 的 agent。
此时 `prompt_variants/v2/famou-master.md` 会**同时覆盖两者**，无法单独控制。

**解决方案：按拓扑加子目录**

```
prompt_variants/
  v2/
    famou/                        # 只覆盖 famou 拓扑
      famou-master.md
    multi-build/                  # 只覆盖 multi-build 拓扑
      famou-master.md
```

但这导致查找链变成三层：

1. `prompt_variants/{variant}/{topology}/{agent}.md` — 精确覆盖
2. `prompt_variants/{variant}/{agent}.md` — 跨拓扑覆盖
3. `configs/{platform}/{topology}/prompts/{agent}.md` — 拓扑默认

此时方案 A 的复杂度已经不比方案 B 低——方案 B 直接 `cp -r` fork 拓扑目录，零概念开销，同样实现了按拓扑隔离 prompt 实验。

### 其他问题

- 一个 variant 目录可能混合多个不相关拓扑的 prompt，语义不清晰
- 三层查找链增加了调试和理解成本（"这个 prompt 到底从哪来的？"）
