"""Idea Judge 辩论环节：闸门、契约与失败降级。

背景（全量实测，79 个 opus run）：
- 刷新 run best 的 attempt 里 56.1% 来自全新起头、与当时最优毫无血缘的路线，
  48.6% 的 run 最终最好的那版从未被改进过 —— **独立路线本身就是价值**。
  因此 Judge 不得把 Idea 拉向当前最优，`respond` 模式保留作者的拒绝权。
- 每个 run 中位产 11 条 Idea，其中 8 条落在头 1 小时；而开跑 45 分钟时
  65/79 个 run 一条评测结果都没有，60 分钟时仍有 54/79 为零。所以纯时间闸门
  要么放早（无据可批）要么挡掉 66% 的 Idea，必须时间 + 证据双闸门。
- 同题首发方案盲评显示 Judge **不会排序**（46 对里命中 76.1%，而闭眼猜同一个
  模型是 78.3%）。所以契约只允许它诊断，且每条意见必须绑定可核查对象。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from famou_scientist.loop.agents.workers import PromptWorkerSet
from famou_scientist.loop.execution import agent_presets
from famou_scientist.loop.execution import cli_agent_wrapper as wrapper
from famou_scientist.loop.runtime.orchestrator import Orchestrator, OrchestratorConfig


# --- 配置归一化 ------------------------------------------------------


def test_debate_defaults_are_off_and_respond():
    config = OrchestratorConfig()
    assert config.idea_debate_enabled is False
    assert config.idea_debate_mode == "respond"
    assert config.idea_debate_max_rounds == 1
    assert config.idea_debate_min_elapsed_sec == 3_600
    assert config.idea_debate_min_evaluated_attempts == 1
    assert config.idea_debate_allow_cross_task_only is False


@pytest.mark.parametrize("mode", ["", "REWRITE_ALL", "judge", None, 7])
def test_unknown_mode_falls_back_to_respond(mode):
    """配置写错不得静默启用影响更大的 rewrite。"""

    assert OrchestratorConfig(idea_debate_mode=mode).idea_debate_mode == "respond"


@pytest.mark.parametrize("mode,expected", [("rewrite", "rewrite"), ("RESPOND", "respond")])
def test_valid_modes_are_preserved(mode, expected):
    assert OrchestratorConfig(idea_debate_mode=mode).idea_debate_mode == expected


@pytest.mark.parametrize("rounds,expected", [(0, 1), (-3, 1), ("x", 1), (3, 3)])
def test_max_rounds_is_clamped(rounds, expected):
    assert OrchestratorConfig(idea_debate_max_rounds=rounds).idea_debate_max_rounds == expected


@pytest.mark.parametrize("value,expected", [(-5, 0.0), ("x", 3_600), (60, 60.0)])
def test_min_elapsed_is_normalized(value, expected):
    config = OrchestratorConfig(idea_debate_min_elapsed_sec=value)
    assert config.idea_debate_min_elapsed_sec == expected


@pytest.mark.parametrize("value,expected", [(-1, 0), ("x", 1), (2, 2)])
def test_min_evaluated_attempts_is_normalized(value, expected):
    config = OrchestratorConfig(idea_debate_min_evaluated_attempts=value)
    assert config.idea_debate_min_evaluated_attempts == expected


# --- 角色注册 --------------------------------------------------------


def _argv(role: str, **overrides) -> list[str]:
    import argparse

    args = argparse.Namespace(
        runtime="claude",
        binary="claude",
        role=role,
        auto_approve=True,
        model=None,
        agent=None,
        profile=None,
        max_turns=None,
        extra_arg=[],
        worktree=Path("/tmp/w"),
        **overrides,
    )
    return wrapper.build_cli_argv(args, "p", Path("/tmp/last.json"))


def test_idea_judge_is_a_read_only_role():
    """Judge 只诊断，不得获得执行权限。"""

    joined = " ".join(_argv("idea_judge"))
    assert "--allowedTools=Read,Edit" in joined
    assert "Bash" not in joined
    assert "WebSearch" not in joined


def test_implement_role_still_gets_execution_tools():
    """回归点：只读集合扩容不得波及 implement。"""

    assert "--allowedTools=Read,Write,Edit,Bash" in " ".join(_argv("implement"))


def test_idea_judge_prompt_builder_is_registered():
    prompt = wrapper.build_prompt(
        role="idea_judge",
        request={"idea": {"id": "idea-1"}},
        instruction="",
        output_path=Path("/tmp/out.json"),
        worktree_result_path=Path("/tmp/w/result.json"),
        worktree=Path("/tmp/w"),
        max_turns=None,
    )
    assert "Idea Judge" in prompt
    # 契约里的两条硬性约束必须真的进到提示词里。
    assert "evidence_refs" in prompt
    assert "has_material_objection" in prompt
    assert "不得要求这条 Idea 向当前最优方案靠拢" in prompt


def test_agent_preset_accepts_idea_judge_role(tmp_path: Path):
    from famou_scientist.loop.execution.workspace import AgentWorkspace

    workspace = AgentWorkspace.create(tmp_path / "ws", "b1")
    argv = agent_presets.build_agent_preset_command(
        {"runtime": "claude", "role": "idea_judge", "model": "m"},
        workspace=workspace,
        input_path=tmp_path / "in.json",
        output_path=tmp_path / "out.json",
        instruction_path=tmp_path / "i.md",
    )
    assert "idea_judge" in argv
    assert "--allow-network-tools" not in argv


# --- 反对意见的可核查性 ----------------------------------------------


def test_objections_without_evidence_are_dropped():
    """没有依据的意见按契约丢弃，避免 Judge 为交差硬挑毛病。"""

    kept = PromptWorkerSet._material_objections(
        {
            "objections": [
                {"statement": "指标未对齐", "evidence_refs": ["inst_a"]},
                {"statement": "感觉不够创新", "evidence_refs": []},
                {"statement": "缺依据", "evidence_refs": ["   "]},
                {"statement": "", "evidence_refs": ["inst_b"]},
                "not a dict",
                {"evidence_refs": ["inst_c"]},
            ]
        }
    )
    assert [item["statement"] for item in kept] == ["指标未对齐"]
    assert kept[0]["evidence_refs"] == ["inst_a"]


def test_objections_missing_entirely_is_empty():
    assert PromptWorkerSet._material_objections({}) == []
    assert PromptWorkerSet._material_objections({"objections": None}) == []


# --- 辩论驱动 --------------------------------------------------------


IDEA = {"id": "idea-1", "title": "原方案", "mechanism": "原机制"}
REVISED = {"id": "ignored", "title": "改后方案", "mechanism": "改后机制"}


class _Debater:
    """只装配辩论所需的最小依赖，不构造完整 WorkerSet。"""

    def __init__(self, verdicts, answers=None):
        self._verdicts = list(verdicts)
        self._answers = list(answers or [])
        self.recorded: list[tuple] = []
        self.critique_calls = 0

    _material_objections = staticmethod(PromptWorkerSet._material_objections)
    _run_idea_debate = PromptWorkerSet._run_idea_debate

    def _critique_idea(self, goal, idea, directive, round_index):
        self.critique_calls += 1
        return self._verdicts.pop(0) if self._verdicts else None

    def _record_debate(self, idea, rounds, outcome):
        self.recorded.append((idea, rounds, outcome))
        return "artifacts/idea_debate/x.md"

    def respond(self, current, feedback, round_index):
        return self._answers.pop(0) if self._answers else None


def _objection(text="指标未对齐"):
    return {
        "objections": [{"statement": text, "evidence_refs": ["inst_a"]}],
        "feedback_markdown": "## 反馈\n\n" + text,
    }


def _emit(debater, mode="respond", rounds=1, emit_pair=False):
    """返回 _run_idea_debate 的完整入队列表。"""

    return debater._run_idea_debate(
        {},
        IDEA,
        {
            "enabled": True,
            "mode": mode,
            "max_rounds": rounds,
            "emit_pair": emit_pair,
            "gate": {"mode": "in_task"},
        },
        respond=debater.respond,
    )


def _run(debater, mode="respond", rounds=1):
    """非配对模式只入队一条，取出来做断言。"""

    out = _emit(debater, mode=mode, rounds=rounds)
    assert len(out) == 1
    return out[0]


def test_no_material_objection_keeps_original_idea():
    d = _Debater([{"has_material_objection": False, "objections": []}])
    out = _run(d)
    assert out["title"] == "原方案"
    assert out["idea_debate"]["outcome"] == "no_objection"
    assert d.recorded[0][2] == "no_objection"


def test_objection_without_evidence_counts_as_no_objection():
    """Judge 自称有意见，但一条都绑不上证据时按无意见处理。"""

    d = _Debater(
        [{"has_material_objection": True, "objections": [{"statement": "太弱", "evidence_refs": []}]}]
    )
    out = _run(d)
    assert out["title"] == "原方案"
    assert out["idea_debate"]["outcome"] == "no_objection"


def test_respond_mode_adopts_author_revision_and_keeps_idea_id():
    d = _Debater([_objection()], answers=[REVISED])
    out = _run(d)
    assert out["title"] == "改后方案"
    # 改写后仍是同一条 Idea，队列与 lineage 引用不能因此断裂。
    assert out["id"] == "idea-1"
    assert out["idea_debate"]["outcome"] == "author_revised"


def test_author_may_decline_and_original_survives():
    """作者行使拒绝权：原样重交即视为坚持，不再纠缠。"""

    d = _Debater([_objection(), _objection()], answers=[dict(IDEA), REVISED])
    out = _run(d, rounds=3)
    assert out["title"] == "原方案"
    assert out["idea_debate"]["outcome"] == "author_kept"
    # 拒绝后立刻停止，不消耗剩余轮次。
    assert d.critique_calls == 1


def test_author_failure_preserves_original_idea():
    d = _Debater([_objection()], answers=[None])
    out = _run(d)
    assert out["title"] == "原方案"
    assert out["idea_debate"]["outcome"] == "author_failed_idea_preserved"


def test_judge_failure_preserves_original_idea():
    """辩论是增益环节，不能成为 Idea 生产的新故障点。"""

    d = _Debater([None])
    out = _run(d)
    assert out["title"] == "原方案"
    assert out["idea_debate"]["outcome"] == "judge_failed_idea_preserved"


def test_rewrite_mode_adopts_judge_revision():
    d = _Debater([{**_objection(), "revised_idea": REVISED}])
    out = _run(d, mode="rewrite")
    assert out["title"] == "改后方案"
    assert out["id"] == "idea-1"
    assert out["idea_debate"]["outcome"] == "judge_rewrote"


def test_rewrite_mode_rejects_malformed_revision():
    d = _Debater([{**_objection(), "revised_idea": {"title": "缺 mechanism"}}])
    out = _run(d, mode="rewrite")
    assert out["title"] == "原方案"
    assert out["idea_debate"]["outcome"] == "rewrite_rejected_idea_preserved"


def test_respond_mode_never_asks_judge_to_rewrite():
    """respond 模式下即使 Judge 越权给了 revised_idea 也不得采用。"""

    d = _Debater([{**_objection(), "revised_idea": REVISED}], answers=[dict(IDEA)])
    out = _run(d, mode="respond")
    assert out["title"] == "原方案"


def test_multi_round_debate_runs_until_max_rounds():
    d = _Debater(
        [_objection("第一轮"), _objection("第二轮")],
        answers=[REVISED, {"id": "x", "title": "第二次改", "mechanism": "m2"}],
    )
    out = _run(d, rounds=2)
    assert out["title"] == "第二次改"
    assert out["idea_debate"]["rounds"] == 2
    assert d.critique_calls == 2


def test_debate_metadata_records_gate_and_feedback_path():
    d = _Debater([{"has_material_objection": False, "objections": []}])
    out = _run(d)
    meta = out["idea_debate"]
    assert meta["mode"] == "respond"
    assert meta["gate"] == {"mode": "in_task"}
    assert meta["feedback_path"] == "artifacts/idea_debate/x.md"


# --- 指令读取 --------------------------------------------------------


@pytest.mark.parametrize(
    "goal",
    [
        {},
        {"benchmark_runtime": {}},
        {"benchmark_runtime": {"idea_debate": {"enabled": False}}},
        {"benchmark_runtime": {"idea_debate": {}}},
        {"benchmark_runtime": {"idea_debate": "yes"}},
        {"benchmark_runtime": "x"},
    ],
)
def test_directive_absent_disables_debate(goal):
    assert PromptWorkerSet._debate_directive(goal) is None


def test_directive_present_enables_debate():
    directive = PromptWorkerSet._debate_directive(
        {"benchmark_runtime": {"idea_debate": {"enabled": True, "mode": "respond"}}}
    )
    assert directive is not None and directive["mode"] == "respond"


# --- 闸门（Orchestrator 侧） -----------------------------------------


class _Gate:
    """只装配闸门所需的最小依赖。"""

    def __init__(self, config, elapsed, evaluated):
        from famou_scientist.loop.runtime.orchestrator import Orchestrator

        self.config = config
        self._elapsed = elapsed
        self._evaluated = evaluated
        self.decisions: list[dict] = []
        self._idea_debate_directive = Orchestrator._idea_debate_directive.__get__(self)
        self.artifacts = self

    def _elapsed_wall_time_sec(self, state):  # noqa: D401 - 测试替身
        return self._elapsed

    def _evaluated_attempt_count(self):
        return self._evaluated

    def record_decision(self, payload, refs=None):
        self.decisions.append(payload)
        return "artifacts/decision.json"


def _gate(elapsed=7_200, evaluated=1, **overrides):
    config = OrchestratorConfig(idea_debate_enabled=True, **overrides)
    return _Gate(config, elapsed, evaluated)


def test_gate_closed_when_feature_disabled():
    g = _Gate(OrchestratorConfig(), 7_200, 5)
    assert g._idea_debate_directive({}) is None


def test_gate_closed_before_min_elapsed():
    """兜底时间闸门：与冲刺期排序对称，开跑一段时间后才启用。"""

    assert _gate(elapsed=1_800, evaluated=3)._idea_debate_directive({}) is None


def test_gate_closed_without_in_task_evidence():
    """实测开跑 60 分钟时 54/79 个 run 仍无评测结果——时间到了也不能开。"""

    assert _gate(elapsed=7_200, evaluated=0)._idea_debate_directive({}) is None


def test_gate_opens_when_both_conditions_met():
    state: dict = {}
    directive = _gate(elapsed=7_200, evaluated=1)._idea_debate_directive(state)
    assert directive["enabled"] is True
    assert directive["mode"] == "respond"
    assert directive["gate"]["mode"] == "in_task"
    assert directive["gate"]["evaluated_attempts"] == 1


def test_cross_task_only_gate_requires_opt_in():
    """无 in-task 证据时可以只凭跨任务经验开，但必须显式打开。"""

    closed = _gate(elapsed=7_200, evaluated=0)
    assert closed._idea_debate_directive({}) is None
    opened = _gate(
        elapsed=7_200,
        evaluated=0,
        idea_debate_allow_cross_task_only=True,
    )
    directive = opened._idea_debate_directive({})
    assert directive["gate"]["mode"] == "cross_task_only"


def test_cross_task_only_still_respects_the_time_gate():
    g = _gate(elapsed=60, evaluated=0, idea_debate_allow_cross_task_only=True)
    assert g._idea_debate_directive({}) is None


def test_activation_is_recorded_once_but_debate_stays_on():
    """与一次性的冲刺期排序不同：辩论开启后每条 Idea 都要走。"""

    g = _gate()
    state: dict = {}
    first = g._idea_debate_directive(state)
    second = g._idea_debate_directive(state)
    assert first is not None and second is not None
    scheduler = state["research_state"]["scheduler"]["idea_debate"]
    assert scheduler["status"] == "active"
    activated_at = scheduler["activated_at"]
    third = g._idea_debate_directive(state)
    assert third is not None
    assert scheduler["activated_at"] == activated_at
    assert [d["decision"] for d in g.decisions] == ["activate_idea_debate"]


def test_min_evaluated_attempts_can_be_raised():
    assert _gate(evaluated=1, idea_debate_min_evaluated_attempts=2)._idea_debate_directive({}) is None
    assert _gate(evaluated=2, idea_debate_min_evaluated_attempts=2)._idea_debate_directive({}) is not None


def test_missing_run_start_timestamp_keeps_gate_closed():
    """算不出已跑时长时按未到点处理，不要盲目启用。"""

    assert _gate(elapsed=None, evaluated=5)._idea_debate_directive({}) is None


def test_directive_carries_mode_and_rounds():
    directive = _gate(idea_debate_mode="rewrite", idea_debate_max_rounds=2)._idea_debate_directive({})
    assert directive["mode"] == "rewrite"
    assert directive["max_rounds"] == 2


# --- 闸门读数本身 ----------------------------------------------------


def test_evaluated_attempt_count_only_counts_finite_scores(tmp_path: Path):
    """工程失败与未评测的 attempt 不能算作"有证据"。"""

    from famou_scientist.loop.runtime.orchestrator import Orchestrator
    from famou_scientist.loop.storage import ExpBank

    bank = ExpBank(tmp_path)
    cases = [
        (0.25, {"valid": True}),
        (-1.5, {"valid": True}),
        # 无正式评测回执：只有分数不算证据。
        (0.9, {}),
        # evaluator 拒绝：分数不可采信。
        (0.9, {"valid": False}),
        (float("nan"), {"valid": True}),
        (float("inf"), {"valid": True}),
        (None, {"valid": True}),
    ]
    for score, evaluation in cases:
        attempt_id = bank.create_attempt(idea={"title": "T"}, lineage_id="L")
        bank.update_attempt(
            attempt_id,
            status="evaluated",
            score=score,
            evaluation=evaluation,
        )

    class _Probe:
        expbank = bank
        _finite_attempt_score = staticmethod(Orchestrator._finite_attempt_score)
        _evaluated_attempt_count = Orchestrator._evaluated_attempt_count

    assert _Probe()._evaluated_attempt_count() == 2


def test_elapsed_wall_time_prefers_active_run_start():
    from famou_scientist.loop.runtime.orchestrator import Orchestrator
    from famou_scientist.loop.utils import now_ms

    probe = type("P", (), {"_elapsed_wall_time_sec": Orchestrator._elapsed_wall_time_sec})()
    started = now_ms() - 120_000
    elapsed = probe._elapsed_wall_time_sec(
        {"research_state": {"active_run_started_at": started, "created_at": 1}}
    )
    assert 110 <= elapsed <= 130


@pytest.mark.parametrize(
    "research",
    [{}, {"active_run_started_at": None}, {"created_at": "x"}],
)
def test_elapsed_wall_time_is_none_without_a_usable_timestamp(research):
    from famou_scientist.loop.runtime.orchestrator import Orchestrator

    probe = type("P", (), {"_elapsed_wall_time_sec": Orchestrator._elapsed_wall_time_sec})()
    assert probe._elapsed_wall_time_sec({"research_state": research}) is None


# --- 端到端：配置 → 闸门 → Judge → 作者回应 → 采纳 ---------------------


def test_debate_runs_end_to_end_through_the_harness(tmp_path: Path, capsys):
    """走真实 CLI 链路验证辩论确实接上了，而不是只在单测里成立。"""

    import json
    import threading

    from famou_scientist import cmdline
    from famou_scientist.loop.tests.test_harness import _unsigned_evaluator, FIXTURES

    run_dir = tmp_path / "run"
    problem = run_dir / "problem"
    (problem / "data").mkdir(parents=True)
    (problem / "README.md").write_text("公开测试任务", encoding="utf-8")
    channel = run_dir / "controller" / "evaluator_channel"
    client = threading.Thread(target=_unsigned_evaluator, args=(channel,), daemon=True)
    client.start()

    rc = cmdline.main(
        [
            "agent",
            "run",
            "--task-id",
            "cli-debate-task",
            "--run-dir",
            str(run_dir),
            "--evaluator-channel",
            str(channel),
            "--allow-unsigned-evaluator",
            "--agent-runtime",
            "claude",
            "--model",
            "test-model",
            "--agent-binary",
            str(FIXTURES / "agents" / "fake_role_cli.py"),
            "--iterations",
            "1",
            "--agent-timeout-sec",
            "10",
            "--experiment-timeout-sec",
            "10",
            "--idea-debate",
            # 测试里没有历史评测结果，用跨任务闸门 + 零时间闸门把辩论立刻打开。
            "--idea-debate-min-elapsed-sec",
            "0",
            "--idea-debate-allow-cross-task-only",
        ]
    )
    client.join(timeout=2)
    assert rc == 0
    capsys.readouterr()

    calls = list((run_dir / "artifacts" / "worker_calls").glob("idea_judge_*.json"))
    assert calls, "Judge 没有被调用"
    debates = list((run_dir / "artifacts").rglob("idea_debate*.json"))
    assert debates, "辩论结论没有落盘"
    record = json.loads(debates[0].read_text(encoding="utf-8"))
    assert record["outcome"] == "author_revised"
    assert record["rounds"][0]["objections"][0]["evidence_refs"] == ["problem/README.md"]
    feedback = list((run_dir / "artifacts").rglob("idea_debate*.md"))
    assert feedback, "反馈 md 没有落盘"


# --- 角色白名单与配置继承 --------------------------------------------


def test_every_role_whitelist_accepts_idea_judge():
    """回归点：新增角色要同时过 4 处白名单，端到端测试曾经只在这里断掉。"""

    import inspect

    from famou_scientist.loop.execution import agent_runtime

    sources = [
        inspect.getsource(agent_runtime.CommandImplementAgent.implement),
        inspect.getsource(agent_presets.build_agent_preset_command),
    ]
    for source in sources:
        assert '"idea_judge"' in source
    # wrapper 侧的 argparse 必须接受该角色，否则子进程直接拒绝启动。
    assert '"idea_judge"' in inspect.getsource(wrapper.parse_args)


def test_both_prompt_files_exist():
    """instruction 与 wrapper 提示词缺任何一份都会让 Judge 静默失败。"""

    from famou_scientist.loop import prompts as prompt_pkg

    root = Path(prompt_pkg.__file__).parent
    assert (root / "benchmark_managed" / "idea_judge.md").is_file()
    assert (root / "cli_agents" / "idea_judge.md").is_file()


def _worker_set(goal: dict[str, Any], tmp_path) -> PromptWorkerSet:
    import famou_scientist.loop.agents.workers as mod

    original = mod._create_agent_adapter
    mod._create_agent_adapter = lambda config, **kwargs: object()
    try:
        return PromptWorkerSet(goal, tmp_path)
    finally:
        mod._create_agent_adapter = original


def _goal(idea_judge: dict[str, Any] | None) -> dict[str, Any]:
    workers: dict[str, Any] = {
        "idea": {
            "type": "agent",
            "runtime": "claude",
            "model": "claude-opus-5",
            "base_url": "https://gateway.example/v1",
            "api_key_env": "IDEA_KEY",
        }
    }
    if idea_judge is not None:
        workers["idea_judge"] = idea_judge
    return {"workers": workers}


def test_judge_inherits_idea_agent_endpoint_when_unset(tmp_path: Path):
    """只声明 type 时继承 Idea 侧已验证可用的运行时与凭据。"""

    workers = _worker_set(_goal({"type": "agent"}), tmp_path)
    config = workers.idea_judge_config
    assert config["runtime"] == "claude"
    assert config["model"] == "claude-opus-5"
    assert config["base_url"] == "https://gateway.example/v1"
    assert config["api_key_env"] == "IDEA_KEY"
    assert workers.idea_judge_agent is not None


def test_judge_model_can_be_overridden_without_losing_endpoint(tmp_path: Path):
    """换判官模型（例如 gpt-5.5）时，端点与凭据仍从 Idea 侧继承。"""

    workers = _worker_set(_goal({"type": "agent", "model": "gpt-5.5"}), tmp_path)
    config = workers.idea_judge_config
    assert config["model"] == "gpt-5.5"
    assert config["base_url"] == "https://gateway.example/v1"


def test_judge_absent_leaves_agent_unconstructed(tmp_path: Path):
    workers = _worker_set(_goal(None), tmp_path)
    assert workers.idea_judge_agent is None


def test_unknown_judge_worker_type_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="workers.idea_judge.type"):
        _worker_set(_goal({"type": "bogus"}), tmp_path)


# --- 提示词模板必须真的把请求交给模型 --------------------------------


@pytest.mark.parametrize(
    "role",
    ["idea", "idea_rank", "idea_judge", "implement", "terminal_solver", "terminal_verifier"],
)
def test_prompt_actually_contains_the_request_payload(role: str):
    """回归点：`idea_judge.md` 曾漏掉 `${request_json}` 占位符。

    builder 照常把请求传进 render_prompt，模板没有对应占位符时它被静默丢弃，
    模型于是拿不到待评 Idea 与 ExpBank 路径，只能盲判并交出"无实质缺陷"。
    端到端测试抓不到：测试用的假 CLI 从 input 文件读请求，不看提示词。
    """

    marker = "famou-request-marker-9f3c1a"
    prompt = wrapper.build_prompt(
        role=role,
        request={"metadata": {"probe": marker}},
        instruction="",
        output_path=Path("/tmp/out.json"),
        worktree_result_path=Path("/tmp/w/result.json"),
        worktree=Path("/tmp/w"),
        max_turns=None,
        submit_candidate_command="submit",
    )
    assert marker in prompt, f"{role} 的提示词没有下发请求内容"


def test_no_prompt_template_silently_drops_a_placeholder():
    """所有 cli_agents 模板都必须消费 builder 传入的请求内容。

    ``cli_agents/idea_judge.md`` 初版漏了 ``${request_json}``，判官在完全看不到
    待评 Idea 和 ExpBank 路径的情况下连续给出「无实质缺陷」，跑了 4 轮探测才定位。

    ``evolution_summarizer.md`` 是有意的例外：复盘 Agent 的取证入口是
    ``${expbank_dir}`` + ``${attempt_index}``（目录 + 路径），完整记录由它自己
    按需打开。此前它内联全量 ``request_json``，实测 286 KB ~ 1.16 MB，在 2026-08
    造成 24 次 ``Prompt is too long``。它的载荷契约由
    ``test_experience_summary_payload.py`` 单独锁住。
    """

    from famou_scientist.loop import prompts as prompt_pkg

    root = Path(prompt_pkg.__file__).parent / "cli_agents"
    payload_by_path = {"evolution_summarizer.md": ("${expbank_dir}", "${attempt_index}")}
    missing = []
    for path in sorted(root.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        markers = payload_by_path.get(path.name, ("${request_json}",))
        if not all(marker in text for marker in markers):
            missing.append(path.name)
    assert missing == [], f"这些模板不会把请求交给模型: {missing}"


# --- 只有真改过的方案才插队 ------------------------------------------


class _Sched:
    """只装配算 priority 所需的 config，方法本身用真实实现。"""

    def __init__(self, bonus=1):
        from famou_scientist.loop.runtime.orchestrator import OrchestratorConfig

        self.config = OrchestratorConfig(idea_debate_priority_bonus=bonus)

    #: 直接绑定真实实现，避免测试替身复制一份会漂移的逻辑。
    priority_for = Orchestrator._attempt_priority


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("author_revised", 2),
        ("judge_rewrote", 2),
        # 判无意见 / 作者拒绝 / 各类降级：内容没变，加速无因果意义。
        ("no_objection", 1),
        ("author_kept", 1),
        ("judge_failed_idea_preserved", 1),
        ("author_failed_idea_preserved", 1),
        ("rewrite_rejected_idea_preserved", 1),
    ],
)
def test_only_actually_revised_ideas_get_priority(outcome, expected):
    """回归点：v3 批次 22 次辩论有 18 次判无意见。

    若一并加速，队列里 priority=2 的绝大多数都是内容未变的方案，既没有因果
    意义，也会把"插队是否有用"这个测量彻底稀释。
    """

    s = _Sched()
    assert s.priority_for({"idea_debate": {"outcome": outcome}}) == expected


def test_undebated_idea_keeps_base_priority():
    assert _Sched().priority_for({"title": "T"}) == 1
    assert _Sched().priority_for({"idea_debate": None}) == 1
    assert _Sched().priority_for({"idea_debate": "yes"}) == 1


def test_priority_bonus_zero_disables_the_queue_jump():
    """对照开关：把"插队"单独关掉时，改写过的方案与普通新 Idea 同级。"""

    assert _Sched(bonus=0).priority_for({"idea_debate": {"outcome": "author_revised"}}) == 1


def test_revised_idea_outranks_plain_idea_in_the_queue(tmp_path: Path):
    """端到端确认：priority 2 的改写方案确实排在 priority 1 的新 Idea 之前。"""

    from famou_scientist.loop.domain.status import LoopStatus
    from famou_scientist.loop.storage.queues import JsonlQueue

    q = JsonlQueue(tmp_path, "benchmark_attempt_queue")
    q.push({"tag": "plain-early"}, item_type="benchmark_attempt", priority=1)
    q.push({"tag": "revised-late"}, item_type="benchmark_attempt", priority=2)
    q.push({"tag": "plain-later"}, item_type="benchmark_attempt", priority=1)
    order = [i["payload"]["tag"] for i in q.list(LoopStatus.Queue.QUEUED)]
    assert order == ["revised-late", "plain-early", "plain-later"]


# --- 从 t=0 起辩论（cross_task_only 闸门）----------------------------


def test_gate_opens_immediately_when_cross_task_only_is_allowed():
    """min_elapsed=0 + allow_cross_task_only 时，第一条 Idea 就能被评审。"""

    g = _gate(
        elapsed=5,
        evaluated=0,
        idea_debate_min_elapsed_sec=0,
        idea_debate_allow_cross_task_only=True,
    )
    directive = g._idea_debate_directive({})
    assert directive is not None
    assert directive["gate"]["mode"] == "cross_task_only"


def test_gate_switches_to_in_task_once_evidence_lands():
    """有了 in-task 证据后自动切档，判官不再受"禁止编造本 Run 事实"的限制。"""

    g = _gate(
        elapsed=5,
        evaluated=2,
        idea_debate_min_elapsed_sec=0,
        idea_debate_allow_cross_task_only=True,
    )
    assert g._idea_debate_directive({})["gate"]["mode"] == "in_task"


# --- 配对模式：原版与改写版同时入队 ----------------------------------


def test_pair_mode_emits_both_arms_when_content_changed():
    """同 Run 内配对是唯一能剥离任务难度/时段/集群波动的设计。"""

    d = _Debater([_objection()], answers=[REVISED])
    out = _emit(d, emit_pair=True)
    assert [i["title"] for i in out] == ["原方案", "改后方案"]
    origin, debated = out
    assert origin["idea_debate"]["arm"] == "origin"
    assert debated["idea_debate"]["arm"] == "debated"
    # 共享 pair_id，便于事后按对取数
    assert origin["idea_debate"]["pair_id"] == debated["idea_debate"]["pair_id"]
    assert debated["idea_debate"]["origin_idea_id"] == IDEA["id"]


def test_pair_mode_gives_the_two_arms_distinct_ids():
    """两条要各自实现、各自评测，id 不能撞。"""

    d = _Debater([_objection()], answers=[REVISED])
    origin, debated = _emit(d, emit_pair=True)
    assert origin["id"] == IDEA["id"]
    assert debated["id"] != origin["id"]


def test_pair_mode_emits_origin_first():
    """origin 先入队、debated 紧随其后：同优先级按 seq 严格 FIFO，相邻消费。"""

    d = _Debater([_objection()], answers=[REVISED])
    out = _emit(d, emit_pair=True)
    assert out[0]["idea_debate"]["arm"] == "origin"


@pytest.mark.parametrize(
    "verdicts,answers",
    [
        ([{"has_material_objection": False, "objections": []}], []),   # 无意见
        ([_objection()], [dict(IDEA)]),                                # 作者拒绝
        ([None], []),                                                  # 判官失败
    ],
)
def test_pair_mode_emits_single_idea_when_nothing_changed(verdicts, answers):
    """内容没变就没得比，不制造无意义的重复实现。"""

    out = _emit(_Debater(verdicts, answers=answers), emit_pair=True)
    assert len(out) == 1
    assert out[0]["title"] == "原方案"
    assert "arm" not in out[0]["idea_debate"]


def test_pair_mode_off_by_default_returns_only_the_revision():
    d = _Debater([_objection()], answers=[REVISED])
    out = _emit(d, emit_pair=False)
    assert len(out) == 1 and out[0]["title"] == "改后方案"


def test_paired_arms_must_share_priority():
    """回归点：给 debated 臂插队会让配对比较失效。"""

    s = _Sched()
    assert s.priority_for({"idea_debate": {"outcome": "author_revised", "arm": "debated"}}) == 1
    assert s.priority_for({"idea_debate": {"outcome": "author_revised", "arm": "origin"}}) == 1
    # 非配对模式下仍然插队
    assert s.priority_for({"idea_debate": {"outcome": "author_revised"}}) == 2


def test_emit_pair_defaults_off():
    assert OrchestratorConfig().idea_debate_emit_pair is False


@pytest.mark.parametrize("value,expected", [(True, True), (1, True), (0, False), (None, False)])
def test_emit_pair_is_normalized(value, expected):
    assert OrchestratorConfig(idea_debate_emit_pair=value).idea_debate_emit_pair is expected


def test_directive_carries_emit_pair():
    g = _gate(idea_debate_emit_pair=True)
    assert g._idea_debate_directive({})["emit_pair"] is True


# --- 消费端：两条臂都必须真的入队 ------------------------------------


class _Enqueue:
    """只装配 _enqueue_benchmark_idea_result 所需的最小依赖。

    回归点：`_run_benchmark_idea_request` 与 `_enqueue_benchmark_idea_result`
    历史上都写死 `ideas[:1]`，配对模式返回的 debated 臂被静默丢弃——而且丢的
    是改写版、留下的是原版，等于"辩论照跑、产出全扔"。单测只覆盖了
    `_run_idea_debate` 本身，没覆盖 orchestrator 的消费端，所以没抓到；
    真实批次跑了 3 小时才在产物里发现 arm 全是 origin。
    """

    def __init__(self, tmp_path, emit_pair=True, limit=None):
        from famou_scientist.loop.runtime.orchestrator import (
            Orchestrator,
            OrchestratorConfig,
        )
        from famou_scientist.loop.storage.queues import JsonlQueue

        self.config = OrchestratorConfig(
            idea_debate_enabled=True, idea_debate_emit_pair=emit_pair
        )
        self.queue = JsonlQueue(tmp_path, "benchmark_attempt_queue")
        self._limit = limit
        self.resource_declarations_required = False
        # 资源准入不是本组关注点：放行一切申报，只测配对是否两条都入队。
        self.resource_broker = type(
            "B", (), {"require_can_ever_fit": staticmethod(lambda request: None)}
        )()
        self.decisions: list[dict] = []
        self.artifacts = self
        self.queues = type("Q", (), {"benchmark_attempt": self.queue})()
        # 本组只测配对入队，不测 Idea 图：benchmark_managed + 默认关闭的
        # idea_graph_enabled 让 _record_benchmark_idea_node 直接短路。
        self.benchmark_managed = True
        self._idea_graph_active = Orchestrator._idea_graph_active.__get__(self)
        self._record_benchmark_idea_node = (
            Orchestrator._record_benchmark_idea_node.__get__(self)
        )
        self._idea_pair_enabled = Orchestrator._idea_pair_enabled.__get__(self)
        self._enqueue_benchmark_idea_result = (
            Orchestrator._enqueue_benchmark_idea_result.__get__(self)
        )
        self._schedule_one_benchmark_idea = (
            Orchestrator._schedule_one_benchmark_idea.__get__(self)
        )
        self._attempt_priority = Orchestrator._attempt_priority.__get__(self)
        self._normalize_resource_request = Orchestrator._normalize_resource_request.__get__(self)

    def _benchmark_attempt_limit(self, state):
        return self._limit

    def save_json(self, kind, obj):
        return "ref/%s" % kind

    def record_decision(self, payload, refs=None):
        self.decisions.append(payload)
        return "ref/decision"


def _pair_result():
    pid = "pair-1"
    return {
        "ideas": [
            {"id": "idea-a", "title": "原方案", "mechanism": "m",
             "idea_debate": {"outcome": "author_revised", "arm": "origin", "pair_id": pid}},
            {"id": "idea-b", "title": "改后方案", "mechanism": "m2",
             "idea_debate": {"outcome": "author_revised", "arm": "debated", "pair_id": pid,
                             "origin_idea_id": "idea-a"}},
        ]
    }


def test_both_paired_arms_reach_the_queue(tmp_path: Path):
    e = _Enqueue(tmp_path)
    assert e._enqueue_benchmark_idea_result({}, _pair_result()) == 2
    items = e.queue.list()
    arms = [(i["payload"]["idea_debate"]["arm"], i["priority"]) for i in items]
    assert arms == [("origin", 1), ("debated", 1)]


def test_paired_arms_get_consecutive_attempt_numbers(tmp_path: Path):
    e = _Enqueue(tmp_path)
    e._enqueue_benchmark_idea_result({}, _pair_result())
    nums = [i["payload"]["attempt_number"] for i in e.queue.list()]
    assert nums == [1, 2]


def test_pair_mode_off_still_enqueues_only_one(tmp_path: Path):
    """回归保护：默认路径的"一次调用只发布一条"语义不能被改坏。"""

    e = _Enqueue(tmp_path, emit_pair=False)
    assert e._enqueue_benchmark_idea_result({}, _pair_result()) == 1
    assert len(e.queue.list()) == 1


def test_attempt_budget_can_split_a_pair(tmp_path: Path):
    """预算只剩一格时先入队 origin；配对不完整，事后按 pair_id 剔除即可。"""

    e = _Enqueue(tmp_path, limit=1)
    assert e._enqueue_benchmark_idea_result({}, _pair_result()) == 1
    assert e.queue.list()[0]["payload"]["idea_debate"]["arm"] == "origin"


def test_decision_log_records_the_pairing(tmp_path: Path):
    """事后要能按 pair_id 把两条臂配起来算差值。"""

    e = _Enqueue(tmp_path)
    e._enqueue_benchmark_idea_result({}, _pair_result())
    arms = [(d.get("debate_arm"), d.get("debate_pair_id")) for d in e.decisions]
    assert arms == [("origin", "pair-1"), ("debated", "pair-1")]
