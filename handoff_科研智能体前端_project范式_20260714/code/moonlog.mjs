// MoonLog：夜间知识编译日志。每天凌晨2点后，把「过去24h内活跃过的对话」+「当日新增产物/知识库
// 文件」编译成一份结构化摘要（LLM 输出 JSON），落盘 moonlog/<date>.json。
//
// 设计取舍（v1，简化 MVP）：
// - 不做跨天增量合并——每天都是独立快照。
// - 不做产物按 session 精确归因——session↔runDir 映射只存在浏览器 localStorage，服务端拿不到，
//   故产物变更只按目录扫描 mtime，不强行关联到具体 session。
// - 不保证「2点整必跑」——famou-scientist web 不是常驻 daemon；用进程内轮询 + 启动时补编替代
//   OS 级 crontab（本文件和 server.mjs 一样，只用 Node 内置模块，零 npm 依赖）。
import { readdir, stat, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, relative } from 'node:path';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TRANSCRIPT_CAP = 4000; // 单个 session 拼接文本上限（字符），防止把编译 prompt 撑爆
const FILE_SCAN_CAP = 200; // 产物/KB 变更文件收录上限（超出仅统计总数，不静默丢弃提示）
const SCAN_SUBDIRS = ['research-runs', 'knowledge-base'];
const CHECK_INTERVAL_MS = 5 * 60 * 1000; // 进程内轮询间隔

function fmtDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
function yesterdayStr(now) {
  return fmtDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
}
function moonlogDir(projectRoot) {
  return join(projectRoot, 'moonlog');
}
function moonlogFile(projectRoot, date) {
  return join(moonlogDir(projectRoot), date + '.json');
}

// 列出所有已编译日期（按日期倒序）。目录不存在则返回空数组。
export async function listMoonlogDates(projectRoot) {
  let entries;
  try {
    entries = await readdir(moonlogDir(projectRoot));
  } catch {
    return [];
  }
  return entries
    .filter((f) => f.endsWith('.json') && DATE_RE.test(f.slice(0, -5)))
    .map((f) => f.slice(0, -5))
    .sort()
    .reverse();
}

// 读取指定日期的编译结果；日期格式非法或文件不存在都返回 null（供路由统一按 404 处理）。
export async function readMoonlog(projectRoot, date) {
  if (!DATE_RE.test(date)) return null;
  try {
    const raw = await readFile(moonlogFile(projectRoot, date), 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

// 递归扫描 subdirs 下 mtime 落在 [start,end) 的文件；总命中数可能超过 cap，只截断收录列表，
// totalMatched 保留真实总数供上层提示「还有 N 个未列出」（不静默截断）。
async function scanChangedFiles(projectRoot, subdirs, start, end, cap = FILE_SCAN_CAP) {
  const collected = [];
  let totalMatched = 0;
  async function walk(dir) {
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      if (ent.name.startsWith('.')) continue;
      const full = join(dir, ent.name);
      if (ent.isDirectory()) {
        await walk(full);
      } else if (ent.isFile()) {
        let st;
        try {
          st = await stat(full);
        } catch {
          continue;
        }
        if (st.mtimeMs >= start && st.mtimeMs < end) {
          totalMatched++;
          if (collected.length < cap) collected.push(relative(projectRoot, full));
        }
      }
    }
  }
  for (const sub of subdirs) {
    await walk(join(projectRoot, sub));
  }
  return { files: collected, totalMatched };
}

// 按前两级目录分组（如 research-runs/<主题>、knowledge-base/<分组>），供 prompt 里按目录展示。
function groupFilesByDir(files) {
  const order = [];
  const map = new Map();
  for (const f of files) {
    const parts = f.split('/');
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : parts[0];
    if (!map.has(dir)) {
      map.set(dir, []);
      order.push(dir);
    }
    map.get(dir).push(parts[parts.length - 1]);
  }
  return order.map((dir) => ({ dir, files: map.get(dir) }));
}

// 抽取消息里的纯文本 parts 并拼成 "[role] 文本" 的行；跟前端 userText() 同款抽取逻辑。
function messageText(m) {
  const role = (m && m.info && m.info.role) || '?';
  const text = ((m && m.parts) || []).filter((p) => p.type === 'text').map((p) => p.text || '').join('').trim();
  return text ? `[${role}] ${text}` : '';
}
function truncateTranscript(text, cap = TRANSCRIPT_CAP) {
  if (text.length <= cap) return text;
  const headLen = Math.floor(cap * 0.6);
  const tailLen = cap - headLen;
  const omitted = text.length - cap;
  return text.slice(0, headLen) + `\n...(省略${omitted}字符)...\n` + text.slice(-tailLen);
}

async function fetchSessionTranscript(ocTarget, session) {
  let msgs = [];
  try {
    const r = await fetch(ocTarget + '/session/' + session.id + '/message');
    if (r.ok) msgs = await r.json();
  } catch { /* 单个 session 拉取失败不影响整体编译，跳过即可 */ }
  const lines = (msgs || []).map(messageText).filter(Boolean);
  return { id: session.id, title: session.title, transcript: truncateTranscript(lines.join('\n\n')) };
}

// 从 opencode 回复里抽出纯文本；防御性处理几种可能的返回形状（单条消息 / 消息数组 / 裸 text）。
function extractReplyText(resp) {
  if (!resp) return '';
  if (Array.isArray(resp)) return extractReplyText(resp[resp.length - 1]);
  if (Array.isArray(resp.parts)) return resp.parts.filter((p) => p.type === 'text').map((p) => p.text || '').join('');
  if (typeof resp.text === 'string') return resp.text;
  return '';
}
function tryParseJson(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch { /* 继续尝试从文本里摘出 JSON 块 */ }
  const m = text.match(/\{[\s\S]*\}/);
  if (m) {
    try {
      return JSON.parse(m[0]);
    } catch { /* 仍失败，交给上层重试/报错 */ }
  }
  return null;
}

async function sendCompilePrompt(ocTarget, sessionID, text) {
  const res = await fetch(ocTarget + '/session/' + sessionID + '/message', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ parts: [{ type: 'text', text }] }),
  });
  if (!res.ok) throw new Error('compile prompt failed: ' + res.status + ' ' + (await res.text().catch(() => '')));
  return extractReplyText(await res.json());
}

function buildPrompt(date, sessionMaterials, fileGroups, totalFilesMatched) {
  const sessBlock = sessionMaterials.length
    ? sessionMaterials.map((s) => `### Session ${s.id} 《${s.title}》\n${s.transcript || '(无文本消息)'}`).join('\n\n')
    : '(当日无活跃对话)';
  const fileBlock = fileGroups.length
    ? fileGroups.map((g) => `- ${g.dir}/：${g.files.join('、')}`).join('\n') +
      (totalFilesMatched > fileGroups.reduce((n, g) => n + g.files.length, 0)
        ? `\n（仅列出部分，当日实际变更文件共 ${totalFilesMatched} 个）`
        : '')
    : '(当日无新增/变更文件)';
  return `你是 MoonLog 知识编译助手，把用户 ${date} 这一天的科研活动编译成一份结构化的知识日志摘要。

【当日活跃对话】
${sessBlock}

【当日新增/变更的产物与知识库文件】
${fileBlock}

请只输出一个 JSON 对象（不要 markdown 代码块、不要任何解释文字），格式：
{
  "date": "${date}",
  "summary": "整体概述，3-5句，讲清楚今天大致在研究什么、进展如何",
  "sessions": [{"id": "会话ID", "title": "会话标题", "highlights": "这个对话做了什么/结论/待解决问题，3-6句"}],
  "artifacts": [{"dir": "目录路径", "files": ["文件名", "..."], "note": "一句话说明这批文件是什么"}],
  "open_questions": ["还没解决/值得跟进的点，可为空数组"]
}`;
}

// 编译指定日期。会创建一个内部专用 session（title 前缀 "[MoonLog] "，metadata.kind="moonlog"）
// 用来发起 LLM 调用——前端按 metadata.kind 过滤，这个 session 不会出现在正常侧栏会话列表里。
export async function compileMoonlog({ ocTarget, projectRoot, date }) {
  if (!DATE_RE.test(date)) throw new Error('invalid date: ' + date);
  const start = new Date(date + 'T00:00:00').getTime();
  const end = start + 24 * 60 * 60 * 1000;

  let sessions = [];
  try {
    const r = await fetch(ocTarget + '/session?roots=true&limit=200');
    if (r.ok) sessions = await r.json();
  } catch (e) {
    throw new Error('拉取 session 列表失败：' + e.message);
  }
  const active = (sessions || []).filter((s) => {
    const t = s && s.time && s.time.updated;
    if (t == null || t < start || t >= end) return false;
    if (s.metadata && s.metadata.kind === 'moonlog') return false;
    if (String(s.title || '').startsWith('New session')) return false;
    return true;
  });

  const { files, totalMatched } = await scanChangedFiles(projectRoot, SCAN_SUBDIRS, start, end);
  const fileGroups = groupFilesByDir(files);

  if (active.length === 0 && totalMatched === 0) {
    return writeMoonlogResult(projectRoot, date, { date, skipped: true, reason: 'no activity' });
  }

  const sessionMaterials = await Promise.all(active.map((s) => fetchSessionTranscript(ocTarget, s)));
  const prompt = buildPrompt(date, sessionMaterials, fileGroups, totalMatched);

  const createRes = await fetch(ocTarget + '/session', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title: '[MoonLog] ' + date, metadata: { kind: 'moonlog' } }),
  });
  if (!createRes.ok) throw new Error('创建编译 session 失败：' + createRes.status);
  const created = await createRes.json();
  const compileSessionID = created.id;

  let raw = '';
  let parsed = null;
  try {
    raw = await sendCompilePrompt(ocTarget, compileSessionID, prompt);
    parsed = tryParseJson(raw);
    if (!parsed) {
      raw = await sendCompilePrompt(
        ocTarget,
        compileSessionID,
        prompt + '\n\n（上一次输出解析 JSON 失败，这次请【只输出一个 JSON 对象】，不要任何 markdown 代码块标记、不要任何前后说明文字。）',
      );
      parsed = tryParseJson(raw);
    }
  } catch (e) {
    return writeMoonlogResult(projectRoot, date, { date, error: true, raw: ('请求失败：' + e.message).slice(0, 2000) });
  }
  if (!parsed) {
    return writeMoonlogResult(projectRoot, date, { date, error: true, raw: String(raw || '').slice(0, 2000) });
  }
  parsed.date = parsed.date || date;
  return writeMoonlogResult(projectRoot, date, parsed);
}

async function writeMoonlogResult(projectRoot, date, result) {
  await mkdir(moonlogDir(projectRoot), { recursive: true });
  await writeFile(moonlogFile(projectRoot, date), JSON.stringify(result, null, 2), 'utf8');
  return result;
}

// 进程内调度器：不依赖 OS crontab（famou-scientist web 不是常驻 daemon）。
// 启动即检查一次（若已过 2 点且昨天没编译过就立即补编），之后每 5 分钟再检查一次。
// 幂等：靠「moonlog/<date>.json 是否已存在」判断要不要编译，文件存在就不会重复触发；
// compiling 内存锁防止同一时刻并发触发两次。
export function startMoonlogScheduler({ ocTarget, projectRoot }) {
  let compiling = false;
  async function maybeCompile() {
    if (compiling) return;
    const now = new Date();
    if (now.getHours() < 2) return;
    const date = yesterdayStr(now);
    try {
      await stat(moonlogFile(projectRoot, date));
      return;
    } catch { /* 不存在，继续编译 */ }
    compiling = true;
    console.log(`[moonlog] 开始编译 ${date} 的知识日志…`);
    try {
      const result = await compileMoonlog({ ocTarget, projectRoot, date });
      console.log(`[moonlog] ${date} 编译完成` + (result && result.skipped ? '（当日无活动，已跳过）' : ''));
    } catch (e) {
      console.error(`[moonlog] ${date} 编译失败：`, e && e.message || e);
    } finally {
      compiling = false;
    }
  }
  setTimeout(maybeCompile, 3000); // 稍等 opencode 就绪
  setInterval(maybeCompile, CHECK_INTERVAL_MS);
}
