#!/usr/bin/env python3
"""Stage an exact local execution snapshot without inference or publication.

Use a destination outside iCloud-managed Documents. Persistent databases and
results stay in the source project; only code, configuration and input CSVs are
copied. This tool never launches the runner or reads human annotation files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

MANIFEST = "local-runtime-manifest.json"
SCHEMA = "spotify-local-runtime-v1"
INPUTS = ("data/hero_200000.csv", "data/source/spotify_reviews_18months.csv")
REQUIRED = (
    "src/spotify_pipeline/__init__.py", "src/spotify_pipeline/engine.py",
    "tools/run_hero.py", "tools/record_command.py", "config/hero.json",
    "vendor/course/check_submission.py", "web/database/schema.sql", *INPUTS,
)
OPTIONAL_TOOLS = (
    "tools/trace_guard.py", "tools/bundle_traces.py",
    "tools/report_hero_pilot.py", "tools/stage_local_runtime.py",
)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def hydrate(path: Path) -> None:
    """Request one exact iCloud file at a time; directories are insufficient."""
    if (sys.platform == "darwin" and path.stat().st_size
            and path.stat().st_blocks == 0 and shutil.which("brctl")):
        subprocess.run(["brctl", "download", str(path)], timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)


def owned_parent(destination: Path, relative: str) -> None:
    """Never follow a destination directory link when copying owned files."""
    parent = destination
    for part in Path(relative).parts[:-1]:
        parent /= part
        if parent.is_symlink():
            raise ValueError(f"Refusing to write through directory symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Required directory is a file: {parent}")


def collect(source: Path) -> tuple[list[str], dict[str, Path]]:
    missing = [name for name in REQUIRED if not (source / name).is_file()]
    if missing:
        raise ValueError("Missing required source files: " + ", ".join(missing))
    copies = set(REQUIRED)
    for directory, suffixes in (
        ("src/spotify_pipeline", {".py"}),
        ("config", {".json", ".csv"}), ("prompts", {".md"}),
        ("vendor/course", {".py", ".json", ".md"}),
        ("web/database", {".sql"}),
    ):
        for path in (source / directory).rglob("*"):
            if path.is_file() and path.suffix in suffixes and "__pycache__" not in path.parts:
                copies.add(str(path.relative_to(source)))
    copies.update(name for name in OPTIONAL_TOOLS if (source / name).is_file())
    links = {name: source / name for name in ("runs", "evals", ".git")}
    for path in (source / "data").iterdir():
        if path.name == "source":
            for child in path.iterdir():
                if child.name != "spotify_reviews_18months.csv":
                    links[f"data/source/{child.name}"] = child
        elif path.name != "hero_200000.csv":
            links[f"data/{path.name}"] = path
    # Keep future database creation in the canonical project as well.
    for name in ("hero-v1.sqlite3", "spend.sqlite3"):
        links[f"data/{name}"] = source / "data" / name
    return sorted(copies), links


def stage(source: Path, destination: Path, *, refresh: bool, copy_env: bool) -> dict:
    source = source.resolve(strict=True)
    destination = destination.expanduser().absolute()
    if destination.is_symlink():
        raise ValueError("Destination itself must not be a symlink")
    destination = destination.resolve()
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Source and runtime must be separate, non-nested directories")
    if destination.exists() and not destination.is_dir():
        raise ValueError("Destination must be a directory")
    copies, links = collect(source)
    if copy_env:
        if not (source / ".env").is_file():
            raise ValueError("--copy-env requires a source .env file")
        copies.append(".env")
    elif (source / ".env").is_file():
        links[".env"] = source / ".env"
    old_manifest = destination / MANIFEST
    if destination.exists() and any(destination.iterdir()) and not old_manifest.is_file() and not refresh:
        raise ValueError("Unmanaged nonempty destination; choose a new directory or explicitly use --refresh")
    if old_manifest.is_file():
        previous = json.loads(old_manifest.read_text())
        if (previous.get("schema") != SCHEMA or previous.get("source") != str(source)) and not refresh:
            raise ValueError("Destination belongs to a different snapshot; explicit --refresh required")

    file_info = []
    conflicts = []
    pending = []
    for relative in copies:
        owned_parent(destination, relative)
        original = source / relative
        hydrate(original)
        sha = digest(original)
        target = destination / relative
        if target.is_dir() and not target.is_symlink():
            raise ValueError(f"Required file is an existing directory: {target}")
        same = target.is_file() and not target.is_symlink() and digest(target) == sha
        if (target.exists() or target.is_symlink()) and not same:
            conflicts.append(relative)
        if not same:
            pending.append((relative, sha))
        if relative != ".env":
            file_info.append({"path": relative, "bytes": original.stat().st_size, "sha256": sha})
    for relative, canonical in links.items():
        owned_parent(destination, relative)
        target = destination / relative
        same = target.is_symlink() and target.resolve() == canonical.resolve()
        if target.is_dir() and not target.is_symlink():
            raise ValueError(f"Refusing to replace persistent directory with a link: {target}")
        if (target.exists() or target.is_symlink()) and not same:
            conflicts.append(relative)
    if conflicts and not refresh:
        raise ValueError("Nonmatching runtime files; explicit --refresh required: " + ", ".join(conflicts))

    destination.parent.mkdir(parents=True, exist_ok=True)
    needed = sum((source / name).stat().st_size for name, _ in pending)
    if shutil.disk_usage(destination.parent).free < needed + 64_000_000:
        raise ValueError("Insufficient disk space for verified staging plus 64 MB reserve")
    # Verify every replacement before changing the existing snapshot.
    with tempfile.TemporaryDirectory(prefix=".spotify-runtime-stage-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        for relative, expected in pending:
            original = source / relative
            prepared = staging / relative
            prepared.parent.mkdir(parents=True, exist_ok=True)
            if relative == ".env":
                prepared.touch(mode=0o600, exist_ok=False)
            shutil.copyfile(original, prepared)
            if digest(prepared) != expected or digest(original) != expected:
                raise ValueError(f"Source changed during staging: {relative}; retry after edits finish")
            os.chmod(prepared, 0o600 if relative == ".env" else original.stat().st_mode & 0o777)
        destination.mkdir(exist_ok=True)
        for relative, _ in pending:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / relative, target)
        for relative, canonical in links.items():
            target = destination / relative
            if target.is_symlink() and target.resolve() == canonical.resolve():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_link = staging / ("link-" + hashlib.sha256(relative.encode()).hexdigest())
            temporary_link.symlink_to(canonical, target_is_directory=canonical.is_dir())
            os.replace(temporary_link, target)
        if copy_env:
            os.chmod(destination / ".env", 0o600)
        result = {
            "schema": SCHEMA, "source": str(source), "destination": str(destination),
            "created_at_unix": time.time(), "files": file_info,
            "persistent_links": {name: str(path) for name, path in sorted(links.items())},
            "credentials": {"mode": "private-copy-0600" if copy_env else "source-link-or-environment",
                            "contents_logged": False},
            "source_files_modified": False, "model_calls": 0,
        }
        prepared_manifest = staging / MANIFEST
        prepared_manifest.write_text(json.dumps(result, indent=2) + "\n")
        os.replace(prepared_manifest, destination / MANIFEST)
    return {"destination": str(destination), "manifest": str(destination / MANIFEST),
            "verified_files": len(file_info), "replaced_files": len(pending),
            "copied_input_bytes": sum((source / name).stat().st_size for name in INPUTS),
            "credentials": result["credentials"]["mode"], "model_calls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path,
                        help="Dedicated runtime directory outside the source project and iCloud")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--refresh", action="store_true",
                        help="Explicitly replace nonmatching owned files; unknown files remain untouched")
    parser.add_argument("--copy-env", action="store_true",
                        help="Copy .env privately with mode 0600; otherwise link it when present")
    args = parser.parse_args()
    try:
        result = stage(args.source, args.destination, refresh=args.refresh, copy_env=args.copy_env)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Staging failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
