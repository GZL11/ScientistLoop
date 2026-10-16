# OpenCode 轨迹观测工具（`famou-scientist trace`）

> 把一次 OpenCode 会话的**完整轨迹**导成干净的 JSONL，按 `session_id` 查询，便于复盘、调试、
> 分析 agent 到底每一步在干嘛（尤其"该 load 的 skill 有没有 load""工具的真实入参/结果是什么"）。
>
> 配套阅读：`docs/overview/ARCHITECTURE.md`（整体架构）、`README.md`（命令速查）。

---

## 0. 一句话

OpenCode 把会话持久化在一个 SQLite 库里；`famou-scientist trace` **只读**这个库，按真实时间序把
`session → message → part` 拼成一条线性轨迹，每个事件一行 JSON 输出。

```bash
famou-scientist trace                 # 列出最近会话，挑 session_id
famou-scientist trace <session_id>    # 导出该会话完整轨迹（JSONL → stdout）
```

---

## 1. 从 OpenCode 自身的轨迹存储出发

### 1.1 存在哪

OpenCode 用一个 **SQLite 数据库**保存所有会话（不是一堆 JSON 文件）：

```
~/.local/share/opencode/opencode.db        # 主库（上一次 checkpoint 时的快照——较旧的、已合并的状态 ）
~/.local/share/opencode/opencode.db-wal    # WAL（Write-Ahead Logging，预写日志，正在写的会话在这里）
~/.local/share/opencode/opencode.db-shm    # WAL 共享内存（共享内存索引,让读取方快速在 WAL 里定位每个 page 的最新版本）
```

路径遵循 XDG：实际取 `$XDG_DATA_HOME/opencode/opencode.db`，未设则回退 `~/.local/share/opencode/`。
也可用环境变量 `OPENCODE_DB` 显式指定（opencode 自身就读它）。

> 注意 WAL：最新的若干条消息可能还在 `-wal` 里没合并进主库。只读连接（见 §2.1）能正确读到
> WAL 中的数据，所以**不必停掉 opencode** 也能 trace 当前会话。

### 1.2 三张核心表

`opencode.db` 有 20 多张表（account/credential/project/permission/todo…），与"轨迹"直接相关的是三张，
逐层包含：

```
session  ──< message  ──< part
（一次会话）  （每条消息）   （消息内的各部分）
```

**`session`** —— 会话元信息（一行一个会话）：

| 关键列 | 含义 |
|--------|------|
| `id` | 会话 id，形如 `ses_131b8afd7ffe…`（trace 的查询键） |
| `title` | 会话标题（opencode 自动总结，如"SSVEP脑机接口研究"） |
| `directory` | 该会话的工作目录 |
| `parent_id` | **父会话 id**——subagent（`task`/reviewer 子 agent）的会话会指向发起它的主会话 |
| `agent` | `build`（主）/ `general` 等（子 agent 类型） |
| `model` | JSON 串，如 `{"id":"claude-sonnet-4-6","providerID":"…"}` |
| `cost` / `tokens_input` / `tokens_output` / `tokens_reasoning` / `tokens_cache_read` / `tokens_cache_write` | 成本与 token 统计 |
| `time_created` / `time_updated` | epoch 毫秒 |

**`message`** —— 每条消息（一行一条），`data` 是 JSON：

```jsonc
// data 字段
{ "role": "user" | "assistant",
  "time": { "created": 1781577240665 },
  "agent": "build",
  "model": { "providerID": "…", "modelID": "claude-sonnet-4-6" },
  "parentID": "msg_…",          // assistant 消息指向触发它的 user 消息
  "cost": …, "tokens": {…}, "finish": "stop" }
```

**`part`** —— 消息内的各部分（一条 assistant 消息通常有多个 part：先文本、再几个工具调用…），
`data` 是 JSON，按 `type` 区分。实测出现的类型：

| `type` | `data` 形状 | 说明 |
|--------|------------|------|
| `text` | `{type, text}` | 用户输入 / 模型可见回复文本 |
| `reasoning` | `{type, text}` | 思考型模型的推理过程（如有） |
| `tool` | `{type, tool, callID, state}` | **工具调用——轨迹里信息量最大的事件** |
| `step-start` | `{type, snapshot}` | 一个推理步开始（含工作区快照 hash） |
| `step-finish` | `{type, reason, tokens, cost, snapshot}` | 一步结束 + 该步 token/成本 |
| `patch` | `{type, hash, files}` | 这一步改动了哪些文件 |

**`tool` part 的 `state`** 是关键，包含工具的**入参、结果、耗时**：

```jsonc
"state": {
  "status": "completed",                       // 或 running / error
  "input":  { "query": "SSVEP", "limit": 5 },  // 工具入参（即 LLM 给的参数）
  "output": "found 5 papers …",                // 工具返回
  "metadata": {…},
  "time": { "start": 1781590010596, "end": 1781590010603 }  // 起止 → 耗时
}
```

### 1.3 排序：靠 `rowid`

`part` 行没有显式的序号列，但 SQLite 的隐式 `rowid` 随插入单调递增，且与 `time_created` 一致——
**按 `rowid` 排 `part` 就是真实发生顺序**（跨消息也成立）。这是 trace 拼线性轨迹的依据。

### 1.4 一次启动 ≠ 一个 session_id

- 一次 `famou-scientist`（OpenCode TUI）里，**每开一轮对话就是一个 `session`**，各有独立 `id`。
- `task` 工具起的 **subagent（如 code-plan-review / peer-review 的独立 reviewer）会另开子 `session`**，
  其 `parent_id` 指向主会话。所以一段研究的完整轨迹可能跨主会话 + 若干子会话。
- 因此工具需要：先 `--list` 找主会话 id，再用 `--include-children` 把子 agent 轨迹折叠进来。

---

## 2. 我们怎么设计的

目标：给一个 `session_id`，输出**人能扫、机器能解析**的完整轨迹——JSONL（每行一个独立 JSON 事件，
天然可 `grep` / `jq` / 流式处理）。实现是一个纯 stdlib（`sqlite3`+`json`+`argparse`，零第三方依赖）的
Python 模块 `famou_scientist/vis/trace.py`，挂成 `famou-scientist trace` 子命令（与 `doctor` 同构）。

### 2.1 只读、不打扰

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

`mode=ro` 只读打开：**不加写锁、不改库、不影响你正在跑的 opencode 会话**，还能正确读到 WAL 中尚未
合并的最新消息。这是"边跑边 trace"安全的前提。

### 2.2 拼轨迹的算法

```
1. 解析 session_id（精确命中；否则按前缀唯一匹配，多个则报错列出）
2. 读 message 表 → 建 message_id → {role, agent, ts} 索引（供每个 part 贴角色）
3. 读 part 表 ORDER BY rowid → 逐个规范化成事件 dict
4. （可选）对每个子会话（parent_id == 主 id）重复 2-3，附在后面
5. 每个事件 json.dumps 一行输出；开头先写一行 session 头
```

每个 `part` 按 `type` **规范化**成统一、扁平、好读的事件（而不是直接吐原始嵌套 JSON）：

| part type | 规范化后的事件字段 |
|-----------|-------------------|
| `text` / `reasoning` | `{i, t, role, kind, text}` |
| `tool` | `{i, t, role, kind:"tool", tool, call, status, input, output, ms, error?}` |
| `step-*` | `{i, t, kind:"step", phase, reason, tokens, cost}` |
| `patch` | `{i, t, kind:"patch", files, hash}` |

`ms = state.time.end - state.time.start`（工具耗时）；`role` 从所属 message 取（user/assistant）；
`i` 是事件序号，`t` 是 ISO 时间。

### 2.3 几个设计取舍

- **规范化优先，但保留逃生口**：默认输出规范化事件（清晰）；`--raw` 则每行吐原始 `part.data`，
  全保真，供需要完整字段时用。
- **JSONL 而非大 JSON 数组**：可流式、可 `grep`/`jq -c`、单行独立，超大会话（实测 212 条消息 →
  700+ 行）也不爆内存。
- **子会话默认不折叠**：`--include-children` 才拉子 agent，避免默认输出过载；每个会话各有一行
  `session` 头，子会话事件的 `session` 字段不同，便于区分/过滤。
- **step 噪声可关**：`--no-steps` 去掉 `step-start/step-finish`，只看"人类视角"的 text+tool+patch。
- **前缀匹配**：`session_id` 给前 10~12 位即可（唯一就命中）。
- **复用既有约定**：路径解析 `OPENCODE_DB > $XDG_DATA_HOME > ~/.local/share`；子命令分发沿用
  `cmdline.py` 里 `doctor` 那套位置参数风格。

### 2.4 输出 JSONL 的结构

第一行是 **session 头**，其后每行一个事件：

```jsonc
{"i":0,"kind":"session","session":"ses_131b…","title":"SSVEP脑机接口研究",
 "directory":"/…/research-runs/ssvep","agent":"build","model":"claude-sonnet-4-6",
 "parent":null,"created":"2026-06-13T…","updated":"2026-06-13T…",
 "messages":212,"cost":…,"tokens":{"input":…,"output":…,"reasoning":…,"cache_read":…,"cache_write":…}}
{"i":1,"t":"…","session":"ses_131b…","msg":"msg_…","role":"user","kind":"text","text":"帮我研究 SSVEP…"}
{"i":7,"t":"…","role":"assistant","kind":"tool","tool":"todowrite","call":"toolu_…","status":"completed","input":{"todos":[…]},"output":"…","ms":7}
{"i":11,"t":"…","role":"assistant","kind":"tool","tool":"skill","call":"…","status":"completed","input":{"name":"literature-search"},"output":"…","ms":170693}
```

---

## 3. 怎么用

### 3.1 列出会话（找 session_id）

```bash
famou-scientist trace                 # 等价于 trace --list
famou-scientist trace --list --limit 50
famou-scientist trace --list --directory ssvep   # 按工作目录子串过滤
```

输出（按最近更新排序，子会话标 `↳子`）：

```
SESSION ID                         MSGS  UPDATED              AGENT      TITLE
ses_131b8afd7ffehGhTuWUuxdXV3p       61  2026-06-16T15:02:37  build      AI助手身份介绍
ses_130e9027bffe3w5pTfvghRAZLJ        4  2026-06-16T14:22:23  general    代码保真审查 (subagent) ↳子
ses_14637bd2effeymAhEt9hmaKesK      212  2026-06-13T16:57:45  build      SSVEP脑机接口研究
```

### 3.2 导出某会话轨迹

```bash
famou-scientist trace ses_14637bd2effe                      # 前缀即可；JSONL → stdout
famou-scientist trace ses_14637bd2effe --include-children   # 连同 subagent 子会话
famou-scientist trace ses_14637bd2effe --out run.jsonl      # 写文件
famou-scientist trace ses_14637bd2effe --no-steps           # 去掉 step 噪声
famou-scientist trace ses_14637bd2effe --raw                # 每行原始 part.data（全保真）
```

### 3.3 全部参数

| 参数 | 作用 |
|------|------|
| `session_id`（位置参数，可前缀） | 要导出的会话；不给则列出最近会话 |
| `--list` / `-l` | 强制列会话后退出 |
| `--limit N` | `--list` 显示条数（默认 30） |
| `--directory STR` | `--list` 按工作目录子串过滤 |
| `--include-children` | 连同 subagent 子会话（`parent_id` 指向本会话的） |
| `--raw` | 每行输出原始 `part.data`，不规范化 |
| `--no-steps` | 不输出 `step-start`/`step-finish` |
| `--out FILE` | 写文件（默认 stdout） |
| `--db PATH` | 指定 `opencode.db`（默认 `OPENCODE_DB` → `$XDG_DATA_HOME/opencode` → `~/.local/share/opencode`） |

### 3.4 配合 `jq` 的常用查法

```bash
# 只看工具调用序列（谁、什么状态、耗时）
famou-scientist trace <sid> | jq -c 'select(.kind=="tool") | {i,tool,status,ms}'

# agent 到底 load 了哪些 skill、按顺序（skill 加载门复盘神器）
famou-scientist trace <sid> | jq -r 'select(.tool=="skill") | "\(.i)\t\(.input.name)"'

# 找跑实验的真实入参与结果
famou-scientist trace <sid> | jq 'select(.tool=="arc_run_experiment") | {input,output,ms}'

# 统计各工具调用次数
famou-scientist trace <sid> | jq -r 'select(.kind=="tool").tool' | sort | uniq -c | sort -rn

# 只看人类对话（user/assistant 文本，跳过工具）
famou-scientist trace <sid> --no-steps | jq -r 'select(.kind=="text") | "[\(.role)] \(.text)"'

# 哪些步骤改了文件
famou-scientist trace <sid> | jq -c 'select(.kind=="patch") | .files'
```

### 3.5 典型用途

- **复盘"为什么没按阶段 load skill"**：看 `tool=="skill"` 出现的位置——是不是写 `hypotheses.md`/
  跑实验之前漏了？（呼应 `guardrails.ts` 的 **skill 加载门**：load skill 本质就是这条
  `skill` 工具调用，门正是靠观测它做会话级跟踪。）
- **核对工具真实行为**：`arc_search_literature` 真查了什么 query、`arc_run_experiment` 的真实
  returncode/metrics、`arc_render_figure` 的体检结果——`input`/`output` 一目了然。
- **成本/性能分析**：按 `ms` 找最慢的工具调用；按 `step` 的 `tokens`/`cost` 看哪一步最烧 token。
- **离线归档**：`--out` 落盘一份 JSONL，会话被清理后仍可回看。

---

## 4. Web 可视化（`--web`）

CLI 出 JSONL 适合脚本，看对话流/工具入参结果用网页更直观。同一个 `trace` 子命令带 `--web`
即起一个**本地、纯 stdlib、零依赖、可离线**的轨迹查看页（深色终端风）。

### 4.1 起服务

```bash
famou-scientist trace --web                 # 起服务并自动打开浏览器（默认 http://127.0.0.1:8765）
famou-scientist trace --web --no-open       # 只起服务，不自动开浏览器（远程/无显示环境用）
famou-scientist trace --web --port 9000     # 换端口（被占用会自动 +1 连试 10 个）
famou-scientist trace --web --host 0.0.0.0  # 对外开放（会打印安全警告，见下）
famou-scientist trace --web --db /path/opencode.db   # 指定库
```

启动后终端会打印访问地址；`Ctrl-C` 停止。**不影响正在跑的 opencode**（只读，见 §2.1），
所以可以一边让 opencode 跑、一边开页面看（点「刷新」拉最新）。

### 4.2 页面布局

```
┌──────────────────────┬──────────────────────────────────────────────────────────┐
│ 🔭 famou-scientist    │  [ 粘 session_id（支持前缀）   ] [Load] [刷新]            │ ← 顶栏
│  · trace             │   ☐含子会话  ☑隐藏 step  [全部▾]  [文本内搜索…]           │
│ ┌──────────────────┐ ├──────────────────────────────────────────────────────────┤
│ │ 筛会话：id/标题…  │ │ 会话 1 · 消息 212 · 工具调用 162 · model … · cost …       │ ← 统计条
│ └──────────────────┘ ├──────────────────────────────────────────────────────────┤
│ ┌──────────────────┐ │ ╔══ 会话头：标题 / model / 目录 / 消息数 / cost / tokens ╗ │
│ │ ses_14637b…       │ │                                                          │
│ │ SSVEP脑机接口研究 │ │  #1 [user]  你好，帮我研究 SSVEP……                       │ ← 对话气泡
│ │ 212 msgs·build    │ │  #2 [assistant]  好方向！我们先……                        │
│ ├──────────────────┤ │  #7 ▸ todowrite   ✓completed        7 ms                  │ ← 工具卡
│ │ ses_130e90… ↳子   │ │  #11 ▸ skill  load: literature-search ✓  170693 ms       │   (折叠 in/out)
│ │ 代码保真审查      │ │  #12 ▸ arc_search_literature ✓  10 ms                    │
│ │ 4 msgs·general    │ │      ├ input  { "query": "SSVEP", "limit": 8 }           │
│ └──────────────────┘ │      └ output { …真实返回… }                             │
│   （← 会话列表）      │  · step-finish  tok in…/out…  cost …      (可隐藏)        │ ← step 行
└──────────────────────┴──────────────────────────────────────────────────────────┘
       左侧栏                                  主区时间线
```

- **左侧栏**：最近会话列表（按更新时间倒序）。顶部框按 id/标题/目录**即时筛**；子会话标 `↳子`；
  **点任意一条即加载**其轨迹（也会自动填进顶栏输入框）。
- **顶栏**：粘 `session_id`（**支持前缀**，给前 10~12 位即可）回车或点 `Load`；`刷新` 重拉当前会话
  （手动刷新，opencode 跑出新内容后点一下即可）。右侧是过滤开关（见 §4.4）。
- **统计条**：当前展示的会话数 / 消息数 / 工具调用数 / model / 总 cost，一眼看规模。
- **主区时间线**：按真实时间序（§1.3 的 `rowid`）从上到下排，事件卡见 §4.3。

### 4.3 时间线上的事件卡

| 事件 | 呈现 |
|------|------|
| **会话头** | 高亮框：标题、`session_id`、model、目录、消息数、cost、tokens（含子会话时每个会话各一张，子会话标「↳ 子会话」） |
| **对话**（user/assistant） | 气泡，user 蓝、assistant 绿区分；正文 `pre-wrap` 保留换行 |
| **工具调用** | 可折叠卡：工具名 + 状态徽章（`completed` 绿 / `error` 红）+ 耗时 `ms`；展开看 `input`（LLM 给的真实入参）和 `output`（真实返回），JSON 美化 |
| **skill 加载** | 工具卡的特例，**紫色高亮**且默认展开，徽章直接显示 `load: <skill 名>`——专门方便复盘"该 load 没 load"（§3.5） |
| **step** | 暗色紧凑行（该步 tokens/cost），默认隐藏，可开 |
| **patch** | 虚线框，列出这一步改动的文件路径 |

### 4.4 顶栏控件

| 控件 | 作用 |
|------|------|
| session_id 输入 + `Load` | 按 id（可前缀）加载；回车等同 Load |
| `刷新` | 重新拉当前会话（手动；不自动轮询） |
| ☐ **含子会话** | 勾上则把 subagent 子会话（`parent_id` 指向当前会话）一并拉来、各自成块（切换会重新加载） |
| ☑ **隐藏 step** | 去掉 `step-start/step-finish` 噪声，只看对话+工具+patch（默认开） |
| **类型过滤**（全部 / 仅工具 / 仅对话） | 只看某类事件 |
| **文本内搜索** | 在已加载事件里按文本即时过滤（匹配整条事件的 JSON，工具名/入参/输出/正文都算） |

> 类型过滤、隐藏 step、文本搜索都是**前端即时过滤**（不重新请求）；只有「含子会话」会重新拉数据。

### 4.5 实现与安全

- 后端 `famou_scientist/vis/trace_web.py`：`http.server.ThreadingHTTPServer`，端点 `/`（前端页）、
  `/api/sessions`、`/api/trace`；数据逻辑**全复用 `trace.py`**，每请求新开只读连接（连接非线程安全）。
- 前端 `famou_scientist/vis/trace_viewer.html`：单文件 vanilla JS/CSS，**无构建、无外链**（断网可用）；
  所有会话内容一律 `textContent` 注入、绝不 `innerHTML` 拼，**防 XSS**。
- **安全**：默认绑 `127.0.0.1`（仅本机）。`--host 0.0.0.0` 会把会话内容（含完整对话）对同网段开放，
  启动时会打印警告——仅在你清楚的可信内网用。后端只读，不写库、不扰 opencode。

---

## 5. 实现位置 / 边界

- 代码：`famou_scientist/vis/trace.py`（CLI + 数据逻辑，纯 stdlib）、`famou_scientist/vis/trace_web.py`（web 服务）、
  `famou_scientist/vis/trace_viewer.html`（前端）；子命令分发在 `famou_scientist/cmdline.py`；
  单测 `famou_scientist/tests/test_trace.py`、`test_trace_web.py`（合成临时库验排序/tool/前缀/子会话 + HTTP 端点）。
- **只读**：绝不写 `opencode.db`；安全地在 opencode 运行时使用。
- **依赖 OpenCode 的库结构**：schema 由 OpenCode 维护，未来大版本若改表结构，需同步调整
  `trace.py` 里读的列/字段（目前读的是 `session`/`message`/`part` 的稳定字段）。
- **不含敏感库表**：只读 `session/message/part`，不碰 `account/credential`（凭证）等。
