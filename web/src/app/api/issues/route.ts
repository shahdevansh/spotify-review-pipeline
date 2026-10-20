import { currentRun, readTransaction } from "@/lib/database";
import { apiResponse, json, noRun } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const empty = { issues: [] };

export async function GET() {
  return apiResponse(empty, () => readTransaction(async (client) => {
    const run = await currentRun(client);
    if (!run) return noRun(empty);
    const { rows } = await client.query(`
      SELECT issue_id, name, description, rank, complaint_count, severity_sum,
             mean_severity::double precision, priority_score::double precision
      FROM spotify_issues WHERE run_id = $1 ORDER BY rank`, [run.run_id]);
    return json({
      status: rows.length ? "ready" : "empty",
      run_id: run.run_id,
      issues: rows,
      ...(rows.length ? {} : { message: "No ranked issues are available for this run." }),
    });
  }));
}
