# Implementation validation

This evidence distinguishes software correctness, actual provider execution and
hosted behavior. None establishes human-label accuracy. All 1,000 learning
reviews and independent verifications completed; no expansion beyond the
learning milestone has run.

`runs/` is excluded from Git. Run paths below name files in the
[v0.1.0-pilot evidence release](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/v0.1.0-pilot).
Download and extract its archive rather than treating these code paths as
GitHub directory links.

| Check | Saved result and scope |
|---|---|
| Full Python suite | 247 passed, 1 skipped; no failures/errors in [pytest.xml](pytest.xml), October 19 at 23:17 Pacific |
| Source checksums and ingestion profile | Supplied manifest matched; [ingestion report](../data/ingestion_report.json) |
| Selected future cohort | 210,000 nonempty original IDs plus 13 explicit empty rows; prepared, not classified |
| Learning input | 1,000 original IDs / 926 distinct texts; excludes golden IDs |
| Frozen v5 configuration | [Model/settings/prompt snapshot](frozen_pilot_configuration.json) |
| Required v5 100 cold | 100 complete; 8 actual calls, no failed attempt; $0.006540340 nominal API value; 39.8034 seconds; 10 independent verifications |
| Required v5 100 warm | 100 complete; no new call or API value; 0.0785 seconds; 100 record-cache and 3 task-cache hits |
| V5 500 incremental | 500 complete; 25 actual calls, no failed attempt; $0.015570362 nominal API value; 73.4815 seconds; 50 independent verifications |
| V5 1,000 incremental | 1,000 complete / 926 distinct texts; 123 actual calls, no failed attempt; $0.096661512 nominal API value; 335.3337 seconds; 1,000 independent verifications |
| Initial five-route public API check | Historical HTTP 200 JSON with database-unavailable state; [public_http.json](public_http.json) |
| Subsequent hosted Neon preflight | Three routes return HTTP 200 / `status: empty`; zero published analysis rows; [neon_api_preflight.json](neon_api_preflight.json) |
| Published pilot reconciliation | [pilot_publication.json](pilot_publication.json): all 1,000 database records, 8 rankings, 32 claims and 445 membership rows match; all 14 review pages traversed; 15 detail reviews plus 400/404/409 behavior checked in 37 requests |
| Live browser visual QA | [dashboard_visual_qa.json](dashboard_visual_qa.json): corrected duplicate/cache counts, quality-hold notice and review detail modal verified |
| Measured database size | Application tables/indexes 1,425,408 bytes; whole database 9,297,920 bytes. Linear 210,000-review estimate 299,335,680 bytes, below 700 MB gate; remeasure at 10,000 |
| Human golden evaluation | Not run; all 50 label answers remain blank |
| Actual frozen-configuration interruption/resume | Helper passed: 60 committed records retained after actual SIGINT; resumed to 500 with no loss/repeated first-pass classification/changed holds. Later scheduled fallback requests touched three checkpoint IDs; `runs/recovery-nebius-v5/recovery/recovery_validation.json` |
| Matched 100-review concurrency trial | Four-worker cold run: 8 calls, $0.0066878, 31.395 seconds versus one-worker 39.8034; one trial per setting, not sustained capacity |
| Observed Neon sleep/wake | [neon_sleep_recovery.json](neon_sleep_recovery.json): control plane observed idle, then all three public entry APIs returned ready; overview returned 1,000 records in 1.009 seconds; post-wake control plane active |
| Live synthetic model behavior | [Evaluation](../evals/synthetic-live/README.md) **failed** its strict behavioral check; two real calls, $0.00055269, isolated from all business metrics |
| Unchanged course checker, principal pilot | [checker_pilot.json](checker_pilot.json): `review_required`; 1,000 valid completed records, with no interruption checkpoint/resume in this execution |
| Unchanged course checker, recovery | [checker_recovery500.json](checker_recovery500.json): `review_required`; 500 valid completed records, cancelled-call usage unknown and scheduled fallback counted as repeated enrichment |

The full Python XML snapshot does not include the optional real PostgreSQL
integration test without `SPOTIFY_TEST_DATABASE_URL`. A separate enabled local
PostgreSQL run passed 15 tests, and the JavaScript cursor/public
metadata checks passed three tests. The deployed production build passed
compilation and TypeScript checks. Those separate observations are not implied
by the Python XML count; retain their scope when reporting them.

PostgreSQL integration uses explicitly synthetic fixtures to check exact source
preservation, cache-origin consistency, claim reconciliation, idempotent import,
transaction rollback, cursor pagination and reader permissions. Synthetic
figures are excluded from published review findings. The hosted reader permits
SELECT while denying INSERT, UPDATE and schema-object creation; default
read-only behavior is enabled.

## Actual model measurements

Cold (`runs/pilot/100-cold/run_summary.json`),
warm (`runs/pilot/100-warm/run_summary.json`),
500 (`runs/pilot/500/run_summary.json`) and
1,000 (`runs/pilot/1000/run_summary.json`) have the same frozen v5 label identity.
All calls use Nebius: Lightning enrichment without thinking, GPT-OSS low-effort
fallback/verification/grouping and GLM-5.3-Flash low-effort memo generation.
The fixed 100 inputs and settings are identical across cold and warm.

The sequence totals 156 requests without a failed attempt, $0.118772214 of
nominal token value and 448.6971 active seconds. No learning record remains
pending or quarantined; 60 have review flags and 46 use fallback predictions.
Final independent agreement is 82.8% topic, 90.6% intent and 83.8% severity.
There are 354 records with any exact difference across all compared fields;
the engine's 339-case trigger instead uses topic/intent/severity mismatch or
sentiment difference greater than 0.25 and excludes `needs_review`.
These measures have different definitions, not contradictory coverage.

The [learning report](../docs/learning-report.md) keeps the quality gate closed.
The seeded 30-review development inspection found seven concerns, eight
ambiguous cases and fifteen supported cases. Six concerns were unflagged.
Qualitative AI-assisted inspection is separate from the blank human golden set.

Token-value measurements are nominal usage calculations, not reconciled credit
debits or incremental cash purchases. Current completed stages have complete
usage, while earlier uncertainty remains held globally. The 500 stage reuses
prior results; its recorded cost and time must not be represented as a cold
500-review benchmark. Warm model outputs retain historical source request IDs
in `evidence_calls.jsonl`; that file is not an incremental billed call log.

A structurally valid source quote can accompany an incorrect label. Source-only
verifier agreement is reported separately from human accuracy. GPT-OSS is also
the fallback model, so first-pass and final-after-fallback agreement require
separate interpretation. `needs_review` is an uncalibrated flag.

## Failure history and accounting provenance

- OpenAI contract evidence (`runs/openai-contract-check/run_summary.json`):
  three insufficient-quota failures, no completed labels, $0.0112626 retained
  unknown-charge hold.
- Qwen (`runs/nebius-contract-qwen/report.json`) and
  GPT-OSS (`runs/nebius-contract-gptoss/report.json`) two-review probes:
  narrow API/schema compatibility, not label accuracy or the required pilot.
- [Screening v1](../docs/nebius-screening-v1.md): source-unsupported entity;
  interrupted repair. Known nominal usage was $0.0010859, with a separate
  $0.0029315 unknown-charge hold.
- [Screening v2](../docs/nebius-screening-v2.md) and
  [archived v2 inspection](../docs/nebius-pilot-changes.md): concrete label and
  output-contract failures, kept as development evidence.
- [V3/v4 memo failures and GLM selection](../docs/nebius-adaptation.md):
  failed attempts remain charged and excluded from the final v5 benchmark.
- V4 accounting correction (`runs/experiment-v4-gptoss-memo-failure/100-cold/accounting_correction/audit.json`),
  with corresponding v2 (`runs/experiment-v2-cold-memo-failure/100-cold/accounting_correction/audit.json`)
  and v3 (`runs/experiment-v3-cold-memo-failure/100-cold/accounting_correction/audit.json`)
  audits: exact request-ID summaries, original bytes and hashes preserved;
  global charges, calls, labels and elapsed time unchanged.

The [published pilot reconciliation](pilot_publication.json) supersedes the
earlier empty/unavailable transport states and establishes matching saved
records, counts, ranking, claims, evidence pagination and recommendations.
The [sleep/wake check](neon_sleep_recovery.json) subsequently observed real idle
compute and successful public reads; [post-wake state](neon_post_wake_status.json)
was active. The storage calculation is a linear pilot extrapolation, not
measured full-volume capacity.
The separate frozen-configuration recovery demonstration passed. Its deliberate
cancellation retains a $0.0022521 unknown-charge hold alongside $0.014970944
known nominal usage; recovery does not turn an interrupted request into a free
call. These costs are additional to the main checkpoint sequence.

The recovery helper specifically rules out repeated **first-pass**
classification, not every later paid request involving a completed ID.
Two scheduled fallback calls touched three saved checkpoint IDs. The unchanged
checker flags those calls and the cancelled call's null usage, so its
`review_required` result is retained rather than repaired by inventing zero
usage or suppressing the fallback evidence.

The live synthetic test exposed an actual unsupported billing/severity-five
answer to pure injected instructions. The pipeline set a review flag, while
blind GPT-OSS returned the expected labels. Both models omitted their raw
injection flag on the otherwise correctly classified blocked-playback case.
The planted wrong topic/severity were detected, but the stricter whole-case
check still failed. This small test supports holding expansion; it does not
measure broad robustness or population accuracy.
