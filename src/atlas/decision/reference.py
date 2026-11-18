"""Independent reference solvers, used to check the primary implementation.

Nothing in this module is used by the certificate. It exists because a claim such as "the
recorded decision's regret was 4.1e-05" must not be established by the same solver that is
being tested. Three separate references are provided:

``solve_osqp``            ADMM interior-point-style first-order method (OSQP).
``solve_clarabel``        interior-point method (Clarabel).
``enumerate_box_solution`` exhaustive enumeration of every active set, exact for small
                          dimensions and restricted to box + budget problems.

The exhaustive enumerator is the strongest reference for small instances: it solves the
equality-constrained subproblem for every combination of pinned coordinates, which is a
different algorithm from anything in :mod:`atlas.decision.qp` (it never runs a general-purpose
nonlinear solver and never recovers multipliers from a candidate point).

Agreement between three independently implemented methods is evidence about the *program*, not
about the world. No reference here says anything about whether the model is a good model.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..core.errors import ValidationError
from .problem import ConvexDecisionProblem, check_feasibility

REFERENCE_SCHEMA = "atlas.decision.reference_solution.v1"


@dataclass(frozen=True, slots=True)
class ReferenceSolution:
    solver: str
    status: str
    weights: tuple[float, ...]
    objective: float
    feasible: bool
    max_violation: float
    runtime_ms: float
    iterations: int
    tolerance: dict[str, float]
    diagnostics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": REFERENCE_SCHEMA,
            "solver": self.solver,
            "status": self.status,
            "weights": list(self.weights),
            "objective": self.objective,
            "feasible": self.feasible,
            "max_violation": self.max_violation,
            "runtime_ms": self.runtime_ms,
            "iterations": self.iterations,
            "tolerance": dict(self.tolerance),
            "diagnostics": dict(self.diagnostics),
        }


def _constraint_matrices(problem: ConvexDecisionProblem):
    n = problem.dimension
    lower, upper = problem.bounds()
    a_matrix, d_vector = problem.inequality_arrays()
    ones = np.ones((1, n))
    rows = [ones, np.eye(n)]
    for row in a_matrix:
        rows.append(row.reshape(1, n))
    a_full = np.vstack(rows)
    lower_bounds = np.concatenate(([problem.budget], lower, np.full(a_matrix.shape[0], -np.inf)))
    upper_bounds = np.concatenate(([problem.budget], upper, d_vector))
    return a_full, lower_bounds, upper_bounds


def solve_osqp(
    problem: ConvexDecisionProblem,
    *,
    eps_abs: float = 1e-10,
    eps_rel: float = 1e-10,
    max_iter: int = 200_000,
    polish: bool = True,
) -> ReferenceSolution:
    """Solve with OSQP at a declared tolerance. Raises if OSQP is not installed."""

    import osqp  # imported lazily so the package stays importable without the extra
    import scipy.sparse as sparse

    import time

    started = time.perf_counter()
    n = problem.dimension
    q = problem.matrix()
    c = problem.cost_vector()
    a_full, lower_bounds, upper_bounds = _constraint_matrices(problem)
    try:
        solver = osqp.OSQP()
        solver.setup(P=sparse.csc_matrix(q), q=c, A=sparse.csc_matrix(a_full),
                     l=lower_bounds, u=upper_bounds, verbose=False, polish=polish,
                     eps_abs=eps_abs, eps_rel=eps_rel, max_iter=max_iter)
        result = solver.solve()
    except Exception as exc:  # pragma: no cover - depends on the installed OSQP version
        raise ValidationError("OSQP could not solve the problem", error=str(exc)) from exc
    weights = np.asarray(result.x, dtype=float)
    feasibility = check_feasibility(problem, weights, tolerance=1e-7)
    runtime_ms = (time.perf_counter() - started) * 1000.0
    return ReferenceSolution(
        solver="osqp",
        status=str(result.info.status),
        weights=tuple(float(v) for v in weights),
        objective=float(problem.objective(weights)) if np.all(np.isfinite(weights)) else float("nan"),
        feasible=feasibility.feasible,
        max_violation=feasibility.max_violation,
        runtime_ms=runtime_ms,
        iterations=int(getattr(result.info, "iter", 0) or 0),
        tolerance={"eps_abs": eps_abs, "eps_rel": eps_rel, "primal_feasibility_check": 1e-7},
        diagnostics={
            "obj_val": float(getattr(result.info, "obj_val", float("nan"))),
            "dual_obj_val": float(getattr(result.info, "dual_obj_val", float("nan"))),
            "pri_res": float(getattr(result.info, "pri_res", float("nan"))),
            "dua_res": float(getattr(result.info, "dua_res", float("nan"))),
        },
    )


def solve_clarabel(
    problem: ConvexDecisionProblem,
    *,
    tol_gap_abs: float = 1e-11,
    tol_feas: float = 1e-11,
    max_iter: int = 500,
) -> ReferenceSolution:
    """Solve with Clarabel's interior-point method at a declared tolerance."""

    import clarabel
    import scipy.sparse as sparse

    import time

    started = time.perf_counter()
    n = problem.dimension
    lower, upper = problem.bounds()
    a_matrix, d_vector = problem.inequality_arrays()
    rows = [np.ones((1, n)), -np.eye(n), np.eye(n)]
    bounds = [np.array([problem.budget]), -lower, upper]
    for row in a_matrix:
        rows.append(row.reshape(1, n))
    for value in d_vector:
        bounds.append(np.array([value]))
    a_full = np.vstack(rows)
    b_full = np.concatenate(bounds).astype(float)
    cones = [clarabel.ZeroConeT(1), clarabel.NonnegativeConeT(a_full.shape[0] - 1)]
    settings = clarabel.DefaultSettings()
    settings.tol_gap_abs = tol_gap_abs
    settings.tol_gap_rel = tol_gap_abs
    settings.tol_feas = tol_feas
    settings.max_iter = int(max_iter)
    settings.verbose = False
    try:
        solver = clarabel.DefaultSolver(sparse.csc_matrix(problem.matrix()),
                                        problem.cost_vector(),
                                        sparse.csc_matrix(a_full), b_full, cones, settings)
        solution = solver.solve()
    except Exception as exc:  # pragma: no cover - depends on the installed Clarabel version
        raise ValidationError("Clarabel could not solve the problem", error=str(exc)) from exc
    weights = np.asarray(solution.x, dtype=float)
    feasibility = check_feasibility(problem, weights, tolerance=1e-7)
    runtime_ms = (time.perf_counter() - started) * 1000.0
    return ReferenceSolution(
        solver="clarabel",
        status=str(solution.status),
        weights=tuple(float(v) for v in weights),
        objective=float(problem.objective(weights)),
        feasible=feasibility.feasible,
        max_violation=feasibility.max_violation,
        runtime_ms=runtime_ms,
        iterations=int(getattr(solution, "iterations", 0) or 0),
        tolerance={"tol_gap_abs": tol_gap_abs, "tol_feas": tol_feas,
                   "primal_feasibility_check": 1e-7},
        diagnostics={"cost_primal": float(getattr(solution, "obj_val", float("nan"))),
                     "cost_dual": float(getattr(solution, "obj_val_dual", float("nan")))},
    )


def enumerate_box_solution(
    problem: ConvexDecisionProblem,
    *,
    max_coordinates: int = 9,
) -> ReferenceSolution:
    """Enumerate every active set of a box + budget program and return the best feasible point.

    For each coordinate the enumeration considers three states -- at its lower bound, at its
    upper bound, or free -- solves the equality-constrained problem on the free block, and keeps
    the candidate if it is feasible and its free coordinates are interior. ``3**n`` candidates,
    so this is exact but restricted to small ``n``; it refuses problems with extra inequality
    rows rather than pretending the enumeration covers them.
    """

    import time

    started = time.perf_counter()
    n = problem.dimension
    if len(problem.inequalities):
        raise ValidationError(
            "active-set enumeration supports box and budget constraints only; "
            "use the OSQP or Clarabel reference for a program with extra rows"
        )
    if n > max_coordinates:
        raise ValidationError("active-set enumeration is exponential; reduce the dimension",
                              dimension=n, limit=max_coordinates)
    q = problem.matrix()
    c = problem.cost_vector()
    lower, upper = problem.bounds()
    best_value = math.inf
    best_weights: np.ndarray | None = None
    evaluated = 0
    feasible_candidates = 0
    for states in itertools.product((0, 1, 2), repeat=n):  # 0 = free, 1 = at lower, 2 = at upper
        pinned = np.flatnonzero(np.asarray(states) != 0)
        free = np.flatnonzero(np.asarray(states) == 0)
        if free.size == 0:
            continue
        w = np.zeros(n)
        for index in pinned:
            w[index] = lower[index] if states[index] == 1 else upper[index]
        pinned_sum = float(np.sum(w[pinned]))
        if pinned_sum > problem.budget + 1e-12:
            continue
        q_ff = q[np.ix_(free, free)]
        cross = q[np.ix_(free, pinned)] @ w[pinned] if pinned.size else np.zeros(free.size)
        # Equality-constrained subproblem: min 0.5 w'Qw + c'w subject to 1'w = remaining budget.
        kkt = np.zeros((free.size + 1, free.size + 1))
        kkt[:free.size, :free.size] = q_ff
        kkt[:free.size, free.size] = 1.0
        kkt[free.size, :free.size] = 1.0
        rhs = np.concatenate((-c[free] - cross, [problem.budget - pinned_sum]))
        try:
            solution = np.linalg.solve(kkt, rhs)
        except np.linalg.LinAlgError:
            continue
        evaluated += 1
        w[free] = solution[:free.size]
        if np.any(w[free] < lower[free] - 1e-12) or np.any(w[free] > upper[free] + 1e-12):
            continue
        if not check_feasibility(problem, w, tolerance=1e-9).feasible:
            continue
        feasible_candidates += 1
        value = float(problem.objective(w))
        if value < best_value - 1e-15:
            best_value, best_weights = value, w.copy()
    if best_weights is None:  # pragma: no cover - only for genuinely infeasible programs
        raise ValidationError("no feasible active set was found")
    runtime_ms = (time.perf_counter() - started) * 1000.0
    feasibility = check_feasibility(problem, best_weights, tolerance=1e-9)
    return ReferenceSolution(
        solver="exhaustive_active_sets",
        status="solved",
        weights=tuple(float(v) for v in best_weights),
        objective=best_value,
        feasible=feasibility.feasible,
        max_violation=feasibility.max_violation,
        runtime_ms=runtime_ms,
        iterations=evaluated,
        tolerance={"active_set_tolerance": 1e-12, "primal_feasibility_check": 1e-9},
        diagnostics={"combinations": 3 ** n, "subproblems_solved": evaluated,
                     "feasible_candidates": feasible_candidates},
    )


def cross_check(
    problem: ConvexDecisionProblem,
    *,
    solvers: Sequence[str] = ("osqp", "clarabel"),
    exhaustive: bool = False,
) -> dict[str, Any]:
    """Solve with several independent methods and report their disagreement.

    The returned ``max_objective_spread`` is the quantity that matters: if two independent
    solvers at tight tolerances disagree by more than the reference regret of a decision, then
    any regret number computed against one of them is not trustworthy at that resolution.
    """

    results: dict[str, dict[str, Any]] = {}
    objectives: list[float] = []
    for name in solvers:
        try:
            if name == "osqp":
                solution = solve_osqp(problem)
            elif name == "clarabel":
                solution = solve_clarabel(problem)
            else:
                raise ValidationError("unknown reference solver", name=name)
        except (ValidationError, ImportError) as exc:
            results[name] = {"available": False, "reason": str(exc)}
            continue
        results[name] = {"available": True, **solution.as_dict()}
        if solution.feasible and math.isfinite(solution.objective):
            objectives.append(solution.objective)
    if exhaustive:
        try:
            solution = enumerate_box_solution(problem)
            results["exhaustive"] = {"available": True, **solution.as_dict()}
            objectives.append(solution.objective)
        except ValidationError as exc:
            results["exhaustive"] = {"available": False, "reason": str(exc)}
    spread = (max(objectives) - min(objectives)) if len(objectives) >= 2 else None
    return {
        "schema": "atlas.decision.cross_check.v1",
        "problem_id": problem.problem_id,
        "dimension": problem.dimension,
        "methods": results,
        "objective_spread": spread,
        "objective_spread_relative": (
            None if spread is None else spread / max(1.0, abs(min(objectives)))
        ),
        "agree": bool(spread is not None and spread <= 1e-8 * max(1.0, abs(min(objectives)))),
    }


__all__ = [
    "REFERENCE_SCHEMA",
    "ReferenceSolution",
    "cross_check",
    "enumerate_box_solution",
    "solve_clarabel",
    "solve_osqp",
]
