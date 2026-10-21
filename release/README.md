> **Historical first-1,000 release guide.** This page documents `v0.1.0-pilot`; its future-scope and blank-label statements describe that release. The [current project README](../README.md) links the separate hero-v1 evidence ZIP for 200,000 completed nonempty reviews and 40,000 independent audits.

# First-1,000 review learning release

**This package contains 1,000 completed development reviews. The 210,000-review cohort is a future target, not a completed run.**

The 100 cold/warm, 500, and 1,000 checkpoints overlap. Do not sum their record counts as unique coverage.

| Checkpoint | Completed inputs | Nominal API USD | Measured wall seconds |
|---|---:|---:|---:|
| 100-cold | 100 | 0.00654034 | 39.803415499998664 |
| 100-warm | 100 | 0.0 | 0.07851741699778358 |
| 500 | 500 | 0.015570362 | 73.48146516700217 |
| 1000 | 1000 | 0.096661512 | 335.3336921670016 |

**The 50 human-label rows are blank. No human golden-set accuracy is established by this release.**
Open `evals/golden-labels.html` to supply independent judgments; the worksheet contains no model predictions.

The genuine live synthetic smoke test reports `model_behavior_passed=false` and `operational_passed=true`. See `evals/synthetic-live/v5-live-001/safety_report.json` and `SUMMARY.md` for case-level injection outcomes and planted-error detection results. These synthetic cases are excluded from business aggregates and do not establish population accuracy or broad robustness.

Both unmodified course-checker reports are preserved with their actual statuses:
- `validation/checker_pilot.json`: `review_required`; warnings: resume_call_evidence × 1, resume_snapshot_mismatch × 1, unreadable_file × 1.
- `validation/checker_recovery500.json`: `review_required`; warnings: invalid_usage × 2, reprocessed_checkpoint × 2.
Full selected-ID coverage does not erase execution-evidence warnings. The 1,000 run has no interruption-before snapshot; the separate recovery run retains cancelled-call unknown usage and resumed fallback overlap. No checkpoint or usage evidence was invented to silence these warnings.

## Evidence map

- `runs/pilot/`: original saved records, attempted calls, configurations, verification, role handoffs, ranking and memos.
- `cost/measured-100/`: immutable cold/warm calculator package and standard-library offline replay.
- `config/`, `prompts/`, `validation/`, `docs/`, `evals/`: frozen settings, tests, inspected failures and scope limitations.
- `data/learning_1000.csv` and `data/source/`: the learning input, unchanged fixed 100/500 inputs, and official source manifest.
- `data/ingestion.json` and the expanded ingestion/selection manifests: profiling of the entire original 660,622-row source.
- `src/spotify_pipeline/`, `tests/`, `tools/`: implementation and offline reproduction helpers.
- `web/`: dashboard/backend source, dependency lockfile, database schema, and blank environment template.
- `runs/recovery-nebius-v5/` and its adjacent `.cast`: actual interruption/resume evidence; `runs/concurrency-100-w4/` and its recording: matched-input concurrency measurement.
- `grading/`: standardized grading export for the declared first-1,000 scope. That run was not interrupted; an absent before-interruption checkpoint is not fabricated.
- `runs/recovery-nebius-v5/grading/`: separate 500-review recovery export, with its own declared scope.
- `release/ledger/`: sanitized read-only spending snapshot, including unknown charges and reservations.
- Earlier screening, probes, and failed experiments are retained under their original `runs/` names; they are not additional completed pilot coverage.

## Spending and uncertainty

Global ledger: 268 attempts, $0.214957094 recorded charges, $0.016446200 unknown-charge holds, and $0.000000000 unsettled reservations.
The ledger includes historical work. It must not be added to checkpoint totals. Unknown holds were preserved; this package did not clear, reconcile, or otherwise mutate the ledger. Nominal usage cost is distinct from cash outlay.

## Offline replay and integrity

From the extracted package root:

```sh
python tools/package_pilot.py replay --package cost/measured-100 --out cost/replay
python tools/package_learning.py verify --archive /path/to/spotify-learning-1000.tar.gz
```

`release/inventory.json` lists each payload's byte length and SHA-256. `release/SHA256SUMS` also covers the inventory. Tar metadata and gzip timestamps are deterministic. The archive itself has a separate external manifest with its checksum.
Source snapshot mode: `apfs-clone`. APFS-clone mode, when selected, reads byte-identical temporary clones using macOS clonefile (or cp -c if the native symbol is unavailable) with up to 16 workers to avoid macOS source-path read stalls; the original files remain untouched, source identity guards still apply, and clones are deleted.
Metadata-only transitions are accepted only after independent captures have identical bytes and a stable final size/stat. Content changes fail the build. Transition counts are recorded in the inventory and external manifest.

The archive deliberately excludes credentials, populated environment files, SQLite databases/caches, dependency directories, the raw 660,622-row CSV, and the unclassified selected 210,000-review input. Source-file checksums preserve dataset identity.
Credential values available from the local environment and `.env` were scanned in every packaged payload before archiving. This is a byte-level credential check, not a claim that arbitrary binary pixels or unknown secrets were inspected.

Model-to-model agreement and agent-assisted qualitative inspection are not human ground truth. Use the saved failure analysis and expansion decision before authorizing a larger run.
