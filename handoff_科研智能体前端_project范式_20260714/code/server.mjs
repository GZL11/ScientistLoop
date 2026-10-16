#!/usr/bin/env node
// Zero-build dev server for Famou 研究台.
// Why not Vite? In restricted networks the npm install of vite/react never completes.
// Instead we serve static files + proxy /oc → opencode, and the browser loads
// React/react-markdown + Babel through THIS server (which fetches them from esm.sh/unpkg).
// That matters on jump hosts: the browser often can't reach esm.sh/unpkg, but the server can —
// so the browser only ever talks to localhost, and the server mirrors the CDN for it.
// No node_modules required.
import http from "node:http"
import https from "node:https"
import net from "node:net"
import tls from "node:tls"
import os from "node:os"
import crypto from "node:crypto"
import { execFile, spawn } from "node:child_process"
import { readFile, writeFile, mkdir, readdir, rename, copyFile, unlink, rmdir } from "node:fs/promises"
import { extname, join, normalize, resolve, relative, basename } from "node:path"
import { fileURLToPath } from "node:url"
import { startMoonlogScheduler, listMoonlogDates, readMoonlog } from "./moonlog.mjs"

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "public")
const SRC = join(fileURLToPath(new URL(".", import.meta.url)), "src")
// 产物根 = 启动服务的工作目录（与 opencode serve 同 cwd，research-runs/ 落在这里）；
// /raw 路由把 research-runs/<topic>/... 这类相对路径以它为基准解析。
const PROJECT_ROOT = resolve(process.cwd())
// CDN 镜像磁盘缓存：取过一次就落盘，之后本地直出（重载秒开 + 对 esm.sh 抖动免疫；warm 后近似离线）。
const CDN_CACHE = process.env.FAMOU_WEB_CDN_CACHE || join(os.tmpdir(), "famou-web-cdn")
const OC_TARGET = process.env.OC_TARGET || "http://127.0.0.1:4097"
const PORT = Number(process.env.PORT || 4096)
const HOST = process.env.HOST || "127.0.0.1"

// LaTeX 编译核验内核（复用 opencode 工具链的 latex_check.py，不重写编译逻辑）。
// server.mjs 在 assets/web/，内核在 assets/opencode/scripts/，故默认相对定位上一级。
const __DIR = fileURLToPath(new URL(".", import.meta.url))
const LATEX_CHECK =
  process.env.FAMOU_LATEX_CHECK || join(__DIR, "..", "opencode", "scripts", "latex_check.py")
const PY = process.env.ARC_PYTHON || "python3"

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".jsx": "text/javascript; charset=utf-8",
  ".tsx": "text/javascript; charset=utf-8",
  ".ts": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  // 二进制产物（图/PDF/Office）——/raw 路由按真实字节 + 正确 content-type 返回，
  // 而非 opencode 的 /file/content（只能返回文本，二进制会变乱码）。
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".bmp": "image/bmp",
  ".ico": "image/x-icon",
  ".pdf": "application/pdf",
  ".txt": "text/plain; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".doc": "application/msword",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
// 浏览器能内联预览的类型（图/PDF/纯文本）→ inline；其余（Office 等）→ attachment 触发下载。
const INLINE = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg",
  ".pdf", ".txt", ".csv", ".html", ".json",
])

// ── Egress 正向代理（按需开启；不设环境变量则保持直连，行为不变）────────────────
// 为什么：这台跳板机**直连**外网（arxiv/doi/esm.sh）极慢甚至超时（实测 45s 下不完一个 PDF），
// 走出口代理后 0.6s 完整拿到。Node 原生 http/https.request 不认 HTTPS_PROXY，需手动建隧道：
//   https 目标 → HTTP CONNECT 隧道 + 在隧道 socket 上跑 TLS；
//   http  目标 → 绝对形式（absolute-form）请求直发代理。
// 凭证只从环境变量读，绝不硬编码/落盘/打日志。
function proxyEnv() {
  const v =
    process.env.HTTPS_PROXY || process.env.https_proxy ||
    process.env.ALL_PROXY || process.env.all_proxy || ""
  if (!v) return null
  let u
  try { u = new URL(v) } catch { return null }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null
  const auth =
    u.username || u.password
      ? "Basic " +
        Buffer.from(
          decodeURIComponent(u.username) + ":" + decodeURIComponent(u.password),
        ).toString("base64")
      : null
  return { host: u.hostname, port: Number(u.port) || (u.protocol === "https:" ? 443 : 80), auth }
}
// 启动时解析一次（进程生命周期内 env 不变）。
const PROXY = proxyEnv()
if (PROXY) console.log(`[famou-web] egress 经正向代理 ${PROXY.host}:${PROXY.port}（凭证从环境变量读取，不落盘）`)

// 为 https 目标建「CONNECT 隧道 + TLS」的自定义 Agent。覆写 createConnection，
// 让 https.request 透明地走代理；keepAlive 让重定向链与 body 复用同一条隧道。
function tunnelAgent(targetUrl) {
  const servername = targetUrl.hostname
  const tgtPort = Number(targetUrl.port) || 443
  const agent = new https.Agent({ keepAlive: true, maxSockets: 8 })
  agent.createConnection = (_opts, cb) => {
    const proxySock = net.connect({ host: PROXY.host, port: PROXY.port })
    let settled = false
    const fail = (err) => {
      if (settled) return
      settled = true
      try { proxySock.destroy() } catch {}
      cb(err) // → 冒泡成 https.request 的 'error' → 既有 502 处理
    }
    const t = setTimeout(() => fail(new Error("proxy CONNECT timeout")), 15000)
    proxySock.once("error", fail)
    proxySock.once("connect", () => {
      let head = `CONNECT ${servername}:${tgtPort} HTTP/1.1\r\n` + `Host: ${servername}:${tgtPort}\r\n`
      if (PROXY.auth) head += `Proxy-Authorization: ${PROXY.auth}\r\n`
      head += "\r\n"
      proxySock.write(head)
    })
    let buf = Buffer.alloc(0)
    const onData = (chunk) => {
      buf = Buffer.concat([buf, chunk])
      const i = buf.indexOf("\r\n\r\n")
      if (i === -1) {
        if (buf.length > 64 * 1024) fail(new Error("proxy CONNECT header too large"))
        return
      }
      proxySock.removeListener("data", onData)
      const statusLine = buf.slice(0, buf.indexOf("\r\n")).toString("latin1")
      const m = /^HTTP\/1\.[01]\s+(\d{3})/.exec(statusLine)
      if (!m || m[1] !== "200") return fail(new Error("proxy CONNECT 失败: " + statusLine))
      clearTimeout(t)
      settled = true
      proxySock.removeListener("error", fail)
      const tlsSock = tls.connect({ socket: proxySock, servername })
      tlsSock.once("error", () => { try { proxySock.destroy() } catch {} })
      cb(null, tlsSock)
    }
    proxySock.on("data", onData)
  }
  return agent
}

// 分发：设了代理时，https → {agent}，http → {rewrite:绝对形式直发代理}；没设 → {}（直连）。
function egress(targetUrl) {
  if (!PROXY) return {}
  if (targetUrl.protocol === "https:") return { agent: tunnelAgent(targetUrl) }
  const headers = {}
  if (PROXY.auth) headers["proxy-authorization"] = PROXY.auth
  return { rewrite: { host: PROXY.host, port: PROXY.port, path: targetUrl.href, headers } }
}

// Proxy /oc/* → opencode serve (handles SSE by piping the raw stream).
function proxy(req, res) {
  const target = new URL(OC_TARGET)
  const path = req.url.replace(/^\/oc/, "") || "/"
  const opts = {
    hostname: target.hostname,
    port: target.port,
    path,
    method: req.method,
    headers: { ...req.headers, host: target.host },
  }
  const up = http.request(opts, (upRes) => {
    res.writeHead(upRes.statusCode || 502, upRes.headers)
    upRes.pipe(res)
  })
  up.on("error", (e) => {
    res.writeHead(502, { "content-type": "text/plain" })
    res.end("proxy error: " + e.message)
  })
  req.pipe(up)
}

// ── CDN mirror ───────────────────────────────────────────────────────────────
// /_esm/*   → https://esm.sh/*    (JS bodies rewritten so transitive imports stay local)
// /_unpkg/* → https://unpkg.com/* (Babel standalone, passthrough)
// esm.sh emits root-relative import specifiers like  from"/react@18.3.1/es2022/react.bundle.mjs".
// Left as-is the browser would resolve them against localhost → miss. We rewrite import/export
// specifiers that start with "/" (and any absolute https://esm.sh/ URL) to the "/_esm/" prefix,
// so the whole dependency closure is fetched through this server. Bare specifiers ("react", …)
// are left untouched and resolved by the page's import map.
function rewriteEsm(body) {
  return body
    .split("https://esm.sh/").join("/_esm/")
    .replace(/(\bfrom\s*["'])\//g, "$1/_esm/")
    .replace(/(\bimport\s*["'])\//g, "$1/_esm/")
    .replace(/(\bimport\s*\(\s*["'])\//g, "$1/_esm/")
}

function cdnProxy(req, res, upstream, rewrite, prefix) {
  const restFull = req.url.slice(prefix.length) || "/"
  const key = encodeURIComponent(prefix + restFull).replace(/%/g, "_").slice(0, 180)
  const bodyFile = join(CDN_CACHE, key + ".bin")
  const ctFile = join(CDN_CACHE, key + ".ct")

  // 1) 缓存命中 → 本地直出
  Promise.all([readFile(bodyFile), readFile(ctFile, "utf-8")])
    .then(([buf, ct]) => {
      res.writeHead(200, { "content-type": ct.trim(), "cache-control": "public, max-age=86400" })
      res.end(buf)
    })
    .catch(() => fetchUpstream(restFull, upstream, rewrite, prefix, 0, (code, ct, buf) => {
      // 2) miss → 回源后落盘（仅成功的 JS/资源）并响应
      if (code === 200 && buf) {
        mkdir(CDN_CACHE, { recursive: true })
          .then(() => Promise.all([writeFile(bodyFile, buf), writeFile(ctFile, ct)]))
          .catch(() => {})
      }
      res.writeHead(code, {
        "content-type": ct,
        "cache-control": "public, max-age=86400",
        "access-control-allow-origin": "*",
      })
      res.end(buf)
    }))
}

// 回源抓取（family:4 规避 IPv6 卡死；跟随 30x；rewrite 时把 esm.sh 的 root-relative/绝对导入改写到 /_esm/）。
function fetchUpstream(rest, upstream, rewrite, prefix, redirects, done) {
  if (!rest.startsWith("/")) rest = "/" + rest
  let url
  try {
    url = new URL(upstream + rest)
  } catch {
    return done(400, "text/plain", Buffer.from("bad cdn url"))
  }
  const eg = egress(url) // CDN 回源恒 https → {agent} 或 {}（直连）
  // done 只能调一次：多条路径（uRes end / uRes error / req error / 超时）都可能触发，重复调用会让
  // cdnProxy 的 done 二次 writeHead → ERR_HTTP_HEADERS_SENT 崩进程。finish 守卫 + 清定时器。
  let finished = false
  const timer = setTimeout(() => up.destroy(new Error("egress timeout")), 45000)
  const finish = (c, ct, b) => {
    if (finished) return
    finished = true
    clearTimeout(timer)
    done(c, ct, b)
  }
  const up = https.request(
    url,
    { method: "GET", family: 4, headers: { "user-agent": "famou-web", "accept-encoding": "identity" }, ...eg },
    (uRes) => {
      const code = uRes.statusCode || 502
      if (code >= 300 && code < 400 && uRes.headers.location && redirects < 4) {
        uRes.resume()
        clearTimeout(timer) // 交棒给下一跳的定时器
        const loc = uRes.headers.location
        const next = loc.startsWith("http") ? loc.replace(/^https?:\/\/[^/]+/, "") : loc
        return fetchUpstream(next, upstream, rewrite, prefix, redirects + 1, finish)
      }
      const ct = uRes.headers["content-type"] || "application/octet-stream"
      const isJs = /javascript|ecmascript|typescript/i.test(ct)
      const chunks = []
      uRes.on("data", (c) => chunks.push(c))
      uRes.on("end", () => {
        let buf = Buffer.concat(chunks)
        if (rewrite && isJs) buf = Buffer.from(rewriteEsm(buf.toString("utf-8")), "utf-8")
        finish(code, ct, buf)
      })
      uRes.on("error", () => finish(502, "text/plain", Buffer.from("cdn read error")))
    },
  )
  up.on("error", (e) => {
    finish(
      502,
      "text/plain",
      Buffer.from("cdn proxy error: " + e.message + "\n（运行 famou-scientist web 的机器需能联网拉依赖 " + url.host + "）"),
    )
  })
  up.end()
}

// Serve raw file bytes for binary 产物（图/PDF/Office），with the correct content-type.
// opencode 的 /file/content 只返回文本，二进制会变乱码——这条路绕过它直接读盘。
async function serveRaw(req, res) {
  const q = new URL(req.url, "http://x").searchParams
  const rel = q.get("path") || ""
  if (!rel) { res.writeHead(400, { "content-type": "text/plain" }); res.end("missing path"); return }
  // 解析到 PROJECT_ROOT 之内，挡住 ../ 越界
  const filePath = resolve(PROJECT_ROOT, rel)
  if (filePath !== PROJECT_ROOT && !filePath.startsWith(PROJECT_ROOT + "/")) {
    res.writeHead(403, { "content-type": "text/plain" }); res.end("forbidden"); return
  }
  try {
    const body = await readFile(filePath)
    const ext = extname(filePath).toLowerCase()
    const disp = INLINE.has(ext) ? "inline" : "attachment"
    // 文件名可能含中文/空格等非 ASCII —— HTTP 头只允许 ASCII，直接塞进 filename="…" 会抛
    // ERR_INVALID_CHAR。按 RFC 5987 用 filename*=UTF-8''<pct-encoded>，并给 ASCII filename 兜底。
    const fname = basename(filePath)
    const asciiName = fname.replace(/[^\x20-\x7e]/g, "_").replace(/"/g, "")
    res.writeHead(200, {
      "content-type": MIME[ext] || "application/octet-stream",
      "content-disposition": `${disp}; filename="${asciiName}"; filename*=UTF-8''${encodeURIComponent(fname)}`,
      "cache-control": "no-cache",
    })
    res.end(body)
  } catch (e) {
    // 无 cache-control 时部分浏览器会把这次 404 记成"这个 URL 就是坏的"，哪怕文件之后写好了
    // 也不会重新请求（同一 <img src> 再也加不出来——实测踩过：生图工具落盘晚了半步，图片
    // 永久预览不出来，直到硬刷新绕过缓存）。显式 no-store，保证文件写好后下次请求能重新探测。
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" })
    res.end("not found: " + rel)
  }
}

// 一键下载整个 workspace：把 run 目录流式打包成 .tar.gz（zip 集群未装，用 tar）。
// GET /archive?path=<run目录相对路径>。路径安全照搬 serveRaw：解析进 PROJECT_ROOT、挡 ../ 越界。
async function serveArchive(req, res) {
  const q = new URL(req.url, "http://x").searchParams
  const rel = q.get("path") || ""
  if (!rel) { res.writeHead(400, { "content-type": "text/plain" }); res.end("missing path"); return }
  const dirPath = resolve(PROJECT_ROOT, rel)
  if (dirPath !== PROJECT_ROOT && !dirPath.startsWith(PROJECT_ROOT + "/")) {
    res.writeHead(403, { "content-type": "text/plain" }); res.end("forbidden"); return
  }
  // 确认是目录（readdir 对文件抛 ENOTDIR、对缺失抛 ENOENT）。
  try { await readdir(dirPath) } catch {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }); res.end("not a directory: " + rel); return
  }
  // 以父目录为基准打包目录本身，使解开后带一层同名目录。
  const parentDir = resolve(dirPath, "..")
  const baseName = basename(dirPath) || "workspace"
  const asciiName = (baseName + ".tar.gz").replace(/[^\x20-\x7e]/g, "_").replace(/"/g, "")
  const child = spawn("tar", ["-czf", "-", "-C", parentDir, baseName])
  let headed = false
  // 首个字节到达再落 200 头，好让 spawn 失败（如 tar 缺失）仍能干净返回 500。
  function ensureHead() {
    if (headed) return
    headed = true
    res.writeHead(200, {
      "content-type": "application/gzip",
      "content-disposition": `attachment; filename="${asciiName}"; filename*=UTF-8''${encodeURIComponent(baseName + ".tar.gz")}`,
      "cache-control": "no-cache",
    })
  }
  child.on("error", (e) => {
    if (!headed) { res.writeHead(500, { "content-type": "text/plain; charset=utf-8" }); res.end("archive failed: " + e.message) }
    else { try { res.destroy() } catch {} }
  })
  child.stdout.on("data", (chunk) => { ensureHead(); res.write(chunk) })
  child.stdout.on("end", () => { ensureHead(); res.end() })
  // 客户端中断 → 杀掉 tar，防僵尸进程堆积。
  res.on("close", () => { if (!child.killed) { try { child.kill() } catch {} } })
}

// 上传写盘：POST /upload，body JSON { runDir, name, mime, dataB64 }。
// opencode 没有原生「上传到工作目录」的 API（/file* 全 GET），故旁路在此把浏览器传来的文件落盘，
// 再由前端把相对路径写进消息文本，交给 agent 用工具读取（避免大文件内联撑爆上下文 / 模型不支持 PDF）。
// 安全：与 serveRaw 同款 PROJECT_ROOT 守卫 + basename 去路径 + 扩展名白名单 + 同名加序号防覆盖。
const UPLOAD_EXT = new Set([
  ".pdf", ".txt", ".md", ".csv", ".tsv", ".json", ".tex", ".bib",
  ".py", ".yaml", ".yml", ".toml", ".ipynb", ".docx", ".xlsx", ".xls", ".doc",
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
])
const UPLOAD_BODY_MAX = 70 * 1024 * 1024 // ~50MB 文件 + base64 膨胀
// 会话 ID 清洗：只留安全字符，防路径注入；空则退回 _misc。用于 _inbox 子目录隔离。
function sanitizeSid(sid) {
  const s = String(sid || "").replace(/[^A-Za-z0-9_-]/g, "")
  return s || "_misc"
}
// 知识库分组名：只取 basename、挡 ../ 与路径分隔符（单层分组，不允许建出嵌套目录），限长防滥用。
// 空串＝根目录（前端语义上的"未分类"，不建实际子目录）。
function sanitizeGroupName(name) {
  const s = basename(String(name || "").trim()).replace(/[\x00-\x1f<>:"|?*\\/]/g, "").trim()
  return s.slice(0, 60)
}
async function serveUpload(req, res) {
  const sendJson = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify(obj))
  }
  // 收 body（带上限，超了即断，防内存炸）
  let buf = Buffer.alloc(0)
  let aborted = false
  try {
    await new Promise((resolve2, reject) => {
      req.on("data", (c) => {
        if (aborted) return
        buf = Buffer.concat([buf, c])
        if (buf.length > UPLOAD_BODY_MAX) { aborted = true; reject(new Error("too large")); try { req.destroy() } catch {} }
      })
      req.on("end", resolve2)
      req.on("error", reject)
    })
  } catch (e) {
    return sendJson(413, { ok: false, error: aborted ? "文件过大（上限 50MB）" : "读取请求失败：" + e.message })
  }
  let body
  try { body = JSON.parse(buf.toString("utf8")) } catch { return sendJson(400, { ok: false, error: "body 非 JSON" }) }
  const name = String(body.name || "").trim()
  const dataB64 = String(body.dataB64 || "")
  const runDir = String(body.runDir || "").trim()
  const sid = sanitizeSid(body.sessionID)
  if (!name || !dataB64) return sendJson(400, { ok: false, error: "缺 name 或 dataB64" })

  // 文件名：只取 basename，挡 ../ 与绝对路径；校验扩展名白名单
  const safeName = basename(name).replace(/[\x00-\x1f<>:"|?*\\/]/g, "").trim()
  const ext = extname(safeName).toLowerCase()
  if (!safeName || safeName.startsWith(".")) return sendJson(400, { ok: false, error: "非法文件名" })
  if (!UPLOAD_EXT.has(ext)) return sendJson(415, { ok: false, error: "不支持的文件类型：" + (ext || "(无扩展名)") })

  // 目标目录：dest=kb → 全局知识库 knowledge-base/[<分组>/]（跨会话共享，分组单层、可选）；
  // 否则有 runDir 落 <runDir>/uploads/；再否则落 research-runs/_inbox/<会话ID>/（按会话隔离）
  let relDir
  if (String(body.dest || "") === "kb") {
    const kbGroup = sanitizeGroupName(body.kbGroup)
    relDir = kbGroup ? join("knowledge-base", kbGroup) : "knowledge-base"
  } else if (runDir && /^research-runs\//.test(runDir)) {
    relDir = join(runDir, "uploads")
  } else {
    relDir = join("research-runs", "_inbox", sid)
  }
  const absDir = resolve(PROJECT_ROOT, relDir)
  if (absDir !== PROJECT_ROOT && !absDir.startsWith(PROJECT_ROOT + "/")) {
    return sendJson(403, { ok: false, error: "forbidden" })
  }
  // 落盘：同名加序号防覆盖
  let bytes
  try { bytes = Buffer.from(dataB64, "base64") } catch { return sendJson(400, { ok: false, error: "base64 解码失败" }) }
  if (bytes.length > UPLOAD_BODY_MAX) return sendJson(413, { ok: false, error: "文件过大（上限 50MB）" })
  try {
    await mkdir(absDir, { recursive: true })
    const stem = safeName.slice(0, safeName.length - ext.length)
    let finalName = safeName
    let abs = join(absDir, finalName)
    for (let i = 1; i < 1000; i++) {
      try { await readFile(abs); finalName = `${stem}-${i}${ext}`; abs = join(absDir, finalName) } // 已存在→换名
      catch { break } // 不存在→可用
    }
    await writeFile(abs, bytes)
    const relPath = relative(PROJECT_ROOT, abs)
    return sendJson(200, { ok: true, path: relPath, abs, bytes: bytes.length })
  } catch (e) {
    return sendJson(500, { ok: false, error: "写盘失败：" + e.message })
  }
}

// 删除知识库文档：POST /kb/delete，body { path }。仅限 knowledge-base/ 下（防越界删除他处文件）。
async function serveKbDelete(req, res) {
  const sendJson = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify(obj))
  }
  let buf = Buffer.alloc(0), aborted = false
  try {
    await new Promise((resolve2, reject) => {
      req.on("data", (c) => { if (aborted) return; buf = Buffer.concat([buf, c]); if (buf.length > 1 << 20) { aborted = true; reject(new Error("too large")); try { req.destroy() } catch {} } })
      req.on("end", resolve2); req.on("error", reject)
    })
  } catch { return sendJson(400, { ok: false, error: "读取请求失败" }) }
  let body
  try { body = JSON.parse(buf.toString("utf8")) } catch { return sendJson(400, { ok: false, error: "body 非 JSON" }) }
  const rel = String(body.path || "").trim()
  if (!rel) return sendJson(400, { ok: false, error: "缺 path" })
  const abs = resolve(PROJECT_ROOT, rel)
  const kbRoot = resolve(PROJECT_ROOT, "knowledge-base")
  // 只允许删 knowledge-base/ 下的文件（挡 ../ 越界、挡删目录本身）
  if (abs === kbRoot || !abs.startsWith(kbRoot + "/")) {
    return sendJson(403, { ok: false, error: "forbidden" })
  }
  try {
    await unlink(abs)
    return sendJson(200, { ok: true, path: rel })
  } catch (e) {
    if (e && e.code === "ENOENT") return sendJson(404, { ok: false, error: "文件不存在" })
    return sendJson(500, { ok: false, error: "删除失败：" + e.message })
  }
}

// 新建知识库分组：POST /kb/mkdir，body { name }。单层目录，落 knowledge-base/<name>/，幂等（已存在不报错）。
async function serveKbMkdir(req, res) {
  const sendJson = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify(obj))
  }
  let buf = Buffer.alloc(0), aborted = false
  try {
    await new Promise((resolve2, reject) => {
      req.on("data", (c) => { if (aborted) return; buf = Buffer.concat([buf, c]); if (buf.length > 1 << 20) { aborted = true; reject(new Error("too large")); try { req.destroy() } catch {} } })
      req.on("end", resolve2); req.on("error", reject)
    })
  } catch { return sendJson(400, { ok: false, error: "读取请求失败" }) }
  let body
  try { body = JSON.parse(buf.toString("utf8")) } catch { return sendJson(400, { ok: false, error: "body 非 JSON" }) }
  const name = sanitizeGroupName(body.name)
  if (!name) return sendJson(400, { ok: false, error: "分组名非法或为空" })
  const abs = resolve(PROJECT_ROOT, join("knowledge-base", name))
  const kbRoot = resolve(PROJECT_ROOT, "knowledge-base")
  if (abs === kbRoot || !abs.startsWith(kbRoot + "/")) return sendJson(403, { ok: false, error: "forbidden" })
  try {
    await mkdir(abs, { recursive: true })
    return sendJson(200, { ok: true, name })
  } catch (e) {
    return sendJson(500, { ok: false, error: "建组失败：" + e.message })
  }
}

// MoonLog：GET /moonlog/list（可用日期列表）+ GET /moonlog/<date>（某天的编译结果）。
// 只读——编译只由 moonlog.mjs 里的调度器发起，这里不提供手动触发端点。
async function serveMoonlogList(req, res) {
  const dates = await listMoonlogDates(PROJECT_ROOT)
  res.writeHead(200, { "content-type": "application/json; charset=utf-8" })
  res.end(JSON.stringify({ dates }))
}
async function serveMoonlogGet(req, res, date) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    res.writeHead(400, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify({ error: "bad date" }))
    return
  }
  const data = await readMoonlog(PROJECT_ROOT, date)
  if (!data) {
    res.writeHead(404, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify({ error: "not found" }))
    return
  }
  res.writeHead(200, { "content-type": "application/json; charset=utf-8" })
  res.end(JSON.stringify(data))
}

// 迁移收拢：POST /upload/migrate，body { sessionID, runDir }。
// 研究建了主题目录后，把 research-runs/_inbox/<会话ID>/ 的上传文件搬到 <runDir>/uploads/，
// 与产物收拢到一起。前端据返回的 from→to 映射更新它记的上传路径（避免大屏点开还指向旧 _inbox）。
async function serveUploadMigrate(req, res) {
  const sendJson = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify(obj))
  }
  let buf = Buffer.alloc(0), aborted = false
  try {
    await new Promise((resolve2, reject) => {
      req.on("data", (c) => { if (aborted) return; buf = Buffer.concat([buf, c]); if (buf.length > 1 << 20) { aborted = true; reject(new Error("too large")); try { req.destroy() } catch {} } })
      req.on("end", resolve2); req.on("error", reject)
    })
  } catch { return sendJson(400, { ok: false, error: "读取请求失败" }) }
  let body
  try { body = JSON.parse(buf.toString("utf8")) } catch { return sendJson(400, { ok: false, error: "body 非 JSON" }) }
  const sid = sanitizeSid(body.sessionID)
  const runDir = String(body.runDir || "").trim()
  if (!runDir || !/^research-runs\//.test(runDir)) return sendJson(400, { ok: false, error: "runDir 非法" })

  const srcRel = join("research-runs", "_inbox", sid)
  const srcAbs = resolve(PROJECT_ROOT, srcRel)
  const dstRel = join(runDir, "uploads")
  const dstAbs = resolve(PROJECT_ROOT, dstRel)
  // 路径守卫：源/目标都必须在 PROJECT_ROOT 内
  for (const p of [srcAbs, dstAbs]) {
    if (p !== PROJECT_ROOT && !p.startsWith(PROJECT_ROOT + "/")) return sendJson(403, { ok: false, error: "forbidden" })
  }
  let names
  try { names = await readdir(srcAbs) } catch { return sendJson(200, { ok: true, moved: [] }) } // 源不存在=幂等空
  const files = []
  for (const n of names) { if (!n.startsWith(".")) files.push(n) }
  if (!files.length) { try { await rmdir(srcAbs) } catch {}; return sendJson(200, { ok: true, moved: [] }) }

  const moved = []
  try {
    await mkdir(dstAbs, { recursive: true })
    for (const n of files) {
      const from = join(srcAbs, n)
      const ext = extname(n)
      const stem = n.slice(0, n.length - ext.length)
      // 目标同名加序号防覆盖
      let finalName = n, to = join(dstAbs, finalName)
      for (let i = 1; i < 1000; i++) {
        try { await readFile(to); finalName = `${stem}-${i}${ext}`; to = join(dstAbs, finalName) } catch { break }
      }
      try {
        await rename(from, to)
      } catch (e) {
        if (e && e.code === "EXDEV") { await copyFile(from, to); await unlink(from) } // 跨设备兜底
        else throw e
      }
      moved.push({ from: relative(PROJECT_ROOT, from), to: relative(PROJECT_ROOT, to) })
    }
    try { await rmdir(srcAbs) } catch {} // 清空的 _inbox/<sid>/ 删掉（非空则忽略）
    return sendJson(200, { ok: true, moved })
  } catch (e) {
    return sendJson(500, { ok: false, error: "迁移失败：" + e.message, moved })
  }
}


// 让中栏「文献大屏」能 iframe 嵌入全文（绕过跨域 + 跳板机浏览器直连不了外网）。
// 安全：仅白名单 host + 只读 GET（不做任意 URL 转发，防 SSRF/被当开放代理）。
const PAPER_HOSTS = new Set([
  "arxiv.org", "www.arxiv.org", "export.arxiv.org",
  "ar5iv.org", "ar5iv.labs.arxiv.org",
  "doi.org", "dx.doi.org",
  // 知名开放获取（OA）站点——这些是公共论文库/出版社的免费全文 PDF 落点，
  // 加入白名单让「免费但非 arXiv」的论文也能在大屏内嵌全文（仍只读 GET、防 SSRF）。
  "ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "pmc.ncbi.nlm.nih.gov",
  "drops.dagstuhl.de",
  "mdpi.com", "www.mdpi.com",
  "openreview.net",
  "aclanthology.org",
  "proceedings.mlr.press",
  "papers.nips.cc", "proceedings.neurips.cc",
  "biorxiv.org", "www.biorxiv.org",
  "medrxiv.org", "www.medrxiv.org",
  // 主流出版社 / 学会页面：多为付费墙——能渲染文章落地页（摘要/参考文献），
  // OA 文章（SpringerOpen/BMC、PLOS、Frontiers、OUP-OA 等）可直出全文 PDF。
  // 仍是白名单：只放行已知公共出版社 host（含其登录跳转域），不开放任意 URL —— SSRF 防护不变。
  "link.springer.com", "idp.springer.com", "springer.com", "www.springer.com",
  "www.nature.com", "nature.com",
  "onlinelibrary.wiley.com",
  "www.sciencedirect.com", "sciencedirect.com", "linkinghub.elsevier.com",
  "dl.acm.org",
  "ieeexplore.ieee.org",
  "academic.oup.com",
  "journals.plos.org",
  "www.frontiersin.org",
  "journals.aps.org", "link.aps.org",
  "www.tandfonline.com",
  "www.cambridge.org",
  "iopscience.iop.org",
  "pubs.acs.org",
])
function _paperHostOk(h) {
  h = (h || "").toLowerCase()
  return PAPER_HOSTS.has(h)
}
// 大屏 iframe 里的友好错误页（深色、居中、可点「打开原文」在新标签查看）——
// 比裸 text「host not allowed / upstream 403」对用户友好得多。
function paperErrPage(res, code, title, detail, openUrl) {
  const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))
  const link = openUrl
    ? `<p style="margin-top:16px"><a href="${esc(openUrl)}" target="_blank" rel="noreferrer" style="color:#6ea8fe;text-decoration:none">在新标签打开原文 ↗</a></p>`
    : ""
  res.writeHead(code, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" })
  res.end(
    `<!doctype html><meta charset="utf-8"><body style="margin:0;display:flex;align-items:center;justify-content:center;height:100vh;background:#0f1117;color:#c8cedb;font:14px/1.7 -apple-system,'PingFang SC',sans-serif">` +
    `<div style="max-width:540px;padding:28px;text-align:center">` +
    `<div style="font-size:34px;margin-bottom:10px">📄</div>` +
    `<div style="font-size:16px;color:#e6e8ee;margin-bottom:8px">${esc(title)}</div>` +
    `<div style="color:#9aa3b2">${esc(detail)}</div>${link}</div></body>`,
  )
}
function servePaper(req, res) {
  const q = new URL(req.url, "http://x").searchParams
  const raw = q.get("url") || ""
  let target
  try { target = new URL(raw) } catch { res.writeHead(400, { "content-type": "text/plain" }); res.end("bad url"); return }
  if (target.protocol !== "https:" && target.protocol !== "http:") {
    res.writeHead(400, { "content-type": "text/plain" }); res.end("bad scheme"); return
  }
  if (!_paperHostOk(target.hostname)) {
    paperErrPage(res, 403, "无法在大屏内嵌该全文",
      "来源站点（" + target.hostname + "）不在可嵌入白名单内（多为付费墙或暂未收录的出版社）。", raw)
    return
  }
  fetchPaper(target, 0, res)
}
// 跟随 30x（family:4 规避 IPv6；每跳都重新校验白名单——doi.org 会跳到出版社域，跳出白名单即放弃）。
function fetchPaper(target, redirects, res) {
  const eg = egress(target) // 设了代理：https→{agent}，http→{rewrite 绝对形式发代理}；没设→{}
  const baseHeaders = { "user-agent": "famou-web", "accept": "application/pdf,text/html,*/*" }
  const handle = (uRes) => {
    const code = uRes.statusCode || 502
    if (code >= 300 && code < 400 && uRes.headers.location && redirects < 5) {
      uRes.resume()
      let next
      try { next = new URL(uRes.headers.location, target) } catch { res.writeHead(502, { "content-type": "text/plain" }); res.end("bad redirect"); return }
      if (!_paperHostOk(next.hostname)) {
        paperErrPage(res, 409, "全文跳转到了未收录站点",
          "跳转到 " + next.hostname + "（多为付费墙）。可用下方「打开原文」在新标签查看。", next.href)
        return
      }
      return fetchPaper(next, redirects + 1, res) // 每跳重算 egress：http→https 自动从 rewrite 切到 tunnel
    }
    if (code >= 400) {
      uRes.resume()
      paperErrPage(res, 502, "出版社未返回可嵌入全文",
        "上游返回 " + code + "（可能需订阅，或拦截了内嵌请求）。可用下方「打开原文」在新标签查看。", target.href)
      return
    }
    // 成功响应：但有些订阅墙会回 200 + 空 body（如 springer 未授权的 content/pdf 是 0 字节 PDF），
    // iframe 会渲染成空白。故**推迟写头到收到第一个字节**；若读完仍 0 字节 → 当作"墙未授权"给友好页。
    let started = false
    uRes.once("data", (first) => {
      started = true
      res.writeHead(200, {
        "content-type": uRes.headers["content-type"] || "application/pdf",
        "cache-control": "no-store",
        "content-disposition": "inline", // 浏览器内联渲染 PDF/HTML（而非下载）
      })
      res.write(first)
      uRes.pipe(res) // 余下字节继续流式输出（首块已手动写出）
    })
    uRes.once("end", () => {
      if (started) return
      paperErrPage(res, 502, "出版社未返回全文内容",
        "上游返回空响应（多为订阅墙未授权）。可用下方「打开原文」在新标签查看。", target.href)
    })
    uRes.on("error", () => {
      if (started) { try { res.destroy() } catch {}; return }
      if (res.headersSent || res.writableEnded) return
      paperErrPage(res, 502, "全文加载中断", "读取上游响应出错。可用下方「打开原文」在新标签查看。", target.href)
    })
  }
  let up
  if (eg.rewrite) {
    // http 目标：绝对形式（path=完整 URL）明文发给代理。连接目标是代理，故用 http。
    up = http.request(
      { host: eg.rewrite.host, port: eg.rewrite.port, path: eg.rewrite.path, method: "GET", headers: { ...eg.rewrite.headers, ...baseHeaders } },
      handle,
    )
  } else {
    const lib = target.protocol === "http:" ? http : https
    up = lib.request(
      target,
      { method: "GET", family: 4, headers: baseHeaders, ...(eg.agent ? { agent: eg.agent } : {}) },
      handle,
    )
  }
  // 仅在「迟迟拿不到响应」时兜底中断（防 body 中途 stall 挂死）；正常完成即清除，避免 keepAlive
  // socket 在成功后被 45s 定时器误 destroy → 触发下面的 error。
  const timer = setTimeout(() => up.destroy(new Error("egress timeout")), 45000)
  up.on("close", () => clearTimeout(timer))
  up.on("error", (e) => {
    clearTimeout(timer)
    // 头已发/响应已结束（如成功 pipe 中途上游断、或成功后 keepAlive socket 超时）→ 不能再写头，
    // 否则 ERR_HTTP_HEADERS_SENT 未捕获会**崩整个进程**（前端随之退出）。这种情况直接断连即可。
    if (res.headersSent || res.writableEnded) { try { res.destroy() } catch {}; return }
    paperErrPage(res, 502, "全文加载失败",
      "代理拉取出错：" + e.message + "（运行 web 的机器需能访问 " + target.host + "）。可用下方「打开原文」在新标签查看。", target.href)
  })
  up.end()
}


// 与 agent 的 arc_latex_check 走同一内核：web 手动编与 Stage 22 自动编结论一致。
// GET /compile?path=<run 内的 .tex 相对路径>&venue=<可选>
function serveCompile(req, res) {
  const sendJson = (code, obj) => {
    res.writeHead(code, { "content-type": "application/json; charset=utf-8", "cache-control": "no-cache" })
    res.end(JSON.stringify(obj))
  }
  const q = new URL(req.url, "http://x").searchParams
  const rel = q.get("path") || ""
  const venue = q.get("venue") || ""
  if (!rel) return sendJson(400, { ok: false, severity: "ERROR", error: "missing path" })
  // 只接受 .tex；并解析到 PROJECT_ROOT 之内，挡住 ../ 越界（与 serveRaw 同款守卫）。
  if (!rel.toLowerCase().endsWith(".tex"))
    return sendJson(400, { ok: false, severity: "ERROR", error: "path must be a .tex file" })
  const texAbs = resolve(PROJECT_ROOT, rel)
  if (texAbs !== PROJECT_ROOT && !texAbs.startsWith(PROJECT_ROOT + "/"))
    return sendJson(403, { ok: false, severity: "ERROR", error: "forbidden" })

  // execFile 数组传参，不过 shell（防注入）；latexmk 首编可能装宏包，给足超时。
  execFile(
    PY,
    [LATEX_CHECK, texAbs, "--venue", venue],
    { timeout: 210000, maxBuffer: 4 * 1024 * 1024 },
    (err, stdout, stderr) => {
      if (err && !stdout) {
        const why = err.killed ? "编译超时（>210s）" : String((stderr || err.message || "").slice(0, 500))
        return sendJson(200, { ok: false, severity: "ERROR", error: "编译失败：" + why })
      }
      let data
      try {
        data = JSON.parse(stdout)
      } catch {
        return sendJson(200, { ok: false, severity: "ERROR", error: "内核返回非 JSON：" + String(stdout).slice(0, 300) })
      }
      // 绝对 pdf_path → 相对 PROJECT_ROOT，供前端经 /raw 显示
      let pdf = ""
      if (data.pdf_path) {
        const r = relative(PROJECT_ROOT, data.pdf_path)
        if (r && !r.startsWith("..")) pdf = r
      }
      sendJson(200, {
        ok: !!data.ok,
        severity: data.severity || "ERROR",
        pdf,
        pages: data.pages ?? null,
        page_limit: data.page_limit ?? null,
        venue: data.venue || "",
        engine: data.engine || "",
        checks: data.checks || [],
        log_tail: data.log_tail || "",
        error: data.error || "",
      })
    },
  )
}

async function serveStatic(req, res) {
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0])
  if (urlPath === "/") urlPath = "/index.html"

  // /src/* → raw source files (browser transpiles .tsx via Babel)
  // everything else → public/
  const base = urlPath.startsWith("/src/") ? join(SRC, "..") : ROOT
  const filePath = normalize(join(base, urlPath))
  if (!filePath.startsWith(normalize(base))) {
    res.writeHead(403)
    res.end("forbidden")
    return
  }
  try {
    let body = await readFile(filePath)
    // index.html：注入当前显示用户名 + 是否锁定到前端。
    //   __FAMOU_USER__      = 环境变量(权威) > famou_user cookie > 空
    //   __FAMOU_USER_LOCKED__ = true 表示由环境变量钉死，前端不可改
    // 无口令、且用户还没设过名字时 __FAMOU_USER__ 为空 → 前端弹「设置用户名（可跳过）」。
    if (filePath.endsWith("index.html")) {
      const cookieUser = sanitizeUser(parseCookies(req)[USER_COOKIE])
      const uname = ENV_USER || cookieUser
      const inject = `<script>window.__FAMOU_USER__=${JSON.stringify(uname)};window.__FAMOU_USER_LOCKED__=${ENV_USER ? "true" : "false"};window.__FAMOU_AUTH_ON__=${AUTH_ON ? "true" : "false"}</script>`
      body = Buffer.from(String(body).replace("</head>", inject + "</head>"))
    }
    // 零构建：源码(app.tsx/styles.css)与 index.html 改完即时生效，绝不让浏览器吃旧缓存
    // （否则改了前端、用户硬刷也可能拿到旧版 → "改了没效果/按钮没反应"）。静态资源一律 no-store。
    res.writeHead(200, {
      "content-type": MIME[extname(filePath)] || "application/octet-stream",
      "cache-control": "no-store, must-revalidate",
    })
    res.end(body)
  } catch {
    res.writeHead(404, { "content-type": "text/plain" })
    res.end("not found: " + urlPath)
  }
}

// ── 简单鉴权门禁（单实例口令）─────────────────────────────────────
// 每个用户一个实例、一个人用，故只需「一道登录墙」防外人访问，无需用户表/多租户。
// 凭据：环境变量 FAMOU_ACCESS_PASSWORD。**未设 → 门禁关闭**（保持单机/内网现状，零打扰）。
// 会话：HMAC 签名 cookie（famou_auth=<exp>.<hex-sig>），无状态、无数据库；服务端用同一口令
// 即可校验，重启不失效。口令本身从不写进 cookie。
const AUTH_PASSWORD = process.env.FAMOU_ACCESS_PASSWORD || ""
const AUTH_ON = AUTH_PASSWORD.length > 0
const AUTH_COOKIE = "famou_auth"
const AUTH_TTL_SEC = Number(process.env.FAMOU_ACCESS_TTL_SEC) || 7 * 24 * 3600 // 默认 7 天
// 签名密钥：口令 + 固定盐（避免直接拿口令当 HMAC key）。口令变 → 旧 cookie 自然失效。
const AUTH_SECRET = crypto.createHash("sha256").update("famou-auth:" + AUTH_PASSWORD).digest()

// ── 显示用户名 ──────────────────────────────────────────────────────
// 用户名只用于前端展示（左下角）。存一个带 TTL 的 cookie（famou_user，与登录态同寿命），
// 服务端渲染 index.html 时注入到 window.__FAMOU_USER__。三种来源，优先级从高到低：
//   ① 环境变量 FAMOU_ACCESS_USER —— 部署方钉死，权威、不可前端改（LOCKED）；
//   ② famou_user cookie —— 有口令时在登录页填、无口令时首访填/跳过分配，过期即重来；
//   ③ 空 —— 前端弹「设置用户名」（无口令首访场景）。
// 它不是访问控制凭据（门禁只认 famou_auth），故不签名，改了也只影响自己的显示名。
const USER_COOKIE = "famou_user"
const ENV_USER = (process.env.FAMOU_ACCESS_USER || "").replace(/[\x00-\x1f]/g, "").trim().slice(0, 64)
function randomUser() { return String(crypto.randomInt(10_000_000, 100_000_000)) } // 8 位随机
function sanitizeUser(s) { return String(s || "").replace(/[\x00-\x1f]/g, "").trim().slice(0, 64) }
function userCookie(name, secure) {
  return `${USER_COOKIE}=${encodeURIComponent(name)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${AUTH_TTL_SEC}${secure ? "; Secure" : ""}`
}

function authSign(exp) {
  return crypto.createHmac("sha256", AUTH_SECRET).update(String(exp)).digest("hex")
}
function authMakeCookie() {
  const exp = Math.floor(Date.now() / 1000) + AUTH_TTL_SEC
  return `${exp}.${authSign(exp)}`
}
function authValidCookie(val) {
  if (!val || typeof val !== "string") return false
  const dot = val.indexOf(".")
  if (dot < 0) return false
  const exp = Number(val.slice(0, dot))
  const sig = val.slice(dot + 1)
  if (!Number.isFinite(exp) || exp < Math.floor(Date.now() / 1000)) return false // 过期
  const want = authSign(exp)
  // 常量时间比较，防时序侧信道
  if (sig.length !== want.length) return false
  try { return crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(want)) } catch { return false }
}
function parseCookies(req) {
  const out = {}
  const raw = req.headers.cookie || ""
  for (const pair of raw.split(";")) {
    const i = pair.indexOf("=")
    if (i < 0) continue
    out[pair.slice(0, i).trim()] = decodeURIComponent(pair.slice(i + 1).trim())
  }
  return out
}
function authOk(req) {
  return authValidCookie(parseCookies(req)[AUTH_COOKIE])
}
// 登录页（服务端内联，零依赖；错误时回显提示）。
function authLoginPage(err = "") {
  return `<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>登录 · Famou 研究台</title><style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;
  background:#0f1115;color:#e6e8ee}
.card{width:340px;max-width:90vw;padding:32px 28px;border-radius:16px;background:#171a21;
  border:1px solid #262b36;box-shadow:0 12px 40px rgba(0,0,0,.4)}
.brand{font-size:20px;font-weight:700;margin:0 0 4px;color:#2dd4bf}
.sub{font-size:13px;color:#9aa3b2;margin:0 0 22px}
label{display:block;font-size:12px;color:#9aa3b2;margin:0 0 6px}
input{width:100%;padding:11px 12px;border-radius:9px;border:1px solid #2a2f3e;background:#0f1115;
  color:#e6e8ee;font-size:15px;outline:none}
input:focus{border-color:#2dd4bf}
button{width:100%;margin-top:16px;padding:11px;border:0;border-radius:9px;background:#2dd4bf;
  color:#06231f;font-size:15px;font-weight:700;cursor:pointer}
button:hover{filter:brightness(1.05)}
.err{margin-top:14px;font-size:13px;color:#f87171;min-height:18px}
</style></head><body>
<form class="card" method="POST" action="/login">
  <p class="brand">Famou 研究台</p>
  <p class="sub">请输入访问口令${ENV_USER ? "" : " 与你的用户名"}</p>
  ${ENV_USER ? "" : `<label for="uname">用户名（用于展示）</label>
  <input id="uname" name="username" type="text" autocomplete="nickname" maxlength="64" placeholder="如：张三" />`}
  <label for="pw">访问口令</label>
  <input id="pw" name="password" type="password" autocomplete="current-password" />
  <button type="submit">进入</button>
  <div class="err">${err ? _html_escape(err) : ""}</div>
</form></body></html>`
}
function _html_escape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
}
// 处理 /login：GET 显示登录页；POST 校验口令 → 发 cookie → 跳首页。
async function serveLogin(req, res) {
  if (req.method === "GET") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" })
    res.end(authLoginPage())
    return
  }
  if (req.method === "POST") {
    let body = ""
    let tooBig = false
    req.on("data", (c) => { body += c; if (body.length > 8192) { tooBig = true; req.destroy() } })
    req.on("end", () => {
      if (tooBig) return
      let pw = ""
      let uname = ""
      const ct = req.headers["content-type"] || ""
      try {
        if (ct.includes("application/json")) {
          const j = JSON.parse(body)
          pw = String(j.password || "")
          uname = sanitizeUser(j.username)
        } else {
          const params = new URLSearchParams(body)
          pw = params.get("password") || ""
          uname = sanitizeUser(params.get("username"))
        }
      } catch { pw = ""; uname = "" }
      const ok = pw.length === AUTH_PASSWORD.length &&
        crypto.timingSafeEqual(Buffer.from(pw), Buffer.from(AUTH_PASSWORD))
      if (!ok) {
        res.writeHead(401, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" })
        res.end(authLoginPage("口令错误，请重试"))
        return
      }
      const secure = (req.headers["x-forwarded-proto"] || "").includes("https")
      // 用户名：环境变量锁定则忽略表单；否则用填的，没填则分配 8 位随机数。与登录态同寿命。
      const finalUser = ENV_USER || uname || randomUser()
      res.writeHead(302, {
        "set-cookie": [
          `${AUTH_COOKIE}=${authMakeCookie()}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${AUTH_TTL_SEC}${secure ? "; Secure" : ""}`,
          userCookie(finalUser, secure),
        ],
        "location": "/",
        "cache-control": "no-store",
      })
      res.end()
    })
    return
  }
  res.writeHead(405, { "content-type": "text/plain" }); res.end("method not allowed")
}
function serveLogout(req, res) {
  res.writeHead(302, { "set-cookie": `${AUTH_COOKIE}=; HttpOnly; Path=/; Max-Age=0`, "location": "/login" })
  res.end()
}
// 设置显示用户名（无口令模式首访、或已登录后改名）。写 famou_user cookie，与登录态同寿命。
// 环境变量锁定时拒绝改（由部署方钉死）。空 body → 分配 8 位随机数（即“跳过”）。
function serveSetUser(req, res) {
  if (ENV_USER) { // 已被环境变量钉死，不接受前端设置
    res.writeHead(409, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify({ ok: false, error: "locked", user: ENV_USER }))
    return
  }
  let body = ""
  let tooBig = false
  req.on("data", (c) => { body += c; if (body.length > 4096) { tooBig = true; req.destroy() } })
  req.on("end", () => {
    if (tooBig) { res.writeHead(413); res.end(); return }
    let uname = ""
    try {
      const ct = req.headers["content-type"] || ""
      if (ct.includes("application/json")) uname = sanitizeUser(JSON.parse(body).username)
      else uname = sanitizeUser(new URLSearchParams(body).get("username"))
    } catch { uname = "" }
    const finalUser = uname || randomUser() // 空=跳过 → 随机 8 位
    const secure = (req.headers["x-forwarded-proto"] || "").includes("https")
    res.writeHead(200, { "set-cookie": userCookie(finalUser, secure), "content-type": "application/json; charset=utf-8", "cache-control": "no-store" })
    res.end(JSON.stringify({ ok: true, user: finalUser }))
  })
}
// 门禁判定：AUTH 关时全放行；开时仅放行登录相关 + CDN 镜像（登录页要加载）。返回 true=已处理/放行前拦截。
function authGate(req, res) {
  if (!AUTH_ON) return false // 未设口令 → 不启用门禁
  const u = req.url || ""
  if (u === "/login" || u.startsWith("/login?")) { serveLogin(req, res); return true }
  if (u === "/logout" || u.startsWith("/logout?")) { serveLogout(req, res); return true }
  if (u.startsWith("/_esm") || u.startsWith("/_unpkg") || u === "/favicon.ico") return false // 公共资源放行
  if (authOk(req)) return false // 已登录 → 放行给后续路由
  // 未登录：API/XHR 返 401，其余跳登录页
  const accept = req.headers["accept"] || ""
  const isApi = u.startsWith("/oc") || u.startsWith("/raw") || u.startsWith("/archive") ||
    u.startsWith("/upload") || u.startsWith("/kb/") || u.startsWith("/compile") || u.startsWith("/paper") ||
    u.startsWith("/moonlog")
  if (isApi || accept.includes("application/json")) {
    res.writeHead(401, { "content-type": "application/json; charset=utf-8" })
    res.end(JSON.stringify({ error: "unauthenticated" }))
  } else {
    res.writeHead(302, { "location": "/login", "cache-control": "no-store" })
    res.end()
  }
  return true
}

http
  .createServer((req, res) => {
    if (authGate(req, res)) return // 门禁：未登录被拦/登录页已处理
    const u = req.url || ""
    if ((u === "/setuser" || u.startsWith("/setuser?")) && req.method === "POST") return serveSetUser(req, res)
    if (u.startsWith("/oc")) return proxy(req, res)
    if ((u.startsWith("/upload/migrate") ) && req.method === "POST") return serveUploadMigrate(req, res)
    if ((u.startsWith("/upload?") || u === "/upload") && req.method === "POST") return serveUpload(req, res)
    if ((u.startsWith("/kb/delete") ) && req.method === "POST") return serveKbDelete(req, res)
    if ((u.startsWith("/kb/mkdir") ) && req.method === "POST") return serveKbMkdir(req, res)
    if (u === "/moonlog/list" || u.startsWith("/moonlog/list?")) return serveMoonlogList(req, res)
    if (u.startsWith("/moonlog/")) return serveMoonlogGet(req, res, u.slice("/moonlog/".length).split("?")[0])
    if (u.startsWith("/compile?") || u === "/compile") return serveCompile(req, res)
    if (u.startsWith("/raw?") || u === "/raw") return serveRaw(req, res)
    if (u.startsWith("/archive?") || u === "/archive") return serveArchive(req, res)
    if (u.startsWith("/paper?") || u === "/paper") return servePaper(req, res)
    if (u.startsWith("/_esm")) return cdnProxy(req, res, "https://esm.sh", true, "/_esm")
    if (u.startsWith("/_unpkg")) return cdnProxy(req, res, "https://unpkg.com", false, "/_unpkg")
    return serveStatic(req, res)
  })
  .listen(PORT, HOST, () => {
    console.log(`[famou-web] http://localhost:${PORT}  (bind ${HOST}, /oc → ${OC_TARGET}, CDN 经本机镜像)`)
    console.log(`[famou-web] 访问鉴权：${AUTH_ON ? "已启用（FAMOU_ACCESS_PASSWORD）" : "未启用（设 FAMOU_ACCESS_PASSWORD 开启登录墙）"}`)
    // MoonLog 夜间编译调度器：进程内轮询 + 启动时补编（famou-scientist web 不是常驻 daemon，
    // 详见 moonlog.mjs 头部注释）。启动失败绝不该拖垮研究台主流程。
    try { startMoonlogScheduler({ ocTarget: OC_TARGET, projectRoot: PROJECT_ROOT }) }
    catch (e) { console.error("[famou-web] moonlog 调度器启动失败（忽略）：", e && e.message || e) }
  })
