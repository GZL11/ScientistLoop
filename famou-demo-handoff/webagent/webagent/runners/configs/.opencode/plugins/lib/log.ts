/**
 * Plugin 共用 logger。
 *
 * 三路 sink(独立配置,失败互不影响):
 *
 *   1. file        `{directory}/hook.log` — 本地审计,调试。所有 plugin hook
 *                  (billing / charge / evolution-loop / fm-evolution / step-limiter)
 *                  共写一个文件,靠 `[<from>]` 标签区分。
 *                  `setLogDirectory(dir)` 调过才走;不调则 skip。
 *
 *   2. HTTP        POST `<url>/logs` — 集中日志接收端。
 *                  默认 url = `http://0.0.0.0`(prod sidecar 形态),
 *                  env `WEBAGENT_LOG_ENDPOINT_URL` 覆盖。设为空串显式关闭。
 *                  失败 swallow,失败次数累计,每 100 次或每 60s 在 stderr 打一行报警。
 *
 *   3. stdout      console.log — 默认 **关**。
 *                  env `WEBAGENT_LOG_STDOUT=1` 显式开;或者 file 跟 HTTP 都没配
 *                  时自动 fallback(避免静默黑洞)。
 *
 * 调用方:
 *   import { log, setLogDirectory } from "./log"
 *   log("billing", "info", "build.skip_settle reason=...")
 *   log("charge",  "info", "2026-... freeze ticket=... → code=0 elapsed=66ms")
 *
 * 输出格式:
 *   stdout:           `[<from>] [<level>] <message>`
 *   file:             `<ISO timestamp> [<from>] [<level>] <message>`
 *     (文件多一段写入时刻,便于离线 grep 时定位事件先后;stdout 一般由容器日志
 *      系统兜底带时间戳,HTTP 端会自己打接收时间,所以这两路不再前置。)
 *   HTTP body:        `{ log: "[<from>] [<level>] <message>", level, from }`
 *     (log 字段保留 [from] 前缀,便于后端任选一路解析,grep 跟本地文件兼容)
 */

import { appendFileSync } from "node:fs"
import { join } from "node:path"

export type LogLevel = "info" | "warn" | "error"

const HTTP_ENDPOINT_ENV = "WEBAGENT_LOG_ENDPOINT_URL"
const STDOUT_ENABLED_ENV = "WEBAGENT_LOG_STDOUT"

const DEFAULT_HTTP_URL = "http://127.0.0.1:8103"
const HTTP_TIMEOUT_MS = 50
const FAILURE_WARN_EVERY = 100
const FAILURE_WARN_INTERVAL_MS = 60_000

// ── 配置(module-level state)──────────────────────────────────────────────

let logDirectory: string | null = null

// HTTP url:
//   env 未设(undefined) → 用默认 DEFAULT_HTTP_URL(prod sidecar 默认形态)
//   env 显式置空("" / 全空白) → null,关闭 HTTP forward
//   env 设了非空值 → 用 env 值
const logHttpUrl: string | null = (() => {
  const raw = process.env[HTTP_ENDPOINT_ENV]
  if (raw === undefined) return DEFAULT_HTTP_URL
  const trimmed = raw.trim()
  if (!trimmed) return null
  return trimmed.replace(/\/$/, "")
})()

const stdoutEnabledByEnv: boolean = (() => {
  const v = (process.env[STDOUT_ENABLED_ENV] ?? "").trim().toLowerCase()
  return v === "1" || v === "true" || v === "yes" || v === "on"
})()

let httpFailureCount = 0
let lastHttpWarnAt = 0

// ── API ───────────────────────────────────────────────────────────────────

/**
 * 注册文件 sink 的目录。文件写到 `{directory}/hook.log`。
 * 多个 plugin 共享同一个 workspace,多次调用幂等。
 * 传空串可关闭文件 sink(测试隔离时用)。
 */
export function setLogDirectory(directory: string): void {
  logDirectory = directory && directory.length > 0 ? directory : null
}

export function log(from: string, level: LogLevel, message: string): void {
  const line = `[${from}] [${level}] ${message}`

  // sink 1: stdout
  // - env 显式开 → 开
  // - 否则:其它 sink 全没配 → fallback 开(避免黑洞)
  if (stdoutEnabledByEnv || (!logDirectory && !logHttpUrl)) {
    // eslint-disable-next-line no-console
    console.log(line)
  }

  // sink 2: file
  if (logDirectory) {
    try {
      const stamp = new Date().toISOString()
      appendFileSync(join(logDirectory, "hook.log"), `${stamp} ${line}\n`)
    } catch {
      /* swallow:文件失败不能拖垮 plugin */
    }
  }

  // sink 3: HTTP
  if (logHttpUrl) {
    forwardHttp(line, level, from)
  }
}

// ── HTTP forwarding(fire-and-forget + 限速失败报警)────────────────────────

function forwardHttp(line: string, level: LogLevel, from: string): void {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS)
  fetch(`${logHttpUrl}/logs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log: line, level, from }),
    signal: ctrl.signal,
  })
    .then((resp) => {
      if (!resp.ok) recordHttpFailure(`HTTP ${resp.status}`)
    })
    .catch((e: unknown) => {
      const err = e as { name?: string; message?: string }
      const reason =
        err?.name === "AbortError" ? "Timeout" : (err?.message ?? String(err))
      recordHttpFailure(reason)
    })
    .finally(() => clearTimeout(timer))
}

function recordHttpFailure(reason: string): void {
  httpFailureCount += 1
  const now = Date.now()
  // 限速:每 100 次失败或距上次报警 ≥60s,才在 stderr 打一行
  if (
    httpFailureCount % FAILURE_WARN_EVERY === 0 ||
    now - lastHttpWarnAt >= FAILURE_WARN_INTERVAL_MS
  ) {
    lastHttpWarnAt = now
    // eslint-disable-next-line no-console
    console.error(
      `[log] endpoint unreachable: total_failed=${httpFailureCount} last_error="${reason}"`,
    )
  }
}

// ── 测试支持(仅供单测重置 module-level state 用)──────────────────────────

/** 测试用:重置失败计数,避免测试间互相污染。生产代码不要用。 */
export function _resetForTesting(): void {
  httpFailureCount = 0
  lastHttpWarnAt = 0
}
