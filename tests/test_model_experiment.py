"""Offline tests of experiment admission, freezing and matched comparisons.

All source rows, prior spending and expected answers here are synthetic fixtures.
These tests neither load credentials nor dispatch a model request.
"""
import asyncio
import csv
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from spotify_pipeline.storage import BudgetLedger


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "model_experiment_under_test", REPO / "tools/run_model_experiment.py"
)
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


@pytest.fixture(autouse=True)
def block_network_and_credentials(monkeypatch):
    async def forbidden_async(*args, **kwargs):
        pytest.fail("An offline experiment test attempted provider dispatch")

    def forbidden_sync(*args, **kwargs):
        pytest.fail("An offline experiment test attempted network access")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_async)
    monkeypatch.setattr(httpx.Client, "send", forbidden_sync)
    for name in ("NEBIUS_API_KEY", "OPENAI_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def experiment_root(tmp_path):
    root = tmp_path / "synthetic-repository"
    for name in experiment.FROZEN_CODE:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, destination)
    shutil.copytree(REPO / "prompts", root / "prompts")
    (root / "config").mkdir()
    shutil.copyfile(REPO / "config/nebius-pilot.json", root / "config/nebius-pilot.json")
    rows = [
        dict(review_id=f"synthetic-original-{index}", review_text=f"Synthetic review {index}",
             review_rating="4", review_likes="0", app_version="synthetic",
             review_timestamp="2026-01-01")
        for index in range(1000)
    ]
    rows[2]["review_text"] = "Synthetic golden exact duplicate"
    rows[3]["review_text"] = "Love it 💕"
    source = root / "data/learning_1000.csv"
    write_csv(source, experiment.SOURCE_FIELDS, rows)
    golden_path = root / "data/source/golden_50_to_label.csv"
    write_csv(
        golden_path, ("review_id", "review_text", "human_topic"),
        [
            dict(review_id=rows[1]["review_id"], review_text=rows[1]["review_text"],
                 human_topic="SYNTHETIC_ANSWER_MUST_NEVER_ENTER_MODEL_INPUT"),
            dict(review_id="synthetic-golden-other-id", review_text=rows[2]["review_text"],
                 human_topic="SYNTHETIC_ANSWER_MUST_NEVER_ENTER_MODEL_INPUT"),
        ],
    )
    (root / "data/data_manifest.json").write_text(json.dumps({
        "files": {"learning_1000.csv": {"sha256": experiment.digest(source.read_bytes())}},
        "source_verified_files": {
            "golden_50_to_label.csv": {"sha256": experiment.digest(golden_path.read_bytes())}
        },
    }))
    ledger = BudgetLedger(root / "data/spend.sqlite3")
    ledger.reserve("synthetic-known", "earlier-synthetic-run", .2,
                   global_cap_usd=50, run_cap_usd=1)
    ledger.settle("synthetic-known", .2)
    ledger.reserve("synthetic-unknown", "earlier-synthetic-run", .031,
                   global_cap_usd=50, run_cap_usd=1)
    ledger.settle("synthetic-unknown", None)
    ledger.close()
    return root


@pytest.fixture
def frozen(experiment_root):
    output = experiment_root / "evals/frozen-test"
    manifest = experiment.prepare(experiment_root, output, 200, 3)
    return experiment_root, output, manifest


def test_paid_gate_precedes_credentials_or_execution(monkeypatch, capsys, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("A run without --execute-paid advanced beyond the CLI gate")

    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(experiment, "run_condition", forbidden)
    monkeypatch.setattr(sys, "argv", [
        "run_model_experiment.py", "run", "--root", str(tmp_path),
        "--arm", "lightning-v6",
    ])
    with pytest.raises(SystemExit) as error:
        experiment.main()
    assert error.value.code == 2
    assert "--execute-paid is required" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_prepare_freezes_exact_blinded_source_and_matched_controls(frozen):
    root, output, manifest = frozen
    original = {row["review_id"]: row for row in experiment.read_reviews(root / "data/learning_1000.csv")}
    panel = experiment.read_jsonl(output / "sources.jsonl")
    assert len(panel) == 200
    assert all(row == original[row["review_id"]] for row in panel)
    assert all(set(row) == set(experiment.SOURCE_FIELDS) for row in panel)
    assert "synthetic-original-1" not in {row["review_id"] for row in panel}
    assert "Synthetic golden exact duplicate" not in {row["review_text"] for row in panel}
    assert all(manifest["source_record_hashes"][row["review_id"]] == experiment.row_sha(row)
               for row in panel)
    assert manifest["selection"]["golden_answers_read"] is False
    assert manifest["human_accuracy_claimed"] is False
    assert manifest["production_promotion"] is False
    assert manifest["budget"]["shared_admission_ceiling_usd"] == pytest.approx(3.231)
    assert manifest["budget"]["per_condition_ceiling_usd"] == .5
    assert experiment.ledger_snapshot(root / "data/spend.sqlite3") == manifest["budget"]["before"]
    configs = [
        json.loads((output / "configs" / f"{arm}.json").read_text())
        for arm in experiment.ARMS
    ]
    assert len(configs) == 5
    for config in configs:
        assert config["fallback_fraction"] == 0
        assert config["max_reviews_per_request"] == 10
        assert config["max_reviews_by_role"]["enrich"] == 10
        assert config["max_output_tokens"] == 6000
        assert config["global_budget_usd"] == pytest.approx(3.231)
        assert config["ledger_path"] == str(root / "data/spend.sqlite3")
        assert "SYNTHETIC_ANSWER_MUST_NEVER_ENTER_MODEL_INPUT" not in json.dumps(config)
    assert len(experiment.read_jsonl(output / "stress_sources.jsonl")) == 25
    cases = json.loads((output / "synthetic_cases.json").read_text())
    assert len(cases) == 15 and all(case["business_evidence"] is False for case in cases)


@pytest.mark.parametrize("relative,message", [
    ("data/learning_1000.csv", "verified ingestion manifest"),
    ("data/source/golden_50_to_label.csv", "unchanged supplied golden source"),
])
def test_prepare_rejects_modified_source_or_golden_answers(experiment_root, relative, message):
    target = experiment_root / relative
    target.write_bytes(target.read_bytes() + b"\n")
    output = experiment_root / "evals/must-not-exist"
    with pytest.raises(ValueError, match=message):
        experiment.prepare(experiment_root, output, 200, 3)
    assert not output.exists()


def test_prepare_rejects_duplicate_ids_even_with_updated_checksum(experiment_root):
    source = experiment_root / "data/learning_1000.csv"
    rows = list(experiment.read_reviews(source))
    rows[-1]["review_id"] = rows[0]["review_id"]
    write_csv(source, experiment.SOURCE_FIELDS, rows)
    manifest_path = experiment_root / "data/data_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["learning_1000.csv"]["sha256"] = experiment.digest(source.read_bytes())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="1000 distinct"):
        experiment.prepare(experiment_root, experiment_root / "evals/rejected", 200, 3)


@pytest.mark.parametrize("relative,message", [
    ("sources.jsonl", "Frozen input changed"),
    ("stress_sources.jsonl", "Frozen input changed"),
    ("synthetic_cases.json", "Frozen synthetic expectations changed"),
    ("configs/glm-v6.json", "Frozen configuration changed"),
])
def test_frozen_input_or_config_tampering_fails_closed(frozen, relative, message):
    root, output, _ = frozen
    target = output / relative
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match=message):
        experiment.validate_frozen(root, output)


def test_frozen_implementation_changes_fail_closed(frozen):
    root, output, _ = frozen
    target = root / "src/spotify_pipeline/data.py"
    target.write_bytes(target.read_bytes() + b"\n# synthetic changed source\n")
    with pytest.raises(ValueError, match="Frozen implementation changed"):
        experiment.validate_frozen(root, output)


def test_loaded_module_must_match_frozen_source(monkeypatch, tmp_path):
    changed = tmp_path / "different-engine.py"
    changed.write_text("# synthetic code from the wrong checkout\n")
    expected = experiment.digest((REPO / "src/spotify_pipeline/engine.py").read_bytes())
    monkeypatch.setattr(experiment.importlib, "import_module",
                        lambda name: SimpleNamespace(__file__=str(changed)))
    with pytest.raises(ValueError, match="Executing source differs"):
        experiment.assert_loaded_implementation({"src/spotify_pipeline/engine.py": expected})


def test_executing_script_must_match_frozen_source():
    with pytest.raises(ValueError, match="Executing source differs"):
        experiment.assert_loaded_implementation({"tools/run_model_experiment.py": "0" * 64})


@pytest.mark.parametrize("existing", ["run", "cache"])
def test_existing_condition_or_cache_rejected_before_engine(frozen, monkeypatch, existing):
    root, output, _ = frozen
    arm, condition = "lightning-v6", "matched"
    if existing == "run":
        (output / "runs" / arm / condition).mkdir(parents=True)
    else:
        (root / "data" / f"experiment-v6-{output.name}-{arm}-{condition}.sqlite3").touch()

    def forbidden(*args, **kwargs):
        pytest.fail("Existing evidence reached Engine construction")

    monkeypatch.setattr(experiment, "Engine", forbidden)
    with pytest.raises(ValueError, match="Condition already exists"):
        asyncio.run(experiment.run_condition(root, output, arm, condition))


def test_conditions_use_fresh_caches_and_strip_synthetic_expected_answers(frozen, monkeypatch):
    root, output, _ = frozen
    invocations = []

    class OfflineRecordingEngine:
        def __init__(self, config, cache, run_dir, budget_usd, workers):
            assert not cache.exists()
            assert budget_usd == .5 and workers == 1
            assert config["fallback_fraction"] == 0
            cache.touch()
            self.entry = {"cache": cache, "config": config, "run_dir": run_dir}
            invocations.append(self.entry)

        async def enrich(self, rows):
            self.entry["rows"] = rows
            assert all(set(row) == set(experiment.SOURCE_FIELDS) for row in rows)
            assert "SYNTHETIC_ANSWER_MUST_NEVER_ENTER_MODEL_INPUT" not in json.dumps(rows)

        def finish(self):
            count = len(self.entry["rows"])
            return dict(completed=count, input_count=count, requests=0, failed_attempts=0,
                        api_cost_usd=0, api_cost_complete=True, wall_seconds=0)

        async def close(self):
            pass

    monkeypatch.setattr(experiment, "Engine", OfflineRecordingEngine)
    for arm, condition in [
        ("lightning-v5", "matched"), ("lightning-v6", "matched"),
        ("lightning-v6", "synthetic"), ("lightning-v6", "batch10"),
        ("lightning-v6", "repeat"), ("lightning-v6", "shuffle"),
    ]:
        result = asyncio.run(experiment.run_condition(root, output, arm, condition))
        assert result["all_inputs_completed"] is True
    assert len({entry["cache"] for entry in invocations}) == 6
    assert invocations[0]["rows"] == invocations[1]["rows"]
    assert len(invocations[2]["rows"]) == 15
    assert invocations[3]["rows"] == invocations[4]["rows"]
    assert invocations[3]["rows"] != invocations[5]["rows"]
    assert {row["review_id"] for row in invocations[3]["rows"]} == {
        row["review_id"] for row in invocations[5]["rows"]
    }


def test_incomplete_condition_exits_nonzero(monkeypatch, tmp_path):
    async def incomplete(*args, **kwargs):
        return {"all_inputs_completed": False}

    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(experiment, "run_condition", incomplete)
    monkeypatch.setattr(sys, "argv", [
        "run_model_experiment.py", "run", "--root", str(tmp_path),
        "--arm", "lightning-v6", "--execute-paid",
    ])
    with pytest.raises(SystemExit) as error:
        experiment.main()
    assert error.value.code == 2
