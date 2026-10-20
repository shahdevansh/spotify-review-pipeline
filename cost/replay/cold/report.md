# Offline cost and runtime replay

All amounts are USD; rates are editable per million billed units. This command makes no paid calls.

Measured inputs: 100; completed: 100; attempted calls: 8.
Nominal repriced API total: 0.00654034; known subtotal: 0.00654034; calls with unknown cost: 0.
Gateway reported actual debit: 0.0; surcharge breakdown: 0.0; unknown gateway debits: 0. These receipt amounts do not change when editable token rates change.
End-to-end elapsed seconds: 39.803415499998664 (run_summary). Summed call seconds: 39.64403191700694.
Cost per 1,000 inputs: 0.0654034; cost per completed record: 6.54034e-05.

## Projections

| Scope | Scenario | Reuse | First pass | Nominal API USD | Including gateway uplift USD | Wall seconds | Budget exceeded |
|---|---|---|---:|---:|---:|---:|---|
| selected | base | True | 159657 | 3.6369456058 | 3.6369456058 | 28571.682491082975 | False |
| selected | conservative | True | 159657 | 5.4536521087 | 5.4536521087 | 42847.899658769966 | False |
| selected | base | False | 210000 | 4.7268001 | 4.7268001 | 37371.046852584026 | False |
| selected | conservative | False | 210000 | 7.0884338499999995 | 7.0884338499999995 | 56046.946201021536 | False |
| full | base | True | 484189 | 11.0426217916 | 11.0426217916 | 86683.083739095 | False |
| full | conservative | True | 484189 | 16.562166387399998 | 16.562166387399998 | 130015.00153078802 | False |
| full | base | False | 660609 | 14.8619207296 | 14.8619207296 | 117519.42739154967 | False |
| full | conservative | False | 660609 | 22.2911147944 | 22.2911147944 | 176269.51700947 | True |

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
