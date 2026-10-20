"""Sealing safety checks using entirely synthetic sources and fake inference."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from test_model_experiment import (  # noqa: F401
    block_network_and_credentials, experiment_root, frozen,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "human_predictions_under_test", REPO / "tools/freeze_human_predictions.py"
)
sealed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sealed)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def refresh_sources_manifest(pack, rows):
    source = pack / "sources.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = json.loads((pack / "sources_manifest.json").read_text())
    manifest.update(
        sources_jsonl=sealed._identity(source),
        parsed_rows_sha256=hashlib.sha256(
            b"".join(bytes.fromhex(sealed.row_sha(row)) for row in rows)
        ).hexdigest(),
        distinct_exact_texts=len({row["review_text"] for row in rows}),
    )
    write_json(pack / "sources_manifest.json", manifest)


@pytest.fixture
def human_pack(frozen):
    root, experiment, manifest = frozen
    target = root / sealed.EXPERIMENT
    target.parent.mkdir(parents=True)
    experiment.rename(target)
    manifest["budget"]["shared_admission_ceiling_usd"] = float(sealed.GLOBAL_CAP)
    for arm in manifest["config_file_hashes"]:
        path = target / "configs" / f"{arm}.json"
        config = json.loads(path.read_text())
        config["global_budget_usd"] = float(sealed.GLOBAL_CAP)
        write_json(path, config)
        manifest["config_file_hashes"][arm] = sealed.digest(path.read_bytes())
        manifest["config_fingerprints"][arm] = sealed.fingerprint(config)
    write_json(target / "manifest.json", manifest)
    pack = root / sealed.SOURCE_PACK
    pack.mkdir(parents=True)
    rows = [dict(review_id=f"synthetic-human-{i}", review_text=f"Synthetic source {i}",
                 review_rating="3", review_likes="0", app_version="synthetic",
                 review_timestamp="2026-01-01") for i in range(200)]
    groups = {"mandatory_golden_50": [row["review_id"] for row in rows[:50]],
              "fresh_text_disjoint_150": [row["review_id"] for row in rows[50:]]}
    write_json(pack / "groups.json", groups)
    source_manifest = {
        "version": "spotify-human-evaluation-sources-v1", "fields": list(sealed.SOURCE_FIELDS),
        "rows": 200, "groups": sealed._identity(pack / "groups.json"),
        "source": {"sha256": "synthetic-full-source-sha256", "bytes": 1},
        "validation": {
            "all_200_exact_text_hashes_match": True,
            "all_200_membership_row_hashes_match": True,
            "exactly_six_original_fields": True, "source_checksum_verified": True,
            "human_answers_read": False, "label_columns_read": False,
        },
        # References must not become input read paths, even if their names look useful.
        "worksheet": {"filename": "DO_NOT_READ_answers.html"},
        "membership": {"filename": "DO_NOT_READ_answers.csv"},
    }
    write_json(pack / "sources_manifest.json", source_manifest)
    refresh_sources_manifest(pack, rows)
    for filename in ("DO_NOT_READ_answers.html", "DO_NOT_READ_answers.csv"):
        (pack / filename).write_text("SYNTHETIC_HUMAN_ANSWER_SECRET")
    return root, pack, rows


def test_paid_gate_before_credentials_plan_or_dispatch(monkeypatch, tmp_path, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Unpaid run reached credentials or inference")
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", forbidden)
    monkeypatch.setattr(sealed, "run", forbidden)
    monkeypatch.setattr(sys, "argv", ["freeze_human_predictions.py", "run",
                                     "--root", str(tmp_path), "--arm", "glm-v6"])
    with pytest.raises(SystemExit) as error:
        sealed.main()
    assert error.value.code == 2
    assert "--execute-paid is required" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_prepare_declares_comparison_without_reading_human_answers(human_pack, monkeypatch):
    root, pack, _ = human_pack
    original = Path.open
    read_names = []
    def guarded(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.parent == pack and "r" in mode:
            assert path.name in {"sources.jsonl", "sources_manifest.json", "groups.json", sealed.PLAN_NAME}
            read_names.append(path.name)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded)
    result = sealed.prepare(root)
    assert result["rows"] == 200
    assert result["budget"]["per_arm_ceiling_usd"] == .5
    assert result["budget"]["shared_admission_ceiling_usd"] == float(sealed.GLOBAL_CAP)
    monkeypatch.setattr(Path, "open", original)
    plan = json.loads((pack / sealed.PLAN_NAME).read_text())
    assert plan["comparison"]["baseline"] == "lightning-v5"
    assert plan["comparison"]["challenger"] == "glm-v6"
    assert plan["metrics"]["primary"]["name"] == "topic_accuracy"
    assert plan["groups"] == sealed.GROUP_COUNTS
    assert plan["controls"]["batch_size"] == 10 and plan["controls"]["workers"] == 1
    assert "SYNTHETIC_HUMAN_ANSWER_SECRET" not in json.dumps(plan)
    assert not (root / sealed.PRIVATE).exists()
    assert set(read_names) == {"sources.jsonl", "sources_manifest.json", "groups.json", sealed.PLAN_NAME}
    with pytest.raises(FileExistsError):
        sealed.prepare(root)


@pytest.mark.parametrize("mutation", ["extra_answer_field", "duplicate_id", "wrong_order", "overlap_text"])
def test_source_allowlist_group_identity_and_order_are_enforced(human_pack, mutation):
    root, pack, rows = human_pack
    if mutation == "extra_answer_field":
        rows[0]["human_topic"] = "SYNTHETIC_ANSWER"
    elif mutation == "duplicate_id":
        rows[0]["review_id"] = rows[1]["review_id"]
    elif mutation == "wrong_order":
        rows[0], rows[50] = rows[50], rows[0]
    else:
        rows[50]["review_text"] = rows[0]["review_text"]
    refresh_sources_manifest(pack, rows)
    with pytest.raises(ValueError):
        sealed.prepare(root)
    assert not (pack / sealed.PLAN_NAME).exists()


def test_duplicate_json_fields_rejected(human_pack):
    root, pack, _ = human_pack
    path = pack / "sources_manifest.json"
    raw = path.read_text()
    path.write_text('{"rows":200,' + raw[1:])
    with pytest.raises(ValueError, match="Duplicate JSON"):
        sealed.prepare(root)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["source", "config", "plan"])
async def test_changed_commitments_stop_before_engine(human_pack, monkeypatch, mutation):
    root, pack, rows = human_pack
    sealed.prepare(root)
    if mutation == "source":
        rows[0]["review_text"] += " CHANGED"
        refresh_sources_manifest(pack, rows)
    elif mutation == "config":
        path = root / sealed.EXPERIMENT / "configs/glm-v6.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = pack / sealed.PLAN_NAME
        plan = json.loads(path.read_text())
        plan["controls"]["workers"] = 4
        write_json(path, plan)
    def forbidden(*args, **kwargs):
        pytest.fail("Changed frozen identity reached Engine")
    monkeypatch.setattr(sealed, "Engine", forbidden)
    with pytest.raises(ValueError):
        await sealed.run(root, "glm-v6", execute_paid=True)
    assert not (root / sealed.PRIVATE).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["partial_arm", "private_symlink"])
async def test_repeat_or_redirected_private_run_refused(human_pack, monkeypatch, tmp_path, existing):
    root, _, _ = human_pack
    sealed.prepare(root)
    if existing == "partial_arm":
        (root / sealed.PRIVATE / "glm-v6").mkdir(parents=True)
    else:
        (root / "private").symlink_to(tmp_path / "redirected")
    def forbidden(*args, **kwargs):
        pytest.fail("Repeated or redirected private run reached Engine")
    monkeypatch.setattr(sealed, "Engine", forbidden)
    with pytest.raises(ValueError):
        await sealed.run(root, "glm-v6", execute_paid=True)


@pytest.mark.asyncio
async def test_callable_also_requires_explicit_paid_flag(human_pack):
    root, _, _ = human_pack
    with pytest.raises(ValueError, match="execute-paid"):
        await sealed.run(root, "glm-v6")


@pytest.mark.asyncio
async def test_private_sealing_preserves_frozen_controls_and_outputs_only_metadata(human_pack, monkeypatch):
    root, pack, rows = human_pack
    prepared = sealed.prepare(root)
    observed = {}
    class SyntheticEngine:
        def __init__(self, config, cache, output, *, budget_usd, workers):
            assert (pack / sealed.PLAN_NAME).is_file()
            assert not cache.exists()
            assert cache.is_relative_to(root / sealed.PRIVATE)
            assert output.is_relative_to(root / sealed.PRIVATE)
            assert budget_usd == .50 and workers == 1
            assert config["fallback_fraction"] == 0
            assert config["max_reviews_by_role"]["enrich"] == 10
            assert config["global_budget_usd"] == float(sealed.GLOBAL_CAP)
            assert config["ledger_path"] == str(root / "data/spend.sqlite3")
            assert sealed.fingerprint(config) == prepared["config_identities"]["glm-v6"]["label_config"]
            cache.write_text("SYNTHETIC PRIVATE CACHE")
            output.mkdir()
            self.output = output
            observed["config"] = config
        async def enrich(self, sources):
            assert sources == rows
            assert all(set(row) == set(sealed.SOURCE_FIELDS) for row in sources)
            (self.output / "enriched.jsonl").write_text("SYNTHETIC_PREDICTION_MUST_STAY_PRIVATE")
        def finish(self):
            return dict(completed=200, requests=20, failed_attempts=0, api_cost_usd=.01,
                        api_cost_complete=False, spending={"unknown_charge_hold_usd": .002},
                        must_not_print="SYNTHETIC_SECRET_EXTRA_SUMMARY")
        async def close(self):
            observed["closed"] = True
    monkeypatch.setattr(sealed, "Engine", SyntheticEngine)
    result = await sealed.run(root, "glm-v6", execute_paid=True)
    assert result["completed"] == 200 and result["all_inputs_completed"]
    assert result["unknown_charge_hold_usd"] == .002
    assert result["prediction_plan_sha256"] == prepared["plan_sha256"]
    assert "SYNTHETIC_PREDICTION" not in json.dumps(result)
    assert "SYNTHETIC_SECRET" not in json.dumps(result)
    assert observed["closed"]
    assert (root / sealed.PRIVATE).stat().st_mode & 0o777 == 0o700
    assert sorted(path.name for path in pack.iterdir()) == [
        "DO_NOT_READ_answers.csv", "DO_NOT_READ_answers.html", "groups.json",
        "prediction_plan.json", "sources.jsonl", "sources_manifest.json",
    ]
    with pytest.raises(ValueError, match="already exists"):
        await sealed.run(root, "glm-v6", execute_paid=True)
