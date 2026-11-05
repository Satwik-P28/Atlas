"""Dated government yield curves and a scoped fixed-coupon bond laboratory.

Conventions are explicit and deliberately narrow:

* The source is the U.S. Treasury Daily Treasury Par Yield Curve.
* Tenors up to one year are treated as zero-coupon annual rates.
* Coupon tenors of two years and longer are bootstrapped as semiannual par bonds.
* Zero rates are continuously compounded and interpolated linearly between nodes.
  Extrapolation is flat rather than an invented curve shape.
* Bond schedules are unadjusted calendar dates, semiannual, ACT/ACT accrued interest.
  Business-day adjustment, call features, sinking funds, taxes and credit spreads are
  outside this first release.

The par-to-zero conversion is the important distinction: par yields are not silently
used as spot rates. For coupon tenors the discount factor is solved from the par-bond
identity and the prior curve nodes.
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

from ..core.errors import ValidationError

CURVE_SCHEMA = "atlas.finance.yield_curve.v1"
TENOR_MONTHS = {
    "1 Mo": 1, "2 Mo": 2, "3 Mo": 3, "4 Mo": 4, "6 Mo": 6, "1 Yr": 12,
    "2 Yr": 24, "3 Yr": 36, "5 Yr": 60, "7 Yr": 84, "10 Yr": 120,
    "20 Yr": 240, "30 Yr": 360,
}
TENOR_LABELS = tuple(TENOR_MONTHS)


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be numeric", value=value) from exc
    if not math.isfinite(number):
        raise ValidationError(f"{field} must be finite", value=value)
    return number


def add_months(value: date, months: int) -> date:
    """Calendar month arithmetic without silently rounding to a business day."""
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    # Clamp the day to the target month's last day; this is a calendar convention,
    # not a business-day adjustment.
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    last = (following - timedelta(days=1)).day
    return date(year, month, min(value.day, last))


def _tenor_years(months: int) -> float:
    return months / 12.0


@dataclass(frozen=True, slots=True)
class CurveNode:
    tenor: str
    months: int
    par_yield: float
    zero_rate: float
    discount_factor: float

    @property
    def years(self) -> float:
        return _tenor_years(self.months)


@dataclass(frozen=True, slots=True)
class YieldCurve:
    observation_date: str
    source_name: str
    source_url: str
    retrieved_at: str
    source_sha256: str
    currency: str
    nodes: tuple[CurveNode, ...]
    interpolation: str = "linear_zero_flat_extrapolation"
    compounding: str = "continuous"
    day_count: str = "ACT/365"
    bootstrap: str = "semiannual_par_bootstrap"

    def _zero(self, years: float) -> float:
        if years <= 0:
            return self.nodes[0].zero_rate
        points = [(node.years, node.zero_rate) for node in self.nodes]
        if years <= points[0][0]:
            return points[0][1]
        for (left_t, left_z), (right_t, right_z) in zip(points, points[1:]):
            if years <= right_t:
                weight = (years - left_t) / (right_t - left_t)
                return left_z + weight * (right_z - left_z)
        return points[-1][1]

    def zero_rate(self, years: float) -> float:
        years = _finite(years, "years")
        if years < 0:
            raise ValidationError("curve time cannot be negative", years=years)
        return self._zero(years)

    def discount_factor(self, years: float) -> float:
        years = _finite(years, "years")
        if years < 0:
            raise ValidationError("curve time cannot be negative", years=years)
        return math.exp(-self.zero_rate(years) * years)

    def forward_rate(self, start: float, end: float) -> float:
        start, end = _finite(start, "start"), _finite(end, "end")
        if start < 0 or end <= start:
            raise ValidationError("forward interval must satisfy 0 <= start < end",
                                  start=start, end=end)
        return (self.zero_rate(end) * end - self.zero_rate(start) * start) / (end - start)

    def shifted(self, bps: float) -> "YieldCurve":
        bps = _finite(bps, "bps")
        return YieldCurve(
            observation_date=self.observation_date,
            source_name=self.source_name,
            source_url=self.source_url,
            retrieved_at=self.retrieved_at,
            source_sha256=self.source_sha256,
            currency=self.currency,
            nodes=tuple(
                CurveNode(node.tenor, node.months, node.par_yield,
                          node.zero_rate + bps / 10_000.0,
                          node.discount_factor * math.exp(-bps / 10_000.0 * node.years))
                for node in self.nodes
            ),
            interpolation=self.interpolation,
            compounding=self.compounding,
            day_count=self.day_count,
            bootstrap=self.bootstrap,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CURVE_SCHEMA,
            "observation_date": self.observation_date,
            "source": {
                "name": self.source_name,
                "url": self.source_url,
                "retrieved_at": self.retrieved_at,
                "sha256": self.source_sha256,
                "rights": "U.S. federal government public data",
            },
            "currency": self.currency,
            "conventions": {
                "compounding": self.compounding,
                "day_count": self.day_count,
                "interpolation": self.interpolation,
                "bootstrap": self.bootstrap,
                "business_day_adjustment": "none",
                "par_yields_are_not_spot_rates": True,
            },
            "nodes": [
                {
                    "tenor": node.tenor,
                    "months": node.months,
                    "years": round(node.years, 8),
                    "par_yield": node.par_yield,
                    "zero_rate": node.zero_rate,
                    "discount_factor": node.discount_factor,
                }
                for node in self.nodes
            ],
            "forwards": [
                {
                    "start_years": round(left.years, 8),
                    "end_years": round(right.years, 8),
                    "rate": self.forward_rate(left.years, right.years),
                }
                for left, right in zip(self.nodes, self.nodes[1:])
            ],
            "limitations": [
                "Treasury par yields are converted with a scoped semiannual bootstrap; they are not used directly as zero rates.",
                "Interpolation is linear in continuously compounded zero rates with flat extrapolation.",
                "No business-day calendar, holiday adjustment or settlement convention from a specific bond indenture is applied.",
            ],
        }


def bootstrap_par_curve(
    observation_date: str,
    par_yields: dict[str, float],
    *,
    source_name: str = "U.S. Department of the Treasury",
    source_url: str = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
    retrieved_at: str = "",
    source_sha256: str = "",
    currency: str = "USD",
) -> YieldCurve:
    """Bootstrap zero rates and discount factors from dated par yields.

    For tenors above one year, the par-bond equation is solved while the prior coupon
    discount factors are interpolated from already bootstrapped nodes. The small fixed
    point is deterministic and bounded; no external solver is required.
    """
    if not isinstance(par_yields, dict) or not par_yields:
        raise ValidationError("par yield curve requires at least one tenor")
    ordered = []
    for label in TENOR_LABELS:
        if label in par_yields and par_yields[label] not in (None, ""):
            rate = _finite(par_yields[label], f"par yield {label}") / 100.0
            if rate <= -1:
                raise ValidationError("par yield must be greater than -100%", tenor=label)
            ordered.append((label, TENOR_MONTHS[label], rate))
    if not ordered:
        raise ValidationError("par yield curve has no recognised tenors")
    # Keep the curve monotone in maturity. Out-of-order input is a caller error.
    if [months for _, months, _ in ordered] != sorted(months for _, months, _ in ordered):
        raise ValidationError("par yield tenors are not ordered")

    nodes: list[CurveNode] = []
    for label, months, par in ordered:
        years = _tenor_years(months)
        if months <= 12:
            # Short Treasury bill tenors are treated as zero-coupon annual rates.
            df = 1.0 / (1.0 + par * years)
            zero = -math.log(df) / years if years else par
        else:
            frequency = 2
            coupon = par / frequency
            # Coupon dates are every 0.5 year from issue to maturity. The first
            # outstanding coupon date is 0.5 year after issue; the final date includes
            # principal. Prior nodes are known; the maturity node is solved below.
            coupon_times = [i / frequency for i in range(1, int(round(years * frequency)))]
            prior_nodes = list(nodes)
            target_df = math.exp(-par * years)

            def interpolate_zero(t: float) -> float:
                points = [(node.years, node.zero_rate) for node in prior_nodes]
                points.append((years, -math.log(target_df) / years))
                points.sort()
                if t <= points[0][0]:
                    return points[0][1]
                for (t0, z0), (t1, z1) in zip(points, points[1:]):
                    if t <= t1:
                        return z0 + (t - t0) / (t1 - t0) * (z1 - z0)
                return points[-1][1]

            for _ in range(60):
                prior_pv = sum(coupon * math.exp(-interpolate_zero(t) * t)
                               for t in coupon_times if t < years - 1e-12)
                denominator = 1.0 + coupon
                target_df = (1.0 - prior_pv) / denominator
                if target_df <= 0:
                    raise ValidationError("par bootstrap produced a non-positive discount factor",
                                          tenor=label, par_yield=par)
            zero = -math.log(target_df) / years
            df = target_df
        nodes.append(CurveNode(label, months, par, zero, df))

    return YieldCurve(
        observation_date=observation_date,
        source_name=source_name,
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_sha256=source_sha256,
        currency=currency,
        nodes=tuple(nodes),
    )


def load_treasury_csv(
    path: str | Path,
    *,
    observation_date: str,
    source_url: str = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "daily-treasury-rates.csv/2024/all?type=daily_treasury_yield_curve"
        "&field_tdr_date_value=2024&page&_format=csv"
    ),
) -> YieldCurve:
    """Read one dated row from an exact U.S. Treasury yield CSV."""
    file = Path(path)
    raw = file.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    target = datetime.strptime(observation_date, "%Y-%m-%d").date()
    with file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                row_date = datetime.strptime(row["Date"], "%m/%d/%Y").date()
            except (KeyError, ValueError):
                continue
            if row_date == target:
                rates = {label: float(row[label]) for label in TENOR_LABELS if row.get(label)}
                return bootstrap_par_curve(
                    observation_date, rates,
                    source_url=source_url,
                    retrieved_at=datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                    source_sha256=digest,
                )
    raise ValidationError("date is not present in the Treasury yield file",
                          observation_date=observation_date, path=str(file))


def _validate_bond(
    face: float, coupon_rate: float, years: float, frequency: int, ytm: float,
) -> tuple[float, float, float, int, float]:
    face = _finite(face, "face")
    coupon_rate = _finite(coupon_rate, "coupon_rate")
    years = _finite(years, "years")
    ytm = _finite(ytm, "ytm")
    if face <= 0:
        raise ValidationError("face must be positive", face=face)
    if coupon_rate < 0 or coupon_rate > 1:
        raise ValidationError("coupon rate must be between 0 and 1", coupon_rate=coupon_rate)
    if years <= 0 or years > 50:
        raise ValidationError("bond maturity must be between 0 and 50 years", years=years)
    if frequency not in (1, 2, 4, 12):
        raise ValidationError("coupon frequency must be 1, 2, 4 or 12", frequency=frequency)
    if ytm <= -1:
        raise ValidationError("yield must be greater than -100%", ytm=ytm)
    return face, coupon_rate, years, frequency, ytm


def price_from_yield(
    face: float, coupon_rate: float, years: float, ytm: float, frequency: int = 2,
) -> float:
    """Dirty price from a nominal annual yield with periodic compounding."""
    face, coupon_rate, years, frequency, ytm = _validate_bond(
        face, coupon_rate, years, frequency, ytm
    )
    periods = max(1, int(round(years * frequency)))
    coupon = face * coupon_rate / frequency
    rate = ytm / frequency
    pv = 0.0
    for period in range(1, periods + 1):
        pv += coupon / (1 + rate) ** period
    pv += face / (1 + rate) ** periods
    return pv


def yield_from_price(
    price: float, face: float, coupon_rate: float, years: float, frequency: int = 2,
) -> float:
    """Solve the nominal annual yield; the price is dirty price."""
    price = _finite(price, "price")
    if price <= 0:
        raise ValidationError("price must be positive", price=price)
    low, high = -0.9999, 5.0
    def objective(rate: float) -> float:
        return price_from_yield(face, coupon_rate, years, rate, frequency) - price
    f_low, f_high = objective(low), objective(high)
    if f_low * f_high > 0:
        raise ValidationError("price cannot be inverted within the supported yield range",
                              price=price, lower=f_low, upper=f_high)
    for _ in range(120):
        middle = (low + high) / 2
        value = objective(middle)
        if abs(value) < 1e-12:
            return middle
        if f_low * value <= 0:
            high = middle
        else:
            low, f_low = middle, value
    return (low + high) / 2


@dataclass(frozen=True, slots=True)
class CashFlow:
    date: str
    year_fraction: float
    coupon: float
    principal: float
    discount_factor: float
    present_value: float


@dataclass(frozen=True, slots=True)
class BondAnalytics:
    settlement_date: str
    maturity_date: str
    face: float
    coupon_rate: float
    frequency: int
    accrued_interest: float
    clean_price: float
    dirty_price: float
    yield_to_maturity: float
    macaulay_duration: float
    modified_duration: float
    convexity: float
    dv01: float
    cash_flows: tuple[CashFlow, ...]
    curve: YieldCurve
    accrued_days: int
    coupon_period_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "settlement_date": self.settlement_date,
            "maturity_date": self.maturity_date,
            "face": self.face,
            "coupon_rate": self.coupon_rate,
            "frequency": self.frequency,
            "accrued_interest": self.accrued_interest,
            "accrued_days": self.accrued_days,
            "coupon_period_days": self.coupon_period_days,
            "clean_price": self.clean_price,
            "dirty_price": self.dirty_price,
            "yield_to_maturity": self.yield_to_maturity,
            "macaulay_duration": self.macaulay_duration,
            "modified_duration": self.modified_duration,
            "convexity": self.convexity,
            "dv01": self.dv01,
            "discount_curve": self.curve.to_dict(),
            "cash_flows": [
                {
                    "date": flow.date, "year_fraction": flow.year_fraction,
                    "coupon": flow.coupon, "principal": flow.principal,
                    "discount_factor": flow.discount_factor,
                    "present_value": flow.present_value,
                }
                for flow in self.cash_flows
            ],
            "conventions": {
                "day_count": "ACT/ACT accrued",
                "schedule": "unadjusted calendar dates",
                "curve_discounting": "continuous zero curve",
                "yield_compounding": f"nominal annual, {self.frequency} coupons per year",
            },
            "limitations": [
                "No business-day adjustment, ex-coupon convention, call/put feature, tax or credit spread.",
                "DV01 uses the dated curve and a one-basis-point parallel shift; it is not a full revaluation of an executable quote.",
            ],
        }


def _coupon_dates(maturity: date, settlement: date, frequency: int) -> list[date]:
    months = 12 // frequency
    dates: list[date] = []
    current = maturity
    while current > settlement:
        dates.append(current)
        current = add_months(current, -months)
    dates.sort()
    return dates


def _previous_coupon(maturity: date, settlement: date, frequency: int) -> tuple[date, date]:
    dates = _coupon_dates(maturity, settlement, frequency)
    if not dates:
        raise ValidationError("bond has no coupon date after settlement",
                              settlement=settlement.isoformat())
    following = dates[0]
    previous = add_months(following, -12 // frequency)
    return previous, following


def analyse_bond(
    curve: YieldCurve,
    *,
    settlement_date: str,
    maturity_date: str,
    coupon_rate: float,
    face: float = 100.0,
    frequency: int = 2,
    shock_bps: tuple[float, ...] = (-100, -50, -25, 0, 25, 50, 100),
) -> BondAnalytics:
    settlement = date.fromisoformat(settlement_date)
    maturity = date.fromisoformat(maturity_date)
    if maturity <= settlement:
        raise ValidationError("maturity must be after settlement")
    face, coupon_rate, years, frequency, _ = _validate_bond(
        face, coupon_rate, (maturity - settlement).days / 365.0, frequency, 0.0
    )
    if abs(years) > 50:
        raise ValidationError("bond maturity exceeds 50 years", years=years)
    coupon_dates = _coupon_dates(maturity, settlement, frequency)
    if not coupon_dates:
        raise ValidationError("bond has no cash flows after settlement")
    flows: list[CashFlow] = []
    total_pv = 0.0
    coupon = face * coupon_rate / frequency
    for index, flow_date in enumerate(coupon_dates):
        years_from_settlement = (flow_date - settlement).days / 365.0
        df = curve.discount_factor(years_from_settlement)
        principal = face if index == len(coupon_dates) - 1 else 0.0
        pv = (coupon + principal) * df
        total_pv += pv
        flows.append(CashFlow(flow_date.isoformat(), years_from_settlement, coupon,
                              principal, df, pv))
    previous, following = _previous_coupon(maturity, settlement, frequency)
    accrued_days = max(0, (settlement - previous).days)
    period_days = max(1, (following - previous).days)
    accrued = coupon * accrued_days / period_days
    dirty = total_pv
    clean = dirty - accrued
    ytm = yield_from_price(dirty, face, coupon_rate, years, frequency)
    macaulay = sum(flow.year_fraction * flow.present_value for flow in flows) / dirty
    periodic_yield = ytm / frequency
    modified = macaulay / (1 + periodic_yield)
    convexity = sum(
        flow.year_fraction * (flow.year_fraction + 1.0 / frequency) * flow.present_value
        for flow in flows
    ) / (dirty * (1 + periodic_yield) ** 2)
    down = _dirty_from_curve(curve.shifted(-1), settlement, maturity, coupon, face, frequency)
    up = _dirty_from_curve(curve.shifted(1), settlement, maturity, coupon, face, frequency)
    # Loss-positive DV01: the price loss for a one-basis-point upward parallel shift.
    dv01 = (down - up) / 2.0

    return BondAnalytics(
        settlement_date=settlement.isoformat(),
        maturity_date=maturity.isoformat(),
        face=face,
        coupon_rate=coupon_rate,
        frequency=frequency,
        accrued_interest=accrued,
        clean_price=clean,
        dirty_price=dirty,
        yield_to_maturity=ytm,
        macaulay_duration=macaulay,
        modified_duration=modified,
        convexity=convexity,
        dv01=dv01,
        cash_flows=tuple(flows),
        curve=curve,
        accrued_days=accrued_days,
        coupon_period_days=period_days,
    )


def _dirty_from_curve(
    curve: YieldCurve, settlement: date, maturity: date, coupon: float,
    face: float, frequency: int,
) -> float:
    coupon_dates = _coupon_dates(maturity, settlement, frequency)
    total = 0.0
    for index, flow_date in enumerate(coupon_dates):
        years = (flow_date - settlement).days / 365.0
        principal = face if index == len(coupon_dates) - 1 else 0.0
        total += (coupon + principal) * curve.discount_factor(years)
    return total


def shock_bond(
    analytics: BondAnalytics,
    *,
    shift_bps: float,
) -> dict[str, Any]:
    shifted = analytics.curve.shifted(shift_bps)
    maturity = date.fromisoformat(analytics.maturity_date)
    settlement = date.fromisoformat(analytics.settlement_date)
    dirty = _dirty_from_curve(
        shifted, settlement, maturity,
        analytics.face * analytics.coupon_rate / analytics.frequency,
        analytics.face, analytics.frequency,
    )
    previous, following = _previous_coupon(maturity, settlement, analytics.frequency)
    accrued = (analytics.face * analytics.coupon_rate / analytics.frequency
               * max(0, (settlement - previous).days) / max(1, (following - previous).days))
    return {
        "shift_bps": shift_bps,
        "dirty_price": dirty,
        "clean_price": dirty - accrued,
        "pnl": dirty - analytics.dirty_price,
        "pnl_per_100_face": (dirty - analytics.dirty_price) / analytics.face * 100,
        "approximation": "full curve revaluation under a parallel zero-rate shift",
    }


def cash_flow_years(analytics: BondAnalytics) -> list[dict[str, float | str]]:
    return [
        {"date": flow.date, "years": flow.year_fraction,
         "coupon": flow.coupon, "principal": flow.principal,
         "present_value": flow.present_value}
        for flow in analytics.cash_flows
    ]


__all__ = [
    "BondAnalytics", "CURVE_SCHEMA", "CashFlow", "CurveNode", "TENOR_LABELS",
    "YieldCurve", "add_months", "analyse_bond", "bootstrap_par_curve",
    "cash_flow_years", "load_treasury_csv", "price_from_yield", "shock_bond",
    "yield_from_price",
]
