#!/usr/bin/env bash
# Submit the 12 SciModelingBench tasks reported by ScienceFlow with an
# approximate parity configuration based on ScienceFlow paper Section 3.3.1.
# The paper specifies 2h, 8 logical CPUs, no accelerator, and <32 GiB RSS.
# Task-specific Q quotas and the two-worker summary protocol are not fully
# represented by this generic Famou harness.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATCH_ID="${BATCH_ID:-scienceflow-dsv4flash-$(date +%Y%m%d-%H%M%S)}"

TASKS=(
    tfbind8
    superconductor
    utr_mrl_egfp_unmodified
    tfbind10_pho4
    gfp
    hopper_controller
    drugmatrix_mchc
    drugmatrix_mch
    drugmatrix_creatinine
    drugmatrix_sodium
    drugmatrix_chloride
    drugmatrix_phosphorus
)

for task_id in "${TASKS[@]}"; do
    TASK_ID="${task_id}" \
    RUN_ID="${task_id}-${BATCH_ID}" \
    AGENT_RUNTIME="${AGENT_RUNTIME:-claude}" \
    MODEL="${MODEL:-deepseek-v4-flash}" \
    MAX_WALL_TIME_HOURS="${MAX_WALL_TIME_HOURS:-2}" \
    STARTUP_GRACE_SEC="${STARTUP_GRACE_SEC:-900}" \
    FINALIZATION_GRACE_SEC="${FINALIZATION_GRACE_SEC:-600}" \
    MAX_BENCHMARK_ATTEMPTS="${MAX_BENCHMARK_ATTEMPTS:-20}" \
    IDEA_CONCURRENCY="${IDEA_CONCURRENCY:-2}" \
    IMPLEMENT_CONCURRENCY="${IMPLEMENT_CONCURRENCY:-2}" \
    EVALUATION_CONCURRENCY="${EVALUATION_CONCURRENCY:-2}" \
    IDEA_QUEUE_CAPACITY="${IDEA_QUEUE_CAPACITY:-2}" \
    EVALUATION_QUEUE_CAPACITY="${EVALUATION_QUEUE_CAPACITY:-2}" \
    AGENT_CPU="${AGENT_CPU:-8}" \
    AGENT_GPU="${AGENT_GPU:-0}" \
    AGENT_MEMORY_GIB="${AGENT_MEMORY_GIB:-32}" \
    DRY_RUN="${DRY_RUN:-0}" \
    "${SCRIPT_DIR}/submit_one_click.sh"
done

printf '\nSubmitted ScienceFlow-parity batch: %s\n' "${BATCH_ID}"
