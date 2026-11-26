#!/usr/bin/env python
"""Build a distribution-safe source snapshot of one commit, without touching history.

Why this exists: the repository's history contains vendor market-data files whose licence
does not permit redistribution. Removing them from the current tree is not enough, because
the blobs remain reachable from the commits that contain them. Rewriting published history
needs maintainer authorisation and would invalidate every existing clone. Until then, a
public distribution candidate must be a *snapshot* that never contained those paths.

This script therefore:

* reads the exact blob set of one commit (``git ls-tree -r``),
* drops every path the distribution audit classifies as restricted vendor data,
* writes a deterministic tar.gz (zeroed timestamps, no owner data, gzip mtime 0),
* verifies the written archive contains none of the excluded paths,
* records the excluded path and blob ids so the removal is auditable.

The original repository, its refs and its objects are untouched. The archive is a source
distribution, not a replacement history: if shipped, it accompanies a clear statement that
the public Git history still exposes the excluded blobs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.release.sanitized_archive.v1"


def _audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_distribution", ROOT / "scripts" / "audit_distribution.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def commit_entries(commit: str) -> list[dict[str, str]]:
    """Every blob in the commit's tree, as ``{path, sha}``."""
    output = subprocess.check_output(["git", "ls-tree", "-r", "-z", commit], cwd=ROOT)
    entries: list[dict[str, str]] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        parts = meta.decode("utf-8").split()
        if len(parts) < 3 or parts[1] != "blob":
            continue
        entries.append({"path": path.decode("utf-8"), "sha": parts[2]})
    return entries


def select(entries: Iterable[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split entries into distributable and excluded paths."""
    audit = _audit_module()
    included: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    for entry in entries:
        kind = audit.classify_path(entry["path"])
        if kind in {"restricted_vendor", "secret_like"}:
            excluded.append({**entry, "classification": kind})
        else:
            included.append(entry)
    return included, excluded


def _blob(sha: str) -> bytes:
    return subprocess.check_output(["git", "cat-file", "blob", sha], cwd=ROOT)


def write_archive(entries: Sequence[dict[str, str]], target: Path) -> dict[str, Any]:
    """Write a deterministic gzip'd tar of the given blob set."""
    target.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for entry in sorted(entries, key=lambda item: item["path"]):
            data = _blob(entry["sha"])
            info = tarfile.TarInfo(name=entry["path"])
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    with open(target, "wb") as handle:
        import gzip

        # filename="" keeps the output name out of the gzip header, so two builds of the
        # same tree produce the same bytes regardless of where they were written.
        with gzip.GzipFile(filename="", fileobj=handle, mode="wb", mtime=0) as compressed:
            compressed.write(buffer.getvalue())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {"path": str(target), "sha256": digest, "bytes": target.stat().st_size,
            "files": len(entries)}


def verify_archive(target: Path, excluded: Sequence[dict[str, str]]) -> dict[str, Any]:
    excluded_paths = {entry["path"] for entry in excluded}
    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
    offenders = sorted(set(names) & excluded_paths)
    return {
        "files": len(names),
        "excluded_present": offenders,
        "clean": not offenders,
    }


def build(commit: str = "HEAD", out: Path | None = None) -> dict[str, Any]:
    out = out or (ROOT / "dist" / f"atlas-source-{commit[:12]}-sanitized.tar.gz")
    included, excluded = select(commit_entries(commit))
    archive = write_archive(included, out)
    verification = verify_archive(out, excluded)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": subprocess.check_output(["git", "rev-parse", commit], cwd=ROOT,
                                          text=True).strip(),
        "commit_subject": subprocess.check_output(
            ["git", "log", "-1", "--format=%s", commit], cwd=ROOT, text=True
        ).strip(),
        "archive": archive,
        "excluded": excluded,
        "verification": verification,
        "history_preserved": {
            "rewritten": False,
            "note": "the repository, its refs and its objects are untouched. The excluded blobs "
                    "remain reachable from the commits that contain them, which is why a public "
                    "Git history still requires an authorised rewrite or a fresh-history branch.",
        },
        "exit_code": 0 if verification["clean"] else 1,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "artifacts" / "release" / "sanitized_archive.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build(args.commit, args.out)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"sanitized archive: {report['archive']['path']}")
        print(f"  sha256 {report['archive']['sha256']}")
        print(f"  files {report['archive']['files']}, excluded {len(report['excluded'])}")
        for entry in report["excluded"]:
            print(f"    excluded {entry['path']} ({entry['sha'][:12]})")
        print(f"  verification: {'clean' if report['verification']['clean'] else 'FAILED'}")
    return int(report["exit_code"])


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
