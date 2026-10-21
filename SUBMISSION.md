# Final assignment: grader entry point

**Submitted analysis:** 200,000 classified nonempty Spotify reviews, 13 empty-text quarantines, and 40,000 independent full GLM-5.3 audits. The entire 660,622-row source was ingested and profiled. The [current assignment](https://docs.google.com/document/d/1PUFw56OGxqbUxiFm0vKtsWX8ac8633BgOlCSGa3TgLA/edit) permits at least 100,000 classified reviews; the declared subset exceeds that amended minimum. Older full-corpus wording in the supplied contract is preserved, not silently rewritten.

## Open these first

1. [Live dashboard](https://spotify-review-observatory.vercel.app): public, read-only, database-backed; inspection makes no model calls.
2. [Decision memo](docs/hero-decision-memo.md): usability reliability/control clarity, alternatives, issue/review IDs and numerical claim references.
3. [Original hero evidence ZIP](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-hero-evidence.zip): frozen `grading/`, `cost/`, independent evaluation, role handoffs and recovery evidence. SHA-256: `950fe1f6fcb1b53a3cc6ce634b071411669b930e5aba05f0c623ea871947049d`.
4. [Submission supplement ZIP](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-submission-supplement.zip): additional grader-facing evidence, without replacing the original hero archive or changing predictions.
5. [Human expected-label/prediction comparisons](evals/human-reference-v2/): all 200 worksheet records, with a separate golden-50 subset, explicit missingness, per-field outcomes and provenance. The user approved this minimal export; personal notes and annotator identity are excluded.
6. [Fresh setup and reproduction evidence](evals/submission-readiness/), [current calculator guide](cost/hero-replay.md), and [database setup](web/README.md).

The [full README](README.md) provides architecture, model/settings rationale, one complete review trace, error analysis, results, limitations and commands. [Publication receipt](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/publication-receipt.json) identifies the original final run, release checksum and public verification. Supplemental evidence is an additional dated validation layer.

## Results and qualifications

| Measure | Frozen hero result |
|---|---:|
| Source rows ingested | 660,622 |
| Selected records | 200,013 |
| Completed nonempty / quarantined empty / pending | 200,000 / 13 / 0 |
| Distinct texts / direct exact-text aliases | 152,363 / 47,637 |
| Independent audit | 40,000 original IDs; 20% |
| Model topic / intent agreement | 36,187/40,000 (90.4675%) / 37,220/40,000 (93.05%) |
| Golden human topic / intent agreement | 33/47 (70.21%) / 41/47 (87.23%) |
| Original project recorded usage / uncertain-charge hold | $35.319959027 / $1.563189415 |
| Original workflow through first public release | 14,986.278 seconds, approximately 4 h 10 min |

The model comparison is **agreement, not human accuracy**. Human results are **posthoc adjudicated reference agreement**, following earlier model comparisons and **43 approved topic changes**. The production outputs remain frozen. Only 99 of the 200 worksheet IDs belong to the hero cohort; the other 101 retain human values but have null production predictions and are excluded from agreement denominators. They are outside scope, not missing hero outputs.

**Human annotation remains incomplete:** golden topic and intent each have 47/50 explicit labels; severity has 13/50 and sentiment 42/50. Unannotated values are not inferred. Golden severity agreement is 4/13 with MAE 1.0769; sentiment MAE is 0.2020 over 42 explicit labels. The original human severity policy selectively labeled functional issues, differing from the course's all-review severity scale. This limits interpretation and prevents claiming a complete 50-review numeric reference. The supplement exposes the actual per-case evidence instead of hiding missingness.

The original accounting above is token usage repriced at saved rates, not reconciled provider cash invoices. Any subsequent isolated safety-test cost is reported separately in its dated evidence and charged to the same project ledger. No new large-scale classification is required for this supplement.

**The unmodified course checker returns `review_required`, not `pass`.** Its sole issue is 96 unavailable usage fields across 48 genuinely failed calls. All other source, coverage, cache, ranking and claim checks pass. `checker.json` is preserved in the original ZIP alongside a narrowly scoped `checker-acceptance.json`; the latter is a disclosed publication gate, not an instructor grade. Null usage is not replaced with fabricated zeros.

## Ten rubric criteria and where to inspect them

Artifact paths shown in code formatting are relative to the original hero ZIP unless linked to repository files.

| Rubric criterion | Evidence | Status / limitation |
|---|---|---|
| **D1. Accessible code, setup and artifacts** | [README](README.md), [source](src/), [lockfile](uv.lock), [.env.example](.env.example), dashboard and two release assets; [fresh setup receipt](evals/submission-readiness/fresh-resident-repro.json) and [install log](evals/submission-readiness/fresh-resident-install.log) | Fresh committed-source install passed on CPython 3.13.11; 21 locked packages. Offline replay/ranking passed with credentials unset and socket connections blocked. |
| **D2. Architecture, shared schema and provenance** | [Architecture](README.md#architecture-and-frozen-model-roles), [labels/examples](config/labels.json), [prompts](prompts/), [engine](src/spotify_pipeline/engine.py); `run/configuration.json`, `grading/records.jsonl.gz`, `grading/calls.jsonl.gz`, four `handoffs/` files | Distinct enrichment, verification, grouping and memo instructions; code owns accounting, validation and arithmetic. Original IDs/hash/source strings and direct cache provenance retained. |
| **D3. Memo numbers trace to calculations and reviews** | [Memo](docs/hero-decision-memo.md), [review trace](README.md#recommendation-and-evidence-trail); `grading/claims.csv`, `grading/ranking.csv`, `grading/membership.csv`; [business audit](evals/hero/business-audit.md) | 32 claims and eight issues. Recomputed ranking/claims match exact saved bytes; quotes establish source membership, not interpretation accuracy. |
| **D4. Recommendation, alternatives and limitations** | [Memo](docs/hero-decision-memo.md), [business audit](evals/hero/business-audit.md), `recommendations.json`, `editorial-review.json` and original model outputs | Usability leads baseline severity sum; playback, billing and access alternatives considered. Fine-grained intervention prevalence and causal retention effects are not claimed. |
| **T1. Human labels, field comparisons and error analysis** | [Human-reference export](evals/human-reference-v2/README.md), [golden per-case CSV](evals/human-reference-v2/golden50-comparison.csv), [all-200 CSV](evals/human-reference-v2/all200-comparison.csv), [report](evals/human-reference-v2/report.md), [aggregate report](evals/hero-human/report.md) | Inspectable minimal user-approved comparisons. **Partial annotation:** 47 topic/intent, 13 severity, 42 sentiment labels among golden 50; posthoc adjudication, not blind accuracy. |
| **T2. Independent verification, planted error and injection** | `evals/hero/evaluation.json`, `evals/hero/verification.jsonl.gz`, disagreements; [frozen-hero synthetic safety evidence](evals/submission-readiness/frozen-safety/); [historical live failure](evals/synthetic-live/v5-live-001/SUMMARY.md) | 40,000 independent original-text judgments. Synthetic test outcomes remain separate from production/business metrics; consult saved results, including failures. Older-model results are explicitly historical. |
| **T3. Real cold/warm pilot, calculator and controls** | `cost/`, `cost/warm100/`, `evals/hero-pilot/replay-validation.json`, `recovery/`, `recovery.cast`; [hero replay guide](cost/hero-replay.md), [fixed-input validation](evals/submission-readiness/hero-cost-source-validation.json) | Cold 100: $0.02360475, 105 attempts, 41.9034s; warm 100: $0, zero calls, 0.2137s. Source-ID/hash sidecar preserves original null metadata. Retry/spend/recovery controls and sensitivity invariants documented. |
| **W1. Ingestion and successful classification coverage** | `grading/ingestion.json`, `grading/run.json`, `grading/records.jsonl.gz`, `selection.json`, `checker.json` | Full-source profile matches; 200,000 completed nonempty and 13 quarantines. Meets amended volume minimum; does not claim all 660k classification. |
| **W2. Runnable staged program, bounded calls and resume** | [Supervisor](tools/run_hero.py), [arbitrary-input CLI](src/spotify_pipeline/cli.py), [operational recovery](docs/hero-operational-recovery.md); handoffs, call evidence, checkpoints, `recovery.cast` | Requests at most 50; separate roles and durable saved outputs. Real separate-process demonstration:10→40 completed, zero reprocessing of saved IDs, identical classification configuration. |
| **W3. Deterministic ranking and deployed database-backed recommendations** | [Dashboard](https://spotify-review-observatory.vercel.app), [API overview](https://spotify-review-observatory.vercel.app/api/overview), [database setup](web/README.md); `database-publication.json`, `publication-reconciliation.json`; fresh reproduction receipt | 200,013 database records, eight issues, 269 MB; all 87,897 issue memberships reconciled across 1,761 pages. Independent reranking reproduces ranks/claims without credentials or model calls. |

These rows identify evidence, not guaranteed rubric points. Historical failures and incomplete annotations remain visible.

## Reproduce without inference

1. Install from this repository using `uv sync --frozen --extra dev --link-mode copy`; activate `.venv`. The verified fresh installation used a resident directory outside iCloud. The earlier Documents/iCloud import issue and successful resident retry are recorded separately.
2. Verify and extract the original evidence ZIP into `evidence/`. Use [cost/hero-replay.md](cost/hero-replay.md) for explicit hero settings; generic historical replay defaults use a different scope.
3. Follow the README's saved-output reranking command. Redirect its verbose stdout to a local log; compare `ranking.csv` and `claims.csv` byte for byte. The [fresh receipt](evals/submission-readiness/fresh-resident-repro.json) records matching hashes with network calls blocked.
4. Inspect the [fixed-100 identity sidecar](evals/submission-readiness/hero-cost-source-validation.json): all 100 cold/warm IDs and source-row hashes match the unchanged instructor input. This post-run check does not invent a historical input checksum in the frozen reports.
5. Play the original recovery recording with `asciinema play evidence/recovery.cast`, or read its plain-text events and `recovery/recovery-validation.json`.

## Submission status

The required single submission is the [public repository URL](https://github.com/shahdevansh/spotify-review-pipeline) through the [verified final-assignment portal](https://bcourses.berkeley.edu/courses/1555592/assignments/9130940). **Portal submission is pending** until a successful portal confirmation is recorded. Repository publication and public release assets do not themselves submit the assignment.

No separate reflection essay or presentation video is specified. The required recording is interruption/resume evidence. The author should be ready to explain the model/code boundaries, one concrete failure, and why the recommendation is provisional.
