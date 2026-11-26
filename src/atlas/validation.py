"""Dataset integrity validation.

Every check here is read-only. Validation exists to surface the ways a financial
dataset goes quietly wrong: mixed units, look-ahead-unsafe timing, dangling revision
chains, tickers claimed by two securities at once, and bars timestamped on days the
market was closed.

Severity contract:

``error``
    The data is internally inconsistent and should not be trusted or published.
``warning``
    Legal but suspicious; a researcher should look before relying on it.
``info``
    Context worth reporting (e.g. a coverage gap in a source).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from .core.ids import normalize_cik
from .core.temporal import iso_date, parse_iso
from .core.units import parse_unit
from .market.actions import COMPUTABLE_ACTION_TYPES, SPLIT_TYPES, ActionType
from .market.calendar import TradingCalendar
from .storage.db import Database
from .storage.migrations import LATEST_VERSION

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    scope: str
    subject: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "scope": self.scope,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    def add(self, code: str, severity: str, scope: str, subject: str | None, detail: str) -> None:
        self.findings.append(Finding(code=code, severity=severity, scope=scope, subject=subject, detail=detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "checks_run": self.checks_run,
            "findings": [f.to_dict() for f in self.findings],
        }


def run_validation(
    db: Database,
    *,
    issuer_id: str | None = None,
    security_id: str | None = None,
    calendar: TradingCalendar | None = None,
) -> ValidationReport:
    """Run every Phase 1 integrity check."""
    report = ValidationReport()
    _check_schema(db, report)
    _check_foreign_keys(db, report)
    _check_evidence(db, report, issuer_id=issuer_id)
    _check_supersession_graph(db, report)
    _check_identity(db, report)
    _check_corporate_actions(db, report, security_id=security_id)
    _check_bars(db, report, security_id=security_id, calendar=calendar)
    return report


def _check_schema(db: Database, report: ValidationReport) -> None:
    report.checks_run.append("schema_version")
    version = db.schema_version()
    if version != LATEST_VERSION:
        report.add(
            "schema_version_mismatch",
            SEVERITY_ERROR,
            "database",
            str(db.path),
            f"schema version {version} != supported {LATEST_VERSION}",
        )


def _check_foreign_keys(db: Database, report: ValidationReport) -> None:
    report.checks_run.append("foreign_keys")
    violations = db.foreign_key_violations()
    for row in violations[:50]:
        report.add(
            "foreign_key_violation",
            SEVERITY_ERROR,
            "database",
            str(row[0]),
            f"row {row[1]} references missing parent",
        )


def _check_evidence(db: Database, report: ValidationReport, *, issuer_id: str | None) -> None:
    report.checks_run.append("evidence_temporal_invariants")
    where = " WHERE entity_id = ?" if issuer_id else ""
    params: tuple[Any, ...] = (issuer_id,) if issuer_id else ()
    rows = db.query(
        "SELECT evidence_id, entity_id, concept, unit, currency, unit_kind, period_end, period_type, "
        "availability_time, availability_precision, observed_at, value_numeric, value_text "
        "FROM evidence" + where,
        params,
    )
    for row in rows:
        identifier = row["evidence_id"]
        if row["availability_precision"] == "unknown":
            if row["availability_time"] is not None:
                report.add(
                    "unknown_availability_with_timestamp",
                    SEVERITY_ERROR,
                    "evidence",
                    identifier,
                    "record claims unknown availability precision but carries a timestamp",
                )
        elif row["availability_time"] is None:
            report.add(
                "availability_timestamp_missing",
                SEVERITY_ERROR,
                "evidence",
                identifier,
                "record claims evidenced availability but has no timestamp",
            )
        if row["unit_kind"] == "monetary" and not row["currency"]:
            report.add("monetary_evidence_without_currency", SEVERITY_ERROR, "evidence", identifier,
                       f"unit {row['unit']} is monetary but no currency is recorded")
        parsed = parse_unit(row["unit"])
        if parsed.kind.value != row["unit_kind"]:
            report.add(
                "unit_kind_mismatch",
                SEVERITY_ERROR,
                "evidence",
                identifier,
                f"stored unit_kind {row['unit_kind']} disagrees with parsed unit {row['unit']!r} ({parsed.kind.value})",
            )
        if row["period_end"] is None:
            report.add("missing_period_end", SEVERITY_ERROR, "evidence", identifier, "record has no reporting period")
        if row["value_numeric"] is None and row["value_text"] is None:
            report.add("missing_value", SEVERITY_ERROR, "evidence", identifier, "record asserts no value")
        for column in ("observed_at", "availability_time"):
            if row[column] is not None:
                try:
                    parse_iso(row[column])
                except Exception:  # noqa: BLE001
                    report.add("unparsable_timestamp", SEVERITY_ERROR, "evidence", identifier,
                               f"{column} is not a valid timestamp: {row[column]!r}")

    report.checks_run.append("evidence_conflicts")
    conflicts = db.query(
        "SELECT entity_id, concept, unit, COALESCE(period_start,'') AS ps, period_end, accession_number, "
        "COUNT(DISTINCT COALESCE(value_numeric, value_text)) AS n FROM evidence "
        "WHERE accession_number IS NOT NULL GROUP BY entity_id, concept, unit, ps, period_end, accession_number "
        "HAVING n > 1" + (" AND entity_id = ?" if issuer_id else ""),
        params,
    )
    for row in conflicts:
        report.add(
            "contradictory_values_in_filing",
            SEVERITY_WARNING,
            "evidence",
            f"{row['entity_id']}:{row['accession_number']}",
            f"{row['concept']} has {row['n']} distinct values for period ending {row['period_end']}",
        )


def _check_supersession_graph(db: Database, report: ValidationReport) -> None:
    report.checks_run.append("supersession_graph")
    edges = db.query("SELECT superseded_id, superseding_id FROM evidence_supersession")
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    for edge in edges:
        parents.setdefault(edge["superseded_id"], []).append(edge["superseding_id"])
        children.setdefault(edge["superseding_id"], []).append(edge["superseded_id"])
    for node in parents:
        if db.query_one("SELECT 1 FROM evidence WHERE evidence_id = ?", (node,)) is None:
            report.add("dangling_supersession", SEVERITY_ERROR, "evidence", node,
                       "supersession edge references a missing record")
    visited: set[str] = set()
    for start in parents:
        stack: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
        while stack:
            node, path = stack.pop()
            # A node appearing earlier in its own path is a genuine cycle. The node
            # itself is excluded because it was just appended.
            if node in path[:-1]:
                report.add("supersession_cycle", SEVERITY_ERROR, "evidence", node,
                           "supersession chain loops: " + " -> ".join(path))
                continue
            if node in visited:
                continue
            visited.add(node)
            for child in parents.get(node, []):
                stack.append((child, path + (child,)))


def _check_identity(db: Database, report: ValidationReport) -> None:
    report.checks_run.append("identity")
    rows = db.query(
        "SELECT ta.ticker, ta.valid_from, ta.valid_to, ta.status, l.security_id FROM ticker_assignment ta "
        "JOIN listing l ON l.listing_id = ta.listing_id WHERE ta.status != 'retracted' "
        "ORDER BY ta.ticker, ta.valid_from"
    )
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row["ticker"], []).append(row)
    for ticker, assignments in grouped.items():
        for index, first in enumerate(assignments):
            for second in assignments[index + 1 :]:
                if first["security_id"] == second["security_id"]:
                    continue
                first_end = first["valid_to"] or "9999-12-31"
                second_end = second["valid_to"] or "9999-12-31"
                if first["valid_from"] <= second_end and second["valid_from"] <= first_end:
                    report.add(
                        "ticker_claimed_by_two_securities",
                        SEVERITY_WARNING,
                        "identity",
                        ticker,
                        f"{first['security_id']} and {second['security_id']} both claim {ticker} "
                        f"over {max(first['valid_from'], second['valid_from'])}..{min(first_end, second_end)}",
                    )

    orphan_issuers = db.query(
        "SELECT issuer_id FROM issuer WHERE issuer_id NOT IN (SELECT DISTINCT issuer_id FROM security)"
    )
    for row in orphan_issuers:
        report.add("issuer_without_security", SEVERITY_INFO, "identity", row["issuer_id"],
                   "issuer has no securities recorded")

    bad_windows = db.query(
        "SELECT ticker_assignment_id, ticker, valid_from, valid_to FROM ticker_assignment "
        "WHERE valid_to IS NOT NULL AND valid_to < valid_from"
    )
    for row in bad_windows:
        report.add("inverted_ticker_window", SEVERITY_ERROR, "identity", row["ticker_assignment_id"],
                   f"{row['ticker']} ends {row['valid_to']} before it starts {row['valid_from']}")


def _check_corporate_actions(db: Database, report: ValidationReport, *, security_id: str | None) -> None:
    report.checks_run.append("corporate_actions")
    where = " WHERE security_id = ?" if security_id else ""
    params: tuple[Any, ...] = (security_id,) if security_id else ()
    rows = db.query("SELECT * FROM corporate_action" + where, params)
    for row in rows:
        identifier = row["action_id"]
        action_type = row["action_type"]
        if action_type in SPLIT_TYPES:
            if row["ratio_from"] is None or row["ratio_to"] is None:
                report.add("split_missing_ratio", SEVERITY_ERROR, "corporate_action", identifier,
                           "split action has no ratio")
                continue
            from_f, to = Decimal(row["ratio_from"]), Decimal(row["ratio_to"])
            if from_f <= 0 or to <= 0:
                report.add("split_non_positive_ratio", SEVERITY_ERROR, "corporate_action", identifier,
                           f"ratios must be positive, found {from_f}:{to}")
            if action_type == ActionType.SPLIT.value and to <= from_f:
                report.add("split_direction_inconsistent", SEVERITY_WARNING, "corporate_action", identifier,
                           f"forward split with ratio {from_f}:{to} does not increase the share count")
        elif action_type == ActionType.CASH_DIVIDEND.value:
            if row["cash_amount"] is None or row["currency"] is None:
                report.add("dividend_missing_terms", SEVERITY_ERROR, "corporate_action", identifier,
                           "cash dividend without amount or currency")
        if action_type in COMPUTABLE_ACTION_TYPES and row["ex_date"] is None and row["effective_date"] is None:
            report.add("action_missing_effective_date", SEVERITY_ERROR, "corporate_action", identifier,
                       f"{action_type} has neither ex-date nor effective date")
        if action_type in COMPUTABLE_ACTION_TYPES and not row["availability_time"]:
            report.add("action_without_availability", SEVERITY_WARNING, "corporate_action", identifier,
                       f"{action_type} has no evidenced public availability; knowledge-filtered views will omit it")


def _check_bars(
    db: Database,
    report: ValidationReport,
    *,
    security_id: str | None,
    calendar: TradingCalendar | None,
) -> None:
    report.checks_run.append("market_bars")
    where = " WHERE security_id = ?" if security_id else ""
    params: tuple[Any, ...] = (security_id,) if security_id else ()
    rows = db.query(
        "SELECT security_id, mic, ts_utc, revision_seq, open, high, low, close, volume, "
        "(SELECT MAX(b2.revision_seq) FROM bar b2 WHERE b2.security_id = bar.security_id AND b2.mic = bar.mic "
        " AND b2.interval = bar.interval AND b2.ts_utc = bar.ts_utc AND b2.source_id = bar.source_id) AS latest_seq "
        "FROM bar" + where,
        params,
    )
    for row in rows:
        subject = f"{row['security_id']}:{row['ts_utc']}"
        if row["latest_seq"] is not None and row["revision_seq"] != row["latest_seq"] and not security_id:
            report.add("stale_bar_revision", SEVERITY_INFO, "market_bar", subject,
                       f"revision {row['revision_seq']} superseded by {row['latest_seq']}")
        o, h, l, c = (Decimal(row["open"]), Decimal(row["high"]), Decimal(row["low"]), Decimal(row["close"]))
        if min(o, h, l, c) <= 0:
            report.add("non_positive_price", SEVERITY_ERROR, "market_bar", subject, "non-positive price")
        if h < max(o, l, c):
            report.add("invalid_ohlc", SEVERITY_ERROR, "market_bar", subject, f"high {h} < max(open,low,close)")
        if l > min(o, h, c):
            report.add("invalid_ohlc", SEVERITY_ERROR, "market_bar", subject, f"low {l} > min(open,high,close)")
        if row["volume"] is not None and Decimal(row["volume"]) < 0:
            report.add("negative_volume", SEVERITY_ERROR, "market_bar", subject, f"volume {row['volume']}")

    if calendar is not None:
        pairs = db.query("SELECT DISTINCT security_id, mic FROM bar" + where, params)
        for pair in pairs:
            span = db.query_one(
                "SELECT MIN(substr(ts_utc,1,10)) AS lo, MAX(substr(ts_utc,1,10)) AS hi FROM bar "
                "WHERE security_id = ? AND mic = ?",
                (pair["security_id"], pair["mic"]),
            )
            if not span or not span["lo"]:
                continue
            calendar.ensure_range(pair["mic"], span["lo"], span["hi"])
            off = db.query(
                "SELECT DISTINCT substr(ts_utc,1,10) AS d FROM bar WHERE security_id = ? AND mic = ? "
                "AND substr(ts_utc,1,10) NOT IN (SELECT session_date FROM trading_session WHERE mic = ?)",
                (pair["security_id"], pair["mic"], pair["mic"]),
            )
            for row in off:
                report.add("bar_outside_calendar", SEVERITY_ERROR, "market_bar",
                           f"{pair['security_id']}:{row['d']}", "observation on a non-session date")


def summarize(db: Database) -> dict[str, Any]:
    """Headline dataset statistics for the ``stats`` command."""
    from .evidence.kernel import EvidenceKernel
    from .storage.quality import issue_summary

    kernel = EvidenceKernel(db)
    evidence_stats = kernel.stats()
    counts = {
        table: db.row_count(table)
        for table in (
            "issuer", "security", "listing", "ticker_assignment", "security_identifier",
            "filing", "evidence", "raw_document", "bar", "corporate_action",
            "trading_session", "data_quality_issue", "source",
        )
    }
    coverage = {
        row["source_id"]: row["n"]
        for row in db.query("SELECT source_id, COUNT(*) AS n FROM raw_document GROUP BY source_id")
    }
    return {
        "schema_version": db.schema_version(),
        "path": str(db.path),
        "tables": counts,
        "evidence": evidence_stats,
        "issues": issue_summary(db),
        "documents_by_source": coverage,
        "integrity_check": db.integrity_check(),
    }
