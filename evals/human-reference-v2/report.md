# Human reference and frozen hero predictions

Posthoc adjudicated reference agreement; **not blind population accuracy**.

All 200 worksheet labels are preserved without personal notes or annotator identity. The hero cohort contains 99 worksheet IDs: all 50 golden IDs and 49 additional IDs. The other 101 retain human labels but have null production predictions and are unscored.

| Group | Field | Explicit reference labels | In hero cohort | Correct / eligible | Agreement | MAE |
|---|---|---:|---:|---:|---:|---:|
| all_annotated_worksheet | topic | 97 | 65 | 48/65 | 73.8462% | — |
| all_annotated_worksheet | intent | 98 | 65 | 54/65 | 83.0769% | — |
| all_annotated_worksheet | severity | 30 | 18 | 5/18 | 27.7778% | 1.0555555555555556 |
| all_annotated_worksheet | sentiment | 89 | 59 | 9/59 | 15.2542% | 0.20516949152542374 |
| mandatory_golden_50 | topic | 47 | 47 | 33/47 | 70.2128% | — |
| mandatory_golden_50 | intent | 47 | 47 | 41/47 | 87.2340% | — |
| mandatory_golden_50 | severity | 13 | 13 | 4/13 | 30.7692% | 1.0769230769230769 |
| mandatory_golden_50 | sentiment | 42 | 42 | 6/42 | 14.2857% | 0.20202380952380952 |
| additional_150 | topic | 50 | 18 | 15/18 | 83.3333% | — |
| additional_150 | intent | 51 | 18 | 13/18 | 72.2222% | — |
| additional_150 | severity | 17 | 5 | 1/5 | 20.0000% | 1.0 |
| additional_150 | sentiment | 47 | 17 | 3/17 | 17.6471% | 0.21294117647058822 |

## Interpretation

- The human reference was corrected after inspecting earlier model predictions, including 43 approved topic changes; this is posthoc adjudicated agreement, not blind accuracy.
- Each field uses only explicitly annotated values. Blank severity, sentiment, and entities are not negative labels and are never imputed.
- Human severity was selectively assigned to functional issues; its score does not estimate severity accuracy for every review.
- Only reference IDs inside the selected hero cohort enter agreement denominators. Outside-cohort references are separately counted; missing/invalid in-cohort predictions count as incorrect for exact agreement.
- Numeric MAE uses valid available predictions only and states its denominator. Selective annotation and small nonrandom subgroups prevent a population-accuracy claim.
- Explicit primary labels are scored; alternative accepted labels and notes are not substituted for the primary label.
- Default-false flags and full-source evidence are reported separately from explicit annotations. Literal quote/entity checks do not establish semantic evidence support.
- Human labels are read only by this offline evaluation after inference; they are not inputs to enrichment, routing, verification, or prompt selection.

## Immutable inputs

- Human reference SHA-256: `6629c11019cebc40e1a311d62b99a0b80b347d24bb337440980068972a1bbb16`
- Frozen prediction SHA-256 (uncompressed JSONL): `8c23941a34abf7c09e279cb6dc49f0778638b25cc7e6a2a05f83b30daee4246c`
- Run: `run-07e2cb4b0e3d9be0`
- Classification configuration: `spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a`
