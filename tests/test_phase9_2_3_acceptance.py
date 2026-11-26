"""Phase 9.2.3 acceptance: rights classes, historical identity and provenance inspection.

Three contracts are tested here.

1. **Rights.** A copyright licence, project authorship and a public-domain dedication are
   three different things. Only an explicit dedication or an explicit grant is
   redistributable, and an unclassified grant fails closed.
2. **Historical identity.** A session enters trusted market history only when its own
   session is covered by a live assignment, or when a source-backed backfill basis names
   the permanent identifier, venue, evidence and author. Anything else is quarantined; a
   session that resolves to another security rejects the batch.
3. **Provenance.** The inspector's identity is recomputed from the stored row, revisions and
   competing providers stay visible, and a pin replays exactly one revision.
"""

from __future__ import annotations

import pytest

from atlas.entities.master import SecurityMaster
from atlas.research import observations, rights
from atlas.research.prices import (
    PriceImportError,
    import_price_series,
    price_on_or_before,
)
from atlas.storage.sources import ensure_default_sources

DAY_ONE = "2025-01-02"
DAY_TWO = "2025-01-03"


def _identity(db, *, ticker: str = "TST", mic: str = "XNYS", valid_from: str = "2020-01-01"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Test Bank", cik="1000001", sic="6021")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, mic, valid_from=valid_from, is_primary=True)
    master.assign_ticker(
        listing, ticker, valid_from=valid_from, confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return master, issuer, security, listing


def _row(close: float, *, day: str = DAY_ONE):
    return {
        "date": day, "open": close - 0.5, "high": close + 0.5,
        "low": close - 1.0, "close": close, "volume": 1000,
    }


def _import(db, *, close: float = 10.0, source: str = "Provider A",
            licence: str = "A restricted", redistribution: str = "restricted",
            rows=None, **kwargs):
    return import_price_series(
        db, ticker=kwargs.pop("ticker", "TST"),
        rows=rows if rows is not None else [_row(close)],
        source_name=source, licence=licence, redistribution=redistribution,
        adjustment_semantics="unadjusted", **kwargs,
    )


def _basis(security: str, *, venue: str = "XNYS", **overrides):
    basis = {
        "security_id": security,
        "permanent_identifier": security,
        "venue": venue,
        "evidence": "listing history record L-1",
        "established_by": "operator",
        "applies_to": "all",
    }
    basis.update(overrides)
    return basis


# --------------------------------------------------------------------- rights classes
def test_rights_classes_are_distinct_and_only_grants_export():
    public = rights.classify("public_domain", copyright_licence="CC0-1.0")
    authored = rights.classify("project_authored", copyright_licence="Apache-2.0")
    restricted = rights.classify("restricted", copyright_licence="Vendor entitlement")
    private = rights.classify("private", copyright_licence="unpublished")
    unknown = rights.classify("unknown", copyright_licence=None)

    assert public["export_allowed"] is True and public["trusted"] is True
    assert authored["export_allowed"] is True
    assert authored["redistribution"] == rights.PROJECT_AUTHORED
    assert restricted["trusted"] is True and restricted["export_allowed"] is False
    assert restricted["local_use_only"] is True
    assert private["export_allowed"] is False
    assert unknown["trusted"] is False and unknown["export_allowed"] is False
    assert len({public["label"], authored["label"], restricted["label"], unknown["label"]}) == 4


def test_permissive_copyright_is_not_promoted_to_public_domain():
    decision = rights.classify("public_domain", copyright_licence="Apache-2.0")
    assert decision["redistribution"] == rights.PROJECT_AUTHORED
    assert decision["export_allowed"] is True
    assert any("not a public-domain dedication" in item for item in decision["warnings"])


def test_project_authored_content_must_declare_its_licence():
    decision = rights.classify("project_authored", copyright_licence=None)
    assert decision["redistribution"] == rights.UNKNOWN
    assert decision["trusted"] is False


def test_unknown_rights_fail_closed_at_export():
    with pytest.raises(rights.RightsError, match="unknown or incomplete"):
        rights.require_exportable(rights.classify(None), what="test package")


def test_unknown_redistribution_cannot_be_imported(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    with pytest.raises(PriceImportError, match="fails closed"):
        _import(db, redistribution="mystery-terms")
    assert db.scalar("SELECT COUNT(*) FROM bar") == 0


# ---------------------------------------------------------------- historical identity
def test_verified_assignment_and_backfill_are_distinguished(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    imported = _import(
        db,
        rows=[_row(10.0, day=DAY_ONE)],
        backfill_basis=_basis(security, applies_to=[DAY_ONE]),
    )
    states = imported["session_identity"]["identity_states"]
    assert states["verified_assignment"] == 1
    assert states["source_backfill"] == 0
    assert imported["backfill_sessions" if False else "session_identity"]["backfill_sessions"] == []


def test_backfill_requires_identifier_venue_evidence_and_author(db):
    ensure_default_sources(db)
    master, _, security, listing = _identity(db)
    master.assign_ticker(
        listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    for broken, reason in (
        (_basis("SEC-someone-else"), "another_security"),
        (_basis(security, venue="XNAS"), "another_venue"),
        (_basis(security, permanent_identifier="TST"), "permanent_identifier"),
        (_basis(security, evidence=""), "cites_no_source_record"),
        (_basis(security, established_by=""), "accountable_author"),
        (_basis(security, applies_to=["2024-01-02"]), "does_not_cover"),
    ):
        with pytest.raises(PriceImportError, match="verified historical identity"):
            _import(
                db, rows=[_row(10.0, day="2026-06-01")], as_of="2024-12-31",
                backfill_basis=broken,
            )
        assert db.scalar("SELECT COUNT(*) FROM bar") == 0
    # The specific reason is reported, not swallowed.
    imported = _import(
        db, rows=[_row(10.0, day="2024-12-30"), _row(10.0, day="2026-06-01")],
        as_of="2024-12-31", backfill_basis=_basis(security, evidence=""),
    )
    quarantined = imported["session_identity"]["quarantined_sessions"]
    assert quarantined[0]["session"] == "2026-06-01"
    assert quarantined[0]["reason"] == "backfill_basis_cites_no_source_record"


def test_backfill_is_recorded_as_a_distinct_basis(db):
    ensure_default_sources(db)
    master, _, security, first_listing = _identity(db)
    master.assign_ticker(
        first_listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    imported = _import(
        db, rows=[_row(10.0, day="2026-06-01")], as_of="2024-12-31",
        backfill_basis=_basis(security),
    )
    record = imported["session_identity"]["backfill_sessions"][0]
    assert record["state"] == "source_backfill"
    assert record["permanent_identifier"] == security
    assert record["venue"] == "XNYS"
    assert record["evidence"] == "listing history record L-1"
    assert record["established_by"] == "operator"
    assert record["distinct_from_live_assignment"] is True


def test_ticker_reused_by_another_security_rejects_the_batch(db):
    ensure_default_sources(db)
    master, issuer, security, first_listing = _identity(db)
    master.assign_ticker(
        first_listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    stolen = master.ensure_security(issuer, class_designation="new common stock", currency="USD")
    listing = master.ensure_listing(stolen, "XNYS", valid_from="2025-01-01")
    master.assign_ticker(
        listing, "TST", valid_from="2025-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    with pytest.raises(PriceImportError, match="different security"):
        _import(
            db, rows=[_row(10.0, day="2024-12-30"), _row(10.5, day=DAY_ONE)],
            as_of="2024-12-30",
        )
    assert db.scalar("SELECT COUNT(*) FROM bar") == 0


def test_quarantine_preserves_the_operator_intent_and_exact_sessions(db):
    ensure_default_sources(db)
    master, _, security, first_listing = _identity(db)
    master.assign_ticker(
        first_listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    imported = _import(
        db, as_of="2024-12-31",
        rows=[_row(10.0, day="2024-12-30"), _row(11.0, day=DAY_ONE), _row(12.0, day="2026-06-01")],
    )
    assert imported["written"] == 1
    assert imported["quarantined"] == 2
    sessions = {item["session"] for item in imported["session_identity"]["quarantined_sessions"]}
    assert sessions == {DAY_ONE, "2026-06-01"}
    assert all(item["state"] == "ambiguous" for item in imported["session_identity"]["quarantined_sessions"])
    stored = {row["ts_utc"][:10] for row in db.query("SELECT ts_utc FROM bar")}
    assert stored == {"2024-12-30"}


# --------------------------------------------------------------------- provenance
def test_observation_detail_exposes_identity_revisions_and_conflicts(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, source="Provider A", licence="A restricted")
    _import(db, close=10.0, source="Provider A", licence="A restricted")  # identical replay
    _import(db, close=11.5, source="Provider B", licence="B restricted")  # competing provider
    listed = observations.observations_for_security(db, security)
    assert listed, "stored observations are listable"
    target = next(item for item in listed if item["source_name"] == "Provider A")
    detail = observations.observation_detail(db, target["observation_id"])
    assert detail is not None
    assert detail["identity"]["content_hash"] == target["content_hash"]
    assert detail["identity"]["recomputable"] is True
    assert detail["source"]["source_id"] == target["source_id"]
    assert detail["source"]["export_allowed"] is False
    assert detail["session"]["adjustment"] in {"raw", "unadjusted"}
    assert detail["session"]["observed_at"] and detail["session"]["ingested_at"]
    assert len(detail["revisions"]) == 1, "an identical replay is not a new revision"
    assert detail["conflict_count"] >= 1
    assert detail["providers_disagree"] is True
    assert len(detail["conflicts"]) == 1
    assert detail["conflicts"][0]["close"] == 11.5
    assert detail["pin"]["observation_id"] == target["observation_id"]
    assert "not a point-in-time vendor vintage" in detail["caveat"]


def test_observation_detail_is_none_for_an_unknown_identifier(db):
    ensure_default_sources(db)
    assert observations.observation_detail(db, "MOB-does-not-exist") is None


def test_revision_chain_grows_and_pins_stay_exact(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    first = min(
        observations.observations_for_security(db, security),
        key=lambda item: int(item["revision_seq"]),
    )
    _import(db, close=10.5)
    detail = observations.observation_detail(db, first["observation_id"])
    assert detail is not None
    assert [item["revision_seq"] for item in detail["revisions"]] == [2, 1]
    assert detail["revisions"][0]["supersedes_seq"] is not None
    assert detail["pin"]["revision_seq"] == 1
    replay = price_on_or_before(
        db, security, DAY_ONE, policy="pinned", pin=detail["pin"],
    )
    assert replay["close"] == 10.0
    assert replay["exact_replay"] is True


def test_observation_endpoints_expose_the_same_identity(tmp_path):
    from fastapi.testclient import TestClient

    from atlas.storage.db import Database
    from atlas.terminal.api import create_app

    path = tmp_path / "provenance.db"
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    db.close()

    client = TestClient(create_app(path), raise_server_exceptions=False)
    listed = client.get(f"/api/securities/{security}/observations")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items and items[0]["observation_id"].startswith("MOB-")

    detail = client.get(f"/api/market/observations/{items[0]['observation_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["identity"]["observation_id"] == items[0]["observation_id"]
    assert body["pin"]["revision_seq"] == 1
    assert body["source"]["export_allowed"] is False

    missing = client.get("/api/market/observations/MOB-missing")
    assert missing.status_code == 404
