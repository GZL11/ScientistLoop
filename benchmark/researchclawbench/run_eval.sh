#!/usr/bin/env bash
#
# run_eval.sh — 一键在 ResearchClawBench 上评测 famou-scientist（建 workspace → 跑 → 打分 → 出分）。
#
# 用法：
#   bash run_eval.sh --rcb /path/to/ResearchClawBench [TASK ...]
#   RCB_HOME=/path/to/ResearchClawBench bash run_eval.sh [TASK ...]
#
# 不传 TASK 时默认跑一个快任务（Astronomy_000，约几分钟）先验证整条链。
#
# 前置（本脚本只检查、不代装）：
#   1. pip 装好 famou-scientist（`famou-scientist` 在 PATH）并配好模型/网关（见 famou 主 README）。
#   2. 自己 clone 好 ResearchClawBench 并装它的依赖：
#        git clone https://github.com/InternScience/ResearchClawBench
#        python3 -m pip install -r ResearchClawBench/evaluation/requirements.txt
#   3. 配好 judge（打分模型，与被测模型解耦）——环境变量或 RCB 的 evaluation/.env：
#        export JUDGE_API_KEY=...  JUDGE_API_BASE=<judge gateway>/v1  JUDGE_MODEL_NAME=gpt-5.1
#
# 凭证只走环境变量 / .env，本脚本绝不写入任何文件。
#
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- 解析 --rcb / RCB_HOME + 任务列表 ----
RCB_HOME="${RCB_HOME:-}"
TASKS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rcb)   RCB_HOME="${2:-}"; shift 2 || shift;;
    --rcb=*) RCB_HOME="${1#*=}"; shift;;
    -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0;;
    *)       TASKS+=("$1"); shift;;
  esac
done
[ ${#TASKS[@]} -eq 0 ] && TASKS=("Astronomy_000")

die() { echo "run_eval: $*" >&2; echo "  → 详见本目录 README.md 的安装/配置步骤。" >&2; exit 1; }

# ---- 前置检查（只检查、不代装）----
[ -n "$RCB_HOME" ] || die "未提供 RCB 路径。用 --rcb <path> 或设 RCB_HOME 环境变量。"
RCB_HOME="$(cd "$RCB_HOME" 2>/dev/null && pwd)" || die "RCB 路径不存在：$RCB_HOME"
[ -d "$RCB_HOME/evaluation" ] || die "$RCB_HOME 不像 ResearchClawBench 仓库（缺 evaluation/）。"
command -v famou-scientist >/dev/null 2>&1 || die "famou-scientist 不在 PATH。先 pip 装 famou-scientist。"

PYBIN="${PYTHON:-python3}"
( cd "$RCB_HOME" && "$PYBIN" -c "import evaluation" >/dev/null 2>&1 ) \
  || die "在 $RCB_HOME 下 import evaluation 失败。装依赖：python3 -m pip install -r evaluation/requirements.txt"
for v in JUDGE_API_KEY JUDGE_API_BASE JUDGE_MODEL_NAME; do
  # 允许走 RCB 的 evaluation/.env：仅当环境变量缺失且无 .env 才拦
  if [ -z "${!v:-}" ] && ! grep -q "^$v=" "$RCB_HOME/evaluation/.env" 2>/dev/null; then
    die "judge 配置缺失：$v。设环境变量或写进 $RCB_HOME/evaluation/.env（别提交）。"
  fi
done

# ---- 注册 famou（幂等，零路径 cmd）----
"$PYBIN" "$HERE/register_famou.py" --rcb "$RCB_HOME" || die "注册 famou 到 agents.json 失败。"

# ---- 逐任务：setup → run → score（在 RCB 下跑；</dev/null 防 opencode 吃掉循环 stdin）----
echo "run_eval: RCB=$RCB_HOME  tasks=${TASKS[*]}" >&2
(
  cd "$RCB_HOME" || die "cannot cd $RCB_HOME"
  for task in "${TASKS[@]}"; do
    echo "==== $task ====" >&2
    "$PYBIN" - "$task" <<'PY' </dev/null
import sys
from evaluation.run_task import TaskRunner
from evaluation import score
task = sys.argv[1]
r = TaskRunner(task, agent_name="Famou-Scientist")
r.setup_workspace()
r.run()
res = score.score_workspace(r.workspace)
s = res.get("score") if isinstance(res, dict) else res
print(f"[RESULT] {task}\tscore={s}\tworkspace={r.workspace}")
PY
  done
) | tee "$HERE/.last_eval.log"

# ---- 汇总均值 ----
"$PYBIN" - "$HERE/.last_eval.log" <<'PY'
import re, sys
scores = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    m = re.search(r"\[RESULT\]\s+(\S+)\s+score=([\d.]+)", line)
    if m:
        scores.append((m.group(1), float(m.group(2))))
if scores:
    avg = sum(s for _, s in scores) / len(scores)
    print("\n== 汇总 ==")
    for t, s in scores:
        print(f"  {t}: {s}")
    print(f"  均值（{len(scores)} 题）: {avg:.2f}")
else:
    print("\n== 无成功出分的任务（看上面的报错；常见：famou 没产出 report / judge 配置问题）==")
PY
