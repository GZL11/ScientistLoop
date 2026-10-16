/**
 * billing-plugin.v2.ts — 生产版 billing plugin(替代实验版 billing_plugin.ts)
 *
 * 四个 hook(基于 design.md V1 + 后续 abort/error bug 修复):
 *
 *   1. event(session.error)
 *      → 接收 opencode 的 session.error 事件,把出错的 sessionID 标记到
 *        模块内 `erroredSessions` Map(TTL 5s 后自动清)。
 *        这是 tool.execute.after 判定"famou-build / evo-builder 是否真正完成"
 *        的唯一可靠信号 —— opencode 的 task tool 在 abort/error 时会用 lastAssistant
 *        兜底返回 partial 合法对象,output 永远非 null,不能用 output 判失败。
 *        IGNORED_ERROR_NAMES(ContextOverflowError)是 opencode 自己 compaction
 *        后继续推理的 recoverable 错误,不算失败,这里跳过。
 *
 *   2. tool.execute.before, task(subagent_type ∈ {famou-build, famou-evo-builder})
 *      → 共通:清掉同 master sid 上的旧 abort/error 标记
 *        (防 abort 后 < 5s 内重试的快速 build 被误判失败 skip)
 *      → famou-build 专属:ChargeClient.freeze(25)
 *        失败种类(全部进同一文案路径):
 *        - InsufficientQuota → 余额不足文案 + 充值链接
 *        - 其他(NetworkError / 5xx / runtime config 缺失 / env 缺失等)
 *          → "计费服务暂时异常" verbatim
 *        失败先经 billingLog → ./log 写到三路 sink(file + stdout/HTTP),
 *        master 收到 tool error 后逐字输出 verbatim,当轮 idle。
 *
 *   3. tool.execute.after, task(subagent_type=famou-build)
 *      → 查 erroredSessions:命中(master sid 或 output.metadata.sessionId 任一)
 *        → skip settle:ticket 留 active,charge TTL=3600 兜底 auto_settle,
 *           按 stage 当前累计 cost 结算(没 cost 过 → 用户付 0)。
 *           1h 内同 ticket 重启 freeze 25 幂等不重复扣。
 *      → 未命中(正常完成) → ChargeClient.settle(25)  (cost=25 + settle=true)
 *      → settle 失败:log + swallow,TTL 兜底
 *
 *   4. tool.execute.after, task(subagent_type=famou-evo-builder)
 *      → 跟 famou-build 同构,查 erroredSessions:
 *        - 命中 → skip cost
 *          * abort:上游(agentway)在事件传到 plugin 之前已 settle,
 *            这里 cost 会撞已 settled ticket → 必须 skip(正确性约束)
 *          * error:ticket 仍 active,同样 skip,让 TTL auto_settle 按当前
 *            stage 累计 cost 结算(用户付已完成轮的公平价格)
 *        - 未命中(一轮正常完成) → ChargeClient.cost(16)
 *
 * evolve 流程其它扣费职责(本 plugin 不管):
 *   - evolve 起飞 freeze 80      由上游(agentway)负责
 *   - evolve 正常完成 settle      由 evolution-loop.ts 在完成检测路径触发
 *   - evolve abort 时的 settle    由上游负责
 *   - evolve fatal error          不 settle,靠 charge TTL=3600 auto_settle 兜底
 *
 * 依赖:
 *   - ./lib/charge-client  ChargeClient 类、billingLog
 *   - ./lib/runtime-config loadRuntimeConfig() 读 user_id / agentway_session_id / baseUrl
 *                          (任何字段或 WEBAGENT_CHARGE_SERVER_URL env 缺失都 throw)
 *   - ./lib/log            setLogDirectory() 注册文件 sink + log() 三路 sink
 */

import type { Plugin } from "@opencode-ai/plugin"
import { consumeExempt } from "./lib/exempt-state"
import {
  ChargeClient,
  type ChargeResult,
  makeNoopChargeClient,
  billingLog,
} from "./lib/charge-client"
import { loadRuntimeConfig, isBillingEnabled } from "./lib/runtime-config"
import { setLogDirectory } from "./lib/log"

// ── 业务常量(故意不 export:金额改动应该走显式 review,文案改动不影响外部) ──

const BUILD_FREEZE_AMOUNT = 25
const BUILD_SETTLE_COST = 25
const EVOLVE_COST_PER_ROUND = 16

/** 充值跳转页面(相对路径,前端原生路由) */
const RECHARGE_URL = "/settings?tab=subscription&upgrade=true"

/**
 * InsufficientQuota 错误文案。
 *
 * 文案职责分离:
 * - plugin (这里) 负责"用户最终看到的字面内容"(<verbatim_message> 标签内)
 * - prompt 只负责行为约束(不 bypass / 不重试 / 不道歉)
 *
 * 结构 = 外层 meta-instruction(给 master 看)+ <verbatim_message> 标签
 * (master 必须逐字转发标签内内容)+ 行为兜底
 */
function buildInsufficientMsg(needed: number, available?: number): string {
  const balanceClause =
    available !== undefined ? `，当前余额仅 ${available} Credits` : ""
  return (
    `【系统提示】用户账户余额不足，执行暂停。请把 <verbatim_message> 标签内的内容` +
    `**逐字**输出给用户(保留 markdown 链接),标签和外层说明不要输出给用户。\n\n` +
    `<verbatim_message>\n` +
    `余额不足，本次求解任务需要 ${needed} Credits${balanceClause}。[立即充值](${RECHARGE_URL})\n` +
    `</verbatim_message>\n\n` +
    `不要尝试替代方案。`
  )
}

/** Charge 服务异常文案(网络 / 5xx / InvalidRequest 等)。不带链接,充值救不了网络问题。 */
function buildServiceErrMsg(): string {
  return (
    `【系统提示】计费服务暂时异常，执行暂停。请把 <verbatim_message> 标签内的内容` +
    `**逐字**输出给用户,标签和外层说明不要输出给用户。\n\n` +
    `<verbatim_message>\n` +
    `计费服务暂时异常，请稍后重试。\n` +
    `</verbatim_message>\n\n` +
    `不要尝试替代方案。`
  )
}

// ── factory(支持测试注入) ───────────────────────────────────────────────

export interface MakeBillingPluginOptions {
  /** 测试注入:绕过 loadRuntimeConfig + new ChargeClient,直接给 mock client */
  client?: ChargeClient
  /** 测试注入:重写金额 */
  amounts?: {
    buildFreeze?: number
    buildSettleCost?: number
    evolveCostPerRound?: number
  }
}

/**
 * 构造 plugin。生产路径调用 `makeBillingPlugin()`(无参),测试时传 mock client。
 */
export function makeBillingPlugin(opts: MakeBillingPluginOptions = {}): Plugin {
  const buildFreeze = opts.amounts?.buildFreeze ?? BUILD_FREEZE_AMOUNT
  const buildSettleCost = opts.amounts?.buildSettleCost ?? BUILD_SETTLE_COST
  const evolveCost = opts.amounts?.evolveCostPerRound ?? EVOLVE_COST_PER_ROUND

  return async ({ directory }) => {
    // 注册文件 sink 目录:`{directory}/hook.log`,所有 [from] 共写一个文件
    setLogDirectory(directory)

    // 失败 sessionID 标记:event hook 收到 session.error 时置位,after hook 查。
    //
    // 必要性:opencode 的 task tool 在 abort / API 错误等场景,内部用 lastAssistant
    // 兜底返回 partial 结果,所以 tool.execute.after 永远拿到合法 output 对象 ——
    // 仅靠 output 没法区分"真完成 vs 失败"。session.error 是 opencode 给我们唯一
    // 可靠的失败信号(参考 opencode/.../session/processor.ts halt + onInterrupt)。
    //
    // 时序保证(SSE 实测):master fiber interrupt 时,processor 的 onInterrupt
    // 同步 publish session.error,然后 task tool 才返回 partial,
    // after hook 比 event hook 晚 6-16ms 触发,标记一定先到位。所以这里直接
    // 同步查 Map 就够,不需要延迟 / setTimeout 协调。
    //
    // TTL 5s:abort/error 之后短时间内的 hook 都查得到,过期自动清避免泄漏。
    const erroredSessions = new Map<string, ReturnType<typeof setTimeout>>()
    const ERRORED_TTL_MS = 5000
    // ContextOverflowError opencode 自己 compaction 后继续推理,不算失败
    const IGNORED_ERROR_NAMES = new Set(["ContextOverflowError"])

    function markErrored(sessionID: string) {
      const prev = erroredSessions.get(sessionID)
      if (prev) clearTimeout(prev)
      erroredSessions.set(
        sessionID,
        setTimeout(() => erroredSessions.delete(sessionID), ERRORED_TTL_MS),
      )
    }

    // Path C 豁免：before-hook 命中 consumeExempt 时把 callID 记下来，
    // after-hook 据此 skip settle/cost。同进程同 plugin 实例，纯内存 Set 即可。
    const exemptedCallIDs = new Set<string>()

    // Lazy init:plugin load 时不立即读 runtime data,
    // 避免在 dev/CI 环境下没准备 runtime 文件就把 server 拖崩
    let cachedClient: ChargeClient | null = opts.client ?? null
    function getClient(): ChargeClient {
      if (!cachedClient) {
        // 计费开关 OFF(默认):返回 noop 替身,不读 runtime data 不调 charge,
        // freeze/cost/settle 全部 return ok=true,plugin 透明无感。
        // 生产部署必须显式设 WEBAGENT_BILLING_ENABLED=1 才会走真扣费路径。
        if (!isBillingEnabled()) {
          cachedClient = makeNoopChargeClient()
          return cachedClient
        }
        const cfg = loadRuntimeConfig()
        cachedClient = new ChargeClient({
          userId: cfg.userId,
          sessionId: cfg.agentwaySessionId, // 业务 session id 作 ticket
          directory,
          baseUrl: cfg.baseUrl,
        })
      }
      return cachedClient
    }

    return {
      /**
       * 监听 session.error,把出错的 sessionID 标记到 erroredSessions,
       * 给 tool.execute.after 用来判定 famou-build 是不是真正成功完成了。
       *
       * 命中范围:master sessionID + subagent sessionID 都标。abort 时两者都会
       * 各自发一次 session.error;subagent-only 的失败(LLM API error / AuthError 等)
       * 只在 subagent sid 上发。after hook 拿到 master sid + output.metadata.sessionId
       * (即 subagent sid),任一命中即视为失败。
       *
       * IGNORED_ERROR_NAMES:ContextOverflowError 是 opencode 自己 compaction 后
       * 继续推理的 recoverable 错误,不算失败。
       */
      event: async ({ event }: { event: { type: string; properties?: unknown } }) => {
        if (event.type !== "session.error") return
        const props = event.properties as Record<string, unknown> | undefined
        const sid = props?.sessionID as string | undefined
        const errName = (props?.error as { name?: string } | undefined)?.name
        if (!sid || !errName) return
        if (IGNORED_ERROR_NAMES.has(errName)) return
        markErrored(sid)
      },

      "tool.execute.before": async (input, output) => {
        if (input.tool !== "task") return
        const subagent = (output.args as { subagent_type?: string } | null)?.subagent_type

        // 一轮新 build / evo-builder 起飞:清掉同 master sid 上的旧 abort/error 标记。
        // 防"abort/error 残留 + 新一轮飞快完成 < 5s TTL → after hook 误判失败"。
        // evo-builder 路径尤其需要,因为 evolve 流程是连续多轮的
        // (上一轮 error → mark parent → 下一轮起飞间隔可能 1-3s,得清掉)。
        if (subagent === "famou-build" || subagent === "famou-evo-builder") {
          const prev = erroredSessions.get(input.sessionID)
          if (prev) {
            clearTimeout(prev)
            erroredSessions.delete(input.sessionID)
          }
        }

        if (subagent !== "famou-build") return

        // Path C 豁免检查：演化收尾的 famou-build 调用（master 收到 evolution-loop
        // 注入的"生成可视化产物"prompt 后派的 build）应该 skip freeze，不重复扣 25。
        // evolution-loop 在切 master 之前已经 markExempt(sessionID)；这里命中就
        // 记下 callID，让 after-hook 同步 skip settle/cost。
        if (consumeExempt(input.sessionID)) {
          exemptedCallIDs.add(input.callID)
          billingLog("info", "build.exempt_freeze", {
            reason: "post-evolve-viz",
            sessionID: input.sessionID,
            callID: input.callID,
          })
          return
        }

        // famou-build 起飞前 freeze
        // getClient() 可能在 lazy init 时 throw(runtime 数据 / env var 缺失);
        // freeze 调用本身可能 throw(理论上 charge-client 内部已 catch,但防御一层)。
        // 失败先经 billingLog → ./log 三路 sink(file 必到、HTTP 默认到、stdout 兜底),
        // 对外抛我们设计的 verbatim 文案 → master 逐字输出"计费服务暂时异常" → idle。
        let result: ChargeResult
        try {
          result = await getClient().freeze(buildFreeze)
        } catch (e) {
          billingLog("error", "freeze.config_error", { error: (e as Error).message })
          throw new Error(buildServiceErrMsg())
        }
        if (!result.ok) {
          if (result.code === "InsufficientQuota") {
            billingLog("error", "freeze.insufficient_quota", {
              needed: buildFreeze,
              available: result.availableCredits ?? null,
            })
            throw new Error(
              buildInsufficientMsg(buildFreeze, result.availableCredits),
            )
          }
          // 其他错误(网络 / 5xx / charge 服务异常)
          billingLog("error", "freeze.charge_error", {
            code: result.code,
            message: result.message,
          })
          throw new Error(buildServiceErrMsg())
        }
      },

      "tool.execute.after": async (input, output) => {
        if (input.tool !== "task") return
        const subagent = (input.args as { subagent_type?: string } | null)?.subagent_type

        if (subagent === "famou-build") {
          // Path C 豁免检查：本次 callID 在 before-hook 已被标记为豁免（演化收尾
          // viz build），同步 skip settle/cost，不动 ticket 状态。
          if (exemptedCallIDs.delete(input.callID)) {
            billingLog("info", "build.exempt_settle", {
              reason: "post-evolve-viz",
              callID: input.callID,
            })
            return
          }

          // 关键判定:famou-build 是真正完成,还是被 abort / 出错?
          //
          // ——不能靠 output:opencode 把 abort/error 都包成 partial 合法对象返回
          //   (task.ts 经 lastAssistant 兜底),output 永远非 null。
          // ——可靠信号:event hook 已经把"失败的 sessionID"记进 erroredSessions。
          //
          // 同一笔 build 涉及两个 sessionID:
          //   - input.sessionID = master 的 session(abort 时 master 也会发 session.error)
          //   - output.metadata.sessionId = subagent (famou-build) 自己的 session
          //     (LLM API error / AuthError 等只在 subagent sid 上发)
          // 任一命中 erroredSessions → 视为失败 → skip settle。
          //
          // skip 语义(沿用 design.md V1):
          //   ticket 留 active,charge TTL=3600 兜底 auto_settle,
          //   按 stage 当前累计的 cost 结算(我们没 cost 过,所以用户付 0)。
          //   1h 内同 ticket 重启 famou-build,freeze 25 在 charge 侧幂等不重复扣。
          const subagentSid = (output as unknown as {
            metadata?: { sessionId?: string }
          } | null)?.metadata?.sessionId
          const masterFailed = erroredSessions.has(input.sessionID)
          const subagentFailed = subagentSid ? erroredSessions.has(subagentSid) : false
          if (masterFailed || subagentFailed) {
            billingLog("info", "build.skip_settle", {
              reason: masterFailed ? "master_session_errored" : "subagent_session_errored",
              masterSessionID: input.sessionID,
              subagentSessionID: subagentSid ?? null,
            })
            return
          }

          // 正常退出 → settle (cost=25 + settle=true)
          // 失败:client 内部已 retry,这里只 swallow,日志写 stdout,TTL=3600 兜底
          try {
            await getClient().settle(buildSettleCost)
          } catch (e) {
            billingLog("warn", "settle.swallowed", { error: (e as Error).message })
          }
          return
        }

        if (subagent === "famou-evo-builder") {
          // 关键判定:这一轮 evo-builder 真完成了,还是被 abort / 出错?
          //
          // 跟 famou-build 同构:erroredSessions 里有 master sid(famou-evolution
          // 的 session)或 subagent sid(evo-builder 自己的 session)即视为失败。
          //
          // skip cost 的语义:
          //   - abort:上游(agentway)在事件传到 plugin 之前就 settle 了 ticket,
          //     这里再 cost 会撞已 settled 的 ticket → 必须 skip(正确性约束,
          //     参考 design.md §3)
          //   - error:ticket 还 active,我们仍然 skip,让 charge TTL=3600 按
          //     stage 当前累计 cost 结算(用户付已完成轮的公平价格)
          const subagentSid = (output as unknown as {
            metadata?: { sessionId?: string }
          } | null)?.metadata?.sessionId
          const masterFailed = erroredSessions.has(input.sessionID)
          const subagentFailed = subagentSid ? erroredSessions.has(subagentSid) : false
          if (masterFailed || subagentFailed) {
            billingLog("info", "evo.skip_cost", {
              reason: masterFailed ? "master_session_errored" : "subagent_session_errored",
              masterSessionID: input.sessionID,
              subagentSessionID: subagentSid ?? null,
            })
            return
          }

          // 正常每轮完成 → cost(16)
          try {
            await getClient().cost(evolveCost)
          } catch (e) {
            billingLog("warn", "cost.swallowed", { error: (e as Error).message })
          }
          return
        }
      },
    }
  }
}

// 默认导出供 opencode plugin loader 加载(生产路径)
export default makeBillingPlugin()
