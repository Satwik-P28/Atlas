"""Guided real-data onboarding.

The interface exists so a user can bring their own lawfully obtained market data into Atlas
without guessing which columns are accepted or what the importer will do to them. It is a
two-step contract:

1. ``preview`` parses the file with the production importer and writes nothing. The user
   sees the column mapping, the accepted and ignored columns, the coverage, the duplicates
   and every issue the parser found.
2. ``import`` runs the same parse again and persists only when the request says
   ``confirm: true``. The dataset is registered as a user-supplied source with
   ``redistribution = user_responsibility`` and the licence text the user supplied.

Atlas never fetches provider data from this route, so it cannot be used as an SSRF pivot,
and it never stores a credential: there is nothing here that accepts one.
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..entities.master import SecurityMaster
from ..ingestion.market_csv import import_csv_bars
from ..market.bars import BarStore
from ..market.calendar import TradingCalendar
from ..storage.db import Database
from ..storage.sources import SourceRegistry

MAX_CSV_CHARS = 2_000_000


class MarketImportRequest(BaseModel):
    security_id: str = Field(min_length=3, max_length=80)
    mic: str = Field(min_length=2, max_length=12)
    csv: str = Field(min_length=20, max_length=MAX_CSV_CHARS)
    source_name: str = Field(default="User-supplied market data", min_length=3, max_length=120)
    licence: str = Field(min_length=3, max_length=400)
    currency: str = Field(default="USD", min_length=3, max_length=8)


class MarketImportConfirm(MarketImportRequest):
    confirm: bool = False


def _parse(db: Database, body: MarketImportRequest) -> tuple[Any, Any]:
    security = SecurityMaster(db).security(body.security_id)
    if security is None:
        raise HTTPException(status_code=404, detail={
            "code": "unknown_security",
            "message": "the security is not registered in this Atlas database",
            "context": {"security_id": body.security_id},
        })
    # A preview must not write: a venue row is created only on import, when the caller has
    # confirmed. Without one the parser still works, using the default session close.
    known_venue = db.query_one("SELECT mic FROM venue WHERE mic = ?", (body.mic.upper(),))
    calendar: TradingCalendar | None = TradingCalendar(db) if known_venue else None
    with tempfile.TemporaryDirectory(prefix="atlas-onboarding-") as directory:
        path = os.path.join(directory, "upload.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(body.csv)
        result = import_csv_bars(
            path,
            security_id=body.security_id,
            mic=body.mic.upper(),
            source_id="onboarding-preview",
            currency=body.currency.upper(),
            calendar=calendar,
        )
    return security, result


def _payload(db: Database, body: MarketImportRequest, security: Any, result: Any) -> dict[str, Any]:
    sessions = [bar.session_date for bar in result.bars]
    duplicates = Counter(sessions)
    repeated = sorted(session for session, count in duplicates.items() if count > 1)
    existing = int(db.scalar(
        "SELECT COUNT(*) FROM bar WHERE security_id = ? AND mic = ?",
        (body.security_id, body.mic.upper()), default=0,
    ) or 0)
    return {
        "schema": "atlas.onboarding.market_preview.v1",
        "security": {
            "security_id": security["security_id"],
            "issuer_id": security.get("issuer_id"),
        },
        "request": {"mic": body.mic.upper(), "currency": body.currency.upper(),
                    "source_name": body.source_name, "licence": body.licence},
        "columns": result.columns,
        "source_columns": result.source_columns,
        "adjusted_columns_ignored": result.adjusted_columns_ignored,
        "rows_read": result.rows_read,
        "rows_skipped": result.rows_skipped,
        "bars_accepted": len(result.bars),
        "coverage": {
            "first_session": min(sessions) if sessions else None,
            "last_session": max(sessions) if sessions else None,
            "sessions": len(duplicates),
        },
        "duplicates": {
            "bars_already_stored_for_series": existing,
            "sessions_repeated_in_file": repeated[:20],
            "policy": "a bar for a session that already exists is stored as a revision when its "
                      "values differ; an exact duplicate is skipped. Rows repeated inside the "
                      "file are reported and the first occurrence wins.",
        },
        "issues": result.issues[:50],
        "issue_count": len(result.issues),
        "rights": {
            "redistribution": "user_responsibility",
            "licence": body.licence,
            "note": "Atlas stores the file you supplied and records the licence you declared. "
                    "It does not redistribute your data and makes no claim about your right to "
                    "use it.",
        },
        "wrote_anything": False,
    }


def register_onboarding_routes(app: Any, get_db: Callable[..., Any]) -> None:
    @app.get("/api/onboarding/status", tags=["onboarding"])
    def onboarding_status(db: Database = Depends(get_db)) -> dict[str, Any]:
        try:
            import pyarrow  # noqa: F401

            parquet = {"available": True, "endpoint": "atlas bars import --file <path>.parquet"}
        except ImportError:
            parquet = {"available": False,
                       "endpoint": "install the 'columnar' extra to enable Parquet import"}
        securities = int(db.scalar("SELECT COUNT(*) FROM security", default=0) or 0)
        bars = int(db.scalar("SELECT COUNT(*) FROM bar", default=0) or 0)
        return {
            "schema": "atlas.onboarding.status.v1",
            "imports": {
                "market_csv": {"available": True,
                               "endpoint": "/api/onboarding/market/preview"},
                "market_parquet": parquet,
                "sec_edgar": {
                    "available": True,
                    "mode": "cli",
                    "command": "atlas sec sync --cik <CIK>",
                    "user_agent_configured": bool(os.environ.get("ATLAS_SEC_USER_AGENT", "").strip()),
                    "note": "Atlas refuses to fetch from SEC without a declared identity and "
                            "contact; set ATLAS_SEC_USER_AGENT before syncing.",
                },
                "fred_alfred": {
                    "available": False,
                    "mode": "offline",
                    "note": "FRED and ALFRED observations are ingested by the offline economic "
                            "ingest scripts in this release; there is no HTTP route, so the "
                            "terminal cannot claim a provider connection it does not have.",
                },
            },
            "database": {"securities": securities, "bars": bars},
            "credentials": {
                "accepted_by_this_interface": [],
                "policy": "no route here accepts, stores or returns a provider credential; "
                          "credentials live in the environment of the ingestion command",
            },
        }

    @app.post("/api/onboarding/market/preview", tags=["onboarding"])
    def market_preview(body: MarketImportRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        security, result = _parse(db, body)
        return _payload(db, body, security, result)

    @app.post("/api/onboarding/market/import", tags=["onboarding"])
    def market_import(body: MarketImportConfirm, db: Database = Depends(get_db)) -> dict[str, Any]:
        if not body.confirm:
            raise HTTPException(status_code=422, detail={
                "code": "confirmation_required",
                "message": "preview the file first, then repeat the request with confirm: true",
            })
        security, result = _parse(db, body)
        preview = _payload(db, body, security, result)
        if not result.bars:
            raise HTTPException(status_code=422, detail={
                "code": "nothing_to_import",
                "message": "the file produced no acceptable bars",
                "context": {"issues": result.issues[:20]},
            })
        if db.query_one("SELECT mic FROM venue WHERE mic = ?", (body.mic.upper(),)) is None:
            TradingCalendar(db).ensure_venue(body.mic.upper())
        source_id = SourceRegistry(db).ensure_custom(
            body.source_name,
            kind="csv_import",
            licence=body.licence,
            redistribution="user_responsibility",
            notes="imported through the guided onboarding interface",
        )
        for bar in result.bars:
            bar.source_id = source_id
        summary = BarStore(db).ingest(result.bars)
        return {
            **preview,
            "wrote_anything": True,
            "source_id": source_id,
            "stored": summary.to_dict(),
            "summary": (
                f"read {result.rows_read} row(s), imported {len(result.bars)}, "
                f"inserted={summary.inserted} duplicates={summary.duplicates} "
                f"revisions={summary.revisions}; {len(result.issues)} issue(s)"
            ),
        }

    return None


__all__ = [
    "MAX_CSV_CHARS",
    "MarketImportConfirm",
    "MarketImportRequest",
    "register_onboarding_routes",
]
