#!/usr/bin/env bash
# Supervise a trusted SciModelingBench evaluator and benchmark-managed Agent loop.
set -euo pipefail

RUN_DIR="${1:?usage: task_entrypoint.sh RUN_DIR TASK_ID RUNTIME MODEL MAX_BENCHMARK_ATTEMPTS MAX_WALL_TIME_HOURS MAX_IMPLEMENT_TURNS MAX_RUN_ATTEMPTS IDEA_CONCURRENCY IMPLEMENT_CONCURRENCY EVALUATION_CONCURRENCY IDEA_QUEUE_CAPACITY EVALUATION_QUEUE_CAPACITY EVALUATOR_REQUEST_TIMEOUT_SEC TIME_AWARE_IDEA_RANKING IDEA_RANK_TRIGGER_REMAINING_SEC IDEA_RANK_MODEL IDEA_RANK_MAX_TURNS IDEA_RANK_TIMEOUT_SEC AVAILABLE_CPU AVAILABLE_GPU AVAILABLE_MEMORY_GIB EVALUATION_TIMEOUT_SEC AGENT_UID AGENT_GID AGENT_PROCESS_MEMORY_LIMIT_GIB REVISION AUTO_INSTALL [AGENT_BINARY]}"
TASK_ID="${2:?missing task id}"
RUNTIME="${3:-claude}"
MODEL="${4:-glm-5.2}"
MAX_BENCHMARK_ATTEMPTS="${5:--}"
MAX_WALL_TIME_HOURS="${6:-4}"
MAX_IMPLEMENT_TURNS="${7:-3}"
MAX_RUN_ATTEMPTS="${8:-6}"
IDEA_CONCURRENCY="${9:-1}"
IMPLEMENT_CONCURRENCY="${10:-1}"
EVALUATION_CONCURRENCY="${11:-3}"
IDEA_QUEUE_CAPACITY="${12:-3}"
EVALUATION_QUEUE_CAPACITY="${13:-3}"
EVALUATOR_REQUEST_TIMEOUT_SEC="${14:-7200}"
TIME_AWARE_IDEA_RANKING="${15:-1}"
IDEA_RANK_TRIGGER_REMAINING_SEC="${16:-3600}"
IDEA_RANK_MODEL="${17:-${MODEL}}"
IDEA_RANK_MAX_TURNS="${18:-30}"
IDEA_RANK_TIMEOUT_SEC="${19:-600}"
AVAILABLE_CPU="${20:-16}"
AVAILABLE_GPU="${21:-0}"
AVAILABLE_MEMORY_GIB="${22:-64}"
EVALUATION_TIMEOUT_SEC="${23:-3600}"
AGENT_UID="${24:-10001}"
AGENT_GID="${25:-10001}"
AGENT_PROCESS_MEMORY_LIMIT_GIB="${26:--}"
REVISION="${27:-d8b9ea3c78ed33edf0869a427940a0651eb49f52}"
AUTO_INSTALL="${28:-1}"
AGENT_BINARY="${29:-}"
EXPERIMENT_TIMEOUT_SEC="${FAMOU_EXPERIMENT_TIMEOUT_SEC:-3600}"
IMPLEMENT_DEADLINE_HEARTBEAT="${FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT:-1}"
IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC="${FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC:-2400}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAMOU_SOURCE="${FAMOU_SOURCE:-$(cd "${SCRIPT_DIR}/../../../../../.." && pwd)}"

CHANNEL_DIR="${RUN_DIR}/controller/evaluator_channel"
TRUSTED_DIR="${RUN_DIR}/trusted"
CLAUDE_SETTINGS_FILE="${TRUSTED_DIR}/claude_settings.json"
AGENT_HOME="${RUN_DIR}/agent_home"
PUBLIC_PYTHONPATH="${FAMOU_SOURCE}"
TRUSTED_PYTHONPATH="${FAMOU_SOURCE}"
TRUSTED_CACHE_DIR="${TRUSTED_DIR}/scimodelingbench/hf_home"
EVALUATOR_LOG="${TRUSTED_DIR}/logs/evaluator.log"
EVALUATOR_PID=""
EVALUATOR_DRAIN_TIMEOUT_SEC="${EVALUATOR_DRAIN_TIMEOUT_SEC:-300}"

if [[ "$(id -u)" != "0" ]]; then
    echo "SciModelingBench task supervisor must start as root" >&2
    exit 2
fi
if [[ -z "${MODEL}" || "${MODEL}" == "-" ]]; then
    echo "an explicit Agent model is required" >&2
    exit 2
fi
for path in "${TRUSTED_DIR}" "${CHANNEL_DIR}" "${RUN_DIR}/problem"; do
    if [[ ! -d "${path}" ]]; then
        echo "required task-local path is missing: ${path}" >&2
        exit 2
    fi
done
if [[ "$(stat -c '%a' "${TRUSTED_DIR}")" != "700" ]]; then
    echo "trusted directory must have mode 700: ${TRUSTED_DIR}" >&2
    exit 2
fi

cleanup() {
    if [[ -n "${EVALUATOR_PID}" ]] && kill -0 "${EVALUATOR_PID}" 2>/dev/null; then
        kill -TERM "${EVALUATOR_PID}" 2>/dev/null || true
        wait "${EVALUATOR_PID}" 2>/dev/null || true
    fi
    rm -f "${AGENT_HOME}/.claude/settings.json"
}

signal_exit() {
    local exit_code="$1"
    exit "${exit_code}"
}

trap cleanup EXIT
trap 'signal_exit 130' INT
trap 'signal_exit 143' TERM

ensure_package() {
    if python - <<'PY' >/dev/null 2>&1
import sci_modeling_bench
PY
    then
        return
    fi
    if [[ "${AUTO_INSTALL}" != "1" ]]; then
        echo "sci-modeling-bench is not installed and AUTO_INSTALL is disabled" >&2
        exit 2
    fi
    python -m pip install sci-modeling-bench
}

run_dataset_preflight() {
    local preflight_log="${TRUSTED_DIR}/logs/dataset_preflight.log"
    echo "running trusted SciModelingBench dataset preflight" >&2
    if ! env -u HF_HUB_OFFLINE -u HF_DATASETS_OFFLINE -u TRANSFORMERS_OFFLINE \
        HF_HOME="${TRUSTED_CACHE_DIR}" \
        HF_DATASETS_CACHE="${TRUSTED_CACHE_DIR}/datasets" \
        PYTHONPATH="${TRUSTED_PYTHONPATH}" \
        python -m famou_scientist.loop.integrations.scimodelingbench.preflight \
        --task-id "${TASK_ID}" \
        --revision "${REVISION}" \
        --cache-dir "${TRUSTED_CACHE_DIR}" >"${preflight_log}" 2>&1; then
        echo "SciModelingBench dataset preflight failed" >&2
        tail -n 100 "${preflight_log}" >&2 || true
        exit 3
    fi
}

restore_claude_settings() {
    if [[ "${RUNTIME}" != "claude" ]]; then
        return
    fi
    if [[ ! -f "${CLAUDE_SETTINGS_FILE}" || -L "${CLAUDE_SETTINGS_FILE}" ]]; then
        echo "Claude resume configuration is missing: ${CLAUDE_SETTINGS_FILE}" >&2
        exit 2
    fi
    mkdir -p "${AGENT_HOME}/.claude"
    cp "${CLAUDE_SETTINGS_FILE}" "${AGENT_HOME}/.claude/settings.json"
    chmod 700 "${AGENT_HOME}" "${AGENT_HOME}/.claude"
    chmod 600 "${AGENT_HOME}/.claude/settings.json"
    chown "${AGENT_UID}:${AGENT_GID}" \
        "${AGENT_HOME}" "${AGENT_HOME}/.claude" "${AGENT_HOME}/.claude/settings.json"
}

mkdir -p "${RUN_DIR}/results" "${TRUSTED_DIR}/logs" "${TRUSTED_CACHE_DIR}"
chmod 700 "${TRUSTED_DIR}/logs"
ensure_package
run_dataset_preflight
restore_claude_settings

# These files describe one supervisor/evaluator session, not durable queue state.
# A resumed run must establish a fresh handshake with its new evaluator worker.
rm -f \
    "${CHANNEL_DIR}/CLIENT_DONE.json" \
    "${CHANNEL_DIR}/EVALUATOR_READY.json" \
    "${CHANNEL_DIR}/EVALUATOR_DONE.json"
for channel_cache in "${CHANNEL_DIR}/requests" "${CHANNEL_DIR}/responses"; do
    find "${channel_cache}" -mindepth 1 -maxdepth 1 \
        \( -type f -o -type l \) -delete
done

env HF_HOME="${TRUSTED_CACHE_DIR}" \
    HF_DATASETS_CACHE="${TRUSTED_CACHE_DIR}/datasets" \
    HF_HUB_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONPATH="${TRUSTED_PYTHONPATH}" \
    python -m famou_scientist.loop.integrations.scimodelingbench.evaluator_worker \
    --task-id "${TASK_ID}" \
    --workspace-dir "${RUN_DIR}/workspace" \
    --channel-dir "${CHANNEL_DIR}" \
    --private-key "${TRUSTED_DIR}/private_key.pem" \
    --agent-log-dir "${RUN_DIR}/controller/evaluator_agent_logs" \
    --cache-dir "${TRUSTED_CACHE_DIR}" \
    --revision "${REVISION}" \
    >"${EVALUATOR_LOG}" 2>&1 &
EVALUATOR_PID=$!

for _ in $(seq 1 600); do
    if [[ -f "${CHANNEL_DIR}/EVALUATOR_READY.json" ]]; then
        break
    fi
    if ! kill -0 "${EVALUATOR_PID}" 2>/dev/null; then
        echo "task-local evaluator exited during startup" >&2
        tail -n 100 "${EVALUATOR_LOG}" >&2 || true
        exit 3
    fi
    sleep 1
done
if [[ ! -f "${CHANNEL_DIR}/EVALUATOR_READY.json" ]]; then
    echo "task-local evaluator did not become ready" >&2
    exit 3
fi

export HOME="${AGENT_HOME}"
export PYTHONPATH="${PUBLIC_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
args=(
    agent run
    --task-id "${TASK_ID}"
    --run-dir "${RUN_DIR}"
    --problem-dir "${RUN_DIR}/problem"
    --workspace-dir "${RUN_DIR}/workspace"
    --evaluator-channel "${CHANNEL_DIR}"
    --evaluator-public-key "${CHANNEL_DIR}/public_key.pem"
    --evaluator-timeout-sec "${EVALUATOR_REQUEST_TIMEOUT_SEC}"
    --experiment-timeout-sec "${EXPERIMENT_TIMEOUT_SEC}"
    --agent-adapter cli
    --agent-graph "${FAMOU_AGENT_GRAPH:-sota_search}"
    --official-gt-budget "${FAMOU_OFFICIAL_GT_BUDGET:-1}"
    --agent-runtime "${RUNTIME}"
    --agent-binary "${AGENT_BINARY}"
    --implement-deadline-heartbeat-after-sec "${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC}"
    --model "${MODEL}"
    --benchmark-adapter scimodelingbench
    --evaluator-adapter scimodelingbench
    --no-scimodelingbench-managed-evaluator
    --no-scimodelingbench-prepare-problem
    --max-wall-time-hours "${MAX_WALL_TIME_HOURS}"
    --max-parallel-ideas "${IDEA_CONCURRENCY}"
    --max-parallel-implementations "${IMPLEMENT_CONCURRENCY}"
    --max-parallel-evaluations "${EVALUATION_CONCURRENCY}"
    --max-implement-lifetime-sec 14400
    --max-implement-turns-per-actor "${MAX_IMPLEMENT_TURNS}"
    --max-run-attempts-per-actor "${MAX_RUN_ATTEMPTS}"
    --idea-queue-high-watermark "${IDEA_QUEUE_CAPACITY}"
    --evaluation-queue-capacity "${EVALUATION_QUEUE_CAPACITY}"
    --idea-rank-trigger-remaining-sec "${IDEA_RANK_TRIGGER_REMAINING_SEC}"
    --idea-rank-model "${IDEA_RANK_MODEL}"
    --idea-rank-max-turns "${IDEA_RANK_MAX_TURNS}"
    --idea-rank-timeout-sec "${IDEA_RANK_TIMEOUT_SEC}"
    --available-cpu "${AVAILABLE_CPU}"
    --available-gpu "${AVAILABLE_GPU}"
    --available-memory-gib "${AVAILABLE_MEMORY_GIB}"
    --agent-uid "${AGENT_UID}"
    --agent-gid "${AGENT_GID}"
    --no-finalize-evaluation
)
if [[ "${AGENT_PROCESS_MEMORY_LIMIT_GIB}" != "-" && -n "${AGENT_PROCESS_MEMORY_LIMIT_GIB}" ]]; then
    args+=(--agent-process-memory-limit-gib "${AGENT_PROCESS_MEMORY_LIMIT_GIB}")
fi
if [[ "${IMPLEMENT_DEADLINE_HEARTBEAT}" == "1" ]]; then
    args+=(--implement-deadline-heartbeat)
else
    args+=(--no-implement-deadline-heartbeat)
fi
if [[ "${MAX_BENCHMARK_ATTEMPTS}" != "-" && -n "${MAX_BENCHMARK_ATTEMPTS}" ]]; then
    args+=(--iterations "${MAX_BENCHMARK_ATTEMPTS}")
fi
if [[ "${TIME_AWARE_IDEA_RANKING}" == "1" ]]; then
    args+=(--time-aware-idea-ranking)
else
    args+=(--no-time-aware-idea-ranking)
fi

set +e
python -m famou_scientist "${args[@]}" \
    > >(tee "${RUN_DIR}/results/agent.log") \
    2> >(tee "${RUN_DIR}/results/agent.stderr.log" >&2)
CONTROLLER_RC=$?
set -e

if [[ ! -f "${CHANNEL_DIR}/CLIENT_DONE.json" ]]; then
    done_tmp="${CHANNEL_DIR}/.CLIENT_DONE.json.tmp.$$"
    printf '{"source":"task_supervisor","controller_returncode":%s}\n' \
        "${CONTROLLER_RC}" >"${done_tmp}"
    mv "${done_tmp}" "${CHANNEL_DIR}/CLIENT_DONE.json"
fi

drain_deadline=$((SECONDS + EVALUATOR_DRAIN_TIMEOUT_SEC))
while kill -0 "${EVALUATOR_PID}" 2>/dev/null; do
    if [[ -f "${CHANNEL_DIR}/EVALUATOR_DONE.json" ]]; then
        break
    fi
    if (( SECONDS >= drain_deadline )); then
        echo "task-local evaluator did not drain within ${EVALUATOR_DRAIN_TIMEOUT_SEC}s" >&2
        kill -TERM "${EVALUATOR_PID}" 2>/dev/null || true
        sleep 2
        if kill -0 "${EVALUATOR_PID}" 2>/dev/null; then
            kill -KILL "${EVALUATOR_PID}" 2>/dev/null || true
        fi
        break
    fi
    sleep 1
done

set +e
wait "${EVALUATOR_PID}"
EVALUATOR_RC=$?
set -e
EVALUATOR_PID=""

if [[ "${CONTROLLER_RC}" -ne 0 ]]; then
    exit "${CONTROLLER_RC}"
fi
if [[ "${EVALUATOR_RC}" -ne 0 ]]; then
    echo "task-local evaluator exited with code ${EVALUATOR_RC}" >&2
    exit "${EVALUATOR_RC}"
fi
if [[ ! -f "${CHANNEL_DIR}/EVALUATOR_DONE.json" ]]; then
    echo "task-local evaluator exited without EVALUATOR_DONE" >&2
    exit 4
fi
exit 0
