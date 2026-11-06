#!/usr/bin/env python
"""Time Phase 9.2 paths without changing stored data."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from atlas.research import regulatory
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database

def timed(fn):
    start = time.perf_counter(); value = fn(); return round((time.perf_counter() - start) * 1000, 3), value

db = Database("var/phase9.db", create=False); svc = EquityResearchService(db)
out = {}
out["regulatory_evidence_jpm"], _ = timed(lambda: regulatory.regulatory_evidence(db, cik="19617"))
out["entity_resolution"], _ = timed(lambda: regulatory.reconcile_entities(db, "19617"))
out["bank_v2_jpm"], _ = timed(lambda: svc.valuation("JPM"))
out["bank_v2_gs"], _ = timed(lambda: svc.valuation("GS"))
out["insurer_unh"], _ = timed(lambda: svc.valuation("UNH"))
out["market_analysis_jpm"], _ = timed(lambda: svc.valuation("JPM")["market"])
out["report_jpm"], report = timed(lambda: svc.analyse("JPM"))
out["package_jpm"], package = timed(lambda: svc.create_package("JPM"))
out["report_bytes"] = len(report["report"].encode())
out["package_bytes"] = len(package["payload"])
print(json.dumps(out, indent=2, sort_keys=True))
Path("artifacts/phase9_2_benchmarks.json").write_text(json.dumps(out, indent=2, sort_keys=True))
db.close()
