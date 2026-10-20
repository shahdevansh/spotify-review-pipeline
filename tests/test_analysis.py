"""Synthetic fixtures only; these tests do not produce production run evidence."""
import asyncio
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from spotify_pipeline.analysis import (
    bounded_evidence, build_analysis, calculate_ranking, rerank, run_analysis,
    validate_recommendations,
)
from spotify_pipeline.export import export_grading


def record(rid, topic="playback", severity=3, intent="complaint", text="Synthetic playback fails."):
    return {
        "review_id": rid, "review_text": text, "review_rating": "1",
        "review_likes": "0", "app_version": "", "review_timestamp": "2023-01-01 00:00:00",
        "source_sha256": "synthetic-hash", "status": "completed", "topic": topic,
        "intent": intent, "sentiment": -0.5, "severity": severity, "entities": [],
        "evidence_quote": text, "needs_review": False, "label_config": "synthetic-v1",
    }


def test_ranking_keeps_original_ids_counts_and_stable_ties():
    rows = [record("a", "playback", 4), record("b", "playback", 2),
            record("c", "access", 3), record("d", "access", 3),
            record("e", "catalog", 1, "request"), record("f", "other", 1, "praise"),
            record("g", "support", 2, "cancellation")]
    rows[1]["cache_source_id"] = "a"  # Accounting never collapses duplicate source IDs.
    result = calculate_ranking(rows)
    assert len(result["membership"]) == 5
    assert [r["issue_id"] for r in result["ranking"]] == ["issue-access", "issue-playback", "issue-support"]
    assert result["ranking"][1]["complaint_count"] == 2
    assert result["ranking"][1]["priority_score"] == 6
    assert result["ranking"][1]["mean_severity"] == "3.000000"
    assert len(result["claims"]) == 12


def test_mean_rounding_and_offline_rerank_identical(tmp_path):
    rows = [record("a", severity=1), record("b", severity=2), record("c", severity=2)]
    (tmp_path / "records.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = build_analysis(rows, tmp_path)
    assert result["ranking"][0]["mean_severity"] == "1.666667"
    before = (tmp_path / "ranking.csv").read_bytes()
    assert rerank(tmp_path) == result
    assert (tmp_path / "ranking.csv").read_bytes() == before


@pytest.mark.parametrize("membership", [
    [],
    [{"issue_id": "issue-playback", "review_id": "a"}, {"issue_id": "issue-playback", "review_id": "a"}],
    [{"issue_id": "issue-access", "review_id": "a"}],
    [{"issue_id": "issue-playback", "review_id": "foreign"}],
])
def test_rejects_missing_duplicate_wrong_or_foreign_membership(membership):
    with pytest.raises(ValueError):
        calculate_ranking([record("a")], membership)


def test_pending_and_quarantined_do_not_enter_business_aggregates():
    rows = [record("a"), {**record("b"), "status": "pending"},
            {**record("c"), "status": "quarantined", "reason": "synthetic_failure"}]
    assert calculate_ranking(rows)["ranking"][0]["complaint_count"] == 1


def test_duplicate_record_id_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        calculate_ranking([record("a"), record("a")])


def test_invalid_intent_is_not_silently_omitted_from_ranking():
    with pytest.raises(ValueError, match="intent"):
        calculate_ranking([record("a", intent="complaint_typo")])


def test_evidence_is_bounded_deterministic_and_deduplicated():
    rows = [record(str(i), text=f"Synthetic text {i // 2}") for i in range(30)]
    evidence = bounded_evidence(rows)
    assert len(evidence["issue-playback"]) == 5
    assert evidence == bounded_evidence(list(reversed(rows)))
    assert len({r["review_text"] for r in evidence["issue-playback"]}) == 5


def memo_result():
    return {
        "summary": "Playback is the strongest measured priority.", "priority_issue_id": "issue-playback",
        "recommendations": [{
            "title": "Restore playback reliability", "rationale": "Reported failures obstruct listening.",
            "issue_ids": ["issue-playback"], "claim_ids": ["claim-playback-severity-sum"],
            "review_ids": ["a"],
        }], "alternatives": [],
        "limitations": ["The historical reviews are self-selected and may omit affected users."],
    }


def test_bounded_distinct_roles_and_grounded_memo(tmp_path):
    calls = []
    async def task(role, payload, schema, review_ids, _validator=None):
        calls.append((role, payload, review_ids))
        if role == "group":
            response = {"issues": [{"issue_id": "issue-playback", "title": "Playback reliability",
                                    "description": "Listening fails.", "review_ids": ["a"]}]}
        else:
            response = memo_result()
        if _validator:
            _validator(response)
        return response
    result = asyncio.run(run_analysis([record("a")], tmp_path, task))
    assert [call[0] for call in calls] == ["group", "memo"]
    assert calls[0][1] != calls[1][1]
    assert result["recommendations"]["priority_issue_id"] == "issue-playback"
    assert "claim-playback-severity-sum" in (tmp_path / "memo.md").read_text()
    assert (tmp_path / "handoffs" / "memo.input.json").exists()


@pytest.mark.parametrize("mutation", ["invented_claim", "invented_review", "unchecked_number", "invented_issue"])
def test_memo_rejects_ungrounded_claims(mutation):
    rows = [record("a")]
    doc = memo_result()
    if mutation == "invented_claim":
        doc["recommendations"][0]["claim_ids"] = ["fake"]
    elif mutation == "invented_review":
        doc["recommendations"][0]["review_ids"] = ["fake"]
    elif mutation == "unchecked_number":
        doc["summary"] = "Fixing playback would recover 10 million users."
    else:
        doc["priority_issue_id"] = "issue-fake"
    with pytest.raises(ValueError):
        validate_recommendations(doc, calculate_ranking(rows), bounded_evidence(rows))


def test_export_does_not_fabricate_missing_execution(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    source = tmp_path / "source.csv"
    row = record("a")
    source_fields = ["review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp"]
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
    (run / "records.jsonl").write_text(json.dumps(row) + "\n")
    build_analysis([row], run)
    report = export_grading(run, tmp_path / "grading", source_path=source, analysis_path=source)
    assert report["status"] == "incomplete_evidence"
    assert "checkpoint_before.json" in report["missing_files"]
    assert not (tmp_path / "grading" / "calls.jsonl").exists()
    manifest = json.loads((tmp_path / "grading" / "run.json").read_text())
    assert manifest["version"] == "a5-audit-v1"
    assert manifest["analysis_count"] == 1


def test_export_preserves_historical_calls(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    source = tmp_path / "source.csv"
    source.write_text("review_id,review_text,review_rating,review_likes,app_version,review_timestamp\na,hello,5,0,,2023-01-01\n")
    (run / "evidence_calls.jsonl").write_text('{"request_id":"historical"}\n')
    (run / "calls.jsonl").write_text("")
    export_grading(run, tmp_path / "grading", source_path=source, analysis_path=source)
    assert (tmp_path / "grading" / "calls.jsonl").read_text() == '{"request_id":"historical"}\n'


def test_synthetic_adapter_passes_unmodified_course_checker(tmp_path):
    """A contract test, not evidence of a real model run or recovery recording."""
    checker_path = Path(__file__).resolve().parents[1] / "vendor/course/check_submission.py"
    spec = importlib.util.spec_from_file_location("course_checker_for_synthetic_test", checker_path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    run, grading = tmp_path / "run", tmp_path / "grading"
    run.mkdir()
    rows = [record("a", severity=4), record("b", severity=2)]
    fields = ("review_id", "review_text", "review_rating", "review_likes", "app_version", "review_timestamp")
    source = tmp_path / "source.csv"
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        row["source_sha256"] = checker.row_sha(row)
    (run / "records.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    build_analysis(rows, run)
    (run / "checkpoint_before.json").write_text(json.dumps({"completed_ids": ["a"]}))
    (run / "checkpoint_after.json").write_text(json.dumps({"completed_ids": ["a", "b"]}))
    calls = [
        {"request_id": f"synthetic-{index}", "role": role, "review_ids": ids,
         "model": "synthetic-test-model", "phase": phase, "outcome": "succeeded",
         "label_config": "synthetic-v1", "input_tokens": 0, "output_tokens": 0}
        for index, (role, ids, phase) in enumerate([
            ("enrich", ["a"], "initial"), ("enrich", ["b"], "resume"),
            ("verify", ["a"], "initial"), ("group", ["a", "b"], "initial"),
            ("memo", [], "initial"),
        ])
    ]
    (run / "calls.jsonl").write_text("".join(json.dumps(call) + "\n" for call in calls))
    export_grading(run, grading, source_path=source, analysis_path=source)
    result = checker.audit(grading, checker.reference(source, source))
    assert result["status"] == "pass", result["issue_counts"]
    assert result["coverage"]["valid_completed"] == 2
