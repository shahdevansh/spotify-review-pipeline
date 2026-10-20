"""Human-label and verifier diagnostics tested only on synthetic cases."""
import csv
import json

import pytest

from spotify_pipeline.evaluation import compare_verifier, evaluate_golden, evidence_checks, learning_report


def prediction(rid="a", **changes):
    text = "Synthetic playback fails."
    return {
        "review_id": rid, "review_text": text, "status": "completed",
        "topic": "playback", "intent": "complaint", "sentiment": -0.5,
        "severity": 4, "needs_review": False, "evidence_quote": text,
        "entities": [], **changes,
    }


def golden_csv(path, rows=None):
    rows = rows or [{"review_id": "a", "review_text": "Synthetic playback fails.",
                    "topic": "playback", "intent": "complaint", "sentiment": "-0.5",
                    "severity": "4", "needs_review": "false", "evidence_quote": "playback fails",
                    "entities": "[]", "ambiguous": "false"}]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_blank_golden_is_pending_not_accuracy(tmp_path):
    csv_path = golden_csv(tmp_path / "gold.csv", [{"review_id": "a", "review_text": "Synthetic", "topic": ""}])
    result = evaluate_golden(csv_path, [], tmp_path / "eval", expected_count=1)
    assert result["status"] == "pending_human_labels"
    assert result["metrics"] is None


def test_human_attestation_required(tmp_path):
    path = golden_csv(tmp_path / "gold.csv")
    with pytest.raises(ValueError, match="human"):
        evaluate_golden(path, [prediction()], tmp_path / "eval", expected_count=1)


def test_complete_human_labels_and_supported_evidence(tmp_path):
    result = evaluate_golden(golden_csv(tmp_path / "gold.csv"), [prediction()], tmp_path / "eval",
                             human_labels_confirmed=True, expected_count=1)
    assert result["metrics"]["topic_agreement"] == 1
    assert result["metrics"]["severity_mae"] == 0
    assert result["metrics"]["sentiment_mae"] == 0
    assert result["metrics"]["needs_review_precision"] is None
    assert result["human_ground_truth"] is True


def test_missing_predictions_stay_in_agreement_denominators(tmp_path):
    result = evaluate_golden(golden_csv(tmp_path / "gold.csv"), [], tmp_path / "eval",
                             human_labels_confirmed=True, expected_count=1)
    assert result["metrics"]["topic_agreement"] == 0
    assert result["metrics"]["severity_mae"] is None
    assert result["metrics"]["severity_mae_denominator"] == 0
    assert result["missing_or_quarantined_predictions"] == 1


def test_ambiguous_accepted_labels_and_needs_review_false_negative(tmp_path):
    path = golden_csv(tmp_path / "gold.csv", [{
        "review_id": "a", "review_text": "Synthetic playback fails.", "topic": "playback",
        "intent": "complaint", "sentiment": "-0.5", "severity": "3", "needs_review": "true",
        "evidence_quote": "playback fails", "entities": "[]", "ambiguous": "true",
        "accepted_severity": "[3, 4]",
    }])
    result = evaluate_golden(path, [prediction()], tmp_path / "eval",
                             human_labels_confirmed=True, expected_count=1)
    assert result["metrics"]["severity_agreement"] == 1
    assert result["metrics"]["severity_mae"] == 0
    assert result["metrics"]["needs_review_recall"] == 0
    assert result["ambiguous_count"] == 1


def test_bad_human_quote_fails_instead_of_becoming_ground_truth(tmp_path):
    path = golden_csv(tmp_path / "gold.csv")
    path.write_text(path.read_text().replace("playback fails,", "invented quote,"))
    with pytest.raises(ValueError, match="quote"):
        evaluate_golden(path, [prediction()], tmp_path / "eval", human_labels_confirmed=True, expected_count=1)


def test_golden_source_identity_is_checked(tmp_path):
    human = golden_csv(tmp_path / "gold.csv")
    source = tmp_path / "original.csv"
    source.write_text("review_id,review_text\na,The real source review.\n")
    with pytest.raises(ValueError, match="isolated source"):
        evaluate_golden(human, [prediction()], tmp_path / "eval", human_labels_confirmed=True,
                        expected_count=1, golden_source_path=source)


def test_quote_and_entity_checks_do_not_claim_semantic_support():
    checks = evidence_checks(prediction(entities=["playback", "invented account"]), "Synthetic playback fails.")
    assert checks["quote_exact_substring"] is True
    assert checks["entities_unsupported_literal"] == ["invented account"]
    assert checks["semantic_evidence_support"] == "requires_human_inspection"


def test_planted_wrong_label_is_disagreement_not_accuracy(tmp_path):
    original = prediction(topic="billing", severity=5)
    independent = prediction()
    report = compare_verifier([original], [independent], tmp_path)
    assert report["ground_truth"] is False
    assert report["disagreement_count"] == 1
    disagreement = json.loads((tmp_path / "disagreements.jsonl").read_text())
    assert set(disagreement["differing_fields"]) == {"topic", "severity"}
    assert disagreement["severity_absolute_difference"] == 1


def test_verifier_unknown_or_duplicate_ids_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        compare_verifier([prediction()], [prediction("foreign")], tmp_path)
    with pytest.raises(ValueError, match="duplicate"):
        compare_verifier([prediction()], [prediction(), prediction()], tmp_path)


def test_verifier_accepts_saved_engine_prediction_envelope(tmp_path):
    envelope = {"review_id": "a", "status": "completed", "prediction": prediction(),
                "sampling_method": "seeded_sha256_without_replacement", "blind": True}
    result = compare_verifier([prediction()], [envelope], tmp_path)
    assert result["field_agreement"]["topic"] == 1
    assert result["disagreement_count"] == 0


def test_no_run_learning_report_stays_gated(tmp_path):
    result = learning_report(tmp_path)
    assert result["status"] == "gated"
    assert result["input_count"] == 0
    assert result["automatic_scaling"] is False
    assert any("No real model run" in reason for reason in result["expansion_blockers"])


def test_inspection_sheet_is_not_overwritten(tmp_path):
    (tmp_path / "records.jsonl").write_text(json.dumps(prediction()) + "\n")
    result = learning_report(tmp_path)
    path = tmp_path / "evals" / "development_inspection.csv"
    before = path.read_bytes()
    learning_report(tmp_path)
    assert before == path.read_bytes()
    assert result["inspection_rows"] == 1
