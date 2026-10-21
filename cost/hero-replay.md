# Replay the frozen hero cold/warm calculator

Install the repository package, download and verify the final hero release, and
extract it into `evidence/` at the repository root. The following is entirely
offline: it reads saved usage, rates and measurement metadata; it does not load
provider credentials or dispatch calls.

From the repository root, enter `evidence/cost/`, then run:

```sh
python - <<'PY_REPLAY'
from pathlib import Path
from spotify_pipeline.cost import calculate_cost
report = calculate_cost(
    Path('pilot_calls.jsonl'), Path('rates.csv'),
    output_dir=Path('replay-hero'),
    selected_reviews=200000, selected_unique_texts=152363,
    full_reviews=660609, full_unique_texts=484189,
    verification_fraction=.20, fallback_fraction=.15,
    spending_limit_usd=48, prior_spend_usd=0,
    conservative_multiplier=1.5, output_token_cap=8000,
    max_workers=16, empty_text_quarantines=13,
)
print(report['measurements'])
PY_REPLAY
```

The expected cold measurement is 100 completed reviews, 105 attempts,
$0.02360475 nominal API usage cost, and 41.903417875 seconds. Repeat the same
command from `evidence/cost/warm100/`: the expected warm result is 100 completed
reviews, zero attempts, $0 incremental API usage and 0.213740208 seconds.

These explicit arguments preserve the saved projection assumptions. The generic
`spotify-pipeline replay` defaults describe the earlier experiment and do not
reproduce the hero projection volume or audit/fallback rates. The saved
`max_workers=16` is a calculator scenario control; the final operational run used
32 enrichment workers and eight verifier workers. The one-worker cold pilot
measurement remains unchanged. Likewise `prior_spend_usd=0` reproduces this saved
incremental scenario, not the final project-wide ledger total.

Edit a copy of `rates.csv` to test pricing and pass its path. Doubling every API
rate with saved usage fixed must double the API subtotal, leaving measured wall
time and local-cost assumptions unchanged. Changing the selected volume changes
projections only. Local compute cost remains unmeasured/unknown. Use a new output
directory for each scenario; never edit the original measured call/record files.

The root README and final release contain measured usage, dated rate sources,
base/conservative reuse/no-reuse scenarios, budget warnings and replay-invariant
evidence. The historical files elsewhere under the repository's `cost/` directory
remain labeled as earlier experiments.
