"""Independent reconciliation of stored facts against the original SEC payload.

The Sri Lankan test of an ingestion pipeline is not "did it run" but "does every stored
number appear in the source, unchanged, with the period the source gave it". That cannot
be answered by calling the parser again: a shared bug would agree with itself.

This module therefore re-derives the expected observation set from the raw
``companyfacts`` document with its **own** walk of the payload — its own tag resolution
over the registry, its own decimal conversion, its own period extraction — and then
compares that set against what is actually in the ``evidence`` table.

Checks performed per concept/unit/period/accession:

* value equality with the source document (exact ``Decimal`` comparison);
* presence in both directions (nothing dropped, nothing invented);
* reporting period and fiscal period agreement;
* duration/instant selection and start-date presence;
* amendment marking (``/A`` form) and amendment availability precision;
* availability evidence: exact timestamps must equal the filing's acceptance time, and
  date-precision records must sit at end-of-day UTC of the filed date;
* filing ``period_of_report`` cross-check (reported as a warning, because the cover-page
  report date and the XBRL period end are not guaranteed to be the same field);
* duplicate stored assertions for one source observation.

Severity contract matches :mod:`atlas.validation`: ``error`` means the stored dataset
disagrees with the source or is internally impossible; ``warning`` means legal but worth
inspecting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .core.concepts import CONCEPTS
from .core.ids import issuer_id_for_cik, normalize_cik
from .core.temporal import parse_date
from .core.units import parse_unit
from .storage.db import Database

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

#: Forms whose cover-page report date is expected to match the XBRL period end.
_PERIODIC_FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F"})


@dataclass(slots=True)
class ReconcileFinding:
    code: str
    severity: str
    concept: str | None
    unit: str | None
    period_end: str | None
    accession: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "concept": self.concept,
            "unit": self.unit,
            "period_end": self.period_end,
            "accession": self.accession,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ReconcileReport:
    cik: str
    entity_id: str
    expected_observations: int = 0
    stored_source_facts: int = 0
    matched: int = 0
    mismatched_values: int = 0
    missing_from_store: int = 0
    unexpected_in_store: int = 0
    duplicate_keys: int = 0
    availability_issues: int = 0
    period_issues: int = 0
    amendment_issues: int = 0
    findings: list[ReconcileFinding] = field(default_factory=list)
    concepts_checked: list[str] = field(default_factory=list)

    def add(
        self,
        code: str,
        severity: str,
        *,
        concept: str | None = None,
        unit: str | None = None,
        period_end: str | None = None,
        accession: str | None = None,
        detail: str,
    ) -> None:
        self.findings.append(
            ReconcileFinding(
                code=code,
                severity=severity,
                concept=concept,
                unit=unit,
                period_end=period_end,
                accession=accession,
                detail=detail,
            )
        )

    @property
    def errors(self) -> list[ReconcileFinding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[ReconcileFinding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def coverage(self) -> str:
        if not self.expected_observations:
            return "no mappable observations in source"
        return f"{self.matched}/{self.expected_observations} source observations verified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "entity_id": self.entity_id,
            "ok": self.ok,
            "coverage": self.coverage,
            "expected_observations": self.expected_observations,
            "stored_source_facts": self.stored_source_facts,
            "matched": self.matched,
            "mismatched_values": self.mismatched_values,
            "missing_from_store": self.missing_from_store,
            "unexpected_in_store": self.unexpected_in_store,
            "duplicate_keys": self.duplicate_keys,
            "availability_issues": self.availability_issues,
            "period_issues": self.period_issues,
            "amendment_issues": self.amendment_issues,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "concepts_checked": self.concepts_checked,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass(slots=True)
class _Expected:
    concept: str
    unit: str
    period_start: str
    period_end: str
    accession: str
    value: Decimal
    form: str
    filed: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    period_type: str


def _expected_observations(payload: Mapping[str, Any], report: ReconcileReport) -> dict[tuple, _Expected]:
    """Re-derive the expected fact set from the raw payload, independently of the parser."""
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        report.add("source_payload_missing_facts", SEVERITY_ERROR, detail="payload has no 'facts' object")
        return {}
    expected: dict[tuple, _Expected] = {}
    for concept_key, concept in CONCEPTS.items():
        # An issuer can migrate from one XBRL element to another between years, so the
        # parser resolves a tag per reported period instead of once for the whole
        # history. The independent expectation set has to walk every source tag too and
        # apply the registry's precedence per source observation; picking a single tag
        # here would silently disagree with the parser about the other years.
        candidates = [
            (priority, namespace, tag)
            for priority, (namespace, tag) in enumerate(concept.source_tags)
            if isinstance(facts.get(namespace), Mapping) and tag in facts[namespace]
        ]
        if not candidates:
            continue
        report.concepts_checked.append(concept_key)
        selected: dict[tuple, tuple[int, _Expected]] = {}
        for priority, namespace, tag in candidates:
            units = facts[namespace][tag].get("units") or {}
            if not isinstance(units, Mapping):
                continue
            asserted: dict[tuple, _Expected] = {}
            for unit_raw, observations in units.items():
                try:
                    unit = parse_unit(unit_raw)
                except Exception:  # noqa: BLE001 - unparseable unit is not a fact Atlas can use
                    report.add(
                        "unparsable_source_unit",
                        SEVERITY_WARNING,
                        concept=concept_key,
                        unit=str(unit_raw),
                        detail=f"source unit {unit_raw!r} cannot be parsed",
                    )
                    continue
                if unit.kind is not concept.unit_kind:
                    # A different unit *kind* is legitimately not mapped; the parser reports
                    # it too. This is not a disagreement about a stored value.
                    continue
                for observation in observations or []:
                    if not isinstance(observation, Mapping):
                        continue
                    end = observation.get("end")
                    raw_value = observation.get("val")
                    if not end or raw_value is None:
                        continue
                    start = observation.get("start") or ""
                    accession = str(observation.get("accn") or "")
                    try:
                        value = Decimal(str(raw_value))
                    except (InvalidOperation, ValueError):
                        report.add(
                            "unparsable_source_value",
                            SEVERITY_ERROR,
                            concept=concept_key,
                            unit=unit.raw,
                            period_end=str(end),
                            accession=accession,
                            detail=f"source value {raw_value!r} is not a decimal",
                        )
                        continue
                    key = (concept_key, unit.raw, start, str(end), accession)
                    if key in asserted:
                        existing = asserted[key]
                        if existing.value != value:
                            report.add(
                                "source_asserts_two_values",
                                SEVERITY_ERROR,
                                concept=concept_key,
                                unit=unit.raw,
                                period_end=str(end),
                                accession=accession,
                                detail=(
                                    f"source document asserts {existing.value} and {value} for the same "
                                    "accession, period and unit"
                                ),
                            )
                        continue
                    expectation = _Expected(
                        concept=concept_key,
                        unit=unit.raw,
                        period_start=str(start),
                        period_end=str(end),
                        accession=accession,
                        value=value,
                        form=str(observation.get("form") or ""),
                        filed=str(observation.get("filed")) if observation.get("filed") else None,
                        fiscal_year=int(observation["fy"]) if observation.get("fy") is not None else None,
                        fiscal_period=str(observation["fp"]) if observation.get("fp") else None,
                        period_type="duration" if start else "instant",
                    )
                    asserted[key] = expectation
                    existing = selected.get(key)
                    if existing is None or priority < existing[0]:
                        selected[key] = (priority, expectation)
        for _, expectation in selected.values():
            expected[
                (
                    expectation.concept,
                    expectation.unit,
                    expectation.period_start,
                    expectation.period_end,
                    expectation.accession,
                )
            ] = expectation
    report.expected_observations = len(expected)
    return expected


def reconcile_companyfacts(
    db: Database,
    payload: Mapping[str, Any],
    *,
    cik: str | int,
) -> ReconcileReport:
    """Compare stored facts for ``cik`` with the values in ``payload``."""
    normalized = normalize_cik(cik)
    entity_id = issuer_id_for_cik(normalized)
    report = ReconcileReport(cik=normalized, entity_id=entity_id)
    expected = _expected_observations(payload, report)

    rows = db.query(
        "SELECT evidence_id, concept, unit, COALESCE(period_start,'') AS ps, period_end, "
        "accession_number, value_numeric, value_text, availability_time, availability_precision, "
        "revision_kind, filed_date, acceptance_datetime, fiscal_year, fiscal_period, quality "
        "FROM evidence WHERE entity_id = ? AND record_kind = 'financial_fact' "
        "AND derivation_kind IN ('source_observation','normalized_source_observation')",
        (entity_id,),
    )
    report.stored_source_facts = len(rows)
    stored: dict[tuple, list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (
            row["concept"],
            row["unit"],
            row["ps"],
            row["period_end"],
            row["accession_number"] or "",
        )
        stored.setdefault(key, []).append(row)

    filings = {
        row["accession_number"]: {key: row[key] for key in row.keys()}
        for row in db.query(
            "SELECT accession_number, form_type, filed_date, acceptance_datetime, period_of_report "
            "FROM filing WHERE cik = ?",
            (normalized,),
        )
    }

    for key, expectation in expected.items():
        matches = stored.get(key)
        if not matches:
            report.missing_from_store += 1
            report.add(
                "source_observation_not_stored",
                SEVERITY_ERROR,
                concept=expectation.concept,
                unit=expectation.unit,
                period_end=expectation.period_end,
                accession=expectation.accession,
                detail="source observation has no corresponding stored evidence record",
            )
            continue
        if len(matches) > 1:
            report.duplicate_keys += 1
            report.add(
                "duplicate_stored_observations",
                SEVERITY_ERROR,
                concept=expectation.concept,
                unit=expectation.unit,
                period_end=expectation.period_end,
                accession=expectation.accession,
                detail=f"{len(matches)} stored records claim the same source observation",
            )
        row = matches[0]
        stored_value = row["value_numeric"] if row["value_numeric"] is not None else row["value_text"]
        try:
            stored_decimal = Decimal(str(stored_value))
        except (InvalidOperation, ValueError):
            stored_decimal = None
        if stored_decimal != expectation.value:
            report.mismatched_values += 1
            report.add(
                "stored_value_differs_from_source",
                SEVERITY_ERROR,
                concept=expectation.concept,
                unit=expectation.unit,
                period_end=expectation.period_end,
                accession=expectation.accession,
                detail=f"source {expectation.value} vs stored {stored_value}",
            )
            continue
        report.matched += 1

        # Period semantics: the source's own start/end/fiscal metadata must survive.
        if expectation.period_type == "duration" and not row["ps"]:
            report.period_issues += 1
            report.add(
                "duration_without_period_start",
                SEVERITY_ERROR,
                concept=expectation.concept,
                period_end=expectation.period_end,
                accession=expectation.accession,
                detail="source observation is a duration but the stored fact has no start date",
            )
        if row["fiscal_year"] != expectation.fiscal_year or (row["fiscal_period"] or None) != expectation.fiscal_period:
            report.add(
                "fiscal_period_differs_from_source",
                SEVERITY_WARNING,
                concept=expectation.concept,
                period_end=expectation.period_end,
                accession=expectation.accession,
                detail=(
                    f"source fy/fp {expectation.fiscal_year}/{expectation.fiscal_period} vs stored "
                    f"{row['fiscal_year']}/{row['fiscal_period']}"
                ),
            )

        # Amendments must be marked as such.
        filing = filings.get(expectation.accession)
        if expectation.form.upper().endswith("/A"):
            if row["revision_kind"] != "amendment":
                report.amendment_issues += 1
                report.add(
                    "amendment_not_marked",
                    SEVERITY_ERROR,
                    concept=expectation.concept,
                    period_end=expectation.period_end,
                    accession=expectation.accession,
                    detail=f"source form {expectation.form} stored as revision_kind={row['revision_kind']}",
                )
            acceptance = (filing or {}).get("acceptance_datetime")
            if acceptance and row["availability_precision"] != "exact":
                report.availability_issues += 1
                report.add(
                    "amendment_availability_not_exact",
                    SEVERITY_ERROR,
                    concept=expectation.concept,
                    period_end=expectation.period_end,
                    accession=expectation.accession,
                    detail=(
                        "filing acceptance timestamp is known but the fact's availability is "
                        f"{row['availability_precision']}"
                    ),
                )

        # Availability must be evidenced by the filing we hold.
        if row["availability_precision"] == "unknown":
            report.availability_issues += 1
            report.add(
                "availability_unknown_but_filing_known",
                SEVERITY_ERROR,
                concept=expectation.concept,
                period_end=expectation.period_end,
                accession=expectation.accession,
                detail="fact has no evidenced availability although a filing with a filed date is stored",
            )
        elif filing is not None:
            if row["availability_precision"] == "exact" and filing["acceptance_datetime"]:
                if row["availability_time"] != filing["acceptance_datetime"]:
                    report.availability_issues += 1
                    report.add(
                        "exact_availability_differs_from_filing",
                        SEVERITY_ERROR,
                        concept=expectation.concept,
                        period_end=expectation.period_end,
                        accession=expectation.accession,
                        detail=(
                            f"stored {row['availability_time']} vs filing acceptance "
                            f"{filing['acceptance_datetime']}"
                        ),
                    )
            elif row["availability_precision"] == "date":
                filed = row["filed_date"] or filing["filed_date"]
                if filed and row["availability_time"]:
                    expected_instant = _end_of_day(filed)
                    if row["availability_time"] != expected_instant:
                        report.availability_issues += 1
                        report.add(
                            "date_availability_not_end_of_day",
                            SEVERITY_ERROR,
                            concept=expectation.concept,
                            period_end=expectation.period_end,
                            accession=expectation.accession,
                            detail=(
                                f"stored {row['availability_time']} but date precision requires "
                                f"{expected_instant}"
                            ),
                        )

            # Cover-page report date is a separate field; disagreement is worth seeing
            # but is not proof of an error.
            if filing["period_of_report"] and filing["form_type"] in _PERIODIC_FORMS:
                if row["period_end"] != filing["period_of_report"]:
                    report.add(
                        "period_end_differs_from_filing_report_date",
                        SEVERITY_WARNING,
                        concept=expectation.concept,
                        period_end=expectation.period_end,
                        accession=expectation.accession,
                        detail=(
                            f"XBRL period end {row['period_end']} vs filing report date "
                            f"{filing['period_of_report']}"
                        ),
                    )

    for key, matches in stored.items():
        if key in expected:
            continue
        report.unexpected_in_store += 1
        row = matches[0]
        report.add(
            "stored_fact_not_in_source",
            SEVERITY_ERROR,
            concept=row["concept"],
            unit=row["unit"],
            period_end=row["period_end"],
            accession=row["accession_number"],
            detail="stored source fact has no matching observation in the source document",
        )
    return report


def _end_of_day(value: str) -> str:
    day = parse_date(value)
    return datetime(day.year, day.month, day.day, 23, 59, 59).strftime("%Y-%m-%dT%H:%M:%SZ")
