"""Adapter to the course's unmodified a5-audit-v1 export contract."""
from __future__ import annotations

import csv
import ctypes
import os
import sys
import uuid
import hashlib
import json
import shutil
from pathlib import Path

from .analysis import load_records, write_json
from .data import profile_csv

REQUIRED_COPY = ("records.jsonl", "membership.csv", "ranking.csv", "claims.csv",
                 "checkpoint_before.json", "checkpoint_after.json")


def file_sha(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_evidence(source: Path, destination: Path) -> None:
    """Atomically snapshot bytes, using APFS copy-on-write when available.

    A clone has a separate inode: later edits to either file cannot change the
    other snapshot. This avoids both the extra disk allocation of a full copy
    and the mutable aliasing of hard links. Other filesystems retain the same
    byte-for-byte export through an ordinary copy.
    """
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        cloned = False
        if sys.platform == "darwin":
            try:
                clonefile = ctypes.CDLL(None, use_errno=True).clonefile
                clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
                clonefile.restype = ctypes.c_int
                cloned = clonefile(os.fsencode(source), os.fsencode(temporary), 0) == 0
            except (AttributeError, OSError):
                pass
        if not cloned:
            temporary.unlink(missing_ok=True)
            shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def export_grading(run_dir: str | Path, output_dir: str | Path,
                   ingestion_path: str | Path | None = None,
                   source_path: str | Path | None = None,
                   analysis_path: str | Path | None = None) -> dict:
    """Copy real evidence only. Missing checkpoints/calls remain missing, with a report.

    ``analysis_path`` is the exact selected or checkpoint CSV supplied to the run.
    ``source_path`` is always the full input, even for a selected-cohort export.
    Pending records are retained as pending and disclosed, never converted to
    quarantines to manufacture accounted-for coverage.
    """
    source, output = Path(run_dir), Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = source / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    if analysis_path is None:
        candidate = summary.get("input_path") or summary.get("analysis_path")
        if candidate:
            analysis_path = Path(candidate)
    if analysis_path is None or not Path(analysis_path).is_file():
        raise ValueError("Export requires the exact analysis CSV path for its count and byte checksum.")
    analysis_path = Path(analysis_path)
    with analysis_path.open(encoding="utf-8-sig", newline="") as handle:
        analysis_rows = list(csv.DictReader(handle))
    ids = [row["review_id"] for row in analysis_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Analysis CSV contains duplicate review IDs.")
    if ingestion_path is not None:
        ingestion = json.loads(Path(ingestion_path).read_text(encoding="utf-8"))
    elif source_path is not None:
        ingestion = profile_csv(source_path)
    else:
        raise ValueError("Export requires a full-source ingestion.json or the full source CSV.")
    write_json(output / "run.json", {
        "version": "a5-audit-v1", "analysis_count": len(ids),
        "analysis_sha256": file_sha(analysis_path), "classification_input_fields": ["review_text"],
        "allow_multi_issue": False, "run_id": summary.get("run_id"),
        "scope": "selected analysis input; complete source ingested separately",
        "full_source_count": ingestion["counts"]["records"],
        "input_file": analysis_path.name,
    })
    write_json(output / "ingestion.json", ingestion)
    copied, missing = [], []
    for name in REQUIRED_COPY:
        candidate = source / name
        if name.endswith(".jsonl") and not candidate.exists():
            candidate = source / (name + ".gz")
        if candidate.exists():
            destination = output / candidate.name
            if candidate.resolve() != destination.resolve():
                _copy_evidence(candidate, destination)
            copied.append(candidate.name)
        else:
            missing.append(name)
    calls_path = source / "evidence_calls.jsonl"
    if not calls_path.exists():
        calls_path = source / "calls.jsonl"
    if calls_path.exists():
        if calls_path.resolve() != (output / "calls.jsonl").resolve():
            _copy_evidence(calls_path, output / "calls.jsonl")
        copied.append("calls.jsonl")
    else:
        missing.append("calls.jsonl")
    record_path = output / "records.jsonl"
    if not record_path.exists():
        record_path = output / "records.jsonl.gz"
    records = load_records(record_path) if record_path.exists() else []
    exported_ids = [row.get("review_id") for row in records]
    report = {
        "status": "exported" if not missing else "incomplete_evidence",
        "copied_files": copied, "missing_files": missing,
        "analysis_count": len(ids), "exported_records": len(records),
        "completed": sum(row.get("status") == "completed" for row in records),
        "quarantined": sum(row.get("status") == "quarantined" for row in records),
        "pending": sum(row.get("status") == "pending" for row in records),
        "missing_ids": sorted(set(ids) - set(exported_ids)),
        "foreign_ids": sorted(set(exported_ids) - set(ids)),
        "duplicate_id_count": len(exported_ids) - len(set(exported_ids)),
        "calls_source": calls_path.name if calls_path.exists() else None,
        "limitations": [
            "Export is not an audit pass; run the supplied unmodified check_submission.py.",
            "Historical evidence calls are used when available; incremental run costs remain in the run's calls.jsonl.",
            "No recovery snapshots, calls, labels, or usage were synthesized by the export adapter.",
        ],
    }
    # Keep diagnostic reports outside grading so the submitted directory remains compact.
    write_json(source / "grading_export_report.json", report)
    return report
