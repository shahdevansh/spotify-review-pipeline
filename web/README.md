# Spotify review observatory

Next.js reads saved analysis results from PostgreSQL. It has no model SDK, provider
key, inference endpoint, or paid call path. Missing data is shown as unavailable;
there are no embedded example results.

## Current submitted run: hero-v1

The public dashboard now serves **200,000 completed nonempty reviews plus 13 empty
quarantines**, with a 40,000-review independent audit. The old pilot publication
and v5 evaluation examples below are retained as historical recipes; they do not
recreate the submitted hero run. See the [current results](../README.md) and
[verified final release](https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/hero-v1).

To inspect the saved hero data, use the public dashboard; no credentials or model
calls are needed. To reproduce the database on **your own fresh PostgreSQL database**,
first install the repository dependencies, verify the release checksum shown in
the root README, and extract its ZIP into `evidence/` at the repository root. The
release separates grading and run artifacts; assemble a working copy before import:

```sh
mkdir -p work/hero-import
cp evidence/grading/records.jsonl.gz evidence/grading/membership.csv \
  evidence/grading/ranking.csv evidence/grading/claims.csv work/hero-import/
cp evidence/issues.json evidence/recommendations.json work/hero-import/
cp evidence/run/run_summary.json evidence/run/configuration.json work/hero-import/
```

Validate the copied files offline, without a database connection or model calls:

```sh
python - <<'PY_VALIDATE'
from spotify_pipeline.database import load_run
bundle = load_run(
    'work/hero-import',
    ingestion_report='evidence/grading/ingestion.json',
    evaluation_path='evidence/evals/hero/evaluation.json',
)
assert bundle.run_id == 'run-07e2cb4b0e3d9be0'
assert len(bundle.records) == 200013 and len(bundle.issues) == 8
assert len(bundle.membership) == 87897 and len(bundle.claims) == 32
print('Hero artifact validation passed; no database changes.')
PY_VALIDATE
```

Then configure your new database's writer `DATABASE_URL` in the ignored root `.env`
and explicitly import. This command writes the database but makes no model calls:

```sh
python - <<'PY_IMPORT'
from dotenv import load_dotenv
from spotify_pipeline.database import import_run
load_dotenv('.env', override=False)
print(import_run(
    'work/hero-import',
    ingestion_report='evidence/grading/ingestion.json',
    evaluation_path='evidence/evals/hero/evaluation.json',
    max_storage_bytes=700_000_000,
))
PY_IMPORT
```

The importer creates tables from `web/database/schema.sql` and switches the saved run atomically;
the size gate rolls back an oversized import. It must be run from this repository
checkout. Keep the published source artifacts unchanged. For the web deployment,
create a dedicated reader role using the grants below, set its server-only
`DATABASE_READONLY_URL`, and deploy `web/` to Vercel. Human-reference evidence remains
a separately versioned, run-bound publication; the old `pilot_audit` example below
is not the hero human report.

## Local preview

```sh
cd web
npm ci
cp .env.example .env.local
# Set DATABASE_READONLY_URL to the database connection string, or leave it unset
# to inspect the honest "results not available" state.
npm run dev -- --port 3017
```

The application runs without database credentials and displays setup status.
With a configured database it queries the current published run. API responses
use `Cache-Control: no-store` so they reflect a newly imported run immediately.

## Publish a saved run

From the repository root, call `spotify_pipeline.database.import_run` with the
saved run directory, a writer connection string through `DATABASE_URL`, and the
full-source ingestion report. The CLI exposes the same operation as `publish-data`:

```sh
spotify-pipeline publish-data --run runs/pilot/1000 \
  --ingestion data/ingestion_report.json
```

The Python interface is:

```python
from spotify_pipeline.database import import_run

result = import_run(
    "runs/pilot/1000",
    ingestion_report="data/ingestion_report.json",
    evaluation_path="runs/pilot/1000/evaluation.json",  # optional legacy measurements
)
```

`load_run` checks the same artifacts offline. Before opening a connection, the
importer validates shared record types, exact source hashes, quote containment,
direct cache provenance, complete complaint/cancellation membership, reproduced
ranking sums and order, and recommendation references. It then creates the
schema, bulk-copies reviews and membership, and switches the current run within
one transaction. A failed import rolls back without replacing visible results.
Reimporting the same run is idempotent before versioned evaluation is published;
older run IDs remain as history. A run with an immutable evaluation report cannot
be deleted or replaced. Publish changed analysis under a new run ID. The
evaluation foreign key deliberately blocks replacement instead of silently
discarding the audit trail.

The full source remains in the local ingestion ledger. The hosted database stores
the selected analysis input and its persisted results, with separate source and
selection counts.

## Historical pilot aggregate publication

This older v5 recipe requires local pilot evidence under `runs/pilot/1000`; those
ignored files are not part of a clean clone or the hero release. It does not
reproduce the final hero audit or human-reference publication. Use the current
hero import recipe above for the submitted run. The former
`web/scripts/publish_evaluation.py` wrapper is not distributed; the supported
module interface, for users who retain the historical pilot inputs, is:

```python
from pathlib import Path
from spotify_pipeline.evaluation_publication import build_pilot_audit

root = Path.cwd()
report = build_pilot_audit(
    root / "runs/pilot/1000",
    project_root=root,
    output_path=root / "evals/dashboard/pilot-v5-audit-v1.json",
)
```

After reviewing that report, publish it explicitly with a writer connection:

```python
import os
from spotify_pipeline.evaluation_publication import publish_evaluation_report

receipt = publish_evaluation_report(
    report,
    database_url=os.environ["DATABASE_URL"],
    project_root=root,
)
```

Publication validates the strict aggregate-only schema, source artifact hashes,
and the saved source/classification identity against the existing database run.
It acquires the same transaction lock as the analysis importer, creates the
evaluation table, and inserts an immutable report without switching the current
run. An identical publication is idempotent; conflicting content under the same
report ID fails. No model calls occur.

The initial report keeps human accuracy pending for two separate groups: the
mandatory 50 and the fresh 150 sampled from the unseen-text frame. Their pooled
200 are not a representative corpus estimate. Human answer rows never belong in
this public schema. Model agreement, AI-assisted inspection, synthetic behavior,
structural checks, ranking sensitivity, and the quality gate have distinct
typed fields. Project usage is a dated nominal ledger snapshot, not a current
cash or credit balance. Candidate comparisons require a separate approved,
source-bound report; an absent comparison is never interpreted as success.

## Read-only database access

Create a dedicated role in the database provider and give it only the following
grants after the schema exists (replace `dashboard_reader` with that role):

```sql
GRANT USAGE ON SCHEMA public TO dashboard_reader;
GRANT SELECT ON spotify_runs, spotify_reviews, spotify_issues,
  spotify_membership, spotify_claims, spotify_recommendations TO dashboard_reader;
-- After evaluation_schema.sql has created the optional evaluation table:
GRANT SELECT ON spotify_evaluation_reports TO dashboard_reader;
```

Set its URL as `DATABASE_READONLY_URL` in Vercel. `DATABASE_URL` is a development
fallback. Both variables are server-only and must never have a `NEXT_PUBLIC_`
prefix. Every API request additionally runs in a PostgreSQL read-only,
repeatable-read transaction with an eight-second statement timeout. Queries use
parameters; no public write endpoints are exposed.

## API

All envelopes contain `status: "ready" | "empty" | "unavailable"`. Missing
configuration and unpublished runs return honest 200 responses suitable for the
dashboard. A failed database connection/query returns 503, invalid pagination
returns 400, and missing review/issue IDs return 404.

| Route | Contents |
|---|---|
| `GET /api/overview` | Current run, source profile, evaluation, claims, measured table/index size and linear size projection |
| `GET /api/issues` | Saved baseline ranking and issue descriptions |
| `GET /api/issues/{id}/reviews?cursor=...` | At most 50 original records and an opaque continuation cursor |
| `GET /api/reviews/{id}` | Original text, labels, evidence, source hash and cache provenance |
| `GET /api/recommendations` | Saved recommendation document and evidence references |
| `GET /api/evaluation?run_id=...` | Recognized versioned evaluation reports bound to the requested run and configuration |

The evaluation route defaults to the current run. An explicit unknown run returns
404; a legacy database without the evaluation table returns an honest `empty`
response while the rest of the dashboard remains usable. The browser rejects
evaluation evidence whose run/configuration differs from the displayed analysis.

Review pagination uses a stable byte-order ID comparison. Cursors include their
run and issue; using a cursor after a new run is published returns 409 and asks
the browser to reload, preventing silent omissions or duplicate pages across
run changes.

## Verify and deploy

```sh
npm run test
npm run typecheck
npm run build
```

Deploy this `web` directory as a Next.js project on Vercel Hobby. Import the
validated pilot run into Neon before describing the deployment as an analysis
dashboard. A deployment without a connected imported run is only a working
application shell.

For live acceptance, reconcile `/api/overview`, `/api/issues`, and representative
review detail responses with the saved artifacts; page through a whole issue and
check unique IDs; confirm there are no model calls; let Neon sleep and retry.
The linear storage projection includes historical imported runs and is
conservative. Refresh the estimate at 10,000 reviews before expansion.
