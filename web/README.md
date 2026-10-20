# Spotify review observatory

Next.js reads saved analysis results from PostgreSQL. It has no model SDK, provider
key, inference endpoint, or paid call path. Missing data is shown as unavailable;
there are no embedded example results.

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
spotify-pipeline publish-data --run runs/pilot1000 \
  --ingestion data/ingestion_report.json
```

The Python interface is:

```python
from spotify_pipeline.database import import_run

result = import_run(
    "runs/pilot1000",
    ingestion_report="data/ingestion_report.json",
    evaluation_path="runs/pilot1000/evaluation.json",  # optional
)
```

`load_run` checks the same artifacts offline. Before opening a connection, the
importer validates shared record types, exact source hashes, quote support,
direct cache provenance, complete complaint/cancellation membership, reproduced
ranking sums and order, and recommendation references. It then creates the
schema, bulk-copies reviews and membership, and switches the current run within
one transaction. A failed import rolls back without replacing visible results.
Reimporting the same run is idempotent; older run IDs remain as history.

The full source remains in the local ingestion ledger. The hosted database stores
the selected analysis input and its persisted results, with separate source and
selection counts.

## Read-only database access

Create a dedicated role in the database provider and give it only the following
grants after the schema exists (replace `dashboard_reader` with that role):

```sql
GRANT USAGE ON SCHEMA public TO dashboard_reader;
GRANT SELECT ON spotify_runs, spotify_reviews, spotify_issues,
  spotify_membership, spotify_claims, spotify_recommendations TO dashboard_reader;
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
