#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${1:?usage: $0 TERMINAL_BENCH_SCIENCE_ROOT}"
REGISTRY="<你的镜像仓库>/famou-public"

declare -A TASK_DIRS=(
  [baseline-free-localization]="tasks/engineering-sciences/mechanical-engineering/baseline-free-localization"
  [guided-wave-localization]="tasks/engineering-sciences/mechanical-engineering/guided-wave-localization"
  [ankle-mri-findings]="tasks/life-sciences/medicine/ankle-mri-findings"
  [finite-free-stam]="tasks/mathematical-sciences/formal-mathematics/finite-free-stam"
  [ode-law-discovery]="tasks/mathematical-sciences/applied-mathematics/ode-law-discovery"
  [small-area-equivalence]="tasks/mathematical-sciences/statistics/small-area-equivalence"
  [tamp-skill-planning]="tasks/engineering-sciences/mechanical-engineering/tamp-skill-planning"
)

tasks=(
  baseline-free-localization
  guided-wave-localization
  ankle-mri-findings
  ode-law-discovery
  small-area-equivalence
  tamp-skill-planning
  finite-free-stam
)

proxy_args=()
for variable in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
  if [[ -n "${!variable:-}" ]]; then
    proxy_args+=(--build-arg "$variable")
  fi
done

for task in "${tasks[@]}"; do
  task_dir="$SOURCE_ROOT/${TASK_DIRS[$task]}"
  test -f "$task_dir/tests/Dockerfile"
  test -f "$task_dir/tests/test.sh"
  target="$REGISTRY/tb-science-${task}-verifier:official-v1"
  # Harbor's verifier Dockerfile must be built with tests/ as the context;
  # this keeps hidden verifier data inside the image and mirrors Harbor.
  docker build --network=host \
    "${proxy_args[@]}" \
    -f "$task_dir/tests/Dockerfile" \
    -t "$target" \
    "$task_dir/tests"
  docker push "$target"
  docker run --rm "$target" test -r /tests/test.sh
done
