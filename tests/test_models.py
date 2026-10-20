import pytest
from pydantic import ValidationError

from spotify_pipeline.models import CompletedRecord, QuarantinedRecord, SourceReview, validate_record


def record(**changes):
    value = {
        "review_id": "synthetic-1",
        "review_text": "Downloads stop offline.",
        "review_rating": "1",
        "review_likes": "0",
        "app_version": "",
        "review_timestamp": "2023-01-01 00:00:00",
        "source_sha256": "a" * 64,
        "status": "completed",
        "topic": "downloads",
        "intent": "complaint",
        "sentiment": -0.5,
        "severity": 4,
        "entities": ["Downloads"],
        "evidence_quote": "Downloads stop offline.",
        "needs_review": False,
        "label_config": "synthetic-v1",
    }
    value.update(changes)
    return value


def test_source_keeps_exact_strings():
    source = {key: value for key, value in record().items() if key.startswith("review_") or key == "app_version"}
    source["review_likes"] = " 0002 "
    source["review_text"] = " \n original \n "
    assert SourceReview.model_validate(source).model_dump() == source


@pytest.mark.parametrize(
    "change",
    [
        {"severity": True},
        {"severity": 3.5},
        {"severity": 6},
        {"sentiment": float("nan")},
        {"sentiment": 1.1},
        {"needs_review": "false"},
        {"topic": "premium"},
        {"intent": "angry"},
        {"evidence_quote": "stop playing"},
        {"entities": ["iPhone"]},
        {"review_text": ""},
        {"cache_source_id": "synthetic-1"},
    ],
)
def test_completed_validation_rejects_invalid_contract(change):
    with pytest.raises(ValidationError):
        CompletedRecord.model_validate(record(**change))


def test_completed_accepts_explicit_provenance():
    completed = CompletedRecord.model_validate(record(confidence=0.8, cache_source_id="synthetic-2"))
    assert completed.model_dump()["confidence"] == 0.8
    assert completed.cache_source_id == "synthetic-2"


def test_quarantine_and_unknown_status():
    source = {key: record()[key] for key in SourceReview.model_fields}
    q = QuarantinedRecord.model_validate(
        dict(source, review_text="", source_sha256="a" * 64, status="quarantined",
             reason="empty_review_text", label_config="synthetic-v1")
    )
    assert q.attempt_count == 0
    assert isinstance(validate_record(q.model_dump()), QuarantinedRecord)
    with pytest.raises(ValueError, match="final record status"):
        validate_record(dict(source, status="pending"))
