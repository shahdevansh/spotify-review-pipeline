# Hero run: storage, recovery and publication checks

The hero run uses 200,000 nonempty source reviews and 13 explicit empty-text quarantines. The final independent audit covers 40,000 original IDs. Model agreement is a diagnostic; it does not establish human accuracy. Private annotation files are excluded from the inference harness and public repository.

## Changes at the completed 60,000-review boundary

The model, prompts, routing policy and classification fingerprint remained unchanged. No requests were in flight during the maintenance boundary. The source run summary was preserved as checkpoint-60000.json before restarting.

- SQLite record, call and exact-text cache payloads use a versioned lossless zlib encoding. Readers accept both the original JSON strings and the compressed payloads. Table-by-table logical hashes verified the database compaction.
- Optional gzip_exports writes records, calls, verification and disagreement JSONL using atomic replacements. The decoded records are unchanged. Database import, grading, offline ranking, calculator replay and release packaging accept the compressed filenames. The unmodified course checker passed synthetic submissions in both formats.
- Provider budget checks use a denormalized provider tag maintained from the authoritative spend_provider mapping by SQLite triggers. All monetary amounts remain in the original integer nano-USD columns. Migration compared all original transaction fields and provider mappings exactly, retained a backup and checked database integrity. Global, run and provider caps still serialize in one transaction; unknown charges retain their reservations.
- Enrichment supports 32 workers under the existing 32 requests/second ceiling. Verification remains at eight workers. Concurrency is an operational setting and does not change classification cache identity.

## iCloud and local disk

macOS can return an empty read for an offloaded file even when its metadata reports a nonzero size. JSONL readers reject short reads. Release packaging compares archived byte counts to source sizes and preserves the previous archive if a read fails.

The local execution mirror keeps source code and input CSVs resident outside iCloud. Closed pilot call evidence is copied only after byte-count, checksum and audit-count validation. The authoritative checkpoints, result database and spending ledger retain their original locations. Never reset the spending ledger or run two supervisors concurrently.

Trace archives may be removed locally only after upload to the authorized private Drive folder, download read-back and SHA-256 verification. Archive manifests and verification receipts remain local. This procedure never deletes the only verified copy.

## Final publication

The supervisor requires the supplied checker to pass, imports the saved run into Postgres, checks database size, and runs tools/reconcile_hero_publication.py against the public API. That tool verifies coverage, the seeded 40,000-ID audit, ranking, claims, recommendations, every issue-membership page, sampled original/alias/quarantine details and stable run identity. It uses read-only, signed-out requests with bounded retries.

The release preserves grading/, cost/, evals/ and recovery/ evidence, including the selected cold/warm measurements and actual recovery recording. Operational proofs are included separately. A failed publication can be resumed from saved artifacts without making another enrichment pass. Only report completion after the hosted results, downloadable evidence and final documentation are reconciled.
