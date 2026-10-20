import { currentRun, readTransaction } from "@/lib/database";
import { apiResponse, json, noRun } from "@/lib/responses";
import { publicRunSummary } from "@/lib/public-data";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const empty = { run: null, source: null, evaluation: null, claims: [], storage: null, scope: null };

export async function GET() {
  return apiResponse(empty, () => readTransaction(async (client) => {
    const stored = await currentRun(client);
    if (!stored) return noRun(empty);
    const { rows: claims } = await client.query(
      "SELECT claim_id, issue_id, metric, value FROM spotify_claims WHERE run_id = $1 ORDER BY claim_id",
      [stored.run_id],
    );
    const { rows: sizes } = await client.query(`
      SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0)::text AS bytes
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = current_schema() AND c.relkind = 'r'
        AND c.relname IN ('spotify_runs','spotify_reviews','spotify_issues',
                         'spotify_membership','spotify_claims','spotify_recommendations',
                         'spotify_evaluation_reports')`);
    const bytes = Number(sizes[0]?.bytes ?? 0);
    const inputCount = Number(stored.summary.input_count ?? stored.imported_rows);
    return json({
      status: "ready",
      run: {
        ...publicRunSummary(stored.summary),
        run_id: stored.run_id,
        created_at: stored.created_at,
        imported_at: stored.imported_at,
        imported_rows: stored.imported_rows,
      },
      source: stored.source_profile ?? { total_rows: null, nonempty_rows: null, empty_rows: null },
      evaluation: stored.evaluation,
      claims,
      storage: {
        bytes,
        projected_bytes_210k: inputCount > 0 ? Math.ceil(bytes * 210_000 / inputCount) : null,
        projection_note: "Linear estimate from current table and index size; verify again at 10,000 reviews.",
      },
      scope: inputCount <= 1_000 ? "pilot" : inputCount <= 10_000 ? "development" : "selected-cohort",
    });
  }));
}
