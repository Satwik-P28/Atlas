"""Phase 9.2 tests: regulatory entities, bank v2, market rights and method rejection."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
from atlas.applications.contracts import read_package
from atlas.applications.service import ApplicationService
from atlas.research import institutions, regulatory
from atlas.research.equity import EquityResearchService
from atlas.research.prices import (
    SOURCE_SELECTION_POLICY,
    import_price_series,
    price_on_or_before,
)
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


def test_bank_common_equity_is_total_less_sec_preferred(live):
    db, _ = live
    svc = EquityResearchService(db)
    jpm = svc.valuation("JPM", as_of="2025-06-30")["institution"]
    gs = svc.valuation("GS", as_of="2025-06-30")["institution"]
    assert jpm["inputs"]["preferred_stock"] == 20_050_000_000
    assert jpm["outputs"]["book_value_common_equity"] == 324_708_000_000
    assert gs["inputs"]["preferred_stock"] == 13_253_000_000
    assert gs["outputs"]["book_value_common_equity"] == 108_743_000_000
    assert jpm["outputs"]["book_value_basis"] == "sec_total_stockholders_equity_less_preferred_stock"
    assert jpm["outputs"]["common_equity_status"] == "derived_total_equity_less_preferred_stock"
    assert jpm["outputs"]["book_value_per_common_share"] == pytest.approx(324_708_000_000 / 2_797_600_000)
    assert jpm["outputs"]["ending_equity_roe_proxy"] == pytest.approx(56_868_000_000 / 324_708_000_000)
    assert jpm["outputs"]["average_common_roe"] == pytest.approx(
        56_868_000_000 / ((324_708_000_000 + 300_474_000_000) / 2)
    )
    assert jpm["outputs"]["roe_used"] == jpm["outputs"]["average_common_roe"]
    assert jpm["outputs"]["roe_basis"] == "average_common_equity"
    assert jpm["outputs"]["company_reported_roe"] is None

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


def test_market_comparison_never_uses_a_price_after_the_cutoff(live):
    db, _ = live
    svc = EquityResearchService(db)
    historical = svc.analyse("JPM", as_of="2025-06-30T00:00:00Z")
    assert historical["valuation"]["market"]["status"] == "unavailable"
    assert historical["valuation"]["institution"]["implied"] is None
    later = svc.analyse("JPM", as_of="2026-01-15T00:00:00Z")
    market = later["valuation"]["market"]
    assert market["status"] == "available"
    assert market["price_date"] == "2025-12-31"
    assert market["price_date"] <= market["information_cutoff"]
    assert market["lookahead_safe"] is True
    assert market["filing_available_at"] is None or market["filing_available_at"][:10] <= market["information_cutoff"]


def test_market_analysis_rejects_a_future_price():
    from atlas.research.prices import market_analysis
    out = market_analysis(
        price={"date": "2026-11-05", "close": 100, "currency": "USD",
               "adjustment_semantics": "unadjusted", "source_id": "x", "observed_at": "2026-11-05"},
        history=None, value_per_share=110, accounting_period_end="2025-12-31",
        information_cutoff="2025-06-30",
    )
    assert out["status"] == "rejected_lookahead"


def test_restricted_price_is_not_in_report_or_package(live):
    db, _ = live
    svc = EquityResearchService(db)
    analysis = svc.analyse("JPM")
    assert "322.22" not in analysis["report"]
    assert "withheld" in analysis["report"]
    pkg = svc.create_package("JPM")
    loaded = read_package(pkg["payload"])
    assert "322.22" not in loaded["files"]["report.md"].decode()
    assert all("price" not in name for name in loaded["files"])
    series = db.query("SELECT * FROM market_price_series")
    assert series and all(row["automated_access_authorized"] == 0 for row in series)


def test_implied_cost_reports_convergence_and_unique_root(live):
    db, _ = live
    implied = EquityResearchService(db).valuation("JPM")["institution"]["implied"]
    assert implied["status"] == "available"
    assert implied["converged"] is True
    assert implied["unique_root"] is True
    assert implied["residual_usd"] <= 0.01
    assert implied["iterations"] <= 100
    assert implied["scan_root_intervals"] == 1


def test_parent_capital_gate_is_blocked_without_fr_y9c(live):
    db, _ = live
    model = EquityResearchService(db).valuation("JPM")["institution"]
    gate = model["parent_capital"]
    assert gate["status"] == "blocked_fr_y9c_unavailable"
    assert gate["subsidiary_evidence_used_for_parent"] is False


def test_price_history_is_truncated_at_cutoff(live):
    from atlas.research.prices import price_history
    db, _ = live
    security_id = db.scalar("SELECT security_id FROM market_price_series LIMIT 1")
    full = price_history(db, security_id)
    cut = price_history(db, security_id, end_date="2026-01-01")
    assert full["last_date"] == "2026-11-05"
    assert cut["last_date"] == "2025-12-31"
    assert all(point["date"] <= "2026-01-01" for point in cut.get("points", []))


def test_assumption_changes_recompute_value(live):
    db, _ = live
    svc = EquityResearchService(db)
    base = svc.valuation("JPM")["institution"]["outputs"]["value_per_share"]
    changed = svc.valuation("JPM", assumptions={"cost_of_equity": 0.13})["institution"]["outputs"]["value_per_share"]
    assert changed < base


def test_bank_regulatory_stress_is_gaap_not_tier_1_leverage(live):
    db, _ = live
    model = EquityResearchService(db).valuation("JPM")["institution"]
    stress = model["scenarios"]["regulatory_stress"]
    assert stress
    first = stress[0]
    assert first["gaap_equity_to_assets_after_percent"] > 4
    assert first["regulatory_leverage_after_percent"] is None
    assert first["regulatory_leverage_status"] == "regulatory_leverage_not_verified"
    assert "passes_minimum" not in first
    assert "tier_1_leverage_after_percent" not in first
    assert model["scenarios"]["regulatory_leverage"]["scenario_metric"] == "gaap_equity_to_assets"
    assert any(f["code"] == "regulatory_leverage_not_verified" for f in model["findings"])


def test_bank_growth_is_implied_by_clean_surplus_not_a_free_assumption(live):
    db, _ = live
    svc = EquityResearchService(db)
    base = svc.valuation("JPM")["institution"]
    supplied = svc.valuation("JPM", assumptions={"growth": 0.25})["institution"]
    assert base["assumptions"]["growth_is_free_parameter"] is False
    assert base["assumptions"]["growth_basis"] == "implied_clean_surplus_retention"
    assert base["assumptions"]["implied_growth"] == pytest.approx(
        base["assumptions"]["sustainable_roe"] * (1 - base["assumptions"]["payout_ratio"])
    )
    assert supplied["outputs"]["value_per_share"] == pytest.approx(
        base["outputs"]["value_per_share"]
    )
    assert supplied["assumptions"]["rejected_assumptions"][0]["field"] == "growth"
    assert any(f["code"] == "growth_is_not_a_free_parameter" for f in supplied["findings"])
    assert supplied["assumptions"]["terminal_payout_ratio"] == pytest.approx(
        1 - supplied["assumptions"]["terminal_growth"]
        / supplied["assumptions"]["sustainable_roe"]
    )


def test_invalid_terminal_growth_refuses_a_finite_value(live):
    db, _ = live
    model = EquityResearchService(db).valuation(
        "JPM", assumptions={"cost_of_equity": 0.10, "terminal_growth": 0.10}
    )["institution"]
    assert model["outputs"]["calculated_equity_value"] is None
    assert model["outputs"]["value_per_share"] is None
    assert any(f["code"] == "terminal_growth_exceeds_cost_of_equity" for f in model["findings"])


def test_saved_package_records_the_selected_market_source(live):
    db, _ = live
    svc = EquityResearchService(db)
    package = svc.create_package("JPM", as_of="2026-01-15")
    state = package["manifest"]["application"]["state"]
    selection = state["market_price_selection"]
    assert selection["selected_source_id"]
    assert selection["price_date"] == "2025-12-31"
    assert selection["policy"] == SOURCE_SELECTION_POLICY
    assert state["price_included"] is False
