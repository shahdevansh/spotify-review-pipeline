# Frozen hero predictions vs. corrected human annotations

Posthoc adjudicated reference agreement; **not blind population accuracy**.

Prediction export coverage: 200,013/200,013 selected rows. Complete selected export.

| Cohort | Field | Explicit labels | In hero cohort | Correct / eligible | Agreement |
|---|---|---:|---:|---:|---:|
| all_annotated_worksheet | topic | 97 | 65 | 48/65 | 73.85% |
| all_annotated_worksheet | intent | 98 | 65 | 54/65 | 83.08% |
| all_annotated_worksheet | severity | 30 | 18 | 5/18 | 27.78% |
| mandatory_golden_50 | topic | 47 | 47 | 33/47 | 70.21% |
| mandatory_golden_50 | intent | 47 | 47 | 41/47 | 87.23% |
| mandatory_golden_50 | severity | 13 | 13 | 4/13 | 30.77% |
| additional_150 | topic | 50 | 18 | 15/18 | 83.33% |
| additional_150 | intent | 51 | 18 | 13/18 | 72.22% |
| additional_150 | severity | 17 | 5 | 1/5 | 20.00% |

- The human reference was corrected after inspecting earlier model predictions, including 43 approved topic changes; this is posthoc adjudicated agreement, not blind accuracy.
- Each field uses only explicitly annotated values. Blank severity, sentiment, and entities are not negative labels and are never imputed.
- Human severity was selectively assigned to functional issues; its score does not estimate severity accuracy for every review.
- Only reference IDs inside the selected hero cohort enter agreement denominators. Outside-cohort references are separately counted; missing/invalid in-cohort predictions count as incorrect for exact agreement.
- Numeric MAE uses valid available predictions only and states its denominator. Selective annotation and small nonrandom subgroups prevent a population-accuracy claim.
- Explicit primary labels are scored; alternative accepted labels and notes are not substituted for the primary label.
- Default-false flags and full-source evidence are reported separately from explicit annotations. Literal quote/entity checks do not establish semantic evidence support.
- Human labels are read only by this offline evaluation after inference; they are not inputs to enrichment, routing, verification, or prompt selection.

The JSON contains field-specific missingness, numeric-error denominators, confusion counts, source checks, and immutable input digests. No review text, IDs, notes, or raw human labels are exported.
