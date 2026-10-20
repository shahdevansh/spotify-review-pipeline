# Offline cost and runtime replay

All amounts are USD; rates are editable per million billed units. This command makes no paid calls.

Measured inputs: 100; completed: 100; attempted calls: 0.
Nominal repriced API total: 0.0; known subtotal: 0.0; calls with unknown cost: 0.
Gateway reported actual debit: 0.0; surcharge breakdown: 0.0; unknown gateway debits: 0. These receipt amounts do not change when editable token rates change.
End-to-end elapsed seconds: 0.07851741699778358 (run_summary). Summed call seconds: 0.
Cost per 1,000 inputs: 0.0; cost per completed record: 0.0.

## Projections

| Scope | Scenario | Reuse | First pass | Nominal API USD | Including gateway uplift USD | Wall seconds | Budget exceeded |
|---|---|---|---:|---:|---:|---:|---|
| selected | base | True | 159657 | None | None | None | None |
| selected | conservative | True | 159657 | None | None | None | None |
| selected | base | False | 210000 | None | None | None | None |
| selected | conservative | False | 210000 | None | None | None | None |
| full | base | True | 484189 | None | None | None | None |
| full | conservative | True | 484189 | None | None | None | None |
| full | base | False | 660609 | None | None | None | None |
| full | conservative | False | 660609 | None | None | None | None |

Cold/warm and initial/resume breakdowns, stage metadata, source-linked rates, uncertainty, and calculation inputs are preserved in report.json and CSV files.

## Replay

From this report's folder, with the pipeline package installed, run:

```sh
spotify-pipeline replay --calls pilot_calls.jsonl --rates rates.csv --out replay
```

This folder contains byte-for-byte copies of the source calls, available review records, rates, and run summary. The summary preserves measured time, input checksum, and cache mode when replayed elsewhere.
Changing rates reprices usage. Changing target volumes only changes projections. No API key is required.

## Limits

- API cost is nominal usage repriced from editable rates; immutable gateway actual debits and fee breakdowns are reported separately.
- Nebius input with an unknown cache breakdown is priced at the published standard rate for all reported input; no cache discount or zero cache usage is invented.
- Existing credits do not make economic usage free. Gateway debits may consume prepaid or promotional credits and do not establish a new cash purchase.
- Missing gateway fee/debit evidence remains unknown. Budget projections add measured nonnegative gateway uplift only when reconciled; discounts are not extrapolated.
- Reservations and charge holds are estimates, not guaranteed cost bounds.
- Unknown usage is excluded from known subtotals, never assumed free; partial/unknown provider markers keep total charges unresolved even when some billing items are present.
- Unknown-charge holds cover entire attempts and are not added again to their known subtotals.
- Summed call durations are not elapsed wall time.
- Runtime projections use measured concurrency and linear workload extrapolation; they are not guarantees.
- Variable unit costs include all logged attempts and retries; fixed downstream overhead is counted once.
- No taxes, hosting charges, or unlogged API calls are inferred.
- Reports should use a single frozen configuration and a single cold run for projection calibration.
