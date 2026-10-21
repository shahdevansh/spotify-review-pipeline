"""Synthetic-only checks for compressed hero evidence and offline evaluation."""
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def write_gzip_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
    with gzip.open(str(path) + ".gz", "wb") as handle:
        handle.write(raw)
    return raw


def test_audit_and_checkpoint_accept_compressed_exports(tmp_path, monkeypatch):
    hero = load_tool("run_hero")
    monkeypatch.setattr(hero, "ROOT", tmp_path)
    base = tmp_path / "runs/hero-v1"
    monkeypatch.setattr(hero, "BASE", base)
    out = base / "run"
    write_gzip_jsonl(out / "verification.jsonl", [
        {"status": "completed", "differences": []},
        {"status": "completed", "differences": ["topic"]},
    ])
    report = hero.evaluation(out)
    assert report["topic"]["agreement"] == .5
    assert report["intent"]["agreement"] == 1
    write_json(base / "quality-decision.json", {"candidate_accepted": True})
    before = {"completed_ids": ["a"], "label_config": "frozen"}
    after = {"completed_ids": ["a", "b"], "label_config": "frozen"}
    write_json(base / "candidate-v2/cold100/checkpoint_after.json", before)
    write_json(out / "checkpoint_after.json", after)
    grading = base / "grading"
    write_gzip_jsonl(grading / "records.jsonl", [
        {"review_id": rid, "status": "completed", "label_config": "frozen", "cache_source_id": None}
        for rid in ("a", "b")])
    write_gzip_jsonl(grading / "calls.jsonl", [
        {"role": "enrich", "review_ids": [rid], "phase": phase, "outcome": "succeeded", "label_config": "frozen"}
        for rid, phase in (("a", "initial"), ("b", "resume"))])
    hero.preserve_grading_checkpoint(grading)
    assert json.loads((grading / "checkpoint_before.json").read_text()) == before


def prepare_package_fixture(tmp_path, monkeypatch):
    hero = load_tool("run_hero")
    monkeypatch.setattr(hero, "ROOT", tmp_path)
    base = tmp_path / "runs/hero-v1"
    monkeypatch.setattr(hero, "BASE", base)
    required = {
        "grading": ["run.json", "ingestion.json", "records.jsonl", "calls.jsonl", "membership.csv", "ranking.csv",
                    "claims.csv", "checkpoint_before.json", "checkpoint_after.json"],
        "run": ["evaluation.json", "verification.jsonl", "disagreements.jsonl", "configuration.json", "run_summary.json",
                "recommendations.json", "memo.md", "handoffs/group.input.json", "handoffs/group.output.json",
                "handoffs/memo.input.json", "handoffs/memo.output.json"],
        "": ["checker.json", "database-publication.json", "recovery.cast"],
        "recovery": ["recovery-validation.json", "checkpoint_before.json", "checkpoint_after.json", "calls.jsonl"],
    }
    for directory, names in required.items():
        for name in names:
            path = base / directory / name
            if path.suffix == ".jsonl":
                write_gzip_jsonl(path, [{"synthetic": "café\n音楽"}])
            else:
                write_json(path, {"synthetic": True})
    pilot = tmp_path / "evals/hero-pilot"
    for name in ("cold100/report.json", "cold100/rates.csv", "cold100/pilot_calls.jsonl",
                 "cold100/pilot_records.jsonl", "cold100/run_summary.json", "warm100/report.json", "warm100/run_summary.json"):
        path = pilot / name
        if path.suffix == ".jsonl":
            write_gzip_jsonl(path, [{"synthetic": True}])
        else:
            write_json(path, {"synthetic": True})
    return hero, base


def test_package_preserves_actual_compressed_names_and_required_roots(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    archive = hero.package_evidence()
    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())
        for path in ("grading/records.jsonl.gz", "grading/calls.jsonl.gz", "cost/pilot_calls.jsonl.gz",
                     "cost/pilot_records.jsonl.gz", "evals/hero/verification.jsonl.gz",
                     "evals/hero/disagreements.jsonl.gz", "recovery/calls.jsonl.gz"):
            assert path in names
            assert path.removesuffix(".gz") not in names
            assert json.loads(gzip.decompress(handle.read(path)).splitlines()[0])["synthetic"]
        assert {"handoffs/group.input.json", "handoffs/memo.output.json"} <= names
    (base / "run/verification.jsonl.gz").unlink()
    with pytest.raises(RuntimeError, match="incomplete final evidence"):
        hero.package_evidence()


def test_package_rejects_short_read_without_replacing_last_valid_archive(tmp_path, monkeypatch):
    hero, base = prepare_package_fixture(tmp_path, monkeypatch)
    archive = hero.package_evidence()
    original = archive.read_bytes()
    original_write = zipfile.ZipFile.write

    def short_write(self, filename, arcname=None, *args, **kwargs):
        if arcname == "grading/records.jsonl.gz":
            self.writestr(arcname, b"")
        else:
            original_write(self, filename, arcname, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", short_write)
    with pytest.raises(OSError, match="Evidence read did not match source size"):
        hero.package_evidence()
    assert archive.read_bytes() == original
    assert (base / "grading/records.jsonl.gz").stat().st_size > 0


def test_empty_resident_projection_evidence_fails_before_budget_or_model_access(tmp_path, monkeypatch):
    hero = load_tool("run_hero")
    monkeypatch.setattr(hero, "ROOT", tmp_path)
    monkeypatch.setattr(hero, "BASE", tmp_path / "runs/hero-v1")
    resident = tmp_path / "runtime-evidence/pilot1000-calls.jsonl"
    resident.parent.mkdir(parents=True)
    resident.write_text("")
    # The resident snapshot is authoritative, even when fallback evidence exists.
    write_gzip_jsonl(hero.BASE / "pilot1000/calls.jsonl", [
        {"role": "verify", "review_ids": ["synthetic"], "outcome": "succeeded", "cost_usd": .01}])
    with pytest.raises(RuntimeError, match="Pilot verifier call evidence is empty or unavailable"):
        hero.projection()


def test_sparse_evaluator_preserves_decompressed_prediction_hash_and_annotation_bytes(tmp_path):
    human = load_tool("evaluate_hero_humans")
    sources, labels, predictions = [], [], []
    for i in range(200):
        rid = str(i)
        source = dict(zip(human.SOURCE_FIELDS, (rid, "Spotify café\n音楽", "5", "0", "1", "2026-01-01")))
        sources.append(source)
        labels.append({"review_id": rid, "review_text": source["review_text"], "row_sha": human.source_hash(source),
                       "topic": "other", "intent": "praise", "severity": None, "sentiment": None,
                       "needs_review": False, "ambiguous": False, "entities": None, "evidence_quote": source["review_text"],
                       "annotation_provenance": {"topic": "annotated", "intent": "annotated", "severity": "not_assessed",
                           "sentiment": "not_assessed", "needs_review": "default_false", "ambiguous": "default_false",
                           "entities": "not_assessed", "evidence_quote": "default_full_source"}})
        predictions.append({**source, "source_sha256": human.source_hash(source), "status": "completed",
                            "label_config": "frozen", "topic": "other", "intent": "praise", "severity": 1,
                            "sentiment": .9, "needs_review": False, "entities": ["Spotify"], "evidence_quote": source["review_text"]})
    annotations = tmp_path / "synthetic-annotations.json"
    write_json(annotations, {"annotation_protocol": "human-partial-v3", "labels": labels,
        "source_digest": human.digest([{key: row[key] for key in ("review_id", "review_text", "row_sha")} for row in labels])})
    original = annotations.read_bytes()
    source_path, prediction_path = tmp_path / "sources.jsonl", tmp_path / "predictions.jsonl"
    write_gzip_jsonl(source_path, sources)
    raw = write_gzip_jsonl(prediction_path, predictions)
    selected, golden = tmp_path / "selected.csv", tmp_path / "golden.csv"
    for path, rows in ((selected, sources), (golden, sources[:50])):
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=human.SOURCE_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    arguments = SimpleNamespace(annotations=annotations, source=source_path, selected=selected,
        golden_source=golden, predictions=prediction_path, label_config="frozen", out=tmp_path / "compressed", allow_incomplete=False)
    human.run(arguments)
    compressed = json.loads((arguments.out / "report.json").read_text())
    assert compressed["artifacts"]["prediction_sha256"] == hashlib.sha256(raw).hexdigest()
    assert compressed["artifacts"]["prediction_sha256_scope"] == "uncompressed_jsonl_bytes"
    assert compressed["groups"]["all_annotated_worksheet"]["fields"]["topic"]["exact_agreement"]["denominator"] == 200
    prediction_path.write_bytes(raw)
    arguments.out = tmp_path / "plain"
    human.run(arguments)
    assert json.loads((arguments.out / "report.json").read_text()) == compressed
    assert annotations.read_bytes() == original
