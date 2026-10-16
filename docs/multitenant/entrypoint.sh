#!/bin/bash
# Famou 租户容器入口。
# - 迭代期：若挂载了 CFS 源码到 $FAMOU_SRC 且尚未安装 → editable 安装（改代码即生效）。
# - 稳定期：源码已固化进镜像时，$FAMOU_SRC 不存在，跳过安装，直接用已装的 famou。
# - key：从 docker run -e 注入的 ANTHROPIC_* 环境变量读取，绝不落盘/不硬编码。
set -e

# 若挂了源码且当前 python 里没有 famou_scientist，就 editable 安装
if [ -d "${FAMOU_SRC}" ] && [ -f "${FAMOU_SRC}/pyproject.toml" ]; then
  if ! python -c "import famou_scientist" 2>/dev/null; then
    echo "[entrypoint] editable 安装 famou-scientist from ${FAMOU_SRC}"
    pip install -e "${FAMOU_SRC}" >/dev/null 2>&1 || pip install -e "${FAMOU_SRC}"
  fi
fi

# 健壮性：确认 famou 可用
if ! python -c "import famou_scientist" 2>/dev/null && ! command -v famou-scientist >/dev/null 2>&1; then
  echo "[entrypoint] ✗ famou-scientist 不可用：既没固化进镜像，也没挂载 ${FAMOU_SRC} 源码。" >&2
  echo "[entrypoint]   迭代期请 -v <CFS源码>:/app 挂载；稳定期请在 Dockerfile 里 pip install 固化。" >&2
  exit 1
fi

# 提示（不打印 key 值）
[ -n "${ANTHROPIC_BASE_URL}" ] && echo "[entrypoint] 模型网关已注入（ANTHROPIC_BASE_URL 已设）"
[ -z "${ANTHROPIC_AUTH_TOKEN}" ] && echo "[entrypoint] ⚠️ 未注入 ANTHROPIC_AUTH_TOKEN —— 模型调用会失败" >&2

exec "$@"
