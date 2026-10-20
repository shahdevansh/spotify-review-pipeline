"""All evaluation fixtures are synthetic; no golden labels or provider calls."""
import copy
import json
import math

import pytest

from spotify_pipeline.data import row_sha
from spotify_pipeline.harness import (
    audit_split_leakage, cluster_bootstrap, evaluate_candidates, main,
    routing_metrics, wilson_interval,
)


def source(rid, text=None):
    return {"review_id": str(rid), "review_text": text or f"Synthetic text {rid}",
            "review_rating": "1", "review_likes": "0", "app_version": "",
            "review_timestamp": "2023-01-01"}


def prediction(row, **changes):
    return {**row, "source_sha256": row_sha(row), "label_config": "synthetic-frozen",
            "status": "completed", "topic": "playback", "intent": "complaint",
            "severity": 3, "sentiment": -.5, "needs_review": False, **changes}


def evaluate(rows, candidates, **kwargs):
    return evaluate_candidates(rows, candidates, bootstrap_repetitions=200, seed=4, **kwargs)


@pytest.mark.parametrize("correct,expected", [
    (0, (0, .2775328)), (5, (.2365931, .7634069)), (10, (.7224672, 1)),
])
def test_wilson_known_bounds(correct, expected):
    result = wilson_interval(correct, 10)
    assert result["lower"] == pytest.approx(expected[0], abs=1e-7)
    assert result["upper"] == pytest.approx(expected[1], abs=1e-7)
    assert result["successes"] == correct and result["trials"] == 10


def test_wilson_empty_and_invalid_counts():
    assert wilson_interval(0, 0)["estimate"] is None
    assert wilson_interval(0, 0)["lower"] is None
    for numerator, denominator in [(2, 1), (-1, 1), (True, 2), (1, -1)]:
        with pytest.raises(ValueError):
            wilson_interval(numerator, denominator)


def test_no_reference_gives_pairwise_agreement_and_rank_sensitivity_not_accuracy():
    rows = [source("a"), source("b")]
    a = [prediction(row) for row in rows]
    b = [prediction(rows[0], topic="billing", severity=4), prediction(rows[1])]
    report = evaluate(rows, {"a": a, "b": b})
    pair = report["pairwise_agreement"][0]
    assert pair["metrics"]["topic"]["agreement"]["estimate"] == .5
    assert "accuracy" not in pair["metrics"]["topic"]
    assert report["reference"]["kind"] == "none"
    assert report["reference"]["human_accuracy_available"] is False
    assert "routing" not in report["candidates"]["a"]
    assert report["ranking_sensitivity"]["pairwise"][0]["top_issue_same"] is False
    assert report["ranking_sensitivity"]["rankings"]["a"]["ranking"][0]["severity_sum"] == 6


def test_human_attestation_required_and_ai_reference_is_not_accuracy():
    row = source("a")
    answers = [prediction(row)]
    with pytest.raises(ValueError, match="human_labels_confirmed"):
        evaluate([row], {"a": answers}, references=answers, reference_kind="human")
    report = evaluate([row], {"a": answers}, references=answers, reference_kind="ai")
    metrics = report["candidates"]["a"]["reference_metrics"]
    assert "agreement" in metrics["topic"] and "accuracy" not in metrics["topic"]
    assert "routing" not in report["candidates"]["a"]
    assert report["reference"]["human_accuracy_available"] is False
    with pytest.raises(ValueError, match="boolean"):
        evaluate([row], {"a": answers}, references=answers, reference_kind="human",
                 human_labels_confirmed="yes")


def test_missing_and_invalid_predictions_remain_in_reference_denominator():
    rows = [source(i) for i in range(4)]
    gold = [prediction(row) for row in rows[:3]]  # Fourth ID is genuinely unlabeled.
    candidates = [prediction(rows[0]), prediction(rows[1], severity="3")]
    report = evaluate(rows, {"a": candidates}, references=gold, reference_kind="human",
                      human_labels_confirmed=True)
    candidate = report["candidates"]["a"]
    metrics = candidate["reference_metrics"]
    assert report["status"] == "incomplete"
    assert candidate["coverage"]["missing_ids"] == ["2", "3"]
    assert candidate["coverage"]["invalid_or_noncompleted"]["1"]["kind"] == "invalid_labels"
    assert metrics["topic"]["accuracy"]["successes"] == 1
    assert metrics["topic"]["accuracy"]["trials"] == 3
    assert metrics["severity"]["numeric_denominator"] == 1
    assert metrics["severity"]["mean_absolute_difference"] == 0
    assert report["reference"]["unlabeled_ids"] == ["3"]
    assert candidate["routing"]["forced_review_failures"] == 2
    assert candidate["routing"]["error_capture_by_flag_or_forced_review"]["value"] == 1


@pytest.mark.parametrize("corruption", ["duplicate", "foreign", "changed_text", "wrong_hash", "nested_id", "mixed_config"])
def test_identity_failures_are_rejected_not_silently_filtered(corruption):
    rows = [source("a"), source("b")]
    predictions = [prediction(row) for row in rows]
    if corruption == "duplicate":
        predictions.append(predictions[0])
    elif corruption == "foreign":
        predictions.append(prediction(source("foreign")))
    elif corruption == "changed_text":
        predictions[0]["review_text"] = "Changed."
    elif corruption == "wrong_hash":
        predictions[0]["source_sha256"] = "0" * 64
    elif corruption == "nested_id":
        predictions[0]["prediction"] = {"review_id": "b"}
    else:
        predictions[0]["label_config"] = "different"
    with pytest.raises(ValueError):
        evaluate(rows, {"a": predictions})


def test_compact_source_bound_prediction_and_declared_frozen_metadata():
    row = source("a")
    compact = {key: value for key, value in prediction(row).items()
               if key not in (*row.keys(), "label_config")}
    compact["review_id"] = "a"
    report = evaluate([row], {"a": [compact]}, candidate_metadata={"a": {"config_id": "synthetic-compact"}})
    assert report["status"] == "complete"
    assert report["candidates"]["a"]["config_id"] == "synthetic-compact"
    compact.pop("source_sha256")
    with pytest.raises(ValueError, match="source_sha256 or exact review_text"):
        evaluate([row], {"a": [compact]}, candidate_metadata={"a": {"config_id": "synthetic-compact"}})


def test_invalid_reference_raises_instead_of_disappearing():
    row = source("a")
    with pytest.raises(ValueError):
        evaluate([row], {"a": [prediction(row)]}, references=[prediction(row, topic="invented")],
                 reference_kind="human", human_labels_confirmed=True)


def test_confusion_macro_f1_and_absent_support_are_explicit():
    rows = [source(i) for i in range(3)]
    gold = [prediction(rows[0]), prediction(rows[1]), prediction(rows[2], topic="billing")]
    predictions = [prediction(rows[0]), prediction(rows[1], topic="billing"), prediction(rows[2], topic="billing")]
    report = evaluate(rows, {"a": predictions}, references=gold, reference_kind="human",
                      human_labels_confirmed=True)
    topic = report["candidates"]["a"]["reference_metrics"]["topic"]
    assert topic["accuracy"]["estimate"] == pytest.approx(2 / 3)
    assert topic["per_class"]["playback"]["reference_support"] == 2
    assert topic["per_class"]["playback"]["predicted_support"] == 1
    assert topic["per_class"]["access"]["f1"] is None
    assert topic["macro_f1_present_labels"] == pytest.approx(2 / 3)
    assert topic["macro_f1_all_taxonomy_labels"] == pytest.approx((2 / 3 + 2 / 3) / 8)
    assert sum(row["count"] for row in topic["confusion"]) == 3


def test_boolean_routing_has_correct_denominators_and_never_uses_flag_as_error():
    ids = ["correct-flagged", "wrong-flagged", "wrong-unflagged", "missing"]
    base = {"topic": "playback", "intent": "complaint", "severity": 3, "sentiment": 0, "needs_review": False}
    reference = {rid: dict(base) for rid in ids}
    predictions = {
        ids[0]: {**base, "needs_review": True}, ids[1]: {**base, "topic": "billing", "needs_review": True},
        ids[2]: {**base, "severity": 4},
    }
    result = routing_metrics(ids, predictions, reference)
    assert result["flag_precision_for_core_error"]["value"] == .5
    assert result["error_capture_by_review_flag"]["value"] == .5
    assert result["error_capture_by_flag_or_forced_review"]["value"] == pytest.approx(2 / 3)
    accepted = result["risk_coverage"][1]
    assert accepted["coverage"]["value"] == .25
    assert accepted["selective_risk"]["estimate"] == 1
    assert result["risk_coverage"][0]["selective_risk"]["estimate"] is None


def test_routing_zero_denominators_and_raw_audited_flags_are_distinct():
    row = source("a")
    p = prediction(row, needs_review=True, raw_model_needs_review=False)
    report = evaluate([row], {"a": [p]}, references=[prediction(row)], reference_kind="human",
                      human_labels_confirmed=True)
    route = report["candidates"]["a"]["routing"]
    assert route["risk_coverage"][1]["coverage"]["value"] == 0
    assert route["risk_coverage"][1]["selective_risk"]["estimate"] is None
    assert route["error_capture_by_review_flag"]["value"] is None
    assert report["candidates"]["a"]["needs_review"]["raw_model_flag_counts"] == {"false": 1}
    assert report["candidates"]["a"]["needs_review"]["audited_true"] == 1


def test_actual_engine_raw_flag_alias_is_supported_without_rewriting_records():
    row = source("a")
    p = prediction(row, needs_review=True, raw_needs_review=False)
    report = evaluate([row], {"a": [p]}, references=[prediction(row)], reference_kind="human",
                      human_labels_confirmed=True)
    candidate = report["candidates"]["a"]
    assert candidate["needs_review"]["raw_model_flag_counts"] == {"false": 1}
    assert candidate["raw_model_routing"]["review_flag_rate"]["value"] == 0
    assert "raw_model_needs_review" not in p
    bad = evaluate([row], {"a": [{**p, "raw_model_needs_review": True}]})
    assert bad["status"] == "incomplete"
    assert "Conflicting" in bad["candidates"]["a"]["coverage"]["invalid_or_noncompleted"]["a"]["reason"]


def test_source_exposure_reports_all_mandatory_labels_and_unseen_text_stratum():
    rows = [source("gold-a", "Repeated exact source."), source("gold-b", "Unseen source.")]
    development = [{**source("dev-x", "Repeated exact source."), "split": "development"}]
    p = [prediction(row) for row in rows]
    with pytest.raises(ValueError, match="Cross-split"):
        evaluate(rows, {"a": p}, split_rows=development)
    report = evaluate(rows, {"a": p}, references=p, reference_kind="human",
                      human_labels_confirmed=True, split_rows=development, leakage_policy="report")
    assert report["status"] == "complete_with_split_overlap"
    assert report["reference"]["labeled_count"] == 2
    assert report["reference"]["unseen_text_labeled_count"] == 1
    assert report["split_audit"]["label_leakage"] == "not_assessed"
    assert report["split_audit"]["cross_split_ids"] == {}
    assert report["split_audit"]["evaluation_text_exposed_ids"] == ["gold-a"]
    assert report["candidates"]["a"]["reference_metrics"]["reference_ids"] == 2
    assert report["candidates"]["a"]["unseen_text_reference_metrics"]["reference_ids"] == 1


def test_seeded_cluster_uncertainty_is_reorder_invariant_and_keeps_multiplicity():
    rows = [source("a", "Repeated."), source("b", "Repeated."), source("c", "Different.")]
    p = [prediction(rows[0]), prediction(rows[1]), prediction(rows[2], topic="billing")]
    refs = [prediction(row) for row in rows]
    first = evaluate(rows, {"a": p}, references=refs, reference_kind="ai")
    second = evaluate(rows[::-1], {"a": p[::-1]}, references=refs[::-1], reference_kind="ai")
    assert first == second
    boot = first["candidates"]["a"]["cluster_uncertainty"]
    assert boot["clusters"] == 2 and boot["records"] == 3
    assert boot["intervals"]["topic_match"]["estimate"] == pytest.approx(2 / 3)
    assert boot["intervals"]["topic_match"]["valid_repetitions"] == 200
    assert boot["intervals"]["topic_match"]["lower"] == 0
    assert boot["intervals"]["topic_match"]["upper"] == 1
    assert boot["intervals"]["topic_match"]["reportable"] is True


def test_identical_candidates_keep_zero_empirical_difference_without_claiming_population_equivalence():
    rows = [source(i) for i in range(5)]
    p = [prediction(row) for row in rows]
    report = evaluate(rows, {"base": p, "other": copy.deepcopy(p)}, references=p,
                      reference_kind="human", human_labels_confirmed=True, baseline_candidate="base")
    intervals = report["paired_reference_differences"]["candidate_minus_baseline"]["other"]["intervals"]
    assert all(value["estimate"] == 0 and value["lower"] is None and value["upper"] is None
               for value in intervals.values())
    assert all(value["interval_status"] == "degenerate_resamples" for value in intervals.values())
    assert all(value["empirical_percentile_range"] == {"lower": 0, "upper": 0, "inferential": False}
               for value in intervals.values())


def test_paired_mae_has_no_estimate_when_candidates_cover_disjoint_ids():
    rows = [source("a"), source("b")]
    refs = [prediction(row) for row in rows]
    report = evaluate(rows, {"base": [prediction(rows[0])],
                            "other": [prediction(rows[1], severity=5)]},
                      references=refs, reference_kind="human", human_labels_confirmed=True,
                      baseline_candidate="base")
    delta = report["paired_reference_differences"]["candidate_minus_baseline"]["other"]
    assert delta["denominators"]["numeric_matched_count"] == 0
    assert delta["denominators"]["binary_reference_count"] == 2
    assert delta["intervals"]["severity_mae"]["estimate"] is None
    assert delta["intervals"]["severity_mae"]["valid_repetitions"] == 0
    assert delta["intervals"]["severity_mae"]["undefined_repetitions"] == 200
    assert delta["intervals"]["topic_match"]["estimate"] == 0


def test_paired_numeric_delta_uses_only_common_valid_reference_ids():
    rows = [source("a"), source("b"), source("c")]
    refs = [prediction(row) for row in rows]
    report = evaluate(rows, {
        "base": [prediction(rows[0], severity=1), prediction(rows[1], severity=3)],
        "other": [prediction(rows[1], severity=4), prediction(rows[2], severity=1)],
    }, references=refs, reference_kind="ai", baseline_candidate="base")
    delta = report["paired_reference_differences"]["candidate_minus_baseline"]["other"]
    assert delta["denominators"]["numeric_matched_ids"] == ["b"]
    assert delta["intervals"]["severity_mae"]["estimate"] == 1
    assert delta["intervals"]["severity_mae"]["lower"] is None
    assert delta["intervals"]["severity_mae"]["upper"] is None
    assert delta["intervals"]["severity_mae"]["contributing_clusters"] == 1
    assert delta["intervals"]["severity_mae"]["interval_status"] == "insufficient_contributing_clusters"
    assert delta["intervals"]["topic_match"]["contributing_clusters"] == 3


def test_numeric_support_counts_text_clusters_not_many_alias_ids():
    rows = [source("a", "Same."), source("b", "Same."), source("c"), source("d")]
    refs = [prediction(row) for row in rows]
    report = evaluate(rows, {"a": [prediction(rows[0], severity=5), prediction(rows[1], severity=5)]},
                      references=refs, reference_kind="ai",
                      evaluation_groups={"all": [row["review_id"] for row in rows]})
    for metrics in (report["candidates"]["a"],
                    report["evaluation_groups"]["all"]["candidates"]["a"]):
        boot = metrics["cluster_uncertainty"]
        numeric = boot["intervals"]["severity_mae"]
        assert boot["clusters"] == 3
        assert numeric["contributing_records"] == 2
        assert numeric["contributing_clusters"] == 1
        assert numeric["estimate"] == 2
        assert numeric["lower"] is None and numeric["upper"] is None
        assert numeric["interval_status"] == "insufficient_contributing_clusters"
        assert numeric["undefined_repetitions"] > 0
        assert boot["intervals"]["topic_match"]["contributing_clusters"] == 3


@pytest.mark.parametrize("count", [2, 150, 200])
def test_all_correct_bootstrap_does_not_report_perfect_accuracy_bounds(count):
    rows = [source(i) for i in range(count)]
    answers = [prediction(row) for row in rows]
    report = evaluate(rows, {"a": answers}, references=answers, reference_kind="ai")
    intervals = report["candidates"]["a"]["cluster_uncertainty"]["intervals"]
    for key, expected in (("topic_match", 1), ("severity_mae", 0)):
        item = intervals[key]
        assert item["estimate"] == expected
        assert item["lower"] is None and item["upper"] is None
        assert item["reportable"] is False and item["degenerate_resamples"] is True
        assert item["interval_status"] == "degenerate_resamples"
        assert any("not proof of perfect accuracy" in warning for warning in item["warnings"])


@pytest.mark.parametrize("repetitions", [1, 20, 99])
def test_low_repetition_ranges_are_diagnostic_not_confidence_intervals(repetitions):
    sources = {str(i): {"text_sha256": str(i)} for i in range(3)}
    boot = cluster_bootstrap(list(sources), sources,
                             lambda ids: {"match": sum(r != "0" for r in ids) / len(ids)},
                             repetitions=repetitions, seed=4)
    item = boot["intervals"]["match"]
    assert boot["status"] == "insufficient_repetitions"
    assert item["estimate"] == pytest.approx(2 / 3)
    assert item["lower"] is None and item["upper"] is None
    assert item["valid_repetitions"] == repetitions
    assert item["reportable"] is False
    assert item["interval_status"] == "insufficient_repetitions"


def test_too_few_defined_draws_are_not_enough_even_with_two_contributing_clusters():
    ids = [str(i) for i in range(10)]
    sources = {rid: {"text_sha256": rid} for rid in ids}
    numeric_ids = {"0", "1"}

    def statistic(sample):
        valid = [rid for rid in sample if rid in numeric_ids]
        return {"mean": sum(int(rid) for rid in valid) / len(valid) if valid else None}

    boot = cluster_bootstrap(ids, sources, statistic, repetitions=100, seed=7,
                             contributing_ids={"mean": numeric_ids})
    item = boot["intervals"]["mean"]
    assert item["contributing_clusters"] == 2
    assert 0 < item["valid_repetitions"] < 100
    assert item["interval_status"] == "insufficient_valid_repetitions"
    assert item["lower"] is None and item["upper"] is None


@pytest.mark.parametrize("contributors", [{"unknown": ["a"]}, {"mean": ["foreign"]}, {"mean": "a"}])
def test_invalid_metric_contributors_are_rejected(contributors):
    with pytest.raises(ValueError, match="Contributing IDs"):
        cluster_bootstrap(["a"], {"a": {"text_sha256": "a"}}, lambda ids: {"mean": 1},
                          repetitions=100, seed=1, contributing_ids=contributors)


def test_external_split_rows_need_explicit_tags_and_valid_evaluation_name():
    row = source("gold", "Repeated.")
    development = [source("dev", "Repeated.")]
    with pytest.raises(ValueError, match="explicit nonempty split"):
        evaluate([row], {"a": [prediction(row)]}, split_rows=development)
    with pytest.raises(ValueError, match="evaluation_split"):
        evaluate([row], {"a": [prediction(row)]}, evaluation_split="")


def test_nested_prediction_cannot_replace_verified_source_identity():
    row = source("a")
    with pytest.raises(ValueError, match="nested prediction changes source"):
        evaluate([row], {"a": [prediction(row, prediction={"review_text": "Changed."})]})


@pytest.mark.parametrize("nested", [{"status": "failed"}, {"label_config": "other"}])
def test_nested_prediction_cannot_conflict_with_outer_status_or_frozen_config(nested):
    row = source("a")
    with pytest.raises(ValueError, match="conflicting nested"):
        evaluate([row], {"a": [prediction(row, prediction=nested)]})


def test_nested_only_status_is_respected_and_nested_config_is_validated():
    row = source("a")
    labels = {key: value for key, value in prediction(row, status="failed").items() if key not in row}
    envelope = {**row, "prediction": labels}
    report = evaluate([row], {"a": [envelope]})
    assert report["status"] == "incomplete"
    assert report["candidates"]["a"]["config_id"] == "synthetic-frozen"
    failure = report["candidates"]["a"]["coverage"]["invalid_or_noncompleted"]["a"]
    assert failure == {"kind": "noncompleted", "status": "failed", "reason": None}


def test_malformed_nested_prediction_keeps_provenance_and_explicit_invalid_coverage():
    row = source("a")
    report = evaluate([row], {"a": [prediction(row, prediction="malformed")]})
    assert report["status"] == "incomplete"
    assert report["candidates"]["a"]["config_id"] == "synthetic-frozen"
    assert report["candidates"]["a"]["coverage"]["invalid_or_noncompleted"]["a"]["kind"] == "invalid_labels"


def test_named_groups_keep_mandatory_and_fresh_labels_separate():
    rows = [source("gold-exposed", "Seen."), source("gold-new"), source("fresh-a"), source("fresh-b")]
    refs = [prediction(row) for row in rows]
    p = [prediction(rows[0], topic="billing"), *refs[1:]]
    report = evaluate(
        rows, {"a": p}, references=refs, reference_kind="human", human_labels_confirmed=True,
        split_rows=[{**source("dev", "Seen."), "split": "development"}], leakage_policy="report",
        evaluation_groups={"mandatory": ["gold-exposed", "gold-new"], "fresh": ["fresh-a", "fresh-b"]},
    )
    assert report["reference"]["labeled_count"] == 4
    golden = report["evaluation_groups"]["mandatory"]
    fresh = report["evaluation_groups"]["fresh"]
    assert golden["labeled_count"] == 2 and golden["exposed_text_labeled_count"] == 1
    assert golden["candidates"]["a"]["reference_metrics"]["topic"]["accuracy"]["estimate"] == .5
    assert golden["candidates"]["a"]["unseen_text_reference_metrics"]["topic"]["accuracy"]["estimate"] == 1
    assert golden["candidates"]["a"]["exposed_text_reference_metrics"]["topic"]["accuracy"]["estimate"] == 0
    assert fresh["labeled_count"] == 2 and fresh["exposed_text_labeled_count"] == 0
    assert fresh["candidates"]["a"]["reference_metrics"]["topic"]["accuracy"]["estimate"] == 1
    assert report["group_accounting"]["grouped_ids"] == 4
    assert "not a population estimate" in report["group_accounting"]["interpretation"]


@pytest.mark.parametrize("groups", [
    {"": ["a"]}, {"x": []}, {"x": ["foreign"]}, {"x": ["a", "a"]},
    {"x": ["a"], "y": ["a"]}, {"x": "a"},
])
def test_invalid_evaluation_groups_rejected(groups):
    row = source("a")
    with pytest.raises(ValueError):
        evaluate([row], {"a": [prediction(row)]}, evaluation_groups=groups)


def test_primary_confusion_is_separate_from_human_acceptable_set_metrics():
    row = source("a")
    reference = prediction(row, alternative_topics=["billing"], alternative_severities=[4],
                           ambiguous=True, evidence_support="supported")
    p = prediction(row, topic="billing", severity=4, needs_review=True, raw_model_needs_review=False)
    report = evaluate([row], {"a": [p]}, references=[reference], reference_kind="human",
                      human_labels_confirmed=True)
    candidate = report["candidates"]["a"]
    assert candidate["reference_metrics"]["topic"]["accuracy"]["estimate"] == 0
    assert candidate["acceptable_set_reference_metrics"]["field_matches"]["topic"]["estimate"] == 1
    assert candidate["acceptable_set_reference_metrics"]["joint_core_match"]["estimate"] == 1
    assert candidate["acceptable_set_reference_metrics"]["nearest_accepted_severity_mae"] == 0
    assert candidate["routing"]["flag_precision_for_core_error"]["value"] == 1
    assert candidate["acceptable_set_routing"]["flag_precision_for_core_error"]["value"] == 0
    assert candidate["raw_model_routing"]["flag_field"] == "raw_model_needs_review"
    assert candidate["raw_model_routing"]["review_flag_rate"]["value"] == 0
    assert candidate["raw_model_routing"]["risk_coverage"][1]["selective_risk"]["estimate"] == 1
    assert report["reference"]["accepted_alternatives_count"] == 1
    assert report["reference"]["annotator_evidence_support_counts"] == {"supported": 1}


@pytest.mark.parametrize("annotations", [
    {"accepted_topic": '["playback", "billing"]'},
    {"alternative_topics": ["billing"], "accepted_topic": ["billing", "playback"]},
])
def test_legacy_accepted_labels_have_explicit_supported_semantics(annotations):
    row = source("a")
    report = evaluate([row], {"a": [prediction(row, topic="billing")]},
                      references=[prediction(row, **annotations)], reference_kind="human",
                      human_labels_confirmed=True)
    metrics = report["candidates"]["a"]["acceptable_set_reference_metrics"]
    assert metrics["field_matches"]["topic"]["estimate"] == 1


@pytest.mark.parametrize("annotations", [
    {"alternative_topics": ["invented"]}, {"alternative_severities": [True]},
    {"alternative_intents": "not-json"}, {"accepted_topic": []},
    {"accepted_topic": ["billing"]}, {"alternative_topics": ["billing", "billing"]},
    {"alternative_topics": ["billing"], "accepted_topic": ["playback"]},
    {"evidence_support": "proved"},
])
def test_invalid_reference_annotations_rejected(annotations):
    row = source("a")
    with pytest.raises(ValueError):
        evaluate([row], {"a": [prediction(row)]}, references=[prediction(row, **annotations)],
                 reference_kind="human", human_labels_confirmed=True)


def test_missing_predictions_use_all_candidate_common_cohort_for_ranking():
    rows = [source("a"), source("b")]
    report = evaluate(rows, {"a": [prediction(rows[0]), prediction(rows[1], topic="billing", severity=5)],
                            "b": [prediction(rows[0])]})
    ranking = report["ranking_sensitivity"]
    assert ranking["matched_count"] == 1 and ranking["excluded_ids"] == ["b"]
    assert all(value["top_issue"] == "issue-playback" for value in ranking["rankings"].values())
    assert report["pairwise_agreement"][0]["cohort_size"] == 2


def test_ranking_retains_duplicate_originals_ignores_praise_and_ties_lexically():
    rows = [source("a", "Same."), source("b", "Same."), source("c"), source("d")]
    p = [prediction(rows[0], severity=2), prediction(rows[1], severity=2),
         prediction(rows[2], topic="billing", severity=4),
         prediction(rows[3], topic="access", severity=1, intent="praise")]
    report = evaluate(rows, {"a": p})
    ranks = report["ranking_sensitivity"]["rankings"]["a"]["ranking"]
    assert [row["issue_id"] for row in ranks] == ["issue-billing", "issue-playback"]
    assert ranks[1]["complaint_count"] == 2 and ranks[1]["severity_sum"] == 4


def test_empty_prediction_file_requires_declared_config_and_reports_all_missing():
    rows = [source("a")]
    report = evaluate(rows, {"a": []}, candidate_metadata={"a": {"config_id": "synthetic-empty"}})
    assert report["status"] == "incomplete"
    assert report["candidates"]["a"]["coverage"]["missing_ids"] == ["a"]
    assert report["ranking_sensitivity"]["matched_count"] == 0


def test_cli_offline_serializable_and_refuses_overwrite(tmp_path, capsys):
    rows = [source("a"), source("b")]
    source_file, predictions, report = tmp_path / "sources.jsonl", tmp_path / "answers.jsonl", tmp_path / "report.json"
    source_file.write_text("".join(json.dumps(row) + "\n" for row in rows))
    predictions.write_text("".join(json.dumps(prediction(row)) + "\n" for row in rows))
    args = ["--sources", str(source_file), "--candidate", f"frozen={predictions}",
            "--bootstrap-repetitions", "20", "--out", str(report)]
    assert main(args) == 0
    assert json.loads(report.read_text())["offline"] is True
    with pytest.raises(ValueError, match="Output exists"):
        main(args)
