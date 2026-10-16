// ARC 研究台 v2 — single-file React app (zero-build, transpiled in-browser by Babel).
// v2: multi-session (新研究/切换) + run-dir binding + 7-stage 产物轨迹右栏.
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import mermaid from "mermaid"

// Markdown 插件（模块级常量，避免每次渲染重建数组）。
// remark-math 解析 $...$ / $$...$$ 公式；rehype-katex 渲染。
// 关键：output:"mathml" → 让 KaTeX 只产 MathML，由浏览器原生渲染，**不依赖 KaTeX 的 CSS/字体文件**
// （本机锁网环境浏览器拉不到 CDN 字体，HTML 输出会变乱框；MathML 零资产、最稳）。
const MD_REMARK = [remarkGfm, remarkMath]
const MD_REHYPE = [[rehypeKatex, { output: "mathml", throwOnError: false }]]
let mermaidSeq = 0

// ===================================================================
// Icon —— 内联线性 SVG 图标（零依赖，替代彩色 emoji，风格统一 Lucide 式）。
// 用法 <Icon name="book" size={16} />；stroke 用 currentColor，随文字色走。
// ===================================================================
const ICON_PATHS = {
  // 导航 / 面板
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  briefcase: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  star: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  chevronLeft: '<path d="m15 18-6-6 6-6"/>',
  chevronsLeft: '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  // 视图 / 状态
  bolt: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  layers: '<path d="m12 2 9 5-9 5-9-5 9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  // 文件 / 产物
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9L9.6 3.9A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"/>',
  filetext: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
  table: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
  code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
  paperclip: '<path d="m21 8-9.2 9.2a3 3 0 0 1-4.2-4.2L15 5.6a2 2 0 0 1 2.8 2.8L9.4 16.6"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  expand: '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M16 21h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>',
  trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  splitRight: '<path d="M4 5h16M4 19h16M4 5v14M20 5v14M12 5v14"/><path d="M15 9l4 3-4 3"/>',
  splitDown: '<path d="M4 5h16M4 19h16M4 5v14M20 5v14M4 12h16"/><path d="M9 15l3 4 3-4"/>',
  panelClose: '<path d="M7 7l10 10M17 7 7 17"/>',
  // 工具 / 领域
  flask: '<path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3"/>',
  microscope: '<path d="M6 18h8M3 22h18M14 22a7 7 0 0 0 0-14M9 14h2M9 12a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2z"/>',
  chart: '<path d="M3 3v18h18"/><path d="M18 17V9M13 17V5M8 17v-3"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  bulb: '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.1v.2h6v-.2c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z"/>',
  brain: '<path d="M12 5a3 3 0 0 0-6 0 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 0zM12 5a3 3 0 0 1 6 0 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 0z"/>',
  bookopen: '<path d="M12 7v14M3 5h6a3 3 0 0 1 3 3M21 5h-6a3 3 0 0 0-3 3M3 5v13h6a3 3 0 0 1 3 3M21 5v13h-6a3 3 0 0 0-3 3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
  logo: '<path d="M4 20V4h9a4 4 0 0 1 0 8H4M13 12l7 8"/>',
  play: '<polygon points="6 4 20 12 6 20 6 4"/>',
  dot: '<circle cx="12" cy="12" r="4"/>',
}
function Icon({ name, size = 16, className, style }) {
  const d = ICON_PATHS[name] || ICON_PATHS.file
  return (
    <svg
      className={"icon" + (className ? " " + className : "")}
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      style={style} aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: d }}
    />
  )
}

// ===================================================================
// opencode client — bare fetch + EventSource against the /oc proxy
// ===================================================================
const OC = "/oc"
// 模型不写死：启动时从 /oc/config 读 opencode 自己配的默认模型（"provider/model" 串）。
// 取不到就置 null —— 发送时不带 model 字段，让 opencode 用它的默认。这样不依赖具体 provider 名。
let MODEL = null
let ACTIVE_SESSION_ID = ""

// 可切换模型：**不写死**，启动时从 opencode /config 的 provider.<id>.models 动态读
// （= 用户在 opencode 配置里声明了什么就展示什么）。取不到时退回这份兜底，保证仍可用。
const MODELS_FALLBACK = [
  { id: "anthropic-gateway/claude-opus-4-8", providerID: "anthropic-gateway", modelID: "claude-opus-4-8", label: "Claude Opus 4.8" },
  { id: "anthropic-gateway/claude-opus-4-6", providerID: "anthropic-gateway", modelID: "claude-opus-4-6", label: "Claude Opus 4.6" },
  { id: "anthropic-gateway/claude-sonnet-4-6", providerID: "anthropic-gateway", modelID: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  { id: "anthropic-gateway/glm-5.1", providerID: "anthropic-gateway", modelID: "glm-5.1", label: "GLM-5.1" },
  { id: "anthropic-gateway/glm-5.2", providerID: "anthropic-gateway", modelID: "glm-5.2", label: "GLM-5.2" },
]
const MODEL_LS_KEY = "famou.model" // localStorage 持久化选中项
// 哪些模型支持"看图"（视觉）。实测：claude-* 能用 read 读图并描述；glm-* 一遇图片就卡死。
// 上传图片但当前模型不在此列 → 前端提示用户换模型（不强制）。将来网关支持 glm 视觉了改这里即可。
const VISION_OK = /(^|\/)claude-/i

// ── 上传 / 快捷动作（豆包式「+」工具栏）────────────────────────────────────
// 上传入口统一支持的类型：跟服务端 /upload 的 UPLOAD_EXT 白名单对齐（那才是真正生效的边界，
// 这里只是浏览器文件选择框的 UI 过滤）；对话框和知识库共用同一份，避免两处各写一半、互不一致。
const ACCEPT = "image/*,application/pdf,.doc,.docx,.xlsx,.xls,.html,.htm,.txt,.md,.py,.csv,.json,.tex,.bib,.tsv,.yaml,.yml,.toml,.ipynb"
const MAX_FILE = 50 * 1024 * 1024 // 单文件 50MB（文档落盘不进 prompt，故放宽；超限跳过并提示）
// 快捷动作：点选后把提示词**预填进输入框**（不自动发），用户可编辑/补充后再发。
// 「图像生成」走预填→agent 自行调 arc_generate_schematic（示意图才用生图，数据图必须 matplotlib）。
const QUICK_ACTIONS = [
  { key: "img", icon: "image", label: "图像生成", text: "请生成一张示意图（架构/概念/流程，无真实数据），描述如下：" },
  { key: "lit", icon: "search", label: "检索文献", text: "搜一下关于 …… 的相关论文" },
  { key: "exp", icon: "flask", label: "设计实验", text: "针对 …… 帮我设计一个可执行的实验方案" },
  { key: "paper", icon: "edit", label: "写论文", text: "把目前 research-runs 里的研究整理成论文初稿" },
]
function fmtSize(n) {
  if (!n && n !== 0) return ""
  if (n < 1024) return n + "B"
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + "KB"
  return (n / 1024 / 1024).toFixed(1) + "MB"
}
function attIcon(mime, name) {
  if ((mime || "").startsWith("image/")) return "image"
  if ((mime || "").includes("pdf") || /\.pdf$/i.test(name || "")) return "filetext"
  if (/\.(csv|tsv|xlsx?)$/i.test(name || "")) return "table"
  if (/\.(py|ipynb|json|tex|bib|ya?ml|toml)$/i.test(name || "")) return "code"
  return "file"
}
// 读一批文件 → {id,name,relPath,mime,size,dataUrl,isImage}；超限的回到 rejected。
// 注意：文件夹上传时浏览器会给 webkitRelativePath，这里保留下来，上传落盘时按相对目录写入当前 session workspace。
function readFiles(fileList) {
  const files = Array.from(fileList || [])
  return Promise.all(
    files.map(
      (f) =>
        new Promise((resolve) => {
          if (f.size > MAX_FILE) { resolve({ rejected: f.webkitRelativePath || f.name }); return }
          const r = new FileReader()
          r.onload = () =>
            resolve({
              id: "att-" + Date.now() + "-" + Math.round(Math.random() * 1e6),
              name: f.name,
              relPath: f.webkitRelativePath || f.name,
              mime: f.type || "application/octet-stream", size: f.size,
              dataUrl: String(r.result || ""), isImage: (f.type || "").startsWith("image/"),
            })
          r.onerror = () => resolve({ rejected: f.webkitRelativePath || f.name })
          r.readAsDataURL(f)
        }),
    ),
  )
}
// 模块级模型列表：启动时被 resolveModel 用 /config 里的真实模型覆盖；组件从 App state 取，
// 而 modelLabelOf 这种模块级函数则查这里（保证标签也跟随动态列表）。
let MODEL_LIST = MODELS_FALLBACK
function modelLabelOf(id) {
  const m = MODEL_LIST.find((x) => x.id === id || x.modelID === id)
  return m ? m.label : id || "默认模型"
}

function parseModel(s) {
  if (!s || typeof s !== "string") return null
  const i = s.indexOf("/")
  if (i < 0) return null
  return { providerID: s.slice(0, i), modelID: s.slice(i + 1) }
}
function modelKey(providerID, modelID) {
  return providerID && modelID ? providerID + "/" + modelID : modelID || ""
}
function modelFromKey(key) {
  const parsed = parseModel(key)
  if (parsed) return parsed
  const m = MODEL_LIST.find((x) => x.modelID === key || x.id === key)
  if (m) return { providerID: m.providerID, modelID: m.modelID }
  return null
}
function canonicalModelKey(key) {
  const m = modelFromKey(key)
  return m ? modelKey(m.providerID, m.modelID) : key || ""
}
// 从 /config 的 provider.<id>.models 抽出模型列表。id 使用完整 provider/model，
// 避免不同 provider 下同名 model 被错误发到当前 provider。
// 汇总所有 provider 的模型（一般就一个 provider）。抽不到返回空数组。
function parseModelList(cfg) {
  const out = []
  const prov = (cfg && cfg.provider) || {}
  for (const pid of Object.keys(prov)) {
    const models = prov[pid] && prov[pid].models
    if (!models || typeof models !== "object") continue
    for (const mid of Object.keys(models)) {
      const label = (models[mid] && models[mid].name) || mid
      out.push({ id: modelKey(pid, mid), providerID: pid, modelID: mid, label })
    }
  }
  return out
}
async function resolveModel() {
  try {
    const r = await fetch(OC + "/config")
    if (r.ok) {
      const cfg = await r.json()
      const list = parseModelList(cfg)
      if (list.length) MODEL_LIST = list // 用 opencode 配置里的真实模型覆盖兜底列表
      const m = parseModel(cfg && cfg.model)
      if (m) MODEL = m
      return MODEL
    }
  } catch { /* 取不到就用默认（不带 model） */ }
  return MODEL
}

async function jsonOf(res) {
  if (!res.ok) throw new Error(res.status + " " + res.statusText + ": " + (await res.text()))
  return res.json()
}
async function createSession(title, famouWorkspace) {
  const body = { title: title || "新研究" }
  if (famouWorkspace) body.famouWorkspace = famouWorkspace
  const res = await fetch(OC + "/session", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
  return jsonOf(res)
}
async function listSessions() {
  // 列表直接来自后端持久化元数据，不在启动时逐个访问 OpenCode session：
  // 逐个访问会冷启动每个历史 cwd，导致页面长时间显示空列表并拖慢新会话。
  try {
    const stateRes = await fetch("/project-state")
    if (!stateRes.ok) return []
    const payload = await stateRes.json()
    const state = payload && payload.state ? payload.state : payload
    const assigned = (state && state.sessProj) || {}
    const titles = (state && state.sessionTitles) || {}
    const meta = (state && state.sessionMeta) || {}
    return Object.keys(assigned).map((sid) => {
      const item = meta[sid] && typeof meta[sid] === "object" ? meta[sid] : {}
      const createdAt = Number(item.createdAt) || 0
      const updatedAt = Number(item.updatedAt) || createdAt
      return {
        id: sid,
        title: titles[sid] || item.title || "新对话",
        directory: item.directory || "",
        createdAt,
        updatedAt,
        time: { created: createdAt, updated: updatedAt },
      }
    }).sort((a, b) => b.updatedAt - a.updatedAt)
  } catch { return [] }
}
async function refreshRegisteredSessions() {
  const [stateRes, sessionRes] = await Promise.all([fetch("/project-state"), fetch(OC + "/session")])
  if (!stateRes.ok || !sessionRes.ok) return []
  const statePayload = await stateRes.json()
  const state = statePayload && statePayload.state ? statePayload.state : statePayload
  const assigned = (state && state.sessProj) || {}
  const all = await jsonOf(sessionRes)
  return (Array.isArray(all) ? all : [])
    .filter((s) => s && assigned[s.id] && !((s.metadata && s.metadata.kind === "moonlog") || /^\[MoonLog\]/.test(String(s.title || ""))))
    .sort((a, b) => sessionTimeMs(b) - sessionTimeMs(a))
}
// MoonLog：GET /moonlog/list（可用日期列表，倒序）+ GET /moonlog/:date（某天的编译结果）。
async function listMoonlogDates() {
  const r = await fetch("/moonlog/list")
  if (!r.ok) return []
  const j = await r.json().catch(() => ({}))
  return j.dates || []
}
async function getMoonlog(date) {
  const r = await fetch("/moonlog/" + encodeURIComponent(date))
  if (!r.ok) return null
  return r.json().catch(() => null)
}
async function sendPrompt(sessionID, text, atts = []) {
  // parts：文本 +（可选）内联 file part。
  // 现状：onSend 已把所有附件（含图片）落盘后以路径文本发出，故正常不传 atts；
  // 保留 atts 形参作为内联通道（将来网关支持视觉时可切回图片内联）。
  const parts = []
  if (text && text.trim()) parts.push({ type: "text", text })
  for (const a of atts) parts.push({ type: "file", mime: a.mime, url: a.dataUrl, filename: a.name })
  const body = { parts }
  if (MODEL) body.model = MODEL // 没解析到默认模型时不带 model，让 opencode 用自身默认
  const res = await fetch(OC + "/session/" + sessionID + "/prompt_async", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok && res.status !== 204) throw new Error("prompt failed: " + res.status + " " + (await res.text()))
}

// 只识别整条纯文本消息中的 Slash Command。命令名不含开头的“/”，其余内容原样作为参数。
function parseSlashCommand(text) {
  const normalized = String(text || "").trim()
  const match = normalized.match(/^\/([A-Za-z0-9][A-Za-z0-9_-]*)(?:\s+([\s\S]*))?$/)
  if (!match) return null
  return { command: match[1], arguments: match[2] || "" }
}

// Slash Command 必须走 OpenCode 的 command API；若仍发给 prompt_async，只会被当作普通聊天文本。
async function sendCommand(sessionID, command, argumentsText = "") {
  const res = await fetch(OC + "/session/" + sessionID + "/command", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ command, arguments: argumentsText }),
  })
  if (!res.ok) throw new Error("command failed: " + res.status + " " + (await res.text()))
  return res.json().catch(() => null)
}

// OpenCode 的命令清单是唯一事实源：前端下拉菜单和历史消息还原都使用它，新增命令无需改 UI。
let COMMANDS_CACHE = []
let COMMANDS_PROMISE = null
async function listCommands() {
  if (COMMANDS_CACHE.length) return COMMANDS_CACHE
  if (!COMMANDS_PROMISE) {
    COMMANDS_PROMISE = fetch(OC + "/command")
      .then(jsonOf)
      .then((value) => {
        const list = Array.isArray(value) ? value : (value && Array.isArray(value.data) ? value.data : [])
        COMMANDS_CACHE = list.filter((item) => item && item.name).map((item) => ({
          name: String(item.name),
          description: String(item.description || ""),
          source: String(item.source || "command"),
          template: String(item.template || ""),
        }))
        return COMMANDS_CACHE
      })
      .catch((error) => {
        COMMANDS_PROMISE = null
        throw error
      })
  }
  return COMMANDS_PROMISE
}

// OpenCode 会把命令模板展开后作为 user message 持久化，却不保存原始“/命令 参数”。
// 实时执行时按 messageID 记账；刷新历史时优先使用该映射，避免把内部模板展示给用户。
function commandDisplayStorageKey(sessionID) { return "famou.commandDisplay." + sessionID }
function loadCommandDisplays(sessionID) {
  try {
    const raw = localStorage.getItem(commandDisplayStorageKey(sessionID))
    const value = raw ? JSON.parse(raw) : {}
    return value && typeof value === "object" ? value : {}
  } catch { return {} }
}
function rememberCommandDisplay(sessionID, messageID, displayText) {
  if (!sessionID || !messageID || !displayText) return
  try {
    const map = loadCommandDisplays(sessionID)
    map[messageID] = displayText
    const keys = Object.keys(map)
    for (const key of keys.slice(0, Math.max(0, keys.length - 200))) delete map[key]
    localStorage.setItem(commandDisplayStorageKey(sessionID), JSON.stringify(map))
  } catch { /* 隐私模式或存储已满时，仅影响刷新后的显示还原。 */ }
}

// 兼容映射建立前的历史消息：用命令模板前后缀反推出 $ARGUMENTS。
// 只接受单个 $ARGUMENTS 占位符且整段完全匹配，避免把普通用户消息误识别成命令。
function inferCommandDisplay(text, commands) {
  const body = String(text || "")
  for (const item of commands || []) {
    const template = String(item.template || "")
    const pieces = template.split("$ARGUMENTS")
    if (pieces.length === 1 && body === template) return "/" + item.name
    if (pieces.length !== 2 || !body.startsWith(pieces[0]) || !body.endsWith(pieces[1])) continue
    const end = pieces[1] ? body.length - pieces[1].length : body.length
    const argumentsText = body.slice(pieces[0].length, end).trim()
    return "/" + item.name + (argumentsText ? " " + argumentsText : "")
  }
  return ""
}
function inferAutomationDisplay(text) {
  const body = String(text || "").trim()
  if (
    body.startsWith("请编译论文并修复所有编译问题，直到通过") &&
    body.includes("arc_latex_check")
  ) return "请编译论文并修复所有编译问题，直到通过。"
  return ""
}
function decorateCommandMessages(sessionID, messages, commands = COMMANDS_CACHE) {
  const saved = loadCommandDisplays(sessionID)
  return (messages || []).map((message) => {
    if (!message || !message.info || message.info.role !== "user") return message
    const raw = (message.parts || []).filter((part) => part.type === "text").map((part) => part.text || "").join("")
    const displayText = saved[message.info.id] || inferCommandDisplay(raw, commands) || inferAutomationDisplay(raw)
    if (!displayText || message.info.displayText === displayText) return message
    return { ...message, info: { ...message.info, displayText } }
  })
}
// 上传文档落盘：把附件 base64 发给 server.mjs 的 /upload，直接写进当前 session workspace（agent cwd）。
// 返回相对 workspace 的路径，供 onSend 写进消息文本交给 agent 读。opencode 无原生上传 API，故走本机 server。
async function uploadFile(att, sessionID, directory = "") {
  const b64 = (att.dataUrl.split(",")[1]) || ""
  const r = await fetch("/upload", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sessionID: sessionID || "", directory: directory || "", name: att.name, relPath: att.relPath || att.name, mime: att.mime, dataB64: b64 }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("upload failed: " + r.status))
  return j.path // 相对当前 session workspace，如 agonevolve_openended.md 或 uploaded-dir/a.md
}
// 上传到全局「知识库」：走同一个 /upload 端点，dest=kb → 落 knowledge-base/[<分组>/]（跨会话共享，本轮仅存档不喂 agent）。
async function uploadKbFile(att, group) {
  const b64 = (att.dataUrl.split(",")[1]) || ""
  const r = await fetch("/upload", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ dest: "kb", kbGroup: group || "", name: att.name, mime: att.mime, dataB64: b64 }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("upload failed: " + r.status))
  return j.path // 如 knowledge-base/foo.pdf 或 knowledge-base/组名/foo.pdf
}
function abortErr() {
  return new DOMException("aborted", "AbortError")
}
function readFileDataUrl(file, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) { reject(abortErr()); return }
    const r = new FileReader()
    const cleanup = () => {
      if (signal) signal.removeEventListener("abort", onAbort)
    }
    const onAbort = () => {
      cleanup()
      try { r.abort() } catch {}
      reject(abortErr())
    }
    if (signal) signal.addEventListener("abort", onAbort, { once: true })
    r.onload = () => { cleanup(); resolve(String(r.result || "")) }
    r.onerror = () => { cleanup(); reject(new Error("read failed")) }
    r.onabort = () => { cleanup(); reject(abortErr()) }
    r.readAsDataURL(file)
  })
}
async function uploadProjectFile(projectId, entry, signal) {
  if (signal && signal.aborted) throw abortErr()
  const dataUrl = await readFileDataUrl(entry.file, signal)
  if (signal && signal.aborted) throw abortErr()
  const b64 = (dataUrl.split(",")[1]) || ""
  const r = await fetch("/upload", {
    method: "POST",
    headers: { "content-type": "application/json" },
    signal,
    body: JSON.stringify({
      dest: "project",
      projectId,
      relPath: entry.name,
      name: entry.name.split("/").pop(),
      mime: entry.mime || entry.file?.type || "application/octet-stream",
      dataB64: b64,
    }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("upload failed: " + r.status))
  return { name: entry.name, size: entry.size, path: j.path, bytes: j.bytes }
}
async function uploadProjectFiles(projectId, entries, { signal, onProgress } = {}) {
  const list = (entries || []).filter((x) => x && x.file && x.name)
  const results = []
  const total = list.length
  const concurrency = total > 24 ? 4 : total > 8 ? 3 : 2
  let next = 0
  let done = 0
  async function worker() {
    while (true) {
      if (signal && signal.aborted) throw abortErr()
      const i = next++
      if (i >= total) return
      const out = await uploadProjectFile(projectId, list[i], signal)
      results[i] = out
      done += 1
      if (onProgress) onProgress(done, total, list[i])
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, total || 1) }, () => worker()))
  return results.filter(Boolean)
}
// 删除知识库文档：POST /kb/delete（服务端仅允许删 knowledge-base/ 下）。
async function deleteKbFile(path) {
  const r = await fetch("/kb/delete", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("delete failed: " + r.status))
  return true
}
// 新建知识库分组：POST /kb/mkdir（单层目录，幂等——已存在不报错），供上传/收藏时"新建分组"用。
async function mkdirKbGroup(name) {
  const r = await fetch("/kb/mkdir", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("mkdir failed: " + r.status))
  return j.name
}
async function renameKbGroupApi(oldName, newName) {
  const r = await fetch("/kb/rename-group", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ oldName, newName }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("rename failed: " + r.status))
  return j.name
}
async function copyKbFileToProject(path, projectId) {
  const r = await fetch("/kb/copy-to-project", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, projectId }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("copy failed: " + r.status))
  return j
}
async function copyKbFileToSession(path, sessionID) {
  const r = await fetch("/kb/copy-to-session", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, sessionID }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("copy failed: " + r.status))
  return j
}
// 历史兼容：旧版本会把上传先放 _inbox/<会话ID>/，建 runDir 后再迁移到 <runDir>/uploads/。
// 新上传已直接落当前 session workspace，不再调用这条迁移路径。
// 返回 from→to 映射（相对路径），供前端更新它记的上传路径。
async function migrateUploads(sessionID, runDir) {
  const r = await fetch("/upload/migrate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sessionID: sessionID || "", runDir: runDir || "" }),
  })
  const j = await r.json().catch(() => ({}))
  if (!j.ok) throw new Error(j.error || ("migrate failed: " + r.status))
  return j.moved || [] // [{from, to}]
}
// 中断当前会话的生成（用户误发 / 输出跑偏时停掉）。opencode 端点：POST /session/:id/abort。
// 中断后服务端会结束本轮（随后多半发 session.idle / 消息定稿），前端再乐观清 busy。
async function abortSession(sessionID) {
  // 返回 abort 请求是否成功送达——onStop 据此决定何时主动 reconcile。
  try {
    const r = await fetch(OC + "/session/" + sessionID + "/abort", { method: "POST" })
    return r.ok
  } catch { return false }
}
async function getMessages(sessionID) {
  // 注意：真实端点是单数 /message（GET 列全部消息）；/messages 不存在会被 UI 拦成 HTML。
  const [messages, commands] = await Promise.all([
    jsonOf(await fetch(OC + "/session/" + sessionID + "/message")),
    listCommands().catch(() => COMMANDS_CACHE),
  ])
  return decorateCommandMessages(sessionID, messages, commands)
}
async function deleteMessage(sessionID, messageID) {
  const r = await fetch(
    OC + "/session/" + encodeURIComponent(sessionID) + "/message/" + encodeURIComponent(messageID),
    { method: "DELETE" },
  )
  if (!r.ok) throw new Error("删除消息失败：" + r.status + " " + (await r.text()))
  return true
}
// OpenCode 的会话状态是生成生命周期的权威来源。消息快照只能作为旧版本服务的兼容兜底，
// 不能用“最后一条 assistant 尚未 completed”推断一个回合仍在运行。
async function getSessionStatus(sessionID, directory = "") {
  if (!sessionID) return null
  try {
    const r = await fetch(withDirectory(OC + "/session/status", directory), {
      headers: { "x-famou-session-id": sessionID },
    })
    if (!r.ok) return null
    const body = await r.json().catch(() => null)
    const data = body && body.data && typeof body.data === "object" ? body.data : body
    const raw = data && data[sessionID]
    if (!raw) return null
    const value = typeof raw === "string" ? raw : raw.type || raw.status || raw.state
    const type = String(value || "").toLowerCase()
    if (["busy", "running", "retry", "waiting"].includes(type)) return { type, busy: true }
    if (["idle", "completed", "complete", "done", "error", "failed", "aborted", "cancelled"].includes(type)) {
      return { type, busy: false }
    }
  } catch { /* connection state is handled by SSE; do not mark a job failed here */ }
  return null
}
// 该会话「是否仍在生成中」——刷新页面/切会话后据此恢复"运行中"指示。
// 关键：opencode 在服务端跑生成（前端用 prompt_async 发完即走），所以刷新**不会**打断生成；
// 但 busy 只活在浏览器内存里，刷新后归零 → 误显示"已停"。判据：最后一条 assistant 消息没有
// time.completed = 仍在生成（已完成的 assistant 都带 completed 时间戳；见 opencode 消息结构）。
// 这个状态在服务端持久化，刷新后 GET /message 仍读得到，所以可靠地复原。session.idle 到达即清。
function isGenerating(msgs) {
  if (!Array.isArray(msgs) || !msgs.length) return false
  const last = msgs[msgs.length - 1]
  const info = (last && last.info) || last || {}
  // compact 后 opencode 注入的合成续推消息 role 是 user，但其后服务端马上会续推 assistant 回复。
  // 若 reconcile 恰在此过渡窗口拉到消息(末尾是它)，按 role!=="assistant" 会误判"已停"→ 误清 busy。
  // 把"末尾是合成续推消息"视为仍在生成，消除该误清。
  if (info.role === "user" && isCompactionContinue(last)) return true
  if (info.role !== "assistant") return false
  const t = info.time || {}
  if (t.created == null || t.completed != null) return false
  // 防历史 orphan running 永久卡住：
  // 如果 opencode/web 服务在工具调用中途重启，DB 里最后一条 assistant 可能永远没有 completed，
  // 最后一个 tool part 也停在 running。刷新/切会话时仅靠 completed=null 会把这种历史残留误判成
  // “模型还在思考”。超过 30 分钟无更新时间的 assistant 视为已中断，ProcessLog 会把 running tool
  // 标成“已中断”，不再让输入框/思考中永久锁死。
  const lastMs = toTimeMs(t.updated ?? info.updatedAt ?? info.updated ?? t.created) || Number(t.created)
  if (Number.isFinite(lastMs) && Date.now() - lastMs > 30 * 60 * 1000) return false
  return true
}
// 消息发送时间：opencode 把时间戳放在 info.time.created（毫秒）。格式化成「MM-DD HH:mm」本地时间。
// 拿不到（旧消息/流式中途）则返回空串 → RoleLine 不渲染时间胶囊。
function fmtMsgTime(info) {
  const ms = info && info.time && info.time.created
  if (ms == null) return ""
  try {
    const d = new Date(ms)
    const p = (n) => String(n).padStart(2, "0")
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  } catch {
    return ""
  }
}
function toTimeMs(v) {
  if (v == null) return 0
  if (typeof v === "number") return v > 1e12 ? v : v * 1000
  const n = Date.parse(String(v))
  return Number.isFinite(n) ? n : 0
}
function sessionTimeMs(s) {
  if (!s) return 0
  const t = s.time || {}
  return toTimeMs(s.updatedAt ?? s.updated ?? t.updated ?? t.completed ?? t.created ?? s.createdAt ?? s.created)
}
function relTime(ms) {
  if (!ms) return "未知时间"
  const diff = Math.max(0, Date.now() - ms)
  const min = Math.floor(diff / 60000)
  if (min < 1) return "刚刚"
  if (min < 60) return `${min}分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day}天前`
  const mon = Math.floor(day / 30)
  if (mon < 12) return `${mon}个月前`
  return `${Math.floor(mon / 12)}年前`
}

// 角色行：角色名（你/研究助手）+ 默认隐藏、悬停消息才显示的发送时间胶囊。
// 时间字体（等宽 var(--mono)）刻意与消息正文不同；灰色、椭圆胶囊内包裹（样式见 .msg-time）。
// side 决定时间相对角色名的方向：assistant 在左 → 时间放右侧；user 右对齐 → 时间放左侧。
// 隐藏态胶囊不占布局空间（max-width:0 折叠），故"你"平时仍贴最右，悬停才左移让出时间。
function RoleLine({ label, info, side = "left" }) {
  const ts = fmtMsgTime(info)
  const pill = ts ? <time className="msg-time">{ts}</time> : null
  return (
    <div className={"msg-role role-" + side}>
      {side === "right" ? pill : null}
      <span className="msg-role-name">{label}</span>
      {side === "left" ? pill : null}
    </div>
  )
}

async function deleteSession(sessionID) {
  const res = await fetch(OC + "/session/" + sessionID, { method: "DELETE" })
  if (!res.ok) throw new Error("delete failed: " + res.status)
}
function subscribeEvents(directory, onEvent, onReopen, onConnectionChange) {
  const es = new EventSource(OC + "/event" + (directory ? "?directory=" + encodeURIComponent(directory) : ""))
  let opened = false
  let hadError = false
  const emit = (ev) => {
    if (!ev || !ev.data) return
    try { onEvent(JSON.parse(ev.data)) } catch { /* ignore keepalives */ }
  }
  es.onopen = () => {
    // EventSource 会在断线后自动重连。重连期间服务端推的事件（含 session.idle / 文本增量）会**丢失**，
    // 导致 busy 卡死、回复补不回来。故重连成功后回调上层 reconcile，从服务端补齐最终状态。
    // 首次 open 不触发（启动流程已 reconcile 过）。
    if (onConnectionChange) onConnectionChange(true)
    if ((opened || hadError) && onReopen) { try { onReopen() } catch { /* ignore */ } }
    opened = true
    hadError = false
  }
  es.onmessage = emit
  const named = [
    "session.created", "session.updated", "session.deleted",
    "message.updated", "message.removed", "message.part.updated", "message.part.removed",
    "session.next.agent.switched", "session.next.model.switched", "session.next.moved",
    "session.next.prompted", "session.next.prompt.admitted", "session.next.prompt.promoted",
    "session.next.interrupt.requested", "session.next.context.updated", "session.next.synthetic",
    "session.next.shell.started", "session.next.shell.ended", "session.next.step.started",
    "session.next.step.ended", "session.next.step.failed",
    "session.next.text.started", "session.next.text.delta", "session.next.text.ended",
    "session.next.reasoning.started", "session.next.reasoning.delta", "session.next.reasoning.ended",
    "session.next.tool.input.started", "session.next.tool.input.delta", "session.next.tool.input.ended",
    "session.next.tool.called", "session.next.tool.progress", "session.next.tool.success", "session.next.tool.failed",
    "session.next.retried", "session.next.compaction.started", "session.next.compaction.delta", "session.next.compaction.ended",
    "message.part.delta", "session.diff", "session.error",
    "command.executed",
    "question.asked", "question.v2.asked", "question.replied", "question.v2.replied", "question.rejected", "question.v2.rejected",
    "permission.asked", "permission.v2.asked", "permission.replied", "permission.v2.replied",
    "session.idle", "session.status", "server.connected",
  ]
  const namedHandlers = []
  for (const name of named) {
    const h = (ev) => emit(ev)
    namedHandlers.push([name, h])
    es.addEventListener(name, h)
  }
  es.onerror = () => {
    hadError = true
    if (onConnectionChange) onConnectionChange(false)
  } // 浏览器自动重连；恢复后由 onopen→onReopen 补偿
  return () => {
    for (const [name, h] of namedHandlers) es.removeEventListener(name, h)
    es.close()
  }
}
async function listFiles(path) {
  // 网络失败、后端故障或目录不存在时抛出，让上层保留上一份有效列表。
  // 真实空目录由后端返回 200 []，不能把 404 误解释成空目录。
  if (String(path || "").startsWith("research-runs/") || String(path || "").startsWith("/")) {
    const sid = ACTIVE_SESSION_ID || ""
    const res = await fetch("/local-file?path=" + encodeURIComponent(path), sid ? { headers: { "x-famou-session-id": sid } } : undefined)
    if (res.status >= 500 || res.status === 404) {
      let detail = ""
      try { detail = JSON.stringify(await res.json()) } catch { try { detail = await res.text() } catch {} }
      throw new Error("backend " + res.status + (detail ? " · " + detail : ""))
    }
    if (!res.ok) return []
    return jsonOf(res)
  }
  const sid = ACTIVE_SESSION_ID || ""
  const res = await fetch(OC + "/file?path=" + encodeURIComponent(path), sid ? { headers: { "x-famou-session-id": sid } } : undefined)
  if (res.status >= 500) throw new Error("backend " + res.status)
  if (!res.ok) return []
  return jsonOf(res)
}
async function readFileContent(path) {
  if (String(path || "").startsWith("research-runs/") || String(path || "").startsWith("/")) {
    const sid = ACTIVE_SESSION_ID || ""
    const res = await fetch("/local-file/content?path=" + encodeURIComponent(path), sid ? { headers: { "x-famou-session-id": sid } } : undefined)
    if (!res.ok) return null
    return jsonOf(res)
  }
  const sid = ACTIVE_SESSION_ID || ""
  const res = await fetch(OC + "/file/content?path=" + encodeURIComponent(path), sid ? { headers: { "x-famou-session-id": sid } } : undefined)
  if (!res.ok) return null
  return jsonOf(res)
}

// ── 问询(question)交互：agent 调 opencode 内置 question 工具问你时，会发 question(.v2).asked
// 事件，且该工具调用一直挂在 running 直到我们回答（不答 → 界面卡"运行中"、问题抛不出来）。
// 下面是「答 / 拒 / 找回」三件套。OpenCode 1.18.x 的 question API 是全局路由；
// 即使 SSE 事件名带 question.v2.*，仍需 fallback 到 /question，并带 x-famou-session-id
// 让本地 proxy 绑定到当前 session workspace。
// body 都是 {answers}（每题一个数组、元素为所选 label，自定义答案就是用户输入的文本）。
function withDirectory(url, directory) {
  if (!directory) return url
  return url + (url.includes("?") ? "&" : "?") + "directory=" + encodeURIComponent(directory)
}
async function replyQuestion(version, sessionID, requestID, answers, directory = "") {
  const headers = sessionID
    ? { "content-type": "application/json", "x-famou-session-id": sessionID }
    : { "content-type": "application/json" }
  const body = JSON.stringify({ answers })
  async function post(url) {
    return fetch(url, {
      method: "POST",
      headers,
      body,
    })
  }

  // OpenCode 1.18.x exposes the question API globally at /question.
  // Some SSE events are named question.v2.*, but there is no stable
  // /api/session/:id/question route in this runtime. Try the event-specific
  // route first only for compatibility, then fall back to the global route.
  let res = null
  if (version === "v2") {
    res = await post(withDirectory(OC + "/api/session/" + sessionID + "/question/" + requestID + "/reply", directory)).catch(() => null)
    if (res && (res.ok || res.status === 204)) return
  }
  res = await post(withDirectory(OC + "/question/" + requestID + "/reply", directory))
  if (res.ok || res.status === 204) return
  const legacyText = await res.text().catch(() => "")
  res = await post(withDirectory(OC + "/api/question/" + requestID + "/reply", directory)).catch(() => null)
  if (res && (res.ok || res.status === 204)) return
  const apiText = res ? await res.text().catch(() => "") : ""
  throw new Error("reply failed: " + (res ? res.status : "network") + " " + (apiText || legacyText))
}
async function rejectQuestion(version, sessionID, requestID, directory = "") {
  const headers = sessionID ? { "x-famou-session-id": sessionID } : {}
  async function post(url) {
    return fetch(url, {
      method: "POST",
      headers,
    })
  }
  if (version === "v2") {
    const res = await post(withDirectory(OC + "/api/session/" + sessionID + "/question/" + requestID + "/reject", directory)).catch(() => null)
    if (res && (res.ok || res.status === 204)) return
  }
  const res = await post(withDirectory(OC + "/question/" + requestID + "/reject", directory)).catch(() => null)
  if (res && (res.ok || res.status === 204)) return
  await post(withDirectory(OC + "/api/question/" + requestID + "/reject", directory)).catch(() => {})
}
// 找回某会话当前挂起的问询(刷新页面/切会话后恢复)。注意返回形态不一：
// v2 会话维度是 {data:[...]} 信封，v1 全局是裸数组。
async function listPendingQuestions(sessionID, directory = "") {
  const arrOf = (j) => (Array.isArray(j) ? j : j && Array.isArray(j.data) ? j.data : [])
  const headers = sessionID ? { "x-famou-session-id": sessionID } : {}
  try {
    const r = await fetch(withDirectory(OC + "/api/session/" + sessionID + "/question", directory), { headers })
    if (r.ok) {
      const a = arrOf(await r.json())
      if (a.length) return a.map((q) => ({ ...q, version: "v2" }))
    }
  } catch { /* ignore */ }
  try {
    const r = await fetch(withDirectory(OC + "/question", directory), { headers })
    if (r.ok) {
      const a = arrOf(await r.json())
      const filtered = a.filter((q) => !q.sessionID || q.sessionID === sessionID).map((q) => ({ ...q, version: "v1" }))
      if (filtered.length) return filtered
    }
  } catch { /* ignore */ }
  try {
    const r = await fetch(withDirectory(OC + "/api/question", directory), { headers })
    if (r.ok) {
      const a = arrOf(await r.json())
      return a.filter((q) => !q.sessionID || q.sessionID === sessionID).map((q) => ({ ...q, version: "v2" }))
    }
  } catch { /* ignore */ }
  return []
}
// ── 权限请求(permission)交互：opencode 的 read/write/edit/bash 等工具碰到"项目目录之外的
// 路径"（external_directory）等敏感操作时会发 permission.asked 并**阻塞该工具调用**直到有人
// 回复——不回复就一直卡着，界面上此前什么提示都没有（问询 question 是同一种"服务端阻塞等回复"
// 模式的另一个实例，这里直接照抄它的处理方式）。回复三态：once(仅这次)/always(记住、按 patterns
// 里的 glob 放行同类)/reject(拒绝，可选 message 当反馈传给 agent)。
async function replyPermission(version, sessionID, requestID, reply, message, directory = "") {
  const headers = sessionID
    ? { "content-type": "application/json", "x-famou-session-id": sessionID }
    : { "content-type": "application/json" }
  const body = JSON.stringify(message ? { reply, message } : { reply })
  async function post(url) {
    return fetch(url, {
      method: "POST",
      headers,
      body,
    })
  }

  // OpenCode 新版本可能走 v2 permission：
  //   POST /api/session/:sessionID/permission/request/:requestID/reply
  // 旧版本走：
  //   POST /permission/:requestID/reply
  // 两条都必须带 directory / x-famou-session-id，否则会落到默认 instance，agent 仍在 session workspace
  // 里等权限，前端却回复到了另一个 instance。
  let res = null
  if (version === "v2") {
    res = await post(withDirectory(OC + "/api/session/" + sessionID + "/permission/request/" + requestID + "/reply", directory)).catch(() => null)
    if (res && (res.ok || res.status === 204)) return
  }
  res = await post(withDirectory(OC + "/permission/" + requestID + "/reply", directory))
  if (res.ok || res.status === 204) return
  const legacyText = await res.text().catch(() => "")
  res = await post(withDirectory(OC + "/api/session/" + sessionID + "/permission/request/" + requestID + "/reply", directory)).catch(() => null)
  if (res && (res.ok || res.status === 204)) return
  const v2Text = res ? await res.text().catch(() => "") : ""
  throw new Error("permission reply failed: " + (res ? res.status : "network") + " " + (v2Text || legacyText))
}
function normalizePermissionRequest(p, version, sessionID, directory = "") {
  const req = p || {}
  return {
    ...req,
    id: req.id,
    sessionID: req.sessionID || sessionID,
    version,
    directory,
    // v1: permission/patterns/always/tool；v2: action/resources/save/source
    permission: req.permission || req.action,
    patterns: req.patterns || req.resources || [],
    always: req.always || req.save || req.resources || [],
    tool: req.tool || (req.source && req.source.type),
  }
}
// 找回某会话当前挂起的权限请求(刷新页面/切会话后恢复)。实时 SSE 是主链路；这里用于 SSE 断线后补偿。
async function listPendingPermissions(sessionID, directory = "") {
  const arrOf = (j) => (Array.isArray(j) ? j : j && Array.isArray(j.data) ? j.data : [])
  const headers = sessionID ? { "x-famou-session-id": sessionID } : {}
  try {
    const r = await fetch(withDirectory(OC + "/permission", directory), { headers })
    if (r.ok) {
      const a = arrOf(await r.json())
      return a.filter((p) => !p.sessionID || p.sessionID === sessionID).map((p) => normalizePermissionRequest(p, "v1", sessionID, directory))
    }
  } catch { /* ignore */ }
  try {
    const r = await fetch(withDirectory(OC + "/api/session/" + sessionID + "/permission/request", directory), { headers })
    if (r.ok) {
      const a = arrOf(await r.json())
      return a.map((p) => normalizePermissionRequest(p, "v2", sessionID, directory))
    }
  } catch { /* ignore */ }
  return []
}

// 本地编译论文 .tex → PDF + 投稿前体检（走本服务的 /compile 端点，复用 latex_check.py 内核）。
// 返回 {ok, severity, pdf, pages, page_limit, checks, log_tail, error}。
async function compilePaper(relTex, venue) {
  const url = "/compile?path=" + encodeURIComponent(relTex) + (venue ? "&venue=" + encodeURIComponent(venue) : "")
  const r = await fetch(url)
  if (!r.ok) return { ok: false, severity: "ERROR", error: "compile http " + r.status }
  return r.json()
}

// ===================================================================
// run-dir 绑定：从会话的 write/edit 工具调用里抽 research-runs/<topic>/
// ===================================================================
// 上传记账：每个会话上传过的文件 [{path,name,mime}]（path 相对当前 session workspace）。
// 面板据此展示「📎 本次上传」，与 Workspace 根目录解耦。
function uploadsKey(sid) { return "famou.uploads." + sid }
function loadUploads(sid) {
  try { const s = sid ? localStorage.getItem(uploadsKey(sid)) : null; return s ? JSON.parse(s) : [] } catch { return [] }
}
function saveUploads(sid, list) {
  try { if (sid) localStorage.setItem(uploadsKey(sid), JSON.stringify(list || [])) } catch {}
}

// ── 文献收藏「资产库」：全局共享一份，存 localStorage，刷新/切会话/跨对话都在 ──
function paperKey(p) { return String((p && (p.doi || p.title)) || "").trim().toLowerCase() }
function litKey(p) { return String((p && (p.doi || p.arxiv_id || p.title)) || "").trim().toLowerCase() }
function loadStarred() {
  try { const s = localStorage.getItem("famou.starred"); const a = s ? JSON.parse(s) : []; return Array.isArray(a) ? a : [] } catch { return [] }
}
function saveStarred(list) {
  try { localStorage.setItem("famou.starred", JSON.stringify(list || [])) } catch {}
}

// ── 项目（Project）分组：后端 .famou/project-state.json 为权威，localStorage 只做缓存/旧数据迁移 ──
const UNARCHIVED = "__unarchived__"
function loadProjects() {
  try { const s = localStorage.getItem("famou.projects"); const a = s ? JSON.parse(s) : []; return Array.isArray(a) ? a : [] } catch { return [] }
}
function saveProjects(list) {
  try { localStorage.setItem("famou.projects", JSON.stringify(list || [])) } catch {}
}
function loadSessProj() {
  try { const s = localStorage.getItem("famou.sessProj"); const o = s ? JSON.parse(s) : {}; return o && typeof o === "object" ? o : {} } catch { return {} }
}
function saveSessProj(map) {
  try { localStorage.setItem("famou.sessProj", JSON.stringify(map || {})) } catch {}
}
function loadCurProj() {
  try { return localStorage.getItem("famou.curProj") || UNARCHIVED } catch { return UNARCHIVED }
}
function saveCurProj(pid) {
  try { localStorage.setItem("famou.curProj", pid || UNARCHIVED) } catch {}
}
function newProjectId() { return "p_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6) }
function projectNameKey(name) {
  const value = String(name || "").trim()
  try { return value.normalize("NFKC").toLowerCase() } catch { return value.toLowerCase() }
}
function projectNameExists(projects, name, excludeId = "") {
  const key = projectNameKey(name)
  return !!key && (projects || []).some((p) => p.id !== excludeId && projectNameKey(p.name) === key)
}
function loadPaperProj() {
  try { const s = localStorage.getItem("famou.paperProj"); const o = s ? JSON.parse(s) : {}; return o && typeof o === "object" ? o : {} } catch { return {} }
}
function savePaperProj(map) {
  try { localStorage.setItem("famou.paperProj", JSON.stringify(map || {})) } catch {}
}
function loadProjFiles() {
  try { const s = localStorage.getItem("famou.projFiles"); const o = s ? JSON.parse(s) : {}; return o && typeof o === "object" ? o : {} } catch { return {} }
}
function saveProjFiles(map) {
  try { localStorage.setItem("famou.projFiles", JSON.stringify(map || {})) } catch {}
}
function loadSessionTitles() {
  try { const s = localStorage.getItem("famou.sessionTitles"); const o = s ? JSON.parse(s) : {}; return o && typeof o === "object" ? o : {} } catch { return {} }
}
function saveSessionTitles(map) {
  try { localStorage.setItem("famou.sessionTitles", JSON.stringify(map || {})) } catch {}
}
function loadSessionMeta() {
  try { const s = localStorage.getItem("famou.sessionMeta"); const o = s ? JSON.parse(s) : {}; return o && typeof o === "object" ? o : {} } catch { return {} }
}
function saveSessionMeta(map) {
  try { localStorage.setItem("famou.sessionMeta", JSON.stringify(map || {})) } catch {}
}
function sessionMetaOf(s) {
  const createdAt = Number((s && s.time && s.time.created) || (s && s.createdAt)) || 0
  const updatedAt = Number((s && s.time && (s.time.updated || s.time.created)) || (s && s.updatedAt)) || createdAt
  return {
    id: String((s && s.id) || ""),
    title: String((s && s.title) || "新对话"),
    directory: String((s && s.directory) || ""),
    createdAt,
    updatedAt,
  }
}
function normalizeProjectState(raw) {
  const src = raw && typeof raw === "object" ? raw : {}
  const projects = Array.isArray(src.projects) ? src.projects.filter((p) => p && typeof p === "object") : []
  const sessProj = src.sessProj && typeof src.sessProj === "object" && !Array.isArray(src.sessProj) ? src.sessProj : {}
  const curProj = typeof src.curProj === "string" && src.curProj ? src.curProj : UNARCHIVED
  const projFiles = src.projFiles && typeof src.projFiles === "object" && !Array.isArray(src.projFiles) ? src.projFiles : {}
  const paperProj = src.paperProj && typeof src.paperProj === "object" && !Array.isArray(src.paperProj) ? src.paperProj : {}
  const sessionTitles = src.sessionTitles && typeof src.sessionTitles === "object" && !Array.isArray(src.sessionTitles) ? src.sessionTitles : {}
  const sessionMeta = src.sessionMeta && typeof src.sessionMeta === "object" && !Array.isArray(src.sessionMeta) ? src.sessionMeta : {}
  return { projects, sessProj, curProj, projFiles, paperProj, sessionTitles, sessionMeta }
}
async function loadProjectState() {
  try {
    const res = await fetch("/project-state")
    if (!res.ok) return null
    const j = await res.json().catch(() => null)
    return j && j.state ? normalizeProjectState(j.state) : null
  } catch {
    return null
  }
}
async function saveProjectState(state) {
  try {
    await fetch("/project-state", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ state: normalizeProjectState(state) }),
    })
  } catch { /* ignore */ }
}
// 「深入解读」指令：把论文（名字+链接）交给研究助手做**纯论文精读**（不牵扯当前课题）。
function deepDivePrompt(p) {
  const link = paperLink(p) || (p.arxiv_id ? "https://arxiv.org/abs/" + p.arxiv_id : "")
  const meta = []
  if (p.authors && p.authors.length) meta.push("作者：" + p.authors.slice(0, 8).join(", ") + (p.authors.length > 8 ? " 等" : ""))
  if (p.year) meta.push("年份：" + p.year)
  if (link) meta.push("链接：" + link)
  return (
    "请深入精读下面这篇论文，给我一份结构化的精读笔记。\n\n" +
    "论文标题：" + (p.title || "") + "\n" +
    (meta.length ? meta.join("\n") + "\n" : "") +
    "\n先用 arc_fetch_source / 联网把这篇论文的全文（或尽量完整的内容）取回来真读，" +
    "不要只凭标题或摘要臆测；若取不到全文，就基于摘要 + 你检索到的可靠信息作答，并注明信息来源与不确定处。\n\n" +
    "按以下结构输出：\n" +
    "1. 研究问题：要解决什么问题、动机与背景。\n" +
    "2. 核心方法：方法/模型/算法怎么做的，关键设计与创新点（讲清机制，别泛泛而谈）。\n" +
    "3. 实验设置：数据集、baseline、评价指标、关键超参与协议。\n" +
    "4. 主要结果：关键数字与结论，相对 baseline 的提升幅度。\n" +
    "5. 局限与可复现性：作者承认的局限、潜在风险、未报告项、是否开源/可复现。\n" +
    "6. 一句话总结：用一两句话概括这篇论文的贡献。\n\n" +
    "用中文回答。"
  )
}
// 深入解读指令很长，完整内容发给后端，但用户气泡里只显示一句自然的 query（看起来就像用户自己输入的）。
const DEEPDIVE_HEAD = "请深入精读下面这篇论文"
function deepDiveDisplay(txt) {
  if (!txt || txt.indexOf(DEEPDIVE_HEAD) !== 0) return null
  const m = txt.match(/论文标题：(.+)/)
  const title = m ? m[1].trim() : ""
  return title ? "解读一下这篇论文：《" + title + "》" : "解读一下这篇论文"
}

// ── 划词追问：选中 agent 回复里某段，针对它「解释一下 / 详细展开 / 深入研究」──
// 同 deepDive 套路：完整指令（含选中原文）发后端，气泡只显示精简 query。
const FOLLOWUP_HEAD = "【针对我选中的这段内容】"
const FOLLOWUP_KINDS = {
  explain: {
    label: "解释一下",
    title: "解释一下这段内容",
    instr:
      "请用通俗易懂的方式解释上面这段内容：它在说什么、关键概念是什么意思、" +
      "为什么是这样。把术语讲清楚，必要时举个简单例子。用中文。",
  },
  expand: {
    label: "详细展开",
    title: "详细展开这段内容",
    instr:
      "请把上面这段内容详细展开：补充背景、来龙去脉、每个要点的细节与彼此关系，" +
      "把略写或一笔带过的地方讲透。用中文，条理清晰。",
  },
  research: {
    label: "深入研究",
    title: "深入研究这段内容",
    instr:
      "请就上面这段内容做深入研究：它背后的原理/机制是什么、相关的代表性工作或方法有哪些、" +
      "有哪些不同观点或权衡、还有哪些未解问题或值得深挖的方向。" +
      "需要时用 arc_search_literature 检索真实文献佐证（不要编造）。用中文。",
  },
}
function followupPrompt(kind, selectedText, overrideInstr) {
  const k = FOLLOWUP_KINDS[kind]
  const quoted = String(selectedText || "").trim()
  // overrideInstr：用户在输入框把动作词改成了别的话 → 用用户的指令；否则用该动作的标准详尽指令。
  const instr = overrideInstr != null ? overrideInstr : (k ? k.instr : "")
  return FOLLOWUP_HEAD + "\n「" + quoted + "」\n\n" + instr
}
function followupDisplay(txt) {
  if (!txt || txt.indexOf(FOLLOWUP_HEAD) !== 0) return null
  // 提取选中原文（首个引号块），气泡显示「<指令> + 选中节选」
  const m = txt.match(/「([\s\S]*?)」/)
  let quoted = m ? m[1].trim() : ""
  if (quoted.length > 40) quoted = quoted.slice(0, 40) + "…"
  for (const kind of Object.keys(FOLLOWUP_KINDS)) {
    if (txt.indexOf(FOLLOWUP_KINDS[kind].instr) >= 0) {
      return FOLLOWUP_KINDS[kind].label + "：" + quoted
    }
  }
  return "追问：" + quoted
}

// 上传附件时，onSend 会把文件路径清单包在这段提示文本里发给后端（教 agent 用工具按路径读取），
// 但这段文本是"悄悄夹带给 agent 的指令"，从没打算给用户看——之前没做显示层剥离，
// 服务端回存的这条用户消息原样渲染出来，气泡里就会露出路径提示文本、图片也消失了
// （因为图早已落盘，消息里只有路径字符串，不含内联 file part）。
// 同 deepDive/followup 套路：剥出真实附带的文字（若有），图片改用落盘路径重新画缩略图。
const UPLOAD_NOTE_HEAD = "[用户上传了以下文件，已保存到工作目录，请直接用工具按给出的相对路径读取"
const UPLOAD_NOTE_LINE_RE = /^- (.+?) \(([^()]*)\)$/
function uploadNoteDisplay(txt) {
  if (!txt || txt.indexOf(UPLOAD_NOTE_HEAD) !== 0) return null
  const end = txt.indexOf("\n]")
  if (end < 0) return null
  const body = txt.slice(txt.indexOf(":\n") + 2, end)
  const files = body
    .split("\n")
    .map((line) => line.match(UPLOAD_NOTE_LINE_RE))
    .filter(Boolean)
    .map((m) => ({ path: m[1].trim(), mime: m[2].trim() }))
  const rest = txt.slice(end + 2).replace(/^\n+/, "")
  return { text: rest, files }
}

// ===================================================================
// 7 阶段定义(产物驱动,按子目录+文件名)
// ===================================================================
const STAGES = [
  { key: "lit", name: "文献综述", icon: "📚", dir: "planning", file: "literature.md" },
  { key: "hyp", name: "假设生成", icon: "💡", dir: "planning", file: "hypotheses.md" },
  { key: "design", name: "实验设计", icon: "🔬", dir: "planning", file: "design.md" },
  { key: "code", name: "实验代码", icon: "🐍", dir: "experiment", file: "experiment.py" },
  { key: "result", name: "结果分析", icon: "📊", dir: "experiment", file: "results.md", alt: ["results.json"] },
  // 下游成品阶段要求 experiment/results.json 存在才算"真完成"——否则是残留/越级(孤儿)。
  { key: "paper", name: "论文写作", icon: "📝", dir: "deliverables", file: "paper.md", altExt: ".tex", requires: { dir: "experiment", file: "results.json" } },
  { key: "cite", name: "引用核验", icon: "✅", dir: "deliverables", file: "citations.md", requires: { dir: "experiment", file: "results.json" } },
]
const STAGE_DIRS = ["planning", "experiment", "deliverables"]
// 判断某阶段是否完成(给定 {dir: [文件名]} 映射)
function stageDone(stage, filesByDir) {
  const files = filesByDir[stage.dir] || []
  if (files.includes(stage.file)) return stage.file
  if (stage.alt && stage.alt.some((a) => files.includes(a))) return stage.alt.find((a) => files.includes(a))
  if (stage.altExt) {
    const hit = files.find((f) => f.endsWith(stage.altExt))
    if (hit) return hit
  }
  return null
}
// 跨阶段前置是否满足（如"论文写作"要求 experiment/results.json 存在）。无 requires 视为满足。
function requiresMet(stage, filesByDir) {
  if (!stage.requires) return true
  return (filesByDir[stage.requires.dir] || []).includes(stage.requires.file)
}

// ===================================================================
// ToolCall card
// ===================================================================
function toolMeta(name, input) {
  switch (name) {
    case "arc_search_literature": return { icon: "book", label: "检索文献" }
    case "arc_run_experiment": return { icon: "flask", label: "运行实验" }
    case "arc_verify_citation": return { icon: "search", label: "核验引用" }
    case "arc_verify_paper": return { icon: "microscope", label: "核验论文引用" }
    case "skill": return { icon: "bookopen", label: "load skill: " + ((input && input.name) || "") }
    case "read": return { icon: "file", label: "读取文件" }
    case "write": return { icon: "edit", label: "写入文件" }
    case "edit": return { icon: "edit", label: "编辑文件" }
    case "bash": return { icon: "code", label: "执行命令" }
    case "list": case "glob": return { icon: "folder", label: "浏览目录" }
    case "grep": return { icon: "search", label: "搜索" }
    case "todowrite": case "todoread": return { icon: "check", label: "任务清单" }
    default: return { icon: "dot", label: name }
  }
}
const STATUS_LABEL = { pending: "待执行", running: "运行中", completed: "完成", error: "失败", interrupted: "已中断" }
// 显示层路径遮罩：用户不认识 research-runs/（那是磁盘上的真实产物根），他们眼里只有右侧的
// 「Workspace」。故**仅在渲染给用户看的文字里**把 research-runs/ 显示成 workspace/。
// 关键：这是纯展示替换，绝不改任何实际路径变量——/raw、/archive、fetch、下载等一律用真路径。
function maskPath(s) {
  if (s == null) return s
  return String(s).replace(/research-runs\//g, "workspace/")
}
function pretty(v) {
  if (v == null) return ""
  if (typeof v === "string") return maskPath(v)
  try { return maskPath(JSON.stringify(v, null, 2)) } catch { return maskPath(String(v)) }
}
function toolBodySummary(tool, output) {
  if (output == null) return null
  const text = typeof output === "string" ? output : pretty(output)
  if (tool === "skill") {
    const m = /<skill_content name="([^"]+)">/i.exec(text) || /<skill_content[^>]*name=([^\s>]+)/i.exec(text)
    return m ? `已加载 skill：${m[1]}` : "已加载 skill"
  }
  if (tool === "question") {
    return "question 工具已触发并等待/记录回答"
  }
  return text
}
function ToolCall({ part, onOpenImage, msgDone, isLast, chatMode }) {
  let status = (part.state && part.state.status) || "pending"
  // 父消息已定稿/已被后续消息取代/会话已不忙，但本工具仍停在 running/pending → 这是被中断的“孤儿”
  // 工具调用（服务端没补终态、或终态 SSE 在中断时丢了），按“已中断”渲染，绝不再无限转圈。
  // 例外：最后一条消息里的 question 工具是在“等用户回答”，属正常等待，不算中断。
  const isWaitingQuestion = isLast && part.tool === "question"
  const interrupted = msgDone && !isWaitingQuestion && (status === "running" || status === "pending")
  if (interrupted) status = "interrupted"
  const meta = toolMeta(part.tool, part.state && part.state.input)
  const [open, setOpen] = useState(status === "error")
  const [copied, setCopied] = useState("") // 复制反馈："已复制"/"复制失败"，短暂显示
  const input = part.state && part.state.input
  const output = (part.state && (part.state.output != null ? part.state.output : part.state.error))
  const imgPath = toolImagePath(part) // 生图/绘图工具产出的图片 → 对话流内嵌缩略图
  const summary = toolBodySummary(part.tool, output)
  async function doCopy() {
    const ok = await copyImageToClipboard(imgPath)
    setCopied(ok ? "已复制" : "复制失败")
    setTimeout(() => setCopied(""), 1600)
  }
  // 对话区模式：只嵌图，不显示工具卡片壳（head/输入输出体都归中间进程区）。
  if (chatMode) {
    if (!imgPath) return null
    return (
      <div className="tool-genimg chat-genimg">
        <div className="tool-genimg-frame" title="点击查看大图" onClick={() => onOpenImage && onOpenImage(imgPath)}>
          <img src={rawUrl(imgPath)} alt={imgPath.split("/").pop()} />
          <div className="tool-genimg-actions">
            <a className="genimg-btn" href={rawUrl(imgPath)} download title="下载" onClick={(e) => e.stopPropagation()}><Icon name="download" size={14} /></a>
            <button type="button" className="genimg-btn" title="复制图片" onClick={(e) => { e.stopPropagation(); doCopy() }}>⧉</button>
          </div>
        </div>
        <div className="tool-genimg-cap"><Icon name="image" size={13} /> {imgPath.split("/").pop()} · {copied || "点击放大"}</div>
      </div>
    )
  }
  return (
    <div className="tool">
      <div className="tool-head" onClick={() => setOpen((o) => !o)}>
        <span className="tool-icon"><Icon name={meta.icon} size={15} /></span>
        <span className="tool-name">{meta.label}</span>
        <span className={"tool-status " + status}>
          {status === "running" && <span className="spinner" style={{ marginRight: 6 }} />}
          {STATUS_LABEL[status] || status}
        </span>
      </div>
      {imgPath && (
        <div className="tool-genimg">
          <div className="tool-genimg-frame" title="点击查看大图" onClick={() => onOpenImage && onOpenImage(imgPath)}>
            <img src={rawUrl(imgPath)} alt={imgPath.split("/").pop()} />
            <div className="tool-genimg-actions">
              <a className="genimg-btn" href={rawUrl(imgPath)} download title="下载" onClick={(e) => e.stopPropagation()}><Icon name="download" size={14} /></a>
              <button type="button" className="genimg-btn" title="复制图片" onClick={(e) => { e.stopPropagation(); doCopy() }}>⧉</button>
            </div>
          </div>
          <div className="tool-genimg-cap"><Icon name="image" size={13} /> {imgPath.split("/").pop()} · {copied || "点击放大"}</div>
        </div>
      )}
      {open && (input != null || summary != null) && (
        <div className="tool-body">
          {input != null && Object.keys(input).length > 0 && (
            <><div className="label">输入</div><pre>{pretty(input)}</pre></>
          )}
          {summary != null && String(summary).length > 0 && (
            <><div className="label">{status === "error" ? "错误" : "输出"}</div><pre>{pretty(summary)}</pre></>
          )}
        </div>
      )}
    </div>
  )
}

// ===================================================================
// Assistant turn
// ===================================================================
function ReasoningBlock({ part }) {
  if (!part.text || !part.text.trim()) return null
  return (
    <details className="reasoning">
      <summary><Icon name="brain" /> 思考过程</summary>
      <div className="reasoning-body">{part.text}</div>
    </details>
  )
}
// 剥离泄漏的思维链标记。某些推理模型（如 GLM 系）用内联 <think>…</think> 输出思考，
// 经 Anthropic 协议适配器时未被正确识别/剥离，导致 </think> 及其包裹的思考漏进正文。
// 这是显示层兜底（不改存储）：底层修好后此函数自然空转。
function stripThink(s) {
  if (!s) return s
  // 1) 成对 <think>…</think>（含跨行）整对删，保留前后真正文。
  let out = s.replace(/<think>[\s\S]*?<\/think>/gi, "")
  // 2) 整段以孤立 </think> 开头 = 上一段溢出的思考尾巴 → 整段判为思考，丢弃。
  //    （真正面向用户的回复不会以 </think> 起头，故不会误伤。）
  if (/^\s*<\/think>/i.test(out)) return ""
  // 3) 残留未闭合 <think> 一直到结尾（流式中途的思考）→ 砍掉。
  out = out.replace(/<think>[\s\S]*$/i, "")
  // 4) 兜底：清掉任何零散残留的 think 标签。
  out = out.replace(/<\/?think>/gi, "")
  return out
}
function MermaidBlock({ source }) {
  const [mode, setMode] = useState("diagram")
  const [svg, setSvg] = useState("")
  const [err, setErr] = useState("")
  const idRef = useRef("")
  if (!idRef.current) idRef.current = "famou-mermaid-" + (++mermaidSeq)

  useEffect(() => {
    let alive = true
    const code = String(source || "").trim()
    if (!code) { setSvg(""); setErr(""); return () => { alive = false } }
    ;(async () => {
      try {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "default",
        })
        const out = await mermaid.render(idRef.current, code)
        if (!alive) return
        setSvg(out.svg || "")
        setErr("")
      } catch (e) {
        if (!alive) return
        setSvg("")
        setErr(e && e.message ? e.message : String(e))
        setMode("source")
      }
    })()
    return () => { alive = false }
  }, [source])

  return (
    <div className="mermaid-card">
      <div className="mermaid-head">
        <span className="mermaid-title"><Icon name="chart" /> Mermaid</span>
        <div className="mermaid-tabs">
          <button className={mode === "diagram" ? "active" : ""} onClick={() => setMode("diagram")} disabled={!svg}>渲染图</button>
          <button className={mode === "source" ? "active" : ""} onClick={() => setMode("source")}>源码</button>
        </div>
      </div>
      {mode === "diagram" && svg ? (
        <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <pre className="mermaid-source"><code>{source}</code></pre>
      )}
      {err ? <div className="mermaid-error">Mermaid 渲染失败，已显示源码：{err}</div> : null}
    </div>
  )
}
function MarkdownCode({ inline, className, children, ...props }) {
  const lang = /language-([^\s]+)/.exec(className || "")?.[1]?.toLowerCase() || ""
  const source = String(children || "").replace(/\n$/, "")
  if (!inline && (lang === "mermaid" || lang === "mmd")) return <MermaidBlock source={source} />
  return <code className={className} {...props}>{children}</code>
}
function MarkdownPre({ children, ...props }) {
  const only = Array.isArray(children) ? children[0] : children
  if (React.isValidElement(only) && only.type === MermaidBlock) return only
  return <pre {...props}>{children}</pre>
}
function cleanMarkdownHref(href) {
  const s = String(href || "")
  if (!/^https?:\/\//i.test(s)) return s
  return s.replace(/[|.,;:!?，。；：！？、)\]}]+$/g, "")
}
function MarkdownLink({ href, children, ...props }) {
  return <a href={cleanMarkdownHref(href)} target="_blank" rel="noreferrer" {...props}>{children}</a>
}
const MD_COMPONENTS = { code: MarkdownCode, pre: MarkdownPre, a: MarkdownLink }
function MarkdownView({ text, className }) {
  return (
    <div className={className}>
      <Markdown remarkPlugins={MD_REMARK} rehypePlugins={MD_REHYPE} components={MD_COMPONENTS}>{text}</Markdown>
    </div>
  )
}
// React.memo：只有 part 引用变化(即这段文本被追加了新增量)才重渲染。配合 appendDelta/upsertPart
// 「只克隆被改动的消息/part」，流式期间历史消息的 Markdown 不再被反复重解析 → 消除长对话卡顿。
const TextBlock = React.memo(function TextBlock({ part }) {
  if (!part.text || !part.text.trim()) return null
  const text = maskPath(stripThink(part.text)) // 显示层：research-runs/ → workspace/
  if (!text || !text.trim()) return null
  return <MarkdownView className="assistant-text" text={text} />
})
// 划词工具条：选中 agent 回复文本后浮现，复制 + 三个追问按钮。
// sel = { text, x, y } | null（x/y 为视口坐标，定位在选区上方居中）
function SelectionToolbar({ sel, onCopy, onFollowup }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => { setCopied(false) }, [sel && sel.text])
  if (!sel) return null
  async function doCopy() {
    try { await navigator.clipboard.writeText(sel.text); setCopied(true); setTimeout(() => setCopied(false), 1200) }
    catch { setCopied(false) }
    onCopy && onCopy()
  }
  // 夹在视口内，避免贴边溢出
  const left = Math.max(120, Math.min(sel.x, window.innerWidth - 120))
  const top = Math.max(8, sel.y - 8)
  return (
    <div className="sel-toolbar" style={{ left, top }} onMouseDown={(e) => e.preventDefault()}>
      <button className="sel-btn" onClick={doCopy}>{copied ? "✓ 已复制" : "复制"}</button>
      <span className="sel-sep" />
      <button className="sel-btn" onClick={() => onFollowup("explain")}>解释一下</button>
      <button className="sel-btn" onClick={() => onFollowup("expand")}>详细展开</button>
      <button className="sel-btn" onClick={() => onFollowup("research")}>深入研究</button>
    </div>
  )
}
// 从生图/绘图工具(arc_generate_schematic / arc_render_figure)的 output 里抽出生成的图片路径，
// 供对话流内嵌缩略图。output 是 JSON 字符串，含 image_path（绝对路径，/raw 能直接读）。
function toolImagePath(part) {
  if (part.type !== "tool") return ""
  if (part.tool !== "arc_generate_schematic" && part.tool !== "arc_render_figure") return ""
  const st = part.state || {}
  if (st.status !== "completed") return ""
  let out = st.output
  if (out == null) return ""
  try { if (typeof out === "string") out = JSON.parse(out) } catch { return "" }
  const p = out && (out.image_path || out.png_path || out.figure_path)
  return p && /\.(png|jpe?g|webp|gif)$/i.test(String(p)) ? String(p) : ""
}
// 一条 assistant 消息在对话区（chatMode）到底会不会渲染出任何东西：文字、已回答的问询回显、
// 生图缩略图——命中任一即算"有内容"，供 Turn 判断要不要整轮跳过渲染（避免留一堆空「研究助手」气泡）。
function turnHasVisibleContent(message) {
  for (const p of message.parts || []) {
    if (p.type === "text" && p.text && p.text.trim()) return true
    if (p.type === "tool") {
      if (p.tool === "question" && answeredQuestionEcho(p)) return true
      if (toolImagePath(p)) return true
    }
  }
  return false
}
function renderPart(part, onOpenImage, msgDone, isLast, chatMode) {
  switch (part.type) {
    // chatMode（左侧对话区）：只留 agent 文字 + 生图/绘图缩略图；读文件/执行命令/搜索等
    // 工具执行细节一律不在对话区展示（都挪到中间「进程」时间线）。思考过程也收起。
    case "reasoning": return chatMode ? null : <ReasoningBlock key={part.id} part={part} />
    case "tool":
      // question 工具：已回答（completed）→ 在对话区回显「你的选择」（否则回答后这段留白、
      // 上下文断裂）。答案就在 state.output 里（"User has answered..."="X"），刷新后仍在，持久可靠。
      if (chatMode && part.tool === "question") {
        const echo = answeredQuestionEcho(part)
        return echo ? <QuestionAnswerEcho key={part.id} items={echo} /> : null
      }
      // 唯一例外：生图/绘图工具产出的图片值得直接在对话里看到 → 保留缩略图（内部只渲染图，无卡片壳）。
      if (chatMode && !toolImagePath(part)) return null
      return <ToolCall key={part.id} part={part} onOpenImage={onOpenImage} msgDone={msgDone} isLast={isLast} chatMode={chatMode} />
    case "text": return <TextBlock key={part.id} part={part} />
    default: return null
  }
}
// 从 question 工具 part 里解析用户选择：优先使用结构化 metadata.answers，
// 旧版本再兼容解析 output 文本；没有可确认答案时返回 null。
function answeredQuestionEcho(part) {
  const st = part.state || {}
  const questions = (st.input && Array.isArray(st.input.questions)) ? st.input.questions : []
  const structured = st.metadata && Array.isArray(st.metadata.answers) ? st.metadata.answers : null
  // OpenCode 会把真实答案持久化在 metadata.answers。部分版本会漏掉 question 工具的
  // completed 终态，但 answers 已经存在；此时仍应回显，不能让用户刚提交的卡片直接消失。
  if (structured && structured.length) {
    const items = structured.map((answer, index) => {
      const values = Array.isArray(answer) ? answer : [answer]
      return {
        q: String((questions[index] && questions[index].question) || ""),
        a: values.map((value) => String(value || "").trim()).filter(Boolean),
      }
    }).filter((item) => item.a.length)
    if (items.length) return items
  }
  const out = typeof st.output === "string" ? st.output : ""
  if (!/answered your questions/i.test(out)) return null
  // 抓所有 "……"="……" 配对；同一问题的多选答案是相邻的多个 ="…"，用 header/question 归并。
  const re = /"([^"]*)"\s*=\s*"([^"]*)"/g
  const items = []
  let m
  let lastQ = null
  while ((m = re.exec(out)) !== null) {
    const q = m[1]
    const a = m[2]
    // 多选：opencode 会输出 "Q"="A1", "A2"——第二段起 key 其实是上一题的另一个答案，
    // 但这里 key 也是被引号包住的答案文本，无法可靠区分。稳妥起见：key 与上一条相同才归并，
    // 否则新起一题。（单选场景——绝大多数——完全正确。）
    if (lastQ && q === lastQ.q) lastQ.a.push(a)
    else { lastQ = { q, a: [a] }; items.push(lastQ) }
  }
  return items.length ? items : null
}

// question reply 接口确认成功后，SSE 的 completed part 仍可能晚到一拍。先在原工具 part 上
// 写入同结构的 metadata.answers，让问询卡无缝变成只读回显；后续服务端快照会用真实记录定稿。
function applyAnsweredQuestionSnapshot(messages, pending, answers) {
  const list = messages || []
  const pendingQuestions = (pending && pending.questions) || []
  const pendingTexts = pendingQuestions.map((q) => String((q && q.question) || ""))
  let target = null
  for (let mi = list.length - 1; mi >= 0 && !target; mi--) {
    const parts = list[mi].parts || []
    for (let pi = parts.length - 1; pi >= 0; pi--) {
      const part = parts[pi]
      if (!part || part.type !== "tool" || part.tool !== "question" || answeredQuestionEcho(part)) continue
      const partQuestions = (((part.state || {}).input || {}).questions || [])
      const partTexts = partQuestions.map((q) => String((q && q.question) || ""))
      const sameQuestions = pendingTexts.length > 0 && pendingTexts.length === partTexts.length
        && pendingTexts.every((text, index) => text === partTexts[index])
      const sameRequest = pending && [part.id, part.callID].includes(pending.requestID)
      if (sameRequest || sameQuestions || pendingTexts.length === 0) target = { mi, pi }
    }
  }
  if (!target) return list
  const message = list[target.mi]
  const parts = message.parts.slice()
  const part = parts[target.pi]
  const state = part.state || {}
  parts[target.pi] = {
    ...part,
    state: {
      ...state,
      status: "completed",
      output: state.output || "User has answered your questions.",
      metadata: { ...(state.metadata || {}), answers },
      time: { ...(state.time || {}), end: (state.time && state.time.end) || Date.now() },
    },
  }
  const next = list.slice()
  next[target.mi] = { ...message, parts }
  return next
}
// 对话区里回显「用户对 agent 问询的选择」，视觉上是一条轻量的「你」侧信息，替代已消失的问询卡片。
function QuestionAnswerEcho({ items }) {
  return (
    <div className="qecho">
      <div className="qecho-badge"><Icon name="check" size={13} /> 你的选择</div>
      {items.map((it, i) => (
        <div className="qecho-row" key={i}>
          {it.q ? <span className="qecho-q">{it.q}</span> : null}
          <span className="qecho-a">{it.a.join("、")}</span>
        </div>
      ))}
    </div>
  )
}
// 抽取本轮 assistant 消息产出的新产物：write/edit 写的文件 + render/schematic 出的图；去重、保序。
// 每项 {path, isImage}。仅在该轮完成(msgDone)后展示。
const _IMG_RE = /\.(png|jpe?g|gif|webp|bmp|svg)$/i
// 真·产物白名单：只有这些扩展名算"产物文件"。过滤掉 agent 写进 run 目录的过程性临时文件
// （问答选择、无后缀裸文件如 venue/plan/notes、隐藏/元数据文件），它们不是给用户看的产出。
const _ARTIFACT_EXT_RE = /\.(md|markdown|txt|tex|bib|pdf|py|ipynb|json|csv|tsv|yaml|yml|png|jpe?g|gif|webp|bmp|svg|html?)$/i
function isArtifactFile(rel) {
  const name = String(rel || "").split("/").pop()
  if (!name || name.startsWith(".")) return false // 隐藏/元数据文件不算产物
  return _ARTIFACT_EXT_RE.test(name)              // 必须有正经扩展名（裸 venue/plan 被排除）
}
// 收集一段"连续 assistant 消息"里产出的产物，跨消息去重（同一个文件被连续几条消息反复编辑，
// 只算一份产物，不按消息各出一张卡）。messages 为该段内的全部消息（见调用处 runMessages）。
function turnArtifacts(messages) {
  const out = []
  const seen = new Set()
  const add = (p, isImage) => {
    const path = String(p || "").trim()
    if (!path || seen.has(path)) return
    // 只收本次研究 run 目录下的产物（含相对路径），过滤临时/系统文件
    if (!/research-runs\//.test(path)) return
    const rel = path.slice(path.indexOf("research-runs/"))
    if (seen.has(rel)) return
    // 图片一律收（生图/绘图产物）；其余必须过产物白名单，滤掉过程性临时文件
    if (!isImage && !isArtifactFile(rel)) return
    seen.add(rel); seen.add(path)
    out.push({ path, displayPath: rel, isImage: isImage || _IMG_RE.test(rel) })
  }
  for (const message of messages) {
    for (const p of (message.parts || [])) {
      if (p.type !== "tool") continue
      const img = toolImagePath(p)
      if (img) { add(img, true); continue }
      if (p.tool === "write" || p.tool === "edit") {
        if (!p.state || p.state.status !== "completed") continue
        const inp = (p.state && p.state.input) || {}
        add(inp.filePath || inp.path || inp.file, false)
      }
    }
  }
  return out
}
// 文本产物卡片：拉前几行做预览图（截断，纯只读）。图片产物直接 <img>。点卡片 → 大屏。
function ArtifactCard({ art, onOpen }) {
  const [text, setText] = useState(null)
  const isImage = art.isImage
  const isMarkdown = /\.(md|markdown)$/i.test(art.displayPath || art.path)
  useEffect(() => {
    if (isImage) return
    let alive = true
    ;(async () => {
      try {
        const c = await readFileContent(art.path)
        const body = c && (c.content != null ? c.content : (typeof c === "string" ? c : ""))
        if (alive) setText(String(body || "").split("\n").slice(0, 12).join("\n"))
      } catch { if (alive) setText("") }
    })()
    return () => { alive = false }
  }, [art.path, isImage])
  const name = (art.displayPath || art.path).split("/").pop()
  return (
    <div className="artifact-card" title={"打开：" + name} onClick={() => onOpen(art.path)}>
      <div className={"artifact-preview" + (isMarkdown ? " markdown" : "")}>
        {isImage
          ? <img className="artifact-img" src={rawUrl(art.path)} alt={name} loading="lazy" />
          : text == null
          ? <div className="artifact-loading">加载中…</div>
          : isMarkdown
          ? <MarkdownView className="artifact-markdown" text={maskPath(text) || "（空文件）"} />
          : <pre className="artifact-text">{maskPath(text) || "（空文件）"}</pre>}
      </div>
      <div className="artifact-foot"><Icon name={fileIcon(name)} size={13} /> <span className="artifact-nm">{name}</span></div>
    </div>
  )
}
function TurnArtifacts({ arts, onOpen }) {
  if (!arts.length) return null
  return (
    <div className="turn-artifacts">
      <div className="turn-artifacts-head">本轮产物（{arts.length}）</div>
      <div className="artifact-grid">
        {arts.map((a) => <ArtifactCard key={a.path} art={a} onOpen={onOpen} />)}
      </div>
    </div>
  )
}

function assistantFailureText(info) {
  const error = info && info.error
  if (!error || error.name === "MessageAbortedError") return ""
  const raw = String((error.data && error.data.message) || error.message || error.name || "未知错误")
  if (/Range of input length should be \[1,\s*1048576\]/i.test(raw)) return ""
  if (/context[_ ]length|context window|prompt is too long/i.test(raw)) return "本轮未能启动：当前会话上下文超过模型限制，自动压缩未能完成。请新建会话继续。"
  const clean = raw.replace(/\s*\(request id:[^)]+\)\s*$/i, "").trim()
  return "本轮请求失败：" + clean
}

function AssistantRun({ messages, onOpenImage, onOpenFile, isLast, busy }) {
  const visible = (messages || []).filter((m) => !isCompactionSummary(m))
  if (!visible.length) return null
  const last = visible[visible.length - 1]
  const t = (last.info && last.info.time) || {}
  const runDone = t.completed != null || !isLast || !busy
  const runArts = turnArtifacts(visible)
  const aborted = visible.some((m) => m.info && m.info.error && m.info.error.name === "MessageAbortedError")
  const hasContent = visible.some((m) => turnHasVisibleContent(m))
  const hasFailureNotice = visible.some((m) => (m.parts || []).some((p) => p.type === "text" && String(p.text || "").includes("当前服务或模型调用异常")))
  const failures = visible.map((m) => assistantFailureText(m.info)).filter(Boolean)
  const failure = hasFailureNotice ? "" : failures[failures.length - 1] || ""
  if (runDone && !aborted && !failure && runArts.length === 0 && !hasContent) return null
  return (
    <div className="msg">
      <RoleLine label="研究助手" info={last.info} />
      <div className="turn">
        {visible.map((m, mi) => {
          const mt = (m.info && m.info.time) || {}
          const msgDone = mt.completed != null || m !== last || runDone
          return (
            <React.Fragment key={m.info.id}>
              {(m.parts || []).map((p) => renderPart(p, onOpenImage, msgDone, isLast && m === last, true))}
            </React.Fragment>
          )
        })}
      </div>
      {failure && (
        <div className="turn-error"><Icon name="x" size={13} /> {failure}</div>
      )}
      {aborted && !hasContent && runArts.length === 0 && (
        <div className="turn-aborted"><Icon name="x" size={13} /> 本轮已停止，未生成回复</div>
      )}
      {onOpenFile && <TurnArtifacts arts={runArts} onOpen={onOpenFile} />}
    </div>
  )
}

function Turn({ message, onOpenImage, onOpenFile, isLast, busy, runMessages }) {
  // 一条 assistant 消息里的工具是否算“被中断的孤儿”（不该再无限转圈）。三种情形：
  //   ① 本消息已定稿(time.completed 有值)——正常完成 / abort 中断；
  //   ② 它不是最后一条消息——后面已有更新消息，本轮早过去了，它的 running 必是被遗弃的僵尸；
  //   ③ 它是最后一条，但会话当前并不 busy（刷新后服务端已不在生成）——同样是僵尸。
  // 只有“最后一条 && 仍 busy”才是真正进行中，spinner 正常转。
  const t = (message.info && message.info.time) || {}
  const msgDone = t.completed != null || !isLast || !busy
  // opencode 对用户停止、看门狗终止等情况都使用 MessageAbortedError，并不携带终止来源。
  // 若这轮完全没有可见内容，补一条中性说明；已有正文或产物时不再追加误导性的终止尾巴。
  const aborted = !!(message.info && message.info.error && message.info.error.name === "MessageAbortedError")
  // runArts：只有段末消息（runMessages 非空）才汇总整段产物；段中其它消息这里恒为空——它们的
  // 产物已经并入段末那张网格，不在自己气泡下重复出现（见 turnArtifacts 注释）。
  const runArts = runMessages ? turnArtifacts(runMessages) : []
  // 纯 bash/read/todowrite 等工具调用、且没有文字/推理/产物可展示的一轮，光秃秃一个「研究助手」
  // 角色头没有意义，直接不渲染（进行中的不动它，留给后面可能出现的文字/产物）。注意：段中非段末
  // 的 edit/write 消息即便自己产出了产物，这里也不展示（留给段末汇总），故用 runArts 而非本消息
  // 自己的产物来判断——不然这类消息会被误判成"无内容"而漏渲染其应有的文字（若有）；若确实文字
  // 也没有，则跟"直接不渲染"的空轮次语义一致，无副作用。
  if (msgDone && !aborted && runArts.length === 0 && !turnHasVisibleContent(message)) return null
  return (
    <div className="msg">
      <RoleLine label="研究助手" info={message.info} />
      <div className="turn">{message.parts.map((p) => renderPart(p, onOpenImage, msgDone, isLast, true))}</div>
      {aborted && !turnHasVisibleContent(message) && runArts.length === 0 && (
        <div className="turn-aborted"><Icon name="x" size={13} /> 本轮已停止，未生成回复</div>
      )}
      {/* 本段（同一次指令触发的连续 assistant 消息）走完后，汇总这一整段产出的产物、只在段末这条
          消息上展示一次（跨消息去重，见 turnArtifacts 注释）。 */}
      {onOpenFile && <TurnArtifacts arts={runArts} onOpen={onOpenFile} />}
    </div>
  )
}

// ===================================================================
// QuestionCard：渲染 agent 的问询(单/多选 + 可选自定义)，回答经 /question reply 回传
// ===================================================================
function QuestionCard({ pending, onReply, onReject }) {
  const qs = (pending && pending.questions) || []
  // 每题各自的选择状态：sel[qi] = 已选 label 数组；customText[qi] = 自定义输入
  const [sel, setSel] = useState(() => qs.map(() => []))
  const [customText, setCustomText] = useState(() => qs.map(() => ""))
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState("")
  // pending 变了(新一轮问询)→ 重置本地状态
  useEffect(() => {
    setSel(qs.map(() => []))
    setCustomText(qs.map(() => ""))
    setSubmitting(false)
    setSubmitError("")
  }, [pending && pending.requestID]) // eslint-disable-line

  function toggle(qi, label, multiple) {
    setSel((prev) => {
      const next = prev.map((a) => a.slice())
      const cur = next[qi]
      if (multiple) {
        const i = cur.indexOf(label)
        if (i >= 0) cur.splice(i, 1)
        else cur.push(label)
      } else {
        next[qi] = cur[0] === label ? [] : [label]
      }
      return next
    })
  }
  function answersForSubmit() {
    return qs.map((q, qi) => {
      const arr = sel[qi].slice()
      const ct = (customText[qi] || "").trim()
      if (ct) arr.push(ct) // 自定义文本作为一个答案 label 追加
      return arr
    })
  }
  const answers = answersForSubmit()
  const ready = answers.every((a) => a.length > 0) // 每题至少一个答案
  async function submit() {
    if (!ready || submitting) return
    setSubmitting(true)
    setSubmitError("")
    try {
      await onReply(answers)
    } catch (e) {
      console.error(e)
      setSubmitError(e && e.message ? e.message : "提交失败，请稍后重试")
      setSubmitting(false)
    }
  }

  return (
    <div className="qcard">
      <div className="qcard-head">
        <span className="qcard-badge">需要你定夺</span>
        <span className="qcard-hint">选项里没有合适的？每题下方都能直接输入你的答案，填完点「提交回答」</span>
      </div>
      {qs.map((q, qi) => (
        <div className="qblock" key={qi}>
          {q.header ? <div className="qheader">{q.header}</div> : null}
          <div className="qtext">{q.question}</div>
          <div className="qopts">
            {(q.options || []).map((opt, oi) => {
              const active = sel[qi].includes(opt.label)
              return (
                <button
                  type="button"
                  key={oi}
                  className={"qopt " + (active ? "active " : "") + (q.multiple ? "multi" : "single")}
                  onClick={() => toggle(qi, opt.label, q.multiple)}
                  title={opt.description || ""}
                >
                  <span className="qopt-mark">{active ? (q.multiple ? "☑" : "●") : (q.multiple ? "☐" : "○")}</span>
                  <span className="qopt-text">
                    <span className="qopt-label">{opt.label}</span>
                    {opt.description ? <span className="qopt-desc">{opt.description}</span> : null}
                  </span>
                </button>
              )
            })}
          </div>
          {/* 每题都给一个自定义输入框：想选的不在选项里时，直接打字即可（不必勉强选一个） */}
          <textarea
            className="qcustom qcustom-textarea"
            placeholder="以上都不合适？在此输入你自己的答案…"
            value={customText[qi]}
            onChange={(e) => setCustomText((prev) => prev.map((v, i) => (i === qi ? e.target.value : v)))}
            onKeyDown={(e) => {
              if ((e.nativeEvent && e.nativeEvent.isComposing) || e.keyCode === 229) return
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit() }
            }}
          />
        </div>
      ))}
      <div className="qcard-foot">
        <button className="qsubmit" onClick={submit} disabled={!ready || submitting}>
          {submitting ? "提交中…" : "提交回答"}
        </button>
        <button className="qreject" onClick={onReject} disabled={submitting}>跳过</button>
      </div>
      {submitError ? <div className="qerror">{submitError}</div> : null}
    </div>
  )
}

// ===================================================================
// PermissionCard：渲染 opencode 的权限请求(permission.asked)——read/write/edit/bash 碰到项目
// 目录之外的路径(external_directory)等敏感操作时会阻塞等回复，这里补上界面（此前完全没处理，
// 会一直卡住看不出原因）。三态：本次允许(once) / 总是允许(always，按 patterns 记住) / 拒绝
// (reject，可选填一句理由回传给 agent)。
// ===================================================================
function permissionSummary(pending) {
  const meta = pending.metadata || {}
  if (pending.permission === "external_directory") {
    const path = meta.filepath || meta.parentDir || (pending.patterns || [])[0] || ""
    return "agent 想访问项目目录之外的路径：" + path
  }
  if (pending.version === "v2" && pending.permission) {
    const resources = (pending.patterns || []).join("、")
    return "agent 请求执行「" + pending.permission + "」" + (resources ? "，资源：" + resources : "") + "，需要你确认才能继续"
  }
  return "agent 请求执行「" + (pending.tool || pending.permission) + "」，需要你确认才能继续"
}

function PermissionCard({ pending, onReply }) {
  const [message, setMessage] = useState("")
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { setMessage(""); setSubmitting(false) }, [pending && pending.id])

  async function act(reply) {
    if (submitting) return
    setSubmitting(true)
    try { await onReply(reply, reply === "reject" ? message.trim() || undefined : undefined) }
    catch (e) { console.error(e); setSubmitting(false) }
  }

  return (
    <div className="pcard">
      <div className="pcard-head">
        <span className="pcard-badge">需要你批准</span>
        <span className="pcard-hint">agent 的操作触发了权限检查，回复前会一直等在这里</span>
      </div>
      <div className="pcard-body">{permissionSummary(pending)}</div>
      <input
        className="qcustom"
        type="text"
        placeholder="拒绝的话，可以在这里写一句理由（会传给 agent）…"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        disabled={submitting}
      />
      <div className="pcard-foot">
        <button className="p-approve" onClick={() => act("once")} disabled={submitting}>
          {submitting ? "处理中…" : "本次允许"}
        </button>
        <button
          className="p-approve-always"
          onClick={() => act("always")}
          disabled={submitting}
          title={"记住此类操作，以后不再问：" + (pending.always || pending.patterns || []).join("、")}
        >
          总是允许
        </button>
        <button className="p-deny" onClick={() => act("reject")} disabled={submitting}>拒绝</button>
      </div>
    </div>
  )
}

// ===================================================================
// Chat
// ===================================================================
function userText(m) {
  if (m && m.info && m.info.displayText) return String(m.info.displayText)
  return m.parts.filter((p) => p.type === "text").map((p) => p.text || "").join("")
}
// 用户消息里的附件(file part)：用于在「你」的气泡里回显所发的图/文件。
function userFiles(m) {
  return m.parts.filter((p) => p.type === "file")
}
// file part 是否有可直接 <img> 显示的图源（data URL / http(s)），且看着像图片。
function fileImgSrc(p) {
  const src = p.url || p.dataUrl || ""
  const looksImg = (p.mime || "").startsWith("image/") || /^data:image\//.test(src) || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(p.filename || "")
  return looksImg && /^(data:|https?:)/.test(src) ? src : ""
}

// 欢迎页：空会话时展示品牌 + 预制示例，点击直接发起研究。
const WELCOME_EXAMPLES = [
  "帮我复现这篇GNN风阻预测论文的方法，用DrivAer数据集验证",
  "调研强化学习在润滑油配方优化中的最新进展，给我一份综述",
  "PEM电解槽仿真数据的故障诊断方法对比，需要文献支撑",
]
function WelcomeScreen({ onPick }) {
  return (
    <div className="welcome">
      <h2 className="welcome-title">
        <span className="brand-baidu">百度</span><span className="brand-famou">伐谋</span>
      </h2>
      <p>描述你的研究需求，我陪你从文献、假设、实验一路做到论文。</p>
      <div className="welcome-examples">
        {WELCOME_EXAMPLES.map((t, i) => (
          <div className="example-btn" key={i} onClick={() => onPick(t)}>{t}</div>
        ))}
      </div>
    </div>
  )
}
// 实验心跳/进度等系统注入：以 [系统通知·…] 开头的是 famou 内部塞给模型的 user-role 提示，
// 不是真实用户消息。对话区不展示；右侧「进程」面板展示实验状态，并从 ↑/↓ 历史回放里过滤掉。
const HEARTBEAT_RE = /^\s*\[系统通知(?:[·:][^\]]*)?\]/
function isInternalSystemNote(text) {
  return HEARTBEAT_RE.test(String(text || ""))
}
// opencode 在 compact(上下文压缩)时会注入两种 role=user 的内部信号消息，都对用户无信息量、
// 且因 role=user 会冒充"你"的气泡：① 压缩发生时的标记消息（parts 里有一个 type: "compaction"
// 的 part，只记 auto/overflow/tail_start_id，没有文字、没有 synthetic/metadata 标记，渲染成
// 空气泡——这是最初漏检的那种）；② 压缩完后的续推提示文本"Continue if you have next steps…"
// （带 synthetic: true + metadata.compaction_continue: true）。三层识别：①③结构化标记，②文本兜底。
function isCompactionContinue(m) {
  if (!m || !m.info || m.info.role !== "user") return false
  const info = m.info
  if (info.synthetic === true || (info.metadata && info.metadata.compaction_continue)) return true
  const parts = m.parts || []
  if (parts.some((p) => p && (p.synthetic === true || (p.metadata && p.metadata.compaction_continue) || p.type === "compaction"))) return true
  return userText(m).includes("Continue if you have next steps")
}
// opencode 压缩上下文时还会让模型生成一条"## 目标/## 约束与偏好/## 进度"格式的回顾总结，
// 存成一条正常的 assistant 消息——但它不是在回答你刚说的话，是内部续推用的上下文重述，突然
// 出现在对话流里会让人以为出 bug 了（不知道背后发生了压缩）。用 info.summary===true /
// info.agent==="compaction" 精确识别（真实 agent 回复的 agent 字段是真正的 agent 名字，不会
// 撞上；不能靠"## 标题"这种文本形态判断，agent 平时正常回复也常用这种格式）。
function isCompactionSummary(m) {
  if (!m || !m.info) return false
  const info = m.info
  return info.summary === true || info.agent === "compaction" || info.mode === "compaction"
}
// 模型切换器：composer 下方的小按钮，点开向上弹出固定模型列表，选中即切换（持久化在 App 里）。
function ModelPicker({ value, models, onPick }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])
  return (
    <div className="model-picker" ref={ref}>
      {open && (
        <div className="model-menu">
          {models.map((m) => (
            <div
              key={m.id}
              className={"model-menu-item" + (m.id === value ? " active" : "")}
              onClick={() => { onPick(m.id); setOpen(false) }}
            >
              <span className="model-check">{m.id === value ? "✓" : ""}</span>
              {m.label}
            </div>
          ))}
        </div>
      )}
      <button type="button" className="model-picker-btn" onClick={() => setOpen((o) => !o)} title="切换模型（下一条消息生效）">
        <span className="model-dot" />
        {modelLabelOf(value)}
        <span className="model-caret">▾</span>
      </button>
    </div>
  )
}
function Chat({ messages, busy, runtimeStatus, onSend, onStop, onDeleteUserMessage, disabled, pendingQuestion, onReplyQuestion, onRejectQuestion, pendingPermission, onReplyPermission, modelID, onPickModel, models, showModelPicker, onOpenImage, focus }) {
  const [draft, setDraft] = useState("")
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deletingMessage, setDeletingMessage] = useState(false)
  const [deleteError, setDeleteError] = useState("")
  async function confirmDeleteMessage() {
    if (!deleteTarget || deletingMessage) return
    setDeletingMessage(true)
    setDeleteError("")
    try {
      await onDeleteUserMessage(deleteTarget.info.id)
      setDeleteTarget(null)
    } catch (error) {
      setDeleteError(String((error && error.message) || error || "删除失败"))
    } finally {
      setDeletingMessage(false)
    }
  }
  const [atts, setAtts] = useState([])      // 待发附件 [{id,name,mime,size,dataUrl,isImage}]
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef(null)              // 隐藏 file input
  const dirRef = useRef(null)               // 隐藏 directory input
  const inputRef = useRef(null)             // 底部输入框
  const scrollRef = useRef(null)
  const [commands, setCommands] = useState([])
  const [commandsLoaded, setCommandsLoaded] = useState(false)
  const [commandIndex, setCommandIndex] = useState(0)
  const [commandMenuDismissed, setCommandMenuDismissed] = useState(false)
  const commandMenuRef = useRef(null)
  useEffect(() => {
    let cancelled = false
    listCommands()
      .then((list) => { if (!cancelled) setCommands(list) })
      .catch(() => { /* 输入普通消息不应被命令清单加载失败阻断。 */ })
      .finally(() => { if (!cancelled) setCommandsLoaded(true) })
    return () => { cancelled = true }
  }, [])
  // 「黏底」跟随：仅当用户当前就在底部附近时，新内容才自动滚到底；一旦用户上滑去看历史，
  // 就暂停自动跟随（不再把他强行拽回 agent 正在输出的位置）。回到底部/自己发消息会重新黏底。
  const stickRef = useRef(true)
  function onScroll() {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 80
  }
  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages, busy, pendingQuestion])
  useLayoutEffect(() => {
    const ta = inputRef.current
    if (!ta) return
    const max = 260
    const min = 56
    ta.style.height = "auto"
    const next = Math.max(min, Math.min(ta.scrollHeight, max))
    ta.style.height = next + "px"
    ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden"
  }, [draft])
  // 一键到顶/到底：作用于聊天滚动容器，平滑滚动。到底 → 恢复黏底；到顶 → 明确离底、暂停跟随。
  function jumpTop() { stickRef.current = false; const el = scrollRef.current; if (el) el.scrollTo({ top: 0, behavior: "smooth" }) }
  function jumpBottom() { stickRef.current = true; const el = scrollRef.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }) }
  // ── 划词追问：仅当选区落在 agent 回复文本(.assistant-text)内时，浮现工具条 ──
  const [sel, setSel] = useState(null) // { text, x, y } | null
  function nodeInAssistant(node) {
    let el = node && (node.nodeType === 1 ? node : node.parentElement)
    while (el) { if (el.classList && el.classList.contains("assistant-text")) return true; el = el.parentElement }
    return false
  }
  function refreshSelection() {
    const s = window.getSelection && window.getSelection()
    if (!s || s.isCollapsed || s.rangeCount === 0) { setSel(null); return }
    const text = String(s.toString() || "").trim()
    if (text.length < 2) { setSel(null); return }
    // 选区两端都要在 agent 文本内（避免跨气泡/选到用户消息）
    if (!nodeInAssistant(s.anchorNode) || !nodeInAssistant(s.focusNode)) { setSel(null); return }
    const rect = s.getRangeAt(0).getBoundingClientRect()
    if (!rect || (!rect.width && !rect.height)) { setSel(null); return }
    setSel({ text, x: rect.left + rect.width / 2, y: rect.top })
  }
  useEffect(() => {
    function onUp() { setTimeout(refreshSelection, 0) }
    function onDown(e) { if (!e.target.closest || !e.target.closest(".sel-toolbar")) setSel(null) }
    document.addEventListener("mouseup", onUp)
    document.addEventListener("mousedown", onDown)
    return () => { document.removeEventListener("mouseup", onUp); document.removeEventListener("mousedown", onDown) }
  }, [])
  function sendFollowup(kind) {
    if (!sel) return
    const sText = sel.text
    setSel(null)
    try { const s = window.getSelection && window.getSelection(); s && s.removeAllRanges() } catch {}
    if (blocked) return
    // 豆包式：选中文本作为输入框上方的【只读引用卡片】（纯引用，不混进输入框）；
    // 动作词（解释一下/详细展开/深入研究）放进输入框当草稿，用户可改可补。
    // 发送时把「引用对应的完整指令 + 输入框文字」一起发给后端。
    setFollowupQuote({ text: sText, kind })
    setDraft(FOLLOWUP_KINDS[kind] ? FOLLOWUP_KINDS[kind].label : "追问")
    setHistIdx(null)
    requestAnimationFrame(() => {
      const ta = document.getElementById("composer-input")
      if (ta) { ta.focus(); try { const n = ta.value.length; ta.setSelectionRange(n, n) } catch {} }
    })
  }
  // 命令历史（像 cc / opencode CLI）：本会话已发送的用户消息，按时间序，方向键 ↑/↓ 回溯。
  // 排除心跳等系统注入——它们不是用户真打过的，不该被 ↑ 回放。
  const history = React.useMemo(
    () => messages.filter((m) => m.info.role === "user" && !isCompactionContinue(m)).map(userText).filter((t) => t.trim() && !isInternalSystemNote(t)),
    [messages],
  )
  const [histIdx, setHistIdx] = useState(null) // null=未在浏览历史；否则是 history 下标
  const stashRef = useRef("")                  // 进入历史浏览前正在编辑的草稿，浏览到底再还原
  const [followupQuote, setFollowupQuote] = useState(null) // 划词追问引用：{text, kind} | null（独立只读卡片）
  // 有待答问询时锁住输入框：避免用户绕过问询直接发下一轮(否则挂起的工具调用一直卡 running)
  const blocked = disabled || !!pendingQuestion
  // 仅在输入命令名阶段显示菜单；选中后补一个空格，菜单关闭，用户可继续填写目标或参数。
  const commandMatch = atts.length === 0 && !followupQuote ? draft.match(/^\/([^\s/]*)$/) : null
  const commandQuery = commandMatch ? commandMatch[1].toLowerCase() : ""
  const commandOptions = React.useMemo(() => {
    if (!commandMatch) return []
    return commands
      .filter((item) => item.name.toLowerCase().startsWith(commandQuery))
      .sort((a, b) => {
        if (a.name === "goal") return -1
        if (b.name === "goal") return 1
        if (a.source !== b.source) return a.source === "command" ? -1 : 1
        return a.name.localeCompare(b.name)
      })
  }, [commands, commandQuery, !!commandMatch])
  const commandMenuVisible = !!commandMatch && !commandMenuDismissed && !blocked
  useEffect(() => { setCommandIndex(0) }, [commandQuery, commands.length])
  // 键盘切换高亮项时同步滚动菜单，确保选中项始终可见；不用 scrollIntoView，避免带动页面滚动。
  useLayoutEffect(() => {
    const menu = commandMenuRef.current
    if (!commandMenuVisible || !menu) return
    const item = menu.querySelector(`[data-command-index="${commandIndex}"]`)
    if (!item) return
    const itemTop = item.offsetTop
    const itemBottom = itemTop + item.offsetHeight
    const visibleTop = menu.scrollTop
    const visibleBottom = visibleTop + menu.clientHeight
    if (itemTop < visibleTop) menu.scrollTop = Math.max(0, itemTop - 6)
    else if (itemBottom > visibleBottom) menu.scrollTop = itemBottom - menu.clientHeight + 6
  }, [commandIndex, commandMenuVisible, commandOptions.length])
  function chooseCommand(item) {
    if (!item) return
    setDraft("/" + item.name + " ")
    setCommandMenuDismissed(true)
    setHistIdx(null)
    requestAnimationFrame(() => {
      const ta = inputRef.current
      if (ta) { ta.focus(); caretEnd(ta) }
    })
  }
  // 读入一批文件 → 附件条；超 8MB 的跳过并提示。
  async function addFiles(fileList) {
    if (blocked) return
    const results = await readFiles(fileList)
    const ok = results.filter((r) => r && r.dataUrl)
    const bad = results.filter((r) => r && r.rejected).map((r) => r.rejected)
    if (ok.length) setAtts((prev) => prev.concat(ok))
    if (bad.length) alert("以下文件超过 8MB，已跳过：\n" + bad.join("\n"))
  }
  function removeAtt(id) { setAtts((prev) => prev.filter((a) => a.id !== id)) }
  // 快捷动作：把提示词预填进输入框（不自动发），focus + 光标置末尾。
  function applyQuick(a) {
    setDraft(a.text)
    setHistIdx(null)
    requestAnimationFrame(() => {
      const ta = document.getElementById("composer-input")
      if (ta) { ta.focus(); try { const n = ta.value.length; ta.setSelectionRange(n, n) } catch {} }
    })
  }
  function submit() {
    const t = draft.trim()
    if ((!t && atts.length === 0 && !followupQuote) || busy || blocked) return
    let toSend = t
    if (followupQuote) {
      const k = followupQuote.kind
      const defaultLabel = FOLLOWUP_KINDS[k] ? FOLLOWUP_KINDS[k].label : "追问"
      // 输入框文字 = 用户想要的指令。仍是默认动作词 → 用该动作的标准详尽指令；改过 → 用用户写的那句。
      // 完整指令(含整段选中原文)发后端，用户看不到细节指令。
      toSend = followupPrompt(k, followupQuote.text, t && t !== defaultLabel ? t : null)
    }
    onSend(toSend, atts)
    stickRef.current = true  // 自己发消息 → 重新黏底，跟随后续回复
    setDraft("")
    setAtts([])
    setFollowupQuote(null)
    setHistIdx(null)        // 发完退出历史浏览
    stashRef.current = ""
  }
  // 重置后把光标移到末尾（等 React 写完 DOM 再设）
  function caretEnd(ta) {
    requestAnimationFrame(() => { try { const n = ta.value.length; ta.setSelectionRange(n, n) } catch {} })
  }
  function onKeyDown(e) {
    // 输入法(IME:中文/日文/拼音等)组合期间的 Enter 是「确认候选词」，不是发送。
    // 若不拦，候选词还没上屏(未进 draft)就把上一版内容发出去，且框里残留的字母清不掉。
    // isComposing=组合进行中；keyCode 229=多数浏览器在组合期给出的哨兵值(双保险)。
    if ((e.nativeEvent && e.nativeEvent.isComposing) || e.keyCode === 229) return
    if (commandMenuVisible) {
      if (e.key === "ArrowDown" && commandOptions.length) {
        e.preventDefault()
        setCommandIndex((index) => (index + 1) % commandOptions.length)
        return
      }
      if (e.key === "ArrowUp" && commandOptions.length) {
        e.preventDefault()
        setCommandIndex((index) => (index - 1 + commandOptions.length) % commandOptions.length)
        return
      }
      if ((e.key === "Enter" || e.key === "Tab") && commandOptions.length) {
        e.preventDefault()
        chooseCommand(commandOptions[Math.min(commandIndex, commandOptions.length - 1)])
        return
      }
      if (e.key === "Escape") {
        e.preventDefault()
        setCommandMenuDismissed(true)
        return
      }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); return }
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return
    const ta = e.target
    const pos = ta.selectionStart
    const val = ta.value
    // 仅当光标在首行/末行才借走方向键回溯历史，否则保留多行文本内的正常移动
    const onFirstLine = !val.slice(0, pos).includes("\n")
    const onLastLine = !val.slice(pos).includes("\n")
    if (e.key === "ArrowUp" && onFirstLine && history.length > 0) {
      e.preventDefault()
      if (histIdx === null) stashRef.current = draft
      const next = histIdx === null ? history.length - 1 : Math.max(0, histIdx - 1)
      setHistIdx(next)
      setDraft(history[next])
      caretEnd(ta)
    } else if (e.key === "ArrowDown" && onLastLine && histIdx !== null) {
      e.preventDefault()
      if (histIdx >= history.length - 1) {
        setHistIdx(null)
        setDraft(stashRef.current) // 翻到最新之后 → 还原浏览前的草稿
      } else {
        setHistIdx(histIdx + 1)
        setDraft(history[histIdx + 1])
      }
      caretEnd(ta)
    }
  }
  // 一次用户指令常被 opencode 拆成多条连续 assistant message。对话区按连续 assistant run
  // 合并成一个"研究助手"块；工具细节留给「进程」视图，产物只在 run 末汇总一次。
  let assistantRun = []
  return (
    <>
      <SelectionToolbar sel={sel} onFollowup={sendFollowup} />
      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll} style={{ display: focus ? "none" : undefined }}>
        {messages.length === 0 && !pendingQuestion && (
          <WelcomeScreen onPick={(t) => !blocked && onSend(t)} />
        )}
        {messages.map((m, i) => {
          const isLast = i === messages.length - 1
          if (m.info.role !== "user") {
            // opencode 压缩上下文时生成的回顾总结：不是在回答你，不展示（见 isCompactionSummary 注释）。
            if (isCompactionSummary(m)) return null
            assistantRun.push(m)
            // 段末判定：到底或后面遇到真实用户消息。compact continue / 系统心跳是内部 user-role
            // 信号，不应切断同一次真实用户请求的 assistant run。
            let isRunEnd = true
            for (let j = i + 1; j < messages.length; j++) {
              const n = messages[j]
              if (!n || !n.info) continue
              if (n.info.role !== "user") { isRunEnd = false; break }
              const txt = userText(n)
              if (!isCompactionContinue(n) && !isInternalSystemNote(txt)) break
              // 尾部只有内部 user-role 信号时，本条 assistant 仍是可见 run 的渲染锚点。
            }
            if (!isRunEnd) return null
            const runMessages = assistantRun
            if (isRunEnd) assistantRun = []
            const runKey = (runMessages[0] && runMessages[0].info && runMessages[0].info.id) || m.info.id
            return <AssistantRun messages={runMessages} key={runKey} onOpenImage={onOpenImage} onOpenFile={onOpenImage} isLast={isLast} busy={busy} />
          }
          const rawTxt = userText(m)
          const files = userFiles(m)
          // opencode compact 续推合成消息：纯内部信号，直接不渲染(连淡灰系统行都不显示)
          if (isCompactionContinue(m)) return null
          // 心跳/进度等系统注入：属于后台进程状态，不进入用户对话流；右侧「进程」面板展示。
          if (isInternalSystemNote(rawTxt)) return null
          assistantRun = []
          // 深入解读 / 划词追问 / 上传附件指令：气泡只显示用户真实输入的部分，完整 prompt 不展开给用户看。
          const uploadNote = uploadNoteDisplay(rawTxt)
          const txt = uploadNote ? uploadNote.text : (deepDiveDisplay(rawTxt) || followupDisplay(rawTxt) || rawTxt)
          // file part 通常只在本地乐观气泡里有（服务端回存的消息只含路径文本，没有内联 file part）；
          // 一旦被服务端消息覆盖，files 会变空——这时改用 uploadNote 从路径文本里剥出的清单重画缩略图
          // （图片用 /raw 按落盘路径取字节，非图片仍走文件名 chip，跟乐观气泡视觉一致）。
          const displayFiles = files.length > 0 ? files : (uploadNote ? uploadNote.files : [])
          return (
            <div className="msg user-msg" key={m.info.id}>
              <div className="user-msg-head">
                {!String(m.info.id || "").startsWith("local-") && (
                  <button type="button" className="user-msg-delete" disabled={busy} onClick={() => { setDeleteError(""); setDeleteTarget(m) }} title="删除这条消息">
                    <Icon name="trash" size={12} />
                  </button>
                )}
                <RoleLine label="你" info={m.info} side="right" />
              </div>
              <div className="bubble-user">
                {txt && <div className="bubble-user-text">{txt}</div>}
                {displayFiles.length > 0 && (
                  <div className="bubble-atts">
                    {displayFiles.map((p, i) => {
                      const src = p.path ? rawUrl(p.path) : fileImgSrc(p)
                      const isImg = p.path
                        ? (p.mime || "").startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(p.path)
                        : !!src
                      const name = p.path ? p.path.split("/").pop() : (p.filename || "文件")
                      return isImg ? (
                        <img className="bubble-img" key={p.id || p.path || i} src={src} alt={name} />
                      ) : (
                        <span className="att-chip" key={p.id || p.path || i}>
                          <span className="att-ic"><Icon name={attIcon(p.mime, name)} /></span>
                          <span className="att-nm">{name}</span>
                        </span>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          )
        })}
        {runtimeStatus && (runtimeStatus.busy || runtimeStatus.type === "error") && !pendingQuestion && !pendingPermission && (
          <div className={"msg runtime-chat-status" + (runtimeStatus.type === "error" ? " error" : "")}>
            <div className="msg-role">
              {runtimeStatus.type === "error" ? <Icon name="x" size={13} /> : <span className="spinner" />}
              {runtimeStatus.type === "submitting"
                ? "正在提交请求…"
                : runtimeStatus.type === "submitted"
                  ? "请求已提交，等待模型响应…"
                  : runtimeStatus.type === "retry"
                    ? "模型服务重试中…"
                    : runtimeStatus.type === "error" ? runtimeStatus.message : "研究助手正在处理…"}
            </div>
          </div>
        )}
        {pendingQuestion && (
          <QuestionCard
            pending={pendingQuestion}
            onReply={onReplyQuestion}
            onReject={onRejectQuestion}
          />
        )}
        {pendingPermission && (
          <PermissionCard pending={pendingPermission} onReply={onReplyPermission} />
        )}
      </div>
      {/* 产物大屏投屏：顶替消息区（chat-scroll 隐藏但不卸载），输入框仍在下方可对话 */}
      {focus && <div className="chat-focus">{focus}</div>}
      {busy && !pendingQuestion && !pendingPermission && (
        <div className="stopbar">
          <button className="stop-gen" onClick={onStop} title="中断当前生成（误发/跑偏时用）">■ 停止生成</button>
        </div>
      )}
      <div
        className="composer"
        onDragOver={(e) => { if (!blocked) { e.preventDefault(); setDragOver(true) } }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          if (blocked) return
          e.preventDefault(); setDragOver(false)
          if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
        }}
      >
        {/* 一键到顶/到底：悬浮在输入框正上方居中 */}
        {messages.length > 0 && (
          <div className="scroll-jump">
            <button type="button" className="jump-btn" title="回到最上" onClick={jumpTop}>
              <svg className="jump-ic" viewBox="0 0 24 24" aria-hidden="true">
                <polyline points="6 14 12 8 18 14" />
              </svg>
            </button>
            <button type="button" className="jump-btn" title="到最底部" onClick={jumpBottom}>
              <svg className="jump-ic" viewBox="0 0 24 24" aria-hidden="true">
                <polyline points="6 10 12 16 18 10" />
              </svg>
            </button>
          </div>
        )}
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          style={{ display: "none" }}
          onChange={(e) => { addFiles(e.target.files); e.target.value = "" }}
        />
        <input
          ref={dirRef}
          type="file"
          webkitdirectory=""
          directory=""
          multiple
          style={{ display: "none" }}
          onChange={(e) => { addFiles(e.target.files); e.target.value = "" }}
        />
        {/* 输入框盒：附件条 → 文本框 → 底部工具栏，整体一个圆角盒（豆包式） */}
        <div className={"composer-box" + (dragOver ? " dragover" : "")}>
          {commandMenuVisible && (
            <div ref={commandMenuRef} className="slash-menu" role="listbox" aria-label="可用命令" onMouseDown={(e) => e.preventDefault()}>
              <div className="slash-menu-title">可用命令</div>
              {!commandsLoaded && <div className="slash-menu-empty">正在加载…</div>}
              {commandsLoaded && commandOptions.length === 0 && <div className="slash-menu-empty">没有匹配的命令</div>}
              {commandOptions.map((item, index) => (
                <button
                  type="button"
                  role="option"
                  aria-selected={index === commandIndex}
                  data-command-index={index}
                  className={"slash-menu-item" + (index === commandIndex ? " active" : "")}
                  key={item.name}
                  onMouseEnter={() => setCommandIndex(index)}
                  onClick={() => chooseCommand(item)}
                >
                  <span className="slash-menu-name">/{item.name}</span>
                  <span className="slash-menu-description">{item.description || "执行该命令"}</span>
                  <span className="slash-menu-source">{item.source === "command" ? "命令" : "能力"}</span>
                </button>
              ))}
            </div>
          )}
          {atts.some((a) => a.isImage) && !VISION_OK.test(modelID || "") && (
            <div className="vision-hint">
              ⚠️ 当前模型（{modelLabelOf(modelID)}）可能无法识别图片{showModelPicker ? "，建议切到 Claude（点左下角模型选择器）" : ""}。仍可发送，但图片可能无回应。
            </div>
          )}
          {atts.length > 0 && (
            <div className="composer-atts">
              {atts.map((a) => (
                <div className={"att-item" + (a.isImage ? " img" : "")} key={a.id}>
                  {a.isImage ? (
                    <img className="att-thumb" src={a.dataUrl} alt={a.name} />
                  ) : (
                    <span className="att-chip">
                      <span className="att-ic"><Icon name={attIcon(a.mime, a.name)} /></span>
                      <span className="att-nm">{a.name}</span>
                      <span className="att-sz">{fmtSize(a.size)}</span>
                    </span>
                  )}
                  <button type="button" className="att-x" title="移除" onClick={() => removeAtt(a.id)}><Icon name="x" size={13} /></button>
                </div>
              ))}
            </div>
          )}
          {followupQuote && (
            <div className="followup-quote">
              <span className="fq-bar" />
              <div className="fq-body">
                <div className="fq-action"><span className="fq-hint">引用选中内容</span></div>
                <div className="fq-text">{followupQuote.text}</div>
              </div>
              <button type="button" className="fq-x" title="移除引用" onClick={() => setFollowupQuote(null)}><Icon name="x" size={13} /></button>
            </div>
          )}
          <textarea
            ref={inputRef}
            id="composer-input"
            rows={2}
            placeholder={
              pendingQuestion
                ? "请先回答上方的问题（或点「跳过」）"
                : disabled
                  ? "点击右上角「+ 新研究」开始"
                  : "输入研究主题或指令… (Enter 发送，Shift+Enter 换行；可粘贴/拖拽图片文件)"
            }
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              setCommandMenuDismissed(false)
              if (histIdx !== null) setHistIdx(null)
            }}
            onKeyDown={onKeyDown}
            onPaste={(e) => {
              const fs = e.clipboardData && e.clipboardData.files
              if (fs && fs.length) { e.preventDefault(); addFiles(fs) }
            }}
            // 仅在「无会话」时才禁用输入；待答问询(pendingQuestion)期间**保持可编辑**——
            // 否则用户提前打的字(尤其 IME 合成中的)会被禁用瞬间丢掉。防「绕过问询抢发」已由
            // submit() 里的 blocked 守卫兜住(问询未答时 Enter/发送都不会真的发出)。
            disabled={disabled}
          />
          {/* 底部工具栏（盒内）：模型选择器（原位置·最左）→ 功能按钮平铺 → 发送 */}
          <div className="composer-tools">
            {showModelPicker && <ModelPicker value={modelID} models={models} onPick={onPickModel} />}
            {showModelPicker && <span className="tool-sep" />}
            <button
              type="button"
              className="tool-btn"
              disabled={blocked}
              title="上传文件/图片到当前对话工作区"
              onClick={() => fileRef.current && fileRef.current.click()}
            ><Icon name="paperclip" /> 上传文件</button>
            <button
              type="button"
              className="tool-btn"
              disabled={blocked}
              title="上传文件夹到当前对话工作区，保留文件夹相对层级"
              onClick={() => dirRef.current && dirRef.current.click()}
            ><Icon name="folder" /> 上传文件夹</button>
            {QUICK_ACTIONS.map((a) => (
              <button
                type="button"
                className="tool-btn"
                key={a.key}
                disabled={blocked}
                title={a.text}
                onClick={() => applyQuick(a)}
              ><Icon name={a.icon} /> {a.label}</button>
            ))}
            <span className="tools-spacer" />
            <button className="send-btn" onClick={submit} disabled={busy || blocked || (!draft.trim() && atts.length === 0)}>发送</button>
          </div>
        </div>
      </div>
      {deleteTarget && (
        <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask" && !deletingMessage) setDeleteTarget(null) }}>
          <div className="np-modal proj-modal">
            <div className="np-title">删除消息</div>
            <div className="np-sub">删除这条用户消息？此操作会从会话历史中永久删除，但不会回滚已经产生的文件修改。</div>
            <div className="delete-message-preview">{userText(deleteTarget).slice(0, 180)}</div>
            {deleteError && <div className="np-error">{deleteError}</div>}
            <div className="np-acts">
              <button className="np-btn" disabled={deletingMessage} onClick={() => setDeleteTarget(null)}>取消</button>
              <button className="np-btn danger" disabled={deletingMessage} onClick={confirmDeleteMessage}>{deletingMessage ? "删除中…" : "删除"}</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ===================================================================
// 右栏 ResearchPanel：7 阶段轨迹 + run 文件树 + 内容查看
// ===================================================================
const CODE_LANGUAGE_BY_EXT = {
  py: "python", pyw: "python", pyi: "python",
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript",
  ts: "typescript", mts: "typescript", cts: "typescript", tsx: "typescript",
  c: "c", h: "c", cc: "cpp", cpp: "cpp", cxx: "cpp", hpp: "cpp", hh: "cpp", hxx: "cpp",
  cs: "csharp", java: "java", kt: "kotlin", kts: "kotlin", scala: "scala",
  go: "go", rs: "rust", swift: "swift", m: "objectivec", mm: "objectivec",
  rb: "ruby", php: "php", pl: "perl", pm: "perl", lua: "lua", r: "r",
  jl: "julia", dart: "dart", ex: "elixir", exs: "elixir", erl: "erlang", hrl: "erlang",
  fs: "fsharp", fsx: "fsharp", vb: "vbnet",
  sh: "bash", bash: "bash", zsh: "bash", fish: "shell", ps1: "powershell",
  bat: "dos", cmd: "dos", sql: "sql",
  html: "xml", htm: "xml", xhtml: "xml", xml: "xml", vue: "xml", svelte: "xml",
  css: "css", scss: "scss", sass: "scss", less: "less",
  json: "json", jsonl: "json", ndjson: "json", geojson: "json", ipynb: "json",
  yaml: "yaml", yml: "yaml", toml: "ini", ini: "ini", cfg: "ini", conf: "ini",
  properties: "properties", env: "bash",
  tex: "latex", sty: "latex", cls: "latex", bib: "latex",
  graphql: "graphql", gql: "graphql", proto: "protobuf",
  cmake: "cmake", gradle: "gradle", groovy: "groovy",
  tf: "hcl", tfvars: "hcl", hcl: "hcl", sol: "solidity",
  asm: "x86asm", s: "x86asm", wasm: "wasm",
  diff: "diff", patch: "diff",
}
const CODE_LANGUAGE_BY_NAME = {
  dockerfile: "dockerfile",
  makefile: "makefile",
  rakefile: "ruby",
  gemfile: "ruby",
  jenkinsfile: "groovy",
  "cmakelists.txt": "cmake",
}
function codeLanguage(name) {
  const base = String(name || "").split("/").pop().toLowerCase()
  if (!base) return ""
  if (CODE_LANGUAGE_BY_NAME[base]) return CODE_LANGUAGE_BY_NAME[base]
  if (base.startsWith("dockerfile.")) return "dockerfile"
  if (base === ".env" || base.startsWith(".env.")) return "bash"
  const ext = base.includes(".") ? base.split(".").pop() : ""
  return CODE_LANGUAGE_BY_EXT[ext] || ""
}

function fileIcon(name) {
  if (name.endsWith(".md")) return "filetext"
  if (name.endsWith(".py")) return "code"
  if (name.endsWith(".json")) return "code"
  if (name.endsWith(".tex")) return "filetext"
  if (name.endsWith(".bib")) return "filetext"
  if (/\.(png|jpe?g|gif|webp|bmp|svg|ico)$/i.test(name)) return "image"
  if (name.endsWith(".pdf")) return "filetext"
  if (/\.(csv|tsv|xls[xmb]?)$/i.test(name)) return "table"
  if (/\.(docx?|pptx?)$/i.test(name)) return "file"
  if (codeLanguage(name)) return "code"
  return "file"
}

// 文件类别决定怎么展示：图/PDF 内联预览、docx 尽量抽文本，其他 Office 走下载。
function fileKind(name) {
  const n = (name || "").toLowerCase()
  if (/\.(png|jpe?g|gif|webp|bmp|svg|ico)$/.test(n)) return "image"
  if (n.endsWith(".pdf")) return "pdf"
  if (/\.(csv|tsv)$/.test(n)) return "csv"
  if (/\.xls[xmb]?$/.test(n)) return "excel"
  if (n.endsWith(".docx")) return "docx"
  if (/\.(doc|pptx?)$/.test(n)) return "office"
  if (n.endsWith(".md")) return "md"
  if (codeLanguage(n)) return "code"
  return "text"
}
// 二进制产物经本地 /raw 路由按真实字节取（绕过只能返回文本的 /oc/file/content）。
function rawUrl(relPath) {
  const sid = ACTIVE_SESSION_ID || ""
  return "/raw?path=" + encodeURIComponent(relPath) + (sid ? "&sessionID=" + encodeURIComponent(sid) : "")
}
// 一键下载整个 workspace：/archive 把 run 目录流式打包成 .tar.gz（server.mjs serveArchive）。
function archiveUrl(relPath) {
  const sid = ACTIVE_SESSION_ID || ""
  return "/archive?path=" + encodeURIComponent(relPath) + (sid ? "&sessionID=" + encodeURIComponent(sid) : "")
}
// 把图片复制到剪贴板：取字节 → ClipboardItem 写入。需安全上下文（localhost 视为安全）。
// 部分浏览器只接受 image/png；生成图就是 png，够用。成功 true，失败 false。
async function copyImageToClipboard(relPath) {
  try {
    const blob = await (await fetch(rawUrl(relPath))).blob()
    const type = blob.type && blob.type.startsWith("image/") ? blob.type : "image/png"
    await navigator.clipboard.write([new ClipboardItem({ [type]: blob })])
    return true
  } catch (e) { console.error("copy image failed", e); return false }
}

// 轻量 CSV/TSV 解析（RFC4180：引号内逗号/换行、转义双引号""）。返回行数组（每行字符串数组）。
function parseDelimited(text, delim) {
  const rows = []
  let row = []
  let cell = ""
  let i = 0
  let quoted = false
  const s = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
  while (i < s.length) {
    const c = s[i]
    if (quoted) {
      if (c === '"') {
        if (s[i + 1] === '"') { cell += '"'; i += 2; continue }
        quoted = false; i++; continue
      }
      cell += c; i++; continue
    }
    if (c === '"') { quoted = true; i++; continue }
    if (c === delim) { row.push(cell); cell = ""; i++; continue }
    if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; i++; continue }
    cell += c; i++
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row) }
  // 去掉末尾全空行
  return rows.filter((r) => !(r.length === 1 && r[0] === ""))
}

// 数据表预览：表头高亮 + 斑马纹 + 行号 + 多 sheet + 前 N 行统计。
const DATA_PREVIEW_ROWS = 200
function DataTable({ sheets }) {
  const [active, setActive] = useState(0)
  const sheet = sheets[active] || { name: "", rows: [] }
  const rows = sheet.rows || []
  const header = rows[0] || []
  const body = rows.slice(1)
  const shown = body.slice(0, DATA_PREVIEW_ROWS)
  const cols = rows.reduce((m, r) => Math.max(m, r.length), 0)
  return (
    <div className="data-wrap">
      {sheets.length > 1 && (
        <div className="sheet-tabs">
          {sheets.map((s, i) => (
            <span
              key={i}
              className={"sheet-chip " + (i === active ? "active" : "")}
              onClick={() => setActive(i)}
            >
              {s.name || "Sheet" + (i + 1)}
            </span>
          ))}
        </div>
      )}
      <div className="data-stat">
        共 {body.length} 行 × {cols} 列
        {body.length > shown.length ? `（预览前 ${shown.length} 行）` : ""}
      </div>
      <div className="data-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th className="rownum">#</th>
              {header.map((h, j) => (
                <th key={j} title={String(h)}>{String(h)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                <td className="rownum">{i + 1}</td>
                {header.map((_, j) => (
                  <td key={j} title={r[j] != null ? String(r[j]) : ""}>{r[j] != null ? String(r[j]) : ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StageTrack({ filesByDir, busy, onOpen, onOpenPdf }) {
  // 每个阶段：在它的子目录里找到约定文件 → done。第一个未 done 的在 busy 时为 active。
  const doneFlags = STAGES.map((s) => stageDone(s, filesByDir))
  const firstTodo = doneFlags.findIndex((f) => !f)
  const pdfName = (filesByDir.deliverables || []).find((f) => f === "paper.pdf")
    || (filesByDir.deliverables || []).find((f) => f.endsWith(".pdf"))
  return (
    <div className="stage-track">
      {STAGES.map((s, i) => {
        const file = doneFlags[i]
        const rel = file ? s.dir + "/" + file : ""
        // 文件在但跨阶段前置(如 results.json)缺 → 孤儿态（残留/越级），不能冒充完成。
        const orphan = !!file && !requiresMet(s, filesByDir)
        const state = file ? (orphan ? "orphan" : "done") : busy && i === firstTodo ? "active" : "todo"
        const isPaper = s.key === "paper"
        function onClick() {
          if (!file) return
          if (isPaper && pdfName) onOpenPdf("deliverables/" + pdfName)
          else onOpen(rel)
        }
        const title = orphan
          ? "⚠ " + s.name + "：产物存在但缺 experiment/results.json——疑似别的研究残留或越级早写，请核对目录"
          : file ? "点击查看 " + (isPaper && pdfName ? "deliverables/" + pdfName : rel) : s.name
        return (
          <div key={s.key} className={"stage-node " + state} onClick={onClick} title={title}>
            <span className="stage-icon">{s.icon}</span>
            <span className="stage-name">{s.name}</span>
            <span className="stage-badge">
              {state === "done" ? "✓" : state === "orphan" ? "⚠" : state === "active" ? <span className="spinner" /> : ""}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── 文献库：从会话里的 arc_search_literature 工具输出聚合（结构化 JSON，零后端、按会话） ──
function mergeLitPaper(prev, next) {
  if (!prev) return next
  if (!next) return prev
  const prevAuthors = Array.isArray(prev.authors) ? prev.authors : []
  const nextAuthors = Array.isArray(next.authors) ? next.authors : []
  const prevEdges = Array.isArray(prev._graph_edges) ? prev._graph_edges : []
  const nextEdges = Array.isArray(next._graph_edges) ? next._graph_edges : []
  const edgeSeen = new Set()
  const edges = prevEdges.concat(nextEdges).filter((e) => {
    const k = JSON.stringify(e || {})
    if (edgeSeen.has(k)) return false
    edgeSeen.add(k)
    return true
  })
  const sources = Array.from(new Set([...(Array.isArray(prev._sources) ? prev._sources : []), ...(Array.isArray(next._sources) ? next._sources : [])]))
  return {
    ...prev,
    ...next,
    authors: nextAuthors.length >= prevAuthors.length ? nextAuthors : prevAuthors,
    abstract: next.abstract || prev.abstract || "",
    url: next.url || prev.url || "",
    doi: next.doi || prev.doi || "",
    arxiv_id: next.arxiv_id || prev.arxiv_id || "",
    _query: next._query || prev._query || "",
    _graph_edges: edges,
    _sources: sources,
  }
}
function mergeLitPapers(listA, listB) {
  const out = []
  const idx = new Map()
  function push(p) {
    if (!p || !p.title) return
    const key = litKey(p)
    if (!key) return
    const cur = idx.get(key)
    if (cur == null) {
      idx.set(key, out.length)
      out.push({
        ...p,
        authors: Array.isArray(p.authors) ? p.authors : [],
        _graph_edges: Array.isArray(p._graph_edges) ? p._graph_edges : [],
        _sources: Array.isArray(p._sources) ? p._sources : [],
      })
      return
    }
    out[cur] = mergeLitPaper(out[cur], p)
  }
  ;(listA || []).forEach(push)
  ;(listB || []).forEach(push)
  return out
}
function extractLitMentionsFromText(text, query) {
  const raw = String(text || "")
  const out = []
  const seen = new Set()
  const add = (p) => {
    if (!p || !p.title) return
    const key = litKey(p)
    if (!key || seen.has(key)) return
    seen.add(key)
    out.push({ ...p, _query: query || "对话提及", _sources: ["assistant-text"] })
  }
  for (const line of raw.split(/\n+/)) {
    String(line || "").replace(/\[([^\]]{3,120})\]\((https?:\/\/[^\s)]+)\)/g, (_m, title, url) => {
      add({ title: String(title || "").trim(), url: String(url || "").trim() })
      return ""
    })
    if (!/(推荐|论文|文献|paper|arxiv|doi|相关工作|相关论文|相关文献|survey|review)/i.test(line)) continue
    String(line || "").replace(/(?:《([^》]{3,120})》|“([^”]{3,120})”|"([^"\n]{3,120})")/g, (_m, a, b, c) => {
      const title = String(a || b || c || "").trim()
      if (title && /[A-Za-z\u4e00-\u9fa5]/.test(title)) add({ title })
      return ""
    })
  }
  raw.replace(/\b(?:doi\s*:\s*|https?:\/\/(?:dx\.)?doi\.org\/)(10\.\d{4,9}\/[^\s<>"']+)/ig, (_m, doi) => {
    add({ title: doi, doi })
    return ""
  })
  raw.replace(/\b(arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)\b/ig, (_m, _p, arxivId) => {
    add({ title: arxivId, arxiv_id: arxivId })
    return ""
  })
  return out
}
function collectLiterature(messages) {
  const seen = new Set()
  const out = []
  const push = (p) => {
    if (!p || !p.title) return
    const key = litKey(p)
    if (!key || seen.has(key)) return
    seen.add(key)
    out.push(p)
  }
  for (const m of messages || []) {
    if (!m.info || m.info.role !== "assistant") continue
    for (const p of m.parts || []) {
      if (p.type === "text" && p.text) {
        for (const item of extractLitMentionsFromText(p.text, "对话提及")) push(item)
        continue
      }
      if (p.type !== "tool" || p.tool !== "arc_search_literature") continue
      const st = p.state || {}
      if (st.status !== "completed" || st.output == null) continue
      const query = String((st.input && st.input.query) || "").trim()
      let data
      try { data = JSON.parse(st.output) } catch { continue }
      const arr = Array.isArray(data)
        ? data
        : Array.isArray(data.accepted) ? data.accepted
        : Array.isArray(data.papers) ? data.papers
        : Array.isArray(data.results) ? data.results
        : Array.isArray(data.candidates) ? data.candidates
        : []
      const graphEdges = Array.isArray(data)
        ? []
        : Array.isArray(data.edges) ? data.edges
        : Array.isArray(data.relations) ? data.relations
        : Array.isArray(data.evidence_edges) ? data.evidence_edges
        : []
      if (!Array.isArray(arr)) continue
      for (const it of arr) {
        if (!it || !it.title) continue
        push({ ...it, _query: query, _graph_edges: graphEdges, _sources: ["arc_search_literature"] })  // _query：产生它的检索词 = 小领域聚类锚点
      }
    }
  }
  return out
}
function paperLink(p) {
  if (!p) return null
  if (p.doi) return "https://doi.org/" + String(p.doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")
  if (p.url) return p.url
  return null
}
// 可嵌入大屏的「全文源」URL（arXiv / 开放获取）。拿不到全文返回 null（降级到完整摘要）。
function paperFullUrl(p) {
  if (!p) return null
  const ax = String(p.arxiv_id || "").trim()
  if (ax) return "https://arxiv.org/pdf/" + ax
  const url = String(p.url || "")
  // url 本身指向 arxiv（abs/pdf）→ 规整成 pdf
  const m = url.match(/arxiv\.org\/(?:abs|pdf)\/([^\s?#]+?)(?:\.pdf)?$/i)
  if (m) return "https://arxiv.org/pdf/" + m[1]
  // url 已是开放 PDF
  if (/^https?:\/\/.+\.pdf($|[?#])/i.test(url)) return url
  return null
}
function paperAuthors(p, n) {
  const a = (p && p.authors) || []
  if (!a.length) return ""
  return a.slice(0, n).join(", ") + (a.length > n ? " 等" : "")
}

// 文献按「小领域」聚类：以产生它的检索 query 分组；类内按年份倒序（越新越靠前）；
// 跨类保持检索先后（反映调研脉络）。无 query 的归到「其他」。
const LIT_HUES = ["#0d7c66", "#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#14b8a6", "#ec4899", "#6366f1", "#84cc16", "#64748b"]
// 聚类标题中文化：检索词多为英文（召回好），这里用术语表 best-effort 翻译显示，
// 查不到的保留原文（“尽量翻译”）；完整原文放进 tooltip。短语在前、单词在后（长优先匹配）。
const LIT_GLOSSARY = [
  ["steady-state visual evoked potential", "稳态视觉诱发电位"],
  ["steady state visual evoked potential", "稳态视觉诱发电位"],
  ["event-related potential", "事件相关电位"],
  ["brain-computer interface", "脑机接口"],
  ["brain computer interface", "脑机接口"],
  ["convolutional neural network", "卷积神经网络"],
  ["graph neural network", "图神经网络"],
  ["recurrent neural network", "循环神经网络"],
  ["canonical correlation analysis", "典型相关分析"],
  ["common spatial pattern", "共空间模式"],
  ["large language model", "大语言模型"],
  ["reinforcement learning", "强化学习"],
  ["self-supervised", "自监督"],
  ["semi-supervised", "半监督"],
  ["unsupervised", "无监督"],
  ["supervised", "有监督"],
  ["transfer learning", "迁移学习"],
  ["domain adaptation", "域适应"],
  ["domain generalization", "域泛化"],
  ["deep learning", "深度学习"],
  ["machine learning", "机器学习"],
  ["neural network", "神经网络"],
  ["attention mechanism", "注意力机制"],
  ["feature extraction", "特征提取"],
  ["signal processing", "信号处理"],
  ["data augmentation", "数据增强"],
  ["classification algorithm", "分类算法"],
  ["motor imagery", "运动想象"],
  ["spatial filter", "空间滤波"],
  ["frequency recognition", "频率识别"],
  ["diffusion model", "扩散模型"],
  ["pre-training", "预训练"],
  ["pretraining", "预训练"],
  ["fine-tuning", "微调"],
  ["finetuning", "微调"],
  ["cross-subject", "跨被试"],
  ["cross subject", "跨被试"],
  ["cross-session", "跨会话"],
  ["subject-independent", "跨被试"],
  ["subject independent", "跨被试"],
  ["real-time", "实时"],
  ["based on", "基于"],
  ["electroencephalography", "脑电"],
  ["electroencephalogram", "脑电"],
  ["riemannian", "黎曼"],
  ["interpretability", "可解释性"],
  ["robustness", "鲁棒性"],
  ["optimization", "优化"],
  ["generative", "生成式"],
  ["benchmark", "基准"],
  ["paradigm", "范式"],
  ["decoding", "解码"],
  ["calibration", "校准"],
  ["classification", "分类"],
  ["algorithms", "算法"],
  ["algorithm", "算法"],
  ["datasets", "数据集"],
  ["dataset", "数据集"],
  ["networks", "网络"],
  ["network", "网络"],
  ["methods", "方法"],
  ["method", "方法"],
  ["models", "模型"],
  ["model", "模型"],
  ["learning", "学习"],
  ["transfer", "迁移"],
  ["recognition", "识别"],
  ["detection", "检测"],
  ["prediction", "预测"],
  ["generation", "生成"],
  ["representation", "表征"],
  ["augmentation", "增强"],
  ["analysis", "分析"],
  ["design", "设计"],
  ["framework", "框架"],
  ["evaluation", "评估"],
  ["performance", "性能"],
  ["application", "应用"],
  ["system", "系统"],
  ["survey", "综述"],
  ["review", "综述"],
  ["speller", "拼写器"],
  ["spelling", "拼写"],
  ["stimulation", "刺激"],
  ["stimulus", "刺激"],
  ["frequency", "频率"],
  ["spatial", "空间"],
  ["temporal", "时序"],
  ["using", "使用"],
  ["online", "在线"],
  ["offline", "离线"],
  ["phase", "相位"],
  ["EEG", "脑电"],
  ["BCI", "脑机接口"],
]
function translateLitLabel(q) {
  if (!q) return q
  let s = String(q)
  for (const [en, zh] of LIT_GLOSSARY) {
    const pat = en.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    s = s.replace(new RegExp("(^|[^A-Za-z])" + pat + "(?![A-Za-z])", "gi"), (m, pre) => pre + zh)
  }
  return s
}
function litYear(p) { const n = parseInt(p && p.year, 10); return isNaN(n) ? -Infinity : n }
function groupLiterature(papers) {
  const groups = new Map()
  for (const p of papers || []) {
    const q = (p._query && p._query.trim()) || "其他"
    if (!groups.has(q)) groups.set(q, [])
    groups.get(q).push(p)
  }
  const out = []
  for (const [query, ps] of groups) {
    ps.sort((a, b) => litYear(b) - litYear(a)) // 类内：新 → 旧
    out.push({ query, papers: ps })
  }
  return out
}

function parseJsonLines(text) {
  return String(text || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line) } catch { return null }
    })
    .filter(Boolean)
}
function normalizePaperCard(p, edges, fallbackQuery) {
  if (!p || !p.title) return null
  let authors = p.authors || []
  if (typeof authors === "string") authors = authors.split(/,\s*/).filter(Boolean)
  return {
    ...p,
    authors,
    abstract: p.abstract || p.summary || p.claimed_contribution || p.relation_to_user_topic || "",
    url: p.url || p.link || "",
    _query: (p.source_queries && p.source_queries[0]) || fallbackQuery || "已筛选文献",
    _graph_edges: edges || [],
  }
}
async function readTextArtifact(path) {
  const fc = await readFileContent(path).catch(() => null)
  return fc && (fc.content != null ? String(fc.content) : (typeof fc === "string" ? fc : ""))
}
async function loadLiteratureArtifacts(runDir) {
  if (!runDir) return { papers: [], candidates: [], files: {}, diagnostics: [] }
  const roots = [runDir, runDir + "/planning", runDir + "/deliverables"]
  async function firstText(name) {
    for (const root of roots) {
      const path = root + "/" + name
      const txt = await readTextArtifact(path)
      if (txt) return { path, text: txt }
    }
    return null
  }
  const [
    paperCards,
    edgeCards,
    claimCards,
    gapMap,
    ideaBank,
    scope,
    diagnostics,
    literatureMap,
    fieldMap,
    queries,
    rejectedPapers,
    seedPapers,
    candidatePapers,
  ] = await Promise.all([
    firstText("paper_cards.jsonl"),
    firstText("evidence_edges.jsonl"),
    firstText("claim_cards.jsonl"),
    firstText("gap_map.yaml"),
    firstText("idea_bank.yaml"),
    firstText("scope.md"),
    firstText("search_diagnostics.jsonl"),
    firstText("literature_map.md"),
    firstText("field_map.md"),
    firstText("queries.jsonl"),
    firstText("rejected_papers.jsonl"),
    firstText("seed_papers.jsonl"),
    firstText("candidate_papers.jsonl"),
  ])
  const edges = edgeCards ? parseJsonLines(edgeCards.text) : []
  const papers = paperCards
    ? parseJsonLines(paperCards.text).map((p) => normalizePaperCard(p, edges, "已筛选文献")).filter(Boolean)
    : []
  const candidates = mergeLitPapers(
    seedPapers ? parseJsonLines(seedPapers.text).map((p) => normalizePaperCard(p, edges, "seed_papers")).filter(Boolean) : [],
    candidatePapers ? parseJsonLines(candidatePapers.text).map((p) => normalizePaperCard(p, edges, "candidate_papers")).filter(Boolean) : [],
  )
  return {
    papers,
    candidates,
    diagnostics: diagnostics ? parseJsonLines(diagnostics.text) : [],
    files: {
      scope,
      paperCards,
      edgeCards,
      claimCards,
      gapMap,
      ideaBank,
      diagnostics,
      literatureMap,
      fieldMap,
      queries,
      rejectedPapers,
      seedPapers,
      candidatePapers,
    },
  }
}

// 单篇文献卡片（★ 收藏 + 悬停「深入解读」+ 大屏 + 原文）。compact=资产侧栏紧凑版（不显摘要）
function LitCard({ p, onFocus, starred, onToggleStar, onDeepDive, compact }) {
  const link = paperLink(p)
  return (
    <div className={"lit-card" + (compact ? " compact" : "")}>
      <div className="lit-card-top">
        <div className="lit-title" onClick={() => onFocus(p)} title="点击大屏展示">{p.title}</div>
        <button
          type="button"
          className={"lit-star" + (starred ? " on" : "")}
          title={starred ? "取消收藏" : "收藏到资产"}
          onClick={(e) => { e.stopPropagation(); onToggleStar && onToggleStar(p) }}
        >
          <Icon name="star" size={15} style={starred ? { fill: "currentColor" } : undefined} />
        </button>
      </div>
      <div className="lit-meta">{paperAuthors(p, 3)}{p.year ? " · " + p.year : ""}</div>
      {!compact && p.abstract ? <div className="lit-abs">{p.abstract}</div> : null}
      <div className="lit-actions">
        {link
          ? <a className="file-dl" href={link} target="_blank" rel="noreferrer"><Icon name="link" size={13} /> 原文</a>
          : <span className="lit-nolink">无链接</span>}
        <span className="lit-actions-sp" />
        <button
          type="button"
          className="lit-deepdive"
          title="把这篇论文发给研究助手做深入精读"
          onClick={(e) => { e.stopPropagation(); onDeepDive && onDeepDive(p) }}
        >
          <Icon name="search" size={13} /> 深入解读
        </button>
      </div>
    </div>
  )
}

const LIT_WORKFLOW_STAGES = [
  { key: "scope", name: "范围确认", fileKey: "scope", desc: "研究边界与目标" },
  { key: "papers", name: "有效文献", fileKey: "paperCards", desc: "筛选后的论文卡" },
  { key: "map", name: "文献图谱", fileKey: "literatureMap", desc: "论文关系与领域地图" },
  { key: "field", name: "领域地图", fileKey: "fieldMap", desc: "子方向、热点与瓶颈" },
  { key: "gap", name: "缺口地图", fileKey: "gapMap", desc: "GapCard 与反例检查" },
  { key: "idea", name: "Idea Bank", fileKey: "ideaBank", desc: "已核查或待核查的想法池" },
]
function LiteratureWorkflowTrack({ files, busy, onOpen }) {
  const hasAnyArtifact = LIT_WORKFLOW_STAGES.some((s) => files && (files[s.fileKey] || (s.altKey && files[s.altKey])))
  if (!hasAnyArtifact) return null
  const done = LIT_WORKFLOW_STAGES.map((s) => files && (files[s.fileKey] || (s.altKey && files[s.altKey])))
  const firstTodo = done.findIndex((x) => !x)
  return (
    <div className="lit-workflow">
      <div className="lit-workflow-head">文献调研阶段</div>
      <div className="lit-workflow-steps">
        {LIT_WORKFLOW_STAGES.map((s, i) => {
          const hit = done[i]
          const state = hit ? "done" : busy && i === firstTodo ? "active" : "todo"
          return (
            <button
              key={s.key}
              type="button"
              className={"lit-workflow-step " + state}
              title={hit ? hit.path : s.desc}
              onClick={() => hit && onOpen && onOpen(hit.path)}
              disabled={!hit}
            >
              <span className="lit-workflow-dot">{hit ? "✓" : i + 1}</span>
              <span className="lit-workflow-main">
                <span>{s.name}</span>
                <small>{s.desc}</small>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// 一个小领域分组（可折叠）
function LitGroup({ group, idx, onFocus, starredKeys, onToggleStar, onDeepDive, compact }) {
  const [open, setOpen] = useState(true)
  const hue = LIT_HUES[idx % LIT_HUES.length]
  const label = translateLitLabel(group.query)
  return (
    <div className="lit-group">
      <div
        className="lit-group-head"
        onClick={() => setOpen((v) => !v)}
        title={group.query}
      >
        <span className="lit-group-dot" style={{ background: hue }} />
        <span className="lit-group-name">{label}</span>
        <span className="lit-group-count" style={{ color: hue, borderColor: hue }}>{group.papers.length}</span>
        <span className={"lit-group-caret" + (open ? " open" : "")}>▸</span>
      </div>
      {open && (
        <div className="lit-group-body">
          {group.papers.map((p, i) => (
            <LitCard
              key={(p.doi || p.title) + "_" + i}
              p={p}
              onFocus={onFocus}
              starred={starredKeys ? starredKeys.has(paperKey(p)) : false}
              onToggleStar={onToggleStar}
              onDeepDive={onDeepDive}
              compact={compact}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function shortLabel(s, n = 34) {
  const t = String(s || "").replace(/\s+/g, " ").trim()
  return t.length > n ? t.slice(0, n - 1) + "…" : t
}
function wrapLabel(s, lineLen = 34, maxLines = 2) {
  const text = String(s || "").replace(/\s+/g, " ").trim()
  if (!text) return [""]
  const words = text.split(" ")
  const lines = []
  let cur = ""
  words.forEach((w) => {
    if (!cur) {
      cur = w
    } else if ((cur + " " + w).length <= lineLen) {
      cur += " " + w
    } else {
      lines.push(cur)
      cur = w
    }
  })
  if (cur) lines.push(cur)
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    kept[maxLines - 1] = shortLabel(kept[maxLines - 1] + " " + lines.slice(maxLines).join(" "), lineLen)
    return kept
  }
  return lines
}
function litGraphPaperID(p) {
  return "paper:" + paperKey(p).replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 80)
}
function litGraphRegisterPaperAliases(map, p, id) {
  const vals = [
    id,
    p && p.paper_id,
    p && p.id,
    p && p.title,
    p && p.doi,
    p && p.arxiv_id,
    p && p.url,
  ]
  vals.forEach((v) => {
    const k = String(v || "").trim().toLowerCase()
    if (k) map.set(k, id)
  })
}
function litGraphEndpointID(ref, map) {
  if (!ref) return null
  if (typeof ref === "object") {
    return litGraphEndpointID(ref.paper_id || ref.id || ref.title || ref.doi || ref.arxiv_id || ref.url, map)
  }
  const s = String(ref).trim()
  if (!s) return null
  if (s.startsWith("topic:") || s.startsWith("paper:") || s.startsWith("gap:")) return s
  return map.get(s.toLowerCase()) || null
}
function litRelationLabel(kind) {
  const k = String(kind || "").trim()
  const labels = {
    retrieved_by: "检索命中",
    cites: "引用",
    extends: "扩展",
    uses_method: "方法复用",
    same_task: "同任务",
    same_benchmark: "同基准",
    compares_with: "直接比较",
    contradicts: "反证/限定",
    survey_of: "综述覆盖",
    application_of: "应用迁移",
    gap_supports: "支撑缺口",
    gap_counterexample: "缺口反例",
  }
  return labels[k] || k || "关联"
}
function litRelationHue(kind, fallback) {
  const colors = {
    cites: "#64748b",
    extends: "#2563eb",
    uses_method: "#7c3aed",
    same_task: "#0d9488",
    same_benchmark: "#059669",
    compares_with: "#f59e0b",
    contradicts: "#dc2626",
    survey_of: "#475569",
    application_of: "#0891b2",
    gap_supports: "#16a34a",
    gap_counterexample: "#b91c1c",
  }
  return colors[String(kind || "")] || fallback || "#64748b"
}
function litGraphNormalizeRelationEdge(edge) {
  if (!edge || typeof edge !== "object") return null
  return {
    source: edge.source || edge.from || edge.src || edge.paper || edge.paper_id,
    target: edge.target || edge.to || edge.dst || edge.related_paper || edge.related_paper_id,
    kind: edge.relation || edge.kind || edge.type,
    evidence: edge.evidence || edge.reason || edge.notes || edge.query || "",
    confidence: edge.confidence || "",
  }
}
function makeLiteratureGraph(groups, collapsed) {
  const nodes = []
  const edges = []
  const paperIDByKey = new Map()
  const semanticEdges = []
  const width = 1040
  let y = 44
  groups.forEach((g, gi) => {
    const hue = LIT_HUES[gi % LIT_HUES.length]
    const tid = "topic:" + gi
    const label = translateLitLabel(g.query)
    nodes.push({ id: tid, kind: "topic", x: 92, y, r: 22, label: shortLabel(label, 22), full: g.query, hue, group: g })
    if (!collapsed.has(tid)) {
      const papers = (g.papers || []).slice(0, 18)
      papers.forEach((p, pi) => {
        const pid = litGraphPaperID(p) || ("paper:" + gi + ":" + pi)
        litGraphRegisterPaperAliases(paperIDByKey, p, pid)
        const px = pi % 2 === 0 ? 360 : 675
        const py = y + pi * 70 - Math.max(0, papers.length - 1) * 18
        const lines = wrapLabel((p && p.title) || "Untitled", 34, 2)
        nodes.push({ id: pid, kind: "paper", x: px, y: py, w: 280, h: lines.length > 1 ? 58 : 46, lines, label: shortLabel((p && p.title) || "Untitled", 48), full: p.title, hue, paper: p })
        edges.push({ source: tid, target: pid, kind: "retrieved_by", label: "检索命中", hue })
        if (pi > 0) edges.push({ source: litGraphPaperID(papers[pi - 1]) || ("paper:" + gi + ":" + (pi - 1)), target: pid, kind: "same_query_context", label: "同主题", hue, soft: true })
        const rels = []
        if (Array.isArray(p.relations)) rels.push(...p.relations)
        if (Array.isArray(p.relationships)) rels.push(...p.relationships)
        if (Array.isArray(p.evidence_edges)) rels.push(...p.evidence_edges)
        if (Array.isArray(p._graph_edges)) rels.push(...p._graph_edges)
        rels.map(litGraphNormalizeRelationEdge).filter(Boolean).forEach((rel) => {
          semanticEdges.push({ ...rel, fallbackSource: pid, hue })
        })
      })
      if ((g.papers || []).length > 18) {
        nodes.push({ id: "more:" + gi, kind: "more", x: 675, y: y + papers.length * 70 - Math.max(0, papers.length - 1) * 18, label: "+" + ((g.papers || []).length - 18) + " 篇", hue })
      }
      y += Math.max(170, papers.length * 70 + 42)
    } else {
      y += 74
    }
  })
  const edgeSeen = new Set(edges.map((e) => e.source + ">" + e.target + ":" + e.kind))
  semanticEdges.forEach((rel) => {
    const source = litGraphEndpointID(rel.source, paperIDByKey) || rel.fallbackSource
    const target = litGraphEndpointID(rel.target, paperIDByKey)
    if (!source || !target || source === target) return
    const kind = rel.kind || "related"
    const key = source + ">" + target + ":" + kind
    if (edgeSeen.has(key)) return
    edgeSeen.add(key)
    edges.push({
      source,
      target,
      kind,
      label: litRelationLabel(kind),
      evidence: rel.evidence,
      confidence: rel.confidence,
      hue: litRelationHue(kind, rel.hue),
      semantic: true,
    })
  })
  return { nodes, edges, width, height: Math.max(280, y + 24) }
}
function downloadTextFile(name, text, type = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function printSVGAsPDF(title, svgText) {
  const w = window.open("", "_blank")
  if (!w) return
  const safeTitle = String(title || "文献图谱").replace(/[<>]/g, "")
  w.document.write(`<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>${safeTitle}</title>
  <style>
    @page { size: A4 landscape; margin: 12mm; }
    body { margin: 0; font-family: Inter, Arial, "Noto Sans SC", sans-serif; color: #111827; }
    .page { padding: 8px; }
    h1 { font-size: 18px; margin: 0 0 10px; }
    svg { width: 100%; height: auto; display: block; }
  </style>
</head>
<body>
  <div class="page">
    <h1>${safeTitle}</h1>
    ${svgText}
  </div>
  <script>
    window.onload = () => {
      setTimeout(() => { window.print() }, 250)
    }
  </script>
</body>
</html>`)
  w.document.close()
}
function literatureGraphExportData(groups) {
  const nodes = []
  const edges = []
  const paperIDByKey = new Map()
  const semanticEdges = []
  groups.forEach((g, gi) => {
    const topicID = "topic:" + gi
    nodes.push({ id: topicID, type: "topic", label: translateLitLabel(g.query), query: g.query })
    ;(g.papers || []).forEach((p, pi) => {
      const pid = litGraphPaperID(p) || ("paper:" + gi + ":" + pi)
      litGraphRegisterPaperAliases(paperIDByKey, p, pid)
      if (!nodes.some((n) => n.id === pid)) {
        nodes.push({
          id: pid,
          type: "paper",
          title: p.title || "",
          authors: p.authors || [],
          year: p.year || "",
          doi: p.doi || "",
          arxiv_id: p.arxiv_id || "",
          url: paperLink(p) || "",
        })
      }
      edges.push({ source: topicID, target: pid, relation: "retrieved_by", label: "检索命中", evidence: g.query })
      if (pi > 0) {
        edges.push({
          source: litGraphPaperID(g.papers[pi - 1]) || ("paper:" + gi + ":" + (pi - 1)),
          target: pid,
          relation: "same_query_context",
          label: "同主题",
          evidence: g.query,
        })
      }
      const rels = []
      if (Array.isArray(p.relations)) rels.push(...p.relations)
      if (Array.isArray(p.relationships)) rels.push(...p.relationships)
      if (Array.isArray(p.evidence_edges)) rels.push(...p.evidence_edges)
      if (Array.isArray(p._graph_edges)) rels.push(...p._graph_edges)
      rels.map(litGraphNormalizeRelationEdge).filter(Boolean).forEach((rel) => {
        semanticEdges.push({ ...rel, fallbackSource: pid })
      })
    })
  })
  const edgeSeen = new Set(edges.map((e) => e.source + ">" + e.target + ":" + e.relation))
  semanticEdges.forEach((rel) => {
    const source = litGraphEndpointID(rel.source, paperIDByKey) || rel.fallbackSource
    const target = litGraphEndpointID(rel.target, paperIDByKey)
    if (!source || !target || source === target) return
    const relation = rel.kind || "related"
    const key = source + ">" + target + ":" + relation
    if (edgeSeen.has(key)) return
    edgeSeen.add(key)
    edges.push({
      source,
      target,
      relation,
      label: litRelationLabel(relation),
      evidence: rel.evidence || "",
      confidence: rel.confidence || "",
    })
  })
  return { version: 1, generated_at: new Date().toISOString(), nodes, edges }
}
function mermaidID(s) {
  return String(s || "node").replace(/[^a-z0-9_]/gi, "_").replace(/^([^a-zA-Z_])/, "_$1").slice(0, 48) || "node"
}
function mermaidText(s) {
  return String(s || "").replace(/["\[\]\n\r]/g, " ").replace(/\s+/g, " ").trim()
}
function literatureGraphMindmapMermaid(groups) {
  const lines = ["mindmap", "  root((文献图谱))"]
  groups.forEach((g, gi) => {
    const topic = mermaidID("topic_" + gi)
    lines.push("    " + topic + "[" + mermaidText(translateLitLabel(g.query)) + "]")
    ;(g.papers || []).forEach((p, pi) => {
      const meta = [p.year, paperAuthors(p, 1)].filter(Boolean).join(" · ")
      const label = mermaidText((p.title || "Untitled") + (meta ? " (" + meta + ")" : ""))
      lines.push("      " + mermaidID(topic + "_paper_" + pi) + "[" + label + "]")
    })
  })
  return lines.join("\n")
}
async function literatureGraphMindmapSVG(groups) {
  if (!mermaidSeq) mermaidSeq = 1
  const id = "lit-mindmap-" + (mermaidSeq++)
  mermaid.initialize({
    startOnLoad: false,
    theme: document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "base",
    securityLevel: "loose",
  })
  const out = await mermaid.render(id, literatureGraphMindmapMermaid(groups))
  return out.svg || ""
}
function LiteratureGraph({ papers, onFocus, starredKeys, onToggleStar, onDeepDive }) {
  const groups = groupLiterature(papers)
  const [collapsed, setCollapsed] = useState(() => new Set())
  const [selected, setSelected] = useState(null)
  const [scale, setScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [exportOpen, setExportOpen] = useState(false)
  const dragRef = useRef(null)
  const exportMenuRef = useRef(null)
  const graph = React.useMemo(() => makeLiteratureGraph(groups, collapsed), [groups, collapsed])
  const byID = React.useMemo(() => {
    const m = new Map()
    graph.nodes.forEach((n) => m.set(n.id, n))
    return m
  }, [graph])
  useEffect(() => {
    if (!exportOpen) return
    function onDocPointerDown(e) {
      if (exportMenuRef.current && exportMenuRef.current.contains(e.target)) return
      setExportOpen(false)
    }
    function onDocKeyDown(e) {
      if (e.key === "Escape") setExportOpen(false)
    }
    document.addEventListener("pointerdown", onDocPointerDown)
    document.addEventListener("keydown", onDocKeyDown)
    return () => {
      document.removeEventListener("pointerdown", onDocPointerDown)
      document.removeEventListener("keydown", onDocKeyDown)
    }
  }, [exportOpen])
  function toggleTopic(id) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  function clickNode(n) {
    if (n.kind === "topic") { toggleTopic(n.id); setSelected(null); return }
    if (n.kind === "paper") setSelected(n.paper)
  }
  function resetView() {
    setScale(1)
    setPan({ x: 0, y: 0 })
  }
  function zoomBy(delta) {
    setScale((v) => Math.max(0.55, Math.min(2.4, +(v + delta).toFixed(2))))
  }
  function onWheel(e) {
    e.preventDefault()
    const dir = e.deltaY > 0 ? -1 : 1
    setScale((v) => Math.max(0.55, Math.min(2.4, +(v + dir * 0.12).toFixed(2))))
  }
  function onMouseDown(e) {
    if (e.target && e.target.closest && e.target.closest(".lit-node")) return
    const rect = e.currentTarget.getBoundingClientRect()
    dragRef.current = {
      x: e.clientX,
      y: e.clientY,
      pan,
      sx: graph.width / Math.max(1, rect.width),
      sy: graph.height / Math.max(1, rect.height),
    }
  }
  function onMouseMove(e) {
    const d = dragRef.current
    if (!d) return
    e.preventDefault()
    setPan({
      x: d.pan.x + (e.clientX - d.x) * d.sx / scale,
      y: d.pan.y + (e.clientY - d.y) * d.sy / scale,
    })
  }
  function onMouseUp() {
    dragRef.current = null
  }
  function exportJSON() {
    downloadTextFile("literature-graph.json", JSON.stringify(literatureGraphExportData(groups), null, 2), "application/json;charset=utf-8")
  }
  async function exportMindmap() {
    downloadTextFile("literature-mindmap.mmd", literatureGraphMindmapMermaid(groups), "text/plain;charset=utf-8")
  }
  async function exportMindmapSVG() {
    const svg = await literatureGraphMindmapSVG(groups)
    if (svg) downloadTextFile("literature-mindmap.svg", svg, "image/svg+xml;charset=utf-8")
  }
  function serializeGraphSVG() {
    const svg = document.querySelector(".lit-graph-canvas svg")
    if (!svg) return ""
    const copy = svg.cloneNode(true)
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg")
    copy.setAttribute("width", String(graph.width))
    copy.setAttribute("height", String(graph.height))
    copy.setAttribute("viewBox", "0 0 " + graph.width + " " + graph.height)
    copy.setAttribute("style", "background:#ffffff")
    const content = copy.querySelector(".lit-graph-content")
    if (content) content.setAttribute("transform", "translate(0 0) scale(1)")
    const css = `
      :root{--bg-card:#ffffff;--bg-soft:#f8fafc;--border:#dbe3ef;--text:#111827;--text-dim:#667085}
      svg{font-family:Inter,Arial,"Noto Sans SC",sans-serif}
      .lit-edge{fill:none;stroke-width:1.2;opacity:.38}.lit-edge.soft{stroke-width:.8;opacity:.18;stroke-dasharray:4 5}
      .lit-topic-mark{fill:#fff;font-size:18px;font-weight:800}.lit-topic-label{fill:#111827;font-size:13px;font-weight:800}
      .lit-topic-sub{fill:#667085;font-size:11px}.lit-paper-label{fill:#111827;font-size:12px;font-weight:700}
      .lit-paper-meta{fill:#667085;font-size:10.5px}.lit-node.more text{fill:#667085;font-size:11px;font-weight:700}
      .lit-node.paper rect{fill:#ffffff;stroke:#dbe3ef}.lit-zoom-badge{display:none}
    `
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style")
    style.textContent = css
    copy.insertBefore(style, copy.firstChild)
    return new XMLSerializer().serializeToString(copy)
  }
  async function exportGraphPDF() {
    const svgText = serializeGraphSVG()
    if (svgText) printSVGAsPDF("文献图谱", svgText)
  }
  async function exportSVG() {
    const svgText = serializeGraphSVG()
    if (svgText) downloadTextFile("literature-graph.svg", svgText, "image/svg+xml;charset=utf-8")
  }
  async function chooseExport(fn) {
    try {
      await fn()
    } catch (e) {
      console.error("literature graph export failed", e)
    } finally {
      setExportOpen(false)
    }
  }
  const sel = selected || (groups[0] && groups[0].papers && groups[0].papers[0]) || null
  return (
    <div className="lit-graph-wrap">
      <div className="lit-graph-hint">
        <span>点击主题展开/收起，点击论文查看详情；滚轮缩放，拖拽空白处移动画布。</span>
        <span className="lit-graph-controls">
          <button type="button" onClick={() => zoomBy(-0.15)} title="缩小">-</button>
          <button type="button" onClick={resetView}>重置</button>
          <button type="button" onClick={() => zoomBy(0.15)} title="放大">+</button>
          <span className="lit-export-menu" ref={exportMenuRef}>
            <button type="button" className="lit-export-btn" onClick={() => setExportOpen((v) => !v)} title="下载文献图谱">
              <Icon name="download" size={13} /> 下载
            </button>
            {exportOpen && (
              <span className="lit-export-pop">
                <button type="button" onClick={() => chooseExport(exportSVG)}>图谱图片 · SVG</button>
                <button type="button" onClick={() => chooseExport(exportMindmapSVG)}>脑图图片 · SVG</button>
                <button type="button" onClick={() => chooseExport(exportMindmap)}>脑图源文件 · Mermaid</button>
                <button type="button" onClick={() => chooseExport(exportGraphPDF)}>图谱打印 · PDF</button>
                <button type="button" onClick={() => chooseExport(exportJSON)}>结构数据 · JSON</button>
              </span>
            )}
          </span>
        </span>
      </div>
      <div className="lit-graph-canvas">
        <svg
          viewBox={"0 0 " + graph.width + " " + graph.height}
          role="img"
          aria-label="文献图谱"
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <defs>
            <marker id="lit-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 Z" fill="currentColor" />
            </marker>
          </defs>
          <g className="lit-graph-content" transform={`translate(${pan.x} ${pan.y}) scale(${scale})`}>
            {graph.edges.map((e, i) => {
              const a = byID.get(e.source)
              const b = byID.get(e.target)
              if (!a || !b) return null
              const x1 = a.kind === "topic" ? a.x + 24 : a.x + (a.w || 0)
              const y1 = a.y
              const x2 = b.kind === "paper" ? b.x - 2 : b.x
              const y2 = b.y
              const mx = (x1 + x2) / 2
              return (
                <path key={i} className={"lit-edge " + (e.soft ? "soft" : "")} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} stroke={e.hue}>
                  <title>{[e.label || e.kind, e.confidence ? "置信度: " + e.confidence : "", e.evidence ? "证据: " + e.evidence : ""].filter(Boolean).join("\n")}</title>
                </path>
              )
            })}
            {graph.nodes.map((n) => {
              if (n.kind === "topic") {
                const isCollapsed = collapsed.has(n.id)
                return (
                  <g key={n.id} className="lit-node topic" transform={`translate(${n.x},${n.y})`} onClick={() => clickNode(n)}>
                    <circle r={n.r} fill={n.hue} />
                    <text className="lit-topic-mark" textAnchor="middle" dy="4">{isCollapsed ? "+" : "-"}</text>
                    <text className="lit-topic-label" x="32" y="-4">{n.label}</text>
                    <text className="lit-topic-sub" x="32" y="14">{(n.group.papers || []).length} 篇</text>
                    <title>{n.full}</title>
                  </g>
                )
              }
              if (n.kind === "paper") {
                const active = sel && paperKey(sel) === paperKey(n.paper)
                const lines = n.lines || [n.label]
                return (
                  <g key={n.id} className={"lit-node paper " + (active ? "active" : "")} transform={`translate(${n.x},${n.y - n.h / 2})`} onClick={() => clickNode(n)}>
                    <rect width={n.w} height={n.h} rx="7" fill="var(--bg-card)" stroke={active ? n.hue : "var(--border)"} />
                    <circle cx="15" cy="20" r="4" fill={n.hue} />
                    <text x="28" y="15" className="lit-paper-label">
                      {lines.map((line, i) => <tspan key={i} x="28" dy={i === 0 ? 0 : 14}>{line}</tspan>)}
                    </text>
                    <text x="28" y={lines.length > 1 ? 44 : 32} className="lit-paper-meta">{paperAuthors(n.paper, 1) || "未知作者"}{n.paper && n.paper.year ? " · " + n.paper.year : ""}</text>
                    <title>{n.full}</title>
                  </g>
                )
              }
              return (
                <g key={n.id} className="lit-node more" transform={`translate(${n.x},${n.y})`}>
                  <rect x="-40" y="-13" width="80" height="26" rx="13" fill="var(--bg-soft)" stroke={n.hue} />
                  <text textAnchor="middle" dy="4">{n.label}</text>
                </g>
              )
            })}
          </g>
          <g className="lit-zoom-badge" transform="translate(12 22)">
            <rect x="0" y="-15" width="64" height="24" rx="6" />
            <text x="32" y="1" textAnchor="middle">{Math.round(scale * 100)}%</text>
          </g>
        </svg>
      </div>
      {sel ? (
        <div className="lit-graph-detail">
          <LitCard
            p={sel}
            onFocus={onFocus}
            starred={starredKeys ? starredKeys.has(paperKey(sel)) : false}
            onToggleStar={onToggleStar}
            onDeepDive={onDeepDive}
          />
        </div>
      ) : null}
    </div>
  )
}

// 右栏「文献」Tab：按小领域聚类的卡片列表（标题/作者/年份/摘要预览 + ★收藏 + 深入解读 + 原文 + 大屏）
function LiteratureList({ papers, onFocus, starredKeys, onToggleStar, onDeepDive }) {
  const [view, setView] = useState("graph")
  if (!papers || !papers.length) {
    return (
      <div className="file-empty" style={{ marginTop: 30, padding: 20 }}>
        还没有检索到文献。<br />研究助手进入<b>文献综述</b>阶段后，<br />这里会汇总本次调研到的所有论文。
      </div>
    )
  }
  const groups = groupLiterature(papers)
  return (
    <div className="lit-list">
      <div className="lit-toolbar">
        <div className="lit-count">共 {papers.length} 篇 · {groups.length} 个方向</div>
        <div className="lit-view-tabs">
          <button className={view === "graph" ? "active" : ""} onClick={() => setView("graph")}>图谱</button>
          <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>列表</button>
        </div>
      </div>
      {view === "graph" ? (
        <LiteratureGraph
          papers={papers}
          onFocus={onFocus}
          starredKeys={starredKeys}
          onToggleStar={onToggleStar}
          onDeepDive={onDeepDive}
        />
      ) : (
        groups.map((g, gi) => (
          <LitGroup
            key={g.query + "_" + gi}
            group={g}
            idx={gi}
            onFocus={onFocus}
            starredKeys={starredKeys}
            onToggleStar={onToggleStar}
            onDeepDive={onDeepDive}
          />
        ))
      )}
    </div>
  )
}

// 从原文里截取含关键词的上下文片段（用于搜索结果预览）。q 已是小写；text 原大小写。
// 返回 {pre, hit, post}：命中词前后各 ctx 字符，便于渲染时把 hit 高亮。找不到返回 null。
function makeSnippet(text, qLower, ctx = 34) {
  if (!text) return null
  const i = text.toLowerCase().indexOf(qLower)
  if (i < 0) return null
  const s = Math.max(0, i - ctx)
  const e = Math.min(text.length, i + qLower.length + ctx)
  return {
    pre: (s > 0 ? "…" : "") + text.slice(s, i),
    hit: text.slice(i, i + qLower.length),
    post: text.slice(i + qLower.length, e) + (e < text.length ? "…" : ""),
  }
}

// 左栏全局搜索框：搜「所有会话标题 + 全部会话消息正文 + 资产(收藏文献)」，不区分大小写，边打边搜。
// 数据来源全部复用现成：listSessions / getMessages / userText / starred；点结果用 onPickSession / onPickPaper 跳转。
// 不卡顿三件套：① 会话消息 blob 缓存(indexRef，避免每次打字重拉) ② debounce ③ 搜索代次(seq)作废过期结果。
function SearchBox({ starred, listSessions, getMessages, userText, onPickSession, onPickPaper }) {
  const [q, setQ] = useState("")
  const [indexing, setIndexing] = useState(false)
  const [res, setRes] = useState(null) // { sessions:[{sid,title,snippet}], papers:[{p,snippet}] } | null
  const indexRef = useRef({ at: 0, items: [] }) // {at: 建索引时刻, items:[{sid,title,blob,raw}]}
  const seqRef = useRef(0)
  const debRef = useRef(null)
  const boxRef = useRef(null)

  // 确保会话消息索引就绪（缓存 60s 内复用）；并发拉全部会话消息，建 blob。
  async function ensureIndex() {
    if (Date.now() - indexRef.current.at < 60_000 && indexRef.current.items.length) return
    setIndexing(true)
    try {
      const sessions = await listSessions()
      const items = await Promise.all(
        (sessions || []).map(async (s) => {
          let raw = ""
          try {
            const msgs = await getMessages(s.id)
            // 压缩摘要（isCompactionSummary）不算真实对话内容，排除掉，否则搜到摘要里的常见词
            // （"目标"/"约束"之类）会带出一段莫名其妙的摘录片段。
            raw = (msgs || []).filter((m) => !isCompactionSummary(m)).map((m) => userText(m)).filter(Boolean).join("\n")
          } catch {
            /* 单个会话拉失败 → 仅标题可搜 */
          }
          return { sid: s.id, title: s.title || "", raw, blob: ((s.title || "") + "\n" + raw).toLowerCase() }
        }),
      )
      indexRef.current = { at: Date.now(), items }
    } catch {
      /* 列会话失败 → 保留旧索引 */
    } finally {
      setIndexing(false)
    }
  }

  async function runSearch(query) {
    const ql = query.trim().toLowerCase()
    if (!ql) { setRes(null); return }
    const my = ++seqRef.current
    await ensureIndex()
    if (my !== seqRef.current) return // 期间用户又打字了 → 本次作废
    const sessions = []
    for (const it of indexRef.current.items) {
      if (it.blob.includes(ql)) {
        sessions.push({ sid: it.sid, title: it.title, snippet: makeSnippet(it.raw, ql) })
      }
    }
    const papers = []
    for (const p of starred || []) {
      const hay = [p.title, (p.authors || []).join(" "), p.year, p.abstract].filter(Boolean).join("  ")
      if (hay.toLowerCase().includes(ql)) papers.push({ p, snippet: makeSnippet(hay, ql) })
    }
    if (my === seqRef.current) setRes({ sessions, papers })
  }

  function onChange(e) {
    const v = e.target.value
    setQ(v)
    if (debRef.current) clearTimeout(debRef.current)
    if (!v.trim()) { setRes(null); seqRef.current++; return }
    debRef.current = setTimeout(() => runSearch(v), 250)
  }

  // 失焦/Esc 关下拉（点结果用 onMouseDown 抢在 blur 前触发）
  const [focused, setFocused] = useState(false)
  const open = focused && !!q.trim()

  function renderSnippet(sn) {
    if (!sn) return null
    return (
      <span className="sr-snippet">
        {sn.pre}<mark>{sn.hit}</mark>{sn.post}
      </span>
    )
  }

  const empty = res && res.sessions.length === 0 && res.papers.length === 0

  return (
    <div className="search-box" ref={boxRef}>
      <input
        className="search-input"
        type="text"
        value={q}
        placeholder="搜对话 + 资产"
        onChange={onChange}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 150)}
        onKeyDown={(e) => { if (e.key === "Escape") { setQ(""); setRes(null); e.currentTarget.blur() } }}
      />
      {open && (
        <div className="search-results">
          {indexing && !res && <div className="sr-hint">索引中…</div>}
          {empty && !indexing && <div className="sr-hint">无匹配</div>}
          {res && res.sessions.length > 0 && (
            <div className="sr-group">
              <div className="sr-group-head"><Icon name="chat" size={13} /> 对话（{res.sessions.length}）</div>
              {res.sessions.map((r) => (
                <div
                  key={r.sid}
                  className="sr-item"
                  onMouseDown={(e) => { e.preventDefault(); onPickSession(r.sid); setFocused(false) }}
                  title={r.title}
                >
                  <div className="sr-title">{r.title || "(未命名对话)"}</div>
                  {renderSnippet(r.snippet)}
                </div>
              ))}
            </div>
          )}
          {res && res.papers.length > 0 && (
            <div className="sr-group">
              <div className="sr-group-head"><Icon name="star" size={13} /> 资产（{res.papers.length}）</div>
              {res.papers.map((r, i) => (
                <div
                  key={(r.p.doi || r.p.title || "") + "_" + i}
                  className="sr-item"
                  onMouseDown={(e) => { e.preventDefault(); onPickPaper(r.p); setFocused(false) }}
                  title={r.p.title}
                >
                  <div className="sr-title">{r.p.title || "(无题文献)"}</div>
                  {renderSnippet(r.snippet)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// 分组选择弹层：选一个已建好的分组，或输入新名字直接建组再选（服务端 /kb/mkdir 幂等，新旧名字一视同仁）。
// 「上传文档」「收藏文献」两处共用；onPick(groupName)，groupName===""表示「未分类」。
function GroupPicker({ title, groups, onPick, onCancel }) {
  const [name, setName] = useState("")
  function submitNew() {
    const n = name.trim()
    if (n) onPick(n)
  }
  return (
    <div className="modal-mask" onClick={onCancel}>
      <div className="group-picker" onClick={(e) => e.stopPropagation()}>
        <div className="group-picker-ttl">{title}</div>
        <div className="group-picker-list">
          <div className="group-picker-item" onClick={() => onPick("")}><Icon name="folder" size={14} /> 未分类</div>
          {(groups || []).map((g) => (
            <div className="group-picker-item" key={g} onClick={() => onPick(g)}><Icon name="folder" size={14} /> {g}</div>
          ))}
        </div>
        <div className="group-picker-new">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="＋ 新建分组，回车确认"
            maxLength={40}
            onKeyDown={(e) => { if (e.key === "Enter") submitNew() }}
          />
          <button onClick={submitNew} disabled={!name.trim()}>创建并选它</button>
        </div>
        <button className="group-picker-cancel" onClick={onCancel}>取消</button>
      </div>
    </div>
  )
}

// 建分组弹窗：屏幕正中的大弹框（不是内嵌小输入框），右上角两个 icon——✓确定/✕取消。
function CreateGroupModal({ onConfirm, onCancel }) {
  const [name, setName] = useState("")
  function submit() {
    const n = name.trim()
    if (n) onConfirm(n)
  }
  return (
    <div className="modal-mask" onClick={onCancel}>
      <div className="gcm" onClick={(e) => e.stopPropagation()}>
        <div className="gcm-actions">
          <button className="gcm-ic gcm-ok" title="确定" onClick={submit} disabled={!name.trim()}><Icon name="check" size={18} /></button>
          <button className="gcm-ic gcm-cancel" title="取消" onClick={onCancel}><Icon name="x" size={18} /></button>
        </div>
        <div className="gcm-ttl">新建分组</div>
        <input
          autoFocus
          className="gcm-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="输入分组名称"
          maxLength={40}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") onCancel() }}
        />
      </div>
    </div>
  )
}

// 一个分组（或"未分类"）内的「文档 + 文献」小节：本分组内直传，不再弹分组选择（目标已经很明确）。
function KbDocsAndPapers({ docs, papers, group, onUpload, onOpenKb, onReadKb, onMoveKbToProject, onDeleteKb, onFocus, starredKeys, onToggleStar, onDeepDive }) {
  const [busy, setBusy] = useState(false)
  const fileRef = useRef(null)
  const litGroups = groupLiterature(papers)
  async function pick(e) {
    const fs = Array.from(e.target.files || [])
    e.target.value = ""
    if (!fs.length) return
    setBusy(true)
    try { await onUpload(fs, group) } finally { setBusy(false) }
  }
  return (
    <React.Fragment>
      <div className="kb-sub">
        <div className="kb-sub-head">
          <span><Icon name="filetext" size={14} /> 文档</span>
          <button
            className="kb-upload-btn"
            onClick={() => fileRef.current && fileRef.current.click()}
            disabled={busy}
            title="上传文档到知识库（docx/md/pdf 等，全局共享）"
          >{busy ? "上传中…" : "＋ 上传"}</button>
          <input ref={fileRef} type="file" multiple accept={ACCEPT} style={{ display: "none" }} onChange={pick} />
        </div>
        {docs.length === 0 ? (
          <div className="assets-empty">这里还没有文档</div>
        ) : (
              <div className="kb-file-list">
            {docs.map((f) => (
              <div className="kb-file" key={f.path} title={f.path}>
                <span className="kb-file-ic" onClick={() => onOpenKb(f.path)}><Icon name={attIcon("", f.name)} /></span>
                <span className="kb-file-nm" onClick={() => onOpenKb(f.path)}>{f.name}</span>
                <button className="kb-file-act" title="在 Workspace 打开预览" onClick={() => onOpenKb(f.path)}>打开</button>
                <button className="kb-file-act" title="新建一个资料解读对话" onClick={() => onReadKb(f)}>解读</button>
                <button className="kb-file-act" title="复制到当前项目 inputs/knowledge-base" onClick={() => onMoveKbToProject(f)}>移入项目</button>
                <a className="file-dl" href={rawUrl(f.path)} download title="下载"><Icon name="download" size={14} /></a>
                <span className="kb-file-del" title="从知识库删除" onClick={() => onDeleteKb(f)}><Icon name="trash" size={13} /></span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="kb-sub">
        <div className="kb-sub-head"><span><Icon name="star" size={14} /> 文献</span></div>
        {papers.length === 0 ? (
          <div className="assets-empty">点亮右侧文献的 ☆ 即可收藏到这里</div>
        ) : (
          litGroups.map((g, gi) => (
            <LitGroup
              key={g.query + "_" + gi}
              group={g}
              idx={gi}
              onFocus={onFocus}
              starredKeys={starredKeys}
              onToggleStar={onToggleStar}
              onDeepDive={onDeepDive}
            />
          ))
        )}
      </div>
    </React.Fragment>
  )
}

// 一个分组的可展开行：点头部就地展开/收起（不跳转），展开内容缩进显示在下面，随全屏页一起滚动。
function KbFolderSection({ group, papers, onRenameGroup, ...rest }) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(group.name)
  const count = group.files.length + papers.length
  useEffect(() => { if (!editing) setDraft(group.name) }, [group.name, editing])
  async function submitRename() {
    const next = draft.trim()
    if (!next || next === group.name) { setDraft(group.name); setEditing(false); return }
    await onRenameGroup(group.name, next)
    setEditing(false)
  }
  return (
    <div className="kb-folder">
      <div className="kb-folder-row" onClick={() => setOpen((v) => !v)}>
        <span className={"assets-caret" + (open ? " open" : "")}>▸</span>
        <Icon name="folder" size={16} />
        {editing ? (
          <input
            className="kb-folder-rename"
            autoFocus
            value={draft}
            onClick={(e) => e.stopPropagation()}
            onDoubleClick={(e) => e.stopPropagation()}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => { submitRename().catch((e) => { alert("重命名失败：" + (e && e.message || e)); setDraft(group.name); setEditing(false) }) }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                submitRename().catch((err) => { alert("重命名失败：" + (err && err.message || err)); setDraft(group.name); setEditing(false) })
              }
              if (e.key === "Escape") {
                e.preventDefault()
                setDraft(group.name)
                setEditing(false)
              }
            }}
            maxLength={60}
          />
        ) : (
          <span
            className="kb-folder-name"
            title="双击重命名分组"
            onDoubleClick={(e) => { e.stopPropagation(); setDraft(group.name); setEditing(true) }}
          >{group.name}</span>
        )}
        <span className="kb-folder-count">{count} 项</span>
      </div>
      {open && (
        <div className="kb-folder-body">
          <KbDocsAndPapers docs={group.files} papers={papers} group={group.name} {...rest} />
        </div>
      )}
    </div>
  )
}

// 左栏「知识库」：全局收藏的文献 + 用户上传的文档（docx/md/pdf 等，全局共享，本轮仅存档浏览）。
// 侧栏里只是一个入口条（点击 → 打开整窗全屏界面），完整内容在 <KnowledgeBaseBody> 里，
// 由 App 级 overlayView 状态在全屏覆盖层中渲染（侧栏窄，展开拥挤；全屏给后续新功能留空间）。
// 知识库支持「分组」（单层文件夹，文档和文献共用）：分组行就地展开/收起（不跳转另一个界面），
// kbData={root:[未分类文件], groups:[{name,files}]} 由 App 维护（分组=knowledge-base/ 下的子目录）。
// 上传类型跟对话框共用同一份 ACCEPT（定义于文件顶部），保持两处入口一致。
// 侧栏入口条：点击 → onOpen()（打开全屏），不再就地展开。
function KnowledgeBaseEntry({ papers, kbData, onOpen }) {
  const docCount = (kbData?.root?.length || 0) + (kbData?.groups || []).reduce((s, g) => s + g.files.length, 0)
  const total = docCount + (papers ? papers.length : 0)
  return (
    <div className="assets-panel">
      <div className="assets-head" onClick={onOpen} title="知识库：收藏文献 + 上传文档（全屏打开）">
        <span className="assets-title"><Icon name="book" size={15} /> 知识库</span>
        <span className="assets-count">{total}</span>
      </div>
    </div>
  )
}
// 全屏界面主体：分组列表（点击就地展开）+ 未分类（常驻展示）。供全屏覆盖层渲染。
function KnowledgeBaseBody({ papers, kbData, onCreateGroup, onRenameGroup, onUpload, onOpenKb, onReadKb, onMoveKbToProject, onDeleteKb, onFocus, starredKeys, onToggleStar, onDeepDive }) {
  const [creatingGroup, setCreatingGroup] = useState(false)
  const root = kbData?.root || []
  const groupList = kbData?.groups || []
  const rootPapers = papers.filter((p) => !p.group)
  const commonProps = { onUpload, onOpenKb, onReadKb, onMoveKbToProject, onDeleteKb, onFocus, starredKeys, onToggleStar, onDeepDive }

  return (
    <div className="fs-body">
      <div className="kb-folders">
        <div className="kb-folders-head">
          <span>分组（点击就地展开）</span>
          <button className="kb-folder-add" onClick={() => setCreatingGroup(true)}>
            <Icon name="plus" size={12} /> 新建分组
          </button>
        </div>
        {groupList.length === 0 ? (
          <div className="assets-empty">还没有分组，点上面「＋新建分组」建一个</div>
        ) : (
          <div className="kb-folder-list">
            {groupList.map((g) => (
              <KbFolderSection
                key={g.name}
                group={g}
                papers={papers.filter((p) => (p.group || "") === g.name)}
                onRenameGroup={onRenameGroup}
                {...commonProps}
              />
            ))}
          </div>
        )}
      </div>
      {/* 未分类：常驻展示，不用展开 */}
      <div className="kb-unsorted">
        <div className="kb-unsorted-ttl"><Icon name="folder" size={14} /> 未分类</div>
        <KbDocsAndPapers docs={root} papers={rootPapers} group="" {...commonProps} />
      </div>
      {creatingGroup && (
        <CreateGroupModal
          onConfirm={(name) => { onCreateGroup(name); setCreatingGroup(false) }}
          onCancel={() => setCreatingGroup(false)}
        />
      )}
    </div>
  )
}

// 标题是否还是 opencode 给的占位默认值（建会话时写的 "新对话" 或 "New session - <时间戳>"）。
function isPlaceholderTitle(t) {
  const s = String(t || "").trim()
  return !s || s === "新对话" || /^New session\b/.test(s)
}

// 左栏「MoonLog」：夜间自动编译的知识摘要，纯只读——不接受手动触发（凌晨2点后由服务端调度器
// 自动编译过去24h活跃的对话+产物变更），前端只负责列日期、展示编译结果。
// 侧栏入口条：点击 → onOpen()（打开全屏）。
function MoonLogEntry({ dateCount, onOpen }) {
  return (
    <div className="assets-panel">
      <div className="assets-head" onClick={onOpen} title="MoonLog：每天凌晨自动编译的知识摘要（全屏打开）">
        <span className="assets-title"><Icon name="moon" size={15} /> MoonLog</span>
        <span className="assets-count">{dateCount}</span>
      </div>
    </div>
  )
}
// 全屏界面主体：左边日期列表，右边选中日期的编译内容。
function MoonLogBody() {
  const [dates, setDates] = useState(null) // null=加载中
  const [selected, setSelected] = useState(null)
  const [data, setData] = useState(null) // null=未选/加载中
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const list = await listMoonlogDates()
      if (cancelled) return
      setDates(list)
      if (list.length) setSelected(list[0])
    })()
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    if (!selected) { setData(null); return }
    let cancelled = false
    setData(null)
    ;(async () => {
      const d = await getMoonlog(selected)
      if (!cancelled) setData(d)
    })()
    return () => { cancelled = true }
  }, [selected])
  return (
    <div className="assets-split">
      <div className="assets-tree-col">
        {dates === null ? (
          <div className="assets-empty">加载中…</div>
        ) : dates.length === 0 ? (
          <div className="assets-empty">凌晨2点后自动编译，暂无历史</div>
        ) : (
          <div className="session-list">
            {dates.map((d) => (
              <div key={d} className={"session-item moonlog-date-item" + (d === selected ? " active" : "")} onClick={() => setSelected(d)}>
                <span className="session-item-icon"><Icon name="moon" size={13} /></span>
                <span className="session-item-title">{d}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="assets-preview-col">
        {!selected ? (
          <div className="file-empty" style={{ padding: 24 }}>选一个日期查看当天的知识摘要。</div>
        ) : data === null ? (
          <div className="file-empty" style={{ padding: 24 }}>加载中…</div>
        ) : data.skipped ? (
          <div className="file-empty" style={{ padding: 24 }}>{selected} 当天无活动，未编译。</div>
        ) : data.error ? (
          <div className="file-empty" style={{ padding: 24 }}>
            编译失败，原始输出：
            <pre style={{ whiteSpace: "pre-wrap", textAlign: "left", marginTop: 8 }}>{data.raw}</pre>
          </div>
        ) : (
          <div className="moonlog-content">
            <div className="moonlog-head">
              <Icon name="moon" size={18} />
              <h2>{selected}</h2>
            </div>
            {data.summary && (
              <div className="moonlog-card moonlog-summary-card">
                <p className="moonlog-summary">{data.summary}</p>
              </div>
            )}
            {(data.sessions || []).length > 0 && (
              <div className="moonlog-section">
                <h3 className="moonlog-section-title">当日对话</h3>
                {data.sessions.map((s) => (
                  <div key={s.id} className="moonlog-card moonlog-session-card">
                    <div className="moonlog-card-top"><strong>{s.title}</strong></div>
                    <div className="moonlog-card-body">{s.highlights}</div>
                  </div>
                ))}
              </div>
            )}
            {(data.artifacts || []).length > 0 && (
              <div className="moonlog-section">
                <h3 className="moonlog-section-title">产物 / 知识库变更</h3>
                {data.artifacts.map((a, i) => (
                  <div key={i} className="moonlog-card moonlog-artifact-card">
                    <div className="moonlog-card-top"><strong>{a.dir}</strong></div>
                    <div className="moonlog-card-body">{(a.files || []).join("、")}</div>
                    {a.note && <div className="moonlog-note">{a.note}</div>}
                  </div>
                ))}
              </div>
            )}
            {(data.open_questions || []).length > 0 && (
              <div className="moonlog-section">
                <h3 className="moonlog-section-title">待解决问题</h3>
                <ul className="moonlog-oq">
                  {data.open_questions.map((q, i) => <li key={i}>{q}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// 中栏「大屏」：把一篇文献拉到中间放大展示（元数据 + 完整摘要 + 跳转原文）
// 可靠开放全文源（arXiv 及常见 OA 会议/预印本）：命中则大屏默认直接看全文 PDF（基本不空白）。
const RELIABLE_FULL = /(arxiv\.org|ar5iv|aclanthology\.org|proceedings\.mlr\.press|papers\.nips\.cc|proceedings\.neurips\.cc|openreview\.net|biorxiv\.org|medrxiv\.org|drops\.dagstuhl\.de)\//i
function PaperFocus({ paper, onClose }) {
  const link = paper ? paperLink(paper) : null
  const fullUrl = paper ? paperFullUrl(paper) : null
  // 命中可靠开放源 → 默认全文；其它来源（出版社 / 付费墙 .pdf，iframe 常空白）默认落到
  // 「题目 + 完整摘要 + 链接」这个**永远有内容**的视图，避免点开大屏一片空白；全文做成可点标签按需加载。
  const isReliableFull = !!fullUrl && RELIABLE_FULL.test(fullUrl)
  const [view, setView] = useState(isReliableFull ? "full" : "abs")
  useEffect(() => {
    const f = paperFullUrl(paper)
    setView(f && RELIABLE_FULL.test(f) ? "full" : "abs")
  }, [paper])
  if (!paper) return null
  return (
    <div className="paper-focus">
      <div className="paper-focus-bar">
        <span className="paper-focus-barttl" title={paper.title}><Icon name="book" size={14} /> {paper.title}</span>
        <span style={{ display: "flex", gap: 8, alignItems: "center", flex: "0 0 auto" }}>
          {fullUrl && (
            <span className="pf-tabs">
              <button className={"pf-tab " + (view === "abs" ? "active" : "")} onClick={() => setView("abs")}>摘要</button>
              <button className={"pf-tab " + (view === "full" ? "active" : "")} onClick={() => setView("full")}>全文</button>
            </span>
          )}
          <button onClick={onClose} title="返回对话"><Icon name="x" size={13} /> 返回</button>
        </span>
      </div>
      {view === "full" && fullUrl ? (
        <iframe
          className="file-pdf-full"
          src={"/paper?url=" + encodeURIComponent(fullUrl)}
          title={paper.title}
        />
      ) : (
        <div className="paper-focus-body">
          <h1 className="paper-focus-title">{paper.title}</h1>
          <div className="paper-focus-meta">{(paper.authors || []).join(", ")}{paper.year ? " · " + paper.year : ""}</div>
          <div className="paper-focus-links">
            {link ? <a className="paper-focus-open" href={link} target="_blank" rel="noreferrer">在新标签打开原文 ↗</a> : null}
            {fullUrl ? <button className="paper-focus-open paper-focus-inlinefull" onClick={() => setView("full")}>在大屏内嵌全文 ↘</button> : null}
            {fullUrl ? <a className="paper-focus-open" href={"/paper?url=" + encodeURIComponent(fullUrl)} target="_blank" rel="noreferrer">在新标签看全文 PDF ↗</a> : null}
            {paper.doi ? <span className="paper-focus-doi">DOI: {paper.doi}</span> : null}
          </div>
          <h3 className="paper-focus-h">摘要</h3>
          <div className="paper-focus-abs">{paper.abstract || "（该来源未提供摘要）"}</div>
          {!fullUrl && (
            <div className="paper-focus-note">
              该文献没有可嵌入的开放全文（非 arXiv / 付费墙）——上方「打开原文」可跳转出版社页面查看。
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// 文件内容渲染体（body-only，无工具栏/壳）——供中栏分栏工作区每格内容复用。
// 按 fileKind 分支：图片/PDF 直出，md/code/text/csv/excel 异步载入（alive 防切换竞态）。
const MONACO_VERSION = "0.52.2"
let monacoModulePromise = null
function loadMonaco() {
  if (window.monaco && window.monaco.editor) return Promise.resolve(window.monaco)
  if (monacoModulePromise) return monacoModulePromise
  monacoModulePromise = new Promise((resolve, reject) => {
    const start = () => {
      if (!window.require || !window.require.config) {
        reject(new Error("Monaco loader unavailable"))
        return
      }
      window.require.config({ paths: { vs: `/_unpkg/monaco-editor@${MONACO_VERSION}/min/vs` } })
      window.require(["vs/editor/editor.main"], () => resolve(window.monaco), reject)
    }
    const existing = document.querySelector("script[data-monaco-loader]")
    if (existing) {
      if (window.require && window.require.config) start()
      else existing.addEventListener("load", start, { once: true })
      return
    }
    const script = document.createElement("script")
    script.src = `/_unpkg/monaco-editor@${MONACO_VERSION}/min/vs/loader.js`
    script.dataset.monacoLoader = "1"
    script.onload = start
    script.onerror = () => {
      script.remove()
      reject(new Error("Failed to load Monaco"))
    }
    document.head.appendChild(script)
  }).catch((error) => {
    monacoModulePromise = null
    throw error
  })
  return monacoModulePromise
}

const MONACO_LANGUAGE_ALIASES = {
  bash: "shell", dos: "bat", objectivec: "objective-c", properties: "ini",
  solidity: "sol", vbnet: "vb", x86asm: "plaintext", wasm: "plaintext",
  makefile: "plaintext", cmake: "plaintext", latex: "plaintext", diff: "plaintext",
}
function monacoLanguage(language) {
  return MONACO_LANGUAGE_ALIASES[language] || language || "plaintext"
}

function CodeView({ text, language }) {
  const source = String(text || "")
  const lineCount = Math.max(1, source.split("\n").length)
  const lineNumbers = Array.from({ length: lineCount }, (_, index) => index + 1).join("\n")
  const languageLabel = String(language || "text").toUpperCase()
  const hostRef = useRef(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let disposed = false
    let editor = null
    let model = null
    let themeObserver = null
    setReady(false)

    loadMonaco().then((monaco) => {
      if (disposed || !host) return
      const syncTheme = () => monaco.editor.setTheme(
        document.documentElement.dataset.theme === "dark" ? "vs-dark" : "vs"
      )
      syncTheme()
      model = monaco.editor.createModel(source, monacoLanguage(language))
      model.updateOptions({ tabSize: 4, insertSpaces: true })
      editor = monaco.editor.create(host, {
        model,
        readOnly: true,
        domReadOnly: true,
        automaticLayout: true,
        theme: document.documentElement.dataset.theme === "dark" ? "vs-dark" : "vs",
        fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
        fontSize: 13,
        lineHeight: 21,
        fontLigatures: false,
        wordWrap: "off",
        scrollBeyondLastLine: false,
        renderWhitespace: "selection",
        renderLineHighlight: "gutter",
        lineNumbersMinChars: 3,
        glyphMargin: false,
        folding: true,
        showFoldingControls: "mouseover",
        matchBrackets: "always",
        selectionHighlight: true,
        occurrencesHighlight: "singleFile",
        colorDecorators: true,
        bracketPairColorization: { enabled: true, independentColorPoolPerBracketType: true },
        guides: { indentation: true, bracketPairs: true, highlightActiveIndentation: true },
        stickyScroll: { enabled: true },
        minimap: { enabled: host.clientWidth >= 620, showSlider: "mouseover", maxColumn: 100 },
        overviewRulerLanes: 0,
        hideCursorInOverviewRuler: true,
        renderValidationDecorations: "off",
        smoothScrolling: true,
        contextmenu: true,
        fixedOverflowWidgets: true,
        padding: { top: 12, bottom: 16 },
        scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
        ariaLabel: `${languageLabel} code preview`,
      })
      themeObserver = new MutationObserver(syncTheme)
      themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] })
      setReady(true)
    }).catch(() => {
      if (!disposed) setReady(false)
    })

    return () => {
      disposed = true
      if (themeObserver) themeObserver.disconnect()
      if (editor) editor.dispose()
      if (model) model.dispose()
    }
  }, [source, language, languageLabel])

  return (
    <div className="code-view">
      <div className="code-view-meta"><Icon name="code" size={13} /> {languageLabel}</div>
      <div className="code-editor-body">
        <div className="monaco-host" ref={hostRef} />
        {!ready && (
          <div className="code-fallback">
            <div className="code-scroll">
              <div className="code-shell">
                <pre className="code-lines" aria-hidden="true">{lineNumbers}</pre>
                <pre className="code-pre"><code>{source}</code></pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function FileView({ path }) {
  const kind = fileKind(path)
  const [content, setContent] = useState("")
  const [tableData, setTableData] = useState(null)
  const [loading, setLoading] = useState(kind === "md" || kind === "code" || kind === "text" || kind === "csv" || kind === "excel" || kind === "docx")
  const [err, setErr] = useState(false)
  useEffect(() => {
    // 图片/PDF/office 不异步载入
    if (!(kind === "md" || kind === "code" || kind === "text" || kind === "csv" || kind === "excel" || kind === "docx")) return
    let alive = true
    setContent(""); setTableData(null); setErr(false); setLoading(true)
    ;(async () => {
      try {
        if (kind === "md" || kind === "code" || kind === "text") {
          const fc = await readFileContent(path)
          if (alive) setContent((fc && fc.content) || "(无法读取)")
        } else if (kind === "csv") {
          const fc = await readFileContent(path)
          const txt = (fc && fc.content) || ""
          const delim = /\.tsv$/i.test(path) ? "\t" : ","
          if (alive) setTableData({ sheets: [{ name: "", rows: parseDelimited(txt, delim) }] })
        } else if (kind === "excel") {
          const buf = await (await fetch(rawUrl(path))).arrayBuffer()
          const XLSX = await import("/_esm/xlsx@0.18.5?bundle&target=es2022")
          const wb = XLSX.read(new Uint8Array(buf), { type: "array" })
          const sheets = wb.SheetNames.map((nm) => ({
            name: nm,
            rows: XLSX.utils.sheet_to_json(wb.Sheets[nm], { header: 1, blankrows: false, defval: "" }),
          }))
          if (alive) setTableData({ sheets })
        } else if (kind === "docx") {
          const buf = await (await fetch(rawUrl(path))).arrayBuffer()
          const mammothMod = await import("/_esm/mammoth@1.8.0?bundle&target=es2022")
          const mammoth = mammothMod.default || mammothMod
          const out = await mammoth.extractRawText({ arrayBuffer: buf })
          if (alive) setContent((out && out.value && out.value.trim()) || "(未能抽取到正文)")
        }
      } catch {
        if (alive) setErr(true)
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [path]) // eslint-disable-line
  if (!path) return null
  if (kind === "image") return <div className="ws-img-wrap"><img className="file-img-full" src={rawUrl(path)} alt={path} /></div>
  if (kind === "pdf") return <iframe className="ws-pdf-full" src={rawUrl(path)} title={path} />
  if (loading) return <div className="file-empty">加载中…</div>
  if (err) return <div className="file-empty">无法预览此文件，请<a className="paper-focus-open" href={rawUrl(path)} download>下载查看</a>。</div>
  if (kind === "md") return <MarkdownView className="paper-focus-body md-body" text={maskPath(content)} />
  if (kind === "code") return <CodeView text={maskPath(content)} language={codeLanguage(path)} />
  if (kind === "docx") return <div className="focus-body-pad"><pre className="focus-pre">{maskPath(content)}</pre></div>
  if (kind === "csv" || kind === "excel")
    return tableData ? <div className="focus-body-pad"><DataTable sheets={tableData.sheets} /></div> : <div className="file-empty">解析中…</div>
  if (kind === "office")
    return <div className="file-empty">此格式无法在浏览器内预览，请<a className="paper-focus-open" href={rawUrl(path)} download>下载查看</a>。</div>
  return <div className="focus-body-pad"><pre className="focus-pre">{maskPath(content)}</pre></div>
}

// LaTeX 编译中间产物——文件树里隐藏，避免编译后刷屏。
const AUX_EXT = /\.(aux|log|fls|fdb_latexmk|out|bbl|blg|synctex\.gz|toc|nav|snm|vrb)$/i
function isAuxFile(name) { return AUX_EXT.test(name || "") }

const INTERNAL_ARTIFACT_NAMES = new Set([
  "queries.jsonl",
  "search_diagnostics.jsonl",
  "rejected_papers.jsonl",
  "claim_cards.jsonl",
  "evidence_edges.jsonl",
  "seed_papers.jsonl",
  "candidate_papers.jsonl",
])
const HIDDEN_ARTIFACT_NAMES = new Set([
  "venue",
  "plan",
  "notes",
])
function artifactVisibility(pathOrName) {
  const name = String(pathOrName || "").split("/").filter(Boolean).pop() || ""
  const lowerName = name.toLowerCase()
  if (!name || name.startsWith(".") || isAuxFile(name)) return "hidden"
  if (HIDDEN_ARTIFACT_NAMES.has(lowerName)) return "hidden"
  if (INTERNAL_ARTIFACT_NAMES.has(lowerName)) return "internal"
  if (/\.jsonl$/i.test(name) && name !== "paper_cards.jsonl") return "internal"
  return "user"
}
function showInUserFileTree(entry, showInternal) {
  if (!entry) return false
  if (entry.type === "directory") return true
  const v = artifactVisibility(entry.name || entry.path)
  if (v === "hidden") return false
  return showInternal || v === "user"
}

function DiagnosticArtifacts({ files, onOpen }) {
  const [open, setOpen] = useState(false)
  const items = Object.values(files || {})
    .filter(Boolean)
    .filter((f) => artifactVisibility(f.path) === "internal")
  if (!items.length) return null
  return (
    <div className="diag-box">
      <button type="button" className="diag-head" onClick={() => setOpen((v) => !v)}>
        <span><Icon name="code" size={13} /> 后台诊断</span>
        <span>{items.length} 个文件 {open ? "收起" : "展开"}</span>
      </button>
      {open && (
        <div className="diag-list">
          {items.map((f) => (
            <button type="button" className="diag-item" key={f.path} onClick={() => onOpen && onOpen(f.path)} title={f.path}>
              <Icon name={fileIcon(f.path)} size={13} />
              <span>{f.path.split("/").pop()}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// 论文卡：deliverables 有 .tex 时显示。「编译」**全程交给助手**：把"编译并修复直到通过"的
// 指令发进当前会话——助手用 arc_latex_check 编译，缺类文件(如 aaai25.sty)就经代理取作者包/
// 降级 article，修 \ref/\cite/缺图，反复重编。大屏/下载读助手编出的 deliverables/paper.pdf。
function PaperCard({ runDir, deliverables, busy, onOpenPdf, onAskAgent }) {
  const texName = deliverables.find((f) => f === "paper.tex") || deliverables.find((f) => f.endsWith(".tex"))
  const [waiting, setWaiting] = useState(false)
  const waitingRef = useRef(false)
  const sawBusyRef = useRef(false)
  useEffect(() => {
    if (!waiting) return
    if (busy) sawBusyRef.current = true
    else if (sawBusyRef.current) {
      waitingRef.current = false
      sawBusyRef.current = false
      setWaiting(false)
    }
  }, [busy, waiting])
  if (!texName) return null
  const texRel = runDir + "/deliverables/" + texName
  const pdfName = deliverables.find((f) => f === "paper.pdf") || deliverables.find((f) => f.endsWith(".pdf"))
  const availPdf = pdfName ? runDir + "/deliverables/" + pdfName : ""

  function compileViaAgent() {
    if (!onAskAgent || waitingRef.current || busy) return
    waitingRef.current = true
    setWaiting(true)
    const prompt =
      "请编译论文并修复所有编译问题，直到通过（不要只看 exit code，要看 arc_latex_check 的 severity）：\n" +
      "- 目标：" + texRel + "（run 目录：" + runDir + "）\n" +
      "- 用 arc_latex_check 编译体检；compiled / exit 0 ≠ 通过。\n" +
      "- 若缺类文件（如 aaai25.sty）：从对应会议作者包取来放进 deliverables/（本机外网走代理）；" +
      "实在取不到就降级到标准 article 类，并在结论里如实标注。\n" +
      "- 修复 dangling \\ref/\\cite、缺图、缺 \\input、缺 .bib 等硬伤。\n" +
      "- 反复编译直到 severity=PASS（或仅剩 WARN），产出 deliverables/paper.pdf；" +
      "完成后简要告诉我修了什么、最终页数。"
    try {
      onAskAgent(prompt, "请编译论文并修复所有编译问题，直到通过。")
    } catch {
      waitingRef.current = false
      sawBusyRef.current = false
      setWaiting(false)
    }
  }

  return (
    <div className="paper-card">
      <div className="paper-card-head">
        <span className="paper-card-title"><Icon name="filetext" size={14} /> 论文 · {texName}</span>
      </div>
      <div className="paper-actions">
        <button className="pc-btn primary" onClick={compileViaAgent} disabled={!onAskAgent || busy || waiting} aria-busy={waiting} title="把编译+修复交给助手，在对话里执行">
          {waiting ? <><span className="spinner compile-spinner" /> 编译中</> : <><Icon name="code" size={13} /> 编译论文</>}
        </button>
        <button className="pc-btn" onClick={() => availPdf && onOpenPdf(availPdf)} disabled={!availPdf}>大屏</button>
        {availPdf
          ? <a className="pc-btn" href={rawUrl(availPdf)} download>下载 PDF</a>
          : <span className="pc-hint">尚无 PDF，点「编译」交给助手生成</span>}
      </div>
      {waiting && (
        <div className="paper-health">
          <div className="pc-check lvl-info">· 正在由助手编译并修复论文
          </div>
        </div>
      )}
    </div>
  )
}

// 产物目录树的一个节点（递归）。目录可展开/折叠，文件点开预览。
// 缩进走内联 paddingLeft（depth*14），复用 .file-entry 样式；箭头 .tree-arrow 展开态 rotate。
function TreeNode({ entry, depth, expanded, childrenCache, selected, onClick, showInternal }) {
  const isDir = entry.type === "directory"
  const isOpen = isDir && expanded.has(entry.path)
  const kids = isOpen ? childrenCache[entry.path] : null
  return (
    <>
      <div
        className={"file-entry " + (isDir ? "dir " : "") + (selected === entry.path ? "active" : "")}
        style={{ paddingLeft: 8 + depth * 14 }}
        onClick={() => onClick(entry)}
      >
        {isDir ? (
          <span className={"tree-arrow" + (isOpen ? " open" : "")}>▸</span>
        ) : (
          <span className="tree-arrow-spacer" />
        )}
        <span><Icon name={isDir ? "folder" : fileIcon(entry.name)} /></span>
        <span className="tree-name">{entry.name}</span>
        {!isDir && (
          // hover 时右侧浮现下载图标：直接下原文件，不触发选中/预览（stopPropagation）。
          <a
            className="tree-dl"
            href={rawUrl(entry.path)}
            download
            title="下载此文件"
            onClick={(e) => e.stopPropagation()}
          >
            <Icon name="download" size={13} />
          </a>
        )}
      </div>
      {isOpen && kids == null && (
        <div className="file-empty" style={{ paddingLeft: 8 + (depth + 1) * 14, padding: "4px 8px", textAlign: "left" }}>
          加载中…
        </div>
      )}
      {isOpen &&
        kids &&
        kids
          .filter((c) => showInUserFileTree(c, showInternal))
          .map((c) => (
            <TreeNode
              key={c.path}
              entry={c}
              depth={depth + 1}
              expanded={expanded}
              childrenCache={childrenCache}
              selected={selected}
              onClick={onClick}
              showInternal={showInternal}
            />
          ))}
    </>
  )
}

function ResearchPanel({ workspaceDir, uploads, busy, refreshKey, literature, onFocusPaper, onOpenPdf, onOpenImage, onFocusFile, onAskAgent, starredKeys, onToggleStar, onDeepDive, onCollapse }) {
  const [entries, setEntries] = useState([]) // session cwd top-level entries
  const [activeRunDir, setActiveRunDir] = useState("")
  const [stageFiles, setStageFiles] = useState({}) // {planning:[...], experiment:[...], deliverables:[...]}
  const [litArtifacts, setLitArtifacts] = useState({ papers: [], candidates: [], files: {}, diagnostics: [] })
  const [litLoading, setLitLoading] = useState(false)
  // 目录树：expanded=已展开目录 path 集合；childrenCache=每个已展开目录的子项（懒取缓存）。
  const [expanded, setExpanded] = useState(() => new Set())
  const [childrenCache, setChildrenCache] = useState({})
  const [selected, setSelected] = useState(null) // 当前在中栏打开的文件（仅用于树里高亮）
  const [tab, setTab] = useState("files") // files | lit
  const [loaded, setLoaded] = useState(false) // 首次列目录是否已完成（未完成时别显示"（空）"，免闪烁）
  const [err, setErr] = useState("") // 列目录失败（后端未连接等）——区别于"真的空"
  const topLoadSeq = useRef(0)
  const dirLoadSeq = useRef(new Map())
  const stageLoadSeq = useRef(0)
  const refreshEffectReady = useRef(false)
  const runDiscoverySeq = useRef(0)

  // 始终指向最新 expanded，供 refreshKey 刷新时遍历已展开目录（避免异步闭包读到旧值）。
  const expandedRef = useRef(expanded)
  expandedRef.current = expanded

  // 目录优先、同类按名字排序（树每层复用）。
  function sortEntries(list) {
    const a = [...list]
    a.sort((x, y) => {
      if (x.type !== y.type) return x.type === "directory" ? -1 : 1
      return x.name.localeCompare(y.name)
    })
    return a
  }
  function mergeLiveEntries(previous, incoming) {
    if (!busy) return incoming
    const seen = new Set(incoming.map((entry) => entry.path))
    return sortEntries(incoming.concat(previous.filter((entry) => !seen.has(entry.path))))
  }

  // 取某目录一层子项；出错返回 null（区别于"真的空 []"）。
  async function fetchDir(path) {
    try { return sortEntries(await listFiles(path)) } catch (e) { setErr((e && e.message) || "读取失败"); return null }
  }
  // 载入 session cwd 顶层（维护 loaded/err 态）。autoExpand=true 时用后端返回的真实 path
  // 默认展开三阶段目录（后端目录 path 带尾斜杠，直接用 entry.path 匹配，别自己拼 key）。
  async function discoverActiveRun() {
    const seq = ++runDiscoverySeq.current
    if (!workspaceDir) { setActiveRunDir(""); return }
    try {
      const runsRoot = workspaceDir.replace(/\/+$/, "") + "/research-runs"
      const runs = sortEntries(await listFiles(runsRoot))
        .filter((entry) => entry.type === "directory")
      if (seq !== runDiscoverySeq.current) return
      const active = runs.length ? runs[runs.length - 1] : null
      if (!active) {
        if (!busy) setActiveRunDir("")
        return
      }
      setActiveRunDir(active.path)
      const stageEntries = sortEntries(await listFiles(active.path))
      if (seq !== runDiscoverySeq.current) return
      const stages = stageEntries.filter((entry) => entry.type === "directory" && STAGE_DIRS.includes(entry.name))
      setExpanded((previous) => {
        const next = new Set(previous)
        next.add(runsRoot)
        next.add(active.path)
        stages.forEach((entry) => next.add(entry.path))
        return next
      })
      setChildrenCache((cache) => ({ ...cache, [runsRoot]: runs, [active.path]: stageEntries }))
      stages.forEach((entry) => reloadDir(entry.path))
    } catch {
      // Keep the previous valid run while the filesystem is temporarily unavailable.
    }
  }
  useEffect(() => { discoverActiveRun() }, [workspaceDir, refreshKey]) // eslint-disable-line

  async function loadTop(autoExpand) {
    const seq = ++topLoadSeq.current
    if (!workspaceDir) { setEntries([]); setLoaded(true); setErr(false); return }
    setLoaded(false); setErr("")
    const top = await fetchDir(workspaceDir)
    if (seq !== topLoadSeq.current) return
    if (top === null) { setLoaded(true); return }
    setEntries((previous) => mergeLiveEntries(previous, top))
    setLoaded(true)
    if (autoExpand) {
      const stageDirs = top.filter((e) => e.type === "directory" && STAGE_DIRS.includes(e.name))
      setExpanded((previous) => {
        const next = new Set(previous)
        stageDirs.forEach((entry) => next.add(entry.path))
        return next
      })
      stageDirs.forEach((e) => reloadDir(e.path))
    }
  }
  // 强制刷新某目录内容（刷新用；出错落空数组不抛）。
  async function reloadDir(p) {
    const seq = (dirLoadSeq.current.get(p) || 0) + 1
    dirLoadSeq.current.set(p, seq)
    const c = await fetchDir(p)
    if (c === null || dirLoadSeq.current.get(p) !== seq) return
    setChildrenCache((cache) => ({
      ...cache,
      [p]: mergeLiveEntries(cache[p] || [], c),
    }))
  }
  // 懒展开：仅当无缓存才取（避免重复请求）。
  async function loadChildren(p) {
    if (childrenCache[p]) return
    reloadDir(p)
  }
  // 顶层 + 所有已展开目录内容一起刷新（保持展开态，不折叠）。
  function refreshAll() {
    if (!workspaceDir) return
    loadTop(false)
    Array.from(expandedRef.current).forEach((p) => reloadDir(p))
    loadStages()
    if (tab === "lit" && activeRunDir) {
      setLitLoading(true)
      loadLiteratureArtifacts(activeRunDir)
        .then(setLitArtifacts)
        .catch(() => setLitArtifacts({ papers: [], candidates: [], files: {}, diagnostics: [] }))
        .finally(() => setLitLoading(false))
    }
  }
  // 展开/折叠一个目录；首次展开时懒取子项。
  function toggleDir(entry) {
    const p = entry.path
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p)
      else { next.add(p); loadChildren(p) }
      return next
    })
  }
  // 树节点点击：目录 → 展开/折叠；文件 → 直接投中栏大屏（不再在右栏下方内联预览）。
  function onClickEntry(e) {
    if (e.type === "directory") toggleDir(e)
    else if (onFocusFile) { setSelected(e.path); onFocusFile(e.path) }
  }

  // 阶段轨迹:拉三个子目录的文件名（任一目录失败都不能整体抛出，否则阶段全灭）
  async function loadStages() {
    const seq = ++stageLoadSeq.current
    if (!activeRunDir) { setStageFiles({}); return }
    const pairs = await Promise.all(STAGE_DIRS.map(async (d) => {
      try {
        const list = await listFiles(activeRunDir + "/" + d)
        return [d, list.filter((e) => e.type === "file").map((e) => e.name)]
      } catch {
        return [d, null]
      }
    }))
    if (seq !== stageLoadSeq.current) return
    setStageFiles((previous) => Object.fromEntries(pairs.map(([d, names]) => {
      if (names === null) return [d, previous[d] || []]
      if (!busy) return [d, names]
      return [d, Array.from(new Set([...(previous[d] || []), ...names])).sort()]
    })))
  }
  useEffect(() => { loadStages() }, [activeRunDir, refreshKey]) // eslint-disable-line
  useEffect(() => {
    let alive = true
    if (!activeRunDir) { setLitArtifacts({ papers: [], candidates: [], files: {}, diagnostics: [] }); setLitLoading(false); return }
    if (tab !== "lit") return
    setLitLoading(true)
    loadLiteratureArtifacts(activeRunDir)
      .then((x) => { if (alive) setLitArtifacts(x) })
      .catch(() => { if (alive) setLitArtifacts({ papers: [], candidates: [], files: {}, diagnostics: [] }) })
      .finally(() => { if (alive) setLitLoading(false) })
    return () => { alive = false }
  }, [activeRunDir, refreshKey, tab]) // eslint-disable-line
  // session cwd 切换时清理旧会话视图；消息更新不会触发根目录切换。
  useEffect(() => {
    setSelected(null)
    setActiveRunDir("")
    setEntries([]); setStageFiles({})
    setExpanded(new Set()); setChildrenCache({})
    loadTop(true)
  }, [workspaceDir]) // eslint-disable-line
  // 文件刷新（agent 一轮结束/手动刷新）：更新顶层 + 已展开目录内容，保持展开不折叠。
  useEffect(() => {
    if (!refreshEffectReady.current) {
      refreshEffectReady.current = true
      return
    }
    if (!workspaceDir) return
    loadTop(false)
    Array.from(expandedRef.current).forEach((p) => reloadDir(p))
  }, [refreshKey]) // eslint-disable-line

  // 点上传项：一律投中栏大屏（图片/PDF 走各自的大屏入口，其它走通用 onFocusFile）。
  function openUpload(u) {
    const k = fileKind(u.path)
    if (k === "image" && onOpenImage) { onOpenImage(u.path); return }
    if (k === "pdf" && onOpenPdf) { onOpenPdf(u.path); return }
    if (onFocusFile) { setSelected(u.path); onFocusFile(u.path) }
  }

  const curatedLiterature = (litArtifacts && litArtifacts.papers) || []
  const displayLiterature = React.useMemo(() => {
    if (curatedLiterature.length) return curatedLiterature
    return mergeLitPapers(literature || [], (litArtifacts && litArtifacts.candidates) || [])
  }, [literature, litArtifacts, curatedLiterature])
  const litCount = (displayLiterature && displayLiterature.length) || 0

  return (
    <>

      {/* 产物 / 文献 切换 */}
      <div className="rp-tabs">
        <button className={"rp-tab " + (tab === "files" ? "active" : "")} onClick={() => setTab("files")}>产物</button>
        <button className={"rp-tab " + (tab === "lit" ? "active" : "")} onClick={() => setTab("lit")}>
          文献{litCount ? " · " + litCount : ""}{curatedLiterature.length ? " · 已筛选" : litCount ? " · 筛选中" : ""}
        </button>
        {onCollapse && <button className="rp-collapse" title="收起此栏" onClick={onCollapse}><Icon name="chevronRight" size={15} /></button>}
      </div>

      {tab === "lit" ? (
        <>
          <LiteratureWorkflowTrack
            files={litArtifacts.files || {}}
            busy={busy}
            onOpen={(p) => onFocusFile && onFocusFile(p)}
          />
          <DiagnosticArtifacts
            files={litArtifacts.files || {}}
            onOpen={(p) => onFocusFile && onFocusFile(p)}
          />
          {litLoading && <div className="file-empty" style={{ padding: "8px 12px", textAlign: "left" }}>加载文献中…</div>}
          <LiteratureList
            papers={displayLiterature}
            onFocus={onFocusPaper}
            starredKeys={starredKeys}
            onToggleStar={onToggleStar}
            onDeepDive={onDeepDive}
          />
        </>
      ) : (
        <>
          {/* 本次上传始终在最上方；Workspace 根目录固定为当前 session cwd。 */}
          {uploads && uploads.length > 0 && (
            <div className="uploads-box">
              <div className="uploads-head"><Icon name="paperclip" size={13} /> 本次上传（{uploads.length}）</div>
              {uploads.map((u, i) => (
                <div className="upload-item" key={u.path || i} onClick={() => openUpload(u)} title={u.path}>
                  <span className="upload-ic"><Icon name={attIcon(u.mime, u.name)} /></span>
                  <span className="upload-nm">{u.name}</span>
                </div>
              ))}
            </div>
          )}

          {/* Workspace 根固定为 Agent cwd；下载打包的也是整个 cwd。 */}
          <div className="ws-root">
            <span className="ws-root-label"><Icon name="folder" size={18} /> Workspace</span>
            {workspaceDir && (
              <a className="file-dl" href={archiveUrl(workspaceDir)} download title="打包下载整个 workspace（.tar.gz）"><Icon name="download" size={13} /> 下载全部</a>
            )}
          </div>

          {!workspaceDir ? null : (
        <>
          {/* 论文卡：deliverables 有 .tex 时显示编译/大屏/下载 */}
          {(stageFiles.deliverables || []).some((f) => f.endsWith(".tex")) && (
            <PaperCard
              runDir={activeRunDir}
              deliverables={stageFiles.deliverables || []}
              busy={busy}
              onOpenPdf={onOpenPdf}
              onAskAgent={onAskAgent}
            />
          )}

          <div className="file-tree">
            {entries.length === 0 && !loaded && <div className="file-empty">加载中…</div>}
            {entries.length === 0 && loaded && err && (
              <div className="file-empty" title={String(err)}>
                工作区目录读取失败<br />
                <span style={{ fontSize: 12, opacity: 0.75 }}>{String(err).slice(0, 180)}</span>
              </div>
            )}
            {entries.filter((e) => showInUserFileTree(e, false)).map((e) => (
              <TreeNode
                key={e.path}
                entry={e}
                depth={0}
                expanded={expanded}
                childrenCache={childrenCache}
                selected={selected}
                onClick={onClickEntry}
                showInternal={false}
              />
            ))}
          </div>
        </>
          )}
        </>
      )}
    </>
  )
}

// ===================================================================
// App：多会话 + SSE 路由 + session cwd 绑定
// ===================================================================
function clampW(v, lo, hi) { return Math.max(lo, Math.min(hi, v || lo)) }

// ── 中栏多文件分栏工作区：二叉拆分树（任意方向嵌套；能否再拆看每格尺寸，不是全局数） ──────────────────
// Leaf  = { kind:"leaf", id, tabs:[path], active }
// Split = { kind:"split", id, dir:"row"|"col", a, b, ratio }
let _wsId = 0
function wsNewId() { _wsId += 1; return "ws" + _wsId }
function wsLeaf(tabs, active) { return { kind: "leaf", id: wsNewId(), tabs: tabs || [], active: active ?? null } }

function wsFindLeaf(node, id) {
  if (!node) return null
  if (node.kind === "leaf") return node.id === id ? node : null
  return wsFindLeaf(node.a, id) || wsFindLeaf(node.b, id)
}
function wsFirstLeaf(node) {
  if (!node) return null
  return node.kind === "leaf" ? node : (wsFirstLeaf(node.a) || wsFirstLeaf(node.b))
}
function wsFindPath(node, path) {
  // 返回含该 path 的叶子（用于"已开则聚焦"），否则 null
  if (!node) return null
  if (node.kind === "leaf") return node.tabs.includes(path) ? node : null
  return wsFindPath(node.a, path) || wsFindPath(node.b, path)
}
// 用 replacement 替换树中 id=targetId 的节点，返回新树（不可变）
function wsReplace(node, targetId, replacement) {
  if (!node) return node
  if (node.id === targetId) return replacement
  if (node.kind === "leaf") return node
  const a = wsReplace(node.a, targetId, replacement)
  const b = wsReplace(node.b, targetId, replacement)
  return a === node.a && b === node.b ? node : { ...node, a, b }
}
// 删一个叶子：兄弟节点上提替换父 split；删唯一叶 → null。返回 {root, promotedId}
function wsRemoveLeaf(root, leafId) {
  if (!root) return { root: null, promotedId: null }
  if (root.kind === "leaf") return root.id === leafId ? { root: null, promotedId: null } : { root, promotedId: null }
  function walk(node) {
    // 若某 split 的直接子是目标叶 → 返回另一子（上提）
    if (node.kind === "split") {
      if (node.a.kind === "leaf" && node.a.id === leafId) return node.b
      if (node.b.kind === "leaf" && node.b.id === leafId) return node.a
      const a = walk(node.a)
      const b = walk(node.b)
      if (a === node.a && b === node.b) return node
      return { ...node, a, b }
    }
    return node
  }
  const newRoot = walk(root)
  return { root: newRoot, promotedId: (wsFirstLeaf(newRoot) || {}).id || null }
}

// 不设总格数上限、也不设每格最小尺寸下限——想拆多少拆多少，格子小到看不清是用户自己的判断，
// 看不下去了自己会取消分栏（关掉格子/合并回去），不用代码替他把关。

function useWorkspace() {
  const [ws, setWs] = useState({ root: null, activePaneId: null })

  const openFile = useCallback((path) => {
    if (!path) return
    setWs((prev) => {
      if (!prev.root) {
        const leaf = wsLeaf([path], path)
        return { root: leaf, activePaneId: leaf.id }
      }
      // 已在某格 → 聚焦那个格 + 该标签
      const owner = wsFindPath(prev.root, path)
      if (owner) {
        const root = wsReplace(prev.root, owner.id, { ...owner, active: path })
        return { root, activePaneId: owner.id }
      }
      // 否则进活动格（活动格不存在则第一个叶）
      const target = wsFindLeaf(prev.root, prev.activePaneId) || wsFirstLeaf(prev.root)
      if (!target) { const leaf = wsLeaf([path], path); return { root: leaf, activePaneId: leaf.id } }
      const root = wsReplace(prev.root, target.id, { ...target, tabs: [...target.tabs, path], active: path })
      return { root, activePaneId: target.id }
    })
  }, [])

  const split = useCallback((paneId, dir) => {
    setWs((prev) => {
      const leaf = wsFindLeaf(prev.root, paneId)
      if (!leaf) return prev
      const dup = leaf.active ? wsLeaf([leaf.active], leaf.active) : wsLeaf([], null)
      const splitNode = { kind: "split", id: wsNewId(), dir, a: leaf, b: dup, ratio: 0.5 }
      return { root: wsReplace(prev.root, paneId, splitNode), activePaneId: dup.id }
    })
  }, [])
  const splitRight = useCallback((id) => split(id, "row"), [split])
  const splitDown = useCallback((id) => split(id, "col"), [split])

  const closePane = useCallback((paneId) => {
    setWs((prev) => {
      const { root, promotedId } = wsRemoveLeaf(prev.root, paneId)
      const active = prev.activePaneId === paneId ? promotedId : prev.activePaneId
      return { root, activePaneId: root ? (active || promotedId) : null }
    })
  }, [])

  const closeTab = useCallback((paneId, path) => {
    setWs((prev) => {
      const leaf = wsFindLeaf(prev.root, paneId)
      if (!leaf) return prev
      const idx = leaf.tabs.indexOf(path)
      const tabs = leaf.tabs.filter((p) => p !== path)
      if (tabs.length === 0) {
        // 空格 → 回收
        const { root, promotedId } = wsRemoveLeaf(prev.root, paneId)
        const active = prev.activePaneId === paneId ? promotedId : prev.activePaneId
        return { root, activePaneId: root ? (active || promotedId) : null }
      }
      let active = leaf.active
      if (active === path) active = tabs[Math.min(idx, tabs.length - 1)] // 右邻优先，否则左邻
      return { root: wsReplace(prev.root, paneId, { ...leaf, tabs, active }), activePaneId: prev.activePaneId }
    })
  }, [])

  const setActivePane = useCallback((paneId) => setWs((prev) => (prev.activePaneId === paneId ? prev : { ...prev, activePaneId: paneId })), [])
  const setActiveTab = useCallback((paneId, path) => setWs((prev) => {
    const leaf = wsFindLeaf(prev.root, paneId)
    if (!leaf) return prev
    return { root: wsReplace(prev.root, paneId, { ...leaf, active: path }), activePaneId: paneId }
  }), [])
  const setRatio = useCallback((splitId, ratio) => setWs((prev) => {
    const r = Math.max(0.15, Math.min(0.85, ratio))
    function mapRatio(node) {
      if (!node || node.kind === "leaf") return node
      if (node.id === splitId) return { ...node, ratio: r }
      const a = mapRatio(node.a), b = mapRatio(node.b)
      return a === node.a && b === node.b ? node : { ...node, a, b }
    }
    return { ...prev, root: mapRatio(prev.root) }
  }), [])
  const reset = useCallback(() => setWs({ root: null, activePaneId: null }), [])

  return { workspace: ws, openFile, splitRight, splitDown, closePane, closeTab, setActivePane, setActiveTab, setRatio, reset }
}

// ── 工作区渲染：递归 SplitNode/Pane + 可拖拽 Divider ─────────────
function wsBasename(p) { return (p || "").split("/").pop() }

function WsDivider({ dir, onDragMove, onDragEnd }) {
  // dir=row 竖直分隔条(左右拖)，col 水平分隔条(上下拖)。
  // 拖动中只用 onDragMove 直改两侧格子的 DOM style.flexGrow（不进 React state），松手
  // 才用 onDragEnd 提交一次最终比例到 state——否则每个 mousemove 都 setRatio 触发整棵
  // 子树（含大屏里渲染的重内容）重渲染，渲染跟不上鼠标事件就会出现"松手了还在滑"的卡顿。
  // 关键：格子里可能是 <iframe>(PDF预览)，iframe 有自己的事件目标，鼠标划过它时原生会把
  // mousemove 派给 iframe 内部而不是外层 window，导致拖拽时"跳一下才跟上"、松手后残留的
  // 一帧还停在旧位置才补上。解法：mousedown 时插入一个盖满全屏的透明捕获层（比 iframe 更
  // 上层），所有 mousemove/mouseup 都只发生在这个捕获层上，iframe/其它格子完全收不到事件。
  function down(e) {
    e.preventDefault(); e.stopPropagation()
    document.body.classList.add("ws-resizing")
    const catcher = document.createElement("div")
    catcher.className = "ws-drag-catcher"
    catcher.style.cursor = dir === "row" ? "col-resize" : "row-resize"
    document.body.appendChild(catcher)
    const move = (ev) => onDragMove(dir === "row" ? ev.clientX : ev.clientY)
    const up = () => {
      document.body.classList.remove("ws-resizing")
      catcher.removeEventListener("mousemove", move)
      catcher.removeEventListener("mouseup", up)
      document.body.removeChild(catcher)
      onDragEnd()
    }
    catcher.addEventListener("mousemove", move)
    catcher.addEventListener("mouseup", up)
  }
  return <div className={"ws-divider " + dir} onMouseDown={down} />
}

function WsSplitNode({ node, actions, activeId }) {
  const ref = useRef(null)
  const slotARef = useRef(null)
  const slotBRef = useRef(null)
  const liveRatioRef = useRef(node.ratio)
  function onDragMove(coord) {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const raw = node.dir === "row" ? (coord - r.left) / r.width : (coord - r.top) / r.height
    const ratio = Math.max(0.15, Math.min(0.85, raw))
    liveRatioRef.current = ratio
    if (slotARef.current) slotARef.current.style.flexGrow = ratio
    if (slotBRef.current) slotBRef.current.style.flexGrow = 1 - ratio
  }
  function onDragEnd() {
    actions.setRatio(node.id, liveRatioRef.current)
  }
  return (
    <div className={"ws-split " + node.dir} ref={ref}>
      <div ref={slotARef} className="ws-slot" style={{ flexGrow: node.ratio, flexBasis: 0 }}>
        <WsNode node={node.a} actions={actions} activeId={activeId} />
      </div>
      <WsDivider dir={node.dir} onDragMove={onDragMove} onDragEnd={onDragEnd} />
      <div ref={slotBRef} className="ws-slot" style={{ flexGrow: 1 - node.ratio, flexBasis: 0 }}>
        <WsNode node={node.b} actions={actions} activeId={activeId} />
      </div>
    </div>
  )
}

function WsPane({ leaf, actions, active }) {
  return (
    <div className={"ws-pane" + (active ? " active" : "")} onMouseDown={() => actions.setActivePane(leaf.id)}>
      <div className="ws-tabbar">
        {leaf.tabs.map((p) => (
          <div
            key={p}
            className={"ws-tab" + (p === leaf.active ? " active" : "")}
            onClick={() => actions.setActiveTab(leaf.id, p)}
            title={p}
          >
            <span><Icon name={fileIcon(wsBasename(p))} /></span>
            <span className="ws-tab-nm">{wsBasename(p)}</span>
            <button className="ws-tab-x" title="关闭标签" onClick={(e) => { e.stopPropagation(); actions.closeTab(leaf.id, p) }}><Icon name="x" size={12} /></button>
          </div>
        ))}
        <span className="ws-tab-spacer" />
        <button className="ws-split-btn" title="向右拆分" aria-label="向右拆分" onClick={(e) => { e.stopPropagation(); actions.splitRight(leaf.id) }}><Icon name="splitRight" size={19} className="ws-op-icon" /></button>
        <button className="ws-split-btn" title="向下拆分" aria-label="向下拆分" onClick={(e) => { e.stopPropagation(); actions.splitDown(leaf.id) }}><Icon name="splitDown" size={19} className="ws-op-icon" /></button>
        <button className="ws-split-btn" title="关闭此格" aria-label="关闭此格" onClick={(e) => { e.stopPropagation(); actions.closePane(leaf.id) }}><Icon name="panelClose" size={19} className="ws-op-icon" /></button>
      </div>
      <div className="ws-pane-body">
        {leaf.active ? <FileView key={leaf.active} path={leaf.active} /> : <div className="file-empty">空格 — 从右侧「大屏」开文件</div>}
      </div>
    </div>
  )
}

function WsNode({ node, actions, activeId }) {
  if (!node) return null
  if (node.kind === "split") return <WsSplitNode node={node} actions={actions} activeId={activeId} />
  return <WsPane leaf={node} actions={actions} active={node.id === activeId} />
}

function WorkspaceGrid({ ws, actions }) {
  if (!ws.root) return null
  return <div className="ws-grid"><WsNode node={ws.root} actions={actions} activeId={ws.activePaneId} /></div>
}

// ②产物区「进程」视图：从 assistant 消息里拍平工具调用成一条实时时间线（像 IDE 运行日志）。
// 顶部若有 todowrite 计划则展示为任务清单。数据全来自 messages，随 SSE 流式增长。
function lastTodos(messages) {
  let todos = null
  for (const m of messages || []) {
    if (!m.info || m.info.role !== "assistant") continue
    for (const p of m.parts || []) {
      if (p.type === "tool" && p.tool === "todowrite") {
        const t = p.state && p.state.input && p.state.input.todos
        if (Array.isArray(t) && t.length) todos = t
      }
    }
  }
  return todos
}
// 从工具输入里抽一句「目标」，让进程时间线读起来是「执行命令 · python train.py」而非光秃秃的动作名。
function toolDetail(tool, input) {
  const inp = input || {}
  const base = (p) => String(p || "").split("/").pop()
  // 命令/路径类详情里的 research-runs/ 同样按显示层遮罩成 workspace/。
  const raw = (() => {
    switch (tool) {
      case "read": case "write": case "edit": return base(inp.filePath || inp.path || inp.file)
      case "bash": return String(inp.command || inp.cmd || "").replace(/\s+/g, " ").slice(0, 80)
      case "list": case "glob": return String(inp.path || inp.pattern || "")
      case "grep": return String(inp.pattern || inp.query || "")
      case "arc_search_literature": return String(inp.query || inp.q || "")
      case "arc_run_experiment": return inp.is_async ? "后台实验" : ""
      case "skill": return String(inp.name || "")
      default: return ""
    }
  })()
  return maskPath(raw)
}
function hasProcessPayload(value) {
  if (value == null) return false
  if (typeof value === "string") return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === "object") return Object.keys(value).length > 0
  return true
}
// 进程时间线的一行：默认收起，点击展开看该步的输入/输出（复用 pretty，与旧对话工具卡片一致）。
// icon/label/status 外观保持不变；只是加了可展开的详情体。
function ProcRow({ e }) {
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(Date.now())
  const input = hasProcessPayload(e.input) ? e.input : null
  const output = hasProcessPayload(e.output) ? e.output : null
  const running = e.status === "running"
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  const startedAt = Number(e.startedAt || 0)
  const elapsed = running && startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : null
  const hasBody = input != null || output != null
  return (
    <div className={"proc-row " + e.status + (open ? " open" : "")}>
      <div className="proc-row-head" onClick={() => hasBody && setOpen((o) => !o)} style={{ cursor: hasBody ? "pointer" : "default" }}>
        <span className="proc-ic"><Icon name={e.icon} size={15} /></span>
        <span className="proc-label">{e.label}</span>
        {e.detail && <span className="proc-detail" title={e.detail}>{e.detail}</span>}
        {elapsed != null && <span className="proc-elapsed">{elapsed}s</span>}
        <span className="proc-status">
          {e.status === "completed" ? <Icon name="check" size={14} />
            : (e.status === "running" || e.status === "pending") ? <span className="spinner" />
            : e.status === "error" ? <Icon name="x" size={14} />
            : e.status === "interrupted" ? <span title="已中断（未收到结束状态）"><Icon name="x" size={13} /></span> : ""}
        </span>
        {hasBody && <span className="proc-caret"><Icon name={open ? "chevronDown" : "chevronRight"} size={13} /></span>}
      </div>
      {open && hasBody && (
        <div className="proc-body">
          {input != null && (
            <><div className="label">输入</div><pre>{pretty(input)}</pre></>
          )}
          {output != null && (
            <><div className="label">{e.status === "error" ? "错误" : "输出"}</div><pre>{pretty(output)}</pre></>
          )}
        </div>
      )}
    </div>
  )
}
function ProcessLog({ messages, busy, sessionID, runtimeStatus }) {
  const [externalJobs, setExternalJobs] = useState([])
  const [planOpen, setPlanOpen] = useState(false)
  useEffect(() => { setPlanOpen(false) }, [sessionID])
  useEffect(() => {
    if (!sessionID) {
      setExternalJobs([])
      return
    }
    let active = true
    const load = async () => {
      try {
        const r = await fetch("/process/progress?sessionID=" + encodeURIComponent(sessionID))
        const data = r.ok ? await r.json() : null
        if (active && data && Array.isArray(data.jobs)) setExternalJobs(data.jobs)
      } catch { /* process panel remains usable when the backend is reconnecting */ }
    }
    load()
    const timer = setInterval(load, 10000)
    return () => { active = false; clearInterval(timer) }
  }, [sessionID])
  const todos = lastTodos(messages)
  const completedTodos = (todos || []).filter((t) => t.status === "completed").length
  const currentTodo = (todos || []).find((t) => t.status === "in_progress") || (todos || []).find((t) => t.status !== "completed" && t.status !== "cancelled")
  const events = []
  const msgs = messages || []
  for (let mi = 0; mi < msgs.length; mi++) {
    const m = msgs[mi]
    if (!m.info || m.info.role !== "assistant") continue
    const isLastMsg = mi === msgs.length - 1
    for (const p of m.parts || []) {
      if (p.type !== "tool") continue
      if (p.tool === "todowrite" || p.tool === "todoread") continue // 计划单独在顶部展示
      const state = p.state || {}
      const input = state.input
      const meta = toolMeta(p.tool, input)
      const output = state.output != null ? state.output : state.error
      // 状态收敛：直接取 state.status 会让「终态 SSE 丢失」的工具永远卡 running/spinner。
      // question 工具尤其常丢终态（见文件顶部注释）。两条兜底，与 ToolCall 的孤儿判定一致：
      //   ① question 只要已拿到结构化答案或可解析的回答 output → 视作完成；
      //   ② 会话已不 busy（idle），或本条不是最后一条消息，却仍停在 running/pending → 是被遗弃的
      //      孤儿（后端没补终态），按已中断收尾，绝不再无限转圈。
      let status = state.status || ""
      const answered = p.tool === "question" && !!answeredQuestionEcho(p)
      const orphan = (status === "running" || status === "pending") && (!busy || !isLastMsg)
      if (answered) status = "completed"
      else if (orphan) status = "interrupted"
      events.push({ id: p.id, icon: meta.icon, label: meta.label, detail: toolDetail(p.tool, input), status, input, output, startedAt: state.time && (state.time.start || state.time.created) })
    }
  }
  for (const job of externalJobs) {
    const p = job && job.progress
    if (!p) continue
    const state = String(job.state || p.state || "running")
    events.push({
      id: "process-" + job.job_id + "-" + String(p.updated_at || ""),
      kind: "experiment",
      icon: ["failed", "timed_out", "cancelled", "aborted"].includes(state) ? "x" : state === "done" ? "check" : "clock",
      label: "实验进度",
      detail: [job.job_id, p.elapsed ? "已跑 " + p.elapsed : "", p.reason || ""].filter(Boolean).join(" · "),
      status: state === "failed" || state === "timed_out" ? "error"
        : state === "cancelled" || state === "aborted" ? "interrupted"
        : state === "done" ? "completed" : "running",
      input: null,
      output: p.tail || p.reason || "",
      timeMs: Number(p.updated_at || job.updated_at || 0),
    })
  }
  const experimentEvents = events.filter((e) => e.kind === "experiment")
  const latestExperiment = experimentEvents[experimentEvents.length - 1]
  const visibleEvents = events.filter((e) => e.kind !== "experiment")
  const scrollRef = useRef(null)
  const activeTool = visibleEvents.some((e) => e.status === "running" || e.status === "pending")
  const showRuntime = runtimeStatus && (runtimeStatus.type === "retry" || runtimeStatus.type === "error" || !activeTool)
  const runtimeTitle = runtimeStatus && runtimeStatus.type === "retry"
    ? `第 ${runtimeStatus.attempt || 1} 次重试 · ${runtimeStatus.message || "模型服务暂时不可用"}`
    : runtimeStatus && runtimeStatus.type === "error" ? (runtimeStatus.message || "模型调用失败")
    : runtimeStatus && runtimeStatus.type === "permission" ? "等待你确认权限请求"
    : runtimeStatus && runtimeStatus.type === "question" ? "等待你回答 Agent 的问题"
    : "等待模型返回下一步"
  // 黏底跟随：同对话区，用户上滑看历史时不再被强行拽回底部（详见 Chat 的 stickRef）。
  const stickRef = useRef(true)
  function onScroll() {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 80
  }
  useEffect(() => { const el = scrollRef.current; if (el && stickRef.current) el.scrollTop = el.scrollHeight }, [events.length, busy])
  return (
    <div className="process-log" ref={scrollRef} onScroll={onScroll}>
      {showRuntime && (
        <div className={"proc-exp-card " + (runtimeStatus.type === "error" ? "error" : "running")}>
          <div className="proc-exp-head">
            <span>
              <Icon name={runtimeStatus.type === "retry" ? "clock" : runtimeStatus.type === "error" ? "x" : "bolt"} size={14} />
              {runtimeStatus.type === "retry" ? " 模型请求重试" : runtimeStatus.type === "error" ? " 模型调用异常" : runtimeStatus.type === "permission" || runtimeStatus.type === "question" ? " 等待用户操作" : " Agent 状态"}
            </span>
          </div>
          <div className="proc-exp-title">{runtimeTitle}</div>
        </div>
      )}
      {todos && todos.length > 0 && (
        <div className="proc-plan">
          <button type="button" className="proc-plan-head" onClick={() => setPlanOpen((value) => !value)}>
            <span><Icon name="layers" size={13} /> 任务进度 {completedTodos}/{todos.length}</span>
            <Icon name={planOpen ? "chevronDown" : "chevronRight"} size={13} />
          </button>
          {!planOpen && currentTodo && <div className="proc-plan-current">{currentTodo.content}</div>}
          {planOpen && todos.map((t, i) => (
            <div className={"proc-plan-item " + (t.status || "")} key={i}>
              <span className="proc-plan-mark"><Icon name={t.status === "completed" ? "check" : t.status === "in_progress" ? "play" : t.status === "cancelled" ? "x" : "dot"} size={13} /></span>
              <span className="proc-plan-text">{t.content}</span>
            </div>
          ))}
        </div>
      )}
      {latestExperiment && (
        <div className={"proc-exp-card " + latestExperiment.status}>
          <div className="proc-exp-head">
            <span><Icon name={latestExperiment.icon} size={14} /> 实验状态</span>
            {latestExperiment.timeMs ? <span>{relTime(latestExperiment.timeMs)}</span> : null}
          </div>
          <div className="proc-exp-title">{latestExperiment.detail}</div>
          <div className="proc-exp-body">{String(latestExperiment.output || "").split("\n").slice(-4).join("\n")}</div>
        </div>
      )}
      {visibleEvents.length === 0 && !latestExperiment ? (
        <div className="file-empty" style={{ padding: 24 }}>
          还没有执行轨迹。<br />发一条指令后，agent 的每一步（检索/实验/核验/写作…）会在这里实时显示。
        </div>
      ) : (
        visibleEvents.map((e) => <ProcRow key={e.id} e={e} />)
      )}
    </div>
  )
}
// ②产物区外壳：页签（进程 / 工作区）+ 内容。工作区视图承载现有四分框(WorkspaceGrid)与文献大屏。
function ProductsPane({ messages, busy, sessionID, runtimeStatus, focusPaper, onCloseFocus, workspace, wsActions, view, onView }) {
  const hasFiles = !!(workspace && workspace.root)
  return (
    <div className="products-pane">
      <div className="products-tabs">
        <button className={"prod-tab " + (view === "process" ? "active" : "")} onClick={() => onView("process")}><Icon name="bolt" size={13} /> 进程</button>
        <button className={"prod-tab " + (view === "files" ? "active" : "")} onClick={() => onView("files")}><Icon name="layers" size={13} /> 工作区</button>
      </div>
      <div className="products-body">
        {view === "process" ? (
          <ProcessLog messages={messages} busy={busy} sessionID={sessionID} runtimeStatus={runtimeStatus} />
        ) : focusPaper ? (
          <PaperFocus paper={focusPaper} onClose={onCloseFocus} />
        ) : hasFiles ? (
          <WorkspaceGrid ws={workspace} actions={wsActions} />
        ) : (
          <div className="file-empty" style={{ padding: 24 }}>点右侧「工作区」目录树里的文件，在这里打开预览。</div>
        )}
      </div>
    </div>
  )
}

function ProjectSwitcher({ projects, curProj, curProjName, unarchivedId, onSelect, onOpenAll }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="proj-switch">
      <div className="proj-cur" onClick={() => setOpen((v) => !v)} title="切换当前项目">
        <Icon name={curProj === unarchivedId ? "chat" : "folder"} size={14} />
        <span className="proj-cur-name">{curProjName}</span>
        <span className="proj-cur-car">▾</span>
      </div>
      {open && (
        <div className="proj-menu">
          <div className="proj-menu-item accent" onClick={() => { setOpen(false); onOpenAll() }}>全部项目 · 新建 / 管理</div>
          {projects.length > 0 && <div className="proj-menu-sep" />}
          {projects.map((p) => (
            <div
              key={p.id}
              className={"proj-menu-item" + (p.id === curProj ? " cur" : "")}
              onClick={() => { setOpen(false); onSelect(p.id) }}
            >{p.name}</div>
          ))}
          <div className="proj-menu-sep" />
          <div
            className={"proj-menu-item dim" + (curProj === unarchivedId ? " cur" : "")}
            onClick={() => { setOpen(false); onSelect(unarchivedId) }}
          >未归档对话</div>
        </div>
      )}
    </div>
  )
}

function NewProjectModal({ projects, onCancel, onCreate }) {
  const [name, setName] = useState("")
  const [files, setFiles] = useState([])
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [progress, setProgress] = useState(null)
  const [err, setErr] = useState("")
  const inputRef = useRef(null)
  const dirRef = useRef(null)
  const abortRef = useRef(null)
  const duplicateName = projectNameExists(projects, name)
  function addFileList(fl, { replace = false } = {}) {
    const arr = Array.from(fl || []).filter((f) => f && f.name).map((f) => ({
      file: f,
      name: f.webkitRelativePath || f.name,
      size: f.size,
      mime: f.type || "application/octet-stream",
    }))
    if (arr.length) setFiles((prev) => replace ? arr : prev.concat(arr))
  }
  async function submit() {
    const nm = name.trim()
    if (!nm || busy || duplicateName) return
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setBusy(true); setCancelling(false); setErr("")
    setProgress(files.length ? { done: 0, total: files.length } : null)
    try {
      await onCreate(nm, files, {
        signal: ctrl.signal,
        onProgress: (done, total) => setProgress({ done, total }),
      })
      setBusy(false); setProgress(null); abortRef.current = null
      onCancel()
    } catch (e) {
      abortRef.current = null
      if (e && e.name === "AbortError") {
        setBusy(false); setCancelling(false); setProgress(null)
        onCancel()
        return
      }
      setErr((e && e.message) || String(e || "创建失败"))
      setBusy(false); setCancelling(false)
    }
  }
  function cancel() {
    if (busy) {
      setCancelling(true)
      if (abortRef.current) abortRef.current.abort()
      return
    }
    onCancel()
  }
  const totalSize = files.reduce((s, f) => s + (f.size || 0), 0)
  return (
    <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask") onCancel() }}>
      <div className="np-modal">
        <div className="np-title">新建项目</div>
        <div className="np-sub">可上传文件或文件夹作为项目初始输入，创建时会保留目录结构。</div>
        <label className="np-label">项目名称 *</label>
        <input
          className={"np-input" + (duplicateName ? " invalid" : "")}
          value={name}
          autoFocus
          placeholder="如：GNN 风阻预测"
          onChange={(e) => { setName(e.target.value); setErr("") }}
          onKeyDown={(e) => { if (e.key === "Enter") submit() }}
          disabled={busy}
        />
        {duplicateName && <div className="np-error">已存在同名项目，请使用其他名称。</div>}
        <label className="np-label">初始内容（可选）</label>
        <div
          className={"np-drop" + (drag ? " on" : "")}
          onClick={() => !busy && inputRef.current && inputRef.current.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault(); setDrag(false)
            if (e.dataTransfer && e.dataTransfer.files) addFileList(e.dataTransfer.files)
          }}
        >
          <div className="np-drop-main">点击选择文件，或拖拽文件到此</div>
          <label
            className={"np-pick" + (busy ? " disabled" : "")}
            onClick={(e) => {
              e.stopPropagation()
              if (busy) e.preventDefault()
              else setErr("")
            }}
          >
            选择文件夹开启工作台
            <input ref={dirRef} className="np-hidden-file" type="file" webkitdirectory="" directory="" multiple onChange={(e) => { addFileList(e.target.files, { replace: true }); e.target.value = "" }} disabled={busy} />
          </label>
          <input ref={inputRef} className="np-hidden-file" type="file" multiple onChange={(e) => { addFileList(e.target.files); e.target.value = "" }} disabled={busy} />
        </div>
        {files.length > 0 && (
          <div className="np-files">
            <div className="np-files-head">{files.length} 个文件 · {fmtSize(totalSize)}<span className="np-files-clear" onClick={() => setFiles([])}>清空</span></div>
            {files.slice(0, 8).map((f, i) => (
              <div className="np-file" key={i}><span className="np-file-nm">{f.name}</span><span className="np-file-sz">{fmtSize(f.size)}</span></div>
            ))}
            {files.length > 8 && <div className="np-file-more">还有 {files.length - 8} 个文件未展示</div>}
          </div>
        )}
        {busy && progress && (
          <div className="np-progress">{cancelling ? "正在取消上传…" : `上传中 ${progress.done} / ${progress.total}`}</div>
        )}
        {err && !duplicateName && <div className="np-error">{err}</div>}
        <div className="np-acts">
          <button className="np-btn" onClick={cancel} disabled={cancelling}>{cancelling ? "取消中…" : "取消"}</button>
          <button className="np-btn primary" disabled={!name.trim() || duplicateName || busy} onClick={submit}>{busy ? "上传中…" : "创建并进入"}</button>
        </div>
      </div>
    </div>
  )
}

function ProjectsHome({ projects, sessProj, sessions, unarchivedId, onOpenProject, onOpenUnarchived, onOpenSession, onNewProject, onRename, onDelete }) {
  const [menuFor, setMenuFor] = useState(null)
  const [renameTarget, setRenameTarget] = useState(null)
  const [renameValue, setRenameValue] = useState("")
  const [deleteTarget, setDeleteTarget] = useState(null)
  useEffect(() => {
    const onDoc = () => setMenuFor(null)
    window.addEventListener("mousedown", onDoc)
    window.addEventListener("blur", onDoc)
    return () => {
      window.removeEventListener("mousedown", onDoc)
      window.removeEventListener("blur", onDoc)
    }
  }, [])
  const countOf = (pid) => (sessions || []).filter((s) => (sessProj[s.id] || unarchivedId) === pid).length
  const unarchN = countOf(unarchivedId)
  const projectNameOf = (pid) => pid === unarchivedId ? "未归档对话" : ((projects || []).find((p) => p.id === pid) || {}).name || "未归档对话"
  const recentSessions = [...(sessions || [])]
    .sort((a, b) => sessionTimeMs(b) - sessionTimeMs(a))
    .slice(0, 6)
  function openRename(p) {
    setMenuFor(null)
    setRenameTarget(p)
    setRenameValue(p.name || "")
  }
  function confirmRename() {
    const p = renameTarget
    const name = renameValue.trim()
    if (!p || !name) return
    onRename(p, name)
    setRenameTarget(null)
  }
  function openDelete(p) {
    setMenuFor(null)
    setDeleteTarget(p)
  }
  function confirmDelete() {
    const p = deleteTarget
    if (!p) return
    onDelete(p)
    setDeleteTarget(null)
  }
  return (
    <div className="project-home-screen">
      <div className="ph-wrap">
        <div className="ph-head">
          <span className="ph-title">全部项目</span>
          <span className="ph-count">{projects.length}</span>
          <span className="ph-acts">
            <button className="ph-btn" onClick={onOpenUnarchived}>临时对话</button>
          </span>
        </div>
        <div className="ph-sub">研究以项目为单位沉淀。已有会话先进入「未归档对话」，后续可移入正式项目。</div>
        <div className="ph-grid">
          <div className="ph-card ph-new" onClick={onNewProject}>
            <div className="ph-new-plus"><Icon name="plus" size={26} /></div>
            <div className="ph-new-lb">新建项目</div>
          </div>
          {projects.map((p) => (
            <div key={p.id} className="ph-card" onClick={() => onOpenProject(p.id)}>
              <button
                type="button"
                className="ph-card-dots"
                title="更多操作"
                onClick={(e) => { e.stopPropagation(); setMenuFor((cur) => cur === p.id ? null : p.id) }}
              >···</button>
              {menuFor === p.id && (
                <div className="ph-menu" onMouseDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                  <button className="ph-menu-item" onClick={() => openRename(p)}><Icon name="edit" size={13} /> 重命名</button>
                  <button className="ph-menu-item danger" onClick={() => openDelete(p)}><Icon name="trash" size={13} /> 删除</button>
                </div>
              )}
              <div className="ph-card-nm"><Icon name="folder" size={15} /> {p.name}</div>
              <div className="ph-card-meta">{countOf(p.id)} 会话</div>
            </div>
          ))}
          <div className="ph-card ph-unarch" onClick={onOpenUnarchived}>
            <div className="ph-card-nm"><Icon name="chat" size={15} /> 未归档对话</div>
            <div className="ph-card-meta">{unarchN} 条 · 可移入项目</div>
          </div>
        </div>
        <div className="ph-recent">
          <div className="ph-section-head">
            <span>最近对话</span>
            <span className="ph-section-count">{recentSessions.length}</span>
          </div>
          {recentSessions.length === 0 ? (
            <div className="ph-recent-empty">还没有对话</div>
          ) : (
            <div className="ph-recent-list">
              {recentSessions.map((s) => {
                const pid = sessProj[s.id] || unarchivedId
                return (
                  <div className="ph-recent-item" key={s.id} onClick={() => onOpenSession(s.id)}>
                    <div className="ph-recent-main">
                      <span className="ph-recent-title">{s.title || "未命名对话"}</span>
                      <span className="ph-recent-project"><Icon name={pid === unarchivedId ? "chat" : "folder"} size={12} /> {projectNameOf(pid)}</span>
                    </div>
                    <time className="ph-recent-time">{relTime(sessionTimeMs(s))}</time>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
      {renameTarget && (
        <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask") setRenameTarget(null) }}>
          <div className="np-modal proj-modal">
            <div className="np-title">重命名项目</div>
            <div className="np-sub">修改项目名称，不影响会话和文献归属。</div>
            <label className="np-label">项目名称</label>
            <input
              className="np-input"
              value={renameValue}
              autoFocus
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") confirmRename() }}
            />
            <div className="np-acts">
              <button className="np-btn" onClick={() => setRenameTarget(null)}>取消</button>
              <button className="np-btn primary" disabled={!renameValue.trim()} onClick={confirmRename}>保存</button>
            </div>
          </div>
        </div>
      )}
      {deleteTarget && (
        <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask") setDeleteTarget(null) }}>
          <div className="np-modal proj-modal">
            <div className="np-title">删除项目</div>
            <div className="np-sub">删除「{deleteTarget.name}」？项目下会话会回到未归档对话。</div>
            <div className="np-acts">
              <button className="np-btn" onClick={() => setDeleteTarget(null)}>取消</button>
              <button className="np-btn danger" onClick={confirmDelete}>删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function App() {
  const [sessions, setSessions] = useState([]) // [{id, title}]
  const [currentID, setCurrentID] = useState(null)
  const initialProjectStateRef = useRef({
    projects: loadProjects(),
    sessProj: loadSessProj(),
    curProj: loadCurProj(),
    projFiles: loadProjFiles(),
    paperProj: loadPaperProj(),
    sessionTitles: loadSessionTitles(),
    sessionMeta: loadSessionMeta(),
  })
  const [projects, setProjects] = useState(initialProjectStateRef.current.projects) // [{id, name, createdAt, updatedAt}]
  const [sessProj, setSessProj] = useState(initialProjectStateRef.current.sessProj) // {sessionId: projectId}
  const [curProj, setCurProj] = useState(initialProjectStateRef.current.curProj) // 当前项目（含 UNARCHIVED）
  const [projView, setProjView] = useState(() => {
    try {
      const v = sessionStorage.getItem("famou.projView")
      return v == null ? true : v === "1"
    } catch { return true }
  })
  const [showNewProj, setShowNewProj] = useState(false)
  const [projFiles, setProjFiles] = useState(initialProjectStateRef.current.projFiles) // {projectId: [{name,size}]}
  const [paperProj, setPaperProj] = useState(initialProjectStateRef.current.paperProj) // 预留：文献按 project 归属
  const [sessionTitles, setSessionTitles] = useState(initialProjectStateRef.current.sessionTitles) // {sessionId: title}
  const [sessionMeta, setSessionMeta] = useState(initialProjectStateRef.current.sessionMeta) // {sessionId: {title,directory,createdAt,updatedAt}}
  const [projectStateLoaded, setProjectStateLoaded] = useState(false)
  const projectStateRef = useRef(initialProjectStateRef.current)
  const sessionTitlesRef = useRef(initialProjectStateRef.current.sessionTitles)
  useEffect(() => {
    projectStateRef.current = { projects, sessProj, curProj, projFiles, paperProj, sessionTitles, sessionMeta }
  }, [projects, sessProj, curProj, projFiles, paperProj, sessionTitles, sessionMeta])
  useEffect(() => {
    sessionTitlesRef.current = sessionTitles
  }, [sessionTitles])
  useEffect(() => {
    try { sessionStorage.setItem("famou.projView", projView ? "1" : "0") } catch {}
  }, [projView])
  useEffect(() => {
    ;(async () => {
      const remote = await loadProjectState()
      if (!remote) return
      setProjects(remote.projects || [])
      setSessProj(remote.sessProj || {})
      setCurProj(remote.curProj || UNARCHIVED)
      setProjFiles(remote.projFiles || {})
      setPaperProj(remote.paperProj || {})
      setSessionTitles(remote.sessionTitles || {})
      setSessionMeta(remote.sessionMeta || {})
      setSessions((prev) => applySessionTitleOverrides(prev, remote.sessionTitles || {}))
      projectStateRef.current = {
        projects: remote.projects || [],
        sessProj: remote.sessProj || {},
        curProj: remote.curProj || UNARCHIVED,
        projFiles: remote.projFiles || {},
        paperProj: remote.paperProj || {},
        sessionTitles: remote.sessionTitles || {},
        sessionMeta: remote.sessionMeta || {},
      }
      sessionTitlesRef.current = remote.sessionTitles || {}
      setProjectStateLoaded(true)
    })()
  }, [])
  useEffect(() => {
    if (!projectStateLoaded) return
    const state = { projects, sessProj, curProj, projFiles, paperProj, sessionTitles, sessionMeta }
    saveProjects(projects)
    saveSessProj(sessProj)
    saveCurProj(curProj)
    saveProjFiles(projFiles)
    savePaperProj(paperProj)
    saveSessionTitles(sessionTitles)
    saveSessionMeta(sessionMeta)
    const t = setTimeout(() => { saveProjectState(state) }, 150)
    return () => clearTimeout(t)
  }, [projectStateLoaded, projects, sessProj, curProj, projFiles, paperProj, sessionTitles, sessionMeta])
  const [msgsBySession, setMsgsBySession] = useState({}) // {sid: Message[]}
  const [busySessions, setBusySessions] = useState({}) // {sid: bool}
  const [runtimeBySession, setRuntimeBySession] = useState({}) // 仅记录 OpenCode 实时事件确认的运行状态
  const runtimeBySessionRef = useRef({})
  runtimeBySessionRef.current = runtimeBySession
  const [connected, setConnected] = useState(false)
  const [sessionRestoreReady, setSessionRestoreReady] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)
  const [sessionCreateError, setSessionCreateError] = useState("")
  const creatingSessionRef = useRef(false)
  // 当前选中模型（持久化在 localStorage）。空串=尚未初始化，启动解析默认模型后填上。
  const [modelID, setModelID] = useState(() => {
    try { return canonicalModelKey(localStorage.getItem(MODEL_LS_KEY) || "") } catch { return "" }
  })
  // 可选模型列表：启动从 opencode /config 动态读（见 resolveModel/parseModelList），先给兜底。
  const [models, setModels] = useState(MODELS_FALLBACK)
  // 是否显示模型选择器：仅「正常自用」(famou-scientist web) 显示；「对外给用户」(设了
  // FAMOU_ACCESS_PASSWORD，后端注入 __FAMOU_AUTH_ON__=true) 时隐藏，不让终端用户切模型。
  const showModelPicker = !(typeof window !== "undefined" && window.__FAMOU_AUTH_ON__ === true)
  // 切换模型：更新状态 + 持久化 + 同步模块级 MODEL（sendPrompt 读它注入 body.model，下一条消息即生效）。
  const pickModel = useCallback((id) => {
    const key = canonicalModelKey(id)
    const m = modelFromKey(key)
    setModelID(key)
    try { localStorage.setItem(MODEL_LS_KEY, key) } catch { /* 隐私模式等忽略 */ }
    if (m) MODEL = m
  }, [])
  const [fileRefresh, setFileRefresh] = useState(0)
  const [focusPaper, setFocusPaper] = useState(null) // 中栏大屏展示的文献（null=不展示；文献单开，不进网格）
  // 左栏「知识库」「MoonLog」整窗全屏覆盖层：null=不展示 / "kb" / "moonlog"。侧栏只留入口条，
  // 点击后盖住整个窗口展示完整内容（侧栏窄，就地展开会拥挤；全屏给后续新功能留空间）。
  // localStorage 持久，刷新页面停留在原来打开的界面，不会跳回主界面。
  const [overlayView, setOverlayView] = useState(() => {
    const v = localStorage.getItem("famou.overlayView")
    return v === "kb" || v === "moonlog" ? v : null
  })
  useEffect(() => {
    if (overlayView) localStorage.setItem("famou.overlayView", overlayView)
    else localStorage.removeItem("famou.overlayView")
  }, [overlayView])
  // 打开时 pushState 一条历史记录，浏览器「返回」按钮能直接关掉全屏覆盖层（而不是退出/离开页面）。
  // 关闭走 history.back()（有 pushState 过的记录才退，否则直接清状态），和点击返回按钮行为一致。
  useEffect(() => {
    if (overlayView && !(history.state && history.state.overlayView)) {
      history.pushState({ overlayView }, "", location.href)
    }
  }, []) // eslint-disable-line
  useEffect(() => {
    function onPopState(e) {
      const v = e.state && e.state.overlayView
      setOverlayView(v === "kb" || v === "moonlog" ? v : null)
    }
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [])
  function openOverlay(v) {
    history.pushState({ overlayView: v }, "", location.href)
    setOverlayView(v)
  }
  function closeOverlay() {
    if (history.state && history.state.overlayView) history.back()
    else setOverlayView(null)
  }
  const ws = useWorkspace() // 中栏多文件分栏工作区（产物文件走这里）
  // 切换会话时关掉文献大屏并清空工作区——否则它是 App 级状态，会继续盖在新会话上。
  useEffect(() => { setFocusPaper(null); ws.reset() }, [currentID]) // eslint-disable-line
  // 文献大屏：单开，点开前不影响工作区（focus 槽里文献优先级更高，见下）。
  const openFocus = useCallback((kind, val) => { if (kind === "paper") { setFocusPaper(val); setProductsView("files") } }, [])
  // 打开一个产物文件到中栏工作区（进活动格标签）；同时关掉文献大屏让网格浮前，并切到 files 视图。
  const openFile = useCallback((path) => { setFocusPaper(null); ws.openFile(path); setProductsView("files") }, [ws])
  const [questionsBySession, setQuestionsBySession] = useState({}) // {sid: {requestID, sessionID, questions, version}}
  const [permissionsBySession, setPermissionsBySession] = useState({}) // {sid: {id, sessionID, permission, patterns, always, tool, metadata}}
  const [uploadsBySession, setUploadsBySession] = useState({}) // {sid: [{path,name,mime}]} 本会话上传的文件
  // 文献收藏「资产库」：全局共享一份，localStorage 持久；点 ☆ 加入/取消。
  // 收藏（打勾）时先弹分组选择，选完/新建才真正生效；取消收藏（去掉勾）直接生效，不弹窗。
  const [starred, setStarred] = useState(loadStarred)
  useEffect(() => { saveStarred(starred) }, [starred])
  const starredKeys = React.useMemo(() => new Set(starred.map(paperKey)), [starred])
  const [starPending, setStarPending] = useState(null) // 待选分组的文献对象；null=当前没有待选
  function toggleStar(p) {
    if (starredKeys.has(paperKey(p))) {
      setStarred((prev) => prev.filter((x) => paperKey(x) !== paperKey(p)))
    } else {
      setStarPending(p)
    }
  }
  async function confirmStar(group) {
    const p = starPending
    setStarPending(null)
    if (!p) return
    if (group) { try { await mkdirKbGroup(group) } catch {} }
    setStarred((prev) => (prev.some((x) => paperKey(x) === paperKey(p)) ? prev : [{ ...p, group: group || "" }, ...prev]))
    await loadKb()
  }
  // 知识库：全局上传文档（knowledge-base/[<分组>/]，跨会话共享，本轮仅存档浏览）。
  // 支持单层分组（=knowledge-base/ 下的子目录）：root=未分类文件，groups=[{name,files}]。
  const [kbData, setKbData] = useState({ root: [], groups: [] })
  const loadKb = useCallback(async () => {
    let top = []
    try { top = await listFiles("knowledge-base") } catch { top = [] }
    const root = (top || []).filter((f) => f.type !== "directory")
    const dirs = (top || []).filter((f) => f.type === "directory")
    const groups = await Promise.all(dirs.map(async (d) => {
      let gf = []
      try { gf = await listFiles(d.path) } catch { gf = [] }
      return { name: d.name, files: (gf || []).filter((f) => f.type !== "directory") }
    }))
    setKbData({ root, groups })
  }, [])
  useEffect(() => { loadKb() }, [loadKb])
  const kbGroupNames = React.useMemo(() => kbData.groups.map((g) => g.name), [kbData])
  async function uploadKb(fileList, group) {
    const results = await readFiles(fileList)
    const ok = results.filter((r) => r && r.dataUrl)
    const bad = results.filter((r) => r && r.rejected).map((r) => r.rejected)
    if (group) { try { await mkdirKbGroup(group) } catch (e) { alert("建组失败：" + (e && e.message || e)) } }
    const failed = []
    for (const att of ok) {
      try { await uploadKbFile(att, group) }
      catch (e) { console.error("kb upload failed", att.name, e); failed.push(att.name + "：" + (e && e.message || e)) }
    }
    await loadKb()
    const lines = []
    if (bad.length) lines.push("以下文件超过大小上限，已跳过：\n" + bad.join("\n"))
    if (failed.length) lines.push("以下文件上传失败：\n" + failed.join("\n"))
    if (lines.length) alert(lines.join("\n\n"))
  }
  async function deleteKb(f) {
    if (!window.confirm("确定从知识库删除「" + f.name + "」？此操作不可恢复。")) return
    try { await deleteKbFile(f.path) } catch (e) { alert("删除失败：" + (e && e.message || e)); return }
    await loadKb()
  }
  async function createKbGroup(name) {
    try { await mkdirKbGroup(name) } catch (e) { alert("建组失败：" + (e && e.message || e)); return }
    await loadKb()
  }
  async function renameKbGroup(oldName, newName) {
    const saved = await renameKbGroupApi(oldName, newName)
    setStarred((prev) => prev.map((p) => (p.group || "") === oldName ? { ...p, group: saved } : p))
    await loadKb()
  }
  function openKbInWorkspace(path) {
    closeOverlay()
    openFile(path)
  }
  function workspaceForProject(pid) {
    return pid && pid !== UNARCHIVED ? "research-runs/projects/" + pid + "/inputs" : ""
  }
  async function sendToSession(sid, text) {
    if (!sid || !text) return
    const base = "local-" + Date.now()
    setMsgsBySession((prev) => ({
      ...prev,
      [sid]: (prev[sid] || []).concat([{
        info: { id: base, sessionID: sid, role: "user" },
        parts: [{ id: base + "-t", messageID: "local", sessionID: sid, type: "text", text }],
      }]),
    }))
    setSessions((prev) => prev.map((x) => (x.id === sid ? { ...x, updatedAt: Date.now() } : x)))
    setBusySessions((prev) => ({ ...prev, [sid]: true }))
    if (!eventDirectory) await new Promise((r) => setTimeout(r, 80))
    sendPrompt(sid, text).catch((e) => {
      console.error(e)
      setBusySessions((prev) => ({ ...prev, [sid]: false }))
    })
  }
  async function readKbWithAgent(f) {
    closeOverlay()
    setProjView(false)
    setRailOpen(true)
    try {
      const title = "解读：" + (f.name || wsBasename(f.path) || "知识库资料")
      const s = await createSession(title)
      const copied = await copyKbFileToSession(f.path, s.id)
      const p = copied.path
      setSessions((prev) => applySessionTitleOverrides([{ ...s, id: s.id, title, directory: s.directory || "", updatedAt: Date.now() }, ...prev]))
      setSessionTitles((prev) => ({ ...prev, [s.id]: title }))
      setSessProj((prev) => ({ ...prev, [s.id]: curProj || UNARCHIVED }))
      setMsgsBySession((prev) => ({ ...prev, [s.id]: [] }))
      setCurrentID(s.id)
      setProductsView("process")
      sendToSession(s.id, "请解读这份资料：" + p)
    } catch (e) {
      alert("解读失败：" + (e && e.message || e))
    }
  }
  async function moveKbToProject(f) {
    if (!projects.length) { alert("还没有正式项目，请先新建项目。"); return }
    const choices = projects.map((p, i) => `${i + 1}. ${p.name}`).join("\n")
    const raw = window.prompt(`把「${f.name}」移入哪个项目？输入编号：\n${choices}`, "1")
    if (raw == null) return
    const target = projects[Number(raw) - 1]
    if (!target) return
    try {
      const copied = await copyKbFileToProject(f.path, target.id)
      setProjFiles((prev) => ({ ...prev, [target.id]: [...(prev[target.id] || []), { name: copied.name, path: copied.path }] }))
      setCurProj(target.id)
      saveCurProj(target.id)
      setProjView(false)
      setRailOpen(true)
      closeOverlay()
      const first = sessions.find((s) => (sessProj[s.id] || UNARCHIVED) === target.id)
      setCurrentID(first ? first.id : null)
      setTimeout(() => openFile(copied.path), 80)
    } catch (e) {
      alert("移入项目失败：" + (e && e.message || e))
    }
  }
  // MoonLog：只用来给侧栏入口条显示「已有几天的编译记录」，全屏页里 MoonLogBody 自己再拉一次
  // （不共享同一份 state——全屏页要在选中日期变化时单独刷新内容，逻辑更简单）。
  const [moonlogDates, setMoonlogDates] = useState([])
  useEffect(() => { listMoonlogDates().then(setMoonlogDates) }, [])
  const [chatW, setChatW] = useState(() => clampW(Number(localStorage.getItem("famou.chatW")) || 380, 280, 680))
  const [rightW, setRightW] = useState(() => clampW(Number(localStorage.getItem("famou.rightW")) || 340, 240, 820))
  // 知识库/MoonLog 全屏覆盖层：右侧抽屉，固定宽度，不支持用户拖拽调整。
  // ⓪可隐藏栏开合（VSCode 侧栏）：默认展开；折叠后只剩一条细活动条。
  const [railOpen, setRailOpen] = useState(() => localStorage.getItem("famou.railOpen") !== "0")
  // ③右侧产物/文献栏开合：默认展开；完全收起后最右侧只留一条半透明侧边条（点箭头拉回）。
  const [rightOpen, setRightOpen] = useState(() => localStorage.getItem("famou.rightOpen") !== "0")
  // ②产物区当前视图：process=实时轨迹 / files=文件工作区(四分框)。打开文件/文献时自动切 files。
  const [productsView, setProductsView] = useState("files")
  useEffect(() => { localStorage.setItem("famou.chatW", String(chatW)) }, [chatW])
  useEffect(() => { localStorage.setItem("famou.rightW", String(rightW)) }, [rightW])
  useEffect(() => { localStorage.setItem("famou.railOpen", railOpen ? "1" : "0") }, [railOpen])
  // 侧栏抽屉是浮层（absolute，不挤占其它栏宽度），点它以外任何地方都应自动收起——
  // 排除侧栏自身（.rail-drawer）和触发它开合的 ☰ 按钮（否则点 ☰ 会“关了又立刻重开”）。
  // 拖拽宽度手柄（.gutter）在拖拽时也不该触发收起，一并排除。
  useEffect(() => {
    if (!railOpen) return
    function onDown(e) {
      if (e.target.closest && (
        e.target.closest(".rail-drawer") ||
        e.target.closest(".rail-icon") ||
        e.target.closest(".gutter") ||
        e.target.closest(".np-mask")
      )) return
      setRailOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    return () => document.removeEventListener("mousedown", onDown)
  }, [railOpen])
  useEffect(() => { localStorage.setItem("famou.rightOpen", rightOpen ? "1" : "0") }, [rightOpen])
  // 主题：默认浅色（百度伐谋墨绿），可切深色；存 localStorage，刷新保持。
  const [theme, setTheme] = useState(() => localStorage.getItem("famou.theme") || "light")
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem("famou.theme", theme)
  }, [theme])
  // 左下角显示的用户名。来源由后端注入：window.__FAMOU_USER__（环境变量 > famou_user cookie），
  // __FAMOU_USER_LOCKED__=true 表示被环境变量钉死、不可改。都没有（无口令首次访问）→ 弹一次
  // 「设置用户名（可跳过）」，跳过就让后端分配 8 位随机数。改名/设名都 POST /setuser 写 cookie
  // （与登录态同寿命、过期才再要）；因 cookie 是 HttpOnly，前端拿返回值更新本地显示态即可。
  const userLocked = typeof window !== "undefined" && window.__FAMOU_USER_LOCKED__ === true
  const [displayUser, setDisplayUser] = useState(() =>
    (typeof window !== "undefined" && window.__FAMOU_USER__) ? String(window.__FAMOU_USER__).trim() : ""
  )
  // 提交用户名到后端（写 cookie），成功后更新显示。name 为空串=跳过→后端给随机数。
  async function submitUser(name) {
    try {
      const r = await fetch("/setuser", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username: name }),
      })
      const j = await r.json().catch(() => null)
      if (j && j.ok && j.user) setDisplayUser(j.user)
    } catch { /* 忽略：下次进入再要 */ }
  }
  // 无口令首访、且还没有名字 → 弹一次可跳过的设置框。用 ref 防重复弹。
  const userAskedRef = useRef(false)
  useEffect(() => {
    if (userLocked || displayUser || userAskedRef.current) return
    userAskedRef.current = true
    const name = window.prompt("给自己起个用户名（用于展示，可留空跳过，将自动分配一个编号）：", "")
    submitUser(name == null ? "" : name.trim())
  }, []) // eslint-disable-line
  function editUser() {
    if (userLocked) return // 环境变量钉死 → 不可改
    const name = window.prompt("修改显示用户名：", displayUser)
    if (name == null) return
    submitUser(name.trim())
  }
  // 拖拽手柄：which="sidebar" 调左栏、"right" 调右栏、"reveal" 从收起态把右栏拉出来。
  // 关键：拖动过程中宽度“连续跟手”（可一路缩到很小），只在松手那一刻才判定收起/保留 →
  // 避免中途出现“突然消失 / 突然跳到某宽度”的跳变，做到丝滑。
  // 高亮只加在被拖动的这一根手柄自己身上（e.currentTarget），不再用 body 级 class 全局点亮
  // 所有 .gutter——否则页面上哪怕只拖一条，其它几条手柄也会一起变色，像“全部在动”。
  // 中间产物区大屏时可能是 <iframe>(PDF)：鼠标划过 iframe，原生事件会被它的文档接管，不再
  // 派给外层 window 的 mousemove/mouseup —— 拖拽因此卡顿、错位，松手事件也可能丢失导致
  // onUp 从未触发（高亮/宽度状态永久卡住）。解法同 WsDivider：mousedown 时插入一个盖满
  // 全屏的透明捕获层，所有 move/up 都绑在它上面，iframe 完全收不到事件。
  function startDrag(which, e) {
    e.preventDefault()
    const handle = e.currentTarget
    handle.classList.add("dragging")
    const startX = e.clientX
    const baseChat = chatW, baseRight = rightW
    let moved = false
    let liveRight = baseRight // 拖动中的实时右栏宽度（松手时据此定收/留）
    if (which === "reveal") { setRightOpen(true); liveRight = 0; setRightW(0) } // 从收起态起拉：宽度从 0 长出
    const catcher = document.createElement("div")
    catcher.className = "ws-drag-catcher"
    catcher.style.cursor = "col-resize"
    document.body.appendChild(catcher)
    function onMove(ev) {
      const dx = ev.clientX - startX
      if (Math.abs(dx) > 3) moved = true
      if (which === "chat") setChatW(clampW(baseChat + dx, 280, 680)) // 对话栏：手柄右移(dx>0)变宽
      else {
        // 右栏 / reveal 把手：宽度 = 基准 - dx（手柄左移变宽），连续跟手，只封顶 820、不设 240 硬地板。
        const base = which === "reveal" ? 0 : baseRight
        liveRight = Math.max(0, Math.min(820, base - dx))
        setRightW(liveRight)
      }
    }
    function onUp() {
      if (which === "right" || which === "reveal") {
        // 松手定夺：最终宽度太窄(<160) → 收起，并把宽度复位到合理值，方便下次拉出/点开不为 0。
        if (liveRight < 160) { setRightOpen(false); setRightW(clampW(baseRight, 240, 820)) }
        else { setRightOpen(true); setRightW(clampW(liveRight, 240, 820)) }
        // reveal 把手只是轻点(几乎没拖) → 直接开到上次宽度，等同点击展开。
        if (which === "reveal" && !moved) { setRightOpen(true); setRightW(clampW(baseRight, 240, 820)) }
      }
      catcher.removeEventListener("mousemove", onMove)
      catcher.removeEventListener("mouseup", onUp)
      document.body.removeChild(catcher)
      document.body.classList.remove("resizing")
      handle.classList.remove("dragging")
    }
    catcher.addEventListener("mousemove", onMove)
    catcher.addEventListener("mouseup", onUp)
    document.body.classList.add("resizing")
  }

  const currentRef = useRef(null)
  currentRef.current = currentID
  const sessionsRef = useRef([])
  sessionsRef.current = sessions
  ACTIVE_SESSION_ID = currentID || ""
  // 记住当前 tab 停留的会话：刷新后恢复；新开窗口/新 tab 不继承旧窗口的 session。
  useEffect(() => {
    if (!sessionRestoreReady) return
    try {
      if (currentID) sessionStorage.setItem("famou.currentSid", currentID)
      else sessionStorage.removeItem("famou.currentSid")
    } catch { /* 隐私模式忽略 */ }
  }, [currentID, sessionRestoreReady])
  // 「正在中断」的会话集合：点了停止后，短暂窗口内忽略仍在路上的 delta/step 事件（它们本会把 busy
  // 顶回 true）。opencode 的 abort 不一定发 session.idle，没有这个抑制，busy 会立刻弹回"运行中"。
  const abortingRef = useRef(new Set())
  // 已由用户停止的会话：在下一次发送前丢弃该轮迟到的流式事件，也禁止 reconcile 把服务端
  // 尚未及时标 completed 的旧消息重新判成运行中。
  const terminatedSessionsRef = useRef(new Set())
  // 单调递增的「活动计数」：每来一次流式增量/部件/步进就 +1。看门狗据此判断生成是否真卡——
  // 计数在涨=正常长生成（别误报无响应），计数停滞=真卡（到时才提示）。
  const activityRef = useRef(0)
  // messageID → role（"user"/"assistant"）。opencode 的 message.part.updated 不带 role，
  // role 只在 message.updated 里；靠这个 Map 给流式部件判定角色（修"用户消息被当成助手回显"的 bug）。
  const rolesRef = useRef(new Map())
  // OpenCode 的正式 message.part.delta 按动画帧批量追加。候选 session.next.* 不进入这里，
  // 避免 Markdown 每个 token 重排，也保证已经展示的正式文本只增不减。
  const deltaBufferRef = useRef(new Map())
  const deltaFrameRef = useRef(null)
  // session.error 有时是 provider/router 的瞬时错误，后续仍会继续生成。先延迟展示；
  // 如果同一 session 随后有增量/步骤/idle，就取消这条错误，避免“报错后又继续刷”的误导。
  const errorTimersRef = useRef(new Map())
  const workspaceRefreshTimerRef = useRef(null)

  const messages = currentID ? msgsBySession[currentID] || [] : []
  const busy = currentID ? !!busySessions[currentID] : false
  const runtimeStatus = currentID ? runtimeBySession[currentID] || null : null
  const pendingQuestion = currentID ? questionsBySession[currentID] || null : null
  const pendingPermission = currentID ? permissionsBySession[currentID] || null : null
  const currentSessionDir = React.useMemo(
    () => (sessions.find((s) => s.id === currentID) || {}).directory || "",
    [sessions, currentID],
  )
  const curProjName = curProj === UNARCHIVED ? "未归档对话" : ((projects.find((p) => p.id === curProj) || {}).name || "未归档对话")
  const projectSessions = sessions.filter((s) => (sessProj[s.id] || UNARCHIVED) === curProj)
  const [sessionMenuFor, setSessionMenuFor] = useState(null)
  const [renameSessionTarget, setRenameSessionTarget] = useState(null)
  const [renameSessionValue, setRenameSessionValue] = useState("")
  const [deleteSessionTarget, setDeleteSessionTarget] = useState(null)
  const [moveSessionTarget, setMoveSessionTarget] = useState(null)
  const [moveSessionNewName, setMoveSessionNewName] = useState("")
  const moveProjectNameDuplicate = projectNameExists(projects, moveSessionNewName)
  function firstQueryFallbackTitle(sid) {
    const list = msgsBySession[sid] || []
    const msg = list.find((m) => m && m.info && m.info.role === "user")
    // Slash Command 的服务端正文是展开模板，标题兜底也必须读取 displayText。
    const line = String(msg ? userText(msg) : "").trim().split("\n")[0]
    if (!line) return ""
    return line.length > 24 ? line.slice(0, 24) + "…" : line
  }
  function isFirstQueryFallbackTitle(sid, title) {
    const t = String(title || "").trim()
    const fallback = firstQueryFallbackTitle(sid)
    return !!t && !!fallback && t === fallback
  }

  function applySessionTitleOverrides(list, titles = sessionTitlesRef.current) {
    const map = titles || {}
    return (list || []).map((s) => {
      const sid = String(s && s.id || "")
      const title = map[sid]
      return title && !isFirstQueryFallbackTitle(sid, title) ? { ...s, title } : s
    })
  }
  function setSessionTitleFor(sid, title) {
    const name = String(title || "").trim()
    if (!sid || !name) return
    const now = Date.now()
    setSessionTitles((prev) => (prev[sid] === name ? prev : { ...prev, [sid]: name }))
    setSessionMeta((prev) => ({ ...prev, [sid]: { ...(prev[sid] || { id: sid }), title: name, updatedAt: now } }))
    setSessions((prev) => prev.map((x) => (x.id === sid ? { ...x, title: name, updatedAt: now } : x)))
  }
  useEffect(() => {
    if (!sessionMenuFor) return
    function onDoc() { setSessionMenuFor(null) }
    window.addEventListener("mousedown", onDoc)
    window.addEventListener("blur", onDoc)
    return () => {
      window.removeEventListener("mousedown", onDoc)
      window.removeEventListener("blur", onDoc)
    }
  }, [sessionMenuFor])
  function openSessionRename(s) {
    setSessionMenuFor(null)
    setRenameSessionTarget(s)
    setRenameSessionValue(String((s && s.title) || "").trim())
  }
  function confirmSessionRename() {
    const s = renameSessionTarget
    const name = String(renameSessionValue || "").trim()
    if (!s || !name) return
    setSessionTitleFor(s.id, name)
    setRenameSessionTarget(null)
  }
  function openSessionDelete(s) {
    setSessionMenuFor(null)
    setDeleteSessionTarget(s)
  }
  function openSessionMove(s) {
    setSessionMenuFor(null)
    setMoveSessionTarget(s)
    setMoveSessionNewName("")
  }
  async function confirmSessionDelete() {
    const s = deleteSessionTarget
    if (!s) return
    const sid = s.id
    setDeleteSessionTarget(null)
    setSessions((prev) => prev.filter((x) => x.id !== sid))
    setSessionTitles((prev) => { const n = { ...prev }; delete n[sid]; return n })
    setSessionMeta((prev) => { const n = { ...prev }; delete n[sid]; return n })
    setMsgsBySession((prev) => { const n = { ...prev }; delete n[sid]; return n })
    setSessProj((prev) => { const n = { ...prev }; delete n[sid]; return n })
    if (currentID === sid) setCurrentID(null)
    try {
      await deleteSession(sid)
    } catch (err) {
      console.error(err)
    }
  }
  function confirmMoveSessionToProject(pid) {
    const s = moveSessionTarget
    if (!s || !pid) return
    setSessProj((prev) => ({ ...prev, [s.id]: pid }))
    setCurProj(pid)
    saveCurProj(pid)
    setCurrentID(s.id)
    setMoveSessionTarget(null)
  }
  function confirmMoveSessionToNewProject() {
    const s = moveSessionTarget
    const name = String(moveSessionNewName || "").trim()
    if (!s || !name || projectNameExists(projects, name)) return
    const id = newProjectId()
    setProjects((prev) => [{ id, name, createdAt: Date.now(), updatedAt: Date.now() }, ...prev])
    setSessProj((prev) => ({ ...prev, [s.id]: id }))
    setCurProj(id)
    saveCurProj(id)
    setCurrentID(s.id)
    setMoveSessionTarget(null)
  }
  // Workspace 的唯一事实来源是 OpenCode session.directory，也就是 Agent 的 cwd。
  // 消息中的工具路径只能触发刷新，不能改变右侧文件树根目录。
  const currentWorkspaceDir = currentSessionDir || ""
  // 本会话上传文件清单：优先内存 state，没有则读 localStorage（刷新/切会话后仍可见）。
  const uploads = currentID ? (uploadsBySession[currentID] || loadUploads(currentID)) : []
  // 新会话必须有独立 cwd；项目输入由后端复制进该 cwd，不直接把项目目录当 Workspace。
  const sessionWorkspaceForCurrentProject = () => ""
  const literature = React.useMemo(() => collectLiterature(messages), [messages])

  // upsert 一个 part 到指定会话的消息列表。
  // 只克隆「被改动的那条消息」与其 parts；其余消息保持原引用不变，
  // 让 React.memo 的 TextBlock/Turn 能跳过重渲染（流式期间不再全表重刷）。
  const upsertPart = useCallback((sid, part) => {
    setMsgsBySession((prev) => {
      const prevList = prev[sid] || []
      const idx = prevList.findIndex((m) => m.info.id === part.messageID)
      if (idx < 0) {
        const role = rolesRef.current.get(part.messageID) || "assistant"
        const msg = { info: { id: part.messageID, sessionID: sid, role }, parts: [part] }
        return { ...prev, [sid]: prevList.concat([msg]) }
      }
      const old = prevList[idx]
      const pi = old.parts.findIndex((p) => p.id === part.id)
      const newParts = old.parts.slice()
      if (pi >= 0) {
        const previousPart = newParts[pi]
        const isStreamingText = (part.type === "text" || part.type === "reasoning")
          && previousPart.type === part.type
          && typeof previousPart.text === "string"
          && typeof part.text === "string"
        const keepCompletedTool = part.type === "tool"
          && previousPart.type === "tool"
          && previousPart.state && previousPart.state.status === "completed"
          && (!part.state || part.state.status !== "completed")
        // SSE 快照可能晚于本地 delta：运行中不允许较短快照把已经展示的文本撤回。
        newParts[pi] = keepCompletedTool
          ? { ...previousPart, ...part, state: previousPart.state }
          : isStreamingText && part.text.length < previousPart.text.length
          ? { ...previousPart, ...part, text: previousPart.text }
          : part
      }
      else newParts.push(part)
      const newList = prevList.slice()
      newList[idx] = { info: old.info, parts: newParts }
      return { ...prev, [sid]: newList }
    })
  }, [])

  const flushPartDeltas = useCallback(() => {
    if (deltaFrameRef.current != null) {
      cancelAnimationFrame(deltaFrameRef.current)
      deltaFrameRef.current = null
    }
    const pending = Array.from(deltaBufferRef.current.values())
    deltaBufferRef.current.clear()
    if (!pending.length) return
    setMsgsBySession((prev) => {
      let next = prev
      for (const item of pending) {
        const list = next[item.sid] || []
        const mi = list.findIndex((m) => m.info && m.info.id === item.messageID)
        if (mi < 0 || rolesRef.current.get(item.messageID) === "user") continue
        const message = list[mi]
        const pi = (message.parts || []).findIndex((p) => p.id === item.partID)
        if (pi < 0) continue
        const part = message.parts[pi]
        const existing = part[item.field]
        if (typeof existing !== "string") continue
        const parts = message.parts.slice()
        parts[pi] = { ...part, [item.field]: existing + item.delta }
        const updated = list.slice()
        updated[mi] = { ...message, parts }
        if (next === prev) next = { ...prev }
        next[item.sid] = updated
      }
      return next
    })
  }, [])

  const appendPartDelta = useCallback((sid, properties) => {
    const messageID = properties && properties.messageID
    const partID = properties && properties.partID
    const field = properties && properties.field
    const delta = properties && properties.delta
    if (!sid || !messageID || !partID || !field || typeof delta !== "string" || !delta) return
    const key = [sid, messageID, partID, field].join("\\u0000")
    const previous = deltaBufferRef.current.get(key)
    deltaBufferRef.current.set(key, previous
      ? { ...previous, delta: previous.delta + delta }
      : { sid, messageID, partID, field, delta })
    if (deltaFrameRef.current == null) {
      deltaFrameRef.current = requestAnimationFrame(() => {
        deltaFrameRef.current = null
        flushPartDeltas()
      })
    }
  }, [flushPartDeltas])

  useEffect(() => () => {
    if (deltaFrameRef.current != null) cancelAnimationFrame(deltaFrameRef.current)
    deltaFrameRef.current = null
    deltaBufferRef.current.clear()
  }, [])

  const cancelPendingSessionError = useCallback((sid) => {
    const t = errorTimersRef.current.get(sid)
    if (!t) return
    clearTimeout(t)
    errorTimersRef.current.delete(sid)
  }, [])

  const upsertMessageInfo = useCallback((sid, info) => {
    if (!info || !info.id) return
    setMsgsBySession((prev) => {
      const prevList = prev[sid] || []
      const idx = prevList.findIndex((m) => m.info.id === info.id)
      if (idx < 0) return prev
      const old = prevList[idx]
      const newList = prevList.slice()
      newList[idx] = { ...old, info: { ...old.info, ...info } }
      return { ...prev, [sid]: newList }
    })
  }, [])

  // command.executed 提供原始命令名、参数和对应 user messageID；记下后所有展示只用原始输入。
  const registerCommandMessage = useCallback((sid, messageID, displayText) => {
    if (!sid || !messageID || !displayText) return
    rememberCommandDisplay(sid, messageID, displayText)
    setMsgsBySession((prev) => {
      const list = prev[sid] || []
      const index = list.findIndex((message) => message.info && message.info.id === messageID)
      if (index < 0) return prev
      const next = list.slice()
      next[index] = { ...list[index], info: { ...list[index].info, displayText } }
      return { ...prev, [sid]: next }
    })
  }, [])

  // 补捞某会话挂起的问询：命中→存下供 QuestionCard 渲染；没有→清掉残留。
  // 被 reconcile（切会话/刷新/idle/重连）与看门狗（运行中无问答框时定时补捞）共用。
  const recoverPendingQuestion = useCallback(async (sid) => {
    const directory = (sessions.find((s) => s.id === sid) || {}).directory || ""
    const pend = await listPendingQuestions(sid, directory)
    setQuestionsBySession((prev) => {
      if (pend.length) {
        const q = pend[0]
        return { ...prev, [sid]: { requestID: q.id, sessionID: sid, questions: q.questions || [], version: q.version, directory } }
      }
      if (!prev[sid]) return prev
      const n = { ...prev }
      delete n[sid]
      return n
    })
  }, [sessions])

  // 补捞某会话挂起的权限请求：命中→存下供 PermissionCard 渲染；没有→清掉残留。跟问询同一套用法。
  const recoverPendingPermission = useCallback(async (sid) => {
    const directory = (sessions.find((s) => s.id === sid) || {}).directory || ""
    const pend = await listPendingPermissions(sid, directory)
    setPermissionsBySession((prev) => {
      if (pend.length) return { ...prev, [sid]: pend[0] }
      if (!prev[sid]) return prev
      const n = { ...prev }
      delete n[sid]
      return n
    })
  }, [sessions])

  async function reconcile(sid) {
    if (terminatedSessionsRef.current.has(sid)) {
      setBusySessions((prev) => (prev[sid] ? { ...prev, [sid]: false } : prev))
      return false
    }
    let stillBusy // true/false=确认过；undefined=网络异常没能确认，调用方按"未知"处理
    const activityVersion = activityRef.current
    const directory = (sessions.find((s) => s.id === sid) || {}).directory || ""
    try {
      const msgs = await getMessages(sid)
      if (terminatedSessionsRef.current.has(sid)) return false
      const authoritative = await getSessionStatus(sid, directory)
      const live = runtimeBySessionRef.current[sid]
      const latest = msgs[msgs.length - 1]
      const persistedFailure = latest && latest.info && latest.info.role === "assistant"
        ? assistantFailureText(latest.info)
        : ""
      const gen = persistedFailure ? false : (authoritative ? authoritative.busy : !!(live && live.busy))
      if (persistedFailure) setRuntimeBySession((prev) => ({ ...prev, [sid]: { type: "error", busy: false, message: persistedFailure } }))
      // 拉取期间又收到 SSE，说明这个 HTTP 快照已经落后；不能用它覆盖刚显示的新文本或 busy 状态。
      if (activityRef.current === activityVersion) {
        if (msgs.length) {
          setMsgsBySession((prev) => {
            const streamed = prev[sid] || []
            // 生成中的服务端快照可能尚未落盘完整。已有流式内容时保持本地单调增长，idle 后再定稿。
            if (gen && streamed.length) return prev
            return { ...prev, [sid]: msgs }
          })
        }
        // 刷新/切会话后复原"运行中"；abort 抑制窗口内只许清 busy、不许重新顶起。
        stillBusy = gen && abortingRef.current.has(sid) ? false : gen
        setBusySessions((prev) => ({ ...prev, [sid]: stillBusy }))
      }
    } catch { /* keep streamed */ }
    // 找回该会话可能挂起的问询(刷新/切会话后恢复 QuestionCard)
    try { await recoverPendingQuestion(sid) } catch { /* ignore */ }
    // 找回该会话可能挂起的权限请求(刷新/切会话后恢复 PermissionCard)
    try { await recoverPendingPermission(sid) } catch { /* ignore */ }
    return stillBusy
  }

  // 状态同步器：运行中且没有问答框/权限框时，每 4 秒补捞挂起请求；连续无流式活动时，
  // 每约 12 秒 reconcile 一次，修复 SSE 漏事件。这里只同步真实状态，不判定超时、不终止回合。
  useEffect(() => {
    const sid = currentID
    if (!sid || !busy || pendingQuestion || pendingPermission) return
    let idleTicks = 0
    let lastSeen = activityRef.current
    const timer = setInterval(async () => {
      if (currentRef.current !== sid) return
      if (activityRef.current !== lastSeen) {
        lastSeen = activityRef.current
        idleTicks = 0
      } else {
        idleTicks += 1
      }
      try { await recoverPendingQuestion(sid) } catch { /* ignore */ }
      try { await recoverPendingPermission(sid) } catch { /* ignore */ }
      if (idleTicks >= 3 && idleTicks % 3 === 0) {
        try { await reconcile(sid) } catch { /* ignore */ }
      }
    }, 4000)
    return () => clearInterval(timer)
  }, [busy, currentID, pendingQuestion, pendingPermission, recoverPendingQuestion, recoverPendingPermission])

  // 标签页切回前台 / 窗口重新聚焦：当前会话仍 busy 则主动 reconcile 补齐——修"切走时 compact 假死、
  // SSE 漏 session.idle，切回来还一直转"的卡死（＝刷新等价物，无需用户手动刷新）。
  useEffect(() => {
    function syncIfBusy() {
      if (document.visibilityState !== "visible") return
      const sid = currentRef.current
      if (sid && busySessions[sid]) { reconcile(sid) }
    }
    document.addEventListener("visibilitychange", syncIfBusy)
    window.addEventListener("focus", syncIfBusy)
    return () => {
      document.removeEventListener("visibilitychange", syncIfBusy)
      window.removeEventListener("focus", syncIfBusy)
    }
  }, [busySessions])

  const handleEvent = useCallback((ev) => {
    // session.error 可能不带 sessionID → 兜底归到当前会话，别让它被下面的 guard 丢弃。
    const evSid = (ev.properties && ev.properties.sessionID)
      || (ev.type === "session.error" ? currentRef.current : null)
    if (!evSid) return
    // 本轮已明确结束后，服务端在 abort 生效前可能仍送来缓存中的 delta/step/error；全部丢弃，
    // 避免界面一边说“已结束”一边继续刷新答案。session.updated 仍保留用于同步标题等元数据。
    if (terminatedSessionsRef.current.has(evSid) && ev.type !== "session.updated") return
    switch (ev.type) {
      // opencode 自己异步生成的会话标题（简短总结，而非我们瞎截的首句）到了，同步进侧栏/资产用的 sessions。
      // 注意：session.updated 会因为 cost/token/status 等无关字段变化频繁触发，此时 info.title 往往
      // 还是占位默认值——用 isPlaceholderTitle 挡掉，否则会把我们刚设好的兜底标题又冲回占位态。
      case "session.updated": {
        const info = ev.properties && ev.properties.info
        if (info) {
          setSessions((prev) => prev.map((x) => {
            if (x.id !== evSid) return x
            const next = { ...x, ...info, id: x.id }
            const custom = sessionTitlesRef.current[evSid]
            if (custom && !isFirstQueryFallbackTitle(evSid, custom)) next.title = custom
            else if (typeof info.title !== "string" || isPlaceholderTitle(info.title)) next.title = x.title
            else {
              next.title = info.title
              setSessionTitles((prevMap) => (prevMap[evSid] === info.title ? prevMap : { ...prevMap, [evSid]: info.title }))
            }
            const it = info.time || {}
            const ms = toTimeMs(info.updatedAt ?? info.updated ?? it.updated ?? it.completed ?? it.created) || sessionTimeMs(next)
            if (ms) next.updatedAt = ms
            return next
          }))
        }
        break
      }
      case "message.updated": {
        // 先记下该消息的 role，供随后到达的 part 判定（user 的 part 要跳过）
        const info = ev.properties && ev.properties.info
        if (info && info.id) rolesRef.current.set(info.id, info.role)
        if (info) upsertMessageInfo(evSid, info)
        break
      }
      case "message.part.updated": {
        const part = ev.properties && ev.properties.part
        // 用户消息的流式部件跳过：界面已有用户发送时的乐观气泡，session.idle 后 reconcile 会用
        // 服务器真消息定稿。只把 assistant（及未知 role）的部件渲染出来，避免"把我的话当助手回显"。
        if (part && rolesRef.current.get(part.messageID) !== "user") {
          cancelPendingSessionError(evSid)
          flushPartDeltas()
          upsertPart(evSid, part)
          activityRef.current++
          if (part.type === "tool" && part.state && part.state.status === "completed" && evSid === currentRef.current) {
            if (workspaceRefreshTimerRef.current) clearTimeout(workspaceRefreshTimerRef.current)
            workspaceRefreshTimerRef.current = setTimeout(() => {
              workspaceRefreshTimerRef.current = null
              if (currentRef.current === evSid) setFileRefresh((value) => value + 1)
            }, 300)
          }
        }
        break
      }
      case "message.part.delta": {
        // 只追加正式 canonical delta；session.next.* 候选流仍然不进入聊天区。
        cancelPendingSessionError(evSid)
        appendPartDelta(evSid, ev.properties || {})
        activityRef.current++
        if (!abortingRef.current.has(evSid)) {
          setBusySessions((prev) => (prev[evSid] ? prev : { ...prev, [evSid]: true }))
        }
        break
      }
      case "command.executed": {
        const p = ev.properties || {}
        const argumentsText = String(p.arguments || "").trim()
        const displayText = "/" + String(p.name || "") + (argumentsText ? " " + argumentsText : "")
        registerCommandMessage(evSid, p.messageID, displayText)
        break
      }
      case "session.next.text.started":
      case "session.next.reasoning.started":
        cancelPendingSessionError(evSid)
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "busy", busy: true } }))
        activityRef.current++
        if (!abortingRef.current.has(evSid)) {
          setBusySessions((prev) => (prev[evSid] ? prev : { ...prev, [evSid]: true }))
        }
        break
      case "session.next.text.delta":
      case "session.next.reasoning.delta": {
        // session.next.* 是内部候选流；正式可见文本只取 message.part.*，避免候选内容闪现后撤回。
        cancelPendingSessionError(evSid)
        activityRef.current++
        if (!abortingRef.current.has(evSid)) {
          setBusySessions((prev) => (prev[evSid] ? prev : { ...prev, [evSid]: true }))
        }
        break
      }
      case "session.next.text.ended":
      case "session.next.reasoning.ended": {
        cancelPendingSessionError(evSid)
        activityRef.current++
        break
      }
      case "session.next.step.started":
        cancelPendingSessionError(evSid)
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "busy", busy: true } }))
        activityRef.current++
        if (!abortingRef.current.has(evSid)) {
          setBusySessions((prev) => ({ ...prev, [evSid]: true }))
        }
        break
      case "session.next.retried": {
        const p = ev.properties || {}
        const err = p.error || {}
        cancelPendingSessionError(evSid)
        setRuntimeBySession((prev) => ({
          ...prev,
          [evSid]: {
            type: "retry",
            busy: true,
            attempt: Number(p.attempt) || 1,
            message: String(err.message || "模型服务暂时不可用"),
          },
        }))
        if (!abortingRef.current.has(evSid)) setBusySessions((prev) => ({ ...prev, [evSid]: true }))
        break
      }
      case "session.status": {
        const raw = ev.properties && ev.properties.status
        const value = typeof raw === "string" ? raw : raw && (raw.type || raw.status || raw.state)
        const type = String(value || "").toLowerCase()
        const isBusy = ["busy", "running", "retry", "waiting"].includes(type)
        const isTerminal = ["idle", "completed", "complete", "done", "error", "failed", "aborted", "cancelled"].includes(type)
        if (isBusy) {
          cancelPendingSessionError(evSid)
          setRuntimeBySession((prev) => ({
            ...prev,
            [evSid]: type === "retry"
              ? {
                  type: "retry",
                  busy: true,
                  attempt: Number(raw && raw.attempt) || 1,
                  message: String((raw && raw.message) || "模型服务暂时不可用"),
                  next: Number(raw && raw.next) || 0,
                }
              : { type: "busy", busy: true },
          }))
          if (!abortingRef.current.has(evSid)) setBusySessions((prev) => ({ ...prev, [evSid]: true }))
        } else if (isTerminal) {
          setRuntimeBySession((prev) => { const next = { ...prev }; delete next[evSid]; return next })
          setBusySessions((prev) => ({ ...prev, [evSid]: false }))
          if (type === "idle" || type === "completed" || type === "done") reconcile(evSid)
        }
        break
      }
      case "session.idle":
        cancelPendingSessionError(evSid)
        setRuntimeBySession((prev) => { const next = { ...prev }; delete next[evSid]; return next })
        setBusySessions((prev) => ({ ...prev, [evSid]: false }))
        reconcile(evSid)
        if (evSid === currentRef.current) setFileRefresh((n) => n + 1)
        break
      // 生成出错（模型不存在 / 网关超时 / 上下文超长 / 限流等）：opencode 发 session.error，
      // 之后通常**不会**再发 session.idle → 若不处理，busy 永远卡住、用户只见"一直转、没回复"。
      // 这里清 busy 并在对话里插一条错误气泡，让用户知道为什么没回复、可重发。
      case "session.error": {
        const err = ev.properties && ev.properties.error
        const msg =
          (err && ((err.data && err.data.message) || err.message || err.name)) ||
          (typeof err === "string" ? err : "") || "生成中断（未知错误）"
        cancelPendingSessionError(evSid)
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "error", busy: false, message: msg } }))
        const timer = setTimeout(async () => {
          errorTimersRef.current.delete(evSid)
          const stillBusy = await reconcile(evSid)
          if (stillBusy) return
          setBusySessions((prev) => ({ ...prev, [evSid]: false }))
          setMsgsBySession((prev) => ({
            ...prev,
            [evSid]: (prev[evSid] || []).concat([{
              info: { id: "err-" + Date.now(), sessionID: evSid, role: "assistant" },
              parts: [{
                id: "errp-" + Date.now(), messageID: "err", sessionID: evSid, type: "text",
                text: "⚠️ 当前服务或模型调用异常：" + msg + "\n\n本轮已经停止。可以重发这条；若反复出现，建议换个模型或稍后再试。",
              }],
            }]),
          }))
        }, 1800)
        errorTimersRef.current.set(evSid, timer)
        break
      }
      // ── 问询(question)：agent 发问 → 存下供 QuestionCard 渲染；答/拒 → 清除 ──
      case "question.asked":
      case "question.v2.asked": {
        const p = ev.properties || {}
        const version = ev.type === "question.v2.asked" ? "v2" : "v1"
        const directory = (sessionsRef.current.find((s) => s.id === evSid) || {}).directory || ""
        setQuestionsBySession((prev) => ({
          ...prev,
          [evSid]: { requestID: p.id, sessionID: evSid, questions: p.questions || [], version, directory },
        }))
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "question", busy: true } }))
        break
      }
      case "question.replied":
      case "question.v2.replied":
      case "question.rejected":
      case "question.v2.rejected":
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "busy", busy: true } }))
        setQuestionsBySession((prev) => {
          if (!prev[evSid]) return prev
          const n = { ...prev }
          delete n[evSid]
          return n
        })
        break
      // ── 权限请求(permission)：agent 碰到 external_directory 等敏感操作 → 存下供
      // PermissionCard 渲染；回复/其它 pending 项被连带处理后 → 清除 ──
      case "permission.asked":
      case "permission.v2.asked": {
        const p = ev.properties || {}
        const version = ev.type === "permission.v2.asked" ? "v2" : "v1"
        const directory = (sessionsRef.current.find((s) => s.id === evSid) || {}).directory || ""
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "permission", busy: true } }))
        setPermissionsBySession((prev) => ({ ...prev, [evSid]: normalizePermissionRequest(p, version, evSid, directory) }))
        break
      }
      case "permission.replied":
      case "permission.v2.replied":
        setRuntimeBySession((prev) => ({ ...prev, [evSid]: { type: "busy", busy: true } }))
        setPermissionsBySession((prev) => {
          if (!prev[evSid]) return prev
          const n = { ...prev }
          delete n[evSid]
          return n
        })
        break
      default:
        break
    }
  }, [upsertPart, appendPartDelta, flushPartDeltas, cancelPendingSessionError, registerCommandMessage])

  useEffect(() => {
    return () => {
      for (const t of errorTimersRef.current.values()) clearTimeout(t)
      errorTimersRef.current.clear()
      if (workspaceRefreshTimerRef.current) clearTimeout(workspaceRefreshTimerRef.current)
      workspaceRefreshTimerRef.current = null
    }
  }, [])

  // 启动：解析默认模型 + 拉历史会话 + 开 SSE
  useEffect(() => {
    ;(async () => {
      try {
        const m = await resolveModel()
        // resolveModel 已用 /config 里的真实模型覆盖 MODEL_LIST → 同步到 state 驱动选择器渲染。
        setModels(MODEL_LIST)
        // 初始化选中模型：优先 localStorage（已在 useState 里读）；没有则用后端默认。
        // provider 被移除或改名后不能继续发送 localStorage 里的旧 key，否则后端只会产生空回复。
        const rememberedModel = parseModel(modelID)
        const remembered = modelID && MODEL_LIST.some((x) => x.id === modelID || x.modelID === modelID)
          ? modelID
          : rememberedModel && MODEL_LIST.some((x) => x.modelID === rememberedModel.modelID) ? rememberedModel.modelID : ""
        const init = canonicalModelKey(remembered || (m && modelKey(m.providerID, m.modelID)) || "anthropic-gateway/claude-sonnet-4-6")
        if (init !== modelID) {
          setModelID(init)
          try { localStorage.setItem(MODEL_LS_KEY, init) } catch { /* 隐私模式等忽略 */ }
        }
        const selected = modelFromKey(init)
        if (selected) MODEL = selected
      } catch { if (!modelID) setModelID("anthropic-gateway/claude-sonnet-4-6") }
      try {
        const list = await listSessions()
        // 过滤掉 opencode 自动建的空壳(标题 "New session - 时间戳")
        const items = list
          .filter((s) => !(s.title || "").startsWith("New session"))
          .map((s) => ({
            ...s,
            id: s.id,
            title: s.title || "研究",
            directory: s.directory || "",
            updatedAt: sessionTimeMs(s),
          }))
        setSessions(applySessionTitleOverrides(items))
        setConnected(true)
        // 后台只做一次 OpenCode 校准，用真实 title/cwd/time 补全旧数据；不阻塞列表首屏。
        void refreshRegisteredSessions().then((fresh) => {
          if (!fresh.length) return
          const learned = {}
          for (const s of fresh) learned[s.id] = sessionMetaOf(s)
          setSessions((prev) => {
            const byID = new Map(fresh.map((s) => [s.id, s]))
            return applySessionTitleOverrides(prev.map((old) => {
              const current = byID.get(old.id)
              return current ? { ...old, ...current, updatedAt: sessionTimeMs(current) } : old
            })).sort((a, b) => sessionTimeMs(b) - sessionTimeMs(a))
          })
          setSessionMeta((prev) => {
            const next = { ...prev, ...learned }
            const nextState = { ...projectStateRef.current, sessionMeta: next }
            projectStateRef.current = nextState
            void saveProjectState(nextState)
            return next
          })
        }).catch((e) => console.warn("session metadata refresh failed", e))
        if (items.length) {
          // 只恢复当前 tab 自己保存的会话；新开窗口不自动挂到最新历史会话。
          let saved = null
          try { saved = sessionStorage.getItem("famou.currentSid") } catch { /* ignore */ }
          const pick = (saved && items.some((s) => s.id === saved)) ? saved : null
          if (pick) {
            setCurrentID(pick)
            setCurProj(sessProj[pick] || UNARCHIVED)
            reconcile(pick)
          }
        }
      } catch (e) {
        console.error("listSessions failed", e)
        setConnected(false)
      } finally {
        setSessionRestoreReady(true)
      }
    })()
  }, []) // eslint-disable-line

  useEffect(() => {
    if (currentID) setCurProj(sessProj[currentID] || UNARCHIVED)
  }, [currentID, sessProj])

  const eventDirectory = currentSessionDir || ""
  const handleEventRef = useRef(handleEvent)
  const reconcileRef = useRef(reconcile)
  handleEventRef.current = handleEvent
  reconcileRef.current = reconcile

  useEffect(() => {
    const unsub = subscribeEvents(eventDirectory, (event) => {
      if (handleEventRef.current) handleEventRef.current(event)
    }, () => {
      const sid = currentRef.current
      if (sid) setRuntimeBySession((prev) => { const next = { ...prev }; delete next[sid]; return next })
      if (sid && reconcileRef.current) reconcileRef.current(sid)
    }, (isConnected) => {
      setConnected(isConnected)
    })
    return unsub
  }, [eventDirectory])

  async function newResearch() {
    if (creatingSessionRef.current) return
    creatingSessionRef.current = true
    setCreatingSession(true)
    setSessionCreateError("")
    const targetProject = curProj || UNARCHIVED
    closeOverlay() // 全屏页(知识库/MoonLog)里新建对话应跳回主界面，而非停留在全屏页背后
    setProjView(false)
    setRailOpen(true)
    try {
      const s = await createSession("新对话", sessionWorkspaceForCurrentProject())
      if (!s || !s.id) throw new Error("创建接口未返回 session ID")
      const created = { ...s, id: s.id, title: "新对话", directory: s.directory || "", updatedAt: Date.now() }
      const createdMeta = sessionMetaOf(created)
      setSessions((prev) => applySessionTitleOverrides([created, ...prev]))
      const nextState = {
        ...projectStateRef.current,
        sessProj: { ...projectStateRef.current.sessProj, [s.id]: targetProject },
        sessionMeta: { ...projectStateRef.current.sessionMeta, [s.id]: createdMeta },
        curProj: targetProject,
      }
      projectStateRef.current = nextState
      setSessProj(nextState.sessProj)
      setSessionMeta(nextState.sessionMeta)
      setCurProj(targetProject)
      saveSessProj(nextState.sessProj)
      saveCurProj(targetProject)
      void saveProjectState(nextState)
      setMsgsBySession((prev) => ({ ...prev, [s.id]: [] }))
      setCurrentID(s.id)
      // 聚焦输入框给出反馈（新会话在左侧列表顶部高亮出现 = 可见反馈）。
      requestAnimationFrame(() => { const ta = document.getElementById("composer-input"); if (ta) ta.focus() })
    } catch (e) {
      console.error("createSession failed", e)
      setSessionCreateError("新会话创建失败，请稍后重试。")
    } finally {
      creatingSessionRef.current = false
      setCreatingSession(false)
    }
  }

  function switchTo(sid) {
    closeOverlay() // 全屏页(知识库/MoonLog)里点会话应跳回主界面，而非停留在全屏页背后
    setProjView(false)
    setCurrentID(sid)
    setCurProj(sessProj[sid] || UNARCHIVED)
    if (!msgsBySession[sid]) reconcile(sid)
  }

  async function onDeleteSession(sid, e) {
    e.stopPropagation() // 别触发 switchTo
    const s = sessions.find((x) => x.id === sid)
    if (!s) return
    openSessionDelete(s)
  }

  function openProjectsHome() {
    setProjView(true)
  }
  function openProject(pid) {
    setCurProj(pid)
    setProjView(false)
    setRailOpen(true)
    saveCurProj(pid)
    const first = sessions.find((s) => (sessProj[s.id] || UNARCHIVED) === pid)
    if (first) setCurrentID(first.id)
  }
  function openUnarchived() {
    openProject(UNARCHIVED)
  }
  function selectProject(pid) {
    setCurProj(pid)
    setProjView(false)
    setRailOpen(true)
    saveCurProj(pid)
    const first = sessions.find((s) => (sessProj[s.id] || UNARCHIVED) === pid)
    if (first) setCurrentID(first.id)
    else if (pid === UNARCHIVED) setCurrentID(null)
  }
  function renameProject(p, nn) {
    const name = (nn || "").trim()
    if (!p || !name) return
    setProjects((prev) => prev.map((x) => (x.id === p.id ? { ...x, name } : x)))
  }
  function deleteProject(p) {
    setProjects((prev) => prev.filter((x) => x.id !== p.id))
    setSessProj((prev) => {
      const n = { ...prev }
      Object.keys(n).forEach((k) => { if (n[k] === p.id) n[k] = UNARCHIVED })
      return n
    })
    if (curProj === p.id) setCurProj(UNARCHIVED)
  }
  function newProject() {
    setShowNewProj(true)
  }
  async function createProject(name, files, opts = {}) {
    if (projectNameExists(projects, name)) throw new Error("已存在同名项目，请使用其他名称。")
    const id = newProjectId()
    const entry = { id, name, createdAt: Date.now(), updatedAt: Date.now() }
    const uploaded = await uploadProjectFiles(id, files, opts)
    setProjects((prev) => [entry, ...prev])
    setProjFiles((prev) => ({ ...prev, [id]: uploaded }))
    setCurProj(id)
    setProjView(false)
    setRailOpen(true)
    setCurrentID(null)
  }
  function moveSessionToProject(sid, e) {
    e.stopPropagation()
    const s = sessions.find((x) => x.id === sid)
    if (!s) return
    openSessionMove(s)
  }

  async function onSend(text, atts = [], opts = {}) {
    let sid = currentID
    // 带附件的消息可能以文件内容或说明开头，不能按 Slash Command 解释。
    const slashCommand = atts.length === 0 ? parseSlashCommand(text) : null
    // 没有会话时自动开一个(豆包：直接输入就开始)
    if (!sid) {
      try {
        const s = await createSession("新对话", sessionWorkspaceForCurrentProject())
        sid = s.id
        const created = { ...s, id: s.id, title: "新对话", directory: s.directory || "", updatedAt: Date.now() }
        const targetProject = curProj || UNARCHIVED
        const nextState = {
          ...projectStateRef.current,
          sessProj: { ...projectStateRef.current.sessProj, [s.id]: targetProject },
          sessionMeta: { ...projectStateRef.current.sessionMeta, [s.id]: sessionMetaOf(created) },
        }
        projectStateRef.current = nextState
        setSessions((prev) => applySessionTitleOverrides([created, ...prev]))
        setSessProj(nextState.sessProj)
        setSessionMeta(nextState.sessionMeta)
        void saveProjectState(nextState)
        setCurrentID(sid)
      } catch (e) { console.error(e); return }
    }
    // 新一轮开始：解除上一轮用户停止留下的迟到事件屏障。
    terminatedSessionsRef.current.delete(sid)
    abortingRef.current.delete(sid)
    // 乐观本地气泡：文本 part（若有）+ 每个附件一个 file part（用户立刻看到自己发的图/文件）。
    // 注意：乐观气泡始终展示**原始**附件（图片缩略图 / 文档文件名），与"发给后端的内容"解耦——
    // 文档实际是落盘后以路径文本发出，但用户气泡仍直观显示自己上传了哪些文件。
    const base = "local-" + Date.now()
    const displayText = String(opts.displayText || text || "")
    const localParts = []
    if (displayText) localParts.push({ id: base + "-t", messageID: "local", sessionID: sid, type: "text", text: displayText })
    atts.forEach((a, i) => localParts.push({
      id: base + "-f" + i, messageID: "local", sessionID: sid, type: "file",
      mime: a.mime, url: a.dataUrl, filename: a.relPath || a.name,
    }))
    setMsgsBySession((prev) => ({
      ...prev,
      [sid]: (prev[sid] || []).concat([{
        info: { id: base, sessionID: sid, role: "user" },
        parts: localParts,
      }]),
    }))
    const sentAt = Date.now()
    setSessions((prev) => prev.map((x) => (x.id === sid ? { ...x, updatedAt: sentAt } : x)))
    setSessionMeta((prev) => ({ ...prev, [sid]: { ...(prev[sid] || { id: sid }), updatedAt: sentAt } }))
    // 首条消息先给侧栏一个可读、稳定的临时标题；OpenCode 生成的摘要标题到达后会覆盖它。
    // 已有自定义标题不覆盖，避免用户改名后下一轮又被首句冲掉。
    const titleLine = String(displayText || text || "").trim().split("\n")[0]
    const fallbackTitle = titleLine.length > 24 ? titleLine.slice(0, 24) + "…" : titleLine
    const existing = sessionsRef.current.find((x) => x.id === sid)
    const placeholder = !existing || !existing.title || isPlaceholderTitle(existing.title) || existing.title === "新对话"
    if (fallbackTitle && placeholder && !sessionTitlesRef.current[sid]) setSessionTitleFor(sid, fallbackTitle)
    setBusySessions((prev) => ({ ...prev, [sid]: true }))
    // 会话标题交给 opencode/agent 自己生成；前端不再用首句兜底。
    // （见 handleEvent），这里不再抢着 PATCH——抢先设了反而会让 opencode 以为"已有标题"而不再生成。

    // 所有附件（图片/PDF/文本/代码）统一落盘到当前 session workspace（agent cwd），
    // 把相对路径写进文本交给 agent 用工具读。新逻辑不再使用 research-runs/_inbox，也不再随 runDir 迁移。

    let finalText = text
    if (atts.length) {
      const lines = []
      const recorded = [] // 落盘成功的 {path,name,mime}，记账供面板展示
      const uploadDirectory = (sessions.find((s) => s.id === sid) || {}).directory || ""
      for (const a of atts) {
        try {
          const p = await uploadFile(a, sid, uploadDirectory)
          lines.push(`- ${p} (${a.mime || "文件"})`)
          recorded.push({ path: p, name: a.relPath || a.name, mime: a.mime })
        } catch (e) {
          console.error("upload failed", a.name, e)
          lines.push(`- ${a.name}（上传失败：${e && e.message ? e.message : "未知错误"}）`)
        }
      }
      if (recorded.length) {
        // 记账到 state + localStorage，让右侧「📎 本次上传」立刻可见、刷新后仍在。
        setUploadsBySession((prev) => {
          const merged = (prev[sid] || loadUploads(sid)).concat(recorded)
          saveUploads(sid, merged)
          return { ...prev, [sid]: merged }
        })
      }
      const note =
        "[用户上传了以下文件，已保存到当前对话的工作目录（也就是你的 cwd），请直接用工具按给出的相对路径读取" +
        "（图片可用支持视觉的方式查看，PDF/文本/代码按需读取；勿凭空找路径、勿反问路径）：\n" +
        lines.join("\n") +
        "\n]"
      finalText = text ? note + "\n\n" + text : note
    }

    setRuntimeBySession((prev) => ({ ...prev, [sid]: { type: "submitting", busy: true } }))
    await new Promise((r) => setTimeout(r, 0))
    const request = slashCommand
      ? sendCommand(sid, slashCommand.command, slashCommand.arguments).then((result) => {
          // 某些代理会漏掉 command.executed 事件；响应中的 parentID 可作为确定性补偿。
          const messageID = result && result.info && result.info.parentID
          if (messageID) registerCommandMessage(sid, messageID, String(text || "").trim())
          return result
        })
      : sendPrompt(sid, finalText)
    request.then(() => {
      setRuntimeBySession((prev) => ({
        ...prev,
        [sid]: !prev[sid] || prev[sid].type === "submitting"
          ? { type: "submitted", busy: true }
          : prev[sid],
      }))
    }).catch((e) => {
      console.error(e)
      const detail = String((e && e.message) || e || "未知错误")
      setRuntimeBySession((prev) => ({
        ...prev,
        [sid]: { type: "error", busy: false, message: "请求发送失败：" + detail },
      }))
      setBusySessions((prev) => ({ ...prev, [sid]: false }))
    })
  }

  // 「深入解读」：把论文（名字+链接）作为一条用户消息直接发给当前对话（无会话则自动开一个）。
  // 先关掉文献大屏并清空工作区，否则大屏会盖在对话上，看不到正在进行的精读。
  function onDeepDive(p) {
    if (!p) return
    setFocusPaper(null); ws.reset()
    onSend(deepDivePrompt(p))
  }

  // 中断当前会话的生成（误发 / 输出跑偏时停掉）。abort 后端会把消息打上 completed 并停止，但**不一定即时
  // 发 session.idle**，且多步工具调用时 abort 信号要等当前这步的网关请求返回才真正生效 → SSE 里可能还有
  // 零星 delta / next.step.started 在路上。对策：① abortingRef 抑制这些事件把 busy 顶回 true（reconcile
  // 同样遵守）；② await abort 送达后主动 reconcile 收敛；③ 抑制窗口拉长到 6s，覆盖"当前步未返回"的尾巴。
  async function onStop() {
    const sid = currentID
    if (!sid) return
    terminatedSessionsRef.current.add(sid)
    abortingRef.current.add(sid)
    setBusySessions((prev) => ({ ...prev, [sid]: false }))
    setRuntimeBySession((prev) => { const next = { ...prev }; delete next[sid]; return next })
    const ok = await abortSession(sid)
    // abort 已送达：稍等服务端给最后一条 assistant 打 completed，再 reconcile 一次收敛到真状态。
    // 仍在抑制窗口内，reconcile 即便抓到"未完成"也只会清 busy、不会顶回 true。
    if (ok) {
      setTimeout(() => reconcile(sid), 400)
      setTimeout(() => reconcile(sid), 1500)
    }
    // 窗口结束后解除抑制（届时生成早已停、无新事件）；其间到达的 idle/error 仍可正常清 busy。
    setTimeout(() => abortingRef.current.delete(sid), 6000)
  }

  async function onDeleteUserMessage(messageID) {
    const sid = currentID
    if (!sid || !messageID) return
    if (busySessions[sid]) throw new Error("Agent 运行期间不能删除消息，请先停止当前回合。")
    await deleteMessage(sid, messageID)
    setMsgsBySession((prev) => ({ ...prev, [sid]: (prev[sid] || []).filter((m) => m.info && m.info.id !== messageID) }))
  }

  // 回答/跳过当前会话的问询 → 回传 OpenCode。接口确认后先把原 question part 转成只读回显，
  // 避免卡片消失和服务端终态之间出现空白；随后由 OpenCode 持久化的 metadata.answers
  // 或兼容 output 定稿，刷新后仍可恢复。
  async function onReplyQuestion(answers) {
    const sid = currentID
    const p = sid && questionsBySession[sid]
    if (!p) return
    const directory = p.directory || (sessions.find((s) => s.id === sid) || {}).directory || ""
    await replyQuestion(p.version, p.sessionID, p.requestID, answers, directory)
    const pend = await listPendingQuestions(sid, directory).catch(() => [])
    const stillPending = pend.some((q) => q.id === p.requestID)
    if (stillPending) throw new Error("提交未被服务端确认，请稍后重试")
    setMsgsBySession((prev) => {
      const current = prev[sid] || []
      const next = applyAnsweredQuestionSnapshot(current, p, answers)
      return next === current ? prev : { ...prev, [sid]: next }
    })
    setQuestionsBySession((prev) => { const n = { ...prev }; delete n[sid]; return n })
    setBusySessions((prev) => ({ ...prev, [sid]: true })) // 模型拿到答案后继续推进
    setTimeout(() => reconcile(sid), 400)
    setTimeout(() => reconcile(sid), 1500)
  }
  async function onRejectQuestion() {
    const sid = currentID
    const p = sid && questionsBySession[sid]
    if (!p) return
    const directory = p.directory || (sessions.find((s) => s.id === sid) || {}).directory || ""
    await rejectQuestion(p.version, p.sessionID, p.requestID, directory)
    setQuestionsBySession((prev) => { const n = { ...prev }; delete n[sid]; return n })
  }

  // 回复当前会话的权限请求 → 回传 opencode；乐观清除(permission.replied 事件也会清)。
  // once/always 放行后模型会继续跑那个工具调用 → busy 顶回 true；reject 只是让 agent 收到反馈
  // 自己决定怎么反应(可能换个方式、可能停下问你)，不强行顶 busy。
  async function onReplyPermission(reply, message) {
    const sid = currentID
    const p = sid && permissionsBySession[sid]
    if (!p) return
    const directory = p.directory || (sessions.find((s) => s.id === sid) || {}).directory || ""
    await replyPermission(p.version, sid, p.id, reply, message, directory)
    setPermissionsBySession((prev) => { const n = { ...prev }; delete n[sid]; return n })
    if (reply !== "reject") setBusySessions((prev) => ({ ...prev, [sid]: true }))
  }

  return (
    <div className={"app" + (rightOpen ? "" : " right-collapsed") + (railOpen ? " rail-open" : "")}>
      {showNewProj && (
        <NewProjectModal
          projects={projects}
          onCancel={() => setShowNewProj(false)}
          onCreate={createProject}
        />
      )}
      {projView && (
        <ProjectsHome
          projects={projects}
          sessProj={sessProj}
          sessions={sessions}
          unarchivedId={UNARCHIVED}
          onOpenProject={openProject}
          onOpenUnarchived={openUnarchived}
          onOpenSession={switchTo}
          onNewProject={newProject}
          onRename={renameProject}
          onDelete={deleteProject}
        />
      )}
      {/* ⓪ 「知识库/MoonLog」整窗全屏覆盖层：fixed 盖住整个 .app（含侧栏/对话/产物/右栏），
          点击左栏对应入口条打开，点返回或切会话关闭。侧栏窄放不下这两块内容，全屏给后续
          新功能（RAG、多文档管理等）留空间。 */}
      {overlayView && (
        <div className="fs-screen">
          <div className="fs-bar">
            <span className="fs-bar-ttl">
              <Icon
                name={overlayView === "kb" ? "book" : "moon"}
                size={16}
              />
              {overlayView === "kb" ? "知识库" : "MoonLog"}
            </span>
          </div>
          {overlayView === "kb" ? (
            <KnowledgeBaseBody
              papers={starred}
              kbData={kbData}
              onCreateGroup={createKbGroup}
              onRenameGroup={renameKbGroup}
              onUpload={uploadKb}
              onOpenKb={openKbInWorkspace}
              onReadKb={readKbWithAgent}
              onMoveKbToProject={moveKbToProject}
              onDeleteKb={deleteKb}
              onFocus={(p) => { openFocus("paper", p); closeOverlay() }}
              starredKeys={starredKeys}
              onToggleStar={toggleStar}
              onDeepDive={onDeepDive}
            />
          ) : (
            <MoonLogBody />
          )}
        </div>
      )}
      {renameSessionTarget && (
        <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask") setRenameSessionTarget(null) }}>
          <div className="np-modal proj-modal">
            <div className="np-title">重命名会话</div>
            <div className="np-sub">修改侧边栏显示名称，不影响会话内容。</div>
            <label className="np-label">会话名称</label>
            <input
              className="np-input"
              value={renameSessionValue}
              autoFocus
              onChange={(e) => setRenameSessionValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") confirmSessionRename() }}
            />
            <div className="np-acts">
              <button className="np-btn" onClick={() => setRenameSessionTarget(null)}>取消</button>
              <button className="np-btn primary" disabled={!String(renameSessionValue || "").trim()} onClick={confirmSessionRename}>保存</button>
            </div>
          </div>
        </div>
      )}
      {deleteSessionTarget && (
        <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask") setDeleteSessionTarget(null) }}>
          <div className="np-modal proj-modal">
            <div className="np-title">删除会话</div>
            <div className="np-sub">删除「{deleteSessionTarget.title}」？此操作不可恢复。</div>
            <div className="np-acts">
              <button className="np-btn" onClick={() => setDeleteSessionTarget(null)}>取消</button>
              <button className="np-btn danger" onClick={confirmSessionDelete}>删除</button>
            </div>
          </div>
        </div>
      )}
      {moveSessionTarget && (
        <div className="np-mask" onClick={(e) => { if (e.target.className === "np-mask") setMoveSessionTarget(null) }}>
          <div className="np-modal proj-modal move-session-modal">
            <div className="np-title">移入项目</div>
            <div className="np-sub">为「{moveSessionTarget.title}」选择一个目标项目，或新建一个项目。</div>
            <div className="move-project-list">
              {projects.length === 0 ? (
                <div className="move-project-empty">还没有项目，先新建一个再移入。</div>
              ) : projects.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={"move-project-item" + ((sessProj[moveSessionTarget.id] || UNARCHIVED) === p.id ? " cur" : "")}
                  onClick={() => confirmMoveSessionToProject(p.id)}
                >
                  <span className="move-project-name">{p.name}</span>
                  <span className="move-project-meta">{sessions.filter((s) => (sessProj[s.id] || UNARCHIVED) === p.id).length} 个会话</span>
                </button>
              ))}
            </div>
            <div className="move-project-new">
              <label className="np-label">新建项目并移入</label>
              <input
                className={"np-input" + (moveProjectNameDuplicate ? " invalid" : "")}
                value={moveSessionNewName}
                autoFocus={projects.length === 0}
                placeholder="输入新项目名称"
                onChange={(e) => setMoveSessionNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") confirmMoveSessionToNewProject() }}
              />
              {moveProjectNameDuplicate && <div className="np-error">已存在同名项目，可直接选择上方项目。</div>}
            </div>
            <div className="np-acts">
              <button className="np-btn" onClick={() => setMoveSessionTarget(null)}>取消</button>
              <button className="np-btn primary" disabled={!String(moveSessionNewName || "").trim() || moveProjectNameDuplicate} onClick={confirmMoveSessionToNewProject}>新建并移入</button>
            </div>
          </div>
        </div>
      )}
      {/* 收藏文献时先选分组：可能从右栏文献列表、也可能从知识库全屏页里触发，故挂在 App 根上、
          z-index 高于 fs-screen，两处都能弹出来。 */}
      {starPending && (
        <GroupPicker
          title="收藏到哪个分组？"
          groups={kbGroupNames}
          onPick={confirmStar}
          onCancel={() => setStarPending(null)}
        />
      )}
      {/* ⓪ 活动条：始终常驻(44px，不挤开其他栏)，点 ☰ 开合侧栏抽屉 */}
      <div className="railbar-collapsed">
        <button className="rail-icon" title={railOpen ? "收起侧栏" : "展开侧栏"} onClick={() => setRailOpen((v) => !v)}><Icon name="menu" size={17} /></button>
        <button className="rail-icon" title={creatingSession ? "正在创建新会话" : "新会话"} disabled={creatingSession} onClick={newResearch}>
          {creatingSession ? <span className="spinner" /> : <Icon name="plus" size={17} />}
        </button>
      </div>

      {/* ⓪ 侧栏抽屉：覆盖(浮层)在内容之上，绝对定位——不改变其他栏宽度；固定宽度，不支持拖拽调整 */}
      {railOpen && (
        <div className="sidebar rail-drawer">
          <div className="sidebar-head">
            <div className="brand-row">
              <span>
                <div className="brand-name">
                  <span className="brand-baidu">百度</span><span className="brand-famou">伐谋</span>
                </div>
                <div className="brand-sub">AutoResearch · 科研搭子</div>
              </span>
            </div>
          </div>
          <ProjectSwitcher
            projects={projects}
            curProj={curProj}
            curProjName={curProjName}
            unarchivedId={UNARCHIVED}
            onSelect={selectProject}
            onOpenAll={openProjectsHome}
          />
          <SearchBox
            starred={starred}
            listSessions={listSessions}
            getMessages={getMessages}
            userText={userText}
            onPickSession={(sid) => switchTo(sid)}
            onPickPaper={(p) => openFocus("paper", p)}
          />
          <KnowledgeBaseEntry papers={starred} kbData={kbData} onOpen={() => openOverlay("kb")} />
          <MoonLogEntry dateCount={moonlogDates.length} onOpen={() => openOverlay("moonlog")} />
          <button className="new-chat-btn" disabled={creatingSession} onClick={newResearch}>
            {creatingSession ? <><span className="spinner session-create-spinner" /> 创建中…</> : <><Icon name="plus" size={14} /> 新会话</>}
          </button>
          {sessionCreateError && <div className="session-create-error" role="alert">{sessionCreateError}</div>}
          <div className="session-list">
            {projectSessions.length === 0 && (
              <div className="file-empty" style={{ fontSize: 12, padding: 16 }}>
                {curProj === UNARCHIVED && sessions.length > 0
                  ? "未归档对话里还没有会话。点「＋ 新会话」或直接输入开始。"
                  : `项目「${curProjName}」下还没有会话。`}
              </div>
            )}
            {projectSessions.map((s) => (
              <div
                key={s.id}
                className={"session-item " + (s.id === currentID ? "active" : "")}
                onClick={() => { setSessionMenuFor(null); switchTo(s.id) }}
                title={s.title}
              >
                <span className="session-item-icon"><Icon name="chat" size={13} /></span>
                <span className="session-item-title">{s.title}</span>
                {questionsBySession[s.id] && <span className="q-flag" title="有待回答的问题">？</span>}
                {permissionsBySession[s.id] && <span className="p-flag" title="有待批准的权限请求">🔒</span>}
                {busySessions[s.id] && <span className="dot busy" />}
                {curProj === UNARCHIVED && projects.length > 0 && (
                  <span className="session-item-move" title="移入项目" onClick={(e) => moveSessionToProject(s.id, e)}>↗</span>
                )}
                <button
                  type="button"
                  className="session-item-dots"
                  title="更多操作"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); setSessionMenuFor((cur) => cur === s.id ? null : s.id) }}
                >···</button>
                {sessionMenuFor === s.id && (
                  <div className="session-item-menu" onMouseDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                    <button className="session-item-menu-item" onClick={() => openSessionMove(s)}><Icon name="folder" size={13} /> 移入项目</button>
                    <button className="session-item-menu-item" onClick={() => openSessionRename(s)}><Icon name="edit" size={13} /> 重命名</button>
                    <button className="session-item-menu-item danger" onClick={() => openSessionDelete(s)}><Icon name="trash" size={13} /> 删除</button>
                  </div>
                )}
              </div>
            ))}
          </div>
            <div className="sidebar-foot">
              <span className={"dot " + (connected ? "live" : "")} title={connected ? "已连接" + (modelID ? " · " + modelLabelOf(modelID) : "") : "连接中…"} />
              <span
                className="sub user-name"
                onClick={editUser}
                title={userLocked ? "当前用户" : "点击修改显示用户名"}
                style={{ cursor: userLocked ? "default" : "pointer" }}
              >
                {displayUser || (connected ? "点此设置用户名" : "连接中…")}
              </span>
              <button
                className="theme-toggle"
                onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                title={theme === "dark" ? "切换浅色" : "切换深色"}
              >
                {theme === "dark" ? <><Icon name="sun" size={13} /> 浅色</> : <><Icon name="moon" size={13} /> 深色</>}
              </button>
            </div>
        </div>
      )}

      {/* ① 对话框：纯当前对话（产物已拆到中栏） */}
      <div className="pane-chat" style={{ width: chatW }}>
        <Chat
          key={currentID || "none"}
          messages={messages}
          busy={busy}
          onSend={onSend}
          runtimeStatus={runtimeStatus}
          onDeleteUserMessage={onDeleteUserMessage}
          onStop={onStop}
          disabled={false}
          pendingQuestion={pendingQuestion}
          onReplyQuestion={onReplyQuestion}
          onRejectQuestion={onRejectQuestion}
          pendingPermission={pendingPermission}
          onReplyPermission={onReplyPermission}
          modelID={modelID}
          onPickModel={pickModel}
          models={models}
          showModelPicker={showModelPicker}
          onOpenImage={openFile}
        />
      </div>

      {/* 拖拽手柄：对话 ↔ 产物 */}
      <div className="gutter" onMouseDown={(e) => startDrag("chat", e)} title="拖动调整宽度" />

      {/* ② 产物区（中，flex）：进程实时轨迹 / 文件工作区（四分框） */}
      <div className="pane-products">
        <ProductsPane
          messages={messages}
          sessionID={currentID}
          busy={busy}
          runtimeStatus={runtimeStatus}
          focusPaper={focusPaper}
          onCloseFocus={() => setFocusPaper(null)}
          workspace={ws.workspace}
          wsActions={ws}
          view={productsView}
          onView={setProductsView}
        />
      </div>

      {/* ③ 右侧：工作区目录树 + 文献。可完全收起 → 只留一条半透明侧边条（点箭头拉回）。 */}
      {rightOpen ? (
        <>
          {/* 拖拽手柄：产物 ↔ 工作区 */}
          <div className="gutter" onMouseDown={(e) => startDrag("right", e)} title="拖动调整宽度" />
          <div className="pane-right" style={{ width: rightW }}>
            <ResearchPanel
              workspaceDir={currentWorkspaceDir}
              uploads={uploads}
              busy={busy}
              refreshKey={fileRefresh}
              literature={literature}
              onFocusPaper={(p) => openFocus("paper", p)}
              onOpenPdf={openFile}
              onOpenImage={openFile}
              onFocusFile={openFile}
              onAskAgent={(prompt, displayText) => onSend(prompt, [], { displayText })}
              starredKeys={starredKeys}
              onToggleStar={toggleStar}
              onDeepDive={onDeepDive}
              onCollapse={() => setRightOpen(false)}
            />
          </div>
        </>
      ) : (
        <div className="right-reveal" title="拖动或点击拉出产物 / 文献栏" onMouseDown={(e) => startDrag("reveal", e)}>
          <Icon name="chevronsLeft" size={22} />
        </div>
      )}
    </div>
  )
}

createRoot(document.getElementById("root")).render(<App />)
