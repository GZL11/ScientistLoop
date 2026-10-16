# -*- coding: UTF-8 -*-
from __future__ import annotations

from famou_scientist import assets


def test_registry_loads():
    reg = assets.load_registry()
    assert reg["schema_version"] == 1
    assert reg["prompts"][0]["id"] == "agents"


def test_assets_check_passes(capsys):
    rc = assets.main(["check"])
    out = capsys.readouterr()
    assert rc == 0
    assert "asset registry check passed" in out.out


def test_assets_show_agents(capsys):
    rc = assets.main(["show", "prompts/agents"])
    out = capsys.readouterr()
    assert rc == 0
    assert '"category": "prompts"' in out.out
    assert '"id": "agents"' in out.out


def test_tool_registry_is_split_by_export():
    reg = assets.load_registry()
    tools = {item["id"]: item for item in reg["tools"]}
    assert "search_literature" in tools
    assert "latex_check" in tools
    assert tools["lookup_paper"]["enabled"] is False
    assert tools["search_literature"]["versions_dir"] != tools["lookup_paper"]["versions_dir"]
    assert tools["latex_check"]["versions_dir"] != tools["search_literature"]["versions_dir"]
