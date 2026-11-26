"""Price Movement Intelligence endpoint: ``POST /api/securities/{id}/price-explanations``.

The route is a thin translation layer. Every decision about what happened, which
observation represents a boundary, which evidence was admissible at a cutoff and which
explanations remain unproven lives in :mod:`atlas.research.move_intelligence`, so the
HTTP surface cannot drift from the engine or from the chart.

The request forbids unknown fields: a client that sends a misspelled
``information_cutoff`` must not silently receive an unbounded retrospective answer.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ...research import investigations, move_intelligence
from ...storage.db import Database


class PriceExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_session: str = Field(description="First selected trading session (YYYY-MM-DD)")
    end_session: str = Field(description="Last selected trading session (YYYY-MM-DD)")
    timeframe: Literal["1d"] = Field(
        default="1d", description="Chart timeframe; only stored daily observations are supported"
    )
    timezone: str = Field(
        default=move_intelligence.DEFAULT_TIMEZONE,
        description="Display timezone for the selected sessions",
    )
    price_basis: Literal["price", "split_adjusted", "total_return"] = Field(
        default="split_adjusted",
        description="Return convention used for the headline statistics",
    )
    mode: Literal["historical_reconstruction", "retrospective_investigation"] = Field(
        default="retrospective_investigation",
        description=(
            "historical_reconstruction requires information_cutoff and excludes later evidence; "
            "retrospective_investigation shows later evidence but excludes it from the ranking"
        ),
    )
    information_cutoff: str | None = Field(
        default=None,
        description="Information cutoff for historical reconstruction (YYYY-MM-DD)",
    )
    benchmark_security_id: str | None = Field(
        default=None, description="Canonical security id used for relative statistics"
    )
    peer_security_ids: list[str] = Field(default_factory=list, max_length=10)
    estimation_sessions: int = Field(default=120, ge=30, le=10_000)
    evidence_limit: int = Field(default=50, ge=1, le=200)
    return_convention: Literal[
        "auto", "interval_close_to_close", "single_session_close_to_close"
    ] = Field(
        default="auto",
        description=(
            "auto uses an interval close-to-close return for a range and a previous-session "
            "close-to-close return for a one-candle selection; the engine refuses a "
            "one-session return when no prior eligible close is stored"
        ),
    )


class SaveInvestigationRequest(PriceExplanationRequest):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None, max_length=200, description="Display name; defaults to ticker and interval"
    )
    version: str = Field(
        default="1.0.0",
        pattern=r"^\d+\.\d+\.\d+$",
        description="Immutable version; an existing name+version is refused",
    )


def build_price_explanations_router(get_db: Callable[..., Any]) -> APIRouter:
    router = APIRouter()

    def _request(security_id: str, body: PriceExplanationRequest) -> move_intelligence.ExplanationRequest:
        return move_intelligence.ExplanationRequest(
            security_id=security_id,
            start_session=body.start_session,
            end_session=body.end_session,
            timeframe=body.timeframe,
            timezone=body.timezone,
            price_basis=body.price_basis,
            mode=body.mode,
            information_cutoff=body.information_cutoff,
            benchmark_security_id=body.benchmark_security_id,
            peer_security_ids=tuple(body.peer_security_ids),
            estimation_sessions=body.estimation_sessions,
            evidence_limit=body.evidence_limit,
            return_convention=body.return_convention,
        )

    @router.post("/api/securities/{security_id}/price-explanations", tags=["research"])
    def price_explanations(
        security_id: str,
        body: PriceExplanationRequest,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return move_intelligence.explain_range(db, _request(security_id, body))

    @router.post(
        "/api/securities/{security_id}/price-investigations",
        tags=["research"],
        status_code=201,
    )
    def save_investigation(
        security_id: str,
        body: SaveInvestigationRequest,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        # The server recomputes the investigation: a client cannot save a report it
        # assembled itself. Reuse of an existing name+version is refused by the store.
        report = move_intelligence.explain_range(db, _request(security_id, body))
        return investigations.save(db, report, name=body.name, version=body.version)

    @router.get("/api/securities/{security_id}/price-investigations", tags=["research"])
    def list_investigations(
        security_id: str,
        db: Database = Depends(get_db),
        limit: int = 50,
    ) -> dict[str, Any]:
        items = [
            item
            for item in investigations.list_investigations(db, limit=max(1, min(limit, 200)))
            if item.get("kind") == investigations.KIND
        ]
        filtered = []
        for item in items:
            stored = db.query_one(
                "SELECT document_json FROM research_object WHERE object_id = ?",
                (item["object_id"],),
            )
            document = json.loads(stored["document_json"]) if stored is not None else {}
            spec = document.get("spec") or {}
            if spec.get("security_id") == security_id:
                filtered.append(
                    {
                        **item,
                        "start_session": (spec.get("interval") or {}).get("start_session"),
                        "end_session": (spec.get("interval") or {}).get("end_session"),
                        "as_of": document.get("as_of"),
                        "reproducibility_hash": (spec.get("reproducibility") or {}).get("hash"),
                    }
                )
        return {"schema": investigations.DOCUMENT_SCHEMA, "items": filtered}

    @router.get("/api/research/price-investigations/{object_id}", tags=["research"])
    def get_investigation(object_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return investigations.get(db, object_id)

    @router.get("/api/research/price-investigations/{object_id}/reproduce", tags=["research"])
    def reproduce_investigation(
        object_id: str, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return investigations.reproduce(db, object_id)

    @router.get("/api/research/price-investigations/{object_id}/impact", tags=["research"])
    def investigation_impact(
        object_id: str, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return investigations.impact(db, object_id)

    @router.get("/api/research/price-investigations/{object_id}/export", tags=["research"])
    def export_investigation(
        object_id: str, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return investigations.export(db, object_id)

    return router


__all__ = ["PriceExplanationRequest", "build_price_explanations_router"]
