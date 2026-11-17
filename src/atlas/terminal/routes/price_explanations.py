"""Price Movement Intelligence endpoint: ``POST /api/securities/{id}/price-explanations``.

The route is a thin translation layer. Every decision about what happened, which
observation represents a boundary, which evidence was admissible at a cutoff and which
explanations remain unproven lives in :mod:`atlas.research.move_intelligence`, so the
HTTP surface cannot drift from the engine or from the chart.

The request forbids unknown fields: a client that sends a misspelled
``information_cutoff`` must not silently receive an unbounded retrospective answer.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ...research import move_intelligence
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


def build_price_explanations_router(get_db: Callable[..., Any]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/securities/{security_id}/price-explanations", tags=["research"])
    def price_explanations(
        security_id: str,
        body: PriceExplanationRequest,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return move_intelligence.explain_range(
            db,
            move_intelligence.ExplanationRequest(
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
            ),
        )

    return router


__all__ = ["PriceExplanationRequest", "build_price_explanations_router"]
