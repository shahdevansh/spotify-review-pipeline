"""Offline safety tests for the bounded concurrency extension; no inference."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Reuse the isolated, synthetic repository and network-denial fixtures.
from test_model_experiment import (  # noqa: F401
    block_network_and_credentials, experiment_root, frozen,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "experiment_concurrency_under_test", REPO / "tools/run_experiment_concurrency.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_paid_gate_precedes_credentials_and_dispatch(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Unpaid invocation advanced to credentials or execution")
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(probe, "run", forbidden)
    monkeypatch.setattr(sys, "argv", ["run_experiment_concurrency.py", "--root", str(tmp_path),
                                     "--arm", "glm-v6"])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2
    assert "--execute-paid is required" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["output", "cache"])
async def test_existing_condition_refused_before_engine_creation(frozen, monkeypatch, existing):
    root, experiment, _ = frozen
    output = experiment / "runs/glm-v6/concurrency4"
    cache = root / "data" / f"experiment-v6-{experiment.name}-glm-v6-concurrency4.sqlite3"
    if existing == "output":
        output.mkdir(parents=True)
    else:
        cache.write_text("SYNTHETIC EXISTING CACHE")
    def forbidden(*args, **kwargs):
        pytest.fail("Repeated condition attempted to construct an Engine")
    monkeypatch.setattr(probe, "Engine", forbidden)
    with pytest.raises(ValueError, match="Condition already exists"):
        await probe.run(root, experiment, "glm-v6")


@pytest.mark.asyncio
@pytest.mark.parametrize("relative", ["configs/glm-v6.json", "sources.jsonl"])
async def test_changed_frozen_input_or_config_refused_before_engine(frozen, monkeypatch, relative):
    root, experiment, _ = frozen
    path = experiment / relative
    path.write_bytes(path.read_bytes() + b"\n")
    def forbidden(*args, **kwargs):
        pytest.fail("Tampered condition attempted to construct an Engine")
    monkeypatch.setattr(probe, "Engine", forbidden)
    with pytest.raises(ValueError, match="Frozen (configuration|input) changed"):
        await probe.run(root, experiment, "glm-v6")
    assert not (experiment / "runs/glm-v6/concurrency4").exists()


@pytest.mark.asyncio
async def test_four_workers_preserve_panel_frozen_config_and_budget(frozen, monkeypatch):
    root, experiment, manifest = frozen
    observed = {}
    class SyntheticEngine:
        def __init__(self, config, cache, output, *, budget_usd, workers):
            observed.update(config=config, cache=cache, output=output, budget=budget_usd, workers=workers)
        async def enrich(self, rows):
            observed["rows"] = rows
        def finish(self):
            return {"completed": len(observed["rows"]), "input_count": len(observed["rows"]),
                    "requests": 0, "failed_attempts": 0, "api_cost_usd": 0,
                    "wall_seconds": 0, "synthetic": True}
        async def close(self):
            observed["closed"] = True
    monkeypatch.setattr(probe, "Engine", SyntheticEngine)
    result = await probe.run(root, experiment, "glm-v6")
    assert observed["workers"] == 4 and observed["budget"] == .50
    assert observed["config"]["fallback_fraction"] == 0
    assert observed["config"]["max_reviews_by_role"]["enrich"] == 10
    assert observed["config"]["global_budget_usd"] == manifest["budget"]["shared_admission_ceiling_usd"]
    assert observed["config"]["ledger_path"] == str(root / "data/spend.sqlite3")
    assert probe.fingerprint(observed["config"]) == manifest["config_fingerprints"]["glm-v6"]
    assert observed["rows"] == probe.read_jsonl(experiment / "sources.jsonl")
    saved = json.loads((observed["output"] / "condition_manifest.json").read_text())
    assert saved["workers"] == 4 and saved["fallback_disabled"] is True
    assert saved["human_accuracy_claimed"] is False and saved["adaptive_extension"] is True
    assert result["all_inputs_completed"] is True and observed["closed"] is True
