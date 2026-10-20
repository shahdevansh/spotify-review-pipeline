# Measured fixed-100 cold/warm pilot

Generated offline from saved evidence. No credentials or model calls are required.

Input checksum: `c884ac3b9be5066995d5063f96ad9af6e5e082975788c1684c4f6b6ea661dd0e`.
Frozen label configuration: `spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb`.

| Measurement | Inputs | Completed | Unique texts | Cache hits | Calls | Nominal API USD | Wall seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| cold | 100 | 100 | 100 | 0 | 8 | 0.00654034 | 39.803415499998664 |
| warm | 100 | 100 | 100 | 100 | 0 | 0.0 | 0.07851741699778358 |

## Configuration and stage evidence

The exact provider/model/effort, prompt/schema versions, batch sizes, worker counts, usage, failures, and retries are in each measurement's `report.json`, `stage_costs.csv`, and the byte-preserved `snapshots/` inputs. Combined `usage.csv` identifies its cold/warm measurement.
Warm downstream calls, if any, remain included in the warm cost. `pilot_calls.jsonl` contains only actual cold/warm attempts; cached historical evidence is not counted again.

## Offline replay

From the original package directory, using only Python 3.11+:

```sh
python calculator/package_pilot.py replay --package . --out replay
```

Edit a copy of `rates.csv` and pass `--rates path/to/edited_rates.csv` to reprice the unchanged usage. Projection flags change estimates only. Choose a new output path for every replay; existing evidence is never overwritten.

The replay command is also available from the repository as `python tools/package_pilot.py replay --package cost/measured-100 --out cost/replay`.

## Limits

- Model agreement is not human-label accuracy.
- Token-rate cost is economic consumption; verified invoice, credit debit, and cash expense are separate.
- Cold and warm wall times are separate measured active-session durations; summed call durations are not wall time.
- Cold and warm records are the same 100 original IDs, not 200 unique processed reviews.
- Projections are calibrated only from the cold run and are estimates, not execution evidence.
- Prior experiments and their retained uncertainty appear in saved global ledger snapshots but are excluded from pilot calls and measured pilot cost.
- Local-compute cost remains unknown unless an explicit hourly estimate is supplied.
