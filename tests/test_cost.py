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
            "rate_key": "jev_input" if provider in {"typesafe", "jev"} else "openai_input"}], **extra}


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


def gateway_call(**extra):
    return call("synthetic-gateway", "enrich", ["1"], provider="jev", model="typesafe-ai/jev-1.13.0",
                requested_model="typesafe-ai/jev-1.13.0", transport="vercel_gateway", usage_source="provider",
                cost_usd=.00005, calculated_rate_cost_usd=.000042,
                gateway_billing={"cost": ".000042", "surchargeCost": ".000008", "gatewayCost": ".00005"}, **extra)


def test_gateway_namespace_is_explicit_and_version_exact():
    row = gateway_call()
    rates = load_rates(RATES)
    assert price_call(row, rates)["api_cost_usd"] == .000042
    row["transport"] = "direct"
    assert price_call(row, rates)["api_cost_usd"] is None
    row["requested_model"] = "jev-1.13.0"
    assert price_call(row, rates)["api_cost_usd"] is None
    row["requested_model"] = "typesafe-ai/jev-1.13.0"
    row["transport"] = "vercel_gateway"
    row["model"] = "typesafe-ai/jev-1.14.0"
    assert price_call(row, rates)["api_cost_usd"] is None
    row["model"] = "typesafe-ai/jev-1.13.0"
    row["requested_model"] = "typesafe-ai/jev-1.14.0"
    assert price_call(row, rates)["api_cost_usd"] is None
    row["requested_model"] = "typesafe-ai/jev-1.13.0"
    row["provider"] = "other"
    assert price_call(row, rates)["api_cost_usd"] is None


def test_gateway_nominal_reprice_doubles_but_receipt_is_immutable(tmp_path):
    path = write_run(tmp_path, [gateway_call()])
    doubled = tmp_path / "double.csv"
    with RATES.open(newline="") as src, doubled.open("w", newline="") as dest:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dest, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            row["usd_per_million"] = str(float(row["usd_per_million"]) * 2)
            writer.writerow(row)
    before = calculate_cost(path, RATES)
    after = calculate_cost(path, doubled)
    assert after["measurements"]["api_cost_usd"] == 2 * before["measurements"]["api_cost_usd"]
    assert before["measurements"]["gateway_reported_actual_debit_usd"] == after["measurements"]["gateway_reported_actual_debit_usd"] == .00005
    assert before["measurements"]["gateway_reported_surcharge_usd"] == after["measurements"]["gateway_reported_surcharge_usd"] == .000008
    assert before["stages"]["enrich"]["gateway_nonnegative_uplift_usd"] == .000008


def test_gateway_missing_fee_remains_unknown_and_blocks_budget_decision(pilot):
    calls = [json.loads(line) for line in pilot.read_text().splitlines()]
    gateway = gateway_call()
    gateway["gateway_billing"] = {"cost": ".000042"}
    gateway["cost_usd"] = None
    calls[0] = gateway
    pilot.write_text("".join(json.dumps(c) + "\n" for c in calls))
    result = calculate_cost(pilot, RATES)
    assert result["measurements"]["api_cost_usd"] is not None
    assert result["measurements"]["gateway_reported_actual_debit_usd"] is None
    assert result["measurements"]["gateway_reported_surcharge_usd"] is None
    assert result["measurements"]["gateway_unknown_debit_calls"] == 1
    assert result["projections"][0]["api_cost_usd"] is not None
    assert result["projections"][0]["projected_cost_including_gateway_uplift_usd"] is None
    assert result["projections"][0]["budget_exceeded"] is None


def test_gateway_known_total_does_not_invent_surcharge_breakdown():
    row = gateway_call()
    row["gateway_billing"] = {"gatewayCost": ".00005"}
    result = price_call(row, load_rates(RATES))
    assert result["gateway_reported_actual_debit_usd"] == .00005
    assert result["gateway_reported_surcharge_usd"] is None
    assert result["gateway_nonnegative_uplift_usd"] == .000008


def test_gateway_projected_budget_includes_measured_uplift(pilot):
    calls = [json.loads(line) for line in pilot.read_text().splitlines()]
    calls[0] = gateway_call()
    pilot.write_text("".join(json.dumps(c) + "\n" for c in calls))
    result = calculate_cost(pilot, RATES)
    projection = result["projections"][0]
    assert projection["gateway_uplift_usd"] == pytest.approx(.000008 / 2 * 159657)
    assert projection["projected_cost_including_gateway_uplift_usd"] == pytest.approx(projection["api_cost_usd"] + projection["gateway_uplift_usd"])
    assert projection["budget_exceeded"] is not None


def test_gateway_receipt_cost_plus_surcharge_and_credits_are_not_extrapolated():
    row = gateway_call()
    row["gateway_billing"] = {"cost": ".00003", "surchargeCost": ".000005"}
    result = price_call(row, load_rates(RATES))
    assert result["gateway_reported_actual_debit_usd"] == .000035
    assert result["gateway_actual_debit_basis"] == "cost_plus_surchargeCost"
    assert result["gateway_nonnegative_uplift_usd"] == 0


def test_gateway_jev_detection_keeps_implicit_openai_fallback_separate(tmp_path):
    calls = [gateway_call(), call("synthetic-fallback", "enrich", ["1"], provider="openai", model="gpt-6-luna")]
    result = calculate_cost(write_run(tmp_path, calls), RATES)
    assert result["stages"]["enrich"]["attempts"] == 1
    assert result["stages"]["fallback"]["attempts"] == 1


def test_gateway_known_debit_does_not_resolve_unknown_nominal_or_double_count_hold(pilot):
    calls = [json.loads(line) for line in pilot.read_text().splitlines()]
    gateway = gateway_call()
    gateway["usage_source"] = "unknown"
    gateway["billing_items"] = []
    gateway["reserved_usd"] = .002
    gateway["unknown_charge_hold_usd"] = .002
    calls[0] = gateway
    pilot.write_text("".join(json.dumps(c) + "\n" for c in calls))
    result = calculate_cost(pilot, RATES)
    assert result["measurements"]["api_cost_usd"] is None
    assert result["measurements"]["gateway_reported_actual_debit_usd"] == .00005
    conservative = result["projections"][1]
    assert conservative["api_cost_usd"] is not None  # Separate reservation scenario.
    assert conservative["projected_cost_including_gateway_uplift_usd"] is None
    assert conservative["budget_exceeded"] is None


def nebius_call(model="Qwen/Qwen3-30B-A3B-Instruct-2507", prefix="nebius_qwen30b"):
    return {"request_id": "synthetic-nebius", "role": "enrich", "review_ids": ["1"],
            "provider": "nebius", "model": model, "requested_model": model,
            "transport": "direct", "usage_source": "provider", "outcome": "succeeded",
            "cost_basis": "provider_usage_times_nominal_standard_rates",
            "reported_invoice_cost_usd": None, "credits_used_usd": None, "cash_purchase_usd": None,
            "input_tokens": 1000, "output_tokens": 200,
            "raw_usage": {"prompt_tokens": 1000, "completion_tokens": 200},
            "normalized_usage": {"cached_input_tokens": None, "reasoning_tokens": None},
            "billing_items": [{"category": "input", "units": 1000, "rate_key": prefix + "_input",
                               "input_policy": "all_reported_input_at_standard_rate"},
                              {"category": "output", "units": 200, "rate_key": prefix + "_output"}]}


def test_nebius_unknown_cache_breakdown_bills_total_at_public_rate(tmp_path):
    row = nebius_call()
    result = price_call(row, load_rates(RATES))
    assert result["api_cost_usd"] == .00016
    assert not result["unknown_cost"]
    assert result["reported_invoice_cost_usd"] is None
    assert result["credits_used_usd"] is None
    assert result["cash_purchase_usd"] is None
    assert row["normalized_usage"]["cached_input_tokens"] is None
    report = calculate_cost(write_run(tmp_path, [row]), RATES)
    assert report["measurements"]["api_cost_usd"] == .00016
    assert report["cash_outlay"]["incremental_cash_purchase_usd"] is None


def test_nebius_reasoning_is_already_in_output_and_cache_discount_not_invented():
    row = nebius_call("openai/gpt-oss-120b", "nebius_gptoss120b")
    row["raw_usage"]["completion_tokens_details"] = {"reasoning_tokens": 150}
    row["raw_usage"]["prompt_tokens_details"] = {"cached_tokens": 900}
    result = price_call(row, load_rates(RATES))
    assert result["api_cost_usd"] == .00027
    assert len(result["billing_items"]) == 2
    assert result["billing_items"][0]["units"] == 1000
    assert result["billing_items"][1]["units"] == 200


def test_nebius_model_id_requires_exact_returned_and_requested_match():
    row = nebius_call()
    row["model"] = "Qwen/Qwen3-30B-A3B-Instruct-2507-fast"
    assert price_call(row, load_rates(RATES))["api_cost_usd"] is None
    row = nebius_call()
    row["requested_model"] = "Qwen/Qwen3-30B-A3B-Instruct-2507-fast"
    assert price_call(row, load_rates(RATES))["api_cost_usd"] is None


def test_nebius_missing_output_remains_unknown_despite_known_input():
    row = nebius_call()
    row["usage_source"] = "provider_partial"
    row["billing_items"] = row["billing_items"][:1]
    row["output_tokens"] = None
    result = price_call(row, load_rates(RATES))
    assert result["api_cost_usd"] is None
    assert result["known_api_subtotal_usd"] == .0001


def test_nebius_rate_edits_change_economic_usage_not_cash_evidence():
    row = nebius_call()
    normal_rates = load_rates(RATES)
    doubled_rates = {key: {**value, "usd_per_million": value["usd_per_million"] * 2}
                     for key, value in normal_rates.items()}
    original = price_call(row, normal_rates)
    doubled = price_call(row, doubled_rates)
    assert doubled["api_cost_usd"] == 2 * original["api_cost_usd"]
    assert original["cash_purchase_usd"] is doubled["cash_purchase_usd"] is None
    assert original["credits_used_usd"] is doubled["credits_used_usd"] is None


def test_verified_nebius_lightning_challenger_uses_exact_catalog_id():
    row = nebius_call("nvidia/Nemotron-3_5-Lightning", "nebius_lightning")
    result = price_call(row, load_rates(RATES))
    assert result["api_cost_usd"] == .000108
    row["model"] = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16"
    assert price_call(row, load_rates(RATES))["api_cost_usd"] is None
