"""Summarize actual learning-run evidence without claiming unperformed evaluation."""
from __future__ import annotations

import json
from pathlib import Path


def learning_report(pilot_dir: Path, rates_path: Path, *, budget: float = 1.5) -> dict:
    pilot_dir = Path(pilot_dir)
    stages = {}
    for name in ("100-cold", "100-warm", "500", "1000"):
        file = pilot_dir / name / "run_summary.json"
        stages[name] = json.loads(file.read_text()) if file.exists() else {"status": "not_run"}
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
        "human_golden_evaluation": "Pending independently supplied human labels and frozen configuration.",
        "required_review": [
            "Inspect 30 seeded random development cases and up to 30 disagreements/failures.",
            "Separate independent model agreement from human-label accuracy.",
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
             report["decision"], "", "| Stage | Completed | Quarantined | Wall seconds | API cost USD |",
             "|---|---:|---:|---:|---:|"]
    for name, data in stages.items():
        lines.append(f"| {name} | {data.get('completed', 'not run')} | {data.get('quarantined', '—')} | "
                     f"{data.get('wall_seconds', '—')} | {data.get('api_cost_usd', '—')} |")
    lines += ["", "## Required inspection", ""] + ["- " + x for x in report["required_review"]]
    lines += ["", "No 10,000- or 210,000-review run is launched by this report.",
              "The final target has 159,657 unique texts; this is a measured source-data count, not a billed-token estimate."]
    (pilot_dir / "learning_report.md").write_text("\n".join(lines) + "\n")
    return report
