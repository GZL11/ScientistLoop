import type { Plugin } from "@opencode-ai/plugin"
import {
  existsSync,
  readFileSync,
  writeFileSync,
  mkdirSync,
  readdirSync,
  statSync,
  cpSync,
  rmSync,
  renameSync,
} from "node:fs"
import { join, basename } from "node:path"
import { isEvolutionActive, getActiveEvolutionDir } from "./lib/evolution-state"
import { log, setLogDirectory, type LogLevel } from "./lib/log"

/**
 * FM Evolution Plugin
 *
 * Hook: tool.execute.after(task)
 * evo-builder 返回后自动：评估 scratch/ 中所有解 → 归档 → 更新状态
 * 分数摘要注入 tool_result，evolution agent 可见。
 *
 * 守卫：isEvolutionActive() 为 false 时跳过，主流程不受影响。
 */

// ── Config ──

interface EvoConfig {
  budget: number
  solution_pattern: string
  iteration: number
  direction: "minimize" | "maximize"
  main_session_id?: string
}

function loadConfig(evoDir: string): EvoConfig {
  const p = join(evoDir, ".harness", "config.json")
  if (existsSync(p)) {
    const raw = JSON.parse(readFileSync(p, "utf-8"))
    return {
      budget: raw.budget ?? 20,
      solution_pattern: raw.solution_pattern ?? "solution*",
      iteration: raw.iteration ?? 0,
      direction: raw.direction === "minimize" ? "minimize" : "maximize",
      main_session_id: raw.main_session_id,
    }
  }
  return { budget: 20, solution_pattern: "solution*", iteration: 0, direction: "maximize" as const }
}

function isBetter(a: number, b: number, direction: "minimize" | "maximize"): boolean {
  return direction === "minimize" ? a < b : a > b
}

function saveConfig(evoDir: string, config: EvoConfig): void {
  const p = join(evoDir, ".harness", "config.json")
  writeFileSync(p, JSON.stringify(config, null, 2))
}

// ── Glob matching (simple) ──

function matchPattern(filename: string, pattern: string): boolean {
  const regex = new RegExp(
    "^" + pattern.replace(/\./g, "\\.").replace(/\*/g, ".*").replace(/\?/g, ".") + "$",
  )
  return regex.test(filename)
}

// ── Scan solutions ──

function scanSolutions(scratchDir: string, pattern: string): string[] {
  if (!existsSync(scratchDir)) return []
  const results: string[] = []

  function walk(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(full)
      } else if (entry.isFile() && matchPattern(entry.name, pattern)) {
        results.push(full)
      }
    }
  }

  walk(scratchDir)
  return results.sort()
}

// ── Evaluate one solution ──

interface EvalResult {
  file: string
  score: number | null
  error?: string
  raw?: Record<string, unknown>
}

async function evaluateOne(
  $: any,
  evaluatorPath: string,
  solutionFile: string,
  timeout = 120,
): Promise<EvalResult> {
  const fileName = basename(solutionFile)
  const scoreFile = solutionFile.replace(/\.[^.]+$/, ".score.json")

  // 跳过已评估且 mtime 足够新的
  if (existsSync(scoreFile)) {
    const solMtime = statSync(solutionFile).mtimeMs
    const scoreMtime = statSync(scoreFile).mtimeMs
    if (scoreMtime >= solMtime) {
      try {
        const raw = JSON.parse(readFileSync(scoreFile, "utf-8"))
        if (raw.score != null) {
          return { file: fileName, score: Number(raw.score), raw }
        }
      } catch { /* fall through to re-evaluate */ }
    }
  }

  try {
    const result = await $`python ${evaluatorPath} ${solutionFile}`.quiet().nothrow()
    if (result.exitCode !== 0) {
      // evaluator 正常处理 solution 失败时会写 .score.json 并 exit(0)
      // exit != 0 说明 evaluator 本身出错，仍尝试读 .score.json（evaluator 可能在崩溃前写了）
      if (existsSync(scoreFile)) {
        try {
          const raw = JSON.parse(readFileSync(scoreFile, "utf-8"))
          if (raw.score != null) {
            return { file: fileName, score: Number(raw.score), raw }
          }
        } catch { /* fall through */ }
      }
      const error = result.stderr.toString().trim().slice(0, 300) || `exit code ${result.exitCode}`
      return { file: fileName, score: null, error }
    }

    // 优先读 .score.json 文件（契约要求）
    if (existsSync(scoreFile)) {
      const raw = JSON.parse(readFileSync(scoreFile, "utf-8"))
      const score = raw.score != null ? Number(raw.score) : null
      return { file: fileName, score, raw }
    }

    // 兜底：从 evaluator stdout 解析 JSON（兼容不写文件的 evaluator）
    const stdout = result.stdout.toString().trim()
    if (stdout) {
      try {
        const raw = JSON.parse(stdout)
        if (raw.score != null) {
          // 同时写 .score.json 以便后续跳过重复评估
          writeFileSync(scoreFile, JSON.stringify(raw, null, 2))
          return { file: fileName, score: Number(raw.score), raw }
        }
      } catch { /* stdout 不是有效 JSON，忽略 */ }
    }

    return { file: fileName, score: null, error: "No score.json produced and stdout not parseable" }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    return { file: fileName, score: null, error: msg }
  }
}

// ── Archive ──

function nextCandidateId(candidatesDir: string): string {
  if (!existsSync(candidatesDir)) return "v001"
  const existing = readdirSync(candidatesDir, { withFileTypes: true })
    .filter(d => d.isDirectory() && d.name.startsWith("v"))
    .map(d => {
      const n = parseInt(d.name.slice(1), 10)
      return isNaN(n) ? 0 : n
    })
  if (existing.length === 0) return "v001"
  return `v${String(Math.max(...existing) + 1).padStart(3, "0")}`
}

function archiveResults(
  evoDir: string,
  results: EvalResult[],
  iteration: number,
  direction: "minimize" | "maximize",
): Array<{ candidate_id: string; file: string; score: number }> {
  const candidatesDir = join(evoDir, "candidates")
  const scratchDir = join(candidatesDir, "scratch")
  const promoted: Array<{ candidate_id: string; file: string; score: number }> = []

  for (const result of results) {
    const score = result.score ?? (direction === "minimize" ? Infinity : -Infinity)
    const cid = nextCandidateId(candidatesDir)
    const dest = join(candidatesDir, cid)
    mkdirSync(dest, { recursive: true })

    // 复制 solution
    const src = join(scratchDir, result.file)
    if (existsSync(src)) {
      cpSync(src, join(dest, result.file))
    }

    // 复制 sibling stem 文件（result.json、agent 自写的 score.json、自定义产物等）
    const stem = result.file.replace(/\.[^.]+$/, "")
    if (existsSync(scratchDir)) {
      for (const sibling of readdirSync(scratchDir, { withFileTypes: true })) {
        if (!sibling.isFile()) continue
        if (sibling.name === result.file) continue
        if (sibling.name.startsWith(stem + ".") || sibling.name.startsWith(stem + "_")) {
          cpSync(join(scratchDir, sibling.name), join(dest, sibling.name))
        }
      }
    }

    // 写 score.json（hook 汇总用，updateIndex 依赖这个固定名）
    const scoreData = { ...(result.raw ?? {}), score, iteration }
    writeFileSync(join(dest, "score.json"), JSON.stringify(scoreData, null, 2))

    promoted.push({ candidate_id: cid, file: result.file, score })
  }

  return promoted
}

// ── INDEX.md ──

function updateIndex(candidatesDir: string, direction: "minimize" | "maximize"): void {
  if (!existsSync(candidatesDir)) return

  // 读取已有 INDEX.md 中的 Approach 信息（evolution agent 填的）
  const existingApproach = new Map<string, string>()
  const indexPath = join(candidatesDir, "INDEX.md")
  if (existsSync(indexPath)) {
    const content = readFileSync(indexPath, "utf-8")
    for (const line of content.split("\n")) {
      const match = line.match(/^\|\s*(v\d+)\s*\|[^|]*\|([^|]*)\|/)
      if (match) {
        const approach = match[2].trim()
        if (approach && approach !== "") {
          existingApproach.set(match[1], approach)
        }
      }
    }
  }

  const candidates: Array<{ id: string; score: number | null; approach: string; iter: unknown; files: string[] }> = []

  for (const entry of readdirSync(candidatesDir, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith("v")) continue
    const scoreFile = join(candidatesDir, entry.name, "score.json")
    if (!existsSync(scoreFile)) continue
    try {
      const data = JSON.parse(readFileSync(scoreFile, "utf-8"))
      const files = readdirSync(join(candidatesDir, entry.name))
        .filter((f: string) => f !== "score.json")
      candidates.push({
        id: entry.name,
        score: data.score ?? null,
        approach: existingApproach.get(entry.name) ?? "",
        iter: data.iteration ?? "?",
        files,
      })
    } catch { continue }
  }

  if (candidates.length === 0) return
  candidates.sort((a, b) =>
    direction === "minimize"
      ? (a.score ?? Infinity) - (b.score ?? Infinity)
      : (b.score ?? -Infinity) - (a.score ?? -Infinity)
  )
  const best = candidates[0]

  const lines = [
    "# Population Index",
    "",
    `Best: ${best.id} (score: ${best.score})`,
    `Total: ${candidates.length} candidates`,
    "",
    "| ID | Score | Approach | Iter | Files |",
    "|----|-------|----------|------|-------|",
    ...candidates.map(c => `| ${c.id} | ${c.score} | ${c.approach} | ${c.iter} | ${c.files.join(", ")} |`),
  ]
  writeFileSync(indexPath, lines.join("\n") + "\n")
}

// ── History ──

function moveScratchToHistory(evoDir: string, iteration: number): void {
  const scratchDir = join(evoDir, "candidates", "scratch")
  const historyDest = join(evoDir, "history", `round_${String(iteration).padStart(3, "0")}`)
  mkdirSync(historyDest, { recursive: true })

  if (existsSync(scratchDir)) {
    for (const entry of readdirSync(scratchDir)) {
      const dest = join(historyDest, entry)
      if (!existsSync(dest)) {
        renameSync(join(scratchDir, entry), dest)
      }
    }
    rmSync(scratchDir, { recursive: true })
  }
  mkdirSync(scratchDir, { recursive: true })
}

// ── Status ──

function getGlobalBest(candidatesDir: string, direction: "minimize" | "maximize"): number | null {
  if (!existsSync(candidatesDir)) return null
  let best: number | null = null
  for (const entry of readdirSync(candidatesDir, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.startsWith("v")) continue
    const scoreFile = join(candidatesDir, entry.name, "score.json")
    if (!existsSync(scoreFile)) continue
    try {
      const score = JSON.parse(readFileSync(scoreFile, "utf-8")).score
      if (score != null && (best === null || isBetter(score, best, direction))) best = score
    } catch { continue }
  }
  return best
}

function loadRoundOutcomes(evoDir: string): Array<Record<string, unknown>> {
  const historyDir = join(evoDir, "history")
  if (!existsSync(historyDir)) return []
  const outcomes: Array<Record<string, unknown>> = []
  const dirs = readdirSync(historyDir, { withFileTypes: true })
    .filter(d => d.isDirectory() && d.name.startsWith("round_"))
    .sort((a, b) => a.name.localeCompare(b.name))
  for (const d of dirs) {
    const f = join(historyDir, d.name, "round.json")
    if (!existsSync(f)) continue
    try { outcomes.push(JSON.parse(readFileSync(f, "utf-8"))) } catch { continue }
  }
  return outcomes
}

// 投影到对外 schema 的 4 字段；用于 <evolve_progress>.rounds[]
interface RoundProgress {
  round: number
  title: string | null
  summary: string | null
  best_score: number | null
}

function loadRounds(evoDir: string): RoundProgress[] {
  return loadRoundOutcomes(evoDir).map(o => ({
    round: o.round as number,
    title: (o.title as string | null) ?? null,
    summary: (o.summary as string | null) ?? null,
    best_score: (o.best_score as number | null) ?? null,
  }))
}

function findBestRound(
  rounds: RoundProgress[],
  direction: "minimize" | "maximize",
): { best_score: number | null; best_round: number | null } {
  let bestScore: number | null = null
  let bestRound: number | null = null
  for (const r of rounds) {
    if (r.best_score == null) continue
    if (bestScore == null || isBetter(r.best_score, bestScore, direction)) {
      bestScore = r.best_score
      bestRound = r.round
    }
  }
  return { best_score: bestScore, best_round: bestRound }
}

function computeStagnation(evoDir: string, direction: "minimize" | "maximize"): number {
  const outcomes = loadRoundOutcomes(evoDir)
  if (outcomes.length < 2) return 0
  let count = 0
  for (let i = outcomes.length - 1; i > 0; i--) {
    const curr = outcomes[i].global_best_after as number | null
    const prev = outcomes[i - 1].global_best_after as number | null
    if (curr == null || prev == null || !isBetter(curr, prev, direction)) count++
    else break
  }
  return count
}

function updateStatus(evoDir: string, iteration: number, config: EvoConfig): void {
  const candidatesDir = join(evoDir, "candidates")
  const globalBest = getGlobalBest(candidatesDir, config.direction)
  const stagnation = computeStagnation(evoDir, config.direction)
  const outcomes = loadRoundOutcomes(evoDir)
  const recent = outcomes.slice(-5).map(o => o.best_score)
  const recentStr = recent.map(s => (s != null ? String(s) : "-")).join(", ")

  let total = 0
  if (existsSync(candidatesDir)) {
    total = readdirSync(candidatesDir, { withFileTypes: true })
      .filter(d => d.isDirectory() && d.name.startsWith("v")).length
  }

  // 保留 evolution agent 写的 Population Summary 和 Diagnosis
  let existingPopSummary = ""
  let existingDiagnosis = ""
  const statusPath = join(evoDir, "status.md")
  if (existsSync(statusPath)) {
    const content = readFileSync(statusPath, "utf-8")
    const popMatch = content.match(/## Population Summary\n([\s\S]*?)(?=\n## |$)/)
    if (popMatch) existingPopSummary = popMatch[1].trim()
    const diagMatch = content.match(/## Diagnosis\n([\s\S]*?)(?=\n## |$)/)
    if (diagMatch) existingDiagnosis = diagMatch[1].trim()
  }

  const lines = [
    "# Status",
    "",
    "## Facts",
    `- Iteration: ${iteration} / ${config.budget}`,
    globalBest != null ? `- Best score: ${globalBest}` : "- Best: (none)",
    `- Last 5 scores: [${recentStr}]`,
    `- Total candidates: ${total}`,
    `- Budget remaining: ${config.budget - iteration} iterations`,
    `- Stagnation: ${stagnation} rounds`,
  ]

  if (existingPopSummary) {
    lines.push("", "## Population Summary", "", existingPopSummary)
  }

  lines.push("", "## Diagnosis", existingDiagnosis || "（待诊断）")

  writeFileSync(statusPath, lines.join("\n") + "\n")
}

function saveRoundRecord(
  evoDir: string,
  iteration: number,
  results: EvalResult[],
  globalBest: number | null,
  summary: RoundSummary,
  direction: "minimize" | "maximize",
): void {
  const historyDir = join(evoDir, "history", `round_${String(iteration).padStart(3, "0")}`)
  mkdirSync(historyDir, { recursive: true })

  const finiteScores = results.filter(r => r.score != null).map(r => r.score!)
  const bestThisRound = finiteScores.length > 0
    ? (direction === "minimize" ? Math.min(...finiteScores) : Math.max(...finiteScores))
    : null

  const record = {
    round: iteration,
    title: summary.title,
    summary: summary.summary,
    best_score: bestThisRound,
    global_best_after: globalBest,
    scores: results.map(r => r.score),
    results: results.map(r => ({ file: r.file, score: r.score, error: r.error })),
  }
  writeFileSync(join(historyDir, "round.json"), JSON.stringify(record, null, 2))
}

// ── Round Summary 提取 ──

interface RoundSummary {
  title: string | null
  summary: string | null
}

function extractRoundSummary(taskOutput: string): RoundSummary {
  const m = taskOutput.match(/<round_summary>([\s\S]*?)<\/round_summary>/i)
  if (!m) return { title: null, summary: null }
  try {
    const obj = JSON.parse(m[1].trim())
    return {
      title: typeof obj.title === "string" ? obj.title : null,
      summary: typeof obj.summary === "string" ? obj.summary : null,
    }
  } catch {
    return { title: null, summary: null }
  }
}

// ── Plugin ──

export const FMEvolutionPlugin: Plugin = async ({ directory, $ }) => {
  // 注册文件 sink 目录(跟其它 plugin 相同 directory,多个 plugin 调用幂等),
  // 所有 hook 共写 `{directory}/hook.log`。
  setLogDirectory(directory)
  // 本 plugin 的事件以 `[fm-evolution]` 前缀走统一 logger(stdout/file/HTTP)。
  // 兼容旧 log(msg, ctxObj) / log(msg, e) 调用风格:args 拼接成 message。
  const evoLog = (level: LogLevel, ...args: unknown[]): void => {
    const msg = args
      .map((a) => (typeof a === "object" ? JSON.stringify(a) : String(a)))
      .join(" ")
    log("fm-evolution", level, msg)
  }
  return {
    "tool.execute.after": async (
      input: { tool: string; sessionID?: string; args?: Record<string, unknown> },
      output: { output: string; args?: Record<string, unknown> },
    ) => {
      if (input.tool !== "task") return

      evoLog("info", "task returned", { sessionID: input.sessionID, active: isEvolutionActive(directory) })

      if (!isEvolutionActive(directory)) return

      const evoDir = getActiveEvolutionDir(directory)
      if (!evoDir) return

      // 只处理主 session 的 task 调用，忽略子 session（evo-builder）内部的 task
      const config = loadConfig(evoDir)
      if (config.main_session_id && input.sessionID && input.sessionID !== config.main_session_id) {
        evoLog("info", "skipped: sub-session task call", {
          inputSession: input.sessionID,
          mainSession: config.main_session_id,
        })
        return
      }

      const scratchDir = join(evoDir, "candidates", "scratch")
      if (!existsSync(scratchDir)) {
        evoLog("info", "skipped: scratch dir not found")
        return
      }

      try {
        const evaluatorPath = join(evoDir, ".harness", "evaluator.py")
        const solutions = scanSolutions(scratchDir, config.solution_pattern)

        evoLog("info", "archiving", {
          iteration: config.iteration,
          solutions: solutions.length,
          pattern: config.solution_pattern,
        })

        // 1. 评估（如果有匹配的 solution）
        const evalStart = Date.now()
        const results: EvalResult[] = []
        for (const sol of solutions) {
          results.push(await evaluateOne($, evaluatorPath, sol))
        }
        if (solutions.length > 0) {
          evoLog("info", "evaluation done", {
            solutions: solutions.length,
            elapsed: `${((Date.now() - evalStart) / 1000).toFixed(1)}s`,
          })
        }

        // 2. 递增 iteration（无论是否有 solution，空轮次也是轮次）
        config.iteration += 1
        const iteration = config.iteration
        saveConfig(evoDir, config)

        // 3. 归档 solution（如果有）
        if (results.length > 0) {
          archiveResults(evoDir, results, iteration, config.direction)
          updateIndex(join(evoDir, "candidates"), config.direction)
        }

        const globalBest = getGlobalBest(join(evoDir, "candidates"), config.direction)
        const stagnation = computeStagnation(evoDir, config.direction)

        // 4. 提取 round_summary（在注入文本前，避免取到 hook 自己的输出）
        const summary = extractRoundSummary(output.output)

        // 5. round record
        saveRoundRecord(evoDir, iteration, results, globalBest, summary, config.direction)

        // 6. scratch → history，清空 scratch
        moveScratchToHistory(evoDir, iteration)

        // 7. 更新 status.md
        updateStatus(evoDir, iteration, config)

        evoLog("info", "archived", {
          iteration,
          results: results.length,
          globalBest,
          stagnation,
        })

        // 8. 注入 <evolve_progress> 给前端展示（schema: docs/evolve_progress_schema.md）
        const rounds = loadRounds(evoDir)
        const { best_round } = findBestRound(rounds, config.direction)
        const totalCandidates = existsSync(join(evoDir, "candidates"))
          ? readdirSync(join(evoDir, "candidates"), { withFileTypes: true })
              .filter((d: { isDirectory(): boolean; name: string }) => d.isDirectory() && d.name.startsWith("v")).length
          : 0

        const progress = {
          round: iteration,
          budget: config.budget,
          best_score: globalBest,
          best_round,
          total_candidates: totalCandidates,
          rounds,
        }
        output.output += `\n\n<evolve_progress>\n${JSON.stringify(progress, null, 2)}\n</evolve_progress>`
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : String(e)
        evoLog("error", message)
        output.output += `\n\n[Evolution Error] ${message}`
      }
    },
  }
}

export default FMEvolutionPlugin
