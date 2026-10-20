import { currentRun, publicReviewColumns, readTransaction } from "@/lib/database";
import { apiResponse, json, noRun } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const empty = { review: null };

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!id || id.length > 512) return json({ ...empty, status: "empty", message: "Invalid review ID." }, 400);
  return apiResponse(empty, () => readTransaction(async (client) => {
    const run = await currentRun(client);
    if (!run) return noRun(empty);
    const { rows } = await client.query(
      `SELECT ${publicReviewColumns} FROM spotify_reviews r WHERE run_id = $1 AND review_id = $2`,
      [run.run_id, id],
    );
    if (!rows.length) return json({ ...empty, status: "empty", message: "Review not found in the published run." }, 404);
    return json({ status: "ready", run_id: run.run_id, review: rows[0] });
  }));
}
