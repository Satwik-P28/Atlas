#!/usr/bin/env python
"""Benchmark the Phase 9.1 equity paths and record the results."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from atlas.applications.service import ApplicationService
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database

ROOT = Path(__file__).resolve().parents[1]


def _timed(fn):
    started = time.perf_counter()
    value = fn()
    return value, round((time.perf_counter() - started) * 1000, 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "var" / "phase9.db"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase9_1_benchmarks.json"))
    args = parser.parse_args()
    db = Database(args.db)
    service = EquityResearchService(db)

    coverage, coverage_ms = _timed(service.coverage)
    workspace, workspace_ms = _timed(lambda: service.workspace("JPM"))
    bank, bank_ms = _timed(lambda: service.valuation("JPM"))
    insurer, insurer_ms = _timed(lambda: service.valuation("UNH"))
    report, report_ms = _timed(lambda: service.analyse("JPM"))
    package, package_ms = _timed(lambda: service.create_package("JPM"))
    # Install into a clean copy so a previous benchmark run cannot collide with the
    # same application version, and so replay is measured without warm state.
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean.db"
        shutil.copy(args.db, clean)
        clean_db = Database(str(clean))
        # A copied database may carry an earlier installation of the same application
        # version; remove installation rows so the measured install is a fresh one.
        clean_db.execute("DELETE FROM application_installation")
        clean_db.execute("DELETE FROM research_object_evidence")
        clean_db.execute("DELETE FROM research_object")
        apps = ApplicationService(clean_db)
        installed, install_ms = _timed(lambda: apps.install(package["payload"]))
        execution, execute_ms = _timed(lambda: apps.execute(installed["install_id"]))
        clean_db.close()

    payload = {
        "schema": "atlas.phase9_1.benchmarks.v1",
        "db": str(args.db),
        "timings_ms": {
            "coverage_20_issuers": coverage_ms,
            "workspace_jpm": workspace_ms,
            "bank_valuation_jpm": bank_ms,
            "insurer_valuation_unh": insurer_ms,
            "report_and_audit_jpm": report_ms,
            "package_jpm": package_ms,
            "install_package": install_ms,
            "execute_package": execute_ms,
        },
        "results": {
            "issuers": coverage["issuers"],
            "financial_coverage_valid": coverage["financial_coverage_valid"],
            "dcf_executes": coverage["dcf_executes"],
            "institution_models_execute": coverage["institution_models_execute"],
            "contract_states": coverage["contract_states"],
            "jpm_method": bank["method"],
            "jpm_contract_state": bank["contract"]["state"],
            "unh_method": insurer["method"],
            "replay_status": execution.get("status"),
        },
        "limits": [
            "Single-machine wall-clock timings; not a load test.",
            "No market prices are bundled, so price-import and multiple paths are exercised only by tests.",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["timings_ms"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
