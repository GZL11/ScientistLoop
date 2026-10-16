#!/usr/bin/env bash
# 批量构建并推送 NatureBench 精确任务镜像。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 记录调用方目录；后面会切换到 NatureBench 根目录构建，输出清单仍应落在调用方指定的位置。
INVOCATION_CWD="$(pwd)"
FAMOU_SOURCE="${FAMOU_SOURCE:-$(cd "${SCRIPT_DIR}/../../../../.." && pwd)}"
NATUREBENCH_ROOT="${NATUREBENCH_ROOT:-/path/to/workspace/opensource/NatureBench}"
REGISTRY="${REGISTRY:-<你的镜像仓库>/famou-public}"
TAG="${TAG:-v1}"
PUSH="${PUSH:-1}"
REBUILD_BASE="${REBUILD_BASE:-0}"
DRY_RUN="${DRY_RUN:-0}"
REMOVE_LOCAL_AFTER_PUSH="${REMOVE_LOCAL_AFTER_PUSH:-0}"
TASK_FILE="${TASK_FILE:-}"
MANIFEST="${MANIFEST:-${FAMOU_SOURCE}/.famou/naturebench-images/publish-$(date +%Y%m%d-%H%M%S).json}"

usage() {
    cat <<'EOF'
Usage:
  publish_task_images.sh [options] TASK_ID [TASK_ID ...]
  publish_task_images.sh --task-file tasks.txt

Options:
  --task-file PATH   每行一个 task id，空行和 # 注释会被忽略
  --registry PATH    镜像仓库前缀
  --tag TAG          所有任务镜像使用的 tag，默认 v1
  --manifest PATH    发布清单输出路径
  --no-push          只构建，不推送
  --rebuild-base     强制重建 NatureBench base:v3
  --remove-local-after-push
                     推送成功后删除 task 镜像，只保留共享 base，适合小根盘批量发布
  --dry-run          只打印操作，不调用 Docker
  -h, --help         显示帮助

也可使用 TASK_IDS="task-a,task-b" 或单个 TASK_ID 环境变量。
EOF
}

run() {
    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '+'
        printf ' %q' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

tasks=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --task-file)
            TASK_FILE="${2:?--task-file requires a path}"
            shift 2
            ;;
        --registry)
            REGISTRY="${2:?--registry requires a value}"
            shift 2
            ;;
        --tag)
            TAG="${2:?--tag requires a value}"
            shift 2
            ;;
        --manifest)
            MANIFEST="${2:?--manifest requires a path}"
            shift 2
            ;;
        --no-push)
            PUSH=0
            shift
            ;;
        --rebuild-base)
            REBUILD_BASE=1
            shift
            ;;
        --remove-local-after-push)
            REMOVE_LOCAL_AFTER_PUSH=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --*)
            echo "unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            tasks+=("$1")
            shift
            ;;
    esac
done

if [[ -n "${TASK_FILE}" ]]; then
    if [[ ! -f "${TASK_FILE}" ]]; then
        echo "task file not found: ${TASK_FILE}" >&2
        exit 2
    fi
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%%#*}"
        line="$(printf '%s' "${line}" | xargs)"
        [[ -n "${line}" ]] && tasks+=("${line}")
    done < "${TASK_FILE}"
fi

if [[ -n "${TASK_IDS:-}" ]]; then
    normalized="${TASK_IDS//,/ }"
    read -r -a env_tasks <<< "${normalized}"
    tasks+=("${env_tasks[@]}")
elif [[ ${#tasks[@]} -eq 0 && -n "${TASK_ID:-}" ]]; then
    tasks+=("${TASK_ID}")
fi

if [[ ${#tasks[@]} -eq 0 ]]; then
    echo "at least one TASK_ID or --task-file is required" >&2
    usage >&2
    exit 2
fi

# 相对路径以脚本启动目录为基准解析，避免 cd 到 NatureBench 根目录后改变输出位置。
if [[ "${MANIFEST}" != /* ]]; then
    MANIFEST="${INVOCATION_CWD}/${MANIFEST}"
fi

if [[ "${REMOVE_LOCAL_AFTER_PUSH}" == "1" && "${PUSH}" != "1" ]]; then
    echo "--remove-local-after-push requires pushing the image" >&2
    exit 2
fi

for command in docker jq; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        echo "required command not found: ${command}" >&2
        exit 2
    fi
done

declare -A seen=()
unique_tasks=()
for task_id in "${tasks[@]}"; do
    if [[ ! "${task_id}" =~ ^[A-Za-z0-9._-]+$ ]]; then
        echo "invalid task id: ${task_id}" >&2
        exit 2
    fi
    [[ -n "${seen[${task_id}]:-}" ]] && continue
    seen["${task_id}"]=1
    unique_tasks+=("${task_id}")
done

if [[ "${DRY_RUN}" != "1" ]]; then
    docker_root="$(docker info --format '{{.DockerRootDir}}')"
    printf 'Docker data root: %s\n' "${docker_root}"
    df -h "${docker_root}"
    if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
        printf '%s' "${REGISTRY_PASSWORD}" | docker login \
            "${REGISTRY%%/*}" --username "${REGISTRY_USERNAME}" --password-stdin
    fi
fi

# Docker BuildKit 不一定会把宿主机代理环境自动传给 Dockerfile 中的 pip。
# 显式传入代理只用于构建期下载依赖，不会成为 Agent 运行时环境的一部分。
docker_build_proxy_args=()
for proxy_name in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
    if [[ -n "${!proxy_name:-}" ]]; then
        docker_build_proxy_args+=(--build-arg "${proxy_name}=${!proxy_name}")
    fi
done

cd "${NATUREBENCH_ROOT}"
if [[ "${DRY_RUN}" == "1" ]] || [[ "${REBUILD_BASE}" == "1" ]] \
    || ! docker image inspect naturebench-base:v3 >/dev/null 2>&1; then
    run docker build --network=host "${docker_build_proxy_args[@]}" -t naturebench-base:v3 \
        -f docker/Dockerfile.base docker
fi
run docker tag naturebench-base:v3 cnsbench-base:v3

manifest_dir="$(dirname "${MANIFEST}")"
mkdir -p "${manifest_dir}"
records_file="$(mktemp "${manifest_dir}/.publish-records.XXXXXX")"
trap 'rm -f "${records_file}"' EXIT

for task_id in "${unique_tasks[@]}"; do
    context="data/naturebench_data/tasks/${task_id}/environment"
    dockerfile="${context}/Dockerfile.v3"
    if [[ ! -f "${dockerfile}" ]]; then
        echo "task Dockerfile not found: ${dockerfile}" >&2
        exit 2
    fi
    image="${REGISTRY}/naturebench-${task_id}:${TAG}"
    printf '\n[%s] build %s\n' "${task_id}" "${image}"
    run docker build --network=host "${docker_build_proxy_args[@]}" \
        -t "${image}" -f "${dockerfile}" "${context}"
    if [[ "${PUSH}" == "1" ]]; then
        run docker push "${image}"
    fi
    pushed=false
    if [[ "${PUSH}" == "1" && "${DRY_RUN}" != "1" ]]; then
        pushed=true
    fi
    image_id=""
    if [[ "${DRY_RUN}" != "1" ]]; then
        image_id="$(docker image inspect "${image}" --format '{{.Id}}')"
    fi
    jq -nc \
        --arg task_id "${task_id}" \
        --arg image "${image}" \
        --arg image_id "${image_id}" \
        --argjson pushed "${pushed}" \
        --argjson remove_local_after_push \
        "$([[ "${REMOVE_LOCAL_AFTER_PUSH}" == "1" ]] && echo true || echo false)" \
        '{task_id: $task_id, image: $image, image_id: $image_id, pushed: $pushed,
          local_image_removed: ($pushed and $remove_local_after_push)}' \
        >> "${records_file}"
    if [[ "${REMOVE_LOCAL_AFTER_PUSH}" == "1" ]]; then
        run docker image rm "${image}"
    fi
done

jq -s \
    --arg registry "${REGISTRY}" \
    --arg tag "${TAG}" \
    --arg generated_at "$(date -Iseconds)" \
    --argjson dry_run "$([[ "${DRY_RUN}" == "1" ]] && echo true || echo false)" \
    '{schema_version: 1, generated_at: $generated_at, registry: $registry, tag: $tag, dry_run: $dry_run, images: .}' \
    "${records_file}" > "${MANIFEST}"

printf '\nPublished %s NatureBench task image(s).\n' "${#unique_tasks[@]}"
printf 'Manifest: %s\n' "${MANIFEST}"
