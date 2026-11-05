"""Persistence and orchestration for Phase 5 institutional calculations."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from ..core.errors import UnknownEntity, ValidationError
from ..core.temporal import iso, utcnow
from ..finance.curves import (
    YieldCurve,
    analyse_bond,
    load_treasury_csv,
    shock_bond,
)
from ..finance.options import bsm_greeks, bsm_price, implied_volatility, option_parity_residual
from ..research.objects import ResearchObjectStore
from ..storage.db import Database
from .risk import optimize, portfolio_analysis
from .universe import UNIVERSE_ID, aligned_panel
from .validation import walk_forward

RUN_SCHEMA = "atlas.institutional.run.v1"
DEFAULT_CURVE_DATE = "2024-06-28"
CURVE_FILE = Path(__file__).resolve().parents[3] / "fixtures" / "phase5" / "treasury-par-yields-2024.csv"


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def curve(date: str = DEFAULT_CURVE_DATE) -> YieldCurve:
    if not CURVE_FILE.exists():
        raise ValidationError("Treasury curve fixture is missing", path=str(CURVE_FILE))
    return load_treasury_csv(CURVE_FILE, observation_date=date)


def curve_dates() -> list[str]:
    if not CURVE_FILE.exists():
        return []
    import csv

    from datetime import datetime

    with CURVE_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        dates = []
        for row in csv.DictReader(handle):
            if not row.get("Date"):
                continue
            dates.append(datetime.strptime(row["Date"], "%m/%d/%Y").date().isoformat())
        return dates


def bond(
    *, settlement_date: str, maturity_date: str, coupon_rate: float,
    curve_date: str = DEFAULT_CURVE_DATE, face: float = 100.0, frequency: int = 2,
    shocks: tuple[float, ...] = (-100, -50, -25, 0, 25, 50, 100),
) -> dict[str, Any]:
    analytics = analyse_bond(
        curve(curve_date), settlement_date=settlement_date, maturity_date=maturity_date,
        coupon_rate=coupon_rate, face=face, frequency=frequency,
    )
    payload = analytics.to_dict()
    payload["shocks"] = [shock_bond(analytics, shift_bps=value) for value in shocks]
    payload["dv01_identity"] = {
        "modified_duration_times_dirty_times_1bp": analytics.modified_duration
        * analytics.dirty_price
        * 0.0001,
        "curve_revaluation_dv01": analytics.dv01,
        "absolute_difference": abs(
            analytics.modified_duration * analytics.dirty_price * 0.0001 - analytics.dv01
        ),
    }
    payload["data_class"] = "official_public_treasury_curve"
    payload["instrument_class"] = "hypothetical_fixed_coupon_government_bond"
    payload["limitations"] = [
        "The curve is a dated public Treasury par-yield snapshot; the bond terms are hypothetical.",
        "No business-day convention, call feature, credit spread, tax or liquidity adjustment is modeled.",
        "Yield and duration are model outputs under the stated conventions, not executable quotes.",
    ]
    payload["fingerprint"] = _hash(payload)
    return payload


def option(
    *, spot: float, strike: float, time: float, rate: float, volatility: float,
    dividend_yield: float = 0.0,
) -> dict[str, Any]:
    call = bsm_price(spot, strike, time, rate, volatility, dividend_yield, "call")
    put = bsm_price(spot, strike, time, rate, volatility, dividend_yield, "put")
    calendar = {
        "spot": spot, "strike": strike, "time": time, "rate": rate,
        "volatility": volatility, "dividend_yield": dividend_yield,
    }
    payload = {
        "schema": "atlas.finance.black_scholes_merton.v1",
        "data_class": "theoretical_model",
        "instrument": "European vanilla option",
        "inputs": calendar,
        "call": bsm_greeks(spot, strike, time, rate, volatility, dividend_yield, "call"),
        "put": bsm_greeks(spot, strike, time, rate, volatility, dividend_yield, "put"),
        "parity_residual": option_parity_residual(
            call, put, spot, strike, time, rate, dividend_yield
        ),
        "implied_volatility": {
            "call": implied_volatility(call, spot, strike, time, rate, dividend_yield, "call"),
            "put": implied_volatility(put, spot, strike, time, rate, dividend_yield, "put"),
        },
        "conventions": {
            "volatility": "annualized",
            "rate": "continuously compounded",
            "dividend_yield": "continuously compounded",
            "vega": "per 1.00 change in volatility",
            "theta": "per year",
            "rho": "per 1.00 change in rate",
        },
        "limitations": [
            "This is a theoretical BSM value, not an executable quote or a volatility-surface claim.",
            "Constant volatility, continuous trading, no transaction costs and European exercise are assumptions.",
        ],
    }
    payload["fingerprint"] = _hash(payload)
    return payload


class InstitutionalService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, kind: str, *, inputs: dict[str, Any], result: dict[str, Any],
             as_of: str | None = None, data_class: str | None = None) -> dict[str, Any]:
        run_id = f"IRUN-{uuid.uuid4().hex[:20]}"
        fingerprint = result.get("fingerprint") or result.get("result_fingerprint") or _hash(result)
        created = iso(utcnow())
        duration = float(result.get("duration_ms", 0.0) or 0.0)
        self.db.execute(
            "INSERT INTO institutional_run (run_id, kind, as_of, data_class, input_json, "
            "result_json, fingerprint, status, duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, kind, as_of or created[:10], data_class or result.get("data_class", "unknown"),
             json.dumps(inputs, sort_keys=True, default=str),
             json.dumps(result, sort_keys=True, default=str), fingerprint, "succeeded",
             duration, created),
        )
        result["run_id"] = run_id
        result["created_at"] = created
        return result

    def save_validation(self, result: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        run_id = f"IRUN-{uuid.uuid4().hex[:20]}"
        created = iso(utcnow())
        fingerprint = result["result_fingerprint"]
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO institutional_run (run_id, kind, as_of, data_class, input_json, "
                "result_json, fingerprint, status, duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, "walk_forward", created[:10], result.get("data_class", "synthetic_fixture"),
                 json.dumps(inputs, sort_keys=True, default=str),
                 json.dumps(result, sort_keys=True, default=str), fingerprint, "succeeded",
                 float(result.get("duration_ms", 0.0) or 0.0), created),
            )
            for attempt in result.get("attempts", []):
                attempt_id = f"IATT-{uuid.uuid4().hex[:20]}"
                self.db.execute(
                    "INSERT INTO validation_attempt (attempt_id, validation_run_id, fold, stage, "
                    "family, lookback, selected, metrics_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (attempt_id, run_id, attempt["fold"], attempt["stage"], attempt["family"],
                     attempt["lookback"], 1 if attempt.get("selected") else 0,
                     json.dumps(attempt.get("metrics", {}), sort_keys=True, default=str), created),
                )
        result["run_id"] = run_id
        result["created_at"] = created
        return result

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT run_id, kind, as_of, data_class, fingerprint, status, duration_ms, created_at "
            "FROM institutional_run ORDER BY created_at DESC, run_id LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        return [dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM institutional_run WHERE run_id = ?", (run_id,))
        if row is None:
            raise UnknownEntity("unknown institutional run", run_id=run_id)
        payload = json.loads(row["result_json"])
        payload["run_id"] = row["run_id"]
        payload["created_at"] = row["created_at"]
        payload["data_class"] = row["data_class"]
        return payload

    def validation_attempts(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT attempt_id, fold, stage, family, lookback, selected, metrics_json "
            "FROM validation_attempt WHERE validation_run_id = ? ORDER BY fold, stage, family, lookback",
            (run_id,),
        )
        return [{**dict(row), "metrics": json.loads(row["metrics_json"])} for row in rows]

    def application_document(
        self, *, kind: str, name: str, inputs: dict[str, Any], result: dict[str, Any],
        object_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a valid `atlas.research_object.v1` application for save/reopen."""
        views = ["inputs", "result", "provenance", "limitations"]
        return {
            "schema_version": "atlas.research_object.v1",
            "kind": "application",
            "name": name,
            "version": "1.0.0",
            "status": "validated",
            "description": f"Saved {kind} institutional research application.",
            "as_of": iso(utcnow()),
            "mode": "atlas_ingested",
            "evidence_ids": [],
            "source_ids": [],
            "object_ids": list(object_ids or []),
            "assumptions": [
                "The application is an immutable research record; reopening evaluates the stored inputs.",
            ],
            "limitations": list(result.get("limitations", [])),
            "spec": {
                "purpose": kind,
                "views": views,
                "application": {
                    "type": kind,
                    "inputs": inputs,
                    "result": result,
                    "data_class": result.get("data_class"),
                    "run_id": result.get("run_id"),
                },
            },
        }

    def save_application(self, document: dict[str, Any]) -> dict[str, Any]:
        return ResearchObjectStore(self.db).create(document)

    def catalog(self) -> dict[str, Any]:
        return {
            "schema": "atlas.institutional.catalog.v1",
            "universe": {
                "id": UNIVERSE_ID,
                "data_class": "synthetic_fixture",
                "note": "Three active synthetic securities; one documented delisted path.",
            },
            "curve": {
                "default_date": DEFAULT_CURVE_DATE,
                "source": "U.S. Department of the Treasury",
                "file": str(CURVE_FILE.relative_to(CURVE_FILE.parents[3])),
                "dates": curve_dates(),
                "conventions": ["continuous zero", "ACT/365", "semiannual par bootstrap",
                                 "linear zero interpolation"],
            },
            "options": {"model": "Black-Scholes-Merton", "exercise": "European",
                        "kinds": ["call", "put"]},
            "optimization": {
                "solver": "active-set KKT enumeration",
                "max_assets": 8,
                "supported": ["minimum variance", "target return", "long only",
                              "max position", "cash allocation", "diagonal shrinkage"],
                "unsupported": ["turnover", "sector caps", "transaction costs"],
            },
            "validation": {
                "methods": ["rolling walk-forward", "expanding walk-forward"],
                "partitions": ["train", "validation", "test"],
                "default_embargo": 5,
                "test_used_for_selection": False,
            },
            "warnings": [
                "The multi-asset fixture is synthetic, not market data.",
                "IBM is the only real security with bars in this local database.",
                "The Treasury curve is public-domain dated observations; bond terms are hypothetical.",
            ],
        }


__all__ = [
    "CURVE_FILE", "DEFAULT_CURVE_DATE", "InstitutionalService", "RUN_SCHEMA",
    "bond", "curve", "curve_dates", "option",
]
