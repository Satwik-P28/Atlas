"""Table geometry from archived filing bytes (version 10.0.1).

The knowledge engine flattens each ``<tr>`` into a list of strings. That loses two things a
financial answer depends on:

* **merged header cells** — a header printed as ``<td colspan=3>2022</td>`` becomes one string
  in a short row, so indexing the data column lands on the *next* year's header;
* **row structure** — a banner row inside a segment table (``Net Sales (Millions)``) is
  indistinguishable from a data row once empty cells are dropped.

This module re-reads the archived HTML and rebuilds a grid in which every column position
carries the header that actually spans it. It is deliberately independent of the database:
its input is the exact bytes that were archived, so its output can be compared against the
stored (flattened) representation and against XBRL.

Nothing here decides whether a number is *correct*. It decides which column a printed number
sits under and which unit banner governs it, and records the coordinate it used.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser
from typing import Iterator

# Reuse the single number/unit vocabulary so geometry and the flattened path never disagree
# about what a unit word or a dash means.
from .statement_scope import (
    classify as classify_statement_context,
    context_is_note,
    group_scope as classify_group_scope,
    title_from_text,
)
from .table_cells import _DASHES, _NUMBER, _norm, detect_scale, parse_number

CONTRACT_VERSION = "10.0.1"
MAX_RENDERED_CHARS = 4_000_000
_PERIOD = re.compile(r"(?:fy\s*)?((?:19|20)\d{2})(?:\s*[A-Za-z]{0,3}\b)?", re.IGNORECASE)
_UNIT_ROW = re.compile(r"\b(millions?|thousands?|billions?)\b", re.IGNORECASE)
_SKIP = {"script", "style", "noscript", "head", "title"}
_BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
#: Statement identity, including the titles this corpus actually prints. Kept separate from
#: ``table_cells.classify_statement`` so the comparison can attribute the difference to the
#: geometry-aware path rather than to a change in the baseline's vocabulary.
_GEOMETRY_STATEMENTS = (
    ("segment", re.compile(r"segment (information|reporting|results)|business segment", re.IGNORECASE)),
    ("balance_sheet", re.compile(r"balance sheets?|statement of financial position|"
                                 r"statements? of financial condition", re.IGNORECASE)),
    ("cash_flow", re.compile(r"statements? of cash flows?", re.IGNORECASE)),
    ("income", re.compile(r"statements? of (income|operations|earnings)|income statements?|"
                          r"statements? of consolidated (income|earnings)|consolidated statement of earnings",
                          re.IGNORECASE)),
)


@dataclass(frozen=True, slots=True)
class RawCell:
    text: str
    colspan: int = 1
    rowspan: int = 1


@dataclass(slots=True)
class GeometryTable:
    index: int
    rows: list[list[RawCell]]
    grid: list[list[RawCell | None]]
    preceding_text: str
    caption: str | None = None
    header_rows: list[int] = field(default_factory=list)
    column_period: dict[int, str] = field(default_factory=dict)
    column_header: dict[int, str] = field(default_factory=dict)
    scale: int | None = None
    currency: str | None = None
    unit_basis: str = "scale_undetected"
    statement_title: str | None = None
    statement_family: str | None = None
    entity_scope: str = "unknown"
    #: Columns of a consolidating statement grouped by the reporting entity they describe
    #: ("Consolidated", "Machinery, Energy & Transportation", "Consolidating Adjustments").
    column_groups: dict[int, str] = field(default_factory=dict)
    digest: str = ""

    def column_group(self, column: int) -> str | None:
        return self.column_groups.get(column)

    def column_scope(self, column: int) -> str:
        label = self.column_groups.get(column)
        return "unknown" if label is None else classify_group_scope(label)

    @property
    def has_column_groups(self) -> bool:
        return len({label for label in self.column_groups.values()}) >= 2

    @property
    def body_start(self) -> int:
        return (max(self.header_rows) + 1) if self.header_rows else 0

    @property
    def width(self) -> int:
        return max((len(row) for row in self.grid), default=0)

    def label_of(self, row: int) -> str:
        for cell in self.grid[row]:
            if cell is not None and cell.text:
                return cell.text
        return ""

    def header_for(self, column: int) -> str:
        return self.column_header.get(column, "")

    def period_for(self, column: int, row: int | None = None) -> str | None:
        """Geometry period for a column, with a row-order fallback.

        The fallback is only used when a data row has exactly as many numeric cells as the
        header row prints periods, so years are assigned left to right rather than guessed.
        """
        period = self.column_period.get(column)
        if period:
            return period
        if row is None:
            return None
        numeric = self.numeric_columns(row)
        periods = self.printed_periods()
        if periods and numeric and len(numeric) == len(periods) and column in numeric:
            return periods[numeric.index(column)]
        return None

    def numeric_columns(self, row: int) -> list[int]:
        out: list[int] = []
        for column, cell in enumerate(self.grid[row] if row < len(self.grid) else []):
            if cell is None or not cell.text:
                continue
            value, _sign, reason = parse_number(cell.text)
            if reason in {"parsed", "percent"}:
                out.append(column)
        return out

    def printed_periods(self) -> list[str]:
        periods: list[str] = []
        for index in self.header_rows:
            for cell in self.rows[index] if index < len(self.rows) else []:
                text = _norm(cell.text)
                # A bare year is the period, not a value: parse_number() would skip it.
                if (parse_number(text)[2] in {"parsed", "percent"}
                        and not re.fullmatch(r"(19|20)\d{2}", text)):
                    continue
                for period in _PERIOD.findall(text):
                    if period not in periods:
                        periods.append(period)
        return periods

    def values(self) -> Iterator[tuple[int, int, RawCell, str | None]]:
        for row in range(self.body_start, len(self.grid)):
            for column, cell in enumerate(self.grid[row]):
                if cell is None or not cell.text:
                    continue
                yield row, column, cell, self.period_for(column, row)

    def digest_payload(self) -> str:
        return "\n".join("|".join(c.text for c in row) for row in self.rows)


class _DocParser(HTMLParser):
    """Collect tables and the visible text that precedes each one."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[GeometryTable] = []
        self._skip = 0
        self._table_depth = 0
        self._rows: list[list[RawCell]] = []
        self._row: list[RawCell] | None = None
        self._cell: dict[str, object] | None = None
        self._caption: str | None = None
        self._pending_caption: str | None = None
        self._text: list[str] = []
        self._in_caption = False
        self._chars = 0

    # -- text buffer
    def _visible(self) -> str:
        joined = "".join(self._text[-4000:])
        # Keep paragraph boundaries: statement titles are whole lines, and collapsing them into
        # one run of prose makes the title indistinguishable from a sentence that mentions it.
        return re.sub(r"[^\S\u2029]+", " ", joined).strip()

    def _flush_table(self) -> None:
        if not self._rows:
            return
        preceding = self._visible()
        table = GeometryTable(index=len(self.tables), rows=self._rows,
                              grid=_expand(self._rows), preceding_text=preceding,
                              caption=self._caption)
        _annotate(table)
        table.digest = hashlib.sha256(table.digest_payload().encode()).hexdigest()
        self.tables.append(table)
        self._rows = []
        self._caption = None

    # -- parser API
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            if self._table_depth == 0:
                self._rows, self._caption = [], self._pending_caption
                self._pending_caption = None
            self._table_depth += 1
            return
        if tag == "tr":
            # Rows are collected at any nesting depth, mirroring how the filing is laid out
            # and how the knowledge engine flattens it, but cells keep their spans.
            if self._row and any(cell.text for cell in self._row):
                self._rows.append(self._row)
            self._row = []
            return
        if tag in {"td", "th"}:
            attributes = dict(attrs)
            self._cell = {
                "colspan": max(1, _int(attributes.get("colspan"))),
                "rowspan": max(1, _int(attributes.get("rowspan"))),
                "parts": [],
            }
            return
        if tag == "caption":
            self._in_caption = True
            self._cell = {"colspan": 1, "rowspan": 1, "parts": []}
            return
        if tag in _BLOCK and not self._cell:
            self._text.append("\u2029")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "table":
            self._table_depth = max(0, self._table_depth - 1)
            if self._table_depth == 0:
                if self._row and any(cell.text for cell in self._row):
                    self._rows.append(self._row)
                self._row = None
                self._flush_table()
            return
        if tag in {"td", "th"} and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell["parts"])).strip()
            cell = RawCell(text=text, colspan=int(self._cell["colspan"]),
                           rowspan=int(self._cell["rowspan"]))
            if self._row is not None:
                self._row.append(cell)
            self._cell = None
            return
        if tag == "caption" and self._cell is not None:
            self._pending_caption = re.sub(r"\s+", " ", "".join(self._cell["parts"])).strip()
            self._cell = None
            self._in_caption = False
            return
        if tag in _BLOCK and not self._cell:
            self._text.append("\u2029")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._chars += len(data)
        if self._chars > MAX_RENDERED_CHARS:
            return
        if self._cell is not None:
            self._cell["parts"].append(data)  # type: ignore[index]
            return
        self._text.append(data)


def _int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 1


def _expand(rows: list[list[RawCell]]) -> list[list[RawCell | None]]:
    """Place every cell at the grid positions its colspan/rowspan covers."""
    grid: list[list[RawCell | None]] = []
    occupied: dict[tuple[int, int], RawCell] = {}
    for row_index, row in enumerate(rows):
        while len(grid) <= row_index:
            grid.append([])
        column = 0
        for cell in row:
            while (row_index, column) in occupied or (
                    column < len(grid[row_index]) and grid[row_index][column] is not None):
                column += 1
            for extra_row in range(cell.rowspan):
                target = row_index + extra_row
                while len(grid) <= target:
                    grid.append([])
                for extra_column in range(cell.colspan):
                    position = column + extra_column
                    while len(grid[target]) <= position:
                        grid[target].append(None)
                    grid[target][position] = cell
                    occupied[(target, position)] = cell
            column += cell.colspan
    return grid


def _annotate(table: GeometryTable) -> None:
    """Derive header rows, per-column headers/periods, scale and statement identity."""
    rows = table.grid
    if not rows:
        return
    # Header rows: the contiguous block of leading rows up to and including the last row that
    # prints a period. A header block can be several rows deep (unit banner, "Year Ended
    # December 31,", year row, sub-labels), and it must not swallow a low-density data row:
    # a row with a label and three numbers can be under the numeric threshold.
    period_rows: list[int] = []
    for index, row in enumerate(rows[:5]):
        texts = [cell.text for cell in row if cell is not None and cell.text]
        if not texts:
            continue
        numeric = sum(1 for text in texts
                      if parse_number(text)[2] in {"parsed", "percent"}
                      and not re.fullmatch(r"(19|20)\d{2}", text))
        if numeric / len(texts) <= 0.5 and _PERIOD.search(" ".join(texts)):
            period_rows.append(index)
    last_header = max(period_rows) if period_rows else 0
    table.header_rows = list(range(last_header + 1))

    width = table.width
    for column in range(width):
        parts: list[str] = []
        seen: set[int] = set()
        for index in table.header_rows:
            if index >= len(rows) or column >= len(rows[index]):
                continue
            cell = rows[index][column]
            if cell is None or not cell.text or id(cell) in seen:
                continue
            seen.add(id(cell))
            parts.append(cell.text)
        table.column_header[column] = " · ".join(parts)
        periods: list[str] = []
        for part in parts:
            # A bare year *is* the period; only a non-year number is a value, not a header.
            if (parse_number(part)[2] in {"parsed", "percent"}
                    and not re.fullmatch(r"(19|20)\d{2}", _norm(part))):
                continue
            for period in _PERIOD.findall(part):
                if period not in periods:
                    periods.append(period)
        if len(periods) == 1:
            table.column_period[column] = periods[0]

    # Unit banners are lines, not scattered words: "(In thousands, except per share amounts)"
    # is one banner. Reading every header and body word as a unit candidate made ordinary
    # statements look self-contradictory.
    unit_lines: list[str] = [table.caption] if table.caption else []
    for index in table.header_rows:
        if index >= len(rows):
            continue
        for cell in rows[index]:
            if cell is None or not cell.text or cell.text in unit_lines:
                continue
            if _UNIT_ROW.search(cell.text) and not cell_is_numeric(cell):
                unit_lines.append(cell.text)
    for index in range(table.body_start, min(len(rows), table.body_start + 2)):
        for cell in rows[index]:
            if cell is None or not cell.text or cell.text in unit_lines:
                continue
            if _UNIT_ROW.search(cell.text) and not cell_is_numeric(cell):
                unit_lines.append(cell.text)
    scale, currency, basis = detect_statement_scale(*unit_lines)
    if basis != "detected" and unit_lines:
        scale, currency, basis = detect_statement_scale(*unit_lines[:1])
    if basis != "detected":
        # The banner is often the line directly above the table ("Dollars in millions"). Only
        # short banner-shaped lines are read: a page of prose about commodity prices mentions
        # millions and billions without saying anything about this table's unit.
        lines = [line.strip() for line in table.preceding_text.split("\u2029") if line.strip()][-12:]
        banners = [line for line in lines
                   if _UNIT_ROW.search(line) and len(line) <= 120 and not cell_is_numeric(RawCell(line))]
        if banners:
            scale, currency, basis = detect_statement_scale(*banners[-2:])
    table.scale, table.currency, table.unit_basis = scale, currency, basis
    found = title_from_text(table.preceding_text)
    if found.family == "unknown" and table.caption:
        found = classify_statement_context(table.caption)
    if found.family == "unknown":
        # Some filers print the statement identity *inside* the table ("STATEMENT 3 /
        # Consolidated Financial Position at December 31"), with the page above devoted to
        # audit-report boilerplate. The header is part of the table's own evidence.
        found = _header_title(table)
    if found.is_statement and context_is_note(_trailing_lines(table.preceding_text, 3)):
        # The page says this table is a note, a summary or a reconciliation of a statement.
        # Its title line naming the statement is what the table is *about*, not what it is.
        found = type(found)("note", found.scope, found.title, "context_note_marker")
    table.statement_family = None if found.family == "unknown" else found.family
    table.entity_scope = found.scope
    table.statement_title = found.title or table.caption
    _annotate_column_groups(table)


def detect_statement_scale(*lines: str) -> tuple[int | None, str | None, str]:
    """Scale of the *amounts* in a statement banner.

    Filings print "(In millions, except number of shares which are reflected in thousands and
    per share amounts)". Reading that as a unit conflict would discard the unit of every modern
    income statement. The unit of the amounts is the one in the main clause; an "except"
    clause describes other quantities.
    """
    primary: list[str] = []
    for line in lines:
        head = re.split(r"\bexcept\b|\bexcluding\b", line, flags=re.IGNORECASE)[0]
        if head.strip():
            primary.append(head)
    return detect_scale(*primary) if primary else (None, None, "scale_undetected")


def classify_statement_title(text: str | None) -> tuple[str | None, str]:
    """Statement family and entity scope from a printed title line (shared classifier)."""
    found = classify_statement_context(text)
    return (None if found.family == "unknown" else found.family), found.scope


def _statement_line(text: str) -> str | None:
    """The last short line before the table that names a statement."""
    found = title_from_text(text)
    return found.title if found.family != "unknown" else None


def _trailing_lines(text: str, count: int) -> str:
    """The last few printed lines of a table's preceding text.

    ``preceding_text`` accumulates the whole document, so a note marker several pages earlier
    must not demote a later statement. Only the lines immediately above the table describe it.
    """
    lines = [line.strip() for line in re.split(r"\u2029", text) if line.strip()]
    return "\u2029".join(lines[-count:])


def _header_title(table: GeometryTable) -> object:
    for index in table.header_rows:
        if index >= len(table.grid):
            continue
        seen: set[int] = set()
        for cell in table.grid[index]:
            if cell is None or not cell.text or id(cell) in seen:
                continue
            seen.add(id(cell))
            found = classify_statement_context(cell.text)
            if found.is_statement:
                return found
    return classify_statement_context(None)


def _annotate_column_groups(table: GeometryTable) -> None:
    """Group the columns of a consolidating statement by the entity they describe.

    Caterpillar prints the consolidated balance sheet four times side by side (consolidated,
    Machinery Energy & Transportation, Financial Products, adjustments). Every group has the same
    row labels and a different number, so without this mapping the resolver sees four conflicting
    `Total assets` values and refuses a question the filing answers plainly.

    Only header rows whose cells name reporting entities are used: a banner row ("STATEMENT 3",
    the company name) is not a column group, and a year row never is.
    """
    if len(table.header_rows) < 2:
        return
    grid = table.grid
    for index in reversed(table.header_rows):
        spans: dict[int, tuple[str, list[int]]] = {}
        for column in range(table.width):
            if index >= len(grid) or column >= len(grid[index]):
                continue
            cell = grid[index][column]
            if cell is None or not cell.text:
                continue
            text = _norm(cell.text)
            if re.fullmatch(r"(19|20)\d{2}", text) or _UNIT_ROW.search(text):
                continue
            if len(text) > 60:
                continue
            entry = spans.setdefault(id(cell), (text, []))
            entry[1].append(column)
        labels = [text for text, _columns in spans.values()]
        if len(set(labels)) < 2:
            continue
        scopes = [classify_group_scope(label) for label in labels]
        if any(scope == "unknown" for scope in scopes):
            continue
        if "consolidated" not in scopes:
            # Two known-looking labels without a consolidated group are a banner pair
            # ("STATEMENT 1" / registrant name), not a consolidating statement.
            continue
        mapping: dict[int, str] = {}
        for text, columns in spans.values():
            for column in columns:
                mapping[column] = text
        table.column_groups = mapping
        return


def parse_tables(html: str | bytes) -> list[GeometryTable]:
    """Parse archived filing bytes into geometry tables, in document order.

    Parsing is pure and the input is immutable bytes, so results are cached by SHA-256: a second
    request over the same accession reuses the geometry instead of re-reading the document. The
    key is the document digest, never the accession or a filename, so cached evidence can never
    be reused across different bytes.
    """
    payload = html.encode("utf-8") if isinstance(html, str) else html
    return list(_parse_cached(hashlib.sha256(payload).hexdigest(), payload))


@lru_cache(maxsize=32)
def _parse_cached(digest: str, payload: bytes) -> tuple[GeometryTable, ...]:
    text = payload.decode("utf-8", errors="replace")
    parser = _DocParser()
    parser.feed(text)
    parser.close()
    if parser._table_depth == 0 and parser._row and any(cell.text for cell in parser._row):
        parser._rows.append(parser._row)
        parser._flush_table()
    return tuple(parser.tables)


def cell_is_numeric(cell: RawCell | None) -> bool:
    if cell is None or not cell.text:
        return False
    if _norm(cell.text).lower() in _DASHES:
        return False
    return bool(_NUMBER.match(_norm(cell.text)))


__all__ = ["CONTRACT_VERSION", "GeometryTable", "RawCell", "parse_tables", "cell_is_numeric",
           "classify_statement_title", "detect_statement_scale"]
