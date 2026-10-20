"""Synthetic billing fixtures only; no credentials or API calls."""
import csv
import json
from pathlib import Path

import pytest

from spotify_pipeline.cost import calculate_cost, load_rates, price_call

RATES = Path(__file__).parents[1] / "config" / "rates.csv"


def write_run(tmp_path, calls, summary=None, records=None):
    path = tmp_path / "calls.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in calls))
    if summary is not None:
        (tmp_path / "run_summary.json").write_text(json.dumps(summary))
    if records is not None:
        (tmp_path / "records.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
    return path


def call(request_id, role, ids, *, units=1000, model="jev-1.13.0", provider="typesafe", **extra):
    return {"request_id": request_id, "role": role, "review_ids": ids, "phase": "initial",
            "provider": provider, "model": model, "outcome": "succeeded", "duration_seconds": 1,
            "cache_mode": "cold", "workers": 1, "billing_items": [{"category": "input", "units": units,
            "rate_key": "jev_input" if provider == "typesafe" else "openai_input"}], **extra}


@pytest.fixture
def pilot(tmp_path):
    calls = [call("synthetic-e1", "enrich", ["1"]), call("synthetic-e2", "enrich", ["2"]),
             call("synthetic-v", "verify", ["1", "2"], model="gpt-6-luna", provider="openai"),
             call("synthetic-g", "group", [], model="gpt-6-luna", provider="openai"),
             call("synthetic-m", "memo", [], model="gpt-6-luna", provider="openai")]
    summary = {"input_count": 3, "completed": 3, "unique_texts": 2, "cache_hits": 1, "wall_seconds": 10}
    return write_run(tmp_path, calls, summary)


def test_billing_units_are_disjoint_and_reasoning_not_counted_twice():
    rates = load_rates(RATES)
    row = call("synthetic-openai", "verify", ["1"], provider="openai", model="gpt-6-luna")
    row["billing_items"] = [{"category": "input", "units": 900, "rate_key": "openai_input"},
                            {"category": "cached_input", "units": 100, "rate_key": "openai_cached_input"},
                            {"category": "output", "units": 200, "rate_key": "openai_output"}]
    row["raw_usage"] = {"input_tokens": 1000, "output_tokens": 200, "reasoning_tokens": 50}
    result = price_call(row, rates)
    assert result["api_cost_usd"] == pytest.approx(.000191)
    row["billing_items"].append({"category": "reasoning", "units": 50, "rate_key": "openai_output"})
    with pytest.raises(ValueError, match="Reasoning"):
        price_call(row, rates)


def test_doubling_rates_doubles_api_not_time_or_local(pilot, tmp_path):
    doubled = tmp_path / "double.csv"
    with RATES.open(newline="") as src, doubled.open("w", newline="") as dest:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dest, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row["usd_per_million"] = str(float(row["usd_per_million"]) * 2)
            writer.writerow(row)
    normal = calculate_cost(pilot, RATES, local_compute_usd_per_hour=1)
    double = calculate_cost(pilot, doubled, local_compute_usd_per_hour=1)
    assert double["measurements"]["api_cost_usd"] == pytest.approx(2 * normal["measurements"]["api_cost_usd"])
    assert double["measurements"]["wall_seconds"] == normal["measurements"]["wall_seconds"] == 10
    assert normal["local_compute"] == double["local_compute"]
    for one, two in zip(normal["projections"], double["projections"]):
        assert two["api_cost_usd"] == pytest.approx(2 * one["api_cost_usd"])
        assert one["projected_wall_seconds"] == two["projected_wall_seconds"]


def test_projection_volume_does_not_change_measurements_or_fixed_overhead(pilot):
    one = calculate_cost(pilot, RATES)
    two = calculate_cost(pilot, RATES, selected_reviews=420000, selected_unique_texts=319314)
    assert one["measurements"] == two["measurements"]
    assert one["stages"] == two["stages"]
    for old, new in zip(one["projections"][:4], two["projections"][:4]):
        assert old["stage_api_cost_usd"]["fixed_overhead"] == new["stage_api_cost_usd"]["fixed_overhead"]
        assert new["stage_api_cost_usd"]["enrich"] == 2 * old["stage_api_cost_usd"]["enrich"]
    assert one["projections"][0]["verification_reviews"] == 2100
    assert one["projections"][4]["first_pass_classifications"] == 484189
    assert one["projections"][6]["first_pass_classifications"] == 660609


def test_unknown_usage_is_unknown_with_estimate_not_invented_usage(tmp_path):
    row = call("synthetic-timeout", "enrich", ["1"], units=None, outcome="failed", reserved_usd=.002)
    report = calculate_cost(write_run(tmp_path, [row]), RATES)
    assert report["measurements"]["api_cost_usd"] is None
    assert report["measurements"]["known_api_subtotal_usd"] == 0
    assert report["measurements"]["unknown_cost_calls"] == 1
    assert report["measurements"]["conservative_charge_estimate_usd"] == .002
    assert report["stages"]["enrich"]["categories_with_missing_units"] == ["input"]
    assert report["projections"][0]["api_cost_usd"] is None


def test_unknown_without_reservation_does_not_invent_bound(tmp_path):
    row = call("synthetic-timeout", "enrich", ["1"], billing_items=None, cost_usd=None)
    result = calculate_cost(write_run(tmp_path, [row]), RATES)
    assert result["measurements"]["conservative_charge_estimate_usd"] is None


def test_partial_usage_and_unknown_charge_hold_are_not_double_counted():
    row = call("synthetic-partial", "verify", ["1"], provider="openai", model="gpt-6-luna")
    row["billing_items"].append({"category": "output", "units": None, "rate_key": "openai_output"})
    row["unknown_charge_hold_usd"] = .001
    result = price_call(row, load_rates(RATES))
    assert result["api_cost_usd"] is None
    assert result["known_api_subtotal_usd"] == .0001
    assert result["conservative_charge_estimate_usd"] == .001


def test_missing_rate_is_unknown_and_negative_units_rejected():
    row = call("synthetic-missing-rate", "enrich", ["1"])
    assert price_call(row, {})["api_cost_usd"] is None
    row["billing_items"][0]["units"] = -1
    with pytest.raises(ValueError):
        price_call(row, load_rates(RATES))


def test_summed_overlapping_durations_are_not_wall_time(tmp_path):
    calls = [call("synthetic-1", "enrich", ["1"], duration_seconds=5),
             call("synthetic-2", "enrich", ["2"], duration_seconds=5)]
    report = calculate_cost(write_run(tmp_path, calls), RATES)
    assert report["measurements"]["summed_call_seconds"] == 10
    assert report["measurements"]["wall_seconds"] is None
    assert report["projections"][0]["projected_wall_seconds"] is None


def test_warm_zero_calls_is_not_missing_evidence(tmp_path):
    path = write_run(tmp_path, [], {"input_count": 100, "completed": 100, "cache_hits": 100,
                                    "unique_texts": 100, "cache_mode": "warm", "wall_seconds": 0.2})
    result = calculate_cost(path, RATES)
    assert result["measurements"]["api_cost_usd"] == 0
    assert result["cache_modes"]["warm"]["attempts"] == 0
    assert result["projections"][0]["api_cost_usd"] is None


def test_output_preserves_calls_and_rates(pilot, tmp_path):
    out = tmp_path / "offline"
    report = calculate_cost(pilot, RATES, out)
    assert (out / "pilot_calls.jsonl").read_bytes() == pilot.read_bytes()
    assert (out / "rates.csv").read_bytes() == RATES.read_bytes()
    assert json.loads((out / "report.json").read_text()) == report
    assert "no paid calls" in (out / "report.md").read_text()
    assert (out / "usage.csv").exists()


def test_retries_are_charged_and_not_counted_as_extra_unique_records(tmp_path):
    rows = [call("synthetic-attempt1", "enrich", ["1"], outcome="failed"),
            call("synthetic-attempt2", "enrich", ["1"])]
    result = calculate_cost(write_run(tmp_path, rows), RATES, verification_fraction=0, fallback_fraction=0)
    stage = result["stages"]["enrich"]
    assert stage["attempts"] == 2
    assert stage["unique_review_ids"] == 1
    assert stage["failed_review_ids"] == 0
    assert stage["api_cost_usd"] == .000084


def test_rates_have_unique_keys_and_valid_prices(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text(RATES.read_text() + RATES.read_text().splitlines()[1] + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_rates(bad)


def test_phases_cache_modes_and_fallbacks_separate(tmp_path):
    rows = [call("synthetic-e", "enrich", ["1"]),
            call("synthetic-f", "enrich", ["1"], provider="openai", model="gpt-6-luna", is_fallback=True, phase="resume"),
            call("synthetic-w", "memo", [], provider="openai", model="gpt-6-luna", cache_mode="warm")]
    result = calculate_cost(write_run(tmp_path, rows), RATES, verification_fraction=0)
    assert result["stages"]["fallback"]["attempts"] == 1
    assert result["phases"]["resume"]["attempts"] == 1
    assert result["cache_modes"]["warm"]["attempts"] == 1
    assert result["projections"][0]["stage_api_cost_usd"]["fixed_overhead"] == 0


@pytest.mark.parametrize("usage_source", ["provider_partial", "unknown", "estimated"])
def test_partial_provider_marker_keeps_cost_unknown_even_with_valid_items(tmp_path, usage_source):
    row = call("synthetic-partial-provider", "verify", ["1"], provider="openai", model="gpt-6-luna",
               usage_source=usage_source, cost_usd=None, reserved_usd=.002, unknown_charge_hold_usd=.002)
    row["billing_items"] = [{"category": "output", "units": 200, "rate_key": "openai_output"}]
    result = calculate_cost(write_run(tmp_path, [row]), RATES)
    assert result["measurements"]["api_cost_usd"] is None
    assert result["measurements"]["known_api_subtotal_usd"] == .0001
    assert result["measurements"]["conservative_charge_estimate_usd"] == .002
    assert result["measurements"]["unknown_cost_calls"] == 1


def test_explicit_not_dispatched_zero_is_known_zero(tmp_path):
    row = call("synthetic-not-dispatched", "enrich", ["1"], outcome="failed", billing_items=[],
               usage_source="not_dispatched", cost_usd=0, input_tokens=0, output_tokens=0)
    result = calculate_cost(write_run(tmp_path, [row]), RATES)
    assert result["measurements"]["api_cost_usd"] == 0
    assert result["measurements"]["unknown_cost_calls"] == 0
    assert result["measurements"]["attempts"] == 1
    assert result["stages"]["enrich"]["failed_review_ids"] == 1


def test_contradictory_not_dispatched_marker_does_not_hide_usage():
    row = call("synthetic-contradiction", "enrich", ["1"], usage_source="not_dispatched", cost_usd=0)
    result = price_call(row, load_rates(RATES))
    assert result["api_cost_usd"] is None
    assert result["known_api_subtotal_usd"] == .000042
    assert "inconsistent_not_dispatched_evidence" in result["billing_problems"]


def test_copied_evidence_folder_replays_measurements_portably(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    summary = {"input_count": 2, "completed": 2, "unique_texts": 1, "cache_hits": 1,
               "wall_seconds": 7.25, "cache_mode": "cold", "input_sha256": "synthetic-checksum"}
    records = [{"review_id": "1", "review_text": "synthetic", "status": "completed"},
               {"review_id": "2", "review_text": "synthetic", "status": "completed", "cache_source_id": "1"}]
    calls = [call("synthetic-copy", "enrich", ["1"])]
    path = write_run(source, calls, summary, records)
    export = tmp_path / "portable"
    original = calculate_cost(path, RATES, export)
    assert (export / "run_summary.json").read_bytes() == (source / "run_summary.json").read_bytes()
    assert json.loads((source / "run_summary.json").read_text()) == summary
    replay = calculate_cost(export / "pilot_calls.jsonl", export / "rates.csv", export / "replay")
    assert replay["measurements"] == original["measurements"]
    assert replay["measurements"]["input_sha256"] == "synthetic-checksum"
    assert replay["measurements"]["wall_seconds"] == 7.25
    assert replay["cache_modes"] == original["cache_modes"]
    assert replay["projections"] == original["projections"]
    instructions = (export / "report.md").read_text()
    assert "--calls pilot_calls.jsonl --rates rates.csv --out replay" in instructions
    assert str(source) not in instructions
