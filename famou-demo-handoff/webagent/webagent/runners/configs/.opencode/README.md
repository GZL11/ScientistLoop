# Famou Agent 使用指南

Famou 是运行在 opencode 上的双 agent 决策系统，面向排程、预测、资源优化等产业场景。
agentway 通过 `opencode acp` 协议启动 opencode，并加载本目录中的 agent 配置。

## Agent 架构

```
用户
 │  自然语言描述需求
 ▼
famou-master（Master Agent）
 │  澄清需求 → 生成 PLAN.md → task 委派
 ▼
famou-build（Builder Subagent）
 │  读取 PLAN.md → 执行求解 → 输出产物
 ▼
产物文件（数据表、HTML 图表等）
```

| Agent | 模式 | 职责 |
|---|---|---|
| `famou-master` | 对话 agent | 澄清需求、写 PLAN.md、验证产物 |
| `famou-build` | subagent | 求解执行、生成产物文件、验证约束 |

---

## 方式一：工作目录（项目级）

将 `.opencode/` 放在 **工作目录** 中，只对该目录下的会话生效。

### 目录结构

```
your-project/
├── .opencode/
│   ├── opencode.jsonc          # 权限配置（agent 工具权限）
│   └── agents/
│       ├── famou-master.md     # Master Agent 系统提示词
│       └── famou-build.md      # Builder Agent 系统提示词
├── data.csv
└── ...
```

### 步骤

将本仓库 `runner-ts/.opencode/` 完整复制到目标工作目录：

```bash
cp -r runner-ts/.opencode/ /path/to/your-project/
```

agentway 启动会话时会以该目录作为 `--cwd`，opencode 自动发现并加载 `.opencode/` 配置。

---

## 方式二：全局配置

将 agent 文件放入 opencode 全局配置目录，对所有工作目录生效（无需在每个项目中复制）。

### 目录结构

```
~/.config/opencode/
├── config.json                 # 全局配置（合并 agent 权限设置）
└── agents/
    ├── famou-master.md
    └── famou-build.md
```

### 步骤

```bash
# 创建目录
mkdir -p ~/.config/opencode/agents

# 复制 agent 提示词
cp runner-ts/.opencode/agents/famou-master.md ~/.config/opencode/agents/
cp runner-ts/.opencode/agents/famou-build.md  ~/.config/opencode/agents/

# 合并权限配置到全局 config.json（如已有 config.json，手动合并 "agent" 字段）
cp runner-ts/.opencode/opencode.jsonc ~/.config/opencode/config.json
```

全局配置后，无论工作目录在哪里，`famou-master` 和 `famou-build` 均可被 opencode 加载。

> **注意**：agentway 启动 opencode 时会设置 `XDG_CONFIG_HOME` 为会话隔离目录，全局配置在此情况下不生效。全局方式适用于直接运行 `opencode acp` 而非通过 agentway runner-ts 的场景。

---

## 通过 agentway 使用

正常使用时，通过 agentway API 创建会话，指定 `agent_type: "opencode"`：

```bash
curl -X POST http://localhost:8080/api/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "帮我做本周的生产排程，最小化总完工时间",
    "agent_type": "opencode",
    "config": { "source": "new", "autonomy": "Full" }
  }'
```

agentway 会自动以工作目录的 `.opencode/` 配置启动 `opencode acp`，并将请求路由到 `famou-master`。

---

## 后续交互

Master 执行完成后，当前工作目录下会生成产物文件，输出中包含：

| 场景 | 处理方式 |
|---|---|
| 局部修改 | 描述要改的部分 → Master 生成 PATCH.md，Builder 增量执行 |
| 目标改变 | 描述新目标 → Master 重写 PLAN.md，Builder 全量重跑 |
| 全新任务 | 描述新任务 → 旧 PLAN.md 归档为 `PLAN_v1.md`，重新开始 |

---

## 依赖

- `opencode` CLI 已安装（`npm install -g opencode-ai`）
- Python 环境 + `uv`（Builder 执行时自动管理 Python 依赖）
