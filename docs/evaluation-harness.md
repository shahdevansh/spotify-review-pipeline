# Offline comparison of frozen candidates

`spotify_pipeline.harness` compares saved predictions against the same original review IDs. It makes no provider calls, reads no implicit reference file, and does not change the frozen v5 pilot, select a winner, or authorize expansion.

Use model agreement to find disagreements and test sensitivity. Human accuracy requires independently supplied human labels and an explicit provenance attestation. Matching another model, or producing a stable issue ranking, does not establish correctness.

## Run without reference labels

Install the project, then run:

```sh
python -m spotify_pipeline.harness \
  --sources matched_input.csv \
  --candidate baseline=baseline/records.jsonl \
  --candidate candidate=candidate/records.jsonl \
  --baseline-candidate baseline \
  --bootstrap-repetitions 1000 \
  --seed 1729 \
  --out comparison/report.json
```

These are example paths. Use the exact input and output files recorded in the experiment manifest. The two candidates may represent different models, prompts, or repeats with different request orders; their prediction files must refer to the same source cohort. Candidate ordering and record ordering do not affect metric calculations. File-byte provenance hashes still change when file contents or ordering change; a worksheet's ordered source digest must remain valid.

When `--reference-kind none` (the default), output contains pairwise agreement and ranking sensitivity. It contains no human accuracy or human error-capture estimates.

The module returns exit code `0` when every candidate supplies a valid completed prediction for every expected ID, or `2` when coverage is incomplete. Invalid source identity, duplicated/foreign IDs, mixed configurations, malformed reference labels, or disallowed split overlap raise errors. An existing output file is never overwritten.

## Input contract

Source records retain all six original string fields: `review_id`, `review_text`, `review_rating`, `review_likes`, `app_version`, and `review_timestamp`. Empty text is outside the classification evaluation cohort; keep its quarantine accounting separately. Every source ID must be unique.

Predictions can be flat records or envelopes containing a `prediction` object. Each record requires:

- `review_id`, plus the original `source_sha256` or exact `review_text`. Every supplied original field is checked against the source. Nested predictions cannot change an identity field or contradict outer status/configuration metadata.
- Valid `topic`, `intent`, integer `severity`, finite `sentiment`, and boolean `needs_review`. The existing strict classification schema supplies allowed values.
- One frozen `label_config` across the candidate. Alternatively, supply `--candidate-metadata metadata.json`, containing `{"candidate_name":{"config_id":"frozen-configuration-identity"}}`. Declared and per-row identities must agree.

Explicit statuses other than `completed` are failures. A missing status is permitted for compact saved predictions. Invalid labels make the whole record invalid; fields from a partially invalid record do not quietly enter other metrics.

Quotes and entities are optional for compact comparison inputs. When present, quotes must be exact substrings and entities must occur in the original text under case-insensitive matching. These are mechanical checks, not semantic evidence-support judgments.

The engine's `raw_needs_review` and the legacy `raw_model_needs_review` are accepted as aliases for an observed raw model flag. Both must be actual booleans; conflicting values invalidate the record. The report uses the canonical name `raw_model_needs_review` internally without rewriting the source artifact. `needs_review` remains the final, audited flag. No flag is described as calibrated confidence.

Accepted file formats are CSV, JSON lists, JSON objects containing `records` or `labels`, JSONL, and gzip-compressed JSONL. CSV boolean cells use `true`/`false`, severity uses an integer, and list-valued fields use JSON arrays.

## Human or AI references

An AI comparator is explicit:

```sh
python -m spotify_pipeline.harness \
  --sources matched_input.csv \
  --candidate candidate=candidate/records.jsonl \
  --reference independent_ai_labels.jsonl \
  --reference-kind ai \
  --out comparison/ai-reference.json
```

Human evaluation additionally requires `--reference-kind human --human-labels-confirmed`. The attestation is a caller assertion of provenance, not a mechanism for proving who wrote the labels. Never point the harness at a blind answer file during tuning. The module does not search for golden files or automatically load them.

References may cover only a subset of expected source IDs. Unlabeled IDs are listed and excluded from reference metrics; missing candidate predictions for labeled IDs remain in binary metric denominators. Malformed supplied reference labels are rejected instead of being silently discarded.

The blind worksheet's JSON and CSV exports are supported directly. Its optional `row_sha` is validated as an alias of the canonical source-row hash. Supplied cohort, rubric, worksheet, source-digest, and seed fields must remain consistent across CSV rows and any JSON wrapper. A wrapper annotator must match every row's `human_labeler`; provided incomplete status or validation errors are rejected. The worksheet's source digest is recomputed over its ordered original ID/text/optional-row-hash records. Reference provenance and labeler counts are retained. A supplied rubric digest is format-checked and preserved, but is not claimed to be independently verified against a rubric file that was never supplied. Wrapper metadata never replaces explicit human-label attestation.

Primary labels determine the ordinary confusion matrices and primary-label accuracy. Optional `alternative_topics`, `alternative_intents`, and `alternative_severities` extend the primary label into an explicitly accepted set. Legacy `accepted_topic`, `accepted_intent`, and `accepted_severity` arrays are also supported and must include the primary label. If both conventions occur, their sets must agree. Invalid or repeated values are rejected.

`acceptable_set_reference_metrics` reports membership in these accepted sets and severity distance to the nearest accepted value. It does not replace primary-label metrics or invent a single-class confusion matrix for multiple acceptable labels. Human routing is likewise reported separately against primary-label errors and acceptable-set errors.

`ambiguous` remains a human annotation, distinct from the model's review flag. `evidence_support` is the annotator's assessment of their own quote and labels (`supported`, `partial`, `unsupported`, or `unclear`); its counts are not a model-evidence correctness score. A semantic audit of model quotes and entities requires a separate annotation exercise.

## Split exposure and the human evaluation groups

Supply `--split-rows split_manifest.jsonl` to check prior source exposure. Each external row must contain the original six fields and an explicit nonempty `split`, such as `development` or `qualitative_inspection`. Evaluation sources are assigned `--evaluation-split evaluation` by default. Missing split tags are errors.

The audit checks cross-split IDs and exact, unnormalized review text. It distinguishes source exposure from label-answer leakage, which it cannot determine. It does not detect paraphrases or semantic near-duplicates. No supplied split manifest means `not_checked`, not `passed`.

The default `--leakage-policy error` rejects overlap. For an existing mandatory holdout with documented prior source overlap, `--leakage-policy report` retains every supplied reference ID and adds exposed-text and unseen-text strata. Do not silently replace mandatory records to obtain cleaner metrics.

The current human evaluation design is:

| Group | Original IDs | Interpretation |
|---|---:|---|
| Mandatory golden set | 50 | Report all mandatory labels |
| Mandatory, unseen exact text | 46 | Subset without exact-text exposure in the development sample |
| Mandatory, exposed exact text | 4 | Separate sensitivity stratum; three shared text clusters |
| Optional fresh holdout | 150 | Conditional sampling frame excluding development and golden IDs/texts |

The optional holdout contains 148 distinct texts. Its source selection manifest and the source-only group mapping are generated under `evals/human-evaluation-v1/`; these artifacts contain no completed human answers. The mapping file `combined_200_strata.csv` identifies `mandatory_golden_50` and `fresh_text_disjoint_150`.

Pass a JSON group mapping with `--evaluation-groups groups.json`:

```json
{
  "mandatory_golden_50": ["golden-review-id"],
  "fresh_text_disjoint_150": ["fresh-review-id"]
}
```

The IDs above illustrate the format, not the actual cohort. Group membership must be nonempty, disjoint, unique, and contained in the supplied source cohort. Ungrouped source IDs are explicit. Each group's labeled count, valid predictions, metrics, cluster intervals, and exposed/unseen reference strata are reported separately. A pooled unweighted result describes the supplied records; it is not an estimate for the full corpus because these groups have different selection designs.

## Metric denominators

| Metric | Denominator and failure policy |
|---|---|
| Topic/intent accuracy or agreement | All referenced original IDs; missing or invalid prediction is incorrect |
| Confusion and class support | All referenced IDs; failures use `__missing_or_invalid__` |
| Severity exact / within one | All referenced IDs; failures are incorrect |
| Severity and sentiment mean absolute difference | Only valid predictions with reference labels; explicit numeric denominator |
| Pairwise candidate agreement | IDs with valid predictions from both candidates; excluded IDs are listed |
| Matched reference metrics and issue ranking | Intersection of valid IDs across every supplied candidate |
| Paired binary differences from baseline | All referenced IDs, with missing predictions counted incorrect |
| Paired numeric differences from baseline | The same pairwise common valid/reference IDs on both sides |

Topic and intent include per-class reference support, predicted support, precision, recall, and F1. `macro_f1_present_labels` averages classes with any reference or predicted support. `macro_f1_all_taxonomy_labels` includes every allowed class, assigning zero to absent classes. Undefined precision/recall/F1 values are `null`, with supports available to interpret them.

Human routing defines an error as any topic, intent, or severity mismatch; it does not use the review flag itself as truth. Sentiment differences remain separate. Reports show flag precision, captured errors, and the fraction of errors captured by either a flag or a missing/invalid result that requires review. Raw-model routing is restricted to valid human-referenced predictions with an observed raw flag; excluded IDs are explicit.

Risk/coverage uses three discrete policies: accept none, accept only unflagged valid predictions, and accept every valid prediction. Coverage divides accepted IDs by all human-referenced IDs. Risk divides incorrect accepted predictions by accepted predictions. Zero accepted predictions give `null` risk, not zero risk. A boolean flag does not support a continuous confidence curve or AUROC.

## Uncertainty and ranking

Binary metrics include 95% Wilson intervals with their numerator and denominator. These are IID diagnostics. When exact texts repeat, interpret dependence through the supplied exact-text cluster resampling. Use its confidence bounds only when that metric's `reportable` flag is true; an empirical resampling range is not a substitute when bounds are suppressed.

Cluster bootstrap draws the observed number of exact-text clusters with replacement and retains every original review ID in a selected cluster. Thus point estimates remain weighted by original reviews, including duplicate-text multiplicity. A fixed seed and sorted clusters make resampling reproducible. Percentile bounds use linear interpolation at `(B - 1) × quantile`.

Reference and pairwise cluster intervals cover topic match, intent match, severity exact match, severity mean absolute difference, and sentiment mean absolute difference. Paired candidate differences use the same cluster draw on both sides. Numeric differences filter each draw to pairwise common valid IDs, retaining resampled multiplicities; disjoint coverage yields `null`, not an average of different records.

Each metric records its eligible original-ID count and **contributing exact-text cluster count**. Binary metrics include failed predictions in their denominators. Numeric metrics use only valid predictions, and paired numeric metrics use only jointly valid predictions. A large reference cohort cannot supply uncertainty information for a numeric metric supported by only one text cluster.

The harness suppresses confidence bounds (`lower`/`upper` are `null`) when fewer than two clusters contribute, fewer than **100 requested or defined resamples** are available, or all defined resamples give the same value. This is a minimum reporting safeguard, not a guarantee of reliable coverage; the default remains 1,000 repetitions. Low-repetition runs remain available for diagnostic tests. Every metric includes `interval_status`, `reportable`, valid/undefined/skipped repetition counts, and relevant warnings.

`empirical_percentile_range` and `bootstrap_mean` preserve descriptive resampling results, explicitly marked noninferential. Thus all-correct samples may have empirical range `[1,1]`, and identical candidates may have empirical difference `[0,0]`, while their confidence bounds remain suppressed. Neither proves perfect population accuracy, zero error, or population equivalence. Zero-event binomial bounds require an independently justified sampling unit and estimand; substituting the distinct-text count into an original-ID-weighted binomial formula is not automatic.

The generic Python `cluster_bootstrap` helper accepts optional `contributing_ids`, mapping a statistic's name to its eligible original IDs. Restricted-denominator statistics must supply this mapping; otherwise all input IDs are assumed eligible. Harness-owned numeric metrics supply it explicitly, including within evaluation groups and paired differences.

These intervals do not account for incorrect reference labels, tuning on an evaluated set, multiple candidate selection, or a nonrepresentative sampling frame. A narrow interval is not evidence of correctness.

Issue scores are exact severity sums for complaint/cancellation records. Ranking uses descending score and ascending issue ID to resolve ties. Each original review retains its weight even when text repeats. Displayed rankings and top-three overlap use active topics only; the Spearman comparison includes all eight topics, assigning zero scores to absent topics and midranks to ties.

Ranking comparisons include top issue agreement, top-three Jaccard overlap, rank correlation, and score differences. Cluster resampling reports the fraction of resamples retaining a candidate's original top issue or agreeing with another candidate's top issue. These are ranking sensitivity measures, not ranking accuracy, confidence intervals on correctness, or estimates of causal product impact.

## Python API and JSON publication contract

```python
from spotify_pipeline.harness import evaluate_candidates

report = evaluate_candidates(
    sources=source_rows_or_path,
    candidates={"baseline": saved_baseline_rows, "candidate": saved_candidate_rows},
    reference_kind="none",
    baseline_candidate="baseline",
    bootstrap_repetitions=1000,
    seed=1729,
)
```

Optional arguments are `references`, `reference_kind`, `human_labels_confirmed`, `candidate_metadata`, `split_rows`, `evaluation_split`, `leakage_policy`, and `evaluation_groups`. Inputs can be paths or already loaded rows. Returned values are JSON-serializable and deterministic for fixed inputs/settings.

| JSON key | Meaning |
|---|---|
| `harness_version`, `offline`, `status` | Report implementation identity and coverage/split status |
| `cohort` | Expected IDs, distinct texts, ID hash, canonical source-row hash |
| `reference` | Explicit kind, attestation, labeled/unlabeled counts, source-bound label hash, ambiguity/self-assessment counts |
| `split_audit` | Exact-ID/text exposure, unseen/exposed evaluation IDs, limits |
| `candidates[name]` | Frozen config identity, raw input digest, strict coverage, flags, and optional reference/routing metrics |
| `pairwise_agreement` | Per-pair matched denominator, exclusions, agreement, and cluster intervals |
| `matched_comparison` | All-candidate valid intersection and its referenced subset |
| `evaluation_groups` | Separate named cohort accounting and metrics |
| `ranking_sensitivity` | Matched-cohort scores, comparisons, and resampled top-issue stability |
| `paired_reference_differences` | Candidate-minus-baseline metrics with binary/numeric cohort identities |

A public interface must preserve `reference.kind`, `human_accuracy_available`, coverage exclusions, and the explicit `not_accuracy` ranking marker. `complete` means structural prediction coverage, not a quality or expansion gate. With no references, `labeled_count` is zero and `human_accuracy_available` is false; no human accuracy should be inferred from pairwise agreement.

Regression tests in `tests/test_harness.py` use synthetic fixtures only. They cover known Wilson values, missing/invalid denominators, source identity, configuration isolation, split exposure, duplicate clusters, paired numeric cohorts, acceptable labels, raw/audited flags, named groups, ranking multiplicity/ties, and offline CLI behavior.
