"""Print the printed geometry of an archived filing for independent gold authoring.

This is an authoring aid, deliberately outside the evaluated system: it imports nothing from
Atlas, runs no resolver, scores nothing, and does not choose a row or a column. It expands an
HTML table into its literal cells and prints the header rows plus the rows whose text contains a
requested phrase, so a reviewer can read the printed statement exactly as it appears and record
the cell, the printed period header and the unit banner by hand.

Usage::

    python scripts/answer_semantics_holdout_inspect.py \
        var/answer_semantics/holdout/snapshots/0000018230-23-000011.html \
        --needle "net sales" --needle "total assets"
"""

from __future__ import annotations

import argparse
import html
import re
from html.parser import HTMLParser
from typing import Any

SCALE = re.compile(r"\(\s*(?:in|amounts in)\s+(thousands|millions|billions)\b", re.IGNORECASE)


class _Tables(HTMLParser):
    """Collect tables as literal rows of cell text, keeping colspan/rowspan counts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._stack: list[list[list[dict[str, Any]]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._heading: list[str] = []
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "colspan": int(attributes.get("colspan") or 1),
                          "rowspan": int(attributes.get("rowspan") or 1),
                          "header": tag == "th"}
        elif tag in {"h1", "h2", "h3", "h4", "div", "p"}:
            self._in_heading = True
        elif tag == "br" and self._cell is not None:
            self._cell["text"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", html.unescape("".join(self._cell["text"]))).strip()
            self._row.append({"text": text, "colspan": self._cell["colspan"],
                              "rowspan": self._cell["rowspan"], "header": self._cell["header"]})
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            if any(cell["text"] for cell in self._row):
                self._stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            table = self._stack.pop()
            if table:
                self.tables.append(table)
        elif tag in {"h1", "h2", "h3", "h4", "div", "p"}:
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)


def _row_text(row: list[dict[str, Any]]) -> str:
    return " | ".join(cell["text"] for cell in row if cell["text"])


def _print_row(position: int, row: list[dict[str, Any]]) -> None:
    cells = " | ".join((f"[{cell['colspan']}]" if cell["colspan"] > 1 else "") + cell["text"]
                      for cell in row)
    print(f"  r{position:03d}: {cells}")


def locate(parser: _Tables, pairs: list[tuple[str, str]]) -> None:
    """Print the table, header rows and matched row for each (phrase, printed number) pair.

    The pair is supplied by the reviewer from the printed statement and the same-accession XBRL
    fact. This mode only reports where those two literals co-occur; it does not rank, score or
    pick a cell.
    """
    for phrase, number in pairs:
        wanted_phrase = phrase.lower()
        wanted_number = number.replace(" ", "")
        found = False
        for index, table in enumerate(parser.tables):
            for position, row in enumerate(table):
                label = _row_text(row).lower()
                if wanted_phrase not in label:
                    continue
                if not any(cell["text"].replace(" ", "") == wanted_number for cell in row):
                    continue
                found = True
                flat = "\n".join(_row_text(item) for item in table)
                banner = SCALE.search(flat)
                print(f"\n=== {phrase!r} {number} :: table {index} rows={len(table)} "
                      f"scale={banner.group(1) if banner else None}")
                first_header = next((pos for pos, item in enumerate(table)
                                     if all(cell["header"] for cell in item if cell["text"])), None)
                if first_header is not None:
                    _print_row(first_header, table[first_header])
                    if first_header + 1 < len(table):
                        _print_row(first_header + 1, table[first_header + 1])
                for context in range(max(0, position - 1), min(len(table), position + 2)):
                    _print_row(context, table[context])
        if not found:
            print(f"\n!!! {phrase!r} {number} not found as a printed cell")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot")
    parser.add_argument("--needle", action="append", default=[],
                        help="phrase whose rows are printed (case-insensitive)")
    parser.add_argument("--locate", action="append", default=[], metavar="PHRASE::NUMBER",
                        help="print the table/header/row where a phrase and a printed number co-occur")
    parser.add_argument("--context", type=int, default=2, help="rows printed after a match")
    parser.add_argument("--table", type=int, default=None, help="print one table by index")
    parser.add_argument("--rows", default="0:4", help="row slice for --table, e.g. 0:4")
    args = parser.parse_args(argv)
    parser = _Tables()
    parser.feed(open(args.snapshot, encoding="utf-8", errors="replace").read())
    if args.table is not None:
        table = parser.tables[args.table]
        start, _, stop = args.rows.partition(":")
        for position in range(int(start), min(len(table), int(stop or start))):
            _print_row(position, table[position])
        return 0
    if args.locate:
        pairs = []
        for item in args.locate:
            phrase, _, number = item.partition("::")
            pairs.append((phrase, number))
        locate(parser, pairs)
        return 0
    needles = [needle.lower() for needle in args.needle]
    for index, table in enumerate(parser.tables):
        flat = "\n".join(_row_text(row) for row in table)
        hits = [position for position, row in enumerate(table)
                if any(needle in _row_text(row).lower() for needle in needles)]
        if needles and not hits:
            continue
        banner = SCALE.search(flat)
        print(f"\n=== table {index}: rows={len(table)} cells={max(len(row) for row in table)}"
              f" scale={banner.group(1) if banner else None}")
        header = [position for position, row in enumerate(table)
                  if all(cell["header"] for cell in row if cell["text"])][:2]
        shown: set[int] = set(header)
        for hit in hits[:20]:
            shown.update(range(max(0, hit - 1), min(len(table), hit + args.context + 1)))
        for position in sorted(shown):
            row = table[position]
            cells = " | ".join(f"[{cell['colspan']}]" + cell["text"] if cell["colspan"] > 1
                               else cell["text"] for cell in row)
            print(f"  r{position:03d}: {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
