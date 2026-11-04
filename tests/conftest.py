"""Shared fixtures.

The suite is fully offline. Real SEC payloads are archived under ``fixtures/``; the
rest is deterministic synthetic data labelled as such.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from atlas.core.temporal import (  # noqa: E402
    ReportingPeriod,
    availability_from_instant,
)
from atlas.entities.master import SecurityMaster  # noqa: E402
from atlas.evidence.kernel import EvidenceKernel  # noqa: E402
from atlas.evidence.model import EvidenceRecord  # noqa: E402
from atlas.market.calendar import TradingCalendar  # noqa: E402
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402

FIXTURES = ROOT / "fixtures"
SEC_FIXTURES = FIXTURES / "sec"
RESTATEMENT_FIXTURES = FIXTURES / "sec_restatement"
MARKET_FIXTURES = FIXTURES / "market"

APPLE_CIK = "0000320193"
RESTATEMENT_CIK = "0001999999"


@pytest.fixture()
def db():
    database = Database(":memory:")
    database.migrate()
    ensure_default_sources(database)
    yield database
    database.close()


@pytest.fixture()
def file_db(tmp_path):
    database = Database(tmp_path / "atlas-test.db")
    database.migrate()
    ensure_default_sources(database)
    yield database
    database.close()


@pytest.fixture()
def master(db):
    return SecurityMaster(db)


@pytest.fixture()
def kernel(db):
    return EvidenceKernel(db)


@pytest.fixture()
def calendar(db):
    return TradingCalendar(db)


@pytest.fixture()
def apple_issuer(master):
    return master.register_issuer(
        legal_name="Apple Inc.", cik=APPLE_CIK, entity_type="corporation", sic="3571",
        fiscal_year_end="0928", source_id="sec-edgar",
    )


@pytest.fixture()
def apple_security(master, apple_issuer):
    master.ensure_venue("XNAS", "Nasdaq Global Select Market", country="US", timezone="America/New_York")
    security = master.ensure_security(apple_issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="1980-12-12", is_primary=True)
    master.assign_ticker(
        listing, "AAPL", valid_from="1980-12-12", confidence=1.0, status="confirmed", source_id="sec-edgar"
    )
    return security


@pytest.fixture()
def make_fact():
    """Build a valid evidence record with sensible overrides."""

    def _make(**overrides):
        params = {
            "entity_id": "ISS-CIK0000320193",
            "entity_kind": "issuer",
            "concept": "revenue",
            "source_id": "sec-edgar",
            "unit": "USD",
            "availability": availability_from_instant("2024-05-01T16:05:12Z", "test.acceptance"),
            "period": ReportingPeriod(
                end=date(2024, 3, 31), start=date(2024, 1, 1), fiscal_year=2024, fiscal_period="Q1"
            ),
            "value": Decimal("100000000"),
            "accession_number": "0001999999-24-000004",
            "form_type": "10-Q",
            "filed_date": "2024-05-01",
            "observed_at": "2024-09-01T12:00:00Z",
            "quality": "verified",
            "verification": "source_primary",
            "source_dataset": "sec_companyfacts",
            "taxonomy": "us-gaap",
            "source_concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
        }
        params.update(overrides)
        return EvidenceRecord.build(**params)

    return _make
