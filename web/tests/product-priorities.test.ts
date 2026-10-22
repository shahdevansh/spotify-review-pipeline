import assert from "node:assert/strict";
import test from "node:test";
import { publishedProductPriorities } from "../src/lib/product-priorities.ts";
import type { HumanReferenceLink } from "../src/lib/human-reference.ts";

// Frozen publication identities from the verified hero evidence. These fixtures
// protect editorial claims from leaking into another run after a publication.
const run = {
  run_id: "run-07e2cb4b0e3d9be0",
  label_config: "spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a",
  completed: 200000, input_count: 200013, quarantined: 13,
};
const reference: HumanReferenceLink = {
  status: "posthoc_adjudicated_reference", run_id: run.run_id, label_config: run.label_config,
  report_url: "https://example.invalid/verified-report", report_sha256: "0".repeat(64),
  prediction_sha256: "8c23941a34abf7c09e279cb6dc49f0778638b25cc7e6a2a05f83b30daee4246c",
  source_sha256: "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6",
  golden_rows: 50, golden_topic_labels: 50, golden_intent_labels: 50, selected_reference_rows: 99,
};
const issues = [
  { issue_id: "issue-usability", complaint_count: 25563, priority_score: 68258, mean_severity: "2.670187" },
  { issue_id: "issue-playback", complaint_count: 12548, priority_score: 39445, mean_severity: "3.143529" },
  { issue_id: "issue-billing", complaint_count: 12794, priority_score: 35437, mean_severity: "2.769814" },
];

test("verified hero identity unlocks editorial priorities without replacing API measurements", () => {
  const before = JSON.stringify(issues);
  const result = publishedProductPriorities(run, reference, issues);
  assert.ok(result);
  assert.deepEqual(result.priorities.map((item) => item.issue_id), issues.map((item) => item.issue_id));
  assert.equal(JSON.stringify(issues), before);
  assert.ok(result.priorities.every((item) => !Object.hasOwn(item, "complaint_count") && !Object.hasOwn(item, "mean_severity")));
});

test("editorial claims stay hidden when publication identity or cohort changes", () => {
  for (const patch of [
    { run_id: "another-run" }, { label_config: "another-config" },
    { completed: 199999 }, { input_count: 200000 }, { quarantined: 12 },
  ]) assert.equal(publishedProductPriorities({ ...run, ...patch }, reference, issues), null);
  for (const patch of [
    { run_id: "another-run" }, { label_config: "another-config" },
    { prediction_sha256: "1".repeat(64) }, { source_sha256: "2".repeat(64) },
  ]) assert.equal(publishedProductPriorities(run, { ...reference, ...patch }, issues), null);
  assert.equal(publishedProductPriorities(null, reference, issues), null);
  assert.equal(publishedProductPriorities(run, null, issues), null);
});

test("partial or duplicated topic responses cannot support editorial cards", () => {
  assert.equal(publishedProductPriorities(run, reference, issues.slice(1)), null);
  assert.equal(publishedProductPriorities(run, reference, [...issues, issues[0]]), null);
});

test("invalid topic measurements fail closed instead of producing misleading chart bars", () => {
  for (const patch of [
    { complaint_count: NaN }, { complaint_count: 0 }, { priority_score: -1 },
    { mean_severity: "unknown" }, { mean_severity: 0 }, { mean_severity: 6 },
  ]) {
    assert.equal(publishedProductPriorities(run, reference, [{ ...issues[0], ...patch }, ...issues.slice(1)]), null);
  }
});
