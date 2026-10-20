"""Deterministic, zero-API source ingestion and review cohort selection."""

from __future__ import annotations

import csv
import hashlib
import heapq
import json
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from .models import SOURCE_FIELDS, SourceReview

DEFAULT_SEED = "berkeley-fall-2026-assignment-5-v1"


def canonical(value: Any) -> str:
    """Serialization identical to the supplied checker."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_sha(row: Mapping[str, str] | SourceReview) -> str:
    """Hash the original six strings, in course order, without normalization."""
    if isinstance(row, SourceReview):
        row = row.model_dump()
    values = [row[key] for key in SOURCE_FIELDS]
    if any(not isinstance(value, str) for value in values):
        raise TypeError("row_sha requires original source strings")
    return hashlib.sha256(canonical(values).encode("utf-8")).hexdigest()


def read_reviews(path: str | Path) -> Iterator[dict[str, str]]:
    """Read CSV including multiline text; exclude any added human-label columns."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames
        if not fields or len(set(fields)) != len(fields):
            raise ValueError("Missing or duplicate CSV headers")
        missing = set(SOURCE_FIELDS) - set(fields)
        if missing:
            raise ValueError(f"Missing source columns: {sorted(missing)}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed CSV row at physical line {reader.line_num}")
            original = {key: row[key] for key in SOURCE_FIELDS}
            if not original["review_id"]:
                raise ValueError(f"Missing review_id at physical line {reader.line_num}")
            yield original


def write_reviews(path: str | Path, rows: Iterable[Mapping[str, str]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SOURCE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in SOURCE_FIELDS})
    temporary.replace(path)
    return path


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def profile_csv(path: str | Path) -> dict[str, Any]:
    """Produce the exact public helper profile, including parsed-row digest."""
    ids: set[str] = set()
    months: Counter[str] = Counter()
    ratings: Counter[str] = Counter()
    counts = Counter(records=0, duplicate_review_ids=0, empty_review_text=0, missing_app_version=0)
    content = hashlib.sha256()
    first, last = None, None
    for row in read_reviews(path):
        content.update(bytes.fromhex(row_sha(row)))
        counts["records"] += 1
        counts["duplicate_review_ids"] += row["review_id"] in ids
        ids.add(row["review_id"])
        counts["empty_review_text"] += not row["review_text"].strip()
        counts["missing_app_version"] += not row["app_version"].strip()
        months[row["review_timestamp"][:7]] += 1
        ratings[row["review_rating"]] += 1
        first = min(first, row["review_timestamp"]) if first else row["review_timestamp"]
        last = max(last, row["review_timestamp"]) if last else row["review_timestamp"]
    return {
        "file_sha256": file_sha256(path),
        "parsed_rows_sha256": content.hexdigest(),
        "counts": dict(counts),
        "reviews_by_month": dict(months),
        "reviews_by_rating": dict(ratings),
        "first_review": first,
        "last_review": last,
    }


def verify_manifest(source_dir: str | Path) -> dict[str, Any]:
    """Check every declared distributed file before using any source records."""
    source_dir = Path(source_dir)
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    verified = {}
    for name, expected in manifest["files"].items():
        path = source_dir / name
        if not path.is_file():
            raise ValueError(f"Manifest file missing: {name}")
        size, checksum = path.stat().st_size, file_sha256(path)
        if size != expected["bytes"] or checksum != expected["sha256"]:
            raise ValueError(f"Source checksum/size mismatch: {name}")
        verified[name] = {"bytes": size, "sha256": checksum}
    return {"manifest": manifest, "verified_files": verified}


def select_cohort(
    rows: Iterable[dict[str, str]], target: int, seed: str = DEFAULT_SEED
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    """Lowest hash-ranked nonempty IDs, plus every explicit empty quarantine."""
    if not isinstance(target, int) or isinstance(target, bool) or target < 1:
        raise ValueError("target must be a positive integer")
    seen: set[str] = set()
    distinct: set[str] = set()
    empty_rows: list[dict[str, str]] = []
    # Keep only the selected payloads while profiling unique source text.
    heap: list[tuple[int, str, dict[str, str]]] = []
    nonempty = 0
    for row in rows:
        rid = row["review_id"]
        if rid in seen:
            raise ValueError(f"Duplicate source review_id: {rid}")
        seen.add(rid)
        text = row["review_text"]
        if not text.strip():
            empty_rows.append(row)
            continue
        nonempty += 1
        distinct.add(text)
        rank = int.from_bytes(hashlib.sha256(f"{seed}:{rid}".encode("utf-8")).digest(), "big")
        candidate = (-rank, rid, row)
        if len(heap) < target:
            heapq.heappush(heap, candidate)
        elif rank < -heap[0][0]:
            heapq.heapreplace(heap, candidate)
    if target > nonempty:
        raise ValueError(f"target {target} exceeds {nonempty} nonempty source rows")
    selected = [row for _, _, row in sorted(heap, key=lambda item: (-item[0], item[1]))]
    return selected, empty_rows, {
        "source_records": len(seen),
        "source_nonempty": nonempty,
        "source_empty": len(empty_rows),
        "source_distinct_nonempty_texts": len(distinct),
    }


def prepare(source_dir: str | Path, output_dir: str | Path, target: int = 210000) -> dict[str, Any]:
    """Verify/profile the entire source and save the fixed learning/final cohorts.

    Produces an official-compatible ``ingestion.json``, expanded report,
    checksum/selection manifest, every-source-ID ledger, learning_1000.csv,
    selected_<target>.csv (including all empty texts), and empty_texts.csv.
    Never reads human answer columns into model-ready inputs.
    """
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    validation = verify_manifest(source_dir)
    source_manifest = validation["manifest"]
    full_path = source_dir / "spotify_reviews_18months.csv"
    profile = profile_csv(full_path)
    for key in ("records", "duplicate_review_ids", "empty_review_text", "missing_app_version"):
        if profile["counts"][key] != source_manifest["profile"][key]:
            raise ValueError(f"Full source profile differs from manifest: {key}")
    for key in ("reviews_by_month", "reviews_by_rating"):
        if profile[key] != source_manifest[key]:
            raise ValueError(f"Full source profile differs from manifest: {key}")
    for key in ("first_review", "last_review"):
        if profile[key] != source_manifest["window"][key]:
            raise ValueError(f"Full source profile differs from manifest: {key}")

    seed = source_manifest["samples"]["seed"]
    selected, empty, counts = select_cohort(read_reviews(full_path), target, seed)
    selected_by_id = {row["review_id"]: row for row in selected}
    golden = list(read_reviews(source_dir / "golden_50_to_label.csv"))
    development = list(read_reviews(source_dir / "analysis_10000.csv"))
    learning = development[:1000]
    golden_ids = {row["review_id"] for row in golden}
    development_ids = {row["review_id"] for row in development}
    if golden_ids & development_ids:
        raise ValueError("Golden IDs overlap development inputs")
    if len(learning) != 1000:
        raise ValueError("Expected 1,000 learning records")
    for sample_name, sample in (("golden", golden), ("development", development)):
        for row in sample:
            rid = row["review_id"]
            if rid in selected_by_id and row_sha(row) != row_sha(selected_by_id[rid]):
                raise ValueError(f"{sample_name} source row mismatch: {rid}")
        if target >= len(golden) + len(development) and not {r["review_id"] for r in sample} <= selected_by_id.keys():
            raise ValueError(f"Selection unexpectedly excludes {sample_name} records")
    for filename, expected in (("cost_100.csv", learning[:100]), ("checkpoint_500.csv", learning[:500])):
        if list(read_reviews(source_dir / filename)) != expected:
            raise ValueError(f"Development checkpoint is not a source-exact prefix: {filename}")

    selected_path = write_reviews(output_dir / f"selected_{target}.csv", [*selected, *empty])
    learning_path = write_reviews(output_dir / "learning_1000.csv", learning)
    empty_path = write_reviews(output_dir / "empty_texts.csv", empty)
    ledger_path = output_dir / "source_ledger.csv"
    temporary = ledger_path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["review_id", "source_sha256", "scope", "reason"])
        for row in read_reviews(full_path):
            rid = row["review_id"]
            if not row["review_text"].strip():
                scope, reason = "selected_quarantine", "empty_review_text"
            elif rid in selected_by_id:
                scope, reason = "selected_classification", ""
            else:
                scope, reason = "outside_selected_scope", "deterministic_sampling"
            writer.writerow([rid, row_sha(row), scope, reason])
    temporary.replace(ledger_path)

    selected_unique = len({row["review_text"] for row in selected})
    scope = {
        **counts,
        "target_nonempty": target,
        "selected_input_records": target + len(empty),
        "selected_nonempty_records": target,
        "selected_empty_quarantines": len(empty),
        "selected_distinct_nonempty_texts": selected_unique,
        "selected_exact_text_reuse": target - selected_unique,
        "outside_selected_scope": counts["source_nonempty"] - target,
        "learning_records": len(learning),
        "learning_distinct_texts": len({r["review_text"] for r in learning}),
        "golden_records": len(golden),
        "golden_in_selection": len(golden_ids & selected_by_id.keys()),
        "development_in_selection": len(development_ids & selected_by_id.keys()),
        "maximum_selected_text_characters": max(len(r["review_text"]) for r in selected),
    }
    files = {
        path.name: {"sha256": file_sha256(path), "bytes": path.stat().st_size}
        for path in (selected_path, learning_path, empty_path, ledger_path)
    }
    manifest = {
        "version": "spotify-selected-cohort-v1",
        "source_file": "spotify_reviews_18months.csv",
        "source_sha256": profile["file_sha256"],
        "source_verified_files": validation["verified_files"],
        "selection": {
            "seed": seed,
            "method": "Lowest SHA-256(seed + ':' + review_id) among nonempty original reviews; all source empty texts appended",
            "ordering": "Ascending selection hash, followed by empty rows in original source order",
            "human_labels_used": False,
        },
        "scope": scope,
        "files": files,
    }
    _write_json(output_dir / "ingestion.json", profile)
    _write_json(output_dir / "ingestion_report.json", {"profile": profile, "scope": scope, "manifest_checks": "passed"})
    _write_json(output_dir / "data_manifest.json", manifest)
    return {
        "source_dir": str(source_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "paths": {
            "selected": str(selected_path.resolve()),
            "learning": str(learning_path.resolve()),
            "empty_texts": str(empty_path.resolve()),
            "ledger": str(ledger_path.resolve()),
            "ingestion": str((output_dir / "ingestion.json").resolve()),
            "manifest": str((output_dir / "data_manifest.json").resolve()),
        },
        "scope": scope,
    }
