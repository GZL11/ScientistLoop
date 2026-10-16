"""
runners/bench_config.py — 加载 bench_config.toml，提供 case 目录和 results 目录。

bench_config.toml 存绝对路径，每台机器独立配置，不提交到版本库。
模板见 bench_config.toml.example。
"""

from pathlib import Path

_TOML_PATH = Path(__file__).parent / "bench_config.toml"

if not _TOML_PATH.exists():
    raise FileNotFoundError(
        f"bench_config.toml not found: {_TOML_PATH}\n"
        f"Copy bench_config.toml.example and fill in absolute paths."
    )

import tomllib
with open(_TOML_PATH, "rb") as _f:
    _cfg = tomllib.load(_f)

_p = _cfg["paths"]

RESULTS_DIR  = Path(_p["results"])
INTERACTIVE_DIR = Path(_p.get("interactive", str(RESULTS_DIR.parent / "interactive_sessions")))

# 统一 benchmark 目录：优先读取配置，否则回退到 webagent/benchmark/cases/
CASES_DIR = Path(_p["benchmark_cases"]) if "benchmark_cases" in _p else (
    Path(__file__).resolve().parent.parent / "benchmark" / "cases"
)

# 自动回答 API 配置（可选，缺失时 --answerer api 会报错）
_answerer = _cfg.get("answerer", {})
ANSWERER_API_BASE_URL = _answerer.get("api_base_url", "")
ANSWERER_AUTH_TOKEN   = _answerer.get("auth_token", "")
ANSWERER_MODEL        = _answerer.get("model", "glm-5")

# 沙箱额外配置（可选，与内置 deny/allow 列表合并）
_sandbox = _cfg.get("sandbox", {})
SANDBOX_EXTRA_DENY_READ        = list(_sandbox.get("extra_deny_read", []))
SANDBOX_EXTRA_ALLOW_WRITE_DIRS = list(_sandbox.get("extra_allow_write_dirs", []))
SANDBOX_EXTRA_ALLOW_WRITE_FILES = list(_sandbox.get("extra_allow_write_files", []))


def resolve_case(name: str) -> Path:
    """将 case 名字解析为绝对路径（使用统一 CASES_DIR）。"""
    path = CASES_DIR / name
    if not path.is_dir():
        raise FileNotFoundError(
            f"Case '{name}' not found in {CASES_DIR}\n"
            f"Available: {[d.name for d in CASES_DIR.iterdir() if d.is_dir()]}"
        )
    return path
