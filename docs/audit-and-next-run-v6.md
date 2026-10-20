# Evaluation audit and the next controlled run

The pipeline accounts for its inputs and reproduces its arithmetic, but its classification accuracy and product recommendation are not established. The larger budget makes stronger first-pass models affordable; it does not resolve inconsistent labels or rubric ambiguity. Keep the published 1,000-review result provisional and evaluate the frozen candidates against blind human annotations before expansion.

Confidence is **high** in the saved accounting and observed test outcomes, **moderate** in cost extrapolation and the choice of GLM as the next candidate, and **unknown** in human accuracy and full-dataset completion time.

## Human annotation: what is ready and when it is used

The [interactive worksheet](../evals/human-evaluation-v1/combined_200.html) contains the required 50 reviews followed by 150 additional reviews. It hides model predictions, star ratings, routing, and disagreement status. Choose an annotator ID, use the embedded rubric, and download JSON backups after each session. Answers belong under the ignored `private/human-labels/` directory.

The 150 additional reviews contain 148 distinct texts, with no exact-text overlap with development or the golden set. They were sampled from a conditional frame of 579,702 eligible original IDs. The combined 200 contain 197 distinct texts. Report the mandatory 50 and fresh 150 separately; their pooled score is not a representative full-corpus accuracy estimate. Four mandatory IDs share development text, so retain all 50 and additionally report the 46 unseen-text cases.

Human answers are needed **before the final model decision and expansion gate**. Development comparisons, structural checks, and source-only preparation can proceed beforehand. Freeze candidate configurations and predictions before opening answers. Revisions informed by those answers must be reported as test-informed development and require new held-out evidence for a fresh generalization claim.

The primary planned contrast is GLM v6 against the Lightning v5 prompt under the same audited engine, input records, and batch size. These are first-pass classifiers, with fallback disabled for the matched comparison. This does not by itself evaluate the later routed system. The [human protocol](human-evaluation-protocol.md) explains ambiguity, acceptable alternatives, and optional independent second annotation.

Both arms now have sealed predictions for all 200 IDs. The [public receipt](../validation/sealed_human_predictions_v1.json) exposes only completion, cost, source/configuration identities, and artifact hashes. No human answers or predicted label values were inspected. Lightning used 20 attempts; GLM completed after 21 attempts including one failed attempt. All prediction content remains private until scoring.

## What to measure

| Question | Measure | Interpretation |
|---|---|---|
| Are labels correct against the human rubric? | Topic/intent accuracy, per-class precision/recall/F1, severity exact agreement and MAE, sentiment MAE, joint topic/intent/severity agreement | Human-referenced results, with source counts and missing/invalid predictions explicit |
| Does routing find the errors? | Flag precision, error capture, residual error among accepted unflagged cases, fallback corrections and regressions | Requires human labels; a model flag is not calibrated confidence |
| Are outputs complete and traceable? | ID coverage, original field/hash preservation, schema validity, quote containment, entity matches, direct cache provenance | Mechanical integrity; exact quotes do not establish semantic support |
| Are conclusions robust? | Alternative-label rankings, top-issue changes, score gaps, text-cluster resampling | Sensitivity to samples and judgments; not proof of business impact |
| Is inference stable? | Identical repeats, changed order, changed batch size, adversarial synthetic cases | Measured regression behavior, kept outside business metrics |
| Can the job finish within constraints? | Total tokens/cost including retries and holds, failed/uncertain attempts, throughput, stage latency, checkpoint/recovery time and memory | Full-system measurements; first-pass concurrency does not accelerate serial downstream stages automatically |

The [offline harness](evaluation-harness.md) implements these distinctions, source-bound comparisons, failure denominators, named evaluation groups, paired comparisons, Wilson diagnostics, and exact-text cluster bootstrap. It suppresses bootstrap bounds when too few contributing clusters or resamples exist and identifies degenerate results. There is no human accuracy field populated from model agreement.

## Concrete audit findings

The [fresh 12-case audit](evaluation-audit-v6.md) follows source text through classification, fallback, verification, issue membership, and numerical claims. Examples:

- A podcast playback/layout failure phrased as a request to fix it remains `request`, despite being flagged. It receives no complaint membership or severity contribution.
- Paid song-selection restrictions likewise remain a flagged request; a complaint interpretation is better supported by the source.
- “No internet connection” is classified as account access despite no account or login failure being described.
- Two identical “Worst app” reviews have correct direct cache provenance. All five original IDs in that text cluster contribute separately to the ranking, demonstrating why cached multiplicity must remain in business aggregates.

These are AI-assisted qualitative judgments, not human ground truth or a prevalence estimate. The fresh audit separates six random and six targeted IDs. A separate [20-case matched-model inspection](model-comparison-v6.md) also records shared larger-model mistakes; majority agreement is never treated as the answer.

The most consequential dashboard finding is that identical aggregation over the same 1,000 IDs yields **usability first under final labels (291 points)** but **playback first under verifier labels (319 points)**. The verifier is fallible too. This establishes that the product priority depends materially on unvalidated classifications.

## New model experiments

All five configurations completed the same 200 development IDs, representing 195 distinct texts, with 20 requests and no failed attempts per arm. All used one worker, batches of at most ten, fresh result caches, and no fallback.

| Configuration | Nominal matched-run cost | Engine wall seconds | Synthetic semantic matches |
|---|---:|---:|---:|
| Lightning, v5 prompt | $0.00415512 | 45.91 | 10/15 |
| Lightning, revised v6 prompt | $0.00477168 | 39.60 | 13/15 |
| GPT-OSS 120B, v6 | $0.01816665 | 56.82 | 14/15 |
| GLM 5.3 Flash, v6 | $0.01112310 | 71.43 | 15/15 |
| Qwen 235B Instruct, v6 | $0.01210960 | 83.13 | 15/15 |

“Synthetic semantic matches” means agreement with predefined topic/intent/severity tuples, not measured natural-review accuracy. Some cases are close to prompt examples. Lightning v6 still follows injected billing instructions in two cases. GPT-OSS's single mismatch concerns the debatable topic of a harmless playlist name. The shared heuristic also flags that harmless phrase, exposing a false-positive route.

Across the matched panel, 95/200 IDs have at least one topic/intent/severity disagreement among candidates. The leading issue changes between usability and other. The v6 prompt is therefore **not automatically an improvement** for Lightning; the development inspection found unsupported cancellation predictions.

The [stability experiment](model-stability-v6.md) tested the same 25 distinct development texts:

| Model | IDs with any semantic change across conditions | Semantic changes on identical batch-10 repeat |
|---|---:|---:|
| Lightning v6 | 10/25 | 0/25 |
| Qwen v6 | 11/25 | 3/25 |
| GLM v6 | 7/25 | 5/25 |

Conditions were batch sizes 1/10/25, shuffled order, and an identical-order repeat. GLM was added adaptively after observing Qwen's sensitivity. These small panels do not estimate population error. They rule out assuming deterministic semantics from temperature zero. The historical “Love it 💕” misclassification was not reproduced in any of the 15 stress runs.

GLM remains the provisional next candidate because of its development behavior and economics, not because it has demonstrated human accuracy or complete stability. Preserve the v5 baseline and use the human comparison to assess gains and regressions.

## Cost, runtime, and scope

The 235 development experiment calls through the four-worker probe cost $0.10159967 at the saved nominal token rates, or $0.101599706 after per-call ledger rounding. The subsequent 41 sealed holdout attempts added $0.019357193. Total new nominal ledger usage for this audit is **$0.120956899**. The final project snapshot is **$0.335913993 known usage plus $0.0164462 earlier uncertain-charge holds = $0.352360193 committed**, with no in-flight reservations. These are token-value estimates and budget holds, not cash purchases or a provider credit balance.

The original matched-development calibration in the [measured cost model](model-options-v6.md) projects approximately **$34.02 for GLM**, **$36.72 for Qwen**, and **$53.26 for GPT-OSS** over all 660,609 nonempty source IDs, using 484,189 distinct texts. Scenarios include prior commitments, a 5% fallback allowance, 1% verification, 10% retry allowance, and $0.25 for final grouping/memo. Downstream unit costs are explicitly identified v5 proxies; these are not observed full runs. Higher-cost sensitivities and token assumptions are preserved in the machine-readable projection.

The subsequent [sealed-prediction cost sensitivity](model-options-v6.md#sealed-prediction-receipt-cost-only-sensitivity) is more conservative: GLM cost per distinct text was 34.94% higher on that separate sample, including its observed failed attempt. Applying that unit cost and a further 10% variable-cost allowance projects **$15.12 for the selected 210,000 IDs** or **$44.66 for all 660,609 nonempty IDs**, including the final current commitment and stage allowance. Full-source headroom is only **$3.34 under the $48 operating ceiling**. The additional 10% is a separate stress assumption; the observed failed attempt is already included in the base. This is cost evidence only, with no inspection of sealed labels and no new accuracy claim.

GLM's four-worker first pass completed the same 200 IDs in 41.38 seconds, versus 71.43 seconds with one worker: **1.726× observed speedup**, with zero failures. Verification and fallback remain serial in the current implementation. An illustrative full-source schedule with those serial proxies is roughly 31 hours, so budget fit does not establish deadline fit.

Storage also needs a measured gate. The published application uses 1,490,944 bytes for the 1,000-review pilot. Simple linear projection gives about 313 MB for 210,000 reviews, but about 985 MB for all 660,609 nonempty reviews—above the conservative 700 MB threshold. Fixed database overhead makes this projection imperfect; measure it at 10,000 before claiming full-source free-hosting feasibility.

Retain 210,000 successful selected classifications as the planned operational target until the 10,000-review checkpoint establishes sustained throughput and quality. Full-source classification is a possible extension, conditional on the measured deadline and budget. Never equate ingestion of all rows with classification of all rows.

## Implemented safeguards and remaining gates

Implemented changes include shared initial/fallback/verifier classification audits; preserved raw flags and deterministic reasons; Retry-After handling without truncating provider waits; zero-charge settlement for cancellation before dispatch; frozen model experiments; strict human worksheet provenance checks; and a versioned aggregate-only evaluation API/dashboard. The 1,000-review labels, memberships, ranking and memo remain unchanged.

The [scaling audit](scaling-performance-audit-v6.md) found that normal call logs already append efficiently. Repeated budget-ledger sums, per-record transactions, memory-heavy finalization, and serial downstream stages deserve measurement before expansion. It provides benchmarks and intervention thresholds; no untested full-scale performance claim is made.

Next gates:

1. Complete the blind annotations and score the sealed candidate predictions by the two named cohorts.
2. Inspect paired wins and regressions, especially severe complaints, cancellation, ambiguity and unflagged errors.
3. Freeze the selected routed configuration and record every route/skip reason. Measure fallback correction and regression, not merely increased agreement.
4. Run the 10,000-review checkpoint with sustained concurrency, source/accounting reconciliation, realistic downstream stages, recovery and memory checks.
5. Expand only if those results support the remaining budget and deadline. Keep unresolved records explicit and recommendations provisional wherever the quality evidence remains inadequate.
