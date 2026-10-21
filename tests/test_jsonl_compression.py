"""Lossless export/reload checks with synthetic data and no paid requests."""
import gzip

import pytest

from spotify_pipeline.engine import fingerprint
from spotify_pipeline.storage import atomic_jsonl, open_jsonl_bytes, read_jsonl, resolve_jsonl
from test_engine import config, engine, row
from test_cost import RATES, call, write_run
from spotify_pipeline.cost import calculate_cost
from spotify_pipeline.analysis import load_records


def test_jsonl_gzip_preserves_exact_decoded_bytes_and_labels(tmp_path):
    path = tmp_path / "records.jsonl"
    values = [{"review_id": "a", "review_text": "\nCafé 🎵 音楽\t", "severity": 4,
               "usage": {"input_tokens": 123, "cached_tokens": 10}, "optional": None}]
    atomic_jsonl(path, values)
    original = path.read_bytes()
    compressed = path.with_name(path.name + ".gz")
    atomic_jsonl(compressed, values)
    assert not path.exists()
    assert gzip.decompress(compressed.read_bytes()) == original
    assert list(read_jsonl(path)) == values
    assert resolve_jsonl(path) == compressed
    with open_jsonl_bytes(path) as handle:
        assert handle.read() == original
    atomic_jsonl(path, values)
    assert not compressed.exists()
    assert path.read_bytes() == original


def test_failed_compression_keeps_previous_complete_export(tmp_path):
    path = tmp_path / "records.jsonl"
    atomic_jsonl(path, [{"old": True}])
    def failing_rows():
        yield {"partial": True}
        raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        atomic_jsonl(path.with_name(path.name + ".gz"), failing_rows())
    assert list(read_jsonl(path)) == [{"old": True}]
    assert not list(tmp_path.glob("*.tmp"))


def test_malformed_gzip_reports_original_line_number(tmp_path):
    path = tmp_path / "bad.jsonl.gz"
    with gzip.open(path, "wt") as handle:
        handle.write('{}\n\nwrong\n')
    with pytest.raises(ValueError, match="bad.jsonl.gz line 3"):
        list(read_jsonl(path))


def test_offline_cost_report_replays_compressed_artifacts_identically(tmp_path):
    calls = [call("synthetic-compressed", "enrich", ["a"])]
    records = [{"review_id": "a", "review_text": "é", "status": "completed"}]
    path = write_run(tmp_path, calls, {"input_count": 1, "completed": 1, "wall_seconds": 2}, records)
    original = calculate_cost(path, RATES)
    atomic_jsonl(path.with_name(path.name + ".gz"), calls)
    atomic_jsonl(tmp_path / "records.jsonl.gz", records)
    output = tmp_path / "cost"
    compressed = calculate_cost(path, RATES, output)
    replay = calculate_cost(output / "pilot_calls.jsonl", output / "rates.csv")
    assert compressed["measurements"] == original["measurements"] == replay["measurements"]
    assert compressed["projections"] == original["projections"] == replay["projections"]
    assert (output / "pilot_calls.jsonl.gz").exists()
    assert (output / "pilot_records.jsonl.gz").exists()
    assert not (output / "pilot_calls.jsonl").exists()
    assert load_records(tmp_path / "records.jsonl") == records


@pytest.mark.asyncio
async def test_engine_gzip_exports_keep_usage_and_fingerprint(tmp_path, config):
    original_fingerprint = fingerprint(config)
    config["gzip_exports"] = True
    assert fingerprint(config) == original_fingerprint
    run = engine(tmp_path, config)
    try:
        rows = [row(1), row(2)]
        records = await run.enrich(rows)
        verification = await run.verify(rows, records, 2)
        assert list(read_jsonl(run.run_dir / "records.jsonl")) == records
        assert list(read_jsonl(run.run_dir / "calls.jsonl")) == run.store.calls(run.run_id)
        assert list(read_jsonl(run.run_dir / "verification.jsonl")) == verification
        for name in ("records", "calls", "evidence_calls", "verification", "disagreements"):
            assert (run.run_dir / f"{name}.jsonl.gz").is_file()
            assert not (run.run_dir / f"{name}.jsonl").exists()
        calls_before = list(read_jsonl(run.run_dir / "calls.jsonl"))
        run.config["gzip_exports"] = False
        run.finish()
        assert list(read_jsonl(run.run_dir / "calls.jsonl")) == calls_before
        assert not (run.run_dir / "calls.jsonl.gz").exists()
    finally:
        await run.close()
