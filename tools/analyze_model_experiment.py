#!/usr/bin/env python3
"""Offline, source-bound analysis of the matched development experiment."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from collections import Counter
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spotify_pipeline.data import row_sha
from spotify_pipeline.harness import evaluate_candidates


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * fraction
    lo = math.floor(pos)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo)


def score_vector(row):
    return {f"issue-{row['topic']}": row["severity"]} if row["intent"] in {"complaint", "cancellation"} else {}


def score_distance(a, b):
    return sum(abs(a.get(key, 0) - b.get(key, 0)) for key in set(a) | set(b))


def summarize_operations(run_dir, config, records, expected_config):
    calls = read_jsonl(run_dir / "calls.jsonl")
    summary = read_json(run_dir / "experiment_summary.json")
    request_ids = [call["request_id"] for call in calls]
    if len(request_ids) != len(set(request_ids)):
        raise ValueError(f"Duplicate request IDs in {run_dir}")
    if summary["label_config"] != expected_config:
        raise ValueError(f"Summary configuration mismatch: {run_dir}")
    total = Decimal(0)
    ledger_nano = 0
    logged_total = Decimal(0)
    token_totals = Counter()
    unknown_usage = Counter()
    for call in calls:
        if call["label_config"] != expected_config or call["run_id"] != summary["run_id"]:
            raise ValueError(f"Foreign call lineage: {run_dir}")
        if call["provider"] != "nebius" or call["model"] != config["models"]["enrich"]:
            raise ValueError(f"Unexpected call provider/model: {run_dir}")
        if call.get("cost_usd") is None or call.get("unknown_charge_hold_usd", 0):
            raise ValueError("Unresolved costs must be reconciled before this complete-cost analysis.")
        recomputed = sum(
            Decimal(str(item["units"])) * Decimal(str(config["rates"][item["rate_key"]])) / 1_000_000
            for item in call["billing_items"]
        )
        if abs(recomputed - Decimal(str(call["cost_usd"]))) > Decimal("0.000000001"):
            raise ValueError(f"Call cost disagrees with frozen rates: {call['request_id']}")
        total += recomputed
        logged_cost = Decimal(str(call["cost_usd"]))
        logged_total += logged_cost
        ledger_nano += int((logged_cost * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))
        for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens"):
            value = call.get("normalized_usage", {}).get(key)
            if value is None:
                unknown_usage[key] += 1
            else:
                token_totals[key] += value
    ledger_total = Decimal(ledger_nano) / 1_000_000_000
    if not summary["api_cost_complete"] or ledger_total != Decimal(str(summary["api_cost_usd"])):
        raise ValueError(f"Summary cost does not reconcile to exact calls: {run_dir}")
    if summary["attempts"] != len(calls):
        raise ValueError(f"Summary attempt count disagrees with calls: {run_dir}")
    if summary["completed"] != len(records) or any(row["status"] != "completed" for row in records):
        raise ValueError(f"Require completed records for operational comparison: {run_dir}")
    reasons = Counter(reason for row in records for reason in row.get("review_reasons", []))
    raw = Counter(str(row.get("raw_needs_review", row.get("raw_model_needs_review"))).lower() for row in records)
    final = Counter(str(row["needs_review"]).lower() for row in records)
    duration = [call["api_duration_seconds"] for call in calls]
    unique = len({row["review_text"] for row in records})
    return {
        "model": config["models"]["enrich"], "reasoning_effort": config["reasoning_effort"]["enrich"],
        "config_id": expected_config, "run_id": summary["run_id"],
        "records": len(records), "unique_texts": unique,
        "exact_text_aliases": sum(bool(row.get("cache_source_id")) for row in records),
        "attempts": len(calls), "outcomes": dict(Counter(call["outcome"] for call in calls)),
        "failed_attempts": summary["failed_attempts"], "nominal_cost_usd": float(total),
        "ledger_accounted_usd": float(ledger_total),
        "cost_reconciliation": {
            "logged_cost_sum_usd": float(logged_total),
            "ledger_minus_nominal_usd": float(ledger_total - total),
            "method": "Exact units×rates checked per call; summary equals per-call logged cost rounded upward to integer nano-USD.",
        },
        "nominal_cost_per_original_id_usd": float(total / len(records)),
        "nominal_cost_per_unique_text_usd": float(total / unique),
        "cost_basis": "Reported provider token usage times frozen nominal standard rates; not cash payment or invoice cost.",
        "usage_sum_of_reported_values": dict(token_totals), "usage_unknown_call_counts": dict(unknown_usage),
        "api_duration_sum_seconds": sum(duration), "api_duration_median_seconds": quantile(duration, .5),
        "api_duration_p95_seconds": quantile(duration, .95),
        "run_wall_seconds": summary["wall_seconds"], "enrich_wall_seconds": summary["stages"]["enrich"]["wall_seconds"],
        "unique_texts_per_run_wall_second": unique / summary["wall_seconds"],
        "raw_flag_counts": dict(raw), "audited_flag_counts": dict(final), "review_reason_counts": dict(reasons),
        "audit_added_flags": sum(row["needs_review"] and not row.get("raw_needs_review", row.get("raw_model_needs_review", True))
                                 for row in records),
        "topic_counts": dict(sorted(Counter(row["topic"] for row in records).items())),
        "intent_counts": dict(sorted(Counter(row["intent"] for row in records).items())),
        "severity_counts": dict(sorted(Counter(str(row["severity"]) for row in records).items())),
        "fallback_records": sum(row.get("fallback_used", False) for row in records),
        "call_request_ids": request_ids,
        "artifacts_sha256": {name: digest(run_dir / name) for name in
                             ("calls.jsonl", "records.jsonl", "experiment_summary.json", "condition_manifest.json")},
    }


def analyze(experiment, *, repetitions=1000):
    manifest = read_json(experiment / "manifest.json")
    sources = read_jsonl(experiment / "sources.jsonl")
    if digest(experiment / "sources.jsonl") != manifest["sources_sha256"]:
        raise ValueError("Frozen source file changed.")
    if {row["review_id"]: row_sha(row) for row in sources} != manifest["source_record_hashes"]:
        raise ValueError("Source identities differ from frozen manifest.")
    names = manifest["design"]["arms"]
    candidates, operations = {}, {}
    for name in names:
        config_path = experiment / "configs" / f"{name}.json"
        if digest(config_path) != manifest["config_file_hashes"][name]:
            raise ValueError(f"Frozen config changed: {name}")
        config = read_json(config_path)
        run = experiment / "runs" / name / "matched"
        condition = read_json(run / "condition_manifest.json")
        if condition["review_ids"] != [row["review_id"] for row in sources] or condition["condition"] != "matched":
            raise ValueError(f"Condition does not match source ordering: {name}")
        candidates[name] = read_jsonl(run / "records.jsonl")
        operations[name] = summarize_operations(run, config, candidates[name], manifest["config_fingerprints"][name])
    report = evaluate_candidates(sources, candidates, reference_kind="none",
                                 baseline_candidate="lightning-v5", bootstrap_repetitions=repetitions, seed=1729)
    if report["status"] != "complete":
        raise ValueError("Matched comparison is not complete; retain explicit failures before interpretation.")
    by_name = {name: {row["review_id"]: row for row in rows} for name, rows in candidates.items()}
    fields = ("topic", "intent", "severity", "sentiment", "needs_review")
    cases = []
    for source in sources:
        rid = source["review_id"]
        labels = {name: {field: by_name[name][rid][field] for field in fields} | {
            "raw_needs_review": by_name[name][rid].get("raw_needs_review"),
            "review_reasons": by_name[name][rid].get("review_reasons", []),
            "issue_score": score_vector(by_name[name][rid]),
        } for name in names}
        differences = [field for field in fields if len({labels[name][field] for name in names}) > 1]
        core = [field for field in differences if field in {"topic", "intent", "severity"}]
        max_distance = max(score_distance(labels[a]["issue_score"], labels[b]["issue_score"])
                           for a, b in itertools.combinations(names, 2))
        if differences:
            cases.append({
                "review_id": rid, "review_text": source["review_text"], "source_sha256": row_sha(source),
                "differing_fields": differences, "core_differing_fields": core,
                "maximum_pair_issue_score_l1_difference": max_distance, "labels": labels,
                "human_ground_truth": False,
            })
    cases.sort(key=lambda row: (-row["maximum_pair_issue_score_l1_difference"],
                               -len(row["core_differing_fields"]), row["review_id"]))
    pair_diagnostics = []
    ids = [row["review_id"] for row in sources]
    for a, b in itertools.combinations(names, 2):
        differing = [rid for rid in ids if any(by_name[a][rid][field] != by_name[b][rid][field]
                                              for field in ("topic", "intent", "severity"))]
        pair_diagnostics.append({
            "first": a, "second": b, "core_disagreement_count": len(differing),
            "first_raw_flagged_disagreements": sum(by_name[a][rid].get("raw_needs_review", False) for rid in differing),
            "second_raw_flagged_disagreements": sum(by_name[b][rid].get("raw_needs_review", False) for rid in differing),
            "first_audited_flagged_disagreements": sum(by_name[a][rid]["needs_review"] for rid in differing),
            "second_audited_flagged_disagreements": sum(by_name[b][rid]["needs_review"] for rid in differing),
            "interpretation": "Flags on model disagreements, not error capture or human accuracy.",
        })
    report["experiment_analysis"] = {
        "manifest_sha256": digest(experiment / "manifest.json"), "source_file_sha256": manifest["sources_sha256"],
        "analysis_script_sha256": digest(Path(__file__)), "harness_source_sha256": digest(ROOT / "src/spotify_pipeline/harness.py"),
        "selection": manifest["selection"], "design": manifest["design"], "operations": operations,
        "matched_attempts_total": sum(item["attempts"] for item in operations.values()),
        "matched_nominal_cost_usd": sum(item["nominal_cost_usd"] for item in operations.values()),
        "matched_ledger_accounted_usd": sum(item["ledger_accounted_usd"] for item in operations.values()),
        "matched_sequential_wall_seconds": sum(item["run_wall_seconds"] for item in operations.values()),
        "any_five_field_disagreement_ids": len(cases),
        "any_core_disagreement_ids": sum(bool(case["core_differing_fields"]) for case in cases),
        "pair_flag_diagnostics": pair_diagnostics,
        "qualitative_case_order": "Descending maximum per-review issue-score L1 difference, then number of core field disagreements, then ID.",
        "scope": "One matched development run per arm; synthetic/stress results and historical pilot are separate.",
        "human_answers_read": False, "production_promotion": False,
    }
    return report, cases


def markdown(report):
    experiment = report["experiment_analysis"]
    operations = experiment["operations"]
    lines = [
        "# Matched model comparison: development evidence",
        "",
        f"All five candidates completed the same {report['cohort']['expected_ids']} original IDs "
        f"({report['cohort']['distinct_exact_texts']} distinct texts). No human reference labels were used.",
        "",
        "These measurements compare model judgments and operational behavior. They do not establish human accuracy "
        "or authorize scale-up. The v5 arm reruns its prompt under the same new audited engine; it is not the historical v5 pilot.",
        "",
        "| Arm | Calls / failed | Nominal cost | Wall s | Input / output tokens | Raw / audited flags | Top issue (score) |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name in experiment["design"]["arms"]:
        item = operations[name]
        ranking = report["ranking_sensitivity"]["rankings"][name]["ranking"]
        top = f"{ranking[0]['issue_id']} ({ranking[0]['severity_sum']})" if ranking else "none"
        usage = item["usage_sum_of_reported_values"]
        lines.append(f"| {name} | {item['attempts']} / {item['failed_attempts']} | ${item['nominal_cost_usd']:.8f} | "
                     f"{item['run_wall_seconds']:.2f} | {usage['input_tokens']:,} / {usage['output_tokens']:,} | "
                     f"{item['raw_flag_counts'].get('true', 0)} / {item['audited_flag_counts'].get('true', 0)} | {top} |")
    lines += [
        "", "Nominal costs reconcile each logged billing item to the frozen rate configuration and the experiment "
        "summary. They are not cash payments or invoice costs. Latencies are single trials, including repairs and "
        "local overhead. Every arm used one worker, batches of up to ten, a separate empty result cache, and no fallback.",
        "", "## Pairwise agreement", "",
        "| Pair | Topic | Intent | Severity exact | Core joint | Severity absolute difference |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pair in report["pairwise_agreement"]:
        m = pair["metrics"]
        lines.append(f"| {pair['first']} / {pair['second']} | {m['topic']['agreement']['estimate']:.1%} | "
                     f"{m['intent']['agreement']['estimate']:.1%} | {m['severity']['exact']['estimate']:.1%} | "
                     f"{m['joint_topic_intent_severity']['estimate']:.1%} | {m['severity']['mean_absolute_difference']:.3f} |")
    lines += [
        "", "All pairwise denominators are 200. The first candidate is a comparator, not ground truth. "
        "JSON includes Wilson diagnostics and seeded exact-text cluster intervals.",
        "", "## Issue score sensitivity", "",
        "| Issue | " + " | ".join(experiment["design"]["arms"]) + " |",
        "|---|" + "---:|" * len(operations),
    ]
    ranks = report["ranking_sensitivity"]["rankings"]
    scoremaps = {name: {row["issue_id"]: row["severity_sum"] for row in item["ranking"]} for name, item in ranks.items()}
    for issue in sorted(set().union(*(set(item) for item in scoremaps.values()))):
        lines.append("| " + issue + " | " + " | ".join(str(scoremaps[name].get(issue, 0))
                                                      for name in experiment["design"]["arms"]) + " |")
    lines += [
        "", "Scores preserve every original ID and use severity sums for complaint/cancellation records only. "
        "Top-issue stability is sensitivity to predictions and the development sample, not business impact.",
        "", f"{experiment['any_core_disagreement_ids']} IDs differ on at least one topic/intent/severity label "
        f"across the five arms; {experiment['any_five_field_disagreement_ids']} differ on at least one of the five label fields.",
        "", "## Reproduction and scope", "",
        "Run `python tools/analyze_model_experiment.py --experiment evals/experiment-v6/matched-200 "
        "--prefix comparison-replay` to create a new report without replacing this one. Saved artifacts are "
        "`comparison.json`, `comparison.md`, and `comparison-cases.jsonl` in the experiment directory. "
        "The JSON records source, config, input, call-log, script, and harness hashes plus exact request IDs.",
        "", "The panel is sampled from already exposed development data, excluding protected golden IDs and exact texts. "
        "No generalization estimate follows from this panel. Named human holdout groups remain separate and blind. "
        "Case inspection is explicitly an AI qualitative audit; targeted cases cannot yield an error-rate estimate.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=ROOT / "evals/experiment-v6/matched-200")
    parser.add_argument("--prefix", default="comparison")
    parser.add_argument("--bootstrap-repetitions", type=int, default=1000)
    args = parser.parse_args()
    if Path(args.prefix).name != args.prefix:
        raise ValueError("Prefix must be a simple filename component.")
    paths = [args.experiment / f"{args.prefix}{suffix}" for suffix in (".json", ".md", "-cases.jsonl")]
    if any(path.exists() for path in paths):
        raise ValueError("Output exists; choose a new prefix to preserve prior evidence.")
    report, cases = analyze(args.experiment, repetitions=args.bootstrap_repetitions)
    paths[0].write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    paths[1].write_text(markdown(report))
    paths[2].write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for row in cases))
    print(json.dumps({"status": report["status"], "no_human_reference": True,
                      "matched_cost_usd": report["experiment_analysis"]["matched_nominal_cost_usd"],
                      "cases": len(cases), "outputs": [str(path) for path in paths]}))


if __name__ == "__main__":
    main()
