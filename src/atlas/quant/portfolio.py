"""Independent portfolio ledger used by the chronological simulator.

The ledger is deliberately small and explicit. It never derives cash from a performance
series: every cash movement is a posted trade, commission, dividend or corporate action.
That makes the final reconciliation check meaningful rather than circular.

Only long positions are supported in this vertical slice. A split changes quantity and
per-share basis without changing total basis or cash; a dividend is credited once on its
ex-date from the raw share count. Strategies should use raw prices, so adjusted-price
dividends are not silently counted a second time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR, localcontext
from typing import Any

from ..core.errors import ValidationError
from ..core.units import canonical_decimal

PRECISION = 28


def D(value: Any) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return canonical_decimal(value)


@dataclass(slots=True)
class Position:
    security_id: str
    quantity: Decimal = Decimal(0)
    cost_basis: Decimal = Decimal(0)
    last_price: Decimal = Decimal(0)

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.last_price

    @property
    def average_cost(self) -> Decimal:
        return self.cost_basis / self.quantity if self.quantity else Decimal(0)


@dataclass(slots=True)
class Portfolio:
    security_id: str
    initial_cash: Decimal
    cash: Decimal = field(init=False)
    position: Position = field(init=False)
    realized_pnl: Decimal = field(default=Decimal(0), init=False)
    dividend_income: Decimal = field(default=Decimal(0), init=False)
    commissions: Decimal = field(default=Decimal(0), init=False)
    slippage_cost: Decimal = field(default=Decimal(0), init=False)
    ledger: list[dict[str, Any]] = field(default_factory=list, init=False)
    last_price: Decimal = field(default=Decimal(0), init=False)

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValidationError("initial cash must be positive", initial_cash=str(self.initial_cash))
        self.cash = self.initial_cash
        self.position = Position(self.security_id)

    # ------------------------------------------------------------------ trading
    def buy(self, date: str, quantity: Decimal, *, reference_price: Decimal, fill_price: Decimal,
            commission: Decimal) -> dict[str, Any]:
        if quantity <= 0:
            raise ValidationError("buy quantity must be positive", quantity=str(quantity))
        gross = quantity * fill_price
        total = gross + commission
        if total > self.cash:
            raise ValidationError("insufficient cash for buy", required=str(total), cash=str(self.cash))
        slip = abs(fill_price - reference_price) * quantity
        self.cash -= total
        self.position.quantity += quantity
        self.position.cost_basis += total
        self.position.last_price = fill_price
        self.commissions += commission
        self.slippage_cost += slip
        entry = {
            "date": date, "side": "buy", "quantity": money(quantity),
            "reference_price": money(reference_price), "fill_price": money(fill_price),
            "gross": money(gross), "commission": money(commission), "slippage": money(slip),
            "cash_flow": money(-total), "realized_pnl": "0", "cash_after": money(self.cash),
            "position_after": money(self.position.quantity),
        }
        self.ledger.append(entry)
        return entry

    def sell(self, date: str, quantity: Decimal, *, reference_price: Decimal, fill_price: Decimal,
             commission: Decimal) -> dict[str, Any]:
        if quantity <= 0:
            raise ValidationError("sell quantity must be positive", quantity=str(quantity))
        if quantity > self.position.quantity:
            raise ValidationError("insufficient position for sell", quantity=str(quantity),
                                  position=str(self.position.quantity))
        gross = quantity * fill_price
        proceeds = gross - commission
        basis_removed = self.position.cost_basis * quantity / self.position.quantity
        realized = proceeds - basis_removed
        slip = abs(fill_price - reference_price) * quantity
        self.cash += proceeds
        self.position.quantity -= quantity
        self.position.cost_basis -= basis_removed
        if self.position.quantity == 0:
            self.position.cost_basis = Decimal(0)
        self.realized_pnl += realized
        self.commissions += commission
        self.slippage_cost += slip
        entry = {
            "date": date, "side": "sell", "quantity": money(quantity),
            "reference_price": money(reference_price), "fill_price": money(fill_price),
            "gross": money(gross), "commission": money(commission), "slippage": money(slip),
            "cash_flow": money(proceeds), "realized_pnl": money(realized),
            "cash_after": money(self.cash), "position_after": money(self.position.quantity),
        }
        self.ledger.append(entry)
        return entry

    # --------------------------------------------------------- corporate actions
    def apply_split(self, date: str, factor: Decimal) -> dict[str, Any]:
        if factor <= 0:
            raise ValidationError("split factor must be positive", factor=str(factor))
        before = self.position.quantity
        if before == 0:
            return {"date": date, "type": "split", "factor": money(factor),
                    "quantity_before": "0", "quantity_after": "0", "cash_flow": "0"}
        self.position.quantity *= factor
        self.ledger.append({
            "date": date, "type": "split", "factor": money(factor),
            "quantity_before": money(before), "quantity_after": money(self.position.quantity),
            "cash_flow": "0", "note": "quantity adjusted; total cost basis unchanged",
        })
        return self.ledger[-1]

    def apply_dividend(self, date: str, per_share: Decimal) -> dict[str, Any]:
        if per_share < 0:
            raise ValidationError("dividend cannot be negative", amount=str(per_share))
        amount = self.position.quantity * per_share
        self.cash += amount
        self.dividend_income += amount
        entry = {
            "date": date, "type": "dividend", "per_share": money(per_share),
            "quantity": money(self.position.quantity), "cash_flow": money(amount),
            "cash_after": money(self.cash),
        }
        if amount:
            self.ledger.append(entry)
        return entry

    # --------------------------------------------------------------- valuation
    def mark(self, price: Decimal) -> None:
        if price <= 0:
            raise ValidationError("mark price must be positive", price=str(price))
        self.last_price = price
        self.position.last_price = price

    @property
    def equity(self) -> Decimal:
        return self.cash + self.position.market_value

    def snapshot(self, date: str) -> dict[str, Any]:
        return {
            "date": date,
            "equity": money(self.equity),
            "cash": money(self.cash),
            "position_value": money(self.position.market_value),
            "position_quantity": money(self.position.quantity),
            "price": money(self.position.last_price),
            "realized_pnl": money(self.realized_pnl),
            "unrealized_pnl": money(self.position.market_value - self.position.cost_basis),
        }

    def reconciliation(self) -> dict[str, Any]:
        trade_flows = sum((D(item["cash_flow"]) for item in self.ledger
                           if item.get("type") not in {"split", "dividend"} and "side" in item),
                          Decimal(0))
        dividend_flows = sum((D(item["cash_flow"]) for item in self.ledger
                              if item.get("type") == "dividend"), Decimal(0))
        expected_cash = self.initial_cash + trade_flows + dividend_flows
        difference = self.cash - expected_cash
        return {
            "beginning_cash": money(self.initial_cash),
            "trade_cash_flows": money(trade_flows),
            "dividend_income": money(dividend_flows),
            "commissions": money(self.commissions),
            "slippage_cost": money(self.slippage_cost),
            "ending_cash": money(self.cash),
            "cash_reconciled": money(difference),
            "cash_identity": "beginning_cash + trade_cash_flows + dividend_income = ending_cash",
            "holdings_quantity": money(self.position.quantity),
            "holdings_market_value": money(self.position.market_value),
            "total_portfolio_value": money(self.equity),
            "realized_pnl": money(self.realized_pnl),
            "unrealized_pnl": money(self.position.market_value - self.position.cost_basis),
            "reconciled": difference == 0,
            "note": "trade_cash_flows and commissions are already netted; commissions are shown separately for analysis.",
        }


def max_affordable_quantity(cash: Decimal, fill_price: Decimal, commission_bps: Decimal) -> Decimal:
    """Whole-share quantity whose gross plus commission fits available cash."""
    if fill_price <= 0:
        return Decimal(0)
    rate = commission_bps / Decimal(10_000)
    quantity = (cash / (fill_price * (Decimal(1) + rate))).to_integral_value(rounding=ROUND_FLOOR)
    while quantity > 0 and quantity * fill_price * (Decimal(1) + rate) > cash:
        quantity -= 1
    return quantity


__all__ = ["Portfolio", "Position", "max_affordable_quantity", "money"]
