# 后台实验心跳与生命周期机制

> 汇总 famou-scientist 在**后台异步实验**的整个生命周期里用到的所有"心跳/通知/收尾"机制：
> 实验**怎么从前台同步调用切到后台 detached 进程**起起来、之后各机制在**哪个阶段**作用、
> **怎么作用**、**预期效果**是什么、有哪些**可调旋钮**和**已知边界**。
>
> 说明：这份文档当前主要覆盖**本地异步实验**（`arc_run_experiment(is_async=true)` → `.famou_jobs/` → heartbeat）。
> 正式集群实验（`arc_cluster_job` / `fm-job-new`）仍在补接自动追踪链路，现阶段主要靠 `list/logs` 查状态。
>
> 配套阅读：`async-experiment-execution` skill（给 agent 看的纪律）、`docs/overview/ARCHITECTURE.md`（整体架构）、
> `docs/operations/TROUBLESHOOTING.md`（排障）。

---

## 0. 为什么需要"心跳"

三个事实凑在一起，逼出了这套机制：

1. **OpenCode 是事件驱动的**：agent 答完一轮就休眠，**不会**自己回头去看"后台那个实验跑完没"。
   不做任何事，结果就只能等用户下次问起才被发现。
2. **长实验跑在 detached 进程组里**：`arc_run_experiment(is_async=true)` 把实验丢进一个脱离 opencode
   生命周期的后台进程（卖点：关 TUI、长训练不断）。代价是它和主对话之间只剩**文件**这一条通信通道。
3. **普通用户不会手动收尾**：Ctrl+C 关掉 opencode 后，用户通常不知道后台还有进程在烧 GPU/CPU，
   更不会主动去 `kill`。

所以我们需要一套"**替 agent 盯着后台、该说话时把它叫醒、退出时把残留收干净**"的机制。
核心思想一句话：**不是让 agent 自己定时轮询（它做不好，只会 busy-poll 烧 token），
而是用一个常驻定时器做廉价文件扫描，只在"确实有事"时叫醒空闲的 agent。**

---

## 1. 全景图：三个组件 × 生命周期各阶段

```
   [启动]                    [运行中]                 [完成/失败/超时]        [取消 / 退出]
arc_run_experiment          async_runner.py           async_runner.py        arc_cancel_experiment
  (is_async=true)            边跑边写信号文件            落终态信号文件            (对话内手刹)
     │                          │                          │                  cleanup.ts
     │ spawn detached           │ status.json:running      │ status.json:done/    (退出兜底)
     ▼                          │ runner.log（进度日志）     │   failed
  写 job 目录                    │                          │ result.json
  + meta.json(sessionID)        │                          │ .done 哨兵
     │                          │                          │
     └──────────── .famou_jobs/<job_id>/（唯一通信通道：信号文件）────────────┘
                                │                          │
                    ┌───────────┴──────────────────────────┴───────────┐
                    │           heartbeat.ts（常驻定时器）                │
                    │  每 TICK_MS 纯文件扫描（零 LLM/零 token）：          │
                    │   ② 进度播报（running，每 PROGRESS_MS）             │
                    │   ① 完成通知（done/failed，去重一次）               │
                    │  仅在 agent 空闲时，经 client.session.prompt 叫醒     │
                    └──────────────────────────────────────────────────┘
```

**各阶段 → 哪个机制作用 → 预期效果**：

| 生命周期阶段 | 作用的机制 | 预期效果 |
|--------------|-----------|---------|
| **启动（同步 → 异步）** | `arc_run_experiment(is_async)` 分流 + detached spawn（§2） | 长任务丢后台、立即返回 job_id，master agent 的 turn 不被阻塞 |
| **运行中** | heartbeat **进度播报**（§4.4） | 每 ~15min 给发起会话播一条"已跑多久 / 占超时上限 / 日志尾 / 有无新输出"，用户心里有数 |
| **完成 / 失败 / 超时** | heartbeat **完成通知**（§4.3）+ 实验质量门 hook | 自动叫醒 agent 去 `arc_experiment_status` 取真结果；done→分析，failed→自愈 |
| **对话内主动取消** | `arc_cancel_experiment`（§6） | killpg 整个进程组、落 `cancelled`，腾出 GPU |
| **opencode 退出** | `cleanup.ts` reaper（§5） | 自动 killpg 所有仍 running 的 job，不留孤儿；逃生阀可关 |

> 注意：心跳机制**只服务后台异步实验**。文献检索、写作、绘图等都是**同步**工具调用（调完即返回），
> 不需要、也没有心跳。所以"各阶段"指的是上表这条**异步实验生命周期线**，不是整个研究流程的每个 Stage。

---

## 2. 实验是怎么被"后台"起起来的（同步主动跑 → 异步 detached 跑）

心跳/收尾都是在 job **已经在后台跑起来之后**才作用的。这一节讲它前面那一步：
`arc_run_experiment` 怎么从"前台同步把实验跑完"切换到"后台 detached 把实验丢出去、立即返回"。
代码在 `tool/arc.ts` 的 `run_experiment`（`:82`）。

### 2.1 一个工具，两种模式（`is_async` 分流）

`arc_run_experiment` 同一个工具，用 `is_async`（默认 `false`，`:96-99`）分流成两条路：

| 模式 | 怎么跑 | 阻塞吗 | 适用 |
|------|--------|--------|------|
| **同步**（默认 `is_async=false`） | 直接在 `TemporaryDirectory` 里 `ExperimentSandbox.run()` 跑完再返回（`:144-161`） | **阻塞**：整个工具调用 = 整个 turn 卡到实验结束 | 秒级 smoke test、跑通性验证、debug 小片段 |
| **异步**（`is_async=true`） | spawn 一个 **detached 子进程**跑 `async_runner.py`，**立即返回 `job_id`**（`:105-141`） | **不阻塞**：spawn 完当场返回，master agent 随即被解放 | 训练 / 下数据 / 多 condition×seed / 任何预计 **>60s** 的 |

> 同步模式用 `TemporaryDirectory`——进程退出目录即清，所以拿不到事后结果，只能阻塞等。
> 异步模式必须用**持久 job 目录**（`.famou_jobs/<job_id>/`），否则 detached 进程跑完、目录被清，
> 谁也读不到结果。这是同步/异步在"产物落盘"上的根本区别。

**判据（写在 `async-experiment-execution` skill 里）**：拿不准就当长任务走异步——异步的额外成本极低，
被卡死的代价很高。`timeout_sec` 要留冗余：**先估实付耗时，再 ×2 当 timeout**（超时是硬 kill）。

### 2.2 异步是怎么"脱离"出去的（detach 三件套）

异步分支（`arc.ts:105-141`）做四件事，关键是后面的 spawn 选项：

```js
// 1) 建持久 job 目录，预写实验代码 + 元数据
fs.mkdirSync(jobDir, { recursive: true })
fs.writeFileSync(jobDir/"code.py", userCode)
fs.writeFileSync(jobDir/"meta.json", { sessionID, created, timeout_sec })  // 供 heartbeat 路由 + 算超时占比

// 2) 把实验丢进一个 detached 子进程（关键三件套）
const logFd = fs.openSync(jobDir/"runner.log", "a")
const child = spawn(PY, [".../async_runner.py", jobDir, timeoutSec], {
  detached: true,                       // ← ① 新进程组/会话 leader
  stdio: ["ignore", logFd, logFd],      // ← ② stdout/stderr 直接写进 runner.log（不经 node）
  env: { ...process.env, ARC_PYTHON: PY },
})
child.unref()                           // ← ③ node 不等它，主进程可独立退出

// 3) 立即返回 job_id（state:running），当场结束本次工具调用
return { job_id, state: "running", job_dir, timeout_sec, hint: "...切勿轮询..." }
```

**detach 三件套各自的作用**：

- **① `detached: true`** —— 子进程成为**新进程组 / 会话的 leader**（PGID == runner 自己的 PID）。
  这一步是整套生命周期的地基：它让 runner **脱离 opencode 的前台进程组**，于是
  - Ctrl+C（SIGINT 只发给前台进程组 opencode）**打不到它** → 长实验不会被随手中断；
  - 反过来，要终止它就得 **killpg（`process.kill(-pid, sig)`，负 pid）**——这正是 §5 cleanup 和 §6 cancel 的做法。
- **② `stdio` 重定向到 `runner.log`** —— 实验的 stdout/stderr 不经 node、直接写文件。这就是 §4.4 进度播报
  能读到"最新日志尾部"的来源；也让 node 端零缓冲压力。
- **③ `child.unref()`** —— 把子进程从 node 的事件循环引用里摘掉，**node 主进程不再等它**，opencode 可以
  独立退出（退出时的收尾交给 §5 cleanup）。

### 2.3 进程树：为什么 killpg 能"连根拔起"

```
opencode (node)  ── 前台进程组
   │ spawn(detached:true) + child.unref()
   ▼
async_runner.py  ── 新进程组 leader（PGID == 自身 PID），已脱离 opencode
   │ ExperimentSandbox → subprocess.run(...)（未 start_new_session）
   ▼
实验进程  ──►  DataLoader / multiprocessing worker
   （孙进程继承 runner 的进程组）
```

- spawn 完，`run_experiment` **当场 return** `{job_id, state:"running"}` → master agent 的 turn 立即结束，
  **不被实验阻塞**，可以继续和用户对话、写不依赖结果的论文段落、起下一个独立实验。
- 实验进程及其 DataLoader/worker 都**继承 runner 的进程组**（runner 没给它们再开新 session），
  所以对 runner PID 做一次 **killpg**（`process.kill(-pid)`）就能把 runner + 实验 + 所有 worker
  **一并终止、不留孤儿**——§5（退出收尾）和 §6（对话内取消）都靠这一点。

> 一句话：**`is_async` 把"阻塞跑完"换成"丢进 detached 进程组 + 立即返回 job_id"**；从此实验脱离 opencode
> 独立活着，主对话不被卡，而它的状态/进度/结果全部通过 `.famou_jobs/<job_id>/` 的信号文件（§3）对外暴露，
> 由心跳（§4）观测、由 cleanup/cancel（§5/§6）收尾。

---

## 3. 信号文件骨架：心跳到底"读什么"

心跳和对话之间**唯一的通信通道**是 job 目录里的几个文件，由 `async_runner.py`（detached runner）
**原子写**（先写 `.tmp` 再 rename，避免读到半截）。所有组件的 `JOBS_ROOT` 解析一致：
`ARC_JOBS_DIR || <cwd>/.famou_jobs`（`arc.ts:29`、`heartbeat.ts:23`、`cleanup.ts:28` 同一份）。

```
.famou_jobs/<job_id>/
├── code.py        # arc.ts 启动前预写的用户实验代码
├── meta.json      # arc.ts 写：{ sessionID, created, timeout_sec }  ← 路由 + 超时占比靠它
├── status.json    # runner 写：{ state, pid, start, end, returncode, timed_out }  ← 状态机核心
├── result.json    # runner 写终态：{ returncode, timed_out, metrics, stdout, stderr, elapsed_sec }
├── runner.log     # 实验 stdout/stderr 实时追加  ← 进度播报取它的尾部
├── .done          # 哨兵文件（内容=returncode），出现即"跑完了"
└── work/          # ExperimentSandbox 的持久工作目录
```

**`status.json` 的状态机**（`state` 字段是一切判断的依据）：

```
running ──成功──▶ done       （returncode==0 且未超时）
   │    ──失败──▶ failed     （returncode!=0 或超时；runner crash 也兜底落 failed）
   └────被杀──▶ cancelled   （arc_cancel_experiment 或 cleanup 落，带 reason）
```

> `async_runner.py` 全程 try/except 兜底：**无论如何 status 都会落到终态**（done/failed），
> 绝不留 running 僵尸——除非进程被 SIGKILL 硬杀来不及写（那种情况由 cleanup / 取消工具补落 cancelled）。

---

## 4. heartbeat 插件——主动通知器（唯一会主动开口的组件）

文件：`famou_scientist/assets/opencode/plugins/heartbeat.ts`。
它在 opencode 的 node 进程里常驻一个定时器，是整套机制的"心脏"。

### 4.1 节拍：`setInterval` tick（零成本文件扫描）

`heartbeat.ts:79` 起一个 `setInterval`，周期 `TICK_MS`（默认 60s，`:24`），`unref()`（`:225`）不阻止退出。
**每一拍只做 `readdirSync(.famou_jobs/)` + 读 `status.json`**——纯文件 I/O，**零 LLM、零 token**。
真正"花一个 turn"（叫醒 agent）的只有"确实有完成"或"到点该播进度"时。这叫**分层心跳**：拍子廉价，开口才贵。

### 4.2 空闲闸门：绝不打断进行中的 turn

注入前必须过闸门：

```js
safeToInject = Date.now() - lastGenActivityAt > QUIET_MS
```

- `message.part.delta` / `message.part.updated` / `session.next.step.started` 这些“仍在生成”的事件会刷新 `lastGenActivityAt`。
- `session.idle` 不再作为唯一判据，因为实际事件流里 idle 后还可能跟着 `session.updated` 等尾随事件。
- 默认 `QUIET_MS=90s`：距上次真实生成活动静默超过这个阈值，才认为 agent 空闲可注入。
- 完成通知还有 `FORCE_NOTIFY_MS=180s` 兜底：如果 job 已经 done/failed 但迟迟没安全注入，超过兜底时间会强制叫醒一次。

**预期效果**：心跳永远在 agent 稳定空闲时才说话，不会在它正回答用户/正跑别的工具时插嘴。

### 4.3 完成通知（最高优先）

扫描中遇到 `state === "done" || "failed"` 且没通知过的 job（`:95-152`）：
经 `client.session.prompt` 注入一条 `[系统通知·实验心跳]`，告诉 agent"实验 X 已完成/失败，
去 `arc_experiment_status("X")` 取真结果"。**用 `Set notified` 去重**——同一个 job 只通知一次。

**预期效果**：你启动异步实验后**可以安心做别的**，跑完会被自动叫醒，不必盯着、不必反复查。

### 4.4 进度播报（运行中，每 `PROGRESS_MS`）

本拍若没发完成通知、且开启了进度播报，则扫 `state === "running"` 的 job（`:156-223`）：

- **限频**：每个 job 用 `Map lastProgressAt` 记上次播报时刻；`now - last < PROGRESS_MS` 就跳过（`:171-172`）。
  `PROGRESS_MS` 默认 15min（`:28-33`，`ARC_PROGRESS_INTERVAL_MS` 可调、设 0 关闭）。首播以"启动时刻"为基准 →
  跑满一个间隔才首播。
- **播什么**（`:204-210`）：已跑多久（`elapsedStr`）、占 `timeout_sec` 的百分比（从 `meta.json` 读）、
  `runner.log` **尾部 8 行**、以及**卡住预警**——`grew`（跟上次相比 log 没变大）就提示"可能在长 epoch/IO，
  也可能已卡住"（`:195`、`:209`）。
- **强约束文案**：每条进度末尾硬写"**不要据此分析/写 Results/研究决策——实验尚未结束**"（`:210`），
  防止被叫醒的 agent 拿没跑完的中间态去编结果。

**预期效果**：实验跑的过程中，用户每隔约 15 分钟就能收到一句进度转达（"epoch 3/10、loss 0.41、已跑 22m、
占超时上限 30%"），心里有数；同时这条机制完全不诱导 agent 做越界分析。

> 进度播报的质量取决于**实验代码有没有边跑边打日志**。`experimental-design` 和
> `async-experiment-execution` 都要求实验**定期打印进度 + 核心指标**（`metric: value` 格式），
> 否则播报就只剩"已跑 X 分钟、无新输出"。日志是喂给播报的原料。

### 4.5 精准路由：发回"发起该实验的那个会话"

无论完成通知还是进度播报，都先读 job 的 `meta.json`（`:120-130`、`:175-183`）：有 `sessionID`
就把通知发回**发起该实验的会话**，否则 fallback 到当前活动会话。多个会话各跑各的 job，通知不串台。

### 4.6 去重 / 限频 / 启动对账（避免吵闹和翻旧账）

- **完成去重**：`Set notified`，每个 job 完成只通知一次；发送失败则撤销标记下拍重试（`:145`）。
- **进度限频**：`Map lastProgressAt`，每 job 每 `PROGRESS_MS` 至多一条；发送失败回退时间戳重试（`:217`）。
- **每拍至多一条**：完成优先于进度；发了就 `break`，不一次性灌多条。

### 4.7 当前范围：只覆盖本地异步 job

- 这套 heartbeat 现在只扫描 `.famou_jobs/`，也只理解 `arc_run_experiment(is_async=true)` 这一条链路。
- `arc_cluster_job` / `fm-job-new` 提交的正式集群任务**不在**这个扫描范围内，所以不会自动被叫醒或播报。
- 如果要让正式集群任务也自动通知，需要再做一层 cluster job registry / heartbeat 对接。
- **启动对账**（`:61-77`）：重开 TUI 时，把**完成已超 2h** 的历史 job 预标为已通知（不翻旧账），
  2h 内完成的留着补发一次（找回离线期间错过的完成事件）。

---

## 5. cleanup 插件——退出收尾（reaper）

文件：`famou_scientist/assets/opencode/plugins/cleanup.ts`。不是定时心跳，而是**退出钩子**，
补齐"detached 进程脱离生命周期"（§2.2）带来的孤儿风险。

- **触发**：`process.on("exit")`（含 opencode 自己 Ctrl+C teardown 走到 `process.exit`，`:153`）；
  外加 `SIGINT/SIGTERM/SIGHUP` 兜底（`:155-157`）。
- **动作**（`reapAll`，`:65`）：同步扫 `.famou_jobs/`，对 `state==="running"` 的 job **killpg 整个进程组**
  （`SIGTERM` 紧跟 `SIGKILL`，`:95-96`）——runner + 实验子进程 + DataLoader/multiprocessing worker 一并终止
  （靠的就是 §2.3 的进程组继承），不留孤儿；随后落 `cancelled` 状态（`reason: opencode-exit:<sig>`）。
- **逃生阀**：`ARC_KEEP_JOBS_ON_EXIT=1` → 跳过清理，保留后台长跑（给"想让实验过夜、关 TUI 也别断"的重度用户，
  `:30`、`:68`）。这恢复 async 的原始语义。
- **非侵入信号处理**（`makeSignalHandler`，`:135`）：先 reap，再摘掉自己；若该信号已无其它监听者就重发一次
  让默认终止生效，否则交给 opencode 自己的 teardown——既保证清理，又不打断 opencode 的 Ctrl+C 处理。

**预期效果**：普通用户得到"**退出即清理**"的安全默认，不留吃 GPU/CPU 的孤儿；重度用户一个环境变量切回"续跑"。

> 局限：硬 `kill -9` opencode（SIGKILL）无法被任何钩子捕获，那种极端情况仍可能留孤儿——
> 用 `arc_cancel_experiment` 或手动 killpg 收尾。

---

## 6. `arc_cancel_experiment`——对话内的"手刹"

`arc.ts` 的 `cancel_experiment` 工具：读 job 的 `status.json` 拿 runner pid（detached → 它是进程组 leader，
见 §2.3），`killpg` 整个组（SIGTERM→等 1.5s→不行再 SIGKILL），落 `cancelled` 终态。已 done/failed/cancelled
的 job 取消是无操作（幂等）。

- **与 cleanup 的分工**：cancel 是"对话里主动停**某一个** job"（手刹）；cleanup 是"退出时兜底清**所有** job"（安全网）。
  两者落的终态一致（`cancelled` + `.done`）。
- **何时用**：实验跑岔了 / 不再需要某 condition / 要腾 GPU / 用户说"别跑了"。
- ⚠️ 取消是**不可逆硬终止**，丢未落盘的中间进度。只想看进度用 `arc_experiment_status`，别用取消。

---

## 7. agent 侧纪律（skill 层，软约束）

机制管"系统会主动叫你"，纪律管"你被叫醒后怎么做、平时怎么查"。见 `async-experiment-execution` skill §3：

- ✅ **收到完成通知** → 直接 `arc_experiment_status` 取结果，进入分析/自愈。
- ✅ **收到进度播报** → **只用一句话转达给用户**，**不**据此分析/写结果（实验没结束）。
- ✅ **自然断点查一次**作双保险（用户下次发消息、刚做完一段别的子任务后顺手查）。
- ❌ **绝不 busy-poll**：`running` 就停手，别在循环里每隔几秒查、别 `running` 后马上重复查
  （反面教材：一次对话把同一状态读 15+ 次纯烧 token）。

一句话：**完成有心跳叫你，平时是"路过看一眼"，绝不是"守在锅边盯"。**

---

## 8. 可调旋钮（环境变量汇总）

| 变量 | 作用 | 默认 | 归属 |
|------|------|------|------|
| `ARC_HEARTBEAT_MS` | 心跳节拍（多久扫一次文件） | `60000`（60s） | heartbeat |
| `ARC_PROGRESS_INTERVAL_MS` | 进度播报间隔；**设 `0` 关闭**进度播报（只留完成通知） | `900000`（15min） | heartbeat |
| `ARC_HEARTBEAT_QUIET_MS` | 判定 agent 空闲的静默阈值 | `90000`（90s） | heartbeat |
| `ARC_FORCE_NOTIFY_MS` | 完成通知兜底时间；超过后强制叫醒一次 | `180000`（180s） | heartbeat |
| `ARC_KEEP_JOBS_ON_EXIT` | `1/true/yes` → opencode 退出时**不**清理后台 job（续跑过夜） | 关（退出即清理） | cleanup |
| `ARC_JOBS_DIR` | job 目录根（三个组件共用） | `<cwd>/.famou_jobs` | 全部 |
| `ARC_PYTHON` / `ARC_HEARTBEAT_DEBUG` / `ARC_CLEANUP_DEBUG` | runner 用的 python / 两个插件的调试日志文件 | — | runner / 插件 |

调密：减小 `ARC_PROGRESS_INTERVAL_MS`。调安静：设它为 0。让长实验过夜：`export ARC_KEEP_JOBS_ON_EXIT=1`。

---

## 9. 边界与已知局限（如实记录）

**精确度分两层**：

- ✅ **"是不是 arc 起的实验"——精确**：`.famou_jobs/` 是专用命名空间，唯一写方是 `arc_run_experiment(is_async=true)`，
  零误报。心跳只看自己这个专用信箱，不是"扫全盘找疑似实验"。
- ⚠️ **"是哪个会话起的"——大多数情况精确，有三个退化点**：

1. **`sessionID` 可能为 null → 退化到当前会话**。`meta.sessionID` 取的是工具调用时的 `ctx.sessionID`（`arc.ts:113`）；
   若 opencode 没在 tool ctx 里提供它，写进去就是 `null`，心跳只能 fallback 到当前活动会话——
   单会话无所谓，多会话并行时**可能发错会话**。
2. **跨进程 / 陈旧 job 不区分**：心跳按目录扫，不区分"是不是本 opencode 进程起的"。同一 cwd 重开 opencode
   会扫到上一轮（可能已死）进程留下的 job；启动对账只挡"完成超 2h"的，一个上轮崩溃、`status.json` 仍停在
   `running` 的 job 这轮还会被当成"在跑"播报。
3. **不验 pid 存活**：进度分支只信 `status.json` 的 `state` 字段，没做 `process.kill(pid,0)` 存活探测。
   "进程已死但状态没落 cancelled"的 job 会被持续报成"running + 无新日志、可能卡住"——`grew` 能提示可疑，
   但它不知道其实已经死了。
4. **不覆盖正式集群 job**：heartbeat 只看 `.famou_jobs/`，不会自动追踪 `arc_cluster_job` / `fm-job-new` 任务。
   所以正式实验的完成/失败目前还需要 `list/logs` 手动查，或等后续接上 cluster registry。

**可选收紧方向**（尚未实现）：

- **pid 存活探针**：播报前 `process.kill(pid, 0)`，死了就跳过或落 `failed`——同时消掉退化点 2、3。
- **进程实例戳**：opencode 启动时生成 instance id，写进 `meta.json`，心跳只认本实例的 job——隔离跨进程串扰（退化点 2）。

---

## 10. 实现位置 / 文件清单

| 文件 | 角色 |
|------|------|
| `tool/arc.ts` | `run_experiment(is_async)` **同步/异步分流 + detached spawn 起 job**（§2）+ 写 meta.json；`cancel_experiment` 手刹；`experiment_status` 读信号文件 |
| `scripts/async_runner.py` | detached runner：跑实验 + 原子写 status/result/.done 信号文件 |
| `plugins/heartbeat.ts` | 常驻定时器：完成通知 + 进度播报（主动通知器） |
| `plugins/cleanup.ts` | 退出钩子：killpg 残留 running job（reaper） |
| `skill/experiment/async-experiment-execution/SKILL.md` | agent 侧纪律（何时走异步、何时查、绝不轮询、播报只转达不分析） |
| `skill/experiment/experimental-design/SKILL.md` | 要求实验定期打印进度 + 核心指标（喂进度播报的原料） |

> 一句话总览：**`is_async` 把实验丢进 detached 进程组（§2），信号文件是通道（§3），heartbeat 是心脏
> （运行中播报 + 完成叫醒，§4），cleanup 是退出收尾（§5），cancel 是对话内手刹（§6），skill 是 agent 侧纪律
> （§7）**——合起来，让"长实验后台跑"既不卡死对话、不烧 token 空转、用户全程心里有数，又不留孤儿、
> 不破真实性护栏。
