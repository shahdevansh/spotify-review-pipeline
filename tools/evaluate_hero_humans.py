#!/usr/bin/env python3
"""Offline aggregate-only evaluation of frozen predictions against sparse labels.

No provider imports, model calls, prompt changes, or annotation writes. The
corrected reference was adjudicated after inspecting earlier predictions, so this
report must never be presented as blind population accuracy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

SOURCE_FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
TOPICS = {"access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"}
INTENTS = {"cancellation", "complaint", "request", "praise", "unclear"}
FIELDS = ("topic", "intent", "severity", "sentiment", "needs_review", "ambiguous", "entities")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_hash(row):
    values = [row[key] for key in SOURCE_FIELDS]
    if any(not isinstance(value, str) for value in values):
        raise ValueError("Source values must preserve original strings.")
    return digest(values)


def valid_value(field, value):
    if field == "topic":
        return isinstance(value, str) and value in TOPICS
    if field == "intent":
        return isinstance(value, str) and value in INTENTS
    if field == "severity":
        return type(value) is int and 1 <= value <= 5
    if field == "sentiment":
        return type(value) in (int, float) and math.isfinite(value) and -1 <= value <= 1
    if field in {"needs_review", "ambiguous"}:
        return type(value) is bool
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def evaluate(document, sources, predictions, selected_ids, golden_ids):
    """Evaluate explicit values independently; never infer a missing answer."""
    labels = document["labels"]
    ids = [row["review_id"] for row in labels]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate annotation IDs.")
    if document.get("annotation_protocol") != "human-partial-v3":
        raise ValueError("Expected the explicitly sparse human-partial-v3 protocol.")
    ordered = [{key: row[key] for key in ("review_id", "review_text", "row_sha")} for row in labels]
    if digest(ordered) != document.get("source_digest"):
        raise ValueError("Annotation source digest mismatch.")
    for row in labels:
        rid = row["review_id"]
        source = sources.get(rid)
        if source is None or row["row_sha"] != source_hash(source) or row["review_text"] != source["review_text"]:
            raise ValueError(f"Annotation source identity mismatch: {rid}")
        if not isinstance(row.get("annotation_provenance"), dict):
            raise ValueError("Missing field annotation provenance.")
        quote = row.get("evidence_quote")
        quote_origin = row["annotation_provenance"].get("evidence_quote")
        if quote_origin == "default_full_source":
            if quote != source["review_text"]:
                raise ValueError("Default evidence quote differs from original source.")
        elif quote_origin != "annotated" or not isinstance(quote, str) or not quote.strip() or quote not in source["review_text"]:
            raise ValueError("Annotated evidence quote is not supported by source.")
        for field in FIELDS:
            origin, value = row["annotation_provenance"].get(field), row.get(field)
            if origin == "annotated":
                if not valid_value(field, value):
                    raise ValueError(f"Invalid explicit human {field}: {rid}")
            elif origin == "not_assessed":
                if value not in (None, ""):
                    raise ValueError(f"Unassessed human {field} contains a value: {rid}")
            elif origin == "default_false" and field in {"needs_review", "ambiguous"}:
                if value is not False:
                    raise ValueError("Declared default-false flag was changed.")
            else:
                raise ValueError(f"Unknown human {field} provenance: {origin}")
        pred = predictions.get(rid)
        if pred is not None and (pred.get("source_sha256") != row["row_sha"] or
                                 any(pred.get(key) != source[key] for key in SOURCE_FIELDS)):
            raise ValueError(f"Prediction source identity mismatch: {rid}")

    groups = {"all_annotated_worksheet": labels,
              "mandatory_golden_50": [row for row in labels if row["review_id"] in golden_ids],
              "additional_150": [row for row in labels if row["review_id"] not in golden_ids]}
    report = {"schema_version": "hero-sparse-human-evaluation-v1",
              "evaluation_status": "posthoc_adjudicated_reference_agreement_not_blind_accuracy",
              "source_identity_checked": True, "raw_human_data_in_report": False, "groups": {},
              "limitations": [
                  "The human reference was corrected after inspecting earlier model predictions, including 43 approved topic changes; this is posthoc adjudicated agreement, not blind accuracy.",
                  "Each field uses only explicitly annotated values. Blank severity, sentiment, and entities are not negative labels and are never imputed.",
                  "Human severity was selectively assigned to functional issues; its score does not estimate severity accuracy for every review.",
                  "Only reference IDs inside the selected hero cohort enter agreement denominators. Outside-cohort references are separately counted; missing/invalid in-cohort predictions count as incorrect for exact agreement.",
                  "Numeric MAE uses valid available predictions only and states its denominator. Selective annotation and small nonrandom subgroups prevent a population-accuracy claim.",
                  "Explicit primary labels are scored; alternative accepted labels and notes are not substituted for the primary label.",
                  "Default-false flags and full-source evidence are reported separately from explicit annotations. Literal quote/entity checks do not establish semantic evidence support.",
                  "Human labels are read only by this offline evaluation after inference; they are not inputs to enrichment, routing, verification, or prompt selection."]}
    for name, rows in groups.items():
        selected = [row for row in rows if row["review_id"] in selected_ids]
        group = {"worksheet_rows": len(rows), "inside_selected_cohort": len(selected),
                 "outside_selected_cohort": len(rows) - len(selected), "fields": {}}
        for field in FIELDS:
            assessed = [row for row in rows if row["annotation_provenance"][field] == "annotated"]
            eligible = [row for row in assessed if row["review_id"] in selected_ids]
            valid = [(row, predictions[row["review_id"]]) for row in eligible
                     if row["review_id"] in predictions and predictions[row["review_id"]].get("status") == "completed"
                     and valid_value(field, predictions[row["review_id"]].get(field))]
            equals = lambda a, b: set(a) == set(b) if field == "entities" else a == b
            metric = {"explicitly_annotated": len(assessed), "not_explicitly_annotated": len(rows) - len(assessed),
                      "inside_selected_cohort": len(eligible), "outside_selected_cohort": len(assessed) - len(eligible),
                      "valid_prediction_count": len(valid), "missing_or_invalid_prediction_count": len(eligible) - len(valid),
                      "exact_agreement": ratio(sum(equals(row[field], pred[field]) for row, pred in valid), len(eligible))}
            if field in {"severity", "sentiment"}:
                errors = [abs(row[field] - pred[field]) for row, pred in valid]
                metric["mean_absolute_error"] = sum(errors) / len(errors) if errors else None
                metric["mae_denominator"] = len(errors)
                if field == "sentiment":
                    metric["within_0_25"] = ratio(sum(value <= .25 for value in errors), len(eligible))
            if field in {"topic", "intent", "severity"}:
                valid_ids = {row["review_id"] for row, _ in valid}
                counts = Counter((str(row[field]), str(predictions[row["review_id"]][field]) if row["review_id"] in valid_ids else "__missing_or_invalid__")
                                 for row in eligible)
                metric["confusion"] = [{"human": a, "prediction": b, "count": n} for (a, b), n in sorted(counts.items())]
            group["fields"][field] = metric
        defaults = [row for row in selected if row["annotation_provenance"]["needs_review"] == "default_false"]
        group["declared_default_false_needs_review"] = ratio(sum(
            predictions.get(row["review_id"], {}).get("status") == "completed" and
            predictions.get(row["review_id"], {}).get("needs_review") is False for row in defaults), len(defaults))
        routing_rows = [row for row in selected if all(row["annotation_provenance"][field] == "annotated"
                                                      for field in ("topic", "intent"))]
        errors, flagged, captured, invalid = 0, 0, 0, 0
        for row in routing_rows:
            pred = predictions.get(row["review_id"], {})
            valid = pred.get("status") == "completed" and all(valid_value(field, pred.get(field)) for field in ("topic", "intent"))
            error = not valid or any(row[field] != pred[field] for field in ("topic", "intent"))
            flag = pred.get("status") == "completed" and pred.get("needs_review") is True
            errors += error
            flagged += flag
            captured += error and flag
            invalid += not valid
        group["needs_review_detection_of_topic_or_intent_errors"] = {
            "jointly_explicit_reference_rows": len(routing_rows), "missing_or_invalid_predictions": invalid,
            "observed_errors_including_missing_predictions": errors, "flagged_predictions": flagged,
            "error_capture_recall": ratio(captured, errors), "flag_precision": ratio(captured, flagged),
            "interpretation": "Flag performance against observed topic/intent errors, independent of the human default-false needs_review convention. Missing predictions are errors and cannot be captured by an absent flag."}
        complete = [predictions[row["review_id"]] for row in selected
                    if predictions.get(row["review_id"], {}).get("status") == "completed"]
        group["mechanical_evidence_checks"] = {
            "completed_prediction_count": len(complete),
            "exact_quote_substring": ratio(sum(isinstance(row.get("evidence_quote"), str) and bool(row["evidence_quote"].strip())
                                                   and row["evidence_quote"] in row["review_text"] for row in complete), len(complete)),
            "unsupported_literal_entity_cases": sum(not valid_value("entities", row.get("entities")) or
                any(entity.casefold() not in row["review_text"].casefold() for entity in row.get("entities", [])) for row in complete),
            "semantic_evidence_accuracy": None}
        report["groups"][name] = group
    return report


def run(args):
    annotation_bytes = args.annotations.read_bytes()
    document = json.loads(annotation_bytes)
    wanted = {row["review_id"] for row in document["labels"]}
    with args.source.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = (json.loads(line) for line in handle if line.strip()) if args.source.suffix == ".jsonl" else csv.DictReader(handle)
        sources = {}
        for row in source_rows:
            if row["review_id"] in wanted:
                if row["review_id"] in sources:
                    raise ValueError("Duplicate original source IDs.")
                sources[row["review_id"]] = row
    with args.selected.open(encoding="utf-8-sig", newline="") as handle:
        selected = [row["review_id"] for row in csv.DictReader(handle)]
    if len(set(selected)) != len(selected):
        raise ValueError("Selected cohort contains duplicate IDs.")
    with args.golden_source.open(encoding="utf-8-sig", newline="") as handle:
        golden = {row["review_id"] for row in csv.DictReader(handle)}
    if len(golden) != 50 or len(wanted) != 200 or not golden <= wanted:
        raise ValueError("Expected the original 200-row worksheet and official golden 50.")
    predictions, seen, configurations, records_digest = {}, set(), set(), hashlib.sha256()
    with args.predictions.open("rb") as handle:
        for line in handle:
            records_digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            rid = row["review_id"]
            if rid in seen:
                raise ValueError("Duplicate prediction IDs.")
            seen.add(rid)
            configurations.add(row.get("label_config"))
            if rid in wanted:
                predictions[rid] = row
    if not seen <= set(selected) or configurations != {args.label_config}:
        raise ValueError("Foreign prediction IDs or unexpected/mixed frozen configurations.")
    if not args.allow_incomplete and seen != set(selected):
        raise ValueError("Hero predictions are incomplete; wait for final export or explicitly use --allow-incomplete.")
    report = evaluate(document, sources, predictions, set(selected), golden)
    report["artifacts"] = {"annotation_sha256": hashlib.sha256(annotation_bytes).hexdigest(),
                           "prediction_sha256": records_digest.hexdigest(), "label_config": args.label_config,
                           "selected_rows": len(selected), "exported_prediction_rows": len(seen),
                           "full_selected_export_present": seen == set(selected)}
    if args.annotations.read_bytes() != annotation_bytes:
        raise ValueError("Annotation input changed during evaluation; refusing a mixed snapshot.")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    lines = ["# Frozen hero predictions vs. corrected human annotations", "",
             "Posthoc adjudicated reference agreement; **not blind population accuracy**.", "",
             f"Prediction export coverage: {len(seen):,}/{len(selected):,} selected rows. " +
             ("Complete selected export." if seen == set(selected) else "**Incomplete checkpoint preview; rerun after hero completion.**"), "",
             "| Cohort | Field | Explicit labels | In hero cohort | Correct / eligible | Agreement |", "|---|---|---:|---:|---:|---:|"]
    for name, group in report["groups"].items():
        for field in ("topic", "intent", "severity"):
            metric = group["fields"][field]
            score = metric["exact_agreement"]
            percentage = f'{score["value"]:.2%}' if score["value"] is not None else "Not assessed"
            lines.append(f'| {name} | {field} | {metric["explicitly_annotated"]} | {metric["inside_selected_cohort"]} | {score["numerator"]}/{score["denominator"]} | {percentage} |')
    lines += ["", *["- " + note for note in report["limitations"]], "",
              "The JSON contains field-specific missingness, numeric-error denominators, confusion counts, source checks, and immutable input digests. No review text, IDs, notes, or raw human labels are exported."]
    (args.out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"output": str(args.out), "status": report["evaluation_status"], "rows": len(seen)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--golden-source", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--label-config", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    run(parser.parse_args())
