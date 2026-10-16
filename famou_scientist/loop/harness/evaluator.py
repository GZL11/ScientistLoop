"""Harness 调用可信 evaluator 的统一客户端。"""
from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..utils import atomic_write_json, new_id, now_ms


class EvaluatorError(RuntimeError):
    """表示可信 evaluator 调用或验签失败。"""


@runtime_checkable
class EvaluatorClient(Protocol):
    """定义 Harness 可调用的正式评测接口。"""

    def request(self, *, operation: str, attempt_id: str) -> dict[str, Any]:
        """调用由 Evaluator Adapter 声明的可信操作。"""
        ...

    def evaluate(self, *, attempt_id: str) -> dict[str, Any]:
        """评测固定 canonical output 并返回正式结果。"""
        ...

    def close(self) -> None:
        """关闭 evaluator 客户端并释放资源。"""
        ...


class FileEvaluatorClient:
    """通过签名文件队列调用独立可信评测 Job。"""

    def __init__(
        self,
        channel_dir: str | Path,
        *,
        public_key: str | Path | None = None,
        timeout_sec: float = 3600,
        poll_interval_sec: float = 1.0,
        allow_unsigned: bool = False,
        cancel_file: str | Path | None = None,
    ):
        """初始化请求/响应目录及签名校验策略。"""
        self.root = Path(channel_dir).expanduser().resolve()
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        self.requests.mkdir(parents=True, exist_ok=True)
        self.responses.mkdir(parents=True, exist_ok=True)
        self.public_key = (
            Path(public_key).expanduser().resolve() if public_key else None
        )
        self.timeout_sec = float(timeout_sec)
        self.poll_interval_sec = max(0.05, float(poll_interval_sec))
        self.allow_unsigned = bool(allow_unsigned)
        self.cancel_file = (
            Path(cancel_file).expanduser().resolve()
            if cancel_file is not None
            else None
        )
        if not self.allow_unsigned and (
            self.public_key is None or not self.public_key.is_file()
        ):
            raise EvaluatorError("signed file evaluator requires a public key")
        # 在任何 Agent 启动前固定公钥内容。仅保存路径不够，因为共享目录中的
        # 文件可能被替换，验签前必须再次与这里的初始字节比较。
        self._public_key_bytes = (
            self.public_key.read_bytes()
            if self.public_key is not None and self.public_key.is_file()
            else b""
        )
        self.public_key_sha256 = hashlib.sha256(self._public_key_bytes).hexdigest()

    def _verify(self, response_path: Path, signature_path: Path) -> None:
        """使用 OpenSSL 公钥校验 evaluator 响应签名。"""
        # unsigned 只允许本地测试显式开启；生产文件通道必须走下面的验签路径。
        if self.allow_unsigned:
            return
        assert self.public_key is not None
        if self.public_key.read_bytes() != self._public_key_bytes:
            raise EvaluatorError(
                "evaluator public key changed after Harness initialization; "
                f"pinned sha256={self.public_key_sha256}"
            )
        process = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(self.public_key),
                "-signature",
                str(signature_path),
                str(response_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise EvaluatorError(
                "evaluator response signature verification failed: "
                + (process.stderr or process.stdout or "unknown openssl error").strip()
            )

    def _request(self, *, kind: str, attempt_id: str) -> dict[str, Any]:
        """提交最小可信请求并等待通过固定公钥验证的响应。"""
        # request_id 关联一次请求和一次响应；attempt_id 仅用于审计。请求中故意
        # 不包含 output_dir、代码路径或私有收尾配置，可信 worker 使用启动时固定值。
        request_id = new_id("evaluator")
        request_path = self.requests / f"{request_id}.json"
        response_path = self.responses / f"{request_id}.json"
        signature_path = self.responses / f"{request_id}.sig"
        atomic_write_json(
            request_path,
            {
                "request_id": request_id,
                "kind": kind,
                "attempt_id": attempt_id,
                "created_at": now_ms(),
            },
        )
        deadline = time.monotonic() + self.timeout_sec
        while time.monotonic() < deadline:
            if self.cancel_file is not None and self.cancel_file.is_file():
                raise EvaluatorError(
                    "evaluator request cancelled by task stop: "
                    f"{self.cancel_file}"
                )
            # 响应 JSON 与签名都完整出现后才读取，避免观察到 evaluator 写入一半
            # 的文件；实际写入端也使用原子替换进一步保证一致性。
            if response_path.is_file() and (
                self.allow_unsigned or signature_path.is_file()
            ):
                self._verify(response_path, signature_path)
                try:
                    result = json.loads(response_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise EvaluatorError(f"invalid evaluator response JSON: {exc}") from exc
                if not isinstance(result, dict):
                    raise EvaluatorError("evaluator response must be a JSON object")
                if result.get("request_id") != request_id:
                    raise EvaluatorError("evaluator response request_id mismatch")
                if not self.allow_unsigned and result.get("redacted_for_agent") is not True:
                    raise EvaluatorError(
                        "evaluator response is missing redacted_for_agent=true"
                    )
                return result
            time.sleep(self.poll_interval_sec)
        raise EvaluatorError(
            f"evaluator timed out after {self.timeout_sec:g}s for request {request_id}"
        )

    def evaluate(self, *, attempt_id: str) -> dict[str, Any]:
        """请求可信 worker 评测固定 canonical output。"""
        return self.request(operation="evaluate", attempt_id=attempt_id)

    def request(self, *, operation: str, attempt_id: str) -> dict[str, Any]:
        """通过签名文件通道调用一个 Adapter 定义的可信操作。"""

        kind = str(operation).strip()
        if not kind or any(character in kind for character in "/\\"):
            raise ValueError(f"invalid evaluator operation: {operation!r}")
        return self._request(kind=kind, attempt_id=attempt_id)

    def close(self) -> None:
        """写入客户端结束标记，允许单运行 worker 正常退出。"""
        # worker 至少处理完已提交请求后再根据该标记退出，避免由 Agent 直接终止
        # 可信评测进程。
        atomic_write_json(self.root / "CLIENT_DONE.json", {"created_at": now_ms()})


class HttpEvaluatorClient:
    """调用固定任务、固定输出目录的可信 HTTP evaluator 代理。"""

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        timeout_sec: float = 3600,
        cancel_file: str | Path | None = None,
        poll_interval_sec: float = 0.1,
    ):
        """初始化可信代理地址和可选令牌。"""
        self.url = url.rstrip("/")
        self.token = token
        self.timeout_sec = float(timeout_sec)
        self.cancel_file = (
            Path(cancel_file).expanduser().resolve()
            if cancel_file is not None
            else None
        )
        self.poll_interval_sec = max(0.05, float(poll_interval_sec))

    def evaluate(self, *, attempt_id: str) -> dict[str, Any]:
        """调用代理的 evaluate 端点且不允许传入输出路径。"""
        return self.request(operation="evaluate", attempt_id=attempt_id)

    def request(self, *, operation: str, attempt_id: str) -> dict[str, Any]:
        """调用与可信 Adapter 操作同名的固定 HTTP 端点。"""

        normalized = str(operation).strip().replace("_", "-")
        if not normalized or any(character in normalized for character in "/\\"):
            raise ValueError(f"invalid evaluator operation: {operation!r}")
        return self._post(normalized, attempt_id=attempt_id)

    def _post(self, endpoint: str, *, attempt_id: str) -> dict[str, Any]:
        """向固定任务代理发送不含文件路径的请求。"""
        # 与文件通道保持相同最小协议，HTTP 服务端自行绑定 task 和 output。
        body = json.dumps({"attempt_id": attempt_id}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.url}/{endpoint}",
            data=body,
            headers=headers,
            method="POST",
        )
        outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def send() -> None:
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_sec,
                ) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - 转交调用线程统一归一化
                outcome.put((False, exc))
            else:
                outcome.put((True, result))

        # urllib 在连接、TLS 或 response.read 阶段都可能阻塞。daemon helper 让
        # 控制线程可以轮询 stop 文件并立即退出；晚到响应不会重新进入调度器。
        threading.Thread(
            target=send,
            name="famou-http-evaluator",
            daemon=True,
        ).start()
        while True:
            if self.cancel_file is not None and self.cancel_file.is_file():
                raise EvaluatorError(
                    "HTTP evaluator request cancelled by task stop: "
                    f"{self.cancel_file}"
                )
            try:
                succeeded, result = outcome.get(timeout=self.poll_interval_sec)
            except queue.Empty:
                continue
            if not succeeded:
                if isinstance(
                    result,
                    (urllib.error.URLError, TimeoutError, json.JSONDecodeError),
                ):
                    raise EvaluatorError(f"HTTP evaluator failed: {result}") from result
                raise result
            break
        if not isinstance(result, dict):
            raise EvaluatorError("HTTP evaluator response must be a JSON object")
        return result

    def close(self) -> None:
        """HTTP evaluator 不需要客户端清理。"""
