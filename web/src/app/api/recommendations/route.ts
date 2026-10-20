import { currentRun, readTransaction } from "@/lib/database";
import { apiResponse, json, noRun } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const empty = { document: null };

export async function GET() {
  return apiResponse(empty, () => readTransaction(async (client) => {
    const run = await currentRun(client);
    if (!run) return noRun(empty);
    const { rows } = await client.query(
      "SELECT document FROM spotify_recommendations WHERE run_id = $1", [run.run_id],
    );
    if (!rows.length) return json({ ...empty, status: "empty", message: "Recommendations have not been published for this run." });
    return json({ status: "ready", run_id: run.run_id, document: rows[0].document });
  }));
}
