# 在 ResearchClawBench 上一键评测 famou-scientist

> 这个目录是一个**自包含的评测套件**。装好 famou + 自备一份 ResearchClawBench(RCB) 后，
> **一条命令**就能从「建任务 workspace → 跑 famou → 搬产物 → 打分」跑到出分。
> 接入 RCB **不需要写 Python adapter，也不需要手改 `agents.json`**——`register_famou.py` 会自动把
> 适配器脚本的绝对路径写进去（agents.json 在你本机、从不提交）。

> ⚠️ **评测内容**：RCB 的任务 prompt（`INSTRUCTIONS.md`）是一份强自包含的「全自主、直接产出
> `report/report.md`」指令，会**盖过 famou 自身的多阶段方法论流程**（peer-review / quality-gate / research-runs 等）。
> 所以**当前这套接入测的是「基线能力」——famou 的真执行工具（真跑实验/真查文献/防编造）+ 底层模型**，
> 而**不是** famou 完整研究流程的差异化能力。把它当「famou 接入 RCB 的最小可跑基线」看，并非是「famou 的真实上限」。

---

## 一、准备（三件，使用者自备；脚本只检查不代装）

### 1. 装好 famou-scientist 并配模型
按 famou 主仓库 `README.md` 装好、配好模型，确认能跑：
```bash
famou-scientist run "用一句话自我介绍"   # 能出回复 = famou + 模型 + 网络都就绪
which famou-scientist                    # 确认 famou 已装进当前环境（跑评测的解释器要能 import 它）
```
> famou 的模型/网关/代理由它自己的配置 + 环境变量提供（`~/.config/opencode/opencode.jsonc`、
> `ANTHROPIC_BASE_URL` 等）。RCB 把 famou 当子进程起、**继承你启动脚本那个 shell 的环境**，
> 所以这些在哪个 shell 里 export 过，就在哪个 shell 里跑评测。
> 最好使用 VPN，开发机不通外网

### 2. 自己 clone 并安装 ResearchClawBench
RCB 是第三方仓库（InternScience），由你自己装；本套件只需要你**告诉它 RCB 在哪**。
```bash
git clone https://github.com/InternScience/ResearchClawBench
python3 -m pip install -r ResearchClawBench/evaluation/requirements.txt
# 关键依赖：structai>=0.1.23（scorer，配 GPT-5 系列 judge）、researchharness、flask、openai
```

### 3. 配 judge（打分模型，与被测模型解耦）
凭证走环境变量**或** RCB 的 `evaluation/.env`（二选一，**别写进会提交的文件**）：
```bash
export JUDGE_API_KEY=<你的judge key>
export JUDGE_API_BASE=<judge gateway>/v1     # OpenAI 兼容端点
export JUDGE_MODEL_NAME=gpt-5.1              # 榜单官方用 gpt-5.1
```

---

## 二、一键评测

```bash
# 传入你的 RCB 路径（参数或 RCB_HOME 环境变量都行），默认跑一个快任务先验证整链
bash run_eval.sh --rcb /path/to/ResearchClawBench Astronomy_000

# 多题：
bash run_eval.sh --rcb /path/to/ResearchClawBench Astronomy_000 Chemistry_000 Physics_003
# 或：
RCB_HOME=/path/to/ResearchClawBench bash run_eval.sh Astronomy_000
```

脚本会自动：① 前置检查（famou 在 PATH、RCB 可 import、judge 配置齐全）→ ② 把 famou 注册进 RCB 的
`agents.json`（幂等；写适配器脚本 `famou_rcb.py` 的绝对路径）→ ③ 对每个任务 `setup_workspace → run → score_workspace` → ④ 打印每题分数 + 均值。

> 先用一个**快任务**（如 `Astronomy_000`/`Physics_003`，几分钟）验证整链通了，再按需扩到整榜（40 题）。
> 含训练的任务（Chemistry/Material）可能跑 ~35–40 分钟。

### 失败怎么看
- famou 没产出报告 → 适配器打印 `WARNING no report/report.md produced` 并以非 0 退出（不会静默拿 0 分）。
- judge 配置缺失 → scorer 抛明确错误（不静默 0）。
- 前置不满足 → `run_eval.sh` 直接报错并指向本节。

---

## 三、目录内容

| 文件 | 作用 |
|---|---|
| `run_eval.sh` | 一键编排：检查 → 注册 → 逐任务 setup/run/score → 出分 + 均值 |
| `famou_rcb.py` | **适配器本体**：非交互跑 famou + 把产物搬进 RCB `report/` 布局（见下） |
| `register_famou.py` | 幂等把 famou 写进 `<RCB>/evaluation/agents.json`（cmd = 用当前解释器跑本目录 `famou_rcb.py` 的绝对路径） |
| `tests/test_famou_rcb.py` | 适配器搬运逻辑单测（不真跑 famou/不调 judge） |

**适配器 = `famou_rcb.py`**（评测套件本体，随本仓库 clone，不进 pip 包——跑评测本来就得 clone 本仓库拿
`run_eval.sh`/`register_famou.py`）。它做契约弥合：非交互跑 `python -m famou_scientist run "$(cat INSTRUCTIONS.md)"`
→ 把 `research-runs/<主题>/deliverables/paper.md` 搬成 `report/report.md`、把图搬进 `report/images/`、并把
markdown 里 `figures/` 链接重写为 `images/`。`register_famou.py` 会把它的绝对路径写进 `agents.json`（本机、不提交）。

---

## 四、接入契约（为什么不是 adapter.py）

RCB 的 `evaluation/run_task.py` 对一个 agent 做三件事：搭 workspace（铺 `data/`、`related_work/`、
`INSTRUCTIONS.md`）→ 把 agent 当子进程起（`subprocess.Popen(cmd, cwd=<WORKSPACE>, shell=True)`，替换
`<WORKSPACE>`/`<PROMPT>`）→ 读 `report/report.md`（+ PNG）对**隐藏的真实论文** rubric 逐条 LLM 评分。
所以接入点是 **agents.json 里一行 CLI 命令**——Claude Code / ResearchClaw 等都这么接。

**两条路别混**：
- **路 A（famou 走这条）**：autonomous agent → `agents.json` 一行命令（即调 `famou_rcb.py`）。
- **路 B（不适用）**：`rcb-eval` + yaml 接的是 **OpenAI 兼容模型端点**，由 RCB 自带 ResearchHarness 提供 scaffold；
  famou 本身就是 scaffold，不塞进它的 scaffold 当「模型」。

| 契约要求 | famou 默认 | 适配器（`famou_rcb.py`）怎么处理 |
|---|---|---|
| 非交互、跑完退出 | `famou-scientist run` 透传成 `opencode run`，跑完即退 | 子进程跑 `python -m famou_scientist run "$(cat INSTRUCTIONS.md)"` |
| 产物在 `report/report.md`+`report/images/*.png` | 写 `research-runs/<主题>/deliverables/paper.md`+`figures/*.png` | 搬运 + 重写图链接 `figures/`→`images/`，并把所有 `*.png` 拷进 `report/images/` |

---

## 五、风险（跑真榜前盯）

1. **「问用户」停顿 vs 全自主**：famou 流程里有「关键停顿点问用户」；headless 下没人可问——RCB 的
   `INSTRUCTIONS.md` 已明令 never ask、做合理假设继续，且无 TTY 也问不了。失败模式是「提前结束、没写 report」，
   适配器会以非 0 退出 + 警告暴露，不静默。
2. **产物落点**：适配器按 `deliverables/paper.md`（兜底排除 `reviews`/`citations` 的最新 `.md`）搬运。
   真跑一题确认 `report/report.md` 真被填，否则 scorer 报「No report found」直接 0 分。
3. **模型覆盖**：可选 `FAMOU_RCB_MODEL=provider/model` 覆盖 famou 默认模型。
