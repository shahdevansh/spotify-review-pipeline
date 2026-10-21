#!/usr/bin/env python3
"""Validate a completed human-only worksheet export and create a NEW private reference.

No provider imports, inference, label imputation, or publication. The original
reference, worksheet, golden source, and supplied export are opened read-only.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("topic", "intent", "severity", "sentiment", "entities", "evidence_quote", "needs_review", "ambiguous", "notes")
REQUIRED = ("topic", "intent", "severity", "sentiment")
SOURCE_FIELDS = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
TOPICS = {"access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"}
INTENTS = {"cancellation", "complaint", "request", "praise", "unclear"}
IDENTITY_KEYS = ("schema_version", "snapshot_sha256", "source_annotation_sha256", "golden_source_sha256", "rubric_sha256")
STATUS = "posthoc_course_reference_completion_not_blind_accuracy"
AI_STATUS = "posthoc_ai_assisted_course_reference_completion_not_blind_accuracy"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def object_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def loads(data):
    def reject_constant(value):
        raise ValueError("Nonfinite JSON number")
    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_equal(a, b):
    # JavaScript JSON.stringify treats 1 and 1.0 as equal. Bool is never numeric.
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(strict_equal(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def valid(field, value, text):
    if value is None:
        return field == "entities"
    if field == "topic":
        return isinstance(value, str) and value in TOPICS
    if field == "intent":
        return isinstance(value, str) and value in INTENTS
    if field == "severity":
        return type(value) is int and 1 <= value <= 5
    if field == "sentiment":
        return type(value) in (int, float) and math.isfinite(value) and -1 <= value <= 1
    if field == "entities":
        return isinstance(value, list) and all(isinstance(x, str) and bool(x.strip()) and len(x) <= 1000 for x in value)
    if field == "evidence_quote":
        return isinstance(value, str) and bool(value.strip()) and value in text
    if field in ("needs_review", "ambiguous"):
        return type(value) is bool
    if field == "notes":
        return isinstance(value, str) and len(value) <= 10000
    return False


def validate_inputs(reference_bytes, supplement_bytes, worksheet_bytes, golden_bytes, *, reference_sha256, supplement_sha256, snapshot_sha256):
    require(sha(reference_bytes) == reference_sha256, "Original reference checksum mismatch")
    require(sha(supplement_bytes) == supplement_sha256, "Supplement checksum mismatch")
    require(len(supplement_bytes) <= 2_000_000, "Supplement exceeds worksheet size limit")
    reference, supplement = loads(reference_bytes), loads(supplement_bytes)
    matches = re.findall(r'<script\b[^>]*\bid="worksheet-data"[^>]*>(.*?)</script>', worksheet_bytes.decode("utf-8"), re.S)
    require(len(matches) == 1, "Expected exactly one worksheet metadata block")
    meta = loads(matches[0])
    meta_without_digest = {key: value for key, value in meta.items() if key != "snapshot_sha256"}
    require(sha(canonical(meta_without_digest).encode()) == meta.get("snapshot_sha256") == snapshot_sha256, "Worksheet snapshot checksum mismatch")
    require(meta.get("schema_version") == "spotify-course-golden-completion-v1", "Unexpected worksheet schema")
    require(meta.get("source_annotation_sha256") == reference_sha256, "Worksheet belongs to another reference")
    require(meta.get("golden_source_sha256") == sha(golden_bytes), "Official golden source checksum mismatch")
    require(meta.get("evaluation_status") == STATUS, "Worksheet evaluation status mismatch")
    expected_top = {*IDENTITY_KEYS, "evaluation_status", "exported_at", "complete", "labels", "changes", "validation_errors"}
    require(isinstance(supplement, dict) and set(supplement) == expected_top, "Unexpected supplement fields")
    for key in IDENTITY_KEYS:
        require(supplement.get(key) == meta.get(key), f"Supplement {key} mismatch")
    require(supplement.get("evaluation_status") == STATUS, "Supplement evaluation status mismatch")
    require(supplement.get("complete") is True and supplement.get("validation_errors") == [], "Supplement is partial or reports validation errors")
    timestamp = datetime.fromisoformat(supplement["exported_at"].replace("Z", "+00:00"))
    require(timestamp.tzinfo is not None, "Human export timestamp must include timezone")
    require(reference.get("annotation_protocol") == "human-partial-v3", "Unexpected reference protocol")
    original = reference.get("labels")
    require(isinstance(original, list) and len(original) == 200, "Expected original 200-row worksheet")
    original_by_id = {row["review_id"]: row for row in original}
    require(len(original_by_id) == 200, "Duplicate original reference IDs")
    identity = [{key: row[key] for key in ("review_id", "review_text", "row_sha")} for row in original]
    require(sha(canonical(identity).encode()) == reference.get("source_digest"), "Original reference source digest mismatch")
    golden = list(csv.DictReader(io.StringIO(golden_bytes.decode("utf-8-sig"))))
    golden_ids = [row["review_id"] for row in golden]
    require(len(golden) == 50 and len(set(golden_ids)) == 50, "Official golden set must contain 50 unique IDs")
    items = meta.get("items")
    require(isinstance(items, list) and len(items) == 50, "Worksheet metadata must contain 50 items")
    require([row["review_id"] for row in items] == golden_ids, "Worksheet differs from official golden IDs/order")
    supplied = supplement.get("labels")
    require(isinstance(supplied, list) and len(supplied) == 50, "Supplement must contain exactly 50 labels")
    by_id = {row["review_id"]: row for row in supplied}
    require(len(by_id) == 50 and set(by_id) == set(golden_ids), "Duplicate, foreign, or missing supplement ID")
    source_by_id = {row["review_id"]: row for row in golden}
    changes = []
    new_reference = copy.deepcopy(reference)
    corrected_by_id = {row["review_id"]: row for row in new_reference["labels"]}
    histories = []
    for i, item in enumerate(items, 1):
        rid = item["review_id"]
        require(rid in original_by_id, "Golden ID absent from original reference")
        old, source, human = original_by_id[rid], source_by_id[rid], by_id[rid]
        source_hash = sha(canonical([source[field] for field in SOURCE_FIELDS]).encode())
        require(item["row_sha"] == old["row_sha"] == human["row_sha"] == source_hash, "Source-row hash mismatch")
        require(item["review_text"] == old["review_text"] == source["review_text"], "Source text mismatch")
        require(item["golden_position"] == i and item["worksheet_position"] == original.index(old) + 1, "Worksheet position mismatch")
        require(set(item["initial"]) == set(FIELDS) and all(strict_equal(item["initial"][field], old.get(field)) for field in FIELDS), "Worksheet initial labels differ from original reference")
        require(item["initial_provenance"] == old["annotation_provenance"], "Worksheet initial provenance mismatch")
        row_keys = {"review_id", "row_sha", *FIELDS, "status", "missing_fields", "annotation_provenance"}
        require(set(human) == row_keys, "Unexpected supplemental row fields")
        require(human.get("status") == "complete" and human.get("missing_fields") == [], "Incomplete human row")
        require(isinstance(human.get("annotation_provenance"), dict) and set(human["annotation_provenance"]) == set(FIELDS), "Unexpected supplemental provenance fields")
        new = corrected_by_id[rid]
        for field in FIELDS:
            value = human[field]
            require(valid(field, value, source["review_text"]), f"Invalid human {field}")
            same = strict_equal(value, item["initial"][field])
            raw_origin = (item["initial_provenance"].get(field) or "preserved_original") if same else ("not_assessed" if value is None else "supplemental_human")
            require(human["annotation_provenance"][field] == raw_origin, "Supplemental provenance differs from recomputed origin")
            if same:
                continue
            changes.append({"review_id": rid, "row_sha": source_hash, "field": field, "before": item["initial"][field], "after": value})
            previous_origin = old["annotation_provenance"].get(field)
            new_origin = "not_assessed" if value is None or field == "notes" and value == "" else "annotated"
            new[field] = copy.deepcopy(value)
            if field != "notes":
                new["annotation_provenance"][field] = new_origin
            histories.append({"review_id": rid, "source_row_sha256": source_hash,
                              "golden_position": i, "worksheet_position": item["worksheet_position"],
                              "field": field, "before": copy.deepcopy(old.get(field)), "after": copy.deepcopy(value),
                              "previous_provenance": previous_origin, "new_provenance": new_origin if field != "notes" else previous_origin,
                              "source": "explicit_human_course_supplement"})
    require(strict_equal(supplement.get("changes"), changes), "Supplement change list differs from recomputed changes")
    # Exactly the approved golden primary fields may differ; all other labels,
    # private original notes/history and source identities remain copied verbatim.
    for rid, old in original_by_id.items():
        new = corrected_by_id[rid]
        if rid not in by_id:
            require(new == old, "A non-golden record changed")
        else:
            require({k: v for k, v in new.items() if k not in FIELDS and k != "annotation_provenance"} ==
                    {k: v for k, v in old.items() if k not in FIELDS and k != "annotation_provenance"}, "Unexpected golden metadata change")
    return new_reference, histories, meta, supplement


def validate_ai_inputs(reference_bytes, supplement_bytes, worksheet_bytes, golden_bytes, ai_snapshot_bytes, *, reference_sha256, supplement_sha256, snapshot_sha256):
    """Require explicit human confirmation of every draft-bearing row before import."""
    require(sha(supplement_bytes) == supplement_sha256, "AI supplement checksum mismatch")
    require(len(supplement_bytes) <= 2_000_000, "Supplement exceeds worksheet size limit")
    ai_meta, raw = loads(ai_snapshot_bytes), loads(supplement_bytes)
    require(ai_meta.get("schema_version") == "spotify-course-golden-ai-review-v1", "Unexpected AI worksheet schema")
    require(sha(canonical({k: v for k, v in ai_meta.items() if k != "snapshot_sha256"}).encode()) == ai_meta.get("snapshot_sha256") == snapshot_sha256,
            "AI worksheet snapshot checksum mismatch")
    require(sha(canonical(ai_meta["draft_document"]).encode()) == ai_meta.get("ai_draft_sha256"), "AI draft document checksum mismatch")
    matches = re.findall(r'<script\b[^>]*\bid="worksheet-data"[^>]*>(.*?)</script>', worksheet_bytes.decode("utf-8"), re.S)
    require(len(matches) == 1, "Expected original manual worksheet metadata")
    manual_meta = loads(matches[0])
    require(ai_meta.get("parent_human_worksheet_snapshot_sha256") == manual_meta.get("snapshot_sha256"), "AI worksheet parent snapshot mismatch")
    ai_keys = {*IDENTITY_KEYS, "ai_draft_sha256", "parent_human_worksheet_snapshot_sha256"}
    expected_top = {*ai_keys, "evaluation_status", "exported_at", "complete", "labels", "changes", "validation_errors"}
    require(isinstance(raw, dict) and set(raw) == expected_top, "Unexpected AI supplement fields")
    for key in ai_keys:
        require(raw.get(key) == ai_meta.get(key), f"AI supplement {key} mismatch")
    for key in ("source_annotation_sha256", "golden_source_sha256", "rubric_sha256"):
        require(ai_meta.get(key) == manual_meta.get(key), "AI worksheet parent identity mismatch")
    require(raw.get("evaluation_status") == ai_meta.get("evaluation_status") == AI_STATUS, "AI evaluation status mismatch")
    require(raw.get("complete") is True and raw.get("validation_errors") == [], "AI supplement contains pending or invalid review")
    require(isinstance(raw.get("labels"), list) and len(raw["labels"]) == 50, "Expected 50 AI-review rows")
    require(isinstance(raw.get("exported_at"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", raw["exported_at"]) is not None, "AI export timestamp format mismatch")
    export_time = datetime.fromisoformat(raw["exported_at"].replace("Z", "+00:00"))
    require(export_time.tzinfo is not None, "AI export timestamp must include timezone")
    ai_items = ai_meta.get("items")
    require(isinstance(ai_items, list) and len(ai_items) == 50, "Expected 50 AI metadata rows")
    require([item["review_id"] for item in ai_items] == [item["review_id"] for item in manual_meta["items"]], "AI worksheet row identities/order changed")
    suggestions = ai_meta["draft_document"]["suggestions"]
    require(isinstance(suggestions, list), "AI suggestions must be a list")
    suggestion_by_id = {row["review_id"]: row for row in suggestions}
    require(len(suggestion_by_id) == len(suggestions), "Duplicate AI suggestion IDs")
    raw_by_id = {row["review_id"]: row for row in raw["labels"]}
    require(len(raw_by_id) == 50 and set(raw_by_id) == {item["review_id"] for item in ai_items}, "Duplicate/foreign AI-review IDs")
    transformed = {key: copy.deepcopy(raw[key]) for key in (*IDENTITY_KEYS, "evaluation_status", "exported_at", "complete", "changes", "validation_errors")}
    transformed.update({key: manual_meta[key] for key in IDENTITY_KEYS})
    transformed["evaluation_status"] = STATUS
    transformed["labels"] = []
    confirmed = {}
    for item, original in zip(ai_items, manual_meta["items"]):
        require({key: value for key, value in item.items() if key not in {"draft_fields", "ai_draft"}} == original, "AI metadata changed original human baseline")
        drafts = item["draft_fields"]
        require(isinstance(drafts, list) and len(drafts) == len(set(drafts)) and set(drafts) == {field for field in REQUIRED if original["initial"][field] is None},
                "AI draft scope must equal originally unannotated required fields")
        suggestion = item["ai_draft"]
        if drafts:
            require(suggestion == suggestion_by_id.get(item["review_id"]), "AI draft inventory mismatch")
            require(suggestion["row_sha"] == item["row_sha"] and suggestion["golden_position"] == item["golden_position"], "AI suggestion source mismatch")
            require(set(suggestion["suggestions"]) == set(drafts) and all(valid(field, suggestion["suggestions"][field], item["review_text"]) for field in drafts), "Invalid AI suggestion scope/value")
        else:
            require(suggestion is None and item["review_id"] not in suggestion_by_id, "Unexpected AI suggestion for complete original row")
        row = raw_by_id[item["review_id"]]
        keys = {"review_id", "row_sha", *FIELDS, "status", "missing_fields", "annotation_provenance", "draft_fields", "reviewed", "reviewed_at", "reviewed_values", "review_status"}
        require(set(row) == keys and row["draft_fields"] == drafts, "Unexpected AI-review row scope/fields")
        require(type(row["reviewed"]) is bool, "Review confirmation must be Boolean")
        require(isinstance(row["annotation_provenance"], dict) and set(row["annotation_provenance"]) == set(FIELDS), "AI-review provenance fields mismatch")
        if drafts:
            require(row["reviewed"] is True and row["review_status"] == "ai_assisted_human_confirmed", "AI suggestions are not human confirmed")
            require(isinstance(row["reviewed_at"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", row["reviewed_at"]) is not None, "Missing/invalid human confirmation timestamp")
            reviewed_time = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
            require(reviewed_time.tzinfo is not None and reviewed_time <= export_time, "Invalid/future human confirmation timestamp")
            require(strict_equal(row["reviewed_values"], {field: row[field] for field in FIELDS}), "Human confirmation does not match current values")
            confirmed[row["review_id"]] = {"draft_fields": list(drafts), "reviewed_at": row["reviewed_at"]}
        else:
            require(row["reviewed"] is False and row["reviewed_at"] is None and row["reviewed_values"] is None and row["review_status"] == "preserved_existing_human",
                    "Unexpected confirmation on a non-draft row")
        clean = {key: copy.deepcopy(value) for key, value in row.items() if key not in {"draft_fields", "reviewed", "reviewed_at", "reviewed_values", "review_status"}}
        for field in FIELDS:
            same = strict_equal(row[field], original["initial"][field])
            manual_origin = (original["initial_provenance"].get(field) or "preserved_original") if same else ("not_assessed" if row[field] is None else "supplemental_human")
            expected = "ai_assisted_human_confirmed" if field in drafts else manual_origin
            require(row["annotation_provenance"][field] == expected, "AI-reviewed field provenance mismatch")
            clean["annotation_provenance"][field] = manual_origin
        transformed["labels"].append(clean)
    require(set(suggestion_by_id) == set(confirmed), "AI suggestion inventory not fully human confirmed")
    transformed_bytes = (json.dumps(transformed, ensure_ascii=False, allow_nan=False) + "\n").encode()
    new_reference, changes, _, _ = validate_inputs(reference_bytes, transformed_bytes, worksheet_bytes, golden_bytes,
        reference_sha256=reference_sha256, supplement_sha256=sha(transformed_bytes), snapshot_sha256=manual_meta["snapshot_sha256"])
    for row in new_reference["labels"]:
        if row["review_id"] in confirmed:
            info = confirmed[row["review_id"]]
            row.setdefault("course_annotation_methods", {}).update({field: "ai_assisted_human_confirmed" for field in info["draft_fields"]})
            row["course_human_confirmation"] = {**info, "snapshot_sha256": snapshot_sha256, "ai_draft_sha256": ai_meta["ai_draft_sha256"]}
    for change in changes:
        info = confirmed.get(change["review_id"])
        if info and change["field"] in info["draft_fields"]:
            change["source"] = "ai_assisted_human_confirmed"
            change["human_confirmed_at"] = info["reviewed_at"]
    ai_meta = copy.deepcopy(ai_meta)
    ai_meta["human_confirmed_ai_rows"] = len(confirmed)
    ai_meta["human_confirmed_ai_fields"] = sum(len(info["draft_fields"]) for info in confirmed.values())
    return new_reference, changes, ai_meta, raw


def run(args):
    sources = {"reference": args.reference, "supplement": args.supplement, "worksheet": args.worksheet, "golden_source": args.golden_source}
    if getattr(args, "ai_snapshot", None) is not None:
        sources["ai_snapshot"] = args.ai_snapshot
    original_bytes = {name: path.read_bytes() for name, path in sources.items()}
    validate = validate_ai_inputs if "ai_snapshot" in original_bytes else validate_inputs
    positional = [original_bytes[name] for name in ("reference", "supplement", "worksheet", "golden_source")]
    if "ai_snapshot" in original_bytes:
        positional.append(original_bytes["ai_snapshot"])
    reference, changes, meta, supplement = validate(*positional, reference_sha256=args.reference_sha256,
        supplement_sha256=args.supplement_sha256, snapshot_sha256=args.snapshot_sha256)
    out = args.out.resolve()
    reference_parts = args.reference.resolve().parts
    private_roots = [Path(*reference_parts[:i + 2]) for i in range(len(reference_parts) - 1)
                     if reference_parts[i:i + 2] == ("private", "human-labels")]
    require(len(private_roots) == 1 and out.is_relative_to(private_roots[0]) and out != private_roots[0],
            "Corrected references and histories must stay within the reference's private/human-labels directory")
    require(not out.exists(), "Output already exists; choose a NEW version")
    require(all(out != path.resolve() and out not in path.resolve().parents for path in sources.values()), "Output overlaps an input")
    now = datetime.now(timezone.utc).isoformat()
    provenance = {"version": args.version, "recorded_at": now, "human_exported_at": supplement["exported_at"],
                  "parent_reference_sha256": args.reference_sha256, "supplement_sha256": args.supplement_sha256,
                  "snapshot_sha256": args.snapshot_sha256, "rubric_sha256": meta["rubric_sha256"],
                  "golden_source_sha256": meta["golden_source_sha256"], "scope": "official_golden_50_only",
                  "golden_rows": 50, "required_fields_complete": list(REQUIRED),
                  "new_labels_inferred_by_importer": 0, "frozen_hero_predictions_consulted": False,
                  "evaluation_status": meta["evaluation_status"], "changed_field_count": len(changes),
                  "change_counts": dict(sorted(Counter(row["field"] for row in changes).items()))}
    if "ai_snapshot" in original_bytes:
        provenance.update(ai_draft_sha256=meta["ai_draft_sha256"],
                          human_confirmed_ai_rows=meta["human_confirmed_ai_rows"],
                          human_confirmed_ai_fields=meta["human_confirmed_ai_fields"],
                          raw_ai_suggestions_counted_without_human_confirmation=0)
    # Distinguish explicit supplemental human edits from confirmed AI suggestions
    # without changing the frozen evaluator's annotated/not_assessed vocabulary.
    by_id = {row["review_id"]: row for row in reference["labels"]}
    for change in changes:
        if change["field"] != "notes":
            by_id[change["review_id"]].setdefault("course_annotation_methods", {}).setdefault(change["field"], "supplemental_human")
    history = {"schema_version": "human-course-supplement-changes-v1", **provenance, "changes": changes,
               "privacy": "PRIVATE: per-field history may include private human notes. Never publish this file."}
    history_bytes = (json.dumps(history, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    reference["course_supplement"] = provenance
    reference["evaluation_status"] = meta["evaluation_status"]
    reference.setdefault("revision_history", []).append({**provenance, "change_log_sha256": sha(history_bytes)})
    # Preserve annotation_protocol and the original source digest. Other 150 rows
    # remain sparse; golden completion does not declare the entire worksheet complete.
    corrected_bytes = (json.dumps(reference, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    require(all(path.read_bytes() == original_bytes[name] for name, path in sources.items()), "An input changed during import")
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".course-supplement-", dir=out.parent))
    try:
        files = {"annotations.corrected.json": corrected_bytes, "changes.private.json": history_bytes,
                 "supplement.original.json": original_bytes["supplement"], "parent.original.json": original_bytes["reference"]}
        if "ai_snapshot" in original_bytes:
            files["ai-draft-snapshot.private.json"] = original_bytes["ai_snapshot"]
        validation = {"passed": True, "version": args.version, "source_inputs_unchanged": True,
                      "reference_record_count": 200, "golden_record_count": 50, "untouched_other_records": 150,
                      "explicit_complete_golden_fields": list(REQUIRED), "raw_parent_sha256": args.reference_sha256,
                      "corrected_sha256": sha(corrected_bytes), "supplement_sha256": args.supplement_sha256,
                      "snapshot_sha256": args.snapshot_sha256, "changes": len(changes),
                      "field_change_counts": provenance["change_counts"], "public_exports_written": False,
                      "files": {name: {"sha256": sha(data), "bytes": len(data)} for name, data in files.items()}}
        files["validation.json"] = (json.dumps(validation, indent=2) + "\n").encode()
        for name, data in files.items():
            with (staging / name).open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            (staging / name).chmod(0o600)
        staging.chmod(0o700)
        require(all(path.read_bytes() == original_bytes[name] for name, path in sources.items()), "An input changed before atomic publication")
        require(not out.exists(), "Output appeared concurrently; refusing overwrite")
        staging.rename(out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({"output": str(out), "passed": True, "corrected_sha256": sha(corrected_bytes),
                      "changes": len(changes), "golden_complete": 50, "public_exports_written": False}))
    return validation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "supplement", "worksheet", "golden-source", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("reference-sha256", "supplement-sha256", "snapshot-sha256", "version"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--ai-snapshot", type=Path)
    run(parser.parse_args())
