/**
 * famou-scientist 实验心跳通知 plugin（heartbeat）—— OpenCode plugin。
 *
 * 解决的问题：OpenCode 是事件驱动的，agent 答完一轮就休眠，不会主动去查后台异步实验
 * （arc_run_experiment(is_async=true) 启动的 job）是否跑完——结果常常等用户问起才被发现。
 *
 * 机制（已实测验证）：插件常驻一个 setInterval 心跳，每 tick **纯文件扫描** .famou_jobs/
 * 的信号文件（零 LLM、零 token）。
 *   ① 完成/失败：通过 client.session.promptAsync 唤醒发起会话，让 agent 核验真实结果。
 *   ② 普通进度：只写入 job/progress.json，由 Web「进程」面板读取，绝不创建聊天消息或 LLM turn。
 *   ③ 语义检查点/无日志告警：在 Agent 空闲时通过 prompt 唤醒，让它核验状态并决定下一步。
 * tick 本身零成本；只有完成、失败或语义检查点才花一个 turn（分层心跳）。
 *
 * 注意：本 plugin 不是护栏（guardrails 才是）。它是**主动通知器**——唯一会主动开口的组件。
 * 纪律：① 仅在 agent 空闲时注入（不打断进行中的 turn）② Set 去重完成、Map 限频/去重进度检查点
 * ③ 每 tick 至多注入一条、完成优先于进度 ④ 只通知近期完成的 job（避免翻旧账）。
 */
import type { Plugin } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

// 与 tool/arc.ts 的 JOBS_ROOT 解析保持一致（异步 job 目录）。
const JOBS_ROOT = process.env.ARC_JOBS_DIR || path.join(process.cwd(), ".famou_jobs")
const TICK_MS = Number(process.env.ARC_HEARTBEAT_MS) || 60_000 // 心跳周期（可调，便于测试/运维）；tick 本身零成本，仅完成时才花 turn
const MAX_POLL_MS = Number(process.env.ARC_HEARTBEAT_MAX_MS) || 2 * 60 * 60 * 1000
const CLAIM_STALE_MS = 10 * 60 * 1000
const MAX_DONE_AGE_MS = MAX_POLL_MS + 15 * 60 * 1000 // 覆盖一次最大退避周期，避免刚完成的任务被误判为旧任务
// 运行中实验的「进度播报」策略：
// - ARC_PROGRESS_INTERVAL_MS=0：全局关闭运行期播报（只保留完成通知）。
// - ARC_PROGRESS_INTERVAL_MS=<正数>：无 job 级策略时使用这个固定间隔。
// - 未设置：默认不播运行中进度，只保留完成/失败通知；job 可在 meta.progress_policy 里声明自己的策略。
const ENV_PROGRESS_MS = (() => {
  const raw = process.env.ARC_PROGRESS_INTERVAL_MS
  if (raw === undefined) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
})()
const PROGRESS_DISABLED = ENV_PROGRESS_MS !== null && ENV_PROGRESS_MS <= 0

type ProgressPolicy = {
  mode: "adaptive" | "fixed" | "off"
  intervalMs: number | null
  minIntervalMs: number
  maxIntervalMs: number
  quietAlertMs: number
  milestones: number[]
  logMilestones: string[]
}
function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}
function num(v: any, fallback: number): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}
function normalizeProgressPolicy(raw: any, timeoutSec: number): ProgressPolicy {
  const p = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {}
  const modeRaw = String(p.mode || "").toLowerCase()
  const mode: ProgressPolicy["mode"] = modeRaw === "off" ? "off" : modeRaw === "fixed" ? "fixed" : "adaptive"
  const timeoutMs = timeoutSec > 0 ? timeoutSec * 1000 : 0
  const baseMs = timeoutMs && timeoutMs <= 30 * 60 * 1000 ? 5 * 60 * 1000
    : timeoutMs && timeoutMs <= 2 * 60 * 60 * 1000 ? 15 * 60 * 1000
    : timeoutMs && timeoutMs <= 12 * 60 * 60 * 1000 ? 30 * 60 * 1000
    : timeoutMs ? 60 * 60 * 1000 : 15 * 60 * 1000
  const minMs = clamp(num(p.min_interval_sec, Math.min(5 * 60, Math.round(baseMs / 1000))) * 1000, 60 * 1000, 24 * 60 * 60 * 1000)
  const maxMs = clamp(num(p.max_interval_sec, Math.max(15 * 60, Math.round(baseMs / 1000))) * 1000, minMs, 24 * 60 * 60 * 1000)
  const intervalMs = p.interval_sec != null ? clamp(num(p.interval_sec, Math.round(baseMs / 1000)) * 1000, minMs, maxMs) : null
  const milestones = Array.isArray(p.milestones) ? p.milestones
    .map((x: any) => Number(x))
    .filter((x: number) => Number.isFinite(x) && x > 0 && x < 1)
    .sort((a: number, b: number) => a - b)
    : [0.25, 0.5, 0.75, 0.9]
  const logMilestones = Array.isArray(p.log_milestones) ? p.log_milestones
    .map((x: any) => String(x || "").trim())
    .filter((x: string) => x.length >= 2)
    .slice(0, 20)
    : []
  return {
    mode,
    intervalMs,
    minIntervalMs: minMs,
    maxIntervalMs: maxMs,
    quietAlertMs: clamp(num(p.quiet_alert_sec, 60 * 60) * 1000, 5 * 60 * 1000, 24 * 60 * 60 * 1000),
    milestones,
    logMilestones,
  }
}
function adaptiveIntervalMs(policy: ProgressPolicy, timeoutSec: number, elapsedMs: number): number {
  if (policy.mode === "fixed" && policy.intervalMs) return policy.intervalMs
  const timeoutMs = timeoutSec > 0 ? timeoutSec * 1000 : 0
  let base = timeoutMs && timeoutMs <= 30 * 60 * 1000 ? 5 * 60 * 1000
    : timeoutMs && timeoutMs <= 2 * 60 * 60 * 1000 ? 15 * 60 * 1000
    : timeoutMs && timeoutMs <= 12 * 60 * 60 * 1000 ? 30 * 60 * 1000
    : timeoutMs ? 60 * 60 * 1000 : 15 * 60 * 1000
  const frac = timeoutMs > 0 ? elapsedMs / timeoutMs : 0
  if (frac >= 0.9) base = Math.min(base, 15 * 60 * 1000)
  else if (frac >= 0.75) base = Math.min(base, 30 * 60 * 1000)
  return clamp(policy.intervalMs || base, policy.minIntervalMs, policy.maxIntervalMs)
}

// 「静默判空闲」阈值：距 agent 上次**真实生成活动**（part.delta/part.updated/next.step）已静默这么久 → 视为空闲、
// 可安全注入。正向判据，取代旧的「lastIdleAt > lastRunAt」相对比较（后者空闲期 lastIdleAt 不前进、易自锁）。
const QUIET_MS = Number(process.env.ARC_HEARTBEAT_QUIET_MS) || 90_000
// 完成通知强制兜底：一个 done/failed job 距「首次观察到完成」超过这么久仍没成功通知 → 无视空闲判据强制注入一次。
// 兜底意义：无论 safeToInject 逻辑藏什么 bug，实验完成最迟这么久必叫醒 agent（failed/超时尤其不该丢）。
const FORCE_NOTIFY_MS = Number(process.env.ARC_FORCE_NOTIFY_MS) || 180_000

// ── 审计落盘（完整链条·默认开）─────────────────────────────────
// 把「心跳每拍决策 / 收到的 opencode 事件 / 每次注入尝试」结构化落盘到 $JOBS_ROOT/_audit/*.jsonl，
// 与 runner 侧的 <job>/lifecycle.jsonl + status.json + sqlite 消息一起，拼成「实验跑到哪 → agent 在不在生成
// → 心跳看到什么、决策什么、注入没 → agent 是否响应」的端到端审计链。出问题可直接 tail 定位，不必事后考古。
// 默认开启；ARC_AUDIT=off/0/false/no 关闭。零敏感信息（不记 key/url/模型）；滚动截断防膨胀。
const AUDIT_OFF = /^(off|0|false|no)$/i.test(process.env.ARC_AUDIT || "")
const AUDIT_DIR = path.join(JOBS_ROOT, "_audit")
const AUDIT_MAX_LINES = 2000
function auditWrite(file: string, rec: Record<string, any>): void {
  if (AUDIT_OFF) return
  try {
    fs.mkdirSync(AUDIT_DIR, { recursive: true })
    fs.appendFileSync(path.join(AUDIT_DIR, file), JSON.stringify({ ts: Date.now(), ...rec }) + "\n")
  } catch {
    /* 审计失败绝不影响主流程 */
  }
}
function auditRotate(file: string): void {
  if (AUDIT_OFF) return
  try {
    const p = path.join(AUDIT_DIR, file)
    if (!fs.existsSync(p)) return
    const lines = fs.readFileSync(p, "utf-8").split("\n")
    if (lines.length > AUDIT_MAX_LINES + 200) {
      fs.writeFileSync(p, lines.slice(-AUDIT_MAX_LINES).join("\n"))
    }
  } catch {
    /* ignore */
  }
}

// 可选调试日志（设 ARC_HEARTBEAT_DEBUG=<文件路径> 开启）；默认关闭、零开销。
const DEBUG_LOG = process.env.ARC_HEARTBEAT_DEBUG // 设为文件路径即开启调试日志；默认关闭、零开销
function dlog(m: string): void {
  if (!DEBUG_LOG) return
  try {
    fs.appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${m}\n`)
  } catch {
    /* ignore */
  }
}

function writeProgressSnapshot(dir: string, snapshot: Record<string, any>): void {
  try {
    const tmp = path.join(dir, ".progress.json.tmp")
    fs.writeFileSync(tmp, JSON.stringify(snapshot), "utf-8")
    fs.renameSync(tmp, path.join(dir, "progress.json"))
  } catch {
    /* process display is best-effort and must never affect the experiment */
  }
}

type SharedHeartbeatState = {
  schedulerStarted: boolean
  currentSession?: string
  lastGenActivityAt: number
}
const SHARED_KEY = Symbol.for("famou-scientist.heartbeat.scheduler.v2")
const globalState = globalThis as any
const shared = globalState[SHARED_KEY] || (globalState[SHARED_KEY] = {
  schedulerStarted: false,
  lastGenActivityAt: Date.now(),
})

function notificationPaths(dir: string, state: string): { claim: string; sent: string } {
  const suffix = state === "done" ? "done" : "failed"
  return {
    claim: path.join(dir, `.heartbeat-${suffix}.claim`),
    sent: path.join(dir, `.heartbeat-${suffix}.sent`),
  }
}

function claimNotification(dir: string, state: string): string | null {
  const marker = notificationPaths(dir, state)
  if (fs.existsSync(marker.sent)) return null
  try {
    fs.writeFileSync(marker.claim, JSON.stringify({ pid: process.pid, at: Date.now() }), { flag: "wx" })
    return marker.claim
  } catch {
    try {
      if (Date.now() - fs.statSync(marker.claim).mtimeMs > CLAIM_STALE_MS) {
        fs.unlinkSync(marker.claim)
        fs.writeFileSync(marker.claim, JSON.stringify({ pid: process.pid, at: Date.now() }), { flag: "wx" })
        return marker.claim
      }
    } catch {
      /* another process owns the claim */
    }
    return null
  }
}

function finishNotificationClaim(dir: string, state: string, claim: string): void {
  const marker = notificationPaths(dir, state)
  try { fs.renameSync(claim, marker.sent) } catch { try { fs.unlinkSync(claim) } catch {} }
}

function releaseNotificationClaim(claim: string): void {
  try { fs.unlinkSync(claim) } catch { /* retry on a later poll */ }
}
export const ArcHeartbeat: Plugin = async ({ client }) => {
  const ownsScheduler = !shared.schedulerStarted
  if (ownsScheduler) shared.schedulerStarted = true
  dlog("heartbeat init; owner=" + ownsScheduler + "; TICK_MS=" + TICK_MS)
  // 正向判空闲：记 lastGenActivityAt = agent **最近一次真实生成活动**的时刻（由 part.delta/part.updated/
  // next.step 这些"在生成"事件更新；session.idle 不更新它）。「距上次生成静默 ≥ QUIET_MS」即视为空闲可注入。
  // 取代旧的 lastIdleAt/lastRunAt 相对比较——后者空闲期 lastIdleAt 不前进、且被注入自污染，会永久自锁。
  // 初值 = 启动时刻：插件刚起的 QUIET_MS 内先不注入（避开启动抖动），之后无生成活动才放行。
  const notified = new Set<string>() // 已通知过的 job_id
  const pollSchedule = new Map<string, { nextAt: number; intervalMs: number }>() // job_id -> 下一次状态检查
  const completedSeenAt = new Map<string, number>() // job_id → 首次观察到 done/failed 的时刻（强制兜底用）
  const lastProgressAt = new Map<string, number>() // 每个 running job 上次进度播报时间
  const lastLogSize = new Map<string, number>() // 每个 job 上次观察到的 runner.log 大小（判有无新输出/卡住）
  const lastLogGrowthAt = new Map<string, number>() // 每个 job 上次观察到 runner.log 增长的时刻
  const lastQuietAlertAt = new Map<string, number>() // 每个 job 上次“无新日志”提醒时刻
  const sentMilestones = new Map<string, Set<string>>() // 每个 job 已播过的时间 milestone
  const sentLogMilestones = new Map<string, Set<string>>() // 每个 job 已播过的日志 milestone
  // 事件流审计：高频 message.part.delta 聚合计数，收到非 delta 事件时再 flush 一行，避免逐 token 刷屏。
  let deltaAgg: { sid: string; count: number } | null = null
  const flushDelta = (): void => {
    if (deltaAgg) {
      auditWrite("events.jsonl", { kind: "event", type: "message.part.delta", agg: deltaAgg.count, sessionID: deltaAgg.sid })
      deltaAgg = null
    }
  }
  // 哪些 opencode 事件代表"agent 正在生成"（依据前端 app.tsx 已验证的 activityRef 更新源）。
  const GEN_EVENTS = new Set(["message.part.delta", "message.part.updated", "session.next.step.started"])

  // 启动对账：把“早就完成（超过 2h）”的历史 job 预先标记为已通知，避免重开 TUI 翻旧账；
  // 2h 内完成的留着，让本会话补发一次（找回离线期间错过的完成事件）。
  try {
    if (fs.existsSync(JOBS_ROOT)) {
      const now = Date.now()
      for (const id of fs.readdirSync(JOBS_ROOT)) {
        const donePath = path.join(JOBS_ROOT, id, ".done")
        try {
          if (fs.existsSync(donePath) && now - fs.statSync(donePath).mtimeMs > MAX_DONE_AGE_MS) {
            notified.add(id)
          }
        } catch {
          /* 忽略单个 job 的统计错误 */
        }
      }
    }
  } catch {
    /* JOBS_ROOT 还不存在很正常 */
  }

  const timer = ownsScheduler ? setInterval(async () => {
    let entries: string[]
    try {
      entries = fs.existsSync(JOBS_ROOT) ? fs.readdirSync(JOBS_ROOT) : []
    } catch {
      return
    }
    // 审计滚动截断（每拍一次，60s 间隔开销可忽略）
    auditRotate("heartbeat.jsonl")
    auditRotate("events.jsonl")

    // 正向判空闲：距上次真实生成活动静默 ≥ QUIET_MS → 可安全注入（不再依赖 lastIdleAt>lastRunAt 相对比较）。
    const sinceGenMs = Date.now() - shared.lastGenActivityAt
    const safeToInject = sinceGenMs > QUIET_MS
    dlog(`tick: sid=${shared.currentSession ?? "?"} sinceGen=${Math.round(sinceGenMs / 1000)}s safe=${safeToInject}`)

    // 第一优先：完成通知（done/failed）。**总是遍历**（不因 !safeToInject 提前 return），
    // 以便对「完成但久未通知」的 job 做强制兜底注入。本拍至多发一条完成通知。
    let injected = false
    const scanned: { job: string; state: string }[] = []
    const dueJobs = new Set<string>()
    for (const id of entries) {
      if (notified.has(id)) continue
      const schedule = pollSchedule.get(id)
      if (schedule && Date.now() < schedule.nextAt) continue
      dueJobs.add(id)
      const dir = path.join(JOBS_ROOT, id)
      const statusPath = path.join(dir, "status.json")
      if (!fs.existsSync(statusPath)) continue

      let st: any
      try {
        st = JSON.parse(fs.readFileSync(statusPath, "utf-8"))
      } catch {
        continue // 正被原子写覆盖的瞬间，下拍再看
      }
      scanned.push({ job: id, state: st.state })
      if (st.state === "running") {
        const nextInterval = Math.min(schedule ? schedule.intervalMs * 2 : TICK_MS * 2, MAX_POLL_MS)
        pollSchedule.set(id, { intervalMs: nextInterval, nextAt: Date.now() + nextInterval })
        continue
      }
      pollSchedule.delete(id)
      if (st.state !== "done" && st.state !== "failed") continue

      // 年龄过滤：太久以前完成的不补发
      try {
        const donePath = path.join(dir, ".done")
        if (fs.existsSync(donePath) && Date.now() - fs.statSync(donePath).mtimeMs > MAX_DONE_AGE_MS) {
          notified.add(id)
          continue
        }
      } catch {
        /* 忽略 */
      }

      // 强制兜底：记「首次观察到完成」的时刻；逾期 FORCE_NOTIFY_MS 仍没发出 → 无视空闲判据强制注入。
      if (!completedSeenAt.has(id)) completedSeenAt.set(id, Date.now())
      const overdue = Date.now() - (completedSeenAt.get(id) as number) > FORCE_NOTIFY_MS
      const forced = overdue && !safeToInject
      if (!safeToInject && !overdue) continue // 空闲未到且未逾期 → 本拍先不发，下拍继续等
      if (injected) break // 本拍已发过一条完成通知，其余留到下拍

      // 精准路由：优先发回“发起该实验的会话”（arc.ts 启动时写入 meta.json），否则发当前会话
      let target = shared.currentSession
      try {
        const metaPath = path.join(dir, "meta.json")
        if (fs.existsSync(metaPath)) {
          const meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"))
          if (meta.sessionID) target = meta.sessionID
        }
      } catch {
        /* 忽略 */
      }
      if (!target) continue // 无目标会话，发不了，下拍再说

      // 跨 workspace / 进程原子抢占通知权，避免多个插件实例同时向同一会话注入。
      const claim = claimNotification(dir, st.state)
      if (!claim) {
        if (fs.existsSync(notificationPaths(dir, st.state).sent)) notified.add(id)
        continue
      }
      notified.add(id)
      const verb = st.state === "done" ? "已完成" : "失败/超时"
      const text =
        `[系统通知·实验心跳] 你之前在后台启动的实验 ${id} ${verb}（state=${st.state}）。` +
        `请调用 arc_experiment_status("${id}") 查看真实结果：done 则按结果继续（分析/研究决策），` +
        `failed/timed_out 则 load experiment-repair 诊断。这是后台进程的真实状态，不是用户的新指令。`
      try {
        await client.session.promptAsync({
          path: { id: target },
          body: { parts: [{ type: "text", text }] },
        })
      } catch {
        notified.delete(id) // 发送失败 → 撤销标记，下拍重试
        releaseNotificationClaim(claim)
        auditWrite("heartbeat.jsonl", { kind: "inject", job: id, notify: st.state, target, ok: false, forced })
        continue
      }
      finishNotificationClaim(dir, st.state, claim)
      auditWrite("heartbeat.jsonl", { kind: "inject", job: id, notify: st.state, target, ok: true, forced })
      // 本拍只发一条，避免一次性灌入多条
      injected = true
      break
    }

    // 第二优先：运行中实验的进度播报（仅当本拍没发完成通知、agent 空闲、且开启了进度播报）。
    // 进度播报不做强制兜底（不如完成通知紧要）——只在 safeToInject 时播，绝不打断进行中的 turn。
    // 每个 running job 可按 meta.progress_policy 声明自适应 interval、时间 milestone、日志 milestone、quiet alert。
    // 运行中进度播报默认收紧为“显式策略优先”：
    // - job 在 meta.progress_policy 里声明了策略 → 播报；
    // - 环境变量显式开启了固定间隔 → 播报；
    // - 两者都没有 → 只保留完成通知，不再默认灌进度。
    if (!injected && !PROGRESS_DISABLED) {
      for (const id of entries) {
        if (!dueJobs.has(id)) continue
        if (notified.has(id)) continue // 已完成的不在此列
        const dir = path.join(JOBS_ROOT, id)
        const statusPath = path.join(dir, "status.json")
        if (!fs.existsSync(statusPath)) continue
        let st: any
        try {
          st = JSON.parse(fs.readFileSync(statusPath, "utf-8"))
        } catch {
          continue
        }
        if (st.state !== "running") continue // 只播运行中的

        const startMs = st.start ? st.start * 1000 : Date.now()
        const now = Date.now()

        // 路由 + timeout + progress_policy（meta.json：arc.ts 启动异步 job 时写入）
        let target = shared.currentSession
        let timeoutSec = 0
        let policyRaw: any = null
        try {
          const meta = JSON.parse(fs.readFileSync(path.join(dir, "meta.json"), "utf-8"))
          if (meta.sessionID) target = meta.sessionID
          if (meta.timeout_sec) timeoutSec = Number(meta.timeout_sec)
          if (meta.progress_policy) policyRaw = meta.progress_policy
        } catch {
          /* 忽略 */
        }
        if (!target) continue // 无目标会话，发不了
        if (!policyRaw && ENV_PROGRESS_MS === null) continue // 默认不播运行中进度：只保留完成通知
        const policy = normalizeProgressPolicy(policyRaw, timeoutSec)
        if (policy.mode === "off") continue

        // runner.log 尾部 + 是否有新输出（与上次播报相比 log 是否变大）
        let tail = ""
        let size = 0
        let logText = ""
        try {
          logText = fs.readFileSync(path.join(dir, "runner.log"), "utf-8")
          size = logText.length
          tail = logText.split("\n").filter(Boolean).slice(-8).join("\n")
        } catch {
          /* 还没日志 */
        }
        const grew = size > (lastLogSize.get(id) ?? 0)
        if (grew || !lastLogGrowthAt.has(id)) lastLogGrowthAt.set(id, now)
        lastLogSize.set(id, size)

        const elapsedMs = now - startMs
        const mins = Math.round(elapsedMs / 60_000)
        const elapsedStr = mins >= 60 ? `${Math.floor(mins / 60)}h${mins % 60}m` : `${mins}m`
        const pct = timeoutSec > 0 ? Math.min(100, Math.round((elapsedMs / (timeoutSec * 1000)) * 100)) : null
        const last = lastProgressAt.get(id) ?? startMs // 首次：以启动时刻为基准 → 一个间隔后才首播
        const intervalMs = !policyRaw && ENV_PROGRESS_MS && ENV_PROGRESS_MS > 0
          ? ENV_PROGRESS_MS
          : adaptiveIntervalMs(policy, timeoutSec, elapsedMs)
        const scheduled = pollSchedule.get(id)
        if (scheduled && intervalMs < scheduled.intervalMs) {
          pollSchedule.set(id, { intervalMs, nextAt: Math.min(scheduled.nextAt, now + intervalMs) })
        }

        let reason = ""
        if (timeoutSec > 0 && policy.milestones.length > 0) {
          const frac = elapsedMs / (timeoutSec * 1000)
          let seen = sentMilestones.get(id)
          if (!seen) { seen = new Set<string>(); sentMilestones.set(id, seen) }
          for (const m of policy.milestones) {
            const key = `t${m}`
            if (frac >= m && !seen.has(key)) {
              seen.add(key)
              reason = `时间检查点 ${Math.round(m * 100)}%`
              break
            }
          }
        }
        if (!reason && logText && policy.logMilestones.length > 0) {
          let seen = sentLogMilestones.get(id)
          if (!seen) { seen = new Set<string>(); sentLogMilestones.set(id, seen) }
          const lower = logText.toLowerCase()
          for (const kw of policy.logMilestones) {
            const key = kw.toLowerCase()
            if (lower.includes(key) && !seen.has(key)) {
              seen.add(key)
              reason = `日志检查点 ${kw}`
              break
            }
          }
        }
        if (!reason && size > 0 && !grew) {
          const lastGrowth = lastLogGrowthAt.get(id) ?? now
          const lastQuiet = lastQuietAlertAt.get(id) ?? 0
          if (now - lastGrowth >= policy.quietAlertMs && now - lastQuiet >= policy.quietAlertMs) {
            lastQuietAlertAt.set(id, now)
            reason = `无新日志 ${Math.round((now - lastGrowth) / 60_000)}min`
          }
        }
        if (!reason && now - last >= intervalMs) reason = `间隔 ${Math.round(intervalMs / 60_000)}min`
        if (!reason) continue

        lastProgressAt.set(id, now) // 先置，防重叠 tick 重复发
        const snapshot = {
          job_id: id, sessionID: target || null, state: "running", elapsed_ms: elapsedMs,
          elapsed: elapsedStr, percent: pct, reason, tail, log_grew: grew, updated_at: now,
        }
        writeProgressSnapshot(dir, snapshot)
        auditWrite("heartbeat.jsonl", { kind: "process_update", job: id, notify: "progress", target, reason })

        // 普通间隔更新只写进程状态，不调用模型。仅语义检查点/卡死告警会恢复空闲 Agent。
        const shouldWakeAgent = /^(时间检查点|日志检查点|无新日志)/.test(reason)
        if (!shouldWakeAgent || !safeToInject) continue
        const text =
          `[系统通知·实验检查点] 后台实验 ${id} 仍在运行：已跑 ${elapsedStr}` +
          (pct !== null ? `（占超时上限 ${pct}%）` : "") +
          `。触发原因：${reason}。请调用 arc_experiment_status("${id}") 核验真实状态；` +
          `若仍 running，只更新计划并继续等待，不要向用户发送独立进度回复。`
        try {
          await client.session.promptAsync({ path: { id: target }, body: { parts: [{ type: "text", text }] } })
        } catch {
          auditWrite("heartbeat.jsonl", { kind: "inject", job: id, notify: "checkpoint", target, ok: false })
          continue
        }
        auditWrite("heartbeat.jsonl", { kind: "inject", job: id, notify: "checkpoint", target, ok: true })
        injected = true
        break
      }
    }

    // 本拍决策落盘（审计链：心跳看到了什么、决策什么、注入没）
    auditWrite("heartbeat.jsonl", {
      kind: "tick",
      currentSession: shared.currentSession ? shared.currentSession.slice(-8) : null,
      safeToInject,
      sinceGenMs,
      scanned,
      injected,
    })
  }, TICK_MS) : null
  ;(timer as any)?.unref?.()

  return {
    /** 跟踪当前活动会话 + 生成活动时刻（决定何时安全注入），并把每个事件落盘为审计证据。 */
    event: async ({ event }: any) => {
      try {
        const t = event?.type
        const p = event?.properties || {}
        const sid = p.sessionID || p.info?.sessionID || p.session?.id || p.info?.id
        if (sid) shared.currentSession = sid
        // 「在生成」事件 → 刷新 lastGenActivityAt（正向判空闲的依据）。session.idle 不更新它（它代表空闲）。
        if (GEN_EVENTS.has(t)) shared.lastGenActivityAt = Date.now()
        // 事件流审计：高频 part.delta 聚合计数，其余事件逐条落盘（先 flush 累积的 delta，保持时序）。
        if (t === "message.part.delta") {
          if (deltaAgg && deltaAgg.sid !== (sid || "")) flushDelta()
          deltaAgg = { sid: sid || "", count: (deltaAgg?.count || 0) + 1 }
        } else {
          flushDelta()
          auditWrite("events.jsonl", { kind: "event", type: t, sessionID: sid || null })
        }
        dlog(`event: ${t} sid=${sid ?? "?"}`)
      } catch {
        /* 事件结构异常不应影响主流程 */
      }
    },
  }
}
