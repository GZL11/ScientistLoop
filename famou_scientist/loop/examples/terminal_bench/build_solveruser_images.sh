#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="<你的镜像仓库>/famou-public"
DOCKERFILE="$ROOT_DIR/Dockerfile.add_solveruser"

tasks=(
  guided-wave-localization
  ankle-mri-findings
  finite-free-stam
  ode-law-discovery
  small-area-equivalence
  tamp-skill-planning
)

for task in "${tasks[@]}"; do
  base="$REGISTRY/tb-science-${task}-agent:claude-code"
  target="$REGISTRY/tb-science-${task}-agent:claude-code-solveruser-v1"
  docker build --network=host \
    --build-arg "BASE_IMAGE=$base" \
    -f "$DOCKERFILE" \
    -t "$target" \
    "$ROOT_DIR"
  docker push "$target"
done
