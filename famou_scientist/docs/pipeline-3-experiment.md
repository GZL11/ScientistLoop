# 阶段三 · 做实验（按说明书写代码做实验）技术文档

> famou-scientist 四阶段技术文档之三。本篇讲**从实验设计到可信数字**：写实现契约 → 写代码 →
> 跑前保真审查 + 冒烟 → 异步跑 + 自愈 → 反思，产出 `experiment/results.json`（可信数字注册表）。
>
> 现在实验执行分两条线：
> - **本地/短任务**：`arc_run_experiment(is_async=true)` + `.famou_jobs/` + heartbeat 自动叫醒；
> - **正式/长任务**：`arc_cluster_job(action="submit")` → `fm-job-new run --no-wait`。
>   目前 heartbeat 只覆盖前一条线；正式集群任务的自动追踪还在补接中，现阶段要靠 `list/logs` 查状态。
>
> 配套阅读：
> - 流程编排总纲：`assets/opencode/AGENTS.md`（Stage 9-15）
> - 上游：[提出 idea](pipeline-2-ideation.md)（提供 `planning/hypotheses.md`）
> - 下游：[写论文](pipeline-4-paper-writing.md)（论文数字全部来自 results.json）
>
> 路径基准：`baidu/acg-fm/famou-scientist/famou_scientist/`。行号会漂移，**按符号名定位更稳**。

---

## 0. 一句话定位

实验阶段的核心是**真实性**：metrics 必须由真执行 tool 跑出来，不许编。
标准次序 = **写实现契约 → 写代码 → 静态保真审查（独立 reviewer）→ 同步冒烟 → 全量异步/集群 → 自愈 → 反思**。
短实验走本地 detached 异步，长实验走集群；二者都要求结果落盘后再分析。当前 heartbeat 只负责本地异步 job 的叫醒。

```
planning/hypotheses.md（用户选定的主假设）
  │ Stage 9-10  benchmark-selection / 备数据 / experimental-design（写实现契约）/ resource-planning
  ▼ planning/design.md（含逐条可勾选的「实现契约清单」）
  │ Stage 11  load tooling skill → 写 experiment/experiment.py
  │           load code-plan-review → 独立 reviewer 子 agent 对照契约逐条核对
  │           + failure-mode-audit（Mode 1/4/6）
  │           → 同步冒烟（is_async=false 迷你跑，四项全过）
  ▼ experiment/code-review.md
  │ Stage 12  短任务：arc_run_experiment(is_async=true) → detached 后台跑
  │           正式长任务：arc_cluster_job(action="submit") → fm-job-new --no-wait
  │           local 路径有 heartbeat 叫醒；cluster 路径目前用 list/logs 查状态
  │ Stage 13  失败 → experiment-repair 自愈（A/B 最多 3 次 / C 第一次就停）
  ▼ experiment/results.json（可信数字注册表）+ results.md
  │ Stage 14-15  statistical-reporting 分析 → research-reflection 对照假设
  │              → research-decision 判 PROCEED / REFINE / PIVOT
  ▼ experiment/reflection.md（按轮次累积）
```

---

## 1. 在 AGENTS.md 里的流程位置

文件：`assets/opencode/AGENTS.md`，Stage 9-15（约 138-173 行）。

| 步骤 | Stage | 做什么 | skill |
|---|---|---|---|
| 选 benchmark + 备数据 + 设计 | 9-11 | 覆盖矩阵选 benchmark、问用户数据、设计 condition/metric/检验、**写实现契约** | benchmark-selection / experimental-design / statistical-power / exploratory-data-analysis |
| 资源规划 | 10 | 估每个 condition×seed 显存/时长，问用户可用资源，跑不动给降规模方案（关键停顿点） | resource-planning |
| 写代码 | 11 | 自己写 `experiment/experiment.py` | pytorch-training / data-loading / mixed-precision / distributed-training |
| 跑前保真审查 | 11 | **独立 reviewer 子 agent** 对照契约逐条核对 + 冒烟测试（四项全过才放行） | code-plan-review + failure-mode-audit（Mode 1/4/6） |
| 跑实验 + 自愈 | 12-13 | 静态审查→同步冒烟→全量异步；短任务走本地 async，正式长任务走集群；失败按节奏自愈 | async-experiment-execution / cluster-experiment-execution / experiment-repair |
| 分析 + 决策 | 14-15 | 真实数据分析、对照假设复盘、判 PROCEED/REFINE/PIVOT | statistical-reporting / research-reflection（+ failure-mode-audit Mode 1/3/5）/ research-decision |

---

## 2. 方法论 Skill

skill 目录根：`assets/opencode/skill/`（experiment/ 与 tooling/ 子目录）。

### 2.1 experimental-design — 实验设计 + 实现契约模板
`skill/experiment/experimental-design/SKILL.md`
- **8 项最佳实践**：baselines · 随机种子 · 方差报告 · 消融 · 变量控制 · 标准划分 · 资源记录 · 定期打印进度
- **实现契约模板（核心）**：`design.md` 必须含一个逐条可勾选的「实现契约/实验清单」小节：
  - 数据（数据集名/路径/train·val·test 精确样本数/预处理/标签映射）
  - 条件 & baseline（逐个列出每个 condition、每个 baseline 及关键配置）
  - 超参（每个关键超参的具体取值）· 种子数（≥3，真随机化，取值列表）
  - 评估（主指标定义/方向/单位/切分聚合/评估协议）
  - 开跑断言（应满足的 `assert`）· 可观测性（进度条 + 周期打印 `metric: value`）
- 拿不准的标 `TBD` 停下问，**别埋在散文里**——这是下游审查/冒烟/数字核验共同的硬基准

### 2.2 statistical-power — 事前功效/样本量
`skill/experiment/statistical-power/SKILL.md`
- 四个紧锁量：样本量 / 效应量 / α / 功效（1-β），任意三个定第四个
- 效应量选择：SESOI（最防守）> 前人估计（需 shrink）> Cohen 惯例（最后用，需声明）
- 闭式公式 wrapped 在 `scripts/power.py`：`sample_size(test, effect_size, power, alpha)`、`mde(...)`；
  支持 t_ind/t_paired/anova/two_proportions/correlation/chi2/linear_regression 等

### 2.3 exploratory-data-analysis — 备数据后系统探查
`skill/experiment/exploratory-data-analysis/SKILL.md`
- 时机：数据取得后、定设计前；覆盖 200+ 科学格式（化学/生信/显微/光谱/蛋白组）
- 自动报告：结构/分布/缺失/异常/类别平衡/**数据泄漏预警**；结论回填实现契约的真实样本数

### 2.4 code-plan-review — 跑前代码保真审查（防静默偏离）
`skill/experiment/code-plan-review/SKILL.md`
- **独立 reviewer subagent**（task 工具，fresh context）：只喂代码 + design.md（含契约）+ hypotheses.md + baseline 配置表
- **保真清单 7 个高危维度**（逐条 ✅/⚠️/❌/⬜ + 指到代码行）：
  1. 数据真实性（**最高危**）：真加载完整数据集，无偷偷子采样/合成/偷梁换柱
  2. 条件/baseline 完整性：都真实实现且会真跑
  3. 指标 & 评估协议：与 baseline-profiling 对齐，无偷换协议
  4. 超参 & 种子：对齐规划，每条件 ≥2 种子
  5. 指标输出格式：sandbox 可解析（`condition=X metric: value`）
  6. 作弊/泄漏排查：无测试集泄漏、无答案写死
  7. 可观测性：进度条 + 周期进度行 + 开跑回显超参 + 首 batch sanity
- **冒烟测试（fail-closed，必做）**：迷你版（1 epoch/1-2 batch/子集）确认 ①真跑通 ②assert 不炸
  ③配置/数据量符合契约 ④指标可解析——**四项全过才允许全量异步**
- 产出 `experiment/code-review.md`（契约逐条表 + 冒烟结果 + 放行判定）；偏离/缺失/冒烟不过 → 先改对齐再跑

### 2.5 failure-mode-audit — 7 种 AI 科研失败模式
`skill/experiment/failure-mode-audit/SKILL.md`（统一诚信清单，跑前/跑后/定稿前都用）

| 模式 | 关键问句 | 关卡 |
|---|---|---|
| Mode 1 实现 bug 蒙混 | 有无可疑整齐数字/方差完全一致（常量泄漏信号） | code-plan-review 跑前 + assertion 自证 |
| Mode 2 幻觉引用 | 引用不存在/张冠李戴 | arc_verify_paper + 引用核验门 |
| Mode 3 幻觉结果 | 每个数字都能在 results.json 找到来源吗 | **数字核验门 hook 硬覆盖** |
| Mode 4 捷径依赖 | 有消融排除虚假特征吗/baseline 够强吗 | code-plan-review 标记 + peer-review 盯 |
| Mode 5 bug 当洞见 | 反预期现象有无文献支持/调试后才出现？全新环境复现过？ | research-reflection 跑后专处 |
| Mode 6 方法学造假 | Methods 每个数字能在代码/配置找到吗 | code-plan-review 跑前 + 数字核验门 |
| Mode 7 早期 frame-lock | 若回 Stage 1，会改问题/方法吗 | novelty-gate + research-decision PIVOT + quality-gate |
- **三态处置**：SUSPECTED → 阻断（用户确认/override 记录/改后重查）；定稿前曾 SUSPECTED 的必须 CLEAR 或已 override

### 2.6 async-experiment-execution — 长实验异步执行
`skill/experiment/async-experiment-execution/SKILL.md`
- **分流**：秒级 smoke 用同步；>60s 用异步，`timeout_sec` 设为估时 ×2（留冗余）
- **启动后自由**：异步立即返回 `{job_id, state:running, job_dir}`，可继续对话，**但结果未确认前不分析/写 Results**
- **心跳纪律（绝不 busy-poll）**：完成由 heartbeat 叫醒（最高优先）；运行期每 ~15min 进度播报；自然断点查一次
- **并发上限**：≤2-3 个，需 resource-planning 估叠加占用
- **防冷启动**：定期打印进度 + 核心指标（`metric: value`，每 epoch/N step）；保留中间产物（重跑跳过重算）

### 2.7 experiment-repair — 自愈
`skill/experiment/experiment-repair/SKILL.md`
- **根因分类 + 标准修法**：缺依赖→加 requirements；OOM→batch 砍半/梯度检查点；下载被拦→预缓存/小模型；
  合成数据回退→修真实加载别假装；超参→lr 降 10×/梯度裁剪；时间守卫杀条件→减条件/epoch/种子；条件雷同→检查区分参数是否真接进前向；种子不足→≥2
- **硬判据**：准确率 <15% = 没学会当失败；条件 <3 或每条件种子 <2 = 统计不足；日志现 "synthetic/random fallback" = 偷用假数据必修；同一根因连修 3 轮还复现 = 判不可修停下报告
- **修复循环**：读 stderr 归类 → 改 experiment.py 重跑 → 最多 3 次仍败按节奏底线停下报告

### 2.8 research-reflection — 跑后反思（防跑偏）
`skill/experiment/research-reflection/SKILL.md`
- **结论 ⇄ 假设对齐三态**：✅ SUPPORTS（方向+量级都兑现 → PROCEED）· 🟡 PARTIAL（方向对证据不够 → REFINE）· ❌ CONTRADICTS（相反/触发证伪 → PIVOT）
- **不支持时归因 5 类**：执行/实现 · 证据强度不足 · 基准不公平 · 指标选错 · 混淆变量 · 假设本身错（→PIVOT）
- 产出 `experiment/reflection.md`（按轮次累积）六块：假设回顾 / 实验结果 / 观察现象 / 对齐判定 / 归因反思 / 下一步规划

### 2.9 resource-planning + statistical-reporting
- `resource-planning/SKILL.md`：估每个 condition×seed 显存/GPU 时长/存储/总算力（优先类比 baseline 报告硬件），
  做表展示、问用户可用资源、判能跑/紧张/跑不动，跑不动给降规模方案
- `statistical-reporting/SKILL.md`：统计检验选择与报告规范，基于真实数据分析更新 results.md

### 2.10 tooling skill（写代码时按需 load）
`skill/tooling/` 下：`pytorch-training`（训练循环最佳实践）· `data-loading`（流水线优化）·
`mixed-precision`（混合精度）· `distributed-training`（多 GPU 分布式）。

### 2.11 cluster-experiment-execution — 正式集群实验
`skill/experiment/cluster-experiment-execution/SKILL.md`
- **适用场景**：正式训练、正式评测、长仿真、大规模数据处理、多 seed / 多 ablation / 多 baseline。
- **工具**：`arc_cluster_job(action="submit" | "list" | "logs" | "pod_ip" | "kill")`
- **底层**：`fm-job-new run --no-wait`，提交后立即返回，不阻塞对话。
- **硬规则**：本地只做 smoke / dry-run；正式任务必须走集群。
- **当前已知边界**：它和 `heartbeat.ts` 还没有打通成统一自动追踪链路，所以集群 job 目前主要靠 `list/logs` 自查，完成后再读真实产物。

---

## 3. 真执行 Tool

定义文件：`assets/opencode/tool/arc.ts`。

### 3.1 arc_run_experiment — 主实验执行（arc.ts L85-166）
- 入参：`code: string`、`timeout_sec: number`（默认 300）、`is_async: boolean`（默认 false）
- **同步模式**（L147-165）：调 `ExperimentSandbox.run()` → 超时控制 + metrics 解析 → 阻塞返回
  `{returncode, timed_out, metrics, stdout, stderr}` → 触发**实验质量门 hook**
- **异步模式**（L109-145）：
  1. 生成唯一 `job_id = job_${Date.now()}_${random}`
  2. 建 job 目录 `.famou_jobs/<job_id>/`，写 `code.py` + `meta.json`（sessionID + timeout_sec）
  3. detached 子进程拉起 `async_runner.py <job_dir> <timeout_sec>`（L126）：
     ```ts
     const child = spawn(PY, [".../async_runner.py", jobDir, String(timeoutSec)], {
       cwd: SCRIPTS, detached: true,
       stdio: ["ignore", logFd, logFd],   // 日志写 runner.log
       env: { ...process.env, ARC_PYTHON: PY },
     })
     child.unref()                         // 不等子进程，立即返回
     ```
  4. **立即返回** `{job_id, state:"running", job_dir, timeout_sec, hint}`，master 随即解放

### 3.2 arc_experiment_status — 查异步状态（arc.ts L171-234）
- 入参：`job_id`
- 确定性读信号文件：`status.json`（state: running/done/failed/cancelled）→ 终态读 `result.json`；
  running 则 tail `runner.log` 尾部 ~15 行供 heartbeat 播报
- 返回 `{job_id, state, returncode, timed_out, cancelled, metrics, stdout, stderr, elapsed_sec, pid, log_tail}`
- done/failed 时**补做实验质量门 hook**

### 3.3 arc_cancel_experiment — 主动停后台实验（arc.ts L239-356）
- 入参：`job_id`
- 读 `status.json` 拿 runner pid → **killpg 整个进程组**（负号 pid）：SIGTERM → 等 1.5s → 仍存活 SIGKILL；处理 ESRCH/EPERM
- 原子写终态：`status.json` → `cancelled`；`result.json` 不存在才补（不覆盖真实结果）；写 `.done` 哨兵

### 3.4 arc_cluster_job — 正式集群实验（fm-job-new）
- 入参：`action: resource | submit | list | logs | pod_ip | kill`
- `submit` 会包装成：
  ```bash
  fm-job run ... --no-wait -- /bin/bash -lc "<command>"
  ```
- 提交后立即返回 job 信息，适合正式训练 / 批量评测 / 长仿真。
- 这条线**不落入 `.famou_jobs/`**，也**不受本地 heartbeat 自动通知**；状态查看依赖 `list/logs`，后续若要自动叫醒，需要再接一层 cluster registry / heartbeat。

> ⚠️ 改 `arc.ts`/plugins/scripts 需**重启 opencode**（port 4097）才生效。

---

## 4. 后端执行脚本 + Job 生命周期

脚本目录：`assets/opencode/scripts/`。

### 4.1 async_runner.py — 后台 runner 入口（~121 行）
启动：`python async_runner.py <job_dir> <timeout_sec>`（arc.ts L126 拉起）。生命周期（L38-122）：
1. 校验 argv → job_dir / timeout_sec
2. 初始化 `status.json`（state=running, pid, start）
3. 读 `code.py` → 创建 `ExperimentSandbox`，调 `sb.run(code, timeout_sec, log_path=runner.log)`
4. 实时 tee stdout/stderr 到 `runner.log`（解决日志为空）
5. 结果落盘：`result.json` + `status.json`（done/failed）+ `.done` 哨兵
6. **全程 try/except 兜底**：任何失败都落终态，绝不留 running 僵尸

### 4.2 sandbox.py — 沙箱核心（~728 行）
- `SandboxConfig`（L28-43）：python_path / gpu_required / allowed_imports / max_memory_mb
- `ExperimentSandbox.run(code, timeout_sec=300, log_path=None)`（L370-429）：建临时脚本（含 AST 校验）→
  `subprocess.run(timeout=timeout_sec)` 硬超时 → 实时 tee → 解析 metrics
- `parse_metrics(stdout)`（L145-256）：三种格式 ①`SUMMARY condition=X metric=Y mean=M std=S`
  ②`condition=X metric: value` ③纯 `metric: value`；`is_metric_name()`（L60-71）过滤日志行

### 4.3 信号文件结构
```
.famou_jobs/<job_id>/
├── code.py        # 待执行的用户代码
├── meta.json      # {sessionID, created, timeout_sec}
├── status.json    # {state, pid, start, end, returncode, timed_out, cancelled, reason}
├── result.json    # {returncode, timed_out, metrics, stdout, stderr, elapsed_sec}
├── .done          # 哨兵（内容=returncode，出现即跑完，供 heartbeat 检测）
├── runner.log     # 实时日志（tee stdout/stderr）
└── work/          # ExperimentSandbox 持久工作目录（data/cache/checkpoints）
```

---

## 5. 强制 Hook + 心跳/清理 Plugin

### 5.1 实验质量门（guardrails.ts L160-192）
- 触发：arc_run_experiment 同步后（L161-174）+ arc_experiment_status 报 done/failed（L180-192）
- 判据 `experimentQualityWarnings()`（L43-59）：returncode≠0 / timed_out / metrics 空 / **所有 metric 全 0**
- 包装 `wrapQualityWarning()`（L62-69）：前缀 `⚠️ 【实验质量门 - 强制护栏】`，要求向用户说明

### 5.2 skill 加载门（本阶段相关条目，guardrails.ts L97-109、L298-318）
- 文件型：`experiment/experiment.py` → `code-plan-review`
- 工具型（L105-109）：`arc_run_experiment` → `code-plan-review`；`arc_render_figure` → `scientific-visualization`；
  `arc_verify_paper` → `citation-faithfulness`；`arc_latex_check` → `latex-fmt`
- 未 load 即写代码/调工具 → 强制警告（跟踪机制见 [ideation 文档](pipeline-2-ideation.md) §3）

### 5.3 heartbeat.ts — 进度播报 + 完成通知（~243 行）
- setInterval 心跳（`TICK_MS=60s`），纯文件扫描 `.famou_jobs/`（零 LLM/零 token）
- **完成通知**（L93-151）：扫 done/failed job → 读 meta.json 拿 sessionID **精准路由回发起会话** →
  注入 `[系统通知·实验心跳] …已完成…请调 arc_experiment_status(...)`
- **进度播报**（L154-222）：每 `PROGRESS_MS=15min`（`ARC_PROGRESS_INTERVAL_MS` 可调/设 0 关）→
  tail runner.log + 算已跑时长/占超时比 + 无新输出卡死预警 → `[系统通知·实验进度] …实验尚未结束…用一句话转达用户`
- 空闲判定（L49-84）：仅当 `session.idle > session.status` 且距今 >GRACE_MS(5s) 才安全注入，不打断进行中 turn
- 只通知 2h 内完成的 job（`MAX_DONE_AGE_MS`），启动对账补发离线期间错过的

### 5.4 cleanup.ts — 退出清理（~160 行）
- 注册 node 退出钩子；opencode 退出（Ctrl+C / exit）扫 `.famou_jobs/` 把 running job **killpg 整组**落 cancelled
- 逃生阀 `ARC_KEEP_JOBS_ON_EXIT=1` → 跳过清理（让长训练关 TUI 也续跑）
- `reapAll`（L65-128）：单次守卫 → SIGTERM→SIGKILL → 原子写 cancelled 终态（reason: `opencode-exit:${signal}`）
- 非侵入注册（L150-159）：`process.on("exit"/"SIGINT"/"SIGTERM"/"SIGHUP")`，不吞信号

### 5.5 集群实验的当前状态
- 现有 `heartbeat.ts`、`cleanup.ts`、`arc_experiment_status` 这一套只覆盖 `.famou_jobs/<job_id>/` 的本地异步实验。
- `arc_cluster_job` 的正式集群任务目前由 `fm-job-new` 管理，**没有**进入 `.famou_jobs/` 信号文件体系。
- 所以正式实验完成后，agent 现在不会被 heartbeat 自动叫醒；需要靠 `arc_cluster_job(action="list"/"logs")` 手动查，或者后续补集群追踪注册。

---

## 6. 产出文件

```
research-runs/<topic>/
├── planning/
│   ├── hypotheses.md   # 上游：用户选定的主假设
│   └── design.md       # 实验设计 —— 含「实现契约」小节（下游审查/冒烟/核验的硬基准）
├── experiment/
│   ├── experiment.py   # 核心产出：实验代码（Stage 11）
│   ├── code-review.md  # 跑前保真审查报告：契约逐条表(✅/⚠️/❌/⬜) + 整改项 + 冒烟结果 + 放行判定
│   ├── results.json    # 【可信数字注册表】论文所有数字都从这取；数字核验门据此拦造假
│   │                   # {"primary_metric":"...","results":{"<condition>":{"<metric>":值,"folds":[...]}}}
│   ├── results.md      # 真实 metrics + 结果分析
│   ├── reflection.md   # 结论⇄假设复盘（六块，按轮次累积，防死循环）
│   └── data/           # 数据集（默认下载位置）
└── .famou_jobs/        # 异步 job 目录（结构见 §4.3）
```

---

## 7. 实验执行全流程（从代码到可信数字）

```
Stage 11  写 experiment.py
  → load code-plan-review → 独立 reviewer 子 agent 对照 design.md 契约逐条核对
  → 跑前 failure-mode-audit（Mode 1/4/6）
  → 同步冒烟 arc_run_experiment(is_async=false) 迷你跑：四项全过？
      ✗ gap/bug → 回去改 experiment.py
      ✅ → 继续
Stage 12  arc_run_experiment(is_async=true) 启动全量
  → async_runner.py（detached）→ ExperimentSandbox.run（subprocess 硬超时 + tee runner.log）
  → 实验质量门 hook（metrics 检查）
  → heartbeat：运行期 ~15min 播报；跑完叫醒
  → arc_experiment_status 自然断点查（绝不轮询）；不需要了 arc_cancel_experiment 停
  → 结果 → results.json
Stage 12′ 正式长任务 / 集群实验
  → arc_cluster_job(action="submit") → fm-job-new run --no-wait
  → list/logs/pod_ip 在自然断点查；结果先落集群产物
  → 目前不走本地 heartbeat 自动叫醒，后续若接 registry 再统一通知
Stage 13  失败 → experiment-repair 自愈（A/B≤3 次 / C 第一次停）
Stage 14  statistical-reporting 分析（真实数据）→ research-reflection 对照假设 + failure-mode-audit（Mode 1/3/5）
Stage 15  research-decision 判 PROCEED / REFINE / PIVOT（A/B 在 PIVOT/REFINE 推倒重来时也必须停下问用户）
```

**铁律**：results.json 落盘后才做分析/写 Results/研究决策；数字只从 results.json 取（数字核验门防编造）。

---

## 8. 关键文件 / 行号速查

| 文件 | 行号 | 内容 |
|---|---|---|
| `AGENTS.md` | 138-173 | Stage 9-15 实验流程 |
| `tool/arc.ts` | 85-166 / 171-234 / 239-356 | run_experiment / experiment_status / cancel_experiment |
| `tool/arc.ts` | `cluster_job` | cluster_job / fm-job-new 正式集群实验 |
| `scripts/async_runner.py` | 38-122 | 后台 runner 生命周期 |
| `scripts/sandbox.py` | 363-536 / 145-256 | ExperimentSandbox / parse_metrics |
| `plugins/guardrails.ts` | 43-59 / 160-192 | 实验质量门判据 + 触发 |
| `plugins/heartbeat.ts` | 93-151 / 154-222 | 完成通知 / 进度播报 |
| `plugins/cleanup.ts` | 65-128 / 150-159 | reapAll / 退出钩子注册 |
| `skill/experiment/code-plan-review/SKILL.md` | 全文 | 保真清单 + 冒烟 |
| `skill/experiment/failure-mode-audit/SKILL.md` | 全文 | 7 种失败模式 |
| `skill/experiment/async-experiment-execution/SKILL.md` | 全文 | 异步执行纪律 |
| `skill/experiment/cluster-experiment-execution/SKILL.md` | 全文 | 正式集群实验提交、查看、取消规则 |
| `skill/experiment/experiment-repair/SKILL.md` | 全文 | 自愈 checklist + 硬判据 |
| `skill/experiment/research-reflection/SKILL.md` | 全文 | 结论⇄假设六块复盘 |
