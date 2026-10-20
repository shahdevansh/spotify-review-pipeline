# Matched model comparison: development evidence

All five candidates completed the same 200 original IDs (195 distinct texts). No human reference labels were used.

These measurements compare model judgments and operational behavior. They do not establish human accuracy or authorize scale-up. The v5 arm reruns its prompt under the same new audited engine; it is not the historical v5 pilot.

| Arm | Calls / failed | Nominal cost | Wall s | Input / output tokens | Raw / audited flags | Top issue (score) |
|---|---:|---:|---:|---:|---:|---|
| lightning-v5 | 20 / 0 | $0.00415512 | 45.91 | 34,488 / 8,691 | 15 / 15 | issue-usability (66) |
| lightning-v6 | 20 / 0 | $0.00477168 | 39.60 | 44,708 / 8,705 | 20 / 22 | issue-usability (67) |
| gptoss-v6 | 20 / 0 | $0.01816665 | 56.82 | 44,319 / 19,198 | 12 / 12 | issue-other (63) |
| glm-v6 | 20 / 0 | $0.01112310 | 71.43 | 43,104 / 9,315 | 10 / 10 | issue-other (55) |
| qwen235-v6 | 20 / 0 | $0.01210960 | 83.13 | 43,145 / 5,801 | 25 / 25 | issue-usability (71) |

Nominal costs reconcile each logged billing item to the frozen rate configuration and the experiment summary. They are not cash payments or invoice costs. Latencies are single trials, including repairs and local overhead. Every arm used one worker, batches of up to ten, a separate empty result cache, and no fallback.

## Pairwise agreement

| Pair | Topic | Intent | Severity exact | Core joint | Severity absolute difference |
|---|---:|---:|---:|---:|---:|
| glm-v6 / gptoss-v6 | 91.0% | 96.0% | 87.0% | 80.5% | 0.140 |
| glm-v6 / lightning-v5 | 87.0% | 87.5% | 81.5% | 71.0% | 0.205 |
| glm-v6 / lightning-v6 | 82.0% | 85.5% | 80.0% | 62.5% | 0.225 |
| glm-v6 / qwen235-v6 | 85.5% | 96.0% | 90.0% | 75.5% | 0.105 |
| gptoss-v6 / lightning-v5 | 88.5% | 90.5% | 81.0% | 72.0% | 0.215 |
| gptoss-v6 / lightning-v6 | 84.0% | 86.5% | 79.0% | 63.5% | 0.235 |
| gptoss-v6 / qwen235-v6 | 88.5% | 95.5% | 88.5% | 78.5% | 0.125 |
| lightning-v5 / lightning-v6 | 91.0% | 90.0% | 87.5% | 76.0% | 0.150 |
| lightning-v5 / qwen235-v6 | 87.0% | 91.0% | 83.0% | 69.5% | 0.190 |
| lightning-v6 / qwen235-v6 | 84.5% | 88.5% | 81.5% | 64.5% | 0.210 |

All pairwise denominators are 200. The first candidate is a comparator, not ground truth. JSON includes Wilson diagnostics and seeded exact-text cluster intervals.

## Issue score sensitivity

| Issue | lightning-v5 | lightning-v6 | gptoss-v6 | glm-v6 | qwen235-v6 |
|---|---:|---:|---:|---:|---:|
| issue-access | 12 | 6 | 12 | 13 | 11 |
| issue-billing | 37 | 27 | 36 | 45 | 27 |
| issue-catalog | 22 | 21 | 21 | 26 | 20 |
| issue-downloads | 6 | 9 | 7 | 6 | 5 |
| issue-other | 48 | 35 | 63 | 55 | 55 |
| issue-playback | 22 | 27 | 32 | 24 | 27 |
| issue-usability | 66 | 67 | 50 | 52 | 71 |

Scores preserve every original ID and use severity sums for complaint/cancellation records only. Top-issue stability is sensitivity to predictions and the development sample, not business impact.

95 IDs differ on at least one topic/intent/severity label across the five arms; 125 differ on at least one of the five label fields.

## Reproduction and scope

Run `python tools/analyze_model_experiment.py --experiment evals/experiment-v6/matched-200 --prefix comparison-replay` to create a new report without replacing this one. Saved artifacts are `comparison.json`, `comparison.md`, and `comparison-cases.jsonl` in the experiment directory. The JSON records source, config, input, call-log, script, and harness hashes plus exact request IDs.

The panel is sampled from already exposed development data, excluding protected golden IDs and exact texts. No generalization estimate follows from this panel. Named human holdout groups remain separate and blind. Case inspection is explicitly an AI qualitative audit; targeted cases cannot yield an error-rate estimate.
