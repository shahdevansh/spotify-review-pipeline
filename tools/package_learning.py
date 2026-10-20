"""Offline, allowlisted first-1,000 learning release. No API calls or uploads.

Default ``plan`` only inspects readiness. ``build --ready`` takes a stable file
snapshot, exports a read-only spend ledger, scans credential values, and creates
a deterministic tar.gz. Existing release archives are never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import gzip
import hashlib
import io
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
VERSION = "spotify-learning-release-v1"
ARCHIVE_ROOT = "spotify-learning-1000"
SOURCE_FIELDS = (
    "review_id", "review_text", "review_rating", "review_likes",
    "app_version", "review_timestamp",
)
STAGES = {"100-cold": 100, "100-warm": 100, "500": 500, "1000": 1000}
REQUIRED_STAGE_FILES = (
    "records.jsonl", "calls.jsonl", "run_summary.json", "run_manifest.json",
    "configuration.json", "verification.jsonl", "membership.csv", "ranking.csv",
    "claims.csv", "issues.json", "recommendations.json", "memo.md",
)
# Every permitted source location is explicit. In particular, data/ and runs/
# are never recursively admitted as a whole.
REQUIRED_FILES = (
    "README.md", "pyproject.toml", "uv.lock",
    ".env.example", "web/.env.example",
    "tools/package_learning.py", "tools/package_pilot.py",
    "config/nebius-pilot.json", "config/rates.csv", "config/labels.json",
    "validation/frozen_pilot_configuration.json",
    "data/source/cost_100.csv", "data/source/checkpoint_500.csv",
    "data/source/manifest.json", "data/learning_1000.csv",
    "data/data_manifest.json", "data/ingestion.json", "data/ingestion_report.json",
    "evals/golden-labels.html", "evals/golden_50_to_label.csv",
    "cost/measured-100/package_manifest.json", "cost/measured-100/report.json",
    "cost/measured-100/report.md",
    "runs/recovery-nebius-v5/recovery/recovery_validation.json",
    "runs/concurrency-100-w4/comparison.json",
    "runs/concurrency-100-w4.cast", "runs/recovery-nebius-v5.cast",
    "docs/learning-report.md", "docs/scaling-economics.md", "docs/scaling-economics.json",
    "grading/run.json", "grading/ingestion.json", "grading/records.jsonl",
    "grading/membership.csv", "grading/ranking.csv", "grading/claims.csv",
    "grading/calls.jsonl", "grading/checkpoint_after.json",
    "runs/recovery-nebius-v5/grading/run.json",
    "runs/recovery-nebius-v5/grading/records.jsonl",
    "runs/recovery-nebius-v5/grading/calls.jsonl",
    "runs/recovery-nebius-v5/grading/checkpoint_before.json",
    "runs/recovery-nebius-v5/grading/checkpoint_after.json",
    "evals/synthetic-live/v5-live-001/safety_report.json",
    "validation/checker_pilot.json", "validation/checker_recovery500.json",
    "validation/offline_rerank.json", "validation/cost_pilot_replay.json",
)
EXACT_FILES = REQUIRED_FILES + (
    "LICENSE", ".gitignore", "cost/README.md",
    "web/README.md", "web/package.json", "web/package-lock.json",
    "web/next.config.ts", "web/tsconfig.json", "web/.gitignore",
    "tools/reconcile_run_cost.py", "tools/record_command.py",
    "tools/recovery_demo.py", "tools/recovery_demo.sh",
    "tools/probe_nebius.py", "tools/compare_nebius.py", "tools/probe_saved_memo.py",
)
TREE_ALLOWLIST = (
    "runs/pilot", "config", "prompts", "docs", "evals", "validation",
    "cost/measured-100", "src/spotify_pipeline", "tests", "vendor/course",
    "cost/replay", "cost/replay-double-rates", "cost/replay-volume-10000",
    "runs/concurrency-100-w4", "runs/recovery-nebius-v5", "grading",
    "web/src", "web/tests", "web/scripts", "web/database",
)
HISTORY_ALLOWLIST = (
    "runs/experiment-v2-cold-memo-failure",
    "runs/experiment-v3-cold-memo-failure",
    "runs/experiment-v4-gptoss-memo-failure",
    "runs/nebius-screening",
    "runs/nebius-screening-v2",
    "runs/openai-contract-check",
    "runs/nebius-inline-schema-memo-probe",
    "runs/nebius-glm-memo-probe",
    "runs/nebius-contract-qwen",
    "runs/nebius-contract-gptoss",
)
SAFE_SUFFIXES = {
    ".py", ".sh", ".json", ".jsonl", ".csv", ".md", ".txt", ".log",
    ".toml", ".lock", ".html", ".xml", ".yaml", ".yml", ".sql",
    ".cast", ".webm", ".mp4", ".png", ".svg", ".pdf", ".ts", ".tsx", ".css",
}
DENIED_PARTS = {
    ".git", ".venv", "venv", "runtime", "node_modules", "__pycache__",
    ".pytest_cache", ".next", ".vercel", "work", "site-packages",
}
DENIED_NAMES = {"spotify_reviews_18months.csv", "source_ledger.csv"}
SECRET_KEY = re.compile(
    r"(?i)(?:API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|"
    r"(?:DATABASE|POSTGRES(?:QL)?)(?:_[A-Z0-9]+)*_URL|CONNECTION_STRING|(?:^|_)DSN$)"
)
SPEND_COLUMNS = (
    "request_id", "run_id", "reserved_nano", "charged_nano", "state",
    "created_at", "settled_at",
)


class PackageError(ValueError):
    """A safe error whose message never contains secret values or source text."""


def require(condition, message):
    if not condition:
        raise PackageError(message)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PackageError(f"Cannot read valid JSON: {path.name}") from None


def source_allowed(relative):
    parts = PurePosixPath(relative).parts
    if not parts or ".." in parts or PurePosixPath(relative).is_absolute():
        return False
    if relative in {".env.example", "web/.env.example", ".gitignore", "web/.gitignore"}:
        return True
    if any(part in DENIED_PARTS or part.startswith(".") for part in parts):
        return False
    name = parts[-1].lower()
    if name in DENIED_NAMES or name.startswith(".env"):
        return False
    if any(marker in name for marker in (".sqlite", ".db", "credential", "private-key")):
        return False
    if name.startswith("selected_") and name.endswith(".csv"):
        return False
    return Path(name).suffix in SAFE_SUFFIXES or name == "license"


def collect_files(root, include_history=True):
    """Return sorted repository-relative paths, rejecting links and odd files."""
    root = root.resolve()
    selected = set()
    ignored = []
    for relative in EXACT_FILES:
        if (root / relative).is_file():
            selected.add(relative)
    trees = TREE_ALLOWLIST + (HISTORY_ALLOWLIST if include_history else ())
    for directory in trees:
        base = root / directory
        if base.is_symlink():
            raise PackageError(f"Symlink is forbidden: {directory}")
        if not base.exists():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise PackageError(f"Symlink is forbidden: {relative}")
            if path.is_file():
                if source_allowed(relative):
                    selected.add(relative)
                else:
                    ignored.append(relative)
    for relative in selected:
        path = root / relative
        require(not path.is_symlink() and path.resolve().is_relative_to(root),
                f"Outside-root source is forbidden: {relative}")
        require(source_allowed(relative), f"Forbidden release source: {relative}")
    return sorted(selected), sorted(ignored)


def readiness(root):
    missing = [relative for relative in REQUIRED_FILES if not (root / relative).is_file()]
    failures, summaries = [], {}
    for name, expected in STAGES.items():
        stage = root / "runs/pilot" / name
        missing.extend(f"runs/pilot/{name}/{file}" for file in REQUIRED_STAGE_FILES
                       if not (stage / file).is_file())
        if not (stage / "run_summary.json").is_file():
            continue
        summary = read_json(stage / "run_summary.json")
        summaries[name] = {
            key: summary.get(key) for key in
            ("run_id", "execution_status", "input_count", "completed", "quarantined",
             "pending", "api_cost_usd", "api_cost_complete", "wall_seconds", "label_config")
        }
        if (summary.get("execution_status") != "completed"
                or summary.get("input_count") != expected
                or summary.get("completed") != expected
                or summary.get("pending", 0) != 0
                or summary.get("quarantined", 0) != 0):
            failures.append(f"runs/pilot/{name}: execution or coverage incomplete")
    configurations = {summary["label_config"] for summary in summaries.values()}
    if len(configurations) > 1 or None in configurations:
        failures.append("runs/pilot: checkpoint label configurations are inconsistent")
    recovery_validation = root / "runs/recovery-nebius-v5/recovery/recovery_validation.json"
    if recovery_validation.is_file() and read_json(recovery_validation).get("passed") is not True:
        failures.append("runs/recovery-nebius-v5: recovery validation has not passed")
    return {"ready": not missing and not failures, "missing_files": sorted(set(missing)),
            "failures": failures, "stages": summaries}


def credential_values(root):
    """Read secret assignments without importing dotenv or displaying values."""
    values = {value for key, value in os.environ.items() if SECRET_KEY.search(key) and value}
    env = root / ".env"
    if env.is_file():
        require(not env.is_symlink(), "Credential file cannot be a symlink: .env")
        try:
            text = env.read_text(encoding="utf-8")
            # dotenv permits whitespace on either side of "="; normalize only
            # assignment prefixes, retaining all quoted value content.
            text = re.sub(r"(?m)^([ \t]*(?:export[ \t]+)?[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*",
                          r"\1=", text)
            lexer = shlex.shlex(text, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = "#"
            tokens = list(lexer)
        except (OSError, ValueError):
            raise PackageError("Cannot parse credential file: .env") from None
        index = 0
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token == "export":
                continue
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", token, re.DOTALL)
            if match:
                key, value = match.groups()
            elif (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token)
                  and index + 1 < len(tokens) and tokens[index] == "="):
                key, value = token, tokens[index + 1]
                index += 2
            else:
                # Ignore no-value assignment tokens and ordinary dotenv comments.
                continue
            if SECRET_KEY.search(key) and value:
                values.add(value)
    expanded = set()
    for value in values:
        expanded.add(value.encode("utf-8"))
        expanded.add(json.dumps(value, ensure_ascii=False)[1:-1].encode("utf-8"))
        expanded.add(quote(value, safe="").encode("ascii"))
        try:
            parsed = urlsplit(value)
            if parsed.password:
                expanded.add(parsed.password.encode("utf-8"))
                expanded.add(unquote(parsed.password).encode("utf-8"))
        except ValueError:
            pass
    return sorted((value for value in expanded if value), key=len, reverse=True)


def scan_payloads(payloads, secrets):
    """On detection, expose filenames only, never values or matching excerpts."""
    matches = []
    for name, data in payloads.items():
        encoded_name = name.encode("utf-8")
        if any(secret in data or secret in encoded_name for secret in secrets):
            matches.append("<redacted filename>" if any(secret in encoded_name for secret in secrets) else name)
    require(not matches, "Credential match in packaged file(s): " + ", ".join(sorted(matches)))


def snapshot_files(root, names, snapshot_mode="direct"):
    payloads, observations = {}, {}
    require(snapshot_mode in {"direct", "apfs-clone"}, "Unsupported snapshot mode.")
    require(snapshot_mode != "apfs-clone" or sys.platform == "darwin",
            "APFS-clone snapshots require macOS; use direct mode on other systems.")
    # Some macOS FileProvider paths stall while reading their original names.
    # APFS clones retain byte identity without reading or rewriting source data.
    # Only allowlisted public candidates are cloned; .env and databases are not.
    native_clone = None
    if snapshot_mode == "apfs-clone":
        try:
            native_clone = ctypes.CDLL(None, use_errno=True).clonefile
            native_clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
            native_clone.restype = ctypes.c_int
        except AttributeError:
            pass
    with tempfile.TemporaryDirectory(prefix="spotify-release-snapshot-") as temporary:
        clone_dir = Path(temporary)
        def capture(item):
            index, name = item
            path = root / name
            stamp = lambda stat: (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            previous_data = None
            transitions = 0
            for attempt in range(3):
                require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
                        f"Unsafe source path during snapshot: {name}")
                before = path.stat()
                if snapshot_mode == "apfs-clone":
                    clone = clone_dir / f"{index}-{attempt}"
                    if native_clone is not None:
                        result = native_clone(os.fsencode(path), os.fsencode(clone), 0)
                        require(result == 0, f"Cannot clone source for snapshot: {name}")
                    else:
                        copied = subprocess.run(["/bin/cp", "-c", str(path), str(clone)],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        require(copied.returncode == 0, f"Cannot clone source for snapshot: {name}")
                    data = clone.read_bytes()
                    clone.unlink()
                else:
                    data = path.read_bytes()
                after = path.stat()
                require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
                        f"Unsafe source path during snapshot: {name}")
                require(previous_data is None or previous_data == data,
                        f"Source content changed during snapshot: {name}")
                if stamp(before) == stamp(after) and len(data) == after.st_size:
                    return name, data, {"stamp": stamp(after), "sha256": sha_bytes(data),
                                        "snapshot_mode": snapshot_mode,
                                        "metadata_transitions": transitions}
                transitions += 1
                previous_data = data
            raise PackageError(f"Source metadata did not stabilize during snapshot: {name}")
        # Independent public-file snapshots have distinct temporary paths.
        # Bounded parallelism avoids macOS FileProvider serialization stalls;
        # executor.map preserves allowlist order and archive bytes stay stable.
        if snapshot_mode == "apfs-clone":
            with ThreadPoolExecutor(max_workers=16) as executor:
                snapshots = list(executor.map(capture, enumerate(names)))
        else:
            snapshots = [capture(item) for item in enumerate(names)]
        for name, data, observed in snapshots:
            payloads[name] = data
            observations[name] = observed
    return payloads, observations


def verify_source_unchanged(root, observations):
    for name, expected in observations.items():
        path = root / name
        require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
                f"Unsafe source path before release completed: {name}")
        observed = path.stat()
        if (observed.st_size, observed.st_mtime_ns, observed.st_ino) == expected["stamp"]:
            continue
        # A metadata-only FileProvider transition is acceptable only after two
        # independent stable captures match the originally captured byte hash.
        for _ in range(2):
            payloads, repeated = snapshot_files(root, [name], expected["snapshot_mode"])
            require(sha_bytes(payloads[name]) == expected["sha256"],
                    f"Source content changed before release completed: {name}")
            expected["stamp"] = repeated[name]["stamp"]
            expected["metadata_transitions"] += repeated[name]["metadata_transitions"]
        expected["metadata_transitions"] += 1


def snapshot_summary(observations):
    return {
        "method": "Stable path/symlink/size guards; metadata transitions require identical independent byte snapshots.",
        "metadata_transition_count": sum(item["metadata_transitions"] for item in observations.values()),
        "metadata_transition_files": sorted(name for name, item in observations.items()
                                            if item["metadata_transitions"]),
    }


def spend_snapshot(path):
    """Read the public ledger columns in one read-only SQLite transaction."""
    require(path.is_file() and not path.is_symlink(), "Spend ledger is missing or unsafe.")
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(spend)")}
        require(set(SPEND_COLUMNS) <= columns, "Spend ledger schema is incomplete.")
        rows = [dict(row) for row in connection.execute(
            "SELECT " + ",".join(SPEND_COLUMNS) + " FROM spend ORDER BY created_at,request_id"
        )]
        connection.rollback()
    except sqlite3.Error:
        raise PackageError("Cannot read the spend ledger safely.") from None
    finally:
        if connection:
            connection.close()
    for row in rows:
        require(type(row["reserved_nano"]) is int and row["reserved_nano"] >= 0,
                "Spend ledger contains an invalid reservation.")
        require(row["charged_nano"] is None
                or (type(row["charged_nano"]) is int and row["charged_nano"] >= 0),
                "Spend ledger contains an invalid charge.")
        require(row["state"] in {"reserved", "unknown", "settled"},
                "Spend ledger contains an unsupported state.")
    data = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False) + "\n").encode()
                    for row in rows)
    totals = {
        "attempts": len(rows),
        "charged_nano": sum(row["charged_nano"] or 0 for row in rows),
        "reserved_nano": sum(row["reserved_nano"] for row in rows if row["state"] == "reserved"),
        "unknown_hold_nano": sum(row["reserved_nano"] for row in rows if row["state"] == "unknown"),
        "state_counts": dict(sorted(Counter(row["state"] for row in rows).items())),
    }
    totals["committed_nano"] = totals["charged_nano"] + totals["reserved_nano"] + totals["unknown_hold_nano"]
    summary = {
        "version": "readonly-spend-snapshot-v1",
        "source": "Read-only transaction over the original SQLite spend table; no database writes",
        "columns": list(SPEND_COLUMNS),
        "currency": "USD",
        "units_per_usd": 1_000_000_000,
        "latest_recorded_event": max((row[key] for row in rows for key in ("created_at", "settled_at")
                                      if row[key]), default=None),
        "totals": totals,
        "export_sha256": sha_bytes(data),
        "limitations": [
            "Unknown charge holds and unsettled reservations are preserved, not cleared or counted as zero.",
            "This global ledger includes historical probes/experiments and must not be added to pilot-only cost totals.",
            "Token-rate costs and reserved liability are not proof of provider invoices or new cash payments.",
        ],
    }
    return data, summary


def validate_captured_inputs(payloads):
    for name in (".env.example", "web/.env.example"):
        for line in payloads[name].decode("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*(.*?)\s*(?:#.*)?", line)
            require(match is not None and match.group(1).strip() in {"", '""', "''"},
                    f"Environment template must contain blank assignments only: {name}")
    course = json.loads(payloads["data/source/manifest.json"])
    for name in ("cost_100.csv", "checkpoint_500.csv"):
        require(sha_bytes(payloads["data/source/" + name]) == course["files"][name]["sha256"],
                f"Fixed input differs from course manifest: {name}")
    csv_rows = lambda data: list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline="")))
    learning = csv_rows(payloads["data/learning_1000.csv"])
    require(len(learning) == 1000, "Learning input must contain exactly 1,000 rows.")
    expected = {row["review_id"]: row for row in learning}
    require(len(expected) == 1000, "Learning input has duplicate IDs.")
    records = [json.loads(line) for line in payloads["runs/pilot/1000/records.jsonl"].splitlines() if line.strip()]
    require(len(records) == 1000 and {r.get("review_id") for r in records} == set(expected),
            "Final learning records do not match the 1,000 input IDs.")
    for record in records:
        original = expected[record["review_id"]]
        canonical = json.dumps([original[key] for key in SOURCE_FIELDS], ensure_ascii=False,
                               separators=(",", ":"), allow_nan=False).encode()
        require(record.get("status") == "completed"
                and all(record.get(key) == original[key] for key in SOURCE_FIELDS)
                and record.get("source_sha256") == sha_bytes(canonical),
                "Final learning records contain an incomplete or changed source row.")
    golden = csv_rows(payloads["evals/golden_50_to_label.csv"])
    require(len(golden) == 50 and len({row["review_id"] for row in golden}) == 50,
            "Golden template must contain 50 distinct original IDs.")
    require(not ({row["review_id"] for row in golden} & set(expected)),
            "Golden IDs overlap the development learning sample.")
    answer_fields = ("topic", "intent", "sentiment", "severity", "entities", "evidence_quote", "needs_review")
    complete_labels = sum(all(str(row.get(field, "")).strip() for field in answer_fields) for row in golden)
    touched_labels = sum(any(str(row.get(field, "")).strip() for field in answer_fields) for row in golden)
    return {"learning_input_count": 1000, "completed": 1000, "golden_count": 50,
            "golden_template_complete_rows": complete_labels, "golden_template_touched_rows": touched_labels}


def release_readme(state, labels, ledger, include_history, safety_report, checker_reports, snapshot_mode):
    lines = [
        "# First-1,000 review learning release", "",
        "**This package contains 1,000 completed development reviews. The 210,000-review cohort is a future target, not a completed run.**",
        "",
        "The 100 cold/warm, 500, and 1,000 checkpoints overlap. Do not sum their record counts as unique coverage.",
        "",
        "| Checkpoint | Completed inputs | Nominal API USD | Measured wall seconds |",
        "|---|---:|---:|---:|",
    ]
    for name, summary in state["stages"].items():
        lines.append(f"| {name} | {summary['completed']} | {summary['api_cost_usd']} | {summary['wall_seconds']} |")
    if labels["golden_template_touched_rows"] == 0:
        lines += ["", "**The 50 human-label rows are blank. No human golden-set accuracy is established by this release.**",
                  "Open `evals/golden-labels.html` to supply independent judgments; the worksheet contains no model predictions."]
    else:
        lines += ["", f"The golden template contains {labels['golden_template_complete_rows']} structurally filled rows "
                  f"and {labels['golden_template_touched_rows']} touched rows. Completion does not establish human authorship.",
                  "Consult saved evaluation provenance before interpreting any agreement as human-label accuracy."]
    lines += ["", "The genuine live synthetic smoke test reports "
              f"`model_behavior_passed={str(safety_report.get('model_behavior_passed')).lower()}` and "
              f"`operational_passed={str(safety_report.get('operational_passed')).lower()}`. "
              "See `evals/synthetic-live/v5-live-001/safety_report.json` and `SUMMARY.md` for case-level injection outcomes and planted-error detection results. "
              "These synthetic cases are excluded from business aggregates and do not establish population accuracy or broad robustness."]
    lines += ["", "Both unmodified course-checker reports are preserved with their actual statuses:"]
    for name, report in checker_reports.items():
        codes = ", ".join(f"{code} × {count}" for code, count in sorted(report.get("issue_counts", {}).items())) or "none"
        lines.append(f"- `{name}`: `{report.get('status', 'unavailable')}`; warnings: {codes}.")
    lines.append("Full selected-ID coverage does not erase execution-evidence warnings. "
                 "The 1,000 run has no interruption-before snapshot; the separate recovery run retains cancelled-call unknown usage and resumed fallback overlap. "
                 "No checkpoint or usage evidence was invented to silence these warnings.")
    totals = ledger["totals"]
    lines += [
        "", "## Evidence map", "",
        "- `runs/pilot/`: original saved records, attempted calls, configurations, verification, role handoffs, ranking and memos.",
        "- `cost/measured-100/`: immutable cold/warm calculator package and standard-library offline replay.",
        "- `config/`, `prompts/`, `validation/`, `docs/`, `evals/`: frozen settings, tests, inspected failures and scope limitations.",
        "- `data/learning_1000.csv` and `data/source/`: the learning input, unchanged fixed 100/500 inputs, and official source manifest.",
        "- `data/ingestion.json` and the expanded ingestion/selection manifests: profiling of the entire original 660,622-row source.",
        "- `src/spotify_pipeline/`, `tests/`, `tools/`: implementation and offline reproduction helpers.",
        "- `web/`: dashboard/backend source, dependency lockfile, database schema, and blank environment template.",
        "- `runs/recovery-nebius-v5/` and its adjacent `.cast`: actual interruption/resume evidence; `runs/concurrency-100-w4/` and its recording: matched-input concurrency measurement.",
        "- `grading/`: standardized grading export for the declared first-1,000 scope. That run was not interrupted; an absent before-interruption checkpoint is not fabricated.",
        "- `runs/recovery-nebius-v5/grading/`: separate 500-review recovery export, with its own declared scope.",
        "- `release/ledger/`: sanitized read-only spending snapshot, including unknown charges and reservations.",
    ]
    if include_history:
        lines.append("- Earlier screening, probes, and failed experiments are retained under their original `runs/` names; they are not additional completed pilot coverage.")
    lines += [
        "", "## Spending and uncertainty", "",
        f"Global ledger: {totals['attempts']} attempts, ${totals['charged_nano'] / 1e9:.9f} recorded charges, "
        f"${totals['unknown_hold_nano'] / 1e9:.9f} unknown-charge holds, and "
        f"${totals['reserved_nano'] / 1e9:.9f} unsettled reservations.",
        "The ledger includes historical work. It must not be added to checkpoint totals. Unknown holds were preserved; "
        "this package did not clear, reconcile, or otherwise mutate the ledger. Nominal usage cost is distinct from cash outlay.",
        "",
        "## Offline replay and integrity", "",
        "From the extracted package root:", "",
        "```sh",
        "python tools/package_pilot.py replay --package cost/measured-100 --out cost/replay",
        "python tools/package_learning.py verify --archive /path/to/spotify-learning-1000.tar.gz",
        "```",
        "",
        "`release/inventory.json` lists each payload's byte length and SHA-256. `release/SHA256SUMS` also covers the inventory. "
        "Tar metadata and gzip timestamps are deterministic. The archive itself has a separate external manifest with its checksum.",
        f"Source snapshot mode: `{snapshot_mode}`. APFS-clone mode, when selected, reads byte-identical temporary clones "
        "using macOS clonefile (or cp -c if the native symbol is unavailable) with up to 16 workers "
        "to avoid macOS source-path read stalls; the original files remain untouched, "
        "source identity guards still apply, and clones are deleted.",
        "Metadata-only transitions are accepted only after independent captures have identical bytes and a stable final size/stat. "
        "Content changes fail the build. Transition counts are recorded in the inventory and external manifest.",
        "",
        "The archive deliberately excludes credentials, populated environment files, SQLite databases/caches, dependency directories, "
        "the raw 660,622-row CSV, and the unclassified selected 210,000-review input. Source-file checksums preserve dataset identity.",
        "Credential values available from the local environment and `.env` were scanned in every packaged payload before archiving. "
        "This is a byte-level credential check, not a claim that arbitrary binary pixels or unknown secrets were inspected.",
        "",
        "Model-to-model agreement and agent-assisted qualitative inspection are not human ground truth. "
        "Use the saved failure analysis and expansion decision before authorizing a larger run.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def make_tar(path, payloads):
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, data in sorted(payloads.items()):
                    info = tarfile.TarInfo(ARCHIVE_ROOT + "/" + name)
                    info.size, info.mtime, info.uid, info.gid = len(data), 0, 0, 0
                    info.uname = info.gname = ""
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(data))


def build(args):
    require(args.ready, "Build requires --ready after the completed pilot and recovery evidence are finalized.")
    root = Path(args.root).resolve()
    state = readiness(root)
    require(state["ready"], "Learning release is not ready. Missing/incomplete paths: "
            + ", ".join(state["missing_files"] + state["failures"]))
    names, ignored = collect_files(root, include_history=not args.no_history)
    payloads, observations = snapshot_files(root, names, snapshot_mode=args.snapshot_mode)
    labels = validate_captured_inputs(payloads)
    ledger = Path(args.ledger)
    if not ledger.is_absolute():
        ledger = root / ledger
    spend, ledger_summary = spend_snapshot(ledger)
    payloads["release/ledger/spend.jsonl"] = spend
    payloads["release/ledger/summary.json"] = json_bytes(ledger_summary)
    safety_report = json.loads(payloads["evals/synthetic-live/v5-live-001/safety_report.json"])
    checker_reports = {name: json.loads(payloads[name]) for name in
                       ("validation/checker_pilot.json", "validation/checker_recovery500.json")}
    payloads["release/README.md"] = release_readme(
        state, labels, ledger_summary, not args.no_history, safety_report, checker_reports, args.snapshot_mode)
    verify_source_unchanged(root, observations)
    inventory = {
        "version": VERSION,
        "scope": labels,
        "target_nonempty_reviews": 210000,
        "history_included": not args.no_history,
        "snapshot_mode": args.snapshot_mode,
        "snapshot_integrity_before_archive": snapshot_summary(observations),
        "source_allowlist": {"files": list(EXACT_FILES), "trees": list(TREE_ALLOWLIST),
                             "history": [] if args.no_history else list(HISTORY_ALLOWLIST)},
        "excluded_candidates": ignored,
        "files": {name: {"bytes": len(data), "sha256": sha_bytes(data)}
                  for name, data in sorted(payloads.items())},
        "inventory_rule": "All payloads except inventory.json and SHA256SUMS; SHA256SUMS additionally hashes inventory.json.",
    }
    payloads["release/inventory.json"] = json_bytes(inventory)
    payloads["release/SHA256SUMS"] = "".join(
        f"{sha_bytes(data)}  {name}\n" for name, data in sorted(payloads.items())
    ).encode()
    secrets = credential_values(root)
    scan_payloads(payloads, secrets)
    verify_source_unchanged(root, observations)
    output = Path(args.out)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    require(output.is_relative_to(root / "release") and output.name.endswith(".tar.gz"),
            "Release archive must be a .tar.gz under this repository's release/ directory.")
    manifest_path = output.with_name(output.name + ".manifest.json")
    require(not output.exists() and not manifest_path.exists(), "Release destination exists; choose a new archive name.")
    output.parent.mkdir(parents=True, exist_ok=True)
    ignore_path = root / "release/.gitignore"
    if not ignore_path.exists():
        ignore_path.write_text("*.tar.gz\n*.zip\n*.tmp\n", encoding="utf-8")
    temporary = output.with_name(output.name + ".tmp")
    require(not temporary.exists(), "Release temporary destination already exists.")
    try:
        make_tar(temporary, payloads)
        verify_source_unchanged(root, observations)
        verified = verify_archive(temporary)
        archive_data = temporary.read_bytes()
        external = {
            "version": VERSION, "archive": output.name, "bytes": len(archive_data),
            "sha256": sha_bytes(archive_data), "payload_file_count": len(payloads),
            "inventory_sha256": sha_bytes(payloads["release/inventory.json"]),
            "credential_scan": {"status": "passed", "credential_values_loaded": bool(secrets),
                                 "scope": "process environment and .env credential assignments"},
            "verification": verified,
            "snapshot_mode": args.snapshot_mode,
            "snapshot_integrity": snapshot_summary(observations),
            "scope": labels,
        }
        scan_payloads({manifest_path.name: json_bytes(external)}, secrets)
        temporary.rename(output)
        manifest_path.write_bytes(json_bytes(external))
        # These reviewer-friendly companions are exact copies of archived files.
        (root / "release/README.md").write_bytes(payloads["release/README.md"])
        (root / "release/inventory.json").write_bytes(payloads["release/inventory.json"])
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {"status": "packaged", "archive": str(output), "manifest": str(manifest_path),
            "sha256": external["sha256"], "bytes": external["bytes"],
            "payload_files": len(payloads), "paid_calls": 0, "ledger_mutated": False}


def verify_archive(path):
    """Inspect in memory; never extract untrusted archive paths to disk."""
    payloads = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                require(member.isfile(), "Archive contains a non-file member.")
                parts = PurePosixPath(member.name).parts
                require(parts and parts[0] == ARCHIVE_ROOT and ".." not in parts
                        and not PurePosixPath(member.name).is_absolute(),
                        "Archive contains an unsafe member path.")
                relative = PurePosixPath(*parts[1:]).as_posix()
                require(relative not in payloads, "Archive repeats a member path.")
                require(source_allowed(relative) or relative == "release/SHA256SUMS",
                        f"Archive contains a forbidden member: {relative}")
                handle = archive.extractfile(member)
                require(handle is not None, "Archive member cannot be read.")
                payloads[relative] = handle.read()
    except (tarfile.TarError, OSError):
        raise PackageError("Cannot read a valid release archive.") from None
    require("release/inventory.json" in payloads and "release/SHA256SUMS" in payloads,
            "Archive lacks its inventory or checksum index.")
    try:
        inventory = json.loads(payloads["release/inventory.json"])
        files = inventory["files"]
        require(set(files) == set(payloads) - {"release/inventory.json", "release/SHA256SUMS"},
                "Archive file list differs from its inventory.")
        for name, item in files.items():
            require(item["bytes"] == len(payloads[name]) and item["sha256"] == sha_bytes(payloads[name]),
                    f"Archive checksum mismatch: {name}")
        expected = "".join(f"{sha_bytes(data)}  {name}\n" for name, data in sorted(payloads.items())
                           if name != "release/SHA256SUMS").encode()
        require(payloads["release/SHA256SUMS"] == expected, "Archive checksum index differs.")
    except (KeyError, TypeError, ValueError):
        raise PackageError("Archive inventory is malformed or inconsistent.") from None
    return {"status": "verified", "payload_files": len(payloads),
            "inventory_sha256": sha_bytes(payloads["release/inventory.json"])}


def self_test():
    """Synthetic-only stdlib checks; no repository artifacts or ledger changes."""
    import unittest

    class PackageTests(unittest.TestCase):
        def test_allowlist_exclusions(self):
            for name in ("data/source/spotify_reviews_18months.csv", ".env",
                         "config/.env.example", "runs/pilot/state.sqlite3",
                         "runs/pilot/credentials.json", "node_modules/x.json",
                         "../outside.json", "data/selected_210000.csv", "work/proof.json"):
                self.assertFalse(source_allowed(name), name)
            self.assertTrue(source_allowed("runs/pilot/1000/records.jsonl"))

        def test_secret_scan_never_displays_value(self):
            with self.assertRaises(PackageError) as error:
                scan_payloads({"handoffs/response.json": b'{"secret":"synthetic-private-token"}'},
                              [b"synthetic-private-token"])
            self.assertIn("handoffs/response.json", str(error.exception))
            self.assertNotIn("synthetic-private-token", str(error.exception))

        def test_dotenv_and_url_password(self):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / ".env").write_text('export TEST_API_KEY="synthetic-key"\n'
                                          'TEST_PASSWORD = "synthetic password"\n'
                                          'SECOND_API_KEY= synthetic-second\n'
                                          'THIRD_API_KEY =synthetic-third\n'
                                          'DATABASE_URL="postgres://u:synthetic%20db@host/db"\n'
                                          'DATABASE_READONLY_URL="postgres://r:synthetic-readonly@host/db"\n'
                                          'ORDINARY_FIELD=not-a-secret\n')
                values = credential_values(root)
                for value in (b"synthetic-key", b"synthetic password", b"synthetic db",
                              b"synthetic-second", b"synthetic-third", b"synthetic-readonly"):
                    self.assertIn(value, values)
                self.assertNotIn(b"not-a-secret", values)

        def test_symlink_and_changed_source_are_rejected(self):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "docs").mkdir()
                original = root / "docs/synthetic.json"
                original.write_text('{"synthetic":true}\n')
                payloads, observations = snapshot_files(root, ["docs/synthetic.json"])
                self.assertEqual(len(payloads), 1)
                original.write_text('{"synthetic":false}\n')
                with self.assertRaises(PackageError):
                    verify_source_unchanged(root, observations)
                (root / "docs/link.json").symlink_to(original)
                with self.assertRaises(PackageError):
                    collect_files(root, include_history=False)

        @unittest.skipUnless(sys.platform == "darwin", "APFS clone mode is macOS-specific")
        def test_clone_snapshot_retains_source_bytes_and_metadata(self):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "synthetic.json"
                source.write_bytes(b'{"synthetic":"clone snapshot"}\n')
                before = source.stat()
                payloads, observations = snapshot_files(root, ["synthetic.json"], "apfs-clone")
                self.assertEqual(payloads["synthetic.json"], source.read_bytes())
                self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ino),
                                 observations["synthetic.json"]["stamp"])
                verify_source_unchanged(root, observations)

        @unittest.skipUnless(sys.platform == "darwin", "APFS clone mode is macOS-specific")
        def test_metadata_transition_accepts_identical_bytes_and_rejects_content_change(self):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "synthetic.json"
                source.write_bytes(b'{"synthetic":true}\n')
                payloads, observations = snapshot_files(root, ["synthetic.json"], "apfs-clone")
                stamp = source.stat()
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000))
                verify_source_unchanged(root, observations)
                self.assertEqual(snapshot_summary(observations)["metadata_transition_count"], 1)
                self.assertEqual(payloads["synthetic.json"], source.read_bytes())
                source.write_bytes(b'{"synthetic":null}\n')
                with self.assertRaises(PackageError):
                    verify_source_unchanged(root, observations)

        def test_ledger_is_read_only_and_keeps_unknown_hold(self):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "spend.sqlite3"
                connection = sqlite3.connect(path)
                connection.execute("CREATE TABLE spend(request_id TEXT,run_id TEXT,reserved_nano INTEGER,"
                                   "charged_nano INTEGER,state TEXT,created_at TEXT,settled_at TEXT)")
                connection.executemany("INSERT INTO spend VALUES(?,?,?,?,?,?,?)", [
                    ("synthetic-a", "synthetic-run", 300, None, "unknown", "t1", "t2"),
                    ("synthetic-b", "synthetic-run", 500, 200, "settled", "t1", "t2"),
                    ("synthetic-c", "synthetic-run", 400, None, "reserved", "t3", None),
                ])
                connection.commit()
                connection.close()
                before = path.read_bytes()
                data, summary = spend_snapshot(path)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(summary["totals"]["committed_nano"], 900)
                self.assertEqual(summary["totals"]["unknown_hold_nano"], 300)
                self.assertEqual(len(data.splitlines()), 3)
                self.assertEqual(set(json.loads(data.splitlines()[0])), set(SPEND_COLUMNS))

        def test_deterministic_archive_and_tamper_rejection(self):
            with tempfile.TemporaryDirectory() as temp:
                files = {"docs/synthetic.md": b"synthetic fixture\n"}
                inventory = {"files": {name: {"bytes": len(data), "sha256": sha_bytes(data)}
                                       for name, data in files.items()}}
                files["release/inventory.json"] = json_bytes(inventory)
                files["release/SHA256SUMS"] = "".join(f"{sha_bytes(data)}  {name}\n"
                                                      for name, data in sorted(files.items())).encode()
                first, second = Path(temp) / "a.tar.gz", Path(temp) / "b.tar.gz"
                make_tar(first, files)
                make_tar(second, files)
                self.assertEqual(first.read_bytes(), second.read_bytes())
                self.assertEqual(verify_archive(first)["status"], "verified")
                files["docs/synthetic.md"] = b"tampered fixture\n"
                third = Path(temp) / "c.tar.gz"
                make_tar(third, files)
                with self.assertRaises(PackageError):
                    verify_archive(third)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PackageTests))
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    for name in ("plan", "build"):
        item = sub.add_parser(name)
        item.add_argument("--root", default=str(ROOT))
        item.add_argument("--no-history", action="store_true")
        if name == "build":
            item.add_argument("--ready", action="store_true")
            item.add_argument("--ledger", default="data/spend.sqlite3")
            item.add_argument("--out", default="release/spotify-learning-1000.tar.gz")
            item.add_argument("--snapshot-mode", choices=("direct", "apfs-clone"), default="direct")
    verify = sub.add_parser("verify")
    verify.add_argument("--archive", required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            return self_test()
        if args.command == "build":
            result = build(args)
        elif args.command == "verify":
            result = verify_archive(Path(args.archive))
        else:
            root = Path(getattr(args, "root", ROOT)).resolve()
            names, ignored = collect_files(root, include_history=not getattr(args, "no_history", False))
            result = {"mode": "read-only-plan", "readiness": readiness(root),
                      "candidate_files": len(names), "candidate_bytes": sum((root / name).stat().st_size for name in names),
                      "excluded_candidates": ignored, "paid_calls": 0}
        print(json.dumps(result, indent=2))
        return 0
    except (PackageError, OSError):
        # OSError may include local filenames but never print source file data.
        error = sys.exception()
        print(str(error) if isinstance(error, PackageError) else "Release filesystem operation failed.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
