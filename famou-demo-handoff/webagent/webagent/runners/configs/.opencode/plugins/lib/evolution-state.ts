/**
 * 演化状态读写 — 共享模块（**非 plugin**，不要在 opencode.json 的 plugin 列表里引用）。
 *
 * 放在 lib/ 子目录下，避免被 opencode 的 `{plugin,plugins}/*.{ts,js}` glob 扫描成 plugin
 * （opencode 会对 plugin 文件的所有 function 类型 named export 都按 plugin 调用一次，
 * 把 helper 函数当 plugin 调用会因为参数类型不匹配报错）。
 *
 * 由 evolution-loop.ts 和 fm-evolution.ts 共用。
 */

import { existsSync, readFileSync, unlinkSync } from "node:fs"
import { join } from "node:path"

// ── 常量 ──

export const STATE_FILE = ".evolution/state.md"
export const DEFAULT_COMPLETION_PROMISE = "演化完成"
export const DEFAULT_MASTER_AGENT = "famou-master"
export const DEFAULT_EVOLUTION_AGENT = "famou-evolution"

// ── 类型 ──

// state.md — 循环控制状态（evolution-loop 管理，不含 iteration）
export interface LoopState {
  active: boolean
  completion_promise: string
  started_at: string
  prompt: string
  session_id?: string
  evolution_dir?: string
  agent?: string
  master_agent?: string
}

// ── state.md 读写 ──

export function getStatePath(directory: string): string {
  return join(directory, STATE_FILE)
}

export function readState(directory: string): LoopState | null {
  const filePath = getStatePath(directory)
  if (!existsSync(filePath)) return null

  try {
    const content = readFileSync(filePath, "utf-8")
    const match = content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/)
    if (!match) return null

    const frontmatter = match[1]
    const body = match[2]?.trim() ?? ""

    const get = (key: string): string | undefined => {
      const m = frontmatter.match(new RegExp(`^${key}:\\s*"?(.+?)"?\\s*$`, "m"))
      return m?.[1]
    }
    const getBool = (key: string): boolean => get(key) === "true"

    if (!getBool("active")) return null

    return {
      active: true,
      completion_promise: get("completion_promise") ?? DEFAULT_COMPLETION_PROMISE,
      started_at: get("started_at") ?? new Date().toISOString(),
      session_id: get("session_id"),
      evolution_dir: get("evolution_dir"),
      agent: get("agent") ?? DEFAULT_EVOLUTION_AGENT,
      master_agent: get("master_agent") ?? DEFAULT_MASTER_AGENT,
      prompt: body,
    }
  } catch {
    return null
  }
}

export function clearState(directory: string): boolean {
  const filePath = getStatePath(directory)
  try {
    if (existsSync(filePath)) unlinkSync(filePath)
    return true
  } catch {
    return false
  }
}

// ── fm-evolution.ts 用的查询接口 ──

export function isEvolutionActive(directory: string): boolean {
  const state = readState(directory)
  return state !== null && state.active
}

export function getActiveEvolutionDir(directory: string): string | null {
  const state = readState(directory)
  return state?.evolution_dir ?? null
}
