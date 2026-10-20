export type ModelRole = {
  role: string;
  model: string;
  provider: string | null;
  reasoning: string | null;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

/** Resolve the saved configuration without inferring a host from a model namespace. */
export function savedModelRoles(settings: unknown): ModelRole[] {
  const config = record(settings);
  const models = record(config.models);
  const providers = record(config.providers);
  const efforts = record(config.reasoning_effort);
  const ordered = ["enrich", "fallback", "verify", "group", "memo"];
  const roles = [...ordered, ...Object.keys(models).filter((role) => !ordered.includes(role))];
  return roles.flatMap((role) => typeof models[role] === "string" ? [{
    role,
    model: models[role] as string,
    provider: typeof providers[role] === "string" ? providers[role] as string : null,
    reasoning: typeof efforts[role] === "string" ? efforts[role] as string : null,
  }] : []);
}

/** A successful model comparison never establishes human evaluation completion. */
export function hasCompletedHumanEvaluation(evaluation: unknown): boolean {
  const report = record(evaluation);
  return report.human_ground_truth === true && report.status === "evaluated";
}

/** Put comparable measurements ahead of diagnostic metadata in the compact panel. */
export function evaluationMeasurements(evaluation: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!evaluation || evaluation.comparison_type !== "independent_model_agreement") return evaluation;
  return {
    compared_reviews: evaluation.verified_count,
    comparable_reviews: evaluation.comparable_count,
    final_disagreements: evaluation.disagreement_count,
    initial_disagreements: evaluation.initial_disagreement_count,
    fallback_reviews: evaluation.fallback_used_count,
    final_model_agreement: evaluation.field_agreement,
    initial_model_agreement: evaluation.initial_model_field_agreement,
    severity_mean_absolute_difference: evaluation.severity_mean_absolute_difference,
    sentiment_mean_absolute_difference: evaluation.sentiment_mean_absolute_difference,
  };
}
