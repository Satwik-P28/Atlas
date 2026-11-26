"""Certified worst-case regret when the correction is only known to lie in a set.

CRI (:mod:`atlas.decision.certificate`) assumes the revision is known exactly: it certifies the
regret of a recorded decision under one declared perturbation ``delta_c``. An audit often
cannot make that assumption. The correction may be:

* known only up to an interval per input (a vendor restates within a range);
* known up to an ellipsoidal confidence region (an estimated revision with a covariance);
* known to be bounded but with no shape assumption;
* partially covered, so that some inputs may be corrected and others may not.

This module certifies the *worst case over a set*::

    sup over ``delta_c`` in ``U`` of [ f_{c+delta_c}(w_old) - min_x f_{c+delta_c}(x) ]

**The supremum is not a convex problem, and is not solved as one.** The true regret is convex
in ``delta_c`` -- the optimal value is concave in ``c``, so its negative is convex, and
``delta_c'w`` is affine -- and a convex function attains its maximum over a compact convex set at
an extreme point. Maximising it directly would mean enumerating vertices or solving a
nonconvex problem per vertex, which is exactly the reoptimisation the method is supposed to
avoid. What *is* tractable is the following.

**Derivation, and a correction.** Weak duality gives ``g_{c+delta}(lam) <= f*_{c+delta}`` for any
dual feasible ``lam``, hence ``regret(delta) <= f_{c+delta}(w) - g_{c+delta}(lam)``. The tempting
next step -- treat ``g`` as affine in ``delta`` and call the supremum a support function -- is
**wrong**: ``g(lam; .)`` is the pointwise minimum of affine functions of ``c``, so it is concave,
and its minimiser moves with ``delta``. Writing ``w(lam)`` for the Lagrangian minimiser at ``c``,
expanding the concave quadratic exactly gives

    regret(delta) <= gap_c(lam) + delta'(w - w(lam)) + 0.5 * delta' Q^-1 delta,

with ``gap_c(lam) = f_c(w) - g_c(lam)`` and ``h_U(d) = sup_{delta in U} delta'd`` the support
function. The first-order term is a support function; the **curvature term is a maximisation of
a convex quadratic over ``U``**, which is NP-hard over a box and is not solved here. It is
bounded soundly by the elementwise envelope

    curv(U) = 0.5 * m' |Q^-1| m,     m_i = max_{delta in U} |delta_i|,

with ``m_i = |center_i| + half_width_i`` for an interval set, ``m_i = |center_i| +
radius * ||L[i, :]||_2`` for an ellipsoid, and the exact ``0.5 * delta' Q^-1 delta`` for a
singleton. The certificate therefore reports

    sup_{delta in U} regret(delta) <= gap_c(lam) + h_U(w - w(lam)) + curv(U),

and all three pieces are closed-form. Four consequences matter:

1. The bound is sound for **any** dual feasible ``lam``, including the multipliers recorded with
   the original decision, so the free version costs one Cholesky solve.
2. The curvature term is second order in the size of the set: for small revisions the bound is
   dominated by the first-order support term, which is what makes it informative rather than
   merely valid.
3. Unlike the inner supremum, the outer problem ``min_lam bound(lam)`` **is convex** -- ``gap`` is
   convex in ``lam`` and the support term is a supremum of affine functions of ``lam`` -- so the
   certificate can be optimised even though the uncertainty cannot.
4. With a singleton set the construction reduces to the CRI bound at the same multipliers (plus
   the exact curvature term, which is the only difference), so this is a generalisation rather
   than a parallel construction. This is asserted as a test.

The guarantee remains conditional on the set actually containing the true correction. That is
measurable and is measured: :func:`adversarial_out_of_set_check` evaluates corrections outside
``U`` and reports the violation rate instead of assuming it away.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ..core.errors import ValidationError
from .problem import ConvexDecisionProblem, check_feasibility
from .qp import DualPoint, _dual_terms, _factor, maximize_dual, validate_dual_point

UNCERTAINTY_SCHEMA = "atlas.decision.uncertainty_set.v1"
WORST_CASE_SCHEMA = "atlas.decision.worst_case_certificate.v1"

SUPPORTED_KINDS = ("singleton", "interval", "ellipsoid")


@dataclass(frozen=True, slots=True)
class UncertaintySet:
    """A documented set of admissible corrections to the linear costs.

    ``interval``   coordinate-wise ``|delta_i| <= half_width_i``, independently. The support
                   function is ``sum_i half_width_i |d_i|`` (attained at a vertex).
    ``ellipsoid``  ``U = {center + shape @ z : ||z||_2 <= radius}``, equivalently
                   ``||shape^-1 (delta - center)||_2 <= radius`` with ``shape`` symmetric positive
                   definite. The support function is ``center'd + radius ||shape @ d||_2``, the
                   maximiser is ``center + radius * shape @ (shape @ d) / ||shape @ d||``, the
                   curvature envelope uses the row norms of ``shape``, and membership inverts
                   ``shape`` (not its Cholesky factor). All four must use this one definition.

    ``singleton``  the exact-revision case, reproducing CRI.
    ``singleton``  the exact-revision case, reproducing CRI.

    ``coverage`` is prose that states where the numbers came from. It is required, because an
    uncertainty set without a documented provenance is an assumption wearing a certificate.
    """

    kind: str
    center: tuple[float, ...]
    half_width: tuple[float, ...] = ()
    shape: tuple[tuple[float, ...], ...] = ()
    radius: float = 0.0
    coverage: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in SUPPORTED_KINDS:
            raise ValidationError("unsupported uncertainty set kind", kind=self.kind)
        n = len(self.center)
        if n == 0:
            raise ValidationError("an uncertainty set needs at least one coordinate")
        if not all(math.isfinite(v) for v in self.center):
            raise ValidationError("uncertainty centre must be finite")
        if self.kind == "interval":
            if len(self.half_width) != n:
                raise ValidationError("interval uncertainty needs one half-width per coordinate",
                                      expected=n, received=len(self.half_width))
            if any(v < 0 or not math.isfinite(v) for v in self.half_width):
                raise ValidationError("half-widths must be finite and non-negative")
        if self.kind == "ellipsoid":
            if len(self.shape) != n or any(len(row) != n for row in self.shape):
                raise ValidationError("ellipsoid shape must be square and match the dimension")
            matrix = np.asarray(self.shape, dtype=float)
            if not np.allclose(matrix, matrix.T, atol=1e-12):
                raise ValidationError("ellipsoid shape must be symmetric")
            if np.min(np.linalg.eigvalsh(matrix)) <= 0:
                raise ValidationError("ellipsoid shape must be positive definite")
            if self.radius < 0 or not math.isfinite(self.radius):
                raise ValidationError("ellipsoid radius must be finite and non-negative")

    @property
    def dimension(self) -> int:
        return len(self.center)

    def support(self, direction: Sequence[float]) -> float:
        """``sup_{delta in U} delta' direction``: the support function, in closed form."""

        d = np.asarray(direction, dtype=float)
        if d.shape != (self.dimension,):
            raise ValidationError("support direction must match the uncertainty dimension",
                                  expected=self.dimension, received=int(d.size))
        center = np.asarray(self.center, dtype=float)
        base = float(center @ d)
        if self.kind == "singleton":
            return base
        if self.kind == "interval":
            return base + float(np.asarray(self.half_width, dtype=float) @ np.abs(d))
        shape = np.asarray(self.shape, dtype=float)
        return base + float(self.radius * np.linalg.norm(shape @ d))

    def argmax(self, direction: Sequence[float]) -> np.ndarray:
        """One maximiser of ``delta' direction`` over ``U`` (used for verification)."""

        d = np.asarray(direction, dtype=float)
        center = np.asarray(self.center, dtype=float)
        if self.kind == "singleton":
            return center
        if self.kind == "interval":
            return center + np.asarray(self.half_width, dtype=float) * np.sign(d)
        shape = np.asarray(self.shape, dtype=float)
        gradient = shape @ d
        norm = float(np.linalg.norm(gradient))
        if norm <= 0:
            return center
        return center + self.radius * (shape @ (gradient / norm))

    def distance_outside(self, delta: Sequence[float]) -> float:
        """Signed distance from ``delta`` to ``U``: ``<= 0`` means inside.

        For the ellipsoid this inverts ``shape`` itself, matching the definition
        ``U = {center + shape z : ||z|| <= radius}`` used by :meth:`support` and
        :meth:`argmax`. Inverting the Cholesky factor instead -- which an earlier version did --
        describes a *different* set and misclassifies points on it: with
        ``shape = diag(0.25, 1)``, ``radius = 1`` and an offset of ``(0.4, 0)``, the offset is
        outside (norm 1.6 through ``shape^-1``) but was reported inside (norm 0.8 through the
        Cholesky factor).
        """

        d = np.asarray(delta, dtype=float)
        if d.shape != (self.dimension,):
            raise ValidationError("point must match the uncertainty dimension",
                                  expected=self.dimension, received=int(d.size))
        offset = d - np.asarray(self.center, dtype=float)
        if self.kind == "singleton":
            return float(np.max(np.abs(offset))) if offset.size else 0.0
        if self.kind == "interval":
            return float(np.max(np.abs(offset) - np.asarray(self.half_width, dtype=float)))
        z = np.linalg.solve(np.asarray(self.shape, dtype=float), offset)
        return float(np.linalg.norm(z) - self.radius)

    def contains(self, delta: Sequence[float], tolerance: float = 1e-12) -> bool:
        """Membership, using the same geometry as :meth:`support` and :meth:`argmax`.

        ``tolerance`` is absolute in the normalised coordinate (the norm of ``shape^-1 (delta -
        center)``), so a point constructed by :meth:`argmax` -- which sits exactly on the boundary
        in exact arithmetic -- is a member even when inverting ``shape`` leaves a few ulps of
        positive residual. The tolerance is far below any economically meaningful correction, so
        it cannot classify a genuinely exterior point as interior: the review's counterexample is
        0.6 outside, twelve orders of magnitude beyond this.
        """

        return self.distance_outside(delta) <= tolerance

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": UNCERTAINTY_SCHEMA,
            "kind": self.kind,
            "center": [float(v) for v in self.center],
            "half_width": [float(v) for v in self.half_width],
            "shape": [[float(v) for v in row] for row in self.shape],
            "radius": float(self.radius),
            "coverage": self.coverage,
            "label": self.label,
            "dimension": self.dimension,
        }


def interval_set(center: Sequence[float], half_width: Sequence[float], *,
                 coverage: str, label: str = "") -> UncertaintySet:
    return UncertaintySet(kind="interval", center=tuple(float(v) for v in center),
                          half_width=tuple(float(v) for v in half_width),
                          coverage=coverage, label=label)


def ellipsoid_set(center: Sequence[float], shape: Sequence[Sequence[float]], radius: float, *,
                  coverage: str, label: str = "") -> UncertaintySet:
    return UncertaintySet(kind="ellipsoid", center=tuple(float(v) for v in center),
                          shape=tuple(tuple(float(v) for v in row) for row in shape),
                          radius=float(radius), coverage=coverage, label=label)


@dataclass(frozen=True, slots=True)
class WorstCaseCertificate:
    schema: str
    problem_id: str
    uncertainty: dict[str, Any]
    objective_at_decision: float
    dual_gap: float
    support_value: float
    curvature_value: float
    curvature_method: str
    bound: float
    bound_at_recorded_multipliers: float | None
    multipliers_optimised: bool
    iterations: dict[str, int]
    runtime_ms: float
    valid: bool
    #: The algebraic objective-value bound. It is a fact about the program and the numbers, and
    #: it holds whether or not the recorded weights are feasible.
    objective_bound: float = float("nan")
    #: Whether the recorded decision is feasible for the program. An objective-value bound at an
    #: infeasible point is not a decision regret certificate.
    decision_feasible: bool = True
    #: ``valid and decision_feasible``: the only flag a caller should act on.
    actionable: bool = True
    feasibility: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "problem_id": self.problem_id,
            "uncertainty": dict(self.uncertainty),
            "objective_at_decision": self.objective_at_decision,
            "dual_gap": self.dual_gap,
            "support_value": self.support_value,
            "curvature_value": self.curvature_value,
            "curvature_method": self.curvature_method,
            "bound": self.bound,
            "bound_at_recorded_multipliers": self.bound_at_recorded_multipliers,
            "multipliers_optimised": self.multipliers_optimised,
            "iterations": dict(self.iterations),
            "runtime_ms": self.runtime_ms,
            "valid": self.valid,
            "objective_bound": self.objective_bound,
            "decision_feasible": self.decision_feasible,
            "actionable": self.actionable,
            "feasibility": dict(self.feasibility),
            "reason": self.reason,
            "verification": dict(self.verification),
            "limitations": list(self.limitations),
        }


def curvature_bound(
    problem: ConvexDecisionProblem,
    uncertainty: UncertaintySet,
) -> dict[str, Any]:
    """Sound upper bound on ``sup_{delta in U} 0.5 * delta' Q^-1 delta``.

    Exact for a singleton (the quadratic is evaluated directly). For a box or an ellipsoid the
    supremum of a convex quadratic is not computable in closed form and is NP-hard over a box,
    so the elementwise envelope ``0.5 m' |Q^-1| m`` with ``m_i = max_{delta in U} |delta_i|`` is
    used. It is a valid upper bound because ``|delta_i| <= m_i`` and ``|Q^-1_ij| >= 0``, and it is
    tight when the coordinates of the correction are comparable in size.
    """

    q = problem.matrix()
    inverse = np.linalg.inv(q)
    center = np.asarray(uncertainty.center, dtype=float)
    if uncertainty.kind == "singleton":
        value = float(0.5 * center @ inverse @ center)
        return {"value": value, "method": "exact_singleton",
                "envelope": [float(abs(v)) for v in center]}
    if uncertainty.kind == "interval":
        envelope = np.abs(center) + np.asarray(uncertainty.half_width, dtype=float)
        method = "elementwise_envelope_box"
    else:
        shape = np.asarray(uncertainty.shape, dtype=float)
        row_norms = np.linalg.norm(shape, axis=1)
        envelope = np.abs(center) + uncertainty.radius * row_norms
        method = "elementwise_envelope_ellipsoid"
    value = float(0.5 * envelope @ np.abs(inverse) @ envelope)
    return {"value": value, "method": method, "envelope": [float(v) for v in envelope]}


def _bound_at(
    problem: ConvexDecisionProblem,
    weights: np.ndarray,
    uncertainty: UncertaintySet,
    point: DualPoint,
    curvature: float | None = None,
) -> tuple[float, float, float, float, np.ndarray]:
    """``(bound, gap, support, curvature, direction)`` for one multiplier vector.

    ``bound = gap + support + curvature`` where the support term is the supremum of the affine
    part over the set and ``curvature`` bounds the convex-quadratic remainder.
    """

    validate_dual_point(problem, point)
    factor = _factor(problem)
    alpha = np.asarray(point.alpha, dtype=float)
    beta = np.asarray(point.beta, dtype=float)
    gamma = np.asarray(point.gamma, dtype=float)
    value, lagrangian_minimiser, _grad_nu, _grad_bounds, _grad_ineq = _dual_terms(
        problem, factor, float(point.nu), alpha, beta, gamma)
    objective = float(problem.objective(weights))
    gap = objective - float(value)
    direction = weights - lagrangian_minimiser
    support = uncertainty.support(direction)
    if curvature is None:
        curvature = float(curvature_bound(problem, uncertainty)["value"])
    return gap + support + curvature, gap, support, curvature, direction


def certify_worst_case(
    decision_problem: ConvexDecisionProblem,
    decision_weights: Sequence[float],
    uncertainty: UncertaintySet,
    *,
    decision_dual: DualPoint | None = None,
    dual_iterations: int = 0,
    gradient_steps: int = 0,
) -> WorstCaseCertificate:
    """Bound the worst-case regret over ``uncertainty`` without re-solving any corrected problem.

    ``dual_iterations`` runs that many dual ascent steps from the recorded multipliers before
    evaluating the bound (cheap, and the bound can only improve). ``gradient_steps`` additionally
    minimises the bound over the multipliers directly, exploiting the fact that the *outer*
    problem is convex even though the inner supremum is not.
    """

    started = time.perf_counter()
    w = np.asarray(decision_weights, dtype=float)
    if w.shape != (decision_problem.dimension,):
        raise ValidationError("decision weights must match the problem dimension",
                              expected=decision_problem.dimension, received=int(w.size))
    if uncertainty.dimension != decision_problem.dimension:
        raise ValidationError("the uncertainty set must match the problem dimension",
                              expected=decision_problem.dimension,
                              received=uncertainty.dimension)
    objective_at_decision = float(decision_problem.objective(w))
    # Whether the recorded decision is admissible is a property of the decision, computed once and
    # reported on every path, including the ones that fail earlier for other reasons.
    feasibility = check_feasibility(decision_problem, w, tolerance=1e-9)
    curvature = curvature_bound(decision_problem, uncertainty)
    limitations = (
        "the bound is conditional on the true correction lying inside the declared set",
        "the bound concerns the specified convex program, not realized outcomes",
        "the curvature term uses an elementwise envelope, so the bound is sound but may be "
        "looser than the exact supremum over the set",
    )

    point: DualPoint | None = None
    recorded_bound = None
    if decision_dual is not None:
        try:
            recorded_bound, _gap, _support, _curv, _direction = _bound_at(
                decision_problem, w, uncertainty, decision_dual, float(curvature["value"]))
            point = DualPoint(nu=decision_dual.nu, alpha=decision_dual.alpha,
                              beta=decision_dual.beta, gamma=decision_dual.gamma,
                              structure_digest=decision_problem.structure_digest())
        except ValidationError as exc:
            return WorstCaseCertificate(
                schema=WORST_CASE_SCHEMA, problem_id=decision_problem.problem_id,
                uncertainty=uncertainty.as_dict(),
                objective_at_decision=objective_at_decision, dual_gap=float("nan"),
                support_value=float("nan"), curvature_value=float(curvature["value"]),
                curvature_method=str(curvature["method"]), bound=float("inf"),
                bound_at_recorded_multipliers=None, multipliers_optimised=False,
                iterations={"requested": int(dual_iterations), "performed": 0},
                runtime_ms=(time.perf_counter() - started) * 1000.0, valid=False,
                objective_bound=float("inf"),
                decision_feasible=bool(feasibility.feasible), actionable=False,
                feasibility=feasibility.as_dict(),
                reason=f"the recorded multipliers were rejected: {exc}",
                limitations=limitations + ("no bound is claimed from invalid multipliers",),
            )

    ascent_iterations = 0
    if dual_iterations > 0:
        point, diagnostics = maximize_dual(decision_problem, init=point,
                                           max_iter=int(dual_iterations))
        ascent_iterations = int(diagnostics.get("iterations", 0))

    gradient_iterations = 0
    if gradient_steps > 0:
        point, gradient_iterations = _minimise_bound_over_multipliers(
            decision_problem, w, uncertainty, point, steps=int(gradient_steps))
        ascent_iterations = max(ascent_iterations, 0)

    if point is None:
        return WorstCaseCertificate(
            schema=WORST_CASE_SCHEMA, problem_id=decision_problem.problem_id,
            uncertainty=uncertainty.as_dict(),
            objective_at_decision=objective_at_decision, dual_gap=float("nan"),
            support_value=float("nan"), curvature_value=float(curvature["value"]),
            curvature_method=str(curvature["method"]), bound=float("inf"),
            bound_at_recorded_multipliers=None, multipliers_optimised=False,
            iterations={"requested": int(dual_iterations), "performed": 0},
            runtime_ms=(time.perf_counter() - started) * 1000.0, valid=False,
            objective_bound=float("inf"),
            decision_feasible=bool(feasibility.feasible), actionable=False,
            feasibility=feasibility.as_dict(),
            reason="no dual feasible point was available; the bound needs recorded multipliers "
                   "or an explicit dual ascent budget",
            limitations=limitations,
        )

    bound, gap, support, _curvature, direction = _bound_at(
        decision_problem, w, uncertainty, point, float(curvature["value"]))
    scale = max(1.0, abs(objective_at_decision))
    algebra_valid = bool(math.isfinite(bound) and bound >= -1e-9 * scale)
    reason = None if algebra_valid else (
        f"the computed bound {bound:.6g} is negative beyond numerical noise, which means the "
        "multipliers or the set are inconsistent; no bound is claimed"
    )
    # A regret certificate is a statement about a *decision*, not only about a number. If the
    # recorded weights are infeasible for the program, the Lagrangian identity still produces an
    # objective-value bound, but the quantity it bounds is not the regret of a decision anyone
    # could have taken. The two are now separated rather than conflated.
    actionable = bool(algebra_valid and feasibility.feasible)
    if not feasibility.feasible:
        infeasibility_note = (
            "the recorded decision is infeasible for the program; the algebraic objective bound "
            f"{bound:.6g} is reported for transparency and is not a decision guarantee"
        )
        reason = f"{reason} {infeasibility_note}" if reason else infeasibility_note
    if not feasibility.feasible:
        limitations = limitations + (
            "the recorded decision violates the program's constraints, so no decision regret "
            "certificate is claimed",
        )
    valid = actionable
    return WorstCaseCertificate(
        schema=WORST_CASE_SCHEMA,
        problem_id=decision_problem.problem_id,
        uncertainty=uncertainty.as_dict(),
        objective_at_decision=objective_at_decision,
        dual_gap=float(gap),
        support_value=float(support),
        curvature_value=float(curvature["value"]),
        curvature_method=str(curvature["method"]),
        bound=float(bound),
        bound_at_recorded_multipliers=recorded_bound,
        multipliers_optimised=bool(gradient_steps > 0),
        iterations={"dual_requested": int(dual_iterations),
                    "dual_performed": ascent_iterations,
                    "gradient_performed": gradient_iterations},
        runtime_ms=(time.perf_counter() - started) * 1000.0,
        valid=valid,
        objective_bound=float(bound),
        decision_feasible=bool(feasibility.feasible),
        actionable=actionable,
        feasibility=feasibility.as_dict(),
        reason=reason,
        limitations=limitations,
    )


def _minimise_bound_over_multipliers(
    problem: ConvexDecisionProblem,
    weights: np.ndarray,
    uncertainty: UncertaintySet,
    start: DualPoint | None,
    *,
    steps: int,
) -> tuple[DualPoint, int]:
    """Minimise ``gap(lam) + h_U(w - w(lam))`` over dual feasible ``lam``.

    This is a convex problem even though ``sup_{delta} regret(delta)`` is not, because the
    bound is affine in ``delta`` and the supremum of affine functions is convex in ``lam``.
    The gradient uses the maximising ``delta`` as a subgradient witness:

        d/dlam h_U(w - w(lam)) = -(d w(lam)/dlam)' delta*,   delta* = argmax over U.

    L-BFGS-B is used with the box ``alpha, beta, gamma >= 0`` and ``nu`` free.
    """

    from scipy import optimize

    n = problem.dimension
    m = len(problem.inequalities)
    factor = _factor(problem)
    q = problem.matrix()
    if start is None:
        x0 = np.zeros(1 + 2 * n + m)
    else:
        validate_dual_point(problem, start)
        x0 = np.concatenate(([start.nu], np.asarray(start.alpha, dtype=float),
                             np.asarray(start.beta, dtype=float),
                             np.asarray(start.gamma, dtype=float)))
    bounds = [(None, None)] + [(0.0, None)] * (2 * n + m)

    def evaluate(x: np.ndarray) -> tuple[float, np.ndarray]:
        nu = float(x[0])
        alpha = x[1:1 + n]
        beta = x[1 + n:1 + 2 * n]
        gamma = x[1 + 2 * n:] if m else np.zeros(0)
        value, lagrangian_minimiser, grad_nu, grad_bounds, grad_ineq = _dual_terms(
            problem, factor, nu, alpha, beta, gamma)
        objective = float(problem.objective(weights))
        gap = objective - float(value)
        direction = weights - lagrangian_minimiser
        support = uncertainty.support(direction)
        delta_star = uncertainty.argmax(direction)
        # Gradient of the gap is minus the dual gradient.
        gradient = -np.concatenate(([grad_nu], grad_bounds, grad_ineq))
        # Gradient of the support term: -(dw/dlam)' delta*. With u = Q^-1 delta*:
        #   dw/dnu = -Q^-1 1, dw/dalpha_i = +Q^-1 e_i, dw/dbeta_i = -Q^-1 e_i,
        #   dw/dgamma_j = -Q^-1 a_j.
        u = np.linalg.solve(factor.T, np.linalg.solve(factor, delta_star))
        support_gradient = np.concatenate((
            [float(u @ np.ones(n))],
            -u,
            u,
            -(problem.inequality_arrays()[0] @ u) if m else np.zeros(0),
        ))
        return gap + support, gradient + support_gradient

    result = optimize.minimize(evaluate, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                               options={"maxiter": int(steps), "ftol": 1e-14, "gtol": 1e-12})
    x = np.asarray(result.x, dtype=float)
    x[1:] = np.maximum(x[1:], 0.0)
    point = DualPoint(
        nu=float(x[0]),
        alpha=tuple(float(v) for v in x[1:1 + n]),
        beta=tuple(float(v) for v in x[1 + n:1 + 2 * n]),
        gamma=tuple(float(v) for v in x[1 + 2 * n:]) if m else (),
        structure_digest=problem.structure_digest(),
    )
    # Only accept the optimised point if it evaluates to a valid, finite bound; otherwise keep
    # the starting point, which is already a valid certificate.
    try:
        value, _w, _grad_nu, _grad_bounds, _grad_ineq = _dual_terms(
            problem, factor, point.nu, np.asarray(point.alpha), np.asarray(point.beta),
            np.asarray(point.gamma))
        if not math.isfinite(float(value)):
            return (start if start is not None else point), 0
        point = DualPoint(nu=point.nu, alpha=point.alpha, beta=point.beta, gamma=point.gamma,
                          value=float(value), structure_digest=problem.structure_digest())
        best = point
        if start is not None and start.value is not None:
            start_bound, _g, _s, _c, _d = _bound_at(problem, weights, uncertainty, start)
            new_bound, _g2, _s2, _c2, _d2 = _bound_at(problem, weights, uncertainty, point)
            if start_bound < new_bound:
                best = start
        return best, int(getattr(result, "nit", 0))
    except ValidationError:  # pragma: no cover - defensive
        return (start if start is not None else point), 0


# ------------------------------------------------------------------- verification
def verify_by_enumeration(
    decision_problem: ConvexDecisionProblem,
    decision_weights: Sequence[float],
    uncertainty: UncertaintySet,
    *,
    limit: int = 12,
) -> dict[str, Any]:
    """Check a bound against the *true* worst case, computed by re-solving every vertex.

    Only meaningful for interval sets with few coordinates (``2**n`` vertices) and a program
    small enough to enumerate. This is the honest test of the whole construction: the bound must
    not fall below the maximum realized regret over the set, and the gap between the two is the
    price of not reoptimising.
    """

    from .qp import solve

    w = np.asarray(decision_weights, dtype=float)
    if uncertainty.kind != "interval":
        raise ValidationError("vertex enumeration is defined for interval sets only")
    if uncertainty.dimension > limit:
        raise ValidationError("vertex enumeration is exponential; reduce the dimension",
                              dimension=uncertainty.dimension, limit=limit)
    center = np.asarray(uncertainty.center, dtype=float)
    half = np.asarray(uncertainty.half_width, dtype=float)
    worst = -math.inf
    worst_delta = None
    vertices = 0
    for signs in np.ndindex(*([2] * len(center))):
        delta = center + half * np.asarray([1.0 if s else -1.0 for s in signs])
        perturbed = decision_problem.replace(
            linear_costs=tuple(float(v) for v in decision_problem.cost_vector() + delta))
        reference = solve(perturbed)
        regret = float(perturbed.objective(w) - reference.objective)
        vertices += 1
        if regret > worst:
            worst, worst_delta = regret, delta
    return {
        "method": "vertex_enumeration",
        "vertices": vertices,
        "true_worst_case_regret": worst,
        "true_worst_case_delta": None if worst_delta is None else [float(v) for v in worst_delta],
    }


def adversarial_out_of_set_check(
    decision_problem: ConvexDecisionProblem,
    decision_weights: Sequence[float],
    uncertainty: UncertaintySet,
    bound: float,
    actual_delta: Sequence[float],
) -> dict[str, Any]:
    """Evaluate a correction that is *outside* the declared set and report whether it violates.

    A bound computed for ``U`` says nothing about ``delta`` outside ``U``. This function exists
    so the failure is measured rather than hidden: it reports whether ``delta`` was inside the
    set, and, if not, whether the realized regret exceeded the bound.
    """

    from .qp import solve

    delta = np.asarray(actual_delta, dtype=float)
    # One membership predicate, shared with the support function and the maximiser. Computing
    # membership separately is how the Cholesky/shapec inversion bug survived a test suite.
    distance = uncertainty.distance_outside(delta)
    inside = uncertainty.contains(delta)
    perturbed = decision_problem.replace(
        linear_costs=tuple(float(v) for v in decision_problem.cost_vector() + delta))
    reference = solve(perturbed)
    realized = float(perturbed.objective(np.asarray(decision_weights, dtype=float))
                     - reference.objective)
    return {
        "inside_declared_set": inside,
        "distance_outside": distance,
        "realized_regret": realized,
        "bound": bound,
        "violated": bool(realized > bound + 1e-12),
        "note": "a violation here is expected and is not a defect in the bound, which is only "
                "claimed for corrections inside the declared set",
    }


__all__ = [
    "SUPPORTED_KINDS",
    "UNCERTAINTY_SCHEMA",
    "WORST_CASE_SCHEMA",
    "UncertaintySet",
    "WorstCaseCertificate",
    "adversarial_out_of_set_check",
    "certify_worst_case",
    "ellipsoid_set",
    "interval_set",
    "verify_by_enumeration",
]
