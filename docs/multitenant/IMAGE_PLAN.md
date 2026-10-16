# Famou 多租户 — 标准化镜像方案

> 状态：设计稿｜2026-07-01｜配套 `docs/multitenant/MULTI_TENANT_DESIGN.md`（v2 容器化方案）的**阶段0：镜像跑通单容器**

---

## 0. 为什么要做这个镜像

现状（实测 2026-07-01）：现有 16 个 `fm-<user>` 容器**没有一个是"开箱即用 famou"的**。它们的构成是：

| 组件 | 现在从哪来 | 问题 |
|---|---|---|
| 基础镜像 `lihuaiming/famou_lihuaiming:v1` | registry | **是空壳**——连 conda 都没有 |
| miniconda（15G，含 `famou` env 7.1G） | **容器内手动装** | 每容器装一遍，不一致 |
| node v24.16.0（nvm，1G）+ opencode-ai@1.17.11（npm global） | **容器内手动装** | 同上；测过的 `coral-fm-job`/`famou_dev` 镜像里都没 node |
| TinyTeX（204M，latex 编译用） | **容器内手动装** | 同上 |
| famou-scientist 0.1.0 | **editable 指向 CFS 源码** | `python -m famou_scientist` 跑，which 为空 |

**结论**：每个用户容器 = 拉空壳 → 手动装 miniconda/node/opencode/TinyTeX → 挂 CFS 源码。**多租户要自动化 spawn，第一步就是把这套手动流程固化成一个标准镜像**——否则网关每起一个容器都要手动配，不可能自动化。

（这也是早期"多人串会话"的根：手动搭、无标准，数据目录/端口全靠约定，一乱就串。）

---

## 1. 两条路（推荐 A 先行）

### 路 A：`docker commit` 当前配好的容器 → 立刻可用（推荐先做，30 分钟出镜像）
当前 `gezengle_fm` 容器已经手动配好了全套（miniconda+famou env+node+opencode+TinyTeX）。直接固化它：
```bash
# 1. 从运行中的容器提交成镜像（把当前状态整个打包）
docker commit gezengle_fm <你的镜像仓库>/famou-public/famou-tenant:v1

# 2. 推到私有 registry（换机可 pull）
docker push <你的镜像仓库>/famou-public/famou-tenant:v1
```
- ✅ 最快，零构建风险，所见即所得。
- ⚠️ 缺点：不可复现（不知道里面到底怎么装的）、体积大（含 CFS editable 指向，换机若不挂同名 CFS 会断）。
- **适合**：先跑通阶段0，验证"一个标准镜像能起 famou web"。

### 路 B：写 Dockerfile 从可复现地构建（推荐稳定后转正）
把手动流程写成 Dockerfile（见 §2）。可复现、可维护、可审计、体积可控。
- **适合**：方案定型后作为正式镜像。

> 建议：**A 先跑通阶段0，B 作为转正镜像**。下面 Dockerfile 是 B。

---

## 2. Dockerfile（路 B，可复现构建）

见同目录 `Dockerfile.famou-tenant`。设计要点：

- **基础**：用一个带 CUDA 的基础镜像（如 `nvidia/cuda:12.1-runtime-ubuntu22.04` 或你们已有的 `coral-fm-job` 系——它已带 python3.12+torch+cuda）。GPU 由宿主 nvidia runtime 透传，镜像不装驱动。
- **固化四件套**：miniconda + famou conda env（py3.12）、node v24.16.0、opencode-ai@1.17.11（npm -g）、TinyTeX。
- **famou 源码两种模式**：
  - **迭代期（默认）**：不 COPY 源码，运行时 `-v CFS源码:/app` 挂载 + `pip install -e /app`（改代码即生效）。
  - **稳定期**：`COPY` 源码 + `pip install /app` 固化版本（可复现、不依赖 CFS）。
- **key 绝不进镜像**：`ANTHROPIC_*` 只在 `docker run -e` 注入。
- **入口**：`famou-scientist web --host 0.0.0.0 --port 8080`（容器内对外，宿主/网关再反代）。
- **opencode 配置**：`~/.config/opencode/opencode.jsonc` 用 `{env:...}` 占位（不硬编码 key），可 COPY 一份模板进镜像。

---

## 3. 每用户容器怎么起（DooD，兄弟容器）

网关（阶段2）在**当前容器内**发 `docker run`（经挂载的宿主 docker.sock）→ 宿主 daemon 起**兄弟容器**：
```bash
docker run -d --name famou-tenant-<user_id> \
  --restart unless-stopped \
  -e ANTHROPIC_BASE_URL="$PLATFORM_BASE" -e ANTHROPIC_AUTH_TOKEN="$PLATFORM_KEY" \
  -e FAMOU_DATA_DIR=/xdg -e ARC_JOBS_DIR=/work/.famou_jobs \
  -v /path/to/workspace/famou-tenants/<user_id>/work:/work \
  -v /local-ssd/famou-tenants/<user_id>/xdg:/xdg \
  [-v /path/to/workspace/.../famou-scientist:/app]  # 迭代期挂源码 \
  --gpus '"device=<N>"'  # 或 MIG 实例；由网关按 fm.gpu_ids 思路分配 \
  <你的镜像仓库>/famou-public/famou-tenant:v1
```
**路径是宿主视角**（docker.sock 执行者是宿主）——好在数据都在 CFS（`/path/to/workspace`，宿主/容器挂载点一致），天然对齐。db 走本地盘 `/local-ssd`（sqlite 不能放 CFS，见主文档 §6.2）。

---

## 4. 与现有 fm 平台的关系（重要，避免重复造）

现有容器带 `fm.node` / `fm.gpu_ids` / `fm.username` label ——说明**已有一套自研平台在管 per-user 容器 + GPU 绑定**（很可能就是 fm-job 的底座）。

**强烈建议先问清**：能否让多租户网关**复用这套 fm 平台**来 spawn 容器（把"起容器+绑GPU"交给它），网关只做"注册/登录/路由"？若可行，本文档的 `docker run` 那步就换成"调 fm 平台 API 起容器"，**省掉自己管容器生命周期和 GPU 分配的一大半工作**。标准化镜像（本文档）无论走哪条都需要，不浪费。

---

## 5. 落地顺序
1. **路 A `docker commit`** 出 `famou-tenant:v1`，`docker run` 起一个干净容器，验证 famou web 能应答/看产物/编 latex（阶段0 验收）。
2. 数据外置演练：产物挂 CFS、db 挂本地盘，删容器后数据不丢。
3. 写 **Dockerfile（路 B）** 转正为可复现镜像，推 registry。
4. 确认能否复用 fm 平台 spawn（§4）→ 定网关起容器的方式。
5. 进主文档阶段2（网关+注册）。

## 6. 待确认
- 基础镜像选哪个（`coral-fm-job` 已带 py3.12+torch+cuda，可省一半）？
- famou 源码：迭代期挂 CFS 还是直接固化进镜像？
- 能否复用 fm 平台 spawn 容器 + 绑 GPU（§4）？
- db 用的本地 SSD 路径（`/local-ssd`?）宿主上是哪个？
