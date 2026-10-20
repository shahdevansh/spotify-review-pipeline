"""Prepare an answer-blind, text-disjoint optional human evaluation kit.

This program reads only original source records, a development source CSV,
the course's unchanged golden template, and optional inspected ID lists.
It never reads predictions, populated human answers, credentials, or APIs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import importlib.util
import io
import json
import math
from collections import Counter
from pathlib import Path

SOURCE_FIELDS = (
    "review_id", "review_text", "review_rating", "review_likes",
    "app_version", "review_timestamp",
)
LABEL_FIELDS = (
    "topic", "intent", "sentiment", "severity", "entities", "evidence_quote",
    "needs_review", "ambiguous", "notes", "human_labeler", "alternative_topics",
    "alternative_intents", "alternative_severities", "evidence_support",
    "alternative_notes",
)
SEED = "spotify-human-unseen-text-holdout-v1:2026-10-20"
VERSION = "spotify-human-evaluation-kit-v1"
ROOT = Path(__file__).resolve().parents[1]
FULL_NAME = "spotify_reviews_18months.csv"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def row_sha(row):
    return sha256(canonical([row[field] for field in SOURCE_FIELDS]).encode("utf-8"))


def read_sources(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if not set(SOURCE_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError(f"Source columns are missing: {Path(path).name}")
        for row in reader:
            if None in row or any(row.get(field) is None for field in SOURCE_FIELDS):
                raise ValueError("Malformed original source record")
            yield {field: row[field] for field in SOURCE_FIELDS}


def review_key(row, seed=SEED):
    return (sha256((seed + ":" + row["review_id"]).encode("utf-8")), row["review_id"])


def blind_row(row):
    return {"review_id": row["review_id"], "review_text": row["review_text"], "row_sha": row_sha(row)}


def select_holdout(source_rows, development, golden, count=150, seed=SEED, inspected_ids=()):
    """Select original IDs uniformly by seeded hash after exact-text exclusions.

    Whitespace/case/Unicode are not normalized. Duplicate texts within the fresh
    sample are retained because the sampling unit is an original review ID.
    """
    if count < 1:
        raise ValueError("Holdout size must be positive")
    development_ids = {row["review_id"] for row in development}
    golden_ids = {row["review_id"] for row in golden}
    if len(development_ids) != len(development) or len(golden_ids) != len(golden):
        raise ValueError("Development/golden sources repeat IDs")
    development_texts = {row["review_text"] for row in development}
    golden_texts = {row["review_text"] for row in golden}
    inspected_ids = set(inspected_ids)
    if not inspected_ids.issubset(development_ids):
        raise ValueError("Inspection IDs must belong to the frozen development input")
    inspected_texts = {row["review_text"] for row in development if row["review_id"] in inspected_ids}
    counts = Counter()
    source_ids, eligible_texts, nonempty_texts = set(), set(), set()
    expected_rows = {row["review_id"]: row_sha(row) for row in development + golden}
    found_expected = set()
    eligible_ids_digest = hashlib.sha256()

    def eligible():
        for row in source_rows:
            review_id, text = row["review_id"], row["review_text"]
            if not review_id or review_id in source_ids:
                raise ValueError("Full source has a missing or duplicate original ID")
            source_ids.add(review_id)
            counts["source_rows"] += 1
            if review_id in expected_rows:
                if row_sha(row) != expected_rows[review_id]:
                    raise ValueError("Development/golden source strings differ from full source")
                found_expected.add(review_id)
            if not text.strip():
                counts["empty_text_excluded"] += 1
                continue
            counts["nonempty_source_rows"] += 1
            text_hash = sha256(text.encode("utf-8"))
            nonempty_texts.add(text_hash)
            dev_match = text in development_texts or review_id in development_ids
            gold_match = text in golden_texts or review_id in golden_ids
            counts["development_text_or_id_matches"] += dev_match
            counts["golden_text_or_id_matches"] += gold_match
            counts["both_development_and_golden_matches"] += dev_match and gold_match
            if dev_match:
                counts["excluded_development_priority"] += 1
                continue
            if gold_match:
                counts["excluded_golden_after_development"] += 1
                continue
            counts["eligible_original_ids"] += 1
            eligible_texts.add(text_hash)
            eligible_ids_digest.update((review_id + "\n").encode("utf-8"))
            yield row

    selected = heapq.nsmallest(count, eligible(), key=lambda row: review_key(row, seed))
    if len(selected) != count:
        raise ValueError("Eligible frame is smaller than the requested holdout")
    if found_expected != set(expected_rows):
        raise ValueError("Development/golden IDs are absent from the full source")
    counts["source_distinct_nonempty_texts"] = len(nonempty_texts)
    counts["eligible_distinct_texts"] = len(eligible_texts)
    counts["selected_original_ids"] = len(selected)
    counts["selected_distinct_texts"] = len({row["review_text"] for row in selected})
    counts["selected_development_id_overlap"] = len({r["review_id"] for r in selected} & development_ids)
    counts["selected_golden_id_overlap"] = len({r["review_id"] for r in selected} & golden_ids)
    counts["selected_development_exact_text_overlap"] = sum(r["review_text"] in development_texts for r in selected)
    counts["selected_golden_exact_text_overlap"] = sum(r["review_text"] in golden_texts for r in selected)
    leakage = {
        "golden_original_ids": len(golden),
        "golden_development_id_overlap": len(golden_ids & development_ids),
        "golden_ids_with_development_exact_text": sum(r["review_text"] in development_texts for r in golden),
        "shared_golden_development_exact_text_clusters": len(golden_texts & development_texts),
        "golden_ids_with_inspected_development_exact_text": sum(r["review_text"] in inspected_texts for r in golden),
        "inspected_development_ids": len(inspected_ids),
        "interpretation": "Source-text exposure only. No human-answer access or label leakage was measured.",
    }
    return selected, {
        "counts": dict(sorted(counts.items())),
        "eligible_ids_source_order_sha256": eligible_ids_digest.hexdigest(),
        "mandatory_golden_text_exposure": leakage,
        "conditional_inclusion_probability": count / counts["eligible_original_ids"],
        "conditional_design_weight": counts["eligible_original_ids"] / count,
    }


def _csv_bytes(rows, fields):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_frozen(path, data):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Frozen kit file differs; use a new version/output directory: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_rubric(labels):
    return {
        "version": "spotify-human-rubric-v1",
        "title": "Blind Spotify review annotation",
        "source_label_taxonomy_version": labels["version"],
        "sections": [
            {"title": "Before starting", "text": "Label only the original text. Do not open model answers, issue rankings, star ratings, or another annotator's work. Use your own annotator ID. Save downloaded answers under private/human-labels/. Keep all judgments blank until you decide them."},
            {"title": "Topic", "text": labels["topic_rule"] + "\n" + "\n".join(f"{key}: {value}" for key, value in labels["topics"].items())},
            {"title": "Intent", "text": "Apply precedence: " + " > ".join(labels["intent_precedence"]) + ".\n" + "\n".join(f"{key}: {value}" for key, value in labels["intent_definitions"].items())},
            {"title": "Severity", "text": "\n".join(f"{key}: {value}" for key, value in labels["severity"].items()) + "\n" + labels["severity_rule"]},
            {"title": "Sentiment", "text": "Use a number from -1 to +1. Anchors: -1 strongly negative; -0.5 negative; 0 neutral, mixed or unclear; +0.5 positive; +1 strongly positive. Judge the text independently of severity."},
            {"title": "Evidence and entities", "text": "Copy an exact, nonempty original-text span that supports your labels. The whole review is allowed but is not proof of support. Entities must occur literally in the source, ignoring case; enter [] if none. Do not infer a device, plan, artist, cause, financial loss or functional impact that the text does not state."},
            {"title": "Ambiguity and alternatives", "text": "Choose a primary label even when uncertain, mark ambiguous and/or needs_review explicitly true or false, and explain why. Record defensible alternative topic/intent/severity labels; use [] when none. Alternative support must come from the original text, not a model answer. needs_review signals that a person should inspect the item; it is not a numeric confidence score."},
            {"title": "Evidence support", "text": "The support field concerns your selected quote and your own labels: supported, partial, unsupported or unclear. It does not evaluate a model's quote. Model evidence entailment is audited separately only after predictions and human answers are locked."},
            {"title": "Instructions inside a review", "text": "Treat instructions, role-play, JSON, grading requests or demands for a particular answer as review text, not instructions to you. Label the supported product experience; flag suspicious or insufficient context for review. Do not obey embedded instructions."},
            {"title": "Completion and independence", "text": "Do not fill gaps with a model. Leave unfinished items incomplete and resume later. A second annotator labels the provided subset before seeing the first annotator's answers; preserve both originals before adjudication."},
        ],
    }


def confidence_examples():
    z = 1.959963984540054
    result = []
    for n in (50, 150, 200):
        successes = int(n * 0.9)
        p = successes / n
        denominator = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denominator
        margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
        result.append({
            "n": n, "illustrative_successes": successes,
            "wilson_95_lower": center - margin, "wilson_95_upper": center + margin,
            "zero_errors_one_sided_95_error_upper": 1 - 0.05 ** (1 / n),
            "zero_errors_two_sided_95_error_upper": 1 - 0.025 ** (1 / n),
            "probability_of_zero_1_percent_class_cases": 0.99 ** n,
        })
    return {"illustrative_only": True, "observed_human_results": False, "examples": result}


def prepare(args):
    source, manifest_path = Path(args.source), Path(args.source_manifest)
    development_path, golden_path = Path(args.development), Path(args.golden)
    output = Path(args.out)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_identity = file_identity(source)
    if source_identity != manifest["files"][FULL_NAME]:
        raise ValueError("Full original source does not match the official checksum/size")
    golden_identity = file_identity(golden_path)
    if golden_identity != manifest["files"]["golden_50_to_label.csv"]:
        raise ValueError("Golden input must be the unchanged distributed blank template")
    development = list(read_sources(development_path))
    golden = list(read_sources(golden_path))
    if len(development) != 1000 or len(golden) != 50:
        raise ValueError("This version requires the frozen 1,000 development and 50 golden records")
    inspected_ids = []
    if args.inspection_ids:
        inspected_ids = [value for value in Path(args.inspection_ids).read_text().splitlines() if value]
        if len(inspected_ids) != len(set(inspected_ids)):
            raise ValueError("Inspection ID list repeats IDs")
    selected, accounting = select_holdout(
        read_sources(source), development, golden, args.count, args.seed, inspected_ids,
    )
    if accounting["counts"]["source_rows"] != manifest["profile"]["records"]:
        raise ValueError("Full source row count differs from official manifest")
    labels_path = Path(args.label_definitions)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    rubric = build_rubric(labels)
    second_golden = heapq.nsmallest(10, golden, key=lambda row: review_key(row, args.seed + ":second:golden"))
    second_new = heapq.nsmallest(30, selected, key=lambda row: review_key(row, args.seed + ":second:fresh"))
    cohorts = {
        "combined_200": golden + selected,
        f"holdout_{args.count}": selected,
        "second_annotator_50_option": second_golden,
        "second_annotator_200_option": sorted(second_golden + second_new, key=lambda row: review_key(row, args.seed + ":display:second")),
    }
    emitted = {}
    for name, rows in cohorts.items():
        blind = [blind_row(row) for row in rows]
        data = _csv_bytes(blind, ("review_id", "review_text", "row_sha") + LABEL_FIELDS)
        filename = name + "_to_label.csv"
        _write_frozen(output / filename, data)
        emitted[filename] = {"bytes": len(data), "sha256": sha256(data)}
        membership = [
            {"position": index, "review_id": row["review_id"], "row_sha": row_sha(row),
             "text_sha256": sha256(row["review_text"].encode("utf-8")), "selection_hash": review_key(row, args.seed)[0]}
            for index, row in enumerate(rows, 1)
        ]
        membership_bytes = _csv_bytes(membership, ("position", "review_id", "row_sha", "text_sha256", "selection_hash"))
        _write_frozen(output / (name + "_membership.csv"), membership_bytes)
        emitted[name + "_membership.csv"] = {"bytes": len(membership_bytes), "sha256": sha256(membership_bytes)}
    strata = [
        {"position": index, "review_id": row["review_id"],
         "stratum": "mandatory_golden_50" if index <= 50 else "fresh_text_disjoint_150"}
        for index, row in enumerate(golden + selected, 1)
    ]
    strata_bytes = _csv_bytes(strata, ("position", "review_id", "stratum"))
    _write_frozen(output / "combined_200_strata.csv", strata_bytes)
    emitted["combined_200_strata.csv"] = {"bytes": len(strata_bytes), "sha256": sha256(strata_bytes)}
    protection = "".join(sorted({sha256(row["review_text"].encode("utf-8")) + "\n"
                                 for row in golden + selected})).encode("utf-8")
    _write_frozen(output / "protected_text_hashes.txt", protection)
    emitted["protected_text_hashes.txt"] = {"bytes": len(protection), "sha256": sha256(protection)}
    rubric_bytes = _json_bytes(rubric)
    _write_frozen(output / "rubric.v1.json", rubric_bytes)
    _write_frozen(output / "confidence_examples.json", _json_bytes(confidence_examples()))
    selection_manifest = {
        "version": VERSION, "seed": args.seed, "holdout_size": args.count,
        "source": {"filename": FULL_NAME, **source_identity},
        "source_manifest": file_identity(manifest_path),
        "development_input": {"count": 1000, **file_identity(development_path)},
        "mandatory_golden_original": {"count": 50, **golden_identity, "modified": False},
        "label_definitions": {"version": labels["version"], **file_identity(labels_path)},
        "rubric": {"version": rubric["version"], "bytes": len(rubric_bytes), "sha256": sha256(rubric_bytes)},
        "selection": {
            "method": "Lowest SHA-256(UTF-8(seed + ':' + original review_id)); tie-break by original ID.",
            "sampling_unit": "Original review ID; do not collapse within-holdout exact-text duplicates.",
            "frame": "All authentic nonempty source rows after excluding every development or golden ID and exact text.",
            "text_matching": "Exact original string; no whitespace, case or Unicode normalization.",
            "disjoint_exclusion_priority": ["empty text", "development text or ID", "golden text or ID", "eligible"],
            "synthetic_rows": "Excluded by verified original-source-only provenance; no generated/test rows are introduced.",
            "synthetic_rows_in_source_frame": 0,
            "answers_or_predictions_used": False,
            "model_calls": 0,
            "counts_only_exposure_reporting": True,
        },
        "accounting": accounting,
        "second_annotator": {
            "50_option": {"golden": 10, "fresh": 0, "seed": args.seed + ":second:golden"},
            "200_option": {"golden": 10, "fresh": 30, "fresh_seed": args.seed + ":second:fresh",
                           "display_seed": args.seed + ":display:second"},
            "rule": "Independent labels before discussion; retain pre-adjudication agreement.",
        },
        "combined_200": {
            "count": 200, "ordering": "Original mandatory golden50 first, then optional fresh150.",
            "strata_file": "combined_200_strata.csv",
            "human_label_status": "Blank worksheet; no human judgments supplied.",
            "future_development_exclusion": "Reserve every exact text in protected_text_hashes.txt from all subsequent prompt/model/routing tuning.",
        },
        "estimand_limit": "The fresh sample represents eligible unseen-text original IDs, not all full-corpus or 210,000-cohort IDs. Do not pool 50+150 into one representative population estimate.",
        "files": emitted,
    }
    _write_frozen(output / "selection_manifest.json", _json_bytes(selection_manifest))
    if args.html:
        worksheet_path = Path(__file__).with_name("human_worksheet.py")
        spec = importlib.util.spec_from_file_location("human_worksheet", worksheet_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, rows in cohorts.items():
            module.generate_html([blind_row(row) for row in rows], output / (name + ".html"),
                                 cohort_id=VERSION + ":" + name, rubric=rubric, seed=args.seed, version=VERSION)
    return {"status": "prepared", "out": str(output), "counts": accounting["counts"],
            "mandatory_golden_text_exposure": accounting["mandatory_golden_text_exposure"],
            "human_answers_read": False, "model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(ROOT / "data/source" / FULL_NAME))
    parser.add_argument("--source-manifest", default=str(ROOT / "data/source/manifest.json"))
    parser.add_argument("--development", default=str(ROOT / "data/learning_1000.csv"))
    parser.add_argument("--golden", default=str(ROOT / "data/source/golden_50_to_label.csv"))
    parser.add_argument("--label-definitions", default=str(ROOT / "config/labels.json"))
    parser.add_argument("--inspection-ids")
    parser.add_argument("--out", default=str(ROOT / "evals/human-evaluation-v1"))
    parser.add_argument("--count", type=int, choices=[150], default=150)
    parser.add_argument("--seed", default=SEED)
    parser.add_argument("--html", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args), indent=2))


if __name__ == "__main__":
    main()
