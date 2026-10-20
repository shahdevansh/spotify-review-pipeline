"""Bounded live API contract probe, separate from required pilot measurements.

Run from the repository root. Every attempt uses the shared budget ledger.
No network activity occurs without --execute-paid. Two development reviews only.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from spotify_pipeline.data import read_reviews
from spotify_pipeline.models import Classification
from spotify_pipeline.nebius import NebiusProvider, normalize_nebius_usage
from spotify_pipeline.providers import ProviderError
from spotify_pipeline.storage import BudgetLedger, atomic_json, canonical, utcnow


async def probe(args):
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    records = list(read_reviews(root / "data/learning_1000.csv"))[:2]
    payload = {"reviews": [{"review_id": r["review_id"], "review_text": r["review_text"]} for r in records]}
    prompt = (root / "prompts/labels.md").read_text() + "\n\n" + (root / "prompts/verify.md").read_text()
    schema = Classification.model_json_schema()
    schema["properties"] = {"review_id": {"type": "string"}, **schema["properties"]}
    schema["required"] = ["review_id", *schema["required"]]
    schema = {"type": "object", "properties": {"reviews": {"type": "array", "items": schema}},
              "required": ["reviews"], "additionalProperties": False}
    # Dated public rates are economic usage costs, not an invoice or cash purchase.
    options = {
        "qwen": ("Qwen/Qwen3-30B-A3B-Instruct-2507", "none", .10, .30,
                 "https://nebius.com/services/token-factory/models/qwen-models-inference"),
        "gptoss": ("openai/gpt-oss-120b", "low", .15, .60,
                   "https://tokenfactory.nebius.com/models/openai/gpt-oss-120b"),
    }
    model, effort, input_rate, output_rate, rate_source = options[args.model]
    kwargs = dict(model=model, reasoning_effort=effort, prompt=prompt, payload=payload,
                  schema=schema, max_output_tokens=3000, schema_name="spotify_contract_probe")
    request = NebiusProvider.build_request(**kwargs)
    out = root / "runs" / f"nebius-contract-{args.model}"
    if (out / "report.json").exists():
        raise SystemExit("Probe already has evidence. Inspect it; do not silently overwrite/rebill.")
    out.mkdir(parents=True, exist_ok=True)
    ledger = BudgetLedger(root / "data/spend.sqlite3")
    provider = NebiusProvider(timeout=60)
    request_id = uuid.uuid4().hex
    reserve = ((len(canonical(request).encode()) + 2048) * input_rate + 3000 * output_rate) / 1e6
    ledger.reserve(request_id, f"nebius-contract-{args.model}", reserve, global_cap_usd=1.50, run_cap_usd=.05)
    atomic_json(out / "request.json", request)
    started = time.monotonic()
    raw = usage = normalized = cost = None
    completed = 0
    error = None
    try:
        response = await provider.structured(**kwargs)
        raw, usage = response.raw, response.usage
        predictions = response.data.get("reviews")
        if not isinstance(predictions, list) or len(predictions) != len(records):
            raise ValueError("Incorrect result count")
        source = {r["review_id"]: r for r in records}
        if {p.get("review_id") for p in predictions} != set(source):
            raise ValueError("Missing, duplicate, or foreign review ID")
        for prediction in predictions:
            item = Classification.model_validate({k: v for k, v in prediction.items() if k != "review_id"})
            text = source[prediction["review_id"]]["review_text"]
            if item.evidence_quote not in text or any(e.casefold() not in text.casefold() for e in item.entities):
                raise ValueError("Unsupported quote or entity")
        completed = len(predictions)
        atomic_json(out / "predictions.json", response.data)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, ProviderError):
            raw, usage = exc.raw, exc.usage
    finally:
        elapsed = time.monotonic() - started
        try:
            normalized = normalize_nebius_usage(usage)
            if normalized and normalized["input_tokens"] is not None and normalized["output_tokens"] is not None:
                cost = (normalized["input_tokens"] * input_rate + normalized["output_tokens"] * output_rate) / 1e6
        except (ValueError, TypeError):
            error = error or "Inconsistent provider usage"
        ledger.settle(request_id, cost)
        atomic_json(out / "response.json", raw)
        report = {
            "purpose": "Live API contract check, excluded from cold/warm pilot measurements",
            "created_at": utcnow(), "request_id": request_id, "provider": "nebius",
            "model": model, "reasoning_effort": effort, "endpoint": provider.endpoint,
            "input_review_ids": [r["review_id"] for r in records],
            "input_sha256": hashlib.sha256(canonical(payload).encode()).hexdigest(),
            "completed": completed, "human_accuracy_claimed": False, "error": error,
            "wall_seconds": elapsed, "raw_usage": usage, "normalized_usage": normalized,
            "economic_usage_cost_usd": cost, "cost_basis": "all_reported_tokens_at_dated_public_rates",
            "credit_debit_verified": False, "incremental_cash_cost_verified": False,
            "input_rate_per_million": input_rate, "output_rate_per_million": output_rate,
            "rates_as_of": "2026-10-19", "rate_source": rate_source,
            "reservation_usd": reserve, "global_spending": ledger.totals(),
        }
        atomic_json(out / "report.json", report)
        print(json.dumps(report, indent=2), flush=True)
        await provider.aclose()
        ledger.close()
    return completed == 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--model", choices=["qwen", "gptoss"], required=True)
    arguments = parser.parse_args()
    if not arguments.execute_paid:
        raise SystemExit("No calls made. --execute-paid is required.")
    raise SystemExit(0 if asyncio.run(probe(arguments)) else 1)
