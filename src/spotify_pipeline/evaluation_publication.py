"""Build and publish the frozen pilot's aggregate-only evaluation, without models.

Human worksheets are deliberately not inputs. Publishing adds one immutable
report in a transaction; it never replaces run data, rankings, or recommendations.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .data import row_sha
from .database import SOURCE_FIELDS, _PROVENANCE_FIELDS, load_run

SCHEMA_VERSION = "spotify-dashboard-evaluation-v1"
FROZEN_RUN_ID = "1000-1ad0e35d239c3e9d"
FROZEN_LABEL_CONFIG = "spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb"
FROZEN_RECORDS_SHA256 = "d7d107cf8b390d4c2f311aa2b2e4d0d29d9a2ba19cb40059e32e91670500be02"
FROZEN_CONFIGURATION_SHA256 = "47d9eba2fc4f3b7776b2f3d95cf758c92db200416743512266c14650852877da"
FIELDS = ("topic", "intent", "severity", "sentiment", "needs_review")
Count = Annotated[int, Field(ge=0)]
Positive = Annotated[int, Field(gt=0)]
Money = Annotated[float, Field(ge=0)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Status = Literal["passed", "failed", "not_available"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or any(
        part in {"..", ".", "~"} for part in value.split("/")
    ) or ":" in value:
        raise ValueError("Artifact paths must be normalized repository-relative paths.")
    return value


def _dated(value: str) -> str:
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("A dated snapshot requires an ISO-8601 timestamp.") from exc
    if date.tzinfo is None:
        raise ValueError("Snapshot timestamps must include a timezone.")
    return value


class EvaluationArtifact(StrictModel):
    path: str
    sha256: Digest
    role: str

    _path = field_validator("path")(_relative_path)


class ComparisonMetric(StrictModel):
    id: str
    label: str
    initial_numerator: Count | None
    final_numerator: Count | None
    denominator: Positive
    unit: Literal["fraction", "severity_points", "sentiment_points"]
    initial_value: float | None
    final_value: float | None
    definition: str

    @model_validator(mode="after")
    def arithmetic(self):
        for prefix in ("initial", "final"):
            numerator, value = getattr(self, prefix + "_numerator"), getattr(self, prefix + "_value")
            if self.unit == "fraction":
                if numerator is None or value is None or numerator > self.denominator:
                    raise ValueError("Fraction metrics require bounded counts and values.")
                if not math.isclose(value, numerator / self.denominator, abs_tol=1e-12):
                    raise ValueError("Metric numerator/denominator does not reproduce its value.")
            elif numerator is not None or (value is not None and value < 0):
                raise ValueError("Mean differences use values, not agreement numerators.")
        return self


class RankingSensitivityRow(StrictModel):
    issue_id: str
    final_rank: Positive
    final_score: Count
    comparison_rank: Positive | None
    comparison_score: Count


class Coverage(StrictModel):
    selected: Positive
    completed: Count
    unique_texts: Positive
    exact_text_aliases: Count
    cache_hits: Count
    compared: Count

    @model_validator(mode="after")
    def counts(self):
        if self.unique_texts + self.exact_text_aliases != self.selected:
            raise ValueError("Distinct texts and aliases must account for selected records.")
        if any(n > self.selected for n in (self.completed, self.cache_hits, self.compared)):
            raise ValueError("Coverage exceeds selected records.")
        return self


class QualityGate(StrictModel):
    status: Literal["hold", "pass", "not_evaluated"]
    summary: str
    reasons: list[str]
    recommendations_provisional: bool


class HumanCohort(StrictModel):
    id: Literal["mandatory_golden_50", "fresh_text_disjoint_150"]
    label: str
    expected_count: Positive
    status: Literal["pending"]
    sampling_note: str


class HumanPending(StrictModel):
    status: Literal["pending_labels"]
    ground_truth_available: Literal[False]
    cohorts: list[HumanCohort]
    metrics: Annotated[list[None], Field(max_length=0)]
    interpretation: str

    @model_validator(mode="after")
    def planned_cohorts(self):
        if {c.id: c.expected_count for c in self.cohorts} != {"mandatory_golden_50": 50, "fresh_text_disjoint_150": 150} or len(self.cohorts) != 2:
            raise ValueError("Human evaluation remains the planned golden 50 plus fresh 150.")
        return self


class Disagreement(StrictModel):
    id: str
    label: str
    count: Count
    denominator: Positive
    definition: str

    @model_validator(mode="after")
    def counts(self):
        if self.count > self.denominator:
            raise ValueError("Disagreements exceed their denominator.")
        return self


class ModelComparison(StrictModel):
    status: Literal["compared", "not_available"]
    answer_blind: bool
    ground_truth: Literal[False]
    shared_fallback_verifier_model: bool
    verifier_provider: str
    verifier_model: str
    metrics: list[ComparisonMetric]
    disagreements: list[Disagreement]


class Routing(StrictModel):
    numeric_signal_available: Count
    confidence_calibrated: Literal[False]
    initial_flagged: Count
    final_flagged: Count
    fallback_count: Count
    fallback_cap: Count
    unique_text_denominator: Positive
    interpretation: str

    @model_validator(mode="after")
    def cap(self):
        if self.fallback_count > self.fallback_cap or self.fallback_cap > self.unique_text_denominator:
            raise ValueError("Fallback counts exceed the saved cap.")
        return self


class InspectionCohort(StrictModel):
    id: str
    label: str
    count: Positive
    supported: Count
    concerns: Count
    ambiguous: Count
    concerns_flagged: Count
    selection_method: str

    @model_validator(mode="after")
    def counts(self):
        if self.supported + self.concerns + self.ambiguous != self.count or self.concerns_flagged > self.concerns:
            raise ValueError("Inspection assessments do not reconcile.")
        return self


class Inspection(StrictModel):
    reviewer_type: Literal["ai_assisted"]
    ground_truth: Literal[False]
    cohorts: list[InspectionCohort]
    interpretation: str


class Synthetic(StrictModel):
    status: Status
    operational_status: Status
    model_behavior_status: Status
    case_count: Count
    scope: str
    artifact_path: str | None

    @field_validator("artifact_path")
    @classmethod
    def path(cls, value):
        return _relative_path(value) if value is not None else None


class RankingSensitivity(StrictModel):
    status: Literal["available", "not_available"]
    ground_truth: Literal[False]
    interpretation: str
    compared_count: Count
    rows: list[RankingSensitivityRow]


class StructuralCheck(StrictModel):
    id: str
    label: str
    passed_count: Count
    total: Positive

    @model_validator(mode="after")
    def counts(self):
        if self.passed_count > self.total:
            raise ValueError("Passed checks exceed their denominator.")
        return self


class Structural(StrictModel):
    status: Status
    checks: list[StructuralCheck]
    semantic_support_established: Literal[False]


class CostSnapshot(StrictModel):
    as_of: str
    source: str
    known_usd: Money
    unknown_hold_usd: Money
    reserved_usd: Money
    committed_usd: Money
    attempts: Count
    basis: Literal["nominal_usage_reprice"]
    scope: Literal["project_snapshot"]

    _date = field_validator("as_of")(_dated)
    _source = field_validator("source")(_relative_path)

    @model_validator(mode="after")
    def arithmetic(self):
        if not math.isclose(self.committed_usd, self.known_usd + self.unknown_hold_usd + self.reserved_usd, abs_tol=1e-10):
            raise ValueError("Project cost snapshot does not reconcile.")
        return self


class PilotAuditReport(StrictModel):
    schema_version: Literal["spotify-dashboard-evaluation-v1"]
    kind: Literal["pilot_audit"]
    report_id: Annotated[str, Field(pattern=r"^pilot-audit-[0-9a-f]{64}$")]
    run_id: Literal["1000-1ad0e35d239c3e9d"]
    label_config: Literal["spotify-d6e940ab47b6313cd1edcca453c786586b7c36a75343e7c781cbf15fbe646dbb"]
    generated_at: str
    records_sha256: Literal["d7d107cf8b390d4c2f311aa2b2e4d0d29d9a2ba19cb40059e32e91670500be02"]
    artifact_refs: list[EvaluationArtifact]
    coverage: Coverage
    quality_gate: QualityGate
    human: HumanPending
    model_comparison: ModelComparison
    routing: Routing
    inspection: Inspection
    synthetic: Synthetic
    ranking_sensitivity: RankingSensitivity
    structural: Structural
    cost_snapshot: CostSnapshot
    limitations: list[str]

    _date = field_validator("generated_at")(_dated)

    @model_validator(mode="after")
    def report_integrity(self):
        payload = self.model_dump()
        if self.report_id != _report_id(payload):
            raise ValueError("Report content does not match its immutable report_id.")
        for items in (self.artifact_refs, self.model_comparison.metrics, self.model_comparison.disagreements,
                      self.inspection.cohorts, self.ranking_sensitivity.rows, self.structural.checks):
            keys = [getattr(x, "path", getattr(x, "id", getattr(x, "issue_id", ""))) for x in items]
            if len(keys) != len(set(keys)):
                raise ValueError("Report contains duplicate artifact or measurement identifiers.")
        n = self.coverage.compared
        if any(x.denominator != n for x in self.model_comparison.metrics + self.model_comparison.disagreements):
            raise ValueError("Comparison denominators do not match coverage.")
        if self.ranking_sensitivity.compared_count != n:
            raise ValueError("Ranking sensitivity uses a different comparison cohort.")
        if self.quality_gate.status != "hold" or not self.quality_gate.recommendations_provisional:
            raise ValueError("This frozen pilot audit must retain its quality hold.")
        if self.synthetic.status == "passed" and (
            self.synthetic.operational_status != "passed" or self.synthetic.model_behavior_status != "passed"
        ):
            raise ValueError("Synthetic overall success requires both operational and model conformance success.")
        _reject_private_strings(payload)
        return self


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _report_id(payload: dict) -> str:
    return "pilot-audit-" + hashlib.sha256(_canonical({k: v for k, v in payload.items() if k != "report_id"})).hexdigest()


def _reject_private_strings(value: Any) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _reject_private_strings(item)
    elif isinstance(value, list):
        for item in value:
            _reject_private_strings(item)
    elif isinstance(value, str) and re.search(r"/Users/|/home/|file://|postgres(?:ql)?://|[A-Za-z]:\\", value):
        raise ValueError("Public evaluation cannot contain private filesystem or connection paths.")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(root: Path, relative: str) -> Path:
    _relative_path(relative)
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("Evaluation artifact must be a file inside the repository.")
    return target


def canonical_records_digest(records: list[dict]) -> str:
    """Match source, labels, and report-driving provenance despite SQL float types."""
    rows = []
    for record in records:
        row = {key: record.get(key) for key in (
            *SOURCE_FIELDS, "source_sha256", "status", "reason", "topic", "intent",
            "sentiment", "severity", "entities", "evidence_quote", "needs_review",
            "label_config", "cache_source_id",
        )}
        if row["sentiment"] is not None:
            row["sentiment"] = float(row["sentiment"])
        provenance = record.get("provenance")
        row["provenance"] = (provenance if isinstance(provenance, dict) else
                             {key: record[key] for key in _PROVENANCE_FIELDS if key in record})
        rows.append(row)
    if len({row["review_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate review IDs in canonical record fingerprint.")
    return hashlib.sha256(_canonical(sorted(rows, key=lambda row: row["review_id"]))).hexdigest()


def _rank(records: list[dict]) -> list[dict]:
    counts, scores = Counter(), Counter()
    for row in records:
        if row["intent"] in {"complaint", "cancellation"}:
            issue = "issue-" + row["topic"]
            counts[issue] += 1
            scores[issue] += row["severity"]
    return [{"issue_id": issue, "rank": i, "score": scores[issue], "count": counts[issue]}
            for i, issue in enumerate(sorted(scores, key=lambda issue: (-scores[issue], issue)), 1)]


def build_pilot_audit(
    run_dir: str | Path, *, project_root: str | Path, output_path: str | Path | None = None,
    generated_at: str | None = None,
) -> PilotAuditReport:
    """Build one reproducible public report from v5 artifacts; never read human labels."""
    root = Path(project_root).resolve()
    directory = Path(run_dir)
    directory = (root / directory).resolve() if not directory.is_absolute() else directory.resolve()
    if directory != root / "runs/pilot/1000":
        raise ValueError("Only the frozen runs/pilot/1000 audit is supported.")
    paths = {
        "records": "runs/pilot/1000/records.jsonl",
        "summary": "runs/pilot/1000/run_summary.json",
        "configuration": "runs/pilot/1000/configuration.json",
        "manifest": "runs/pilot/1000/run_manifest.json",
        "verification": "runs/pilot/1000/verification.jsonl",
        "comparison": "runs/pilot/1000/evals/verifier_report.json",
        "ranking": "runs/pilot/1000/ranking.csv",
        "inspection": "evals/pilot_inspection_report.json",
        "synthetic": "evals/synthetic-live/v5-live-001/safety_report.json",
        "cost_snapshot": "validation/dashboard_evaluation_audit_v6.json",
        "text_exposure_audit": "evals/audit-v6/audit_summary.json",
    }
    files = {role: _resolve(root, path) for role, path in paths.items()}
    bundle = load_run(directory, skip_evaluation=True)
    summary, records = bundle.summary, bundle.records
    if (bundle.run_id != FROZEN_RUN_ID or summary.get("label_config") != FROZEN_LABEL_CONFIG
            or _sha(files["records"]) != FROZEN_RECORDS_SHA256):
        raise ValueError("Frozen run/configuration/records fingerprint mismatch.")
    if len(records) != 1000 or any(r["status"] != "completed" or r["label_config"] != FROZEN_LABEL_CONFIG for r in records):
        raise ValueError("The frozen pilot requires exactly 1,000 completed matching records.")
    if _sha(files["configuration"]) != FROZEN_CONFIGURATION_SHA256:
        raise ValueError("Frozen configuration fingerprint mismatch.")
    configuration, manifest = _read(files["configuration"]), _read(files["manifest"])
    if manifest["identity"]["label_config"] != FROZEN_LABEL_CONFIG or configuration["prompt_version"] != "pilot-v5-nebius":
        raise ValueError("Frozen configuration identity mismatch.")
    if any(summary["model_settings"][key] != configuration[key] for key in ("models", "providers", "reasoning_effort")):
        raise ValueError("Saved model settings differ from the frozen configuration.")
    audit, inspection = _read(files["cost_snapshot"]), _read(files["inspection"])
    exposure = _read(files["text_exposure_audit"])
    if exposure.get("human_gold") is not False or exposure["golden_text_overlap"]["golden_original_ids_with_development_text_overlap"] != 4:
        raise ValueError("Source-only golden text-exposure summary differs from the reviewed audit.")
    for relative, digest in audit["artifact_sha256"].items():
        if relative in paths.values() and _sha(_resolve(root, relative)) != digest:
            raise ValueError("Frozen audit artifact fingerprint mismatch.")
    if (inspection["configuration"] != FROZEN_LABEL_CONFIG
            or inspection["random_selection"]["records_sha256"] != FROZEN_RECORDS_SHA256
            or inspection["targeted_selection"]["verification_sha256"] != _sha(files["verification"])):
        raise ValueError("Inspection identity or source fingerprint mismatch.")
    indexed = {r["review_id"]: r for r in records}
    verification = _jsonl(files["verification"])
    if len(verification) != 1000 or {v["review_id"] for v in verification} != set(indexed) or any(
        v["status"] != "completed" or v["label_config"] != FROZEN_LABEL_CONFIG or v["blind"] is not True for v in verification
    ):
        raise ValueError("Verification must cover all frozen original IDs with blind completed results.")
    final = [indexed[v["review_id"]] for v in verification]
    initial = [r["initial_prediction"] if r.get("fallback_used") else r for r in final]
    predictions = [v["prediction"] for v in verification]
    n = len(final)
    metrics = []
    for field in FIELDS:
        before = sum(a[field] == b[field] for a, b in zip(initial, predictions))
        after = sum(a[field] == b[field] for a, b in zip(final, predictions))
        metrics.append(dict(id=field, label=field.replace("_", " ").capitalize() + " exact agreement",
            initial_numerator=before, final_numerator=after, denominator=n, unit="fraction",
            initial_value=before / n, final_value=after / n,
            definition="Exact equality with blind verifier predictions; not accuracy against human labels."))
    for field in ("severity", "sentiment"):
        means = [float(sum(Decimal(str(abs(a[field] - b[field]))) for a, b in zip(rows, predictions)) / n)
                 for rows in (initial, final)]
        metrics.append(dict(id=field + "_mean_absolute_difference", label=field.capitalize() + " mean absolute difference",
            initial_numerator=None, final_numerator=None, denominator=n, unit=field + "_points",
            initial_value=means[0], final_value=means[1],
            definition="Mean absolute distance between model outputs across all 1,000 comparable original IDs."))
    rules = [
        ("categorical", "Topic, intent, or severity", lambda a, b: any(a[f] != b[f] for f in FIELDS[:3]),
         "At least one exact topic, intent, or severity difference."),
        ("categorical_or_sentiment_gt_025", "Categorical or sentiment gap >0.25",
         lambda a, b: any(a[f] != b[f] for f in FIELDS[:3]) or abs(a["sentiment"] - b["sentiment"]) > .25,
         "Exact topic/intent/severity difference OR absolute sentiment distance strictly greater than 0.25; engine definition."),
        ("business_exact", "Any exact business-label difference", lambda a, b: any(a[f] != b[f] for f in FIELDS[:4]),
         "Any exact topic, intent, severity, or sentiment difference; excludes the review flag."),
        ("all_exact", "Any exact field, including review flag", lambda a, b: any(a[f] != b[f] for f in FIELDS),
         "Any exact topic, intent, severity, sentiment, or needs_review difference; evaluator definition."),
    ]
    disagreements = [dict(id=key, label=label, count=sum(test(a, b) for a, b in zip(final, predictions)),
                         denominator=n, definition=definition) for key, label, test, definition in rules]
    compared = _read(files["comparison"])
    if compared.get("ground_truth") is not False or compared["verified_count"] != n or compared["comparable_count"] != n:
        raise ValueError("Saved comparison has invalid provenance or denominators.")
    for metric in metrics[:5]:
        if (not math.isclose(compared["field_agreement"][metric["id"]], metric["final_value"], abs_tol=1e-12)
                or not math.isclose(compared["initial_model_field_agreement"][metric["id"]], metric["initial_value"], abs_tol=1e-12)):
            raise ValueError("Saved agreement does not reproduce from records.")
    if compared["disagreement_count"] != disagreements[-1]["count"]:
        raise ValueError("Saved disagreement count does not reproduce.")
    if any(not math.isclose(compared[m["id"]], m["final_value"], abs_tol=1e-12) for m in metrics[5:]):
        raise ValueError("Saved mean differences do not reproduce.")
    cohorts, seen = [], set()
    for name, selection in (("random", inspection["random_selection"]["selection"]),
                             ("targeted", inspection["targeted_selection"]["selection_method"])):
        cases = [c for c in inspection["cases"] if c["sample"] == name]
        ids = {c["review_id"] for c in cases}
        expected_ids = (set(inspection["random_selection"]["review_ids"]) if name == "random" else
                        {x["review_id"] for x in inspection["targeted_selection"]["ids"]})
        if len(cases) != 30 or len(ids) != 30 or ids != expected_ids or seen & ids or not ids <= set(indexed):
            raise ValueError("Inspection cohorts must contain separate matching sets of 30 original IDs.")
        seen |= ids
        for case in cases:
            if case["final_prediction"] != {key: indexed[case["review_id"]][key] for key in FIELDS}:
                raise ValueError("Inspection case labels differ from the frozen records.")
        counts = Counter(c["assessment"] for c in cases)
        flagged = sum(indexed[c["review_id"]]["needs_review"] for c in cases if c["assessment"] == "concern")
        saved = inspection["samples"][name]
        if dict(counts) != saved["assessments"] or flagged != saved["flagged_by_assessment"].get("concern", 0):
            raise ValueError("Inspection summary does not reproduce from saved case assessments.")
        cohorts.append(dict(id=name, label="Seeded random 30" if name == "random" else "Targeted disagreements 30",
            count=30, supported=counts["supported"], concerns=counts["concern"], ambiguous=counts["ambiguous"],
            concerns_flagged=flagged, selection_method=selection))
    if inspection.get("human_gold") is not False or inspection["gate"]["decision"] != "hold_expansion_for_focused_repair_and_remeasurement":
        raise ValueError("Inspection provenance or frozen quality decision differs.")
    synthetic = _read(files["synthetic"])
    if (synthetic.get("synthetic") is not True or synthetic.get("production_records_modified") is not False
            or synthetic["operational"]["frozen_label_config"] != FROZEN_LABEL_CONFIG):
        raise ValueError("Synthetic conformance identity does not match the frozen run.")
    if synthetic["passed"] != (synthetic["operational_passed"] and synthetic["model_behavior_passed"]):
        raise ValueError("Synthetic overall status contradicts its component results.")
    final_rank, verifier_rank = _rank(final), _rank(predictions)
    if final_rank != [{"issue_id": r["issue_id"], "rank": r["rank"], "score": r["priority_score"],
                       "count": r["complaint_count"]} for r in bundle.issues]:
        raise ValueError("Saved ranking does not reproduce from final labels.")
    ranked = {r["issue_id"]: r for r in verifier_rank}
    if set(ranked) - {r["issue_id"] for r in final_rank}:
        raise ValueError("Comparison-only issue needs an explicit contract extension.")
    checks = [
        ("source_identity", "Original source strings and official row hashes",
         sum(row_sha(r) == r["source_sha256"] for r in records)),
        ("quote_substring", "Evidence quote is an exact source substring",
         sum(bool(r["evidence_quote"].strip()) and r["evidence_quote"] in r["review_text"] for r in records)),
        ("literal_entities", "Every extracted entity occurs literally in its source",
         sum(all(e.casefold() in r["review_text"].casefold() for e in r["entities"]) for r in records)),
    ]
    ledger = audit["offline_checks"]["current_local_global_ledger"]
    unique = len({r["review_text"] for r in records})
    fallback = {r["review_text"] for r in records if r.get("fallback_used")}
    numeric = sum(type(r.get("uncertainty_score")) in (int, float) and r.get("confidence_source") != "not_available"
                  for r in records)
    destination = None
    if output_path is not None:
        destination = Path(output_path)
        if not destination.is_absolute():
            destination = root / destination
        destination = destination.resolve()
        if not destination.is_relative_to(root / "evals/dashboard") or destination.suffix != ".json":
            raise ValueError("Public report output must be a JSON file under evals/dashboard.")
        if generated_at is None and destination.exists():
            generated_at = PilotAuditReport.model_validate(_read(destination)).generated_at
    payload = dict(
        schema_version=SCHEMA_VERSION, kind="pilot_audit", run_id=bundle.run_id, label_config=FROZEN_LABEL_CONFIG,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(), records_sha256=FROZEN_RECORDS_SHA256,
        artifact_refs=[dict(path=path, sha256=_sha(files[role]), role=role) for role, path in paths.items()],
        coverage=dict(selected=n, completed=n, unique_texts=unique, exact_text_aliases=n-unique,
                      cache_hits=summary["cache_hits"], compared=n),
        quality_gate=dict(status="hold", summary="Hold expansion for focused repair and remeasurement.",
            reasons=[inspection["gate"]["rationale"], "The live synthetic test passed operational checks but failed model conformance.",
                     "Changing model labels changes the highest-ranked issue; neither ranking establishes human correctness."],
            recommendations_provisional=True),
        human=dict(status="pending_labels", ground_truth_available=False, metrics=[], cohorts=[
            dict(id="mandatory_golden_50", label="Course golden set", expected_count=50, status="pending",
                 sampling_note="Mandatory, label-blind course 50. The source-only audit found 4 original IDs sharing exact text with development; this is not an unseen-text holdout. Answers are not read by this builder."),
            dict(id="fresh_text_disjoint_150", label="Fresh holdout", expected_count=150, status="pending",
                 sampling_note="Planned fresh 150 with unseen text from the conditional frame of 579,702 original IDs; report this conditional sampling frame separately.")],
            interpretation="The planned human evaluation totals 200 (golden 50 plus fresh 150). These cohorts are not pooled as a representative sample. No human worksheet or answer fields were read; this publication contains no human metrics."),
        model_comparison=dict(status="compared", answer_blind=True, ground_truth=False,
            shared_fallback_verifier_model=(configuration["models"]["fallback"] == configuration["models"]["verify"]
                                           and configuration["providers"]["fallback"] == configuration["providers"]["verify"]),
            verifier_provider=configuration["providers"]["verify"], verifier_model=configuration["models"]["verify"],
            metrics=metrics, disagreements=disagreements),
        routing=dict(numeric_signal_available=numeric, confidence_calibrated=False,
            initial_flagged=sum(r["needs_review"] for r in initial), final_flagged=sum(r["needs_review"] for r in final),
            fallback_count=len(fallback), fallback_cap=math.floor(unique * configuration["fallback_fraction"]),
            unique_text_denominator=unique,
            interpretation="Flags combine model ambiguity and deterministic checks, not calibrated error probabilities. The configured 0.6 Jev confidence threshold does not apply to Lightning, which supplied no numeric confidence. Fallback and verifier share a model; improved agreement is not proof of correction."),
        inspection=dict(reviewer_type="ai_assisted", ground_truth=False, cohorts=cohorts,
            interpretation="AI-assisted qualitative review. Random and deliberately targeted cases have different selection mechanisms; do not pool them into an accuracy estimate. Ambiguous is separate from concern."),
        synthetic=dict(status="passed" if synthetic["passed"] else "failed",
            operational_status="passed" if synthetic["operational_passed"] else "failed",
            model_behavior_status="passed" if synthetic["model_behavior_passed"] else "failed",
            case_count=len(synthetic["cases"]), scope=synthetic["scope_limit"], artifact_path=paths["synthetic"]),
        ranking_sensitivity=dict(status="available", ground_truth=False, compared_count=n,
            interpretation="Offline reranking of all 1,000 blind verifier predictions using the same complaint/cancellation membership and severity-sum rule. This is label sensitivity, not a corrected ranking or ground truth; saved production ranking is unchanged.",
            rows=[dict(issue_id=r["issue_id"], final_rank=r["rank"], final_score=r["score"],
                       comparison_rank=ranked.get(r["issue_id"], {}).get("rank"),
                       comparison_score=ranked.get(r["issue_id"], {}).get("score", 0)) for r in final_rank]),
        structural=dict(status="passed" if all(value == n for _, _, value in checks) else "failed",
            checks=[dict(id=key, label=label, passed_count=value, total=n) for key, label, value in checks],
            semantic_support_established=False),
        cost_snapshot=dict(as_of=ledger["captured_at"], source=paths["cost_snapshot"],
            known_usd=float(ledger["spent_usd"]), unknown_hold_usd=float(ledger["unknown_charge_hold_usd"]),
            reserved_usd=float(ledger["reserved_usd"]), committed_usd=float(ledger["committed_usd"]),
            attempts=ledger["attempts"], basis="nominal_usage_reprice", scope="project_snapshot"),
        limitations=[
            "Model agreement is not human accuracy; blind answers can still share model errors.",
            "Structural validity and exact source quotations do not establish semantic support or entity recall.",
            "Qualitative inspection is AI-assisted; its targeted cohort is not representative.",
            "The cost figure is a dated project snapshot at nominal saved rates, not a live balance or verified cash purchase.",
            "Human benchmark metrics remain unpublished; human worksheets and answer rows are excluded.",
            "The report was assembled from saved evidence; generated_at is report construction time and cost_snapshot.as_of is the earlier ledger observation time.",
        ])
    payload["report_id"] = _report_id(payload)
    report = PilotAuditReport.model_validate(payload)
    if destination is not None:
        serialized = report.model_dump_json(indent=2) + "\n"
        if destination.exists():
            if destination.read_text(encoding="utf-8") != serialized:
                raise ValueError("A saved evaluation report is immutable; choose a new output filename.")
            return report
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(serialized, encoding="utf-8")
    return report


def publish_evaluation_report(
    report: PilotAuditReport | dict | str | Path, *, database_url: str, project_root: str | Path,
) -> dict:
    """Validate local and database identity, then insert one immutable report.

    Requires an explicit write connection from the caller. No environment lookup,
    credential logging, provider calls, or changes to the current run are performed.
    """
    if isinstance(report, (str, Path)):
        report = _read(Path(report))
    checked = PilotAuditReport.model_validate(report.model_dump() if isinstance(report, PilotAuditReport) else report)
    root = Path(project_root).resolve()
    for source in checked.artifact_refs:
        if _sha(_resolve(root, source.path)) != source.sha256:
            raise ValueError("Publication source fingerprint mismatch.")
    rebuilt = build_pilot_audit("runs/pilot/1000", project_root=root, generated_at=checked.generated_at)
    if checked.model_dump() != rebuilt.model_dump():
        raise ValueError("Public report does not reproduce from its source artifacts.")
    if not database_url:
        raise ValueError("An explicit database_url is required to publish evaluation.")
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    records = _jsonl(root / "runs/pilot/1000/records.jsonl")
    local_summary = _read(root / "runs/pilot/1000/run_summary.json")
    expected_digest = canonical_records_digest(records)
    schema = root / "web/database/evaluation_schema.sql"
    with psycopg.connect(database_url, connect_timeout=15, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(873522106)")
            cursor.execute("SELECT summary FROM spotify_runs WHERE run_id=%s FOR SHARE", (checked.run_id,))
            saved = cursor.fetchone()
            identity_fields = ("run_id", "label_config", "input_sha256", "input_count", "completed",
                               "quarantined", "unique_texts", "cache_hits", "model_settings", "stages")
            if not saved or any(saved["summary"].get(key) != local_summary.get(key) for key in identity_fields):
                raise ValueError("Database run/configuration fingerprint mismatch.")
            columns = ",".join((*SOURCE_FIELDS, "source_sha256", "status", "reason", "topic", "intent",
                "sentiment", "severity", "entities", "evidence_quote", "needs_review", "label_config", "cache_source_id",
                "provenance"))
            cursor.execute(f"SELECT {columns} FROM spotify_reviews WHERE run_id=%s", (checked.run_id,))
            if canonical_records_digest(cursor.fetchall()) != expected_digest:
                raise ValueError("Database source/classification fingerprint mismatch.")
            cursor.execute(schema.read_text(encoding="utf-8"))
            inserted = _insert_immutable(cursor, checked.model_dump(), Jsonb)
    return {"report_id": checked.report_id, "run_id": checked.run_id, "kind": checked.kind,
            "inserted": inserted, "idempotent": not inserted, "validated_records": len(records),
            "canonical_records_sha256": expected_digest, "run_data_modified": False}


def _insert_immutable(cursor, payload: dict, json_adapter) -> bool:
    """Transaction-internal insertion shared with isolated SQL integration tests."""
    cursor.execute("SELECT payload FROM spotify_evaluation_reports WHERE report_id=%s", (payload["report_id"],))
    existing = cursor.fetchone()
    if existing is not None:
        if existing["payload"] != payload:
            raise ValueError("Immutable report_id already exists with different content.")
        return False
    cursor.execute("""INSERT INTO spotify_evaluation_reports
        (report_id,run_id,kind,schema_version,label_config,payload)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (payload["report_id"], payload["run_id"], payload["kind"], payload["schema_version"],
         payload["label_config"], json_adapter(payload)))
    return True
