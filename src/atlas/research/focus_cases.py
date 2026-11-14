"""The thirteen FOCUS financial cases over real 10-K filings (v10.0.0).

This is the single definition of the case set. Each case is a research request, a historical
cutoff and, when the request is answerable, the resolver binding that produced the value. The
runner keeps the bindings so that a certificate can be built from the same evidence the answer
used; nothing is re-resolved for the certificate.

Every case is classified by *why* it did or did not answer:

``answered``
    A value was computed and independently recomputed.
``justified_unanswerability``
    The question asks for a concept the statement does not contain (a bank has no gross profit).
``historical_information_refusal``
    The filing exists but was not public at the cutoff.
``capability_gap``
    The evidence needed to answer exists in principle but this system did not resolve it.
``ambiguous_evidence``
    More than one candidate cell matched and none is defensibly unique.
``defect``
    A value was produced that is inconsistent with the filing.

A refusal is recorded with its reason. A refusal is not scored as a success; it is scored as a
refusal with a cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .financial_answers import FinancialAnswerEngine
from .financial_concepts import ConceptResolver, bind
from .knowledge import KnowledgeEngine

ENGINE_FAMILY = "10.0.0"

COCA_COLA = "COCA COLA CO"
JPMORGAN = "JPMORGAN CHASE & CO"
THREE_M = "3M CO"

#: (family, issuer legal name, cutoff, operator, request)
CASES: list[tuple[str, str, str, str, dict[str, Any]]] = [
    ("operating", COCA_COLA, "2023-06-30T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
    ("operating", COCA_COLA, "2023-06-30T00:00:00Z", "lookup",
     {"concept": "net_income", "period": "2022"}),
    ("operating", COCA_COLA, "2023-06-30T00:00:00Z", "percentage_change",
     {"concept": "revenue", "current_period": "2022", "prior_period": "2021"}),
    ("operating", COCA_COLA, "2023-06-30T00:00:00Z", "margin",
     {"numerator": "operating_income", "concept": "revenue", "period": "2022"}),
    ("operating", COCA_COLA, "2023-06-30T00:00:00Z", "ratio",
     {"numerator": "total_assets", "concept": "revenue", "period": "2022"}),
    ("bank", JPMORGAN, "2024-01-01T00:00:00Z", "lookup",
     {"concept": "total_assets", "period": "2022"}),
    ("bank", JPMORGAN, "2024-01-01T00:00:00Z", "lookup",
     {"concept": "net_income", "period": "2022"}),
    ("bank", JPMORGAN, "2024-01-01T00:00:00Z", "ratio",
     {"numerator": "net_income", "concept": "total_assets", "period": "2022"}),
    ("bank", JPMORGAN, "2024-01-01T00:00:00Z", "lookup",
     {"concept": "gross_profit", "period": "2022"}),
    ("segment", THREE_M, "2024-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
    ("segment", THREE_M, "2024-01-01T00:00:00Z", "percentage_change",
     {"concept": "revenue", "current_period": "2022", "prior_period": "2021"}),
    ("segment", THREE_M, "2024-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2018"}),
    ("cutoff", THREE_M, "2017-01-01T00:00:00Z", "lookup",
     {"concept": "revenue", "period": "2022"}),
]

#: Requests that cannot be satisfied because the concept does not exist in that kind of statement.
STRUCTURALLY_UNANSWERABLE = {
    (JPMORGAN, "gross_profit"),
}


@dataclass(slots=True)
class CaseResult:
    case_id: str
    family: str
    issuer: str
    cutoff: str
    operator: str
    request: dict[str, Any]
    packet: dict[str, Any]
    bindings: list[Any]
    resolutions: dict[str, Any]
    classification: str
    note: str | None = None

    @property
    def answered(self) -> bool:
        return self.packet.get("outcome") == "answered"

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "issuer": self.issuer,
            "cutoff": self.cutoff,
            "operator": self.operator,
            "request": self.request,
            "outcome": self.packet.get("outcome"),
            "classification": self.classification,
            "note": self.note,
            "value": self.packet.get("value"),
            "unit": self.packet.get("unit"),
            "currency": self.packet.get("currency"),
            "period": self.packet.get("period"),
            "reason": self.packet.get("reason"),
            "context": self.packet.get("context"),
            "resolution": self.resolutions,
            "inputs": [
                {key: item.get(key) for key in
                 ("cell_id", "document_id", "accession", "table_id", "unit_id", "row", "column",
                  "row_label", "column_label", "period", "raw", "value", "scale", "currency",
                  "availability_time", "availability_precision", "rights")}
                for item in (self.packet.get("inputs") or [])
            ],
        }


def issuer_id(db: Any, legal_name: str) -> str:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE legal_name = ?", (legal_name,))
    if row is None:
        raise SystemExit(f"issuer not present in this corpus: {legal_name}")
    return row["issuer_id"]


def _resolve(resolver: ConceptResolver, issuer: str, concept: str, period: str, cutoff: str):
    resolution = resolver.resolve(issuer, concept, period, cutoff)
    return resolution, bind(resolution, issuer, concept)


def _normalise(text: str | None) -> str:
    import re

    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _aliases(concept: str) -> set[str]:
    from .financial_concepts import CONCEPTS

    entry = CONCEPTS.get(concept)
    return {_normalise(alias) for alias in (entry.aliases if entry else (concept,))}


def diagnose(db: Any, answers: FinancialAnswerEngine, issuer: str, concept: str, period: str,
             cutoff: str, packet: dict[str, Any]) -> tuple[str, str | None]:
    """Explain a refusal from the corpus, not from the resolver's own label.

    The resolver's reason string is a description of what the resolver did, not of what the
    evidence is. Reporting ``ambiguous_evidence`` because the resolver returned ``ambiguous``
    would launder a resolver defect into a finding about the question. Each branch below is
    checked against the stored cells so the classification is about the filings.
    """
    if packet.get("outcome") == "answered":
        return "answered", None
    aliases = _aliases(concept)

    # 1. The evidence exists and is unique at the cutoff, so resolution, not the filing, failed.
    at_cutoff = [
        cell for cell in answers.cells(issuer, cutoff)
        if cell.status == "verified" and _normalise(cell.row_label) in aliases
        and (not period or cell.period == period)
    ]
    values = {cell.value for cell in at_cutoff}
    if len(values) == 1:
        cell = at_cutoff[0]
        return "capability_gap", (
            "the filing prints a unique statement row for this concept "
            f"({cell.row_label!r} = {cell.raw!r} for {cell.period}), but concept resolution did "
            f"not bind it ({packet.get('reason')}); this is a resolution limitation, not an "
            "unanswerable question")
    if len(values) > 1:
        return "ambiguous_evidence", (
            "several verified statement rows match the concept with different amounts "
            f"({sorted(values)[:4]}); selecting one would be a guess")

    # 2. The concept never appears in this issuer's statements at all.
    if not any(_normalise(cell.row_label) in aliases and cell.status == "verified"
               for cell in answers.cells(issuer, None)):
        return "justified_unanswerability", (
            f"no verified statement row of this issuer uses the concept {concept!r}; the "
            "question asks for a line item the statements do not report")

    # 3. A filing covers the period but was not public at the cutoff.
    covered = db.query_one(
        "SELECT accession, availability_time FROM knowledge_document WHERE issuer_id = ? "
        "AND period_of_report LIKE ? ORDER BY availability_time LIMIT 1",
        (issuer, f"{period}%"))
    if covered is not None and str(covered["availability_time"]) > cutoff:
        return "historical_information_refusal", (
            f"accession {covered['accession']} covers {period} but became available "
            f"{covered['availability_time']}, after the cutoff {cutoff}")
    return "capability_gap", (
        "the evidence was not resolved by this system; this is a resolution limitation, not a "
        "proof that the question is unanswerable")


def run_cases(db: Any, *, cases: list[tuple[str, str, str, str, dict[str, Any]]] | None = None,
              cutoff_override: str | None = None) -> list[CaseResult]:
    """Execute every case against an ingested corpus and return result packets."""
    knowledge = KnowledgeEngine(db)
    answers = FinancialAnswerEngine(knowledge)
    resolver = ConceptResolver(knowledge)
    results: list[CaseResult] = []
    for index, case in enumerate(cases or CASES, start=1):
        family, name, cutoff, operator, request = case
        cutoff = cutoff_override or cutoff
        iid = issuer_id(db, name)
        packet: dict[str, Any] = {
            "family": family, "issuer": name, "cutoff": cutoff, "operator": operator,
            "request": request, "engine_version": "9.6.3",
        }
        bindings: list[Any] = []
        resolutions: dict[str, Any] = {}
        if operator == "lookup":
            resolution, binding = _resolve(resolver, iid, request["concept"],
                                           request["period"], cutoff)
            resolutions["base"] = resolution
            if binding is None:
                packet.update(outcome="abstained",
                              reason=f"concept_resolution:{resolution.status}")
            else:
                bindings = [binding]
                packet.update(answers.lookup_bound(binding, cutoff))
        elif operator == "percentage_change":
            current_res, current_bind = _resolve(resolver, iid, request["concept"],
                                                 request["current_period"], cutoff)
            prior_res, prior_bind = _resolve(resolver, iid, request["concept"],
                                             request["prior_period"], cutoff)
            resolutions.update(current=current_res, prior=prior_res)
            if current_bind is None or prior_bind is None:
                packet.update(outcome="abstained", reason="concept_resolution:" + ",".join(
                    f"{period}={resolution.status}" for period, resolution in
                    ((request["current_period"], current_res),
                     (request["prior_period"], prior_res))))
            else:
                bindings = [current_bind, prior_bind]
                packet.update(answers.percentage_change_bound(
                    current_bind, prior_bind, cutoff,
                    metric=(f"{request['concept']} {request['current_period']}"
                            f" vs {request['prior_period']}")))
        else:
            numerator_res, numerator_bind = _resolve(resolver, iid, request["numerator"],
                                                     request["period"], cutoff)
            base_res, base_bind = _resolve(resolver, iid, request["concept"],
                                           request["period"], cutoff)
            resolutions.update(numerator=numerator_res, base=base_res)
            if numerator_bind is None or base_bind is None:
                packet.update(outcome="abstained", reason="concept_resolution:" + ",".join(
                    resolution.status for resolution in (numerator_res, base_res)
                    if resolution.status != "resolved"))
            else:
                bindings = [numerator_bind, base_bind]
                packet.update(answers.margin_bound(numerator_bind, base_bind, cutoff)
                              if operator == "margin"
                              else answers.ratio_bound(numerator_bind, base_bind, cutoff))
        packet["research_task"] = f"{name}: {operator} {request}"
        packet["cutoff"] = cutoff
        diagnosis_concept = (request.get("concept") or request.get("numerator") or "")
        diagnosis_period = (request.get("period") or request.get("current_period") or "")
        classification, note = diagnose(db, answers, iid, diagnosis_concept, diagnosis_period,
                                        cutoff, packet)
        results.append(CaseResult(
            case_id=f"FOCUS-{index:02d}", family=family, issuer=name, cutoff=cutoff,
            operator=operator, request=request, packet=packet, bindings=bindings,
            resolutions={key: value.as_dict() for key, value in resolutions.items()},
            classification=classification, note=note))
    return results


__all__ = ["CASES", "CaseResult", "ENGINE_FAMILY", "diagnose", "issuer_id", "run_cases"]
