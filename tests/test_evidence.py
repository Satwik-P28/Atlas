"""Temporal evidence kernel: immutability, supersession, point-in-time selection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from atlas.core.errors import MissingDataError, ValidationError
from atlas.core.temporal import (
    ReportingPeriod,
    availability_from_date,
    availability_from_instant,
    unknown_availability,
)
from atlas.evidence.kernel import SELECTION_POLICY, IngestStatus

ENTITY = "ISS-CIK0000320193"


# --------------------------------------------------------------------------- #
# Idempotency and immutability
# --------------------------------------------------------------------------- #
def test_ingest_twice_is_idempotent(kernel, make_fact):
    first = kernel.ingest(make_fact())
    second = kernel.ingest(make_fact())
    assert first.status == IngestStatus.INSERTED
    assert second.status == IngestStatus.DUPLICATE
    assert second.evidence_id == first.evidence_id
    assert kernel.count() == 1


def test_reobservation_with_new_timestamp_is_still_a_duplicate(kernel, make_fact):
    kernel.ingest(make_fact(observed_at="2024-09-01T00:00:00Z"))
    outcome = kernel.ingest(make_fact(observed_at="2025-01-01T00:00:00Z"))
    assert outcome.status == IngestStatus.DUPLICATE
    assert kernel.count() == 1


def test_restatement_creates_a_new_record_and_preserves_the_original(kernel, make_fact):
    original = make_fact(value=Decimal("100000000"))
    amended = make_fact(
        value=Decimal("90000000"),
        accession_number="0001999999-24-000009",
        form_type="10-Q/A",
        revision_kind="amendment",
        availability=availability_from_instant("2024-08-15T20:31:44Z", "test.acceptance"),
    )
    kernel.ingest(original)
    outcome = kernel.ingest(amended)
    assert outcome.status == IngestStatus.SUPERSEDING
    assert outcome.superseded == [original.evidence_id]
    assert kernel.count() == 2
    history = kernel.history(ENTITY, "revenue")
    assert [record.value_numeric for record in history] == ["100000000", "90000000"]
    assert [record.revision_kind for record in history] == ["original", "amendment"]


def test_supersession_links_are_recorded_in_both_directions(kernel, make_fact, db):
    original = make_fact()
    amended = make_fact(
        value=Decimal("90000000"),
        accession_number="0001999999-24-000009",
        availability=availability_from_instant("2024-08-15T20:31:44Z", "t"),
    )
    kernel.ingest(original)
    kernel.ingest(amended)
    rows = db.query("SELECT superseded_id, superseding_id FROM evidence_supersession")
    assert [(row["superseded_id"], row["superseding_id"]) for row in rows] == [
        (original.evidence_id, amended.evidence_id)
    ]
    chain = kernel.lineage(original.evidence_id)
    original_entry = next(entry for entry in chain if entry["evidence_id"] == original.evidence_id)
    assert original_entry["superseded_by"] == [amended.evidence_id]


def test_later_availability_only(kernel, make_fact):
    """A record whose availability is unknown must never supersede a dated one."""
    dated = make_fact(availability=availability_from_instant("2024-05-01T16:05:12Z", "t"))
    undated = make_fact(
        value=Decimal("1"),
        accession_number="0001999999-24-000010",
        availability=unknown_availability("no filed date"),
    )
    kernel.ingest(dated)
    outcome = kernel.ingest(undated)
    assert outcome.superseded == []
    assert kernel.count() == 2


# --------------------------------------------------------------------------- #
# Question A: what was publicly available?
# --------------------------------------------------------------------------- #
def test_as_of_excludes_later_disclosure(kernel, make_fact):
    original = make_fact(value=Decimal("100000000"))
    restated = make_fact(
        value=Decimal("90000000"),
        accession_number="0001999999-24-000009",
        form_type="10-Q/A",
        revision_kind="amendment",
        availability=availability_from_instant("2024-08-15T20:31:44Z", "t"),
    )
    kernel.ingest(original)
    kernel.ingest(restated)

    before = kernel.as_of(ENTITY, "2024-06-01T00:00:00Z", concepts=["revenue"])
    assert [fact.value for fact in before.facts] == ["100000000"]
    assert before.facts[0].accession_number == "0001999999-24-000004"
    assert before.excluded_not_yet_available == 1
    assert before.mode == "public_available"

    after = kernel.as_of(ENTITY, "2024-09-01T00:00:00Z", concepts=["revenue"])
    assert [fact.value for fact in after.facts] == ["90000000"]
    assert after.facts[0].superseded_versions == [original.evidence_id]


def test_as_of_before_first_disclosure_returns_nothing(kernel, make_fact):
    kernel.ingest(make_fact())
    result = kernel.as_of(ENTITY, "2020-01-01T00:00:00Z")
    assert result.facts == []
    assert result.excluded_not_yet_available == 1


def test_date_precision_availability_is_not_visible_earlier_that_day(kernel, make_fact):
    record = make_fact(
        availability=availability_from_date("2024-05-01", "test.filed"),
        accession_number="0001999999-24-000077",
    )
    kernel.ingest(record)
    morning = kernel.as_of(ENTITY, "2024-05-01T12:00:00Z")
    evening = kernel.as_of(ENTITY, "2024-05-01T23:59:59Z")
    assert morning.facts == []
    assert len(evening.facts) == 1
    assert evening.facts[0].availability_precision == "date"


def test_unknown_availability_is_excluded_and_reported(kernel, make_fact):
    kernel.ingest(make_fact(availability=unknown_availability("no timing evidence")))
    result = kernel.as_of(ENTITY, "2030-01-01T00:00:00Z")
    assert result.facts == []
    assert result.excluded_unknown_availability == 1
    assert result.completeness.startswith(("partial", "incomplete"))
    assert any("excluded" in note for note in result.notes)

    included = kernel.as_of(ENTITY, "2030-01-01T00:00:00Z", include_unknown=True)
    assert len(included.facts) == 1
    assert included.facts[0].availability_unknown is True
    assert "availability_unknown" in included.facts[0].quality_flags


# --------------------------------------------------------------------------- #
# Question B: what had Atlas ingested?
# --------------------------------------------------------------------------- #
def test_public_availability_and_ingestion_are_different_questions(kernel, make_fact):
    record = make_fact(
        availability=availability_from_instant("2024-05-01T16:05:12Z", "t"),
        observed_at="2024-09-01T00:00:00Z",
    )
    kernel.ingest(record)
    public = kernel.as_of(ENTITY, "2024-06-01T00:00:00Z", mode="public_available")
    ingested = kernel.as_of(ENTITY, "2024-06-01T00:00:00Z", mode="atlas_ingested")
    assert len(public.facts) == 1
    assert ingested.facts == []
    later = kernel.as_of(ENTITY, "2024-10-01T00:00:00Z", mode="atlas_ingested")
    assert len(later.facts) == 1
    assert later.facts[0].observed_at == "2024-09-01T00:00:00Z"


def test_atlas_ingested_mode_ignores_availability(kernel, make_fact):
    """Observed before it was public: a data error, but each question answers honestly."""
    kernel.ingest(make_fact(availability=availability_from_instant("2024-05-01T16:05:12Z", "t"),
                            observed_at="2024-04-01T00:00:00Z"))
    assert len(kernel.as_of(ENTITY, "2024-04-15T00:00:00Z", mode="atlas_ingested").facts) == 1
    assert kernel.as_of(ENTITY, "2024-04-15T00:00:00Z", mode="public_available").facts == []


# --------------------------------------------------------------------------- #
# Selection policy details
# --------------------------------------------------------------------------- #
def test_unchanged_value_keeps_earliest_evidence(kernel, make_fact):
    first = make_fact(availability=availability_from_instant("2024-05-01T16:05:12Z", "t"))
    reassertion = make_fact(
        accession_number="0001999999-25-000002",
        form_type="10-K",
        availability=availability_from_instant("2025-05-01T16:05:12Z", "t"),
    )
    kernel.ingest(first)
    kernel.ingest(reassertion)
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z")
    assert result.facts[0].evidence_id == first.evidence_id
    assert result.facts[0].revision_count == 2
    assert "multiple_versions" in result.facts[0].quality_flags


def test_source_observation_outranks_derived_value(kernel, make_fact):
    source = make_fact(concept="gross_profit", value=Decimal("40"), source_concept="GrossProfit")
    derived = make_fact(
        concept="gross_profit",
        value=Decimal("41"),
        derivation_kind="derived_calculation",
        derivation_rule="atlas.derived.gross_profit.v1",
        accession_number=None,
        source_concept=None,
        availability=availability_from_instant("2024-09-01T00:00:00Z", "t"),
    )
    kernel.ingest(source)
    kernel.ingest(derived)
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z", concepts=["gross_profit"])
    assert result.facts[0].value == "40"
    assert result.facts[0].derivation_kind == "source_observation"


def test_contradictory_values_with_identical_availability_are_flagged(kernel, make_fact):
    kernel.ingest(make_fact(value=Decimal("100"), accession_number="0001999999-24-000004"))
    kernel.ingest(make_fact(value=Decimal("101"), accession_number="0001999999-24-000005"))
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z")
    assert result.contradictions
    assert result.contradictions[0]["concept"] == "revenue"
    assert len(result.contradictions[0]["values"]) == 2
    assert "contradictory_evidence" in result.facts[0].quality_flags


def test_annual_and_quarterly_periods_coexist(kernel, make_fact):
    quarterly = make_fact(
        period=ReportingPeriod(end=date(2024, 3, 31), start=date(2024, 1, 1), fiscal_year=2024, fiscal_period="Q1"),
        value=Decimal("100"),
    )
    annual = make_fact(
        period=ReportingPeriod(end=date(2024, 3, 31), start=date(2023, 4, 1), fiscal_year=2024, fiscal_period="FY"),
        value=Decimal("400"),
    )
    kernel.ingest(quarterly)
    kernel.ingest(annual)
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z", concepts=["revenue"])
    assert len(result.facts) == 2
    assert {fact.value for fact in result.facts} == {"100", "400"}
    assert {fact.period_start for fact in result.facts} == {"2024-01-01", "2023-04-01"}


def test_different_units_are_separate_facts(kernel, make_fact):
    revenue = make_fact(concept="revenue", unit="USD", value=Decimal("100"))
    eps = make_fact(
        concept="eps_diluted",
        unit="USD/shares",
        value=Decimal("1.25"),
        source_concept="EarningsPerShareDiluted",
        period=ReportingPeriod(end=date(2024, 3, 31), start=date(2024, 1, 1)),
    )
    shares = make_fact(
        concept="weighted_average_shares_diluted",
        unit="shares",
        value=Decimal("1000"),
        source_concept="WeightedAverageNumberOfDilutedSharesOutstanding",
        period=ReportingPeriod(end=date(2024, 3, 31), start=date(2024, 1, 1)),
    )
    for record in (revenue, eps, shares):
        kernel.ingest(record)
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z")
    units = {fact.concept: fact.unit for fact in result.facts}
    assert units == {"revenue": "USD", "eps_diluted": "USD/shares",
                     "weighted_average_shares_diluted": "shares"}


def test_selection_result_records_its_policy(kernel, make_fact):
    kernel.ingest(make_fact())
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z")
    assert result.policy == SELECTION_POLICY
    assert result.to_dict()["mode_description"].startswith("information publicly available")


def test_unknown_concept_filter_is_rejected(kernel):
    with pytest.raises(ValidationError):
        kernel.as_of(ENTITY, "2026-01-01T00:00:00Z", concepts=["made_up_concept"])


def test_pagination_reports_truncation(kernel, make_fact):
    for index, concept in enumerate(["revenue", "net_income", "assets", "liabilities"]):
        kernel.ingest(
            make_fact(concept=concept, source_concept=f"Tag{index}", value=Decimal(index + 1),
                      unit="USD", period=ReportingPeriod(end=date(2024, 3, 31)))
        )
    result = kernel.as_of(ENTITY, "2026-01-01T00:00:00Z", limit=2)
    assert len(result.facts) == 2
    assert result.truncated is True


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def test_provenance_traverses_back_to_the_source(kernel, make_fact):
    record = make_fact()
    kernel.ingest(record)
    report = kernel.provenance(record.evidence_id)
    assert report.source["source_id"] == "sec-edgar"
    assert report.source["redistribution"] == "public_domain"
    assert report.record.accession_number == "0001999999-24-000004"
    assert any("10-Q" in line for line in report.narrative)
    assert any("availability" in line.lower() for line in report.narrative)
    assert report.revision_chain[0]["evidence_id"] == record.evidence_id


def test_provenance_flags_missing_availability(kernel, make_fact):
    record = make_fact(availability=unknown_availability("no filed date"))
    kernel.ingest(record)
    report = kernel.provenance(record.evidence_id)
    assert any("NOT EVIDENCED" in line for line in report.narrative)
    assert any("not evidenced" in limitation.lower() for limitation in report.limitations)


def test_provenance_of_derived_value_lists_inputs(kernel, make_fact):
    revenue = make_fact(concept="revenue", value=Decimal("100"))
    cost = make_fact(concept="cost_of_revenue", value=Decimal("60"), source_concept="CostOfRevenue")
    kernel.ingest(revenue)
    kernel.ingest(cost)
    derived = make_fact(
        concept="gross_profit",
        value=Decimal("40"),
        derivation_kind="derived_calculation",
        derivation_rule="atlas.derived.gross_profit.v1",
        accession_number=None,
        source_concept=None,
        lineage={
            "rule": "atlas.derived.gross_profit.v1",
            "steps": [{"step": "subtract", "detail": "revenue - cost_of_revenue"}],
            "inputs": [
                {"evidence_id": revenue.evidence_id, "concept": "revenue", "value": "100", "unit": "USD"},
                {"evidence_id": cost.evidence_id, "concept": "cost_of_revenue", "value": "60", "unit": "USD"},
            ],
        },
    )
    kernel.ingest(derived)
    report = kernel.provenance(derived.evidence_id)
    assert len(report.derived_inputs) == 2
    assert all(entry["found"] for entry in report.derived_inputs)
    assert report.transformation[0]["step"] == "subtract"
    assert report.record.derivation_kind == "derived_calculation"


def test_missing_evidence_raises(kernel):
    with pytest.raises(MissingDataError):
        kernel.get("EV-does-not-exist")


def test_stats_summarise_activity(kernel, make_fact):
    kernel.ingest(make_fact())
    kernel.ingest(make_fact(value=Decimal("1"), accession_number="A-2",
                            availability=availability_from_instant("2024-09-01T00:00:00Z", "t")))
    stats = kernel.stats()
    assert stats["evidence_records"] == 2
    assert stats["distinct_accessions"] == 2
    assert stats["supersession_links"] == 1
    assert stats["by_concept"]["revenue"] == 2
