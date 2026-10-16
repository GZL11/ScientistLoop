import type { Plugin, PluginInput } from "@opencode-ai/plugin"
import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import {
  DEFAULT_EVOLUTION_AGENT,
  DEFAULT_MASTER_AGENT,
  clearState,
  readState,
} from "./lib/evolution-state"
// ── billing 接入 ──
import {
  ChargeClient,
  makeNoopChargeClient,
  billingLog,
} from "./lib/charge-client"
import { loadRuntimeConfig, isBillingEnabled } from "./lib/runtime-config"
import { markExempt } from "./lib/exempt-state"
import { log, setLogDirectory, type LogLevel } from "./lib/log"

/**
 * Evolution Loop Plugin — 循环控制。
 *
 * 核心机制：
 * 1. /evolve command 触发时，evolution agent 调 init_evolution 创建 workspace，
 *    同时激活循环状态（写 .evolution/state.md）
 * 2. session.idle 时检测 agent 输出中是否有 <promise>演化完成</promise>
 *    - 没有 → 读 config.json 判断 iteration < budget → 注入 continuation
 *    - 有 → 清除状态 → 注入 agent=famou-master 的切回消息
 * 3. session.deleted / session.error(abort) → 清除状态
 *
 * agent 回切依赖 default_agent=famou-master（opencode.jsonc），
 * 演化结束后用户手动输入自动回到 master，无需 chat.message hook。
 *
 * 状态文件：
 * - {cwd}/.evolution/state.md — 循环是否 active（lib/evolution-state 管理）
 * - {evo_dir}/.harness/config.json — iteration/budget（fm-evolution hook 管理）
 *
 * 注意：state.md 的读写、isEvolutionActive 等共享逻辑放在 lib/evolution-state.ts。
 * 不要在本文件再 export helper 函数 —— opencode plugin loader 会把每个 function 类型
 * 的 named export 都当 plugin 调一次，把 helper 当 plugin 调会用错的参数类型，导致
 * "paths[0] must be of type string, got object" 这类错误。
 */

// config.json — 演化配置（fm-evolution hook 管理 iteration）
interface EvoConfig {
  budget: number
  iteration: number
  solution_pattern: string
}

// ── config.json 读取 ──

function readEvoConfig(evolutionDir: string): EvoConfig | null {
  const p = join(evolutionDir, ".harness", "config.json")
  if (!existsSync(p)) return null
  try {
    const raw = JSON.parse(readFileSync(p, "utf-8"))
    return {
      budget: raw.budget ?? 20,
      iteration: raw.iteration ?? 0,
      solution_pattern: raw.solution_pattern ?? "solution*",
    }
  } catch {
    return null
  }
}

// ── 完成检测 ──

async function detectCompletion(
  client: PluginInput["client"],
  sessionID: string,
  promise: string,
  directory: string,
  evolutionAgent: string,
): Promise<boolean> {
  try {
    const response = await Promise.race([
      client.session.messages({
        path: { id: sessionID },
        query: { directory },
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("API timeout")), 3000),
      ),
    ])

    const messages = (response as { data?: unknown[] }).data ?? []
    if (!Array.isArray(messages)) return false

    // 只看 evolution 父 agent 的发言。messages 流里同时含父和 task 派出的 evo-builder
    // 子 agent 输出，如果不过滤，evo-builder 在自己的 status 描述里偶然出现完成标记
    // 字样会被误判为完成。
    const assistantMessages = (messages as Array<{
      info?: { role?: string; agent?: string }
      parts?: Array<{ type: string; text?: string }>
    }>).filter((msg: any) =>
      msg.info?.role === "assistant" && msg.info?.agent === evolutionAgent,
    )

    const lastAssistant = assistantMessages[assistantMessages.length - 1]
    if (!lastAssistant?.parts) return false

    const pattern = new RegExp(`<promise>\\s*${promise.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*</promise>`, "is")
    const text = lastAssistant.parts
      .filter((p: any) => p.type === "text")
      .map((p: any) => p.text ?? "")
      .join("\n")

    return pattern.test(text)
  } catch {
    return false
  }
}

// ── 最后一条 assistant 的 agent ──

async function getLastAssistantAgent(
  client: PluginInput["client"],
  sessionID: string,
  directory: string,
): Promise<string | undefined> {
  try {
    const response = await Promise.race([
      client.session.messages({
        path: { id: sessionID },
        query: { directory },
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("API timeout")), 3000),
      ),
    ])

    const messages = (response as { data?: unknown[] }).data ?? []
    if (!Array.isArray(messages)) return undefined

    const assistantMessages = (messages as Array<{
      info?: { role?: string; agent?: string }
    }>).filter((msg: any) => msg.info?.role === "assistant")

    return assistantMessages[assistantMessages.length - 1]?.info?.agent
  } catch {
    return undefined
  }
}

// ── Plugin 导出 ──

export const EvolutionLoopPlugin: Plugin = async (ctx: PluginInput) => {
  const { directory, client } = ctx
  // 注册文件 sink 目录(跟 billing-plugin 相同 directory,幂等),
  // 所有 plugin hook 共写 `{directory}/hook.log`,靠 `[<from>]` 区分。
  setLogDirectory(directory)
  // 本 plugin 的事件以 `[evolution-loop]` 前缀走统一 logger(stdout/file/HTTP)。
  // 用 args 拼 message 是为了兼容旧 loopLog(msg, ctxObj) / loopLog(msg, e) 调用风格。
  const loopLog = (level: LogLevel, ...args: unknown[]): void => {
    const msg = args
      .map((a) => (typeof a === "object" ? JSON.stringify(a) : String(a)))
      .join(" ")
    log("evolution-loop", level, msg)
  }
  // 最近 5 秒收到 session.error 的 sessionID → 错误信息
  // 用于在紧接而至的 session.idle 上判定 fatal halt（参考 opencode session/processor.ts
  // halt：fatal error 会同步 publish Error + status.set(idle)；ContextOverflowError
  // 只 publish 不 idle，由 opencode 自己 compaction 后继续，不会被这个窗口捕获）。
  const pendingError = new Map<string, { name?: string }>()

  // ── billing: lazy charge client + 正常完成 settle ──
  // 与 billing-plugin 共用 agentwaySessionId 作 ticket(同一对话同一 ticket)。
  // 失败 swallow:charge 内部已 retry,这里再失败靠 TTL=3600 auto_settle 兜底,
  // 不阻塞 master agent 切换(用户体验比 settle 重要)。
  // abort / fatal halt 路径不动:abort 上游负责 settle / fatal 靠 TTL 兜底(按 stage 结算)。
  //
  // 计费总开关 OFF 时返回 noop client,settleAndLog 也是 ok=true 透明走过,
  // 没扣费但 evolution-loop 自身的 master 切换不受影响。
  let cachedChargeClient: ChargeClient | null = null
  function getChargeClient(): ChargeClient {
    if (!cachedChargeClient) {
      if (!isBillingEnabled()) {
        cachedChargeClient = makeNoopChargeClient()
        return cachedChargeClient
      }
      const cfg = loadRuntimeConfig()
      cachedChargeClient = new ChargeClient({
        userId: cfg.userId,
        sessionId: cfg.agentwaySessionId,
        directory,
        baseUrl: cfg.baseUrl,
      })
    }
    return cachedChargeClient
  }

  async function settleAndLog(reason: string): Promise<void> {
    try {
      const r = await getChargeClient().settle()
      // 双通道(同一 hook.log 不同 [from] 前缀):
      //  - billingLog → `[billing]` 体系,跟 billing-plugin 的 freeze/settle 串成完整账单流水
      //  - loopLog    → `[evolution-loop]` 体系,保留演化流程完整运行轨迹
      const code = r.ok ? "0" : r.code
      billingLog("info", "evolve.settle_done", { reason, code })
      loopLog("info", "billing settle done", { reason, ok: r.ok, code })
    } catch (e) {
      const error = String(e)
      billingLog("error", "evolve.settle_failed", { reason, error })
      loopLog("error", "billing settle threw", { reason, error })
    }
  }

  /**
   * 统一的演化终止流程：清状态 + 切 master agent 让其按 prompt 输出结尾，
   * 保证所有终止场景（abort / fatal / 完成 / budget）以一段 master message 收尾，
   * 上游可以靠这个统一信号识别演化结束。
   *
   * - state.active 且 sessionID 是主 session：清 state.md，切 master 走 active prompt
   * - state.active 但 sessionID 不是主 session（如父+子同时报错时的子 session 事件）：跳过
   * - state 不存在但当前 agent 是 famou-evolution：init_evolution 之前的早期阶段，
   *   不清 state（本来就没有），直接在当前 session 切 master 走 preInit prompt
   * - 其它情况：什么都不做
   */
  async function terminateEvolution(
    eventSessionID: string,
    prompts: { active: string; preInit: string },
  ): Promise<void> {
    const state = readState(directory)
    if (state && state.active) {
      if (state.session_id && state.session_id !== eventSessionID) {
        loopLog("info", "terminate skipped: not main session", {
          sessionID: eventSessionID, mainSession: state.session_id,
        })
        return
      }
      clearState(directory)
      const mainSessionID = state.session_id ?? eventSessionID
      const masterAgent = state.master_agent ?? DEFAULT_MASTER_AGENT
      try {
        await client.session.prompt({
          path: { id: mainSessionID },
          body: { agent: masterAgent, parts: [{ type: "text", text: prompts.active }] },
          query: { directory },
        })
        loopLog("info", "terminate (active) accepted", { sessionID: mainSessionID })
      } catch (e) {
        loopLog("error", "terminate (active) failed", e)
      }
      return
    }

    const agent = await getLastAssistantAgent(client, eventSessionID, directory)
    if (agent === DEFAULT_EVOLUTION_AGENT) {
      try {
        await client.session.prompt({
          path: { id: eventSessionID },
          body: { agent: DEFAULT_MASTER_AGENT, parts: [{ type: "text", text: prompts.preInit }] },
          query: { directory },
        })
        loopLog("info", "terminate (pre-init) accepted", { sessionID: eventSessionID })
      } catch (e) {
        loopLog("error", "terminate (pre-init) failed", e)
      }
    }
  }

  return {
    event: async ({ event }: { event: { type: string; properties?: unknown } }) => {
      const props = event.properties as Record<string, unknown> | undefined

      // ── session.idle → fatal 检测 / 续轮 / 停止 ──
      if (event.type === "session.idle") {
        const sessionID = props?.sessionID as string | undefined
        if (!sessionID) return

        // session.error 后 5 秒内紧接的 idle = fatal halt，触发统一终止流程。
        const errorInfo = pendingError.get(sessionID)
        if (errorInfo) {
          pendingError.delete(sessionID)
          loopLog("warn", "fatal halt detected", { sessionID, errorName: errorInfo.name })
          await terminateEvolution(sessionID, {
            active: "演化已异常终止，请告知用户。",
            preInit: "演化已异常终止，请告知用户。",
          })
          return
        }

        const state = readState(directory)
        if (!state || !state.active) return
        // 只处理主 session 的 idle 事件，忽略子 session（task 创建的）
        if (state.session_id && state.session_id !== sessionID) {
          loopLog("info", "session.idle skipped: not main session", { sessionID, mainSession: state.session_id })
          return
        }

        loopLog("info", "session.idle", { sessionID })

        // 检测完成标记（只看 evolution 父 agent 的发言）
        const completed = await detectCompletion(
          client, sessionID, state.completion_promise, directory,
          state.agent ?? DEFAULT_EVOLUTION_AGENT,
        )

        if (completed) {
          loopLog("info", "completion detected, stopping", { sessionID })
          clearState(directory)
          await settleAndLog("completion") // ← billing: 正常完成 settle
          // billing: 标记下一次 famou-build 豁免扣费（master 收到注入 prompt 后
          // 会派 build 生成 viz，这次 build 属于演化收尾，不应再扣 25）
          markExempt(sessionID)
          const masterAgent = state.master_agent ?? DEFAULT_MASTER_AGENT
          loopLog("info", "switching to master", { agent: masterAgent, sessionID })
          try {
            await client.session.prompt({
              path: { id: sessionID },
              body: {
                agent: masterAgent,
                parts: [{ type: "text", text: "演化已完成。请基于演化最优结果生成可视化产物并交付给用户，同时总结演化的优化效果。" }],
              },
              query: { directory },
            })
            loopLog("info", "master switch prompt accepted", { sessionID })
          } catch (e) {
            loopLog("error", "failed to switch to master (completion)", e)
          }
          return
        }

        // 读 config.json 获取 iteration 和 budget
        const evoDir = state.evolution_dir
        if (!evoDir) return

        const config = readEvoConfig(evoDir)
        if (!config) return

        // 达到最大迭代次数
        if (config.iteration >= config.budget) {
          loopLog("info", "budget reached", { iteration: config.iteration, budget: config.budget, sessionID })
          clearState(directory)
          await settleAndLog("budget reached") // ← billing: 正常完成(跑满)settle
          // billing: 同 completion 分支，标记下一次 famou-build 豁免扣费
          markExempt(sessionID)
          const masterAgent = state.master_agent ?? DEFAULT_MASTER_AGENT
          loopLog("info", "switching to master", { agent: masterAgent, sessionID })
          try {
            await client.session.prompt({
              path: { id: sessionID },
              body: {
                agent: masterAgent,
                parts: [{ type: "text", text: `演化已达到最大轮数 (${config.budget})。请基于演化最优结果生成可视化产物并交付给用户，同时总结演化的优化效果。` }],
              },
              query: { directory },
            })
            loopLog("info", "master switch prompt accepted", { sessionID })
          } catch (e) {
            loopLog("error", "failed to switch to master (budget)", e)
          }
          return
        }

        // 续轮
        loopLog("info", "continuing", { iteration: config.iteration, budget: config.budget, sessionID })
        const continuationPrompt = [
          `开始第 ${config.iteration + 1}/${config.budget} 轮演化。`,
          ``,
          `演化工作空间：${evoDir}`,
          `代码文件匹配：${config.solution_pattern}（匹配的文件会被自动评估和归档）`,
          ``,
          `请完成以下步骤：`,
          `1. 读 ${evoDir}/status.md 了解当前状态`,
          `2. 派发新的 famou-evo-builder（不要传 task_id），task prompt 需包含演化工作空间路径和代码文件匹配模式`,
          `3. evo-builder 返回后，诊断并更新 INDEX.md Approach 列、status.md 的 Population Summary 和 Diagnosis`,
          `4. 判断是否停止`,
        ].join("\n")

        try {
          await client.session.prompt({
            path: { id: sessionID },
            body: {
              agent: state.agent ?? DEFAULT_EVOLUTION_AGENT,
              parts: [{ type: "text", text: continuationPrompt }],
            },
            query: { directory },
          })
        } catch (e) {
          loopLog("error", "failed to inject continuation", e)
        }
      }

      // ── session.deleted → 清除状态 ──
      if (event.type === "session.deleted") {
        const sessionInfo = props?.info as { id?: string } | undefined
        if (sessionInfo?.id) {
          const state = readState(directory)
          if (state && state.active) {
            clearState(directory)
          }
          pendingError.delete(sessionInfo.id)
        }
      }

      // ── session.error → abort 走统一终止；其它错误暂存等 idle 判 fatal ──
      if (event.type === "session.error") {
        const sessionID = props?.sessionID as string | undefined
        const error = props?.error as { name?: string } | undefined

        loopLog("warn", "session.error", { sessionID, errorName: error?.name })

        if (error?.name === "MessageAbortedError" && sessionID) {
          await terminateEvolution(sessionID, {
            active: "演化已被用户取消，请告知用户。",
            preInit: "演化已被用户取消，请告知用户。",
          })
          return
        }

        // 非 abort 错误：先暂存，由后续 5 秒内紧接的 session.idle 在 idle 分支
        // 判定 fatal halt 并触发 terminateEvolution。ContextOverflowError 这种
        // 不会 idle 的错误会自然过期，不会被错杀。
        if (sessionID) {
          pendingError.set(sessionID, { name: error?.name })
          setTimeout(() => pendingError.delete(sessionID), 5000)
        }
      }
    },

    tool: {},
  }
}

export default EvolutionLoopPlugin
