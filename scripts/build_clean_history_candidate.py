#!/usr/bin/env python
"""Build and verify an isolated clean-history repository from the sanitized snapshot.

The public repository's history still contains vendor market-data blobs whose licences do not
permit redistribution. A snapshot archive removes them from the *tree*; a new repository with
its own single commit removes them from the *history* of that candidate. This script builds
that candidate locally, proves it does not contain the restricted paths, and writes a
cryptographic provenance mapping back to the original release commit.

It rewrites nothing in the original repository, changes no visibility, deletes no reference and
publishes nothing: creating the candidate is the only action, and publication remains a
maintainer decision (see docs/REPOSITORY_MIGRATION.md for the exact commands).

Usage::

    .venv/bin/python scripts/build_clean_history_candidate.py --commit HEAD
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.provenance_mapping.v1"

# Paths that must never appear in a distribution candidate, as prefixes.
FORBIDDEN_PREFIXES = ("data/vendor/", "fixtures/vendor/", "fixtures/nasdaq/", "fixtures/alphavantage/")
FORBIDDEN_SUBSTRINGS = ("nasdaq_screener", "alpha_vantage", "alphavantage")


def load_sanitizer():
    path = ROOT / "scripts" / "build_sanitized_archive.py"
    spec = importlib.util.spec_from_file_location("build_sanitized_archive", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def git(*arguments: str, cwd: Path) -> str:
    result = subprocess.run(["git", *arguments], cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()[:400]}")
    return result.stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


DATA_EXTENSIONS = (".csv", ".tsv", ".json", ".parquet", ".xlsx", ".zip", ".gz", ".db")


def forbidden(path: str) -> bool:
    """Vendor *data* is forbidden; connector code that mentions a vendor is not.

    `src/atlas/ingestion/market_alphavantage.py` is Atlas's own client, not vendor data. A
    path only counts when it lives in a data directory or carries a data-file extension.
    """
    lowered = path.lower()
    if lowered.startswith(FORBIDDEN_PREFIXES):
        return True
    if not (lowered.startswith(("fixtures/", "data/", "artifacts/"))
            or lowered.endswith(DATA_EXTENSIONS)):
        return False
    return any(token in lowered for token in FORBIDDEN_SUBSTRINGS)


def build(commit: str, target: Path) -> dict[str, Any]:
    sanitizer = load_sanitizer()
    report = sanitizer.build(commit, None)
    report["commit_date"] = git("log", "-1", "--format=%cI", report["commit"], cwd=ROOT).strip()
    archive = Path(report["archive"]["path"])
    if not archive.is_absolute():
        archive = ROOT / archive

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:  # refuse absolute paths and parent traversal
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError(f"unsafe archive member: {name}")
        tar.extractall(target, filter="data")

    # A single root directory from the archive is flattened into the repository.
    entries = [item for item in target.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        for child in inner.iterdir():
            shutil.move(str(child), str(target / child.name))
        inner.rmdir()

    git("init", "-q", "-b", "main", cwd=target)
    git("config", "user.name", "Atlas Release Bot", cwd=target)
    git("config", "user.email", "release@atlas.invalid", cwd=target)
    git("add", "-A", cwd=target)
    from atlas import __release_label__

    message = (f"Atlas {__release_label__} distribution source\n\n"
               f"Sanitized snapshot of {report['commit']} with restricted vendor data excluded.\n"
               f"Provenance: docs/PROVENANCE_MAPPING.json.")
    environment = {
        "GIT_AUTHOR_NAME": "Atlas Release Bot",
        "GIT_AUTHOR_EMAIL": "release@atlas.invalid",
        "GIT_COMMITTER_NAME": "Atlas Release Bot",
        "GIT_COMMITTER_EMAIL": "release@atlas.invalid",
        "GIT_AUTHOR_DATE": report["commit_date"],
        "GIT_COMMITTER_DATE": report["commit_date"],
    }
    import os

    subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(target), check=True,
                   env={**os.environ, **environment}, capture_output=True, text=True)

    head = git("rev-parse", "HEAD", cwd=target).strip()
    tree = git("rev-parse", "HEAD^{tree}", cwd=target).strip()
    objects = git("rev-list", "--objects", "--all", cwd=target).splitlines()
    paths = [line.split(" ", 1)[1] for line in objects if " " in line]
    leaked = [path for path in paths if forbidden(path)]
    tracked = git("ls-files", cwd=target).splitlines()
    status = git("status", "--porcelain", cwd=target).strip()

    return {
        "target": str(target.relative_to(ROOT)) if target.is_relative_to(ROOT) else str(target),
        "original_commit": report["commit"],
        "original_commit_date": report["commit_date"],
        "sanitized_commit": head,
        "sanitized_tree": tree,
        "archive": {"path": str(archive), "sha256": sha256_file(archive),
                    "bytes": archive.stat().st_size, "files": report["archive"]["files"]},
        "tracked_files": len(tracked),
        "objects": len(objects),
        "clean_tree": status == "",
        "excluded_paths": [entry["path"] for entry in report["excluded"]],
        "excluded_blobs": [{"path": entry["path"], "blob": entry["sha"]} for entry in report["excluded"]],
        "restricted_paths_reachable": leaked,
        "verification": {
            "no_restricted_paths_in_history": leaked == [],
            "clean_working_tree": status == "",
            "single_commit": len(git("rev-list", "--all", cwd=target).split()) == 1,
            "tree_matches_archive": report["verification"].get("clean") is True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--target", type=Path, default=ROOT / ".release" / "clean-history")
    parser.add_argument("--provenance", type=Path,
                        default=ROOT / "docs" / "PROVENANCE_MAPPING.json")
    args = parser.parse_args(argv)

    report = build(args.commit, args.target)
    report["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report["schema"] = SCHEMA
    report["note"] = (
        "The candidate is a fresh-history snapshot. It does not fix exposure in the original "
        "repository, whose history still contains the excluded blobs until the maintainer "
        "authorises a rewrite or makes that repository private.")
    args.provenance.write_text(json.dumps(report, indent=2) + "\n")

    passed = all(report["verification"].values())
    print(f"clean-history candidate: {report['target']} @ {report['sanitized_commit'][:12]}")
    print(f"  files {report['tracked_files']}, objects {report['objects']}, "
          f"archive {report['archive']['sha256'][:16]}")
    print(f"  excluded paths: {len(report['excluded_paths'])}; "
          f"restricted reachable: {len(report['restricted_paths_reachable'])}")
    for name, ok in report["verification"].items():
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    print(f"  provenance: {args.provenance}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
