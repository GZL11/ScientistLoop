#!/usr/bin/env bash
# 一键提交 NatureBench：准备权限分层目录后启动单个任务 fm-job。
#
# 完整流程：
#
#   NatureBench 公开 problem + Famou 源码
#                    │
#                    ▼
#       1. 准备 Agent 隔离运行目录
#                    │
#                    ▼
#       2. 创建评测响应签名密钥
#                    │
#                    ▼
#       3. 单个 Task fm-job
#       ├── 可信 Evaluator 进程
#       └── 非特权 Agent 子进程
#
# 这个脚本只负责上述编排；任务内生命周期由 task_entrypoint.sh 监督。
set -euo pipefail


# ── 配置区：均可通过同名环境变量覆盖 ────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAMOU_SOURCE="${FAMOU_SOURCE:-$(cd "${SCRIPT_DIR}/../../../../.." && pwd)}"
NATUREBENCH_ROOT="${NATUREBENCH_ROOT:-/path/to/workspace/opensource/NatureBench}"
FM_JOB_BIN="${FM_JOB_BIN:-fm-job}"

TASK_ID="${TASK_ID:-s43588-024-00689-2}"
IMAGE="${IMAGE:-<你的镜像仓库>/famou-public/naturebench-${TASK_ID}:v1}"
AGENT_RUNTIME="${AGENT_RUNTIME:-claude}"
MODEL="${MODEL:-glm-5.2}"
IDEA_RUNTIME="${IDEA_RUNTIME:-${AGENT_RUNTIME}}"
IMPLEMENT_RUNTIME="${IMPLEMENT_RUNTIME:-${AGENT_RUNTIME}}"
IDEA_MODEL="${IDEA_MODEL:-${MODEL}}"
IMPLEMENT_MODEL="${IMPLEMENT_MODEL:-${MODEL}}"
IDEA_PROMPT_VERSION="${IDEA_PROMPT_VERSION:-v1}"
IMPLEMENT_PROMPT_VERSION="${IMPLEMENT_PROMPT_VERSION:-v1}"
KIMI_CODE_CONFIG="${KIMI_CODE_CONFIG:-${HOME}/.kimi-code/config.toml}"
CODE_RUNTIME_SOURCE="${CODE_RUNTIME_SOURCE:-}"
CODE_RUNTIME_DIR=""
TASK_CODE_RUNTIME_DIR=""
# HuggingFace 默认使用可访问的镜像；代理地址仍由提交者在环境中显式提供，
# 避免把带凭据的网络配置写入仓库或运行配置文件。
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-0}"
# 价格只绑定已确认的 GLM-5.2；换模型时默认不重算，避免误套价格。
if [[ "${MODEL}" == "glm-5.2" || "${MODEL}" == "zai-org/glm-5.2" ]]; then
    PRICING_CURRENCY="${PRICING_CURRENCY:-USD}"
    INPUT_PRICE_PER_MILLION="${INPUT_PRICE_PER_MILLION:-1.4}"
    CACHE_CREATION_PRICE_PER_MILLION="${CACHE_CREATION_PRICE_PER_MILLION:-1.4}"
    CACHE_READ_PRICE_PER_MILLION="${CACHE_READ_PRICE_PER_MILLION:-0.26}"
    OUTPUT_PRICE_PER_MILLION="${OUTPUT_PRICE_PER_MILLION:-4.4}"
    PRICING_SOURCE="${PRICING_SOURCE:-user_confirmed}"
    PRICING_EFFECTIVE_AT="${PRICING_EFFECTIVE_AT:-2026-08-11}"
else
    PRICING_CURRENCY="${PRICING_CURRENCY:-USD}"
    INPUT_PRICE_PER_MILLION="${INPUT_PRICE_PER_MILLION:-}"
    CACHE_CREATION_PRICE_PER_MILLION="${CACHE_CREATION_PRICE_PER_MILLION:-}"
    CACHE_READ_PRICE_PER_MILLION="${CACHE_READ_PRICE_PER_MILLION:-}"
    OUTPUT_PRICE_PER_MILLION="${OUTPUT_PRICE_PER_MILLION:-}"
    PRICING_SOURCE="${PRICING_SOURCE:-}"
    PRICING_EFFECTIVE_AT="${PRICING_EFFECTIVE_AT:-}"
fi
# 缺省不限制全局尝试/正式评分次数；兼容旧的 ITERATIONS 显式配置。
MAX_BENCHMARK_ATTEMPTS="${MAX_BENCHMARK_ATTEMPTS:-${ITERATIONS:--}}"
MAX_WALL_TIME_HOURS="${MAX_WALL_TIME_HOURS:-4}"
STARTUP_GRACE_SEC="${STARTUP_GRACE_SEC:-900}"
MAX_IMPLEMENT_TURNS="${MAX_IMPLEMENT_TURNS:-3}"
MAX_RUN_ATTEMPTS="${MAX_RUN_ATTEMPTS:-6}"
IDEA_CONCURRENCY="${IDEA_CONCURRENCY:-1}"
IMPLEMENT_CONCURRENCY="${IMPLEMENT_CONCURRENCY:-1}"
EVALUATION_CONCURRENCY="${EVALUATION_CONCURRENCY:-3}"
IDEA_QUEUE_CAPACITY="${IDEA_QUEUE_CAPACITY:-3}"
# 评测配额按任务覆盖。**必须在下面那几个派生预算之前做完**：
# EVALUATION_DRAIN_BUDGET_SEC / FINALIZATION_GRACE_SEC / HARD_TIMEOUT_SEC 都是
# 拿 EVALUATION_TIMEOUT_SEC 算出来的，改晚了外层 timeout 仍按 3600s 收口，
# 于是评测刚放宽就被 pod 硬超时截断。
#
# 只在提交者没有显式设置同名环境变量时生效（用 ${VAR+set} 而不是 -n 判断，
# 显式写 EVALUATION_TIMEOUT_SEC=3600 也算显式，不该被表里的值改掉）。
EVALUATION_QUOTA_FILE="${EVALUATION_QUOTA_FILE:-${SCRIPT_DIR}/evaluation_quota.json}"
apply_evaluation_quota() {
    local key overridden
    for key in evaluation_timeout_sec evaluation_queue_capacity; do
        case "${key}" in
            evaluation_timeout_sec) overridden="${EVALUATION_TIMEOUT_SEC+set}" ;;
            evaluation_queue_capacity) overridden="${EVALUATION_QUEUE_CAPACITY+set}" ;;
        esac
        [[ -n "${overridden}" ]] && continue
        local value
        value="$(
            TASK_ID="${TASK_ID}" QUOTA_KEY="${key}" \
            python3 - "${EVALUATION_QUOTA_FILE}" <<'PY'
import json
import os
import sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as handle:
        table = json.load(handle)
except FileNotFoundError:
    raise SystemExit(0)
entry = (table.get("tasks") or {}).get(os.environ["TASK_ID"]) or {}
value = entry.get(os.environ["QUOTA_KEY"])
if isinstance(value, int) and value > 0:
    print(value)
PY
        )"
        [[ -n "${value}" ]] || continue
        case "${key}" in
            evaluation_timeout_sec)
                EVALUATION_TIMEOUT_SEC="${value}"
                EVALUATION_QUOTA_APPLIED+=("evaluation_timeout_sec=${value}")
                ;;
            evaluation_queue_capacity)
                EVALUATION_QUEUE_CAPACITY="${value}"
                EVALUATION_QUOTA_APPLIED+=("evaluation_queue_capacity=${value}")
                ;;
        esac
    done
}
EVALUATION_QUOTA_APPLIED=()
apply_evaluation_quota
EVALUATION_QUEUE_CAPACITY="${EVALUATION_QUEUE_CAPACITY:-3}"
EXPERIMENT_TIMEOUT_SEC="${EXPERIMENT_TIMEOUT_SEC:-3600}"
# 单次 Implement 激活上限。20260920 实测：3600 秒下 43/181 次 attempt 跑满被掐，
# 心跳送到时代码还没跑通，收尾那 19.5 分钟全被 smoke 吃掉。放到 80 分钟，心跳等
# 比例后移。详见 .famou/naturebench-submit-batches/20260920-graph-v2-ab-10x2/HEARTBEAT_FINDINGS.md
IMPLEMENT_TIMEOUT_SEC="${IMPLEMENT_TIMEOUT_SEC:-4800}"
IMPLEMENT_DEADLINE_HEARTBEAT="${IMPLEMENT_DEADLINE_HEARTBEAT:-1}"
IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC="${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC:-3200}"
EVALUATION_TIMEOUT_SEC="${EVALUATION_TIMEOUT_SEC:-3600}"
JUDGE_TIMEOUT_SEC="${JUDGE_TIMEOUT_SEC:-3600}"
EVALUATOR_REQUEST_TIMEOUT_SEC="${EVALUATOR_REQUEST_TIMEOUT_SEC:-$((EVALUATION_TIMEOUT_SEC + 300))}"
# 4 小时只约束 Idea/Implement admission。截止时 Evaluation Queue 最多有
# EVALUATION_QUEUE_CAPACITY 条；按最坏串行执行 canonical run 和官方 evaluator，
# 再给最终 Judge 与启动过程留出时间，避免外层 timeout 提前截断合法排空。
RESEARCH_BUDGET_SEC="$(awk -v hours="${MAX_WALL_TIME_HOURS}" 'BEGIN { printf "%d", hours * 3600 }')"
EVALUATION_DRAIN_BUDGET_SEC="$((EVALUATION_QUEUE_CAPACITY * (EXPERIMENT_TIMEOUT_SEC + EVALUATION_TIMEOUT_SEC)))"
FINALIZATION_GRACE_SEC="${FINALIZATION_GRACE_SEC:-$((EVALUATION_DRAIN_BUDGET_SEC + JUDGE_TIMEOUT_SEC + 300))}"
HARD_TIMEOUT_SEC="${HARD_TIMEOUT_SEC:-$((RESEARCH_BUDGET_SEC + FINALIZATION_GRACE_SEC + STARTUP_GRACE_SEC))}"
TIME_AWARE_IDEA_RANKING="${TIME_AWARE_IDEA_RANKING:-1}"
IDEA_RANK_TRIGGER_REMAINING_SEC="${IDEA_RANK_TRIGGER_REMAINING_SEC:-3600}"
IDEA_RANK_MODEL="${IDEA_RANK_MODEL:-${MODEL}}"
# Idea 图：benchmark 工作流默认不落 idea→idea 派生边（expbank/IDEAS.md 恒为空），
# A/B 对照时显式打开。默认必须是 0——本脚本是所有历史批次共用的提交入口。
IDEA_GRAPH="${IDEA_GRAPH:-0}"
# 图的 schema 版本：v1 = 现状（IDEAS.md，单父、无分数），v2 = 方案演化图
# （GRAPH.md，多父 DAG + 节点带最好分 + 算子校验）。默认必须是 v1——本脚本是所有
# 历史批次共用的提交入口，默认改 v2 会静默改变后续一切 run 的行为。
IDEA_GRAPH_VERSION="${IDEA_GRAPH_VERSION:-v1}"
# Idea Judge 辩论：默认关闭，A/B 对照时显式打开。判官模型留空则继承 Idea Agent。
IDEA_DEBATE="${IDEA_DEBATE:-0}"
IDEA_DEBATE_MODE="${IDEA_DEBATE_MODE:-respond}"
IDEA_DEBATE_MAX_ROUNDS="${IDEA_DEBATE_MAX_ROUNDS:-1}"
IDEA_DEBATE_MIN_ELAPSED_SEC="${IDEA_DEBATE_MIN_ELAPSED_SEC:-3600}"
IDEA_DEBATE_MIN_EVALUATED_ATTEMPTS="${IDEA_DEBATE_MIN_EVALUATED_ATTEMPTS:-1}"
IDEA_DEBATE_ALLOW_CROSS_TASK_ONLY="${IDEA_DEBATE_ALLOW_CROSS_TASK_ONLY:-0}"
IDEA_DEBATE_EMIT_PAIR="${IDEA_DEBATE_EMIT_PAIR:-0}"
IDEA_DEBATE_MAX_TURNS="${IDEA_DEBATE_MAX_TURNS:-30}"
IDEA_DEBATE_TIMEOUT_SEC="${IDEA_DEBATE_TIMEOUT_SEC:-1800}"
IDEA_JUDGE_MODEL="${IDEA_JUDGE_MODEL:--}"
IDEA_RANK_MAX_TURNS="${IDEA_RANK_MAX_TURNS:-30}"
IDEA_RANK_TIMEOUT_SEC="${IDEA_RANK_TIMEOUT_SEC:-1800}"
AGENT_CPU="${AGENT_CPU:-30}"
AGENT_MEMORY_GIB="${AGENT_MEMORY_GIB:-128}"
AGENT_PROCESS_MEMORY_LIMIT_GIB="${AGENT_PROCESS_MEMORY_LIMIT_GIB:--}"
AGENT_UID="${AGENT_UID:-10001}"
AGENT_GID="${AGENT_GID:-10001}"
RESOURCE_TIER="${RESOURCE_TIER:-auto}"
VALIDITY_JUDGE="${VALIDITY_JUDGE:-1}"
JUDGE_MODEL="${JUDGE_MODEL:--}"
# Agent-facing ExpBank is restricted to trusted validity verdicts.  The
# current task is always excluded from its Run-local snapshot to prevent
# self-reuse of historical solutions.
CROSS_TASK_JUDGE_MODEL="${CROSS_TASK_JUDGE_MODEL:-gpt-5.5}"
# CROSS_TASK_EXPBANK=0 seeds an entry-less snapshot: the control arm of the
# cross-task ExpBank A/B.  The directory still exists so the Run takes the
# same code path; only the catalog is empty.
CROSS_TASK_EXPBANK="${CROSS_TASK_EXPBANK:-1}"
# Seed the Run snapshot from a frozen copy instead of the live bank.  Required
# for A/B batches: the live bank keeps absorbing finished Runs, so arms
# launched hours apart would otherwise read different banks.  Empty = live.
CROSS_TASK_SEED_BANK_ROOT="${CROSS_TASK_SEED_BANK_ROOT:-}"
# 任务级过滤方向。cross（默认）= 剔除本任务自己的历史，Run 是一次独立搜索；
# self = 反过来，快照里**只**留本任务自己的历史复盘，别的任务一条不给。后者是
# 同任务自身经验 A/B（20260911-selftask-expbank-ab-15x3）的处理臂：跨任务那轮
# 测出来是 null，要把迁移距离缩到最短再测一次。两条臂的对照臂都是
# CROSS_TASK_EXPBANK=0（空库），所以两个实验可以直接横向比。
CROSS_TASK_EXPBANK_SCOPE="${CROSS_TASK_EXPBANK_SCOPE:-cross}"
# RESUME_RUN=1：不新建 Run，而是重开一个已按墙钟结束的 Run。
# 此时 problem / trusted / 跨任务快照都已就位，prepare_run.py 会因目标已存在而
# 报 FileExistsError，所以整个首次 staging 阶段要换成 resume_run.py：
# 刷新 staged 源码（老 Run 里那份不含新开关）、清 evaluator 通道标记、重放已实现过的 Idea。
RESUME_RUN="${RESUME_RUN:-0}"
PAIRWISE_IMPROVE_SEARCH="${PAIRWISE_IMPROVE_SEARCH:-1}"
# 出分后还让不让同一个 ImplementActor 就地改进（refine）。默认 1＝历史行为。
# 演化图 v2 要求关掉：改进必须回 IdeaAgent 看图、选 operator + parents，
# 作为新的 exploit 节点入队，这样才进得了主读数。
REFINE_AFTER_EVALUATION="${REFINE_AFTER_EVALUATION:-1}"
# 单个方案允许 debug 的总次数。空＝不设独立上限（历史行为，实际只受
# MAX_RUN_ATTEMPTS 和墙钟约束）。关掉 refine 之后这是唯一还能让 actor
# 被再唤醒的理由，所以两个开关通常一起设。
MAX_DEBUG_ATTEMPTS="${MAX_DEBUG_ATTEMPTS:-}"
IDEA_GENERATION="${IDEA_GENERATION:-1}"
# 小任务可复制公开 problem；超大任务把 RUN_DIR 放到 NatureBench 同盘后，
# auto 会建立 root-owned 只读硬链接，避免重复复制数百 GiB 数据。
PROBLEM_STAGING_MODE="${PROBLEM_STAGING_MODE:-auto}"
PROBLEM_SNAPSHOT_SOURCE="${PROBLEM_SNAPSHOT_SOURCE:-}"
PROBLEM_SNAPSHOT_MANIFEST="${PROBLEM_SNAPSHOT_MANIFEST:-}"
PROBLEM_SNAPSHOT_LINK="${PROBLEM_SNAPSHOT_LINK:-0}"
MANIFEST_HASH_MAX_FILE_BYTES="${MANIFEST_HASH_MAX_FILE_BYTES:-1048576}"
MANIFEST_HASH_TOTAL_BUDGET_BYTES="${MANIFEST_HASH_TOTAL_BUDGET_BYTES:-67108864}"

RUN_ID="${RUN_ID:-${TASK_ID}-$(date +%Y%m%d-%H%M%S)}"
# 作业名的附加标识，拼在 `famou-nb-<task>` 后面。
#
# fm-job 在 prefix 后面补的是**时间戳到秒**，所以默认作业名只有 task 这一个变量。
# 同一道题的两个作业在同一秒落地，名字逐字相同，第二个直接被 k8s 拒掉：
#   Error: failed to create Job: jobs.batch "famou-nb-...-155355" already exists
# 20260915 那批 A/B 就是这么死的——20 个作业只成了 11 个，而且**失败全部集中在
# 一条臂**，10 对里只剩 2 对完整。注意 `RUN_ID` 里带臂标识救不了：作业名从来不用
# RUN_ID，两者是两套命名。
#
# A/B 批次必须传这个变量（如 `gv0`、`gv1`），把臂写进名字，从结构上消掉同秒撞名。
# 默认空 ⇒ 作业名与历史逐字节一致，老批次零改动。
JOB_NAME_TAG="${JOB_NAME_TAG:-}"
if [[ -n "${JOB_NAME_TAG}" && ! "${JOB_NAME_TAG}" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
    # k8s Job 名是 DNS-1123 标签，非法字符会在 fm-job 那边报一个很难读的错，
    # 不如在这里就说清楚。
    echo "JOB_NAME_TAG 只能是小写字母、数字和连字符（DNS-1123）：${JOB_NAME_TAG}" >&2
    exit 2
fi
JOB_NAME_PREFIX="famou-nb-${TASK_ID}${JOB_NAME_TAG:+-${JOB_NAME_TAG}}"
if (( ${#JOB_NAME_PREFIX} > 46 )); then
    # fm-job 还要追加 `-YYYYmmdd-HHMMSS`（16 字符），总长不能超过 DNS-1123 的 63。
    echo "作业名前缀过长（${#JOB_NAME_PREFIX} > 46），缩短 JOB_NAME_TAG：${JOB_NAME_PREFIX}" >&2
    exit 2
fi
RUN_DIR="${RUN_DIR:-${FAMOU_SOURCE}/.famou/naturebench-runs/${RUN_ID}}"
# 复用旧 Run 的只读题面快照时，新 Run 可以放在旧 Run 的 reruns/ 下，
# fm-job 只需挂载这个共同父目录，不必暴露整个 NatureBench 运行集合。
FMJOB_MOUNT_HOST_DIR="${FMJOB_MOUNT_HOST_DIR:-${RUN_DIR}}"
TRUSTED_DIR="${RUN_DIR}/trusted"
CLAUDE_SETTINGS_SOURCE="${CLAUDE_SETTINGS_SOURCE:-${HOME}/.claude/settings.json}"

# fm-job --subpath 相对于整个 CFS 根目录，而不是当前用户的目录。
CFS_OWNER_PREFIX="${CFS_OWNER_PREFIX:-/path/to/workspace/}"
FMJOB_MOUNT_PREFIX="${FMJOB_MOUNT_PREFIX:-/path/to/workspace}"


resolve_resource_tier() {
    # 根据 NatureBench 官方 task-set 确定任务计算档位。
    if [[ "${RESOURCE_TIER}" != "auto" ]]; then
        return
    fi
    local tier
    for tier in cpu gpu_low gpu_high; do
        if grep -Fqx "${TASK_ID}" "${NATUREBENCH_ROOT}/task-set/${tier}.txt"; then
            RESOURCE_TIER="${tier}"
            return
        fi
    done
    echo "task is absent from NatureBench resource task-sets: ${TASK_ID}" >&2
    exit 2
}


resolve_agent_gpu() {
    # 优先使用显式 AGENT_GPU，否则按官方资源档位申请 GPU。
    if [[ -n "${AGENT_GPU:-}" ]]; then
        return
    fi
    case "${RESOURCE_TIER}" in
        cpu)
            AGENT_GPU=0
            ;;
        gpu_low|gpu_high)
            AGENT_GPU=1
            ;;
        *)
            echo "unsupported NatureBench resource tier: ${RESOURCE_TIER}" >&2
            exit 2
            ;;
    esac
}


stage() {
    printf '\n[%s/3] %s\n' "$1" "$2"
}


prepare_agent_run() {
    if [[ "${RESUME_RUN}" == "1" ]]; then
        stage 1 "重开已结束的 Run（刷新源码、清通道标记、重放被排序 Idea）"
        if [[ ! -d "${RUN_DIR}" ]]; then
            echo "RESUME_RUN=1 requires an existing run dir: ${RUN_DIR}" >&2
            exit 2
        fi
        local resume_args=(
            --run-dir "${RUN_DIR}"
            --famou-source "${FAMOU_SOURCE}"
            --agent-uid "${AGENT_UID}"
            --agent-gid "${AGENT_GID}"
        )
        if [[ -f "${CLAUDE_SETTINGS_SOURCE}" ]]; then
            resume_args+=(--claude-settings "${CLAUDE_SETTINGS_SOURCE}")
        else
            echo "Claude settings not found: ${CLAUDE_SETTINGS_SOURCE}" >&2
            exit 2
        fi
        if [[ "${VALIDITY_JUDGE}" != "1" ]]; then
            resume_args+=(--no-judge-settings)
        fi
        python "${SCRIPT_DIR}/resume_run.py" "${resume_args[@]}"
        return 0
    fi
    stage 1 "准备不含 GT 和 evaluator 的 Agent 运行目录"

    # Seed this Run's public, read-only cross-task snapshot before Agents start.
    #
    # 这里**不再合并 outbox**。合并要遍历全部 run 目录（500+）并对每条记录抢一次
    # 库锁，是批次级维护动作；挂在每次提交上时，40 个并发提交会在 NFS 文件锁上排成
    # 车队——实测 39 个进程卡在 nfs4_retry_setlk、零 IO 进展、半小时一个 Run 目录
    # 都建不出来。合并改由批次脚本或定时任务显式执行：
    #
    #   python sync_cross_task_expbank.py --runs-root <runs> --bank-root <bank>
    #
    # 设 CROSS_TASK_MERGE_ON_SUBMIT=1 可恢复旧行为（单个提交、想立刻回流时用）。
    if [[ "${CROSS_TASK_MERGE_ON_SUBMIT:-0}" == "1" ]]; then
        python "${SCRIPT_DIR}/sync_cross_task_expbank.py" \
            --runs-root "${FAMOU_SOURCE}/.famou/naturebench-runs" \
            --bank-root "${FAMOU_SOURCE}/.famou/cross_task_expbank"
    fi

    if [[ -z "${MODEL}" || "${MODEL}" == "-" ]]; then
        echo "MODEL must be explicit; NatureBench defaults to glm-5.2" >&2
        exit 2
    fi

    local args=(
        --naturebench-root "${NATUREBENCH_ROOT}"
        --task-id "${TASK_ID}"
        --famou-source "${FAMOU_SOURCE}"
        --run-dir "${RUN_DIR}"
        --agent-uid "${AGENT_UID}"
        --agent-gid "${AGENT_GID}"
        --problem-staging-mode "${PROBLEM_STAGING_MODE}"
        --manifest-hash-max-file-bytes "${MANIFEST_HASH_MAX_FILE_BYTES}"
        --manifest-hash-total-budget-bytes "${MANIFEST_HASH_TOTAL_BUDGET_BYTES}"
    )
    if [[ -n "${PROBLEM_SNAPSHOT_SOURCE}" || -n "${PROBLEM_SNAPSHOT_MANIFEST}" ]]; then
        if [[ -z "${PROBLEM_SNAPSHOT_SOURCE}" || -z "${PROBLEM_SNAPSHOT_MANIFEST}" ]]; then
            echo "PROBLEM_SNAPSHOT_SOURCE and PROBLEM_SNAPSHOT_MANIFEST must be set together" >&2
            exit 2
        fi
        args+=(
            --problem-snapshot-source "${PROBLEM_SNAPSHOT_SOURCE}"
            --problem-snapshot-manifest "${PROBLEM_SNAPSHOT_MANIFEST}"
        )
        if [[ "${PROBLEM_SNAPSHOT_LINK}" == "1" ]]; then
            args+=(--problem-snapshot-link)
        fi
    fi
    if [[ "${IDEA_RUNTIME}" == "claude" || "${IMPLEMENT_RUNTIME}" == "claude" ]]; then
        if [[ ! -f "${CLAUDE_SETTINGS_SOURCE}" ]]; then
            echo "Claude settings not found: ${CLAUDE_SETTINGS_SOURCE}" >&2
            exit 2
        fi
        args+=(--claude-settings "${CLAUDE_SETTINGS_SOURCE}")
    fi
    if [[ "${IDEA_RUNTIME}" == "kimi-code" || "${IMPLEMENT_RUNTIME}" == "kimi-code" ]]; then
        if [[ ! -f "${KIMI_CODE_CONFIG}" ]]; then
            echo "Kimi Code config not found: ${KIMI_CODE_CONFIG}" >&2
            exit 2
        fi
        args+=(--kimi-code-config "${KIMI_CODE_CONFIG}")
    fi
    if [[ "${VALIDITY_JUDGE}" == "1" ]]; then
        if [[ ! -f "${CLAUDE_SETTINGS_SOURCE}" ]]; then
            echo "Judge settings source not found: ${CLAUDE_SETTINGS_SOURCE}" >&2
            exit 2
        fi
        args+=(
            --judge-settings-source "${CLAUDE_SETTINGS_SOURCE}"
            --trusted-judge-settings "${TRUSTED_DIR}/judge_settings.json"
        )
    fi
    python "${SCRIPT_DIR}/prepare_run.py" "${args[@]}"

    local seed_args=(
        --bank-root "${FAMOU_SOURCE}/.famou/cross_task_expbank"
        --skip-merge
        --seed-run "${RUN_DIR}"
        --judge-model "${CROSS_TASK_JUDGE_MODEL}"
    )
    if [[ "${CROSS_TASK_EXPBANK_SCOPE}" == "self" ]]; then
        seed_args+=(--only-task-id "${TASK_ID}")
    else
        seed_args+=(--exclude-task-id "${TASK_ID}")
    fi
    if [[ -n "${CROSS_TASK_SEED_BANK_ROOT}" ]]; then
        seed_args+=(--seed-bank-root "${CROSS_TASK_SEED_BANK_ROOT}")
    fi
    if [[ "${CROSS_TASK_EXPBANK}" == "0" ]]; then
        seed_args+=(--empty-seed)
    fi
    python "${SCRIPT_DIR}/sync_cross_task_expbank.py" "${seed_args[@]}"
}


stage_code_runtime() {
    if [[ "${IDEA_RUNTIME}" != "z-code" && "${IMPLEMENT_RUNTIME}" != "z-code" ]]; then
        return
    fi

    CODE_RUNTIME_DIR="${RUN_DIR}/agent_runtime/z-code"
    if [[ -n "${CODE_RUNTIME_SOURCE}" ]]; then
        CODE_RUNTIME_SOURCE="$(readlink -f "${CODE_RUNTIME_SOURCE}")"
        if [[ ! -x "${CODE_RUNTIME_SOURCE}/bin/zulu" || \
              ! -f "${CODE_RUNTIME_SOURCE}/comate-engine/bin/comate.js" ]]; then
            echo "reusable z-code runtime is incomplete: ${CODE_RUNTIME_SOURCE}" >&2
            exit 2
        fi
        if grep -R -q -I -E \
            'AKAj4CwQ|SKPgSwp2G|BCE-V3/|WEIYUN-TOKEN|apiin\.im\.baidu\.com.*access_token=|access_token=[A-Za-z0-9%_+./=-]{16,}|BOS_KEY[[:space:]]*=[[:space:]]*https?://' \
            "${CODE_RUNTIME_SOURCE}/comate-engine" "${CODE_RUNTIME_SOURCE}/zulu-cli" \
            2>/dev/null; then
            echo "reusable z-code runtime contains a sensitive credential pattern" >&2
            exit 2
        fi
        mkdir -p "$(dirname "${CODE_RUNTIME_DIR}")"
        ln -s "$(realpath --relative-to="$(dirname "${CODE_RUNTIME_DIR}")" "${CODE_RUNTIME_SOURCE}")" \
            "${CODE_RUNTIME_DIR}"
        return
    fi

    local zulu_binary zulu_root comate_engine_root
    zulu_binary="$(command -v zulu || true)"
    if [[ -z "${zulu_binary}" ]]; then
        echo "z-code requires a host zulu installation for CFS runtime staging" >&2
        exit 2
    fi
    zulu_binary="$(readlink -f "${zulu_binary}")"
    zulu_root="$(cd "$(dirname "${zulu_binary}")/.." && pwd)"
    comate_engine_root="$(cd "${zulu_root}/../comate-engine" && pwd)"
    if [[ ! -f "${zulu_root}/bundle/index.js" || \
          ! -f "${comate_engine_root}/bin/comate.js" ]]; then
        echo "incomplete z-code installation: ${zulu_root}" >&2
        exit 2
    fi

    mkdir -p \
        "${CODE_RUNTIME_DIR}/bin" \
        "${CODE_RUNTIME_DIR}/zulu-cli" \
        "${CODE_RUNTIME_DIR}/comate-engine"
    # Ownership is intentionally reset in the mounted Run directory; preserving
    # the host UID/GID fails on some CFS/tmpfs combinations.
    cp -R "${zulu_root}/." "${CODE_RUNTIME_DIR}/zulu-cli/"
    cp -R "${comate_engine_root}/." "${CODE_RUNTIME_DIR}/comate-engine/"
    rm -rf \
        "${CODE_RUNTIME_DIR}/comate-engine/assets" \
        "${CODE_RUNTIME_DIR}/comate-engine/plugins"
    find "${CODE_RUNTIME_DIR}/comate-engine" "${CODE_RUNTIME_DIR}/zulu-cli" \
        -type f -name '*.js' -print0 \
        | xargs -0 -r perl -pi -e \
            's/AKAj4CwQ/REMOVED_/g; s/SKPgSwp2G/REMOVED_/g'
    if grep -R -n -I -E \
        'AKAj4CwQ|SKPgSwp2G|BCE-V3/|WEIYUN-TOKEN|apiin\.im\.baidu\.com.*access_token=|access_token=[A-Za-z0-9%_+./=-]{16,}|BOS_KEY[[:space:]]*=[[:space:]]*https?://' \
        "${CODE_RUNTIME_DIR}/comate-engine" "${CODE_RUNTIME_DIR}/zulu-cli" \
        2>/dev/null; then
        echo "sensitive credential pattern remains in staged z-code runtime" >&2
        exit 2
    fi
    ln -s ../zulu-cli/bin/zulu "${CODE_RUNTIME_DIR}/bin/zulu"
    ln -s zulu "${CODE_RUNTIME_DIR}/bin/z-code"
    chmod -R a+rX,a-w "${CODE_RUNTIME_DIR}"
}


create_evaluator_key() {
    stage 2 "创建 Evaluator 响应签名密钥"

    mkdir -p "${TRUSTED_DIR}"
    chmod 700 "${TRUSTED_DIR}"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
        -out "${TRUSTED_DIR}/private_key.pem" >/dev/null 2>&1
    openssl pkey -in "${TRUSTED_DIR}/private_key.pem" -pubout \
        -out "${RUN_DIR}/controller/evaluator_channel/public_key.pem" >/dev/null 2>&1
}


resolve_task_mount() {
    # 默认只挂载本次 RUN_DIR。复用旧题面时可挂载两者的最小共同父目录；
    # trusted/ 仍靠 root:0700 与非特权 Agent 做进程内权限隔离。
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
    # 历史 snapshot 只在宿主 staging 阶段被校验并 hardlink 到当前 Run。
    # Task 容器不会读取源路径，因此无需扩大 fm-job 挂载范围。
    RUN_SUBPATH="${FMJOB_MOUNT_HOST_DIR#${CFS_OWNER_PREFIX}}"
    TASK_RUN_DIR="${FMJOB_MOUNT_PREFIX}/${RUN_DIR#${CFS_OWNER_PREFIX}}"
    if [[ -n "${CODE_RUNTIME_DIR}" ]]; then
        TASK_CODE_RUNTIME_DIR="${TASK_RUN_DIR}/agent_runtime/z-code"
    fi
}


submit_task_job() {
    stage 3 "提交单个 Task Job（资源共享、文件权限隔离）"

    # 提交回执落盘。作业名是 `<JOB_NAME_PREFIX>-<时间戳到秒>`；不传 `JOB_NAME_TAG`
    # 时前缀退化成 `famou-nb-<task>`，**不含臂/重复位标识**，光看 `fm-job list`
    # 无法把作业对回具体 Run——A/B 批次里同题两臂长得一模一样。没有这份回执时，
    # 审计「40 个目录是不是都真提交成功了」只能去一千多行的 fm-job list 里 grep，
    # 而且分不出谁是谁；被中断留下的「目录已建、作业没提」的半成品更是查不出来
    # （submit.sh 会因为目录存在而永远跳过它）。
    #
    # 回执解决的是**事后对账**，`JOB_NAME_TAG` 解决的是**提交时撞名**，两件事，
    # 都要做。
    local receipt_dir="${RUN_DIR}/controller"
    local submit_log="${receipt_dir}/fmjob_submit.log"
    mkdir -p "${receipt_dir}"

    # fm-job 不会自动继承提交机的任意环境变量。显式构造网络环境后，
    # Task supervisor、Agent、Candidate canonical run 和 Judge 的子进程都会继承。
    # 只透传已经存在的代理变量；数组值不会经过 shell 二次解析。
    local task_network_env=(
        "HF_ENDPOINT=${HF_ENDPOINT}"
        "HF_HUB_ENABLE_HF_TRANSFER=${HF_HUB_ENABLE_HF_TRANSFER}"
    )
    local proxy_name
    for proxy_name in \
        HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY \
        http_proxy https_proxy all_proxy no_proxy; do
        if [[ -n "${!proxy_name:-}" ]]; then
            task_network_env+=("${proxy_name}=${!proxy_name}")
        fi
    done

    "${FM_JOB_BIN}" run \
        --prefix "${JOB_NAME_PREFIX}" \
        --image "${IMAGE}" \
        --gpu "${AGENT_GPU}" --cpu "${AGENT_CPU}" \
        --memory "${AGENT_MEMORY_GIB}Gi" --shm-size 8Gi \
        --subpath "${RUN_SUBPATH}" --no-wait \
        -- env "${task_network_env[@]}" \
        FAMOU_EXPERIMENT_TIMEOUT_SEC="${EXPERIMENT_TIMEOUT_SEC}" \
        FAMOU_IMPLEMENT_TIMEOUT_SEC="${IMPLEMENT_TIMEOUT_SEC}" \
        FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT="${IMPLEMENT_DEADLINE_HEARTBEAT}" \
        FAMOU_IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC="${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC}" \
        FAMOU_PRICING_CURRENCY="${PRICING_CURRENCY}" \
        FAMOU_INPUT_PRICE_PER_MILLION="${INPUT_PRICE_PER_MILLION}" \
        FAMOU_CACHE_CREATION_PRICE_PER_MILLION="${CACHE_CREATION_PRICE_PER_MILLION}" \
        FAMOU_CACHE_READ_PRICE_PER_MILLION="${CACHE_READ_PRICE_PER_MILLION}" \
        FAMOU_OUTPUT_PRICE_PER_MILLION="${OUTPUT_PRICE_PER_MILLION}" \
        FAMOU_PRICING_SOURCE="${PRICING_SOURCE}" \
        FAMOU_PRICING_EFFECTIVE_AT="${PRICING_EFFECTIVE_AT}" \
        FAMOU_IDEA_RUNTIME="${IDEA_RUNTIME}" \
        FAMOU_IMPLEMENT_RUNTIME="${IMPLEMENT_RUNTIME}" \
        FAMOU_IDEA_MODEL="${IDEA_MODEL}" \
        FAMOU_IMPLEMENT_MODEL="${IMPLEMENT_MODEL}" \
        FAMOU_PAIRWISE_IMPROVE_SEARCH="${PAIRWISE_IMPROVE_SEARCH}" \
        FAMOU_REFINE_AFTER_EVALUATION="${REFINE_AFTER_EVALUATION}" \
        FAMOU_MAX_DEBUG_ATTEMPTS="${MAX_DEBUG_ATTEMPTS}" \
        FAMOU_IDEA_GENERATION="${IDEA_GENERATION}" \
        FAMOU_IDEA_GRAPH="${IDEA_GRAPH}" \
        FAMOU_IDEA_GRAPH_VERSION="${IDEA_GRAPH_VERSION}" \
        FAMOU_IDEA_DEBATE="${IDEA_DEBATE}" \
        FAMOU_IDEA_DEBATE_MODE="${IDEA_DEBATE_MODE}" \
        FAMOU_IDEA_DEBATE_MAX_ROUNDS="${IDEA_DEBATE_MAX_ROUNDS}" \
        FAMOU_IDEA_DEBATE_MIN_ELAPSED_SEC="${IDEA_DEBATE_MIN_ELAPSED_SEC}" \
        FAMOU_IDEA_DEBATE_MIN_EVALUATED_ATTEMPTS="${IDEA_DEBATE_MIN_EVALUATED_ATTEMPTS}" \
        FAMOU_IDEA_DEBATE_ALLOW_CROSS_TASK_ONLY="${IDEA_DEBATE_ALLOW_CROSS_TASK_ONLY}" \
        FAMOU_IDEA_DEBATE_EMIT_PAIR="${IDEA_DEBATE_EMIT_PAIR}" \
        FAMOU_IDEA_DEBATE_MAX_TURNS="${IDEA_DEBATE_MAX_TURNS}" \
        FAMOU_IDEA_DEBATE_TIMEOUT_SEC="${IDEA_DEBATE_TIMEOUT_SEC}" \
        FAMOU_IDEA_JUDGE_MODEL="${IDEA_JUDGE_MODEL}" \
        FAMOU_IDEA_PROMPT_VERSION="${IDEA_PROMPT_VERSION}" \
        FAMOU_IMPLEMENT_PROMPT_VERSION="${IMPLEMENT_PROMPT_VERSION}" \
        FAMOU_CODE_RUNTIME_DIR="${TASK_CODE_RUNTIME_DIR}" \
        timeout --signal=TERM --kill-after=60s "${HARD_TIMEOUT_SEC}" /bin/bash \
        "${TASK_RUN_DIR}/famou-scientist/famou_scientist/loop/examples/naturebench/fmjob/task_entrypoint.sh" \
        "${TASK_RUN_DIR}" "${TASK_ID}" "${AGENT_RUNTIME}" "${MODEL}" \
        "${MAX_BENCHMARK_ATTEMPTS}" "${MAX_WALL_TIME_HOURS}" "${MAX_IMPLEMENT_TURNS}" \
        "${MAX_RUN_ATTEMPTS}" "${IDEA_CONCURRENCY}" \
        "${IMPLEMENT_CONCURRENCY}" "${EVALUATION_CONCURRENCY}" \
        "${IDEA_QUEUE_CAPACITY}" "${EVALUATION_QUEUE_CAPACITY}" \
        "${VALIDITY_JUDGE}" "${EVALUATOR_REQUEST_TIMEOUT_SEC}" \
        "${TIME_AWARE_IDEA_RANKING}" \
        "${IDEA_RANK_TRIGGER_REMAINING_SEC}" "${IDEA_RANK_MODEL}" \
        "${IDEA_RANK_MAX_TURNS}" "${IDEA_RANK_TIMEOUT_SEC}" \
        "${AGENT_CPU}" "${AGENT_GPU}" "${AGENT_MEMORY_GIB}" \
        "${EVALUATION_TIMEOUT_SEC}" "${JUDGE_TIMEOUT_SEC}" \
        "${AGENT_UID}" "${AGENT_GID}" "${JUDGE_MODEL}" \
        "${AGENT_PROCESS_MEMORY_LIMIT_GIB}" 2>&1 | tee "${submit_log}"
    local fmjob_status="${PIPESTATUS[0]}"

    local job_name
    job_name="$(grep -oE "${JOB_NAME_PREFIX}-[0-9]{8}-[0-9]{6}" "${submit_log}" \
        | head -1 || true)"
    write_submit_receipt "${job_name}" "${fmjob_status}"
    if [[ "${fmjob_status}" != "0" ]]; then
        echo "fm-job run failed (exit ${fmjob_status}); receipt: ${receipt_dir}/fmjob.json" >&2
        return "${fmjob_status}"
    fi
    if [[ -z "${job_name}" ]]; then
        # 提交成功但没解析出作业名：回执仍然落盘（job_name 为 null），审计脚本
        # 据此报告"无法核对"，而不是把它误判成半成品。
        echo "WARN: 未能从 fm-job 输出解析作业名，回执已落盘但 job_name 为空" >&2
    fi
}


write_submit_receipt() {
    # 把提交回执写进 <run>/controller/fmjob.json。
    local job_name="$1"
    local fmjob_status="$2"
    python3 - "$@" <<PY
import json, os, sys, time

job_name = sys.argv[1] or None
status = sys.argv[2]
receipt = {
    "job_name": job_name,
    "fmjob_exit_code": int(status) if status.isdigit() else status,
    "run_id": os.environ.get("RUN_ID"),
    "task_id": os.environ.get("TASK_ID"),
    "run_dir": os.environ.get("RUN_DIR"),
    "image": os.environ.get("IMAGE"),
    "submitted_at_ms": int(time.time() * 1000),
    # 实验相关配置一并留档：事后审计不必再去翻批次脚本，也能确认这个 Run
    # 到底是哪条臂、用的哪版提示词、从哪份库 seed。
    "cross_task_expbank": os.environ.get("CROSS_TASK_EXPBANK"),
    "cross_task_expbank_scope": os.environ.get("CROSS_TASK_EXPBANK_SCOPE"),
    "cross_task_seed_bank_root": os.environ.get("CROSS_TASK_SEED_BANK_ROOT") or None,
    "idea_prompt_version": os.environ.get("IDEA_PROMPT_VERSION"),
    "implement_prompt_version": os.environ.get("IMPLEMENT_PROMPT_VERSION"),
    # 与 cross_task_expbank 同理：只有调用方显式设过才会留档，脚本内默认值不 export。
    # 两臂配对实验务必在两条臂上都显式传 IDEA_GRAPH，否则事后分不清哪条是对照。
    "idea_graph": os.environ.get("IDEA_GRAPH"),
    # ⚠️ 两个版本的图存储构造都有副作用（mkdir + 写空索引），所以「GRAPH.md 是空的」
    # 不能用来区分两臂——臂标识只有这里可靠。
    "idea_graph_version": os.environ.get("IDEA_GRAPH_VERSION"),
    # 同理只有显式设过才留档。它控制 infra.scheduling.search_policy.enabled
    # （队列层的 refine/switch/fuse 三选一），与 idea_graph* 是彼此独立的开关，
    # 关掉之后 Improve 回合只剩 refine。跑完只从产物看不出它开没开——lease
    # 事件不发生时队列里什么痕迹都没有——所以必须在这里留档。
    "pairwise_improve_search": os.environ.get("PAIRWISE_IMPROVE_SEARCH"),
    # 这两项同样事后不可见：关掉 refine 之后队列里根本不产生 actor_continuation，
    # 「没有 refine」和「有预算但没触发」在产物上长得一模一样。
    "refine_after_evaluation": os.environ.get("REFINE_AFTER_EVALUATION"),
    "max_debug_attempts": os.environ.get("MAX_DEBUG_ATTEMPTS"),
    # 这两项**直接内插生效值**，不走 os.environ：脚本内有默认值，调用方通常不显式
    # 设置，走 os.environ 会一律记成 null，事后就分不清这个 run 的单次 Implement
    # 上限到底是 3600 还是 4800——而这正是超时率能不能跨批次比较的前提。
    "implement_timeout_sec": ${IMPLEMENT_TIMEOUT_SEC},
    "implement_deadline_heartbeat_after_sec": ${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC},
    "idea_model": os.environ.get("IDEA_MODEL"),
    "implement_model": os.environ.get("IMPLEMENT_MODEL"),
    "concurrency": {
        "idea": os.environ.get("IDEA_CONCURRENCY"),
        "implement": os.environ.get("IMPLEMENT_CONCURRENCY"),
        "evaluation": os.environ.get("EVALUATION_CONCURRENCY"),
    },
    "max_wall_time_hours": os.environ.get("MAX_WALL_TIME_HOURS"),
}
path = os.path.join(os.environ["RUN_DIR"], "controller", "fmjob.json")
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(receipt, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(tmp, path)
PY
}


print_summary() {
    printf '\nNatureBench jobs submitted.\n'
    printf '  run_id:     %s\n' "${RUN_ID}"
    printf '  host_dir:   %s\n' "${RUN_DIR}"
    printf '  task_dir:   %s\n' "${TASK_RUN_DIR}"
    printf '  mount root: %s\n' "${FMJOB_MOUNT_HOST_DIR}"
    printf '  fm-job count: 1\n'
    printf '  agent budget: %sh\n' "${MAX_WALL_TIME_HOURS}"
    printf '  evaluation drain budget: %ss (queue capacity worst-case serial drain)\n' \
        "${EVALUATION_DRAIN_BUDGET_SEC}"
    printf '  finalization grace: %ss (evaluation drain + Judge + buffer)\n' \
        "${FINALIZATION_GRACE_SEC}"
    printf '  infrastructure hard timeout: %ss\n' "${HARD_TIMEOUT_SEC}"
    printf '  benchmark attempts: %s\n' \
        "$([[ "${MAX_BENCHMARK_ATTEMPTS}" == "-" ]] && printf 'unlimited' || printf '%s' "${MAX_BENCHMARK_ATTEMPTS}")"
    printf '  concurrency: idea=%s implement=%s evaluation=%s\n' \
        "${IDEA_CONCURRENCY}" "${IMPLEMENT_CONCURRENCY}" "${EVALUATION_CONCURRENCY}"
    printf '  queue capacity: idea=%s evaluation=%s\n' \
        "${IDEA_QUEUE_CAPACITY}" "${EVALUATION_QUEUE_CAPACITY}"
    printf '  validity judge: %s (model=%s)\n' "${VALIDITY_JUDGE}" "${JUDGE_MODEL}"
    printf '  idea agent: %s + %s\n' "${IDEA_RUNTIME}" "${IDEA_MODEL}"
    printf '  implement agent: %s + %s\n' "${IMPLEMENT_RUNTIME}" "${IMPLEMENT_MODEL}"
    if [[ -n "${CODE_RUNTIME_DIR}" ]]; then
        printf '  staged code runtime: %s\n' "${CODE_RUNTIME_DIR}"
    fi
    printf '  HuggingFace endpoint: %s (hf_transfer=%s)\n' \
        "${HF_ENDPOINT}" "${HF_HUB_ENABLE_HF_TRANSFER}"
    if [[ -n "${ALL_PROXY:-}" || -n "${all_proxy:-}" ]]; then
        printf '  task proxy: configured (value hidden)\n'
    else
        printf '  task proxy: not configured\n'
    fi
    if [[ -n "${INPUT_PRICE_PER_MILLION}" ]]; then
        printf '  token pricing: input=%s cache_create=%s cache_read=%s output=%s %s/M\n' \
            "${INPUT_PRICE_PER_MILLION}" "${CACHE_CREATION_PRICE_PER_MILLION}" \
            "${CACHE_READ_PRICE_PER_MILLION}" "${OUTPUT_PRICE_PER_MILLION}" \
            "${PRICING_CURRENCY}"
    fi
    printf '  implement DDL heartbeat: %s (after=%ss, activation limit=%ss)\n' \
        "${IMPLEMENT_DEADLINE_HEARTBEAT}" "${IMPLEMENT_DEADLINE_HEARTBEAT_AFTER_SEC}" \
        "${IMPLEMENT_TIMEOUT_SEC}"
    printf '  evaluation quota: timeout=%ss queue=%s hard-timeout=%ss\n' \
        "${EVALUATION_TIMEOUT_SEC}" "${EVALUATION_QUEUE_CAPACITY}" "${HARD_TIMEOUT_SEC}"
    if (( ${#EVALUATION_QUOTA_APPLIED[@]} > 0 )); then
        printf '    per-task override from %s: %s\n' \
            "${EVALUATION_QUOTA_FILE}" "${EVALUATION_QUOTA_APPLIED[*]}"
    fi
    printf '  resource tier: %s (cpu=%s gpu=%s memory=%sGi)\n' \
        "${RESOURCE_TIER}" "${AGENT_CPU}" "${AGENT_GPU}" "${AGENT_MEMORY_GIB}"
    printf '  agent process memory limit: %s GiB ("-" means auto)\n' \
        "${AGENT_PROCESS_MEMORY_LIMIT_GIB}"
    printf '  privilege boundary: trusted=root agent=%s:%s\n' \
        "${AGENT_UID}" "${AGENT_GID}"
    printf '  problem staging: %s (manifest hash file<=%s bytes, total<=%s bytes)\n' \
        "${PROBLEM_STAGING_MODE}" "${MANIFEST_HASH_MAX_FILE_BYTES}" \
        "${MANIFEST_HASH_TOTAL_BUDGET_BYTES}"
    if [[ -n "${PROBLEM_SNAPSHOT_SOURCE}" ]]; then
        printf '  reused public problem snapshot: %s\n' "${PROBLEM_SNAPSHOT_SOURCE}"
    fi
    printf '  time-aware idea ranking: %s (remaining=%ss model=%s timeout=%ss)\n' \
        "${TIME_AWARE_IDEA_RANKING}" "${IDEA_RANK_TRIGGER_REMAINING_SEC}" \
        "${IDEA_RANK_MODEL}" "${IDEA_RANK_TIMEOUT_SEC}"
    printf '  idea debate: %s (mode=%s rounds=%s judge=%s elapsed>=%ss evaluated>=%s cross_task_only=%s emit_pair=%s)\n' \
        "${IDEA_DEBATE}" "${IDEA_DEBATE_MODE}" "${IDEA_DEBATE_MAX_ROUNDS}" \
        "${IDEA_JUDGE_MODEL}" "${IDEA_DEBATE_MIN_ELAPSED_SEC}" \
        "${IDEA_DEBATE_MIN_EVALUATED_ATTEMPTS}" "${IDEA_DEBATE_ALLOW_CROSS_TASK_ONLY}" \
        "${IDEA_DEBATE_EMIT_PAIR}"
    printf '  resume=%s pairwise_improve_search=%s idea_generation=%s idea_graph=%s (schema=%s)\n' \
        "${RESUME_RUN}" "${PAIRWISE_IMPROVE_SEARCH}" "${IDEA_GENERATION}" \
        "${IDEA_GRAPH}" "${IDEA_GRAPH_VERSION}"
    printf '  cross-task expbank: %s (scope=%s judge=%s self_task=%s seed_bank=%s)\n' \
        "${CROSS_TASK_EXPBANK}" "${CROSS_TASK_EXPBANK_SCOPE}" "${CROSS_TASK_JUDGE_MODEL}" \
        "${TASK_ID}" "${CROSS_TASK_SEED_BANK_ROOT:-<live>}"
}


main() {
    resolve_resource_tier
    resolve_agent_gpu
    prepare_agent_run
    stage_code_runtime
    create_evaluator_key
    resolve_task_mount
    submit_task_job
    print_summary
}


if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
