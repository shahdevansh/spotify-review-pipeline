# Reproducing the hero run and inspecting its evidence

This guide contains the setup, exact commands, accounting definitions, and saved proofs behind the [project README](../README.md). The public result is the frozen `hero-v1` run, identified as `run-07e2cb4b0e3d9be0`, with classification configuration `spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a`. The verified inference code revision was `b354b75b95570e7485192011f5de89f0104c19de`; subsequent reference and documentation changes do not change its predictions.

## Environment and source

The project requires Python 3.11 or later and Node.js 22 or later for the dashboard. Dependencies are pinned in [uv.lock](../uv.lock) and [web/package-lock.json](../web/package-lock.json).

```sh
uv sync --frozen --extra dev --link-mode copy
source .venv/bin/activate
```

A fresh committed-source installation using CPython 3.13.11 installed 21 locked packages in a new resident environment. Calculator replay and full saved-output reranking passed with credentials unset, socket connections blocked, and no `PYTHONPATH` override. The [installation log](../evals/submission-readiness/fresh-resident-install.log) and [reproduction receipt](../evals/submission-readiness/fresh-resident-repro.json) record the result. The earlier Documents/iCloud installation encountered an import-path problem, which remains in the evidence.

Offline inspection, calculator replay, ranking, and the course checker require no API credentials. Paid execution requires ignored `.env` values based on the blank [.env.example](../.env.example): `OPENAI_API_KEY` for Decisions and `NEBIUS_API_KEY` for LLM work. `DATABASE_URL` is needed only for database publication, while the deployed API uses a server-side read-only connection. Credentials are excluded from Git and release artifacts.

Download the instructor's [complete dataset ZIP](https://drive.google.com/file/d/1P0rUoAS_wVjp3BYKqXMEyD4u0uJP1Bvf/view) and extract its eleven files into `data/source/`. The source is the course's historical May 2022 to November 2023 extract of BwandoWando's Spotify Google Store reviews, published as CC0. Its CSV is excluded from the repository and has this SHA-256:

```text
1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6
```

Recreate the selected cohort without model calls:

```sh
spotify-pipeline prepare --target 210000
python -c 'from tools.run_hero import prepare; print(prepare())'
```

The first command verifies the source files and creates the original 210,000-review SHA-256-ordered cohort. The second selects its first 200,000 nonempty reviews and adds all 13 empty source records, writing `data/hero_200000.csv`. Offline reconstruction from the complete source reproduced the exact selected CSV bytes, whose SHA-256 is:

```text
9ba77c9312b4c11146f3303eecdcd4dd3a92a50ae32244e31dbb81e89fc3cd5b
```

Original six-field strings and the supplied row-hash convention are preserved. Missing app version alone does not remove a review, and unselected source IDs remain outside the declared classification scope.

## Release files and integrity

Download the [hero-v1 release](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1) and extract `spotify-hero-evidence.zip` into `evidence/`. The archive contains 118 members and is 77,788,263 bytes, with SHA-256 `950fe1f6fcb1b53a3cc6ce634b071411669b930e5aba05f0c623ea871947049d`. Its separate [publication receipt](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/publication-receipt.json) identifies the code, deployment, final checks, and archive checksum.

The [submission supplement](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-submission-supplement.zip) adds fresh setup and replay checks, a fixed-input identity sidecar, frozen-model synthetic tests, and the earlier partial reference. The [golden review ZIP](https://github.com/shahdevansh/spotify-review-pipeline/releases/download/hero-v1/spotify-golden-review-set.zip) contains the completed comparison with updated report wording, while the earlier course-reference v3 archive remains available as a historical snapshot. These presentation changes preserve the original hero archive and every reference value. The [current reference](../evals/human-reference-v3/) is the appropriate source for present golden-set results, and the [v3 publication receipt](../evals/submission-readiness/course-reference-v3/receipt.json) records the original validation and dashboard publication.

Paths beginning `grading/`, `run/`, `handoffs/`, `validation/`, or `recovery/` below refer to files inside the extracted hero archive unless linked directly to the repository. Its root `cost/` directory preserves the selected cold-100 measurement, with warm measurements in `cost/warm100/`.

## Calculator replay and deterministic ranking

Reprice the measured cold-100 calls with explicit hero projection settings:

```sh
python - <<'PY'
from pathlib import Path
from spotify_pipeline.cost import calculate_cost
report = calculate_cost(
    Path('evidence/cost/pilot_calls.jsonl'),
    Path('evidence/cost/rates.csv'),
    output_dir=Path('work/hero-cost-replay'),
    selected_reviews=200000, selected_unique_texts=152363,
    verification_fraction=.20, fallback_fraction=.15,
    spending_limit_usd=48,
)
print(report['measurements'])
PY
```

Repeat using `evidence/cost/warm100/` to inspect the warm run. The historical generic CLI defaults describe an earlier experiment, so these explicit projection arguments are intentional. Editing a copy of `rates.csv` allows price sensitivity checks: doubling API rates doubles the API subtotal without changing measured time or local costs, and changing projected volume leaves pilot measurements unchanged. Five replay invariants passed; the archive retains `evals/hero-pilot/replay-validation.json` and `validation/clean-release-calculator.json`. See the [calculator guide](../cost/hero-replay.md) for additional context.

Recreate the ranking from a working copy of the saved records and membership:

```sh
mkdir -p work/hero-rerank
cp evidence/grading/records.jsonl.gz evidence/grading/membership.csv work/hero-rerank/
spotify-pipeline rerank --run work/hero-rerank
cmp evidence/grading/ranking.csv work/hero-rerank/ranking.csv
cmp evidence/grading/claims.csv work/hero-rerank/claims.csv
```

The baseline is `priority_score = severity_sum`, ordered by descending score and then ascending issue ID. Each complaint or cancellation belongs to one primary-topic issue. Original review counts include exact-text aliases, and mean severity uses decimal half-up rounding to six places. The model-generated issue descriptions never alter membership. An independent Counter/Decimal implementation reproduced all 87,897 memberships, eight rankings, and 32 numerical claims byte for byte; `validation/offline-validation.json` records that check.

The saved ranking checksum is `9e0952b616c37faf297cf977c2ec5a881c20a495205d9562c5dd0097b6299f27`, and the claims checksum is `1fe408f1e7da701f8b2595962a4e20a747272b712b40427c26fd403e1f860dd5`. These checks establish arithmetic consistency on the frozen predictions. Label quality is evaluated separately in the model audit and golden review set.

## Course checker and the recorded exception

After recreating the selected CSV, run the unchanged supplied checker:

```sh
python vendor/course/check_submission.py reference \
  --full data/source/spotify_reviews_18months.csv \
  --analysis data/hero_200000.csv --out work/hero-reference.json
python vendor/course/check_submission.py check \
  --reference work/hero-reference.json --submission evidence/grading \
  --out work/hero-self-check.json
```

Its output remains `review_required` because 48 failed requests lack two token-usage fields each, leaving 96 missing fields. All other coverage, identity, membership, ranking, and numerical-claim checks pass. The [course grading contract](../vendor/course/GRADING_CONTRACT.md) allows unavailable usage to be disclosed in the README; missing usage is retained as unavailable rather than invented or removed.

The archive preserves both `checker.json` and `checker-acceptance.json`. The latter is a separate publication gate that accepts only the validated missing-usage exception. It does not change the course checker, its output, or the unresolved-charge hold. The original checker SHA-256 is `d60bd66d84922d934c65b3d42b2c7d36cc738e8c75e2d6f2b2f58bca3141c26d`.

## Paid execution and dashboard deployment

The staged supervisor requires an explicit paid-execution flag:

```sh
python tools/run_hero.py --execute-paid
```

The [supervisor guide](../HERO_RUN.md) explains checkpoint execution, role handoffs, spending admission, and recovery. Resume work with the same configuration and ledger, and run only one supervisor against a given state. A separate command supports a small arbitrary-input run:

```sh
spotify-pipeline run --execute-paid --input /path/to/reviews.csv \
  --config config/hero.json --out runs/custom --db data/custom.sqlite3 \
  --budget 1.50 --global-budget 48 --workers 1 --verify-count 20
```

The example's verification count is intended for a small controlled input. A new large run needs its own volume, audit, cost, and concurrency plan. The hero's frozen [configuration](../config/hero.json), [labels](../config/labels.json), and [prompts](../prompts/) make the executed settings inspectable.

The application in [web/](../web/) runs on Vercel and reads Neon Postgres through a read-only API. Its build commands are:

```sh
cd web
npm ci
npm run build
vercel deploy
```

Provision the database and configure the server-side `DATABASE_READONLY_URL` using the [web setup guide](../web/README.md). The pipeline writer connection is used for imports only. Publication checks the 700 MB limit inside the import transaction, rolling back if the gate fails. The final import occupies 269,041,664 bytes and contains 200,013 records and eight issues.

The original final reconciliation made 1,784 unauthenticated GET requests without retries. It compared all 87,897 issue members across 1,761 pages, eight rankings, 32 claims, recommendations, and stable run identity against saved outputs. Nineteen sampled detail records covered original, alias, and quarantine provenance; non-issue detail endpoints were sampled rather than exhaustively checked. The archive's `database-publication.json` and `publication-reconciliation.json` preserve these results. The later golden-reference display update passed 39 web tests and a production build, with [its receipt](../evals/submission-readiness/course-reference-v3/receipt.json) and [rendered dashboard](../evals/submission-readiness/course-reference-v3/dashboard.png) saved in the repository. The database sleep/wake check belongs to the earlier pilot, and no new hero sleep/wake result is claimed.

## Accounting, elapsed time, and recovery

At the completed hero snapshot, project-wide recorded usage was $35.319959027 and the unresolved-charge hold was $1.563189415, totaling $36.883148442 with no active reservations. A subsequent frozen-configuration synthetic check recorded $0.005504154, bringing the later project total to $35.325463181 plus the same hold, or $36.888652596. These values price recorded provider usage and reserve uncertain charges; they do not claim reconciled invoice totals. The operational admission ceiling was $48 within the $50 project budget, and hosting used free plans.

Accounting scopes differ intentionally. The completed hero run itself recorded 154,595 attempts, 56 failed attempts, and nominal usage of $33.782901124. The project-wide inference snapshot included earlier experiments and recorded 159,820 attempts. The grading export contains 156,446 call rows because it also retains historical cache-origin evidence; summing those rows as newly billed work would double-count some calls. The supplied checker finds 48 failed requests without usage in that export. `run/run_summary.json` contains the original snapshot, while the separate [frozen safety evidence](../evals/submission-readiness/frozen-safety/) documents the later synthetic run.

The measured workflow starts with the cold-100 checkpoint at 2026-10-21 02:20:33 UTC and ends with initial public release at approximately 06:30:20 UTC, totaling 14,986.278 seconds. It includes the candidate, pilot, confirmation, scaling, recovery, final audit, and first publication. Earlier project setup, previous experiments, labeling, approximately eight seconds of supervisor setup, and later release-refresh review are outside this boundary. Classification during scaling ran from 02:30:36 UTC to 05:29:20 UTC, taking 2 hours 58 minutes 44.807 seconds. Reused pilot caches mean the scaling result is not a cold-from-empty throughput benchmark, and the final stage's individual wall timer is not the entire workflow duration. `operational-final.json` preserves the timing anchors.

During the final audit, the first 17 successful full-GLM calls averaged 45.23 seconds, compared with 6.39 seconds across eight pilot calls, while 23 requests reached the old 60-second timeout. The audit was stopped, its 425 completed IDs verified in the task cache, and eight canceled requests retained as uncertain-charge holds. A tested operational change increased the Nebius timeout to 180 seconds while preserving request bodies and the frozen classification configuration. The resumed eight-worker audit completed all 40,000 comparisons. Later latency improved, but that temporal change does not establish that the timeout setting caused the provider to become faster.

The [operational recovery notes](hero-operational-recovery.md), recorded `recovery.cast`, and archive files `audit-timeout-stop.json`, `audit-timeout-repair.json`, and `audit-timeout-post-restart-timing.json` retain the recovery evidence. Compression, indexed spending admission, and a resident runtime also addressed disk pressure and offloaded-file stalls without changing labels or cache identity.

## Test evidence and trace coverage

The final focused Python check passed 127 test functions and 10 subtests, reported as 137 JUnit cases with no failures, errors, or skips. These were credential-free tests using synthetic data, fake HTTP transports, and temporary databases, rather than a rerun of every historical test. The archive retains `validation/focused-tests.json` and its log. A separate 22-case packaging/gzip regression run and five calculator invariants are reported separately to avoid adding overlapping tests into an inflated suite count.

The later [frozen safety check](../evals/submission-readiness/frozen-safety/) exercised nine nonempty synthetic reviews and one quarantine, including instruction-injection cases. It made eleven successful provider attempts, cost $0.005504154, and completed its ten predeclared cases. A planted-label copy was detected using cached independent judgments, and five offline failure simulations checked malformed output, transient failure, retry exhaustion, budget refusal, and empty input. These small checks support the tested behaviors and are excluded from business metrics; they do not establish general model robustness.

Structured call evidence and raw role handoffs are included for graders. Raw provider traces also have private backups with documented coverage limits: the final inventory records 18 private GitHub draft assets, five historically verified Drive bundles, and zero pending compacted TARs, while 3,448 older offloaded request/response pairs and 38 request-only files remain local. Complete remote backup of every raw trace is not claimed. `validation/trace-backup-inventory.json` preserves the inventory, and private backup locations are not public submission links.

For a review-level path from source text through prediction, disagreement, membership, and recommendation, inspect the [business audit](../evals/hero/business-audit.md), [editorial review](../evals/hero/editorial-review.json), and [decision memo](hero-decision-memo.md). The memo review changed presentation fields while leaving nine protected prediction, verification, membership, ranking, claim, and raw handoff artifacts unchanged. The [submission guide](../SUBMISSION.md) provides the rubric map without requiring readers to follow the operational history first.
