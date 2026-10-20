"""Offline audit reconciliation and isolated transaction tests; no human inputs."""
import json
import os
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError

from spotify_pipeline import evaluation_publication as publication

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SOURCE_FILES = (
    *(f"runs/pilot/1000/{name}" for name in (
        "records.jsonl", "run_summary.json", "configuration.json", "run_manifest.json",
        "verification.jsonl", "ranking.csv", "issues.json", "membership.csv", "claims.csv",
        "recommendations.json", "evals/verifier_report.json",
    )),
    "evals/pilot_inspection_report.json",
    "evals/synthetic-live/v5-live-001/safety_report.json",
    "validation/dashboard_evaluation_audit_v6.json",
    "evals/audit-v6/audit_summary.json",
    "web/database/evaluation_schema.sql",
)


def require_frozen_sources(root):
    missing = [relative for relative in FROZEN_SOURCE_FILES if not (root / relative).is_file()]
    if missing:
        pytest.skip(
            f"Frozen pilot evidence is absent (first missing: {missing[0]}). "
            "Download the v0.1.0-pilot evidence release from "
            "https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/v0.1.0-pilot "
            "and extract the archive into the repository root, restoring runs/pilot/1000/ "
            "and its supporting evaluation artifacts; then rerun "
            "pytest tests/test_evaluation_publication.py."
        )
    return root


@pytest.fixture(scope="module")
def audit():
    """Keep contract/privacy/arithmetic checks runnable from a source-only clone."""
    payload = json.loads((ROOT / "evals/dashboard/pilot-v5-audit-v1.json").read_text())
    return publication.PilotAuditReport.model_validate(payload)


@pytest.fixture(scope="module")
def frozen_sources():
    return require_frozen_sources(ROOT)


@pytest.fixture
def copied_sources(tmp_path, frozen_sources):
    for relative in FROZEN_SOURCE_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen_sources / relative, destination)
    return tmp_path


def resign(payload):
    payload["report_id"] = publication._report_id(payload)
    return payload


def test_tracked_audit_arithmetic_and_pending_human_contract(audit):
    assert audit.coverage.model_dump() == {
        "selected": 1000, "completed": 1000, "unique_texts": 926,
        "exact_text_aliases": 74, "cache_hits": 549, "compared": 1000,
    }
    assert [r.count for r in audit.model_comparison.disagreements] == [310, 339, 341, 354]
    assert [r.final_numerator for r in audit.model_comparison.metrics[:5]] == [828, 906, 838, 902, 948]
    assert audit.model_comparison.metrics[-2].final_value == .201
    assert audit.model_comparison.metrics[-1].final_value == pytest.approx(.0843)
    assert (audit.routing.initial_flagged, audit.routing.final_flagged, audit.routing.fallback_count) == (93, 60, 46)
    assert audit.routing.numeric_signal_available == 0
    assert [(r.concerns, r.concerns_flagged) for r in audit.inspection.cohorts] == [(7, 1), (23, 3)]
    assert audit.synthetic.status == "failed"
    assert audit.synthetic.operational_status == "passed"
    assert audit.synthetic.model_behavior_status == "failed"
    assert audit.ranking_sensitivity.rows[0].issue_id == "issue-usability"
    assert audit.ranking_sensitivity.rows[0].comparison_rank == 3
    playback = next(row for row in audit.ranking_sensitivity.rows if row.issue_id == "issue-playback")
    assert (playback.final_score, playback.comparison_score, playback.comparison_rank) == (204, 319, 1)
    assert audit.human.metrics == []
    assert [r.expected_count for r in audit.human.cohorts] == [50, 150]
    assert "complete_count" not in audit.human.model_dump()
    assert audit.cost_snapshot.as_of == "2026-10-20T07:33:08.452107+00:00"
    assert audit.cost_snapshot.known_usd == .214957094
    assert audit.cost_snapshot.committed_usd == pytest.approx(.231403294)
    assert audit.quality_gate.status == "hold"


def test_missing_frozen_evidence_explains_release_extraction(tmp_path):
    with pytest.raises(pytest.skip.Exception, match="extract the archive into the repository root") as skipped:
        require_frozen_sources(tmp_path)
    assert "v0.1.0-pilot" in str(skipped.value)
    assert "runs/pilot/1000/records.jsonl" in str(skipped.value)


def test_builder_does_not_read_any_human_worksheet(monkeypatch, audit, frozen_sources):
    original = Path.open

    def guard(path, *args, **kwargs):
        assert not any(term in str(path).lower() for term in ("golden", "human-label", "holdout", "worksheet"))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    again = publication.build_pilot_audit("runs/pilot/1000", project_root=frozen_sources, generated_at=audit.generated_at)
    assert again == audit


def test_generic_run_evaluation_is_not_read(copied_sources, monkeypatch):
    """A future human-results file must not become an implicit builder input."""
    evaluation = copied_sources / "runs/pilot/1000/evaluation.json"
    evaluation.write_text('{"synthetic_private_answer_canary": "must never be opened"}')
    original = Path.open

    def guard(path, *args, **kwargs):
        assert path.name != "evaluation.json", "Generic run evaluation must remain unread"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)
    assert publication.build_pilot_audit("runs/pilot/1000", project_root=copied_sources).human.metrics == []


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(human_cases=[]),
    lambda p: p["human"].update(answers=[]),
    lambda p: p["human"].update(metrics=[{"accuracy": 1.0}]),
    lambda p: p["human"].update(ground_truth_available=True),
    lambda p: p["inspection"].update(cases=[]),
    lambda p: p["coverage"].update(completed=True),
    lambda p: p["coverage"].update(completed="1000"),
    lambda p: p["coverage"].update(completed=-1),
    lambda p: p["cost_snapshot"].update(known_usd=float("nan")),
    lambda p: p["cost_snapshot"].update(known_usd=float("inf")),
    lambda p: p["model_comparison"]["metrics"][0].update(final_numerator=1001),
    lambda p: p["model_comparison"]["metrics"][0].update(final_value=.5),
    lambda p: p["cost_snapshot"].update(committed_usd=.01),
    lambda p: p["inspection"]["cohorts"][0].update(concerns=30),
    lambda p: p["routing"].update(fallback_count=47),
    lambda p: p["synthetic"].update(status="passed"),
    lambda p: p["quality_gate"].update(status="pass"),
])
def test_strict_contract_rejects_unmeasured_private_or_inconsistent_content(audit, mutation):
    payload = audit.model_dump()
    mutation(payload)
    with pytest.raises((ValidationError, ValueError)):
        # Invalid non-finite values can fail even before report ID validation.
        publication.PilotAuditReport.model_validate(resign(payload))


@pytest.mark.parametrize("path", ["/Users/private/a.json", "../a.json", "x/../a.json",
                                  "~/a.json", "C:\\private\\a.json", "file:///a.json"])
def test_source_references_are_relative_and_cannot_escape(audit, path):
    payload = audit.model_dump()
    payload["artifact_refs"][0]["path"] = path
    with pytest.raises(ValidationError):
        publication.PilotAuditReport.model_validate(resign(payload))


def test_private_path_in_prose_and_immutable_content_id_rejected(audit):
    payload = audit.model_dump()
    payload["limitations"].append("See /Users/private/notes.json")
    with pytest.raises(ValidationError, match="private"):
        publication.PilotAuditReport.model_validate(resign(payload))
    payload = audit.model_dump()
    payload["quality_gate"]["summary"] = "Different text"
    with pytest.raises(ValidationError, match="report_id"):
        publication.PilotAuditReport.model_validate(payload)


@pytest.mark.parametrize("file,field,value,error", [
    ("run_summary.json", "label_config", "wrong", "configuration"),
    ("configuration.json", "uncertainty_threshold", .99, "configuration fingerprint"),
    ("records.jsonl", "review_rating", "changed source string", "source hash mismatch"),
])
def test_builder_rejects_frozen_source_and_configuration_changes(copied_sources, file, field, value, error):
    path = copied_sources / "runs/pilot/1000" / file
    if file.endswith("jsonl"):
        lines = path.read_text().splitlines()
        row = json.loads(lines[0])
        row[field] = value
        lines[0] = json.dumps(row)
        path.write_text("\n".join(lines) + "\n")
    else:
        document = json.loads(path.read_text())
        document[field] = value
        path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match=error):
        publication.build_pilot_audit("runs/pilot/1000", project_root=copied_sources)


def test_saved_output_is_idempotent_and_cannot_overwrite_human_files(copied_sources):
    output = copied_sources / "evals/dashboard/audit.json"
    first = publication.build_pilot_audit("runs/pilot/1000", project_root=copied_sources, output_path=output)
    before = output.stat().st_mtime_ns
    assert publication.build_pilot_audit("runs/pilot/1000", project_root=copied_sources, output_path=output) == first
    assert output.stat().st_mtime_ns == before
    with pytest.raises(ValueError, match="evals/dashboard"):
        publication.build_pilot_audit("runs/pilot/1000", project_root=copied_sources, output_path="evals/not-a-report.csv")
    altered = json.loads(output.read_text())
    altered["quality_gate"]["summary"] = "Modified after publication"
    output.write_text(json.dumps(resign(altered)))
    with pytest.raises(ValueError, match="immutable"):
        publication.build_pilot_audit("runs/pilot/1000", project_root=copied_sources, output_path=output)


def test_canonical_records_normalize_sql_types_but_preserve_source_and_labels(frozen_sources):
    records = publication._jsonl(frozen_sources / "runs/pilot/1000/records.jsonl")[:3]
    sql_records = deepcopy(records)
    for row in sql_records:
        row["sentiment"] = float(row["sentiment"])
        row.setdefault("reason", None)
        row.setdefault("cache_source_id", None)
        row["provenance"] = {key: row[key] for key in publication._PROVENANCE_FIELDS if key in row}
    assert publication.canonical_records_digest(records) == publication.canonical_records_digest(sql_records[::-1])
    for field, value in [
        ("review_rating", "01"), ("review_text", "changed"), ("topic", "changed"),
        ("intent", "changed"), ("sentiment", .123), ("severity", 5),
        ("entities", ["changed"]), ("evidence_quote", "changed"), ("needs_review", True),
        ("status", "missing"), ("label_config", "changed"),
        ("fallback_used", True), ("initial_prediction", {"topic": "changed"}),
        ("confidence_source", "changed"), ("classifier_model", "changed"),
    ]:
        changed = deepcopy(records)
        changed[0][field] = value if changed[0].get(field) != value else None
        assert publication.canonical_records_digest(records) != publication.canonical_records_digest(changed), field
    with pytest.raises(ValueError, match="Duplicate"):
        publication.canonical_records_digest(records + [records[0]])


class FakeCursor:
    def __init__(self, records, summary, existing=None):
        self.records, self.summary, self.existing = records, summary, existing
        self.sql, self.result, self.inserted = [], None, None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if sql.startswith("SELECT summary"):
            self.result = {"summary": self.summary} if self.summary is not None else None
        elif sql.startswith("SELECT payload"):
            self.result = {"payload": self.existing} if self.existing is not None else None
        elif sql.startswith("INSERT INTO spotify_evaluation_reports"):
            self.inserted = params[-1].obj
            self.existing = self.inserted
        return self

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.records


class FakeConnection:
    def __init__(self, cursor):
        self.saved_cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.saved_cursor


def test_publication_checks_database_source_and_labels_before_insert(monkeypatch, audit, frozen_sources):
    import psycopg
    records = publication._jsonl(ROOT / "runs/pilot/1000/records.jsonl")
    summary = publication._read(ROOT / "runs/pilot/1000/run_summary.json")
    cursor = FakeCursor(records, summary)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: FakeConnection(cursor))
    first = publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)
    assert first["inserted"] and first["validated_records"] == 1000
    second = publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)
    assert second["idempotent"] and not second["inserted"]
    assert not any(sql.lstrip().startswith(("UPDATE spotify_runs", "DELETE", "COPY")) for sql in cursor.sql)
    assert sum(sql.startswith("INSERT") for sql in cursor.sql) == 1
    for field in ("review_text", "topic", "label_config", "initial_prediction", "fallback_used"):
        damaged = deepcopy(records)
        damaged[0][field] = "changed"
        cursor = FakeCursor(damaged, summary)
        with pytest.raises(ValueError, match="source/classification"):
            publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)
        assert cursor.inserted is None
    cursor = FakeCursor(records, {"label_config": "wrong"})
    with pytest.raises(ValueError, match="run/configuration"):
        publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)
    for field, value in (("cache_hits", 1), ("model_settings", {})):
        cursor = FakeCursor(records, {**summary, field: value})
        with pytest.raises(ValueError, match="run/configuration"):
            publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)
        assert cursor.inserted is None
    cursor = FakeCursor(records, None)
    with pytest.raises(ValueError, match="run/configuration"):
        publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)
    cursor = FakeCursor(records, summary, {"altered": True})
    with pytest.raises(ValueError, match="Immutable"):
        publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=ROOT)


def test_changed_artifact_fails_before_any_database_connection(copied_sources, monkeypatch, audit):
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: pytest.fail("Must fail before database connection"))
    (copied_sources / "evals/pilot_inspection_report.json").write_text("{}")
    with pytest.raises(ValueError, match="source fingerprint"):
        publication.publish_evaluation_report(audit, database_url="synthetic-only", project_root=copied_sources)


def test_exported_json_schema_matches_strict_model():
    saved = json.loads((ROOT / "schemas/dashboard-evaluation.schema.json").read_text())
    assert saved == publication.PilotAuditReport.model_json_schema()
    assert saved == json.loads((ROOT / "web/database/dashboard-evaluation.schema.json").read_text())
    assert saved["additionalProperties"] is False
    assert all(v.get("additionalProperties") is False for v in saved["$defs"].values() if v.get("type") == "object")


def test_local_sql_immutable_insertion_rollback_and_restricted_delete(frozen_sources):
    """Opt-in, isolated schema; never use production or touch existing fixture rows."""
    url = os.environ.get("SPOTIFY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set SPOTIFY_TEST_DATABASE_URL to a loopback *_test database.")
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or not parsed.path.endswith("_test"):
        pytest.fail("Only a loopback database ending in _test may run this test.")
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    name = "synthetic_evaluation_" + uuid.uuid4().hex
    run_id = "synthetic-evaluation-transaction"
    report = {"report_id": "synthetic-evaluation-report", "run_id": run_id, "kind": "pilot_audit",
              "schema_version": publication.SCHEMA_VERSION, "label_config": "synthetic-only", "example": True}
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
        connection.execute(f"CREATE SCHEMA {name}")
        try:
            connection.execute(f"SET search_path TO {name}")
            connection.execute((ROOT / "web/database/schema.sql").read_text())
            connection.execute((ROOT / "web/database/evaluation_schema.sql").read_text())
            connection.execute("INSERT INTO spotify_runs(run_id,summary,imported_rows) VALUES(%s,'{}',0)", (run_id,))
            with connection.transaction(), connection.cursor() as cursor:
                assert publication._insert_immutable(cursor, report, Jsonb)
            original = connection.execute("SELECT payload,created_at FROM spotify_evaluation_reports").fetchone()
            with connection.transaction(), connection.cursor() as cursor:
                assert not publication._insert_immutable(cursor, report, Jsonb)
                with pytest.raises(ValueError, match="Immutable"):
                    publication._insert_immutable(cursor, {**report, "example": False}, Jsonb)
            assert connection.execute("SELECT payload,created_at FROM spotify_evaluation_reports").fetchone() == original
            with pytest.raises(RuntimeError, match="deliberate rollback"):
                with connection.transaction(), connection.cursor() as cursor:
                    publication._insert_immutable(cursor, {**report, "report_id": "synthetic-evaluation-rollback"}, Jsonb)
                    raise RuntimeError("deliberate rollback")
            assert connection.execute("SELECT count(*) AS n FROM spotify_evaluation_reports").fetchone()["n"] == 1
            for query in (
                "UPDATE spotify_evaluation_reports SET payload=payload",
                "DELETE FROM spotify_evaluation_reports",
                "DELETE FROM spotify_runs",
            ):
                with pytest.raises(psycopg.Error):
                    connection.execute(query)
            reader_exists = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='spotify_dashboard_reader') AS present"
            ).fetchone()["present"]
            if reader_exists:
                privileges = connection.execute(
                    "SELECT has_table_privilege('spotify_dashboard_reader', %s, 'SELECT') AS can_read,"
                    "has_table_privilege('spotify_dashboard_reader', %s, 'INSERT,UPDATE,DELETE') AS can_write",
                    (name + ".spotify_evaluation_reports", name + ".spotify_evaluation_reports"),
                ).fetchone()
                assert privileges == {"can_read": True, "can_write": False}
        finally:
            connection.execute("SET search_path TO public")
            connection.execute(f"DROP SCHEMA {name} CASCADE")
