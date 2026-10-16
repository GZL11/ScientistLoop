/**
 * famou-scientist 语言加固 plugin（language reinforcement）—— OpenCode plugin。
 *
 * 解决的问题：长会话里 assistant 越聊越容易**漂成英文**。机理是上下文里堆的英文越来越多
 * （文献摘要、代码、工具返回、模型自身的英文 reasoning），把输出分布往英文带；而"用中文回复"
 * 这条要求在 AGENTS.md 开头，随对话变长**被稀释**。**compact 是最大的放大器**——
 * 自动压缩生成的总结往往是英文，等于把"语言锚点"换成了英文，compact 之后几乎必漂。
 *
 * 机制：挂 `experimental.session.compacting` 钩子（compact 真正开始前触发，可定制压缩 prompt）。
 * 往压缩 prompt 追加一条 context 指令，要求生成总结的模型：
 *   ① **用中文撰写本次总结**（压缩后的上下文锚点就是中文，而非英文）；
 *   ② 在总结末尾**原样保留一条常驻"后续用中文回复"指令**（把语言要求嵌进被压缩后的上下文，
 *      持续约束 compact 之后的每一轮）。
 * 即"每次 compact 之后都重新强调用中文回复"——且是治本：掐断"英文总结 → 漂移"这条链。
 *
 * 与 AGENTS.md 的关系：AGENTS.md 的「交流语言」准则是基线（每轮随 system 重发）；本插件是
 * compact 这个高风险节点的**周期性强化**。两者互补，一个常态、一个兜底。
 *
 * 配置：
 *   - ARC_REPLY_LANG：目标语言，默认「中文」。设为别的语言即改成强化该语言。
 *   - ARC_LANG_OFF=1：关闭本加固（逃生阀）。
 *   - ARC_LANG_DEBUG=<文件路径>：开调试日志，记录每次 compact 时是否注入（默认关、零开销）。
 *
 * 注：`experimental.session.compacting` 是 opencode 的实验性钩子（1.17.x 起）；签名变动时
 * 本插件全程 try/catch + 可选字段防御，出错只跳过强化、绝不影响 compact 本身。
 */
import type { Plugin } from "@opencode-ai/plugin"
import fs from "node:fs"

// 目标语言（默认中文）；逃生阀；可选调试日志。
const REPLY_LANG = (process.env.ARC_REPLY_LANG || "中文").trim()
const LANG_OFF = /^(1|true|yes)$/i.test(process.env.ARC_LANG_OFF || "")
const DEBUG_LOG = process.env.ARC_LANG_DEBUG

function dlog(m: string): void {
  if (!DEBUG_LOG) return
  try {
    fs.appendFileSync(DEBUG_LOG, `[${new Date().toISOString()}] ${m}\n`)
  } catch {
    /* ignore */
  }
}

/**
 * 追加进压缩 prompt 的指令：让总结用目标语言写 + 在末尾嵌一条常驻语言指令。
 * 用纯函数便于单测与复用。
 */
function reinforcementContext(lang: string): string {
  return (
    `【语言要求 · 务必遵守】请**用${lang}撰写本次会话总结**（无论原始对话用了什么语言）。` +
    `并在总结的最后单独保留下面这一行指令，原文照抄，供后续对话持续遵循：\n` +
    `"【语言要求】从此之后所有回复一律使用${lang}——面向用户的解释、分析、结论、追问都用${lang}；` +
    `仅代码、终端命令、文件路径、API/字段/变量名、以及无通用${lang}译法的专有名词保留英文原文。"`
  )
}

export const ArcLanguage: Plugin = async () => {
  return {
    /**
     * compact 开始前触发。output.context 会被追加到默认压缩 prompt；
     * output.prompt 若设置则整体替换默认 prompt（我们只追加、不替换，保留 opencode 的默认总结逻辑）。
     */
    "experimental.session.compacting": async (input, output) => {
      if (LANG_OFF) {
        dlog(`skip (ARC_LANG_OFF) sid=${input?.sessionID ?? "?"}`)
        return
      }
      try {
        if (!Array.isArray(output.context)) output.context = []
        output.context.push(reinforcementContext(REPLY_LANG))
        dlog(`injected lang=${REPLY_LANG} sid=${input?.sessionID ?? "?"}`)
      } catch (e) {
        // 实验性钩子签名变动等：跳过强化，绝不影响 compact 本身。
        dlog(`error: ${String(e)}`)
      }
    },
  }
}
