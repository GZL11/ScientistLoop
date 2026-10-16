#!/usr/bin/env bash
# Build/push a NatureBench task image with the supported coding CLIs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATUREBENCH_ROOT="${NATUREBENCH_ROOT:-/path/to/workspace/opensource/NatureBench}"
TASK_ID="${TASK_ID:-s41592-025-02893-y}"
IMAGE_TAG="${IMAGE_TAG:-cli-runtimes-v2-clean}"
BASE_IMAGE="${BASE_IMAGE:-<你的镜像仓库>/famou-public/scimodelingbench-agent:cli-runtimes-v1}"
# 官方评测环境（/opt/pyeval）。由 build_eval_env_image.sh 单独构建一次，这里只搬运。
# 置空可跳过搬运——此时评测器回退到任务镜像的解释器，即改动前的行为。
EVAL_ENV_IMAGE="${EVAL_ENV_IMAGE:-<你的镜像仓库>/famou-public/naturebench-evalenv:v1}"
TASK_BASE_IMAGE="${TASK_BASE_IMAGE:-<你的镜像仓库>/famou-public/naturebench-${TASK_ID}:v1}"
IMAGE="${IMAGE:-<你的镜像仓库>/famou-public/naturebench-${TASK_ID}:${IMAGE_TAG}}"
PUSH="${PUSH:-1}"
KIMI_BINARY="${KIMI_BINARY:-/root/.kimi-code/bin/kimi}"
ZULU_BINARY="${ZULU_BINARY:-$(command -v zulu || true)}"

[[ -x "${KIMI_BINARY}" ]] || { echo "Kimi binary not executable: ${KIMI_BINARY}" >&2; exit 2; }
[[ -n "${ZULU_BINARY}" ]] || { echo "zulu binary not found" >&2; exit 2; }
ZULU_BINARY="$(readlink -f "${ZULU_BINARY}")"
ZULU_ROOT="$(cd "$(dirname "${ZULU_BINARY}")/.." && pwd)"
COMATE_ENGINE_ROOT="$(cd "${ZULU_ROOT}/../comate-engine" && pwd)"
[[ -f "${ZULU_ROOT}/bundle/index.js" && -f "${COMATE_ENGINE_ROOT}/bin/comate.js" ]] || {
    echo "incomplete Zulu installation under ${ZULU_ROOT}" >&2
    exit 2
}

BUILD_CONTEXT="$(mktemp -d "${TMPDIR:-/tmp}/naturebench-agent-image.XXXXXX")"
cleanup() { rm -rf "${BUILD_CONTEXT}"; }
trap cleanup EXIT

# 评测环境是可选的一层：给空值就退回「评测器与 Agent 共用解释器」的老行为，
# 老镜像因此不会因为这次改动而构建失败。
EVAL_ENV_STAGE=""
EVAL_ENV_COPY=""
if [[ -n "${EVAL_ENV_IMAGE}" ]]; then
    EVAL_ENV_STAGE="FROM ${EVAL_ENV_IMAGE} AS evalenv"
    # 搬进来之后当场验一次：venv 换了镜像还能不能起来、numpy/pandas 是不是评测口径的
    # 版本。搬运失败在 build 阶段炸掉，好过线上把整题评成 −1。
    EVAL_ENV_COPY="COPY --from=evalenv /opt/pyeval /opt/pyeval
RUN /opt/pyeval/bin/python -c \"import numpy, pandas; assert numpy.__version__[0] == '2' and pandas.__version__ >= '2.3', (numpy.__version__, pandas.__version__); print('eval env:', numpy.__version__, pandas.__version__)\""
fi

cat > "${BUILD_CONTEXT}/Dockerfile" <<EOF
${EVAL_ENV_STAGE}
FROM ${BASE_IMAGE} AS cli-runtimes
RUN rm -rf \
       /opt/comate-engine/assets \
       /opt/comate-engine/plugins \
    && find /opt/comate-engine /opt/zulu-cli -type f -name '*.js' -print0 \
       | xargs -0 -r perl -pi -e \
           's/AKAj4CwQ/REMOVED_/g; s/SKPgSwp2G/REMOVED_/g'
FROM ${TASK_BASE_IMAGE}
${EVAL_ENV_COPY}
COPY --from=cli-runtimes /usr/local/bin/kimi /usr/local/bin/kimi
COPY --from=cli-runtimes /opt/zulu-cli /opt/zulu-cli
COPY --from=cli-runtimes /opt/comate-engine /opt/comate-engine
ENV COMATE_ENGINE_PATH=/opt/comate-engine
RUN ln -s /opt/zulu-cli/bin/zulu /usr/local/bin/zulu \
    && ln -s /usr/local/bin/zulu /usr/local/bin/z-code \
    && command -v claude && command -v codex && command -v kimi \
    && command -v zulu && command -v z-code \
    && if grep -R -n -I -E \
         'AKAj4CwQ|SKPgSwp2G|BCE-V3/|WEIYUN-TOKEN|apiin\\.im\\.baidu\\.com.*access_token=|access_token=[A-Za-z0-9%_+./=-]{16,}|BOS_KEY[[:space:]]*=[[:space:]]*https?://' \
         /opt/comate-engine /opt/zulu-cli 2>/dev/null; then \
         echo 'ERROR: sensitive credential pattern remains in coding runtimes' >&2; \
         exit 1; \
       fi
EOF
docker build --network=host -t "${IMAGE}" "${BUILD_CONTEXT}"
if [[ "${PUSH}" == "1" ]]; then
    docker push "${IMAGE}"
fi
printf 'NatureBench agent image ready: %s\n' "${IMAGE}"
