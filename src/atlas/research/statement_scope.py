"""Statement identity and reporting scope for filing tables (version 10.1.0).

A printed row label is not statement context. ``Total assets`` appears on the consolidated
balance sheet, on a subsidiary's balance sheet, in a fair-value note, in a segment reconciliation
and in a consolidating schedule, and the numbers differ. Both resolvers therefore need the same
answer to two questions before a candidate may compete:

* **What kind of table is this?** (income statement, balance sheet, cash-flow statement, note,
  segment disclosure, schedule …)
* **What reporting scope does it describe?** (the consolidated entity, a parent-only column, a
  reportable segment, a subsidiary, one member of a consolidating schedule)

The classifier is lexical and deliberately conservative: a title must look like a statement title,
and note-shaped text ("Amounts Offset in the Consolidated Balance Sheets", "Supplemental Data for
Financial Position", "fair value … measured on a recurring basis") is classified as a note even
when it mentions "balance sheets". That distinction is the one that let an offset note win over the
real Intel balance sheet, and that let a supplementary consolidating schedule make Caterpillar's
consolidated totals look ambiguous.

Nothing here is issuer-specific. Every rule is a property of the printed English title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Statement families. ``note`` and ``unknown`` are refusals, not statements.
FAMILIES = ("income", "balance_sheet", "cash_flow", "equity", "segment", "note", "unknown")
#: Reporting scopes, ordered from most to least consolidated.
SCOPES = ("consolidated", "consolidating_member", "parent", "segment", "subsidiary", "unknown")

CONSOLIDATED_REQUIRED = "consolidated"
#: Scopes that can never satisfy a question about the consolidated entity.
INCOMPATIBLE_SCOPES = frozenset({"parent", "segment", "subsidiary", "consolidating_member"})

_NOTE_MARKERS = (
    "amounts offset", "offset in the", "fair value", "supplemental", "supplementary",
    "selected financial data", "summarized", "reconciliation", "reconciles", "rollforward",
    "roll-forward", "average balance", "average balances", "disaggregat", "by segment",
    "by geographic", "segment information", "geographic area information", "schedule of",
    "schedule i", "schedule ii", "notes to consolidated", "notes to financial",
)
#: Markers strong enough to demote a *table* whose last title-shaped line names a statement: a
#: page headed "selected financial data for BCC" must not lend its "Financial Position" line the
#: identity of Boeing's consolidated statement.
TABLE_CONTEXT_NOTE_MARKERS = (
    "amounts offset", "fair value", "supplemental", "supplementary", "selected financial data",
    "summarized", "reconciliation", "reconciles", "rollforward", "roll-forward",
    "average balance", "average balances", "disaggregat", "schedule of",
)

_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("segment", re.compile(
        r"\bsegment (information|reporting|results)\b|\bbusiness segments?\b|"
        r"\bgeographic (area )?information\b", re.IGNORECASE)),
    ("balance_sheet", re.compile(
        r"\bbalance sheets?\b|\bstatements? of financial (position|condition)\b|"
        r"\bfinancial position\b|\bfinancial condition\b", re.IGNORECASE)),
    ("cash_flow", re.compile(r"\bstatements? of cash flows?\b|\bcash flows? statements?\b",
                             re.IGNORECASE)),
    ("equity", re.compile(
        r"\bstatements? of (changes in )?(stockholders'?|shareholders'?|members'?)?\s*equity\b|"
        r"\bchanges in (stockholders'?|shareholders'?)\s*equity\b", re.IGNORECASE)),
    ("income", re.compile(
        r"\bstatements? of (consolidated )?(income|operations|earnings)\b|"
        r"\bincome statements?\b|\bconsolidated statements? of operations\b|"
        r"\bconsolidated results of operations\b|\bstatements? of loss\b", re.IGNORECASE)),
)

_CONSOLIDATED_MARKERS = ("consolidated", "and subsidiaries", "and subsidiary", "combined")
_PARENT_MARKERS = ("parent company", "parent-only", "parent only", "parent guarantor",
                   "parent and guarantor", "parent guarantor and subsidiary issuer")
_SUBSIDIARY_MARKERS = ("subsidiary issuer", "subsidiaries of the registrant", "subsidiary")
_CONSOLIDATING_MARKERS = ("consolidating", "supplemental consolidating", "combining")

#: A title line longer than this is prose about a table, not the table's title.
MAX_TITLE_CHARS = 130


@dataclass(frozen=True, slots=True)
class StatementClass:
    family: str
    scope: str
    title: str | None = None
    evidence: str = "no_title"

    @property
    def is_statement(self) -> bool:
        return self.family in {"income", "balance_sheet", "cash_flow", "equity"}


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def is_note_text(text: str | None) -> bool:
    lowered = norm(text).lower()
    return any(marker in lowered for marker in _NOTE_MARKERS)


def context_is_note(text: str | None) -> bool:
    """Is the surrounding prose enough to demote a statement-shaped title line?"""
    lowered = norm(text).lower()
    return any(marker in lowered for marker in TABLE_CONTEXT_NOTE_MARKERS)


def classify(text: str | None) -> StatementClass:
    """Classify one printed line as a statement title, a note, or neither.

    Order matters. Note markers are checked first: "Amounts Offset in the Consolidated Balance
    Sheets" names the balance sheet but is a note about it, and treating it as the statement is
    exactly the confusion this module exists to prevent.
    """
    cleaned = norm(text)
    if not cleaned:
        return StatementClass("unknown", "unknown", None, "empty")
    if len(cleaned) > MAX_TITLE_CHARS:
        return StatementClass("unknown", "unknown", cleaned[:MAX_TITLE_CHARS], "prose")
    lowered = cleaned.lower()
    # A 10-K section heading is not a statement title. "Item 8. Financial Statements and
    # Supplementary Data" contains a note marker and, without this guard, classified every table
    # under it as a note — including the consolidated statements themselves.
    if (re.match(r"^(item|part)\s+\d", lowered)
            or lowered.startswith(("management's discussion", "management’s discussion"))):
        return StatementClass("unknown", "unknown", cleaned, "section_heading")
    # A segment disclosure is a note in the filing, but "segment" is the more useful identity:
    # it says why the table's numbers are not the consolidated group's.
    if re.search(r"\bsegment (information|reporting|results)\b|\bgeographic (area )?information\b",
                 cleaned, re.IGNORECASE):
        return StatementClass("segment", "segment", cleaned, "segment_title")
    if is_note_text(lowered):
        return StatementClass("note", _scope(lowered, family=None), cleaned, "note_marker")
    for family, pattern in _TITLE_PATTERNS:
        if pattern.search(cleaned):
            return StatementClass(family, _scope(lowered, family=family), cleaned, "title_pattern")
    return StatementClass("unknown", "unknown", cleaned, "no_pattern")


def _scope(lowered: str, *, family: str | None) -> str:
    if any(marker in lowered for marker in _PARENT_MARKERS):
        return "parent"
    if any(marker in lowered for marker in _SUBSIDIARY_MARKERS) and "subsidiaries" not in lowered:
        return "subsidiary"
    if any(marker in lowered for marker in _CONSOLIDATING_MARKERS):
        return "consolidating_member"
    if family == "segment":
        return "segment"
    if any(marker in lowered for marker in _CONSOLIDATED_MARKERS):
        return "consolidated"
    return "unknown"


def scope_compatible(required: str, found: str) -> bool:
    """May a candidate with ``found`` scope answer a question that needs ``required``?"""
    if required != CONSOLIDATED_REQUIRED:
        return True
    return found not in INCOMPATIBLE_SCOPES


_SEGMENT_GROUP_MARKERS = (
    "segment", "products", "transportation", "solutions", "banking", "markets",
    "services", "international", "americas", "emea", "asia", "europe", "industrial",
    "consumer", "commercial", "financial", "machinery", "energy",
)


def group_scope(label: str | None) -> str:
    """Scope of one column group inside a consolidating table header.

    A banner ("STATEMENT 1", the registrant's name) is *not* a column group. Returning
    ``unknown`` for it is what keeps a two-group false positive from making an ordinary
    consolidated statement look like a consolidating schedule.
    """
    lowered = norm(label).lower()
    if not lowered:
        return "unknown"
    if any(marker in lowered for marker in ("adjust", "eliminat", "reclass")):
        return "adjustment"
    if "consolidated" in lowered or "combined" in lowered or lowered == "total":
        return "consolidated"
    if any(marker in lowered for marker in _SEGMENT_GROUP_MARKERS):
        return "segment"
    return "unknown"


def title_from_text(text: str | None) -> StatementClass:
    """The last title-shaped line in a block of preceding text.

    Titles are printed as short own-line paragraphs. Page numbers, "Table of Contents" and prose
    that ends in a full stop are skipped rather than guessed at.
    """
    if not text:
        return StatementClass("unknown", "unknown", None, "no_text")
    lines = [part.strip() for part in re.split(r"\u2029|\u2022", text) if part.strip()]
    for line in reversed(lines[-10:]):
        if not (0 < len(line) <= MAX_TITLE_CHARS):
            continue
        if line.rstrip().endswith((".", ":", ";")):
            continue
        candidate = classify(line)
        if candidate.family != "unknown":
            return candidate
    return StatementClass("unknown", "unknown", None, "no_title_line")


__all__ = [
    "CONSOLIDATED_REQUIRED", "FAMILIES", "INCOMPATIBLE_SCOPES", "MAX_TITLE_CHARS", "SCOPES",
    "StatementClass", "classify", "context_is_note", "group_scope", "is_note_text", "norm",
    "scope_compatible", "title_from_text",
]
