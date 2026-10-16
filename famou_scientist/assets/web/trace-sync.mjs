#!/usr/bin/env node
/**
 * trace-sync.mjs — famou-scientist 轨迹转存器（零侵入·独立进程）。
 *
 * 目的：单机（非多租户）模式下把本容器的 opencode 轨迹（对话/工具/事件全在 opencode.db）
 * 定期快照到 CFS 的**每容器独立**路径，用于事后收集分析、迭代改进。不碰 opencode、不碰
 * server.mjs、不改任何跑在别人容器里的 plugin —— 纯旁路，最稳。
 *
 * 机制：
 *   ① opencode.db 是 WAL 模式的活动库，不能直接 cp（会拿到不一致/半写快照）。用
 *      `sqlite3 <db> ".backup <tmp>"` 做**在线一致快照**（把 WAL 合并进快照），再原子 rename
 *      到 CFS 目标，读者永远看到完整文件。
 *   ② 目标 = <DEST>/<hostname>/opencode.db —— 每容器一条独立路径（$HOSTNAME 天然区分），
 *      互不覆盖。附一份 meta.json（hostname / 时间 / 大小 / DB 行数概览）便于盘点。
 *   ③ 两种运行姿态：--once（退出兜底，同步一次即返回）；默认常驻，每 INTERVAL 同步一次，
 *      并在收到 SIGTERM/SIGINT 时再兜底同步一次后退出。
 *
 * 隐私：轨迹含用户 prompt 原文。目标目录写入 NOTICE.txt 说明收集范围/用途，便于告知与合规。
 *
 * 用法：
 *   node trace-sync.mjs --once           # 同步一次（可挂到退出钩子/cron）
 *   node trace-sync.mjs                   # 常驻，每 FAMOU_TRACE_INTERVAL_MS 同步一次
 * 环境变量：
 *   FAMOU_TRACE_DEST       目标根（默认 /path/to/workspace/famou-scientist-user-db/famou-traces）
 *   FAMOU_TRACE_DB         源 DB（默认 ~/.local/share/opencode/opencode.db）
 *   FAMOU_TRACE_INTERVAL_MS  常驻同步间隔（默认 600000 = 10min）
 *   FAMOU_TRACE_ID         覆盖标识（默认从安装路径 workspace/<user> 抽 <user>，见 resolveNodeId）
 *   FAMOU_TRACE_SQLITE     sqlite3 可执行路径（默认 "sqlite3"，走 PATH）
 *   FAMOU_TRACE_OFF        truthy → 整体禁用（什么都不做，便于一键关停）
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import crypto from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const execFileP = promisify(execFile);

const OFF = /^(1|true|yes|on)$/i.test(process.env.FAMOU_TRACE_OFF || '');
const DEST_ROOT =
  process.env.FAMOU_TRACE_DEST ||
  '/path/to/workspace/famou-scientist-user-db/famou-traces';
const HOME = os.homedir();
const SRC_DB =
  process.env.FAMOU_TRACE_DB || path.join(HOME, '.local/share/opencode/opencode.db');
const INTERVAL_MS = Number(process.env.FAMOU_TRACE_INTERVAL_MS) || 600_000;
const SQLITE = process.env.FAMOU_TRACE_SQLITE || 'sqlite3';

/**
 * 每容器唯一子目录标识（node_id）——**收集不串**的关键。
 *
 * 大家共用同一台物理机、各跑各的容器。注意：`os.hostname()` 返回的是**物理宿主机名**
 * （如 qianfan-a800-0210-10），所有容器**共享同一个**，不能用来区分；容器名（如 gezengle-fm）
 * 由外层编排平台掌管，**没注入容器内部**，脚本拿不到。真正每人不同、且人类可读的信号是
 * **安装路径**：famou-scientist 装在 `/path/to/workspace/<user>/…`，`<user>` 段各人各异
 * （gezengle / lihaoran13 …）。故优先级：
 *
 *   ① FAMOU_TRACE_ID 已设 → 纯用它（部署方注入真容器名/用户名，最精确，全权保证唯一）。
 *   ② 否则从**本脚本自身路径**（import.meta.url，必在 …/workspace/<user>/…/assets/web/）抽
 *      `workspace/<user>` 的 <user> 段作标识——零配置、人类可读、每人不同。
 *   ③ 连 <user> 都抽不到（路径布局异常）→ 退回 `<hostname>-<每库持久随机码>`：随机码是每份
 *      数据目录首次生成、持久化到 `<dataDir>/.famou-trace-id` 的 8 位码，至少保证不同库不覆盖。
 */
function extractWorkspaceUser() {
  // 本脚本一定位于 …/workspace/<user>/…/assets/web/trace-sync.mjs
  const selfPath = fileURLToPath(import.meta.url);
  const m = selfPath.match(/\/workspace\/([^/]+)\//);
  return m ? m[1] : '';
}

function persistentInstallId() {
  const idPath = path.join(path.dirname(SRC_DB), '.famou-trace-id');
  let id = '';
  try {
    id = fs.readFileSync(idPath, 'utf8').trim();
  } catch {
    /* 尚未生成 */
  }
  if (!/^[0-9a-f]{8}$/.test(id)) {
    id = crypto.randomBytes(4).toString('hex');
    try {
      fs.mkdirSync(path.dirname(idPath), { recursive: true });
      fs.writeFileSync(idPath, id, { flag: 'wx' }); // 原子创建：已存在则抛，转而读回
    } catch {
      try {
        const existing = fs.readFileSync(idPath, 'utf8').trim();
        if (/^[0-9a-f]{8}$/.test(existing)) { id = existing; }
      } catch {
        /* 落盘失败：退化为本次进程内随机码，仍能区分不同库，只是不跨重启稳定 */
      }
    }
  }
  return id;
}

function resolveNodeId() {
  const explicit = (process.env.FAMOU_TRACE_ID || '').trim();
  if (explicit) { return explicit.replace(/[^A-Za-z0-9._-]/g, '_'); }
  const user = extractWorkspaceUser();
  if (user) { return user.replace(/[^A-Za-z0-9._-]/g, '_'); }
  const host = (os.hostname() || 'unknown').replace(/[^A-Za-z0-9._-]/g, '_');
  return `${host}-${persistentInstallId()}`;
}

const NODE_ID = resolveNodeId();
const DEST_DIR = path.join(DEST_ROOT, NODE_ID);
const FP_PATH = path.join(DEST_DIR, '.fingerprint');

function log(m) {
  console.log(`[trace-sync] ${new Date().toISOString()} ${m}`);
}

/**
 * 变化指纹：DB 主文件 + -wal + -shm 的 (mtimeMs,size) 拼串。opencode 写入走 WAL，故必须把
 * -wal 纳入，否则空闲判据永远为"变了"或永远为"没变"。用于跳过"无变化"的全量快照，防止空闲
 * 容器把 CFS 反复写满。
 */
async function fingerprint() {
  const parts = [];
  for (const suffix of ['', '-wal', '-shm']) {
    try {
      const st = await fsp.stat(SRC_DB + suffix);
      parts.push(`${suffix}:${st.mtimeMs}:${st.size}`);
    } catch {
      parts.push(`${suffix}:-`);
    }
  }
  return parts.join('|');
}

/** sqlite3 在线一致快照到 tmp，再原子 rename 到 dest。返回快照字节数。 */
async function snapshotDb() {
  if (!fs.existsSync(SRC_DB)) {
    log(`源 DB 不存在，跳过：${SRC_DB}`);
    return null;
  }
  await fsp.mkdir(DEST_DIR, { recursive: true });
  const finalPath = path.join(DEST_DIR, 'opencode.db');
  // tmp 与 final 同目录（同一文件系统）→ rename 才是原子的。
  const tmpPath = path.join(DEST_DIR, `.opencode.db.tmp-${process.pid}`);
  try {
    await fsp.rm(tmpPath, { force: true });
    // .backup 做 WAL 合并的一致快照；直接落到 CFS 上的 tmp。
    await execFileP(SQLITE, [SRC_DB, `.backup '${tmpPath}'`], {
      maxBuffer: 1 << 20,
      timeout: 10 * 60_000,
    });
    const st = await fsp.stat(tmpPath);
    await fsp.rename(tmpPath, finalPath);
    return st.size;
  } finally {
    await fsp.rm(tmpPath, { force: true }).catch(() => {});
  }
}

/** 从源库读几个概览计数，写进 meta（best-effort，失败不阻断）。 */
async function dbOverview() {
  const q =
    'SELECT (SELECT count(*) FROM session), (SELECT count(*) FROM message), (SELECT count(*) FROM part);';
  try {
    const { stdout } = await execFileP(SQLITE, [SRC_DB, '-noheader', q], {
      timeout: 30_000,
    });
    const [sessions, messages, parts] = stdout.trim().split('|').map((n) => Number(n) || 0);
    return { sessions, messages, parts };
  } catch {
    return null;
  }
}

async function writeMeta(dbBytes, overview) {
  const meta = {
    node_id: NODE_ID,
    hostname: os.hostname(),
    synced_at: new Date().toISOString(),
    synced_at_epoch: Math.floor(Date.now() / 1000),
    src_db: SRC_DB,
    db_bytes: dbBytes,
    overview,
  };
  await fsp
    .writeFile(path.join(DEST_DIR, 'meta.json'), JSON.stringify(meta, null, 2))
    .catch((e) => log(`写 meta 失败（忽略）：${e.message}`));
}

const NOTICE = `此目录收集 famou-scientist（单机模式）本容器的 opencode 研究轨迹，用于产品改进与问题诊断。
收集内容：opencode.db 的一致快照（含会话/消息/工具调用/事件；可能含用户输入的 prompt 原文）。
每容器一条独立子目录（以 hostname 区分）。如需停止收集，设环境变量 FAMOU_TRACE_OFF=1。
`;

async function writeNotice() {
  await fsp
    .writeFile(path.join(DEST_DIR, 'NOTICE.txt'), NOTICE)
    .catch(() => {});
}

let syncing = false;
async function syncOnce(reason, { force = false } = {}) {
  if (syncing) {
    log(`上一次同步未完成，跳过（${reason}）`);
    return;
  }
  syncing = true;
  const t0 = Date.now();
  try {
    if (!fs.existsSync(SRC_DB)) {
      log(`源 DB 不存在，跳过：${SRC_DB}`);
      return;
    }
    const fp = await fingerprint();
    // 无变化守卫：DB/WAL 指纹与上次一致 → 跳过全量快照（除非 force，如退出兜底）。
    if (!force) {
      const prev = await fsp.readFile(FP_PATH, 'utf8').catch(() => null);
      if (prev === fp) {
        log(`无变化，跳过（${reason}）`);
        return;
      }
    }
    const bytes = await snapshotDb();
    if (bytes == null) { return; }
    const overview = await dbOverview();
    await writeMeta(bytes, overview);
    await writeNotice();
    await fsp.writeFile(FP_PATH, fp).catch(() => {});
    const mb = (bytes / 1048576).toFixed(1);
    const ov = overview
      ? ` sessions=${overview.sessions} msgs=${overview.messages} parts=${overview.parts}`
      : '';
    log(`同步完成（${reason}）：${DEST_DIR}/opencode.db ${mb}MB${ov} 用时${Date.now() - t0}ms`);
  } catch (e) {
    log(`同步失败（${reason}）：${e.message}`);
  } finally {
    syncing = false;
  }
}

/**
 * 收集目标可用探测——本机（无 CFS）用户的**静默兜底**关键。
 *
 * 判据：DEST_ROOT 的**父目录必须已经存在且可写**（不自己创建它）。即 CFS 上那个专门的收集区
 *   /path/to/workspace/<user>/famou-scientist-user-db/  应由部署方/管理员预先建好；
 * trace-sync 只在其下建 famou-traces/<user>/ 子目录。这样：
 *   - CFS 已挂载且收集区就绪 → 父目录存在 → 收集；
 *   - 本机无 CFS → /path/to/workspace/... 整条路径都不存在 → 父目录 ENOENT → 判「无收集目标」，
 *     静默退出，绝不在本机盘上凭空造出 /path/to/workspace 目录树。
 * 不做「上溯到 /」——否则 root 对 / 恒可写，会误判所有路径可用。
 */
async function destWritable() {
  const parent = path.dirname(path.resolve(DEST_ROOT));
  const attempt = (async () => {
    try {
      const st = await fsp.stat(parent);
      if (!st.isDirectory()) { return false; }
      await fsp.access(parent, fs.constants.W_OK);
      return true;
    } catch {
      return false; // ENOENT（无 CFS）/ EACCES（无权限）→ 不收集
    }
  })();
  // 探测加超时：绝不让一个病态/挂起的路径（如某些特殊 fs）无限期拖住启动。
  const timeout = new Promise((resolve) => setTimeout(() => resolve(false), 8000));
  try {
    return await Promise.race([attempt, timeout]);
  } catch {
    return false;
  }
}

async function main() {
  if (OFF) {
    log('FAMOU_TRACE_OFF 已设置 → 禁用，退出');
    return;
  }
  // 无 CFS/收集目标不可用 → 静默兜底：不收集、不报错、不常驻。
  // 显式 exit(0)：即便探测超时留下一个吊着事件循环的挂起 promise，也保证进程干净退出。
  if (!(await destWritable())) {
    log(`收集目标不可用（${DEST_ROOT}）——本机模式，轨迹不收集，退出。`);
    process.exit(0);
  }
  const once = process.argv.includes('--once');
  log(`启动：node_id=${NODE_ID} src=${SRC_DB} dest=${DEST_DIR} ${once ? '(once)' : `每${INTERVAL_MS}ms`}`);

  await syncOnce(once ? 'once' : 'startup');
  if (once) { return; }

  const timer = setInterval(() => syncOnce('interval'), INTERVAL_MS);
  // 注意：不要 unref —— 这个定时器就是常驻进程的存活锚。unref 会让进程在 startup 同步后
  // 立刻退出（信号 handler 不保持事件循环存活），常驻模式失效。

  // 收到终止信号：兜底同步一次再退出。
  let closing = false;
  const handleSignal = async (sig) => {
    if (closing) { return; }
    closing = true;
    log(`收到 ${sig}，兜底同步后退出`);
    clearInterval(timer);
    await syncOnce(`exit:${sig}`, { force: true });
    process.exit(0);
  };
  for (const sig of ['SIGTERM', 'SIGINT']) {
    process.on(sig, () => handleSignal(sig));
  }
}

main().catch((e) => {
  log(`致命错误：${e?.stack || e}`);
  process.exit(1);
});
