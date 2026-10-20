"""Retest a failed saved memo with explicit paid authorization and a shared ledger."""
import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from spotify_pipeline.analysis import memo_schema, validate_recommendations
from spotify_pipeline.engine import Engine, load_config
from spotify_pipeline.storage import atomic_json


async def run(args):
    load_dotenv(".env")
    source = Path(args.source)
    payload = json.loads((source / "handoffs/memo.input.json").read_text())
    evidence = payload["evidence"]
    result = {"ranking": payload["ranking"], "claims": payload["claims"]}
    output = Path(args.out)
    if output.exists():
        raise ValueError("Use a fresh output path; prior evidence is preserved.")
    engine = Engine(load_config(args.config), Path(args.db), output, budget_usd=.05, workers=1)
    try:
        response = await engine.model_task(
            "memo", payload, memo_schema(result, evidence),
            [row["review_id"] for rows in evidence.values() for row in rows],
            _validator=lambda value: validate_recommendations(value, result, evidence))
        atomic_json(output / "validated_memo.json", response)
        print(json.dumps({"validated": True, **engine.finish()}, indent=2))
    finally:
        engine.finish()
        await engine.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--config", default="config/nebius-pilot.json")
    args = parser.parse_args()
    if not args.execute_paid:
        raise SystemExit("No calls made. --execute-paid is required.")
    asyncio.run(run(args))
