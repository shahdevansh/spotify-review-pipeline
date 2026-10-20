"""Offline diagnostics, with human golden labels separated from model agreement."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .analysis import TOPICS, load_records, write_csv, write_json

FIELDS = ("topic", "intent", "severity", "sentiment", "needs_review")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")


def _boolean(value: Any) -> bool:
    if type(value) is bool:
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
        return False
    raise ValueError(f"Expected explicit boolean, received {value!r}")


def _accepted(row: dict, field: str) -> list:
    alternate = row.get("accepted_" + field)
    values = json.loads(alternate) if alternate and alternate.strip() else [row[field]]
    if not isinstance(values, list) or not values:
        raise ValueError(f"accepted_{field} must be a nonempty JSON array")
    if field == "severity":
        if any(str(v) not in {"1", "2", "3", "4", "5"} for v in values):
            raise ValueError("Human severity must be an integer from one to five.")
        return [int(v) for v in values]
    allowed = TOPICS if field == "topic" else INTENTS
    if any(v not in allowed for v in values):
        raise ValueError(f"Invalid human {field} labels")
    return values


def evidence_checks(record: dict, text: str) -> dict:
    quote = record.get("evidence_quote")
    entities = record.get("entities")
    if not isinstance(entities, list):
        entities = []
    unsupported = [entity for entity in entities
                   if not isinstance(entity, str) or not entity.strip() or entity.casefold() not in text.casefold()]
    return {"quote_exact_substring": isinstance(quote, str) and bool(quote.strip()) and quote in text,
            "entities_unsupported_literal": unsupported,
            "semantic_evidence_support": "requires_human_inspection"}


def evaluate_golden(golden_csv: str | Path, records_path: Any, output_dir: str | Path,
                    *, human_labels_confirmed: bool = False, expected_count: int = 50,
                    sentiment_tolerance: float = 0.25,
                    golden_source_path: str | Path | None = None) -> dict:
    """Require complete human answers. Missing predictions remain in denominators.

    A blank worksheet returns an explicit pending report, never synthetic accuracy.
    ``human_labels_confirmed`` is an attestation about provenance, not a way to
    generate labels. Never pass these labels to an enrichment/model task.
    """
    with Path(golden_csv).open(encoding="utf-8-sig", newline="") as handle:
        expected = list(csv.DictReader(handle))
    output = Path(output_dir)
    required = ("topic", "intent", "severity", "sentiment", "needs_review", "evidence_quote", "entities")
    incomplete = [r.get("review_id") for r in expected if any(not str(r.get(k, "")).strip() for k in required)]
    ids = [r.get("review_id") for r in expected]
    if len(set(ids)) != len(ids) or any(not rid for rid in ids):
        raise ValueError("Golden labels contain duplicate or missing review IDs.")
    if len(expected) != expected_count or incomplete:
        report = {"status": "pending_human_labels", "human_ground_truth": True,
                  "expected_count": expected_count, "received_count": len(expected),
                  "incomplete_ids": incomplete, "metrics": None,
                  "limitations": ["No golden accuracy was computed from incomplete human labels."]}
        write_json(output / "golden_report.json", report)
        return report
    if golden_source_path is None and expected_count == 50:
        candidate = Path(__file__).resolve().parents[2] / "data/source/golden_50_to_label.csv"
        if candidate.exists():
            golden_source_path = candidate
    source_checked = False
    if golden_source_path is not None:
        with Path(golden_source_path).open(encoding="utf-8-sig", newline="") as handle:
            original = {row["review_id"]: row["review_text"] for row in csv.DictReader(handle)}
        if set(original) != set(ids) or any(row["review_text"] != original[row["review_id"]] for row in expected):
            raise ValueError("Human label IDs or original texts differ from the isolated source golden set.")
        source_checked = True
    attested = human_labels_confirmed or all(str(r.get("human_labeler", "")).strip() for r in expected)
    if not attested:
        raise ValueError("Confirm that these labels were independently supplied by a human with --human-labels-confirmed.")
    predictions = {r["review_id"]: r for r in load_records(records_path)}
    if not 0 <= sentiment_tolerance <= 2:
        raise ValueError("Sentiment tolerance must be between zero and two.")
    cases, confusion, support = [], defaultdict(Counter), Counter()
    for human in expected:
        rid = human["review_id"]
        pred = predictions.get(rid, {})
        valid = pred.get("status") == "completed"
        allowed = {field: _accepted(human, field) for field in ("topic", "intent", "severity")}
        sentiment = float(human["sentiment"])
        if not math.isfinite(sentiment) or not -1 <= sentiment <= 1:
            raise ValueError(f"Invalid human sentiment: {rid}")
        needs_review = _boolean(human["needs_review"])
        entities = json.loads(human["entities"])
        if not isinstance(entities, list) or any(not isinstance(e, str) for e in entities):
            raise ValueError(f"Human entities must be a JSON string array: {rid}")
        text = human["review_text"]
        if human["evidence_quote"] not in text or not human["evidence_quote"].strip():
            raise ValueError(f"Human evidence quote does not occur in source: {rid}")
        ambiguous = (_boolean(human["ambiguous"]) if str(human.get("ambiguous", "")).strip()
                     else any(len(values) > 1 for values in allowed.values()))
        matches = {field: valid and pred.get(field) in allowed[field] for field in allowed}
        severity_error = (min(abs(pred["severity"] - n) for n in allowed["severity"])
                          if valid and type(pred.get("severity")) is int else None)
        sentiment_error = (abs(pred["sentiment"] - sentiment)
                           if valid and type(pred.get("sentiment")) in (float, int) else None)
        checks = evidence_checks(pred, text)
        case = {
            "review_id": rid, "prediction_status": pred.get("status", "missing"), "ambiguous": ambiguous,
            "expected": {**allowed, "sentiment": sentiment, "needs_review": needs_review,
                         "entities": entities, "evidence_quote": human["evidence_quote"]},
            "prediction": {key: pred.get(key) for key in (*FIELDS, "entities", "evidence_quote")},
            "correct": {**matches, "needs_review": valid and pred.get("needs_review") is needs_review,
                        "sentiment_within_tolerance": sentiment_error is not None and sentiment_error <= sentiment_tolerance,
                        "entities_exact": valid and set(pred.get("entities", [])) == set(entities)},
            "severity_absolute_error": severity_error, "sentiment_absolute_error": sentiment_error,
            **checks,
        }
        cases.append(case)
        support["|".join(allowed["topic"])] += 1
        for field in ("topic", "intent"):
            confusion[field][("|".join(allowed[field]), str(pred.get(field, "__missing__")))] += 1
    n = len(cases)
    severity_errors = [c["severity_absolute_error"] for c in cases if c["severity_absolute_error"] is not None]
    sentiment_errors = [c["sentiment_absolute_error"] for c in cases if c["sentiment_absolute_error"] is not None]
    nr_tp = sum(c["prediction"]["needs_review"] is True and c["expected"]["needs_review"] is True for c in cases)
    nr_fp = sum(c["prediction"]["needs_review"] is True and c["expected"]["needs_review"] is False for c in cases)
    nr_fn = sum(c["prediction"]["needs_review"] is not True and c["expected"]["needs_review"] is True for c in cases)
    metrics = {field + "_agreement": sum(c["correct"][field] for c in cases) / n
               for field in ("topic", "intent", "severity", "needs_review")}
    metrics.update({
        "severity_mae": sum(severity_errors) / len(severity_errors) if severity_errors else None,
        "severity_mae_denominator": len(severity_errors),
        "sentiment_mae": sum(sentiment_errors) / len(sentiment_errors) if sentiment_errors else None,
        "sentiment_mae_denominator": len(sentiment_errors),
        "sentiment_within_tolerance": sum(c["correct"]["sentiment_within_tolerance"] for c in cases) / n,
        "sentiment_tolerance": sentiment_tolerance,
        "quote_exact_substring_rate": sum(c["quote_exact_substring"] for c in cases) / n,
        "unsupported_literal_entity_cases": sum(bool(c["entities_unsupported_literal"]) for c in cases),
        "entities_exact_agreement": sum(c["correct"]["entities_exact"] for c in cases) / n,
        "needs_review_precision": nr_tp / (nr_tp + nr_fp) if nr_tp + nr_fp else None,
        "needs_review_recall": nr_tp / (nr_tp + nr_fn) if nr_tp + nr_fn else None,
    })
    report = {
        "status": "evaluated", "human_ground_truth": True, "denominator": n,
        "source_identity_checked": source_checked,
        "missing_or_quarantined_predictions": sum(c["prediction_status"] != "completed" for c in cases),
        "ambiguous_count": sum(c["ambiguous"] for c in cases), "metrics": metrics,
        "per_topic_counts": dict(support),
        "limitations": ["Human-label provenance is attested by the caller or worksheet labeler fields.",
                        "Agreement includes missing/quarantined predictions as incorrect.",
                        "MAE uses available completed numeric predictions only; its denominator is explicit.",
                        "Accepted ambiguous labels score the nearest accepted severity.",
                        "Exact quote membership and literal entity checks do not establish semantic support.",
                        "A small human sample is diagnostic, not a precise population accuracy estimate."],
    }
    if not source_checked:
        report["limitations"].append("Source golden identity was not checked; supply golden_source_path for external evaluations.")
    write_json(output / "golden_report.json", report)
    write_json(output / "golden_cases.json", cases)
    write_json(output / "golden_disagreements.json", [c for c in cases if not all(c["correct"].values())])
    write_csv(output / "golden_confusion.csv",
              [{"field": field, "expected": pair[0], "predicted": pair[1], "count": count}
               for field, entries in confusion.items() for pair, count in sorted(entries.items())],
              ("field", "expected", "predicted", "count"))
    return report


def compare_verifier(records: Any, verifier_records: Any, output_dir: str | Path) -> dict:
    """Compare independent model answers. This is agreement, not label accuracy."""
    originals = {r["review_id"]: r for r in load_records(records)}
    verified = load_records(verifier_records)
    if len({r["review_id"] for r in verified}) != len(verified):
        raise ValueError("Verifier output contains duplicate IDs.")
    comparisons = []
    for entry in verified:
        rid = entry["review_id"]
        item = {**entry, **entry.get("prediction", {})}
        if rid not in originals:
            raise ValueError(f"Verifier returned an unknown ID: {rid}")
        original = originals[rid]
        comparable = original.get("status") == "completed" and item.get("status", "completed") == "completed"
        differing = [field for field in FIELDS if original.get(field) != item.get(field)] if comparable else list(FIELDS)
        comparisons.append({
            "review_id": rid, "comparable": comparable, "differing_fields": differing,
            "enrichment": {field: original.get(field) for field in FIELDS},
            "verification": {field: item.get(field) for field in FIELDS},
            "severity_absolute_difference": abs(original["severity"] - item["severity"]) if comparable else None,
            "sentiment_absolute_difference": abs(original["sentiment"] - item["sentiment"]) if comparable else None,
        })
    count = len(comparisons)
    report = {
        "status": "compared" if count else "no_verifier_predictions", "ground_truth": False,
        "verified_count": count, "disagreement_count": sum(bool(c["differing_fields"]) for c in comparisons),
        "comparable_count": sum(c["comparable"] for c in comparisons),
        "field_agreement": {field: sum(c["comparable"] and field not in c["differing_fields"] for c in comparisons) / count
                            if count else None for field in FIELDS},
        "limitations": ["Independent model agreement is not human accuracy.",
                        "Targeted difficult cases must be reported separately from the seeded random sample."],
    }
    output = Path(output_dir)
    write_json(output / "verifier_report.json", report)
    for name, items in (("verifier_comparisons.jsonl", comparisons),
                        ("disagreements.jsonl", [c for c in comparisons if c["differing_fields"]])):
        (output / name).write_text("".join(json.dumps(c, ensure_ascii=False, allow_nan=False) + "\n" for c in items), encoding="utf-8")
    return report


def learning_report(run_dir: str | Path, output_dir: str | Path | None = None,
                    cost_report: dict | None = None) -> dict:
    """Create an honest pilot decision record and a blank qualitative inspection sheet."""
    source = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else source / "evals"
    record_path = source / "records.jsonl"
    records = load_records(record_path) if record_path.exists() else []
    completed = [r for r in records if r.get("status") == "completed"]
    verifier_path = output / "verifier_report.json"
    verifier = json.loads(verifier_path.read_text(encoding="utf-8")) if verifier_path.exists() else {}
    summary_path = source / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    disagreement_path = output / "disagreements.jsonl"
    disagreements = load_records(disagreement_path) if disagreement_path.exists() else []
    random_cases = sorted(completed, key=lambda row: hashlib.sha256(
        ("pilot-inspection-v1:" + row["review_id"]).encode()).hexdigest())[:30]
    differing_ids = [row["review_id"] for row in disagreements][:30]
    indexed = {r["review_id"]: r for r in records}
    inspection_path = output / "development_inspection.csv"
    if not inspection_path.exists():
        cases = []
        for cohort, selected in (("seeded_random", random_cases),
                                 ("targeted_disagreement", [indexed[rid] for rid in differing_ids if rid in indexed])):
            for record in selected:
                checks = evidence_checks(record, record.get("review_text", ""))
                cases.append({
                    "cohort": cohort, "review_id": record["review_id"],
                    "review_text": record.get("review_text", ""),
                    **{field: record.get(field, "") for field in FIELDS},
                    "evidence_quote": record.get("evidence_quote", ""),
                    "entities": json.dumps(record.get("entities", []), ensure_ascii=False),
                    "quote_exact_substring": checks["quote_exact_substring"],
                    "topic_supported": "", "severity_supported": "", "quote_supports_label": "",
                    "entities_supported": "", "inspector": "", "inspection_notes": "",
                })
        write_csv(inspection_path, cases, ("cohort", "review_id", "review_text", *FIELDS,
                  "evidence_quote", "entities", "quote_exact_substring", "topic_supported",
                  "severity_supported", "quote_supports_label", "entities_supported",
                  "inspector", "inspection_notes"))
    with inspection_path.open(encoding="utf-8", newline="") as handle:
        inspections = list(csv.DictReader(handle))
    reviewed = sum(bool(row.get("inspector", "").strip()) and
                   all(row.get(field, "").strip() for field in (
                       "topic_supported", "severity_supported", "quote_supports_label", "entities_supported"))
                   for row in inspections)
    blockers = []
    if len(records) != 1000:
        blockers.append("The learning cohort has not accounted for exactly 1,000 original IDs.")
    if len(completed) != len(records):
        blockers.append("Some selected records have not completed classification; inspect their recorded handling.")
    if not records:
        blockers.append("No real model run has been recorded.")
    if verifier.get("verified_count", 0) < len(records) or not verifier:
        blockers.append("Independent comparator predictions do not yet cover the complete learning cohort.")
    if reviewed < len(inspections) or not inspections:
        blockers.append("Development evidence-support and disagreement inspection is unfinished.")
    if cost_report is None:
        blockers.append("A measured conservative cost/time projection has not been attached.")
    if not (source / "deployment_validation.json").exists():
        blockers.append("The deployed database/API reconciliation has not been recorded.")
    # Quality review and cost acceptance remain deliberate decisions, not a call-count heuristic.
    decision_path = output / "pilot_decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8")) if decision_path.exists() else None
    if decision is None:
        blockers.append("A reviewed configuration/routing decision has not been recorded.")
    report = {
        "status": "ready_for_review" if not blockers else "gated",
        "automatic_scaling": False, "input_count": len(records), "completed": len(completed),
        "quarantined": sum(r.get("status") == "quarantined" for r in records),
        "unique_texts": len({r.get("review_text") for r in records}),
        "needs_review": sum(r.get("needs_review") is True for r in completed),
        "inspection_rows": len(inspections), "inspected_rows": reviewed,
        "verifier": verifier, "measured_run": summary, "cost_projection": cost_report,
        "expansion_blockers": blockers,
        "questions_to_resolve": [
            "Which topic/severity boundaries produced concrete development errors?",
            "Which evidence quotes or entities failed semantic support inspection?",
            "Which uncertainty cases benefited from escalation, and within the fallback cap?",
            "What actual usage, retry behavior, latency and sustainable throughput were measured?",
            "Which concurrency levels were actually measured, and did failures increase?",
            "Does the deployed database/API reproduce every saved count, ranking and evidence reference?",
            "What supported prompt/routing changes require a new configuration and cold/warm measurement?",
        ],
    }
    write_json(output / "learning_report.json", report)
    body = ["# Learning checkpoint", "",
            f"State: **{report['status']}**. Automatic scaling is disabled.", "",
            f"Saved IDs: {len(records)}. Completed: {len(completed)}. "
            f"Inspected development rows: {reviewed}/{len(inspections)}.", "",
            "## Expansion conditions", ""]
    body.extend(f"- {blocker}" for blocker in blockers)
    body.extend(["", "## Questions requiring measured evidence", ""])
    body.extend(f"- {question}" for question in report["questions_to_resolve"])
    body.extend(["", "Model-to-model agreement is not human accuracy. "
                 "Development inspection is separate from the isolated human golden set.", ""])
    (output / "learning_report.md").write_text("\n".join(body), encoding="utf-8")
    return report
