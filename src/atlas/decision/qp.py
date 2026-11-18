"""Verified convex QP solving and independently checkable optimality diagnostics.

Two things happen here and they are deliberately separate:

1. A *primal* candidate is produced by a general-purpose solver (SciPy SLSQP).
2. A *dual* feasible point is produced by maximising the explicit Lagrange dual, and the
   duality gap ``P(w) - D(nu, alpha, beta, gamma)`` is reported.

The second step is what makes the layer auditable. Weak duality guarantees
``D <= optimum <= P`` for **any** ``alpha, beta, gamma >= 0`` and any ``nu``, so the gap is a
valid upper bound on suboptimality even when the primal solver is inaccurate or reports
failure. A solver's ``success`` flag is never treated as evidence of optimality; the gap and
the KKT residuals are.

The dual of the canonical problem is itself a concave quadratic in
``(nu, alpha, beta, gamma)``::

    g(nu,a,b,g) = -0.5 r' Q^-1 r - nu*budget + a'lower - b'upper - g'd
    r           = c + nu*1 - a + b + A'g

with ``a, b, g >= 0``. Every evaluation is a single Cholesky solve, so a dual feasible point
is cheap. That is the mechanism the revision certificates exploit: a re-used multiplier
vector is already a valid bound with zero optimisation.

Requirement: ``Q`` must be positive definite for a finite dual bound. With a singular risk
matrix the dual function is ``-inf`` on a non-empty set of multiplier vectors and the
certificate is refused with an explicit reason rather than silently regularised.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from scipy import optimize

from ..core.errors import ValidationError
from .problem import (
    DEFAULT_TOLERANCE,
    ConvexDecisionProblem,
    check_feasibility,
)

QP_SCHEMA = "atlas.decision.qp_solution.v1"
KKT_SCHEMA = "atlas.decision.kkt_report.v1"
DUAL_SCHEMA = "atlas.decision.dual_point.v1"

#: Relative KKT tolerance: the residual is measured against the natural scale of the
#: objective gradient, ``max(1, ||Q||_max * ||w||_inf + ||c||_max)``. An absolute tolerance
#: would be meaningless across problems whose objectives differ by six orders of magnitude,
#: so the certificate states the scale it used and the absolute residual it obtained.
KKT_TOLERANCE = 1e-7


def gradient_scale(problem: ConvexDecisionProblem, weights: Sequence[float]) -> float:
    """Upper bound on the magnitude of the objective gradient at ``weights``."""

    w = np.asarray(weights, dtype=float)
    q = problem.matrix()
    c = problem.cost_vector()
    magnitude = float(np.max(np.abs(w))) if w.size else 0.0
    return max(1.0, float(np.max(np.abs(q))) * magnitude + float(np.max(np.abs(c)) if c.size else 0.0))


@dataclass(frozen=True, slots=True)
class DualPoint:
    """A candidate Lagrange multiplier vector. Sign constraints are enforced on use."""

    nu: float
    alpha: tuple[float, ...]
    beta: tuple[float, ...]
    gamma: tuple[float, ...] = ()
    value: float | None = None

    def projected(self) -> "DualPoint":
        return DualPoint(
            nu=float(self.nu),
            alpha=tuple(max(0.0, float(v)) for v in self.alpha),
            beta=tuple(max(0.0, float(v)) for v in self.beta),
            gamma=tuple(max(0.0, float(v)) for v in self.gamma),
            value=self.value,
        )

    def vector(self, dimension: int, inequalities: int) -> np.ndarray:
        return np.concatenate(
            (
                np.array([self.nu], dtype=float),
                np.asarray(self.alpha, dtype=float),
                np.asarray(self.beta, dtype=float),
                np.asarray(self.gamma, dtype=float) if inequalities else np.zeros(0),
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": DUAL_SCHEMA,
            "nu": self.nu,
            "alpha": list(self.alpha),
            "beta": list(self.beta),
            "gamma": list(self.gamma),
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class KKTReport:
    stationarity: float
    dual_feasibility: float
    complementarity: float
    primal_feasibility: float
    tolerance: float
    satisfied: bool
    multipliers: DualPoint | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": KKT_SCHEMA,
            "stationarity": self.stationarity,
            "dual_feasibility": self.dual_feasibility,
            "complementarity": self.complementarity,
            "primal_feasibility": self.primal_feasibility,
            "tolerance": self.tolerance,
            "satisfied": self.satisfied,
            "reason": self.reason,
            "multipliers": self.multipliers.as_dict() if self.multipliers else None,
        }


@dataclass(frozen=True, slots=True)
class QPSolution:
    status: str
    weights: tuple[float, ...]
    objective: float
    feasible: bool
    max_violation: float
    kkt: KKTReport
    dual_bound: float | None
    duality_gap: float | None
    certified_optimal: bool
    dual: DualPoint | None
    solver: str
    iterations: int
    runtime_ms: float
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": QP_SCHEMA,
            "status": self.status,
            "weights": list(self.weights),
            "objective": self.objective,
            "feasible": self.feasible,
            "max_violation": self.max_violation,
            "kkt": self.kkt.as_dict(),
            "dual_bound": self.dual_bound,
            "duality_gap": self.duality_gap,
            "certified_optimal": self.certified_optimal,
            "dual": self.dual.as_dict() if self.dual else None,
            "solver": self.solver,
            "iterations": self.iterations,
            "runtime_ms": self.runtime_ms,
            "diagnostics": dict(self.diagnostics),
        }


# ------------------------------------------------------------------------ linear algebra
def _factor(problem: ConvexDecisionProblem) -> np.ndarray:
    """Cholesky factor of Q, or a raised error for a singular risk matrix."""

    q = problem.matrix()
    try:
        return np.linalg.cholesky(q)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - exercised by a dedicated test
        raise ValidationError(
            "the dual bound requires a positive definite risk matrix; "
            "regularise the covariance (for example with shrinkage) before certifying",
            problem_id=problem.problem_id,
        ) from exc


def _dual_terms(
    problem: ConvexDecisionProblem,
    factor: np.ndarray,
    nu: float,
    alpha: np.ndarray,
    beta: np.ndarray,
    gamma: np.ndarray,
) -> tuple[float, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(value, w, grad_nu, grad_bounds, grad_ineq)`` for one dual point."""

    c = problem.cost_vector()
    a_matrix, d_vector = problem.inequality_arrays()
    r = c + nu + beta - alpha
    if a_matrix.shape[0]:
        r = r + a_matrix.T @ gamma
    w = -np.linalg.solve(factor.T, np.linalg.solve(factor, r))
    # w = -Q^-1 r, so r'Q^-1 r = -r'w and the quadratic term -0.5 r'Q^-1 r equals +0.5 r'w.
    # The opposite sign produces a "dual" above the primal, which is impossible and was a
    # real defect caught by the weak-duality assertion below.
    value = 0.5 * float(r @ w) - nu * problem.budget
    lower, upper = problem.bounds()
    value += float(alpha @ lower) - float(beta @ upper)
    if d_vector.shape[0]:
        value -= float(gamma @ d_vector)
    # d g / d nu = 1'w - budget. The sign was verified by finite differences; the opposite
    # sign makes every dual line search fail at the first step.
    grad_nu = float(np.sum(w)) - problem.budget
    # d g / d alpha_i = lower_i - w_i and d g / d beta_i = w_i - upper_i. The beta sign
    # matters: ascending on (upper - w) instead walks the multiplier to infinity because
    # raising beta lowers w and therefore raises (upper - w).
    grad_bounds = np.concatenate((lower - w, w - upper))
    grad_ineq = (a_matrix @ w - d_vector) if a_matrix.shape[0] else np.zeros(0)
    return value, w, grad_nu, grad_bounds, grad_ineq


def dual_objective(
    problem: ConvexDecisionProblem,
    point: DualPoint,
) -> tuple[float, np.ndarray, np.ndarray]:
    """Evaluate the dual function and the primal point it certifies.

    Returns ``(value, w, gradient)`` where ``gradient`` is ordered as
    ``[nu, alpha(n), beta(n), gamma(m)]``. ``w`` is the unconstrained minimiser of the
    Lagrangian for this multiplier vector; it need not be primal feasible, which is exactly
    why the dual value is a *lower* bound rather than a solution.
    """

    factor = _factor(problem)
    alpha = np.asarray(point.alpha, dtype=float)
    beta = np.asarray(point.beta, dtype=float)
    gamma = np.asarray(point.gamma, dtype=float)
    if alpha.shape != (problem.dimension,) or beta.shape != (problem.dimension,):
        raise ValidationError("dual bound multipliers must match the problem dimension")
    if gamma.shape != (len(problem.inequalities),):
        raise ValidationError("dual inequality multipliers must match inequality count")
    value, w, grad_nu, grad_bounds, grad_ineq = _dual_terms(
        problem, factor, float(point.nu), alpha, beta, gamma
    )
    return value, w, np.concatenate(([grad_nu], grad_bounds, grad_ineq))


def maximize_dual(
    problem: ConvexDecisionProblem,
    *,
    init: DualPoint | None = None,
    max_iter: int = 200,
    tolerance: float = 1e-12,
) -> tuple[DualPoint, dict[str, Any]]:
    """Maximise the dual function over ``alpha, beta, gamma >= 0`` with ``nu`` free.

    Any returned point is projected onto the non-negative orthant before evaluation, so its
    value is a valid lower bound regardless of the optimiser's status. ``max_iter`` is
    exposed because the revision certificates want to measure the value of a *cheap* bound.
    """

    factor = _factor(problem)
    n = problem.dimension
    m = len(problem.inequalities)
    if init is None:
        start = np.zeros(1 + 2 * n + m)
    else:
        start = init.projected().vector(n, m)
    bounds = [(None, None)] + [(0.0, None)] * (2 * n + m)

    def neg(x: np.ndarray) -> tuple[float, np.ndarray]:
        nu = float(x[0])
        alpha = x[1:1 + n]
        beta = x[1 + n:1 + 2 * n]
        gamma = x[1 + 2 * n:] if m else np.zeros(0)
        value, _w, grad_nu, grad_bounds, grad_ineq = _dual_terms(
            problem, factor, nu, alpha, beta, gamma
        )
        grad = np.concatenate(([grad_nu], grad_bounds, grad_ineq))
        return -value, -grad

    result = optimize.minimize(
        neg,
        start,
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": int(max_iter), "ftol": tolerance, "gtol": 1e-12, "maxcor": 30},
    )
    x = np.asarray(result.x, dtype=float)
    if not np.all(np.isfinite(x)):
        x = start.copy()
    x[1:] = np.maximum(x[1:], 0.0)
    point = DualPoint(
        nu=float(x[0]),
        alpha=tuple(float(v) for v in x[1:1 + n]),
        beta=tuple(float(v) for v in x[1 + n:1 + 2 * n]),
        gamma=tuple(float(v) for v in x[1 + 2 * n:]) if m else (),
    )
    # Any dual feasible point is a valid bound, so keep the best *finite* candidate rather
    # than trusting the optimiser's final iterate.
    candidates = [point, init.projected() if init is not None else None,
                  DualPoint(0.0, tuple(0.0 for _ in range(n)), tuple(0.0 for _ in range(n)),
                            tuple(0.0 for _ in range(m)))]
    best: DualPoint | None = None
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            candidate_value, _w, _grad = dual_objective(problem, candidate)
        except (ValidationError, FloatingPointError, ValueError):
            continue
        if not math.isfinite(candidate_value):
            continue
        if best is None or candidate_value > float(best.value or -math.inf):
            best = DualPoint(nu=candidate.nu, alpha=candidate.alpha, beta=candidate.beta,
                             gamma=candidate.gamma, value=candidate_value)
    point = best or DualPoint(nu=point.nu, alpha=point.alpha, beta=point.beta, gamma=point.gamma)
    value = point.value
    diagnostics = {
        "iterations": int(getattr(result, "nit", 0)),
        "status": int(getattr(result, "status", -1)),
        "message": str(getattr(result, "message", "")),
        "max_iter": int(max_iter),
        "gradient_inf_norm": float(np.max(np.abs(result.jac))) if result.jac is not None else None,
    }
    return point, diagnostics


# ------------------------------------------------------------------------ multipliers
def polish(
    problem: ConvexDecisionProblem,
    weights: Sequence[float],
    *,
    active_tolerance: float = 1e-7,
    rounds: int = 3,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Refine a candidate by solving the equality-constrained problem on its active set.

    A general solver stops at a feasibility tolerance, which leaves stationarity residuals
    around ``1e-8``. That is fine for reporting an allocation and useless for an exactness
    certificate, where the active set has to be identified without ambiguity. One Newton step
    on the active set recovers machine-precision weights when the active set is correct; the
    step is accepted only if the objective does not increase, so a wrong active set cannot
    make the candidate worse.
    """

    lower, upper = problem.bounds()
    q = problem.matrix()
    c = problem.cost_vector()
    a_matrix, d_vector = problem.inequality_arrays()
    n = problem.dimension
    current = np.clip(np.asarray(weights, dtype=float), lower, upper)
    best = float(problem.objective(current))
    accepted = 0
    for _ in range(max(1, rounds)):
        free = np.flatnonzero((current - lower > active_tolerance) &
                              (upper - current > active_tolerance))
        if free.size == 0:
            break
        pinned = np.setdiff1d(np.arange(n), free)
        active_rows = np.zeros(0, dtype=int)
        if a_matrix.shape[0]:
            slack = d_vector - a_matrix @ current
            active_rows = np.flatnonzero(slack <= active_tolerance)
        q_ff = q[np.ix_(free, free)]
        cross = q[np.ix_(free, pinned)] @ current[pinned] if pinned.size else np.zeros(free.size)
        rows = [np.ones(free.size)]
        rhs = [problem.budget - float(np.sum(current[pinned]))]
        for row in active_rows:
            rows.append(a_matrix[row, free])
            rhs.append(float(d_vector[row] - a_matrix[row, pinned] @ current[pinned]))
        a_eq = np.vstack(rows)
        b_eq = np.asarray(rhs, dtype=float)
        kkt = np.zeros((free.size + a_eq.shape[0],) * 2)
        kkt[:free.size, :free.size] = q_ff
        kkt[:free.size, free.size:] = a_eq.T
        kkt[free.size:, :free.size] = a_eq
        target = np.concatenate((-c[free] - cross, b_eq))
        try:
            solution = np.linalg.lstsq(kkt, target, rcond=None)[0]
        except np.linalg.LinAlgError:  # pragma: no cover - defensive
            break
        candidate = current.copy()
        candidate[free] = solution[:free.size]
        if np.any(candidate < lower - 1e-9) or np.any(candidate > upper + 1e-9):
            break
        if a_matrix.shape[0] and np.any(a_matrix @ candidate - d_vector > 1e-9):
            break
        value = float(problem.objective(candidate))
        if value > best + 1e-16:
            break
        current, best = candidate, value
        accepted += 1
    return current, {"accepted_steps": accepted, "objective": best}


def derive_multipliers(
    problem: ConvexDecisionProblem,
    weights: Sequence[float],
    *,
    active_tolerance: float = 1e-8,
) -> tuple[DualPoint | None, dict[str, Any]]:
    """Recover a multiplier vector for a *given* primal point by linear algebra alone.

    This is the cheap exactness test. For a fixed candidate ``w`` the KKT stationarity
    equation is linear in ``(nu, alpha, beta, gamma)`` once the active set is fixed, so the
    multipliers are a least-squares solve on the active coordinates. No optimisation occurs.

    The recovered multipliers are only a certificate if they satisfy the sign constraints and
    reproduce stationarity; both are checked and reported by the caller. When ``w`` is not
    optimal the residual is non-zero, which is how the routine detects non-optimality.
    """

    w = np.asarray(weights, dtype=float)
    n = problem.dimension
    lower, upper = problem.bounds()
    a_matrix, d_vector = problem.inequality_arrays()
    m = a_matrix.shape[0]

    # nu is free, so it enters as the difference of two non-negative columns. Without this
    # split, the non-negativity feasibility problem below is infeasible whenever the budget
    # multiplier is negative, which is common, and optimal corner solutions get rejected.
    columns: list[np.ndarray] = [np.ones(n), -np.ones(n)]
    labels: list[tuple[str, int]] = [("nu_pos", -1), ("nu_neg", -1)]
    at_lower: list[int] = []
    at_upper: list[int] = []
    fixed: list[int] = []
    for i in range(n):
        lo_gap = abs(w[i] - lower[i])
        hi_gap = abs(w[i] - upper[i])
        if upper[i] - lower[i] <= active_tolerance:
            fixed.append(i)
            continue
        if lo_gap <= active_tolerance and hi_gap <= active_tolerance:
            fixed.append(i)
        elif lo_gap <= active_tolerance:
            at_lower.append(i)
        elif hi_gap <= active_tolerance:
            at_upper.append(i)
    for i in fixed:
        column = np.zeros(n)
        column[i] = -1.0
        columns.append(column)
        labels.append(("fixed", i))
    for i in at_lower:
        column = np.zeros(n)
        column[i] = -1.0
        columns.append(column)
        labels.append(("alpha", i))
    for i in at_upper:
        column = np.zeros(n)
        column[i] = 1.0
        columns.append(column)
        labels.append(("beta", i))
    active_inequalities: list[int] = []
    if m:
        slack = d_vector - a_matrix @ w
        for j in range(m):
            if abs(slack[j]) <= active_tolerance:
                active_inequalities.append(j)
                columns.append(a_matrix[j])
                labels.append(("gamma", j))

    target = -(problem.matrix() @ w + problem.cost_vector())
    design = np.column_stack(columns)
    solution, _residuals, rank, _singular = np.linalg.lstsq(design, target, rcond=None)
    residual = float(np.max(np.abs(design @ solution - target))) if solution.size else float("inf")
    method = "least_squares"
    # The dual multipliers are constrained to be non-negative. When a solution sits on many
    # bounds at once the linear system is underdetermined: least squares returns the
    # minimum-norm representative, which can contain a small negative multiplier even though a
    # non-negative solution with the same (zero) residual exists. That produced a spurious
    # "not optimal" verdict on perfectly optimal corner solutions, so in that case the system is
    # re-solved under the sign constraint and the constrained solution is preferred whenever it
    # fits the stationarity equation at least as well.
    negative = float(np.min(solution[1:])) if solution.size > 1 else 0.0
    if negative < -1e-12 or residual > 1e-8:
        # Ask the exact question the certificate needs: is there a *non-negative* multiplier
        # vector satisfying stationarity? A bounded least-squares solve is not sufficient here
        # because the system is consistent and underdetermined, so the residual is already zero
        # and only the sign of the null-space representative is wrong. A feasibility LP answers
        # it directly.
        try:
            feasibility = optimize.linprog(
                np.ones(design.shape[1]),
                A_eq=design,
                b_eq=target,
                bounds=[(0.0, None)] * design.shape[1],
                method="highs",
            )
            if feasibility.success and feasibility.x is not None:
                candidate = np.asarray(feasibility.x, dtype=float)
                candidate_residual = float(np.max(np.abs(design @ candidate - target)))
                if candidate_residual <= max(residual, 1e-9) + 1e-9 and candidate_residual <= 1e-7:
                    solution, residual, method = candidate, candidate_residual, "nonnegative_lp"
        except (ValueError, np.linalg.LinAlgError):  # pragma: no cover - defensive
            pass

    alpha = np.zeros(n)
    beta = np.zeros(n)
    gamma = np.zeros(m)
    sign_violation = 0.0
    nu = 0.0
    for (kind, index), value in zip(labels, solution):
        if kind == "nu_pos":
            nu += float(value)
            continue
        if kind == "nu_neg":
            nu -= float(value)
            continue
        if kind == "alpha":
            alpha[index] = float(value)
            sign_violation = max(sign_violation, max(0.0, -float(value)))
        elif kind == "beta":
            beta[index] = float(value)
            sign_violation = max(sign_violation, max(0.0, -float(value)))
        elif kind == "fixed":
            # A coordinate pinned by lower == upper carries one signed multiplier that may
            # be split arbitrarily between the two bounds; keep the split non-negative.
            value = float(value)
            if value >= 0:
                beta[index] = value
            else:
                alpha[index] = -value
        elif kind == "gamma":
            gamma[index] = float(value)
            sign_violation = max(sign_violation, max(0.0, -float(value)))
    point = DualPoint(nu=float(nu), alpha=tuple(alpha), beta=tuple(beta),
                      gamma=tuple(gamma) if m else ())
    diagnostics = {
        "rank": int(rank),
        "design_columns": int(design.shape[1]),
        "residual": residual,
        "recovery_method": method,
        "sign_violation": sign_violation,
        "active_lower": at_lower,
        "active_upper": at_upper,
        "fixed": fixed,
        "active_inequalities": active_inequalities,
    }
    return point, diagnostics


def verify_kkt(
    problem: ConvexDecisionProblem,
    weights: Sequence[float],
    point: DualPoint | None = None,
    *,
    tolerance: float | None = None,
) -> KKTReport:
    """Check the KKT system of the convex program at ``(w, multipliers)``.

    For a convex program with linear constraints the KKT conditions are sufficient for global
    optimality, and constraint qualification always holds, so they are also necessary. A
    ``satisfied`` report is therefore an optimality certificate for the *specified* program,
    and a report with a large residual is evidence that ``w`` is not optimal. Neither
    statement says anything about the real world.
    """

    w = np.asarray(weights, dtype=float)
    if tolerance is None:
        tolerance = KKT_TOLERANCE * gradient_scale(problem, w)
    feasibility = check_feasibility(problem, w, tolerance=tolerance)
    if point is None:
        point, diagnostics = derive_multipliers(problem, w)
        if point is None:
            return KKTReport(0.0, 0.0, 0.0, feasibility.max_violation, tolerance, False,
                             reason="no multipliers recovered", multipliers=None)
    else:
        diagnostics = {}
    alpha = np.asarray(point.alpha, dtype=float)
    beta = np.asarray(point.beta, dtype=float)
    gamma = np.asarray(point.gamma, dtype=float)
    a_matrix, d_vector = problem.inequality_arrays()
    lower, upper = problem.bounds()
    stationarity = problem.matrix() @ w + problem.cost_vector() + point.nu - alpha + beta
    if a_matrix.shape[0]:
        stationarity = stationarity + a_matrix.T @ gamma
    stationarity_norm = float(np.max(np.abs(stationarity))) if stationarity.size else 0.0
    dual_feasibility = 0.0
    if alpha.size:
        dual_feasibility = max(dual_feasibility, max(0.0, float(-np.min(alpha))))
    if beta.size:
        dual_feasibility = max(dual_feasibility, max(0.0, float(-np.min(beta))))
    if gamma.size:
        dual_feasibility = max(dual_feasibility, max(0.0, float(-np.min(gamma))))
    complementarity = 0.0
    if alpha.size:
        complementarity = max(complementarity, float(np.max(np.abs(alpha * (w - lower)))))
    if beta.size:
        complementarity = max(complementarity, float(np.max(np.abs(beta * (upper - w)))))
    if gamma.size:
        complementarity = max(complementarity, float(np.max(np.abs(gamma * (d_vector - a_matrix @ w)))))
    satisfied = (
        feasibility.feasible
        and stationarity_norm <= tolerance
        and dual_feasibility <= tolerance
        and complementarity <= tolerance
    )
    reason = None if satisfied else _kkt_reason(
        stationarity_norm, dual_feasibility, complementarity, feasibility.max_violation, tolerance
    )
    return KKTReport(
        stationarity=stationarity_norm,
        dual_feasibility=dual_feasibility,
        complementarity=complementarity,
        primal_feasibility=feasibility.max_violation,
        tolerance=tolerance,
        satisfied=satisfied,
        multipliers=point,
        reason=reason,
    )


def _kkt_reason(stationarity: float, dual: float, complementarity: float, primal: float,
                tolerance: float) -> str:
    failures = []
    if primal > tolerance:
        failures.append(f"primal feasibility {primal:.3e}")
    if stationarity > tolerance:
        failures.append(f"stationarity {stationarity:.3e}")
    if dual > tolerance:
        failures.append(f"dual feasibility {dual:.3e}")
    if complementarity > tolerance:
        failures.append(f"complementarity {complementarity:.3e}")
    return "; ".join(failures)


# ------------------------------------------------------------------------ primal solve
def _slsqp_solve(
    problem: ConvexDecisionProblem,
    start: np.ndarray,
    *,
    tolerance: float,
    max_iter: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    q = problem.matrix()
    c = problem.cost_vector()
    a_matrix, d_vector = problem.inequality_arrays()

    def objective(w: np.ndarray) -> float:
        return float(0.5 * w @ q @ w + c @ w)

    def gradient(w: np.ndarray) -> np.ndarray:
        return q @ w + c

    def budget(w: np.ndarray) -> float:
        return float(np.sum(w) - problem.budget)

    def budget_jac(w: np.ndarray) -> np.ndarray:
        return np.ones_like(w)

    constraints: list[dict[str, Any]] = [
        {"type": "eq", "fun": budget, "jac": budget_jac}
    ]
    if a_matrix.shape[0]:
        constraints.append({
            "type": "ineq",
            "fun": lambda w: d_vector - a_matrix @ w,
            "jac": lambda w: -a_matrix,
        })
    bounds = list(zip(problem.lower, problem.upper))
    result = optimize.minimize(
        objective,
        start,
        jac=gradient,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": int(max_iter), "ftol": tolerance, "disp": False},
    )
    diagnostics = {
        "status": int(getattr(result, "status", -1)),
        "message": str(getattr(result, "message", "")),
        "iterations": int(getattr(result, "nit", 0)),
        "solver_success": bool(getattr(result, "success", False)),
        "nfev": int(getattr(result, "nfev", 0)),
    }
    return np.asarray(result.x, dtype=float), diagnostics


def restore_budget(problem: ConvexDecisionProblem, weights: Sequence[float]) -> np.ndarray:
    """Project onto the budget equality while respecting the box and the linear rows.

    A general solver can stop a few ulps outside the equality. The projection is a feasibility
    restoration step only: it never changes which objective is optimised.
    """

    w = np.clip(np.asarray(weights, dtype=float), problem.lower, problem.upper).copy()
    a_matrix, d_vector = problem.inequality_arrays()
    for _ in range(2 * problem.dimension + 8):
        residual = problem.budget - float(np.sum(w))
        if abs(residual) <= 1e-12:
            break
        moved = False
        for index in range(problem.dimension):
            if abs(residual) <= 1e-12:
                break
            lower, upper = problem.lower[index], problem.upper[index]
            room = (upper - w[index]) if residual > 0 else (w[index] - lower)
            if room <= 1e-15:
                continue
            step = math.copysign(min(abs(residual), room), residual)
            candidate = w.copy()
            candidate[index] += step
            if a_matrix.shape[0] and np.any(a_matrix @ candidate - d_vector > 1e-12):
                continue
            w = candidate
            residual -= step
            moved = True
        if not moved:
            break
    return w


def initial_feasible_point(problem: ConvexDecisionProblem) -> np.ndarray:
    """A deterministic feasible start: clip the equal split into the box, then the budget.

    This is a heuristic and is allowed to be infeasible when the budget cannot be met with
    the box; the solver then reports infeasibility instead of silently repairing it.
    """

    n = problem.dimension
    lower, upper = problem.bounds()
    w = np.clip(np.full(n, problem.budget / n), lower, upper)
    return w


def solve(
    problem: ConvexDecisionProblem,
    *,
    warm_start: Sequence[float] | None = None,
    tolerance: float = 1e-12,
    max_iter: int = 500,
    dual_iterations: int = 200,
    kkt_tolerance: float | None = None,
) -> QPSolution:
    """Solve the canonical convex program and report self-certifying diagnostics.

    Failure modes are explicit: an infeasible box/budget combination returns
    ``status="infeasible"`` with a reason; a non-converged primal still returns its weights
    and gap so the caller can decide whether the gap is small enough to use.
    """

    started = time.perf_counter()
    lower, upper = problem.bounds()
    if float(np.sum(lower)) > problem.budget + DEFAULT_TOLERANCE:
        return _failure(problem, "infeasible", "the lower bounds already exceed the budget",
                        started, "budget_infeasible")
    if float(np.sum(upper)) < problem.budget - DEFAULT_TOLERANCE:
        return _failure(problem, "infeasible", "the upper bounds cannot reach the budget",
                        started, "budget_infeasible")

    start = initial_feasible_point(problem) if warm_start is None else _project_box(
        np.asarray(warm_start, dtype=float), lower, upper
    )
    # Objective scaling. Dividing Q and c by one positive constant leaves the optimal set
    # unchanged but keeps a general-purpose solver in the range where its stopping tests mean
    # something: a capacity program with a 2.6e6 objective previously stopped with a 3e-7
    # budget residual and was reported infeasible. The scale is recorded, and the dual
    # multipliers are multiplied back so every reported quantity is in original units.
    scale = max(float(np.max(np.abs(problem.matrix()))),
                float(np.max(np.abs(problem.cost_vector()))), 1e-12)
    scaled_risk = tuple(tuple(float(v) / scale for v in row) for row in problem.risk_matrix)
    scaled_costs = tuple(float(v) / scale for v in problem.linear_costs)
    scaled = problem.replace(
        problem_id=f"{problem.problem_id}::scaled",
        risk_matrix=scaled_risk,
        linear_costs=scaled_costs,
    )
    weights, diagnostics = _slsqp_solve(scaled, start, tolerance=tolerance, max_iter=max_iter)
    weights = restore_budget(problem, weights)
    weights, polish_diagnostics = polish(problem, weights)
    diagnostics["polish"] = polish_diagnostics
    diagnostics["objective_scale"] = scale
    effective_tolerance = (KKT_TOLERANCE if kkt_tolerance is None else kkt_tolerance) * \
        gradient_scale(problem, weights)
    feasibility = check_feasibility(problem, weights, tolerance=effective_tolerance)

    try:
        scaled_point, dual_diagnostics = maximize_dual(scaled, max_iter=dual_iterations)
        point = DualPoint(
            nu=scaled_point.nu * scale,
            alpha=tuple(v * scale for v in scaled_point.alpha),
            beta=tuple(v * scale for v in scaled_point.beta),
            gamma=tuple(v * scale for v in scaled_point.gamma),
        )
        value, _unused, _grad = dual_objective(problem, point)
        if math.isfinite(value):
            point = DualPoint(nu=point.nu, alpha=point.alpha, beta=point.beta,
                              gamma=point.gamma, value=value)
            dual_bound = float(value)
        else:
            dual_bound = None
    except ValidationError as exc:
        point, dual_diagnostics, dual_bound = None, {"error": str(exc)}, None
    dual_valid = True

    kkt_point, multiplier_diagnostics = derive_multipliers(problem, weights)
    if point is not None and dual_bound is not None and dual_valid:
        # Prefer whichever multiplier set verifies stationarity; the least-squares recovery is
        # exact for an optimal point and is therefore the natural certificate candidate.
        if kkt_point is not None:
            recovered = verify_kkt(problem, weights, kkt_point, tolerance=kkt_tolerance)
            if recovered.satisfied:
                kkt = recovered
            else:
                kkt = verify_kkt(problem, weights, point, tolerance=kkt_tolerance)
        else:
            kkt = verify_kkt(problem, weights, point, tolerance=kkt_tolerance)
    else:
        kkt = verify_kkt(problem, weights, kkt_point, tolerance=kkt_tolerance)

    objective = problem.objective(weights)
    gap = None
    if dual_bound is not None:
        gap = objective - dual_bound
        if gap < 0:
            if gap > -1e-7:
                gap = 0.0
            else:
                # Weak duality makes a negative gap impossible; treat it as a numerical
                # failure and refuse the bound rather than report an unattainable one.
                dual_valid = False
                diagnostics["dual_rejected"] = f"dual bound {dual_bound} exceeded primal {objective}"
                dual_bound = None
                gap = None
    certified = bool(kkt.satisfied and (gap is None or gap <= effective_tolerance))
    if not feasibility.feasible:
        status = "infeasible"
    elif certified:
        status = "optimal"
    elif gap is not None and gap <= 1e-6:
        status = "near_optimal"
    else:
        status = "feasible_uncertified"
    runtime_ms = (time.perf_counter() - started) * 1000.0
    return QPSolution(
        status=status,
        weights=tuple(float(v) for v in weights),
        objective=objective,
        feasible=feasibility.feasible,
        max_violation=feasibility.max_violation,
        kkt=kkt,
        dual_bound=dual_bound,
        duality_gap=gap,
        certified_optimal=certified,
        dual=point,
        solver="scipy-slsqp-primal/dual-lbfgsb-multipliers",
        iterations=int(diagnostics.get("iterations", 0)),
        runtime_ms=runtime_ms,
        diagnostics={
            "primal": diagnostics,
            "dual": dual_diagnostics,
            "multipliers": multiplier_diagnostics,
            "feasibility": feasibility.as_dict(),
            "solver_versions": _solver_versions(),
        },
    )


def _solver_versions() -> dict[str, str]:
    import scipy

    return {"scipy": scipy.__version__, "numpy": np.__version__}


def _project_box(w: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    if w.shape != lower.shape:
        raise ValidationError("warm start must match problem dimension",
                              expected=int(lower.size), received=list(w.shape))
    return np.clip(w, lower, upper)


def _failure(problem: ConvexDecisionProblem, status: str, reason: str, started: float,
             code: str) -> QPSolution:
    empty = KKTReport(0.0, 0.0, 0.0, float("inf"), KKT_TOLERANCE, False, reason=reason)
    return QPSolution(
        status=status,
        weights=tuple(0.0 for _ in range(problem.dimension)),
        objective=float("nan"),
        feasible=False,
        max_violation=float("inf"),
        kkt=empty,
        dual_bound=None,
        duality_gap=None,
        certified_optimal=False,
        dual=None,
        solver="scipy-slsqp-primal/dual-lbfgsb-multipliers",
        iterations=0,
        runtime_ms=(time.perf_counter() - started) * 1000.0,
        diagnostics={"failure_code": code, "reason": reason},
    )


__all__ = [
    "DUAL_SCHEMA",
    "KKT_SCHEMA",
    "KKT_TOLERANCE",
    "QP_SCHEMA",
    "DualPoint",
    "KKTReport",
    "QPSolution",
    "derive_multipliers",
    "gradient_scale",
    "restore_budget",
    "dual_objective",
    "initial_feasible_point",
    "maximize_dual",
    "solve",
    "verify_kkt",
]
