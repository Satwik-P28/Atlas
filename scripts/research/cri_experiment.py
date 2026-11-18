"""Certified Revision Impact (CRI): preregistered experiments.

Every experiment here has a known data-generating process, fixed seeds and a named
comparison. Nothing is tuned on the reported events: the parameters are fixed in
``CONFIG`` before the run, and the ledger records every arm that executes, including the
ones that fail.

Run::

    .venv/bin/python scripts/research/cri_experiment.py --output artifacts/research

Outputs
-------
``cri_results.json``   full machine-readable results, manifests and per-event records
``cri_report.md``      generated tables (the prose report cites these numbers)
``cri_ledger.jsonl``   append-only trial ledger, including failures
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

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
from atlas.decision.problem import ConvexDecisionProblem, mean_variance_problem
from atlas.decision.qp import DualPoint, solve
from atlas.decision.revision import EvidenceRevision, InputSensitivity, compile_revisions

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
    "scaling_sizes": [8, 16, 32, 64, 128],
    "scaling_seed": 9001,
    "misspecification_factors": [1, 2, 5, 10],
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


# ----------------------------------------------------------------------- experiment 1
def experiment_certificates(seed: int) -> dict[str, Any]:
    """Soundness, tightness, certification rate and cost across revision magnitudes."""

    market = synthetic_market(seed, n_assets=CONFIG["n_risky"], periods=CONFIG["window"] + CONFIG["rebalances"] + 10)
    rng = np.random.default_rng(seed + 7)
    assets = market.assets
    n = len(assets)
    records: list[dict[str, Any]] = []
    for step in range(CONFIG["rebalances"]):
        end = CONFIG["window"] + step
        window = market.returns[end - CONFIG["window"]:end]
        covariance, shrinkage = ledoit_wolf_covariance(window)
        mu_hat = window.mean(axis=0)
        problem = decision_problem(assets, mu_hat, covariance, problem_id=f"s{seed}-r{step}", as_of=READY_CLOCK)
        decision = solve(problem)
        if decision.status != "optimal":
            records.append({"step": step, "status": decision.status, "skipped": True})
            continue
        # A revision affects between one and three inputs, scaled by the sampling error of the
        # estimate it corrects. That ties the perturbation to a real quantity instead of an
        # arbitrary knob.
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
            )
            for index in indices
        ]
        sensitivities = [InputSensitivity(f"ret_{i}", tuple(-1.0 if j == i else 0.0 for j in range(n)))
                         for i in indices]
        compilation = compile_revisions(problem, revisions, sensitivities, audit_as_of=REVISION_CLOCK)
        reference = solve(compilation.problem)

        started = time.perf_counter()
        certificate = certify_revision_impact(problem, decision.weights, compilation,
                                             decision_dual=decision.dual,
                                             reference_solution=reference,
                                             useful_bound=CONFIG["useful_tolerance"])
        certificate_ms = (time.perf_counter() - started) * 1000.0
        started = time.perf_counter()
        solve(compilation.problem)
        recompute_ms = (time.perf_counter() - started) * 1000.0

        warm5 = certify_revision_impact(problem, decision.weights, compilation,
                                        decision_dual=decision.dual, dual_iterations=5,
                                        useful_bound=CONFIG["useful_tolerance"])
        cold = certify_revision_impact(problem, decision.weights, compilation,
                                       decision_dual=None, dual_iterations=200,
                                       useful_bound=CONFIG["useful_tolerance"])
        convex = strong_convexity_bound(compilation.problem, decision.weights)
        taylor = first_order_estimate(problem.cost_vector(), compilation.problem.cost_vector(),
                                      decision.weights)
        realized = certificate.reference["realized_regret"]
        records.append({
            "step": step,
            "status": decision.status,
            "shrinkage": shrinkage,
            "delta_l2": compilation.magnitude,
            "realized_regret": realized,
            "weights_changed": certificate.reference["weights_changed"],
            "max_weight_change": certificate.reference["max_weight_change"],
            "verdict": certificate.verdict,
            "zero_regret": certificate.zero_regret,
            "bound_warm": certificate.bounded["regret_upper_bound"],
            "bound_warm5": warm5.bounded["regret_upper_bound"],
            "bound_cold": cold.bounded["regret_upper_bound"],
            "bound_convex": convex["bound"] if convex["valid"] else None,
            "estimate_taylor": taylor["estimate"],
            "meets_tolerance": certificate.bounded["meets_tolerance"],
            "certificate_ms": certificate_ms,
            "recompute_ms": recompute_ms,
            "condition_number": covariance_diagnostics(covariance)["condition_number"],
        })

    usable = [record for record in records if not record.get("skipped")]
    realized = [record["realized_regret"] for record in usable]
    arms = {
        "zero_regret_certificate": [record["zero_regret"] for record in usable],
        "bounded_within_tolerance": [record["meets_tolerance"] for record in usable],
        "warm_bound_sound": [record["bound_warm"] is not None and
                             record["bound_warm"] + 1e-12 >= record["realized_regret"]
                             for record in usable],
        "warm5_bound_sound": [record["bound_warm5"] is not None and
                              record["bound_warm5"] + 1e-12 >= record["realized_regret"]
                              for record in usable],
        "cold_bound_sound": [record["bound_cold"] is not None and
                             record["bound_cold"] + 1e-12 >= record["realized_regret"]
                             for record in usable],
        "convex_bound_sound": [record["bound_convex"] is not None and
                               record["bound_convex"] + 1e-12 >= record["realized_regret"]
                               for record in usable],
        "taylor_sound": [abs(record["estimate_taylor"]) + 1e-12 >= record["realized_regret"]
                         for record in usable],
    }
    tightness = {
        arm: [record[key] / max(record["realized_regret"], 1e-15)
              for record in usable if record.get(key) is not None]
        for arm, key in (("warm", "bound_warm"), ("warm5", "bound_warm5"),
                         ("cold", "bound_cold"), ("convex", "bound_convex"))
    }
    positive = [r for r in usable if r["realized_regret"] > 1e-10]
    certified_zero = [r["realized_regret"] for r in usable if r["zero_regret"]]
    return {
        "zero_regret_certified_realized_max": max(certified_zero) if certified_zero else None,
        "zero_regret_certified_realized_p95": percentile(certified_zero, 0.95),
        "seed": seed,
        "dataset_digest": market.dataset_digest,
        "events": len(usable),
        "skipped": len(records) - len(usable),
        "mean_realized_regret": float(np.mean(realized)) if realized else None,
        "median_realized_regret": float(np.median(realized)) if realized else None,
        "fraction_with_regret": rate([r["realized_regret"] > 1e-10 for r in usable]),
        "fraction_weights_changed": rate([r["weights_changed"] for r in usable]),
        "rates": {arm: rate(flags) for arm, flags in arms.items()},
        "conditional_tightness": {
            arm: {"median": percentile(values, 0.5), "p90": percentile(values, 0.9),
                  "count": len(values)}
            for arm, values in tightness.items()
        },
        "conditional_on_positive_regret": {
            "count": len(positive),
            "zero_regret_rate": rate([r["zero_regret"] for r in positive]),
            "warm_tightness_median": percentile(
                [r["bound_warm"] / r["realized_regret"] for r in positive], 0.5),
        },
        "cost_ms": {
            "certificate_median": percentile([r["certificate_ms"] for r in usable], 0.5),
            "recompute_median": percentile([r["recompute_ms"] for r in usable], 0.5),
        },
        "records": records,
    }


# ----------------------------------------------------------------------- experiment 2
def experiment_cap_tightness(seed: int) -> dict[str, Any]:
    """Does the certificate's value depend on position limits being active?

    A tighter cap puts more coordinates on a bound, which is exactly the regime where a small
    revision leaves the active set intact. This is the honest boundary of the result: the
    certificate is informative when the optimal solution is corporate, and mostly silent when
    every coordinate is interior.
    """

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
                                          REVISION_CLOCK)]
            sensitivities = [InputSensitivity(f"ret_{index}",
                                              tuple(-1.0 if j == index else 0.0 for j in range(n)))]
            compilation = compile_revisions(problem, revisions, sensitivities,
                                            audit_as_of=REVISION_CLOCK)
            reference = solve(compilation.problem)
            certificate = certify_revision_impact(problem, decision.weights, compilation,
                                                 decision_dual=decision.dual,
                                                 reference_solution=reference)
            certified += int(certificate.zero_regret)
            changed += int(certificate.reference["weights_changed"])
            if certificate.zero_regret:
                certified_regrets.append(certificate.reference["realized_regret"])
        output.append({"cap": cap, "trials": trials, "zero_regret_rate": certified / trials,
                       "weights_changed_rate": changed / trials,
                       "max_regret_when_certified": max(certified_regrets) if certified_regrets else None})
    return {"seed": seed, "sweep": output}


# ----------------------------------------------------------------------- experiment 3
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
                                        REVISION_CLOCK)
            sensitivity = InputSensitivity(f"ret_{index}",
                                           tuple(-1.0 if j == index else 0.0 for j in range(n)))
            compilation = compile_revisions(problem, [revision], [sensitivity],
                                            audit_as_of=REVISION_CLOCK)
            certificate = certify_revision_impact(problem, decision.weights, compilation,
                                                 decision_dual=decision.dual)
            # The program that actually occurred used the true revision.
            true_costs = tuple(problem.linear_costs[j] - (actual if j == index else 0.0)
                               for j in range(n))
            actual_problem = problem.replace(linear_costs=true_costs)
            actual_reference = solve(actual_problem)
            realized = actual_problem.objective(decision.weights) - actual_reference.objective
            bound = certificate.bounded["regret_upper_bound"]
            events += 1
            if bound is None or bound + 1e-15 < realized:
                violations += 1
            ratios.append(realized / max(bound or 0.0, 1e-15))
        output.append({"declared_fraction": 1.0 / factor, "events": events,
                       "violation_rate": violations / events,
                       "median_realized_over_bound": percentile(ratios, 0.5)})
    return {"seed": seed, "sweep": output}


# ----------------------------------------------------------------------- experiment 4
def experiment_degeneracy(seed: int) -> dict[str, Any]:
    """Duplicate assets: value regret stays certifiable, weight identity does not."""

    # Two assets correlated at 0.999 with different variances: the risk matrix is positive
    # definite, so the dual bound exists, but the two assets are near-perfect substitutes and
    # the objective is almost flat along the direction that swaps them.
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
    revision = EvidenceRevision("dup-rev", "dup-ev", "ret_2", 0.01, REVISION_CLOCK)
    sensitivity = InputSensitivity("ret_2", (0.0, 0.0, -1.0, 0.0))
    compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=REVISION_CLOCK)
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


# ----------------------------------------------------------------------- experiment 5
def experiment_hindsight(seed: int) -> dict[str, Any]:
    """The leakage arm: auditing a decision that was made with the later evidence.

    It reports zero regret almost always, which is precisely why it is useless as an audit of
    the decision that was actually taken.
    """

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
                                      REVISION_CLOCK)]
        sensitivities = [InputSensitivity(f"ret_{index}",
                                          tuple(-1.0 if j == index else 0.0 for j in range(n)))]
        compilation = compile_revisions(problem, revisions, sensitivities, audit_as_of=REVISION_CLOCK)
        honest = certify_revision_impact(problem, decision.weights, compilation,
                                         decision_dual=decision.dual)
        # Hindsight: recompute the decision with the later evidence, then audit *that* decision.
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
        "honest_zero_regret_rate": honest_zero / trials,
        "hindsight_zero_regret_rate": hindsight_zero / trials,
        "mean_regret_of_the_actual_decision": float(np.mean(hindsight_regret)),
        "note": ("the hindsight arm audits a decision that was never available; its zero-regret "
                 "rate is an artefact of the construction, not evidence of stability"),
    }


# ----------------------------------------------------------------------- experiment 6
def experiment_scaling() -> dict[str, Any]:
    """Certificate cost versus full re-solve cost as the program grows."""

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
        decision = solve(problem)
        index = 0
        revision = EvidenceRevision("scale-rev", "scale-ev", f"ret_{index}", 0.004, REVISION_CLOCK)
        sensitivity = InputSensitivity(f"ret_{index}",
                                       tuple(-1.0 if j == index else 0.0 for j in range(n)))
        compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=REVISION_CLOCK)
        certificate_times, recompute_times = [], []
        for _ in range(3):
            started = time.perf_counter()
            certify_revision_impact(problem, decision.weights, compilation,
                                    decision_dual=decision.dual)
            certificate_times.append((time.perf_counter() - started) * 1000.0)
            started = time.perf_counter()
            solve(compilation.problem)
            recompute_times.append((time.perf_counter() - started) * 1000.0)
        rows.append({
            "n": n,
            "certificate_ms": percentile(certificate_times, 0.5),
            "recompute_ms": percentile(recompute_times, 0.5),
            "speed_ratio": percentile(recompute_times, 0.5) / max(percentile(certificate_times, 0.5), 1e-9),
            "solve_status": decision.status,
            "dual_iterations": decision.diagnostics["dual"]["iterations"],
        })
    return {"rows": rows}


# ----------------------------------------------------------------------- experiment 7
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
                                    REVISION_CLOCK, source_id="demand-forecast-revision")
        sensitivity = InputSensitivity(f"margin_{line}",
                                       tuple(1.0 if j == line else 0.0 for j in range(4)))
        compilation = compile_revisions(problem, [revision], [sensitivity], audit_as_of=REVISION_CLOCK)
        reference = solve_capacity_allocation(compilation.problem)
        certificate = certify_revision_impact(problem, decision.weights, compilation,
                                              decision_dual=decision.dual,
                                              reference_solution=reference)
        results.append({
            "trial": trial,
            "verdict": certificate.verdict,
            "zero_regret": certificate.zero_regret,
            "realized_regret": certificate.reference["realized_regret"],
            "bound": certificate.bounded["regret_upper_bound"],
            "weights_changed": certificate.reference["weights_changed"],
        })
    return {
        "seed": seed,
        "status": decision.status,
        "certified_optimal": decision.certified_optimal,
        "zero_regret_rate": rate([item["zero_regret"] for item in results]),
        "bound_sound_rate": rate([item["bound"] is not None and
                                  item["bound"] + 1e-12 >= item["realized_regret"]
                                  for item in results]),
        "mean_realized_regret": float(np.mean([item["realized_regret"] for item in results])),
        "trials": results,
    }


# --------------------------------------------------------------------------- driver
def aggregate(seed_results: Sequence[dict[str, Any]], *, block: int, seed: int) -> dict[str, Any]:
    """Pool event-level indicators across seeds and bootstrap them.

    The interval has to be computed over *events*, not over five seed-level rates: a bootstrap
    of five numbers cannot produce a meaningful interval, and an earlier version of this
    function silently returned degenerate intervals for exactly that reason. Events within a
    seed are serially dependent (the estimation window overlaps), so the resampling is a
    moving-block bootstrap rather than an i.i.d. one.
    """

    records = [record for result in seed_results for record in result["records"]
               if not record.get("skipped")]
    flags = {
        "zero_regret_certificate": [record["zero_regret"] for record in records],
        "bounded_within_tolerance": [record["meets_tolerance"] for record in records],
        "warm_bound_sound": [record["bound_warm"] is not None and
                             record["bound_warm"] + 1e-12 >= record["realized_regret"]
                             for record in records],
        "warm5_bound_sound": [record["bound_warm5"] is not None and
                              record["bound_warm5"] + 1e-12 >= record["realized_regret"]
                              for record in records],
        "cold_bound_sound": [record["bound_cold"] is not None and
                             record["bound_cold"] + 1e-12 >= record["realized_regret"]
                             for record in records],
        "convex_bound_sound": [record["bound_convex"] is not None and
                               record["bound_convex"] + 1e-12 >= record["realized_regret"]
                               for record in records],
        "taylor_sound": [abs(record["estimate_taylor"]) + 1e-12 >= record["realized_regret"]
                         for record in records],
    }
    intervals = {
        arm: moving_block_bootstrap_ci([float(flag) for flag in values],
                                       block=min(block, len(values)), resamples=1500, seed=seed)
        for arm, values in flags.items() if len(values) >= 3
    }
    regrets = [record["realized_regret"] for record in records]
    tightness = [record["bound_warm"] / record["realized_regret"] for record in records
                 if record.get("bound_warm") is not None and record["realized_regret"] > 1e-10]
    return {
        "events": len(records),
        "pooled_rates": {arm: float(np.mean([float(v) for v in values]))
                         for arm, values in flags.items()},
        "rate_intervals": intervals,
        "realized_regret": summarize(regrets),
        "warm_tightness_positive_regret_only": summarize(tightness),
    }


def to_markdown(results: dict[str, Any]) -> str:
    lines = ["# CRI experiment results (generated)", "",
             "Generated by `scripts/research/cri_experiment.py`. Do not hand-edit.", ""]
    lines.append("## Configuration")
    lines.append("```json")
    lines.append(json.dumps(CONFIG, indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append("## Certificate rates by seed")
    lines.append("")
    lines.append("| seed | events | regret>0 | weights changed | zero-regret cert. | bounded ≤ tol | warm bound sound | cold bound sound | convex bound sound |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for result in results["certificates"]["per_seed"]:
        rates = result["rates"]
        lines.append(
            f"| {result['seed']} | {result['events']} | {result['fraction_with_regret']:.3f} | "
            f"{result['fraction_weights_changed']:.3f} | {rates['zero_regret_certificate']:.3f} | "
            f"{rates['bounded_within_tolerance']:.3f} | {rates['warm_bound_sound']:.3f} | "
            f"{rates['cold_bound_sound']:.3f} | {rates['convex_bound_sound']:.3f} |"
        )
    pooled = results["certificates"]["aggregate"]["pooled_rates"]
    lines.append("")
    lines.append("Pooled: " + ", ".join(f"{arm} = {value:.3f}" for arm, value in pooled.items()))
    lines.append("")
    lines.append("Realized regret among zero-regret-certified events (max / p95): "
                 + " / ".join(
                     "n/a" if result["zero_regret_certified_realized_max"] is None
                     else f"{result['zero_regret_certified_realized_max']:.3e}"
                     for result in results["certificates"]["per_seed"])
                 + " (max); "
                 + " / ".join(
                     "n/a" if result["zero_regret_certified_realized_p95"] is None
                     else f"{result['zero_regret_certified_realized_p95']:.3e}"
                     for result in results["certificates"]["per_seed"])
                 + " (p95)")
    lines.append("")
    lines.append("## Bound tightness (bound / realized regret, positive-regret events)")
    lines.append("")
    lines.append("| arm | median | p90 | events |")
    lines.append("|---|---|---|---|")
    for arm, stats in results.get("aggregate_tightness",
                                 results["certificates_aggregate_tightness"]).items():
        if stats["median"] is None:
            continue
        lines.append(f"| {arm} | {stats['median']:.2f} | {stats['p90']:.2f} | {stats['count']} |")
    lines.append("")
    lines.append("## Position-cap sweep")
    lines.append("")
    lines.append("| cap | zero-regret rate | weights changed | max regret when certified |")
    lines.append("|---|---|---|---|")
    for row in results["cap_tightness"]["sweep"]:
        worst = row.get("max_regret_when_certified")
        lines.append(f"| {row['cap']:.2f} | {row['zero_regret_rate']:.3f} | "
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
    lines.append("## Scaling")
    lines.append("")
    lines.append("| n | certificate ms | re-solve ms | ratio |")
    lines.append("|---|---|---|---|")
    for row in results["scaling"]["rows"]:
        lines.append(f"| {row['n']} | {row['certificate_ms']:.3f} | {row['recompute_ms']:.3f} | "
                     f"{row['speed_ratio']:.2f}× |")
    lines.append("")
    lines.append("## Degeneracy")
    lines.append("")
    degeneracy = results["degeneracy"]
    lines.append(f"rank {degeneracy['rank']} / {degeneracy['dimension']}, identifiability "
                 f"`{degeneracy['weight_identifiability']}`, objective gap between twins "
                 f"{degeneracy['objective_gap_between_twins']:.3e}, primary verdict "
                 f"`{degeneracy['primary_verdict']}`, twin verdict `{degeneracy['twin_verdict']}`.")
    lines.append("")
    lines.append("## Hindsight arm and cross-domain transfer")
    lines.append("")
    hindsight = results["hindsight"]
    lines.append(f"Honest zero-regret rate {hindsight['honest_zero_regret_rate']:.3f}; hindsight "
                 f"zero-regret rate {hindsight['hindsight_zero_regret_rate']:.3f}; mean regret of "
                 f"the actual decision {hindsight['mean_regret_of_the_actual_decision']:.3e}.")
    cross = results["cross_domain"]
    lines.append(f"Capacity allocation: zero-regret rate {cross['zero_regret_rate']:.3f}, bound "
                 f"sound rate {cross['bound_sound_rate']:.3f}, mean realized regret "
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

    started = time.perf_counter()
    per_seed = []
    for seed in CONFIG["seeds"]:
        result = experiment_certificates(seed)
        per_seed.append(result)
        ledger.append({
            "arm": "certificate_soundness",
            "hypothesis": "the certified bound never understates realized regret",
            "seed": seed,
            "events": result["events"],
            "outcome": "completed",
            "warm_bound_sound_rate": result["rates"]["warm_bound_sound"],
            "zero_regret_rate": result["rates"]["zero_regret_certificate"],
        })

    aggregate_certificates = aggregate(per_seed, block=CONFIG["bootstrap"]["block"],
                                       seed=CONFIG["bootstrap"]["seed"])
    tightness_by_arm = {}
    for arm in ("warm", "warm5", "cold", "convex"):
        values = []
        for result in per_seed:
            for record in result["records"]:
                if record.get("skipped") or record["realized_regret"] <= 1e-10:
                    continue
                key = {"warm": "bound_warm", "warm5": "bound_warm5", "cold": "bound_cold",
                       "convex": "bound_convex"}[arm]
                if record.get(key) is not None:
                    values.append(record[key] / record["realized_regret"])
        tightness_by_arm[arm] = {
            "median": percentile(values, 0.5), "p90": percentile(values, 0.9),
            "count": len(values),
        }

    results: dict[str, Any] = {
        "generated_by": "scripts/research/cri_experiment.py",
        "config": CONFIG,
        "certificates": {
            "per_seed": [{k: v for k, v in result.items() if k != "records"} for result in per_seed],
            "aggregate": aggregate_certificates,
        },
        "certificates_aggregate_tightness": tightness_by_arm,
        "cap_tightness": experiment_cap_tightness(CONFIG["seeds"][0]),
        "misspecification": experiment_misspecification(CONFIG["seeds"][0]),
        "degeneracy": experiment_degeneracy(CONFIG["seeds"][0]),
        "hindsight": experiment_hindsight(CONFIG["seeds"][0]),
        "scaling": experiment_scaling(),
        "cross_domain": experiment_cross_domain(CONFIG["seeds"][0]),
        "records": [record for result in per_seed for record in result["records"]],
        "manifests": [],
        "runtime_seconds": None,
    }
    results["aggregate_tightness"] = tightness_by_arm
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
            solver="scipy-slsqp-primal/dual-lbfgsb-multipliers",
        ).with_environment()
        results["manifests"].append(manifest.as_dict())

    for name, outcome in (("cap_tightness", results["cap_tightness"]),
                          ("misspecification", results["misspecification"]),
                          ("degeneracy", results["degeneracy"]),
                          ("hindsight", results["hindsight"]),
                          ("scaling", results["scaling"]),
                          ("cross_domain", results["cross_domain"])):
        ledger.append({"arm": name, "hypothesis": f"{name} diagnostic", "seed":
                       CONFIG["seeds"][0], "outcome": "completed"})

    results["runtime_seconds"] = time.perf_counter() - started
    results["ledger_summary"] = ledger.summary()
    write_json(output / "cri_results.json", results)
    (output / "cri_report.md").write_text(to_markdown(results), encoding="utf-8")
    print(json.dumps({k: results[k] for k in
                      ("certificates_aggregate_tightness", "runtime_seconds", "ledger_summary")},
                     indent=2, default=float)[:4000])
    print("wrote", output / "cri_results.json")


if __name__ == "__main__":
    main()
