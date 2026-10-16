/**
 * famou-scientist 后台实验回收 plugin（cleanup / reaper）—— OpenCode plugin。
 *
 * 解决的问题：异步实验（arc_run_experiment(is_async=true)）是 **detached 进程组**，
 * 故意脱离 opencode 生命周期（卖点：关 TUI 长训练不断）。但普通用户 Ctrl+C 退出 opencode
 * 后，**不会**意识到后台还有进程在烧 GPU/CPU，也不会主动去 kill——于是孤儿进程默默堆积。
 *
 * 机制：插件在 opencode 的 node 进程里注册退出钩子。opencode 退出时（含它自己的 Ctrl+C
 * 处理走到 process.exit），**同步**扫描 .famou_jobs/，把仍 running 的 job **killpg 整个进程组**
 * （runner + 实验子进程 + DataLoader/multiprocessing worker 一并终止，不留孤儿），并把状态
 * 落成 cancelled。这样普通用户得到“退出即清理”的安全默认。
 *
 * 逃生阀：设环境变量 ARC_KEEP_JOBS_ON_EXIT=1 → 跳过清理，保留后台长跑（给“想让实验过夜、
 * 关了 TUI 也别断”的重度用户）。这正是 async 原始语义，按需开启。
 *
 * 与 arc_cancel_experiment 工具的关系：工具是“对话里主动停某个 job”（手刹）；本插件是
 * “退出时兜底清理所有 job”（默认安全网）。两者落的终态一致（cancelled + .done 哨兵）。
 *
 * 安全性：① 仅 killpg state=running 的 job（done/failed/cancelled 不动）② 单次执行（done 守卫）
 * ③ 信号处理器不吞信号、不干扰 opencode 自己的 Ctrl+C teardown（见 makeSignalHandler 注释）
 * ④ 全程同步（process 'exit' 钩子只允许同步），不依赖被杀的 runner 自行收尾。
 */
import type { Plugin } from "@opencode-ai/plugin"
import fs from "node:fs"
import path from "node:path"

// 与 tool/arc.ts、heartbeat.ts 的 JOBS_ROOT 解析保持一致。
const JOBS_ROOT = process.env.ARC_JOBS_DIR || path.join(process.cwd(), ".famou_jobs")
// 逃生阀：truthy（"1"/"true"/"yes"）→ 退出时保留后台实验，不清理。
const KEEP_ON_EXIT = /^(1|true|yes)$/i.test(process.env.ARC_KEEP_JOBS_ON_EXIT || "")

// 可选调试日志（设 ARC_CLEANUP_DEBUG=<文件路径> 开启）；默认关闭、零开销。
const DEBUG_LOG = process.env.ARC_CLEANUP_DEBUG
function dlog(m: string): void {
  if (!DEBUG_LOG) return
  try {
    fs.appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${m}\n`)
  } catch {
    /* ignore */
  }
}

/** 给整个进程组发信号（负 pid = killpg）；组已不存在(ESRCH)视为已结束；EPERM 等退回单进程。 */
function killGroup(pid: number, sig: NodeJS.Signals): void {
  try {
    process.kill(-pid, sig)
  } catch (e: any) {
    if (e?.code === "ESRCH") return
    try {
      process.kill(pid, sig)
    } catch {
      /* 已无法触达，放弃 */
    }
  }
}

function writeAtomic(p: string, data: unknown): void {
  const tmp = p + ".tmp"
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf-8")
  fs.renameSync(tmp, p)
}

let reaped = false
/** 同步扫描并终止所有仍在跑的后台实验。单次执行。 */
function reapAll(reason: string): void {
  if (reaped) return
  reaped = true
  if (KEEP_ON_EXIT) {
    dlog(`ARC_KEEP_JOBS_ON_EXIT set → skip cleanup on ${reason}`)
    return
  }

  let entries: string[]
  try {
    entries = fs.existsSync(JOBS_ROOT) ? fs.readdirSync(JOBS_ROOT) : []
  } catch {
    return
  }

  let killed = 0
  for (const id of entries) {
    const dir = path.join(JOBS_ROOT, id)
    const statusPath = path.join(dir, "status.json")
    let st: any
    try {
      st = JSON.parse(fs.readFileSync(statusPath, "utf-8"))
    } catch {
      continue // 没有/读不到 status.json：跳过
    }
    if (st.state !== "running") continue
    const pid = Number(st.pid)
    if (!pid || Number.isNaN(pid)) continue

    // 退出在即、无法 await 给优雅期 → SIGTERM 紧跟 SIGKILL，确保不留孤儿。
    killGroup(pid, "SIGTERM")
    killGroup(pid, "SIGKILL")

    try {
      writeAtomic(statusPath, {
        state: "cancelled",
        pid,
        start: st.start,
        end: Date.now() / 1000,
        returncode: -1,
        cancelled: true,
        reason: `opencode-exit:${reason}`,
      })
      const resultPath = path.join(dir, "result.json")
      if (!fs.existsSync(resultPath)) {
        writeAtomic(resultPath, {
          returncode: -1,
          timed_out: false,
          cancelled: true,
          metrics: {},
          stdout: "",
          stderr: `experiment cancelled on opencode exit (${reason})`,
          elapsed_sec: null,
        })
      }
      const donePath = path.join(dir, ".done")
      if (!fs.existsSync(donePath)) fs.writeFileSync(donePath, "-1", "utf-8")
    } catch {
      /* 落盘失败不影响“已杀掉进程”这个既成事实 */
    }
    killed++
  }
  if (killed > 0) dlog(`reaped ${killed} running job(s) on ${reason}`)
}

/**
 * 信号处理器：非侵入式。先 reap，再摘掉自己；若该信号已无其它监听者（opencode 没装自己的
 * handler）→ 重新发一次让默认终止行为生效；若还有其它监听者（opencode 自己的 teardown）→
 * 不重发，交给它退出。这样既保证清理，又不打断 opencode 的 Ctrl+C 处理、不重复触发它。
 */
function makeSignalHandler(sig: NodeJS.Signals): () => void {
  const handler = () => {
    reapAll(sig)
    process.removeListener(sig, handler)
    if (process.listenerCount(sig) === 0) {
      try {
        process.kill(process.pid, sig)
      } catch {
        /* ignore */
      }
    }
  }
  return handler
}

export const ArcCleanup: Plugin = async () => {
  dlog(`init; JOBS_ROOT=${JOBS_ROOT}; KEEP_ON_EXIT=${KEEP_ON_EXIT}`)
  // 主钩子：进程真正退出时（含 process.exit）同步清理。不干扰信号处理，最可靠。
  process.on("exit", () => reapAll("exit"))
  // 兜底：信号驱动的退出（opencode 若未走到 'exit'）。非侵入式（见 makeSignalHandler）。
  for (const s of ["SIGINT", "SIGTERM", "SIGHUP"] as NodeJS.Signals[]) {
    process.on(s, makeSignalHandler(s))
  }
  return {}
}
