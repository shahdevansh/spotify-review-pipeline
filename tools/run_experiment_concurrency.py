#!/usr/bin/env python3
"""Bounded four-worker development probe against an already frozen experiment."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from run_model_experiment import (
    Engine, atomic_json, canonical, fingerprint, read_jsonl, validate_frozen,
)


async def run(root: Path, experiment: Path, arm: str) -> dict:
    manifest = validate_frozen(root, experiment)
    config = json.loads((experiment / "configs" / f"{arm}.json").read_text())
    config["_root"] = str(root)
    if fingerprint(config) != manifest["config_fingerprints"][arm]:
        raise ValueError("Frozen configuration mismatch.")
    rows = read_jsonl(experiment / "sources.jsonl")
    output = experiment / "runs" / arm / "concurrency4"
    cache = root / "data" / f"experiment-v6-{experiment.name}-{arm}-concurrency4.sqlite3"
    if output.exists() or cache.exists():
        raise ValueError("Condition already exists; refusing a billed rerun.")
    output.mkdir(parents=True)
    atomic_json(output / "condition_manifest.json", {
        "arm": arm, "condition": "concurrency4", "workers": 4,
        "input_hash": hashlib.sha256(canonical(rows).encode()).hexdigest(),
        "review_ids": [row["review_id"] for row in rows],
        "label_config": fingerprint(config), "fallback_disabled": True,
        "selection": "Same frozen development panel as the one-worker matched run",
        "adaptive_extension": True,
        "rationale": "Measure first-pass throughput before extrapolating to full volume.",
        "human_accuracy_claimed": False,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "frozen_experiment": experiment.name,
    })
    engine = Engine(config, cache, output, budget_usd=.50, workers=4)
    error = None
    try:
        await engine.enrich(rows)
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        summary = engine.finish()
        summary.update(
            experiment_arm=arm, experiment_condition="concurrency4",
            human_accuracy_claimed=False, terminal_exception=error,
            all_inputs_completed=summary["completed"] == len(rows),
        )
        atomic_json(output / "experiment_summary.json", summary)
        await engine.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--experiment", type=Path)
    parser.add_argument("--arm", required=True, choices=["glm-v6", "qwen235-v6"])
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if not args.execute_paid:
        parser.error("No inference made. --execute-paid is required.")
    root = args.root.resolve()
    experiment = args.experiment or root / "evals/experiment-v6/matched-200"
    from dotenv import load_dotenv
    load_dotenv(root / ".env")
    result = asyncio.run(run(root, experiment.resolve(), args.arm))
    print(json.dumps({key: result[key] for key in (
        "experiment_arm", "experiment_condition", "completed", "requests",
        "failed_attempts", "api_cost_usd", "wall_seconds", "all_inputs_completed",
    )}, indent=2))
    if not result["all_inputs_completed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
