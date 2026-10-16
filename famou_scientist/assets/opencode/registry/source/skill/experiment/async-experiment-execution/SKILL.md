---
name: async-experiment-execution
description: Local sandbox async execution discipline for small or medium experiments launched with arc_run_experiment(is_async=true). Do NOT use for formal cluster experiments, GPU training, long simulations, or batch evaluation; load cluster-experiment-execution and submit via arc_cluster_job instead. Use this only for local smoke tests, dry-runs, or short background checks, and check arc_experiment_status at natural breakpoints — never busy-poll.
metadata:
  category: experiment
  trigger-keywords: "local async,local background,sandbox async,本地异步,本地后台,smoke test,dry-run,迷你实验,跑通性验证,短实验,arc_run_experiment,arc_experiment_status,arc_cancel_experiment,non-blocking local"
  applicable-stages: "11,12,13"
  priority: "1"
  version: "1.0"
  author: researchclaw
---

## 何时用这个 skill

这个 skill 只用于**本地 sandbox 异步执行**：秒级到分钟级 smoke test、dry-run、迷你实验、脚本跑通性验证。

**正式实验不要用这个 skill。** 一旦进入训练、批量评测、GPU 任务、长时间 simulation、大规模数据处理、多 seed/ablation/grid 等正式实验阶段，必须改用 `cluster-experiment-execution`，并通过 `arc_cluster_job(action="submit")` 提交到集群。

本 skill 的定位是：当你仍在本地快速验证代码能否启动时，使用 `arc_run_experiment(is_async=true)` 避免阻塞；但它不是正式实验调度方案。

> 底层支持：`arc_run_experiment(is_async=true)` 把本地实验丢进 detached 后台进程、
> 立即返回 `job_id`；`arc_experiment_status(job_id)` 确定性读结果信号文件。

---

## 1. 分流：同步还是异步？

| 预估耗时 / 类型 | 怎么调 |
|----------------|--------|
| 秒级 smoke test、跑通性验证、debug 小片段 | `arc_run_experiment(code, is_async=false)`（默认，同步，等它返回）|
| 本地短后台检查、迷你实验、dry-run | `arc_run_experiment(code, is_async=true, timeout_sec=<够用的硬上限>)` |
| 正式训练、批量评测、GPU/长仿真、大数据处理 | **不要用本 skill；load `cluster-experiment-execution` 并用 `arc_cluster_job(action="submit")`** |

如果只是本地验证且拿不准是否会超过几十秒，可以用本地异步；如果已经是正式训练/评测/仿真，则不要在这里犹豫，直接转 `cluster-experiment-execution` 走集群。

**`timeout_sec` 要留冗余，别卡着估**：超时是**硬 kill**（到点直接杀进程、未保存的进度丢失），
所以宁可高估。规则：**先估一个实付耗时，再 ×2 当 timeout**——估 1h 就设 `timeout_sec=7200`，
估 20min 就设 1200s。先 load `resource-planning` 拿耗时估算，再按 ×2 留余量。
（别无脑设几万秒：太大的 timeout 会让一个真挂死/死循环的任务白占资源到上限才被杀。）

> **多分片在一个 job 里串行跑时**，`timeout_sec` 要按 **分片数 × 单分片实付 × 2** 估，**别按单分片估**
> （踩坑实例：3 seeds 顺序跑一个 job 只给了 1800s，单 seed 评估就要 ~600s+，3 个串行必然超时被硬 kill、白跑）。
> 但更优解是按「§4 并行优先」**把分片拆成多个并行 job**——每个 job 只需单分片的 timeout，既快又不易超时。
> 一句话：**超时往往是「本该并行却串行」的副作用**，优先拆并行，其次才是把 timeout 按分片数放大。

## 2. 启动后立即被解放——但别启动依赖结果的步骤

异步启动会立刻返回 `{job_id, state:"running", job_dir}`。拿到后你就自由了，**可以**：
- 继续和用户对话、回答问题、调整后续计划；
- 写论文里**不依赖本次结果**的部分（Intro、Related Work、Method 描述）；
- 准备/启动**下一个**独立实验（见并发上限）。

但**绝对不要**在 `state` 变成 `done` 之前做这些依赖结果的事：
- 分析结果、写 Results/Discussion、登记 `results.json`；
- load `research-decision` / `research-reflection` 做 PROCEED/REFINE/PIVOT 判定。

结果还没出来就分析 = 编数据，直接违反真实性优先。

## 3. 心跳纪律：声明监控策略，在自然断点查，**绝不 busy-poll**

OpenCode 没有"实验跑完主动通知你"的原生机制，但本插件装了一个 **heartbeat 通知 plugin**，会**主动叫醒你**两类时机：
- **完成通知**：后台实验跑完（done/failed）时自动注入一条通知，叫你去查结果——所以你启动异步实验后**可以安心做别的，不必盯着**。
- **进度播报**：实验**运行期间**，heartbeat 会按 `progress_policy_json` 或 timeout 自适应策略注入进度（已跑多久 / 占超时上限 / `runner.log` 最新几行 / 有无新输出），前端展示在「进程」面板。
  收到运行中进度时，**不要据此分析/写结果，也不要为了这条进度单独回复用户**——实验还没结束。

启动异步实验时，尽量声明监控策略，而不是让 heartbeat 固定间隔猜：

```json
{
  "mode": "adaptive",
  "milestones": [0.25, 0.5, 0.75, 0.9],
  "log_milestones": ["epoch", "validation", "final evaluation", "saving checkpoint"],
  "quiet_alert_sec": 3600,
  "min_interval_sec": 900,
  "max_interval_sec": 3600
}
```

调用时把它序列化为字符串传给 `progress_policy_json`。选择规则：
- **知道实验阶段**（epoch/validation/final evaluation/保存 checkpoint）→ 写 `log_milestones`，这比纯时间更有意义；
- **不知道阶段** → 至少写时间 `milestones`，常用 `[0.25,0.5,0.75,0.9]`；
- **短实验** → `min_interval_sec`/`max_interval_sec` 小一些，或 `mode:"off"` 关闭运行期进度；
- **长实验/日志稀疏实验** → `max_interval_sec` 设 30-60min，`quiet_alert_sec` 设 30-60min，用于发现可能卡住；
- **完成/失败通知**不受进度策略影响，永远优先。

在此之上，你仍应在**自然断点**主动查一次作为双保险，但**查的方式有纪律**——反复轮询是公认的烧 token 反面教材（有 agent 一次对话里把同一个
状态读了 15+ 次，纯浪费）：

- ✅ **收到心跳通知** → 直接 `arc_experiment_status(job_id)` 取结果，进入分析 / 自愈。
- ✅ **在自然断点查一次**：用户下次发消息时、你刚做完一段别的子任务后——顺手查一下。
- ✅ `running` → **就停手别再查**，回去继续做别的或等用户/等心跳；不要立刻再查第二次。
- ❌ **不要**写"循环里每隔几秒查一次"这种 busy-poll，也不要 `running` 后马上重复查。

一句话：**完成有心跳叫你，平时是"路过看一眼"，绝不是"守在锅边盯"**。

## 4. 并行优先：能拆就拆，省墙钟（设计/执行实验时默认先问这句）

异步解决了"不卡死对话"，但还有第二个浪费：**一个实验内部本来能并行的维度，被写成单进程 for 循环串行跑**。
典型反例——`run_full.py` 把 3 seeds × 5 conditions 写成一层层 for 循环顺着跑，1.5~2 小时，
而 GPU 利用率才 24%。这不是"异步"能救的，异步只是把这坨串行丢到后台；**墙钟该砍的没砍**。

所以**写实验代码 / 决定怎么跑之前，默认先问一句**：

> **「这个实验的哪些维度是互相独立的？」**

独立维度 = **可并行轴**。常见的可并行轴：
- **seed**（每个随机种子各跑各的，互不依赖）
- **condition / ablation**（每个对照条件独立训练评估）
- **超参网格点**（grid search 每个点独立）
- **数据集分片 / 多数据集**（各分片各算各的）
- **baseline 方法**（每个 baseline 各自独立训练，互不影响）

只要这些维度独立，**就不该串行 for 循环跑完，而应拆成多个 `is_async` job 并行提交**。

### 决策：拆，还是不拆？

| 判据 | 结论 |
|------|------|
| 有可并行轴（seed/condition/grid/分片/baseline 独立）**且** 单分片资源 × 并发数 ≤ 可用资源 | **拆**：每分片一个 `arc_run_experiment(is_async=true)`，并发提交 |
| 有可并行轴 但 资源只够 1 个（显存/核数拉满） | 不拆，串行或排队（资源是硬约束，见下节） |
| 分片间有依赖（early-stopping 共享、贝叶斯调参靠上一轮、课程学习分阶段） | **不能拆**这条轴（依赖轴串行，独立轴仍可拆） |
| 分片太小（每片秒级~十几秒），启动/调度开销 > 收益 | 不值得拆，合在一个 job 里串行更省事 |

**先 load `resource-planning`** 估单个分片的显存/算力/时长，再 ×并发数对照用户可用资源——这一步定"能拆几个"。

### 怎么拆：参数化 + 结果隔离 + 合并（三步，第二步最容易翻车）

1. **参数化分片脚本**：把"全量单脚本"改成**按 seed/condition 接参数**的脚本（`--seed`、`--condition`），
   每个 `arc_run_experiment` 传不同参数 → 各起一个 detached job，自动落在各自 `job_dir`，**天然不冲突**。
2. **结果隔离（关键，否则互相覆盖）**：每个分片**写各自的结果文件**——`results_seed0.json`、
   `results_cond_A.json`…**绝不能让多个并行 job 都写同一个 `experiment/results.json`**：它们会并发覆盖，
   最后只剩最后一个写的、前面全丢且**无报错**（静默数据损坏）。文件名用分片参数拼，保证唯一。
3. **全部 done 后合并**：等**所有**分片 job 都 `done`，再把 `results_*.json` 合并成总
   `experiment/results.json`（可信数字注册表）。合并是确定性的"读 N 个小文件 → 按 condition/seed 归并 → 写一个"，
   **放进冒烟测试覆盖**（迷你跑 2 个分片，验证合并出的结构符合 `design.md` 实现契约的 schema）。

### 资源纪律（承接下一节「并发上限」）

- **并发数怎么定**：`并发数 ≈ min( 可用显存 / 单分片显存, 可用 GPU 数, 默认上限 2~3 )`，取最小。
  CPU 密集型（如 UKF 评估、纯 CPU 仿真）则 `并发数 ≈ min( 物理核数 / 单分片线程数, 默认上限 )`。
- **CPU 密集并行务必限每进程线程数**：多进程并行时若每个进程都默认开满线程，会**线程超订**（总线程 ≫ 核数）
  互相抢核反而更慢。给每个 job 设 `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `OPENBLAS_NUM_THREADS`
  （≈ 核数 / 并发数），让各进程吃不重叠的核。
- 具体上限、多 job 资源叠加对照，见下一节 **§5 并发上限**——本节负责"该拆"，下节负责"别拆爆"。

### 和心跳纪律的衔接（§3 仍然适用）

- 并行多 job → **各有各的 `job_id`**：完成通知、进度播报**照常按 job 逐个来**；
  收到某个 job 的运行中进度时不要单独回复用户，前端会在「进程」面板展示；别据此分析。
- 查状态仍守 §3 纪律：**自然断点查、`running` 就停手、绝不 busy-poll**。
- **但分析的时机变了**：必须**等所有分片都 `done`** 再合并、再进入分析 / 研究决策。
  少数分片还在 `running` 就先合并 = 拿不完整数据下结论，违反真实性优先。
  个别分片 `failed/timed_out` → 按自愈只补**那一个**分片重跑，不必整批重来。

> 一句话：**异步是"别卡死"，并行是"别磨蹭"**。独立维度默认拆成多 job 并跑、各写各的结果文件、
> 全 done 再合并——墙钟从"3×5 串行"砍到"≈单分片时长 × 批次"，GPU 也不再只用两成。

## 5. 并发上限：别把机器打爆

可以同时挂多个异步实验（各自 `job_id`），但：
- 默认**并发 ≤ 2~3 个**；
- 先 load `resource-planning` 估每个 job 的显存/算力，**多个 job 的资源占用要叠加**对照
  用户可用资源——别同时起 4 个训练把 GPU 显存挤爆导致全部 OOM。

## 6. 失败与超时仍走自愈

异步进程**自带硬超时**（`timeout_sec`）。当 `arc_experiment_status` 返回
`state:"failed"` 或 `timed_out:true`：
- 仍按 AGENTS.md 第 6 步的**自愈循环**处理：load `experiment-repair` 拿诊断 checklist
  → 改代码 → 重跑（A/B 节奏最多 3 次，C 节奏第一次失败即停问用户）。
- 重跑同样用异步（长任务）。

## 7. 防冷启动：让"超时"不等于"全丢"（重要）

超时是硬 kill，但被杀**不该让下一次从零开始**。注意：**不要求**实验一定有 checkpoint
机制——很多代码、很多任务本来就没有。真正要强调的是**两件低成本的事**，写实验代码时就做进去：

1. **定期打印进度 + 核心指标（边跑边输出，别憋到最后）**：
   - **进度**：epoch/step（如 `epoch 3/10`、`step 1200/5000`）、已处理样本数、阶段里程碑、耗时。
   - **核心指标**：当前 loss / 主指标（acc/F1/…）、学习率等——**用 `metric: value` 格式**打印
     （如 `train_loss: 0.41`），既人能读，也能被 sandbox 的 metrics 解析器抓到。
   - **要定期打**（每个 epoch / 每 N 步打一行），别只在结尾打一次——中途没有输出，进度播报和
     超时排查都看不到"跑到哪了"。
   - 这些进 `runner.log`，有两个直接回报：
     - **喂进度播报**：heartbeat 会按 `progress_policy_json` / 自适应策略把 `runner.log` 尾部送到「进程」面板（§3），打了进度+指标，
       用户就能实时看到"epoch 几了、loss 多少"；闷头不打，播报就只剩"已跑 X 分钟、无新输出"。
     - **超时/卡死可判**：`arc_experiment_status` 的 `log_tail` 能看到最后跑到哪，区分"timeout 真不够"
       还是"卡死"，也为下次估时长提供依据。阶段性 `metric: value` 在超时前也能被解析到。

2. **保留必要中间产物（落盘到持久路径）**：
   - 已下好的数据、预处理结果、已算完的特征/embedding、阶段性输出，**写到磁盘**
     （如 `experiment/data/`、`experiment/cache/`，或 job 的 `work/`）。
   - 这样重跑时**先检查产物是否已存在、存在就跳过重算**（下数据/预处理这种最值得，
     往往占大头）——把"冷启动"降级成"接着上次跑"。
   - 有 checkpoint 机制的（如训练）当然更好：定期存权重 + 重跑时 resume；没有也没关系，
     上面两条已经能避免大部分重复劳动。

> 一句话：写实验代码时就**多打日志、把算好的东西落盘**。这样即便 timeout 被腰斩，
> 下次也是"接着跑"而不是"推倒重来"——成本极低，回报很大。

## 8. 真实性不破防（重要）

异步**不是绕过护栏的后门**：
- 结果只认 `arc_experiment_status` 报 `done` 时返回的真实 metrics / `result.json`；
  论文数字仍只能来自 `experiment/results.json`，**数字核验门 hook 照旧拦编造**。
- **实验质量门 hook 会在 `arc_experiment_status` 报 done/failed 时自动触发**
  （全 0 metric / 无 metric / 失败 → 强制警告），和同步执行享受同一道护栏。
- 别因为"实验在后台跑、我没盯着"就脑补一个 metric 填进去——必须等真结果。

## 9. 取消后台实验 + 退出清理（要知道）

异步实验跑在一个 **detached 进程组**里，技术上能脱离 opencode 独立存活。围绕它的生命周期有两件事要知道：

**(a) 退出时默认会清理（防孤儿泄漏）**

opencode 退出（Ctrl+C / 正常退出）时，cleanup 插件会**自动 killpg 所有仍 running 的后台实验**，
把状态落成 `cancelled`，不留吃 GPU/CPU 的孤儿进程。这是面向普通用户的安全默认——退出即清干净。

- **逃生阀**：想让长实验"关了 TUI 也继续跑过夜"的，启动 opencode 前设环境变量
  `export ARC_KEEP_JOBS_ON_EXIT=1`，退出时就**不**清理、后台 job 继续。这恢复 async 的原始语义，按需开启。
- 注：硬 `kill -9` opencode（SIGKILL）无法被任何钩子捕获，那种极端情况仍可能留下孤儿——用 `arc_cancel_experiment` 或手动 killpg 收尾。

**(b) 运行期间主动取消某个 job**

实验跑岔了 / 不再需要 / 要腾 GPU 时，不必等退出，直接停某一个：

```
arc_cancel_experiment(job_id)
```

- 读 job 的 `status.json` 拿 runner pid，**killpg 整个进程组**：runner + 真正跑实验的子进程 +
  它派生的 DataLoader/multiprocessing worker 一并终止，不留孤儿；随后把状态落成 `cancelled`。
- 之后 `arc_experiment_status(job_id)` 会显示 `state: cancelled`；已 done/failed 的 job 取消是无操作。
- **何时主动取消**：实验跑岔了（代码/方向错了，code-review 没拦住的）/ 不再需要这个 condition /
  要腾 GPU 给新实验 / 用户说"别跑了"。
- ⚠️ 取消是**不可逆**的硬终止，会丢掉未落盘的中间进度。先确认这个 job 确实不要了再取消；
  只想看进度用 `arc_experiment_status`，别用取消。

---

## 产物落盘

异步 job 的中间产物落在 `job_dir`（默认 `.famou_jobs/<job_id>/`）：
`status.json`（状态）、`result.json`（真实结果）、`runner.log`（运行日志）、`work/`（沙箱工作区）。
确认结果可信后，把真实 metrics 整理进 `experiment/results.json`（可信数字注册表）——
后续论文所有数字都从这里取。

> 一句话：长实验一律后台异步跑，你边跑边陪用户做别的；在自然断点瞄一眼状态，
> 结果出来再分析。既不卡死对话，也不烧 token 空转，更不破真实性护栏。
