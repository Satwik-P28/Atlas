#!/usr/bin/env python
"""Scan installed Python packages and the frontend lockfile for known vulnerabilities.

Python queries the OSV batch API with the exact installed versions — the advisory database
GitHub's advisory feed publishes to — and records every returned identifier with its
severity. The frontend scan runs ``npm audit`` because that is the registry's own advisory
graph for the lockfile.

An inconclusive scan is reported as ``not_run`` with the failure reason; it is never
recorded as clean. A release is blocked only by critical or high findings that were
actually observed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.release.dependency_scan.v1"
OSV_QUERYBATCH = "https://api.osv.dev/v1/querybatch"
BLOCKING = {"critical", "high"}
SEVERITIES = ("critical", "high", "moderate", "low", "unknown")


def python_packages() -> list[dict[str, str]]:
    from importlib import metadata

    seen: dict[tuple[str, str], dict[str, str]] = {}
    for distribution in metadata.distributions():
        name = (distribution.metadata or {}).get("Name")
        version = distribution.version
        if not name or not version:
            continue
        seen[(name.lower(), version)] = {"name": name, "version": version, "ecosystem": "PyPI"}
    return [seen[key] for key in sorted(seen)]


def normalise_severity(vulnerability: dict[str, Any]) -> str:
    specific = vulnerability.get("database_specific") or {}
    severity = str(specific.get("severity") or "").strip().lower()
    if severity in {"critical", "high", "moderate", "low"}:
        return severity
    if severity == "medium":
        return "moderate"
    for entry in vulnerability.get("severity") or []:
        score = entry.get("score")
        try:
            numeric = float(str(score))
        except (TypeError, ValueError):
            continue
        if numeric >= 9.0:
            return "critical"
        if numeric >= 7.0:
            return "high"
        if numeric >= 4.0:
            return "moderate"
        return "low"
    return "unknown"


def _osv_batch(packages: Sequence[dict[str, str]], timeout: float) -> list[dict[str, Any]]:
    body = json.dumps({
        "queries": [
            {"package": {"name": package["name"], "ecosystem": package["ecosystem"]},
             "version": package["version"]}
            for package in packages
        ]
    }).encode("utf-8")
    request = urllib.request.Request(
        OSV_QUERYBATCH, data=body,
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        payload = json.loads(response.read().decode("utf-8"))
    return list(payload.get("results") or [])


def scan_python(*, network: bool = True, timeout: float = 90.0) -> dict[str, Any]:
    packages = python_packages()
    if not network:
        return {"status": "not_run", "reason": "network disabled by --offline",
                "packages": len(packages), "findings": []}
    findings: list[dict[str, Any]] = []
    try:
        for start in range(0, len(packages), 400):
            chunk = packages[start:start + 400]
            results = _osv_batch(chunk, timeout)
            for package, result in zip(chunk, results):
                for vulnerability in result.get("vulns") or []:
                    findings.append({
                        "package": package["name"],
                        "version": package["version"],
                        "id": vulnerability.get("id"),
                        "aliases": vulnerability.get("aliases") or [],
                        "summary": (vulnerability.get("summary") or "").strip(),
                        "severity": normalise_severity(vulnerability),
                        "fixed_versions": sorted({
                            affected.get("ranges", [{}])[0].get("events", [{}])[0].get("fixed", "")
                            for affected in vulnerability.get("affected") or []
                            if affected.get("ranges")
                        } - {""}),
                    })
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {"status": "not_run", "reason": f"OSV query failed: {exc}",
                "packages": len(packages), "findings": findings}
    return {"status": "ok", "packages": len(packages), "findings": findings}


def scan_npm(web_dir: Path, *, network: bool = True, timeout: float = 180.0) -> dict[str, Any]:
    if not web_dir.is_dir():
        return {"status": "not_run", "reason": "no web directory", "findings": []}
    if not network:
        return {"status": "not_run", "reason": "network disabled by --offline", "findings": []}
    try:
        completed = subprocess.run(
            ["npm", "audit", "--json", "--audit-level=low"],
            cwd=web_dir, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "not_run", "reason": f"npm audit could not run: {exc}", "findings": []}
    try:
        payload = json.loads(completed.stdout or "{}")
    except ValueError:
        return {"status": "not_run",
                "reason": f"npm audit returned unreadable output (exit {completed.returncode})",
                "findings": []}
    findings: list[dict[str, Any]] = []
    for name, advisory in (payload.get("vulnerabilities") or {}).items():
        if advisory.get("severity") in {"critical", "high", "moderate", "low"}:
            findings.append({
                "package": name,
                "version": (advisory.get("range") or "").strip(),
                "id": (advisory.get("via") or [{}])[0].get("source") if isinstance(
                    (advisory.get("via") or [None])[0], dict) else advisory.get("via"),
                "aliases": [],
                "summary": (advisory.get("via") or [""])[0] if isinstance(
                    (advisory.get("via") or [""])[0], str) else "",
                "severity": advisory.get("severity"),
                "fixed_versions": [i.get("fixAvailable")] if isinstance(
                    advisory.get("fixAvailable"), str) else [],
            })
    return {"status": "ok", "counts": payload.get("metadata", {}).get("vulnerabilities", {}),
            "findings": findings}


def summarise(findings: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        severity = str(finding.get("severity") or "unknown").lower()
        counts[severity if severity in counts else "unknown"] += 1
    return counts


def build_report(root: Path = ROOT, *, network: bool = True) -> dict[str, Any]:
    python = scan_python(network=network)
    npm = scan_npm(root / "web", network=network)
    findings = list(python["findings"]) + list(npm["findings"])
    counts = summarise(findings)
    blocking = [finding for finding in findings
                if str(finding.get("severity")).lower() in BLOCKING]
    statuses = {python["status"], npm["status"]}
    if blocking:
        verdict = "blocked"
    elif "ok" in statuses:
        verdict = "clean" if "not_run" not in statuses else "partial"
    else:
        verdict = "not_run"
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": python,
        "npm": npm,
        "severity_counts": counts,
        "blocking_findings": len(blocking),
        "verdict": verdict,
        "policy": ("critical and high findings block a release; moderate and low findings are "
                   "recorded and triaged. An inconclusive scan is reported as not_run, never as "
                   "clean."),
        "exit_code": 1 if blocking else (3 if verdict == "not_run" else 0),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "artifacts" / "release" / "dependency_scan.json")
    parser.add_argument("--offline", action="store_true", help="skip network queries")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(ROOT, network=not args.offline)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"dependency verdict: {report['verdict']} "
              f"(python {report['python']['status']}, npm {report['npm']['status']})")
        print(f"  severity counts: {report['severity_counts']}")
        for finding in (report["python"]["findings"] + report["npm"]["findings"])[:20]:
            print(f"  {finding.get('severity', 'unknown'):8} {finding.get('package')} "
                  f"{finding.get('version')} {finding.get('id')}")
    return int(report["exit_code"])


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
