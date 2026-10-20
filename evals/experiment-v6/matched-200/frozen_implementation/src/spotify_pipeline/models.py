"""Shared, strict record contracts. Source strings are never normalized."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SOURCE_FIELDS = (
    "review_id",
    "review_text",
    "review_rating",
    "review_likes",
    "app_version",
    "review_timestamp",
)
TOPICS = ("access", "usability", "playback", "downloads", "catalog", "billing", "support", "other")
INTENTS = ("cancellation", "complaint", "request", "praise", "unclear")
Topic = Literal["access", "usability", "playback", "downloads", "catalog", "billing", "support", "other"]
Intent = Literal["cancellation", "complaint", "request", "praise", "unclear"]
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SourceReview(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    review_id: str = Field(min_length=1)
    review_text: str
    review_rating: str
    review_likes: str
    app_version: str
    review_timestamp: str


class Classification(BaseModel):
    """Language judgments only; metadata never belongs in model inputs."""

    model_config = ConfigDict(strict=True, extra="forbid")

    topic: Topic
    intent: Intent
    sentiment: float = Field(ge=-1, le=1, allow_inf_nan=False)
    severity: int = Field(ge=1, le=5)
    entities: list[str]
    evidence_quote: str = Field(min_length=1)
    needs_review: bool

    @model_validator(mode="after")
    def reject_empty_entities(self) -> "Classification":
        if any(not entity.strip() for entity in self.entities):
            raise ValueError("entities must contain nonempty source terms")
        return self


class CompletedRecord(SourceReview, Classification):
    # Extra provenance fields are allowed, but required fields remain strict.
    model_config = ConfigDict(strict=True, extra="allow")

    source_sha256: SHA256
    status: Literal["completed"] = "completed"
    label_config: str = Field(min_length=1)
    cache_source_id: str | None = None

    @model_validator(mode="after")
    def check_source_evidence(self) -> "CompletedRecord":
        if not self.review_text.strip():
            raise ValueError("completed records must have nonempty review text")
        if self.evidence_quote not in self.review_text:
            raise ValueError("evidence_quote must be an exact original-text substring")
        if self.cache_source_id == self.review_id:
            raise ValueError("cache_source_id cannot refer to the same review")
        if any(entity.casefold() not in self.review_text.casefold() for entity in self.entities):
            raise ValueError("entities must be explicitly present in the review text")
        return self


class QuarantinedRecord(SourceReview):
    model_config = ConfigDict(strict=True, extra="allow")

    source_sha256: SHA256
    status: Literal["quarantined"] = "quarantined"
    reason: str = Field(min_length=1)
    attempt_count: int = Field(default=0, ge=0)
    label_config: str = Field(min_length=1)


Record = CompletedRecord | QuarantinedRecord


def validate_record(record: dict) -> Record:
    """Validate status-specific output; pending inputs are not final records."""
    if record.get("status") == "completed":
        return CompletedRecord.model_validate(record)
    if record.get("status") == "quarantined":
        return QuarantinedRecord.model_validate(record)
    raise ValueError("final record status must be completed or quarantined")
