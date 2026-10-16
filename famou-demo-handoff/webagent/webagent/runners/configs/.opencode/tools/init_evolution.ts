import { tool } from "@opencode-ai/plugin"
import {
  existsSync,
  mkdirSync,
  writeFileSync,
  copyFileSync,
  readdirSync,
  readFileSync,
  statSync,
  cpSync,
  rmSync,
} from "node:fs"
import { basename, isAbsolute, join, resolve } from "node:path"

// ── 归档工具：把已有 run_NNN/ 浓缩成 archive/run_NNN/{best,insights.md,summary.md} ──

function safeReadFile(path: string): string {
  try {
    return readFileSync(path, "utf-8")
  } catch {
    return ""
  }
}

interface BestCandidate {
  vName: string
  vDir: string
  score: number
}

/** 扫 candidates/v*\/*.score.json，按 direction 找 validity=1 的最佳解 */
function findBestCandidate(
  candidatesDir: string,
  direction: string,
): BestCandidate | null {
  if (!existsSync(candidatesDir)) return null

  let best: BestCandidate | null = null
  const isBetter = (a: number, b: number) =>
    direction === "minimize" ? a < b : a > b

  for (const entry of readdirSync(candidatesDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    if (!/^v\d+/.test(entry.name)) continue // 只看 v001 / v002 ... 形式

    const vDir = join(candidatesDir, entry.name)
    // candidates/v* 下的固定文件名是 score.json（loop/workspace.py:272 写入）。
    // history/round_NNN/ 下用 *.score.json 后缀，但 archive 只扫 candidates/，
    // 这里只需精确匹配 score.json。
    const scorePath = join(vDir, "score.json")
    if (!existsSync(scorePath)) continue
    try {
      const data = JSON.parse(readFileSync(scorePath, "utf-8"))
      if (typeof data.score !== "number") continue
      if (data.validity !== 1) continue
      if (best === null || isBetter(data.score, best.score)) {
        best = { vName: entry.name, vDir, score: data.score }
      }
    } catch {
      // 解析失败跳过
      continue
    }
  }
  return best
}

/** 从 status.md 抽 ## Diagnosis 段（到下一个 ## 同级标题或文件末） */
function extractDiagnosis(statusContent: string): string {
  if (!statusContent) return "(no status.md)"
  const m = statusContent.match(/##\s*Diagnosis\s*\n([\s\S]*?)(?=\n##\s|$)/)
  return m ? m[1].trim() : "(no Diagnosis section)"
}

/** 从 status.md 抽 Iteration: N / M 字段 */
function extractIteration(statusContent: string): string {
  const m = statusContent.match(/Iteration:\s*(\d+\s*\/\s*\d+)/)
  return m ? m[1] : "N/A"
}

/** 数 candidates/ 下 v* 子目录数量 */
function countCandidates(candidatesDir: string): number {
  if (!existsSync(candidatesDir)) return 0
  try {
    return readdirSync(candidatesDir, { withFileTypes: true }).filter(
      (e) => e.isDirectory() && /^v\d+/.test(e.name),
    ).length
  } catch {
    return 0
  }
}

/**
 * 归档一个 run_NNN 目录：保留 best/ + insights.md + summary.md，删除原目录。
 * 失败不抛——保留原目录，不阻塞主流程。
 */
export function archiveRun(runDir: string, archiveDir: string): void {
  // summary.md 是归档最后一步写的——存在即代表归档完成，跳过
  if (existsSync(join(archiveDir, "summary.md"))) return

  // 读 direction（来自 .harness/config.json）
  let direction = "maximize"
  try {
    const cfgPath = join(runDir, ".harness", "config.json")
    if (existsSync(cfgPath)) {
      const cfg = JSON.parse(readFileSync(cfgPath, "utf-8"))
      if (cfg.direction === "minimize" || cfg.direction === "maximize") {
        direction = cfg.direction
      }
    }
  } catch {
    // direction 读取失败用默认值
  }

  mkdirSync(archiveDir, { recursive: true })

  // 1. 找最佳 candidate
  const candidatesDir = join(runDir, "candidates")
  const best = findBestCandidate(candidatesDir, direction)

  // 2. 复制 best vNNN 整个目录
  if (best) {
    try {
      cpSync(best.vDir, join(archiveDir, "best"), { recursive: true })
    } catch (e) {
      console.error(`Failed to copy best ${best.vName}: ${e}`)
    }
  }

  // 3. 复制 insights.md
  const insightsSrc = join(runDir, "knowledge", "insights.md")
  if (existsSync(insightsSrc)) {
    try {
      copyFileSync(insightsSrc, join(archiveDir, "insights.md"))
    } catch {}
  }

  // 3.5 复制 .harness（evaluator.py / objective.md / config.json）
  // 保留演化契约：支持下一次 /evolve 复用上轮评估器，也便于追溯产出 best
  // 的评估口径。失败不抛——归档是 best-effort，缺它不影响主流程。
  const harnessSrc = join(runDir, ".harness")
  if (existsSync(harnessSrc)) {
    try {
      cpSync(harnessSrc, join(archiveDir, ".harness"), { recursive: true })
    } catch (e) {
      console.error(`Failed to copy .harness: ${e}`)
    }
  }

  // 4. 生成 summary.md（纯文本抽取，无 LLM）
  const statusContent = safeReadFile(join(runDir, "status.md"))
  const diagnosis = extractDiagnosis(statusContent)
  const iteration = extractIteration(statusContent)
  const totalCands = countCandidates(candidatesDir)
  const runId = basename(runDir)

  const summaryLines = [
    `# Evolution Run ${runId} — Summary`,
    "",
    "## Best",
    best
      ? `- score: ${best.score}\n- direction: ${direction}\n- candidate: ${best.vName}\n- 代码位置: best/`
      : `- (无 validity=1 的有效解)\n- direction: ${direction}`,
    "",
    "## Iteration",
    `- ${iteration}`,
    `- 总候选解: ${totalCands}`,
    "",
    "## Final Diagnosis (extracted from status.md)",
    diagnosis,
    "",
  ]
  writeFileSync(join(archiveDir, "summary.md"), summaryLines.join("\n"))

  // 5. 删除原 runDir
  try {
    rmSync(runDir, { recursive: true, force: true })
  } catch (e) {
    console.error(`Failed to remove ${runDir}: ${e}`)
  }
}

// ── 输入校验 + 快照 ──────────────────────────────────────────────────────────

/**
 * 校验并把输入文件读进内存。先于任何破坏性操作调用，保证：
 * - 文件缺失 / 非文件 / 不可读 → 抛出对模型可读可操作的 Error（零副作用）
 * - 成功 → 返回字节快照，与源路径解耦（源即便随后被 archive 删除也不影响）
 *
 * 相对路径按工作目录 cwd 解析，避免按进程 cwd 解析导致的误判。
 */
function loadInputFile(label: string, rawPath: string, cwd: string): Uint8Array {
  const abs = isAbsolute(rawPath) ? rawPath : resolve(cwd, rawPath)
  let st
  try {
    st = statSync(abs)
  } catch {
    throw new Error(
      `${label}文件不存在：${abs}。请先在当前工作目录写出该文件（不要引用 .evolution/ 下历史 run 的文件），再重新调用 init_evolution。`,
    )
  }
  if (!st.isFile()) {
    throw new Error(`${label}路径不是文件：${abs}。请传入 ${label} 文件本身的路径。`)
  }
  try {
    return readFileSync(abs)
  } catch (e) {
    throw new Error(
      `${label}无法读取：${abs}（${(e as Error).message}）。请检查文件是否完整、权限是否正确后重试。`,
    )
  }
}

// ── run 目录扫描 ─────────────────────────────────────────────────────────────

/** 列出 evolutionRoot 下所有 run_NNN 目录的绝对路径 */
function listRunDirs(evolutionRoot: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(evolutionRoot, { withFileTypes: true })) {
    if (entry.isDirectory() && /^run_\d+$/.test(entry.name)) {
      out.push(join(evolutionRoot, entry.name))
    }
  }
  return out
}

/** 同时扫 evolutionRoot + archive/ 求下一个 run 编号，防止与历史 / 已归档 run 重号 */
function nextRunId(evolutionRoot: string, archiveRoot: string): string {
  let maxNum = 0
  const scan = (root: string): void => {
    if (!existsSync(root)) return
    for (const entry of readdirSync(root, { withFileTypes: true })) {
      if (entry.isDirectory() && entry.name.startsWith("run_")) {
        const num = parseInt(entry.name.split("_")[1], 10)
        if (!isNaN(num) && num > maxNum) maxNum = num
      }
    }
  }
  scan(evolutionRoot)
  scan(archiveRoot)
  return `run_${String(maxNum + 1).padStart(3, "0")}`
}

// ── 主 tool ──────────────────────────────────────────────────────────────────

export default tool({
  description:
    "初始化 FM 演化工作空间。创建 .evolution/run_NNN/ 目录结构，复制 evaluator 和 objective，激活演化循环。启动前自动归档已有 run。",
  args: {
    evaluator: tool.schema
      .string()
      .describe("evaluator.py 的路径"),
    objective: tool.schema
      .string()
      .describe("objective.md 的路径"),
    budget: tool.schema
      .number()
      .default(5)
      .describe("演化总轮数"),
    solution_pattern: tool.schema
      .string()
      .default("*.py")
      .describe("solution 文件匹配模式"),
    direction: tool.schema
      .string()
      .default("maximize")
      .describe("优化方向: maximize 或 minimize"),
  },
  async execute(args, context) {
    const cwd = context.directory
    const evolutionRoot = join(cwd, ".evolution")

    // evoDir 在 try 外声明，供 catch 回滚半成品新 run。
    // 整个 init 包在一个 try 里：校验 / mkdir / 写文件 / 扫描的任何异常
    // 都被规范化为可读 Error 回传模型，绝不逃逸成裸崩溃。
    let evoDir: string | null = null

    try {
      // ── Phase 1: 校验 + 快照输入（先于任何破坏性操作，零副作用）──
      // 读进内存彻底解耦"输入"与"archive 旧 run"：即便 agent 把路径指向
      // 即将被 archive 删除的历史 run，字节也已在手，不会再 copy 失败。
      const evaluatorBytes = loadInputFile("评估器 (evaluator.py)", args.evaluator, cwd)
      const objectiveBytes = loadInputFile("问题描述 (objective.md)", args.objective, cwd)

      // ── Phase 2: 规划（建根目录 + 只读扫描）──
      mkdirSync(evolutionRoot, { recursive: true })
      const archiveRoot = join(evolutionRoot, "archive")
      // 待 archive 的旧 run 先记下来；破坏性 archive 推迟到 Phase 5（新 run 落盘后）。
      const oldRuns = listRunDirs(evolutionRoot)
      const runId = nextRunId(evolutionRoot, archiveRoot)
      evoDir = join(evolutionRoot, runId)

      // ── Phase 3: 落盘新 run（任何失败由 catch 回滚 evoDir，旧 run 完好）──
      mkdirSync(join(evoDir, "candidates", "scratch"), { recursive: true })
      mkdirSync(join(evoDir, "knowledge"), { recursive: true })
      mkdirSync(join(evoDir, "history"), { recursive: true })
      const harnessDir = join(evoDir, ".harness")
      mkdirSync(harnessDir, { recursive: true })

      // 用快照写入（不再 copyFileSync 源路径——源此刻可能已不在）
      writeFileSync(join(harnessDir, "evaluator.py"), evaluatorBytes)
      writeFileSync(join(harnessDir, "objective.md"), objectiveBytes)

      // knowledge/insights.md
      writeFileSync(
        join(evoDir, "knowledge", "insights.md"),
        "# Insights\n\n## 问题理解\n\n## 实验结论\n\n## 待验证的想法\n",
      )

      // status.md
      writeFileSync(
        join(evoDir, "status.md"),
        [
          "# Status",
          "",
          "## Facts",
          `- Iteration: 0 / ${args.budget}`,
          "- Best: (none)",
          "- Last 5 scores: []",
          "- Total candidates: 0",
          `- Budget remaining: ${args.budget} iterations`,
          "- Stagnation: 0 rounds",
          "",
          "## Diagnosis",
          "（首轮，无历史诊断）",
          "",
        ].join("\n"),
      )

      // INDEX.md
      writeFileSync(
        join(evoDir, "candidates", "INDEX.md"),
        "# Population Index\n\nNo candidates yet.\n",
      )

      // config.json（含主 session ID，供 hook 过滤子 session 的 task 调用）
      writeFileSync(
        join(harnessDir, "config.json"),
        JSON.stringify(
          {
            budget: args.budget,
            solution_pattern: args.solution_pattern,
            iteration: 0,
            direction: args.direction,
            main_session_id: context.sessionID,
          },
          null,
          2,
        ),
      )

      // ── Phase 4: 激活演化循环（state.md 写成功才算 init 完成）──
      writeFileSync(
        join(evolutionRoot, "state.md"),
        [
          "---",
          "active: true",
          `completion_promise: "演化完成"`,
          `started_at: "${new Date().toISOString()}"`,
          `session_id: "${context.sessionID}"`,
          `evolution_dir: "${evoDir}"`,
          `agent: "famou-evolution"`,
          `master_agent: "famou-master"`,
          "---",
          "FM Evolution",
          "",
        ].join("\n"),
      )

      // ── Phase 5: archive 旧 run（唯一不可逆步骤，放最后）──
      // best-effort：archive 是对"旧数据"的善后，失败不应让一次成功的新 init
      // 失败，也不是模型能处理的事——逐个 try/catch 吞掉并记日志即可。
      for (const runDir of oldRuns) {
        try {
          archiveRun(runDir, join(archiveRoot, basename(runDir)))
        } catch (e) {
          console.error(`Archive failed for ${basename(runDir)}: ${e}`)
        }
      }

      return JSON.stringify({
        evolution_dir: evoDir,
        run_id: runId,
        budget: args.budget,
        solution_pattern: args.solution_pattern,
        direction: args.direction,
      })
    } catch (e) {
      // 回滚半成品新 run：保证现场干净，且旧 run 未被触碰
      // （archive 在成功路径最后才执行，失败路径根本没跑到）。
      if (evoDir) {
        try {
          rmSync(evoDir, { recursive: true, force: true })
        } catch {
          // 回滚失败无害：残留的空 / 半 run 下一轮 init 会被 archive 清掉
        }
      }
      // 规范化为可读、可操作的 Error 回传模型。opencode 会把 tool execute
      // 抛出的 Error.message 作为 tool error 交给模型（与 billing-plugin 同机制），
      // 模型据此重写 evaluator / objective 后重试。
      const msg = e instanceof Error ? e.message : String(e)
      throw new Error(`演化初始化失败：${msg}`)
    }
  },
})
