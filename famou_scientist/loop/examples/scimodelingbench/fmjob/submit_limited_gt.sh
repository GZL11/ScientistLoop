#!/usr/bin/env bash
# Independent 2h trials for each task x k x repetition. No cross-run warm-start.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATCH_ID="${BATCH_ID:-limited-gt-$(date +%Y%m%d-%H%M%S)}"
read -r -a TASK_LIST <<< "${TASKS:-tfbind8 tfbind10_pho4 cell_dag_nas superconductor hopper_controller utr_mrl_egfp_unmodified gfp drugmatrix_mchc drugmatrix_mch drugmatrix_creatinine drugmatrix_sodium drugmatrix_chloride drugmatrix_phosphorus}"
read -r -a BUDGET_LIST <<< "${GT_BUDGETS:-0 1 5 20}"
REPEATS="${REPEATS:-1}"
: "${MODEL:?Set MODEL explicitly so all budget arms use the same model}"
[[ "${REPEATS}" =~ ^[1-9][0-9]*$ ]] || { echo 'REPEATS must be positive' >&2; exit 2; }
for k in "${BUDGET_LIST[@]}"; do
    [[ "${k}" =~ ^(0|1|5|20)$ ]] || { echo "unsupported ablation k=${k}" >&2; exit 2; }
done
# Each call must receive a distinct run directory. Prevent accidental inherited
# RUN_DIR/RUN_ID/RESUME from collapsing multiple experimental arms.
unset RUN_DIR RUN_ID RESUME
for ((repeat=1; repeat<=REPEATS; repeat++)); do
    for task_id in "${TASK_LIST[@]}"; do
        for k in "${BUDGET_LIST[@]}"; do
            TASK_ID="${task_id}" RUN_ID="${task_id}-${BATCH_ID}-k${k}-r${repeat}" \
            AGENT_GRAPH=scimodeling_budget OFFICIAL_GT_BUDGET="${k}" \
            MAX_WALL_TIME_HOURS=2 MAX_BENCHMARK_ATTEMPTS=- \
            AGENT_CPU="${AGENT_CPU:-8}" AGENT_GPU="${AGENT_GPU:-0}" \
            AGENT_MEMORY_GIB="${AGENT_MEMORY_GIB:-32}" \
            TIME_AWARE_IDEA_RANKING=0 IMPLEMENT_DEADLINE_HEARTBEAT=0 \
            FINALIZATION_GRACE_SEC="${FINALIZATION_GRACE_SEC:-4200}" \
            bash "${SCRIPT_DIR}/submit_one_click.sh"
        done
    done
done
