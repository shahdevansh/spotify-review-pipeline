import assert from "node:assert/strict";
import test from "node:test";
import { humanReferenceCoverage, humanReferenceDisclosure, publishedHumanReference } from "../src/lib/human-reference.ts";
import { qualityPresentation } from "../src/lib/evaluation-view.ts";

// Synthetic publication metadata. No values in this fixture activate production.
const run = {
  run_id: "run-07e2cb4b0e3d9be0",
  label_config: "spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a",
  input_count: 200013, completed: 200000, quarantined: 13, pending: 0, imported_rows: 200013,
};
const source = {
  total_rows: 660622, nonempty_rows: 660609, empty_rows: 13,
  file_sha256: "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6",
};
const manifest = {
  schema_version: "spotify-hero-human-reference-link-v1",
  publication: {
    status: "verified_public_aggregate", run_id: run.run_id, label_config: run.label_config,
    github_commit: "a".repeat(40), report_sha256: "b".repeat(64), prediction_sha256: "c".repeat(64),
    source_sha256: source.file_sha256, golden_rows: 50, golden_topic_labels: 47,
    golden_intent_labels: 47, selected_reference_rows: 99,
  },
};

test("human evidence is inactive until a verified publication is configured", () => {
  assert.equal(publishedHumanReference(run, source, { ...manifest, publication: null }), null);
  for (const bad of [null, {}, [], { ...manifest, publication: null },
    { ...manifest, schema_version: "unknown" }, { ...manifest, schema_version: [manifest.schema_version] }, { ...manifest, extra: true }]) {
    assert.equal(publishedHumanReference(run, source, bad), null);
  }
});

test("verified evidence emits only a fixed-repository immutable link and bounded coverage", () => {
  const result = publishedHumanReference(run, source, manifest)!;
  assert.equal(result.report_url, `https://github.com/shahdevansh/spotify-review-pipeline/blob/${"a".repeat(40)}/evals/hero-human/report.md`);
  assert.equal(result.status, "posthoc_adjudicated_reference");
  assert.match(humanReferenceCoverage(result), /topic 47\/50; intent 47\/50/);
  assert.match(humanReferenceCoverage(result), /label counts, not correct-prediction counts/);
  assert.doesNotMatch(JSON.stringify(result), /review_text|notes|\/Users\/|annotation|human_answer/);
  assert.equal(Object.keys(result).length, 11);
});

test("every stored run identity and completeness field must match exactly", () => {
  for (const key of Object.keys(run)) {
    for (const value of [undefined, null, [], NaN, -1, String(run[key as keyof typeof run]) + "x"]) {
      assert.equal(publishedHumanReference({ ...run, [key]: value }, source, manifest), null, key);
    }
  }
  assert.equal(publishedHumanReference({ ...run, completed: "200000" }, source, manifest), null);
  assert.equal(publishedHumanReference(null, source, manifest), null);
});

test("source checksum aliases are explicit and conflicts or count changes fail closed", () => {
  for (const key of ["total_rows", "nonempty_rows", "empty_rows", "file_sha256"]) {
    assert.equal(publishedHumanReference(run, { ...source, [key]: undefined }, manifest), null, key);
  }
  for (const alias of ["source_sha256", "sha256"]) {
    const { file_sha256, ...counts } = source;
    assert.ok(publishedHumanReference(run, { ...counts, [alias]: file_sha256 }, manifest));
    assert.equal(publishedHumanReference(run, { ...source, [alias]: "f".repeat(64) }, manifest), null);
  }
});

test("malformed publication identities, hashes, coverage and unexpected private fields are rejected", () => {
  const p = manifest.publication;
  const invalidOverrides: Array<[string, unknown]> = [
    ["status", "pending"], ["run_id", "old-run"], ["label_config", "different"],
    ["source_sha256", "f".repeat(64)], ["github_commit", "main"],
    ["github_commit", "javascript:alert(1)"], ["github_commit", "../foreign"],
    ["report_sha256", ""], ["prediction_sha256", null], ["golden_rows", 200],
    ["golden_topic_labels", 51], ["golden_intent_labels", "47"],
    ["selected_reference_rows", 49], ["selected_reference_rows", 201], ["notes", "private"],
    ["report_url", "https://example.com"],
  ];
  for (const [key, value] of invalidOverrides) {
    assert.equal(publishedHumanReference(run, source, { ...manifest, publication: { ...p, [key]: value } }), null, key);
  }
});

test("human reference disclosure does not turn model agreement into a quality pass", () => {
  const human = publishedHumanReference(run, source, manifest)!;
  const comparison = { comparison_type: "independent_model_agreement", verified_count: 40000,
    comparable_count: 40000, field_agreement: { topic: 0.91, intent: 0.935 }, ground_truth: false };
  const result = qualityPresentation(null, comparison, human);
  assert.equal(result.tone, "neutral");
  assert.equal(result.provisional, true);
  assert.match(result.label, /adjudicated human reference published/);
  assert.match(result.summary, /sparse, posthoc adjudicated/);
  assert.match(result.summary, /Neither result establishes blind population accuracy/);
  assert.doesNotMatch(result.summary, /no run-matched human/);
  assert.equal(qualityPresentation({ status: "hold", summary: "Existing hold", reasons: [], recommendations_provisional: true }, comparison, human).status, "hold");
});

const aiManifest = {
  schema_version: "spotify-hero-human-reference-link-v2",
  publication: {
    ...manifest.publication,
    report_path: "evals/human-reference-v3/report.md",
    reference_type: "ai_assisted_human_confirmed",
    reference_sha256: "dd95152c33ac420e77d54688af9b0904432100d7824b849489eb17f9ab5dfc21",
    golden_topic_labels: 50, golden_intent_labels: 50,
    golden_severity_labels: 50, golden_sentiment_labels: 50,
  },
};

test("new evidence links only the published v3 path and exact confirmed reference", () => {
  const result = publishedHumanReference(run, source, aiManifest)!;
  assert.ok(result);
  assert.equal(result.report_url, `https://github.com/shahdevansh/spotify-review-pipeline/blob/${"a".repeat(40)}/evals/human-reference-v3/report.md`);
  assert.equal(result.reference_type, "ai_assisted_human_confirmed");
  assert.equal(result.reference_sha256, aiManifest.publication.reference_sha256);
  assert.equal(result.status, "posthoc_adjudicated_reference");
  assert.match(humanReferenceCoverage(result), /topic 50\/50; intent 50\/50; severity 50\/50; sentiment 50\/50/);
  assert.match(humanReferenceCoverage(result), /not correct-prediction counts/);
  assert.equal(Object.keys(result).length, 15);
});

test("new link fails closed for incomplete fields, changed provenance, and arbitrary paths", () => {
  const invalid: Array<[string, unknown]> = [
    ["report_path", "evals/hero-human/report.md"], ["report_path", "../private/notes"],
    ["report_path", "https://example.com"], ["reference_type", "blind_human"],
    ["reference_sha256", "e".repeat(64)], ["golden_topic_labels", 49],
    ["golden_intent_labels", 49], ["golden_severity_labels", 49],
    ["golden_sentiment_labels", 49], ["golden_severity_labels", "50"],
    ["github_commit", "main"], ["report_sha256", "not-verified"], ["notes", "private"],
  ];
  for (const [key, value] of invalid) assert.equal(publishedHumanReference(run, source, {
    ...aiManifest, publication: { ...aiManifest.publication, [key]: value },
  }), null, key);
  for (const key of Object.keys(aiManifest.publication)) {
    const p: Record<string, unknown> = { ...aiManifest.publication };
    delete p[key];
    assert.equal(publishedHumanReference(run, source, { ...aiManifest, publication: p }), null, key);
  }
  assert.equal(publishedHumanReference(run, source, { ...aiManifest, schema_version: manifest.schema_version }), null);
  assert.equal(publishedHumanReference(run, source, { ...manifest, schema_version: aiManifest.schema_version }), null);
});

test("new publication retains every exact hero identity and source completeness guard", () => {
  for (const key of Object.keys(run)) assert.equal(publishedHumanReference({ ...run, [key]: null }, source, aiManifest), null, key);
  for (const key of Object.keys(source)) assert.equal(publishedHumanReference(run, { ...source, [key]: null }, aiManifest), null, key);
  assert.equal(publishedHumanReference(run, source, { ...aiManifest, publication: null }), null);
});

test("golden review display uses a neutral heading while preserving methods and scope", () => {
  const ref = publishedHumanReference(run, source, aiManifest)!;
  const copy = humanReferenceDisclosure(ref);
  assert.equal(copy.heading, "Golden review set agreement");
  assert.equal(copy.badge, "50 reviewed records");
  assert.doesNotMatch(`${copy.heading} ${copy.badge}`, /AI-assisted|posthoc|blind population/i);
  assert.match(copy.context, /model-generated suggestions for 51 missing fields/);
  assert.match(copy.context, /edited them where needed, and confirmed the completed labels/);
  assert.match(copy.context, /earlier adjudications made after model predictions were inspected/);
  assert.match(copy.context, /size and annotation history limit conclusions/);
  assert.match(copy.scope, /Additional-review labels remain selectively annotated/);
  assert.match(copy.note, /authorized individual-label export/);
  assert.match(copy.note, /Personal notes are excluded/);
  assert.match(copy.note, /Production predictions and model-agreement results remain unchanged/);
  assert.doesNotMatch(copy.note, /No individual human answers/);
  const historical = humanReferenceDisclosure(publishedHumanReference(run, source, manifest)!);
  assert.equal(historical.badge, "Posthoc adjudicated · Sparse labels");
});

test("golden review summary preserves the existing quality gate", () => {
  const ref = publishedHumanReference(run, source, aiManifest)!;
  const comparison = { comparison_type: "independent_model_agreement", verified_count: 40000,
    comparable_count: 40000, field_agreement: { topic: 0.91, intent: 0.935 }, ground_truth: false };
  const result = qualityPresentation(null, comparison, ref);
  assert.equal(result.label, "Model verification and golden review set agreement published");
  assert.match(result.summary, /40,000 original review IDs/);
  assert.match(result.summary, /separate comparison against 50 reviewed records/);
  assert.doesNotMatch(`${result.label} ${result.summary}`, /AI-assisted|posthoc|blind population/i);
  assert.equal(result.tone, "neutral");
  assert.equal(result.provisional, true);
  assert.equal(qualityPresentation({ status: "hold", summary: "Prior hold", reasons: [], recommendations_provisional: true }, comparison, ref).status, "hold");
});


test("draft activation template is rejected until public commit and report digest are supplied", () => {
  const template = { ...aiManifest, publication: { ...aiManifest.publication,
    github_commit: "REQUIRES_IMMUTABLE_PUBLIC_COMMIT", report_sha256: "REQUIRES_VERIFIED_REPORT_SHA256",
  } };
  assert.equal(publishedHumanReference(run, source, template), null);
  assert.equal(publishedHumanReference(run, source, { ...aiManifest, schema_version: [aiManifest.schema_version] }), null);
});
