#!/usr/bin/env python
"""Build the Phase 8 flagship package and its declarative domain pack.

This script intentionally starts from a fresh SQLite database and the repository's
real 2023 NOAA/EIA fixture, so the artifact cannot depend on somebody's local state.
The package is unsigned; its sidecar records the SHA-256 that the pack pins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.applications.service import ApplicationService  # noqa: E402
from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.economic.service import EconomicService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402

AS_OF = "2026-11-05T23:59:59Z"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "fixtures" / "phase8"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atlas-phase8-") as directory:
        db = Database(Path(directory) / "source.db")
        try:
            db.migrate()
            ensure_default_sources(db)
            economic = EconomicService(db)
            economic.bootstrap()
            run = economic.analyze(as_of=AS_OF, persist=True)
            scenario = economic.scenario(run["run_id"])
            built = ApplicationService(db).create_economic_package(
                run["run_id"], scenario_id=scenario["scenario_id"], version="1.0.0"
            )
        finally:
            db.close()

    package_path = out / "flagship_weather_demand.atlas"
    package_path.write_bytes(built["payload"])
    package_sha = hashlib.sha256(built["payload"]).hexdigest()
    pack = {
        "schema": "atlas.domain_pack.v1",
        "pack_id": "atlas.energy-research",
        "name": "Energy research essentials",
        "version": "1.0.0",
        "publisher": {"id": "atlas.first-party", "name": "Atlas Quant first-party"},
        "license": "Apache-2.0 for pack metadata; source data retains its listed public-domain terms.",
        "compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"},
        "kind": "declarative",
        "dependencies": {
            "compiler": "atlas.fec.compiler.v1",
            "operators": [{"name": "mul", "version": "1.0.0"}],
        },
        "capabilities": ["execute_fec_operator", "render_declarative_ui"],
        "sources": [
            {"source_id": "eia-930", "license": "U.S. Government public domain",
             "redistribution": "permitted"},
            {"source_id": "noaa-ghcn", "license": "U.S. Government public domain",
             "redistribution": "permitted"},
        ],
        "resources": {"max_package_bytes": 8388608},
        "object_types": ["weather_demand_analysis", "application"],
        "validation": {
            "mode": "package-integrity-and-runtime-reproduction",
            "expected_status": "reproduced",
        },
        "test_vectors": [
            {"name": "Flagship panel reproduces",
             "expected": {"status": "reproduced", "test_rmse": 2956.577890101359,
                          "test_r2": -0.8934655019352953}},
        ],
        "limitations": [
            "The pack carries one explicit weather-demand application; it is not a marketplace.",
            "It contains no real-estate, private-location, executable-plugin or collaboration component.",
            "The application remains an association, not an identified causal effect.",
        ],
        "applications": [
            {"path": "flagship_weather_demand.atlas", "sha256": package_sha,
             "application_id": built["application_id"], "version": built["version"]},
        ],
        "created_at": AS_OF,
    }
    pack_path = out / "energy_research_pack.json"
    pack_path.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    readme = (
        "# Phase 8 fixtures\n\n"
        "`flagship_weather_demand.atlas` is built from the repository's real 2023 EIA-930\n"
        "and NOAA GHCN-Daily fixtures through the ordinary Economic Lab and package code.\n"
        "It is unsigned. The SHA-256 in `energy_research_pack.json` proves byte integrity,\n"
        "not publisher identity.\n\n"
        f"- run: `{run['run_id']}`\n"
        f"- scenario: `{scenario['scenario_id']}`\n"
        f"- package: `{built['package_id']}`\n"
        f"- package SHA-256: `{package_sha}`\n"
        f"- built at: `{iso(utcnow())}` (the pinned artifact, not a live rebuild)\n"
        "- limitations: test RMSE 2,956.58 MW, test R² -0.8935, positive bias, unidentified causality,\n"
        "  hypothetical manufacturer exposure, current archive rather than historical vintage.\n"
    )
    (out / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps({
        "package": str(package_path), "package_sha256": package_sha,
        "pack": str(pack_path), "run_id": run["run_id"],
        "scenario_id": scenario["scenario_id"], "size_bytes": len(built["payload"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
