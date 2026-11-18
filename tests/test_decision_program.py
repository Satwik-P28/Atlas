"""Verification of the canonical decision program and its self-certifying solver.

The point of these tests is independence. The primal solution is checked against a
completely separate exact solver (active-set enumeration) and, for diagonal risk matrices,
against a closed form. The dual bound is checked against the primal by weak duality and its
gradient against finite differences. A test that compared the solver to itself would prove
nothing.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

# The decision layer needs SciPy, which lives in the `optimization` extra. The packaging
# contract forbids adding it to `dev`, so these tests skip rather than fail a minimal install.
pytest.importorskip("scipy", reason="the decision research layer requires the optimization extra")

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.decision.baselines import (
    equal_weight,
    mean_cvar,
    minimum_variance,
    robust_box,
    robust_ellipsoid,
    single_asset,
    strong_convexity_bound,
)
from atlas.decision.estimators import (
    covariance_diagnostics,
    diagonal_loading,
    ledoit_wolf_covariance,
    sample_covariance,
    sample_mean,
)
from atlas.decision.metrics import (
    cvar_historical,
    max_drawdown,
    moving_block_bootstrap_ci,
    turnover,
)
from atlas.decision.problem import (
    ConvexDecisionProblem,
    LinearInequality,
    check_feasibility,
    mean_variance_problem,
)
from atlas.decision.qp import (
    DualPoint,
    derive_multipliers,
    dual_objective,
    maximize_dual,
    solve,
    verify_kkt,
)


# --------------------------------------------------------------------- reference solvers
def enumerate_box_qp(problem: ConvexDecisionProblem) -> tuple[float, np.ndarray]:
    """Exact solution by enumerating every lower/free/upper assignment. Independent of SLSQP."""

    n = problem.dimension
    q = problem.matrix()
    c = problem.cost_vector()
    lower, upper = problem.bounds()
    best_value, best_weights = math.inf, None
    for assignment in itertools.product(("lower", "free", "upper"), repeat=n):
        pinned = [i for i, choice in enumerate(assignment) if choice != "free"]
        free = [i for i, choice in enumerate(assignment) if choice == "free"]
        w = np.zeros(n)
        for i in pinned:
            w[i] = lower[i] if assignment[i] == "lower" else upper[i]
        if not free:
            if abs(float(np.sum(w)) - problem.budget) <= 1e-9:
                value = problem.objective(w)
                if value < best_value:
                    best_value, best_weights = value, w
            continue
        q_ff = q[np.ix_(free, free)]
        cross = q[np.ix_(free, pinned)] @ w[pinned] if pinned else np.zeros(len(free))
        block = np.zeros((len(free) + 1, len(free) + 1))
        block[:len(free), :len(free)] = q_ff
        block[:len(free), len(free)] = 1.0
        block[len(free), :len(free)] = 1.0
        target = np.concatenate((-(c[free] + cross),
                                 [problem.budget - float(np.sum(w[pinned]))]))
        solution = np.linalg.lstsq(block, target, rcond=None)[0]
        w[free] = solution[:len(free)]
        if np.any(w[free] < lower[free] - 1e-9) or np.any(w[free] > upper[free] + 1e-9):
            continue
        if abs(float(np.sum(w)) - problem.budget) > 1e-9:
            continue
        value = problem.objective(w)
        if value < best_value:
            best_value, best_weights = value, w
    assert best_weights is not None, "enumeration found no feasible allocation"
    return best_value, best_weights


def diagonal_closed_form(expected_returns, variances, risk_aversion, budget):
    """For ``Q = risk_aversion * diag(variances)`` the optimum is a clipped 1-D root find."""

    from scipy.optimize import brentq

    mu = np.asarray(expected_returns, dtype=float)
    q = np.asarray(variances, dtype=float) * risk_aversion

    def shares(nu: float) -> np.ndarray:
        return np.clip((mu - nu) / q, 0.0, None)

    nu = brentq(lambda value: float(np.sum(shares(value)) - budget), -10.0, 10.0, xtol=1e-15)
    return shares(nu)


def random_problem(seed: int, *, n: int = 4, upper: float = 0.7) -> ConvexDecisionProblem:
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(n, n))
    sigma = a @ a.T / n * 0.05 + np.eye(n) * 0.01
    mu = rng.normal(0.08, 0.03, size=n)
    return mean_variance_problem(
        problem_id=f"random-{seed}",
        assets=[f"A{i}" for i in range(n)],
        expected_returns=mu,
        covariance=sigma,
        risk_aversion=3.0,
        lower=0.0,
        upper=upper,
        budget=1.0,
    )


# ------------------------------------------------------------------------------ schema
def test_problem_rejects_dimension_mismatch():
    with pytest.raises(ValidationError):
        ConvexDecisionProblem(
            problem_id="bad", variables=("a", "b"), linear_costs=(0.0,),
            risk_matrix=((1.0, 0.0), (0.0, 1.0)), lower=(0.0, 0.0), upper=(1.0, 1.0), budget=1.0,
        )


def test_problem_rejects_indefinite_risk_matrix():
    with pytest.raises(ValidationError):
        ConvexDecisionProblem(
            problem_id="bad", variables=("a", "b"), linear_costs=(0.0, 0.0),
            risk_matrix=((1.0, 0.0), (0.0, -0.5)), lower=(0.0, 0.0), upper=(1.0, 1.0), budget=1.0,
        )


def test_problem_rejects_asymmetric_risk_matrix():
    with pytest.raises(ValidationError):
        ConvexDecisionProblem(
            problem_id="bad", variables=("a", "b"), linear_costs=(0.0, 0.0),
            risk_matrix=((1.0, 0.5), (0.2, 1.0)), lower=(0.0, 0.0), upper=(1.0, 1.0), budget=1.0,
        )


def test_problem_rejects_inverted_bounds_and_nonfinite_values():
    with pytest.raises(ValidationError):
        ConvexDecisionProblem(
            problem_id="bad", variables=("a",), linear_costs=(0.0,), risk_matrix=((1.0,),),
            lower=(0.5,), upper=(0.1,), budget=0.2,
        )
    with pytest.raises(ValidationError):
        ConvexDecisionProblem(
            problem_id="bad", variables=("a",), linear_costs=(math.nan,), risk_matrix=((1.0,),),
            lower=(0.0,), upper=(1.0,), budget=0.2,
        )


def test_mean_variance_requires_positive_risk_aversion():
    with pytest.raises(ValidationError):
        mean_variance_problem(problem_id="x", assets=["a"], expected_returns=[0.1],
                              covariance=[[0.04]], risk_aversion=0.0)


def test_digest_ignores_provenance_but_tracks_mathematics():
    problem = random_problem(11)
    same_math = problem.replace(as_of="2030-01-01T00:00:00Z", evidence_ids=("e1",))
    with_different_cost = problem.replace(
        linear_costs=tuple(value + 0.001 for value in problem.linear_costs)
    )
    assert problem.digest() == same_math.digest()
    assert problem.digest() != with_different_cost.digest()


def test_feasibility_reports_the_violated_constraint():
    problem = random_problem(3)
    report = check_feasibility(problem, (0.0, 0.0, 0.0, 0.0))
    assert not report.feasible
    assert report.budget_residual == pytest.approx(1.0)
    assert any("budget" in detail for detail in report.details)

    capped = problem.replace(upper=(0.1, 0.1, 0.1, 1.0))
    report = check_feasibility(capped, (0.5, 0.5, 0.0, 0.0))
    assert not report.feasible
    assert report.upper_violation == pytest.approx(0.4)


# ------------------------------------------------------------------------------- solver
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_primal_matches_independent_active_set_enumeration(seed):
    problem = random_problem(seed)
    solution = solve(problem)
    reference_value, reference_weights = enumerate_box_qp(problem)
    assert solution.feasible
    assert solution.objective == pytest.approx(reference_value, abs=1e-10)
    assert np.max(np.abs(np.asarray(solution.weights) - reference_weights)) < 1e-8


def test_diagonal_case_matches_closed_form():
    mu = [0.10, 0.12, 0.08]
    variances = [0.04, 0.05, 0.03]
    problem = mean_variance_problem(
        problem_id="diag", assets=["A", "B", "C"], expected_returns=mu,
        covariance=np.diag(variances), risk_aversion=1.0, lower=0.0, upper=1.0, budget=1.0,
    )
    expected = diagonal_closed_form(mu, variances, 1.0, 1.0)
    solution = solve(problem)
    assert np.max(np.abs(np.asarray(solution.weights) - expected)) < 1e-8


def test_solution_is_self_certifying():
    problem = random_problem(21)
    solution = solve(problem)
    assert solution.status == "optimal"
    assert solution.certified_optimal
    assert solution.kkt.satisfied
    assert solution.duality_gap is not None and abs(solution.duality_gap) <= 1e-9
    assert solution.kkt.stationarity <= solution.kkt.tolerance
    assert solution.kkt.complementarity <= solution.kkt.tolerance


def test_dual_gradient_matches_finite_differences():
    """This is the test that catches a wrong sign in the dual objective."""

    problem = random_problem(5)
    point = DualPoint(nu=0.04, alpha=tuple([0.01] * 4), beta=tuple([0.01] * 4))
    value, _w, gradient = dual_objective(problem, point)
    steps = 1e-5
    numeric = []
    base = {"nu": point.nu, "alpha": list(point.alpha), "beta": list(point.beta)}
    coordinates = [("nu", 0)] + [("alpha", i) for i in range(4)] + [("beta", i) for i in range(4)]

    def shifted(kind: str, index: int, amount: float) -> float:
        moved = {k: (list(v) if isinstance(v, list) else v) for k, v in base.items()}
        if kind == "nu":
            moved["nu"] = base["nu"] + amount
        else:
            moved[kind][index] = base[kind][index] + amount
        candidate = DualPoint(nu=moved["nu"], alpha=tuple(moved["alpha"]),
                              beta=tuple(moved["beta"]))
        return dual_objective(problem, candidate)[0]

    for kind, index in coordinates:
        # Central differences remove the O(h) truncation term that a one-sided step leaves on
        # a quadratic, which is what made this comparison look like a gradient error.
        numeric.append((shifted(kind, index, steps) - shifted(kind, index, -steps)) / (2 * steps))
    assert np.max(np.abs(np.asarray(numeric) - gradient)) < 1e-8


@given(st.integers(min_value=0, max_value=40))
@settings(max_examples=12, deadline=None)
def test_weak_duality_holds_for_every_admissible_dual_point(seed):
    problem = random_problem(seed, n=3)
    solution = solve(problem)
    if solution.dual_bound is None:
        pytest.skip("no finite dual bound for this instance")
    assert solution.dual_bound <= solution.objective + 1e-9
    point, _diagnostics = maximize_dual(problem, max_iter=80)
    assert point.value is not None
    assert point.value <= solution.objective + 1e-9


def test_infeasible_budget_is_reported_not_repaired():
    problem = random_problem(7).replace(upper=(0.1, 0.1, 0.1, 0.1))
    solution = solve(problem)
    assert solution.status == "infeasible"
    assert not solution.feasible
    assert solution.diagnostics["failure_code"] == "budget_infeasible"

    below = random_problem(7).replace(lower=(0.9, 0.9, 0.0, 0.0), upper=(1.0, 1.0, 0.7, 0.7))
    solution = solve(below)
    assert solution.status == "infeasible"
    assert solution.diagnostics["failure_code"] == "budget_infeasible"


def test_singular_risk_matrix_refuses_the_dual_bound_but_solves():
    n = 3
    returns = [[0.01, 0.02, 0.03], [0.02, 0.01, 0.04], [0.0, 0.03, 0.02], [0.01, 0.0, 0.01]]
    singular = sample_covariance(returns) * 0.0  # exactly zero matrix: PSD but singular
    problem = mean_variance_problem(
        problem_id="singular", assets=["a", "b", "c"], expected_returns=[0.1, 0.2, 0.3],
        covariance=singular, risk_aversion=1.0, lower=0.0, upper=1.0, budget=1.0,
    )
    solution = solve(problem)
    # A singular risk matrix makes the dual unbounded, so no finite *regret bound* exists.
    assert solution.dual_bound is None
    assert solution.duality_gap is None
    assert "positive definite" in solution.diagnostics["dual"]["error"]
    # The KKT system is still a complete optimality certificate for a convex program, so the
    # status is allowed to be "optimal" even though no quantitative bound is available.
    assert solution.kkt.satisfied
    assert solution.certified_optimal


def test_kkt_detects_a_non_optimal_candidate():
    problem = random_problem(9)
    solution = solve(problem)
    shifted = np.asarray(solution.weights) + np.array([0.02, -0.02, 0.0, 0.0])
    report = verify_kkt(problem, shifted)
    assert not report.satisfied
    assert report.stationarity > report.tolerance or report.complementarity > report.tolerance


def test_multiplier_recovery_is_exact_at_the_optimum():
    problem = random_problem(13)
    solution = solve(problem)
    point, diagnostics = derive_multipliers(problem, solution.weights)
    assert point is not None
    assert diagnostics["residual"] < 1e-10
    assert diagnostics["sign_violation"] < 1e-12


def test_inequality_rows_are_enforced():
    problem = random_problem(17).replace(
        inequalities=(LinearInequality((1.0, 1.0, 0.0, 0.0), 0.25, "pair_cap"),)
    )
    solution = solve(problem)
    weights = np.asarray(solution.weights)
    assert weights[0] + weights[1] <= 0.25 + 1e-9
    assert solution.certified_optimal


def test_runtime_and_solver_metadata_are_recorded():
    solution = solve(random_problem(19))
    assert solution.runtime_ms > 0
    assert solution.solver
    assert solution.diagnostics["solver_versions"]["numpy"]
    assert solution.diagnostics["primal"]["message"]


# ---------------------------------------------------------------------------- baselines
def test_equal_weight_is_feasible_and_balanced():
    problem = random_problem(23)
    result = equal_weight(problem)
    assert result.feasible
    assert np.allclose(result.weights, 0.25)


def test_single_asset_respects_the_cap():
    problem = random_problem(23)
    result = single_asset(problem, 0)
    assert result.feasible
    assert result.weights[0] == pytest.approx(min(1.0, problem.upper[0]))


def test_minimum_variance_does_not_exceed_equal_weight_variance():
    problem = random_problem(29)
    minvar = minimum_variance(problem)
    equal = equal_weight(problem)
    q = problem.matrix()
    assert np.asarray(minvar.weights) @ q @ np.asarray(minvar.weights) <= \
        np.asarray(equal.weights) @ q @ np.asarray(equal.weights) + 1e-10


def test_box_ambiguity_is_vacuous_for_a_long_only_budget():
    """``||w||_1`` is constant on the simplex, so a box on the mean cannot change the decision.

    This is a mathematical fact, not a defect, and it is why the ellipsoidal counterpart is
    the meaningful fixed-radius robust baseline.
    """

    problem = random_problem(31)
    base = solve(problem)
    robust = robust_box(problem, 0.05)
    assert np.max(np.abs(np.asarray(base.weights) - np.asarray(robust.weights))) < 1e-6


def test_ellipsoidal_robustness_changes_the_allocation():
    problem = random_problem(31)
    base = solve(problem)
    robust = robust_ellipsoid(problem, 0.05)
    assert robust.feasible
    assert np.max(np.abs(np.asarray(base.weights) - np.asarray(robust.weights))) > 1e-3
    assert np.linalg.norm(robust.weights) <= np.linalg.norm(base.weights) + 1e-6


def test_mean_cvar_returns_a_feasible_allocation():
    rng = np.random.default_rng(4)
    scenarios = rng.normal(0.001, 0.01, size=(200, 4))
    problem = random_problem(33)
    result = mean_cvar(problem, scenarios, alpha=0.9)
    assert result.feasible
    assert sum(result.weights) == pytest.approx(1.0, abs=1e-7)


def test_strong_convexity_bound_is_valid_but_loose_at_a_constrained_optimum():
    """The gradient-norm bound ignores the constraints, so it does not vanish at the optimum.

    ``f(w) - f* <= ||grad f(w)||^2 / (2m)`` holds for every feasible ``w``, but at a *constrained*
    optimum the gradient is balanced by multipliers rather than zero, so the bound stays
    positive even though the gap is zero. It is a valid competitor, not a tight one, and the
    report says exactly that.
    """

    problem = random_problem(37)
    solution = solve(problem)
    report = strong_convexity_bound(problem, solution.weights)
    assert report["valid"]
    assert report["bound"] > 0.0
    reference_value, _weights = enumerate_box_qp(problem)
    realized = problem.objective(solution.weights) - reference_value
    assert realized <= 1e-10
    assert report["bound"] >= realized - 1e-12


# --------------------------------------------------------------------------- estimators
def test_ledoit_wolf_matches_the_independent_sklearn_implementation():
    sklearn_covariance = pytest.importorskip("sklearn.covariance")
    rng = np.random.default_rng(123)
    returns = rng.normal(0.0, 0.02, size=(60, 8))
    ours, shrinkage = ledoit_wolf_covariance(returns)
    reference = sklearn_covariance.LedoitWolf().fit(returns)
    assert shrinkage == pytest.approx(reference.shrinkage_, abs=1e-8)
    assert np.max(np.abs(ours - reference.covariance_)) < 1e-10
    diagnostics = covariance_diagnostics(ours)
    assert diagnostics["positive_definite"]


def test_diagonal_loading_makes_a_singular_matrix_positive_definite():
    rng = np.random.default_rng(5)
    returns = rng.normal(size=(4, 6))
    singular = sample_covariance(returns)
    assert covariance_diagnostics(singular)["positive_definite"] is False
    loaded = diagonal_loading(singular, floor=1e-6)
    assert covariance_diagnostics(loaded)["positive_definite"] is True


def test_sample_moments_are_plain_and_correct():
    returns = [[0.0, 1.0], [2.0, 3.0]]
    assert np.allclose(sample_mean(returns), [1.0, 2.0])
    assert np.allclose(sample_covariance(returns), [[2.0, 2.0], [2.0, 2.0]])


# ------------------------------------------------------------------------------ metrics
def test_turnover_is_half_the_l1_distance():
    assert turnover([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)
    assert turnover([0.5, 0.5], [0.5, 0.5]) == 0.0


def test_cvar_is_the_mean_of_the_worst_tail():
    values = list(range(1, 101))
    assert cvar_historical([-float(v) for v in values], confidence=0.9) == pytest.approx(-95.5)


def test_max_drawdown_of_a_monotone_decline():
    assert max_drawdown([-0.5]) == pytest.approx(0.5)
    assert max_drawdown([0.1, 0.1]) == pytest.approx(0.0)


def test_block_bootstrap_is_deterministic_for_a_seed_and_reports_its_assumptions():
    values = list(np.linspace(-0.01, 0.02, 60))
    first = moving_block_bootstrap_ci(values, block=5, resamples=200, seed=7)
    second = moving_block_bootstrap_ci(values, block=5, resamples=200, seed=7)
    assert first == second
    assert first["lower"] <= first["statistic"] <= first["upper"]
    assert first["block_length"] == 5
    assert "block length" in first["caveat"]
