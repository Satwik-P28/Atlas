"""Financial Data Fabric v2.

The fabric distinguishes *what the provider said* from *when it said it*. Phase 6
uses the existing immutable ``bar`` contract and adds an explicit dataset view over
it: dataset identity, source rights, security membership, alignment and data-quality
findings. Vendor bytes are never written into this module or committed as fixtures.

The EODHD demo adapter is intentionally a *documented demo* entitlement, not a
claim that the vendor's full history is free. Its rows are local-only and carry
``redistribution=restricted``.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

from ..core.errors import ValidationError
from ..core.temporal import iso_date
from ..market.bars import BarStore
from ..storage.db import Database

DATA_SCHEMA = "atlas.learning.dataset.v2"
DATA_CLASSES = (
    "observed",
    "historically_reconstructed",
    "point_in_time_verified",
    "synthetic",
    "hypothetical",
)

# Minimum number of daily sessions a dataset needs before a learning panel can be
# built. The learning catalog reports it so the interface never offers a dataset that
# the panel loader will reject.
MIN_SESSIONS = 60

PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "provider": "eodhd-demo",
        "name": "EODHD demo API",
        "access": "demo token, no account required for the documented sample symbols",
        "coverage": "AAPL.US, MSFT.US, TSLA.US, VTI.US and AMZN.US resolved during the Phase 6 audit",
        "rights": "Vendor demo terms; local research only; no redistribution asserted",
        "redistribution": "restricted",
        "freshness": "retrieved at ingestion; historical display vintage is not evidenced",
        "adjustment": "raw OHLCV plus vendor adjusted_close; Phase 6 uses the post-split raw window",
        "status": "implemented adapter; local cache is not committed",
    },
    {
        "provider": "sec-edgar",
        "name": "U.S. SEC EDGAR",
        "access": "public, fair-access User-Agent required",
        "coverage": "filings and XBRL company facts; no OHLCV",
        "rights": "U.S. federal government work, public domain",
        "redistribution": "public_domain",
        "freshness": "filing acceptance timestamp",
        "adjustment": "not applicable",
        "status": "existing Phase 1 source",
    },
    {
        "provider": "us-treasury",
        "name": "U.S. Department of the Treasury",
        "access": "public CSV",
        "coverage": "daily par yield curve",
        "rights": "U.S. federal government work, public domain",
        "redistribution": "public_domain",
        "freshness": "daily publication date",
        "adjustment": "not applicable",
        "status": "existing Phase 5 fixture",
    },
    {
        "provider": "fred",
        "name": "FRED / ALFRED",
        "access": "public CSV endpoints; ALFRED vintages require the API",
        "coverage": "macro series; no security OHLCV",
        "rights": "FRED terms and series-specific attribution",
        "redistribution": "restricted",
        "freshness": "series publication; ALFRED vintage required for point-in-time",
        "adjustment": "not applicable",
        "status": "catalogued, not used for the Phase 6 equity panel",
    },
    {
        "provider": "user-csv",
        "name": "User-authorized CSV/Parquet import",
        "access": "local file supplied by the user",
        "coverage": "declared by the user",
        "rights": "user responsibility; Atlas records the declaration",
        "redistribution": "user_responsibility",
        "freshness": "file declaration",
        "adjustment": "explicit column mapping required",
        "status": "adapter contract; no dataset bundled",
    },
)

DATASET_QUALITY_CODES = (
    "duplicate_session",
    "nonpositive_price",
    "impossible_ohlc",
    "invalid_volume",
    "missing_session",
    "insufficient_overlap",
    "unadjusted_split_window",
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _source_row(db: Database, source_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT source_id, name, kind, homepage, licence, redistribution, notes FROM source WHERE source_id = ?",
        (source_id,),
    )
    return dict(row) if row else None


def _ticker(db: Database, security_id: str) -> str | None:
    row = db.query_one(
        "SELECT ta.ticker FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
        "WHERE l.security_id = ? ORDER BY ta.valid_from DESC LIMIT 1",
        (security_id,),
    )
    return row["ticker"] if row else None


def _security_label(db: Database, security_id: str) -> dict[str, Any]:
    row = db.query_one(
        "SELECT s.security_id, s.issuer_id, s.class_designation, s.security_type, "
        "i.legal_name, i.cik FROM security s JOIN issuer i ON i.issuer_id = s.issuer_id "
        "WHERE s.security_id = ?",
        (security_id,),
    )
    if row is None:
        raise ValidationError("dataset cites an unknown security", security_id=security_id)
    return {**dict(row), "ticker": _ticker(db, security_id)}


def dataset_id(source_id: str) -> str:
    return f"{source_id}:all"


def catalog(db: Database) -> list[dict[str, Any]]:
    """Return datasets that are actually present, never an aspirational list."""
    rows = db.query(
        "SELECT source_id, COUNT(DISTINCT security_id) AS securities, "
        "COUNT(DISTINCT substr(ts_utc,1,10)) AS sessions, MIN(ts_utc) AS first, "
        "MAX(ts_utc) AS last FROM bar WHERE interval = '1d' "
        "GROUP BY source_id HAVING securities >= 1 ORDER BY securities DESC, source_id"
    )
    items = []
    for row in rows:
        source = _source_row(db, row["source_id"])
        if source is None:
            continue
        synthetic = source["kind"] in {"synthetic", "synthetic_fixture"}
        items.append({
            "dataset_id": dataset_id(row["source_id"]),
            "source_id": row["source_id"],
            "name": source["name"],
            "data_class": "synthetic" if synthetic else "observed",
            "securities": row["securities"],
            "sessions": row["sessions"],
            # A dataset below the panel minimum cannot load: advertising it as
            # selectable produced a 422 on every page visit instead of a clear state.
            "min_sessions": MIN_SESSIONS,
            "eligible": int(row["sessions"]) >= MIN_SESSIONS,
            "start": row["first"],
            "end": row["last"],
            "rights": source["redistribution"],
            "licence": source["licence"],
            "point_in_time_verified": False,
            "note": (
                "Synthetic values, not market observations."
                if synthetic
                else "Provider observations without archived historical display vintage; "
                     "treat as reconstructed rather than point-in-time verified."
            ),
        })
    return items


def _sessions_between(start: str, end: str) -> int:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    count = 0
    current = first
    while current <= last:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def load_panel(
    db: Database,
    *,
    dataset: str | None = None,
    source_id: str | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    min_sessions: int = MIN_SESSIONS,
) -> dict[str, Any]:
    """Build an aligned close/volume panel from immutable bars.

    ``dataset`` is ``source:all`` as returned by :func:`catalog`. The panel uses one
    price observation per security/session and the intersection of available dates,
    so a missing security is counted rather than forward-filled.
    """
    if source_id is None and dataset:
        source_id = dataset.split(":", 1)[0]
    if not source_id:
        raise ValidationError("dataset or source_id is required")
    source = _source_row(db, source_id)
    if source is None:
        raise ValidationError("dataset source is not registered", source_id=source_id)
    start_date = iso_date(start) if start else "1900-01-01"
    end_date = iso_date(end) if end else "2999-12-31"
    rows = db.query(
        "SELECT DISTINCT security_id, mic FROM bar WHERE source_id = ? AND interval = '1d' "
        "AND ts_utc <= ? ORDER BY security_id",
        (source_id, end_date + "T23:59:59Z"),
    )
    if not rows:
        raise ValidationError("dataset has no daily observations", source_id=source_id)
    instruments: list[dict[str, Any]] = []
    series: dict[str, dict[str, float]] = {}
    volumes: dict[str, dict[str, float]] = {}
    quality: list[dict[str, Any]] = []
    for row in rows:
        bars = BarStore(db).query(row["security_id"], row["mic"], start_date, end_date)
        if not bars:
            continue
        by_date: dict[str, Any] = {}
        for bar in bars:
            if bar.session_date in by_date:
                quality.append({"code": "duplicate_session", "security_id": row["security_id"],
                                "date": bar.session_date, "severity": "error"})
            by_date[bar.session_date] = bar
        if len(by_date) < min_sessions:
            continue
        meta = _security_label(db, row["security_id"])
        instruments.append({
            "security_id": row["security_id"], "mic": row["mic"].upper(),
            "ticker": meta.get("ticker") or row["security_id"],
            "name": meta.get("legal_name"), "class_designation": meta.get("class_designation"),
            "sessions": len(by_date), "first": min(by_date), "last": max(by_date),
        })
        series[row["security_id"]] = {day: float(bar.close) for day, bar in by_date.items()}
        volumes[row["security_id"]] = {
            day: float(bar.volume) for day, bar in by_date.items() if bar.volume is not None
        }
        for bar in bars:
            for code, detail in bar.structural_flags():
                quality.append({"code": code if code != "non_positive_price" else "nonpositive_price",
                                "security_id": row["security_id"], "date": bar.session_date,
                                "severity": "error", "detail": detail})
    if not instruments:
        raise ValidationError("no security has enough observations for this dataset",
                              source_id=source_id, min_sessions=min_sessions)
    dates = sorted(set.intersection(*(set(value) for value in series.values())))
    if len(dates) < min_sessions:
        quality.append({
            "code": "insufficient_overlap", "severity": "error",
            "detail": f"{len(dates)} aligned sessions, minimum {min_sessions}",
        })
        raise ValidationError("dataset does not have enough aligned sessions",
                              sessions=len(dates), minimum=min_sessions)
    ordered = {security: [value[day] for day in dates] for security, value in series.items()}
    ordered_volumes = {
        security: [value.get(day) for day in dates] for security, value in volumes.items()
    }
    expected = _sessions_between(dates[0], dates[-1])
    missing = max(0, expected - len(dates))
    if missing:
        quality.append({"code": "missing_session", "severity": "warning",
                        "detail": f"{missing} weekday session(s) absent from the aligned panel"})
    payload = {
        "schema": DATA_SCHEMA,
        "dataset_id": dataset_id(source_id),
        "source_id": source_id,
        "name": source["name"],
        "data_class": "synthetic" if source["kind"] in {"synthetic", "synthetic_fixture"} else "observed",
        "point_in_time_verified": False,
        "rights": source["redistribution"],
        "licence": source["licence"],
        "instruments": instruments,
        "dates": dates,
        "closes": ordered,
        "volumes": ordered_volumes,
        "coverage": {
            "securities": len(instruments),
            "sessions": len(dates),
            "start": dates[0],
            "end": dates[-1],
            "expected_weekdays": expected,
            "missing_weekdays": missing,
            "adjustment": "raw close; corporate actions are not interpolated",
            "historical_vintage": "provider retrieval only; no displayed-vintage archive",
        },
        "quality": quality,
        "quality_summary": {
            "errors": sum(1 for item in quality if item["severity"] == "error"),
            "warnings": sum(1 for item in quality if item["severity"] == "warning"),
            "checks": list(DATASET_QUALITY_CODES),
        },
        "provider_catalog": [item for item in PROVIDERS if item["provider"] == source_id],
        "limitations": [
            "The panel is the intersection of available securities; absent names are not imputed.",
            "Raw prices do not include dividends; total-return claims require an adjustment contract.",
            "A provider download does not prove what the provider displayed at a past instant.",
            "Restricted vendor history is not redistributed with the source repository.",
        ],
    }
    payload["content_hash"] = _hash(payload)
    return payload


def panel_from_series(
    series: Mapping[str, Iterable[float]],
    *,
    volumes: Mapping[str, Iterable[float | None]] | None = None,
    dates: Iterable[str] | None = None,
    data_class: str = "synthetic",
    source_id: str = "atlas-synthetic",
    name: str = "Deterministic learning fixture",
) -> dict[str, Any]:
    """Construct a panel for independent tests without touching provider data."""
    closes = {key: [float(value) for value in values] for key, values in series.items()}
    length = len(next(iter(closes.values())))
    if any(len(values) != length for values in closes.values()):
        raise ValidationError("all test series must have the same length")
    day_values = list(dates) if dates is not None else [
        (date(2022, 1, 3) + timedelta(days=index)).isoformat() for index in range(length)
    ]
    if len(day_values) != length:
        raise ValidationError("dates and series lengths differ")
    instruments = [
        {"security_id": key, "mic": "XNAS", "ticker": key, "name": key,
         "class_designation": "test series", "sessions": length,
         "first": day_values[0], "last": day_values[-1]}
        for key in closes
    ]
    payload = {
        "schema": DATA_SCHEMA,
        "dataset_id": f"{source_id}:test",
        "source_id": source_id,
        "name": name,
        "data_class": data_class,
        "point_in_time_verified": False,
        "rights": "public_domain" if data_class == "synthetic" else "restricted",
        "licence": "Apache-2.0 test fixture" if data_class == "synthetic" else None,
        "instruments": instruments,
        "dates": day_values,
        "closes": closes,
        "volumes": {key: list(values) for key, values in (volumes or {}).items()} or {
            key: [1_000_000.0] * length for key in closes
        },
        "coverage": {"securities": len(closes), "sessions": length,
                     "start": day_values[0], "end": day_values[-1],
                     "expected_weekdays": length, "missing_weekdays": 0,
                     "adjustment": "test fixture", "historical_vintage": "not applicable"},
        "quality": [],
        "quality_summary": {"errors": 0, "warnings": 0, "checks": list(DATASET_QUALITY_CODES)},
        "provider_catalog": [],
        "limitations": ["Synthetic deterministic fixture for software validation."]
        if data_class == "synthetic" else ["Test panel; provenance supplied by the caller."],
    }
    payload["content_hash"] = _hash(payload)
    return payload


def validate_panel(panel: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(panel, dict) or panel.get("schema") != DATA_SCHEMA:
        raise ValidationError("unsupported dataset schema", supported=DATA_SCHEMA)
    if panel.get("data_class") not in DATA_CLASSES:
        raise ValidationError("unknown data class", data_class=panel.get("data_class"))
    dates = panel.get("dates") or []
    closes = panel.get("closes") or {}
    if not dates or not closes:
        raise ValidationError("dataset has no observations")
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise ValidationError("dataset dates must be unique and sorted")
    for security, values in closes.items():
        if len(values) != len(dates):
            raise ValidationError("dataset series is not aligned", security_id=security)
        if any(not math.isfinite(float(value)) or float(value) <= 0 for value in values):
            raise ValidationError("dataset contains nonpositive or nonfinite prices",
                                  security_id=security)
    return panel


__all__ = [
    "DATA_CLASSES",
    "DATA_SCHEMA",
    "DATASET_QUALITY_CODES",
    "PROVIDERS",
    "catalog",
    "dataset_id",
    "load_panel",
    "panel_from_series",
    "validate_panel",
]
