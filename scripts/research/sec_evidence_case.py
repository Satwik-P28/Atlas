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

The second figure is the comparative column of a later annual report -- a *revision of a previously
reported number*, which is the only fact the archive establishes on its own. Whether such a
revision is a formal restatement is a separate, checkable question, and an earlier version of this
script simply asserted that it was. It is not. Both primary documents leave Item 9C ("do the
financial statements reflect the correction of an error") unchecked, and the FY2024 document says
why the figure moved:

    In the first quarter of 2024, we reclassified royalty income ... from Other
    (income)/deductions--net and began presenting Royalty revenues as a separate line item within
    Total revenues ... Prior-period amounts have been recast to conform to the current
    presentation.

So the ``+1,057`` million is royalty income moved into ``Total revenues`` and the comparative
column recast to follow, not an error correction. In accounting terms this is a reclassification
disclosed under a change in presentation (ASC 220/280), not a restatement under ASC 250, and no
Form 10-K/A was filed. The classification below is *derived* from the two documents at run time --
the Item 9C checkbox state and the disclosure sentences are recorded with their hashes -- so a
future archive change would show up as a changed verdict rather than a stale caption.

Both values, forms, accession numbers, primary-document digests and acceptance instants are read
from the archive at run time and checked against these constants; nothing is typed in by hand.

What the case *is not*
----------------------
The decision model is a **stylised three-line allocation** in which the only evidence-linked
coefficient is the revenue forecast of one line. The other coefficients, the risk matrix and the
budget are model parameters with no claim to empirical validity, and the mapping from a revenue
revision to an expected-return change is a *declared* sensitivity of ``-1/1000`` per dollar
of revenue. Nothing here interprets the reclassification as a signal about Pfizer's prospects; the
point is that the compiler dates, filters and prices a real documented revision correctly. This case study demonstrates that a real revision can be dated, identified and
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
LATER_ACCESSION = "0000078003-25-000054"

#: The sentence Item 9C of Form 10-K asks, followed by its checkbox. Unchecked means the filer does
#: not report the statements as reflecting a correction of an error.
ERROR_CORRECTION_ITEM = "correction of an error to previously issued financial statements"

#: Disclosure language that distinguishes a conforming recast from an error correction.
RECAST_MARKERS = ("recast to conform", "reclassified royalty income",
                  "will restate prior periods for consistency")

#: The model input is the *reported revenue growth rate* for FY2023 against FY2022, and the
#: declared mapping from that growth rate to the first line's expected return is ``0.1``. Both
#: numbers are modelling assumptions, stated here rather than buried in the code: a growth rate
#: is a more defensible input than a revenue level, and the 0.1 keeps the three lines on
#: comparable scales so the allocation is not trivially pinned to one cap.
GROWTH_SCALE = 0.1

#: The decision was taken after the original annual report and before the recast.
DECISION_CLOCK = "2024-06-30T20:00:00Z"
#: The audit is run after the recast comparative was accepted.
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


def plain_text(payload: bytes) -> str:
    """Primary-document text with tags stripped, for disclosure inspection only."""

    import html as _html
    import re as _re

    text = _re.sub(r"<[^>]+>", " ", payload.decode("utf-8", errors="ignore"))
    return _re.sub(r"\s+", " ", _html.unescape(text))


def characterize_documents(original_payload: bytes, later_payload: bytes) -> dict[str, Any]:
    """Derive what kind of revision this is from the two primary documents themselves.

    Two independent signals, both recorded verbatim:

    * the Item 9C checkbox -- checked only when the filer reports the statements as reflecting a
      correction of an error, which is the formal definition of a restatement;
    * disclosure language about recasting comparatives to conform to a new presentation.

    The verdict is ``error_correction`` only if the checkbox is checked. Otherwise a recast
    disclosure makes it a ``conforming_recast``; with neither signal the case is reported as an
    ``unexplained_revision`` and no accounting interpretation is offered, because the documents
    would not support one.
    """

    signals: dict[str, Any] = {}
    for label, payload in (("original", original_payload), ("later", later_payload)):
        text = plain_text(payload)
        index = text.lower().find(ERROR_CORRECTION_ITEM)
        window = text[index:index + 400] if index >= 0 else ""
        after = window.split("statements.", 1)[1][:8] if "statements." in window else ""
        checked = "\u2612" in after or "\u2611" in after
        quotes = [sentence for sentence in
                  (" ".join(segment.split()) for segment in text.replace("?", ".").split("."))
                  if any(marker.lower() in sentence.lower() for marker in RECAST_MARKERS)]
        signals[label] = {
            "item_9c_sentence_found": bool(index >= 0),
            "item_9c_glyph_after_sentence": after.strip(),
            "error_correction_checkbox_checked": bool(checked),
            "recast_disclosures": quotes[:4],
        }

    error_correction = any(item["error_correction_checkbox_checked"] for item in signals.values())
    recast = any(item["recast_disclosures"] for item in signals.values())
    if error_correction:
        characterization = "error_correction"
    elif recast:
        characterization = "conforming_recast"
    else:
        characterization = "unexplained_revision"
    return {
        "characterization": characterization,
        "formal_restatement": error_correction,
        "error_correction_reported": error_correction,
        "conforming_recast_disclosed": recast,
        "signals": signals,
        "method": ("Item 9C checkbox state plus recast disclosures read from both primary "
                   "documents at run time; no classification is typed in"),
        "accounting_note": (
            "A recast of comparative periods to follow a new presentation is a reclassification "
            "disclosure, not a restatement of previously issued financial statements; "
            "it does not by itself indicate an error, and no Form 10-K/A was filed for FY2023"
        ),
    }


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
                                    {ORIGINAL_ACCESSION, LATER_ACCESSION})

    # The primary documents are fetched and hashed so the accounting characterisation below is
    # auditable from the archive, not asserted by this script.
    documents: dict[str, Any] = {}
    payloads: dict[str, bytes] = {}
    for role, accession in (("original", ORIGINAL_ACCESSION), ("later", LATER_ACCESSION)):
        filing = acceptance[accession]
        payload, digest, cached = fetch(filing["filing_url"],
                                        output / str(filing["primary_document"]))
        payloads[role] = payload
        documents[role] = {
            "accession": accession,
            "form": filing["form"],
            "primary_document": filing["primary_document"],
            "url": filing["filing_url"],
            "sha256": digest,
            "bytes": len(payload),
            "served_from_cache": cached,
        }
    characterization = characterize_documents(payloads["original"], payloads["later"])

    by_key = {(fact["accession"], fact["period_end"]): fact for fact in revenue["facts"]}
    original = by_key[(ORIGINAL_ACCESSION, PERIOD_END)]
    base = by_key[(ORIGINAL_ACCESSION, BASE_PERIOD_END)]
    later_filing = by_key[(LATER_ACCESSION, PERIOD_END)]
    if original["value"] == later_filing["value"]:  # pragma: no cover - guards the archive
        raise SystemExit("the archive no longer shows two distinct values for this period")

    growth_original = original["value"] / base["value"] - 1.0
    growth_later = later_filing["value"] / base["value"] - 1.0
    delta_growth = growth_later - growth_original
    problem = build_problem(growth_original)
    decision = solve(problem)
    revision = EvidenceRevision(
        revision_id=f"pfe-fy2023-revenue-growth-recast-{LATER_ACCESSION}",
        evidence_id=LATER_ACCESSION,
        input_key="pfe_fy2023_revenue_growth",
        delta=delta_growth,
        available_at=acceptance[LATER_ACCESSION]["acceptance"],
        kind="linear_objective",
        source_id=f"SEC 10-K {LATER_ACCESSION}",
        version=2,
        note=("FY2023 revenue as recast in the FY2024 annual report's comparative column after "
              "royalty income was reclassified into Total revenues, replacing the figure first "
              "filed in the FY2023 annual report; the model input is the implied growth rate "
              "against FY2022. A conforming recast, not an error correction"),
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

    # And the archived-but-not-yet-public case: an audit run before the recast existed.
    early = compile_revisions(problem, [revision], [sensitivity],
                             audit_as_of="2025-01-15T12:00:00Z",
                             starting_vintage="fy2023-10K-vintage")

    results: dict[str, Any] = {
        "schema": "atlas.research.sec_evidence_case.v1",
        "generated_by": "scripts/research/sec_evidence_case.py",
        "characterization": {
            **characterization,
            "what_changed": (
                "beginning in 2024 Pfizer presents royalty income within Total revenues instead "
                "of Other (income)/deductions--net, and recast prior-period comparatives to "
                "follow; the FY2023 comparative therefore exceeds the FY2023 as-filed figure by "
                "the reclassified royalty amount"),
            "what_it_is_not": (
                "not an error correction, not a restatement under ASC 250, not a Form 10-K/A, "
                "not an enforcement action, and not evidence about Pfizer's performance"),
        },
        "documents": documents,
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
            "later_filing": {**later_filing, **acceptance[LATER_ACCESSION]},
            "base_period": {**base, "url": URLS["concept"]},
            "growth_original": growth_original,
            "growth_in_later_filing": growth_later,
            "delta_growth": delta_growth,
            "delta_revenue_usd": later_filing["value"] - original["value"],
            "relative_change": (later_filing["value"] - original["value"]) / original["value"],
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
                "purpose": "an audit run before the recast was accepted",
                "status": early.status,
                "applied": [item.revision_id for item in early.applied],
                "excluded_reasons": [item["reason"] for item in early.excluded],
            },
        },
        "limitations": [
            "one reclassification of one line; no portfolio-level conclusion follows",
            "the revenue-to-coefficient mapping is declared, not estimated",
            "the second and third lines of the model are illustrative parameters",
            "a comparative-column recast is not an enforcement action or a fraud finding",
            "the revised figure is not an independent measurement of the same quantity: it "
            "includes royalty income the as-filed figure excluded, so the difference is a "
            "change in presentation as well as in amount",
            "the characterisation rests on two documents and their Item 9C checkboxes; it does "
            "not audit Pfizer's accounting",
        ],
    }
    write_json(output / "sec_evidence_case.json", results)

    lines = [
        "# Real-evidence case study: an SEC revenue revision",
        "",
        "Generated by `scripts/research/sec_evidence_case.py`. Source documents are cached next to",
        "this file with their SHA-256 digests.",
        "",
        f"**{results['source']['company']}** (CIK {CIK}), `us-gaap:Revenues`, FY2023.",
        "",
        "| | original filing | later filing |",
        "|---|---|---|",
        f"| value (USD) | {original['value']:,.0f} | {later_filing['value']:,.0f} |",
        f"| form | {original['form']} | {later_filing['form']} |",
        f"| accession | {ORIGINAL_ACCESSION} | {LATER_ACCESSION} |",
        f"| accepted | {acceptance[ORIGINAL_ACCESSION]['acceptance']} | "
        f"{acceptance[LATER_ACCESSION]['acceptance']} |",
        "",
        f"Relative change: {results['revision']['relative_change']:.4%}. Compiled cost "
        f"perturbation: {results['audit']['cost_effect_applied']}.",
        "",
        "## What kind of revision this is",
        "",
        f"Characterisation: **`{characterization['characterization']}`** "
        f"(formal restatement: {characterization['formal_restatement']}).",
        "",
        "Read from the primary documents at run time:",
        "",
    ]
    for role, signal in characterization["signals"].items():
        lines.append(f"- {role}: Item 9C error-correction box "
                     f"{'checked' if signal['error_correction_checkbox_checked'] else 'unchecked'}"
                     f" ({len(signal['recast_disclosures'])} recast disclosure(s) found)")
        for quote in signal["recast_disclosures"][:2]:
            lines.append(f"  > {quote}")
    lines += [
        "",
        f"_{characterization['accounting_note']}._",
        "",
        f"{results['characterization']['what_changed']}",
        "",
        f"It is {results['characterization']['what_it_is_not']}.",
        "",
        "## Audit",
        "",
        f"- decision clock {DECISION_CLOCK}, audit clock {AUDIT_CLOCK}",
        f"- temporal relationship: `{certificate.temporal_relationship}`",
        f"- verdict: `{certificate.verdict}`",
        f"- certified regret bound: {certificate.exact['numerical_regret_bound']}",
        f"- realized regret (OSQP reference): {realized:.3e}",
        f"- bound sound: {results['audit']['bound_sound']}",
        "",
        "## Controls",
        "",
        f"- re-offered after the decision clock: status `{reincorporated.status}`, "
        f"excluded because {[item['reason'] for item in reincorporated.excluded]}",
        f"- audited before the recast was accepted: status `{early.status}`, "
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
