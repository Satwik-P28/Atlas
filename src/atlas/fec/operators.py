"""Registered, versioned mathematical operators.

Every operator declares its financial type rule and a pure implementation. Values are
``Decimal`` scalars or tuples of ``Decimal`` values for series. No operator executes user
code. Adding an operator requires a new registry entry and tests, which is the extension
point for future vectorised or GPU backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable, Sequence

from .types import (
    FinType, SCALAR, TypeMismatch, add_types, common_numeric, div_types, mul_types,
)

OPERATOR_VERSION = "atlas.fec.operators.v1"
DECIMAL_PRECISION = 28


def _dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a finite number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("non-finite numeric result")
    return result


def _series(value: Any) -> tuple[Decimal, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(_dec(item) for item in value)
    raise ValueError("expected a series")


def _is_series(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _elementwise(left: Any, right: Any, fn: Callable[[Decimal, Decimal], Decimal]) -> Any:
    if _is_series(left) or _is_series(right):
        left_values = _series(left) if _is_series(left) else None
        right_values = _series(right) if _is_series(right) else None
        length = len(left_values) if left_values is not None else len(right_values)  # type: ignore[arg-type]
        if left_values is not None and len(left_values) != length:
            raise ValueError("series lengths differ")
        if right_values is not None and len(right_values) != length:
            raise ValueError("series lengths differ")
        return tuple(
            fn(
                left_values[i] if left_values is not None else _dec(left),
                right_values[i] if right_values is not None else _dec(right),
            )
            for i in range(length)
        )
    return fn(_dec(left), _dec(right))


def _series_type(base: FinType, temporal: str | None = None) -> FinType:
    return FinType("series", base.currency, base.kind, temporal if temporal is not None else base.temporal)


def _infer_unary(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    return types[0]


def _infer_same(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    return add_types(types[0], types[1])


def _infer_mul(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    return mul_types(types[0], types[1])


def _infer_div(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    return div_types(types[0], types[1])


def _infer_growth(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    if types[0].kind != "series":
        raise TypeMismatch("growth requires a series", code="unit_mismatch")
    return FinType("series", types[0].currency, "ratio", "forecast")


def _infer_forecast(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    base = types[0]
    return FinType("series", base.currency, base.kind, "forecast")


def _infer_npv(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    if types[0].kind != "series":
        raise TypeMismatch("npv requires a series", code="unit_mismatch")
    if types[1].kind not in {"rate", "ratio", "scalar"}:
        raise TypeMismatch("discount rate must be a Rate", code="unit_mismatch")
    return FinType(types[0].element or "money", types[0].currency)


def _infer_discount(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    if types[0].kind == "series":
        raise TypeMismatch("discount operates on a single cash flow", code="unit_mismatch")
    if types[1].kind not in {"rate", "ratio", "scalar"}:
        raise TypeMismatch("discount rate must be a Rate", code="unit_mismatch")
    return types[0]


def _infer_delta(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    if types[1].kind != "series":
        raise TypeMismatch("delta requires a series as its second argument", code="unit_mismatch")
    return types[1]


def _infer_terminal(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    if types[0].kind != "series":
        raise TypeMismatch("terminal value requires a forecast series", code="unit_mismatch")
    return FinType(types[0].element or "money", types[0].currency)


def _infer_sum(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    if types[0].kind != "series":
        raise TypeMismatch("sum requires a series", code="unit_mismatch")
    return FinType(types[0].element or "scalar", types[0].currency)


def _infer_scalar(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    return SCALAR


def _infer_minmax(types: Sequence[FinType], params: dict[str, Any]) -> FinType:
    return common_numeric(list(types))


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    key: str
    version: str
    arity: int
    infer: Callable[[Sequence[FinType], dict[str, Any]], FinType]
    execute: Callable[[Sequence[Any], dict[str, Any]], Any]
    formula: str
    description: str
    cacheable: bool = True


def _npv_execute(args: Sequence[Any], params: dict[str, Any]) -> Decimal:
    series = _series(args[0])
    rate = _dec(args[1])
    if rate <= -1:
        raise ValueError("discount rate must be greater than -100%")
    convention = str(params.get("convention", "end_year"))
    if convention not in {"end_year", "mid_year"}:
        raise ValueError(f"unknown discounting convention {convention!r}")
    total = Decimal(0)
    for index, cash in enumerate(series):
        exponent = Decimal(index + 1) + (Decimal("0.5") if convention == "mid_year" else Decimal(0))
        factor = (Decimal(1) + rate) ** exponent
        total += cash / factor
    return total


def _terminal_execute(args: Sequence[Any], params: dict[str, Any]) -> Decimal:
    series = _series(args[0])
    if not series:
        raise ValueError("terminal value requires at least one forecast cash flow")
    last = series[-1]
    method = str(params.get("method", "gordon_growth"))
    if method == "exit_multiple":
        multiple = _dec(params.get("multiple", 0))
        if multiple <= 0:
            raise ValueError("exit multiple must be positive")
        return last * multiple
    if method != "gordon_growth":
        raise ValueError(f"unknown terminal method {method!r}")
    rate = _dec(args[1])
    growth = _dec(args[2])
    if rate <= growth:
        raise ValueError("terminal growth must be below the discount rate")
    return last * (Decimal(1) + growth) / (rate - growth)


def _discount_execute(args: Sequence[Any], params: dict[str, Any]) -> Decimal:
    value, rate = _dec(args[0]), _dec(args[1])
    periods = _dec(params.get("periods", 1))
    if rate <= -1:
        raise ValueError("discount rate must be greater than -100%")
    convention = str(params.get("convention", "end_year"))
    exponent = periods + (Decimal("0.5") if convention == "mid_year" else Decimal(0))
    return value / ((Decimal(1) + rate) ** exponent)


def _forecast_execute(args: Sequence[Any], params: dict[str, Any]) -> tuple[Decimal, ...]:
    base = _dec(args[0])
    rates = args[1]
    periods = int(params.get("periods", len(rates) if _is_series(rates) else 0))
    if periods < 1 or periods > 200:
        raise ValueError("forecast periods must be between 1 and 200")
    if _is_series(rates):
        rate_values = _series(rates)
        if len(rate_values) != periods:
            raise ValueError("growth series length must equal forecast periods")
    else:
        rate_values = tuple(_dec(rates) for _ in range(periods))
    values = []
    level = base
    for rate in rate_values:
        if rate <= -1:
            raise ValueError("growth rate must be greater than -100%")
        level *= (Decimal(1) + rate)
        values.append(level)
    return tuple(values)


def _growth_execute(args: Sequence[Any], params: dict[str, Any]) -> tuple[Decimal, ...]:
    series = _series(args[0])
    result = [Decimal(0)]
    for index in range(1, len(series)):
        previous = series[index - 1]
        result.append((series[index] / previous - 1) if previous != 0 else Decimal(0))
    return tuple(result)


def _diff_execute(args: Sequence[Any], params: dict[str, Any]) -> tuple[Decimal, ...]:
    series = _series(args[0])
    return tuple([Decimal(0)] + [series[i] - series[i - 1] for i in range(1, len(series))])


def _safe_div(left: Any, right: Any) -> Any:
    if _is_series(left) or _is_series(right):
        left_values = _series(left) if _is_series(left) else None
        right_values = _series(right) if _is_series(right) else None
        length = len(left_values) if left_values is not None else len(right_values)  # type: ignore[arg-type]
        result = []
        for index in range(length):
            a = left_values[index] if left_values is not None else _dec(left)
            b = right_values[index] if right_values is not None else _dec(right)
            if b == 0:
                raise ValueError("division by zero")
            result.append(a / b)
        return tuple(result)
    a, b = _dec(left), _dec(right)
    if b == 0:
        raise ValueError("division by zero")
    return a / b


def _mean_execute(args: Sequence[Any], params: dict[str, Any]) -> Decimal:
    series = _series(args[0])
    if not series:
        raise ValueError("mean of an empty series")
    return sum(series, Decimal(0)) / Decimal(len(series))


REGISTRY: dict[str, OperatorSpec] = {}


def register(spec: OperatorSpec) -> None:
    REGISTRY[spec.key] = spec


register(OperatorSpec("add", OPERATOR_VERSION, 2, _infer_same, lambda a, p: _elementwise(a[0], a[1], lambda x, y: x + y),
                      "a + b", "Add compatible quantities"))
register(OperatorSpec("sub", OPERATOR_VERSION, 2, _infer_same, lambda a, p: _elementwise(a[0], a[1], lambda x, y: x - y),
                      "a - b", "Subtract compatible quantities"))
register(OperatorSpec("mul", OPERATOR_VERSION, 2, _infer_mul, lambda a, p: _elementwise(a[0], a[1], lambda x, y: x * y),
                      "a × b", "Multiply prices by shares, quantities by rates, or scale series"))
register(OperatorSpec("div", OPERATOR_VERSION, 2, _infer_div, lambda a, p: _safe_div(a[0], a[1]),
                      "a ÷ b", "Divide with explicit unit and zero checks"))
register(OperatorSpec("neg", OPERATOR_VERSION, 1, _infer_unary, lambda a, p: _elementwise(Decimal(0), a[0], lambda x, y: x - y),
                      "-a", "Negate a quantity"))
register(OperatorSpec("abs", OPERATOR_VERSION, 1, _infer_unary, lambda a, p: tuple(abs(x) for x in _series(a[0])) if _is_series(a[0]) else abs(_dec(a[0])),
                      "|a|", "Absolute value"))
register(OperatorSpec("pow", OPERATOR_VERSION, 2, _infer_scalar, lambda a, p: _dec(a[0]) ** _dec(a[1]),
                      "a ^ b", "Scalar power"))
register(OperatorSpec("min", OPERATOR_VERSION, 2, _infer_minmax, lambda a, p: min(_dec(a[0]), _dec(a[1])),
                      "min(a,b)", "Minimum"))
register(OperatorSpec("max", OPERATOR_VERSION, 2, _infer_minmax, lambda a, p: max(_dec(a[0]), _dec(a[1])),
                      "max(a,b)", "Maximum"))
register(OperatorSpec("growth", OPERATOR_VERSION, 1, _infer_growth, _growth_execute,
                      "(s[t]/s[t-1])-1", "Period-over-period growth"))
register(OperatorSpec("diff", OPERATOR_VERSION, 1, lambda t, p: t[0], _diff_execute,
                      "s[t]-s[t-1]", "First difference of a series"))

def _delta_execute(args: Sequence[Any], params: dict[str, Any]) -> tuple[Decimal, ...]:
    base = _dec(args[0])
    series = _series(args[1])
    if not series:
        return tuple()
    return tuple([series[0] - base] + [series[i] - series[i - 1] for i in range(1, len(series))])


register(OperatorSpec("delta", OPERATOR_VERSION, 2, _infer_delta, _delta_execute,
                      "s[0]-base, s[t]-s[t-1]", "Change versus a base value"))
register(OperatorSpec("forecast_series", OPERATOR_VERSION, 2, _infer_forecast, _forecast_execute,
                      "base·Π(1+g)", "Compound a base quantity over forecast periods"))
register(OperatorSpec("npv", OPERATOR_VERSION, 2, _infer_npv, _npv_execute,
                      "Σ cf/(1+r)^t", "Present value of a cash-flow series"))
register(OperatorSpec("terminal_value", OPERATOR_VERSION, 3, _infer_terminal, _terminal_execute,
                      "FCF·(1+g)/(r-g)", "Gordon growth or exit-multiple terminal value"))
register(OperatorSpec("discount", OPERATOR_VERSION, 2, _infer_discount, _discount_execute,
                      "v/(1+r)^t", "Discount a single cash flow"))
register(OperatorSpec("sum", OPERATOR_VERSION, 1, _infer_sum,
                      lambda a, p: sum(_series(a[0]), Decimal(0)),
                      "Σs", "Sum a series"))
register(OperatorSpec("mean", OPERATOR_VERSION, 1, lambda t, p: FinType("ratio"), _mean_execute,
                      "Σs/n", "Arithmetic mean of a series"))


def operator_versions() -> dict[str, str]:
    return {key: spec.version for key, spec in sorted(REGISTRY.items())}
