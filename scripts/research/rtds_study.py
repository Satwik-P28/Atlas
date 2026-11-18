"""Real-world revision study: does a published revision change the decision, and what can be certified?

The dataset comes from :mod:`scripts.research.rtds_build` (ALFRED real-time vintages). This module
turns each event into a decision/audit pair on a fixed convex program, measures the true regret by
re-solving with two independent solvers, and scores certificates and baselines against it.

Two things are deliberately not done here:

* the audit-time program is never taken from the revision compiler alone -- it is also built directly
  from the audit-vintage observations and the two are asserted equal (:mod:`scripts.research.rtds_model`);
* an upper bound above the tolerance is never reported as a materiality claim. A regret upper bound
  below tolerance proves immateriality; nothing in the certificate proves materiality, so materiality
  needs its own witness (a feasible point whose objective is far enough below the recorded one).

Two revision processes are analysed separately and never pooled: quarterly BEA expenditure aggregates
and monthly BLS payroll employment.

Run: ``.venv/bin/python scripts/research/rtds_study.py``
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas.decision.baselines import first_order_estimate, strong_convexity_bound  # noqa: E402
from atlas.decision.certificate import certify_revision_impact, stability_radius  # noqa: E402
from atlas.decision.qp import derive_multipliers, solve, verify_kkt  # noqa: E402
from atlas.decision.reference import solve_osqp  # noqa: E402
from atlas.decision.uncertainty import certify_worst_case, interval_set  # noqa: E402

from rtds_model import (  # noqa: E402
    COST_CONVENTION,
    assert_equivalent,
    audit_problem_direct,
    build_problem,
    compile_audit_problem,
    greedy_repair,
    regret_lower_bound,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "artifacts" / "research" / "rtds"
OUT = DATA

#: Preregistered thresholds. ``TAU`` is the regret below which a revision is immaterial.
TAU = 1e-3
#: Risk weights considered by the prespecified calibration rule (train split only).
RHO_GRID = (0.25, 0.5, 1.0, 2.0)
#: A lower bound this far above ``TAU`` is reported as a materiality certificate; the margin keeps
#: solver noise from being reported as a proof.
MATERIAL_MARGIN = 1e-9

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "magnitude": ("delta_cost_l2",),
    "metadata": ("changed_inputs", "revision_index", "benchmark"),
    "geometry_no_radius": ("delta_cost_l2", "binding", "condition"),
    "geometry_projection": ("delta_cost_l2", "binding", "condition", "delta_cost_on_decision"),
    "geometry_full": ("delta_cost_l2", "binding", "condition", "delta_cost_on_decision",
                      "log_radius"),
}
#: Which groups need the directional stability radius (and therefore repeated KKT evaluations).
RADIUS_GROUPS = ("geometry_full",)


def load_dataset() -> dict[str, Any]:
    return json.loads((DATA / "dataset.json").read_text())


def growth_matrix(events: Sequence[dict[str, Any]]) -> np.ndarray:
    return np.asarray([event["growth_decision"] for event in events], dtype=float)


def calibration(events: Sequence[dict[str, Any]], labels: Sequence[str]) -> dict[str, Any]:
    """Mean, scale and correlation of **first-print** growth, estimated on the train split only."""

    matrix = growth_matrix(events)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0, ddof=1)
    scale = np.where(scale > 0, scale, 1.0)
    correlation = np.corrcoef(matrix.T)
    return {"mean": mean, "scale": scale, "correlation": correlation,
            "events": int(matrix.shape[0])}


def standardise(growth: Sequence[float], block: dict[str, Any]) -> np.ndarray:
    return (np.asarray(growth, dtype=float) - block["mean"]) / block["scale"]


def interior_share(events: Sequence[dict[str, Any]], cohort: str, labels: Sequence[str],
                   block: dict[str, Any], rho: float) -> float:
    """Share of events whose optimum is not exclusively at box corners (train split only)."""

    interior = 0
    for event in events:
        cost = standardise(event["growth_decision"], block)
        problem = build_problem(cost, cohort, labels, block["correlation"], rho,
                                event["decision_vintage"], "calibration")
        solution = solve(problem)
        if not solution.feasible:
            continue
        lower, upper = problem.bounds()
        weights = np.asarray(solution.weights, dtype=float)
        at_bound = np.isclose(weights, lower, atol=1e-6) | np.isclose(weights, upper, atol=1e-6)
        if not np.all(at_bound):
            interior += 1
    return interior / max(1, len(events))


def choose_rho(train: Sequence[dict[str, Any]], cohort: str, labels: Sequence[str],
               block: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Prespecified rule: the risk weight with the largest interior share on the train split."""

    shares = {f"{rho:g}": interior_share(train, cohort, labels, block, rho) for rho in RHO_GRID}
    best = max(RHO_GRID, key=lambda rho: (shares[f"{rho:g}"], -abs(rho - 1.0)))
    return best, shares


def clustered_interval(values: Sequence[float], clusters: Sequence[str], *, resamples: int = 2000,
                       seed: int = 7) -> dict[str, Any]:
    """Moving-block bootstrap over clusters (decision years), not over events."""

    order = sorted(set(clusters))
    grouped: dict[str, list[float]] = {key: [] for key in order}
    for value, key in zip(values, clusters):
        grouped[key].append(float(value))
    block = 3 if len(order) >= 9 else max(2, len(order) // 2)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(resamples):
        draw: list[float] = []
        start = rng.integers(0, max(1, len(order) - block + 1))
        for index in range(block):
            key = order[(start + index) % len(order)]
            draw.extend(grouped[key])
        if draw:
            means.append(float(np.mean(draw)))
    point = float(np.mean(values)) if values else float("nan")
    return {"estimate": point,
            "lower": float(np.quantile(means, 0.025)) if means else None,
            "upper": float(np.quantile(means, 0.975)) if means else None,
            "clusters": len(order), "block": block, "resamples": resamples,
            "method": "moving_block_bootstrap_over_decision_years"}


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Rank-based AUC; ties count one half."""

    positives = [s for s, y in zip(scores, labels) if y]
    negatives = [s for s, y in zip(scores, labels) if not y]
    if not positives or not negatives:
        return None
    total = 0.0
    for value in positives:
        for other in negatives:
            total += 1.0 if value > other else 0.5 if value == other else 0.0
    return total / (len(positives) * len(negatives))


def clustered_auc_interval(scores: Sequence[float], labels: Sequence[bool],
                           clusters: Sequence[str], *, resamples: int = 400,
                           seed: int = 11) -> dict[str, Any] | None:
    """AUC interval by resampling whole decision years, so a year's events move together."""

    if not scores or len(scores) != len(labels):
        return None
    order = sorted(set(clusters))
    index: dict[str, list[int]] = {key: [] for key in order}
    for position, key in enumerate(clusters):
        index[key].append(position)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(resamples):
        picked: list[int] = []
        for _ in range(len(order)):
            key = order[int(rng.integers(0, len(order)))]
            picked.extend(index[key])
        value = auc([scores[i] for i in picked], [labels[i] for i in picked])
        if value is not None:
            values.append(value)
    point = auc(list(scores), list(labels))
    if not values:
        return None
    return {"estimate": point, "lower": float(np.quantile(values, 0.025)),
            "upper": float(np.quantile(values, 0.975)), "clusters": len(order),
            "resamples": resamples, "method": "cluster_bootstrap_over_decision_years"}


def logistic_fit(features: np.ndarray, labels: np.ndarray, *, l2: float = 1.0,
                 iterations: int = 60) -> np.ndarray:
    """Newton/IRLS with a ridge term: small enough to implement, honest enough to trust."""

    design = np.hstack([np.ones((features.shape[0], 1)), features])
    beta = np.zeros(design.shape[1])
    for _ in range(iterations):
        eta = design @ beta
        probability = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        weight = np.clip(probability * (1 - probability), 1e-8, None)
        gradient = design.T @ (probability - labels) + l2 * np.concatenate([[0.0], beta[1:]])
        hessian = design.T @ (design * weight[:, None]) + l2 * np.eye(design.shape[1])
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def logistic_score(features: np.ndarray, beta: np.ndarray) -> np.ndarray:
    design = np.hstack([np.ones((features.shape[0], 1)), features])
    return 1.0 / (1.0 + np.exp(-np.clip(design @ beta, -30, 30)))


def serialise_size(payload: Any) -> int:
    return len(json.dumps(payload, sort_keys=True, default=str).encode())


def classify_regret(bound: float | None, lower_bound: float, tau: float = TAU) -> str:
    """Three-way classification, with the asymmetry that the whole method rests on.

    An upper bound below the tolerance *proves* immateriality. An upper bound above it proves
    nothing: it is a failure to certify, not a proof of materiality. Materiality therefore needs a
    lower bound, which comes from a feasible point whose objective is far enough below the recorded
    decision's. Anything else is honestly unknown.
    """

    if bound is not None and bound <= tau:
        return "certified_immaterial"
    if lower_bound > tau + MATERIAL_MARGIN:
        return "certified_material"
    return "unknown"


#: Cohort-level provenance. The URL template is identical for every decision in a cohort, so it is
#: stored in the shared block rather than repeated in each record.
EVIDENCE_URL = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=<ID>&vintage_date=<DATE>"


def evidence_digest(event: dict[str, Any]) -> str:
    """Digest of the retained observation record behind one decision.

    Both audit workflows need to say *which* observations they audited, not only what they computed
    from them. The digest is the same for both arms, so it is shared overhead and cancels in the
    comparison; it is carried in the record because a record without provenance is not an audit trail.
    """

    payload = json.dumps(event["inputs"], sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def decision_state(decision_problem: Any, decision: Any, costs_decision: Sequence[float],
                   event: dict[str, Any], cohort: str) -> dict[str, Any]:
    """The state **both** audit workflows must retain: the recorded decision and its provenance.

    A re-solve needs the recorded weights (otherwise there is nothing to test) and the decision-time
    linear costs (otherwise the revision has no base); so does a certificate. Neither arm gets this
    state for free, and the earlier version of the storage comparison charged it to only one arm.
    """

    return {
        "cohort": cohort,
        "period": event["period"],
        "decision_vintage": event["decision_vintage"],
        "audit_vintage": event["audit_vintage"],
        "decision_as_of": decision_problem.as_of,
        "decision_clock": f"{event['decision_vintage']}T23:59:59Z",
        "audit_clock": f"{event['audit_vintage']}T23:59:59Z",
        "horizon_days": event["horizon_days_actual"],
        "weights": [float(value) for value in decision.weights],
        "costs_decision": [float(value) for value in costs_decision],
        "structure_digest": decision_problem.structure_digest(),
        "problem_digest": decision_problem.digest(),
        "provenance": {"observation_digest": evidence_digest(event)},
    }


def minimal_record(decision_problem: Any, decision: Any, costs_decision: Sequence[float],
                   event: dict[str, Any], cohort: str, *,
                   delta: Sequence[float] | None = None) -> dict[str, Any]:
    """The smallest representation that a *fresh process* can certify from.

    It carries the recorded decision with its provenance (:func:`decision_state`), the multipliers
    recorded with it (without them no bound can be evaluated), and -- when ``delta`` is given -- the
    revision as a change in linear costs, which is the audit-time input in the form a certificate
    consumes. Without ``delta`` the record relies on the revision being newly available evidence, and
    that is exactly what ``rtds_audit_record.py --verify`` reconstructs it from.
    """

    dual = decision.dual
    record = decision_state(decision_problem, decision, costs_decision, event, cohort)
    record["multipliers"] = {
        "nu": float(dual.nu),
        "alpha": [float(value) for value in dual.alpha],
        "beta": [float(value) for value in dual.beta],
        "gamma": [float(value) for value in dual.gamma],
    }
    if delta is not None:
        record["revision_delta"] = [float(value) for value in delta]
    return record


def resolve_record(decision_problem: Any, decision: Any, costs_decision: Sequence[float],
                   costs_audit: Sequence[float], event: dict[str, Any], cohort: str
                   ) -> dict[str, Any]:
    """The functionally equivalent state a re-solve needs: same decision state, audit-time costs.

    This exists so the storage comparison is like for like. It is *not* the smallest thing that could
    be written down in principle; it is the smallest thing a re-solve workflow must retain to answer
    the same question (was the recorded decision affected?) from the same evidence.
    """

    record = decision_state(decision_problem, decision, costs_decision, event, cohort)
    record["costs_audit"] = [float(value) for value in costs_audit]
    return record


def shared_structure(cohort: str, labels: Sequence[str], correlation: np.ndarray, rho: float,
                     manifest_digest: str | None = None) -> dict[str, Any]:
    """Everything an audit needs that is identical for every decision in a cohort.

    Both workflows share this block: the matrix, bounds, constraint rows, risk weight, the train-split
    standardisation and the cohort's provenance (vendor, URL template, series, manifest digest).
    """

    from rtds_model import UPPER, allocations

    rows = [row.as_dict() for row in allocations(len(labels), cohort)]
    block = {
        "cohort": cohort, "assets": list(labels), "risk_weight": float(rho),
        "risk_matrix": (rho * np.asarray(correlation, dtype=float)).tolist(),
        "lower": 0.0, "upper": UPPER, "budget": 1.0, "inequalities": rows,
        "provenance": {"source": "ALFRED", "url_template": EVIDENCE_URL,
                       "series": list(labels), "manifest_digest": manifest_digest},
    }
    return block


def train_half_width(train: Sequence[dict[str, Any]], block: dict[str, Any]) -> list[float]:
    """Mean ``|Δc|`` per input over **training events only**.

    The single implementation used by both the main analysis and the sensitivity grid. The grid used
    to compute this from train and test events together, which leaked test revisions into the width of
    the uncertainty set; the width is now train-only everywhere, by construction.
    """

    if not train:
        return [0.0] * len(np.asarray(block["mean"], dtype=float))
    deltas = np.abs(np.asarray([standardise(event["growth_audit"], block) for event in train])
                    - np.asarray([standardise(event["growth_decision"], block) for event in train]))
    return deltas.mean(axis=0).tolist()


def run_event(event: dict[str, Any], cohort: str, labels: Sequence[str], block: dict[str, Any],
              rho: float, *, dual_iterations: int = 0) -> dict[str, Any] | None:
    """One decision/audit pair, every method, and the measured truth."""

    returns_decision = standardise(event["growth_decision"], block)
    returns_audit = standardise(event["growth_audit"], block)
    decision_clock = f"{event['decision_vintage']}T23:59:59Z"
    audit_clock = f"{event['audit_vintage']}T23:59:59Z"
    decision_problem = build_problem(returns_decision, cohort, labels, block["correlation"], rho,
                                     event["decision_vintage"], "decision")
    clock_start = time.perf_counter()
    decision = solve(decision_problem)
    decision_ms = (time.perf_counter() - clock_start) * 1000.0
    if not decision.feasible or decision.dual is None:
        return None
    recorded = np.asarray(decision.weights, dtype=float)

    # ---- the audit-time program: compiled from the revision records ...
    clock_start = time.perf_counter()
    compilation = compile_audit_problem(
        decision_problem, returns_decision, returns_audit, labels,
        event_id=f"{event['period']}", decision_clock=decision_clock, audit_clock=audit_clock,
        audit_vintage=event["audit_vintage"], decision_vintage=event["decision_vintage"])
    compile_ms = (time.perf_counter() - clock_start) * 1000.0
    if compilation.status != "applied":
        return None
    audit_problem = compilation.problem
    # ---- ... and built independently from the audit-vintage observations. They must be the same
    # program: coefficients, quadratic matrix, feasible region, and objective at probe points.
    direct = audit_problem_direct(returns_audit, cohort, labels, block["correlation"], rho,
                                  event["decision_vintage"], "audit_direct")
    equivalence = assert_equivalent(audit_problem, direct, recorded,
                                   context=f"cohort {cohort} {event['period']}")
    equivalence_max = max(equivalence.values())

    costs_decision = np.asarray(decision_problem.cost_vector(), dtype=float)
    costs_audit = np.asarray(audit_problem.cost_vector(), dtype=float)
    delta_cost = costs_audit - costs_decision

    objective_at_decision = float(audit_problem.objective(recorded))
    clock_start = time.perf_counter()
    internal = solve(audit_problem)
    internal_ms = (time.perf_counter() - clock_start) * 1000.0
    clock_start = time.perf_counter()
    external = solve_osqp(audit_problem)
    external_ms = (time.perf_counter() - clock_start) * 1000.0
    objectives = [float(internal.objective), float(external.objective)]
    best = min(objectives)
    regret = objective_at_decision - best
    regret_conservative = objective_at_decision - max(objectives)
    resolution = abs(objectives[0] - objectives[1])

    clock_start = time.perf_counter()
    certificate = certify_revision_impact(decision_problem, recorded, compilation,
                                          decision_dual=decision.dual,
                                          dual_iterations=dual_iterations)
    certificate_ms = (time.perf_counter() - clock_start) * 1000.0
    bound = certificate.bounded["regret_upper_bound"]

    clock_start = time.perf_counter()
    multipliers, _diagnostics = derive_multipliers(audit_problem, recorded)
    stable = bool(multipliers is not None and
                  verify_kkt(audit_problem, recorded, multipliers).satisfied)
    active_set_ms = (time.perf_counter() - clock_start) * 1000.0

    taylor = first_order_estimate(decision_problem.cost_vector(), audit_problem.cost_vector(),
                                  recorded)
    strong = strong_convexity_bound(audit_problem, recorded)

    # ---- a materiality witness: a feasible descent gives a *lower* bound on regret.
    clock_start = time.perf_counter()
    repair = greedy_repair(audit_problem, recorded)
    repair_ms = (time.perf_counter() - clock_start) * 1000.0
    if not repair["feasible"]:
        raise AssertionError(f"the repair point is infeasible for cohort {cohort} {event['period']}")
    lower_bound = regret_lower_bound(audit_problem, recorded, repair["weights"])
    if lower_bound > regret + 1e-6:
        raise AssertionError(
            f"the regret lower bound {lower_bound:.6g} exceeds the measured regret {regret:.6g} "
            f"for cohort {cohort} {event['period']}: the truth or the witness is wrong")

    # ---- CRI-U answers three *different* uncertainty questions, and they are kept separately.
    # Widths are the training split's mean |Δc| per input in every arm; no arm is an absolute level.
    half = np.asarray(block["half_width_cost"], dtype=float)
    coverage = "train-split mean |delta cost| per input (2000-2012 only)"
    # (1) Prospective, base = the audit-time program: how much *further* correction could arrive
    # after the audit vintage and still leave the decision certifiably immaterial? A future correction
    # cannot be observed with two vintages, so this arm's containment is not measurable here and no
    # containment rate is claimed for it.
    clock_start = time.perf_counter()
    uncertainty_audit = interval_set(center=[0.0] * len(labels), half_width=half, coverage=coverage,
                                     label="further correction beyond the audit vintage")
    worst_audit = certify_worst_case(audit_problem, recorded, uncertainty_audit,
                                     decision_dual=decision.dual,
                                     dual_iterations=dual_iterations)
    worst_case_ms = (time.perf_counter() - clock_start) * 1000.0
    # (2) Prospective, base = the decision-time program, centre = no change: if the total correction
    # were any vector in a symmetric box around zero. The observed correction is inside this box for
    # only about half of the events, which is measured (``out_of_set``) and makes the guarantee
    # conditional -- it is reported as such, not as a guarantee on the historical revision.
    uncertainty_decision = interval_set(center=[0.0] * len(labels), half_width=half,
                                        coverage=coverage,
                                        label="prospective total correction, no change assumed")
    worst_decision = certify_worst_case(decision_problem, recorded, uncertainty_decision,
                                        decision_dual=decision.dual,
                                        dual_iterations=dual_iterations)
    out_of_set = float(uncertainty_decision.distance_outside(delta_cost))
    # (3) Post-audit, base = the decision-time program, centre = the *observed* cost revision: the
    # revision is known, but it is itself an estimate, wrong by a typical revision error. This is the
    # only arm whose set is centred on the historical correction, so it is the only arm that can make
    # a statement about the revision that actually occurred (within its declared error).
    clock_start = time.perf_counter()
    uncertainty_postaudit = interval_set(center=delta_cost, half_width=half, coverage=coverage,
                                         label="observed revision +/- a typical revision error")
    worst_postaudit = certify_worst_case(decision_problem, recorded, uncertainty_postaudit,
                                         decision_dual=decision.dual,
                                         dual_iterations=dual_iterations)
    postaudit_ms = (time.perf_counter() - clock_start) * 1000.0
    postaudit_distance = float(uncertainty_postaudit.distance_outside(delta_cost))

    clock_start = time.perf_counter()
    warm = solve(audit_problem, warm_start=recorded)
    warm_ms = (time.perf_counter() - clock_start) * 1000.0

    clock_start = time.perf_counter()
    radius = stability_radius(decision_problem, recorded, direction=delta_cost,
                              upper_limit=10.0) if np.any(delta_cost) else None
    radius_ms = (time.perf_counter() - clock_start) * 1000.0
    lower, upper = decision_problem.bounds()
    at_bound = np.isclose(recorded, lower, atol=1e-6) | np.isclose(recorded, upper, atol=1e-6)

    # ---- stored state, charged identically to both workflows. The comparison is between two
    # functionally equivalent records: the same decision state and provenance, plus either the
    # multipliers a certificate needs or the audit-time costs a re-solve needs.
    state = decision_state(decision_problem, decision, costs_decision, event, cohort)
    record = minimal_record(decision_problem, decision, costs_decision, event, cohort)
    record_with_revision = minimal_record(decision_problem, decision, costs_decision, event, cohort,
                                          delta=delta_cost)
    re_solve = resolve_record(decision_problem, decision, costs_decision, costs_audit, event, cohort)
    problem_bytes = serialise_size(audit_problem.as_dict())
    cost_only_bytes = serialise_size([float(value) for value in costs_audit])

    verdict = classify_regret(bound, lower_bound)
    certified_immaterial = verdict == "certified_immaterial"
    certified_material = verdict == "certified_material"

    return {
        "cohort": cohort,
        "period": event["period"],
        "decision_vintage": event["decision_vintage"],
        "audit_vintage": event["audit_vintage"],
        "split": event["split"],
        "category": event["category"],
        "changed_inputs": event["changed_inputs"],
        "revision_index": event["revision_index"],
        "delta_growth_l2": event["delta_growth_l2"],
        "delta_cost_l2": float(np.linalg.norm(delta_cost)),
        "delta_cost_on_decision": float(abs(delta_cost @ recorded)),
        "equivalence_max": float(equivalence_max),
        "regret": float(regret),
        "regret_conservative": float(regret_conservative),
        "resolution": float(resolution),
        "lower_bound": float(lower_bound),
        "material": bool(regret > TAU),
        "verdict": verdict,
        "certified_immaterial": certified_immaterial,
        "certified_material": certified_material,
        "bound": None if bound is None else float(bound),
        "bound_over_regret": (None if bound is None else float(bound) / float(regret)
                              if regret > 0 else None),
        "stable": stable,
        "taylor": float(taylor["estimate"]),
        "strong_convexity": None if not strong["valid"] else float(strong["bound"]),
        "worst_case_audit": float(worst_audit.bound) if (worst_audit.valid and
                                                         worst_audit.bound is not None) else None,
        "worst_case_decision": float(worst_decision.bound)
        if (worst_decision.valid and worst_decision.bound is not None) else None,
        "worst_case_postaudit": float(worst_postaudit.bound)
        if (worst_postaudit.valid and worst_postaudit.bound is not None) else None,
        "out_of_set": out_of_set,
        "postaudit_distance": postaudit_distance,
        "binding": int(sum(np.isclose(recorded, lower, atol=1e-6) |
                           np.isclose(recorded, upper, atol=1e-6))),
        "radius": None if radius is None else float(radius.radius),
        "radius_evaluations": None if radius is None else int(radius.evaluations),
        "condition": float(np.linalg.cond(decision_problem.matrix())),
        "weights": [float(value) for value in recorded],
        "returns_decision": returns_decision.tolist(),
        "returns_audit": returns_audit.tolist(),
        "timing": {"decision_ms": decision_ms, "compile_ms": compile_ms,
                   "certificate_ms": certificate_ms, "internal_ms": internal_ms,
                   "external_ms": external_ms, "warm_ms": warm_ms,
                   "active_set_ms": active_set_ms, "worst_case_ms": worst_case_ms,
                   "postaudit_ms": postaudit_ms, "repair_ms": repair_ms,
                   "radius_ms": radius_ms},
        "storage": {"record_bytes": serialise_size(record),
                    "record_with_revision_bytes": serialise_size(record_with_revision),
                    "resolve_bytes": serialise_size(re_solve),
                    "decision_state_bytes": serialise_size(state),
                    "provenance_bytes": serialise_size(state["provenance"]),
                    "problem_bytes": problem_bytes,
                    "cost_only_bytes": cost_only_bytes},
    }


def coverage_block(rows: Sequence[dict[str, Any]], name: str, immaterial: Sequence[bool],
                   material: Sequence[bool], *, note: str = "") -> dict[str, Any]:
    """Coverage, abstention and soundness of one method. Shared by every method table."""

    n = len(rows)
    certified_immaterial = sum(1 for flag in immaterial if flag)
    certified_material = sum(1 for flag in material if flag)
    false_immaterial = sum(1 for row, flag in zip(rows, immaterial) if flag and row["material"])
    false_material = sum(1 for row, flag in zip(rows, material) if flag and not row["material"])
    immaterial_events = sum(1 for row in rows if not row["material"])
    return {"method": name, "events": n,
            "certified_immaterial": certified_immaterial,
            "certified_immaterial_share": certified_immaterial / n if n else None,
            "certified_material": certified_material,
            "certified_material_share": certified_material / n if n else None,
            "abstentions": n - certified_immaterial - certified_material,
            "abstention_share": (n - certified_immaterial - certified_material) / n if n else None,
            "decisions_certified": (certified_immaterial + certified_material) / n if n else None,
            "false_immaterial_certificates": false_immaterial,
            "false_material_certificates": false_material,
            "errors": false_immaterial + false_material,
            "immaterial_events": immaterial_events,
            "coverage_of_immaterial": (certified_immaterial / immaterial_events
                                       if immaterial_events else None),
            "note": note}


def certificate_table(rows: Sequence[dict[str, Any]], tau: float) -> dict[str, Any]:
    """Coverage of each certificate, split into immateriality certificates, materiality witnesses and
    abstentions. An upper bound above the tolerance is a *failure to prove*, never a proof."""

    witness = [row["lower_bound"] > tau + MATERIAL_MARGIN for row in rows]
    return {
        "cri_immateriality_certificate": coverage_block(
            rows, "CRI regret bound <= tau (validated upper bound)",
            [row["bound"] is not None and row["bound"] <= tau for row in rows],
            [False] * len(rows),
            note="an upper bound above tau is a failure to certify, never a materiality claim"),
        "cri_with_witness": coverage_block(
            rows, "CRI certificate + greedy feasible-descent materiality witness",
            [row["bound"] is not None and row["bound"] <= tau for row in rows], witness),
        "active_set": coverage_block(
            rows, "active-set / KKT stability (implies regret 0)",
            [row["stable"] for row in rows], [False] * len(rows)),
        "strong_convexity": coverage_block(
            rows, "strong-convexity upper bound <= tau",
            [row["strong_convexity"] is not None and row["strong_convexity"] <= tau
             for row in rows], [False] * len(rows)),
        "no_recompute": coverage_block(
            rows, "no recomputation (asserts regret 0 for every event)",
            [True] * len(rows), [False] * len(rows)),
    }


#: The audit workflows compared head to head. ``kkt_plus_greedy`` is the simpler combined method:
#: one least-squares dual recovery plus a KKT check, then a descent only when the decision moved.
WORKFLOWS: dict[str, str] = {
    "kkt_only": "KKT stability only (dual recovery + feasibility check, no descent)",
    "kkt_plus_greedy": "KKT stability + greedy feasible descent",
    "cri_only": "CRI certificate only",
    "cri_plus_greedy": "CRI certificate + greedy feasible descent",
    "osqp_resolve": "OSQP re-solve (ground truth for the regret, no certificate)",
}


def workflow_verdicts(row: dict[str, Any], tau: float = TAU) -> dict[str, str]:
    """Three-way verdict each workflow would publish, from the quantities it actually computes.

    The only difference between ``kkt_plus_greedy`` and ``cri_plus_greedy`` is the immateriality
    test: KKT stability at the recorded weights, or a regret upper bound at or below the tolerance.
    Both use the same descent for the opposite direction, so any difference in coverage is the
    certificate's incremental contribution -- and nothing else.
    """

    stable = bool(row["stable"])
    bound = row["bound"]
    certified = bound is not None and bound <= tau
    witness = row["lower_bound"] > tau + MATERIAL_MARGIN
    return {
        "kkt_only": "certified_immaterial" if stable else "unknown",
        "kkt_plus_greedy": ("certified_immaterial" if stable
                            else "certified_material" if witness else "unknown"),
        "cri_only": "certified_immaterial" if certified else "unknown",
        "cri_plus_greedy": ("certified_immaterial" if certified
                            else "certified_material" if witness else "unknown"),
        # A re-solve measures the regret, so it is the truth, not a certificate.
        "osqp_resolve": "certified_material" if row["regret"] > tau else "certified_immaterial",
    }


def workflow_runtime(row: dict[str, Any], name: str, *, descend_always: bool = False
                     ) -> dict[str, float]:
    """End-to-end audit cost of one workflow on one event, in milliseconds.

    The descent is only run when the first stage did not already settle the event, unless
    ``descend_always`` is set. ``compile_ms`` and ``decision_ms`` are charged to every workflow: the
    audit program has to be built from the revision in all of them, and the recorded decision is what
    is being audited.
    """

    timing = row["timing"]
    stable = bool(row["stable"])
    certified = row["bound"] is not None and row["bound"] <= TAU
    if name == "kkt_only":
        stage = timing["active_set_ms"]
    elif name == "kkt_plus_greedy":
        stage = timing["active_set_ms"] + (timing["repair_ms"]
                                          if (descend_always or not stable) else 0.0)
    elif name == "cri_only":
        stage = timing["certificate_ms"]
    elif name == "cri_plus_greedy":
        stage = timing["certificate_ms"] + (timing["repair_ms"]
                                           if (descend_always or not certified) else 0.0)
    elif name == "osqp_resolve":
        stage = timing["external_ms"]
    else:  # pragma: no cover - guarded by WORKFLOWS
        raise KeyError(name)
    return {"audit_ms": stage, "with_compile_ms": stage + timing["compile_ms"],
            "end_to_end_ms": stage + timing["compile_ms"] + timing["decision_ms"]}


def workflow_table(rows: Sequence[dict[str, Any]], tau: float = TAU) -> dict[str, Any]:
    """Head-to-head comparison of the audit workflows, including the simpler combined baseline."""

    def summarise(values: Sequence[float]) -> dict[str, float | None]:
        if not values:
            return {"median": None, "mean": None, "total_s": None}
        return {"median": float(np.median(values)), "mean": float(np.mean(values)),
                "total_s": float(np.sum(values)) / 1000.0}

    verdicts = [workflow_verdicts(row, tau) for row in rows]
    out: dict[str, Any] = {
        "runtime_definition": ("per event; audit stage only, then including program compilation, "
                               "then including the original decision solve"),
        "methods": {}, "agreement": {},
    }
    for name, label in WORKFLOWS.items():
        block = coverage_block(rows, label,
                               [v[name] == "certified_immaterial" for v in verdicts],
                               [v[name] == "certified_material" for v in verdicts])
        block["kind"] = ("re_solve_ground_truth" if name == "osqp_resolve"
                         else "audit_workflow")
        runs = [workflow_runtime(row, name) for row in rows]
        block["runtime_ms"] = {
            "audit_stage": summarise([run["audit_ms"] for run in runs]),
            "with_compile": summarise([run["with_compile_ms"] for run in runs]),
            "end_to_end": summarise([run["end_to_end_ms"] for run in runs]),
        }
        if name in {"kkt_plus_greedy", "cri_plus_greedy"}:
            always = [workflow_runtime(row, name, descend_always=True) for row in rows]
            block["runtime_ms"]["descent_always_end_to_end"] = summarise(
                [run["end_to_end_ms"] for run in always])
        out["methods"][name] = block

    kkt = [v["kkt_plus_greedy"] for v in verdicts]
    cri = [v["cri_plus_greedy"] for v in verdicts]
    out["agreement"] = {
        "events": len(rows),
        "verdict_disagreements": sum(1 for a, b in zip(kkt, cri) if a != b),
        "certified_sets_identical": (
            [v["kkt_plus_greedy"] == "certified_immaterial" for v in verdicts]
            == [v["cri_plus_greedy"] == "certified_immaterial" for v in verdicts]),
        "incremental_cri_immaterialities": sum(
            1 for a, b in zip(kkt, cri)
            if b == "certified_immaterial" and a != "certified_immaterial"),
        "incremental_cri_materialities": sum(
            1 for a, b in zip(kkt, cri)
            if b == "certified_material" and a != "certified_material"),
        "kkt_stable_but_bound_above_tau": sum(
            1 for row in rows if row["stable"]
            and (row["bound"] is None or row["bound"] > tau)),
        "cri_immaterial_without_kkt_stability": sum(
            1 for row, v in zip(rows, verdicts)
            if v["cri_plus_greedy"] == "certified_immaterial" and not row["stable"]),
        "descent_supplies_all_material_verdicts": sum(
            1 for v in verdicts if v["kkt_plus_greedy"] == "certified_material"),
    }
    return out


def uncertainty_table(rows: Sequence[dict[str, Any]], tau: float = TAU) -> dict[str, Any]:
    """The three CRI-U questions, answered separately: coverage, containment, conditional guarantee.

    Mixing them is what made the earlier zero read as a general failure. Containment is measurable
    only for a set that is supposed to contain the *observed* correction; for a prospective set about
    a future correction it is not measurable with two vintages, and the report says so instead of
    quoting a rate.
    """

    arms: dict[str, Any] = {
        "prospective_audit_base": {
            "question": ("prospective: if a further correction of typical size arrived after the "
                         "audit vintage, would the decision still be certifiably immaterial?"),
            "base": "audit-time program", "centre": "zero (no further change)",
            "bounds": [row["worst_case_audit"] for row in rows], "contained": None,
            "containment_note": ("not measurable with two vintages: the set is about a correction "
                                 "that has not arrived yet"),
        },
        "prospective_decision_base": {
            "question": ("prospective: if the total correction were any vector in a symmetric box "
                         "around no change, would the decision be certifiably immaterial?"),
            "base": "decision-time program", "centre": "zero (no change assumed)",
            "bounds": [row["worst_case_decision"] for row in rows],
            "contained": [row["out_of_set"] <= 0 for row in rows],
            "containment_note": ("measured against the observed cost revision; the guarantee is "
                                 "conditional on containment"),
        },
        "postaudit_observed_centre": {
            "question": ("post-audit: given the observed revision, and that it is itself wrong by a "
                         "typical revision error, is the decision certifiably immaterial?"),
            "base": "decision-time program", "centre": "observed cost revision",
            "bounds": [row["worst_case_postaudit"] for row in rows],
            "contained": [row["postaudit_distance"] <= 0 for row in rows],
            "containment_note": ("contains the observed revision by construction; whether it "
                                 "contains any *later* correction is not measured here"),
        },
    }
    for name, arm in arms.items():
        values = arm.pop("bounds")
        certified = [value is not None and value <= tau for value in values]
        contained = arm["contained"]
        block = coverage_block(rows, name, certified, [False] * len(rows))
        block["certified_immaterial"] = sum(certified)
        block["certified_immaterial_share"] = float(np.mean(certified)) if rows else None
        finite = [value for value in values if value is not None]
        block["median_bound"] = float(np.median(finite)) if finite else None
        if contained is not None:
            n_contained = sum(1 for flag in contained if flag)
            block["contained_events"] = n_contained
            block["containment_share"] = n_contained / len(rows) if rows else None
            block["certified_given_contained"] = (
                sum(1 for flag, cert in zip(contained, certified) if flag and cert)
                / n_contained if n_contained else None)
            block["certified_and_contained_share"] = (
                sum(1 for flag, cert in zip(contained, certified) if flag and cert)
                / len(rows) if rows else None)
        else:
            block["contained_events"] = None
            block["containment_share"] = None
            block["certified_given_contained"] = None
            block["certified_and_contained_share"] = None
        block["question"] = arm["question"]
        block["base"] = arm["base"]
        block["centre"] = arm["centre"]
        block["containment_note"] = arm["containment_note"]
        arms[name] = block
    return arms


def heuristic_table(rows: Sequence[dict[str, Any]], tau: float) -> dict[str, Any]:
    """Ranking heuristics. These are predictions, not certificates, and are reported as such."""

    def score(name: str, values: Sequence[float | None]) -> dict[str, Any]:
        pairs = [(value, row["material"]) for value, row in zip(values, rows)
                 if value is not None]
        if not pairs:
            return {"heuristic": name, "events": 0}
        values_only = [value for value, _ in pairs]
        labels = [truth for _, truth in pairs]
        ranked = auc(values_only, labels)
        flags = [value > tau for value in values_only]
        return {"heuristic": name, "events": len(pairs), "auc": ranked,
                "flags_material_share": float(np.mean(flags)),
                "precision_when_flagged": (
                    sum(1 for flag, truth in zip(flags, labels) if flag and truth) /
                    max(1, sum(1 for flag in flags if flag))),
                "note": "a heuristic ranking/flag, never a certificate"}

    return {
        "revision_magnitude": score("revision magnitude (log l2 delta cost)",
                                    [math.log1p(row["delta_cost_l2"]) for row in rows]),
        "first_order_estimate": score("first-order estimate (absolute)", 
                                     [abs(row["taylor"]) for row in rows]),
        "cri_bound": score("CRI regret upper bound (absolute)",
                           [row["bound"] for row in rows]),
    }


def feature_matrix(rows: Sequence[dict[str, Any]], group: str) -> np.ndarray:
    columns = {
        "delta_cost_l2": lambda row: row["delta_cost_l2"],
        "delta_cost_on_decision": lambda row: row["delta_cost_on_decision"],
        "changed_inputs": lambda row: len(row["changed_inputs"]),
        "revision_index": lambda row: float(row["revision_index"]),
        "benchmark": lambda row: 1.0 if row["category"] == "annual_benchmark_window" else 0.0,
        "binding": lambda row: float(row["binding"]),
        "condition": lambda row: row["condition"],
        "log_radius": lambda row: (0.0 if row["radius"] is None
                                   else math.log1p(row["radius"])),
    }
    return np.array([[columns[name](row) for name in FEATURE_GROUPS[group]]
                     for row in rows], dtype=float)


def standardise_features(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = train.mean(axis=0)
    scale = train.std(axis=0, ddof=1)
    scale = np.where(scale > 0, scale, 1.0)
    return (train - mean) / scale, (other - mean) / scale


def prediction_table(train_rows: Sequence[dict[str, Any]], test_rows: Sequence[dict[str, Any]],
                     years: Sequence[str]) -> dict[str, Any]:
    """Five prespecified feature groups: does the geometry result survive without the radius?"""

    label_train = np.array([1.0 if row["material"] else 0.0 for row in train_rows])
    label_test = np.array([1.0 if row["material"] else 0.0 for row in test_rows])
    out: dict[str, Any] = {"groups": {}, "train_events": len(train_rows),
                           "test_events": len(test_rows),
                           "model": ("ridge logistic regression (l2=1) on the train split; AUC is "
                                     "rank-based on the test split, ties count one half")}
    for group in FEATURE_GROUPS:
        started = time.perf_counter()
        train_features = feature_matrix(train_rows, group)
        test_features = feature_matrix(test_rows, group)
        feature_ms = (time.perf_counter() - started) * 1000.0 / max(1, len(test_rows))
        if not len(train_features) or not len(test_features):
            continue
        train_scaled, test_scaled = standardise_features(train_features, test_features)
        beta = logistic_fit(train_scaled, label_train)
        scores = logistic_score(test_scaled, beta)
        needs_radius = group in RADIUS_GROUPS
        # The directional stability radius is not free metadata: it runs a bracketing search of
        # multiplier recoveries and KKT checks per event. Its cost is charged to the group here.
        radius_ms = [row["timing"]["radius_ms"] for row in test_rows] if needs_radius else []
        total_ms = feature_ms * len(test_rows) + float(np.sum(radius_ms)) if radius_ms else \
            feature_ms * len(test_rows)
        out["groups"][group] = {
            "features": list(FEATURE_GROUPS[group]),
            "auc": auc(scores.tolist(), label_test.astype(bool).tolist()),
            "auc_interval": clustered_auc_interval(scores.tolist(),
                                                   label_test.astype(bool).tolist(), years),
            "uses_stability_radius": needs_radius,
            "median_total_ms_per_event": total_ms / max(1, len(test_rows)),
            "total_ms": total_ms,
            "kkt_evaluations_per_event": (float(np.median(
                [row["radius_evaluations"] or 0 for row in test_rows]))
                if needs_radius else 0.0),
            "note": ("includes the bracketing search of KKT tests needed by the directional "
                     "radius" if needs_radius else "features are computed from the recorded "
                     "decision and the revision only"),
        }
    return out


def cohort_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Headline materiality and certification numbers for one set of rows."""

    if not rows:
        return {"events": 0}
    years = [row["decision_vintage"][:4] for row in rows]
    material = [row["material"] for row in rows]
    certified_immaterial = [row["certified_immaterial"] for row in rows]
    certified_material = [row["certified_material"] for row in rows]
    immaterial_events = sum(1 for flag in material if not flag)
    nonzero = [row for row in rows if row["delta_cost_l2"] > 0]
    return {
        "events": len(rows),
        "materiality": {
            "share": float(np.mean(material)),
            "interval": clustered_interval([1.0 if flag else 0.0 for flag in material], years),
            "material_events": int(sum(material)),
            "immaterial_events": immaterial_events,
            "nonzero_revision_share": len(nonzero) / len(rows),
        },
        "certification": {
            "immaterial": int(sum(certified_immaterial)),
            "immaterial_share": float(np.mean(certified_immaterial)),
            "immaterial_interval": clustered_interval(
                [1.0 if flag else 0.0 for flag in certified_immaterial], years),
            "material": int(sum(certified_material)),
            "material_share": float(np.mean(certified_material)),
            "unknown": int(len(rows) - sum(certified_immaterial) - sum(certified_material)),
            "unknown_share": float(np.mean([not (a or b) for a, b
                                            in zip(certified_immaterial, certified_material)])),
            "decisions_certified_share": float(np.mean(
                [a or b for a, b in zip(certified_immaterial, certified_material)])),
            "false_immaterial": int(sum(1 for row in rows
                                        if row["certified_immaterial"] and row["material"])),
            "false_material": int(sum(1 for row in rows
                                      if row["certified_material"] and not row["material"])),
            "coverage_of_immaterial": (sum(certified_immaterial) / immaterial_events
                                       if immaterial_events else None),
        },
        "tightness": {
            "median_bound_material": (float(np.median([row["bound"] for row in rows
                                                       if row["material"] and row["bound"] is not None]))
                                      if any(row["material"] and row["bound"] is not None
                                             for row in rows) else None),
            "median_bound_immaterial": (float(np.median([row["bound"] for row in rows
                                                         if not row["material"]
                                                         and row["bound"] is not None]))
                                        if any(not row["material"] and row["bound"] is not None
                                               for row in rows) else None),
            "median_bound_over_regret_material": (
                float(np.median([row["bound"] / row["regret"] for row in rows
                                 if row["material"] and row["bound"] is not None]))
                if any(row["material"] and row["bound"] is not None for row in rows) else None),
            "median_lower_bound_material": (
                float(np.median([row["lower_bound"] for row in rows if row["material"]]))
                if any(row["material"] for row in rows) else None),
            "median_lower_over_regret_material": (
                float(np.median([row["lower_bound"] / row["regret"] for row in rows
                                 if row["material"] and row["regret"] > 0]))
                if any(row["material"] and row["regret"] > 0 for row in rows) else None),
        },
    }


def analyse_cohort(cohort: dict[str, Any]) -> dict[str, Any]:
    key = cohort["cohort"]
    labels = cohort["labels"]
    events = cohort["events"]
    train = [event for event in events if event["split"] == "train"]
    pilot = [event for event in events if event["split"] == "pilot"]
    test = [event for event in events if event["split"] == "test"]
    holdout = [event for event in events if event["split"] == "holdout"]
    block = calibration(train, labels)
    rho, shares = choose_rho(train, key, labels, block)
    print(f"[{key}] rho={rho} interior shares={shares}", flush=True)

    # CRI-U widths: the *magnitude* of a typical correction, in linear-cost units, from the train
    # split only -- one implementation, shared with the sensitivity grid.
    block["half_width_cost"] = train_half_width(train, block)

    rows = []
    for event in events:
        row = run_event(event, key, labels, block, rho)
        if row is not None:
            rows.append(row)
    test_rows = [row for row in rows if row["split"] == "test"]
    pilot_rows = [row for row in rows if row["split"] == "pilot"]
    train_rows = [row for row in rows if row["split"] == "train"]
    holdout_rows = [row for row in rows if row["split"] == "holdout"]
    years = [row["decision_vintage"][:4] for row in test_rows]

    agreement = {
        "certified_and_stable": int(sum(1 for row in test_rows
                                        if row["certified_immaterial"] and row["stable"])),
        "certified_not_stable": int(sum(1 for row in test_rows
                                        if row["certified_immaterial"] and not row["stable"])),
        "stable_not_certified": int(sum(1 for row in test_rows
                                        if row["stable"] and not row["certified_immaterial"])),
        "test_events": len(test_rows),
    }

    timing_names = ("decision_ms", "compile_ms", "certificate_ms", "internal_ms", "external_ms",
                    "warm_ms", "active_set_ms", "worst_case_ms", "postaudit_ms", "repair_ms",
                    "radius_ms")
    timing = {}
    for name in timing_names:
        values = [row["timing"][name] for row in test_rows]
        timing[name] = {"median": float(np.median(values)) if values else None,
                        "mean": float(np.mean(values)) if values else None}
    storage = {}
    storage_names = ("record_bytes", "record_with_revision_bytes", "resolve_bytes",
                     "decision_state_bytes", "provenance_bytes", "problem_bytes",
                     "cost_only_bytes")
    for name in storage_names:
        values = [row["storage"][name] for row in test_rows]
        storage[name] = {"median_bytes": float(np.median(values)) if values else None}
    shared = shared_structure(key, labels, block["correlation"], rho,
                              cohort.get("manifest_digest"))
    shared_bytes = serialise_size(shared)
    storage["shared_bytes"] = {"value": float(shared_bytes)}
    storage["decisions"] = {"value": float(len(rows))}
    storage["functional_equivalence"] = {
        "note": ("both arms carry the same decision state and provenance (recorded weights, "
                 "decision-time costs, clocks, vintages, horizon, digests) and the same shared "
                 "block; the CRI arm adds the multipliers and the revision delta, the re-solve arm "
                 "adds the audit-time cost vector, which is the input of the same size"),
        "cri_arm": "record_with_revision_bytes + amortized shared",
        "re_solve_arm": "resolve_bytes + amortized shared",
    }
    if rows:
        amortized = float(shared_bytes) / len(rows)
        storage["amortized_shared_bytes_per_decision"] = {"value": amortized}
        for name, column in (("record_with_revision", "record_with_revision_bytes"),
                             ("resolve", "resolve_bytes"),
                             ("decision_state", "decision_state_bytes"),
                             ("cost_only", "cost_only_bytes")):
            storage[f"{name}_plus_amortized_shared"] = {
                "value": float(np.median([row["storage"][column] for row in rows])) + amortized}
        storage["record_plus_amortized_shared"] = {
            "value": float(np.median([row["storage"]["record_bytes"] for row in rows]))
            + amortized}
        # The ratio that matters: like-for-like, does the certificate record save anything?
        cri = storage["record_with_revision_plus_amortized_shared"]["value"]
        resolve = storage["resolve_plus_amortized_shared"]["value"]
        storage["cri_over_re_solve_ratio"] = {"value": cri / resolve if resolve else None}

    return {
        "cohort": key,
        "name": cohort["name"],
        "series": cohort["series"],
        "labels": labels,
        "rho": rho,
        "rho_interior_shares": shares,
        "tau": TAU,
        "convention": dict(COST_CONVENTION),
        "counts": {"events": len(events), "train": len(train), "pilot": len(pilot),
                   "test": len(test), "holdout": len(holdout),
                   "processed_test": len(test_rows), "processed_train": len(train_rows),
                   "processed_holdout": len(holdout_rows),
                   "dropped": len(test) - len(test_rows)},
        "equivalence": {
            "max_disagreement": float(max((row["equivalence_max"] for row in rows), default=0.0)),
            "events_checked": len(rows),
            "fields": ["linear_costs", "risk_matrix", "lower", "upper", "budget",
                       "inequality_matrix", "inequality_bounds", "objective_at_probe_points",
                       "gradient_at_decision"],
        },
        "label": ("post-results reanalysis of the preregistered 2015-01-01 .. 2024-06-30 test "
                  "split; the period had already been inspected when these corrections were made"),
        "test": cohort_summary(test_rows),
        "holdout": cohort_summary(holdout_rows),
        "certificates": certificate_table(test_rows, TAU),
        "workflows": workflow_table(test_rows, TAU),
        "uncertainty": uncertainty_table(test_rows, TAU),
        "heuristics": heuristic_table(test_rows, TAU),
        "agreement": agreement,
        "prediction": prediction_table(train_rows, test_rows, years),
        "timing_ms": timing,
        "storage": storage,
        "cri_u": {
            "half_width_cost": block["half_width_cost"],
            "half_width_source": "train split only (2000-2012); test events never enter the width",
            "median_out_of_set_distance": (float(np.median([row["out_of_set"] for row in test_rows]))
                                           if test_rows else None),
            "out_of_set_share": (float(np.mean([row["out_of_set"] > 0 for row in test_rows]))
                                 if test_rows else None),
            "arms_reported_in": "uncertainty",
        },
        "pilot": {"events": len(pilot_rows),
                  "material_share": (float(np.mean([row["material"] for row in pilot_rows]))
                                     if pilot_rows else None)},
        "rows": rows,
    }


def sensitivity_grid(dataset: dict[str, Any]) -> dict[str, Any]:
    """Prespecified secondary grid: risk weight and materiality threshold."""

    results: dict[str, Any] = {}
    for cohort in dataset["cohorts"]:
        key = cohort["cohort"]
        labels = cohort["labels"]
        events = [event for event in cohort["events"] if event["split"] in {"train", "test"}]
        train = [event for event in events if event["split"] == "train"]
        block = calibration(train, labels)
        # Train-only: the grid used to pool train and test revisions here, which leaked test data
        # into the uncertainty-set width. The width is part of the method, not a reported metric.
        block["half_width_cost"] = train_half_width(train, block)
        grid = {}
        for rho in (0.02, 0.05, 0.2, 1.0):
            rows = [run_event(event, key, labels, block, rho) for event in events]
            rows = [row for row in rows if row is not None and row["split"] == "test"]
            if not rows:
                continue
            grid[f"rho={rho:g}"] = {
                "events": len(rows),
                "materiality": {
                    f"tau={tau:g}": float(np.mean([row["regret"] > tau for row in rows]))
                    for tau in (1e-2, 1e-3, 1e-4)},
                "certified_immaterial": {
                    f"tau={tau:g}": float(np.mean([row["bound"] is not None and row["bound"] <= tau
                                                   for row in rows]))
                    for tau in (1e-2, 1e-3, 1e-4)},
            }
        results[key] = grid
    return results


def main() -> None:
    dataset = load_dataset()
    payload: dict[str, Any] = {
        "schema": "atlas.rtds.study.v3",
        "supersedes": ["artifacts/research/rtds/superseded/results_v1.json",
                       "artifacts/research/rtds/superseded/results_v2.json"],
        "sample_label": ("post-results reanalysis of the preregistered 2015-2024H1 test split; "
                         "not an untouched confirmation"),
        "preregistration": "docs/research/rtds/PREREGISTRATION.md",
        "corrections": "docs/research/rtds/CORRECTIONS.md",
        "convention": dict(COST_CONVENTION),
        "tau": TAU,
        "holds_out_2024h2_2025h1": True,
        "cohorts": [],
    }
    for cohort in dataset["cohorts"]:
        result = analyse_cohort(cohort)
        payload["cohorts"].append(result)
        test = result["test"]
        print(f"[{cohort['cohort']}] test events={test['events']} "
              f"materiality={test['materiality']['share']:.4f} "
              f"certified_immaterial={test['certification']['immaterial_share']:.4f} "
              f"certified_material={test['certification']['material_share']:.4f} "
              f"unknown={test['certification']['unknown_share']:.4f} "
              f"holdout_events={result['holdout'].get('events', 0)}", flush=True)
    payload["sensitivity"] = sensitivity_grid(dataset)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"wrote {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
