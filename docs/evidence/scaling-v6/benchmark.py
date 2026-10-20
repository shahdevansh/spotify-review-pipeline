"""Offline synthetic persistence benchmark. Never instantiates a provider/Engine.

Every DB lives under a fresh /private/tmp directory, never the shared ledger.
Each benchmark step has a hard 55-second timeout; results are saved after steps.
"""
import gc
import hashlib
import json
import platform
import signal
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent / "benchmark-rerun-results.json"
sys.path.insert(0, str(ROOT / "src"))
from spotify_pipeline.storage import ResultStore, BudgetLedger, atomic_jsonl, canonical

TEMP = Path(tempfile.mkdtemp(prefix="spotify-synthetic-scaling-v6-", dir="/private/tmp"))
RESULTS = {"synthetic": True, "business_evidence": False, "provider_calls": 0,
           "api_cost_usd": 0, "scratch_dir": str(TEMP), "python": sys.version,
           "platform": platform.platform(), "filesystem": "/private/tmp (local temporary filesystem)",
           "production_files_modified": False, "storage_source_sha256":
           hashlib.sha256((ROOT / "src/spotify_pipeline/storage.py").read_bytes()).hexdigest(),
           "steps": []}


def save(value):
    RESULTS["steps"].append(value)
    OUT.write_text(json.dumps(RESULTS, indent=2) + "\n")
    print(json.dumps(value), flush=True)


def deadline(_signal, _frame):
    raise TimeoutError("55 second offline step limit")


signal.signal(signal.SIGALRM, deadline)


def fixture_call(index):
    ids = [f"synthetic-review-{index:05d}-{item:02d}" for item in range(10)]
    return dict(request_id=f"synthetic-request-{index:05d}", run_id="synthetic-run", role="enrich",
                purpose="initial_classification", provider="synthetic-no-provider", model="synthetic-model",
                label_config="synthetic-config", phase="initial", outcome="succeeded", synthetic=True,
                review_ids=ids, review_id_mapping={f"r{i}": value for i, value in enumerate(ids)},
                model_input_ids=[f"r{i}" for i in range(10)], started_at="2026-10-20T00:00:00+00:00",
                workers=1, attempt=1, reasoning_effort="none", reserved_usd=.001,
                input_tokens=2000, output_tokens=700, cost_usd=0,
                billing_items=[{"rate_key": "synthetic_input", "units": 2000},
                               {"rate_key": "synthetic_output", "units": 700}],
                normalized_usage={"input_tokens": 2000, "output_tokens": 700,
                                  "cached_input_tokens": None, "reasoning_tokens": None},
                usage_source="synthetic_fixture", duration_seconds=0, api_duration_seconds=0,
                unknown_charge_hold_usd=0, dispatch_status="synthetic_not_dispatched",
                schema_version="synthetic-schema", prompt_version="synthetic-prompt", error=None)


def benchmark_calls(n):
    folder = TEMP / f"calls-{n}"
    folder.mkdir()
    store = ResultStore(folder / "calls.sqlite3")
    journal = folder / "append.jsonl"
    started = time.perf_counter()
    total_bytes = 0
    final_latencies = []
    for index in range(n):
        call = fixture_call(index)
        one = time.perf_counter()
        store.save_call({**call, "outcome": "failed", "error": "synthetic_queued"})
        store.save_call(call)
        text = canonical(call) + "\n"
        with journal.open("a") as handle:
            handle.write(text)
        total_bytes += len(text.encode())
        if index >= n - 100:
            final_latencies.append(time.perf_counter() - one)
    write_seconds = time.perf_counter() - started
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    parsed = store.calls("synthetic-run")
    read_seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    started = time.perf_counter()
    atomic_jsonl(folder / "snapshot.jsonl", parsed)
    export_seconds = time.perf_counter() - started
    assert len(parsed) == n and (folder / "snapshot.jsonl").read_bytes() == journal.read_bytes()
    store.close()
    return dict(kind="call_journal_and_snapshot", n=n, final_call_mean_bytes=total_bytes / n,
                write_seconds=write_seconds, persisted_calls_per_second=n / write_seconds,
                last100_mean_seconds=statistics.mean(final_latencies),
                list_parse_seconds_with_tracemalloc=read_seconds, list_parse_peak_bytes=peak,
                atomic_export_seconds=export_seconds, append_bytes=journal.stat().st_size,
                snapshot_bytes=(folder / "snapshot.jsonl").stat().st_size,
                database_bytes=(folder / "calls.sqlite3").stat().st_size)


def benchmark_ledger(n):
    folder = TEMP / f"ledger-{n}"
    folder.mkdir()
    ledger = BudgetLedger(folder / "synthetic-spend.sqlite3")
    started = time.perf_counter()
    tail = []
    for index in range(n):
        one = time.perf_counter()
        ledger.reserve(f"synthetic-{index}", "synthetic-run", .001,
                       global_cap_usd=1000000, run_cap_usd=1000000)
        ledger.settle(f"synthetic-{index}", .0001)
        if index >= n - 100:
            tail.append(time.perf_counter() - one)
    elapsed = time.perf_counter() - started
    plans = {"global": [list(row) for row in ledger.conn.execute(
        "EXPLAIN QUERY PLAN SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend")],
        "run": [list(row) for row in ledger.conn.execute(
        "EXPLAIN QUERY PLAN SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend WHERE run_id='synthetic-run'")]}
    assert ledger.totals()["attempts"] == n
    ledger.close()
    return dict(kind="ledger_reserve_and_settle", n=n, elapsed_seconds=elapsed,
                last100_mean_seconds=statistics.mean(tail), admissions_per_second=n / elapsed,
                aggregate_row_visits_estimate=n * (n - 1), explain_query_plan=plans,
                database_bytes=(folder / "synthetic-spend.sqlite3").stat().st_size,
                amounts_are_synthetic=True, real_cost_usd=0)


def benchmark_materialize(n):
    folder = TEMP / f"records-{n}"
    folder.mkdir()
    store = ResultStore(folder / "records.sqlite3")
    rows = []
    started = time.perf_counter()
    for index in range(n):
        text = f"Synthetic review {index}: a Spotify playback feature does not work."
        digest = hashlib.sha256(text.encode()).hexdigest()
        value = dict(topic="playback", intent="complaint", sentiment=-.5, severity=3,
                     entities=["Spotify"], evidence_quote=text, needs_review=False,
                     review_audit={"version": "synthetic", "labels_modified": False},
                     review_reasons=[], raw_needs_review=False)
        record = dict(review_id=f"synthetic-review-{index:06d}", review_text=text, review_rating="",
                      review_likes="", app_version="SYNTHETIC", review_timestamp="", source_sha256="0"*64,
                      label_config="synthetic-config", status="completed", **value)
        store.save_record("synthetic-config", digest, record, cache_value=value)
        rows.append((digest, record))
    initial_seconds = time.perf_counter() - started
    started = time.perf_counter()
    for digest, record in rows:
        assert store.cached("synthetic-config", digest)
        store.save_record("synthetic-config", digest, record)
    materialize_seconds = time.perf_counter() - started
    started = time.perf_counter()
    atomic_jsonl(folder / "records.jsonl", [record for _, record in rows])
    export_seconds = time.perf_counter() - started
    store.close()
    return dict(kind="record_save_then_materialize_rewrite", n=n,
                initial_save_seconds=initial_seconds, repeated_read_and_write_seconds=materialize_seconds,
                atomic_export_seconds=export_seconds, export_bytes=(folder / "records.jsonl").stat().st_size,
                database_bytes=(folder / "records.sqlite3").stat().st_size)


for kind, function in (("calls", benchmark_calls), ("ledger", benchmark_ledger), ("records", benchmark_materialize)):
    for n in (100, 1000, 10000):
        signal.alarm(55)
        try:
            save(function(n))
        except TimeoutError as exc:
            save({"kind": kind, "n": n, "timed_out": True, "limit_seconds": 55, "message": str(exc)})
        finally:
            signal.alarm(0)
RESULTS["finished"] = True
OUT.write_text(json.dumps(RESULTS, indent=2) + "\n")
print(f"Saved synthetic-only results: {OUT}", flush=True)
