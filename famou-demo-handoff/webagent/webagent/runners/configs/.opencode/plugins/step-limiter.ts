import type { Plugin } from "@opencode-ai/plugin"
import { existsSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { isEvolutionActive, getActiveEvolutionDir } from "./lib/evolution-state"
import { log, setLogDirectory, type LogLevel } from "./lib/log"

/**
 * Step Limiter Plugin — 替代 opencode 原生 MAX_STEPS。
 *
 * 背景：opencode 原生 step limit（agent.steps）触发时会向消息列表末尾注入一条
 * `role: "assistant"` 的提示（max-steps.txt），但 Bedrock 上的 Claude 4.6 不支持
 * assistant message prefill，会报 400 ValidationException。详见 sst/opencode#13768。
 *
 * 本 plugin 通过 tool.execute.after 在子 session 的工具调用上做计数，到阈值时
 * 把 wrap-up 提示以 <system-reminder> 形式追加到 tool_result 末尾（user role 上下文，
 * Bedrock 兼容）。配套要求 famou-evo-builder 的 frontmatter 不设 steps（默认 Infinity），
 * 让原生路径不再触发。
 *
 * 守卫：isEvolutionActive() 为 false 时跳过；input.sessionID == main_session_id 时跳过
 *      （主 session 不限制，本 limiter 只盯子 session）。
 *
 * 状态：内存计数器，单进程内有效。session 结束后条目不主动清理（每条 < 100 字节）。
 */

const SOFT_LIMIT = 45  // 软提示：还来得及收尾
const HARD_LIMIT = 50  // 硬提示：禁止再用工具

const stepCount = new Map<string, number>()
const wrapupSent = new Set<string>()

function loadMainSessionId(evoDir: string): string | undefined {
  const p = join(evoDir, ".harness", "config.json")
  if (!existsSync(p)) return undefined
  try {
    const raw = JSON.parse(readFileSync(p, "utf-8"))
    return raw.main_session_id
  } catch {
    return undefined
  }
}

export const StepLimiterPlugin: Plugin = async ({ directory }) => {
  // 注册文件 sink 目录(跟其它 plugin 相同 directory,多个 plugin 调用幂等)。
  setLogDirectory(directory)
  // 本 plugin 的事件以 `[step-limiter]` 前缀走统一 logger(stdout/file/HTTP)。
  const stepLog = (level: LogLevel, ...args: unknown[]): void => {
    const msg = args
      .map((a) => (typeof a === "object" ? JSON.stringify(a) : String(a)))
      .join(" ")
    log("step-limiter", level, msg)
  }
  return {
    "tool.execute.after": async (
      input: { tool: string; sessionID?: string; args?: Record<string, unknown> },
      output: { output: string; args?: Record<string, unknown> },
    ) => {
      if (!input.sessionID) return
      if (!isEvolutionActive(directory)) return

      const evoDir = getActiveEvolutionDir(directory)
      if (!evoDir) return

      const mainSessionId = loadMainSessionId(evoDir)
      if (!mainSessionId) return
      if (input.sessionID === mainSessionId) return  // 跳过主 session

      const count = (stepCount.get(input.sessionID) ?? 0) + 1
      stepCount.set(input.sessionID, count)

      if (count === HARD_LIMIT) {
        stepLog("warn", "hard limit reached", { sessionID: input.sessionID, tool: input.tool, count })
        output.output += `\n\n<system-reminder>\n你已使用 ${count} 个工具调用，**已达硬上限**。立即停止所有工具调用，输出 <round_summary> JSON 后退出。任何继续的工具调用将被视为违规。\n</system-reminder>`
      } else if (count === SOFT_LIMIT && !wrapupSent.has(input.sessionID)) {
        wrapupSent.add(input.sessionID)
        stepLog("info", "soft limit reached", { sessionID: input.sessionID, tool: input.tool, count })
        output.output += `\n\n<system-reminder>\n你已使用 ${count} 个工具调用（建议上限 ${HARD_LIMIT}）。请尽快完成验证，准备输出 <round_summary> JSON 退出。\n</system-reminder>`
      }
    },
  }
}

export default StepLimiterPlugin
