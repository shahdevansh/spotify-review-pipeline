# Dashboard and evaluation audit — v6 design

**Decision: keep the published v5 dashboard as a provisional learning artifact. It is not evidence that the product priority or model accuracy has been established. Build the Evaluation tab around a versioned harness report before comparing or promoting another configuration.**

Confidence is **high** in the API reconciliation, saved metric definitions, and issues below; **unknown** in human-label accuracy. This audit used unauthenticated public API reads, source inspection, offline recomputation, and a read-only SQLite ledger connection. It made no model calls, deployment changes, or database writes. No frontend changes were prepared.

The live capture began **2026-10-20 07:31:30 UTC**. The local ledger snapshot was read at **07:33:08 UTC**. The published run remains `1000-1ad0e35d239c3e9d`, configuration `spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb`. “v6” in this document names the next audit/harness design; it does not claim a completed v6 model run.

## Evidence and verified facts

The [public dashboard](https://spotify-review-observatory.vercel.app) returned HTTP 200 for overview, issues, recommendations, and the first page of the highest-ranked issue. The [saved audit capture](../validation/dashboard_evaluation_audit_v6.json) contains the responses, exact source hashes, ledger comparison, and recomputed rankings. The earlier [complete publication reconciliation](../validation/pilot_publication.json) checked every stored source record and issue membership; this audit did not repeat all pagination requests.

| Claim | Result |
|---|---|
| Published run/configuration/settings match the saved v5 run | Verified |
| Principal pilot contains 1,000 original review IDs / 926 distinct texts | Verified |
| 74 duplicates within this cohort vs. 549 saved results reused across processing | Correctly distinguished by the current UI |
| Incremental pilot nominal API value | `$0.096661512`; matches saved run |
| Configured providers and models | Correct: Nebius hosts Lightning enrichment, GPT-OSS fallback/verification/grouping, and GLM-5.3-Flash memo |
| Human benchmark | Pending; blank worksheet has 50 rows and zero complete human label rows |
| Human accuracy warning | Present and correct |
| Qualitative quality hold | Present, but hardcoded to this one run ID |
| Ranking arithmetic | Recomputes exactly from final saved model labels |
| Semantic reliability of ranking/memo | Not established; inspected label problems can alter the priority |
| Source, hash, quote, and literal-entity integrity | All 1,000 pass; this does not establish semantic label support |

The current source explicitly distinguishes model judgments from human evaluation and warns that shared fallback/verifier models can have correlated errors. Preserve those improvements. The remaining problems concern missing decision evidence, ambiguous definitions, and how another run would inherit or lose the warnings.

## Prioritized changes

### P1 — Make the quality decision a persisted harness output

**Quick-reader risk:** “1,000 classified / 100% processed” and a complete recommendation can look like a completed quality gate. The current orange warning mitigates this for v5, but [`page.tsx:327`](../web/src/app/page.tsx#L327) identifies the reviewed pilot by a literal run ID. Another published run would lose that warning even if its quality were unknown or its inspection decision were also hold.

**Evidence:** the current [inspection report](../evals/pilot_inspection_report.json) says `hold_expansion_for_focused_repair_and_remeasurement`. Its random 30 contain 7 concerns, 8 ambiguous cases, and 15 supported cases; six concerns are unflagged. The separate targeted 30 contain 23 concerns, 3 ambiguous cases, and 4 supported cases. These are AI-assisted development judgments, not human accuracy estimates.

**Change:** publish `processing_status`, `quality_gate.status`, `human_evaluation.status`, and `recommendation_status` separately. A transported API response of `status: ready` must never imply quality passed. Render the gate and its reasons beside the run summary and again above recommendations. For a new configuration with no matched evaluation, show **“Quality not evaluated; recommendations provisional.”**

**Acceptance:** a fixture with complete processing and failed/unknown quality never receives a quality-success badge; changing the run ID does not remove a persisted hold. The gate must reference the exact evaluated run/configuration and artifact hashes.

### P1 — Expose ranking sensitivity and qualify model-assigned severity

**Quick-reader risk:** “Priority ranking,” “total reported severity,” and exact claim links can imply that the ranking is an established product priority. Severity is assigned by models; the source reviewer did not supply the assignment’s severity scale. Exact arithmetic does not validate the classifications.

**Recomputation on the same 1,000 original IDs:**

| Topic | Final-label severity sum / rank | Blind-verifier severity sum / rank |
|---|---:|---:|
| Usability | 291 / 1 | 234 / 3 |
| Billing | 239 / 2 | 221 / 4 |
| Other | 233 / 3 | 309 / 2 |
| Playback | 204 / 4 | 319 / 1 |

This is a **model-judgment sensitivity comparison, not a corrected ranking or a confidence interval**. The verifier also makes errors. Nevertheless, the top priority changes when another saved prediction set is used with the identical aggregation rule. The full recomputation is in the audit capture.

The [memo inspection](../evals/pilot_inspection_report.json) identifies concrete contamination: examples assigned to usability describe crashes/no sound/audio quality, while some Premium-linked selection restrictions are assigned outside billing. The numerical memo traces are valid conditional on those labels.

**Change:** use **“Provisional ranking from final model labels”** and **“Score = sum of model-assigned severity.”** Add a small rank-sensitivity panel, with explicit source-prediction set, cohort, and “not ground truth” label. Show inspection concerns on linked review cases. Do not overwrite frozen v5 labels or silently replace the published ranking with verifier labels.

**Acceptance:** both rankings recompute from saved memberships or predictions; zero-member topics remain explicit; selected examples cannot be mistaken for measured subtopic prevalence. Recommendations retain conditional language until the actual quality gate passes.

### P1 — Replace ambiguous disagreement totals and raw ratios with defined metrics

The UI currently shows **“Final Disagreements: 354”**, while operational traces record **339**. Both are internally valid:

| Definition on final labels versus blind verifier | Count / denominator |
|---|---:|
| Topic, intent, or severity differs | 310 / 1,000 |
| Those categorical fields differ, or absolute sentiment difference > 0.25 | 339 / 1,000 |
| Any exact business-field difference, including sentiment | 341 / 1,000 |
| Any exact business-field or `needs_review` difference | 354 / 1,000 |

Two records contribute only a small sentiment difference to the third rule; another 13 differ only on `needs_review`. The current panel omits these definitions. Sources: [`engine.py`](../src/spotify_pipeline/engine.py), [`evaluation.py`](../src/spotify_pipeline/evaluation.py), and the independently recomputed [inspection definitions](../evals/pilot_inspection_report.json).

**Change:** make the primary metric **“Operational disagreements: 339 / 1,000”**, with the exact rule visible. Offer categorical, exact-business-field, and flag-inclusive definitions separately. Render agreement as **“82.8% · 828/1,000”**, not just `0.828`. Label severity as exact agreement and sentiment agreement as exact numeric equality; show absolute differences separately.

Model comparison divides agreement by returned verifier entries, whereas mean absolute difference uses comparable entries. Those denominators happen to be 1,000 here; the contract must preserve the difference when a verifier result is missing or invalid. A missing comparison is not an error against known truth.

**Acceptance:** each metric has an explicit rule, numerator, denominator, unit, missing-data policy, and source. The dashboard never labels model disagreements as errors or agreement as accuracy.

### P1 — Give human, model, inspection, synthetic, and structural evidence separate sections

[`run-display.ts:36`](../web/src/lib/run-display.ts#L36) deliberately selects 17 comparison scalars. It drops routing/confidence diagnostics and completed qualitative inspection. The database currently stores one `evaluation` JSON value, and the importer accepts a supplied report without validating a typed evaluation envelope or binding its metadata to the record/configuration hashes. Replacing that value with a human report would also replace the visible model comparison.

Generic [`scalarMetrics`](../web/src/app/page.tsx#L194) recursively flattens fields and takes the first 18. A future human report can therefore crowd its actual metrics out with metadata and classification diagnostics. `hasCompletedHumanEvaluation` checks two flags; it does not validate label count, provenance, cohort, or configuration.

**Change:** use separate typed sections within one versioned report. Human metrics stay `null` with a pending status until independently supplied labels and identity checks support evaluation. Display both model comparison and human results when available; do not make one replace the other. Put synthetic testing in its own explicitly synthetic section.

The [live synthetic smoke report](../evals/synthetic-live/v5-live-001/safety_report.json) records operational success but model-behavior failure. It is outside business metrics and must not become an overall green “evaluation passed” because the requests completed.

**Acceptance:** importing a report for another `label_config`, source/record hash, or review-ID manifest fails atomically. Pending human labels cannot produce zero error or a perfect score. A failed model-behavior assertion cannot be hidden by passing transport/structural checks.

### P1 — Show the uncertainty flag’s limitations and missed concerns

**Quick-reader risk:** 94.8% `needs_review` agreement can look like strong error detection, while review cards with no warning may look validated.

Actual final-versus-verifier flag counts are:

| Final flag | Verifier flag | Records |
|---|---|---:|
| False | False | 913 |
| True | True | 35 |
| True | False | 25 |
| False | True | 27 |

The saved report has **60 final flags, zero numeric confidence values, and 1,000 unavailable numeric signals**. Initial flags total 93. Fallback reached 46 unique texts, equal to `floor(926 × 0.05)`; it changed business labels in 27 records. Final flags include 47 non-routed and 13 routed records. Six of the seven concerns in the random inspection were unflagged.

**Change:** call the signal an **“Uncalibrated review flag.”** Show coverage, sources, fallback cap/denominator, routed cases, and unresolved cases. Place **“No flag does not establish correctness”** beside case filters. Expose original, final, and verifier predictions in the same development-case view. State that fallback and verifier both use GPT-OSS, beyond the generic correlation caveat.

The configured numeric uncertainty threshold is not an observed calibrated Lightning confidence score. If the threshold is inactive for the provider/model, the contract should say so.

**Acceptance:** missing confidence renders unknown; it is never coerced to zero uncertainty or 100% confidence. Flag precision/recall remain unavailable without an appropriate labeled evaluation; AI-assisted concern counts are separately named and not presented as human error rates.

### P2 — Date the cumulative cost snapshot and separate later experiments

The current copy correctly says **incremental this run**, **nominal**, and **at this snapshot**. The snapshot date and excluded later experiments are not visible next to the cumulative amount.

| Nominal ledger measure | Published pilot snapshot | Read-only local ledger at audit |
|---|---:|---:|
| Known usage | $0.192745660 | $0.214957094 |
| Unknown-charge hold | $0.014194100 | $0.016446200 |
| Reserved in-flight | $0 | $0 |
| Committed known + hold + reserved | $0.206939760 | $0.231403294 |
| Attempts | 231 | 268 |

The later known usage is **$0.022211434** above the published snapshot; 37 later attempts exist. This is not a defect in the frozen pilot run. It is a freshness distinction for recovery, concurrency, synthetic, and future model experiments. Neither amount is a reconciled cash purchase or provider credit balance.

**Change:** show **“Project ledger snapshot as of [UTC timestamp]”**, the covered experiment IDs/count, and “later experiments excluded” when a newer published experiment ledger exists. Keep the pilot’s `$0.096661512` incremental value immutable. A separately exported project-ledger snapshot can update independently of review classifications.

**Acceptance:** publishing a new cost snapshot does not alter historical run measurements; changing projected volume does not change them either. Known usage, unknown holds, in-flight reservations, and cash reconciliation status remain distinct.

### P2 — Preserve evidence distinctions and make trace inspection useful

The public review API returns classifier/model, fallback, initial prediction, and flag provenance, but the [`Review` type and dialog](../web/src/app/page.tsx#L54) do not display that provenance. “Exact substring of the source” is true, yet its check mark can be mistaken for support of the label. All 1,000 saved quotes are the complete original text.

**Change:** show separate rows for **source integrity**, **semantic support assessment**, and **prediction provenance**. Allow development-case inspection of source → initial prediction → routing reason → final prediction → blind verifier → inspection rationale. List request/artifact references without private filesystem paths or credentials. Label issue evidence as ID-ordered pagination, not a representative sample.

Claim IDs currently prove that cited numbers exist and reproduce from the ranking; they do not prove the associated prose or subtopic interpretation. Alternatives currently display rationale without their saved claim/review links. Make those links available too, and expose the count when only three of a recommendation’s reviews are initially shown.

### P2 — Publish one authoritative evaluation manifest and keep UI requests coherent

There is already a stale generated artifact: `runs/pilot/1000/evals/learning_report.json` says **0/60 inspected** and deployment review missing. The later top-level inspection and publication reports prove that inspection and deployment reconciliation finished. The quality hold is now due to observed label problems, not missing inspection. A harness must not select “whichever report file exists” as the current decision.

**Change:** publish an evaluation manifest selecting exact report IDs/hashes and supersession relationships, with both run generation and publication timestamps. Derive the displayed gate from that manifest. Keep earlier reports immutable and explicitly historical.

The UI independently fetches overview, issues, and recommendations, but does not compare their returned run IDs. Each API transaction is internally consistent; a current-run switch between requests could still mix runs on screen. Bind requests to a selected `run_id`/publication snapshot and reject mismatched responses. The new Evaluation API should follow the same rule.

**Acceptance:** a mixed-run response fixture triggers a reload/state error instead of rendering a hybrid analysis. Publishing another pilot or development experiment does not change the current run unless promotion is explicit.

### P3 — Clarify scope and units

- State the pilot’s sampling manifest, original-ID weighting, and exclusion of the golden holdout. Reused text retains each original review’s weight; it is not a count of unique users.
- The current mean severity is rounded to two decimals for display; the claim register and exports retain six. This is acceptable if the score definition remains visible.
- The storage formatter divides by `1024²` while labeling the result MB. Use MiB, or divide by `1,000,000` for MB. Keep the expansion threshold’s byte value explicit.
- Record observed label-period bounds when supported by the source. Avoid implying that a small historical review sample measures current Spotify incidence, revenue impact, or observed churn.

## Proposed Evaluation tab and harness contract

This is a proposal, not an implemented API or claim that the following fields already exist. The harness should write a schema-validated report and selected development/synthetic case rows offline. The publication step should validate identities, then import that saved report transactionally. Dashboard requests should make no model calls.

Suggested read-only interfaces:

- `GET /api/evaluation?run_id=<id>`: the report matching the chosen publication snapshot.
- `GET /api/evaluation/cases?run_id=<id>&report_id=<id>&cohort=<id>&cursor=<cursor>`: capped, stable pagination of development or synthetic cases.
- Existing overview/issues/recommendations routes accept the same run/snapshot binding.

The existing JSONB evaluation column can hold the versioned envelope initially. A report table keyed by `(run_id, report_id)` and a case table keyed by `(report_id, cohort_id, review_id)` are preferable when retaining multiple evaluation snapshots. Keep verbose provider handoffs in downloadable artifacts rather than duplicating them in Postgres.

### Envelope

```typescript
type EvaluationReport = {
  schema_version: "spotify-evaluation-dashboard-v1";
  report_id: string;
  run_id: string;
  label_config: string;
  publication_snapshot_id: string;
  generated_at: string;                 // UTC, evaluation generation
  published_at: string;                 // UTC, publication
  source_sha256: string;
  records_sha256: string;
  selected_ids_sha256: string;
  artifact_refs: ArtifactRef[];          // sanitized relative/download references + SHA-256
  supersedes_report_id: string | null;
  coverage: Coverage;
  quality_gate: QualityGate;
  human: HumanEvaluation;
  model_comparison: ModelComparison;
  routing: RoutingEvaluation;
  inspection: InspectionEvaluation;
  structural_checks: CheckResult[];
  synthetic_checks: SyntheticEvaluation;
  ranking_sensitivity: RankingSensitivity | null;
  costs: CostSnapshots;
};
```

Every referenced artifact must be tied to this run/configuration, or explicitly identify a separate experiment/cohort. Golden answer files must remain isolated from enrichment, prompt tuning, routing, and candidate-selection inputs. Public human reporting should expose aggregate results and provenance; the development-case endpoint must not expose the held-out answers as a tuning set.

### Metric primitive

```typescript
type Metric = {
  metric_id: string;
  label: string;
  kind: "model_agreement" | "human_agreement" | "human_error"
      | "model_difference" | "count" | "structural_check";
  field: string | null;
  phase: "initial" | "final" | null;
  value: number | null;
  unit: "fraction" | "count" | "severity_points" | "sentiment_points";
  numerator: number | null;
  denominator: number | null;
  denominator_definition: string;
  missing_count: number;
  comparison_rule: string;
  threshold: number | null;
  weighting: "original_review_id";
  artifact_ref_ids: string[];
  interval: { method: string; lower: number; upper: number } | null;
};
```

Do not invent confidence intervals from two model outputs or treat duplicate-text original IDs as independent semantic observations when estimating statistical uncertainty. For means, preserve the evaluated count and definition; a numerator is optional. Human errors require appropriate human ground truth. “Not measured,” “pending,” “failed,” and measured zero are different values/states.

### Required section fields

| Section | Required content and behavior |
|---|---|
| `coverage` | Named cohort, input/source counts, original-ID and distinct-text counts, exact-text aliases, cache hits, requested/returned/successful/comparable verification counts, failed/missing counts, selection method/seed/ID manifest, holdout exclusion assertion. Original IDs and unique-text denominators must not be mixed. |
| `quality_gate` | `status: pass \| hold \| not_evaluated`, recommendation status, criterion IDs, each criterion’s observed result/expected rule, reasons, owner/reviewer type, next actions, artifact refs. Passing transport or agreement alone cannot establish quality. |
| `human` | `status: pending_labels \| incomplete_labels \| evaluated \| invalid`, expected/complete/evaluated label counts, human provenance/attestation, frozen configuration identity, source-ID/hash validation, ambiguity/adjudication policy, metrics or `null`. Preserve per-metric denominators. |
| `model_comparison` | Answer-blind flag and audit result; classifier/fallback/verifier provider/model IDs; shared-model relationship; initial and final metrics; all named disagreement definitions; severity-difference histogram and sentiment-difference distribution; comparison coverage and failures. |
| `routing` | Initial/final flag counts, flag sources, numeric-signal availability, calibration status, effective threshold or “not applicable,” fallback fraction/cap denominator/cap count, eligible/routed/excluded-by-cap counts, routed and non-routed unresolved counts, before/after label changes. Do not call same-model agreement gains accuracy improvements. |
| `inspection` | Reviewer type and `human_ground_truth: false` for this AI-assisted review; separate random/targeted cohorts with seeds/selection rules; concern/ambiguous/supported counts; flagged-by-assessment matrix; linked case IDs. Do not pool targeted and random cases into prevalence. |
| `structural_checks` | Source-field/hash preservation, quote containment, literal-entity checks, source/label ID coverage, membership/ranking/claim reconciliation; numerator/denominator and failure IDs. Explicitly `semantic_support_established: false` unless separately evaluated. |
| `synthetic_checks` | `synthetic: true`, case-set/version, predeclared expectations, actual values, operational/model-behavior outcomes separately, pipeline stages tested/not tested, overall status, production-data-exclusion assertion. No synthetic case enters business metrics. |
| `ranking_sensitivity` | Cohort/hash, same aggregation rule, published final-label ranking and named alternate-prediction ranking, rank/score deltas, membership changes, `ground_truth: false`, clear interpretation. This must not mutate the primary ranking. |
| `costs` | Immutable incremental run amount; dated project-ledger snapshot; experiment coverage; known/unknown/reserved/committed amounts; rate snapshot identity; nominal/invoice/credit/cash basis; billing reconciliation status; no fabricated cash balance. |

### Case detail contract

Each development/synthetic case should provide:

1. Original review ID/text/hash and cohort/selection reason.
2. Initial/final/verifier labels, their provider/model/configuration identities, and whether answers were hidden from verification.
3. Fallback decision/reason, effective routing rule, review-flag sources, and nullable confidence with its meaning.
4. Structural quote/entity checks separately from semantic-support assessment.
5. Inspection/adjudication type, concern/ambiguity/support status, rationale, and any suggested interpretation explicitly identified as such.
6. Issue memberships and the record’s exact contribution to published and alternate ranking scores.
7. Sanitized request/handoff/artifact IDs and hashes; direct cache source ID with no alias chains.

### Tab order and presentation

1. **Quality decision:** hold/pass/not evaluated, reasons, next actions, evaluated run and as-of timestamp.
2. **Human benchmark:** pending count and purpose first; later actual measured human metrics.
3. **Blind model comparison:** paired initial/final percentages with denominators; named disagreement rules and model relationships.
4. **Routing and unresolved cases:** coverage, uncalibrated flags, cap decisions, flagged/unflagged inspection cases.
5. **Development inspection:** separate random and targeted cohorts with case drill-down.
6. **Source integrity and synthetic tests:** separate operational integrity from model-behavior outcomes.
7. **Ranking sensitivity and reproducibility:** alternative predictions, exact calculation artifacts, schema/configuration hashes.

## Implementation order and acceptance gate

1. Agree the envelope and metric semantics with the harness owner. Add the pure offline export/schema validation first; do not regenerate frozen outputs.
2. Assemble the v5 report from authoritative comparison, inspection, synthetic, and publication evidence. Explicitly supersede the stale auto-generated learning report. Verify every number against source artifacts.
3. Add targeted tests for mismatched run/configuration hashes, missing verification, pending human labels, failed synthetic behavior, unknown confidence, disagreement thresholds, stale cost snapshots, and mixed-run API responses.
4. Implement the Evaluation tab and API only after that contract is accepted. Remove generic scalar flattening and run-ID-specific gate logic; preserve the current pilot warning during migration.
5. Reconcile persisted report/case rows with the saved export, inspect the rendered desktop/mobile view, and then request the authorized publication/deployment step.

**Current sharing assessment:** suitable to share as a transparently provisional pilot, with its existing hold notice. **Needs revision** before being used to select a product priority, assert accuracy, compare v6 against v5, or authorize expansion.

This pass did not operate the shared browser or repeat rendered responsive/keyboard QA. Current layout behavior is therefore outside this audit’s fresh verification; the parent can combine this report with its visual inspection. No UI, production data, or deployment was changed by this audit.
