# -*- coding: UTF-8 -*-
"""OpenCode config healing regression tests."""
from __future__ import annotations

import json

from famou_scientist import config_heal


def _provider(npm: str) -> dict:
    return {
        "npm": npm,
        "options": {"baseURL": "https://gateway.example/v1"},
        "models": {
            "test-model": {
                "name": "Test Model",
                "limit": {"context": 200000, "output": 32000},
            }
        },
    }


def _write_config(tmp_path, payload: dict):
    path = tmp_path / "opencode.jsonc"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_custom_anthropic_gateway_gets_image_cap_and_is_idempotent(tmp_path, monkeypatch):
    path = _write_config(tmp_path, {"provider": {"gateway": _provider("@ai-sdk/anthropic")}})
    monkeypatch.setattr(config_heal, "_CONFIG_CANDIDATES", (path,))

    assert config_heal.heal_config(verbose=False) == 1
    healed = json.loads(path.read_text(encoding="utf-8"))
    assert healed["attachment"]["image"] == {
        "auto_resize": True,
        "max_base64_bytes": config_heal.DEFAULT_IMAGE_MAX_BASE64_BYTES,
    }
    first = path.read_text(encoding="utf-8")
    assert config_heal.heal_config(verbose=False) == 0
    assert path.read_text(encoding="utf-8") == first
    assert path.with_suffix(".jsonc.bak").exists()


def test_existing_attachment_config_is_preserved(tmp_path, monkeypatch):
    attachment = {"image": {"auto_resize": False, "max_base64_bytes": 999999}}
    path = _write_config(
        tmp_path,
        {"provider": {"gateway": _provider("@ai-sdk/anthropic")}, "attachment": attachment},
    )
    original = path.read_text(encoding="utf-8")
    monkeypatch.setattr(config_heal, "_CONFIG_CANDIDATES", (path,))

    assert config_heal.heal_config(verbose=False) == 0
    assert path.read_text(encoding="utf-8") == original


def test_non_anthropic_gateway_does_not_get_image_cap(tmp_path, monkeypatch):
    path = _write_config(tmp_path, {"provider": {"gateway": _provider("@ai-sdk/openai")}})
    original = path.read_text(encoding="utf-8")
    monkeypatch.setattr(config_heal, "_CONFIG_CANDIDATES", (path,))

    assert config_heal.heal_config(verbose=False) == 0
    assert path.read_text(encoding="utf-8") == original
