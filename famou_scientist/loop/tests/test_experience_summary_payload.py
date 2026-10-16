"""复盘 Agent 的取证契约：给目录和路径，不内联全量记录。

历史故障：``_experience_summary_context`` 返回全量 ``attempts``，被
``build_experience_summary_prompt`` 原样 ``json.dumps(indent=2)`` 内联进提示词
正文。实测 ``public/context.json`` 286 KB ~ 1.16 MB，而**同一份数据在工作区里
已经有一份**——复盘节点是带 Read/Grep/Glob 的 CLI Agent，自己读就行。这份冗余
在 2026-08 造成 24 次 ``Prompt is too long``，且按 attempt 数选择性触发：跑得
越多、经验越厚的 Run 越复盘不出来。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from famou_scientist.loop.execution import cli_agent_wrapper as wrapper
from famou_scientist.loop.prompts import render_prompt


TEMPLATE = "cli_agents/evolution_summarizer.md"


def _prompt(request: dict, tmp_path: Path) -> str:
    return wrapper.build_experience_summary_prompt(
        request=request,
        instruction="复盘本 Run。",
        output_path=tmp_path / "out.json",
        worktree_result_path=tmp_path / "EVOLUTION.md",
        worktree=tmp_path,
        max_turns="30",
    )


def _context(n: int = 3) -> dict:
    return {
        "goal_name": "naturebench_demo",
        "domain": "cellular_omics",
        "workflow_type": "benchmark_managed",
        "research_state": {"status": "completed"},
        "expbank_dir": "/runs/demo/expbank",
        "attempt_index": [
            {
                "attempt_id": f"{i:04d}",
                "status": "evaluated",
                "score": -0.05 * i,
                "idea_title": f"方案 {i}",
                "record_path": f"/runs/demo/expbank/{i:04d}/record.json",
            }
            for i in range(1, n + 1)
        ],
    }


# --- 取证上下文的信封形状（生产用嵌套，测试一直用扁平）-------------------
#
# 这一组是 2026-09 那个故障的回归点。``build_experience_summary_prompt`` 原本写
# ``metadata = request``，而生产调用把 context 放在 ``request["metadata"]`` 里
# （``agents/workers.py::summarize_experience`` 传 ``metadata=context``）。三个占位
# 符于是**同时**静默兜底：``{}`` / 相对路径 ``expbank`` /「没有 attempt 记录」。
# 复盘 Agent 在 worktree 里 ``ls expbank/`` 扑空，如实写下「证据全部缺失」，这句话
# 被当作正式经验存进库。20260909 批次 105 份里 90 份如此；2026-08 缺失率 2%，
# 2026-09 升到 32%。
#
# 它能活一个月，是因为**本文件此前每一条用例都传扁平 dict**——恰好是生产永远不会
# 出现的形状。所以下面第一条必须按嵌套信封断言。


def _nested(context: dict) -> dict:
    """生产调用形态：context 挂在 ``metadata`` 键下，同层还有 goal/idea 等。"""

    return {
        "goal": {"name": "demo"},
        "idea": {"id": "x", "task": "experience_summary"},
        "call_id": "experience_summary_1",
        "metadata": context,
    }


def test_prompt_reads_the_nested_metadata_envelope(tmp_path: Path):
    """回归点：生产形态下取证入口必须真的下发，而不是三个兜底值。"""

    text = _prompt(_nested(_context(5)), tmp_path)

    assert "/runs/demo/expbank" in text
    for i in range(1, 6):
        assert f"/runs/demo/expbank/{i:04d}/record.json" in text
    assert "naturebench_demo" in text


def test_nested_envelope_does_not_trigger_any_silent_fallback(tmp_path: Path):
    """三个兜底串一个都不许出现——它们同时出现就是那 90 份瞎写复盘的成因。"""

    text = _prompt(_nested(_context(5)), tmp_path)

    assert "```json\n{}\n```" not in text
    assert "没有 attempt 记录" not in text
    assert "挂在 `expbank`" not in text


def test_flat_request_still_renders(tmp_path: Path):
    """``resummarize_run.py`` 与本文件其余用例直接传扁平 context，必须继续可用。"""

    text = _prompt(_context(3), tmp_path)

    assert "/runs/demo/expbank" in text
    assert "/runs/demo/expbank/0001/record.json" in text


def test_empty_metadata_envelope_falls_back_to_the_flat_shape(tmp_path: Path):
    """``metadata`` 为空 dict 时不能把扁平字段也一起吞掉。"""

    request = dict(_context(2))
    request["metadata"] = {}

    assert "/runs/demo/expbank/0001/record.json" in _prompt(request, tmp_path)


def test_missing_expbank_dir_never_renders_a_plausible_relative_path(tmp_path: Path):
    """兜底值必须是不可执行的标记。

    相对路径 ``expbank`` 看着像合法挂载点，Agent 会真的去 ls；它的 cwd 是
    worktree，必然扑空，然后写出一份「证据缺失」的复盘。静默降级成一条看似合理
    的错路径，比直接留空危险得多。
    """

    context = _context(1)
    context.pop("expbank_dir")

    text = _prompt(context, tmp_path)

    assert "挂在 `expbank`" not in text
    assert "未提供 expbank 路径" in text


# --- 载荷不再内联全量记录 -------------------------------------------------


def test_prompt_does_not_inline_the_whole_request(tmp_path: Path):
    context = _context()
    context["attempts"] = [{"attempt_id": "0001", "idea": {"method": "x" * 50_000}}]

    text = _prompt(context, tmp_path)

    assert "x" * 1000 not in text


def test_prompt_size_does_not_grow_with_attempt_count(tmp_path: Path):
    """10 条与 200 条 attempt 的提示词差距必须是线性的目录行，而不是全量记录。"""

    small = len(_prompt(_context(10), tmp_path))
    large = len(_prompt(_context(200), tmp_path))

    # 每条目录约 100~150 字节；200 条不应把提示词推到 100 KB 量级。
    assert large - small < 40_000
    assert large < 60_000


def test_template_has_no_request_json_placeholder():
    """``${request_json}`` 是那 24 次 Prompt is too long 的直接来源。"""

    text = (
        Path(wrapper.__file__).resolve().parents[1] / "prompts" / TEMPLATE
    ).read_text(encoding="utf-8")

    assert "${request_json}" not in text


# --- 取证入口必须真的下发 -------------------------------------------------


def test_prompt_carries_the_expbank_directory(tmp_path: Path):
    text = _prompt(_context(), tmp_path)
    assert "/runs/demo/expbank" in text


def test_prompt_carries_every_attempt_and_its_record_path(tmp_path: Path):
    text = _prompt(_context(5), tmp_path)
    for i in range(1, 6):
        assert f"{i:04d}" in text
        assert f"/runs/demo/expbank/{i:04d}/record.json" in text


def test_prompt_renders_scores_not_raw_floats(tmp_path: Path):
    text = _prompt(_context(1), tmp_path)
    assert "-0.050000" in text


def test_missing_score_renders_as_placeholder(tmp_path: Path):
    context = _context(1)
    context["attempt_index"][0]["score"] = None
    assert "—" in _prompt(context, tmp_path)


def test_empty_attempt_index_is_stated_explicitly(tmp_path: Path):
    context = _context(0)
    text = _prompt(context, tmp_path)
    assert "没有 attempt 记录" in text


def test_pipe_in_idea_title_does_not_break_the_table(tmp_path: Path):
    context = _context(1)
    context["attempt_index"][0]["idea_title"] = "A | B | C"
    text = _prompt(context, tmp_path)
    row = [l for l in text.splitlines() if "`0001`" in l][0]
    assert row.count("|") == 6


def test_non_dict_rows_are_skipped(tmp_path: Path):
    context = _context(1)
    context["attempt_index"].append("garbage")
    assert "garbage" not in _prompt(context, tmp_path)


def test_absent_attempt_index_still_renders(tmp_path: Path):
    context = _context()
    context.pop("attempt_index")
    assert "没有 attempt 记录" in _prompt(context, tmp_path)


# --- 提示词仍然要求实际取证 -----------------------------------------------


def test_template_requires_opening_specific_records():
    text = (
        Path(wrapper.__file__).resolve().parents[1] / "prompts" / TEMPLATE
    ).read_text(encoding="utf-8")

    # 只给目录不够——必须明确要求打开最好、最差、失败的那几条，
    # 否则 Agent 会只看目录里的分数就下结论。
    assert "必须实际打开" in text
    assert "record_path" in text


def test_template_keeps_the_two_sections_downstream_agents_actually_use():
    text = (
        Path(wrapper.__file__).resolve().parents[1] / "prompts" / TEMPLATE
    ).read_text(encoding="utf-8")

    assert "When to use" in text
    assert "When not to use" in text


def test_template_forbids_transplanting_score_ranges():
    """「本任务拿到 +0.13」不能写成对新任务的收益预期。"""

    text = (
        Path(wrapper.__file__).resolve().parents[1] / "prompts" / TEMPLATE
    ).read_text(encoding="utf-8")

    assert "分数区间不可迁移" in text


def test_every_placeholder_in_the_template_is_supplied(tmp_path: Path):
    """漏填占位符会静默留下字面量 ``${...}``——``cli_agents/idea_judge.md``
    初版漏了 ``${request_json}``，判官在完全看不到待评 Idea 的情况下连续给出
    「无实质缺陷」，跑了 4 轮探测才定位。"""

    text = _prompt(_context(), tmp_path)
    assert "${" not in text


# --- 结构化 JSON 那条路径已移除 -------------------------------------------


def test_structured_json_template_is_gone():
    root = Path(wrapper.__file__).resolve().parents[1] / "prompts"
    assert not (root / "cli_agents" / "experience_summarizer.md").exists()


def test_result_filename_is_always_markdown():
    """复盘只有 Markdown 一种形态，不再按 summary_format 分叉。"""

    source = Path(wrapper.__file__).read_text(encoding="utf-8")
    assert "famou_experience_summary.json" not in source
    assert "_summary_format" not in source


def test_no_dangling_reference_to_the_removed_summary_format():
    """回归点：删掉 ``_summary_format`` 时漏了一处**不带下划线**的引用。

    上面那条只查 ``_summary_format``，而漏下来的标识符是 ``summary_format``，
    正好从缝里漏过去。后果不是启动即失败，而是跑到收尾那一刻才 ``NameError``：
    Agent 已经写完 EVOLUTION.md，wrapper 在读它之前炸掉，于是 09-07 之后**每个
    run 的复盘都没能回流**，经验库停止增长（两个 verify run 的 outbox 里
    ``evolution_markdown`` 都是 0 字符）。
    """

    source = Path(wrapper.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "summary_format" not in code


def test_markdown_harvest_keys_only_on_the_role():
    """收尾时取 Markdown 的分支不能再依赖任何格式开关。"""

    source = Path(wrapper.__file__).read_text(encoding="utf-8")
    assert 'if args.role == "experience_summary":' in source
