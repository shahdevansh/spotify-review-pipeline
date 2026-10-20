# Candidate v6: mechanisms, interpretations, and comparison limits

Status: a development experiment, not a demonstrated quality improvement. No human golden labels were read for this audit or prompt revision. The original `prompts/labels.md`, v5 configuration, calls, predictions, and measurements remain unchanged.

## Observations from the 1,000 development records

The final v5 classifications and independent verifier disagree on topic for 172 records, intent for 94, and severity for 162. These are disagreement counts, not error counts or accuracy. The verifier is also fallible.

One trace establishes a semantic failure without relying on the verifier as truth: review `0b626430-7bf8-4ae4-9a44-f6ffc4324424`, “Love it 💕”, received `other/cancellation/2`, sentiment `-1`. It appears as `r11` in a 25-review first-pass batch in `runs/pilot/500`; the next review, `r12`, explicitly discusses uninstalling. The original request, response, and saved alias mapping agree. This is consistent with cross-review contamination, but adjacency alone does not prove its cause. The new experiment must distinguish a model error from sensitivity to batch size, order, and neighboring text.

## Proposed prompt mechanisms

`prompts/labels-v6.md` keeps the assignment's eight topics, intent precedence, and five severity levels. It makes the following decisions explicit:

- Match each output ID back to that review's text and avoid borrowing a neighboring review's intent or impact.
- Treat a reported failure followed by “please fix” as a complaint; distinguish it from a pure desired addition.
- Choose the highest-severity supported problem, then use that same problem's topic.
- Separate strong language from functional impact, and partial/intermittent disruption from a clearly blocked core task.
- Avoid topic inference from broad words such as “update”, “Premium”, or “developer” alone.
- Distinguish absent specificity from unintelligible text. Clear brief praise or generic criticism needs no invented defect.

The examples are synthetic. They are not prevalence evidence, held-out evaluation, or replacements for human labeling.

## Interpretations that require disclosure

Two cases are not completely resolved by the assignment's short rubric:

1. **Uninstall/reinstall for troubleshooting.** The contract explicitly lists uninstalling under cancellation; a literal reading could include temporary removal solely to reinstall. V6 instead asks the model to consider the stated purpose and flag an unresolved distinction. We must report this interpretation and inspect both outcomes; it is not an instructor-confirmed rule.
2. **Workaround and task scope.** V5 broadly suggested that an alternate connection or workaround lowers severity to 3. V6 distinguishes a workaround restoring the affected task from another device/platform merely continuing to work. The contract does not define every device/mode scope, so unresolved cases must be flagged and reported rather than silently adjudicated.

Other narrow boundaries—missing one catalog item, a playlist failing to load, restricted seeking, and an interrupted but partly functioning playback session—remain contextual applications of severity 2/3/4. No lookup table should overwrite the model's supported judgment merely to increase inter-model agreement.

## Shared audit and accounting repairs

All new comparison arms use `classification_audit_policy: shared-classification-audit-v1`, independently of their prompt/model choice. The implementation version and injection pattern participate in the cache fingerprint.

`raw_needs_review` preserves the model's own flag. The final `needs_review` combines that flag with deterministic inconsistency and suspicious-instruction checks. `review_reasons` and `review_audit` describe additions and retained concerns. The audit does not change topic, intent, severity, or sentiment. It applies to primary classification, bounded fallback, and verification. A fallback can resolve an initial ambiguity or consistency issue, but it cannot erase an already detected suspicious-instruction flag.

The accounting repairs distinguish cancellation before dispatch from cancellation after a request starts. A pre-dispatch cancellation records `outcome: failed`, `dispatch_status: not_dispatched`, `usage_source: not_dispatched`, zero usage/cost, and no uncertain charge. An in-flight cancellation retains the unknown-charge reservation. Historical holds are unchanged. Numeric and HTTP-date `Retry-After` values now govern the minimum retry delay instead of being truncated to 30 seconds.

## Matched experimental design

Use the same seeded 200 original development IDs, original text, batch size 10, order, one worker, and no fallback for all primary arms:

1. Lightning with the v5 prompt.
2. Lightning with the v6 prompt.
3. GPT-OSS 120B low reasoning with v6.
4. GLM 5.3 Flash low reasoning with v6.
5. Qwen 235B Instruct without thinking controls, with v6.

The first two arms isolate a prompt effect under the new common audit. The latter three compare models under v6; they do not identify model/prompt interactions because the stronger models have no v5-prompt arm. If a strong-model result changes the recommendation, a bounded old-prompt run on that same model would help separate the causes.

Freeze the manifest, exact requests, model IDs, reasoning controls, batch/output limits, and rates before calls. Use fresh result/task caches per arm and the shared spend ledger. Save raw provider judgments alongside audited flags. Do not select a winner by agreement with one comparator alone.

On a separate 25-text development stress set, use singleton, batch-10, and batch-25 requests; rotate/shuffle order and repeat a fixed condition without cached reuse. Keep the sampled IDs and permutations saved. Report per-review and per-position label flips, exact-ID/duplicate/missing failures, truncation, retry cost, latency, and raw/audited flag coverage. Include deliberately adjacent contradictory synthetic reviews and injected-instruction cases, tagged synthetic and excluded from business metrics.

The schema and ID validator can establish exact coverage, but cannot establish that a semantically valid label belongs to its intended text. Full-text evidence quotes and regex-matched entities establish source provenance, not label entailment. Evaluate entailment separately on blinded sampled disagreements, preserving ambiguous alternatives.

The current HTTP timeout is a 60-second provider default, not a total wall-clock deadline; output estimation assumes 160 visible tokens per record without a separate reasoning allowance. These remain harness limitations. Keep controls fixed, measure truncation explicitly, and treat any changed cap, split/retry policy, or deadline as a separately identified experiment.
