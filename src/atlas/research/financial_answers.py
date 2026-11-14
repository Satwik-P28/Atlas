"""Bounded financial-answer compiler on top of the Financial-Economic Compiler (9.6.3).

Every supported question is compiled into a typed FEC model, executed by
``atlas.fec.ExecutionEngine``, and then recomputed by
``atlas.research.financial_verification`` with independent parsing and ``Fraction`` arithmetic.
If the two disagree, Atlas refuses to present an answer.

The engine does not re-implement FEC arithmetic. What remains here is the mapping from verified
table cells to typed plan inputs, the financial validity rules (same concept, period, scale,
currency) and the evidence contract of the answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable

from atlas.fec import ExecutionEngine, compile_model
from atlas.fec.compiler import COMPILER_VERSION
from atlas.fec.operators import operator_versions

from .financial_verification import (
    VerificationError,
    evaluate as verify_evaluate,
    parse_raw,
    round_half_up,
)
from .table_cells import Cell, extract_cells

ENGINE_VERSION = "9.6.4"
OPERATOR_VERSION = COMPILER_VERSION
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
    "vintage_conflict",
    "verification_disagreement",
}
# Display precision by answer type. Exact Fraction/Decimal output is preserved separately.
_DISPLAY_PLACES = {
    "reported_value": 2,
    "sum": 2,
    "percentage_change": 2,
    "margin_percent": 2,
    "ratio": 4,
    "multiple": 4,
    "yield": 4,
    "duration": 4,
    "probability": 6,
    "basis_point_sensitivity": 4,
}
_ROUNDING_POLICY = "typed_half_up_by_answer_type"


@dataclass(slots=True)
class InputRef:
    cell: Cell


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _decimal(text: Any) -> Any:
    from decimal import Decimal
    try:
        return Decimal(str(text))
    except Exception:  # noqa: BLE001
        return None


def _fec_type(cell: Cell) -> str:
    if cell.currency == "USD":
        return "Money[USD]"
    if "share" in cell.row_label.lower():
        return "Shares"
    # Unknown unit: FEC still enforces arithmetic consistency, but no currency is claimed.
    return "Scalar"


def _compile_and_run(name: str, inputs: list[dict[str, Any]], nodes: list[dict[str, Any]],
                     output: str, values: dict[str, Any]) -> dict[str, Any]:
    spec = {
        "schema_version": "atlas.model.v1",
        "name": name,
        "version": "1.0.0",
        "interface": "graph",
        "inputs": inputs,
        "nodes": nodes,
        "outputs": {"value": output},
    }
    model = compile_model(spec)
    result = ExecutionEngine(use_cache=False).execute(model, values, persist=False)
    encoded = result["exact_outputs"]["value"]
    raw = encoded["value"] if isinstance(encoded, dict) else encoded
    return {
        "value": Decimal(str(raw)),
        "compiler_version": model.compiler_version,
        "fingerprint": result["fingerprint"],
        "run_id": result["run_id"],
        "trace": result["trace"],
        "operator_versions": result["manifest"]["operator_versions"],
        "spec": spec,
    }


def _decimal_to_fraction(value: Decimal) -> Fraction:
    return Fraction(value)


class FinancialAnswerEngine:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.db = engine.db

    # ---------------------------------------------------------------- evidence
    def cells(self, issuer_id: str, cutoff: str | None) -> list[Cell]:
        documents = self.db.query(
            "SELECT document_id, accession, availability_time, availability_precision, rights, "
            "filed_date FROM knowledge_document WHERE issuer_id = ? AND form_type = '10-K' "
            "AND status = 'indexed'", (issuer_id,))
        out: list[Cell] = []
        for document in documents:
            if cutoff and document["availability_time"] and document["availability_time"] > cutoff:
                continue
            tables = self.db.query(
                "SELECT table_id, unit_id, section_path, caption, units, footnotes, rows_json, sha256 "
                "FROM knowledge_table WHERE document_id = ?", (document["document_id"],))
            units = {unit["unit_id"]: dict(unit) for unit in self.db.query(
                "SELECT unit_id, ordinal, heading, body FROM knowledge_unit WHERE document_id = ?",
                (document["document_id"],))}
            for table in tables:
                row = dict(table)
                # Statement identity comes from the document's own text, not the truncated
                # section path ("Item 8"): the nearest statement title in this unit, then the
                # immediately preceding unit.
                statement = _statement_context(units, dict(table))
                row.update(statement)
                row["rows"] = json.loads(row.pop("rows_json"))
                notes = table["footnotes"]
                if not notes:
                    parsed_notes: list[str] = []
                else:
                    try:
                        candidate = json.loads(notes)
                        parsed_notes = candidate if isinstance(candidate, list) else [str(candidate)]
                    except ValueError:
                        parsed_notes = [str(notes)]
                row["footnotes"] = parsed_notes
                out.extend(extract_cells(row, document=dict(document)))
        return out

    def find(self, cells: Iterable[Cell], metric: str, period: str) -> list[Cell]:
        """Resolve a metric to cells at one period (exact label, then token-set equality)."""
        wanted = {token for token in _tokenize(metric)}
        phrase = metric.strip().lower()
        candidates = [cell for cell in cells
                      if cell.status == "verified" and (not period or cell.period == period)]
        exact = [cell for cell in candidates if cell.row_label.strip().lower() == phrase]
        if exact:
            return exact
        return [cell for cell in candidates if wanted and set(_tokenize(cell.row_label)) == wanted]

    # ---------------------------------------------------------------- bindings
    def validate_binding(self, binding: Any, cutoff: str) -> list[str]:
        """Revalidate a resolved binding against the store before any arithmetic."""
        problems: list[str] = []
        document = self.db.query_one(
            "SELECT document_id, issuer_id, accession, availability_time, rights "
            "FROM knowledge_document WHERE document_id = ?", (binding.document_id,))
        if document is None:
            return ["document_missing"]
        if document["issuer_id"] != binding.issuer_id:
            problems.append("issuer_mismatch")
        if binding.accession != document["accession"]:
            problems.append("accession_mismatch")
        available = binding.availability_time or document["availability_time"]
        if not available or available > cutoff:
            problems.append("future_evidence")
        table = self.db.query_one(
            "SELECT sha256, unit_id, rows_json FROM knowledge_table WHERE table_id = ?",
            (binding.table_id,))
        if table is None:
            problems.append("table_missing")
        else:
            if table["sha256"] != binding.source_table_sha256:
                problems.append("table_hash_mismatch")
            if table["unit_id"] != binding.unit_id:
                problems.append("unit_mismatch")
            rows = json.loads(table["rows_json"] or "[]")
            sourced = False
            if 0 <= binding.row < len(rows) and 0 <= binding.column < len(rows[binding.row]):
                sourced = " ".join(rows[binding.row][binding.column].split()) == binding.raw
            if not sourced:
                problems.append("cell_not_in_source")
            printed = set(re.findall(r"(?:19|20)\d{2}", table["rows_json"] or ""))
            if not binding.period or binding.period not in printed:
                problems.append("period_mismatch")
        try:
            unit = self.engine.unit(binding.unit_id)
        except Exception:  # noqa: BLE001
            unit = None
        if not unit:
            problems.append("unit_missing")
        else:
            body = (unit.get("body") or "").encode("utf-8")
            digest = hashlib.sha256(body).hexdigest()
            stored = unit.get("sha256")
            # A SHA field is not verification: recompute from stored bytes.
            if not stored or stored != digest:
                problems.append("unit_hash_mismatch")
        if binding.value is None or _decimal(binding.value) != parse_raw(binding.raw):
            problems.append("value_does_not_match_raw")
        if binding.scale is None:
            problems.append("scale_unknown")
        return problems

    def cell_from_binding(self, binding: Any) -> Cell:
        return Cell(
            document_id=binding.document_id, accession=binding.accession,
            table_id=binding.table_id, unit_id=binding.unit_id,
            section_path="", table_caption=binding.statement_title, row=binding.row,
            column=binding.column, row_label=binding.row_label,
            column_label=binding.column_label, period=binding.period,
            currency=binding.currency, unit=binding.currency, scale=binding.scale,
            sign_convention="plain", raw=binding.raw, value=binding.value,
            footnotes=[], status="verified", reason=None, extraction_method="binding",
            confidence="high", source_sha256=binding.source_table_sha256,
            availability_time=binding.availability_time,
            availability_precision=binding.availability_precision, rights=binding.rights,
            statement_title=binding.statement_title,
            statement_family=binding.statement_family, entity_scope=binding.entity_scope)

    def lookup_bound(self, binding: Any, cutoff: str) -> dict[str, Any]:
        return self._bound("lookup", [binding], cutoff, formula="lookup(cell)",
                           answer_type="reported_value", metric=binding.row_label,
                           period=binding.period or "")

    def percentage_change_bound(self, current: Any, prior: Any, cutoff: str,
                                metric: str) -> dict[str, Any]:
        return self._bound("percentage_change", [current, prior], cutoff,
                           formula="(current - prior) / prior * 100",
                           answer_type="percentage_change", metric=metric,
                           period=f"{current.period} vs {prior.period}")

    def ratio_bound(self, numerator: Any, denominator: Any, cutoff: str) -> dict[str, Any]:
        return self._bound("ratio", [numerator, denominator], cutoff,
                           formula="numerator / denominator", answer_type="ratio",
                           metric=f"{numerator.row_label} / {denominator.row_label}",
                           period=numerator.period or "")

    def margin_bound(self, numerator: Any, revenue: Any, cutoff: str) -> dict[str, Any]:
        return self._bound("margin", [numerator, revenue], cutoff,
                           formula="numerator / revenue * 100",
                           answer_type="margin_percent",
                           metric=f"{numerator.row_label} margin", period=numerator.period or "")

    def _bound(self, operator: str, bindings: list[Any], cutoff: str, *, formula: str,
               answer_type: str, metric: str, period: str) -> dict[str, Any]:
        problems: list[str] = []
        for binding in bindings:
            problems.extend(self.validate_binding(binding, cutoff))
        if problems:
            return self._refuse("input_unverified", problems=sorted(set(problems)))
        cells = [self.cell_from_binding(binding) for binding in bindings]
        if operator == "lookup":
            cell = cells[0]
            return self._run(
                operator="lookup", name="Reported value", formula=formula,
                answer_type=answer_type, metric=metric, period=period, cells=cells,
                inputs=[{"name": "value", "type": _fec_type(cell), "required": True}],
                nodes=[], output="value", values={"value": cell.value},
                raw_values=[cell.raw],
                limitations=["Value is quoted from one verified cell bound by the resolver."])
        if operator == "percentage_change":
            cur, prev = cells
            kind = _fec_type(cur)
            return self._run(
                operator=operator, name="Percentage change", formula=formula,
                answer_type=answer_type, metric=metric, period=period, cells=cells,
                inputs=[{"name": "current", "type": kind, "required": True},
                        {"name": "prior", "type": kind, "required": True},
                        {"name": "hundred", "type": "Scalar", "default": 100}],
                nodes=[{"id": "delta", "op": "sub", "inputs": ["current", "prior"]},
                       {"id": "fraction", "op": "div", "inputs": ["delta", "prior"]},
                       {"id": "scaled", "op": "mul", "inputs": ["fraction", "hundred"]}],
                output="scaled",
                values={"current": cur.value, "prior": prev.value, "hundred": 100},
                raw_values=[cur.raw, prev.raw], limitations=[])
        if operator == "ratio":
            top, bottom = cells
            return self._run(
                operator=operator, name="Ratio", formula=formula, answer_type=answer_type,
                metric=metric, period=period, cells=cells,
                inputs=[{"name": "numerator", "type": _fec_type(top), "required": True},
                        {"name": "denominator", "type": _fec_type(bottom), "required": True}],
                nodes=[{"id": "quotient", "op": "div", "inputs": ["numerator", "denominator"]}],
                output="quotient",
                values={"numerator": top.value, "denominator": bottom.value},
                raw_values=[top.raw, bottom.raw], limitations=[])
        top, bottom = cells
        return self._run(
            operator="margin", name="Margin", formula=formula, answer_type=answer_type,
            metric=metric, period=period, cells=cells,
            inputs=[{"name": "numerator", "type": _fec_type(top), "required": True},
                    {"name": "revenue", "type": _fec_type(bottom), "required": True},
                    {"name": "hundred", "type": "Scalar", "default": 100}],
            nodes=[{"id": "fraction", "op": "div", "inputs": ["numerator", "revenue"]},
                   {"id": "scaled", "op": "mul", "inputs": ["fraction", "hundred"]}],
            output="scaled",
            values={"numerator": top.value, "revenue": bottom.value, "hundred": 100},
            raw_values=[top.raw, bottom.raw], limitations=[])

    # ---------------------------------------------------------------- operators
    def lookup(self, issuer_id: str, cutoff: str, *, metric: str, period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        matches = self.find(cells, metric, period)
        if not matches:
            return self._refuse("metric_not_found", metric=metric, period=period)
        if len({cell.value for cell in matches}) > 1:
            return self._refuse("metric_ambiguous", metric=metric,
                                candidates=[cell.cell_id for cell in matches[:5]])
        cell = matches[0]
        return self._run(
            operator="lookup", name="Reported value", formula="lookup(cell)",
            answer_type="reported_value", metric=metric, period=period, cells=[cell],
            inputs=[{"name": "value", "type": _fec_type(cell), "required": True}],
            nodes=[], output="value", values={"value": cell.value},
            raw_values=[cell.raw],
            limitations=["Value is quoted from a verified table cell; no computation was performed."],
        )

    def percentage_change(self, issuer_id: str, cutoff: str, *, metric: str,
                          current_period: str, prior_period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        current, prior = self.find(cells, metric, current_period), self.find(cells, metric, prior_period)
        refusal = self._require(current, prior, current_period, prior_period)
        if refusal:
            return refusal
        cur, prev = current[0], prior[0]
        kind = _fec_type(cur)
        return self._run(
            operator="percentage_change", name="Percentage change",
            formula="(current - prior) / prior * 100", answer_type="percentage_change",
            metric=metric, period=f"{current_period} vs {prior_period}", cells=[cur, prev],
            inputs=[{"name": "current", "type": kind, "required": True},
                    {"name": "prior", "type": kind, "required": True},
                    {"name": "hundred", "type": "Scalar", "default": 100}],
            nodes=[{"id": "delta", "op": "sub", "inputs": ["current", "prior"]},
                   {"id": "fraction", "op": "div", "inputs": ["delta", "prior"]},
                   {"id": "scaled", "op": "mul", "inputs": ["fraction", "hundred"]}],
            output="scaled",
            values={"current": cur.value, "prior": prev.value, "hundred": 100},
            raw_values=[cur.raw, prev.raw],
            limitations=["Both cells must report the same concept; row labels were required to match."],
        )

    def ratio(self, issuer_id: str, cutoff: str, *, numerator: str, denominator: str,
              period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        top, bottom = self.find(cells, numerator, period), self.find(cells, denominator, period)
        refusal = self._require(top, bottom, period, period, allow_same_period=True)
        if refusal:
            return refusal
        return self._run(
            operator="ratio", name="Ratio", formula="numerator / denominator",
            answer_type="ratio", metric=f"{numerator} / {denominator}", period=period,
            cells=[top[0], bottom[0]],
            inputs=[{"name": "numerator", "type": _fec_type(top[0]), "required": True},
                    {"name": "denominator", "type": _fec_type(bottom[0]), "required": True}],
            nodes=[{"id": "quotient", "op": "div", "inputs": ["numerator", "denominator"]}],
            output="quotient", values={"numerator": top[0].value, "denominator": bottom[0].value},
            raw_values=[top[0].raw, bottom[0].raw],
            limitations=["Ratio is dimensionless; both inputs must share scale and currency."],
        )

    def margin(self, issuer_id: str, cutoff: str, *, numerator: str, revenue: str,
               period: str) -> dict[str, Any]:
        cells = self.cells(issuer_id, cutoff)
        top, bottom = self.find(cells, numerator, period), self.find(cells, revenue, period)
        refusal = self._require(top, bottom, period, period, allow_same_period=True)
        if refusal:
            return refusal
        return self._run(
            operator="margin", name="Margin", formula="numerator / revenue * 100",
            answer_type="margin_percent", metric=f"{numerator} margin", period=period,
            cells=[top[0], bottom[0]],
            inputs=[{"name": "numerator", "type": _fec_type(top[0]), "required": True},
                    {"name": "revenue", "type": _fec_type(bottom[0]), "required": True},
                    {"name": "hundred", "type": "Scalar", "default": 100}],
            nodes=[{"id": "fraction", "op": "div", "inputs": ["numerator", "revenue"]},
                   {"id": "scaled", "op": "mul", "inputs": ["fraction", "hundred"]}],
            output="scaled", values={"numerator": top[0].value, "revenue": bottom[0].value,
                                     "hundred": 100},
            raw_values=[top[0].raw, bottom[0].raw],
            limitations=["Margin definition follows the two row labels used; a different "
                         "definition in the filing would produce a different number."],
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
        inputs = [{"name": f"c{index}", "type": _fec_type(cell), "required": True}
                  for index, cell in enumerate(chosen)]
        nodes: list[dict[str, Any]] = []
        running = "c0"
        for index in range(1, len(chosen)):
            node_id = f"sum{index}"
            nodes.append({"id": node_id, "op": "add", "inputs": [running, f"c{index}"]})
            running = node_id
        values = {f"c{index}": cell.value for index, cell in enumerate(chosen)}
        return self._run(
            operator="total", name="Component total", formula="sum(components)",
            answer_type="sum", metric=" + ".join(components), period=period, cells=chosen,
            inputs=inputs, nodes=nodes, output=running, values=values,
            raw_values=[cell.raw for cell in chosen],
            limitations=["Components must be exhaustive and non-overlapping; that was assumed, "
                         "not proven."],
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
        if a.period and b.period and a.period != b.period and not allow_same_period:
            pass  # different periods are the point of a change calculation
        return None

    def _run(self, *, operator: str, name: str, formula: str, answer_type: str, metric: str,
             period: str, cells: list[Cell], inputs: list[dict[str, Any]],
             nodes: list[dict[str, Any]], output: str, values: dict[str, Any],
             raw_values: list[str], limitations: list[str]) -> dict[str, Any]:
        # Scale/currency consistency before any arithmetic (beyond pairwise checks above).
        scales = {cell.scale for cell in cells}
        currencies = {cell.currency for cell in cells}
        if None in scales:
            return self._refuse("unit_mismatch", detail="one or more inputs have unknown scale")
        if len(scales) > 1 or len(currencies) > 1:
            return self._refuse("unit_mismatch", scales=sorted(scales, key=lambda s: s or -1),
                                currencies=sorted(str(c) for c in currencies))
        try:
            fec = _compile_and_run(name, inputs, nodes, output, values)
        except Exception as exc:  # noqa: BLE001 - a compiler refusal is a refusal, not a crash
            return self._refuse("missing_input", detail=f"FEC refused the plan: {exc}")
        try:
            verified = verify_evaluate(operator, raw_values)
        except (VerificationError, ValueError) as exc:
            return self._refuse("verification_disagreement", detail=f"verifier refused: {exc}")
        places = _DISPLAY_PLACES.get(answer_type, 2)
        displayed = round_half_up(verified, places=places)
        fec_displayed = fec["value"].quantize(Decimal(10) ** -places)
        if displayed != fec_displayed:
            return self._refuse(
                "verification_disagreement",
                fec=str(fec["value"]), independent=str(verified),
                displayed_fec=str(fec_displayed), displayed_independent=str(displayed))
        unit = ({"kind": "percent", "scale": 0} if "percent" in answer_type
                else {"kind": "ratio", "scale": 0} if answer_type == "ratio"
                else {"kind": cells[0].unit, "scale": cells[0].scale})
        economic = None
        if answer_type in {"reported_value", "sum"} and cells[0].scale is not None:
            economic = str(Decimal(str(verified)) * (Decimal(10) ** cells[0].scale))
        payload = {
            "engine_version": ENGINE_VERSION, "operator_version": OPERATOR_VERSION,
            "answer_type": answer_type, "value": str(displayed), "period": period,
            "formula": formula, "cells": [cell.cell_id for cell in cells],
            "fec_fingerprint": fec["fingerprint"],
            "value_exact": str(verified), "display_places": places,
        }
        return {
            "outcome": "answered",
            "answer_type": answer_type,
            "value": str(displayed),
            "value_exact": str(verified),
            "display_places": places,
            "economic_amount": economic,
            "unit": unit,
            "currency": cells[0].currency,
            "period": period,
            "metric": metric,
            "formula": formula,
            "operator_version": OPERATOR_VERSION,
            "engine_version": ENGINE_VERSION,
            "inputs": [self._input_payload(cell) for cell in cells],
            "verification": {
                "independent_recomputation": True,
                "method": "Fraction verifier over raw text vs FEC execution",
                "verifier_version": "9.6.4",
                "rounding_policy": _ROUNDING_POLICY,
                "display_places": places,
            },
            "fec": {
                "compiler_version": fec["compiler_version"],
                "model_fingerprint": fec["fingerprint"],
                "run_id": fec["run_id"],
                "operator_versions": fec["operator_versions"],
                "plan": fec["spec"],
                "trace": fec["trace"],
            },
            "limitations": limitations + [
                "Computed values are never presented as quoted filings; the source cells are the "
                "authoritative statement.",
                "Display rounding is applied only after exact verification; intermediates stay exact.",
            ],
            "reproducibility_fingerprint": _fingerprint(payload),
        }

    def _input_payload(self, cell: Cell) -> dict[str, Any]:
        try:
            unit = self.engine.unit(cell.unit_id)
        except Exception:  # noqa: BLE001 - a missing passage is a validation failure
            unit = None
        return {
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
        }

    def _refuse(self, reason: str, **context: Any) -> dict[str, Any]:
        assert reason in ABSTENTION_REASONS, reason
        return {
            "outcome": "abstained", "reason": reason, "context": context,
            "engine_version": ENGINE_VERSION, "operator_version": OPERATOR_VERSION,
            "limitations": ["Atlas does not guess missing, ambiguous or unit-incompatible inputs."],
        }


_TITLE_LINE = re.compile(
    r"(consolidated statements? of [a-z ]+|consolidated balance sheets?|"
    r"consolidated statements? of cash flows?|parent company[ a-z]*|segment information)",
    re.IGNORECASE)


def _statement_context(units: dict[str, dict], table: dict) -> dict[str, Any]:
    """Nearest explicit statement title and unit scale from the document's own text.

    SEC filings put the statement title in its own paragraph a few blocks before the table, not in
    a caption. Search the current block and up to three preceding blocks; never assume the section
    heading ("Item 8") is the statement title.
    """
    from .table_cells import classify_statement, detect_scale
    current = units.get(table.get("unit_id"), {})
    ordinal = int(current.get("ordinal", 0) or 0)
    by_ordinal = {int(unit.get("ordinal", -1)): unit for unit in units.values()}
    blocks: list[dict] = [current] + [by_ordinal[ordinal - step] for step in (1, 2, 3, 4)
                                      if ordinal - step in by_ordinal]
    title: str | None = None
    family, scope = None, "unknown"
    for block in blocks:
        texts = [str(block.get("heading") or "")]
        for line in str(block.get("body") or "").splitlines()[:8]:
            # Statement titles are short lines, not sentences from surrounding prose.
            if 0 < len(line) <= 90 and not line.rstrip().endswith((".", ";", ":")):
                texts.append(line)
        for text in texts:
            candidate_family, candidate_scope = classify_statement(text)
            if candidate_family:
                title, family, scope = text.strip()[:200], candidate_family, candidate_scope
                break
        if family:
            break
    scale_hint = None
    scale_patterns = (
        "in millions", "in thousands", "in billions",
        "millions of dollars", "thousands of dollars", "billions of dollars",
        "dollars in millions", "dollars in thousands", "dollars in billions",
        "(millions)", "(thousands)", "(billions)",
        "(millions,", "(thousands,", "(billions,",
        "millions,", "thousands,", "billions,",
        # Bare unit words: 3M prints "(Millions, except per share amounts)" in-table.
        "millions", "thousands", "billions",
        "$ in millions", "$ in thousands", "usd in millions",
    )
    if not table.get("units"):
        for block in blocks[:5]:
            body = str(block.get("body") or "")
            heading = str(block.get("heading") or "")
            # Prefer the text that actually carries the scale phrase. Headings are often the
            # section title ("Item 8") while the scale lives in a neighbouring body line.
            for candidate in (body, heading, f"{heading}\n{body}"):
                lowered = candidate.lower()
                if any(pattern in lowered for pattern in scale_patterns):
                    scale_hint = candidate[:200]
                    break
            if scale_hint:
                break
    caption = str(table.get("caption") or "").lower()
    caption_has_scale = any(word in caption for word in ("million", "thousand", "billion"))
    units_value = table.get("units") or (None if caption_has_scale else scale_hint)
    return {"statement_title": title, "statement_family": family or "unknown",
            "entity_scope": scope, "units": units_value}


def _tokenize(text: str) -> list[str]:
    import re
    return re.findall(r"[a-z]{3,}", text.lower())


__all__ = ["FinancialAnswerEngine", "ENGINE_VERSION", "OPERATOR_VERSION", "ABSTENTION_REASONS"]
