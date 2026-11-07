"""Phase 9.2.2 observation identity, revision pinning, session identity and selection.

The contract under test: a saved research object records the exact observation revision it
used. Importing a later correction must not silently change that replay, the alternatives
must remain inspectable, and moving to the newer revision must be an explicit act.

A second contract: a multi-session import must not distribute its rows across guessed
securities. Each session has to resolve to the same security and venue the batch declared.
"""

from __future__ import annotations

import time

import pytest

from atlas.entities.master import SecurityMaster
from atlas.research import observations
from atlas.research.objects import ResearchObjectStore
from atlas.research.prices import (
    SOURCE_SELECTION_POLICY,
    PriceImportError,
    import_price_series,
    price_for_pin,
    price_on_or_before,
    price_summary,
)
from atlas.storage.sources import ensure_default_sources

DAY_ONE = "2025-01-02"
DAY_TWO = "2025-01-03"


def _identity(db, *, ticker: str = "TST", mic: str = "XNYS"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Test Bank", cik="1000001", sic="6021")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, mic, valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(
        listing, ticker, valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return master, issuer, security, listing


def _row(close: float, *, day: str = DAY_ONE):
    return {
        "date": day, "open": close - 0.5, "high": close + 0.5,
        "low": close - 1.0, "close": close, "volume": 1000,
    }


def _import(db, *, close: float, source: str = "Provider A", licence: str = "A restricted",
            rows=None, **kwargs):
    return import_price_series(
        db, ticker=kwargs.pop("ticker", "TST"),
        rows=rows if rows is not None else [_row(close)],
        source_name=source, licence=licence, redistribution="restricted",
        adjustment_semantics="unadjusted", **kwargs,
    )


# --------------------------------------------------------------- observation identity
def test_observation_identity_covers_security_session_source_and_revision(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    first = _import(db, close=10.0)
    selected = price_on_or_before(db, security, DAY_ONE)
    observation = selected["observation"]
    assert observation["schema"] == observations.OBSERVATION_SCHEMA
    assert observation["security_id"] == security
    assert observation["session_date"] == DAY_ONE
    assert observation["source_id"] == first["source"]["source_id"]
    assert observation["revision_seq"] == 1
    assert observation["observation_id"].startswith("MOB-")
    assert len(observation["content_hash"]) == 64
    # The same stored row always recomputes the same identity.
    assert selected["pin"]["observation_id"] == observation["observation_id"]


def test_pin_keeps_revision_one_when_a_correction_is_imported(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    original = price_on_or_before(db, security, DAY_ONE)
    pin_one = original["pin"]
    assert original["close"] == 10.0 and original["revision_seq"] == 1

    _import(db, close=11.0)  # provider correction for the same session
    latest = price_on_or_before(db, security, DAY_ONE)
    assert latest["close"] == 11.0 and latest["revision_seq"] == 2
    assert latest["observation_id"] != pin_one["observation_id"]

    replay = price_for_pin(db, pin_one)
    assert replay["status"] == "exact"
    assert replay["exact_replay"] is True
    assert replay["price"]["close"] == 10.0
    assert replay["price"]["revision_seq"] == 1
    assert replay["observation"]["observation_id"] == pin_one["observation_id"]

    # Opting in to the newer revision is explicit and yields a different result.
    newer = price_for_pin(db, latest["pin"])
    assert newer["exact_replay"] is True
    assert newer["price"]["close"] == 11.0
    # Both observations survive; nothing was rewritten.
    assert db.scalar("SELECT COUNT(*) FROM bar") == 2


def test_unresolvable_pin_reports_unavailability_instead_of_latest_price(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    pin = price_on_or_before(db, security, DAY_ONE)["pin"]
    missing = dict(pin, revision_seq=99)
    replay = price_for_pin(db, missing)
    assert replay["status"] == "exact_revision_unavailable"
    assert replay["exact_replay"] is False
    assert replay["price"] is None
    assert "substitute" in replay["reason"]


def test_pin_with_a_corrupted_content_hash_is_refused(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    pin = price_on_or_before(db, security, DAY_ONE)["pin"]
    tampered = dict(pin, content_hash="0" * 64)
    replay = price_for_pin(db, tampered)
    assert replay["status"] == "exact_revision_content_mismatch"
    assert replay["price"] is None


def test_competing_providers_keep_independent_pins(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    provider_a = _import(db, close=10.0, source="Provider A", licence="A restricted")
    provider_b = _import(db, close=20.0, source="Provider B", licence="B restricted")
    a_pin = price_on_or_before(db, security, DAY_ONE, source_id=provider_a["source"]["source_id"])["pin"]
    b_pin = price_on_or_before(db, security, DAY_ONE, source_id=provider_b["source"]["source_id"])["pin"]
    assert a_pin["observation_id"] != b_pin["observation_id"]
    assert price_for_pin(db, a_pin)["price"]["close"] == 10.0
    assert price_for_pin(db, b_pin)["price"]["close"] == 20.0


def test_pinned_selection_refuses_another_security(db):
    ensure_default_sources(db)
    master, issuer, security, _ = _identity(db)
    _import(db, close=10.0)
    pin = price_on_or_before(db, security, DAY_ONE)["pin"]
    other = master.ensure_security(issuer, class_designation="class B", currency="USD")
    with pytest.raises(PriceImportError, match="different security"):
        price_on_or_before(db, other, DAY_ONE, policy="pinned", pin=pin)


def test_saved_research_object_replays_its_pinned_revision(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    first = _import(db, close=10.0)
    source_id = first["source"]["source_id"]
    pin_one = price_on_or_before(db, security, DAY_ONE)["pin"]
    store = ResearchObjectStore(db)
    document = {
        "schema_version": "atlas.research_object.v1",
        "kind": "dataset",
        "name": "Pinned market observation study",
        "version": "1.0.0",
        "status": "draft",
        "description": "Records the exact observation revision used by the study.",
        "as_of": f"{DAY_ONE}T00:00:00Z",
        "mode": "atlas_ingested",
        "evidence_ids": [],
        "source_ids": [source_id],
        "spec": {
            "universe": ["TST"], "fields": ["close"], "frequency": "daily",
            "adjustment": "raw",
            "observation_pin": pin_one,
        },
    }
    saved = store.create(document)

    _import(db, close=11.0)  # a later correction must not touch the saved study

    reopened = store.get(saved["object_id"])
    stored_pin = reopened["document"]["spec"]["observation_pin"]
    replay = price_for_pin(db, stored_pin)
    assert replay["status"] == "exact"
    assert replay["price"]["close"] == 10.0

    # Explicitly opting in produces a second, separate research-object version.
    newer_pin = price_on_or_before(db, security, DAY_ONE)["pin"]
    updated = dict(document)
    updated["version"] = "1.1.0"
    updated["spec"] = dict(document["spec"], observation_pin=newer_pin)
    saved_two = store.create(updated)
    assert saved_two["object_id"] != saved["object_id"]
    assert price_for_pin(db, saved_two["document"]["spec"]["observation_pin"])["price"]["close"] == 11.0
    assert price_for_pin(db, store.get(saved["object_id"])["document"]["spec"]["observation_pin"])["price"]["close"] == 10.0


# ------------------------------------------------------------------ selection policy
def test_default_selection_declares_its_basis(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    selection = price_on_or_before(db, security, DAY_ONE)["source_selection"]
    assert selection["policy"] == SOURCE_SELECTION_POLICY
    assert selection["requested_policy"] == "latest_session"
    assert selection["dimensions"]["provider"] == "single_provider_selected_then_held_constant"
    assert selection["observation_id"].startswith("MOB-")


def test_latest_import_and_latest_session_are_different_choices(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, rows=[_row(10.0, day=DAY_TWO)])
    time.sleep(1.05)  # a genuinely later ingestion instant
    _import(db, close=20.0, source="Provider B", licence="B restricted", rows=[_row(20.0, day=DAY_ONE)])
    by_session = price_on_or_before(db, security, DAY_TWO, policy="latest_session")
    by_import = price_on_or_before(db, security, DAY_TWO, policy="latest_revision")
    assert by_session["date"] == DAY_TWO and by_session["close"] == 10.0
    assert by_import["date"] == DAY_ONE and by_import["close"] == 20.0
    assert by_import["source_selection"]["dimensions"]["revision"] == "latest_ingested_revision"


def test_explicit_source_policy_requires_a_source(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    with pytest.raises(PriceImportError, match="explicit_source"):
        price_on_or_before(db, security, DAY_ONE, policy="explicit_source")
    with pytest.raises(PriceImportError, match="unknown market-price selection policy"):
        price_on_or_before(db, security, DAY_ONE, policy="guess-the-best")


# ------------------------------------------------------------------- session identity
def test_batch_spanning_a_ticker_reassignment_is_rejected(db):
    ensure_default_sources(db)
    master, issuer, first_security, first_listing = _identity(db)
    master.assign_ticker(
        first_listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    second_security = master.ensure_security(issuer, class_designation="new common stock", currency="USD")
    second_listing = master.ensure_listing(second_security, "XNYS", valid_from="2025-01-01")
    master.assign_ticker(
        second_listing, "TST", valid_from="2025-01-01", confidence=1.0,
        status="confirmed", source_id="sec-edgar",
    )
    with pytest.raises(PriceImportError, match="do not resolve to the requested"):
        _import(
            db, close=10.0, as_of="2024-12-30",
            rows=[_row(10.0, day="2024-12-30"), _row(10.5, day="2025-01-02")],
        )
    assert db.scalar("SELECT COUNT(*) FROM bar") == 0


def test_session_outside_every_assignment_window_is_reported_not_reassigned(db):
    """A backfill session with no assignment window is flagged, never given an identity."""
    ensure_default_sources(db)
    master, _, security, first_listing = _identity(db)
    master.assign_ticker(
        first_listing, "TST", valid_from="2020-01-01", valid_to="2024-12-31",
        confidence=1.0, status="confirmed", source_id="sec-edgar",
    )
    imported = _import(db, close=10.0, as_of="2024-12-31", rows=[_row(10.0, day="2026-06-01")])
    assert imported["security_id"] == security
    assert imported["session_identity"]["unassigned_sessions"] == ["2026-06-01"]
    # The row still belongs to the declared security; no other identity was invented.
    stored = db.query("SELECT security_id FROM bar")
    assert [row["security_id"] for row in stored] == [security]


def test_session_identity_is_recorded_on_a_successful_import(db):
    ensure_default_sources(db)
    _, _, security, _ = _identity(db)
    imported = _import(
        db, close=10.0, rows=[_row(10.0, day=DAY_ONE), _row(10.5, day=DAY_TWO)],
    )
    identity = imported["session_identity"]
    assert identity["sessions_checked"] == 2
    assert identity["first_session"] == DAY_ONE
    assert identity["last_session"] == DAY_TWO
    assert identity["identity_basis"] == "per_session_ticker_resolution"
    assert price_summary(db, security)["latest_session"] == DAY_TWO
