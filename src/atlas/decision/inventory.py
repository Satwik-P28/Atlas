"""A second decision domain on the same convex program: capacity allocation.

The transfer test here is deliberately *structural*, and the report says so. The same
canonical program — quadratic risk, a capacity budget, box bounds and linear service floors —
is instantiated with operational semantics: allocate scarce capacity across product lines
whose demand is uncertain, with a margin per unit and a group-level service floor.

What this demonstrates is that the certificate layer is not written against portfolio
vocabulary: it never sees an asset, a return or a covariance. What it does **not**
demonstrate is that the method improves operational decisions in practice, because the
demand process is synthetic. Claiming otherwise would be the kind of unsupported transfer
claim this pass is designed to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..core.errors import ValidationError
from .problem import ConvexDecisionProblem, LinearInequality
from .qp import QPSolution, solve

CAPACITY_SCHEMA = "atlas.decision.capacity_allocation.v1"


@dataclass(frozen=True, slots=True)
class CapacityLine:
    """One product line: unit margin, mean demand, and a service floor as a fraction."""

    line_id: str
    unit_margin: float
    mean_demand: float
    service_floor: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "unit_margin": self.unit_margin,
            "mean_demand": self.mean_demand,
            "service_floor": self.service_floor,
        }


def capacity_allocation_problem(
    *,
    problem_id: str,
    lines: Sequence[CapacityLine],
    demand_covariance: Sequence[Sequence[float]],
    capacity: float,
    risk_aversion: float,
    group_cap: tuple[Sequence[int], float] | None = None,
    as_of: str | None = None,
) -> ConvexDecisionProblem:
    """``min 0.5 * risk_aversion * x'Σx - margin'x`` over capacity allocations ``x``.

    ``Σ`` is the demand covariance: the quadratic term prices the mismatch risk created by
    allocating capacity to a volatile line. ``group_cap`` adds ``sum_{i in group} x_i <= cap``,
    which exercises the linear-inequality path that a plain portfolio box does not.
    """

    n = len(lines)
    if n == 0:
        raise ValidationError("at least one capacity line is required")
    covariance = np.asarray(demand_covariance, dtype=float)
    if covariance.shape != (n, n):
        raise ValidationError("demand covariance must be square and match lines", lines=n,
                              shape=list(covariance.shape))
    covariance = (covariance + covariance.T) / 2.0
    floors = tuple(float(line.service_floor) for line in lines)
    for floor in floors:
        if not 0.0 <= floor <= 1.0:
            raise ValidationError("a service floor must be a fraction in [0, 1]", floor=floor)
    upper = tuple(float(line.mean_demand) for line in lines)
    lower = tuple(floor * mean for floor, mean in zip(floors, upper))
    inequalities: list[LinearInequality] = []
    if group_cap is not None:
        indices, bound = group_cap
        coefficients = tuple(1.0 if i in set(indices) else 0.0 for i in range(n))
        inequalities.append(LinearInequality(coefficients, float(bound), label="group_capacity_cap"))
    if capacity < sum(lower) - 1e-9:
        raise ValidationError("capacity is below the sum of the service floors",
                              capacity=capacity, floors=sum(lower))
    return ConvexDecisionProblem(
        problem_id=problem_id,
        variables=tuple(line.line_id for line in lines),
        linear_costs=tuple(-float(line.unit_margin) for line in lines),
        risk_matrix=tuple(tuple(float(v) for v in row) for row in risk_aversion * covariance),
        lower=lower,
        upper=upper,
        budget=float(capacity),
        inequalities=tuple(inequalities),
        semantics="capacity_allocation",
        as_of=as_of,
        labels={"domain": "operations", "quantity": "capacity units"},
    )


def solve_capacity_allocation(problem: ConvexDecisionProblem) -> QPSolution:
    if problem.semantics != "capacity_allocation":
        raise ValidationError("expected a capacity_allocation problem", semantics=problem.semantics)
    return solve(problem)


def capacity_report(problem: ConvexDecisionProblem, solution: QPSolution) -> dict[str, Any]:
    allocation = np.asarray(solution.weights, dtype=float)
    lower, upper = problem.bounds()
    return {
        "schema": CAPACITY_SCHEMA,
        "schema_note": "operational reading of the canonical convex program",
        "problem_id": problem.problem_id,
        "allocation": {name: float(value) for name, value in zip(problem.variables, allocation)},
        "capacity_used": float(np.sum(allocation)),
        "capacity": problem.budget,
        "slack_by_line": {name: float(hi - value) for name, hi, value in zip(problem.variables, upper, allocation)},
        "at_floor": [name for name, lo, value in zip(problem.variables, lower, allocation)
                     if abs(value - lo) <= 1e-8],
        "at_ceiling": [name for name, hi, value in zip(problem.variables, upper, allocation)
                       if abs(value - hi) <= 1e-8],
        "certificate": {
            "certified_optimal": solution.certified_optimal,
            "duality_gap": solution.duality_gap,
            "kkt": solution.kkt.as_dict(),
        },
        "limitation": "synthetic demand covariance; not an operational recommendation",
    }


__all__ = [
    "CAPACITY_SCHEMA",
    "CapacityLine",
    "capacity_allocation_problem",
    "capacity_report",
    "solve_capacity_allocation",
]
