# Famou 研究台（web 前端）

Famou-scientist 的研究专用 Web 界面：聊天交互 + 实时思考过程 + 研究产物文件查看。
后端就是 `opencode serve`（注入了 AGENTS.md / tool / skill / hook），前端零构建，浏览器直连。

## 启动

```bash
famou-scientist web
# → 起后端 opencode serve(内部 :4097) + 前端(对外 :4096)，自动开浏览器
# 浏览器打开 http://localhost:4096
```

参数：

```bash
famou-scientist web --port 8080      # 前端对外端口（默认 4096）
famou-scientist web --oc-port 4099   # 后端内部端口（默认 4097）
famou-scientist web --host 0.0.0.0   # 前端对外可达（默认 127.0.0.1 仅本机；会话含对话内容，谨慎）
famou-scientist web --no-open        # 不自动打开浏览器
```

## 它做什么

- **左栏 会话管理**：`＋ 新对话` 开一个新研究（独立会话）；多个研究纵向切换，
  后台会话推进时其条目上有 busy 指示；可删除会话
- **中栏 聊天**：给研究助手主题（如"研究 dropout 对小数据集过拟合的影响"），
  实时看它的**工具调用卡片**（load skill、arc_search_literature、arc_run_experiment…）、
  思考过程、流式回复
- **右栏 本次科研**（ResearchPanel）：
  - **7 阶段轨迹**（产物驱动）：文献→假设→设计→代码→结果→论文→核验，
    对应产物文件出现即点亮该节点，点击查看
  - **本 run 文件树 + 内容查看**：只展示当前这次科研的 `research-runs/<主题>/` 产物

### run 目录怎么和会话绑定

OpenCode 不会主动告诉前端 agent 把 run 命名成什么。前端**从当前会话的 write/edit
工具调用里抽取**：agent 按 AGENTS.md 写 `research-runs/<主题>/…` 时，前端正则
提取 `research-runs/([^/]+)/` 即得本次 run 目录。自动绑定，无需 agent 额外配合。

> 7 阶段是**软节点**：agent 可能跳过某阶段（如纯文献综述不写实验），节点保持灰色，
> 忠实反映实际产物——这正是"产物驱动"而非"猜 stage"的好处。

## 架构（零构建）

```
浏览器 (localhost:4096)
  │ React + react-markdown + Babel —— 全部经本机服务器的 CDN 镜像加载（浏览器只连 localhost）
  │ 无 npm install、无打包步骤
  ├─ POST /oc/session                    建会话
  ├─ POST /oc/session/:id/prompt_async   发消息(立即返回)
  ├─ GET  /oc/event (SSE)                实时思考流 → 渲染 timeline
  ├─ GET  /oc/file, /oc/file/content     研究产物
  └─ GET  /_esm/* , /_unpkg/*            依赖镜像（server.mjs 回源 esm.sh/unpkg 并落盘缓存）
       ↓ server.mjs (Node 原生 http：静态服务 + /oc 代理 + CDN 镜像，内部 :4097)
opencode serve (127.0.0.1:4097)
       由 famou-scientist web 注入 OPENCODE_CONFIG_DIR / ARC_ROOT / ARC_PYTHON
       → 加载 AGENTS.md / skill / tool / hook（和 TUI 同一套能力）
```

`famou-scientist web`（`famou_scientist/web.py`）负责起这两个进程并守护：复用
`launcher.build_env()` 给后端注入资产环境，前端用随包分发的 `server.mjs`；Ctrl+C 或任一退出即收尾。
后端 cwd 沿用你当前工作目录，`research-runs/` 落在那里。

**为什么零构建**：受限网络下 npm install 装不上 vite/react。改用浏览器原生 ESM + import map +
Babel standalone 浏览器内转译，无需 node_modules。

**依赖怎么来（重要，跳板机关键）**：React / react-markdown / Babel 不让浏览器直连 CDN，而是经
`server.mjs` 的 **CDN 镜像**（`/_esm/*`→esm.sh、`/_unpkg/*`→unpkg）取——**浏览器只跟 localhost 说话**。
所以即使你 SSH 转发后在本地浏览器打开、本地访问不了 esm.sh/unpkg 也能加载；联网需求落在**运行
`famou-scientist web` 的那台机器**（它通常能联网，毕竟跑研究还要连模型/文献）。镜像结果**落盘缓存**
（默认 `$TMPDIR/famou-web-cdn`，可用 `FAMOU_WEB_CDN_CACHE` 改），重载秒开、warm 后近似离线，
也对 esm.sh 偶发抖动免疫。回源强制 IPv4（规避 Node 在某些环境 IPv6 卡死）。

## 文件

| 文件（`famou_scientist/assets/web/`） | 作用 |
|------|------|
| `server.mjs` | Node 原生 http：静态服务 + `/oc` 代理（含 SSE）+ `/_esm`·`/_unpkg` CDN 镜像（回源+缓存）；读 `PORT`/`HOST`/`OC_TARGET`/`FAMOU_WEB_CDN_CACHE` |
| `public/index.html` | import map(esm.sh) + Babel standalone 加载器 |
| `src/app.tsx` | 单文件 React 应用（client / Chat / Turn / ToolCall / ResearchPanel / App） |
| `src/styles.css` | 样式（深色三栏） |
| `loop-api.mjs` | Loop runtime 只读 API：状态、队列、产物、决策、经验池、报告、证据包 |

> 编排逻辑在包里的 `famou_scientist/web.py`，命令入口是 `famou-scientist web`。

## 配置点

- **模型**：`src/app.tsx` 顶部 `MODEL = { providerID, modelID }` 写死为
  `openai-compatible/claude-sonnet-4-6`。若你的 opencode 配的是别的 provider/model，
  改这一行即可（要和 `~/.config/opencode/opencode.jsonc` 里声明的 provider-id/model-key 对上）。
- **端口 / 绑定**：`--port` / `--oc-port` / `--host`（见上）。

## 范围

MVP = 多会话聊天 + 实时思考流 + 7 阶段轨迹 + 本 run 产物查看。
**后续可做**：论文实时预览、A/B/C 节奏选择器、gate approve/reject 按钮、心跳进度在前端可视化。

## Loop 只读面板

Loop runtime 的工作目录是：

```text
.famou/loop/<goal_id>/
```

Web 端不直接修改该目录，只通过 `server.mjs` 暴露的只读接口读取状态：

| 接口 | 用途 |
|------|------|
| `GET /loop/goals` | 列出当前项目下的 Loop goals |
| `GET /loop/status?goal_id=...` | ResearchState、队列摘要、评测预算 |
| `GET /loop/queues?goal_id=...` | 队列计数与队列项 |
| `GET /loop/artifacts?goal_id=...` | artifact index，支持 `type/offset/limit` |
| `GET /loop/artifact?goal_id=...&artifact_id=...` | 查看单个产物内容 |
| `GET /loop/decisions?goal_id=...` | 决策日志 |
| `GET /loop/clarifications?goal_id=...` | Master bridge 的澄清请求 |
| `GET /loop/experience?goal_id=...` | 共享经验池，支持 `type/q/offset/limit` |
| `GET /loop/report?goal_id=...` | status summary、final report、claim map |
| `GET /loop/evidence-bundle?goal_id=...` | evidence manifest 与证据包下载入口 |

安全边界：

- `goal_id` 只能是单层安全名称；
- artifact 的路径必须来自 `artifact_index.jsonl`，并且解析后仍在该 goal workspace 内；
- 额外拒绝通过 symlink 越过项目根目录的 goal workspace / artifact；
- 所有接口只支持 `GET`，Web 面板不承担 pause、stop、goal patch 等 master 控制职责；
- JSONL 末尾被并发写入时，暂时无法解析的最后一行会被跳过，并在响应中给出 `invalid_lines`。
