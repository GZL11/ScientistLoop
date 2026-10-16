# Famou 多租户 Web 服务 — 完整技术设计（v2·容器化+业界调研）

> 状态：设计稿（待评审）｜最后更新：2026-07-01
> 关联：`docs/multitenant/MULTI_TENANT_MVP.md`（早期可行性评估）。本文档是 v2，基于业界方案调研重写，**方案从"单机多进程"改为"单机每用户一容器"**，并明确 **不使用 k8s**。

---

## 0. 一句话

在**不改动现有 `famou-scientist web`（单机开发者模式）**的前提下，参照 **JupyterHub 的 Hub+Proxy+Spawner 架构**（单机 Docker 版，非 k8s），
为每个注册用户拉起**一个独立的 famou 容器**；一个对外网关做**注册/登录/路由**；用户数据与镜像**全部外置**（镜像入仓库、数据入 CFS），
让**机器变成可随时替换的纯算力**。GPU 借鉴 **ComfyUI 云服务**的做法：控制面（每用户轻实例）与算力面（共享 GPU）分离。

---

## 1. 业界调研：类似服务都怎么做的

我们的需求本质是「**多用户 + 每人一个有状态的 web 服务 + 稀缺 GPU**」。业界有三类成熟参考：

### 1.1 JupyterHub —— "每用户一容器 web 服务"的教科书（最贴合，重点借鉴）
JupyterHub 就是"多用户、每人一个 notebook server、带认证和路由"的标准答案，四个子系统：

| 组件 | 职责 | 对应到 famou |
|---|---|---|
| **Hub** | 认证、管理用户、**Spawner 拉起单用户实例** | 我们的网关（注册/登录/起容器） |
| **Proxy**（configurable-http-proxy） | **动态路由** HTTP 到 Hub 或某用户实例 | 网关的反代层（按用户路由到其容器） |
| **Spawner** | 怎么起单用户实例；**DockerSpawner=每人一个容器** | 我们的"起 famou 容器"逻辑 |
| **Authenticator** | 认证方式（可插拔：本地账号/OAuth/LDAP） | 我们的 identity（注册/登录，可插拔换 SSO） |

**关键收获**：
- **单机不用 k8s 也能跑**——`DockerSpawner` 在单机用 Docker 给每人起容器；**TLJH（The Littlest JupyterHub）**就是"单机、~100 用户以内、不用 k8s"的官方发行版，正是我们的规模和约束。
- 架构是**动态路由代理 + 按需 spawn**：用户登录→Hub 认证→Spawner 起他的容器→Proxy 把后续请求直接路由到该容器。**这套模式我们照搬。**
- z2jh（Kubernetes 版）**不适用**（我们不用 k8s），但架构模式与 DockerSpawner 一致。

### 1.2 Coder / code-server —— 每用户一个开发容器（印证方案）
Coder 是自托管的"每用户一个远程开发环境"，架构与 JupyterHub 同构：
- **控制面 `coderd`**（认证/编排/状态，用 PostgreSQL 存元数据）+ **每用户一个 workspace 容器** + **模板定义容器长什么样**（镜像/资源/挂载卷）。
- 可**纯 Docker + docker-compose 部署，不需要 k8s**；每 workspace 是独立容器，挂 volume 持久化。
- **印证两点**：① 控制面元数据用**正经数据库**（Postgres），不用 sqlite 硬扛并发；② 每用户容器 + 持久卷是这类服务的标准形态。

### 1.3 ComfyUI 云服务（RunComfy/Runpod）—— 稀缺 GPU 怎么服务多用户（GPU 部分借鉴）
ComfyUI 原生单用户（全局队列+共享状态），云服务的多用户方案高度一致：
- **不给每用户绑一张常驻 GPU**（太浪费）；而是 **任务队列 + GPU worker 池**：N 个 GPU worker（通常一 GPU 一 worker）从队列领活，谁空谁领，**GPU 是"任务级共享"不绑用户**。
- **控制面/算力面分离**：用户交互层（轻，不占卡）与 GPU 执行层（共享池，按需/排队）解耦；serverless 方案还做 scale-to-zero（跑完释放 GPU）。
- **给 famou 的启示**：famou 的 web/对话/看产物**不吃 GPU**，适合每人一个轻容器常驻；而**跑实验（吃 GPU）**应学 ComfyUI——不在用户容器里直接抢卡，而是**提交到共享 GPU 队列**（这正好和你要的 **fm-job** 呼应）。

### 1.4 GPU 单机多容器共享（NVIDIA 官方三种，不依赖 k8s）
| 方式 | 显存隔离 | 算力隔离 | 适用 |
|---|---|---|---|
| **默认 `--gpus device=N`** | 否 | 时间片 | 最简；一容器绑一卡，或多容器共卡（会抢） |
| **MIG**（A800 支持！） | **硬件级** | **硬件级** | 把一张 A800 切成 2~7 份，每份当独立卡给一个容器，**硬隔离** ✅ |
| **MPS** | 否 | 空间共享 | 多进程并发共享一卡，利用率高，无显存硬隔离 |

**对我们**：8×A800-80G + **MIG** → 可把卡切成更多份，服务更多"轻量吃卡"用户；重训练则整卡绑定或走 GPU 队列。

---

## 2. 目标与非目标

### 目标
- **双模式并存**：现有 `famou web` 零改动；多租户是**新入口 + 新目录**，参照 JupyterHub 模式实现。
- **用户注册/账号管理**：注册、登录、改密、登出；管理员列/禁用/删/邀请/看用量。
- **每用户一个 famou 容器**：独立会话/产物/数据，物理隔离。
- **共用平台 key、数据隔离**：key 只在容器 env（网关注入），用户不可见。
- **稳定可迁移**：机器可随时换——镜像入仓库、数据入 CFS、一键重建。
- **GPU 可控**：先整卡/ MIG 分配 + 每用户并发闸门；演进到 GPU 队列（对接 fm-job）。

### 非目标
- **不用 k8s**（用单机 Docker + docker-compose / Docker SDK 编排，走 TLJH/Coder 的单机路子）。
- 不改现有 `famou web` / opencode / 研究流程（容器里跑的就是现成 famou）。
- 本期不做团队/共享空间（先一人一租户）。
- 本期不做真高可用（单机宕机=中断，见 §7 诚实局限）。

---

## 3. 架构（JupyterHub 模式 · 单机 Docker）

```
                 ┌──────────────────────────────────────────────────┐
   外部用户  ───►│  Gateway（"Hub"，唯一对外，前置 TLS）               │
  (注册/登录/用) │  ┌─────────────┬──────────────┬─────────────────┐ │
                 │  │ Authenticator│ Spawner       │ Proxy            │ │
                 │  │ 注册/登录/   │ 起/停/复用    │ 动态路由：按用户  │ │
                 │  │ 会话(可插拔) │ 用户容器      │ 转到其容器端口    │ │
                 │  │ →Postgres   │ (Docker SDK)  │ (HTTP+SSE)       │ │
                 │  └─────────────┴──────────────┴─────────────────┘ │
                 └──────┬─────────────────────┬─────────────────────┘
                        │                     │
         ┌──────────────▼──────┐  ┌───────────▼───────────┐
         │ 用户A 容器           │  │ 用户B 容器             │  …每人一个
         │ famou-scientist web │  │ famou-scientist web   │  (镜像=同一个)
         │ 挂载:               │  │ 挂载:                 │
         │  /data→CFS/users/A  │  │  /data→CFS/users/B    │  产物落 CFS
         │  db→本地盘+备份CFS   │  │  db→本地盘+备份CFS     │  (sqlite 见§6)
         │ env: 平台key(注入)  │  │ env: 平台key(注入)    │  key 不入镜像
         │ --gpus 按需/MIG     │  │ --gpus 按需/MIG       │
         └─────────────────────┘  └───────────────────────┘

  镜像 ← 私有 Registry(可pull)     数据 ← CFS(独立于机器)     key ← 运行时注入
  机器=可丢弃纯算力：换机 = 新机 pull镜像 + 挂同一CFS + 注入key + 起容器
```

**技术选型**：
- 网关/Hub：**aiohttp**（async、SSE 透传天然、中间件挂鉴权、能调 Docker SDK）。
- Spawner：**Docker SDK for Python**（`docker` 库）起/停容器；或 shell 出 `docker run`。**不用 k8s。**
- 控制面元数据：**Postgres**（学 Coder/JupyterHub，账号/会话/实例映射；避免用 sqlite 扛并发）。
- 反代：aiohttp 里实现（HTTP + SSE `StreamResponse` 逐块透传，去 hop-by-hop 头）。

---

## 4. 用户注册与账号管理

### 4.1 元数据（Postgres，不是 sqlite——控制面要并发）
`users(user_id, username, pass_hash[argon2id], role, status, quota_json, created_at)`、
`sessions(sid, user_id, expires_at, ...)`、`invites(token, used_by, ...)`、
`instances(user_id, container_id, port, gpu_binding, state, last_active)`。

### 4.2 注册模式（`--signup-mode`）
`open`（自助，需防刷）｜`invite`（受邀，**推荐默认**）｜`closed`（仅管理员建号）。

### 4.3 认证（可插拔，学 JupyterHub Authenticator）
`POST /signup` / `/login` / `/logout` / `/account/password`；session cookie（`HttpOnly+SameSite+Secure`）。
**可插拔接口 `authenticate(request)->user_id|None`**——换公司 SSO/OAuth 只改这一个函数。

### 4.4 管理员台
`/admin/users`（列：状态/容器状态/磁盘/额度）、`disable|enable|delete`、`/admin/invites`、`/admin/usage`。
删账号默认**归档不物删**（§6）。

---

## 5. 容器化：镜像与每用户容器

### 5.1 镜像（一个基础镜像，所有用户共用）
- 基础：`python3 + node24 + opencode(npm 0.13.7)`。**好消息：famou 包 `dependencies=[]`（纯标准库），不引入依赖地狱。**
- 可选：TinyTeX（latex 编译）；实验重依赖（torch 等）**运行时按需装**（镜像小、启动快；首次跑实验联网装，走代理）——先这样，后续可做"预装重依赖"的胖镜像变体。
- famou 源码：**先用挂载**（`-v famou仓库:/app`，改代码即生效，适合仍在迭代）；稳定后改 pip 装进镜像固定版本。
- **key 绝不进镜像**（红线）——只在 `docker run -e` 运行时注入。

### 5.2 每用户容器（Spawner 起）
```
docker run -d --name famou-<user_id> \
  -e ANTHROPIC_BASE_URL=... -e ANTHROPIC_AUTH_TOKEN=... （网关注入，不入镜像）\
  -v /path/to/workspace/famou-tenants/<user_id>/work:/work         （产物→CFS）\
  -v /local-ssd/famou-tenants/<user_id>/xdg:/xdg               （db→本地盘，见§6）\
  -e FAMOU_DATA_DIR=/xdg -e ARC_JOBS_DIR=/work/.famou_jobs \
  --restart unless-stopped \
  [--gpus '"device=N"' | MIG 实例]  \
  famou-image  famou-scientist web --host 0.0.0.0 --port 8080
```
容器内仍是**现成的 `famou-scientist web`**（零改动）；隔离靠 `FAMOU_DATA_DIR`/`cwd`/`ARC_JOBS_DIR`（已有 env 旋钮）+ 容器边界双保险。

---

## 6. 稳定性与可迁移（机器是租的 → 机器可丢弃）

### 6.1 核心原则：牛，不是宠物。把"不能丢的"全外置
| 层 | 归属 | 对策 |
|---|---|---|
| 机器、容器 | 可丢弃 | 随时能重建 |
| **镜像** | 必须持久 | **推私有 Registry**；无仓库则 `docker save` tar 存 CFS。别只活在本机 docker |
| **用户产物**(research-runs) | 必须持久 | **bind mount 到 CFS**（`/path/to/workspace`，已确认是 `fuse.cfs` **网络盘，独立于机器**）。普通文件，无锁问题 |
| **会话 db**(opencode.db, sqlite) | 必须持久但**有坑** | 见 §6.2 |
| **密钥/配置** | 必须持久 | env/secret 注入 + 重建脚本入 git |

### 6.2 关键技术张力：sqlite 不能直接放 CFS（重点）
- opencode.db 是 **sqlite**，而 **sqlite 在网络/FUSE 文件系统上的文件锁不可靠**（可能损坏/锁失败；famou 的 `_network_fs_type` 告警正为此）。
- 但"迁移不丢"又要求 db 持久化到机器外。**这俩打架。**
- **采纳方案**：db 放**机器本地盘/SSD**（快、锁可靠）+ **定期备份/快照到 CFS**（如每 5 分钟 rsync 或 sqlite `.backup`）。RPO=备份间隔（分钟级，可接受），换机时从 CFS 恢复 db。
- **产物文件放 CFS**（无锁问题），**db 放本地+备份**——分开对待。

### 6.3 诚实局限：单机 Docker ≠ 高可用
| 目标 | 单机 Docker+CFS+Registry |
|---|---|
| 数据不丢（RPO≈分钟级） | ✅ |
| 快速恢复（RTO=分钟级，新机重建） | ✅ |
| **零中断（机器宕机自动切）** | ❌ 单机做不到，需多机编排 |
对"租用单机"的现实目标 = **可恢复 + 数据安全**，不是高可用。要零中断得上多机（届时才需要 swarm 或托管，仍可不碰 k8s）。

### 6.4 换机 Runbook（把"迁移"变成一条流程）
新机器：装 Docker + nvidia-container-toolkit → `docker pull famou-image`（从仓库）→ 挂同一份 CFS → 从 CFS 恢复各用户 db → 注入平台 key → `docker-compose up` 网关 → 网关按 `instances` 表重拉用户容器。**RTO 分钟级，数据不丢。**

---

## 7. GPU 策略（分两步，呼应 ComfyUI 与 fm-job）

**现状**：famou/sandbox **无任何 GPU 调度**，GPU 全靠 agent 在实验 code.py 手写 `CUDA_VISIBLE_DEVICES`。8 张卡是物理天花板，与是否容器化无关。

- **第一步（MVP，容器内跑实验）**：每用户容器按需绑卡——`--gpus device=N` 或 **MIG** 切分（A800 支持，可把 8 卡切成更多份服务更多轻量用户）；配 **每用户并发实验数 ≤1** 闸门防抢。简单，先能用。
- **第二步（演进，学 ComfyUI 控制面/算力面分离）**：用户容器**不直接跑 GPU 实验**，而是把实验**作为作业提交到共享 GPU 队列**（**fm-job**）——排队、按卡分配、跑完释放。GPU 利用率最高，用户容量与 GPU 解耦。**这一步同时服务你要的 RCB 批量评测。**

---

## 8. 配额与限流（共用 key → 强制配套，否则被烧爆）
每用户：并发实验数（≤1~2，GPU 闸门）、QPS 限流、磁盘配额、可选 token/额度上限；
全局：最大容器数、闲置容器回收（默认 30min 停/休眠，释放资源）、崩溃 `--restart` 自愈。

---

## 9. 安全边界（红线）
平台 key 只在容器 env（网关注入），**绝不**入镜像/db/产物/日志/前端；口令 argon2id 哈希；session 高熵 cookie；
`user_id` 限字符集挡穿越；容器边界隔离越权；CFS 落盘的产物按用户子树隔离。

---

## 10. 分阶段落地（不用 k8s）

| 阶段 | 内容 | 验收 |
|---|---|---|
| **0 · 镜像跑通单容器** | 写 Dockerfile（源码挂载+运行时装依赖）；`docker run` 起 1 个容器 | 容器内 `famou web` 模型能应答、产物能看、latex 能编 |
| **1 · 数据外置 + 稳定性** | 产物 bind mount CFS；db 本地+定时备份 CFS；镜像推仓库；换机 runbook 演练 | 删容器/换机后数据不丢、能一键重建 |
| **2 · 网关 + 注册（JupyterHub 模式）** | aiohttp Hub：注册/登录/会话(Postgres) + Docker SDK Spawner + 反代(HTTP+SSE) | 两用户各注册登录、各自容器、互不可见 |
| **3 · 配额 + 生命周期** | 每用户并发/QPS/磁盘、闲置回收、崩溃自愈、全局上限 | 一人跑满不拖垮他人 |
| **4 · 管理台 + 对外暴露** | admin 页；网关 0.0.0.0+TLS+对外通道（frp/托管，见 MVP §10） | 管理员可运营；外部浏览器直达 |
| **5 · GPU 队列（可选，接 fm-job）** | 实验执行 → 提交作业到共享 GPU 池 | 多人错峰共享 8 卡，利用率高 |

---

## 11. 与 v1（单机多进程）方案的差异
| 维度 | v1 多进程 | **v2 每用户容器（本文档）** |
|---|---|---|
| 隔离 | 数据硬、资源软（要自配 cgroup） | 数据+**资源硬隔离**（`--memory/--cpus/--gpus` 免费送） |
| GPU 分配 | 无协调 | `--gpus`/MIG 硬绑定，可切分 |
| famou 改动 | 要抽 spawn 纯函数 | **几乎不改**（容器跑现成 famou） |
| 稳定/迁移 | 状态在机器本地，难迁 | 镜像入仓库+数据入 CFS，**可丢弃机器** |
| 崩溃爆炸半径 | 进程组 | 容器内核级隔离，最小 |
| 参照 | 自研 | **JupyterHub/Coder 成熟模式** |
| 代价 | 省镜像、启动快 | 镜像维护、冷启动、GPU runtime |
**结论**：对"租用单机 + 要稳定 + 有 GPU"的场景，**v2 容器化更优**——资源硬隔离和可迁移性是白送的，且有成熟先例（JupyterHub 单机/TLJH、Coder）。

---

## 12. 开放问题（需拍板）
1. **镜像仓库**：有没有公司 Harbor/私有 registry？（决定镜像持久化方式）
2. **CFS 跨机可挂载性**：换机后新机能挂同一份 `/path/to/workspace` 吗？（"迁移不丢"的地基）
3. **本地盘**：机器有没有本地 SSD 放 sqlite db？（§6.2 的前提）
4. **注册模式**：open/invite/closed？
5. **GPU 分配**：先整卡绑定，还是一上来就 MIG 切分？何时接 fm-job 队列？
6. **可接受中断窗口**：机器宕机后"分钟级新机恢复"能接受吗（=单机足够），还是要零中断（=多机）？
7. **账号体系**：先自建轻量账号，还是直接接公司 SSO？

---

## 附：为什么这套不需要 k8s
JupyterHub 的 **TLJH（单机版）**、Coder 的 **docker-compose 部署** 都证明：**单机、~100 用户内、每人一容器**，用 **Docker SDK/compose + 一个路由代理**就够，k8s 是"多机调度"才需要的。我们单机单目标，**用 Docker + aiohttp 网关（Hub+Proxy+Spawner 模式）** 即可；未来真要多机再谈编排（也可选 swarm，仍不必上 k8s）。
