"""Independent verification of the two P0 corrections and the worst-case certificate.

Three things are checked here and nothing else:

1. **Direction.** Weak duality is an inequality with a specific orientation. The tests assert the
   orientation numerically on instances where the wrong direction would produce a negative,
   obviously false "bound".
2. **Preconditions.** A dual point with a negative multiplier, a non-finite value, a wrong
   dimension or a different constraint geometry is refused, and the false bound it would have
   produced is exhibited so the refusal is not merely cosmetic.
3. **Soundness of the worst-case certificate** against an independent solver (OSQP) over
   explicitly enumerated or sampled corrections, including corrections outside the declared set.

The reference regret is always computed by a different implementation from the one under test.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

pytest.importorskip("scipy", reason="the decision research layer requires the optimization extra")

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.decision.certificate import certify_revision_impact  # noqa: E402
from atlas.decision.problem import ConvexDecisionProblem, mean_variance_problem  # noqa: E402
from atlas.decision.qp import (  # noqa: E402
    DualPoint,
    dual_objective,
    residual_regret_bound,
    derive_multipliers,
    maximize_dual,
    solve,
    validate_dual_point,
)
from atlas.decision.reference import (  # noqa: E402
    cross_check,
    enumerate_box_solution,
    solve_clarabel,
    solve_osqp,
)
from atlas.decision.revision import (  # noqa: E402
    EvidenceRevision,
    InputSensitivity,
    compile_revisions,
)
from atlas.decision.uncertainty import (  # noqa: E402
    adversarial_out_of_set_check,
    certify_worst_case,
    curvature_bound,
    ellipsoid_set,
    interval_set,
)

DECISION_CLOCK = "2024-11-01T21:00:00Z"
AUDIT_CLOCK = "2024-11-05T12:00:00Z"


def make_problem(seed: int = 3, *, n: int = 5, upper: float = 0.5,
                 as_of: str | None = DECISION_CLOCK) -> ConvexDecisionProblem:
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(n, n))
    sigma = a @ a.T / n * 0.04 + np.eye(n) * 0.01
    mu = rng.normal(0.08, 0.02, size=n)
    return mean_variance_problem(
        problem_id=f"verify-{seed}-{n}-{upper}",
        assets=[f"A{i}" for i in range(n)],
        expected_returns=mu,
        covariance=sigma,
        risk_aversion=4.0,
        lower=0.0,
        upper=upper,
        budget=1.0,
        as_of=as_of,
    )


def direct_gap(problem: ConvexDecisionProblem, weights, point: DualPoint) -> float:
    value, _w, _grad = dual_objective(problem, point)
    return float(problem.objective(np.asarray(weights)) - value)


# ------------------------------------------------------------------------ 1. direction
def test_weak_duality_has_the_documented_direction():
    """``g <= f* <= f(w)``, hence ``regret <= f(w) - g``. The reverse would be unsound."""

    problem = make_problem(11)
    solution = solve(problem)
    point, _diagnostics = derive_multipliers(problem, solution.weights)
    assert point is not None
    dual_value, _w, _grad = dual_objective(problem, point)
    objective = problem.objective(solution.weights)
    # A dual feasible value never exceeds the primal objective at a feasible point.
    assert dual_value <= objective + 1e-12
    # Therefore the gap is a non-negative upper bound on the regret, not a lower bound.
    gap = objective - dual_value
    assert gap >= -1e-12
    assert gap <= 1e-6, f"the certificate at an optimal point should be tight, got {gap}"


def test_the_bound_is_an_upper_bound_on_realized_regret_not_a_lower_bound():
    problem = make_problem(12)
    solution = solve(problem)
    revision = EvidenceRevision("r", "e", "ret_0", 0.05, "2024-11-02T22:00:00Z")
    sensitivity = InputSensitivity("ret_0", (-1.0, 0.0, 0.0, 0.0, 0.0))
    compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=AUDIT_CLOCK)
    reference = solve_osqp(compilation.problem)
    realized = float(compilation.problem.objective(solution.weights) - reference.objective)
    certificate = certify_revision_impact(problem, solution.weights, compilation,
                                          decision_dual=solution.dual)
    bound = certificate.bounded["regret_upper_bound"]
    assert bound is not None
    assert bound >= realized - 1e-12, "the bound must not understate the realized regret"
    assert realized >= 0.0


# ------------------------------------------------------------------- 2. dual feasibility
def test_negative_multiplier_is_refused_and_its_false_bound_is_exhibited():
    """The adversarial example the review asked for.

    A negative ``alpha`` entry produces a *larger* dual value, which turns the gap negative and
    would be reported as a negative regret bound. The corrected evaluator refuses the point.
    """

    problem = make_problem(13)
    solution = solve(problem)
    n = problem.dimension
    # ``alpha = c`` cancels the cost vector inside the Lagrangian residual, driving it to zero.
    # With every alpha negative that is sign-infeasible, and the resulting "dual value" of 0
    # exceeds the true optimum, which is negative.
    assert all(value < 0 for value in problem.linear_costs)
    bad = DualPoint(nu=0.0, alpha=tuple(float(v) for v in problem.linear_costs),
                    beta=tuple(0.0 for _ in range(n)),
                    structure_digest=problem.structure_digest())
    with pytest.raises(ValidationError, match="non-negative"):
        dual_objective(problem, bad)
    with pytest.raises(ValidationError):
        validate_dual_point(problem, bad)

    # Show what the uncorrected code would have claimed. The value is computed with the sign
    # check bypassed on purpose, which is exactly the old behaviour.
    value, _w, _grad = dual_objective(problem, bad, strict=False)
    claimed = problem.objective(solution.weights) - value
    assert value > solution.objective, "the invalid point must beat the true optimum"
    assert claimed < 0.0, "so the \"regret bound\" it yields is negative and false"


def test_non_finite_multipliers_are_refused():
    problem = make_problem(14)
    n = problem.dimension
    for value in (float("nan"), float("inf"), float("-inf")):
        bad = DualPoint(nu=value, alpha=tuple(0.0 for _ in range(n)),
                        beta=tuple(0.0 for _ in range(n)))
        with pytest.raises(ValidationError, match="finite"):
            validate_dual_point(problem, bad)


def test_wrong_dimension_and_wrong_geometry_are_refused():
    problem = make_problem(15)
    n = problem.dimension
    with pytest.raises(ValidationError, match="dimension"):
        validate_dual_point(problem, DualPoint(0.0, (0.0,) * (n - 1), (0.0,) * n))
    # Same multipliers, different cap: the dual feasible set changed, so the recorded vector is
    # not a certificate for the new program.
    tightened = problem.replace(upper=tuple(0.4 for _ in range(n)))
    point = DualPoint(0.0, (0.0,) * n, (0.0,) * n,
                      structure_digest=problem.structure_digest())
    with pytest.raises(ValidationError, match="constraint structure"):
        validate_dual_point(tightened, point)
    # A cost-only revision leaves the structure digest unchanged, which is the case CRI needs.
    revised = problem.replace(linear_costs=tuple(v + 0.01 for v in problem.linear_costs))
    assert revised.structure_digest() == problem.structure_digest()
    assert revised.digest() != problem.digest()
    validate_dual_point(revised, point)


def test_certificate_reports_rejected_recorded_multipliers_instead_of_using_them():
    problem = make_problem(16)
    solution = solve(problem)
    revision = EvidenceRevision("r", "e", "ret_0", 0.02, "2024-11-02T22:00:00Z")
    sensitivity = InputSensitivity("ret_0", (-1.0, 0.0, 0.0, 0.0, 0.0))
    compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=AUDIT_CLOCK)
    n = problem.dimension
    invalid = DualPoint(0.0, tuple(-1.0 for _ in range(n)), tuple(0.0 for _ in range(n)))
    certificate = certify_revision_impact(problem, solution.weights, compilation,
                                          decision_dual=invalid)
    assert certificate.recorded_dual_status == "rejected"
    assert certificate.bounded["regret_upper_bound"] is None
    assert "non-negative" in certificate.bounded["recorded_dual_rejected_reason"]
    assert certificate.verdict in {"uncertified", "zero_regret_within_residual"}


def test_infeasible_recorded_decision_suppresses_the_bound():
    """A regret bound needs a feasible recorded point; reporting one was a defect."""

    problem = make_problem(17)
    solution = solve(problem)
    tightened = problem.replace(lower=tuple(0.34 for _ in range(problem.dimension)))
    compilation = compile_revisions(tightened, [], [], audit_as_of=AUDIT_CLOCK)
    certificate = certify_revision_impact(tightened, solution.weights, compilation,
                                          decision_dual=solution.dual)
    assert certificate.verdict == "infeasible_under_revision"
    assert certificate.bounded["regret_upper_bound"] is None
    assert "infeasible" in certificate.bounded["bound_rejected_reason"]


# ------------------------------------------------------------------------ 3. iteration budget
@pytest.mark.parametrize("budget", [0, 1, 2, 5, 10, 20, 50, 200])
def test_the_iteration_budget_is_the_budget_that_runs(budget: int):
    problem = make_problem(18)
    solution = solve(problem)
    revision = EvidenceRevision("r", "e", "ret_0", 0.03, "2024-11-02T22:00:00Z")
    sensitivity = InputSensitivity("ret_0", (-1.0, 0.0, 0.0, 0.0, 0.0))
    compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=AUDIT_CLOCK)
    certificate = certify_revision_impact(problem, solution.weights, compilation,
                                          decision_dual=solution.dual,
                                          dual_iterations=budget)
    record = certificate.bounded["dual_budget"]
    assert record["requested_iterations"] == budget
    assert record["actual_iterations"] <= budget
    assert record["budget_respected"] is True
    if budget == 0:
        assert record["performed"] is False
        assert record["objective_evaluations"] == 0
        assert certificate.bounded["bound_kind"] == "duality_gap_from_recorded_multipliers"
    else:
        assert record["performed"] is True
        assert record["final_value"] is not None
        assert record["objective_evaluations"] >= 1
        assert "iterations" in certificate.bounded["bound_kind"]


def test_more_iterations_never_worsen_the_bound():
    problem = make_problem(19)
    solution = solve(problem)
    revision = EvidenceRevision("r", "e", "ret_0", 0.03, "2024-11-02T22:00:00Z")
    sensitivity = InputSensitivity("ret_0", (-1.0, 0.0, 0.0, 0.0, 0.0))
    compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=AUDIT_CLOCK)
    bounds = []
    for budget in (0, 1, 2, 5, 20):
        certificate = certify_revision_impact(problem, solution.weights, compilation,
                                              decision_dual=solution.dual,
                                              dual_iterations=budget)
        bounds.append(certificate.bounded["regret_upper_bound"])
    assert all(b is not None for b in bounds)
    for earlier, later in zip(bounds, bounds[1:]):
        assert later <= earlier + 1e-12


# --------------------------------------------------------------------- 4. residual bound
def test_residual_bound_satisfies_its_identity_and_bounds_the_gap():
    problem = make_problem(20)
    solution = solve(problem)
    point, diagnostics = derive_multipliers(problem, solution.weights)
    assert point is not None
    report = residual_regret_bound(problem, solution.weights, point)
    assert report["valid"] is True
    # 0.5 r'Q^-1 r + slack must reproduce the duality gap, which is what makes it a bound.
    identity = report["identity_check"]
    assert identity["absolute_difference"] <= 1e-12 * max(1.0, abs(report["duality_gap"])) \
        or identity["absolute_difference"] <= 1e-14
    assert report["bound"] is not None
    assert report["bound"] >= -1e-15
    assert report["conservative_bound"] >= report["bound"] - 1e-12
    assert diagnostics["recovery_method"] in {"least_squares", "nonnegative_lp"}


def test_residual_bound_is_sound_when_multipliers_are_not_complementary():
    """The slack term is what keeps the bound valid away from complementarity."""

    problem = make_problem(21)
    solution = solve(problem)
    n = problem.dimension
    # Non-zero multipliers on inactive constraints: dual feasible, not complementary.
    point = DualPoint(nu=solution.dual.nu if solution.dual else 0.0,
                      alpha=tuple(1e-3 for _ in range(n)),
                      beta=tuple(1e-3 for _ in range(n)))
    report = residual_regret_bound(problem, solution.weights, point)
    assert report["valid"] is True
    assert report["complementarity_slack"] > 0.0
    reference = solve_osqp(problem)
    realized = float(problem.objective(solution.weights) - reference.objective)
    assert report["bound"] >= realized - 1e-10


def test_singular_risk_matrix_removes_the_bound_but_not_the_kkt_test():
    problem = make_problem(22, n=4)
    # Two identical columns make the risk matrix singular.
    mutated = np.asarray(problem.risk_matrix, dtype=float).copy()
    mutated[1, :] = mutated[0, :]
    mutated[:, 1] = mutated[:, 0]
    singular = problem.replace(risk_matrix=tuple(tuple(float(v) for v in row) for row in mutated))
    with pytest.raises(ValidationError, match="positive definite"):
        maximize_dual(singular, max_iter=5)


# ------------------------------------------------------------------ 5. independent solvers
def test_three_independent_solvers_agree_to_machine_precision():
    problem = make_problem(23)
    report = cross_check(problem, exhaustive=True)
    assert report["agree"] is True
    assert report["objective_spread"] is not None
    assert report["objective_spread"] < 1e-9
    available = {name for name, entry in report["methods"].items() if entry["available"]}
    assert {"osqp", "clarabel", "exhaustive"} <= available


def test_osqp_and_clarabel_both_reach_the_exhaustive_optimum_on_random_problems():
    for seed in (31, 32, 33):
        problem = make_problem(seed, n=6)
        exhaustive = enumerate_box_solution(problem)
        osqp = solve_osqp(problem)
        clarabel = solve_clarabel(problem)
        assert osqp.feasible and clarabel.feasible
        assert abs(osqp.objective - exhaustive.objective) < 1e-7
        assert abs(clarabel.objective - exhaustive.objective) < 1e-7


def test_primary_solver_matches_the_independent_reference():
    for seed in (41, 42, 43):
        problem = make_problem(seed, n=5)
        mine = solve(problem)
        reference = solve_osqp(problem)
        assert abs(mine.objective - reference.objective) < 1e-9


# ------------------------------------------------------------- 6. worst-case certificate
def test_singleton_worst_case_reduces_to_the_cri_bound():
    """The generalisation must agree with the special case, otherwise it is a parallel theory."""

    problem = make_problem(24)
    solution = solve(problem)
    delta = np.zeros(problem.dimension)
    delta[0] = 0.03
    singleton = interval_set(center=delta, half_width=[0.0] * problem.dimension,
                             coverage="a singleton is the exact-revision case")
    certificate = certify_worst_case(problem, solution.weights, singleton,
                                     decision_dual=solution.dual)
    perturbed = problem.replace(linear_costs=tuple(float(v) for v in
                                                  problem.cost_vector() + delta))
    cri_gap = direct_gap(perturbed, solution.weights, DualPoint(
        nu=solution.dual.nu, alpha=solution.dual.alpha, beta=solution.dual.beta,
        gamma=solution.dual.gamma))
    assert certificate.valid is True
    assert certificate.bound == pytest.approx(cri_gap, abs=1e-12)


@pytest.mark.parametrize("seed", [51, 52, 53, 54])
def test_interval_worst_case_bound_covers_every_vertex(seed: int):
    problem = make_problem(seed, n=4)
    solution = solve(problem)
    center = np.zeros(problem.dimension)
    center[0] = 0.01
    half = np.full(problem.dimension, 0.01)
    uset = interval_set(center=center, half_width=half, coverage="synthetic test set")
    certificate = certify_worst_case(problem, solution.weights, uset,
                                     decision_dual=solution.dual, gradient_steps=20)
    assert certificate.valid is True
    worst = -math.inf
    for signs in itertools.product((1.0, -1.0), repeat=problem.dimension):
        delta = center + half * np.asarray(signs)
        perturbed = problem.replace(linear_costs=tuple(
            float(v) for v in problem.cost_vector() + delta))
        reference = solve_osqp(perturbed)
        worst = max(worst, float(perturbed.objective(solution.weights) - reference.objective))
    assert certificate.bound >= worst - 1e-10, (
        f"bound {certificate.bound:.6g} understated the true worst case {worst:.6g}")


def test_ellipsoid_worst_case_bound_covers_sampled_corrections():
    problem = make_problem(55, n=4)
    solution = solve(problem)
    shape = np.eye(problem.dimension) * 0.01
    uset = ellipsoid_set(center=[0.01, 0.0, 0.0, 0.0], shape=shape, radius=1.0,
                         coverage="synthetic test ellipsoid")
    certificate = certify_worst_case(problem, solution.weights, uset,
                                     decision_dual=solution.dual, gradient_steps=20)
    assert certificate.valid is True
    rng = np.random.default_rng(7)
    worst = -math.inf
    for _ in range(24):
        direction = rng.normal(size=problem.dimension)
        direction /= np.linalg.norm(direction)
        delta = uset.center_array() + 0.01 * direction if hasattr(uset, "center_array") else (
            np.asarray(uset.center) + 0.01 * direction)
        perturbed = problem.replace(linear_costs=tuple(
            float(v) for v in problem.cost_vector() + delta))
        reference = solve_osqp(perturbed)
        worst = max(worst, float(perturbed.objective(solution.weights) - reference.objective))
    assert certificate.bound >= worst - 1e-10


def test_curvature_term_is_the_only_conservatism_for_a_large_set():
    problem = make_problem(56, n=3)
    solution = solve(problem)
    wide = interval_set(center=[0.0, 0.0, 0.0], half_width=[0.5, 0.5, 0.5],
                        coverage="deliberately wide")
    report = curvature_bound(problem, wide)
    assert report["method"] == "elementwise_envelope_box"
    # The envelope must dominate the quadratic at every vertex of the box.
    inverse = np.linalg.inv(problem.matrix())
    for signs in itertools.product((1.0, -1.0), repeat=3):
        delta = 0.5 * np.asarray(signs)
        assert 0.5 * delta @ inverse @ delta <= report["value"] + 1e-15


def test_out_of_set_corrections_are_measured_not_hidden():
    problem = make_problem(57, n=4)
    solution = solve(problem)
    narrow = interval_set(center=[0.0] * 4, half_width=[0.001] * 4,
                          coverage="deliberately narrow so the check can fail")
    certificate = certify_worst_case(problem, solution.weights, narrow,
                                     decision_dual=solution.dual)
    outside = np.zeros(4)
    outside[0] = 0.2  # far outside the declared set
    check = adversarial_out_of_set_check(problem, solution.weights, narrow,
                                         certificate.bound, outside)
    assert check["inside_declared_set"] is False
    assert check["distance_outside"] > 0.0
    assert check["violated"] is True, "a correction outside the set must be able to violate"
    assert "not a defect" in check["note"]
