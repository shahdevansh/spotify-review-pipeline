"""Safety properties: these tests use no providers, credentials, or paid calls."""
import argparse
import json

import pytest

from spotify_pipeline.cli import _pilot_stage_ready, _prepare_run, _require_paid, _run, build_parser
from spotify_pipeline.storage import ResultStore, atomic_json, atomic_jsonl


def test_paid_execution_requires_explicit_switch(monkeypatch):
    monkeypatch.setattr("spotify_pipeline.cli._credentials", lambda: pytest.fail("Must not read credentials yet"))
    with pytest.raises(ValueError, match="disabled"):
        _require_paid(argparse.Namespace(execute_paid=False))


def test_missing_credentials_stop_before_provider_initialization(monkeypatch):
    monkeypatch.setattr("spotify_pipeline.cli._credentials",
                        lambda: {"TYPESAFE_API_KEY": False, "OPENAI_API_KEY": False})
    with pytest.raises(ValueError, match="No calls made"):
        _require_paid(argparse.Namespace(execute_paid=True))


@pytest.mark.parametrize("transport,required,other", [
    ("direct", "TYPESAFE_API_KEY", "VERCEL_TYPESAFE_API_KEY"),
    ("vercel_gateway", "VERCEL_TYPESAFE_API_KEY", "TYPESAFE_API_KEY"),
])
def test_jev_credential_matches_selected_transport(tmp_path, monkeypatch, transport, required, other):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"jev_transport": transport}))
    args = argparse.Namespace(execute_paid=True, config=str(config))
    available = {"OPENAI_API_KEY": True, required: True, other: False}
    monkeypatch.setattr("spotify_pipeline.cli._credentials", lambda: available)
    _require_paid(args)
    available.update({required: False, other: True})
    with pytest.raises(ValueError, match=required):
        _require_paid(args)


def test_no_command_does_not_select_paid_execution():
    assert build_parser().parse_args([]).command is None


def test_pilot_expansion_is_bounded_in_parser():
    args = build_parser().parse_args(["pilot"])
    assert args.budget == 1.5
    assert args.execute_paid is False
    assert args.db.endswith("data/pilot_cache.sqlite3")


def identity(tmp_path, **changes):
    return {"input_path": str(tmp_path / "input.csv"), "input_sha256": "synthetic-checksum",
            "label_config": "synthetic-config", "cache_path": str(tmp_path / "cache.sqlite3"),
            "cache_mode": "cold", "verify_count": 10, "workers": 1, **changes}


def test_cold_experiment_rejects_contaminated_cache_without_erasing_it(tmp_path):
    cache = ResultStore(tmp_path / "cache.sqlite3")
    cache.save_task("key", "memo", {"synthetic": True}, "request")
    cache.close()
    with pytest.raises(ValueError, match="empty result"):
        _prepare_run(tmp_path / "cold", identity(tmp_path))
    assert not (tmp_path / "cold" / "run_manifest.json").exists()
    cache = ResultStore(tmp_path / "cache.sqlite3")
    assert cache.task("key")["value"] == {"synthetic": True}
    cache.close()


def test_new_cold_proof_survives_resume_and_input_changes_are_rejected(tmp_path):
    out = tmp_path / "cold"
    manifest, previous = _prepare_run(out, identity(tmp_path))
    assert manifest["empty_cache_at_start"] and previous is None
    cache = ResultStore(tmp_path / "cache.sqlite3")
    cache.save_task("key", "verify", {"synthetic": True}, "request")
    cache.close()
    atomic_json(out / "run_summary.json", {"execution_status": "interrupted", "wall_seconds": 12})
    restored, previous = _prepare_run(out, identity(tmp_path))
    assert restored == manifest
    assert previous["wall_seconds"] == 12
    with pytest.raises(ValueError, match="changed"):
        _prepare_run(out, identity(tmp_path, input_sha256="changed"))


def test_unowned_saved_evidence_cannot_be_relabeled_cold(tmp_path):
    out = tmp_path / "cold"
    atomic_json(out / "run_summary.json", {"synthetic": True})
    with pytest.raises(ValueError, match="without a matching run manifest"):
        _prepare_run(out, identity(tmp_path))


@pytest.mark.parametrize("changes,message", [
    ({"completed": 99, "quarantined": 1}, "incomplete"),
    ({"execution_status": "incomplete", "pending": 1}, "incomplete"),
    ({"api_cost_complete": False}, "unresolved billed usage"),
    ({"global_spending": {"reserved_usd": .01}}, "in-flight reservation"),
    ({"global_spending": {"committed_usd": 19}}, "exceeds the budget"),
    ({"stages": {"verify": {"completed": 9}}}, "incomplete independent verification"),
])
def test_pilot_does_not_expand_after_incomplete_or_unpriced_stage(changes, message):
    result = {"execution_status": "completed", "input_count": 100, "completed": 100,
              "api_cost_complete": True, "stages": {"verify": {"completed": 10}},
              "global_spending": {"unknown_charge_hold_usd": 0, "reserved_usd": 0}}
    with pytest.raises(ValueError, match=message):
        _pilot_stage_ready({**result, **changes}, "100-cold", 10)


def test_pilot_can_expand_with_semantic_disagreements_for_later_inspection():
    _pilot_stage_ready({"execution_status": "completed", "input_count": 100, "completed": 100,
                       "api_cost_complete": True,
                       "stages": {"verify": {"completed": 10, "disagreements": 4}}},
                      "100-cold", 10)


def test_prior_unknown_charges_remain_budgeted_without_invalidating_measured_stage():
    _pilot_stage_ready({"execution_status": "completed", "input_count": 100, "completed": 100,
                       "api_cost_complete": True, "global_budget_usd": 1.5,
                       "global_spending": {"unknown_charge_hold_usd": .02, "committed_usd": .25},
                       "stages": {"verify": {"completed": 10}}},
                      "100-cold", 10)


def test_all_nebius_roles_require_only_nebius_credential(tmp_path, monkeypatch):
    config = tmp_path / "nebius.json"
    config.write_text(json.dumps({"providers": {role: "nebius"
        for role in ("enrich", "fallback", "verify", "group", "memo")}}))
    args = argparse.Namespace(execute_paid=True, config=str(config))
    monkeypatch.setattr("spotify_pipeline.cli._credentials", lambda: {"NEBIUS_API_KEY": True})
    _require_paid(args)
    monkeypatch.setattr("spotify_pipeline.cli._credentials", lambda: {"OPENAI_API_KEY": True})
    with pytest.raises(ValueError, match="NEBIUS_API_KEY"):
        _require_paid(args)


class SyntheticEngine:
    """No network; exercises CLI lifecycle and preservation of measured evidence."""
    created = []

    def __init__(self, config, db_path, run_dir, **kwargs):
        self.store = ResultStore(db_path)
        self.run_dir, self.rows, self.records, self.stages = run_dir, [], [], {}
        self.phase = "initial"
        self.created.append(self)

    async def enrich(self, rows, phase, stop_after):
        self.rows, self.phase = rows, phase
        self.records = [dict(row, status="completed") for row in rows]
        atomic_jsonl(self.run_dir / "records.jsonl", self.records)
        return self.records

    async def verify(self, rows, records, count):
        self.stages["verify"] = {"completed": min(count, len(records))}
        atomic_jsonl(self.run_dir / "verification.jsonl", [])

    async def model_task(self, *args, **kwargs):
        raise AssertionError("Synthetic lifecycle never invokes a provider")

    def finish(self):
        atomic_jsonl(self.run_dir / "calls.jsonl", [])
        result = {"input_count": len(self.rows), "completed": len(self.records),
                  "stages": self.stages, "wall_seconds": 0.01}
        atomic_json(self.run_dir / "run_summary.json", result)
        return result

    async def close(self):
        self.store.close()


@pytest.fixture
def synthetic_cli(tmp_path, monkeypatch):
    from spotify_pipeline.data import write_reviews
    source = tmp_path / "input.csv"
    write_reviews(source, [{"review_id": "synthetic-one", "review_text": "Synthetic text",
                           "review_rating": "1", "review_likes": "0", "app_version": "",
                           "review_timestamp": "2023-01-01"}])
    args = build_parser().parse_args([
        "run", "--execute-paid", "--input", str(source), "--out", str(tmp_path / "cold"),
        "--db", str(tmp_path / "cache.sqlite3"), "--cache-mode", "cold", "--verify-count", "1",
    ])
    SyntheticEngine.created = []
    monkeypatch.setattr("spotify_pipeline.cli._require_paid", lambda args: None)
    monkeypatch.setattr("spotify_pipeline.engine.Engine", SyntheticEngine)
    postprocessed = []
    monkeypatch.setattr("spotify_pipeline.cli._postprocess_run", lambda out, args, result: postprocessed.append(result))

    async def analysis(records, out, model_task):
        atomic_json(out / "issues.json", [])
        atomic_json(out / "recommendations.json", {"synthetic": True})

    monkeypatch.setattr("spotify_pipeline.analysis.run_analysis", analysis)
    return args, postprocessed


@pytest.mark.asyncio
async def test_completed_measurement_is_not_overwritten_by_repeat_command(synthetic_cli):
    from pathlib import Path
    args, postprocessed = synthetic_cli
    first = await _run(args)
    path = Path(args.out) / "run_summary.json"
    unchanged = path.read_bytes()
    second = await _run(args)
    assert first == second and path.read_bytes() == unchanged
    assert len(SyntheticEngine.created) == 1 and len(postprocessed) == 1
    assert first["cache_mode"] == "cold" and first["empty_cache_at_start"]
    assert len(first["input_sha256"]) == 64


@pytest.mark.asyncio
async def test_resume_preserves_prior_elapsed_time_and_marks_resume(synthetic_cli):
    from pathlib import Path
    args, _ = synthetic_cli
    args.stop_after = 0
    first = await _run(args)
    assert first["execution_status"] == "paused"
    saved = Path(args.out) / "run_summary.json"
    previous = json.loads(saved.read_text())
    previous["wall_seconds"] = 12
    atomic_json(saved, previous)
    args.stop_after = None
    result = await _run(args)
    assert result["execution_status"] == "completed"
    assert SyntheticEngine.created[-1].phase == "resume"
    assert result["wall_seconds"] >= 12 and len(result["sessions"]) == 2


@pytest.mark.asyncio
async def test_changed_csv_is_rejected_before_creating_engine(synthetic_cli):
    from pathlib import Path
    args, _ = synthetic_cli
    await _run(args)
    source = Path(args.input)
    source.write_text(source.read_text().replace("Synthetic text", "Changed source text"))
    with pytest.raises(ValueError, match="changed"):
        await _run(args)
    assert len(SyntheticEngine.created) == 1
