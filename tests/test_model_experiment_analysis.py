"""Offline accounting reconciliation on synthetic logs only."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "offline_model_analysis", Path(__file__).parents[1] / "tools/analyze_model_experiment.py")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def fixture(tmp_path):
    config = {"models": {"enrich": "synthetic-model"}, "reasoning_effort": {"enrich": "none"},
              "rates": {"synthetic_input": .1, "synthetic_output": .2}}
    record = {"review_id": "synthetic", "review_text": "Synthetic review.", "status": "completed",
              "topic": "other", "intent": "praise", "severity": 1, "needs_review": False,
              "raw_needs_review": False}
    call = {"request_id": "synthetic-request", "run_id": "synthetic-run", "label_config": "synthetic-config",
            "provider": "nebius", "model": "synthetic-model", "cost_usd": .00005000000000000001,
            "billing_items": [{"units": 100, "rate_key": "synthetic_input"},
                              {"units": 200, "rate_key": "synthetic_output"}],
            "normalized_usage": {"input_tokens": 100, "output_tokens": 200},
            "api_duration_seconds": 1.0, "outcome": "succeeded"}
    summary = {"run_id": "synthetic-run", "label_config": "synthetic-config", "api_cost_complete": True,
               "api_cost_usd": .000050001, "attempts": 1, "completed": 1, "failed_attempts": 0,
               "wall_seconds": 2.0, "stages": {"enrich": {"wall_seconds": 1.5}}}
    (tmp_path / "calls.jsonl").write_text(json.dumps(call) + "\n")
    (tmp_path / "records.jsonl").write_text(json.dumps(record) + "\n")
    (tmp_path / "experiment_summary.json").write_text(json.dumps(summary))
    (tmp_path / "condition_manifest.json").write_text("{}")
    return config, [record], call


def test_exact_nominal_cost_and_conservative_nano_ledger_rounding_are_both_preserved(tmp_path):
    config, records, _ = fixture(tmp_path)
    result = analysis.summarize_operations(tmp_path, config, records, "synthetic-config")
    assert result["nominal_cost_usd"] == .00005
    assert result["ledger_accounted_usd"] == .000050001
    assert result["cost_reconciliation"]["ledger_minus_nominal_usd"] == 1e-9
    assert result["usage_unknown_call_counts"] == {"cached_input_tokens": 1, "reasoning_tokens": 1}
    assert "reasoning_tokens" not in result["usage_sum_of_reported_values"]


@pytest.mark.parametrize("corruption", ["duplicate_request", "wrong_cost", "foreign_run", "unknown_charge"])
def test_invalid_cost_or_lineage_is_rejected_before_reporting(tmp_path, corruption):
    config, records, call = fixture(tmp_path)
    calls = [call]
    if corruption == "duplicate_request":
        calls.append(dict(call))
    elif corruption == "wrong_cost":
        call["cost_usd"] = .01
    elif corruption == "foreign_run":
        call["run_id"] = "foreign"
    else:
        call["unknown_charge_hold_usd"] = .001
    (tmp_path / "calls.jsonl").write_text("".join(json.dumps(row) + "\n" for row in calls))
    with pytest.raises(ValueError):
        analysis.summarize_operations(tmp_path, config, records, "synthetic-config")
