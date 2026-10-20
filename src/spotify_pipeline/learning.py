"""Summarize actual learning-run evidence without claiming unperformed evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from .evaluation import classification_signal_summary


def learning_report(pilot_dir: Path, rates_path: Path, *, budget: float = 1.5) -> dict:
    pilot_dir = Path(pilot_dir)
    stages = {}
    for name in ("100-cold", "100-warm", "500", "1000"):
        file = pilot_dir / name / "run_summary.json"
        stages[name] = json.loads(file.read_text()) if file.exists() else {"status": "not_run"}
    signal_summaries, cost_evidence, role_settings = {}, {}, {}
    for name, stage in stages.items():
        records = pilot_dir / name / "records.jsonl"
        signal_summaries[name] = classification_signal_summary(records) if records.exists() else None
        cost_file = pilot_dir / name / "cost/report.json"
        cost = json.loads(cost_file.read_text()) if cost_file.exists() else None
        cost_evidence[name] = cost.get("measurements") if cost else None
        settings = stage.get("model_settings", {})
        role_settings[name] = {
            "providers": settings.get("providers", {}),
            "models": settings.get("models", {}),
            "reasoning_effort": settings.get("reasoning_effort", {}),
        }
    final = stages["1000"]
    complete = final.get("completed", 0) == 1000
    report = {
        "status": "requires_review" if complete else "incomplete",
        "decision": "Do not expand until pilot evidence, errors, budget and throughput are reviewed.",
        "stages": stages,
        "pilot_budget_usd": budget,
        "target_original_reviews": 210000,
        "observed_target_distinct_texts": 159657,
        "rates_path": str(rates_path),
        "role_settings": role_settings,
        "classification_signals": signal_summaries,
        "cost_evidence": cost_evidence,
        "cost_interpretation": "Nominal usage repricing measures economic API usage at saved public rates. "
                               "Provider-reported gateway debits are separate evidence. Neither establishes "
                               "incremental cash purchases or the remaining prepaid/promotional credit balance.",
        "incremental_cash_spend_usd": None,
        "remaining_provider_credits_usd": None,
        "human_golden_evaluation": "Pending independently supplied human labels and frozen configuration.",
        "required_review": [
            "Inspect 30 seeded random development cases and up to 30 disagreements/failures.",
            "Separate independent model agreement from human-label accuracy.",
            "Keep missing provider confidence unknown; assess needs_review as an uncalibrated prediction.",
            "Confirm exact quotes support labels and entities are grounded.",
            "Explain prompt changes and freeze the configuration.",
            "Refresh conservative total cost and sustained wall-time projection.",
            "Verify deployed database/API counts and recovery/spend controls.",
        ],
        "automatic_expansion": False,
    }
    pilot_dir.mkdir(parents=True, exist_ok=True)
    (pilot_dir / "learning_report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# 1,000-review learning checkpoint", "", f"Status: **{report['status']}**.", "",
             report["decision"], "", "| Stage | Completed | Quarantined | Wall seconds | Logged usage/debit USD |",
             "|---|---:|---:|---:|---:|"]
    for name, data in stages.items():
        lines.append(f"| {name} | {data.get('completed', 'not run')} | {data.get('quarantined', '—')} | "
                     f"{data.get('wall_seconds', '—')} | {data.get('api_cost_usd', '—')} |")
    lines += ["", "## Required inspection", ""] + ["- " + x for x in report["required_review"]]
    lines += ["", "## Model roles and confidence", ""]
    for name, settings in role_settings.items():
        if settings["models"]:
            roles = "; ".join(f"{role}: {settings['providers'].get(role, 'provider not recorded')} / {model}"
                              for role, model in sorted(settings["models"].items()))
            lines.append(f"- {name}: {roles}.")
    lines += ["", "Model ambiguity flags are not calibrated confidence scores. "
              "Unreported probabilities remain unknown; the JSON report preserves the observed metadata counts.",
              "", "## Cost interpretation", "", report["cost_interpretation"],
              "Incremental cash purchases and remaining credit balances are unmeasured by this report."]
    lines += ["", "No 10,000- or 210,000-review run is launched by this report.",
              "The final target has 159,657 unique texts; this is a measured source-data count, not a billed-token estimate."]
    (pilot_dir / "learning_report.md").write_text("\n".join(lines) + "\n")
    return report
