# Blind human evaluation kit

Open **[combined_200.html](combined_200.html)**. It contains the required golden 50 first and 150 additional original reviews. The existing golden worksheet is unchanged.

1. Choose an annotator ID.
2. Label from the text alone using the worksheet rubric.
3. Download JSON after each session; save answers under `private/human-labels/`.
4. Keep answers sealed until the model configuration and predictions are frozen.

All public label fields start blank. Model answers, star ratings, routing and disagreement information are hidden. Optional alternative-label and evidence-support fields are under a collapsed diagnostics section.

| File | Purpose |
|---|---|
| `combined_200.html` / `combined_200_to_label.csv` | Main 200-review worksheet and blank CSV |
| `combined_200_strata.csv` | Required50 versus fresh150 group map |
| `groups.json` | Direct `evaluation_groups` mapping for the offline harness: 50 required IDs and 150 fresh IDs |
| `sources.jsonl` / `sources_manifest.json` | Machine-only input: exactly six original fields for the same 200 IDs, verified against original row hashes; metadata is not displayed in the worksheet |
| `holdout_150.html` / matching CSV | Additional reviews separately |
| `second_annotator_200_option.html` | Independent second labels for 40 reviews: 10 required + 30 fresh |
| `second_annotator_50_option.html` | Independent second labels for 10 required reviews |
| `selection_manifest.json` | Original checksums, exact selection rules, exclusions and exposure counts |
| `*_membership.csv` | Source identity hashes; the selection-hash column is the common base holdout-seed hash |
| `protected_text_hashes.txt` | Reserve these original exact texts from future tuning |
| `rubric.v1.json` | Frozen human rubric |
| `confidence_examples.json` | Hypothetical uncertainty calculations, not model results |
| `kit_integrity.json` | File checksums and preparation validation |

The fresh150 come from **579,702 eligible original IDs** after excluding all development and golden exact texts. They estimate quality for that unseen-text frame. Do not interpret a pooled 200-review score as representative of the full corpus.

The source-only exposure check found four golden IDs sharing development text, including two sharing previously inspected text. All mandatory50 remain in evaluation; exposed and unseen subsets must be reported separately. No human answers were accessed to prepare this kit.

See the [human evaluation protocol](../../docs/human-evaluation-protocol.md) for timing, second annotation, adjudication, evidence support, class denominators and confidence-interval limits.

For final scoring, pass `groups.json` to the harness's `--evaluation-groups` option (or load it as the Python API's `evaluation_groups` argument). Supply the original six-field source rows filtered to those same 200 IDs. Human answer imports and scoring must wait for the authorized, frozen evaluation described in the protocol. The group map contains source IDs only.
