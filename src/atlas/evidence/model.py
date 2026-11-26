"""Evidence record model: the immutable unit of recorded financial information.

An evidence record is one *assertion*, by one source document, about one concept,
for one entity, over one period, expressed in one unit. Records are append-only:
restatements and corrections add records, they never mutate earlier ones. Everything
a researcher needs to audit a number is stored on the record or reachable from it:

* what was asserted (``concept``, ``value_numeric``, ``unit``, period)
* where it came from (``source_id``, ``source_url``, ``accession_number``, ``raw_doc_id``)
* the untouched original element name (``taxonomy`` + ``source_concept``)
* when it was filed / accepted / publicly available / observed by Atlas
* whether the number is direct, normalized, derived or estimated (``derivation_kind``)
* how it relates to earlier or later versions (``revision_kind``, ``supersedes``)

The record deliberately does **not** carry a "current value" flag: currency of a fact
is a function of the query's time semantics, not a property of the record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ..core.concepts import CONCEPTS, DERIVATIONS
from ..core.errors import ValidationError
from ..core.ids import evidence_id as make_evidence_id
from ..core.temporal import (
    Availability,
    AvailabilityPrecision,
    PeriodType,
    ReportingPeriod,
    iso,
    iso_date,
    to_utc,
    utcnow,
)
from ..core.units import Unit, UnitKind, canonical_decimal, parse_decimal, parse_unit


class RecordKind(str, Enum):
    FINANCIAL_FACT = "financial_fact"
    ECONOMIC_OBSERVATION = "economic_observation"
    MARKET_METADATA = "market_metadata"


class EntityKind(str, Enum):
    ISSUER = "issuer"
    SECURITY = "security"


class RevisionKind(str, Enum):
    ORIGINAL = "original"
    AMENDMENT = "amendment"
    RESTATEMENT = "restatement"
    CORRECTION = "correction"


class DerivationKind(str, Enum):
    SOURCE_OBSERVATION = "source_observation"
    NORMALIZED_SOURCE_OBSERVATION = "normalized_source_observation"
    DERIVED_CALCULATION = "derived_calculation"
    ESTIMATE = "estimate"


class Quality(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    SUSPECT = "suspect"
    QUARANTINED = "quarantined"


class Verification(str, Enum):
    SOURCE_PRIMARY = "source_primary"
    SOURCE_SECONDARY = "source_secondary"
    CROSS_VALIDATED = "cross_validated"
    UNCHECKED = "unchecked"


#: Authority tier used by the selection policy. A direct observation always outranks
#: a derived value for the same concept and period, even if the derived value is newer.
BASIS_TIER: dict[str, int] = {
    DerivationKind.SOURCE_OBSERVATION.value: 0,
    DerivationKind.NORMALIZED_SOURCE_OBSERVATION.value: 0,
    DerivationKind.DERIVED_CALCULATION.value: 2,
    DerivationKind.ESTIMATE.value: 3,
}

_QUALITY_RANK = {
    Quality.VERIFIED.value: 0,
    Quality.UNVERIFIED.value: 1,
    Quality.SUSPECT.value: 2,
    Quality.QUARANTINED.value: 3,
}

_VERIFICATION_RANK = {
    Verification.CROSS_VALIDATED.value: 0,
    Verification.SOURCE_PRIMARY.value: 1,
    Verification.SOURCE_SECONDARY.value: 2,
    Verification.UNCHECKED.value: 3,
}


def basis_tier(derivation_kind: str) -> int:
    return BASIS_TIER.get(str(derivation_kind), 1)


#: Insert order of evidence columns; must match the schema in migrations.py.
COLUMNS: tuple[str, ...] = (
    "evidence_id",
    "record_kind",
    "entity_id",
    "entity_kind",
    "concept",
    "source_id",
    "source_url",
    "source_dataset",
    "source_dataset_version",
    "taxonomy",
    "source_concept",
    "value_numeric",
    "value_text",
    "unit",
    "unit_kind",
    "currency",
    "period_start",
    "period_end",
    "period_type",
    "fiscal_year",
    "fiscal_period",
    "valid_from",
    "valid_to",
    "availability_time",
    "availability_precision",
    "availability_basis",
    "filed_date",
    "acceptance_datetime",
    "observed_at",
    "ingest_seq",
    "content_hash",
    "original_record_hash",
    "raw_doc_id",
    "accession_number",
    "form_type",
    "revision_kind",
    "supersedes",
    "derivation_kind",
    "derivation_rule",
    "transformation_lineage",
    "quality",
    "verification",
    "limitations",
)


@dataclass(slots=True)
class EvidenceRecord:
    """One immutable recorded assertion."""

    evidence_id: str
    record_kind: str
    entity_id: str
    entity_kind: str
    concept: str
    source_id: str
    unit: str
    unit_kind: str
    availability_precision: str
    observed_at: str
    content_hash: str
    revision_kind: str
    derivation_kind: str
    quality: str
    verification: str
    value_numeric: str | None = None
    value_text: str | None = None
    currency: str | None = None
    source_url: str | None = None
    source_dataset: str | None = None
    source_dataset_version: str | None = None
    taxonomy: str | None = None
    source_concept: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    period_type: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    availability_time: str | None = None
    availability_basis: str | None = None
    filed_date: str | None = None
    acceptance_datetime: str | None = None
    original_record_hash: str | None = None
    raw_doc_id: str | None = None
    accession_number: str | None = None
    form_type: str | None = None
    supersedes: str | None = None
    derivation_rule: str | None = None
    transformation_lineage: str | None = None
    limitations: str | None = None
    ingest_seq: int = 0

    # ------------------------------------------------------------- accessors
    @property
    def availability_known(self) -> bool:
        return self.availability_time is not None and self.availability_precision != AvailabilityPrecision.UNKNOWN.value

    @property
    def decimal_value(self):
        if self.value_numeric is None:
            return None
        return parse_decimal(self.value_numeric)

    @property
    def lineage(self) -> dict[str, Any]:
        if not self.transformation_lineage:
            return {}
        try:
            return json.loads(self.transformation_lineage)
        except json.JSONDecodeError:  # pragma: no cover - stored data guard
            return {"unparsable": self.transformation_lineage}

    @property
    def tier(self) -> int:
        return basis_tier(self.derivation_kind)

    @property
    def concept_label(self) -> str:
        concept = CONCEPTS.get(self.concept)
        if concept is not None:
            return concept.label
        derivation = DERIVATIONS.get(self.concept)
        if derivation is not None:
            return derivation.label
        return self.concept

    def to_row(self) -> tuple[Any, ...]:
        return tuple(getattr(self, column) for column in COLUMNS)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "EvidenceRecord":
        values = {column: row[column] for column in COLUMNS}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        payload = {column: getattr(self, column) for column in COLUMNS}
        payload["availability_known"] = self.availability_known
        payload["basis_tier"] = self.tier
        payload["concept_label"] = self.concept_label
        return payload

    # -------------------------------------------------------------- factories
    @classmethod
    def build(
        cls,
        *,
        entity_id: str,
        entity_kind: str | EntityKind,
        concept: str,
        source_id: str,
        unit: Unit | str,
        availability: Availability,
        period: ReportingPeriod | None = None,
        value: Any | None = None,
        value_text: str | None = None,
        record_kind: str | RecordKind = RecordKind.FINANCIAL_FACT,
        revision_kind: str | RevisionKind = RevisionKind.ORIGINAL,
        derivation_kind: str | DerivationKind = DerivationKind.SOURCE_OBSERVATION,
        derivation_rule: str | None = None,
        lineage: dict[str, Any] | None = None,
        quality: str | Quality = Quality.UNVERIFIED,
        verification: str | Verification = Verification.UNCHECKED,
        source_url: str | None = None,
        source_dataset: str | None = None,
        source_dataset_version: str | None = None,
        taxonomy: str | None = None,
        source_concept: str | None = None,
        accession_number: str | None = None,
        form_type: str | None = None,
        accepted_at: Any | None = None,
        filed_date: Any | None = None,
        raw_doc_id: str | None = None,
        observed_at: Any | None = None,
        limitations: str | None = None,
        valid_from: Any | None = None,
        valid_to: Any | None = None,
        original_record_hash: str | None = None,
        evidence_override: str | None = None,
    ) -> "EvidenceRecord":
        """Construct and validate a record, deriving its stable id and content hash."""
        if isinstance(entity_kind, EntityKind):
            entity_kind_value = entity_kind.value
        else:
            entity_kind_value = str(entity_kind)
        if entity_kind_value not in {k.value for k in EntityKind}:
            raise ValidationError("invalid entity kind", entity_kind=entity_kind_value)
        if not entity_id:
            raise ValidationError("entity_id is required")
        if not concept:
            raise ValidationError("concept is required")
        if not source_id:
            raise ValidationError("source_id is required")

        parsed_unit = unit if isinstance(unit, Unit) else parse_unit(unit)
        record_kind_value = record_kind.value if isinstance(record_kind, RecordKind) else str(record_kind)
        revision_kind_value = revision_kind.value if isinstance(revision_kind, RevisionKind) else str(revision_kind)
        derivation_kind_value = (
            derivation_kind.value if isinstance(derivation_kind, DerivationKind) else str(derivation_kind)
        )
        quality_value = quality.value if isinstance(quality, Quality) else str(quality)
        verification_value = verification.value if isinstance(verification, Verification) else str(verification)

        if value is None and value_text is None:
            raise ValidationError("an evidence record must assert a value", concept=concept)
        value_numeric = canonical_decimal(value) if value is not None else None
        if value_text is not None and value is not None:
            raise ValidationError("record carries both a numeric and a textual value", concept=concept)

        if not availability.known:
            availability_time = None
            precision_value = AvailabilityPrecision.UNKNOWN.value
        else:
            assert availability.time is not None
            availability_time = iso(availability.time)
            precision_value = availability.precision.value

        period_start = iso_date(period.start) if period and period.start else None
        period_end = iso_date(period.end) if period else None
        period_type = None
        fiscal_year = None
        fiscal_period = None
        if period is not None:
            period_type = (period.period_type.value if isinstance(period.period_type, PeriodType) else str(period.period_type))
            fiscal_year = period.fiscal_year
            fiscal_period = period.fiscal_period

        if record_kind_value == RecordKind.FINANCIAL_FACT.value and period_end is None:
            raise ValidationError("financial facts require a reporting period", concept=concept)

        observed = iso(observed_at) if observed_at is not None else iso(utcnow())
        if parsed_unit.kind is UnitKind.MONETARY and not parsed_unit.currency:
            raise ValidationError("monetary evidence requires a currency", unit=parsed_unit.raw)

        identity = {
            "source_id": source_id,
            "entity_id": entity_id,
            "entity_kind": entity_kind_value,
            "concept": concept,
            "accession_number": accession_number or "",
            "period_start": period_start or "",
            "period_end": period_end or "",
            "unit": parsed_unit.raw,
            "value_numeric": value_numeric or "",
            "value_text": value_text or "",
            "availability_time": availability_time or "",
            "revision_kind": revision_kind_value,
            "derivation_kind": derivation_kind_value,
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
        generated_id = make_evidence_id(
            source_id=source_id,
            entity_id=entity_id,
            concept=concept,
            accession_number=accession_number,
            period_start=period_start,
            period_end=period_end,
            unit=parsed_unit.raw,
            value_numeric=value_numeric,
            availability_time=availability_time,
            revision_kind=revision_kind_value,
        )

        return cls(
            evidence_id=evidence_override or generated_id,
            record_kind=record_kind_value,
            entity_id=entity_id,
            entity_kind=entity_kind_value,
            concept=concept,
            source_id=source_id,
            value_numeric=value_numeric,
            value_text=value_text,
            unit=parsed_unit.raw,
            unit_kind=parsed_unit.kind.value,
            currency=parsed_unit.currency,
            source_url=source_url,
            source_dataset=source_dataset,
            source_dataset_version=source_dataset_version,
            taxonomy=taxonomy,
            source_concept=source_concept,
            period_start=period_start,
            period_end=period_end,
            period_type=period_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            valid_from=iso_date(valid_from) if valid_from is not None else None,
            valid_to=iso_date(valid_to) if valid_to is not None else None,
            availability_time=availability_time,
            availability_precision=precision_value,
            availability_basis=availability.basis,
            filed_date=iso_date(filed_date) if filed_date is not None else None,
            acceptance_datetime=iso(accepted_at) if accepted_at is not None else None,
            observed_at=observed,
            content_hash=digest,
            original_record_hash=original_record_hash,
            raw_doc_id=raw_doc_id,
            accession_number=accession_number,
            form_type=form_type,
            revision_kind=revision_kind_value,
            derivation_kind=derivation_kind_value,
            derivation_rule=derivation_rule,
            transformation_lineage=json.dumps(lineage, sort_keys=True) if lineage else None,
            quality=quality_value,
            verification=verification_value,
            limitations=limitations,
        )

    # --------------------------------------------------------------- helpers
    def lineage_key(self) -> tuple[str, ...]:
        """Identity of the *economic fact* this record speaks about.

        Two records sharing a lineage key are versions of the same fact and may
        supersede each other. The tier is part of the key so a derived value never
        supersedes an observed one.
        """
        return (
            self.entity_id,
            self.record_kind,
            self.concept,
            self.unit,
            self.period_start or "",
            self.period_end or "",
            str(self.tier),
        )

    def ordering_key(self) -> tuple[str, str, int, str]:
        """Deterministic ordering: availability, observation, ingestion order, id."""
        return (self.availability_time or "", self.observed_at or "", self.ingest_seq, self.evidence_id)

    def quality_rank(self) -> tuple[int, int]:
        return (_QUALITY_RANK.get(self.quality, 9), _VERIFICATION_RANK.get(self.verification, 9))

    def same_value(self, other: "EvidenceRecord") -> bool:
        return self.value_numeric == other.value_numeric and self.value_text == other.value_text

    def is_derived(self) -> bool:
        return self.derivation_kind == DerivationKind.DERIVED_CALCULATION.value


def lineage_step(
    step: str,
    *,
    detail: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    rule: str | None = None,
) -> dict[str, Any]:
    """Build one inspectable transformation step for ``transformation_lineage``."""
    payload: dict[str, Any] = {"step": step}
    if detail:
        payload["detail"] = detail
    if rule:
        payload["rule"] = rule
    if inputs is not None:
        payload["inputs"] = inputs
    return payload
