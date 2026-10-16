#!/usr/bin/env bash
# Build and push the three images a Terminal-Bench Science task needs under the
# famou terminal_task harness:
#   1. tb-science-<task>-agent:claude-code            task environment + Claude Code CLI
#   2. tb-science-<task>-agent:claude-code-solveruser-v1  + official verifier runtime account
#   3. tb-science-<task>-verifier:official-v1         task-owned tests/Dockerfile (hidden GT)
#
# Usage: build_tbs_task_images.sh TERMINAL_BENCH_SCIENCE_ROOT task-slug [task-slug ...]
# Env:   SKIP_PUSH=1 to build only; KEEP_INTERMEDIATE=1 to keep base layers.
set -Eeuo pipefail

SOURCE_ROOT="${1:?usage: $0 TERMINAL_BENCH_SCIENCE_ROOT task [task ...]}"
shift
[[ $# -ge 1 ]] || { echo "at least one task slug required" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${REGISTRY:-<你的镜像仓库>/famou-public}"
SOLVERUSER_DOCKERFILE="$HERE/Dockerfile.add_solveruser"

build_args=()
for variable in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
  if [[ -n "${!variable:-}" ]]; then
    build_args+=(--build-arg "$variable=${!variable}")
  fi
done

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

resolve_task_dir() {
  local slug="$1"
  local found
  found="$(find "$SOURCE_ROOT/tasks" -mindepth 3 -maxdepth 3 -type d -name "$slug" | head -1)"
  [[ -n "$found" ]] || { echo "task not found under $SOURCE_ROOT/tasks: $slug" >&2; return 1; }
  printf '%s\n' "$found"
}

# Task Dockerfiles often pin a registry digest that the local mirror cannot
# resolve. Pre-pull each FROM image; when that fails and a digest-free tag of
# the same image exists locally, rewrite the FROM line in a temporary copy.
# Direct PyPI is unreachable/slow from the build host; inject the mirror the
# host itself uses. Lock files with --require-hashes still verify the same
# wheel digests, so this does not change what gets installed.
PIP_MIRROR="${PIP_MIRROR:-http://mirrors.baidubce.com/pypi/simple/}"
PIP_MIRROR_HOST="${PIP_MIRROR_HOST:-mirrors.baidubce.com}"
APT_MIRROR_HOST="${APT_MIRROR_HOST:-mirrors.baidubce.com}"
# Shell snippet (kept single-quoted so $f is literal) that rewrites Debian
# (sources.list and deb822) and Ubuntu apt sources; no-op on images without apt.
APT_FIX='for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do [ -f "$f" ] && sed -i -e "s|deb.debian.org|MIRROR|g" -e "s|security.debian.org|MIRROR|g" -e "s|archive.ubuntu.com|MIRROR|g" -e "s|security.ubuntu.com|MIRROR|g" "$f"; done; true'
APT_FIX="${APT_FIX//MIRROR/$APT_MIRROR_HOST}"
# Rewrites Debian (both sources.list and deb822) and Ubuntu apt sources; no-op
# on images without apt.

prepare_dockerfile() {
  local dockerfile="$1" out="$2"
  # Some task Dockerfiles are CRLF; the stray \r would otherwise become part of
  # the image reference (hbv-calibration-1).
  tr -d '\r' < "$dockerfile" > "$out"
  if [[ -n "$PIP_MIRROR" ]]; then
    # Insert after every FROM line so each build stage inherits the mirror.
    sed -i "/^FROM /a ENV PIP_INDEX_URL=${PIP_MIRROR} PIP_TRUSTED_HOST=${PIP_MIRROR_HOST}" "$out"
  fi
  if [[ -n "$APT_MIRROR_HOST" ]]; then
    # deb.debian.org / archive.ubuntu.com crawl at ~50 KB/s from this host; the
    # internal mirror serves the same archives at full speed.
    awk -v fix="$APT_FIX" '{print} /^FROM /{print "RUN " fix}' "$out" > "$out.tmp" && mv "$out.tmp" "$out"
  fi
  local line ref bare
  while IFS= read -r line; do
    ref="$(printf '%s' "$line" | awk '{print $2}')"
    [[ "$ref" == *"\${"* ]] && continue         # ARG-driven FROM, leave alone
    [[ "$ref" == *" AS "* ]] && ref="${ref%% *}"
    # Skip stage references (FROM builder AS x).
    grep -qE "^FROM .* AS ${ref}\$" "$out" && continue
    if docker image inspect "$ref" >/dev/null 2>&1; then
      continue
    fi
    if docker pull "$ref" >/dev/null 2>&1; then
      continue
    fi
    bare="${ref%%@*}"
    if [[ "$bare" != "$ref" ]] && docker image inspect "$bare" >/dev/null 2>&1; then
      log "  FROM $ref not pullable; using local $bare"
      sed -i "s|${ref//|/\\|}|${bare}|g" "$out"
      continue
    fi
    if docker pull "$bare" >/dev/null 2>&1; then
      log "  FROM $ref not pullable; pulled and using $bare"
      sed -i "s|${ref//|/\\|}|${bare}|g" "$out"
      continue
    fi
    echo "cannot obtain base image $ref" >&2
    return 1
  done < <(grep -E '^FROM ' "$out")
}

build_task() {
  local slug="$1"
  local task_dir env_dir tests_dir base_tag cc_tag final_tag ver_tag tmp
  task_dir="$(resolve_task_dir "$slug")"
  env_dir="$task_dir/environment"
  tests_dir="$task_dir/tests"
  test -f "$env_dir/Dockerfile" || { echo "missing $env_dir/Dockerfile" >&2; return 1; }
  test -f "$tests_dir/Dockerfile" || { echo "missing $tests_dir/Dockerfile" >&2; return 1; }
  test -f "$tests_dir/test.sh" || { echo "missing $tests_dir/test.sh" >&2; return 1; }

  base_tag="tbs-local-${slug}-base"
  cc_tag="$REGISTRY/tb-science-${slug}-agent:claude-code"
  final_tag="$REGISTRY/tb-science-${slug}-agent:claude-code-solveruser-v1"
  ver_tag="$REGISTRY/tb-science-${slug}-verifier:official-v1"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  log "=== $slug: 1/4 task environment -> $base_tag"
  prepare_dockerfile "$env_dir/Dockerfile" "$tmp/Dockerfile.env" || return 1
  docker build --network=host "${build_args[@]}" -f "$tmp/Dockerfile.env" -t "$base_tag" "$env_dir" || return 1

  log "=== $slug: 2/4 + Claude Code CLI -> $cc_tag"
  cat > "$tmp/Dockerfile.cc" <<'EOF'
ARG TASK_BASE
FROM ${TASK_BASE}
USER root
ENV DEBIAN_FRONTEND=noninteractive
RUN for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do [ -f "$f" ] && sed -i -e "s|deb.debian.org|APT_MIRROR_HOST_PLACEHOLDER|g" -e "s|security.debian.org|APT_MIRROR_HOST_PLACEHOLDER|g" -e "s|archive.ubuntu.com|APT_MIRROR_HOST_PLACEHOLDER|g" -e "s|security.ubuntu.com|APT_MIRROR_HOST_PLACEHOLDER|g" "$f"; done; true
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates git curl jq xz-utils && rm -rf /var/lib/apt/lists/*
# Ubuntu 22.04 (rocker) ships Node 12, which Claude Code cannot run on. Install
# a Node 20 LTS tarball from the npm mirror when the distro build is too old.
RUN set -e; v="$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')"; \
    if [ -z "$v" ] || [ "$v" -lt 18 ]; then \
      curl -fsSL https://registry.npmmirror.com/-/binary/node/v20.19.2/node-v20.19.2-linux-x64.tar.xz -o /tmp/node.tar.xz \
      && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 && rm -f /tmp/node.tar.xz; \
    fi; node -v; npm -v
RUN npm install -g --registry=https://registry.npmmirror.com @anthropic-ai/claude-code
RUN command -v claude && (command -v python3 || command -v python)
EOF
  sed -i "s|APT_MIRROR_HOST_PLACEHOLDER|${APT_MIRROR_HOST}|g" "$tmp/Dockerfile.cc"
  docker build --network=host "${build_args[@]}" --build-arg "TASK_BASE=$base_tag" -f "$tmp/Dockerfile.cc" -t "$cc_tag" "$tmp" || return 1

  log "=== $slug: 3/4 + solveruser -> $final_tag"
  docker build --network=host --build-arg "BASE_IMAGE=$cc_tag" -f "$SOLVERUSER_DOCKERFILE" -t "$final_tag" "$HERE" || return 1

  log "=== $slug: 4/4 official verifier -> $ver_tag"
  prepare_dockerfile "$tests_dir/Dockerfile" "$tmp/Dockerfile.tests" || return 1
  docker build --network=host "${build_args[@]}" -f "$tmp/Dockerfile.tests" -t "$ver_tag" "$tests_dir" || return 1
  docker run --rm --entrypoint sh "$ver_tag" -c 'test -r /tests/test.sh' || return 1

  if [[ "${SKIP_PUSH:-0}" != "1" ]]; then
    log "=== $slug: push"
    docker push "$final_tag" || return 1
    docker push "$ver_tag" || return 1
  fi
  if [[ "${KEEP_INTERMEDIATE:-0}" != "1" ]]; then
    docker image rm "$base_tag" "$cc_tag" >/dev/null 2>&1 || true
  fi
  log "READY $slug agent=$final_tag verifier=$ver_tag"
}

status=0
for slug in "$@"; do
  if ! build_task "$slug"; then
    log "FAILED $slug"
    status=1
  fi
done
exit "$status"
