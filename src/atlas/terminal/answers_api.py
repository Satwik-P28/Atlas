"""HTTP surface for financial answers and their certificates.

This is the analyst-facing form of the machinery the research corpus already uses: the
concept resolver picks exactly one verified consolidated cell, the answer engine performs
the typed arithmetic, and ``build_certificate`` packages the result so a third party can
recompute it without calling Atlas.

Nothing here invents an answer. An unresolved or ambiguous concept is a 422 refusal with
the candidates Atlas considered, and the certificate is only built from an answered packet.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.temporal import iso, utcnow
from ..research.certificate import SCHEMA as CERTIFICATE_SCHEMA
from ..research.certificate import build_certificate
from ..research.certificate_verify import verify_payload
from ..research.filing_evidence import cutoff_instant
from ..research.financial_concepts import CONCEPTS, ConceptResolver, bind
from ..research.knowledge import KnowledgeEngine
from ..terminal.read_models import resolve_company


def classify_citation(column_label: Any, period: Any) -> tuple[bool | None, str]:
    """Say whether the parsed column label agrees with the period the resolver chose.

    Filers lay statements out with currency symbols in their own columns (`2026 |  | 2025`),
    so a raw column index can name the wrong year even when the value and the resolved period
    are right. Reporting the disagreement is better than presenting a label the parser cannot
    vouch for: the number keeps its period, and the citation says it is ambiguous.
    """
    label_years = {token for token in re.findall(r"(?:19|20)\d{2}", str(column_label))}
    period_years = {token for token in re.findall(r"(?:19|20)\d{2}", str(period))}
    if not label_years or not period_years:
        return None, "unchecked"
    if label_years & period_years:
        return True, "exact"
    return False, "ambiguous_column_label"


def citation_period_gate(column_label: Any, period: Any) -> tuple[bool | None, str]:
    """Classify the citation and refuse it when the label contradicts the resolved period.

    A number whose cited column names a different year than the period it is bound to is not an
    acceptable answer: the disagreement is evidence that the column mapping is wrong, and the
    document did not resolve it. Such an answer is refused with a typed error rather than
    disclosed and returned, so no certificate can imply a period the source does not support.
    """
    agrees, quality = classify_citation(column_label, period)
    if quality == "ambiguous_column_label":
        raise HTTPException(status_code=422, detail={
            "code": "citation_period_conflict",
            "message": ("the cited column names a different period than the resolved answer; "
                        "the column-to-period mapping could not be established from the "
                        "document"),
            "context": {"column_label": None if column_label is None else str(column_label),
                        "period": None if period is None else str(period)},
        })
    return agrees, quality


class AnswerRequest(BaseModel):
    issuer_id: str = Field(min_length=3, max_length=80)
    concept: str = Field(min_length=2, max_length=60)
    period: str = Field(min_length=4, max_length=20)
    as_of: str | None = Field(default=None, max_length=40)
    scope: Literal["consolidated", "any"] = "consolidated"


class CertificateRequest(AnswerRequest):
    research_question: str | None = Field(default=None, max_length=400)


class VerifyRequest(BaseModel):
    certificate: dict[str, Any]


def _cutoff(value: str | None) -> str:
    if not value:
        return iso(utcnow())
    resolved = cutoff_instant(value)
    if resolved is None:  # pragma: no cover - cutoff_instant always resolves a date
        raise HTTPException(status_code=422, detail={"code": "invalid_cutoff", "message": value})
    return resolved


def _availability(precision: str | None, availability_time: str | None) -> dict[str, Any]:
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


def register_answer_routes(app: Any, get_db: Callable[..., Any]) -> None:
    def _registry() -> dict[str, Any]:
        return {
            "items": [
                {"key": concept.key, "aliases": list(concept.aliases),
                 "statement": concept.statement, "kind": concept.kind,
                 "segment_sensitive": concept.segment_sensitive}
                for concept in sorted(CONCEPTS.values(), key=lambda item: item.key)
            ],
            "count": len(CONCEPTS),
            "policy": "a concept resolves only when exactly one verified consolidated cell "
                      "matches its definition for the requested period",
        }

    @app.get("/api/answers/concepts", tags=["answers"])
    def answer_concepts() -> dict[str, Any]:
        return _registry()

    def _resolve(db: Any, body: AnswerRequest) -> dict[str, Any]:
        engine = KnowledgeEngine(db)
        resolver = ConceptResolver(engine)
        cutoff = _cutoff(body.as_of)
        if body.concept not in CONCEPTS:
            raise HTTPException(status_code=422, detail={
                "code": "unsupported_concept",
                "message": "the concept is not registered",
                "context": {"concept": body.concept, "supported": sorted(CONCEPTS)},
            })
        resolution = resolver.resolve(body.issuer_id, body.concept, body.period, cutoff,
                                      context=body.scope)
        header = {
            "question": {"issuer_id": body.issuer_id, "concept": body.concept,
                         "period": body.period, "as_of": cutoff, "scope": body.scope},
            "resolution": resolution.as_dict(),
            "resolver": {"version": resolution.resolver_version,
                         "xbrl_status": resolution.xbrl_status},
        }
        if resolution.status != "resolved" or resolution.cell is None:
            raise HTTPException(status_code=422, detail={
                "code": "answer_refused",
                "message": "Atlas could not resolve the concept to exactly one verified cell",
                "context": {**header, "reason": resolution.reason or resolution.status,
                            "candidates": resolution.candidates[:5]},
            })
        binding = bind(resolution, body.issuer_id, body.concept)
        if binding is None:  # pragma: no cover - mirrors the resolved status
            raise HTTPException(status_code=422, detail={
                "code": "binding_failed", "message": "resolved cell could not be bound",
            })
        answer = resolver.answers.lookup_bound(binding, cutoff)
        if answer.get("outcome") != "answered":
            raise HTTPException(status_code=422, detail={
                "code": "answer_refused",
                "message": "the bound cell did not produce a verified answer",
                "context": {**header, "reason": answer.get("reason"),
                            "verification": answer.get("verification")},
            })
        label_agrees, citation_quality = citation_period_gate(binding.column_label,
                                                              binding.period)
        evidence = {
            "document_id": binding.document_id, "accession": binding.accession,
            "column_label_agrees_with_period": label_agrees,
            "citation_quality": citation_quality,
            "table_id": binding.table_id, "unit_id": binding.unit_id,
            "cell_id": binding.cell_id, "row": binding.row, "column": binding.column,
            "row_label": binding.row_label, "column_label": binding.column_label,
            "statement_title": binding.statement_title,
            "statement_family": binding.statement_family,
            "entity_scope": binding.entity_scope, "period": binding.period,
            "currency": binding.currency, "scale": binding.scale, "raw": binding.raw,
            "value": binding.value, "source_table_sha256": binding.source_table_sha256,
            "rights": binding.rights, "rationale": binding.rationale,
        }
        return {
            **header,
            "answer": answer,
            "evidence": evidence,
            "availability": _availability(binding.availability_precision,
                                          binding.availability_time),
            "semantics": {
                "verified_but_not_proven_correct": True,
                "note": "the cell is verified against its source table and the arithmetic is "
                        "checked; the economic interpretation remains the analyst's judgement",
            },
        }

    @app.post("/api/answers/resolve", tags=["answers"])
    def answer_resolve(body: AnswerRequest, db: Any = Depends(get_db)) -> dict[str, Any]:
        return _resolve(db, body)

    @app.post("/api/answers/certificate", tags=["answers"])
    def answer_certificate(body: CertificateRequest,
                           db: Any = Depends(get_db)) -> dict[str, Any]:
        resolved = _resolve(db, body)
        evidence = resolved["evidence"]
        document = db.query_one(
            "SELECT sha256, primary_document_url, form_type, availability_precision, "
            "availability_time FROM knowledge_document WHERE document_id = ?",
            (evidence["document_id"],),
        )
        issuer = resolve_company(db, body.issuer_id)
        source_documents = {
            evidence["document_id"]: {
                "sha256": document["sha256"] if document else None,
                "primary_document_url": document["primary_document_url"] if document else None,
                "form_type": document["form_type"] if document else None,
            }
        }
        engine = KnowledgeEngine(db)
        resolver = ConceptResolver(engine)
        resolution = resolver.resolve(body.issuer_id, body.concept, body.period,
                                      resolved["question"]["as_of"], context=body.scope)
        binding = bind(resolution, body.issuer_id, body.concept)
        if binding is None:  # pragma: no cover - _resolve already required a resolution
            raise HTTPException(status_code=422, detail={"code": "binding_failed",
                                                         "message": "cell could not be bound"})
        question = body.research_question or (
            f"What was {body.concept.replace('_', ' ')} for {body.issuer_id} in {body.period}, "
            f"as known at {resolved['question']['as_of']}?"
        )
        certificate = build_certificate(
            research_question=question,
            answer=resolved["answer"],
            bindings=[binding],
            cutoff=resolved["question"]["as_of"],
            issuer_identity={"cik": issuer.get("cik"), "issuer_name": issuer.get("legal_name"),
                             "schema": "atlas.mcp.issuer.v1"},
            source_documents=source_documents,
        )
        return {
            "schema": CERTIFICATE_SCHEMA,
            "certificate": certificate,
            "answer": resolved["answer"],
            "evidence": evidence,
            "availability": resolved["availability"],
        }

    @app.post("/api/certificates/verify", tags=["answers"])
    def certificate_verify(body: VerifyRequest) -> dict[str, Any]:
        report = verify_payload(body.certificate)
        return {
            "report": report,
            "note": "verification establishes internal consistency and, when pinned source bytes "
                    "are supplied, source identity. It never establishes that the economic "
                    "interpretation of the value is correct.",
        }

    return None


__all__ = ["register_answer_routes", "AnswerRequest", "CertificateRequest", "VerifyRequest",
           "classify_citation", "citation_period_gate"]
