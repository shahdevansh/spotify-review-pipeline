#!/usr/bin/env python3
"""Analyze saved synthetic and batch/order experiments using only local files.

No provider, engine, credential loader or human-answer file is imported/read.
Default execution refuses to publish a final report until every declared run
has a completed summary. --allow-partial explicitly labels unfinished evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIELDS = (
    "review_id", "review_text", "review_rating", "review_likes",
    "app_version", "review_timestamp",
)
SEMANTIC_FIELDS = ("topic", "intent", "severity")
COMPARISON_FIELDS = (*SEMANTIC_FIELDS, "sentiment", "raw_needs_review", "needs_review")
STRESS_ARMS = ("lightning-v6", "qwen235-v6")
STRESS_CONDITIONS = ("batch1", "batch10", "batch25", "shuffle", "repeat")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_sha(row):
    values = [row[field] for field in SOURCE_FIELDS]
    if any(not isinstance(value, str) for value in values):
        raise ValueError("Source fields must remain the original strings")
    return hashlib.sha256(canonical(values).encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def index_unique(rows, description):
    indexed = {row["review_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate review IDs in {description}")
    return indexed


def fraction(matches, total):
    return {"matches": matches, "denominator": total,
            "fraction": matches / total if total else None}


def observed(record):
    if record is None or record.get("status") != "completed":
        return None
    return {field: record.get(field) for field in COMPARISON_FIELDS}


def flag_score(details, actual_field):
    counts = dict(true_positive=0, true_negative=0, false_positive=0,
                  false_negative=0, unavailable=0)
    for detail in details:
        expected = detail["expected"]["needs_review"]
        actual = (detail["actual"] or {}).get(actual_field)
        if not isinstance(actual, bool):
            counts["unavailable"] += 1
        elif expected:
            counts["true_positive" if actual else "false_negative"] += 1
        else:
            counts["false_positive" if actual else "true_negative"] += 1
    counts.update(fraction(counts["true_positive"] + counts["true_negative"], len(details)))
    return counts


def score_synthetic(cases, records):
    """Missing predictions stay in every denominator; no human-accuracy claim."""
    indexed = index_unique(records, "synthetic records")
    details = []
    for case in cases:
        rid = case["source"]["review_id"]
        record = indexed.get(rid)
        actual = observed(record)
        field_matches = {field: actual is not None and actual[field] == case["expected"][field]
                         for field in SEMANTIC_FIELDS}
        details.append({
            "case": case["case"], "review_id": rid,
            "review_text": case["source"]["review_text"], "expected": case["expected"],
            "actual": actual, "status": (record or {}).get("status", "missing"),
            "field_matches": field_matches, "semantic_tuple_match": all(field_matches.values()),
            "raw_flag_match": actual is not None and isinstance(actual["raw_needs_review"], bool)
                              and actual["raw_needs_review"] == case["expected"]["needs_review"],
            "audited_flag_match": actual is not None and isinstance(actual["needs_review"], bool)
                                  and actual["needs_review"] == case["expected"]["needs_review"],
            "review_reasons": (record or {}).get("review_reasons", []),
            "review_audit": (record or {}).get("review_audit"),
        })
    fields = {
        field: fraction(sum(detail["field_matches"][field] for detail in details), len(cases))
        for field in SEMANTIC_FIELDS
    }
    return {
        "interpretation": "Agreement with predeclared AI-authored rubric regression expectations; not human accuracy",
        "case_count": len(cases),
        "completed": sum(detail["actual"] is not None for detail in details),
        "field_agreement": fields,
        "semantic_tuple_agreement": fraction(
            sum(detail["semantic_tuple_match"] for detail in details), len(cases)),
        "raw_review_flag_agreement": flag_score(details, "raw_needs_review"),
        "audited_review_flag_agreement": flag_score(details, "needs_review"),
        "audit_introduced_false_positive_ids": [
            detail["review_id"] for detail in details
            if detail["actual"] is not None and not detail["expected"]["needs_review"]
            and detail["actual"]["raw_needs_review"] is False
            and detail["actual"]["needs_review"] is True
        ],
        "semantic_mismatch_ids": [
            detail["review_id"] for detail in details if not detail["semantic_tuple_match"]
        ],
        "cases": details,
    }


def compare_records(sources, left, right):
    """Compare matched IDs; disagreement is not a correctness determination."""
    left_index, right_index = index_unique(left, "left run"), index_unique(right, "right run")
    details = []
    matches = {field: 0 for field in COMPARISON_FIELDS}
    semantic_matches = all_matches = both_completed = 0
    for source in sources:
        rid = source["review_id"]
        a, b = observed(left_index.get(rid)), observed(right_index.get(rid))
        available = a is not None and b is not None
        both_completed += available
        equal = {field: available and a[field] is not None and b[field] is not None
                 and a[field] == b[field] for field in COMPARISON_FIELDS}
        for field in COMPARISON_FIELDS:
            matches[field] += equal[field]
        semantic_match = all(equal[field] for field in SEMANTIC_FIELDS)
        every_match = all(equal.values())
        semantic_matches += semantic_match
        all_matches += every_match
        if not every_match:
            details.append({
                "review_id": rid, "review_text": source["review_text"],
                "left": a, "right": b, "both_completed": available,
                "different_or_unavailable_fields": [field for field, same in equal.items() if not same],
                "semantic_tuple_changed_or_unavailable": not semantic_match,
            })
    return {
        "denominator": len(sources), "both_completed": both_completed,
        "field_agreement": {field: fraction(count, len(sources)) for field, count in matches.items()},
        "semantic_tuple_agreement": fraction(semantic_matches, len(sources)),
        "all_six_fields_agreement": fraction(all_matches, len(sources)),
        "any_semantic_difference_or_unavailable_count": len(sources) - semantic_matches,
        "any_difference_or_unavailable_count": len(sources) - all_matches,
        "differences": details,
    }


def load_run(experiment, arm, condition, sources):
    directory = experiment / "runs" / arm / condition
    required = ("condition_manifest.json", "experiment_summary.json", "records.jsonl", "calls.jsonl")
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        return {"ready": False, "arm": arm, "condition": condition,
                "missing_files": missing}, None
    source_index = index_unique(sources, "frozen input")
    condition_manifest = read_json(directory / "condition_manifest.json")
    ids = condition_manifest["review_ids"]
    if len(ids) != len(source_index) or set(ids) != set(source_index):
        raise ValueError(f"{arm}/{condition}: condition input IDs differ from the frozen sources")
    ordered_sources = [source_index[rid] for rid in ids]
    input_hash = hashlib.sha256(canonical(ordered_sources).encode()).hexdigest()
    if condition_manifest["input_hash"] != input_hash:
        raise ValueError(f"{arm}/{condition}: condition source content hash mismatch")
    records = read_jsonl(directory / "records.jsonl")
    indexed = index_unique(records, f"{arm}/{condition}")
    if set(indexed) - set(source_index):
        raise ValueError(f"{arm}/{condition}: unexpected output IDs")
    for rid, record in indexed.items():
        source = source_index[rid]
        if any(record.get(field) != source[field] for field in SOURCE_FIELDS):
            raise ValueError(f"{arm}/{condition}: original source fields differ for {rid}")
        if record["source_sha256"] != row_sha(source):
            raise ValueError(f"{arm}/{condition}: source SHA differs for {rid}")
        if record.get("label_config") != condition_manifest["label_config"]:
            raise ValueError(f"{arm}/{condition}: label configuration differs for {rid}")
    summary = read_json(directory / "experiment_summary.json")
    calls = read_jsonl(directory / "calls.jsonl")
    if len({call["request_id"] for call in calls}) != len(calls):
        raise ValueError(f"{arm}/{condition}: duplicate call IDs")
    completed = sum(record.get("status") == "completed" for record in records)
    if summary["completed"] != completed or summary["input_count"] != len(sources):
        raise ValueError(f"{arm}/{condition}: summary record counts disagree with saved records")
    if summary["requests"] != len(calls):
        raise ValueError(f"{arm}/{condition}: summary request count disagrees with call log")
    known_costs = [Decimal(str(call["cost_usd"])) for call in calls
                   if call.get("cost_usd") is not None]
    known_cost = sum(known_costs, Decimal(0))
    # BudgetLedger conservatively rounds each attempt upward to nano-USD.
    # Float serialization can place a call just above an exact nano boundary.
    ledger_cost = sum(((cost * 10**9).to_integral_value(rounding=ROUND_CEILING) / 10**9
                       for cost in known_costs), Decimal(0))
    if ledger_cost != Decimal(str(summary["api_cost_usd"])):
        raise ValueError(f"{arm}/{condition}: summary known cost disagrees with call log")
    hold = sum((Decimal(str(call.get("unknown_charge_hold_usd", 0)))
                for call in calls if call.get("cost_usd") is None), Decimal(0))
    all_complete = completed == len(sources) and len(records) == len(sources)
    if bool(summary["all_inputs_completed"]) != all_complete:
        raise ValueError(f"{arm}/{condition}: completion flag disagrees with records")
    return {
        "ready": True, "arm": arm, "condition": condition,
        "all_inputs_completed": all_complete, "input_count": len(sources),
        "completed": completed, "quarantined": summary.get("quarantined"),
        "cache_hits": summary.get("cache_hits"), "requests": len(calls),
        "failed_attempts": sum(call.get("outcome") == "failed" for call in calls),
        "api_cost_usd": float(ledger_cost), "recorded_call_cost_usd": float(known_cost),
        "ledger_rounding_usd": float(ledger_cost - known_cost),
        "unknown_charge_hold_usd": float(hold),
        "api_cost_complete": summary["api_cost_complete"],
        "wall_seconds": summary["wall_seconds"],
        "model_settings": summary.get("model_settings"),
        "condition_manifest": condition_manifest,
        "file_sha256": {name: sha(directory / name) for name in required},
    }, records


def analyze(experiment, extra_stress_arms=()):
    manifest_path = experiment / "manifest.json"
    manifest = read_json(manifest_path)
    extra_stress_arms = tuple(dict.fromkeys(extra_stress_arms))
    if set(extra_stress_arms) & set(STRESS_ARMS):
        raise ValueError("An extra stress arm must not repeat an original stress arm")
    if set(extra_stress_arms) - set(manifest["design"]["arms"]):
        raise ValueError("Extra stress arms must already belong to the frozen model comparison")
    stress_arms = (*STRESS_ARMS, *extra_stress_arms)
    for filename, key in (
        ("synthetic_cases.json", "synthetic_cases_sha256"),
        ("stress_sources.jsonl", "stress_sources_sha256"),
    ):
        if sha(experiment / filename) != manifest[key]:
            raise ValueError(f"Frozen input changed: {filename}")
    cases = read_json(experiment / "synthetic_cases.json")
    stress_sources = read_jsonl(experiment / "stress_sources.jsonl")
    if len(cases) != 15 or len(stress_sources) != 25:
        raise ValueError("Expected the predeclared 15 synthetic and 25 stress records")
    if len({row["review_text"] for row in stress_sources}) != 25:
        raise ValueError("Stress inputs must contain 25 distinct original texts")
    synthetic_sources = [case["source"] for case in cases]
    report = {
        "version": "spotify-offline-stability-v6" + ("-adaptive-v2" if extra_stress_arms else ""),
        "manifest_sha256": sha(manifest_path), "human_answers_read": False,
        "human_accuracy_claimed": False, "model_calls_made_by_analysis": 0,
        "scope": {
            "synthetic_cases": 15, "synthetic_arms": manifest["design"]["arms"],
            "stress_distinct_original_reviews": 25, "stress_arms": list(stress_arms),
            "stress_conditions": list(STRESS_CONDITIONS), "primary_reference": "batch10",
            "semantic_fields": list(SEMANTIC_FIELDS), "all_compared_fields": list(COMPARISON_FIELDS),
            "expected_run_count": len(manifest["design"]["arms"]) + len(stress_arms) * len(STRESS_CONDITIONS),
        },
        "interpretation": [
            "Synthetic expectations were authored before these runs and are rubric regression checks, not human-reviewed ground truth.",
            "Many synthetic cases resemble prompt examples; success does not establish unseen-review accuracy.",
            "Stress comparisons measure sensitivity to batching, order and repeated requests, not which label is correct.",
            "Raw model needs_review and audit-adjusted needs_review are scored separately.",
            "Missing/quarantined outputs remain in comparison denominators and are not silently dropped.",
            "Saved known costs and unknown holds are separate; wall time is measured per condition and includes retries.",
        ],
        "synthetic": {}, "stress": {}, "pending_runs": [], "incomplete_runs": [],
    }
    if extra_stress_arms:
        prior_path = experiment / "stability_report.json"
        if not prior_path.is_file():
            raise ValueError("An adaptive extension requires the preserved original stability_report.json")
        prior = read_json(prior_path)
        if not prior["all_declared_runs_complete"] or prior.get("adaptive_extension"):
            raise ValueError("The adaptive extension must reference a completed original report")
        if prior["manifest_sha256"] != report["manifest_sha256"]:
            raise ValueError("Adaptive extension must use the same original frozen experiment")
        report["adaptive_extension"] = {
            "extra_stress_arms": list(extra_stress_arms),
            "selected_after_initial_results": True,
            "selection_reason": "Additional model stress tests selected after the initial synthetic and batch/order results showed sensitivity in the original stress arms",
            "prior_report": "stability_report.json", "prior_report_sha256": sha(prior_path),
            "prior_expected_run_count": 15,
            "new_expected_run_count": report["scope"]["expected_run_count"],
            "new_inputs_or_human_answers_used": False,
            "same_frozen_stress_inputs": True,
            "interpretation": "Adaptive follow-up, not an additional arm predeclared before observing the initial stress results",
        }
    evidence_runs = []
    for arm in manifest["design"]["arms"]:
        run, records = load_run(experiment, arm, "synthetic", synthetic_sources)
        evidence_runs.append(run)
        if not run["ready"]:
            report["pending_runs"].append(f"{arm}/synthetic")
            report["synthetic"][arm] = {"run": run}
            continue
        if not run["all_inputs_completed"]:
            report["incomplete_runs"].append(f"{arm}/synthetic")
        report["synthetic"][arm] = {"run": run, **score_synthetic(cases, records)}
    love_sources = [row for row in stress_sources if row["review_text"] == "Love it 💕"]
    if len(love_sources) != 1:
        raise ValueError("Expected one exact Love it diagnostic in the frozen stress set")
    love_source = love_sources[0]
    love_expected = next(case["expected"] for case in cases if case["case"] == "praise")
    for arm in stress_arms:
        loaded, runs = {}, {}
        for condition in STRESS_CONDITIONS:
            run, records = load_run(experiment, arm, condition, stress_sources)
            evidence_runs.append(run)
            runs[condition] = run
            if not run["ready"]:
                report["pending_runs"].append(f"{arm}/{condition}")
            else:
                loaded[condition] = records
                if not run["all_inputs_completed"]:
                    report["incomplete_runs"].append(f"{arm}/{condition}")
        pairs = {}
        changed_by_field = {field: set() for field in COMPARISON_FIELDS}
        semantic_changed, any_changed = set(), set()
        for left, right in itertools.combinations(STRESS_CONDITIONS, 2):
            if left not in loaded or right not in loaded:
                continue
            comparison = compare_records(stress_sources, loaded[left], loaded[right])
            pairs[f"{left}__vs__{right}"] = {"left_condition": left, "right_condition": right, **comparison}
            for difference in comparison["differences"]:
                rid = difference["review_id"]
                any_changed.add(rid)
                if difference["semantic_tuple_changed_or_unavailable"]:
                    semantic_changed.add(rid)
                for field in difference["different_or_unavailable_fields"]:
                    changed_by_field[field].add(rid)
        baseline = {
            condition: compare_records(stress_sources, loaded["batch10"], loaded[condition])
            for condition in STRESS_CONDITIONS if condition != "batch10"
            and "batch10" in loaded and condition in loaded
        }
        love = {}
        for condition, records in loaded.items():
            record = index_unique(records, f"{arm}/{condition}").get(love_source["review_id"])
            actual = observed(record)
            love[condition] = {
                "actual": actual,
                "semantic_expected_match": actual is not None and all(
                    actual[field] == love_expected[field] for field in SEMANTIC_FIELDS),
                "review_reasons": (record or {}).get("review_reasons", []),
            }
        report["stress"][arm] = {
            "runs": runs, "vs_batch10": baseline, "all_pairwise": pairs,
            "unique_ids_changed_or_unavailable_across_conditions": sorted(any_changed),
            "unique_ids_with_semantic_change_or_unavailable": sorted(semantic_changed),
            "unique_changed_ids_by_field": {field: sorted(ids) for field, ids in changed_by_field.items()},
            "love_it_diagnostic": {
                "review_id": love_source["review_id"], "review_text": love_source["review_text"],
                "expected_from_predeclared_identical_text_case": love_expected,
                "conditions": love,
                "interpretation": "A wrong label here is evidence of failure on this text; differences alone do not prove neighboring-text contamination caused it.",
            },
        }
    ready = [run for run in evidence_runs if run["ready"]]
    report["all_declared_runs_complete"] = not report["pending_runs"] and not report["incomplete_runs"]
    report["totals_for_loaded_synthetic_and_stress_runs_only"] = {
        "runs_loaded": len(ready), "requests": sum(run["requests"] for run in ready),
        "failed_attempts": sum(run["failed_attempts"] for run in ready),
        "api_cost_usd": float(sum((Decimal(str(run["api_cost_usd"])) for run in ready), Decimal(0))),
        "unknown_charge_hold_usd": float(sum(
            (Decimal(str(run["unknown_charge_hold_usd"])) for run in ready), Decimal(0))),
        "api_cost_complete": all(run["api_cost_complete"] for run in ready),
        "sum_of_individual_wall_seconds": sum(run["wall_seconds"] for run in ready),
        "wall_time_interpretation": "Sum of condition durations, not the elapsed makespan of parallel execution",
    }
    return report


def label(value):
    if value is None:
        return "unavailable"
    return "/".join(str(value.get(field)) for field in SEMANTIC_FIELDS)


def fmt_fraction(value):
    return f'{value["matches"]}/{value["denominator"]}'


def markdown(report):
    complete = report["all_declared_runs_complete"]
    lines = [
        "# Model stability experiment v6", "",
        "**Status: " + ("all declared synthetic and stress conditions completed." if complete
                        else "partial evidence; unfinished conditions remain.") + "**",
        "",
    ]
    extension = report.get("adaptive_extension")
    report_name = "stability_report_v2.json" if extension else "stability_report.json"
    if extension:
        lines.extend([
            "**Adaptive extension:** " + ", ".join(extension["extra_stress_arms"])
            + " was added to the five stress conditions after reviewing the initial results. "
            "The original 15-run JSON remains `stability_report.json`, and its narrative is preserved "
            "as `docs/model-stability-v6-initial.md`. This revision covers "
            f'{extension["new_expected_run_count"]} runs using the same frozen inputs. '
            "This added stress comparison was not predeclared before the initial observations.",
            "",
        ])
    if complete:
        synthetic_values = ", ".join(
            f'{arm}: {entry["semantic_tuple_agreement"]["matches"]}/15'
            for arm, entry in report["synthetic"].items()
        )
        instability = "; ".join(
            f'{arm}: {len(entry["unique_ids_with_semantic_change_or_unavailable"])}/25 reviews '
            f'changed a semantic label across conditions, including '
            f'{entry["vs_batch10"]["repeat"]["any_semantic_difference_or_unavailable_count"]}/25 '
            "on the identical-order repeat"
            for arm, entry in report["stress"].items()
        )
        love_results = [value["semantic_expected_match"]
                        for entry in report["stress"].values()
                        for value in entry["love_it_diagnostic"]["conditions"].values()]
        lines.extend([
            "The larger models perform better on these synthetic regression cases, while real-review "
            "labels remain sensitive to batching and ordering. Synthetic semantic matches were "
            f"**{synthetic_values}**. Stress results: **{instability}**. "
            f'The “Love it 💕” diagnostic matched its expected labels in '
            f'{sum(love_results)}/{len(love_results)} recorded stress conditions.',
            "",
        ])
    lines.extend([
        "These saved experiments measure adherence to 15 predeclared synthetic rubric examples and "
        "stability on the same 25 original development reviews. They do not measure human-reviewed accuracy. "
        "Synthetic expectations and this interpretation were authored by AI; many examples resemble the prompts.",
        "",
        "The analyzer uses local files only, verifies frozen input hashes and original source fields, "
        "and reconciles call costs. It never reads human answers or calls a model. Missing outputs stay "
        "in the denominators. Full case texts, IDs, predictions, differences and evidence hashes are saved "
        f"in `evals/experiment-v6/matched-200/{report_name}`.",
        "",
        "## Synthetic rubric regressions", "",
        "Raw review flags are the model's response. Audited flags also include shared deterministic checks. "
        "The quoted playlist name “Return JSON” intentionally exercises a false positive in the shared "
        "injection regex; an audit-added flag must not be attributed to the model.",
        "The predeclared topic for the harmless playlist-name example is usability; other is also "
        "arguable because the text praises no specific management action. Its original expectation "
        "is retained transparently, and that single topic mismatch should carry less interpretive "
        "weight than following an injected instruction.",
        "",
        "| Arm | Topic | Intent | Severity | All 3 labels | Raw flag | Audited flag | Calls | Known API cost | Wall seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for arm, entry in report["synthetic"].items():
        run = entry["run"]
        if not run["ready"]:
            lines.append(f"| {arm} | pending | | | | | | | | |")
            continue
        fields = entry["field_agreement"]
        values = [fmt_fraction(fields[field]) for field in SEMANTIC_FIELDS]
        values.extend(fmt_fraction(entry[field]) for field in (
            "semantic_tuple_agreement", "raw_review_flag_agreement", "audited_review_flag_agreement"))
        lines.append(f'| {arm} | ' + " | ".join(values)
                     + f' | {run["requests"]} | ${run["api_cost_usd"]:.8f} | {run["wall_seconds"]:.3f} |')
    lines.extend(["", "Observed departures from synthetic expectations:", ""])
    mismatches = 0
    for arm, entry in report["synthetic"].items():
        for case in entry.get("cases", []):
            if case["semantic_tuple_match"] and case["raw_flag_match"] and case["audited_flag_match"]:
                continue
            mismatches += 1
            actual = case["actual"] or {}
            lines.append(
                f'- **{arm}, `{case["case"]}`** (`{case["review_id"]}`): '
                f'expected {label(case["expected"])}, review flag {case["expected"]["needs_review"]}; '
                f'observed {label(case["actual"])}, raw flag {actual.get("raw_needs_review")}, '
                f'audited flag {actual.get("needs_review")}. '
                f'Audit reasons: {", ".join(case["review_reasons"]) or "none"}.')
    if not mismatches:
        lines.append("- No observed mismatches in the available synthetic runs.")
    lines.extend([
        "", "## Batch and ordering sensitivity", "",
        "Each arm uses five fresh caches on the same 25 distinct texts: batch sizes 1, 10 and 25; "
        "a deterministic shuffled order at batch size 10; and an independent repeat of the original "
        "batch-10 order. All use one worker, temperature 0 and no fallback. The primary reference is "
        "the original batch-10 run. The development stress panel was selected deterministically, "
        "with the known “Love it” case deliberately included; it is not a representative held-out sample. "
        "Field agreement is descriptive, not correctness.",
        "",
        "| Arm / comparison with batch10 | Topic | Intent | Severity | All 3 labels | Sentiment | Raw flag | Audited flag | Any semantic difference | Any of 6 fields differs |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for arm, entry in report["stress"].items():
        for condition, comparison in entry["vs_batch10"].items():
            fields = comparison["field_agreement"]
            values = [fmt_fraction(fields[field]) for field in SEMANTIC_FIELDS]
            values.append(fmt_fraction(comparison["semantic_tuple_agreement"]))
            values.extend(fmt_fraction(fields[field]) for field in COMPARISON_FIELDS[3:])
            lines.append(f"| {arm} / {condition} | " + " | ".join(values)
                         + f' | {comparison["any_semantic_difference_or_unavailable_count"]}'
                         + f' | {comparison["any_difference_or_unavailable_count"]} |')
    lines.extend(["", "Measured stress-run costs and latency:", "",
                  "| Arm | Condition | Completed | Calls | Failed attempts | Known API cost | Wall seconds |",
                  "|---|---|---:|---:|---:|---:|---:|"])
    for arm, entry in report["stress"].items():
        for condition, run in entry["runs"].items():
            if run["ready"]:
                lines.append(
                    f'| {arm} | {condition} | {run["completed"]}/{run["input_count"]} | '
                    f'{run["requests"]} | {run["failed_attempts"]} | ${run["api_cost_usd"]:.8f} | '
                    f'{run["wall_seconds"]:.3f} |')
            else:
                lines.append(f"| {arm} | {condition} | pending | | | | |")
    lines.extend(["", "### The “Love it 💕” diagnostic", "",
                  "This original review has the same text as the predeclared synthetic praise case: "
                  "`other/praise/1`. The table exposes whether batching or order changes its labels. "
                  "A failure on this text is concrete; attributing its cause to neighboring-review "
                  "contamination would require additional controlled evidence.", "",
                  "| Arm | Condition | Original review ID | Observed labels | Matches expected labels |",
                  "|---|---|---|---|---|"])
    for arm, entry in report["stress"].items():
        diagnostic = entry["love_it_diagnostic"]
        for condition, value in diagnostic["conditions"].items():
            lines.append(f'| {arm} | {condition} | `{diagnostic["review_id"]}` | '
                         f'{label(value["actual"])} | {value["semantic_expected_match"]} |')
    totals = report["totals_for_loaded_synthetic_and_stress_runs_only"]
    lines.extend([
        "", f'These loaded synthetic/stress runs made **{totals["requests"]} requests**, with '
        f'**{totals["failed_attempts"]} failed attempts**, **${totals["api_cost_usd"]:.8f} known API cost** '
        f'and **${totals["unknown_charge_hold_usd"]:.8f} unknown-charge holds**. '
        "Matched-200 runs and historical experiments are excluded from this total.",
        "Known API costs use the shared ledger's per-attempt upward rounding to nano-USD. "
        "The JSON also preserves the raw sum of logged call costs and the rounding difference for each run.",
        "", "Offline reproduction:", "", "```sh",
        "python -S tools/analyze_experiment_stability.py"
        + "".join(f" --stress-arm {arm}" for arm in (extension or {}).get("extra_stress_arms", [])),
        "```", "",
        "The script refuses a final report while declared conditions are missing. "
        "`--allow-partial` is available for explicitly unfinished inspection. Runtime, provider routing, "
        "and token caps remain those of the frozen experiment; identical seeds and temperature 0 do "
        "not guarantee deterministic hosted-model responses.",
    ])
    if not complete:
        lines.extend(["", "Pending runs: " + (", ".join(report["pending_runs"]) or "none") + ".",
                      "Incomplete runs: " + (", ".join(report["incomplete_runs"]) or "none") + "."])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=ROOT / "evals/experiment-v6/matched-200")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--markdown", type=Path, default=ROOT / "docs/model-stability-v6.md")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--stress-arm", action="append", default=[],
                        help="Add a frozen model arm as a disclosed adaptive stress follow-up")
    args = parser.parse_args()
    report = analyze(args.experiment.resolve(), args.stress_arm)
    if not report["all_declared_runs_complete"] and not args.allow_partial:
        parser.error("Evidence is not complete; no report written. Pending: "
                     + ", ".join(report["pending_runs"] + report["incomplete_runs"]))
    destination = args.report or args.experiment / (
        "stability_report_v2.json" if args.stress_arm else "stability_report.json")
    if args.stress_arm and destination.resolve() == (args.experiment / "stability_report.json").resolve():
        parser.error("An adaptive report must not overwrite the original stability_report.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(destination), "markdown": str(args.markdown),
                      "all_declared_runs_complete": report["all_declared_runs_complete"],
                      "totals": report["totals_for_loaded_synthetic_and_stress_runs_only"]}, indent=2))


if __name__ == "__main__":
    main()
