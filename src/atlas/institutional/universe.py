"""Synthetic multi-asset fixture for institutional portfolio research.

This is deliberately a *synthetic* market. It exists to exercise alignment, delisting,
covariance, optimization and walk-forward mechanics when only one real price series is
available. It is never mixed with the IBM vendor observations and every response carries
``data_class = synthetic_fixture``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

UNIVERSE_SCHEMA = "atlas.institutional.universe.v1"
UNIVERSE_ID = "SYN-UNIVERSE-PHASE5"


def _lcg(seed: int):
    state = seed & 0xFFFFFFFF

    def draw() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 0x100000000

    def normal() -> float:
        # Box-Muller with a floor avoids log(0).
        u1 = max(draw(), 1e-12)
        u2 = draw()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    return normal


@dataclass(frozen=True, slots=True)
class Instrument:
    security_id: str
    ticker: str
    name: str
    sector: str
    currency: str
    membership_start: str
    membership_end: str | None
    listing_status: str
    delisted: bool
    source_id: str = "phase5-synthetic-fixture"
    data_class: str = "synthetic_fixture"


INSTRUMENTS = (
    Instrument("SYN-ALPHA", "ALFA", "Synthetic Alpha", "Technology", "USD",
               "2021-01-04", None, "active", False),
    Instrument("SYN-BETA", "BETA", "Synthetic Beta", "Industrials", "USD",
               "2021-01-04", None, "active", False),
    Instrument("SYN-GAMMA", "GAMA", "Synthetic Gamma", "Defensives", "USD",
               "2021-06-01", None, "active", False),
    Instrument("SYN-DELTA", "DELT", "Synthetic Delta (delisted)", "Energy", "USD",
               "2021-01-04", "2023-12-29", "delisted", True),
)

_PARAMS = {
    "SYN-ALPHA": {"seed": 101, "drift": 0.105, "vol": 0.25, "beta": 1.20, "start": 100.0},
    "SYN-BETA": {"seed": 202, "drift": 0.070, "vol": 0.19, "beta": 0.85, "start": 80.0},
    "SYN-GAMMA": {"seed": 303, "drift": 0.055, "vol": 0.14, "beta": 0.55, "start": 65.0},
    "SYN-DELTA": {"seed": 404, "drift": -0.045, "vol": 0.31, "beta": 1.05, "start": 45.0},
}


def _business_days(start: date, end: date) -> list[date]:
    result = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _correlated_normals(seed: int, count: int, beta: float) -> list[float]:
    normal = _lcg(seed)
    market = _lcg(99991)
    values = []
    idiosyncratic_weight = max(0.15, math.sqrt(max(0.01, 1.0 - min(beta, 0.95) ** 2)))
    for _ in range(count):
        values.append(beta * market() + idiosyncratic_weight * normal())
    return values


def build_panel() -> dict[str, Any]:
    """Build deterministic daily prices, including a genuine delisting cutoff."""
    dates = _business_days(date(2021, 1, 4), date(2024, 12, 31))
    series: dict[str, list[dict[str, Any]]] = {}
    for instrument in INSTRUMENTS:
        params = _PARAMS[instrument.security_id]
        shocks = _correlated_normals(params["seed"], len(dates), params["beta"])
        price = params["start"]
        prices = []
        for session, shock in zip(dates, shocks):
            if session.isoformat() < instrument.membership_start:
                continue
            if instrument.membership_end and session.isoformat() > instrument.membership_end:
                continue
            daily_drift = params["drift"] / 252.0
            daily_vol = params["vol"] / math.sqrt(252.0)
            price *= math.exp(daily_drift - 0.5 * daily_vol * daily_vol + daily_vol * shock)
            prices.append({"date": session.isoformat(), "close": round(price, 6)})
        series[instrument.security_id] = prices
    all_dates = sorted({point["date"] for points in series.values() for point in points})
    membership = {}
    for instrument in INSTRUMENTS:
        available = {point["date"] for point in series[instrument.security_id]}
        membership[instrument.security_id] = [
            {"date": day, "member": day in available, "reason": (
                "listed" if day in available
                else "before_listing" if day < instrument.membership_start
                else "after_delisting"
            )}
            for day in all_dates
        ]
    payload = {
        "schema": UNIVERSE_SCHEMA,
        "universe_id": UNIVERSE_ID,
        "name": "Phase 5 synthetic multi-asset fixture",
        "data_class": "synthetic_fixture",
        "provenance": {
            "source_id": "phase5-synthetic-fixture",
            "description": "Deterministic correlated geometric price paths generated for software validation.",
            "not_a_market_claim": True,
            "real_data_available": "IBM only, in the Phase 4 Quant Lab",
            "seed": "documented per instrument; use build_panel() in this exact release for reproduction",
        },
        "calendar": {
            "kind": "weekdays_only",
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
            "sessions": len(dates),
            "holidays_modeled": False,
        },
        "instruments": [asdict(instrument) for instrument in INSTRUMENTS],
        "series": series,
        "membership": membership,
        "survivorship": {
            "delisted_security_present": True,
            "broad_market_universe": False,
            "survivorship_bias_free": False,
            "note": ("One delisted path is present with an explicit end date, but four synthetic "
                     "names cannot represent a market universe or eliminate survivorship bias."),
        },
    }
    payload["content_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def aligned_panel(start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Return the panel restricted to dates with at least two live instruments."""
    panel = build_panel()
    instruments = {item["security_id"]: item for item in panel["instruments"]}
    dates = sorted({
        point["date"] for values in panel["series"].values() for point in values
        if (start is None or point["date"] >= start) and (end is None or point["date"] <= end)
    })
    rows = []
    for day in dates:
        row = {"date": day, "prices": {}}
        for security_id, values in panel["series"].items():
            match = next((point for point in values if point["date"] == day), None)
            if match:
                row["prices"][security_id] = match["close"]
        if len(row["prices"]) >= 2:
            rows.append(row)
    return {
        "schema": UNIVERSE_SCHEMA,
        "universe_id": UNIVERSE_ID,
        "data_class": "synthetic_fixture",
        "instruments": panel["instruments"],
        "dates": rows,
        "content_hash": panel["content_hash"],
        "calendar": panel["calendar"],
        "survivorship": panel["survivorship"],
        "provenance": panel["provenance"],
    }


def returns_matrix(
    panel: dict[str, Any] | None = None, *, start: str | None = None, end: str | None = None,
) -> dict[str, Any]:
    data = panel or aligned_panel(start=start, end=end)
    rows = data["dates"]
    # The risk/validation engine uses the active, continuously listed sleeve. The
    # delisted security remains visible in the universe and membership history but is
    # not silently forward-filled into a portfolio return matrix.
    securities = [item["security_id"] for item in data["instruments"]
                  if not item.get("delisted")]
    observations = []
    previous: dict[str, float] | None = None
    aligned_dates = []
    for row in rows:
        if previous is None:
            previous = dict(row["prices"])
            continue
        if all(security_id in row["prices"] and security_id in previous for security_id in securities):
            observation = [
                row["prices"][security_id] / previous[security_id] - 1.0
                for security_id in securities
            ]
            observations.append(observation)
            aligned_dates.append(row["date"])
        previous = {**previous, **row["prices"]}
    return {
        "securities": securities,
        "dates": aligned_dates,
        "returns": observations,
        "data_class": data["data_class"],
        "universe_id": data["universe_id"],
        "instruments": data["instruments"],
        "provenance": data["provenance"],
        "content_hash": data["content_hash"],
    }


__all__ = [
    "INSTRUMENTS", "Instrument", "UNIVERSE_ID", "UNIVERSE_SCHEMA", "aligned_panel",
    "build_panel", "returns_matrix",
]
