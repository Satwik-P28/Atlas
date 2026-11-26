"""Typed financial primitives and their compatibility rules.

The type system is intentionally conservative. It rejects currency mixing, stock/flow
confusion and forecast/observation arithmetic unless the model makes the conversion
explicit. Financial semantics are enforced at compile time; runtime checks remain as a
second line of defence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

KINDS = {
    "money", "price", "shares", "rate", "ratio", "scalar", "series",
    "probability", "distribution", "forecast", "stock", "flow",
}
TEMPORALS = {"flow", "stock", "forecast", "observation", "instant"}
CURRENCY = re.compile(r"^[A-Z]{3}$")
_TYPE = re.compile(r"^([A-Za-z]+)(?:\[([^\]]+)\])?$")


class TypeMismatch(ValueError):
    def __init__(self, message: str, *, code: str = "type_mismatch", **context: Any):
        super().__init__(message)
        self.code = code
        self.context = context


@dataclass(frozen=True, slots=True)
class FinType:
    kind: str
    currency: str | None = None
    element: str | None = None
    temporal: str | None = None
    convention: str | None = None
    horizon: int | None = None

    def label(self) -> str:
        if self.kind == "series":
            inner = self.element or "scalar"
            suffix = f"[{self.currency}]" if self.currency else ""
            temporal = f"<{self.temporal}>" if self.temporal else ""
            return f"Series[{inner}{suffix}]{temporal}"
        suffix = f"[{self.currency}]" if self.currency else ""
        if self.kind == "rate" and self.convention:
            suffix = f"[{self.convention}]"
        if self.kind == "forecast" and self.horizon:
            suffix = f"[{self.horizon}]"
        return f"{self.kind.title()}{suffix}"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in (
            ("kind", self.kind), ("currency", self.currency), ("element", self.element),
            ("temporal", self.temporal), ("convention", self.convention),
            ("horizon", self.horizon),
        ) if value is not None}

    @classmethod
    def from_dict(cls, value: dict[str, Any] | str | "FinType") -> "FinType":
        if isinstance(value, FinType):
            return value
        if isinstance(value, str):
            return cls.parse(value)
        if not isinstance(value, dict):
            raise TypeMismatch("type must be a string or object", code="invalid_type")
        return cls(**{key: value[key] for key in (
            "kind", "currency", "element", "temporal", "convention", "horizon"
        ) if key in value})

    @classmethod
    def parse(cls, text: str) -> "FinType":
        if not isinstance(text, str):
            raise TypeMismatch("type must be a string", code="invalid_type")
        match = _TYPE.match(text.strip())
        if not match:
            raise TypeMismatch(f"cannot parse financial type {text!r}", code="invalid_type", type=text)
        kind = match.group(1).lower()
        arg = match.group(2)
        if kind == "series":
            element = "scalar"
            currency = None
            temporal = None
            if arg:
                parts = [part.strip() for part in arg.split(",")]
                inner = cls.parse(parts[0])
                element = inner.kind
                currency = inner.currency
                temporal = inner.temporal
                for part in parts[1:]:
                    if part.lower() in TEMPORALS:
                        temporal = part.lower()
            return cls(kind="series", element=element, currency=currency, temporal=temporal)
        if kind == "forecast":
            return cls(kind="forecast", horizon=int(arg or 5), temporal="forecast")
        if kind == "rate":
            return cls(kind="rate", convention=arg or "annual")
        if kind in {"money", "price", "stock", "flow"}:
            currency = (arg or "USD").split("/")[0].strip().upper()
            if not CURRENCY.match(currency):
                raise TypeMismatch("currency must be a three-letter code", code="invalid_currency", currency=currency)
            temporal = "stock" if kind == "stock" else "flow" if kind == "flow" else None
            return cls(kind=kind, currency=currency, temporal=temporal)
        if kind in {"shares", "ratio", "scalar", "probability", "distribution"}:
            return cls(kind=kind)
        raise TypeMismatch(f"unknown financial type {kind!r}", code="invalid_type", type=text)

    def with_temporal(self, temporal: str | None) -> "FinType":
        return FinType(self.kind, self.currency, self.element, temporal, self.convention, self.horizon)


SCALAR = FinType("scalar")
USD = FinType("money", "USD")
SHARES = FinType("shares")
RATIO = FinType("ratio")


def _currency(type_: FinType) -> str | None:
    return type_.currency


def _assert_currencies(a: FinType, b: FinType) -> None:
    if a.currency and b.currency and a.currency != b.currency:
        raise TypeMismatch(
            f"cannot combine {a.currency} and {b.currency} without an explicit FX conversion",
            code="currency_mismatch", left=a.currency, right=b.currency,
            hint="insert a dated FX conversion node; Atlas does not invent an exchange rate",
        )


def _assert_temporal(a: FinType, b: FinType) -> None:
    if a.temporal and b.temporal and a.temporal != b.temporal:
        raise TypeMismatch(
            f"cannot combine {a.temporal} with {b.temporal}",
            code="temporal_mismatch", left=a.temporal, right=b.temporal,
            hint="forecasts, accounting flows and instantaneous stocks are not interchangeable",
        )


def _series(element: str, currency: str | None, temporal: str | None = None) -> FinType:
    return FinType("series", currency, element, temporal)


def add_types(a: FinType, b: FinType) -> FinType:
    _assert_currencies(a, b)
    _assert_temporal(a, b)
    if a.kind == "series" or b.kind == "series":
        left = a if a.kind == "series" else _series(a.kind, a.currency, a.temporal)
        right = b if b.kind == "series" else _series(b.kind, b.currency, b.temporal)
        if left.element != right.element:
            if "scalar" not in {left.element, right.element}:
                raise TypeMismatch("series elements are incompatible", code="unit_mismatch",
                                   left=left.element, right=right.element)
            element = right.element if left.element == "scalar" else left.element
        else:
            element = left.element
        return _series(element, left.currency or right.currency, left.temporal or right.temporal)
    if {a.kind, b.kind} == {"scalar"}:
        return a
    if a.kind == "scalar":
        return b
    if b.kind == "scalar":
        return a
    if a.kind != b.kind:
        raise TypeMismatch(f"cannot add {a.label()} and {b.label()}", code="unit_mismatch",
                           left=a.label(), right=b.label())
    if a.kind == "rate" and a.convention != b.convention:
        raise TypeMismatch("rate conventions differ", code="convention_mismatch",
                           left=a.convention, right=b.convention)
    return a


def mul_types(a: FinType, b: FinType) -> FinType:
    _assert_currencies(a, b)
    _assert_temporal(a, b)
    if a.kind == "series" or b.kind == "series":
        series = a if a.kind == "series" else b
        other = b if a.kind == "series" else a
        if other.kind not in {"scalar", "ratio", "rate"}:
            if series.element == "price" and other.kind == "shares":
                return _series("money", series.currency, series.temporal)
            raise TypeMismatch(f"cannot multiply {a.label()} by {b.label()}", code="unit_mismatch",
                               left=a.label(), right=b.label())
        element = series.element if other.kind in {"scalar", "ratio", "rate"} else other.kind
        return _series(element or "scalar", series.currency, series.temporal)
    if a.kind == "scalar":
        return b
    if b.kind == "scalar":
        return a
    kinds = {a.kind, b.kind}
    if kinds == {"price", "shares"}:
        return FinType("money", a.currency or b.currency)
    if a.kind == "money" and b.kind in {"ratio", "rate"}:
        return a
    if b.kind == "money" and a.kind in {"ratio", "rate"}:
        return b
    if a.kind == "price" and b.kind in {"ratio", "rate"}:
        return a
    if b.kind == "price" and a.kind in {"ratio", "rate"}:
        return b
    raise TypeMismatch(f"cannot multiply {a.label()} by {b.label()}", code="unit_mismatch",
                       left=a.label(), right=b.label())


def div_types(a: FinType, b: FinType) -> FinType:
    _assert_currencies(a, b)
    _assert_temporal(a, b)
    if a.kind == "series":
        if b.kind not in {"scalar", "ratio", "rate", "series"}:
            raise TypeMismatch("series can only be divided by a numeric quantity", code="unit_mismatch")
        return _series(a.element or "scalar", a.currency, a.temporal)
    if b.kind == "series":
        raise TypeMismatch("cannot divide by a series", code="unit_mismatch")
    if a.kind == b.kind and a.kind in {"money", "price", "shares", "scalar", "ratio", "rate"}:
        return FinType("ratio")
    if a.kind == "money" and b.kind == "shares":
        return FinType("price", a.currency)
    if a.kind == "money" and b.kind == "ratio":
        return a
    if a.kind == "price" and b.kind == "shares":
        return FinType("price", a.currency)
    if a.kind == "scalar" and b.kind in {"money", "price"}:
        return FinType("ratio")
    raise TypeMismatch(f"cannot divide {a.label()} by {b.label()}", code="unit_mismatch",
                       left=a.label(), right=b.label())


def common_numeric(types: list[FinType]) -> FinType:
    if not types:
        return SCALAR
    result = types[0]
    for item in types[1:]:
        result = add_types(result, item)
    return result
