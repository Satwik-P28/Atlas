#!/usr/bin/env python
"""Audit what a public clone of Atlas can reach, now and through history.

Two different questions matter for distribution and they have different answers:

1. *Is the current tree distributable?* If a restricted vendor dataset or a credential is
   tracked right now, the release is blocked.
2. *Is restricted material still reachable through history?* Removing a file in a later
   commit does not remove its blobs: anyone can recover them from a branch that still
   points at the earlier commit. That is an exposure, but fixing it means rewriting
   published history, which requires maintainer authorisation. This script therefore
   reports it as a finding with `history_exposed: true` and does not rewrite anything.

Exit status: 0 when the current tree is clean (history exposure alone does not fail the
run, it is reported); 1 when the current tree tracks restricted or secret-like material.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.release.distribution_audit.v1"

# Vendor datasets whose licence does not permit redistribution. The current tree must not
# contain them; their presence in history is reported separately.
RESTRICTED_VENDOR_TOKENS = ("nasdaq_", "alphavantage", "alpha_vantage")

# Path shapes that would mean a credential or local secret was committed.
SECRET_PATH_TOKENS = (
    ".env",
    "credentials.json",
    "id_rsa",
    ".pem",
    ".p12",
    "service-account",
    "secrets.yaml",
    "secrets.yml",
)

# Content shapes that are worth failing a release over when they appear in tracked text.
SECRET_CONTENT_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
)

# A vendor name in a code path (an adapter module) is not redistributed data. Only data
# files can carry the vendor's observations.
DATA_SUFFIXES = {".csv", ".json", ".parquet", ".tsv", ".txt", ".xlsx", ".xls", ".zip"}

TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".cfg", ".ini", ".js", ".ts", ".tsx", ".html", ".css", ".mjs", ".cjs", ".sh"}


def classify_path(path: str) -> str:
    """Return ``restricted_vendor``, ``secret_like`` or ``none`` for one repository path."""
    lowered = path.lower()
    base = lowered.rsplit("/", 1)[-1]
    suffix = "." + base.rsplit(".", 1)[-1] if "." in base else ""
    if any(token in base for token in RESTRICTED_VENDOR_TOKENS):
        return "restricted_vendor" if suffix in DATA_SUFFIXES else "vendor_adapter_code"
    if any(token in lowered for token in SECRET_PATH_TOKENS):
        return "secret_like"
    return "none"


def scan_paths(paths: Iterable[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {"restricted_vendor": [], "secret_like": [], "vendor_adapter_code": []}
    for path in paths:
        kind = classify_path(path)
        if kind != "none":
            found[kind].append(path)
    return {key: sorted(value) for key, value in found.items()}


def scan_contents(root: Path, paths: Sequence[str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in paths:
        if Path(path).suffix.lower() not in TEXT_SUFFIXES:
            continue
        target = root / path
        if not target.is_file() or target.stat().st_size > 2_000_000:
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - unreadable tracked file
            continue
        for pattern in SECRET_CONTENT_PATTERNS:
            if pattern.search(text):
                findings.append({"path": path, "pattern": pattern.pattern})
                break
    return findings


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def tracked_paths() -> list[str]:
    output = _git("ls-tree", "-r", "--name-only", "HEAD")
    return [line for line in output.splitlines() if line]


def history_findings() -> list[dict[str, object]]:
    """Paths whose blobs are still reachable from some ref, with the refs that hold them."""
    reachable = _git("rev-list", "--objects", "--all")
    candidates = sorted(
        {
            line.split(" ", 1)[1]
            for line in reachable.splitlines()
            if " " in line and classify_path(line.split(" ", 1)[1]) != "none"
        }
    )
    found: list[dict[str, object]] = []
    for path in candidates:
        if classify_path(path) == "none":
            continue
        commits = _git("log", "--all", "--format=%H", "--diff-filter=A", "--", path).splitlines()
        refs: list[str] = []
        for commit in commits:
            for ref in _git("branch", "-a", "--contains", commit).splitlines():
                cleaned = ref.strip().lstrip("*").strip()
                if cleaned:
                    refs.append(cleaned)
        found.append(
            {
                "path": path,
                "classification": classify_path(path),
                "added_by": commits,
                "reachable_from_refs": sorted(set(refs)),
            }
        )
    return found


def build_report(root: Path) -> dict[str, object]:
    paths = tracked_paths()
    tree = scan_paths(paths)
    contents = scan_contents(root, paths)
    history = history_findings()
    restricted_history = [item for item in history if item["classification"] == "restricted_vendor"]
    current_tree_violations = bool(tree["restricted_vendor"] or tree["secret_like"] or contents)
    return {
        "schema": SCHEMA,
        "revision": _git("rev-parse", "HEAD"),
        "tracked_file_count": len(paths),
        "current_tree": {
            "restricted_vendor_paths": tree["restricted_vendor"],
            "vendor_adapter_code": tree["vendor_adapter_code"],
            "secret_like_paths": tree["secret_like"],
            "secret_content_findings": contents,
            "clean": not (tree["restricted_vendor"] or tree["secret_like"] or contents),
        },
        "history": {
            "restricted_vendor_paths_reachable": restricted_history,
            "secret_like_paths_reachable": [
                item for item in history if item["classification"] == "secret_like"
            ],
            "history_exposed": bool(restricted_history),
            "remediation": (
                "Removing these paths in a later commit does not remove the blobs. A clean "
                "distribution requires a rewritten or fresh-history branch, which needs "
                "maintainer authorisation because existing clones and forks keep the old "
                "objects."
            ),
        },
        "verdict": (
            "blocked_current_tree" if current_tree_violations
            else "history_exposed" if restricted_history
            else "clean"
        ),
        "exit_code": 1 if current_tree_violations else 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "release" / "distribution_audit.json")
    parser.add_argument("--json", action="store_true", help="print the report to stdout")
    args = parser.parse_args(argv)

    report = build_report(ROOT)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"distribution verdict: {report['verdict']}")
        if report["current_tree"]["restricted_vendor_paths"]:
            print("  restricted vendor paths tracked:", report["current_tree"]["restricted_vendor_paths"])
        if report["current_tree"]["secret_like_paths"]:
            print("  secret-like paths tracked:", report["current_tree"]["secret_like_paths"])
        exposed = report["history"]["restricted_vendor_paths_reachable"]
        if exposed:
            print(f"  {len(exposed)} restricted vendor path(s) still reachable through history:")
            for item in exposed:
                print(f"    {item['path']} (added by {', '.join(c[:8] for c in item['added_by'])})")
    return int(report["exit_code"])


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
