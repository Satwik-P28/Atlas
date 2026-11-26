"""Audit the committed holdout selection without reselecting anything.

Offline checks recompute the committed selection rule, its commitment hash, development-set
overlap, accession shape and the fiscal-calendar assumption. ``--network`` additionally
compares every planned accession, filing date, acceptance time and primary document with SEC
submissions metadata (metadata only; no filing body is fetched, parsed or scored).

Findings are recorded with a severity. ``error`` means the cohort cannot be scored as declared;
``warning`` is a limitation that must be reported but does not change the selection. Nothing in
this script may replace an issuer or an accession.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "answer_semantics"
PLAN = FIXTURES / "holdout_plan.json"
UNIVERSE = FIXTURES / "holdout_universe.json"
DEV_CORPUS = FIXTURES / "corpus.json"
DEV_QUESTIONS = FIXTURES / "questions.json"
OUT = ROOT / "artifacts" / "answer_semantics" / "holdout_selection_audit.json"

ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _norm_cik(value: str) -> str:
    return str(value).lstrip("0").zfill(10)


def _rank(seed: str, cik: str) -> str:
    return hashlib.sha256(f"{seed}/{cik}".encode()).hexdigest()


def audit_offline() -> list[dict[str, Any]]:
    plan = _load(PLAN)
    universe = _load(UNIVERSE)
    dev_corpus = _load(DEV_CORPUS)
    dev_questions = _load(DEV_QUESTIONS)
    findings: list[dict[str, Any]] = []

    def add(code: str, severity: str, detail: str, evidence: Any = None) -> None:
        findings.append({"code": code, "severity": severity, "detail": detail,
                         "evidence": evidence})

    candidates = universe["candidates"]
    add("universe_size", "info", f"{len(candidates)} candidates declared",
        {"candidates": len(candidates), "selection_count": universe["selection_count"]})
    if len(candidates) != len({_norm_cik(c["cik"]) for c in candidates}):
        add("universe_duplicate_cik", "error", "the candidate universe repeats a CIK")

    filings = plan["filings"]
    accessions = [item["accession"] for item in filings]
    ciks = [_norm_cik(item["cik"]) for item in filings]
    if len(filings) != int(universe["selection_count"]):
        add("selection_size", "error",
            f"plan holds {len(filings)} filings but the universe declares {universe['selection_count']}")
    if len(set(accessions)) != len(accessions):
        add("duplicate_accession", "error", "the plan repeats an accession", accessions)
    if len(set(ciks)) != len(ciks):
        add("duplicate_issuer", "error", "the plan repeats an issuer", ciks)
    bad_shape = [item["accession"] for item in filings if not ACCESSION.match(item["accession"])]
    if bad_shape:
        add("accession_shape", "error", "accession does not match the EDGAR form", bad_shape)

    expected_commitment = hashlib.sha256(json.dumps(accessions).encode()).hexdigest()
    if plan.get("commitment") != expected_commitment:
        add("commitment_mismatch", "error", "the plan commitment does not hash its accession list",
            {"recorded": plan.get("commitment"), "recomputed": expected_commitment})

    seed = universe["seed"]
    recomputed = {_norm_cik(item["cik"]): _rank(seed, _norm_cik(item["cik"]))[:16]
                  for item in filings}
    mismatched = {item["cik"]: {"recorded": item.get("rank"), "recomputed": recomputed[_norm_cik(item["cik"])]}
                  for item in filings if item.get("rank") != recomputed[_norm_cik(item["cik"])]}
    if mismatched:
        add("rank_mismatch", "error", "a recorded rank does not match sha256(seed/cik)", mismatched)
    ranks = [recomputed[_norm_cik(item["cik"])] for item in filings]
    if ranks != sorted(ranks):
        add("rank_order", "error", "the selected filings are not in ascending rank order", ranks)

    excluded = {_norm_cik(cik) for cik in plan["excluded_development_ciks"]}
    dev_ciks = {_norm_cik(item["cik"]) for item in dev_corpus["filings"]}
    dev_ciks |= {_norm_cik(item["issuer_cik"]) for item in dev_questions["questions"]}
    if excluded != dev_ciks:
        add("exclusion_set_drift", "warning",
            "the frozen exclusion set is not exactly the development corpus issuer set",
            {"frozen_only": sorted(excluded - dev_ciks), "development_only": sorted(dev_ciks - excluded)})
    overlap = sorted(set(ciks) & dev_ciks)
    if overlap:
        add("development_overlap", "error", "a holdout issuer also appears in the development set",
            overlap)
    if set(ciks) - {_norm_cik(item["cik"]) for item in candidates}:
        add("outside_universe", "error", "the plan selected an issuer outside the frozen universe")

    target = int(universe["target_fiscal_year"])
    off_year = [item["accession"] for item in filings
                if str(item.get("period_of_report"))[:4] != str(target)]
    if off_year:
        add("period_year_mismatch", "error", "a filing's period end is outside the target year", off_year)

    # The rule keys on the calendar year of the period end. Issuers with a January-May year end
    # label that year differently, so the cohort is *not* twelve issuer-labelled fiscal-2022
    # filings. This is a protocol caveat, not a reselection trigger.
    non_calendar = [{"accession": item["accession"], "issuer": item["issuer"],
                     "period_of_report": item["period_of_report"]}
                    for item in filings if item["period_of_report"][5:7] in {"01", "02", "03", "04", "05"}]
    if non_calendar:
        add("fiscal_label_caveat", "warning",
            "the selection rule uses the calendar year of the period end, not the issuer's "
            "fiscal-year label; a late-January/spring period end can be labelled with the prior "
            "fiscal year by its issuer. Questions must state the period end.",
            non_calendar)

    planned_primary = [item.get("primary_document") for item in filings]
    if any(not name for name in planned_primary):
        add("missing_primary_document", "error", "the plan does not name a primary document")

    add("protocol_scope", "info",
        "both arms receive identical accessions, question text and cutoff dates; the development "
        "corpus is a disjoint issuer set and stays development-only.", {"development_ciks": len(dev_ciks)})
    return findings


def _fetch_json(url: str, user_agent: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed sec.gov host
        return json.loads(response.read().decode("utf-8"))


def _submissions(cik: str, user_agent: str) -> dict[str, Any]:
    return _fetch_json(f"https://data.sec.gov/submissions/CIK{_norm_cik(cik)}.json", user_agent)


def _all_rows(cik: str, user_agent: str) -> dict[str, list[Any]]:
    """Recent filings plus the paginated overflow files, as parallel column lists."""
    payload = _submissions(cik, user_agent)
    filings = payload.get("filings", {})
    columns: dict[str, list[Any]] = {key: list(value) for key, value in
                                    (filings.get("recent") or {}).items()
                                    if isinstance(value, list)}
    for extra in filings.get("files") or []:
        name = extra.get("name")
        if not name:
            continue
        page = _fetch_json(f"https://data.sec.gov/submissions/{name}", user_agent)
        for key, value in page.items():
            if isinstance(value, list):
                columns.setdefault(key, []).extend(value)
    return columns


def audit_network() -> list[dict[str, Any]]:
    user_agent = (os.environ.get("ATLAS_SEC_USER_AGENT") or "").strip()
    if not user_agent:
        raise SystemExit("ATLAS_SEC_USER_AGENT must be set for --network (SEC fair access)")
    plan = _load(PLAN)
    findings: list[dict[str, Any]] = []
    for filing in plan["filings"]:
        rows = _all_rows(filing["cik"], user_agent)
        found = None
        for index, accession in enumerate(rows.get("accessionNumber", [])):
            if accession == filing["accession"]:
                found = {key: rows[key][index] for key in rows if isinstance(rows[key], list)
                         and index < len(rows[key])}
                break
        if found is None:
            findings.append({"code": "accession_not_in_submissions", "severity": "error",
                             "detail": f"{filing['accession']} is not in the issuer's recent filings",
                             "evidence": filing["issuer"]})
            continue
        differences = {}
        for planned, observed, key in (
                (filing.get("filed_date"), found.get("filingDate"), "filed_date"),
                (filing.get("primary_document"), found.get("primaryDocument"), "primary_document"),
                (filing.get("period_of_report"), found.get("reportDate"), "period_of_report")):
            if planned != observed:
                differences[key] = {"planned": planned, "sec_submissions": observed}
        if str(found.get("form", "")).upper() not in {"10-K", "10-K/A"}:
            differences["form"] = {"planned": "10-K", "sec_submissions": found.get("form")}
        if differences:
            findings.append({"code": "metadata_discrepancy", "severity": "error",
                             "detail": f"{filing['issuer']} metadata disagrees with SEC submissions",
                             "evidence": {"accession": filing["accession"], "differences": differences}})
        planned_acceptance = str(filing.get("acceptance_time") or "").replace(".000Z", "Z")
        observed_acceptance = str(found.get("acceptanceDateTime") or "").replace(".000Z", "Z")
        if planned_acceptance and observed_acceptance and planned_acceptance != observed_acceptance:
            findings.append({"code": "acceptance_time_discrepancy", "severity": "warning",
                             "detail": f"{filing['issuer']} acceptance time differs in precision",
                             "evidence": {"planned": planned_acceptance,
                                          "sec_submissions": observed_acceptance}})
        if planned_acceptance[:10] > str(filing.get("filed_date")):
            findings.append({"code": "acceptance_after_filed_date", "severity": "warning",
                             "detail": ("acceptance UTC timestamp falls on the day before the EDGAR "
                                        "filing date; recorded as EDGAR reports it, not corrected"),
                             "evidence": {"accession": filing["accession"],
                                          "acceptance": planned_acceptance,
                                          "filed_date": filing.get("filed_date")}})
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--network", action="store_true",
                        help="also verify the plan against SEC submissions metadata")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    findings = audit_offline()
    if args.network:
        findings.extend(audit_network())
    errors = [item for item in findings if item["severity"] == "error"]
    warnings = [item for item in findings if item["severity"] == "warning"]
    payload = {
        "schema": "atlas.answer_semantics.holdout_selection_audit.v1",
        "plan_commitment": _load(PLAN).get("commitment"),
        "network": bool(args.network),
        "findings": findings,
        "errors": len(errors),
        "warnings": len(warnings),
        "selection_changed": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    for item in findings:
        print(f"[{item['severity']:7s}] {item['code']}: {item['detail']}")
    print(f"errors={len(errors)} warnings={len(warnings)} artifact={out}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
