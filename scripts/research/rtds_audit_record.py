"""Export and verify a *sufficient* minimal audit record for the vintage study.

The earlier version of the study reported a 366-429 byte "audit record" and compared it with a
807-1080 byte serialised problem. That record was not sufficient: it omitted the multipliers (without
which no regret bound can be evaluated) and the decision-time cost vector (without which the revision
has no base), so nothing could be certified from it. This module constructs a record that *is*
sufficient, then proves it by reconstructing the certificate in a fresh process using only:

* the per-decision record (weights, multipliers, decision-time linear costs, clocks, digests);
* the per-cohort shared structure (risk matrix, bounds, constraint rows, risk weight), stored once;
* the newly available revision data (the audit-vintage observations already in ``dataset.json``).

Usage::

    .venv/bin/python scripts/research/rtds_audit_record.py --export
    .venv/bin/python scripts/research/rtds_audit_record.py --verify
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas.decision.certificate import certify_revision_impact  # noqa: E402
from atlas.decision.problem import (  # noqa: E402
    ConvexDecisionProblem,
    LinearInequality,
    check_feasibility,
)
from atlas.decision.qp import DualPoint  # noqa: E402
from atlas.decision.revision import EvidenceRevision, InputSensitivity, compile_revisions  # noqa: E402

import rtds_study as study  # noqa: E402
from rtds_model import COST_CONVENTION  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "artifacts" / "research" / "rtds"
RECORDS = DATA / "audit_records.json"
VERIFICATION = DATA / "audit_record_verification.json"


def problem_from_record(shared: dict[str, Any], costs: Sequence[float],
                        as_of: str) -> ConvexDecisionProblem:
    """Rebuild a program from the shared structure and one decision's linear costs.

    Note the direction: the record stores the **linear costs** (``c``), not expected returns, so no
    sign convention is re-derived at verification time. That is deliberate -- a verification step
    that re-used the convention could reproduce a sign error instead of catching it.
    """

    return ConvexDecisionProblem(
        problem_id=f"{shared['cohort']}::reconstructed",
        variables=tuple(shared["assets"]),
        linear_costs=tuple(float(value) for value in costs),
        risk_matrix=tuple(tuple(float(v) for v in row) for row in shared["risk_matrix"]),
        lower=tuple(float(shared["lower"]) for _ in shared["assets"]),
        upper=tuple(float(shared["upper"]) for _ in shared["assets"]),
        budget=float(shared["budget"]),
        inequalities=tuple(LinearInequality(tuple(row["coefficients"]), float(row["bound"]),
                                           row.get("label", ""))
                           for row in shared["inequalities"]),
        semantics="portfolio_mean_variance",
        as_of=as_of,
        labels={"cohort": shared["cohort"], "reconstruction": "record_only"},
    )


def export() -> dict[str, Any]:
    """Rebuild the decisions, write the sufficient records and the shared structure."""

    dataset = study.load_dataset()
    payload: dict[str, Any] = {"schema": "atlas.rtds.audit_record.v1",
                               "convention": dict(COST_CONVENTION), "shared": {},
                               "standardisation": {}, "records": []}
    for cohort in dataset["cohorts"]:
        key = cohort["cohort"]
        labels = cohort["labels"]
        train = [event for event in cohort["events"] if event["split"] == "train"]
        block = study.calibration(train, labels)
        rho, _shares = study.choose_rho(train, key, labels, block)
        block["half_width_cost"] = study.train_half_width(train, block)
        payload["shared"][key] = study.shared_structure(key, labels, block["correlation"], rho,
                                                        cohort.get("manifest_digest"))
        # Train-split standardisation: shared by every decision in the cohort, so it is stored once.
        payload["standardisation"][key] = {"mean": block["mean"].tolist(),
                                           "scale": block["scale"].tolist(),
                                           "source": "train split 2000-2012 first-print growth"}
        for event in cohort["events"]:
            if event["split"] not in {"train", "test", "holdout"}:
                continue
            returns_decision = study.standardise(event["growth_decision"], block)
            problem = study.build_problem(returns_decision, key, labels, block["correlation"], rho,
                                          event["decision_vintage"], "decision")
            decision = study.solve(problem)
            if not decision.feasible or decision.dual is None:
                continue
            record = study.minimal_record(problem, decision, problem.cost_vector(), event, key)
            record["split"] = event["split"]
            payload["records"].append(record)
    RECORDS.write_text(json.dumps(payload, indent=1, sort_keys=True))
    total = len(payload["records"])
    per_record = (sum(study.serialise_size(record) for record in payload["records"]) / total
                  if total else 0.0)
    summary = {"records": total, "mean_record_bytes": per_record,
               "shared_bytes": {key: study.serialise_size(value)
                                for key, value in payload["shared"].items()},
               "standardisation_bytes": {key: study.serialise_size(value)
                                         for key, value in payload["standardisation"].items()}}
    print(json.dumps(summary, indent=1))
    return summary


def verify() -> dict[str, Any]:
    """Fresh process: certify from the record, the shared structure and the revision data only."""

    payload = json.loads(RECORDS.read_text())
    results = json.loads((DATA / "results.json").read_text())
    reference = {}
    for cohort in results["cohorts"]:
        for row in cohort["rows"]:
            reference[(cohort["cohort"], row["period"])] = row
    dataset = study.load_dataset()
    revisions_at: dict[tuple[str, str], dict[str, Any]] = {}
    for cohort in dataset["cohorts"]:
        for event in cohort["events"]:
            revisions_at[(cohort["cohort"], event["period"])] = event

    checked = 0
    failures: list[dict[str, Any]] = []
    worst_bound_gap = 0.0
    max_feasibility_violation = 0.0
    for record in payload["records"]:
        key = record["cohort"]
        shared = payload["shared"][key]
        event = revisions_at[(key, record["period"])]
        as_of = record["decision_as_of"]
        decision_problem = problem_from_record(shared, record["costs_decision"], as_of)
        feasibility = check_feasibility(decision_problem, record["weights"], tolerance=1e-7)
        max_feasibility_violation = max(max_feasibility_violation, feasibility.max_violation)
        # Newly available revision data: the audit-vintage observations, expressed as a change in
        # the objective's linear costs. The scaling comes from the cohort's train-split
        # standardisation, which the record itself does not carry -- it is shared, like the matrix.
        returns_audit = (np.asarray(event["growth_audit"], dtype=float) - np.asarray(
            payload["standardisation"][key]["mean"])) / np.asarray(
            payload["standardisation"][key]["scale"])
        costs_audit = -returns_audit
        costs_decision = np.asarray(record["costs_decision"], dtype=float)
        revisions = []
        sensitivities = []
        for index, label in enumerate(shared["assets"]):
            delta = float(costs_audit[index] - costs_decision[index])
            if delta == 0.0:
                continue
            revisions.append(EvidenceRevision(
                revision_id=f"{record['period']}::{label}",
                evidence_id=record["audit_vintage"],
                input_key=label,
                delta=delta,
                available_at=record["audit_clock"],
                effective_at=record["audit_clock"],
                kind="linear_objective",
                delta_semantics="absolute",
            ))
            effect = [0.0] * len(shared["assets"])
            effect[index] = 1.0
            sensitivities.append(InputSensitivity(label, tuple(effect)))
        dual = DualPoint(nu=record["multipliers"]["nu"],
                         alpha=tuple(record["multipliers"]["alpha"]),
                         beta=tuple(record["multipliers"]["beta"]),
                         gamma=tuple(record["multipliers"]["gamma"]),
                         structure_digest=decision_problem.structure_digest())
        compilation = compile_revisions(
            decision_problem, revisions, sensitivities, as_of=record["decision_clock"],
            audit_as_of=record["audit_clock"], starting_vintage=record["decision_vintage"])
        certificate = certify_revision_impact(decision_problem, record["weights"], compilation,
                                              decision_dual=dual)
        bound = certificate.bounded["regret_upper_bound"]
        row = reference.get((key, record["period"]))
        checked += 1
        if row is None or row["bound"] is None:
            failures.append({"cohort": key, "period": record["period"],
                             "reason": "no reference bound"})
            continue
        gap = abs(float(bound) - float(row["bound"]))
        worst_bound_gap = max(worst_bound_gap, gap)
        if gap > 1e-9 * max(1.0, abs(float(row["bound"]))):
            failures.append({"cohort": key, "period": record["period"],
                             "reference": row["bound"], "reconstructed": float(bound), "gap": gap})
        if bool(float(bound) <= study.TAU) != bool(row["certified_immaterial"]):
            failures.append({"cohort": key, "period": record["period"],
                             "reason": "verdict disagreement",
                             "reference": row["certified_immaterial"]})
    summary = {
        "schema": "atlas.rtds.audit_record_verification.v1",
        "records_checked": checked,
        "failures": failures,
        "worst_bound_absolute_gap": worst_bound_gap,
        "max_feasibility_violation_reconstructed": max_feasibility_violation,
        "certificates_reproduced": checked - len(failures),
        "note": ("the reconstructing process reads only audit_records.json, dataset.json (for the "
                 "newly available audit-vintage observations) and the shared train-split "
                 "standardisation; it never calls the study's event pipeline"),
    }
    VERIFICATION.write_text(json.dumps(summary, indent=1))
    print(json.dumps({key: summary[key] for key in
                      ("records_checked", "certificates_reproduced", "worst_bound_absolute_gap")},
                     indent=1))
    if failures:
        print(f"{len(failures)} records failed verification", file=sys.stderr)
    return summary


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--export"
    if mode == "--export":
        export()
    elif mode == "--verify":
        verify()
    else:
        raise SystemExit(f"unknown mode {mode!r}; use --export or --verify")
