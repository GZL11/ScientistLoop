"""合规判定的网关抖动重试。

实测背景（2026-08-27 ~ 09-07）：容器内 judge 打网关时会间歇性拿到
``HTTP 502``，同一天里成功与 502 混着出现——

    08-27  共 10  成功  4  502 失败  6
    09-01  共 15  成功  0  502 失败 15
    09-06  共 25  成功 10  502 失败 15

事后实测该网关服务 gpt-5.5 正常（HTTP 200），所以不是端点配错，是上游抖动。
此前没有任何重试：一次抖动就把 ``is_valid`` 永久写成 ``null``，导致该 Run
既被提交包判为「缺少布尔 Judge 结论」而排除，又因 ``judge_verdict = None``
进不了跨任务经验目录，只能事后手工跑主机侧补判——积压了 35 个。

两条不可越界的红线：

1. **明确的 True/False 绝不重判**——那会退化成「挑一个更宽松的判官」，
   是结果导向的筛选。
2. **非抖动类失败不重试**——缺 API key、证据缺失、脚本崩溃重试多少次都一样，
   重试只会掩盖真实故障。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from famou_scientist.loop.integrations.naturebench import evaluator_worker as worker


# --- 什么算可重试 ---------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "judge_error: HTTP 502: request failed",          # 实测的那一个
        "judge_error: HTTP 500: internal error",
        "judge_error: HTTP 503: service unavailable",
        "judge_error: HTTP 504: gateway timeout",
        "judge_error: HTTP 429: too many requests",
        "judge_error: Bad Gateway",
        "judge_error: Service Unavailable",
        "judge_error: Too Many Requests",
        "judge_error: rate limit exceeded",
        "judge_error: ReadTimeout: timed out",
        "judge_error: Connection reset by peer",
        "judge_error: connection refused",
        "judge_error: temporarily unavailable",
        "judge_error: RemoteDisconnected: Remote end closed connection",
        "judge_error: SSLError: EOF occurred in violation of protocol",
    ],
)
def test_gateway_flake_is_retryable(reason):
    assert worker._is_retryable_judge_error({"is_valid": None, "reason": reason}) is True


@pytest.mark.parametrize(
    "reason",
    [
        "judge_error: no API key",
        "judge_error: FileNotFoundError: submissions.json",
        "judge_error: ValueError: missing best attempt",
        "judge_error: HTTP 401: unauthorized",
        "judge_error: HTTP 403: forbidden",
        "judge_error: HTTP 404: model not found",
        "judge_error: invalid model name",
        "",
    ],
)
def test_deterministic_failures_are_not_retryable(reason):
    """重试只会掩盖真实故障。缺 key、证据缺失、鉴权失败重试多少次都一样。"""

    assert worker._is_retryable_judge_error({"is_valid": None, "reason": reason}) is False


@pytest.mark.parametrize("decided", [True, False])
def test_a_decided_verdict_is_never_retried(decided):
    """红线：明确结论不能重判，否则等于挑一个更宽松的判官。"""

    verdict = {"is_valid": decided, "reason": "judge_error: HTTP 502: request failed"}
    assert worker._is_retryable_judge_error(verdict) is False


def test_missing_is_valid_key_with_flake_reason_is_retryable():
    assert worker._is_retryable_judge_error({"reason": "HTTP 502"}) is True


# --- 重试驱动 -------------------------------------------------------------


class _Runner:
    """按脚本依次返回预设的 judge stdout。"""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.calls = 0

    def __call__(self, argv, **kwargs):
        self.calls += 1
        value = self.verdicts[min(self.calls - 1, len(self.verdicts) - 1)]

        class _Result:
            stdout = json.dumps(value, ensure_ascii=False)
            stderr = ""
            returncode = 0 if isinstance(value.get("is_valid"), bool) else 2

        return _Result()


FLAKE = {"is_valid": None, "reason": "judge_error: HTTP 502: request failed"}
VALID = {"is_valid": True, "reason": "端到端学习流水线，无硬编码答案。"}
INVALID = {"is_valid": False, "reason": "run.py 直接写入目标值。"}
NO_KEY = {"is_valid": None, "reason": "judge_error: no API key"}


def _run(monkeypatch, tmp_path: Path, verdicts):
    runner = _Runner(verdicts)
    slept: list[float] = []
    monkeypatch.setattr(worker.subprocess, "run", runner)
    verdict, _stdout, _stderr, _code = worker._judge(
        judge_script=tmp_path / "judge.py",
        task_dir=tmp_path,
        run_dir=tmp_path,
        best_attempt_id="0005",
        request_id="req-1",
        agent_runtime="claude",
        model="gpt-5.5",
        timeout_sec=60.0,
        submissions_path=tmp_path / "submissions.json",
        submission_map_path=tmp_path / "map.json",
        sleep=slept.append,
    )
    return verdict, runner, slept


def test_a_single_flake_recovers_on_retry(monkeypatch, tmp_path: Path):
    verdict, runner, slept = _run(monkeypatch, tmp_path, [FLAKE, VALID])

    assert verdict["is_valid"] is True
    assert runner.calls == 2
    assert slept == [5.0]


def test_two_flakes_then_success(monkeypatch, tmp_path: Path):
    verdict, runner, slept = _run(monkeypatch, tmp_path, [FLAKE, FLAKE, VALID])

    assert verdict["is_valid"] is True
    assert runner.calls == 3
    assert slept == [5.0, 20.0]


def test_retries_are_bounded(monkeypatch, tmp_path: Path):
    """判定跑在可信评测进程里，不能无限重试拖住整个 Run 的收尾。"""

    verdict, runner, slept = _run(monkeypatch, tmp_path, [FLAKE])

    assert verdict["is_valid"] is None
    assert runner.calls == 4
    assert slept == [5.0, 20.0, 60.0]


def test_success_on_first_try_does_not_sleep(monkeypatch, tmp_path: Path):
    verdict, runner, slept = _run(monkeypatch, tmp_path, [VALID])

    assert verdict["is_valid"] is True
    assert runner.calls == 1
    assert slept == []


def test_invalid_verdict_is_accepted_immediately(monkeypatch, tmp_path: Path):
    """判为违规是有效结论，必须一次落定。"""

    verdict, runner, slept = _run(monkeypatch, tmp_path, [INVALID, VALID])

    assert verdict["is_valid"] is False
    assert runner.calls == 1
    assert slept == []


def test_deterministic_failure_is_not_retried(monkeypatch, tmp_path: Path):
    verdict, runner, slept = _run(monkeypatch, tmp_path, [NO_KEY, VALID])

    assert verdict["is_valid"] is None
    assert runner.calls == 1
    assert slept == []


# --- 重试证据 -------------------------------------------------------------


def test_attempts_are_recorded_when_a_retry_happened(monkeypatch, tmp_path: Path):
    """没有这条证据就分不出「一次就成」和「重试后才成」，也看不出抖动多频繁。"""

    verdict, _runner, _slept = _run(monkeypatch, tmp_path, [FLAKE, FLAKE, VALID])

    attempts = verdict["judge_attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2, 3]
    assert [a["is_valid"] for a in attempts] == [None, None, True]
    assert "502" in attempts[0]["reason"]


def test_no_attempts_field_when_it_succeeded_first_try(monkeypatch, tmp_path: Path):
    """绝大多数判定一次成功，不给它们增加噪声字段。"""

    verdict, _runner, _slept = _run(monkeypatch, tmp_path, [VALID])

    assert "judge_attempts" not in verdict


def test_exhausted_retries_keep_the_last_reason(monkeypatch, tmp_path: Path):
    verdict, _runner, _slept = _run(monkeypatch, tmp_path, [FLAKE])

    assert "502" in verdict["reason"]
    assert len(verdict["judge_attempts"]) == 4


def test_unparsable_stdout_is_treated_as_a_failure(monkeypatch, tmp_path: Path):
    """judge 子进程崩溃时 stdout 里没有 JSON——不能当成有效结论。"""

    class _Broken:
        def __init__(self):
            self.calls = 0

        def __call__(self, argv, **kwargs):
            self.calls += 1

            class _Result:
                stdout = "Traceback (most recent call last):\n  boom\n"
                stderr = "boom"
                returncode = 1

            return _Result()

    runner = _Broken()
    monkeypatch.setattr(worker.subprocess, "run", runner)
    verdict, _stdout, _stderr, code = worker._judge(
        judge_script=tmp_path / "judge.py",
        task_dir=tmp_path,
        run_dir=tmp_path,
        best_attempt_id="0005",
        request_id="req-1",
        agent_runtime="claude",
        model="gpt-5.5",
        timeout_sec=60.0,
        submissions_path=tmp_path / "submissions.json",
        submission_map_path=tmp_path / "map.json",
        sleep=lambda _s: None,
    )

    assert verdict["is_valid"] is None
    assert code == 1
    # 解析失败不是网关抖动，不该重试。
    assert runner.calls == 1


def test_backoff_grows(monkeypatch, tmp_path: Path):
    """退避必须递增：网关抖动往往持续数十秒，等长间隔会连着撞上。"""

    assert list(worker._JUDGE_RETRY_BACKOFF_SEC) == sorted(
        worker._JUDGE_RETRY_BACKOFF_SEC
    )
    assert len(set(worker._JUDGE_RETRY_BACKOFF_SEC)) == len(
        worker._JUDGE_RETRY_BACKOFF_SEC
    )
