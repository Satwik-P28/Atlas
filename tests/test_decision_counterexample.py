"""The reviewer's counterexample, and the property it falsified.

A two-variable program with a single general inequality admits a complete hand calculation of
every quantity in the residual certificate. The version of the certificate that negated its
inequality slack term reported a bound of ``0.235`` here while the regret is ``0.510``; an
unsound bound, not merely a loose one. The numbers are small enough to check on paper, which is
the point: a trend in a 598-event study cannot distinguish a sign error from noise, and this can.

Problem::

    min  0.5 (w1^2 + w2^2) - 2 w1
    s.t. w1 + w2 = 1,  0 <= w_i <= 1,  w1 <= 0.8

with recorded ``w = (0.5, 0.5)`` and dual point ``nu = alpha = beta = 0``, ``gamma = 0.7``.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy", reason="the decision research layer requires the optimization extra")

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.decision.problem import (  # noqa: E402
    ConvexDecisionProblem,
    LinearInequality,
    check_feasibility,
)
from atlas.decision.qp import (  # noqa: E402
    DualPoint,
    derive_multipliers,
    dual_objective,
    residual_regret_bound,
    solve,
)
from atlas.decision.reference import solve_clarabel, solve_osqp  # noqa: E402

RECORDED = np.array([0.5, 0.5])


def counterexample_problem() -> ConvexDecisionProblem:
    return ConvexDecisionProblem(
        problem_id="audit-counterexample",
        variables=("w1", "w2"),
        linear_costs=(-2.0, 0.0),
        risk_matrix=((1.0, 0.0), (0.0, 1.0)),
        lower=(0.0, 0.0),
        upper=(1.0, 1.0),
        budget=1.0,
        inequalities=(LinearInequality((1.0, 0.0), 0.8, "w1 <= 0.8"),),
    )


def audit_dual() -> DualPoint:
    problem = counterexample_problem()
    return DualPoint(nu=0.0, alpha=(0.0, 0.0), beta=(0.0, 0.0), gamma=(0.7,),
                     structure_digest=problem.structure_digest())


def test_reference_optimum_is_the_hand_solution_under_three_solvers():
    problem = counterexample_problem()
    internal = solve(problem)
    osqp = solve_osqp(problem)
    clarabel = solve_clarabel(problem)
    for weights in (internal.weights, osqp.weights, clarabel.weights):
        assert weights[0] == pytest.approx(0.8, abs=1e-6)
        assert weights[1] == pytest.approx(0.2, abs=1e-6)
    for value in (internal.objective, osqp.objective, clarabel.objective):
        assert value == pytest.approx(-1.26, abs=1e-7)


def test_hand_computable_regret_is_five_hundred_and_ten_thousandths():
    problem = counterexample_problem()
    # f(w) = 0.5(0.25 + 0.25) - 2(0.5) = -0.75;  f* = 0.5(0.64 + 0.04) - 1.6 = -1.26.
    assert problem.objective(RECORDED) == pytest.approx(-0.75)
    regret = problem.objective(RECORDED) - (-1.26)
    assert regret == pytest.approx(0.510, abs=1e-12)


def test_the_dual_gap_at_the_audit_point_is_the_hand_value():
    """``f(w) - g(lambda)`` with ``nu = alpha = beta = 0``, ``gamma = 0.7``."""

    problem = counterexample_problem()
    dual_value, _w, _grad = dual_objective(problem, audit_dual())
    assert dual_value == pytest.approx(-1.405, abs=1e-12)
    gap = problem.objective(RECORDED) - dual_value
    assert gap == pytest.approx(0.655, abs=1e-12)


def test_residual_bound_reproduces_the_gap_and_dominates_the_regret():
    """The regression that the negated slack term failed.

    ``0.5 r'Q^-1 r = 0.445`` and ``gamma'(d - Aw) = 0.7 * 0.3 = 0.21`` sum to ``0.655``. The
    defective version subtracted the second term and reported ``0.235``, below the ``0.510``
    regret it claimed to bound.
    """

    problem = counterexample_problem()
    report = residual_regret_bound(problem, RECORDED, audit_dual())
    assert report["quadratic_form"] == pytest.approx(0.445, abs=1e-12)
    assert report["slack_terms"]["gamma_d_minus_Aw"] == pytest.approx(0.21, abs=1e-12)
    assert report["slack_terms"]["alpha_w_minus_l"] == 0.0
    assert report["slack_terms"]["beta_u_minus_w"] == 0.0
    assert report["bound"] == pytest.approx(0.655, abs=1e-12)
    assert report["bound"] > 0.510
    assert report["valid"] is True
    assert report["identity_check"]["identity_ok"] is True
    assert report["gap_identity_residual"] <= 1e-12


def test_the_old_negated_slack_would_have_been_unsound():
    """Pin the failure so a future edit cannot reintroduce it unnoticed."""

    problem = counterexample_problem()
    report = residual_regret_bound(problem, RECORDED, audit_dual())
    defective = report["quadratic_form"] - report["slack_terms"]["gamma_d_minus_Aw"]
    assert defective == pytest.approx(0.235, abs=1e-12)
    assert defective < 0.510, "the negated form understates the regret it claims to bound"


def test_inequality_slack_vanishes_when_the_constraint_is_tight():
    """At a point where ``w1 <= 0.8`` is tight, the gamma term vanishes and both forms agree.

    This is why the defect needed an *inactive* row to surface: on an active row the two sign
    conventions are identical, and every test that only exercised active constraints passed.
    """

    problem = counterexample_problem()
    tight = np.array([0.8, 0.2])
    report = residual_regret_bound(problem, tight, audit_dual())
    assert report["slack_terms"]["gamma_d_minus_Aw"] == pytest.approx(0.0, abs=1e-12)
    assert report["bound"] == pytest.approx(report["quadratic_form"], abs=1e-12)
    # The remaining 0.145 is the stationarity residual of the audit dual, not the inequality slack.
    assert report["quadratic_form"] == pytest.approx(0.145, abs=1e-12)
    assert report["identity_check"]["identity_ok"] is True


def test_every_slack_term_is_nonnegative_at_a_feasible_point():
    problem = counterexample_problem()
    assert check_feasibility(problem, RECORDED).feasible
    report = residual_regret_bound(problem, RECORDED, audit_dual())
    for name, value in report["slack_terms"].items():
        assert value >= -1e-15, f"{name} should be a non-negative complementarity term"


def test_multipliers_recovered_at_the_optimum_certify_zero_within_residual():
    problem = counterexample_problem()
    point, _diagnostics = derive_multipliers(problem, np.array([0.8, 0.2]))
    assert point is not None
    report = residual_regret_bound(problem, np.array([0.8, 0.2]), point)
    assert report["valid"] is True
    assert report["bound"] <= 1e-12
    assert report["identity_check"]["identity_ok"] is True


def test_negative_gamma_is_still_refused_before_any_arithmetic():
    problem = counterexample_problem()
    bad = DualPoint(nu=0.0, alpha=(0.0, 0.0), beta=(0.0, 0.0), gamma=(-0.7,))
    with pytest.raises(ValidationError, match="non-negative"):
        residual_regret_bound(problem, RECORDED, bad)
