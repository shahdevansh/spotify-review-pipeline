import { selectEvaluationReports, type EvaluationResponse } from "./evaluation-report.ts";

type QueryClient = {
  query(text: string, values?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
};
export const emptyEvaluation = {
  run_id: null, label_config: null, report: null, candidate_comparison: null,
};

export function requestedEvaluationRun(url: string): string | undefined {
  const value = new URL(url).searchParams.get("run_id");
  if (value === null) return undefined;
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(value) || /[\r\n]/.test(value)) {
    throw new Error("INVALID_RUN_ID");
  }
  return value;
}

/** All statements are read-only, with an explicit run/configuration binding. */
export async function readEvaluation(
  client: QueryClient, requestedRunId?: string,
): Promise<{ body: EvaluationResponse; httpStatus: number }> {
  const found = await client.query(
    requestedRunId
      ? "SELECT run_id, summary FROM spotify_runs WHERE run_id = $1 LIMIT 1"
      : "SELECT run_id, summary FROM spotify_runs WHERE is_current = true LIMIT 1",
    requestedRunId ? [requestedRunId] : [],
  );
  const run = found.rows[0];
  if (!run) return {
    body: { ...emptyEvaluation, status: "empty", message: "No matching published analysis run is available." },
    httpStatus: requestedRunId ? 404 : 200,
  };
  const summary = run.summary as { label_config?: unknown };
  const identity = { run_id: String(run.run_id), label_config: String(summary.label_config ?? "") };
  const table = await client.query("SELECT to_regclass('spotify_evaluation_reports') AS table_name");
  if (!table.rows[0]?.table_name) return {
    body: { ...emptyEvaluation, ...identity, status: "empty", message: "A versioned evaluation report has not been published for this run. Legacy measurements remain available in the overview." },
    httpStatus: 200,
  };
  const result = await client.query(
    `SELECT DISTINCT ON (kind) kind, schema_version, payload
       FROM spotify_evaluation_reports
      WHERE run_id = $1 AND label_config = $2
      ORDER BY kind, created_at DESC, report_id DESC`,
    [identity.run_id, identity.label_config],
  );
  const selected = selectEvaluationReports(
    result.rows as { kind: string; schema_version: string; payload: unknown }[], identity,
  );
  const ready = Boolean(selected.report || selected.candidate_comparison);
  return {
    body: {
      ...identity, ...selected, status: ready ? "ready" : "empty",
      ...(!ready ? { message: "No supported evaluation report matches this run and configuration." } : {}),
    },
    httpStatus: 200,
  };
}
