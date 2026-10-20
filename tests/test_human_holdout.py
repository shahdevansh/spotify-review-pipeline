"""Meaningful synthetic checks; these never open actual human answers."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "prepare_human_evaluation", Path(__file__).resolve().parents[1] / "tools/prepare_human_evaluation.py"
)
kit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kit)


def row(review_id, text):
    return dict(zip(kit.SOURCE_FIELDS, [review_id, text, "1", "0", "", "2023-01-01 00:00:00"]))


def test_text_exclusion_including_aliases_and_original_id_sampling():
    source = [row("dev", "shared"), row("alias", "shared"), row("gold", "gold text"),
              row("gold-alias", "gold text"), row("empty", " "),
              row("fresh-a", "duplicate fresh"), row("fresh-b", "duplicate fresh")]
    selected, report = kit.select_holdout(source, [source[0]], [source[2]], count=2, inspected_ids=["dev"])
    assert {r["review_id"] for r in selected} == {"fresh-a", "fresh-b"}
    assert report["counts"]["eligible_original_ids"] == 2
    assert report["counts"]["selected_distinct_texts"] == 1
    assert report["counts"]["excluded_development_priority"] == 2
    assert report["counts"]["excluded_golden_after_development"] == 2
    assert report["counts"]["empty_text_excluded"] == 1


def test_reordering_preserves_selection_and_exact_text_is_not_normalized():
    source = [row("dev", "same"), row("gold", "gold"), row("a", "Same"),
              row("b", "same "), row("c", "different"), row("d", "another")]
    first, _ = kit.select_holdout(source, [source[0]], [source[1]], 3)
    second, _ = kit.select_holdout(reversed(source), [source[0]], [source[1]], 3)
    assert first == second
    assert len(first) == 3


def test_duplicate_foreign_and_mismatched_source_fail():
    source = [row("dev", "dev"), row("gold", "gold"), row("a", "fresh")]
    with pytest.raises(ValueError, match="duplicate"):
        kit.select_holdout(source + [source[2]], source[:1], source[1:2], 1)
    with pytest.raises(ValueError, match="absent"):
        kit.select_holdout(source[1:], source[:1], source[1:2], 1)
    with pytest.raises(ValueError, match="differ"):
        kit.select_holdout(source, [row("dev", "changed")], source[1:2], 1)
    with pytest.raises(ValueError, match="Inspection"):
        kit.select_holdout(source, source[:1], source[1:2], 1, inspected_ids=["foreign"])


def test_exposure_counts_disclosed_without_label_answers_or_text():
    source = [row("dev", "shared"), row("gold", "shared"), row("fresh", "fresh")]
    _, report = kit.select_holdout(source, source[:1], source[1:2], 1, inspected_ids=["dev"])
    exposure = report["mandatory_golden_text_exposure"]
    assert exposure["golden_development_id_overlap"] == 0
    assert exposure["golden_ids_with_development_exact_text"] == 1
    assert exposure["golden_ids_with_inspected_development_exact_text"] == 1
    assert "shared" not in kit.canonical(exposure).replace("shared_golden_development_exact_text_clusters", "")


def test_blank_human_projection_and_frozen_output(tmp_path):
    data = kit._csv_bytes([kit.blind_row(row("a", "Source"))],
                          ("review_id", "review_text", "row_sha") + kit.LABEL_FIELDS)
    assert b"review_rating" not in data
    assert b"topic,intent" in data
    assert data.decode().splitlines()[1].endswith("," * len(kit.LABEL_FIELDS))
    path = tmp_path / "frozen.csv"
    kit._write_frozen(path, data)
    kit._write_frozen(path, data)
    with pytest.raises(ValueError, match="Frozen"):
        kit._write_frozen(path, b"changed")


def test_confidence_examples_are_hypothetical_and_numerically_correct():
    examples = kit.confidence_examples()
    assert examples["observed_human_results"] is False
    fifty = examples["examples"][0]
    assert fifty["n"] == 50
    assert fifty["wilson_95_lower"] == pytest.approx(0.786397685625)
    assert fifty["wilson_95_upper"] == pytest.approx(0.956524235069)
    assert fifty["zero_errors_one_sided_95_error_upper"] == pytest.approx(0.0581550791)
