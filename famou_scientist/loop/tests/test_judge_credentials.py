"""Judge 凭据链路的三道防线。

这条链路反复出问题：容器内 judge 拿不到 key -> 判定写出 is_valid=null ->
Run 照常"成功"结束 -> 提交包错判、跨任务经验因 agent_visible=False 无法回流。
每次都要事后手工补判，已重复四次。这里覆盖三处修正：

1. gpt-5.5 走 OpenAI 分支，凭据别名此前只补了 Anthropic 一侧
2. 缺凭据时启动即失败，不把配置错误留到判定时才显现
3. 补判结论写在独立批次目录，消费方必须能读到，否则永远看到 null
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from famou_scientist.loop.integrations.naturebench.evaluator_worker import (
    _assert_judge_credentials,
    _judge_provider_for_model,
    _load_trusted_settings,
)


JUDGE_KEYS = (
    "JUDGE_OPENAI_API_KEY",
    "JUDGE_ANTHROPIC_API_KEY",
    "JUDGE_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "JUDGE_OPENAI_BASE_URL",
    "JUDGE_BASE_URL",
    "ANTHROPIC_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in JUDGE_KEYS:
        monkeypatch.delenv(key, raising=False)


def _settings(tmp_path: Path, env: dict[str, str]) -> Path:
    path = tmp_path / "judge_settings.json"
    path.write_text(json.dumps({"env": env}), encoding="utf-8")
    return path


# --- 1. provider 分流 --------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-5.5", "openai"),
        ("gpt-4o", "openai"),
        ("claude-opus-5", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
        (None, "anthropic"),
        ("", "anthropic"),
    ],
)
def test_provider_routing(model, expected):
    assert _judge_provider_for_model(model) == expected


def test_auth_token_fills_openai_key(tmp_path, monkeypatch):
    """回归点：gpt-5.5 走 OpenAI 分支，此前只补 Anthropic 别名导致必然缺 key。"""

    _load_trusted_settings(_settings(tmp_path, {"ANTHROPIC_AUTH_TOKEN": "tok"}))
    assert os.environ["JUDGE_OPENAI_API_KEY"] == "tok"
    assert os.environ["JUDGE_ANTHROPIC_API_KEY"] == "tok"


def test_explicit_keys_are_not_overwritten(tmp_path):
    _load_trusted_settings(
        _settings(
            tmp_path,
            {
                "ANTHROPIC_AUTH_TOKEN": "tok",
                "JUDGE_OPENAI_API_KEY": "explicit",
            },
        )
    )
    assert os.environ["JUDGE_OPENAI_API_KEY"] == "explicit"


def test_openai_base_url_derived_from_gateway(tmp_path):
    """OpenAI 分支不回落 ANTHROPIC_BASE_URL，缺省会打到官方端点而非本部署网关。"""

    _load_trusted_settings(
        _settings(
            tmp_path,
            {"ANTHROPIC_AUTH_TOKEN": "tok", "ANTHROPIC_BASE_URL": "https://gw.example"},
        )
    )
    assert os.environ["JUDGE_OPENAI_BASE_URL"] == "https://gw.example/v1"


def test_explicit_base_url_wins(tmp_path):
    _load_trusted_settings(
        _settings(
            tmp_path,
            {
                "ANTHROPIC_BASE_URL": "https://gw.example",
                "JUDGE_OPENAI_BASE_URL": "https://judge.example/v1",
            },
        )
    )
    assert os.environ["JUDGE_OPENAI_BASE_URL"] == "https://judge.example/v1"


# --- 2. 启动即校验 ----------------------------------------------------


def test_missing_openai_key_fails_fast(monkeypatch):
    """缺凭据必须在 Run 开始前失败，而不是产出一份未判定的结果。"""

    monkeypatch.setenv("JUDGE_ANTHROPIC_API_KEY", "only-anthropic")
    with pytest.raises(RuntimeError, match="JUDGE_OPENAI_API_KEY"):
        _assert_judge_credentials("gpt-5.5")


def test_missing_anthropic_key_fails_fast():
    with pytest.raises(RuntimeError, match="JUDGE_ANTHROPIC_API_KEY"):
        _assert_judge_credentials("claude-opus-5")


@pytest.mark.parametrize(
    "model,key",
    [
        ("gpt-5.5", "JUDGE_OPENAI_API_KEY"),
        ("gpt-5.5", "JUDGE_API_KEY"),
        ("claude-opus-5", "JUDGE_ANTHROPIC_API_KEY"),
        ("claude-opus-5", "ANTHROPIC_API_KEY"),
    ],
)
def test_any_accepted_key_passes(model, key, monkeypatch):
    monkeypatch.setenv(key, "k")
    _assert_judge_credentials(model)


def test_error_message_names_the_missing_variables():
    """报错要能直接指导修复，而不是只说"失败了"。"""

    with pytest.raises(RuntimeError) as excinfo:
        _assert_judge_credentials("gpt-5.5")
    message = str(excinfo.value)
    assert "gpt-5.5" in message
    assert "openai" in message
    assert "JUDGE_OPENAI_API_KEY" in message


def test_gate_only_applies_when_judge_enabled():
    """未启用 validity judge 的 Run 不受该校验影响。

    judge_enabled = run_dir is not None；不写 run_dir 的评测路径（如纯签名
    结果验证）本就不会调用 judge，缺凭据不该阻断它们。
    """

    import inspect

    from famou_scientist.loop.integrations.naturebench import evaluator_worker

    source = inspect.getsource(evaluator_worker.main)
    index = source.index("_assert_judge_credentials")
    # 该调用必须处于 judge_enabled 分支内。
    assert "if judge_enabled:" in source[:index]


# --- 3. 补判结论必须可被消费 -------------------------------------------


def _sync_module():
    import importlib.util

    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "naturebench"
        / "fmjob"
        / "sync_cross_task_expbank.py"
    )
    spec = importlib.util.spec_from_file_location("sync_cte", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_with(tmp_path: Path, root: dict | None, batches: dict[str, dict]) -> Path:
    run = tmp_path / "run"
    (run / "controller").mkdir(parents=True)
    if root is not None:
        (run / "controller" / "judge_verdict.json").write_text(
            json.dumps(root), encoding="utf-8"
        )
    for name, value in batches.items():
        batch = run / "controller" / "naturebench_judge" / name
        batch.mkdir(parents=True)
        (batch / "judge_verdict.json").write_text(json.dumps(value), encoding="utf-8")
    return run


def test_rejudge_overrides_null_placeholder(tmp_path):
    """回归点：只读 controller/judge_verdict.json 会永远看到补判前的 null。"""

    run = _run_with(
        tmp_path,
        {"is_valid": None, "reason": "judge_error: no API key"},
        {"gpt-5.5-rejudge-20260826": {"is_valid": True, "model": "gpt-5.5"}},
    )
    verdict = _sync_module()._resolve_verdict(run)
    assert verdict["is_valid"] is True


def test_undecided_batches_are_ignored(tmp_path):
    """补判批次自身也可能失败；null 不能盖掉根部结论。"""

    run = _run_with(
        tmp_path,
        {"is_valid": False, "model": "gpt-5.5"},
        {"failed-batch": {"is_valid": None, "reason": "judge_error"}},
    )
    verdict = _sync_module()._resolve_verdict(run)
    assert verdict["is_valid"] is False


def test_latest_batch_wins_by_mtime(tmp_path):
    """按 mtime 而非目录名：字典序会让 formal-rejudge-20260820 排在 rejudge-20260819 前。"""

    run = _run_with(
        tmp_path,
        None,
        {
            "gpt-5.5-rejudge-20260819": {"is_valid": False, "model": "gpt-5.5"},
            "gpt-5.5-formal-rejudge-20260820": {"is_valid": True, "model": "gpt-5.5"},
        },
    )
    newer = (
        run
        / "controller"
        / "naturebench_judge"
        / "gpt-5.5-formal-rejudge-20260820"
        / "judge_verdict.json"
    )
    os.utime(newer, (2_000_000_000, 2_000_000_000))
    verdict = _sync_module()._resolve_verdict(run)
    assert verdict["is_valid"] is True


def test_falls_back_to_root_when_no_batches(tmp_path):
    run = _run_with(tmp_path, {"is_valid": True, "model": "gpt-5.5"}, {})
    assert _sync_module()._resolve_verdict(run)["is_valid"] is True


def test_returns_none_when_nothing_recorded(tmp_path):
    run = _run_with(tmp_path, None, {})
    assert _sync_module()._resolve_verdict(run) is None
