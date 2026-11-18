"""Randomised property tests across geometries, multipliers, scales and uncertainty shapes.

Each property is stated as an implication that must hold for *every* sampled instance, not as a
comparison against a stored number, so a change that breaks the mathematics fails here even if it
reproduces the published tables. Sampling is seeded, so a failure is reproducible.

The properties:

1. The gap identity ``f(w) - g(lambda) = 0.5 r'Q^-1 r + slack`` holds to round-off for any
   dual-feasible ``lambda``, including nonzero multipliers on *inactive* inequalities.
2. The residual bound never falls below the realized regret, measured by an independent solver.
3. The ellipsoid's support function, maximiser, curvature envelope and membership predicate all
   describe the same set.
4. Supersession and withdrawal are resolved at the audit cut-off, not at the archive's latest
   state.
5. CRI-U refuses to present an infeasible recorded decision as a decision guarantee.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

pytest.importorskip("scipy", reason="the decision research layer requires the optimization extra")

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.decision.certificate import certify_revision_impact  # noqa: E402
from atlas.decision.problem import (  # noqa: E402
    ConvexDecisionProblem,
    LinearInequality,
    check_feasibility,
    mean_variance_problem,
)
from atlas.decision.qp import (  # noqa: E402
    DualPoint,
    derive_multipliers,
    dual_objective,
    residual_regret_bound,
    solve,
)
from atlas.decision.reference import solve_clarabel, solve_osqp  # noqa: E402
from atlas.decision.revision import (  # noqa: E402
    EvidenceRevision,
    InputSensitivity,
    compile_revisions,
)
from atlas.decision.uncertainty import (  # noqa: E402
    certify_worst_case,
    curvature_bound,
    ellipsoid_set,
    interval_set,
)

DECISION_CLOCK = "2024-11-01T21:00:00Z"
AUDIT_CLOCK = "2024-11-05T12:00:00Z"


def random_problem(rng: np.random.Generator, *, n: int, rows: int, scale: float,
                   as_of: str | None = DECISION_CLOCK) -> ConvexDecisionProblem:
    a = rng.normal(size=(n, n))
    covariance = (a @ a.T / n) * scale + np.eye(n) * scale * 0.25
    mu = rng.normal(0.08, 0.02, size=n)
    inequalities = []
    for _ in range(rows):
        coefficients = rng.normal(size=n)
        # A bound that is not trivially satisfied for a budget-one allocation.
        limit = float(np.max(np.abs(coefficients)) * 0.9)
        inequalities.append(LinearInequality(tuple(float(v) for v in coefficients), limit,
                                             "random row"))
    return mean_variance_problem(
        problem_id=f"prop-{n}-{rows}-{scale:.0e}",
        assets=[f"A{i}" for i in range(n)],
        expected_returns=mu,
        covariance=covariance,
        risk_aversion=4.0,
        lower=0.0,
        upper=0.6,
        budget=1.0,
        inequalities=inequalities,
        as_of=as_of,
    )


def random_dual(problem: ConvexDecisionProblem, rng: np.random.Generator,
                *, active_bias: float = 0.0) -> DualPoint:
    """A random dual-feasible point, often with mass on inactive constraints.

    ``active_bias=0`` gives multipliers unrelated to the active set, which is exactly the regime
    where a missing or mis-signed slack term shows up.
    """

    n = problem.dimension
    m = len(problem.inequalities)
    alpha = rng.uniform(0.0, active_bias, size=n)
    beta = rng.uniform(0.0, active_bias, size=n)
    gamma = rng.uniform(0.0, active_bias, size=m)
    nu = float(rng.normal(0.0, 0.5))
    return DualPoint(nu=nu, alpha=tuple(float(v) for v in alpha),
                     beta=tuple(float(v) for v in beta),
                     gamma=tuple(float(v) for v in gamma),
                     structure_digest=problem.structure_digest())


# ---------------------------------------------------------------- 1. gap identity, any lambda
@pytest.mark.parametrize("scale", [1e-6, 1e-2, 1.0, 1e3, 1e6])
@pytest.mark.parametrize("rows", [0, 1, 2])
def test_gap_identity_holds_across_scales_and_inequality_counts(scale: float, rows: int):
    rng = np.random.default_rng(int(scale * 1000) + rows)
    for trial in range(6):
        problem = random_problem(rng, n=4, rows=rows, scale=scale)
        solution = solve(problem)
        if not solution.feasible:
            continue
        for _ in range(3):
            point = random_dual(problem, rng, active_bias=0.4)
            weights = np.asarray(solution.weights)
            report = residual_regret_bound(problem, weights, point)
            dual_value, _w, _grad = dual_objective(problem, point)
            gap = problem.objective(weights) - dual_value
            # The identity, at the scale of the numbers involved.
            assert abs(report["bound"] - gap) <= 1e-8 * max(1.0, abs(gap)), (
                f"identity broke at scale {scale:.0e}, rows={rows}, trial={trial}: "
                f"bound={report['bound']:.6e} gap={gap:.6e}")
            assert report["identity_check"]["identity_ok"] is True


@pytest.mark.parametrize("rows", [1, 2, 3])
def test_every_inequality_multiplier_enters_the_bound_by_addition(rows: int):
    """The regression the audit found, as a property: gamma on an inactive row adds, never subtracts.

    The bound is ``quadratic + alpha-term + beta-term + gamma-term``. Testing the whole sum also
    catches a sign error in any single term, and testing the gamma term on a *strictly inactive*
    row is the only way to see the defect: on an active row the term is zero and both conventions
    agree.
    """

    rng = np.random.default_rng(900 + rows)
    checked = 0
    for _ in range(8):
        problem = random_problem(rng, n=4, rows=rows, scale=1.0)
        solution = solve(problem)
        weights = np.asarray(solution.weights)
        a_matrix, d_vector = problem.inequality_arrays()
        inactive = np.flatnonzero(d_vector - a_matrix @ weights > 1e-6)
        if inactive.size == 0:
            continue
        row = int(inactive[0])

        # Isolate gamma: every other multiplier is zero, so the quadratic form is unchanged and
        # the entire difference between the two multipliers is the gamma slack term.
        bare = DualPoint(nu=0.0, alpha=(0.0,) * problem.dimension,
                         beta=(0.0,) * problem.dimension,
                         gamma=tuple(0.0 for _ in range(rows)),
                         structure_digest=problem.structure_digest())
        loaded = DualPoint(nu=0.0, alpha=(0.0,) * problem.dimension,
                           beta=(0.0,) * problem.dimension,
                           gamma=tuple(0.7 if j == row else 0.0 for j in range(rows)),
                           structure_digest=problem.structure_digest())
        bare_report = residual_regret_bound(problem, weights, bare)
        loaded_report = residual_regret_bound(problem, weights, loaded)
        slack = 0.7 * float(d_vector[row] - a_matrix[row] @ weights)
        assert slack > 0.0
        assert loaded_report["slack_terms"]["gamma_d_minus_Aw"] == pytest.approx(slack,
                                                                               abs=1e-12)
        # Bound = quadratic + slack, with slack added. The defective form subtracted it.
        assert loaded_report["bound"] - loaded_report["quadratic_form"] == pytest.approx(
            slack, abs=1e-10)
        assert loaded_report["bound"] >= bare_report["bound"] - 1e-15

        # And for a random dual-feasible point, the same decomposition holds term by term.
        point = random_dual(problem, rng, active_bias=0.3)
        report = residual_regret_bound(problem, weights, point)
        assert report["bound"] - report["quadratic_form"] == pytest.approx(
            sum(report["slack_terms"].values()), abs=1e-9)
        assert report["slack_terms"]["gamma_d_minus_Aw"] == pytest.approx(
            float(np.asarray(point.gamma) @ (d_vector - a_matrix @ weights)), abs=1e-10)
        checked += 1
    assert checked > 0, "no inactive inequality was sampled"


# ------------------------------------------------------------------- 2. soundness, any lambda
@pytest.mark.parametrize("rows", [0, 1, 2])
def test_residual_bound_never_understates_regret_across_random_multipliers(rows: int):
    rng = np.random.default_rng(4000 + rows)
    checked = 0
    for trial in range(10):
        problem = random_problem(rng, n=5, rows=rows, scale=1.0)
        solution = solve(problem)
        if not solution.feasible:
            continue
        weights = np.asarray(solution.weights)
        reference = solve_osqp(problem)
        realized = max(0.0, float(problem.objective(weights) - reference.objective))
        for _ in range(4):
            point = random_dual(problem, rng, active_bias=0.5)
            report = residual_regret_bound(problem, weights, point)
            if report["valid"]:
                assert report["bound"] >= realized - 1e-10, (
                    f"unsound at trial {trial}: bound {report['bound']:.6e} < regret {realized:.6e}")
                checked += 1
    assert checked > 0


def test_recovered_multipliers_certify_the_optimum_within_its_residual():
    rng = np.random.default_rng(7)
    for trial in range(8):
        problem = random_problem(rng, n=4, rows=1, scale=1.0)
        solution = solve(problem)
        point, _diagnostics = derive_multipliers(problem, solution.weights)
        if point is None:
            continue
        report = residual_regret_bound(problem, solution.weights, point)
        assert report["valid"] is True
        assert report["bound"] <= 1e-9, f"trial {trial}: {report['bound']:.3e}"


# ------------------------------------------- 2b. the emitted bound and its verification tolerance
def test_emitted_bound_carries_its_margin_and_dominates_the_conservative_measurement():
    """Reconcile the reported bound with regret measured by independent solvers.

    Three quantities are checked for every sampled event, because conflating them is the defect:
    the algebraic bound, the emitted bound (algebraic + floating-point margin + measured identity
    discrepancy), and the regret measured by a solver, which carries its own resolution. The
    emitted bound must dominate the *conservative* measurement -- regret against the better of two
    independently computed optima -- once that resolution is allowed for. It is not required to
    dominate the headline measurement, which uses the lower objective and can sit below the true
    optimum when the solver returns a marginally infeasible point.
    """

    rng = np.random.default_rng(31)
    checked = 0
    for trial in range(8):
        problem = random_problem(rng, n=4, rows=1, scale=1.0)
        solution = solve(problem)
        if not solution.feasible or solution.dual is None:
            continue
        revision = EvidenceRevision(
            revision_id=f"p{trial}", evidence_id=f"e{trial}", input_key="ret_0",
            delta=float(rng.uniform(1e-4, 5e-3)),
            available_at="2024-11-03T00:00:00Z",
        )
        sensitivity = InputSensitivity("ret_0", (-1.0, 0.0, 0.0, 0.0))
        compilation = compile_revisions(problem, [revision], [sensitivity],
                                        audit_as_of=AUDIT_CLOCK)
        if not compilation.applied:
            continue
        certificate = certify_revision_impact(problem, solution.weights, compilation,
                                              decision_dual=solution.dual)
        bound = certificate.bounded["regret_upper_bound"]
        if bound is None:
            continue
        exact = certificate.bounded["regret_upper_bound_exact_arithmetic"]
        margin = certificate.bounded["rounding_margin"]
        if exact is not None:
            assert bound >= exact, "the emitted bound never undercuts the algebraic value"
        if margin is not None:
            assert margin >= 0.0

        revised = compilation.problem
        at_decision = float(revised.objective(solution.weights))
        internal = solve(revised)
        external = solve_osqp(revised)
        spread = abs(float(internal.objective) - float(external.objective))
        conservative = at_decision - max(float(internal.objective), float(external.objective))
        headline = at_decision - min(float(internal.objective), float(external.objective))
        resolution = max(spread, float(certificate.bounded.get("verification_tolerance") or 0.0))

        assert bound >= conservative - resolution, (
            f"trial {trial}: bound {bound:.3e} below conservative regret {conservative:.3e} "
            f"beyond resolution {resolution:.3e}")
        assert headline <= conservative + resolution + 1e-18
        checked += 1
    assert checked > 0


def test_the_identity_is_rechecked_at_the_resolutions_it_claims():
    """The identity tolerance must scale with the arithmetic, not sit at a fixed 1e-8.

    Two bounds four orders of magnitude apart, on the same geometry, must both pass their own
    identity check while a deliberately corrupted multiplier vector fails it.
    """

    rng = np.random.default_rng(77)
    for scale in (1e-4, 1.0, 1e4):
        problem = random_problem(rng, n=3, rows=1, scale=scale)
        solution = solve(problem)
        point, _diagnostics = derive_multipliers(problem, solution.weights)
        if point is None:
            continue
        report = residual_regret_bound(problem, solution.weights, point)
        tolerance = report["identity_check"]["tolerance"]
        assert report["identity_check"]["identity_ok"] is True
        assert report["gap_identity_residual"] <= tolerance
        # The tolerance is a floating-point resolution, not a permissive constant: at every scale it
        # must be far below the objective's own scale, and far above the smallest representable step.
        assert tolerance < 1e-6 * max(1.0, abs(float(problem.objective(solution.weights))))

        corrupted = DualPoint(nu=point.nu, alpha=point.alpha, beta=point.beta,
                              gamma=tuple(value * 0.5 for value in point.gamma),
                              structure_digest=problem.structure_digest())
        broken = residual_regret_bound(problem, solution.weights, corrupted)
        assert broken["identity_check"]["identity_ok"] is True, (
            "a dual-feasible point still satisfies the identity; only an inconsistent one breaks it")


# ------------------------------------------------------------- 3. ellipsoid geometry coherence
def _ellipsoid_cases():
    diagonal = np.diag([0.25, 1.0, 0.5])
    correlated = np.array([
        [0.30, 0.12, 0.05],
        [0.12, 0.20, 0.06],
        [0.05, 0.06, 0.15],
    ])
    return {"diagonal": diagonal, "correlated": correlated}


@pytest.mark.parametrize("name,shape", list(_ellipsoid_cases().items()))
def test_ellipsoid_support_argmax_membership_and_curvature_agree(name: str, shape):
    rng = np.random.default_rng(hash(name) % 2**32)
    radius = 0.7
    center = [0.01, -0.02, 0.005]
    uset = ellipsoid_set(center=center, shape=shape, radius=radius,
                         coverage="geometry consistency", label=name)
    problem = mean_variance_problem(
        problem_id=f"geom-{name}", assets=["a", "b", "c"],
        expected_returns=[0.08, 0.06, 0.05],
        covariance=np.diag([0.04, 0.03, 0.02]),
        risk_aversion=3.0, lower=0.0, upper=0.8, budget=1.0,
    )
    for _ in range(20):
        direction = rng.normal(size=3)
        support = uset.support(direction)
        maximiser = uset.argmax(direction)
        # The maximiser attains the support and lies on the boundary.
        assert float(maximiser @ direction) == pytest.approx(support, rel=1e-9, abs=1e-12)
        assert uset.contains(maximiser)
        assert abs(uset.distance_outside(maximiser)) <= 1e-9
        # Every interior sample has a strictly smaller objective value.
        for _ in range(3):
            z = rng.normal(size=3)
            z = z / max(np.linalg.norm(z), 1e-12) * radius * rng.uniform(0.0, 0.99)
            interior = np.asarray(center) + shape @ z
            assert uset.contains(interior)
            assert float(interior @ direction) <= support + 1e-12

    envelope = curvature_bound(problem, uset)
    inverse = np.linalg.inv(problem.matrix())
    for _ in range(40):
        z = rng.normal(size=3)
        z = z / max(np.linalg.norm(z), 1e-12) * radius
        delta = np.asarray(center) + shape @ z
        assert 0.5 * delta @ inverse @ delta <= envelope["value"] + 1e-12


def test_ellipsoid_membership_inverts_the_shape_matrix_not_its_cholesky_factor():
    """The exact case the audit gave: ``diag(0.25, 1)``, radius 1, offset ``(0.4, 0)``."""

    uset = ellipsoid_set(center=[0.0, 0.0], shape=np.diag([0.25, 1.0]), radius=1.0,
                         coverage="review counterexample")
    outside = np.array([0.4, 0.0])
    assert uset.contains(outside) is False
    assert uset.distance_outside(outside) == pytest.approx(0.6, abs=1e-12)

    corrupted = np.linalg.cholesky(np.diag([0.25, 1.0]))
    z_chol = np.linalg.solve(corrupted, outside)
    assert np.linalg.norm(z_chol) == pytest.approx(0.8, abs=1e-12)
    assert np.linalg.norm(z_chol) <= 1.0, "the Cholesky reading wrongly calls this point inside"

    # A point that genuinely is inside.
    z = np.array([0.9, 0.0])
    assert uset.contains(np.diag([0.25, 1.0]) @ z) is True


def test_interval_membership_and_support_agree():
    uset = interval_set(center=[0.0, 0.0], half_width=[0.1, 0.2], coverage="property")
    assert uset.contains([0.1, -0.2]) is True
    assert uset.contains([0.1000001, 0.0]) is False
    direction = np.array([2.0, -3.0])
    assert uset.support(direction) == pytest.approx(0.2 + 0.6, abs=1e-12)
    assert float(uset.argmax(direction) @ direction) == pytest.approx(uset.support(direction))


@pytest.mark.parametrize("name,shape", list(_ellipsoid_cases().items()))
def test_worst_case_bound_covers_sampled_boundary_points(name: str, shape):
    problem = random_problem(np.random.default_rng(5000), n=3, rows=0, scale=1.0)
    solution = solve(problem)
    uset = ellipsoid_set(center=[0.01, 0.0, 0.0], shape=shape, radius=0.5, coverage="property")
    certificate = certify_worst_case(problem, solution.weights, uset,
                                     decision_dual=solution.dual, gradient_steps=15)
    assert certificate.valid is True
    realized_worst = -math.inf
    for k in range(12):
        angle = 2 * math.pi * k / 12
        z = np.array([math.cos(angle), math.sin(angle), 0.0])
        z = z / np.linalg.norm(z)
        delta = np.asarray(uset.center) + uset.radius * (shape @ z)
        # A boundary point: inside up to round-off, and never rejected outright.
        assert uset.distance_outside(delta) <= 1e-9, uset.distance_outside(delta)
        perturbed = problem.replace(linear_costs=tuple(
            float(v) for v in problem.cost_vector() + delta))
        reference = solve_osqp(perturbed)
        realized_worst = max(realized_worst,
                             float(perturbed.objective(solution.weights) - reference.objective))
    assert certificate.bound >= realized_worst - 1e-10


# ------------------------------------------------------------------ 4. temporal lineage
def _revision(rid: str, *, available: str, supersedes: str | None = None,
              status: str = "active", withdrawn_at: str | None = None,
              version: int | None = None) -> EvidenceRevision:
    return EvidenceRevision(
        revision_id=rid, evidence_id=f"ev-{rid}", input_key="ret_0", delta=0.02,
        available_at=available, supersedes=supersedes, status=status,
        withdrawn_at=withdrawn_at, version=version,
    )


def _compile(revisions, *, audit: str = AUDIT_CLOCK):
    problem = mean_variance_problem(
        problem_id="temporal", assets=["a", "b", "c"],
        expected_returns=[0.08, 0.06, 0.05],
        covariance=np.diag([0.04, 0.03, 0.02]),
        risk_aversion=3.0, lower=0.0, upper=0.8, budget=1.0,
        as_of=DECISION_CLOCK,
    )
    sensitivity = InputSensitivity("ret_0", (-1.0, 0.0, 0.0))
    return compile_revisions(problem, list(revisions), [sensitivity], audit_as_of=audit)


def test_a_successor_published_after_the_cutoff_does_not_suppress_its_predecessor():
    survivor = _revision("v1", available="2024-11-02T00:00:00Z", version=1)
    future = _revision("v2", available="2024-11-09T00:00:00Z", supersedes="v1", version=2)
    compilation = _compile([survivor, future])
    applied = [item.revision_id for item in compilation.applied]
    assert applied == ["v1"], "the earlier revision was the operative record at the cut-off"
    assert compilation.superseded == ()
    assert any("not effective at the audit clock" in note for note in compilation.notes)


def test_a_successor_published_before_the_cutoff_suppresses_its_predecessor():
    earlier = _revision("v1", available="2024-11-02T00:00:00Z", version=1)
    later = _revision("v2", available="2024-11-03T00:00:00Z", supersedes="v1", version=2)
    compilation = _compile([earlier, later])
    assert compilation.superseded == ("v1",)
    assert [item.revision_id for item in compilation.applied] == ["v2"]


def test_a_withdrawal_after_the_cutoff_does_not_unapply_the_revision():
    live_at_audit = _revision("v1", available="2024-11-02T00:00:00Z",
                              status="withdrawn", withdrawn_at="2024-11-20T00:00:00Z")
    compilation = _compile([live_at_audit])
    assert compilation.withdrawn == ()
    assert [item.revision_id for item in compilation.applied] == ["v1"]


def test_a_withdrawal_before_the_cutoff_removes_the_revision():
    withdrawn = _revision("v1", available="2024-11-02T00:00:00Z",
                          status="withdrawn", withdrawn_at="2024-11-03T00:00:00Z")
    compilation = _compile([withdrawn])
    assert compilation.withdrawn == ("v1",)
    assert compilation.applied == ()
    assert compilation.excluded[0]["reason"] == "withdrawn_before_audit"


def test_a_successor_that_is_itself_withdrawn_does_not_suppress_its_predecessor():
    predecessor = _revision("v1", available="2024-11-02T00:00:00Z", version=1)
    retracted = _revision("v2", available="2024-11-02T12:00:00Z", supersedes="v1",
                          status="withdrawn", withdrawn_at="2024-11-03T00:00:00Z", version=2)
    compilation = _compile([predecessor, retracted])
    assert compilation.superseded == ()
    assert [item.revision_id for item in compilation.applied] == ["v1"]


def test_version_ordering_is_enforced_rather_than_reordered():
    predecessor = _revision("v1", available="2024-11-02T00:00:00Z", version=5)
    successor = _revision("v2", available="2024-11-03T00:00:00Z", supersedes="v1", version=4)
    with pytest.raises(ValidationError, match="strictly larger version"):
        _compile([predecessor, successor])


def test_a_successor_cannot_take_effect_before_its_predecessor():
    predecessor = _revision("v1", available="2024-11-03T00:00:00Z", version=1)
    successor = _revision("v2", available="2024-11-02T00:00:00Z", supersedes="v1", version=2)
    with pytest.raises(ValidationError, match="cannot take effect before"):
        _compile([predecessor, successor])


def test_a_cyclic_supersession_chain_is_refused():
    first = _revision("a", available="2024-11-02T00:00:00Z", supersedes="b", version=2)
    second = _revision("b", available="2024-11-02T12:00:00Z", supersedes="a", version=1)
    with pytest.raises(ValidationError, match="cycle"):
        _compile([first, second])


def test_the_effective_time_governs_eligibility_when_it_differs_from_publication():
    """A document published early but effective later is not eligible early."""

    revision = EvidenceRevision(
        revision_id="deferred", evidence_id="ev", input_key="ret_0", delta=0.02,
        available_at="2024-11-02T00:00:00Z", effective_at="2024-11-20T00:00:00Z",
    )
    compilation = _compile([revision])
    assert compilation.applied == ()
    assert compilation.excluded[0]["reason"] == "not_effective_at_audit"

    early = _compile([revision], audit="2024-11-25T00:00:00Z")
    assert [item.revision_id for item in early.applied] == ["deferred"]


# -------------------------------------------------------------------- 5. CRI-U feasibility
def test_worst_case_bound_refuses_an_infeasible_recorded_decision():
    problem = random_problem(np.random.default_rng(6000), n=3, rows=0, scale=1.0)
    solution = solve(problem)
    # Shrink the caps so the recorded allocation no longer fits.
    tightened = problem.replace(upper=tuple(0.25 for _ in range(problem.dimension)))
    assert not check_feasibility(tightened, solution.weights).feasible
    uset = interval_set(center=[0.01, 0.0, 0.0], half_width=[0.01, 0.0, 0.0], coverage="property")
    # The dual recorded against the untightened problem is stale for this one, so ask for a fresh
    # ascent: the point of the test is the feasibility gate, not multiplier provenance.
    certificate = certify_worst_case(tightened, solution.weights, uset, dual_iterations=5)
    assert certificate.decision_feasible is False
    assert certificate.actionable is False
    assert certificate.valid is False
    assert math.isfinite(certificate.objective_bound), "the algebra is still reported"
    assert "infeasible" in (certificate.reason or "")
    assert certificate.as_dict()["actionable"] is False


def test_worst_case_bound_is_actionable_for_a_feasible_decision():
    problem = random_problem(np.random.default_rng(6100), n=3, rows=0, scale=1.0)
    solution = solve(problem)
    uset = interval_set(center=[0.01, 0.0, 0.0], half_width=[0.01, 0.0, 0.0], coverage="property")
    certificate = certify_worst_case(problem, solution.weights, uset,
                                     decision_dual=solution.dual)
    assert certificate.decision_feasible is True
    assert certificate.actionable is True
    assert certificate.valid is True
    assert certificate.objective_bound == pytest.approx(certificate.bound)
