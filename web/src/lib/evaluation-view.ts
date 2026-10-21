import {
  EVALUATION_SCHEMA_VERSION,
  reportMatchesRun,
  type ComparisonMetric,
  type EvaluationResponse,
  type PilotAuditReport,
} from "./evaluation-report.ts";
import type { HumanReferenceLink } from "./human-reference.ts";

const integer = new Intl.NumberFormat("en-US");
const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
const numberOrNull = (value: unknown): number | null => finite(value) ? value : null;

export function qualityPresentation(gate: PilotAuditReport["quality_gate"] | null, legacyEvaluation: unknown = null, humanReference: HumanReferenceLink | null = null) {
  if (gate?.status === "hold") {
    return {
      status: "hold" as const,
      tone: "warning" as const,
      label: "Quality hold",
      summary: gate.summary,
      provisional: true,
    };
  }
  if (gate?.status === "pass") {
    return {
      status: "pass" as const,
      tone: "success" as const,
      label: "Saved quality gate passed",
      summary: gate.summary,
      provisional: gate.recommendations_provisional,
    };
  }
  const comparison = gate ? null : legacyModelComparison(legacyEvaluation);
  if (comparison && finite(comparison.verified) && Number.isInteger(comparison.verified) &&
      comparison.verified > 0 && finite(comparison.comparable) && comparison.comparable > 0 &&
      comparison.comparable <= comparison.verified && comparison.metrics.some((metric) =>
        metric.unit === "fraction" && finite(metric.final_value) &&
        metric.final_value >= 0 && metric.final_value <= 1)) {
    return {
      status: "model_verification_available" as const,
      tone: "neutral" as const,
      label: humanReference?.reference_type === "ai_assisted_human_confirmed"
        ? "Model verification and AI-assisted, human-confirmed reference agreement published"
        : humanReference ? "Model verification and adjudicated human reference published" : "Model verification published · Human accuracy not evaluated",
      summary: humanReference?.reference_type === "ai_assisted_human_confirmed"
        ? `Saved independent model comparison covers ${integer.format(comparison.verified)} original review IDs. A separate posthoc reference includes AI-drafted labels explicitly reviewed and confirmed by the user. Neither result establishes blind population accuracy.`
        : humanReference
        ? `Saved independent model comparison covers ${integer.format(comparison.verified)} original review IDs. A separate sparse, posthoc adjudicated human reference is linked below. Neither result establishes blind population accuracy.`
        : `Saved independent model comparison covers ${integer.format(comparison.verified)} original review IDs. Human accuracy is not established by model agreement; no run-matched human benchmark is published here.`,
      provisional: true,
    };
  }
  return {
    status: "not_evaluated" as const,
    tone: "neutral" as const,
    label: "Quality not evaluated",
    summary: gate?.summary || "No matched quality decision has been published for this run.",
    provisional: true,
  };
}

export function humanBenchmarkSummary(human: PilotAuditReport["human"] | null) {
  const planned = human
    ? human.cohorts.reduce((sum, cohort) => sum + cohort.expected_count, 0)
    : null;
  return {
    status: "pending" as const,
    planned,
    label: human ? `Pending · ${integer.format(planned!)} planned reviews` : "Human benchmark not published",
    metric: "Not measured",
  };
}

/** Missing measurements and empty denominators must never become a measured zero. */
export function formatRatio(numerator: number | null, denominator: number | null): string {
  if (!finite(numerator) || !finite(denominator) || denominator <= 0) return "Not measured";
  return `${(100 * numerator / denominator).toFixed(1)}% · ${integer.format(numerator)}/${integer.format(denominator)}`;
}

export function comparisonMetricDisplay(
  metric: DisplayComparisonMetric,
  phase: "initial" | "final",
): { value: string; detail: string } {
  const value = metric[`${phase}_value`];
  const numerator = metric[`${phase}_numerator`];
  if (!finite(value) || !finite(metric.denominator) || metric.denominator <= 0) {
    return { value: "Not measured", detail: "No comparable measurement published" };
  }
  if (metric.unit === "fraction") {
    return {
      value: `${(100 * value).toFixed(1)}%`,
      detail: finite(numerator)
        ? `${integer.format(numerator)}/${integer.format(metric.denominator)}`
        : `Denominator ${integer.format(metric.denominator)} · numerator not published`,
    };
  }
  return {
    value: `${value.toFixed(3)} ${metric.unit === "severity_points" ? "severity" : "sentiment"} points`,
    detail: `${integer.format(metric.denominator)} comparable reviews`,
  };
}

export function confidencePresentation(available: number | null) {
  if (available === null || !finite(available)) {
    return { label: "Numeric confidence unknown", detail: "Signal availability was not published." };
  }
  if (available === 0) {
    return { label: "Numeric confidence unknown", detail: "No numeric confidence values were reported." };
  }
  return {
    label: "Numeric signals are uncalibrated",
    detail: `${integer.format(available)} records have a numeric signal; this is not a calibrated correctness probability.`,
  };
}

export function utcTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Timestamp not available"
    : `${date.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, "")} UTC`;
}

/** The endpoint validates publication; this bounded guard protects rendering unknown payloads. */
function renderableReport(value: unknown): value is PilotAuditReport {
  const report = object(value);
  if (report.schema_version !== EVALUATION_SCHEMA_VERSION || report.kind !== "pilot_audit") return false;
  const requiredObjects = ["coverage", "quality_gate", "human", "model_comparison", "routing",
    "inspection", "synthetic", "ranking_sensitivity", "structural", "cost_snapshot"];
  if (requiredObjects.some((key) => !report[key] || typeof report[key] !== "object" || Array.isArray(report[key]))) return false;
  const gate = object(report.quality_gate);
  const human = object(report.human);
  const model = object(report.model_comparison);
  const inspection = object(report.inspection);
  const ranking = object(report.ranking_sensitivity);
  const structural = object(report.structural);
  const routing = object(report.routing);
  const synthetic = object(report.synthetic);
  const costs = object(report.cost_snapshot);
  const arrays = [gate.reasons, human.cohorts, model.metrics, model.disagreements,
    inspection.cohorts, ranking.rows, structural.checks, report.limitations, report.artifact_refs];
  if (arrays.some((array) => !Array.isArray(array))) return false;
  const outcomes = ["passed", "failed", "not_available"];
  if (![synthetic.status, synthetic.operational_status, synthetic.model_behavior_status, structural.status]
    .every((status) => outcomes.includes(String(status)))) return false;
  return typeof report.run_id === "string" && typeof report.label_config === "string" &&
    typeof report.report_id === "string" && typeof report.generated_at === "string" &&
    typeof report.records_sha256 === "string" &&
    (report.limitations as unknown[]).every((item) => typeof item === "string") &&
    ["hold", "pass", "not_evaluated"].includes(String(gate.status)) &&
    typeof gate.summary === "string" && (gate.reasons as unknown[]).every((reason) => typeof reason === "string") &&
    human.status === "pending_labels" && typeof human.interpretation === "string" &&
    (human.cohorts as unknown[]).every((item) => {
      const cohort = object(item);
      return typeof cohort.id === "string" && typeof cohort.label === "string" &&
        finite(cohort.expected_count) && cohort.expected_count >= 0 && typeof cohort.sampling_note === "string";
    }) &&
    typeof model.verifier_provider === "string" && typeof model.verifier_model === "string" &&
    (model.metrics as unknown[]).every((item) => {
      const metric = object(item);
      return typeof metric.id === "string" && typeof metric.label === "string" &&
        finite(metric.denominator) && typeof metric.definition === "string" &&
        ["fraction", "severity_points", "sentiment_points"].includes(String(metric.unit));
    }) &&
    (model.disagreements as unknown[]).every((item) => {
      const metric = object(item);
      return typeof metric.id === "string" && typeof metric.label === "string" &&
        typeof metric.definition === "string" && finite(metric.count) && finite(metric.denominator);
    }) &&
    typeof routing.interpretation === "string" && typeof inspection.interpretation === "string" &&
    (inspection.cohorts as unknown[]).every((item) => {
      const cohort = object(item);
      return typeof cohort.id === "string" && typeof cohort.label === "string" &&
        typeof cohort.selection_method === "string" &&
        ["count", "supported", "concerns", "ambiguous", "concerns_flagged"].every((key) => finite(cohort[key]));
    }) &&
    typeof synthetic.scope === "string" && typeof ranking.interpretation === "string" &&
    (ranking.rows as unknown[]).every((item) => {
      const row = object(item);
      return typeof row.issue_id === "string" && finite(row.final_score) && finite(row.comparison_score);
    }) &&
    (structural.checks as unknown[]).every((item) => {
      const check = object(item);
      return typeof check.id === "string" && typeof check.label === "string" &&
        finite(check.passed_count) && finite(check.total);
    }) &&
    typeof costs.as_of === "string";
}

export function matchedEvaluation(
  response: EvaluationResponse | null,
  run: { run_id: string; label_config: string } | null | undefined,
): { report: PilotAuditReport | null; warning: string | null } {
  if (!run) return { report: null, warning: "No analysis run is loaded." };
  if (!response || response.status !== "ready" || !response.report) {
    return {
      report: null,
      warning: "Versioned pilot-audit overlay not published or unavailable. Saved model agreement and any linked human-reference report remain separate evidence.",
    };
  }
  if (response.run_id !== run.run_id || response.label_config !== run.label_config ||
      !reportMatchesRun(response.report, run)) {
    return {
      report: null,
      warning: "Evaluation identity mismatch: the response belongs to a different run or configuration. It has not been displayed.",
    };
  }
  if (!renderableReport(response.report)) {
    return {
      report: null,
      warning: "The saved evaluation report has an unsupported or incomplete schema. It has not been displayed.",
    };
  }
  return { report: response.report, warning: null };
}

export type LegacyComparison = {
  format: "hero_categorical" | "legacy_flag_inclusive";
  metrics: DisplayComparisonMetric[];
  verified: number | null;
  comparable: number | null;
  finalDisagreements: number | null;
  initialDisagreements: number | null;
};
export type DisplayComparisonMetric = Omit<ComparisonMetric, "denominator"> & { denominator: number | null };

/** Legacy endpoints may omit identity; a provided identity can never contradict the overview. */
export function responseMatchesRun(
  response: { run_id?: string | null; label_config?: string | null },
  run: { run_id: string; label_config: string },
): boolean {
  return (!response.run_id || response.run_id === run.run_id) &&
    (!response.label_config || response.label_config === run.label_config);
}

/** Recognized legacy fields only; arbitrary human reports are never flattened. */
export function legacyModelComparison(value: unknown): LegacyComparison | null {
  const legacy = object(value);
  if (legacy.comparison_type !== "independent_model_agreement") return null;
  const verified = numberOrNull(legacy.verified_count);
  const comparable = numberOrNull(legacy.comparable_count);
  const final = object(legacy.field_agreement);
  const initial = object(legacy.initial_model_field_agreement);
  const categoricalFields = ["topic", "intent", "severity"];
  const categoricalMarker = Array.isArray(legacy.limitations) && legacy.limitations.includes("Sentiment and review-flag agreement are not measured by this summary.");
  const heroCategorical = legacy.n === verified && finite(verified) && verified > 0 && Number.isInteger(verified) &&
    legacy.reference === "blind independent model; not human ground truth" && legacy.ground_truth === false &&
    categoricalMarker &&
    Object.keys(final).length === 3 && categoricalFields.every((field) => {
      const metric = object(legacy[field]);
      return finite(metric.matches) && Number.isInteger(metric.matches) && metric.matches >= 0 && metric.matches <= verified &&
        metric.denominator === verified && finite(metric.agreement) && metric.agreement === final[field] &&
        Math.abs(metric.agreement - metric.matches / verified) < 1e-10;
    });
  if (categoricalMarker && (!heroCategorical || !finite(comparable) || !Number.isInteger(comparable) || comparable < 0 || comparable > verified! ||
      !finite(legacy.disagreement_count) || !Number.isInteger(legacy.disagreement_count) ||
      legacy.disagreement_count < 0 || legacy.disagreement_count > verified!)) return null;
  const fields = [
    ["topic", "Topic exact agreement"],
    ["intent", "Intent exact agreement"],
    ["severity", "Severity exact agreement"],
    ["sentiment", "Sentiment exact numeric equality"],
    ["needs_review", "Review-flag exact agreement"],
  ];
  const metrics: DisplayComparisonMetric[] = (heroCategorical ? fields.slice(0, 3) : fields).map(([id, label]) => ({
    id, label, initial_numerator: null, final_numerator: heroCategorical ? numberOrNull(object(legacy[id]).matches) : null,
    denominator: verified, unit: "fraction",
    initial_value: heroCategorical ? null : numberOrNull(initial[id]), final_value: numberOrNull(final[id]),
    definition: heroCategorical
      ? "Exact categorical equality against the blind independent verifier. The numerator is the saved match count; the denominator includes all returned verifier entries, including unavailable comparisons."
      : "Exact equality against the blind verifier. Denominator is returned verifier entries; unavailable comparisons do not count as agreements. Numerators were not published in this legacy report.",
  }));
  for (const [field, unit] of (heroCategorical ? [] : [["severity", "severity_points"], ["sentiment", "sentiment_points"]] as const)) {
    metrics.push({
      id: `${field}_difference`, label: `${field === "severity" ? "Severity" : "Sentiment"} mean absolute difference`,
      initial_numerator: null, final_numerator: null, denominator: comparable, unit,
      initial_value: null, final_value: numberOrNull(legacy[`${field}_mean_absolute_difference`]),
      definition: "Mean absolute final-label difference against the verifier, using only comparable completed records. No initial mean was published.",
    });
  }
  return {
    format: heroCategorical ? "hero_categorical" : "legacy_flag_inclusive", metrics, verified, comparable,
    finalDisagreements: numberOrNull(legacy.disagreement_count),
    initialDisagreements: numberOrNull(legacy.initial_disagreement_count),
  };
}

/** Saved project totals are usage accounting, not a provider balance or live bill. */
export function savedProjectSpending(value: unknown): {
  spent: number; unknownHold: number; reserved: number; committed: number;
} | null {
  const snapshot = object(value);
  const spent = snapshot.spent_usd, unknownHold = snapshot.unknown_charge_hold_usd;
  const reserved = snapshot.reserved_usd, committed = snapshot.committed_usd;
  if (![spent, unknownHold, reserved, committed].every((number) => finite(number) && number >= 0)) return null;
  if (!finite(spent) || !finite(unknownHold) || !finite(reserved) || !finite(committed) ||
      Math.abs(committed - spent - unknownHold - reserved) > 1e-8) return null;
  return { spent, unknownHold, reserved, committed };
}

export function publicPredictionProvenance(value: unknown): {
  classifier: string | null;
  fallback: string;
  initial: [string, string][];
  reasons: string[];
} {
  const provenance = object(value);
  const provider = typeof provenance.classifier_provider === "string" ? provenance.classifier_provider : null;
  const model = typeof provenance.classifier_model === "string" ? provenance.classifier_model : null;
  const initial = object(provenance.initial_prediction);
  const fields = ["topic", "intent", "severity", "sentiment", "needs_review"];
  const labels: [string, string][] = fields.flatMap((key) => {
    const entry = initial[key];
    return typeof entry === "string" || typeof entry === "boolean" || finite(entry)
      ? [[key.replaceAll("_", " "), String(entry)]] as [string, string][]
      : [];
  });
  const reasons = Array.isArray(provenance.fallback_reason)
    ? provenance.fallback_reason.filter((reason): reason is string => typeof reason === "string").slice(0, 8)
    : typeof provenance.fallback_reason === "string" ? [provenance.fallback_reason] : [];
  return {
    classifier: model ? `${provider || "Provider not published"} · ${model}` : null,
    fallback: provenance.fallback_used === true ? "Escalation used"
      : provenance.fallback_used === false ? "Escalation not used" : "Escalation status not published",
    initial: labels,
    reasons,
  };
}
