const RUN_FIELDS = [
  "run_id", "label_config", "input_count", "completed", "quarantined", "pending",
  "unique_texts", "cache_hits", "task_cache_hits", "requests", "attempts",
  "failed_attempts", "api_cost_usd", "api_cost_complete", "spending",
  "global_spending", "budget_usd", "global_budget_usd", "wall_seconds",
  "phase", "model_settings", "stages", "limitations",
] as const;

/** Only documented public metrics leave the database, never local run paths. */
export function publicRunSummary(summary: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(RUN_FIELDS.filter((key) => key in summary).map((key) => [key, summary[key]]));
}
