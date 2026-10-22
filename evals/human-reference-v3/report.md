# Golden review set agreement

This report compares the frozen hero predictions with the reviewed golden set and the additional worksheet annotations.

All 200 worksheet records are preserved without personal notes or annotator identity. The hero cohort contains 99 worksheet IDs: all 50 golden IDs and 49 additional IDs. The other 101 records retain human labels but have null production predictions and are unscored.

| Group | Field | Explicit reference labels | In hero cohort | Correct / eligible | Agreement | MAE |
|---|---|---:|---:|---:|---:|---:|
| all_annotated_worksheet | topic | 100 | 68 | 51/68 | 75.0000% | — |
| all_annotated_worksheet | intent | 101 | 68 | 57/68 | 83.8235% | — |
| all_annotated_worksheet | severity | 67 | 55 | 41/55 | 74.5455% | 0.36363636363636365 |
| all_annotated_worksheet | sentiment | 97 | 67 | 10/67 | 14.9254% | 0.20134328358208956 |
| mandatory_golden_50 | topic | 50 | 50 | 36/50 | 72.0000% | — |
| mandatory_golden_50 | intent | 50 | 50 | 44/50 | 88.0000% | — |
| mandatory_golden_50 | severity | 50 | 50 | 40/50 | 80.0000% | 0.3 |
| mandatory_golden_50 | sentiment | 50 | 50 | 7/50 | 14.0000% | 0.1974 |
| additional_150 | topic | 50 | 18 | 15/18 | 83.3333% | — |
| additional_150 | intent | 51 | 18 | 13/18 | 72.2222% | — |
| additional_150 | severity | 17 | 5 | 1/5 | 20.0000% | 1.0 |
| additional_150 | sentiment | 47 | 17 | 3/17 | 17.6471% | 0.21294117647058822 |

## Interpretation

- The human reference was corrected after inspecting earlier model predictions, including 43 approved topic changes.
- Each field uses only explicitly annotated values. Blank severity, sentiment, and entities are not negative labels and are never imputed.
- The completed golden 50 use the course severity rubric for every record; the additional 150 retain sparse original annotations.
- Only reference IDs inside the selected hero cohort enter agreement denominators. Outside-cohort references are separately counted; missing/invalid in-cohort predictions count as incorrect for exact agreement.
- Numeric MAE uses valid available predictions only and states its denominator. Selective annotation and small nonrandom subgroups prevent a population-accuracy claim.
- Explicit primary labels are scored; alternative accepted labels and notes are not substituted for the primary label.
- Default-false flags and full-source evidence are reported separately from explicit annotations. Literal quote/entity checks do not establish semantic evidence support.
- Human labels are read only by this offline evaluation after inference; they are not inputs to enrichment, routing, verification, or prompt selection.

## Immutable inputs

- Human reference SHA-256: `dd95152c33ac420e77d54688af9b0904432100d7824b849489eb17f9ab5dfc21`
- Frozen prediction SHA-256 (uncompressed JSONL): `8c23941a34abf7c09e279cb6dc49f0778638b25cc7e6a2a05f83b30daee4246c`
- Run: `run-07e2cb4b0e3d9be0`
- Classification configuration: `spotify-f84b2a9afdaa455fd81d26077cab1ccebc7a62bb1b46bab461d9ae593bcb584a`

## How the reference was prepared

The reference includes 51 originally missing field values across 40 reviews that were proposed by models and then reviewed and confirmed by the user, including any user edits. Field-level methods are retained in the structured exports. The reference was finalized after earlier model comparisons, so these scores describe agreement on this reviewed set. Frozen hero predictions were not inputs to the draft review or importer.


## Inspect the cases

[Methodology and field definitions](README.md) · [Golden 50 comparison CSV](golden50-comparison.csv) · [All 200 worksheet records CSV](all200-comparison.csv) · [Per-case HTML view](index.html) · [Structured all-200 JSONL](all200-comparison.jsonl)
