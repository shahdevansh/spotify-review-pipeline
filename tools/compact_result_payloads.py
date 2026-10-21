#!/usr/bin/env python3
"""Losslessly compact opaque result payloads at an offline checkpoint.

Stop every process using this result database first. This tool takes an exclusive
SQLite lock, compresses records.record_json, calls.value_json, and
text_cache.value_json, and
verifies each stored payload byte-for-byte before committing a bounded batch.
It does not alter decoded records, task caches, the spending ledger, or model outputs.
The WAL is explicitly checkpointed and truncated after every committed batch.
No VACUUM is performed: freed pages are reused by subsequent hero checkpoints.
Restart only code with the compatible storage decoder after migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from spotify_pipeline.storage import compress_json_text, stored_json_text


TABLES = {"calls": "value_json", "text_cache": "value_json", "records": "record_json"}


def _write_report(path: Path | None, report: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def _query(conn: sqlite3.Connection, sql: str, parameters=()) -> list:
    """Exhaust and close every read cursor before checkpointing the WAL."""
    cursor = conn.execute(sql, parameters)
    try:
        return cursor.fetchall()
    finally:
        cursor.close()


def _checkpoint(conn: sqlite3.Connection, database: Path, report: dict) -> None:
    if conn.in_transaction:
        raise RuntimeError("Cannot checkpoint an active migration transaction")
    wal = database.with_name(database.name + "-wal")
    before = wal.stat().st_size if wal.exists() else 0
    report["max_observed_wal_bytes_before_checkpoint"] = max(
        report.get("max_observed_wal_bytes_before_checkpoint", 0), before)
    result = _query(conn, "PRAGMA wal_checkpoint(TRUNCATE)")[0]
    if result[0] != 0:
        raise RuntimeError(f"WAL checkpoint blocked by a database reader: {result}")
    after = wal.stat().st_size if wal.exists() else 0
    if after:
        raise RuntimeError(f"WAL checkpoint reported success but retained {after} bytes")
    report["wal_checkpoint"] = list(result)
    report["wal_checkpoints_completed"] = report.get("wal_checkpoints_completed", 0) + 1
    report["max_observed_wal_bytes_after_checkpoint"] = max(
        report.get("max_observed_wal_bytes_after_checkpoint", 0), after)


def compact_database(database: Path, *, batch_size: int = 100,
                     report_path: Path | None = None) -> dict:
    """Caller must have stopped database users; an exclusive lock enforces it."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if not database.is_file():
        raise FileNotFoundError(database)
    conn = sqlite3.connect(database, timeout=1, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=1000").close()
    conn.execute("PRAGMA synchronous=FULL").close()
    conn.execute("PRAGMA locking_mode=EXCLUSIVE").close()
    report = {"database": str(database.resolve()), "codec": "SPJZ1+zlib6",
              "started_at": datetime.now(timezone.utc).isoformat(),
              "status": "running", "vacuum_performed": False,
              "batch_size": batch_size, "tables": {},
              "physical_file_shrink_expected": False,
              "note": "Freed SQLite pages are retained for reuse; only payload bytes change."}
    try:
        # The exclusive locking mode retains the lock between bounded commits.
        conn.execute("BEGIN EXCLUSIVE").close()
        present = {row[0] for row in _query(conn, "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"records", *TABLES}.issubset(present) or "spend" in present:
            raise ValueError("Expected a results database, never a spending ledger")
        report["page_count_before"] = _query(conn, "PRAGMA page_count")[0][0]
        report["freelist_count_before"] = _query(conn, "PRAGMA freelist_count")[0][0]
        report["page_size"] = _query(conn, "PRAGMA page_size")[0][0]
        conn.commit()
        _checkpoint(conn, database, report)
        for table, column in TABLES.items():
            total = _query(conn, f"SELECT COUNT(*) FROM {table}")[0][0]
            stats = {"rows_total": total, "rows_compressed": 0,
                     "uncompressed_bytes": 0, "compressed_bytes": 0,
                     "verified_exact_utf8_bytes": True}
            report["tables"][table] = stats
            digest = hashlib.sha256()
            last_rowid = -1
            while True:
                conn.execute("BEGIN EXCLUSIVE").close()
                rows = _query(conn,
                    f"SELECT rowid,{column} FROM {table} "
                    f"WHERE rowid>? AND typeof({column})='text' ORDER BY rowid LIMIT ?",
                    (last_rowid, batch_size))
                if not rows:
                    conn.commit()
                    break
                packed = []
                for rowid, original in rows:
                    # Preserve formatting, Unicode, and numeric representations
                    # exactly: do not deserialize/re-serialize during migration.
                    blob = compress_json_text(original)
                    if stored_json_text(blob) != original:
                        raise ValueError(f"Codec verification failed: {table} row {rowid}")
                    packed.append((blob, rowid, original))
                conn.executemany(f"UPDATE {table} SET {column}=? WHERE rowid=?",
                                 [(blob, rowid) for blob, rowid, _ in packed]).close()
                for blob, rowid, original in packed:
                    saved = _query(conn, f"SELECT {column} FROM {table} WHERE rowid=?", (rowid,))[0][0]
                    raw = original.encode("utf-8")
                    if not isinstance(saved, bytes) or stored_json_text(saved).encode("utf-8") != raw:
                        raise ValueError(f"Read-back verification failed: {table} row {rowid}")
                    digest.update(str(rowid).encode() + b"\0" + str(len(raw)).encode() + b"\0" + raw)
                    stats["uncompressed_bytes"] += len(raw)
                    stats["compressed_bytes"] += len(blob)
                    stats["rows_compressed"] += 1
                conn.commit()
                _checkpoint(conn, database, report)
                last_rowid = rows[-1][0]
                stats["migrated_payloads_sha256"] = digest.hexdigest()
                _write_report(report_path, report)
            if _query(conn, f"SELECT COUNT(*) FROM {table}")[0][0] != total:
                raise ValueError(f"Record count changed: {table}")
            stats["remaining_plain_rows"] = _query(conn,
                f"SELECT COUNT(*) FROM {table} WHERE typeof({column})='text'")[0][0]
        report["page_count_after"] = _query(conn, "PRAGMA page_count")[0][0]
        report["freelist_count_after"] = _query(conn, "PRAGMA freelist_count")[0][0]
        # With exclusive ownership this checkpoints the small WAL, not a copy
        # of the database. Keep the full original database file in place.
        _checkpoint(conn, database, report)
        report["integrity_check"] = _query(conn, "PRAGMA quick_check")[0][0]
        if report["integrity_check"] != "ok":
            raise ValueError("SQLite quick_check failed")
        report["status"] = "completed"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report_path, report)
        return report
    except BaseException as exc:
        if conn.in_transaction:
            conn.rollback()
        report["status"] = "interrupted_or_failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        _write_report(report_path, report)
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--database-stopped", action="store_true",
                        help="Confirm all harness and monitor connections to this result DB are stopped")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.database_stopped:
        parser.error("Stop every database user and explicitly pass --database-stopped")
    report = compact_database(args.database, batch_size=args.batch_size, report_path=args.report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
