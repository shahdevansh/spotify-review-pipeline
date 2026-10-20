#!/usr/bin/env python3
"""Seal predictions privately before independently supplied human evaluation.

Only source-only JSONL, its manifest, and groups are read from the human pack.
Preparation makes no inference. Execution requires an already frozen public
plan and --execute-paid. Predictions never enter public reports or dashboards.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

from run_model_experiment import (
    ROOT, Engine, SOURCE_FIELDS, atomic_json, canonical, digest, fingerprint,
    ledger_snapshot, row_sha, utcnow, validate_frozen,
)

ARMS = ("lightning-v5", "glm-v6")
GROUP_COUNTS = {"mandatory_golden_50": 50, "fresh_text_disjoint_150": 150}
GLOBAL_CAP = Decimal("3.231403294")
PER_ARM_CAP = .50
EXPERIMENT = Path("evals/experiment-v6/matched-200")
SOURCE_PACK = Path("evals/human-evaluation-v1")
PRIVATE = Path("private/human-predictions-v1")
PLAN_NAME = "prediction_plan.json"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _json(raw: str):
    return json.loads(raw, object_pairs_hook=_unique_object)


def _inside(root: Path, relative: Path) -> Path:
    """Reject symlink redirection even when the resulting target stays local."""
    current = root.resolve()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlinked evidence paths are not accepted.")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("Evidence path escaped the repository.")
    return current


def _identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": digest(raw)}


def _read_sources(root: Path) -> tuple[list[dict], dict, dict]:
    # These literal paths are the entire human input read surface. Manifest
    # worksheet/membership/source references are provenance, never read targets.
    manifest_path = _inside(root, SOURCE_PACK / "sources_manifest.json")
    source_path = _inside(root, SOURCE_PACK / "sources.jsonl")
    groups_path = _inside(root, SOURCE_PACK / "groups.json")
    manifest = _json(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "spotify-human-evaluation-sources-v1":
        raise ValueError("Unsupported source-only manifest.")
    if manifest.get("fields") != list(SOURCE_FIELDS):
        raise ValueError("Source manifest must declare exactly the six original fields.")
    for path, expected in ((source_path, manifest["sources_jsonl"]),
                           (groups_path, manifest["groups"])):
        if _identity(path) != {key: expected[key] for key in ("bytes", "sha256")}:
            raise ValueError("Human evaluation source or group checksum changed.")
    rows = [_json(line) for line in source_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if len(rows) != 200 or manifest.get("rows") != 200:
        raise ValueError("Exactly 200 source-only records are required.")
    if any(not isinstance(row, dict) or set(row) != set(SOURCE_FIELDS)
           or any(not isinstance(value, str) for value in row.values()) for row in rows):
        raise ValueError("Only the six original string fields may enter prediction.")
    ids = [row["review_id"] for row in rows]
    if len(set(ids)) != 200 or any(not value for value in ids):
        raise ValueError("Source IDs must be 200 unique nonempty strings.")
    if any(not row["review_text"].strip() for row in rows):
        raise ValueError("Human evaluation sources must be nonempty.")
    parsed_hash = hashlib.sha256(b"".join(bytes.fromhex(row_sha(row)) for row in rows)).hexdigest()
    if parsed_hash != manifest.get("parsed_rows_sha256"):
        raise ValueError("Source row hash commitment changed.")
    distinct = len({row["review_text"] for row in rows})
    if distinct != manifest.get("distinct_exact_texts"):
        raise ValueError("Source distinct-text count changed.")
    groups = _json(groups_path.read_text(encoding="utf-8"))
    if set(groups) != set(GROUP_COUNTS):
        raise ValueError("Exactly the predeclared 50/150 groups are required.")
    for name, count in GROUP_COUNTS.items():
        if not isinstance(groups[name], list) or len(groups[name]) != count:
            raise ValueError("Human evaluation group size changed.")
        if any(not isinstance(value, str) for value in groups[name]):
            raise ValueError("Group memberships must contain only source IDs.")
    if [value for name in GROUP_COUNTS for value in groups[name]] != ids:
        raise ValueError("Source IDs must match the complete frozen 50/150 group order.")
    texts = {row["review_id"]: row["review_text"] for row in rows}
    if ({texts[value] for value in groups["mandatory_golden_50"]}
            & {texts[value] for value in groups["fresh_text_disjoint_150"]}):
        raise ValueError("Human evaluation groups must be exact-text disjoint.")
    validation = manifest.get("validation", {})
    for flag in ("all_200_exact_text_hashes_match", "all_200_membership_row_hashes_match",
                 "exactly_six_original_fields", "source_checksum_verified"):
        if validation.get(flag) is not True:
            raise ValueError("The independently prepared source verification is incomplete.")
    if validation.get("human_answers_read") is not False or validation.get("label_columns_read") is not False:
        raise ValueError("Source preparation must attest that no human answers were read.")
    identities = {
        "sources": _identity(source_path), "manifest": _identity(manifest_path),
        "groups": _identity(groups_path), "parsed_rows_sha256": parsed_hash,
        "rows": len(rows), "distinct_exact_texts": distinct,
        "source_population_identity": manifest["source"],
    }
    return rows, groups, identities


def _validated(root: Path) -> tuple[dict, dict, list[dict], dict, dict]:
    experiment = _inside(root, EXPERIMENT)
    frozen = validate_frozen(root, experiment)
    configs = {}
    for arm in ARMS:
        config = _json((experiment / "configs" / f"{arm}.json").read_text(encoding="utf-8"))
        config["_root"] = str(root.resolve())
        if fingerprint(config) != frozen["config_fingerprints"][arm]:
            raise ValueError("Frozen configuration fingerprint mismatch.")
        if (config.get("fallback_fraction") != 0
                or config.get("max_reviews_per_request") != 10
                or config.get("max_reviews_by_role", {}).get("enrich") != 10):
            raise ValueError("Prediction requires the frozen batch10/no-fallback controls.")
        if Decimal(str(config.get("global_budget_usd"))) != GLOBAL_CAP:
            raise ValueError("Prediction must retain the existing global trial ceiling.")
        if Path(config["ledger_path"]).resolve() != (root / "data/spend.sqlite3").resolve():
            raise ValueError("Prediction must use the existing shared spending ledger.")
        configs[arm] = config
    if Decimal(str(frozen["budget"]["shared_admission_ceiling_usd"])) != GLOBAL_CAP:
        raise ValueError("The original experiment trial ceiling changed.")
    rows, groups, identities = _read_sources(root)
    return frozen, configs, rows, groups, identities


def _plan(root: Path) -> tuple[dict, dict, list[dict], dict]:
    frozen, configs, rows, groups, identities = _validated(root)
    plan = {
        "version": "sealed-human-predictions-v1",
        "purpose": "Freeze model predictions before independently supplied human labels.",
        "comparison": {"baseline": "lightning-v5", "challenger": "glm-v6",
                       "selection": "Declared before human labels are available.",
                       "arms": list(ARMS)},
        "groups": GROUP_COUNTS,
        "source_identities": identities,
        "experiment_manifest_sha256": digest((root / EXPERIMENT / "manifest.json").read_bytes()),
        "implementation_hashes": frozen["implementation_hashes"],
        "runner_sha256": digest(Path(__file__).read_bytes()),
        "config_identities": {
            arm: {"config_file_sha256": frozen["config_file_hashes"][arm],
                  "label_config": frozen["config_fingerprints"][arm],
                  "provider": configs[arm]["providers"]["enrich"],
                  "model": configs[arm]["models"]["enrich"],
                  "reasoning_effort": configs[arm]["reasoning_effort"]["enrich"],
                  "prompt_version": configs[arm]["prompt_version"]}
            for arm in ARMS
        },
        "controls": {"batch_size": 10, "workers": 1, "fallback_fraction": 0,
                     "same_original_ids_and_order": True,
                     "cache": "Separate empty private cache per arm; original-ID metrics.",
                     "inference_configuration_unchanged": True,
                     "private_artifacts": str(PRIVATE)},
        "metrics": {
            "primary": {"name": "topic_accuracy",
                        "comparison": "Paired challenger-minus-baseline accuracy on the same original IDs.",
                        "reporting": "Report golden50 and fresh150 separately; pooled200 is descriptive."},
            "secondary": {
                "joint_core_accuracy": "Topic, intent, and integer severity all exactly correct.",
                "intent_macro_f1": "Unweighted macro F1 across the five fixed intent labels; zero division is zero.",
                "severity_mae": "Mean absolute difference on the 1..5 severity scale.",
                "sentiment_mae": "Mean absolute difference on the -1..1 sentiment scale.",
                "routing": "Raw and audited needs_review rates, error capture and unflagged error rate.",
            },
            "missing_predictions": "Count as incorrect for accuracy; report missingness and MAE coverage explicitly.",
            "ambiguous_or_missing_human_labels": "Report counts; omit unlabeled dimensions without adjudicating them by model output.",
            "ground_truth": "Only independently supplied human labels, after both arms are sealed.",
            "human_answers_read": False, "model_outputs_inspected": False,
        },
        "budget": {"per_arm_ceiling_usd": PER_ARM_CAP,
                   "shared_admission_ceiling_usd": float(GLOBAL_CAP),
                   "new_authorization_or_credit_purchase": False},
    }
    return plan, configs, rows, groups


def prepare(root: Path) -> dict:
    root = root.resolve()
    plan, _, _, _ = _plan(root)
    path = _inside(root, SOURCE_PACK / PLAN_NAME)
    # O_EXCL makes the declaration immutable, including simultaneous callers.
    plan["created_at"] = utcnow()
    with path.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"rows": plan["source_identities"]["rows"], "groups": plan["groups"],
            "plan_sha256": digest(path.read_bytes()),
            "source_sha256": plan["source_identities"]["sources"]["sha256"],
            "config_identities": plan["config_identities"], "budget": plan["budget"]}


async def run(root: Path, arm: str, *, execute_paid: bool = False) -> dict:
    if not execute_paid:
        raise ValueError("--execute-paid is required.")
    if arm not in ARMS:
        raise ValueError("Only the two predeclared comparison arms may execute.")
    root = root.resolve()
    expected, configs, rows, groups = _plan(root)
    plan_path = _inside(root, SOURCE_PACK / PLAN_NAME)
    plan = _json(plan_path.read_text(encoding="utf-8"))
    declared = {key: value for key, value in plan.items() if key != "created_at"}
    if declared != expected or not isinstance(plan.get("created_at"), str):
        raise ValueError("The public prediction plan changed; no inference admitted.")
    # Reading ledger totals is allowed; prediction results never enter this ledger.
    snapshot = ledger_snapshot(root / "data/spend.sqlite3")
    if snapshot["reserved_usd"]:
        raise ValueError("Wait for in-flight requests before starting a sealed arm.")
    if Decimal(str(snapshot["committed_usd"])) >= GLOBAL_CAP:
        raise ValueError("The existing shared trial allocation is exhausted.")
    private = _inside(root, PRIVATE)
    arm_dir = _inside(root, PRIVATE / arm)
    if arm_dir.exists():
        raise ValueError("Prediction arm already exists; refusing a duplicate billed run.")
    previous_umask = os.umask(0o077)
    try:
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(private, 0o700)
        arm_dir.mkdir(mode=0o700)  # Exclusive claim: a concurrent runner loses here.
        cache, output = arm_dir / "cache.sqlite3", arm_dir / "run"
        atomic_json(arm_dir / "prediction_identity.json", {
            "arm": arm, "prediction_plan_sha256": digest(plan_path.read_bytes()),
            "source_identities": expected["source_identities"],
            "config_identity": expected["config_identities"][arm],
            "groups": groups, "created_at": utcnow(), "human_answers_read": False,
        })
        engine = Engine(configs[arm], cache, output, budget_usd=PER_ARM_CAP, workers=1)
        exception_name = None
        try:
            await engine.enrich(rows)
        except BaseException as exc:
            exception_name = type(exc).__name__
            raise
        finally:
            try:
                summary = engine.finish()
                # Hash private bytes without parsing or inspecting predictions.
                artifacts = {
                    str(path.relative_to(arm_dir)): _identity(path)
                    for path in sorted(output.rglob("*")) if path.is_file()
                }
                result = {
                    "arm": arm, "completed": summary["completed"], "input_count": len(rows),
                    "requests": summary["requests"], "failed_attempts": summary["failed_attempts"],
                    "api_cost_usd": summary["api_cost_usd"],
                    "api_cost_complete": summary["api_cost_complete"],
                    "unknown_charge_hold_usd": summary.get("spending", {}).get("unknown_charge_hold_usd", 0),
                    "all_inputs_completed": summary["completed"] == len(rows),
                    "prediction_plan_sha256": digest(plan_path.read_bytes()),
                    "source_sha256": expected["source_identities"]["sources"]["sha256"],
                    "config_identity": expected["config_identities"][arm],
                    "artifacts_sha256": digest(canonical(artifacts)),
                }
                atomic_json(arm_dir / "sealed_artifacts.json",
                            {"artifacts": artifacts, "summary": result,
                             "terminal_exception": exception_name, "sealed_at": utcnow()})
            finally:
                await engine.close()
    finally:
        os.umask(previous_umask)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--execute-paid", action="store_true")
    args = parser.parse_args()
    if args.command == "run" and not args.execute_paid:
        parser.error("No inference made. --execute-paid is required.")
    if args.command == "run" and not args.arm:
        parser.error("--arm is required for run.")
    try:
        if args.command == "prepare":
            result = prepare(args.root)
        else:
            from dotenv import load_dotenv
            load_dotenv(args.root.resolve() / ".env")
            result = asyncio.run(run(args.root, args.arm, execute_paid=True))
        print(json.dumps(result, indent=2))
    except Exception as exc:
        # Provider exceptions can contain response text: never expose it publicly.
        parser.exit(2, f"Sealed prediction operation stopped ({type(exc).__name__}); "
                    "no prediction content is printed.\n")
    if args.command == "run" and not result["all_inputs_completed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
