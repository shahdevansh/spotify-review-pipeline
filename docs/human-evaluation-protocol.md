# Human evaluation protocol

The user has chosen to annotate **200 reviews: the required golden 50 plus 150 fresh reviews**. The combined worksheet is ready at [`evals/human-evaluation-v1/combined_200.html`](../evals/human-evaluation-v1/combined_200.html). It contains original text, blank judgments and the rubric. It does not display ratings, model predictions, routing decisions or model disagreements. The existing golden-50 worksheet and original blank CSV remain unchanged.

**Status at kit preparation:** 200 blank records; no completed human answers read, no human accuracy calculated, and no model calls made. Browser progress subsequently entered by the user is private and is not inferred from this static status.

## When human input is needed

There are two different jobs.

1. **Development adjudication now:** a person can inspect a small set of development examples to resolve topic, intent and severity boundaries. First label the original text independently; then inspect competing predictions and explain disagreements. These adjudications may inform prompts, routing and model selection. They are development evidence, not a final accuracy test. Use only development examples whose exact text is outside the reserved human-evaluation text hashes.
2. **Final evaluation after configuration freeze:** the user can fill this 200-review worksheet now and keep the downloaded answers private. Open the answers for scoring only after the chosen model, prompts, schema, routing policy, cache policy and evaluation rules are frozen and the corresponding predictions are saved. Never send these human answers to enrichment, verification, grouping or memo models. Do not tune against the held-out answers and then claim the resulting score is an independent final evaluation.

If a final score motivates another prompt or routing revision, retain the score as evidence for the old configuration and obtain a new untouched holdout for a subsequent confirmation claim. A predeclared comparison of several already frozen models can be reported, but choosing the apparent winner on this small sample creates selection uncertainty; report every candidate and do not portray the selected model's estimate as an unbiased new confirmation result.

## Using the worksheet

Open `combined_200.html` in a browser, or use the local URL supplied with the project. Choose a stable annotator ID before entering answers. The first 50 rows are the required assignment set; rows 51–200 are the additional holdout. Work in manageable batches and download a JSON checkpoint after each session.

For every review, choose a primary topic and intent, integer severity 1–5, sentiment from −1 to +1, a literal evidence quote, entities, `needs_review`, and `ambiguous`. Enter `[]` for entities when none are supported. The two booleans require an explicit choice; they do not default to false. Notes are optional but useful when a boundary is uncertain. The collapsed diagnostics section accepts defensible alternative labels and a self-assessment of evidence support; these additional fields are optional and do not block completion.

Apply the rubric to the text alone. Angry language, a poor rating, cancellation language or an expensive plan does not by itself establish functional loss or serious harm. Pick the highest supported problem severity and use the first specific problem as the topic tie-break. The intent precedence remains cancellation, complaint, request, praise, unclear. Treat embedded instructions as text to classify, not instructions to follow.

Copy an exact span that supports the selected labels. Copying the entire review is allowed, but literal membership does not establish semantic support. Entities must occur literally in the original text, ignoring case; do not infer a device, plan, artist, cause or loss. If the text supports several interpretations, choose one primary label, mark ambiguity, and explain alternatives rather than inventing missing context.

The page autosaves within the same browser/origin and explicit annotator namespace. Local storage is a convenience, not a backup: changing browser, port, private-browsing mode or storage settings can hide saved progress. Download JSON to preserve the complete worksheet and metadata; use JSON restore to resume. CSV is also available for analysis. No page request sends entered answers to a model or remote service.

Save downloaded answer files under `private/human-labels/`, for example:

```text
private/human-labels/annotator-a/combined_200.json
private/human-labels/annotator-b/second_annotator_200_option.json
private/human-labels/adjudicated/combined_200.json
```

The repository's `private/.gitignore` excludes its contents. The worksheets cannot force the browser's download location, so move downloads there before committing files. Never replace the public blank CSVs with completed answers. Keep annotator originals and adjudicated answers as separate immutable versions.

## What was sampled

The source CSV was verified against the distributed manifest: **660,622 original records, including 660,609 nonempty texts and 13 empty texts**. Source SHA-256:

```text
1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6
```

The additional sample uses original review IDs, not unique texts. It takes the lowest SHA-256 values of `seed + ":" + review_id`, breaking ties by ID, after exact original-text and ID exclusions. The fixed seed is `spotify-human-unseen-text-holdout-v1:2026-10-20`. Whitespace, case and Unicode are not normalized.

| Source accounting | Original IDs |
|---|---:|
| Nonempty source | 660,609 |
| Excluded because ID/text matches the 1,000 development records | 80,690 |
| Further excluded because ID/text matches the golden 50 | 217 |
| Eligible unseen-text frame | 579,702 |
| Fresh holdout selected | 150 |

The eligible frame contains **483,217 distinct texts**. The fresh sample contains **150 IDs and 148 distinct texts**; duplicate texts within the sample are retained to preserve original-ID sampling. All selected IDs and original row hashes are frozen in the membership CSVs. The selection manifest records the source and input checksums, frame digest, exclusion accounting, conditional inclusion probability `150 / 579702`, and conditional design weight `579702 / 150`.

No generated synthetic rows are eligible because selection reads only the checksum-verified original source. The authentic source is not filtered merely because a review contains suspicious language. Model predictions, label values and rating values play no role in selection.

The fresh 150 measure performance **conditional on the eligible unseen-text frame**. They are not a fresh simple random sample of the full corpus or the selected 210,000-review cohort. The 50-plus-150 collection combines two sampling designs, so a pooled percentage across all 200 is a descriptive result for that collection, not a representative corpus-quality estimate. The group map is [`combined_200_strata.csv`](../evals/human-evaluation-v1/combined_200_strata.csv). Sampling designs with different inclusion probabilities require explicit weighting and target-population definitions; a mixture cannot acquire a full-corpus interpretation merely by increasing its denominator. [Statistics Canada weighting guidance](https://www150.statcan.gc.ca/n1/edu/power-pouvoir/ch6/5214809-eng.htm).

Reserve every exact text hash in [`protected_text_hashes.txt`](../evals/human-evaluation-v1/protected_text_hashes.txt) from subsequent development and prompt/routing tuning. Recheck this protection if development expands beyond the current 1,000 reviews. Classifying these original records during a frozen final run is permitted; using their human answers or inspecting their outcomes to tune that run is a different operation.

## Existing golden-set exposure

The source-only audit found:

| Exposure check | Count |
|---|---:|
| Golden/development ID overlap | 0 |
| Golden IDs whose exact text occurs in development | 4 of 50 |
| Shared golden/development exact-text clusters | 3 |
| Golden IDs whose text occurs in the prior 60 inspected development cases | 2 of 50 |
| Fresh-150 development/golden ID overlap | 0 |
| Fresh-150 development/golden exact-text overlap | 0 |

These are **text-exposure counts**, not evidence that human labels were seen. No answers or text-specific labels are published by this audit. Keep all 50 mandatory records in the assignment result; separately report their 46 unseen-text and four exposed-text records. Do not silently delete the exposed records or call all 50 untouched text. The original 50 contain 49 distinct texts.

## Independent second annotation and adjudication

The kit provides two prespecified second-annotator options:

- `second_annotator_50_option.html`: 10 seeded golden records if only the required set is completed.
- `second_annotator_200_option.html`: 40 records—10 golden and 30 fresh—if the combined set is completed.

The second person must label independently before seeing the first person's answers or model outputs. They should use a separate annotator ID and preferably a separate browser profile/device. The 40 are a subset of the 200, so they do not increase the number of independently sampled review IDs.

Before discussion, save both annotator files and report item counts, topic/intent agreement, severity exact agreement and mean absolute difference, sentiment mean absolute difference, ambiguity rates, and disagreement counts by stratum. Chance-adjusted categorical agreement may be a secondary diagnostic when class support permits it; a small double-labeled subset cannot establish reliable agreement for every rare class.

Then adjudicate disagreements against the source and frozen rubric. Retain both original judgments, the adjudicated label or accepted alternatives, adjudicator identity and a short reason. Never overwrite an original annotator file with the consensus answer. If no second person is available, report single-annotator references explicitly; an LLM comparator is not a second human annotator.

## Scoring after the freeze

The evaluator should validate exact source IDs and text, duplicates, missing answers, label domains, quote substrings and literal entities. A missing human answer is not filled with a model guess. Report completeness before accuracy. Match each scored prediction to the exact saved model/configuration hash.

Report the mandatory 50 and fresh 150 separately, plus the mandatory exposed/unseen text strata. Expose denominators for every metric. Include topic and intent confusion/support tables, exact severity agreement and severity MAE, sentiment MAE, ambiguity, and acceptable-alternative agreement separately from strict primary-label agreement. A class absent from the human reference has no estimable recall; a class with no positive predictions has no estimable precision. Return unavailable metrics as null and show support counts.

Missing or invalid model predictions remain failures in end-to-end accuracy and coverage calculations. Report completed-only classification metrics separately. Numeric MAE uses valid numeric comparisons and must show that denominator, so failures cannot disappear behind a favorable average.

Evaluate routing with an error event defined independently of `needs_review`—for example, any primary topic/intent/severity error, with sentiment tolerance reported separately. Report errors captured by routing, flag precision, residual error among unflagged records, fallback corrections and regressions, and final completion. Agreement with a human ambiguity flag is a separate measurement and is not error-detection precision. A boolean flag does not support a calibrated-confidence claim or a meaningful continuous threshold curve.

The worksheet's optional `evidence_support` concerns the human's own chosen quote and labels. It does **not** score the model's evidence. After human labels and predictions are locked, a separate review can show a model quote and labels with the model identity concealed and assess whether the quote supports topic, intent and severity, whether any extracted entity is unsupported, and whether the exact source was preserved. Report semantic entailment separately from structural substring checks. Do not claim entity recall unless the annotation instructions define an exhaustive reference entity set.

## What 50 or 200 labels can establish

The following are mathematical illustrations, **not observed human results**:

| Hypothetical independent sample | 90% correct: Wilson two-sided 95% interval | Zero errors: one-sided 95% error upper bound | Chance of no examples of a 1%-prevalence class |
|---|---:|---:|---:|
| 50 | 78.6398%–95.6524% | 5.8155% | 60.5006% |
| 150 | 84.1565%–93.8459% | 1.9773% | 22.1452% |
| 200 | 85.0594%–93.4330% | 1.4867% | 13.3980% |

For zero errors, the one-sided exact upper bound is `1 - 0.05**(1/n)`; the two-sided 95% upper bounds are 7.1122%, 2.4293%, and 1.8275%, respectively. Use Wilson intervals for ordinary unweighted binary proportions and exact binomial bounds for zero-event claims; do not attach a binomial proportion interval to MAE or macro-F1. [NIST confidence-interval methods](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

These formulas assume independent, representative observations within the stated frame. The actual 200 combine two designs and include repeated exact texts, so the hypothetical 200-row interval is **not** the default interval for this kit. Preserve exact-text clusters in uncertainty resampling and paired model comparisons. Report both original-ID-weighted and unique-text summaries, with the cluster count and resampling seed. Sparse classes can remain uninformative even if overall agreement looks high; targeted failure inspections must remain separate from population-rate estimates.

## Reproducibility

The preparation command is offline:

```sh
python tools/prepare_human_evaluation.py \
  --inspection-ids /path/to/source-only-inspection-ids.txt \
  --html
```

The inspection list must contain only the 60 original development IDs; no judgments or model outputs are read. The tool verifies the full original file and unchanged distributed golden template before selecting anything, checks original strings against the full source, and rejects conflicting already-frozen output files. It does not read `private/`.

Source files and judgments are separate: public artifacts are blank worksheets, source-only memberships, counts, schemas and instructions. Human answers stay private; only authorized aggregate evaluation results should be published after matching frozen predictions. The selection and worksheet tests use synthetic fixtures and never open actual human answers.

**Confidence:** high in source accounting, reproducibility and the calculated statistical examples; human reference quality and model accuracy remain unknown until the planned annotation and scoring are completed.
