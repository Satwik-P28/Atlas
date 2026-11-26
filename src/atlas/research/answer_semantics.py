"""Held-out evaluation of financial answer semantics (version 10.0.1).

The question this module scores is narrow and checkable: *did the system read the filing's
statement correctly* — the right amount, from the right period column, in the right unit, citing
the cell it actually used — and did it abstain where the evidence conflicts or does not exist?

Ground truth is not taken from Atlas. For every question it comes from

* the SEC XBRL fact filed with the same accession (value, period end, unit), read from the
  committed ``fixtures/answer_semantics/xbrl_facts.json``;
* the printed statement cell recorded during review, which must agree with the XBRL fact within
  one printed unit before the question is scored at all.

A question whose two authorities disagree is not silently repaired: it is marked
``gold_inconsistent`` and excluded from every denominator, and the report counts it.

Scoring separates the ways of being wrong:

``false_answer``      answered with a wrong amount, period or unit (the dangerous case);
``citation_failure``  the amount is right but the cited cell, row or filing is not the one the
                      question is about — a correct number from the wrong source is not a
                      correct answer;
``resolution_failure``abstained although the document prints the evidence;
``evidence_missing``  abstained because the document does not print that evidence;
``unjustified_abstention`` abstained on evidence that exists, without a conflict.

Numerical accuracy (amount, period, unit), citation accuracy (the cited accession, row and
raw text) and fully source-correct accuracy (all of them together) are reported separately.
The headline ``exact_answer_rate`` is the combined criterion.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from .financial_answers import FinancialAnswerEngine
from .financial_concepts import CONCEPTS, ConceptResolver, _label_score, bind
from .financial_verification import VerificationError, evaluate as verify_evaluate, round_half_up
from .geometry_resolution import GeometryDocument, GeometryResolver, SourceIntegrityError
from .knowledge import KnowledgeEngine
from .table_geometry import parse_tables

EVALUATION_VERSION = "10.0.2"
SCOPES = {"accession", "as_of"}
ANSWERABLE_CLASSES = {"xbrl_verified"}
ABSTENTION_CLASSES = {"conflicting_evidence", "structurally_unanswerable"}
CONFLICT_REASONS = {"vintage_conflict", "conflicting_row_values", "ambiguous_conflicting_rows"}
TOLERANCE = {"lookup": Fraction(1, 2), "arithmetic": Fraction(5, 1000)}

ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = ROOT / "fixtures" / "answer_semantics" / "corpus.json"
QUESTIONS_PATH = ROOT / "fixtures" / "answer_semantics" / "questions.json"
FACTS_PATH = ROOT / "fixtures" / "answer_semantics" / "xbrl_facts.json"
MANIFEST_PATH = ROOT / "artifacts" / "answer_semantics" / "corpus_manifest.json"
DEFAULT_DB = ROOT / "var" / "answer_semantics" / "semantics.db"
DEFAULT_SNAPSHOTS = ROOT / "var" / "answer_semantics" / "snapshots"
DEFAULT_OUTPUT = ROOT / "artifacts" / "answer_semantics" / "evaluation.json"


# --------------------------------------------------------------------------- inputs
@dataclass(slots=True)
class Question:
    id: str
    question: str
    cik: str
    accession: str
    cutoff: str
    operator: str
    concept: str
    period: str
    xbrl: list[dict[str, Any]]
    expect: dict[str, Any]
    gold_class: str
    tags: list[str] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    scope: str = "accession"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    return load_json(path)


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return load_json(path)


def load_facts(path: Path = FACTS_PATH) -> dict[str, list[dict[str, Any]]]:
    return load_json(path)["facts"]


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    payload = load_json(path)
    questions: list[Question] = []
    seen: set[str] = set()
    for raw in payload["questions"]:
        identifier = raw["id"]
        if identifier in seen:
            raise ValueError(f"duplicate question id: {identifier}")
        seen.add(identifier)
        questions.append(Question(
            id=identifier, question=raw["question"], cik=raw["issuer_cik"],
            accession=raw["accession"], cutoff=raw["cutoff"], operator=raw["operator"],
            concept=raw["concept"], period=raw["period"], xbrl=raw["xbrl"],
            expect=raw["expect"], gold_class=raw["gold_class"], tags=raw.get("tags", []),
            review=raw.get("review", {}), scope=raw.get("scope", "accession")))
        if questions[-1].scope not in SCOPES:
            raise ValueError(f"unknown scope on {identifier}: {questions[-1].scope}")
    return questions


# --------------------------------------------------------------------------- gold
def find_fact(facts: dict[str, list[dict[str, Any]]], cik: str, tag: str, end: str,
              accn: str) -> list[dict[str, Any]]:
    return [item for item in facts.get(cik, [])
            if item["tag"] == tag and item["end"] == end and item["accn"] == accn]


def select_fact(candidates: list[dict[str, Any]], printed: Fraction | None,
                scale: int | None) -> dict[str, Any] | None:
    """Pick the consolidated XBRL fact for a printed statement cell.

    SEC company facts include dimensional facts under the same tag (a segment's revenue, a
    subsidiary's income). They are not the consolidated statement. The reviewed printed cell
    decides which fact is meant; without that reference an ambiguous tag is *not* resolved.
    """
    if len(candidates) == 1:
        return candidates[0]
    if printed is None or scale is None:
        return None
    matches = [item for item in candidates
               if abs(Fraction(str(item["val"])) - printed) <= Fraction(10 ** int(scale), 2)]
    return matches[0] if len(matches) == 1 else None


def derive_gold(question: Question, facts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Ground truth from the filing's own XBRL facts, cross-checked against the review.

    Returns ``{"class": ..., ...}``. ``gold_inconsistent`` is a real outcome: it means the
    reviewed printed cell and the XBRL fact do not describe the same amount, so the question
    cannot be used to judge anybody.
    """
    if question.gold_class in ABSTENTION_CLASSES:
        return {"class": question.gold_class, "inputs": [],
                "note": question.expect.get("note", "")}
    inputs: list[dict[str, Any]] = []
    citations_for_match = question.expect.get("citations", [])
    for index, selector in enumerate(question.xbrl):
        citation = citations_for_match[index] if index < len(citations_for_match) else {}
        printed = None
        if citation.get("raw") is not None and citation.get("scale") is not None:
            try:
                printed = Fraction(str(citation["raw"]).replace(",", "")) * (
                    10 ** int(citation["scale"]))
            except (ValueError, ZeroDivisionError):
                printed = None
        fact = select_fact(find_fact(facts, question.cik, selector["tag"], selector["end"],
                                     selector["accn"]), printed, citation.get("scale"))
        if fact is None:
            return {"class": "gold_inconsistent",
                    "detail": ("XBRL fact absent, or more than one dimensional fact and none "
                               f"matches the reviewed printed cell: {selector}")}
        inputs.append({
            "tag": fact["tag"], "end": fact["end"], "accn": fact["accn"], "fy": fact["fy"],
            "fp": fact["fp"], "value": str(fact["val"]), "unit": fact["unit"],
            "source": "https://data.sec.gov/api/xbrl/companyfacts/",
        })
    values = [Fraction(item["value"]) for item in inputs]
    if question.operator == "lookup":
        exact = values[0]
        display = exact
    elif question.operator == "percentage_change":
        if values[1] == 0:
            return {"class": "gold_inconsistent", "detail": "zero prior value"}
        exact = (values[0] - values[1]) / values[1] * 100
        display = round_half_up(exact, places=2)
    elif question.operator == "margin":
        if values[1] == 0:
            return {"class": "gold_inconsistent", "detail": "zero revenue"}
        exact = values[0] / values[1] * 100
        display = round_half_up(exact, places=2)
    else:
        return {"class": "gold_inconsistent", "detail": f"unsupported operator {question.operator}"}
    # The reviewed printed cell must describe the XBRL amount within one printed unit. This is
    # what keeps the two authorities independent instead of one rationalising the other.
    citations = question.expect.get("citations", [])
    for citation, fact in zip(citations, inputs):
        scale = citation.get("scale")
        raw = citation.get("raw")
        if scale is None or raw is None:
            continue
        try:
            printed = Fraction(str(raw).replace(",", "")) * (10 ** int(scale))
        except (ValueError, ZeroDivisionError):
            return {"class": "gold_inconsistent", "detail": f"unparseable printed value {raw!r}"}
        if abs(printed - Fraction(fact["value"])) > Fraction(10 ** int(scale), 2):
            return {"class": "gold_inconsistent",
                    "detail": (f"printed {raw} x 1e{scale} = {printed} but XBRL says "
                               f"{fact['value']}")}
    return {"class": "xbrl_verified", "inputs": inputs,
            "value_exact": str(exact), "value_display": str(display)}


# --------------------------------------------------------------------------- responses
def _baseline_cells_engine(engine: KnowledgeEngine) -> FinancialAnswerEngine:
    class _Cached(FinancialAnswerEngine):
        """Cache the per-document cell extraction so the comparison measures resolution.

        Both systems pay their index cost once; the per-question number is the cost of
        resolving a concept, not the cost of re-parsing the filing.
        """

        def __init__(self) -> None:
            super().__init__(engine)
            self._cache: dict[tuple[str, str | None], list[Any]] = {}

        def cells(self, issuer_id: str, cutoff: str | None) -> list[Any]:  # type: ignore[override]
            key = (issuer_id, cutoff or "")
            if key not in self._cache:
                self._cache[key] = super().cells(issuer_id, cutoff)
            return self._cache[key]

    return _Cached()


class _CachedResolver(ConceptResolver):
    def __init__(self, engine: KnowledgeEngine, answers: FinancialAnswerEngine) -> None:
        self.engine = engine
        self.answers = answers


def issuer_id_for(db: Any, cik: str) -> str | None:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
    return None if row is None else row["issuer_id"]


def baseline_response(question: Question, db: Any, answers: FinancialAnswerEngine,
                      resolver: ConceptResolver) -> dict[str, Any]:
    started = time.perf_counter()
    issuer = issuer_id_for(db, question.cik)
    if issuer is None:
        return {"runner": "baseline", "outcome": "abstained", "reason": "issuer_not_indexed",
                "elapsed_ms": 0.0}
    concept = CONCEPTS.get(question.concept)
    if concept is None:
        return {"runner": "baseline", "outcome": "abstained", "reason": "unsupported_concept",
                "elapsed_ms": 0.0}
    if question.operator == "lookup":
        resolution = resolver.resolve(issuer, question.concept, question.period, question.cutoff)
        binding = bind(resolution, issuer, question.concept)
        if binding is None:
            return _abstained("baseline", f"concept_resolution:{resolution.status}",
                              resolution.reason, resolution.as_dict(), started)
        mismatch = _scope_mismatch(question, [binding])
        if mismatch:
            return _abstained("baseline", mismatch, None, resolution.as_dict(), started)
        packet = answers.lookup_bound(binding, question.cutoff)
    elif question.operator == "percentage_change":
        prior_period = question.expect["prior_period"]
        current = resolver.resolve(issuer, question.concept, question.period, question.cutoff)
        prior = resolver.resolve(issuer, question.concept, prior_period, question.cutoff)
        bindings = [bind(current, issuer, question.concept), bind(prior, issuer, question.concept)]
        if any(item is None for item in bindings):
            return _abstained("baseline", "concept_resolution:" + ",".join(
                f"{item.status}" for item in (current, prior)), None,
                {"current": current.as_dict(), "prior": prior.as_dict()}, started)
        mismatch = _scope_mismatch(question, bindings)
        if mismatch:
            return _abstained("baseline", mismatch, None,
                              {"current": current.as_dict(), "prior": prior.as_dict()}, started)
        packet = answers.percentage_change_bound(bindings[0], bindings[1], question.cutoff,
                                                 metric=f"{question.concept} change")
    else:  # margin
        numerator_concept = question.expect["numerator"]
        top = resolver.resolve(issuer, numerator_concept, question.period, question.cutoff)
        base = resolver.resolve(issuer, question.concept, question.period, question.cutoff)
        bindings = [bind(top, issuer, numerator_concept), bind(base, issuer, question.concept)]
        if any(item is None for item in bindings):
            return _abstained("baseline", "concept_resolution:" + ",".join(
                f"{item.status}" for item in (top, base)), None,
                {"numerator": top.as_dict(), "base": base.as_dict()}, started)
        mismatch = _scope_mismatch(question, bindings)
        if mismatch:
            return _abstained("baseline", mismatch, None,
                              {"numerator": top.as_dict(), "base": base.as_dict()}, started)
        packet = answers.margin_bound(bindings[0], bindings[1], question.cutoff)
    if packet.get("outcome") != "answered":
        return _abstained("baseline", str(packet.get("reason")), None, packet, started)
    inputs = packet.get("inputs") or []
    return {
        "runner": "baseline", "outcome": "answered",
        "value_display": packet.get("value"),
        "value_economic": packet.get("economic_amount"),
        "period": packet.get("period"), "scale": (inputs[0].get("scale") if inputs else None),
        "currency": packet.get("currency"), "accession": (inputs[0].get("accession") if inputs else None),
        "citations": [{"accession": item.get("accession"), "row_label": item.get("row_label"),
                       "raw": item.get("raw"), "period": item.get("period"),
                       "scale": item.get("scale"), "column_label": item.get("column_label")}
                      for item in inputs],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _scope_mismatch(question: Question, bindings: list[Any]) -> str | None:
    """An accession-scoped question may only be answered from its own filing.

    The baseline resolver searches every filing the issuer has ingested, which is right for an
    as-of question and wrong for one that names an accession: a comparative column in a later
    10-K can carry the same fiscal year. Refusing is cheaper than reading the wrong document.
    """
    if question.scope != "accession":
        return None
    for binding in bindings:
        accession = getattr(binding, "accession", None) if binding is not None else None
        if accession and accession != question.accession:
            return f"source_accession_mismatch:{accession}"
    return None


def _resolve_scope(question: Question) -> dict[str, Any]:
    scope: dict[str, Any] = {"cutoff": question.cutoff, "cik": question.cik}
    if question.scope == "accession":
        scope["accession"] = question.accession
    return scope


def operand_integrity(cells: list[Any], operator: str) -> str | None:
    """Refuse to combine cells that do not describe the same measured thing.

    A margin or a percentage change is only meaningful when both operands are printed in the
    same unit, the same currency, from the same document, at compatible periods, on the same
    reporting scope. The certificate verifier enforces this for certificates; this path must
    not be weaker, so it refuses before any arithmetic instead of normalising silently.
    """
    if len(cells) < 2:
        return None
    if any(cell.scale is None for cell in cells):
        return "missing_scale"
    if len({cell.scale for cell in cells}) != 1:
        return "mixed_scale"
    stated = {cell.currency for cell in cells if cell.currency}
    if len(stated) > 1:
        return "mixed_currency"
    if len({cell.accession for cell in cells}) != 1:
        return "mixed_source_accession"
    if len({cell.document_sha256 for cell in cells}) != 1:
        return "mixed_source_document"
    scopes = {cell.entity_scope for cell in cells if cell.entity_scope not in {None, "unknown"}}
    if len(scopes) > 1:
        return "mixed_entity_scope"
    if scopes & {"segment", "parent"}:
        return "non_consolidated_scope"
    periods = [cell.period for cell in cells]
    if operator == "margin" and len(set(periods)) != 1:
        return "incompatible_periods"
    if operator == "percentage_change" and len(set(periods)) != 2:
        return "incompatible_periods"
    return None


def _abstained(runner: str, reason: str, detail: Any, evidence: Any,
               started: float) -> dict[str, Any]:
    return {"runner": runner, "outcome": "abstained", "reason": reason,
            "detail": detail, "evidence": evidence,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}


def geometry_response(question: Question, resolver: GeometryResolver) -> dict[str, Any]:
    started = time.perf_counter()
    scope = _resolve_scope(question)
    if question.operator == "lookup":
        resolution = resolver.resolve(question.concept, question.period, **scope)
        if resolution.status != "resolved" or resolution.cell is None:
            return _abstained("geometry", f"geometry:{resolution.status}:{resolution.reason}",
                              resolution.reason, resolution.as_dict(), started)
        cell = resolution.cell
        exact = Fraction(str(cell.value))
        economic = exact * (10 ** cell.scale) if cell.scale is not None else exact
        return {
            "runner": "geometry", "outcome": "answered",
            "value_display": _decimal_text(exact),
            "value_economic": _decimal_text(economic),
            "period": cell.period, "scale": cell.scale, "currency": cell.currency,
            "accession": cell.accession,
            "citations": [{"accession": cell.accession, "row_label": cell.row_label,
                           "raw": cell.raw, "period": cell.period, "scale": cell.scale,
                           "column_label": cell.column_header, "table_digest": cell.table_digest,
                           "document_sha256": cell.document_sha256,
                           "statement_family": cell.statement_family,
                           "entity_scope": cell.entity_scope,
                           "table_index": cell.table_index}],
            "resolution": resolution.as_dict(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    if question.operator == "percentage_change":
        prior_period = question.expect["prior_period"]
        current = resolver.resolve(question.concept, question.period, **scope)
        prior = resolver.resolve(question.concept, prior_period, **scope)
        resolved = [item for item in (current, prior)
                    if item.status == "resolved" and item.cell is not None]
        if len(resolved) != 2:
            return _abstained("geometry", "geometry:" + ",".join(
                f"{item.status}:{item.reason}" for item in (current, prior)), None,
                {"current": current.as_dict(), "prior": prior.as_dict()}, started)
        raw_values = [current.cell.raw, prior.cell.raw]  # type: ignore[union-attr]
        cells = [current.cell, prior.cell]
    else:
        numerator_concept = question.expect["numerator"]
        top = resolver.resolve(numerator_concept, question.period, **scope)
        base = resolver.resolve(question.concept, question.period, **scope)
        resolved = [item for item in (top, base)
                    if item.status == "resolved" and item.cell is not None]
        if len(resolved) != 2:
            return _abstained("geometry", "geometry:" + ",".join(
                f"{item.status}:{item.reason}" for item in (top, base)), None,
                {"numerator": top.as_dict(), "base": base.as_dict()}, started)
        raw_values = [top.cell.raw, base.cell.raw]  # type: ignore[union-attr]
        cells = [top.cell, base.cell]
    problem = operand_integrity([cell for cell in cells if cell is not None], question.operator)
    if problem:
        return _abstained("geometry", f"unit_integrity:{problem}", problem,
                          {"operands": [_operand_digest(cell) for cell in cells]}, started)
    try:
        exact = verify_evaluate(question.operator, raw_values)
    except (VerificationError, ValueError) as exc:
        return _abstained("geometry", "verification_disagreement", str(exc), None, started)
    display = round_half_up(exact, places=2)
    return {
        "runner": "geometry", "outcome": "answered", "value_display": str(display),
        "value_economic": None, "period": cells[0].period,  # type: ignore[union-attr]
        "scale": cells[0].scale,  # type: ignore[union-attr]
        "currency": cells[0].currency,  # type: ignore[union-attr]
        "accession": cells[0].accession,  # type: ignore[union-attr]
        "citations": [{"accession": cell.accession, "row_label": cell.row_label,  # type: ignore[union-attr]
                       "raw": cell.raw, "period": cell.period, "scale": cell.scale,
                       "column_label": cell.column_header, "table_digest": cell.table_digest}
                      for cell in cells],  # type: ignore[union-attr]
        "value_exact": str(exact),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _operand_digest(cell: Any) -> dict[str, Any] | None:
    if cell is None:
        return None
    return {"accession": cell.accession, "row_label": cell.row_label, "raw": cell.raw,
            "scale": cell.scale, "currency": cell.currency, "period": cell.period,
            "statement_family": cell.statement_family, "entity_scope": cell.entity_scope,
            "document_sha256": cell.document_sha256}


def _decimal_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return format(Decimal(value.numerator) / Decimal(value.denominator), "f")


# --------------------------------------------------------------------------- scoring
def score(question: Question, gold: dict[str, Any], response: dict[str, Any],
          documents: dict[str, GeometryDocument]) -> dict[str, Any]:
    """Compare one response with ground truth. Never repairs either side."""
    result: dict[str, Any] = {"id": question.id, "runner": response["runner"],
                              "outcome": response["outcome"],
                              "gold_class": gold["class"], "tags": question.tags,
                              "elapsed_ms": response.get("elapsed_ms", 0.0)}
    if response["outcome"] == "error":
        result.update(status="runner_error", correct=False, reason=response.get("reason"))
        return result
    if gold["class"] == "gold_inconsistent":
        result.update(status="excluded", correct=False, reason="gold_inconsistent",
                      detail=gold.get("detail"))
        return result
    if question.gold_class in ABSTENTION_CLASSES:
        return _score_abstention(question, response, documents, result)
    # ---- answerable question
    if response["outcome"] != "answered":
        refusal = classify_refusal(question, response, documents)
        result.update(status=refusal, correct=False, reason=response.get("reason"),
                      detail=response.get("detail"))
        return result
    correct_value = _value_matches(question, gold, response)
    period_ok = _period_matches(question, response)
    unit_ok = response.get("scale") == question.expect["scale"]
    citation = _citation_matches(question, response)
    source_ok = _source_matches(question, gold, response)
    header_ok = _header_confirms_period(question, response)
    numerical = bool(correct_value and period_ok and unit_ok)
    fully_correct = bool(numerical and source_ok and citation)
    # A correct amount attributed to the wrong filing, row or raw text is not a correct answer
    # to a question about evidence. It is reported as a citation failure, not as a hit.
    status = "correct" if fully_correct else ("citation_failure" if numerical else "false_answer")
    result.update(correct=fully_correct, value_ok=correct_value, period_ok=period_ok,
                  unit_ok=unit_ok, numerical_ok=numerical, citation_ok=citation,
                  source_ok=source_ok, header_confirmed=header_ok, status=status,
                  reason=None, response=_response_digest(response))
    return result


def _score_abstention(question: Question, response: dict[str, Any],
                      documents: dict[str, GeometryDocument], result: dict[str, Any]) -> dict[str, Any]:
    if response["outcome"] == "answered":
        result.update(status="unsupported_confident_answer", correct=False,
                      reason="answered_where_no_answer_is_supported",
                      response=_response_digest(response))
        return result
    reason = str(response.get("reason") or "")
    conflict = any(marker in reason for marker in CONFLICT_REASONS)
    if question.gold_class == "conflicting_evidence":
        justified = conflict
        status = "justified_abstention" if justified else "unjustified_abstention"
    else:  # structurally unanswerable: the statement never prints the concept
        justified = conflict or not _evidence_printed(question, documents)
        status = "justified_abstention" if justified else "unjustified_abstention"
    result.update(status=status, correct=justified, reason=response.get("reason"),
                  detail=response.get("detail"))
    return result


def _value_matches(question: Question, gold: dict[str, Any], response: dict[str, Any]) -> bool:
    if question.operator == "lookup":
        observed = response.get("value_economic")
        if observed is None:
            return False
        try:
            return abs(Fraction(str(observed)) - Fraction(gold["inputs"][0]["value"])) <= Fraction(
                10 ** int(question.expect["scale"]), 2)
        except (ValueError, ZeroDivisionError):
            return False
    try:
        return abs(Fraction(str(response.get("value_display"))) - Fraction(gold["value_display"])) \
            <= TOLERANCE["arithmetic"]
    except (ValueError, ZeroDivisionError, TypeError):
        return False


def _expected_periods(question: Question) -> list[str]:
    if question.operator == "percentage_change":
        return [question.period, question.expect["prior_period"]]
    if question.operator == "margin":
        return [question.period, question.period]
    return [question.period]


def _period_matches(question: Question, response: dict[str, Any]) -> bool:
    expected = _expected_periods(question)
    citations = response.get("citations") or []
    if len(citations) != len(expected):
        return False
    return all(str(item.get("period")) == period for item, period in zip(citations, expected))


def _header_confirms_period(question: Question, response: dict[str, Any]) -> bool:
    """The citation's own column label must name the period it is used for."""
    citations = response.get("citations") or []
    expected = _expected_periods(question)
    if len(citations) != len(expected):
        return False
    return all(period in str(item.get("column_label") or "") or
               f"20{period[-2:]}" in str(item.get("column_label") or "")
               for item, period in zip(citations, expected))


def _source_matches(question: Question, gold: dict[str, Any],
                    response: dict[str, Any]) -> bool:
    """The cited accession must be the filing whose XBRL fact defines the answer.

    For an accession-scoped question that is the named filing. For an as-of question it is
    whichever filing supplied the fact, which the gold records per input.
    """
    expected = [str(item["accn"]) for item in gold.get("inputs") or []]
    citations = response.get("citations") or []
    if not expected or len(citations) != len(expected):
        return False
    if [str(item.get("accession") or "") for item in citations] != expected:
        return False
    return all(accession == question.accession for accession in expected) \
        if question.scope == "accession" else True


def _citation_matches(question: Question, response: dict[str, Any]) -> bool:
    expected = question.expect.get("citations") or []
    citations = response.get("citations") or []
    if len(citations) != len(expected):
        return False
    for want, got in zip(expected, citations):
        if _raw_amount(got.get("raw")) != _raw_amount(want.get("raw")):
            return False
        if want.get("accession") and got.get("accession") != want["accession"]:
            return False
        labels = {str(label).strip().lower() for label in want.get("row_labels", [])}
        if labels and str(got.get("row_label") or "").strip().lower() not in labels:
            return False
    return True


def classify_refusal(question: Question, response: dict[str, Any],
                     documents: dict[str, GeometryDocument]) -> str:
    """Is a refusal about the filing, about the resolver, or about absent evidence?"""
    reason = str(response.get("reason") or "")
    if any(marker in reason for marker in CONFLICT_REASONS):
        return "unjustified_abstention"
    if _evidence_printed(question, documents):
        return "resolution_failure"
    return "evidence_missing"


def _evidence_printed(question: Question, documents: dict[str, GeometryDocument]) -> bool:
    """Does the archived filing print a row for this concept at this period, anywhere?

    This is an independent check: it scans every table for a label the concept's own alias
    vocabulary reaches and for a printed period the question asks about. It does not use
    either resolver's table, scope or uniqueness policy.
    """
    concept = CONCEPTS.get(question.concept)
    if concept is None:
        return False
    periods = set(_expected_periods(question))
    document = documents.get(question.accession)
    if document is None:
        return False
    for table in document.tables:
        for row in range(table.body_start, len(table.grid)):
            label = table.label_of(row)
            if max((_label_score(label, alias) for alias in concept.aliases), default=0.0) < 2.0:
                continue
            if not periods & set(table.printed_periods()):
                continue
            if table.numeric_columns(row):
                return True
    return False


def _raw_amount(text: Any) -> str:
    """Compare a printed amount, not its typography.

    Filers put the currency symbol in the cell (``$137,100``) or in a separate column
    (``137,100``); both cite the same printed value. Spaces, currency signs and a leading plus are
    removed; parentheses and minus signs are kept because they carry the sign.
    """
    value = str(text or "")
    value = re.sub(r"[\s$€£¥]", "", value)
    return value.replace("+", "")


def _response_digest(response: dict[str, Any]) -> dict[str, Any]:
    return {key: response.get(key) for key in
            ("value_display", "value_economic", "period", "scale", "accession", "citations")}


# --------------------------------------------------------------------------- run
def load_documents(manifest: dict[str, Any], snapshots: Path,
                   corpus: dict[str, Any] | None = None) -> dict[str, GeometryDocument]:
    """Parse archived filings only after their bytes match the committed manifest.

    Everything downstream cites ``document_sha256``; that field is only trustworthy if the
    bytes were hashed here. A missing, truncated, appended or replaced snapshot fails closed,
    and the manifest is checked against the declared corpus so an extra or renamed filing
    cannot slip into the evaluation set.
    """
    declared = {}
    if corpus is not None:
        declared = {filing["accession"]: filing for filing in corpus["filings"]}
    documents: dict[str, GeometryDocument] = {}
    for filing in manifest["filings"]:
        accession = filing["accession"]
        if accession in documents:
            raise SourceIntegrityError(f"duplicate accession in manifest: {accession}")
        if corpus is not None:
            expected = declared.get(accession)
            if expected is None:
                raise SourceIntegrityError(f"manifest accession not in the declared corpus: {accession}")
            if str(expected["cik"]).lstrip("0") != str(filing["cik"]).lstrip("0"):
                raise SourceIntegrityError(
                    f"manifest CIK {filing['cik']} disagrees with the corpus for {accession}")
        path = snapshots / f"{accession}.html"
        if not path.exists():
            raise SourceIntegrityError(f"archived snapshot missing: {path}")
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != filing["document_sha256"]:
            raise SourceIntegrityError(
                f"archived snapshot altered: {path} hashes to {digest}, manifest records "
                f"{filing['document_sha256']}")
        documents[accession] = GeometryDocument.from_html(
            payload, accession=accession, document_sha256=digest, cik=filing["cik"],
            availability_time=filing.get("availability_time"),
            rights=filing.get("rights", "user_responsibility"))
    return documents


def run(output: Path = DEFAULT_OUTPUT, db_path: Path = DEFAULT_DB,
        snapshots: Path = DEFAULT_SNAPSHOTS,
        questions_path: Path = QUESTIONS_PATH, manifest_path: Path = MANIFEST_PATH,
        facts_path: Path = FACTS_PATH, corpus_path: Path = CORPUS_PATH) -> dict[str, Any]:
    """Score both resolvers on one corpus. ``corpus_path`` keeps cohorts separate.

    The prospective holdout must not be scored through the development paths, so the declared
    corpus is a parameter. Nothing else about resolution or scoring changes: both arms see the
    same questions, documents and environment.
    """
    from ..storage.db import Database

    manifest = load_manifest(manifest_path)
    facts = load_facts(facts_path)
    questions = load_questions(questions_path)
    built_started = time.perf_counter()
    documents = load_documents(manifest, Path(snapshots), corpus=load_corpus(corpus_path))
    geometry_build_ms = round((time.perf_counter() - built_started) * 1000, 3)

    database = Database(str(db_path))
    knowledge = KnowledgeEngine(database)
    answers = _baseline_cells_engine(knowledge)
    resolver = _CachedResolver(knowledge, answers)
    baseline_build_started = time.perf_counter()
    for cik in sorted({question.cik for question in questions}):
        issuer = issuer_id_for(database, cik)
        if issuer:
            answers.cells(issuer, None)  # warm: the one-time flattened-cell extraction
    baseline_build_ms = round((time.perf_counter() - baseline_build_started) * 1000, 3)

    geometry = GeometryResolver(documents.values())
    results: list[dict[str, Any]] = []
    golds: dict[str, dict[str, Any]] = {}
    for question in questions:
        gold = derive_gold(question, facts)
        golds[question.id] = gold
        for name, runner in (("baseline", lambda: baseline_response(
                                  question, database, answers, resolver)),
                             ("geometry", lambda: geometry_response(question, geometry))):
            try:
                response = runner()
            except Exception as exc:  # noqa: BLE001 - one broken question must not hide the rest
                response = {"runner": name, "outcome": "error",
                            "reason": f"{type(exc).__name__}: {exc}", "elapsed_ms": 0.0}
            results.append(score(question, gold, response, documents))
    report = {
        "schema": "atlas.answer_semantics.evaluation.v1",
        "evaluation_version": EVALUATION_VERSION,
        "corpus_digest": manifest["xbrl"]["digest"],
        "questions": len(questions),
        "gold": {question.id: golds[question.id] for question in questions},
        "build_ms": {"baseline_flattened_cells": baseline_build_ms,
                     "geometry_tables": geometry_build_ms},
        "metrics": {runner: summarise([item for item in results if item["runner"] == runner],
                                     golds, questions)
                    for runner in ("baseline", "geometry")},
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def summarise(results: list[dict[str, Any]], golds: dict[str, dict[str, Any]],
              questions: Iterable[Question]) -> dict[str, Any]:
    answerable = [item for item in results
                  if golds[item["id"]]["class"] == "xbrl_verified"]
    abstention = [item for item in results
                  if golds[item["id"]]["class"] in ABSTENTION_CLASSES]
    excluded = [item for item in results if item["status"] == "excluded"]
    answered = [item for item in answerable if item["outcome"] == "answered"]
    correct = [item for item in answerable if item["status"] == "correct"]
    false = [item for item in answerable if item["status"] == "false_answer"]
    citation_failures = [item for item in answerable if item["status"] == "citation_failure"]
    numerical = [item for item in answerable if item.get("numerical_ok")]
    justified = [item for item in abstention if item["status"] == "justified_abstention"]
    unsupported = [item for item in abstention
                   if item["status"] == "unsupported_confident_answer"]
    latencies = sorted(item.get("elapsed_ms", 0.0) for item in results)
    return {
        "scored_questions": len(answerable) + len(abstention),
        "excluded_questions": len(excluded),
        "answerable": len(answerable),
        "answered": len(answered),
        "correct": len(correct),
        "exact_answer_rate": _rate(len(correct), len(answerable)),
        "numerical_accuracy": _rate(len(numerical), len(answerable)),
        "answer_precision": _rate(len(correct), len(answered)),
        "citation_failures": len(citation_failures),
        "source_accuracy": _rate(sum(1 for item in answered if item.get("source_ok")),
                                 len(answered)),
        "period_accuracy": _rate(sum(1 for item in answered if item.get("period_ok")), len(answered)),
        "unit_accuracy": _rate(sum(1 for item in answered if item.get("unit_ok")), len(answered)),
        "citation_accuracy": _rate(sum(1 for item in answered if item.get("citation_ok")), len(answered)),
        "period_header_confirmed": _rate(
            sum(1 for item in answered if item.get("header_confirmed")), len(answered)),
        "false_answers": len(false),
        "false_answer_rate": _rate(len(false), len(answered)),
        # ``resolution_failures`` and ``unjustified_abstentions`` are disjoint statuses of the same
        # population: an answerable question the system did not answer. Reported together here so
        # the abstention count can never be understated by reading one field alone.
        "answerable_abstentions": sum(1 for item in answerable
                                      if item["outcome"] != "answered"),
        "unjustified_abstentions": sum(1 for item in answerable
                                       if item["status"] == "unjustified_abstention"),
        "resolution_failures": sum(1 for item in answerable if item["status"] == "resolution_failure"),
        "evidence_missing": sum(1 for item in answerable if item["status"] == "evidence_missing"),
        "runner_errors": sum(1 for item in results if item["status"] == "runner_error"),
        "abstention_questions": len(abstention),
        "justified_abstentions": len(justified),
        "justified_abstention_rate": _rate(len(justified), len(abstention)),
        "unsupported_confident_answers": len(unsupported),
        "latency_ms": {"median": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 4)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
    return round(values[index], 3)


__all__ = ["Question", "derive_gold", "load_documents", "load_questions", "run", "score",
           "baseline_response", "geometry_response", "summarise", "EVALUATION_VERSION"]
