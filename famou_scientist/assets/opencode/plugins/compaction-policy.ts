/**
 * famou-scientist compact 后续跑策略 plugin。
 *
 * 目标：
 *   1. compact 本身继续保留，避免长上下文直接爆窗；
 *   2. compact 后的 synthetic auto-continue 不再使用泛化的
 *      "Continue if you have next steps..."，而是收窄到最后一个真实用户请求；
 *   3. 轻量问答默认不自动续跑，避免 agent 在用户没有要求时自顾自推进。
 *
 * 依赖：
 *   - OpenCode 原生 hook `experimental.compaction.autocontinue` 可控制 enabled；
 *   - Famou runtime patch `compaction-autocontinue-text-hook` 扩展该 hook，使 output.text
 *     可以替换 synthetic continue 文本。没有 runtime patch 时，本插件仍能做 enabled gating。
 */
import type { Plugin } from "@opencode-ai/plugin"
import fs from "node:fs"

const POLICY_OFF = /^(1|true|yes)$/i.test(process.env.ARC_COMPACTION_POLICY_OFF || "")
const DEBUG_LOG = process.env.ARC_COMPACTION_POLICY_DEBUG

function dlog(m: string): void {
  if (!DEBUG_LOG) return
  try {
    fs.appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${m}\n`)
  } catch {
    /* ignore */
  }
}

function messageText(message: any): string {
  return (message?.parts || [])
    .filter((part: any) => part?.type === "text")
    .map((part: any) => String(part.text || ""))
    .join("\n")
    .trim()
}

function isLightweightRequest(text: string): boolean {
  const t = text.trim()
  if (!t) return false
  if (/继续|写到文件|保存|落盘|整理成.*(文档|文件)|生成|创建|实现|修改|修复|编译|跑实验|执行|对比.*整理/.test(t)) {
    return false
  }
  return /解读一下|解释一下|怎么看|是什么|是不是|对吗|为什么|总结一下|讲一下|读一下/.test(t)
}

function narrowContinueText(input: any, text: string): string {
  const overflow = input?.overflow === true
  const overflowNote = overflow
    ? "前一次请求因为上下文或附件过大触发了 compact；如果最后一个真实用户请求依赖已被移除的附件，请直接说明无法继续并请用户重新上传更小或更少的附件。\n\n"
    : ""
  const quoted = text ? `最后一个真实用户请求是：\n${text}\n\n` : ""
  return (
    overflowNote +
    quoted +
    "这是 compact 后的内部续跑指令：仅继续完成上面这个真实用户请求中已经明确要求、且在 compact 前尚未完成的动作。" +
    "不要扩大任务范围，不要新增对比/整理/推进方向，不要主动提出下一步。" +
    "如果该请求已经完成，直接停止，不要再输出进度总结。"
  )
}

export const ArcCompactionPolicy: Plugin = async () => {
  return {
    "experimental.compaction.autocontinue": async (input: any, output: any) => {
      if (POLICY_OFF) {
        dlog(`skip (ARC_COMPACTION_POLICY_OFF) sid=${input?.sessionID ?? "?"}`)
        return
      }
      const text = messageText(input?.message)
      const lightweight = isLightweightRequest(text)
      if (lightweight) {
        output.enabled = false
        dlog(`disabled lightweight sid=${input?.sessionID ?? "?"} text=${JSON.stringify(text.slice(0, 120))}`)
        return
      }
      output.enabled = true
      output.text = narrowContinueText(input, text)
      dlog(`enabled narrow sid=${input?.sessionID ?? "?"} text=${JSON.stringify(text.slice(0, 120))}`)
    },
  }
}
