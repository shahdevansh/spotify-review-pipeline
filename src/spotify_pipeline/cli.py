"""Explicit paid execution and offline-first commands for the review pipeline."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _print(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _credentials():
    load_dotenv(ROOT / ".env", override=False)
    return {name: bool(os.environ.get(name)) for name in
            ("TYPESAFE_API_KEY", "VERCEL_TYPESAFE_API_KEY", "OPENAI_API_KEY", "NEBIUS_API_KEY",
             "DATABASE_URL", "DATABASE_READONLY_URL")}


def _require_paid(args):
    if not args.execute_paid:
        raise ValueError("Paid execution is disabled. Add --execute-paid to explicitly run model calls.")
    available = _credentials()
    config_path = Path(getattr(args, "config", ROOT / "config/pipeline.json"))
    config = json.loads(config_path.read_text())
    from .engine import ROLE_PROVIDERS, role_provider
    declared = config.get("providers", {})
    if not isinstance(declared, dict) or set(declared) - set(ROLE_PROVIDERS):
        raise ValueError("Unsupported provider role configuration; no calls made.")
    providers = {role_provider(config, role) for role in ROLE_PROVIDERS}
    if providers - {"jev", "openai", "nebius"}:
        raise ValueError("Unsupported provider; no calls made.")
    required = set()
    if "jev" in providers:
        transport = config.get("jev_transport", "direct")
        if transport not in {"direct", "vercel_gateway"}:
            raise ValueError("Unsupported Jev transport; no calls made.")
        required.add("VERCEL_TYPESAFE_API_KEY" if transport == "vercel_gateway" else "TYPESAFE_API_KEY")
    required.update({"openai": "OPENAI_API_KEY", "nebius": "NEBIUS_API_KEY"}[provider]
                    for provider in providers - {"jev"})
    missing = [key for key in sorted(required) if not available.get(key)]
    if missing:
        raise ValueError("Configure " + ", ".join(missing) + f" in the ignored {ROOT / '.env'}. No calls made.")


@contextmanager
def _cache_lock(path: Path):
    """One CLI writer per result cache; the spend ledger stays shared across caches."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("This result cache is already in use by another pipeline process.") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _cache_counts(path: Path) -> dict[str, int]:
    """Read only; an existing experiment must never be silently renamed 'cold'."""
    if not path.exists():
        return {}
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
        present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("records", "text_cache", "task_cache", "calls") if name in present}


def _run_identity(args, config: dict) -> dict:
    from .data import file_sha256
    from .engine import fingerprint
    return {
        "input_path": str(Path(args.input).resolve()),
        "input_sha256": file_sha256(args.input),
        "label_config": fingerprint(config),
        "cache_path": str(Path(args.db).resolve()),
        "cache_mode": getattr(args, "cache_mode", "incremental"),
        "verify_count": args.verify_count,
        "workers": args.workers,
    }


def _prepare_run(out: Path, identity: dict) -> tuple[dict, dict | None]:
    """Freeze identity before calls. Completed measurements are immutable."""
    from .storage import atomic_json, utcnow
    manifest_path = out / "run_manifest.json"
    summary_path = out / "run_summary.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["identity"] != identity:
            raise ValueError("This run's input/configuration/cache/settings changed. Use a new --out and a new --db for a new cold experiment.")
        if not Path(identity["cache_path"]).exists():
            raise ValueError("The original result cache is missing; do not resume or relabel this saved experiment.")
        previous = json.loads(summary_path.read_text()) if summary_path.exists() else None
        if previous and previous.get("execution_status") == "completed":
            required = ("records.jsonl", "calls.jsonl", "verification.jsonl", "issues.json", "recommendations.json")
            missing = [name for name in required if not (out / name).is_file()]
            if missing:
                raise ValueError(f"Completed run is missing saved artifacts: {missing}. Restore them before continuing.")
        return manifest, previous
    if summary_path.exists() or (out.exists() and any(out.iterdir())):
        raise ValueError("The output directory contains evidence without a matching run manifest. Use a new --out; saved evidence was preserved.")
    cache_counts = _cache_counts(Path(identity["cache_path"]))
    if identity["cache_mode"] == "cold" and any(cache_counts.values()):
        raise ValueError("Cold experiment requires an empty result/task/call cache. Use a new --db; the shared spending ledger must remain unchanged.")
    manifest = {"version": "pipeline-run-manifest-v1", "identity": identity,
                "created_at": utcnow(), "initial_cache_counts": cache_counts,
                "empty_cache_at_start": not any(cache_counts.values())}
    atomic_json(manifest_path, manifest)
    return manifest, None


def _postprocess_run(out: Path, args, result: dict) -> dict:
    """All reporting is offline and uses incremental calls, never evidence-call copies."""
    from .cost import calculate_cost
    from .evaluation import compare_verifier, learning_report
    verifier_path = out / "verification.jsonl"
    if verifier_path.exists():
        compare_verifier(out / "records.jsonl", verifier_path, out / "evals")
    cost = calculate_cost(
        out / "calls.jsonl", getattr(args, "rates", str(ROOT / "config/rates.csv")),
        output_dir=out / "cost",
        prior_spend_usd=result.get("global_spending", {}).get("committed_usd", 0),
        spending_limit_usd=18.0,
    )
    if result.get("input_count") == 1000:
        learning_report(out, cost_report=cost)
    return cost


def _pilot_stage_ready(result: dict, name: str, verify_count: int) -> None:
    """Completed control flow is insufficient: stop expansion on incomplete evidence."""
    if result.get("execution_status") != "completed" or result.get("completed") != result.get("input_count"):
        raise ValueError(f"Pilot stage {name} is incomplete; inspect its saved failures before expansion.")
    if result.get("api_cost_complete") is not True:
        raise ValueError(f"Pilot stage {name} has unresolved billed usage; reconcile it before expansion.")
    global_spending = result.get("global_spending", {})
    if global_spending.get("reserved_usd", 0):
        raise ValueError("Shared spending contains an in-flight reservation; reconcile it before expansion.")
    # Prior experiments' unknown charges remain fully held by the shared ledger.
    # They reduce every subsequent admission budget, without turning a fully
    # measured current stage into an unmeasured one.
    if global_spending.get("committed_usd", 0) > result.get("global_budget_usd", 18):
        raise ValueError("Shared spending plus retained uncertainty exceeds the budget; do not expand.")
    verification = result.get("stages", {}).get("verify", {})
    if verification.get("completed", 0) != verify_count:
        raise ValueError(f"Pilot stage {name} has incomplete independent verification; inspect before expansion.")


async def _run(args):
    _require_paid(args)
    from .data import read_reviews
    from .engine import Engine, load_config
    from .analysis import run_analysis
    from .storage import atomic_json
    started = time.monotonic()
    config = load_config(args.config)
    config["global_budget_usd"] = args.global_budget
    out = Path(args.out)
    with _cache_lock(Path(args.db)):
        identity = _run_identity(args, config)
        manifest, previous = _prepare_run(out, identity)
        if previous and previous.get("execution_status") == "completed":
            _print({"status": "already_completed", "out": str(out), "saved_measurements_unchanged": True})
            return previous
        rows = list(read_reviews(Path(args.input)))
        engine = Engine(config, Path(args.db), out, budget_usd=args.budget, workers=args.workers)
        prior_wall = previous.get("wall_seconds", 0.0) if previous else 0.0
        sessions = list(previous.get("sessions", [])) if previous else []
        status = "failed"
        try:
            interrupted_cold = identity["cache_mode"] == "cold" and any(_cache_counts(Path(args.db)).values())
            phase = "resume" if previous is not None or interrupted_cold else args.phase
            records = await engine.enrich(rows, phase=phase, stop_after=args.stop_after)
            if args.stop_after is None:
                await engine.verify(rows, records, args.verify_count)
                await run_analysis(records, out, engine.model_task)
                expected_verified = min(args.verify_count, sum(r["status"] == "completed" for r in records))
                verified = engine.stages.get("verify", {}).get("completed", 0)
                status = "completed" if not any(r["status"] == "pending" for r in records) and verified == expected_verified else "incomplete"
            else:
                status = "paused"
        except (KeyboardInterrupt, asyncio.CancelledError):
            status = "interrupted"
            raise
        finally:
            try:
                result = engine.finish()
                session_wall = time.monotonic() - started
                sessions.append({"phase": engine.phase, "wall_seconds": session_wall, "status": status})
                result.update(identity, execution_status=status,
                              wall_seconds=prior_wall + session_wall,
                              wall_time_definition="sum of measured active CLI sessions; excludes time stopped between resumes",
                              sessions=sessions, empty_cache_at_start=manifest["empty_cache_at_start"])
                atomic_json(out / "run_summary.json", result)
            finally:
                await engine.close()
        _postprocess_run(out, args, result)
        _print(result)
        return result


async def _pilot(args):
    """Run only 100 -> warm100 -> 500 -> 1000. Never silently scale further."""
    _require_paid(args)
    source, out = Path(args.source), Path(args.out)
    learning = Path(args.learning)
    if not learning.exists():
        raise ValueError("Run prepare before pilot; the deterministic learning_1000.csv is missing.")
    from .data import file_sha256
    source_manifest = json.loads((ROOT / "vendor/course/manifest.json").read_text())
    for name in ("cost_100.csv", "checkpoint_500.csv"):
        expected = source_manifest["files"][name]["sha256"]
        if file_sha256(source / name) != expected:
            raise ValueError(f"The fixed {name} checksum no longer matches the course manifest.")
    stages = [
        ("100-cold", source / "cost_100.csv", 1, 10),
        ("100-warm", source / "cost_100.csv", 1, 10),
        ("500", source / "checkpoint_500.csv", 2, 50),
        ("1000", learning, args.workers, 1000),
    ]
    for name, csv_path, workers, verify in stages:
        print(f"\nStarting pilot stage {name}; shared paid ceiling ${args.budget:.2f}", flush=True)
        run_args = argparse.Namespace(
            execute_paid=True, input=str(csv_path), out=str(out / name), config=args.config,
            db=args.db, budget=args.budget, global_budget=args.budget,
            workers=workers, verify_count=verify, phase="initial", stop_after=None,
            cache_mode="cold" if name == "100-cold" else "warm" if name == "100-warm" else "incremental",
            rates=args.rates)
        result = await _run(run_args)
        _pilot_stage_ready(result, name, verify)
        if name == "100-warm":
            calls = [json.loads(line) for line in (out / name / "calls.jsonl").read_text().splitlines() if line.strip()]
            if any(call.get("role") == "enrich" for call in calls):
                raise ValueError("Warm replay made enrichment calls; investigate changed or incomplete cached results.")
    from .learning import learning_report
    _print(learning_report(out, Path(args.rates), budget=args.budget))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    pre = sub.add_parser("preflight", help="Show credential presence only; no paid calls")
    pre.add_argument("--json", action="store_true")
    prep = sub.add_parser("prepare", help="Verify source and create deterministic subsets")
    prep.add_argument("--source", default=str(ROOT / "data/source"))
    prep.add_argument("--out", default=str(ROOT / "data"))
    prep.add_argument("--target", type=int, default=210000)
    for name in ("run", "pilot"):
        p = sub.add_parser(name, help="Explicit paid pipeline execution" if name == "run" else "Bounded 1000-review learning run")
        p.add_argument("--execute-paid", action="store_true")
        p.add_argument("--config", default=str(ROOT / "config/pipeline.json"))
        p.add_argument("--db", default=str(ROOT / ("data/pilot_cache.sqlite3" if name == "pilot" else "data/state.sqlite3")))
        p.add_argument("--budget", type=float, default=1.50)
        p.add_argument("--workers", type=int, default=4 if name == "pilot" else 1)
        if name == "run":
            p.add_argument("--input", required=True)
            p.add_argument("--out", required=True)
            p.add_argument("--global-budget", type=float, default=18)
            p.add_argument("--verify-count", type=int, default=10)
            p.add_argument("--phase", choices=("initial", "resume"), default="initial")
            p.add_argument("--stop-after", type=int)
            p.add_argument("--cache-mode", choices=("cold", "warm", "incremental"), default="incremental")
            p.add_argument("--rates", default=str(ROOT / "config/rates.csv"))
        else:
            p.add_argument("--source", default=str(ROOT / "data/source"))
            p.add_argument("--learning", default=str(ROOT / "data/learning_1000.csv"))
            p.add_argument("--out", default=str(ROOT / "runs/pilot"))
            p.add_argument("--rates", default=str(ROOT / "config/rates.csv"))
    replay = sub.add_parser("replay", help="Offline cost arithmetic; never makes model calls")
    replay.add_argument("--calls", default=str(ROOT / "cost/pilot_calls.jsonl"))
    replay.add_argument("--rates", default=str(ROOT / "config/rates.csv"))
    replay.add_argument("--out", default=str(ROOT / "cost/replay"))
    rerank = sub.add_parser("rerank", help="Rebuild membership, ranking and claims without models")
    rerank.add_argument("--run", required=True)
    evaluate = sub.add_parser("evaluate", help="Compare saved predictions to human labels offline")
    evaluate.add_argument("--gold", required=True)
    evaluate.add_argument("--records", required=True)
    evaluate.add_argument("--out", default=str(ROOT / "evals/golden-results"))
    evaluate.add_argument("--human-labels-confirmed", action="store_true",
                          help="Attest that expected labels were independently supplied by a person")
    export = sub.add_parser("export", help="Export the standardized grading evidence")
    export.add_argument("--run", required=True)
    export.add_argument("--out", default=str(ROOT / "grading"))
    export.add_argument("--ingestion", default=str(ROOT / "data/ingestion.json"))
    export.add_argument("--source", default=str(ROOT / "data/source/spotify_reviews_18months.csv"))
    export.add_argument("--analysis", required=True)
    database = sub.add_parser("publish-data", help="Import a saved run into configured Postgres")
    database.add_argument("--run", required=True)
    database.add_argument("--ingestion", default=str(ROOT / "data/ingestion_report.json"))
    database.add_argument("--evaluation")
    learn = sub.add_parser("learning-report", help="Summarize saved pilot evidence; no calls")
    learn.add_argument("--pilot", default=str(ROOT / "runs/pilot"))
    learn.add_argument("--rates", default=str(ROOT / "config/rates.csv"))
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            _print({"credentials": _credentials(), "paid_calls": 0,
                    "pilot_limit_usd": 1.50, "global_limit_usd": 18.0})
        elif args.command == "prepare":
            from .data import prepare
            _print(prepare(Path(args.source), Path(args.out), target=args.target))
        elif args.command == "run":
            asyncio.run(_run(args))
        elif args.command == "pilot":
            asyncio.run(_pilot(args))
        elif args.command in ("replay", None):
            from .cost import calculate_cost
            if args.command is None:
                parser.print_help()
                print("\nDefault behavior is offline. Use replay for saved cost evidence; run/pilot require --execute-paid.")
            else:
                _print(calculate_cost(Path(args.calls), Path(args.rates), output_dir=Path(args.out)))
        elif args.command == "rerank":
            from .analysis import rerank
            _print(rerank(Path(args.run)))
        elif args.command == "evaluate":
            from .evaluation import evaluate_golden
            _print(evaluate_golden(Path(args.gold), Path(args.records), Path(args.out),
                                   human_labels_confirmed=args.human_labels_confirmed))
        elif args.command == "export":
            from .export import export_grading
            _print(export_grading(Path(args.run), Path(args.out),
                                 ingestion_path=Path(args.ingestion), source_path=Path(args.source),
                                 analysis_path=Path(args.analysis)))
        elif args.command == "publish-data":
            load_dotenv(ROOT / ".env", override=False)
            from .database import import_run
            _print(import_run(Path(args.run), ingestion_report=Path(args.ingestion),
                              evaluation_path=Path(args.evaluation) if args.evaluation else None))
        elif args.command == "learning-report":
            from .learning import learning_report
            _print(learning_report(Path(args.pilot), Path(args.rates)))
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; completed checkpoints remain saved. Resume with unchanged configuration.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
