# Evaluation audit v6: fresh cases, routing, and evidence limits

**The main weakness is semantic quality and unresolved routing, not missing source evidence.** A fresh audit found two reviews whose reported failures are flagged as inconsistent but remain classified as requests. They therefore receive no complaint membership or severity contribution. A third review assigns an internet-connection failure to account access. Exact quotes, hashes, and cache links all remain intact.

Confidence is **high** in these trace findings and in the offline calculations below. Confidence in population accuracy is **unknown** because no human benchmark answers were supplied. The larger $50 total model budget permits stronger candidates to be tested; it does not turn model agreement into ground truth.

This audit reads the frozen v5 publication archive. It makes no paid calls and does not modify runs, prompts, configurations, golden labels, or production recommendations. All proposed corrections below are AI-assisted development judgments or explicitly marked sensitivity scenarios.

## Selection and artifact provenance

The [selection manifest](../evals/audit-v6/selection.json) freezes 12 original IDs, excluding all 60 previously inspected IDs. Six are selected by the lowest SHA-256 values of `spotify-fresh-audit-v6-20261020:` plus original ID. The other six are selected sequentially: two highest saved severity × exact-text multiplicity among complaint/cancellation records, two highest unflagged severities, and two highest flagged-but-unrouted severities. Seeded hashes break ties. These are purposeful ranking/routing strata, not a representative sample.

The two highest-multiplicity selections both contain “Worst app.” This was a consequence of selecting original IDs rather than unique texts and is retained transparently. There are **12 original IDs and 11 distinct texts**; the pair audits cache propagation but provides one independent semantic example.

The frozen `records.jsonl` SHA-256 is `d7d107cf8b390d4c2f311aa2b2e4d0d29d9a2ba19cb40059e32e91670500be02`. For all 12 cases, the six source fields match `learning_1000.csv`, official row hashes match, evidence equals the complete original text, and every extracted entity occurs in that text.

The full [JSON traces](../evals/audit-v6/case_audit.json) and [CSV](../evals/audit-v6/case_audit.csv) include the original quote, source hash, initial/final labels, fallback state, verifier output, cache origin, relevant provider request IDs, issue membership, and claim IDs. [Audit summary](../evals/audit-v6/audit_summary.json) contains all counts. Human gold status is explicitly false.

| Group | Supported business labels | Concern | Ambiguous |
|---|---:|---:|---:|
| Fresh random, six original IDs | 5 | 0 | 1 |
| Targeted, six original IDs | 2 | 3 | 1 |

These are qualitative review categories, not an accuracy estimate. Exact sentiment intensity remains subjective in some otherwise supported cases. The earlier random-30 findings are not overturned by six additional mostly supported examples.

## Fresh case findings

| Original review ID | Source evidence and saved result | Audit interpretation |
|---|---|---|
| `398566f7-2519-40e6-a2f4-6676657a18a7` | Premium skip restriction and a blank subscription-purchase page; billing/complaint/3 | Topic and intent are supported. Severity 3 versus verifier 4 exposes a rubric gap: whether a blocked purchase, while free use remains, is a “core task.” Ambiguous rather than an automatic verifier win. |
| `8c81b973-f8c0-4d32-b0e0-844601f266fa` | “Good 👍”; other/praise/1 | Supported general praise. This ID is the classification origin for a two-ID exact-text cluster. |
| `38f7068a-1d9f-49cd-8a8b-0d7b5a66bd6f` | Random app playback; “Browser version is good so far”; playback/complaint/3 | The explicit working browser supports the final severity 3 over verifier 4. Using the same service's browser does not establish cancellation. Negative direction is supported; exact sentiment intensity is less clear. |
| `9bd0779f-c0a2-4bef-8e09-92705b4f75a2` | “Amazing platform”; other/praise/1 | Supported general praise. |
| `af53cf35-c680-4ccb-b30c-cfd85bb61c57` | Free controls and lyrics moved behind Premium; billing/complaint/3 | Final billing follows the explicit paid-control rule better than verifier usability. Mixed praise does not erase the complaint. |
| `2037ccd0-4957-4d55-bc86-55eeab9a80b1` | “The new update sucks!”; other/complaint/2 | Supported generic criticism. The earlier “This new update sucks.” was assigned usability without a specific defect. Harmless wording variations reveal inconsistent rule application. |
| `8822ec39-cccc-49d8-b7e0-0bbfdbc95c5e` | “Worst app”; other/complaint/2 | Supported. Direct cache link to completed origin `06a45bd5-3ed9-43af-b7f2-8b9487e2ffff`; separate issue-other membership. |
| `eafc278c-3f57-447f-945c-580ae5a4815c` | “Worst app”; other/complaint/2 | Same supported classification and direct origin. All five original IDs in the cluster contribute five complaints and ten severity points. No alias chain was found. |
| `3df77a78-ad9a-4456-8be8-8178ffd43d67` | “Always say no internet connection” plus absent Bollywood songs; access/complaint/4 | Account access is unsupported: no login, signup, password, or account failure is described. Playback is better supported. Severity 3 versus 4 remains ambiguous because all listening is not explicitly stated to be blocked. |
| `074efbfd-f69e-46ca-9cea-e5204a192a2a` | “It's impossible to use the app without prime”; billing/complaint/4 | Billing is plausible as a paid-tier reference, but “impossible” may describe blockage or frustration with restrictions. Both models agree on 4 without resolving that ambiguity. This case enters the bounded group/memo evidence pack. |
| `ad2f2969-e6fd-4427-8e35-6f157737e1f7` | Podcasts play only in portrait; request to fix it; usability/request/3, flagged | The existing functional failure makes complaint primary. Usability/complaint/3 is better supported. No fallback occurred and the saved request label has no issue membership, suppressing one complaint and three supported severity points. |
| `ad730d1a-829a-4dc4-9561-7e1cd07e2c30` | Premium required for next-song/choice controls and seeking unavailable; billing/request/2, flagged | Reported restrictions support billing/complaint/3. The question form does not make this a pure request. Verifier fixes intent but overstates restrictions as severity 4. Saved membership is absent. |

## Routing audit: detected inconsistencies still affect metrics

On the full frozen 1,000-ID output:

- **60** final records are flagged; **47** of them have no fallback.
- **Eight** final records combine request intent with severity greater than one. All eight carry the deterministic inconsistency flag.
- **Three** final records combine complaint intent with severity one.
- The fallback allowance reaches **46 unique texts**, the floor of 5% of 926. None of the 12 fresh audited IDs received fallback, so this audit cannot estimate fallback correction effectiveness.

The request inconsistency is operationally consequential: grouping includes complaints/cancellations only. A detected but unresolved request label removes a potentially valid complaint from the ranking, rather than merely adding an uncertainty badge.

The frozen router sorts flagged candidates by a count of review reasons, then provider signal, then original ID; prior checkpoint escalations consume part of the shared quota. There is no saved per-case skip reason that clearly distinguishes quota exclusion from other causes. The final flag is not a calibrated probability of error.

Recommended harness changes:

1. Persist a routing decision for every unique text: reasons, priority, quota available, chosen/skipped, and explicit budget/quota-exhaustion reason. Carry it to every original ID.
2. Distinguish hard rubric inconsistencies from soft ambiguity. Attempt bounded repair or retain an explicit unresolved state; do not silently rewrite a semantic label by rule. Preserve the original prediction and any repair response.
3. Expose unresolved membership effects alongside the required unchanged baseline: flagged complaint count included in ranking, flagged non-complaint count excluded, and sensitivity bounds. Changing the baseline itself would break the assignment's deterministic ranking contract.
4. Test whether routing captures errors in **unflagged** records. Evaluate error capture, routing precision, nonrouted residual error, fallback correction and regression rates, end-to-end quality, cost, and coverage on human labels. Reviewing routed cases alone cannot identify missed errors.
5. Add synthetic invariance cases for punctuation/articles in generic criticism; complaint versus polite/rhetorical request; paid controls versus a paid subscriber's unrelated defect; and explicit workarounds versus complete blockage. Exclude these generated cases from business metrics.

These changes should be compared under a fixed total-cost allocation. A larger fallback quota is an experiment, not evidence of improved accuracy.

## Golden-set text overlap: labels remain blind, but texts are not wholly unseen

A source-only hash comparison found **zero overlapping original IDs**, but **three exact-text clusters** overlap between the development 1,000 and golden 50. Those clusters cover **four golden IDs**. **Two golden IDs** share text with the prior 60 AI-inspected cases; the fresh 12 do not add further golden-text exposure.

Only original source ID/text columns were processed, and the exported [overlap summary](../evals/audit-v6/golden_text_overlap.json) reveals counts rather than golden IDs or text. No human answer columns were read or displayed. This is evidence of development-text exposure, **not evidence of human-answer leakage**.

Keep the mandated evaluation on all 50. Also report an explicitly labeled **46-ID subset with no exact-text overlap with the 1,000 development inputs**. Do not quietly drop the four overlapping cases or call the whole 50 an unseen-text benchmark. Prevent further tuning on golden text or its duplicates, and audit text overlap across future splits before interpreting generalization results.

## Human evaluation protocol and statistical limits

Freeze model versions, prompts, schema, routing, and predictions before opening human answers. Present randomized original text and the rubric without stars, metadata, model outputs, route, flags, or disagreement status. Ask for labels, exact supporting spans, ambiguity, and acceptable alternatives. Two independent humans with adjudication are preferable; if only the user labels, state that fact. Do not replace failures or ambiguous cases with easier reviews.

**Current decision: the user will label 200 original reviews.** The delivered, immutable [combined worksheet](../evals/human-evaluation-v1/combined_200.html) contains the mandatory golden 50 plus 150 fresh reviews. The fresh portion has 148 distinct texts; the combined 200 contain 197 distinct texts. Keep the delivered worksheet and membership fixed. Its optional second-annotator worksheet covers 40 of these same reviews (10 mandatory and 30 fresh); it does not expand the 200-review assignment.

The fresh150 are sampled from **579,702 eligible original IDs** in the full authentic source after excluding every development and golden ID and exact text. They have zero development/golden text overlap and represent that **conditional unseen-text frame**, not the full corpus or the selected 210,000-review cohort. The [selection manifest](../evals/human-evaluation-v1/selection_manifest.json) records exclusions, source checksums, seed and inclusion probability. Preserve separate results for mandatory50, mandatory50 exposure subsets, and fresh150. An all200 score may be shown only as a descriptive score for the supplied evaluation set; pooling cannot create a representative population estimate. Reweighting the fresh150 cannot recover performance on excluded texts that had zero selection probability.

The sample-size examples below retain 300 solely to illustrate how uncertainty changes with a larger hypothetical sample. **No additional 300-review labeling run is proposed or requested.** If a later study oversamples rare topics, severity 4–5, cancellations or routed cases, record the sampling probabilities and report those strata separately. Predicted-positive sampling can estimate precision in that stratum but misses false negatives needed for recall.

Report original-ID-weighted results for the operational workload and distinct-text results for semantic coverage. Keep exact-text groups together when splitting development from holdout. Cluster resampling by text preserves the dependence created by cache reuse. The two inspected “Worst app” aliases demonstrate why five repeated IDs are not five independent language judgments.

Use Wilson intervals for ordinary independent binary proportions and exact binomial bounds for small or zero-event counts. The following are **illustrative calculations, not measured accuracy**; the formulas and assumptions follow [NIST's confidence-interval guidance](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

| Hypothetical observation | Statistical implication |
|---|---|
| 45 correct out of 50 | Wilson 95% interval: **78.64%–95.65%** |
| 27 correct out of 30 within a class | Wilson 95% interval: **74.38%–96.54%** |
| Zero errors in 50 independent cases | One-sided 95% error upper bound: **5.82%** |
| Zero errors in 300 independent cases | One-sided 95% error upper bound: **0.994%** |
| A true class prevalence of 1%, sample 50 | **60.50%** chance of observing no examples |
| A true class prevalence of 1%, sample 300 | **4.90%** chance of observing no examples |

The zero-event bound is `1 − 0.05^(1/n)`; the rare-class absence probability is `(1 − prevalence)^n`. Three hundred total reviews do not establish a rare class's recall when only a handful belong to that class. The frozen predictions themselves contain only two support-topic records, illustrating the coverage problem without establishing true support prevalence. Use design-aware uncertainty for weighted audits and clustered observations; ordinary binomial intervals do not apply to macro-F1 or MAE.

Compare stronger candidates on the same frozen human-labeled IDs. Report paired gains and regressions; use exact McNemar for paired binary correctness and paired text-cluster resampling for continuous error metrics. Five A-only wins and zero B-only wins still yield an exact two-sided p-value of **0.0625**. Predeclare primary metrics and avoid choosing a model from many exploratory comparisons without acknowledging selection. [Statsmodels documents the exact binomial McNemar calculation](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html).

Before human answers exist, candidate-model comparisons can support operational and qualitative judgments only. A more expensive model, agreement with GPT-OSS, and a fluent rationale are not independent correctness evidence.

## Ranking stability: exact arithmetic does not validate labels

The [offline sensitivity artifact](../evals/audit-v6/ranking_sensitivity.json) recomputes scores under three clearly distinguished label sets:

| Issue | Initial first-pass score | Final routed score | Fresh-case correction sensitivity |
|---|---:|---:|---:|
| Usability | 287 | 291 | 294 |
| Billing | 235 | 239 | 242 |
| Other | 218 | 233 | 233 |
| Playback | 204 | 204 | 208 |
| Access | 87 | 95 | 91 |
| Catalog | 48 | 50 | 50 |
| Downloads | 27 | 27 | 27 |
| Support | 3 | 2 | 2 |

All three preserve the eight-topic order. The last column is an in-memory **what-if** applying only the three clearer fresh findings: connection failure moves access→playback while retaining its existing uncertain severity 4; the two flagged requests become complaints at severity 3. It is not a human-corrected run. The two added memberships increase total complaints from 445 to 447 in that scenario.

The leader's final gap over billing is **52 points**. A severity-5 record moved from leader to runner-up can reduce a gap by ten points; a cached text with `m` original IDs can move it by `10m`. This is a worst-case sensitivity bound, not a prediction of actual errors.

For the next configuration, report initial/final rank order, top-three membership, top-two gap, and explicit ambiguous-label scenarios. Bootstrap resampling of fixed predicted labels measures sample robustness only. Assessing robustness to label error requires human-supported corrections or clearly labeled sensitivity assumptions, with exact-text multiplicity preserved.

## Recommended next comparison

Use the earlier 60 and these fresh 12 cases as an explicitly exposed development regression suite. Freeze a separate comparison sample before evaluating stronger candidates. Require complete trace accounting, no unresolved hard inconsistencies hidden as validated success, measured cost/throughput on identical inputs, and a report of source-supported improvements and regressions. Keep all existing run artifacts.

Choose a candidate using the full evidence: structured validity, source support, development error behavior, human results when available, routing performance, and conservative total-budget projection. Preserve the original required ranking baseline and display uncertainty alongside it. The $50 budget should cover all new calls and prior spend/holds; no additional model expenditure is needed for the offline audit itself.
