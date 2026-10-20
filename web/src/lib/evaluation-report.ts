/** Public, aggregate-only evaluation contract. Human answer rows never belong here. */
import { validatePilotAudit } from "./evaluation-validation.ts";
export const EVALUATION_SCHEMA_VERSION = "spotify-dashboard-evaluation-v1" as const;

export type EvaluationArtifact = { path: string; sha256: string; role: string };
export type ComparisonMetric = {
  id: string;
  label: string;
  initial_numerator: number | null;
  final_numerator: number | null;
  denominator: number;
  unit: "fraction" | "severity_points" | "sentiment_points";
  initial_value: number | null;
  final_value: number | null;
  definition: string;
};
export type RankingSensitivityRow = {
  issue_id: string;
  final_rank: number;
  final_score: number;
  comparison_rank: number | null;
  comparison_score: number;
};

export type PilotAuditReport = {
  schema_version: typeof EVALUATION_SCHEMA_VERSION;
  kind: "pilot_audit";
  report_id: string;
  run_id: string;
  label_config: string;
  generated_at: string;
  records_sha256: string;
  artifact_refs: EvaluationArtifact[];
  coverage: {
    selected: number;
    completed: number;
    unique_texts: number;
    exact_text_aliases: number;
    cache_hits: number;
    compared: number;
  };
  quality_gate: {
    status: "hold" | "pass" | "not_evaluated";
    summary: string;
    reasons: string[];
    recommendations_provisional: boolean;
  };
  human: {
    status: "pending_labels";
    ground_truth_available: false;
    cohorts: { id: string; label: string; expected_count: number; status: "pending"; sampling_note: string }[];
    metrics: [];
    interpretation: string;
  };
  model_comparison: {
    status: "compared" | "not_available";
    answer_blind: boolean;
    ground_truth: false;
    shared_fallback_verifier_model: boolean;
    verifier_provider: string;
    verifier_model: string;
    metrics: ComparisonMetric[];
    disagreements: { id: string; label: string; count: number; denominator: number; definition: string }[];
  };
  routing: {
    numeric_signal_available: number;
    confidence_calibrated: false;
    initial_flagged: number;
    final_flagged: number;
    fallback_count: number;
    fallback_cap: number;
    unique_text_denominator: number;
    interpretation: string;
  };
  inspection: {
    reviewer_type: "ai_assisted";
    ground_truth: false;
    cohorts: {
      id: string; label: string; count: number; supported: number; concerns: number;
      ambiguous: number; concerns_flagged: number; selection_method: string;
    }[];
    interpretation: string;
  };
  synthetic: {
    status: "passed" | "failed" | "not_available";
    operational_status: "passed" | "failed" | "not_available";
    model_behavior_status: "passed" | "failed" | "not_available";
    case_count: number;
    scope: string;
    artifact_path: string | null;
  };
  ranking_sensitivity: {
    status: "available" | "not_available";
    ground_truth: false;
    interpretation: string;
    compared_count: number;
    rows: RankingSensitivityRow[];
  };
  structural: {
    status: "passed" | "failed" | "not_available";
    checks: { id: string; label: string; passed_count: number; total: number }[];
    semantic_support_established: false;
  };
  cost_snapshot: {
    as_of: string;
    source: string;
    known_usd: number;
    unknown_hold_usd: number;
    reserved_usd: number;
    committed_usd: number;
    attempts: number;
    basis: "nominal_usage_reprice";
    scope: "project_snapshot";
  };
  limitations: string[];
};

/** Candidate reports are optional and require a separately authorized publication. */
export type CandidateComparisonReport = {
  schema_version: "spotify-candidate-comparison-v1";
  kind: "candidate_comparison";
  report_id: string;
  run_id: string;
  label_config: string;
  generated_at: string;
  cohort_id: string;
  cohort_sha256: string;
  reference_kind: "ai_development" | "none";
  human_accuracy_status: "pending";
  conditions: {
    condition_id: string; model: string; provider: string; label_config: string;
    expected_count: number; completed_count: number; failed_count: number;
    nominal_cost_usd: number | null; metrics: ComparisonMetric[];
  }[];
  interpretation: string;
  artifact_refs: EvaluationArtifact[];
};

export type EvaluationResponse = {
  status: "ready" | "empty" | "unavailable";
  message?: string;
  run_id: string | null;
  label_config: string | null;
  report: PilotAuditReport | null;
  candidate_comparison: CandidateComparisonReport | null;
};

export function reportMatchesRun(
  report: Pick<PilotAuditReport, "run_id" | "label_config">,
  run: { run_id: string; label_config: string },
): boolean {
  return report.run_id === run.run_id && report.label_config === run.label_config;
}

/** Read only recognized versions; a future schema must never be silently flattened. */
export function selectEvaluationReports(
  rows: { kind: string; schema_version: string; payload: unknown }[],
  run: { run_id: string; label_config: string },
): Pick<EvaluationResponse, "report" | "candidate_comparison"> {
  let report: PilotAuditReport | null = null;
  let candidate_comparison: CandidateComparisonReport | null = null;
  for (const row of rows) {
    if (!row.payload || typeof row.payload !== "object") continue;
    const payload = row.payload as { run_id?: unknown; label_config?: unknown; kind?: unknown; schema_version?: unknown };
    if (payload.run_id !== run.run_id || payload.label_config !== run.label_config ||
        payload.kind !== row.kind || payload.schema_version !== row.schema_version) continue;
    if (!report && row.kind === "pilot_audit" && row.schema_version === EVALUATION_SCHEMA_VERSION &&
        validatePilotAudit(row.payload)) {
      report = row.payload;
    }
    // Candidate reports stay unavailable until their own strict aggregate-only
    // schema and publication validator are implemented and independently tested.
  }
  return { report, candidate_comparison };
}
