> **Historical v5 pilot evidence.** The measurements and commands below describe the earlier Lightning/GPT-OSS experiment. Current hero-v1 uses Decisions plus Nebius GLM, 200,000 selected nonempty reviews and 20% independent verification. See the [current results and verified offline commands](../README.md), [hero pilot comparison](../evals/hero-pilot/report.md), and the final hero release's root `cost/` and `cost/warm100/` folders. The selected hero cold100 measured $0.02360475, 105 attempts and 41.9034 seconds; warm100 made zero calls at $0 in 0.2137 seconds. Do not use the old scope, models, budget or default projection settings below as hero-run results.

# Cost and runtime evidence

The implementation is `src/spotify_pipeline/cost.py`; editable dated prices are
in `config/rates.csv`. Running the calculator is offline and requires no API key.

The final v5 fixed-100 cold/warm measurement is complete and packaged in
[measured-100](measured-100/report.md) and [measured-100.zip](measured-100.zip).
The cold run completed 100 reviews and 10 blind verifications in 39.8034155 seconds,
using 8 calls with no failed attempts and $0.00654034 of nominal token-rate
consumption. The unchanged warm run completed in 0.0785174 seconds with 100
record-cache hits, 3 task-cache hits, zero new calls, and zero incremental API
consumption. Credit debit and cash expense have not been reconciled.

Actual probe and model-screening evidence remains separate from this
end-to-end fixed-100 measurement. The independent
[offline replay checks](../validation/cost_pilot_replay.json) verified rate
doubling and projection-volume invariance without provider credentials.

After configuring provider credentials, explicitly execute:

```sh
spotify-pipeline pilot --execute-paid --config config/nebius-pilot.json --budget 1.50
```

The official v5 experiment uses a fresh, explicitly named cache:

```sh
spotify-pipeline pilot --execute-paid --config config/nebius-pilot.json \
  --db data/pilot_v5_cache.sqlite3 --out runs/pilot --budget 1.50
```

Earlier failed experiments are retained separately, including
`runs/experiment-v2-cold-memo-failure` and
`runs/experiment-v4-gptoss-memo-failure`. Their calls are excluded from the official
measured package. Their ledger entries remain preserved. The final model
configuration uses Lightning for enrichment, GPT-OSS for fallback, verification
and grouping, and GLM-5.3-Flash for the memo.

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

After both fixed-100 stages are complete, package their saved evidence without
making API calls:

```sh
python tools/package_pilot.py package \
  --cold runs/pilot/100-cold --warm runs/pilot/100-warm \
  --out cost/measured-100 \
  --archive cost/measured-100.zip
```

The optional ZIP is a deterministic release asset containing the same package;
the command prints its SHA-256. The package includes the 100 cold records,
`pilot_calls.jsonl` containing actual cold and warm attempts only, editable
`rates.csv`, combined `usage.csv`, separate measured reports, configuration and
summary snapshots, the original fixed input and checksum, and the current
offline calculator source. Historical `evidence_calls.jsonl` cache-origin copies,
contract probes, and screening experiments are excluded from measured pilot cost.

Packaging rejects missing or incomplete stages, changed fixed inputs, differing
cold/warm configurations, warm enrichment calls, duplicate request IDs, or
unresolved current-stage usage. Prior experiments' holds remain visible in saved
global-ledger snapshots. Existing package, replay, and archive destinations are
never overwritten; choose a fresh path for a new measurement or scenario.

Replay the package without credentials:

```sh
python tools/package_pilot.py replay \
  --package cost/measured-100 --out cost/replay
```

The package is also standalone: after unzipping it, use Python 3.11+ and run
`python calculator/package_pilot.py replay --package . --out replay`.
This path needs only Python's standard library; it does not load `.env`, contact
providers, or require the pipeline's third-party dependencies.

To check editable prices, copy `rates.csv`, double its rates, and pass
`--rates /path/to/doubled_rates.csv --out cost/replay-double`. API repricing must
double while recorded wall time and local-compute assumptions stay unchanged.
Projection options such as `--selected-reviews`, `--selected-unique-texts`,
`--verification-fraction`, and `--spending-limit-usd` affect estimates only.
Use the separate cold/warm reports for measurements; the combined call log
does not define one shared elapsed time or 200 distinct input reviews.

Do not create empty or synthetic usage files to stand in for the real
measurements. An empty warm call log is valid only when a completed warm run and
its cached artifacts establish that no new calls occurred.

The test suite exercises rate doubling, volume changes, partial usage,
conservative projections, cached-input arithmetic, reasoning-token handling,
and fixed-overhead accounting with explicitly synthetic fixtures.
