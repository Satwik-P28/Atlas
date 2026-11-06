#!/usr/bin/env python
"""Independent Phase 9.1 model audit.

Recomputes the bank residual-income and insurer justified-earnings results with a
separate Decimal implementation, checks that the industrial DCF remains rejected for a
financial institution, that a negative valuation is preserved, and that the packaged
institution application replays from a clean database. It does not call the production
valuation operators to produce its reference values.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from decimal import Decimal, getcontext
from pathlib import Path

from atlas.applications.service import ApplicationService
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database

getcontext().prec = 34
ROOT = Path(__file__).resolve().parents[1]


def _bank_reference(model: dict) -> dict:
    a = model["assumptions"]
    book = Decimal(str(model["outputs"].get("book_value_used", model["outputs"].get("book_value_common_equity"))))
    bv0 = book
    roe = Decimal(str(a["sustainable_roe"]))
    coe = Decimal(str(a["cost_of_equity"]))
    payout = Decimal(str(a["payout_ratio"]))
    terminal_growth = Decimal(str(a["terminal_growth"]))
    horizon = int(a["horizon"])
    pv = Decimal(0)
    for year in range(1, horizon + 1):
        net_income = roe * book
        residual = net_income - coe * book
        pv += residual / ((Decimal(1) + coe) ** year)
        book = book + net_income - net_income * payout
    terminal = (roe - coe) * book * (Decimal(1) + terminal_growth) / (coe - terminal_growth)
    pv_terminal = terminal / ((Decimal(1) + coe) ** horizon)
    equity = bv0 + pv + pv_terminal
    shares = Decimal(str(model["inputs"]["shares_outstanding"]))
    return {
        "equity_value": float(equity),
        "value_per_share": float(equity / shares),
        "pv_explicit": float(pv),
        "pv_terminal": float(pv_terminal),
        "terminal_value_share": float(pv_terminal / equity) if equity else None,
    }


def _insurer_reference(model: dict) -> dict:
    a = model["assumptions"]
    eps = Decimal(str(model["outputs"]["eps_diluted"]))
    eps_pe = Decimal(1) + Decimal(str(a["growth"]))
    coe = Decimal(str(a["cost_of_equity"]))
    payout = Decimal(str(a["payout_ratio"]))
    pe = payout * eps_pe / (coe - Decimal(1) + Decimal(1) - 0)  # placeholder replaced below
    growth = Decimal(str(a["growth"]))
    pe = payout * (Decimal(1) + growth) / (coe - growth)
    return {"justified_pe": float(pe), "value_per_share": float(eps * pe)}


def _rel_close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= max(1e-9, abs(right) * tolerance)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "var" / "phase9.db"))
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "phase9_1_model_audit.json"))
    args = parser.parse_args()

    db = Database(args.db)
    service = EquityResearchService(db)
    checks: list[dict] = []

    for ticker in ("JPM", "GS"):
        valuation = service.valuation(ticker)
        model = valuation["institution"]
        reference = _bank_reference(model)
        for key in ("equity_value", "value_per_share"):
            engine_key = "calculated_equity_value" if key == "equity_value" else key
            actual = float(model["outputs"][engine_key])
            checks.append({
                "ticker": ticker,
                "check": f"bank_residual_income_{key}",
                "reference": reference[key],
                "model": actual,
                "passed": _rel_close(reference[key], actual),
                "method": "independent Decimal residual-income loop",
            })
        checks.append({
            "ticker": ticker,
            "check": "dcf_rejected_for_financial_institution",
            "model": valuation["eligibility"].get("rejected_method"),
            "passed": valuation["eligibility"].get("rejected_method") == "unlevered_fcff_dcf",
        })
        checks.append({
            "ticker": ticker,
            "check": "contract_not_promoted_to_economic_support",
            "model": valuation["contract"]["state"],
            "passed": valuation["contract"]["state"] == "arithmetically_verified" and not valuation["economically_supported"],
        })

    insurer = service.valuation("UNH")
    reference = _insurer_reference(insurer["institution"])
    for key in ("justified_pe", "value_per_share"):
        actual = float(insurer["institution"]["outputs"][key])
        checks.append({
            "ticker": "UNH",
            "check": f"insurer_{key}",
            "reference": reference[key],
            "model": actual,
            "passed": _rel_close(reference[key], actual),
            "method": "independent justified-earnings identity",
        })
    checks.append({
        "ticker": "UNH",
        "check": "insurer_partial_disclosure",
        "model": insurer["institution"]["partial"],
        "passed": insurer["institution"]["partial"] is True,
    })

    amazon = service.valuation("AMZN")
    checks.append({
        "ticker": "AMZN",
        "check": "negative_dcf_preserved",
        "model": amazon["dcf"]["outputs"]["value_per_share"],
        "passed": amazon["dcf"]["outputs"]["value_per_share"] < 0,
    })

    for ticker in ("JPM", "UNH"):
        package = service.create_package(ticker)
        again = service.create_package(ticker)
        checks.append({
            "ticker": ticker,
            "check": "package_deterministic",
            "model": package["package_sha256"][:16],
            "passed": package["package_sha256"] == again["package_sha256"],
        })
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp) / "clean.db"
            shutil.copy(args.db, clean)
            clean_db = Database(str(clean))
            clean_db.execute("DELETE FROM application_installation")
            clean_db.execute("DELETE FROM research_object_evidence")
            clean_db.execute("DELETE FROM research_object")
            clean_service = EquityResearchService(clean_db)
            installed = ApplicationService(clean_db).install(package["payload"])
            execution = ApplicationService(clean_db).execute(installed["install_id"])
            checks.append({
                "ticker": ticker,
                "check": "package_replays_from_clean_db",
                "model": execution.get("status"),
                "passed": execution.get("status") == "reproduced" and not execution.get("differences"),
            })
            clean_db.close()

    passed = all(check["passed"] for check in checks)
    payload = {
        "schema": "atlas.phase9_1.model_audit.v1",
        "db": str(args.db),
        "status": "pass" if passed else "fail",
        "checks": checks,
        "counts": {"total": len(checks), "passed": sum(1 for c in checks if c["passed"])},
        "limits": [
            "The bank and insurer reference implementations share the same documented inputs; agreement proves arithmetic, not the economic validity of the assumptions.",
            "Call Report, FDIC and CMS data are not joined; only consolidated SEC facts are used.",
            "No market prices are bundled, so price-based and reverse-DCF checks are unavailable for this universe.",
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "counts": payload["counts"]}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
