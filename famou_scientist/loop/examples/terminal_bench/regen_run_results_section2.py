#!/usr/bin/env python3
"""Regenerate RUN_RESULTS_CN.md §2.1: per task, one row per (K, run) with the
FinalAudit result and the classified final failure reasons."""
import json, glob, os, re, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
from regen_run_results_section3 import render, dedup_cells  # shared failure-description + intra-run de-dup
from agent_actions import turn_summaries, reaction_cell, abnormal_turns_note
from translate_cache import translate_missing
from agent_narrative import collect_items, ensure_narratives

ROOT = Path(".famou")
TASKS = ["ode-law-discovery","baseline-free-localization","guided-wave-localization","ankle-mri-findings",
         "tamp-skill-planning","finite-free-stam","reactor-safety-control","rdkit-ic-constraints",
         "hbv-calibration-1","traffic-flux-inversion","linked-cell-suppression","small-area-equivalence"]
# credible runs per (task, K) in run order; historical K=∞ batches are per task.
HIST_INF = {"ode-law-discovery":["v19","v22","v24"],"baseline-free-localization":["v22","v24"],
            "guided-wave-localization":["v22","v24"],"ankle-mri-findings":["v20","v22","v24"],
            "tamp-skill-planning":["v23","v25","v29"],"finite-free-stam":["v21","v29"]}
FIRST4 = TASKS[:5]  # incl. tamp; baseline/finite excluded below
BATCHES = {  # K -> list of batch dirs, in run order (a task appears in a batch only if its dir exists)
    "0": ["v56-gt-final-only","v57-gt-final-only","v63-gt-final-only-b1r2","v59-gt-final-only-r2","v66-gt-final-only-b1r3","v61-gt-final-only-r3","v69-gt-final-only-c1","v70-gt-final-only-c2","v71-gt-final-only-c3"],
    "1": ["v54-gt-budget1","v64-gt-budget1-b1r2","v67-gt-budget1-b1r3","v72-gt-budget1-c1","v73-gt-budget1-c2","v74-gt-budget1-c3"],
    "5": ["v55-gt-budget5","v65-gt-budget5-b1r2","v68-gt-budget5-b1r3","v75-gt-budget5-c1","v76-gt-budget5-c2","v77-gt-budget5-c3","v80-gt-budget5-c4"],
    "∞": ["v58-gt-primary","v60-gt-primary-r2","v62-gt-primary-r3","v78-gt-primary-c1","v79-gt-primary-c2"],
}
def trial_dir(task, batch):
    return ROOT / f"tbs-reruns-{batch}" / f"tbs-{task}-tbs-reruns-{batch}"
def gt_rounds(d):
    n = 0
    for rp in glob.glob(str(d / "famou/controller/surrogate/round_*.json")):
        x = json.load(open(rp)); g = x.get("gt_evaluation")
        if g and (g.get("stdout") or "").strip(): n += 1
    return n
def gt_round_details(d):
    """One entry per candidate-level GT: the GT verdict, then what the Solver did in the
    following turn (duration, edits, artifact diff, its own closing words)."""
    out = []; k = 0
    turns = turn_summaries(d)
    seen = set()  # intra-run: a check's full description prints once, later rounds collapse to 同上·实际
    rounds = sorted(glob.glob(str(d / "famou/controller/surrogate/round_*.json")), key=lambda p: int(re.search(r"round_(\d+)", p).group(1)))
    for rp in rounds:
        x = json.load(open(rp)); g = x.get("gt_evaluation")
        if not g or not (g.get("stdout") or "").strip(): continue
        k += 1; n = int(re.search(r"round_(\d+)", rp).group(1))
        res, cells = render(g.get("stdout", ""))
        cells = dedup_cells(cells, seen)
        short = "；".join(cells) if cells else "无（全部通过）"
        line = f"**GT#{k}**（第 {n} 轮）{res}：{short}"
        nxt = turns.get(n + 1)
        if nxt is not None:
            nar = NARR.get(NARR_INDEX.get((str(d), n)))
            line += f"<br>→ Agent 之后：{reaction_cell(nxt, TRANSLATIONS, oneliner=(nar or {}).get('一句话'))}"
        elif x.get("status") == "passed":
            line += "<br>→ 候选通过，进入 FinalAudit"
        else:
            line += "<br>→ 无后续 turn（预算或额度用尽，进入 FinalAudit）"
        out.append(line)
    return out

def summarize(d):
    fa = d / "famou/controller/final_audit/result.json"
    st = d / "famou/controller/graph/state.json"
    rounds = gt_round_details(d)
    if not fa.exists():
        # A run whose graph failed before FinalAudit (e.g. verifier job-name
        # collision, harness error) is an infrastructure failure, not a result:
        # drop it from the tables entirely (RUN_RESULTS 1.3 口径).
        rs = d / "famou/controller/run_summary.json"
        if rs.exists() and json.load(open(rs)).get("outcome") == "graph_failed_before_final_audit":
            return "SKIP"
        if st.exists():
            j = json.load(open(st)); data = j.get("data", j)
            if j.get("status") == "failed":
                return "SKIP"
            return None, None, f"进行中（{j.get('phase')}，Solver 已用 {round((data.get('solver_elapsed_ms') or 0)/60000)} min）", len(rounds), rounds
        return None, None, "进行中", 0, rounds
    r = json.load(open(fa)); res, cells = render(r.get("stdout", ""))
    reward = (r.get("metrics") or {}).get("reward")
    if r.get("infrastructure_error"):
        cells = [f"基础设施错误：{r['infrastructure_error']}（结果无效）"]
    return res, reward, ("<br>".join(cells) if cells else "无（全部通过）"), len(rounds), rounds
TRANSLATIONS = {}
NARR, NARR_INDEX = {}, {}

def all_closing_texts():
    texts = []
    for task in TASKS:
        dirs = [trial_dir(task, b) for b in HIST_INF.get(task, [])]
        for K in BATCHES:
            dirs += [trial_dir(task, b) for b in BATCHES[K]]
        for d in dirs:
            if not (d / "famou").is_dir(): continue
            for n, t in turn_summaries(d).items():
                if n >= 1:
                    txt = t["last_text"] or t["first_text"]
                    if txt: texts.append(txt)
    return texts

def all_run_dirs():
    dirs = []
    for task in TASKS:
        for b in HIST_INF.get(task, []): dirs.append(trial_dir(task, b))
        for K in BATCHES:
            dirs += [trial_dir(task, b) for b in BATCHES[K]]
    return [d for d in dirs if (d / "famou").is_dir()]

def collect():
    """Return {task: {K: [(res, reward, reason, n_gt, rounds), ...]}} in run order."""
    global TRANSLATIONS, NARR, NARR_INDEX
    TRANSLATIONS = translate_missing(all_closing_texts())
    items, NARR_INDEX = collect_items(all_run_dirs(), render)
    NARR = ensure_narratives(items)
    data = {}
    for task in TASKS:
        data[task] = {}
        for K in ["0", "1", "5", "∞"]:
            runs = []
            if K == "∞":
                for b in HIST_INF.get(task, []): runs.append(trial_dir(task, b))
            for b in BATCHES[K]:
                d = trial_dir(task, b)
                if d.is_dir() and (d / "famou").is_dir(): runs.append(d)
            data[task][K] = [r + (d,) for d, r in ((d, summarize(d)) for d in runs) if r != "SKIP"]
    return data

def matrix_table(data):
    lines = ["| Task | K=0 | K=1 | K=5 | K=∞ |", "| --- | --- | --- | --- | --- |"]
    for task in TASKS:
        cells = []
        for K in ["0", "1", "5", "∞"]:
            runs = data[task][K]
            done = [r for r in runs if r[0] is not None]
            if not runs: cells.append("—"); continue
            passed = sum(1 for r in done if r[1] == 1.0)
            txt = f"{passed}/{len(done)}" if done else "0/0"
            if passed: txt = f"**{txt}**"
            pending = len(runs) - len(done)
            if pending: txt += f"（+{pending} 进行中）"
            cells.append(txt)
        lines.append(f"| `{task}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)

def main():
    data = collect()
    out = ["每格为「通过次数 / 已完成运行次数」，「—」表示未跑该配置，括号内为仍在运行的次数。K=∞ 即每轮 Solver 退出后自动调用官方 GT 的 gt_primary 模式。目标是每格 3 次可信运行。", "", matrix_table(data), "", "下面按任务列出每一次运行。「每次 GT 后的结果与未通过项目」一列按顺序记录运行期间每一次官方 GT 的判定，每条 GT 下面一行「→ Agent 之后」是 Solver 拿到该反馈后那个 turn 的概要：用时、编辑与命令次数、声明产物中哪些文件发生了变化（与上一轮导出逐字节比对），以及一句话结论。Agent 对每次反馈的理解、实际做法和是否触及根因的完整叙述见第 5 章对应任务。「产物无变化」表示 Solver 读了反馈但决定不改。FinalAudit 及其未通过项目在右侧两列（归类方法见 1.4）。K=0 没有运行期间 GT，该列为「—」。"]
    for task in TASKS:
        rows = []
        for K in ["0", "1", "5", "∞"]:
            for k, (res, reward, reason, n_gt, rounds, d) in enumerate(data[task][K], 1):
                per_gt = "<br>".join(rounds) if rounds else "—"
                note = abnormal_turns_note(d)
                if note: per_gt = f"**{note}**" + ("<br>" + per_gt if rounds else "")
                if res is None:
                    rows.append(f"| {K} | run{k} | {n_gt} | {per_gt} | {reason} | | |")
                else:
                    verdict = "**通过**" if reward == 1.0 else "未通过"
                    rows.append(f"| {K} | run{k} | {n_gt} | {per_gt} | {res} | {verdict} | {reason} |")
        if not rows: continue
        out.append(f"\n**{task}**\n\n| K | run | 运行期间 GT 次数 | 每次 GT 后的结果与未通过项目 | FinalAudit | 结果 | FinalAudit 未通过的项目（归类）：检查内容。实际值 |\n| --- | --- | ---: | --- | ---: | --- | --- |")
        out.extend(rows)
    return "\n".join(out) + "\n"

DOCS = [
    (Path("docs/benchmarks/terminal_bench_science/RUN_RESULTS_CN.md"), "<!-- section-2.1-generated-begin -->", "<!-- section-2.1-generated-end -->"),
]

def write_doc():
    body_md = main()
    for doc, BEGIN, END in DOCS:
        text = doc.read_text(encoding="utf-8")
        if BEGIN not in text:
            print(f"skip {doc.name}: markers not found"); continue
        i = text.index(BEGIN); j = text.index(END) + len(END)
        doc.write_text(text[:i] + BEGIN + "\n" + body_md + END + text[j:], encoding="utf-8")
        print(f"updated {doc.name}")

if __name__ == "__main__":
    if "--write" in sys.argv: write_doc(); print("RUN_RESULTS §2.1 regenerated")
    else: print(main())
