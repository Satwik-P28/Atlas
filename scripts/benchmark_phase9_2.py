#!/usr/bin/env python
"""Time Phase 9.2 paths without changing the working database."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from atlas.applications.contracts import read_package
from atlas.applications.service import ApplicationService
from atlas.research import fr_y9c, regulatory
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database


def timed(fn):
    start = time.perf_counter()
    value = fn()
    return round((time.perf_counter() - start) * 1000, 3), value


db = Database("var/phase9.db", create=False)
svc = EquityResearchService(db)
out: dict[str, object] = {}

out["regulatory_evidence_jpm"], _ = timed(
    lambda: regulatory.regulatory_evidence(db, cik="19617")
)
out["entity_resolution"], _ = timed(lambda: regulatory.reconcile_entities(db, "19617"))
out["fr_y9c_evidence_jpm"], _ = timed(
    lambda: fr_y9c.holding_company_evidence(db, cik="19617", cutoff="2025-06-30")
)
out["bank_v2_jpm"], _ = timed(lambda: svc.valuation("JPM"))
out["bank_v2_gs"], _ = timed(lambda: svc.valuation("GS"))
out["insurer_unh"], _ = timed(lambda: svc.valuation("UNH"))
out["market_analysis_jpm"], _ = timed(lambda: svc.valuation("JPM")["market"])
out["report_jpm"], report = timed(lambda: svc.analyse("JPM"))
out["package_jpm"], package = timed(lambda: svc.create_package("JPM"))
out["report_bytes"] = len(report["report"].encode())
out["package_bytes"] = len(package["payload"])

with tempfile.TemporaryDirectory() as directory:
    fresh = Database(Path(directory) / "import.db")
    fresh.migrate()
    regulatory.seed_entities(fresh)
    out["fr_y9c_bulk_import"], imported = timed(
        lambda: fr_y9c.ingest_archive(
            fresh,
            ROOT / "fixtures" / "regulatory" / "BHCF20241231.ZIP",
            ROOT / "fixtures" / "regulatory" / "Financial_Download_Dictionary.xlsx",
            cik="19617",
            entity_id="REG-JPM-PARENT",
            retrieved_at="2026-11-06T20:00:00Z",
        )
    )
    out["fr_y9c_rows_in_archive"] = imported["archive"]["rows_in_archive"]
    out["fr_y9c_observations_written"] = imported["observations_written"]
    out["fr_y9c_missing_fields"] = imported["missing_fields"]
    out["fr_y9c_consolidated_statement"], _ = timed(
        lambda: fr_y9c.holding_company_evidence(
            fresh, cik="19617", cutoff="2025-06-30"
        )
    )
    fresh.close()

with tempfile.TemporaryDirectory() as directory:
    fresh = Database(Path(directory) / "install.db")
    migrations = fresh.migrate()
    service = ApplicationService(fresh)
    out["package_install"], installed = timed(
        lambda: service.install(package["payload"])
    )
    out["package_execute"], execution = timed(
        lambda: service.execute(installed["install_id"])
    )
    out["package_executed_status"] = execution["status"]
    out["package_executed_reproduced"] = execution["reproduced"]
    out["fresh_schema"] = fresh.schema_version()
    out["fresh_migrations"] = migrations
    fresh.close()

loaded = read_package(package["payload"])
exported = ROOT / "artifacts" / "phase9_2_application.atlas"
out["source_sizes"] = {
    "bhcf_zip_bytes": (ROOT / "fixtures" / "regulatory" / "BHCF20241231.ZIP").stat().st_size,
    "dictionary_bytes": (
        ROOT / "fixtures" / "regulatory" / "Financial_Download_Dictionary.xlsx"
    ).stat().st_size,
    "benchmark_package_bytes": len(package["payload"]),
    "benchmark_package_sha256": loaded["package_sha256"],
    "exported_artifact_bytes": exported.stat().st_size,
    "exported_artifact_sha256": hashlib.sha256(exported.read_bytes()).hexdigest(),
    "fr_y9c_member_rows": out["fr_y9c_rows_in_archive"],
    "database_bytes": Path("var/phase9.db").stat().st_size,
}
browser_path = Path("artifacts/phase9_2_browser.json")
if browser_path.exists():
    browser = json.loads(browser_path.read_text())
    out["browser_workflow_ms"] = browser.get("browser_workflow_ms")
    out["browser_known_data_gaps"] = browser.get("known_data_gaps", [])

print(json.dumps(out, indent=2, sort_keys=True))
Path("artifacts/phase9_2_benchmarks.json").write_text(json.dumps(out, indent=2, sort_keys=True))
db.close()
