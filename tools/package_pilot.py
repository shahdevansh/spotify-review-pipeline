"""Package and replay the actual fixed-100 cold/warm evidence, entirely offline.

Only an explicit whitelist of saved files is copied. Historical evidence_calls
are never included in measured pilot_calls. Existing destinations are immutable.
The packaged calculator and this script use only the Python standard library.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
import tempfile
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("review_id", "review_text", "review_rating", "review_likes",
          "app_version", "review_timestamp")
REQUIRED = ("records.jsonl", "calls.jsonl", "run_summary.json",
            "run_manifest.json", "configuration.json", "verification.jsonl",
            "issues.json", "membership.csv", "ranking.csv", "claims.csv",
            "recommendations.json", "memo.md")
OPTIONAL = ("disagreements.jsonl", "checkpoint_start.json",
            "checkpoint_before.json", "checkpoint_after.json")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def calculator(source=None):
    source = Path(source) if source else ROOT / "src/spotify_pipeline/cost.py"
    if not source.is_file():
        source = Path(__file__).resolve().with_name("cost.py")
    require(source.is_file(), "Offline calculator source is missing.")
    # Avoid writing __pycache__ into an immutable saved evidence package.
    module = types.ModuleType("offline_pilot_cost")
    exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), module.__dict__)
    return source, module


def validate_stage(path, mode, source, checksum):
    path = Path(path)
    missing = [name for name in REQUIRED if not (path / name).is_file()]
    require(not missing, f"{mode} stage is not ready; missing artifacts: {missing}. No package written.")
    summary = read_json(path / "run_summary.json")
    manifest = read_json(path / "run_manifest.json")
    config = read_json(path / "configuration.json")
    calls = read_jsonl(path / "calls.jsonl")
    records = read_jsonl(path / "records.jsonl")
    identity = manifest.get("identity", {})
    require(summary.get("execution_status") == "completed",
            f"{mode} stage is {summary.get('execution_status', 'unknown')}; preserve it and finish the run first.")
    require(summary.get("cache_mode") == mode and identity.get("cache_mode") == mode,
            f"{mode} stage does not declare the required cache mode.")
    require(summary.get("input_sha256") == checksum == identity.get("input_sha256"),
            f"{mode} input checksum differs from the unchanged cost_100.csv.")
    require(summary.get("input_count") == summary.get("completed") == len(source) == 100,
            f"{mode} must contain exactly 100 completed fixed-input records.")
    require(summary.get("quarantined", 0) == summary.get("pending", 0) == 0,
            f"{mode} still has pending or quarantined pilot records.")
    require(summary.get("api_cost_complete") is True,
            f"{mode} stage has unresolved usage; reconcile it before packaging complete evidence.")
    wall = summary.get("wall_seconds")
    require(type(wall) in (int, float) and math.isfinite(wall) and wall > 0,
            f"{mode} is missing a valid measured wall time.")
    require(summary.get("label_config") == identity.get("label_config"),
            f"{mode} label configuration differs between manifest and summary.")
    if mode == "cold":
        require(summary.get("workers") == identity.get("workers") == 1,
                "The required cold-100 measurement must use one worker.")
        require(manifest.get("empty_cache_at_start") is True
                and summary.get("empty_cache_at_start") is True,
                "Cold run has no evidence that its result cache started empty.")
    else:
        require(not any(call.get("role") == "enrich" for call in calls),
                "Warm replay made enrichment calls; inspect the saved evidence before packaging.")
    expected = {row["review_id"]: row for row in source}
    observed = [row.get("review_id") for row in records]
    require(len(observed) == len(set(observed)) == 100 and set(observed) == set(expected),
            f"{mode} records have missing, duplicate, or foreign IDs.")
    for row in records:
        original = expected[row["review_id"]]
        canonical = json.dumps([original[key] for key in FIELDS], ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False)
        require(all(row.get(key) == original[key] for key in FIELDS)
                and row.get("source_sha256") == hashlib.sha256(canonical.encode()).hexdigest(),
                f"{mode} source values/hash differ for {row['review_id']}.")
        require(row.get("status") == "completed" and row.get("label_config") == summary["label_config"],
                f"{mode} contains an incomplete or different-configuration record.")
    request_ids = [call.get("request_id") for call in calls]
    require(all(isinstance(value, str) and value for value in request_ids)
            and len(request_ids) == len(set(request_ids)),
            f"{mode} calls contain missing or duplicate request IDs.")
    require(all(call.get("run_id") == summary.get("run_id") for call in calls),
            f"{mode} calls.jsonl contains another run's historical calls.")
    require(all(call.get("label_config") == summary["label_config"] for call in calls),
            f"{mode} call evidence mixes label configurations.")
    require(all(len(call.get("review_ids", [])) <= 50 for call in calls if call.get("role") == "enrich"),
            f"{mode} contains an enrichment request exceeding 50 reviews.")
    require(len(calls) == summary.get("requests") == summary.get("attempts"),
            f"{mode} call count differs from the saved summary.")
    verify_count = identity.get("verify_count")
    verification = read_jsonl(path / "verification.jsonl")
    require(type(verify_count) is int and verify_count > 0
            and len(verification) == verify_count
            and all(row.get("status") == "completed" and row.get("blind") is True for row in verification)
            and summary.get("stages", {}).get("verify", {}).get("completed") == verify_count,
            f"{mode} independent verification is missing or incomplete.")
    if mode == "cold":
        require(all(any(call.get("role") == role and call.get("outcome") == "succeeded" for call in calls)
                    for role in ("enrich", "verify", "group", "memo")),
                "Cold pilot must include successful enrichment, verification, grouping, and memo calls.")
    return summary, config, calls


def csv_rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, default_fields):
    fields = list(dict.fromkeys(key for row in rows for key in row)) or default_fields
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def combine_calls(snapshots, destination):
    with destination.open("wb") as stream:
        for mode in ("cold", "warm"):
            data = (snapshots / mode / "calls.jsonl").read_bytes()
            stream.write(data)
            if data and not data.endswith(b"\n"):
                stream.write(b"\n")


def build_reports(package, out, rates, options):
    _, module = calculator(package / "calculator/cost.py")
    reports, summaries, configs = {}, {}, {}
    usage, measured_calls = [], []
    for mode in ("cold", "warm"):
        stage = package / "snapshots" / mode
        summaries[mode] = read_json(stage / "run_summary.json")
        configs[mode] = read_json(stage / "configuration.json")
        config = configs[mode]
        args = dict(options)
        args.update(output_token_cap=config.get("max_output_tokens", 6000),
                    max_workers=config.get("max_workers", 1),
                    fallback_fraction=config.get("fallback_fraction", .05))
        reports[mode] = module.calculate_cost(stage / "calls.jsonl", rates,
                                             output_dir=out / mode, **args)
        for name, combined in (("usage.csv", usage), ("measured_calls.csv", measured_calls)):
            combined.extend({"measurement": mode, **row} for row in csv_rows(out / mode / name))
    shutil.copyfile(package / "snapshots/cold/records.jsonl", out / "pilot_records.jsonl")
    combine_calls(package / "snapshots", out / "pilot_calls.jsonl")
    if rates.resolve() != (out / "rates.csv").resolve():
        shutil.copyfile(rates, out / "rates.csv")
    write_csv(out / "usage.csv", usage, ["measurement", "request_id", "category", "units", "rate_key"])
    write_csv(out / "measured_calls.csv", measured_calls, ["measurement", "request_id", "api_cost_usd"])
    report = {
        "schema_version": "measured-pilot-package-v1", "mode": "offline", "currency": "USD",
        "input_sha256": summaries["cold"]["input_sha256"],
        "label_config": summaries["cold"]["label_config"],
        "measurements": {mode: value["measurements"] for mode, value in reports.items()},
        "stage_details": {mode: value["stages"] for mode, value in reports.items()},
        "model_settings": {mode: summaries[mode].get("model_settings", {
            key: configs[mode].get(key) for key in ("models", "providers", "reasoning_effort")
        }) for mode in reports},
        "run_summaries": summaries,
        "cold_calibrated_projections": reports["cold"]["projections"],
        "projection_options": options,
        "scope": "Only actual calls from the fixed-100 cold and warm runs; no historic cache-origin copies or separate experiments.",
        "cash_outlay": {"status": "not_reconciled", "incremental_cash_purchase_usd": None},
        "limitations": [
            "Model agreement is not human-label accuracy.",
            "Token-rate cost is economic consumption; verified invoice, credit debit, and cash expense are separate.",
            "Cold and warm wall times are separate measured active-session durations; summed call durations are not wall time.",
            "Cold and warm records are the same 100 original IDs, not 200 unique processed reviews.",
            "Projections are calibrated only from the cold run and are estimates, not execution evidence.",
            "Prior experiments and their retained uncertainty appear in saved global ledger snapshots but are excluded from pilot calls and measured pilot cost.",
            "Local-compute cost remains unknown unless an explicit hourly estimate is supplied.",
        ],
    }
    write_json(out / "report.json", report)
    lines = ["# Measured fixed-100 cold/warm pilot", "",
             "Generated offline from saved evidence. No credentials or model calls are required.", "",
             f"Input checksum: `{report['input_sha256']}`.",
             f"Frozen label configuration: `{report['label_config']}`.", "",
             "| Measurement | Inputs | Completed | Unique texts | Cache hits | Calls | Nominal API USD | Wall seconds |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for mode, item in report["measurements"].items():
        lines.append(f"| {mode} | {item['input_count']} | {item['completed_records']} | "
                     f"{item['unique_texts']} | {item['cache_hits']} | {item['attempts']} | "
                     f"{item['api_cost_usd']} | {item['wall_seconds']} |")
    lines += ["", "## Configuration and stage evidence", "",
              "The exact provider/model/effort, prompt/schema versions, batch sizes, worker counts, "
              "usage, failures, and retries are in each measurement's `report.json`, `stage_costs.csv`, "
              "and the byte-preserved `snapshots/` inputs. Combined `usage.csv` identifies its cold/warm measurement.",
              "Warm downstream calls, if any, remain included in the warm cost. `pilot_calls.jsonl` contains "
              "only actual cold/warm attempts; cached historical evidence is not counted again.", "",
              "## Offline replay", "",
              "From the original package directory, using only Python 3.11+:", "", "```sh",
              "python calculator/package_pilot.py replay --package . --out replay", "```", "",
              "Edit a copy of `rates.csv` and pass `--rates path/to/edited_rates.csv` to reprice "
              "the unchanged usage. Projection flags change estimates only. Choose a new output path "
              "for every replay; existing evidence is never overwritten.", "",
              "The replay command is also available from the repository as "
              "`python tools/package_pilot.py replay --package cost/measured-100 --out cost/replay`.", "",
              "## Limits", ""] + ["- " + line for line in report["limitations"]]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def projection_options(args, saved=None):
    values = dict(saved or {})
    for key in ("selected_reviews", "selected_unique_texts", "full_reviews", "full_unique_texts",
                "verification_fraction", "spending_limit_usd", "prior_spend_usd",
                "conservative_multiplier", "local_compute_usd_per_hour", "empty_text_quarantines"):
        value = getattr(args, key, None)
        if value is not None:
            values[key] = value
    return values


def fresh_destination(path):
    require(not path.exists(), f"Destination already exists: {path}. Choose a new --out; saved measurements are preserved.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{path.name}-", dir=path.parent))


def make_archive(package, destination):
    require(not destination.exists(), f"Archive already exists: {destination}. Choose a new archive path.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                entry = zipfile.ZipInfo(str(path.relative_to(package)), date_time=(2026, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, path.read_bytes())
    return {"path": str(destination), "sha256": sha(destination), "bytes": destination.stat().st_size}


def package_pilot(args):
    source = Path(args.input)
    checksum = sha(source)
    course = read_json(args.course_manifest)
    require(checksum == course["files"]["cost_100.csv"]["sha256"],
            "Input is not the unchanged fixed course cost_100.csv.")
    original = csv_rows(source)
    cold, config, cold_calls = validate_stage(args.cold, "cold", original, checksum)
    warm, warm_config, warm_calls = validate_stage(args.warm, "warm", original, checksum)
    require(cold["label_config"] == warm["label_config"] and config == warm_config,
            "Cold/warm settings differ; this is not an unchanged-configuration warm replay.")
    require(cold["run_id"] != warm["run_id"], "Cold/warm must have distinct run IDs.")
    require(not ({call["request_id"] for call in cold_calls} & {call["request_id"] for call in warm_calls}),
            "Cold/warm call logs repeat request IDs; historical copies must not be counted twice.")
    output = Path(args.out).resolve()
    if args.archive:
        archive = Path(args.archive).resolve()
        require(not archive.is_relative_to(output), "Archive must be outside the package directory.")
        require(not archive.exists(), f"Archive already exists: {archive}.")
    temporary = fresh_destination(output)
    try:
        for mode, origin in (("cold", Path(args.cold)), ("warm", Path(args.warm))):
            target = temporary / "snapshots" / mode
            target.mkdir(parents=True)
            for name in REQUIRED + OPTIONAL:
                if (origin / name).is_file():
                    shutil.copyfile(origin / name, target / name)
        (temporary / "source").mkdir()
        shutil.copyfile(source, temporary / "source/cost_100.csv")
        shutil.copyfile(args.course_manifest, temporary / "source/course_manifest.json")
        (temporary / "calculator").mkdir()
        source_module, _ = calculator()
        shutil.copyfile(source_module, temporary / "calculator/cost.py")
        shutil.copyfile(__file__, temporary / "calculator/package_pilot.py")
        options = projection_options(args)
        options.setdefault("prior_spend_usd", warm.get("global_spending", {}).get("committed_usd", 0))
        build_reports(temporary, temporary, Path(args.rates).resolve(), options)
        immutable = [p for directory in ("snapshots", "source", "calculator")
                     for p in (temporary / directory).rglob("*") if p.is_file()]
        write_json(temporary / "package_manifest.json", {
            "schema_version": "fixed-100-package-v1",
            "input_sha256": checksum, "label_config": cold["label_config"],
            "source_run_ids": {"cold": cold["run_id"], "warm": warm["run_id"]},
            "original_rates_sha256": sha(temporary / "rates.csv"),
            "immutable_files": {str(p.relative_to(temporary)): sha(p) for p in sorted(immutable)},
            "projection_options": options,
            "original_sources": {"cold": str(Path(args.cold).resolve()),
                                 "warm": str(Path(args.warm).resolve())},
        })
        # Generated reports should refer to the durable output, never staging.
        for path in temporary.rglob("*"):
            if path.is_file() and not path.is_relative_to(temporary / "snapshots") \
                    and not path.is_relative_to(temporary / "source") \
                    and not path.is_relative_to(temporary / "calculator") \
                    and path.suffix in {".json", ".md", ".csv"}:
                text = path.read_text(encoding="utf-8").replace(str(temporary), str(output))
                path.write_text(text, encoding="utf-8")
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    result = {"status": "packaged", "out": str(output), "paid_calls": 0,
              "cold_attempts": len(cold_calls), "warm_attempts": len(warm_calls)}
    if args.archive:
        result["archive"] = make_archive(output, Path(args.archive).resolve())
    return result


def replay(args):
    package = Path(args.package).resolve()
    manifest = read_json(package / "package_manifest.json")
    for name, digest in manifest["immutable_files"].items():
        target = package / name
        require(target.is_file() and sha(target) == digest,
                f"Immutable package input changed or is missing: {name}. Preserve the original evidence.")
    output = Path(args.out).resolve()
    temporary = fresh_destination(output)
    try:
        options = projection_options(args, manifest.get("projection_options", {}))
        build_reports(package, temporary,
                      Path(args.rates).resolve() if args.rates else package / "rates.csv", options)
        for path in temporary.rglob("*"):
            if path.is_file() and path.suffix in {".json", ".md", ".csv"}:
                path.write_text(path.read_text(encoding="utf-8").replace(str(temporary), str(output)),
                                encoding="utf-8")
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {"status": "replayed", "out": str(output), "paid_calls": 0}


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command")
    pack = commands.add_parser("package", help="Validate and preserve completed cold/warm measurements.")
    pack.add_argument("--cold", default=str(ROOT / "runs/pilot/100-cold"))
    pack.add_argument("--warm", default=str(ROOT / "runs/pilot/100-warm"))
    pack.add_argument("--input", default=str(ROOT / "data/source/cost_100.csv"))
    pack.add_argument("--course-manifest", default=str(ROOT / "vendor/course/manifest.json"))
    pack.add_argument("--rates", default=str(ROOT / "config/rates.csv"))
    pack.add_argument("--out", default=str(ROOT / "cost/measured-100"))
    pack.add_argument("--archive", help="Optional deterministic ZIP, outside the output directory.")
    rerun = commands.add_parser("replay", help="Reprice a saved package offline without credentials.")
    rerun.add_argument("--package", default=str(ROOT / "cost/measured-100"))
    rerun.add_argument("--rates", help="Optional edited rates CSV; defaults to packaged rates.")
    rerun.add_argument("--out", default=str(ROOT / "cost/replay"))
    for item in (pack, rerun):
        for flag in ("selected-reviews", "selected-unique-texts", "full-reviews",
                     "full-unique-texts", "empty-text-quarantines"):
            item.add_argument("--" + flag, type=int)
        for flag in ("verification-fraction", "spending-limit-usd", "prior-spend-usd",
                     "conservative-multiplier", "local-compute-usd-per-hour"):
            item.add_argument("--" + flag, type=float)
    return root


def main():
    arguments = parser()
    args = arguments.parse_args()
    if args.command is None:
        arguments.print_help()
        return 0
    try:
        print(json.dumps(package_pilot(args) if args.command == "package" else replay(args), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Cannot {args.command}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
