"""Synthetic process tests: actual SIGINT and SQLite, never provider calls."""
from __future__ import annotations

import argparse
import importlib.util
import json
import signal
import sqlite3
import sys
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("recovery_demo", Path(__file__).parents[1] / "tools/recovery_demo.py")
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


def test_paid_gate_does_not_spawn_or_create_paths(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("No child should be started without explicit paid opt-in")
    monkeypatch.setattr(demo.subprocess, "Popen", unexpected)
    assert demo.main(["--config", str(tmp_path / "missing.json"), "--out", str(tmp_path / "run")]) == 2
    assert not (tmp_path / "run").exists()


def test_identity_fields_match_initial_and_resume():
    args = argparse.Namespace(config=Path("config/nebius-pilot.json"), input=Path("data/learning_1000.csv"),
                              out=Path("runs/recovery"), db=Path("data/recovery.sqlite3"), budget=1.5,
                              global_budget=1.5, verify_count=1000, rates=Path("config/rates.csv"))
    initial, resumed = demo.build_command(args, "initial"), demo.build_command(args, "resume")
    assert initial[:-1] == resumed[:-1]
    assert initial[-2:] == ["--phase", "initial"]
    assert resumed[-2:] == ["--phase", "resume"]
    assert "--stop-after" not in initial
    assert initial[initial.index("--verify-count") + 1] == "1000"
    assert initial[initial.index("--cache-mode") + 1] == "cold"


def test_real_signal_preserves_committed_rows_and_unknown_hold(tmp_path):
    """A local synthetic process actually receives SIGINT after its DB commit."""
    child_script = tmp_path / "synthetic_child.py"
    db = tmp_path / "synthetic.sqlite3"
    marker = tmp_path / "signal.json"
    child_script.write_text(
        """import json, signal, sqlite3, sys, time
from pathlib import Path
db, marker = sys.argv[1:]
conn = sqlite3.connect(db)
conn.executescript('''
CREATE TABLE records(record_json TEXT);
CREATE TABLE calls(value_json TEXT);
CREATE TABLE spend(request_id TEXT,run_id TEXT,reserved_nano INTEGER,charged_nano INTEGER,state TEXT);
''')
def interrupted(signum, frame):
    conn.execute("UPDATE spend SET state='unknown' WHERE state='reserved'")
    conn.commit()
    Path(marker).write_text(json.dumps({"received_signal": signum, "synthetic": True}))
    conn.close()
    raise SystemExit(130)
signal.signal(signal.SIGINT, interrupted)
for index in range(50):
    conn.execute("INSERT INTO records VALUES(?)", (json.dumps({"review_id": "synthetic-"+str(index), "status":"completed", "synthetic":True}),))
conn.execute("INSERT INTO spend VALUES('synthetic-inflight','synthetic-run',1000000,NULL,'reserved')")
conn.commit()
while True:
    time.sleep(.05)
""",
        encoding="utf-8")
    event = demo.interrupt_at_checkpoint(
        [sys.executable, str(child_script), str(db), str(marker)], db, 50,
        cwd=tmp_path, timeout=10, poll_seconds=.01, shutdown_timeout=5)
    assert event["signal"] == "SIGINT"
    assert event["exit_code"] == 130
    assert len(event["observed_completed_ids"]) == 50
    assert json.loads(marker.read_text())["received_signal"] == signal.SIGINT
    assert len(demo.progress_snapshot(db)["completed_ids"]) == 50
    assert demo.ledger_snapshot(db, "synthetic-run") == [
        {"request_id": "synthetic-inflight", "reserved_nano": 1000000,
         "charged_nano": None, "state": "unknown"}]


def test_recovery_audit_detects_lost_rows_rebilling_and_released_holds():
    hold = {"request_id": "r", "reserved_nano": 5, "charged_nano": None, "state": "unknown"}
    before = {"completed_ids": ["a", "b"]}
    after = {"completed_ids": ["a", "b", "c"]}
    calls = [{"phase": "resume", "purpose": "initial_classification", "review_ids": ["c"]},
             {"phase": "resume", "purpose": "independent_verification", "review_ids": ["a"]}]
    assert demo.assert_recovery(before, after, calls, [hold], [hold])["passed"]
    bad = demo.assert_recovery(before, {"completed_ids": ["a"]},
                               [{"phase": "resume", "purpose": "initial_classification", "review_ids": ["a"]}],
                               [hold], [{**hold, "charged_nano": 0, "state": "settled"}])
    assert not bad["passed"]
    assert bad["lost_completed_ids"] == ["b"]
    assert bad["reclassified_completed_ids"] == ["a"]
    assert bad["changed_uncertain_reservations"] == ["r"]


def test_progress_poll_never_creates_database(tmp_path):
    absent = tmp_path / "absent.sqlite3"
    assert demo.progress_snapshot(absent) == {"completed_ids": [], "call_count": 0}
    assert not absent.exists()
