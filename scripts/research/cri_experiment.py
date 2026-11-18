"""Certified Revision Impact (CRI) and CRI-U: preregistered experiments.

Every number in the technical report is produced here, and every table in
``artifacts/research/cri_tables.md`` is rendered from the single JSON written by this script. The
prose report cites that file rather than restating numbers, because the previous version of this
work quoted a speed-up (25.6x) that the committed run did not reproduce (18.92x): the number came
from an earlier invocation and drifted. One source of truth removes that failure mode.

What changed after the PR review
--------------------------------
* Trial accounting is explicit. Every attempted rebalance is recorded, with a reason if it is
  rejected. The previous version reported "598 events, 0 skipped" while two trials had vanished.
* Reference regret is computed by an **independent solver** (OSQP) as well as by the internal one.
  The disagreement between them is reported, and a decision whose regret is smaller than that
  disagreement is flagged rather than trusted.
* The dual ascent arms use exactly the requested iteration budget. The previous "5-step" arm
  silently ran at least 20 iterations, so its tightness number was not a five-step number.
* Certificate time is separated from the time needed to construct and store the original dual
  solution, and both are separated from the re-solve.
* The worst-case (uncertainty set) experiment is new: the bound is compared against the exact
  worst case obtained by re-solving every vertex of the box.

Run::

    .venv/bin/python scripts/research/cri_experiment.py --output artifacts/research
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from atlas.decision.baselines import first_order_estimate, strong_convexity_bound
from atlas.decision.certificate import certify_revision_impact, degeneracy_report
from atlas.decision.estimators import covariance_diagnostics, ledoit_wolf_covariance
from atlas.decision.experiment import RunManifest, TrialLedger, array_digest, write_json
from atlas.decision.inventory import (
    CapacityLine,
    capacity_allocation_problem,
    solve_capacity_allocation,
)
from atlas.decision.metrics import moving_block_bootstrap_ci, summarize
from atlas.decision.problem import (ConvexDecisionProblem, check_feasibility,
                                    mean_variance_problem)
from atlas.decision.qp import solve
from atlas.decision.reference import solve_osqp
from atlas.decision.revision import EvidenceRevision, InputSensitivity, compile_revisions
from atlas.decision.uncertainty import (
    adversarial_out_of_set_check,
    certify_worst_case,
    interval_set,
)

#: Fixed before the run. Changing a value here invalidates the preregistration.
CONFIG: dict[str, Any] = {
    "n_risky": 6,
    "cap": 0.25,
    "risk_aversion": 5.0,
    "window": 250,
    "rebalances": 120,
    "seeds": [101, 102, 103, 104, 105],
    "revision_scale": 1.0,
    "useful_tolerance": 1e-4,
    "dual_budgets": [0, 1, 2, 5, 10, 20, 200],
    "scaling_sizes": [8, 16, 32, 64, 128],
    "scaling_seed": 9001,
    "misspecification_factors": [1, 2, 5, 10],
    "uncertainty_trials": 40,
    "uncertainty_dimension": 4,
    "bootstrap": {"block": 12, "resamples": 1500, "seed": 424242},
}

READY_CLOCK = "2024-06-28T20:30:00Z"
REVISION_CLOCK = "2024-07-02T12:00:00Z"


# --------------------------------------------------------------------------- data
@dataclass(frozen=True, slots=True)
class Market:
    returns: np.ndarray
    assets: tuple[str, ...]
    dataset_digest: str


def synthetic_market(seed: int, *, n_assets: int, periods: int, n_factors: int = 3) -> Market:
    """A three-factor return panel. Synthetic, and labelled as such everywhere it is used."""

    rng = np.random.default_rng(seed)
    loadings = rng.normal(0.0, 0.02, size=(n_factors, n_assets))
    factor_mean = np.array([0.0006, 0.0003, -0.0002])
    factor_vol = np.array([0.010, 0.008, 0.006])
    factors = rng.normal(size=(periods, n_factors)) * factor_vol + factor_mean
    idiosyncratic = rng.normal(0.0, 0.008, size=(periods, n_assets))
    returns = factors @ loadings + idiosyncratic
    assets = tuple(f"SYN{i:02d}" for i in range(n_assets))
    return Market(returns=returns, assets=assets, dataset_digest=array_digest(returns))


def decision_problem(assets: Sequence[str], mu: np.ndarray, covariance: np.ndarray,
                     *, problem_id: str, as_of: str) -> ConvexDecisionProblem:
    return mean_variance_problem(
        problem_id=problem_id,
        assets=assets,
        expected_returns=mu,
        covariance=covariance,
        risk_aversion=CONFIG["risk_aversion"],
        lower=0.0,
        upper=CONFIG["cap"],
        budget=1.0,
        as_of=as_of,
        labels={"data": "synthetic_three_factor", "estimator": "ledoit_wolf"},
    )


# ------------------------------------------------------------------------ metrics
def percentile(values: Sequence[float], q: float) -> float | None:
    array = np.asarray([v for v in values if v is not None and math.isfinite(float(v))], dtype=float)
    return float(np.quantile(array, q)) if array.size else None


def rate(flags: Sequence[bool]) -> float | None:
    return float(np.mean(flags)) if len(flags) else None


def _resolution(record: dict[str, Any]) -> float:
    # The resolution a measurement carries: the two reference optima disagree by this much, and the
    # emitted bound is only defensible down to its own floating-point margin.
    return float(max(record.get("verification_resolution") or 0.0,
                     record.get("rounding_margin") or 0.0))


def _bound_sound(record: dict[str, Any], key: str, *, resolution_aware: bool) -> bool:
    # Strict: the bound dominates the measured regret outright. Resolution-aware: it dominates it to
    # within the measurement's own resolution, which is the only claim a float64 solver permits.
    bound = record.get(key)
    if bound is None:
        return False
    tolerance = _resolution(record) if resolution_aware else 0.0
    return bool(record["realized_regret"] <= bound + tolerance)


def reference_regret(problem: ConvexDecisionProblem, weights: Sequence[float]) -> dict[str, Any]:
    """Realized regret measured by two independent solvers, with its own resolution.

    The measured regret is ``f(w) - min(f_internal, f_osqp)``. That is an *upper* estimate of the
    true regret only if both solver points are feasible: a solver that returns a point violating
    the constraints by a few ulps can report an objective slightly below the true optimum, and the
    measured regret then exceeds the true regret by exactly that much. So the block records which
    solver produced the lower objective and by how much that point violates the constraints, and
    reports a ``verification_resolution``: no comparison between a bound and this measurement is
    meaningful below it.

    ``regret`` (the larger of the two measurements) is kept as the reported figure because it is
    the conservative choice for a *reader*; ``regret_conservative`` is the smaller one, which is
    the conservative choice when asking whether a bound was exceeded.
    """

    objective_at_decision = float(problem.objective(np.asarray(weights, dtype=float)))
    internal = solve(problem)
    external = solve_osqp(problem)
    regret_internal = float(objective_at_decision - internal.objective)
    regret_external = float(objective_at_decision - external.objective)
    spread = abs(internal.objective - external.objective)
    objectives = {"internal": float(internal.objective), "osqp": float(external.objective)}
    low_solver = min(objectives, key=objectives.get)
    low_weights = internal.weights if low_solver == "internal" else external.weights
    low_feasibility = check_feasibility(problem, low_weights, tolerance=1e-9)
    resolution = max(spread, 64.0 * float(np.finfo(float).eps)
                     * max(1.0, abs(objective_at_decision)))
    return {
        "regret_internal": regret_internal,
        "regret_external": regret_external,
        "regret": max(regret_internal, regret_external),
        "regret_conservative": min(regret_internal, regret_external),
        "external_weights": tuple(float(v) for v in external.weights),
        "solver_spread": spread,
        "verification_resolution": float(resolution),
        "low_solver": low_solver,
        "low_solver_max_violation": float(low_feasibility.max_violation),
        "low_solver_feasible": bool(low_feasibility.feasible),
        "below_solver_resolution": bool(
            max(regret_internal, regret_external) < 10.0 * max(spread, 1e-15)),
        "internal_status": internal.status,
        "external_status": external.status,
        "external_objective": float(external.objective),
    }


def _precision_block(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile each certified bound with the regret an independent solver measures.

    The question this answers is narrow and specific: *does any measured regret exceed the bound
    emitted for that event, and if so, is the excess explained by the resolution of the measurement
    rather than by a defect in the certificate?* An unexplained shortfall (excess beyond the
    solver spread and the emitted rounding margin) would be a soundness failure; a shortfall
    inside the resolution is not evidence either way, and is counted separately rather than
    averaged away.
    """

    certified = [r for r in records if r.get("verdict") == "zero_regret_within_residual"]
    emitted = [r["bound_warm"] for r in certified if r.get("bound_warm") is not None]
    algebraic = [r["numerical_regret_bound"] for r in certified
                 if r.get("numerical_regret_bound") is not None]
    measured = [r["realized_regret"] for r in certified]
    pairs = [(max(0.0, r["realized_regret"] - r["bound_warm"]), r["verification_resolution"])
             for r in certified if r.get("bound_warm") is not None]
    shortfalls = [item[0] for item in pairs]
    unexplained = [(shortfall, resolution) for shortfall, resolution in pairs
                   if shortfall > resolution]
    identity_ld = [r["identity_residual_extended_precision"] for r in certified
                   if r.get("identity_residual_extended_precision") is not None]
    with_bound = [r for r in records if r.get("bound_warm") is not None]
    strict_violations = [r for r in with_bound if r["realized_regret"] > r["bound_warm"]]
    aware_violations = [r for r in with_bound
                        if r["realized_regret"] > r["bound_warm"] + _resolution(r)]
    return {
        "certified_events": len(certified),
        "algebraic_bound_max": max(algebraic) if algebraic else None,
        "algebraic_bound_median": percentile(algebraic, 0.5),
        "emitted_bound_max": max(emitted) if emitted else None,
        "emitted_bound_median": percentile(emitted, 0.5),
        "measured_regret_max": max(measured) if measured else None,
        "measured_regret_median": percentile(measured, 0.5),
        "solver_resolution_max": max((item[1] for item in pairs), default=None),
        "events_measured_exceeds_emitted": int(sum(1 for value in shortfalls if value > 0)),
        "max_shortfall": max(shortfalls) if shortfalls else 0.0,
        "events_shortfall_within_resolution": int(
            sum(1 for shortfall, resolution in pairs if shortfall <= resolution)),
        "events_shortfall_beyond_resolution": len(unexplained),
        "worst_shortfall_over_resolution": (
            max(item[0] / item[1] for item in pairs if item[1] > 0) if any(
                item[1] > 0 for item in pairs) else 0.0),
        # The measurement that a bound must actually dominate: regret computed against the *better*
        # of the two solver optima. The headline figure uses the worse one, which is the right
        # choice for a reader and the wrong one for testing soundness.
        "conservative_regret_max": max(
            (r["regret_conservative"] for r in certified), default=None),
        # Over every event that carries a bound, not only the certified ones: the two ways of
        # counting a violation, so that a 1.000 rate can never be read as an exact guarantee.
        "bound_events_all": len(with_bound),
        "strict_bound_violations_all": len(strict_violations),
        "resolution_aware_bound_violations_all": len(aware_violations),
        "events_bound_below_conservative_measurement": int(sum(
            1 for r in certified if r.get("bound_warm") is not None
            and r["regret_conservative"] > r["bound_warm"] + r["verification_resolution"])),
        "certified_events_with_low_solver_violation": int(sum(
            1 for r in certified if (r.get("low_solver_max_violation") or 0.0) > 0.0)),
        "max_low_solver_violation": max(
            (r.get("low_solver_max_violation") or 0.0 for r in certified), default=0.0),
        "identity_residual_extended_precision_max": max(identity_ld) if identity_ld else None,
        "conclusion": (
            "a bound below the measured regret is a reconciliation question only when the excess "
            "exceeds the solver's own resolution; every one of these events is inside it"
            if not unexplained else
            "at least one measured regret exceeds its emitted bound by more than the solver "
            "resolution, which is a soundness anomaly and must be investigated"),
    }


# --------------------------------------------------------------- experiment 1: certificates
def experiment_certificates(seed: int) -> dict[str, Any]:
    """Soundness, tightness, coverage, cost and trial accounting across revision magnitudes."""

    market = synthetic_market(seed, n_assets=CONFIG["n_risky"],
                              periods=CONFIG["window"] + CONFIG["rebalances"] + 10)
    rng = np.random.default_rng(seed + 7)
    assets = market.assets
    n = len(assets)
    attempts: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for step in range(CONFIG["rebalances"]):
        end = CONFIG["window"] + step
        window = market.returns[end - CONFIG["window"]:end]
        covariance, shrinkage = ledoit_wolf_covariance(window)
        mu_hat = window.mean(axis=0)
        problem = decision_problem(assets, mu_hat, covariance,
                                   problem_id=f"s{seed}-r{step}", as_of=READY_CLOCK)
        dual_clock = time.perf_counter()
        decision = solve(problem)
        dual_construction_ms = (time.perf_counter() - dual_clock) * 1000.0
        if decision.status != "optimal" or decision.dual is None:
            attempts.append({"step": step, "outcome": "rejected",
                             "reason": f"solver_status_{decision.status}"})
            continue
        count = int(rng.integers(1, 4))
        indices = rng.choice(n, size=count, replace=False)
        standard_error = window.std(axis=0, ddof=1) / math.sqrt(CONFIG["window"])
        delta = np.zeros(n)
        for index in indices:
            delta[index] = rng.normal(0.0, CONFIG["revision_scale"] * standard_error[index] * 3.0)
        revisions = [
            EvidenceRevision(
                revision_id=f"s{seed}-r{step}-rev{int(index)}",
                evidence_id=f"ev-{seed}-{step}-{int(index)}",
                input_key=f"ret_{int(index)}",
                delta=float(delta[index]),
                available_at=REVISION_CLOCK,
                source_id="10-Q/A" if step % 2 else "vendor-correction",
                incorporated_in="decision-vintage",
            )
            for index in indices
        ]
        sensitivities = [InputSensitivity(f"ret_{i}", tuple(-1.0 if j == i else 0.0 for j in range(n)))
                         for i in indices]
        compilation = compile_revisions(problem, revisions, sensitivities,
                                        audit_as_of=REVISION_CLOCK,
                                        starting_vintage="decision-vintage")
        if not compilation.applied:
            attempts.append({"step": step, "outcome": "rejected",
                             "reason": "revision_not_compiled",
                             "detail": compilation.excluded})
            continue

        reference = reference_regret(compilation.problem, decision.weights)
        clock = time.perf_counter()
        warm = certify_revision_impact(problem, decision.weights, compilation,
                                       decision_dual=decision.dual,
                                       useful_bound=CONFIG["useful_tolerance"])
        certificate_ms = (time.perf_counter() - clock) * 1000.0
        clock = time.perf_counter()
        solve(compilation.problem)
        recompute_cold_ms = (time.perf_counter() - clock) * 1000.0
        clock = time.perf_counter()
        solve(compilation.problem, warm_start=decision.weights)
        recompute_warm_ms = (time.perf_counter() - clock) * 1000.0
        clock = time.perf_counter()
        solve_osqp(compilation.problem)
        recompute_osqp_ms = (time.perf_counter() - clock) * 1000.0

        budget_arms: dict[str, Any] = {}
        for budget in CONFIG["dual_budgets"]:
            arm = certify_revision_impact(problem, decision.weights, compilation,
                                          decision_dual=decision.dual,
                                          dual_iterations=budget,
                                          useful_bound=CONFIG["useful_tolerance"])
            budget_arms[str(budget)] = {
                "bound": arm.bounded["regret_upper_bound"],
                "kind": arm.bounded["bound_kind"],
                "actual_iterations": arm.bounded["dual_budget"]["actual_iterations"],
                "objective_evaluations": arm.bounded["dual_budget"]["objective_evaluations"],
            }
        convex = strong_convexity_bound(compilation.problem, decision.weights)
        taylor = first_order_estimate(problem.cost_vector(), compilation.problem.cost_vector(),
                                      decision.weights)
        realized = reference["regret"]
        attempts.append({"step": step, "outcome": "accepted"})
        records.append({
            "step": step,
            "shrinkage": shrinkage,
            "delta_l2": compilation.magnitude,
            "realized_regret": realized,
            "regret_internal": reference["regret_internal"],
            "regret_external": reference["regret_external"],
            "solver_spread": reference["solver_spread"],
            "verification_resolution": reference["verification_resolution"],
            "regret_conservative": reference["regret_conservative"],
            "low_solver": reference["low_solver"],
            "low_solver_max_violation": reference["low_solver_max_violation"],
            "low_solver_feasible": reference["low_solver_feasible"],
            "below_solver_resolution": reference["below_solver_resolution"],
            "weights_changed": bool(np.max(np.abs(np.asarray(decision.weights) -
                                                  np.asarray(reference["external_weights"]))) > 1e-6),
            "verdict": warm.verdict,
            "certified_within_residual": warm.zero_regret,
            "bound_warm": warm.bounded["regret_upper_bound"],
            "identity_residual_extended_precision": (
                (warm.bounded.get("residual_kkt_residuals") or {})
                .get("identity_residual_extended_precision")),
            "residual_rejected": warm.bounded.get("residual_rejected"),
            "bound_arms": budget_arms,
            "bound_convex": convex["bound"] if convex["valid"] else None,
            "estimate_taylor": taylor["estimate"],
            "meets_tolerance": warm.bounded["meets_tolerance"],
            "certificate_ms": certificate_ms,
            "dual_construction_ms": dual_construction_ms,
            "recompute_cold_ms": recompute_cold_ms,
            "recompute_warm_ms": recompute_warm_ms,
            "recompute_osqp_ms": recompute_osqp_ms,
            "recovery_method": warm.exact["recovery_method"],
            "used_lp_fallback": warm.exact["used_lp_fallback"],
            "numerical_regret_bound": warm.exact["numerical_regret_bound"],
            "kkt_satisfied": warm.exact["kkt"]["satisfied"],
            "condition_number": covariance_diagnostics(covariance)["condition_number"],
        })

    usable = [record for record in records]
    realized = [record["realized_regret"] for record in usable]
    arms = {
        "certified_within_residual": [record["certified_within_residual"] for record in usable],
        "bounded_within_tolerance": [record["meets_tolerance"] for record in usable],
        "warm_bound_sound": [_bound_sound(record, "bound_warm", resolution_aware=True)
                             for record in usable],
        # The same count without the resolution allowance, so 1.000 cannot be read as an exact
        # numerical guarantee: it is a guarantee to the precision of the solver that checks it.
        "warm_bound_sound_strict": [_bound_sound(record, "bound_warm", resolution_aware=False)
                                    for record in usable],
        "convex_bound_sound": [record["bound_convex"] is not None and
                               record["bound_convex"] + 1e-12 >= record["realized_regret"]
                               for record in usable],
        "taylor_sound": [abs(record["estimate_taylor"]) + 1e-12 >= record["realized_regret"]
                         for record in usable],
    }
    for budget in CONFIG["dual_budgets"]:
        arms[f"bound_sound_at_{budget}"] = [
            record["bound_arms"][str(budget)]["bound"] is not None and
            record["bound_arms"][str(budget)]["bound"] + 1e-12 >= record["realized_regret"]
            for record in usable
        ]
    positive = [r for r in usable if r["realized_regret"] > 1e-10]
    tightness = {}
    for budget in CONFIG["dual_budgets"]:
        values = [record["bound_arms"][str(budget)]["bound"] / record["realized_regret"]
                  for record in usable
                  if record["bound_arms"][str(budget)]["bound"] is not None
                  and record["realized_regret"] > 1e-10]
        tightness[str(budget)] = {"median": percentile(values, 0.5),
                                  "p90": percentile(values, 0.9), "count": len(values)}
    certified_zero = [r["realized_regret"] for r in usable if r["certified_within_residual"]]
    # The residual bound attached to the *certified* verdict, which is the set the report
    # describes. Records carry a numerical bound under both verdicts, and mixing them made the
    # headline maximum describe a `regret_bounded` event rather than a certified one.
    # Two bounds, never one: the algebraic residual and the value actually emitted, which adds the
    # floating-point resolution of the arithmetic that produced it.
    residual_bounds = [r["bound_warm"] for r in usable
                       if r["certified_within_residual"] and r["bound_warm"] is not None]
    algebraic_bounds = [r["numerical_regret_bound"] for r in usable
                        if r["certified_within_residual"]
                        and r["numerical_regret_bound"] is not None]
    return {
        "seed": seed,
        "dataset_digest": market.dataset_digest,
        "attempted": len(attempts),
        "accepted": len(usable),
        "rejected": len(attempts) - len(usable),
        "rejection_reasons": _reason_counts(attempts),
        "events": len(usable),
        "residual_certified_realized_max": max(certified_zero) if certified_zero else None,
        "residual_certified_realized_p95": percentile(certified_zero, 0.95),
        "mean_realized_regret": float(np.mean(realized)) if realized else None,
        "median_realized_regret": float(np.median(realized)) if realized else None,
        "max_solver_spread": max((r["solver_spread"] for r in usable), default=None),
        "regret_below_solver_resolution_rate": rate([r["below_solver_resolution"] for r in usable]),
        "fraction_with_regret": rate([r["realized_regret"] > 1e-10 for r in usable]),
        "rates": {arm: rate(flags) for arm, flags in arms.items()},
        "tightness_by_budget": tightness,
        "residual_bound": {
            "max": max(residual_bounds) if residual_bounds else None,
            "median": percentile(residual_bounds, 0.5),
            "count": len(residual_bounds),
            "algebraic_max": max(algebraic_bounds) if algebraic_bounds else None,
            "algebraic_median": percentile(algebraic_bounds, 0.5),
        },
        "lp_fallback_rate": rate([r["used_lp_fallback"] for r in usable]),
        "recovery_methods": _reason_counts(
            [{"reason": r["recovery_method"]} for r in usable]),
        "conditional_on_positive_regret": {
            "count": len(positive),
            "certified_within_residual_rate": rate([r["certified_within_residual"] for r in positive]),
        },
        "cost_ms": {
            "certificate_median": percentile([r["certificate_ms"] for r in usable], 0.5),
            "dual_construction_median": percentile(
                [r["dual_construction_ms"] for r in usable], 0.5),
            "recompute_cold_median": percentile([r["recompute_cold_ms"] for r in usable], 0.5),
            "recompute_warm_median": percentile([r["recompute_warm_ms"] for r in usable], 0.5),
            "recompute_osqp_median": percentile([r["recompute_osqp_ms"] for r in usable], 0.5),
        },
        "attempts": attempts,
        "records": records,
    }


def _reason_counts(entries: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("reason", "unspecified"))
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------- experiment 2: cap sweep
def experiment_cap_tightness(seed: int) -> dict[str, Any]:
    """Where exact certification comes from: active bounds, not interior optima."""

    market = synthetic_market(seed + 500, n_assets=CONFIG["n_risky"],
                              periods=CONFIG["window"] + 40)
    rng = np.random.default_rng(seed + 11)
    assets = market.assets
    n = len(assets)
    window = market.returns[-CONFIG["window"]:]
    covariance, _ = ledoit_wolf_covariance(window)
    mu_hat = window.mean(axis=0)
    output = []
    for cap in (0.18, 0.22, 0.25, 0.35, 0.50, 1.00):
        certified = 0
        changed = 0
        certified_regrets: list[float] = []
        trials = 40
        for trial in range(trials):
            problem = mean_variance_problem(
                problem_id=f"cap{cap}-{trial}", assets=assets, expected_returns=mu_hat,
                covariance=covariance, risk_aversion=CONFIG["risk_aversion"],
                lower=0.0, upper=cap, budget=1.0, as_of=READY_CLOCK,
            )
            decision = solve(problem)
            index = int(rng.integers(0, n))
            delta = float(rng.normal(0.0, 0.004))
            revisions = [EvidenceRevision(f"r{trial}", f"e{trial}", f"ret_{index}", delta,
                                          REVISION_CLOCK, incorporated_in="decision-vintage")]
            sensitivities = [InputSensitivity(f"ret_{index}",
                                              tuple(-1.0 if j == index else 0.0 for j in range(n)))]
            compilation = compile_revisions(problem, revisions, sensitivities,
                                            audit_as_of=REVISION_CLOCK,
                                            starting_vintage="decision-vintage")
            reference = reference_regret(compilation.problem, decision.weights)
            certificate = certify_revision_impact(problem, decision.weights, compilation,
                                                  decision_dual=decision.dual,
                                                  reference_solution=solve(compilation.problem))
            certified += int(certificate.zero_regret)
            changed += int(abs(reference["regret"]) > 1e-10)
            if certificate.zero_regret:
                certified_regrets.append(reference["regret"])
        output.append({"cap": cap, "trials": trials, "certified_within_residual_rate": certified / trials,
                       "weights_changed_rate": changed / trials,
                       "max_regret_when_certified": max(certified_regrets) if certified_regrets else None})
    return {"seed": seed, "sweep": output}


# ------------------------------------------------------- experiment 3: misspecification
def experiment_misspecification(seed: int) -> dict[str, Any]:
    """How the guarantee fails when the declared sensitivity understates the actual revision."""

    market = synthetic_market(seed + 900, n_assets=CONFIG["n_risky"],
                              periods=CONFIG["window"] + 10)
    assets = market.assets
    n = len(assets)
    window = market.returns[-CONFIG["window"]:]
    covariance, _ = ledoit_wolf_covariance(window)
    mu_hat = window.mean(axis=0)
    rng = np.random.default_rng(seed + 13)
    output = []
    for factor in CONFIG["misspecification_factors"]:
        violations, events, ratios = 0, 0, []
        for trial in range(40):
            problem = decision_problem(assets, mu_hat, covariance,
                                       problem_id=f"mis-{factor}-{trial}", as_of=READY_CLOCK)
            decision = solve(problem)
            index = int(rng.integers(0, n))
            actual = float(rng.normal(0.0, 0.006))
            declared = actual / factor
            revision = EvidenceRevision(f"r{trial}", f"e{trial}", f"ret_{index}", declared,
                                        REVISION_CLOCK, incorporated_in="decision-vintage")
            sensitivity = InputSensitivity(f"ret_{index}",
                                           tuple(-1.0 if j == index else 0.0 for j in range(n)))
            compilation = compile_revisions(problem, [revision], [sensitivity],
                                            audit_as_of=REVISION_CLOCK,
                                            starting_vintage="decision-vintage")
            certificate = certify_revision_impact(problem, decision.weights, compilation,
                                                 decision_dual=decision.dual)
            true_costs = tuple(problem.linear_costs[j] - (actual if j == index else 0.0)
                               for j in range(n))
            actual_problem = problem.replace(linear_costs=true_costs)
            reference = reference_regret(actual_problem, decision.weights)
            realized = reference["regret"]
            bound = certificate.bounded["regret_upper_bound"]
            events += 1
            if bound is None or bound + 1e-15 < realized:
                violations += 1
            ratios.append(realized / max(bound or 0.0, 1e-15))
        output.append({"declared_fraction": 1.0 / factor, "events": events,
                       "violation_rate": violations / events,
                       "median_realized_over_bound": percentile(ratios, 0.5)})
    return {"seed": seed, "sweep": output}


# -------------------------------------------------------------------- experiment 4: degeneracy
def experiment_degeneracy(seed: int) -> dict[str, Any]:
    """Duplicate assets: value regret stays certifiable, weight identity does not."""

    assets = ["DUP-A", "DUP-B", "SOLO", "OTHER"]
    covariance = np.array([
        [0.0400, 0.0398, 0.0000, 0.0040],
        [0.0398, 0.0400, 0.0000, 0.0040],
        [0.0000, 0.0000, 0.0200, 0.0000],
        [0.0040, 0.0040, 0.0000, 0.0300],
    ])
    problem = mean_variance_problem(
        problem_id="degenerate", assets=assets, expected_returns=[0.10, 0.10, 0.05, 0.07],
        covariance=covariance, risk_aversion=4.0, lower=0.0, upper=0.6, budget=1.0,
        as_of=READY_CLOCK,
    )
    report = degeneracy_report(problem)
    decision = solve(problem)
    twin = np.asarray(decision.weights).copy()
    shift = min(twin[0] * 0.5, 0.6 - twin[1])
    twin[0] -= shift
    twin[1] += shift
    revision = EvidenceRevision("dup-rev", "dup-ev", "ret_2", 0.01, REVISION_CLOCK,
                                incorporated_in="decision-vintage")
    sensitivity = InputSensitivity("ret_2", (0.0, 0.0, -1.0, 0.0))
    compilation = compile_revisions(problem, [revision], [sensitivity],
                                    audit_as_of=REVISION_CLOCK,
                                    starting_vintage="decision-vintage")
    certificate = certify_revision_impact(problem, decision.weights, compilation,
                                          decision_dual=decision.dual)
    twin_certificate = certify_revision_impact(problem, twin, compilation,
                                               decision_dual=decision.dual)
    return {
        "seed": seed,
        "rank": report["rank"],
        "dimension": report["dimension"],
        "weight_identifiability": report["weight_identifiability"],
        "weights": list(decision.weights),
        "twin_weights": [float(v) for v in twin],
        "objective_gap_between_twins": abs(problem.objective(twin) - problem.objective(decision.weights)),
        "twin_verdict": twin_certificate.verdict,
        "primary_verdict": certificate.verdict,
        "primary_bound": certificate.bounded["regret_upper_bound"],
        "twin_bound": twin_certificate.bounded["regret_upper_bound"],
        "note": ("both weight vectors are optimal for the same program, so a decision-identity "
                 "claim is meaningless here while the value certificate remains valid"),
    }


# --------------------------------------------------------------------- experiment 5: hindsight
def experiment_hindsight(seed: int) -> dict[str, Any]:
    """The leakage arm: auditing a decision that was made with the later evidence."""

    market = synthetic_market(seed + 1300, n_assets=CONFIG["n_risky"],
                              periods=CONFIG["window"] + 30)
    rng = np.random.default_rng(seed + 17)
    assets = market.assets
    n = len(assets)
    window = market.returns[-CONFIG["window"]:]
    covariance, _ = ledoit_wolf_covariance(window)
    mu_hat = window.mean(axis=0)
    honest_zero, hindsight_zero, hindsight_regret = 0, 0, []
    trials = 40
    for trial in range(trials):
        problem = decision_problem(assets, mu_hat, covariance,
                                   problem_id=f"hind-{trial}", as_of=READY_CLOCK)
        decision = solve(problem)
        index = int(rng.integers(0, n))
        delta = float(rng.normal(0.0, 0.006))
        revisions = [EvidenceRevision(f"r{trial}", f"e{trial}", f"ret_{index}", delta,
                                      REVISION_CLOCK, incorporated_in="decision-vintage")]
        sensitivities = [InputSensitivity(f"ret_{index}",
                                          tuple(-1.0 if j == index else 0.0 for j in range(n)))]
        compilation = compile_revisions(problem, revisions, sensitivities,
                                        audit_as_of=REVISION_CLOCK,
                                        starting_vintage="decision-vintage")
        honest = certify_revision_impact(problem, decision.weights, compilation,
                                         decision_dual=decision.dual)
        hindsight_decision = solve(compilation.problem)
        hindsight = certify_revision_impact(compilation.problem, hindsight_decision.weights,
                                            compile_revisions(compilation.problem, [], []),
                                            decision_dual=hindsight_decision.dual)
        honest_zero += int(honest.zero_regret)
        hindsight_zero += int(hindsight.zero_regret)
        hindsight_regret.append(compilation.problem.objective(decision.weights) -
                                compilation.problem.objective(hindsight_decision.weights))
    return {
        "seed": seed,
        "trials": trials,
        "honest_certified_within_residual_rate": honest_zero / trials,
        "hindsight_certified_within_residual_rate": hindsight_zero / trials,
        "mean_regret_of_the_actual_decision": float(np.mean(hindsight_regret)),
        "note": ("the hindsight arm audits a decision that was never available; its within-residual "
                 "rate is an artefact of the construction, not evidence of stability"),
    }


# --------------------------------------------------------------------- experiment 6: scaling
def experiment_scaling() -> dict[str, Any]:
    """Certificate cost versus re-solve cost, with the dual construction reported separately."""

    rng = np.random.default_rng(CONFIG["scaling_seed"])
    rows = []
    for n in CONFIG["scaling_sizes"]:
        a = rng.normal(size=(n, n))
        covariance = a @ a.T / n * 0.04 + np.eye(n) * 0.02
        mu = rng.normal(0.08, 0.02, size=n)
        problem = mean_variance_problem(
            problem_id=f"scale-{n}", assets=[f"A{i}" for i in range(n)],
            expected_returns=mu, covariance=covariance, risk_aversion=4.0,
            lower=0.0, upper=max(2.5 / n, 0.05), budget=1.0, as_of=READY_CLOCK,
        )
        clock = time.perf_counter()
        decision = solve(problem)
        dual_construction = (time.perf_counter() - clock) * 1000.0
        revision = EvidenceRevision("scale-rev", "scale-ev", "ret_0", 0.004, REVISION_CLOCK,
                                    incorporated_in="decision-vintage")
        sensitivity = InputSensitivity("ret_0", tuple(-1.0 if j == 0 else 0.0 for j in range(n)))
        compilation = compile_revisions(problem, [revision], [sensitivity],
                                       audit_as_of=REVISION_CLOCK,
                                       starting_vintage="decision-vintage")
        certificate_times, cold_times, warm_times, osqp_times, stages = [], [], [], [], []
        for _ in range(3):
            clock = time.perf_counter()
            certificate = certify_revision_impact(problem, decision.weights, compilation,
                                                  decision_dual=decision.dual)
            certificate_times.append((time.perf_counter() - clock) * 1000.0)
            stages.append(certificate.exact["timings_ms"])
            clock = time.perf_counter()
            solve(compilation.problem)
            cold_times.append((time.perf_counter() - clock) * 1000.0)
            clock = time.perf_counter()
            solve(compilation.problem, warm_start=decision.weights)
            warm_times.append((time.perf_counter() - clock) * 1000.0)
            clock = time.perf_counter()
            solve_osqp(compilation.problem)
            osqp_times.append((time.perf_counter() - clock) * 1000.0)
        median = lambda values: percentile(values, 0.5) or 0.0
        rows.append({
            "n": n,
            "certificate_ms": median(certificate_times),
            "dual_construction_ms": dual_construction,
            "recompute_cold_ms": median(cold_times),
            "recompute_warm_ms": median(warm_times),
            "recompute_osqp_ms": median(osqp_times),
            "speed_ratio_cold": median(cold_times) / max(median(certificate_times), 1e-9),
            "speed_ratio_warm": median(warm_times) / max(median(certificate_times), 1e-9),
            "speed_ratio_osqp": median(osqp_times) / max(median(certificate_times), 1e-9),
            "stages_ms": {key: float(np.median([stage.get(key, 0.0) for stage in stages]))
                          for key in ("multiplier_recovery_ms", "kkt_check_ms",
                                      "residual_bound_ms", "warm_dual_evaluation_ms")},
            "solve_status": decision.status,
            "used_lp_fallback": certificate.exact["used_lp_fallback"],
        })
    return {"rows": rows}


# --------------------------------------------------------------- experiment 7: cross-domain
def experiment_cross_domain(seed: int) -> dict[str, Any]:
    """The same certificate on a capacity-allocation program with linear service caps."""

    rng = np.random.default_rng(seed + 2100)
    lines = [
        CapacityLine("LINE-A", 3.0, 100.0, 0.10),
        CapacityLine("LINE-B", 5.0, 80.0, 0.20),
        CapacityLine("LINE-C", 2.0, 120.0, 0.00),
        CapacityLine("LINE-D", 4.0, 90.0, 0.05),
    ]
    scales = np.array([100.0, 80.0, 120.0, 90.0])
    correlation = 0.3 * np.ones((4, 4)) + 0.7 * np.eye(4)
    covariance = np.outer(scales, scales) * correlation
    problem = capacity_allocation_problem(
        problem_id="capacity-x", lines=lines, demand_covariance=covariance, capacity=250.0,
        risk_aversion=0.02, group_cap=([0, 1, 2], 220.0), as_of=READY_CLOCK,
    )
    decision = solve_capacity_allocation(problem)
    results = []
    for trial in range(20):
        line = int(rng.integers(0, 4))
        delta = float(rng.normal(0.0, 0.4))
        revision = EvidenceRevision(f"d{trial}", f"de{trial}", f"margin_{line}", delta,
                                    REVISION_CLOCK, source_id="demand-forecast-revision",
                                    incorporated_in="decision-vintage")
        sensitivity = InputSensitivity(f"margin_{line}",
                                       tuple(1.0 if j == line else 0.0 for j in range(4)))
        compilation = compile_revisions(problem, [revision], [sensitivity],
                                        audit_as_of=REVISION_CLOCK,
                                        starting_vintage="decision-vintage")
        reference = reference_regret(compilation.problem, decision.weights)
        certificate = certify_revision_impact(problem, decision.weights, compilation,
                                              decision_dual=decision.dual)
        results.append({
            "trial": trial,
            "verdict": certificate.verdict,
            "certified_within_residual": certificate.zero_regret,
            "realized_regret": reference["regret"],
            "bound": certificate.bounded["regret_upper_bound"],
            "below_solver_resolution": reference["below_solver_resolution"],
        })
    return {
        "seed": seed,
        "status": decision.status,
        "certified_optimal": decision.certified_optimal,
        "certified_within_residual_rate": rate([item["certified_within_residual"] for item in results]),
        "bound_sound_rate": rate([item["bound"] is not None and
                                  item["bound"] + 1e-9 >= item["realized_regret"]
                                  for item in results]),
        "mean_realized_regret": float(np.mean([item["realized_regret"] for item in results])),
        "trials": results,
    }


# --------------------------------------------------------- experiment 8: uncertainty sets
def experiment_uncertainty_sets(seed: int) -> dict[str, Any]:
    """Worst-case certificate over a box: soundness, tightness and cost against enumeration.

    The comparison is the honest one. The exact worst case needs ``2**n`` re-solves; the bound
    needs one Cholesky solve plus a support-function evaluation. The bound must never fall below
    the enumerated worst case, and the ratio of the two measures what not reoptimising costs.
    """

    n = CONFIG["uncertainty_dimension"]
    rng = np.random.default_rng(seed + 3100)
    rows = []
    for trial in range(CONFIG["uncertainty_trials"]):
        a = rng.normal(size=(n, n))
        covariance = a @ a.T / n * 0.05 + np.eye(n) * 0.02
        mu = rng.normal(0.08, 0.02, size=n)
        problem = mean_variance_problem(
            problem_id=f"unc-{trial}", assets=[f"U{i}" for i in range(n)],
            expected_returns=mu, covariance=covariance, risk_aversion=4.0,
            lower=0.0, upper=0.6, budget=1.0, as_of=READY_CLOCK,
        )
        decision = solve(problem)
        index = int(rng.integers(0, n))
        centre = np.zeros(n)
        centre[index] = float(rng.normal(0.0, 0.01))
        half = np.full(n, 0.0)
        half[index] = abs(centre[index]) * 0.5 + 1e-4
        uset = interval_set(center=centre, half_width=half,
                            coverage="half the magnitude of the point revision, one coordinate")
        clock = time.perf_counter()
        certificate = certify_worst_case(problem, decision.weights, uset,
                                         decision_dual=decision.dual, gradient_steps=20)
        bound_ms = (time.perf_counter() - clock) * 1000.0
        clock = time.perf_counter()
        worst = -math.inf
        for signs in itertools.product((1.0, -1.0), repeat=n):
            delta = centre + half * np.asarray(signs)
            perturbed = problem.replace(linear_costs=tuple(
                float(v) for v in problem.cost_vector() + delta))
            worst = max(worst, reference_regret(perturbed, decision.weights)["regret"])
        enumeration_ms = (time.perf_counter() - clock) * 1000.0
        outside = np.zeros(n)
        outside[index] = centre[index] + 0.05
        check = adversarial_out_of_set_check(problem, decision.weights, uset,
                                             certificate.bound, outside)
        rows.append({
            "trial": trial,
            "bound": certificate.bound,
            "valid": certificate.valid,
            "gap": certificate.dual_gap,
            "support": certificate.support_value,
            "curvature": certificate.curvature_value,
            "true_worst_case": worst,
            "sound": bool(certificate.valid and certificate.bound + 1e-12 >= worst),
            "tightness": certificate.bound / max(worst, 1e-15),
            "vertices": 2 ** n,
            "bound_ms": bound_ms,
            "enumeration_ms": enumeration_ms,
            "cost_ratio": enumeration_ms / max(bound_ms, 1e-9),
            "out_of_set_violated": check["violated"],
            "out_of_set_regret": check["realized_regret"],
        })
    return {
        "seed": seed,
        "trials": len(rows),
        "dimension": n,
        "sound_rate": rate([row["sound"] for row in rows]),
        "median_tightness": percentile([row["tightness"] for row in rows], 0.5),
        "p90_tightness": percentile([row["tightness"] for row in rows], 0.9),
        "median_bound_ms": percentile([row["bound_ms"] for row in rows], 0.5),
        "median_enumeration_ms": percentile([row["enumeration_ms"] for row in rows], 0.5),
        "median_cost_ratio": percentile([row["cost_ratio"] for row in rows], 0.5),
        "out_of_set_violation_rate": rate([row["out_of_set_violated"] for row in rows]),
        "rows": rows,
    }


# --------------------------------------------------------------------------- driver
def aggregate(seed_results: Sequence[dict[str, Any]], *, block: int, seed: int) -> dict[str, Any]:
    """Pool event-level indicators across seeds and bootstrap them over events, not seeds."""

    records = [record for result in seed_results for record in result["records"]]
    flags = {
        "certified_within_residual": [record["certified_within_residual"] for record in records],
        "bounded_within_tolerance": [record["meets_tolerance"] for record in records],
        "warm_bound_sound": [_bound_sound(record, "bound_warm", resolution_aware=True)
                             for record in records],
        "warm_bound_sound_strict": [_bound_sound(record, "bound_warm", resolution_aware=False)
                                    for record in records],
        "convex_bound_sound": [record["bound_convex"] is not None and
                               record["bound_convex"] + 1e-12 >= record["realized_regret"]
                               for record in records],
        "taylor_sound": [abs(record["estimate_taylor"]) + 1e-12 >= record["realized_regret"]
                         for record in records],
    }
    for budget in CONFIG["dual_budgets"]:
        # Arm bounds live in a nested mapping, so they are read there rather than through
        # _bound_sound. Resolution-aware for the same reason as the warm bound above.
        flags[f"bound_sound_at_{budget}"] = [
            record["bound_arms"][str(budget)]["bound"] is not None and
            record["realized_regret"] <= (record["bound_arms"][str(budget)]["bound"]
                                          + _resolution(record))
            for record in records
        ]
    intervals = {
        arm: moving_block_bootstrap_ci([float(flag) for flag in values],
                                       block=min(block, len(values)), resamples=1500, seed=seed)
        for arm, values in flags.items() if len(values) >= 3
    }
    regrets = [record["realized_regret"] for record in records]
    tightness: dict[str, dict[str, Any]] = {}
    for budget in CONFIG["dual_budgets"]:
        values = [record["bound_arms"][str(budget)]["bound"] / record["realized_regret"]
                  for record in records
                  if record["bound_arms"][str(budget)]["bound"] is not None
                  and record["realized_regret"] > 1e-10]
        tightness[str(budget)] = {"median": percentile(values, 0.5),
                                  "p90": percentile(values, 0.9), "count": len(values)}
    return {
        "events": len(records),
        "pooled_rates": {arm: float(np.mean([float(v) for v in values]))
                         for arm, values in flags.items()},
        "rate_intervals": intervals,
        "realized_regret": summarize(regrets),
        "max_solver_spread": max((r["solver_spread"] for r in records), default=None),
        "fraction_with_regret": rate([r["realized_regret"] > 1e-10 for r in records]),
        "tightness_by_budget": tightness,
    }


def to_markdown(results: dict[str, Any]) -> str:
    """Render every published table from the results dictionary. No hand-edited numbers."""

    lines = ["# CRI experiment results (generated)", "",
             "Generated by `scripts/research/cri_experiment.py`. Do not hand-edit: every table in",
             "the technical report is copied from this file.", ""]
    lines.append("## Configuration")
    lines.append("```json")
    lines.append(json.dumps(results["config"], indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")

    lines.append("## Trial accounting")
    lines.append("")
    lines.append("| seed | attempted | accepted | rejected | reasons |")
    lines.append("|---|---|---|---|---|")
    for result in results["certificates"]["per_seed"]:
        reasons = {key: value for key, value in result["rejection_reasons"].items()
                   if key != "unspecified"}
        lines.append(f"| {result['seed']} | {result['attempted']} | {result['accepted']} | "
                     f"{result['rejected']} | {json.dumps(reasons) if reasons else 'none'} |")
    totals = results["certificates"]["totals"]
    lines.append(f"| **all** | **{totals['attempted']}** | **{totals['accepted']}** | "
                 f"**{totals['rejected']}** | |")
    lines.append("")

    lines.append("## Certificate rates, pooled over seeds")
    lines.append("")
    lines.append("| arm | rate | 95% moving-block interval |")
    lines.append("|---|---|---|")
    aggregate_block = results["certificates"]["aggregate"]
    for arm, value in aggregate_block["pooled_rates"].items():
        interval = aggregate_block["rate_intervals"].get(arm)
        rendered = (f"[{interval['lower']:.3f}, {interval['upper']:.3f}]"
                    if interval else "n/a")
        lines.append(f"| {arm} | {value:.3f} | {rendered} |")
    lines.append("")

    lines.append("## Bound tightness by dual iteration budget (positive-regret events)")
    lines.append("")
    lines.append(f"Events with realized regret above `1e-10`: "
                 f"{results['certificates']['fraction_with_regret']:.3f} of accepted events.")
    lines.append("")
    lines.append("| requested iterations | median bound/regret | p90 | events |")
    lines.append("|---|---|---|---|")
    for arm, stats in results["certificates"]["tightness_by_budget"].items():
        if stats["median"] is None:
            continue
        lines.append(f"| {arm} | {stats['median']:.3f} | {stats['p90']:.3f} | {stats['count']} |")
    lines.append("")

    lines.append("## Numerical residual certificate")
    lines.append("")
    residual = results["certificates"]["residual"]
    lines.append(f"Over the {residual['count']} events certified within the residual, the emitted bound "
                 f"has median {residual['median']:.3e} and maximum {residual['max']:.3e}"
                 + (f" (algebraic value before the floating-point margin: median "
                    f"{residual['algebraic_median']:.3e}, maximum {residual['algebraic_max']:.3e})"
                    if residual.get('algebraic_median') is not None else "") + ".")
    precision = results["certificates"].get("precision") or {}
    if precision.get("certified_events"):
        lines.append("")
        lines.append("### Reconciliation against independently measured regret")
        lines.append("")
        lines.append(
            f"- measured reference regret in the same set: median "
            f"{precision['measured_regret_median']:.3e}, maximum {precision['measured_regret_max']:.3e}")
        lines.append(
            f"- events whose measured regret exceeds the emitted bound: "
            f"{precision['events_measured_exceeds_emitted']} of {precision['certified_events']}, "
            f"largest excess {precision['max_shortfall']:.3e}")
        lines.append(
            f"- solver verification resolution (spread between the two reference optima): "
            f"{precision['solver_resolution_max']:.3e}; worst excess as a fraction of it: "
            f"{precision['worst_shortfall_over_resolution']:.2f}")
        lines.append(
            f"- excesses beyond that resolution: **{precision['events_shortfall_beyond_resolution']}** "
            "(an excess here would be a soundness anomaly, not a measurement question)")
        lines.append(
            f"- events where the emitted bound is below the *conservative* regret (computed "
            f"against the better solver optimum) beyond resolution: "
            f"**{precision['events_bound_below_conservative_measurement']}**")
        lines.append(
            f"- certified events where the lower-objective solver's point violates a constraint: "
            f"{precision['certified_events_with_low_solver_violation']} of "
            f"{precision['certified_events']}, worst violation "
            f"{precision['max_low_solver_violation']:.2e} — this is what makes a solver report an "
            "objective below the true optimum")
        lines.append(
            f"- identity residual recomputed in extended precision, maximum: "
            f"{precision['identity_residual_extended_precision_max']:.3e}")
        lines.append(
            f"- over **all {precision['bound_events_all']}** events carrying a bound, measured regret "
            f"exceeds it outright in {precision['strict_bound_violations_all']} and beyond the "
            f"solver resolution in {precision['resolution_aware_bound_violations_all']} — the "
            "resolution-aware rates in the table above are the second kind, and they are the only "
            "sense in which a soundness rate of 1.000 holds")
        lines.append(f"- {precision['conclusion']}")
    lines.append(f"LP fallback used in {results['certificates']['lp_fallback_rate']:.3f} of events; "
                 f"recovery methods: {json.dumps(results['certificates']['recovery_methods'])}.")
    lines.append("")

    lines.append("## Reference agreement")
    lines.append("")
    lines.append(f"Maximum |internal - OSQP| objective difference over all events: "
                 f"{aggregate_block['max_solver_spread']:.3e}.")
    lines.append(f"Share of events whose regret is below ten times that spread: "
                 f"{results['certificates']['below_resolution_rate']:.3f}.")
    lines.append("")

    lines.append("## Cost")
    lines.append("")
    lines.append("| n | certificate ms | dual construction ms | re-solve cold ms | re-solve warm ms "
                 "| OSQP ms | ratio vs cold SLSQP | ratio vs warm SLSQP | ratio vs OSQP |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in results["scaling"]["rows"]:
        lines.append(f"| {row['n']} | {row['certificate_ms']:.3f} | {row['dual_construction_ms']:.3f} "
                     f"| {row['recompute_cold_ms']:.3f} | {row['recompute_warm_ms']:.3f} "
                     f"| {row['recompute_osqp_ms']:.3f} | {row['speed_ratio_cold']:.2f}× "
                     f"| {row['speed_ratio_warm']:.2f}× | {row['speed_ratio_osqp']:.2f}× |")
    lines.append("")

    lines.append("## Position-cap sweep")
    lines.append("")
    lines.append("| cap | within-residual rate | weights changed | max regret when certified |")
    lines.append("|---|---|---|---|")
    for row in results["cap_tightness"]["sweep"]:
        worst = row.get("max_regret_when_certified")
        lines.append(f"| {row['cap']:.2f} | {row['certified_within_residual_rate']:.3f} | "
                     f"{row['weights_changed_rate']:.3f} | "
                     f"{'n/a' if worst is None else f'{worst:.2e}'} |")
    lines.append("")

    lines.append("## Sensitivity misspecification")
    lines.append("")
    lines.append("| declared fraction of the true revision | violation rate | median realized/bound |")
    lines.append("|---|---|---|")
    for row in results["misspecification"]["sweep"]:
        median = row["median_realized_over_bound"]
        lines.append(f"| {row['declared_fraction']:.3f} | {row['violation_rate']:.3f} | "
                     f"{'n/a' if median is None else f'{median:.2f}'} |")
    lines.append("")

    lines.append("## Worst-case certificate over an interval set")
    lines.append("")
    uncertainty = results["uncertainty_sets"]
    lines.append(f"dimension {uncertainty['dimension']}, {uncertainty['trials']} trials, "
                 f"{2 ** uncertainty['dimension']} vertices enumerated per trial.")
    lines.append("")
    lines.append(f"- sound rate: {uncertainty['sound_rate']:.3f}")
    lines.append(f"- median bound / true worst case: {uncertainty['median_tightness']:.3f} "
                 f"(p90 {uncertainty['p90_tightness']:.3f})")
    lines.append(f"- median bound cost: {uncertainty['median_bound_ms']:.3f} ms; "
                 f"median enumeration cost: {uncertainty['median_enumeration_ms']:.3f} ms; "
                 f"ratio {uncertainty['median_cost_ratio']:.2f}×")
    lines.append(f"- corrections drawn outside the declared set violated the bound in "
                 f"{uncertainty['out_of_set_violation_rate']:.3f} of trials, as expected")
    lines.append("")

    lines.append("## Degeneracy, hindsight and the second domain")
    lines.append("")
    degeneracy = results["degeneracy"]
    lines.append(f"Degeneracy: rank {degeneracy['rank']} / {degeneracy['dimension']}, "
                 f"identifiability `{degeneracy['weight_identifiability']}`, objective gap between "
                 f"twins {degeneracy['objective_gap_between_twins']:.3e}, primary verdict "
                 f"`{degeneracy['primary_verdict']}`, twin verdict `{degeneracy['twin_verdict']}`.")
    hindsight = results["hindsight"]
    lines.append(f"Hindsight: honest within-residual rate {hindsight['honest_certified_within_residual_rate']:.3f}; "
                 f"hindsight within-residual rate {hindsight['hindsight_certified_within_residual_rate']:.3f}; mean "
                 f"regret of the actual decision "
                 f"{hindsight['mean_regret_of_the_actual_decision']:.3e}.")
    cross = results["cross_domain"]
    lines.append(f"Capacity allocation: within-residual rate {cross['certified_within_residual_rate']:.3f}, bound sound "
                 f"rate {cross['bound_sound_rate']:.3f}, mean realized regret "
                 f"{cross['mean_realized_regret']:.3e}.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/research")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    ledger = TrialLedger(output / "cri_ledger.jsonl")
    ledger.reset()

    started = time.perf_counter()
    per_seed = []
    for seed in CONFIG["seeds"]:
        result = experiment_certificates(seed)
        per_seed.append(result)
        ledger.append({
            "arm": "certificate_soundness",
            "hypothesis": "the certified bound never understates realized regret",
            "seed": seed,
            "attempted": result["attempted"],
            "accepted": result["accepted"],
            "rejected": result["rejected"],
            "outcome": "completed",
            "warm_bound_sound_rate": result["rates"]["warm_bound_sound"],
            "certified_within_residual_rate": result["rates"]["certified_within_residual"],
        })

    aggregate_certificates = aggregate(per_seed, block=CONFIG["bootstrap"]["block"],
                                       seed=CONFIG["bootstrap"]["seed"])
    records = [record for result in per_seed for record in result["records"]]
    certified_records = [r for r in records if r.get("verdict") == "zero_regret_within_residual"]
    residual_bounds = [r["bound_warm"] for r in certified_records
                       if r.get("bound_warm") is not None]
    algebraic_bounds = [r["numerical_regret_bound"] for r in certified_records
                        if r.get("numerical_regret_bound") is not None]
    precision = _precision_block(records)
    results: dict[str, Any] = {
        "generated_by": "scripts/research/cri_experiment.py",
        "config": CONFIG,
        "certificates": {
            "per_seed": [{k: v for k, v in result.items() if k not in {"records", "attempts"}}
                         for result in per_seed],
            "aggregate": aggregate_certificates,
            "totals": {
                "attempted": sum(result["attempted"] for result in per_seed),
                "accepted": sum(result["accepted"] for result in per_seed),
                "rejected": sum(result["rejected"] for result in per_seed),
            },
            "tightness_by_budget": aggregate_certificates["tightness_by_budget"],
            "fraction_with_regret": aggregate_certificates["fraction_with_regret"],
            "precision": precision,
            "residual": {"median": percentile(residual_bounds, 0.5),
                         "max": max(residual_bounds) if residual_bounds else None,
                         "count": len(residual_bounds),
                         "algebraic_median": percentile(algebraic_bounds, 0.5),
                         "algebraic_max": (max(algebraic_bounds) if algebraic_bounds else None),
                         "realized_max": max(
                             (r["realized_regret"] for r in records
                              if r["verdict"] == "zero_regret_within_residual"), default=None)},
            "lp_fallback_rate": rate([r["used_lp_fallback"] for r in records]),
            "recovery_methods": _reason_counts([{"reason": r["recovery_method"]} for r in records]),
            "below_resolution_rate": rate([r["below_solver_resolution"] for r in records]),
        },
        "cap_tightness": experiment_cap_tightness(CONFIG["seeds"][0]),
        "misspecification": experiment_misspecification(CONFIG["seeds"][0]),
        "degeneracy": experiment_degeneracy(CONFIG["seeds"][0]),
        "hindsight": experiment_hindsight(CONFIG["seeds"][0]),
        "scaling": experiment_scaling(),
        "cross_domain": experiment_cross_domain(CONFIG["seeds"][0]),
        "uncertainty_sets": experiment_uncertainty_sets(CONFIG["seeds"][0]),
        "records": records,
        "attempts": [attempt for result in per_seed for attempt in result["attempts"]],
        "manifests": [],
        "runtime_seconds": None,
    }
    for seed, result in zip(CONFIG["seeds"], per_seed):
        manifest = RunManifest(
            experiment_id=f"cri-soundness-{seed}",
            hypothesis="a warm-started dual certificate bounds realized regret without a re-solve",
            arm="certificate_soundness",
            seed=seed,
            dataset_digest=result["dataset_digest"],
            parameters={"revision_scale": CONFIG["revision_scale"], "cap": CONFIG["cap"],
                        "risk_aversion": CONFIG["risk_aversion"], "window": CONFIG["window"]},
            splits={"causal": "trailing window only; revision applied after the decision clock"},
            estimator="ledoit_wolf",
            solver="scipy-slsqp-primal/dual-lbfgsb-multipliers + osqp reference",
        ).with_environment()
        results["manifests"].append(manifest.as_dict())

    for name in ("cap_tightness", "misspecification", "degeneracy", "hindsight", "scaling",
                 "cross_domain", "uncertainty_sets"):
        ledger.append({"arm": name, "hypothesis": f"{name} diagnostic",
                       "seed": CONFIG["seeds"][0], "outcome": "completed"})

    results["runtime_seconds"] = time.perf_counter() - started
    results["ledger_summary"] = ledger.summary()
    write_json(output / "cri_results.json", results)
    (output / "cri_tables.md").write_text(to_markdown(results), encoding="utf-8")
    (output / "cri_report.md").write_text(to_markdown(results), encoding="utf-8")
    print(json.dumps({
        "totals": results["certificates"]["totals"],
        "pooled": results["certificates"]["aggregate"]["pooled_rates"],
        "runtime_seconds": results["runtime_seconds"],
    }, indent=2, default=float)[:2500])
    print("wrote", output / "cri_results.json")


if __name__ == "__main__":
    main()
