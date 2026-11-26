"""Phase 9.1 tests: methodology eligibility, institution models and price rights.

These tests exercise the second question of equity research: not only whether a number is
reproducible, but whether the method that produced it is admissible for the business and
whether the result has actually passed the verification gates it claims.
"""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.applications.contracts import read_package
from atlas.applications.service import ApplicationService
from atlas.research import institutions
from atlas.research.eligibility import (
    ARITHMETICALLY_VERIFIED,
    DCF,
    ECONOMICALLY_REVIEWED,
    INDEPENDENTLY_BENCHMARKED,
    INSUFFICIENT_SOURCE_COVERAGE,
    JUSTIFIED_EARNINGS,
    METHODOLOGICALLY_ELIGIBLE,
    RESIDUAL_INCOME,
    UNSUPPORTED,
    build_contract,
    classify_business_model,
    missing_inputs,
)
from atlas.research.equity import EquityResearchService, _valuation_eligibility
from atlas.research.prices import (
    PriceImportError,
    import_price_series,
    price_summary,
    valuation_multiples,
)
from atlas.storage.db import Database

ROOT = Path(__file__).resolve().parents[1]
TICKERS = ["AAPL", "JPM", "GS", "UNH"]


@pytest.fixture(scope="module")
def phase9(tmp_path_factory):
    path = tmp_path_factory.mktemp("phase9-1") / "phase9.db"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_phase9_db.py"),
         "--db", str(path), "--tickers", ",".join(TICKERS)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    db = Database(path, create=False)
    yield db
    db.close()


def _metrics(*, equity=1000.0, net_income=120.0, eps=5.0, shares=100.0, diluted=105.0):
    return {
        "period_end": "2025-12-31",
        "metrics": {
            "equity": {"value": equity, "evidence_ids": ["E1"]},
            "net_income": {"value": net_income, "evidence_ids": ["E2"]},
            "net_income_common": {"value": net_income, "evidence_ids": ["E2"]},
            "eps_diluted": {"value": eps, "evidence_ids": ["E3"]},
            "shares_outstanding": {"value": shares, "evidence_ids": ["E4"]},
            "weighted_average_shares_diluted": {"value": diluted, "evidence_ids": ["E5"]},
            "roe": {"value": net_income / equity, "evidence_ids": []},
        },
    }


ISSUER = {"issuer_id": "ISS-1", "cik": "1", "legal_name": "Test Bank", "sic": "6021"}
COVERAGE = {"ticker": "TST", "ticker_identity": {"status": "verified"}, "share_basis": "period_end_share_count"}


def test_business_model_classification_is_explicit():
    assert classify_business_model("6021")["method"] == RESIDUAL_INCOME
    assert classify_business_model("6211")["method"] == RESIDUAL_INCOME
    assert classify_business_model("6324")["method"] == JUSTIFIED_EARNINGS
    assert classify_business_model("3571")["method"] == DCF
    assert classify_business_model("6500")["method"] is None
    assert classify_business_model(None)["method"] is None
    assert missing_inputs(RESIDUAL_INCOME, ["equity", "net_income"]) == ["shares_outstanding"]


def test_contract_never_promotes_execution_to_economic_support():
    eligible = build_contract(
        issuer={"sic": "3571"}, metrics={"as_of": "2026-01-01"}, coverage=COVERAGE,
        available=["revenue", "shares_outstanding", "net_income", "cash_and_equivalents"],
    )
    assert eligible["state"] == METHODOLOGICALLY_ELIGIBLE
    verified = build_contract(
        issuer={"sic": "3571"}, metrics={"as_of": "2026-01-01"}, coverage=COVERAGE,
        available=["revenue", "shares_outstanding", "net_income", "cash_and_equivalents"],
        arithmetic={"passed": True},
    )
    assert verified["state"] == ARITHMETICALLY_VERIFIED
    reviewed = build_contract(
        issuer={"sic": "3571"}, metrics={"as_of": "2026-01-01"}, coverage=COVERAGE,
        available=["revenue", "shares_outstanding", "net_income", "cash_and_equivalents"],
        arithmetic={"passed": True}, economic_review={"reviewer": "test"},
    )
    assert reviewed["state"] == ECONOMICALLY_REVIEWED
    benchmarked = build_contract(
        issuer={"sic": "3571"}, metrics={"as_of": "2026-01-01"}, coverage=COVERAGE,
        available=["revenue", "shares_outstanding", "net_income", "cash_and_equivalents"],
        arithmetic={"passed": True}, economic_review={"reviewer": "test"},
        benchmark={"reference": "test"},
    )
    assert benchmarked["state"] == INDEPENDENTLY_BENCHMARKED
    # A failed arithmetic reconstruction blocks promotion even with a review attached.
    failed = build_contract(
        issuer={"sic": "3571"}, metrics={"as_of": "2026-01-01"}, coverage=COVERAGE,
        available=["revenue", "shares_outstanding", "net_income", "cash_and_equivalents"],
        arithmetic={"passed": False}, economic_review={"reviewer": "test"},
    )
    assert failed["state"] == METHODOLOGICALLY_ELIGIBLE
    assert failed["arithmetic_status"] == "fail"


def test_contract_blocks_unsupported_models_and_missing_inputs():
    unsupported = build_contract(
        issuer={"sic": "6500"}, metrics={}, coverage=COVERAGE, available=[],
    )
    assert unsupported["state"] == UNSUPPORTED
    assert unsupported["method"] is None
    missing = build_contract(
        issuer={"sic": "3571"}, metrics={}, coverage=COVERAGE, available=["revenue"],
    )
    assert missing["state"] == INSUFFICIENT_SOURCE_COVERAGE
    assert "shares_outstanding" in " ".join(missing["missing_inputs"])


def test_bank_residual_income_matches_an_independent_decimal_reconstruction():
    result = institutions.build_bank_valuation(
        issuer=ISSUER, metrics=_metrics(), coverage=COVERAGE,
        assumptions={"cost_of_equity": 0.10, "terminal_growth": 0.0, "payout_ratio": 0.0},
    )
    assert result["status"] == "supported"
    assert result["executes"] is True
    assumptions = result["assumptions"]
    bv = Decimal("1000")
    pv = Decimal("0")
    for year in range(1, assumptions["horizon"] + 1):
        ri = (Decimal(str(assumptions["sustainable_roe"])) - Decimal("0.10")) * bv
        pv += ri / (Decimal("1.10") ** year)
        bv += Decimal(str(assumptions["sustainable_roe"])) * bv  # zero payout: book value grows by net income
    terminal = (Decimal(str(assumptions["sustainable_roe"])) - Decimal("0.10")) * bv
    terminal_pv = terminal / Decimal("0.10") / (Decimal("1.10") ** assumptions["horizon"])
    expected = (Decimal("1000") + pv + terminal_pv) / Decimal("100")
    assert abs(float(expected) - result["outputs"]["value_per_share"]) < 1e-9
    assert result["contract"]["state"] == ARITHMETICALLY_VERIFIED


def test_negative_residual_equity_is_preserved_and_not_a_tradable_price():
    result = institutions.build_bank_valuation(
        issuer=ISSUER, metrics=_metrics(equity=100.0, net_income=-50.0),
        coverage=COVERAGE,
    )
    assert result["outputs"]["negative_residual_equity"] is True
    assert result["outputs"]["calculated_equity_value"] < 0
    assert result["outputs"]["value_per_share"] < 0
    assert result["outputs"]["realizable_common_price"] is None
    assert any(f["code"] == "negative_residual_equity" for f in result["findings"])


def test_insurer_is_partial_and_does_not_invent_medical_loss_ratio():
    result = institutions.build_insurer_valuation(
        issuer={"sic": "6324", "legal_name": "Test Insurer"}, metrics=_metrics(),
        coverage=COVERAGE,
    )
    assert result["method"] == JUSTIFIED_EARNINGS
    assert result["partial"] is True
    assert result["health_insurance"]["medical_loss_ratio"] is None
    assert result["health_insurance"]["status"] == "not_available_in_fixture"
    assert result["contract"]["state"] == ARITHMETICALLY_VERIFIED
    assert result["outputs"]["value_per_share"] == pytest.approx(result["outputs"]["eps_diluted"] * result["outputs"]["justified_pe"])


def test_share_basis_sensitivity_reports_both_denominators():
    result = institutions.build_bank_valuation(
        issuer=ISSUER, metrics=_metrics(), coverage=COVERAGE,
    )
    bases = {row["basis"] for row in result["sensitivity"]["share_basis"]}
    assert bases == {"period_end_share_count", "weighted_average_diluted"}


def test_jpm_and_gs_use_residual_income_and_unh_uses_justified_earnings(phase9):
    service = EquityResearchService(phase9)
    bank = service.valuation("JPM")
    assert bank["eligibility"]["rejected_method"] == DCF
    assert bank["method"] == RESIDUAL_INCOME
    assert bank["dcf"] is None and bank["institution"] is not None
    assert bank["contract"]["state"] == ARITHMETICALLY_VERIFIED
    assert bank["economically_supported"] is False
    assert service.valuation("GS")["method"] == RESIDUAL_INCOME

    insurer = service.valuation("UNH")
    assert insurer["method"] == JUSTIFIED_EARNINGS
    assert insurer["institution"]["partial"] is True
    assert insurer["contract"]["state"] == ARITHMETICALLY_VERIFIED

    industrial = service.valuation("AAPL")
    assert industrial["method"] == DCF
    assert industrial["dcf"] is not None


def test_price_import_requires_rights_and_produces_multiples(phase9):
    service = EquityResearchService(phase9)
    workspace = service.workspace("AAPL")
    metrics = workspace["metrics"]
    ticker = workspace["coverage"]["ticker"]
    rows = [
        {"date": "2025-01-02", "close": 200.0},
        {"date": "2025-01-03", "close": 210.0},
    ]
    from atlas.entities.master import SecurityMaster

    master = SecurityMaster(phase9)
    security_id = master.resolve_ticker(ticker).candidates[0].security_id
    mic = str(master.listings(security_id)[0]["mic"])
    imported = import_price_series(
        phase9, ticker=ticker, rows=rows, source_name="Test feed",
        licence="test-only", redistribution="user_responsibility",
        adjustment_semantics="unadjusted", security_id=security_id, mic=mic,
        backfill_basis={
            "security_id": security_id,
            "permanent_identifier": security_id,
            "venue": mic,
            "evidence": "tests/test_phase9_1_models.py fixture series",
            "established_by": "Atlas test suite",
            "applies_to": "all",
        },
    )
    assert imported["written"] == 2
    assert imported["source"]["export_allowed"] is False
    summary = price_summary(phase9, imported["security_id"])
    assert summary["status"] == "available"
    assert summary["latest_close"] == 210.0
    multiples = valuation_multiples(metrics, 210.0)
    assert multiples["status"] == "available"
    assert multiples["pe"] is not None

    with pytest.raises(PriceImportError):
        import_price_series(
            phase9, ticker=ticker, rows=rows, source_name="x", licence="x",
            redistribution="all_rights_reserved", adjustment_semantics="unadjusted",
        )


def test_absent_price_is_declared_not_invented(phase9):
    summary = EquityResearchService(phase9).workspace("JPM")["market_price"]
    assert summary["status"] in {"available", "unavailable"}
    if summary["status"] == "unavailable":
        assert summary["observations"] == 0
        assert "does not bundle" in summary["detail"]
    assert valuation_multiples({"metrics": {}}, None)["status"] == "unavailable"


def test_institution_package_is_deterministic_and_replays_from_a_clean_database(phase9):
    service = EquityResearchService(phase9)
    first = service.create_package("JPM")
    second = service.create_package("JPM")
    assert first["package_sha256"] == second["package_sha256"]
    assert first["report"] == second["report"]
    package = read_package(first["payload"])
    assert package["manifest"]["application"]["runtime"]["kind"] == "report_bundle"

    apps = ApplicationService(phase9)
    installed = apps.install(first["payload"])
    assert installed["status"] == "installed"
    execution = apps.execute(installed["install_id"])
    assert execution["status"] == "reproduced"
    assert execution["reproduced"] is True
    assert execution["differences"] == {}
    assert execution["contract_state"] == ARITHMETICALLY_VERIFIED


def test_eligibility_status_remains_separate_from_arithmetic_success(phase9):
    eligibility = _valuation_eligibility(
        {"sic": "6021"}, [], available=["equity", "net_income", "shares_outstanding"]
    )
    assert eligibility["status"] == "unsupported_methodology"
    assert eligibility["method"] == RESIDUAL_INCOME
    valuation = EquityResearchService(phase9).valuation("JPM")
    assert valuation["status"] == "supported"
    assert valuation["eligibility"]["status"] == "unsupported_methodology"
    assert valuation["economically_supported"] is False
