# Famou 多租户 — 用户鉴权体系设计

> 状态：阶段 A（逻辑库）+ B（aiohttp 网关）+ C（每用户实例 + 管理台用量）**已实现**，单测 75 项全绿｜2026-07-02｜隶属 `docs/multitenant/MULTI_TENANT_DESIGN.md` 的**身份+实例层**
> 本版已定：**纯自建账号**（用户名+密码，scrypt 零依赖）｜**邀请码注册**（一次性+可过期+可吊销+消费审计）｜**账号可设使用期限**｜**每用户独立实例+数据隔离**（进程模型）｜**管理台看用户 agent 轨迹/token 花费**｜数据存 CFS SQLite（鉴权库）+ 本地盘（每用户 opencode.db）｜阶段 C+（容器/GPU/跨机）交下游编排层

---

## 0. 定位与边界（为什么能独立于集群先做）

鉴权体系只负责一件事：**确认「你是谁」→ 产出一个可信的 `user_id` + 一个会话（session）**。
它**不关心**这个身份之后被拿去做什么——起容器、起进程、还是交给 fm 平台调度，那是**下游编排层**的事。

```
   浏览器 ──(注册/登录)──►┌───────────────────────┐
                          │  鉴权网关（本文档）      │  aiohttp: gateway.py
                          │  注册 / 登录 / 会话      │  authenticate 中间件 = 门禁
                          │  输出：authenticate()   │──► user_id（可信身份）
                          └───────────┬───────────┘        │
                          鉴权通过后流式反代(注入 X-Famou-User)  ▼
                                      ▼             下游编排层（阶段C，工程同学评估）
                          [前端 server.mjs :4096]    「拿 user_id 去起/找该用户的 famou 实例」
                                      │                      （阶段 B 先只反代到单个固定上游）
                          ──/oc 反代──►[opencode serve :4097]
```

**契约**：鉴权层对下游只暴露一个函数 `authenticate(request) -> user_id | None`。
下游（网关的路由/spawn 逻辑）只依赖这个返回值，**完全不关心账号是自建还是 SSO**。
→ 这就是它能**先落地、且未来换 SSO 只改一个函数**的原因；集群方案怎么定，都不影响这层。

**本层负责** ✅：注册、登录、登出、改密、会话签发/校验/过期、邀请码、管理员账号管理、防爆破限流。
**本层不负责** ❌：起容器/进程、GPU 分配、反向代理、实例生命周期、模型 key（那些在编排层/运行时注入）。

---

## 1. 数据模型（SQLite on CFS）

单库文件：`<AUTH_DB>`（默认 `/path/to/workspace/famou-scientist-user-db/identity.db`），WAL 模式。

```sql
-- 用户
CREATE TABLE users (
  user_id     TEXT PRIMARY KEY,   -- 内部不可变 ID（uuid4 或 u_<随机>）；下游用它作隔离键/目录名，限 [A-Za-z0-9_-]
  username    TEXT UNIQUE NOT NULL,-- 登录名（大小写不敏感，存小写）
  pass_hash   TEXT NOT NULL,       -- scrypt 哈希（标准库、含盐、绝不存明文；格式串带算法标识，可平滑升级 argon2）
  role        TEXT NOT NULL DEFAULT 'user',   -- 'user' | 'admin'
  status      TEXT NOT NULL DEFAULT 'active', -- 'active' | 'disabled'
  created_at  INTEGER NOT NULL,
  last_login  INTEGER,
  expires_at  INTEGER              -- 可选：账号使用期限（null=永久）；到期后 authenticate/login 自动拒绝，用于"只给用一段时间"
);
-- 会话（登录态）
CREATE TABLE sessions (
  sid         TEXT PRIMARY KEY,    -- secrets.token_urlsafe(32)，高熵
  user_id     TEXT NOT NULL REFERENCES users(user_id),
  created_at  INTEGER NOT NULL,
  last_seen   INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL
);
-- 邀请码（一次性；用完即失效，不可复用）
CREATE TABLE invites (
  token       TEXT PRIMARY KEY,    -- 高熵随机；一次性
  created_by  TEXT NOT NULL,       -- 管理员 user_id
  note        TEXT,                -- 备注（发给谁）
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER,             -- 可选：到期未用自动失效（null=永不过期）；避免发出去的码一直可用
  status      TEXT NOT NULL DEFAULT 'unused', -- 'unused' | 'used' | 'revoked'
  used_by     TEXT,                -- 用后写入注册者 user_id
  used_at     INTEGER
);
-- 登录失败计数（防爆破，可选独立表或内存）
CREATE TABLE login_attempts (
  username    TEXT, ip TEXT, at INTEGER
);
```

### 存储决策：为什么 SQLite on CFS 在这层可行（与 opencode.db 区别对待）
- 鉴权数据**极低频写**（注册/登录偶发）、**量小**（用户数百级）、**必须持久+换机不丢**（CFS 天然满足）。
- SQLite 放 CFS 的风险来自**多进程抢 FUSE 文件锁**；而鉴权库**只有网关单进程写** → 进程内串行，锁竞争基本不触发。
- **一条纪律**：全局保证**单网关实例写**（启动时抢 `<AUTH_DB>.lock` pidfile，防换机时新旧网关双写）。
- 对比：`opencode.db` 是**每用户实例高频写** → 必须放本地盘+备份 CFS（见主文档 §6.2）。**两者分开对待。**

---

## 2. 注册（邀请码模式）

```
POST /signup   body: { invite, username, password }
```
1. 校验 `invite`：`status='unused'` **且**（无过期或 `now < expires_at`）——否则拒绝。
2. 校验 `username` 唯一（小写归一）、口令强度（长度≥8）。
3. `pass_hash = scrypt(password)`；生成 `user_id`；写 `users`（role=user, status=active）。
4. **在同一事务里**把邀请码置为已用：`status='used', used_by=user_id, used_at=now` —— 之后任何再拿它注册的请求都因 `status!='unused'` 被拒。**一次性、用完即失效、不可复用。**
5. 建 session（§4）→ 下发 cookie → 302 到研究台。
> 失败（码无效/已用/已吊销/已过期/用户名占用/弱口令）返回明确错误。
> **并发防重放**：第 4 步用 `UPDATE invites SET status='used',... WHERE token=? AND status='unused'` 的**条件更新**，只有影响行数=1 才继续建号——即便两个请求同时拿同一码，也只有一个能成功（数据库层面保证一次性，不靠先查后写）。

管理员管理邀请码：
- 生成：`POST /admin/invites { note, expires_in? }` → 返回一次性 token（管理员线下发给受邀人；可设过期，如 7 天）。
- **吊销**：`POST /admin/invites/{token}/revoke` → `status='revoked'`（把**未用**的码作废，防止发错/泄漏后被人注册）。

---

## 3. 登录 / 登出 / 改密

```
POST /login    { username, password }   → 校验 status=active + 未到期 + scrypt.verify → 建 session → cookie
POST /logout                            → 删当前 session
POST /account/password { old, new }     → 验 old → 更新 pass_hash → （可选）吊销其余 session
```
- 登录失败：`login_attempts` 记录；同 username/IP 在窗口内超阈值 → 临时锁定 + 延迟响应（防爆破）。
- 口令永远只比对哈希；错误提示统一为"用户名或密码错误"（不区分是哪个）。

---

## 4. 会话机制（Cookie）

- 登录/注册成功 → 建 `sessions` 行（`sid=token_urlsafe(32)`，`expires_at=now+TTL`，TTL 可配默认 7d）。
- 下发 cookie：`Set-Cookie: famou_sid=<sid>; HttpOnly; SameSite=Lax; Path=/; Secure`（Secure 在上 TLS 后必开）。
- 每次请求：`authenticate()` 读 cookie → 查 `sessions` → 未过期则刷新 `last_seen`（滑动过期可选）→ 返回 `user_id`。
- 登出/改密/禁用 → 删对应 session 行（即时失效）。
- 过期清理：惰性（命中过期即删）+ 定期扫。

---

## 5. 可插拔认证接口（未来换 SSO 的唯一改动点）

```python
# identity.py —— 下游只依赖这一个函数
def authenticate(request) -> str | None:
    """从请求解析出可信 user_id；未登录/无效返回 None。
    自建版：读 famou_sid cookie → sessions 表 → user_id。
    换 SSO 版：改为校验 IdP 下发的 token/OIDC，映射到本地 user_id。上层不动。
    """
```
- **自建（本版）**：cookie → sessions。
- **未来 SSO/OAuth**：只替换此函数体（校验 IdP token、首登自动建 user 行）。注册/登录页可停用，其余（会话消费、下游契约）完全不变。
- **并存**：可同时支持（本地账号 + SSO），`authenticate` 内先试 SSO 再试本地。

---

## 6. 与下游编排层的契约（解耦点）

鉴权层对编排层暴露的**全部**接口：

| 提供 | 形式 | 下游怎么用 |
|---|---|---|
| `authenticate(request) -> user_id\|None` | 函数/中间件 | 每个受保护请求先过它；None → 302 /login（XHR → 401） |
| `user_id`（稳定、字符集受限） | 字符串 | 作隔离键：`users/<user_id>/…` 目录、容器名 `famou-tenant-<user_id>`、路由表 key |
| `get_user(user_id)`（role/status） | 查询 | 编排层判权限（admin）、拒绝 disabled 用户 |

> 下游**看不到也不需要**口令/邀请/session 细节。它只问"这个请求是谁(user_id)、能不能用(status)"。
> **这意味着：鉴权层现在就能实现并单测（mock 请求→断言 user_id），完全不依赖容器/集群是否就绪。**

---

## 7. HTTP 接口清单（网关挂载）

| 方法 路径 | 鉴权 | 说明 |
|---|---|---|
| `GET /signup` `/login` | 公开 | 简单 HTML 表单页 |
| `POST /signup` | 公开(需邀请码) | 注册 |
| `POST /login` `/logout` | 公开 / 已登录 | 登录/登出 |
| `GET /account` | 已登录 | 改密页 + 看自己信息 |
| `POST /account/password` | 已登录 | 改密 |
| `GET /admin` | admin | **租户管理页**（内联 HTML+JS，可视化列用户/邀请码、发码、禁用启用、设期限、吊销、重置口令；非 admin 返回 403 HTML） |
| `GET /admin/users` | admin | 列用户（状态/创建/最近登录） |
| `POST /admin/users/{id}/disable\|enable` | admin | 禁用/启用（禁用即吊销其 session；下游据此停实例） |
| `POST /admin/users/{id}/expiry` | admin | 设/清账号使用期限 `{ expires_at\|null }`（"只给用一段时间"；到期即掉线，下游据此停实例） |
| `POST /admin/users/{id}/reset-password` | admin | 重置某用户口令（无邮件找回场景的兜底；返回新临时口令） |
| `POST /admin/invites` | admin | 生成邀请码（可设过期） |
| `POST /admin/invites/{token}/revoke` | admin | 吊销未使用的邀请码 |
| `GET /admin/invites` | admin | 列邀请码（含 `used_by`/`used_at`：谁在何时用了哪个码，供审计） |
| `GET /healthz` | 公开 | 健康检查 |
| 其余 `/*` | 已登录 | 交给下游反代（未登录 → /login） |

---

## 8. 安全要点（红线）

- 口令：**scrypt**（标准库、带盐、内存硬 KDF、抗爆破）；绝不存/日志明文；格式串带算法标识，可平滑升级 argon2。
- session：高熵 token；cookie `HttpOnly+SameSite=Lax+Secure`；可配 TTL + 滑动过期 + 主动吊销。
- 邀请码：一次性、高熵、可标注/回收。
- 防爆破：登录失败限流 + 账号临时锁定 + 统一错误文案。
- `user_id` 字符集限制（下游用作目录名/容器名，挡路径穿越、命令注入）。
- 单写者纪律：网关实例锁，防 CFS 上 sqlite 双写。
- **本层不碰模型 key**（key 在编排层运行时注入容器 env，与鉴权解耦）。

---

## 9. 文件/目录布局

```
/path/to/workspace/famou-scientist-user-db/   # 鉴权层持久数据（CFS，换机不丢）
├── identity.db                    # sqlite（users/sessions/invites），WAL
├── identity.db.lock               # 单网关写者 pidfile
└── (可选) auth-audit.log          # 注册/登录/禁用审计（不含口令/token 明文）
```
> 未来接 SSO 时此库仍在（存本地 user 映射/审计），只是注册/登录入口改走 IdP。

---

## 10. 落地阶段与验证（本层可独立完成）

**阶段 A · 纯逻辑库**（不依赖网关/容器）
- `identity.py`：建库、`create_invite/redeem_signup/login/logout/change_password/create_session/resolve_session/authenticate/get_user/disable_user`；账号期限 `set_user_expiry`、邀请码审计 `get_invite/list_invites`。scrypt 哈希（标准库，零依赖；格式串带算法标识，可平滑升级 argon2）。
- 单测：注册（有效/无效/已用邀请码/重名/弱口令）、登录（对/错/禁用/**到期**/锁定）、会话（签发/校验/过期/吊销）、改密后旧 session 失效、`user_id` 字符集、**账号期限**（到期拒登/拒 authenticate、清期限恢复）、**邀请码消费查询**（used_by/used_at）。**全用临时 sqlite，不碰真实环境。**

**阶段 B · 挂到 aiohttp 网关** ✅ 已完成（2026-07-01）
- `famou_scientist/multitenant/gateway.py`：aiohttp 鉴权网关，摆在前端 `server.mjs`(:4096) **之前**。
  - 认证端点（极简内联 HTML）：`GET/POST /login`、`/signup`、`POST /logout`、`GET /account`、`POST /account/password`；成功种 `famou_sid` cookie（`HttpOnly; SameSite=Lax; Path=/`，`--secure-cookie` 开 `Secure`）。**角色分流**：登录成功后管理员重定向到 `/admin`（管理工具页），普通用户到 `/`（研究台）；注册者必为普通用户 → `/`。
  - `auth_middleware`：公开白名单放行；其余读 cookie → `store.authenticate` → 未登录时 **XHR/JSON 请求 401、否则 302 /login**；命中则挂 `request["user_id"]`/`["user"]`。
  - admin 端点（JSON，`role=admin` 校验）：`GET /admin/users`、`POST /admin/users/{id}/disable|enable|expiry|reset-password`、`POST /admin/invites`、`GET /admin/invites`、`POST /admin/invites/{token}/revoke`——全部转发到阶段 A 的 `IdentityStore`，网关**不含新鉴权逻辑**。
  - **可视化管理页** `GET /admin`（内联 HTML+JS，零构建）：管理员在网页上列用户/邀请码、发码、禁用启用、设期限、吊销码、重置口令（前端 fetch 调上述 JSON 端点）；`/account` 页对 admin 显示入口链接；非 admin 访问 `/admin` 返回 403 HTML。
  - 兜底 `_proxy`：`ClientSession(trust_env=False)`（绕环境代理）流式反代到**单个固定上游**（`--upstream`，默认 `http://127.0.0.1:4096`），`StreamResponse` 边收边写透传 SSE，剥逐跳头，注入 **`X-Famou-User: <user_id>`**（给下游编排层 ③ 的身份钩子）。
  - **单写者锁**：启动抢 `<AUTH_DB>.lock` pidfile，存活 pid 持有则拒绝启动（防 CFS 双写）。
  - 入口：`famou-scientist serve-multi`（全参数）；或便捷 `famou-scientist admin USER:PASS`（起网关 + 引导管理员 + 自动选空闲端口(4095起) + 开浏览器 /admin）。`famou web`（内部单用户）默认行为完全不变。
- 单测 `tests/test_gateway.py`（aiohttp TestClient + 假上游回显 `X-Famou-User`）全绿：门禁 302/401、公开页开放、登录→反代注入身份、登录错误、**角色分流重定向**、注册种 cookie/坏邀请码、登出失效、admin role 403、邀请码生命周期（used_by）、**到期/禁用即时掉线**、set-expiry 端点、**admin 管理页 200/403**。
- 边界：只反代**单个**上游；每用户实例路由 / 起容器 / GPU 属阶段 C（下游编排层，工程同学评估）；外网暴露属网络层，本阶段内网自测闭环。

**阶段 C · 每用户独立实例 + 管理台用量（轻量版，进程模型不上容器）** ✅ 已实现（2026-07-02）
- `multitenant/spawner.py`：`Spawner` 按 `user_id` 懒启动"每用户一套（opencode 后端 + server.mjs 前端）"，
  数据隔离靠 `FAMOU_DATA_DIR→XDG_DATA_HOME`（launcher.build_env）——每用户 opencode.db 落各自本地盘目录。
  生命周期 `SPAWNING→RUNNING⇄STOPPED（数据留盘，复用 data_dir→历史延续）/FAILED`；空闲回收（reaper 后台任务）、
  并发上限（满则回收最久空闲/`CapacityError`）、per-user 锁防并发首访重复起、crash 清理后重拉、close 全清。
  复用 `web._find_free_port/_wait_backend/_terminate/_inject_egress_proxy`（server.mjs **零改动**）。
- `gateway.py`：`build_app(..., spawner=)`；`_proxy` 有 spawner 时 `ensure(user_id)` → 反代到该实例端口，
  `CapacityError`→503 / `SpawnError`→502 友好降级。`serve-multi` **默认启用每用户实例**（`--single-upstream` 回退阶段 B 单上游）；
  `--data-root`（默认 `~/.local/share/famou-mt`，**本地盘**）/ `--work-root`（默认 CFS `.../famou-scientist-user-db/work`）
  / `--max-instances`(20) / `--idle-timeout`(1800) / `--web-port-base`(4200) / `--oc-port-base`(4600)；
  `--data-root` 落网络盘时 stderr 告警（sqlite 锁不可靠）。隔离布局：
  `<data-root>/<uid>/opencode/opencode.db`（用户级独立库，session 是库内概念 → 天然不跨用户）+ `<work-root>/<uid>/research-runs/`。
- 管理台用量：`GET /admin/users/{uid}/usage`（只读该用户 opencode.db，复用 `trace._connect`(mode=ro 不锁库)
  + `trace_web.build_sessions_payload` + `session_header` 汇总总 cost/总 tokens/会话数/最近活动 + 实例运行状态）、
  `GET /admin/users/{uid}/trace?session=`（复用 `build_trace_payload`）。`/admin` 页每用户加「用量/轨迹」弹层：
  实例状态徽标 + 汇总卡 + 会话列表 → 点会话看轨迹。uid 过 `_USER_ID_RE` 防路径穿越。
- 单测：`test_spawner.py`(9，假后端)、`test_gateway_spawner.py`(3，反代到用户实例/双用户不同端口/容量满降级)、
  `test_gateway_usage.py`(6，汇总/空库/鉴权/非法uid/轨迹/未知会话)；`spawner=None` 时旧 57 项无回归。**共 75 项全绿。**
- **已知取舍**：opencode.db 必须本地盘（CFS 锁不可靠）→ 换机丢会话历史；research-runs 产物走 CFS 留档。
- 边界（未做）：容器化 / GPU 绑定 / 跨机（真·阶段 C，工程同学后续）；外网暴露（网络层）。

**阶段 C+（更远）· 交接给容器/集群编排层**
- 把进程版 Spawner 换成容器版（DooD 起 fm-tenant 容器 + 绑 GPU），复用现有 fm-job 底座（见 MULTI_TENANT_DESIGN.md）。

### 端到端验证清单
1. `identity.py` 单测全绿（注册/登录/会话/改密/限流/字符集）。
2. 管理员生成邀请码 → 用它注册 A → 得 cookie → `authenticate` 返回 A 的 user_id。
3. 无邀请码 / 用过的码注册 → 拒绝。
4. 错误口令 N 次 → 锁定 + 延迟。
5. A 登录态访问受保护路径通过；登出后同 cookie 被拒。
6. admin 禁用 A → A 的 session 立即失效、无法登录。
7. 换机演练：新网关挂同一 CFS `identity.db` → 用户无感继续登录（数据在 CFS 不丢）。
8. 单写者锁：起第二个网关实例 → 抢锁失败退出（防双写）。
9. **（阶段 C）** `serve-multi --data-root <本地盘>` → 用户 A、B 各登录各拿独立实例（不同端口、不同 opencode.db）→ A 看不到 B 会话。
10. **（阶段 C）** 管理员 `/admin` →「用量/轨迹」显示每用户总 cost/tokens/会话数 + 实例状态 → 点会话看轨迹。
11. **（阶段 C）** 空闲超时实例被回收、再次访问自动重启且历史延续；`--data-root` 指 CFS → 启动期告警。

---

## 11. 已定决策（2026-07-01 评审通过）
1. **口令**：最小长度 **8**，不强制复杂度；**不做邮件找回**（无邮件系统）→ 忘密码由**管理员重置**。
2. **会话**：TTL **7 天**；不做"记住我"/多设备管理；**管理员禁用用户即刻吊销其 session（掉线）**。
3. **首个管理员**：首次启动 `serve-multi --admin <user>:<pass>` 自动创建，之后由他发邀请码。
4. **审计**：只记大事——**注册 / 登录 / 禁用**（不记每次页面访问；绝不记口令/token 明文）。
5. **注册**：邀请码即管控闸门，**不加**额外"注册后人工审核"。邀请码**一次性、用完即失效（数据库条件更新保证）、可设过期、管理员可吊销未用码**。
6. **SSO**：**暂不考虑**（`authenticate` 已隔离为单函数，将来要接再定 IdP 类型，不影响当前实现）。
7. **账号管控（2026-07-01 追加）**：
   - **使用期限**：可给账号设 `expires_at`（"只给用一段时间"）；到期后 `authenticate`/`login` **自动拒绝**（`AccountExpired`），并即刻吊销其会话（掉线）；置 `null` 解除。与"手动 disable"互补——一个到点自动、一个随时手动。
   - **邀请码消费审计**：邀请码被消费时已写入 `used_by`（注册者 user_id）/`used_at`（时刻）；新增 `get_invite`/`list_invites` 查询接口，管理员可回看**谁在何时用了哪个码**。
