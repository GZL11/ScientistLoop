# Famou Scientist 前端与 Agent 行为逻辑说明

> 本文描述 2026-08-10 代码中的**实际行为**，不是理想方案。重点回答三个问题：前端做什么、OpenCode/后端做什么、哪些逻辑真的会改变 Agent 的执行。

## 1. 先说结论

前端本身不运行 Agent，也不决定 Agent 应该如何做科研。

前端的主要职责是：

1. 把用户消息、附件路径、模型选择和交互结果提交给 OpenCode；
2. 接收 OpenCode 的实时事件，并把正式回答流式显示出来；
3. 把回答、工具调用、实验进度和文件分别放到合适的区域；
4. 在刷新、断线或漏事件后，重新拉取服务端真实状态；
5. 展示并回复会阻塞 Agent 的问题和权限请求。

真正控制 Agent 研究方式的主要是 OpenCode、`AGENTS.md`、skills、hooks/plugins 和 tools。前端只有在**主动拼接提示词、选择模型、回复 question/permission、停止会话**时，才会直接影响 Agent 行为。

可以把整体关系理解为：

```text
用户
  |
  v
浏览器前端 app.tsx
  |  提交消息 / 回复问题 / 停止
  v
Web 服务 server.mjs（代理、cwd 绑定、文件接口）
  |
  v
OpenCode（保存 session、运行 Agent、调用模型和工具）
  |
  +--> tools / skills / AGENTS / plugins
  |
  +--> SSE 实时事件 --> 前端聊天区 / 进程区
  |
  +--> session cwd 中的文件 --> 前端 Workspace
```

## 2. 四个容易混淆的概念

### 2.1 Session

一次独立对话。消息历史、运行状态、Agent 工具调用和 cwd 都挂在 session 上。

### 2.2 Project

前端的项目分组，用于组织 session 和项目初始文件。项目、session 归属、手动标题等信息持久化在后端 `.famou/project-state.json`，浏览器 `localStorage` 只作为缓存和旧数据迁移来源。

需要注意：**当前 Project 归属不会自动改变 Agent 的 cwd，也不会自动把 Project 初始文件复制进新 session。** 因此，目前“同一 Project 下的新对话”主要表示 UI 分组关系，不等于 Agent 自动继承该项目的文件上下文。

### 2.3 Session cwd

Agent 实际工作的目录，也是右侧 Workspace 应当展示的根目录。

创建 session 时，`server.mjs` 会在 `.famou/workspaces/` 下分配一个独立目录，并在里面执行 `git init`。这样 OpenCode 不会误把上层 Famou 仓库识别为工作目录。

当前约束是：

```text
Agent cwd = OpenCode session.directory = 前端 Workspace 根目录
```

消息里出现的路径只能触发刷新或打开文件，不能改变 Workspace 根目录。

### 2.4 Research run

Agent 通常在 session cwd 下创建 `research-runs/<run-name>/` 保存某次研究的过程文件和交付物。

前端当前会从 `research-runs/` 下选择排序后的最后一个目录作为“活动 run”。这只是目录推断，不是 Agent 或后端明确声明，存在选错 run 的风险。

## 3. 一条普通消息如何执行

### 第一步：确定 session

用户已有当前 session 时直接使用；没有 session 时，前端先调用 `POST /oc/session` 创建一个。

创建请求经过 `server.mjs` 后，会先分配独立 workspace，再把该目录作为 `directory` 和 `x-opencode-directory` 传给 OpenCode。

### 第二步：前端立即显示用户消息

前端先插入一个本地“乐观消息”，用户无需等待网络返回就能看到自己发送的文字和附件。

这条本地消息只是显示反馈。OpenCode 保存的正式消息会在本轮结束或状态对账时替换它。

### 第三步：处理附件

附件不会直接作为大段二进制内容塞进 prompt。前端会：

1. 用浏览器 `FileReader` 读取文件；
2. 通过 `/upload` 写入当前 session cwd；
3. 把相对路径写进给 Agent 的文本；
4. 告诉 Agent 使用工具读取这些路径。

因此 Agent 实际收到的是“文件位于 `xxx.pdf`，请读取”，而不是 PDF 的 base64 内容。

普通附件目前串行上传；创建 Project 时选择的文件夹使用 2 到 4 个并发 worker，并支持 `AbortController` 取消。

### 第四步：异步提交给 OpenCode

普通消息调用：

```text
POST /oc/session/:sessionID/prompt_async
```

纯 Slash Command 调用：

```text
POST /oc/session/:sessionID/command
```

`prompt_async` 表示请求被 OpenCode 接收后浏览器即可返回，不需要保持一个 HTTP 请求直到 Agent 完成。Agent 在服务端继续运行，所以刷新浏览器不应中断生成。

### 第五步：接收实时事件

前端使用：

```text
EventSource(/oc/event?directory=<session cwd>)
```

订阅 OpenCode 的 SSE 事件。正式回答通过 `message.part.updated` 和 `message.part.delta` 进入聊天区。

### 第六步：本轮收尾

收到 `session.idle` 或明确的完成状态后，前端会：

1. 清除“运行中”；
2. 拉取正式消息做最终对账；
3. 刷新 Workspace；
4. 重新检查是否还有未回复的 question 或 permission。

## 4. 流式输出为什么不会再“出现后消失”

OpenCode 同时可能提供两类文本：

- `message.part.*`：已经进入正式消息的 canonical 内容；
- `session.next.*`：模型生成过程中的候选文本或 reasoning。

当前前端只把 `message.part.updated` 和 `message.part.delta` 放进聊天区。`session.next.text.*`、`session.next.reasoning.*` 只用于判断 Agent 仍有活动，不展示文本。

这样做是为了避免候选内容先显示、随后被模型或 OpenCode 改写，导致用户看到文字闪现、撤回或覆盖。

另外还有三层防抖：

1. delta 按浏览器动画帧批量追加，减少每个 token 都触发整页排版；
2. 已显示的流式文本不会被更短的 SSE 快照覆盖；
3. HTTP 对账期间如果收到更新的 SSE，旧 HTTP 快照不会覆盖新内容。

连续多条 assistant message 会合并成一个 `AssistantRun`。这是视觉分组，不会修改 OpenCode 保存的原始消息。

## 5. 聊天区、进程区和 Workspace 分别展示什么

### 5.1 聊天区

聊天区面向用户沟通，当前展示：

- 用户真实输入；
- Agent 的正式文本回答；
- Agent question 的已完成回答结果；
- Agent 生成的图片缩略图；
- 一轮结束后识别出的本轮产物卡片；
- 确认失败后的错误消息；
- 用户主动停止且该轮没有任何可见结果时的中止说明。

聊天区当前隐藏：

- reasoning；
- 普通工具调用卡片和工具原始输入输出；
- `[系统通知...]` 开头的心跳注入消息；
- OpenCode compaction 的内部 continuation 消息；
- compaction summary；
- 只有工具、没有用户可见文本或产物的 assistant message。

这里的原则是：**聊天区保留结论、关键说明和必须由用户处理的信息；内部执行细节进入进程区。**

“本轮产物”并不是扫描整个 Workspace 得到的。它只汇总同一个 `AssistantRun` 中已完成的 `write`/`edit` 和生图工具，并且只接受 `research-runs/` 下带常见交付物扩展名的文件。因此，一个文件可以已经存在于 Workspace，但因为不是本轮工具明确产出的，聊天区不一定出现对应卡片。

### 5.2 进程区

进程区从同一份 OpenCode 消息中提取工具 parts，展示：

- `todowrite` 形成的任务计划和完成数量；
- 检索、读写文件、实验、核验等工具调用；
- 工具的 pending、running、completed、error 状态；
- 展开后的工具输入和输出；
- `/process/progress` 返回的后台实验状态。

如果工具仍标记为 running，但 session 已经 idle，或者它不属于最后一条 assistant message，前端会把它视为孤立状态并显示“已中断”，避免永久转圈。

实验进度在进程区顶部只保留最新状态卡，历史心跳不会不断追加到聊天区。

进程区不会主动要求 Agent 创建任务计划或调用工具。用户一提问就出现细粒度阶段，说明 Agent 自己调用了 `todowrite` 或相关工具；前端只是把已有工具记录展开显示。

### 5.3 Workspace

Workspace 直接浏览 session cwd，而不是从聊天消息里的文件路径拼出一个虚拟文件列表。

刷新时有以下保护：

- 目录按需展开和缓存；
- 工具完成后延迟约 300 ms 刷新，等待文件落盘；
- 本轮结束时刷新根目录和已展开目录；
- Agent 忙碌期间，把新扫描结果与旧结果合并，避免短暂的不完整扫描让已有产物消失；
- 单次目录读取失败时尽量保留上一次成功内容。

默认隐藏：

- 点文件和 LaTeX 辅助文件；
- `venue`、`plan`、`notes` 等内部工作文件；
- `queries.jsonl`、`search_diagnostics.jsonl`、`rejected_papers.jsonl`、`claim_cards.jsonl`、`evidence_edges.jsonl` 等诊断材料。

诊断材料可以进入折叠的“后台诊断”，不应与用户交付物混在主文件树中。

界面会把回答中的真实路径前缀 `research-runs/` 显示成更容易理解的 `workspace/`。这只是文字遮罩，不会重命名磁盘目录，也不会改变 Agent 读取文件时使用的真实路径。

## 6. “运行中”状态如何判断

前端优先查询 OpenCode 的 `/session/status`，因为它是执行状态的权威来源。

如果当前 OpenCode 版本不提供可用状态，才退回到消息推断：最后一条 assistant message 没有 `time.completed`，则可能仍在生成。超过 30 分钟仍未完成的旧 assistant message 会被视为孤立/中断，避免刷新后永久显示运行中。

以下事件也会实时改变状态：

- delta、part 更新、step started：设为运行中；
- `session.status=busy/running/retry/waiting`：设为运行中；
- `session.idle/completed/done/error/failed/aborted/cancelled`：结束运行中状态。

当前没有“60 秒无输出就自动终止 Agent”的前端硬规则。

## 7. SSE 断线与状态补偿

SSE 负责实时，但网络断开期间的事件不会自动重放。因此前端还有 HTTP 补偿：

- 运行中每 4 秒检查一次是否漏掉 question/permission；
- 连续约 12 秒没有新的流式活动时，重新获取消息和 session status；
- 浏览器标签重新可见或窗口重新聚焦时，如果仍显示 busy，会再次对账；
- SSE 重连后也会对账。

这套逻辑只修复展示状态，不判断任务超时，也不主动结束 Agent 回合。

## 8. 错误和“服务暂无响应”如何处理

前端只在收到 OpenCode 的 `session.error` 后处理真实错误，不再根据固定无输出时长猜测失败。

由于 provider/router 可能先发瞬时错误、随后继续输出，前端会延迟约 1.8 秒：

1. 期间如果又收到正式文本、工具步骤或 idle，取消错误提示；
2. 延迟后再次查询真实 session 状态；
3. 只有确认不再运行时，才在聊天区显示失败并结束本轮。

因此，正常长实验或长工具调用不应仅因 60 秒没有聊天文本就被判失败。

## 9. 停止按钮的真实含义

用户点击停止后，前端调用 OpenCode 的 abort API。

前端会立即把界面设为不忙，并在 6 秒内忽略该轮迟到的 delta/step/error，避免按钮刚停止后又被旧事件顶回“运行中”。随后在约 0.4 秒和 1.5 秒各做一次对账，让最终状态收敛到 OpenCode 的真实记录。

显示“用户手动终止”必须以这次真实的前端停止操作为依据，不能因为超时、断线或工具失败而冒充用户终止。

## 10. Agent question 和 permission

这两类事件会真正阻塞 Agent：

### Question

Agent 使用 question 工具向用户提问时，OpenCode 暂停执行并发出 `question.asked`。前端显示居中的应用内问询卡，用户回答或跳过后，答案回传 OpenCode，Agent 继续。

### Permission

Agent 尝试受限路径或敏感操作时，OpenCode 发出 `permission.asked`。前端显示权限卡，用户可以单次允许、持续允许或拒绝。

刷新或切回 session 后，前端会通过 HTTP 找回尚未处理的问题和权限，不只依赖当时那一条 SSE。

有 question/permission 等待处理时，输入框仍可编辑以保留中文输入法内容，但发送会被阻止，直到当前阻塞项处理完毕。

## 11. Session 标题、模型和 Slash Command

### Session 标题

首条用户消息会先作为临时可读标题，最长 24 个字符。随后如果 OpenCode 产生摘要标题，`session.updated` 会替换临时标题。用户手动重命名后的标题优先级更高，并写入 project state。

因此“首 query”只是等待 OpenCode 自动命名时的兜底，不应成为最终命名策略。

### 模型选择

模型列表从 OpenCode `/config` 动态读取。用户选择后，下一条 `prompt_async` 会携带对应的 `providerID/modelID`；未解析出模型时不传 model，让 OpenCode 使用默认值。

这是前端会直接影响 Agent 的逻辑，因为它改变了实际调用的模型。

### Slash Command

只有整条消息符合 `/command arguments` 且没有附件时才按命令处理。命令必须走 OpenCode command API，不能作为普通 prompt 发送。

OpenCode 会把展开后的命令模板保存成 user message。前端另外保存原始命令显示文本，避免刷新后把内部模板暴露给用户。

## 12. 文献区的数据从哪里来

右侧文献区会识别四类来源：

1. Agent 产出的 `paper_cards.jsonl`，视为已经筛选的正式文献；
2. `seed_papers.jsonl`、`candidate_papers.jsonl` 等候选文件；
3. 已完成的 `arc_search_literature` 工具输出；
4. Agent 正式回答中可识别的标题、链接、DOI 和 arXiv ID。

当前优先级是：

```text
只要 paper_cards.jsonl 非空 -> 只展示 paper_cards
否则 -> 合并候选文件、工具输出和聊天文本
```

所以右侧文献可能比聊天区少。这不一定是漏解析，也可能是因为前端把 `paper_cards.jsonl` 当成“Agent 已筛选后的最终集合”。有正式卡片时显示“已筛选”，只有候选或聊天提取结果时显示“筛选中”。

这项策略会影响用户对研究覆盖度的判断，但不会改变 Agent 的检索行为。

## 13. 实验心跳和后台进度

心跳插件解决的是：Agent 一轮结束后会休眠，后台异步实验完成时需要有人重新唤醒它。

当前机制分三层：

### 13.1 定时扫描

插件默认每 60 秒扫描 `.famou_jobs/` 的状态文件。扫描本身不调用模型，不产生 token。

每个 running job 的实际检查会按 2 倍间隔退避，最大 2 小时。60 秒 tick 只是调度器醒来查看“哪些 job 到检查时间了”，不等于每分钟查询每个实验或调用 Agent。

### 13.2 普通运行进度

普通间隔进度只写入 job 的 `progress.json`。Web 后端 `/process/progress` 读取它，前端进程区约每 10 秒拉取并显示。

这类更新不会创建聊天消息，也不会调用模型。

运行期进度默认关闭；只有 job 显式声明 `progress_policy`，或环境变量显式设置固定间隔时才播报。策略可以按实验超时长度、自定义最小/最大间隔、时间 milestone、日志关键词和长时间无日志来调整。

### 13.3 何时唤醒 Agent

以下情况会用 `client.session.promptAsync()` 给原 session 注入内部系统通知：

- 实验完成或失败；
- 到达语义检查点；
- 长时间无新日志，需要 Agent 判断是否卡住。

普通定时间隔不会唤醒 Agent。唤醒前尽量等待 Agent 空闲；完成通知超过兜底时间仍未发送时会强制投递。跨插件实例用 claim/sent 文件去重，避免同一个 job 被重复通知。

内部通知会让 Agent 核验真实实验状态并继续决策，但前端通过 `[系统通知...]` 规则把原始通知从聊天区过滤掉。用户应该看到 Agent 后续给出的关键结论，而不是心跳原文。

## 14. 论文编译按钮目前如何工作

论文卡只有在活动 run 的 `deliverables/` 中发现 `.tex` 时才显示。

点击“编译”并不是直接调用前端 `/compile` 完成全部工作，而是向当前 session 发送一条隐藏的详细用户 prompt，让 Agent：

- 调用 `arc_latex_check`；
- 修复引用、图片、输入文件和 bibliography 问题；
- 重复编译到 PASS 或只剩 WARN；
- 生成 `paper.pdf` 并回复结果。

聊天区只显示简短的“请编译论文并修复所有编译问题，直到通过”，内部详细约束不会完整冒充用户文字。按钮提交后进入 waiting，变为不可点击；观察到 Agent 从 busy 回到 idle 后恢复。

**当前不一致：**隐藏 prompt 仍写着“拿不到会议类文件就降级到标准 article”。这与已经确定的“先获取官方模板、从源头解决环境/模板问题、不静默降级”原则冲突，应在后续修改运行逻辑时移除或改成明确询问用户。

## 15. 哪些前端逻辑真的影响 Agent

| 前端动作或逻辑 | 是否影响 Agent | 原因 |
| --- | --- | --- |
| 选择模型 | 是 | 改变下一轮实际调用的模型 |
| 发送普通消息 | 是 | 创建一个 Agent turn |
| 点击快捷动作 | 暂时否 | 只是预填输入框，用户发送后才影响 Agent |
| 点击论文编译 | 是 | 前端拼接隐藏 prompt 并创建 Agent turn |
| 上传附件 | 是 | 文件写入 Agent cwd，路径加入 prompt |
| 回复 question | 是 | 解除阻塞并把答案交给 Agent |
| 回复 permission | 是 | 决定工具操作能否继续 |
| 点击停止 | 是 | 调用 OpenCode abort |
| Slash Command | 是 | 走 OpenCode command API，执行命令模板 |
| 心跳完成/检查点通知 | 是 | plugin 用内部 prompt 唤醒 Agent |
| 聊天区过滤 reasoning/tool | 否 | 只改变用户看到什么 |
| 合并 AssistantRun | 否 | 只改变消息视觉分组 |
| Workspace 刷新与文件过滤 | 否 | 只改变文件展示，不改变磁盘内容 |
| 文献“已筛选/筛选中” | 否 | 只改变展示来源和状态文案 |
| 12 秒 HTTP 对账 | 否 | 只恢复真实消息和状态，不创建 turn |
| 进程区 10 秒拉实验进度 | 否 | 只读取 `progress.json` |

## 16. 数据分别持久化在哪里

| 数据 | 权威来源 | 浏览器刷新后 |
| --- | --- | --- |
| session 和消息 | OpenCode | 可恢复 |
| session cwd | OpenCode `session.directory`，后端映射作缓存 | 可从 session 信息恢复 |
| Agent 产物 | session cwd 文件系统 | 可恢复 |
| 项目、session 归属、手动标题 | `.famou/project-state.json` | 可恢复 |
| 项目状态的浏览器副本 | `localStorage` | 仅缓存/迁移用途 |
| 当前 tab 的 session | `sessionStorage` | 当前 tab 刷新可恢复，新 tab 不继承 |
| 当前模型、主题、栏宽 | `localStorage` | 可恢复 |
| 当前 session 上传记录 | `localStorage` + 内存 | 可恢复显示，文件本身以磁盘为准 |
| 实验状态和进度 | `.famou_jobs/<job>/` | 可恢复 |
| SSE 事件 | 不持久化 | 丢失后通过消息/status HTTP 对账 |

## 17. 当前已知的不一致和风险

### 高优先级

1. **Project 与 Agent 文件上下文没有真正打通。** Project 内新 session 仍是独立 cwd，项目初始文件不会自动复制或挂载进去。
2. **活动 run 由目录排序推断。** 一个 session 有多个 run 时，右侧阶段、文献和论文卡可能绑定错目录。
3. **编译隐藏 prompt 允许 `article` fallback。** 与模板优先策略冲突，可能产出“能编译但不符合目标 venue”的论文。

### 中优先级

4. **正式文献卡会覆盖其他来源。** `paper_cards.jsonl` 一旦非空，聊天和工具里更多的候选文献不会同时显示，容易让用户误以为文献丢失。
5. **Project 大文件夹仍经浏览器完整读取并 base64 编码。** 虽然已有并发和取消，但大文件/大量文件仍消耗浏览器内存，并增加请求体积。
6. **普通消息附件仍逐个串行上传。** 多附件时首条 Agent 请求会明显延迟。
7. **文件大小文案可能与真实限制不一致。** 代码限制为单文件 50 MB，部分 UI 提示仍可能沿用旧的 8 MB 文案。

### 需要持续观察

8. **`session.error` 的 1.8 秒延迟是经验值。** 它不终止 Agent，但不同 provider 的错误恢复时序可能不同。
9. **编译按钮依赖 busy 从 false -> true -> false。** 如果 Agent 请求未真正进入 busy，按钮可能长期 waiting；如果 busy 事件异常，也可能提前恢复。
10. **前端仍有少量原生 `alert/confirm/prompt`。** Agent question/permission 已是应用内卡片，但知识库、用户名等非 Agent 操作仍可能使用浏览器弹窗。

## 18. Agent-first 原则下的建议边界

保持系统简单时，可以遵循以下边界：

1. 前端不要根据文件名、等待时长或消息文本猜 Agent 下一步；
2. 前端只提交用户明确动作，并展示 OpenCode 的真实状态；
3. 科研流程、文献规范、数据获取和论文规范优先放在有版本管理的 `AGENTS.md`、skills 和 hooks 中；
4. 只有安全边界、持久化、断线恢复和明确的用户阻塞需要后端强约束；
5. Agent 应主动在聊天区给出阶段性结论，前端不应根据工具日志自动编造“进展总结”；
6. Workspace、进程和聊天使用同一 session/cwd/message 事实源，不建立相互独立的推断状态。

## 19. 排查问题时先看哪里

### 聊天没有流式输出

依次检查：

1. `/oc/session/:id/prompt_async` 是否成功；
2. `/oc/event?directory=...` 是否连接；
3. 是否有 `message.part.delta`，而不只是 `session.next.*`；
4. `/session/status` 是否仍为 busy；
5. 是否存在待回复 question/permission；
6. 是否收到真实 `session.error`。

### Agent 在运行，但 Workspace 没产物

依次检查：

1. OpenCode `session.directory`；
2. Agent 实际 cwd；
3. 文件是否写入同一目录；
4. `/local-file?path=<cwd>&sessionID=<sid>` 返回；
5. 文件是否被归类为 hidden/internal；
6. 当前活动 run 是否被目录排序选错。

### 文献一直“筛选中”

依次检查：

1. 活动 run 是否正确；
2. `paper_cards.jsonl` 是否存在且内容可解析；
3. 是否只有候选文件或工具输出；
4. 文献检索工具是否仍 running 或成为孤立状态。

### 实验心跳报错或重复

依次检查：

1. `.famou_jobs/<job>/status.json` 的真实 state；
2. `progress.json` 和 `runner.log`；
3. `.heartbeat-*.claim/.sent` 去重文件；
4. `_audit/heartbeat.jsonl` 中扫描、路由和注入记录；
5. job `meta.json` 中的 sessionID 和 progress policy。

## 20. 代码入口索引

| 逻辑 | 主要代码 |
| --- | --- |
| 消息发送、SSE、状态恢复、聊天/进程/Workspace | `famou_scientist/assets/web/src/app.tsx` |
| OpenCode 反向代理和 session cwd 注入 | `famou_scientist/assets/web/server.mjs` 中 `proxyCreateSession()`、`proxy()` |
| 独立 workspace 创建 | `server.mjs` 中 `allocateWorkspace()` |
| 文件上传、读取、预览和下载 | `server.mjs` 中 `serveUpload()`、`serveLocalFile()`、`serveRaw()`、`serveArchive()` |
| 项目状态持久化 | `app.tsx` 中 `loadProjectState()` / `saveProjectState()`；`server.mjs` 中 `/project-state` |
| OpenCode 事件归并 | `app.tsx` 中 `handleEvent()`、`reconcile()`、`subscribeEvents()` |
| Agent 问询和权限 | `app.tsx` 中 `QuestionCard`、`PermissionCard` 及 reply/recover 函数 |
| 文献提取和筛选 | `app.tsx` 中 `collectLiterature()`、`loadLiteratureArtifacts()` |
| 产物与文件树 | `app.tsx` 中 `AssistantRun`、`ResearchPanel`、`artifactVisibility()` |
| 进程轨迹 | `app.tsx` 中 `ProcessLog` |
| 实验进度 API | `server.mjs` 中 `serveProcessProgress()` |
| 实验心跳和 Agent 唤醒 | `famou_scientist/assets/opencode/plugins/heartbeat.ts` |
| 论文编译入口 | `app.tsx` 中 `PaperCard.compileViaAgent()`；`server.mjs` 中 `serveCompile()` |

