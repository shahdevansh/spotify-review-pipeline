import { currentRun, publicReviewColumns, readTransaction } from "@/lib/database";
import { decodeCursor, encodeCursor } from "@/lib/cursor";
import { apiResponse, json, noRun } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const empty = { reviews: [], next_cursor: null };

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!id || id.length > 256) return json({ ...empty, status: "empty", message: "Invalid issue ID." }, 400);
  let cursor;
  try {
    cursor = decodeCursor(new URL(request.url).searchParams.get("cursor"));
  } catch {
    return json({ ...empty, status: "empty", message: "Invalid review cursor." }, 400);
  }
  if (cursor && cursor.issue_id !== id) {
    return json({ ...empty, status: "empty", message: "The cursor belongs to another issue." }, 400);
  }
  return apiResponse({ ...empty, issue_id: id }, () => readTransaction(async (client) => {
    const run = await currentRun(client);
    if (!run) return noRun({ ...empty, issue_id: id });
    if (cursor && cursor.run_id !== run.run_id) {
      return json({ ...empty, status: "empty", message: "A new run was published. Reload this issue to continue." }, 409);
    }
    const exists = await client.query(
      "SELECT 1 FROM spotify_issues WHERE run_id = $1 AND issue_id = $2", [run.run_id, id],
    );
    if (!exists.rowCount) return json({ ...empty, status: "empty", message: "Issue not found." }, 404);
    const { rows } = await client.query(`
      SELECT ${publicReviewColumns}
      FROM spotify_membership m JOIN spotify_reviews r
        ON r.run_id = m.run_id AND r.review_id = m.review_id
      WHERE m.run_id = $1 AND m.issue_id = $2
        AND ($3::text IS NULL OR m.review_id COLLATE "C" > $3 COLLATE "C")
      ORDER BY m.review_id COLLATE "C" ASC LIMIT 51`,
    [run.run_id, id, cursor?.review_id ?? null]);
    const reviews = rows.slice(0, 50);
    return json({
      status: "ready",
      run_id: run.run_id,
      issue_id: id,
      reviews,
      next_cursor: rows.length > 50
        ? encodeCursor({ run_id: run.run_id, issue_id: id, review_id: reviews[49].review_id })
        : null,
    });
  }));
}
