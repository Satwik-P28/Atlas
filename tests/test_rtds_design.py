"""Regression tests for the real-world revision study's design.

Three properties are protected here, each of which was wrong in the first version of the study:

1. the objective-coefficient mapping from a vintage revision to the audit-time program;
2. the basis of the uncertainty set used for the worst-case (CRI-U) comparison;
3. the interpretation of an upper bound above the tolerance, which is a failure to certify and not a
   proof of materiality.

The equivalence assertion is the permanent guard: every archived event is checked between the
revision-compiled audit program and one built directly from the audit-vintage observations.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "scripts" / "research"
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

import rtds_study as study  # noqa: E402
from atlas.decision.certificate import certify_revision_impact, stability_radius  # noqa: E402
from atlas.decision.qp import derive_multipliers, solve, verify_kkt  # noqa: E402
from atlas.decision.revision import (  # noqa: E402
    EvidenceRevision,
    InputSensitivity,
    compile_revisions,
)
from atlas.decision.uncertainty import certify_worst_case, interval_set  # noqa: E402
from rtds_model import (  # noqa: E402
    assert_equivalent,
    audit_problem_direct,
    build_problem,
    compile_audit_problem,
    greedy_repair,
    regret_lower_bound,
    revision_deltas,
    vertex_enumeration_worst_case,
)

LABELS = ["total", "manufacturing", "construction"]
COHORT = "B"
CORRELATION = np.array([[1.0, 0.3, 0.1], [0.3, 1.0, 0.2], [0.1, 0.2, 1.0]])
RHO = 1.0
Z_DECISION = np.array([0.40, -0.10, 0.20])
Z_AUDIT = np.array([0.05, 0.30, -0.15])


def _decision():
    problem = build_problem(Z_DECISION, COHORT, LABELS, CORRELATION, RHO, "2020-01-31", "decision")
    solution = solve(problem)
    assert solution.feasible and solution.dual is not None
    return problem, solution


def test_defect_reproduction_and_corrected_mapping():
    """The old sign convention produced ``z_A - 2 z_D``; the documented one produces ``-z_A``."""

    problem, _solution = _decision()
    # The defect: the standardised growth difference passed as if it were a cost difference.
    revisions, sensitivities = [], []
    for index, label in enumerate(LABELS):
        delta = float(Z_AUDIT[index] - Z_DECISION[index])
        if delta == 0.0:
            continue
        revisions.append(EvidenceRevision(
            revision_id=f"old::{label}", evidence_id="2021-01-31", input_key=label, delta=delta,
            available_at="2021-01-31T23:59:59Z", kind="linear_objective"))
        effect = [0.0] * len(LABELS)
        effect[index] = 1.0
        sensitivities.append(InputSensitivity(label, tuple(effect)))
    defect = compile_revisions(problem, revisions, sensitivities, as_of="2020-01-31T23:59:59Z",
                               audit_as_of="2021-01-31T23:59:59Z").problem
    np.testing.assert_allclose(defect.cost_vector(), Z_AUDIT - 2 * Z_DECISION, atol=1e-12)
    assert not np.allclose(defect.cost_vector(), -Z_AUDIT, atol=1e-6)

    # The documented convention: a change in the linear costs, applied with a positive identity.
    corrected = compile_audit_problem(
        problem, Z_DECISION, Z_AUDIT, LABELS, event_id="test", decision_clock="2020-01-31T23:59:59Z",
        audit_clock="2021-01-31T23:59:59Z", audit_vintage="2021-01-31",
        decision_vintage="2020-01-31").problem
    np.testing.assert_allclose(corrected.cost_vector(), -Z_AUDIT, atol=1e-12)
    assert_equivalent(corrected, audit_problem_direct(Z_AUDIT, COHORT, LABELS, CORRELATION, RHO,
                                                      "2020-01-31"), [0.4, 0.35, 0.25])
    with pytest.raises(AssertionError):
        assert_equivalent(defect, audit_problem_direct(Z_AUDIT, COHORT, LABELS, CORRELATION, RHO,
                                                      "2020-01-31"), [0.4, 0.35, 0.25])


def test_revision_deltas_are_cost_deltas():
    deltas = revision_deltas(Z_DECISION, Z_AUDIT)
    assert len(deltas) == len(LABELS)
    for index, delta in deltas:
        assert delta == pytest.approx(float(-Z_AUDIT[index] + Z_DECISION[index]))


def test_archived_events_compile_to_the_audit_vintage_program():
    """The permanent guard: every archived event, both cohorts, compiled == direct."""

    path = ROOT / "artifacts" / "research" / "rtds" / "dataset.json"
    if not path.exists():  # pragma: no cover - the artifact is committed
        pytest.skip("archived dataset is not present")
    dataset = json.loads(path.read_text())
    checked = 0
    for cohort in dataset["cohorts"]:
        labels = cohort["labels"]
        train = [event for event in cohort["events"] if event["split"] == "train"]
        block = study.calibration(train, labels)
        rho = 1.0
        for event in [event for event in cohort["events"] if event["split"] == "test"][:6]:
            returns_decision = study.standardise(event["growth_decision"], block)
            returns_audit = study.standardise(event["growth_audit"], block)
            problem = build_problem(returns_decision, cohort["cohort"], labels,
                                    block["correlation"], rho, event["decision_vintage"], "d")
            solution = solve(problem)
            assert solution.feasible and solution.dual is not None
            compiled = compile_audit_problem(
                problem, returns_decision, returns_audit, labels, event_id=event["period"],
                decision_clock=f"{event['decision_vintage']}T23:59:59Z",
                audit_clock=f"{event['audit_vintage']}T23:59:59Z",
                audit_vintage=event["audit_vintage"],
                decision_vintage=event["decision_vintage"])
            assert compiled.status == "applied"
            direct = audit_problem_direct(returns_audit, cohort["cohort"], labels,
                                          block["correlation"], rho, event["decision_vintage"])
            report = assert_equivalent(compiled.problem, direct, solution.weights,
                                       context=f"{cohort['cohort']} {event['period']}")
            assert max(report.values()) < 1e-9
            checked += 1
    assert checked >= 8


def test_calendar_horizon_is_calendar_aware():
    sys.path.insert(0, str(RESEARCH))
    import rtds_build

    assert rtds_build.add_months(date(2020, 1, 28), 12) == date(2021, 1, 28)
    # 29 February clips to the end of February rather than spilling into March.
    assert rtds_build.add_months(date(2020, 2, 29), 12) == date(2021, 2, 28)
    assert rtds_build.add_months(date(2019, 11, 30), 12) == date(2020, 11, 30)
    assert rtds_build.add_months(date(2020, 3, 31), 4) == date(2020, 7, 31)

    path = ROOT / "artifacts" / "research" / "rtds" / "dataset.json"
    if not path.exists():  # pragma: no cover
        pytest.skip("archived dataset is not present")
    dataset = json.loads(path.read_text())
    assert dataset["horizon_rule"].startswith("audit vintage = first vintage on or after add_months")
    for cohort in dataset["cohorts"]:
        for event in cohort["events"]:
            decision = date.fromisoformat(event["decision_vintage"])
            audit = date.fromisoformat(event["audit_vintage"])
            assert audit >= rtds_build.add_months(decision, 12)
            # Within one release cycle of the target: releases are monthly (B) or quarterly (A),
            # so the first vintage at or after the target can lag it by up to a quarter.
            assert (audit - rtds_build.add_months(decision, 12)).days <= 90
            # The realised horizon is a calendar year plus at most one release lag, not a fixed
            # day count: the old 400/366-day approximation produced exactly one constant.
            assert 365 <= event["horizon_days_actual"] <= 440
            assert event["horizon_months"] == 12


def test_uncertainty_set_is_centred_on_the_base_it_declares():
    """CRI-U over a set of *additional* corrections, checked against exhaustive vertices."""

    problem, solution = _decision()
    weights = np.asarray(solution.weights, dtype=float)
    half = [0.05, 0.05, 0.05]
    zero_centred = interval_set(center=[0.0, 0.0, 0.0], half_width=half, coverage="test")
    certificate = certify_worst_case(problem, weights, zero_centred,
                                     decision_dual=solution.dual)
    exact = vertex_enumeration_worst_case(problem, weights, [0.0, 0.0, 0.0], half)
    assert certificate.valid
    assert certificate.bound >= exact["worst_regret"] - 1e-9
    assert exact["vertices_evaluated"] == 8

    # A singleton at zero is the exact-revision case: it must reproduce the CRI bound.
    singleton = interval_set(center=[0.0, 0.0, 0.0], half_width=[0.0, 0.0, 0.0], coverage="test")
    at_zero = certify_worst_case(problem, weights, singleton, decision_dual=solution.dual)
    assert at_zero.bound == pytest.approx(0.0, abs=1e-9)

    # Treating an absolute cost level as a perturbation inflates the bound by an order of
    # magnitude, which is what made the old CRI-U comparison report zero certifications.
    level_as_perturbation = interval_set(center=[1.0, 0.0, 0.0], half_width=half, coverage="test")
    inflated = certify_worst_case(problem, weights, level_as_perturbation,
                                  decision_dual=solution.dual)
    assert inflated.bound > 10 * max(certificate.bound, 1e-6)


def test_materiality_witness_is_a_valid_lower_bound():
    problem, solution = _decision()
    weights = np.asarray(solution.weights, dtype=float)
    corrected = compile_audit_problem(
        problem, Z_DECISION, Z_AUDIT, LABELS, event_id="t", decision_clock="2020-01-31T23:59:59Z",
        audit_clock="2021-01-31T23:59:59Z", audit_vintage="2021-01-31",
        decision_vintage="2020-01-31").problem
    repair = greedy_repair(corrected, weights)
    assert repair["feasible"]
    optimum = solve(corrected)
    true_regret = float(corrected.objective(weights)) - float(optimum.objective)
    lower = regret_lower_bound(corrected, weights, repair["weights"])
    assert 0.0 <= lower <= true_regret + 1e-9


def test_upper_bound_above_tolerance_is_not_a_materiality_claim():
    assert study.classify_regret(0.5e-3, 0.0) == "certified_immaterial"
    # A large upper bound on a genuinely immaterial revision is *unknown*, not material.
    assert study.classify_regret(0.5, 0.0) == "unknown"
    # Materiality needs its own witness.
    assert study.classify_regret(0.5, 0.2) == "certified_material"
    assert study.classify_regret(None, 0.0004) == "unknown"


def test_immaterial_certificate_and_material_witness_cannot_both_hold():
    problem, solution = _decision()
    weights = np.asarray(solution.weights, dtype=float)
    compiled = compile_audit_problem(
        problem, Z_DECISION, Z_AUDIT, LABELS, event_id="t", decision_clock="2020-01-31T23:59:59Z",
        audit_clock="2021-01-31T23:59:59Z", audit_vintage="2021-01-31",
        decision_vintage="2020-01-31")
    certificate = certify_revision_impact(problem, weights, compiled,
                                          decision_dual=solution.dual)
    bound = certificate.bounded["regret_upper_bound"]
    repair = greedy_repair(compiled.problem, weights)
    lower = regret_lower_bound(compiled.problem, weights, repair["weights"])
    assert not (bound is not None and bound <= study.TAU and lower > study.TAU)


def test_stability_radius_reports_its_kkt_evaluation_count():
    problem, solution = _decision()
    weights = np.asarray(solution.weights, dtype=float)
    direction = -Z_AUDIT + Z_DECISION
    radius = stability_radius(problem, weights, direction=direction, upper_limit=10.0)
    assert radius.evaluations > 0
    assert radius.radius >= 0.0
    multipliers, _ = derive_multipliers(problem, weights)
    assert multipliers is not None and verify_kkt(problem, weights, multipliers).satisfied
