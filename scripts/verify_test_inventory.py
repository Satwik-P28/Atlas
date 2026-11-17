#!/usr/bin/env python3
"""Reconcile the declared test inventory with the tests pytest actually collects.

This exists because a hand-written "718 passed / 19 tests" claim drifted from the real
suite. The inventory is the single machine-readable source; this script fails when the
baseline, feature count or total no longer add up, or when the browser harness no longer
contains the number of checks it claims.

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
FEATURE = ROOT / "tests" / "test_price_explanations.py"
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

    actual_total = collected()
    actual_feature = collected("tests/test_price_explanations.py")
    declared_total = (
        python["baseline_tests"] + python["feature_tests"] + python["other_added_tests"]
    )

    failures: list[str] = []
    if declared_total != python["expected_total"]:
        failures.append(
            f"declared parts sum to {declared_total}, expected_total says {python['expected_total']}"
        )
    if actual_total != python["expected_total"]:
        failures.append(f"pytest collects {actual_total}, inventory expects {python['expected_total']}")
    if actual_feature != python["feature_tests"]:
        failures.append(
            f"{FEATURE.name} collects {actual_feature}, inventory says {python['feature_tests']}"
        )

    browser_source = BROWSER.read_text()
    browser_checks = len(re.findall(r"\n  await check\(", browser_source))
    if browser_checks != inventory["frontend"]["browser_checks"]:
        failures.append(
            f"browser harness has {browser_checks} checks, inventory says "
            f"{inventory['frontend']['browser_checks']}"
        )

    print(f"baseline={python['baseline_tests']} feature={actual_feature} total={actual_total}")
    print(f"browser_checks={browser_checks}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("VERIFIED: test inventory matches collected tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
