"""Independent validation of Atlas calculations.

Each check recomputes a published value from its declared inputs using arithmetic written
in this module, not by calling the function under test. A check records expected, actual,
tolerance and the evidence ids involved, so a failure points at a number rather than a
stack trace. Tolerance is explicit: decimals are exact, adjusted prices allow one cent of
rounding, and ratios allow 1e-9.

This is deliberately small and auditable. It is not a second terminal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Sequence

from ..core.temporal import iso, parse_iso, utcnow
from ..market.actions import ActionStore
from ..terminal import read_models

EXACT = Decimal("0")
CENT = Decimal("0.011")
RATIO = Decimal("1e-9")


def _check(
    name: str,
    *,
    expected: Any,
    actual: Any,
    tolerance: Decimal,
    evidence_ids: Sequence[str] = (),
    note: str | None = None,
) -> dict[str, Any]:
    try:
        difference = abs(Decimal(str(expected)) - Decimal(str(actual)))
        passed = difference <= tolerance
    except Exception:  # noqa: BLE001 - a malformed value is a failed check
        difference = None
        passed = False
    return {
        "name": name,
        "expected": str(expected),
        "actual": str(actual),
        "difference": str(difference) if difference is not None else None,
        "tolerance": str(tolerance),
        "passed": passed,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
        "note": note,
    }


def validate_ratios(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    m = {
        key: value
        for key, value in metrics.items()
        if isinstance(value, dict) and value.get("value") is not None
    }

    def value(key: str) -> Decimal | None:
        return Decimal(str(m[key]["value"])) if key in m else None

    def evidence(*keys: str) -> list[str]:
        return [eid for key in keys for eid in m.get(key, {}).get("evidence_ids", [])]

    revenue = value("revenue")
    if revenue and revenue != 0:
        for key, numerator, label in (
            ("net_margin", "net_income", "net margin = net income / revenue"),
            ("operating_margin", "operating_income", "operating margin = operating income / revenue"),
            ("gross_margin", "gross_profit", "gross margin = gross profit / revenue"),
        ):
            top = value(numerator)
            if top is not None and key in m:
                checks.append(_check(label, expected=top / revenue, actual=m[key]["value"],
                                     tolerance=RATIO, evidence_ids=evidence(numerator, "revenue")))

    equity = value("equity")
    net_income = value("net_income")
    if equity and net_income is not None and "roe" in m:
        checks.append(_check("ROE = net income / equity", expected=net_income / equity,
                             actual=m["roe"]["value"], tolerance=RATIO,
                             evidence_ids=evidence("net_income", "equity")))

    debt_lt, debt_st = value("long_term_debt") or Decimal(0), value("short_term_debt") or Decimal(0)
    if "total_debt" in m and (debt_lt or debt_st):
        checks.append(_check("total debt = long-term + short-term", expected=debt_lt + debt_st,
                             actual=m["total_debt"]["value"], tolerance=EXACT,
                             evidence_ids=evidence("long_term_debt", "short_term_debt")))

    ocf, capex = value("operating_cash_flow"), value("capex")
    if ocf is not None and capex is not None and "free_cash_flow" in m:
        checks.append(_check("free cash flow = operating cash flow - |capex|",
                             expected=ocf - abs(capex), actual=m["free_cash_flow"]["value"],
                             tolerance=EXACT,
                             evidence_ids=evidence("operating_cash_flow", "capex")))

    cap, shares = value("market_cap"), value("shares_outstanding")
    if cap is not None and shares is not None and metrics.get("price") is not None:
        checks.append(_check("market cap = price x shares outstanding",
                             expected=Decimal(str(metrics["price"])) * shares,
                             actual=cap, tolerance=CENT,
                             evidence_ids=evidence("shares_outstanding"),
                             note=f"price as of {metrics.get('price_as_of')}"))

    if cap:
        for concept, yield_key in (
            ("net_income", "earnings_yield"),
            ("free_cash_flow", "fcf_yield"),
            ("equity", "book_to_market"),
        ):
            base = value(concept)
            if base is not None and yield_key in m:
                checks.append(_check(
                    f"{yield_key} = {concept} / market cap",
                    expected=base / cap, actual=m[yield_key]["value"], tolerance=RATIO,
                    evidence_ids=evidence(concept, "shares_outstanding"),
                ))
        if net_income is not None and net_income > 0 and "pe" in m:
            checks.append(_check(
                "pe = market cap / net_income", expected=cap / net_income,
                actual=m["pe"]["value"], tolerance=RATIO,
                evidence_ids=evidence("net_income", "shares_outstanding"),
            ))
        if "pe" in m and "earnings_yield" in m:
            product = Decimal(str(m["pe"]["value"])) * Decimal(str(m["earnings_yield"]["value"]))
            checks.append(_check("P/E x earnings yield = 1", expected=Decimal(1), actual=product,
                                 tolerance=RATIO, evidence_ids=evidence("net_income", "shares_outstanding")))

    total_debt, cash = value("total_debt"), value("cash_and_equivalents")
    if cap is not None and total_debt is not None and cash is not None and "ev" in m:
        checks.append(_check("EV = market cap + total debt - cash",
                             expected=cap + total_debt - cash, actual=m["ev"]["value"],
                             tolerance=CENT,
                             evidence_ids=evidence("shares_outstanding", "cash_and_equivalents")))
    return checks


def validate_actions(db, security_id: str, *, as_of: str | None = None) -> list[dict[str, Any]]:
    actions = ActionStore(db).list(security_id, knowledge_as_of=as_of)
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions:
        duplicate = action.action_id in seen
        seen.add(action.action_id)
        checks.append({
            "name": f"action {action.action_id} is unique and dated",
            "expected": "unique, ex-date present",
            "actual": ("duplicate" if duplicate else "unique") + (f", {action.ex_date}" if action.ex_date else ", no ex-date"),
            "passed": bool(not duplicate and action.ex_date and parse_iso(action.ex_date)),
            "evidence_ids": [action.action_id],
            "note": action.action_type,
        })
        if action.cash_amount is not None:
            checks.append({
                "name": f"dividend {action.ex_date} amount > 0",
                "expected": "> 0",
                "actual": str(action.cash_amount),
                "passed": Decimal(str(action.cash_amount)) > 0,
                "evidence_ids": [action.action_id],
                "note": "cash dividend",
            })
        if action.ratio_to is not None and action.ratio_from:
            factor = Decimal(str(action.ratio_to)) / Decimal(str(action.ratio_from))
            checks.append({
                "name": f"split {action.ex_date} factor is positive",
                "expected": "factor > 0",
                "actual": str(factor),
                "passed": factor > 0,
                "evidence_ids": [action.action_id],
                "note": "ratio_to / ratio_from",
            })
    return checks


def _independent_split_factor(actions: Iterable[Any], session_date: str) -> Decimal:
    factor = Decimal(1)
    for action in actions:
        if action.ratio_to and action.ratio_from and action.ex_date and action.ex_date > session_date:
            factor *= Decimal(str(action.ratio_to)) / Decimal(str(action.ratio_from))
    return factor


def validate_market(db, security_id: str, *, as_of: str | None = None) -> list[dict[str, Any]]:
    # A five-year window stays below the browser downsample threshold, so every point
    # can be compared one-for-one instead of validating a sampled series.
    raw = read_models.market_series(db, security_id, range_key="5Y", view="raw", as_of=as_of)
    split = read_models.market_series(db, security_id, range_key="5Y", view="split", as_of=as_of)
    actions = ActionStore(db).list(security_id, knowledge_as_of=as_of)
    checks: list[dict[str, Any]] = []
    if not raw["bars"] or not split["bars"]:
        return [{"name": "market series exists", "passed": False, "expected": ">=1 bar",
                 "actual": str(len(raw["bars"])), "evidence_ids": [], "note": "no observations"}]
    split_by_date = {bar["date"]: bar for bar in split["bars"]}
    mismatches = 0
    worst = Decimal(0)
    for bar in raw["bars"]:
        adjusted = split_by_date.get(bar["date"])
        if adjusted is None:
            mismatches += 1
            continue
        expected = Decimal(str(bar["close"])) / _independent_split_factor(actions, bar["date"])
        difference = abs(expected - Decimal(str(adjusted["close"])))
        worst = max(worst, difference)
        if difference > CENT:
            mismatches += 1
    checks.append({
        "name": "split-adjusted close = raw close / cumulative split factor",
        "expected": "0 bars beyond $0.011",
        "actual": f"{mismatches} mismatched; worst {worst}",
        "passed": mismatches == 0,
        "evidence_ids": [],
        "note": f"{len(raw['bars'])} raw observations checked independently",
    })

    tr = read_models.market_series(db, security_id, range_key="5Y", view="total_return", as_of=as_of)
    points = tr.get("index", [])
    dividends: dict[str, Decimal] = {}
    for action in actions:
        if action.cash_amount is not None and action.ex_date:
            dividends[action.ex_date] = dividends.get(action.ex_date, Decimal(0)) + Decimal(str(action.cash_amount))
    if len(points) > 1:
        level = Decimal(1)
        previous = None
        worst_tr = Decimal(0)
        for point in points:
            bar = split_by_date.get(point["time"])
            if bar is None:
                continue
            close = Decimal(str(bar["close"]))
            if previous is not None and previous > 0:
                factor = _independent_split_factor(actions, point["time"])
                dividend = dividends.get(point["time"], Decimal(0)) / factor
                level *= (close + dividend) / previous
            previous = close
        worst_tr = abs(level - Decimal(str(points[-1]["value"])))
        checks.append(_check(
            "total-return index recomputed from prices, splits and dividends",
            expected=level, actual=points[-1]["value"], tolerance=Decimal("1e-8"),
            note=f"{len(points)} index points; absolute difference {worst_tr}",
        ))
    return checks


def run(db, identifier: str, *, as_of: str | None = None, mode: str | None = None) -> dict[str, Any]:
    instant = iso(as_of) if as_of else iso(utcnow())
    metrics = read_models.issuer_metrics(db, identifier, as_of=instant, mode=mode)
    issuer = metrics["issuer"]
    checks: list[dict[str, Any]] = []
    checks.extend(validate_ratios({**metrics["metrics"], "price": metrics.get("price"),
                                   "price_as_of": metrics.get("price_as_of")}))
    securities = read_models.list_companies(db, limit=500)
    security_id = next(
        (s["security_id"] for company in securities if company["issuer_id"] == issuer["issuer_id"]
         for s in company["securities"]), None
    )
    if security_id:
        checks.extend(validate_actions(db, security_id, as_of=instant))
        checks.extend(validate_market(db, security_id, as_of=instant))
    passed = sum(1 for check in checks if check["passed"])
    return {
        "issuer": issuer,
        "as_of": instant,
        "mode": metrics["mode"],
        "security_id": security_id,
        "checks": checks,
        "passed": passed,
        "failed": len(checks) - passed,
        "total": len(checks),
        "status": "verified" if checks and passed == len(checks) else "failed" if checks else "insufficient_data",
        "tolerances": {"decimal": str(EXACT), "adjusted_price": str(CENT), "ratio": str(RATIO)},
        "notes": [
            "Checks recompute values from inputs; they do not call the indicator or ratio function under test.",
            "Adjusted prices allow one cent of rounding; ratios are exact to 1e-9.",
            "A passing run proves consistency with this implementation's declared formulas, not the absence of vendor data errors.",
        ],
        "schema": "atlas.research.validation.v1",
    }
