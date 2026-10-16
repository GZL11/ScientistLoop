"""NatureBench 可信评分设施的 Agent 侧代理。"""
from __future__ import annotations

import errno
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ...facilities import EvaluationRequest, EvaluationResult
from .benchmark import _agent_view, attempt_id_from_artifact

# 旧发布目录挪走之后的清理重试。清理失败**不影响本次评测**，这几次重试只是
# 想让常见的短暂占用（评测子进程刚退出、NFS 还没回收句柄）不至于留下垃圾。
_CLEANUP_ATTEMPTS = 3
_CLEANUP_BACKOFF_SEC = 0.5
# NFS 上「文件还开着」会以这两个 errno 冒出来：unlink 被转成 silly-rename
# （`.nfsXXXX`），随后的 rmdir 就撞上 ENOTEMPTY；直接动那个 silly-rename 文件
# 本身则是 EBUSY。二者都不代表发布失败。
_BUSY_ERRNOS = frozenset({errno.EBUSY, errno.ENOTEMPTY})


def _discard_path(path: Path) -> None:
    """尽力删除已经改名让位的旧发布目录，失败只留垃圾、不抛异常。"""

    for index in range(_CLEANUP_ATTEMPTS):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if exc.errno not in _BUSY_ERRNOS or index == _CLEANUP_ATTEMPTS - 1:
                return
            time.sleep(_CLEANUP_BACKOFF_SEC * (index + 1))


def _replace_path(source: Path, destination: Path) -> None:
    """用不保留符号链接的真实副本原子替换 canonical 发布路径。

    **不能原地 rmtree 再 copytree。** 这个 run 目录在 CFS/NFS 上，只要还有任何
    进程（上一次评测的子进程、Judge、Agent 的后台残留）持着 ``output/`` 下的文件，
    NFS 就会把 unlink 转成 silly-rename ``.nfsXXXX``，于是 ``rmtree`` 以
    ``OSError(39, 'Directory not empty')`` 或 ``OSError(16, 'Device or resource
    busy')`` 结束——**整次评测就这么废掉**，线上 s41592-023-02148-8 连着三次
    attempt（0004/0005/0006）都死在这里，报到上层是
    ``evaluator/analysis failed: OSError(16, ...)``。

    改成「先拷到同目录的临时名 → rename 让位 → rename 就位 → 事后清理」：

    * ``rename`` 在 NFS 上对**开着的文件照样成功**，所以关键路径不再依赖「没人
      占用」这个我们控制不了的前提；
    * 清理旧目录退化成尽力而为，失败最多留下垃圾目录，不再影响评分；
    * ``output/`` 不存在的窗口从「整个 copytree 期间」缩短到两次 rename 之间。

    临时目录必须与 ``destination`` **同父**：跨设备的 ``os.replace`` 会
    ``EXDEV``，而这里正是要靠 rename 的原子性。
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    token = f".{destination.name}.publish.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    staged = destination.parent / token
    _discard_path(staged)
    if source.is_dir():
        shutil.copytree(source, staged, symlinks=False)
    else:
        shutil.copy2(source, staged)

    superseded: Path | None = None
    if destination.exists() or destination.is_symlink():
        superseded = destination.parent / f"{token}.superseded"
        os.rename(destination, superseded)
    try:
        os.rename(staged, destination)
    except OSError:
        # 让位成功但就位失败：把旧发布原样放回去，别留下一个空的 canonical 路径。
        if superseded is not None and not destination.exists():
            os.rename(superseded, destination)
            superseded = None
        _discard_path(staged)
        raise
    if superseded is not None:
        _discard_path(superseded)


def _transport_request(transport: Any, *, operation: str, attempt_id: str) -> dict[str, Any]:
    """调用可信 transport 的统一操作接口。"""

    request = getattr(transport, "request", None)
    if not callable(request):
        raise TypeError("Evaluator transport 必须实现 request(operation, attempt_id)")
    value = request(operation=operation, attempt_id=attempt_id)
    if not isinstance(value, dict):
        raise TypeError("trusted evaluator response must be an object")
    return value


class NatureBenchEvaluationFacility:
    """发布 NatureBench Artifact 并通过可信 transport 获取官方评分。"""

    def __init__(
        self,
        transport: Any,
        *,
        run_dir: str | Path,
        workspace_dir: str | Path,
        benchmark_name: str,
    ):
        """保存可信 transport 和唯一 canonical output 发布位置。"""

        self.transport = transport
        self.run_dir = Path(run_dir).expanduser().resolve()
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.benchmark_name = str(benchmark_name)
        self._official_eval_lock = threading.Lock()

    def evaluate(self, request: EvaluationRequest) -> EvaluationResult:
        """验证 Artifact 哈希，发布快照并请求 NatureBench 正式评分。"""

        request.artifact_ref.verify()
        artifact_path = request.artifact_ref.storage_path
        attempt_id = attempt_id_from_artifact(self.run_dir, artifact_path)
        artifact = Path(artifact_path).resolve()
        # 发布与评分使用同一把锁，防止并发 Candidate 覆盖固定 output。
        with self._official_eval_lock:
            _replace_path(artifact, self.workspace_dir / "output")
            raw = _transport_request(
                self.transport,
                operation="evaluate",
                attempt_id=attempt_id,
            )
        # Transport 是隔离边界。即使某个可信代理错误地返回了额外字段，
        # 进入 Controller 和 Agent 工作目录前也必须再次经过公开字段白名单。
        public = _agent_view(raw, source="official_evaluator")
        metrics = public.get("official_metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        return EvaluationResult(
            request_id=str(raw.get("request_id") or f"evaluation-{attempt_id}"),
            attempt_id=attempt_id,
            valid=raw.get("valid") is True,
            metrics=metrics,
            stdout=str(public.get("stdout") or ""),
            stderr=str(public.get("stderr") or ""),
            extra=dict(public.get("extra") or {}),
            diagnostics_public=dict(public.get("diagnostics_public") or {}),
            error=str(public["error"]) if public.get("error") else None,
            metadata={
                "benchmark": self.benchmark_name,
                "artifact": artifact_path,
                "redacted_for_agent": True,
                **{
                    key: public[key]
                    for key in (
                        "execution_id",
                        "agent_log_dir",
                        "stdout_path",
                        "stderr_path",
                    )
                    if isinstance(public.get(key), str)
                },
            },
        )

    def request_operation(self, *, operation: str, attempt_id: str) -> dict[str, Any]:
        """供 NatureBench Adapter 发起其声明的可信收尾操作。"""

        return _transport_request(
            self.transport,
            operation=operation,
            attempt_id=attempt_id,
        )

    def agent_view(
        self,
        result: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        """按正式评分白名单生成 Agent 可见结果。"""

        return _agent_view(result, source=source)

    def close(self) -> None:
        """关闭底层可信 transport。"""

        self.transport.close()


__all__ = ["NatureBenchEvaluationFacility"]
