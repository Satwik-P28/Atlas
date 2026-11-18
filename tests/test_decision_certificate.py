"""Verification of revision compilation, certificates and the second-domain adapter.

The central test is soundness: across many random revisions the certified regret bound must
never fall below the realized regret, and a zero-regret certificate must coincide with a
genuinely zero realized regret. Soundness is checked against an independent re-solve, not
against the certificate machinery itself.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy", reason="the decision research layer requires the optimization extra")

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.decision.certificate import (
    certify_revision_impact,
    degeneracy_report,
    regret_tolerance_radius,
    stability_radius,
)
from atlas.decision.inventory import (
    CapacityLine,
    capacity_allocation_problem,
    capacity_report,
    solve_capacity_allocation,
)
from atlas.decision.problem import LinearInequality, mean_variance_problem
from atlas.decision.qp import derive_multipliers, solve, verify_kkt
from atlas.decision.revision import (
    EvidenceRevision,
    InputSensitivity,
    compile_revisions,
    directional_perturbation,
    parse_instant,
)

DECISION_CLOCK = "2024-11-01T21:00:00Z"
#: The audit is run four days after the decision. Revisions public in between are the ones an
#: audit exists to evaluate.
AUDIT_CLOCK = "2024-11-05T12:00:00Z"


def problem(seed: int = 3, *, n: int = 5, upper: float = 0.5):
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(n, n))
    sigma = a @ a.T / n * 0.04 + np.eye(n) * 0.01
    mu = rng.normal(0.08, 0.02, size=n)
    return mean_variance_problem(
        problem_id=f"cert-{seed}",
        assets=[f"A{i}" for i in range(n)],
        expected_returns=mu,
        covariance=sigma,
        risk_aversion=4.0,
        lower=0.0,
        upper=upper,
        budget=1.0,
        as_of=DECISION_CLOCK,
    )


def sensitivity_for(index: int, n: int = 5) -> InputSensitivity:
    effect = [0.0] * n
    effect[index] = -1.0  # an upward revision of the expected return lowers the cost
    return InputSensitivity(f"ret_{index}", tuple(effect))


def revision(index: int, delta: float, available_at: str = "2024-11-02T22:00:00Z") -> EvidenceRevision:
    return EvidenceRevision(
        revision_id=f"r{index}-{delta}",
        evidence_id=f"ev{index}",
        input_key=f"ret_{index}",
        delta=delta,
        available_at=available_at,
        source_id="10-Q/A",
    )


def compile_audited(base, revisions, sensitivities, **kwargs):
    """Compile with an explicit audit clock: the ordinary revision-audit configuration."""
    kwargs.setdefault("audit_as_of", AUDIT_CLOCK)
    return compile_revisions(base, revisions, sensitivities, **kwargs)


# ------------------------------------------------------------------------- instants
def test_instants_are_normalised_to_utc_and_offsets_are_respected():
    assert parse_instant("2024-11-01T21:00:00Z") == parse_instant("2024-11-01T21:00:00+00:00")
    # 19:30 Eastern daylight time is 23:30 UTC, later than 21:00 UTC.
    eastern = parse_instant("2024-11-01T19:30:00-04:00")
    assert eastern == parse_instant("2024-11-01T23:30:00Z")
    assert eastern > parse_instant(DECISION_CLOCK)
    assert parse_instant("2024-11-01T21:00:00") == parse_instant("2024-11-01T21:00:00Z")


def test_invalid_instant_is_rejected_but_an_absent_instant_is_not_an_error():
    with pytest.raises(ValidationError):
        parse_instant("not-a-date")
    # Optional provenance fields are allowed to be absent; absence is reported upstream as
    # "no_decision_clock" rather than raised here.
    assert parse_instant(None) is None


# ------------------------------------------------------------------------ compilation
def test_revision_after_the_decision_clock_is_excluded_with_a_reason():
    base = problem()
    compilation = compile_revisions(
        base, [revision(0, 0.05, available_at="2024-11-05T22:00:00Z")], [sensitivity_for(0)]
    )
    assert compilation.status == "no_material_change"
    assert compilation.applied == ()
    assert compilation.excluded[0]["reason"] == "not_available_at_decision"
    assert compilation.problem.digest() == base.digest()


def test_revision_between_the_clocks_is_applied():
    base = problem()
    compilation = compile_audited(base, [revision(0, 0.05)], [sensitivity_for(0)])
    assert compilation.status == "applied"
    assert len(compilation.applied) == 1
    assert compilation.delta_cost[0] == pytest.approx(-0.05)
    assert compilation.problem.linear_costs[0] == pytest.approx(base.linear_costs[0] - 0.05)
    assert compilation.problem.digest() != base.digest()
    assert compilation.lineage[0]["category"] == "published_after_decision"


def test_revision_before_the_decision_clock_is_not_applied_again():
    """A correction already public when the decision was taken is inside the base vintage.

    Eligibility by timestamp is not the same as novelty: applying it again would double count
    the correction, which is the defect the PR review found.
    """

    base = problem()
    stale = revision(0, 0.05, available_at="2024-10-30T22:00:00Z")
    compilation = compile_audited(base, [stale], [sensitivity_for(0)])
    assert compilation.status == "no_material_change"
    assert compilation.applied == ()
    assert compilation.incorporated == (stale.revision_id,)
    assert compilation.excluded[0]["reason"] == "already_incorporated_in_decision_vintage"
    assert compilation.lineage[0]["category"] == "incorporated_before_decision"
    assert compilation.problem.digest() == base.digest()
    assert compilation.as_dict()["lineage"]


def test_pre_decision_revision_can_be_included_only_by_explicit_opt_in():
    """"The model missed evidence that was already public" is a different question, and named."""

    base = problem()
    compilation = compile_audited(
        base, [revision(0, 0.05, available_at="2024-10-30T22:00:00Z")], [sensitivity_for(0)],
        include_pre_decision=True,
    )
    assert compilation.status == "applied"
    assert compilation.lineage[0]["category"] == "pre_decision_explicitly_included"


def test_revision_exactly_at_the_clock_is_treated_as_incorporated():
    base = problem()
    compilation = compile_audited(
        base, [revision(0, 0.01, available_at=DECISION_CLOCK)], [sensitivity_for(0)]
    )
    assert compilation.status == "no_material_change"
    assert compilation.excluded[0]["reason"] == "already_incorporated_in_decision_vintage"


def test_withdrawn_and_superseded_revisions_are_excluded_with_reasons():
    base = problem()
    withdrawn = EvidenceRevision("w1", "ev-w", "ret_0", 0.05, "2024-11-02T22:00:00Z",
                                status="withdrawn")
    first = EvidenceRevision("s1", "ev-s1", "ret_1", 0.03, "2024-11-02T22:00:00Z")
    second = EvidenceRevision("s2", "ev-s2", "ret_1", 0.04, "2024-11-03T22:00:00Z",
                              supersedes="s1")
    sensitivities = [sensitivity_for(0), sensitivity_for(1)]
    compilation = compile_audited(base, [withdrawn], sensitivities)
    assert compilation.withdrawn == ("w1",)
    assert compilation.excluded[0]["reason"] == "withdrawn_before_audit"
    assert compilation.status == "no_material_change"

    compilation = compile_audited(base, [first, second], sensitivities)
    assert compilation.superseded == ("s1",)
    assert [item.revision_id for item in compilation.applied] == ["s2"]
    assert compilation.delta_cost[1] == pytest.approx(-0.04)
    reasons = {item["revision_id"]: item["reason"] for item in compilation.excluded}
    assert reasons["s1"] == "superseded_before_audit"


def test_lineage_categories_cover_every_supplied_revision():
    base = problem()
    revisions = [
        revision(0, 0.02, available_at="2024-10-30T22:00:00Z"),
        revision(1, 0.02, available_at="2024-11-02T22:00:00Z"),
        revision(2, 0.02, available_at="2024-12-02T22:00:00Z"),
        EvidenceRevision("unmapped", "ev-x", "unknown_input", 0.1, "2024-11-02T22:00:00Z"),
    ]
    compilation = compile_audited(base, revisions, [sensitivity_for(0), sensitivity_for(1),
                                                    sensitivity_for(2)])
    assert len(compilation.lineage) == len(revisions)
    categories = {item["revision_id"]: item["category"] for item in compilation.lineage}
    assert set(categories.values()) == {
        "incorporated_before_decision", "published_after_decision", "published_after_audit",
        "unmapped",
    }


def test_unsupported_perturbation_kind_is_refused_not_ignored():
    base = problem()
    covariance_revision = EvidenceRevision(
        revision_id="rv", evidence_id="ev", input_key="covariance", delta=0.2,
        available_at="2024-10-30T00:00:00Z", kind="risk_matrix",
    )
    compilation = compile_audited(base, [covariance_revision], [sensitivity_for(0)])
    assert compilation.status == "no_material_change"
    assert compilation.excluded[0]["reason"] == "unsupported_perturbation_kind"


def test_missing_sensitivity_is_excluded():
    compilation = compile_audited(problem(), [revision(0, 0.05)], [])
    assert compilation.excluded[0]["reason"] == "no_declared_sensitivity"


def test_problem_without_a_clock_cannot_be_audited():
    base = problem().replace(as_of=None)
    compilation = compile_audited(base, [revision(0, 0.05)], [sensitivity_for(0)])
    assert compilation.status == "no_decision_clock"
    assert "cannot be established" in compilation.notes[0]


def test_hindsight_mode_is_labelled_and_contaminates_the_program():
    base = problem()
    future = revision(0, 0.05, available_at="2024-11-05T22:00:00Z")
    compilation = compile_audited(base, [future], [sensitivity_for(0)], allow_future=True)
    assert compilation.hindsight is True
    assert compilation.status == "applied"
    assert any("HINDSIGHT" in note for note in compilation.notes)


def test_audit_clock_applies_revisions_that_became_public_after_the_decision():
    """The ordinary audit case: the decision is frozen, the evidence is not."""

    base = problem()
    future = revision(0, 0.01, available_at="2024-11-05T22:00:00Z")
    compilation = compile_audited(base, [future], [sensitivity_for(0)],
                                    audit_as_of="2024-11-06T00:00:00Z")
    assert compilation.status == "applied"
    assert compilation.post_decision_revision_ids == (future.revision_id,)
    decision = solve(base)
    certificate = certify_revision_impact(base, decision.weights, compilation,
                                          decision_dual=decision.dual)
    assert certificate.temporal_relationship == "revision_available_after_decision"


def test_revision_after_the_audit_clock_is_still_excluded():
    base = problem()
    later = revision(0, 0.01, available_at="2024-11-10T00:00:00Z")
    compilation = compile_audited(base, [later], [sensitivity_for(0)],
                                    audit_as_of="2024-11-06T00:00:00Z")
    assert compilation.status == "no_material_change"
    assert compilation.excluded[0]["reason"] == "not_available_at_audit"


def test_audit_clock_cannot_precede_the_decision_clock():
    with pytest.raises(ValidationError):
        compile_audited(problem(), [], [], audit_as_of="2024-01-01T00:00:00Z")


def test_without_a_revision_the_program_is_unchanged():
    compilation = compile_audited(problem(), [], [])
    assert compilation.status == "no_material_change"
    assert compilation.magnitude == 0.0


# ------------------------------------------------------------------------ certificates
def test_exact_certificate_reports_a_residual_bound_not_an_exact_zero():
    """A tolerance-satisfied KKT test licenses a numerical statement, not ``0.0``.

    The certificate must report the validated residual bound and the residuals behind it. An
    exact zero would be a claim the arithmetic does not support, and it would silently discard
    the only quantity that makes the verdict checkable.
    """

    base = problem()
    solution = solve(base)
    compilation = compile_audited(base, [revision(0, 1e-9)], [sensitivity_for(0)])
    certificate = certify_revision_impact(base, solution.weights, compilation,
                                          decision_dual=solution.dual)
    reference = solve(compilation.problem)
    realized = max(0.0, compilation.problem.objective(solution.weights) - reference.objective)
    assert certificate.zero_regret
    assert certificate.verdict == "zero_regret_within_residual"
    bound = certificate.bounded["regret_upper_bound"]
    assert bound is not None
    assert 0.0 < bound < 1e-12, "the bound must be the computed residual, not a literal zero"
    assert bound >= realized - 1e-15, "and it must still be sound"
    assert certificate.exact["numerical_regret_bound"] is not None
    residuals = certificate.bounded["residual_kkt_residuals"]
    assert residuals["stationarity"] >= 0.0
    assert residuals["gap_identity_residual"] is not None


def test_bound_never_understates_realized_regret_across_random_revisions():
    """The core soundness property, checked against an independent re-solve."""

    checked = 0
    for seed in (11, 12, 13):
        base = problem(seed)
        solution = solve(base)
        rng = np.random.default_rng(seed)
        for trial in range(40):
            index = int(rng.integers(0, base.dimension))
            magnitude = float(rng.uniform(1e-4, 0.05))
            compilation = compile_audited(base, [revision(index, magnitude)],
                                            [sensitivity_for(index, base.dimension)])
            certificate = certify_revision_impact(base, solution.weights, compilation,
                                                 decision_dual=solution.dual)
            reference = solve(compilation.problem)
            realized = compilation.problem.objective(solution.weights) - reference.objective
            assert realized >= -1e-12
            if certificate.zero_regret:
                assert realized < 1e-6, "a zero-regret certificate must mean zero regret"
            bound = certificate.bounded["regret_upper_bound"]
            assert bound is not None
            assert bound + 1e-12 >= realized, (
                f"bound {bound} understated realized regret {realized} "
                f"(seed={seed} trial={trial})"
            )
            checked += 1
    assert checked == 120


def test_certificate_reports_tightness_against_the_reference():
    base = problem(21)
    solution = solve(base)
    compilation = compile_audited(base, [revision(2, 0.03)], [sensitivity_for(2)])
    reference = solve(compilation.problem)
    certificate = certify_revision_impact(base, solution.weights, compilation,
                                          decision_dual=solution.dual,
                                          reference_solution=reference)
    reference_block = certificate.reference
    assert reference_block["realized_regret"] >= 0
    assert reference_block["bound_over_realized_regret"] >= 1.0
    assert reference_block["bound_understates"] is False
    assert reference_block["weights_changed"] in (True, False)


def test_reference_requires_no_revision_to_change_the_allocation():
    """A tiny, correctly signed revision leaves the box-constrained allocation unchanged."""

    base = problem(5, upper=0.4)
    solution = solve(base)
    compilation = compile_audited(base, [revision(0, 1e-12)], [sensitivity_for(0)])
    reference = solve(compilation.problem)
    assert np.max(np.abs(np.asarray(reference.weights) - np.asarray(solution.weights))) < 1e-6


def test_infeasible_revision_verdict_is_explicit():
    base = problem()
    solution = solve(base)
    # A revision that changes the budget would be a different program; here the feasible set
    # changes only through a tightened box, so the recorded weights can become infeasible.
    tightened = base.replace(lower=(0.3, 0.0, 0.0, 0.0, 0.0))
    compilation = compile_audited(tightened, [], [])
    certificate = certify_revision_impact(tightened, solution.weights, compilation,
                                          decision_dual=solution.dual)
    assert certificate.verdict == "infeasible_under_revision"
    assert certificate.exact["kkt"]["satisfied"] is False


def test_guarantee_scope_names_its_conditions():
    base = problem(8)
    solution = solve(base)
    compilation = compile_audited(base, [revision(1, 0.02)], [sensitivity_for(1)])
    certificate = certify_revision_impact(base, solution.weights, compilation,
                                          decision_dual=solution.dual)
    assert "declared linear input sensitivity" in certificate.guarantee_scope
    assert any("conditional" in limitation for limitation in certificate.limitations)
    assert certificate.temporal_relationship == "revision_available_after_decision"


def test_misspecified_sensitivity_can_break_the_bound_and_is_reported_as_a_limitation():
    """The bound is conditional on the declared sensitivity. Violating it is detectable."""

    base = problem(13)
    solution = solve(base)
    declared = 0.005
    actual = 0.05
    compilation = compile_audited(base, [revision(0, declared)], [sensitivity_for(0)])
    certificate = certify_revision_impact(base, solution.weights, compilation,
                                          decision_dual=solution.dual)
    # The program that actually occurred used a ten-times larger revision.
    actual_problem = directional_perturbation(base, [1.0, 0, 0, 0, 0], 0.0).replace(
        linear_costs=tuple(base.linear_costs[i] - (actual if i == 0 else 0.0)
                           for i in range(base.dimension))
    )
    actual_reference = solve(actual_problem)
    actual_regret = actual_problem.objective(solution.weights) - actual_reference.objective
    bound = certificate.bounded["regret_upper_bound"]
    assert actual_regret > bound, "the declared-program bound cannot cover an undeclared revision"
    assert any("conditional" in limitation for limitation in certificate.limitations)


def test_degeneracy_keeps_the_value_certificate_sound_but_breaks_identity_claims():
    """Two identical assets: the optimal *value* is unique, the optimal *weights* are not."""

    base = problem(2, n=3, upper=0.8)
    duplicated = mean_variance_problem(
        problem_id="degenerate",
        assets=["A", "A2", "C"],
        expected_returns=[0.1, 0.1, 0.05],
        covariance=[[0.04, 0.04, 0.0], [0.04, 0.04, 0.0], [0.0, 0.0, 0.02]],
        risk_aversion=4.0, lower=0.0, upper=0.8, budget=1.0, as_of=DECISION_CLOCK,
    )
    report = degeneracy_report(duplicated)
    assert report["rank_deficient"]
    assert report["weight_identifiability"] == "non_unique"
    solution = solve(duplicated)
    assert solution.certified_optimal
    # A different split between the two identical assets has the same objective.
    twin = np.asarray(solution.weights).copy()
    shift = min(twin[0], 0.8 - twin[1], 0.05)
    twin[0] -= shift
    twin[1] += shift
    assert duplicated.objective(twin) == pytest.approx(duplicated.objective(solution.weights), abs=1e-12)
    assert abs(twin[0] - solution.weights[0]) > 1e-3


# ----------------------------------------------------------------------------- radius
def test_regret_is_convex_along_a_linear_ray():
    """Convexity is what licenses bisection for the tolerance radius."""

    base = problem(17)
    solution = solve(base)
    direction = np.zeros(base.dimension)
    direction[0] = 1.0
    radii = [0.0, 0.005, 0.01, 0.02, 0.04, 0.08]
    regrets = []
    for radius in radii:
        perturbed = directional_perturbation(base, direction, radius)
        reference = solve(perturbed)
        regrets.append(perturbed.objective(solution.weights) - reference.objective)
    assert regrets[0] == pytest.approx(0.0, abs=1e-12)
    slopes = [(regrets[i + 1] - regrets[i]) / (radii[i + 1] - radii[i]) for i in range(len(radii) - 1)]
    assert all(b >= a - 1e-9 for a, b in zip(slopes, slopes[1:])), slopes


def test_exact_invariance_radius_is_zero_for_an_interior_optimum():
    # Equal means and a one-factor covariance with equal loadings put the optimum at the equal
    # split, strictly inside every bound, so no non-zero perturbation can leave it optimal.
    n = 4
    covariance = 0.04 * (0.5 * np.ones((n, n)) + 0.5 * np.eye(n))
    base = mean_variance_problem(
        problem_id="interior", assets=[f"A{i}" for i in range(n)],
        expected_returns=np.full(n, 0.10), covariance=covariance, risk_aversion=2.0,
        lower=0.0, upper=0.9, budget=1.0, as_of=DECISION_CLOCK,
    )
    solution = solve(base)
    assert np.all(np.asarray(solution.weights) > 0.2)
    direction = np.zeros(n)
    direction[0] = 1.0
    radius = stability_radius(base, solution.weights, direction)
    assert radius.radius == 0.0
    assert any("interior" in note for note in radius.notes)


def test_exact_invariance_radius_is_positive_when_bounds_are_active():
    base = problem(23, upper=0.25)  # four assets at the cap forces an active set
    solution = solve(base)
    weights = np.asarray(solution.weights)
    assert np.sum(np.isclose(weights, 0.25, atol=1e-9)) >= 2
    direction = np.zeros(base.dimension)
    direction[-1] = 1.0  # raise the cost of the marginal asset only
    radius = stability_radius(base, solution.weights, direction, upper_limit=0.5)
    assert radius.radius > 1e-6
    perturbed_inside = directional_perturbation(base, direction, radius.radius * 0.99)
    point, _ = derive_multipliers(perturbed_inside, solution.weights)
    assert verify_kkt(perturbed_inside, solution.weights, point).satisfied


def test_regret_tolerance_radius_brackets_the_threshold():
    base = problem(29)
    solution = solve(base)
    direction = np.zeros(base.dimension)
    # Lowering the cost of the zero-weight asset is what actually moves the optimum; raising it
    # leaves the allocation unchanged and produces a radius at the search limit instead.
    direction[0] = -1.0
    result = regret_tolerance_radius(base, solution.weights, direction, tolerance=0.001,
                                     upper_limit=0.3)
    assert result["bracketed"]
    inside = result["radius"] * 0.95
    outside = result["radius"] * 1.05
    for radius, should_pass in ((inside, True), (outside, False)):
        perturbed = directional_perturbation(base, direction, radius)
        regret = perturbed.objective(solution.weights) - solve(perturbed).objective
        assert (regret <= 0.001) is should_pass


# ------------------------------------------------------------------------ second domain
def capacity_problem():
    lines = [
        CapacityLine("L1", 3.0, 100.0, 0.1),
        CapacityLine("L2", 5.0, 80.0, 0.2),
        CapacityLine("L3", 2.0, 120.0, 0.0),
    ]
    covariance = np.array([[400.0, 120.0, 60.0], [120.0, 300.0, 80.0], [60.0, 80.0, 500.0]])
    return capacity_allocation_problem(
        problem_id="capacity", lines=lines, demand_covariance=covariance, capacity=200.0,
        risk_aversion=0.01, group_cap=([0, 1], 150.0), as_of=DECISION_CLOCK,
    )


def test_capacity_allocation_respects_floors_group_cap_and_capacity():
    problem_instance = capacity_problem()
    solution = solve_capacity_allocation(problem_instance)
    report = capacity_report(problem_instance, solution)
    weights = np.asarray(solution.weights)
    assert solution.certified_optimal
    assert weights.sum() == pytest.approx(200.0, abs=1e-7)
    assert weights[0] >= 10.0 - 1e-9  # 10% of mean demand
    assert weights[1] >= 16.0 - 1e-9  # 20% of mean demand
    assert weights[0] + weights[1] <= 150.0 + 1e-9
    assert report["capacity_used"] == pytest.approx(200.0, abs=1e-7)
    assert "synthetic" in report["limitation"]


def test_capacity_problem_rejects_impossible_floors():
    lines = [CapacityLine("L1", 1.0, 100.0, 0.9)]
    with pytest.raises(ValidationError):
        capacity_allocation_problem(
            problem_id="bad", lines=lines, demand_covariance=[[1.0]], capacity=50.0,
            risk_aversion=1.0,
        )


def test_the_same_certificate_works_on_the_operational_problem():
    problem_instance = capacity_problem()
    solution = solve_capacity_allocation(problem_instance)
    revision = EvidenceRevision(
        revision_id="demand-rev", evidence_id="ev-demand", input_key="margin_L2", delta=-0.5,
        available_at="2024-11-02T12:00:00Z", source_id="demand-forecast-revision",
    )
    sensitivity = InputSensitivity("margin_L2", (0.0, 1.0, 0.0))
    compilation = compile_audited(problem_instance, [revision], [sensitivity])
    certificate = certify_revision_impact(problem_instance, solution.weights, compilation,
                                          decision_dual=solution.dual,
                                          reference_solution=solve_capacity_allocation(compilation.problem))
    assert certificate.temporal_relationship == "revision_available_after_decision"
    assert certificate.bounded["regret_upper_bound"] is not None
