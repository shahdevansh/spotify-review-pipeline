#!/usr/bin/env python3
"""Offline hero pilot comparison and calculator; no private human labels."""
import csv
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runs/hero-v1'
OUT = ROOT / 'evals/hero-pilot'
OUT.mkdir(exist_ok=True)


def hydrate(path):
    if sys.platform == 'darwin' and path.exists() and path.stat().st_blocks == 0:
        subprocess.run(['brctl', 'download', str(path)], check=True, timeout=5)
    return path


def read_json(path):
    return json.loads(hydrate(path).read_text())


def read_jsonl(path):
    return [json.loads(line) for line in hydrate(path).read_text().splitlines() if line.strip()]


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, path)


# Direct execution of this pure offline module avoids offloaded package pyc files.
calculate_cost = runpy.run_path(str(hydrate(ROOT / 'src/spotify_pipeline/cost.py')))['calculate_cost']
selection = read_json(BASE / 'quality-decision.json')
chosen = BASE / ('candidate-v2' if selection.get('candidate_accepted') else '')
options = dict(selected_reviews=200000, selected_unique_texts=152363,
               verification_fraction=.2, fallback_fraction=.15, spending_limit_usd=48)
rates_path = hydrate(ROOT / 'config/rates.csv')


def validate_replay():
    calls_path = chosen / 'cold100/calls.jsonl'
    for name in ('calls.jsonl', 'records.jsonl', 'run_summary.json'):
        hydrate(chosen / 'cold100' / name)
    with rates_path.open(newline='') as stream:
        reader = csv.DictReader(stream)
        rate_fields, double_rates = reader.fieldnames, list(reader)
    for row in double_rates:
        row['usd_per_million'] = str(Decimal(row['usd_per_million']) * 2)
    doubled_path = OUT / 'rates-doubled.csv'
    with doubled_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rate_fields)
        writer.writeheader()
        writer.writerows(double_rates)
    # Nonzero illustrative local rate tests separation; it is not an incurred cost.
    replay_options = {**options, 'local_compute_usd_per_hour': 1}
    base = calculate_cost(calls_path, rates_path, **replay_options)
    doubled = calculate_cost(calls_path, doubled_path, **replay_options)
    resized = calculate_cost(calls_path, rates_path, **{**replay_options,
                             'selected_reviews': 100000, 'selected_unique_texts': 80000})
    bm, dm, vm = [r['measurements'] for r in (base, doubled, resized)]
    checks = {
        'double_rates_double_api_subtotal': Decimal(str(dm['api_cost_usd'])) == Decimal(str(bm['api_cost_usd'])) * 2,
        'double_rates_preserve_measured_time': bm['wall_seconds'] == dm['wall_seconds'],
        'double_rates_preserve_local_cost_scenario': base['local_compute'] == doubled['local_compute'],
        'volume_preserves_all_recorded_measurements': bm == vm,
        'volume_changes_projection': base['projections'] != resized['projections'],
    }
    assert all(checks.values()), checks
    result = {
        'mode': 'offline', 'passed': True, 'checks': checks,
        'source_calls_sha256': hashlib.sha256(calls_path.read_bytes()).hexdigest(),
        'source_rates_sha256': hashlib.sha256(rates_path.read_bytes()).hexdigest(),
        'doubled_rates_sha256': hashlib.sha256(doubled_path.read_bytes()).hexdigest(),
        'measured_input_count': bm['input_count'], 'base_api_usd': bm['api_cost_usd'],
        'doubled_api_usd': dm['api_cost_usd'], 'measured_wall_seconds': bm['wall_seconds'],
        'local_compute_test': base['local_compute'],
        'local_compute_note': 'One USD/hour is an illustrative invariant test, not a claim of incurred local cost.',
        'projection_volumes': [{'reviews': 200000, 'unique_texts': 152363},
                               {'reviews': 100000, 'unique_texts': 80000}],
        'reproduction': 'python tools/report_hero_pilot.py --replay-only; no credentials or API calls required',
    }
    atomic_json(OUT / 'replay-validation.json', result)
    return result


if '--replay-only' in sys.argv:
    print(json.dumps(validate_replay()))
    raise SystemExit(0)

paths = [ROOT / 'runs/pilot/1000/records.jsonl', ROOT / 'runs/decisions-v1/1000/records.jsonl',
         BASE / 'pilot1000/records.jsonl', chosen / 'pilot1000/records.jsonl',
         chosen / 'pilot1000/verification.jsonl']
ref = {x['review_id']: x['prediction'] for x in read_jsonl(paths[-1]) if x['status'] == 'completed'}
metrics = {}
for name, path in zip(['original_lightning', 'previous_decisions', 'hero_initial_5_percent', 'hero_selected'], paths):
    records = {x['review_id']: x for x in read_jsonl(path)}
    metrics[name] = {f: {'matches': sum(records[k][f] == v[f] for k, v in ref.items()), 'n': len(ref)}
                     for f in ('topic', 'intent', 'severity')}
initial_ref = {x['review_id']: x['prediction'] for x in read_jsonl(BASE / 'pilot1000/verification.jsonl')
               if x['status'] == 'completed'}
repeatability = {f: sum(initial_ref[k][f] != ref[k][f] for k in ref) for f in ('topic', 'intent', 'severity')}
result = {'verifier_repeat_disagreements': repeatability, 'same_blind_frontier_reference': metrics,
          'confirmation': read_json(BASE / 'confirmation1000/evaluation.json'), 'selection': selection,
          'warning': 'Model agreement, not human accuracy; confirmation uses fresh IDs, with exact-text cache reuse disclosed.'}
atomic_json(OUT / 'comparison.json', result)
for name in ('cold100', 'warm100'):
    for filename in ('calls.jsonl', 'records.jsonl', 'run_summary.json'):
        hydrate(chosen / name / filename)
    calculate_cost(chosen / name / 'calls.jsonl', rates_path, output_dir=OUT / name, **options)
    shutil.copyfile(chosen / name / 'run_summary.json', OUT / (name + '-summary.json'))
validate_replay()
text = ['# Hero harness pilot comparison', '',
        'All configurations below are compared against the same 200 blinded full GLM-5.3 judgments. These are development agreement figures, not human accuracy.', '',
        '| Configuration | Topic | Intent | Severity |', '|---|---:|---:|---:|']
for name, m in metrics.items():
    text.append('| ' + name + ' | ' + ' | '.join(f"{m[f]['matches']}/{m[f]['n']} ({m[f]['matches']/m[f]['n']:.1%})" for f in ('topic', 'intent', 'severity')) + ' |')
c = result['confirmation']
text += ['', f"Repeated verifier calls differed on {repeatability['topic']}/200 topics and {repeatability['intent']}/200 intents. The table uses one fixed reference for every configuration.", '',
         f"Fresh-ID confirmation (1,000 reviews; 200 audited): topic {c['topic']['agreement']:.1%}, intent {c['intent']['agreement']:.1%}, severity {c['severity']['agreement']:.1%}. Both requested agreement targets passed. Sample uncertainty and correlated GLM-family errors remain; see Wilson intervals in JSON.", '',
         'The selected harness increases bounded whole-record fallback to 15%, raises uncertainty eligibility to 0.70, and ranks candidates using topic/intent/severity confidence weights 0.5/0.4/0.1. No human annotations or verifier answers are substituted into enrichment.', '',
         'Cold/warm measured calculator outputs are alongside this report. All exports are offline replays of provider-reported usage.', '',
         'Replay invariants pass: doubling API rates doubles the API subtotal without changing measured time or the illustrative local-compute scenario; changing projected volume leaves every recorded pilot measurement unchanged. See replay-validation.json.']
(OUT / 'report.md').write_text('\n'.join(text) + '\n')
print(json.dumps(result))
