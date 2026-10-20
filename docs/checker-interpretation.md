# Interpreting the unmodified course checker

Both saved checker reports have `status: review_required`. Neither is a full
audit pass. The primary 1,000-review analysis and the separate 500-review recovery
demonstration have different evidence and are exported separately.

Detailed `runs/` artifacts are excluded from Git. The run paths below refer to
the evidence archive described in the [README](../README.md). Download and
extract that archive into the repository root to overlay the saved run folders;
these code-formatted paths are not links to committed GitHub files.

The checked script is byte-identical to the instructor-supplied
`data/source/check_submission.py`; its SHA-256 is
`d60bd66d84922d934c65b3d42b2c7d36cc738e8c75e2d6f2b2f58bca3141c26d`.
Each reference was built from the complete original source CSV and the exact
analysis CSV for that run. The checker was not edited, and no calls, usage,
checkpoints, or labels were synthesized to remove its warnings.

## Primary 1,000-review analysis

The [primary report](../validation/checker_pilot.json) checks
[grading/](../grading/) against `data/learning_1000.csv`. It finds:

- 1,000 valid completed records, no missing, duplicate, quarantined, invalid, or
  unresolved records, and 74 valid exact-text cache reuses.
- No reported discrepancy in source accounting, issue membership, baseline
  ranking, or numerical claims.
- Three recovery-related flags: `unreadable_file` for the absent
  `checkpoint_before.json`, `resume_snapshot_mismatch`, and
  `resume_call_evidence`.

This analysis run was not interrupted. Its missing before-checkpoint and resume
calls remain missing. The 500-review recovery files have not been copied into
this export.

The [offline rerank check](../validation/offline_rerank.json) independently
regenerated ranking, aggregates, and claims from copies of the saved 1,000 records
and membership without credentials or model calls. Their byte hashes matched
the originals; the original run files remained unchanged.

## Separate 500-review recovery demonstration

The [recovery checker report](../validation/checker_recovery500.json) checks
the separate `runs/recovery-nebius-v5/grading/` export against the
unchanged `checkpoint_500.csv`. It finds 500 valid completed records and 21 valid
exact-text cache reuses, with no missing or duplicate IDs and no ranking or
claim discrepancies. Its remaining flags are:

| Flag | Count | Observed cause |
|---|---:|---|
| `invalid_usage` | 2 | One cancelled in-flight call has unknown input and output token counts. |
| `reprocessed_checkpoint` | 2 | Two resumed fallback calls include three IDs already saved as completed first-pass records. |

The cancelled request, `8d58e0c81ef24b429899d42e59606895`, has
`purpose: initial_classification`, `outcome: failed`, and
`error: cancelled_in_flight_usage_unknown`. Both token counts and its actual
cost remain `null`. The ledger retains a $0.0022521 unknown-charge hold.
The checker requires nonnegative integer token counts for every attempt,
including failures. Substituting zero would invent billing evidence, so the
two `invalid_usage` flags are preserved. The hold is an estimated reservation,
not a confirmed charge or guaranteed upper bound.

The two calls flagged as reprocessing are recorded in
`runs/recovery-nebius-v5/calls.jsonl`:

| Resumed request | Recorded task | Previously saved first-pass IDs included |
|---|---|---|
| `0d763280ad9e491fb92c2db1e25dcc8d` | `role: enrich`, `purpose: fallback`, `is_fallback: true` | `084077ee-f9be-446a-9935-9e58550d5153`; `3e8bdc92-4934-457e-85cc-8b9d14bf51c0` |
| `805ef03963494f549e44ef4c8848372d` | `role: enrich`, `purpose: fallback`, `is_fallback: true` | `ad730d1a-829a-4dc4-9561-7e1cd07e2c30` |

The saved before-checkpoint contains 60 completed first-pass IDs; the final
after-checkpoint contains 500. The custom
`runs/recovery-nebius-v5/recovery/recovery_validation.json`
confirms no lost completed IDs, no repeated first-pass classification, and no
release of the interrupted call's uncertain reservation.

That custom check is narrower than the course checker. Scheduled fallback
judgments did run after resumption for three records already marked completed
by the first pass, and those calls incurred additional usage. Therefore the
evidence supports **no repeated first-pass classification**, but does not support
a broad claim that no completed ID received another paid judgment. The course
checker treats successful resumed `enrich` calls uniformly and preserves both
reprocessing flags. Recovery billing is still incomplete because of the
cancelled call's unknown usage.

## What these results do not establish

The checker returns a coverage candidate of 1.0 for each declared analysis
scope. This is not a course grade and does not satisfy the assignment's amended
minimum of 100,000 classifications. These artifacts establish a 1,000-review
learning run and a separate recovery experiment, not a completed 200,000-plus
review analysis.

The checker reports human-label quality as `not_supplied`. Valid source hashes,
quotes, schemas, calculations, and call logs do not establish semantic label
accuracy. The human golden evaluation remains separate. The completed
[fixed-100 cost package](../cost/measured-100/report.md) includes only actual
cold/warm calls; historical cache-origin calls in grading exports are not added
again to its measured costs.
