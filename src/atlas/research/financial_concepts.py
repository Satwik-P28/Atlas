"""Deterministic financial-concept resolution (version 9.6.3).

A verified number is not an answer. This module maps a research requirement to one financial
concept, then to one table row/column in one filing vintage, and refuses when the mapping is not
unique.

Lexical aliases are *candidates*, not proof. The settled mapping carries the concept key, the
statement hint, the vintage and the evidence identity. XBRL validation is declared but reported as
unavailable: the corpus stores no XBRL fact table, so no concept identity is asserted from XBRL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .financial_answers import FinancialAnswerEngine
from .table_cells import Cell

RESOLVER_VERSION = "9.6.4"


@dataclass(frozen=True, slots=True)
class Concept:
    key: str
    aliases: tuple[str, ...]
    xbrl_tags: tuple[str, ...]
    statement: str
    kind: str
    segment_sensitive: bool = True


CONCEPTS: dict[str, Concept] = {
    "revenue": Concept("revenue", ("revenue", "net sales", "total revenue", "net revenue",
                                   "total net revenue", "net operating revenues", "sales"), ("us-gaap:Revenues", "us-gaap:SalesRevenueNet",
                                              "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
                       "income", "flow"),
    "net_income": Concept("net_income", ("net income", "net earnings", "net income (loss)",
                                         "net loss"), ("us-gaap:NetIncomeLoss",), "income", "flow"),
    "operating_income": Concept("operating_income", ("operating income", "income from operations",
                                                     "operating profit"),
                                ("us-gaap:OperatingIncomeLoss",), "income", "flow"),
    "gross_profit": Concept("gross_profit", ("gross profit", "gross margin"),
                            ("us-gaap:GrossProfit",), "income", "flow"),
    "total_assets": Concept("total_assets", ("total assets",), ("us-gaap:Assets",), "balance",
                            "stock", segment_sensitive=False),
    "total_liabilities": Concept("total_liabilities", ("total liabilities",),
                                 ("us-gaap:Liabilities",), "balance", "stock",
                                 segment_sensitive=False),
    "cash_and_equivalents": Concept("cash_and_equivalents",
                                    ("cash and cash equivalents", "cash and equivalents",
                                     "cash and due from banks"),
                                    ("us-gaap:CashAndCashEquivalentsAtCarryingValue",), "balance",
                                    "stock", segment_sensitive=False),
    "operating_cash_flow": Concept("operating_cash_flow",
                                   ("net cash provided by operating activities",
                                    "cash provided by operating activities",
                                    "net cash from operating activities"),
                                   ("us-gaap:NetCashProvidedByUsedInOperatingActivities",),
                                   "cash_flow", "flow"),
    "capital_expenditures": Concept("capital_expenditures",
                                    ("capital expenditures", "purchases of property and equipment",
                                     "additions to property, plant and equipment"),
                                    ("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",),
                                    "cash_flow", "flow"),
    "shares_basic": Concept("shares_basic", ("basic", "weighted average shares"),
                            ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",), "income",
                            "flow", segment_sensitive=False),
    "shares_diluted": Concept("shares_diluted", ("diluted", "weighted average diluted shares"),
                              ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",),
                              "income", "flow", segment_sensitive=False),
}

# Companion rows that must coexist in the same table for a row to be the primary statement. A
# segment note can print "Total assets" without liabilities and equity; a parent-company schedule
# can print it without the consolidated totals.
COMPANION_ROWS = {
    "total_assets": (("total liabilities",), ("equity", "stockholders' equity")),
    "total_liabilities": (("total assets",),),
    "revenue": (("cost of sales", "cost of goods sold", "cost of revenue", "gross profit",
                 "operating income", "income from operations"),),
    "net_income": (("operating income", "income from operations", "diluted", "basic"),),
    "operating_income": (("net sales", "revenue", "net income"),),
    "gross_profit": (("net sales", "revenue", "cost of sales", "cost of goods sold"),),
    "cash_and_equivalents": (("total assets", "total liabilities", "current assets"),),
    "operating_cash_flow": (("investing activities", "financing activities"),),
    "capital_expenditures": (("investing activities", "operating activities"),),
}
SEGMENT_MARKERS = ("segment", "north america", "international", "emea", "europe", "asia",
                   "americas", "corporate", "other", "consumer", "industrial", "safety",
                   "health care", "transportation", "financial services")
STATEMENT_HINTS = {
    "income": ("income", "operations", "earnings", "statements of operations"),
    "balance": ("balance sheet", "financial position", "financial condition"),
    "cash_flow": ("cash flow", "cash flows"),
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("\u2019", "'")).strip()


def statement_scope(section_path: str, caption: str | None) -> str:
    """Coarse statement scope. The same row label appears in several statements."""
    text = f"{section_path} {caption or ''}".lower()
    if "parent company" in text or "parent-only" in text:
        return "parent"
    if "segment" in text:
        return "segment"
    if "consolidated" in text:
        return "consolidated"
    return "unknown"


QUALIFIERS = ("less:", "noncontrolling", "attributable to non", "before income taxes",
              "including", "excluding", "per share", "per diluted share")

# Labels that contain "sales"/"revenue" but are not the consolidated top-line concept.
REVENUE_FALSE_FRIENDS = (
    "percent of", "% of", "organic", "change", "growth", "by segment", "by geographic",
    "disaggregated", "rental",
)

COST_QUALIFIERS = ("cost of", "costs of", "costs and expenses", "less", "expense")


def _label_score(label: str, alias: str) -> float:
    text = _normalise(label)
    alias = _normalise(alias)
    if text.startswith(COST_QUALIFIERS) and not alias.startswith(COST_QUALIFIERS):
        return 0.0
    if alias in {"sales", "revenue", "net sales", "total revenue", "net revenue",
                 "total net revenue", "net operating revenues"}:
        if any(friend in text for friend in REVENUE_FALSE_FRIENDS):
            return 0.0
    score = _base_label_score(text, alias)
    if score and any(qualifier in text for qualifier in QUALIFIERS):
        score -= 2.0
    # A bare "sales" alias must not outrank an exact "net sales" when both exist; demote
    # partial "sales" matches that are longer phrases like "sales (millions)" unless exact.
    if alias == "sales" and text != "sales" and "net sales" not in text:
        score = min(score, 1.5)
    return max(0.0, score)


def _base_label_score(text: str, alias: str) -> float:
    if text == alias:
        return 3.0
    if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
        return 2.0 + min(len(alias.split()), 4) / 10
    alias_tokens = set(alias.split())
    label_tokens = set(text.split())
    if alias_tokens and alias_tokens <= label_tokens:
        return 1.0
    return 0.0


@dataclass(slots=True)
class Resolution:
    status: str
    concept: str
    period: str
    cell: Cell | None = None
    reason: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    vintage: dict[str, Any] | None = None
    score: float = 0.0
    xbrl_status: str = "unavailable: no XBRL fact table in this corpus"
    resolver_version: str = RESOLVER_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "concept": self.concept, "period": self.period,
            "reason": self.reason, "candidates": self.candidates, "vintage": self.vintage,
            "score": round(self.score, 3), "resolver_version": self.resolver_version,
            "xbrl_status": self.xbrl_status,
            "cell": None if self.cell is None else {
                "cell_id": self.cell.cell_id, "row_label": self.cell.row_label,
                "column_label": self.cell.column_label, "raw": self.cell.raw,
                "value": self.cell.value, "period": self.cell.period,
                "scale": self.cell.scale, "currency": self.cell.currency,
                "document_id": self.cell.document_id, "accession": self.cell.accession,
                "table_id": self.cell.table_id, "row": self.cell.row,
                "column": self.cell.column, "section_path": self.cell.section_path,
                "source_sha256": self.cell.source_sha256,
            },
        }


class ConceptResolver:
    def __init__(self, engine: Any) -> None:
        self.answers = FinancialAnswerEngine(engine)
        self.engine = engine

    def _document_meta(self, issuer_id: str) -> dict[str, dict[str, Any]]:
        rows = self.engine.db.query(
            "SELECT document_id, accession, filed_date, period_of_report, availability_time "
            "FROM knowledge_document WHERE issuer_id = ? AND form_type = '10-K'", (issuer_id,))
        return {row["document_id"]: dict(row) for row in rows}

    def resolve(self, issuer_id: str, concept_key: str, period: str, cutoff: str,
                *, context: str = "consolidated") -> Resolution:
        concept = CONCEPTS.get(concept_key)
        if concept is None:
            return Resolution("unsupported_concept", concept_key, period,
                              reason="concept_not_registered")
        cells = [cell for cell in self.answers.cells(issuer_id, cutoff)
                 if cell.period == period and cell.status == "verified"]
        scored: list[tuple[float, Cell, bool]] = []
        for cell in cells:
            score = max((_label_score(cell.row_label, alias) for alias in concept.aliases),
                        default=0.0)
            if score <= 0:
                continue
            haystack = _normalise(cell.section_path + " " + (cell.table_caption or "")
                                  + " " + cell.column_label)
            if context == "consolidated" and _normalise(cell.row_label).startswith("consolidated"):
                score += 0.5
            family = cell.statement_family or "unknown"
            expected = "balance_sheet" if concept.statement == "balance" else concept.statement
            if family == expected:
                score += 1.0
            elif family != "unknown":
                score -= 2.0
            if context == "consolidated":
                if cell.entity_scope == "consolidated":
                    score += 1.0
                elif cell.entity_scope in {"parent", "segment"}:
                    score -= 3.0
            scope = (cell.entity_scope if cell.entity_scope != "unknown"
                     else statement_scope(cell.section_path, cell.table_caption))
            if context == "consolidated":
                if scope == "consolidated":
                    score += 1.0
                elif scope in {"parent", "segment"}:
                    score -= 3.0
            on_statement = (family == expected or any(
                hint in haystack for hint in STATEMENT_HINTS.get(concept.statement, ())))
            if on_statement:
                score += 0.5
            if concept.segment_sensitive and context == "consolidated":
                label = _normalise(cell.row_label)
                if any(marker in label for marker in SEGMENT_MARKERS):
                    score -= 1.5
            scored.append((score, cell, on_statement))
        # A balance-sheet concept must come from the balance sheet when that statement is present;
        # an Item 15 schedule or a note is not the consolidated statement.
        companions = COMPANION_ROWS.get(concept_key)
        if companions and scored:
            labels_by_table: dict[str, set[str]] = {}
            for cell in cells:
                labels_by_table.setdefault(cell.table_id, set()).add(_normalise(cell.row_label))
            def complete(cell: Cell) -> bool:
                labels = labels_by_table.get(cell.table_id, set())
                return all(any(marker in label for label in labels for marker in group)
                           for group in companions)
            filtered = [(score, cell, flag) for score, cell, flag in scored if complete(cell)]
            if filtered:
                scored = filtered
        if any(flag for _, _, flag in scored):
            scored = [(score, cell, flag) for score, cell, flag in scored if flag]
        expected_family = "balance_sheet" if concept.statement == "balance" else concept.statement
        if any(cell.statement_family == expected_family for _, cell, _ in scored):
            scored = [(score, cell, flag) for score, cell, flag in scored
                      if cell.statement_family == expected_family]
        if context == "consolidated" and any(
                cell.entity_scope == "consolidated" for _, cell, _ in scored):
            scored = [(score, cell, flag) for score, cell, flag in scored
                      if cell.entity_scope == "consolidated"]
        # Consolidated scope wins over parent-company and segment presentations of the same label.
        if context == "consolidated" and any(
                (cell.entity_scope if cell.entity_scope != "unknown"
                 else statement_scope(cell.section_path, cell.table_caption)) == "consolidated"
                for _, cell, _ in scored):
            scored = [(score, cell, flag) for score, cell, flag in scored
                      if (cell.entity_scope if cell.entity_scope != "unknown"
                          else statement_scope(cell.section_path, cell.table_caption))
                      == "consolidated"]
        if not scored:
            return Resolution("not_found", concept_key, period, reason="no_candidate_row")
        # An exact alias ("net sales" == "net sales") outranks a longer phrase that merely
        # contains it ("sales (millions)", "organic sales"); conflicting exact matches still
        # remain ambiguous below.
        exact = [(score, cell, flag) for score, cell, flag in scored
                 if _normalise(cell.row_label) in {_normalise(a) for a in concept.aliases}]
        if exact:
            scored = exact
        best = max(score for score, _, _ in scored)
        finalists = [(score, cell) for score, cell, _ in scored if score == best]
        # A token-subset match (score 1.0) is only a candidate: "total current assets" and
        # "state and local income taxes" must not satisfy total assets or net income.
        if best < 2.0:
            return Resolution("ambiguous", concept_key, period, reason="weak_alias_match",
                              candidates=[self._candidate(cell, score) for score, cell in finalists])
        cells_final = [cell for _, cell in finalists]
        meta = self._document_meta(issuer_id)
        # Two different values in one filing are an ambiguity. A disagreement across filings is a
        # vintage/restatement question and is handled below as a refusal with both vintages shown.
        per_document: dict[str, set[str]] = {}
        for cell in cells_final:
            per_document.setdefault(cell.document_id, set()).add(cell.value or "")
        if any(len(values) > 1 for values in per_document.values()):
            return Resolution("ambiguous", concept_key, period, reason="conflicting_row_values",
                              candidates=[self._candidate(cell, best) for cell in cells_final])

        def rank(cell: Cell) -> tuple[int, str]:
            info = meta.get(cell.document_id, {})
            original = str(info.get("period_of_report") or "")[:4] == str(period)
            return (0 if original else 1, str(info.get("filed_date") or ""))

        chosen = sorted(cells_final, key=rank)[0]
        vintage = meta.get(chosen.document_id, {})
        # Historical vintage policy: for a fiscal year, the filing whose own period is that year is
        # the original statement. If another available filing reports a different value for the
        # same concept and period, the restatement status is unresolved, so Atlas refuses.
        conflicts = []
        for cell in cells:
            if cell.document_id == chosen.document_id or cell.value == chosen.value:
                continue
            # Only the same statement in another vintage can contradict this fact. A revenue
            # row from a note or segment table is a different disclosure, not a restatement.
            if (cell.statement_family != chosen.statement_family
                    or cell.entity_scope != chosen.entity_scope
                    or cell.table_id == chosen.table_id):
                continue
            score = max((_label_score(cell.row_label, alias) for alias in concept.aliases),
                        default=0.0)
            if score < 2.0:
                continue
            if concept.segment_sensitive and context == "consolidated":
                if any(marker in _normalise(cell.row_label) for marker in SEGMENT_MARKERS):
                    continue
            other = meta.get(cell.document_id, {})
            # Any other vintage reporting a different value for the same concept and period is an
            # unresolved restatement signal, even when it reports the period as a comparative.
            conflicts.append({"document_id": cell.document_id,
                              "accession": cell.accession, "value": cell.value,
                              "raw": cell.raw, "filed_date": other.get("filed_date"),
                              "period_of_report": other.get("period_of_report")})
        if conflicts and all(item["value"] == chosen.value for item in conflicts):
            conflicts = []
        if conflicts:
            return Resolution("vintage_conflict", concept_key, period,
                              reason="multiple_filings_disagree",
                              candidates=conflicts + [self._candidate(chosen, best)],
                              vintage={**vintage, "document_id": chosen.document_id})
        return Resolution("resolved", concept_key, period, cell=chosen, score=best,
                          vintage={"document_id": chosen.document_id,
                                   "accession": chosen.accession,
                                   "filed_date": vintage.get("filed_date"),
                                   "period_of_report": vintage.get("period_of_report"),
                                   "selection_policy": "filing whose own period is the requested "
                                                      "year; disagreements refused"})

    @staticmethod
    def _candidate(cell: Cell, score: float) -> dict[str, Any]:
        return {"row_label": cell.row_label, "period": cell.period, "value": cell.value,
                "raw": cell.raw, "document_id": cell.document_id, "score": round(score, 3)}


__all__ = ["CONCEPTS", "Concept", "ConceptResolver", "Resolution", "RESOLVER_VERSION"]


@dataclass(frozen=True, slots=True)
class ResolvedFinancialInput:
    """Immutable evidence binding: identity of one verified cell, carried to FEC."""

    issuer_id: str
    concept: str
    document_id: str
    accession: str
    table_id: str
    unit_id: str
    cell_id: str
    row: int
    column: int
    row_label: str
    column_label: str
    period: str | None
    currency: str | None
    scale: int | None
    value: str | None
    raw: str
    source_table_sha256: str
    statement_title: str | None
    statement_family: str
    entity_scope: str
    availability_time: str | None
    availability_precision: str | None
    rights: str | None
    resolver_version: str
    rationale: str


def bind(resolution: "Resolution", issuer_id: str, concept: str) -> ResolvedFinancialInput | None:
    """Turn a resolved cell into a binding. Ambiguous or unresolved results cannot be bound."""
    cell = resolution.cell
    if resolution.status != "resolved" or cell is None:
        return None
    rationale = (f"label match score {resolution.score:.2f}; "
                 f"statement={cell.statement_family}/{cell.entity_scope}; "
                 f"period={cell.period}; scale={cell.scale}")
    return ResolvedFinancialInput(
        issuer_id=issuer_id, concept=concept, document_id=cell.document_id,
        accession=cell.accession, table_id=cell.table_id, unit_id=cell.unit_id,
        cell_id=cell.cell_id, row=cell.row, column=cell.column, row_label=cell.row_label,
        column_label=cell.column_label, period=cell.period, currency=cell.currency,
        scale=cell.scale, value=cell.value, raw=cell.raw,
        source_table_sha256=cell.source_sha256, statement_title=cell.statement_title,
        statement_family=cell.statement_family, entity_scope=cell.entity_scope,
        availability_time=cell.availability_time,
        availability_precision=cell.availability_precision, rights=cell.rights,
        resolver_version=RESOLVER_VERSION, rationale=rationale)


__all__ += ["ResolvedFinancialInput", "bind"]
