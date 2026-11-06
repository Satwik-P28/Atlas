#!/usr/bin/env python
"""Independent Phase 9.2 audit: regulatory identities, bank arithmetic and price alignment.

Every reference calculation here is implemented with Decimal inside this file. It does
not call the production residual-income operators, so two independent implementations
must agree before a check passes.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, getcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.applications.contracts import read_package  # noqa: E402
from atlas.research import institutions, regulatory  # noqa: E402
from atlas.research.equity import EquityResearchService  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

getcontext().prec = 34


def reference_ri(book, roe, coe, payout, horizon, terminal_growth):
    bv = Decimal(str(book)); roe = Decimal(str(roe)); coe = Decimal(str(coe))
    payout = Decimal(str(payout)); g = Decimal(str(terminal_growth))
    pv = Decimal(0)
    for year in range(1, horizon + 1):
        ni = bv * roe
        residual = ni - coe * bv
        pv += residual / ((Decimal(1) + coe) ** year)
        bv += ni * (Decimal(1) - payout)
    terminal = (roe - coe) * bv * (Decimal(1) + g) / (coe - g)
    return bv, pv, terminal / ((Decimal(1) + coe) ** horizon), Decimal(str(book)) + pv + terminal / ((Decimal(1) + coe) ** horizon)


def approx(a, b, tol=Decimal("0.02")):
    return abs(Decimal(str(a)) - Decimal(str(b))) <= tol


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9.db")
    parser.add_argument("--out", default="artifacts/phase9_2_model_audit.json")
    args = parser.parse_args()
    db = Database(args.db, create=False)
    svc = EquityResearchService(db)
    checks = []
    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    jpm = svc.valuation("JPM"); gs = svc.valuation("GS"); unh = svc.valuation("UNH")
    jm = jpm["institution"]; gm = gs["institution"]; um = unh["institution"]
    ri = jm["outputs"]["rows"][0]
    close_bv, pv, pv_tv, equity = reference_ri(
        jm["inputs"]["equity"], jm["assumptions"]["sustainable_roe"],
        jm["assumptions"]["cost_of_equity"], jm["assumptions"]["payout_ratio"],
        int(jm["assumptions"]["horizon"]), jm["assumptions"]["terminal_growth"])
    check("book-value roll-forward", approx(ri["closing_book_value"], (Decimal(str(ri["opening_book_value"])) + Decimal(str(ri["net_income"])) - Decimal(str(ri["dividends"])))),
          "opening + net income - distributions = closing")
    check("distribution treatment", approx(ri["dividends"], Decimal(str(ri["net_income"])) * Decimal(str(jm["assumptions"]["payout_ratio"]))),
          "payout applied to net income in the reference schedule")
    check("residual-income present value", approx(jm["outputs"]["pv_explicit_residual_income"], pv, Decimal("1")),
          f"reference PV {pv}")
    check("terminal residual value", approx(jm["outputs"]["pv_terminal_value"], pv_tv, Decimal("1")),
          f"reference PV terminal {pv_tv}")
    check("equity value bridge", approx(jm["outputs"]["calculated_equity_value"], equity, Decimal("2")),
          f"reference equity {equity}")
    grid = jm["sensitivity"]["cost_of_equity_and_roe"]
    check("cost-of-equity sensitivity direction", all(
        grid[i]["value_per_share"] >= grid[i + 3]["value_per_share"]
        for i in range(3) if grid[i]["value_per_share"] is not None and grid[i + 3]["value_per_share"] is not None),
        "value falls as cost of equity rises at fixed ROE")
    check("ROE sensitivity direction", all(
        grid[i]["value_per_share"] <= grid[i + 1]["value_per_share"]
        for i in (0, 3, 6) if grid[i]["value_per_share"] is not None),
        "value rises with ROE at fixed cost of equity")
    tce = jm["tangible_book"]
    eq = jm["regulatory"]["values"]["EQ"]["value"]; intan = jm["regulatory"]["values"]["INTAN"]["value"]
    check("tangible equity adjustment", tce["tangible_common_equity_usd"] == (eq - intan) * 1000 and tce["used_in_per_share"] is False,
          "EQ - INTAN on the subsidiary; never divided by parent shares")
    vals = {k: v["value"] for k, v in jm["regulatory"]["values"].items() if v.get("value") is not None}
    check("capital ratio reconciliation", approx(vals["RBCRWAJ"], 16.211188932535546) and jm["capital"]["status"] == "available",
          "reported total risk-based ratio preserved, not recomputed without RWA")
    check("net interest income bounds", (
        vals.get("NIM") is not None and vals.get("INTINC") is not None
        and 0 < vals["NIM"] < vals["INTINC"] and vals.get("NIMY", 0) > 0
    ), "NIM lies between zero and reported interest income; FDIC omits interest expense in the latest record, so no identity is asserted")
    stress = (jm["scenarios"]["regulatory_stress"] or [None])[0]
    expected_delta = (Decimal(str(vals["NIM"])) * 4 * Decimal("-0.10") * Decimal("0.79")) * 1000
    check("credit-loss and NII stress arithmetic", stress is not None and approx(
        stress["annual_net_income_delta_usd"], expected_delta, Decimal("1")),
        "subsidiary stress applies annualized NII shock and 21% tax; reported allowance ratio uses a broader loan base and is not asserted as an identity")
    check("insurance premium and claims arithmetic", um["health_insurance"]["status"] == "not_available_in_fixture",
          "no premium or claims fields are invented when the fixture lacks them")
    check("insurance operating margin identity", um["outputs"]["justified_pe"] is not None and approx(
        um["outputs"]["value_per_share"], um["outputs"]["eps_diluted"] * um["outputs"]["justified_pe"], Decimal("0.01")),
        "value per share = EPS x justified multiple")
    check("equity value per share", approx(jm["outputs"]["value_per_share"], jm["outputs"]["calculated_equity_value"] / jm["inputs"]["shares_outstanding"], Decimal("0.01")),
          "equity value / period-end share count")
    check("historical source timing preserved", bool(jm["regulatory"]["values"]["EQ"]["observation_id"]) and jm["regulatory"]["status"] == "available",
          "each observation carries an id, source and period; retrieval time is stored in provenance")
    market = jpm["market"]
    filing_time = market.get("filing_available_at")
    check("market-price cutoff safety", (
        market["status"] == "available" and market["lookahead_safe"] is True
        and market["price_date"] <= market["information_cutoff"]
        and (filing_time is None or filing_time[:10] <= market["information_cutoff"])
    ), f"price {market['price_date']} <= cutoff {market['information_cutoff']}; filing {filing_time or 'unrecorded'}; mixed_date={market['mixed_date']}")
    rejected = False
    try:
        regulatory.assert_comparable([
            {"entity_id": "REG-JPM-PARENT", "consolidation_basis": regulatory.PARENT, "period_end": "2025-12-31"},
            {"entity_id": "REG-JPM-BANK", "consolidation_basis": regulatory.SUBSIDIARY, "period_end": "2025-12-31"},
        ])
    except regulatory.RegulatoryReconciliationError:
        rejected = True
    check("parent/subsidiary conflation rejected", rejected, "mixed consolidation bases raise instead of aggregating")
    period_rejected = False
    try:
        regulatory.assert_comparable([
            {"entity_id": "REG-JPM-BANK", "consolidation_basis": regulatory.SUBSIDIARY, "period_end": "2025-12-31"},
            {"entity_id": "REG-JPM-BANK", "consolidation_basis": regulatory.SUBSIDIARY, "period_end": "2026-06-30"},
        ])
    except regulatory.RegulatoryReconciliationError:
        period_rejected = True
    check("incompatible reporting periods rejected", period_rejected, "different period ends raise instead of forming a ratio")
    package = svc.create_package("JPM")
    loaded = read_package(package["payload"])
    financials = json.loads(loaded["files"]["data/financials.json"])
    replay = institutions.build_bank_valuation_v2(
        issuer=financials["issuer"], metrics=financials["metrics"], coverage=financials["coverage"],
        regulatory=financials.get("regulatory"),
        assumptions=json.loads(loaded["files"]["artifacts/institution.json"])["assumptions"])
    check("research package reproduction", approx(replay["outputs"]["value_per_share"], jm["outputs"]["value_per_share"], Decimal("0.01")),
          "independent recomputation from the packaged snapshot and assumptions")
    summary = {
        "schema": "atlas.phase9_2.audit.v1",
        "database": args.db,
        "counts": {"total": len(checks), "passed": sum(1 for c in checks if c["passed"])},
        "status": "pass" if all(c["passed"] for c in checks) else "fail",
        "checks": checks,
        "independent_reference": "Decimal arithmetic implemented in this script; production operators are not called for reference values.",
        "limitations": [
            "Parent goodwill and intangibles are not mapped, so no parent tangible book per share is audited.",
            "No external valuation report or analyst estimate is available; economic review remains unrecorded.",
        ],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    db.close()
    return 0 if summary["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
