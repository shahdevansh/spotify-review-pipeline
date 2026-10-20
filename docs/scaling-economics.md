# Scaling economics after the v5 learning pilot

A fresh run over **210,000 nonempty source reviews / 159,657 distinct texts** projects to **$3.52 in the base case** and **$4.74 in the declared conservative scenario**, at published Nebius rates. Both fit the remaining $18 operating allowance. The separate $2 reserve is untouched by this calculation. **Affordability does not clear the quality gate:** this report does not recommend launching 10,000 or 210,000 reviews before the label concerns are resolved.

Confidence is **moderate** in cost extrapolation and **low** in sustained runtime. The completed pilot establishes small-sample consumption; it is not a long-running production trial. All amounts below are nominal API usage priced from provider token counters, **not reconciled invoices, measured credit debits, or measured cash purchases**.

Machine-readable calculations and evidence hashes: [scaling-economics.json](scaling-economics.json). Snapshot: `2026-10-20T06:19:45.655940+00:00`. Frozen configuration: `pilot-v5-nebius`, label identity `spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb`.

## Actual evidence used

Only the final v5 `runs/pilot/100-cold/`, `runs/pilot/100-warm/`, `runs/pilot/500/`, and `runs/pilot/1000/` calls calibrate production cost. Each contains `run_summary.json` and `calls.jsonl`. Historical model screening, failed prompt versions, isolated probes, the concurrency comparison and recovery demonstration are excluded from unit calibration. Their real consumption remains in the shared budget ledger.

Run folders are excluded from Git. These are evidence paths to inspect in the local workspace or after downloading and extracting the pilot evidence release, rather than GitHub source links. The intended release tag is `v0.1.0-pilot`; the companion JSON supplies file hashes for verification.

| Checkpoint | Workers | Newly classified texts | New fallback texts | Paid verifier evaluations | Paid requests | Nominal usage | Wall seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| 100-cold | 1 | 100 | 5 | 10 | 8 | $0.00654034 | 39.803 |
| 100-warm | 1 | 0 | 0 | 0 | 0 | $0.00000000 | 0.079 |
| 500 | 2 | 379 | 18 | 50 | 25 | $0.01557036 | 73.481 |
| 1000 | 4 | 447 | 23 | 1000 | 123 | $0.09666150 | 335.334 |

The final sequence made **156 paid requests with zero failed attempts**, costing **$0.11877220** when repriced directly from tokens. Saved summaries total $0.118772214; the $0.000000014 difference is fixed-unit ledger rounding. All charged failed attempts would be included; there were none in this final v5 calibration.

The larger checkpoints reused earlier enrichment. Their row counts therefore cannot be multiplied by a single full-run cost per review. The 1,000-row learning set contains 926 distinct texts, with 46 total fallback evaluations across the checkpoints. Verification paid for 1,060 evaluation occurrences over 1,000 distinct source IDs; repeated checkpoint evaluations are real paid work. A global union of verifier IDs would give the wrong unit denominator. The warm replay made zero new model calls and cost $0 in new model usage.

| Role | Accepted evaluation units | Paid requests | Input / output tokens | Nominal usage | USD per 1,000 role evaluations |
|---|---:|---:|---:|---:|---:|
| Primary classification | 926 | 38 | 86,812 / 41,392 | $0.01514280 | $0.01635 |
| Fallback | 46 | 6 | 9,802 / 4,611 | $0.00423690 | $0.09211 |
| Independent verification | 1,060 | 106 | 186,034 / 100,576 | $0.08825070 | $0.08326 |

Grouping cost $0.00443160 and memo generation $0.00671020 across three checkpoint analysis pairs. The final-scale estimate includes **one final grouping/memo pair**, not three checkpoint pairs and not a per-review multiplier. The base uses the latest 1,000-review pair, $0.0039936; evidence is bounded rather than expanding with every review.

## Cohort and cost assumptions

The selected cohort preserves all 210,000 original nonempty IDs and classifies the 159,657 exact distinct texts once. The physical source file also retains 13 empty-text quarantines, for 210,013 rows; those rows are excluded from model-volume estimates. The full fallback scenario saturates the 5% cap: `floor(159657 × 0.05) = 7982` unique texts. Independent verification covers 1% of original IDs: `210000 × 0.01 = 2100` reviews. Verification is sampled by original ID, not only by distinct text.

Reproducing the current batching limits against the saved cohort gives **6,387 primary requests**: 6,386 batches of 25 and one batch of seven. There are no additional byte-driven splits in this source order. Fallback requires at least **799** batches at a ten-review maximum; verification requires **210** at that maximum. The eventual fallback selection can produce smaller batches; the observed per-review cost calibration already includes partial pilot batches. Batching counts exclude retries and the one final grouping/memo pair.

| Role | Full-cohort units | Base USD | Conservative USD |
|---|---:|---:|---:|
| Primary classification | 159,657 | $2.6109 | $3.1465 |
| Fallback | 7,982 | $0.7352 | $1.3706 |
| Independent verification | 2,100 | $0.1748 | $0.2118 |
| One final group/memo pair and stated allowance | One pair | $0.0040 | $0.0080 |
| **Total** | | **$3.5249** | **$4.7368** |

Base role cost is total observed charged usage divided by accepted logical evaluations, then multiplied by the production count. The numerator includes retries; retries never create extra successful denominator units. Fallback is identified by `purpose=fallback`, because its logged role is `enrich`.

For the conservative case, each role uses the larger of the observed nearest-rank P95 batch cost per accepted review and the highest checkpoint mean, then assumes **10% additional retry load**. The observed retry rate was zero: ten percent is an explicit stress assumption, not a measurement. This scenario also allows one whole retry of a final group/memo pair at the largest observed charge for each role. It is a sensitivity case, **not a statistical confidence bound or maximum bill**. Only six fallback batches were observed; their P95 is effectively the largest batch unit cost and includes a small partial batch.

| Role | Base USD / 1,000 evaluations | Higher observed unit basis before retry allowance |
|---|---:|---:|
| Primary classification | $0.01635 | $0.01792 |
| Fallback | $0.09211 | $0.15610 |
| Independent verification | $0.08326 | $0.09168 |

The calculation reserves a complete fresh-cohort run without subtracting already-paid compatible pilot cache entries. Reusing the 926 primary and 46 fallback results could avoid their observed $0.01937970; no verification-cache saving is assumed because the production sample and task batches must match. Prompt or schema revisions change cache identity and invalidate that potential saving.

## Runtime and concurrency

The original 100/500/1,000 checkpoints changed workers, review counts, cache coverage and verification counts simultaneously. They are **not a concurrency experiment**. The separate matched comparison, saved as `runs/concurrency-100-w4/comparison.json`, used the same input checksum, model configuration, batching, pacing and empty-cache start with one worker and four workers. Each completed all reviews with eight paid requests and no failures.

| Measurement | One worker | Four workers | Observed speedup |
|---|---:|---:|---:|
| Primary request span, including admission wait | 15.464 s | 10.247 s | 1.509× |
| Enrichment, including fallback | 17.448 s | 12.729 s | 1.371× |
| Whole run | 39.803 s | 31.395 s | 1.268× |
| Median primary API latency | 3.719 s | 4.666 s | — |

Four workers yielded 9.759 primary reviews/second in this single matched run, versus 6.467 with one worker. It did not produce fourfold throughput. Model outputs and service latency varied; one sequential observation at each setting does not establish stable production speedup.

Only primary classification uses worker concurrency. Fallback and verification currently await batches sequentially. The local limiter admits at most two requests/second and 10,000 **estimated admission tokens**/second; these conservative pacing tokens are not billed token counts or verified account quotas. Recorded `duration_seconds` includes admission wait; `api_duration_seconds` separates provider service time. The enrichment stage timer also includes fallback, so it is not a pure primary timer.

The base scheduling calculation uses the slower of matched four-worker primary throughput, observed API service divided across four workers, token pacing and request pacing. Serial roles use their observed service/pacing rates. The conservative case substitutes observed P95 batch latency and estimated token usage per evaluation, preserves the matched primary floor and adds the stated retry allowance.

| Scheduled work | Base hours | Conservative hours |
|---|---:|---:|
| Primary classification | 4.54 | 5.00 |
| Serial fallback | 0.73 | 1.33 |
| Serial verification | 0.16 | 0.23 |
| Final analysis | 0.004 | 0.011 |
| **API scheduling total** | **5.44** | **6.57** |

These are planning calculations, **not end-to-end completion estimates or service guarantees**. Full-cohort ingestion, checkpoint I/O, database loading/indexing, deployment and human inspection add time that this pilot did not measure at final scale. Sustained provider throttling, outages or revised prompts could change both cost and duration. The future pipeline should retain bounded concurrency and record actual progress rather than promise this completion time.

## Remaining budget and the separate quality gate

At the ledger snapshot above, settled nominal project usage was **$0.21440440**, unresolved charge holds were **$0.01644620**, and in-flight reservations were **$0.00000000**. Total committed value was **$0.23085060**, leaving **$17.7691** under the $18 operating ceiling. This includes historical experiments and diagnostics, not just the final v5 pilot. Later activity changes this snapshot; the ledger remains the admission authority.

| Budget test | USD |
|---|---:|
| Remaining operating allowance at snapshot | $17.7691 |
| Less full fresh-cohort base projection | $3.5249 |
| Headroom after base | $14.2443 |
| Less full fresh-cohort conservative projection | $4.7368 |
| Headroom after conservative | $13.0323 |

The pilot structurally completed all 1,000 reviews and all 1,000 verifier judgments, but reported 339 disagreements under its saved topic/intent/severity and sentiment-difference checks. These are **model disagreements, not a human error rate**. The [learning report](learning-report.md) records the qualitative concerns and decision to stop before expansion. Economic feasibility does not establish label accuracy, calibrated confidence, causal business conclusions or readiness to publish final-cohort findings.

## Unit prices and reproducibility

| Exact Nebius model | Role | Input USD / million | Output USD / million |
|---|---|---:|---:|
| `nvidia/Nemotron-3_5-Lightning` | Primary, thinking disabled | $0.06 | $0.24 |
| `openai/gpt-oss-120b` | Fallback, verifier, group; low reasoning | $0.15 | $0.60 |
| `zai-org/GLM-5.3-Flash` | Memo; low reasoning | $0.15 | $0.50 |

Prices were verified on October 19, 2026 against the [official Nebius public catalog](https://tokenfactory.nebius.com/api/public/models_info) and are recorded in [rates.csv](../config/rates.csv). All reported input is priced at the standard rate; no unverified cache discount is assumed. Output already includes reasoning, so reasoning tokens are not added again. [Nebius usage contract](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion).

The companion JSON records source paths and SHA-256 hashes, all checkpoint measurements, denominators, formulas, scenario parameters, the matched comparison and the ledger snapshot. The configuration is [nebius-pilot.json](../config/nebius-pilot.json); model-selection history and limitations are in [nebius-adaptation.md](nebius-adaptation.md). No paid calls or runtime/configuration changes were made to produce this report.
