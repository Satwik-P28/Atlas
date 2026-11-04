"""Units, money and exact decimal arithmetic.

Financial values are never stored as binary floats. SQLite has no decimal type, so
values are persisted as canonical decimal *strings* (see :func:`canonical_decimal`)
and converted with :class:`decimal.Decimal` on read. This keeps 0.1 + 0.2 exact and
makes stored values byte-identical for identical economic quantities, which the
evidence dedup logic relies on.

Units are modelled explicitly because "USD", "shares", "USD/shares" and "pure" are
not interchangeable: adding an EPS figure to a revenue figure is a bug, not a
rounding difference.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from .errors import CurrencyMismatchError, UnitMismatchError, ValidationError

# Currencies Atlas understands as ISO-4217 alphabetic codes. Unknown codes are still
# accepted (vendors invent them) but must look like a code.
_KNOWN_CURRENCIES = frozenset(
    {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "HKD", "INR", "BRL", "MXN", "SEK", "NOK", "DKK", "SGD", "KRW", "TWD", "ZAR"}
)


class UnitKind(str, Enum):
    """Economic dimension of a measured quantity."""

    MONETARY = "monetary"
    SHARES = "shares"
    PER_SHARE = "per_share"
    PURE = "pure"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Unit:
    """A parsed unit such as ``USD``, ``shares``, ``USD/shares`` or ``pure``."""

    raw: str
    kind: UnitKind
    currency: str | None = None

    @property
    def key(self) -> str:
        """Stable storage key for this unit."""
        return self.raw

    def is_compatible_with(self, other: "Unit") -> bool:
        if self.kind != other.kind:
            return False
        if self.kind in (UnitKind.MONETARY, UnitKind.PER_SHARE):
            return self.currency == other.currency
        return True

    def require_compatible(self, other: "Unit") -> None:
        if self.is_compatible_with(other):
            return
        if self.kind == other.kind and self.currency != other.currency:
            raise CurrencyMismatchError(
                "cannot combine monetary values in different currencies",
                left=self.raw,
                right=other.raw,
            )
        raise UnitMismatchError(
            "cannot combine values with incompatible units", left=self.raw, right=other.raw
        )

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return self.raw


_PURE_UNITS = {
    "pure": UnitKind.PURE,
    "ratio": UnitKind.PURE,
    "number": UnitKind.PURE,
    "percent": UnitKind.PURE,
    "shares": UnitKind.SHARES,
    "share": UnitKind.SHARES,
    "share(s)": UnitKind.SHARES,
}


def parse_unit(raw: str | None) -> Unit:
    """Parse an XBRL/vendor unit string into a :class:`Unit`.

    XBRL uses ``USD``, ``shares``, ``USD/shares`` and ``pure``. Vendors occasionally
    report ``USD millions`` or ``usd``; both are accepted but the raw string is
    preserved so provenance stays exact and scaling is never implicit.
    """
    if raw is None:
        return Unit(raw="unknown", kind=UnitKind.UNKNOWN, currency=None)
    text = str(raw).strip()
    if not text:
        return Unit(raw="unknown", kind=UnitKind.UNKNOWN, currency=None)
    lowered = text.lower()

    if "/" in lowered:
        numerator, _, denominator = lowered.partition("/")
        numerator = numerator.strip().lstrip("$").strip()
        denominator = denominator.strip()
        if denominator.startswith("share") and numerator.isalpha() and len(numerator) == 3:
            return Unit(raw=text, kind=UnitKind.PER_SHARE, currency=numerator.upper())
        return Unit(raw=text, kind=UnitKind.UNKNOWN, currency=None)

    if lowered in _PURE_UNITS:
        return Unit(raw=text, kind=_PURE_UNITS[lowered], currency=None)

    # "USD", "$USD", "usd millions", "USD thousand"
    token = lowered.lstrip("$").split(" ")[0]
    if len(token) == 3 and token.isalpha():
        upper = token.upper()
        if upper in _KNOWN_CURRENCIES:
            return Unit(raw=text, kind=UnitKind.MONETARY, currency=upper)
        # Unknown but well-formed alphabetic currency code.
        return Unit(raw=text, kind=UnitKind.MONETARY, currency=upper)
    return Unit(raw=text, kind=UnitKind.UNKNOWN, currency=None)


def canonical_decimal(value: Decimal | int | str | float) -> str:
    """Canonical decimal string: no exponent, no redundant trailing zeros.

    ``Decimal("1000.00")`` -> ``"1000"``; ``Decimal("1E+3")`` -> ``"1000"``;
    ``Decimal("0.123456789")`` -> ``"0.123456789"``. Negative zero collapses to
    ``"0"`` so that ``-0.00`` and ``0`` dedupe as the same observation.
    """
    if isinstance(value, float):
        # Never let a binary float silently define a financial value.
        raise ValidationError("binary floats are not accepted for financial values", value=value)
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:  # pragma: no cover - defensive
        raise ValidationError("value is not a valid decimal", value=value) from exc
    if not dec.is_finite():
        raise ValidationError("value must be finite", value=value)
    if dec == 0:
        return "0"
    text = format(dec.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_decimal(value: str | int | Decimal) -> Decimal:
    """Parse a stored decimal string back to :class:`Decimal`."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise ValidationError("binary floats are not accepted for financial values", value=value)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("value is not a valid decimal", value=value) from exc
    if not dec.is_finite():
        raise ValidationError("value must be finite", value=value)
    return dec


@dataclass(frozen=True, slots=True)
class Money:
    """An amount with a currency, using exact decimal arithmetic."""

    amount: Decimal
    currency: str
    unit_raw: str | None = None

    def __post_init__(self) -> None:
        currency = str(self.currency).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("invalid ISO-4217 currency", currency=self.currency)
        object.__setattr__(self, "currency", currency)
        if isinstance(self.amount, float):
            raise ValidationError("binary floats are not accepted for financial values")
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", parse_decimal(self.amount))
        if not self.amount.is_finite():
            raise ValidationError("amount must be finite", amount=str(self.amount))

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                "cannot combine money in different currencies",
                left=self.currency,
                right=other.currency,
            )

    def add(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def scale(self, factor: Decimal | int | str) -> "Money":
        return Money(self.amount * parse_decimal(factor), self.currency)

    def negate(self) -> "Money":
        return Money(-self.amount, self.currency)

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"{canonical_decimal(self.amount)} {self.currency}"


@dataclass(frozen=True, slots=True)
class Quantity:
    """A measured quantity with an arbitrary parsed unit."""

    amount: Decimal
    unit: Unit

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise ValidationError("binary floats are not accepted for financial values")
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", parse_decimal(self.amount))

    def add(self, other: "Quantity") -> "Quantity":
        self.unit.require_compatible(other.unit)
        return Quantity(self.amount + other.amount, self.unit)

    def subtract(self, other: "Quantity") -> "Quantity":
        self.unit.require_compatible(other.unit)
        return Quantity(self.amount - other.amount, self.unit)

    def as_money(self) -> Money:
        if self.unit.kind is not UnitKind.MONETARY or not self.unit.currency:
            raise UnitMismatchError("quantity is not monetary", unit=self.unit.raw)
        return Money(self.amount, self.unit.currency, self.unit.raw)


def ensure_same_unit(left: Unit, right: Unit) -> None:
    """Raise unless two units are economically interchangeable."""
    left.require_compatible(right)
