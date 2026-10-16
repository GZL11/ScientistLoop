科学写作与自主发现智能体
===

一个做科研的 AI 智能体，两种用法共享同一套执行内核与质量护栏。

科学写作 —— 人在环内
---

从一个想法到一篇稿子，四段流水线：**深度文献调研 → 提假设 → 真跑实验 → 成稿**。
以插件形式挂在 [OpenCode](https://opencode.ai) 上，由它负责对话、规划与决策，
本仓库提供**方法论 skill**（怎么做研究）、**真执行 tool**（文献检索 / 实验执行 /
引用核验 / 图表生成 / LaTeX 排版）和**强制质量护栏 hook**。

护栏是 hook 不是提示词，智能体跳不过：**没有真实检索结果不许写综述，没有真实运行
产物不许写结论，每条引用都要能核回原文**。终端 TUI 与网页研究台两套界面，
关键节点等人确认。

自主发现 —— 闭环
---

给定一个任务契约，让智能体自己循环：**提方案 → 写实现 → 封闭评测 → 把结果写回**，
在固定预算内反复迭代，不需要人介入。已接入 NatureBench、SciModelingBench、
terminal-bench 及 terminal-bench-science 四套基准。

两条贯穿始终的设计约束：

- **评测对智能体封闭。** 隐藏测试集只到评测器，任何 agent 都碰不到；分数算不算数由
  独立的有效性闸门决定，而不是由提出方案的那个 agent 说了算。
- **记录只有宿主能写。** 实验库智能体只读、宿主只写；下一轮提方案读到的是机器写下的
  事实，不是上一轮自己的叙述。

### 方案演化图

每个节点是**一个完整方案**，每条边是一次算子应用：

| 算子 | 父节点 | 做什么 |
|---|---|---|
| `innovate` | 无（指向 ROOT） | 开一条新路线，不是微调 |
| `exploit` | 恰好 1 个 | 在已有方案上只改一处，效果可归因 |
| `cross` | ≥ 2 个有分的 | 取各自起作用的部分，从头重写 |
| `ensemble` | ≥ 2 个有产物的 | 复用父节点训练好的权重而非机制 |

`cross` 让一个节点可以有多个父节点，所以搜索结构是 **DAG 而不是树**——这也是
磁盘记录存 `parents` 列表而非单个 `parent_id` 的原因。算子与父节点数不匹配的方案
宿主直接退回重提（最多 3 次），**宿主不替智能体改算子**，因为算子是一个关于来源的
声明，替它改等于伪造来源。

仓库结构
---

| 路径 | 内容 |
|---|---|
| `famou_scientist/` | Python 包：CLI、环境体检、更新器、网页研究台 |
| `famou_scientist/loop/` | **闭环运行时**：agents / runtime / storage / execution / evaluation / harness / prompts，以及四套基准的接入（`examples/`） |
| `famou_scientist/assets/opencode/` | 写作侧资产：skill、tool、plugin、提示词注册表（含版本与变更日志） |
| `famou_scientist/assets/web/` | 网页研究台前端与服务端 |
| `docs/` | 设计文档、架构说明、运维手册、基准调研与接入指南、论文插图源码 |
| `integrations/`、`benchmark/` | ResearchClawBench 接入 |
| `knowledge-base/` | 领域资料（Evolve / LLM / RL / VL / VLA） |
| `handoff/`、`famou-demo-handoff/` | 前端与适配层交接文档 |
| `overleaf_upload/` | 论文 LaTeX 稿件分节源文件 |

文档从 `docs/README.md` 进，建议顺序：`overview/ARCHITECTURE.md` →
`overview/CODEBASE_WALKTHROUGH_CN.md` → `design/EVOLUTION_GRAPH_V2_CN.md`。

> 本仓库只含源码与文档。运行产物（实验库、权重、跑分记录、日志、缓存）不入库。

快速开始
---

三步即用：

```bash
# 1. 装 OpenCode（它是主体），并配好一个模型 provider
npm i -g opencode-ai
opencode auth login          # 配置你自己的模型 API（本插件不碰任何 key）

# 2. 装本插件
pip install famou-scientist
# 或（开发 / 想用 famou-scientist update 自更新）：clone 仓库后 editable 安装
#   git clone https://github.com/GZL11/ScientistLoop.git && cd ScientistLoop
#   pip install -e .           # editable：之后 `famou-scientist update`(git pull) 即时生效，无需重装

# 3. 启动研究台
famou-scientist              # 体检 → 初始菜单 → 进入研究台
```

> **更新**：editable（`pip install -e .`）装法下，`famou-scientist update` 会帮你
> `git pull` 拉最新代码、即时生效（`--check` 只查不拉、`-y` 免确认）——首次仍需按上面
> clone+editable 装好，此后就不必手动 pull 了。纯 `pip install` 装的则用 `pip install -U famou-scientist`。

启动后先看到一个 **Famou-Scientist 初始菜单**（交互式终端下）：**方向键 ↑/↓ 选择**、回车确认、`q`/ESC 退出，
四个选项竖排——

- **开始新研究**：进入 TUI 对话，从零开一个研究。
- **继续历史会话**：列出本地会话库里的历史会话（按最近更新，可选），选中直接回到那次对话。
- **Web 研究台**：起网页界面（等价 `famou-scientist web`，详见下文）。
- **退出**。

> 想跳过菜单直达对话（脚本/老手）：`famou-scientist --no-intro`（或设 `FAMOU_NO_INTRO=1`）；
> 带任何透传参数（如 `--model`）也会自动跳过菜单。

选「开始新研究」后直接自然语言对话，例如：

```
> 帮我研究"dropout 对小数据集过拟合的影响"
  → 智能体自己查文献、提假设、设计实验、写代码、真跑、分析、写论文，每个关键节点问你

> 搜一下 transformer attention 的相关论文
  → 调 arc_search_literature 拿真实论文（不是编的）
```

其它命令：

```bash
famou-scientist web          # 起网页研究台（边对话边看产物；详见下文「Web 研究台」）
famou-scientist --no-intro   # 跳过初始菜单，直达 TUI 对话（FAMOU_NO_INTRO=1 同效）
famou-scientist doctor       # 只体检（检查 opencode / python3 / 模型配置），不启动
famou-scientist update       # 一键更新到最新代码（git pull；--check 只查不拉、-y 免确认）
famou-scientist --version    # 版本
famou-scientist --model openai-compatible/claude-sonnet-4-6   # 透传参数给 opencode
famou-scientist trace        # 列出最近会话；trace <session_id> 把该会话完整轨迹导成 JSONL（只读，便于复盘/调试，详见 docs/operations/TRAJECTORY_OBSERVABILITY.md）
famou-scientist trace --web   # 起本地网页可视化轨迹：搜 session_id 看完整时间线（深色终端风，默认 127.0.0.1:8765）
```

> **网络受限环境**：OpenCode 启动时会联网拉取 [models.dev](https://models.dev) 的模型目录。
> 若你的机器需走代理才能访问外网，启动前先导出代理变量，否则会卡在 `Failed to fetch
> models.dev` 超时：
>
> ```bash
> export ALL_PROXY=http://<用户名>:<密码>@<代理主机>:<端口>   # 换成你自己的代理凭证，切勿提交
> export https_proxy=$ALL_PROXY http_proxy=$ALL_PROXY
> famou-scientist
> ```

配置模型（两种方式，二选一）
---

本工具**不管理任何 API key**——模型 provider 由 OpenCode 自己配置，凭证存在你本机、不进任何文件库。
OpenCode 有两条配置路线，按你用的模型来源选：

### 方式 A：官方 provider —— `opencode auth login`

如果你直接用 Anthropic / OpenAI / Google 等**官方服务**，用交互式登录最省事：

```bash
opencode auth login          # 选一家 provider（这就是你看到的"选公司"），填官方 key 或走 OAuth
```

凭证会存到 `~/.config/opencode/auth.json`（OpenCode 自己管理）。启动后用 `provider/model` 指定模型，例如 `anthropic/claude-sonnet-4-6`。

### 方式 B：自建网关 / 内部 router —— 写配置文件

如果你用的是**公司内部 router / 统一网关**（如 litellm、one-api，或任何 OpenAI 兼容接口），它不在 `auth login` 的"公司列表"里——**不要用 auth login**，而是在全局配置文件里声明一个 `openai-compatible` provider：

编辑 `~/.config/opencode/opencode.jsonc`：

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai-compatible": {                          // provider id，自己起名
      "npm": "@ai-sdk/openai-compatible",           // 用 OpenAI 兼容协议对接
      "name": "My Router",
      "options": {
        "baseURL": "http://<你的网关地址>/v1",        // 你的 router 地址
        "apiKey": "<你的 key>"                        // 直接写这里
      },
      "models": {                                    // 网关后面挂的模型，按需列
        // limit.context 建议写上：自定义网关在 models.dev 里查不到上下文上限，
        // 漏写会让 OpenCode 的「自动 compact」不触发、长会话上下文撑爆后模型吐空白。
        // 取模型真实窗口的保守值即可（多数 ~20 万）。忘了也没关系——famou 启动时会自动补默认值。
        "claude-sonnet-4-6": { "name": "claude-sonnet-4-6", "limit": { "context": 200000, "output": 32000 } },
        "deepseek-v3":       { "name": "deepseek-v3",       "limit": { "context": 128000, "output": 8000 } }
      }
    }
  }
}
```

启动后用 `provider-id/model-key` 指定模型，例如本例的 `openai-compatible/claude-sonnet-4-6`。

> **关于 `limit`（重要）**：自定义/内部网关的 provider 不在 models.dev 目录里，OpenCode 无从得知模型上下文上限。
> 若模型定义漏写 `limit.context`，自动 compact（到上限约 90% 自动压缩历史）就**永不触发**，长会话会一路涨到被网关硬拒、
> 模型逐轮返回空白。为防这点，`famou-scientist` 启动时会**自动检测并给缺失的模型回填一个安全默认**
> （`context: 200000`，原配置先备份为 `opencode.jsonc.bak`），你也可以照上面手动写好、或之后自行调整。

> **怎么选**：用官方服务 → A；用公司内部网关 → B。两者可共存（config 里多个 provider）。
> 配好后跑 `famou-scientist doctor`，"模型配置"一项会显示 ✅。

它能做什么
---

| 能力 | 形态 | 说明 |
|------|------|------|
| 文献检索 | tool | 真查 OpenAlex / Semantic Scholar / arXiv，防 LLM 编论文 |
| 实验执行 | tool | sandbox 真跑 Python 代码出真 metrics，防编造结果；长任务支持后台异步执行（`is_async`）+ 查状态，不阻塞对话 |
| 引用核验 | tool | 真查 arXiv/CrossRef/OpenAlex 确认引用存在，防幻觉引用；并可抓被引文献摘要做 claim 级审计（引用是否真支撑论点）|
| 科研绘图 | tool + skill | 渲染绘图代码出图 + 出版规范确定性体检（DPI/画布/字号/废弃 colormap/坐标轴），配视觉反馈闭环（渲染→真看图→批判→改）画出又规范又好看的图；统计图与概念/架构示意图都管 |
| 假设构建 / 实验设计 / 科学写作 / 统计报告…… | skill | 34 个方法论 skill，OpenCode 按需 load 自己执行 |
| 实验质量门 / 引用核验门 / 论文数字核验门 / 图版核验门 / skill 加载门 | hook | 确定性强制护栏：可疑数据/引用/违规图自动警告；该 load 方法论 skill 没 load 也会强制提醒 |

**真实性优先**：文献、实验、引用一律走真执行 tool 拿真数据；论文里的数字会被确定性
核验门比对实验真值，编造的数字进不了论文。

工作产物
---

研究过程的所有产物落盘到你**当前工作目录**下的 `research-runs/<主题>/`：

```
research-runs/<主题>/
├── planning/        # 文献综述、假设、实验设计
├── experiment/      # 实验代码、数据、结果（results.json 是可信数字注册表）
└── deliverables/    # 论文（.md/.tex）、参考文献、评审意见、引用核验报告
```

轨迹查询与可视化（trace）
---

研究跑完想复盘"智能体每一步到底干了啥"？OpenCode 把每次会话存在本地 SQLite（`opencode.db`），
`famou-scientist trace` **只读**它，把一个会话的完整轨迹（user/assistant 对话、工具调用的真实
入参/结果、skill 何时被 load、改了哪些文件）按时间序取出来——**CLI 导 JSONL** 或 **网页可视化**两种看法。

```bash
# 命令行：先列会话找 session_id，再导出该会话完整轨迹（JSONL，可配 jq）
famou-scientist trace                       # 列出最近会话
famou-scientist trace <session_id>          # 导出完整轨迹 → stdout（支持 id 前缀）
famou-scientist trace <session_id> --include-children   # 连同 subagent 子会话
famou-scientist trace <session_id> --out run.jsonl      # 写文件

# 网页：搜 session_id 看可视化时间线（深色终端风，纯本地、只读、离线可用）
famou-scientist trace --web                 # 起服务并开浏览器（默认 http://127.0.0.1:8765）
```

- **只读、不打扰**：只读 `opencode.db`（能读 WAL），opencode 正在跑时也能边跑边看，不影响它。
- **零依赖**：纯 Python stdlib + 单文件前端（无 npm/CDN/框架）。代码在 `famou_scientist/vis/`。
- 用 `jq` 一行就能看"load 了哪些 skill / 各工具入参结果 / 谁最慢"等。完整用法、页面布局、设计原理见
  **[docs/operations/TRAJECTORY_OBSERVABILITY.md](docs/operations/TRAJECTORY_OBSERVABILITY.md)**。

Web 研究台（famou-scientist web）
---

不想用终端 TUI、想要个**网页界面边对话边看研究产物**？一条命令起 Web 研究台：

```bash
famou-scientist web
# → 起后端 opencode serve(内部 :4097) + 前端(对外 :4096)，自动打开浏览器 http://localhost:4096
```

**前置条件**：和 TUI 一样要先装好 `opencode` + 配好模型（见上文「配置模型」）；另外需本机有 `node`
（opencode 本身也依赖它，通常已具备）。模型**无需在网页里选**——前端自动读取 opencode 配置里的
默认模型（`/config` 的 `model`），左下角会显示当前模型名。

### 页面长什么样（三栏）

- **左栏 · 会话**：`＋ 新对话` 开一个新研究；多个研究纵向切换，后台还在推进的会话有 busy 圆点；可删除。
- **中栏 · 聊天**：输入研究主题/指令，实时看智能体的**工具调用卡片**（load skill、`arc_search_literature`、
  `arc_run_experiment`…）、思考过程折叠块、流式回复。Enter 发送、Shift+Enter 换行。
- **右栏 · 本次科研**：**7 阶段轨迹**（文献→假设→设计→代码→结果→论文→核验，产物文件出现即点亮、
  可点开看）＋ 本 run 的 `research-runs/<主题>/` 文件树与内容预览。

### 参数

```bash
famou-scientist web --port 8080      # 前端对外端口（默认 4096）
famou-scientist web --oc-port 4099   # 后端 opencode serve 内部端口（默认 4097）
famou-scientist web --host 0.0.0.0   # 前端绑定地址（默认 127.0.0.1 仅本机；会话含对话内容，对外需谨慎）
famou-scientist web --no-open        # 不自动打开浏览器
famou-scientist web --no-auto-port   # 端口被占用时直接报错退出（默认会自动避让，见下）
```

> **端口被占用怎么办**（同机/同节点多人，尤其容器 `--network host` 时常见）：默认**自动避让**——
> 交互式终端会**先问你**（回车=用自动挑的空闲端口 / 直接输一个端口号 / `q` 退出），
> 非交互（脚本/headless）则静默换到空闲端口并打印用了哪对端口。想撞了就报错退出用 `--no-auto-port`。
> 避让换端口的目的是**各起各的、不串到别人的后端和会话**。

### 两种用法

- **纯本地**（浏览器和服务在同一台机器）：直接 `famou-scientist web`，会自动弹出本地浏览器，不用任何转发。
- **跳板机 / 远程服务器**：在服务器上 `famou-scientist web`（服务器无 GUI，自动开浏览器会静默跳过），
  把本地端口转发到服务器的 `4096`，在**本地浏览器**打开转发的口即可。端口特意这么设计：前端占对外
  `4096`（你通常已转发的口），后端退到内部 `4097`（无需转发），前端把 `/oc` 代理过去。

### 它怎么工作（要点）

- **后端**：`opencode serve` 注入和 TUI 同一套资产环境（`OPENCODE_CONFIG_DIR`/`ARC_ROOT`/`ARC_PYTHON`），
  所以网页里跑的研究与 `famou-scientist`（TUI）能力完全一致——一样 load skill、调 tool、过 hook。
  `research-runs/` 落在你**启动命令时的当前工作目录**。
- **前端零构建**：浏览器经 import map + Babel 在浏览器内转译 React，无需 `npm install`；依赖经本机
  `server.mjs` 的 **CDN 镜像**加载（`/_esm`→esm.sh、`/_unpkg`→unpkg，回源 + 落盘缓存），**浏览器只连
  localhost**——所以跳板机/本地浏览器拉不到 esm.sh 也能用，联网需求落在**运行命令的那台机器**
  （它本来就要连模型/文献；首屏拉一次后缓存，重载秒开）。
- 完整用法、架构、模型/端口/缓存配置点见 **[famou_scientist/assets/web/README.md](famou_scientist/assets/web/README.md)**。

> 只想要后端 HTTP/SSE 接口（自己接前端/脚本）？用 `famou-scientist serve`（`--port`/`--hostname`
> 透传给 opencode），它注入同一套资产环境但不起前端。`famou-scientist web` 就是在它之上多起一个网页前端。

测试
---

```bash
pip install -e .[test]
pytest
```

如何贡献
---

贡献 patch 流程及质量要求见 iCode 仓库。改动 plugin 资产（`famou_scientist/assets/`）后，
注意 OpenCode 的配置不热重载——需重启 `famou-scientist` 才生效。

版本信息
---
本项目的各版本信息和变更历史可以在[这里][changelog]查看。

维护者
---
### owners
* gezengle(gezengle@users.noreply.github.com)

### committers
* gezengle(gezengle@users.noreply.github.com)

讨论
---
百度Hi交流群：群号


[changelog]: https://github.com/GZL11/ScientistLoop/blob/master:CHANGELOG.md
