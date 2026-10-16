"""Summarize what the Solver did in each turn of a terminal_task trial.

For every solver turn N>=1 (i.e. after the GT of round N-1 was fed back) we
report: duration, how many edits/commands it ran, which declared artifact files
changed versus the previous round's export, and the Solver's own closing text.
"""
import glob, hashlib, json, os, re
from pathlib import Path

def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()

def _export_files(trial, n):
    root = Path(trial) / "artifacts" / "fmjob-agent" / f"round_{n}"
    if not root.is_dir(): return None
    return {str(p.relative_to(root)): _sha(p) for p in root.rglob("*") if p.is_file()}

def files_changed(trial, n):
    cur, prev = _export_files(trial, n), _export_files(trial, n - 1)
    if cur is None or prev is None: return None
    changed = [k for k in cur if k not in prev or prev[k] != cur[k]]
    removed = [k for k in prev if k not in cur]
    return sorted(os.path.basename(k) for k in changed), sorted(os.path.basename(k) for k in removed)

def _turn_files(trial):
    out = Path(trial) / "famou" / "terminal_task_agents" / "branches" / "solver" / "outputs"
    files = glob.glob(str(out / "*.claude_agent_trajectory.jsonl"))
    def ts(p):
        m = re.search(r"implement_agent_(\d+)_", os.path.basename(p)); return int(m.group(1)) if m else 0
    return sorted(files, key=ts)

def _texts_and_tools(path):
    first = last = ""; tools = {"Edit": 0, "Write": 0, "Bash": 0, "Read": 0}
    for line in open(path, errors="replace"):
        try: e = json.loads(line)
        except Exception: continue
        if e.get("event_type") != "assistant": continue
        msg = (e.get("payload") or {}).get("message") or {}
        for part in msg.get("content") or []:
            if not isinstance(part, dict): continue
            if part.get("type") == "text" and part.get("text", "").strip():
                t = part["text"].strip()
                if not first: first = t
                last = t
            elif part.get("type") == "tool_use":
                name = part.get("name"); tools[name] = tools.get(name, 0) + 1
    return first, last, tools

def _durations(trial):
    d = {}
    ev = Path(trial) / "famou" / "controller" / "graph" / "events.jsonl"
    if not ev.exists(): return d
    for line in open(ev):
        try: e = json.loads(line)
        except Exception: continue
        r = e.get("result") or {}
        if r.get("kind") == "agent_turn":
            m = re.search(r"solver_turn_(\d+)", r.get("invocation_id", ""))
            if m:
                o = r.get("output") or {}; t = o.get("telemetry") or {}
                d[int(m.group(1))] = (round((t.get("duration_ms") or 0) / 60000), o.get("turn_status"), t.get("provider_turns"))
    return d

def _clean(t, limit):
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"`{1,3}", "", t)
    t = t.replace("|", "\\|")  # keep markdown table cells intact
    return t if len(t) <= limit else t[:limit].rstrip() + "…"

def turn_summaries(trial, text_limit=600):
    """{turn_index: {...}} for every solver turn found in the trial."""
    files = _turn_files(trial); durs = _durations(trial); out = {}
    for n, path in enumerate(files):
        first, last, tools = _texts_and_tools(path)
        dur, status, provider_turns = durs.get(n, (None, None, None))
        ch = files_changed(trial, n) if n >= 1 else None
        out[n] = {
            "duration_min": dur, "status": status, "model_turns": provider_turns,
            "edits": tools.get("Edit", 0) + tools.get("Write", 0), "bash": tools.get("Bash", 0),
            "files_changed": ch[0] if ch else None, "files_removed": ch[1] if ch else None,
            "first_text": _clean(first, text_limit), "last_text": _clean(last, text_limit),
        }
    return out

def reaction_cell(summary, translations=None, oneliner=None):
    """One-line description of a post-feedback turn. Prefers the generated one-line
    conclusion (agent_narrative.py); falls back to the Solver's own closing text,
    shown in Chinese when a translation is available (see translate_cache.py)."""
    if summary is None: return "（无后续 turn）"
    parts = []
    if summary["duration_min"] is not None:
        parts.append(f"{summary['duration_min']} min，{summary['edits']} 次文件编辑、{summary['bash']} 次命令")
    fc = summary["files_changed"]
    if fc is None: parts.append("产物未导出")
    elif not fc: parts.append("**产物无变化**")
    else: parts.append("改动：" + "、".join(fc[:4]) + ("…" if len(fc) > 4 else ""))
    if oneliner:
        parts.append(oneliner)
        return "；".join(parts)
    txt = summary["last_text"] or summary["first_text"]
    if txt:
        if translations is not None:
            from translate_cache import zh
            txt = zh(txt, translations)
        parts.append("Solver 结语：" + txt)
    return "；".join(parts)


def turn_exit_codes(trial):
    """[(turn_index, returncode)] from the CLI wrapper metadata, in turn order.
    -9 means the Solver process was SIGKILLed from outside (not a natural exit)."""
    logs = Path(trial) / "famou" / "terminal_task_agents" / "branches" / "solver" / "logs"
    files = glob.glob(str(logs / "*.claude_wrapper_meta.json"))
    def ts(p):
        m = re.search(r"implement_agent_(\d+)_", os.path.basename(p)); return int(m.group(1)) if m else 0
    out = []
    for n, path in enumerate(sorted(files, key=ts)):
        try: meta = json.load(open(path))
        except Exception: continue
        rc = meta.get("returncode")
        if rc is None: rc = (meta.get("telemetry") or {}).get("returncode")
        out.append((n, rc))
    return out

def dropped_gt_requests(trial):
    """Turns whose recovered result JSON asked for an official GT but whose round
    never ran one (the turn ended abnormally, so the graph skipped the request)."""
    files = _turn_files(trial); dropped = []
    for n, path in enumerate(files):
        rj = path.replace(".claude_agent_trajectory.jsonl", ".json")
        try: r = json.load(open(rj))
        except Exception: continue
        flag = r.get("request_official_gt")
        if not (flag is True or str(flag).lower() in {"true", "yes", "1"}): continue
        rp = Path(trial) / "famou" / "controller" / "surrogate" / f"round_{n}.json"
        gt = json.load(open(rp)).get("gt_evaluation") if rp.exists() else None
        if not gt: dropped.append(n)
    return dropped

def abnormal_turns_note(trial):
    """One-line ⚠ note when Solver turns were killed / requests dropped, else ''."""
    codes = turn_exit_codes(trial)
    killed = [n for n, rc in codes if rc == -9]
    parts = []
    if killed:
        parts.append(f"{len(codes)} 个 Solver turn 中 {len(killed)} 个被 SIGKILL（返回码 -9，非自然结束）")
    dropped = dropped_gt_requests(trial)
    if dropped:
        parts.append("第 " + "、".join(str(n) for n in dropped) + " 轮 Solver 写出了 GT 申请，但该 turn 异常结束，harness 按失败处理，申请未受理")
    return ("⚠ " + "；".join(parts)) if parts else ""
