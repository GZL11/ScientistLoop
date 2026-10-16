/**
 * runtime-config.ts — 生产环境 charge 接入配置加载
 *
 * 配置来源(按优先级 fallback):
 *
 *   user_id / agentway_session_id
 *     1. opts.runtimeDir 显式传入
 *     2. /famou/agents/famou_1/runtime/data       (生产 runtime 注入)
 *     3. <这个文件所在目录>/.dev-runtime           (本地 dev 兜底)
 *
 *   baseUrl
 *     1. opts.baseUrl 显式传入
 *     2. $WEBAGENT_CHARGE_SERVER_URL              (生产/dev 都必须设置)
 *     若 1/2 都没有 → throw(不再 fallback 到 localhost,避免静默错连)
 *
 * 缺失任何字段 / env 未设置都会 throw,plugin 上层会把错误打到 stdout
 * 让用户能在日志看到根因。
 *
 * 本地开发只需:
 *   mkdir -p billing/.dev-runtime
 *   echo "<your_user_id>"      > billing/.dev-runtime/user_id
 *   echo "agentway-local"      > billing/.dev-runtime/agentway_session_id
 *   export WEBAGENT_CHARGE_SERVER_URL=http://127.0.0.1:8080
 *
 * 然后任何 plugin / 脚本里直接 `loadRuntimeConfig()` 就能读到。
 *
 * 注:opencode 原生 session_id 之前读但 plugin 没用,已从 contract 移除。
 *    需要的话直接 import opencode 自己的 session 接口即可。
 */

import { existsSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const PROD_RUNTIME_DIR = "/famou/agents/famou_1/runtime/data"
const CHARGE_BASE_URL_ENV = "WEBAGENT_CHARGE_SERVER_URL"
const BILLING_ENABLED_ENV = "WEBAGENT_BILLING_ENABLED"

// dev fallback 目录:`<本文件所在目录>/.dev-runtime`。
// 必须 lazy 求值——某些 plugin loader 环境(opencode bun-compiled runtime)下
// `import.meta.url` 不是 string,top-level 调用 fileURLToPath 会抛
// "paths[0] must be of type string, got object",拖垮整个 plugin。
// 只在 autoDetectRuntimeDir 真正需要 dev fallback 时按需算,prod 走 PROD_RUNTIME_DIR 完全不会触发。
let _devFallbackDir: string | null = null
function getDevFallbackRuntimeDir(): string {
  if (_devFallbackDir !== null) return _devFallbackDir
  _devFallbackDir = join(dirname(fileURLToPath(import.meta.url)), ".dev-runtime")
  return _devFallbackDir
}

/**
 * 计费总开关。默认 **关闭**(opt-in 安全):未设置 / 设错值都不计费。
 *
 * 接受为 enabled 的字面值(case-insensitive,trim 之后):
 *   "1", "true", "yes", "on"
 *
 * 其他值(包括 "0", "false", "no", "off", "", 未设置, 任意字符串)→ 关闭。
 *
 * 关闭模式下:
 *   - 不读 runtime data 文件(无需 user_id / agentway_session_id)
 *   - 不构造 ChargeClient(直接返回 noop 实现)
 *   - 所有 freeze/cost/settle 调用返回 ok=true 的 noop result,plugin 透明无感
 *
 * 生产部署务必显式设置 `WEBAGENT_BILLING_ENABLED=1`,
 * 不设默认就**不扣费**(避免新环境意外扣费)。
 */
export function isBillingEnabled(): boolean {
  const v = (process.env[BILLING_ENABLED_ENV] ?? "").trim().toLowerCase()
  return v === "1" || v === "true" || v === "yes" || v === "on"
}

export interface RuntimeConfig {
  /** Charge x-user-id header */
  userId: string
  /** 业务侧 session id(agentway 层),作 ticket */
  agentwaySessionId: string
  /** charge 服务 base URL */
  baseUrl: string
}

export interface LoadOptions {
  /** 测试或显式注入:runtime data 根路径 */
  runtimeDir?: string
  /** 测试或显式注入:base URL,绕过 env */
  baseUrl?: string
}

export function loadRuntimeConfig(opts: LoadOptions = {}): RuntimeConfig {
  const runtimeDir = opts.runtimeDir ?? autoDetectRuntimeDir()

  return {
    userId: readRequired(join(runtimeDir, "user_id")),
    agentwaySessionId: readRequired(join(runtimeDir, "agentway_session_id")),
    baseUrl: opts.baseUrl ?? readBaseUrl(),
  }
}

function autoDetectRuntimeDir(): string {
  if (existsSync(PROD_RUNTIME_DIR)) return PROD_RUNTIME_DIR
  const devFallback = getDevFallbackRuntimeDir()
  if (existsSync(devFallback)) return devFallback
  throw new Error(
    `runtime data dir not found. Tried:\n` +
      `  - ${PROD_RUNTIME_DIR} (production)\n` +
      `  - ${devFallback} (dev fallback)\n` +
      `本地开发请先 mkdir 上面 dev fallback 路径并写入 user_id / agentway_session_id 文件。`,
  )
}

function readBaseUrl(): string {
  const v = process.env[CHARGE_BASE_URL_ENV]
  if (v && v.trim()) return v.trim()
  throw new Error(
    `${CHARGE_BASE_URL_ENV} env var is required but not set (or empty). ` +
      `Production must set this; local dev: export ${CHARGE_BASE_URL_ENV}=http://127.0.0.1:8080`,
  )
}

function readRequired(path: string): string {
  if (!existsSync(path)) {
    throw new Error(`runtime data file missing: ${path}`)
  }
  const v = readFileSync(path, "utf-8").trim()
  if (!v) {
    throw new Error(`runtime data file empty: ${path}`)
  }
  return v
}
