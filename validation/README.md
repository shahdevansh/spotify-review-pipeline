# Implementation validation

These checks validate implementation behavior. They are not paid pilot results
or evidence of model accuracy.

| Check | Observed result |
|---|---|
| Full Python suite | 163 passed, 1 skipped; see `pytest.xml` |
| Real PostgreSQL suite, separately enabled | 14 passed |
| JavaScript cursor and public-metadata tests | 3 passed |
| Actual source checksums and profile | Matched supplied manifest |
| Selected cohort | 210,000 nonempty original IDs plus 13 empty source rows |
| Blind learning sample | 1,000 original IDs, 926 distinct texts; no golden IDs |
| Vercel production build | Successful compilation and TypeScript |
| Public page | HTTP 200, no authentication required |
| Five public API routes | HTTP 200 JSON with truthful database-unavailable state |
| Credential preflight | Both model keys and both database URLs absent |
| New paid model calls | 0 |

The PostgreSQL integration uses explicitly synthetic fixtures in a local
test database. It checks exact source preservation, cache-origin consistency,
claim reconciliation, idempotent import, transaction rollback, pagination, and
read-only access. Synthetic figures are not published as review findings.

The optional integration test in the standard Python run needs a test database.
Its skip is expected without `SPOTIFY_TEST_DATABASE_URL`; the separate enabled
run tested a real local PostgreSQL instance.

No real cold/warm costs, provider throughput, human-label accuracy, business
recommendations, hosted Neon storage measurements, or real interruption recording
exist yet. Those artifacts must come from the actual bounded pilot.

The JUnit file omits the local machine hostname and normalizes the checkout path;
test outcomes are unchanged.
