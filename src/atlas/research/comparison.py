"""Cross-company comparison of verified financial figures.

A comparison answers one question honestly: are these numbers comparable? Each company's
figure is resolved by the same registered concept resolver over the same period, and the
cell identity travels with the value. Nothing is normalised to make the table look tidy: a
currency, unit, scale, entity-scope or coverage difference is reported as a finding, and a
blocking finding marks the whole comparison ``comparable: false``.

That is the point of the feature. A comparison that silently divides a consolidated total by
a parent-only figure is worse than no comparison, because it looks like evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..core.errors import AtlasError, ValidationError
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from .filing_evidence import cutoff_instant
from .financial_concepts import CONCEPTS, ConceptResolver, bind
from .knowledge import KnowledgeEngine

COMPARISON_SCHEMA = "atlas.company_comparison.v1"

#: Findings that make the figures non-comparable. Scale is blocking, not cosmetic: a cell's
#: value is the number as reported and the scale travels beside it, so 34,229 in thousands and
#: 34,229 in millions are the same digits for a thousand times different money.
BLOCKING_FINDINGS = frozenset({
    "currency_mismatch", "unit_mismatch", "entity_scope_mismatch", "scale_mismatch",
    "period_mismatch", "insufficient_coverage",
})


def availability(precision: str | None, availability_time: str | None) -> dict[str, Any]:
    """Availability semantics, identical to the single-answer surface.

    Kept here rather than imported from the HTTP layer so the research package has no
    dependency on the terminal package.
    """
    verified = precision in {"exact", "date"}
    return {
        "availability_time": availability_time,
        "availability_precision": precision,
        "is_estimated": not verified,
        "note": (
            "observed availability with the stated precision"
            if verified else
            "modelled upper bound on public release, not an observed instant; it may exclude "
            "evidence for a cutoff but must never be read as verified historical availability"
        ),
    }


def compatibility_findings(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report every way the resolved rows differ from each other."""
    resolved = [row for row in rows if row.get("status") == "resolved"]
    findings: list[dict[str, Any]] = []

    def note(code: str, message: str, **extra: Any) -> None:
        findings.append({
            "code": code,
            "severity": "blocking" if code in BLOCKING_FINDINGS else "disclosed",
            "message": message,
            **extra,
        })

    if len(resolved) < 2:
        note("insufficient_coverage",
             "Fewer than two companies resolved this concept for the period, so there is "
             "nothing to compare.",
             resolved=[row.get("issuer_id") for row in resolved])
    for field_name, code, label in (
        ("currency", "currency_mismatch", "currency"),
        ("entity_scope", "entity_scope_mismatch", "consolidation scope"),
        ("scale", "scale_mismatch", "reported scale"),
        ("statement_family", "statement_mismatch", "statement family"),
    ):
        values = sorted({str(row[field_name]) for row in resolved if row.get(field_name)})
        if len(values) > 1:
            note(code, f"The figures disagree on {label}: {', '.join(values)}.", values=values)
    periods = sorted({str(row["period"]) for row in resolved if row.get("period")})
    if len(periods) > 1:
        note("period_mismatch", f"The figures cover different periods: {', '.join(periods)}.",
             values=periods)
    refused = [row for row in rows if row.get("status") != "resolved"]
    if refused:
        note("partial_coverage",
             "Some companies have no verified figure for this concept and period; they are "
             "reported as refusals rather than estimated.",
             refused=[{"issuer_id": row.get("issuer_id") or row.get("requested"),
                       "status": row.get("status"), "reason": row.get("reason")}
                      for row in refused])
    return findings


@dataclass(slots=True)
class CompanyComparisonService:
    db: Database
    resolver: ConceptResolver = field(init=False)

    def __post_init__(self) -> None:
        self.resolver = ConceptResolver(KnowledgeEngine(self.db))

    # ------------------------------------------------------------------ resolution
    def _row(self, identifier: str, concept: str, period: str, cutoff: str,
             scope: str) -> dict[str, Any]:
        from ..terminal.read_models import resolve_company

        empty: dict[str, Any] = {
            "value": None, "currency": None, "scale": None, "period": None,
            "entity_scope": None, "statement_family": None, "evidence": None,
            "availability": None,
        }
        try:
            company = resolve_company(self.db, identifier)
        except AtlasError as exc:
            return {
                "requested": identifier, "issuer_id": None, "legal_name": None, "ticker": None,
                "status": "unknown_issuer", "reason": str(exc), **empty,
            }
        header = {
            "requested": identifier,
            "issuer_id": company["issuer_id"],
            "legal_name": company.get("legal_name"),
            "ticker": company.get("ticker"),
        }
        resolution = self.resolver.resolve(company["issuer_id"], concept, period, cutoff,
                                           context=scope)
        if resolution.status != "resolved" or resolution.cell is None:
            return {
                **header, "status": "refused",
                "reason": resolution.reason or resolution.status,
                "candidates": [
                    {"cell_id": item.get("cell_id"), "row_label": item.get("row_label"),
                     "period": item.get("period")}
                    for item in (resolution.candidates or [])[:5]
                ],
                **empty,
            }
        binding = bind(resolution, company["issuer_id"], concept)
        if binding is None:  # pragma: no cover - mirrors the resolved status above
            return {**header, "status": "refused", "reason": "binding_failed", **empty}
        return {
            **header,
            "status": "resolved",
            "reason": None,
            "value": binding.value,
            "currency": binding.currency,
            "scale": binding.scale,
            "period": binding.period,
            "entity_scope": binding.entity_scope,
            "statement_family": binding.statement_family,
            "evidence": {
                "document_id": binding.document_id,
                "accession": binding.accession,
                "table_id": binding.table_id,
                "cell_id": binding.cell_id,
                "row_label": binding.row_label,
                "column_label": binding.column_label,
                "statement_title": binding.statement_title,
                "source_table_sha256": binding.source_table_sha256,
                "rights": binding.rights,
                "rationale": binding.rationale,
            },
            "availability": availability(binding.availability_precision,
                                         binding.availability_time),
        }

    # ------------------------------------------------------------------------ public
    def compare(self, issuers: Iterable[str], *, concepts: Iterable[str], period: str,
                cutoff: str | None = None, scope: str = "consolidated") -> dict[str, Any]:
        company_list = [str(item).strip() for item in issuers if str(item).strip()]
        concept_list = [str(item).strip() for item in concepts if str(item).strip()]
        if len(company_list) < 2:
            raise ValidationError("a comparison needs at least two companies",
                                  given=len(company_list))
        if not concept_list:
            raise ValidationError("a comparison needs at least one concept")
        unsupported = sorted(set(concept_list) - set(CONCEPTS))
        if unsupported:
            raise ValidationError("unsupported concept", unsupported=unsupported,
                                  supported=sorted(CONCEPTS))
        resolved_cutoff = cutoff_instant(cutoff) if cutoff else iso(utcnow())
        if resolved_cutoff is None:  # pragma: no cover - cutoff_instant resolves every date
            raise ValidationError("invalid cutoff", cutoff=cutoff)

        blocks: list[dict[str, Any]] = []
        for concept in concept_list:
            rows = [self._row(identifier, concept, period, resolved_cutoff, scope)
                    for identifier in company_list]
            findings = compatibility_findings(rows)
            blocks.append({
                "concept": concept,
                "statement": CONCEPTS[concept].statement,
                "rows": rows,
                "findings": findings,
                "comparable": not any(item["severity"] == "blocking" for item in findings),
            })
        return {
            "schema": COMPARISON_SCHEMA,
            "period": period,
            "cutoff": resolved_cutoff,
            "scope": scope,
            "concepts": blocks,
            "comparable": all(block["comparable"] for block in blocks),
            "note": (
                "Only issuers stored in this Atlas database are compared; this is not an "
                "industry index, a peer-set average or a valuation opinion. Values are quoted "
                "from verified table cells and keep their evidence ids."
            ),
        }


__all__ = ["CompanyComparisonService", "COMPARISON_SCHEMA", "BLOCKING_FINDINGS",
           "availability", "compatibility_findings"]
