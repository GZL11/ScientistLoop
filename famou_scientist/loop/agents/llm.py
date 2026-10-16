"""端到端工作节点使用的模型客户端抽象。"""
from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from ..utils import atomic_write_json, new_id, now_ms
from ..observability import normalize_command_telemetry


class LLMError(RuntimeError):
    """表示大模型调用相关错误。"""

    def __init__(self, message: str, *, call_meta: dict[str, Any] | None = None):
        """保存错误文本及可供 Infra 记录的调用元数据。"""

        super().__init__(message)
        self.call_meta = dict(call_meta or {})


class LLMClient:
    """定义大模型客户端接口。"""
    def complete_json(self, task: str, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """调用模型并返回结构化结果。"""
        raise NotImplementedError


class DummyLLMClient(LLMClient):
    """提供确定性的测试用大模型客户端。"""
    def complete_json(self, task: str, prompt: str, context: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        """调用模型并返回结构化结果。"""
        if task == "idea_generator":
            return {
                "ideas": [
                    {
                        "title": "Prompt Prototype Router",
                        "mechanism": "Learn class prototypes and route examples through an interpretable shallow rule.",
                        "expected_gain": ["interpretability", "latency"],
                        "risks": ["may underfit complex nonlinear data"],
                        "validation_plan": ["compare to baseline", "measure latency", "ablate prototype count"],
                    },
                    {
                        "title": "HPO-only tweak",
                        "mechanism": "Tune learning rate and batch size only.",
                        "expected_gain": ["accuracy"],
                        "risks": ["low novelty"],
                        "validation_plan": ["grid search"],
                    },
                ]
            }
        if task == "idea_gate":
            idea = context.get("idea") or {}
            low = "hpo" in str(idea.get("title", "")).lower() or "tune" in str(idea.get("mechanism", "")).lower()
            return {
                "accept": not low,
                "decision": "reject" if low else "accept_to_ideaspark",
                "reasons": ["HPO-only idea is low novelty"] if low else ["contains a concrete mechanism"],
                "risks": [],
                "similar_prior_work": [],
            }
        if task == "idea_rank_judge":
            ideas = context.get("ideas") or []
            return {
                "ranking": [
                    {
                        "queue_item_id": idea.get("queue_item_id"),
                        "idea_id": idea.get("idea_id"),
                        "rank": index,
                        "reason": "dummy LLM preserves input order",
                        "scores": {
                            "feasibility": 3,
                            "score_potential": 3,
                            "time_fit": 3,
                            "resource_fit": 3,
                        },
                    }
                    for index, idea in enumerate(ideas, start=1)
                    if isinstance(idea, dict)
                ]
            }
        if task == "method_designer":
            return {
                "title": "Prototype Router Method",
                "method_summary": (
                    "Generate a small executable method that writes a submission "
                    "artifact and records the selected mechanism."
                ),
                "entrypoint": "method.py",
                "files": [
                    {
                        "path": "method.py",
                        "content": (
                            "import argparse\n"
                            "import json\n"
                            "from pathlib import Path\n"
                            "\n"
                            "parser = argparse.ArgumentParser()\n"
                            "parser.add_argument('--output', required=True)\n"
                            "args = parser.parse_args()\n"
                            "Path(args.output).parent.mkdir(parents=True, exist_ok=True)\n"
                            "Path(args.output).write_text(json.dumps({"
                            "'method': 'prototype_router', 'trained': True\n"
                            "}), encoding='utf-8')\n"
                        ),
                    }
                ],
                "experiment_plan": ["execute generated entrypoint", "evaluate submission"],
            }
        if task == "result_analyst":
            return {"promote": True, "retry": False, "decision": "promote_to_analyze_spark", "reasons": ["dummy LLM promotes smoke branch"]}
        if task == "deep_analyzer":
            return {"paper_candidate": True, "claims": ["dummy LLM deep analysis claim"], "limitations": []}
        return {}


class CommandLLMClient(LLMClient):
    """通过外部命令调用大模型客户端。"""

    def __init__(self, workspace: str | Path, cmd_template: str, *, cwd: str | Path | None = None, timeout_sec: int = 300):
        """初始化对象并保存必要配置。"""
        self.workspace = Path(workspace)
        self.cmd_template = cmd_template
        self.cwd = Path(cwd).resolve() if cwd else None
        self.timeout_sec = timeout_sec
        self.root = self.workspace / "artifacts" / "worker_calls"
        self.root.mkdir(parents=True, exist_ok=True)

    def complete_json(self, task: str, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """调用模型并返回结构化结果。"""
        call_id = new_id(f"llm_{task}")
        started_at = now_ms()
        started_monotonic = time.monotonic()
        call_dir = self.root / call_id
        call_dir.mkdir(parents=True, exist_ok=True)
        input_path = call_dir / "input.json"
        output_path = call_dir / "output.json"
        raw_path = call_dir / "raw.txt"
        meta_path = call_dir / "meta.json"
        payload = {"task": task, "prompt": prompt, "context": context, "call_id": call_id, "created_at": started_at}
        atomic_write_json(input_path, payload)
        cmd = self.cmd_template.format(
            input=shlex.quote(str(input_path)),
            output=shlex.quote(str(output_path)),
            task=shlex.quote(task),
        )
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.cwd) if self.cwd else None,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_sec,
            )
            timed_out = False
            stdout = proc.stdout
            stderr = proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            returncode = -1
        raw_path.write_text(f"[command]\n{cmd}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n", encoding="utf-8")
        parsed: dict[str, Any] = {}
        parse_error = None
        if output_path.exists():
            try:
                parsed = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                parse_error = repr(exc)
        elif stdout.strip():
            try:
                parsed = json.loads(stdout.strip().splitlines()[-1])
                atomic_write_json(output_path, parsed)
            except json.JSONDecodeError as exc:
                parse_error = repr(exc)
        else:
            parse_error = "missing output"
        finished_at = now_ms()
        telemetry = normalize_command_telemetry(parsed)
        telemetry.update(
            {
                "adapter": "single_llm_command",
                "runtime": "command",
                "role": task,
                "status": (
                    "succeeded"
                    if returncode == 0 and parse_error is None
                    else "failed"
                ),
                "started_at_ms": started_at,
                "finished_at_ms": finished_at,
                "duration_ms": int((time.monotonic() - started_monotonic) * 1000),
                "returncode": returncode,
                "trajectory": {
                    "normalized_path": None,
                    "records": 0,
                    "native_refs": [],
                    "resume_delta": False,
                },
            }
        )
        meta = {
            "id": call_id,
            "task": task,
            "command": cmd,
            "returncode": returncode,
            "timed_out": timed_out,
            "valid": returncode == 0 and parse_error is None,
            "parse_error": parse_error,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "raw_path": str(raw_path),
            "created_at": started_at,
            "finished_at": finished_at,
            "telemetry": telemetry,
        }
        atomic_write_json(meta_path, meta)
        if returncode != 0 or parse_error is not None:
            raise LLMError(
                f"LLM command failed task={task} rc={returncode} "
                f"parse_error={parse_error}; raw={raw_path}",
                call_meta=meta,
            )
        parsed["__worker_call__"] = meta
        return parsed


def llm_from_goal(goal_doc: dict[str, Any], workspace: str | Path, *, cwd: str | Path | None = None) -> LLMClient:
    """根据目标配置创建模型客户端。"""
    workers = goal_doc.get("workers") if isinstance(goal_doc.get("workers"), dict) else {}
    llm = workers.get("llm") if isinstance(workers.get("llm"), dict) else {}
    llm_type = llm.get("type") or "dummy"
    if llm_type == "command":
        return CommandLLMClient(workspace, str(llm.get("cmd") or ""), cwd=cwd, timeout_sec=int(llm.get("timeout_sec") or 300))
    return DummyLLMClient()
