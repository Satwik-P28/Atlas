"""Freeze the untouched external cohort, before any resolver runs on it.

This script does one thing: apply the committed selection rule to the committed candidate
universe and record the resulting filings. It fetches SEC metadata only (submissions), never
filing bodies, and it never parses a filing or produces an answer. Its output is the
pre-registration: seed, rule, accessions, filing dates and URLs, hashed as a whole so a later
change is visible.

A holdout that is selected after seeing resolver output is not a holdout. Re-running this script
is only meaningful when the universe, seed or rule change, and that change must be reported.

Requires ``ATLAS_SEC_USER_AGENT`` (SEC fair-access policy).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research.knowledge import absolute_document_url, sec_filings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "fixtures" / "answer_semantics" / "holdout_universe.json"
OUTPUT = ROOT / "fixtures" / "answer_semantics" / "holdout_plan.json"


def _rank(seed: str, cik: str) -> str:
    return hashlib.sha256(f"{seed}/{cik}".encode()).hexdigest()


def select(universe: dict[str, Any]) -> list[dict[str, Any]]:
    seed = universe["seed"]
    year = int(universe["target_fiscal_year"])
    excluded = {str(cik).lstrip("0").zfill(10) for cik in universe["excluded_development_ciks"]}
    ranked = sorted(
        (filing for filing in universe["candidates"]
         if str(filing["cik"]).lstrip("0").zfill(10) not in excluded),
        key=lambda filing: _rank(seed, str(filing["cik"]).lstrip("0").zfill(10)))
    chosen: list[dict[str, Any]] = []
    for filing in ranked:
        cik = str(filing["cik"]).lstrip("0").zfill(10)
        rows = sec_filings(cik, forms=["10-K"])
        match = next((row for row in rows
                      if str(row.get("period_of_report") or "")[:4] == str(year)), None)
        time.sleep(0.12)  # SEC fair-access pacing
        if match is None:
            print(f"skip {filing['name']}: no 10-K with a {year} period of report")
            continue
        chosen.append({
            "cik": cik,
            "issuer": filing["name"],
            "accession": match["accession"],
            "period_of_report": match.get("period_of_report"),
            "filed_date": match.get("filed_date"),
            "acceptance_time": match.get("acceptance_time"),
            "primary_document": match.get("primary_document"),
            "url": absolute_document_url(cik, match["accession"], match.get("primary_document")),
            "rank": _rank(seed, cik)[:16],
        })
        if len(chosen) == int(universe["selection_count"]):
            break
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", default=str(UNIVERSE))
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args(argv)
    universe = json.loads(Path(args.universe).read_text())
    if len(universe["candidates"]) < universe["selection_count"]:
        raise SystemExit("candidate universe is smaller than the selection count")
    chosen = select(universe)
    if len(chosen) < universe["selection_count"]:
        raise SystemExit(f"only {len(chosen)} eligible filings found; relax nothing silently")
    accessions = [item["accession"] for item in chosen]
    if len(set(accessions)) != len(accessions):
        raise SystemExit("duplicate accession in the selected cohort")
    plan = {
        "schema": "atlas.answer_semantics.holdout_plan.v1",
        "status": "selected_not_yet_ingested",
        "frozen_at": iso(utcnow()),
        "seed": universe["seed"],
        "target_fiscal_year": universe["target_fiscal_year"],
        "selection_rule": universe["rule"],
        "excluded_development_ciks": universe["excluded_development_ciks"],
        "candidates_considered": len(universe["candidates"]),
        "filings": chosen,
        "commitment": hashlib.sha256(
            json.dumps([item["accession"] for item in chosen]).encode()).hexdigest(),
        "protocol": {
            "authoring": ("Questions are written from printed statement geometry and SEC XBRL "
                          "company facts only. No resolver, evaluation harness or answer artifact "
                          "may be run against these filings before the gold file is frozen."),
            "gold": ("Each question records the printed cell (accession, row, column, raw text, "
                     "scale, period) and the same-accession XBRL fact; disagreement is recorded "
                     "as gold_inconsistent and excluded, never repaired."),
            "freeze": ("Gold and the question set are hashed and committed before the first "
                       "scoring run; that hash is the preregistration."),
            "reporting": ("One scoring run is reported in full, including false answers, "
                          "citation failures and refusals. Changing the protocol, questions or "
                          "gold after the run makes the cohort a development set."),
        },
        "instructions": ("Run scripts/answer_semantics_holdout_select.py only to re-freeze a "
                         "changed universe/seed/rule; ingesting and scoring this cohort is a "
                         "separate, later milestone."),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(plan, indent=2) + "\n")
    print(f"frozen {len(chosen)} filings; commitment {plan['commitment']}")
    for item in chosen:
        print(f"  {item['issuer']:45s} {item['accession']}  {item['period_of_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
