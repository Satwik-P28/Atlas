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


def minimal_record(decision_problem: Any, decision: Any, costs_decision: Sequence[float],
                   event: dict[str, Any], cohort: str) -> dict[str, Any]:
    """The smallest representation that a *fresh process* can certify from.

    It has to carry the recorded decision, the multipliers that were recorded with it (without them
    no bound can be evaluated), and the decision-time linear costs (without them the revision has no
    base). The quadratic matrix, the bounds and the constraint rows are shared by every decision in a
    cohort and are stored once, not per decision.
    """

    dual = decision.dual
    return {
        "cohort": cohort,
        "period": event["period"],
        "decision_vintage": event["decision_vintage"],
        "audit_vintage": event["audit_vintage"],
        "decision_as_of": decision_problem.as_of,
        "decision_clock": f"{event['decision_vintage']}T23:59:59Z",
        "audit_clock": f"{event['audit_vintage']}T23:59:59Z",
        "weights": [float(value) for value in decision.weights],
        "multipliers": {
            "nu": float(dual.nu),
            "alpha": [float(value) for value in dual.alpha],
            "beta": [float(value) for value in dual.beta],
            "gamma": [float(value) for value in dual.gamma],
        },
        "costs_decision": [float(value) for value in costs_decision],
        "structure_digest": decision_problem.structure_digest(),
        "problem_digest": decision_problem.digest(),
    }


def shared_structure(cohort: str, labels: Sequence[str], correlation: np.ndarray, rho: float
                     ) -> dict[str, Any]:
    """Everything a certificate needs that is identical for every decision in a cohort."""

    from rtds_model import UPPER, allocations

    rows = [row.as_dict() for row in allocations(len(labels), cohort)]
    return {
        "cohort": cohort, "assets": list(labels), "risk_weight": float(rho),
        "risk_matrix": (rho * np.asarray(correlation, dtype=float)).tolist(),
        "lower": 0.0, "upper": UPPER, "budget": 1.0, "inequalities": rows,
    }


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

    # ---- CRI-U on two explicitly declared bases. The set is a set of *additional corrections*:
    # its centre is zero on both, because a correction is not an absolute level.
    half = np.asarray(block["half_width_cost"], dtype=float)
    clock_start = time.perf_counter()
    uncertainty_audit = interval_set(center=[0.0] * len(labels), half_width=half,
                                     coverage="train mean |delta costs| per input, 2000-2012",
                                     label="further correction beyond the audit vintage")
    worst_audit = certify_worst_case(audit_problem, recorded, uncertainty_audit,
                                     decision_dual=decision.dual,
                                     dual_iterations=dual_iterations)
    worst_case_ms = (time.perf_counter() - clock_start) * 1000.0
    uncertainty_decision = interval_set(center=[0.0] * len(labels), half_width=half,
                                        coverage="train mean |delta costs| per input, 2000-2012",
                                        label="correction relative to the decision vintage")
    worst_decision = certify_worst_case(decision_problem, recorded, uncertainty_decision,
                                        decision_dual=decision.dual,
                                        dual_iterations=dual_iterations)
    out_of_set = float(uncertainty_decision.distance_outside(delta_cost))

    clock_start = time.perf_counter()
    warm = solve(audit_problem, warm_start=recorded)
    warm_ms = (time.perf_counter() - clock_start) * 1000.0

    clock_start = time.perf_counter()
    radius = stability_radius(decision_problem, recorded, direction=delta_cost,
                              upper_limit=10.0) if np.any(delta_cost) else None
    radius_ms = (time.perf_counter() - clock_start) * 1000.0
    lower, upper = decision_problem.bounds()
    at_bound = np.isclose(recorded, lower, atol=1e-6) | np.isclose(recorded, upper, atol=1e-6)

    record = minimal_record(decision_problem, decision, costs_decision, event, cohort)
    record_bytes = serialise_size(record)
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
        "out_of_set": out_of_set,
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
                   "repair_ms": repair_ms, "radius_ms": radius_ms},
        "storage": {"record_bytes": record_bytes, "problem_bytes": problem_bytes,
                    "cost_only_bytes": cost_only_bytes},
    }


def certificate_table(rows: Sequence[dict[str, Any]], tau: float) -> dict[str, Any]:
    """Coverage of each method, split into immateriality certificates, materiality witnesses and
    abstentions. An upper bound above the tolerance is a *failure to prove*, never a proof."""

    def summarise(name: str, immaterial: list[bool], material: list[bool]) -> dict[str, Any]:
        n = len(rows)
        certified_immaterial = sum(1 for flag in immaterial if flag)
        certified_material = sum(1 for flag in material if flag)
        false_immaterial = sum(1 for row, flag in zip(rows, immaterial)
                               if flag and row["material"])
        wrong_material = sum(1 for row, flag in zip(rows, material)
                             if flag and not row["material"])
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
                "false_material_certificates": wrong_material,
                "immaterial_events": immaterial_events,
                "coverage_of_immaterial": (certified_immaterial / immaterial_events
                                           if immaterial_events else None)}

    bounded = [row["bound"] is not None and row["bound"] <= tau for row in rows]
    return {
        "cri_immateriality_certificate": summarise(
            "CRI regret bound <= tau (validated upper bound)", bounded, [False] * len(rows)),
        "cri_with_witness": summarise(
            "CRI certificate + feasible-repair materiality witness",
            bounded, [row["certified_material"] for row in rows]),
        "active_set": summarise(
            "active-set / KKT stability (implies regret 0)",
            [row["stable"] for row in rows], [False] * len(rows)),
        "strong_convexity": summarise(
            "strong-convexity upper bound <= tau",
            [row["strong_convexity"] is not None and row["strong_convexity"] <= tau
             for row in rows], [False] * len(rows)),
        "cri_u_audit_base": summarise(
            "CRI-U: further correction beyond the audit vintage",
            [row["worst_case_audit"] is not None and row["worst_case_audit"] <= tau
             for row in rows], [False] * len(rows)),
        "cri_u_decision_base": summarise(
            "CRI-U: correction relative to the decision vintage",
            [row["worst_case_decision"] is not None and row["worst_case_decision"] <= tau
             for row in rows], [False] * len(rows)),
        "no_recompute": summarise(
            "no recomputation (asserts regret 0 for every event)",
            [True] * len(rows), [False] * len(rows)),
    }


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
    # split only. The set is centred on zero -- a correction is not a level.
    train_deltas = [np.abs(standardise(event["growth_audit"], block)
                           - standardise(event["growth_decision"], block)) for event in train]
    width = np.asarray(train_deltas, dtype=float)
    block["half_width_cost"] = width.mean(axis=0).tolist() if width.size else [0.0] * len(labels)

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
                    "warm_ms", "active_set_ms", "worst_case_ms", "repair_ms", "radius_ms")
    timing = {}
    for name in timing_names:
        values = [row["timing"][name] for row in test_rows]
        timing[name] = {"median": float(np.median(values)) if values else None,
                        "mean": float(np.mean(values)) if values else None}
    storage = {}
    for name in ("record_bytes", "problem_bytes", "cost_only_bytes"):
        values = [row["storage"][name] for row in test_rows]
        storage[name] = {"median_bytes": float(np.median(values)) if values else None}
    shared = shared_structure(key, labels, block["correlation"], rho)
    shared_bytes = serialise_size(shared)
    storage["shared_bytes"] = {"value": float(shared_bytes)}
    storage["decisions"] = {"value": float(len(rows))}
    if rows:
        storage["amortized_shared_bytes_per_decision"] = {
            "value": float(shared_bytes) / len(rows)}
        storage["record_plus_amortized_shared"] = {
            "value": float(np.median([row["storage"]["record_bytes"] for row in rows]))
            + float(shared_bytes) / len(rows)}
        storage["cost_only_plus_amortized_shared"] = {
            "value": float(np.median([row["storage"]["cost_only_bytes"] for row in rows]))
            + float(shared_bytes) / len(rows)}

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
        "test": cohort_summary(test_rows),
        "holdout": cohort_summary(holdout_rows),
        "certificates": certificate_table(test_rows, TAU),
        "heuristics": heuristic_table(test_rows, TAU),
        "agreement": agreement,
        "prediction": prediction_table(train_rows, test_rows, years),
        "timing_ms": timing,
        "storage": storage,
        "cri_u": {
            "half_width_cost": block["half_width_cost"],
            "median_out_of_set_distance": (float(np.median([row["out_of_set"] for row in test_rows]))
                                           if test_rows else None),
            "out_of_set_share": (float(np.mean([row["out_of_set"] > 0 for row in test_rows]))
                                 if test_rows else None),
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
        deltas = [np.abs(standardise(event["growth_audit"], block)
                         - standardise(event["growth_decision"], block)) for event in events]
        block["half_width_cost"] = np.asarray(deltas).mean(axis=0).tolist()
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
        "schema": "atlas.rtds.study.v2",
        "supersedes": "artifacts/research/rtds/superseded/results_v1.json",
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
