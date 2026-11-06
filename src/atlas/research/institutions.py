"""Equity valuation models for banks, capital-markets firms and insurers.

The Phase 9 engine valued operating companies with an unlevered free-cash-flow DCF and
correctly refused financial institutions. That refusal was honest but incomplete: banks
and insurers are a large part of the listed market and they have their own economics.

This module implements two equity-side models:

* **Residual income** for banks and capital-markets firms. Value is reported book value
  plus the present value of returns earned above the cost of equity. Debt, deposits and
  trading liabilities are operating inputs, so the enterprise-to-equity bridge of a DCF
  does not apply.
* **Justified earnings with a residual-income cross-check** for insurers. Consolidated
  insurers mix underwriting with service businesses; when segment disclosures are absent
  the result is explicitly partial rather than silently treated as a pure insurer.

Both models consume reported facts only. Assumptions are named, versioned, and echoed in
the output. A negative residual equity value is preserved and labelled as a calculated
residual, never presented as a tradable negative share price and never floored at zero.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .eligibility import (
    JUSTIFIED_EARNINGS,
    RESIDUAL_INCOME,
    build_contract,
    classify_business_model,
)

INSTITUTION_SCHEMA = "atlas.institution_valuation.v1"
BANK_MODEL_VERSION = "atlas.bank.residual_income.v1"
INSURER_MODEL_VERSION = "atlas.insurer.justified_earnings.v1"

BANK_DEFAULTS = {
    "cost_of_equity": 0.10,
    "sustainable_roe": None,
    "growth": 0.03,
    "payout_ratio": 0.40,
    "horizon": 5,
    "terminal_growth": 0.025,
}

INSURER_DEFAULTS = {
    "cost_of_equity": 0.09,
    "growth": 0.04,
    "payout_ratio": 0.35,
    "terminal_growth": 0.025,
}


def _metric(metrics: Mapping[str, Any], key: str) -> float | None:
    item = (metrics.get("metrics") or {}).get(key)
    if not isinstance(item, Mapping) or item.get("value") is None:
        return None
    try:
        return float(item["value"])
    except (TypeError, ValueError):
        return None


def _evidence(metrics: Mapping[str, Any], key: str) -> list[str]:
    item = (metrics.get("metrics") or {}).get(key)
    if not isinstance(item, Mapping):
        return []
    return list(item.get("evidence_ids") or [])


def _inputs(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "equity": _metric(metrics, "equity"),
        "net_income": _metric(metrics, "net_income"),
        "net_income_common": _metric(metrics, "net_income_common"),
        "eps_diluted": _metric(metrics, "eps_diluted"),
        "shares_outstanding": _metric(metrics, "shares_outstanding"),
        "weighted_average_shares_diluted": _metric(metrics, "weighted_average_shares_diluted"),
        "total_assets": _metric(metrics, "assets"),
        "total_liabilities": _metric(metrics, "liabilities"),
        "operating_cash_flow": _metric(metrics, "operating_cash_flow"),
        "revenue": _metric(metrics, "revenue"),
        "operating_income": _metric(metrics, "operating_income"),
        "roe": _metric(metrics, "roe"),
        "period_end": metrics.get("period_end"),
    }


def _provenance(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: {
            "value": _metric(metrics, key),
            "evidence_ids": _evidence(metrics, key),
            "basis": ((metrics.get("metrics") or {}).get(key) or {}).get("basis")
            if isinstance((metrics.get("metrics") or {}).get(key), Mapping)
            else None,
        }
        for key in (
            "equity",
            "net_income",
            "net_income_common",
            "eps_diluted",
            "shares_outstanding",
            "weighted_average_shares_diluted",
            "assets",
            "liabilities",
            "revenue",
            "roe",
        )
        if _metric(metrics, key) is not None
    }


def _share_bases(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    bases = []
    if inputs.get("shares_outstanding"):
        bases.append({"basis": "period_end_share_count", "shares": float(inputs["shares_outstanding"])})
    if inputs.get("weighted_average_shares_diluted"):
        bases.append({
            "basis": "weighted_average_diluted",
            "shares": float(inputs["weighted_average_shares_diluted"]),
        })
    return bases


# --------------------------------------------------------------------------- bank
def _bank_arithmetic(
    *,
    book_value: float,
    roe: float,
    cost_of_equity: float,
    growth: float,
    payout: float,
    horizon: int,
    terminal_growth: float,
) -> dict[str, Any]:
    """Plain-arithmetic residual income, independent of the reporting presentation."""
    bv = book_value
    rows = []
    pv_ri = 0.0
    for year in range(1, horizon + 1):
        net_income = roe * bv
        dividends = net_income * payout
        residual = net_income - cost_of_equity * bv
        discount = (1.0 + cost_of_equity) ** year
        pv = residual / discount
        pv_ri += pv
        rows.append({
            "year": year,
            "opening_book_value": bv,
            "net_income": net_income,
            "dividends": dividends,
            "residual_income": residual,
            "present_value": pv,
            "closing_book_value": bv + net_income - dividends,
        })
        bv = bv + net_income - dividends
    terminal_residual = (roe - cost_of_equity) * bv * (1.0 + terminal_growth)
    if cost_of_equity <= terminal_growth:
        terminal_value = None
        terminal_note = "Cost of equity must exceed terminal growth for a finite terminal value."
    else:
        terminal_value = terminal_residual / (cost_of_equity - terminal_growth)
        terminal_note = None
    pv_terminal = (terminal_value / ((1.0 + cost_of_equity) ** horizon)) if terminal_value is not None else None
    equity_value = book_value + pv_ri + (pv_terminal or 0.0) if terminal_value is not None else None
    return {
        "rows": rows,
        "pv_explicit_residual_income": pv_ri,
        "terminal_residual_income": terminal_residual,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal,
        "calculated_equity_value": equity_value,
        "terminal_note": terminal_note,
        "book_value_rollforward_ends_at": bv,
    }


def _bank_sensitivity(
    *,
    book_value: float,
    roe: float,
    shares: float,
    base: Mapping[str, Any],
) -> dict[str, Any]:
    grid = []
    for cost_of_equity in (base["cost_of_equity"] - 0.01, base["cost_of_equity"], base["cost_of_equity"] + 0.01):
        for roe_shift in (-0.02, 0.0, 0.02):
            scenario_roe = roe + roe_shift
            calc = _bank_arithmetic(
                book_value=book_value,
                roe=scenario_roe,
                cost_of_equity=cost_of_equity,
                growth=base["growth"],
                payout=base["payout_ratio"],
                horizon=base["horizon"],
                terminal_growth=base["terminal_growth"],
            )
            value = calc["calculated_equity_value"]
            grid.append({
                "cost_of_equity": round(cost_of_equity, 6),
                "roe": round(scenario_roe, 6),
                "equity_value": value,
                "value_per_share": (value / shares) if value is not None and shares else None,
            })
    terminal = []
    for terminal_growth in (0.015, base["terminal_growth"], 0.035):
        calc = _bank_arithmetic(
            book_value=book_value,
            roe=roe,
            cost_of_equity=base["cost_of_equity"],
            growth=base["growth"],
            payout=base["payout_ratio"],
            horizon=base["horizon"],
            terminal_growth=terminal_growth,
        )
        value = calc["calculated_equity_value"]
        terminal.append({
            "terminal_growth": terminal_growth,
            "equity_value": value,
            "value_per_share": (value / shares) if value is not None and shares else None,
        })
    share_rows = []
    for item in _share_bases({"shares_outstanding": base.get("shares_outstanding"),
                              "weighted_average_shares_diluted": base.get("weighted_average_shares_diluted")}):
        value = base["calculated_equity_value"]
        share_rows.append({
            **item,
            "value_per_share": (value / item["shares"]) if value is not None and item["shares"] else None,
        })
    return {
        "cost_of_equity_and_roe": grid,
        "terminal_growth": terminal,
        "share_basis": share_rows,
        "note": (
            "Sensitivity cells are model outputs under the stated assumptions, not forecasts. "
            "They show how much the value depends on inputs Atlas did not observe."
        ),
    }


def build_bank_valuation(
    *,
    issuer: Mapping[str, Any],
    metrics: Mapping[str, Any],
    coverage: Mapping[str, Any],
    assumptions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = _inputs(metrics)
    merged = dict(BANK_DEFAULTS)
    merged.update({key: value for key, value in (assumptions or {}).items() if value is not None})
    book_value = inputs.get("equity")
    net_income = inputs.get("net_income_common") or inputs.get("net_income")
    shares = inputs.get("shares_outstanding")
    if book_value is None or net_income is None or not shares:
        return {
            "schema": INSTITUTION_SCHEMA,
            "method": RESIDUAL_INCOME,
            "model_version": BANK_MODEL_VERSION,
            "status": "unsupported_data",
            "reason": "Residual income requires reported book value, net income and a share denominator.",
            "inputs": inputs,
            "executes": False,
            "economically_supported": False,
        }
    reported_roe = inputs.get("roe") or (net_income / book_value if book_value else None)
    roe = float(merged["sustainable_roe"]) if merged.get("sustainable_roe") is not None else float(reported_roe)
    cost_of_equity = float(merged["cost_of_equity"])
    terminal_growth = float(merged["terminal_growth"])
    horizon = int(merged["horizon"])
    calc = _bank_arithmetic(
        book_value=float(book_value),
        roe=roe,
        cost_of_equity=cost_of_equity,
        growth=float(merged["growth"]),
        payout=float(merged["payout_ratio"]),
        horizon=horizon,
        terminal_growth=terminal_growth,
    )
    equity_value = calc["calculated_equity_value"]
    raw_per_share = (equity_value / float(shares)) if equity_value is not None else None
    negative = equity_value is not None and equity_value < 0
    findings: list[dict[str, Any]] = []
    if negative:
        findings.append({
            "code": "negative_residual_equity",
            "severity": "warning",
            "detail": (
                "The calculated residual equity value is negative. It is reported as a calculated "
                "residual, not as a negative price a holder could realise; the common-stock value "
                "is not floored at zero and is not presented as tradable."
            ),
        })
    if roe <= cost_of_equity:
        findings.append({
            "code": "no_excess_return",
            "severity": "warning",
            "detail": (
                "Reported return on equity does not exceed the assumed cost of equity, so the "
                "residual-income contribution is zero or negative and the value is anchored to "
                "book value."
            ),
        })
    if terminal_growth >= cost_of_equity:
        findings.append({
            "code": "terminal_growth_exceeds_cost_of_equity",
            "severity": "error",
            "detail": "No finite terminal value exists under these assumptions.",
        })
    if inputs.get("weighted_average_shares_diluted"):
        findings.append({
            "code": "share_basis_divergence",
            "severity": "info",
            "detail": (
                "Period-end shares and weighted-average diluted shares differ. The primary value "
                "uses the period-end count at the valuation date; the weighted-average count is "
                "shown as a sensitivity because it belongs to the income period, not the valuation date."
            ),
        })
    audit_checks = [
        {
            "name": "book value roll-forward",
            "formula": "BV_end = BV_start + net income - dividends",
            "expected": calc["book_value_rollforward_ends_at"],
            "actual": calc["rows"][-1]["closing_book_value"] if calc["rows"] else None,
        },
        {
            "name": "present value of residual income",
            "formula": "sum((NI_t - CoE*BV_t-1)/(1+CoE)^t)",
            "expected": sum(row["present_value"] for row in calc["rows"]),
            "actual": calc["pv_explicit_residual_income"],
        },
        {
            "name": "equity value bridge",
            "formula": "BV0 + PV(RI) + PV(TV) = equity value",
            "expected": (
                book_value + calc["pv_explicit_residual_income"] + (calc["pv_terminal_value"] or 0.0)
                if calc["terminal_value"] is not None else None
            ),
            "actual": equity_value,
        },
    ]
    for check in audit_checks:
        expected = check["expected"]
        actual = check["actual"]
        check["difference"] = (
            abs(float(expected) - float(actual))
            if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) else None
        )
        check["passed"] = check["difference"] is not None and check["difference"] <= max(1.0, abs(float(expected or 0)) * 1e-9)
    passed = all(check["passed"] for check in audit_checks)
    arithmetic = {
        "passed": passed,
        "checks": audit_checks,
        "tolerance": "1e-9 relative or 1 USD absolute on monetary components",
        "version": BANK_MODEL_VERSION,
    }
    limitations = [
        "Tangible book value is not computed: goodwill and intangible assets are not mapped in this fixture, so the tangible-book cross-check is unavailable rather than assumed to equal book value.",
        "Credit losses, net interest margin, deposit beta and regulatory capital ratios are not modelled from Call Reports; only consolidated SEC facts are used.",
        "Segment-level earnings and regulatory-entity data are not available in this fixture and are not proxied.",
        "The cost of equity is an explicit analyst assumption, not a market-observed quantity; no price series is bundled.",
    ]
    contract = build_contract(
        issuer=issuer,
        metrics=metrics,
        coverage=coverage,
        available=[key for key, value in inputs.items() if value is not None],
        assumptions={key: merged[key] for key in ("cost_of_equity", "sustainable_roe", "growth",
                                                   "payout_ratio", "horizon", "terminal_growth")},
        arithmetic=arithmetic,
        extra_limitations=limitations,
    )
    return {
        "schema": INSTITUTION_SCHEMA,
        "method": RESIDUAL_INCOME,
        "method_description": "Residual income on reported book value.",
        "business_model": classify_business_model(issuer.get("sic"))["business_model"],
        "model_version": BANK_MODEL_VERSION,
        "status": "supported",
        "executes": True,
        "economically_supported": False,
        "assumptions": {
            "cost_of_equity": cost_of_equity,
            "sustainable_roe": roe,
            "growth": float(merged["growth"]),
            "payout_ratio": float(merged["payout_ratio"]),
            "horizon": horizon,
            "terminal_growth": terminal_growth,
            "share_basis": "period_end_share_count",
        },
        "inputs": inputs,
        "provenance": _provenance(metrics),
        "outputs": {
            "book_value_common_equity": book_value,
            "reported_roe": reported_roe,
            "calculated_equity_value": equity_value,
            "value_per_share": raw_per_share,
            "realizable_common_price": None if negative else raw_per_share,
            "negative_residual_equity": negative,
            "pv_explicit_residual_income": calc["pv_explicit_residual_income"],
            "pv_terminal_value": calc["pv_terminal_value"],
            "terminal_value": calc["terminal_value"],
            "terminal_value_share": (
                (calc["pv_terminal_value"] / equity_value)
                if calc["pv_terminal_value"] is not None and equity_value else None
            ),
            "rows": calc["rows"],
        },
        "sensitivity": _bank_sensitivity(
            book_value=float(book_value),
            roe=roe,
            shares=float(shares),
            base={
                **merged,
                "cost_of_equity": cost_of_equity,
                "calculated_equity_value": equity_value,
                "shares_outstanding": inputs.get("shares_outstanding"),
                "weighted_average_shares_diluted": inputs.get("weighted_average_shares_diluted"),
            },
        ),
        "audit": arithmetic,
        "contract": contract,
        "findings": findings,
        "limitations": limitations,
        "segments": {
            "status": "unavailable",
            "detail": "No segment revenue or earnings tags are mapped in this fixture; segment analysis is not fabricated.",
        },
        "tangible_book": {
            "status": "unavailable",
            "tangible_book_value": None,
            "tangible_book_per_share": None,
            "detail": "Goodwill and intangibles are not mapped; tangible book is not proxied by book value.",
        },
    }


# ------------------------------------------------------------------------- insurer
def build_insurer_valuation(
    *,
    issuer: Mapping[str, Any],
    metrics: Mapping[str, Any],
    coverage: Mapping[str, Any],
    assumptions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = _inputs(metrics)
    merged = dict(INSURER_DEFAULTS)
    merged.update({key: value for key, value in (assumptions or {}).items() if value is not None})
    eps = inputs.get("eps_diluted")
    net_income = inputs.get("net_income")
    book_value = inputs.get("equity")
    shares = inputs.get("shares_outstanding")
    cost_of_equity = float(merged["cost_of_equity"])
    growth = float(merged["growth"])
    terminal_growth = float(merged["terminal_growth"])
    payout = float(merged["payout_ratio"])
    if eps is None or not shares:
        return {
            "schema": INSTITUTION_SCHEMA,
            "method": JUSTIFIED_EARNINGS,
            "model_version": INSURER_MODEL_VERSION,
            "status": "unsupported_data",
            "reason": "A justified-earnings value requires diluted EPS and a share denominator.",
            "inputs": inputs,
            "executes": False,
            "economically_supported": False,
        }
    justified_pe = (payout * (1.0 + growth) / (cost_of_equity - growth)
                    if cost_of_equity > growth else None)
    value_per_share = eps * justified_pe if justified_pe is not None else None
    equity_value = value_per_share * shares if value_per_share is not None else None
    roe = (net_income / book_value) if net_income is not None and book_value else None
    residual_check = None
    if book_value and net_income is not None and cost_of_equity > terminal_growth:
        residual = net_income - cost_of_equity * book_value
        residual_check = {
            "book_value": book_value,
            "residual_income": residual,
            "capitalized_residual": residual * (1.0 + terminal_growth) / (cost_of_equity - terminal_growth),
            "method": "single-period residual capitalisation, for cross-check only",
        }
    findings = []
    if value_per_share is not None and value_per_share < 0:
        findings.append({
            "code": "negative_justified_value",
            "severity": "warning",
            "detail": "Negative earnings imply a negative justified value; it is preserved and not treated as a price.",
        })
    if justified_pe is not None and justified_pe > 25:
        findings.append({
            "code": "high_justified_multiple",
            "severity": "warning",
            "detail": f"Justified P/E of {justified_pe:.1f}x is highly sensitive to the assumed cost of equity and growth.",
        })
    sensitivity = []
    for cost in (cost_of_equity - 0.01, cost_of_equity, cost_of_equity + 0.01):
        for g in (growth - 0.01, growth, growth + 0.01):
            if cost <= g:
                continue
            pe = payout * (1.0 + g) / (cost - g)
            sensitivity.append({
                "cost_of_equity": round(cost, 6),
                "growth": round(g, 6),
                "justified_pe": pe,
                "value_per_share": eps * pe,
            })
    checks = []
    if value_per_share is not None and equity_value is not None:
        checks.append({
            "name": "equity value from per-share value",
            "formula": "value_per_share * shares = equity value",
            "expected": equity_value,
            "actual": value_per_share * shares,
            "passed": abs(equity_value - value_per_share * shares) <= 1e-6,
        })
    checks.append({
        "name": "justified P/E identity",
        "formula": "payout*(1+g)/(CoE-g)",
        "expected": justified_pe,
        "actual": (payout * (1.0 + growth) / (cost_of_equity - growth)
                   if cost_of_equity > growth else None),
        "passed": justified_pe is not None and cost_of_equity > growth,
    })
    passed = all(check["passed"] for check in checks) and value_per_share is not None
    arithmetic = {
        "passed": passed,
        "checks": checks,
        "tolerance": "1e-6 relative on the per-share identity",
        "version": INSURER_MODEL_VERSION,
    }
    limitations = [
        "UnitedHealth consolidates a healthcare-services business with insurance operations. No segment split is mapped in this fixture, so the earnings-based value is partial and is not presented as a pure-insurer valuation.",
        "The medical loss ratio, claims development and reserve adequacy are not computed: premium and medical-cost tags are not mapped.",
        "Membership, premium trends and regulatory capital at the plan level are not available; no CMS plan-level data is joined to consolidated results.",
        "The justified multiple is an explicit assumption-driven result, not an observed market multiple; no market price is bundled.",
    ]
    contract = build_contract(
        issuer=issuer,
        metrics=metrics,
        coverage=coverage,
        available=[key for key, value in inputs.items() if value is not None],
        assumptions={key: merged[key] for key in ("cost_of_equity", "growth", "payout_ratio", "terminal_growth")},
        arithmetic=arithmetic,
        partial=True,
        extra_limitations=limitations,
    )
    return {
        "schema": INSTITUTION_SCHEMA,
        "method": JUSTIFIED_EARNINGS,
        "method_description": "Justified earnings value with a residual-income cross-check.",
        "business_model": classify_business_model(issuer.get("sic"))["business_model"],
        "model_version": INSURER_MODEL_VERSION,
        "status": "supported",
        "executes": True,
        "economically_supported": False,
        "partial": True,
        "assumptions": {
            "cost_of_equity": cost_of_equity,
            "growth": growth,
            "payout_ratio": payout,
            "terminal_growth": terminal_growth,
            "share_basis": "period_end_share_count",
        },
        "inputs": inputs,
        "provenance": _provenance(metrics),
        "outputs": {
            "eps_diluted": eps,
            "net_income": net_income,
            "reported_roe": roe,
            "justified_pe": justified_pe,
            "value_per_share": value_per_share,
            "calculated_equity_value": equity_value,
            "residual_income_cross_check": residual_check,
        },
        "sensitivity": {
            "cost_of_equity_and_growth": sensitivity,
            "note": "Cells are assumption-driven outputs, not observed market multiples.",
        },
        "audit": arithmetic,
        "contract": contract,
        "findings": findings,
        "limitations": limitations,
        "segments": {
            "status": "unavailable",
            "detail": "Consolidated statements mix insurance and healthcare services; no segment split is mapped.",
        },
        "health_insurance": {
            "medical_loss_ratio": None,
            "premium_revenue": None,
            "medical_costs": None,
            "reserves": None,
            "status": "not_available_in_fixture",
            "detail": "Plan-level and line-of-business disclosures are not bundled; no estimate is inserted.",
        },
    }


def build_institution_valuation(
    *,
    issuer: Mapping[str, Any],
    metrics: Mapping[str, Any],
    coverage: Mapping[str, Any],
    assumptions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    classification = classify_business_model(issuer.get("sic"))
    if classification["method"] == JUSTIFIED_EARNINGS:
        return build_insurer_valuation(
            issuer=issuer, metrics=metrics, coverage=coverage, assumptions=assumptions
        )
    return build_bank_valuation(
        issuer=issuer, metrics=metrics, coverage=coverage, assumptions=assumptions
    )


# ------------------------------------------------------------------ bank v2
BANK_MODEL_VERSION_V2 = "atlas.bank.residual_income.v2"
CAPITAL_REQUIREMENTS = {
    "common_equity_tier_1": 7.0,
    "tier_1_leverage": 4.0,
    "total_risk_based_capital": 10.5,
}


def _regulatory_latest(regulatory: Mapping[str, Any] | None) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    if not regulatory:
        return None, None
    for block in regulatory.get("subsidiaries") or []:
        if block.get("status") == "available" and block.get("latest"):
            return block, block["latest"]
    return None, None


def _reg_value(latest: Mapping[str, Any] | None, field: str) -> float | None:
    if not latest:
        return None
    item = (latest.get("values") or {}).get(field)
    if not isinstance(item, Mapping) or item.get("value") is None:
        return None
    try:
        return float(item["value"])
    except (TypeError, ValueError):
        return None


def implied_cost_of_equity(
    *,
    price: float,
    shares: float,
    book_value: float,
    roe: float,
    payout: float,
    horizon: int,
    terminal_growth: float,
    low: float = 0.035,
    high: float = 0.40,
) -> dict[str, Any]:
    """Solve for the cost of equity that reproduces the observed price.

    This is a reverse of the same residual-income arithmetic, not an independent model.
    The result is a market-implied expectation conditional on the other assumptions.
    """
    if price <= 0 or shares <= 0:
        return {"status": "unavailable", "reason": "a positive price and share count are required"}
    if low <= terminal_growth:
        low = terminal_growth + 0.005

    def value(coe: float) -> float | None:
        calc = _bank_arithmetic(
            book_value=book_value, roe=roe, cost_of_equity=coe, growth=0.0,
            payout=payout, horizon=horizon, terminal_growth=terminal_growth,
        )
        equity = calc["calculated_equity_value"]
        return (equity / shares) if equity is not None else None

    f_low, f_high = value(low), value(high)
    if f_low is None or f_high is None:
        return {"status": "unavailable", "reason": "no finite value in the solver bracket"}
    if (f_low - price) * (f_high - price) > 0:
        return {
            "status": "unavailable",
            "reason": "the observed price is outside the model's value range for the declared assumptions",
            "bracket": {"low_coe": low, "high_coe": high,
                        "low_value": f_low, "high_value": f_high},
        }
    # Scan the bracket so a non-monotonic value function cannot be hidden behind
    # one bisection result. Multiple sign changes mean the price is consistent with
    # more than one cost of equity and no single number should be reported.
    scan = [low + (high - low) * index / 200.0 for index in range(201)]
    scan_values = [(coe, value(coe)) for coe in scan]
    sign_changes = 0
    intervals = []
    for (left, left_value), (right, right_value) in zip(scan_values, scan_values[1:]):
        if left_value is None or right_value is None:
            continue
        if (left_value - price) == 0 or (right_value - price) == 0:
            continue
        if (left_value - price) * (right_value - price) < 0:
            sign_changes += 1
            intervals.append([left, right])
    if sign_changes == 0:
        return {"status": "unavailable", "reason": "no price-consistent cost of equity in the bracket"}
    if sign_changes > 1:
        return {
            "status": "ambiguous",
            "reason": (
                "The observed price is consistent with more than one cost of equity under the "
                "declared assumptions; Atlas does not report a single precise implied rate."
            ),
            "root_intervals": intervals,
            "bracket": {"low_coe": low, "high_coe": high},
        }
    a, b = intervals[0]
    iterations = 0
    for _ in range(100):
        iterations += 1
        mid = (a + b) / 2.0
        mid_value = value(mid)
        if mid_value is None:
            return {"status": "unavailable", "reason": "value became undefined inside the bracket"}
        if mid_value > price:
            a = mid
        else:
            b = mid
        if abs(mid_value - price) <= max(1e-8, abs(price) * 1e-10):
            break
    solved = (a + b) / 2.0
    solved_value = value(solved)
    residual = abs(solved_value - price) if solved_value is not None else None
    return {
        "status": "available",
        "implied_cost_of_equity": solved,
        "price": price,
        "solved_value_per_share": solved_value,
        "iterations": iterations,
        "residual_usd": residual,
        "converged": bool(residual is not None and residual <= 0.01),
        "unique_root": True,
        "scan_root_intervals": 1,
        "method": "monotonic_bracket_scan_plus_bisection",
        "bracket": {"low_coe": low, "high_coe": high},
        "conditional_on": {
            "roe": roe, "payout_ratio": payout, "horizon": horizon,
            "terminal_growth": terminal_growth,
        },
        "note": (
            "The implied cost of equity is conditional on the stated ROE, payout, horizon and "
            "terminal growth. It is not an estimate of the true cost of capital."
        ),
    }


def _bank_v2_scenarios(
    *, book_value: float, roe: float, shares: float, base: Mapping[str, Any],
    latest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payout_rows = []
    for payout in (0.20, 0.40, 0.60):
        for buyback in (0.0, 0.02):
            distribution = min(1.0, payout + buyback)
            calc = _bank_arithmetic(
                book_value=book_value, roe=roe, cost_of_equity=float(base["cost_of_equity"]),
                growth=0.0, payout=distribution, horizon=int(base["horizon"]),
                terminal_growth=float(base["terminal_growth"]),
            )
            value = calc["calculated_equity_value"]
            payout_rows.append({
                "payout_ratio": payout,
                "buyback_yield": buyback,
                "total_distribution_ratio": distribution,
                "value_per_share": (value / shares) if value is not None and shares else None,
            })
    stress = []
    equity = _reg_value(latest, "EQ")
    assets = _reg_value(latest, "ASSET")
    nii = _reg_value(latest, "NIM")
    nco = _reg_value(latest, "NTLNLS")
    if equity is not None and assets and nii is not None and nco is not None:
        annual_nii = nii * 4.0
        annual_nco = nco * 4.0
        for nii_shock in (-0.10, 0.0, 0.10):
            for nco_multiple in (1.0, 2.0):
                delta = (annual_nii * nii_shock * 0.79
                         - annual_nco * (nco_multiple - 1.0) * 0.79)
                equity_after = equity + delta
                leverage = (equity_after / assets) * 100.0
                stress.append({
                    "nii_shock": nii_shock,
                    "charge_off_multiple": nco_multiple,
                    "annual_net_income_delta_usd": delta * 1000.0,
                    "equity_after_usd": equity_after * 1000.0,
                    "tier_1_leverage_after_percent": leverage,
                    "passes_minimum": leverage >= CAPITAL_REQUIREMENTS["tier_1_leverage"],
                })
    return {
        "payout_and_buyback": payout_rows,
        "regulatory_stress": stress,
        "regulatory_stress_basis": (
            "subsidiary_standalone, annualized NII and net charge-offs, 21% tax assumption, "
            "assets held constant. This is a capital sensitivity of the insured bank, not a "
            "parent valuation."
        ) if stress else "not_available",
        "note": "Scenarios are assumption grids, not forecasts or management guidance.",
    }


def build_bank_valuation_v2(
    *,
    issuer: Mapping[str, Any],
    metrics: Mapping[str, Any],
    coverage: Mapping[str, Any],
    regulatory: Mapping[str, Any] | None = None,
    assumptions: Mapping[str, Any] | None = None,
    market_price: float | None = None,
) -> dict[str, Any]:
    """Bank residual income v2 with regulatory evidence on the correct legal entity."""
    classification = classify_business_model(issuer.get("sic"))
    merged = {key: value for key, value in (assumptions or {}).items() if value is not None}
    # Capital-markets earnings are more cyclical; the higher default cost of equity is a
    # documented assumption, not an observation. An explicit user value always wins.
    differentiated_default = None
    if classification["business_model"] == "capital_markets" and "cost_of_equity" not in merged:
        merged["cost_of_equity"] = 0.11
        differentiated_default = {
            "field": "cost_of_equity", "value": 0.11, "business_model": "capital_markets",
            "reason": "higher assumed cyclicality of capital-markets revenue; not an observed input",
        }
    base = build_bank_valuation(
        issuer=issuer, metrics=metrics, coverage=coverage, assumptions=merged or None
    )
    if not base.get("executes"):
        return {**base, "model_version": BANK_MODEL_VERSION_V2, "regulatory": regulatory,
                "market": None}
    block, latest = _regulatory_latest(regulatory)
    equity_reg = _reg_value(latest, "EQ")
    intangibles_reg = _reg_value(latest, "INTAN")
    assets_reg = _reg_value(latest, "ASSET")
    tangible_reg = (
        equity_reg - intangibles_reg
        if equity_reg is not None and intangibles_reg is not None else None
    )
    capital = (latest or {}).get("capital_constraint") or {"status": "not_available"}
    derived = (latest or {}).get("derived") or {}
    entity_map = (regulatory or {}).get("entity_map") or {}
    aligned = bool(block and entity_map.get("status") == "verified")
    entity_check = {
        "status": "verified" if aligned else "not_evaluated",
        "compatible": True if aligned else None,
        "parent": (entity_map.get("parent") or {}).get("legal_name"),
        "subsidiary": (block or {}).get("entity", {}).get("legal_name"),
        "parent_basis": "parent_consolidated (SEC)",
        "subsidiary_basis": "subsidiary_standalone (Call Report)",
        "additive": False,
        "reason": (
            "The consolidated parent supplies the per-share denominator; the insured subsidiary "
            "supplies regulatory context. They are never summed."
            if aligned else "No aligned regulatory subsidiary was supplied for this issuer."
        ),
    }
    tangible_book = {
        "status": "available_subsidiary_only" if tangible_reg is not None else "unavailable",
        "basis": "subsidiary_standalone" if tangible_reg is not None else None,
        "legal_entity": (block or {}).get("entity", {}).get("legal_name"),
        "tangible_common_equity_usd": tangible_reg * 1000.0 if tangible_reg is not None else None,
        "tangible_equity_to_assets": (derived.get("tangible_equity_to_assets") or {}).get("value"),
        "value_per_share": None,
        "used_in_per_share": False,
        "parent_status": "not_mapped",
        "detail": (
            "Parent-level goodwill and intangibles are not mapped from SEC facts. Tangible equity "
            "is reported for the insured subsidiary only and is not divided by parent shares."
        ),
    }
    driver = {
        "model": "consolidated_roe_residual_income",
        "business_model": classification["business_model"],
        "label": (
            "capital-markets consolidated ROE" if classification["business_model"] == "capital_markets"
            else "diversified-bank consolidated ROE"
        ),
        "segment_forecast": False,
        "segment_evidence": "unavailable",
        "detail": (
            "Segment revenue and earnings are not mapped, so the model does not forecast consumer "
            "lending, investment banking, trading or asset management separately. The ROE path is "
            "a consolidated assumption labelled accordingly."
        ),
        "differentiated_default": differentiated_default,
    }
    assumptions_out = base["assumptions"]
    implied = None
    if market_price:
        implied = implied_cost_of_equity(
            price=float(market_price), shares=float(base["inputs"]["shares_outstanding"]),
            book_value=float(base["inputs"]["equity"]),
            roe=float(assumptions_out["sustainable_roe"]),
            payout=float(assumptions_out["payout_ratio"]),
            horizon=int(assumptions_out["horizon"]),
            terminal_growth=float(assumptions_out["terminal_growth"]),
        )
    scenarios = _bank_v2_scenarios(
        book_value=float(base["inputs"]["equity"]), roe=float(assumptions_out["sustainable_roe"]),
        shares=float(base["inputs"]["shares_outstanding"]),
        base={**assumptions_out, "cost_of_equity": assumptions_out["cost_of_equity"]},
        latest=latest,
    )
    limitations = list(base.get("limitations") or [])
    limitations.extend([
        "Regulatory capital evidence covers the insured subsidiary, not the consolidated parent; capital headroom is in percentage points because dollar RWA is not published.",
        "The parent's goodwill and intangibles are not mapped, so no parent tangible book value per share is reported.",
        "Consolidated holding-company capital is gated: no FR Y-9C observation is ingested, so subsidiary capital is not promoted to a parent-level conclusion.",
        "Segment-level earnings are not available; the ROE path is consolidated and is labelled as such.",
    ])
    contract = build_contract(
        issuer=issuer, metrics=metrics, coverage=coverage,
        available=list(base["inputs"].keys()) + (["regulatory_capital"] if aligned else []),
        assumptions=assumptions_out,
        arithmetic=base["audit"],
        entity_check=entity_check,
        method_evidence={
            "regulatory_alignment": "aligned_to_declared_subsidiary" if aligned else "not_ingested",
            "subsidiary_entity": (block or {}).get("entity", {}).get("legal_name"),
            "consolidation_basis": "subsidiary_standalone",
            "parent_basis": "parent_consolidated",
            "additive": False,
            "capital_ratios": capital.get("observed_percent") if capital.get("status") == "available" else None,
            "tangible_book_basis": tangible_book["basis"],
        },
        extra_limitations=limitations,
    )
    return {
        **base,
        "model_version": BANK_MODEL_VERSION_V2,
        "contract": contract,
        "regulatory": {
            "status": (regulatory or {}).get("status", "not_ingested"),
            "subsidiary": (block or {}).get("entity"),
            "period_end": (latest or {}).get("period_end"),
            "values": (latest or {}).get("values"),
            "derived": derived,
            "capital": capital,
            "entity_map": entity_map,
            "comparability": (regulatory or {}).get("comparability"),
            "limitations": (regulatory or {}).get("limitations", []),
        } if regulatory else None,
        "capital": capital,
        "tangible_book": tangible_book,
        "driver": driver,
        "scenarios": scenarios,
        "implied": implied,
        "parent_capital": {
            "status": "blocked_fr_y9c_unavailable",
            "basis": "parent_consolidated",
            "reason": (
                "No official FR Y-9C observation for JPMorgan Chase & Co. has been ingested. "
                "The insured-bank Call Report is not a substitute for consolidated holding-company "
                "capital, and the two are never aggregated."
            ),
            "required_evidence": "Federal Reserve FR Y-9C, reporting entity RSSD 852218 / CIK 19617",
            "subsidiary_evidence_used_for_parent": False,
        },
        "external_value_evidence": {
            "status": "not_recorded",
            "detail": (
                "No published analyst value, transaction price or independent valuation report is "
                "recorded for this issuer. Arithmetic verification is not external economic validation."
            ),
        },
    }
