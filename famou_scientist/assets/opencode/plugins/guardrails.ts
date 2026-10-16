/**
 * famou-scientist 强制护栏 hook（guardrails）—— OpenCode plugin。
 *
 * 设计原则：「代码校验 → 硬 hook（强制运行，agent 跳不过）」。
 * 引用核验、实验质量评估、论文数字核验都是确定性纯代码，适合做成 hook 在事件点自动触发。
 *
 * 本文件实现四个硬护栏：
 *   ① 实验质量门：agent 调 arc_run_experiment（同步）或 arc_experiment_status 报 done/failed
 *      （异步）后，检查 metrics 质量（全 0/空/失败）。同步异步共用同一道判据。
 *   ② 引用核验门：agent 调 arc_verify_paper 后，发现 hallucinated 引用则强制警告。
 *   ③ 论文数字核验门：agent 写论文文件（deliverables/paper.md / *.tex）后，把论文 Results 段的
 *      数字与 run 目录的 results.json（可信数字注册表）确定性比对，发现无实验依据的
 *      数字（可能编造）则注入强制警告。核验逻辑在自包含的 scripts/verify_paper_cli.py（纯 stdlib）。
 *   ④ 图版核验门：agent 调 arc_render_figure 出图后，确定性体检（scripts/figure_lint.py）若判
 *      severity=FAIL（如 jet/rainbow colormap、字号不可读等硬规范违规）则注入强制警告。
 *      WARN/advisory 由工具内联返回、留给 agent 自行判断，只对 FAIL 硬拦（避免误伤）。
 *   ⑤ skill 加载门：观测内置 `skill` 工具调用做会话级跟踪；当 agent 在产物型动作（写
 *      hypotheses/design/experiment.py/paper，或调 arc_run_experiment/arc_render_figure）时
 *      未 load 对应方法论 skill，则注入强制警告——把"按阶段 load skill"从软指令变成确定性兜底。
 *   ⑧ 参考文献完整性门：写/编辑论文文件后，正文里有 \cite{...} 或提到 references.bib，但同目录
 *      下 references.bib 不存在——"悬空引用"，论文交出去读者/审稿人找不到文献条目，强制补上。
 *   ⑩ 数据真实性门：写/编辑实验代码后扫描 synthetic/mock/fake/random data 红旗与真实数据加载证据；
 *      正式集群提交前由 arc_cluster_job 再做 preflight，防止用合成数据冒充真实数据复现。
 *
 * hook 与 tool 的区别：tool 是 agent「可用可不用」，hook 是 OpenCode 在事件点「必然触发」。
 * 自包含：核验脚本随插件分发，PLUGIN_ROOT 由 CLI 注入环境变量 ARC_ROOT（指向 assets/opencode）。
 */
import type { Plugin } from "@opencode-ai/plugin"
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

// 插件根目录（assets/opencode）：优先 CLI 注入的 ARC_ROOT，回退本文件所在目录的上一级
// （本文件在 <root>/plugins/guardrails.ts，故上一级即 <root>）。
const PLUGIN_ROOT =
  process.env.ARC_ROOT || path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const PY = process.env.ARC_PYTHON || "python3"
const VERIFY_SCRIPT = path.join(PLUGIN_ROOT, "scripts", "verify_paper_cli.py")

/**
 * 实验质量门的判据（纯函数，便于在多个触发点复用）。
 * 入参是含 returncode/timed_out/metrics 的实验结果对象（同步执行返回值，
 * 或异步 arc_experiment_status 在 done/failed 时返回的结果）。
 * 返回警告文本数组（空数组表示通过）。
 */
function experimentQualityWarnings(data: any): string[] {
  const warnings: string[] = []
  if (data.returncode !== 0) {
    warnings.push(`实验执行失败（returncode=${data.returncode}）——结果不可信，不要用于论文。`)
  }
  if (data.timed_out) {
    warnings.push("实验超时——结果可能不完整。")
  }
  const metrics = data.metrics || {}
  const metricVals = Object.values(metrics).filter((v) => typeof v === "number") as number[]
  if (metricVals.length === 0) {
    warnings.push("未解析到任何 metric——实验可能没真正产出结果，不要编造数据。")
  } else if (metricVals.every((v) => v === 0)) {
    warnings.push("所有 metric 都是 0——实验很可能未真正执行核心逻辑，请检查代码。")
  }
  return warnings
}

/** 把质量门警告包装成强制护栏文本（保留原始返回值附在后面）。 */
// 所有护栏文案统一追加这句：护栏文本是塞进 tool 输出、逼 agent 正视问题的"内部提示"，不是
// 写给最终用户看的产品文案（"XX门/强制护栏"这类内部代号，用户视角看就是莫名其妙的术语泄露——
// 实测踩过：agent 会原样把"孤儿论文门"念给用户）。加这句提醒 agent 转述时用人话讲问题本身。
const GATE_NOTE_FOR_AGENT =
  "（以上是给你自己看的内部提示，跟用户沟通时用你自己的话把问题本身讲清楚就好，不要把「孤儿论文门/强制护栏」这类内部术语原文念给用户。）"
function wrapQualityWarning(warnings: string[], original: string): string {
  return (
    `⚠️ 【实验质量门 - 强制护栏】\n` +
    warnings.map((w) => `  - ${w}`).join("\n") +
    `\n\n你必须向用户说明这些问题，不得用可疑数据继续写论文。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始结果 ──\n${original}`
  )
}

const DATASET_SYNTHETIC_PATTERNS: Array<[RegExp, string]> = [
  [/\bsynthetic(?:[_\s-]+data|[_\s-]+dataset)?\b/i, "出现 synthetic data/dataset"],
  [/\bmock(?:[_\s-]+data|[_\s-]+dataset)?\b/i, "出现 mock data/dataset"],
  [/\bfake(?:[_\s-]+data|[_\s-]+dataset)?\b/i, "出现 fake data/dataset"],
  [/\bdummy(?:[_\s-]+data|[_\s-]+dataset)?\b/i, "出现 dummy data/dataset"],
  [/\btoy(?:[_\s-]+data|[_\s-]+dataset)?\b/i, "出现 toy data/dataset"],
  [/\brandom(?:[_\s-]+data|[_\s-]+dataset|[_\s-]+fallback)\b/i, "出现 random data/dataset/fallback"],
  [/\bmake_(?:classification|regression|blobs|moons|circles)\s*\(/i, "使用 sklearn.datasets.make_* 生成数据"],
  [/\bnp\.random\.(?:randn|rand|normal|uniform)\s*\(/i, "使用 np.random 生成数组，疑似生成特征/标签"],
  [/\btorch\.(?:randn|rand|normal|empty)\s*\(/i, "使用 torch 随机张量，疑似生成特征/标签"],
  [/\bgenerate_[a-z0-9_]*(?:data|dataset|sample|label|pointcloud|point_cloud)s?\s*\(/i, "出现 generate_*data/dataset/sample/label/pointcloud 函数"],
]

const DATASET_REAL_EVIDENCE_PATTERNS: RegExp[] = [
  /\b(?:data_dir|data_path|dataset_dir|dataset_path|root_dir|csv_path|mesh_dir|stl_dir)\s*=/i,
  /\b(?:os\.path\.exists|Path\([^)]*\)\.exists|assert\s+.*exists)\s*\(/,
  /\b(?:pd\.read_csv|np\.load|torch\.load|load_dataset|open3d\.io\.read|trimesh\.load|glob\.glob|Path\([^)]*\)\.glob)\s*\(/,
  /\b(?:Harvard Dataverse|Dataverse|DrivAerNet|ImageNet|CIFAR|MNIST|HuggingFace)\b/i,
]

function uniqueStrings(xs: string[]): string[] {
  return Array.from(new Set(xs))
}

function datasetAuthenticityWarnings(code: string): string[] {
  const warnings: string[] = []
  const flags = DATASET_SYNTHETIC_PATTERNS.filter(([re]) => re.test(code || "")).map(([, label]) => label)
  if (flags.length > 0) {
    warnings.push(
      "检测到合成/模拟数据红旗：" + uniqueStrings(flags).join("；") +
      "。如果用户要求真实数据集/论文复现，这份代码不能作为正式实验代码。",
    )
  }
  if (!DATASET_REAL_EVIDENCE_PATTERNS.some((re) => re.test(code || ""))) {
    warnings.push(
      "未检测到明确真实数据加载证据：数据路径变量、文件存在性检查、标准数据读取调用、官方数据集名等。正式实验前必须补齐 data_path、split 样本数、len(dataset)、首 batch sanity 日志。",
    )
  }
  return warnings
}

function wrapDatasetAuthenticityWarning(warnings: string[], original: string): string {
  return (
    `⚠️ 【数据真实性门 - 强制护栏】\n` +
    warnings.map((w) => `  - ${w}`).join("\n") +
    `\n\n标准处理：先问用户是否已有真实数据集路径；若没有，问下载位置（默认 experiment/data/）并用官方方式下载。` +
    `除非用户明确要求 simulation/toy study，否则不得用合成/随机/mock 数据顶替真实数据集，也不得把 smoke test 结果当复现实验结果。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始返回 ──\n${original}`
  )
}

const WORD_RE = /[a-z0-9]+(?:[-_.][a-z0-9]+)*/gi
const PAPER_STOP_TOKENS = new Set(["a", "an", "and", "for", "in", "of", "on", "paper", "the", "this", "with", "to"])

function normalizeText(value: string): string {
  return String(value || "").toLowerCase().replace(/\s+/g, " ").trim()
}

function tokenize(value: string): string[] {
  return normalizeText(value).match(WORD_RE) || []
}

function meaningfulTokens(value: string): string[] {
  return tokenize(value).filter((t) => !PAPER_STOP_TOKENS.has(t) && t.length >= 3 && !/^\d+$/.test(t))
}

function tokenSimilarity(a: string, b: string): number {
  if (a === b) return 1
  if (!a || !b) return 0
  const dp = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0))
  for (let i = 0; i <= a.length; i++) dp[i][0] = i
  for (let j = 0; j <= b.length; j++) dp[0][j] = j
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    }
  }
  return 1 - dp[a.length][b.length] / Math.max(a.length, b.length)
}

function coreMatchScore(query: string, text: string): number {
  const qs = meaningfulTokens(query)
  const ts = meaningfulTokens(text)
  if (qs.length === 0) return 1
  if (ts.length === 0) return 0
  let hits = 0
  for (const q of qs) {
    if (ts.some((t) => tokenSimilarity(q, t) >= 0.86)) hits += 1
  }
  return hits / qs.length
}

function looksLikeSpecificPaperLookupText(text: string): boolean {
  const q = normalizeText(text)
  if (!q) return false
  if (/(survey|review|literature|related work|state of the art|sota|benchmark landscape|systematic|综述|调研|相关工作|文献)/i.test(q)) {
    return false
  }
  const tokens = tokenize(q)
  const hasVersion = /\b(v(?:er(?:sion)?)?\.?\s*)?\d+(?:\.\d+)+[a-z]?\b/i.test(q)
  const hasIdentifier = /\b(?:arxiv|doi)\b|10\.\d{4,9}\//i.test(q) || /\b\d{4}\.\d{4,5}(?:v\d+)?\b/.test(q)
  const hasTitleShape = /[:?]/.test(q) || /[A-Z][a-z]+[A-Z][A-Za-z0-9]*/.test(text) || /[-_]/.test(q)
  return hasIdentifier || (tokens.length <= 8 && (hasVersion || hasTitleShape))
}

function looksLikeBroadLiteratureQuery(text: string): boolean {
  return /(survey|review|literature|related work|systematic|benchmark landscape|综述|调研|相关工作|文献)/i.test(String(text || ""))
}

function extractTextLike(value: unknown): string {
  if (typeof value === "string") return value
  if (!value || typeof value !== "object") return ""
  const obj = value as Record<string, unknown>
  for (const key of ["text", "content", "message", "prompt", "body", "query", "input", "output"]) {
    const v = obj[key]
    if (typeof v === "string" && v.trim()) return v
  }
  for (const key of ["message", "data", "args", "payload"]) {
    const v = obj[key]
    if (v && typeof v === "object") {
      const nested = extractTextLike(v)
      if (nested) return nested
    }
  }
  return ""
}

/** 把图版核验门的硬违规（FAIL 级 check）包装成强制护栏文本。 */
function wrapFigureGateWarning(fails: any[], original: string): string {
  return (
    `⚠️ 【图版核验门 - 强制护栏】\n` +
    fails.map((c) => `  - ${c.name}：${c.msg}`).join("\n") +
    `\n\n这张图存在硬规范违规，不得用于论文。请修复绘图代码后用 arc_render_figure 重渲染，` +
    `并用 read 工具复看渲染结果（参见 scientific-visualization 视觉反馈闭环）。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始体检 ──\n${original}`
  )
}

/** 把编译核验门的硬违规（FAIL 级 check）包装成强制护栏文本。 */
function wrapLatexGateWarning(fails: any[], original: string): string {
  return (
    `⚠️ 【编译核验门 - 强制护栏】\n` +
    fails.map((c) => `  - ${c.name}：${c.msg}`).join("\n") +
    `\n\n论文编译存在致命问题（满屏 ?? / 缺图 / 根本编不过）——"编出了 PDF"不代表能投。` +
    `请逐项修复（补 \\label/.bib 条目、补缺失的图文件、改正报错），改完再用 arc_latex_check 复编，` +
    `FAIL 清零方可导出投稿。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始体检 ──\n${original}`
  )
}

// ── skill 加载门配置 ─────────────────────────────────────────
// 产物型动作 → 该动作前应已 load 的方法论 skill。命中动作但本会话没 load → 强制警告。
// 文件型（写/编辑特定 run 产物，复用数字门的 filePath 取法）：
const SKILL_FILE_GATES: { re: RegExp; skill: string; action: string }[] = [
  { re: /planning\/hypotheses\.md$/, skill: "hypothesis-formulation", action: "写 hypotheses.md（构建假设）" },
  { re: /planning\/design\.md$/, skill: "experimental-design", action: "写 design.md（实验设计）" },
  { re: /experiment\/experiment\.py$/, skill: "code-plan-review", action: "写 experiment.py（跑前代码保真审查）" },
  { re: /deliverables\/paper\.md$/, skill: "scientific-writing", action: "写 paper.md（论文写作）" },
  { re: /\.tex$/, skill: "scientific-writing", action: "写 .tex（论文写作）" },
]
// 工具型（调用某 arc_ 工具前应已 load 对应 skill）：
const SKILL_TOOL_GATES: Record<string, { skill: string; action: string }> = {
  arc_run_experiment: { skill: "code-plan-review", action: "跑实验（跑前应先做代码保真审查）" },
  arc_render_figure: { skill: "scientific-visualization", action: "出图（应走视觉反馈闭环）" },
  arc_verify_paper: { skill: "citation-faithfulness", action: "核验整篇引用（应同时查引用支撑性）" },
  arc_latex_check: { skill: "latex-fmt", action: "编译核验论文（应按 latex-fmt 取 venue 章节/页限/引用规范）" },
}

/** 把 skill 门提醒包装成强制护栏文本（保留原始返回值附在后面）。 */
function wrapSkillGateWarning(skill: string, action: string, original: string): string {
  return (
    `⚠️ 【skill 加载门 - 强制护栏】\n` +
    `  - 你正在「${action}」，但本会话未检测到 load 过 \`${skill}\` skill\n\n` +
    `请先 load \`${skill}\` 拿到 ARC 沉淀的方法论，再按它的 checklist 重做这一步——别只凭通用认知。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始返回 ──\n${original}`
  )
}

export const ArcGuardrails: Plugin = async () => {
  // skill 加载门：会话级跟踪已 load 的 skill（sessionID → 已见 skill-tool 调用参数的拼接 blob）。
  // 用 blob.includes(skillName) 判断，robust，不依赖 skill 工具的具体 arg 字段名。
  const loadedSkills = new Map<string, string>()
  // 文献检索意图：记录最近用户消息是否像“找/读某一篇论文”，用于轻量软提醒。
  const retrievalIntent = new Map<string, { specific: boolean; broad: boolean; text: string }>()
  // 孤儿论文门：会话级记录已告警过的 run 目录（sessionID → Set<runDir>），同 run 只告警一次。
  const orphanWarned = new Map<string, Set<string>>()
  // 引用核验强制门：会话级记录"本会话是否调用过 arc_verify_paper"（sessionID → boolean）。
  // 护栏②只在调用之后按结果拦截，但没人强制"必须调用"——论文可以带着一堆没查过的 \cite{}
  // 就宣布"写完了"。这里补上：写带 \cite{} 的论文文件时，若本会话从没验证过，强制提醒先查。
  const verifiedSessions = new Set<string>()
  // 可选调试：设 ARC_SKILLGATE_DEBUG=<文件路径> 开启，记录每次见到的 tool 名（用于实测确认 hook 能观测 skill 工具）。
  const SKILLGATE_DEBUG = process.env.ARC_SKILLGATE_DEBUG
  const sglog = (m: string): void => {
    if (!SKILLGATE_DEBUG) return
    try {
      fs.appendFileSync(SKILLGATE_DEBUG, `[${new Date().toISOString()}] ${m}\n`)
    } catch {
      /* ignore */
    }
  }

  return {
    /**
     * tool.execute.after —— 工具执行完触发。
     * input = { tool, sessionID, callID, args }；output.output = 工具返回字符串（可改以注入警告）。
     */
    "tool.execute.after": async (input, output) => {
      sglog(`tool=${input.tool} sid=${input.sessionID ?? "?"}`)
      const sid = String(input.sessionID || "")
      const intent = retrievalIntent.get(sid)

      // ── skill 加载门 · 跟踪 ──────────────────────────────
      // load skill = 调内置 `skill` 工具；把其参数追加进本会话 blob（供下方各门检查）。
      if (input.tool === "skill" || input.tool === "skills") {
        try {
          const sid = String(input.sessionID || "")
          const prev = loadedSkills.get(sid) || ""
          loadedSkills.set(sid, prev + " " + JSON.stringify((input as any).args || {}))
          sglog(`tracked skill load: ${JSON.stringify((input as any).args || {})}`)
        } catch {
          /* 跟踪失败不影响主流程 */
        }
      }

      // ── 护栏 ①：实验质量门（同步执行）──────────────────
      if (input.tool === "arc_run_experiment") {
        try {
          const data = JSON.parse(output.output)
          // 异步模式 launch 只返回 {state:"running", job_id}，无 metrics → 跳过，
          // 留给 arc_experiment_status 在结果就绪时再查（见下）。
          if (data.state !== "running") {
            const warnings = experimentQualityWarnings(data)
            if (warnings.length > 0) {
              output.output = wrapQualityWarning(warnings, output.output)
            }
          }
        } catch {
          /* output 不是 JSON，不拦截 */
        }
      }

      // ── 护栏 ①’：实验质量门（异步结果就绪时）──────────────
      // arc_experiment_status 报 done/failed 时，结果才有 metrics，此刻补做质量门，
      // 确保异步路径与同步路径享受同一道护栏（不会因为后台跑而绕过）。
      if (input.tool === "arc_experiment_status") {
        try {
          const data = JSON.parse(output.output)
          if (data.state === "done" || data.state === "failed") {
            const warnings = experimentQualityWarnings(data)
            if (warnings.length > 0) {
              output.output = wrapQualityWarning(warnings, output.output)
            }
          }
        } catch {
          /* 非 JSON，不拦截 */
        }
      }

      // ── 护栏 ②：引用核验门 ──────────────────────────────
      if (input.tool === "arc_verify_paper") {
        verifiedSessions.add(sid) // 标记"调过"，跟结果好坏无关——⑨门只管有没有查
        try {
          const data = JSON.parse(output.output)
          if (data.hallucinated > 0 || data.suspicious > 0) {
            output.output =
              `⚠️ 【引用核验门 - 强制护栏】\n` +
              `  - 发现 ${data.hallucinated} 条疑似编造引用、${data.suspicious} 条可疑引用\n` +
              `  - 这些引用未能在 arXiv/CrossRef/OpenAlex 核实\n\n` +
              `你必须删除或替换这些引用，绝不能让编造的引用进入最终论文。` +
              GATE_NOTE_FOR_AGENT +
              `\n\n── 核验报告 ──\n${output.output}`
          }
        } catch {
          /* 非 JSON，不拦截 */
        }
      }

      // ── 护栏 ②’：论文候选质量门 ───────────────────────
      // 具体论文/模糊论文查找后，若返回结果与 query 没有核心词重合，提示不要把
      // 数字/版本号/泛词匹配当成候选论文。
      if (["websearch", "web_search", "webfetch", "web_fetch", "arc_search_literature"].includes(input.tool)) {
        try {
          const query = extractTextLike((input as any).args?.query || "") || intent?.text || ""
          const paperLike = looksLikeSpecificPaperLookupText(query) || intent?.specific || false
          if (paperLike && query && coreMatchScore(query, output.output || "") < 0.25) {
            output.output =
              `⚠️ 【论文候选质量门 - 强制护栏】\n` +
              `  - 本次检索看起来是在找具体论文，但返回内容与查询核心词几乎没有匹配\n` +
              `  - 这类结果不要当作候选论文展示给用户，先用原始 query 重新核验网页证据，或补更强线索（作者/DOI/arXiv ID/机构）\n\n` +
              GATE_NOTE_FOR_AGENT +
              `\n\n── 原始返回 ──\n${output.output}`
          }
        } catch {
          /* 不拦截 */
        }
      }

      // ── 护栏 ②’’：检索升级门 ─────────────────────────
      // 用户只是在找单篇/模糊论文，但 agent 做 broad literature search 时提醒收紧。
      if (input.tool === "arc_search_literature") {
        try {
          const query = extractTextLike((input as any).args?.query || "")
          if ((intent?.specific || looksLikeSpecificPaperLookupText(query)) && looksLikeBroadLiteratureQuery(query)) {
            output.output =
              `⚠️ 【检索升级门 - 强制护栏】\n` +
              `  - 这轮上下文更像是在找单篇论文，不是要做 broad literature review\n` +
              `  - 先完成具体论文定位与核验，再决定是否扩大到 related work / survey\n\n` +
              GATE_NOTE_FOR_AGENT +
              `\n\n── 原始返回 ──\n${output.output}`
          }
        } catch {
          /* 不拦截 */
        }
      }

      // ── 护栏 ④：图版核验门 ──────────────────────────────
      // arc_render_figure 出图后做确定性体检，severity=FAIL（硬规范违规）才强制拦截。
      if (input.tool === "arc_render_figure") {
        try {
          const data = JSON.parse(output.output)
          if (data.rendered && data.severity === "FAIL") {
            const fails = (data.checks || []).filter((c: any) => c.level === "FAIL")
            if (fails.length > 0) {
              output.output = wrapFigureGateWarning(fails, output.output)
            }
          }
        } catch {
          /* 非 JSON，不拦截 */
        }
      }

      // ── 护栏 ⑥：编译核验门 ──────────────────────────────
      // arc_latex_check 真编 paper.tex 后做确定性体检，severity=FAIL（悬空 ??/缺图/编不过）才强制拦截。
      // "编出 PDF/退出码 0" ≠ 没问题——FAIL 级是会被审稿人一眼看穿的硬伤，不许带着导出投稿。
      if (input.tool === "arc_latex_check") {
        try {
          const data = JSON.parse(output.output)
          if (data.severity === "FAIL") {
            const fails = (data.checks || []).filter((c: any) => c.level === "FAIL")
            if (fails.length > 0) {
              output.output = wrapLatexGateWarning(fails, output.output)
            }
          }
        } catch {
          /* 非 JSON，不拦截 */
        }
      }

      // ── 护栏 ③：论文数字核验门 ──────────────────────────
      // 写/编辑论文文件后，确定性核验论文 Results 段的数字是否都有实验依据。
      if (input.tool === "write" || input.tool === "edit") {
        const fp = String((input.args as any)?.filePath || "")
        // ── 护栏 ⑪：正式文献清单门 ───────────────────────
        // literature.md 是用户可见的综述结论；若没有同 run 的 paper_cards.jsonl，说明
        // 检索候选/子 agent 结果尚未被主 agent 汇总成正式清单。写入仍保留，但提醒不能宣布完成。
        if (/planning\/(?:literature|literature_map)\.md$/.test(fp)) {
          const runDir = resolveRunDir(fp)
          if (runDir) {
            const cardPaths = [
              path.join(runDir, "paper_cards.jsonl"),
              path.join(runDir, "planning", "paper_cards.jsonl"),
              path.join(runDir, "deliverables", "paper_cards.jsonl"),
            ]
            const hasCards = cardPaths.some((p) => {
              try { return fs.statSync(p).size > 0 } catch { return false }
            })
            if (!hasCards) {
              output.output =
                `⚠️ 【正式文献清单门 - 强制护栏】\n` +
                `  - 已写入文献综述，但同一 run 中没有非空 paper_cards.jsonl\n` +
                `  - 聊天列表、检索工具 accepted 或子 agent 返回都不是最终筛选清单\n\n` +
                `请由主 agent 完成去重与相关性核验，写入 paper_cards.jsonl 后再宣布文献调研完成；` +
                `右侧文献、综述和后续 references.bib 都应以它为准。` +
                GATE_NOTE_FOR_AGENT +
                `\n\n── 原始返回 ──\n${output.output}`
            }
          }
        // ── 护栏 ⑩：数据真实性门 ─────────────────────────
        }
        // 写/编辑正式实验代码后，立刻扫描合成/随机/mock 数据红旗与真实数据加载证据。
        // 这是 DrivAerNet/Harvard Dataverse 这类真实数据复现问题的硬兜底：不能让 agent
        // 先用自己造的数据跑完，再事后承认"不是复现"。
        if (/experiment\/experiment\.py$/.test(fp) || /(?:^|\/)(?:train|run|main|experiment)\.py$/.test(fp)) {
          try {
            const code = fs.readFileSync(fp, "utf-8")
            const warnings = datasetAuthenticityWarnings(code)
            if (warnings.length > 0) {
              output.output = wrapDatasetAuthenticityWarning(warnings, output.output)
            }
          } catch {
            /* 读不到代码则不拦截；后续 cluster submit preflight 仍会再查 */
          }
        }
        // 只对成品论文文件触发（deliverables/paper.md 或 任意 .tex）
        if (/deliverables\/paper\.md$/.test(fp) || /\.tex$/.test(fp)) {
          // results.json 相对论文文件自身定位（不依赖 PLUGIN_ROOT）：
          // 论文在 <run>/deliverables/paper.md，results.json 在 <run>/experiment/results.json。
          // 顺着论文路径找到含 deliverables 的 run 目录，再拼 experiment/results.json。
          const resultsJson = resolveResultsJson(fp)
          if (resultsJson) {
            try {
              // results.json 不存在时脚本 exit 3 → execFileSync 抛 → catch 静默（中途写作不打扰）
              const out = execFileSync(PY, [VERIFY_SCRIPT, "--paper", fp, "--results", resultsJson], {
                encoding: "utf-8",
                timeout: 30000,
              })
              const r = JSON.parse(out)
              if (r.severity === "REJECT") {
                const nums = (r.unverified || [])
                  .map((u: any) => `${u.value}（${u.section}）`)
                  .join("、")
                output.output =
                  `⚠️ 【论文数字核验门 - 强制护栏】\n` +
                  `  - 论文 Results/实验段出现 ${r.strict_violations} 个无实验依据的数字：${nums}\n` +
                  `  - 它们在本次实验的 results.json 可信记录里找不到（容差 1% 内）——可能是编造\n\n` +
                  `你必须逐个核验：要么改成真实结果、要么从 results.json 取真值；绝不能让编造数字进论文。` +
                  GATE_NOTE_FOR_AGENT +
                  `\n\n── 原始返回 ──\n${output.output}`
              }
            } catch {
              /* 脚本失败 / 无 results.json / 论文还没数字 —— 不拦截（中途写作） */
            }
          }
        }
      }

      // ── 护栏 ⑦：孤儿论文门 ──────────────────────────────
      // 写/编辑某 run 目录内文件时，若该 run 的 deliverables 已有论文/评审产物、却没有
      // experiment/results.json —— 极可能是「别的研究遗留」或「越级早写」。注入强制告警，
      // 防止把残留当本 run 成果（"实验没做完论文却已存在"的根源）。每会话+run 只告警一次。
      if (input.tool === "write" || input.tool === "edit") {
        const fp = String((input.args as any)?.filePath || "")
        const runDir = resolveRunDir(fp)
        if (runDir) {
          const sid = String(input.sessionID || "")
          const warnedSet = orphanWarned.get(sid) || new Set<string>()
          if (!warnedSet.has(runDir) && hasOrphanPaper(runDir)) {
            output.output = wrapOrphanWarning(runDir, output.output)
            warnedSet.add(runDir)
            orphanWarned.set(sid, warnedSet)
          }
        }
      }

      // ── 护栏 ⑧：参考文献完整性门 ──────────────────────────
      // 写/编辑论文文件后，正文里出现 \cite{...} 或提到 "references.bib"，但同目录下
      // references.bib 不存在——"悬空引用"：论文交出去，读者/审稿人找不到对应文献条目。
      // 不做会话级去重（跟数字门③一样每次都重查）：一旦 agent 把 references.bib 补上，
      // 条件自然不成立，警告自己停；在那之前每次改论文都该提醒，不能只提一次就不管了。
      if (input.tool === "write" || input.tool === "edit") {
        const fp = String((input.args as any)?.filePath || "")
        if (/deliverables\/paper\.md$/.test(fp) || /\.tex$/.test(fp)) {
          try {
            const content = fs.readFileSync(fp, "utf-8")
            const hasCite = /\\cite\{/.test(content) || /references\.bib/i.test(content)
            if (hasCite) {
              const bibPath = path.join(path.dirname(fp), "references.bib")
              if (!fs.existsSync(bibPath)) {
                output.output = wrapBibGateWarning(bibPath, output.output)
              }
            }
          } catch {
            /* 读文件失败（罕见）——不拦截 */
          }
        }
      }

      // ── 护栏 ⑨：引用核验强制门 ──────────────────────────
      // 护栏②只在 arc_verify_paper 调用之后按结果拦截，但没人强制"必须调用"过——论文可以带着
      // 一堆没查过真实性的 \cite{} 就直接宣布"写完了"。这里补上：写带 \cite{} 的论文文件时，
      // 若本会话从未调用过 arc_verify_paper，强制提醒先查——跟⑧一样每次重查，查过就不再触发。
      if (input.tool === "write" || input.tool === "edit") {
        const fp = String((input.args as any)?.filePath || "")
        if (/deliverables\/paper\.md$/.test(fp) || /\.tex$/.test(fp)) {
          try {
            const content = fs.readFileSync(fp, "utf-8")
            if (/\\cite\{/.test(content) && !verifiedSessions.has(String(input.sessionID || ""))) {
              output.output = wrapVerifyGateWarning(output.output)
            }
          } catch {
            /* 读文件失败（罕见）——不拦截 */
          }
        }
      }

      // ── 护栏 ⑤：skill 加载门 ────────────────────────────
      // 产物型动作前应已 load 对应方法论 skill；本会话 blob 不含 → 注入强制提醒。
      // 注：与上面的门可叠加（如 paper.md 同时触发数字门③与本门⑤），各自独立 prepend。
      {
        const blob = loadedSkills.get(String(input.sessionID || "")) || ""
        // 文件型
        if (input.tool === "write" || input.tool === "edit") {
          const fp = String((input.args as any)?.filePath || "")
          for (const g of SKILL_FILE_GATES) {
            if (g.re.test(fp) && !blob.includes(g.skill)) {
              output.output = wrapSkillGateWarning(g.skill, g.action, output.output)
              break // 一个动作只提示一个前置 skill
            }
          }
        }
        // 工具型
        const tg = SKILL_TOOL_GATES[input.tool]
        if (tg && !blob.includes(tg.skill)) {
          output.output = wrapSkillGateWarning(tg.skill, tg.action, output.output)
        }
      }
    },

    "chat.message": async (input) => {
      try {
        const sid = String((input as any).sessionID || "")
        if (!sid) return
        const text = extractTextLike((input as any).message || input)
        if (!text) return
        retrievalIntent.set(sid, {
          specific: looksLikeSpecificPaperLookupText(text),
          broad: looksLikeBroadLiteratureQuery(text),
          text,
        })
      } catch {
        /* ignore */
      }
    },
  }
}

/**
 * 从论文文件路径推算同一 run 的 experiment/results.json 路径。
 * 论文在 <run>/deliverables/paper.md（或 .tex），results.json 在 <run>/experiment/results.json。
 * 不依赖 PLUGIN_ROOT —— run 目录在用户工作区，相对论文文件自身定位才正确。
 */
function resolveResultsJson(paperPath: string): string | null {
  const deliverablesDir = path.dirname(paperPath) // <run>/deliverables（paper.md 时）
  // 兼容 paper 直接放 deliverables/ 下，或更深一层
  let dir = deliverablesDir
  for (let i = 0; i < 4; i++) {
    if (path.basename(dir) === "deliverables") {
      const runDir = path.dirname(dir)
      return path.join(runDir, "experiment", "results.json")
    }
    const parent = path.dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  // 论文不在 deliverables/ 下（如 *.tex 放别处）：退而求其次，找同级或上级的 experiment/
  const sibling = path.join(path.dirname(paperPath), "..", "experiment", "results.json")
  return sibling
}

/**
 * 从任意文件路径推算它所属的 run 根目录 `<...>/research-runs/<topic>`（绝对或相对都行）。
 * 不在 research-runs/ 下 → null。
 */
function resolveRunDir(fp: string): string | null {
  const norm = String(fp).replace(/\\/g, "/")
  const idx = norm.indexOf("research-runs/")
  if (idx < 0) return null
  const topic = norm.slice(idx + "research-runs/".length).split("/")[0]
  if (!topic) return null
  return norm.slice(0, idx) + "research-runs/" + topic
}

/**
 * run 目录是否"孤儿"：deliverables 已有论文产物（paper.md / 任意 *.tex），
 * 却没有 experiment/results.json —— 残留或越级早写的强信号。
 */
function hasOrphanPaper(runDir: string): boolean {
  try {
    const deliv = path.join(runDir, "deliverables")
    const resultsJson = path.join(runDir, "experiment", "results.json")
    if (fs.existsSync(resultsJson)) return false // 有真结果 → 不是孤儿
    if (fs.existsSync(path.join(deliv, "paper.md"))) return true
    let names: string[] = []
    try { names = fs.readdirSync(deliv) } catch { return false }
    return names.some((n) => n.endsWith(".tex"))
  } catch {
    return false
  }
}

/** 把孤儿论文门告警包装成强制护栏文本（保留原始返回值附在后面）。 */
function wrapOrphanWarning(runDir: string, original: string): string {
  return (
    `⚠️ 【孤儿论文门 - 强制护栏】\n` +
    `  - 目录 \`${runDir}/deliverables\` 已有论文/评审产物，但 \`experiment/results.json\` 不存在\n` +
    `  - 这极可能是**别的研究遗留**在此目录、或**实验没做完就越级写论文**\n\n` +
    `请先核对：这些产物是不是本次研究亲手产出的？若是残留——清理掉或换一个干净的 run 目录；` +
    `绝不能把别的研究的论文当作本 run 的成果。**论文只在本 run 的 results.json 出来后才写。**` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始返回 ──\n${original}`
  )
}

/** 把参考文献完整性门告警包装成强制护栏文本（保留原始返回值附在后面）。 */
function wrapBibGateWarning(bibPath: string, original: string): string {
  return (
    `⚠️ 【参考文献完整性门 - 强制护栏】\n` +
    `  - 论文正文用了 \\cite{...} 或提到了 references.bib，但 \`${bibPath}\` 不存在\n` +
    `  - 这是悬空引用——读者/审稿人拿不到对应的文献条目\n\n` +
    `你必须现在就把 references.bib 生成出来：每个 \\cite{key} 对应一条真实文献的 BibTeX 条目，` +
    `数据取自你已检索到的文献（literature.md / arc_search_literature 的结果），绝不能编造，` +
    `别把这一步拖到"以后"。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始返回 ──\n${original}`
  )
}

/** 把引用核验强制门告警包装成强制护栏文本（保留原始返回值附在后面）。 */
function wrapVerifyGateWarning(original: string): string {
  return (
    `⚠️ 【引用核验强制门 - 强制护栏】\n` +
    `  - 论文正文用了 \\cite{...}，但本会话还没调用过 arc_verify_paper 核实过这些引用\n\n` +
    `你必须先调 arc_verify_paper 核实一遍，确认没有编造/幻觉引用，再宣布论文写完。` +
    GATE_NOTE_FOR_AGENT +
    `\n\n── 原始返回 ──\n${original}`
  )
}
