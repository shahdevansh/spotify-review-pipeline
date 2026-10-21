#!/usr/bin/env python3
"""Render the local evaluation package from saved evidence only."""
import csv,hashlib,html,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from spotify_pipeline.storage import atomic_json
from spotify_pipeline.cost import calculate_cost
P=ROOT/'private/decisions-pilot-v1';B=ROOT/'runs/decisions-v1'
def read(p):return json.loads(p.read_text())
def jl(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
d=read(P/'evaluation.json');t={x:read(B/x/'completed-stage.json') for x in ('throughput-8','throughput-16')}
allcalls=[c for p in B.glob('*/calls.jsonl') for c in jl(p)]
assert len({c['request_id'] for c in allcalls})==len(allcalls)
d['all_experiments_spend_usd']=sum(c['cost_usd'] or 0 for c in allcalls)
d['all_experiments_attempts']=len(allcalls);d['all_experiments_failed_api_attempts']=sum(c['outcome']!='succeeded' for c in allcalls)
d['throughput_experiments']=t
pa={r['review_id']:r for r in jl(B/'throughput-8/records.jsonl')};pb={r['review_id']:r for r in jl(B/'throughput-16/records.jsonl')}
d['throughput_label_changes']={f:sum(pa[k][f]!=pb[k][f] for k in pa) for f in ('topic','intent','severity','sentiment','needs_review')}
d['projected_enrichment_hours_16rps']=t['throughput-16']['wall_seconds']/t['throughput-16']['unique_texts']*d['hero_scope']['unique_texts']/3600
# Verification is deliberately sequential; add measured per-review wall time and fixed work.
v=d['stages']['1000']['stages']['verify']
d['projected_verification_hours']=v['wall_seconds']/100*2000/3600
recovery=read(B/'recovery/recovery-validation.json');d['recovery_demonstration']=recovery
# Separate post-run operational hardening from the model configuration actually evaluated.
d['post_run_operational_hardening']={'provider_caps_usd':{'decisions':23,'nebius':24},'global_hero_operational_ceiling_usd':48,'pilot_incremental_ceiling_usd':3,'unknown_legacy_charges_count_against_each_provider_cap':True,'model_prompts_and_predictions_changed':False}
# A volume change cannot change recorded measurements.
a=d['cost']['measurements'];b=calculate_cost(P/'cost/calls.jsonl',ROOT/'config/rates.csv',selected_reviews=100000,selected_unique_texts=100000,spending_limit_usd=48)['measurements']
assert a==b;d['calculator_tests']['volume_change_preserves_measurements']=True
check=P/'checker.json'
if check.exists():d['checker']=read(check)
# Audit these seeded disagreements without creating reference labels.
notes=[
('62e3e595-9ae3-499d-ba74-e43b4fb81e8e','Moderate','Cannot choose favorite parts suggests restricted seeking rather than total playback loss. New severity 3 is defensible; topic usability may be better than playback. Verifier severity 4 is not a reliable correction.'),
('e23c12dd-e6f1-469c-a6e0-506f56b7b786','Low','Smiling emojis and Ok support mild positive sentiment, but praise versus unclear is ambiguous. Do not treat verifier agreement as ground truth.'),
('a78d831a-69f4-428a-9235-cfdd9775c509','High','Explicit Premium restrictions support billing. The new usability topic misses that link; its severity 3 better reflects remaining shuffle playback than severity 4.'),
('4a2ba740-231c-406e-a7a1-c31349e99c44','Moderate','Restrictions are asserted without identifying a function. Severity 2 is better supported than 3; the new model likely infers functional loss.'),
('509915ba-cf86-4baa-9bea-a73af229ca48','Moderate','A problem playing the next song identifies a function, but does not establish blockage. Severity 3 is plausible; this merits review rather than a confident 2.'),
('50626053-301c-42fa-91aa-2f88aef82e64','Moderate','Restricted song selection and paying for ordered playback go beyond ad annoyance. Severity 3 is supported; billing versus usability requires the primary-problem tie-break.'),
('a62c808d-e338-43c8-907f-67a199ec986b','Moderate','Wrong-song playback still provides music. Severity 3 is defensible and the verifier may overstate complete blockage.'),
('7f057d48-0855-4325-950b-44f9e6fc2ee1','Moderate','Buying another service does not necessarily state leaving Spotify. Complaint is safer than inferred cancellation; ad annoyance alone supports severity 2 rather than 3.'),
('61a5ce62-a044-4cd6-be77-b2494f479c66','High','Premium-only seeking restriction supports billing and severity 3. New prediction is better aligned to the rubric than the verifier.'),
('4f6feaff-f6fb-430d-8681-592c5833d3c1','Moderate','An offline/login loop makes access versus downloads contextual. The model should flag this ambiguity instead of returning needs_review false.'),
('686fa8a8-f220-4ddd-b283-d61dd242051a','Moderate','Threat to unsubscribe supports cancellation, but the technical impact of the token error is underspecified. Verifier complaint/4 is not clearly better.'),
('d146397f-4a94-4980-be00-ae9212eca3a7','High','Explicit premium-only selection with limited skips supports billing/3, not wholly blocked playback. The new prediction is defensible.')]
audit={r['review_id']:r for r in read(P/'audit-candidates.json')};audited=[{**audit[rid],'analyst_confidence':conf,'analyst_assessment':note,'human_ground_truth':False} for rid,conf,note in notes]
atomic_json(P/'inspected-cases.json',audited);atomic_json(P/'evaluation.json',d)
h=d['human_adjudicated']['pooled_descriptive'];ver=d['against_archived_blind_verifier'];forecast=d['provider_forecast']
lines=['# Decisions + Nebius pilot: measured results','',
'**Decision: do not launch the hero run yet.** The 1,000-review pipeline works, costs fit the overall budget, and measured throughput is practical at 16 requests/second. Human-label agreement does not establish an accuracy win over frozen GLM; fallback and reference-label boundaries still need attention.','',
'## Implemented harness','',
'- OpenAI Decisions supplies topic, intent and integer severity Choices plus a sentiment Score. Full raw probabilities and request/response evidence are saved. No OpenAI generative LLM calls are used.',
'- Nebius GLM handles a capped 5% difficult-case fallback, issue descriptions and the recommendation memo. Nebius GPT-OSS supplies blind verification. Python/SQL handles exact-text reuse, validation, membership and ranking.',
'- A compact assignment-derived Decisions prompt reduced the one-review smoke input from 2,289 to 1,113 tokens. No human answers entered inference. The revised configuration was then frozen for the pilot.',
'- Malformed output/refusal checks, source-ID validation, transactional checkpoints, confidence diagnostics, call traces and offline evaluation remain explicit.',
'- Resume no longer sends already completed records to the fallback model. A real two-process recording demonstrates 10 saved records becoming 40 with zero repeated completed-ID enrichment.',
'- Added independent provider admission caps ($23 Decisions, $24 Nebius), in addition to the overall cap. Reservations and unknown charges count; untagged historical costs are conservatively counted against each provider cap. This operational hardening was unit-tested after inference; it did not change predictions.',
'- Pilot admission was limited to $3 additional spend. Hero execution still requires the user’s next instruction.','',
'## Operational results','',
'| Measurement | Result |','|---|---:|',
f'| Selected development reviews completed | 1,000 / 1,000 |',
'| Distinct development texts / exact-text aliases | 926 / 74 |',
f'| Fixed 100 cold, all stages | {d["stages"]["100-cold"]["wall_seconds"]:.2f} s; ${d["stages"]["100-cold"]["api_cost_usd"]:.5f} |',
'| Fixed 100 warm, all stages | 0.10 s; $0; zero new calls |',
f'| Cold plus incremental 1,000 pipeline | ${d["calculator_tests"]["measured_api_total_usd"]:.5f}; {d["stages"]["100-cold"]["wall_seconds"]+d["stages"]["1000"]["wall_seconds"]:.2f} s summed stage elapsed |',
f'| All new experiments including smoke, synthetic, human-side, recovery, throughput | ${d["all_experiments_spend_usd"]:.5f} |',
f'| Failed API attempts across these experiments | {d["all_experiments_failed_api_attempts"]} |',
'| Isolated 200 reviews, 8 requests/s | 27.36 s |','| Same 200, 16 requests/s | 15.68 s |',
'| Label changes between throughput repetitions | 0 across topic, intent, severity, sentiment and review flags |','',
'Costs are provider-reported tokens multiplied by dated nominal rates, not invoices or measured cash debits. The 1,000 and human-side runs overlapped under shared pacing, so their elapsed times are not isolated provider benchmarks. The two throughput tests were sequential and isolated.','',
'## Human reference: adjudicated and incomplete','',
'| Configuration | Topic /97 | Intent /98 | Severity MAE /30 | Sentiment MAE /89 |','|---|---:|---:|---:|---:|']
for name in ('lightning-v5','glm-v6','decisions-first','decisions-hybrid'):
 m=h[name];lines.append(f'| {name} | {m["topic"]["matches"]} ({m["topic"]["agreement"]:.1%}) | {m["intent"]["matches"]} ({m["intent"]["agreement"]:.1%}) | {m["severity"]["mae"]:.3f} | {m["sentiment"]["mae"]:.3f} |')
lines += ['', 'The reference is the approved adjudication-v2 snapshot. Missing fields stay missing; all models use the same denominators. The 43 approved topic edits were made after inspecting predictions, and other personal interpretations still differ from the assignment. These are agreement measurements, not blind population accuracy. Mandatory-50 and supplementary-150 results are saved separately in evaluation.json. No reference labels were changed in this pilot.', '',
'## Matched development comparison against the archived independent verifier','',
'| Configuration | Topic /1,000 | Intent /1,000 | Severity exact /1,000 | Severity MAE | Sentiment MAE |','|---|---:|---:|---:|---:|---:|']
for name,m in ver.items():lines.append(f'| {name} | {m["topic"]["agreement"]:.1%} | {m["intent"]["agreement"]:.1%} | {m["severity"]["agreement"]:.1%} | {m["severity"]["mae"]:.3f} | {m["sentiment"]["mae"]:.3f} |')
lines += ['', 'The verifier is another model, not ground truth. Twelve seeded disagreements were inspected: several verifier severity-4 judgments overstate total blockage, while some new predictions miss explicit Premium restrictions or infer cancellation. A fresh blind 100-review verification sample gave topic agreement 92% for the new hybrid versus 79% for the old pipeline, but intent was 91% versus 94%. This is mixed evidence, not a universal improvement.', '',
'## Routing and synthetic tests','',
'- Fallback processed 46 of 926 distinct texts (4.97%). Against the archived verifier it fixed 13 joint topic/intent/severity disagreements and introduced 3. On the partial human reference it reduced topic and intent agreement by one case each relative to Decisions alone.',
'- 203 of 1,000 final IDs remain flagged. Confidence bins show a useful risk gradient, but high confidence still has disagreements; confidence is not calibrated accuracy.',
'- Synthetic suite: 14/15 correct topic/intent/severity combinations; 13/15 match all expected labels plus flags. Both injected-instruction cases retain correct labels and are flagged. A playlist literally named “Return JSON” is overflagged and loses its specific topic. A serious-financial-harm case has correct labels but an extra review flag.',
'- Final consolidated targeted suite: 224 tests passed. The unmodified assignment checker passes for the declared 1,000-review scope: no missing/duplicate/invalid IDs, 74 valid cache reuses, and exact ranking/claim reconciliation. This is a pilot-scope mechanical pass, not full-assignment completion or a grade. Ranking replay reproduces saved ranking/membership; doubling rates doubles API subtotal; changing projected volume leaves pilot measurements unchanged.', '',
'## Projection for the requested 200,000-review hero cohort','',
f'The existing deterministic cohort contains **{d["hero_scope"]["unique_texts"]:,} distinct texts** in its first 200,000 nonempty rows. Exact reuse preserves all original review counts.', '',
'| Provider | Base | Conservative (1.5×) |','|---|---:|---:|',
f'| OpenAI Decisions | ${forecast["openai_decisions_base_usd"]:.2f} | ${forecast["openai_decisions_conservative_usd"]:.2f} |',
f'| Nebius fallback, 1% verification, grouping, memo | ${forecast["nebius_base_usd"]:.2f} | ${forecast["nebius_base_usd"]*1.5:.2f} |',
f'| Total new hero inference | ${forecast["total_base_usd"]:.2f} | ${forecast["total_conservative_usd"]:.2f} |','',
f'Measured 16-request/s enrichment extrapolates to about **{d["projected_enrichment_hours_16rps"]:.2f} hours**, plus approximately {d["projected_verification_hours"]:.2f} hours of independent verification and fixed downstream work. Allow additional time for sustained rate limits, retries, database publication and reconciliation. The small test is not proof of multi-hour throughput.',
'The total fits the $50 overall budget. The conservative OpenAI component exceeds the reported $25 credit, and the new $23 dispatch cap would stop earlier. Resolve that with an explicit provider-budget decision or a separately measured Nebius continuation route; do not treat remaining Nebius credit as transferable OpenAI credit.', '',
'## Recommended next changes before hero approval','',
'1. Preserve both first-pass and fallback answers. Change fallback to field-aware review: investigate uncertain fields without automatically replacing every accepted field. Validate on development data and fresh held-out cases; do not tune against the adjudicated golden answers.',
'2. Separate semantic ambiguity from literal injection-keyword matches. Keep the raw safety flag, but avoid treating a harmless playlist name as evidence that the classification is unreliable.',
'3. Finish the mandatory golden-50 reference under the assignment rubric: topic and intent currently 47/50 each, sentiment 42/50, severity 13/50. Existing corrections remain preserved; model-generated guesses cannot fill human ground truth.',
'4. Retain 16 requests/s only as the measured candidate ceiling; test sustained throughput at the required 10,000 checkpoint before continuing to 200,000. The full run is not started.',
'5. Resolve the OpenAI sub-budget, then publish final selected-run data to the database/dashboard and regenerate claims/memo from that run. The current public dashboard still represents the earlier published pilot; this report is local and private.', '',
'## Replay and evidence','',
'Run `python tools/analyze_decisions_pilot.py` then `python tools/report_decisions_pilot.py` with the project environment. These commands use saved files and make no model calls. Paid execution requires an explicit `--execute-paid` flag on `tools/run_decisions_pilot.py`.', '',
'- [Structured evaluation](evaluation.json)','- [Inspected cases](inspected-cases.json)','- [Offline cost replay](cost/replay/report.md)','- [Grading export](grading/run.json)','- [Recovery recording](../../runs/decisions-v1/recovery.cast)','- [Final test output](../../work/decisions-final-tests.log)','- [Preserved corrected annotations](../human-labels/adjudication-v2/annotations.corrected.json)',
'- [OpenAI Decisions documentation](https://developers.openai.com/api/docs/guides/decisions)','- [Nebius model-rate catalog](https://tokenfactory.nebius.com/api/public/models_info)','']
(P/'report.md').write_text('\n'.join(lines))
# Render a self-contained readable HTML report without external scripts or dependencies.
esc=html.escape;chunks=[];table=False;ul=False
for line in lines:
 if line.startswith('|'):
  if not table:chunks.append('<table>');table=True
  cells=[v.strip() for v in line.strip('|').split('|')]
  if all(set(c)<=set('-: ') for c in cells):continue
  chunks.append('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in cells)+'</tr>');continue
 if table:chunks.append('</table>');table=False
 if line.startswith('# '):chunks.append('<h1>'+esc(line[2:])+'</h1>')
 elif line.startswith('## '):chunks.append('<h2>'+esc(line[3:])+'</h2>')
 elif line:
  import re
  content=esc(line)
  content=re.sub(r'\*\*(.*?)\*\*',r'<strong>\1</strong>',content)
  content=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'<a href="\2">\1</a>',content)
  chunks.append('<p>'+content+'</p>')
chunks.append('<h2>Inspect the twelve audited cases</h2>')
for r in audited:chunks.append('<details><summary>'+esc(r['review_id'])+'</summary><blockquote>'+esc(r['review_text'])+'</blockquote><p>'+esc(r['analyst_assessment'])+'</p><pre>'+esc(json.dumps({k:r[k] for k in ['old','new','verifier']},indent=2))+'</pre></details>')
(P/'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Decisions + Nebius: 1,000-review evaluation</title><style>body{font:16px/1.55 system-ui;max-width:1150px;margin:32px auto;padding:0 24px;color:#172339;background:#fafbfc}h1{font-size:32px}h2{margin-top:36px}table{border-collapse:collapse;width:100%;background:white;font-size:14px}td{padding:10px;border:1px solid #dce3ec}tr:first-child{font-weight:700;background:#e8eef6}a{color:#125ea8}details{background:white;border:1px solid #ddd;padding:12px;margin:8px 0}pre{white-space:pre-wrap}blockquote{border-left:3px solid #aab;padding-left:16px}</style>'+''.join(chunks)+'</html>')
print(json.dumps({'report':str(P/'report.html'),'total_experiment_cost':d['all_experiments_spend_usd'],'enrich_hours':d['projected_enrichment_hours_16rps'],'verify_hours':d['projected_verification_hours']}))
