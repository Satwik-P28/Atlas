"""The decision model the vintage study audits, and the single convention that maps data into it.

**The convention, stated once.** A revision is represented as a change in the program's *linear
cost vector*, and it is applied with a positive identity sensitivity. The objective is

    min  0.5 * x' H x + c'x        H = rho * corr(z)  (constant across vintages)

with ``c = -z`` where ``z`` is standardised growth. ``mean_variance_problem`` takes *expected
returns* and stores ``linear_costs = -expected_returns``, so a problem built from growth ``z`` has
``c = -z``.

    decision vintage:  c_D = -z_D
    audit vintage:     c_A = -z_A
    revision:          delta = c_A - c_D = z_D - z_A          (positive identity sensitivity)

The compiled audit problem must therefore satisfy ``c_D + delta == -z_A``. The earlier version of
this study passed ``delta = z_A - z_D`` into a problem whose costs are ``-z_D``, producing
``z_A - 2 z_D``: a valid QP, but not the model the protocol describes. That defect is reproduced in
``tests/test_rtds_design.py`` and must never come back, which is why the audit problem is now also
constructed directly from the audit-vintage observations and asserted equal to the compiled one.

Everything else in this module is shared machinery: the cohort constraints, the equivalent-problem
assertion, and the cheap feasible repair used to *lower*-bound regret (an upper bound cannot prove
materiality, so a materiality claim needs its own witness).
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

import numpy as np

from atlas.decision.problem import (
    ConvexDecisionProblem,
    LinearInequality,
    check_feasibility,
    mean_variance_problem,
)
from atlas.decision.revision import EvidenceRevision, InputSensitivity, RevisionCompilation, compile_revisions

#: The one documented convention. Recorded in every artifact that involves a revision.
COST_CONVENTION = {
    "name": "revision_is_change_in_linear_cost",
    "sensitivity": "positive_identity",
    "objective": "min 0.5 x'(rho*corr)x + c'x",
    "cost": "c = -z (z = standardised growth); mean_variance_problem(expected_returns=z)",
    "decision_time": "c_D = -z_D",
    "audit_time": "c_A = -z_A",
    "revision": "delta = c_A - c_D = z_D - z_A",
    "invariant": "c_D + delta == -z_A for every event; asserted, not assumed",
}

#: Constraints that make the active set non-trivial. Rows are ``coefficients @ x <= bound``, so a
#: floor is written with a negated row.
INEQUALITIES: dict[str, tuple[tuple[tuple[float, ...], float, str], ...]] = {
    "A": (((0.0, 0.0, -1.0, 0.0), -0.15, "government floor"),      # x_gov >= 0.15
          ((0.0, 1.0, 0.0, 0.0), 0.45, "investment cap")),        # x_inv <= 0.45
    "B": (((0.0, -1.0, 0.0), -0.20, "manufacturing floor"),),      # x_manuf >= 0.20
}

UPPER = 0.6


def allocations(n: int, cohort: str) -> tuple[LinearInequality, ...]:
    return tuple(LinearInequality(tuple(row), float(bound), label)
                 for row, bound, label in INEQUALITIES[cohort])


def build_problem(returns: Sequence[float], cohort: str, labels: Sequence[str],
                  correlation: np.ndarray, rho: float, as_of: str, problem_id: str,
                  *, problem_labels: dict[str, str] | None = None) -> ConvexDecisionProblem:
    """``min 0.5 x'(rho*corr)x - returns'x`` on the budget/box/inequality set."""

    return mean_variance_problem(
        problem_id=problem_id,
        assets=list(labels),
        expected_returns=[float(value) for value in returns],
        covariance=(rho * np.asarray(correlation, dtype=float)).tolist(),
        risk_aversion=1.0,
        lower=0.0,
        upper=UPPER,
        budget=1.0,
        inequalities=allocations(len(labels), cohort),
        as_of=as_of,
        labels=dict(problem_labels or {"cohort": cohort, "risk_weight": f"{rho:g}"}),
    )


def audit_problem_direct(returns_audit: Sequence[float], cohort: str, labels: Sequence[str],
                         correlation: np.ndarray, rho: float, as_of: str,
                         problem_id: str = "audit_direct") -> ConvexDecisionProblem:
    """The audit-time program built **only** from the audit-vintage observations.

    This is the reference the compiled program is checked against: no revision machinery, no
    shared state, one construction from the corrected data.
    """

    return build_problem(returns_audit, cohort, labels, correlation, rho, as_of, problem_id)


def revision_deltas(returns_decision: Sequence[float], returns_audit: Sequence[float]
                    ) -> list[tuple[int, float]]:
    """``(index, delta_linear_cost)`` for every coordinate whose cost changed.

    ``delta = (-z_A) - (-z_D)``. Writing the negation out is the point: the sign error this study
    is correcting came from treating the standardised growth difference as if it were already a
    cost difference.
    """

    zd = np.asarray(returns_decision, dtype=float)
    za = np.asarray(returns_audit, dtype=float)
    cost_decision = -zd
    cost_audit = -za
    return [(index, float(cost_audit[index] - cost_decision[index]))
            for index in range(za.size) if cost_audit[index] != cost_decision[index]]


def revision_objects(returns_decision: Sequence[float], returns_audit: Sequence[float],
                     labels: Sequence[str], *, event_id: str, audit_clock: str,
                     audit_vintage: str) -> tuple[list[EvidenceRevision], list[InputSensitivity]]:
    """Revision records and their declared sensitivities, with the convention documented above."""

    revisions: list[EvidenceRevision] = []
    sensitivities: list[InputSensitivity] = []
    for index, delta in revision_deltas(returns_decision, returns_audit):
        label = labels[index]
        revisions.append(EvidenceRevision(
            revision_id=f"{event_id}::{label}",
            evidence_id=audit_vintage,
            input_key=label,
            delta=delta,
            available_at=audit_clock,
            effective_at=audit_clock,
            kind="linear_objective",
            source_id=f"ALFRED vintage {audit_vintage}",
            version=1,
            delta_semantics="absolute",
            note="change in the objective's linear cost relative to the decision vintage",
        ))
        effect = [0.0] * len(labels)
        effect[index] = 1.0
        sensitivities.append(InputSensitivity(label, tuple(effect)))
    return revisions, sensitivities


def compile_audit_problem(decision_problem: ConvexDecisionProblem,
                          returns_decision: Sequence[float], returns_audit: Sequence[float],
                          labels: Sequence[str], *, event_id: str, decision_clock: str,
                          audit_clock: str, audit_vintage: str,
                          decision_vintage: str) -> RevisionCompilation:
    revisions, sensitivities = revision_objects(
        returns_decision, returns_audit, labels, event_id=event_id, audit_clock=audit_clock,
        audit_vintage=audit_vintage)
    return compile_revisions(
        decision_problem, revisions, sensitivities,
        as_of=decision_clock, audit_as_of=audit_clock, starting_vintage=decision_vintage,
    )


def _inequality_arrays(problem: ConvexDecisionProblem) -> tuple[np.ndarray, np.ndarray]:
    matrix, bounds = problem.inequality_arrays()
    return np.asarray(matrix, dtype=float), np.asarray(bounds, dtype=float)


def equivalence_report(compiled: ConvexDecisionProblem, direct: ConvexDecisionProblem,
                       weights: Sequence[float], *, seed: int = 0) -> dict[str, float]:
    """Maximum disagreement between two constructions of the same audit program.

    Compares the objective coefficients, the quadratic matrix, the feasible region (bounds, budget,
    inequality rows and right-hand sides) and the objective value at the recorded decision plus
    several probe points. Zero everywhere means the two constructions are the same program.
    """

    w = np.asarray(weights, dtype=float)
    rng = np.random.default_rng(seed)
    probes = [w] + [rng.uniform(-0.5, 1.5, size=w.size) for _ in range(4)]
    compiled_matrix = np.asarray(compiled.matrix(), dtype=float)
    direct_matrix = np.asarray(direct.matrix(), dtype=float)
    compiled_ineq, compiled_bounds = _inequality_arrays(compiled)
    direct_ineq, direct_bounds = _inequality_arrays(direct)
    return {
        "linear_costs": float(np.max(np.abs(np.asarray(compiled.cost_vector(), dtype=float)
                                            - np.asarray(direct.cost_vector(), dtype=float)))),
        "risk_matrix": float(np.max(np.abs(compiled_matrix - direct_matrix))),
        "lower": float(np.max(np.abs(np.asarray(compiled.lower, dtype=float)
                                    - np.asarray(direct.lower, dtype=float)))),
        "upper": float(np.max(np.abs(np.asarray(compiled.upper, dtype=float)
                                    - np.asarray(direct.upper, dtype=float)))),
        "budget": float(abs(compiled.budget - direct.budget)),
        "inequality_matrix": float(np.max(np.abs(compiled_ineq - direct_ineq)))
        if compiled_ineq.size or direct_ineq.size else 0.0,
        "inequality_bounds": float(np.max(np.abs(compiled_bounds - direct_bounds)))
        if compiled_bounds.size or direct_bounds.size else 0.0,
        "objective_at_probe_points": float(max(
            abs(float(compiled.objective(point)) - float(direct.objective(point)))
            for point in probes)),
        "gradient_at_decision": float(np.max(np.abs(
            np.asarray(compiled.gradient(w), dtype=float)
            - np.asarray(direct.gradient(w), dtype=float)))),
    }


def assert_equivalent(compiled: ConvexDecisionProblem, direct: ConvexDecisionProblem,
                      weights: Sequence[float], *, tolerance: float = 1e-10,
                      context: str = "") -> dict[str, float]:
    """Raise if the compiled audit program differs from the independently built one."""

    report = equivalence_report(compiled, direct, weights)
    worst = max(report.values()) if report else 0.0
    if worst > tolerance:
        raise AssertionError(
            f"compiled audit program disagrees with the audit-vintage program"
            f"{f' for {context}' if context else ''}: {report} (tolerance {tolerance:.1e})")
    return report


def greedy_repair(problem: ConvexDecisionProblem, weights: Sequence[float], *,
                  max_sweeps: int = 12, tolerance: float = 1e-12) -> dict[str, Any]:
    """A feasible descent from the recorded decision: the witness behind a materiality claim.

    Any feasible point gives ``f(x_candidate) >= f*``, so ``f(w) - f(x_candidate)`` is a *lower*
    bound on the regret of ``w``. A certificate's upper bound cannot prove materiality; this can,
    when the bound is large enough to survive the objective scale. The search is coordinate
    descent over budget-preserving swaps (``x_i - t, x_j + t``), each step solved in closed form
    and clipped to the feasible interval, so it costs ``O(n^2)`` objective evaluations per sweep
    and no solver.
    """

    q = np.asarray(problem.matrix(), dtype=float)
    c = np.asarray(problem.cost_vector(), dtype=float)
    lower, upper = problem.bounds()
    a_matrix, a_bounds = _inequality_arrays(problem)
    x = np.array(weights, dtype=float)
    n = x.size
    improvement_total = 0.0
    sweeps = 0
    for _ in range(max_sweeps):
        sweeps += 1
        gradient = q @ x + c
        slack = a_bounds - a_matrix @ x if a_matrix.shape[0] else np.zeros(0)
        best = (0.0, -1, -1, 0.0)
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                direction = np.zeros(n)
                direction[j] = 1.0
                direction[i] = -1.0
                bound = math.inf
                if direction[j] > 0:
                    bound = min(bound, float(upper[j] - x[j]))
                if direction[i] < 0:
                    bound = min(bound, float(x[i] - lower[i]))
                if a_matrix.shape[0]:
                    rows = a_matrix @ direction
                    for k in range(rows.size):
                        if rows[k] > 1e-14:
                            bound = min(bound, max(0.0, float(slack[k] / rows[k])))
                if not math.isfinite(bound) or bound <= tolerance:
                    continue
                slope = float(gradient @ direction)
                curvature = float(direction @ q @ direction)
                if curvature > 0:
                    step = min(max(-slope / curvature, 0.0), bound)
                else:
                    step = bound if slope < 0 else 0.0
                if step <= tolerance:
                    continue
                gain = -(slope * step + 0.5 * curvature * step * step)
                if gain > best[0]:
                    best = (gain, i, j, step)
        if best[0] <= 1e-16:
            break
        _, i, j, step = best
        x[i] -= step
        x[j] += step
        improvement_total += best[0]
    return {"weights": x, "improvement": float(improvement_total), "sweeps": sweeps,
            "feasible": bool(check_feasibility(problem, x, tolerance=1e-9).feasible)}


def regret_lower_bound(problem: ConvexDecisionProblem, weights: Sequence[float],
                       candidate: Sequence[float]) -> float:
    """``f(w) - f(candidate)``: a valid lower bound on regret for any feasible candidate."""

    return float(problem.objective(weights)) - float(problem.objective(candidate))


def vertex_enumeration_worst_case(problem: ConvexDecisionProblem, weights: Sequence[float],
                                  center: Sequence[float], half_width: Sequence[float]
                                  ) -> dict[str, Any]:
    """Exact worst-case regret over an interval set, by enumerating all ``2^n`` vertices.

    Verification helper for the tests only: it re-solves at every vertex, which is exactly the
    reoptimisation the certificates are meant to avoid. Used to confirm that a certified
    worst-case bound is (a) an upper bound and (b) not absurdly loose.
    """

    from itertools import product

    from atlas.decision.qp import solve

    base = np.asarray(problem.cost_vector(), dtype=float)
    offsets = np.asarray(center, dtype=float)
    half = np.asarray(half_width, dtype=float)
    n = base.size
    worst = -math.inf
    worst_delta: list[float] | None = None
    evaluated = 0
    for signs in product((-1.0, 1.0), repeat=n):
        delta = offsets + half * np.asarray(signs)
        perturbed = problem.replace(
            problem_id=f"{problem.problem_id}::vertex{evaluated}",
            linear_costs=tuple(float(value) for value in base + delta))
        reference = solve(perturbed)
        if not reference.feasible:
            continue
        regret = float(perturbed.objective(weights)) - float(reference.objective)
        evaluated += 1
        if regret > worst:
            worst, worst_delta = regret, [float(v) for v in delta]
    return {"worst_regret": None if worst == -math.inf else worst,
            "argmax_delta": worst_delta, "vertices_evaluated": evaluated,
            "vertices_total": 2 ** n}


def describe_convention() -> dict[str, Any]:
    return {"schema": "atlas.rtds.convention.v1", **COST_CONVENTION,
            "inequalities": {key: [list(row) + [bound] for row, bound, _label in rows]
                             for key, rows in INEQUALITIES.items()},
            "upper": UPPER}


__all__ = [
    "COST_CONVENTION",
    "INEQUALITIES",
    "UPPER",
    "allocations",
    "assert_equivalent",
    "audit_problem_direct",
    "build_problem",
    "compile_audit_problem",
    "describe_convention",
    "equivalence_report",
    "greedy_repair",
    "regret_lower_bound",
    "revision_deltas",
    "revision_objects",
    "vertex_enumeration_worst_case",
]
