/**
 * exempt-state.ts — 跨 plugin 共享的"下一次 famou-build 调用扣费豁免"状态。
 *
 * 用途：演化结束后，evolution-loop 切回 master 让其"生成可视化产物"。master 会
 * 派 famou-build subagent 干这个活——但本次 build 是演化的延续，**不应再扣 25**
 * （演化本身的 80 已包含此次收尾）。
 *
 * 机制：
 *  1. evolution-loop 在切 master 之前调 `markExempt(sessionID)` 在内存标记
 *  2. billing-plugin 在 `tool.execute.before(famou-build)` 调 `consumeExempt`
 *     - 命中（同 sessionID + 未过期）→ skip freeze（一次性消费，不会再用）
 *     - 未命中 → 走原 freeze 逻辑
 *  3. billing-plugin 内部用 Set<callID> 把 before 的豁免决策传给 after，
 *     after 直接 skip settle/cost
 *
 * 为什么用内存而非文件：
 *  - evolution-loop + billing-plugin 在同一 opencode 进程内，共享 Node 模块缓存
 *  - 内存方案省去文件 IO / 原子重命名 / TTL GC 等复杂度
 *  - 进程崩溃丢标记 → master 调 build → freeze 失败（ticket 已被 evolve settle 关掉）
 *    → master 报错而非多扣，**fail-safe**，比多扣更可接受
 *
 * TTL：5 分钟。viz build 通常很快（拷数据 + 渲染图表），留够缓冲即可。
 *
 * 注意：本文件只能放在 `plugins/lib/` 下，**不可放 `plugins/` 根目录**——opencode
 * plugin loader 会把每个 `function` 类型的 named export 当 plugin 实例调一次，
 * 把 helper 函数误当成 plugin 加载会引发"paths[0] must be of type string"等错误。
 * (同 `lib/evolution-state.ts` 文件头注释。)
 */

const DEFAULT_TTL_MS = 5 * 60 * 1000

// sessionID -> expiresAt (unix ms)
const exemptedSessions = new Map<string, number>()

/** evolution-loop 在演化收尾切 master 之前调用，标记"下一次 famou-build 豁免扣费"。 */
export function markExempt(sessionID: string, ttlMs: number = DEFAULT_TTL_MS): void {
  exemptedSessions.set(sessionID, Date.now() + ttlMs)
}

/**
 * billing-plugin 在 famou-build 起飞前调用：
 *  - 同 sessionID + 未过期 → 返回 true 并**一次性消费**（删除标记）
 *  - 否则返回 false
 *
 * 一次性消费保证：master 若在豁免窗口内多次派 famou-build，只有第一次免单。
 */
export function consumeExempt(sessionID: string): boolean {
  const expiresAt = exemptedSessions.get(sessionID)
  if (expiresAt === undefined) return false
  exemptedSessions.delete(sessionID)              // one-shot
  return expiresAt > Date.now()                   // 过期视为未豁免
}

/** 测试专用：重置所有豁免状态。**生产代码禁止调用。** */
export function __resetExemptStateForTesting(): void {
  exemptedSessions.clear()
}
