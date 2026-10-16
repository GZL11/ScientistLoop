# Single Agent 方案设计

## 动机

当前 Famou 双 agent 架构：
```
CC/OpenCode main → famou-master（规划/澄清）→ famou-build（执行）
```

实验发现 master 有时会在 build 失败时自己继续完成任务，说明双 agent 拆分的边界并非必须。
Single agent 方案：
```
CC/OpenCode → famou-single（规划 + 澄清 + 执行，一体完成）
```

目标：通过对比实验验证 single agent 是否能达到与双 agent 相近或更好的效果。

---

## Runner 类型

| runner | 配置注入 | agent 结构 |
|---|---|---|
| `cc_native` | 无 | 裸 CC |
| `cc_famou` | `.claude/` | famou-master → famou-build |
| `cc_single` | `.claude-single/` | famou-single（一体） |
| `opencode_native` | 无 | OpenCode 内置 build |
| `opencode_famou` | `.opencode/` | famou-master → famou-build |
| `opencode_single` | `.opencode-single/` | famou-single（一体） |

---

## 文件变更

### 1. `agent_builder.py`：去掉硬编码 `AGENT_NAMES`

现状：`AGENT_NAMES = ["famou-master", "famou-build"]`（硬编码）

改法：从 `frontmatter/` 目录**自动发现** agent 名称：

```python
# 旧
for agent_name in AGENT_NAMES:

# 新
frontmatter_files = sorted(frontmatter_dir.glob("*.txt"))
for frontmatter_file in frontmatter_files:
    agent_name = frontmatter_file.stem
```

效果：
- `.claude/frontmatter/` 有 `famou-master.txt` + `famou-build.txt` → 组装两个 agent（cc_famou 不变）
- `.claude-single/frontmatter/` 只有 `famou-single.txt` → 只组装一个 agent（cc_single）

### 2. 新增配置目录

#### `configs/.claude-single/`（CC single agent）

```
configs/.claude-single/
  settings.json              # { "agent": "famou-single" }
  frontmatter/
    famou-single.txt         # CC sub-agent frontmatter（名称/工具/描述）
```

`settings.json`：
```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "agent": "famou-single"
}
```

`frontmatter/famou-single.txt`（参考 famou-build.txt 格式，全工具）：
```
---
name: famou-single
description: Famou Single Agent - 意图识别、澄清需求、规划与执行全流程
tools: [Read, Write, Edit, Bash, Glob, Grep, TodoWrite, TodoRead]
maxTurns: 100
---
```

#### `configs/.opencode-single/`（OpenCode single agent）

```
configs/.opencode-single/
  opencode.jsonc             # default_agent = "famou-single"，全工具权限
  frontmatter/
    famou-single.txt         # OpenCode frontmatter（可为空或加 description/mode）
```

`opencode.jsonc`：
```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {},
  "default_agent": "famou-single",
  "agent": {
    "famou-single": {
      "thinking": { "type": "enabled", "budgetTokens": 20000 },
      "permission": {
        "bash": "allow",
        "edit": "allow",
        "write": "allow",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "todowrite": "allow",
        "todoread": "allow",
        "task": "deny"
      }
    }
  }
}
```

`frontmatter/famou-single.txt`（参考 famou-build 的 OpenCode frontmatter）：
```
---
description: Single Agent - 意图识别、澄清需求、规划与执行全流程
---
```

### 3. Prompt 文件

```
prompt_variants/
  baseline/
    famou-master.md      # 现有（不变）
    famou-build.md       # 现有（不变）
    famou-single.md      # 新增：single agent 正文（CC 和 OpenCode 共用同一正文）
```

CC 和 OpenCode 的 single agent 共用同一份 `famou-single.md` 正文，只通过各自的 frontmatter 控制平台差异（工具列表、权限等）。

### 4. `run_b3.py` / `run_b2.py`：注册新 runner

```python
_DEFAULT_AGENT_CONFIG: dict[str, Path | None] = {
    "cc_native":        None,
    "cc_famou":         _CONFIGS_DIR / ".claude",
    "cc_single":        _CONFIGS_DIR / ".claude-single",    # 新增
    "opencode_native":  None,
    "opencode_famou":   _CONFIGS_DIR / ".opencode",
    "opencode_single":  _CONFIGS_DIR / ".opencode-single",  # 新增
}
```

### 5. `factory.py`：注册 runner 类

```python
_REGISTRY = {
    "cc_native":        NativeCCRunner,
    "cc_famou":         CCFamouRunner,
    "cc_single":        CCFamouRunner,       # 复用，配置不同
    "opencode_native":  OpenCodeNativeRunner,
    "opencode_famou":   OpenCodeACPRunner,
    "opencode_single":  OpenCodeACPRunner,   # 复用，配置不同
}
```

**新 runner 类型不需要写新代码**，完全复用现有 runner，只是注入不同的 config 目录。

---

## Prompt Variant 支持

与双 agent 机制完全一致，继承逻辑：`variant/ → baseline/`

```bash
# 使用 baseline 版 famou-single.md
python -m runners.run_b3 --case city_delivery_routing --runner cc_single

# 使用 v2 版 famou-single.md（只需在 prompt_variants/v2/ 下放 famou-single.md）
python -m runners.run_b3 --case city_delivery_routing --runner cc_single --prompt-variant v2
```

`prompt_variants/v2/famou-single.md` 不存在时自动 fallback 到 `baseline/famou-single.md`。

---

## 实现顺序

1. **改 `agent_builder.py`**：`assemble_agents` 从 `frontmatter/` 自动发现 agent 名称（去掉硬编码 `AGENT_NAMES`），验证 cc_famou 不受影响
2. **创建配置目录**：`configs/.claude-single/` 和 `configs/.opencode-single/`
3. **写 prompt 正文**：`prompt_variants/baseline/famou-single.md`（内容待定，可先 placeholder）
4. **注册 runner**：更新 `run_b3.py`、`run_b2.py`、`factory.py`
5. **更新 README**：runner 表格加 `cc_single` / `opencode_single`
