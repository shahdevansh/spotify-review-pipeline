"""Lossless storage and offline migration checks; no provider calls."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from spotify_pipeline.storage import (
    COMPRESSED_JSON_PREFIX, ResultStore, canonical, compress_json_text,
    decode_stored_json, encode_stored_json, stored_json_text,
)


def _migration():
    path = Path(__file__).resolve().parents[1] / "tools/compact_result_payloads.py"
    spec = importlib.util.spec_from_file_location("compact_result_payloads", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compact_database


def _call(request_id="request-1"):
    return {"request_id": request_id, "run_id": "run-1", "text": "🎵 Café 東京 e\u0301\nline two",
            "usage": {"input_tokens": 123456, "output_tokens": 789, "cached_tokens": 0},
            "cost_usd": 0.000123456, "response": {"valid": True, "missing": None}}


def test_new_and_legacy_codec_preserve_unicode_and_usage():
    original = _call()
    old = json.dumps(original, ensure_ascii=False, indent=2)
    encoded = encode_stored_json(original)
    assert encoded.startswith(COMPRESSED_JSON_PREFIX)
    assert decode_stored_json(encoded) == decode_stored_json(old) == original
    assert stored_json_text(compress_json_text(old)).encode("utf-8") == old.encode("utf-8")
    assert decode_stored_json(memoryview(encoded)) == original


def test_corrupt_compressed_payload_fails_visibly():
    with pytest.raises(Exception):
        decode_stored_json(COMPRESSED_JSON_PREFIX + b"broken")


def test_store_reads_mixed_formats_and_record_sql(tmp_path):
    store = ResultStore(tmp_path / "results.sqlite3")
    first = _call()
    second = _call("request-2")
    store.conn.execute("INSERT INTO calls VALUES(?,?,?)", (first["request_id"], first["run_id"], canonical(first)))
    store.save_call(second)
    assert store.calls() == [first, second]
    assert store.calls("run-1") == [first, second]
    record = {"review_id": "review-1", "source_sha256": "source", "status": "completed", "topic": "other"}
    cached = {"usage": first["usage"], "quote": first["text"], "topic": "other"}
    store.save_record("config", "text", record, cache_value=cached)
    store.conn.execute("INSERT INTO text_cache VALUES(?,?,?,?)", ("old", "text", "old-id", canonical(cached)))
    assert store.cached("config", "text") == {"origin_id": "review-1", "value": cached}
    assert store.cached("old", "text") == {"origin_id": "old-id", "value": cached}
    assert store.record("config", "review-1") == record
    assert store.conn.execute("SELECT typeof(record_json) FROM records").fetchone()[0] == "blob"
    before_changes = store.conn.total_changes
    store.save_record("config", "text", record)
    assert store.conn.total_changes == before_changes
    assert store.conn.execute("SELECT json_extract(stored_json_text(record_json),'$.topic') FROM records").fetchone()[0] == "other"
    store.save_task("task", "verify", cached, "request-2")
    assert store.conn.execute("SELECT typeof(value_json) FROM task_cache").fetchone()[0] == "text"
    store.close()


def test_offline_migration_preserves_bytes_counts_and_untargeted_tables(tmp_path):
    path = tmp_path / "results.sqlite3"
    store = ResultStore(path)
    old_strings = []
    for i in range(7):
        value = _call(f"request-{i}")
        value["text"] *= 100
        serialized = json.dumps(value, ensure_ascii=False, indent=2)
        old_strings.append(serialized)
        store.conn.execute("INSERT INTO calls VALUES(?,?,?)", (value["request_id"], "run-1", serialized))
        store.conn.execute("INSERT INTO text_cache VALUES(?,?,?,?)", ("config", str(i), str(i), serialized))
    record = {"review_id": "review", "source_sha256": "sha", "status": "completed", "topic": "other"}
    store.conn.execute("INSERT INTO records VALUES(?,?,?,?,?)", ("config", "review", "sha", "text", canonical(record)))
    store.save_task("task", "verify", {"score": 1}, "request-1")
    untouched = {table: [tuple(row) for row in store.conn.execute(f"SELECT * FROM {table}")]
                 for table in ("task_cache",)}
    store.close()
    migrate = _migration()
    report = migrate(path, batch_size=2, report_path=tmp_path / "report.json")
    assert report["status"] == "completed"
    assert report["integrity_check"] == "ok"
    assert report["vacuum_performed"] is False
    assert report["wal_checkpoints_completed"] == 11  # 9 data batches + initial/final
    assert report["max_observed_wal_bytes_after_checkpoint"] == 0
    assert report["max_observed_wal_bytes_before_checkpoint"] < 1_000_000
    conn = sqlite3.connect(path)
    for table in ("calls", "text_cache"):
        rows = conn.execute(f"SELECT value_json FROM {table} ORDER BY rowid").fetchall()
        assert [stored_json_text(row[0]) for row in rows] == old_strings
        assert all(isinstance(row[0], bytes) for row in rows)
        assert report["tables"][table]["rows_compressed"] == 7
        assert report["tables"][table]["compressed_bytes"] < report["tables"][table]["uncompressed_bytes"]
    assert stored_json_text(conn.execute("SELECT record_json FROM records").fetchone()[0]) == canonical(record)
    assert report["tables"]["records"]["rows_compressed"] == 1
    for table, expected in untouched.items():
        assert conn.execute(f"SELECT * FROM {table}").fetchall() == expected
    conn.close()
    second = migrate(path, batch_size=2)
    assert all(table["rows_compressed"] == 0 for table in second["tables"].values())


def test_migration_refuses_spend_ledger(tmp_path):
    path = tmp_path / "spend.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE spend(request_id TEXT)")
    conn.close()
    with pytest.raises(ValueError, match="never a spending ledger"):
        _migration()(path)
