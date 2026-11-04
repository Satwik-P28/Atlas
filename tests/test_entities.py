"""Entity master: ticker changes, ticker reuse, share classes, delistings, conflicts."""

from __future__ import annotations

import pytest

from atlas.core.errors import AmbiguousResolution, UnknownEntity, ValidationError
from atlas.entities.master import RESOLUTION_AMBIGUOUS, SecurityMaster


def _meta_with_fb(master: SecurityMaster):
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Meta Platforms Demo Inc.", cik="1900001")
    security = master.ensure_security(issuer, class_designation="Class A common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2012-05-18", is_primary=True)
    master.assign_ticker(listing, "FB", valid_from="2012-05-18", confidence=1.0, status="confirmed")
    return issuer, security, listing


def _other_issuer_with_ticker(master: SecurityMaster, ticker: str, valid_from: str):
    issuer = master.register_issuer(legal_name="Unrelated Robotics Demo Corp", cik="1900002")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from=valid_from, is_primary=True)
    master.assign_ticker(listing, ticker, valid_from=valid_from, confidence=0.8, status="probable")
    return issuer, security, listing


# --------------------------------------------------------------------------- #
# Ticker changes
# --------------------------------------------------------------------------- #
def test_ticker_change_closes_the_old_assignment(master):
    _, security, _ = _meta_with_fb(master)
    change = master.record_ticker_change(security, "META", "2022-06-09")
    assert change["previous_ticker"] == "FB"
    assert change["previous_closed_on"] == "2022-06-08"
    assert change["new_ticker"] == "META"
    assignments = master.ticker_assignments(security)
    assert [(a["ticker"], a["valid_from"], a["valid_to"]) for a in assignments] == [
        ("FB", "2012-05-18", "2022-06-08"),
        ("META", "2022-06-09", None),
    ]


def test_historical_ticker_still_resolves_before_the_change(master):
    _, security, _ = _meta_with_fb(master)
    master.record_ticker_change(security, "META", "2022-06-09")
    before = master.resolve_ticker("FB", as_of="2021-06-01")
    assert before.candidates[0].security_id == security
    assert before.confidence == "confirmed"
    # The new ticker did not exist before the change.
    assert master.resolve_ticker("META", as_of="2021-06-01").candidates == []
    assert master.resolve_ticker("META", as_of="2023-01-01").candidates[0].security_id == security


def test_ticker_reuse_numbers_two_securities_without_merging(master):
    _, meta_security, _ = _meta_with_fb(master)
    master.record_ticker_change(meta_security, "META", "2022-06-09")
    _, reuse_security, _ = _other_issuer_with_ticker(master, "FB", "2023-01-10")

    early = master.resolve_ticker("FB", as_of="2021-06-01")
    late = master.resolve_ticker("FB", as_of="2024-01-01")
    assert early.candidates[0].security_id == meta_security
    assert late.candidates[0].security_id == reuse_security
    assert meta_security != reuse_security

    gap = master.resolve_ticker("FB", as_of="2022-12-01")
    assert gap.candidates == []
    assert gap.confidence == "none"
    assert any("not currently active" in line or "historical assignment" in line for line in gap.reasoning)

    current = master.resolve_ticker("FB")
    assert current.candidates[0].security_id == reuse_security
    # No overlap, so no conflict is reported even though the symbol was reused.
    assert master.ticker_conflicts("FB") == []


def test_simultaneous_claims_are_ambiguous_and_never_auto_resolved(master):
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    first_issuer = master.register_issuer(legal_name="First Claimant Inc.", cik="1900011")
    first = master.ensure_security(first_issuer, class_designation="common stock")
    first_listing = master.ensure_listing(first, "XNAS", valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(first_listing, "XYZ", valid_from="2020-01-01", confidence=0.9, status="confirmed")

    second_issuer = master.register_issuer(legal_name="Second Claimant Inc.", cik="1900012")
    second = master.ensure_security(second_issuer, class_designation="common stock")
    second_listing = master.ensure_listing(second, "XNAS", valid_from="2020-06-01", is_primary=True)
    master.assign_ticker(second_listing, "XYZ", valid_from="2020-06-01", confidence=0.9, status="confirmed")

    resolution = master.resolve_ticker("XYZ", as_of="2021-01-01")
    assert resolution.confidence == RESOLUTION_AMBIGUOUS
    assert len({candidate.security_id for candidate in resolution.candidates}) == 2
    assert any("not a permanent identifier" in line for line in resolution.reasoning)
    with pytest.raises(AmbiguousResolution):
        resolution.require_single()

    conflicts = master.ticker_conflicts("XYZ")
    assert len(conflicts) == 1
    assert conflicts[0]["overlap"] == ["2020-06-01", "9999-12-31"]


def test_ticker_reuse_notice_when_not_currently_active(master):
    _, meta_security, _ = _meta_with_fb(master)
    master.retire_security(meta_security, as_of="2022-06-08", reason="demo delisting")
    resolution = master.resolve_ticker("FB")
    assert resolution.candidates == []
    assert any("historical assignment" in line for line in resolution.reasoning)


# --------------------------------------------------------------------------- #
# Share classes and securities
# --------------------------------------------------------------------------- #
def test_one_issuer_multiple_share_classes(master):
    issuer = master.register_issuer(legal_name="Alphabet Demo Inc.", cik="1652044")
    class_a = master.ensure_security(issuer, class_designation="Class A common stock")
    class_c = master.ensure_security(issuer, class_designation="Class C capital stock")
    assert class_a != class_c
    assert len(master.securities_for_issuer(issuer)) == 2
    # Same designation resolves to the same security (no duplicate creation).
    assert master.ensure_security(issuer, class_designation="Class A Common Stock") == class_a


def test_security_requires_registered_issuer(master):
    with pytest.raises(UnknownEntity):
        master.ensure_security("ISS-CIK9999999999", class_designation="common stock")


def test_listing_requires_registered_venue(master):
    issuer = master.register_issuer(legal_name="No Venue Inc.", cik="1900021")
    security = master.ensure_security(issuer, class_designation="common stock")
    with pytest.raises(UnknownEntity):
        master.ensure_listing(security, "ZZZZ", valid_from="2020-01-01")


def test_delisting_closes_windows_but_keeps_history(master):
    _, security, _ = _meta_with_fb(master)
    master.retire_security(security, as_of="2024-01-01", reason="acquired")
    profile = master.security_profile(security)
    assert profile["security"]["is_active"] == 0
    assert profile["listings"][0]["valid_to"] == "2024-01-01"
    assert profile["tickers"][0]["valid_to"] == "2024-01-01"
    # Historical resolution still works for the period it was listed.
    assert master.resolve_ticker("FB", as_of="2021-06-01").candidates[0].security_id == security
    assert master.resolve_ticker("FB").candidates == []


def test_invalid_ticker_window_rejected(master):
    _, _, listing = _meta_with_fb(master)
    with pytest.raises(ValidationError):
        master.assign_ticker(listing, "BAD", valid_from="2020-01-01", valid_to="2019-01-01")


# --------------------------------------------------------------------------- #
# Identifiers and relationships
# --------------------------------------------------------------------------- #
def test_conflicting_identifiers_across_sources_are_surfaced(master):
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer_a = master.register_issuer(legal_name="Identifier A Inc.", cik="1900031")
    security_a = master.ensure_security(issuer_a, class_designation="common stock")
    issuer_b = master.register_issuer(legal_name="Identifier B Inc.", cik="1900032")
    security_b = master.ensure_security(issuer_b, class_designation="common stock")
    master.assign_identifier(security_a, "ISIN", "US0000000001", confidence=0.9, status="probable")
    master.assign_identifier(security_b, "ISIN", "US0000000001", confidence=0.6, status="unverified")

    resolution = master.resolve_identifier("ISIN", "US0000000001")
    assert resolution.confidence == RESOLUTION_AMBIGUOUS
    assert len(resolution.candidates) == 2
    assert any("conflicting sources" in line for line in resolution.reasoning)


def test_identifiers_are_not_licence_free_assumptions(master):
    issuer = master.register_issuer(legal_name="Cusip Holder Inc.", cik="1900041")
    security = master.ensure_security(issuer, class_designation="common stock")
    master.assign_identifier(
        security, "CUSIP", "037833100", confidence=0.5, status="probable",
        licence_note="CUSIP requires a licence from CUSIP Global Services; stored for internal matching only",
    )
    identifiers = master.identifiers(security)
    assert identifiers[0]["licence_note"].startswith("CUSIP requires a licence")


def test_relationships_require_distinct_issuers(master):
    parent = master.register_issuer(legal_name="Parent Inc.", cik="1900051")
    child = master.register_issuer(legal_name="Child Inc.", cik="1900052")
    relationship = master.record_relationship(parent, child, "subsidiary", valid_from="2019-01-01", confidence=0.9)
    assert relationship.startswith("REL-")
    with pytest.raises(ValidationError):
        master.record_relationship(parent, parent, "subsidiary")
    assert len(master.relationships(parent)) == 1


def test_issuer_profile_includes_securities_and_tickers(master):
    issuer, security, _ = _meta_with_fb(master)
    profile = master.issuer_profile(cik="1900001")
    assert profile["issuer"]["issuer_id"] == issuer
    assert profile["securities"][0]["security"]["security_id"] == security
    assert profile["securities"][0]["tickers"][0]["ticker"] == "FB"
    with pytest.raises(UnknownEntity):
        master.issuer_profile(cik="999999999")
