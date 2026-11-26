"""Geometry-aware concept resolution (version 10.0.1).

The baseline resolver (``financial_concepts.ConceptResolver``) searches cells that the
knowledge engine flattened out of the filing. That representation loses merged header groups
and row structure, so a printed number can be attributed to the wrong year or to a banner row
inside a segment table.

This resolver searches the same filing bytes through ``table_geometry`` instead. It keeps the
baseline's concept vocabulary and label scoring unchanged — the only thing that differs is
where the period, unit and statement identity come from — so a difference in outcomes is
attributable to geometry rather than to a richer lexicon.

Policy, in order:

1. a candidate must print an alias with a score of at least 2.0 (same threshold as baseline);
2. the table must have a detected unit scale, or the amount is not usable;
3. the table's statement family must match the concept's statement — tables whose family is
   unknown are a weaker tier and are only used when no statement table matched;
4. segment and parent-company tables are not the consolidated statement;
5. the column must carry the requested period in its own header (or by the row-order
   fallback), otherwise the row matched but the period did not: ``period_not_located``;
6. two different amounts for the same concept and period is an ambiguity, not a choice.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .financial_concepts import (
    COMPANION_ROWS,
    CONCEPTS,
    SEGMENT_MARKERS,
    _label_score,
    _normalise,
    component_sum_supports_total,
)
from .statement_scope import INCOMPATIBLE_SCOPES
from .table_geometry import GeometryTable, parse_tables
from .table_cells import parse_number

RESOLVER_VERSION = "10.1.0"
_SCORE_FLOOR = 2.0
#: Rows that only a primary statement prints. Used to decide whether an untitled table has the
#: shape of a statement, and to choose the most statement-like table when two untitled tables
#: disagree. Never used to accept a value on its own.
STATEMENT_SHAPE = {
    "income": ("revenue", "revenues", "sales", "cost of sales", "cost of revenue",
               "cost of goods sold", "cost of products", "gross profit", "gross margin",
               "operating income", "operating profit", "income from operations",
               "operating expenses", "net income", "net loss", "diluted", "basic",
               "interest income", "interest expense"),
    "balance_sheet": ("total assets", "total liabilities", "total equity",
                      "total stockholders", "total shareholders", "current assets",
                      "current liabilities", "cash and cash equivalents", "retained earnings"),
    "cash_flow": ("operating activities", "investing activities", "financing activities",
                  "net cash"),
}
ATTRIBUTION_MARKERS = ("attributable", "noncontrolling", "non-controlling")
_SEGMENT_TABLE_MARKERS = ("reportable segment", "segment information", "by segment",
                          "segment results", "business segment", "segments")


class SourceIntegrityError(ValueError):
    """The bytes to be parsed are not the bytes the corpus manifest authenticated."""


@dataclass(slots=True)
class GeometryDocument:
    """One filing document: archived bytes plus the metadata needed to cite them."""

    accession: str
    document_sha256: str
    cik: str = ""
    availability_time: str | None = None
    rights: str | None = None
    tables: list[GeometryTable] = field(default_factory=list)

    @classmethod
    def from_html(cls, html: str | bytes, *, accession: str, document_sha256: str | None = None,
                  cik: str = "", availability_time: str | None = None,
                  rights: str | None = None) -> "GeometryDocument":
        """Parse one filing, refusing bytes that do not match the expected digest.

        A digest passed alongside the bytes is only meaningful if it is recomputed here: the
        caller's field is metadata, the bytes are the evidence. Without that check, mutated
        archived HTML could be analysed while still carrying the committed original digest.
        """
        payload = html.encode("utf-8") if isinstance(html, str) else html
        digest = hashlib.sha256(payload).hexdigest()
        if document_sha256 is not None and digest != document_sha256:
            raise SourceIntegrityError(
                f"snapshot digest mismatch for {accession}: expected {document_sha256}, "
                f"bytes are {digest}")
        return cls(accession=accession, document_sha256=digest, cik=cik,
                   availability_time=availability_time, rights=rights,
                   tables=parse_tables(payload))


@dataclass(slots=True)
class GeometryCellRef:
    accession: str
    document_sha256: str
    table_index: int
    table_digest: str
    table_sha: str
    row: int
    column: int
    row_label: str
    column_header: str
    period: str | None
    scale: int | None
    currency: str | None
    raw: str
    value: str
    statement_family: str | None
    statement_title: str | None
    entity_scope: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "accession": self.accession, "document_sha256": self.document_sha256,
            "table_index": self.table_index, "table_digest": self.table_digest,
            "table_sha": self.table_sha, "row": self.row, "column": self.column,
            "row_label": self.row_label, "column_header": self.column_header,
            "period": self.period, "scale": self.scale, "currency": self.currency,
            "raw": self.raw, "value": self.value,
            "statement_family": self.statement_family,
            "statement_title": self.statement_title, "entity_scope": self.entity_scope,
        }


@dataclass(slots=True)
class GeometryResolution:
    status: str
    concept: str
    period: str
    cell: GeometryCellRef | None = None
    reason: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    resolver_version: str = RESOLVER_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "concept": self.concept, "period": self.period,
                "reason": self.reason, "score": round(self.score, 3),
                "resolver_version": self.resolver_version,
                "cell": None if self.cell is None else self.cell.as_dict(),
                "candidates": self.candidates}


def _expected_family(concept_statement: str) -> str:
    return "balance_sheet" if concept_statement == "balance" else concept_statement


def _is_segment_table(table: GeometryTable) -> bool:
    haystack = _normalise(f"{table.caption or ''} {table.statement_title or ''} "
                          f"{table.preceding_text[-300:]}")
    if table.entity_scope == "segment":
        return True
    return any(marker in haystack for marker in _SEGMENT_TABLE_MARKERS)


def _row_label(table: GeometryTable, row: int) -> str:
    return table.label_of(row)


class GeometryResolver:
    def __init__(self, documents: Iterable[GeometryDocument]) -> None:
        self.documents = [doc for doc in documents]

    # ------------------------------------------------------------------ resolution
    def resolve(self, concept_key: str, period: str, *, cutoff: str | None = None,
                cik: str | None = None, accession: str | None = None) -> GeometryResolution:
        """Resolve one concept for one issuer, optionally for one exact filing.

        ``cik`` scopes the search to that issuer's filings; without it another company's
        statement could satisfy the request. ``accession`` goes further and pins the source to
        one document, which is what an accession-scoped question means: the FY2017 figure as
        that filing printed it, not whichever newer filing happens to match the period first.
        Leaving ``accession`` unset is the separate as-of mode, where several filings of the
        same issuer may be searched up to ``cutoff`` and a disagreement is a vintage conflict.
        """
        if accession is not None and not any(doc.accession == accession for doc in self.documents):
            return GeometryResolution("not_found", concept_key, period,
                                      reason="accession_not_in_corpus")
        concept = CONCEPTS.get(concept_key)
        if concept is None:
            return GeometryResolution("unsupported_concept", concept_key, period,
                                      reason="concept_not_registered")
        expected = _expected_family(concept.statement)
        strong: list[tuple[float, GeometryCellRef]] = []
        weak: list[tuple[float, GeometryCellRef]] = []
        label_matches = 0
        period_misses: list[GeometryCellRef] = []
        unit_misses = 0
        note_matches = 0
        scope_misses = 0
        notes: list[tuple[float, GeometryCellRef, int]] = []
        shapes: dict[tuple[str, int], int] = {}
        companions = COMPANION_ROWS.get(concept_key)
        for document in self.documents:
            if accession is not None and document.accession != accession:
                continue
            if cik and document.cik and document.cik != cik:
                continue
            if cutoff and document.availability_time and document.availability_time > cutoff:
                continue
            for table in document.tables:
                family = table.statement_family
                # Notes and segment disclosures print statement labels with different numbers.
                # They are not the statement and never compete with one.
                if family in {"note", "segment"}:
                    note_matches += self._concept_rows(table, concept)
                    consolidated_group = table.has_column_groups and any(
                        table.column_scope(column) == "consolidated"
                        for column in range(table.width))
                    if (not _scope_allows(table, expected) and not consolidated_group
                            and not (companions
                                     and self._table_has_companions_shape(table, companions))):
                        continue
                    for row in range(table.body_start, len(table.grid)):
                        label = _row_label(table, row)
                        score = max((_label_score(label, alias) for alias in concept.aliases),
                                    default=0.0)
                        if score < _SCORE_FLOOR or table.scale is None:
                            continue
                        reference = self._cell_at(document, table, row, period)
                        if reference is not None and reference.period == period:
                            notes.append((score, reference, _statement_shape(table, expected)))
                    continue
                if _is_segment_table(table):
                    continue
                if family is not None and family != expected:
                    continue
                if not _scope_allows(table, expected):
                    if self._concept_rows(table, concept):
                        label_matches += 1
                    scope_misses += 1
                    continue
                if table.has_column_groups and not any(
                        table.column_scope(column) == "consolidated"
                        for column in range(table.width)):
                    scope_misses += 1
                    continue
                if table.scale is None:
                    # Only counts against this concept if the table carried the concept at all.
                    if any(_label_score(_row_label(table, row), alias) >= _SCORE_FLOOR
                           for row in range(table.body_start, len(table.grid))
                           for alias in concept.aliases):
                        unit_misses += 1
                    continue
                for row in range(table.body_start, len(table.grid)):
                    label = _row_label(table, row)
                    if not label:
                        continue
                    score = max((_label_score(label, alias) for alias in concept.aliases), default=0.0)
                    if score < _SCORE_FLOOR:
                        continue
                    if "total" in _normalise(label).split():
                        score += 0.2
                    label_matches += 1
                    if concept.segment_sensitive and any(
                            marker in _normalise(label) for marker in SEGMENT_MARKERS):
                        continue
                    reference = self._cell_at(document, table, row, period)
                    if reference is None:
                        continue
                    if reference.period != period:
                        period_misses.append(reference)
                        continue
                    shapes[(reference.accession, reference.table_index)] = _statement_shape(
                        table, expected)
                    if family == expected:
                        strong.append((score, reference))
                        continue
                    # An unidentified table must prove it is a primary statement: either by
                    # printing the companion rows, or by carrying enough statement line items
                    # that it cannot be a one-row summary.
                    if companions and not self._table_has_companions(reference, companions):
                        if shapes[(reference.accession, reference.table_index)] < 3:
                            continue
                    weak.append((score, reference))
        pool = strong or weak
        if not pool and not strong:
            # Last resort: a note or schedule that prints the concept. Used only when no statement
            # did, when every such row agrees on one value, and when the table has at least the
            # shape of a financial schedule. The resolution records that it is note-derived.
            if notes and any(shape >= 2 or reference.entity_scope == "consolidated"
                             for _, reference, shape in notes):
                values = {reference.value for _, reference, _ in notes}
                if len(values) == 1:
                    label_matches += 0
                    best_note = max(notes, key=lambda item: (item[0], item[2]))
                    return GeometryResolution(
                        "resolved", concept_key, period, cell=best_note[1],
                        score=best_note[0],
                        candidates=[self._candidate(best_note[1], best_note[0])])
                return GeometryResolution(
                    "ambiguous", concept_key, period, reason="conflicting_note_values",
                    candidates=[self._candidate(reference, score)
                                for score, reference, _ in notes[:8]])
        if not pool:
            if period_misses:
                best = period_misses[0]
                return GeometryResolution(
                    "period_not_located", concept_key, period,
                    reason="row_matched_but_no_column_carries_the_requested_period",
                    candidates=[self._candidate(best, 0.0)], )
            if unit_misses and not label_matches:
                return GeometryResolution("unit_unresolved", concept_key, period,
                                          reason="matching_rows_have_no_detected_scale")
            if scope_misses and label_matches:
                return GeometryResolution("scope_mismatch", concept_key, period,
                                          reason="only_non_consolidated_columns_carry_the_row")
            if note_matches and not label_matches:
                return GeometryResolution("statement_scope_unresolved", concept_key, period,
                                          reason="concept_printed_only_in_notes_or_schedules")
            return GeometryResolution("not_found", concept_key, period, reason="no_candidate_row")
        # Companion rows keep a labelled subtotal from being read as the primary statement row.
        companions = COMPANION_ROWS.get(concept_key)
        if companions and len({(ref.accession, ref.table_index) for _, ref in pool}) > 1:
            filtered = [(score, ref) for score, ref in pool
                        if self._table_has_companions(ref, companions)]
            if filtered:
                pool = filtered
        # Only rows that print the concept with equal strength compete. A weak phrase match
        # ("Net income attributable to ...") must not manufacture an ambiguity against an
        # exact row, which is the baseline's existing rule and is kept here on purpose.
        best = max(score for score, _ in pool)
        pool = [(score, ref) for score, ref in pool if score == best]
        # A top-line concept is printed both as "Sales" (a component) and as "Total revenue"
        # (the statement total). When exactly one candidate prints "total", it is the total.
        totals = [(score, ref) for score, ref in pool if "total" in _normalise(ref.row_label)]
        if totals and len(totals) < len(pool):
            others = [(score, ref) for score, ref in pool if (score, ref) not in totals]
            if component_sum_supports_total([ref.value for _, ref in others],
                                            [ref.value for _, ref in totals]):
                pool = totals
        values = {ref.value for _, ref in pool}
        if len(values) > 1 and not strong:
            # Two untitled tables disagree. The consolidated statement prints many more line
            # items than a segment summary; if one table is uniquely the most statement-like and
            # its rows agree, use it. Otherwise the conflict is real and the answer is refused.
            counts = {key: shapes.get(key, 0) for key in
                      {(ref.accession, ref.table_index) for _, ref in pool}}
            deepest = max(counts.values(), default=0)
            top = [(score, ref) for score, ref in pool
                   if counts.get((ref.accession, ref.table_index), 0) == deepest]
            if deepest >= 4 and len({ref.value for _, ref in top}) == 1:
                pool = top
                values = {ref.value for _, ref in pool}
        if len(values) > 1:
            return GeometryResolution(
                "ambiguous", concept_key, period, reason="conflicting_row_values",
                candidates=[self._candidate(ref, score) for score, ref in pool[:8]])
        # Prefer a citation whose own column header names the period over one that relied on the
        # row-order fallback: the number may be right either way, but only the first is evidence
        # that the reader can check against the filing.
        def rank(item: tuple[float, GeometryCellRef]) -> tuple[int, int, int]:
            score, reference = item
            header = _normalise(reference.column_header or "")
            explicit = period in header or f"20{period[-2:]}" in header
            return (0 if explicit else 1, -int(score * 100), -reference.table_index)

        best_score, chosen = min(pool, key=rank)[:2]
        if concept_key == "net_income":
            conflict = self._attribution_conflict(chosen)
            if conflict is not None:
                return GeometryResolution(
                    "ambiguous", concept_key, period, reason="definitional_ambiguity",
                    candidates=[self._candidate(chosen, best_score),
                                self._candidate(conflict, 2.0)])
        return GeometryResolution("resolved", concept_key, period, cell=chosen,
                                  score=best_score, candidates=[self._candidate(chosen, best_score)])

    # ------------------------------------------------------------------ helpers
    def _table_has_companions_shape(self, table: GeometryTable,
                                    companions: tuple[tuple[str, ...], ...]) -> bool:
        labels = [_normalise(_row_label(table, row))
                  for row in range(table.body_start, len(table.grid))]
        return all(any(marker in label for label in labels for marker in group)
                   for group in companions)

    def _attribution_conflict(self, chosen: GeometryCellRef) -> GeometryCellRef | None:
        """A different net-income definition printed in the same statement.

        "Net income (loss)" and "Net income attributable to the parent" are two numbers, and the
        difference is noncontrolling interests. A question that says only "net income" names
        neither, so the two together are a definitional ambiguity rather than a preference.
        """
        for document in self.documents:
            if document.accession != chosen.accession:
                continue
            for table in document.tables:
                if table.index != chosen.table_index:
                    continue
                for row in range(table.body_start, len(table.grid)):
                    label = _normalise(_row_label(table, row))
                    if not any(marker in label for marker in ATTRIBUTION_MARKERS):
                        continue
                    if "net" not in label or not ({"income", "earnings", "loss"} & set(label.split())):
                        continue
                    reference = self._cell_at(document, table, row, chosen.period or "")
                    if reference is not None and reference.value != chosen.value:
                        return reference
        return None

    @staticmethod
    def _concept_rows(table: GeometryTable, concept: Any) -> int:
        """How many rows in a non-statement table would have matched the concept's labels."""
        return sum(1 for row in range(table.body_start, len(table.grid))
                   if any(_label_score(_row_label(table, row), alias) >= _SCORE_FLOOR
                          for alias in concept.aliases))

    def _cell_at(self, document: GeometryDocument, table: GeometryTable, row: int,
                 period: str) -> GeometryCellRef | None:
        """The numeric cell in this row that sits under the requested period.

        A row can print several years. Returning the first number would attribute whichever
        column happened to come first, so the geometry period decides; the first numeric cell
        is kept only as a diagnostic for ``period_not_located``.
        """
        first: GeometryCellRef | None = None
        for column, cell in enumerate(table.grid[row]):
            if cell is None or not cell.text or column == 0:
                continue
            value, _sign, reason = parse_number(cell.text)
            if reason not in {"parsed", "percent"}:
                continue
            if table.column_scope(column) in {"segment", "adjustment"}:
                # A consolidating schedule prints the same label for each entity; only the
                # consolidated group answers a consolidated question.
                continue
            column_period = table.period_for(column, row)
            column_scope = table.column_scope(column)
            reference = GeometryCellRef(
                accession=document.accession, document_sha256=document.document_sha256,
                table_index=table.index, table_digest=table.digest,
                table_sha=_table_sha(table), row=row, column=column,
                row_label=_row_label(table, row), column_header=table.header_for(column),
                period=column_period, scale=table.scale, currency=table.currency,
                raw=cell.text, value=str(value), statement_family=table.statement_family,
                statement_title=table.statement_title,
                entity_scope=("consolidated" if column_scope == "consolidated"
                              else table.entity_scope))
            if column_period == period:
                return reference
            if first is None:
                first = reference
        return first

    def _table_has_companions(self, reference: GeometryCellRef,
                              companions: tuple[tuple[str, ...], ...]) -> bool:
        for document in self.documents:
            if document.accession != reference.accession:
                continue
            for table in document.tables:
                if table.index != reference.table_index:
                    continue
                labels = [_normalise(_row_label(table, row))
                          for row in range(table.body_start, len(table.grid))]
                return all(any(marker in label for label in labels for marker in group)
                           for group in companions)
        return False

    @staticmethod
    def _candidate(reference: GeometryCellRef, score: float) -> dict[str, Any]:
        return {**reference.as_dict(), "score": round(score, 3)}


def _table_sha(table: GeometryTable) -> str:
    return table.digest


def _statement_shape(table: GeometryTable, expected: str) -> int:
    markers = STATEMENT_SHAPE.get(expected, ())
    if not markers:
        return 0
    return sum(1 for row in range(table.body_start, len(table.grid))
               if any(marker in _normalise(_row_label(table, row)) for marker in markers))


def _scope_allows(table: GeometryTable, expected: str) -> bool:
    """Statement scope check: an explicit non-consolidated title is never the group total."""
    if table.entity_scope in INCOMPATIBLE_SCOPES:
        return False
    if expected == "balance_sheet" and table.entity_scope == "segment":
        return False
    return True


__all__ = ["GeometryCellRef", "GeometryDocument", "GeometryResolution", "GeometryResolver",
           "RESOLVER_VERSION", "SourceIntegrityError"]
