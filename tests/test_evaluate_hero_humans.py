"""Synthetic fixtures only; never read the user's private annotations."""
import copy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "tools/evaluate_hero_humans.py"
SPEC = importlib.util.spec_from_file_location("evaluate_hero_humans", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    sources, labels, predictions = {}, [], {}
    for i in range(3):
        rid = str(i)
        source = dict(zip(MODULE.SOURCE_FIELDS, (rid, "Spotify works", "5", "0", "1", "2026-01-01")))
        sources[rid] = source
        labels.append({"review_id": rid, "review_text": source["review_text"], "row_sha": MODULE.source_hash(source),
                       "topic": "other", "intent": "praise", "severity": None, "sentiment": None,
                       "needs_review": False, "ambiguous": False, "entities": None, "evidence_quote": source["review_text"],
                       "annotation_provenance": {"topic": "annotated", "intent": "annotated", "severity": "not_assessed",
                           "sentiment": "not_assessed", "needs_review": "default_false", "ambiguous": "default_false",
                           "entities": "not_assessed", "evidence_quote": "default_full_source"}})
        predictions[rid] = {**source, "source_sha256": MODULE.source_hash(source), "status": "completed",
                            "topic": "other", "intent": "praise", "severity": 1, "sentiment": .9,
                            "needs_review": False, "entities": ["Spotify"], "evidence_quote": source["review_text"]}
    document = {"annotation_protocol": "human-partial-v3", "labels": labels,
                "source_digest": MODULE.digest([{key: row[key] for key in ("review_id", "review_text", "row_sha")} for row in labels])}
    return document, sources, predictions


def test_each_field_has_its_own_mask_and_no_imputation():
    document, sources, predictions = fixture()
    document["labels"][0]["topic"] = None
    document["labels"][0]["annotation_provenance"]["topic"] = "not_assessed"
    report = MODULE.evaluate(document, sources, predictions, {"0", "1", "2"}, {"0"})
    fields = report["groups"]["all_annotated_worksheet"]["fields"]
    assert fields["topic"]["exact_agreement"] == {"numerator": 2, "denominator": 2, "value": 1}
    assert fields["intent"]["exact_agreement"]["denominator"] == 3
    assert fields["severity"]["exact_agreement"]["denominator"] == 0
    assert fields["entities"]["exact_agreement"]["value"] is None
    assert fields["needs_review"]["explicitly_annotated"] == 0


def test_missing_in_scope_counts_in_exact_denominator_but_outside_scope_does_not():
    document, sources, predictions = fixture()
    del predictions["1"]
    fields = MODULE.evaluate(document, sources, predictions, {"0", "1"}, {"0"})["groups"]["all_annotated_worksheet"]["fields"]
    assert fields["intent"]["exact_agreement"] == {"numerator": 1, "denominator": 2, "value": .5}
    assert fields["intent"]["outside_selected_cohort"] == 1
    assert fields["intent"]["missing_or_invalid_prediction_count"] == 1
    assert any(row["prediction"] == "__missing_or_invalid__" for row in fields["intent"]["confusion"])


def test_explicit_numeric_mae_and_no_private_rows_exported():
    document, sources, predictions = fixture()
    document["labels"][0]["sentiment"] = 1
    document["labels"][0]["annotation_provenance"]["sentiment"] = "annotated"
    before = copy.deepcopy(document)
    result = MODULE.evaluate(document, sources, predictions, set(sources), {"0"})
    metric = result["groups"]["all_annotated_worksheet"]["fields"]["sentiment"]
    assert metric["mae_denominator"] == 1
    assert metric["mean_absolute_error"] == pytest.approx(.1)
    assert document == before
    serialized = MODULE.canonical(result)
    assert "Spotify works" not in serialized
    assert "review_id" not in serialized


def test_error_capture_is_measured_against_label_errors_not_default_flags():
    document, sources, predictions = fixture()
    predictions["0"]["topic"] = "usability"
    predictions["0"]["needs_review"] = True
    del predictions["1"]
    metric = MODULE.evaluate(document, sources, predictions, set(sources), {"0"})["groups"]["all_annotated_worksheet"]["needs_review_detection_of_topic_or_intent_errors"]
    assert metric["observed_errors_including_missing_predictions"] == 2
    assert metric["error_capture_recall"]["value"] == .5
    assert metric["flag_precision"]["value"] == 1
    assert metric["missing_or_invalid_predictions"] == 1


@pytest.mark.parametrize("kind", ["reference", "prediction", "default_quote", "unassessed_value", "duplicate"])
def test_corrupt_input_fails_closed(kind):
    document, sources, predictions = fixture()
    if kind == "reference":
        document["labels"][0]["row_sha"] = "a" * 64
    elif kind == "prediction":
        predictions["0"]["source_sha256"] = "a" * 64
    elif kind == "default_quote":
        document["labels"][0]["evidence_quote"] = "Spotify"
    elif kind == "unassessed_value":
        document["labels"][0]["severity"] = 1
    else:
        document["labels"].append(document["labels"][0])
    with pytest.raises(ValueError):
        MODULE.evaluate(document, sources, predictions, set(sources), {"0"})
