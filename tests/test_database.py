"""Synthetic importer fixtures; no provider calls and no production output."""
import csv
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from spotify_pipeline.data import row_sha
from spotify_pipeline.database import RunBundle, _profile, import_run, load_run, validate_bundle


def synthetic_record(review_id="synthetic-1", text="Playback stopped."):
    record = {
        "review_id": review_id,
        "review_text": text,
        "review_rating": "1",
        "review_likes": "0",
        "app_version": "",
        "review_timestamp": "2026-01-01 00:00:00",
        "status": "completed",
        "topic": "playback",
        "intent": "complaint",
        "severity": 4,
        "sentiment": -0.8,
        "entities": [],
        "evidence_quote": text,
        "needs_review": False,
        "label_config": "synthetic-configuration",
        "cache_source_id": None,
    }
    record["source_sha256"] = row_sha(record)
    return record


def synthetic_bundle():
    return RunBundle(
        run_id="synthetic-run",
        summary={"run_id": "synthetic-run", "input_count": 1, "completed": 1, "quarantined": 0},
        records=[synthetic_record()],
        issues=[{
            "issue_id": "issue-playback", "name": "Playback", "description": "Synthetic fixture",
            "rank": 1, "complaint_count": 1, "severity_sum": 4,
            "mean_severity": Decimal("4.000000"), "priority_score": 4,
        }],
        membership=[{"review_id": "synthetic-1", "issue_id": "issue-playback"}],
        claims=[{"claim_id": "synthetic-claim", "issue_id": "issue-playback", "metric": "severity_sum", "value": "4"}],
        recommendations={
            "summary": "Synthetic fixture", "priority_issue_id": "issue-playback",
            "recommendations": [{
                "title": "Synthetic recommendation", "rationale": "Synthetic evidence",
                "issue_ids": ["issue-playback"], "claim_ids": ["synthetic-claim"],
                "review_ids": ["synthetic-1"],
            }],
            "alternatives": [], "limitations": ["Synthetic test data."],
        },
        source_profile=None,
        evaluation=None,
    )


def write_bundle(tmp_path, bundle):
    (tmp_path / "run_summary.json").write_text(json.dumps(bundle.summary))
    (tmp_path / "records.jsonl").write_text("\n".join(json.dumps(record) for record in bundle.records) + "\n")
    (tmp_path / "issues.json").write_text(json.dumps([
        {"issue_id": item["issue_id"], "title": item["name"], "description": item["description"]}
        for item in bundle.issues
    ]))
    for name, rows in (
        ("ranking.csv", [{k: v for k, v in row.items() if k not in ("name", "description")} for row in bundle.issues]),
        ("membership.csv", bundle.membership), ("claims.csv", bundle.claims),
    ):
        with (tmp_path / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (tmp_path / "recommendations.json").write_text(json.dumps(bundle.recommendations))


def test_saved_bundle_loads_without_database_or_provider(tmp_path):
    bundle = synthetic_bundle()
    write_bundle(tmp_path, bundle)
    loaded = load_run(tmp_path)
    assert loaded.run_id == "synthetic-run"
    assert loaded.records[0]["app_version"] == ""
    assert loaded.issues[0]["name"] == "Playback"
    assert loaded.issues[0]["mean_severity"] == Decimal("4.000000")


def test_full_source_profile_is_not_confused_with_selected_rows():
    assert _profile({
        "profile": {"counts": {"records": 100, "empty_review_text": 3}, "file_sha256": "abc"},
        "scope": {"selected_nonempty_records": 7},
    }) == {"total_rows": 100, "nonempty_rows": 97, "empty_rows": 3, "file_sha256": "abc"}
    assert _profile({"total_rows": 100})["nonempty_rows"] is None


@pytest.mark.parametrize("mutation,error", [
    (lambda b: b.summary.update(input_count=2), "input_count"),
    (lambda b: b.records.append(deepcopy(b.records[0])), "duplicate review"),
    (lambda b: b.records[0].update(review_rating="2"), "source hash mismatch"),
    (lambda b: b.issues[0].update(priority_score=99), "does not reproduce"),
    (lambda b: b.claims[0].update(value="99"), "Claim does not reproduce"),
    (lambda b: b.claims[0].update(issue_id="invented"), "unknown issue"),
    (lambda b: b.membership.clear(), "does not cover"),
    (lambda b: b.recommendations["recommendations"][0]["claim_ids"].append("invented"), "unknown claim_ids"),
])
def test_inconsistent_exports_cannot_be_published(mutation, error):
    bundle = synthetic_bundle()
    mutation(bundle)
    with pytest.raises(ValueError, match=error):
        validate_bundle(bundle)


def test_direct_cache_provenance_is_accepted_and_chains_rejected():
    bundle = synthetic_bundle()
    second = synthetic_record("synthetic-2")
    second["cache_source_id"] = "synthetic-1"
    bundle.records.append(second)
    bundle.summary.update(input_count=2, completed=2)
    bundle.membership.append({"review_id": "synthetic-2", "issue_id": "issue-playback"})
    bundle.issues[0].update(complaint_count=2, severity_sum=8, priority_score=8)
    bundle.claims[0]["value"] = "8"
    validate_bundle(bundle)
    second["needs_review"] = True
    with pytest.raises(ValueError, match="classification mismatch"):
        validate_bundle(bundle)
    second["needs_review"] = False
    third = synthetic_record("synthetic-3")
    third["cache_source_id"] = "synthetic-2"
    bundle.records.append(third)
    with pytest.raises(ValueError, match="directly"):
        validate_bundle(bundle)


def test_no_database_credentials_fails_before_connection(tmp_path, monkeypatch):
    write_bundle(tmp_path, synthetic_bundle())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="Set DATABASE_URL"):
        import_run(tmp_path)


def test_quarantined_rows_preserve_source_and_need_no_membership():
    bundle = synthetic_bundle()
    empty = synthetic_record("synthetic-empty", "")
    empty = {key: empty[key] for key in (
        "review_id", "review_text", "review_rating", "review_likes", "app_version",
        "review_timestamp", "source_sha256", "label_config",
    )}
    empty.update(status="quarantined", reason="empty_review_text")
    bundle.records.append(empty)
    bundle.summary.update(input_count=2, quarantined=1)
    validate_bundle(bundle)


def test_publication_preflight_requires_complete_independent_comparison(tmp_path):
    """The reconciliation tool stays offline and rejects a false accuracy claim."""
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    script = Path(__file__).resolve().parents[1] / "web/scripts/verify_publication.py"
    spec = importlib.util.spec_from_file_location("verify_publication", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_bundle(tmp_path, synthetic_bundle())
    ingestion = tmp_path / "ingestion.json"
    ingestion.write_text(json.dumps({"counts": {"records": 3, "empty_review_text": 0}}))
    evaluation = tmp_path / "verifier_report.json"
    evaluation.write_text(json.dumps({"verified_count": 1, "ground_truth": False}))
    args = SimpleNamespace(
        run=str(tmp_path), ingestion=str(ingestion), evaluation=str(evaluation),
        expected_count=1, live=False,
    )
    result = module.verify(args)
    assert result["status"] == "ready_for_authorized_import"
    assert result["mutations_performed"] is False
    evaluation.write_text(json.dumps({"verified_count": 1, "ground_truth": True}))
    with pytest.raises(AssertionError, match="human accuracy"):
        module.verify(args)


def test_real_postgres_import_reimport_rollback_and_pagination(tmp_path):
    """Opt-in integration test against an isolated local, synthetic-only database."""
    import os
    from urllib.parse import urlparse

    url = os.environ.get("SPOTIFY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SPOTIFY_TEST_DATABASE_URL to a local *_test database.")
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or not parsed.path.endswith("_test"):
        pytest.fail("Integration tests require a loopback-only database ending in _test.")

    psycopg = pytest.importorskip("psycopg")
    bundle = synthetic_bundle()
    bundle.run_id = "synthetic-database-integration"
    ids = [f"synthetic-{i:03d}" for i in range(53)] + [
        "synthetic-Z", "synthetic-a", "synthetic-Å", "synthetic-É",
    ]
    bundle.records = [
        synthetic_record(review_id, f"Synthetic playback complaint {i}: stopped.")
        for i, review_id in enumerate(ids)
    ]
    bundle.records[0].update(
        review_text='  Playback\tstopped.\n"Résumé" \\\\ 🎵  ',
        review_rating="01", review_likes="000", app_version="",
        review_timestamp=" 2026-01-01 00:00:00 ",
        confidence_source="not_reported",
        review_flag_interpretation="Uncalibrated model flag; no probability was reported.",
        initial_prediction={"topic": "playback", "severity": 2, "needs_review": True},
    )
    for i, record in enumerate(bundle.records):
        record["severity"] = i % 5 + 1
        record["evidence_quote"] = record["review_text"]
        record["source_sha256"] = row_sha(record)
    bundle.records[1].update(
        review_text=bundle.records[0]["review_text"],
        evidence_quote=bundle.records[0]["evidence_quote"],
        severity=bundle.records[0]["severity"],
        cache_source_id=bundle.records[0]["review_id"],
    )
    bundle.records[1]["source_sha256"] = row_sha(bundle.records[1])
    severity_sum = sum(record["severity"] for record in bundle.records)
    bundle.membership = [
        {"review_id": review_id, "issue_id": "issue-playback"} for review_id in ids
    ]
    bundle.issues[0].update(
        complaint_count=len(ids), severity_sum=severity_sum, priority_score=severity_sum,
        mean_severity=(Decimal(severity_sum) / len(ids)).quantize(Decimal("0.000001")),
    )
    bundle.claims[0]["value"] = str(severity_sum)
    bundle.recommendations["recommendations"][0]["review_ids"] = [ids[0]]
    empty = synthetic_record("synthetic-empty", "")
    empty = {key: empty[key] for key in (
        "review_id", "review_text", "review_rating", "review_likes", "app_version",
        "review_timestamp", "source_sha256", "label_config",
    )}
    empty.update(status="quarantined", reason="empty_review_text")
    bundle.records.append(empty)
    bundle.summary.update(
        run_id=bundle.run_id, input_count=len(ids) + 1,
        completed=len(ids), quarantined=1,
    )
    write_bundle(tmp_path, bundle)
    imported = import_run(tmp_path, url)
    assert imported["imported_rows"] == 58
    assert imported["storage_bytes"] > 0
    assert import_run(tmp_path, url)["imported_rows"] == 58

    with psycopg.connect(url, autocommit=True) as connection:
        from spotify_pipeline.database import SOURCE_FIELDS
        saved = connection.execute(
            f"SELECT {','.join(SOURCE_FIELDS)}, source_sha256, cache_source_id "
            "FROM spotify_reviews WHERE run_id = %s", (bundle.run_id,),
        ).fetchall()
        assert len(saved) == 58
        originals = {row["review_id"]: row for row in bundle.records}
        provenance = connection.execute(
            "SELECT provenance FROM spotify_reviews WHERE run_id=%s AND review_id=%s",
            (bundle.run_id, ids[0]),
        ).fetchone()[0]
        for field in ("confidence_source", "review_flag_interpretation", "initial_prediction"):
            assert provenance[field] == bundle.records[0][field]
        for row in saved:
            restored = dict(zip((*SOURCE_FIELDS, "source_sha256", "cache_source_id"), row))
            original = originals[restored["review_id"]]
            assert {key: restored[key] for key in SOURCE_FIELDS} == {
                key: original[key] for key in SOURCE_FIELDS
            }
            assert row_sha(restored) == restored["source_sha256"] == original["source_sha256"]
            assert restored["cache_source_id"] == original.get("cache_source_id")

        seen, cursor = [], None
        while True:
            page = connection.execute(
                """SELECT m.review_id FROM spotify_membership m
                   WHERE m.run_id = %s AND m.issue_id = %s
                     AND (%s::text IS NULL OR m.review_id COLLATE "C" > %s COLLATE "C")
                   ORDER BY m.review_id COLLATE "C" ASC LIMIT 50""",
                (bundle.run_id, "issue-playback", cursor, cursor),
            ).fetchall()
            if not page:
                break
            seen.extend(row[0] for row in page)
            cursor = page[-1][0]
        assert seen == sorted(ids, key=lambda value: value.encode("utf-8"))
        assert len(set(seen)) == 57
        assert connection.execute(
            "SELECT count(*) FROM spotify_runs WHERE is_current"
        ).fetchone()[0] == 1

        connection.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'spotify_reader')
              THEN CREATE ROLE spotify_reader LOGIN; END IF;
            END $$;
            GRANT USAGE ON SCHEMA public TO spotify_reader;
            GRANT SELECT ON ALL TABLES IN SCHEMA public TO spotify_reader;
        """)
        with psycopg.connect(url, autocommit=True) as reader:
            reader.execute("SET ROLE spotify_reader")
            assert reader.execute("SELECT count(*) FROM spotify_reviews").fetchone()[0] >= 58
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute("UPDATE spotify_runs SET is_current = false")

        # Fail after the old current flag is cleared and replacement rows inserted.
        # The transaction must restore the complete previous current run.
        connection.execute("""
            CREATE OR REPLACE FUNCTION synthetic_reject_import() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'synthetic importer rollback probe';
            END $$;
            CREATE TRIGGER synthetic_import_failure BEFORE INSERT ON spotify_claims
            FOR EACH ROW EXECUTE FUNCTION synthetic_reject_import();
        """)
        try:
            for run_id in (bundle.run_id, "synthetic-failed-replacement"):
                failed = deepcopy(bundle)
                failed.run_id = run_id
                failed.summary["run_id"] = run_id
                write_bundle(tmp_path, failed)
                with pytest.raises(psycopg.errors.RaiseException, match="rollback probe"):
                    import_run(tmp_path, url)
                assert connection.execute(
                    "SELECT run_id FROM spotify_runs WHERE is_current"
                ).fetchall() == [(bundle.run_id,)]
                assert connection.execute(
                    "SELECT count(*) FROM spotify_reviews WHERE run_id = %s",
                    (bundle.run_id,),
                ).fetchone()[0] == 58
                assert connection.execute(
                    "SELECT metric FROM spotify_claims WHERE run_id = %s", (bundle.run_id,),
                ).fetchone()[0] == "severity_sum"
            assert connection.execute(
                "SELECT count(*) FROM spotify_runs WHERE run_id = 'synthetic-failed-replacement'"
            ).fetchone()[0] == 0
        finally:
            connection.execute("DROP TRIGGER synthetic_import_failure ON spotify_claims")
            connection.execute("DROP FUNCTION synthetic_reject_import()")
