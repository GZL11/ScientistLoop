# -*- coding: UTF-8 -*-
################################################################################
#
# Copyright (c) 2026 Baidu.com, Inc. All Rights Reserved
#
################################################################################
"""核心不变量测试：自包含性 + 资产完整性 + CLI 装配。

这些测试守护本项目最关键的三条不变量，任一被破坏都会让"装 opencode 即用"失效：

1. **脐带不复活**：Python 内核（scripts/）绝不能重新依赖 researchclaw。
   把 researchclaw 在 sys.modules 里封死，内核仍能 import 才算通过。
2. **资产完整**：34 个 skill + 内核 + tool/hook/AGENTS.md/opencode.json 齐全。
3. **CLI 装配**：launcher 能定位资产、build_env 注入正确的环境变量。

Authors: gezengle(gezengle@users.noreply.github.com)
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import pytest

from famou_scientist import launcher


def _scripts_dir() -> Path:
    return launcher.opencode_config_dir() / "scripts"


# ── 不变量 1：脐带不复活（最关键）─────────────────────────────
KERNEL_MODULES = [
    "models", "cache", "arxiv_client", "openalex_client", "semantic_scholar",
    "search", "verify", "sandbox",
    "verify_paper_cli", "paper_verifier", "verified_registry", "source_text",
    "figure_lint",
]


@pytest.mark.parametrize("modname", KERNEL_MODULES)
def test_kernel_self_contained(modname, monkeypatch):
    """每个内核模块在 researchclaw 被封死时仍能 import（证明零 ARC 依赖）。"""
    # 把 researchclaw 钉成 None：任何 `import researchclaw[.x]` 立即 ImportError
    monkeypatch.setitem(sys.modules, "researchclaw", None)
    # 清掉可能已加载的内核，强制重新解析 import
    for m in KERNEL_MODULES:
        monkeypatch.delitem(sys.modules, m, raising=False)
    monkeypatch.syspath_prepend(str(_scripts_dir()))

    __import__(modname)  # 抛异常即测试失败


def test_no_researchclaw_import_statements():
    """静态检查：内核源码里不残留 `from researchclaw` / `import researchclaw`。"""
    offenders = []
    for py in _scripts_dir().glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("from researchclaw", "import researchclaw")):
                offenders.append(f"{py.name}:{i}: {stripped}")
    assert not offenders, "内核残留 researchclaw import：\n" + "\n".join(offenders)


# ── 不变量 2：资产完整 ────────────────────────────────────────
def test_skill_count():
    """方法论 SKILL.md 全部就位（基线 ≥40，随后续新增的 domain/experiment skill 增长）。"""
    cd = launcher.opencode_config_dir()
    skills = glob.glob(str(cd / "skill" / "**" / "SKILL.md"), recursive=True)
    assert len(skills) >= 40, f"skill 数应 >= 40，实际 {len(skills)}"


def test_kernel_count():
    """全部 Python 内核就位（基线 ≥11，含后续新增的 source_text / figure_lint）。"""
    kernels = list(_scripts_dir().glob("*.py"))
    assert len(kernels) >= 11, f"内核脚本应 >= 11，实际 {len(kernels)}"


def test_core_assets_present():
    """tool / hook / AGENTS.md / opencode.json 关键文件齐全。"""
    cd = launcher.opencode_config_dir()
    for rel in (
        "opencode.json",
        "AGENTS.md",
        "commands/goal.md",
        "tool/arc.ts",
        "plugins/guardrails.ts",
        "plugins/heartbeat.ts",
        "plugins/cleanup.ts",
        "plugins/compaction-policy.ts",
    ):
        assert (cd / rel).exists(), f"缺失关键资产：{rel}"


# ── 不变量 3：CLI 装配 ────────────────────────────────────────



def test_heartbeat_is_singleton_claimed_and_backed_off():
    """Heartbeat scheduling is singleton, atomically claimed, and backed off."""
    source = (
        launcher.opencode_config_dir() / "plugins" / "heartbeat.ts"
    ).read_text(encoding="utf-8")

    assert 'Symbol.for("famou-scientist.heartbeat.scheduler.v2")' in source
    assert 'flag: "wx"' in source
    assert "schedule.intervalMs * 2" in source
    assert "MAX_POLL_MS" in source
    assert "2 * 60 * 60 * 1000" in source
    assert "writeProgressSnapshot(dir, snapshot)" in source

def test_launcher_locates_assets():
    """launcher 能定位到存在的资产目录。"""
    assert launcher.assets_dir().is_dir()
    assert launcher.opencode_config_dir().is_dir()


def test_build_env_injects_required_vars():
    """build_env 注入 OPENCODE_CONFIG_DIR / ARC_ROOT / ARC_PYTHON。"""
    env = launcher.build_env({})
    cd = str(launcher.opencode_config_dir())
    assert env["OPENCODE_CONFIG_DIR"] == cd
    assert env["ARC_ROOT"] == cd
    assert env["ARC_PYTHON"]  # 非空
    assert env["OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"] == "1"


def test_sandbox_actually_runs():
    """烟雾测试：sandbox 内核真能执行代码并解析 metric。"""
    monkey_scripts = str(_scripts_dir())
    sys.path.insert(0, monkey_scripts)
    try:
        import tempfile
        from sandbox import ExperimentSandbox, SandboxConfig
        cfg = SandboxConfig(python_path=sys.executable)
        with tempfile.TemporaryDirectory() as d:
            sb = ExperimentSandbox(cfg, Path(d))
            r = sb.run("print('primary_metric: 0.42')", timeout_sec=30)
        assert r.returncode == 0
        assert r.metrics.get("primary_metric") == 0.42
    finally:
        sys.path.remove(monkey_scripts)


def test_async_runner_smoke(tmp_path, monkeypatch):
    """烟雾测试：async_runner.py 后台跑完后落 .done / result.json / status.json。"""
    import json
    import os
    import subprocess

    scripts = _scripts_dir()
    job_dir = tmp_path / "job_x"
    job_dir.mkdir()
    (job_dir / "code.py").write_text("print('primary_metric: 0.42')", encoding="utf-8")

    # 直接同步跑 runner（它内部用 sandbox 真执行）；真实异步 detached 由 arc.ts 负责
    env = {**os.environ, "ARC_PYTHON": sys.executable}
    proc = subprocess.run(
        [sys.executable, str(scripts / "async_runner.py"), str(job_dir), "30"],
        cwd=str(scripts), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    assert (job_dir / ".done").exists()
    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert status["state"] == "done"
    assert result["returncode"] == 0
    assert result["metrics"].get("primary_metric") == 0.42


def test_source_text_no_query_offline():
    """烟雾测试：source_text.fetch_source 无参时离线返回 found=False（不触网）。"""
    monkey_scripts = str(_scripts_dir())
    sys.path.insert(0, monkey_scripts)
    try:
        import source_text
        r = source_text.fetch_source()
        assert r["found"] is False
        assert "title" in r or "reason" in r
    finally:
        sys.path.remove(monkey_scripts)


def test_figure_lint_smoke(tmp_path):
    """烟雾测试：figure_lint 渲染绘图代码、出图、并对硬违规判 FAIL。"""
    pytest.importorskip("matplotlib")
    monkey_scripts = str(_scripts_dir())
    sys.path.insert(0, monkey_scripts)
    try:
        import figure_lint

        # ① 规范图（单栏、有轴标签+单位、viridis）→ 生成文件、无 FAIL
        good = (
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots(figsize=(3.4, 2.6))\n"
            "ax.plot([0, 1, 2], [0.1, 0.5, 0.9])\n"
            "ax.set_xlabel('Epoch')\n"
            "ax.set_ylabel('Accuracy (%)')\n"
        )
        out_pdf = tmp_path / "good.pdf"
        r = figure_lint.render_and_lint(good, str(out_pdf), kind="data", journal="single")
        assert r["rendered"] is True
        assert out_pdf.exists()
        # 矢量目标会另存 png 供读图
        assert (tmp_path / "good.png").exists()
        assert r["severity"] in ("PASS", "WARN")
        assert isinstance(r["checks"], list) and r["checks"]

        # ② 违规图（jet colormap + 极小字号）→ severity=FAIL，命中 colormap/font_size
        bad = (
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots(figsize=(3.4, 2.6))\n"
            "ax.imshow([[0, 1], [1, 0]], cmap='jet')\n"
            "ax.tick_params(labelsize=3)\n"
        )
        rb = figure_lint.render_and_lint(bad, str(tmp_path / "bad.png"), kind="data")
        assert rb["severity"] == "FAIL"
        fail_names = {c["name"] for c in rb["checks"] if c["level"] == "FAIL"}
        assert "colormap" in fail_names

        # ③ 渲染错误路径 → rendered=False, severity=ERROR（不会被图版核验门当 FAIL 拦）
        rerr = figure_lint.render_and_lint("raise ValueError('x')", str(tmp_path / "e.png"))
        assert rerr["rendered"] is False
        assert rerr["severity"] == "ERROR"
    finally:
        sys.path.remove(monkey_scripts)
