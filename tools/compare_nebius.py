"""Matched, blind model screening on the unchanged 100-review development set.

This is a separate experiment, not the required end-to-end cold measurement.
The same rubric, schema, record order and batches are supplied independently.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from dotenv import load_dotenv
from spotify_pipeline.data import read_reviews, file_sha256
from spotify_pipeline.engine import Engine, load_config
from spotify_pipeline.storage import atomic_json

MODELS = {
    "qwen": ("Qwen/Qwen3-30B-A3B-Instruct-2507", "none"),
    "lightning": ("nvidia/Nemotron-3_5-Lightning", "none"),
    "gptoss": ("openai/gpt-oss-120b", "low"),
}


async def run(args):
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    config = load_config(root / "config/nebius-pilot.json")
    model, effort = MODELS[args.model]
    config["models"]["verify"] = model
    config["reasoning_effort"]["verify"] = effort
    config["global_budget_usd"] = 1.5
    input_path = root / "data/source/cost_100.csv"
    rows = list(read_reviews(input_path))
    out = root / "runs" / args.experiment / args.model
    if (out / "screening_report.json").exists():
        raise SystemExit("This experiment already has evidence. Inspect it before repeating.")
    engine = Engine(config, root / "data" / f"{args.experiment}_{args.model}.sqlite3",
                    out, budget_usd=.10, workers=1)
    try:
        results = await engine.verify(rows, [], sample_count=len(rows))
        summary = engine.finish()
        completed = sum(r["status"] == "completed" for r in results)
        report = {
            "purpose": "Matched model screening, not end-to-end cold/warm cost",
            "input_sha256": file_sha256(input_path), "input_count": len(rows),
            "model": model, "reasoning_effort": effort, "completed": completed,
            "independent_source_only": True, "human_accuracy_claimed": False,
            "summary": summary,
        }
        atomic_json(out / "screening_report.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "summary"} |
                         {k: summary[k] for k in ("requests", "failed_attempts", "api_cost_usd",
                                                  "api_cost_complete", "wall_seconds")}, indent=2))
        return completed == len(rows) and summary["api_cost_complete"]
    finally:
        engine.finish()
        await engine.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--experiment", default="nebius-screening-v2")
    args = parser.parse_args()
    if not args.execute_paid:
        raise SystemExit("No calls made. --execute-paid is required.")
    if not re.fullmatch(r"[a-z0-9_-]+", args.experiment):
        raise SystemExit("Experiment name must contain only lowercase letters, digits, _ or -.")
    raise SystemExit(0 if asyncio.run(run(args)) else 1)
