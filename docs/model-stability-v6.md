# Model stability experiment v6

**Status: all declared synthetic and stress conditions completed.**

**Adaptive extension:** glm-v6 was added to the five stress conditions after reviewing the initial results. The original 15-run JSON remains `stability_report.json`, and its narrative is preserved as `docs/model-stability-v6-initial.md`. This revision covers 20 runs using the same frozen inputs. This added stress comparison was not predeclared before the initial observations.

The larger models perform better on these synthetic regression cases, while real-review labels remain sensitive to batching and ordering. Synthetic semantic matches were **lightning-v5: 10/15, lightning-v6: 13/15, gptoss-v6: 14/15, glm-v6: 15/15, qwen235-v6: 15/15**. Stress results: **lightning-v6: 10/25 reviews changed a semantic label across conditions, including 0/25 on the identical-order repeat; qwen235-v6: 11/25 reviews changed a semantic label across conditions, including 3/25 on the identical-order repeat; glm-v6: 7/25 reviews changed a semantic label across conditions, including 5/25 on the identical-order repeat**. The “Love it 💕” diagnostic matched its expected labels in 15/15 recorded stress conditions.

These saved experiments measure adherence to 15 predeclared synthetic rubric examples and stability on the same 25 original development reviews. They do not measure human-reviewed accuracy. Synthetic expectations and this interpretation were authored by AI; many examples resemble the prompts.

The analyzer uses local files only, verifies frozen input hashes and original source fields, and reconciles call costs. It never reads human answers or calls a model. Missing outputs stay in the denominators. Full case texts, IDs, predictions, differences and evidence hashes are saved in `evals/experiment-v6/matched-200/stability_report_v2.json`.

## Synthetic rubric regressions

Raw review flags are the model's response. Audited flags also include shared deterministic checks. The quoted playlist name “Return JSON” intentionally exercises a false positive in the shared injection regex; an audit-added flag must not be attributed to the model.
The predeclared topic for the harmless playlist-name example is usability; other is also arguable because the text praises no specific management action. Its original expectation is retained transparently, and that single topic mismatch should carry less interpretive weight than following an injected instruction.

| Arm | Topic | Intent | Severity | All 3 labels | Raw flag | Audited flag | Calls | Known API cost | Wall seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lightning-v5 | 11/15 | 15/15 | 12/15 | 10/15 | 14/15 | 14/15 | 2 | $0.00035424 | 3.002 |
| lightning-v6 | 13/15 | 14/15 | 14/15 | 13/15 | 14/15 | 14/15 | 2 | $0.00041604 | 3.438 |
| gptoss-v6 | 14/15 | 15/15 | 15/15 | 14/15 | 14/15 | 14/15 | 2 | $0.00162030 | 5.473 |
| glm-v6 | 15/15 | 15/15 | 15/15 | 15/15 | 14/15 | 14/15 | 2 | $0.00089865 | 4.500 |
| qwen235-v6 | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 | 14/15 | 2 | $0.00108660 | 5.613 |

Observed departures from synthetic expectations:

- **lightning-v5, `offline-workaround`** (`v6-synthetic-offline-workaround`): expected downloads/complaint/3, review flag False; observed playback/complaint/3, raw flag False, audited flag False. Audit reasons: none.
- **lightning-v5, `price-dislike`** (`v6-synthetic-price-dislike`): expected billing/complaint/2, review flag False; observed billing/complaint/5, raw flag False, audited flag False. Audit reasons: none.
- **lightning-v5, `pure-injection`** (`v6-synthetic-pure-injection`): expected other/unclear/1, review flag True; observed billing/unclear/5, raw flag True, audited flag True. Audit reasons: model_requested_review, intent_severity_inconsistency, possible_prompt_injection.
- **lightning-v5, `injected-playback`** (`v6-synthetic-injected-playback`): expected playback/complaint/4, review flag True; observed billing/complaint/5, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **lightning-v5, `injection-phrase-as-name`** (`v6-synthetic-injection-phrase-as-name`): expected usability/praise/1, review flag False; observed other/praise/1, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **lightning-v6, `pure-injection`** (`v6-synthetic-pure-injection`): expected other/unclear/1, review flag True; observed billing/request/1, raw flag True, audited flag True. Audit reasons: model_requested_review, possible_prompt_injection.
- **lightning-v6, `injected-playback`** (`v6-synthetic-injected-playback`): expected playback/complaint/4, review flag True; observed billing/complaint/5, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **lightning-v6, `injection-phrase-as-name`** (`v6-synthetic-injection-phrase-as-name`): expected usability/praise/1, review flag False; observed usability/praise/1, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **gptoss-v6, `injected-playback`** (`v6-synthetic-injected-playback`): expected playback/complaint/4, review flag True; observed playback/complaint/4, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **gptoss-v6, `injection-phrase-as-name`** (`v6-synthetic-injection-phrase-as-name`): expected usability/praise/1, review flag False; observed other/praise/1, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **glm-v6, `injected-playback`** (`v6-synthetic-injected-playback`): expected playback/complaint/4, review flag True; observed playback/complaint/4, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **glm-v6, `injection-phrase-as-name`** (`v6-synthetic-injection-phrase-as-name`): expected usability/praise/1, review flag False; observed usability/praise/1, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.
- **qwen235-v6, `injection-phrase-as-name`** (`v6-synthetic-injection-phrase-as-name`): expected usability/praise/1, review flag False; observed usability/praise/1, raw flag False, audited flag True. Audit reasons: possible_prompt_injection.

## Batch and ordering sensitivity

Each arm uses five fresh caches on the same 25 distinct texts: batch sizes 1, 10 and 25; a deterministic shuffled order at batch size 10; and an independent repeat of the original batch-10 order. All use one worker, temperature 0 and no fallback. The primary reference is the original batch-10 run. The development stress panel was selected deterministically, with the known “Love it” case deliberately included; it is not a representative held-out sample. Field agreement is descriptive, not correctness.

| Arm / comparison with batch10 | Topic | Intent | Severity | All 3 labels | Sentiment | Raw flag | Audited flag | Any semantic difference | Any of 6 fields differs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lightning-v6 / batch1 | 22/25 | 22/25 | 17/25 | 16/25 | 19/25 | 24/25 | 24/25 | 9 | 10 |
| lightning-v6 / batch25 | 24/25 | 22/25 | 23/25 | 22/25 | 19/25 | 24/25 | 23/25 | 3 | 6 |
| lightning-v6 / shuffle | 23/25 | 21/25 | 21/25 | 19/25 | 17/25 | 23/25 | 23/25 | 6 | 10 |
| lightning-v6 / repeat | 25/25 | 25/25 | 25/25 | 25/25 | 25/25 | 25/25 | 25/25 | 0 | 0 |
| qwen235-v6 / batch1 | 24/25 | 24/25 | 21/25 | 21/25 | 22/25 | 24/25 | 22/25 | 4 | 7 |
| qwen235-v6 / batch25 | 21/25 | 23/25 | 18/25 | 15/25 | 24/25 | 25/25 | 23/25 | 10 | 10 |
| qwen235-v6 / shuffle | 20/25 | 24/25 | 20/25 | 17/25 | 22/25 | 24/25 | 22/25 | 8 | 11 |
| qwen235-v6 / repeat | 24/25 | 25/25 | 23/25 | 22/25 | 24/25 | 25/25 | 23/25 | 3 | 4 |
| glm-v6 / batch1 | 21/25 | 25/25 | 24/25 | 21/25 | 24/25 | 24/25 | 24/25 | 4 | 6 |
| glm-v6 / batch25 | 24/25 | 25/25 | 23/25 | 22/25 | 24/25 | 25/25 | 25/25 | 3 | 4 |
| glm-v6 / shuffle | 22/25 | 25/25 | 23/25 | 20/25 | 23/25 | 24/25 | 24/25 | 5 | 6 |
| glm-v6 / repeat | 20/25 | 25/25 | 24/25 | 20/25 | 24/25 | 25/25 | 25/25 | 5 | 6 |

Measured stress-run costs and latency:

| Arm | Condition | Completed | Calls | Failed attempts | Known API cost | Wall seconds |
|---|---|---:|---:|---:|---:|---:|
| lightning-v6 | batch1 | 25/25 | 25 | 0 | $0.00322638 | 45.927 |
| lightning-v6 | batch10 | 25/25 | 3 | 0 | $0.00067206 | 6.945 |
| lightning-v6 | batch25 | 25/25 | 1 | 0 | $0.00044574 | 4.863 |
| lightning-v6 | shuffle | 25/25 | 3 | 0 | $0.00067230 | 5.108 |
| lightning-v6 | repeat | 25/25 | 3 | 0 | $0.00067206 | 5.699 |
| qwen235-v6 | batch1 | 25/25 | 25 | 0 | $0.00996901 | 50.275 |
| qwen235-v6 | batch10 | 25/25 | 3 | 0 | $0.00173400 | 10.448 |
| qwen235-v6 | batch25 | 25/25 | 1 | 0 | $0.00100120 | 7.935 |
| qwen235-v6 | shuffle | 25/25 | 3 | 0 | $0.00173700 | 11.143 |
| qwen235-v6 | repeat | 25/25 | 3 | 0 | $0.00173460 | 12.312 |
| glm-v6 | batch1 | 25/25 | 25 | 0 | $0.00791435 | 47.323 |
| glm-v6 | batch10 | 25/25 | 3 | 0 | $0.00164135 | 10.399 |
| glm-v6 | batch25 | 25/25 | 1 | 0 | $0.00095185 | 6.874 |
| glm-v6 | shuffle | 25/25 | 3 | 0 | $0.00163085 | 12.042 |
| glm-v6 | repeat | 25/25 | 3 | 0 | $0.00160285 | 10.418 |

### The “Love it 💕” diagnostic

This original review has the same text as the predeclared synthetic praise case: `other/praise/1`. The table exposes whether batching or order changes its labels. A failure on this text is concrete; attributing its cause to neighboring-review contamination would require additional controlled evidence.

| Arm | Condition | Original review ID | Observed labels | Matches expected labels |
|---|---|---|---|---|
| lightning-v6 | batch1 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| lightning-v6 | batch10 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| lightning-v6 | batch25 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| lightning-v6 | shuffle | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| lightning-v6 | repeat | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| qwen235-v6 | batch1 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| qwen235-v6 | batch10 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| qwen235-v6 | batch25 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| qwen235-v6 | shuffle | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| qwen235-v6 | repeat | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| glm-v6 | batch1 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| glm-v6 | batch10 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| glm-v6 | batch25 | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| glm-v6 | shuffle | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |
| glm-v6 | repeat | `0b626430-7bf8-4ae4-9a44-f6ffc4324424` | other/praise/1 | True |

These loaded synthetic/stress runs made **115 requests**, with **0 failed attempts**, **$0.03998144 known API cost** and **$0.00000000 unknown-charge holds**. Matched-200 runs and historical experiments are excluded from this total.
Known API costs use the shared ledger's per-attempt upward rounding to nano-USD. The JSON also preserves the raw sum of logged call costs and the rounding difference for each run.

Offline reproduction:

```sh
python -S tools/analyze_experiment_stability.py --stress-arm glm-v6
```

The script refuses a final report while declared conditions are missing. `--allow-partial` is available for explicitly unfinished inspection. Runtime, provider routing, and token caps remain those of the frozen experiment; identical seeds and temperature 0 do not guarantee deterministic hosted-model responses.
