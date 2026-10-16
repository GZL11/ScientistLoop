#!/usr/bin/env bash
# 构建/推送 NatureBench 官方评测环境镜像（只需构建一次，90 个任务镜像共用）。
#
# 为什么单独一层
# --------------
# 评测环境与 Agent 环境的依赖 pin **互斥**（numpy 2.x vs torch cu118 要求的
# numpy<2），必须分成两个 venv。但 90 个任务镜像各建一遍 venv 既慢又容易漂移，
# 所以这里构建一次 `naturebench-evalenv:<tag>`，再由 build_agent_image.sh
# 用 `COPY --from=` 把 /opt/pyeval 整个搬进每个任务镜像——与现有搬运
# zulu/comate 运行时的做法完全一致。
#
# 用法：
#   bash build_eval_env_image.sh                       # 构建并推送
#   PUSH=0 bash build_eval_env_image.sh                # 只构建
#   EVAL_ENV_TAG=v2 bash build_eval_env_image.sh       # 换 tag
#
# 改完之后**必须**跑 verify_eval_env.py，在全部 90 道题上验证 evaluator 能被导入；
# 否则少一个包就会在线上变成一次静默的 −1。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_ENV_TAG="${EVAL_ENV_TAG:-v1}"
BASE_IMAGE="${BASE_IMAGE:-<你的镜像仓库>/famou-public/naturebench-base:v3}"
IMAGE="${IMAGE:-<你的镜像仓库>/famou-public/naturebench-evalenv:${EVAL_ENV_TAG}}"
PUSH="${PUSH:-1}"

docker build --network=host \
    --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
    -t "${IMAGE}" \
    -f "${SCRIPT_DIR}/Dockerfile.evalenv" \
    "${SCRIPT_DIR}"

if [[ "${PUSH}" == "1" ]]; then
    docker push "${IMAGE}"
fi
printf 'NatureBench eval env image ready: %s\n' "${IMAGE}"
