"""Materialized, generation-keyed financial metrics.

The Phase 2 screener recomputed a full point-in-time selection for every issuer on every
request. That is correct but repeats identical work. This module stores the *same*
``issuer_metrics`` payload under a key that includes:

* the exact information instant (never rounded for explicit historical queries);
* the temporal mode;
* the calculation model version;
* a generation token derived from the issuer's evidence, filings and market bars.

A stale generation is never returned. Recomputing a single issuer after an amendment
invalidates only that issuer's cached rows; every other issuer stays warm.

Current-time requests are normalized to end-of-day, matching the conservative
availability convention used elsewhere. An explicit ``as_of`` is preserved exactly, so a
day-precision cache key cannot smuggle intraday knowledge backwards.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.temporal import AsOfMode, iso, iso_date, utcnow
from ..storage.db import Database
from . import read_models

MODEL_VERSION = "atlas.materialized_metrics.v1"


def normalize_as_of(as_of: str | None) -> str:
    if as_of:
        return iso(as_of)
    return f"{iso_date(utcnow())}T23:59:59Z"


def generation(db: Database, issuer_id: str) -> str:
    """A token covering every input that can change this issuer's metrics."""
    row = db.query_one(
        "SELECT COALESCE(MAX(evidence.ingest_seq), 0) AS seq, COUNT(*) AS n "
        "FROM evidence WHERE evidence.entity_id = ?",
        (issuer_id,),
    )
    filings = db.scalar(
        "SELECT COUNT(*) FROM filing WHERE issuer_id = ?", (issuer_id,), 0
    )
    bars = db.scalar(
        "SELECT COUNT(*) FROM bar b JOIN security s ON s.security_id = b.security_id "
        "WHERE s.issuer_id = ?",
        (issuer_id,),
        0,
    )
    return f"{row['seq'] if row else 0}|{row['n'] if row else 0}|{filings}|{bars}|{MODEL_VERSION}"


def get_issuer_metrics(
    db: Database,
    issuer_id: str,
    *,
    as_of: str | None = None,
    mode: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    instant = normalize_as_of(as_of)
    resolved_mode = mode or AsOfMode.PUBLIC_AVAILABLE.value
    try:
        AsOfMode(resolved_mode)
    except ValueError:
        from ..core.errors import ValidationError

        raise ValidationError("unknown as-of mode", mode=resolved_mode)
    token = generation(db, issuer_id)
    existing = db.query_one(
        "SELECT payload_json FROM metric_snapshot WHERE issuer_id = ? AND as_of = ? "
        "AND mode = ? AND model_version = ? AND generation = ?",
        (issuer_id, instant, resolved_mode, MODEL_VERSION, token),
    )
    if existing is not None and not force:
        return json.loads(existing["payload_json"])

    payload = read_models.issuer_metrics(
        db, issuer_id, as_of=instant, mode=resolved_mode
    )
    evidence_ids = sorted(
        {
            evidence_id
            for metric in payload.get("metrics", {}).values()
            for evidence_id in metric.get("evidence_ids", [])
        }
    )
    now = iso(utcnow())
    db.execute(
        "INSERT INTO metric_snapshot (issuer_id, as_of, mode, model_version, generation, "
        "period_end, payload_json, evidence_count, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(issuer_id, as_of, mode, model_version) DO UPDATE SET "
        "generation = excluded.generation, period_end = excluded.period_end, "
        "payload_json = excluded.payload_json, evidence_count = excluded.evidence_count, "
        "updated_at = excluded.updated_at",
        (
            issuer_id,
            instant,
            resolved_mode,
            MODEL_VERSION,
            token,
            payload.get("period_end"),
            json.dumps(payload, sort_keys=True),
            len(evidence_ids),
            now,
            now,
        ),
    )
    return payload


def invalidate_issuer(db: Database, issuer_id: str) -> int:
    cursor = db.execute("DELETE FROM metric_snapshot WHERE issuer_id = ?", (issuer_id,))
    return int(cursor.rowcount or 0)


def invalidate_all(db: Database) -> int:
    cursor = db.execute("DELETE FROM metric_snapshot")
    return int(cursor.rowcount or 0)


def stats(db: Database) -> dict[str, Any]:
    rows = db.query(
        "SELECT COUNT(*) AS snapshots, COUNT(DISTINCT issuer_id) AS issuers, "
        "COALESCE(MAX(updated_at), '') AS last_updated FROM metric_snapshot"
    )
    return dict(rows[0]) if rows else {"snapshots": 0, "issuers": 0, "last_updated": ""}
