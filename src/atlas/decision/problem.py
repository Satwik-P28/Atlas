"""Canonical convex decision problems for the Decision Research Lab.

A decision problem is a *convex program*, not a trading strategy. The schema here is the
single interface every other decision component speaks: the solver, the revision compiler,
the certificate layer, the classical baselines, the experiment harness and the API.

The canonical form is::

    minimize     0.5 * w' Q w + c' w
    subject to   sum_i w_i = budget                      (budget equality, dual nu)
                 lower_i <= w_i <= upper_i               (boxes, duals alpha/beta)
                 A_j w <= d_j                            (optional rows, dual gamma)

`Q` must be symmetric positive semidefinite and `c` finite. Mean-variance portfolio
allocation is one instantiation (``Q = risk_aversion * Sigma``, ``c = -mu``); an inventory
or capacity allocation with quadratic smoothing is another. Keeping the canonical form
separate from the financial reading is what makes the certificate layer reusable outside
finance without a second implementation.

Why the canonical form and not a generic modelling language: a certificate has to be
*checkable*. Restricting the program to a quadratic objective with linear constraints keeps
the KKT system explicit, so optimality can be verified from the primal solution and a
multiplier vector alone, with residuals reported instead of asserted.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from ..core.errors import ValidationError

PROBLEM_SCHEMA = "atlas.decision.problem.v1"
FEASIBILITY_SCHEMA = "atlas.decision.feasibility.v1"

#: Relative tolerance used for symmetric/PSD validation and for constraint checks. It is
#: deliberately loose enough to accept a covariance rebuilt from rounded decimals and tight
#: enough that a genuinely indefinite matrix is rejected.
DEFAULT_TOLERANCE = 1e-8

#: Tolerance on the minimum eigenvalue as a fraction of the largest eigenvalue. A sample
#: covariance from fewer observations than assets is singular but still admissible.
PSD_RTOL = 1e-10


@dataclass(frozen=True, slots=True)
class LinearInequality:
    """One row ``coefficients @ w <= bound`` with a human-readable label."""

    coefficients: tuple[float, ...]
    bound: float
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"coefficients": list(self.coefficients), "bound": self.bound, "label": self.label}


@dataclass(frozen=True, slots=True)
class ConvexDecisionProblem:
    """A fully specified convex decision instance.

    ``evidence_ids`` and ``as_of`` are provenance, not decoration: the revision compiler
    refuses to perturb a problem with evidence that was not available at ``as_of``, and the
    saved record uses them to explain which inputs produced the decision.
    """

    problem_id: str
    variables: tuple[str, ...]
    linear_costs: tuple[float, ...]
    risk_matrix: tuple[tuple[float, ...], ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    budget: float
    inequalities: tuple[LinearInequality, ...] = ()
    semantics: str = "generic_convex"
    as_of: str | None = None
    evidence_ids: tuple[str, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ validation
    def __post_init__(self) -> None:
        n = len(self.variables)
        if n == 0:
            raise ValidationError("a decision problem needs at least one variable")
        if len(self.linear_costs) != n:
            raise ValidationError("linear_costs must match variables", variables=n,
                                  costs=len(self.linear_costs))
        if len(self.risk_matrix) != n or any(len(row) != n for row in self.risk_matrix):
            raise ValidationError("risk_matrix must be square and match variables", variables=n)
        for name, values in (("lower", self.lower), ("upper", self.upper)):
            if len(values) != n:
                raise ValidationError(f"{name} must match variables", variables=n, received=len(values))
        for value in (*self.linear_costs, self.budget, *self.lower, *self.upper):
            if not math.isfinite(value):
                raise ValidationError("decision problem values must be finite", value=value)
        for i, (lo, hi) in enumerate(zip(self.lower, self.upper)):
            if lo > hi:
                raise ValidationError("lower bound exceeds upper bound", variable=self.variables[i],
                                      lower=lo, upper=hi)
        for row in self.inequalities:
            if len(row.coefficients) != n:
                raise ValidationError("inequality row must match variables", label=row.label)
            if not math.isfinite(row.bound) or any(not math.isfinite(v) for v in row.coefficients):
                raise ValidationError("inequality coefficients must be finite", label=row.label)
        self._validated_risk_matrix()

    def _validated_risk_matrix(self) -> np.ndarray:
        matrix = np.asarray(self.risk_matrix, dtype=float)
        if not np.all(np.isfinite(matrix)):
            raise ValidationError("risk_matrix must contain finite values")
        scale = float(np.max(np.abs(matrix))) or 1.0
        if not np.allclose(matrix, matrix.T, rtol=1e-9, atol=DEFAULT_TOLERANCE * scale):
            raise ValidationError("risk_matrix must be symmetric")
        eigenvalues = np.linalg.eigvalsh((matrix + matrix.T) / 2.0)
        if float(eigenvalues[0]) < -PSD_RTOL * max(abs(float(eigenvalues[-1])), 1.0):
            raise ValidationError("risk_matrix must be positive semidefinite",
                                  min_eigenvalue=float(eigenvalues[0]))
        return matrix

    # ------------------------------------------------------------------ accessors
    @property
    def dimension(self) -> int:
        return len(self.variables)

    def matrix(self) -> np.ndarray:
        """The risk matrix as a fresh float array (never a live view into the dataclass)."""

        return np.asarray(self.risk_matrix, dtype=float).copy()

    def cost_vector(self) -> np.ndarray:
        return np.asarray(self.linear_costs, dtype=float).copy()

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return (np.asarray(self.lower, dtype=float).copy(), np.asarray(self.upper, dtype=float).copy())

    def inequality_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.inequalities:
            return (np.zeros((0, self.dimension)), np.zeros(0))
        matrix = np.asarray([row.coefficients for row in self.inequalities], dtype=float)
        return (matrix, np.asarray([row.bound for row in self.inequalities], dtype=float))

    def objective(self, weights: Sequence[float]) -> float:
        w = np.asarray(weights, dtype=float)
        if w.shape != (self.dimension,):
            raise ValidationError("weights must match problem dimension",
                                  expected=self.dimension, received=list(np.shape(w)))
        q = self.matrix()
        return float(0.5 * w @ q @ w + self.cost_vector() @ w)

    def gradient(self, weights: Sequence[float]) -> np.ndarray:
        w = np.asarray(weights, dtype=float)
        return self.matrix() @ w + self.cost_vector()

    # ------------------------------------------------------------------ identity
    def canonical_payload(self) -> dict[str, Any]:
        """Deterministic, hashable description of the mathematical problem.

        Provenance fields (``as_of``, ``evidence_ids``, ``labels``) are excluded: two
        instances with the same mathematics but different evidence clocks are the same
        program, which is exactly what the revision compiler needs to reason about.
        """

        return {
            "problem_id": self.problem_id,
            "variables": list(self.variables),
            "linear_costs": [float(v) for v in self.linear_costs],
            "risk_matrix": [[float(v) for v in row] for row in self.risk_matrix],
            "lower": [float(v) for v in self.lower],
            "upper": [float(v) for v in self.upper],
            "budget": float(self.budget),
            "inequalities": [row.as_dict() for row in self.inequalities],
            "semantics": self.semantics,
        }

    def digest(self) -> str:
        payload = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def replace(self, **changes: Any) -> "ConvexDecisionProblem":
        data = {
            "problem_id": self.problem_id,
            "variables": self.variables,
            "linear_costs": self.linear_costs,
            "risk_matrix": self.risk_matrix,
            "lower": self.lower,
            "upper": self.upper,
            "budget": self.budget,
            "inequalities": self.inequalities,
            "semantics": self.semantics,
            "as_of": self.as_of,
            "evidence_ids": self.evidence_ids,
            "labels": self.labels,
        }
        data.update(changes)
        return ConvexDecisionProblem(**data)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PROBLEM_SCHEMA,
            "problem_id": self.problem_id,
            "semantics": self.semantics,
            "variables": list(self.variables),
            "linear_costs": [float(v) for v in self.linear_costs],
            "risk_matrix": [[float(v) for v in row] for row in self.risk_matrix],
            "lower": [float(v) for v in self.lower],
            "upper": [float(v) for v in self.upper],
            "budget": float(self.budget),
            "inequalities": [row.as_dict() for row in self.inequalities],
            "as_of": self.as_of,
            "evidence_ids": list(self.evidence_ids),
            "labels": dict(self.labels),
            "digest": self.digest(),
            "dimension": self.dimension,
        }


# ---------------------------------------------------------------------- construction
def mean_variance_problem(
    *,
    problem_id: str,
    assets: Sequence[str],
    expected_returns: Sequence[float],
    covariance: Sequence[Sequence[float]],
    risk_aversion: float,
    lower: Sequence[float] | float = 0.0,
    upper: Sequence[float] | float = 1.0,
    budget: float = 1.0,
    inequalities: Iterable[LinearInequality] = (),
    as_of: str | None = None,
    evidence_ids: Sequence[str] = (),
    labels: dict[str, str] | None = None,
) -> ConvexDecisionProblem:
    """``min 0.5 * risk_aversion * w'Sigma w - mu'w`` on the budget/box feasible set.

    The covariance is symmetrised before validation so a matrix assembled from pairwise
    calculations that differ in the last bits is not rejected for a rounding artefact.
    """

    n = len(assets)
    if risk_aversion <= 0 or not math.isfinite(risk_aversion):
        raise ValidationError("risk_aversion must be positive and finite", value=risk_aversion)
    if len(expected_returns) != n:
        raise ValidationError("expected_returns must match assets", assets=n,
                              returns=len(expected_returns))
    sigma = np.asarray(covariance, dtype=float)
    if sigma.shape != (n, n):
        raise ValidationError("covariance must be square and match assets", assets=n,
                              shape=list(sigma.shape))
    sigma = (sigma + sigma.T) / 2.0
    lower_values = _broadcast(lower, n, "lower")
    upper_values = _broadcast(upper, n, "upper")
    return ConvexDecisionProblem(
        problem_id=problem_id,
        variables=tuple(assets),
        linear_costs=tuple(-float(value) for value in expected_returns),
        risk_matrix=tuple(tuple(float(value) for value in row) for row in risk_aversion * sigma),
        lower=lower_values,
        upper=upper_values,
        budget=float(budget),
        inequalities=tuple(inequalities),
        semantics="portfolio_mean_variance",
        as_of=as_of,
        evidence_ids=tuple(evidence_ids),
        labels=dict(labels or {}),
    )


def _broadcast(value: Sequence[float] | float, n: int, name: str) -> tuple[float, ...]:
    if isinstance(value, (int, float)):
        return tuple(float(value) for _ in range(n))
    values = tuple(float(v) for v in value)
    if len(values) != n:
        raise ValidationError(f"{name} must be a scalar or match assets", assets=n, received=len(values))
    return values


# ---------------------------------------------------------------------- feasibility
@dataclass(frozen=True, slots=True)
class FeasibilityReport:
    """Explicit primal feasibility, including *which* constraint is violated and by how much.

    A boolean is not enough for a certificate: a reader has to see whether a revision changed
    the budget, a box bound, or an added linear restriction.
    """

    feasible: bool
    max_violation: float
    budget_residual: float
    lower_violation: float
    upper_violation: float
    inequality_violation: float
    details: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": FEASIBILITY_SCHEMA,
            "feasible": self.feasible,
            "max_violation": self.max_violation,
            "budget_residual": self.budget_residual,
            "lower_violation": self.lower_violation,
            "upper_violation": self.upper_violation,
            "inequality_violation": self.inequality_violation,
            "details": list(self.details),
        }


def check_feasibility(
    problem: ConvexDecisionProblem,
    weights: Sequence[float],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> FeasibilityReport:
    w = np.asarray(weights, dtype=float)
    if w.shape != (problem.dimension,):
        raise ValidationError("weights must match problem dimension",
                              expected=problem.dimension, received=list(np.shape(w)))
    lower, upper = problem.bounds()
    budget_residual = float(abs(float(np.sum(w)) - problem.budget))
    lower_violation = float(max(0.0, float(np.max(lower - w))))
    upper_violation = float(max(0.0, float(np.max(w - upper))))
    matrix, bounds = problem.inequality_arrays()
    inequality_violation = 0.0
    if matrix.shape[0]:
        inequality_violation = float(max(0.0, float(np.max(matrix @ w - bounds))))
    details: list[str] = []
    if budget_residual > tolerance:
        details.append(f"budget residual {budget_residual:.3e} exceeds {tolerance:.3e}")
    if lower_violation > tolerance:
        details.append(f"lower bound violated by {lower_violation:.3e}")
    if upper_violation > tolerance:
        details.append(f"upper bound violated by {upper_violation:.3e}")
    if inequality_violation > tolerance:
        details.append(f"linear inequality violated by {inequality_violation:.3e}")
    worst = max(budget_residual, lower_violation, upper_violation, inequality_violation)
    return FeasibilityReport(
        feasible=worst <= tolerance,
        max_violation=worst,
        budget_residual=budget_residual,
        lower_violation=lower_violation,
        upper_violation=upper_violation,
        inequality_violation=inequality_violation,
        details=tuple(details),
    )


__all__ = [
    "DEFAULT_TOLERANCE",
    "FEASIBILITY_SCHEMA",
    "PROBLEM_SCHEMA",
    "PSD_RTOL",
    "ConvexDecisionProblem",
    "FeasibilityReport",
    "LinearInequality",
    "check_feasibility",
    "mean_variance_problem",
]
