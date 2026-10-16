# Skill Sets 方案设计

## 概念

Agent Skill 是放在 `.claude/skills/<name>/SKILL.md` 的**可复用指令性知识**，格式为 YAML frontmatter + Markdown 正文。与 prompt（agent 的核心指令）不同，skill 提供的是"遇到特定问题时的处理方法"，可被 Claude 自动调用或手动触发。

实验目标：测试注入不同 skill 集是否影响 agent 的问题求解方式和输出质量。

---

## 与其他实验轴的关系

| 参数 | 控制内容 |
|---|---|
| `--runner` | agent 架构（双 agent / single / native） |
| `--prompt-variant` | agent 核心指令内容 |
| `--skill-set` | 注入的 skill 知识集（本文档） |

三轴完全独立，可任意组合：
```bash
python -m runners.run_b3 --runner cc_famou --prompt-variant v2 --skill-set lp-formulation
```

---

## 平台兼容性

| 平台 | 原生路径 | `.claude/skills/` 支持 |
|---|---|---|
| CC | `workspace/.claude/skills/` | 完整支持 |
| OpenCode | `workspace/.opencode/skills/` | 文档声称支持但有 bug，不可靠 |

**结论**：runner 层各自负责复制到平台原生路径，skill 内容文件两者共用。

---

## 文件结构

```
runners/
  configs/
    skill_sets/
      default/              # 空（不注入任何 skill，默认值）
      <skill-set-name>/     # 一个 skill set = 一组 SKILL.md 文件
        <skill-a>/
          SKILL.md
        <skill-b>/
          SKILL.md
```

### SKILL.md 格式

```markdown
---
name: <skill-name>
description: <何时自动触发该 skill，或 Claude 应在什么情况下使用它>
---

# <Skill 标题>

<具体指令内容>
```

### 示例

```
configs/skill_sets/
  default/                          # 空
  lp-formulation/
    lp/
      SKILL.md                      # 线性规划建模指南
  planning/
    structured-planning/
      SKILL.md                      # 结构化拆解问题步骤
  bundle-a/                         # 多 skill 组合
    lp/
      SKILL.md
    structured-planning/
      SKILL.md
```

---

## 代码改动

### 1. `agent_builder.py`：新增 `copy_skills()`

```python
_SKILL_SETS_DIR = _RUNNERS_DIR / "configs" / "skill_sets"

def copy_skills(skill_set: str, platform: str, workspace: Path) -> None:
    """
    将 skill_set 下的所有 skill 文件复制到 workspace 的平台原生路径。

    skill_set : configs/skill_sets/ 下的子目录名（"default" 时跳过）
    platform  : "cc"       → workspace/.claude/skills/
                "opencode" → workspace/.opencode/skills/
    """
    if skill_set == "default":
        return

    src = _SKILL_SETS_DIR / skill_set
    if not src.exists():
        raise FileNotFoundError(f"skill_set 不存在: {src}")

    dst_map = {
        "cc":       workspace / ".claude"   / "skills",
        "opencode": workspace / ".opencode" / "skills",
    }
    dst = dst_map[platform]
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)
```

### 2. `backends/base.py`：`RunnerConfig` 加字段

```python
@dataclass
class RunnerConfig:
    runner_type: str
    agent_config_dir: Path | None = None
    prompt_variant: str = "baseline"
    prompt_variants_dir: Path | None = None
    model: str | None = None
    max_turns: int = 100
    skill_set: str = "default"          # 新增
```

### 3. `backends/cc_famou.py`：注入 skill

```python
async def start(self, workspace: Path) -> NativeCCSession:
    workspace.mkdir(parents=True, exist_ok=True)
    if self.config.agent_config_dir:
        from ..agent_builder import copy_base_config, assemble_agents, copy_skills
        copy_base_config(self.config.agent_config_dir, workspace)
        assemble_agents(...)
        copy_skills(self.config.skill_set, "cc", workspace)   # 新增
    return NativeCCSession(workspace, self.config)
```

### 4. `backends/opencode_acp.py`：`OpenCodeACPRunner` 注入 skill

```python
async def start(self, workspace: Path) -> OpenCodeSession:
    workspace.mkdir(parents=True, exist_ok=True)
    if self.config.agent_config_dir:
        from ..agent_builder import copy_base_config, assemble_agents, copy_skills
        copy_base_config(self.config.agent_config_dir, workspace)
        assemble_agents(...)
        copy_skills(self.config.skill_set, "opencode", workspace)   # 新增
    client, session_id = await _start_acp(workspace)
    return OpenCodeSession(client, session_id)
```

`OpenCodeNativeRunner` 不注入配置，也不注入 skill（保持原生状态）。

### 5. `run_b3.py` / `run_b2.py`：加参数

```python
parser.add_argument("--skill-set", default="default",
                    help="注入的 skill 集名称（configs/skill_sets/ 下的目录，默认: default）")
```

传入 `RunnerConfig`：
```python
config = RunnerConfig(
    runner_type=runner_type,
    agent_config_dir=...,
    prompt_variant=prompt_variant,
    skill_set=args.skill_set,           # 新增
)
```

---

## 实现顺序

1. `agent_builder.py` 加 `copy_skills()` 函数
2. `RunnerConfig` 加 `skill_set` 字段
3. `cc_famou.py` 和 `opencode_acp.py` 调用 `copy_skills()`
4. `run_b3.py` / `run_b2.py` 加 `--skill-set` 参数
5. 创建 `configs/skill_sets/default/`（空目录，加 `.gitkeep`）
6. 按需添加具体 skill set 目录和 SKILL.md 文件

---

## 注意事项

- `NativeCCRunner`（`cc_native`）不注入配置也不注入 skill，`--skill-set` 对其无效
- `OpenCodeNativeRunner`（`opencode_native`）同上
- skill_set 目录不存在时运行报错（`FileNotFoundError`），避免静默跳过掩盖配置错误
- CC 侧需要确认 `allowed_tools` 包含 `"Skill"` 才能让 Claude 调用 skill
