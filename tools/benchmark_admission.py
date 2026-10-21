#!/usr/bin/env python3
"""Read-only source snapshot, money-preserving migration, private SQL benchmark.

No API calls and no writes to the source ledger. Synthetic scale rows exist only
in the automatically deleted temporary copy, never in the project ledger.
"""
import argparse
import hashlib
import json
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

from spotify_pipeline.storage import BudgetLedger, atomic_json, utcnow


GLOBAL = "SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend"
RUN = GLOBAL + " WHERE run_id=?"
OLD_PROVIDER = """SELECT COALESCE(SUM(COALESCE(s.charged_nano,s.reserved_nano)),0)
FROM spend s LEFT JOIN spend_provider p ON s.request_id=p.request_id
WHERE p.provider=? OR p.provider IS NULL"""
NEW_PROVIDER = """SELECT
(SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend WHERE admission_provider=?) +
(SELECT COALESCE(SUM(COALESCE(charged_nano,reserved_nano)),0) FROM spend WHERE admission_provider IS NULL)"""


def digest(c, table):
    columns = "request_id,run_id,reserved_nano,charged_nano,state,created_at,settled_at" if table == "spend" else "request_id,provider"
    h = hashlib.sha256(); count = 0
    for row in c.execute(f"SELECT {columns} FROM {table} ORDER BY request_id"):
        h.update(json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
        count += 1
    return {"rows": count, "sha256_original_columns": h.hexdigest()}


def benchmark(c, run_id, provider, *, optimized):
    output = {}
    for name, sql, parameters in (("global", GLOBAL, ()), ("run", RUN, (run_id,)),
                                  ("provider", NEW_PROVIDER if optimized else OLD_PROVIDER, (provider,))):
        durations = []
        for _ in range(12):
            start = time.perf_counter(); value = c.execute(sql, parameters).fetchone()[0]
            durations.append(time.perf_counter() - start)
        output[name] = {"commitment_nano_usd": value, "mean_seconds": statistics.mean(durations),
                        "minimum_seconds": min(durations), "repetitions": len(durations),
                        "query_plan": [tuple(row) for row in c.execute("EXPLAIN QUERY PLAN " + sql, parameters)]}
    output["combined_mean_seconds"] = sum(v["mean_seconds"] for v in output.values())
    return output


def run(source, destination, synthetic_count=150000):
    with tempfile.TemporaryDirectory(prefix="spotify-admission-benchmark-") as directory:
        copy_path = Path(directory) / "private-copy.sqlite3"
        reader = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
        copied = sqlite3.connect(copy_path); reader.backup(copied); reader.close()
        before = {table: digest(copied, table) for table in ("spend", "spend_provider")}
        run_id = copied.execute("SELECT run_id FROM spend GROUP BY run_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
        provider = copied.execute("SELECT provider FROM spend_provider GROUP BY provider ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
        old_benchmark = benchmark(copied, run_id, provider, optimized=False); copied.close()
        start = time.perf_counter(); ledger = BudgetLedger(copy_path); migration_seconds = time.perf_counter() - start
        after = {table: digest(ledger.conn, table) for table in ("spend", "spend_provider")}
        if before != after:
            raise RuntimeError("Migration altered original ledger columns or provider tags")
        optimized = benchmark(ledger.conn, run_id, provider, optimized=True)
        for name in ("global", "run", "provider"):
            if old_benchmark[name]["commitment_nano_usd"] != optimized[name]["commitment_nano_usd"]:
                raise RuntimeError("Migration changed an admission total")
        report = {"created_at": utcnow(), "source_ledger": str(source), "source_access": "read-only SQLite backup",
                  "temporary_copy_deleted_after_test": True, "money_or_api_calls_created_in_source": False,
                  "migration_seconds": migration_seconds, "original_ledger_digests": before,
                  "post_migration_digests": after, "original_columns_identical": True,
                  "admission_totals_identical": True, "baseline": old_benchmark, "optimized": optimized}
        missing = max(0, synthetic_count - before["spend"]["rows"])
        with ledger.conn:
            ledger.conn.execute("BEGIN IMMEDIATE")
            ledger.conn.executemany("""INSERT INTO spend
              (request_id,run_id,reserved_nano,charged_nano,state,created_at,settled_at)
              VALUES(?,?,1,1,'settled','synthetic-benchmark','synthetic-benchmark')""",
              ((f"synthetic-performance-{i}", run_id) for i in range(missing)))
            ledger.conn.executemany("INSERT INTO spend_provider VALUES(?,?)",
              ((f"synthetic-performance-{i}", provider) for i in range(missing)))
        report["synthetic_scale"] = {"ledger_rows": before["spend"]["rows"] + missing,
                                     "added_synthetic_rows": missing,
                                     "benchmark": benchmark(ledger.conn, run_id, provider, optimized=True)}
        report["private_copy_integrity"] = ledger.conn.execute("PRAGMA integrity_check").fetchone()[0]
        ledger.close(); atomic_json(destination, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.source, args.out)
    print(json.dumps({"report": str(args.out), "original_rows": result["original_ledger_digests"]["spend"]["rows"],
                      "baseline_ms": result["baseline"]["combined_mean_seconds"] * 1000,
                      "optimized_ms": result["optimized"]["combined_mean_seconds"] * 1000,
                      "scale_150k_ms": result["synthetic_scale"]["benchmark"]["combined_mean_seconds"] * 1000,
                      "original_columns_identical": result["original_columns_identical"],
                      "admission_totals_identical": result["admission_totals_identical"]}))
