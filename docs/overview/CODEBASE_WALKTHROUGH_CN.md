# Famou-Scientist / AutoResearchClaw 代码库全景梳理

> 面向：内部工程同学，用于理解这套系统的结构、边界与对接面，方便后续工程合作。
> 一句话：**一个「科研 Agent」——底座是 OpenCode（对话/规划/执行的 master agent），我们以「插件资产」的形式给它注入科研能力（工具 + 护栏 + 方法论 skill），再套一层产品壳（CLI + Web 研究台）。**

---

## 0. 一图看懂

```
┌──────────────────────────────────────────────────────────────────────┐
│  两个代码仓库                                                             │
│                                                                        │
│  ① AutoResearchClaw（开源，Python 引擎）   ② famou-scientist（内部 LIVE 产品） │
│     researchclaw/  —— 自主科研流水线引擎        famou_scientist/ —— 产品壳       │
│     arc-opencode-plugin/ —— 接入 OpenCode 的样板   assets/opencode/ —— 生产版插件资产 │
└──────────────────────────────────────────────────────────────────────┘

运行期三层（LIVE 产品实际跑的形态）：

  用户 ──▶ ① 产品壳（CLI / Web 研究台）
                │  launcher 注入环境变量 + 资产目录
                ▼
           ② OpenCode（master agent：对话、规划、调用工具、跑 hook）
                │  从 OPENCODE_CONFIG_DIR 加载我们的插件资产
                ▼
           ③ 科研能力插件资产（assets/opencode/）
                ├─ AGENTS.md      科研流程编排（软约束：system prompt）
                ├─ tool/arc.ts    11 个"真执行"工具（TS 壳 → 调 Python 内核）
                ├─ plugins/*.ts   强制护栏 hook（硬约束：拦截工具输出）
                ├─ skill/         40 个方法论 skill（SKILL.md）
                └─ scripts/*.py   17 个自包含 Python 内核（零三方依赖）
```

**三种约束强度**（贯穿整个设计）：
- **软（知识）**：`skill/` 里的 SKILL.md — agent 该做某步前先"读方法论"。
- **中（工具）**：`tool/arc.ts` — agent 调真执行工具（检索文献、跑实验、核验引用）。
- **硬（护栏）**：`plugins/*.ts` 的 hook — 拦截工具输出，发现造假/幻觉/不合规就强制改（agent 绕不过）。

---

## 1. 两个仓库的关系（最容易混淆，先讲清）

| | ① AutoResearchClaw（开源） | ② famou-scientist（内部 LIVE 产品） |
|---|---|---|
| 定位 | **科研流水线引擎** + OpenCode 接入样板 | **对外产品**：把能力打磨成好用的 CLI / Web |
| 语言 | Python（`researchclaw/` 包，26+ 子命令） | Python 产品壳（`famou_scientist/`）+ TS 插件资产 + React 前端 |
| 依赖 | 有自己的依赖 | **`dependencies = []` 零依赖**（核心壳），aiohttp 等是可选 |
| 与对方关系 | 被参考/被抽取 | **不 import researchclaw**：把需要的执行内核（检索/沙箱/核验）**抽成纯 stdlib 脚本拷进 `assets/opencode/scripts/`** |
| 路径 | `/mnt/.../opensource/AutoResearchClaw/` | `/mnt/.../famou-scientist/baidu/acg-fm/famou-scientist/` |

**关键结论给工程同学**：LIVE 产品 **不直接跑 researchclaw 那套 23 阶段 Python 状态机**。它走的是「OpenCode 当 master agent + 我们注入的插件资产」这条路。researchclaw 是能力来源/参考实现；真正部署跑的是 famou-scientist 这套。两者的桥梁 = **arc-opencode-plugin 这套接入范式**（下节）。

---

## 2. 插件集成层（工程合作的核心，重点看这节）

### 2.1 OpenCode 是什么、我们怎么插进去

OpenCode = 开源的 master-agent 框架（npm 包 `opencode-ai`，`opencode serve` 起 HTTP/SSE 后端 + TUI）。它原生支持三种扩展点，我们**零改 OpenCode 源码**、纯"加资产"接入：

| 扩展点 | OpenCode 怎么发现 | 我们放什么 |
|---|---|---|
| **instructions** | `opencode.json` 里 `instructions: ["AGENTS.md"]` | 科研流程编排 system prompt |
| **tool** | 自动扫描配置目录下 `tool/*.ts` 的 `export const x = tool({...})` | `tool/arc.ts`（11 个工具） |
| **plugin/hook** | 自动扫描 `plugins/*.ts` 的 `export const X: Plugin` | 4 个护栏/运维插件 |
| **skill** | `opencode.json` 里 `skills.paths: ["skill"]` | 40 个 SKILL.md |

`assets/opencode/opencode.json` 本体极简：
```json
{ "$schema": "https://opencode.ai/config.json",
  "instructions": ["AGENTS.md"],
  "skills": { "paths": ["skill"] } }
```

### 2.2 arc-opencode-plugin（开源样板）vs assets/opencode（LIVE 生产版）

- **`arc-opencode-plugin/`**（开源仓）= 最小接入样板：`AGENTS.md` + `tool/arc.ts`（4 工具）+ `plugins/guardrails.ts`（1 护栏），`package.json` 声明 peer dep `@opencode-ai/plugin`，靠环境变量 `ARC_ROOT`/`ARC_PYTHON` 找到 researchclaw 的 Python。**它是"如何把 ARC 接进 OpenCode"的教科书**。
- **`famou_scientist/assets/opencode/`**（LIVE）= 生产扩展版，自包含、不依赖外部 researchclaw：
  - `tool/arc.ts`：**11 个工具**（下表）
  - `plugins/`：**4 个**（guardrails / heartbeat / cleanup / language）
  - `skill/`：**40 个** SKILL.md（domain 9 / experiment 24 / tooling 4 / writing 3）
  - `scripts/`：**17 个纯 stdlib Python 内核**（零三方依赖，工具壳通过子进程调用）

### 2.3 11 个真执行工具（`tool/arc.ts`）

| 工具 | 作用 |
|---|---|
| `search_literature` | 检索真实文献（OpenAlex / Semantic Scholar / arXiv，摘要截断省 token） |
| `run_experiment` | 跑实验（沙箱 AST 安检；`is_async` → 后台 detached job，秒回 job_id） |
| `experiment_status` / `cancel_experiment` | 查/杀异步实验（读 `.famou_jobs/<id>/status.json`；killpg 整进程组） |
| `verify_citation` / `verify_paper` | 引用核验（存在性：arxiv id / DOI / crossref；防幻觉引用） |
| `fetch_source` | 抓引用来源正文（做"引用真支撑论点吗"的支撑性核验） |
| `render_figure` | 出 matplotlib 图 + figure lint（禁彩虹色系、小字号等硬检查） |
| `generate_schematic` | 调图像模型出架构/方法示意图 |
| `fetch_latex_template` / `latex_check` | 取 venue 官方 LaTeX 模板 / 编译前查断裂 \ref、缺图、overfull |

工具壳（TS）本身不含逻辑，都是 `spawnSync(ARC_PYTHON, ["-c", code], {cwd: scripts})` 调对应 Python 内核。

### 2.4 强制护栏 hook（`plugins/guardrails.ts`，硬约束的核心）

机制：注册 `tool.execute.after`，在工具输出返回给 agent **之前**改写 `output.output`——把警告插到最前面，agent 无法忽略。这是"科研诚信"的兜底闸门：

- **实验质量门**：`run_experiment` 结果全 0 / 超时 / 崩了 → 强制标注"不得用可疑数据写论文"。
- **引用核验门**：`verify_paper` 发现幻觉/可疑引用 → 强制"删除或替换，绝不进终稿"。
- **数字核验门**：写 `paper.md`/`.tex` 时比对 `results.json`，无依据的数字强制警告。
- **图规范门 / LaTeX 编译门**：图不合规、tex 编不过 → 拦下。

另外 3 个插件：`heartbeat.ts`（异步 job 完成主动通知）、`cleanup.ts`（退出时优雅收尾 job）、`language.ts`（压缩上下文时强化中文输出）。

### 2.5 launcher 如何把资产接上 OpenCode（`launcher.py`）

`famou_scientist/launcher.py` 的 `build_env()` 构造环境变量后 `os.execvpe("opencode", ...)` 进程替换：

| 环境变量 | 值 | 作用 |
|---|---|---|
| `OPENCODE_CONFIG_DIR` | `assets/opencode/` | OpenCode 从这里加载 tool/plugin/skill/AGENTS.md |
| `ARC_ROOT` | 同上 | TS 工具壳据此定位 `scripts/` |
| `ARC_PYTHON` | 当前解释器 | 保证 Python 版本一致 |
| `XDG_DATA_HOME` | `=FAMOU_DATA_DIR`（可选） | 会话库存储位置隔离 |
| `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS` | `1` | 只用我们 40 个 skill，屏蔽用户 `~/.claude` |

> 设计要点：**不改 cwd**。资产在安装包里，用户的科研产物 `research-runs/` 落在用户当前目录，两套坐标系解耦。

---

## 3. 开源核心 researchclaw（引擎，了解即可）

`researchclaw/` 是一套**确定性的 23 阶段科研流水线状态机**（选题→文献→假设→实验设计→执行→分析→写作→评审→定稿导出，含质量门与 PIVOT/REFINE 回退）。工程同学重点了解它的分层：

- **引擎**：`pipeline/runner.py`（主状态机 + 检查点 + HITL 阻塞）、`pipeline/stages.py`（阶段枚举/门控）、`pipeline/contracts.py`（每阶段输入输出契约）、`pipeline/stage_impls/`（各阶段实现）。
- **LLM 抽象**：`llm/client.py`（OpenAI 兼容，stdlib）、`llm/acp_client.py`（**ACP = Agent Client Protocol**，可跑在任意 ACP 兼容 agent 上，不锁 provider）、`llm/anthropic_adapter.py`。
- **能力子包**：`literature/`（多源检索 + 4 层引用核验）、`experiment/`（sandbox/docker/ssh 执行 + 自愈修复 + 多领域执行器）、`domains/`（领域自动路由：HEP/生物/化学/ML/统计…）、`hitl/`（人在环，6 种介入模式）、`evolution.py`+`evolution_aevolve.py`（跨 run 经验沉淀）、`knowledge/`+`memory/`（跨 run 知识/上下文）、`skills/`（builtin 方法论）、`mcp/`+`server/`+`web/`（MCP 服务 / Web 后端 / 网络检索）。
- 入口：`cli.py`（`researchclaw run/serve/wizard/...`）、`run.sh`（后台运行 + 日志 + 凭证）。

> LIVE 产品把其中真正需要"跑"的内核（检索/沙箱/核验/figure lint/latex check）**抽成 17 个 stdlib 脚本**放进插件资产，不再拉整个 researchclaw 依赖。

---

## 4. famou-scientist 产品层（我们实际部署/维护的）

入口 `cmdline.py`，`pyproject.toml` 注册 `famou-scientist = famou_scientist.cmdline:main`。

### 4.1 CLI 子命令

| 子命令 | 作用 | 关键文件 |
|---|---|---|
| `famou-scientist`（裸） | 体检 → 交互菜单 → 起 OpenCode TUI | `doctor.py`/`intro.py`/`launcher.py` |
| `web` | 起 **Web 研究台**（opencode serve 后端 + 零构建前端） | `web.py`, `assets/web/` |
| `serve` | 只起 opencode serve（HTTP/SSE 后端） | `launcher.py` |
| `trace [SID]` | 只读导出会话轨迹/token 花费（不锁库） | `vis/trace.py` |
| `doctor` / `update` | 体检 / 一键 git pull 更新 | `doctor.py` / `updater.py` |

### 4.2 Web 研究台（`web.py` + `assets/web/`）

- **零构建**：`server.mjs` 是纯 Node dev server——静态托管 `public/`，浏览器端用 Babel 现场编译 `src/app.tsx`，React/react-markdown 经 **server 做 CDN 镜像**（锁网环境浏览器直连不了 esm.sh，由 server 代取）。**不需要 npm build**。
- **数据流**：浏览器(`:4096`) → `server.mjs`（`/oc`→反代 opencode serve `:4097`；`/raw`→读 `research-runs/` 产物字节；`/paper`/`/_esm`→CDN 镜像/经 egress 代理）→ opencode 后端。
- **前端 `app.tsx`**（单文件 React）：多会话对话 + SSE 流式渲染 + 右侧产物区（Workspace 目录树 + 一键打包下载）+ 左侧知识库（收藏文献 + 上传文档）+ 资产（有产物的会话按会话分区）+ 模型选择 + KaTeX 数学。

## 5. 数据存储与网络（部署会问）

| 数据 | 位置 | 盘 | 说明 |
|---|---|---|---|
| 对话历史（opencode.db） | `$XDG_DATA_HOME/opencode/opencode.db`（默认 `~/.local/share/opencode/opencode.db`） | 本地盘 | 高频写，CFS 上 sqlite 锁不可靠 → 建议本地盘 |
| 科研产物（research-runs） | 启动目录下 `research-runs/` 或 `.famou/workspaces/<session>/research-runs/` | 本地盘/CFS | 大文件、留档、可跨机 |
| 知识库上传 | `knowledge-base/`（PROJECT_ROOT 下） | — | 用户上传文档，全局 |
| 异步实验 job | `.famou_jobs/<job_id>/` | — | code.py / status.json / results.json / .done |

网络：Web `:4096`、opencode `:4097` 默认绑 `127.0.0.1`（内网）。远程用户经**跳板机 SSH -L 端口转发**到本机 localhost 访问；opencode 后端永不对外暴露。

---

## 6. 与工程合作的对接面（建议重点讨论）

1. **接入范式已定型**：任何新科研能力 = 加一个 `tool/*.ts`（TS 壳）+ 一个 `scripts/*.py`（stdlib 内核），或加一个 `skill/*/SKILL.md`（方法论）。**零改 OpenCode、零改 researchclaw**，横向扩展。
2. **免 SSH 外部访问**：当前依赖 SSH 隧道；要做"公网点链接即用"需要网络入站层（公司统一网关 / frp），属工程侧。
3. **质量护栏是产品护城河**：造假/幻觉/不合规的硬拦截都在 `plugins/guardrails.ts`，扩能力时新增门类往这里加。
