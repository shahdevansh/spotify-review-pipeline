"""Synthetic, offline checks of the stability report's denominators and audit."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stability_analysis_under_test", ROOT / "tools/analyze_experiment_stability.py"
)
stability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stability)


def source(index):
    return dict(review_id=f"synthetic-{index}", review_text=f"Synthetic review {index}",
                review_rating="5", review_likes="0", app_version="", review_timestamp="")


def record(index, **changes):
    value = {**source(index), "status": "completed", "topic": "other", "intent": "praise",
             "severity": 1, "sentiment": 1, "raw_needs_review": False,
             "needs_review": False, "label_config": "synthetic-config",
             "source_sha256": stability.row_sha(source(index))}
    return {**value, **changes}


def case(index):
    return {"case": f"synthetic-case-{index}", "source": source(index),
            "expected": dict(topic="other", intent="praise", severity=1, needs_review=False)}


def test_missing_predictions_remain_in_all_denominators():
    result = stability.score_synthetic([case(1), case(2)], [record(1)])
    assert result["semantic_tuple_agreement"] == {"matches": 1, "denominator": 2, "fraction": .5}
    assert result["field_agreement"]["topic"]["denominator"] == 2
    assert result["raw_review_flag_agreement"]["unavailable"] == 1
    assert result["semantic_mismatch_ids"] == ["synthetic-2"]


def test_shared_audit_false_positive_is_separate_from_raw_model_flag():
    result = stability.score_synthetic([case(1)], [record(
        1, needs_review=True, review_reasons=["possible_prompt_injection"])])
    assert result["raw_review_flag_agreement"]["matches"] == 1
    assert result["audited_review_flag_agreement"]["false_positive"] == 1
    assert result["audit_introduced_false_positive_ids"] == ["synthetic-1"]
    assert result["semantic_tuple_agreement"]["matches"] == 1


def test_sentiment_change_does_not_become_semantic_label_disagreement():
    result = stability.compare_records([source(1)], [record(1)], [record(1, sentiment=.8)])
    assert result["semantic_tuple_agreement"]["matches"] == 1
    assert result["any_semantic_difference_or_unavailable_count"] == 0
    assert result["any_difference_or_unavailable_count"] == 1
    assert result["differences"][0]["different_or_unavailable_fields"] == ["sentiment"]


def saved_run(tmp_path):
    directory = tmp_path / "runs/synthetic-arm/batch10"
    directory.mkdir(parents=True)
    row = source(1)
    (directory / "condition_manifest.json").write_text(json.dumps({
        "review_ids": [row["review_id"]], "label_config": "synthetic-config",
        "input_hash": hashlib.sha256(stability.canonical([row]).encode()).hexdigest(),
    }))
    (directory / "records.jsonl").write_text(json.dumps(record(1)) + "\n")
    (directory / "calls.jsonl").write_text(json.dumps({
        "request_id": "synthetic-call", "cost_usd": .0010000000000000002,
        "outcome": "succeeded", "unknown_charge_hold_usd": 0,
    }) + "\n")
    (directory / "experiment_summary.json").write_text(json.dumps({
        "completed": 1, "input_count": 1, "requests": 1, "api_cost_usd": .001000001,
        "all_inputs_completed": True, "api_cost_complete": True, "wall_seconds": 1,
    }))
    return directory


def test_saved_run_cost_reconciles_per_attempt_ledger_rounding(tmp_path):
    saved_run(tmp_path)
    run, records = stability.load_run(tmp_path, "synthetic-arm", "batch10", [source(1)])
    assert run["ready"] and run["all_inputs_completed"]
    assert run["api_cost_usd"] == .001000001
    assert 0 < run["ledger_rounding_usd"] < .0000000011
    assert records[0]["review_id"] == "synthetic-1"


def test_changed_original_source_fields_fail_closed(tmp_path):
    directory = saved_run(tmp_path)
    changed = record(1, review_text="Synthetic altered source")
    (directory / "records.jsonl").write_text(json.dumps(changed) + "\n")
    with pytest.raises(ValueError, match="original source fields differ"):
        stability.load_run(tmp_path, "synthetic-arm", "batch10", [source(1)])


def test_cost_summary_mismatch_fails_closed(tmp_path):
    directory = saved_run(tmp_path)
    path = directory / "experiment_summary.json"
    summary = json.loads(path.read_text())
    summary["api_cost_usd"] = 0
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="known cost disagrees"):
        stability.load_run(tmp_path, "synthetic-arm", "batch10", [source(1)])


def test_missing_final_summary_is_pending_not_zero_cost_success(tmp_path):
    run, records = stability.load_run(tmp_path, "synthetic-arm", "batch10", [source(1)])
    assert run["ready"] is False
    assert "experiment_summary.json" in run["missing_files"]
    assert "api_cost_usd" not in run
    assert records is None


@pytest.mark.parametrize("extra, message", [
    (["unknown-model"], "already belong to the frozen"),
    (["lightning-v6"], "must not repeat"),
])
def test_adaptive_extension_accepts_only_additional_frozen_arms(tmp_path, extra, message):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "design": {"arms": ["lightning-v6", "qwen235-v6", "glm-v6"]},
    }))
    with pytest.raises(ValueError, match=message):
        stability.analyze(tmp_path, extra)


def test_adaptive_cli_cannot_overwrite_preserved_original_report(tmp_path, monkeypatch):
    original = tmp_path / "stability_report.json"
    original.write_text("synthetic preserved initial report")
    monkeypatch.setattr(stability, "analyze",
                        lambda *args: {"all_declared_runs_complete": True})
    monkeypatch.setattr(sys, "argv", [
        "analyze_experiment_stability.py", "--experiment", str(tmp_path),
        "--stress-arm", "glm-v6", "--report", str(original),
    ])
    with pytest.raises(SystemExit) as error:
        stability.main()
    assert error.value.code == 2
    assert original.read_text() == "synthetic preserved initial report"
