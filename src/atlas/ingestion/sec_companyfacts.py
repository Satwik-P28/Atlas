"""SEC company facts (XBRL) parsing and normalisation.

The ``companyfacts`` endpoint returns every XBRL fact a registrant has ever reported,
grouped by taxonomy/namespace, then element name, then unit. Two consequences drive
the design here:

1. **A fact is re-reported many times.** Annual revenue appears in the 10-K that
   covers it and again as a comparative in the following year's 10-K. Each appearance
   is a separate observation with its own accession and filing date, so each becomes a
   separate evidence record. The kernel's point-in-time selection decides which one to
   show for a given date; nothing here collapses them.
2. **Not every element means what its name suggests for every issuer.** Mapping is
   restricted to the explicit registry in ``atlas.core.concepts``; unmapped elements
   are counted and reported rather than guessed at.

Availability is taken from the filing's SEC acceptance timestamp when the submissions
payload is available (``exact`` precision). Otherwise it falls back to the filing
``filed`` date pinned to end-of-day UTC (``date`` precision), which is conservative:
an as-of query on that date will not see the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from ..core.concepts import CONCEPTS, TagResolution, resolve_tag
from ..core.errors import ParseError
from ..core.temporal import (
    Availability,
    PeriodType,
    ReportingPeriod,
    availability_from_date,
    availability_from_instant,
    iso,
    iso_date,
    parse_date,
    parse_iso,
    to_utc,
    unknown_availability,
    utcnow,
)
from ..core.units import UnitKind, canonical_decimal, parse_unit
from ..evidence.model import DerivationKind, EvidenceRecord, Quality, RevisionKind, Verification, lineage_step
from .sec_submissions import FilingInfo

SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

NORMALIZE_MAGNITUDE_OUTFLOW_RULE = "atlas.normalize.magnitude_outflow.v1"

#: Unit kinds each canonical concept may legitimately be reported in.
_ALLOWED_UNIT_KINDS: dict[UnitKind, UnitKind] = {k: k for k in UnitKind}


@dataclass(slots=True)
class CompanyFactsResult:
    records: list[EvidenceRecord] = field(default_factory=list)
    entity_name: str | None = None
    cik: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    unmapped_tags: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_name": self.entity_name,
            "cik": self.cik,
            "stats": self.stats,
            "unmapped_tags": self.unmapped_tags,
            "issues": self.issues,
            "records": len(self.records),
        }


def decimal_from_json(value: Any) -> Decimal:
    """Convert a JSON number/string to an exact Decimal.

    Python parses JSON numbers as floats. Converting through ``str`` recovers the
    shortest round-tripping decimal, which is the value the source intended (SEC emits
    at most a handful of decimals). Float arithmetic is never used downstream.
    """
    if isinstance(value, bool):
        raise ParseError("boolean is not a valid financial value", value=value)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            return Decimal(text)
        except Exception as exc:  # noqa: BLE001
            raise ParseError("unparseable numeric value", value=value) from exc
    raise ParseError("unsupported value type", value_type=type(value).__name__)


def _availability_for(
    observation: Mapping[str, Any],
    filing: FilingInfo | None,
) -> tuple[Availability, str]:
    """Resolve evidenced public availability, or an explicit unknown."""
    if filing is not None and filing.acceptance_datetime:
        try:
            return (
                availability_from_instant(
                    parse_iso(filing.acceptance_datetime),
                    "sec_submissions.acceptance_datetime",
                ),
                "exact",
            )
        except Exception:  # noqa: BLE001 - malformed timestamp falls back conservatively
            pass
    filed = observation.get("filed") or (filing.filed_date if filing else None)
    if filed:
        return (
            availability_from_date(parse_date(filed), "sec_companyfacts.filed_date_end_of_day_utc"),
            "date",
        )
    return unknown_availability("sec_companyfacts:no_filed_date"), "unknown"


def _period_for(observation: Mapping[str, Any]) -> ReportingPeriod | None:
    end = observation.get("end")
    if not end:
        return None
    start = observation.get("start")
    fy = observation.get("fy")
    fp = observation.get("fp")
    try:
        return ReportingPeriod(
            end=parse_date(end),
            start=parse_date(start) if start else None,
            fiscal_year=int(fy) if fy is not None else None,
            fiscal_period=str(fp) if fp else None,
            period_type=PeriodType.DURATION if start else PeriodType.INSTANT,
        )
    except Exception:  # noqa: BLE001 - invalid periods are reported, not coerced
        return None


def parse_companyfacts(
    payload: Mapping[str, Any],
    *,
    issuer_id: str,
    source_id: str,
    source_url: str,
    raw_doc_id: str | None = None,
    observed_at: str | None = None,
    filings: Mapping[str, FilingInfo] | None = None,
    issuer_overrides: Mapping[str, str] | None = None,
    include_concepts: Sequence[str] | None = None,
) -> CompanyFactsResult:
    """Normalise a ``companyfacts`` payload into evidence records."""
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise ParseError("companyfacts payload has no 'facts' object", url=source_url)
    observed = iso(to_utc(observed_at)) if observed_at else iso(utcnow())
    filing_index = filings or {}
    wanted = set(include_concepts) if include_concepts else None

    available: set[tuple[str, str]] = set()
    for namespace, elements in facts.items():
        if not isinstance(elements, Mapping):
            continue
        for tag in elements:
            available.add((str(namespace), str(tag)))

    result = CompanyFactsResult(
        entity_name=payload.get("entityName"),
        cik=str(payload.get("cik")) if payload.get("cik") is not None else None,
    )

    mapped_tags: set[tuple[str, str]] = set()
    observations_total = 0
    observations_used = 0
    observations_skipped_units = 0
    observations_skipped_period = 0
    duplicates_removed = 0
    currencies_by_concept: dict[str, set[str]] = {}
    dedupe: dict[tuple[str, ...], EvidenceRecord] = {}
    conflicting: dict[tuple[str, ...], set[str]] = {}
    concepts_covered: list[str] = []

    for concept_key, concept in CONCEPTS.items():
        if wanted is not None and concept_key not in wanted:
            continue
        resolution = resolve_tag(concept_key, available, issuer_overrides=issuer_overrides)
        if resolution is None:
            continue
        concepts_covered.append(concept_key)
        mapped_tags.add((resolution.namespace, resolution.tag))
        element = facts.get(resolution.namespace, {}).get(resolution.tag, {})
        units = element.get("units", {}) if isinstance(element, Mapping) else {}
        if not isinstance(units, Mapping):
            continue
        for unit_raw, observations in units.items():
            parsed_unit = parse_unit(unit_raw)
            if parsed_unit.kind is not concept.unit_kind:
                observations_skipped_units += len(observations or [])
                result.issues.append(
                    {
                        "code": "unit_kind_mismatch",
                        "severity": "warning",
                        "concept": concept_key,
                        "unit": unit_raw,
                        "detail": (
                            f"{concept_key} is expected in {concept.unit_kind.value} units; "
                            f"observations reported in {parsed_unit.kind.value} were not mapped"
                        ),
                    }
                )
                continue
            if parsed_unit.currency:
                currencies_by_concept.setdefault(concept_key, set()).add(parsed_unit.currency)
            for observation in observations or []:
                observations_total += 1
                period = _period_for(observation)
                if period is None:
                    observations_skipped_period += 1
                    result.issues.append(
                        {
                            "code": "invalid_period",
                            "severity": "warning",
                            "concept": concept_key,
                            "detail": f"observation without a usable period: {observation!r}"[:400],
                        }
                    )
                    continue
                if observation.get("val") is None:
                    observations_skipped_period += 1
                    continue
                try:
                    value = decimal_from_json(observation.get("val"))
                except ParseError as exc:
                    result.issues.append(
                        {"code": "unparsable_value", "severity": "error", "concept": concept_key, "detail": str(exc)}
                    )
                    observations_skipped_period += 1
                    continue

                accession = str(observation.get("accn") or "") or None
                form = str(observation.get("form") or "") or None
                filing = filing_index.get(accession) if accession else None
                availability, precision = _availability_for(observation, filing)

                revision_kind = RevisionKind.ORIGINAL
                if form and form.strip().upper().endswith("/A"):
                    revision_kind = RevisionKind.AMENDMENT

                derivation_kind = DerivationKind.SOURCE_OBSERVATION
                derivation_rule = None
                lineage: dict[str, Any] | None = None
                quality = Quality.VERIFIED
                limitations = None
                if concept.sign_policy == "magnitude_outflow":
                    if value < 0:
                        quality = Quality.SUSPECT
                        limitations = (
                            f"{concept_key} was reported as a negative number ({value}); Atlas stores the "
                            "reported sign and flags it rather than flipping it silently"
                        )
                        result.issues.append(
                            {
                                "code": "negative_outflow_value",
                                "severity": "warning",
                                "concept": concept_key,
                                "accession": accession,
                                "detail": limitations,
                            }
                        )
                    derivation_kind = DerivationKind.NORMALIZED_SOURCE_OBSERVATION
                    derivation_rule = NORMALIZE_MAGNITUDE_OUTFLOW_RULE
                    lineage = {
                        "rule": NORMALIZE_MAGNITUDE_OUTFLOW_RULE,
                        "description": "concept defined as a positive outflow magnitude; source reported positive",
                        "steps": [
                            lineage_step(
                                "assert_positive_outflow_magnitude",
                                detail=f"{concept_key} kept at reported value {canonical_decimal(value)}",
                                rule=NORMALIZE_MAGNITUDE_OUTFLOW_RULE,
                            )
                        ],
                    }

                try:
                    record = EvidenceRecord.build(
                        entity_id=issuer_id,
                        entity_kind="issuer",
                        concept=concept_key,
                        source_id=source_id,
                        unit=parsed_unit,
                        availability=availability,
                        period=period,
                        value=value,
                        revision_kind=revision_kind,
                        derivation_kind=derivation_kind,
                        derivation_rule=derivation_rule,
                        lineage=lineage,
                        quality=quality,
                        verification=Verification.SOURCE_PRIMARY,
                        source_url=source_url,
                        source_dataset="sec_companyfacts",
                        source_dataset_version=payload.get("version"),
                        taxonomy=resolution.namespace,
                        source_concept=resolution.tag,
                        accession_number=accession,
                        form_type=form,
                        accepted_at=filing.acceptance_datetime if filing else None,
                        filed_date=observation.get("filed") or (filing.filed_date if filing else None),
                        raw_doc_id=raw_doc_id,
                        observed_at=observed,
                        limitations=limitations,
                    )
                except Exception as exc:  # noqa: BLE001 - record-level rejection is reported
                    result.issues.append(
                        {"code": "record_rejected", "severity": "error", "concept": concept_key, "detail": str(exc)}
                    )
                    continue

                key = (
                    concept_key,
                    parsed_unit.raw,
                    period.start.isoformat() if period.start else "",
                    period.end.isoformat(),
                    accession or "",
                )
                previous = dedupe.get(key)
                if previous is not None:
                    if previous.value_numeric != record.value_numeric:
                        conflicting.setdefault(key, set()).update(
                            {previous.value_numeric or "", record.value_numeric or ""}
                        )
                    duplicates_removed += 1
                    continue
                dedupe[key] = record
                observations_used += 1

    # Same filing, same concept, same period, same unit, different values: a genuine
    # internal contradiction. Flag every participating record as suspect.
    contradicted_ids: set[str] = set()
    for key, values in conflicting.items():
        contradicted_ids.add(key[0] + "|" + key[4])
        result.issues.append(
            {
                "code": "conflicting_values_same_filing",
                "severity": "error",
                "concept": key[0],
                "accession": key[4],
                "detail": f"filing asserts multiple values for the same period and unit: {sorted(values)}",
            }
        )

    records: list[EvidenceRecord] = []
    for key, record in dedupe.items():
        if key[4] and f"{key[0]}|{key[4]}" in contradicted_ids:
            record.quality = Quality.SUSPECT.value
            record.limitations = "filing asserts conflicting values for this period; treated as suspect"
        records.append(record)

    # A concept reported in more than one currency is not an error - foreign private
    # issuers legitimately do this - but the currencies must never be combined. Each
    # currency is stored as its own fact and the situation is reported.
    multi_currency = {
        concept_key: sorted(currencies)
        for concept_key, currencies in currencies_by_concept.items()
        if len(currencies) > 1
    }
    for concept_key, currencies in multi_currency.items():
        result.issues.append(
            {
                "code": "multi_currency_concept",
                "severity": "warning",
                "concept": concept_key,
                "detail": (
                    f"{concept_key} is reported in multiple currencies {currencies}; Atlas stores them as "
                    "separate facts and never converts or combines them"
                ),
            }
        )

    result.records = records
    unmapped = sorted(f"{ns}:{tag}" for ns, tag in available if (ns, tag) not in mapped_tags)
    result.unmapped_tags = unmapped
    result.stats = {
        "tags_available": len(available),
        "tags_mapped": len(mapped_tags),
        "concepts_covered": sorted(concepts_covered),
        "observations_total": observations_total,
        "observations_used": observations_used,
        "observations_deduplicated": duplicates_removed,
        "observations_skipped_unit_mismatch": observations_skipped_units,
        "observations_skipped_invalid_period": observations_skipped_period,
        "unmapped_tags": len(unmapped),
        "multi_currency_concepts": multi_currency,
        "availability_exact": sum(1 for r in records if r.availability_precision == "exact"),
        "availability_date": sum(1 for r in records if r.availability_precision == "date"),
        "availability_unknown": sum(1 for r in records if r.availability_precision == "unknown"),
    }
    return result
