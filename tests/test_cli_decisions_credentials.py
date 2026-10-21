"""Offline regression for the documented arbitrary-input hero entrypoint."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spotify_pipeline import cli
from spotify_pipeline.decisions import DecisionsProvider
from spotify_pipeline.engine import validate_config


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("No network calls are permitted in credential validation")

    monkeypatch.setattr("socket.create_connection", blocked)
    monkeypatch.setattr("socket.socket.connect", blocked)


@pytest.fixture
def hero_args():
    return SimpleNamespace(execute_paid=True, config=ROOT / "config/hero.json")


def test_frozen_hero_configuration_accepts_only_its_real_provider_keys(monkeypatch, hero_args):
    available = {"OPENAI_API_KEY": True, "NEBIUS_API_KEY": True}
    monkeypatch.setattr(cli, "_credentials", lambda: available)
    assert DecisionsProvider.env_name == "OPENAI_API_KEY"
    validate_config(json.loads(hero_args.config.read_text()))
    cli._require_paid(hero_args)


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "NEBIUS_API_KEY"])
def test_hero_rejects_each_missing_required_key(monkeypatch, hero_args, missing):
    available = {"OPENAI_API_KEY": True, "NEBIUS_API_KEY": True}
    available[missing] = False
    monkeypatch.setattr(cli, "_credentials", lambda: available)
    with pytest.raises(ValueError, match=f"Configure {missing}.*No calls made"):
        cli._require_paid(hero_args)


def test_hero_reports_both_missing_keys_without_requests(monkeypatch, hero_args):
    monkeypatch.setattr(cli, "_credentials", lambda: {})
    with pytest.raises(ValueError, match="Configure NEBIUS_API_KEY, OPENAI_API_KEY"):
        cli._require_paid(hero_args)


def test_paid_flag_is_checked_before_credentials_or_config(monkeypatch):
    def forbidden():
        raise AssertionError("Credentials must not be read in offline mode")

    monkeypatch.setattr(cli, "_credentials", forbidden)
    with pytest.raises(ValueError, match="Paid execution is disabled"):
        cli._require_paid(SimpleNamespace(execute_paid=False, config="missing.json"))


@pytest.mark.parametrize("change", ["unknown_provider", "unknown_role"])
def test_unknown_provider_or_role_still_rejected(monkeypatch, hero_args, tmp_path, change):
    config = json.loads(hero_args.config.read_text())
    config["providers"]["enrich" if change == "unknown_provider" else "invented_role"] = "invented_provider"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(cli, "_credentials", lambda: {"OPENAI_API_KEY": True, "NEBIUS_API_KEY": True})
    with pytest.raises(ValueError, match="Unsupported provider"):
        cli._require_paid(SimpleNamespace(execute_paid=True, config=path))


def test_engine_still_restricts_decisions_to_enrichment(hero_args):
    config = json.loads(hero_args.config.read_text())
    config["providers"]["verify"] = "decisions"
    config["models"]["verify"] = "gpt-6-luna"
    with pytest.raises(ValueError, match="Unsupported provider 'decisions' for verify"):
        validate_config(config)


@pytest.mark.parametrize("provider,transport,required_key", [
    ("openai", "direct", "OPENAI_API_KEY"),
    ("jev", "direct", "TYPESAFE_API_KEY"),
    ("jev", "vercel_gateway", "VERCEL_TYPESAFE_API_KEY"),
])
def test_existing_provider_credential_requirements_unchanged(monkeypatch, hero_args, tmp_path, provider, transport, required_key):
    config = json.loads(hero_args.config.read_text())
    config["providers"]["enrich"] = provider
    config["jev_transport"] = transport
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(config))
    args = SimpleNamespace(execute_paid=True, config=path)
    available = {"NEBIUS_API_KEY": True, required_key: True}
    monkeypatch.setattr(cli, "_credentials", lambda: available)
    cli._require_paid(args)
    available[required_key] = False
    with pytest.raises(ValueError, match=f"Configure {required_key}"):
        cli._require_paid(args)
