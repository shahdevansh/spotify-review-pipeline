import assert from "node:assert/strict";
import test from "node:test";
import type { ComparisonMetric, EvaluationResponse, PilotAuditReport } from "../src/lib/evaluation-report.ts";
import {
  comparisonMetricDisplay,
  confidencePresentation,
  formatRatio,
  humanBenchmarkSummary,
  legacyModelComparison,
  matchedEvaluation,
  publicPredictionProvenance,
  qualityPresentation,
  responseMatchesRun,
  utcTimestamp,
} from "../src/lib/evaluation-view.ts";

// Synthetic display fixture only. These values never populate a production run.
function report(): PilotAuditReport {
  return {
    schema_version: "spotify-dashboard-evaluation-v1", kind: "pilot_audit",
    report_id: "synthetic-ui-report", run_id: "synthetic-run", label_config: "synthetic-config",
    generated_at: "2026-10-20T01:00:00Z", records_sha256: "synthetic-not-a-source-hash", artifact_refs: [],
    coverage: { selected: 10, completed: 10, unique_texts: 9, exact_text_aliases: 1, cache_hits: 1, compared: 10 },
    quality_gate: { status: "hold", summary: "Synthetic hold despite completed processing", reasons: [], recommendations_provisional: true },
    human: {
      status: "pending_labels", ground_truth_available: false, metrics: [], interpretation: "Pending",
      cohorts: [
        { id: "golden", label: "Golden holdout", expected_count: 50, status: "pending", sampling_note: "Synthetic metadata" },
        { id: "fresh", label: "Fresh holdout", expected_count: 150, status: "pending", sampling_note: "Synthetic metadata" },
      ],
    },
    model_comparison: { status: "not_available", answer_blind: true, ground_truth: false, shared_fallback_verifier_model: true, verifier_provider: "synthetic", verifier_model: "synthetic", metrics: [], disagreements: [] },
    routing: { numeric_signal_available: 0, confidence_calibrated: false, initial_flagged: 1, final_flagged: 1, fallback_count: 0, fallback_cap: 0, unique_text_denominator: 9, interpretation: "Synthetic" },
    inspection: { reviewer_type: "ai_assisted", ground_truth: false, cohorts: [], interpretation: "Synthetic" },
    synthetic: { status: "failed", operational_status: "passed", model_behavior_status: "failed", case_count: 1, scope: "Synthetic display fixture", artifact_path: null },
    ranking_sensitivity: { status: "not_available", ground_truth: false, interpretation: "Synthetic", compared_count: 0, rows: [] },
    structural: { status: "passed", checks: [], semantic_support_established: false },
    cost_snapshot: { as_of: "2026-10-20T01:00:00Z", source: "synthetic", known_usd: 0, unknown_hold_usd: 0, reserved_usd: 0, committed_usd: 0, attempts: 0, basis: "nominal_usage_reprice", scope: "project_snapshot" },
    limitations: [],
  };
}

test("pending human cohorts show planned coverage, never zero error or an accuracy result", () => {
  const human = humanBenchmarkSummary(report().human);
  assert.equal(human.planned, 200);
  assert.equal(human.status, "pending");
  assert.equal(human.metric, "Not measured");
  assert.match(human.label, /200 planned reviews/);
  const absent = humanBenchmarkSummary(null);
  assert.equal(absent.planned, null);
  assert.equal(absent.label, "Human benchmark not published");
});

test("ratio display includes original denominator and preserves a measured zero", () => {
  assert.equal(formatRatio(828, 1000), "82.8% · 828/1,000");
  assert.equal(formatRatio(0, 20), "0.0% · 0/20");
  assert.equal(formatRatio(null, 20), "Not measured");
  assert.equal(formatRatio(0, 0), "Not measured");
});

test("model metrics retain exact numerator and their own denominators", () => {
  const metric: ComparisonMetric = {
    id: "topic", label: "Topic agreement", initial_numerator: 8, final_numerator: 9,
    denominator: 10, unit: "fraction", initial_value: 0.8, final_value: 0.9, definition: "Synthetic equality",
  };
  assert.deepEqual(comparisonMetricDisplay(metric, "initial"), { value: "80.0%", detail: "8/10" });
  assert.deepEqual(comparisonMetricDisplay(metric, "final"), { value: "90.0%", detail: "9/10" });
  assert.equal(comparisonMetricDisplay({ ...metric, denominator: 0 }, "final").value, "Not measured");
  assert.equal(comparisonMetricDisplay({ ...metric, final_value: null }, "final").value, "Not measured");
  assert.deepEqual(comparisonMetricDisplay({ ...metric, denominator: 7, unit: "severity_points", final_value: 0 }, "final"),
    { value: "0.000 severity points", detail: "7 comparable reviews" });
});

test("a hold is never styled as success, even with no reasons and complete processing", () => {
  const result = qualityPresentation(report().quality_gate);
  assert.equal(result.status, "hold");
  assert.equal(result.tone, "warning");
  assert.equal(result.provisional, true);
  assert.equal(qualityPresentation(null).status, "not_evaluated");
  assert.notEqual(qualityPresentation(null).tone, "success");
  assert.equal(qualityPresentation({ ...report().quality_gate, status: "pass", recommendations_provisional: false }).tone, "success");
});

test("published model verification is distinct from unavailable human accuracy and a quality pass", () => {
  const comparison = {
    comparison_type: "independent_model_agreement", verified_count: 40000, comparable_count: 40000,
    field_agreement: { topic: 0.91, intent: 0.935 }, ground_truth: false,
  };
  const result = qualityPresentation(null, comparison);
  assert.equal(result.status, "model_verification_available");
  assert.equal(result.tone, "neutral");
  assert.equal(result.provisional, true);
  assert.match(result.label, /Model verification published/);
  assert.match(result.label, /Human accuracy not evaluated/);
  assert.match(result.summary, /40,000 original review IDs/);
  assert.equal(qualityPresentation(report().quality_gate, comparison).status, "hold");
  assert.equal(qualityPresentation({ ...report().quality_gate, status: "pass" }, comparison).status, "pass");
  for (const invalid of [
    { ...comparison, verified_count: 0 },
    { ...comparison, comparable_count: 0 },
    { ...comparison, comparable_count: 40001 },
    { ...comparison, field_agreement: {} },
    { ...comparison, field_agreement: { topic: 1.2 } },
    { human_ground_truth: true, metrics: { accuracy: 1 } },
  ]) assert.equal(qualityPresentation(null, invalid).status, "not_evaluated");
});

test("missing or zero numeric-signal coverage means unknown confidence, not zero uncertainty", () => {
  assert.equal(confidencePresentation(null).label, "Numeric confidence unknown");
  assert.equal(confidencePresentation(0).label, "Numeric confidence unknown");
  assert.match(confidencePresentation(0).detail, /No numeric confidence/);
  assert.match(confidencePresentation(10).label, /uncalibrated/);
  assert.doesNotMatch(confidencePresentation(10).detail, /100%/);
});

test("matching evaluation persists the hold across arbitrary run IDs and rejects mixed identity", () => {
  const saved = report();
  const response: EvaluationResponse = { status: "ready", run_id: saved.run_id, label_config: saved.label_config, report: saved, candidate_comparison: null };
  assert.equal(matchedEvaluation(response, saved).report?.quality_gate.status, "hold");
  const other = { ...saved, run_id: "another-synthetic-run" };
  assert.equal(matchedEvaluation({ ...response, run_id: other.run_id, report: other }, other).report?.quality_gate.status, "hold");
  assert.match(matchedEvaluation(response, other).warning!, /identity mismatch/);
  assert.equal(matchedEvaluation(response, { ...saved, label_config: "different" }).report, null);
  assert.equal(matchedEvaluation({ ...response, run_id: "different" }, saved).report, null);
});

test("legacy endpoint absence and malformed report fail safely without inventing a pass", () => {
  const saved = report();
  assert.equal(matchedEvaluation(null, saved).report, null);
  assert.match(matchedEvaluation(null, saved).warning!, /not published or unavailable/);
  const response = { status: "ready", run_id: saved.run_id, label_config: saved.label_config, report: { ...saved, human: {} }, candidate_comparison: null } as unknown as EvaluationResponse;
  assert.equal(matchedEvaluation(response, saved).report, null);
  assert.match(matchedEvaluation(response, saved).warning!, /incomplete schema/);
});

test("legacy comparison uses named fields and never reconstructs unpublished numerators", () => {
  const legacy = legacyModelComparison({
    comparison_type: "independent_model_agreement", verified_count: 10, comparable_count: 8,
    field_agreement: { topic: 0.8 }, initial_model_field_agreement: { topic: 0.7 },
    severity_mean_absolute_difference: 0, disagreement_count: 3,
  })!;
  assert.equal(legacy.metrics[0].final_numerator, null);
  assert.match(comparisonMetricDisplay(legacy.metrics[0], "final").detail, /Denominator 10 · numerator not published/);
  assert.equal(legacy.metrics.find((metric) => metric.id === "severity_difference")?.denominator, 8);
  assert.equal(legacyModelComparison({ status: "evaluated", human_ground_truth: true, metrics: { accuracy: 1 } }), null);
  const missingCounts = legacyModelComparison({ comparison_type: "independent_model_agreement" })!;
  assert.equal(missingCounts.metrics[0].denominator, null);
  assert.equal(comparisonMetricDisplay(missingCounts.metrics[0], "final").value, "Not measured");
});

test("review and page response identities cannot contradict the displayed run", () => {
  const run = { run_id: "synthetic-run", label_config: "synthetic-config" };
  assert.equal(responseMatchesRun({ run_id: run.run_id }, run), true);
  assert.equal(responseMatchesRun({ run_id: "promoted-run" }, run), false);
  assert.equal(responseMatchesRun({ label_config: "other-config" }, run), false);
  assert.equal(responseMatchesRun({}, run), true);
});

test("cost timestamp is explicitly UTC and invalid dates remain unknown", () => {
  assert.equal(utcTimestamp("2026-10-20T01:00:00-07:00"), "2026-10-20 08:00:00 UTC");
  assert.equal(utcTimestamp("not a date"), "Timestamp not available");
});

test("public provenance renders only returned bounded prediction fields", () => {
  const result = publicPredictionProvenance({
    classifier_provider: "synthetic-provider", classifier_model: "synthetic-model", fallback_used: true,
    initial_prediction: { topic: "billing", severity: 3, needs_review: false, private_trace: "not displayed" },
    fallback_reason: ["synthetic-reason"], secret_key: "not displayed",
  });
  assert.equal(result.classifier, "synthetic-provider · synthetic-model");
  assert.equal(result.fallback, "Escalation used");
  assert.equal(result.initial.length, 3);
  assert.doesNotMatch(JSON.stringify(result), /private_trace|secret_key|not displayed/);
  assert.equal(publicPredictionProvenance(null).classifier, null);
});
