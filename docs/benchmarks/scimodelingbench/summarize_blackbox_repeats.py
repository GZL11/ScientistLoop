"""Archive all three repetitions, preserving protocol and adopted scores."""
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'limited_gt_blackbox_20261009'
TASKS = ('tfbind8', 'tfbind10_pho4', 'cell_dag_nas')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = []
    for task in TASKS:
        for k in (0, 1, 5, 20):
            for repeat in (1, 2, 3):
                run_id = f'{task}-limited-gt-huayan-20261009-k{k}-r{repeat}'
                run = ROOT / '.famou/scimodelingbench-fmjob-runs' / run_id
                state = json.loads((run / 'controller/limited_gt/state.json').read_text())
                summary_path = run / 'controller/run_summary.json'
                summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
                valid_queries = [q['result']['metrics']['score'] for q in state['queries']
                                 if q.get('result', {}).get('valid')
                                 and isinstance(q['result'].get('metrics', {}).get('score'), (int, float))]
                best = max(valid_queries) if valid_queries else None
                final = summary.get('final_score')
                override_path = run / 'controller/reporting_override.json'
                override = json.loads(override_path.read_text()) if override_path.exists() else {}
                supplemental_path = run / 'controller/audit_recovery/supplemental_audit.json'
                supplemental = json.loads(supplemental_path.read_text()) if supplemental_path.exists() else {}
                scores = [v for v in (best, final) if v is not None]
                used = len(state['queries'])
                assert used <= k
                assert state['wall_time_sec'] == 7200
                experiment = state['experiment']
                assert (experiment['model'], experiment['runtime'], experiment['cpu'],
                        experiment['gpu'], experiment['memory_gib']) == ('glm-5.2', 'claude', 8, 0, 32)
                rows.append(dict(task=task, k=k, repeat=repeat, gt_used=used,
                    outcome=summary.get('outcome', 'pending_final_audit'),
                    protocol_final_score=final,
                    reported_score=override.get('reported_score', final),
                    score_source=override.get('score_source', 'final_audit' if final is not None else 'missing'),
                    best_query_score=best, best_score=max(scores) if scores else None,
                    supplemental_score=supplemental.get('supplemental_score'),
                    recovered_final_audit=(run / 'controller/audit_recovery/recovery.json').exists(),
                    run_id=run_id))
    grouped = []
    for task in TASKS:
        for k in (0, 1, 5, 20):
            arms = [r for r in rows if r['task'] == task and r['k'] == k]
            group = dict(task=task, k=k, n_total=3,
                         mean_gt_used=statistics.mean(r['gt_used'] for r in arms))
            for key in ('protocol_final_score', 'reported_score', 'best_score'):
                values = [r[key] for r in arms if r[key] is not None]
                group[f'n_{key}'] = len(values)
                group[f'mean_{key}'] = statistics.mean(values) if values else None
                group[f'std_{key}'] = statistics.stdev(values) if len(values) > 1 else None
            grouped.append(group)
    write_csv(OUT / 'all_repeats_results.csv', rows)
    write_csv(OUT / 'all_repeats_grouped.csv', grouped)
    print(json.dumps({'runs':len(rows), 'pending':sum(r['outcome']=='pending_final_audit' for r in rows),
        'protocol_scored':sum(r['protocol_final_score'] is not None for r in rows),
        'reported_scored':sum(r['reported_score'] is not None for r in rows),
        'supplemental':sum(r['supplemental_score'] is not None for r in rows)}))


if __name__ == '__main__':
    main()
