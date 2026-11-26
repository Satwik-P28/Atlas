"""Domain primitives: identifiers, units, time semantics, concept registry."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from atlas.core.concepts import CONCEPTS, DERIVATIONS, concept_metadata, resolve_tag
from atlas.core.errors import (
    CurrencyMismatchError,
    TemporalError,
    UnitMismatchError,
    ValidationError,
)
from atlas.core.ids import (
    issuer_id_for_cik,
    issuer_id_for_entity,
    normalize_cik,
    normalize_class_key,
    normalize_ticker,
    security_id,
)
from atlas.core.temporal import (
    AsOfMode,
    Availability,
    AvailabilityPrecision,
    PeriodType,
    ReportingPeriod,
    availability_from_date,
    availability_from_instant,
    iso,
    iso_date,
    parse_date,
    parse_iso,
    unknown_availability,
)
from atlas.core.units import (
    Money,
    UnitKind,
    canonical_decimal,
    parse_decimal,
    parse_unit,
)


# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("320193", "0000320193"),
        (320193, "0000320193"),
        ("0000320193", "0000320193"),
        ("CIK0000320193", "0000320193"),
        ("cik320193", "0000320193"),
        ("1", "0000000001"),
    ],
)
def test_normalize_cik(raw, expected):
    assert normalize_cik(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12345678901", "-12"])
def test_normalize_cik_rejects_invalid(raw):
    with pytest.raises(ValidationError):
        normalize_cik(raw)


@pytest.mark.parametrize(
    "raw,expected",
    [("aapl", "AAPL"), (" brk.b ", "BRK.B"), ("bf-b", "BF-B")],
)
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "A B", "X" * 40])
def test_normalize_ticker_rejects_invalid(raw):
    with pytest.raises(ValidationError):
        normalize_ticker(raw)


@pytest.mark.parametrize(
    "designation,expected",
    [
        ("Common Stock", "common"),
        ("common shares", "common"),
        ("Class A Common Stock", "class_a"),
        ("Class B", "class_b"),
        ("Series C Preferred Stock", "series_c_preferred"),
    ],
)
def test_normalize_class_key(designation, expected):
    assert normalize_class_key(designation) == expected


def test_issuer_id_is_cik_anchored_and_entity_ids_differ():
    assert issuer_id_for_cik("320193") == "ISS-CIK0000320193"
    entity_id = issuer_id_for_entity("Apple Inc.", "US")
    assert entity_id.startswith("ISS-E")
    assert entity_id != issuer_id_for_cik("320193")


def test_security_id_ignores_ticker_and_distinguishes_share_classes():
    issuer = issuer_id_for_cik("320193")
    common = security_id(issuer, "common stock")
    class_a = security_id(issuer, "Class A Common Stock")
    assert common != class_a
    # Same inputs are stable across calls (idempotent ingestion relies on this).
    assert common == security_id(issuer, "Common Stock")
    assert "AAPL" not in common


# --------------------------------------------------------------------------- #
# Units and decimals
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,kind,currency",
    [
        ("USD", UnitKind.MONETARY, "USD"),
        ("usd", UnitKind.MONETARY, "USD"),
        ("USD/shares", UnitKind.PER_SHARE, "USD"),
        ("shares", UnitKind.SHARES, None),
        ("pure", UnitKind.PURE, None),
        ("USD millions", UnitKind.MONETARY, "USD"),
    ],
)
def test_parse_unit(raw, kind, currency):
    unit = parse_unit(raw)
    assert unit.kind is kind
    assert unit.currency == currency
    assert unit.raw == raw  # the source string is preserved for provenance


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1000.00", "1000"),
        (Decimal("1E+3"), "1000"),
        (Decimal("-0.00"), "0"),
        (Decimal("0.10"), "0.1"),
        (Decimal("0.123456789"), "0.123456789"),
        (0, "0"),
        (-5, "-5"),
    ],
)
def test_canonical_decimal(value, expected):
    assert canonical_decimal(value) == expected
    assert parse_decimal(expected) == parse_decimal(expected)


def test_canonical_decimal_rejects_binary_float():
    with pytest.raises(ValidationError):
        canonical_decimal(0.1)


def test_money_arithmetic_is_exact_and_currency_safe():
    total = Money(Decimal("0.1"), "USD").add(Money(Decimal("0.2"), "USD"))
    assert total.amount == Decimal("0.3")
    with pytest.raises(CurrencyMismatchError):
        Money(Decimal("1"), "USD").add(Money(Decimal("1"), "EUR"))


def test_unit_compatibility_rules():
    parse_unit("USD").require_compatible(parse_unit("USD"))
    with pytest.raises(UnitMismatchError):
        parse_unit("USD").require_compatible(parse_unit("shares"))
    with pytest.raises(CurrencyMismatchError):
        parse_unit("USD").require_compatible(parse_unit("EUR"))
    # per-share values are monetary in a specific currency
    parse_unit("USD/shares").require_compatible(parse_unit("USD/shares"))


# --------------------------------------------------------------------------- #
# Time semantics
# --------------------------------------------------------------------------- #
def test_iso_roundtrip_is_canonical():
    moment = datetime(2024, 5, 1, 16, 5, 12, tzinfo=timezone.utc)
    text = iso(moment)
    assert text == "2024-05-01T16:05:12Z"
    assert parse_iso(text) == moment
    assert iso("2024-05-01T16:05:12+00:00") == text
    assert iso_date("2024-05-01T23:00:00Z") == "2024-05-01"


def test_availability_from_date_is_conservative_end_of_day():
    availability = availability_from_date("2024-05-01", "test.filed")
    assert availability.precision is AvailabilityPrecision.DATE
    assert availability.iso == "2024-05-01T23:59:59Z"
    # A query earlier that day must not see it.
    assert availability.time > parse_iso("2024-05-01T12:00:00Z")


def test_availability_from_instant_is_exact():
    availability = availability_from_instant("2024-05-01T16:05:12Z", "sec.acceptance")
    assert availability.precision is AvailabilityPrecision.EXACT
    assert availability.known


def test_unknown_availability_cannot_carry_a_time():
    unknown = unknown_availability("no timing evidence")
    assert not unknown.known
    assert unknown.iso is None
    with pytest.raises(TemporalError):
        Availability(time=datetime(2024, 1, 1, tzinfo=timezone.utc), precision=AvailabilityPrecision.UNKNOWN, basis="x")
    with pytest.raises(TemporalError):
        Availability(time=None, precision=AvailabilityPrecision.EXACT, basis="x")


def test_availability_requires_evidence_basis():
    with pytest.raises(TemporalError):
        availability_from_instant("2024-05-01T00:00:00Z", "  ")


def test_reporting_period_invariants():
    annual = ReportingPeriod(end=date(2024, 9, 28), start=date(2023, 9, 30))
    assert annual.duration_days == 364
    assert annual.is_approximate_year
    assert not annual.is_approximate_quarter
    with pytest.raises(TemporalError):
        ReportingPeriod(end=date(2024, 3, 31), start=date(2024, 4, 1))
    with pytest.raises(TemporalError):
        ReportingPeriod(end=date(2024, 3, 31), start=date(2024, 1, 1), period_type=PeriodType.INSTANT)


def test_asof_modes_are_distinct():
    assert AsOfMode.PUBLIC_AVAILABLE.column == "availability_time"
    assert AsOfMode.ATLAS_INGESTED.column == "observed_at"
    assert AsOfMode.PUBLIC_AVAILABLE.description != AsOfMode.ATLAS_INGESTED.description


# --------------------------------------------------------------------------- #
# Concept registry
# --------------------------------------------------------------------------- #
def test_concept_resolution_prefers_registry_priority():
    resolution = resolve_tag(
        "revenue",
        [("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")],
    )
    assert resolution is not None
    assert resolution.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert resolution.priority == 0
    assert "us-gaap:Revenues" not in resolution.considered


def test_concept_resolution_falls_back_in_order():
    resolution = resolve_tag("revenue", [("us-gaap", "Revenues"), ("us-gaap", "SalesRevenueNet")])
    assert resolution is not None and resolution.tag == "Revenues"


def test_missing_concept_returns_none_rather_than_substituting():
    assert resolve_tag("revenue", [("us-gaap", "OperatingIncomeLoss")]) is None


def test_unknown_concept_is_an_error():
    with pytest.raises(KeyError):
        resolve_tag("ebitda_magic", [("us-gaap", "Revenues")])


def test_issuer_override_wins_but_must_be_reported():
    resolution = resolve_tag(
        "revenue", [("us-gaap", "Revenues")], issuer_overrides={"revenue": "us-gaap:Revenues"}
    )
    assert resolution is not None and resolution.reason == "issuer_override"
    # An override the issuer does not report must not fall back silently.
    assert resolve_tag("revenue", [("us-gaap", "SalesRevenueNet")], issuer_overrides={"revenue": "us-gaap:Revenues"}) is None


def test_every_concept_declares_tags_and_units():
    for key, concept in CONCEPTS.items():
        assert concept.source_tags, f"{key} has no source tags"
        assert all(namespace and tag for namespace, tag in concept.source_tags), key
        assert concept.unit_kind is not UnitKind.UNKNOWN, key
    for key, derivation in DERIVATIONS.items():
        assert derivation.requires, key
        assert derivation.rule_id.startswith("atlas.derived.")


def test_concept_metadata_is_serializable():
    metadata = concept_metadata()
    assert "revenue" in metadata
    assert metadata["revenue"]["source_tags"][0].startswith("us-gaap:")
