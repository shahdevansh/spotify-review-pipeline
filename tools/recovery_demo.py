#!/usr/bin/env python3
"""Actually interrupt and resume a pilot of <=1,000 rows after >=50 saved rows.

Use only after configuration freeze. This is a separate paid recovery experiment,
not a replacement for the official cold/warm measurement. An interrupted request
may have been billed: its shared-ledger reservation is deliberately retained.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def progress_snapshot(db: Path) -> dict:
    """Read only committed records; never create a database while polling."""
    if not db.exists():
        return {"completed_ids": [], "call_count": 0}
    try:
        with sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=0.1) as conn:
            records = [json.loads(row[0]) for row in conn.execute("SELECT record_json FROM records")]
            count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        return {"completed_ids": sorted(row["review_id"] for row in records if row.get("status") == "completed"),
                "call_count": count}
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "locked" in str(exc):
            return {"completed_ids": [], "call_count": 0}
        raise


def ledger_snapshot(path: Path, run_id: str) -> list[dict]:
    """Save this experiment's reservations, without modifying shared accounting."""
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT request_id,reserved_nano,charged_nano,state FROM spend WHERE run_id=? ORDER BY request_id",
            (run_id,))]


def stop_owned_child(child: subprocess.Popen, timeout: float = 30) -> int:
    """Every signal targets this Popen child, never a process name or group."""
    if child.poll() is None:
        child.send_signal(signal.SIGINT)
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.terminate()
        try:
            return child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            return child.wait()


def interrupt_at_checkpoint(command: list[str], db: Path, threshold: int, *,
                            cwd: Path, env: dict | None = None, timeout: float = 600,
                            poll_seconds: float = 0.025, shutdown_timeout: float = 30) -> dict:
    """Launch a real process, observe durable state, and deliver a real SIGINT."""
    print(f"Starting initial pipeline process; SIGINT threshold: {threshold} committed records.", flush=True)
    child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        while child.poll() is None:
            snapshot = progress_snapshot(db)
            if len(snapshot["completed_ids"]) >= threshold:
                event = {
                    "event": "real_sigint_after_committed_checkpoint", "child_pid": child.pid,
                    "signal": "SIGINT", "observed_at": datetime.now(timezone.utc).isoformat(),
                    "observed_completed_ids": snapshot["completed_ids"],
                    "observed_call_count": snapshot["call_count"],
                    "signal_boundary": "external SQLite observation; a provider request may be in flight",
                }
                print(f"Observed {len(snapshot['completed_ids'])} committed completed records. "
                      f"Sending SIGINT to owned child PID {child.pid}.", flush=True)
                child.send_signal(signal.SIGINT)
                try:
                    event["exit_code"] = child.wait(timeout=shutdown_timeout)
                except subprocess.TimeoutExpired:
                    event["exit_code"] = stop_owned_child(child, shutdown_timeout)
                    event["shutdown_timeout"] = True
                return event
            if time.monotonic() >= deadline:
                raise RuntimeError("Interruption threshold was not reached before the deadline; no resume attempted.")
            time.sleep(poll_seconds)
        raise RuntimeError(f"Initial process exited ({child.returncode}) before an observed interruption; no resume attempted.")
    finally:
        if child.poll() is None:
            stop_owned_child(child, shutdown_timeout)


def build_command(args, phase: str) -> list[str]:
    # Keep every run-identity field identical. Only the control-flow phase changes.
    return [sys.executable, "-m", "spotify_pipeline.cli", "run", "--execute-paid",
            "--config", str(args.config), "--input", str(args.input), "--out", str(args.out),
            "--db", str(args.db), "--budget", str(args.budget), "--global-budget", str(args.global_budget),
            "--workers", "1", "--verify-count", str(args.verify_count), "--cache-mode", "cold",
            "--rates", str(args.rates), "--phase", phase]


def assert_recovery(before: dict, after: dict, calls: list[dict],
                    held_before: list[dict], ledger_after: list[dict]) -> dict:
    before_ids = set(before["completed_ids"])
    after_ids = set(after["completed_ids"])
    missing = sorted(before_ids - after_ids)
    rebilled = sorted({review_id for call in calls
                       if call.get("phase") == "resume" and call.get("purpose") == "initial_classification"
                       for review_id in call.get("review_ids", []) if review_id in before_ids})
    after_by_id = {row["request_id"]: row for row in ledger_after}
    changed_holds = [row["request_id"] for row in held_before if after_by_id.get(row["request_id"]) != row]
    result = {"completed_before": len(before_ids), "completed_after": len(after_ids),
              "lost_completed_ids": missing, "reclassified_completed_ids": rebilled,
              "changed_uncertain_reservations": changed_holds,
              "retained_uncertain_reservation_count": len(held_before)}
    result["passed"] = not (missing or rebilled or changed_holds)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--input", type=Path, default=ROOT / "data/source/checkpoint_500.csv")
    parser.add_argument("--out", type=Path, default=Path("runs/recovery-nebius"))
    parser.add_argument("--db", type=Path, default=Path("data/recovery-nebius-cache.sqlite3"))
    parser.add_argument("--rates", type=Path, default=Path("config/rates.csv"))
    parser.add_argument("--budget", type=float, default=1.50)
    parser.add_argument("--global-budget", type=float, default=1.50)
    parser.add_argument("--verify-count", type=int, default=10)
    parser.add_argument("--interrupt-after", type=int, default=50)
    parser.add_argument("--interrupt-timeout", type=float, default=600)
    args = parser.parse_args(argv)
    if not args.execute_paid:
        print("No calls made. Pass --execute-paid to authorize this separate recovery experiment.")
        return 2
    for name in ("config", "input", "out", "db", "rates"):
        path = getattr(args, name)
        setattr(args, name, path.resolve())
    if args.out.exists() or any(Path(str(args.db) + suffix).exists() for suffix in ("", "-wal", "-shm")):
        parser.error("Use fresh --out and --db paths; existing evidence is never overwritten.")
    with args.input.open(newline="", encoding="utf-8") as handle:
        count = sum(1 for _ in csv.DictReader(handle))
    if count > 1000 or not 50 <= args.interrupt_after < count:
        parser.error("Recovery is limited to <=1000 input rows and an interruption threshold >=50 below input size.")
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    ledger = Path(config.get("ledger_path", "data/spend.sqlite3"))
    if not ledger.is_absolute():
        ledger = args.config.parent.parent / ledger
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    print(f"Recovery input: {count} reviews; config: {args.config}; workers: 1; "
          f"verification: {args.verify_count}; global ceiling: ${args.global_budget:.2f}.", flush=True)
    event = interrupt_at_checkpoint(build_command(args, "initial"), args.db, args.interrupt_after,
                                    cwd=ROOT, env=env, timeout=args.interrupt_timeout)
    evidence = args.out / "recovery"
    write_json(evidence / "interruption_event.json", event)
    initial_summary = read_json(args.out / "run_summary.json")
    if event.get("shutdown_timeout") or initial_summary.get("execution_status") != "interrupted":
        raise RuntimeError("The child did not complete its interrupted-checkpoint shutdown; evidence preserved, no resume attempted.")
    before = progress_snapshot(args.db)
    initial_manifest = read_json(args.out / "run_manifest.json")
    initial_ledger = ledger_snapshot(ledger, initial_summary["run_id"])
    held = [row for row in initial_ledger if row["state"] in {"reserved", "unknown"}]
    write_json(evidence / "before_resume.json", {
        **before, "identity": initial_manifest["identity"],
        "config_file_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "ledger_entries": initial_ledger, "uncertain_reservations": held})
    shutil.copy2(args.out / "run_summary.json", evidence / "interrupted_run_summary.json")
    shutil.copy2(args.out / "checkpoint_after.json", evidence / "interrupted_checkpoint.json")
    if args.config.read_bytes() != config_bytes:
        raise RuntimeError("Configuration file changed during interruption; no resume attempted.")
    print(f"Interrupted shutdown persisted {len(before['completed_ids'])} completed records. "
          f"{len(held)} uncertain charge reservations remain held. Resuming the same run.", flush=True)
    resumed = subprocess.Popen(build_command(args, "resume"), cwd=ROOT, env=env, start_new_session=True)
    try:
        code = resumed.wait()
    finally:
        if resumed.poll() is None:
            stop_owned_child(resumed)
    if code:
        raise RuntimeError(f"Resume exited {code}; checkpoints and shared ledger were preserved.")
    final_summary = read_json(args.out / "run_summary.json")
    if read_json(args.out / "run_manifest.json") != initial_manifest:
        raise RuntimeError("Run identity changed across interruption/resume.")
    calls = [json.loads(line) for line in (args.out / "calls.jsonl").read_text().splitlines() if line.strip()]
    result = assert_recovery(before, progress_snapshot(args.db), calls, held,
                             ledger_snapshot(ledger, initial_summary["run_id"]))
    result.update(execution_status=final_summary.get("execution_status"), input_count=count,
                  api_cost_complete=final_summary.get("api_cost_complete"))
    result["passed"] = result["passed"] and final_summary.get("execution_status") == "completed" and result["completed_after"] == count
    write_json(evidence / "recovery_validation.json", result)
    print(json.dumps(result, indent=2), flush=True)
    print(f"Actual interruption and recovery evidence: {evidence}", flush=True)
    if held:
        print("The interrupted request's possible charge remains reserved. Recovery success does not resolve that billing uncertainty.", flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Recovery demonstration stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
