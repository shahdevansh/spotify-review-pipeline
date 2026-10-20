import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from spotify_pipeline.data import profile_csv, read_reviews, row_sha, select_cohort, write_reviews
from spotify_pipeline.models import SOURCE_FIELDS


def synthetic(rid, text="text", **changes):
    row = dict(zip(SOURCE_FIELDS, [rid, text, "5", "0", "", "2023-01-01 00:00:00"]))
    row.update(changes)
    return row


def test_source_hash_is_compact_original_string_list():
    row = synthetic("synthetic-é", " \nCafé 😀\r\n ", review_likes=" 0002 ")
    expected = hashlib.sha256(
        json.dumps([row[key] for key in SOURCE_FIELDS], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert row_sha(row) == expected
    assert row_sha(row) != row_sha(dict(row, review_text=row["review_text"].strip()))
    with pytest.raises(TypeError):
        row_sha(dict(row, review_likes=2))


def test_multiline_csv_round_trip_and_golden_field_exclusion(tmp_path):
    rows = [synthetic("synthetic-1", 'line 1,\n"quoted" line 2'), synthetic("synthetic-2", "  ")]
    csv = write_reviews(tmp_path / "reviews.csv", rows)
    assert list(read_reviews(csv)) == rows
    csv.write_text(csv.read_text().replace("review_timestamp\n", "review_timestamp,human_topic\n").replace(
        "2023-01-01 00:00:00\n", "2023-01-01 00:00:00,billing\n"), encoding="utf-8")
    assert list(read_reviews(csv)) == rows


def test_selection_stable_and_all_empty_rows_retained():
    rows = [synthetic(f"synthetic-{i}", "same" if i % 2 else str(i)) for i in range(15)]
    rows.append(synthetic("synthetic-empty", " \n "))
    selected, empty, counts = select_cohort(rows, 7, seed="test")
    reversed_selected, reversed_empty, reversed_counts = select_cohort(reversed(rows), 7, seed="test")
    assert selected == reversed_selected
    assert empty == reversed_empty
    assert counts == reversed_counts
    assert counts["source_nonempty"] == 15
    assert counts["source_distinct_nonempty_texts"] == 9
    assert len(selected) == 7 and empty[0]["review_id"] == "synthetic-empty"


def test_invalid_csv_duplicate_ids_and_excess_target_fail(tmp_path):
    path = tmp_path / "invalid.csv"
    path.write_text("review_id,review_id\nx,y\n")
    with pytest.raises(ValueError, match="duplicate CSV"):
        list(read_reviews(path))
    with pytest.raises(ValueError, match="Duplicate source"):
        select_cohort([synthetic("same-id"), synthetic("same-id")], 1)
    with pytest.raises(ValueError, match="exceeds"):
        select_cohort([synthetic("synthetic-1")], 2)


def test_profile_matches_official_checker(tmp_path):
    rows = [synthetic("synthetic-1", "É\nx"), synthetic("synthetic-2", " \n "),
            synthetic("synthetic-2", "duplicate ID", app_version=" 1.1 ")]
    path = write_reviews(tmp_path / "reviews.csv", rows)
    official = Path(__file__).parents[1] / "data" / "source" / "check_submission.py"
    if not official.is_file():
        pytest.skip("Official source helper not downloaded")
    spec = importlib.util.spec_from_file_location("official_checker", official)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert profile_csv(path) == module.profile(path)
    assert all(row_sha(row) == module.row_sha(row) for row in rows)
