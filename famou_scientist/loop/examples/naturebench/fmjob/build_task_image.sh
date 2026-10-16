#!/usr/bin/env bash
# 构建单个 NatureBench 任务镜像；批量构建和自动推送使用 publish_task_images.sh。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATUREBENCH_ROOT="${NATUREBENCH_ROOT:-/path/to/workspace/opensource/NatureBench}"
TASK_ID="${TASK_ID:-s43588-024-00689-2}"
IMAGE="${IMAGE:-<你的镜像仓库>/famou-public/naturebench-${TASK_ID}:v1}"

registry="${IMAGE%/naturebench-*}"
name_and_tag="${IMAGE##*/}"
tag="${name_and_tag##*:}"
if [[ "${IMAGE}" != "${registry}/naturebench-${TASK_ID}:${tag}" ]]; then
    echo "IMAGE must follow <registry>/naturebench-${TASK_ID}:<tag>: ${IMAGE}" >&2
    exit 2
fi
PUSH=0 NATUREBENCH_ROOT="${NATUREBENCH_ROOT}" REGISTRY="${registry}" TAG="${tag}" \
    "${SCRIPT_DIR}/publish_task_images.sh" --no-push "${TASK_ID}"
