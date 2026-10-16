// Famou Scientist Loop read-only API.
//
// The Loop runtime is Python-owned and persists a deliberately boring file
// layout under .famou/loop/<goal_id>/.  This module only reads that layout.  It
// never changes research state, consumes a queue, runs an evaluator, or
// generates a report.  Keeping the API read-only is important: the web UI is
// a viewing surface, not another controller for the research loop.
import {
  readFile,
  readdir,
  realpath,
  stat,
} from "node:fs/promises"
import {
  extname,
  join,
  relative,
  resolve,
  sep,
} from "node:path"

const QUEUE_NAMES = ["ideaspark", "experiment_queue", "analyze_spark"]
const QUEUE_STATUSES = ["queued", "running", "finished", "failed", "archived"]
const DEFAULT_LIMIT = 100
const MAX_LIMIT = 500
const MAX_ARTIFACT_BYTES = 10 * 1024 * 1024

const TEXT_EXTENSIONS = new Set([
  ".c", ".cc", ".cpp", ".css", ".csv", ".diff", ".h", ".hpp", ".html",
  ".ini", ".ipynb", ".java", ".js", ".json", ".jsonl", ".jsx", ".jl",
  ".log", ".lua", ".m", ".md", ".mermaid", ".mjs", ".py", ".r", ".rb",
  ".rs", ".sass", ".scss", ".sh", ".sql", ".svg", ".tex", ".toml", ".ts",
  ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml", ".zsh",
])

function ok(body) {
  return { status: 200, body: { ok: true, ...body } }
}

function fail(status, error, extra = {}) {
  return { status, body: { ok: false, error, ...extra } }
}

function isInside(abs, root) {
  return abs === root || abs.startsWith(root + sep)
}

function projectRelative(projectRoot, abs) {
  const rel = relative(projectRoot, abs)
  return rel.split(sep).join("/")
}

function isSafeGoalId(value) {
  const id = String(value || "").trim()
  // Goal IDs are one path segment.  Dots are allowed because explicit goal
  // files may use them, but "." and ".." and separators are never allowed.
  return id !== "." && id !== ".." && /^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,119}$/.test(id)
}

function loopRoot(projectRoot) {
  return resolve(projectRoot, ".famou", "loop")
}

function boundedInt(value, fallback, max = MAX_LIMIT) {
  const parsed = Number.parseInt(String(value ?? ""), 10)
  if (!Number.isFinite(parsed) || parsed < 0) return fallback
  return Math.min(parsed, max)
}

function boolParam(value) {
  return ["1", "true", "yes", "on"].includes(String(value || "").toLowerCase())
}

function sortNewest(rows) {
  return [...rows].sort((a, b) => {
    const at = Number(a?.updated_at ?? a?.created_at ?? a?.ts ?? 0)
    const bt = Number(b?.updated_at ?? b?.created_at ?? b?.ts ?? 0)
    if (Number.isFinite(at) && Number.isFinite(bt) && at !== bt) return bt - at
    return String(b?.id || "").localeCompare(String(a?.id || ""))
  })
}

function page(rows, searchParams) {
  const offset = boundedInt(searchParams.get("offset"), 0, Number.MAX_SAFE_INTEGER)
  const limit = boundedInt(searchParams.get("limit"), DEFAULT_LIMIT)
  return {
    items: rows.slice(offset, offset + limit),
    total: rows.length,
    offset,
    limit,
  }
}

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"))
  } catch {
    return null
  }
}

async function readText(path) {
  try {
    return await readFile(path, "utf8")
  } catch {
    return null
  }
}

async function readJsonl(path, { source = "" } = {}) {
  let raw
  try {
    raw = await readFile(path, "utf8")
  } catch (error) {
    if (error?.code === "ENOENT") return { rows: [], invalid_lines: 0 }
    return { rows: [], invalid_lines: 0, read_error: error?.message || "read failed" }
  }
  const rows = []
  let invalidLines = 0
  for (const line of raw.split(/\r?\n/)) {
    const text = line.trim()
    if (!text) continue
    try {
      const value = JSON.parse(text)
      if (value && typeof value === "object" && !Array.isArray(value)) {
        rows.push(source ? { ...value, _source_file: source } : value)
      } else {
        invalidLines += 1
      }
    } catch {
      // JSONL is appended by a long-running loop.  A reader may observe the
      // final partial line while a writer is flushing; skip it rather than
      // making the whole dashboard unavailable.
      invalidLines += 1
    }
  }
  return { rows, invalid_lines: invalidLines }
}

async function readJsonFiles(dir, safetyRoot = dir) {
  let entries
  try {
    entries = await readdir(dir, { withFileTypes: true })
  } catch {
    return []
  }
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .sort((a, b) => a.name.localeCompare(b.name))
  const rows = []
  for (const entry of files) {
    const path = join(dir, entry.name)
    if (!(await existingPathInside(path, safetyRoot))) continue
    const value = await readJson(path)
    if (value && typeof value === "object" && !Array.isArray(value)) rows.push(value)
  }
  return rows
}

async function readWorkspace(projectRoot, goalId) {
  if (!isSafeGoalId(goalId)) return { response: fail(400, "invalid goal_id") }
  const root = loopRoot(projectRoot)
  const workspace = resolve(root, goalId)
  if (!isInside(workspace, root) || workspace === root) {
    return { response: fail(400, "invalid goal_id") }
  }
  try {
    const info = await stat(workspace)
    if (!info.isDirectory()) return { response: fail(404, "goal workspace not found") }
  } catch (error) {
    if (error?.code === "ENOENT") return { response: fail(404, "goal workspace not found") }
    return { response: fail(500, "cannot inspect goal workspace") }
  }
  // The workspace is normally a directory created by the Python runtime.
  // Reject a symlinked workspace (or a symlinked .famou/loop root) that would
  // make a syntactically safe goal_id resolve outside PROJECT_ROOT.
  try {
    const [realProjectRoot, realRoot, realWorkspace] = await Promise.all([
      realpath(resolve(projectRoot)),
      realpath(root),
      realpath(workspace),
    ])
    if (!isInside(realRoot, realProjectRoot) || !isInside(realWorkspace, realRoot)) {
      return { response: fail(403, "goal workspace is outside project root") }
    }
  } catch {
    return { response: fail(403, "goal workspace is forbidden") }
  }
  return { root, workspace, goalId }
}

async function existingPathInside(abs, root) {
  if (!isInside(abs, root) || abs === root) return false
  try {
    const [realRoot, realAbs] = await Promise.all([realpath(root), realpath(abs)])
    return isInside(realAbs, realRoot) && realAbs !== realRoot
  } catch {
    return false
  }
}

function emptyJsonl() {
  return { rows: [], invalid_lines: 0 }
}

async function safeReadJson(workspace, rel) {
  const path = resolve(workspace, rel)
  if (!(await existingPathInside(path, workspace))) return null
  return readJson(path)
}

async function safeReadText(workspace, rel) {
  const path = resolve(workspace, rel)
  if (!(await existingPathInside(path, workspace))) return null
  return readText(path)
}

async function safeReadJsonl(workspace, rel) {
  const path = resolve(workspace, rel)
  try {
    await stat(path)
  } catch (error) {
    if (error?.code === "ENOENT") return emptyJsonl()
    return { ...emptyJsonl(), read_error: error?.message || "read failed" }
  }
  if (!(await existingPathInside(path, workspace))) {
    return { ...emptyJsonl(), read_error: "path is forbidden" }
  }
  return readJsonl(path)
}

async function queueItems(workspace, queueName) {
  if (!QUEUE_NAMES.includes(queueName)) return []
  return sortNewest(await readJsonFiles(join(workspace, "queues", `${queueName}_items`), workspace))
}

function queueCounts(items) {
  const counts = Object.fromEntries(QUEUE_STATUSES.map((status) => [status, 0]))
  for (const item of items) {
    const status = String(item?.status || "")
    if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status] += 1
  }
  return { ...counts, total: items.length }
}

async function queueSummary(workspace) {
  const summary = {}
  for (const name of QUEUE_NAMES) {
    summary[name] = queueCounts(await queueItems(workspace, name))
  }
  return summary
}

function queueItemView(item, includePayload) {
  const out = { ...item }
  if (!includePayload) {
    delete out.payload
    if (item?.payload && typeof item.payload === "object" && !Array.isArray(item.payload)) {
      out.payload_keys = Object.keys(item.payload).slice(0, 100)
      out.payload_summary = {
        id: item.payload.id ?? null,
        title: item.payload.title ?? null,
        idea_id: item.payload.idea_id ?? null,
        branch_id: item.payload.branch_id ?? null,
        artifact: item.payload.artifact ?? null,
      }
    }
  }
  return out
}

async function artifactIndex(workspace) {
  return safeReadJsonl(workspace, "artifacts/artifact_index.jsonl")
}

async function decisionLog(workspace) {
  return safeReadJsonl(workspace, "artifacts/decision_log.jsonl")
}

async function clarificationLog(workspace) {
  return safeReadJsonl(workspace, "control/clarification_request.jsonl")
}

async function experienceRecords(workspace) {
  let entries
  try {
    entries = await readdir(join(workspace, "shared_experience_pool"), { withFileTypes: true })
  } catch {
    return { rows: [], invalid_lines: 0 }
  }
  const rows = []
  let invalidLines = 0
  for (const entry of entries.filter((x) => x.isFile() && x.name.endsWith(".jsonl")).sort((a, b) => a.name.localeCompare(b.name))) {
    const rel = join("shared_experience_pool", entry.name)
    const path = resolve(workspace, rel)
    if (!(await existingPathInside(path, workspace))) continue
    const result = await readJsonl(path, { source: entry.name })
    rows.push(...result.rows)
    invalidLines += result.invalid_lines || 0
  }
  return { rows, invalid_lines: invalidLines }
}

function addArtifactLinks(projectRoot, workspace, record) {
  const out = { ...record }
  const rel = typeof record?.path === "string" ? record.path : ""
  const abs = rel && !rel.startsWith("/") ? resolve(workspace, rel) : ""
  if (abs && isInside(abs, workspace) && abs !== workspace) {
    const projectRel = projectRelative(projectRoot, abs)
    out.raw_path = projectRel
    out.raw_url = `/raw?path=${encodeURIComponent(projectRel)}`
  }
  return out
}

async function findArtifact(projectRoot, workspace, artifactId) {
  if (!artifactId) return { response: fail(400, "missing artifact_id") }
  const index = await artifactIndex(workspace)
  const record = index.rows.find((item) => String(item?.id || "") === String(artifactId))
  if (!record) return { response: fail(404, "artifact not found") }
  const rel = typeof record.path === "string" ? record.path : ""
  if (!rel || rel.startsWith("/")) return { response: fail(403, "artifact path is forbidden") }
  const abs = resolve(workspace, rel)
  if (!(await existingPathInside(abs, workspace))) {
    return { response: fail(403, "artifact path is forbidden") }
  }
  return { record, abs, index }
}

function isTextArtifact(path) {
  return TEXT_EXTENSIONS.has(extname(path).toLowerCase())
}

async function artifactContent(projectRoot, workspace, record, abs) {
  const out = addArtifactLinks(projectRoot, workspace, record)
  let info
  try {
    info = await stat(abs)
  } catch {
    return { artifact: out, content: null, content_format: "missing", missing: true }
  }
  out.bytes = info.size
  if (info.size > MAX_ARTIFACT_BYTES) {
    return {
      artifact: out,
      content: null,
      content_format: "omitted",
      omitted_reason: "artifact_too_large",
      max_bytes: MAX_ARTIFACT_BYTES,
    }
  }
  if (!isTextArtifact(abs)) {
    return { artifact: out, content: null, content_format: "binary", omitted_reason: "binary_artifact" }
  }
  const text = await readText(abs)
  if (text == null) return { artifact: out, content: null, content_format: "missing", missing: true }
  if (extname(abs).toLowerCase() === ".json") {
    try {
      return { artifact: out, content: JSON.parse(text), content_format: "json" }
    } catch {
      // Keep malformed/partially-written JSON visible as text.
    }
  }
  return { artifact: out, content: text, content_format: "text" }
}

async function listGoals(projectRoot) {
  const root = loopRoot(projectRoot)
  let entries
  try {
    const [realProjectRoot, realRoot] = await Promise.all([
      realpath(resolve(projectRoot)),
      realpath(root),
    ])
    if (!isInside(realRoot, realProjectRoot)) return fail(403, "loop root is outside project root")
    entries = await readdir(root, { withFileTypes: true })
  } catch (error) {
    if (error?.code === "ENOENT") return ok({ root: ".famou/loop", goals: [] })
    return fail(500, "cannot list loop goals")
  }
  const goals = []
  for (const entry of entries.filter((x) => x.isDirectory()).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!isSafeGoalId(entry.name)) continue
    const workspace = resolve(root, entry.name)
    const state = await safeReadJson(workspace, "research_state.yaml")
    const rs = state?.research_state || {}
    const queues = await queueSummary(workspace)
    const index = await artifactIndex(workspace)
    const clarifications = await clarificationLog(workspace)
    let updatedAt = Number(rs.updated_at || 0)
    if (!updatedAt) {
      try { updatedAt = Math.round((await stat(workspace)).mtimeMs) } catch { updatedAt = 0 }
    }
    goals.push({
      goal_id: entry.name,
      status: rs.status || "unknown",
      name: rs.goal?.name || entry.name,
      domain: rs.goal?.domain || "",
      created_at: rs.created_at || null,
      updated_at: updatedAt || null,
      workspace: projectRelative(projectRoot, workspace),
      queues,
      artifact_count: index.rows.length,
      clarification_count: clarifications.rows.length,
    })
  }
  goals.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0))
  return ok({ root: ".famou/loop", goals })
}

async function getStatus(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const state = await safeReadJson(workspace, "research_state.yaml")
  if (!state || typeof state !== "object") return fail(404, "research_state not found")
  const clarifications = await clarificationLog(workspace)
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    research_state: state.research_state || {},
    queues: await queueSummary(workspace),
    clarification_summary: {
      total: clarifications.rows.length,
      open: clarifications.rows.filter((x) => String(x.status || "open") === "open").length,
    },
    audit: {
      invalid_clarification_lines: clarifications.invalid_lines || 0,
    },
  })
}

async function getQueues(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const includePayload = boolParam(searchParams.get("include_payload"))
  const queues = {}
  for (const name of QUEUE_NAMES) {
    const items = await queueItems(workspace, name)
    queues[name] = {
      counts: queueCounts(items),
      items: items.map((item) => queueItemView(item, includePayload)).slice(0, MAX_LIMIT),
      truncated: items.length > MAX_LIMIT,
    }
  }
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    summary: Object.fromEntries(Object.entries(queues).map(([name, value]) => [name, value.counts])),
    queues,
  })
}

async function getArtifacts(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const result = await artifactIndex(workspace)
  const type = String(searchParams.get("type") || "").trim()
  const records = sortNewest(result.rows)
    .filter((record) => !type || String(record.type || "") === type)
    .map((record) => addArtifactLinks(projectRoot, workspace, record))
  const resultPage = page(records, searchParams)
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    artifacts: resultPage.items,
    total: resultPage.total,
    offset: resultPage.offset,
    limit: resultPage.limit,
    invalid_lines: result.invalid_lines || 0,
  })
}

async function getArtifact(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const found = await findArtifact(projectRoot, workspace, searchParams.get("artifact_id"))
  if (found.response) return found.response
  const content = await artifactContent(projectRoot, workspace, found.record, found.abs)
  return ok({ goal_id: goalId, workspace: projectRelative(projectRoot, workspace), ...content })
}

async function getDecisions(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const result = await decisionLog(workspace)
  const rows = sortNewest(result.rows)
  const resultPage = page(rows, searchParams)
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    decisions: resultPage.items,
    total: resultPage.total,
    offset: resultPage.offset,
    limit: resultPage.limit,
    invalid_lines: result.invalid_lines || 0,
  })
}

async function getClarifications(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const result = await clarificationLog(workspace)
  const rows = sortNewest(result.rows)
  const resultPage = page(rows, searchParams)
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    clarifications: resultPage.items,
    total: resultPage.total,
    offset: resultPage.offset,
    limit: resultPage.limit,
    invalid_lines: result.invalid_lines || 0,
  })
}

async function getExperience(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const result = await experienceRecords(workspace)
  const type = String(searchParams.get("type") || "").trim()
  const query = String(searchParams.get("q") || "").trim().toLowerCase()
  const rows = sortNewest(result.rows).filter((row) => {
    if (type && String(row.type || "") !== type) return false
    if (!query) return true
    return JSON.stringify(row).toLowerCase().includes(query)
  })
  const resultPage = page(rows, searchParams)
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    records: resultPage.items,
    total: resultPage.total,
    offset: resultPage.offset,
    limit: resultPage.limit,
    invalid_lines: result.invalid_lines || 0,
  })
}

async function getReport(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const finalPath = resolve(workspace, "artifacts", "evidence_bundle", "final_report.md")
  const statusPath = resolve(workspace, "status_summary.md")
  const claimMapPath = resolve(workspace, "artifacts", "evidence_bundle", "claim_evidence_map.json")
  const manifestPath = resolve(workspace, "artifacts", "evidence_bundle", "manifest.json")
  const finalReport = await safeReadText(workspace, "artifacts/evidence_bundle/final_report.md")
  const statusSummary = await safeReadText(workspace, "status_summary.md")
  const claimMap = await safeReadJson(workspace, "artifacts/evidence_bundle/claim_evidence_map.json")
  const manifest = await safeReadJson(workspace, "artifacts/evidence_bundle/manifest.json")
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    available: Boolean(finalReport || statusSummary || claimMap || manifest),
    final_report: finalReport,
    status_summary: statusSummary,
    claim_evidence_map: claimMap,
    manifest,
    paths: {
      final_report: finalReport ? projectRelative(projectRoot, finalPath) : null,
      status_summary: statusSummary ? projectRelative(projectRoot, statusPath) : null,
    },
  })
}

async function getEvidenceBundle(projectRoot, searchParams) {
  const loaded = await readWorkspace(projectRoot, searchParams.get("goal_id"))
  if (loaded.response) return loaded.response
  const { workspace, goalId } = loaded
  const bundleDir = resolve(workspace, "artifacts", "evidence_bundle")
  let isDirectory = false
  if (await existingPathInside(bundleDir, workspace)) {
    try { isDirectory = (await stat(bundleDir)).isDirectory() } catch {}
  }
  if (!isDirectory) {
    return ok({
      goal_id: goalId,
      workspace: projectRelative(projectRoot, workspace),
      available: false,
      manifest: null,
      files: [],
      archive_url: null,
    })
  }
  const manifest = await safeReadJson(workspace, "artifacts/evidence_bundle/manifest.json")
  const files = Array.isArray(manifest?.files) ? manifest.files : []
  const bundleRel = projectRelative(projectRoot, bundleDir)
  return ok({
    goal_id: goalId,
    workspace: projectRelative(projectRoot, workspace),
    available: true,
    bundle_path: bundleRel,
    archive_url: `/archive?path=${encodeURIComponent(bundleRel)}`,
    manifest,
    files,
  })
}

// Return null when the URL does not belong to this API.  The server can then
// continue with its normal static-file routing.
export async function handleLoopRequest({ projectRoot, url, method = "GET" }) {
  const parsed = new URL(url || "/", "http://famou.local")
  const pathname = parsed.pathname.replace(/\/+$/, "") || "/"
  if (pathname !== "/loop" && !pathname.startsWith("/loop/")) return null
  if (method !== "GET") return fail(405, "method not allowed")

  if (pathname === "/loop" || pathname === "/loop/goals") return listGoals(resolve(projectRoot))
  if (pathname === "/loop/status") return getStatus(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/queues") return getQueues(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/artifacts") return getArtifacts(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/artifact") return getArtifact(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/decisions") return getDecisions(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/clarifications") return getClarifications(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/experience") return getExperience(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/report") return getReport(resolve(projectRoot), parsed.searchParams)
  if (pathname === "/loop/evidence-bundle") return getEvidenceBundle(resolve(projectRoot), parsed.searchParams)
  return fail(404, "unknown loop endpoint")
}
