# Pilot inspection report

The full narrative is [Learning quality review](../docs/learning-quality-review.md). Machine-readable evidence is [pilot_inspection_report.json](pilot_inspection_report.json), with all 60 cases in [pilot_inspection.csv](pilot_inspection.csv).

**Decision: hold expansion for a focused repair and remeasurement.**

| Group | Supported | Concern | Ambiguous |
|---|---:|---:|---:|
| Seeded random 30 | 15 | 7 | 8 |
| Targeted disagreement 30 | 4 | 23 | 3 |

Six of seven random concerns were unflagged. All 1,000 source hashes, original fields, full quotes, and literal entities passed integrity checks. Independent verification completed 1,000 records; its agreement is a model comparison, not human accuracy. The isolated human golden 50 remain pending.

The engine records 339 disagreements using topic/intent/severity differences or sentiment distance greater than 0.25. Exact business-field comparison gives 341; including `needs_review` gives 354. These definitions are reconciled in the report.

Offline ranking and numerical claim traceability pass conditional on saved labels. Topic errors contaminate the memo's primary-category evidence; the substantive recommendation remains provisional. No source predictions or memo outputs were edited during inspection.
