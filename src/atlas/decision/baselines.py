"""Classical baselines and competing regret bounds.

The research claim in this pass is about *certificates*, so the baselines have to be honest
alternatives rather than strawmen. There are two families.

**Decision baselines** answer "what should have been held?": equal weight, a single asset
(cash or minimum-risk), minimum variance, mean-variance, a fixed-radius robust counterpart,
and a mean-CVaR programme. The first four are parameter-free; the last two are tuned on a
validation window with the same budget as the proposed method.

**Bound baselines** answer "how large could the regret be?" without re-solving: a
strong-convexity bound derived from the gradient norm, and a first-order Taylor estimate.
The strong-convexity bound is mathematically valid and is the fair competitor to the duality
bound. The Taylor estimate is *not* a bound, and the experiments report how often it
understates the true regret, because it is a widely used surrogate for "impact".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from scipy import optimize

from ..core.errors import ValidationError
from .problem import ConvexDecisionProblem
from .qp import QPSolution, solve

BASELINE_SCHEMA = "atlas.decision.baseline.v1"


@dataclass(frozen=True, slots=True)
class BaselineResult:
    name: str
    weights: tuple[float, ...]
    objective: float
    feasible: bool
    diagnostics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": BASELINE_SCHEMA,
            "name": self.name,
            "weights": list(self.weights),
            "objective": self.objective,
            "feasible": self.feasible,
            "diagnostics": dict(self.diagnostics),
        }


def _water_fill(problem: ConvexDecisionProblem, target: np.ndarray) -> np.ndarray:
    """Clip a target allocation into the box, then redistribute the budget residual.

    Deterministic and geometry-preserving: the remainder goes to the coordinates with the
    most room, in index order, which makes ties reproducible.
    """

    lower, upper = problem.bounds()
    w = np.clip(target, lower, upper)
    for _ in range(4 * problem.dimension + 8):
        residual = problem.budget - float(np.sum(w))
        if abs(residual) <= 1e-12:
            break
        room = (upper - w) if residual > 0 else (w - lower)
        candidates = np.flatnonzero(room > 1e-15)
        if candidates.size == 0:
            break
        share = residual / float(candidates.size)
        for index in candidates:
            delta = max(-room[index], min(room[index], share))
            w[index] += delta
    return w


def equal_weight(problem: ConvexDecisionProblem) -> BaselineResult:
    n = problem.dimension
    target = np.full(n, problem.budget / n)
    w = _water_fill(problem, target)
    return BaselineResult("equal_weight", tuple(float(v) for v in w), problem.objective(w),
                          bool(abs(np.sum(w) - problem.budget) < 1e-8),
                          {"note": "budget split equally, then clipped into the box"})


def single_asset(problem: ConvexDecisionProblem, index: int, *, name: str = "single_asset") -> BaselineResult:
    """Put the whole budget into one variable: the cash or minimum-risk policy."""

    if not 0 <= index < problem.dimension:
        raise ValidationError("asset index out of range", index=index, dimension=problem.dimension)
    target = np.zeros(problem.dimension)
    target[index] = problem.budget
    w = _water_fill(problem, target)
    return BaselineResult(name, tuple(float(v) for v in w), problem.objective(w),
                          bool(abs(np.sum(w) - problem.budget) < 1e-8),
                          {"asset": problem.variables[index]})


def minimum_variance(problem: ConvexDecisionProblem) -> BaselineResult:
    zero_cost = problem.replace(problem_id=f"{problem.problem_id}::minvar",
                                linear_costs=tuple(0.0 for _ in range(problem.dimension)))
    solution: QPSolution = solve(zero_cost)
    return BaselineResult("minimum_variance", solution.weights, problem.objective(solution.weights),
                          solution.feasible, {"solver_status": solution.status,
                                              "certified_optimal": solution.certified_optimal})


def mean_variance(problem: ConvexDecisionProblem) -> BaselineResult:
    solution = solve(problem)
    return BaselineResult("mean_variance", solution.weights, solution.objective, solution.feasible,
                          {"solver_status": solution.status,
                           "certified_optimal": solution.certified_optimal,
                           "duality_gap": solution.duality_gap})


def robust_box(problem: ConvexDecisionProblem, radius: float, *,
               max_iter: int = 500) -> BaselineResult:
    """Worst-case linear cost over the box ``|delta_i| <= radius``.

    The counterpart is exact: the worst-case term is ``radius * ||w||_1``, represented with
    auxiliary variables ``s >= |w|``. No sampling and no approximation.
    """

    if radius < 0 or not math.isfinite(radius):
        raise ValidationError("radius must be finite and non-negative", radius=radius)
    n = problem.dimension
    q = problem.matrix()
    c = problem.cost_vector()
    lower, upper = problem.bounds()

    def objective(x: np.ndarray) -> float:
        w, s = x[:n], x[n:]
        return float(0.5 * w @ q @ w + c @ w + radius * np.sum(s))

    def gradient(x: np.ndarray) -> np.ndarray:
        w = x[:n]
        grad = np.concatenate((q @ w + c, np.full(n, radius)))
        return grad

    bounds = list(zip(lower, upper)) + [(0.0, None)] * n
    constraints = [
        {"type": "eq", "fun": lambda x: float(np.sum(x[:n]) - problem.budget),
         "jac": lambda x: np.concatenate((np.ones(n), np.zeros(n)))},
        {"type": "ineq", "fun": lambda x: x[n:] - x[:n],
         "jac": lambda x: np.hstack((-np.eye(n), np.eye(n)))},
        {"type": "ineq", "fun": lambda x: x[n:] + x[:n],
         "jac": lambda x: np.hstack((np.eye(n), np.eye(n)))},
    ]
    start = _water_fill(problem, np.full(n, problem.budget / n))
    guess = np.concatenate((start, np.abs(start)))
    result = optimize.minimize(objective, guess, jac=gradient, method="SLSQP", bounds=bounds,
                               constraints=constraints,
                               options={"maxiter": max_iter, "ftol": 1e-12, "disp": False})
    w = np.clip(np.asarray(result.x[:n], dtype=float), lower, upper)
    feasible = abs(float(np.sum(w)) - problem.budget) <= 1e-7
    return BaselineResult("robust_box", tuple(float(v) for v in w), problem.objective(w), feasible, {
        "radius": radius,
        "solver_status": int(getattr(result, "status", -1)),
        "solver_success": bool(getattr(result, "success", False)),
        "worst_case_objective": float(objective(np.asarray(result.x, dtype=float))),
        "ambiguity_set": "box on linear costs, half-width radius",
    })


def robust_ellipsoid(problem: ConvexDecisionProblem, radius: float, *,
                    max_iter: int = 500) -> BaselineResult:
    """Worst-case linear cost over the ellipsoid ``||delta||_2 <= radius``.

    The counterpart is ``min 0.5 w'Qw + c'w + radius * ||w||_2``, solved with an auxiliary
    epigraph variable. Unlike :func:`robust_box`, this baseline is **not** vacuous under a
    budget equality with non-negative weights: ``||w||_1`` is constant on that set, so a box
    ambiguity cancels out of the objective, while ``||w||_2`` still penalises concentration.
    That distinction matters for the comparison, so both are kept and labelled.
    """

    if radius < 0 or not math.isfinite(radius):
        raise ValidationError("radius must be finite and non-negative", radius=radius)
    n = problem.dimension
    q = problem.matrix()
    c = problem.cost_vector()
    lower, upper = problem.bounds()

    def objective(x: np.ndarray) -> float:
        w, t = x[:n], x[n]
        return float(0.5 * w @ q @ w + c @ w + radius * t)

    def gradient(x: np.ndarray) -> np.ndarray:
        return np.concatenate((q @ x[:n] + c, np.array([radius])))

    bounds = list(zip(lower, upper)) + [(0.0, None)]
    constraints = [
        {"type": "eq", "fun": lambda x: float(np.sum(x[:n]) - problem.budget),
         "jac": lambda x: np.concatenate((np.ones(n), np.zeros(1)))},
        {"type": "ineq", "fun": lambda x: float(x[n] ** 2 - x[:n] @ x[:n]),
         "jac": lambda x: np.concatenate((-2.0 * x[:n], np.array([2.0 * x[n]])))},
    ]
    start = _water_fill(problem, np.full(n, problem.budget / n))
    guess = np.concatenate((start, np.array([float(np.linalg.norm(start))])))
    result = optimize.minimize(objective, guess, jac=gradient, method="SLSQP", bounds=bounds,
                               constraints=constraints,
                               options={"maxiter": max_iter, "ftol": 1e-12, "disp": False})
    w = np.clip(np.asarray(result.x[:n], dtype=float), lower, upper)
    feasible = abs(float(np.sum(w)) - problem.budget) <= 1e-7
    return BaselineResult("robust_ellipsoid", tuple(float(v) for v in w), problem.objective(w),
                          feasible, {
        "radius": radius,
        "solver_status": int(getattr(result, "status", -1)),
        "solver_success": bool(getattr(result, "success", False)),
        "worst_case_objective": float(objective(np.asarray(result.x, dtype=float))),
        "ambiguity_set": "euclidean ball on linear costs, radius",
    })


def mean_cvar(
    problem: ConvexDecisionProblem,
    scenario_returns: Sequence[Sequence[float]],
    *,
    alpha: float = 0.95,
) -> BaselineResult:
    """Rockafellar-Uryasev mean-CVaR linear programme over a scenario set.

    ``scenario_returns[s][i]`` is the return of variable ``i`` in scenario ``s``. The
    objective is the scenario mean return minus the CVaR of the loss, and the problem is
    solved with HiGHS so the result is deterministic for a fixed input.
    """

    scenarios = np.asarray(scenario_returns, dtype=float)
    n = problem.dimension
    if scenarios.ndim != 2 or scenarios.shape[1] != n:
        raise ValidationError("scenario_returns must be (scenarios, variables)",
                              shape=list(scenarios.shape), dimension=n)
    if not 0.0 < alpha < 1.0:
        raise ValidationError("alpha must be in (0, 1)", alpha=alpha)
    count = scenarios.shape[0]
    means = scenarios.mean(axis=0)
    lower, upper = problem.bounds()
    # Variables: w (n), eta (1), z (count).
    total = n + 1 + count
    cost = np.concatenate((-means, [1.0], np.full(count, 1.0 / ((1.0 - alpha) * count))))
    a_ub = np.zeros((count, total))
    a_ub[:, :n] = -scenarios
    a_ub[:, n] = -1.0
    a_ub[:, n + 1:] = -np.eye(count)
    b_ub = np.zeros(count)
    a_eq = np.zeros((1, total))
    a_eq[0, :n] = 1.0
    b_eq = np.array([problem.budget])
    bounds = list(zip(lower, upper)) + [(None, None)] + [(0.0, None)] * count
    result = optimize.linprog(cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds,
                              method="highs")
    if not result.success:
        raise ValidationError("mean-CVaR linear programme failed", message=str(result.message))
    w = np.clip(np.asarray(result.x[:n], dtype=float), lower, upper)
    return BaselineResult("mean_cvar", tuple(float(v) for v in w), problem.objective(w),
                          abs(float(np.sum(w)) - problem.budget) <= 1e-7, {
        "alpha": alpha,
        "scenarios": count,
        "cvar_objective": float(result.fun),
        "solver": "highs",
        "note": "the objective optimized here is mean-CVaR, not the quadratic program",
    })


# ---------------------------------------------------------------------- bound baselines
def strong_convexity_bound(problem: ConvexDecisionProblem, weights: Sequence[float]) -> dict[str, Any]:
    """``f(w) - f* <= ||grad f(w)||^2 / (2 m)`` with ``m`` the smallest risk-matrix eigenvalue.

    Valid whenever ``m > 0``. It needs no dual information, which makes it the natural
    like-for-like competitor to the duality bound: both are one linear solve away.
    """

    w = np.asarray(weights, dtype=float)
    eigenvalues = np.linalg.eigvalsh(problem.matrix())
    modulus = float(eigenvalues[0])
    gradient = problem.gradient(w)
    norm = float(np.linalg.norm(gradient))
    if modulus <= 0:
        return {"bound": None, "valid": False, "modulus": modulus, "gradient_norm": norm,
                "reason": "the risk matrix is singular so the objective is not strongly convex"}
    return {"bound": norm ** 2 / (2.0 * modulus), "valid": True, "modulus": modulus,
            "gradient_norm": norm, "reason": None, "method": "strong_convexity"}


def first_order_estimate(old_cost: Sequence[float], new_cost: Sequence[float],
                        weights: Sequence[float]) -> dict[str, Any]:
    """``(c_new - c_old)' w``: the first-order change in the objective at fixed weights.

    Reported as an **estimate**. It is the change in the *reported objective*, not in the
    regret, because it ignores the movement of the optimum. The experiments count how often
    it understates the true regret; that count is the argument against using it as an impact
    measure.
    """

    delta = np.asarray(new_cost, dtype=float) - np.asarray(old_cost, dtype=float)
    w = np.asarray(weights, dtype=float)
    return {"estimate": float(delta @ w), "method": "first_order_fixed_weights",
            "valid_bound": False}


__all__ = [
    "BASELINE_SCHEMA",
    "BaselineResult",
    "equal_weight",
    "first_order_estimate",
    "mean_cvar",
    "mean_variance",
    "minimum_variance",
    "robust_box",
    "robust_ellipsoid",
    "single_asset",
    "strong_convexity_bound",
]
