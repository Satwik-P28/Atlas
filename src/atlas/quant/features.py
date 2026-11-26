"""Point-in-time feature engine for Quant Lab.

Features are computed from raw observations whose *session date* is at or before the
requested information cutoff. Atlas never treats an observation downloaded later as
having been available earlier: the result publishes both the session dates used and the
provider source ids, and the historical-cutoff tests assert that later bars cannot enter
a rolling window.

Only price/volume transformations are implemented in this first vertical slice. The
feature contract is intentionally extensible, but unsupported kinds fail instead of
silently substituting a different calculation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..core.units import canonical_decimal
from ..market.bars import Bar, BarStore
from ..storage.db import Database

FEATURE_SCHEMA = "atlas.feature.v1"
FEATURE_ENGINE_VERSION = "atlas.feature.engine.v1"
SUPPORTED_KINDS = ("price", "return", "sma", "momentum", "volatility", "volume_zscore")
MAX_WINDOW = 500


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("feature input is not numeric", value=value) from exc
    if not number.is_finite():
        raise ValidationError("feature input is not finite", value=value)
    return number


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _sample_stdev(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    average = _mean(values)
    variance = sum((value - average) ** 2 for value in values) / Decimal(len(values) - 1)
    return variance.sqrt()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(specs: list[dict[str, Any]], security_id: str) -> str:
    payload = {"schema": FEATURE_SCHEMA, "engine": FEATURE_ENGINE_VERSION,
               "security_id": security_id, "features": specs}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def normalise_feature(spec: Any, index: int = 0) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValidationError("feature must be an object", index=index)
    name = str(spec.get("name", "")).strip()
    if not name or len(name) > 64:
        raise ValidationError("feature name must be 1-64 characters", index=index)
    kind = str(spec.get("kind", "")).strip()
    if kind not in SUPPORTED_KINDS:
        raise ValidationError("unsupported feature kind", kind=kind, supported=list(SUPPORTED_KINDS))
    window = spec.get("window", 1)
    try:
        window = int(window)
    except (TypeError, ValueError) as exc:
        raise ValidationError("feature window must be an integer", feature=name) from exc
    if window < 1 or window > MAX_WINDOW:
        raise ValidationError("feature window is out of range", feature=name, window=window,
                              min=1, max=MAX_WINDOW)
    if kind in {"return", "sma", "momentum", "volatility", "volume_zscore"} and window < 2:
        raise ValidationError("rolling features need a window of at least 2", feature=name)
    return {"name": name, "kind": kind, "window": window,
            "missing": str(spec.get("missing", "skip"))}


def normalise_features(specs: Any) -> list[dict[str, Any]]:
    if not isinstance(specs, list) or not specs:
        raise ValidationError("at least one feature is required")
    if len(specs) > 16:
        raise ValidationError("too many feature definitions", limit=16)
    result = [normalise_feature(spec, index) for index, spec in enumerate(specs)]
    names = [item["name"] for item in result]
    if len(names) != len(set(names)):
        raise ValidationError("feature names must be unique", names=names)
    return result


def _generation(db: Database, security_id: str, mic: str, cutoff: str) -> str:
    row = db.query_one(
        "SELECT COUNT(*) AS n, MAX(ingested_at) AS latest, MAX(revision_seq) AS revision "
        "FROM bar WHERE security_id = ? AND mic = ? AND interval = '1d' AND ts_utc <= ?",
        (security_id, mic.upper(), iso_date(cutoff) + "T23:59:59Z"),
    )
    payload = {
        "bars": int(row["n"] or 0) if row else 0,
        "ingested": row["latest"] if row else None,
        "revision": int(row["revision"] or 0) if row else 0,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:20]


@dataclass(slots=True)
class FeatureResult:
    security_id: str
    mic: str
    as_of: str
    start: str
    end: str
    feature_fingerprint: str
    points: list[dict[str, Any]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FEATURE_SCHEMA,
            "security_id": self.security_id,
            "mic": self.mic,
            "as_of": self.as_of,
            "start": self.start,
            "end": self.end,
            "fingerprint": self.feature_fingerprint,
            "points": self.points,
            "metadata": self.metadata,
        }


class FeatureEngine:
    """Compute deterministic rolling features from raw daily observations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def _bars(self, security_id: str, mic: str, cutoff: str) -> list[Bar]:
        bars = BarStore(self.db).query(security_id, mic, "1900-01-01", cutoff)
        # One row per session. BarStore returns the latest provider revision, but a
        # corrupt import could still contain an unexpected duplicate; choose the last
        # ordered observation explicitly instead of silently averaging it.
        by_date: dict[str, Bar] = {}
        for bar in bars:
            if bar.session_date <= iso_date(cutoff):
                by_date[bar.session_date] = bar
        return [by_date[key] for key in sorted(by_date)]

    @staticmethod
    def _value(
        feature: dict[str, Any],
        closes: list[Decimal],
        volumes: list[Decimal | None],
        returns: list[Decimal | None],
        index: int,
    ) -> Decimal | None:
        kind, window = feature["kind"], int(feature["window"])
        if kind == "price":
            return closes[index]
        if kind == "return":
            return returns[index]
        if index + 1 < window:
            return None
        if kind == "sma":
            return _mean(closes[index - window + 1:index + 1])
        if kind == "momentum":
            if index - window < 0:
                return None
            previous = closes[index - window]
            return None if previous == 0 else closes[index] / previous - 1
        if kind == "volatility":
            window_returns = [value for value in returns[index - window + 1:index + 1]
                              if value is not None]
            return _sample_stdev(window_returns)
        if kind == "volume_zscore":
            window_volumes = [value for value in volumes[index - window + 1:index + 1]
                              if value is not None]
            if len(window_volumes) < 2:
                return None
            average = _mean(window_volumes)
            deviation = _sample_stdev(window_volumes)
            if deviation is None or deviation == 0:
                return None
            return (window_volumes[-1] - average) / deviation
        raise ValidationError("unsupported feature kind", kind=kind)

    def compute(
        self,
        security_id: str,
        mic: str,
        specs: Iterable[dict[str, Any]],
        *,
        start: str | date | None = None,
        end: str | date | None = None,
        as_of: str | date | None = None,
        missing: str = "skip",
        persist: bool = False,
    ) -> FeatureResult:
        features = normalise_features(list(specs))
        if missing not in {"skip", "error"}:
            raise ValidationError("missing must be 'skip' or 'error'", missing=missing)
        cutoff_source = as_of or end or iso(utcnow())
        cutoff = iso_date(cutoff_source)
        start_date = iso_date(start) if start else None
        if end is not None and iso_date(end) > cutoff:
            raise ValidationError("feature end date is after the information cutoff",
                                  end=iso_date(end), as_of=cutoff)
        bars = self._bars(security_id, mic, cutoff)
        if not bars:
            raise ValidationError("no market observations at or before the cutoff",
                                  security_id=security_id, as_of=cutoff)
        key = fingerprint(features, security_id)
        generation = _generation(self.db, security_id, mic, cutoff)
        cached = None
        if persist:
            row = self.db.query_one(
                "SELECT generation, values_json, metadata_json FROM feature_snapshot "
                "WHERE feature_key = ? AND security_id = ? AND as_of = ?",
                (key, security_id, cutoff),
            )
            if row and row["generation"] == generation:
                cached = {
                    "points": json.loads(row["values_json"]),
                    "metadata": json.loads(row["metadata_json"]),
                }

        closes = [bar.close for bar in bars]
        volumes = [bar.volume for bar in bars]
        returns: list[Decimal | None] = [None]
        for index in range(1, len(closes)):
            previous = closes[index - 1]
            returns.append(None if previous == 0 else closes[index] / previous - 1)

        points: list[dict[str, Any]] = []
        if cached is None:
            max_window = max(feature["window"] for feature in features)
            for index, bar in enumerate(bars):
                if start_date and bar.session_date < start_date:
                    continue
                values: dict[str, Any] = {}
                missing_names: list[str] = []
                for feature in features:
                    value = self._value(feature, closes, volumes, returns, index)
                    if value is None:
                        missing_names.append(feature["name"])
                        if missing == "error":
                            raise ValidationError(
                                "feature has no value at session", feature=feature["name"],
                                session=bar.session_date, window=feature["window"],
                            )
                    else:
                        values[feature["name"]] = float(value)
                if not values:
                    continue
                points.append({
                    "date": bar.session_date,
                    "values": values,
                    "missing": missing_names,
                    "close": float(bar.close),
                    "available_at": f"{bar.session_date}T23:59:59Z",
                })
            metadata = {
                "engine": FEATURE_ENGINE_VERSION,
                "schema": FEATURE_SCHEMA,
                "sessions": len(bars),
                "first_session": bars[0].session_date,
                "last_session": bars[-1].session_date,
                "lookback_sessions": max_window,
                "missing_policy": missing,
                "source_ids": sorted({bar.source_id for bar in bars}),
                "cutoff_policy": "session_date <= information_cutoff; provider observations are not treated as historical vintages without archives",
                "generation": generation,
            }
            if persist:
                now = iso(utcnow())
                self.db.execute(
                    "INSERT INTO feature_snapshot (feature_key, security_id, as_of, generation, "
                    "values_json, metadata_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(feature_key, security_id, as_of) DO UPDATE SET "
                    "generation=excluded.generation, values_json=excluded.values_json, "
                    "metadata_json=excluded.metadata_json, updated_at=excluded.updated_at",
                    (key, security_id, cutoff, generation, canonical_json(points),
                     canonical_json(metadata), now, now),
                )
        else:
            metadata = cached["metadata"]
            points = cached["points"]
            metadata = {**metadata, "cache_hit": True}

        return FeatureResult(
            security_id=security_id,
            mic=mic.upper(),
            as_of=cutoff,
            start=start_date or bars[0].session_date,
            end=bars[-1].session_date,
            feature_fingerprint=key,
            points=points,
            metadata=metadata,
        )

    def values(self, result: FeatureResult) -> dict[str, dict[str, Any]]:
        """Index computed points by date for the simulator."""
        return {point["date"]: point for point in result.points}

    def get_series_catalog(self, security_id: str) -> dict[str, Any]:
        """Describe available raw data without inventing coverage."""
        bars = BarStore(self.db)
        coverage = bars.coverage(security_id, self._mic(security_id) or "XNYS")
        return coverage

    def _mic(self, security_id: str) -> str | None:
        row = self.db.query_one(
            "SELECT mic FROM listing WHERE security_id = ? ORDER BY is_primary DESC, valid_from LIMIT 1",
            (security_id,),
        )
        return row["mic"] if row else None


__all__ = [
    "FEATURE_ENGINE_VERSION",
    "FEATURE_SCHEMA",
    "FeatureEngine",
    "FeatureResult",
    "SUPPORTED_KINDS",
    "canonical_json",
    "fingerprint",
    "normalise_features",
]
