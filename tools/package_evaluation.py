"""Offline public v6 evaluation overlay; never reads private answers/predictions.

Use ``plan`` or ``scan`` before the final freeze. ``build --ready`` is an explicit
operator attestation that public files are final. This does not run models, query
databases, inspect private directories, publish artifacts, or replace v0.1.0.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile
from unittest.mock import patch

from package_learning import (
    PackageError, credential_values, json_bytes, require, scan_payloads, sha_bytes,
    snapshot_files, snapshot_summary, verify_source_unchanged,
)

ROOT = Path(__file__).resolve().parents[1]
VERSION = "spotify-public-evaluation-overlay-v6"
ARCHIVE_ROOT = "spotify-evaluation-v6"
META = "release/evaluation-v6"
BASE_RELEASE = {
    "repository": "https://github.com/shahdevansh/spotify-review-pipeline",
    "release": "https://github.com/shahdevansh/spotify-review-pipeline/releases/tag/v0.1.0-pilot",
    "archive": "spotify-learning-1000.tar.gz",
    "download": "https://github.com/shahdevansh/spotify-review-pipeline/releases/download/v0.1.0-pilot/spotify-learning-1000.tar.gz",
    "bytes": 4489358,
    "sha256": "8675a22ee7008b0036f5e8226223a8ab65b16dfc14f6a745ff7248ccc3b988b8",
}
HUMAN_BASE = "evals/human-evaluation-v1"
HUMAN_FILES = (
    "combined_200.html", "combined_200_to_label.csv", "combined_200_membership.csv",
    "combined_200_strata.csv", "holdout_150.html", "holdout_150_to_label.csv",
    "holdout_150_membership.csv", "second_annotator_50_option.html",
    "second_annotator_50_option_to_label.csv", "second_annotator_50_option_membership.csv",
    "second_annotator_200_option.html", "second_annotator_200_option_to_label.csv",
    "second_annotator_200_option_membership.csv", "protected_text_hashes.txt",
    "README.md", "kit_integrity.json", "groups.json", "rubric.v1.json",
    "selection_manifest.json", "confidence_examples.json", "sources.jsonl",
    "sources_manifest.json", "prediction_plan.json",
)
VALIDATION_FILES = (
    "dashboard_evaluation_database.json", "dashboard_evaluation_preflight.json",
    "dashboard_evaluation_publication.json", "dashboard_evaluation_preview.json",
    "dashboard_evaluation_production.json", "dashboard_evaluation_rendered_qa.json",
    "dashboard_evaluation_checks.json", "dashboard_evaluation_audit_v6.json",
    "pilot_publication_after_evaluation.json", "worksheet_harness_integration.json",
    "holdout_source_overlap.json", "sealed_human_predictions_v1.json",
    "public_release_verification.json", "evaluation_v6_full_tests.json",
)
EXACT_FILES = (
    "README.md", "pyproject.toml", "uv.lock", "LICENSE", ".gitignore", ".env.example",
    "web/.env.example", "web/.gitignore", "web/README.md", "web/package.json",
    "web/package-lock.json", "web/next.config.ts", "web/tsconfig.json",
) + tuple(f"{HUMAN_BASE}/{name}" for name in HUMAN_FILES) + tuple(
    f"validation/{name}" for name in VALIDATION_FILES
)
TREE_ALLOWLIST = (
    "src/spotify_pipeline", "tools", "tests", "schemas", "config", "prompts", "docs",
    "web/src", "web/tests", "web/scripts", "web/database", "web/public",
    "evals/experiment-v6", "evals/dashboard", "evals/audit-v6",
)
DENIED_PARTS = {
    "private", "secrets", "credentials", ".git", ".venv", "venv", "runtime",
    "node_modules", "__pycache__", ".pytest_cache", ".next", ".vercel",
    "work", "site-packages", "human-labels", "human-predictions-v1",
}
DENIED_NAMES = {
    "spotify_reviews_18months.csv", "source_ledger.csv",
    "selected_210000.csv", "human_labels.json", "human_labels.csv",
}
SAFE_SUFFIXES = {
    ".py", ".sh", ".json", ".jsonl", ".csv", ".md", ".txt", ".log", ".toml",
    ".lock", ".html", ".xml", ".yaml", ".yml", ".sql", ".ts", ".tsx", ".css",
    ".png", ".svg", ".ico", ".cast",
}
REQUIRED_FILES = (
    "README.md", "pyproject.toml", "uv.lock", ".env.example", "web/.env.example",
    "tools/package_evaluation.py", "tools/package_learning.py",
    "src/spotify_pipeline/harness.py", "src/spotify_pipeline/evaluation_publication.py",
    "tools/freeze_human_predictions.py", "tests/test_worksheet_harness_integration.py",
    "prompts/labels-v6.md", "schemas/dashboard-evaluation.schema.json",
    "web/database/dashboard-evaluation.schema.json", "web/database/evaluation_schema.sql",
    "docs/audit-and-next-run-v6.md", "docs/evaluation-audit-v6.md",
    "docs/dashboard-evaluation-audit-v6.md", "docs/model-comparison-v6.md",
    "docs/model-stability-v6.md", "docs/model-options-v6.md",
    "docs/evaluation-harness.md", "docs/human-evaluation-protocol.md",
    "docs/scaling-performance-audit-v6.md", "docs/v6-rubric-change-notes.md",
    "docs/evidence/scaling-v6/benchmark.py", "docs/evidence/scaling-v6/results.json",
    "docs/evidence/scaling-v6/size_profile.json",
    "evals/experiment-v6/cost-projections.json",
    "evals/experiment-v6/matched-200/manifest.json",
    "evals/experiment-v6/matched-200/sources.jsonl",
    "evals/experiment-v6/matched-200/stress_sources.jsonl",
    "evals/experiment-v6/matched-200/synthetic_cases.json",
    "evals/experiment-v6/matched-200/comparison.json",
    "evals/experiment-v6/matched-200/stability_report_v2.json",
    "evals/experiment-v6/matched-200/frozen_implementation/README.md",
    "evals/experiment-v6/matched-200/comparison-history/rebuild-validation.json",
    "evals/dashboard/pilot-v5-audit-v1.json",
    "evals/audit-v6/audit_summary.json", "evals/audit-v6/case_audit.csv",
    "evals/audit-v6/case_audit.json", "evals/audit-v6/golden_text_overlap.json",
    "evals/audit-v6/ranking_sensitivity.json", "evals/audit-v6/selected_records.json",
    "evals/audit-v6/selection.json", "evals/audit-v6/statistical_illustrations.json",
) + tuple(f"{HUMAN_BASE}/{name}" for name in HUMAN_FILES) + tuple(
    f"validation/{name}" for name in VALIDATION_FILES
)
PINNED_PUBLIC = {
    f"{HUMAN_BASE}/combined_200.html": "764c6ec8a54efac58c7596e1f1efb8438109957ccddd28ed2ee93664aae189bd",
    f"{HUMAN_BASE}/sources.jsonl": "37d343c6380f3c42bfadf14e684a0aa0d1352cadcba7d424dedfdd1fb4744c0f",
    f"{HUMAN_BASE}/groups.json": "602fc42873490cb98e6e0391c72ef45496a163f9f26972c861b1c8f651642b03",
    f"{HUMAN_BASE}/combined_200_to_label.csv": "fc04b850482ba15b47b2e9753a69df2a58190cf347217c9278295296da3e2b61",
    f"{HUMAN_BASE}/holdout_150_to_label.csv": "49e490fc33d93d32893cacb7eafcb7b47aaa671dea55ebbec82b9fb636366d6c",
    f"{HUMAN_BASE}/second_annotator_200_option_to_label.csv": "82fa12ba07904970c562db4ae3c545915bd38cf0c8fcba72f0426fa6b9f9006a",
    f"{HUMAN_BASE}/second_annotator_50_option_to_label.csv": "313c01ae3ea1c45c5f140aa1c2d277ecfcea9f3850766ef452ce9f766462ceff",
}
SOURCE_FIELDS = (
    "review_id", "review_text", "review_rating", "review_likes",
    "app_version", "review_timestamp",
)
WORKSHEET_FIELDS = (
    "review_id", "review_text", "row_sha", "topic", "intent", "sentiment",
    "severity", "entities", "evidence_quote", "needs_review", "ambiguous",
    "notes", "human_labeler", "alternative_topics", "alternative_intents",
    "alternative_severities", "evidence_support", "alternative_notes",
)
WORKSHEET_COUNTS = {
    "combined_200_to_label.csv": 200, "holdout_150_to_label.csv": 150,
    "second_annotator_50_option_to_label.csv": 10,
    "second_annotator_200_option_to_label.csv": 40,
}
EXCLUSIONS = [
    "private/ and all human answers and sealed human predictions",
    "Credentials and .env files; only the two blank .env.example templates are admitted",
    "Databases, SQLite caches, node_modules, .next, .vercel, .git, Python caches",
    "Full raw 660,622-row source, ingestion ledger, and 210,000-row proposed input",
    "Original v5 run evidence, grading, recovery and measured-cost artifacts: obtain v0.1.0",
    "Arbitrary files in evals/ or the human-kit directory: only exact named human-kit files",
]


def source_allowed(relative):
    path = PurePosixPath(relative)
    parts = path.parts
    if not parts or path.is_absolute() or ".." in parts or "\\" in relative:
        return False
    if relative in {".env.example", "web/.env.example", ".gitignore", "web/.gitignore"}:
        return True
    if any(part.lower() in DENIED_PARTS or part.startswith(".") for part in parts):
        return False
    name = parts[-1].lower()
    if name in DENIED_NAMES or name.startswith(".env"):
        return False
    if any(marker in name for marker in (".sqlite", ".db", "credential", "private-key")):
        return False
    return path.suffix in SAFE_SUFFIXES or name == "license"


def is_allowlisted(relative):
    return source_allowed(relative) and (
        relative in EXACT_FILES
        or any(relative.startswith(tree + "/") for tree in TREE_ALLOWLIST)
    )


def require_safe_source(root, relative):
    """Reject links at every path level, including exact-file parent paths."""
    path = root
    for part in PurePosixPath(relative).parts:
        path = path / part
        require(not path.is_symlink(), f"Symlink is forbidden: {relative}")
    require(path.resolve().is_relative_to(root), f"Unsafe source path: {relative}")


def collect_files(root):
    """Prune protected directories before traversal; inspect only named public roots."""
    root = root.resolve()
    selected, excluded = set(), []
    for relative in EXACT_FILES:
        path = root / relative
        require_safe_source(root, relative)
        if path.is_file():
            selected.add(relative)
    for tree in TREE_ALLOWLIST:
        base = root / tree
        require_safe_source(root, tree)
        if not base.exists():
            continue
        for current, directories, filenames in os.walk(base, followlinks=False):
            kept = []
            for name in directories:
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if name.lower() in DENIED_PARTS or name.startswith("."):
                    excluded.append(relative + "/")
                    continue
                require(not path.is_symlink(), f"Symlink is forbidden: {relative}")
                kept.append(name)
            directories[:] = kept
            for name in filenames:
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if not is_allowlisted(relative):
                    excluded.append(relative)
                    continue
                require(not path.is_symlink(), f"Symlink is forbidden: {relative}")
                require(path.is_file(), f"Non-regular file is forbidden: {relative}")
                selected.add(relative)
    for relative in selected:
        path = root / relative
        require(is_allowlisted(relative), f"Forbidden release source: {relative}")
        require_safe_source(root, relative)
    return sorted(selected), sorted(excluded)


def plan(root):
    names, excluded = collect_files(root)
    missing = sorted(set(REQUIRED_FILES) - set(names))
    return {
        "version": VERSION, "ready": not missing, "missing_files": missing,
        "public_source_file_count": len(names),
        "source_bytes": sum((root / name).stat().st_size for name in names),
        "human_kit_exact_file_count": len(HUMAN_FILES),
        "public_human_receipt": "validation/sealed_human_predictions_v1.json",
        "explicit_exclusions": EXCLUSIONS, "skipped_within_public_roots": excluded,
        "dependency": BASE_RELEASE,
        "private_directories_traversed": False,
        "human_answers_or_private_predictions_read": False,
    }


def parse_json(payloads, name):
    try:
        return json.loads(payloads[name])
    except (KeyError, ValueError, UnicodeDecodeError):
        raise PackageError(f"Missing or invalid public JSON: {name}") from None


def source_hash(row):
    return sha_bytes(json.dumps([row[key] for key in SOURCE_FIELDS], ensure_ascii=False,
                                sort_keys=True, separators=(",", ":")).encode("utf-8"))


def validate_blank_csv(data, name, source_by_id, membership_ids, expected_count):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    require(tuple(reader.fieldnames or ()) == WORKSHEET_FIELDS,
            f"Blank worksheet header differs or repeats: {name}")
    rows = list(reader)
    require(len(rows) == expected_count, f"Blank worksheet count differs: {name}")
    require([row["review_id"] for row in rows] == membership_ids
            and len(set(membership_ids)) == expected_count,
            f"Blank worksheet IDs or order differ: {name}")
    for row in rows:
        require(None not in row and all(value is not None for value in row.values()),
                f"Blank worksheet row width differs: {name}")
        require(all(row[key] == "" for key in WORKSHEET_FIELDS[3:]),
                f"Expected blank worksheet has answers: {name}")
        original = source_by_id.get(row["review_id"])
        require(original is not None and row["review_text"] == original["review_text"]
                and row["row_sha"] == source_hash(original),
                f"Blank worksheet source identity differs: {name}")


def validate_captured_inputs(payloads):
    for name, digest in PINNED_PUBLIC.items():
        require(name in payloads and sha_bytes(payloads[name]) == digest,
                f"Frozen public input hash mismatch: {name}")
    kit = parse_json(payloads, f"{HUMAN_BASE}/kit_integrity.json")
    require(set(kit["files"]) == set(HUMAN_FILES) - {"kit_integrity.json", "prediction_plan.json"},
            "Frozen public kit integrity inventory differs.")
    for name, identity in kit["files"].items():
        data = payloads[f"{HUMAN_BASE}/{name}"]
        require(identity["bytes"] == len(data) and identity["sha256"] == sha_bytes(data),
                f"Frozen public kit integrity mismatch: {name}")
    for name in (".env.example", "web/.env.example"):
        for line in payloads[name].decode("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                require(not line.split("=", 1)[1].strip().strip("'\""),
                        f"Environment template contains a value: {name}")
    sources = [json.loads(line) for line in payloads[f"{HUMAN_BASE}/sources.jsonl"].splitlines()]
    groups = parse_json(payloads, f"{HUMAN_BASE}/groups.json")
    manifest = parse_json(payloads, f"{HUMAN_BASE}/sources_manifest.json")
    require(len(sources) == 200 and all(
        set(row) == set(SOURCE_FIELDS) and all(type(row[key]) is str for key in SOURCE_FIELDS)
        for row in sources), "Human source-only rows differ from the six-field contract.")
    ids = [row["review_id"] for row in sources]
    require(len(set(ids)) == 200, "Human source-only IDs are not unique.")
    require(set(groups) == {"mandatory_golden_50", "fresh_text_disjoint_150"}
            and len(groups["mandatory_golden_50"]) == 50
            and len(groups["fresh_text_disjoint_150"]) == 150
            and groups["mandatory_golden_50"] + groups["fresh_text_disjoint_150"] == ids,
            "Human evaluation group partition or ordering differs.")
    parsed_sha = sha_bytes(b"".join(bytes.fromhex(source_hash(row)) for row in sources))
    require(manifest["parsed_rows_sha256"] == parsed_sha, "Parsed source hash differs.")
    for key, relative in (("sources_jsonl", "sources.jsonl"), ("groups", "groups.json"),
                          ("membership", "combined_200_membership.csv"),
                          ("worksheet", "combined_200.html")):
        data = payloads[f"{HUMAN_BASE}/{relative}"]
        require(manifest[key]["sha256"] == sha_bytes(data)
                and manifest[key]["bytes"] == len(data), f"Source manifest mismatch: {relative}")
    # Parse only predeclared, hash-pinned BLANK CSVs. No answer-export searches.
    source_by_id = {row["review_id"]: row for row in sources}
    for name, expected_count in WORKSHEET_COUNTS.items():
        membership = name.replace("_to_label.csv", "_membership.csv")
        membership_rows = list(csv.DictReader(io.StringIO(
            payloads[f"{HUMAN_BASE}/{membership}"].decode("utf-8"))))
        validate_blank_csv(payloads[f"{HUMAN_BASE}/{name}"], name, source_by_id,
                           [row["review_id"] for row in membership_rows], expected_count)
    receipt = parse_json(payloads, "validation/sealed_human_predictions_v1.json")
    # Accept only the separately authored public aggregate/hash receipt schema.
    receipt_keys = {
        "version", "created_at", "provenance", "prediction_plan_sha256", "source_sha256",
        "human_answers_read", "model_prediction_labels_inspected", "arms",
        "all_inputs_completed", "human_accuracy_available", "ledger", "limits",
        "unique_text_count_source",
    }
    arm_keys = {
        "arm", "completed", "input_count", "requests", "failed_attempts", "api_cost_usd",
        "api_cost_complete", "artifacts_sha256", "unique_texts",
    }
    require(set(receipt) == receipt_keys
            and isinstance(receipt["arms"], list) and len(receipt["arms"]) == 2
            and all(isinstance(arm, dict) and set(arm) == arm_keys for arm in receipt["arms"])
            and {arm["arm"] for arm in receipt["arms"]} == {"glm-v6", "lightning-v5"}
            and set(receipt["ledger"]) == {
                "known_nominal_usd", "in_flight_reserved_usd", "unknown_charge_hold_usd", "committed_usd"
            }, "Public sealed receipt aggregate schema differs.")
    is_money = lambda value: type(value) in {int, float} and math.isfinite(value) and value >= 0
    is_sha = lambda value: isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value)
    require(all(is_money(value) for value in receipt["ledger"].values())
            and all(isinstance(receipt[key], str) and receipt[key]
                    for key in ("version", "created_at", "provenance", "unique_text_count_source"))
            and type(receipt["all_inputs_completed"]) is bool
            and isinstance(receipt["limits"], list)
            and all(isinstance(value, str) for value in receipt["limits"])
            and is_sha(receipt["source_sha256"]) and is_sha(receipt["prediction_plan_sha256"]),
            "Public sealed receipt contains a non-scalar or invalid aggregate value.")
    for arm in receipt["arms"]:
        require(all(type(arm[key]) is int and arm[key] >= 0 for key in
                    ("completed", "input_count", "requests", "failed_attempts", "unique_texts"))
                and is_money(arm["api_cost_usd"]) and type(arm["api_cost_complete"]) is bool
                and is_sha(arm["artifacts_sha256"]),
                "Public sealed receipt arm contains a non-scalar or invalid aggregate value.")
    require(receipt["human_answers_read"] is False
            and receipt["model_prediction_labels_inspected"] is False
            and receipt["human_accuracy_available"] is False,
            "Public sealed receipt is no longer the pre-evaluation receipt.")
    require(receipt["prediction_plan_sha256"] == sha_bytes(payloads[f"{HUMAN_BASE}/prediction_plan.json"])
            and receipt["source_sha256"] == sha_bytes(payloads[f"{HUMAN_BASE}/sources.jsonl"]),
            "Public sealed receipt source/plan identity differs.")
    return {
        "frozen_worksheet_source_and_group_hashes": "passed",
        "blank_worksheet_files": "passed",
        "human_source_rows": 200, "groups": {"mandatory_golden_50": 50, "fresh_text_disjoint_150": 150},
        "six_original_source_fields_and_order": "passed",
        "environment_templates_blank": True,
        "public_sealed_receipt_exact_aggregate_schema": "passed",
        "public_kit_integrity_files_verified": len(kit["files"]),
        "human_answers_or_private_predictions_read": False,
    }


def overlay_readme():
    return f"""# Public evaluation improvement — v6 overlay

This is an overlay for the Spotify review pipeline repository and the immutable
[v0.1.0 pilot release]({BASE_RELEASE['release']}). It does not replace that archive.

1. Obtain the repository source and `spotify-learning-1000.tar.gz` from v0.1.0.
2. Verify the old archive SHA-256 is `{BASE_RELEASE['sha256']}`.
3. Extract v0.1.0 and copy the contents of its `spotify-learning-1000/` directory
   into the repository root, preserving its pilot evidence.
4. Extract this archive and copy the contents of `spotify-evaluation-v6/` into the
   repository root. Current public code/docs overwrite earlier versions; original
   v5 records, grading, cost and recovery artifacts remain supplied by v0.1.0.
5. Verify this overlay with `python tools/package_evaluation.py verify --archive
   release/spotify-evaluation-v6.tar.gz`. Its internal inventory gives every
   public payload's size and SHA-256; it does not require credentials.

The completed business pipeline remains the 1,000-review pilot. The 210,000-review
target has not been executed. This overlay preserves development model trials,
synthetic/stress tests, stability/concurrency evidence, frozen trial implementation,
evaluation harness, public dashboard evaluation, and the blind human-evaluation kit.
Model agreement and synthetic tests are not human accuracy measurements.

Human evaluation contains the mandatory 50 and a separately sampled fresh 150
(200 total). These are distinct sampling designs; pooled metrics are descriptive,
not an unbiased full-corpus prevalence estimate. The published worksheets are blank.
The source-only prediction plan and a public aggregate/hash sealing receipt may
describe completed private inference; no sealed predictions or human answers are here.
Keep downloaded answers in an ignored private directory, and use the documented
explicit human-label attestation only after predictions/configuration are frozen.

Excluded: private/, real answers, sealed prediction values, .env/credentials,
databases/caches, node_modules/.next, the full raw source and selected 210k input.
No private directory is traversed by the packager. Known credential values from
process environment and the repository .env are used only for an in-memory scan;
scan failures reveal filenames, never credential values. No provider calls, database
queries, uploads or Git operations occur during packaging.

On macOS the snapshot uses native APFS clones to avoid observed FileProvider read
stalls. Originals are untouched. Path/symlink/size guards apply; metadata transitions
are accepted only when independent captures have identical bytes. The external
manifest records the actual snapshot method and transition count.
"""


def make_payloads(sources):
    payloads = dict(sources)
    payloads[f"{META}/README.md"] = overlay_readme().encode("utf-8")
    inventory = {
        "version": VERSION, "archive_root": ARCHIVE_ROOT, "dependency": BASE_RELEASE,
        "scope": "Public evaluation overlay; completed pilot 1000, target 210000 not run",
        "exclusions": EXCLUSIONS,
        "human_answers_or_private_predictions_read": False,
        "files": [{"path": name, "bytes": len(data), "sha256": sha_bytes(data)}
                  for name, data in sorted(payloads.items())],
    }
    payloads[f"{META}/inventory.json"] = json_bytes(inventory)
    payloads[f"{META}/SHA256SUMS"] = "".join(
        f"{sha_bytes(data)}  {name}\n" for name, data in sorted(payloads.items())
    ).encode("utf-8")
    return payloads, inventory


def tar_bytes(payloads):
    result = io.BytesIO()
    with gzip.GzipFile(fileobj=result, mode="wb", filename="", mtime=0, compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, data in sorted(payloads.items()):
                member = tarfile.TarInfo(f"{ARCHIVE_ROOT}/{name}")
                member.size = len(data)
                member.mode = 0o644
                member.mtime = 0
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                archive.addfile(member, io.BytesIO(data))
    return result.getvalue()


def verify_archive(path, require_complete=True):
    payloads = {}
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                require(member.isfile(), "Archive contains a non-regular member.")
                require(member.name.startswith(ARCHIVE_ROOT + "/"), "Archive root differs.")
                name = member.name[len(ARCHIVE_ROOT) + 1:]
                require(name not in payloads, "Archive has a duplicate member.")
                require(name in {f"{META}/README.md", f"{META}/inventory.json", f"{META}/SHA256SUMS"}
                        or is_allowlisted(name), "Archive member is outside the public allowlist.")
                handle = archive.extractfile(member)
                require(handle is not None, "Cannot read archive member.")
                payloads[name] = handle.read()
    except (tarfile.TarError, OSError):
        raise PackageError("Cannot read valid overlay archive.") from None
    inventory = parse_json(payloads, f"{META}/inventory.json")
    require(inventory.get("version") == VERSION and inventory.get("dependency") == BASE_RELEASE,
            "Archive identity or base-release dependency differs.")
    rows = inventory.get("files", [])
    paths = [row["path"] for row in rows]
    require(len(paths) == len(set(paths)), "Inventory has duplicate paths.")
    require(set(payloads) == set(paths) | {f"{META}/inventory.json", f"{META}/SHA256SUMS"},
            "Archive and inventory file sets differ.")
    for row in rows:
        data = payloads[row["path"]]
        require(len(data) == row["bytes"] and sha_bytes(data) == row["sha256"],
                f"Archive inventory mismatch: {row['path']}")
    sums = "".join(f"{sha_bytes(data)}  {name}\n" for name, data in sorted(payloads.items())
                   if name != f"{META}/SHA256SUMS").encode("utf-8")
    require(payloads[f"{META}/SHA256SUMS"] == sums, "Archive SHA256SUMS differs.")
    if require_complete:
        require(set(REQUIRED_FILES) <= set(payloads), "Required public evidence is missing from archive.")
        validate_captured_inputs(payloads)
    return {"verified": True, "archive_bytes": path.stat().st_size,
            "archive_sha256": sha_bytes(path.read_bytes()), "payload_file_count": len(rows),
            "archive_member_count": len(payloads),
            "inventory_sha256": sha_bytes(payloads[f"{META}/inventory.json"])}


def capture(root, mode):
    readiness = plan(root)
    require(readiness["ready"], "Public overlay files are missing: " + ", ".join(readiness["missing_files"]))
    names, _ = collect_files(root)
    for name in names:
        require_safe_source(root, name)
    sources, observations = snapshot_files(root, names, mode)
    for name in names:
        require_safe_source(root, name)
    validation = validate_captured_inputs(sources)
    secrets = credential_values(root)
    scan_payloads(sources, secrets)
    verify_source_unchanged(root, observations)
    return sources, observations, validation, secrets, readiness


def build(root, archive_path, mode, ready):
    require(ready, "Building requires --ready after the operator's public-file freeze.")
    archive_path = archive_path.absolute()
    manifest_path = Path(str(archive_path) + ".manifest.json")
    require(not archive_path.exists() and not manifest_path.exists(),
            "Existing archives/manifests are immutable; choose a new output path.")
    require(archive_path.name != BASE_RELEASE["archive"], "Cannot replace the v0.1.0 archive.")
    packaging_tests = self_test()
    sources, observations, validation, secrets, readiness = capture(root, mode)
    payloads, inventory = make_payloads(sources)
    scan_payloads(payloads, secrets)
    data = tar_bytes(payloads)
    verify_source_unchanged(root, observations)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    # Verify in a staging directory; interrupted writes never occupy the final
    # immutable filename. Hard links publish exclusively without overwriting.
    with tempfile.TemporaryDirectory(prefix=".evaluation-build-", dir=archive_path.parent) as temporary:
        staged_archive = Path(temporary) / archive_path.name
        staged_archive.write_bytes(data)
        result = verify_archive(staged_archive)
        manifest = {
            "version": VERSION, **result, "archive_filename": archive_path.name,
            "dependency": BASE_RELEASE, "source_file_count": len(sources),
            "source_bytes": sum(map(len, sources.values())), "source_snapshot_mode": mode,
            "source_snapshot_validation": snapshot_summary(observations),
            "validation": validation, "credential_scan": "passed",
            "packaging_self_tests": {"status": packaging_tests["self_test"],
                                     "check_count": len(packaging_tests["checks"]),
                                     "checks": packaging_tests["checks"]},
            "private_directories_traversed": False, "exclusions": EXCLUSIONS,
            "skipped_within_public_roots": readiness["skipped_within_public_roots"],
        }
        staged_manifest = Path(temporary) / manifest_path.name
        staged_manifest.write_bytes(json_bytes(manifest))
        created = []
        try:
            os.link(staged_archive, archive_path)
            created.append(archive_path)
            os.link(staged_manifest, manifest_path)
            created.append(manifest_path)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
    companions = root / META
    companions.mkdir(parents=True, exist_ok=True)
    for name in ("README.md", "inventory.json", "SHA256SUMS"):
        (companions / name).write_bytes(payloads[f"{META}/{name}"])
    return manifest


def self_test():
    checks = []
    with tempfile.TemporaryDirectory(prefix="spotify-overlay-test-") as temporary:
        root = Path(temporary).resolve()
        def put(name, data=b"public\n"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        put("README.md")
        put("tools/helper.py")
        put("private/answers.json", b"DO NOT READ")
        put("evals/human-evaluation-v1/actual_answers.json", b"DO NOT READ")
        put("evals/experiment-v6/private/sealed.json", b"DO NOT READ")
        put("web/src/node_modules/dependency.js", b"DO NOT READ")
        put("evals/experiment-v6/cache.sqlite", b"DO NOT READ")
        put(".env", b"EXAMPLE_API_KEY=synthetic-secret-123456\n")
        real_walk = os.walk
        visited = []
        def observed_walk(*args, **kwargs):
            for current, dirs, files in real_walk(*args, **kwargs):
                visited.append(Path(current).relative_to(root).as_posix())
                yield current, dirs, files
        with patch("os.walk", observed_walk):
            names, _ = collect_files(root)
        require(set(names) == {"README.md", "tools/helper.py"}, "Self-test: allowlist failed.")
        require(not any("private" in PurePosixPath(name).parts
                        or "node_modules" in PurePosixPath(name).parts for name in visited),
                "Self-test: protected directory traversed.")
        checks.append("protected directories pruned; human answers and databases excluded")
        (root / "tools/unsafe.py").symlink_to(root / "private/answers.json")
        try:
            collect_files(root)
        except PackageError:
            pass
        else:
            raise PackageError("Self-test: symlink accepted.")
        (root / "tools/unsafe.py").unlink()
        checks.append("allowlisted symlinks rejected")
        (root / "web/src/node_modules/dependency.js").unlink()
        (root / "web/src/node_modules").rmdir()
        (root / "web/src").rmdir()
        (root / "web").rmdir()
        (root / "web").symlink_to(root / "private", target_is_directory=True)
        try:
            collect_files(root)
        except PackageError:
            pass
        else:
            raise PackageError("Self-test: exact-file parent symlink accepted.")
        (root / "web").unlink()
        checks.append("exact-file ancestor symlinks rejected")
        (root / "private/code").mkdir()
        (root / "src").symlink_to(root / "private/code", target_is_directory=True)
        try:
            with patch("os.walk", observed_walk):
                collect_files(root)
        except PackageError:
            pass
        else:
            raise PackageError("Self-test: public-tree ancestor symlink accepted.")
        (root / "src").unlink()
        require(not any("private" in PurePosixPath(name).parts for name in visited),
                "Self-test: ancestor link caused private traversal.")
        checks.append("public-tree ancestor symlinks rejected before traversal")
        secret = b"synthetic-secret-123456"
        try:
            scan_payloads({"README.md": secret}, [secret])
        except PackageError as exc:
            require("README.md" in str(exc) and secret.decode() not in str(exc),
                    "Self-test: credential scanner leaked value.")
        else:
            raise PackageError("Self-test: credential not detected.")
        checks.append("credential detection exposes only filename")
        payloads, _ = make_payloads({"README.md": b"public\n"})
        first, second = tar_bytes(payloads), tar_bytes(payloads)
        require(first == second, "Self-test: archive is not deterministic.")
        archive = root / "test.tar.gz"
        archive.write_bytes(first)
        require(verify_archive(archive, require_complete=False)["verified"],
                "Self-test: valid archive rejected.")
        payloads["README.md"] = b"tampered\n"
        archive.write_bytes(tar_bytes(payloads))
        try:
            verify_archive(archive, require_complete=False)
        except PackageError:
            pass
        else:
            raise PackageError("Self-test: tampered archive accepted.")
        checks.append("deterministic archive, exact inventory and tamper rejection")
        require(not is_allowlisted("../private/answers.json")
                and not is_allowlisted("/etc/passwd")
                and not is_allowlisted("evals/human-evaluation-v1/answers.json"),
                "Self-test: unsafe member accepted.")
        checks.append("traversal and unlisted human files rejected")
        fake_source = dict(zip(SOURCE_FIELDS, ("synthetic-1", "Synthetic packaging case",
                                              "3", "0", "", "2026-01-01")))
        fake_row = {key: "" for key in WORKSHEET_FIELDS}
        fake_row.update(review_id="synthetic-1", review_text=fake_source["review_text"],
                        row_sha=source_hash(fake_source))
        def encoded_csv(fields, row):
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(fields)
            writer.writerow([row[key] for key in fields])
            return output.getvalue().encode("utf-8")
        validate_blank_csv(encoded_csv(WORKSHEET_FIELDS, fake_row), "synthetic.csv",
                           {"synthetic-1": fake_source}, ["synthetic-1"], 1)
        for fields, row in (
            (WORKSHEET_FIELDS + ("topic",), fake_row),
            (WORKSHEET_FIELDS[:-1], fake_row),
            (WORKSHEET_FIELDS, {**fake_row, "topic": "other"}),
            (WORKSHEET_FIELDS, {**fake_row, "review_text": "Changed source"}),
            (WORKSHEET_FIELDS, {**fake_row, "row_sha": "0" * 64}),
        ):
            try:
                validate_blank_csv(encoded_csv(fields, row), "synthetic.csv",
                                   {"synthetic-1": fake_source}, ["synthetic-1"], 1)
            except PackageError:
                pass
            else:
                raise PackageError("Self-test: changed or nonblank worksheet accepted.")
        checks.append("blank CSV exact header, width, source identity and judgment checks")
    return {"self_test": "passed", "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("plan", "scan", "build", "verify", "self-test"),
                        default="plan")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--snapshot-mode", choices=("direct", "apfs-clone"),
                        default="apfs-clone" if sys.platform == "darwin" else "direct")
    parser.add_argument("--ready", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    archive = args.archive or root / "release/spotify-evaluation-v6.tar.gz"
    try:
        if args.action == "plan":
            result = plan(root)
        elif args.action == "self-test":
            result = self_test()
        elif args.action == "verify":
            result = verify_archive(archive)
        elif args.action == "scan":
            sources, observations, validation, _, _ = capture(root, args.snapshot_mode)
            result = {"scan": "passed", "source_file_count": len(sources),
                      "source_bytes": sum(map(len, sources.values())),
                      "validation": validation, "source_snapshot_validation": snapshot_summary(observations)}
        else:
            result = build(root, archive, args.snapshot_mode, args.ready)
        displayed = dict(result)
        if "source_snapshot_validation" in displayed:
            displayed["source_snapshot_validation"] = dict(displayed["source_snapshot_validation"])
            files = displayed["source_snapshot_validation"].pop("metadata_transition_files", [])
            displayed["source_snapshot_validation"]["metadata_transition_file_count"] = len(files)
        print(json.dumps(displayed, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except PackageError as exc:
        print(f"Package error: {exc}", file=sys.stderr)
        return 2
    except (OSError, KeyError, ValueError, TypeError):
        print("Package error: malformed public input or filesystem failure; no values displayed.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
