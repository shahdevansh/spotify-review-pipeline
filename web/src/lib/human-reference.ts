import publicationManifest from "./hero-human-publication.json" with { type: "json" };

const HERO_RUN = "run-07e2cb4b0e3d9be0";
const HERO_CONFIG = "spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a";
const SOURCE_SHA = "1fc85de68a304dd8978b537cfa58793d5f41cbaf417fa32cb53899f83a2fcef6";
const schema = "spotify-hero-human-reference-link-v1";
const aiSchema = "spotify-hero-human-reference-link-v2";
const AI_REFERENCE_SHA = "dd95152c33ac420e77d54688af9b0904432100d7824b849489eb17f9ab5dfc21";
const AI_REPORT_PATH = "evals/human-reference-v3/report.md";
const digest = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
const count = (value: unknown, maximum: number): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= maximum;

export type HumanReferenceLink = {
  status: "posthoc_adjudicated_reference";
  run_id: string;
  label_config: string;
  report_url: string;
  report_sha256: string;
  prediction_sha256: string;
  source_sha256: string;
  golden_rows: 50;
  golden_topic_labels: number;
  golden_intent_labels: number;
  selected_reference_rows: number;
  reference_type?: "ai_assisted_human_confirmed";
  reference_sha256?: string;
  golden_severity_labels?: 50;
  golden_sentiment_labels?: 50;
};

/**
 * A release operator activates the manifest only after reading back the exact
 * aggregate report from its immutable public GitHub commit and checking its SHA.
 * This is link metadata, not a new quality gate or an inference input. No private
 * labels, notes, local paths, report body, or model scores are accepted or emitted.
 */
export function publishedHumanReference(
  runValue: unknown, sourceValue: unknown, manifestValue: unknown = publicationManifest,
): HumanReferenceLink | null {
  const run = object(runValue), source = object(sourceValue), manifest = object(manifestValue);
  const publication = object(manifest?.publication);
  if (!run || !source || !manifest || !publication ||
      (manifest.schema_version !== schema && manifest.schema_version !== aiSchema) ||
      Object.keys(manifest).length !== 2) return null;
  const aiConfirmed = manifest.schema_version === aiSchema;
  const keys = ["status", "run_id", "label_config", "github_commit", "report_sha256",
    "prediction_sha256", "source_sha256", "golden_rows", "golden_topic_labels",
    "golden_intent_labels", "selected_reference_rows"];
  if (aiConfirmed) keys.push("report_path", "reference_type", "reference_sha256",
    "golden_severity_labels", "golden_sentiment_labels");
  if (Object.keys(publication).length !== keys.length || keys.some((key) => !Object.hasOwn(publication, key))) return null;
  if (publication.status !== "verified_public_aggregate" || publication.run_id !== HERO_RUN ||
      publication.label_config !== HERO_CONFIG || publication.source_sha256 !== SOURCE_SHA ||
      run.run_id !== HERO_RUN || run.label_config !== HERO_CONFIG || run.input_count !== 200013 ||
      run.completed !== 200000 || run.quarantined !== 13 || run.pending !== 0 || run.imported_rows !== 200013) return null;
  const sourceHashes = [source.source_sha256, source.file_sha256, source.sha256].filter((value) => value !== undefined);
  if (!sourceHashes.length || sourceHashes.some((value) => value !== SOURCE_SHA)) return null;
  if (source.total_rows !== 660622 || source.nonempty_rows !== 660609 || source.empty_rows !== 13) return null;
  if (typeof publication.github_commit !== "string" || !/^[0-9a-f]{40}$/.test(publication.github_commit) ||
      !digest(publication.report_sha256) || !digest(publication.prediction_sha256) ||
      publication.golden_rows !== 50 || !count(publication.golden_topic_labels, 50) ||
      !count(publication.golden_intent_labels, 50) || !count(publication.selected_reference_rows, 200) ||
      publication.selected_reference_rows < 50) return null;
  if (aiConfirmed && (publication.report_path !== AI_REPORT_PATH ||
      publication.reference_type !== "ai_assisted_human_confirmed" ||
      publication.reference_sha256 !== AI_REFERENCE_SHA ||
      publication.golden_topic_labels !== 50 || publication.golden_intent_labels !== 50 ||
      publication.golden_severity_labels !== 50 || publication.golden_sentiment_labels !== 50)) return null;
  return {
    status: "posthoc_adjudicated_reference", run_id: HERO_RUN, label_config: HERO_CONFIG,
    report_url: `https://github.com/shahdevansh/spotify-review-pipeline/blob/${publication.github_commit}/${aiConfirmed ? AI_REPORT_PATH : "evals/hero-human/report.md"}`,
    report_sha256: publication.report_sha256 as string,
    prediction_sha256: publication.prediction_sha256 as string,
    source_sha256: SOURCE_SHA, golden_rows: 50,
    golden_topic_labels: publication.golden_topic_labels,
    golden_intent_labels: publication.golden_intent_labels,
    selected_reference_rows: publication.selected_reference_rows,
    ...(aiConfirmed ? {
      reference_type: "ai_assisted_human_confirmed" as const,
      reference_sha256: AI_REFERENCE_SHA,
      golden_severity_labels: 50 as const,
      golden_sentiment_labels: 50 as const,
    } : {}),
  };
}

export function humanReferenceCoverage(reference: HumanReferenceLink): string {
  if (reference.reference_type === "ai_assisted_human_confirmed") {
    return `Golden-50 annotation coverage: topic ${reference.golden_topic_labels}/50; intent ${reference.golden_intent_labels}/50; severity ${reference.golden_severity_labels}/50; sentiment ${reference.golden_sentiment_labels}/50. These are label counts, not correct-prediction counts.`;
  }
  return `Golden-50 annotation coverage: topic ${reference.golden_topic_labels}/50; intent ${reference.golden_intent_labels}/50. These are label counts, not correct-prediction counts.`;
}

/** The reference provenance does not upgrade model agreement to human accuracy. */
export function humanReferenceDisclosure(reference: HumanReferenceLink) {
  if (reference.reference_type === "ai_assisted_human_confirmed") return {
    heading: "AI-assisted, human-confirmed reference agreement",
    badge: "AI-assisted · Human-confirmed · Posthoc",
    context: "Earlier annotations include corrections made after model predictions were inspected. Missing golden-review fields were then drafted with AI and explicitly reviewed and confirmed by the user. This mixed-provenance reference is not a blind human benchmark.",
    scope: "All four required fields are complete for the golden 50 under the course rubric. Additional-review labels remain selectively annotated; each field retains its own evaluated denominator.",
    note: "The linked report includes agreement, differences, provenance, and links to the authorized individual-label export. Personal notes are excluded. Production predictions and model-agreement results remain unchanged; recommendations remain provisional.",
  };
  return {
    heading: "Human reference evaluation",
    badge: "Posthoc adjudicated · Sparse labels",
    context: "The reference was corrected after earlier model predictions were inspected. Blank fields remain unannotated; severity was selectively assigned to functional issues.",
    scope: "Each field has its own evaluated denominator; the report separates golden reviews from additional reviews.",
    note: "The linked snapshot contains field agreement, error counts, missingness, and limitations. No individual human answers or notes are exposed in that aggregate report. Model agreement remains a separate diagnostic; recommendations remain provisional.",
  };
}
