# Hyra Benchmark / Result 汇总

> 核验日期：2026-08-10。  
> 主要来源：Hyra 官方页 <https://hy.tencent.com/research/hyra>；官方结果仓库 <https://github.com/Tencent-Hunyuan/Hyra-results>。  
> 重要口径：Hyra-results 不是一个统一 benchmark suite。它是 Hyra 在 AI4AI、AI4Science 和 AI4Fun 上发布的一组结果 artifact。官方 README 的比较方式是：每一行拿对应任务的 best prior published result 或公开 leaderboard 结果作为 `Prev best`，再报告 Hyra 的数值。不同任务使用各自指标，没有统一总分。

## 1. 总体评测口径

Hyra 官方结果仓库说明：

- 每一行比较 `Prev best` 和 `Hyra`。
- `Prev best` 来自论文、公开 leaderboard、公开 repo 或任务内定义的 baseline。
- 指标方向由箭头标明：`down` 表示越低越好，`up` 表示越高越好。
- 指标按各 benchmark 自己定义，不做跨任务归一化。
- 官方表注明结果状态截至 2026-07-10；部分任务在持续更新的公开榜单上，后续可能已有新结果。
- `AI4Fun` 是创意和游戏 demo，官方明确写为 no leaderboard comparison。

因此，Hyra 更适合作为“跨领域研究/工程任务结果集合”来读，而不是严格意义上的统一 hidden-evaluator benchmark。

## 2. Track 总览

| Track | 数量 | 类型 | 是否有统一排行榜 | 说明 |
|---|---:|---|---|---|
| AI4AI | 3 | 自动 AI 研究、训练加速、GPU kernel 优化 | 否，各任务沿用对应公开 benchmark / baseline | 主要对比 Recursive 的自动 AI 研究结果 |
| AI4Science | 9 | 数学、组合优化、几何 packing、药物 docking、量子 routing、符号预测 | 否，各任务使用各自来源 | 大多对比 TTT-Discover、SimpleTES、AdderBoard、Packing Center 或任务 baseline |
| AI4Fun | 4 | 游戏、音乐、3D 生成 demo | 否 | 无 leaderboard comparison，只发布 artifact |

## 3. AI4AI

| Task | 任务/Benchmark | 指标 | 方向 | Prev best | Hyra | 硬件 / 环境要求 | 主要出处 / 榜单 |
|---|---|---:|---|---:|---:|---|---|
| `nanochat_autoresearch` | 固定 5 分钟预算训练小语言模型，目标是更低 validation bits-per-byte | val BPB | down | 0.9109 | 0.9015 | 记录结果在 `1x NVIDIA B200`；README 写明需要 `1x NVIDIA B200` 或兼容 CUDA 环境，约 `169 GB` 可用显存；Python 3.12、PyTorch 2.9.1 CUDA 13.0、compute capability 10.0；固定训练预算 300 s | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4AI/nanochat_autoresearch>；Recursive: <https://www.recursive.com/articles/first-steps-toward-automated-ai-research>；Recursive artifacts: <https://github.com/recursive-org/first-steps-toward-automated-ai-research>；Karpathy autoresearch: <https://github.com/karpathy/autoresearch> |
| `nanogpt_speedrun` | nanoGPT speedrun，小模型训练到目标 validation loss 的用时 | wall-clock | down | 77.5 s | 76.4 s | 记录结果是同一台 `8x NVIDIA H100` 机器上的 3 次独立 run；Python 3.12、PyTorch 2.10.0 CUDA 12.8、Triton 3.6.0、FlashAttention 3、NVIDIA driver 580.159.04；默认脚本启动 3 轮 8 进程训练 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4AI/nanogpt_speedrun>；Recursive: <https://www.recursive.com/articles/first-steps-toward-automated-ai-research>；Recursive artifacts: <https://github.com/recursive-org/first-steps-toward-automated-ai-research>；相关公开 speedrun 入口：<https://github.com/KellerJordan/modded-nanogpt> |
| `sol_execbench` | SOL-ExecBench，GPU kernel 优化接近 hardware speed-of-light | score | up | 0.754 | 0.771 | SOL-ExecBench 的官方目标硬件是 NVIDIA B200；官方评测在 B200 上运行，SM clocks 锁到 1500 MHz；需要 Docker + NVIDIA Container Toolkit、Hugging Face CLI、NVIDIA driver 580+。Hyra 子目录发布 10 个 showcase kernel JSON，未在该 README 里单独声明本地搜索资源 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4AI/sol_execbench>；SOL-ExecBench paper: <https://www.microsoft.com/en-us/research/publication/sol-execbench-speed-of-light-benchmarking-for-real-world-gpu-kernels-against-hardware-limits/>；SOL-ExecBench repo: <https://github.com/NVIDIA/SOL-ExecBench>；SOL-ExecBench leaderboard: <https://research.nvidia.com/benchmarks/sol-execbench/leaderboard/collection/1/B200>；Recursive: <https://www.recursive.com/articles/first-steps-toward-automated-ai-research> |

### AI4AI 细节

- `nanochat_autoresearch` 的 Hyra 子目录记录了单 B200 结果：validation BPB 为 `0.901543`，训练时间约 300.1 s，总时间约 348.4 s，训练 3,410 steps，训练 token 约 447.0M。
- `nanogpt_speedrun` 的 Hyra 子目录记录三次 8×H100 run，平均训练时间 `76.435 s`，平均 validation loss `3.28007`。
- `sol_execbench` 的 Hyra 子目录发布了 10 个 showcase kernel 的 JSON 结果，官方总表用整体 score `0.771` 与 Recursive 的 `0.754` 对比。

### AI4AI 硬件注意点

- `nanochat_autoresearch` 和 `nanogpt_speedrun` 是强硬件相关的 wall-clock / fixed-budget 任务。显存、GPU 型号、GPU clocks、driver、CUDA/PyTorch/Triton 版本、编译缓存和机器负载都会影响可复现性。
- `nanochat_autoresearch` 的约 `169 GB` 显存来自 Hyra 记录 run 的 peak GPU memory，低显存 GPU 即使能运行兼容代码，也不应直接和官方数值比较。
- `nanogpt_speedrun` 默认脚本会跑 3 次完整 8 GPU 训练并聚合结果；单次 smoke test 或减少 step 的结果不能作为 scored result。
- `sol_execbench` 的 official score 与硬件 SOL bound 绑定，跨 GPU 代际不可直接比较。B200 collection 的 leaderboard 才是同硬件口径。

## 4. AI4Science

| Task | 领域/问题 | 指标 | 方向 | Prev best | Hyra | 主要出处 / 榜单 |
|---|---|---:|---|---:|---:|---|
| `autocorrelation_first` | 第一自卷积/自相关常数最小化 | `C1` | down | 1.502870 | 1.502850 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/autocorrelation_first>；TTT-Discover: <https://arxiv.org/abs/2601.16175> |
| `autocorrelation_second` | 第二自相关比率最大化 | `R` | up | 0.962694 | 0.962901 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/autocorrelation_second>；SimpleTES: <https://arxiv.org/abs/2604.19341> |
| `erdos_min_overlap` | Erdos minimum-overlap 常数 | `C5` | down | 0.380868 | 0.380859 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/erdos_min_overlap>；SimpleTES: <https://arxiv.org/abs/2604.19341> |
| `sums_diffs` | sum-vs-difference 集合构造 | `C(A)` | up | 1.14489 | 1.21079 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/sums_diffs>；SimpleTES: <https://arxiv.org/abs/2604.19341>；Hyra 后续证明仓库：<https://github.com/Tencent-Hunyuan/sum-diff-proof> |
| `packing_records` | 几何 shape-in-shape packing 记录 | records broken | up | n/a | 100 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/packing_records>；Erich Friedman's Packing Center: <https://erich-friedman.github.io/packing/> |
| `smallest_adder` | 能做 10 位整数加法的最小 transformer | params | down | 36 | 15 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/smallest_adder>；AdderBoard leaderboard: <https://github.com/anadim/AdderBoard> |
| `parp1_docking` | PARP1 inhibitor docking / 分子设计 | objective | down | -9.77 | -10.60 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/parp1_docking>；baseline 是已批准 PARP1 inhibitor Olaparib；无统一公开 leaderboard |
| `qubit_routing` | 量子线路 routing，减少额外 CNOT | CNOTs added | down | 269,037 | 258,369 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/qubit_routing>；SimpleTES: <https://arxiv.org/abs/2604.19341> |
| `sunspot_symbolic` | 太阳黑子时间序列符号预测 | forecast R2 | up | 0.47 | 0.78 | Hyra task: <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Science/sunspot_symbolic>；baseline 是 copy-last-frame / persistence forecast；无统一公开 leaderboard |

### AI4Science 指标说明

- `C1`：第一自卷积/自相关常数，`max(f*f)/(int f)^2`，越低越好。
- `R`：第二自相关比率，`||f*f||_2^2 / (||f*f||_1 * ||f*f||_infty)`，越高越好。
- `C5`：Erdos minimum-overlap 常数，越低越好。
- `C(A)`：`log(|A+A|/|A|) / log(|A-A|/|A|)`，越高越好。
- `params`：在至少 0.99 accuracy 下完成两个 10 位整数加法的 transformer 唯一可训练参数数，越低越好。
- `objective`：PARP1 docking objective，`Vina score + 10 * (1 - QED)`，越低越好。
- `CNOTs added`：SWAP routing 额外插入的 CNOT 数；1 个 SWAP 计 3 个 CNOT，越低越好。
- `forecast R2`：monthly sunspot number 的 rolling-origin free-running 24-month forecast R2，越高越好。

## 5. AI4Fun

官方 README 对 AI4Fun 的口径是 creative and game-playing demos，no leaderboard comparison。

| Task | 类型 | 评测/对比 | Artifact |
|---|---|---|---|
| `AI4Fun/reversi` | Reversi / Othello bot | 无官方 leaderboard comparison；目标是 Botzone 8x8 arena bot | <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Fun/reversi>；Botzone: <https://www.botzone.org.cn/> |
| `AI4Fun/music` | 五声部编曲 | 无 leaderboard comparison | <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Fun/music> |
| `AI4Fun/3d_penguin` | Blender procedural 3D QQ penguin | 无 leaderboard comparison | <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Fun/3d_penguin>；Blender `bpy`: <https://docs.blender.org/api/current/bpy.html> |
| `AI4Fun/3d_hunyuan` | Blender procedural 3D Hunyuan logo orb | 无 leaderboard comparison | <https://github.com/Tencent-Hunyuan/Hyra-results/tree/main/AI4Fun/3d_hunyuan>；Blender `bpy`: <https://docs.blender.org/api/current/bpy.html> |

## 6. 读 Hyra 结果时的注意点

1. **不是统一榜单**：Hyra 没有把这些任务放进同一个 evaluator/harness，也没有跨任务 aggregate score。
2. **对比基线来源不一**：AI4AI 主要对比 Recursive；AI4Science 里有 TTT-Discover、SimpleTES、AdderBoard、Packing Center，也有 Olaparib 或 persistence forecast 这类任务 baseline。
3. **部分结果依赖硬件和环境**：例如 `nanochat_autoresearch`、`nanogpt_speedrun`、`sol_execbench` 都对 GPU 型号、驱动、CUDA/PyTorch/Triton 版本敏感。
4. **公开榜单可能继续变化**：官方 README 明确提醒，部分任务在持续更新的公开 leaderboard 上，后续结果可能 warm-start from Hyra's published solutions。
5. **科研含义强弱不同**：`packing_records`、`sums_diffs`、`smallest_adder` 更接近“可验证记录/构造”；`parp1_docking` 是 surrogate objective，不等同于湿实验验证；`AI4Fun` 主要是 artifact demo。

## 7. 快速结论

Hyra 的 benchmark/result 覆盖 16 个条目：

- 3 个 AI4AI：自动 AI 研究、训练加速、GPU kernel 优化。
- 9 个 AI4Science：数学极值、组合构造、packing、最小加法器、药物 docking、量子 routing、太阳黑子符号预测。
- 4 个 AI4Fun：Reversi、音乐、3D procedural 生成。

严格报告时建议写成：

> Hyra reports task-specific improvements over prior published or leaderboard results across AI4AI and AI4Science tasks, plus AI4Fun artifacts without leaderboard comparison. These are heterogeneous result artifacts rather than a single unified benchmark suite.
