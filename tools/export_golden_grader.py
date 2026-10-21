#!/usr/bin/env python3
"""Prepare an allowlisted golden-50 or all-200 comparison; never publish or infer labels.

Uses the frozen aggregate evaluator's source validation and sparse-label rules.
The output contains human labels and must remain private until explicitly approved.
Only Python standard-library imports plus the supplied offline evaluator are used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.util
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def main(args):
    spec = importlib.util.spec_from_file_location("frozen_human_evaluator", args.evaluator)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    annotation_bytes = args.annotations.read_bytes()
    if sha(annotation_bytes) != args.annotation_sha256:
        raise ValueError("Reference checksum mismatch")
    document = json.loads(annotation_bytes)
    labels = {row["review_id"]: row for row in document["labels"]}
    if len(labels) != 200:
        raise ValueError("Expected the original 200-row reference worksheet")

    def csv_rows(path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)

    golden_rows = list(csv_rows(args.golden_source))
    golden_ids = [row["review_id"] for row in golden_rows]
    if len(golden_ids) != 50 or len(set(golden_ids)) != 50 or not set(golden_ids) <= labels.keys():
        raise ValueError("Official golden set must have 50 unique reference IDs")
    selected_ids = [row["review_id"] for row in csv_rows(args.selected)]
    if len(selected_ids) != len(set(selected_ids)) or not set(golden_ids) <= set(selected_ids):
        raise ValueError("Invalid selected IDs or incomplete golden membership")
    sources = {}
    for row in csv_rows(args.source):
        if row["review_id"] in labels:
            if row["review_id"] in sources:
                raise ValueError("Duplicate reference ID in full source")
            sources[row["review_id"]] = row
    for row in golden_rows:
        if any(row[field] != sources[row["review_id"]][field] for field in evaluator.SOURCE_FIELDS):
            raise ValueError("Official golden source differs from original full source")
    predictions, seen, configurations = {}, set(), set()
    prediction_digest = hashlib.sha256()
    with evaluator.open_jsonl_bytes(args.predictions) as handle:
        for line in handle:
            prediction_digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            rid = row["review_id"]
            if rid in seen:
                raise ValueError("Duplicate prediction ID")
            seen.add(rid)
            configurations.add(row.get("label_config"))
            if rid in labels:
                predictions[rid] = row
    if prediction_digest.hexdigest() != args.prediction_sha256:
        raise ValueError("Frozen prediction checksum mismatch")
    if seen != set(selected_ids) or configurations != {args.label_config}:
        raise ValueError("Incomplete/foreign predictions or changed frozen configuration")
    full_report = evaluator.evaluate(document, sources, predictions, set(selected_ids), set(golden_ids))
    golden_metrics = full_report["groups"]["mandatory_golden_50"]
    if args.baseline_report:
        baseline = json.loads(args.baseline_report.read_bytes())
        if baseline["groups"] != full_report["groups"]:
            raise ValueError("Aggregate evaluation differs from frozen published reference report")

    fields = (*evaluator.FIELDS, "evidence_quote")
    output_rows = []
    export_ids = list(labels) if args.scope == "all" else golden_ids
    golden_positions = {rid: position for position, rid in enumerate(golden_ids, 1)}
    for position, rid in enumerate(export_ids, 1):
        label, pred = labels[rid], predictions.get(rid, {})
        inside_selected = rid in set(selected_ids)
        expected, comparisons = {}, {}
        for field in fields:
            origin = label["annotation_provenance"][field]
            value = label.get(field)
            expected[field] = {"value": value, "explicitly_annotated": origin == "annotated", "origin": origin}
            annotated = origin == "annotated"
            eligible = annotated and inside_selected
            if field == "evidence_quote":
                comparisons[field] = {
                    "included_in_agreement_denominator": False,
                    "exact_string_match": value == pred.get(field) if eligible else None,
                    "prediction_is_exact_source_substring": (isinstance(pred.get(field), str)
                    and bool(pred[field].strip()) and pred[field] in sources[rid]["review_text"]) if inside_selected else None,
                    "semantic_support": None,
                }
                continue
            valid = pred.get("status") == "completed" and evaluator.valid_value(field, pred.get(field))
            equals = set(value) == set(pred[field]) if eligible and valid and field == "entities" else value == pred.get(field)
            comparisons[field] = {
                "included_in_agreement_denominator": eligible,
                "prediction_valid": valid if inside_selected else None,
                "exact_match": bool(valid and equals) if eligible else None,
                "absolute_error": abs(value - pred[field]) if eligible and valid and field in {"severity", "sentiment"} else None,
            }
        # Only explicitly allowlisted fields survive; personal notes, alternatives,
        # labeler identity, and revision history cannot enter. Scope controls rows.
        output_rows.append({
            "schema_version": "golden-grader-case-v1",
            "worksheet_position": position if args.scope == "all" else list(labels).index(rid) + 1,
            "golden_position": golden_positions.get(rid),
            "reference_group": "mandatory_golden_50" if rid in golden_positions else "additional_150",
            "inside_selected_cohort": inside_selected,
            "review_id": rid,
            "source_row_sha256": evaluator.source_hash(sources[rid]),
            "review_text": sources[rid]["review_text"],
            "expected": expected,
            "prediction": {field: pred.get(field) for field in fields} if inside_selected else None,
            "comparison": comparisons,
            "provenance": {
                "evaluation_status": full_report["evaluation_status"],
                "reference_sha256": args.annotation_sha256,
                "prediction_sha256_uncompressed_jsonl": args.prediction_sha256,
                "run_id": args.run_id,
                "label_config": args.label_config,
                "prediction_status": pred.get("status") if inside_selected else "outside_selected_cohort",
                "classifier_provider": pred.get("classifier_provider"),
                "classifier_model": pred.get("classifier_model"),
                "fallback_used": pred.get("fallback_used"),
            },
        })
    # Independent reconciliation from the exact exported per-case comparison.
    export_metrics = full_report["groups"]["all_annotated_worksheet"] if args.scope == "all" else golden_metrics
    for field in evaluator.FIELDS:
        scored = [row for row in output_rows if row["comparison"][field]["included_in_agreement_denominator"]]
        score = export_metrics["fields"][field]["exact_agreement"]
        if len(scored) != score["denominator"] or sum(row["comparison"][field]["exact_match"] for row in scored) != score["numerator"]:
            raise ValueError(f"Per-case agreement mismatch for {field}")
        if field in {"severity", "sentiment"}:
            errors = [row["comparison"][field]["absolute_error"] for row in scored if row["comparison"][field]["absolute_error"] is not None]
            actual = sum(errors) / len(errors) if errors else None
            expected_mae = export_metrics["fields"][field]["mean_absolute_error"]
            if actual is not None and abs(actual - expected_mae) > 1e-12 or (actual is None) != (expected_mae is None):
                raise ValueError(f"Per-case MAE mismatch for {field}")
    if args.annotations.read_bytes() != annotation_bytes:
        raise ValueError("Reference changed during read-only export")
    if args.out.exists():
        raise ValueError("Refusing to overwrite an existing export; choose a new version")
    args.out.mkdir(parents=True, mode=0o700)
    jsonl = "".join(dump(row) + "\n" for row in output_rows)
    stem = "all200-comparison" if args.scope == "all" else "golden50-comparison"
    (args.out / (stem + ".jsonl")).write_text(jsonl)
    if args.scope == "all":
        (args.out / "golden50-comparison.jsonl").write_text("".join(dump(row) + "\n" for rid in golden_ids for row in output_rows if row["review_id"] == rid))
    flat = []
    for row in output_rows:
        item = {key: row[key] for key in ("worksheet_position", "golden_position", "reference_group", "inside_selected_cohort", "review_id", "source_row_sha256", "review_text")}
        item.update(row["provenance"])
        for field in fields:
            for key, value in row["expected"][field].items():
                item[f"expected_{field}_{key}"] = dump(value)
            item[f"prediction_{field}"] = dump(row["prediction"][field] if row["prediction"] is not None else None)
            for key, value in row["comparison"][field].items():
                item[f"{field}_{key}"] = dump(value)
        flat.append(item)
    with (args.out / (stem + ".csv")).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    if args.scope == "all":
        by_id = {row["review_id"]: row for row in flat}
        with (args.out / "golden50-comparison.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(flat[0]))
            writer.writeheader()
            writer.writerows(by_id[rid] for rid in golden_ids)
    report = {"schema_version": "human-reference-grader-export-v1", "publication_approved": args.publication_approved,
              "scope": args.scope,
              "evaluation_status": full_report["evaluation_status"], "groups": full_report["groups"] if args.scope == "all" else {"mandatory_golden_50": golden_metrics},
              "artifacts": {"reference_sha256": args.annotation_sha256, "prediction_sha256": args.prediction_sha256,
                            "label_config": args.label_config, "run_id": args.run_id,
                            "evaluator_sha256": sha(args.evaluator.read_bytes()),
                            "golden_source_sha256": sha(args.golden_source.read_bytes())},
              "limitations": full_report["limitations"]}
    (args.out / "aggregate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Human reference and frozen hero predictions", "",
             "Posthoc adjudicated reference agreement; **not blind population accuracy**.", "",
             "All 200 worksheet labels are preserved without personal notes or annotator identity. "
             "The hero cohort contains 99 worksheet IDs: all 50 golden IDs and 49 additional IDs. "
             "The other 101 records retain human labels but have null production predictions and are unscored.", "",
             "| Group | Field | Explicit reference labels | In hero cohort | Correct / eligible | Agreement | MAE |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for group_name, group in report["groups"].items():
        for field in ("topic", "intent", "severity", "sentiment"):
            metric = group["fields"][field]
            score = metric["exact_agreement"]
            agreement = f'{score["value"]:.4%}' if score["value"] is not None else "Not assessed"
            mae = metric.get("mean_absolute_error")
            lines.append(f'| {group_name} | {field} | {metric["explicitly_annotated"]} | {metric["inside_selected_cohort"]} | {score["numerator"]}/{score["denominator"]} | {agreement} | {mae if mae is not None else "—"} |')
    lines += ["", "## Interpretation", "", *["- " + item for item in report["limitations"]], "",
              "## Immutable inputs", "",
              f'- Human reference SHA-256: `{args.annotation_sha256}`',
              f'- Frozen prediction SHA-256 (uncompressed JSONL): `{args.prediction_sha256}`',
              f'- Run: `{args.run_id}`', f'- Classification configuration: `{args.label_config}`', ""]
    if args.scope != "all":
        lines[4] = "This export contains only the official golden 50, all in the selected hero cohort."
    (args.out / "report.md").write_text("\n".join(lines))
    escaped = lambda value: html.escape(str(value), quote=True)
    cards = []
    for row in output_rows:
        cells = []
        for field in fields:
            expected, comparison = row["expected"][field], row["comparison"][field]
            match = comparison.get("exact_match")
            outcome = "Outside selected cohort / unscored" if not row["inside_selected_cohort"] else "Unannotated / excluded" if not expected["explicitly_annotated"] else ("Match" if match is True else "Mismatch / invalid prediction" if match is False else "Literal quote comparison only")
            cells.append("<tr>" + "".join(f"<td>{escaped(v)}</td>" for v in (field, dump(expected["value"]), expected["origin"], dump(row["prediction"][field] if row["prediction"] is not None else None), outcome, comparison.get("absolute_error"))) + "</tr>")
        cards.append(f'<section><h2>Worksheet {row["worksheet_position"]} · {escaped(row["reference_group"])}: {escaped(row["review_id"])}</h2><p class="review">{escaped(row["review_text"])}</p><p class="hash">Source hash: {escaped(row["source_row_sha256"])}</p><div class="scroll"><table><thead><tr><th>Field</th><th>Expected</th><th>Human provenance</th><th>Frozen prediction</th><th>Comparison</th><th>Absolute error</th></tr></thead><tbody>{"".join(cells)}</tbody></table></div></section>')
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Private golden-50 comparison</title><style>body{font:16px system-ui;margin:32px auto;padding:0 20px;max-width:1250px;color:#17252f;background:#f6f8fa}h1{font-size:28px}section{background:white;border:1px solid #ccd5df;border-radius:8px;padding:20px;margin:24px 0}h2{font-size:19px;overflow-wrap:anywhere}.review{white-space:pre-wrap}.hash{font:12px monospace;overflow-wrap:anywhere}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #ddd;max-width:340px;overflow-wrap:anywhere}th{background:#eef3f7}.warning{padding:16px;background:#fff1c6;border-left:5px solid #bb7200}</style><h1>Private golden-50 expected labels and frozen predictions</h1><p class="warning">Publication is not approved. Posthoc adjudicated reference agreement; not blind population accuracy. This file contains only the official golden 50. Personal notes and the other 150 worksheet records are excluded.</p><p>Blank severity, sentiment, and entities remain unannotated. False flags and full-source evidence follow the user\'s declared defaults; defaults do not count as explicit labels. Missing model ambiguity predictions are reported as invalid, not inferred.</p>' + "".join(cards) + '</html>\n'
    if args.scope == "all":
        page = page.replace("Private golden-50", "Human reference 200-row").replace("private golden-50", "human reference 200-row").replace("This file contains only the official golden 50. Personal notes and the other 150 worksheet records are excluded.", "This file contains all 200 worksheet records, grouped into the official golden 50 and additional 150. Personal notes and annotator identities are excluded. All 101 records outside the hero cohort have null predictions and are unscored.")
    if args.publication_approved:
        page = page.replace("Publication is not approved.", "Publication of these minimal labels and comparisons was explicitly approved by the user.")
    (args.out / "index.html").write_text(page)
    instructions = """# Private golden-50 grader export

**Prepared locally; publication permission is pending.** Do not commit or upload this directory without the user's explicit approval.

This contains the official 50 golden records in original golden-file order, source text and row hashes, explicitly allowlisted expected labels and field provenance, frozen hero predictions, and per-case comparisons. No personal notes, alternative-label notes, annotator identity, revision history, or other 150 worksheet records are exported. The original 200-row reference is unchanged.

- `golden50-comparison.jsonl` is the authoritative structured per-case export.
- `golden50-comparison.csv` is a flattened equivalent. Label cells are JSON encoded: `null` means unassessed, `false` is a Boolean, and arrays remain arrays.
- `index.html` is an entirely local, static review page with no scripts, analytics, storage, or external requests.
- `aggregate.json` reuses the frozen evaluator's golden-50 metrics exactly.
- `validation.json` records checksums and independent per-case reconciliation.

This reference was adjudicated after earlier model comparisons, including approved topic corrections. It is **not a blind accuracy test**. Missing labels are never inferred. Severity and sentiment use only explicit labels. A missing entities answer is unannotated, not an empty entity list. User-declared `default_false` flags and `default_full_source` quotes remain visible but are excluded from explicit-label agreement denominators. Quote equality is a literal comparison, not a semantic evidence score. The pipeline does not output a separate ambiguity Boolean; missing ambiguity predictions are invalid under the original evaluator.

The exporter is offline and read-only with respect to all source data. It cannot write model inputs, prompt settings, routing, predictions, or training data. A new reference version must be explicitly supplied with its new SHA; output directories are never overwritten.
"""
    if args.scope == "all":
        instructions = instructions.replace("Private golden-50 grader export", "Human-reference 200-row grader export").replace("This contains the official 50 golden records in original golden-file order", "This contains all 200 worksheet records in original worksheet order, with a separate official golden-50 JSONL subset in golden-file order").replace(", or other 150 worksheet records", "").replace("`golden50-comparison.jsonl` is the authoritative structured per-case export.", "`all200-comparison.jsonl` is the authoritative structured per-case export. `golden50-comparison.jsonl` is the official 50-row subset.").replace("`golden50-comparison.csv`", "`all200-comparison.csv`").replace("golden-50 metrics exactly", "all three group metrics exactly")
        instructions += "\nOnly 99 worksheet IDs are in the hero cohort (50 golden and 49 additional). The other 101 retain their human values but have null production predictions, outside_selected_cohort provenance, and no agreement denominator contribution. They are not counted as missing hero predictions.\n"
    if args.publication_approved:
        instructions = instructions.replace("**Prepared locally; publication permission is pending.** Do not commit or upload this directory without the user's explicit approval.", "**The user explicitly approved publication of all 200 minimal expected-label, public-source, and frozen-prediction comparisons.** Personal notes and annotator identity remain excluded. This exporter prepares files locally and does not publish them itself.")
    instructions += "\nExplicit reference coverage (each field scored separately):\n\n"
    for group_name, group in report["groups"].items():
        counts = ", ".join(f'{field}: {group["fields"][field]["explicitly_annotated"]}/{group["worksheet_rows"]}' for field in ("topic", "intent", "severity", "sentiment"))
        instructions += f"- {group_name}: {counts}.\n"
    (args.out / "README.md").write_text(instructions)
    forbidden_keys = {"notes", "alternative_notes", "alternative_topics", "alternative_intents", "alternative_severities", "human_labeler", "annotator_id", "raw_labels", "revision_history"}
    def inspect(value):
        if isinstance(value, dict):
            if forbidden_keys & value.keys():
                raise ValueError("A forbidden private field entered the export")
            for nested in value.values():
                inspect(nested)
        elif isinstance(value, list):
            for nested in value:
                inspect(nested)
    inspect(output_rows)
    reread = [json.loads(line) for line in (args.out / (stem + ".jsonl")).read_text().splitlines()]
    if reread != output_rows or [row["review_id"] for row in reread] != export_ids:
        raise ValueError("Export round-trip or identity mismatch")
    with (args.out / (stem + ".csv")).open(newline="", encoding="utf-8") as handle:
        csv_reread = list(csv.DictReader(handle))
    if [row["review_id"] for row in csv_reread] != export_ids:
        raise ValueError("CSV identity mismatch")
    if any(row["source_row_sha256"] != evaluator.source_hash(sources[row["review_id"]]) for row in reread):
        raise ValueError("Export source-hash mismatch")
    validation = {"passed": True, "golden_records": 50, "exported_records": len(output_rows), "other_worksheet_records_exported": len(output_rows) - 50,
                  "outside_selected_predictions_null_and_unscored": all(row["prediction"] is None and all(not comparison["included_in_agreement_denominator"] for comparison in row["comparison"].values()) for row in output_rows if not row["inside_selected_cohort"]),
                  "forbidden_private_fields_absent": True, "per_case_aggregate_matches_frozen_evaluator": True,
                  "reference_unchanged": args.annotations.read_bytes() == annotation_bytes,
                  "reference_sha256": args.annotation_sha256,
                  "files": {path.name: {"sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
                            for path in sorted(args.out.iterdir()) if path.is_file()}}
    (args.out / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    for path in args.out.iterdir():
        path.chmod(0o600)
    print(json.dumps({"output": str(args.out), "passed": True, "rows": len(output_rows),
                      "metrics": {field: golden_metrics["fields"][field]["exact_agreement"] for field in ("topic", "intent", "severity")},
                      "sentiment_mae": golden_metrics["fields"]["sentiment"]["mean_absolute_error"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("evaluator", "annotations", "source", "selected", "golden-source", "predictions", "out"):
        parser.add_argument("--" + field, type=Path, required=True)
    for field in ("annotation-sha256", "prediction-sha256", "label-config", "run-id"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--scope", choices=("golden", "all"), default="golden")
    parser.add_argument("--publication-approved", action="store_true")
    main(parser.parse_args())
