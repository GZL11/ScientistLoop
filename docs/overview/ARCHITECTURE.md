# famou-scientist 架构与运行逻辑

> 代码库：文件页：baidu/acg-fm/famou-scientist  *master
> 一份面向开发者/使用者的整体说明：famou-scientist 是什么、启动后发生了什么、
> 提供了哪些能力、一次研究是怎么跑完的。配套阅读：根目录 `README.md`（快速上手）、
> `assets/opencode/AGENTS.md`（给 agent 的流程指令）。

---

## 1. 一句话定位

**famou-scientist 不是一个独立的 agent，而是 [OpenCode](https://opencode.ai) 的一个"科研能力插件"。**

- **主体（master agent）是 OpenCode**：负责对话、规划、决策、调度。
- **famou-scientist 是能力库**：给 OpenCode 注入三类东西 —— 方法论 **skill**、真执行 **tool**、强制护栏 **hook**。
- **非侵入**：不改 OpenCode 一行代码，只通过"配置目录 + 资产文件"把能力挂上去。

```
┌────────────────────────────────────────────────────────────┐
│                      用户（自然语言对话）                       │
└───────────────────────────┬────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────┐
│  OpenCode（master agent：对话 / 规划 / 决策 / 调度 / LLM 后端） │
│                                                              │
│  按 AGENTS.md 编排研究流程，按需 ↓ 调用 famou-scientist 能力    │
└───┬───────────────────┬───────────────────┬─────────────────┘
    │ load              │ call              │ 自动触发(跳不过)
┌───▼──────┐      ┌──────▼───────┐    ┌──────▼──────────┐
│ skill ×34 │      │  tool ×7      │    │  hook ×5         │
│ 方法论    │      │  真执行       │    │  强制护栏        │
│(纯 md)    │      │ (调 py 内核)  │    │ (调 py 校验)     │
└──────────┘      └──────┬───────┘    └──────┬──────────┘
                        │                    │
                  ┌─────▼────────────────────▼─────┐
                  │  scripts/*.py 自包含内核(纯stdlib)│
                  │  检索栈 / sandbox / 引用&数字核验  │
                  └─────────────────────────────────┘
```

**设计哲学**：
- **真实性优先**：文献、实验结果、引用一律走"真执行 tool"拿真数据，杜绝 LLM 编造。
- **代码校验 → 硬 hook；方法论判断 → 软 skill**：能确定性校验的（引用是否存在、数字是否有依据）做成 hook 强制触发；需要思考判断的（怎么设计实验、怎么写作）做成 skill 供 agent 主动 load。

---

## 2. 启动链路：`famou-scientist` 命令做了什么

入口 `famou_scientist.cmdline:main`（pyproject 注册的 console script），三步：

```
famou-scientist [args]
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│ ① doctor.check()  —— 启动前体检 (famou_scientist/doctor.py) │
│    硬性: opencode 在 PATH 吗？(缺则退出)                     │
│    软性: python3 ≥ 3.10？ / ~/.config/opencode 配了 provider？│
└─────────────────────────────────────────────────────────┘
      │ 通过
      ▼
┌─────────────────────────────────────────────────────────┐
│ ② launcher.build_env()  —— 注入环境变量 (launcher.py)       │
│    OPENCODE_CONFIG_DIR = <pkg>/assets/opencode             │
│        → OpenCode 从这里加载 opencode.json / AGENTS.md /    │
│          skill / tool / plugin                             │
│    ARC_ROOT   = 同上 (tool/hook 据此定位 scripts/ 内核)      │
│    ARC_PYTHON = sys.executable (跑实验/内核脚本的解释器)      │
│    OPENCODE_DISABLE_CLAUDE_CODE_SKILLS = 1 (屏蔽用户 ~/.claude│
│        里的 skill，只用本插件 34 个，避免干扰研究流程)         │
└─────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│ ③ os.execvpe("opencode", args, env)  —— 进程替换            │
│    当前 python 进程被 opencode 接管，用户进入 TUI 对话         │
│    (doctor 子命令则只跑 ① 然后退出，不启动 TUI)              │
└─────────────────────────────────────────────────────────┘
```

**关键点：配置是"合并"不是"替换"。** `OPENCODE_CONFIG_DIR` 指向 assets 目录，但 OpenCode
仍会合并全局 `~/.config/opencode/opencode.jsonc`（用户配 provider/key 的地方）。
所以：**assets 提供"研究能力"（instructions+skill+tool+hook），全局配置提供"模型 provider"，
两者互补** —— 这也是 famou-scientist "不碰任何 key" 的实现基础。

`assets/opencode/opencode.json` 内容极简，只声明加载哪些资产：
```json
{ "instructions": ["AGENTS.md"], "skills": { "paths": ["skill"] } }
```
（tool/ 和 plugins/ 目录被 OpenCode 按约定自动扫描，无需在此声明。）

> **关于 "Python ≥ 3.10" 的说明**：这是 doctor 的**软性推荐下限**，不是硬性依赖——
> 低于它只 warning、不阻断启动。实际上内核脚本（`scripts/*.py`）**没有用任何 3.10+ 专属语法**：
> 11/11 个文件都带 `from __future__ import annotations`（类型注解是惰性字符串），
> 无 match-case、无运行时 `X|Y` union、无 `dataclass(slots=)`，技术上更低版本也能跑。
> 取 3.10 只是个保守合理的"维护中的现代 Python"基线（3.9 及以下已近 EOL），
> 并与 `pyproject.toml` 的 `requires-python = ">=3.10"` 对齐。`doctor` 检测的 python
> 就是将来 `ARC_PYTHON`（跑实验/内核脚本的解释器），所以建议在该 Python 环境里装齐实验依赖。

---

## 3. 三层能力详解

### 3.1 真执行 tool（核心，`assets/opencode/tool/arc.ts`）

OpenCode 把 `tool/arc.ts` 里 export 的每个工具注册为 `arc_<导出名>`。多数 tool 通过
`spawnSync(ARC_PYTHON, ["-c", code])` 同步调用 `scripts/` 下的自包含 Python 内核（纯 stdlib，
无第三方运行依赖）；`arc_run_experiment` 另有 detached 后台异步模式，`arc_experiment_status`
则纯 Node `fs` 读信号文件、不起 python。

| Tool（OpenCode 中的名字） | 作用 | 调用的内核 |
|---------------------------|------|-----------|
| `arc_search_literature(query, limit)` | 多源检索真实论文（OpenAlex + Semantic Scholar + arXiv），返回标题/作者/年份/摘要/DOI | `search.py` → `openalex_client.py` / `semantic_scholar.py` / `arxiv_client.py` |
| `arc_run_experiment(code, timeout_sec, is_async)` | 在 sandbox 真实执行 Python 实验代码（AST 安全校验后跑）。`is_async=false` 同步返回 returncode/metrics/stdout/stderr；`is_async=true` 用 detached 进程后台跑、立即返回 `job_id` 不阻塞 master | `sandbox.py`（同步）/ `async_runner.py`（异步） |
| `arc_experiment_status(job_id)` | 查异步实验状态：确定性读 job 目录 `status.json`/`result.json`/`runner.log`，返回 running/done/failed + 真实 metrics（纯 fs，零 LLM） | （无，Node fs 直读） |
| `arc_cluster_job(action, ...)` | 正式集群实验入口：训练、批量评测、GPU 长任务、大规模仿真必须走 `fm-job-new run --no-wait`。支持 resource / submit / list / logs / pod_ip / kill，并在 submit 前做数据真实性 preflight | `fm-job` |
| `arc_verify_citation(title, arxiv_id, doi)` | 核验**单条**引用是否真实存在（arXiv/CrossRef/DataCite/OpenAlex） | `verify.py` |
| `arc_verify_paper(bib_text)` | 核验**整篇** BibTeX，返回 verified/suspicious/hallucinated 计数 | `verify.py` |
| `arc_fetch_source(title, arxiv_id, doi)` | 抓被引文献**摘要**做 claim 级审计（引用是否真支撑论点），复用文献检索多源 client | `source_text.py` → `search.py` |
| `arc_render_figure(code, out_path, kind, journal)` | 渲染绘图代码到图片 + 出版规范**确定性体检**（DPI/画布宽/字号/废弃 colormap/坐标轴标签/矢量导出），返回 image_path + lint。配 `scientific-visualization` 视觉反馈闭环；与 run_experiment 区别：出图+体检，不解析 metrics | `figure_lint.py` |

### 3.2 强制护栏 hook ×5（`assets/opencode/plugins/guardrails.ts`）

挂在 OpenCode 的 **`tool.execute.after`** 事件上 —— 工具执行完**必然触发**，agent 跳不过。
hook 可改写工具返回值，向 agent 注入强制警告。

| 护栏 | 触发时机 | 逻辑 |
|------|---------|------|
| ① **实验质量门** | `arc_run_experiment`（同步）之后，**或** `arc_experiment_status` 报 done/failed（异步）之后 | returncode≠0 / 超时 / 无 metric / metric 全 0 → 注入警告"结果不可信，不得用于论文"。同步异步共用同一判据（`experimentQualityWarnings`），异步路径不会绕过 |
| ② **引用核验门** | `arc_verify_paper` 之后 | hallucinated>0 或 suspicious>0 → 注入警告"必须删除/替换编造引用" |
| ③ **论文数字核验门** | `write`/`edit` 写入 `deliverables/paper.md` 或 `*.tex` 之后 | 调 `verify_paper_cli.py`，把论文 Results 段数字与 `experiment/results.json` 比对（容差 1%），出现无实验依据的数字（severity=REJECT）→ 注入警告"必须从 results.json 取真值" |
| ④ **图版核验门** | `arc_render_figure` 之后 | `figure_lint.py` 体检出 `severity=FAIL`（硬规范违规：jet/rainbow colormap、字号不可读等）→ 注入警告"图存在硬违规，不得用于论文，必须修复重渲染"。WARN/advisory 由工具内联返回、留给 agent 判断，只对 FAIL 硬拦 |
| ⑤ **skill 加载门** | 写 `hypotheses.md`/`design.md`/`experiment.py`/`paper.md`(`.tex`)，或调 `arc_run_experiment`/`arc_render_figure`/`arc_verify_paper` 之后 | 靠观测内置 `skill` 工具调用做**会话级跟踪**；该动作前未 load 对应方法论 skill（`hypothesis-formulation`/`experimental-design`/`code-plan-review`/`scientific-writing`/`scientific-visualization`/`citation-faithfulness`）→ 注入警告"先 load 拿方法论再做"。把"按阶段 load skill"从软指令变成确定性兜底 |

护栏 ③ 通过论文文件路径自动反推同一 run 的 `experiment/results.json`（不依赖插件目录，
因为 run 目录在用户工作区）。

### 3.2′ 实验心跳通知 plugin（`assets/opencode/plugins/heartbeat.ts`）

不是护栏，是**主动通知器**——解决"OpenCode 事件驱动、agent 答完即休眠、不会主动查后台异步实验"的问题。
插件 init 时常驻一个 `setInterval`（默认 60s）心跳：每拍**纯文件扫描** `.famou_jobs/*/status.json`
（零 LLM、零 token），发现某 job 变 `done/failed` 且未通知过时，用 `client.session.prompt` 往会话
注入一条中性状态通知，**叫醒空闲的 agent** 去调 `arc_experiment_status` 取结果。

纪律：① 仅 agent 空闲时注入（不打断进行中的 turn，靠 `event` hook 的 `session.idle` 判定）
② Set 去重（同一 job 只叫一次）③ 每拍至多一条 ④ 只通知 2h 内完成的（避免重开翻旧账）
⑤ 精准路由（`arc_run_experiment` 启动异步 job 时把 `sessionID` 写进 `meta.json`，通知发回发起会话）。
"叫醒能力"已实测验证：后台定时器调 `client.session.prompt` 确实能触发空闲 agent 的新一轮响应（agent 收到通知后自动 `arc_experiment_status` 取真实结果）。
心跳周期可用环境变量 `ARC_HEARTBEAT_MS` 调（默认 60000ms），调试日志可设 `ARC_HEARTBEAT_DEBUG=<文件路径>` 开启。

当前边界：heartbeat 只扫描 `.famou_jobs/`，所以只覆盖 `arc_run_experiment(is_async=true)` 的本地异步实验；
`arc_cluster_job` / `fm-job-new` 的正式集群任务尚未接入自动通知，现阶段需要 `list/logs` 查状态。

### 3.3 方法论 skill ×34（`assets/opencode/skill/`）

纯 Markdown 方法论（部分含脚本），agent 在执行某步前先 `load` 对应 skill 获取 ARC 沉淀的
领域 know-how，而非只用通用知识。分四桶：

**experiment（19 个）— 研究方法论**

| skill | 简述（做什么 / 何时 load） |
|-------|--------------------------|
| `literature-search` | 系统性文献综述方法论（检索策略/筛选/综合）——做综述、写背景时 |
| `baseline-profiling` | 精确抽取候选 baseline 的 benchmark/数据处理/训练配置，保证同基准公平对比——选 baseline、调研前作时 |
| `benchmark-selection` | 选用哪些 benchmark/数据集并获取数据，判断能否复用 baseline 已报告数字——定评估集前 |
| `hypothesis-formulation` | 从观察出发结构化生成可证伪假设（含竞争解释、实验预测） |
| `experimental-design` | 设计可复现的 ML 实验（消融/baseline/受控对比） |
| `resource-planning` | 估算每个实验的算力/显存/时长，对照用户可用资源判断能否跑——设计后、写代码前 |
| `experiment-repair` | 诊断实验为何失败（报错/超时/全 0/接近随机）并自行修复——重跑前 |
| `code-plan-review` | 跑实验前起独立 reviewer 子 agent 逐项核对代码是否忠实实现规划（数据/条件/baseline/协议/超参），防静默偏离，执行级证据 + fail-closed——写代码后、跑实验前 |
| `failure-mode-audit` | 统一诚信清单：跑前/跑后/定稿前逐项排除 7 种 AI 科研失败模式（实现 bug/幻觉引用/幻觉结果/捷径/bug 当洞见/方法学造假/frame-lock），SUSPECTED 即阻断——被 code-plan-review/research-reflection/quality-gate/peer-review 共用 |
| `async-experiment-execution` | 长实验如何后台异步跑（`is_async`）+ 心跳查状态 + 解放 master 不阻塞——跑实验前 |
| `cluster-experiment-execution` | 正式实验提交/查看/取消规范：本地只做 smoke，训练/评测/GPU/长仿真走 `arc_cluster_job` + `fm-job-new` |
| `research-decision` | 基于可信结果判 PROCEED / REFINE / PIVOT——分析→决策的岔口 |
| `research-reflection` | 写论文前对照最初假设检验结论能否支撑（SUPPORTS/PARTIAL/CONTRADICTS），不支持则归因反思并落盘 `reflection.md`——防 agent 跑偏 |
| `novelty-gate` | 提出新假设/失败后的后续方向前自检创新性（机制级差异/非重复/达 MPU），增量就深挖或如实告知——防反射式小修小补消耗用户 |
| `statistical-reporting` | 统计检验选择、假设检查与 APA 规范报告——分析结果、写 Results 时 |
| `peer-review` | 模拟顶会严格同行评审找问题，建议用独立 reviewer 子 agent 避免确认偏误——草稿写完后 |
| `citation-faithfulness` | 不止查引用真伪，更查"引用是否真支撑论点"：用 `arc_fetch_source` 抓被引摘要判 SUPPORTED/UNSUPPORTED/AMBIGUOUS（advisory，摘要级）——同行评审 + 引用核验时 |
| `quality-gate` | 论文导出前 go/no-go 终检：按阈值打分 + 逐个数字比对真实实验（反造假） |
| `systematic-review` | 遵循 PRISMA 的系统性综述方法——文献检索/筛选阶段 |
| `meta-analysis` | 跨研究/跨实验结果的统计合并方法 |

**writing（2 个）— 论文写作阶段（实验/分析/评审收尾后）**

| skill | 简述 |
|-------|------|
| `scientific-writing` | IMRAD 结构学术写作、引用格式、报告规范——起草/修订论文时 |
| `scientific-visualization` | 出版级图表：视觉反馈闭环（`arc_render_figure` 渲染→`read` 真看图→批判→改）+ 统计图与概念/架构示意图（TikZ/schematic）+ 图数据溯源 |

**domain（9 个）— 领域知识（按研究领域选）**

| skill | 简述 |
|-------|------|
| `cv-classification` | 图像分类最佳实践（CIFAR/ImageNet 等基准） |
| `cv-detection` | 目标检测最佳实践（COCO/VOC，YOLO/DETR 架构） |
| `nlp-pretraining` | 语言模型预训练与微调最佳实践 |
| `nlp-alignment` | LLM 对齐技术（RLHF/DPO/指令微调） |
| `rl-policy-optimization` | 强化学习策略优化（PPO/SAC/奖励设计） |
| `quantum-qiskit` | Qiskit 2.x 变分量子机器学习（特征映射/VQC/VQE/MPS/噪声模型） |
| `hep-phenomenology` | 高能物理唯象（BSM/暗物质/对撞机/截面与排除限） |
| `biology-biopython` | 用 Biopython 做序列操作/解析/BLAST/系统发育 |
| `chemistry-rdkit` | 用 RDKit 做分子分析/描述符/指纹/子结构搜索（SMILES/药物发现） |

**tooling（4 个）— 工程实践（写实验代码时选）**

| skill | 简述 |
|-------|------|
| `pytorch-training` | 稳健的 PyTorch 训练循环最佳实践 |
| `data-loading` | 优化数据加载流水线，避免 GPU 饥饿 |
| `mixed-precision` | FP16/BF16 混合精度，加速训练、省显存 |
| `distributed-training` | 多 GPU / PyTorch DDP 分布式训练 |

### 3.4 自包含内核 `scripts/*.py`

从 AutoResearchClaw（ARC）一次性剥离、剪断 `researchclaw` 依赖的纯 stdlib 内核：

| 子系统 | 文件 |
|--------|------|
| 文献检索栈 | `search.py`（统一检索+去重）、`openalex_client.py`、`semantic_scholar.py`、`arxiv_client.py`、`cache.py`（本地查询缓存）、`models.py`（数据模型 Paper/Author） |
| 实验执行 | `sandbox.py`（AST 安全校验 + 隔离执行 + metrics 解析）、`async_runner.py`（异步实验后台 detached runner，复用 sandbox，落 status/result/.done 信号文件） |
| 引用核验 | `verify.py`（多数据库查证引擎）、`source_text.py`（抓被引文献摘要做 claim 级审计，复用 `search.py`） |
| 论文数字核验 | `paper_verifier.py`、`verify_paper_cli.py`（hook 调用的 CLI）、`verified_registry.py`（可信数字注册表） |
| 科研绘图体检 | `figure_lint.py`（渲染绘图代码 + 自省 Figure 做出版规范确定性体检：DPI/画布宽/字号/废弃 colormap/坐标轴标签/矢量导出，图版核验门据此判 FAIL） |

---

## 4. 一次研究是怎么跑完的（研究流程）

OpenCode 按 `AGENTS.md` 编排。这是**默认骨架，可自由调整**（跳过实验只做综述、并行探索多假设等）——
agent 是主导者，不是固定流水线执行器。对应 ARC 的 23 个 Stage：

| 阶段 | Stage | 做什么 | 关键产物 / 停顿点 |
|------|-------|--------|------------------|
| **1. 理解意图** | 1-2 | 拆解主题为可研究子问题；**主动问交互节奏**；建 `research-runs/<主题>/`；`todowrite` 建任务列表 | — |
| **2. 文献综述** | 3-6 | load `literature-search`：定策略→`arc_search_literature` 搜真实文献→筛选→抽取；对候选 baseline load `baseline-profiling` 逐篇抽 benchmark/数据/超参 | `planning/literature.md`（含 baseline 配置表） |
| **3. 综合+假设** | 7-8 | 文献聚类、**指明研究空白**；load `hypothesis-formulation` 生成 3-5 个可证伪假设 | `planning/hypotheses.md` ← **关键停顿** |
| **4. 选 benchmark+备数据+设计** | 9-11 | load `benchmark-selection` 选基准、判断能否复用 baseline 数字；**问用户数据集路径**；load `experimental-design` 设计 condition/metric/检验 | `planning/design.md` ← **关键停顿** |
| **5. 资源规划+写代码** | 10-11 | load `resource-planning` 估显存/算力/时长、**问用户可用资源**、跑不动给降规模方案；load tooling skill 写 `experiment.py`；**跑前** load `code-plan-review` 起独立 reviewer 子 agent 核对代码⇄规划保真度（防数据子采样/缺条件/协议漂移）+ `failure-mode-audit` 核对 Mode 1/4/6，fail-closed | ← **关键停顿（资源）**、`experiment/code-review.md` |
| **6. 跑实验+自愈** | 12-13 | load `async-experiment-execution`：短任务 `arc_run_experiment(is_async=true)` 后台跑、立即返回 job_id；正式长任务改走 `cluster-experiment-execution` / `arc_cluster_job`；结果就绪前都不要分析。local 路径上心跳 `arc_experiment_status` 查（勿轮询）；`done` 才拿真 metrics；登记 `results.json`（**可信数字注册表**）；失败时 load `experiment-repair` 自愈（A/B 最多 3 次，C 第一次失败即停） | `experiment/results.{json,md}`、`.famou_jobs/<job_id>/` / 集群 job 产物 |
| **7. 分析+研究决策** | 14-15 | load `statistical-reporting` 分析；load `research-reflection` 对照最初假设检验结论能否支撑、不支持则归因反思落盘 `reflection.md`（+ `failure-mode-audit` 核对 Mode 1/3/5）；load `research-decision` 给 **PROCEED / REFINE / PIVOT** 三选一 | `experiment/reflection.md`；REFINE/PIVOT 重大变更 ← **关键停顿** |
| **8. 写论文+评审+质量门** | 16-20 | load `scientific-writing` 起草；出图走 `scientific-visualization` 视觉反馈闭环（`arc_render_figure` 渲染→`read` 真看图→批判→改，图版核验门拦硬违规）；load `peer-review` 起**独立 reviewer 子 agent** 找问题（+ `failure-mode-audit` 复查 7 模式）；load `quality-gate` 打分卡；数字核验门 hook 自动拦编造数字 | `deliverables/paper.md`、`deliverables/figures/`、`reviews.md` ← **关键停顿** |
| **9. 核验引用+导出** | 22-23 | 每条引用 `arc_verify_citation` 验存在性，整篇 `arc_verify_paper`；load `citation-faithfulness` 用 `arc_fetch_source` 抓摘要查支撑性；导出 `paper.md` + `paper.tex` + `references.bib` | `deliverables/{paper.tex,references.bib,citations.md}` |

> Stage 21（跨 run 进化：把本次教训存盘供未来复用）当前**不做**——需跨会话持久化，测试阶段先略过。

### 交互节奏（第 1 步必问）

| 模式 | 行为 | 适合 |
|------|------|------|
| **A 全自动** | 一口气从文献跑到论文，只在最后汇报（硬问题仍停） | 信任自主推进、想省心 |
| **B 关键节点**（默认推荐） | 在 ① 选定假设 ② 确认设计 ③ 论文初稿 三处停 | 大多数情况 |
| **C 逐步** | 每个环节都展示产物、等确认 | 全程把关 / 边看边学 |

**节奏只控制"主动征询"频率，不控制"出问题必报告"**：实验失败、引用核验不过、与假设矛盾的
反预期结果，无论哪种节奏都**一律停下如实报告**，绝不被 auto 静默。

---

## 5. 工作产物结构

famou-scientist **不改 cwd**：产物落在用户启动时所在的工作目录下的 `research-runs/<主题>/`：

```
research-runs/<主题简写>/
├── planning/                # 📋 规划
│   ├── literature.md        # 文献综述 + 真实论文列表 + baseline 配置表
│   ├── hypotheses.md        # 候选假设（可证伪，含 H0）
│   └── design.md            # 实验设计 + benchmark 选择 + 资源规划
├── experiment/              # 🧪 实验
│   ├── experiment.py        # 实验代码
│   ├── code-review.md       # 跑前代码保真审查报告（代码⇄规划核对）
│   ├── data/                # 数据集（默认下载位置）
│   ├── results.json         # 可信数字注册表（数字核验门据此查）
│   ├── results.md           # 真实 metrics + 分析
│   └── reflection.md        # 结论⇄假设复盘日志（对齐判定+归因+下一步）
└── deliverables/            # 📦 成品
    ├── paper.md / paper.tex # 论文（markdown / NeurIPS-ICML 风格 LaTeX）
    ├── references.bib       # BibTeX
    ├── reviews.md           # 同行评审意见
    └── citations.md         # 引用核验报告
```

**产物可见的双通道**：① 完整产物落盘（可翻阅、可直接改文件后让 agent 重读，等价于 ARC 的 edit gate）；
② 对话里只给要点+关键数字+文件路径，不刷屏。

---

## 6. 配置与启动

### 模型 provider（二选一，由 OpenCode 管理，本插件不碰 key）

- **方式 A 官方服务**：`opencode auth login`，凭证存 `~/.config/opencode/auth.json`
- **方式 B 自建网关/内部 router**：编辑 `~/.config/opencode/opencode.jsonc` 声明 provider
  （`@ai-sdk/openai-compatible` 或 `@ai-sdk/anthropic`），`apiKey`/`baseURL` 支持 `{env:VAR}` 占位

### 安装

```bash
npm i -g opencode-ai                 # ① 装主体 OpenCode
pip install famou-scientist          # ② 装本插件（要求 Python ≥ 3.10）
famou-scientist doctor               # ③ 体检三项
famou-scientist                      # ④ 体检通过 → 进 TUI
```

### 网络受限环境

OpenCode 启动会联网拉 `models.dev` 模型目录。需代理才能上外网的机器，启动前先：
```bash
export ALL_PROXY=http://<user>:<pass>@<host>:<port>
export https_proxy=$ALL_PROXY http_proxy=$ALL_PROXY
```
否则会卡在 `Failed to fetch models.dev` 超时。

---

## 7. 关键设计取舍速查

| 问题 | 取舍 |
|------|------|
| 为什么是插件而非独立 agent？ | 复用 OpenCode 成熟的 TUI/对话/调度/多 provider，只维护"研究能力"这部分资产，可移植到任意 OpenCode |
| skill vs tool vs hook 怎么分？ | 需思考判断 → skill（软，可选）；OpenCode 做不到的真执行 → tool（agent 主动调）；确定性校验 → hook（硬，自动触发跳不过） |
| 怎么防 LLM 编造？ | 三道真执行 tool 拿真数据 + 三道 hook 护栏（实验质量/引用真实/数字有据），`results.json` 作为全篇数字唯一可信来源 |
| 为什么不改 cwd？ | 资产在 site-packages、研究产物在用户工作区，两个坐标系解耦，用户在哪起就把成果落在哪 |
| 配置会不会冲掉用户的 provider？ | 不会，OpenCode 配置是多源**合并**：assets 出能力、全局配置出 provider |
