#!/usr/bin/env python3
"""Build the local Phase 7 economic-intelligence database.

Usage:
    .venv/bin/python scripts/build_phase7_db.py --db var/atlas-phase7.db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.economic.service import EconomicService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "var" / "atlas-phase7.db"))
    parser.add_argument("--no-run", action="store_true")
    args = parser.parse_args()
    db = Database(args.db)
    try:
        applied = db.migrate()
        ensure_default_sources(db)
        service = EconomicService(db)
        boot = service.bootstrap()
        out = {"database": str(args.db), "migrations_applied": applied, "schema": db.schema_version(),
               "bootstrap_counts": boot["counts"]}
        if not args.no_run:
            existing = service.list_runs(limit=1)
            run = (service.get_run(existing[0]["run_id"]) if existing
                   else service.analyze(as_of=iso(utcnow()), persist=True))
            scenario = service.scenario(run["run_id"])
            app = service.save_application(
                run["run_id"], scenario_id=scenario["scenario_id"],
                name=f"Weather to electricity · ERCOT 2023 · {run['run_id'][-8:]}",
                purpose="A reproducible public-data investigation of Dallas temperature, ERCOT "
                        "electricity demand and an explicitly hypothetical manufacturing exposure.",
            )
            out.update({
                "run_id": run["run_id"],
                "conclusion": run["conclusion"],
                "test_rmse": run["test"]["rmse"],
                "baseline_rmse": run["baseline"]["rmse"],
                "skill_vs_seasonal": run["skill_vs_seasonal"],
                "causal_status": run["causal_status"],
                "scenario_id": scenario["scenario_id"],
                "scenario_demand_change": scenario["demand"]["change_fraction"],
                "scenario_cost_delta_usd": scenario["financial"]["cost_delta_usd"],
                "application_object_id": app["object_id"],
            })
        print(json.dumps(out, indent=2, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
