#!/usr/bin/env bash
# Build and optionally push the SciModelingBench fm-job image.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-<你的镜像仓库>/famou-public/scimodelingbench-agent:cli-runtimes-v2-datasets48}"
PUSH="${PUSH:-0}"

# Pin runtime versions in the image metadata unless the builder deliberately
# overrides them. z-code is intentionally an explicit build-time input because
# no public package source is available for it in this repository.
CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-2.1.199}"
CODEX_VERSION="${CODEX_VERSION:-0.147.0}"
OPENCODE_VERSION="${OPENCODE_VERSION:-1.18.1}"
DATASETS_VERSION="${DATASETS_VERSION:-4.8.5}"
HUGGINGFACE_HUB_VERSION="${HUGGINGFACE_HUB_VERSION:-1.15.0}"
PYARROW_VERSION="${PYARROW_VERSION:-24.0.0}"
KIMI_BINARY="${KIMI_BINARY:-$(command -v kimi || true)}"
if [[ -z "${KIMI_BINARY}" ]]; then
    echo "kimi-code runtime requires the Kimi Code CLI; command 'kimi' was not found." >&2
    exit 2
fi
KIMI_BINARY="$(readlink -f "${KIMI_BINARY}")"
if [[ ! -x "${KIMI_BINARY}" ]]; then
    echo "Kimi CLI is not executable: ${KIMI_BINARY}" >&2
    exit 2
fi
ZULU_BINARY="${ZULU_BINARY:-$(command -v zulu || true)}"
if [[ -z "${ZULU_BINARY}" ]]; then
    echo "z-code runtime requires the Baidu Comate Zulu CLI; command 'zulu' was not found." >&2
    exit 2
fi
ZULU_ROOT="$(cd "$(dirname "$(readlink -f "${ZULU_BINARY}")")/.." && pwd)"
COMATE_ENGINE_ROOT="$(cd "${ZULU_ROOT}/../comate-engine" && pwd)"
if [[ ! -f "${ZULU_ROOT}/bin/zulu" || ! -f "${ZULU_ROOT}/bundle/index.js" || \
      ! -f "${COMATE_ENGINE_ROOT}/bin/comate.js" ]]; then
    echo "incomplete Zulu installation; expected zulu-cli and sibling comate-engine under ${ZULU_ROOT}/.." >&2
    exit 2
fi

BUILD_CONTEXT="$(mktemp -d "${TMPDIR:-/tmp}/scimodelingbench-image.XXXXXX")"
PROXY_ARGS=()
for proxy_name in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
    if [[ -n "${!proxy_name:-}" ]]; then
        PROXY_ARGS+=(--build-arg "${proxy_name}=${!proxy_name}")
    fi
done
cleanup() {
    rm -rf "${BUILD_CONTEXT}"
}
trap cleanup EXIT
cp "${SCRIPT_DIR}/Dockerfile" "${BUILD_CONTEXT}/Dockerfile"
cp "${KIMI_BINARY}" "${BUILD_CONTEXT}/kimi"
cp -a "${ZULU_ROOT}" "${BUILD_CONTEXT}/zulu-cli"
cp -a "${COMATE_ENGINE_ROOT}" "${BUILD_CONTEXT}/comate-engine"

docker build --network=host \
    "${PROXY_ARGS[@]}" \
    --build-arg "CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}" \
    --build-arg "CODEX_VERSION=${CODEX_VERSION}" \
    --build-arg "OPENCODE_VERSION=${OPENCODE_VERSION}" \
    --build-arg "DATASETS_VERSION=${DATASETS_VERSION}" \
    --build-arg "HUGGINGFACE_HUB_VERSION=${HUGGINGFACE_HUB_VERSION}" \
    --build-arg "PYARROW_VERSION=${PYARROW_VERSION}" \
    -t "${IMAGE}" -f "${BUILD_CONTEXT}/Dockerfile" "${BUILD_CONTEXT}"
if [[ "${PUSH}" == "1" ]]; then
    docker push "${IMAGE}"
fi

printf 'SciModelingBench image ready: %s\n' "${IMAGE}"
