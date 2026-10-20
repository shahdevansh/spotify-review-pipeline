import type { PilotAuditReport } from "../src/lib/evaluation-report.ts";

/** Synthetic aggregate fixture; fixed identity literals exercise the v5 schema. */
export function publicReportFixture(): PilotAuditReport {
  return {
    schema_version: "spotify-dashboard-evaluation-v1", kind: "pilot_audit",
    report_id: `pilot-audit-${"a".repeat(64)}`, run_id: "1000-1ad0e35d239c3e9d",
    label_config: "spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb",
    records_sha256: "d7d107cf8b390d4c2f311aa2b2e4d0d29d9a2ba19cb40059e32e91670500be02",
    generated_at: "2026-10-20T01:00:00Z", artifact_refs: [],
    coverage: { selected: 10, completed: 10, unique_texts: 9, exact_text_aliases: 1, cache_hits: 1, compared: 10 },
    quality_gate: { status: "hold", summary: "Synthetic test only", reasons: [], recommendations_provisional: true },
    human: { status: "pending_labels", ground_truth_available: false, metrics: [], interpretation: "Synthetic pending",
      cohorts: [
        { id: "mandatory_golden_50", label: "Mandatory", expected_count: 50, status: "pending", sampling_note: "Synthetic" },
        { id: "fresh_text_disjoint_150", label: "Conditional", expected_count: 150, status: "pending", sampling_note: "Synthetic" },
      ] },
    model_comparison: { status: "compared", answer_blind: true, ground_truth: false,
      shared_fallback_verifier_model: true, verifier_provider: "synthetic", verifier_model: "synthetic",
      metrics: [{ id: "topic", label: "Topic agreement", initial_numerator: 1, final_numerator: 1,
        denominator: 10, unit: "fraction", initial_value: 0.1, final_value: 0.1, definition: "Synthetic equality" }],
      disagreements: [] },
    routing: { numeric_signal_available: 0, confidence_calibrated: false, initial_flagged: 1, final_flagged: 1,
      fallback_count: 0, fallback_cap: 0, unique_text_denominator: 9, interpretation: "Synthetic" },
    inspection: { reviewer_type: "ai_assisted", ground_truth: false, cohorts: [], interpretation: "Synthetic" },
    synthetic: { status: "failed", operational_status: "passed", model_behavior_status: "failed",
      case_count: 1, scope: "Synthetic display fixture", artifact_path: null },
    ranking_sensitivity: { status: "not_available", ground_truth: false, interpretation: "Synthetic",
      compared_count: 10, rows: [] },
    structural: { status: "passed", checks: [], semantic_support_established: false },
    cost_snapshot: { as_of: "2026-10-20T01:00:00Z", source: "validation/synthetic.json",
      known_usd: 0, unknown_hold_usd: 0, reserved_usd: 0, committed_usd: 0, attempts: 0,
      basis: "nominal_usage_reprice", scope: "project_snapshot" },
    limitations: [],
  };
}
