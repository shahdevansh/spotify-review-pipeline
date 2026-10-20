"""Synthetic accounting regressions; no provider execution."""
import importlib.util
import json
from pathlib import Path

import pytest

from spotify_pipeline.storage import BudgetLedger

SPEC = importlib.util.spec_from_file_location(
    "reconcile_run_cost", Path(__file__).resolve().parents[1] / "tools/reconcile_run_cost.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(tmp_path, *, orphan_state="settled"):
    ledger_path, run = tmp_path / "ledger.sqlite3", tmp_path / "run"
    run.mkdir()
    ledger = BudgetLedger(ledger_path)
    for rid, cost in (("old", .02), ("current", .006)):
        ledger.reserve(rid, "reused-id", .03, global_cap_usd=1, run_cap_usd=1)
        if rid == "old" and orphan_state == "reserved":
            continue
        ledger.settle(rid, None if rid == "old" and orphan_state == "unknown" else cost)
    summary = {"run_id": "reused-id", "label_config": "synthetic", "requests": 1, "attempts": 1,
               "api_cost_usd": ledger.totals()["spent_usd"], "api_cost_complete": True,
               "spending": ledger.totals(), "global_spending": ledger.totals(), "wall_seconds": 12.5}
    (run / "run_summary.json").write_text(json.dumps(summary))
    (run / "cost").mkdir()
    (run / "cost/run_summary.json").write_text(json.dumps(summary))
    call = {"request_id": "current", "run_id": "reused-id", "label_config": "synthetic", "cost_usd": .006}
    (run / "calls.jsonl").write_text(json.dumps(call) + "\n")
    ledger.close()
    return run, ledger_path


def test_exact_request_correction_preserves_calls_ledger_original_and_time(tmp_path):
    run, ledger_path = fixture(tmp_path)
    original, calls, ledger_bytes = ((run / "run_summary.json").read_bytes(),
                                     (run / "calls.jsonl").read_bytes(), ledger_path.read_bytes())
    audit = MODULE.reconcile(run, ledger_path)
    result = json.loads((run / "run_summary.json").read_text())
    assert result["api_cost_usd"] == .006 and result["spending"]["attempts"] == 1
    assert result["global_spending"]["spent_usd"] == .026
    assert result["wall_seconds"] == 12.5
    assert audit["excluded_settled_request_ids"] == ["old"]
    assert (run / "accounting_correction/run_summary.before.json").read_bytes() == original
    assert (run / "calls.jsonl").read_bytes() == calls
    assert ledger_path.read_bytes() == ledger_bytes
    assert (run / "cost/run_summary.json").read_bytes() == (run / "run_summary.json").read_bytes()
    assert MODULE.reconcile(run, ledger_path) == audit


@pytest.mark.parametrize("orphan_state", ["reserved", "unknown"])
def test_correction_cannot_hide_unmatched_unsettled_attempts(tmp_path, orphan_state):
    run, ledger_path = fixture(tmp_path, orphan_state=orphan_state)
    original = (run / "run_summary.json").read_bytes()
    with pytest.raises(ValueError, match="Unmatched unsettled"):
        MODULE.reconcile(run, ledger_path)
    assert (run / "run_summary.json").read_bytes() == original


def test_correction_rejects_mismatched_call_cost(tmp_path):
    run, ledger_path = fixture(tmp_path)
    calls = json.loads((run / "calls.jsonl").read_text())
    calls["cost_usd"] = .00001
    (run / "calls.jsonl").write_text(json.dumps(calls) + "\n")
    with pytest.raises(ValueError, match="ledger charge differ"):
        MODULE.reconcile(run, ledger_path)
