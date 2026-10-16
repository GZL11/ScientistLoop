#!/usr/bin/env bash
# Submit one SciModelingBench task through fm-job.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAMOU_SOURCE="${FAMOU_SOURCE:-$(cd "${SCRIPT_DIR}/../../../../.." && pwd)}"
FM_JOB_BIN="${FM_JOB_BIN:-fm-job}"

TASK_ID="${TASK_ID:-tfbind8}"
IMAGE="${IMAGE:-<你的镜像仓库>/famou-public/scimodelingbench-agent:cli-runtimes-v2-datasets48}"
AGENT_RUNTIME="${AGENT_RUNTIME:-claude}"
AGENT_BINARY="${AGENT_BINARY:-}"
MODEL="${MODEL:-glm-5.2}"
AGENT_GRAPH="${AGENT_GRAPH:-sota_search}"
OFFICIAL_GT_BUDGET="${OFFICIAL_GT_BUDGET:-1}"
MAX_BENCHMARK_ATTEMPTS="${MAX_BENCHMARK_ATTEMPTS:-${ITERATIONS:--}}"
DEFAULT_WALL_TIME_HOURS=4
if [[ "${AGENT_GRAPH}" == "scimodeling_budget" ]]; then
    DEFAULT_WALL_TIME_HOURS=2
fi
MAX_WALL_TIME_HOURS="${MAX_WALL_TIME_HOURS:-${DEFAULT_WALL_TIME_HOURS}}"
STARTUP_GRACE_SEC="${STARTUP_GRACE_SEC:-900}"
MAX_IMPLEMENT_TURNS="${MAX_IMPLEMENT_TURNS:-3}"
MAX_RUN_ATTEMPTS="${MAX_RUN_ATTEMPTS:-6}"
IDEA_CONCURRENCY="${IDEA_CONCURRENCY:-1}"
IMPLEMENT_CONCURRENCY="${IMPLEMENT_CONCURRENCY:-1}"
EVALUATION_CONCURRENCY="${EVALUATION_CONCURRENCY:-3}"
IDEA_QUEUE_CAPACITY="${IDEA_QUEUE_CAPACITY:-3}"
EVALUATION_QUEUE_CAPACITY="${EVALUATION_QUEUE_CAPACITY:-3}"
EXPERIMENT_TIMEOUT_SEC="${EXPERIMENT_TIMEOUT_SEC:-3600}"
IMPLEMENT_DEADLINE_HEARTBEAT="${IMPLEMENT_DEADLINE_HEARTBEAT:-1}"
IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC="${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC:-2400}"
EVALUATION_TIMEOUT_SEC="${EVALUATION_TIMEOUT_SEC:-3600}"
EVALUATOR_REQUEST_TIMEOUT_SEC="${EVALUATOR_REQUEST_TIMEOUT_SEC:-$((EVALUATION_TIMEOUT_SEC + 300))}"
RESEARCH_BUDGET_SEC="$(awk -v hours="${MAX_WALL_TIME_HOURS}" 'BEGIN { printf "%d", hours * 3600 }')"
EVALUATION_DRAIN_BUDGET_SEC="$((EVALUATION_QUEUE_CAPACITY * (EXPERIMENT_TIMEOUT_SEC + EVALUATION_TIMEOUT_SEC)))"
FINALIZATION_GRACE_SEC="${FINALIZATION_GRACE_SEC:-$((EVALUATION_DRAIN_BUDGET_SEC + 300))}"
HARD_TIMEOUT_SEC="${HARD_TIMEOUT_SEC:-$((RESEARCH_BUDGET_SEC + FINALIZATION_GRACE_SEC + STARTUP_GRACE_SEC))}"
TIME_AWARE_IDEA_RANKING="${TIME_AWARE_IDEA_RANKING:-1}"
IDEA_RANK_TRIGGER_REMAINING_SEC="${IDEA_RANK_TRIGGER_REMAINING_SEC:-3600}"
IDEA_RANK_MODEL="${IDEA_RANK_MODEL:-${MODEL}}"
IDEA_RANK_MAX_TURNS="${IDEA_RANK_MAX_TURNS:-30}"
IDEA_RANK_TIMEOUT_SEC="${IDEA_RANK_TIMEOUT_SEC:-600}"
AGENT_CPU="${AGENT_CPU:-16}"
AGENT_GPU="${AGENT_GPU:-0}"
AGENT_MEMORY_GIB="${AGENT_MEMORY_GIB:-64}"
AGENT_PROCESS_MEMORY_LIMIT_GIB="${AGENT_PROCESS_MEMORY_LIMIT_GIB:--}"
AGENT_UID="${AGENT_UID:-10001}"
AGENT_GID="${AGENT_GID:-10001}"
SCIMODELINGBENCH_REVISION="${SCIMODELINGBENCH_REVISION:-d8b9ea3c78ed33edf0869a427940a0651eb49f52}"
SCIMODELINGBENCH_AUTO_INSTALL="${SCIMODELINGBENCH_AUTO_INSTALL:-0}"
DRY_RUN="${DRY_RUN:-0}"
RESUME="${RESUME:-0}"

RUN_ID="${RUN_ID:-${TASK_ID}-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="${RUN_DIR:-${FAMOU_SOURCE}/.famou/scimodelingbench-fmjob-runs/${RUN_ID}}"
TRUSTED_DIR="${RUN_DIR}/trusted"
TRUSTED_CACHE_DIR="${TRUSTED_DIR}/scimodelingbench/hf_home"
CLAUDE_SETTINGS_SOURCE="${CLAUDE_SETTINGS_SOURCE:-${HOME}/.claude/settings.json}"
KIMI_CODE_CONFIG="${KIMI_CODE_CONFIG:-${TRUSTED_DIR}/kimi-code/config.toml}"

CFS_OWNER_PREFIX="${CFS_OWNER_PREFIX:-/path/to/workspace/}"
FMJOB_MOUNT_PREFIX="${FMJOB_MOUNT_PREFIX:-/path/to/workspace}"
FMJOB_MOUNT_HOST_DIR="${FMJOB_MOUNT_HOST_DIR:-${FAMOU_SOURCE}}"

stage() {
    printf '\n[%s/3] %s\n' "$1" "$2"
}

prepare_agent_run() {
    stage 1 "prepare isolated SciModelingBench run directory"

    if [[ -z "${MODEL}" || "${MODEL}" == "-" ]]; then
        echo "MODEL must be explicit" >&2
        exit 2
    fi
    local args=(
        --task-id "${TASK_ID}"
        --famou-source "${FAMOU_SOURCE}"
        --run-dir "${RUN_DIR}"
        --cache-dir "${TRUSTED_CACHE_DIR}"
        --revision "${SCIMODELINGBENCH_REVISION}"
        --agent-uid "${AGENT_UID}"
        --agent-gid "${AGENT_GID}"
    )
    if [[ "${AGENT_RUNTIME}" == "claude" ]]; then
        if [[ ! -f "${CLAUDE_SETTINGS_SOURCE}" ]]; then
            echo "Claude settings not found: ${CLAUDE_SETTINGS_SOURCE}" >&2
            exit 2
        fi
        args+=(--claude-settings "${CLAUDE_SETTINGS_SOURCE}")
    fi
    env ALL_PROXY="${ALL_PROXY:-}" \
        HTTPS_PROXY="${HTTPS_PROXY:-}" \
        HTTP_PROXY="${HTTP_PROXY:-}" \
        HF_HOME="${TRUSTED_CACHE_DIR}" \
        HF_DATASETS_CACHE="${TRUSTED_CACHE_DIR}/datasets" \
        PYTHONPATH="${FAMOU_SOURCE}${PYTHONPATH:+:${PYTHONPATH}}" \
        python "${SCRIPT_DIR}/prepare_run.py" "${args[@]}"
}

validate_resume_run() {
    stage 1 "validate existing SciModelingBench run for resume"

    local state_path="${RUN_DIR}/research_state.yaml"
    if [[ "${AGENT_GRAPH}" == "scimodeling_budget" ]]; then
        state_path="${RUN_DIR}/controller/limited_gt/state.json"
    fi
    for path in \
        "${state_path}" \
        "${RUN_DIR}/problem" \
        "${RUN_DIR}/workspace" \
        "${RUN_DIR}/trusted/private_key.pem" \
        "${RUN_DIR}/controller/evaluator_channel/public_key.pem"; do
        if [[ ! -e "${path}" ]]; then
            echo "resume run is missing required path: ${path}" >&2
            exit 2
        fi
    done
    if [[ ! -d "${RUN_DIR}/controller/evaluator_channel/requests" || \
          ! -d "${RUN_DIR}/controller/evaluator_channel/responses" ]]; then
        echo "resume run is missing evaluator channel directories: ${RUN_DIR}" >&2
        exit 2
    fi
    if [[ "${AGENT_RUNTIME}" == "claude" && \
          ! -f "${RUN_DIR}/trusted/claude_settings.json" ]]; then
        echo "resume run is missing durable Claude settings: ${RUN_DIR}/trusted/claude_settings.json" >&2
        exit 2
    fi
}

validate_kimi_config() {
    if [[ "${AGENT_RUNTIME}" != "kimi-code" ]]; then
        return
    fi
    if [[ ! -f "${KIMI_CODE_CONFIG}" ]]; then
        echo "kimi-code requires a Kimi config file: ${KIMI_CODE_CONFIG}" >&2
        exit 2
    fi
}

create_evaluator_key() {
    stage 2 "create evaluator response signing key"

    mkdir -p "${TRUSTED_DIR}" "${RUN_DIR}/controller/evaluator_channel"
    chmod 700 "${TRUSTED_DIR}"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
        -out "${TRUSTED_DIR}/private_key.pem" >/dev/null 2>&1
    openssl pkey -in "${TRUSTED_DIR}/private_key.pem" -pubout \
        -out "${RUN_DIR}/controller/evaluator_channel/public_key.pem" >/dev/null 2>&1
}

resolve_task_mount() {
    if [[ "${FMJOB_MOUNT_HOST_DIR}" != "${CFS_OWNER_PREFIX}"* ]]; then
        echo "mount root must be below CFS_OWNER_PREFIX=${CFS_OWNER_PREFIX}: ${FMJOB_MOUNT_HOST_DIR}" >&2
        exit 2
    fi
    case "${RUN_DIR}/" in
        "${FMJOB_MOUNT_HOST_DIR}/"*) ;;
        *)
            echo "RUN_DIR must be inside FMJOB_MOUNT_HOST_DIR: ${RUN_DIR}" >&2
            exit 2
            ;;
    esac
    RUN_SUBPATH="${FMJOB_MOUNT_HOST_DIR#${CFS_OWNER_PREFIX}}"
    TASK_RUN_DIR="${FMJOB_MOUNT_PREFIX}/${RUN_DIR#${CFS_OWNER_PREFIX}}"
}

submit_task_job() {
    stage 3 "submit SciModelingBench task job"

    # Kubernetes Job names are RFC 1123; task directories keep the canonical id.
    local job_task_id="${TASK_ID//_/-}"
    local job_prefix="famou-smb-${job_task_id}"
    if [[ "${AGENT_GRAPH}" == "scimodeling_budget" ]]; then
        # Four budget arms may finish preparation in the same second.
        # fm-job appends only a second-resolution timestamp to this prefix.
        job_prefix+="-k${OFFICIAL_GT_BUDGET}"
    fi
    local fmjob_args=(
        run
        --prefix "${job_prefix}"
        --gpu "${AGENT_GPU}"
        --cpu "${AGENT_CPU}"
        --memory "${AGENT_MEMORY_GIB}Gi"
        --shm-size 8Gi
        --subpath "${RUN_SUBPATH}"
        --no-wait
    )
    if [[ -n "${IMAGE}" && "${IMAGE}" != "-" ]]; then
        fmjob_args+=(--image "${IMAGE}")
    fi

    local command=(
        "${FM_JOB_BIN}" "${fmjob_args[@]}" --
        env ALL_PROXY="${ALL_PROXY:-}"
        HTTPS_PROXY="${HTTPS_PROXY:-}" \
        HTTP_PROXY="${HTTP_PROXY:-}" \
        FAMOU_SOURCE="${FAMOU_SOURCE}" \
        FAMOU_AGENT_GRAPH="${AGENT_GRAPH}" \
        FAMOU_OFFICIAL_GT_BUDGET="${OFFICIAL_GT_BUDGET}" \
        KIMI_CODE_CONFIG="${KIMI_CODE_CONFIG}" \
        FAMOU_EXPERIMENT_TIMEOUT_SEC="${EXPERIMENT_TIMEOUT_SEC}" \
        FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT="${IMPLEMENT_DEADLINE_HEARTBEAT}" \
        FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC="${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC}" \
        timeout --signal=TERM --kill-after=60s "${HARD_TIMEOUT_SEC}" /bin/bash \
        "${FAMOU_SOURCE}/famou_scientist/loop/examples/scimodelingbench/fmjob/task_entrypoint.sh" \
        "${TASK_RUN_DIR}" "${TASK_ID}" "${AGENT_RUNTIME}" "${MODEL}" \
        "${MAX_BENCHMARK_ATTEMPTS}" "${MAX_WALL_TIME_HOURS}" \
        "${MAX_IMPLEMENT_TURNS}" "${MAX_RUN_ATTEMPTS}" \
        "${IDEA_CONCURRENCY}" "${IMPLEMENT_CONCURRENCY}" \
        "${EVALUATION_CONCURRENCY}" "${IDEA_QUEUE_CAPACITY}" \
        "${EVALUATION_QUEUE_CAPACITY}" "${EVALUATOR_REQUEST_TIMEOUT_SEC}" \
        "${TIME_AWARE_IDEA_RANKING}" "${IDEA_RANK_TRIGGER_REMAINING_SEC}" \
        "${IDEA_RANK_MODEL}" "${IDEA_RANK_MAX_TURNS}" "${IDEA_RANK_TIMEOUT_SEC}" \
        "${AGENT_CPU}" "${AGENT_GPU}" "${AGENT_MEMORY_GIB}" \
        "${EVALUATION_TIMEOUT_SEC}" "${AGENT_UID}" "${AGENT_GID}" \
        "${AGENT_PROCESS_MEMORY_LIMIT_GIB}" "${SCIMODELINGBENCH_REVISION}" \
        "${SCIMODELINGBENCH_AUTO_INSTALL}" "${AGENT_BINARY}"
    )
    if [[ "${DRY_RUN}" == "1" ]]; then
        printf 'dry-run fm-job command:\n'
        printf '  %q' "${command[@]}"
        printf '\n'
        return
    fi
    "${command[@]}"
}

print_summary() {
    printf '\nSciModelingBench job submitted.\n'
    printf '  run_id:     %s\n' "${RUN_ID}"
    printf '  host_dir:   %s\n' "${RUN_DIR}"
    printf '  task_dir:   %s\n' "${TASK_RUN_DIR}"
    printf '  mount root: %s\n' "${FMJOB_MOUNT_HOST_DIR}"
    printf '  task_id:    %s\n' "${TASK_ID}"
    printf '  revision:   %s\n' "${SCIMODELINGBENCH_REVISION}"
    printf '  agent runtime: %s\n' "${AGENT_RUNTIME}"
    printf '  agent binary:  %s\n' "${AGENT_BINARY:-<runtime default>}"
    printf '  agent model: %s\n' "${MODEL}"
    printf '  resources: cpu=%s gpu=%s memory=%sGi\n' \
        "${AGENT_CPU}" "${AGENT_GPU}" "${AGENT_MEMORY_GIB}"
    printf '  hard timeout: %ss\n' "${HARD_TIMEOUT_SEC}"
    printf '  dry run: %s\n' "${DRY_RUN}"
}

main() {
    if [[ "${DRY_RUN}" != "1" ]]; then
        if [[ "${RESUME}" == "1" || -e "${RUN_DIR}/research_state.yaml" || -e "${RUN_DIR}/controller/limited_gt/state.json" ]]; then
            validate_resume_run
        else
            prepare_agent_run
            create_evaluator_key
        fi
        validate_kimi_config
    fi
    resolve_task_mount
    submit_task_job
    print_summary
}

main "$@"
