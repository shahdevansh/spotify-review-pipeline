import { readTransaction } from "@/lib/database";
import { apiResponse, json } from "@/lib/responses";
import { emptyEvaluation, readEvaluation, requestedEvaluationRun } from "@/lib/evaluation-query";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  let requestedRun: string | undefined;
  try {
    requestedRun = requestedEvaluationRun(request.url);
  } catch {
    return json({ ...emptyEvaluation, status: "empty", message: "Invalid run_id parameter." }, 400);
  }
  return apiResponse(emptyEvaluation, () => readTransaction(async (client) => {
    const result = await readEvaluation(client, requestedRun);
    return json(result.body, result.httpStatus);
  }));
}
