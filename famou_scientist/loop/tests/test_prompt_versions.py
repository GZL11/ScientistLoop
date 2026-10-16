"""Idea Agent 提示词版本切换与 v4 回应协议。

背景：提示词一律新增版本、不原地改——run 目录只 stage 源码、不存提示词快照，
原地改会让历史批次无法复现。版本解析在两处（wrapper 的 build_idea_prompt 与
workers 的 _prompt），加新版本必须同时改，本组把这条锁住。

v4 只改 wrapper 层的「回应 Idea Judge」一节。动机是 v3 虽然写了"你保留作者权"，
但实测拒绝率为 0（v4 批次作者被唤醒 4 次全部改写；配对批次 55 次改写、
author_kept 0 次）。复盘见 prompts/PROMPT_VERSIONS_CN.md。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from famou_scientist.loop.agents.workers import PromptWorkerSet
from famou_scientist.loop.execution import cli_agent_wrapper as wrapper
from famou_scientist.loop import prompts as prompt_pkg

ROOT = Path(prompt_pkg.__file__).parent


def _render(version: str) -> str:
    old = os.environ.get("FAMOU_IDEA_PROMPT_VERSION")
    os.environ["FAMOU_IDEA_PROMPT_VERSION"] = version
    try:
        return wrapper.build_prompt(
            role="idea",
            request={"metadata": {"probe": "version-marker"}},
            instruction="INSTRUCTION-BODY",
            output_path=Path("/tmp/out.json"),
            worktree_result_path=Path("/tmp/w/result.json"),
            worktree=Path("/tmp/w"),
            max_turns=None,
        )
    finally:
        if old is None:
            os.environ.pop("FAMOU_IDEA_PROMPT_VERSION", None)
        else:
            os.environ["FAMOU_IDEA_PROMPT_VERSION"] = old


# --- 版本文件齐全 ---------------------------------------------------


@pytest.mark.parametrize("version", ["", "_v2", "_v3", "_v4", "_v5", "_v6"])
def test_both_layers_have_every_version(version: str):
    """instruction 与 wrapper 两层都必须有对应版本，缺一层会在运行期才炸。"""

    assert (ROOT / "benchmark_managed" / f"idea_agent{version}.md").is_file()
    assert (ROOT / "cli_agents" / f"idea_agent{version}.md").is_file()


def test_v4_wrapper_keeps_the_request_payload():
    """回归点：`cli_agents/idea_judge.md` 初版漏了 ${request_json}，判官全程盲判。"""

    assert "${request_json}" in (ROOT / "cli_agents" / "idea_agent_v4.md").read_text(
        encoding="utf-8"
    )
    assert "version-marker" in _render("v4")


def test_v4_instruction_layer_is_byte_identical_to_v3():
    """v4 只改 wrapper 层；instruction 层若一起动了，就分不清是哪一层的效果。"""

    v3 = (ROOT / "benchmark_managed" / "idea_agent_v3.md").read_text(encoding="utf-8")
    v4 = (ROOT / "benchmark_managed" / "idea_agent_v4.md").read_text(encoding="utf-8")
    assert v3 == v4


# --- 版本解析（两处必须一致）-----------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("v6", "idea_agent_v6"),
        ("6", "idea_agent_v6"),
        ("selftask-v6", "idea_agent_v6"),
        ("v5", "idea_agent_v5"),
        ("5", "idea_agent_v5"),
        ("expbank-v5", "idea_agent_v5"),
        ("v4", "idea_agent_v4"),
        ("4", "idea_agent_v4"),
        ("debate-v4", "idea_agent_v4"),
        ("V4", "idea_agent_v4"),
        ("v3", "idea_agent_v3"),
        ("validity-v3", "idea_agent_v3"),
        ("v2", "idea_agent_v2"),
        ("algorithm-v2", "idea_agent_v2"),
        ("v1", "idea_agent"),
        ("", "idea_agent"),
        ("bogus", "idea_agent"),
    ],
)
def test_instruction_layer_resolves_version(tmp_path: Path, version, expected):
    import famou_scientist.loop.agents.workers as mod

    original = mod._create_agent_adapter
    mod._create_agent_adapter = lambda config, **kwargs: object()
    old = os.environ.get("FAMOU_IDEA_PROMPT_VERSION")
    os.environ["FAMOU_IDEA_PROMPT_VERSION"] = version
    try:
        workers = PromptWorkerSet({"workflow": {"type": "benchmark_managed"}}, tmp_path)
        text = workers._prompt("idea_generator")
    finally:
        mod._create_agent_adapter = original
        if old is None:
            os.environ.pop("FAMOU_IDEA_PROMPT_VERSION", None)
        else:
            os.environ["FAMOU_IDEA_PROMPT_VERSION"] = old
    assert text == (ROOT / "benchmark_managed" / f"{expected}.md").read_text(
        encoding="utf-8"
    ).strip()


@pytest.mark.parametrize("version", ["v4", "4", "debate-v4"])
def test_wrapper_layer_resolves_v4(version):
    assert "DEBATE: declined_premise" in _render(version)


# --- v5 两个经验库的区分 ----------------------------------------------
#
# v4 及更早把 `expbank_dir` 描述成「项目级 .famou/cross_task_expbank 为本 Run
# 准备的只读快照」，并让 Agent 去读 `<expbank_dir>/INDEX.md`。实际 `expbank_dir`
# 指向的是**本任务**的 `<run>/expbank`，跨任务快照从没作为目录下发过，且它的清单
# 是 `index.jsonl` 不是 `INDEX.md`。实测 20 个 w/ 臂 run 无一打开过跨任务目录。


@pytest.mark.parametrize("version", ["v5", "5", "expbank-v5"])
def test_wrapper_layer_resolves_v5(version):
    assert "cross_task_expbank_dir" in _render(version)


def _v5(layer: str) -> str:
    return (ROOT / layer / "idea_agent_v5.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("layer", ["benchmark_managed", "cli_agents"])
def test_v5_names_the_cross_task_snapshot_separately(layer: str):
    text = _v5(layer)
    assert "cross_task_expbank_dir" in text
    assert "index.jsonl" in text


@pytest.mark.parametrize("layer", ["benchmark_managed", "cli_agents"])
def test_v5_no_longer_calls_the_in_task_bank_the_cross_task_snapshot(layer: str):
    """回归点：`expbank_dir` 是本任务的库，不能再说它是项目级跨任务快照。"""

    text = _v5(layer)
    assert "`expbank_dir` 是项目级 `.famou/cross_task_expbank`" not in text
    assert "当请求中存在 `expbank_dir` 时，必须使用请求提供的完整绝对路径" not in text


@pytest.mark.parametrize("layer", ["benchmark_managed", "cli_agents"])
def test_v5_explains_that_result_is_a_grade_not_a_status(layer: str):
    """`result` 换成成绩档位后，提示词必须跟着换口径，否则 Agent 仍按状态读。"""

    text = _v5(layer)
    assert "surpass_sota" in text and "below_sota" in text


def test_v5_keeps_the_v4_debate_protocol():
    """v5 = v4 + 经验库口径修正；辩论协议必须原样保留。"""

    assert "DEBATE: declined_premise" in _v5("cli_agents")


# --- v6 同任务自身经验口径 --------------------------------------------
#
# v5 通篇把 cross_task_expbank_dir 描述成「别的任务」的快照，并要求 Agent
# 论证可迁移性、禁止把历史结论当作当前任务事实。v6 用在同任务自身经验 A/B
# 的处理臂上（seed 侧 --only-task-id），那些话全是反向指令：快照里就是这道题
# 自己的历史，结论直接适用。另外加一条噪声提示——诊断显示 run 内 62% 的
# 「刷新最佳」幅度小于该任务自身的重复噪声，而 Agent 无从自行发现这件事。


def _v6(layer: str) -> str:
    return (ROOT / layer / "idea_agent_v6.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("version", ["v6", "6", "selftask-v6"])
def test_wrapper_layer_resolves_v6(version):
    assert "cross_task_expbank_dir" in _render(version)


@pytest.mark.parametrize("layer", ["benchmark_managed", "cli_agents"])
def test_v6_reframes_the_snapshot_as_self_history(layer: str):
    """回归点：v6 里不能再出现「别的任务」「已剔除本任务自己的历史条目」。"""

    text = _v6(layer)
    assert "别的任务**的跨任务经验快照" not in text
    assert "快照已剔除本任务自己的历史条目" not in text
    assert "自己" in text and "cross_task_expbank_dir" in text


@pytest.mark.parametrize("layer", ["benchmark_managed", "cli_agents"])
def test_v6_warns_that_small_gains_may_be_noise(layer: str):
    """v6 的实质改动：换掉「论证可迁移性」，换上「小幅提升可能是噪声」。"""

    text = _v6(layer)
    assert "噪声" in text
    assert "0.0x" in text


def test_v6_keeps_the_v4_debate_protocol():
    """v6 = v5 + 自身经验口径；辩论协议必须原样保留。"""

    assert "DEBATE: declined_premise" in _v6("cli_agents")


@pytest.mark.parametrize("version", ["v5", "v4", "v3", "v2", "v1"])
def test_v5_and_older_keep_the_cross_task_framing(version):
    """v1–v5 逐字保留：已跑过的批次必须能复现。"""

    text = _render(version)
    assert "快照里只保留了这道题自己前几轮的复盘" not in text


@pytest.mark.parametrize("version", ["v3", "v2", "v1", "bogus"])
def test_older_versions_do_not_get_the_v4_protocol(version):
    """回归保护：旧版本必须逐字保留，否则历史批次无法复现。"""

    assert "DEBATE: declined_premise" not in _render(version)


@pytest.mark.parametrize("version", ["v4", "v3", "v2", "v1"])
def test_older_versions_do_not_mention_the_cross_task_dir(version):
    """v1–v4 逐字保留：已跑过的批次必须能复现。"""

    assert "cross_task_expbank_dir" not in _render(version)


# --- v4 回应协议的实质内容 -------------------------------------------


def _v4() -> str:
    return (ROOT / "cli_agents" / "idea_agent_v4.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "clause",
    [
        "DEBATE: modified",
        "DEBATE: declined_premise",
        "DEBATE: declined_not_bottleneck",
        "DEBATE: partial",
    ],
)
def test_v4_defines_all_four_dispositions(clause):
    """二元 → 四种处置：v3 缺"前提不成立但看着有可取之处"这一格，
    作者于是自创 partial rebuttal + accepted kernel 然后照改。"""

    assert clause in _v4()


def test_v4_forbids_accepting_the_kernel_after_rebutting_the_premise():
    """点名禁止实测出现过的那种写法。"""

    text = _v4()
    assert "前提不成立就是驳回，没有内核可接受" in text
    assert "accepted kernel" in text


def test_v4_restricts_changes_once_the_idea_already_matches():
    """已达标时只有 blocking 级意见才允许改动——origin>=0 分层 4/6 变差。"""

    text = _v4()
    assert "current_score >= 0" in text
    assert "blocking" in text


def test_v4_requires_the_declined_body_to_stay_identical():
    assert "方案主体必须与上一版逐字相同" in _v4()


def test_v4_states_that_declining_is_normal():
    """v3 的措辞下拒绝率为 0；v4 明确把拒绝写成正常结果。"""

    assert "拒绝修改是正常且常见的结果" in _v4()


def test_v4_cites_the_measured_cost_of_needless_edits():
    """把实测代价写进提示词，让模型知道无谓改动的期望收益为负。"""

    text = _v4()
    assert "−0.0329" in text or "-0.0329" in text
    assert "52.9%" in text


# --- 台账 -------------------------------------------------------------


def test_version_ledger_exists_and_covers_v4():
    ledger = ROOT / "PROMPT_VERSIONS_CN.md"
    assert ledger.is_file()
    text = ledger.read_text(encoding="utf-8")
    assert "FAMOU_IDEA_PROMPT_VERSION" in text
    assert "idea_agent_v4.md" in text
    assert "idea_agent_v5.md" in text
    # 两处解析都要在台账里点名，避免下次只改一处
    assert "cli_agent_wrapper.py" in text and "workers.py" in text


# --- Terminal Verifier compiler prompt versions ---------------------------


@pytest.mark.parametrize("suffix", ["v0", "v1", "v2"])
def test_terminal_verifier_prompt_files_are_preserved(suffix: str):
    """The legacy compiler prompt remains selectable for reproducibility."""

    terminal = ROOT / "cli_agents" / "terminal_task"
    if suffix in {"v1", "v2"}:
        assert (terminal / f"verifier_instruction_{suffix}.md").is_file()
    for stem in ("verifier_compile", "verifier_repair_compile", "verifier_diagnose"):
        assert (terminal / f"{stem}_{suffix}.md").is_file()


def _render_terminal_verifier(version: str, phase: str = "compile_plan") -> str:
    old = os.environ.get("FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION")
    os.environ["FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION"] = version
    try:
        return wrapper.build_terminal_verifier_prompt(
            request={"metadata": {"terminal_phase": phase}},
            instruction="INSTRUCTION-BODY",
            output_path=Path("/tmp/out.json"),
            worktree_result_path=Path("/tmp/w/result.json"),
            worktree=Path("/tmp/w"),
            max_turns=None,
        )
    finally:
        if old is None:
            os.environ.pop("FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION", None)
        else:
            os.environ["FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION"] = old


def test_terminal_verifier_prompt_defaults_to_v1_and_v0_is_selectable():
    old = os.environ.pop("FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION", None)
    try:
        current = wrapper.build_terminal_verifier_prompt(
            request={},
            instruction="INSTRUCTION-BODY",
            output_path=Path("/tmp/out.json"),
            worktree_result_path=Path("/tmp/w/result.json"),
            worktree=Path("/tmp/w"),
            max_turns=None,
        )
    finally:
        if old is not None:
            os.environ["FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION"] = old
    assert "官方断言对齐清单" in current
    assert "FAMOU_TERMINAL_VERIFIER_PROMPT_VERSION" not in current

    legacy = _render_terminal_verifier("v0")
    assert "Terminal Task Verifier Compiler v1" in legacy
    assert "官方断言对齐清单" not in legacy


def test_terminal_verifier_v1_contains_exact_and_hidden_coverage_rules():
    text = _render_terminal_verifier("v1")
    for clause in (
        "优先采用可执行官方测试",
        "time_variable == \"t\"",
        "coverage=uncovered",
        "mutation test",
        "不能伪装成隐藏 GT 通过",
        "静态 contract 与动态行为分开",
        "官方没有要求的额外文件",
        "format_pass",
        "behavior_pass",
        "value_proxy_pass",
    ):
        assert clause in text


def test_terminal_verifier_v2_contains_explicit_value_quality_requirements():
    text = _render_terminal_verifier("v2")
    for clause in (
        "独立参考",
        "指标同构",
        "覆盖分布",
        "最差优先",
        "动态真实性",
        "校准与不确定性",
        "false-pass",
        "value_proxy_pass",
    ):
        assert clause in text
