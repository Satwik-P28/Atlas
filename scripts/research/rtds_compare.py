"""Attribute the change between the superseded study and the corrected one.

Three arms on the same decision events, so the correction is not one unexplained difference:

1. **v1 (superseded)**: the old sign convention and the old 400/366-day audit horizon.
2. **mapping fixed, horizon unchanged**: the documented cost convention applied to the *old* audit
   vintages. This isolates the sign error.
3. **v2 (corrected)**: the documented convention and the calendar-aware audit horizon.

Run: ``.venv/bin/python scripts/research/rtds_compare.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtds_study as study  # noqa: E402
from atlas.decision.certificate import certify_revision_impact  # noqa: E402
from atlas.decision.qp import solve  # noqa: E402
from atlas.decision.reference import solve_osqp  # noqa: E402
from rtds_model import build_problem, compile_audit_problem  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "artifacts" / "research" / "rtds"
OUT = DATA / "comparison.json"


def arm(returns_decision: np.ndarray, returns_audit: np.ndarray, cohort: str,
        labels: Sequence[str], correlation: np.ndarray, rho: float, decision_vintage: str,
        audit_vintage: str) -> dict[str, Any] | None:
    problem = build_problem(returns_decision, cohort, labels, correlation, rho, decision_vintage,
                           "decision")
    decision = solve(problem)
    if not decision.feasible or decision.dual is None:
        return None
    compiled = compile_audit_problem(
        problem, returns_decision, returns_audit, labels, event_id="compare",
        decision_clock=f"{decision_vintage}T23:59:59Z", audit_clock=f"{audit_vintage}T23:59:59Z",
        audit_vintage=audit_vintage, decision_vintage=decision_vintage)
    if compiled.status != "applied":
        return None
    audit = compiled.problem
    weights = np.asarray(decision.weights, dtype=float)
    internal = solve(audit)
    external = solve_osqp(audit)
    regret = float(audit.objective(weights)) - min(float(internal.objective),
                                                   float(external.objective))
    certificate = certify_revision_impact(problem, weights, compiled, decision_dual=decision.dual)
    bound = certificate.bounded["regret_upper_bound"]
    return {"regret": regret, "material": bool(regret > study.TAU),
            "bound": None if bound is None else float(bound),
            "certified_immaterial": bool(bound is not None and bound <= study.TAU)}


def main() -> None:
    dataset = study.load_dataset()
    previous = json.loads((DATA / "superseded" / "dataset_v1.json").read_text())
    old_results = json.loads((DATA / "superseded" / "results_v1.json").read_text())
    old_rows = {(cohort["cohort"], row["period"]): row
                for cohort in old_results["cohorts"] for row in cohort["rows"]}
    payload: dict[str, Any] = {"schema": "atlas.rtds.comparison.v1", "cohorts": []}
    for cohort, before in zip(dataset["cohorts"], previous["cohorts"]):
        key = cohort["cohort"]
        labels = cohort["labels"]
        train = [event for event in cohort["events"] if event["split"] == "train"]
        block = study.calibration(train, labels)
        rho = 1.0
        before_events = {event["period"]: event for event in before["events"]}
        arms = {"v1": {"material": 0, "certified": 0, "events": 0},
                "mapping_fixed_old_horizon": {"material": 0, "certified": 0, "events": 0},
                "v2": {"material": 0, "certified": 0, "events": 0}}
        audit_changed = coefficients_changed = paired = 0
        for event in cohort["events"]:
            if event["split"] != "test":
                continue
            old = before_events.get(event["period"])
            row_v1 = old_rows.get((key, event["period"]))
            if old is None or row_v1 is None:
                continue
            paired += 1
            if old["audit_vintage"] != event["audit_vintage"]:
                audit_changed += 1
            if old["growth_audit"] != event["growth_audit"]:
                coefficients_changed += 1
            returns_decision = study.standardise(event["growth_decision"], block)
            arms["v1"]["events"] += 1
            arms["v1"]["material"] += int(row_v1["material"])
            arms["v1"]["certified"] += int(row_v1["certified_immaterial"])
            old_audit = study.standardise(old["growth_audit"], block)
            fixed = arm(returns_decision, old_audit, key, labels, block["correlation"], rho,
                        event["decision_vintage"], old["audit_vintage"])
            if fixed is not None:
                arms["mapping_fixed_old_horizon"]["events"] += 1
                arms["mapping_fixed_old_horizon"]["material"] += int(fixed["material"])
                arms["mapping_fixed_old_horizon"]["certified"] += int(
                    fixed["certified_immaterial"])
            corrected = arm(returns_decision, study.standardise(event["growth_audit"], block), key,
                            labels, block["correlation"], rho, event["decision_vintage"],
                            event["audit_vintage"])
            if corrected is not None:
                arms["v2"]["events"] += 1
                arms["v2"]["material"] += int(corrected["material"])
                arms["v2"]["certified"] += int(corrected["certified_immaterial"])
        payload["cohorts"].append({
            "cohort": key,
            "paired_test_events": paired,
            "audit_vintage_changed": audit_changed,
            "audit_growth_coefficients_changed": coefficients_changed,
            "arms": arms,
        })
        print(f"[{key}] paired={paired} audit_changed={audit_changed} "
              f"coefficients_changed={coefficients_changed} arms={arms}", flush=True)
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
