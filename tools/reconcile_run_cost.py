#!/usr/bin/env python3
"""Offline, auditable correction of a legacy output-path run-ID collision.

Never changes the spending ledger, call logs, model outputs, or elapsed time.
Only already settled, unrelated ledger entries may be excluded from a summary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from spotify_pipeline.storage import BudgetLedger, atomic_json, canonical, utcnow


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def totals(rows: list[dict]) -> dict:
    spent = sum(row["charged_nano"] or 0 for row in rows)
    reserved = sum(row["reserved_nano"] for row in rows if row["state"] == "reserved")
    unknown = sum(row["reserved_nano"] for row in rows if row["state"] == "unknown")
    return {"spent_usd": spent / 1e9, "reserved_usd": reserved / 1e9,
            "unknown_charge_hold_usd": unknown / 1e9,
            "committed_usd": (spent + reserved + unknown) / 1e9, "attempts": len(rows)}


def reconcile(run_dir: str | Path, ledger_path: str | Path) -> dict:
    run_dir, ledger_path = Path(run_dir).resolve(), Path(ledger_path).resolve()
    summary_path, calls_path = run_dir / "run_summary.json", run_dir / "calls.jsonl"
    summary_bytes, calls_bytes = summary_path.read_bytes(), calls_path.read_bytes()
    correction = run_dir / "accounting_correction"
    audit_path = correction / "audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text())
        if (audit.get("status") == "completed" and
                audit["corrected_summary_sha256"] == sha(summary_bytes) and
                audit["calls_sha256"] == sha(calls_bytes)):
            return audit
        raise ValueError("Existing correction differs from current evidence; preserve it and inspect manually.")
    summary = json.loads(summary_bytes)
    calls = [json.loads(line) for line in calls_bytes.splitlines() if line.strip()]
    ids = [call["request_id"] for call in calls]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate request IDs in calls.jsonl.")
    if any(call["run_id"] != summary["run_id"] or call["label_config"] != summary["label_config"] for call in calls):
        raise ValueError("Call identity differs from the saved summary.")
    with sqlite3.connect(f"{ledger_path.as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        snapshot = [dict(row) for row in conn.execute("SELECT * FROM spend ORDER BY request_id")]
    by_id = {row["request_id"]: row for row in snapshot}
    if any(rid not in by_id for rid in ids):
        raise ValueError("A saved request is missing from the ledger.")
    included = [by_id[rid] for rid in ids]
    excluded = [row for row in snapshot if row["run_id"] == summary["run_id"] and row["request_id"] not in set(ids)]
    if any(row["state"] != "settled" for row in excluded):
        raise ValueError("Unmatched unsettled ledger holds cannot be excluded; inspect the interrupted requests.")
    for call, entry in zip(calls, included):
        if entry["run_id"] != summary["run_id"]:
            raise ValueError("Ledger request belongs to another run.")
        expected = None if call.get("cost_usd") is None else BudgetLedger._nano(call["cost_usd"])
        if entry["charged_nano"] != expected:
            raise ValueError("Call cost and integer ledger charge differ.")
        if (expected is not None) != (entry["state"] == "settled"):
            raise ValueError("Call billing completeness and ledger state differ.")
    spending = totals(included)
    corrected = {**summary, "api_cost_usd": spending["spent_usd"],
                 "api_cost_complete": not bool(spending["reserved_usd"] or spending["unknown_charge_hold_usd"]),
                 "spending": spending, "requests": len(calls), "attempts": len(calls),
                 "accounting_basis": "exact_request_ids_in_calls_jsonl",
                 "accounting_correction": "accounting_correction/audit.json"}
    assert corrected["global_spending"] == summary["global_spending"]
    assert corrected.get("wall_seconds") == summary.get("wall_seconds")
    correction.mkdir()
    (correction / "run_summary.before.json").write_bytes(summary_bytes)
    cost_summary_path = run_dir / "cost" / "run_summary.json"
    if cost_summary_path.exists():
        (correction / "cost_run_summary.before.json").write_bytes(cost_summary_path.read_bytes())
    atomic_json(correction / "run_summary.corrected.json", corrected)
    corrected_bytes = (correction / "run_summary.corrected.json").read_bytes()
    audit = {
        "version": "legacy-run-id-accounting-correction-v1", "status": "prepared", "created_at": utcnow(),
        "reason": "Legacy run_id depended only on reused output path and included archived experiment charges.",
        "original_summary_sha256": sha(summary_bytes), "corrected_summary_sha256": sha(corrected_bytes),
        "calls_sha256": sha(calls_bytes), "included_request_ids": ids,
        "excluded_settled_request_ids": [row["request_id"] for row in excluded],
        "original_spending": summary["spending"], "corrected_spending": spending,
        "global_summary_preserved": summary["global_spending"],
        "ledger_access": "SQLite mode=ro; all rows and charges preserved",
        "ledger_snapshot_sha256": sha(canonical(snapshot).encode()),
        "global_ledger_snapshot_at_correction": totals(snapshot),
        "originals_preserved": ["run_summary.before.json"] + (
            ["cost_run_summary.before.json"] if cost_summary_path.exists() else []),
        "unchanged": ["calls.jsonl", "provider handoffs", "labels", "model configuration", "wall time", "shared ledger"],
    }
    atomic_json(audit_path, audit)
    if calls_path.read_bytes() != calls_bytes or summary_path.read_bytes() != summary_bytes:
        raise ValueError("Run evidence changed during reconciliation; prepared correction retained without applying.")
    atomic_json(summary_path, corrected)
    if cost_summary_path.exists():
        atomic_json(cost_summary_path, corrected)
    audit["status"] = "completed"
    atomic_json(audit_path, audit)
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.run, args.ledger), indent=2))
