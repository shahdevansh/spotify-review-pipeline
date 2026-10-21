# Complete, import, and disclose a course reference

The course reference is an evaluation artifact. These offline tools do not call models, alter production predictions, retrain a classifier, or publish files. They preserve the original annotation export and create a new version after the user supplies a completed worksheet export.

Two input schemas are supported:

- `spotify-course-golden-completion-v1`: a completed manual worksheet.
- `spotify-course-golden-ai-review-v1`: a worksheet containing AI suggestions that the user explicitly reviewed. Every draft-bearing row must carry a confirmation, timestamp, and exact copy of the confirmed field values. Editing a value after confirmation invalidates it. Unreviewed suggestions are rejected.

Private worksheet snapshots, downloaded exports, personal notes, and original reference files are not included in the public repository. Supply your own authorized copies. A published comparison must disclose its reference's posthoc adjudication and any AI assistance; it is not blind population accuracy.

## Import a new private version

Run from the repository root after installing its dependencies. Compute the SHA-256 of the actual user-supplied file and verify the expected parent/snapshot checksums before substituting the placeholders below.

```sh
PYTHONPATH=src python tools/import_course_supplement.py \
  --reference private/human-labels/adjudication-v2/annotations.corrected.json \
  --reference-sha256 EXACT_PARENT_REFERENCE_SHA256 \
  --supplement private/human-labels/incoming/golden-50-ai-reviewed-supplement.json \
  --supplement-sha256 EXACT_USER_EXPORT_SHA256 \
  --worksheet private/human-labels/course-completion-v1/golden_50_course_completion.html \
  --ai-snapshot private/human-labels/course-completion-v1/ai_draft_source_snapshot.json \
  --snapshot-sha256 EXACT_AI_WORKSHEET_SNAPSHOT_SHA256 \
  --golden-source data/source/golden_50_to_label.csv \
  --version course-ai-reviewed-NEXT \
  --out private/human-labels/course-ai-reviewed-NEXT
```

For a manual worksheet, omit `--ai-snapshot`, supply its `golden-50-course-supplement.json`, and use the manual worksheet snapshot SHA.

The importer validates exact schema, raw input checksums, the official 50 identities and source hashes, required-field completeness, types and ranges, provenance, and a recomputed per-field change list. It rejects duplicate or foreign IDs, unsupported quotes, nonfinite numbers, inconsistent confirmation values, and incorrect snapshots. Boolean values cannot masquerade as numbers.

The new output must lie inside the parent reference's `private/human-labels/` directory. Existing destinations are rejected. It contains:

- `annotations.corrected.json`: the new 200-record reference.
- `parent.original.json` and `supplement.original.json`: byte-identical source copies.
- `changes.private.json`: private per-field history, potentially including personal notes.
- `validation.json`: checksums, coverage, and validation results.
- `ai-draft-snapshot.private.json` for AI-assisted imports.

Only the 50 golden records can change; the other 150 and source identities are preserved. The annotation protocol remains sparse because completing the golden set does not imply completion of the other 150 records. The importer retains AI-assisted field methods and human confirmation metadata separately from the evaluator's `annotated`/`not_assessed` vocabulary.

**Do not publish this private import directory or its change history.**

## Evaluate against the unchanged final predictions

Run `tools/evaluate_hero_humans.py` using the new corrected reference, full source, selected cohort, official golden CSV, and frozen final records. Save a new aggregate evaluation directory; preserve the earlier report. Keep the same prediction digest, run identity, and classification configuration.

The evaluator determines field-specific denominators and handles outside-cohort records. A missing optional label remains unannotated. An out-of-cohort reference has no production prediction and is not counted as a missing hero prediction. Default-false flags and full-source quote defaults do not become explicit human labels merely because they have values.

The evaluator retains historical explanatory prose. Its output is useful for checking calculations; the course-reference wrapper below produces the current disclosure and field methods without changing scores.

## Prepare the minimal public comparison

Use `tools/export_course_reference.py` for a newly imported course reference. It invokes the minimal base exporter and then preserves course/AI-assisted provenance in the public artifacts.

```sh
PYTHONPATH=src python tools/export_course_reference.py \
  --evaluator tools/evaluate_hero_humans.py \
  --annotations private/human-labels/course-ai-reviewed-NEXT/annotations.corrected.json \
  --annotation-sha256 EXACT_NEW_REFERENCE_SHA256 \
  --source data/source/spotify_reviews_18months.csv \
  --selected data/hero_200000.csv \
  --golden-source data/source/golden_50_to_label.csv \
  --predictions release/hero-v1/grading/records.jsonl.gz \
  --prediction-sha256 EXACT_FROZEN_UNCOMPRESSED_PREDICTION_SHA256 \
  --label-config EXACT_FROZEN_CLASSIFICATION_CONFIGURATION \
  --run-id EXACT_FROZEN_RUN_ID \
  --baseline-report private/human-labels/course-ai-reviewed-NEXT/evaluation/report.json \
  --scope all \
  --publication-approved \
  --out private/human-labels/course-ai-reviewed-NEXT/public-candidate
```

Adjust the final-records path to the verified extracted evidence location. `--baseline-report` must point to the **new** aggregate evaluation, not an older reference's metrics. `--publication-approved` records an approval already obtained; the tool itself does not obtain approval or upload anything.

Review and publish only the generated minimal comparison files after authorization. They include public source text/identity, primary expected values and provenance, frozen predictions, per-field comparisons, aggregate reports, and validation hashes. Personal notes, alternative-label notes, annotator identity, private change histories, draft rationales, and per-review confirmation timestamps remain excluded.

AI-assisted outputs identify the assistance at the beginning of the report and README, in each affected field's `annotation_method`, and in the HTML's separate **Human provenance** and **Annotation method** columns. The report links to the golden-50 and all-200 CSVs, structured JSONL, and per-case HTML.

## Synthetic verification

From `tools/`:

```sh
PYTHONPATH=../src python -m unittest test_import_course_supplement -v
```

The tests locate the existing `tools/evaluate_hero_humans.py` relative to themselves; no machine-specific runtime path is required. All fixtures are synthetic. The suite covers both complete import-to-export paths, rejection of malformed/unreviewed inputs, unchanged original records, note/identity exclusion, individual HTML field-method reconciliation, and HTML escaping. No tests need credentials or make model calls.
