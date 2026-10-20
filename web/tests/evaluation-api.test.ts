import assert from "node:assert/strict";
import test from "node:test";
import { requestedEvaluationRun, readEvaluation } from "../src/lib/evaluation-query.ts";
import { selectEvaluationReports } from "../src/lib/evaluation-report.ts";
import { validatePilotAudit } from "../src/lib/evaluation-validation.ts";
import { publicReportFixture } from "./evaluation-fixture.ts";

const fixture = publicReportFixture();
const run = { run_id: fixture.run_id, label_config: fixture.label_config };
function mockQuery(results: Record<string, unknown>[][]) {
  const calls: { text: string; values: unknown[] }[] = [];
  return {
    calls,
    async query(text: string, values: unknown[] = []) {
      calls.push({ text, values });
      assert.match(text.trimStart(), /^SELECT /);
      return { rows: results.shift() ?? [] };
    },
  };
}

test("evaluation run parameter is explicit and rejects malformed IDs", () => {
  assert.equal(requestedEvaluationRun("https://example.test/api/evaluation"), undefined);
  assert.equal(requestedEvaluationRun("https://example.test/api/evaluation?run_id=synthetic-run"), "synthetic-run");
  for (const bad of ["", "' OR 1=1", "x".repeat(161), "a\nb", "a\n", "a\r"]) {
    assert.throws(() => requestedEvaluationRun(`https://example.test/api/evaluation?run_id=${encodeURIComponent(bad)}`));
  }
});

test("legacy database without evaluation table stays readable and explicitly unpublished", async () => {
  const client = mockQuery([[{ run_id: run.run_id, summary: { label_config: run.label_config } }], [{ table_name: null }]]);
  const result = await readEvaluation(client);
  assert.equal(result.httpStatus, 200);
  assert.equal(result.body.status, "empty");
  assert.equal(result.body.report, null);
  assert.equal(client.calls.length, 2);
  assert.match(result.body.message!, /not been published/);
});

test("evaluation lookup binds run and configuration and exposes only recognized matching report", async () => {
  const payload = publicReportFixture();
  const client = mockQuery([
    [{ run_id: run.run_id, summary: { label_config: run.label_config } }],
    [{ table_name: "spotify_evaluation_reports" }],
    [{ kind: payload.kind, schema_version: payload.schema_version, payload }],
  ]);
  const result = await readEvaluation(client, run.run_id);
  assert.equal(result.body.status, "ready");
  assert.deepEqual(client.calls[0].values, [run.run_id]);
  assert.deepEqual(client.calls[2].values, [run.run_id, run.label_config]);
  assert.deepEqual(result.body.report, payload);
});

test("public boundary rejects human answers at every nested schema level", () => {
  assert.equal(validatePilotAudit(publicReportFixture()), true);
  const sentinel = [{ review_id: "synthetic-holdout-only", topic: "SYNTHETIC_ANSWER_SENTINEL" }];
  const targets = [
    { ...publicReportFixture(), human_answers: sentinel },
    { ...publicReportFixture(), human: { ...publicReportFixture().human, human_answers: sentinel } },
    { ...publicReportFixture(), model_comparison: { ...publicReportFixture().model_comparison, human_answers: sentinel } },
    { ...publicReportFixture(), ...JSON.parse('{"constructor":{"human_answers":["SYNTHETIC_ANSWER_SENTINEL"]}}') },
    { ...publicReportFixture(), human: { ...publicReportFixture().human, ...JSON.parse('{"__proto__":{"human_answers":["SYNTHETIC_ANSWER_SENTINEL"]}}') } },
    { ...publicReportFixture(), routing: { ...publicReportFixture().routing, ...JSON.parse('{"toString":{"human_answers":["SYNTHETIC_ANSWER_SENTINEL"]}}') } },
  ];
  for (const payload of targets) {
    const selected = selectEvaluationReports([{ kind: payload.kind, schema_version: payload.schema_version, payload }], run);
    assert.equal(selected.report, null);
    assert.doesNotMatch(JSON.stringify(selected), /SYNTHETIC_ANSWER_SENTINEL/);
  }
});

test("public boundary rejects inconsistent metric arithmetic, invalid values, and private paths", () => {
  const badFraction = publicReportFixture();
  badFraction.model_comparison.metrics[0].final_value = 0.9;
  const badCount = publicReportFixture();
  badCount.coverage.cache_hits = 11;
  const badMoney = publicReportFixture();
  badMoney.cost_snapshot.committed_usd = 1;
  const privatePath = publicReportFixture();
  privatePath.artifact_refs = [{ path: "/Users/synthetic/answers.json", sha256: "a".repeat(64), role: "synthetic" }];
  const numericBoolean = publicReportFixture();
  (numericBoolean.coverage as unknown as Record<string, unknown>).cache_hits = true;
  const infinity = publicReportFixture();
  infinity.cost_snapshot.known_usd = Infinity;
  for (const payload of [badFraction, badCount, badMoney, privatePath, numericBoolean, infinity]) {
    assert.equal(validatePilotAudit(payload), false);
  }
});

test("unsupported candidate payload is not exposed even with matching identity strings", () => {
  const payload = { ...run, kind: "candidate_comparison", schema_version: "spotify-candidate-comparison-v1",
    human_answers: [{ review_id: "synthetic-holdout-only", topic: "SYNTHETIC_ANSWER_SENTINEL" }] };
  const result = selectEvaluationReports([{ kind: payload.kind, schema_version: payload.schema_version, payload }], run);
  assert.equal(result.candidate_comparison, null);
  assert.doesNotMatch(JSON.stringify(result), /SYNTHETIC_ANSWER_SENTINEL/);
});

test("foreign fingerprints and unknown evaluation schemas never become current results", () => {
  const row = { kind: "pilot_audit", schema_version: "spotify-dashboard-evaluation-v1",
    payload: { ...run, kind: "pilot_audit", schema_version: "spotify-dashboard-evaluation-v1" } };
  assert.equal(selectEvaluationReports([{ ...row, payload: { ...row.payload, label_config: "other" } }], run).report, null);
  assert.equal(selectEvaluationReports([{ ...row, payload: { ...row.payload, run_id: "other" } }], run).report, null);
  assert.equal(selectEvaluationReports([{ ...row, schema_version: "future-version", payload: { ...row.payload, schema_version: "future-version" } }], run).report, null);
});

test("an explicit unknown run returns 404 instead of silently reading the current run", async () => {
  const client = mockQuery([[]]);
  const result = await readEvaluation(client, "missing-run");
  assert.equal(result.httpStatus, 404);
  assert.equal(result.body.run_id, null);
  assert.equal(client.calls.length, 1);
});
