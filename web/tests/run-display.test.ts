import assert from "node:assert/strict";
import test from "node:test";
import { evaluationMeasurements, hasCompletedHumanEvaluation, savedModelRoles } from "../src/lib/run-display.ts";

test("saved roles distinguish a model namespace from its actual provider", () => {
  const roles = savedModelRoles({
    models: { enrich: "nvidia/Nemotron-3_5-Lightning", verify: "openai/gpt-oss-120b" },
    providers: { enrich: "nebius", verify: "nebius" },
    reasoning_effort: { enrich: "none", verify: "low" },
  });
  assert.equal(roles[1].model, "openai/gpt-oss-120b");
  assert.equal(roles[1].provider, "nebius");
  assert.equal(roles[1].reasoning, "low");
  assert.deepEqual(savedModelRoles(undefined), []);
  assert.equal(savedModelRoles({ models: { verify: "openai/example" } })[0].provider, null);
});

test("even perfect model agreement leaves human accuracy pending", () => {
  const comparison = {
    status: "compared", comparison_type: "independent_model_agreement", ground_truth: false,
    verified_count: 1000, field_agreement: { topic: 1, intent: 1 },
    initial_model_field_agreement: { topic: 0.8, intent: 0.9 },
  };
  assert.equal(hasCompletedHumanEvaluation(comparison), false);
  assert.equal(hasCompletedHumanEvaluation({ human_ground_truth: true, status: "pending_human_labels" }), false);
  assert.equal(hasCompletedHumanEvaluation({ human_ground_truth: true, status: "evaluated" }), true);
  const displayed = evaluationMeasurements(comparison)!;
  assert.equal(displayed.compared_reviews, 1000);
  assert.deepEqual(displayed.final_model_agreement, { topic: 1, intent: 1 });
  assert.deepEqual(displayed.initial_model_agreement, { topic: 0.8, intent: 0.9 });
});
