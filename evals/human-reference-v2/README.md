# Human-reference 200-row grader export

**The user explicitly approved publication of all 200 minimal expected-label, public-source, and frozen-prediction comparisons.** Personal notes and annotator identity remain excluded. This exporter prepares files locally and does not publish them itself.

This contains all 200 worksheet records in original worksheet order, with a separate official golden-50 JSONL subset in golden-file order, source text and row hashes, explicitly allowlisted expected labels and field provenance, frozen hero predictions, and per-case comparisons. No personal notes, alternative-label notes, annotator identity, revision history are exported. The original 200-row reference is unchanged.

- `all200-comparison.jsonl` is the authoritative structured per-case export. `golden50-comparison.jsonl` is the official 50-row subset.
- `all200-comparison.csv` is a flattened equivalent. Label cells are JSON encoded: `null` means unassessed, `false` is a Boolean, and arrays remain arrays.
- `index.html` is an entirely local, static review page with no scripts, analytics, storage, or external requests.
- `aggregate.json` reuses the frozen evaluator's all three group metrics exactly.
- `validation.json` records checksums and independent per-case reconciliation.

This reference was adjudicated after earlier model comparisons, including approved topic corrections. It is **not a blind accuracy test**. Within the mandatory golden 50, topic and intent have 47 explicit labels each; the three missing pairs are not inferred. Across all 200 worksheet records, topic has 97 explicit labels and intent has 98. Severity and sentiment use only explicit labels. A missing entities answer is unannotated, not an empty entity list. User-declared `default_false` flags and `default_full_source` quotes remain visible but are excluded from explicit-label agreement denominators. Quote equality is a literal comparison, not a semantic evidence score. The pipeline does not output a separate ambiguity Boolean; missing ambiguity predictions are invalid under the original evaluator.

The exporter is offline and read-only with respect to all source data. It cannot write model inputs, prompt settings, routing, predictions, or training data. A new reference version must be explicitly supplied with its new SHA; output directories are never overwritten.

Only 99 worksheet IDs are in the hero cohort (50 golden and 49 additional). The other 101 retain their human values but have null production predictions, outside_selected_cohort provenance, and no agreement denominator contribution. They are not counted as missing hero predictions.
