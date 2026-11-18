"""A real, publicly documented evidence revision, compiled by the CRI machinery.

This is the case study the research plan asks for: an authentic, timestamped revision from a
public filing archive, carried through Atlas's revision compiler and certificate, with source
identifiers, acceptance timestamps and content hashes preserved.

What the case *is*
------------------
Pfizer's FY2023 revenue appears twice in the SEC's XBRL company-facts archive:

* ``58,496,000,000`` in the FY2023 Form 10-K, accession ``0000078003-24-000039``, accepted
  ``2024-02-22T18:17:37Z``;
* ``59,553,000,000`` for the *same* fiscal year in the FY2024 Form 10-K, accession
  ``0000078003-25-000054``, accepted ``2025-02-27T21:27:18Z``.

The second figure is the comparative column of a later annual report, i.e. a restatement of the
prior year rather than an amendment on Form 10-K/A. Both values, forms, accession numbers and
acceptance instants are read from the archive at run time and checked against these constants;
nothing is typed in by hand.

What the case *is not*
----------------------
The decision model is a **stylised three-line allocation** in which the only evidence-linked
coefficient is the revenue forecast of one line. The other coefficients, the risk matrix and the
budget are model parameters with no claim to empirical validity, and the mapping from a revenue
restatement to an expected-return change is a *declared* sensitivity of ``-1/1000`` per dollar
of revenue. This case study demonstrates that a real revision can be dated, identified and
compiled with the same eligibility rules as the synthetic experiments. It does **not** audit a
real portfolio, and it says nothing about realized returns.

Run::

    .venv/bin/python scripts/research/sec_evidence_case.py --output artifacts/research/evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from atlas.decision.certificate import certify_revision_impact
from atlas.decision.experiment import write_json
from atlas.decision.problem import mean_variance_problem
from atlas.decision.qp import solve
from atlas.decision.reference import solve_osqp
from atlas.decision.revision import EvidenceRevision, InputSensitivity, compile_revisions

USER_AGENT = "Atlas research prototype (contact: satwik@example.com)"
CIK = "0000078003"
COMPANY = "PFIZER INC"
CONCEPT = "Revenues"
PERIOD = "2023-01-01"
BASE_PERIOD = "2022-01-01"
PERIOD_END = "2023-12-31"
BASE_PERIOD_END = "2022-12-31"

ORIGINAL_ACCESSION = "0000078003-24-000039"
RESTATED_ACCESSION = "0000078003-25-000054"

#: The model input is the *reported revenue growth rate* for FY2023 against FY2022, and the
#: declared mapping from that growth rate to the first line's expected return is ``0.1``. Both
#: numbers are modelling assumptions, stated here rather than buried in the code: a growth rate
#: is a more defensible input than a revenue level, and the 0.1 keeps the three lines on
#: comparable scales so the allocation is not trivially pinned to one cap.
GROWTH_SCALE = 0.1

#: The decision was taken after the original annual report and before the restatement.
DECISION_CLOCK = "2024-06-30T20:00:00Z"
#: The audit is run after the restated comparative was accepted.
AUDIT_CLOCK = "2025-03-01T12:00:00Z"

URLS = {
    "concept": f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK}/us-gaap/{CONCEPT}.json",
    "submissions": f"https://data.sec.gov/submissions/CIK{CIK}.json",
}


def fetch(url: str, cache: Path) -> tuple[bytes, str, bool]:
    """Return ``(payload, sha256, from_cache)``, caching the exact bytes for offline replay."""

    if cache.exists():
        payload = cache.read_bytes()
        from_cache = True
    else:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310 - fixed host
            payload = response.read()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(payload)
        from_cache = False
    return payload, hashlib.sha256(payload).hexdigest(), from_cache


def extract_revenue(payload: bytes) -> dict[str, Any]:
    """Every annual ``Revenues`` figure for the two periods of interest, keyed by accession."""

    document = json.loads(payload)
    wanted = {(PERIOD, PERIOD_END), (BASE_PERIOD, BASE_PERIOD_END)}
    matches = []
    for unit, facts in document.get("units", {}).items():
        if unit != "USD":
            continue
        for fact in facts:
            if (fact.get("start"), fact.get("end")) not in wanted:
                continue
            if fact.get("form") not in {"10-K", "10-K/A"}:
                continue
            matches.append({
                "value": float(fact["val"]),
                "period_start": fact["start"],
                "period_end": fact["end"],
                "form": fact["form"],
                "accession": fact["accn"],
                "filed": fact["filed"],
                "fy": fact.get("fy"),
                "fp": fact.get("fp"),
            })
    return {"entity": document.get("entityName"), "concept": document.get("tag"),
            "facts": sorted(matches, key=lambda item: (item["filed"], item["period_end"]))}


def extract_acceptance(payload: bytes, accessions: set[str]) -> dict[str, dict[str, Any]]:
    document = json.loads(payload)
    recent = document["filings"]["recent"]
    found: dict[str, dict[str, Any]] = {}
    for index, accession in enumerate(recent["accessionNumber"]):
        if accession in accessions:
            found[accession] = {
                "form": recent["form"][index],
                "filing_date": recent["filingDate"][index],
                "acceptance": recent["acceptanceDateTime"][index],
                "primary_document": recent["primaryDocument"][index],
                "report_date": recent["reportDate"][index],
                "filing_url": (f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/"
                               f"{accession.replace('-', '')}/{recent['primaryDocument'][index]}"),
            }
    return found


def build_problem(growth: float):
    """A stylised three-line allocation whose first coefficient is the revenue growth rate."""

    covariance = np.array([
        [0.0400, 0.0040, 0.0020],
        [0.0040, 0.0300, 0.0030],
        [0.0020, 0.0030, 0.0200],
    ])
    expected = np.array([growth * GROWTH_SCALE, 0.055, 0.040])
    return mean_variance_problem(
        problem_id=f"sec-{CIK}-fy2023",
        assets=("PFE-REVENUE-LINE", "LINE-B", "LINE-C"),
        expected_returns=expected,
        covariance=covariance,
        risk_aversion=3.0,
        lower=0.0,
        upper=0.8,
        budget=1.0,
        as_of=DECISION_CLOCK,
        evidence_ids=(ORIGINAL_ACCESSION,),
        labels={
            "evidence": "SEC XBRL companyconcept us-gaap:Revenues",
            "model": "stylised_three_line_allocation",
            "assumption": "revenue maps linearly to the objective coefficient at 1/1000",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/research/evidence")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    concept_payload, concept_hash, concept_cached = fetch(URLS["concept"], output / "concept.json")
    submissions_payload, submissions_hash, submissions_cached = fetch(
        URLS["submissions"], output / "submissions.json")

    revenue = extract_revenue(concept_payload)
    acceptance = extract_acceptance(submissions_payload,
                                    {ORIGINAL_ACCESSION, RESTATED_ACCESSION})
    by_key = {(fact["accession"], fact["period_end"]): fact for fact in revenue["facts"]}
    original = by_key[(ORIGINAL_ACCESSION, PERIOD_END)]
    base = by_key[(ORIGINAL_ACCESSION, BASE_PERIOD_END)]
    restated = by_key[(RESTATED_ACCESSION, PERIOD_END)]
    if original["value"] == restated["value"]:  # pragma: no cover - guards the archive
        raise SystemExit("the archive no longer shows two distinct values for this period")

    growth_original = original["value"] / base["value"] - 1.0
    growth_restated = restated["value"] / base["value"] - 1.0
    delta_growth = growth_restated - growth_original
    problem = build_problem(growth_original)
    decision = solve(problem)
    revision = EvidenceRevision(
        revision_id=f"pfe-fy2023-revenue-growth-restated-{RESTATED_ACCESSION}",
        evidence_id=RESTATED_ACCESSION,
        input_key="pfe_fy2023_revenue_growth",
        delta=delta_growth,
        available_at=acceptance[RESTATED_ACCESSION]["acceptance"],
        kind="linear_objective",
        source_id=f"SEC 10-K {RESTATED_ACCESSION}",
        note=("FY2023 revenue as reported in the FY2024 annual report's comparative column, "
              "replacing the figure first filed in the FY2023 annual report; the model input "
              "is the implied growth rate against FY2022"),
    )
    sensitivity = InputSensitivity(
        input_key="pfe_fy2023_revenue_growth",
        cost_effect=(-GROWTH_SCALE, 0.0, 0.0),
        note="declared: the objective minimises -growth*0.1 on the first line",
    )

    # The ordinary audit: eligible at the audit clock, published after the decision clock.
    compilation = compile_revisions(problem, [revision], [sensitivity],
                                    audit_as_of=AUDIT_CLOCK,
                                    starting_vintage="fy2023-10K-vintage")
    reference = solve_osqp(compilation.problem)
    internal_reference = solve(compilation.problem)
    certificate = certify_revision_impact(problem, decision.weights, compilation,
                                          decision_dual=decision.dual)
    # Regret can never be negative; if a reference solver returns a worse objective than the
    # recorded decision the solver, not the decision, is at fault. Take the best available
    # optimum and record both so the discrepancy stays visible.
    best_optimal = min(float(reference.objective), float(internal_reference.objective))
    realized = max(0.0, float(compilation.problem.objective(np.asarray(decision.weights))
                             - best_optimal))

    # The double-count guard: the same revision re-offered for a decision taken *after* it was
    # published must be treated as already incorporated, not applied again.
    later_problem = problem.replace(as_of="2025-06-30T20:00:00Z")
    reincorporated = compile_revisions(later_problem, [revision], [sensitivity],
                                      audit_as_of="2025-09-30T12:00:00Z",
                                      starting_vintage="fy2024-10K-vintage")

    # And the archived-but-not-yet-public case: an audit run before the restatement existed.
    early = compile_revisions(problem, [revision], [sensitivity],
                             audit_as_of="2025-01-15T12:00:00Z",
                             starting_vintage="fy2023-10K-vintage")

    results: dict[str, Any] = {
        "schema": "atlas.research.sec_evidence_case.v1",
        "generated_by": "scripts/research/sec_evidence_case.py",
        "source": {
            "company": revenue["entity"] or COMPANY,
            "cik": CIK,
            "concept": revenue["concept"],
            "unit": "USD",
            "period": {"start": PERIOD, "end": "2023-12-31"},
            "urls": URLS,
            "content_sha256": {"concept": concept_hash, "submissions": submissions_hash},
            "served_from_cache": {"concept": concept_cached, "submissions": submissions_cached},
            "user_agent": USER_AGENT,
        },
        "revision": {
            "original": {**original, **acceptance[ORIGINAL_ACCESSION]},
            "restated": {**restated, **acceptance[RESTATED_ACCESSION]},
            "base_period": {**base, "url": URLS["concept"]},
            "growth_original": growth_original,
            "growth_restated_in_later_filing": growth_restated,
            "delta_growth": delta_growth,
            "delta_revenue_usd": restated["value"] - original["value"],
            "relative_change": (restated["value"] - original["value"]) / original["value"],
            "compiled_revision": revision.as_dict(),
            "declared_sensitivity": sensitivity.as_dict(),
        },
        "model": {
            "kind": "stylised_three_line_allocation",
            "disclaimer": ("the risk matrix, the other two coefficients and the budget are model "
                           "parameters; only the first coefficient is evidence-linked"),
            "problem": problem.as_dict(),
            "decision_weights": list(decision.weights),
            "decision_objective": decision.objective,
            "decision_status": decision.status,
        },
        "audit": {
            "decision_as_of": DECISION_CLOCK,
            "audit_as_of": AUDIT_CLOCK,
            "temporal_relationship": certificate.temporal_relationship,
            "verdict": certificate.verdict,
            "reference_objective_osqp": float(reference.objective),
            "reference_objective_internal": float(internal_reference.objective),
            "reference_status_osqp": reference.status,
            "exact_optimal_for_revised_program": certificate.exact["optimal_for_revised_program"],
            "numerical_regret_bound": certificate.exact["numerical_regret_bound"],
            "regret_upper_bound": certificate.bounded["regret_upper_bound"],
            "realized_regret_external_solver": realized,
            "bound_sound": bool(certificate.bounded["regret_upper_bound"] is not None and
                                certificate.bounded["regret_upper_bound"] + 1e-12 >= realized),
            "lineage": [dict(item) for item in compilation.lineage],
            "cost_effect_applied": list(compilation.delta_cost),
        },
        "controls": {
            "double_count_guard": {
                "purpose": "re-offering a revision published before the decision clock",
                "status": reincorporated.status,
                "applied": [item.revision_id for item in reincorporated.applied],
                "excluded_reasons": [item["reason"] for item in reincorporated.excluded],
                "temporal_relationship": None,
            },
            "not_yet_public": {
                "purpose": "an audit run before the restatement was accepted",
                "status": early.status,
                "applied": [item.revision_id for item in early.applied],
                "excluded_reasons": [item["reason"] for item in early.excluded],
            },
        },
        "limitations": [
            "one restatement of one line; no portfolio-level conclusion follows",
            "the revenue-to-coefficient mapping is declared, not estimated",
            "the second and third lines of the model are illustrative parameters",
            "a comparative-column restatement is not an enforcement action or a fraud finding",
        ],
    }
    write_json(output / "sec_evidence_case.json", results)

    lines = [
        "# Real-evidence case study: an SEC revenue restatement",
        "",
        "Generated by `scripts/research/sec_evidence_case.py`. Source documents are cached next to",
        "this file with their SHA-256 digests.",
        "",
        f"**{results['source']['company']}** (CIK {CIK}), `us-gaap:Revenues`, FY2023.",
        "",
        "| | original | restated |",
        "|---|---|---|",
        f"| value (USD) | {original['value']:,.0f} | {restated['value']:,.0f} |",
        f"| form | {original['form']} | {restated['form']} |",
        f"| accession | {ORIGINAL_ACCESSION} | {RESTATED_ACCESSION} |",
        f"| accepted | {acceptance[ORIGINAL_ACCESSION]['acceptance']} | "
        f"{acceptance[RESTATED_ACCESSION]['acceptance']} |",
        "",
        f"Relative change: {results['revision']['relative_change']:.4%}. Compiled cost "
        f"perturbation: {results['audit']['cost_effect_applied']}.",
        "",
        "## Audit",
        "",
        f"- decision clock {DECISION_CLOCK}, audit clock {AUDIT_CLOCK}",
        f"- temporal relationship: `{certificate.temporal_relationship}`",
        f"- verdict: `{certificate.verdict}`",
        f"- certified regret bound: {certificate.bounded['regret_upper_bound']}",
        f"- realized regret (OSQP reference): {realized:.3e}",
        f"- bound sound: {results['audit']['bound_sound']}",
        "",
        "## Controls",
        "",
        f"- re-offered after the decision clock: status `{reincorporated.status}`, "
        f"excluded because {[item['reason'] for item in reincorporated.excluded]}",
        f"- audited before the restatement was accepted: status `{early.status}`, "
        f"excluded because {[item['reason'] for item in early.excluded]}",
        "",
        "## What this does not show",
        "",
    ]
    for limitation in results["limitations"]:
        lines.append(f"- {limitation}")
    (output / "sec_evidence_case.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: results["audit"][key] for key in
                      ("verdict", "temporal_relationship", "regret_upper_bound", "bound_sound")},
                     indent=2, default=float))
    print("wrote", output / "sec_evidence_case.json")


if __name__ == "__main__":
    main()
