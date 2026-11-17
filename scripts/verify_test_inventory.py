#!/usr/bin/env python3
"""Reconcile the declared test inventory with what pytest actually collects.

This exists because a hand-written "718 passed / 19 tests" claim drifted from the real
suite. The inventory separates two kinds of number and refuses to conflate them:

* **observed** — counted by collecting or running the tests at this revision;
* **reconstructed** — derived by subtraction from observed totals, which is not the
  same as having counted the baseline independently.

The script fails when an observed count disagrees with collection, when the declared
parts no longer add up, or when a reconstructed number is presented as observed.

Usage:
    .venv/bin/python scripts/verify_test_inventory.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "artifacts" / "test_inventory.json"
BROWSER = ROOT / "web" / "e2e" / "price-explanation.mjs"


def collected(node: str | None = None) -> int:
    command = [sys.executable, "-m", "pytest", "-o", "addopts=", "--collect-only", "-q"]
    if node:
        command.append(node)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"pytest collection failed with exit {result.returncode}")
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if match:
        return int(match.group(1))
    ids = [line for line in result.stdout.splitlines() if "::" in line]
    return len(ids)


def main() -> int:
    inventory = json.loads(INVENTORY.read_text())
    python = inventory["python"]
    observed = python["observed"]
    reconstructed = python["reconstructed"]

    failures: list[str] = []
    lines: list[str] = []

    actual_total = collected()
    lines.append(f"observed total (collected): {actual_total}")
    if actual_total != observed["total_collected"]:
        failures.append(
            f"pytest collects {actual_total}, inventory observed total says {observed['total_collected']}"
        )

    observed_sum = 0
    for entry in observed["files"]:
        if entry.get("method") != "observed":
            failures.append(f"{entry['file']} is listed as observed but carries no observed method")
        actual = collected(entry["file"])
        lines.append(f"observed {entry['file']}: {actual}")
        if actual != entry["count"]:
            failures.append(f"{entry['file']} collects {actual}, inventory says {entry['count']}")
        observed_sum += actual

    baseline = reconstructed["baseline_tests"]
    if baseline.get("method") != "reconstructed_by_subtraction":
        failures.append(
            "the baseline count is derived by subtraction; it must be labelled "
            "reconstructed_by_subtraction, not presented as an independent measurement"
        )
    derived_baseline = actual_total - observed_sum
    lines.append(
        f"reconstructed baseline (total - observed feature files): {derived_baseline}"
    )
    if derived_baseline != baseline["count"]:
        failures.append(
            f"derived baseline is {derived_baseline}, inventory says {baseline['count']}"
        )
    lines.append(
        "provenance: total and feature counts observed; baseline reconstructed, "
        "not independently counted at the earlier revision"
    )

    browser_source = BROWSER.read_text()
    browser_checks = len(re.findall(r"\n  await check\(", browser_source))
    if browser_checks != inventory["frontend"]["browser_checks"]:
        failures.append(
            f"browser harness has {browser_checks} checks, inventory says "
            f"{inventory['frontend']['browser_checks']}"
        )
    lines.append(f"browser harness checks: {browser_checks}")
    if not inventory["frontend"].get("rerun_in_this_pass"):
        lines.append(
            "browser harness result is historical: " + inventory["frontend"]["browser_result"]
        )

    print("\n".join(lines))
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("VERIFIED: observed counts match collection; reconstructed counts are labelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
