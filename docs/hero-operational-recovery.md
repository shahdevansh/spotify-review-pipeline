# Hero run: storage, recovery and publication checks

**Verified inference and API outcome:** 200,000 completed nonempty classifications, 13 empty-text quarantines, zero pending records and all 40,000 required independent audits completed. Recorded token-rate usage plus unresolved-charge hold is $35.319959027 + $1.563189415 = $36.883148442; zero active reservations at the completed-inference snapshot. The original course checker remains `review_required` solely for missing usage on 48 failed requests; the separate contract acceptance preserves that status and unavailable values. The database contains 200,013 records and eight issues in 269,041,664 bytes. Final unauthenticated API reconciliation passed at 06:09:26 UTC on October 21, traversing all 87,897 issue members and checking 19 detail samples. **Publication:** [hero-v1 evidence](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1), ZIP SHA-256 `950fe1f6fcb1b53a3cc6ce634b071411669b930e5aba05f0c623ea871947049d`. Total workflow elapsed to publication: approximately 4 h 10 min through the first public release (14,986.278 s); final documentation/release-refresh QA is separate; timing evidence: `operational-final.json`.

The hero run completed its target of 200,000 nonempty source reviews and 13 explicit empty-text quarantines. The final independent audit covers all 40,000 selected original IDs. Model agreement is a diagnostic; it does not establish human accuracy. Private annotation files are excluded from the inference harness and public repository. This operational account distinguishes inference completion, API reconciliation and final release publication.

## Changes at the completed 60,000-review boundary

The model, prompts, routing policy and classification fingerprint remained unchanged. No requests were in flight during the maintenance boundary. The source run summary was preserved as `checkpoint-60000.json` before restarting.

- SQLite record, call and exact-text cache payloads use a versioned lossless zlib encoding. Readers accept both the original JSON strings and the compressed payloads. Table-by-table logical hashes verified the database compaction.
- Optional `gzip_exports` writes records, calls, verification and disagreement JSONL using atomic replacements. The decoded records are unchanged. Database import, grading, offline ranking, calculator replay and release packaging accept the compressed filenames. The unmodified course checker passed synthetic submissions in both formats.
- Provider budget checks use a denormalized provider tag maintained from the authoritative `spend_provider` mapping by SQLite triggers. All monetary amounts remain in the original integer nano-USD columns. Migration compared all original transaction fields and provider mappings exactly, retained a backup and checked database integrity. Global, run and provider caps still serialize in one transaction; unknown charges retain their reservations.
- Enrichment supports 32 workers under the existing 32 requests/second ceiling and token pacing. Verification remains at eight workers. Concurrency is an operational setting and does not change classification cache identity.

## Final-audit timeout repair

The hero configuration overrides Nebius's request timeout from 60 to 180 seconds. The provider implementation retains its 60-second default for configurations without an override. The repair changes how long the client waits; it does not change model request content, prompts, output schemas, routing or saved classification identity. Verification remains at eight workers, and the frozen classification fingerprint remains `spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a`.

The saved stop, repair, shutdown, timing and budget records document the interruption and restart. Resume uses durable completed work; it does not reset the spending ledger or substitute verifier labels into production classifications. Unknown timeout charges retain their holds and bounded retry/admission controls remain in force. The cause of the subsequent provider latency recovery is unknown; a longer client timeout is not evidence that provider inference became faster.

Keep this operational episode separate from classifier-quality changes. Report the final 40,000-ID audit only from its completed saved evaluation. For timing, use supervisor/process evidence for the whole hero run; the final stage's `run_summary.json` wall time is not the full-run duration. Do not revise the original pilot measurements.

## iCloud and local disk

macOS can return an empty read for an offloaded file even when its metadata reports a nonzero size. JSONL readers reject short reads. Release packaging compares archived byte counts to source sizes and preserves the previous archive if a read fails.

The local execution mirror keeps source code and input CSVs resident outside iCloud. Closed pilot call evidence is copied only after byte-count, checksum and audit-count validation. Frozen publication-support files are checked against their saved sizes and SHA-256 values before packaging. The authoritative checkpoints, result database and spending ledger retain their original locations. Never reset the spending ledger or run two supervisors concurrently.

Trace compaction checks byte counts, gzip integrity, parsed JSON, archive inventories and source read-back before removing redundant closed request/response pairs. Initial remote bundles were uploaded through the correct Berkeley account in Dia, downloaded again and SHA-256 verified. The connected Drive API belongs to the wrong account and must not be used.

After Dia's file picker stalled, `tools/github_trace_backup_guard.py` began using the **unpublished `hero-private-trace-backups` GitHub draft release** as the temporary private backup destination. It verifies the account, repository and draft state; scans for secrets; validates the nested ZIP/TAR inventories; and compares a downloaded asset's SHA-256 with the local receipt before cleanup. The draft must remain unpublished. These raw trace backups are not public grader evidence and must not be linked as public release assets.

The final trace inventory at 06:17:53 UTC records 18 private GitHub draft assets and five previously verified Drive bundles. The final-audit bundle was downloaded and SHA-256 verified, and no compacted TAR remained pending. However, 3,448 older offloaded request/response pairs and 38 request-only files remain local. Ten older receipts were offloaded and not reread by that inventory. This is verified final-audit-tail coverage, not a claim that every raw trace has a remote copy. Request-only attempts remain explicit; response files are not fabricated.

Local trace archives and redundant bundle/download bytes may be removed only after a verified remote copy exists. Receipts identify the actual destination (`github_draft` or Drive); archive manifests, verification receipts, checkpoints, the result database and the spending ledger remain local. This procedure never deletes the only verified copy.

## Final publication

The supplied checker reports `review_required` solely for 96 unavailable usage fields across 48 failed requests; all other checks pass. Its original output is preserved. The course contract permits clearly disclosed unavailable usage rather than invented values. A strict separate acceptance gate verifies that this is the only exception, requires the corresponding failed-call accounting, and writes `checker-acceptance.json`; it never changes unknown usage to zero or removes failed attempts. At completed inference, recorded usage was $35.319959027, the unknown-charge hold remained $1.563189415, and active reservations were zero. These are nominal usage and unresolved allowances, not reconciled cash charges.

After the documented checker acceptance gate, the supervisor imports the saved run into Postgres. The 700 MB storage limit is checked **inside the import transaction**, so an oversized import rolls back before becoming public. It then runs `tools/reconcile_hero_publication.py` against the public API. That tool verifies coverage, the seeded 40,000-ID audit, ranking, claims, recommendations, every issue-membership page, sampled original/alias/quarantine details and stable run identity. It uses read-only, signed-out requests with bounded retries.

The public release preserves `grading/`, `cost/`, `evals/` and `recovery/` evidence, including the selected cold/warm measurements, structured call logs, group/memo handoffs and actual recovery recording. Operational proofs are included separately. Raw trace backup bundles and private human annotations are excluded.

The aggregate human-reference evaluation is generated separately after final inference. It must be included in the final evidence package, with field-specific label coverage and its posthoc adjudication limitation, before documentation is finalized. The finalizer's completion status alone does not establish that this follow-up has occurred.

A failed publication can be resumed from saved artifacts without another enrichment pass. Once the full audit is saved, recover through finalization or offline `--package-only` as appropriate; do not repeat the supervisor's full-audit cost projection or paid stages merely to rebuild a ZIP. Offline packaging does not itself rerun the checker, import or API reconciliation. Only report completion after the hosted results, downloadable evidence, aggregate human evaluation and final documentation are reconciled.

## Final focused software and display checks

The final credential-free Python job passed 127 test functions plus 10 subtests (137 JUnit-reported cases), with zero failures, errors or skips. Its scope is synthetic operational regression tests, with fake HTTP transports and temporary databases, not a full historical-suite rerun or live provider evaluation. The release retains `validation/focused-tests.json` and `.txt`. The independent rerank, source selection and clean-release calculator receipts are alongside them in `validation/`.

The display deployment from `01527c3f10b58b7acd68ca0e3832f41ae5ddd6d5` passed remote TypeScript/build and 33 focused web tests. Five unauthenticated HTTP checks returned 200; browser inspection confirmed the hero counts, accounting, model-versus-human evaluation limits and original-review provenance dialog. See `web-deployment.json` and `validation/vercel-build.log`. The prior full member-pagination reconciliation applies to the unchanged database. No new hero sleep/wake measurement was performed; the pilot observation remains historical.

## Publication availability and timing scope

`publication-artifact-availability.json` identifies 19 verified resident snapshots used to recover publication from iCloud stalls, with no omitted proofs. Both initially stalled maintenance files were hydrated before the final package; original files remain retained. A separate 22-case packaging/gzip regression run passed after the final recovery hardening, recorded in `validation/packaging-recovery-tests.json`, which preserves the preceding seven-case check. These overlapping focused runs are not added to the earlier 137-case count as a new full suite. The final validation snapshot uses an exact ten-filename inventory, separately from the 19 operational artifact snapshots.

`operational-final.json` records 14,986.277779 seconds from the first cold-100 checkpoint at 02:20:33 UTC to initial publication at 06:30:20 UTC on October 21: approximately 4 hours 10 minutes. The interval includes hero candidates, pilots, confirmation, scaling, audit and recoveries, and excludes earlier project setup/experiments/labeling and approximately eight seconds of supervisor setup. Scaling starts at the 10,000-checkpoint log and took approximately four hours with cache reuse, not a cold-from-empty 200,000-review benchmark. Final documentation and release-refresh QA remain separate from that initial-publication endpoint.

The separate public release asset `publication-receipt.json` records the final archive hash, code and documentation commits, deployment identity and final QA timestamp. Keeping it outside the ZIP avoids a circular archive checksum; it does not redefine the initial-publication runtime in `operational-final.json`.
