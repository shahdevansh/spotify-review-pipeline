# Implementation status

The frozen v5 pipeline has completed the fixed 100-review cold/warm sequence,
500-review checkpoint, and all 1,000 learning reviews with independent
verification of all 1,000 original IDs.
**No 10,000- or 210,000-review processing run has started.** The 50 human golden
labels remain blank, so human-label accuracy is unknown.

Confidence is high in the saved source counts, request accounting and structural
checks. Label quality and semantic recommendation quality require inspection;
model agreement is not ground truth.

The [learning report](learning-report.md) recommends **holding expansion**:
the seeded random inspection found seven concerns and eight ambiguous cases
among 30 reviews, and six of those seven concerns were unflagged. These are
AI-assisted development judgments, not human accuracy estimates. Topic
contamination in the top-ranked issue makes the business conclusion provisional.
The separate [live synthetic evaluation](../evals/synthetic-live/README.md)
also failed its strict model-behavior check: Lightning followed a pure injected
instruction to assign billing/severity five, while the deterministic guard
flagged the input without correcting the labels. Blind GPT-OSS gave the
expected other/unclear/severity-one answer. Both models classified the
blocked-playback case correctly but omitted the requested injection flag.
These synthetic cases never entered the 1,000-review business metrics.

Paths beginning `runs/` refer to the evidence archive, not committed repository
directories. Download and extract the
[v0.1.0-pilot release evidence](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/v0.1.0-pilot)
to inspect them. Source and methodological reports are committed directly.

## Source and execution scope

The [verified ingestion report](../data/ingestion_report.json) records 660,622
source rows, 660,609 nonempty reviews, 13 empty reviews, and 484,189 distinct
nonempty texts. The deterministic future cohort has 210,000 nonempty reviews
with 159,657 distinct texts; adding the explicit empty-text quarantines gives
210,013 analysis input rows. Selection and full-source profiling are completed
preparation, not evidence that these reviews have been classified.

The learning input contains 1,000 original IDs and 926 distinct texts, excludes
the golden set, and is drawn from the supplied development file.

## Frozen v5 execution

The [saved configuration](../validation/frozen_pilot_configuration.json) fixes
label identity `spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb`.
All inference uses Nebius:

| Role | Exact model | Reasoning setting |
|---|---|---|
| Initial enrichment | `nvidia/Nemotron-3_5-Lightning` | none |
| Fallback, independent verification, grouping | `openai/gpt-oss-120b` | low |
| Recommendation memo | `zai-org/GLM-5.3-Flash` | low |

The fast classifier implements the intended System-1 role but is not Jev and
has no calibrated confidence estimate. Uncertainty/consistency flags drive
fallback capped at five percent of unique texts. Classification uses original
text and request-local mapping IDs; source quotes and literal entities are
assembled by code. The verifier receives no enrichment prediction. Fallback
and verification use the same model, which can increase their agreement.

| Stage | Completed IDs | New requests / failed attempts | Nominal API value | Active wall seconds |
|---|---:|---:|---:|---:|
| 100 cold (`runs/pilot/100-cold/run_summary.json`) | 100 | 8 / 0 | $0.006540340 | 39.8034 |
| 100 warm (`runs/pilot/100-warm/run_summary.json`) | 100 | 0 / 0 | $0 | 0.0785 |
| 500 incremental (`runs/pilot/500/run_summary.json`) | 500 | 25 / 0 | $0.015570362 | 73.4815 |
| 1,000 incremental (`runs/pilot/1000/run_summary.json`) | 1,000 | 123 / 0 | $0.096661512 | 335.3337 |

Cold uses the unchanged course input and an empty cache. Warm reuses all 100
saved records and all three verification/group/memo task results. The
500-review checkpoint reuses prior classifications, has 479 distinct texts,
and independently verifies 50 original IDs; its cost and time are incremental,
not a separate 500-review cold measurement. The cold stage verified ten IDs.
The v5 cache is `data/pilot_v5_cache.sqlite3`.

The sequence totals 156 actual requests, zero failed attempts, $0.118772214
of nominal API value and 448.6971 active seconds, including the warm replay.
The final 1,000 records contain 74 exact-text aliases and 46 fallback outputs;
60 records remain flagged `needs_review`. All records are structurally completed,
with no quarantine or pending record. The 1,000 checkpoint's 549 record-cache
hits include reused earlier outputs and exact-text reuse; they are not 549
additional unique texts. Its verification stage took 272.5312 seconds.

`runs/pilot/1000/evals/verifier_report.json` reports final topic, intent and
severity agreement of 82.8%, 90.6% and 83.8%, with severity mean absolute
difference 0.201 and sentiment mean absolute difference 0.0843. There are 354
records with any exact difference across the five compared fields, including
sentiment and `needs_review`. The engine's separate 339-case inspection trigger
uses topic/intent/severity mismatch or sentiment difference greater than 0.25,
and excludes `needs_review`. The definitions explain the different counts.
Pre-fallback exact disagreements occurred on 365 records; final agreement gains
do not prove correctness when fallback and verifier share GPT-OSS.

The saved baseline ranks usability first with severity sum 291 across 127
complaint/cancellation records, followed by billing at 239 across 83 records.
The saved memo follows that baseline. These are findings within the classified
historical learning sample; semantic inspection and label uncertainty still
constrain any product recommendation.

These amounts value reported token usage at recorded public prices, including
reasoning in completion tokens. They do not establish the credit debit or new
cash expense. The shared ledger retains earlier experiments' charges and
$0.0164462 in unknown-charge holds after the recovery demonstration; those
holds are budget reservations, not confirmed charges. No principal v5
checkpoint has unresolved usage; the deliberately interrupted recovery request
retains its separate hold.

## Implemented safeguards and validation

- Typed validation, exact-text caches, atomic SQLite checkpoints, capped retries,
  shared spending reservations, and separate incremental versus historical call logs.
- Complete cold/warm/500/1,000 orchestration with immutable completed stages,
  per-stage gates and active-session timing. New configurations require new
  output/cache locations; the shared spending ledger persists.
- Compact bounded classification arrays and exact request-local identifier
  mapping. Dynamic group/memo schemas restrict identifiers; cross-issue joins
  and numeral-free prose are validated before accepting a memo.
- Deterministic issue membership, severity-sum ranking, decimal half-up means,
  checked numerical claims, offline calculator, course exports and inspection worksheets.
- Blind golden-label worksheet with no model answers.
- PostgreSQL importer, read-only API with cursor pagination and Next.js dashboard.
- A real command recorder and a passed interruption/resume demonstration under
  the frozen configuration.

[Validation evidence](../validation/README.md) distinguishes automated tests,
real provider execution and hosted checks. Synthetic fixtures establish software
behavior only; they never enter review metrics.

## Preserved development failures

Earlier experiments remain separate from the current v5 measurement:

1. OpenAI contract run (`runs/openai-contract-check/run_summary.json`): three
   inference requests returned insufficient quota; no labels completed.
   The ledger preserves $0.0112626 in unknown-charge holds.
2. [Screening v1](nebius-screening-v1.md): a model-generated entity was not in
   the source; validation rejected the batch. An interrupted retry retained
   a $0.0029315 hold. Code now attaches exact quotes and source-matched entities.
3. [Screening v2](nebius-screening-v2.md): Lightning completed the matched set
   fastest in the observed comparison; substantive label errors remained.
   Missing/duplicate IDs and GPT-OSS output repetition motivated compact mapping
   IDs, exact array lengths and ten-review verifier batches.
4. [Archived v2](nebius-pilot-changes.md): memo responses embedded UUIDs in
   prose or replaced ASCII hyphens with Unicode lookalikes. They were rejected.
5. [Archived v3/v4](nebius-adaptation.md#historical-v3-and-v4-memo-experiments):
   GPT-OSS repeatedly exhausted the memo completion limit. V4 completed cold
   and warm but failed at the 500-review memo. An isolated GLM probe succeeded,
   motivating the fresh v5 configuration and a new cold/warm sequence.

A legacy run ID depended only on output path and mixed derived per-run cost
summaries when output names were reused after archiving. Future identities also
include configuration and cache path. Exact request-ID reconciliation preserves
all original summaries and the full shared ledger. Audit records are saved for
v2 (`runs/experiment-v2-cold-memo-failure/100-cold/accounting_correction/audit.json`),
v3 (`runs/experiment-v3-cold-memo-failure/100-cold/accounting_correction/audit.json`)
and v4 (`runs/experiment-v4-gptoss-memo-failure/100-cold/accounting_correction/audit.json`).
V2's amount was confirmed unchanged; v3 and v4 were corrected. Model outputs,
request outcomes and wall times were not changed.

## Deployment and remaining gates

The [public dashboard](https://spotify-review-observatory.vercel.app) is deployed
and connected to Neon through a dedicated reader role. The saved
[hosted reconciliation](../validation/pilot_publication.json) passed after
publishing the completed 1,000-review pilot: all source/enrichment database
rows, eight ranks, 32 claims and 445 membership rows matched saved artifacts.
All membership records were traversed across 14 API pages; 15 detail reviews
and invalid/missing/stale cursor behavior were checked across 37 API requests.
The earlier [empty-state preflight](../validation/neon_api_preflight.json)
remains historical evidence, not the current published state.

Application tables and indexes use 1,425,408 bytes; the full database occupies
9,297,920 bytes. A linear 210,000-review application-storage projection is
299,335,680 bytes, below the 700,000,000-byte gate. This is a pilot projection,
not a measured full-cohort database, and must be refreshed at 10,000 reviews.
[Actual sleep/wake verification](../validation/neon_sleep_recovery.json)
passed after the Neon control plane reported idle. The first unauthenticated
overview request returned HTTP 200 / ready / 1,000 records in 1.009 seconds;
issues and recommendations also returned ready, and the control plane
subsequently reported active. No model calls or database writes occurred.
The dashboard visibly distinguishes 74 duplicate-text aliases from 549 records
reused in the incremental run and displays the quality hold.

The recorded recovery demonstration sent SIGINT after observing 50 completed
records; 60 were saved before interruption finished. Resume completed all 500,
with no lost completed ID, no repeated first-pass classification of committed
IDs and no changed uncertain reservation. Two scheduled fallback requests
subsequently touched three checkpoint IDs; therefore this is not a claim
that no completed ID appeared in any later paid request.
It recorded 26 successful calls and one deliberate cancellation, $0.014970944
known nominal usage, a retained $0.0022521 uncertainty hold and 99.0407 active
seconds. This is additional evidence usage, excluded from the main pilot cost.
The validation is `runs/recovery-nebius-v5/recovery/recovery_validation.json`.
The [unchanged course checker](../validation/checker_recovery500.json)
returns `review_required`: the deliberate cancellation has unknown token
usage, and the checker counts those fallback requests as repeated enrichment.
The [principal 1,000-review check](../validation/checker_pilot.json) also
returns `review_required` because its execution did not include an interruption
checkpoint/resume. Complete coverage and ranking reconciliation do not make
either report a full checker pass.

A matched 100-review cold trial with four workers took 31.395 seconds and eight
calls at $0.0066878, compared with 39.8034 seconds using one worker. The primary
request span fell from 15.464 to 10.247 seconds, about 1.51 times faster.
One trial per setting does not establish sustained provider capacity.

Before expansion: address the inspected label errors, injection behavior and weak routing, compare
revised candidates on development data, freeze a configuration and repeat the
fixed cold/warm measurement. Refresh conservative
cost/runtime/storage estimates before larger checkpoints. Human golden labels
must be supplied independently before reporting human evaluation. Neither
software tests nor cross-model agreement satisfy that requirement. The
implementation stops at the learning milestone; larger runs remain gated.
