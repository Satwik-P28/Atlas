"""Verified financial table cells (contract version 9.6.2).

The Phase 9.5 parser preserves a table's rows as text. That is not a semantic grid: it does not
say which cell belongs to which period, unit or sign. This module derives a *cell-level* view and
refuses to guess when the geometry is ambiguous.

A cell is ``verified`` only when:

* the table has exactly one unit interpretation (caption, header or column header),
* the column resolves to exactly one period (or to a period-free label like "Total"),
* the raw text parses to exactly one number with an unambiguous sign,
* the row label is unique within the table or disambiguated by its period column.

Everything else is ``unresolved`` with a machine-readable reason. A dash is *not* zero: filings use
dashes for nil, not-applicable and not-disclosed, and the caption rarely says which.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

CONTRACT_VERSION = "9.6.2"

_UNIT_WORDS = {
    "thousand": 3, "thousands": 3, "000": 3,
    "million": 6, "millions": 6, "mm": 6,
    "billion": 9, "billions": 9, "bn": 9,
}
_PERIOD = re.compile(r"(?:fy\s*)?((?:19|20)\d{2})(?:\s*[A-Za-z]{0,3}\b)?", re.IGNORECASE)
_NUMBER = re.compile(r"^\(?\s*[-+]?\$?\s*[\d,]*\.?\d+\s*\)?%?$")
_DASHES = {"-", "–", "—", "—", "n/a", "nm", "*"}
_SYMBOLS = {"$", "€", "£", "¥", "%", "usd", "eur", "gbp"}


@dataclass(slots=True)
class Cell:
    document_id: str
    accession: str
    table_id: str
    unit_id: str
    section_path: str
    table_caption: str | None
    row: int
    column: int
    row_label: str
    column_label: str
    period: str | None
    currency: str | None
    unit: str | None
    scale: int | None
    sign_convention: str
    raw: str
    value: str | None
    footnotes: list[str] = field(default_factory=list)
    status: str = "unresolved"
    reason: str | None = None
    extraction_method: str = "html_row_column_v1"
    confidence: str = "low"
    source_sha256: str = ""
    availability_time: str | None = None
    availability_precision: str | None = None
    rights: str | None = None

    @property
    def cell_id(self) -> str:
        payload = f"{self.table_id}:{self.row}:{self.column}:{self.raw}"
        return f"CELL-{hashlib.sha256(payload.encode()).hexdigest()[:16]}"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cell_id"] = self.cell_id
        data["contract_version"] = CONTRACT_VERSION
        return data


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def detect_scale(*texts: str) -> tuple[int | None, str | None, str]:
    """Return (power-of-ten scale, currency, basis) if all texts agree, else (None, ..., reason)."""
    found: set[int] = set()
    currency: set[str] = set()
    for text in texts:
        lowered = _norm(text).lower()
        for word, power in _UNIT_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                found.add(power)
        if "$" in lowered or "usd" in lowered or "u.s. dollar" in lowered:
            currency.add("USD")
        if "€" in lowered or "eur" in lowered:
            currency.add("EUR")
        if "£" in lowered or "gbp" in lowered:
            currency.add("GBP")
    if len(found) > 1:
        return None, None, "conflicting_units"
    if len(currency) > 1:
        return None, None, "conflicting_currencies"
    scale = next(iter(found)) if found else 0
    return scale, next(iter(currency)) if currency else None, "detected"


def parse_number(raw: str) -> tuple[Decimal | None, str, str]:
    """Parse one SEC table cell. Returns (value, sign convention, failure reason)."""
    text = _norm(raw)
    if not text:
        return None, "none", "empty_cell"
    if text.lower() in _DASHES:
        # A dash is not zero. Nil, not-applicable and not-disclosed are indistinguishable here.
        return None, "none", "dash_not_zero"
    percent = text.endswith("%")
    candidate = text.rstrip("%").strip()
    negative = False
    if candidate.startswith("(") and candidate.endswith(")"):
        negative = True
        candidate = candidate[1:-1]
    candidate = candidate.replace("$", "").replace(",", "").replace(" ", "")
    if candidate.startswith("-"):
        negative, candidate = True, candidate[1:]
    if not candidate or not re.fullmatch(r"\d*\.?\d+", candidate):
        return None, "none", "unparseable"
    try:
        value = Decimal(candidate)
    except InvalidOperation:
        return None, "none", "unparseable"
    if negative:
        value = -value
    return value, "parentheses_negative" if negative else "plain", "percent" if percent else "parsed"


_FOOTNOTE = re.compile(r"\s*(?:\(([a-z]{1,2}|\d{1,2})\)|([*\u2020\u2021]+))\s*$", re.IGNORECASE)


def split_footnote(raw: str) -> tuple[str, str | None]:
    """Separate a trailing footnote marker from the value, keeping the marker for provenance."""
    match = _FOOTNOTE.search(raw)
    if not match:
        return raw, None
    marker = match.group(1) or match.group(2) or ""
    return raw[:match.start()].strip(), marker


def _periods(header: str) -> list[str]:
    return [match.group(1) for match in _PERIOD.finditer(_norm(header))]


def _looks_numeric(row: Iterable[str]) -> float:
    cells = [cell for cell in row if _norm(cell)]
    if not cells:
        return 0.0
    numeric = sum(1 for cell in cells if _NUMBER.match(_norm(cell))
                  and not re.fullmatch(r"(19|20)\d{2}", _norm(cell)))
    return numeric / len(cells)


def extract_cells(
    table: dict[str, Any], *, document: dict[str, Any], max_header_rows: int = 3
) -> list[Cell]:
    """Derive cells from one stored ``knowledge_table`` row.

    ``table`` needs ``table_id``, ``unit_id``, ``section_path``, ``rows_json`` (list of rows),
    ``caption``, ``units``, ``footnotes``, ``sha256``.
    """
    rows: list[list[str]] = table.get("rows") or table.get("rows_json") or []
    if isinstance(rows, str):
        import json as _json
        rows = _json.loads(rows)
    footnotes_value = table.get("footnotes")
    if isinstance(footnotes_value, str):
        try:
            import json as _json
            footnotes_value = _json.loads(footnotes_value)
        except ValueError:
            footnotes_value = [footnotes_value]
    if not isinstance(footnotes_value, list):
        footnotes_value = []
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    scale, currency, unit_basis = detect_scale(table.get("caption") or "",
                                               table.get("units") or "")
    header_rows: list[int] = []
    for index, row in enumerate(rows[:max_header_rows]):
        if _looks_numeric(row) <= 0.34 and any(_periods(cell) for cell in row):
            header_rows.append(index)
        elif header_rows and _looks_numeric(row) <= 0.34 and not (row and _norm(row[0])):
            # A continuation header has an empty row-label cell; a data row starts with its label.
            header_rows.append(index)
    if not header_rows:
        header_rows = [0]
    body_start = max(header_rows) + 1

    # --- grid reconstruction -------------------------------------------------
    # SEC tables often put "$" in its own column and leave empty spacer columns between
    # periods. Reading those as data columns shifts every header by one or more positions and
    # turns real values into "unparseable" cells. Drop columns that are empty, or symbol-only,
    # across the body; then right-align the header periods onto the value columns. Original
    # column indices are preserved on every emitted cell.
    body_rows = rows[body_start:]
    raw_width = max((len(row) for row in rows), default=0)
    kept: list[int] = []
    for column in range(raw_width):
        values = [_norm(row[column]) for row in body_rows if column < len(row)]
        non_empty = [value for value in values if value]
        if not non_empty:
            continue
        if all(value in _SYMBOLS for value in non_empty):
            continue
        kept.append(column)
    if not kept:
        kept = list(range(raw_width))
    width = len(kept)
    headers: list[str] = [""] * width
    for index in header_rows:
        raw_header = [_norm(cell) for cell in rows[index] if _norm(cell)]
        if width <= 1 or not raw_header:
            continue
        periods = [cell for cell in raw_header if _periods(cell)]
        values = (periods or raw_header)[-(width - 1):]
        if len(values) < width - 1:
            values = [""] * (width - 1 - len(values)) + values
        for position in range(1, width):
            parts = [part for part in (headers[position], values[position - 1]) if part]
            headers[position] = " · ".join(dict.fromkeys(parts))
    rows = [[row[i] if i < len(row) else "" for i in kept] for row in rows]
    cells: list[Cell] = []
    occurrences: dict[str, int] = {}
    labels = [_norm(row[0]) for row in rows[body_start:] if row]
    duplicated = {label for label in labels if labels.count(label) > 1}
    for row_index in range(body_start, len(rows)):
        row = rows[row_index]
        label = _norm(row[0]) if row else ""
        occurrences[label] = occurrences.get(label, 0) + 1
        for column in range(1, width):
            raw = _norm(row[column]) if column < len(row) else ""
            if not raw:
                continue
            header = headers[column] if column < len(headers) else ""
            periods = _periods(header)
            numeric_text, marker = split_footnote(raw)
            value, sign, reason = parse_number(numeric_text)
            status, cell_reason = "verified", None
            if periods:
                period = periods[0] if len(set(periods)) == 1 else None
                if period is None:
                    status, cell_reason = "unresolved", "merged_period_header"
            else:
                period = None
            if status == "verified" and reason not in {"parsed", "percent"}:
                status, cell_reason = "unresolved", reason
            if status == "verified" and unit_basis != "detected":
                status, cell_reason = "unresolved", unit_basis
            if status == "verified" and label in duplicated:
                # Same label twice is only safe when the column periods disambiguate it.
                if not period:
                    status, cell_reason = "unresolved", "duplicate_row_label"
            if status == "verified" and not label:
                status, cell_reason = "unresolved", "missing_row_label"
            cells.append(Cell(
                document_id=document["document_id"], accession=document["accession"],
                table_id=table["table_id"], unit_id=table["unit_id"],
                section_path=table.get("section_path") or "",
                table_caption=table.get("caption"),
                row=row_index, column=kept[column] if column < len(kept) else column,
                row_label=label, column_label=header,
                period=period, currency=currency, unit="USD" if currency == "USD" else table.get("units"),
                scale=scale if status == "verified" else None, sign_convention=sign,
                raw=raw, value=str(value) if status == "verified" and value is not None else None,
                footnotes=([*footnotes_value, marker] if marker else footnotes_value), status=status, reason=cell_reason,
                confidence="high" if status == "verified" else "low",
                source_sha256=table.get("sha256") or "",
                availability_time=document.get("availability_time"),
                availability_precision=document.get("availability_precision"),
                rights=document.get("rights"),
            ))
    return cells


FINANCIAL_CAPTION_HINTS = (
    "balance sheet", "statement of operations", "statements of operations", "income statement",
    "cash flow", "financial position", "in millions", "in thousands", "(in thousands",
    "in billions", "financial statements", "results of operations", "segment",
)
NON_FINANCIAL_LABEL_HINTS = (
    "item 1", "item 2", "item 3", "item 4", "item 5", "item 6", "item 7", "item 8",
    "item 9", "item 10", "item 11", "item 12", "item 13", "item 14", "item 15",
    "present position", "other positions held", "part i", "part ii", "part iii",
)


def classify_table(table: dict[str, Any], cells: list[Cell]) -> tuple[str, str]:
    """Classify a stored table as financial, non-financial or unknown.

    The Phase 9.6.2 "unparseable" count was dominated by tables of contents and executive-bio
    tables. Counting those as extraction failures measures the corpus, not the parser, so they are
    separated instead of being made "verified".
    """
    caption = _norm(table.get("caption") or "").lower()
    section = _norm(table.get("section_path") or "").lower()
    labels = [_norm(cell.row_label).lower() for cell in cells[:40]]
    headers = " ".join(_norm(cell.column_label).lower() for cell in cells[:20])
    haystack = f"{caption} {section} {headers}"
    if any(hint in label for label in labels for hint in NON_FINANCIAL_LABEL_HINTS):
        return "non_financial", "document_navigation_or_personnel_table"
    if any(hint in haystack for hint in FINANCIAL_CAPTION_HINTS):
        if cells:
            return "financial", "caption_or_section_signal"
        return "unknown", "no_cells"
    verified = sum(1 for cell in cells if cell.status == "verified")
    numeric_density = verified / len(cells) if cells else 0.0
    if len(cells) >= 6 and numeric_density >= 0.5:
        return "financial", "numeric_density"
    return "unknown", "no_financial_signal"


def cell_as_of(cell: Cell, cutoff: str) -> bool:
    """A cell may only be used if its document was available at the cutoff."""
    if not cell.availability_time:
        return False
    return cell.availability_time <= cutoff


__all__ = [
    "Cell", "CONTRACT_VERSION", "classify_table", "detect_scale", "parse_number",
    "extract_cells", "cell_as_of", "split_footnote",
]
