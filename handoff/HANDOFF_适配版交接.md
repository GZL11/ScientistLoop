# 适配版前端交接说明

> 目标：将 autoresearch-demo 的前端 UI 适配到 famou-scientist（opencode 后端），替换 opencode 原生 React 前端。

---

## 1. 要交接的文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `index.html` | `famou-scientist/famou_scientist/assets/web/static_adapted_backup/index.html` | 适配版前端（2971 行，单文件 CSS+HTML+JS） |
| `adapter.py` | `famou-scientist/famou_scientist/assets/web/adapter_backup.py` | Flask 协议翻译层（551 行） |
| **对照原版** | `PRDdraft/autoresearch-demo/static/index.html` | 原版前端（3145 行） |
| **对照原版** | `PRDdraft/autoresearch-demo/server.py` | 原版后端（631 行） |

---

## 2. 架构差异

### 原版（autoresearch-demo）

```
浏览器 ──→ server.py (Flask, 端口 5050)
              ├── /api/sessions/*/send  → 千帆 OpenAI API 直连（qwen3-vl-235b）
              ├── /api/agent/sessions/* → WebAgent 后端 (localhost:8765)
              └── /api/topo/*           → TopoManager（拓扑探索引擎）
```

- `callSessionLLM` → 千帆 LLM 直连，server.py 内部调 `client.chat.completions.create(stream=True)`
- `callAgentLLM` → WebAgent 后端，server.py 转发到 `localhost:8765`
- 有独立的 `agentSessionId`，和 `currentSessionId` 分开管理

### 适配版（famou-scientist）

```
浏览器 ──→ adapter.py (Flask, 端口 5050)
              ├── /api/sessions/*/send   → 转发到 agent_send_message（同下）
              ├── /api/agent/sessions/*  → opencode API (经 server.mjs 代理)
              └── 无 /api/topo/*
```

```
adapter.py ──→ server.mjs (端口 4096, Node 代理)
                  └──→ opencode serve (端口 4097, Go 后端)
```

- `callSessionLLM` 和 `callAgentLLM` **都走同一条路**：adapter.py → opencode agent
- 无独立 `agentSessionId`，统一用 `currentSessionId`
- adapter.py 核心工作：**SSE 协议翻译**（opencode 的推送式全局 EventSource → 前端期望的逐请求 SSE 流）

---

## 3. 核心功能差异

### 3.1 Session 管理

| | 原版 | 适配版 |
|---|---|---|
| 会话 session | `currentSessionId`（server.py 管理，磁盘持久化） | `currentSessionId`（opencode 管理） |
| Agent session | **独立** `agentSessionId`（WebAgent 管理） | **无**，复用 `currentSessionId` |
| 创建 agent session | `createAgentSession()` 调 `/api/agent/sessions`，传 `runner_type` + `model` | 删除了 `createAgentSession()`，`callAgentLLM` 直接用 `currentSessionId` |

### 3.2 callSessionLLM（LLM 直连）

| | 原版 | 适配版 |
|---|---|---|
| 路由 | `/api/sessions/${sid}/send` → server.py 调千帆 | 同路由 → adapter.py 转发到 `agent_send_message` → opencode agent |
| 实际后端 | 千帆 qwen3 直连 | opencode agent（模型由 opencode 配置决定） |
| 错误处理 | 无 try-catch | 有 try-catch + throw |
| SSE 注释行 | 不跳过 | 跳过 `': '` 开头的行（keepalive） |

**影响**：Deep Research 的 plan 生成原本走千帆 LLM 快速出 JSON，适配版走 opencode agent（更重、更慢，可能有工具调用干扰）。

### 3.3 callAgentLLM（Agent 调用）

| | 原版 | 适配版 |
|---|---|---|
| Session | 用 `agentSessionId`（独立） | 用 `currentSessionId` |
| 创建 | 自动调 `createAgentSession()` | 不需要，session 已存在 |
| 错误时 | `agentSessionId = null` 重置 | 不重置（统一 session） |
| 错误处理 | 无 try-catch | 有 try-catch + onError |

### 3.4 Deep Research 流程

**流程一致**：用户点"深度研究" → 输入主题 → LLM 生成 plan JSON → 渲染 Plan Card → 用户确认 → Agent 执行。

**差异在于**：

```
原版流程：
  1. callSessionLLM → 千帆 LLM 直连 → 快速出 plan JSON
  2. renderPlanCard → 用户确认
  3. runAgentTask → callAgentLLM → WebAgent 执行

适配版流程：
  1. callSessionLLM → adapter → opencode agent → 出 plan JSON（慢，可能带工具调用）
  2. renderPlanCard → 用户确认
  3. runAgentTask → callAgentLLM → adapter → opencode agent 执行
```

Plan Card 的 `renderPlanCard`、`confirmPlan`、`cancelPlan`、`togglePlanEdit`、`runAgentTask` 函数逻辑**完全一致**，无改动。

### 3.5 Plan 编辑模式

两版都有 `isPlanEditing` + `clearEditContext`，逻辑一致：用户点"编辑"后输入调整意见 → `callSessionLLM` 让 LLM 输出新 plan JSON → 重新渲染 Plan Card。

### 3.6 runDeepResearch（自动化深度研究）

两版都有 `runDeepResearch(topic)` 函数（原版 line 1373，适配版 line 1202），逻辑一致：
- 隐藏轨迹 tab，切到证据链
- 三阶段：文献检索 → 精读分析 → 综合报告
- 各阶段调 `callLLM` 生成内容
- 自动创建 sources、artifacts

---

## 4. 删除/缺失的功能

### 4.1 拓扑探索引擎（Topo）

原版有完整的拓扑探索功能（`/api/topo/*` 共 10 个路由 + `topo_engine.py`），适配版**完全删除**。

### 4.2 runAutoResearch / runAutoResearchSimulated

原版有 `runAutoResearch(topic)`（line 2104）和 `runAutoResearchSimulated(topic)`（line 2237），适配版**删除了这两个函数**。`confirmPlan` 中的 `intent === 'auto_research'` 分支仍存在但无法触发。

### 4.3 createAgentSession

原版有独立的 `createAgentSession()` 函数，传 `runner_type: 'opencode_famou', model: 'sonnet'`。适配版删除了，agent 调用直接复用 `currentSessionId`。

### 4.4 Bench 文件管理（部分）

原版有 `benchTableHTML`、`renderBenchCards`、`openBenchFile`、`closeBenchPreview`、`maximizeBenchPreview` 等函数。适配版保留了大部分但有简化。

### 4.5 Topbar 标题

原版 topbar 显示 "AutoResearch"，适配版**清空 topbar**（只保留 actions 按钮）。

---

## 5. 新增/增强

### 5.1 错误处理

适配版在所有关键函数加了 try-catch：
- `createSession()` — HTTP 状态检查 + session_id 空值检查
- `callAgentLLM()` — fetch try-catch + 非 ok 状态处理 + stream try-catch
- `callSessionLLM()` — fetch try-catch + 非 ok 状态处理 + stream try-catch + 跳过 SSE 注释行
- `sendMessage()` — 整体 try-catch，catch 中清理 indicator + 显示错误 div

### 5.2 SSE 注释行跳过

适配版的 `callSessionLLM` 和 `callAgentLLM` 都加了 `if (line.startsWith(': ')) continue;`，跳过 adapter 发的 keepalive 注释。

---

## 6. adapter.py 协议翻译详解

### 核心难点：SSE 翻译

opencode 的 SSE 是**全局推送流**（`GET /oc/event`），所有 session 的事件混在一起。前端期望的是**逐请求 SSE**（POST 发消息 → 该请求的 Response 就是 SSE 流）。

adapter.py 的 `agent_send_message` 做的事：

```
1. 启动后台线程监听 GET /oc/event（全局 SSE）
2. 等 SSE 连接就绪（threading.Event 同步）
3. POST /oc/session/:sid/prompt_async（发送用户消息，fire-and-forget）
4. 从事件队列中取事件，按 sessionID 过滤
5. 翻译事件格式：
   - message.part.updated (type=text)  → 计算文字增量 → {type:"text", content:delta}
   - message.part.updated (type=reasoning) → {type:"info", content:delta}
   - message.part.updated (type=tool, running) → {type:"tool_call", ...}
   - message.part.updated (type=tool, completed) → {type:"tool_result", ...}
   - session.idle → {type:"done"}
   - session.error → {type:"error", ...}
6. 结束后关闭 SSE 连接
```

### 已知 Bug（未解决）

**SSE 长行拆断**：`iter_lines(chunk_size=512)` 在遇到大 JSON（如 `message.part.updated` 含完整文本）时会拆断数据行，导致 JSON 解析失败。**文本事件全部丢失，前端无输出。**

最新修复（在 `adapter.py` 中，但 backup 里可能不是最新版）：改用 `iter_content(chunk_size=8192)` + 手动按 `\n` 拆行 + 累积多个 `data:` 行。

### 文字增量计算

opencode 的 `message.part.updated` 事件每次发送**全量文本**（不是增量）。adapter 维护 `text_state[part_id]` 记录上次文本，计算 `delta = current[len(prev):]` 发送增量给前端。

---

## 7. API 路由对照

| 路由 | 原版 server.py | 适配版 adapter.py |
|------|---------------|------------------|
| `POST /api/sessions` | 创建 session（磁盘持久化） | → `POST /oc/session` |
| `GET /api/sessions` | 列出 sessions | → `GET /oc/session?roots=true` |
| `GET /api/sessions/:sid` | 获取消息 | → `GET /oc/session/:sid/message` + 格式翻译 |
| `POST /api/sessions/:sid/send` | **千帆 LLM 直连** SSE | → `agent_send_message`（走 opencode agent） |
| `POST /api/agent/sessions` | 创建 agent session（发到 WebAgent） | → `POST /oc/session` |
| `POST /api/agent/sessions/:sid/send` | 转发到 WebAgent SSE | → opencode `prompt_async` + SSE 翻译 |
| `GET /api/agent/sessions/:sid/file` | 转发到 WebAgent | → `GET /oc/file/content` 或 `/raw` |
| `GET /api/agent/status` | 检查 WebAgent 在线 | → `GET /oc/config` |
| `/api/topo/*` (10 个路由) | 拓扑探索引擎 | **不存在** |

---

## 8. 依赖

| | 原版 | 适配版 |
|---|---|---|
| Python | flask, flask-cors, openai, requests | flask, flask-cors, requests |
| 外部服务 | 千帆 API（`qianfan.baidubce.com`）+ WebAgent (`localhost:8765`) | opencode serve + server.mjs |
| Node.js | 不需要 | 需要（server.mjs 代理） |

---

## 9. 快速上手

### 跑原版（确认功能正常）

```bash
cd PRDdraft/autoresearch-demo && python server.py
# 浏览器开 http://localhost:5050
```

### 跑适配版（需要 famou-scientist 环境）

```bash
cd famou-scientist && famou-scientist web
# 浏览器开终端提示的端口（默认 4096）
# 适配版前端在 static_adapted_backup/，需要手动配置 adapter
```

---

## 10. 待解决问题

1. **SSE 长行解析**：adapter.py 的 SSE 解析器需要用 `iter_content` + 手动拆行（不能用 `iter_lines`），否则大 JSON 事件会丢失
2. **Plan 生成走 agent 太重**：`callSessionLLM` 原本直连千帆出 plan JSON 很快，现在走 opencode agent 可能慢且带副作用（工具调用）。考虑是否需要保留一条千帆直连通道专门用于 plan 生成
3. **session.error 处理**：opencode 的 `session.error` 事件需要翻译给前端，否则错误静默
4. **缺少 agentSessionId 独立管理**：原版 agent session 出错时会重置 `agentSessionId = null` 并新建。适配版统一用 `currentSessionId`，没有这个容错机制
