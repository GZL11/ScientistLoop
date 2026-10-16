# 把 famou-scientist 接到 ResearchClawBench 评测

> 🚚 **已迁移**：接入逻辑（含适配器脚本 `famou_rcb.py`）现在收敛进评测套件
> **`benchmark/researchclawbench/`**（`run_eval.sh` + `register_famou.py` + README，零路径、一键到出分）。
> 新接入请直接看那个目录。本文件保留作历史参考。

> 一句话：ResearchClawBench 用**子进程**驱动自主 agent，**不需要写 Python adapter**——
> 只要在它的 `evaluation/agents.json` 里加一行命令，指向本目录的 `famou-rcb` 壳脚本即可。
> 壳脚本负责「非交互跑 famou + 把产物搬到 RCB 期望的 `report/` 布局」。

相关背景见 `docs/benchmarks/BENCHMARKS_AI4S.md`（ResearchClawBench 是我们「对外背书」的选择之一：第三方在线榜、
藏目标论文防泄漏、以 Claude Code 为基线）。

---

## 0. 端到端：从零跑通一个任务（外部接入者照这一节即可）

下面是从「只有一台能跑 famou 的机器」到「跑出一个任务的分数」的完整最短路径。
`<X>` 一律替换成你自己机器上的实际值。**所有凭证只走环境变量 / `.env`，绝不写进任何提交的文件。**

> ⚠️ **先理解你测到的是什么**：RCB 的任务 prompt（`INSTRUCTIONS.md`）是一份强自包含的「全自主、直接产出
> `report/report.md`」指令，会**盖过 famou 自身的多阶段方法论流程**（peer-review / quality-gate / research-runs 等）。
> 所以**当前这套接入测的是「基线能力」——famou 的真执行工具（真跑实验/真查文献/防编造）+ 底层模型**，
> 而**不是** famou 完整研究流程的差异化能力。把它当「famou 接入 RCB 的最小可跑基线」来看，别误读成「famou 的真实上限」。
> （要测完整流程需改接入让 prompt 走 famou 的阶段编排，见 §4/§1。）

### 步骤 1 · 先让 famou-scientist 本身能跑

按 famou 主仓库 `README.md` 装好并配好模型——确认这条能正常应答再继续：

```bash
famou-scientist run "用一句话自我介绍"     # 能出回复 = famou + 模型 + 网络都就绪
```

> famou 的模型/网关/代理全部由它自己的配置 + 环境变量提供（`~/.config/opencode/opencode.jsonc`、
> `ANTHROPIC_BASE_URL` / `ALL_PROXY` 等）。RCB 把 famou 当子进程起、**继承你启动 RCB 那个 shell 的环境**，
> 所以这些在哪个 shell 里 export 过，就在哪个 shell 里启动 RCB。

### 步骤 2 · 取 ResearchClawBench 并装评测依赖

```bash
git clone https://github.com/InternScience/ResearchClawBench
cd ResearchClawBench
python3 -m pip install -r evaluation/requirements.txt
# 关键依赖：structai>=0.1.23（scorer，配合 GPT-5 系列 judge）、researchharness、flask、openai
```

### 步骤 3 · 注册 famou（改 `evaluation/agents.json`）

在 `evaluation/agents.json` 里加一项，`cmd` 用**你机器上 famou 仓库的绝对路径**：

```json
"famou": {
  "label": "Famou-Scientist",
  "icon": "F",
  "logo": "/static/logos/researchclaw.svg",
  "cmd": "/abs/path/to/famou-scientist/integrations/researchclawbench/famou-rcb -w <WORKSPACE>"
}
```

- `<WORKSPACE>` 是 RCB 自己会替换的占位符，**原样保留、不要改**。
- 壳脚本从 `<WORKSPACE>/INSTRUCTIONS.md` 读 prompt，所以 `cmd` 里只需要 `<WORKSPACE>` 一个占位符。
- 若执行位丢了：`chmod +x integrations/researchclawbench/famou-rcb`。

### 步骤 4 · 配 judge（打分用的模型，与被测模型相互独立）

scorer 拿 famou 产出的 `report/report.md` 对**隐藏的真实论文** rubric 逐条打分，需要一个 judge 模型。
凭证走环境变量**或** `evaluation/.env`（RCB 用 `python-dotenv` 读，二选一）：

```bash
export JUDGE_API_KEY=<你的judge key>
export JUDGE_API_BASE=<judge gateway>/v1      # OpenAI 兼容端点
# JUDGE_MODEL_NAME 在 evaluation/config.py（榜单官方用 gpt-5.1）；需要改就改那里或同名环境变量
```

> judge 应与被测 agent 用的模型**解耦**（避免自评偏置）。**别把 key 写进会提交的文件**——用环境变量或
> 已被 `.gitignore` 的 `evaluation/.env`。

### 步骤 5 · 跑通一个任务并看分

先拿一个**快任务**验证整条链（Physics 类约 4 分钟；Chemistry/Material 含训练可达 ~35–38 分钟）：

```bash
# (a) 建 workspace（RCB 把任务的 data/、related_work/、INSTRUCTIONS.md 铺好）
python3 -c "from evaluation.run_task import TaskRunner; \
r=TaskRunner('Physics_003', agent_name='Famou-Scientist'); r.setup_workspace(); print(r.workspace)"
# → 打印出 <WORKSPACE> 路径，记下它

# (b) 跑 famou（壳脚本：famou 非交互跑 → 把 paper.md/图 搬进 report/）
integrations/researchclawbench/famou-rcb -w <WORKSPACE>
# 成功标志：壳脚本打印 "report/report.md OK (...bytes, N image(s))" 并 exit 0
# 失败标志：打印 "WARNING no report/report.md produced" 并 exit 1（见 §4 风险点 #1/#2）

# (c) 打分
python3 -c "from evaluation import score; print(score.score_workspace('<WORKSPACE>'))"
```

也可以用 **Web UI** 单跑（更直观）：

```bash
python3 -m evaluation.server          # flask 起服务（默认本机端口，见启动日志）
# 浏览器打开 → 选任务 → agent 选 "Famou-Scientist" → Start Run
```

批量评测用仓库自带入口 `./rcb-eval`（配 `eval_configs/` 下的 yaml）。
**注意**：批量并发跑时 `opencode run` 会**吃掉循环的 stdin**——子进程必须 `</dev/null` 隔离、manifest 用独立 FD 读，
否则后续任务不启动（见 §4 与 `EVAL_2026-06-21.md` §7）。

> 跑完一题确认 `report/report.md` 真被生成、scorer 真打出分，整条链就通了。要刷完整榜（40 题）再按需扩。

---

## 1. ResearchClawBench 的接入契约（为什么不是 adapter.py）

ResearchClawBench 的 `evaluation/run_task.py` 对一个 agent 做三件事：

1. **搭 workspace**：把任务的 `data/`、`related_work/`（只读）拷进去，建 `code/ outputs/ report/ report/images/`，
   并把完整任务 prompt 写成 `<WORKSPACE>/INSTRUCTIONS.md`（来自 `instructions_tmpl.py`：要求**全自主、不许问人、
   最终产出 `report/report.md` + `report/images/*.png`**）。
2. **把 agent 当子进程起**：`subprocess.Popen(cmd, cwd=<WORKSPACE>, shell=True)`，替换 `<PROMPT>` / `<WORKSPACE>`
   占位符，stdout 收进 `_agent_output.jsonl`。
3. **打分**：读 `<WORKSPACE>/report/report.md`（+ `report/`、`outputs/` 里的 PNG），用 `target_study/checklist.json`
   逐条对**隐藏的真实论文**做 LLM 评分。

所以接入点是 **agents.json 里一行 CLI 命令**，不是 Python adapter——Claude Code / ResearchClaw / LingTai 都是这么接的。

**两条路别混**：
- **路 A（famou 走这条）**：autonomous agent → agents.json 一行命令。
- **路 B（不适用）**：`rcb-eval` + yaml，接的是 **OpenAI 兼容模型端点**，由 RCB 自带的 **ResearchHarness** 提供 scaffold。
  famou 本身就是 scaffold，不能塞进它的 scaffold 当「模型」。

### famou 与契约的两处错位，壳脚本负责弥合

| 契约要求 | famou 默认行为 | 壳脚本怎么处理 |
|---|---|---|
| 非交互、跑完退出 | `famou-scientist run <prompt>` 透传成 `opencode run`（非交互模式），跑完即退 | 直接用 `run` 子命令 |
| 产物在 `report/report.md` + `report/images/*.png` | 写到 `research-runs/<主题>/deliverables/paper.md` + `figures/*.png` | 跑完把 `paper.md`→`report/report.md`、`figures/*.png`→`report/images/`，并把 markdown 里 `figures/` 图链接重写为 `images/` |

---

## 2. 安装

### 2.1 让 `famou-rcb` 可执行（已随仓库提交，含执行位）

```bash
chmod +x integrations/researchclawbench/famou-rcb   # 若执行位丢失
```

壳脚本**自包含**：用 `PYTHONPATH=<repo>` 调 `python3 -m famou_scientist`，所以**不要求** `famou-scientist`
在 PATH（在 PATH 时会优先用控制台脚本）。

### 2.2 在 ResearchClawBench 注册 famou

编辑 `ResearchClawBench/evaluation/agents.json`，加一项（**用你机器上的绝对路径**）：

```json
"famou": {
  "label": "Famou-Scientist",
  "icon": "F",
  "logo": "/static/logos/researchclaw.svg",
  "cmd": "/abs/path/to/famou-scientist/integrations/researchclawbench/famou-rcb -w <WORKSPACE>"
}
```

> 壳脚本从 `<WORKSPACE>/INSTRUCTIONS.md` 读 prompt，所以 `cmd` 里**只需要 `<WORKSPACE>` 占位符**。

### 2.3 配好模型与网络（和平时跑 famou 一样）

- OpenCode 模型配置（`~/.config/opencode/opencode.jsonc`）里要有可用的 `model` 与 provider 凭证；
- gateway/代理走环境变量（如 `ANTHROPIC_BASE_URL` / `ALL_PROXY`）——**子进程继承启动 RCB 时的环境**，
  所以在**启动 RCB Web UI 或 `rcb-eval` 的那个 shell**里先 export 好。
- 可选：`FAMOU_RCB_MODEL=provider/model` 覆盖默认模型（否则用 opencode 配置里的默认）。

---

## 3. 运行

### Web UI（推荐先用它单跑一个任务）

```bash
cd ResearchClawBench
python3 -m evaluation.server      # 或仓库内的等价入口
# 浏览器开 http://localhost:5000 → 选任务 → agent 选 "Famou-Scientist" → Start Run
```

### 命令行单任务

直接调壳脚本（手动准备一个 workspace），或经 RCB 的 Web/server 流程。注意 `rcb-eval`（yaml 那套）是
**路 B（ResearchHarness 模型端点）**，**不走 famou**；famou 用 agents.json 的 agent 路径。

---

## 4. 跑真榜前要盯的风险（按优先级）

1. **「问用户」停顿 vs 全自主**（最高危）：famou 的 `AGENTS.md` 有「关键停顿点，问用户」（如备数据）。
   headless `opencode run` 下没有人可问——RCB 的 `INSTRUCTIONS.md` 已明令「never ask、做合理假设、继续」，
   且无 TTY 时 agent 也问不了。**失败模式是「提前结束、没写 paper.md」**——壳脚本会检测到（exit 1 + 警告），
   不会静默交错报告。若真发生，需要给 famou 加一个 benchmark 模式抑制这些停顿。
2. **产物文件名/落点**：壳脚本按 `research-runs/<主题>/deliverables/paper.md` + `figures/*.png` 搬运（带通配兜底，
   排除 `reviews.md`/`citations.md`）。真跑一遍确认 `report/report.md` 真被填上，否则 scorer 报「No report found」直接 0 分。
3. **工具权限**：`opencode.json` 未设 `permission`（默认放行），headless 已验证不卡（见下）。若换环境出现卡顿，
   在 benchmark 专用 config 里显式 `permission: allow`。

---

## 5. 已验证 / 待验证

**已验证（本次接入）**：
- ✅ **启动链（真模型）**：`famou-scientist run "<prompt>"` → `opencode run` → 加载我们的 skill/tool/hook 资产
  → 用配置的 `claude-sonnet-4-6` 应答 → **跑完干净退出**。非交互、不卡权限。
- ✅ **产物搬运**：合成 workspace 单测——`paper.md`→`report/report.md`、`figures/*.png`→`report/images/`、
  图链接 `figures/`→`images/` 重写、`reviews.md` 正确排除。
- ✅ **注册**：`agents.json` 合法、被 `config.AGENT_PRESETS` 加载，出现 `famou` 项。

**待验证（需你用 gateway 环境跑一整个真任务）**：
- ⏳ famou 在 headless 下**完整跑完一个 RCB 任务并真的写出 `paper.md`**（验证风险点 #1/#2）。建议先拿
  `Physics_003`（示例 config 默认任务）单跑一遍，看 `report/report.md` 是否生成、scorer 是否打出分。

---

## 6. 壳脚本约定速查

| 项 | 值 |
|---|---|
| 入口 | `integrations/researchclawbench/famou-rcb -w <WORKSPACE>` |
| prompt 来源 | `<WORKSPACE>/INSTRUCTIONS.md`（RCB 写入） |
| 启动方式 | PATH 有 `famou-scientist` 用之，否则 `PYTHONPATH=<repo> python3 -m famou_scientist run` |
| 模型覆盖 | 环境变量 `FAMOU_RCB_MODEL`（可选） |
| 搬运：论文 | `research-runs/*/deliverables/paper.md`（兜底：deliverables 下非 reviews/citations 的最新 `.md`）→ `report/report.md` |
| 搬运：图 | run 目录下所有 `*.png` → `report/images/` |
| 退出码 | 有 `report/report.md` → 0；否则 → 1（并打印警告） |
