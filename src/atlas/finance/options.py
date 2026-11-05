"""Black-Scholes-Merton European option math.

The implementation is intentionally a single declared model, not a claim of executable
market pricing. Rates and dividend yields are continuously compounded; volatility is
annualized; time is in years. Greeks are reported in their conventional raw units:
vega per 1.00 change in volatility, theta per year, rho per 1.00 change in the rate.
"""

from __future__ import annotations

import math
from typing import Any

from ..core.errors import ValidationError

OPTION_SCHEMA = "atlas.finance.black_scholes_merton.v1"


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be numeric", value=value) from exc
    if not math.isfinite(number):
        raise ValidationError(f"{field} must be finite", value=value)
    return number


def _cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _validate(
    spot: float, strike: float, time: float, rate: float, volatility: float,
    dividend_yield: float, kind: str,
) -> tuple[float, float, float, float, float, float, str]:
    spot = _finite(spot, "spot")
    strike = _finite(strike, "strike")
    time = _finite(time, "time")
    rate = _finite(rate, "rate")
    volatility = _finite(volatility, "volatility")
    dividend_yield = _finite(dividend_yield, "dividend_yield")
    if spot <= 0 or strike <= 0:
        raise ValidationError("spot and strike must be positive", spot=spot, strike=strike)
    if time < 0:
        raise ValidationError("time to expiry cannot be negative", time=time)
    if volatility < 0:
        raise ValidationError("volatility cannot be negative", volatility=volatility)
    if kind not in {"call", "put"}:
        raise ValidationError("option kind must be call or put", kind=kind)
    return spot, strike, time, rate, volatility, dividend_yield, kind


def bsm_price(
    spot: float, strike: float, time: float, rate: float, volatility: float,
    dividend_yield: float = 0.0, kind: str = "call",
) -> float:
    """Theoretical European option value."""
    spot, strike, time, rate, volatility, dividend_yield, kind = _validate(
        spot, strike, time, rate, volatility, dividend_yield, kind
    )
    if time == 0:
        return max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    if volatility == 0:
        forward = spot * math.exp((rate - dividend_yield) * time)
        value = (forward - strike) * math.exp(-rate * time)
        return max(value, 0.0)
    sqrt_t = math.sqrt(time)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility ** 2) * time) / (
        volatility * sqrt_t
    )
    d2 = d1 - volatility * sqrt_t
    if kind == "call":
        return spot * math.exp(-dividend_yield * time) * _cdf(d1) - strike * math.exp(
            -rate * time
        ) * _cdf(d2)
    return strike * math.exp(-rate * time) * _cdf(-d2) - spot * math.exp(
        -dividend_yield * time
    ) * _cdf(-d1)


def bsm_greeks(
    spot: float, strike: float, time: float, rate: float, volatility: float,
    dividend_yield: float = 0.0, kind: str = "call",
) -> dict[str, float]:
    """Analytical Greeks for the same declared BSM model."""
    spot, strike, time, rate, volatility, dividend_yield, kind = _validate(
        spot, strike, time, rate, volatility, dividend_yield, kind
    )
    if time == 0 or volatility == 0:
        # The delta is the limiting intrinsic slope; gamma/vega are undefined at the
        # kink in the payoff, so this release reports zero for those diagnostics rather
        # than presenting a numerically arbitrary spike.
        delta = (1.0 if spot > strike else 0.0) if kind == "call" else (
            -1.0 if spot < strike else 0.0
        )
        return {
            "price": bsm_price(spot, strike, time, rate, volatility, dividend_yield, kind),
            "delta": delta, "gamma": 0.0, "vega": 0.0,
            "theta": 0.0, "rho": 0.0,
            "note": "expiry or zero-volatility limit; gamma/vega are not differentiable",
        }
    sqrt_t = math.sqrt(time)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility ** 2) * time) / (
        volatility * sqrt_t
    )
    d2 = d1 - volatility * sqrt_t
    discount_q = math.exp(-dividend_yield * time)
    discount_r = math.exp(-rate * time)
    gamma = discount_q * _pdf(d1) / (spot * volatility * sqrt_t)
    vega = spot * discount_q * _pdf(d1) * sqrt_t
    if kind == "call":
        price = bsm_price(spot, strike, time, rate, volatility, dividend_yield, kind)
        delta = discount_q * _cdf(d1)
        theta = (
            -spot * discount_q * _pdf(d1) * volatility / (2 * sqrt_t)
            - rate * strike * discount_r * _cdf(d2)
            + dividend_yield * spot * discount_q * _cdf(d1)
        )
        rho = strike * time * discount_r * _cdf(d2)
    else:
        price = bsm_price(spot, strike, time, rate, volatility, dividend_yield, kind)
        delta = -discount_q * _cdf(-d1)
        theta = (
            -spot * discount_q * _pdf(d1) * volatility / (2 * sqrt_t)
            + rate * strike * discount_r * _cdf(-d2)
            - dividend_yield * spot * discount_q * _cdf(-d1)
        )
        rho = -strike * time * discount_r * _cdf(-d2)
    return {
        "price": price, "delta": delta, "gamma": gamma, "vega": vega,
        "theta": theta, "rho": rho,
    }


def implied_volatility(
    price: float, spot: float, strike: float, time: float, rate: float,
    dividend_yield: float = 0.0, kind: str = "call", *, tolerance: float = 1e-10,
) -> float:
    """Invert a BSM price by bounded bisection and reject arbitrage-inconsistent input."""
    price = _finite(price, "price")
    spot = _finite(spot, "spot")
    strike = _finite(strike, "strike")
    time = _finite(time, "time")
    rate = _finite(rate, "rate")
    dividend_yield = _finite(dividend_yield, "dividend_yield")
    if spot <= 0 or strike <= 0:
        raise ValidationError("spot and strike must be positive", spot=spot, strike=strike)
    if time < 0:
        raise ValidationError("time to expiry cannot be negative", time=time)
    if kind not in {"call", "put"}:
        raise ValidationError("option kind must be call or put", kind=kind)
    if price < 0:
        raise ValidationError("option price cannot be negative", price=price)
    if time <= 0:
        intrinsic = max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
        if abs(price - intrinsic) <= tolerance:
            return 0.0
        raise ValidationError("expired option price does not equal intrinsic value",
                              price=price, intrinsic=intrinsic)
    lower_bound = max(
        (spot * math.exp(-dividend_yield * time)
         - strike * math.exp(-rate * time)) if kind == "call" else
        (strike * math.exp(-rate * time)
         - spot * math.exp(-dividend_yield * time)), 0.0
    )
    upper_bound = spot * math.exp(-dividend_yield * time) if kind == "call" else (
        strike * math.exp(-rate * time)
    )
    if price < lower_bound - tolerance or price > upper_bound + tolerance:
        raise ValidationError("price violates no-arbitrage bounds for the declared model",
                              price=price, lower_bound=lower_bound, upper_bound=upper_bound)
    low, high = 1e-8, 5.0
    for _ in range(160):
        middle = (low + high) / 2
        value = bsm_price(spot, strike, time, rate, middle, dividend_yield, kind)
        if abs(value - price) < tolerance:
            return middle
        if value < price:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def option_parity_residual(
    call: float, put: float, spot: float, strike: float, time: float,
    rate: float, dividend_yield: float = 0.0,
) -> float:
    """C - P - S e^{-qT} + K e^{-rT}; zero under the declared model."""
    return call - put - spot * math.exp(-dividend_yield * time) + strike * math.exp(
        -rate * time
    )


__all__ = [
    "OPTION_SCHEMA", "bsm_greeks", "bsm_price", "implied_volatility",
    "option_parity_residual",
]
