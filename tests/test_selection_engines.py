"""Differential and adversarial tests for point-in-time selection.

Two independent implementations exist: a Python selector and a SQL selector. They are
only allowed to coexist because they are proven equivalent here, over randomised data
and over the specific adversarial shapes that break naive as-of logic:

* date-precision availability at the day boundary,
* corrections published at the *same* instant,
* backfilled evidence that is publicly older but ingested later,
* records whose public availability is unevidenced (and are still knowable to Atlas),
* derived values competing with observed values.

Every scenario is asserted on both engines, so a future optimisation cannot quietly
change an answer.
"""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

import pytest

from atlas.core.errors import ValidationError
from atlas.core.temporal import (
    PeriodType,
    ReportingPeriod,
    availability_from_date,
    availability_from_instant,
    unknown_availability,
)
from atlas.evidence.kernel import ENGINE_PYTHON, ENGINE_SQL, EvidenceKernel
from atlas.evidence.model import EvidenceRecord

ENTITY = "ISS-CIK0000000001"
ENGINES = (ENGINE_PYTHON, ENGINE_SQL)


def add(
    kernel: EvidenceKernel,
    *,
    concept: str = "revenue",
    value: str = "100",
    unit: str = "USD",
    start: str | None = "2024-01-01",
    end: str = "2024-03-31",
    availability=None,
    quality: str = "verified",
    derivation: str = "source_observation",
    revision: str = "original",
    observed_at: str = "2024-09-01T00:00:00Z",
    accession: str | None = None,
    derivation_rule: str | None = None,
    lineage: dict | None = None,
    period_type: str | None = None,
):
    if period_type is None:
        period_type = PeriodType.DURATION.value if start else PeriodType.INSTANT.value
    if availability is None:
        availability = availability_from_instant("2024-05-01T16:05:12Z", "test.acceptance")
    record = EvidenceRecord.build(
        entity_id=ENTITY,
        entity_kind="issuer",
        concept=concept,
        source_id="sec-edgar",
        unit=unit,
        availability=availability,
        period=ReportingPeriod(
            end=date.fromisoformat(end),
            start=date.fromisoformat(start) if start else None,
            fiscal_year=2024,
            fiscal_period="Q1",
            period_type=PeriodType(period_type),
        ),
        value=Decimal(value),
        quality=quality,
        verification="source_primary",
        derivation_kind=derivation,
        derivation_rule=derivation_rule,
        lineage=lineage,
        revision_kind=revision,
        accession_number=accession,
        form_type="10-Q",
        observed_at=observed_at,
        taxonomy="us-gaap",
        source_concept="Revenues",
    )
    return kernel.ingest(record)


def summarize(result) -> tuple:
    facts = {}
    for fact in result.facts:
        key = (fact.concept, fact.period_start or "", fact.period_end or "", fact.unit)
        facts[key] = {
            "value": fact.value,
            "evidence_id": fact.evidence_id,
            "revisions": fact.revision_count,
            "flags": tuple(fact.quality_flags),
            "availability": fact.availability_time,
            "derivation": fact.derivation_kind,
            "unknown": fact.availability_unknown,
        }
    contradictions = sorted(
        (c["concept"], tuple(c["values"]), tuple(c["evidence_ids"]), c["selected"])
        for c in result.contradictions
    )
    return (
        facts,
        contradictions,
        result.excluded_not_yet_available,
        result.excluded_unknown_availability,
        result.completeness,
        tuple(result.notes),
    )


def assert_engines_agree(kernel: EvidenceKernel, as_of: str, **kwargs):
    results = {
        engine: kernel.as_of(ENTITY, as_of, engine=engine, **kwargs) for engine in ENGINES
    }
    summarized = {engine: summarize(result) for engine, result in results.items()}
    assert summarized[ENGINE_SQL] == summarized[ENGINE_PYTHON], (
        f"engines disagree at {as_of} with {kwargs}\n"
        f"python={summarized[ENGINE_PYTHON]}\nsql={summarized[ENGINE_SQL]}"
    )
    return results[ENGINE_SQL]


# --------------------------------------------------------------------------- #
# Adversarial scenarios
# --------------------------------------------------------------------------- #
def test_date_precision_is_conservative_at_the_day_boundary(kernel):
    add(
        kernel,
        availability=availability_from_date("2024-05-02", "sec_companyfacts.filed_date_end_of_day_utc"),
        accession="0000000001-24-000001",
    )
    before = assert_engines_agree(kernel, "2024-05-02T12:00:00Z")
    assert before.facts == []
    assert before.excluded_not_yet_available == 1

    at_end_of_day = assert_engines_agree(kernel, "2024-05-02T23:59:59Z")
    assert len(at_end_of_day.facts) == 1

    after = assert_engines_agree(kernel, "2024-05-03T00:00:00Z")
    assert len(after.facts) == 1
    assert after.facts[0].availability_precision == "date"


def test_simultaneous_corrections_are_adjudicated_and_reported(kernel):
    instant = availability_from_instant("2024-05-01T16:05:12Z", "test.acceptance")
    add(kernel, value="100", availability=instant, accession="0000000001-24-000001")
    add(
        kernel,
        value="90",
        availability=instant,
        revision="correction",
        quality="unverified",
        accession="0000000001-24-000002",
    )
    result = assert_engines_agree(kernel, "2024-06-01T00:00:00Z")
    assert len(result.facts) == 1
    fact = result.facts[0]
    # The revision chain says which assertion came later; ingestion order breaks the tie.
    assert fact.value == "90"
    assert len(result.contradictions) == 1
    contradiction = result.contradictions[0]
    assert contradiction["values"] == ["100", "90"]
    assert len(contradiction["evidence_ids"]) == 2
    assert contradiction["selected"] == fact.evidence_id
    assert "contradictory_evidence" in fact.quality_flags


def test_backfilled_evidence_does_not_overwrite_newer_knowledge(kernel):
    add(
        kernel,
        value="200",
        availability=availability_from_instant("2024-08-01T20:00:00Z", "test.acceptance"),
        accession="0000000001-24-000010",
    )
    # Ingested later, but publicly available earlier: a backfill, not a revision.
    add(
        kernel,
        value="150",
        availability=availability_from_instant("2024-05-01T20:00:00Z", "test.acceptance"),
        accession="0000000001-24-000009",
    )
    june = assert_engines_agree(kernel, "2024-06-01T00:00:00Z")
    assert [f.value for f in june.facts] == ["150"]

    september = assert_engines_agree(kernel, "2024-09-01T00:00:00Z")
    assert [f.value for f in september.facts] == ["200"]
    assert september.contradictions == []
    assert september.facts[0].revision_count == 2

    # No supersession edge was invented for the backfill.
    assert kernel.get(june.facts[0].evidence_id).revision_kind == "original"


def test_atlas_ingested_mode_includes_unknown_availability_exactly_once(kernel):
    add(
        kernel,
        value="77",
        availability=unknown_availability("sec_companyfacts:no_filed_date"),
        observed_at="2024-07-01T00:00:00Z",
        accession="0000000001-24-000020",
    )
    public = assert_engines_agree(kernel, "2024-09-01T00:00:00Z")
    assert public.facts == []
    assert public.excluded_unknown_availability == 1
    assert "not provably complete" in public.completeness or public.completeness.startswith("incomplete")

    ingested = assert_engines_agree(kernel, "2024-09-01T00:00:00Z", mode="atlas_ingested")
    assert len(ingested.facts) == 1
    assert ingested.facts[0].value == "77"
    assert ingested.excluded_unknown_availability == 0
    assert ingested.facts[0].availability_unknown is True

    # The same record must not be emitted twice (once as known, once as unknown).
    assert len({f.evidence_id for f in ingested.facts}) == 1

    # Atlas had not ingested it before 1 July even though it is publicly old.
    earlier = assert_engines_agree(kernel, "2024-06-01T00:00:00Z", mode="atlas_ingested")
    assert earlier.facts == []
    assert earlier.excluded_not_yet_available == 1


def test_source_observation_outranks_derived_value(kernel):
    add(kernel, concept="gross_profit", value="40", availability=availability_from_instant("2024-05-01T10:00:00Z", "t"))
    add(
        kernel,
        concept="gross_profit",
        value="41",
        availability=availability_from_instant("2024-06-01T10:00:00Z", "t"),
        derivation="derived_calculation",
        derivation_rule="atlas.derived.gross_profit.v1",
    )
    result = assert_engines_agree(kernel, "2024-07-01T00:00:00Z", concepts=["gross_profit"])
    assert [f.value for f in result.facts] == ["40"]
    assert result.facts[0].derivation_kind == "source_observation"


def test_contradiction_without_chain_prefers_best_quality(kernel):
    instant = availability_from_instant("2024-05-01T16:05:12Z", "t")
    add(kernel, value="10", availability=instant, quality="suspect")
    add(kernel, value="11", availability=instant, quality="verified")
    result = assert_engines_agree(kernel, "2024-06-01T00:00:00Z")
    assert len(result.contradictions) == 1
    assert result.facts[0].value == "11"
    assert result.facts[0].quality == "verified"


def test_unchanged_value_reports_earliest_evidence(kernel):
    add(kernel, value="500", availability=availability_from_instant("2024-05-01T10:00:00Z", "t"), accession="A1")
    add(kernel, value="500", availability=availability_from_instant("2024-06-01T10:00:00Z", "t"), accession="A2")
    result = assert_engines_agree(kernel, "2024-07-01T00:00:00Z")
    assert result.facts[0].accession_number == "A1"
    assert result.facts[0].revision_count == 2
    assert result.facts[0].superseded_versions == []


# --------------------------------------------------------------------------- #
# Randomised differential test
# --------------------------------------------------------------------------- #
CONCEPTS = ("revenue", "net_income", "assets")
UNITS = ("USD", "EUR")
VALUES = ("100", "101", "102", "103")
INSTANTS = (
    "2024-02-15T00:00:00Z",
    "2024-05-01T00:00:00Z",
    "2024-07-15T00:00:00Z",
    "2024-10-01T00:00:00Z",
    "2025-01-01T00:00:00Z",
)


def _random_records(rng: random.Random, count: int) -> list[dict]:
    records: list[dict] = []
    for _ in range(count):
        concept = rng.choice(CONCEPTS)
        choose = rng.random()
        if choose < 0.65:
            availability = availability_from_instant(
                f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T"
                f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
                "test.exact",
            )
        elif choose < 0.9:
            availability = availability_from_date(
                f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "test.date",
            )
        else:
            availability = unknown_availability("test.unknown")
        end = rng.choice(["2024-03-31", "2024-06-30", "2024-09-30"])
        start = None
        if concept != "assets":
            # Quarter or year to date, always ending at ``end``: a start after the end
            # would be an invalid period, and the point of this test is selection.
            span = rng.choice([90, 365])
            start = (date.fromisoformat(end) - __import__("datetime").timedelta(days=span)).isoformat()
        records.append(
            {
                "concept": concept,
                "unit": rng.choice(UNITS),
                "value": rng.choice(VALUES),
                "start": start,
                "end": end,
                "availability": availability,
                "quality": rng.choice(["verified", "verified", "unverified", "suspect"]),
                "derivation": "derived_calculation" if rng.random() < 0.15 else "source_observation",
                "revision": rng.choice(["original", "original", "amendment"]),
                "observed_at": f"2024-{rng.randint(1, 12):02d}-01T00:00:00Z",
                "accession": f"0000000001-24-{rng.randint(1, 999999):06d}",
            }
        )
    return records


@pytest.mark.parametrize("seed", [7, 21, 43, 99])
def test_engines_agree_on_randomised_histories(kernel, seed):
    rng = random.Random(seed)
    records = _random_records(rng, 45)
    rng.shuffle(records)
    for record in records:
        add(
            kernel,
            **record,
            derivation_rule="atlas.derived.gross_profit.v1" if record["derivation"] == "derived_calculation" else None,
        )
    for as_of in INSTANTS:
        for mode in ("public_available", "atlas_ingested"):
            for include_unknown in (False, True):
                assert_engines_agree(
                    kernel, as_of, mode=mode, include_unknown=include_unknown
                )


def test_engines_agree_on_the_real_apple_payload(db):
    import json
    from pathlib import Path

    from atlas.ingestion.sec_sync import SecIngestor

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "sec"
    submissions = json.loads((fixtures / "submissions_CIK0000320193.json").read_text())
    facts = json.loads((fixtures / "companyfacts_CIK0000320193.json").read_text())
    report = SecIngestor(db).sync_payloads(
        "0000320193",
        submissions_payload=submissions,
        companyfacts_payload=facts,
        observed_at="2026-01-01T00:00:00Z",
    )
    kernel = EvidenceKernel(db)
    for as_of in ("2019-01-01T00:00:00Z", "2022-06-30T00:00:00Z", "2026-12-31T00:00:00Z"):
        for mode in ("public_available", "atlas_ingested"):
            for statement in (None, "income", "balance", "cashflow"):
                results = {
                    engine: kernel.as_of(
                        report.issuer_id, as_of, mode=mode, statement=statement, engine=engine
                    )
                    for engine in ENGINES
                }
                assert summarize(results[ENGINE_SQL]) == summarize(results[ENGINE_PYTHON]), (
                    f"engines disagree for {as_of} {mode} {statement}"
                )


def test_unknown_engine_is_rejected(kernel):
    with pytest.raises(ValidationError):
        kernel.as_of(ENTITY, "2024-01-01T00:00:00Z", engine="magic")
