# Five models/prompts on the same 200 development reviews

**Do not promote Lightning v6 on these results. GLM v6 is the leading candidate for the next quality gate, with GPT-OSS retained as an independent comparator.** This is a provisional engineering judgment from measured operations and targeted AI inspection, not a claim that GLM has the highest human accuracy. Synthetic behavior and batch/repeat stability are separate gates; human accuracy remains unknown.

Confidence is **high** in the reconciled accounting and observed label/ranking differences, **moderate** in the comparative qualitative judgment, and **unknown** for out-of-sample human accuracy.

## What was compared

The frozen experiment selected 200 original IDs, containing 195 exact texts, from the previously exposed 1,000-review development cohort. Protected golden IDs and exact texts were excluded. No human answers were read.

Each arm used the same review order, one worker, batches of at most ten, a separate empty result cache, and no fallback. The five duplicates retained their original review weight. Lightning v5 reruns the v5 prompt under the same newly audited engine as the other candidates; it is not a remeasurement of the historical v5 pilot.

All five arms completed all 200 IDs in twenty successful calls each, with no failed attempts. The 100 calls cost **$0.05032615 at frozen nominal token rates**, or **$0.050326164 in the shared ledger** after its per-call upward rounding to integer nano-USD. These amounts are economic API usage estimates, not cash payments or provider invoice charges.

The [machine report](../evals/experiment-v6/matched-200/comparison.json) preserves source/configuration hashes, exact call IDs, billing reconciliation, full coverage denominators, pairwise metrics, and ranking sensitivity. The [generated comparison table](../evals/experiment-v6/matched-200/comparison.md) and [case-level disagreements](../evals/experiment-v6/matched-200/comparison-cases.jsonl) are derived from the same saved outputs.

## Cost, timing, and flags

| Arm | Nominal cost | Total wall time | Reported input / output tokens | Raw / audited review flags |
|---|---:|---:|---:|---:|
| Lightning v5 | $0.00415512 | 45.91 s | 34,488 / 8,691 | 15 / 15 |
| Lightning v6 | $0.00477168 | 39.60 s | 44,708 / 8,705 | 20 / 22 |
| GPT-OSS v6, low reasoning | $0.01816665 | 56.82 s | 44,319 / 19,198 | 12 / 12 |
| GLM v6, low reasoning | $0.01112310 | 71.43 s | 43,104 / 9,315 | 10 / 10 |
| Qwen235 v6, non-thinking | $0.01210960 | 83.13 s | 43,145 / 5,801 | 25 / 25 |

These are single runs, not replicated latency estimates. Every arm uses the same nominal input-rate policy: all reported input tokens are priced once, regardless of whether a cache breakdown was provided. Output totals already include reasoning where applicable; no reasoning charge is added twice. GPT-OSS and Qwen did not report a separate reasoning-token count in these calls. Missing detail remains unknown.

Raw flags are model judgments. Audited flags add deterministic consistency checks. Lightning v6 gained two flags from those checks; Qwen also triggered two consistency checks on already flagged records, so its total did not increase. A higher flag count does not establish better error capture, and a lower count does not establish higher confidence.

For example, Lightning v6 and GLM disagree on at least one core label for 75 IDs. Lightning v6 flags twelve of those; GLM flags four. These are **flags on disagreements**, not counts of captured errors. Human labels are needed to determine which predictions, if either, are wrong.

## The business ranking depends on the candidate

The models disagree on topic, intent, or severity for **95 of 200 IDs**. They disagree on at least one of the five label fields for **125 IDs**. Among GPT-OSS, GLM, and Qwen, joint topic/intent/severity agreement ranges from **75.5% to 80.5%**. Their agreement is not a substitute for reference labels.

| Issue severity sum | Lightning v5 | Lightning v6 | GPT-OSS v6 | GLM v6 | Qwen235 v6 |
|---|---:|---:|---:|---:|---:|
| Access | 12 | 6 | 12 | 13 | 11 |
| Billing | 37 | 27 | 36 | 45 | 27 |
| Catalog | 22 | 21 | 21 | 26 | 20 |
| Downloads | 6 | 9 | 7 | 6 | 5 |
| Other | 48 | 35 | **63** | **55** | 55 |
| Playback | 22 | 27 | 32 | 24 | 27 |
| Usability | **66** | **67** | 50 | 52 | **71** |

Support has zero complaint/cancellation membership in each arm. Scores count every original review and include only complaint/cancellation records, preserving the assignment's baseline severity-sum rule.

The top issue is usability for the two Lightning prompts and Qwen, but other for GPT-OSS and GLM. “Other” is a broad taxonomy bucket; its rank does not identify a specific product intervention. A recommendation memo must not convert that rank into an unsupported subtopic prevalence claim.

Across 1,000 seeded exact-text cluster resamples, the original top issue persists in 83.3% of resamples for Lightning v5, 96.6% for Lightning v6, 74.5% for GPT-OSS, 48.1% for GLM, and 80.1% for Qwen. These are sampling sensitivity fractions, not probabilities that a ranking is correct. Lightning v6's stable ranking coexists with clear source-level mistakes.

## What the targeted AI inspection found

An independent AI reviewer inspected twenty deliberately selected disagreements, prioritizing cancellation differences, severity spread, and changes to a review's ranking contribution. This is a diagnostic case series, not a random audit or an accuracy estimate. The [inspection artifact](../evals/experiment-v6/matched-200/comparison-ai-inspection.json) preserves all twenty original texts, hashes, every model's labels, confidence in each assessment, and unresolved ambiguity.

Representative findings:

| Review ID and source | Observed output | AI assessment |
|---|---|---|
| `b92a7381-b5cd-4c77-9176-e5c4b4818c8a` — “You deserve 0 star” | Lightning v6: other / cancellation / 1; all four others: other / complaint / 2 | No departure statement supports cancellation. Lightning v6 regresses on a simple criticism. All five leave the review unflagged. |
| `87200bc4-c742-4f59-bb19-98529dfa714e` — “Hate this application 🖕🖕” | Same Lightning v6 cancellation/1 pattern; others complaint/2 | Anger is not evidence of departure. This is another unflagged regression. |
| `ce06030b-e366-4fb8-ba24-23a70988aea9` — geopolitical boycott/rating rationale | Lightning v6: cancellation/1; all others: unclear/1 | Lightning v6 invents personal departure despite the explicit boycott rule. |
| `4c415cc6-dd24-4046-a9fa-2a371e3d4fb5` — payment demanded for app features; “Bring back old Spotify” | Both Lightning arms: cancellation/2; GPT-OSS, GLM and Qwen: billing / complaint / 3 | No personal departure is stated. Lightning v6 also moves an explicit payment complaint to usability. |
| `ead2b9f1-76d0-4934-b397-e2d11d0eff73` — “I'll just go to YouTube and make a playlist there.” | Both Lightning arms: billing / cancellation / 4; GPT-OSS, GLM and Qwen: billing / complaint / 3 | Every returned combination is questionable: the other three arms miss explicit switching, while Lightning overstates restricted choice as blocked core playback. Billing / cancellation / 3 is better supported. |
| `d75d0860-2d1e-4634-97a8-ca6ca63d9d0e` — basic features need Premium; “I'm already using other apps now.” | Lightning v6 and GPT-OSS: cancellation/1; GLM and Qwen: billing / cancellation / 3 | Severity1 ignores an explicit feature restriction. GLM and Qwen better preserve the stated impact. |
| `cc39673b-e332-4f1d-a6c6-ce378a715dcb` — song choice, repeat and skipping restricted, explicitly tied to Premium | GLM: billing / complaint / 3; every other arm: playback / complaint / 4 | GLM follows the premium-control rule. The others appear to turn restricted controls into completely blocked listening. |
| `c1726764-f0ce-4abc-ad9e-6cd143e1b2c7` — cannot open Spotify Wrapped | Lightning v5, GPT-OSS, Qwen: access / complaint / 4; Lightning v6: catalog / complaint / 3; GLM: playback / complaint / 3 | Failure of Wrapped does not establish account/login failure or blocked listening. Severity3 is more plausible, but the taxonomy topic remains ambiguous. GLM flags it; the access/4 outputs do not. |

These cases identify three recurring boundaries: criticism versus personal departure, feature restrictions versus blocked core tasks, and the topic of the actual reported problem versus a feature mentioned nearby. They also show why a majority vote is insufficient: GPT-OSS, GLM and Qwen all miss the same explicit switching statement.

## Provisional candidate judgment

**Lightning v6:** do not adopt the prompt revision as an improvement. It creates clear unsupported cancellations on simple text and costs more than Lightning v5 in this matched run. Its faster observed runtime does not compensate for those specific regressions.

**Lightning v5:** retain as the cheap baseline, with known limitations. The inspection finds unsupported cancellations and overstated severity shared by both Lightning arms. Existing flags do not establish that these problems can be reliably routed away.

**GLM v6:** prioritize for the next gate. Its handling of several payment restrictions and explicit feature impacts is better supported in the inspected cases, and its measured nominal cost is lower than GPT-OSS and Qwen. This is moderate-confidence qualitative evidence, not a measured superiority claim. It still misses explicit switching, misclassifies the Wrapped task, and has an unstable top ranking in this small panel.

**GPT-OSS v6:** useful as a distinct comparator. It was faster than GLM in this run, but used substantially more output tokens and sometimes assigned severity1 despite an explicit problem. Its high agreement with GLM does not confer ground-truth status.

**Qwen235 v6:** keep through the stress gate. It recognizes some departures and restricted features, but has no operational advantage over GLM in this single trial and produces its own unsupported task/severity judgments. Its larger review-flag count is not evidence of better calibration.

No production configuration has been selected by this report. Final selection should combine the separate synthetic and stability results with the blind human evaluation. The human report must retain the mandatory fifty and the fresh one-hundred-fifty as separate sampling groups, with exposed/unseen text strata and explicit uncertainty.

## Reproduction

```sh
python tools/analyze_model_experiment.py \
  --experiment evals/experiment-v6/matched-200 \
  --prefix comparison-replay
```

The script runs offline, verifies the frozen input/configuration hashes, reconciles each logged call against frozen rates and the summary's nano-USD accounting, invokes the evaluation harness with `reference_kind="none"`, and refuses to overwrite an existing report. It reads only the matched condition; stress, synthetic, historical pilot, and human-label artifacts are not pooled into these results.
