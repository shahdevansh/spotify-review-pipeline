# V6 scaling and persistence audit

Date: October 20, 2026. **The current normal call-log path already appends incrementally. The genuine quadratic path is spending admission, which sums the ledger on every request.** At the tested sizes, these local costs are small relative to provider latency; memory, repeated transactions, and restart/export work deserve attention before a large run.

This is a read-only implementation audit plus isolated, synthetic storage benchmarks. No provider was instantiated, no inference request was made, and no production database or shared spending ledger was opened for writing. The frozen engine, storage, provider, and experiment-runner files were not changed. API cost was **$0**. No monetary rate was assigned to local CPU/disk time.

## What the implementation actually does

Let C be new API attempts, H historical attempts, U distinct texts, and N original reviews.

| Path | Current behavior | Complexity and implication |
|---|---|---|
| Attempt journal | `_invoke` saves a queued call in SQLite, updates it after completion, and appends one final JSONL line. | O(C) log bytes and transactions. There is no full JSONL rewrite per successful attempt. |
| Budget admission | `BudgetLedger.reserve` computes global and per-run `SUM(COALESCE(charged_nano,reserved_nano))` under `BEGIN IMMEDIATE`. | O(C² + CH) aggregate work. For C=48,000 and no history, the two sums visit approximately 2,303,952,000 rows in total. These are logical row visits, not necessarily physical disk reads. |
| Completed records | Each unique original is saved in its own transaction. `_materialize` subsequently reads and rewrites every selected completed row, including unchanged originals. | Linear, but many durable transactions. Approximately 6C + U + N transactions for successful LLM batches, before fallback and other operations. |
| Failure accounting | A terminal batch failure loads all calls and scans them for each failed review's attempt count. | O(FC) with bounded batch size, where F is failed batches; potentially quadratic during widespread failures. |
| Resume startup | Parses every `task-*.json` and exports all current-run calls. | O(C) restart work and many filesystem lookups. |
| Finalization | Exports current calls, loads all historical calls to select evidence, then reads current calls again for summary. | O(C+H) per checkpoint, with large intermediate Python lists. It happens at stage/session checkpoints, not every request. |
| Review grouping | Exact-text groups contain references to input rows. Searching each group's origin is bounded by that group's size. | Aggregate origin-search work is O(N), not an unrestricted scan of all reviews for every text. |
| Verification/fallback concurrency | Both `verify` and `_fallback` iterate batches with a direct `await` inside a sequential loop. Only primary enrichment uses the worker queue. | Increasing `workers` currently parallelizes first-pass classification, not these later passes. Their wall time must be projected independently. |

Source locations: [engine.py](../src/spotify_pipeline/engine.py), especially `_invoke`, `_materialize`, `summary`, and `finish`; [storage.py](../src/spotify_pipeline/storage.py), especially `BudgetLedger.reserve`, `ResultStore.calls`, and `save_record`.

## Bounded offline measurements

The benchmark ran on the local `/private/tmp` filesystem with SQLite WAL and `synchronous=FULL`, using the actual storage implementation. Each step had a hard 55-second limit; all completed. There was one observation per size. This is a storage microbenchmark, not a dedicated-host throughput or network benchmark.

Call fixtures contain ten synthetic IDs and average 1,608 serialized bytes. The call test performs two SQLite saves per call and opens/appends the journal once per completed call, matching the relevant persistence pattern. It does not include provider transport, raw request/response handoff files, pacing, task-cache writes, or the budget ledger; those costs must not be inferred from this row alone.

| Test | 100 items | 1,000 items | 10,000 items |
|---|---:|---:|---:|
| Call saves twice + append | 0.045 s | 0.357 s | 2.937 s |
| Atomic call snapshot export | 0.002 s | 0.023 s | 0.389 s |
| Ledger reserve + settle | 0.093 s | 0.424 s | 6.580 s |
| Initial record/cache saves | 0.017 s | 0.154 s | 1.228 s |
| Repeated record lookup + unchanged rewrite | 0.023 s | 0.089 s | 0.932 s |
| Atomic record export | 0.001 s | 0.009 s | 0.091 s |

The 10,000-call append file and exported snapshot were byte-identical at **16,080,000 bytes each**. The 10,000-record export was **6,497,780 bytes**. Parsing the 10,000 calls with `tracemalloc` enabled took 0.515 seconds and peaked at **90,503,444 bytes** of tracked allocations. Profiling adds overhead, so this parsing time is not an uninstrumented runtime estimate.

At 10,000 ledger rows, the last 100 reserve/settle pairs averaged **1.127 ms** each. Query plans confirm a full global table scan and a per-run indexed scan over all matching rows. A per-run index locates the rows but does not precompute their sum.

Raw results and reproducible synthetic fixture code:

- [Benchmark results](evidence/scaling-v6/results.json)
- [Existing v5 artifact size profile](evidence/scaling-v6/size_profile.json)
- [Offline benchmark](evidence/scaling-v6/benchmark.py)

Run the benchmark with the project's Python environment:

```bash
python docs/evidence/scaling-v6/benchmark.py
```

All generated databases remain in a fresh temporary directory. Rerun measurements are written separately from the preserved `results.json`. Fixture accounting amounts are synthetic; they are not real costs or changes to the project's spending ledger.

## What this means for a large run

The user-selected 210,000-review cohort contains 159,657 unique texts, implying approximately **15,966 first-pass requests at batch size 10**, before retries and downstream work. A full-source scenario with 484,189 unique nonempty texts would require approximately **48,419 such requests**. The 48,000-request scenario is consequently larger than the current 210,000-review target.

At 48,000 calls with the benchmark fixture shape:

- One append log is approximately **77.2 MB**. A checkpoint export writes another 77.2 MB; this is linear.
- A single fully parsed call list extrapolates to roughly **434 MB** of tracked allocation. The engine can simultaneously retain input rows, review groups, completed records, evidence calls, and a second call list. This is a memory concern even when export time is modest.
- Naively scaling only the measured quadratic ledger component from 10,000 to 48,000 gives approximately **152 seconds**. This is an illustration, not a measured forecast: it includes fixed/linear costs and assumes the same filesystem/cache behavior. It does not establish that admission will dominate an hours-long network run.

The existing v5 1,000-review evidence is larger than the synthetic call shape: call JSONL entries average **2,947 bytes**, while completed review entries average **954 bytes**. Handoff file-size averages are about **12.8 KB per request**, **4.8 KB per response**, and **5.2 KB per task**. Only file sizes were read for raw responses, not model reasoning.

Using those v5 averages illustratively, 48,000 calls would produce about **141 MB of call JSONL** and **1.10 GB across approximately 144,000 handoff files**. This excludes SQLite files, WAL growth, review exports, archives, and additional checkpoints. New models/prompts can change these sizes. Many small files may make restart and packaging slower than sequential byte throughput suggests.

Review JSONL alone extrapolates to about **200 MB for 210,000 rows** or **631 MB for 660,622 rows**, before database indexes, duplicate storage, v6 audit metadata, and provider artifacts. These byte estimates are not PostgreSQL size measurements or proof that a hosting limit will be met.

## Proposed changes after the experiment freeze

1. **Make admission counters constant-time without weakening accounting.** Keep immutable per-request reservations/settlements as the audit source. Add global and per-run integer counters updated in the same SQLite transaction as reserve/settle. Backfill by a verified one-time sum, compare counters against the journal, and fail closed on disagreement. Unknown reservations remain fully committed; settling known usage replaces, rather than adds to, the reserved commitment. Test concurrent admissions, process crashes, old holds, migration, and reconciliation.

2. **Persist a completed batch atomically.** Save its originals/cache entries together in one transaction after validation. This preserves the assignment's after-each-batch checkpoint guarantee while avoiding one durable transaction per review. Materialize aliases in bounded chunks; skip unchanged completed originals. Keep `FULL` durability.

3. **Retain append journaling and make checkpoints streamed.** The current append design is already appropriate. Treat SQLite as authoritative after a crash. Rebuild a canonical JSONL snapshot at explicit checkpoints/final export with an SQL cursor or bounded pages, not `fetchall` plus a full list. A versioned append event log can record queued/final attempt states, while the grading export contains one final row per attempt. Do not rewrite all history after every request.

4. **Index provenance and attempts.** Store request-to-review membership and task source references in SQLite. Query only calls needed by the selected configuration/run/evidence lineage; avoid parsing every historical call or every task handoff file. Keep raw handoffs available, potentially sharded or archived after finalization. Do not replace their provenance with fabricated cache-call entries.

5. **Separate lightweight progress from expensive exports.** Progress should use maintained counters and bounded queries. Full records/evidence exports should occur at declared durable checkpoints, after interruption, and at final reconciliation. Preserve the actual checkpoint snapshots used by the recovery demonstration.

6. **Bound parallelism for verification and fallback before a long production run.** Increasing primary workers alone cannot remove the sequential downstream time. After the frozen comparison, use a bounded queue/semaphore for these independent requests while retaining shared rate admission, per-request spending reservations, and cancellation semantics. Select the fallback candidates and quota deterministically before dispatch; freeze verification sampling and batch membership, and sort outputs deterministically after completion. Reuse the same original-text-only verifier inputs. Test coverage, quota, resume behavior, budget exhaustion, and cancellation under concurrency before measuring throughput.

The four-worker GLM experiment is explicitly a **first-pass-only** probe with fallback disabled. It must not be described as a fourfold end-to-end speedup. Full-run projections should sum measured/projected primary time, independently measured serial or parallel fallback time, verification time, and bounded grouping/memo overhead. A fallback proxy based on a different model or task must remain labeled as a proxy; the local storage benchmark does not validate it.

## Limits and release gate

These changes are proposals only. No frozen experiment implementation was modified. Before deploying them, preserve old artifacts, version operational behavior, run budget/concurrency/recovery tests, and repeat the 100/1,000/10,000 synthetic checks. Then measure the real 10,000-review checkpoint and actual database size before committing to large-scale inference.

Use the following provisional engineering triggers at that checkpoint. They are explicit operating targets, not thresholds derived from the small benchmark:

| Measurement | Trigger | Action before expanding |
|---|---|---|
| Process memory | Measured peak RSS exceeds the smaller of 2 GB or 25% of physical RAM, or a size-adjusted projection crosses it | Stream exports and reduce simultaneous full-data structures; rerun the checkpoint and measure RSS again. `tracemalloc` alone is insufficient because it excludes some native allocations. |
| Ledger admission | p95 reserve/settle latency exceeds 10 ms **or** 5% of the median provider request latency over the last 1,000 admissions | Implement and validate transactional counters before increasing request volume/concurrency. Track lock waits separately. |
| Local persistence capacity | An isolated representative persistence benchmark cannot sustain at least 10 times the planned aggregate provider request rate | Batch durable writes and investigate I/O before increasing workers. At a planned 2 requests/second, this requires at least 20 persisted requests/second; the 10,000-item microbenchmarks exceed that floor by a wide margin. |
| End-to-end throughput | Doubling workers gains less than 20% completed-review throughput, or increases timeout/429 frequency | Keep the lower worker count and inspect admission wait, API latency, and failure causes. Do not attribute a provider bottleneck to JSON logging. |
| Export/restart | A 10,000-review checkpoint takes more than 30 seconds to export/reopen, or measured scaling projects more than five minutes at the target | Stream filtered exports and index task/evidence provenance; do not add more frequent full snapshots. |
| Artifact growth | Projected deployment database exceeds the plan's 700 MB conservative threshold | Measure table/index sizes and change deployment storage or scope before upload. Local SQLite/raw-log sizes are not interchangeable with PostgreSQL size. |

The current evidence does **not** trigger an urgent per-request logging rewrite. The ledger has an unfavorable asymptotic form but remains fast in the 10,000-entry local test. Counter and export work should follow the frozen comparison, with changes justified by larger-checkpoint measurements and these bounds.

Existing offline tests already cover rate-doubling replay, portable evidence replay, known-zero `not_dispatched` calls, retained unknown holds, and raw-versus-audited flags across fallback and verification. These should remain release gates for any optimization: topic/intent/severity/sentiment and the raw provider flag must survive byte-for-byte or value-for-value, even when derived flags or storage layout change.

Confidence is **high** in the code-path and asymptotic findings, **moderate** in transfer of the local microbenchmark constants, and **low** in extrapolated full-run wall time or database size without a measured larger checkpoint.
