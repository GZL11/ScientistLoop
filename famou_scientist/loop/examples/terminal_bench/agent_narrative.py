"""Per-GT narratives: what the Solver understood and did after each official GT.

For every (trial, GT round n) whose GT did not pass and which is followed by a
Solver turn n+1, we condense that turn's trajectory (texts + tool calls), pair
it with the GT feedback the Solver saw and with the next GT / FinalAudit
outcome, and ask claude-opus-5 to write a fixed four-part Chinese account:
反馈 / Agent 的判断 / 做了什么 / 结果（含是否触及根因）plus a one-line summary.
Results are cached by content hash so each narrative is generated once.
"""
import hashlib, json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from agent_actions import _turn_files, _durations, files_changed, _clean  # noqa: E402

CACHE = Path(__file__).with_name("agent_narratives.json")
MODEL = os.environ.get("FAMOU_NARRATIVE_MODEL", "claude-opus-5")
WORKERS = int(os.environ.get("FAMOU_NARRATIVE_WORKERS", "8"))
FIELDS = ["一句话", "反馈", "判断", "行动", "结果", "根因命中"]
_lock = threading.Lock()


def load():
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def _save(cache):
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CACHE)


def condensed_transcript(path, budget=9000):
    """Assistant texts and tool calls of one turn, in order, trimmed to ~budget chars
    (head + evenly sampled middle + tail) so long turns stay representative."""
    segs = []
    for line in open(path, errors="replace"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("event_type") != "assistant":
            continue
        msg = (e.get("payload") or {}).get("message") or {}
        for part in msg.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and part.get("text", "").strip():
                segs.append("[说] " + _clean(part["text"], 1200))
            elif part.get("type") == "tool_use":
                inp = part.get("input") or {}
                name = part.get("name")
                if name == "Bash":
                    segs.append("[命令] " + _clean(str(inp.get("command", "")), 160))
                elif name in ("Edit", "Write", "MultiEdit"):
                    segs.append(f"[改文件] {os.path.basename(str(inp.get('file_path', '')))}")
                elif name == "Read":
                    segs.append(f"[读] {os.path.basename(str(inp.get('file_path', '')))}")
    if not segs:
        return ""
    total = sum(len(s) + 1 for s in segs)
    if total <= budget:
        return "\n".join(segs)
    head, tail = [], []
    n = 0
    for s in segs:
        if n + len(s) > budget * 0.35:
            break
        head.append(s); n += len(s) + 1
    m = 0
    for s in reversed(segs):
        if m + len(s) > budget * 0.35:
            break
        tail.insert(0, s); m += len(s) + 1
    middle = segs[len(head):len(segs) - len(tail)]
    picked, k = [], 0
    if middle:
        step = max(1, len(middle) // 12)
        for s in middle[::step]:
            if k + len(s) > budget * 0.3:
                break
            picked.append(_clean(s, 400)); k += len(s) + 1
    return "\n".join(head + [f"…（中间省略 {len(middle) - len(picked)} 步）…"] + picked + ["…"] + tail)


def _gt(trial, n):
    p = Path(trial) / "famou/controller/surrogate" / f"round_{n}.json"
    if not p.exists():
        return None
    g = json.load(open(p)).get("gt_evaluation")
    return g if g and (g.get("stdout") or "").strip() else None


def _final_audit(trial):
    p = Path(trial) / "famou/controller/final_audit/result.json"
    if not p.exists():
        return None
    r = json.load(open(p))
    return {"stdout": r.get("stdout", ""), "reward": (r.get("metrics") or {}).get("reward")}


def _error_lines(stdout, limit=1500):
    lines = [l.strip()[2:].strip() for l in (stdout or "").splitlines() if l.startswith("E ") and len(l.strip()) > 3]
    txt = "\n".join(dict.fromkeys(lines))
    return txt if len(txt) <= limit else txt[:limit] + "…"


def _next_outcome(trial, n, render):
    """The first GT after round n, else the FinalAudit."""
    files = _turn_files(trial)
    for m in range(n + 1, len(files) + 2):
        g = _gt(trial, m)
        if g:
            res, cells = render(g.get("stdout", ""))
            return f"第 {m} 轮 GT：{res}；" + ("；".join(cells) if cells else "全部通过")
    fa = _final_audit(trial)
    if fa:
        res, cells = render(fa["stdout"])
        return f"FinalAudit：{res}（reward={fa['reward']}）；" + ("；".join(cells) if cells else "全部通过")
    return "尚无后续结果（仍在运行）"


def build_item(trial, n, render):
    """Return (key, prompt, meta) for GT round n followed by turn n+1, or None."""
    g = _gt(trial, n)
    if not g or g.get("status") == "passed":
        return None
    files = _turn_files(trial)
    if n + 1 >= len(files):
        return None
    res, cells = render(g.get("stdout", ""))
    durs = _durations(trial)
    dur, status, _ = durs.get(n + 1, (None, None, None))
    ch = files_changed(trial, n + 1)
    changed = "、".join(ch[0]) if ch and ch[0] else ("产物无任何变化" if ch is not None else "产物未导出")
    instr = Path(trial) / "task-view" / "instruction.md"
    task_txt = _clean(instr.read_text(encoding="utf-8", errors="replace"), 700) if instr.exists() else ""
    transcript = condensed_transcript(files[n + 1])
    outcome = _next_outcome(trial, n, render)
    task_id = os.path.basename(str(trial)).split("-tbs-reruns")[0][4:]
    material = (
        f"【任务】{task_id}。{task_txt}\n\n"
        f"【本次官方 GT 反馈（第 {n} 轮）】{res}：{'；'.join(cells) if cells else '全部通过'}\n"
        f"原始错误行：\n{_error_lines(g.get('stdout', ''))}\n\n"
        f"【Agent 拿到反馈后的这一轮（第 {n + 1} 轮）】用时 {dur} 分钟，turn 状态 {status}；声明产物中发生变化的文件：{changed}\n"
        f"轨迹（按时间顺序，[说]=Agent 的话，[命令]/[改文件]=工具调用）：\n{transcript}\n\n"
        f"【这一轮之后的评测结果】{outcome}\n"
    )
    prompt = (
        "你是实验记录员。下面是一个 AI Agent 在科研任务中收到一次官方评测（GT）失败反馈后、那一轮的完整工作材料。"
        "请只根据材料，用中文写一段让没看过轨迹的人也能看懂的说明，严格输出一个 JSON 对象，键与要求如下：\n"
        "\"一句话\"：≤40 字，概括 Agent 这一轮做了什么、产物变没变。\n"
        "\"反馈\"：≤60 字，GT 报了什么问题（保留测试名和数值）。\n"
        "\"判断\"：≤130 字，Agent 认为失败原因是什么、打算怎么修（写它自己的理解，不要替它补充）。\n"
        "\"行动\"：≤160 字，实际做了哪些事、改了哪些东西；若产物没变要明确写「产物没变」及原因（例如它主动决定不改）。\n"
        "\"结果\"：≤130 字，对照「之后的评测结果」说明改动是否奏效；再判断 Agent 的解释是否触及真正的原因，说出依据。\n"
        "\"根因命中\"：只填 是 / 部分 / 否 / 无法判断 之一。\n"
        "要求：口语化、直接、不用「该」「其」等公文腔；测试名、文件名、数值保留原文；不要臆测材料之外的事实；不要输出 JSON 以外的任何内容。\n\n"
        + material
    )
    key = hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    meta = {"task": task_id, "round": n, "duration_min": dur, "changed": changed, "gt": res}
    return key, prompt, meta


def collect_items(trials, render):
    """All (key, prompt, meta) for every failed GT round followed by a Solver turn.
    Returns (items, {(trial_str, round): key})."""
    items, index = [], {}
    for trial in trials:
        # Round numbering can start above 0 (a turn that produced no candidate
        # has no round file), so enumerate the files that exist.
        rounds = sorted(
            int(re.search(r"round_(\d+)", p.name).group(1))
            for p in (Path(trial) / "famou/controller/surrogate").glob("round_*.json")
        ) if (Path(trial) / "famou/controller/surrogate").is_dir() else []
        for n in rounds:
            it = build_item(trial, n, render)
            if it:
                items.append(it); index[(str(trial), n)] = it[0]
    return items, index


def _call(prompt):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    out = subprocess.run(
        ["claude", "--bare", "--print", "--model", MODEL, "--output-format", "json", prompt],
        capture_output=True, text=True, timeout=420, env=env, cwd="/tmp",
    ).stdout
    result = json.loads(out).get("result", "")
    s = result[result.find("{"): result.rfind("}") + 1]
    obj = json.loads(s)
    if not all(k in obj for k in FIELDS):
        raise ValueError(f"missing fields: {sorted(set(FIELDS) - set(obj))}")
    return {k: str(obj[k]).strip() for k in FIELDS}


def ensure_narratives(items, log=sys.stderr):
    """items: list of (key, prompt, meta). Generate every missing key; return cache."""
    cache = load()
    todo = [(k, p, m) for k, p, m in items if k not in cache]
    print(f"narratives: {len(items)} needed, {len(todo)} to generate", file=log, flush=True)

    def work(entry):
        k, p, m = entry
        try:
            val = _call(p)
        except Exception as exc:  # leave missing; caller falls back
            print(f"  FAIL {m['task']} round {m['round']}: {exc}", file=log, flush=True)
            return
        with _lock:
            cache[k] = val
            _save(cache)
        print(f"  ok {m['task']} round {m['round']}", file=log, flush=True)

    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(work, todo))
    return cache


def narrative_block(nar, meta, indent="  "):
    """Markdown bullets for one GT round."""
    if nar is None:
        return f"{indent}- （叙述待生成）"
    act_hdr = f"做了什么（{meta['duration_min']} min，改动：{meta['changed']}）" if meta.get("duration_min") is not None else "做了什么"
    return "\n".join([
        f"{indent}- 反馈：{nar['反馈']}",
        f"{indent}- Agent 的判断：{nar['判断']}",
        f"{indent}- {act_hdr}：{nar['行动']}",
        f"{indent}- 结果：{nar['结果']}（根因命中：{nar['根因命中']}）",
    ])
