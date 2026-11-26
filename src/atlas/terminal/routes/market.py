"""Market endpoints: overview, price series, observations and replay.

These routes were part of ``atlas.terminal.api``; they are extracted unchanged so the
module keeps one responsibility (application wiring) and this group owns another (market
presentation). The public contract is byte-identical: same paths, methods, operation ids,
tags, parameters, request bodies and response schemas, checked by
``tests/test_phase9_2_7_market_series.py::test_openapi_contract_is_unchanged``.

Every response comes from ``atlas.terminal.read_models``, which now reads the canonical
market-evidence contract, so no route decides which observation represents a price.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...storage.db import Database
from .. import read_models


class IndicatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    params: dict[str, Any] = Field(default_factory=dict)


class MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range: str = "1Y"
    start: str | None = None
    end: str | None = None
    view: Literal["raw", "split", "total_return"] = "split"
    indicators: list[IndicatorRequest] = Field(default_factory=list, max_length=6)
    as_of: str | None = None


class MarketReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: dict[str, Any]
    information_cutoff: str | None = None


def build_market_router(get_db: Callable[..., Any]) -> APIRouter:
    """Build the market router over the application's request-scoped database dependency."""
    router = APIRouter()

    @router.get("/api/markets/overview", tags=["market"])
    def markets(db: Database = Depends(get_db)) -> dict[str, Any]:
        return read_models.market_overview(db)

    @router.get("/api/securities/{security_id}/market", tags=["market"])
    def market_get(
        security_id: str,
        range: str = "1Y",
        start: str | None = None,
        end: str | None = None,
        view: Literal["raw", "split", "total_return"] = "split",
        as_of: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return read_models.market_series(
            db, security_id, range_key=range, start=start, end=end, view=view, as_of=as_of
        )

    @router.post("/api/securities/{security_id}/market", tags=["market"])
    def market_post(
        security_id: str, body: MarketRequest, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return read_models.market_series(
            db,
            security_id,
            range_key=body.range,
            start=body.start,
            end=body.end,
            view=body.view,
            indicators=[item.model_dump() for item in body.indicators],
            as_of=body.as_of,
        )

    @router.get("/api/securities/{security_id}/actions", tags=["market"])
    def security_actions(
        security_id: str, as_of: str | None = None, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        from ...market.actions import ActionStore

        return {
            "security_id": security_id,
            "items": [a.to_dict() for a in ActionStore(db).list(security_id, knowledge_as_of=as_of)],
            "as_of": as_of,
            "schema": read_models.TERMINAL_SCHEMA,
        }

    @router.get("/api/securities/{security_id}/observations", tags=["market"])
    def security_observations(
        security_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        from ...research.observations import observations_for_security

        items = observations_for_security(db, security_id, limit=limit)
        return {
            "schema": "atlas.market_observation.list.v1",
            "security_id": security_id,
            "count": len(items),
            "items": items,
        }

    @router.post("/api/market/replay", tags=["market"])
    def market_replay(
        body: MarketReplayRequest, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        from ...research.prices import price_for_pin

        return price_for_pin(db, body.pin, information_cutoff=body.information_cutoff)

    @router.get("/api/market/observations/{observation_id}/replay", tags=["market"])
    def market_observation_replay(
        observation_id: str,
        as_of: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        from ...research.observations import observation_detail
        from ...research.prices import price_for_pin

        detail = observation_detail(db, observation_id)
        if detail is None:
            raise HTTPException(
                status_code=404, detail=f"no stored market observation {observation_id}"
            )
        return price_for_pin(db, detail["pin"], information_cutoff=as_of)

    @router.get("/api/market/observations/{observation_id}", tags=["market"])
    def market_observation(
        observation_id: str, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        from ...research.observations import observation_detail

        detail = observation_detail(db, observation_id)
        if detail is None:
            raise HTTPException(
                status_code=404,
                detail=f"no stored market observation {observation_id}",
            )
        return detail

    return router
