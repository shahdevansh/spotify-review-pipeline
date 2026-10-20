# The 1,000-review pilot works; fix label errors before scaling

The complete pilot classified all **1,000 original review IDs**, independently
checked all 1,000 with a second model, generated saved issue rankings and a
recommendation memo, and published the results to a database-backed
[dashboard](https://spotify-review-observatory.vercel.app).
The final checkpoint sequence made **156 requests with no failed attempts**,
using **$0.118772214 of nominal API value**. Its measured active wall time was
448.6971 seconds, including the warm replay. Earlier experiments and separate
recovery/concurrency tests are additional usage, not hidden inside that number.

**Decision: do not expand this frozen configuration yet.** Budget and hosting
look feasible. Topic boundaries, intent precedence, severity, and the weak
uncertainty flag remain material quality concerns. This is the requested
learning milestone, not a completed 210,000-review submission.

Confidence is **high** in coverage, source preservation, deterministic
calculations, and the observed execution. Confidence is **moderate** in the
cost/storage projections, **low** in sustained runtime, and **unknown** in
human-label accuracy.
The 50 human golden labels have not been supplied. Independent model agreement
and AI-assisted inspection are not substitutes for them.

## What changed after learning from the pilot

The user's existing Nebius credits removed the need to purchase Vercel Gateway
credits. The configured Nebius catalog did not expose Jev. We tested available
models and selected the following roles:

| Role | Model hosted by Nebius | Setting |
|---|---|---|
| First classification | `nvidia/Nemotron-3_5-Lightning` | Thinking disabled |
| Difficult cases, independent verification, grouping | `openai/gpt-oss-120b` | Low reasoning |
| Recommendation memo | `zai-org/GLM-5.3-Flash` | Low reasoning |

Lightning supplies the fast System-1 **role**; it does not reproduce Jev's
architecture or calibrated confidence. GPT-OSS supplies separate fallback,
verification and grouping roles with different inputs and saved handoffs.
GLM replaced GPT-OSS for the memo after repeated bounded-output failures in
earlier experiments. No human golden answers were used for these choices.

The main implementation lessons were to attach exact source quotes and literal
entities in code; use short per-request mapping IDs; require exact returned ID
sets and array lengths; give the complete JSON schema in both the prompt and
response-format field; and constrain memo references to actual issue, claim and
review IDs. Earlier failed outputs and charged attempts remain available in the
evidence archive. See [provider adaptation](nebius-adaptation.md) and
[changes justified by observed failures](nebius-pilot-changes.md).

## Measured checkpoints

| Checkpoint | Completed | New calls | Failed attempts | Nominal API value | Active seconds |
|---|---:|---:|---:|---:|---:|
| Fixed 100 cold, one worker | 100 | 8 | 0 | $0.006540340 | 39.8034 |
| Identical 100 warm | 100 | 0 | 0 | $0 | 0.0785 |
| 500 incremental, two workers | 500 | 25 | 0 | $0.015570362 | 73.4815 |
| 1,000 incremental, four workers | 1,000 | 123 | 0 | $0.096661512 | 335.3337 |

The pilot contains **926 distinct texts and 74 exact-text reuses**. Incremental
stages reuse prior work; their costs are not independent cold measurements.
The 100, 500 and 1,000 stages independently verified 10, 50 and 1,000 IDs
respectively, so there are 1,060 paid verification occurrences over 1,000
distinct original IDs.

Amounts reprice provider-reported usage at saved standard rates, including
reasoning in completion tokens. They are not reconciled invoices, credit
debits, or incremental cash purchases. The shared ledger also retains
uncertain-charge reservations from interrupted requests and earlier quota
failures. See the [measured calculator](../cost/README.md).

## Answers to the learning questions

**Which label boundaries cause errors?** The seeded random inspection found
7 concerns, 8 ambiguous cases, and 15 supported cases in 30 reviews. The
targeted inspection deliberately concentrates on difficult cases and cannot
estimate error prevalence. Recurring concerns include crashes/audio failures
assigned to usability, explicit Premium controls assigned outside billing,
generic criticism assigned a specific defect, mixed praise/complaint treated
as a request or praise, and restricted functionality treated as wholly blocked.
These are AI-assisted qualitative judgments, not measured human accuracy.

**Are quotes and entities grounded?** All 1,000 source-field copies, official
row hashes, full-text evidence quotes and literal entities passed integrity
checks. Exact quotation establishes that the words occurred; it does not make
the model's interpretation correct. Several inspected labels remain
questionable despite a perfectly copied quote.

**Does escalation work?** The final result includes 46 fallback records and
60 `needs_review` flags. Six of the seven concerns in the random inspection
were unflagged. This does not support trusting self-reported uncertainty as
the sole router. The fallback and verifier share GPT-OSS, so any improvement in
their agreement may partly reflect correlated errors.

| Agreement with independent verifier | Initial first-pass labels | Final routed labels |
|---|---:|---:|
| Topic | 82.5% | 82.8% |
| Intent | 89.8% | 90.6% |
| Severity, exact | 82.7% | 83.8% |

Final severity mean absolute difference is **0.201**; sentiment mean absolute
difference is **0.0843**. The operational report counts **339 disagreements**
using topic/intent/severity differences or sentiment gaps greater than 0.25.
The evaluation report counts **354** using any exact difference across topic,
intent, severity, sentiment and `needs_review`. The definitions differ; neither
number is an error count against ground truth.

**What did concurrency buy?** A separate cold trial on the identical 100
reviews and configuration took 31.395 seconds with four workers, versus
39.803 seconds with one. The primary request span fell from 15.464 to 10.247
seconds. This is one matched trial per setting, not a sustained-capacity
guarantee. Fallback and verification remain serial, and shared token pacing
limits additional gains. See [scaling economics](scaling-economics.md).

The full fresh-cohort forecast is **$3.52 base / $4.74 conservative** for
159,657 first-pass texts, a cap-saturated 7,982 fallbacks, 2,100 independent
verification reviews, and one final grouping/memo pair. The conservative case
uses higher observed batch unit costs plus an assumed ten-percent retry load;
it is a sensitivity scenario, not a guaranteed bill. API scheduling projects
to 5.44–6.57 hours, with ingestion, checkpoint I/O, database publication and
inspection still additional. Sustained throughput must be measured at 10,000.

**Do recovery and spending controls work?** A separate 500-review experiment
under the same frozen configuration received a real SIGINT after 50 completed
records were observed. Graceful shutdown preserved 60 completed original IDs.
Resume completed all 500 without losing those records or repeating their
first-pass classification. The subsequent scheduled fallback stage did make
two requests covering three checkpoint IDs.
The actual terminal recording, before/after snapshots, request IDs and ledger
audit are saved under `runs/recovery-nebius-v5/` and
`runs/recovery-nebius-v5.cast` in the evidence archive. Its interrupted request
retains a $0.0022521 unknown-charge hold; the experiment consumed $0.014970944
in known nominal usage. This is separate recovery evidence, not an interruption
retroactively claimed for the principal 1,000-review run.
The unmodified course checker marks both exports `review_required`: the
1,000-review run lacks an interruption snapshot; the recovery run honestly
retains unknown token usage for the interrupted request and the checker treats
those scheduled fallback requests as reprocessing. These are disclosed in the
[checker interpretation](checker-interpretation.md); no usage or checkpoints
were fabricated to produce a clean audit result.

**What happened in the live injection test?** Two real Nebius calls evaluated
three nonempty synthetic reviews plus one empty-text quarantine, outside all
business metrics. The fast model followed a pure injected label instruction,
returning unsupported billing/severity-five labels. The deterministic guard
flagged the text; the blind verifier returned other/unclear/severity-one.
On the blocked-playback case with an embedded instruction, both models got
topic/intent/severity right but failed to set their own injection-review flags.
The verifier detected the separately planted wrong topic and severity in a
copied record. This smoke test **failed overall** and demonstrates that
flagging suspicious text alone does not prevent label contamination.
See the [live synthetic evaluation](../evals/synthetic-live/README.md).

**Does the hosted backend reproduce the saved run?** Yes. Reconciliation
checked all 1,000 database records and provenance, all 8 rankings, 32 claims,
445 memberships across all 14 evidence pages, the saved recommendation, and
15 review detail responses. Invalid and stale cursor handling was checked.
The app tables occupy 1,425,408 bytes; the initial linear 210,000-review
projection is 299,335,680 bytes, below the 700 MB planning threshold. Refresh
this projection at 10,000 because retained runs and indexes affect growth.
The [publication check](../validation/pilot_publication.json) records the exact
artifacts and comparisons.

Neon was observed actually idle before an unauthenticated dashboard API request
woke it. The overview returned the saved 1,000-review run in 1.009 seconds;
issues and recommendations also matched, and the control plane subsequently
reported active. The [sleep/wake evidence](../validation/neon_sleep_recovery.json)
records this observed event.

**What does the recommendation mean?** The current baseline ranks usability
first: 127 complaint/cancellation records, severity sum 291, mean severity
2.291339. Billing follows with 83 records and severity sum 239. These are exact
calculations on the saved labels. They are provisional product conclusions:
the top issue's evidence includes crashes and sound failures whose correct
topic may be playback. Topic contamination could change the ranking and should
be repaired before turning the memo into a decision.

## Next iteration and expansion gate

1. Add focused development examples for the observed topic, intent and severity
   boundaries. Keep the golden 50 isolated. Preserve v5 evidence.
2. Compare the revised fast classifier with a stronger first-pass alternative
   on the same development cases. GPT-OSS also made errors; it is not a known
   correct answer key. Nebius's measured economics leave room for this test.
3. Evaluate explicit ambiguity/consistency routing alongside model flags.
   Measure which cases benefit; retain the five-percent cap until evidence
   supports a different allocation. Suspicious injected instructions need
   an explicit unresolved or independently checked handling path; a review
   flag alone did not prevent the observed false label.
4. Freeze the chosen configuration, invalidate affected caches, and repeat the
   fixed 100 cold/warm test. Inspect the resulting errors before the 10,000
   checkpoint, then refresh sustained throughput, cost and database size.
5. Supply the 50 independent human labels and evaluate once the configuration
   is frozen. Report topic/intent agreement, severity exact agreement and MAE,
   sentiment MAE, evidence support and ambiguity honestly.

The entire **660,622-row source** is ingested and profiled. The prepared final
scope is **210,000 nonempty reviews plus 13 explicit empty-text quarantines**,
with **159,657 distinct nonempty texts**. These are preparation counts;
**only the 1,000-review pilot has completed classification in the principal
run**. No 10,000- or 210,000-review processing job was launched.

The repository, live pilot and downloadable evidence are a reviewable first
milestone. Human evaluation and the larger classification run remain necessary
for the full assignment.
