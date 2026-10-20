# Cost and runtime evidence

The implementation is `src/spotify_pipeline/cost.py`; editable dated prices are
in `config/rates.csv`. Running the calculator is offline and requires no API key.

**A real pilot has not yet been run.** No real pilot usage, charge, latency, or
model-quality measurements are claimed by this repository's initial version.
Missing measurements must not be read as zero cost or perfect accuracy.

After configuring provider credentials, explicitly execute:

```sh
spotify-pipeline pilot --execute-paid --budget 1.50
```

This produces separate cold/warm/500/1000 run evidence. The original 100 input
rows and their checksum are retained. Then replay the saved cold measurements:

```sh
spotify-pipeline replay \
  --calls runs/pilot/100-cold/calls.jsonl \
  --rates config/rates.csv --out cost/cold
spotify-pipeline replay \
  --calls runs/pilot/100-warm/calls.jsonl \
  --rates config/rates.csv --out cost/warm
```

The replay report distinguishes known billed subtotals from complete charges,
raw provider usage from estimates, result caching from provider prompt caching,
measured wall time from summed request durations, and one-time grouping/memo
work from per-record work. Uncertain timeout charges remain unresolved.

For final submission, preserve `pilot_records.jsonl`, `pilot_calls.jsonl`,
usage/rates, report, and replay instructions here, or supply them in a clearly
linked release asset. Do not create empty or synthetic usage files to stand in
for those real measurements.

The test suite exercises rate doubling, volume changes, partial usage,
conservative projections, cached-input arithmetic, reasoning-token handling,
and fixed-overhead accounting with explicitly synthetic fixtures.
