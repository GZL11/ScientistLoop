/**
 * famou-scientist research capability tools for OpenCode (self-contained).
 *
 * 架构：OpenCode 是 master agent，本插件是能力库。
 *
 * - 知识类能力（假设生成/实验设计/科学写作）→ 不在这里，由 OpenCode
 *   读 skill 库（../skills/）自己执行。
 * - 真执行能力（文献检索/实验执行/引用核验）→ 这里的工具，调本插件
 *   自包含的 Python 内核（scripts/*.py），不依赖任何外部包（纯 stdlib）。
 *
 * 自包含：Python 内核从 ARC 一次性剥离，已剪断 researchclaw 依赖。
 * 部署时 PLUGIN_ROOT 由 CLI（famou_scientist.launcher）注入环境变量 ARC_ROOT，
 * 指向本插件安装目录（.../assets/opencode）。
 */
import { tool } from "@opencode-ai/plugin"
import { spawn, spawnSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

// 插件根目录（assets/opencode）：优先 CLI 注入的 ARC_ROOT，回退到本文件所在目录的上一级
// （本文件在 <root>/tool/arc.ts，故上一级即 <root>）。
const PLUGIN_ROOT =
  process.env.ARC_ROOT || path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const SCRIPTS = path.join(PLUGIN_ROOT, "scripts")
// 跑用户实验/内核脚本用的 python3：优先 CLI 注入的 ARC_PYTHON，回退 PATH 里的 python3。
const PY = process.env.ARC_PYTHON || "python3"
// 异步实验 job 目录根：默认落在用户工作目录的 .famou_jobs/，可用 ARC_JOBS_DIR 覆盖。
const JOBS_ROOT = process.env.ARC_JOBS_DIR || path.join(process.cwd(), ".famou_jobs")

// 产物路径参数（out_path/results_path/tex_path…）语义上是"相对项目根"（跟 bash/read/write 等
// 工具一致），但 runPython 起的 python 子进程 cwd 定在 SCRIPTS（插件自身目录，见下），不是项目根——
// 若原样把相对路径塞进子脚本，Python 端 Path(rel) 会相对 SCRIPTS 解析，落到完全错误的地方（实测
// 踩过：arc_generate_schematic 报"已生成"，真实 research-runs/ 下却找不到文件，图藏进了
// assets/opencode/scripts/research-runs/ 底下）。这里统一在传给 Python 前转成绝对路径，与 cwd 无关。
function projectPath(p: string): string {
  const s = String(p || "")
  return s && !path.isAbsolute(s) ? path.join(process.cwd(), s) : s
}

/** 跑一段 Python（cwd=scripts，可直接 import 内核模块），返回 stdout。 */
function runPython(code: string, timeoutMs = 300_000): string {
  const r = spawnSync(PY, ["-c", code], {
    cwd: SCRIPTS,
    encoding: "utf-8",
    timeout: timeoutMs,
    maxBuffer: 20 * 1024 * 1024,
  })
  if (r.status !== 0) {
    return `[famou-scientist error exit=${r.status}]\n${r.stderr || r.stdout || "(no output)"}`
  }
  return (r.stdout || "").trim() || "(empty result)"
}

/**
 * 截断灌进上下文的长文本：保留头 + 尾（中间用省略标记），避免实验全量 stdout
 * （多条件/多 epoch 的打印）把上下文吹爆。全量始终在 job 的 runner.log 里可查。
 */
function headTail(s: string, head = 1500, tail = 3000): string {
  s = s || ""
  if (s.length <= head + tail) return s
  const omitted = s.length - head - tail
  return `${s.slice(0, head)}\n…[已截断 ${omitted} 字符，全量见 job 目录 runner.log]…\n${s.slice(-tail)}`
}

const SEARCH_STOPWORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into",
  "is", "it", "of", "on", "or", "paper", "papers", "research", "study", "survey", "the",
  "to", "using", "via", "with", "without", "what", "which", "why", "this", "that", "these",
])

function searchTokens(s: string): string[] {
  const raw = String(s || "").toLowerCase().match(/[a-z0-9][a-z0-9._-]*/g) || []
  return raw
    .map((t) => t.replace(/^v(?=\d)/, ""))
    .filter((t) => t.length > 1 && !SEARCH_STOPWORDS.has(t))
}

function unique<T>(xs: T[]): T[] {
  return Array.from(new Set(xs))
}

function looksLikeVersionOnlyMatch(queryTokens: string[], textTokens: string[]): boolean {
  const matched = queryTokens.filter((t) => textTokens.includes(t))
  if (!matched.length) return false
  return matched.every((t) => /^\d+(\.\d+)*$/.test(t) || /^20\d\d$/.test(t))
}

function scoreLiteratureCandidate(p: any, query: string, userQuery: string, mode: string) {
  const qTokens = unique(searchTokens([userQuery, query].filter(Boolean).join(" ")))
  const title = String(p?.title || "")
  const abstract = String(p?.abstract || "")
  const titleTokens = unique(searchTokens(title))
  const bodyTokens = unique(searchTokens(title + " " + abstract))
  const titleHits = qTokens.filter((t) => titleTokens.includes(t))
  const bodyHits = qTokens.filter((t) => bodyTokens.includes(t))
  const matchReasons: string[] = []
  const rejectReasons: string[] = []
  let score = 0

  if (qTokens.length === 0) score = 0.2
  if (titleHits.length) {
    score += Math.min(0.58, titleHits.length / Math.max(3, qTokens.length) * 0.7)
    matchReasons.push(`标题命中核心词: ${titleHits.slice(0, 6).join(", ")}`)
  }
  if (bodyHits.length > titleHits.length) {
    score += Math.min(0.28, (bodyHits.length - titleHits.length) / Math.max(4, qTokens.length) * 0.4)
    matchReasons.push(`摘要/元数据补充命中: ${bodyHits.filter((t) => !titleHits.includes(t)).slice(0, 6).join(", ")}`)
  }
  if (p?.doi || p?.arxiv_id || p?.url) {
    score += 0.08
    matchReasons.push("有 DOI/arXiv/URL 元数据")
  }
  if (p?.year && Number(p.year) >= 2022) score += 0.04

  if (looksLikeVersionOnlyMatch(qTokens, titleTokens)) {
    score -= 0.45
    rejectReasons.push("仅命中版本号/年份/数字，缺少主题核心词")
  }
  if (qTokens.length >= 2 && titleHits.length === 0 && bodyHits.length <= 1) {
    score -= 0.25
    rejectReasons.push("标题未命中核心词，摘要命中也很弱")
  }
  if (String(mode || "").toLowerCase() === "paper" && titleHits.length === 0) {
    score -= 0.2
    rejectReasons.push("具体论文查找场景下标题不匹配")
  }

  score = Math.max(0, Math.min(1, score))
  if (!matchReasons.length && bodyHits.length) matchReasons.push(`弱命中: ${bodyHits.slice(0, 4).join(", ")}`)
  return { score, matchReasons, rejectReasons }
}

function classifyLiteratureResults(raw: any[], query: string, userQuery: string, mode: string, limit: number) {
  const accepted: any[] = []
  const rejected: any[] = []
  const uncertain: any[] = []
  for (const p of raw || []) {
    const scored = scoreLiteratureCandidate(p, query, userQuery, mode)
    const item = {
      ...p,
      relevance_score: Number(scored.score.toFixed(3)),
      match_reasons: scored.matchReasons,
      reject_reasons: scored.rejectReasons,
      source_queries: unique([userQuery, query].filter(Boolean)),
    }
    if (scored.rejectReasons.length && scored.score < 0.25) rejected.push({
      ...item,
      reject_reason: scored.rejectReasons.join("; "),
      mismatch_type: scored.rejectReasons.some((r) => r.includes("版本号")) ? "version_only" : "weak_metadata",
    })
    else if (scored.score >= 0.28 || accepted.length < Math.min(3, limit)) accepted.push(item)
    else uncertain.push(item)
  }
  return {
    accepted: accepted.slice(0, limit),
    uncertain: uncertain.slice(0, Math.max(0, limit - accepted.length)),
    rejected,
  }
}

function appendSearchDiagnostic(record: any) {
  const line = JSON.stringify(record) + "\n"
  const targets = [
    path.join(process.cwd(), "search_diagnostics.jsonl"),
    path.join(process.cwd(), "queries.jsonl"),
  ]
  for (const target of targets) {
    try {
      fs.appendFileSync(target, line, "utf-8")
    } catch {
      /* Diagnostics are best-effort and must never break retrieval. */
    }
  }
}

export const search_literature = tool({
  description: `统一学术文献检索入口（OpenAlex + Semantic Scholar + arXiv 多源）。

返回论文列表（标题/作者/年份/摘要/DOI）。这是真实 API 调用，不是 LLM 编造。

使用原则：
- 具体论文/模糊论文名查找：原生 websearch/webfetch 负责第一轮网页入口和页面核验；本工具用于补充 OpenAlex/Semantic Scholar/arXiv 元数据、摘要、DOI/arXiv ID 和相近学术候选。
- 主题/related work/survey：本工具可直接用于多源学术检索，并按 literature-search skill 的当前策略拆分子方向。
- 不再因为 query 像具体论文名而拒绝；但候选必须经过标题核心词、作者/年份/URL 证据核验，不能把只匹配数字、版本号、年份或泛词的结果当作候选论文。`,
  args: {
    query: tool.schema.string().describe("检索关键词"),
    user_query: tool.schema
      .string()
      .optional()
      .describe("可选：用户原始问题。具体论文/模糊论文名查找时建议原样传入，用于保留可追溯性。"),
    mode: tool.schema
      .string()
      .optional()
      .describe("可选：auto | paper | topic | systematic。当前作为检索意图标记和轨迹记录，实际检索仍返回学术候选。"),
    output_format: tool.schema
      .string()
      .optional()
      .describe("可选：structured | array。默认 structured，返回 accepted/rejected/uncertain/diagnostics；array 用于旧调用兼容。"),
    limit: tool.schema.number().describe("最多返回几篇").default(15),
  },
  async execute(args) {
    const limit = Number(args.limit) || 15
    const userQuery = String((args as any).user_query || "").trim()
    const query = String(args.query || userQuery || "")
    const mode = String((args as any).mode || "auto").trim() || "auto"
    const outputFormat = String((args as any).output_format || "structured").trim()
    const code = `
import json
from search import search_papers

# 控制注入上下文的体积：摘要只回前 ~280 字（够判相关性/选篇），承重文献再用
# arc_fetch_source 按需取全文摘要；作者截前 4 个；compact 输出（无 indent）。
# 经验：全量 abstract+5作者+indent 单次可达 ~49K 字符，是上下文被吹爆的主因。
_ABS = 280
def _trunc(s, n=_ABS):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rstrip() + "…"

papers = search_papers(${JSON.stringify(query)}, limit=${limit})
out = []
for p in papers:
    names = [a.name for a in p.authors]
    authors = names[:4] + (["et al."] if len(names) > 4 else [])
    out.append({
        "title": p.title,
        "authors": authors,
        "year": getattr(p, "year", None),
        "doi": p.doi,
        "arxiv_id": getattr(p, "arxiv_id", "") or "",
        "url": getattr(p, "url", "") or "",
        "abstract": _trunc(p.abstract),
    })
print(json.dumps(out, ensure_ascii=False))
`
    const stdout = runPython(code)
    let raw: any[] = []
    try {
      const parsed = JSON.parse(stdout)
      raw = Array.isArray(parsed) ? parsed : []
    } catch {
      return stdout
    }
    const buckets = classifyLiteratureResults(raw, query, userQuery, mode, limit)
    const diagnostics = {
      query,
      user_query: userQuery,
      intent: mode,
      sources: ["openalex", "semantic_scholar", "arxiv"],
      raw_count: raw.length,
      accepted_count: buckets.accepted.length,
      rejected_count: buckets.rejected.length,
      uncertain_count: buckets.uncertain.length,
      failure_mode: buckets.accepted.length ? "" : "insufficient_retrieval_evidence",
      notes: buckets.accepted.length ? "accepted candidates require downstream source verification" : "no sufficiently relevant accepted candidates; do not infer novelty or absence of prior work",
      created_at: new Date().toISOString(),
    }
    appendSearchDiagnostic(diagnostics)
    if (outputFormat === "array") return JSON.stringify(buckets.accepted)
    return JSON.stringify({
      query,
      user_query: userQuery,
      intent: mode,
      accepted: buckets.accepted,
      rejected: buckets.rejected,
      uncertain: buckets.uncertain,
      diagnostics,
      edges: buckets.accepted.map((p) => ({
        source: `query:${query}`,
        target: p.paper_id || p.doi || p.arxiv_id || p.title,
        relation: "retrieved_by",
        evidence: query,
        confidence: p.relevance_score >= 0.55 ? "high" : p.relevance_score >= 0.35 ? "medium" : "low",
      })),
    })
  },
})

export const lookup_paper = tool({
  description: `查找用户提到的某一篇具体论文（支持标题、缩写、近似拼写、arXiv ID、DOI）。

用于「X 这篇论文看一下」「X paper」「某个 bench/method 的论文」这类请求。
它会融合 OpenAlex/Semantic Scholar/arXiv 的学术检索；若已配置网页搜索，也会并行用用户原始 query 做 web search，
再统一给候选打分。中低置信候选必须先问用户确认，不要直接当作目标论文。`,
  args: {
    query: tool.schema.string().describe("用户给出的论文名、缩写、近似标题、arXiv ID 或 DOI。第一轮应原样传入，不要擅自追加 arxiv/paper。"),
    limit: tool.schema.number().describe("返回候选数量，默认 5。").default(5),
  },
  async execute(args) {
    const query = String(args.query || "").trim()
    const limit = Number(args.limit) || 5
    if (!query) throw new Error("query 为空。请传入论文名、缩写、arXiv ID 或 DOI。")
    let webResults: Array<{ title: string; url: string; snippet: string }> = []
    if (process.env.AI_SEARCH_KEY) {
      try {
        const raw = await runBaiduWebSearch(query, Math.min(Math.max(limit * 2, 8), 12))
        webResults = raw.map((r) => ({
          title: r.title?.trim() || "",
          url: r.url?.trim() || "",
          snippet: r.snippet?.trim() || "",
        })).filter((r) => r.title || r.url || r.snippet)
      } catch {
        webResults = []
      }
    }
    const code = `
import json
from paper_lookup import lookup_paper
result = lookup_paper(
    ${JSON.stringify(query)},
    limit=${limit},
    web_results=json.loads(${JSON.stringify(JSON.stringify(webResults, null, 2))}),
)
print(json.dumps(result, ensure_ascii=False))
`
    return runPython(code)
  },
})

/* ───────────────────────────────────────────────────────────────
 * 能力 2：实验执行 —— 真在 sandbox 跑 Python 代码
 * ─────────────────────────────────────────────────────────────── */
export const run_experiment = tool({
  description: `在 sandbox 中真实执行 Python 实验代码，返回 stdout/stderr/metrics。

代码会被 AST 安全校验后执行。用于跑 OpenCode 自己设计/生成的实验。
返回真实运行结果（含解析出的 metrics），不是 LLM 编造。

两种模式：
- 同步（默认，is_async=false）：阻塞直到跑完，适合秒级 smoke test。
- 异步（is_async=true）：实验在后台 detached 进程跑，**立即返回 job_id**，
  master agent 不被阻塞、可继续对话/做别的事，之后用 arc_experiment_status(job_id)
  查状态。**长任务（训练/下数据/预计 >120s）必须用异步。**`,
  args: {
    code: tool.schema.string().describe("要执行的 Python 代码"),
    timeout_sec: tool.schema.number().describe("超时秒数").default(300),
    is_async: tool.schema
      .boolean()
      .describe("是否后台异步执行（长任务必须 true，立即返回 job_id 不阻塞）")
      .default(false),
  },
  async execute(args, ctx) {
    const timeoutSec = Number(args.timeout_sec) || 300
    const userCode = String(args.code || "")

    // ── 异步模式：detached 进程后台跑，立即返回 job_id ──
    if (args.is_async) {
      const jobId = `job_${Date.now()}_${Math.floor(Math.random() * 1e6)}`
      const jobDir = path.join(JOBS_ROOT, jobId)
      fs.mkdirSync(jobDir, { recursive: true })
      fs.writeFileSync(path.join(jobDir, "code.py"), userCode, "utf-8")
      // 记录发起会话 + timeout（供 heartbeat 把完成/进度通知精准发回本会话、并算超时占比）
      try {
        const sessionID = (ctx as any)?.sessionID
        fs.writeFileSync(
          path.join(jobDir, "meta.json"),
          JSON.stringify({ sessionID: sessionID || null, created: Date.now(), timeout_sec: timeoutSec }),
          "utf-8",
        )
      } catch {
        /* meta 写失败不影响实验启动 */
      }
      const logFd = fs.openSync(path.join(jobDir, "runner.log"), "a")
      const child = spawn(PY, [path.join(SCRIPTS, "async_runner.py"), jobDir, String(timeoutSec)], {
        cwd: SCRIPTS,
        detached: true,
        stdio: ["ignore", logFd, logFd],
        env: { ...process.env, ARC_PYTHON: PY },
      })
      child.unref()
      fs.closeSync(logFd)
      return JSON.stringify(
        {
          job_id: jobId,
          state: "running",
          job_dir: jobDir,
          timeout_sec: timeoutSec,
          hint: "实验已后台启动。用 arc_experiment_status(job_id) 在自然断点查状态，切勿轮询。结果就绪前不要开始依赖它的步骤（分析/写 Results/研究决策）。",
        },
        null,
        2,
      )
    }

    // ── 同步模式（默认）：阻塞跑完再返回 ──
    const code = `
import json, tempfile
from pathlib import Path
from sandbox import ExperimentSandbox, SandboxConfig
cfg = SandboxConfig(python_path=${JSON.stringify(PY)})
with tempfile.TemporaryDirectory() as d:
    sb = ExperimentSandbox(cfg, Path(d))
    r = sb.run(${JSON.stringify(userCode)}, timeout_sec=${timeoutSec})
    print(json.dumps({
        "returncode": r.returncode,
        "timed_out": r.timed_out,
        "metrics": r.metrics,
        "stdout": (r.stdout or "")[-3000:],
        "stderr": (r.stderr or "")[-1500:],
    }, ensure_ascii=False, indent=2))
`
    return runPython(code, (timeoutSec + 60) * 1000)
  },
})

/* ───────────────────────────────────────────────────────────────
 * 能力 2b：查异步实验状态 —— 读 job 目录的信号文件（零 python、零 LLM）
 * ─────────────────────────────────────────────────────────────── */
export const experiment_status = tool({
  description: `查询 arc_run_experiment(is_async=true) 启动的后台实验状态。

确定性读 job 目录的信号文件（status.json / result.json），不重新执行、不调模型。
- running：实验还在跑，返回末尾日志；**不要反复轮询**，在下个自然断点再查。
- done/failed：返回真实 metrics + stdout/stderr 尾部，可据此进入分析/自愈。`,
  args: {
    job_id: tool.schema.string().describe("arc_run_experiment 异步返回的 job_id"),
  },
  async execute(args) {
    const jobId = String(args.job_id || "")
    const jobDir = path.join(JOBS_ROOT, jobId)
    if (!fs.existsSync(jobDir)) {
      return JSON.stringify({ job_id: jobId, state: "unknown", error: "找不到该 job（job_id 错误或目录已清理）" }, null, 2)
    }
    const statusPath = path.join(jobDir, "status.json")
    if (!fs.existsSync(statusPath)) {
      // job 目录已建但 runner 进程刚起、还没来得及写 status.json → 视为启动中
      return JSON.stringify({ job_id: jobId, state: "running", note: "实验进程启动中，稍后在下个断点再查" }, null, 2)
    }
    let status: any = {}
    try {
      status = JSON.parse(fs.readFileSync(statusPath, "utf-8"))
    } catch {
      // status.json 正被原子写覆盖的极小窗口：视为 running
      return JSON.stringify({ job_id: jobId, state: "running", note: "状态刷新中，稍后再查" }, null, 2)
    }

    const state = status.state || "running"
    if (state === "done" || state === "failed" || state === "cancelled") {
      let result: any = {}
      try {
        result = JSON.parse(fs.readFileSync(path.join(jobDir, "result.json"), "utf-8"))
      } catch {
        /* result 还没落 / 读失败 */
      }
      return JSON.stringify(
        {
          job_id: jobId,
          state,
          returncode: result.returncode ?? status.returncode,
          timed_out: result.timed_out ?? status.timed_out ?? false,
          cancelled: state === "cancelled" || result.cancelled || false,
          metrics: result.metrics || {},
          stdout: headTail(result.stdout || ""),
          stderr: headTail(result.stderr || "", 500, 1500),
          elapsed_sec: result.elapsed_sec,
        },
        null,
        2,
      )
    }

    // running：给末尾日志，便于判断是否卡住
    let tail = ""
    try {
      const log = fs.readFileSync(path.join(jobDir, "runner.log"), "utf-8")
      tail = log.split("\n").slice(-15).join("\n")
    } catch {
      /* 还没有日志 */
    }
    return JSON.stringify({ job_id: jobId, state: "running", pid: status.pid, log_tail: tail }, null, 2)
  },
})

/* ───────────────────────────────────────────────────────────────
 * 能力 2c：取消异步实验 —— killpg 整个进程组，主动释放 GPU/CPU
 * ─────────────────────────────────────────────────────────────── */
export const cancel_experiment = tool({
  description: `停止一个 arc_run_experiment(is_async=true) 启动的后台实验，释放它占用的 GPU/CPU/内存。

背景：异步实验是 detached 进程，**不随 opencode（Ctrl+C 退出）一起结束**——这是为了"关了 TUI 长训练也不断"。
所以「不想要的后台实验」需要主动停。本工具读 job 的 status.json 拿 runner pid（detached → 它是进程组 leader），
**killpg 整个进程组**：runner + 真正跑实验的子进程 + 它派生的 DataLoader/multiprocessing worker 一并终止，
不留孤儿。随后把状态落成 cancelled（arc_experiment_status 可查）。

何时用：实验跑岔了 / 不再需要 / 要腾 GPU / 退出 opencode 前想清干净。
已 done/failed/cancelled 的 job 是无操作。`,
  args: {
    job_id: tool.schema.string().describe("要停止的后台实验 job_id"),
  },
  async execute(args) {
    const jobId = String(args.job_id || "")
    const jobDir = path.join(JOBS_ROOT, jobId)
    if (!fs.existsSync(jobDir)) {
      return JSON.stringify({ job_id: jobId, state: "unknown", error: "找不到该 job（job_id 错误或目录已清理）" }, null, 2)
    }
    const statusPath = path.join(jobDir, "status.json")
    let status: any = {}
    try {
      status = JSON.parse(fs.readFileSync(statusPath, "utf-8"))
    } catch {
      return JSON.stringify({ job_id: jobId, state: "unknown", error: "读不到 status.json（实验进程可能刚启动，稍后重试）" }, null, 2)
    }

    const state = status.state || "running"
    if (state === "done" || state === "failed" || state === "cancelled") {
      // 已是终态：无操作（幂等）
      return JSON.stringify({ job_id: jobId, state, note: "实验已结束，无需取消" }, null, 2)
    }

    const pid = Number(status.pid)
    if (!pid || Number.isNaN(pid)) {
      return JSON.stringify({ job_id: jobId, state, error: "status.json 无有效 pid，无法终止" }, null, 2)
    }

    // killpg：detached runner 的 pid == 进程组 leader，负号 pid 即对整个进程组发信号。
    // 先 SIGTERM 给清理机会，等一会儿仍存活再 SIGKILL；最后兜底单进程 kill。
    const signalGroup = (sig: NodeJS.Signals): boolean => {
      try {
        process.kill(-pid, sig) // 负 pid → killpg
        return true
      } catch (e: any) {
        if (e?.code === "ESRCH") return false // 进程组已不存在 = 已结束
        // EPERM 等：退回单进程 kill
        try {
          process.kill(pid, sig)
          return true
        } catch {
          return false
        }
      }
    }

    signalGroup("SIGTERM")
    await new Promise((res) => setTimeout(res, 1500))
    // 仍存活（kill(-pid,0) 不抛即在）→ 强杀
    let stillAlive = false
    try {
      process.kill(-pid, 0)
      stillAlive = true
    } catch {
      stillAlive = false
    }
    if (stillAlive) signalGroup("SIGKILL")

    // 原子落终态：让 arc_experiment_status / heartbeat 看到干净的 cancelled，
    // 不依赖被杀掉的 runner 自己收尾（它已无机会写 status）。
    const now = Date.now()
    const writeAtomic = (p: string, data: any) => {
      const tmp = p + ".tmp"
      fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf-8")
      fs.renameSync(tmp, p)
    }
    try {
      writeAtomic(statusPath, {
        state: "cancelled",
        pid,
        start: status.start,
        end: now / 1000,
        returncode: -1,
        cancelled: true,
      })
      // result.json 仅在 runner 还没写过终态时补一份，避免覆盖真实结果
      const resultPath = path.join(jobDir, "result.json")
      if (!fs.existsSync(resultPath)) {
        writeAtomic(resultPath, {
          returncode: -1,
          timed_out: false,
          cancelled: true,
          metrics: {},
          stdout: "",
          stderr: "experiment cancelled by user (arc_cancel_experiment)",
          elapsed_sec: status.start ? Math.round((now / 1000 - status.start) * 1000) / 1000 : null,
        })
      }
      // .done 哨兵：不存在才写（别覆盖 runner 自然完成的 returncode）
      const donePath = path.join(jobDir, ".done")
      if (!fs.existsSync(donePath)) fs.writeFileSync(donePath, "-1", "utf-8")
    } catch {
      /* 落盘失败不影响"已杀掉进程"这个既成事实 */
    }

    return JSON.stringify(
      {
        job_id: jobId,
        state: "cancelled",
        killed_pgid: pid,
        escalated_to_sigkill: stillAlive,
        note: "已终止该实验的整个进程组（runner + 实验子进程 + worker）。GPU/CPU 已释放。",
      },
      null,
      2,
    )
  },
})


export const verify_citation = tool({
  description: `核验一条引用是否真实存在（防 AI 编造引用）。

通过 arXiv ID / DOI / 标题在真实数据库（arXiv/CrossRef/DataCite/OpenAlex）
查证。用于论文定稿前确认所有引用真实。`,
  args: {
    title: tool.schema.string().describe("论文标题"),
    arxiv_id: tool.schema.string().describe("arXiv ID（可选）").default(""),
    doi: tool.schema.string().describe("DOI（可选）").default(""),
  },
  async execute(args) {
    // 可选参数缺失时 JSON.stringify(undefined) 会产出裸 "undefined"，必须兜底
    const title = String(args.title || "")
    const arxivId = String(args.arxiv_id || "")
    const doi = String(args.doi || "")
    const code = `
import json
from verify import verify_by_arxiv_id, verify_by_doi, verify_by_openalex
title = ${JSON.stringify(title)}
arxiv_id = ${JSON.stringify(arxivId)}
doi = ${JSON.stringify(doi)}
res = None
if arxiv_id:
    res = verify_by_arxiv_id(arxiv_id, title)
if res is None and doi:
    res = verify_by_doi(doi, title)
if res is None:
    res = verify_by_openalex(title)
if res is None:
    print(json.dumps({"verified": False, "reason": "未在任何数据库找到"}, ensure_ascii=False))
else:
    print(json.dumps({
        "verified": res.status.value if hasattr(res.status, "value") else str(res.status),
        "matched_title": getattr(res, "matched_title", ""),
        "source": getattr(res, "source", ""),
    }, ensure_ascii=False, indent=2))
`
    return runPython(code)
  },
})

/* ───────────────────────────────────────────────────────────────
 * 能力 4：批量引用核验 —— 核验整个 BibTeX，配合 guardrails hook 强制护栏
 * ─────────────────────────────────────────────────────────────── */
export const verify_paper = tool({
  description: `核验整篇论文的所有 BibTeX 引用是否真实存在（防 AI 编造引用）。

传入完整的 .bib 文本，逐条在 arXiv/CrossRef/OpenAlex 核实。
返回报告含 verified/suspicious/hallucinated 计数。
**论文定稿前必须调用**——guardrails hook 会在发现编造引用时强制警告。`,
  args: {
    bib_text: tool.schema.string().describe("完整 BibTeX 文本"),
  },
  async execute(args) {
    const bibText = String(args.bib_text || "")
    const code = `
import json
from verify import verify_citations
bib = ${JSON.stringify(bibText)}
# 测试/交互场景用短延迟，避免逐条 1.5s 太慢
report = verify_citations(bib, inter_verify_delay=0.3)
d = report.to_dict()
# to_dict 可能嵌在 summary 下，扁平化关键字段
summary = d.get("summary", d)
print(json.dumps({
    "total": summary.get("total", 0),
    "verified": summary.get("verified", 0),
    "suspicious": summary.get("suspicious", 0),
    "hallucinated": summary.get("hallucinated", 0),
    "skipped": summary.get("skipped", 0),
}, ensure_ascii=False, indent=2))
`
    return runPython(code, 360_000)
  },
})

/* ───────────────────────────────────────────────────────────────
 * 能力 5：抓被引文献摘要 —— 用于 claim 级引用审计（这条引用真支撑你的论点吗）
 * ─────────────────────────────────────────────────────────────── */
export const fetch_source = tool({
  description: `抓取被引文献的真实摘要，用于核验"这条引用是否真的支撑你论文里那句话"（claim 级 / faithfulness 审计）。

通过 title / arxiv_id / doi 在 OpenAlex/S2/arXiv 检索，返回最佳匹配论文的**摘要**。
配合 citation-faithfulness skill：你拿到摘要后自行判定 SUPPORTED / UNSUPPORTED / AMBIGUOUS。

与 arc_verify_citation 的区别：verify_citation 只验"这篇引用真实存在 + 标题相似"；
本工具进一步取回原文摘要，让你判断它**内容上**是否支持你的论点。
注意：只能拿到摘要（正文常付费墙），据此判定属 advisory（仅供参考），不能当硬证据。`,
  args: {
    title: tool.schema.string().describe("被引论文标题").default(""),
    arxiv_id: tool.schema.string().describe("arXiv ID（可选）").default(""),
    doi: tool.schema.string().describe("DOI（可选）").default(""),
  },
  async execute(args) {
    const title = String(args.title || "")
    const arxivId = String(args.arxiv_id || "")
    const doi = String(args.doi || "")
    const code = `
import json
from source_text import fetch_source
res = fetch_source(title=${JSON.stringify(title)}, arxiv_id=${JSON.stringify(arxivId)}, doi=${JSON.stringify(doi)})
print(json.dumps(res, ensure_ascii=False, indent=2))
`
    return runPython(code)
  },
})

export const fetch_latex_template = tool({
  description: `按目标 venue 取官方 LaTeX 类文件（.cls/.sty/.bst）到产物目录，让 paper.tex 在下游（Overleaf / 用户机器）能真编译。

配合 latex-fmt skill 在 Stage 22 导出时用：选定 venue 后，把对应模板文件放进 deliverables/，paper.tex 引用它们即可编译。
venue 是**枚举值**（不是任意 URL，只从官方源白名单下载）。可自动取：neurips、icml、ieee、kdd、sigir、eccv、acl/emnlp/coling。
带年份的（neurips/icml）**默认自动探测当前能下到的最新一年**（顶会每年发新模板，绝不用过时旧年）；只有复现某届旧版才传 year。无稳定自动源的（iclr/cvpr/aaai/interspeech/tmlr/nature/science）会返回出处与降级建议。
**取不到时不要硬凑**：用基础 article 类导出，并在报告/limitations 里如实标注未取到官方模板（呼应 quality-gate）。`,
  args: {
    venue: tool.schema.string().describe("目标会议/期刊，如 neurips/icml/ieee/acl/cvpr"),
    dest_dir: tool.schema.string().describe("落盘目录（须在工作目录内，如 research-runs/<topic>/deliverables）"),
    year: tool.schema.number().describe("带年份的源（neurips/icml）：0=自动取最新可用年份(推荐)；仅复现旧届才指定具体年份").default(0),
  },
  async execute(args) {
    const venue = String(args.venue || "")
    const destDir = String(args.dest_dir || "")
    const year = Number(args.year) || 0
    const code = `
import json
from latex_template import fetch
res = fetch(${JSON.stringify(venue)}, ${JSON.stringify(destDir)}, ${year || "None"})
print(json.dumps(res, ensure_ascii=False, indent=2))
`
    return runPython(code)
  },
})

export const render_figure = tool({
  description: `渲染一段 matplotlib 绘图代码到图片文件，并返回**图片路径 + 出版规范确定性体检**（图版核验门）。

这是科研绘图视觉反馈闭环的执行端，配合 scientific-visualization skill 使用：
1) 你写绘图代码（数据务必从 results.json 取真值，禁止硬编码）；
2) 调本工具渲染 → 拿到 image_path（png）+ lint 体检结果；
3) **必须用原生 read 工具真看那张 png**（不是看代码，是看图），按 rubric 自评清晰度/美观；
4) 有问题就改代码重渲染（≤3 轮），定稿确保矢量图（.pdf）进论文。

lint 确定性检查：DPI、画布宽是否匹配期刊栏、字号是否可读、是否用了被废弃的 jet/rainbow colormap、
坐标轴标签/单位、矢量导出等。severity=FAIL（如 jet colormap、字号不可读）会被图版核验门强制拦截。

与 arc_run_experiment 区别：那个是 sandbox 跑实验出 metrics；本工具是出图 + 图质量体检，不解析 metrics。
kind: data=统计数据图（全量体检）；schematic=概念/架构示意图（放宽，只查画布/DPI/导出）。`,
  args: {
    code: tool.schema.string().describe("matplotlib 绘图 Python 代码（自行 import；用 plt.subplots/figure 建图）"),
    out_path: tool.schema
      .string()
      .describe("图保存路径，建议 research-runs/<主题>/deliverables/figures/figN.pdf（矢量会另存同名 .png 供读图）"),
    kind: tool.schema
      .string()
      .describe('"data"=统计数据图 | "schematic"=概念/架构示意图')
      .default("data"),
    journal: tool.schema
      .string()
      .describe('"single"=单栏(3.3-3.5in) | "double"=双栏(6.5-7.1in)')
      .default("single"),
    results_path: tool.schema
      .string()
      .describe("results.json 路径（数据溯源用，可选）")
      .default(""),
  },
  async execute(args) {
    const userCode = String(args.code || "")
    const outPath = projectPath(args.out_path)
    const kind = String(args.kind || "data")
    const journal = String(args.journal || "single")
    const resultsPath = projectPath(args.results_path)
    const code = `
import json
from figure_lint import render_and_lint
res = render_and_lint(
    ${JSON.stringify(userCode)},
    ${JSON.stringify(outPath)},
    kind=${JSON.stringify(kind)},
    journal=${JSON.stringify(journal)},
    results_path=${JSON.stringify(resultsPath)},
)
print(json.dumps(res, ensure_ascii=False, indent=2))
`
    return runPython(code)
  },
})

export const generate_schematic = tool({
  description: `用生图模型（gpt-image-2）生成**架构图 / 方法概览图 / 概念示意图**，存盘并返回路径。

定位：架构图/概览图/示意图用代码（TikZ/matplotlib）很难画好看，改由生图模型出。配 scientific-visualization skill：
1) 先**通读论文方法段**（paper.md 的 Method + design.md），逐模块理解在做什么；
2) 自己**撰写详尽英文提示词**（列每个模块、模块间数据流/箭头、整体布局、克制的学术配色、clean flat schematic 风格）；
3) 调本工具出图；
4) **必须用原生 read 工具真看那张 png**，对照方法段**逐模块/逐连线核对有无幻觉结构**（画出论文里不存在的模块/错误连线）；有出入就改提示词重出（≤3 轮）。

⚠️ 红线：**只用于 schematic（架构/概览/流程/概念示意，无真实数据）**。统计**数据图（柱/线/散点等）绝不用本工具**——那必须用 arc_render_figure 走 matplotlib 从 results.json 画（生图模型会把数值编得像而错）。

网关：复用 opencode 启动配置的通用网关，用户无需额外配；缺凭证会如实报错（image_gen.py 会依次试
ANTHROPIC_BASE_URL/AUTH_TOKEN 环境变量、opencode 自身的 provider 配置/auth.json，两条都没找到才算真没配）。`,
  args: {
    prompt: tool.schema
      .string()
      .describe("详尽英文绘图描述：每个模块、模块间数据流/箭头、整体布局、配色方案、clean schematic 风格（你先读方法段后自己撰写）"),
    out_path: tool.schema
      .string()
      .describe("图保存路径，建议 research-runs/<主题>/deliverables/figures/arch.png"),
    size: tool.schema
      .string()
      .describe('尺寸，如 "1536x1024"(横版架构图) | "1024x1024" | "1024x1536"')
      .default("1536x1024"),
  },
  async execute(args) {
    const prompt = String(args.prompt || "")
    const outPath = projectPath(args.out_path)
    const size = String(args.size || "1536x1024")
    // prompt 走临时文件，避免命令行转义/超长。
    const tmp = path.join(os.tmpdir(), `arc_schematic_${process.pid}_${Date.now()}.txt`)
    fs.writeFileSync(tmp, prompt, "utf-8")
    try {
      const code = `
import json, sys
from image_gen import generate
res = generate(
    open(${JSON.stringify(tmp)}, encoding="utf-8").read(),
    ${JSON.stringify(outPath)},
    size=${JSON.stringify(size)},
)
print(json.dumps(res, ensure_ascii=False, indent=2))
`
      return runPython(code, 200_000)
    } finally {
      try { fs.unlinkSync(tmp) } catch {}
    }
  },
})

export const latex_check = tool({
  description: `本地真编一遍 paper.tex 并做**投稿前确定性体检**（编译核验门）。论文定稿/导出（Stage 22）后调它。

关键：**"编出 PDF / 退出码 0" ≠ 没问题**。LaTeX 的 Error 会中断（自己会报），但**很多 Warning 会"编过却坏"**——
所以本工具不看退出码，而是用 latexmk 真编（自动多趟 + bibtex/biber，悬空引用编两遍自然消解），再**解析 .log** 抓：
- **悬空 \\ref / \\cite**（正文会渲成 ??）→ FAIL
- **缺图 / 缺 \\input / 缺 .bib 文件** → FAIL
- **编译报错** → FAIL
- **overfull \\hbox**（文字戳出版心）/ underfull → WARN
- **页数 vs venue 上限**（传 venue 才查；LaTeX 给页数，上限是我们的规则；粗判不拆 refs/appendix）→ WARN

severity=FAIL 会被**编译核验门 hook 强制拦截**（满屏 ?? / 缺图 / 编不过的稿子不许导出）。
需本机有 TeX：没装会返回 severity=ERROR 并提示装 TinyTeX（wget yihui.org/tinytex 一行装，~300M）。
与 arc_fetch_latex_template 区别：那个是把官方 .cls/.sty 拉进产物目录；本工具是把 paper.tex 真编一遍验质量。`,
  args: {
    tex_path: tool.schema
      .string()
      .describe("主 .tex 文件路径（如 research-runs/<主题>/deliverables/paper.tex）"),
    venue: tool.schema
      .string()
      .describe("目标会议/期刊（页限核对用，可选；如 neurips/icml/cvpr/acl/kdd）")
      .default(""),
  },
  async execute(args) {
    const texPath = projectPath(args.tex_path)
    const venue = String(args.venue || "")
    const code = `
import json
from latex_check import check
res = check(${JSON.stringify(texPath)}, venue=${venue ? JSON.stringify(venue) : "None"})
print(json.dumps(res, ensure_ascii=False, indent=2))
`
    return runPython(code)
  },
})

/* ───────────────────────────────────────────────────────────────
 * 能力 12：通用网页搜索 —— 百度 AI 搜索（非学术论文）
 * 移植自独立的 baidu_search.ts（原为通用客服/助手场景写的），改成研究场景用：
 * - 跟 arc_search_literature 分工不重叠：学术论文/研究文献用 arc_search_literature（真调
 *   arXiv/Semantic Scholar/OpenAlex，有摘要/DOI/引用元数据，更权威）；本工具是通用网页搜索，
 *   覆盖论文库查不到的东西——工具/框架文档、会议官网、技术博客、报错排障之类。
 * - 原版有个 bug：TODAY 在模块顶层算（`const TODAY = new Date()...`），opencode 进程一起来
 *   就定死了，长时间跑着的进程日期会一直是启动那天（跟这次修的 taxonomy.png 路径 bug 同一类
 *   "一次性初始化值被当成永远新鲜"）。这里挪到 execute() 里每次现算。
 * ─────────────────────────────────────────────────────────────── */
const AI_SEARCH_DEFAULT_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
const AI_SEARCH_DEFAULT_COUNT = 10
const AI_SEARCH_MIN_COUNT = 1
const AI_SEARCH_MAX_COUNT = 50
const AI_SEARCH_TIMEOUT_MS = 30_000
const AI_SEARCH_MAX_OUTPUT_CHARS = 30_000
const AI_SEARCH_MAX_QUERY_CHARS = 72
const AI_SEARCH_FRESHNESS_PRESET = /^(pd|pw|pm|py)$/
const AI_SEARCH_FRESHNESS_RANGE = /^\d{4}-\d{2}-\d{2}to\d{4}-\d{2}-\d{2}$/

function charLen(s: string): number {
  let n = 0
  for (const ch of s) n += ch.charCodeAt(0) > 127 ? 2 : 1
  return n
}
function clampCount(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.floor(n)))
}
function buildFreshnessFilter(freshness?: string): { filter: object; error?: string } {
  if (!freshness) return { filter: {} }
  const today = new Date()
  const tomorrow = new Date(today.getTime() + 86_400_000).toISOString().slice(0, 10)
  if (AI_SEARCH_FRESHNESS_PRESET.test(freshness)) {
    const days = { pd: 1, pw: 7, pm: 30, py: 365 }[freshness as "pd" | "pw" | "pm" | "py"]!
    const start = new Date(today.getTime() - days * 86_400_000).toISOString().slice(0, 10)
    return { filter: { range: { page_time: { gte: start, lt: tomorrow } } } }
  }
  if (AI_SEARCH_FRESHNESS_RANGE.test(freshness)) {
    const [gte, lt] = freshness.split("to")
    return { filter: { range: { page_time: { gte, lt } } } }
  }
  return { filter: {}, error: "invalid freshness format" }
}
interface BaiduSearchResponse {
  references?: Array<{ title?: string; url?: string; snippet?: string; date?: string; website?: string }>
  code?: number | string
  message?: string
}
async function runBaiduWebSearch(
  query: string,
  count: number,
  freshness?: string,
): Promise<Array<{ title?: string; url?: string; snippet?: string; date?: string; website?: string }>> {
  const apiUrl = process.env.AI_SEARCH_URL?.trim() || AI_SEARCH_DEFAULT_URL
  const ABANDON = "本次搜索无法完成，请改用其他知识来源或换个角度回答。"
  const RETRY_LATER = "本次搜索请改用其他知识来源，稍后再试。"

  const apiKey = process.env.AI_SEARCH_KEY
  if (!apiKey) {
    throw new Error(`百度搜索鉴权未配置（环境变量 AI_SEARCH_KEY 未设置）。${ABANDON}`)
  }
  if (!query) throw new Error("query 为空。请传入具体的搜索关键词后重试。")
  if (charLen(query) > AI_SEARCH_MAX_QUERY_CHARS) {
    throw new Error(
      `query 太长（${charLen(query)} 字符，上限 ${AI_SEARCH_MAX_QUERY_CHARS}，中文算 2 字符）。请拆成多个更聚焦的关键词，分多次搜索。`,
    )
  }

  const filterResult = buildFreshnessFilter(freshness)
  if (filterResult.error) {
    throw new Error(
      `freshness 格式不合法（"${freshness}"）。合法值：pd / pw / pm / py，或 YYYY-MM-DDtoYYYY-MM-DD（例如 2026-01-01to2026-05-01）。请改用合法格式后重试。`,
    )
  }
  const body = {
    messages: [{ role: "user", content: query }],
    search_source: "baidu_search_v2",
    resource_type_filter: [{ type: "web", top_k: count }],
    search_filter: filterResult.filter,
  }

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), AI_SEARCH_TIMEOUT_MS)
  let resp: Response
  try {
    resp = await fetch(apiUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "X-Appbuilder-From": "opencode",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (e) {
    clearTimeout(timer)
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(`百度搜索超时（${AI_SEARCH_TIMEOUT_MS / 1000} 秒无响应）。${RETRY_LATER}`)
    }
    throw new Error(`百度搜索网络请求失败（${(e as Error).message}）。${ABANDON}`)
  }
  clearTimeout(timer)

  if (!resp.ok) {
    const rawBody = await resp.text().catch(() => "")
    const text = rawBody
      .replace(/Bearer\s+[\w\-.~+/]+=*/gi, "Bearer [REDACTED]")
      .replace(/("?Authorization"?\s*[:=]\s*")[^"]+/gi, '$1[REDACTED]')
      .slice(0, 300)
    const baseMsg =
      resp.status === 401 ? `百度搜索鉴权失败（HTTP 401）。${ABANDON}`
      : resp.status === 403 ? `百度搜索权限不足（HTTP 403）。${ABANDON}`
      : resp.status === 429 ? `百度搜索触发限流（HTTP 429）。${RETRY_LATER}`
      : resp.status >= 500 ? `百度搜索服务端故障（HTTP ${resp.status}）。${RETRY_LATER}`
      : `百度搜索 HTTP ${resp.status} ${resp.statusText}。${ABANDON}`
    throw new Error(text ? `${baseMsg}\n服务端返回：${text}` : baseMsg)
  }

  let data: BaiduSearchResponse
  try {
    data = (await resp.json()) as BaiduSearchResponse
  } catch (e) {
    throw new Error(`百度搜索响应格式异常（解析失败：${(e as Error).message}）。${ABANDON}`)
  }
  if (typeof data.code === "number" && data.code !== 0) {
    throw new Error(
      `百度搜索业务错误（code=${data.code}）：${data.message ?? "(无 message)"}。请根据业务信息判断：参数类问题可调整后重试；配额/权限类问题请改用其他知识来源。`,
    )
  }
  return data.references ?? []
}
function formatWebSearchResults(
  refs: Array<{ title?: string; url?: string; snippet?: string; website?: string; date?: string }>,
  query: string,
): string {
  const items: object[] = []
  for (let i = 0; i < refs.length; i++) {
    const r = refs[i]
    items.push({
      rank: i + 1,
      title: r.title?.trim() || "(no title)",
      url: r.url?.trim() || "",
      website: r.website?.trim() || undefined,
      date: r.date?.trim() || undefined,
      snippet: r.snippet?.trim() || "",
    })
  }
  const header = `网页搜索 "${query}" 命中 ${refs.length} 条结果。`
  const footer = "这是网页搜索结果，不是学术论文——引用具体事实时标注来源站点，不要当成 peer-review 文献直接进 references.bib。"
  const tryAll = `${header}\n\n${JSON.stringify(items, null, 2)}\n\n${footer}`
  if (tryAll.length <= AI_SEARCH_MAX_OUTPUT_CHARS) return tryAll
  const kept: object[] = []
  let cumulativeLen = header.length + footer.length + 50
  for (const item of items) {
    const itemLen = JSON.stringify(item, null, 2).length + 4
    if (cumulativeLen + itemLen > AI_SEARCH_MAX_OUTPUT_CHARS) break
    kept.push(item)
    cumulativeLen += itemLen
  }
  const dropped = items.length - kept.length
  const truncNote = dropped > 0 ? `\n\n(注：还有 ${dropped} 条因长度截断未展示，如需更多结果请精化 query 后重试。)` : ""
  return `${header}\n\n${JSON.stringify(kept, null, 2)}${truncNote}\n\n${footer}`
}

// 默认不注册这个工具：未设 AI_SEARCH_KEY 时导出 undefined。opencode 的工具发现（registry.ts
// isPluginTool）靠 `typeof value === "object"` 判断，undefined 直接被跳过、不会进 custom 工具
// 列表——agent 完全看不到这个工具的存在，不是"看到了但调用报错"。想启用只需设 AI_SEARCH_KEY；
// 不想两者语义强绑定（比如想先配好 key 但暂不启用）可以后续拆一个独立开关，目前按最简单处理。
// 用具名函数包一层而不是直接三元包住 tool({...})，避免整块内容跟着重新缩进、放大 diff。
function buildWebSearchTool() {
  return tool({
  description: `百度 AI 搜索——查实时网页信息（中英文支持），**不是**学术论文检索。

**跟 arc_search_literature 的分工**（别搞混）：
- 学术论文/研究文献 → 用 \`arc_search_literature\`（真调 arXiv/Semantic Scholar/OpenAlex，有摘要/DOI/
  引用元数据，能进 references.bib）。
- 除论文之外的、会随时间变化或论文库里查不到的信息 → 用本工具。

**典型科研场景**（不限于此）：
- 工具/框架/库的最新版本、API 变更、安装/兼容性问题（如某个 benchmark 仓库的最新 README、
  PyTorch/vLLM 新特性）
- 会议/期刊官网信息、CFP、投稿截止日期（\`arc_fetch_latex_template\` 取不到官方模板时，先搜官网链接）
- 复现某个方法时遇到的报错信息、依赖版本兼容性排障
- 公司/实验室的技术博客、产品发布（非 peer-review，但常是最新一手进展，比如大厂的模型发布博客）
- 数据集/开源代码仓库的获取方式、许可协议

**不用本工具**：
- 学术论文的检索/核验/摘要 → \`arc_search_literature\` / \`arc_verify_paper\` / \`arc_fetch_source\`
- 需要真跑代码验证的问题 → \`arc_run_experiment\`

query 写法：简洁关键词组合（≤72 字符，中文算 2），不写整句。`,
  args: {
    query: tool.schema.string().describe("搜索关键词。上限 72 字符（中文算 2）。最佳实践：简洁关键词组合，不写整句。"),
    count: tool.schema
      .number()
      .optional()
      .describe(`返回结果数 1-${AI_SEARCH_MAX_COUNT}，默认 ${AI_SEARCH_DEFAULT_COUNT}（快查用 5，深度调研用 20+）。`),
    freshness: tool.schema
      .string()
      .optional()
      .describe(
        "时间过滤，两种格式：\n" +
          "- 预设值：pd / pw / pm / py（过去 24h / 7d / 30d / 365d）\n" +
          "- 区间：YYYY-MM-DDtoYYYY-MM-DD\n" +
          "省略则不限时间。",
      ),
  },
  async execute(args) {
    const query = String(args.query || "").trim()
    const count = clampCount(args.count ?? AI_SEARCH_DEFAULT_COUNT, AI_SEARCH_MIN_COUNT, AI_SEARCH_MAX_COUNT)
    const refs = await runBaiduWebSearch(query, count, args.freshness)
    if (refs.length === 0) {
      return `网页搜索 "${query}" 无命中。建议：换用更通用的关键词、移除 freshness 过滤、或拆成多个子查询。`
    }
    return formatWebSearchResults(refs, query)
  },
  })
}
export const web_search = process.env.AI_SEARCH_KEY ? buildWebSearchTool() : undefined
