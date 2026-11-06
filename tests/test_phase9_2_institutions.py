"""Phase 9.2 tests: regulatory entities, bank v2, market rights and method rejection."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
from atlas.applications.contracts import read_package
from atlas.applications.service import ApplicationService
from atlas.research import institutions, regulatory
from atlas.research.equity import EquityResearchService
from atlas.research.prices import import_price_series, price_on_or_before
from atlas.storage.db import Database

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope="module")
def live(tmp_path_factory):
    path = tmp_path_factory.mktemp("phase9-2") / "phase9.db"
    subprocess.run([sys.executable, str(ROOT/"scripts"/"build_phase9_db.py"), "--db", str(path),
                    "--tickers", "JPM,GS,UNH"], check=True, capture_output=True)
    db = Database(path, create=False)
    db.migrate(); regulatory.seed_entities(db)
    for fixture in sorted((ROOT/"fixtures"/"regulatory").glob("fdic_*.json")):
        import json
        regulatory.ingest_fdic_payload(db, json.loads(fixture.read_text()))
    rows = [{"date": "2025-12-31", "open": 300, "high": 330, "low": 300, "close": 322.22, "volume": 1000},
            {"date": "2026-11-05", "open": 330, "high": 340, "low": 330, "close": 335.0, "volume": 1000}]
    import_price_series(db, ticker="JPM", rows=rows, source_name="test feed", licence="restricted test",
                        redistribution="restricted", adjustment_semantics="unadjusted")
    yield db, path
    db.close()

def test_entity_map_is_verified_and_not_additive(live):
    _, _ = live
    db, _ = live
    mapping = regulatory.reconcile_entities(db, "19617")
    assert mapping["status"] == "verified"
    assert mapping["parent"]["consolidation_basis"] == regulatory.PARENT
    assert all(s["consolidation_basis"] == regulatory.SUBSIDIARY for s in mapping["subsidiaries"])

def test_parent_subsidiary_aggregation_rejected(live):
    with pytest.raises(regulatory.RegulatoryReconciliationError):
        regulatory.assert_comparable([
            {"entity_id": "P", "consolidation_basis": regulatory.PARENT, "period_end": "2025-12-31"},
            {"entity_id": "S", "consolidation_basis": regulatory.SUBSIDIARY, "period_end": "2025-12-31"},
        ])

def test_period_mismatch_rejected(live):
    with pytest.raises(regulatory.RegulatoryReconciliationError):
        regulatory.assert_comparable([
            {"entity_id": "S", "consolidation_basis": regulatory.SUBSIDIARY, "period_end": "2025-12-31"},
            {"entity_id": "S", "consolidation_basis": regulatory.SUBSIDIARY, "period_end": "2026-06-30"},
        ])

def test_bank_v2_uses_subisidiary_tangible_equity_not_parent_shares(live):
    db, _ = live
    v = EquityResearchService(db).valuation("JPM")
    model = v["institution"]
    assert model["model_version"] == institutions.BANK_MODEL_VERSION_V2
    assert model["regulatory"]["entity_map"]["status"] == "verified"
    assert model["tangible_book"]["used_in_per_share"] is False
    assert model["tangible_book"]["tangible_common_equity_usd"] > 0
    assert model["capital"]["observed_percent"]["tier_1_leverage"] > 4

def test_jpm_and_gs_differentiate_cost_of_equity(live):
    db, _ = live
    svc = EquityResearchService(db)
    jpm, gs = svc.valuation("JPM"), svc.valuation("GS")
    assert jpm["institution"]["assumptions"]["cost_of_equity"] == 0.10
    assert gs["institution"]["assumptions"]["cost_of_equity"] == 0.11
    assert gs["institution"]["driver"]["business_model"] == "capital_markets"

def test_implied_cost_of_equity_reproduces_price(live):
    db, _ = live
    model = EquityResearchService(db).valuation("JPM")["institution"]
    implied = model["implied"]
    assert implied["status"] == "available"
    assert abs(implied["solved_value_per_share"] - implied["price"]) < 0.01

def test_bank_rejects_fcff_dcf(live):
    db, _ = live
    v = EquityResearchService(db).valuation("JPM", method="unlevered_fcff_dcf")
    assert v["status"] == "rejected_method"
    assert v["executes"] is False
    assert v["admissible_method"] == "residual_income_equity"

def test_restricted_prices_are_not_exported(live):
    db, path = live
    svc = EquityResearchService(db)
    pkg = svc.create_package("JPM")
    loaded = read_package(pkg["payload"])
    assert loaded["manifest"]["application"]["state"]["price_included"] is False
    assert "data/prices.json" not in loaded["files"]
    summary = svc.workspace("JPM")["market_price"]
    assert summary["source"]["export_allowed"] is False

def test_package_replays_from_packaged_regulatory_snapshot(live):
    db, path = live
    svc = EquityResearchService(db)
    pkg = svc.create_package("JPM")
    service = ApplicationService(db)
    installed = service.install(pkg["payload"])
    result = service.execute(installed["install_id"])
    assert result["status"] == "reproduced"
    assert result["contract_state"] == "arithmetically_verified"
