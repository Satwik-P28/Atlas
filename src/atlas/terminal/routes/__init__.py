"""Coherent endpoint groups extracted from the terminal API module.

Each router is built by a factory that receives the request-scoped database dependency, so
the shared configuration (CORS, body limits, exception handlers, static mounting) stays in
``atlas.terminal.api`` and the routers own only their routes.
"""

from .market import (
    IndicatorRequest,
    MarketReplayRequest,
    MarketRequest,
    build_market_router,
)

__all__ = [
    "IndicatorRequest",
    "MarketReplayRequest",
    "MarketRequest",
    "build_market_router",
]
