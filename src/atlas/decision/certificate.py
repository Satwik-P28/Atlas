"""Certificates for decisions taken under now-superseded evidence.

The question this module answers is narrower, and more useful, than "did the optimal solution
change?" It is:

    Given the decision that was actually taken at time ``t``, and the evidence that has since
    become public, what can be *proved* about the regret of that decision under the corrected
    program — without re-solving from scratch?

Two certificates are produced, with different costs and different strengths.

**Exact optimality certificate.**
If the recorded weights satisfy the KKT system of the corrected program, they are optimal for
it (convex program, linear constraints) and the regret is zero. The multipliers are recovered
from the weights by a least-squares solve on the active set -- linear algebra, no optimisation
-- and, when least squares returns a sign-infeasible representative of an underdetermined
system, by a non-negative feasibility LP. Both are measured separately: the LP is a HiGHS
interior-point/branch-and-bound call, so the certificate reports which path ran, how often it
ran, and what each cost. Calling the whole test "O(n^2) with no optimisation" was inaccurate.
This is the classical support-set invariancy test in the form that matters for an audit, and it
is *sufficient*: a negative answer proves nothing on its own.

A KKT residual below a tolerance is a numerical statement, not a proof. The certificate
therefore also reports ``residual_regret_bound``: ``0.5 r'Q^-1 r`` for the recovered
stationarity residual, which upper bounds ``regret`` whenever ``w`` is feasible and the
multipliers are complementary at ``w``, and ``||r||^2/(2 lambda_min)`` as a fallback that uses
only ``Q >= lambda_min I``. On a correct corner solution that number is around ``1e-17``, which
is what the report now says instead of "exactly zero".

**Bounded-regret certificate.**
For any dual feasible multiplier vector ``lam``, weak duality gives ``g(lam) <= f*``, hence
``regret = f(w) - f* <= f(w) - g(lam)``. The feasible dual set does not depend on the linear
costs, so the multiplier vector recorded with the original decision is *still dual feasible*
for the corrected program. Evaluating it costs one Cholesky solve. That is a valid regret
bound with zero optimisation, and it can be tightened by a few dual ascent steps. The recorded
multiplier vector is validated before use -- sign feasibility, dimensions, finiteness and
constraint-structure identity -- and an invalid one is refused with a recorded reason rather
than projected into validity, because a projected vector is a different vector.

The guarantee is conditional and the report says so: it holds for the convex program as
declared, with the declared linear input sensitivity. It is not a claim about market
outcomes, and it is void if the sensitivity declaration is wrong — a failure mode measured
in the experiments rather than asserted away.

A proposition used by the radius search (proof in the technical report): along a fixed
direction ``d``, the set of radii ``r >= 0`` for which a fixed ``w`` remains optimal is a
closed interval containing zero. Reason: with ``w`` fixed, the KKT system is a *linear*
system of inequalities in ``(r, multipliers)``; the projection of a polyhedron onto the
``r`` axis is an interval, and ``r = 0`` is feasible by assumption. Bisection is therefore
sound.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ..core.errors import ValidationError
from .problem import ConvexDecisionProblem, check_feasibility
from .qp import (
    KKT_TOLERANCE,
    DualPoint,
    KKTReport,
    derive_multipliers,
    dual_objective,
    maximize_dual,
    residual_regret_bound,
    validate_dual_point,
    verify_kkt,
)
from .revision import RevisionCompilation, directional_perturbation

CERTIFICATE_SCHEMA = "atlas.decision.revision_certificate.v1"
RADIUS_SCHEMA = "atlas.decision.stability_radius.v1"

#: A certified gap below this value is reported as zero regret. It is at the level of the
#: floating-point residual of the Cholesky solves, not a modelling tolerance.
ZERO_GAP_TOLERANCE = 1e-9

#: Default absolute ceiling for a *useful* bounded-regret certificate. A bound above this is
#: still mathematically valid but is reported as ``uncertified`` because it carries no
#: decision-relevant information. The value is in objective units and is overridable.
DEFAULT_USEFUL_BOUND = 1.0e-3

#: Three statements that are often conflated and must not be. The certificate makes the first two;
#: it does not make the third, and says so in the same record.
CLAIM_CLASSES = {
    "analytic_under_exact_arithmetic": (
        "For any dual-feasible multipliers, weak duality gives f(w) - g(lam) >= f(w) - f* in exact "
        "arithmetic. A theorem about the declared program and the declared linear sensitivity; it "
        "is not a statement about floating-point arithmetic."),
    "empirical_agreement": (
        "The computed bound and an independently measured reference regret agree within the observed "
        "solver-disagreement threshold. This is a numerical observation on float64 arithmetic, not "
        "a proof that the value encloses the true error."),
    "verified_floating_point_enclosure": (
        "A rigorous upper bound on the floating-point error itself, established by directed rounding "
        "or interval arithmetic. Not available: ``rounding_margin`` is a forward-error *estimate* "
        "under the standard model, so it bounds the arithmetic only up to an unverified modelling "
        "step."),
}


@dataclass(frozen=True, slots=True)
class RevisionCertificate:
    schema: str
    revision_id: str | None
    problem_id: str
    decision_as_of: str | None
    decision_digest: str
    revised_digest: str
    temporal_relationship: str
    verdict: str
    exact: dict[str, Any]
    bounded: dict[str, Any]
    feasibility: dict[str, Any]
    guarantee_scope: str
    limitations: tuple[str, ...] = ()
    hindsight: bool = False
    reference: dict[str, Any] | None = None
    recorded_dual_status: str = "not_supplied"
    #: Which of the three claim classes this certificate actually makes; see :data:`CLAIM_CLASSES`.
    claims: dict[str, Any] = field(default_factory=dict)

    @property
    def zero_regret(self) -> bool:
        """Zero regret *up to the reported residual*, never an exact mathematical zero.

        The KKT test compares residuals against a tolerance, so the certificate reports the
        validated residual bound (``0.5 r'Q^-1 r + slack``) instead of overwriting it with ``0.0``.
        The property name is kept for callers; the verdict says what is actually claimed.
        """

        return self.verdict == "zero_regret_within_residual"

    @property
    def certified(self) -> bool:
        return self.verdict in {"zero_regret_within_residual", "regret_bounded"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "revision_id": self.revision_id,
            "problem_id": self.problem_id,
            "decision_as_of": self.decision_as_of,
            "decision_digest": self.decision_digest,
            "revised_digest": self.revised_digest,
            "temporal_relationship": self.temporal_relationship,
            "verdict": self.verdict,
            "zero_regret": self.zero_regret,
            "certified": self.certified,
            "exact": dict(self.exact),
            "bounded": dict(self.bounded),
            "feasibility": dict(self.feasibility),
            "guarantee_scope": self.guarantee_scope,
            "limitations": list(self.limitations),
            "hindsight": self.hindsight,
            "reference": dict(self.reference) if self.reference else None,
            "recorded_dual_status": self.recorded_dual_status,
            "claims": dict(self.claims),
        }


def _temporal_relationship(compilation: RevisionCompilation) -> str:
    if compilation.status == "no_decision_clock":
        return "unknown_no_decision_clock"
    if compilation.hindsight:
        return "contaminated_hindsight"
    if compilation.post_decision_revision_ids:
        # The ordinary audit case: evidence that was not public when the decision was taken is
        # now public and is being used to evaluate that decision.
        return "revision_available_after_decision"
    if compilation.incorporated and not compilation.applied:
        # The subtle case: everything supplied is already inside the recorded vintage, so there
        # is nothing to audit. Distinguishing this from "no revision" is the point of lineage.
        return "revision_already_incorporated"
    if compilation.applied and compilation.excluded:
        return "mixed_availability"
    if compilation.applied:
        return "pre_decision_revision_explicitly_included"
    if compilation.withdrawn and not compilation.excluded:
        return "revision_withdrawn"
    if compilation.excluded:
        return "revision_not_eligible"
    return "no_revision"


def certify_revision_impact(
    decision_problem: ConvexDecisionProblem,
    decision_weights: Sequence[float],
    compilation: RevisionCompilation,
    *,
    decision_dual: DualPoint | None = None,
    dual_iterations: int = 0,
    kkt_tolerance: float = KKT_TOLERANCE,
    useful_bound: float = DEFAULT_USEFUL_BOUND,
    reference_solution: Any | None = None,
) -> RevisionCertificate:
    """Certify the regret of a recorded decision under the corrected program.

    ``dual_iterations=0`` measures the *free* certificate: the multiplier vector recorded with
    the decision, re-used without any optimisation. Higher values measure how much a small,
    bounded amount of dual ascent improves the bound.
    """

    w = np.asarray(decision_weights, dtype=float)
    if w.shape != (decision_problem.dimension,):
        raise ValidationError("decision weights must match the problem dimension",
                              expected=decision_problem.dimension, received=int(w.size))
    revised = compilation.problem
    timings: dict[str, float] = {}
    clock = time.perf_counter()
    feasibility = check_feasibility(revised, w, tolerance=max(kkt_tolerance, 1e-9))
    objective_at_decision = float(revised.objective(w))
    timings["feasibility_ms"] = (time.perf_counter() - clock) * 1000.0
    limitations: list[str] = [
        "the guarantee is conditional on the declared linear input sensitivity",
        "the guarantee concerns the specified convex program, not realized market outcomes",
    ]
    if compilation.hindsight:
        limitations.append("HINDSIGHT DIAGNOSTIC: future-public revisions were applied")

    clock = time.perf_counter()
    multipliers, multiplier_diagnostics = derive_multipliers(revised, w)
    timings["multiplier_recovery_ms"] = (time.perf_counter() - clock) * 1000.0
    timings["multiplier_recovery_method"] = 0.0
    clock = time.perf_counter()
    exact_report: KKTReport = verify_kkt(revised, w, multipliers, tolerance=kkt_tolerance)
    timings["kkt_check_ms"] = (time.perf_counter() - clock) * 1000.0
    residual_block: dict[str, Any] | None = None
    if multipliers is not None:
        clock = time.perf_counter()
        try:
            residual_block = residual_regret_bound(revised, w, multipliers)
        except ValidationError as exc:  # pragma: no cover - defensive
            residual_block = {"valid": False, "reason": str(exc)}
        timings["residual_bound_ms"] = (time.perf_counter() - clock) * 1000.0
    recovery_method = str(multiplier_diagnostics.get("recovery_method", "none"))
    exact_block = {
        "optimal_for_revised_program": bool(exact_report.satisfied),
        "optimality_kind": "numerical_within_tolerance" if exact_report.satisfied else "not_verified",
        "kkt": exact_report.as_dict(),
        "multiplier_diagnostics": {
            key: value for key, value in multiplier_diagnostics.items()
            if key in {"rank", "design_columns", "residual", "sign_violation", "active_lower",
                       "active_upper", "fixed", "active_inequalities", "recovery_method"}
        },
        "recovery_method": recovery_method,
        "used_lp_fallback": recovery_method == "nonnegative_lp",
        "residual_regret_bound": residual_block,
        "numerical_regret_bound": (residual_block or {}).get("bound"),
        "cost": (
            "least squares on the active set (linear algebra); a non-negative feasibility LP "
            "(HiGHS) only when least squares returns a sign-infeasible representative"
        ) if recovery_method == "least_squares" else (
            "non-negative feasibility LP (HiGHS) because least squares was sign-infeasible or "
            "left a residual"
        ),
    }

    bounded_block: dict[str, Any] = {
        "objective_at_decision": objective_at_decision,
        "dual_start": None,
        "dual_value": None,
        "regret_upper_bound": None,
        "bound_kind": "none",
        "bound_valid": False,
        "dual_iterations": int(dual_iterations),
        "useful_bound": float(useful_bound),
        "cost": "one Cholesky solve per dual evaluation",
        "primal_feasible_unused": None,
    }
    dual_point: DualPoint | None = None
    recorded_dual_status = "not_supplied"
    if decision_dual is not None:
        # The dual feasible set is independent of the linear costs, so the recorded multipliers
        # remain feasible for the corrected program -- but that is a claim about the *signs* and
        # the *constraint geometry*, and both are checked here. A recorded vector with a
        # negative multiplier is not a lower bound and must not be reported as one.
        try:
            validate_dual_point(revised, decision_dual)
        except ValidationError as exc:
            recorded_dual_status = "rejected"
            bounded_block["recorded_dual_rejected_reason"] = str(exc)
            bounded_block["recorded_dual_rejected"] = True
        else:
            clock = time.perf_counter()
            try:
                value, _unused, _grad = dual_objective(revised, decision_dual)
            except ValidationError as exc:
                recorded_dual_status = "rejected"
                bounded_block["recorded_dual_rejected_reason"] = str(exc)
                bounded_block["recorded_dual_rejected"] = True
            else:
                timings["warm_dual_evaluation_ms"] = (time.perf_counter() - clock) * 1000.0
                if math.isfinite(value):
                    dual_point = DualPoint(
                        nu=decision_dual.nu, alpha=decision_dual.alpha,
                        beta=decision_dual.beta, gamma=decision_dual.gamma, value=float(value),
                        structure_digest=revised.structure_digest(),
                    )
                    recorded_dual_status = "accepted"
                    bounded_block["dual_start"] = "recorded_decision_multipliers"
                    bounded_block["dual_value"] = float(value)
    if dual_point is None and recorded_dual_status != "rejected":
        bounded_block["dual_start"] = "cold_start"

    # The iteration budget is exactly what the caller asked for. An earlier version applied
    # max(int(dual_iterations), 20), so an arm described as "five steps" silently performed at
    # least twenty and the reported tightness was not the tightness of a five-step bound.
    requested_iterations = max(0, int(dual_iterations))
    ascent_block: dict[str, Any] = {
        "requested_iterations": requested_iterations,
        "performed": False,
        "actual_iterations": 0,
        "objective_evaluations": 0,
        "gradient_evaluations": 0,
        "runtime_ms": 0.0,
        "budget_respected": True,
    }
    if requested_iterations > 0:
        clock = time.perf_counter()
        try:
            dual_point, diagnostics = maximize_dual(
                revised, init=dual_point, max_iter=requested_iterations
            )
            ascent_block.update({
                "performed": True,
                "actual_iterations": int(diagnostics.get("iterations", 0)),
                "objective_evaluations": int(diagnostics.get("objective_evaluations", 0)),
                "gradient_evaluations": int(diagnostics.get("gradient_evaluations", 0)),
                "start_value": diagnostics.get("start_value"),
                "final_value": diagnostics.get("final_value"),
                "budget_respected": bool(diagnostics.get("budget_respected", True)),
                "start_kind": diagnostics.get("start_kind"),
                "status": diagnostics.get("status"),
            })
            bounded_block["dual_diagnostics"] = diagnostics
            bounded_block["dual_new_iterations"] = int(diagnostics.get("iterations", 0))
        except ValidationError as exc:
            ascent_block["error"] = str(exc)
            bounded_block["dual_error"] = str(exc)
        ascent_block["runtime_ms"] = (time.perf_counter() - clock) * 1000.0
    bounded_block["dual_budget"] = ascent_block

    scale = max(1.0, abs(objective_at_decision))
    if not feasibility.feasible:
        # Weak duality needs a feasible recorded point: if the revision makes the recorded
        # decision infeasible, f(w) is still a number but it is not the value of a decision the
        # auditor may take, so no regret bound is claimed. Reporting one was a defect.
        bounded_block["regret_upper_bound"] = None
        bounded_block["bound_rejected_reason"] = (
            "the recorded decision is infeasible for the revised program; a regret bound is "
            "undefined and is deliberately not reported"
        )
    elif dual_point is not None and dual_point.value is not None and math.isfinite(float(dual_point.value)):
        bound = objective_at_decision - float(dual_point.value)
        if bound < -1e-9 * scale:
            # Weak duality forbids this. It happens when the dual evaluation is numerically
            # invalid, so the bound is refused instead of being clamped to a comfortable zero.
            bounded_block["bound_rejected_reason"] = (
                f"dual value {float(dual_point.value):.12g} exceeded the objective "
                f"{objective_at_decision:.12g} at the recorded weights; no bound is claimed"
            )
        else:
            bounded_block["dual_value"] = float(dual_point.value)
            # The same principle as the residual certificate: the difference of two float64
            # objectives carries a forward error, and a bound is only defensible down to it. It is
            # negligible against a gap of order 1e-3 and decisive against one of order 1e-18, which
            # is exactly when it matters.
            dual_margin = 8.0 * (float(np.finfo(float).eps) / 2.0) * (revised.dimension + 2) * (
                abs(objective_at_decision) + abs(float(dual_point.value)))
            bounded_block["regret_upper_bound"] = float(max(bound, 0.0)) + dual_margin
            bounded_block["regret_upper_bound_exact_arithmetic"] = float(max(bound, 0.0))
            bounded_block["rounding_margin"] = dual_margin
            bounded_block["verification_tolerance"] = dual_margin
            bounded_block["bound_valid"] = True
            bounded_block["bound_kind"] = (
                "duality_gap_from_recorded_multipliers" if requested_iterations == 0
                else f"duality_gap_after_{ascent_block['actual_iterations']}_iterations"
            )

    residual_bound = None
    residual_margin = None
    if residual_block is not None and residual_block.get("valid"):
        # Emit the margin-inclusive value: the algebraic bound plus the floating-point resolution
        # of the arithmetic that produced it. Emitting the algebraic value alone would present a
        # 1e-18 number as verified to 1e-18 when float64 resolves roughly 1e-15 of it.
        residual_bound = residual_block.get("bound_including_margin")
        residual_margin = residual_block.get("rounding_margin")
    if not feasibility.feasible:
        verdict = "infeasible_under_revision"
    elif exact_report.satisfied and residual_bound is not None:
        # A satisfied KKT system under a tolerance licenses a *numerical* statement, not an exact
        # zero. The residual certificate is the validated upper bound; reporting 0.0 here discarded
        # the only quantity that makes the claim checkable.
        verdict = "zero_regret_within_residual"
        bounded_block["regret_upper_bound"] = float(residual_bound)
        bounded_block["bound_valid"] = True
        bounded_block["bound_kind"] = "residual_regret_certificate"
        bounded_block["bound_source"] = "residual_certificate"
        bounded_block["residual_kkt_residuals"] = {
            "stationarity": exact_report.stationarity,
            "dual_feasibility": exact_report.dual_feasibility,
            "complementarity": exact_report.complementarity,
            "primal_feasibility": exact_report.primal_feasibility,
            "tolerance": exact_report.tolerance,
            "gap_identity_residual": residual_block.get("gap_identity_residual")
            if residual_block else None,
            "identity_residual_extended_precision":
                residual_block.get("identity_residual_longdouble") if residual_block else None,
        }
        # Two numbers, never one: the algebraic bound and the floating-point resolution that
        # separates it from what the arithmetic can defend. The emitted bound is the sum.
        bounded_block["regret_upper_bound_exact_arithmetic"] = (
            residual_block.get("bound") if residual_block else None)
        bounded_block["rounding_margin"] = residual_margin
        bounded_block["verification_tolerance"] = residual_margin
        bounded_block["bound_precision_note"] = (
            "the reported bound is the algebraic residual plus a forward floating-point error "
            "estimate; digits below that margin are not claimed")
    elif bounded_block["regret_upper_bound"] is not None:
        # A finite bound is a certificate whether or not it is small. Whether it is small
        # enough to act on is a separate, declared-tolerance question, so it is reported as
        # its own flag rather than folded into the verdict.
        verdict = "regret_bounded"
        if residual_block is not None and not residual_block.get("valid"):
            # Say why the residual certificate was refused. Without this, an event whose KKT test
            # passed but whose identity did not verify looks like an unexplained fallback, and the
            # earlier version of this code resolved that silence by reporting 0.0.
            bounded_block["residual_rejected"] = {
                "reason": "the residual certificate failed its own identity check at the "
                          "floating-point resolution of the arithmetic",
                "gap_identity_residual": residual_block.get("gap_identity_residual"),
                "identity_tolerance": (residual_block.get("identity_check") or {}).get("tolerance"),
                "algebraic_bound": residual_block.get("bound"),
                "quadratic_form": residual_block.get("quadratic_form"),
                "complementarity_slack": residual_block.get("complementarity_slack"),
                "primal_feasible": residual_block.get("primal_feasible"),
                "max_primal_violation": residual_block.get("max_primal_violation"),
            }
    else:
        verdict = "uncertified"
    bound = bounded_block["regret_upper_bound"]
    bounded_block["meets_tolerance"] = bool(bound is not None and bound <= useful_bound)
    bounded_block["tolerance_kind"] = "absolute_objective_units"
    timings["total_ms"] = sum(
        value for key, value in timings.items()
        if key.endswith("_ms")) + ascent_block.get("runtime_ms", 0.0)
    exact_block["timings_ms"] = dict(timings)

    reference_block = None
    if reference_solution is not None:
        optimal_weights = np.asarray(getattr(reference_solution, "weights", reference_solution), dtype=float)
        optimal_value = float(revised.objective(optimal_weights))
        realized = float(objective_at_decision - optimal_value)
        reference_block = {
            "optimal_objective": optimal_value,
            "realized_regret": max(realized, 0.0),
            "weights_changed": bool(np.max(np.abs(optimal_weights - w)) > 1e-6),
            "max_weight_change": float(np.max(np.abs(optimal_weights - w))),
            "recompute_runtime_ms": getattr(reference_solution, "runtime_ms", None),
        }
        if bound is not None:
            denominator = max(realized, 1e-15)
            reference_block["bound_over_realized_regret"] = float(bound / denominator)
            reference_block["bound_understates"] = bool((bound + 1e-15) < realized)

    # ------------------------------------------------ what is actually being claimed, in three parts
    # The analytic theorem holds whenever a dual-feasible point generated the bound. The empirical
    # statement holds only where a reference measurement exists, and only to the resolution of that
    # measurement. The third class -- a verified floating-point enclosure -- is not available, and
    # saying so is part of the certificate rather than a caveat in a document.
    analytic_holds = bound is not None
    claims = {
        "made": (["analytic_under_exact_arithmetic"] if analytic_holds else []) +
                (["empirical_agreement"] if reference_block is not None and bound is not None else []),
        "not_made": ["verified_floating_point_enclosure"],
        "analytic_under_exact_arithmetic": {
            "holds": analytic_holds,
            "statement": CLAIM_CLASSES["analytic_under_exact_arithmetic"],
            "assumptions": [
                "the recorded decision is feasible for the revised program",
                "the multipliers are dual feasible for the revised program's constraint structure",
                "the revision's input-to-cost mapping is the declared linear sensitivity",
            ],
            "algebraic_bound": bounded_block.get("regret_upper_bound_exact_arithmetic"),
            "emitted_bound": bound,
        },
        "empirical_agreement": {
            "measured": reference_block is not None and bound is not None,
            "statement": CLAIM_CLASSES["empirical_agreement"],
            "verification_tolerance": bounded_block.get("verification_tolerance"),
            "reference_regret": (reference_block or {}).get("realized_regret"),
            "note": ("agreement is with a reference solver's own float64 result; it is evidence about "
                     "the bound and the solver jointly, not a proof about either"),
        },
        "verified_floating_point_enclosure": {
            "available": False,
            "statement": CLAIM_CLASSES["verified_floating_point_enclosure"],
            "margin_kind": "forward_error_estimate",
        },
    }
    return RevisionCertificate(
        schema=CERTIFICATE_SCHEMA,
        revision_id=(compilation.applied[0].revision_id if compilation.applied else None),
        problem_id=decision_problem.problem_id,
        decision_as_of=compilation.decision_as_of,
        decision_digest=decision_problem.digest(),
        revised_digest=revised.digest(),
        temporal_relationship=_temporal_relationship(compilation),
        verdict=verdict,
        exact=exact_block,
        bounded=bounded_block,
        feasibility=feasibility.as_dict(),
        guarantee_scope=(
            "conditional on the declared convex program and the declared linear input "
            "sensitivity; bounds the objective regret of the recorded decision under the "
            "corrected coefficients; says nothing about realized returns"
        ),
        limitations=tuple(limitations),
        hindsight=compilation.hindsight,
        reference=reference_block,
        recorded_dual_status=recorded_dual_status,
        claims=claims,
    )


# ------------------------------------------------------------------------ stability radius
@dataclass(frozen=True, slots=True)
class StabilityRadius:
    radius: float
    threshold: float
    direction_l2: float
    evaluations: int
    converged: bool
    initial_optimal: bool
    certified_cost_delta: float | None
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": RADIUS_SCHEMA,
            "radius": self.radius,
            "threshold": self.threshold,
            "direction_l2": self.direction_l2,
            "evaluations": self.evaluations,
            "converged": self.converged,
            "initial_optimal": self.initial_optimal,
            "certified_cost_delta_at_radius": self.certified_cost_delta,
            "notes": list(self.notes),
        }


def stability_radius(
    problem: ConvexDecisionProblem,
    weights: Sequence[float],
    direction: Sequence[float],
    *,
    upper_limit: float = 1.0,
    tolerance: float = 1e-10,
    max_evaluations: int = 200,
    kkt_tolerance: float = KKT_TOLERANCE,
) -> StabilityRadius:
    """Largest ``r`` along ``direction`` for which ``weights`` remains exactly optimal.

    Geometric expansion to bracket the first failure, then bisection. Each evaluation is a
    multiplier recovery plus a KKT check, so the search is cheap and needs no solver.
    """

    d = np.asarray(direction, dtype=float)
    if not np.any(np.abs(d) > 0):
        raise ValidationError("stability radius needs a non-zero direction")

    w = np.asarray(weights, dtype=float)

    def optimal_at(radius: float) -> bool:
        perturbed = directional_perturbation(problem, d, radius)
        point, _diagnostics = derive_multipliers(perturbed, w, active_tolerance=1e-8)
        if point is None:
            return False
        return verify_kkt(perturbed, w, point, tolerance=kkt_tolerance).satisfied

    evaluations = 0
    initial = optimal_at(0.0)
    evaluations += 1
    if not initial:
        return StabilityRadius(0.0, tolerance, float(np.linalg.norm(d)), evaluations, True, False,
                               None, ("the recorded weights are not optimal for the base problem",))
    low, high = 0.0, None
    step = max(upper_limit / 1024.0, tolerance)
    while step <= upper_limit and evaluations < max_evaluations:
        if not optimal_at(step):
            high = step
            break
        low = step
        step *= 2.0
        evaluations += 1
    if high is None:
        return StabilityRadius(low, tolerance, float(np.linalg.norm(d)), evaluations, False, True,
                               None, (f"no failure detected up to r={low:.6g}",))
    while (high - low) > tolerance and evaluations < max_evaluations:
        middle = (low + high) / 2.0
        if optimal_at(middle):
            low = middle
        else:
            high = middle
        evaluations += 1
    notes = ["radius is along the declared direction only"]
    # The KKT test itself has a resolution: below roughly 1e-6 in objective-coefficient units
    # a perturbation is indistinguishable from floating-point noise, so a radius that small is
    # reported as zero rather than as a spurious positive number.
    if low <= max(1e-6, 100.0 * tolerance):
        lower, upper = problem.bounds()
        interior = bool(np.all(np.abs(np.asarray(weights, dtype=float) - lower) > 1e-7) and
                        np.all(np.abs(upper - np.asarray(weights, dtype=float)) > 1e-7))
        low = 0.0
        notes.append(
            "radius is numerically zero: the recorded weights are interior to every box bound, "
            "so the optimum moves with the objective coefficients for any non-zero perturbation"
            if interior else
            "radius is numerically zero: the active set changes for any non-zero perturbation"
        )
    return StabilityRadius(low, tolerance, float(np.linalg.norm(d)), evaluations, True, True, None,
                           tuple(notes))


def regret_tolerance_radius(
    problem: ConvexDecisionProblem,
    weights: Sequence[float],
    direction: Sequence[float],
    *,
    tolerance: float,
    upper_limit: float = 1.0,
    bisection_tolerance: float = 1e-10,
    max_evaluations: int = 200,
) -> dict[str, Any]:
    """Largest ``r`` for which the *realized regret* of ``weights`` stays below ``tolerance``.

    This is the operationally meaningful radius, and unlike exact invariance it is positive
    for interior optima. Bisection is justified by convexity: the optimal value ``V*(c + r d)``
    is concave in the cost vector (a pointwise minimum of affine functions), so the regret
    ``G(r) = f_r(w) - V*(c + r d)`` is convex in ``r`` with ``G(0) = 0``; therefore
    ``{r >= 0 : G(r) <= tolerance}`` is an interval containing zero.

    Each evaluation re-solves the perturbed program, so this is a reference measurement used
    to score the certificates, not a cheap replacement for them.
    """

    from .qp import solve  # local import keeps the certificate module import-light

    d = np.asarray(direction, dtype=float)
    if not np.any(np.abs(d) > 0):
        raise ValidationError("regret radius needs a non-zero direction")
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValidationError("tolerance must be finite and non-negative", tolerance=tolerance)
    w = np.asarray(weights, dtype=float)
    evaluations = 0

    def regret_at(radius: float) -> float:
        nonlocal evaluations
        evaluations += 1
        perturbed = directional_perturbation(problem, d, radius)
        reference = solve(perturbed)
        return float(perturbed.objective(w) - reference.objective)

    if regret_at(0.0) > tolerance:
        return {"radius": 0.0, "tolerance": tolerance, "evaluations": evaluations,
                "bracketed": False, "reason": "the base decision already exceeds the tolerance"}
    low, high = 0.0, None
    step = max(upper_limit / 1024.0, bisection_tolerance)
    while step <= upper_limit and evaluations < max_evaluations:
        if regret_at(step) > tolerance:
            high = step
            break
        low = step
        step *= 2.0
    if high is None:
        return {"radius": low, "tolerance": tolerance, "evaluations": evaluations,
                "bracketed": False, "reason": f"regret stayed within tolerance up to r={low:.6g}"}
    while (high - low) > bisection_tolerance and evaluations < max_evaluations:
        middle = (low + high) / 2.0
        if regret_at(middle) <= tolerance:
            low = middle
        else:
            high = middle
    return {"radius": low, "tolerance": tolerance, "evaluations": evaluations,
            "bracketed": True, "reason": None,
            "convexity_used": "regret is convex in the perturbation radius along a linear ray"}


def degeneracy_report(problem: ConvexDecisionProblem, *, tolerance: float = 1e-8) -> dict[str, Any]:
    """Detect a non-unique optimum: linearly dependent risk-matrix columns.

    This matters for honesty about "the decision did not change". Under a singular risk
    matrix the *value* is unique but the *weights* need not be, so a value-regret certificate
    can be sound while a decision-identity claim is meaningless. The condition number and the
    rank deficit are reported explicitly.
    """

    q = problem.matrix()
    eigenvalues = np.linalg.eigvalsh(q)
    largest = float(eigenvalues[-1]) if eigenvalues.size else 0.0
    smallest = float(eigenvalues[0]) if eigenvalues.size else 0.0
    rank = int(np.sum(eigenvalues > tolerance * max(largest, 1.0)))
    condition = float(largest / smallest) if smallest > 0 else float("inf")
    return {
        "dimension": problem.dimension,
        "rank": rank,
        "rank_deficient": rank < problem.dimension,
        "smallest_eigenvalue": smallest,
        "largest_eigenvalue": largest,
        "condition_number": condition,
        "weight_identifiability": "unique" if smallest > tolerance * max(largest, 1.0) else "non_unique",
    }


__all__ = [
    "CERTIFICATE_SCHEMA",
    "DEFAULT_USEFUL_BOUND",
    "RADIUS_SCHEMA",
    "ZERO_GAP_TOLERANCE",
    "RevisionCertificate",
    "StabilityRadius",
    "certify_revision_impact",
    "degeneracy_report",
    "regret_tolerance_radius",
    "stability_radius",
]
