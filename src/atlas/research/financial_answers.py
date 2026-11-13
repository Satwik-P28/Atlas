"""Bounded financial-answer compiler (version 9.6.2).

A financial answer is compiled from verified table cells, never guessed. Every answer identifies
the cells it used, their periods, units and hashes, the formula, and an independent recomputation.
When an input is missing, ambiguous or unit-incompatible, the engine abstains with a reason code.

The operators mirror the Financial-Economic Compiler's semantics (Decimal arithmetic, explicit
units), but this module deliberately does not evaluate arbitrary FEC programs: it supports a fixed
set of financial relationships that can be checked against printed cells.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from .table_cells import Cell, cell_as_of, extract_cells

ENGINE_VERSION = "9.6.2"
OPERATOR_VERSION = "fec-table-9.6.2"
ABSTENTION_REASONS = {
    "no_verified_cells",
    "metric_not_found",
    "metric_ambiguous",
    "period_not_found",
    "input_unverified",
    "unit_mismatch",
    "period_mismatch",
    "zero_denominator",
    "missing_input",
    "insufficient_inputs",
    "future_evidence",
}


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z]{3,}", text.lower())}


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        __import__("json").dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


@dataclass(slots=True)
class InputRef:
    cell: Cell


class FinancialAnswerEngine:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.db = engine.db

    # ---------------------------------------------------------------- evidence
    def cells(self, issuer_id: str, cutoff: str | None) -> list[Cell]:
        documents = self.db.query(
            "SELECT document_id, accession, availability_time, availability_precision, rights "
            "FROM knowledge_document WHERE issuer_id = ? AND form_type = '10-K' "
            "AND status = 'indexed'", (issuer_id,))
        out: list[Cell] = []
        for document in documents:
            if cutoff and document["availability_time"] and document["availability_time"] > cutoff:
                continue
            tables = self.db.query(
                "SELECT table_id, unit_id, section_path, caption, units, footnotes, rows_json, sha256 "
                "FROM knowledge_table WHERE document_id = ?", (document["document_id"],))
            for table in tables:
                row = dict(table)
                row["rows"] = __import__("json").loads(row.pop("rows_json"))
                row["footnotes"] = __import__("json").loads(row["footnotes"]) if row["footnotes"] else []
                out.extend(extract_cells(row, document=dict(document)))
        return out

    def find(self, cells: Iterable[Cell], metric: str, period: str) -> list[Cell]:
        """Resolve a metric to cells at one period.

        Matching is exact-label first, then token-set equality. Subset matching is rejected:
        "revenue" must not resolve to "Cost of revenue", which is a different concept.
        """
        wanted = _tokens(metric)
        phrase = metric.strip().lower()
        candidates = [cell for cell in cells
                      if cell.status == "verified" and (not period or cell.period == period)]
        exact = [cell for cell in candidates if cell.row_label.strip().lower() == phrase]
        if exact:
            return exact
        equal = [cell for cell in candidates if wanted and _tokens(cell.row_label) == wanted]
        return equal

    # ---------------------------------------------------------------- operators
    def lookup(self, issuer_id: str, cutoff: str, *, metric: str, period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        matches = self.find(cells, metric, period)
        if not matches:
            return self._refuse("metric_not_found", metric=metric, period=period)
        values = {cell.value for cell in matches}
        if len(matches) > 1 and len(values) > 1:
            return self._refuse("metric_ambiguous", metric=metric,
                                candidates=[cell.cell_id for cell in matches[:5]])
        cell = matches[0]
        return self._answer(
            value=Decimal(cell.value), answer_type="reported_value",
            metric=metric, period=period, cells=[cell],
            formula="lookup(cell)", limitations=[
                "Value is quoted from a verified table cell; no computation was performed."],
        )

    def percentage_change(self, issuer_id: str, cutoff: str, *, metric: str,
                          current_period: str, prior_period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        current = self.find(cells, metric, current_period)
        prior = self.find(cells, metric, prior_period)
        refusal = self._require(current, prior, current_period, prior_period)
        if refusal:
            return refusal
        cur, prev = current[0], prior[0]
        if Decimal(prev.value) == 0:
            return self._refuse("zero_denominator", metric=metric)
        value = (Decimal(cur.value) - Decimal(prev.value)) / Decimal(prev.value) * 100
        return self._answer(
            value=value, answer_type="percentage_change", metric=metric,
            period=f"{current_period} vs {prior_period}", cells=[cur, prev],
            formula="(current - prior) / prior * 100", limitations=[
                "Both cells must report the same concept; the row labels were required to match."],
        )

    def ratio(self, issuer_id: str, cutoff: str, *, numerator: str, denominator: str,
              period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        top = self.find(cells, numerator, period)
        bottom = self.find(cells, denominator, period)
        refusal = self._require(top, bottom, period, period, allow_same_period=True)
        if refusal:
            return refusal
        if Decimal(bottom[0].value) == 0:
            return self._refuse("zero_denominator", numerator=numerator, denominator=denominator)
        value = Decimal(top[0].value) / Decimal(bottom[0].value)
        return self._answer(
            value=value, answer_type="ratio", metric=f"{numerator} / {denominator}",
            period=period, cells=[top[0], bottom[0]],
            formula="numerator / denominator", limitations=[
                "Ratio is dimensionless; both inputs must share scale and currency."],
        )

    def margin(self, issuer_id: str, cutoff: str, *, numerator: str, revenue: str,
               period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        top = self.find(cells, numerator, period)
        bottom = self.find(cells, revenue, period)
        refusal = self._require(top, bottom, period, period, allow_same_period=True)
        if refusal:
            return refusal
        if Decimal(bottom[0].value) == 0:
            return self._refuse("zero_denominator", numerator=numerator, revenue=revenue)
        value = Decimal(top[0].value) / Decimal(bottom[0].value) * 100
        return self._answer(
            value=value, answer_type="margin_percent", metric=f"{numerator} margin",
            period=period, cells=[top[0], bottom[0]],
            formula="numerator / revenue * 100", limitations=[
                "Margin definition follows the two row labels used; a different definition in the "
                "filing would produce a different number."],
        )

    def total(self, issuer_id: str, cutoff: str, *, components: list[str],
              period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        chosen: list[Cell] = []
        for component in components:
            matches = self.find(cells, component, period)
            if not matches:
                return self._refuse("missing_input", component=component, period=period)
            chosen.append(matches[0])
        value = sum((Decimal(cell.value) for cell in chosen), Decimal(0))
        return self._answer(
            value=value, answer_type="sum", metric=" + ".join(components), period=period,
            cells=chosen, formula="sum(components)", limitations=[
                "Components must be exhaustive and non-overlapping; that was assumed, not proven."],
        )

    # ---------------------------------------------------------------- plumbing
    def _require(self, left: list[Cell], right: list[Cell], left_period: str, right_period: str,
                 allow_same_period: bool = False) -> dict[str, Any] | None:
        if not left or not right:
            return self._refuse("missing_input",
                                missing=[p for p, cells in ((left_period, left), (right_period, right))
                                         if not cells])
        if len({cell.value for cell in left}) > 1 or len({cell.value for cell in right}) > 1:
            return self._refuse("metric_ambiguous")
        a, b = left[0], right[0]
        if not allow_same_period and a.period == b.period:
            return self._refuse("period_mismatch", detail="both inputs report the same period")
        if (a.scale, a.currency) != (b.scale, b.currency):
            return self._refuse("unit_mismatch", left=[a.scale, a.currency],
                                right=[b.scale, b.currency])
        return None

    def _answer(self, *, value: Decimal, answer_type: str, metric: str, period: str,
                cells: list[Cell], formula: str, limitations: list[str]) -> dict[str, Any]:
        rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Independent recomputation: parse the raw strings again, without reusing Cell.value.
        from .table_cells import parse_number
        recomputed: Decimal | None = None
        if formula == "lookup(cell)":
            recomputed = parse_number(cells[0].raw)[0]
        elif formula.startswith("(current"):
            cur, prior = (parse_number(cell.raw)[0] for cell in cells)
            recomputed = (cur - prior) / prior * 100 if cur is not None and prior is not None else None
        elif formula.startswith("numerator / denominator"):
            top, bottom = (parse_number(cell.raw)[0] for cell in cells)
            recomputed = top / bottom if top is not None and bottom not in (None, 0) else None
        elif formula.startswith("numerator / revenue"):
            top, bottom = (parse_number(cell.raw)[0] for cell in cells)
            recomputed = top / bottom * 100 if top is not None and bottom not in (None, 0) else None
        elif formula.startswith("sum"):
            parts = [parse_number(cell.raw)[0] for cell in cells]
            recomputed = sum(parts, Decimal(0)) if all(part is not None for part in parts) else None
        independent = recomputed is not None and recomputed.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP) == rounded
        citations = []
        for cell in cells:
            try:
                unit = self.engine.unit(cell.unit_id)
            except Exception:  # noqa: BLE001 - a missing passage is a validation failure
                unit = None
            citations.append({
                "cell_id": cell.cell_id, "unit_id": cell.unit_id, "table_id": cell.table_id,
                "document_id": cell.document_id, "accession": cell.accession,
                "section_path": cell.section_path, "row": cell.row, "column": cell.column,
                "row_label": cell.row_label, "column_label": cell.column_label,
                "period": cell.period, "raw": cell.raw, "value": cell.value,
                "scale": cell.scale, "currency": cell.currency,
                "unit_sha256": (unit or {}).get("sha256"),
                "availability_time": cell.availability_time,
                "availability_precision": cell.availability_precision,
                "rights": cell.rights,
            })
        if "percent" in answer_type:
            unit = {"kind": "percent", "scale": 0}
        elif answer_type == "ratio":
            unit = {"kind": "ratio", "scale": 0}
        else:
            unit = {"kind": cells[0].unit, "scale": cells[0].scale}
        payload = {
            "engine_version": ENGINE_VERSION, "operator_version": OPERATOR_VERSION,
            "answer_type": answer_type, "value": str(rounded), "period": period,
            "formula": formula, "cells": [cell.cell_id for cell in cells],
            "verified": independent,
        }
        return {
            "outcome": "answered" if independent else "unverified_calculation",
            "answer_type": answer_type,
            "value": str(rounded),
            "unit": unit,
            "currency": cells[0].currency,
            "period": period,
            "metric": metric,
            "formula": formula,
            "operator_version": OPERATOR_VERSION,
            "engine_version": ENGINE_VERSION,
            "inputs": citations,
            "verification": {
                "independent_recomputation": independent,
                "rounding_policy": "half_up_2dp",
                "method": "re-parse raw text and recompute",
            },
            "limitations": limitations + [
                "Computed values are never presented as quoted filings; the source cells are the "
                "authoritative statement.",
            ],
            "reproducibility_fingerprint": _fingerprint(payload),
        }

    def _refuse(self, reason: str, **context: Any) -> dict[str, Any]:
        assert reason in ABSTENTION_REASONS, reason
        return {
            "outcome": "abstained", "reason": reason, "context": context,
            "engine_version": ENGINE_VERSION, "operator_version": OPERATOR_VERSION,
            "limitations": ["Atlas does not guess missing, ambiguous or unit-incompatible inputs."],
        }


__all__ = ["FinancialAnswerEngine", "ENGINE_VERSION", "OPERATOR_VERSION", "ABSTENTION_REASONS"]
