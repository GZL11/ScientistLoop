/**
 * ChargeClient — Charge `PUT /v1/quotas` 的 HTTP 客户端
 *
 * 设计见 ./design.md (V1)。
 * Charge API 接口见 ./charge_api.md。
 *
 * 三个写操作:
 *   - freeze(amount)        冻结
 *   - cost(amount)          上报消耗(不结算)
 *   - settle(finalCost?)    结算(可选携带最后一笔 cost)
 *
 * 重试策略(Q3 锁定):
 *   - 网络错误 / Timeout / 5xx / ConcurrentAccess  → 重试 2 次,backoff 50ms + 200ms
 *   - InsufficientQuota / InvalidRequest 等业务错  → 不重试,直接返回
 *   - 重试时 operate_id 保持不变(spec §4.2 幂等,Charge 自动回放首次结果不会重复扣费)
 *
 * 调用方处理(plugin 层):
 *   - freeze 失败 → throw Error 让 master prompt 接管
 *   - cost / settle 失败 → log + 静默 swallow (TTL=3600 兜底)
 */

import { log, type LogLevel } from "./log"

const PRODUCT = "WebAgent"
const QUOTA_NAME = "credit"
const SETTLE_TTL = 3600
const HTTP_TIMEOUT_MS = 5000
const RETRY_BACKOFFS_MS = [50, 200]
/** 业务码里值得重试的(网络/timeout 是 transport 层另算) */
const RETRYABLE_CODES = new Set(["ConcurrentAccess", "InternalServerError"])

// ── 类型 ───────────────────────────────────────────────────────────────────

export interface ChargeStage {
  total_freeze: number
  total_cost: number
  freeze_remain: number
  settled_cost: number
  released_credit: number
  expired_credit: number
}

export interface ChargeAvailable {
  total: number
  daily: number
  package: number
  bonus: number
}

export interface ChargeData {
  ticket: string
  operate_id: string
  product: string
  quota_name: string
  op: "freeze" | "cost" | "release" | "settle" | "auto_settle"
  status: "active" | "settled" | "auto_settled" | "compensated"
  settle_seq: number
  stage: ChargeStage
  available_credits: ChargeAvailable
}

export type ChargeResult =
  | { ok: true; data: ChargeData; retried: number }
  | {
      ok: false
      code: string
      message: string
      retried: number
      /** 失败响应里如果带回 data.available_credits.total,在这里透出。
       *  目前主要用途:InsufficientQuota 时在错误消息里告诉用户当前余额。
       *  charge 团队若改字段路径,只需改 tryOnce() 里的解析。 */
      availableCredits?: number
    }

export interface ChargeClientOptions {
  /** Charge x-user-id header,用户唯一标识 */
  userId: string
  /** 同时也是 ticket(同对话所有计费用同一个 ticket) */
  sessionId: string
  /**
   * @deprecated refactor 后 ChargeClient 不再自己写 log 文件,改由 `./log` 的
   * 模块级 `setLogDirectory(dir)` 统一管(plugin 在初始化时已经调过)。
   * 字段保留只是为了不破坏现有 caller(billing-plugin / 测试都还在传),
   * 在 ChargeClient 内部不读不用,新代码不要依赖。
   */
  directory?: string
  /** Charge 服务 base URL(默认 http://127.0.0.1:8080,本地 port-forward) */
  baseUrl?: string
  /** 注入 fetch(测试用) */
  fetcher?: typeof fetch
  /** 注入 sleep(测试用,跳 backoff) */
  sleep?: (ms: number) => Promise<void>
  /** 单次 HTTP 超时(ms),默认 5000 */
  timeoutMs?: number
  /** 注入 log sink(测试用,绕过 stdout/file/HTTP 三路 sink,直接收 line 字符串) */
  log?: (line: string) => void
}

// ── helpers ────────────────────────────────────────────────────────────────

function shortUuid(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 12)
}

async function defaultSleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

// ── ChargeClient ──────────────────────────────────────────────────────────

export class ChargeClient {
  private userId: string
  private sessionId: string
  private baseUrl: string
  private fetcher: typeof fetch
  private sleep: (ms: number) => Promise<void>
  private timeoutMs: number
  private extLog: ((line: string) => void) | null

  constructor(opts: ChargeClientOptions) {
    this.userId = opts.userId
    this.sessionId = opts.sessionId
    // opts.directory:deprecated,refactor 后不再用,见 ChargeClientOptions 注释
    this.baseUrl = (opts.baseUrl ?? "http://127.0.0.1:8080").replace(/\/$/, "")
    this.fetcher = opts.fetcher ?? fetch
    this.sleep = opts.sleep ?? defaultSleep
    this.timeoutMs = opts.timeoutMs ?? HTTP_TIMEOUT_MS
    this.extLog = opts.log ?? null
  }

  /** 冻结 amount 信用点 */
  async freeze(amount: number): Promise<ChargeResult> {
    return this.put({ freeze: amount }, "freeze")
  }

  /** 上报 amount 信用点消耗(不结算) */
  async cost(amount: number): Promise<ChargeResult> {
    return this.put({ cost: amount }, "cost")
  }

  /**
   * 结算当前阶段。
   * @param finalCost 可选:>0 时同时上报最后一笔消耗 + 结算
   *                  (对应 spec "最后一笔消耗并结算"组合)。
   *                  正常 build 流程结束时用 settle(25),evolve 收尾用 settle()。
   */
  async settle(finalCost?: number): Promise<ChargeResult> {
    const extra: Record<string, unknown> = { settle: true }
    if (finalCost && finalCost > 0) extra.cost = finalCost
    return this.put(extra, "settle")
  }

  // ── 内部 ─────────────────────────────────────────────────────────────────

  private async put(
    extra: Record<string, unknown>,
    op: "freeze" | "cost" | "settle",
  ): Promise<ChargeResult> {
    // operate_id 一次生成,重试时复用 —— 关键:Charge 用它做幂等,
    // 重试不会重复扣费(spec §4.2)。
    const operate_id = `op-${this.sessionId}-${op}-${shortUuid()}`
    const body = {
      ticket: this.sessionId,
      operate_id,
      product: PRODUCT,
      quota_name: QUOTA_NAME,
      settle_ttl: SETTLE_TTL,
      ...extra,
    }

    for (let attempt = 0; attempt <= RETRY_BACKOFFS_MS.length; attempt++) {
      const start = Date.now()
      const result = await this.tryOnce(body)
      const elapsed = Date.now() - start

      // 把当前 retried 计数(已经重试过几次)绑到结果里
      result.retried = attempt

      this.logOne(op, body, result, elapsed)

      if (result.ok) return result

      // 是否可重试
      const isRetryable =
        result.code === "NetworkError" ||
        result.code === "Timeout" ||
        RETRYABLE_CODES.has(result.code)

      if (!isRetryable || attempt >= RETRY_BACKOFFS_MS.length) {
        return result
      }

      await this.sleep(RETRY_BACKOFFS_MS[attempt])
    }
    // 循环每次迭代必从内部 return —— 不可达,这里仅为 TS 类型完备
    throw new Error("unreachable: charge-client put() exited loop without return")
  }

  private async tryOnce(body: Record<string, unknown>): Promise<ChargeResult> {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs)
    try {
      const resp = await this.fetcher(`${this.baseUrl}/v1/quotas`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "x-user-id": this.userId,
          "x-bce-request-id": `req-${shortUuid()}`,
        },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
      clearTimeout(timer)

      if (resp.status >= 500) {
        return {
          ok: false,
          code: "InternalServerError",
          message: `HTTP ${resp.status}`,
          retried: 0,
        }
      }
      // 4xx: spec 说业务错误也走 200。如果真的拿到 4xx 那是网关/路由层问题,不重试。
      if (resp.status >= 400) {
        return {
          ok: false,
          code: "InvalidRequest",
          message: `HTTP ${resp.status}`,
          retried: 0,
        }
      }
      const json = (await resp.json()) as {
        code?: string
        message?: string
        data?: Partial<ChargeData>
      }
      if (json && json.code === "0" && json.data) {
        return { ok: true, data: json.data as ChargeData, retried: 0 }
      }
      return {
        ok: false,
        code: (json && json.code) || "UnknownError",
        message: (json && json.message) || "no message",
        retried: 0,
        // 失败响应若携带 data.available_credits.total,透出给调用方
        // (目前 InsufficientQuota 老版本响应不带,charge 团队正在补;补完后这里自动生效)
        availableCredits: json?.data?.available_credits?.total,
      }
    } catch (e: unknown) {
      clearTimeout(timer)
      const err = e as { name?: string; message?: string }
      const isAbort = err?.name === "AbortError"
      return {
        ok: false,
        code: isAbort ? "Timeout" : "NetworkError",
        message: String(err?.message ?? err),
        retried: 0,
      }
    }
  }

  private logOne(
    op: string,
    body: Record<string, unknown>,
    result: ChargeResult,
    elapsed: number,
  ): void {
    const ticketShort = this.sessionId.slice(-12)
    const amount = (body.freeze ?? body.cost ?? "—") as string | number
    const settleMark = body.settle ? "+settle" : ""
    const code = result.ok ? "0" : result.code
    // message 不含 [charge] 前缀(由 log() 统一加),但保留 UTC timestamp
    // (charge 行的 timestamp 是 HTTP attempt 的真实时刻,有审计价值)。
    const message =
      `${new Date().toISOString()} ` +
      `${op}${settleMark} ticket=${ticketShort} amount=${amount} retried=${result.retried} ` +
      `→ code=${code} elapsed=${elapsed}ms`

    // 测试路径:extLog 注入用于断言 retry 行为。
    // 喂给 extLog 的是渲染后整行(含 [charge] [level] 前缀),跟 stdout/file 一致。
    const level = chargeResultLevel(result)
    if (this.extLog) {
      this.extLog(`[charge] [${level}] ${message}`)
      return
    }

    // 生产路径:走统一 logger(stdout / file / HTTP forward 三路 sink)
    log("charge", level, message)
  }
}

/** charge 结果映射到 log level:成功 info / 可重试错误 warn / 终态错误 error */
function chargeResultLevel(result: ChargeResult): LogLevel {
  if (result.ok) return "info"
  if (result.code === "NetworkError" || result.code === "Timeout") return "warn"
  if (RETRYABLE_CODES.has(result.code)) return "warn"
  return "error"
}

// ── billing 层统一日志接口(thin wrappers,实现在 ./log)────────────────────

/**
 * billing-plugin / evolution-loop 共用的日志器。
 *
 * stdout/file/HTTP 三路 sink 由 `./log` 模块统一管,见那里的文档。
 * 这里只负责把 `event` + `ctx` 拼成 message,然后 fwd 给 `log("billing", ...)`.
 *
 * 格式:  `[billing] [LEVEL] event.tag key1=val1 key2=val2 ...`
 *
 * level 取值:
 *   - info  = 预期事件(skip 路径、settle 成功)
 *   - warn  = 已 swallow 的失败(settle/cost 失败,TTL 兜底)
 *   - error = throw 给用户的失败(config 缺失 / charge 错误 / 余额不足)
 * event.tag 点号分隔便于 grep:freeze.config_error / settle.swallowed / 等
 */
export type BillingLogLevel = LogLevel

export function billingLog(
  level: BillingLogLevel,
  event: string,
  ctx?: Record<string, unknown>,
): void {
  const ctxStr =
    ctx && Object.keys(ctx).length > 0
      ? " " +
        Object.entries(ctx)
          .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
          .join(" ")
      : ""
  log("billing", level, `${event}${ctxStr}`)
}

// ── noop client(billing disabled 时使用)──────────────────────────────────

/**
 * 计费总开关 OFF 时返回的 ChargeClient 替身。
 *
 * - freeze / cost / settle 全部返回 ok=true 的 result,plugin 不感知
 * - 不访问 charge HTTP,不读 runtime data,不打 log
 * - stage 字段全为 0,available_credits 为 0
 *
 * 用法:在 plugin 的 lazy `getClient()` 入口判断 isBillingEnabled() === false 时
 * 直接返回此对象。其他逻辑(retry / 文案 / TTL 兜底)对 plugin 来说完全透明。
 */
export function makeNoopChargeClient(): ChargeClient {
  const noopData: ChargeData = {
    ticket: "noop",
    operate_id: "noop",
    product: PRODUCT,
    quota_name: QUOTA_NAME,
    op: "freeze",
    status: "active",
    settle_seq: 0,
    stage: {
      total_freeze: 0,
      total_cost: 0,
      freeze_remain: 0,
      settled_cost: 0,
      released_credit: 0,
      expired_credit: 0,
    },
    available_credits: { total: 0, daily: 0, package: 0, bonus: 0 },
  }
  const noopResult: ChargeResult = { ok: true, data: noopData, retried: 0 }
  // 用 duck-typing 返回,不继承 ChargeClient(避免触发 constructor / 文件 IO)
  return {
    freeze: async () => noopResult,
    cost: async () => noopResult,
    settle: async () => noopResult,
  } as unknown as ChargeClient
}
