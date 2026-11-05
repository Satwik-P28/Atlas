"""Phase 9 adversarial tests for integrated equity research.

The tests build a real subset database from the archived SEC payloads rather than
hand-writing facts, so a regression in ingestion, tag migration, fiscal-period filtering
or the DCF audit is observable end to end. Synthetic databases are used only where a
specific adversarial shape cannot be produced from the real archive.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.applications.contracts import read_package
from atlas.applications.service import ApplicationService
from atlas.core.errors import ValidationError
from atlas.core.temporal import ReportingPeriod, availability_from_instant
from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.evidence.model import EvidenceRecord
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.metric_store import get_issuer_metrics

ROOT = Path(__file__).resolve().parents[1]
TICKERS = ["AAPL", "GOOGL", "AMZN", "JPM", "GS"]
PHASE9_DB_PATH: Path | None = None


@pytest.fixture(scope="module")
def phase9(tmp_path_factory):
    global PHASE9_DB_PATH
    root = tmp_path_factory.mktemp("phase9-equity")
    path = root / "phase9.db"
    PHASE9_DB_PATH = path
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_phase9_db.py"),
            "--db", str(path),
            "--tickers", ",".join(TICKERS),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    db = Database(path, create=False)
    yield db
    db.close()


def _service(phase9) -> EquityResearchService:
    return EquityResearchService(phase9)


def test_coverage_and_valuation_are_reported_separately(phase9):
    coverage = _service(phase9).coverage()
    readiness = {item["ticker"]: item for item in coverage["readiness"]["items"]}
    assert coverage["issuers"] == len(TICKERS)
    # Financial coverage requires the reported statement set, including liabilities.
    # AMZN never tags us-gaap:Liabilities in the archived companyfacts payload. JPM and
    # GS report liabilities but are financial institutions, so they are valid coverage
    # and invalid valuation subjects at the same time.
    assert coverage["financial_coverage_valid"] == 3
    # Valuation eligibility is narrower and does not consume total liabilities.
    assert readiness["AMZN"]["eligibility"] == "eligible"
    assert readiness["AMZN"]["financial_coverage_valid"] is False
    assert readiness["JPM"]["eligibility"] == "unsupported_methodology"
    assert readiness["GS"]["eligibility"] == "unsupported_methodology"
    assert readiness["GS"]["financial_institution"] is True
    assert coverage["valuation_executes"] == 3
    assert coverage["valuation_economically_supported"] == 3
    assert coverage["methodology_rejected"] == 2
    assert coverage["with_prices"] == 0


def test_financial_institution_is_refused_a_generic_dcf_and_package(phase9):
    service = _service(phase9)
    analysis = service.analyse("JPM")
    assert analysis["valuation"]["status"] == "unsupported_methodology"
    assert analysis["valuation"]["executes"] is False
    assert analysis["valuation"]["dcf"] is None
    assert "financial institution" in analysis["valuation"]["eligibility"]["reasons"][0].lower()
    assert "residual income" in " ".join(analysis["valuation"]["eligibility"]["reasons"])
    assert analysis["metadata"]["valuation_executes"] is False
    with pytest.raises(ValidationError):
        service.create_package("JPM")
    report = analysis["report"]
    assert "DCF rejected for this issuer type" in report
    assert "does not tune assumptions" in report


def test_missing_valuation_inputs_are_declared_not_invented():
    from atlas.research.equity import _valuation_eligibility

    eligibility = _valuation_eligibility({"sic": "3571"}, ["revenue", "shares_outstanding"])
    assert eligibility["status"] == "insufficient_data"
    assert "revenue" in eligibility["reasons"][0]
    assert eligibility["required_remedy"] == "additional reported facts before valuation"

    institution = _valuation_eligibility({"sic": "6021"}, [])
    assert institution["status"] == "unsupported_methodology"
    assert "residual income" in institution["required_remedy"]


def test_every_dcf_component_is_independently_recomputed(phase9):
    analysis = _service(phase9).analyse("AAPL")
    audit = analysis["valuation"]["audit"]
    assert audit["arithmetic_valid"] is True
    assert audit["component_count"] == 8
    assert {check["name"] for check in audit["checks"]} == {
        "Revenue forecast path", "FCFF path", "PV of explicit forecast", "Terminal value",
        "PV of terminal value", "Enterprise value", "Equity value bridge", "Value per share",
    }
    assert all(check["status"] == "pass" for check in audit["checks"])
    assert audit["verdict"] in {"supported", "supported_with_findings"}
    assert audit["economically_supported"] is audit["arithmetic_valid"]
    assert audit["share_denominator"]["basis"] == "period_end_share_count"
    assert "option dilution" in audit["share_denominator"]["limitation"]


def test_share_denominator_fallbacks_are_labelled_and_limited(phase9):
    service = _service(phase9)
    weighted = service._share_denominator(
        {"shares": 1_000.0, "provenance": {"shares_outstanding": {
            "basis": "weighted_average_diluted", "evidence_ids": ["EVD-1"]}}},
        {"metrics": {"weighted_average_shares_diluted": {"value": 1_000.0}}},
    )
    assert weighted["basis"] == "weighted_average_diluted"
    assert weighted["period_end_count"] is None
    assert "weighted diluted average" in weighted["limitation"]

    derived = service._share_denominator(
        {"shares": 500.0, "provenance": {"shares_outstanding": {
            "basis": "derived_net_income_over_eps", "evidence_ids": ["EVD-2"]}}},
        {"metrics": {}},
    )
    assert derived["basis"] == "derived_net_income_over_eps"
    assert "estimate, not a reported count" in derived["limitation"]


def test_negative_dcf_value_is_preserved_without_tuning(phase9):
    analysis = _service(phase9).analyse("AMZN")
    valuation = analysis["valuation"]
    assert valuation["status"] == "supported"
    assert valuation["dcf"]["outputs"]["value_per_share"] < 0
    assert valuation["audit"]["arithmetic_valid"] is True
    assert valuation["economically_supported"] is True
    codes = {finding["code"] for finding in valuation["findings"]}
    assert "negative_equity_value" in codes
    assert "negative_fcff" in codes
    # The audit reports the finding; it does not change the recorded assumptions.
    for key in ("operating_margin", "capex_pct_revenue", "revenue_growth", "wacc"):
        assert valuation["dcf"]["assumptions"][key] == valuation["defaults"][key]
    assert "-" in analysis["report"]


def test_revenue_tag_migration_resolves_per_period(phase9):
    issuer = phase9.query_one("SELECT * FROM issuer WHERE cik='0001652044'")
    tags = {
        row["source_concept"]
        for row in phase9.query(
            "SELECT DISTINCT source_concept FROM evidence WHERE entity_id=? AND concept='revenue'",
            (issuer["issuer_id"],),
        )
    }
    assert len(tags) >= 2, tags
    metrics = get_issuer_metrics(phase9, issuer["issuer_id"])
    assert metrics["period_end"] == "2025-12-31"
    revenue = metrics["metrics"]["revenue"]["value"]
    assert abs(revenue - 402_836_000_000) < 1_000_000
    fact = phase9.query_one(
        "SELECT source_concept FROM evidence WHERE evidence_id=?",
        (metrics["metrics"]["revenue"]["evidence_ids"][0],),
    )
    assert fact["source_concept"].endswith("Revenues")
    older = phase9.query_one(
        "SELECT source_concept FROM evidence WHERE entity_id=? AND concept='revenue' "
        "AND period_end='2021-12-31' ORDER BY availability_time DESC LIMIT 1",
        (issuer["issuer_id"],),
    )
    assert older["source_concept"] != fact["source_concept"]


def test_amendments_and_overlapping_facts_resolve_to_latest_filing(phase9):
    issuer = phase9.query_one("SELECT * FROM issuer WHERE cik='0000320193'")
    overlaps = phase9.query(
        "SELECT concept, period_end, COUNT(*) AS n FROM evidence WHERE entity_id=? "
        "AND period_type='duration' GROUP BY concept, period_end HAVING n > 1 "
        "ORDER BY n DESC LIMIT 1",
        (issuer["issuer_id"],),
    )
    assert overlaps, "the real archive should contain overlapping facts"
    row = overlaps[0]
    selected = phase9.query_one(
        "SELECT evidence_id, availability_time FROM evidence WHERE entity_id=? AND concept=? "
        "AND period_end=? ORDER BY availability_time DESC, evidence_id DESC LIMIT 1",
        (issuer["issuer_id"], row["concept"], row["period_end"]),
    )
    metrics = get_issuer_metrics(phase9, issuer["issuer_id"])
    if row["period_end"] == metrics["period_end"] and row["concept"] in metrics["metrics"]:
        chosen = metrics["metrics"][row["concept"]]["evidence_ids"][0]
        assert chosen == selected["evidence_id"]


def test_selected_annual_facts_are_330_to_400_day_durations(phase9):
    # The archive deliberately keeps every FY-tagged observation, including transition
    # periods. What must be annual is the fact the metric and history selectors choose.
    for cik in ("0000320193", "0001652044", "0001018724"):
        issuer = phase9.query_one("SELECT * FROM issuer WHERE cik=?", (cik,))
        metrics = get_issuer_metrics(phase9, issuer["issuer_id"])
        row = phase9.query_one(
            "SELECT period_start, period_end, julianday(period_end) - julianday(period_start) AS days "
            "FROM evidence WHERE evidence_id=?",
            (metrics["metrics"]["revenue"]["evidence_ids"][0],),
        )
        assert 330 <= row["days"] <= 400
        history = _service(phase9).workspace(cik)["history"]
        for concept in history["concepts"]:
            for point in concept["points"]:
                days = phase9.scalar(
                    "SELECT julianday(period_end) - julianday(period_start) FROM evidence "
                    "WHERE evidence_id=?", (point["evidence_id"],), default=None,
                )
                assert days is None or 330 <= days <= 400


def test_fiscal_period_filter_ignores_non_annual_fy_duration(db):
    master = SecurityMaster(db)
    issuer = master.register_issuer(legal_name="Transition Co", cik="0000000999", source_id="sec-edgar")
    kernel = EvidenceKernel(db)
    for concept, value, start, end, available in (
        ("revenue", "100", date(2023, 9, 30), date(2024, 9, 28), "2024-11-01T16:00:00Z"),
        # A six-month transition period tagged as FY must not become the annual reference.
        ("revenue", "60", date(2024, 9, 29), date(2025, 3, 29), "2025-05-01T16:00:00Z"),
    ):
        kernel.ingest(
            EvidenceRecord.build(
                entity_id=issuer,
                entity_kind="issuer",
                concept=concept,
                source_id="sec-edgar",
                unit="USD",
                availability=availability_from_instant(available, "test.acceptance"),
                period=ReportingPeriod(
                    end=end, start=start, fiscal_year=end.year, fiscal_period="FY"
                ),
                value=Decimal(value),
                accession_number=f"A-{end.year}",
                form_type="10-K",
                filed_date=available[:10],
                observed_at=available,
                quality="verified",
                verification="source_primary",
                source_dataset="sec_companyfacts",
                taxonomy="us-gaap",
                source_concept="us-gaap:Revenues",
            )
        )
    metrics = get_issuer_metrics(db, issuer)
    assert metrics["period_end"] == "2024-09-28"
    assert metrics["metrics"]["revenue"]["value"] == 100.0


def test_historical_cutoff_excludes_later_annual_filings(phase9):
    issuer = phase9.query_one("SELECT * FROM issuer WHERE cik='0000320193'")
    latest = get_issuer_metrics(phase9, issuer["issuer_id"])
    historical = get_issuer_metrics(
        phase9, issuer["issuer_id"], as_of="2020-01-01T00:00:00Z", mode="public_available"
    )
    assert historical["period_end"] < latest["period_end"]
    analysis = _service(phase9).analyse("AAPL", as_of="2020-01-01T00:00:00Z")
    assert analysis["workspace"]["metrics"]["period_end"] < latest["period_end"]


def test_absent_market_prices_never_become_a_zero(phase9):
    issuer = phase9.query_one("SELECT * FROM issuer WHERE cik='0000320193'")
    metrics = get_issuer_metrics(phase9, issuer["issuer_id"])
    assert metrics.get("price") is None
    assert "market_cap" not in metrics["metrics"]
    analysis = _service(phase9).analyse("AAPL")
    assert analysis["valuation"]["dcf"]["data_status"]["price"] is None
    assert analysis["valuation"]["dcf"]["data_status"]["price_source"] is None
    assert "not bundled" in analysis["report"]


def test_report_is_source_linked_and_contains_the_audit(phase9):
    analysis = _service(phase9).analyse("AAPL")
    report = analysis["report"]
    assert "## Valuation methodology and eligibility" in report
    assert "### Independent component audit" in report
    assert "### Share denominator" in report
    assert "## Findings and audit verdict" in report
    assert "report SHA-256 is recorded" in report
    assert "no LLM generated any factual claim" in report
    assert analysis["metadata"]["dcf_audit_verdict"] in {"supported", "supported_with_findings"}
    assert analysis["metadata"]["report_sha256"] == hashlib.sha256(report.encode()).hexdigest()


def test_package_is_deterministic_and_reproduces_from_a_clean_database(phase9, tmp_path):
    service = _service(phase9)
    first = service.create_package("AAPL")
    second = service.create_package("AAPL")
    assert first["package_sha256"] == second["package_sha256"]
    loaded = read_package(first["payload"])
    files = loaded["files"]
    assert not any(name.endswith((".py", ".js", ".sh", ".exe")) for name in files)
    assert "artifacts/dcf_audit.json" in files
    assert json.loads(files["artifacts/dcf_audit.json"])["arithmetic_valid"] is True
    assert hashlib.sha256(files["report.md"]).hexdigest() == first["report_sha256"]

    clean = Database(tmp_path / "clean.db")
    clean.migrate()
    ensure_default_sources(clean)
    try:
        installed = ApplicationService(clean).install(first["payload"])
        execution = ApplicationService(clean).execute(installed["install_id"])
    finally:
        clean.close()
    assert execution["status"] == "reproduced"
    for key, value in first["expected_outputs"].items():
        assert abs(float(execution["outputs"][key]) - float(value)) <= 1e-9


def test_workspace_reconciles_and_exposes_evidence(phase9):
    workspace = _service(phase9).workspace("AAPL")
    assert workspace["coverage"]["financial_coverage_valid"] is True
    assert workspace["quality_checks"]
    assert workspace["provenance"]["evidence_details"]
    assert workspace["history"]["periods"]
    assert all(
        point["evidence_id"]
        for row in workspace["history"]["concepts"]
        for point in row["points"]
    )


def test_api_exposes_coverage_report_and_package(phase9):
    from fastapi.testclient import TestClient

    from atlas.terminal.api import create_app

    client = TestClient(create_app(PHASE9_DB_PATH))
    coverage = client.get("/api/equity/coverage")
    assert coverage.status_code == 200
    payload = coverage.json()
    assert payload["issuers"] == len(TICKERS)
    assert payload["valuation_executes"] == 3

    workspace = client.get("/api/equity/AAPL/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["company"]["cik"] == "0000320193"

    report = client.post("/api/equity/AAPL/report", json={"assumptions": {}})
    assert report.status_code == 200
    body = report.json()
    assert body["valuation"]["audit"]["arithmetic_valid"] is True
    assert "### Independent component audit" in body["report"]

    package = client.post("/api/equity/AAPL/package", json={})
    assert package.status_code == 200
    assert package.json()["package_base64"]
    download = client.get("/api/equity/AAPL/package.atlas")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"

    rejected = client.post("/api/equity/JPM/package", json={})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"]

    readiness = client.get("/api/equity/JPM/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["items"][0]["eligibility"] == "unsupported_methodology"
