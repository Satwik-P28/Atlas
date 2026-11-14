"""Independent arithmetic verification for financial answers (version 9.6.3).

This module deliberately shares no code with the FEC runtime or the table-cell parser. It:

* parses raw filing text with its own regular expression and ``Fraction`` arithmetic,
* computes the same economic relationships exactly (no Decimal context, no rounding drift),
* exposes a fixed reference-vector set that is checked by the test suite.

The answer engine compares the FEC result with this module's result and refuses to answer when
they disagree. Agreement between two independent implementations is evidence; agreement of an
implementation with itself is not.
"""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

VERIFIER_VERSION = "9.6.4"

_RAW = re.compile(r"^\s*(?P<open>\()?\s*(?P<sign>[-+])?\s*\$?\s*(?P<body>\d[\d,]*(?:\.\d+)?)\s*%?\s*\)?\s*$")
_DASHES = {"", "-", "--", "—", "–", "n/a", "na", "nm"}


class VerificationError(ValueError):
    """Raised when raw evidence cannot be independently parsed."""


def parse_raw(text: str) -> Fraction:
    """Parse one printed value. Parentheses mean negative; a dash is never zero."""
    if text is None:
        raise VerificationError("missing cell text")
    cleaned = str(text).strip()
    if cleaned.lower() in _DASHES:
        raise VerificationError(f"not a numeric value: {text!r}")
    match = _RAW.match(cleaned)
    if not match:
        raise VerificationError(f"unparseable value: {text!r}")
    body = match.group("body").replace(",", "")
    value = Fraction(body)
    closed = cleaned.endswith(")")
    if bool(match.group("open")) != closed:
        raise VerificationError(f"unbalanced parentheses: {text!r}")
    negative = bool(match.group("open")) or match.group("sign") == "-"
    return -value if negative else value


def round_half_up(value: Fraction, places: int = 2) -> Decimal:
    """Banker's-rounding-free quantization applied identically to both implementations."""
    scale = 10 ** places
    scaled = value * scale
    numerator, denominator = scaled.numerator, scaled.denominator
    sign = -1 if numerator < 0 else 1
    numerator = abs(numerator)
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return Decimal(sign * quotient).scaleb(-places)


def as_fraction(value: Decimal) -> Fraction:
    return Fraction(value)


def lookup(raw: str) -> Fraction:
    return parse_raw(raw)


def percentage_change(current_raw: str, prior_raw: str) -> Fraction:
    current, prior = parse_raw(current_raw), parse_raw(prior_raw)
    if prior == 0:
        raise VerificationError("zero denominator")
    return (current - prior) / prior * 100


def ratio(numerator_raw: str, denominator_raw: str) -> Fraction:
    denominator = parse_raw(denominator_raw)
    if denominator == 0:
        raise VerificationError("zero denominator")
    return parse_raw(numerator_raw) / denominator


def margin(numerator_raw: str, revenue_raw: str) -> Fraction:
    return ratio(numerator_raw, revenue_raw) * 100


def total(raw_values: list[str]) -> Fraction:
    values = [parse_raw(raw) for raw in raw_values]
    if not values:
        raise VerificationError("no components")
    return sum(values, Fraction(0))


# Hand-computed vectors: (expression, inputs, expected). The suite asserts each one without
# calling the FEC runtime.
REFERENCE_VECTORS = [
    ("lookup", ["1,234"], "1234"),
    ("lookup", ["(234)"], "-234"),
    ("lookup", ["-50"], "-50"),
    ("lookup", ["12.5%"], "12.5"),
    ("percentage_change", ["1,234", "1,100"], "12.1818181818"),
    ("percentage_change", ["100", "100"], "0"),
    ("ratio", ["2,500", "1,234"], "2.0259319287"),
    ("margin", ["1,000", "1,234"], "81.0372771475"),
    ("total", ["1,100", "900"], "2000"),
]

# Deliberate refusals, also checked without production code.
REFUSAL_VECTORS = [
    ("lookup", ["-"]),
    ("lookup", [""]),
    ("lookup", ["1,2x4"]),
    ("percentage_change", ["100", "0"]),
    ("ratio", ["1", "0"]),
    ("margin", ["1", "0"]),
]


def evaluate(operator: str, raw_values: list[str]) -> Fraction:
    if operator == "lookup":
        return lookup(raw_values[0])
    if operator == "percentage_change":
        return percentage_change(raw_values[0], raw_values[1])
    if operator == "ratio":
        return ratio(raw_values[0], raw_values[1])
    if operator == "margin":
        return margin(raw_values[0], raw_values[1])
    if operator == "total":
        return total(raw_values)
    raise VerificationError(f"unsupported operator: {operator}")


__all__ = [
    "VERIFIER_VERSION", "VerificationError", "parse_raw", "round_half_up", "evaluate",
    "REFERENCE_VECTORS", "REFUSAL_VECTORS",
]
