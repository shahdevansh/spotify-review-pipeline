"""Publish saved, validated run artifacts to the dashboard's PostgreSQL database.

No model calls are made here. Import and the current-run switch are one transaction;
readers therefore see the complete previous run or the complete replacement.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from .storage import read_jsonl, resolve_jsonl

SOURCE_FIELDS = (
    "review_id", "review_text", "review_rating", "review_likes",
    "app_version", "review_timestamp",
)
REVIEW_COLUMNS = (
    "run_id", *SOURCE_FIELDS, "source_sha256", "status", "reason", "topic", "intent",
    "sentiment", "severity", "entities", "evidence_quote", "needs_review",
    "label_config", "cache_source_id", "provenance",
)
_PROVENANCE_FIELDS = (
    "model", "provider", "route", "confidence", "topic_confidence",
    "intent_confidence", "severity_confidence", "request_id", "fallback_reason",
    "classifier_provider", "classifier_model", "fallback_used",
    "uncertainty_score", "review_reasons",
    "confidence_source", "review_flag_interpretation", "initial_prediction",
)
_CLASSIFICATION_FIELDS = (
    "topic", "intent", "sentiment", "severity", "entities",
    "evidence_quote", "needs_review", "label_config",
)


@dataclass
class RunBundle:
    run_id: str
    summary: dict[str, Any]
    records: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    membership: list[dict[str, str]]
    claims: list[dict[str, str]]
    recommendations: dict[str, Any] | None
    source_profile: dict[str, Any] | None
    evaluation: dict[str, Any] | None


def _json(path: Path, *, required: bool = False) -> Any:
    if not path.exists():
        if required:
            raise ValueError(f"Required run artifact is missing: {path.name}")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _profile(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize common ingestion-report names without supplying missing values."""
    if not value:
        return None
    nested = value.get("profile")
    profile = nested if isinstance(nested, dict) else value
    source = {**profile, **profile.get("counts", {})}
    aliases = {
        "total_rows": ("total_rows", "row_count", "rows", "total_records", "input_count", "records"),
        "nonempty_rows": ("nonempty_rows", "nonempty_texts", "nonempty_review_count"),
        "empty_rows": ("empty_rows", "empty_texts", "empty_review_count", "empty_text_count", "empty_review_text"),
    }
    result: dict[str, Any] = {}
    for target, candidates in aliases.items():
        candidate = next((source[k] for k in candidates if k in source), None)
        result[target] = int(candidate) if isinstance(candidate, (int, str)) and str(candidate).isdigit() else None
    if result["nonempty_rows"] is None and all(result[k] is not None for k in ("total_rows", "empty_rows")):
        result["nonempty_rows"] = result["total_rows"] - result["empty_rows"]
    for key in ("source_sha256", "file_sha256", "sha256", "filename", "source_file"):
        if key in source:
            result[key] = source[key]
    return result


def load_run(
    run_dir: str | Path,
    *,
    ingestion_report: str | Path | None = None,
    evaluation_path: str | Path | None = None,
    skip_evaluation: bool = False,
) -> RunBundle:
    """Read and reconcile a saved run before opening a database connection."""
    if skip_evaluation and evaluation_path is not None:
        raise ValueError("skip_evaluation cannot be combined with an explicit evaluation_path.")
    directory = Path(run_dir)
    summary = _json(directory / "run_summary.json", required=True)
    if not isinstance(summary, dict) or not isinstance(summary.get("run_id"), str) or not summary["run_id"]:
        raise ValueError("run_summary.json must contain a nonempty run_id.")
    records_path = resolve_jsonl(directory / "records.jsonl")
    if not records_path.exists():
        raise ValueError("Required run artifact is missing: records.jsonl")
    records = list(read_jsonl(records_path))

    raw_issues = _json(directory / "issues.json") or []
    if isinstance(raw_issues, dict):
        raw_issues = raw_issues.get("issues", [])
    if not isinstance(raw_issues, list):
        raise ValueError("issues.json must contain an issue list.")
    descriptions = {item["issue_id"]: item for item in raw_issues}
    issues = []
    for row in _csv(directory / "ranking.csv"):
        detail = descriptions.get(row["issue_id"], {})
        issues.append({
            "issue_id": row["issue_id"],
            "name": detail.get("name") or detail.get("title") or row["issue_id"],
            "description": detail.get("description") or detail.get("summary") or "",
            "rank": int(row["rank"]),
            "complaint_count": int(row["complaint_count"]),
            "severity_sum": int(row["severity_sum"]),
            "mean_severity": Decimal(row["mean_severity"]),
            "priority_score": int(row["priority_score"]),
        })
    profile = _json(Path(ingestion_report)) if ingestion_report else summary.get("source_profile")
    if profile is None:
        profile = _json(directory / "ingestion_report.json")
    evaluation = None
    if not skip_evaluation:
        evaluation = _json(Path(evaluation_path)) if evaluation_path else summary.get("evaluation")
        if evaluation is None:
            evaluation = _json(directory / "evaluation.json")
    bundle = RunBundle(
        run_id=summary["run_id"],
        summary=summary,
        records=records,
        issues=issues,
        membership=_csv(directory / "membership.csv"),
        claims=_csv(directory / "claims.csv"),
        recommendations=_json(directory / "recommendations.json"),
        source_profile=_profile(profile),
        evaluation=evaluation,
    )
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: RunBundle) -> None:
    """Reject inconsistent exports, broken references, and unsupported evidence."""
    from .data import row_sha
    from .models import validate_record

    records: dict[str, dict[str, Any]] = {}
    for record in bundle.records:
        if not isinstance(record, dict):
            raise ValueError("Every review record must be a JSON object.")
        for field in SOURCE_FIELDS:
            if not isinstance(record.get(field), str):
                raise ValueError(f"Source field {field} must be an original string.")
        review_id = record["review_id"]
        if not review_id or review_id in records:
            raise ValueError(f"Missing or duplicate review ID: {review_id!r}")
        records[review_id] = record
        validate_record(record)
        source_sha = record.get("source_sha256", "")
        if not isinstance(source_sha, str) or len(source_sha) != 64 or any(c not in "0123456789abcdef" for c in source_sha):
            raise ValueError(f"Invalid source hash on {review_id}")
        if row_sha(record) != source_sha:
            raise ValueError(f"Original source hash mismatch on {review_id}")
        if record.get("status") == "completed":
            if not isinstance(record.get("severity"), int) or isinstance(record["severity"], bool) or not 1 <= record["severity"] <= 5:
                raise ValueError(f"Invalid severity on {review_id}")
            sentiment = record.get("sentiment")
            if not isinstance(sentiment, (float, int)) or isinstance(sentiment, bool) or not -1 <= sentiment <= 1:
                raise ValueError(f"Invalid sentiment on {review_id}")
            quote = record.get("evidence_quote")
            if not isinstance(quote, str) or not quote or quote not in record["review_text"]:
                raise ValueError(f"Unsupported evidence quote on {review_id}")
            if not isinstance(record.get("entities"), list) or not all(isinstance(x, str) for x in record["entities"]):
                raise ValueError(f"Invalid entities on {review_id}")
            if not isinstance(record.get("needs_review"), bool):
                raise ValueError(f"Missing needs_review flag on {review_id}")
            if not record.get("label_config"):
                raise ValueError(f"Missing label configuration on {review_id}")
        elif record.get("status") == "quarantined":
            if not record.get("reason"):
                raise ValueError(f"Quarantine reason missing on {review_id}")
        else:
            raise ValueError(f"Only completed or quarantined final records may be published: {review_id}")
    for record in records.values():
        source_id = record.get("cache_source_id")
        if source_id:
            source = records.get(source_id)
            if not source or source_id == record["review_id"] or source.get("status") != "completed" or source.get("cache_source_id"):
                raise ValueError(f"Cache provenance must point directly to a completed original: {record['review_id']}")
            if source["review_text"] != record["review_text"] or source.get("label_config") != record.get("label_config"):
                raise ValueError(f"Cache provenance text/config mismatch: {record['review_id']}")
            if any(source.get(key) != record.get(key) for key in _CLASSIFICATION_FIELDS):
                raise ValueError(f"Cache provenance classification mismatch: {record['review_id']}")
    if bundle.summary.get("input_count") != len(records):
        raise ValueError("Summary input_count does not match records.jsonl.")
    status_counts = Counter(record["status"] for record in records.values())
    for key, status in (("completed", "completed"), ("quarantined", "quarantined")):
        if key in bundle.summary and bundle.summary[key] != status_counts[status]:
            raise ValueError(f"Summary {key} does not match records.jsonl.")

    issues = {issue["issue_id"]: issue for issue in bundle.issues}
    if len(issues) != len(bundle.issues):
        raise ValueError("Duplicate ranked issue IDs.")
    memberships: dict[str, str] = {}
    severities: dict[str, list[int]] = defaultdict(list)
    for member in bundle.membership:
        review_id, issue_id = member["review_id"], member["issue_id"]
        if review_id in memberships:
            raise ValueError(f"Duplicate issue membership for {review_id}")
        if review_id not in records or issue_id not in issues:
            raise ValueError("Membership references a missing review or issue.")
        record = records[review_id]
        if record["status"] != "completed" or record.get("intent") not in ("complaint", "cancellation"):
            raise ValueError("Only completed complaint/cancellation records belong in issues.")
        memberships[review_id] = issue_id
        severities[issue_id].append(record["severity"])
    # Incomplete upstream grouping can be represented honestly by no grouping files.
    if bundle.issues or bundle.membership:
        expected_members = {
            key for key, record in records.items()
            if record["status"] == "completed" and record.get("intent") in ("complaint", "cancellation")
        }
        if set(memberships) != expected_members:
            raise ValueError("Issue membership does not cover all complaint/cancellation reviews.")
    for issue_id, issue in issues.items():
        values = severities[issue_id]
        count, total = len(values), sum(values)
        mean = (Decimal(total) / Decimal(count) if count else Decimal(0)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if (issue["complaint_count"], issue["severity_sum"], issue["priority_score"], issue["mean_severity"]) != (count, total, total, mean):
            raise ValueError(f"Ranking does not reproduce from issue membership: {issue_id}")
    expected_order = sorted(bundle.issues, key=lambda item: (-item["priority_score"], item["issue_id"]))
    if any(issue["rank"] != i for i, issue in enumerate(expected_order, 1)):
        raise ValueError("Ranking order must be descending score, then ascending issue ID.")
    claims = {claim["claim_id"]: claim for claim in bundle.claims}
    if len(claims) != len(bundle.claims):
        raise ValueError("Duplicate claim IDs.")
    seen_metrics = set()
    for claim in bundle.claims:
        issue = issues.get(claim.get("issue_id"))
        metric = claim.get("metric")
        if issue is None or metric not in ("complaint_count", "severity_sum", "mean_severity", "priority_score"):
            raise ValueError("Claim references an unknown issue or unsupported baseline metric.")
        try:
            agrees = Decimal(claim["value"]) == Decimal(str(issue[metric]))
        except (ValueError, ArithmeticError):
            agrees = False
        if not agrees:
            raise ValueError(f"Claim does not reproduce from validated ranking: {claim['claim_id']}")
        key = (claim["issue_id"], metric)
        if key in seen_metrics:
            raise ValueError("Duplicate claim for the same issue and metric.")
        seen_metrics.add(key)
    if bundle.recommendations is not None:
        document = bundle.recommendations
        if not isinstance(document, dict):
            raise ValueError("Recommendations must be a JSON object.")
        priority = document.get("priority_issue_id")
        if priority is not None and priority not in issues:
            raise ValueError("Recommendation priority references a missing issue.")
        for item in document.get("recommendations", []) + document.get("alternatives", []):
            if not isinstance(item, dict):
                raise ValueError("Every recommendation or alternative must be an object.")
            for field, known in (("issue_ids", issues), ("claim_ids", claims), ("review_ids", records)):
                if any(reference not in known for reference in item.get(field, [])):
                    raise ValueError(f"Recommendation contains an unknown {field} reference.")


def import_run(
    run_dir: str | Path,
    database_url: str | None = None,
    *,
    ingestion_report: str | Path | None = None,
    evaluation_path: str | Path | None = None,
    max_storage_bytes: int | None = None,
) -> dict[str, Any]:
    """Atomically upsert a run, bulk-copy its records, and make it current.

    The caller supplies DATABASE_URL; this function never prints or persists it.
    """
    if max_storage_bytes is not None and (type(max_storage_bytes) is not int or max_storage_bytes <= 0):
        raise ValueError("max_storage_bytes must be a positive integer or None.")
    bundle = load_run(run_dir, ingestion_report=ingestion_report, evaluation_path=evaluation_path)
    connection_string = database_url or os.environ.get("DATABASE_URL")
    if not connection_string:
        raise ValueError("Set DATABASE_URL to import saved results into PostgreSQL.")
    import psycopg
    from psycopg.types.json import Jsonb

    schema_path = Path(__file__).resolve().parents[2] / "web" / "database" / "schema.sql"
    if not schema_path.exists():
        raise ValueError("web/database/schema.sql is missing; run the importer from the repository checkout.")
    with psycopg.connect(connection_string, connect_timeout=15) as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema_path.read_text(encoding="utf-8"))
            cursor.execute("SELECT pg_advisory_xact_lock(873522106)")
            cursor.execute("UPDATE spotify_runs SET is_current = false WHERE is_current = true")
            cursor.execute("DELETE FROM spotify_runs WHERE run_id = %s", (bundle.run_id,))
            cursor.execute(
                """INSERT INTO spotify_runs
                   (run_id,is_current,summary,source_profile,evaluation,imported_rows)
                   VALUES (%s,true,%s,%s,%s,%s)""",
                (bundle.run_id, Jsonb(bundle.summary), Jsonb(bundle.source_profile), Jsonb(bundle.evaluation), len(bundle.records)),
            )
            with cursor.copy(f"COPY spotify_reviews ({','.join(REVIEW_COLUMNS)}) FROM STDIN") as copy:
                for record in bundle.records:
                    row = {
                        **record,
                        "run_id": bundle.run_id,
                        "entities": Jsonb(record.get("entities", [])),
                        "provenance": Jsonb({key: record[key] for key in _PROVENANCE_FIELDS if key in record}),
                    }
                    copy.write_row(tuple(row.get(column) for column in REVIEW_COLUMNS))
            if bundle.issues:
                cursor.executemany(
                    """INSERT INTO spotify_issues (run_id,issue_id,name,description,rank,
                       complaint_count,severity_sum,mean_severity,priority_score)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(bundle.run_id, *(issue[key] for key in (
                        "issue_id", "name", "description", "rank", "complaint_count",
                        "severity_sum", "mean_severity", "priority_score",
                    ))) for issue in bundle.issues],
                )
            with cursor.copy("COPY spotify_membership (run_id,issue_id,review_id) FROM STDIN") as copy:
                for member in bundle.membership:
                    copy.write_row((bundle.run_id, member["issue_id"], member["review_id"]))
            if bundle.claims:
                cursor.executemany(
                    "INSERT INTO spotify_claims (run_id,claim_id,issue_id,metric,value) VALUES (%s,%s,%s,%s,%s)",
                    [(bundle.run_id, row["claim_id"], row.get("issue_id") or None, row["metric"], row["value"]) for row in bundle.claims],
                )
            if bundle.recommendations is not None:
                cursor.execute(
                    "INSERT INTO spotify_recommendations (run_id,document) VALUES (%s,%s)",
                    (bundle.run_id, Jsonb(bundle.recommendations)),
                )
            cursor.execute("""
                SELECT COALESCE(SUM(pg_total_relation_size(c.oid)),0)
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND c.relkind='r'
                  AND c.relname IN ('spotify_runs','spotify_reviews','spotify_issues',
                                   'spotify_membership','spotify_claims','spotify_recommendations',
                                   'spotify_evaluation_reports')
            """)
            size = int(cursor.fetchone()[0])
            if max_storage_bytes is not None and size > max_storage_bytes:
                # Raising inside the connection context rolls back the entire
                # import, including the is_current switch and old-run deletion.
                raise ValueError(f"Imported database size {size} exceeds {max_storage_bytes} bytes; publication rolled back.")
    return {
        "run_id": bundle.run_id,
        "imported_rows": len(bundle.records),
        "issues": len(bundle.issues),
        "storage_bytes": size,
        "projected_bytes_210k": (size * 210_000 + len(bundle.records) - 1) // len(bundle.records) if bundle.records else None,
        "status": "published",
    }
