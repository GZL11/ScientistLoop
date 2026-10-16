#!/usr/bin/env bash
# 在一个 fm-job 内监督可信 Evaluator 和非特权 Agent Loop。
set -euo pipefail

RUN_DIR="${1:?usage: task_entrypoint.sh RUN_DIR TASK_ID RUNTIME MODEL MAX_BENCHMARK_ATTEMPTS MAX_WALL_TIME_HOURS MAX_IMPLEMENT_TURNS MAX_RUN_ATTEMPTS IDEA_CONCURRENCY IMPLEMENT_CONCURRENCY EVALUATION_CONCURRENCY IDEA_QUEUE_CAPACITY EVALUATION_QUEUE_CAPACITY VALIDITY_JUDGE EVALUATOR_REQUEST_TIMEOUT_SEC TIME_AWARE_IDEA_RANKING IDEA_RANK_TRIGGER_REMAINING_SEC IDEA_RANK_MODEL IDEA_RANK_MAX_TURNS IDEA_RANK_TIMEOUT_SEC AVAILABLE_CPU AVAILABLE_GPU AVAILABLE_MEMORY_GIB EVALUATION_TIMEOUT_SEC JUDGE_TIMEOUT_SEC AGENT_UID AGENT_GID JUDGE_MODEL AGENT_PROCESS_MEMORY_LIMIT_GIB}"
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
VALIDITY_JUDGE="${14:-1}"
EVALUATOR_REQUEST_TIMEOUT_SEC="${15:-7200}"
TIME_AWARE_IDEA_RANKING="${16:-1}"
IDEA_RANK_TRIGGER_REMAINING_SEC="${17:-3600}"
IDEA_RANK_MODEL="${18:-${MODEL}}"
IDEA_RANK_MAX_TURNS="${19:-30}"
IDEA_RANK_TIMEOUT_SEC="${20:-600}"
AVAILABLE_CPU="${21:-30}"
AVAILABLE_GPU="${22:-0}"
AVAILABLE_MEMORY_GIB="${23:-128}"
EVALUATION_TIMEOUT_SEC="${24:-3600}"
JUDGE_TIMEOUT_SEC="${25:-3600}"
AGENT_UID="${26:-10001}"
AGENT_GID="${27:-10001}"
JUDGE_MODEL="${28:--}"
AGENT_PROCESS_MEMORY_LIMIT_GIB="${29:--}"
EXPERIMENT_TIMEOUT_SEC="${FAMOU_EXPERIMENT_TIMEOUT_SEC:-3600}"
# 单次 Implement 激活的墙钟上限。默认 4800（80 分钟）：20260920 实测 3600 秒下
# 43/181 次 attempt 是跑满被掐的，心跳送到时代码还没跑通（HEARTBEAT_FINDINGS.md）。
IMPLEMENT_TIMEOUT_SEC="${FAMOU_IMPLEMENT_TIMEOUT_SEC:-4800}"
IMPLEMENT_DEADLINE_HEARTBEAT="${FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT:-1}"
# 与上面等比例放大（2400/3600 = 3200/4800），心跳后仍留约 26 分钟收尾。
IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC="${FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC:-3200}"
PRICING_CURRENCY="${FAMOU_PRICING_CURRENCY:-USD}"
INPUT_PRICE_PER_MILLION="${FAMOU_INPUT_PRICE_PER_MILLION:-}"
CACHE_CREATION_PRICE_PER_MILLION="${FAMOU_CACHE_CREATION_PRICE_PER_MILLION:-}"
CACHE_READ_PRICE_PER_MILLION="${FAMOU_CACHE_READ_PRICE_PER_MILLION:-}"
OUTPUT_PRICE_PER_MILLION="${FAMOU_OUTPUT_PRICE_PER_MILLION:-}"
PRICING_SOURCE="${FAMOU_PRICING_SOURCE:-}"
PRICING_EFFECTIVE_AT="${FAMOU_PRICING_EFFECTIVE_AT:-}"
IDEA_RUNTIME="${FAMOU_IDEA_RUNTIME:-${RUNTIME}}"
IMPLEMENT_RUNTIME="${FAMOU_IMPLEMENT_RUNTIME:-${RUNTIME}}"
IDEA_MODEL="${FAMOU_IDEA_MODEL:-${MODEL}}"
IMPLEMENT_MODEL="${FAMOU_IMPLEMENT_MODEL:-${MODEL}}"
CODE_RUNTIME_DIR="${FAMOU_CODE_RUNTIME_DIR:-}"
# 下面两个走环境变量，理由与 Idea Judge 辩论一致：位置参数契约已有 29 个，
# 不再继续拉长。默认值即当前生产行为，只有 resume 重跑批次会关掉。
PAIRWISE_IMPROVE_SEARCH="${FAMOU_PAIRWISE_IMPROVE_SEARCH:-1}"
# 出分后还让不让同一个 actor 就地 refine。关掉＝改进必须回 IdeaAgent 看图。
REFINE_AFTER_EVALUATION="${FAMOU_REFINE_AFTER_EVALUATION:-1}"
# 单个方案允许 debug 的总次数。空＝不设独立上限（历史行为）。
MAX_DEBUG_ATTEMPTS="${FAMOU_MAX_DEBUG_ATTEMPTS:-}"
IDEA_GENERATION="${FAMOU_IDEA_GENERATION:-1}"

CHANNEL_DIR="${RUN_DIR}/controller/evaluator_channel"
TRUSTED_DIR="${RUN_DIR}/trusted"
AGENT_HOME="${RUN_DIR}/agent_home"
PUBLIC_PYTHONPATH="${RUN_DIR}/famou-scientist"
TRUSTED_PYTHONPATH="${TRUSTED_DIR}/famou-scientist"
TRUSTED_TASK_DIR="${TRUSTED_DIR}/naturebench/data/naturebench_data/tasks/${TASK_ID}"
EVALUATOR_LOG="${TRUSTED_DIR}/logs/evaluator.log"
EVALUATOR_PID=""
EVALUATOR_DRAIN_TIMEOUT_SEC="${EVALUATOR_DRAIN_TIMEOUT_SEC:-300}"

if [[ "$(id -u)" != "0" ]]; then
    echo "NatureBench task supervisor must start as root" >&2
    exit 2
fi
if [[ -z "${MODEL}" || "${MODEL}" == "-" ]]; then
    echo "an explicit Agent model is required" >&2
    exit 2
fi
for path in "${TRUSTED_DIR}" "${TRUSTED_TASK_DIR}" "${CHANNEL_DIR}"; do
    if [[ ! -d "${path}" ]]; then
        echo "required task-local path is missing: ${path}" >&2
        exit 2
    fi
done
if [[ "$(stat -c '%a' "${TRUSTED_DIR}")" != "700" ]]; then
    echo "trusted directory must have mode 700: ${TRUSTED_DIR}" >&2
    exit 2
fi

# 评测器自带的原生二进制补上可执行位。
#
# s42256-023-00712-7 的 `evaluation/qvina02` 是一个静态链接的 ELF，但落到这里时
# 是 0644——执行位在上游打包/解包的路上丢了。于是 evaluator 里的
# `subprocess.run([QVINA_BIN, ...])` 抛 PermissionError(13)，而那一段外面套的是
# `except (subprocess.TimeoutExpired, Exception): return None`，异常被整个吞掉，
# 每个分子的 Vina Score 都变成 None，aggregate 恒为 −1.0。**线上 18 次 attempt
# 全中，日志里一个字都没有**：QED/SA/Diversity 都是真数，只有 Vina Score 是 null。
#
# evaluator 自己有个回退 `shutil.which("qvina02")`，但它只在**文件不存在**时才触发；
# 文件存在却不可执行正好绕过它。
#
# 写成对 ELF 的通用扫描而不是给这道题写死路径：现在全 90 题只有这一个原生工具，
# 但下次多一个，我们不会再赔掉一整批 attempt 才发现。以 root 跑，改的是本次作业的
# 私有副本（`${TRUSTED_DIR}` 下），不动上游数据集。
while IFS= read -r binary; do
    if [[ ! -x "${binary}" ]] && head -c 4 "${binary}" | grep -q $'\x7fELF'; then
        chmod +x "${binary}"
        echo "fixed missing exec bit: ${binary}"
    fi
done < <(find "${TRUSTED_TASK_DIR}/evaluation" -maxdepth 2 -type f ! -name '*.py' -size +10k 2>/dev/null)

cleanup() {
    # EXIT 时只做最后兜底。正常路径会先让 worker 看到 CLIENT_DONE 并自行排空；
    # 只有异常或信号路径才需要在这里终止仍存活的可信进程。
    if [[ -n "${EVALUATOR_PID}" ]] && kill -0 "${EVALUATOR_PID}" 2>/dev/null; then
        kill -TERM "${EVALUATOR_PID}" 2>/dev/null || true
        wait "${EVALUATOR_PID}" 2>/dev/null || true
    fi
    rm -f "${AGENT_HOME}/.claude/settings.json"
}

signal_exit() {
    # Supervisor 收到 fm-job 终止信号时不再接受新工作，并清理完整子进程。
    local exit_code="$1"
    exit "${exit_code}"
}

trap cleanup EXIT
trap 'signal_exit 130' INT
trap 'signal_exit 143' TERM

evaluator_args=(
    --task-dir "${TRUSTED_TASK_DIR}"
    --output-dir "${RUN_DIR}/workspace/output"
    --channel-dir "${CHANNEL_DIR}"
    --private-key "${TRUSTED_DIR}/private_key.pem"
    --agent-log-dir "${RUN_DIR}/controller/evaluator_agent_logs"
    --trusted-evidence-dir "${TRUSTED_DIR}/raw_evaluator_artifacts"
    --evaluation-timeout-sec "${EVALUATION_TIMEOUT_SEC}"
    --idle-timeout-sec 86400
)
if [[ "${VALIDITY_JUDGE}" == "1" ]]; then
    evaluator_args+=(
        --run-dir "${RUN_DIR}"
        --agent-runtime "${RUNTIME}"
        --judge-settings "${TRUSTED_DIR}/judge_settings.json"
        --judge-model "${JUDGE_MODEL}"
        --judge-timeout-sec "${JUDGE_TIMEOUT_SEC}"
    )
fi

mkdir -p "${RUN_DIR}/results" "${TRUSTED_DIR}/logs"
chmod 700 "${TRUSTED_DIR}/logs"
PYTHONPATH="${TRUSTED_PYTHONPATH}" \
    python -m famou_scientist.loop.integrations.naturebench.evaluator_worker \
    "${evaluator_args[@]}" \
    >"${EVALUATOR_LOG}" 2>&1 &
EVALUATOR_PID=$!

for _ in $(seq 1 600); do
    if [[ -f "${CHANNEL_DIR}/EVALUATOR_READY.json" ]]; then
        break
    fi
    if ! kill -0 "${EVALUATOR_PID}" 2>/dev/null; then
        echo "task-local evaluator exited during startup" >&2
        # 只由 root Supervisor 把启动错误送到 fm-job 日志；该文件本身不进入
        # Agent 可读 results/。
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
if [[ -n "${CODE_RUNTIME_DIR}" ]]; then
    if [[ ! -x "${CODE_RUNTIME_DIR}/bin/zulu" || \
          ! -f "${CODE_RUNTIME_DIR}/comate-engine/bin/comate.js" ]]; then
        echo "staged z-code runtime is incomplete: ${CODE_RUNTIME_DIR}" >&2
        exit 2
    fi
    export COMATE_ENGINE_PATH="${CODE_RUNTIME_DIR}/comate-engine"
    export PATH="${CODE_RUNTIME_DIR}/bin:${PATH}"
fi
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
    --agent-runtime "${RUNTIME}"
    --idea-runtime "${IDEA_RUNTIME}"
    --implement-runtime "${IMPLEMENT_RUNTIME}"
    --idea-model "${IDEA_MODEL}"
    --implement-model "${IMPLEMENT_MODEL}"
    --implement-agent-timeout-sec "${IMPLEMENT_TIMEOUT_SEC}"
    --implement-deadline-heartbeat-after-sec "${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC}"
    --model "${MODEL}"
    --benchmark-adapter naturebench
    --evaluator-adapter naturebench
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
)
if [[ "${AGENT_PROCESS_MEMORY_LIMIT_GIB}" != "-" && -n "${AGENT_PROCESS_MEMORY_LIMIT_GIB}" ]]; then
    args+=(--agent-process-memory-limit-gib "${AGENT_PROCESS_MEMORY_LIMIT_GIB}")
fi
# Idea 图同样走环境变量传参。默认关闭：benchmark 工作流历史上不落 idea→idea
# 派生边，开着会改变所有既有批次的行为。
IDEA_GRAPH="${FAMOU_IDEA_GRAPH:-0}"
if [[ "${IDEA_GRAPH}" == "1" || "${IDEA_GRAPH}" == "true" ]]; then
    args+=(--idea-graph)
    # 图的 schema 版本。默认 v1（现状：IDEAS.md，单父、无分数）；v2 是方案演化图
    # （GRAPH.md，多父 DAG + 节点带最好分 + 算子校验）。非法值由 harness 抛错，
    # 不在这里悄悄钳成默认——拼错的版本号安静跑成对照臂会毁掉整批配对实验。
    args+=(--idea-graph-version "${FAMOU_IDEA_GRAPH_VERSION:-v1}")
fi
# Idea Judge 辩论走环境变量传参，避免继续拉长本脚本已有的位置参数契约。
IDEA_DEBATE="${FAMOU_IDEA_DEBATE:-0}"
if [[ "${IDEA_DEBATE}" == "1" || "${IDEA_DEBATE}" == "true" ]]; then
    args+=(--idea-debate)
    args+=(--idea-debate-mode "${FAMOU_IDEA_DEBATE_MODE:-respond}")
    args+=(--idea-debate-max-rounds "${FAMOU_IDEA_DEBATE_MAX_ROUNDS:-1}")
    args+=(--idea-debate-min-elapsed-sec "${FAMOU_IDEA_DEBATE_MIN_ELAPSED_SEC:-3600}")
    args+=(--idea-debate-min-evaluated-attempts \
        "${FAMOU_IDEA_DEBATE_MIN_EVALUATED_ATTEMPTS:-1}")
    args+=(--idea-debate-max-turns "${FAMOU_IDEA_DEBATE_MAX_TURNS:-30}")
    args+=(--idea-debate-timeout-sec "${FAMOU_IDEA_DEBATE_TIMEOUT_SEC:-1800}")
    if [[ "${FAMOU_IDEA_DEBATE_ALLOW_CROSS_TASK_ONLY:-0}" == "1" ]]; then
        args+=(--idea-debate-allow-cross-task-only)
    fi
    if [[ "${FAMOU_IDEA_DEBATE_EMIT_PAIR:-0}" == "1" ]]; then
        args+=(--idea-debate-emit-pair)
    fi
    if [[ -n "${FAMOU_IDEA_JUDGE_MODEL:-}" && "${FAMOU_IDEA_JUDGE_MODEL}" != "-" ]]; then
        args+=(--idea-judge-model "${FAMOU_IDEA_JUDGE_MODEL}")
    fi
fi
pricing_count=0
for value in \
    "${INPUT_PRICE_PER_MILLION}" \
    "${CACHE_CREATION_PRICE_PER_MILLION}" \
    "${CACHE_READ_PRICE_PER_MILLION}" \
    "${OUTPUT_PRICE_PER_MILLION}"; do
    if [[ -n "${value}" ]]; then
        pricing_count=$((pricing_count + 1))
    fi
done
if [[ "${pricing_count}" -ne 0 && "${pricing_count}" -ne 4 ]]; then
    echo "all four token prices must be configured together" >&2
    exit 2
fi
if [[ "${pricing_count}" -eq 4 ]]; then
    args+=(
        --pricing-currency "${PRICING_CURRENCY}"
        --input-price-per-million "${INPUT_PRICE_PER_MILLION}"
        --cache-creation-price-per-million "${CACHE_CREATION_PRICE_PER_MILLION}"
        --cache-read-price-per-million "${CACHE_READ_PRICE_PER_MILLION}"
        --output-price-per-million "${OUTPUT_PRICE_PER_MILLION}"
    )
    if [[ -n "${PRICING_SOURCE}" ]]; then
        args+=(--pricing-source "${PRICING_SOURCE}")
    fi
    if [[ -n "${PRICING_EFFECTIVE_AT}" ]]; then
        args+=(--pricing-effective-at "${PRICING_EFFECTIVE_AT}")
    fi
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
if [[ "${PAIRWISE_IMPROVE_SEARCH}" == "1" ]]; then
    args+=(--pairwise-improve-search)
else
    args+=(--no-pairwise-improve-search)
fi
if [[ "${REFINE_AFTER_EVALUATION}" == "1" ]]; then
    args+=(--refine-after-evaluation)
else
    args+=(--no-refine-after-evaluation)
fi
if [[ -n "${MAX_DEBUG_ATTEMPTS}" ]]; then
    args+=(--max-debug-attempts-per-actor "${MAX_DEBUG_ATTEMPTS}")
fi
if [[ "${IDEA_GENERATION}" == "1" ]]; then
    args+=(--idea-generation)
else
    args+=(--no-idea-generation)
fi
if [[ "${VALIDITY_JUDGE}" == "1" ]]; then
    args+=(--finalize-evaluation)
else
    args+=(--no-finalize-evaluation)
fi

set +e
python -m famou_scientist "${args[@]}" \
    > >(tee "${RUN_DIR}/results/agent.log") \
    2> >(tee "${RUN_DIR}/results/agent.stderr.log" >&2)
CONTROLLER_RC=$?
set -e

# FileEvaluatorClient.close() 正常会创建该标记。Controller 若在初始化或异常路径
# 提前退出，则由可信 Supervisor 补写，确保 worker 处理完已经落盘的请求后退出。
if [[ ! -f "${CHANNEL_DIR}/CLIENT_DONE.json" ]]; then
    done_tmp="${CHANNEL_DIR}/.CLIENT_DONE.json.tmp.$$"
    printf '{"source":"task_supervisor","controller_returncode":%s}\n' \
        "${CONTROLLER_RC}" >"${done_tmp}"
    mv "${done_tmp}" "${CHANNEL_DIR}/CLIENT_DONE.json"
fi

# 不在 EXIT trap 中立即 kill evaluator。等待它观察 CLIENT_DONE、处理完请求并写出
# EVALUATOR_DONE；这样墙钟截止后的评测排空也属于同一个 fm-job 的正常生命周期。
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
