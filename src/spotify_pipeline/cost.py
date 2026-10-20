"""Offline replay of saved billing evidence; this module never makes API calls.

`calculate_cost` reprices explicit, mutually exclusive `billing_items` using CSV
rates. Missing usage is unknown, not free. Reservations are estimates, not bills.
Sibling run_summary.json and records.jsonl provide optional measurement context.
Changing projection volumes or rates does not mutate the saved evidence.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

MILLION = Decimal(1_000_000)
RATE_COLUMNS = ("rate_key", "provider", "model", "category", "usd_per_million", "source_url", "as_of")


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a nonnegative finite number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be a nonnegative finite number")
    return result


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def load_rates(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load editable USD-per-million rates; duplicate keys are rejected."""
    rates: dict[str, dict[str, Any]] = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not set(RATE_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError(f"Rates CSV requires columns: {', '.join(RATE_COLUMNS)}")
        for row in reader:
            key = row["rate_key"]
            if not key or key in rates:
                raise ValueError(f"Empty or duplicate rate_key: {key!r}")
            rates[key] = {**row, "usd_per_million": _decimal(row["usd_per_million"], key)}
    return rates


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{number}: expected JSON object")
                rows.append(item)
    return rows


def price_call(call: dict[str, Any], rates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Reprice one attempted call, preserving partial and unknown billing.

    `input` means uncached input, not total provider input. Output already
    includes any billable reasoning tokens; a separate reasoning item is
    rejected to prevent accidental double-counting.
    """
    known = Decimal(0)
    problems: list[str] = []
    priced_items = []
    items = call.get("billing_items")
    usage_source = call.get("usage_source")
    if usage_source in {"provider_partial", "unknown", "estimated"}:
        problems.append(f"incomplete_usage:{usage_source}")
    not_dispatched = (usage_source == "not_dispatched" and call.get("cost_usd") == 0
                      and call.get("input_tokens") in (None, 0)
                      and call.get("output_tokens") in (None, 0)
                      and (items is None or items == []))
    if usage_source == "not_dispatched" and not not_dispatched:
        problems.append("inconsistent_not_dispatched_evidence")
    if not isinstance(items, list) or not items:
        # Explicit no-charge outcomes (e.g. locally rejected calls) are allowed;
        # failed API calls without usage must not silently become free.
        if (usage_source == "not_billed" and call.get("cost_usd") == 0) or not_dispatched:
            items = []
        else:
            items = []
            problems.append("missing_billing_items")
    categories = set()
    for item in items:
        category = str(item.get("category", ""))
        if category in {"reasoning", "reasoning_tokens"}:
            raise ValueError("Reasoning must be included in output, not charged separately")
        if category in categories:
            raise ValueError(f"Duplicate billing category {category!r} in call {call.get('request_id')}")
        categories.add(category)
        rate = rates.get(item.get("rate_key"))
        units = None if item.get("units") is None else _decimal(item["units"], "billing units")
        error = None
        if units is None:
            error = "unknown_units"
        elif rate is None:
            error = "missing_rate"
        elif rate["category"] != category:
            error = "rate_category_mismatch"
        elif call.get("provider") and ({"jev": "typesafe"}.get(rate["provider"], rate["provider"]) != {"jev": "typesafe"}.get(call["provider"], call["provider"])):
            error = "rate_provider_mismatch"
        # Exact model and processing tier are part of the rate key. Aliases are
        # accepted only when the requested model is the configured rate model.
        elif call.get("model") and rate["model"] not in {call["model"], call.get("requested_model")}:
            error = "rate_model_mismatch"
        cost = None if error else units * rate["usd_per_million"] / MILLION
        if cost is not None:
            known += cost
        else:
            problems.append(f"{category}:{error}")
        priced_items.append({**item, "units": _number(units), "cost_usd": _number(cost),
                             "usd_per_million": _number(rate["usd_per_million"]) if rate else None,
                             "source_url": rate["source_url"] if rate else None,
                             "as_of": rate["as_of"] if rate else None, "error": error})
    hold = call.get("unknown_charge_hold_usd")
    reserve = call.get("reserved_usd")
    estimate = None
    if problems and (hold is not None or reserve is not None):
        # Engine holds and reservations both cover the *entire attempt*.
        # Do not add a partially known subtotal again. Neither is a bound.
        estimate = max(known, _decimal(hold, "unknown charge hold") if hold is not None else Decimal(0),
                       _decimal(reserve, "reservation") if reserve is not None else Decimal(0))
    return {"api_cost_usd": None if problems else _number(known),
            "known_api_subtotal_usd": _number(known),
            "conservative_charge_estimate_usd": _number(estimate) if problems else _number(known),
            "unknown_cost": bool(problems), "billing_problems": problems,
            "reported_cost_usd": call.get("cost_usd"), "billing_items": priced_items}


def _totals(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    known = sum((_decimal(row["known_api_subtotal_usd"], "cost") for row in rows), Decimal(0))
    unknown = sum(bool(row["unknown_cost"]) for row in rows)
    estimates = [row["conservative_charge_estimate_usd"] for row in rows]
    return {"api_cost_usd": None if unknown else _number(known),
            "known_api_subtotal_usd": _number(known), "unknown_cost_calls": unknown,
            "conservative_charge_estimate_usd": None if any(x is None for x in estimates) else
            _number(sum((_decimal(x, "charge estimate") for x in estimates), Decimal(0)))}


def _stage(call: dict[str, Any], has_jev: bool) -> str:
    role = call.get("role", "unknown")
    if role in {"fallback", "escalate"} or call.get("is_fallback") or call.get("purpose") == "fallback":
        return "fallback"
    if role == "enrich" and has_jev and call.get("provider") == "openai":
        return "fallback"
    return role


def _cache_mode(call: dict[str, Any], summary: dict[str, Any]) -> str:
    value = call.get("cache_mode", call.get("cold_warm", summary.get("cache_mode", "unspecified")))
    return value if value in {"cold", "warm"} else "unspecified"


def _measure(calls: list[dict[str, Any]], records: list[dict[str, Any]], summary: dict[str, Any],
             priced: list[dict[str, Any]]) -> dict[str, Any]:
    enrich = [c for c in calls if c.get("role") == "enrich"]
    ids = {str(i) for c in enrich for i in c.get("review_ids", [])}
    succeeded = {str(i) for c in enrich if c.get("outcome") == "succeeded" for i in c.get("review_ids", [])}
    record_completed = sum(r.get("status") == "completed" for r in records)
    n = summary.get("input_count", len(records) if records else len(ids))
    complete = summary.get("completed", record_completed if records else len(succeeded))
    wall = summary.get("wall_seconds")
    if wall is not None:
        wall = float(_decimal(wall, "wall_seconds"))
    cost = _totals(priced)
    api = cost["api_cost_usd"]
    return {**cost, "input_count": n, "completed_records": complete,
            "failed_records": summary.get("failed", sum(r.get("status") == "failed" for r in records) if records else len(ids - succeeded)),
            "quarantined_records": summary.get("quarantined", sum(r.get("status") == "quarantined" for r in records)),
            "unique_texts": summary.get("unique_texts", len({r.get("review_text") for r in records if r.get("review_text")}) if records else None),
            "cache_hits": summary.get("cache_hits", sum(bool(r.get("cache_source_id")) for r in records)),
            "attempts": len(calls), "requests": len({c.get("request_id", i) for i, c in enumerate(calls)}),
            "wall_seconds": wall, "wall_time_source": "run_summary" if wall is not None else "unavailable",
            "summed_call_seconds": sum(float(c.get("duration_seconds") or 0) for c in calls),
            "cost_per_1000_inputs_usd": api * 1000 / n if api is not None and n else None,
            "cost_per_completed_record_usd": api / complete if api is not None and complete else None,
            "throughput_inputs_per_second": n / wall if wall else None,
            "measurement_source": "run_summary" if summary else "records_and_calls" if records else "calls_only"}


def _stage_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {str(i) for row in rows for i in row.get("review_ids", [])}
    success = {str(i) for row in rows if row.get("outcome") == "succeeded" for i in row.get("review_ids", [])}
    usage: dict[str, Decimal] = defaultdict(Decimal)
    missing_usage = set()
    for row in rows:
        for item in row["billing_items"]:
            if item.get("units") is None:
                missing_usage.add(item["category"])
            else:
                usage[item["category"]] += _decimal(item["units"], "usage")
    return {**_totals(rows), "attempts": len(rows), "unique_review_ids": len(ids),
            "completed_review_ids": len(success), "failed_review_ids": len(ids - success),
            "providers": sorted({str(r.get("provider", "unknown")) for r in rows}),
            "models": sorted({str(r.get("model", "unknown")) for r in rows}),
            "reasoning_efforts": sorted({str(r.get("reasoning_effort", "unreported")) for r in rows}),
            "prompt_versions": sorted({str(r.get("prompt_version", r.get("label_config", "unreported"))) for r in rows}),
            "schema_versions": sorted({str(r.get("schema_version", "unreported")) for r in rows}),
            "batch_sizes": sorted({len(r.get("review_ids", [])) for r in rows}),
            "worker_counts": sorted({int(r["workers"]) for r in rows if r.get("workers") is not None}),
            "known_billed_units": {k: float(v) for k, v in sorted(usage.items())},
            "categories_with_missing_units": sorted(missing_usage),
            "summed_call_seconds": sum(float(r.get("duration_seconds") or 0) for r in rows)}


def _project(stages: dict[str, dict[str, Any]], measured: dict[str, Any], *, reviews: int, unique: int,
             reuse: bool, verification_fraction: float, fallback_fraction: float,
             conservative_multiplier: float, spending_limit_usd: float, prior_spend_usd: float,
             scenario: str) -> dict[str, Any]:
    enrich = stages.get("enrich", {})
    n = enrich.get("unique_review_ids", 0)
    work = unique if reuse else reviews
    problems = []
    parts = {}
    stage_seconds = {}
    fallback = stages.get("fallback", {})
    observed_fallback = fallback.get("unique_review_ids", 0) / n if n else 0
    fraction = observed_fallback if scenario == "base" else max(observed_fallback, fallback_fraction)
    if observed_fallback > fallback_fraction:
        problems.append("Observed fallback fraction exceeds the configured cap; projection preserves observed spend")
    units = {"enrich": work, "verify": math.ceil(reviews * verification_fraction),
             "fallback": math.ceil(work * fraction)}
    multiplier = 1 if scenario == "base" else conservative_multiplier
    for stage, target in units.items():
        source = stages.get(stage, {})
        source_name = stage
        if stage == "fallback" and target and not source.get("unique_review_ids"):
            source, source_name = stages.get("verify", {}), "verify_proxy"
        denominator = source.get("unique_review_ids", 0)
        metric = "api_cost_usd" if scenario == "base" else "conservative_charge_estimate_usd"
        cost = source.get(metric)
        if target == 0:
            parts[stage], stage_seconds[stage] = 0.0, 0.0
        elif not denominator or cost is None:
            parts[stage], stage_seconds[stage] = None, None
            problems.append(f"{stage}: insufficient measured usage or unpriced calls")
        else:
            parts[stage] = cost / denominator * target * multiplier
            stage_seconds[stage] = source.get("summed_call_seconds", 0) / denominator * target * multiplier
        if source_name != stage:
            problems.append("fallback cost uses measured independent-verifier cost as a proxy")
    fixed = [s for name, s in stages.items() if name not in units]
    fixed_values = [s.get("api_cost_usd" if scenario == "base" else "conservative_charge_estimate_usd") for s in fixed]
    fixed_cost = None if any(v is None for v in fixed_values) else sum(fixed_values)
    parts["fixed_overhead"] = fixed_cost
    if not n:
        problems.append("No measured initial enrichment requests; run the cold pilot first")
    missing_fixed = [name for name in ("group", "memo") if name not in stages]
    if missing_fixed:
        problems.append("Fixed stages not measured: " + ", ".join(missing_fixed))
    total = None if not n or missing_fixed or any(v is None for v in parts.values()) else sum(parts.values())
    # Use measured end-to-end elapsed time, calibrating stage work at the
    # observed concurrency. Do not divide by a desired worker count.
    wall = measured.get("wall_seconds")
    measured_fixed_seconds = sum(s.get("summed_call_seconds", 0) for s in fixed)
    measured_variable_seconds = sum(stages.get(s, {}).get("summed_call_seconds", 0) for s in units)
    projected_wall = None
    if wall is not None and measured_variable_seconds > 0 and all(v is not None for v in stage_seconds.values()):
        # Fixed provider calls are sequential downstream stages. If their
        # reported durations exceed elapsed time, do not invent a calibration.
        if wall >= measured_fixed_seconds:
            calibration = (wall - measured_fixed_seconds) / measured_variable_seconds
            projected_wall = sum(stage_seconds.values()) * calibration + measured_fixed_seconds
        else:
            problems.append("Wall time is shorter than fixed stage durations; runtime projection unavailable")
    return {"scenario": scenario, "reviews": reviews, "distinct_texts": unique,
            "exact_text_reuse": reuse, "first_pass_classifications": work,
            "verification_fraction": verification_fraction, "verification_reviews": units["verify"],
            "fallback_fraction": fraction, "fallback_reviews": units["fallback"],
            "conservative_multiplier": multiplier, "stage_api_cost_usd": parts,
            "api_cost_usd": total, "prior_spend_usd": prior_spend_usd,
            "spend_including_prior_usd": None if total is None else prior_spend_usd + total,
            "budget_exceeded": None if total is None else prior_spend_usd + total > spending_limit_usd,
            "projected_wall_seconds": projected_wall, "limitations": problems}


def calculate_cost(calls_path: str | Path, rates_path: str | Path, output_dir: str | Path | None = None,
                   selected_reviews: int = 210000, selected_unique_texts: int = 159657,
                   full_reviews: int = 660609, full_unique_texts: int = 484189, *,
                   verification_fraction: float = 0.01, fallback_fraction: float = 0.05,
                   spending_limit_usd: float = 18.0, prior_spend_usd: float = 0.0,
                   conservative_multiplier: float = 1.5, output_token_cap: int = 8000,
                   max_workers: int = 16, local_compute_usd_per_hour: float | None = None,
                   empty_text_quarantines: int = 13) -> dict[str, Any]:
    """Recompute saved usage and project selected/full workloads, fully offline.

    Every source call is included in measured totals. Projection baselines omit
    explicitly warm-cache calls, keeping warm/cold measurements separate.
    Rates are USD per million billed units, never assumed token counts. Fixed
    group/memo overhead is included once. Default 1% verification is independent
    of the pilot's deliberately larger validation fraction. Conservative costs
    inflate variable measured unit costs by 1.5; this is a scenario, not a bound.
    """
    for label, count, distinct in (("selected", selected_reviews, selected_unique_texts), ("full", full_reviews, full_unique_texts)):
        if not isinstance(count, int) or not isinstance(distinct, int) or count < 0 or not 0 <= distinct <= count:
            raise ValueError(f"{label}: require integer 0 <= unique_texts <= reviews")
    if not isinstance(empty_text_quarantines, int) or empty_text_quarantines < 0:
        raise ValueError("empty_text_quarantines must be a nonnegative integer")
    if not 0 <= verification_fraction <= 1 or not 0 <= fallback_fraction <= 1:
        raise ValueError("Verification and fallback fractions must be in [0, 1]")
    if conservative_multiplier < 1 or max_workers < 1 or output_token_cap < 1:
        raise ValueError("Invalid conservative multiplier, workers, or output cap")
    _decimal(spending_limit_usd, "spending limit")
    _decimal(prior_spend_usd, "prior spend")
    if local_compute_usd_per_hour is not None:
        _decimal(local_compute_usd_per_hour, "local compute rate")
    path = Path(calls_path)
    calls = _read_jsonl(path)
    rates = load_rates(rates_path)
    summary_path = path.parent / "run_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    record_path = path.parent / ("pilot_records.jsonl" if path.name == "pilot_calls.jsonl" else "records.jsonl")
    records = _read_jsonl(record_path) if record_path.exists() else []
    has_jev = any(c.get("role") == "enrich" and str(c.get("model", "")).startswith("jev-") for c in calls)
    priced = [{**c, **price_call(c, rates), "stage": _stage(c, has_jev), "cache_mode": _cache_mode(c, summary)} for c in calls]
    measurements = _measure(calls, records, summary, priced)
    measurements["input_ids"] = [str(r.get("review_id")) for r in records] if records else None
    measurements["input_sha256"] = summary.get("input_sha256", summary.get("input_checksum"))
    by_phase: dict[str, list] = defaultdict(list)
    by_cache: dict[str, list] = defaultdict(list)
    by_stage: dict[str, list] = defaultdict(list)
    projection_stages: dict[str, list] = defaultdict(list)
    for row in priced:
        by_phase[str(row.get("phase", "unspecified"))].append(row)
        by_cache[row["cache_mode"]].append(row)
        by_stage[row["stage"]].append(row)
        if row["cache_mode"] != "warm":
            projection_stages[row["stage"]].append(row)
    if not priced and summary.get("cache_mode") in {"warm", "cold"}:
        by_cache[summary["cache_mode"]] = []
    stages = {name: _stage_summary(rows) for name, rows in sorted(by_stage.items())}
    saved_stages = summary.get("stages", {})
    for name, stage in stages.items():
        timing = saved_stages.get(name, {}) if isinstance(saved_stages, dict) else {}
        stage["wall_seconds"] = timing.get("wall_seconds") if isinstance(timing, dict) else None
    baseline = {name: _stage_summary(rows) for name, rows in projection_stages.items()}
    projections = []
    for scope, reviews, unique in (("selected", selected_reviews, selected_unique_texts), ("full", full_reviews, full_unique_texts)):
        for reuse in (True, False):
            for scenario in ("base", "conservative"):
                projections.append({"scope": scope, "empty_text_quarantines": empty_text_quarantines,
                    "total_source_rows_in_scope": reviews + empty_text_quarantines,
                    **_project(baseline, measurements, reviews=reviews, unique=unique,
                    reuse=reuse, verification_fraction=verification_fraction, fallback_fraction=fallback_fraction,
                    conservative_multiplier=conservative_multiplier, spending_limit_usd=spending_limit_usd,
                    prior_spend_usd=prior_spend_usd, scenario=scenario)})
    local = None if local_compute_usd_per_hour is None or measurements["wall_seconds"] is None else local_compute_usd_per_hour * measurements["wall_seconds"] / 3600
    report = {"schema_version": "cost-report-v1", "mode": "offline", "currency": "USD",
              "calls_path": str(path), "rates_path": str(rates_path), "measurements": measurements,
              "phases": {k: _stage_summary(v) for k, v in sorted(by_phase.items())},
              "cache_modes": {k: {**_stage_summary(v), "wall_seconds": measurements["wall_seconds"] if summary.get("cache_mode") == k else None} for k, v in sorted(by_cache.items())},
              "stages": stages, "projections": projections,
              "local_compute": {"usd_per_hour": local_compute_usd_per_hour, "estimated_cost_usd": local,
                                "status": "unknown" if local is None else "estimate"},
              "controls": {"spending_limit_usd": spending_limit_usd, "prior_spend_usd": prior_spend_usd,
                           "output_token_cap": output_token_cap, "max_workers": max_workers,
                           "fallback_fraction": fallback_fraction, "verification_fraction": verification_fraction},
              "rates": [{**v, "usd_per_million": float(v["usd_per_million"])} for v in rates.values()],
              "limitations": ["Reservations and charge holds are estimates, not guaranteed cost bounds.",
                              "Unknown usage is excluded from known subtotals, never assumed free; partial/unknown provider markers keep total charges unresolved even when some billing items are present.",
                              "Unknown-charge holds cover entire attempts and are not added again to their known subtotals.",
                              "Summed call durations are not elapsed wall time.",
                              "Runtime projections use measured concurrency and linear workload extrapolation; they are not guarantees.",
                              "Variable unit costs include all logged attempts and retries; fixed downstream overhead is counted once.",
                              "No taxes, hosting charges, or unlogged API calls are inferred.",
                              "Reports should use a single frozen configuration and a single cold run for projection calibration."]}
    if output_dir is not None:
        _write_report(Path(output_dir), report, priced, path, Path(rates_path), record_path)
    return report


def _csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _write_report(out: Path, report: dict[str, Any], priced: list[dict[str, Any]], calls_path: Path,
                  rates_path: Path, record_path: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    call_rows = [{k: row.get(k) for k in ("request_id", "role", "stage", "phase", "cache_mode", "provider", "model", "outcome", "api_cost_usd", "known_api_subtotal_usd", "unknown_cost", "conservative_charge_estimate_usd", "reported_cost_usd", "billing_problems", "duration_seconds")} for row in priced]
    _csv(out / "measured_calls.csv", call_rows, list(call_rows[0]) if call_rows else ["request_id", "api_cost_usd"])
    usage = [{"request_id": row.get("request_id"), "stage": row["stage"], "phase": row.get("phase"),
              "provider": row.get("provider"), "model": row.get("model"), **item} for row in priced for item in row["billing_items"]]
    _csv(out / "usage.csv", usage, None if usage else ["request_id", "category", "units", "rate_key", "cost_usd"])
    _csv(out / "stage_costs.csv", [{"stage": name, **value} for name, value in report["stages"].items()])
    _csv(out / "projections.csv", report["projections"])
    for source, dest in ((calls_path, out / "pilot_calls.jsonl"), (rates_path, out / "rates.csv"),
                         (record_path, out / "pilot_records.jsonl"),
                         (calls_path.parent / "run_summary.json", out / "run_summary.json")):
        if source.exists() and source.resolve() != dest.resolve():
            dest.write_bytes(source.read_bytes())
    m = report["measurements"]
    lines = ["# Offline cost and runtime replay", "", "All amounts are USD; rates are editable per million billed units. This command makes no paid calls.", "",
             f"Measured inputs: {m['input_count']}; completed: {m['completed_records']}; attempted calls: {m['attempts']}.",
             f"Repriced API total: {m['api_cost_usd']}; known subtotal: {m['known_api_subtotal_usd']}; calls with unknown cost: {m['unknown_cost_calls']}.",
             f"End-to-end elapsed seconds: {m['wall_seconds']} ({m['wall_time_source']}). Summed call seconds: {m['summed_call_seconds']}.",
             f"Cost per 1,000 inputs: {m['cost_per_1000_inputs_usd']}; cost per completed record: {m['cost_per_completed_record_usd']}.", "",
             "## Projections", "", "| Scope | Scenario | Reuse | First pass | API USD | Wall seconds | Budget exceeded |", "|---|---|---|---:|---:|---:|---|"]
    for p in report["projections"]:
        lines.append(f"| {p['scope']} | {p['scenario']} | {p['exact_text_reuse']} | {p['first_pass_classifications']} | {p['api_cost_usd']} | {p['projected_wall_seconds']} | {p['budget_exceeded']} |")
    lines += ["", "Cold/warm and initial/resume breakdowns, stage metadata, source-linked rates, uncertainty, and calculation inputs are preserved in report.json and CSV files.",
              "", "## Replay", "", "From this report's folder, with the pipeline package installed, run:", "", "```sh", "spotify-pipeline replay --calls pilot_calls.jsonl --rates rates.csv --out replay", "```", "",
              "This folder contains byte-for-byte copies of the source calls, available review records, rates, and run summary. The summary preserves measured time, input checksum, and cache mode when replayed elsewhere.",
              "Changing rates reprices usage. Changing target volumes only changes projections. No API key is required.", "", "## Limits", ""]
    lines.extend(f"- {line}" for line in report["limitations"])
    (out / "report.md").write_text("\n".join(lines) + "\n")
