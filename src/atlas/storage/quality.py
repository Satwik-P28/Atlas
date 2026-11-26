"""Data-quality issue log.

Validation never mutates source values. When Atlas detects something suspicious it
records an issue with a stable code, a severity and enough detail to reproduce the
finding, and keeps the observation as received. The issue log is the audit trail for
"we saw this and did not paper over it".
"""

from __future__ import annotations

from typing import Any

from ..core.ids import issue_id
from ..core.temporal import iso, utcnow
from .db import Database

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"


def record_issue(
    db: Database,
    *,
    scope: str,
    subject_id: str | None,
    code: str,
    severity: str,
    detail: str,
) -> str:
    """Record an issue idempotently (identical findings collapse to one row)."""
    if severity not in {SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR}:
        raise ValueError(f"invalid severity {severity!r}")
    identifier = issue_id(scope, subject_id or "", code, detail)
    db.execute(
        "INSERT INTO data_quality_issue (issue_id, scope, subject_id, code, severity, detail, detected_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(scope, subject_id, code, detail) DO UPDATE SET "
        "severity=excluded.severity",
        (identifier, scope, subject_id, code, severity, detail, iso(utcnow())),
    )
    return identifier


def list_issues(
    db: Database,
    *,
    scope: str | None = None,
    unresolved_only: bool = True,
    severity: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    if unresolved_only:
        clauses.append("resolved_at IS NULL")
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM data_quality_issue{where} ORDER BY detected_at DESC, issue_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = db.query(sql, params)
    return [{k: row[k] for k in row.keys()} for row in rows]


def issue_summary(db: Database) -> dict[str, int]:
    rows = db.query(
        "SELECT severity, COUNT(*) AS n FROM data_quality_issue WHERE resolved_at IS NULL GROUP BY severity"
    )
    summary = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 0, SEVERITY_INFO: 0}
    for row in rows:
        summary[row["severity"]] = row["n"]
    return summary


def resolve_issue(db: Database, identifier: str) -> None:
    db.execute(
        "UPDATE data_quality_issue SET resolved_at = ? WHERE issue_id = ?", (iso(utcnow()), identifier)
    )
