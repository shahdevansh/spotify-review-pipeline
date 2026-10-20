"""Offline, source-bound comparison of frozen candidates; never imports providers.

Reference provenance is explicit. Missing predictions are outcomes, not filtered
successes. Exact-text cluster resampling preserves original-review multiplicity.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable, Mapping

from .data import row_sha
from .models import SOURCE_FIELDS, TOPICS, INTENTS, Classification, SourceReview

LABEL_FIELDS = ("topic", "intent", "severity", "sentiment", "needs_review")
CORE_FIELDS = ("topic", "intent", "severity")
MISSING = "__missing_or_invalid__"
VERSION = "offline-candidate-harness-v2"
MIN_BOOTSTRAP_REPETITIONS = 100


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(value: Any) -> list[dict]:
    if not isinstance(value, (str, Path)):
        return [dict(row) for row in value]
    path = Path(value)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        if path.suffix == ".csv":
            rows = list(csv.DictReader(handle))
            for row in rows:
                for key in ("needs_review", "raw_model_needs_review", "raw_needs_review", "ambiguous"):
                    if row.get(key, "").lower() in {"true", "false"}:
                        row[key] = row[key].lower() == "true"
                if row.get("severity", "").isdigit():
                    row["severity"] = int(row["severity"])
                if "sentiment" in row:
                    try:
                        row["sentiment"] = float(row["sentiment"])
                    except (TypeError, ValueError):
                        pass  # Invalid fields remain explicit validation failures.
                for key in ("entities", "alternative_topics", "alternative_intents", "alternative_severities",
                            "accepted_topic", "accepted_intent", "accepted_severity"):
                    if row.get(key, "").startswith("["):
                        try:
                            row[key] = json.loads(row[key])
                        except json.JSONDecodeError:
                            pass
            return rows
        if path.suffix == ".json":
            result = json.load(handle)
            if isinstance(result, dict):
                result = result.get("records", result.get("labels"))
            if not isinstance(result, list):
                raise ValueError("JSON input must contain a list, records list, or labels list.")
            return [dict(row) for row in result]
        return [json.loads(line) for line in handle if line.strip()]


def _reference_input(value: Any) -> tuple[list[dict], dict]:
    """Validate supplied worksheet provenance without searching for answer files."""
    wrapper = {}
    if isinstance(value, Mapping):
        wrapper = dict(value)
        records = wrapper.get("labels", wrapper.get("records"))
        if not isinstance(records, list):
            raise ValueError("Reference envelope requires a labels or records list.")
        rows = _load(records)
    elif isinstance(value, (str, Path)) and Path(value).suffix == ".json":
        document = json.loads(Path(value).read_text(encoding="utf-8-sig"))
        if isinstance(document, dict):
            wrapper = document
            records = wrapper.get("labels", wrapper.get("records"))
            if not isinstance(records, list):
                raise ValueError("Reference envelope requires a labels or records list.")
            rows = _load(records)
        else:
            rows = _load(value)
    else:
        rows = _load(value)
    fields = ("schema_version", "worksheet_version", "cohort_id", "rubric_version",
              "rubric_sha256", "source_digest", "seed")
    metadata = {}
    for key in fields:
        supplied = [row.get(key) for row in rows] if any(key in row for row in rows) else []
        if supplied and any(item != supplied[0] for item in supplied):
            raise ValueError(f"Reference rows mix {key} provenance.")
        if key in wrapper:
            if supplied and supplied[0] != wrapper[key]:
                raise ValueError(f"Reference wrapper conflicts with row {key}.")
            metadata[key] = wrapper[key]
        elif supplied:
            metadata[key] = supplied[0]
        if key in metadata and key != "seed" and (
            not isinstance(metadata[key], str) or not metadata[key].strip()
        ):
            raise ValueError(f"Reference {key} must be nonempty text when supplied.")
    for key in ("rubric_sha256", "source_digest"):
        if key in metadata and (len(metadata[key]) != 64 or any(c not in "0123456789abcdef" for c in metadata[key])):
            raise ValueError(f"Reference {key} must be a lowercase SHA-256 digest.")
    if "complete" in wrapper and wrapper["complete"] is not True:
        raise ValueError("Reference worksheet export is not marked complete.")
    if "validation_errors" in wrapper and wrapper["validation_errors"] != []:
        raise ValueError("Reference worksheet export contains validation errors.")
    if "annotator_id" in wrapper:
        annotator = wrapper["annotator_id"]
        if not isinstance(annotator, str) or not annotator.strip():
            raise ValueError("Reference annotator_id must be nonempty text.")
        if any(row.get("human_labeler") != annotator for row in rows):
            raise ValueError("Reference wrapper annotator_id differs from row human_labeler.")
        metadata["annotator_id"] = annotator
    for row in rows:
        if "human_labeler" in row and (
            not isinstance(row["human_labeler"], str) or not row["human_labeler"].strip()
        ):
            raise ValueError("Supplied human_labeler must be nonempty text.")
    if "source_digest" in metadata:
        source_rows = [{**{key: row.get(key) for key in ("review_id", "review_text")},
                        **({"row_sha": row["row_sha"]} if row.get("row_sha") not in (None, "") else {})}
                       for row in rows]
        if _digest(source_rows) != metadata["source_digest"]:
            raise ValueError("Reference worksheet source_digest differs from its ordered original rows.")
    return rows, {
        "metadata": metadata, "human_labeler_counts": dict(Counter(
            row.get("human_labeler", "not_supplied") for row in rows)),
        "source_digest_checked": "source_digest" in metadata,
        "source_digest_definition": "Ordered review_id/review_text/optional row_sha worksheet source rows.",
        "rubric_file_independently_verified": False,
        "rubric_digest_scope": "Retained and checked for consistent formatting/provenance; no corresponding rubric file is loaded implicitly.",
        "input_sha256": hashlib.sha256(Path(value).read_bytes()).hexdigest()
                        if isinstance(value, (str, Path)) else _digest(
                            value if isinstance(value, Mapping) else sorted(rows, key=lambda row: str(row.get("review_id", "")))),
    }


def _index(rows: Iterable[dict], role: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        rid = row.get("review_id")
        if not isinstance(rid, str) or not rid or rid in result:
            raise ValueError(f"{role}: missing or duplicate review_id {rid!r}")
        result[rid] = row
    return result


def _sources(rows: Any) -> dict[str, dict]:
    indexed = _index(_load(rows), "source")
    for rid, row in indexed.items():
        source = {key: row.get(key) for key in SOURCE_FIELDS}
        SourceReview.model_validate(source)
        if not row["review_text"].strip():
            raise ValueError(f"Evaluation cohort must contain nonempty source text: {rid}")
        if row.get("source_sha256") not in (None, row_sha(source)):
            raise ValueError(f"Source hash mismatch: {rid}")
        indexed[rid] = {**source, "source_sha256": row_sha(source),
                        "text_sha256": _text_hash(source["review_text"])}
    return indexed


def _bound_row(row: dict, source: dict, role: str) -> dict:
    """Require a source hash or original text; verify every supplied source field."""
    rid = source["review_id"]
    if "source_sha256" not in row and not row.get("row_sha") and "review_text" not in row:
        raise ValueError(f"{role} {rid}: require source_sha256 or exact review_text.")
    if "source_sha256" in row and row["source_sha256"] != source["source_sha256"]:
        raise ValueError(f"{role} {rid}: source hash mismatch.")
    if row.get("row_sha") not in (None, "", source["source_sha256"]):
        raise ValueError(f"{role} {rid}: worksheet row_sha source hash mismatch.")
    for key in SOURCE_FIELDS:
        if key in row and row[key] != source[key]:
            raise ValueError(f"{role} {rid}: changed original {key}.")
    prediction = row.get("prediction", row)
    if not isinstance(prediction, dict):
        # Keep provenance/status so malformed labels remain a coverage outcome
        # instead of accidentally becoming a missing-configuration error.
        return {**row, **{key: None for key in LABEL_FIELDS}}
    if prediction.get("review_id", rid) != rid:
        raise ValueError(f"{role} {rid}: nested prediction ID mismatch.")
    for key in (*SOURCE_FIELDS, "source_sha256"):
        if key in prediction and prediction[key] != source[key]:
            raise ValueError(f"{role} {rid}: nested prediction changes source {key}.")
    if prediction.get("row_sha") not in (None, "", source["source_sha256"]):
        raise ValueError(f"{role} {rid}: nested worksheet row_sha source hash mismatch.")
    for key in ("status", "label_config"):
        if key in row and key in prediction and row[key] != prediction[key]:
            raise ValueError(f"{role} {rid}: conflicting nested {key}.")
    return {**row, **prediction}


def _labels(row: dict, source: dict) -> dict:
    required = {key: row.get(key) for key in LABEL_FIELDS}
    # Full quotes/entities are optional evaluation fields, but validate them if
    # provided. This does not turn mechanically copied text into semantic proof.
    item = Classification.model_validate({
        **required, "evidence_quote": row.get("evidence_quote", source["review_text"]),
        "entities": row.get("entities", []),
    }).model_dump()
    if item["evidence_quote"] not in source["review_text"]:
        raise ValueError("Evidence quote is absent from original text.")
    if any(entity.casefold() not in source["review_text"].casefold() for entity in item["entities"]):
        raise ValueError("Entity is absent from original text.")
    for key in ("raw_model_needs_review", "raw_needs_review", "ambiguous"):
        if key in row and type(row[key]) is not bool:
            raise ValueError(f"{key} must be boolean when supplied.")
        if key in row:
            item[key] = row[key]
    if "raw_needs_review" in item:
        if "raw_model_needs_review" in item and item["raw_model_needs_review"] != item["raw_needs_review"]:
            raise ValueError("Conflicting raw_needs_review and raw_model_needs_review aliases.")
        item["raw_model_needs_review"] = item.pop("raw_needs_review")
    return item


def _reference_annotations(row: dict, labels: dict) -> dict:
    """Keep primary labels and accepted alternatives as separate scoring contracts."""
    accepted = {}
    for field, plural, allowed in (
        ("topic", "topics", TOPICS), ("intent", "intents", INTENTS),
        ("severity", "severities", (1, 2, 3, 4, 5)),
    ):
        provided = {}
        for key in (f"accepted_{field}", f"alternative_{plural}"):
            value = row.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{key} must be a JSON array.") from exc
            if not isinstance(value, list) or any(
                type(item) is not (int if field == "severity" else str) or item not in allowed for item in value
            ):
                raise ValueError(f"{key} must contain valid {field} labels.")
            if key.startswith("accepted_") and not value:
                raise ValueError(f"{key} must be nonempty when supplied.")
            if len(set(value)) != len(value):
                raise ValueError(f"{key} must not repeat labels.")
            provided[key] = set(value) if key.startswith("accepted_") else {labels[field], *value}
        if len(provided) == 2 and len({frozenset(values) for values in provided.values()}) != 1:
            raise ValueError(f"Conflicting accepted and alternative {field} sets.")
        values = next(iter(provided.values()), {labels[field]})
        if labels[field] not in values:
            raise ValueError(f"Accepted {field} set must include the primary label.")
        accepted[field] = sorted(values)
    support = row.get("evidence_support")
    if support not in (None, "", "supported", "partial", "unsupported", "unclear"):
        raise ValueError("evidence_support must be supported, partial, unsupported, or unclear.")
    return {**labels, "accepted_labels": accepted,
            "annotator_self_assessed_evidence_support": support or None}


def wilson_interval(successes: int, trials: int, confidence: float = .95) -> dict:
    if type(successes) is not int or type(trials) is not int or not 0 <= successes <= trials:
        raise ValueError("Wilson requires integers 0 <= successes <= trials.")
    if not 0 < confidence < 1:
        raise ValueError("Confidence must be between zero and one.")
    result = {"successes": successes, "trials": trials, "confidence": confidence,
              "method": "wilson_iid", "estimate": successes / trials if trials else None,
              "lower": None, "upper": None}
    if not trials:
        return result
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p, z2 = successes / trials, z * z
    center = (p + z2 / (2 * trials)) / (1 + z2 / trials)
    half = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials)) / (1 + z2 / trials)
    result.update(lower=max(0.0, center - half), upper=min(1.0, center + half))
    return result


def _ratio(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def _categorical(truth: list[str], predictions: list[str | None], labels: tuple,
                 term: str) -> dict:
    counts = Counter(zip(truth, [value if value is not None else MISSING for value in predictions]))
    classes = {}
    for label in labels:
        tp = counts[label, label]
        support = sum(n for (expected, _), n in counts.items() if expected == label)
        predicted = sum(n for (_, observed), n in counts.items() if observed == label)
        classes[label] = {
            "reference_support": support, "predicted_support": predicted, "true_positive": tp,
            "precision": tp / predicted if predicted else None,
            "recall": tp / support if support else None,
            "f1": 2 * tp / (support + predicted) if support + predicted else None,
        }
    present = [row["f1"] for row in classes.values() if row["f1"] is not None]
    correct = sum(a == b for a, b in zip(truth, predictions))
    return {
        term: wilson_interval(correct, len(truth)),
        "macro_f1_present_labels": sum(present) / len(present) if present else None,
        "macro_f1_all_taxonomy_labels": sum(row["f1"] or 0 for row in classes.values()) / len(labels) if truth else None,
        "macro_f1_definition": "Unweighted class F1; present means reference_support + predicted_support > 0.",
        "per_class": classes,
        "confusion": [{"reference": a, "prediction": b, "count": n} for (a, b), n in sorted(counts.items())],
        "missing_prediction_label": MISSING,
    }


def _error(prediction: dict | None, reference: dict, *, acceptable_sets: bool = False) -> bool:
    if prediction is None:
        return True
    return any(prediction[field] not in reference.get("accepted_labels", {}).get(field, [reference[field]])
               if acceptable_sets else prediction[field] != reference[field] for field in CORE_FIELDS)


def _statistics(ids: list[str], predictions: dict, reference: dict, term: str) -> dict:
    valid = [rid for rid in ids if rid in predictions]
    severity = [abs(predictions[rid]["severity"] - reference[rid]["severity"]) for rid in valid]
    sentiment = [abs(predictions[rid]["sentiment"] - reference[rid]["sentiment"]) for rid in valid]
    return {
        "reference_ids": len(ids), "valid_prediction_ids": len(valid),
        "missing_or_invalid_prediction_ids": len(ids) - len(valid),
        "topic": _categorical([reference[r]["topic"] for r in ids],
                              [predictions.get(r, {}).get("topic") for r in ids], TOPICS, term),
        "intent": _categorical([reference[r]["intent"] for r in ids],
                               [predictions.get(r, {}).get("intent") for r in ids], INTENTS, term),
        "severity": {
            "exact": wilson_interval(sum(predictions.get(r, {}).get("severity") == reference[r]["severity"] for r in ids), len(ids)),
            "within_one": wilson_interval(sum(abs(predictions[r]["severity"] - reference[r]["severity"]) <= 1 for r in valid), len(ids)),
            "mean_absolute_difference": sum(severity) / len(severity) if severity else None,
            "numeric_denominator": len(severity),
        },
        "sentiment": {"mean_absolute_difference": sum(sentiment) / len(sentiment) if sentiment else None,
                      "numeric_denominator": len(sentiment)},
        "needs_review": {"agreement": wilson_interval(
            sum(predictions.get(r, {}).get("needs_review") == reference[r]["needs_review"] for r in ids), len(ids))},
        "joint_topic_intent_severity": wilson_interval(
            sum(not _error(predictions.get(r), reference[r]) for r in ids), len(ids)),
        "numeric_failure_policy": "MAE uses valid numeric predictions only; missing/invalid count remains explicit. Binary metrics count failures as incorrect.",
    }


def routing_metrics(ids: list[str], predictions: dict, human_reference: dict, *,
                    flag_field: str = "needs_review", acceptable_sets: bool = False) -> dict:
    """Flag performance against core label errors; never against the flag itself."""
    valid = [rid for rid in ids if rid in predictions]
    flagged = [rid for rid in valid if predictions[rid][flag_field]]
    unflagged = [rid for rid in valid if not predictions[rid][flag_field]]
    errors = {rid for rid in ids if _error(predictions.get(rid), human_reference[rid], acceptable_sets=acceptable_sets)}
    valid_errors = errors & set(valid)
    flagged_errors = errors & set(flagged)
    forced = set(ids) - set(valid)
    points = []
    for policy, accepted in (("accept_none", []), ("accept_unflagged", unflagged), ("accept_all_valid", valid)):
        points.append({"policy": policy, "coverage": _ratio(len(accepted), len(ids)),
                       "selective_risk": wilson_interval(len(errors & set(accepted)), len(accepted))})
    return {
        "error_definition": ("Any topic, intent, or severity outside its accepted set." if acceptable_sets else
                             "Any primary topic, intent, or severity mismatch.") +
                            " needs_review is excluded; sentiment is reported separately.",
        "flag_field": flag_field,
        "reference_kind": "human", "reference_ids": len(ids), "valid_prediction_ids": len(valid),
        "forced_review_failures": len(forced), "raw_model_flag_available": sum("raw_model_needs_review" in predictions[r] for r in valid),
        "review_flag_rate": _ratio(len(flagged), len(valid)),
        "flag_precision_for_core_error": _ratio(len(flagged_errors), len(flagged)),
        "error_capture_by_review_flag": _ratio(len(flagged_errors), len(valid_errors)),
        "error_capture_by_flag_or_forced_review": _ratio(len(flagged_errors | forced), len(errors)),
        "risk_coverage": points,
        "limitations": "Boolean flags give discrete operating points, not a calibrated score, continuous risk curve, or AUROC.",
    }


def _accepted_statistics(ids: list[str], predictions: dict, reference: dict) -> dict:
    valid = [rid for rid in ids if rid in predictions]
    errors = [min(abs(predictions[r]["severity"] - value) for value in reference[r]["accepted_labels"]["severity"])
              for r in valid]
    return {
        "definition": "A prediction matches any explicitly accepted label; single-class confusion and primary-label metrics remain separate.",
        "reference_ids": len(ids), "valid_prediction_ids": len(valid),
        "field_matches": {field: wilson_interval(
            sum(predictions.get(r, {}).get(field) in reference[r]["accepted_labels"][field] for r in ids), len(ids))
            for field in CORE_FIELDS},
        "joint_core_match": wilson_interval(sum(not _error(predictions.get(r), reference[r], acceptable_sets=True)
                                                for r in ids), len(ids)),
        "nearest_accepted_severity_mae": sum(errors) / len(errors) if errors else None,
        "numeric_denominator": len(errors),
        "within_one_accepted_severity": wilson_interval(sum(value <= 1 for value in errors), len(ids)),
    }


def _percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    offset = (len(values) - 1) * q
    lower = math.floor(offset)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (offset - lower)


def _bootstrap_scalar(ids: list[str], predictions: dict, reference: dict) -> dict:
    valid = [r for r in ids if r in predictions]
    return {
        "topic_match": sum(predictions.get(r, {}).get("topic") == reference[r]["topic"] for r in ids) / len(ids) if ids else None,
        "intent_match": sum(predictions.get(r, {}).get("intent") == reference[r]["intent"] for r in ids) / len(ids) if ids else None,
        "severity_exact": sum(predictions.get(r, {}).get("severity") == reference[r]["severity"] for r in ids) / len(ids) if ids else None,
        "severity_mae": sum(abs(predictions[r]["severity"] - reference[r]["severity"]) for r in valid) / len(valid) if valid else None,
        "sentiment_mae": sum(abs(predictions[r]["sentiment"] - reference[r]["sentiment"]) for r in valid) / len(valid) if valid else None,
    }


def _numeric_contributors(ids: list[str], predictions: dict) -> dict[str, list[str]]:
    """Numeric means exclude invalid predictions; binary metrics include them."""
    valid = sorted(set(ids) & set(predictions))
    return {key: valid for key in ("severity_mae", "sentiment_mae")}


def cluster_bootstrap(ids: list[str], sources: dict, statistic, *, repetitions: int,
                      seed: int, confidence: float = .95,
                      contributing_ids: Mapping[str, Iterable[str]] | None = None) -> dict:
    """Sample whole text clusters, with per-statistic interval safeguards.

    A statistic with a restricted denominator must declare its contributing IDs.
    Otherwise every input ID is assumed eligible. Low-repetition and degenerate
    resampling ranges remain diagnostic; they are not reported as confidence
    bounds. This cannot establish reference correctness or population accuracy.
    """
    if type(repetitions) is not int or repetitions < 0 or type(seed) is not int:
        raise ValueError("Bootstrap repetitions must be nonnegative integer; seed must be integer.")
    if not 0 < confidence < 1:
        raise ValueError("Confidence must be between zero and one.")
    groups = defaultdict(list)
    for rid in sorted(ids):
        groups[sources[rid]["text_sha256"]].append(rid)
    clusters = [groups[key] for key in sorted(groups)]
    point = statistic(sorted(ids))
    contributors = {}
    for key, members in (contributing_ids or {}).items():
        if key not in point or isinstance(members, (str, bytes)):
            raise ValueError("Contributing IDs require a known statistic and an iterable of IDs.")
        members = set(members)
        if members - set(ids):
            raise ValueError("Contributing IDs must belong to the bootstrap input.")
        contributors[key] = members
    contributing_counts = {}
    for key in point:
        members = contributors.get(key, set(ids))
        contributing_counts[key] = {
            "contributing_records": len(members),
            "contributing_clusters": len({sources[rid]["text_sha256"] for rid in members}),
            "contribution_basis": "explicit_eligible_ids" if key in contributors else "all_input_ids",
        }
    result = {"method": "exact_text_cluster_percentile", "confidence": confidence, "seed": seed,
              "requested_repetitions": repetitions, "clusters": len(clusters), "records": len(ids),
              "point_estimate_weighting": "original review IDs, not equally weighted unique texts",
              "quantile_method": "linear interpolation at (B - 1) * quantile",
              "minimum_reportable_repetitions": MIN_BOOTSTRAP_REPETITIONS,
              "intervals": {}}
    rng = random.Random(seed)
    samples = {key: [] for key in point}
    executed = repetitions if len(clusters) >= 2 else 0
    for _ in range(executed):
        sampled = [rid for _ in clusters for rid in clusters[rng.randrange(len(clusters))]]
        for key, value in statistic(sampled).items():
            if value is not None and math.isfinite(value):
                samples[key].append(value)
    alpha = (1 - confidence) / 2
    result["status"] = ("insufficient_clusters" if len(clusters) < 2 else
                        "disabled" if repetitions == 0 else
                        "insufficient_repetitions" if repetitions < MIN_BOOTSTRAP_REPETITIONS else "computed")
    for key, values in samples.items():
        support = contributing_counts[key]
        low = _percentile(values, alpha) if values else None
        high = _percentile(values, 1 - alpha) if values else None
        degenerate = bool(values) and min(values) == max(values)
        warnings = []
        if support["contributing_clusters"] < 2:
            status = "insufficient_contributing_clusters"
        elif repetitions == 0:
            status = "disabled"
        elif point[key] is None or not values:
            status = "undefined_statistic"
        elif repetitions < MIN_BOOTSTRAP_REPETITIONS:
            status = "insufficient_repetitions"
        elif len(values) < MIN_BOOTSTRAP_REPETITIONS:
            status = "insufficient_valid_repetitions"
        elif degenerate:
            status = "degenerate_resamples"
        else:
            status = "reportable"
        if support["contributing_clusters"] < 2:
            warnings.append("Fewer than two eligible exact-text clusters; numeric support cannot be borrowed from other reference IDs.")
        if repetitions < MIN_BOOTSTRAP_REPETITIONS or len(values) < MIN_BOOTSTRAP_REPETITIONS:
            warnings.append("Fewer than 100 requested or defined resamples; bounds are diagnostic only.")
        if degenerate:
            warnings.append("All defined resamples have the same value. Resampling cannot reveal unobserved errors; this is not proof of perfect accuracy, zero error, or population equivalence.")
        reportable = status == "reportable"
        result["intervals"][key] = {
            "estimate": point[key], "lower": low if reportable else None,
            "upper": high if reportable else None, "reportable": reportable, "interval_status": status,
            **support, "bootstrap_mean": sum(values) / len(values) if values else None,
            "valid_repetitions": len(values), "undefined_repetitions": executed - len(values),
            "skipped_repetitions": repetitions - executed,
            "empirical_percentile_range": {"lower": low, "upper": high, "inferential": False},
            "degenerate_resamples": degenerate, "warnings": warnings,
        }
    return result


def _ranking(ids: list[str], predictions: dict) -> dict:
    totals, counts = Counter(), Counter()
    for rid in ids:
        row = predictions[rid]
        if row["intent"] in {"complaint", "cancellation"}:
            iid = f"issue-{row['topic']}"
            totals[iid] += row["severity"]
            counts[iid] += 1
    order = sorted(totals, key=lambda iid: (-totals[iid], iid))
    return {"records": len(ids), "complaint_or_cancellation_records": sum(counts.values()),
            "zero_score_issue_policy": "Display only topics with complaint/cancellation membership; rank correlation still includes all eight topics with zeros.",
            "top_issue": order[0] if order else None,
            "ranking": [{"rank": i + 1, "issue_id": iid, "severity_sum": totals[iid],
                         "complaint_count": counts[iid]} for i, iid in enumerate(order)]}


def _rank_compare(first: dict, second: dict) -> dict:
    a, b = {r["issue_id"]: r["severity_sum"] for r in first["ranking"]}, {r["issue_id"]: r["severity_sum"] for r in second["ranking"]}
    all_issues = [f"issue-{topic}" for topic in TOPICS]
    # Midranks preserve score ties instead of crediting alphabetical zero-score ties.
    def ranks(values):
        return [1 + sum(v > x for v in values) + (sum(v == x for v in values) - 1) / 2 for x in values]
    ar, br = ranks([a.get(i, 0) for i in all_issues]), ranks([b.get(i, 0) for i in all_issues])
    av, bv = sum(ar) / len(ar), sum(br) / len(br)
    denom = math.sqrt(sum((r - av) ** 2 for r in ar) * sum((r - bv) ** 2 for r in br))
    correlation = sum((x - av) * (y - bv) for x, y in zip(ar, br)) / denom if denom else None
    atop = {r["issue_id"] for r in first["ranking"][:3]}
    btop = {r["issue_id"] for r in second["ranking"][:3]}
    return {
        "top_issue_same": first["top_issue"] == second["top_issue"] if first["top_issue"] or second["top_issue"] else None,
        "top_three_jaccard": len(atop & btop) / len(atop | btop) if atop | btop else None,
        "spearman_all_eight_topics_with_midranks": correlation,
        "score_differences_second_minus_first": {iid: b.get(iid, 0) - a.get(iid, 0) for iid in sorted(all_issues)},
        "interpretation": "Matched-cohort ranking sensitivity, not correctness or causal product impact.",
    }


def audit_split_leakage(sources: dict, split_rows: Any = None, *, evaluation_split: str = "evaluation") -> dict:
    if not isinstance(evaluation_split, str) or not evaluation_split.strip():
        raise ValueError("evaluation_split must be a nonempty string.")
    if split_rows is None:
        return {"status": "not_checked", "reason": "No development/holdout split manifest supplied."}
    memberships, texts = defaultdict(set), defaultdict(set)
    identities = {}
    for row in [{**row, "split": evaluation_split} for row in sources.values()] + _load(split_rows):
        split = row.get("split")
        if not isinstance(split, str) or not split.strip():
            raise ValueError("External split rows require an explicit nonempty split name.")
        source = _sources([row])[row["review_id"]]
        rid = source["review_id"]
        if rid in identities and identities[rid] != source["source_sha256"]:
            raise ValueError(f"Split manifest changes source identity: {rid}")
        identities[rid] = source["source_sha256"]
        memberships[rid].add(split)
        texts[source["text_sha256"]].add(split)
    id_overlap = {rid: sorted(names) for rid, names in memberships.items() if len(names) > 1}
    text_overlap = {digest: sorted(names) for digest, names in texts.items() if len(names) > 1}
    exposed = sorted(rid for rid in sources if sources[rid]["text_sha256"] in text_overlap)
    return {"status": "overlap_detected" if id_overlap or text_overlap else "passed",
            "evaluation_split": evaluation_split, "cross_split_ids": id_overlap,
            "cross_split_exact_text_hashes": text_overlap,
            "evaluation_text_exposed_ids": exposed,
            "evaluation_unseen_text_ids": sorted(set(sources) - set(exposed)),
            "label_leakage": "not_assessed",
            "interpretation": "Exact text overlap establishes source exposure, not that human reference answers were read.",
            "scope": "Exact IDs/source identity and unnormalized exact texts only; near-duplicate semantic leakage is not tested."}


def evaluate_candidates(sources: Any, candidates: Mapping[str, Any], *, references: Any = None,
                        reference_kind: str = "none", human_labels_confirmed: bool = False,
                        candidate_metadata: Mapping[str, dict] | None = None, split_rows: Any = None,
                        evaluation_split: str = "evaluation", leakage_policy: str = "error",
                        evaluation_groups: Mapping[str, Iterable[str]] | None = None,
                        baseline_candidate: str | None = None, bootstrap_repetitions: int = 1000,
                        seed: int = 1729) -> dict:
    """Return a JSON-serializable report without reading any implicit label files."""
    if reference_kind not in {"none", "human", "ai"} or (references is None) != (reference_kind == "none"):
        raise ValueError("Supply explicit reference_kind human/ai with references, or none without references.")
    if type(human_labels_confirmed) is not bool:
        raise ValueError("human_labels_confirmed must be a boolean.")
    if reference_kind == "human" and not human_labels_confirmed:
        raise ValueError("Human reference requires explicit human_labels_confirmed=True.")
    if leakage_policy not in {"error", "report"}:
        raise ValueError("leakage_policy must be error or report.")
    if type(bootstrap_repetitions) is not int or bootstrap_repetitions < 0 or type(seed) is not int:
        raise ValueError("Bootstrap repetitions must be nonnegative integer; seed must be integer.")
    source = _sources(sources)
    if not source or not candidates or any(not isinstance(name, str) or not name for name in candidates):
        raise ValueError("Nonempty source cohort and named candidates are required.")
    ids, names = sorted(source), sorted(candidates)
    groups, grouped = {}, set()
    for group, members in (evaluation_groups or {}).items():
        if not isinstance(group, str) or not group.strip() or isinstance(members, (str, bytes)):
            raise ValueError("Evaluation groups require nonempty names and lists of IDs.")
        members = list(members)
        if not members or any(not isinstance(rid, str) for rid in members) or len(set(members)) != len(members):
            raise ValueError(f"Evaluation group {group}: require nonempty distinct string IDs.")
        if set(members) - set(source) or set(members) & grouped:
            raise ValueError(f"Evaluation group {group}: foreign or overlapping group IDs.")
        groups[group] = sorted(members)
        grouped.update(members)
    if baseline_candidate is None:
        baseline_candidate = names[0]
    if baseline_candidate not in candidates:
        raise ValueError("Baseline must name a supplied candidate.")
    split_audit = audit_split_leakage(source, split_rows, evaluation_split=evaluation_split)
    if split_audit["status"] == "overlap_detected" and leakage_policy == "error":
        raise ValueError("Cross-split review ID or exact-text leakage detected.")
    valid, candidate_reports = {}, {}
    for name in names:
        rows = _index(_load(candidates[name]), f"candidate {name}")
        foreign = sorted(set(rows) - set(source))
        if foreign:
            raise ValueError(f"candidate {name}: foreign IDs: {foreign}")
        bound_rows = {rid: _bound_row(row, source[rid], f"candidate {name}") for rid, row in rows.items()}
        declared = (candidate_metadata or {}).get(name, {}).get("config_id")
        supplied_ids = [row.get("label_config") for row in bound_rows.values()]
        if (declared is not None and (not isinstance(declared, str) or not declared)) or any(
            value is not None and (not isinstance(value, str) or not value) for value in supplied_ids
        ):
            raise ValueError(f"candidate {name}: configuration identity must be a nonempty string.")
        if not declared and any(value is None for value in supplied_ids):
            raise ValueError(f"candidate {name}: each row needs label_config unless metadata declares config_id.")
        config_ids = {value for value in supplied_ids if value}
        if declared:
            config_ids.add(declared)
        if len(config_ids) != 1 or any(not isinstance(value, str) for value in config_ids):
            raise ValueError(f"candidate {name}: require one frozen label_config or metadata config_id.")
        valid[name], failures = {}, {}
        raw_flags = Counter()
        for rid, row in rows.items():
            bound = bound_rows[rid]
            if bound.get("status", "completed") != "completed":
                failures[rid] = {"kind": "noncompleted", "status": bound["status"], "reason": bound.get("reason")}
                continue
            try:
                valid[name][rid] = _labels(bound, source[rid])
                if "raw_model_needs_review" in valid[name][rid]:
                    raw_flags[str(valid[name][rid]["raw_model_needs_review"]).lower()] += 1
            except ValueError as exc:
                failures[rid] = {"kind": "invalid_labels", "reason": str(exc)}
        missing = sorted(set(source) - set(rows))
        candidate_reports[name] = {
            "config_id": next(iter(config_ids)), "input_sha256": _digest([rows[rid] for rid in sorted(rows)]),
            "coverage": {"expected": len(ids), "received": len(rows), "valid": len(valid[name]),
                         "missing_ids": missing, "invalid_or_noncompleted": failures,
                         "complete": not missing and not failures},
            "needs_review": {"audited_true": sum(r["needs_review"] for r in valid[name].values()),
                             "valid_denominator": len(valid[name]), "raw_model_flag_counts": dict(raw_flags),
                             "raw_model_flag_missing": len(valid[name]) - sum(raw_flags.values()),
                             "calibrated": False},
        }
    common = sorted(set(ids).intersection(*(set(valid[name]) for name in names)))
    reference, reference_provenance = {}, None
    if references is not None:
        reference_rows, reference_provenance = _reference_input(references)
        rows = _index(reference_rows, "reference")
        if set(rows) - set(source):
            raise ValueError("Reference contains foreign IDs.")
        for rid, row in rows.items():
            bound = _bound_row(row, source[rid], "reference")
            if bound.get("status", "completed") != "completed":
                raise ValueError(f"Reference is not a completed label: {rid}")
            reference[rid] = _reference_annotations(bound, _labels(bound, source[rid]))
    reference_ids, common_reference = sorted(reference), sorted(set(reference) & set(common))
    unseen_reference = sorted(set(reference) & set(split_audit.get("evaluation_unseen_text_ids", [])))
    exposed_reference = sorted(set(reference) & set(split_audit.get("evaluation_text_exposed_ids", [])))
    term = "accuracy" if reference_kind == "human" else "agreement"
    for name in names:
        if reference:
            candidate_reports[name]["reference_metrics"] = _statistics(reference_ids, valid[name], reference, term)
            candidate_reports[name]["matched_reference_metrics"] = _statistics(common_reference, valid[name], reference, term)
            candidate_reports[name]["acceptable_set_reference_metrics"] = _accepted_statistics(reference_ids, valid[name], reference)
            if split_rows is not None:
                candidate_reports[name]["unseen_text_reference_metrics"] = _statistics(unseen_reference, valid[name], reference, term)
                candidate_reports[name]["exposed_text_reference_metrics"] = _statistics(exposed_reference, valid[name], reference, term)
            candidate_reports[name]["cluster_uncertainty"] = cluster_bootstrap(
                reference_ids, source, lambda sample, name=name: _bootstrap_scalar(sample, valid[name], reference),
                repetitions=bootstrap_repetitions, seed=seed,
                contributing_ids=_numeric_contributors(reference_ids, valid[name]))
            if reference_kind == "human":
                candidate_reports[name]["routing"] = routing_metrics(reference_ids, valid[name], reference)
                candidate_reports[name]["acceptable_set_routing"] = routing_metrics(
                    reference_ids, valid[name], reference, acceptable_sets=True)
                raw_ids = [rid for rid in reference_ids if rid in valid[name] and
                           "raw_model_needs_review" in valid[name][rid]]
                candidate_reports[name]["raw_model_routing"] = {
                    **routing_metrics(raw_ids, valid[name], reference, flag_field="raw_model_needs_review"),
                    "excluded_missing_prediction_or_raw_flag_ids": sorted(set(reference_ids) - set(raw_ids)),
                    "scope": "Only valid human-referenced predictions with an observed raw model flag.",
                }
    pairs = []
    for first, second in itertools.combinations(names, 2):
        pair_ids = sorted(set(valid[first]) & set(valid[second]))
        comparison = {
            "first": first, "second": second, "reference_role": "first_candidate_comparator_not_ground_truth",
            "cohort_size": len(ids), "matched_valid_count": len(pair_ids),
            "excluded_ids": sorted(set(ids) - set(pair_ids)), "matched_ids_sha256": _digest(pair_ids),
            "metrics": _statistics(pair_ids, valid[second], valid[first], "agreement"),
            "cluster_uncertainty": cluster_bootstrap(
                pair_ids, source, lambda sample, a=first, b=second: _bootstrap_scalar(sample, valid[b], valid[a]),
                repetitions=bootstrap_repetitions, seed=seed),
        }
        pairs.append(comparison)
    rankings = {name: _ranking(common, valid[name]) for name in names}
    rank_comparisons = []
    for first, second in itertools.combinations(names, 2):
        rank_comparisons.append({"first": first, "second": second,
                                **_rank_compare(rankings[first], rankings[second])})
    def rank_stability(sample):
        sampled_rankings = {name: _ranking(sample, valid[name]) for name in names}
        values = {
            f"{name}:top_matches_original": (
                float(sampled_rankings[name]["top_issue"] == rankings[name]["top_issue"])
                if sampled_rankings[name]["top_issue"] is not None and rankings[name]["top_issue"] is not None else None)
            for name in names
        }
        for first, second in itertools.combinations(names, 2):
            match = _rank_compare(sampled_rankings[first], sampled_rankings[second])["top_issue_same"]
            values[f"{first}|{second}:top_issue_same"] = float(match) if match is not None else None
        return values
    ranking_bootstrap = cluster_bootstrap(common, source, rank_stability,
                                         repetitions=bootstrap_repetitions, seed=seed)
    ranking_bootstrap["empirical_top_stability"] = {
        key: {"bootstrap_fraction": value.get("bootstrap_mean"),
              "valid_repetitions": value["valid_repetitions"],
              "undefined_repetitions": value.get("undefined_repetitions", bootstrap_repetitions),
              "contributing_clusters": value["contributing_clusters"],
              "resampling_status": value["interval_status"],
              "warnings": value["warnings"]}
        for key, value in ranking_bootstrap.pop("intervals").items()
    }
    ranking_bootstrap["interpretation"] = (
        "Fractions of cluster resamples retaining an original top issue or matching a comparator; "
        "sampling sensitivity, not a confidence interval on ranking correctness.")
    deltas = {}
    if reference:
        for name in names:
            if name == baseline_candidate:
                continue
            numeric_ids = set(reference_ids) & set(valid[name]) & set(valid[baseline_candidate])
            def delta(sample, name=name):
                baseline = _bootstrap_scalar(sample, valid[baseline_candidate], reference)
                candidate = _bootstrap_scalar(sample, valid[name], reference)
                # Numeric averages must use the same IDs on both sides, including
                # each resampled copy of an original review.
                paired = [rid for rid in sample if rid in numeric_ids]
                b_numeric = _bootstrap_scalar(paired, valid[baseline_candidate], reference)
                c_numeric = _bootstrap_scalar(paired, valid[name], reference)
                for key in ("severity_mae", "sentiment_mae"):
                    baseline[key], candidate[key] = b_numeric[key], c_numeric[key]
                return {key: candidate[key] - baseline[key] if candidate[key] is not None and baseline[key] is not None else None
                        for key in baseline}
            deltas[name] = cluster_bootstrap(
                reference_ids, source, delta, repetitions=bootstrap_repetitions, seed=seed,
                contributing_ids={key: sorted(numeric_ids) for key in ("severity_mae", "sentiment_mae")})
            deltas[name]["denominators"] = {
                "binary_reference_count": len(reference_ids), "numeric_matched_count": len(numeric_ids),
                "numeric_matched_ids": sorted(numeric_ids), "numeric_matched_ids_sha256": _digest(sorted(numeric_ids)),
                "numeric_excluded_reference_ids": sorted(set(reference_ids) - numeric_ids),
            }
    group_reports = {}
    for group, members in sorted(groups.items()):
        labeled = sorted(set(members) & set(reference))
        unseen = sorted(set(labeled) & set(unseen_reference))
        exposed = sorted(set(labeled) & set(exposed_reference))
        group_reports[group] = {
            "review_ids": members, "ids_sha256": _digest(members), "expected_count": len(members),
            "labeled_count": len(labeled), "unlabeled_ids": sorted(set(members) - set(labeled)),
            "unseen_text_labeled_count": len(unseen) if split_rows is not None else None,
            "exposed_text_labeled_count": len(exposed) if split_rows is not None else None,
            "candidates": {},
        }
        for name in names:
            item = {"valid_prediction_count": len(set(members) & set(valid[name]))}
            if labeled:
                item.update(
                    reference_metrics=_statistics(labeled, valid[name], reference, term),
                    acceptable_set_reference_metrics=_accepted_statistics(labeled, valid[name], reference),
                    cluster_uncertainty=cluster_bootstrap(
                        labeled, source, lambda sample, name=name: _bootstrap_scalar(sample, valid[name], reference),
                        repetitions=bootstrap_repetitions, seed=seed,
                        contributing_ids=_numeric_contributors(labeled, valid[name])),
                )
                if split_rows is not None:
                    item["unseen_text_reference_metrics"] = _statistics(unseen, valid[name], reference, term)
                    item["exposed_text_reference_metrics"] = _statistics(exposed, valid[name], reference, term)
                if reference_kind == "human":
                    item["routing"] = routing_metrics(labeled, valid[name], reference)
            group_reports[group]["candidates"][name] = item
    complete = all(row["coverage"]["complete"] for row in candidate_reports.values())
    return {
        "harness_version": VERSION, "offline": True,
        "status": "incomplete" if not complete else (
            "complete_with_split_overlap" if split_audit["status"] == "overlap_detected" else "complete"),
        "cohort": {"expected_ids": len(ids), "distinct_exact_texts": len({source[r]["text_sha256"] for r in ids}),
                   "review_ids": ids, "ids_sha256": _digest(ids),
                   "source_rows_sha256": _digest([(rid, source[rid]["source_sha256"]) for rid in ids])},
        "reference": {"kind": reference_kind, "human_confirmed": reference_kind == "human" and human_labels_confirmed,
                      "provenance": reference_provenance,
                      "human_accuracy_available": reference_kind == "human" and bool(reference),
                      "labeled_count": len(reference), "unlabeled_ids": sorted(set(ids) - set(reference)),
                      "ambiguous_count": sum(row.get("ambiguous", False) for row in reference.values()),
                      "accepted_alternatives_count": sum(any(len(values) > 1 for values in row["accepted_labels"].values())
                                                         for row in reference.values()),
                      "annotator_evidence_support_counts": dict(Counter(
                          row["annotator_self_assessed_evidence_support"] or "not_supplied" for row in reference.values())),
                      "evidence_support_interpretation": "Annotator assessment of their own quote and labels; not a model-evidence correctness audit.",
                      "unseen_text_labeled_count": len(unseen_reference) if split_rows is not None else None,
                      "exposed_text_labeled_count": len(exposed_reference) if split_rows is not None else None,
                      "all_supplied_reference_ids_retained": True,
                      "source_bound_labels_sha256": _digest(reference) if reference else None},
        "split_audit": split_audit, "candidates": candidate_reports, "pairwise_agreement": pairs,
        "evaluation_groups": group_reports,
        "group_accounting": {
            "grouped_ids": len(grouped), "unassigned_ids": sorted(set(ids) - grouped) if groups else [],
            "interpretation": "Named groups are reported separately. Pooled metrics are descriptive of supplied records, not a population estimate; no design weights are assumed.",
        },
        "matched_comparison": {"all_candidate_valid_ids": common, "all_candidate_valid_count": len(common),
                               "matched_reference_ids": common_reference},
        "ranking_sensitivity": {"matched_ids_sha256": _digest(common), "matched_count": len(common),
                               "excluded_ids": sorted(set(ids) - set(common)), "rankings": rankings,
                               "pairwise": rank_comparisons, "cluster_bootstrap_top_stability": ranking_bootstrap,
                               "not_accuracy": True},
        "paired_reference_differences": {"baseline": baseline_candidate, "candidate_minus_baseline": deltas,
                                        "sampling": "Same exact-text cluster draws for each side of every difference."},
        "uncertainty": {"confidence": .95, "bootstrap_repetitions": bootstrap_repetitions, "seed": seed,
                        "wilson_scope": "IID diagnostic; repeated texts require dependence-aware interpretation. Use cluster bounds only when their per-metric reportable flag is true.",
                        "bootstrap_interval_policy": "Bounds require at least two contributing exact-text clusters, 100 requested and defined resamples, and nondegenerate resamples. Empirical ranges remain diagnostic only.",
                        "limits": "Intervals describe sampling uncertainty under exchangeable text clusters, not reference correctness or population representativeness."},
        "limitations": ["No implicit golden-label file is read; provenance is an explicit caller attestation.",
                        "AI-reference and candidate agreement are not human accuracy.",
                        "Structural quote/entity checks do not establish semantic label correctness.",
                        "No candidate selection or automatic expansion is performed."],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--candidate", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--candidate-metadata", help="JSON mapping of candidate names to config_id.")
    parser.add_argument("--reference")
    parser.add_argument("--reference-kind", choices=("none", "human", "ai"), default="none")
    parser.add_argument("--human-labels-confirmed", action="store_true")
    parser.add_argument("--split-rows")
    parser.add_argument("--evaluation-split", default="evaluation")
    parser.add_argument("--evaluation-groups", help="JSON object mapping disjoint cohort names to review ID lists.")
    parser.add_argument("--leakage-policy", choices=("error", "report"), default="error")
    parser.add_argument("--baseline-candidate")
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    candidates = {}
    for item in args.candidate:
        if "=" not in item:
            parser.error("--candidate must be NAME=PATH")
        name, path = item.split("=", 1)
        if not name or name in candidates:
            parser.error("Candidate names must be nonempty and unique.")
        candidates[name] = path
    output = Path(args.out)
    if output.exists():
        raise ValueError("Output exists; choose a new report path to preserve evidence.")
    report = evaluate_candidates(
        args.sources, candidates, references=args.reference, reference_kind=args.reference_kind,
        human_labels_confirmed=args.human_labels_confirmed,
        candidate_metadata=json.loads(Path(args.candidate_metadata).read_text()) if args.candidate_metadata else None,
        split_rows=args.split_rows, evaluation_split=args.evaluation_split, leakage_policy=args.leakage_policy,
        evaluation_groups=json.loads(Path(args.evaluation_groups).read_text()) if args.evaluation_groups else None,
        baseline_candidate=args.baseline_candidate, bootstrap_repetitions=args.bootstrap_repetitions, seed=args.seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "report": str(output), "offline": True}))
    return 0 if report["status"] in {"complete", "complete_with_split_overlap"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
