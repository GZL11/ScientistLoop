"""Agent-readable copies of trusted evaluator execution logs."""
from __future__ import annotations

from pathlib import Path

from ..utils import atomic_write_json


def write_agent_log_copy(
    root: str | Path,
    *,
    request_id: str,
    stdout: str,
    stderr: str,
) -> dict[str, str]:
    """Write a read-only per-request log view without exposing trusted paths."""

    safe_id = str(request_id)
    if not safe_id or Path(safe_id).name != safe_id or safe_id in {".", ".."}:
        raise ValueError(f"invalid evaluator request id: {request_id!r}")
    directory = Path(root).expanduser().resolve() / safe_id
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o755)
    paths = {"stdout_path": directory / "stdout.log", "stderr_path": directory / "stderr.log"}
    for path, content in ((paths["stdout_path"], stdout), (paths["stderr_path"], stderr)):
        path.write_text(str(content or ""), encoding="utf-8")
        path.chmod(0o644)
    manifest = directory / "manifest.json"
    atomic_write_json(manifest, {
        "execution_id": safe_id,
        "files": ["stdout.log", "stderr.log"],
        "visibility": "agent_read_only",
    })
    manifest.chmod(0o644)
    return {
        "execution_id": safe_id,
        "agent_log_dir": str(directory),
        "stdout_path": str(paths["stdout_path"]),
        "stderr_path": str(paths["stderr_path"]),
    }


__all__ = ["write_agent_log_copy"]
