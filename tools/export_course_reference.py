#!/usr/bin/env python3
"""Wrap the frozen minimal exporter with explicit course-completion provenance.

Never publish or call models. Use this instead of the base exporter for a NEW
reference created by import_course_supplement.py, especially AI-assisted reviews.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

import export_golden_grader as base

METHODS = {"original_reference", "supplemental_human", "ai_assisted_human_confirmed"}
SAFE_COMPLETION_FIELDS = {"version", "parent_reference_sha256", "supplement_sha256", "snapshot_sha256", "rubric_sha256",
                          "scope", "golden_rows", "required_fields_complete", "evaluation_status", "ai_draft_sha256",
                          "human_confirmed_ai_rows", "human_confirmed_ai_fields", "raw_ai_suggestions_counted_without_human_confirmation",
                          "frozen_hero_predictions_consulted", "new_labels_inferred_by_importer"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def render_course_html(rows, statement):
    """Render the sanitized per-case JSON directly, including field-level method."""
    escape = lambda value: html.escape(str(value), quote=True)
    cards = []
    for row in rows:
        cells = []
        for field, expected in row["expected"].items():
            comparison = row["comparison"][field]
            match = comparison.get("exact_match")
            outcome = ("Outside selected cohort / unscored" if not row["inside_selected_cohort"] else
                       "Unannotated / excluded" if not expected["explicitly_annotated"] else
                       "Match" if match is True else "Mismatch / invalid prediction" if match is False else
                       "Literal quote comparison only")
            prediction = row["prediction"][field] if row["prediction"] is not None else None
            values = (field, json.dumps(expected["value"], ensure_ascii=False), expected["origin"],
                      expected["annotation_method"], json.dumps(prediction, ensure_ascii=False), outcome,
                      comparison.get("absolute_error"))
            cells.append('<tr data-field="' + escape(field) + '">' +
                         "".join("<td>" + escape(value) + "</td>" for value in values) + "</tr>")
        cards.append('<section data-review-id="' + escape(row["review_id"]) + '"><h2>Worksheet ' +
                     escape(row["worksheet_position"]) + " · " + escape(row["reference_group"]) + ": " +
                     escape(row["review_id"]) + '</h2><p class="review">' + escape(row["review_text"]) +
                     '</p><p class="hash">Source hash: ' + escape(row["source_row_sha256"]) +
                     '</p><div class="scroll"><table><thead><tr><th>Field</th><th>Expected</th>'
                     '<th>Human provenance</th><th>Annotation method</th><th>Frozen prediction</th>'
                     '<th>Comparison</th><th>Absolute error</th></tr></thead><tbody>' + "".join(cells) +
                     "</tbody></table></div></section>")
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Completed course reference comparison</title><style>'
            'body{font:16px system-ui;margin:32px auto;padding:0 20px;max-width:1400px;color:#17252f;background:#f6f8fa}'
            'h1{font-size:28px}section{background:white;border:1px solid #ccd5df;border-radius:8px;padding:20px;margin:24px 0}'
            'h2{font-size:19px;overflow-wrap:anywhere}.review{white-space:pre-wrap}.hash{font:12px monospace;overflow-wrap:anywhere}'
            '.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:8px;'
            'border-bottom:1px solid #ddd;max-width:340px;overflow-wrap:anywhere}th{background:#eef3f7}'
            '.warning{padding:16px;background:#fff1c6;border-left:5px solid #bb7200}</style>'
            '<h1>Completed course reference and frozen hero predictions</h1><p class="warning">' + escape(statement) +
            '</p><p>Posthoc reference agreement; not blind population accuracy. Original human provenance and annotation method '
            'are separate columns. AI-assisted fields are identified individually. Unannotated and outside-cohort values remain '
            'excluded from scoring. This static page contains no personal notes, scripts, analytics, or external requests.</p>' +
            "".join(cards) + "</html>\n")


def disclose(out, reference, expected_sha):
    raw = reference.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError("New reference changed before provenance disclosure")
    document = json.loads(raw)
    completion = document.get("course_supplement")
    if not isinstance(completion, dict):
        raise ValueError("Expected an imported course-completion reference")
    status = completion["evaluation_status"]
    if status not in {"posthoc_course_reference_completion_not_blind_accuracy", "posthoc_ai_assisted_course_reference_completion_not_blind_accuracy"}:
        raise ValueError("Unknown course-reference evaluation status")
    labels = {row["review_id"]: row for row in document["labels"]}
    public_completion = {key: completion[key] for key in sorted(SAFE_COMPLETION_FIELDS) if key in completion}
    ai = "ai_assisted" in status
    if ai:
        if completion.get("raw_ai_suggestions_counted_without_human_confirmation") != 0:
            raise ValueError("Unconfirmed AI suggestions cannot be published as labels")
        statement = (f'This posthoc reference includes {completion["human_confirmed_ai_fields"]} originally missing field values '
                     f'across {completion["human_confirmed_ai_rows"]} reviews that were drafted with AI and then explicitly confirmed '
                     'by the user, including any user edits. Per-field annotation_method preserves that assistance. '
                     'These are not independent blind human labels. Frozen hero predictions were not inputs to the draft review or importer.')
    else:
        statement = ('The user completed the course golden-50 fields in a separate manual worksheet. '
                     'This remains posthoc reference agreement, not blind population accuracy. '
                     'Per-field annotation_method identifies new supplemental human edits.')
    method_by_id = {}
    jsonl_paths = [path for path in out.glob("*-comparison.jsonl") if path.is_file()]
    if not jsonl_paths:
        raise ValueError("Missing base comparison exports")
    for path in jsonl_paths:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            label = labels[row["review_id"]]
            if row["source_row_sha256"] != label["row_sha"] or row["review_text"] != label["review_text"] or row["provenance"]["reference_sha256"] != expected_sha:
                raise ValueError("Comparison identity/reference mismatch")
            methods = label.get("course_annotation_methods", {})
            for field, expected in row["expected"].items():
                if (json.dumps(expected["value"], ensure_ascii=False, sort_keys=True) != json.dumps(label.get(field), ensure_ascii=False, sort_keys=True)
                        or expected["origin"] != label["annotation_provenance"][field]
                        or expected["explicitly_annotated"] is not (label["annotation_provenance"][field] == "annotated")):
                    raise ValueError("Public expected values/provenance differ from the approved reference")
                method = methods.get(field, "original_reference")
                if method not in METHODS:
                    raise ValueError("Unknown per-field annotation method")
                if method == "ai_assisted_human_confirmed":
                    confirmation = label.get("course_human_confirmation", {})
                    if not ai or field not in confirmation.get("draft_fields", []) or not confirmation.get("reviewed_at"):
                        raise ValueError("Missing private human confirmation for an AI-assisted field")
                expected["annotation_method"] = method
            row["provenance"]["evaluation_status"] = status
            row["provenance"]["reference_completion"] = public_completion
            method_by_id[row["review_id"]] = {field: expected["annotation_method"] for field, expected in row["expected"].items()}
        path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in rows))
    for path in out.glob("*-comparison.csv"):
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle); rows = list(reader); fields = reader.fieldnames
        additions = [f"expected_{field}_annotation_method" for field in next(iter(method_by_id.values()))]
        fields = fields + [key for key in additions if key not in fields]
        for row in rows:
            row["evaluation_status"] = status
            for field, method in method_by_id[row["review_id"]].items():
                row[f"expected_{field}_annotation_method"] = json.dumps(method)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields);writer.writeheader();writer.writerows(rows)
    aggregate_path = out / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_bytes())
    aggregate["evaluation_status"] = status
    aggregate["reference_completion"] = public_completion
    old_sentence = "Human severity was selectively assigned to functional issues; its score does not estimate severity accuracy for every review."
    new_sentence = "The completed golden 50 use the course severity rubric for every record; the additional 150 retain sparse original annotations."
    aggregate["limitations"] = [new_sentence if value == old_sentence else value for value in aggregate["limitations"]]
    aggregate["limitations"].insert(0, statement)
    aggregate_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    for name in ("README.md", "report.md"):
        path = out / name
        text = path.read_text().replace(old_sentence, new_sentence).replace("All 200 worksheet labels", "All 200 worksheet records")
        if ai:
            opening = "**AI-assisted, human-confirmed posthoc reference agreement; not blind population accuracy.**"
            if "Posthoc adjudicated reference agreement; **not blind population accuracy**." in text:
                text = text.replace("Posthoc adjudicated reference agreement; **not blind population accuracy**.", opening, 1)
            else:
                title, remainder = text.split("\n", 1)
                text = title + "\n\n" + opening + "\n" + remainder
        text += "\n## Course-completion provenance\n\n" + statement + "\n\nEvaluation status: `" + status + "`.\n"
        if name == "report.md":
            text += ("\n## Inspect the cases\n\n"
                     "[Methodology and field definitions](README.md) · "
                     "[Golden 50 comparison CSV](golden50-comparison.csv) · "
                     "[All 200 worksheet records CSV](all200-comparison.csv) · "
                     "[Per-case HTML view](index.html) · "
                     "[Structured all-200 JSONL](all200-comparison.jsonl)\n")
        path.write_text(text)
    main_jsonl = out / "all200-comparison.jsonl"
    if not main_jsonl.exists():
        main_jsonl = out / "golden50-comparison.jsonl"
    html_rows = [json.loads(line) for line in main_jsonl.read_text().splitlines()]
    (out / "index.html").write_text(render_course_html(html_rows, statement))
    validation_path = out / "validation.json"
    validation = json.loads(validation_path.read_bytes())
    validation.update(course_completion_provenance_disclosed=True, evaluation_status=status,
                      ai_assistance_disclosed=ai, reference_completion=public_completion)
    validation["files"] = {path.name: {"sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}
                           for path in sorted(out.iterdir()) if path.is_file() and path.name != "validation.json"}
    validation_path.write_text(json.dumps(validation, indent=2) + "\n")
    if reference.read_bytes() != raw:
        raise ValueError("Reference changed during disclosure")


def main(args):
    # This path operates only on a new output directory created by the base
    # exporter; historical published files are never overwritten.
    raw = args.annotations.read_bytes()
    if sha(raw) != args.annotation_sha256 or "course_supplement" not in json.loads(raw):
        raise ValueError("Expected the exact newly imported course reference")
    base.main(args)
    disclose(args.out, args.annotations, args.annotation_sha256)
    print(json.dumps({"course_reference_output": str(args.out), "assistance_disclosed": True, "published": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("evaluator", "annotations", "source", "selected", "golden-source", "predictions", "out"):
        parser.add_argument("--" + field, type=Path, required=True)
    for field in ("annotation-sha256", "prediction-sha256", "label-config", "run-id"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--scope", choices=("golden", "all"), default="all")
    parser.add_argument("--publication-approved", action="store_true")
    main(parser.parse_args())
