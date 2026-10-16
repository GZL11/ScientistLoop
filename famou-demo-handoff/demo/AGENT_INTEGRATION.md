# AutoResearch Demo — Agent后端对接记录

> 更新时间：2026-06-23

## 架构

```
用户浏览器 (localhost:5050)
  │
  ├── 普通对话/Deep Research → Flask server.py → 千帆API (qwen3-vl-235b)
  │
  └── AutoResearch → Flask代理 → WebAgent FastAPI (localhost:8765) → OpenCode → API
```

## 两条链路

| 链路 | 触发条件 | 后端 | 模型 |
|------|---------|------|------|
| **千帆直连** | 普通对话 / Deep Research | Flask → OpenAI SDK → 千帆 | qwen3-vl-235b-a22b-thinking |
| **Agent代理** | AutoResearch（Plan Card确认后） | Flask → WebAgent → OpenCode | 由OpenCode配置决定 |

## 代理路由（server.py新增）

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/agent/status` | GET | 检查WebAgent是否在线 |
| `/api/agent/sessions` | POST | 创建agent session |
| `/api/agent/sessions` | GET | 列出agent sessions |
| `/api/agent/sessions/:id/send` | POST | 发送消息（SSE流式代理） |
| `/api/agent/sessions/:id/messages` | GET | 获取消息历史 |
| `/api/agent/sessions/:id/files` | GET | 列出workspace文件 |
| `/api/agent/sessions/:id/trace` | GET | 获取执行trace |

## SSE事件格式（从WebAgent透传）

```
event: text
data: {"type": "text", "content": "回复文本", "tool": "", "tool_input": "", "is_error": false}

event: tool_call
data: {"type": "tool_call", "content": "", "tool": "bash", "tool_input": "python analyze.py", "is_error": false}

event: tool_result
data: {"type": "tool_result", "content": "执行结果...", "tool": "", "tool_input": "", "is_error": false}

event: info
data: {"type": "info", "content": "[step] reason=stop tokens: in=3 out=7", "tool": "", "tool_input": "", "is_error": false}

event: done
data: {"status": "ok"}
```

## 前端处理（index.html新增）

### callAgentLLM(message, callbacks)
- 创建agent session → 通过`/api/agent/sessions/:id/send`发送消息
- 解析SSE事件流，分发到callbacks：
  - `onText(fullText, chunk)` — 文本回复
  - `onToolCall(tc, allCalls)` — 工具调用（渲染为可折叠卡片）
  - `onToolResult(content)` — 工具结果
  - `onInfo(content)` — 状态信息（token统计等）
  - `onDone(fullText, toolCalls)` — 完成
  - `onError(error)` — 错误

### runAutoResearch(topic)
- Agent在线 → 走真实agent后端，实时渲染工具调用+文本回复
- Agent离线 → Fallback到LLM模拟模式（runAutoResearchSimulated）

## 启动步骤

```bash
# 1. 启动WebAgent后端
cd /path/to/webagent
ANTHROPIC_API_KEY="sk-xxx" python -m webagent.runners.ui.server
# → http://localhost:8765

# 2. 启动AutoResearch Demo
cd /path/to/autoresearch-demo
python3 server.py
# → http://localhost:5050
# 启动时会自动检测WebAgent状态
```

## OpenCode配置

API配置在 `~/.config/opencode/opencode.jsonc`：
```json
{
  "provider": {
    "anthropic": {
      "options": {
        "baseURL": "http://211.23.3.237:27544/v1"
      }
    }
  }
}
```
环境变量：`ANTHROPIC_API_KEY=<你的 ANTHROPIC_API_KEY>`
