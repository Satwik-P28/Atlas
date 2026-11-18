"""Real-world revision study: does a published revision change the decision, and can CRI prove it doesn't?

The dataset comes from :mod:`scripts.research.rtds_build` (ALFRED real-time vintages). This module
turns each event into a decision/audit pair on a fixed convex resource-allocation program, measures
the true regret by re-solving, runs the certificate and every competing method, and writes the
statistics that the protocol in ``docs/research/rtds/PREREGISTRATION.md`` fixes in advance.

Two cohorts are analysed separately and never pooled: quarterly BEA expenditure aggregates and
monthly BLS payroll employment. They are different revision processes, and averaging them would be a
statistic about the average of two unrelated things.

Run: ``.venv/bin/python scripts/research/rtds_study.py``
"""

from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from atlas.decision.baselines import first_order_estimate, strong_convexity_bound
from atlas.decision.certificate import certify_revision_impact, stability_radius
from atlas.decision.problem import LinearInequality, mean_variance_problem
from atlas.decision.qp import derive_multipliers, solve, verify_kkt
from atlas.decision.reference import solve_osqp
from atlas.decision.revision import EvidenceRevision, InputSensitivity, compile_revisions
from atlas.decision.uncertainty import certify_worst_case, interval_set

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "artifacts" / "research" / "rtds"
OUT = DATA

#: Preregistered thresholds. ``TAU`` is the regret below which a revision is called immaterial.
TAU = 1e-3
#: Risk weights considered by the prespecified calibration rule (train split only).
RHO_GRID = (0.25, 0.5, 1.0, 2.0)
#: Constraints that make the active set non-trivial.
INEQUALITIES: dict[str, tuple[tuple[tuple[float, ...], float, str], ...]] = {
    # Rows are ``coefficients @ w <= bound``, so a floor is written with a negated row.
    "A": (((0.0, 0.0, -1.0, 0.0), -0.15, "government floor"),      # x_gov >= 0.15
          ((0.0, 1.0, 0.0, 0.0), 0.45, "investment cap")),        # x_inv <= 0.45
    "B": (((0.0, -1.0, 0.0), -0.20, "manufacturing floor"),),      # x_manuf >= 0.20
}
LOWER_FLOOR = {"A": 0.15, "B": 0.20}


def load_dataset() -> dict[str, Any]:
    return json.loads((DATA / "dataset.json").read_text())


def growth_matrix(events: Sequence[dict[str, Any]]) -> np.ndarray:
    return np.asarray([event["growth_decision"] for event in events], dtype=float)


def calibration(events: Sequence[dict[str, Any]], labels: Sequence[str]) -> dict[str, Any]:
    """Mean, scale and correlation of **first-print** growth, estimated on the train split only."""

    matrix = growth_matrix(events)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0, ddof=1)
    scale = np.where(scale > 0, scale, 1.0)
    correlation = np.corrcoef(matrix.T)
    return {"mean": mean, "scale": scale, "correlation": correlation,
            "events": int(matrix.shape[0])}


def standardise(growth: Sequence[float], block: dict[str, Any]) -> np.ndarray:
    return (np.asarray(growth, dtype=float) - block["mean"]) / block["scale"]


def allocations(n: int, cohort: str) -> tuple[LinearInequality, ...]:
    return tuple(LinearInequality(tuple(row), float(bound), label)
                 for row, bound, label in INEQUALITIES[cohort])


def build_problem(cost: Sequence[float], cohort: str, labels: Sequence[str],
                  correlation: np.ndarray, rho: float, as_of: str, problem_id: str):
    """``min 0.5 x'(rho*corr) x - cost'x`` on the budget/box/inequality set."""

    return mean_variance_problem(
        problem_id=problem_id,
        assets=list(labels),
        expected_returns=[float(value) for value in cost],
        covariance=(rho * correlation).tolist(),
        risk_aversion=1.0,
        lower=0.0,
        upper=0.6,
        budget=1.0,
        inequalities=allocations(len(labels), cohort),
        as_of=as_of,
        labels={"cohort": cohort, "risk_weight": f"{rho:g}"},
    )


def interior_share(events: Sequence[dict[str, Any]], cohort: str, labels: Sequence[str],
                   block: dict[str, Any], rho: float) -> float:
    """Share of events whose optimum is not exclusively at box corners (train split only)."""

    interior = 0
    for event in events:
        cost = standardise(event["growth_decision"], block)
        problem = build_problem(cost, cohort, labels, block["correlation"], rho,
                                event["decision_vintage"], "calibration")
        solution = solve(problem)
        if not solution.feasible:
            continue
        lower, upper = problem.bounds()
        weights = np.asarray(solution.weights, dtype=float)
        at_bound = np.isclose(weights, lower, atol=1e-6) | np.isclose(weights, upper, atol=1e-6)
        if not np.all(at_bound):
            interior += 1
    return interior / max(1, len(events))


def choose_rho(train: Sequence[dict[str, Any]], cohort: str, labels: Sequence[str],
               block: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """Prespecified rule: the risk weight with the largest interior share on the train split."""

    shares = {f"{rho:g}": interior_share(train, cohort, labels, block, rho) for rho in RHO_GRID}
    best = max(RHO_GRID, key=lambda rho: (shares[f"{rho:g}"], -abs(rho - 1.0)))
    return best, shares


def clustered_interval(values: Sequence[float], clusters: Sequence[str], *, resamples: int = 2000,
                       seed: int = 7) -> dict[str, Any]:
    """Moving-block bootstrap over clusters (decision years), not over events."""

    order = sorted(set(clusters))
    grouped: dict[str, list[float]] = {key: [] for key in order}
    for value, key in zip(values, clusters):
        grouped[key].append(float(value))
    block = 3 if len(order) >= 9 else max(2, len(order) // 2)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(resamples):
        draw: list[float] = []
        start = rng.integers(0, max(1, len(order) - block + 1))
        for index in range(block):
            key = order[(start + index) % len(order)]
            draw.extend(grouped[key])
        if draw:
            means.append(float(np.mean(draw)))
    point = float(np.mean(values)) if values else float("nan")
    return {"estimate": point,
            "lower": float(np.quantile(means, 0.025)) if means else None,
            "upper": float(np.quantile(means, 0.975)) if means else None,
            "clusters": len(order), "block": block, "resamples": resamples,
            "method": "moving_block_bootstrap_over_decision_years"}


def clustered_auc_interval(scores: Sequence[float], labels: Sequence[bool],
                           clusters: Sequence[str], *, resamples: int = 400,
                           seed: int = 11) -> dict[str, Any] | None:
    """AUC interval by resampling whole decision years, so a year's events move together."""

    if not scores or len(scores) != len(labels):
        return None
    order = sorted(set(clusters))
    index: dict[str, list[int]] = {key: [] for key in order}
    for position, key in enumerate(clusters):
        index[key].append(position)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(resamples):
        picked: list[int] = []
        for _ in range(len(order)):
            key = order[int(rng.integers(0, len(order)))]
            picked.extend(index[key])
        sample_scores = [scores[i] for i in picked]
        sample_labels = [labels[i] for i in picked]
        value = auc(sample_scores, sample_labels)
        if value is not None:
            values.append(value)
    point = auc(list(scores), list(labels))
    if not values:
        return None
    return {"estimate": point, "lower": float(np.quantile(values, 0.025)),
            "upper": float(np.quantile(values, 0.975)), "clusters": len(order),
            "resamples": resamples, "method": "cluster_bootstrap_over_decision_years"}


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Rank-based AUC; ties count one half."""

    positives = [s for s, y in zip(scores, labels) if y]
    negatives = [s for s, y in zip(scores, labels) if not y]
    if not positives or not negatives:
        return None
    total = 0.0
    for value in positives:
        for other in negatives:
            total += 1.0 if value > other else 0.5 if value == other else 0.0
    return total / (len(positives) * len(negatives))


def logistic_fit(features: np.ndarray, labels: np.ndarray, *, l2: float = 1.0,
                 iterations: int = 60) -> np.ndarray:
    """Newton/IRLS with a ridge term: small enough to implement, honest enough to trust."""

    design = np.hstack([np.ones((features.shape[0], 1)), features])
    beta = np.zeros(design.shape[1])
    for _ in range(iterations):
        eta = design @ beta
        probability = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        weight = np.clip(probability * (1 - probability), 1e-8, None)
        gradient = design.T @ (probability - labels) + l2 * np.concatenate([[0.0], beta[1:]])
        hessian = design.T @ (design * weight[:, None]) + l2 * np.eye(design.shape[1])
        step = np.linalg.solve(hessian, gradient)
        beta -= step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def logistic_score(features: np.ndarray, beta: np.ndarray) -> np.ndarray:
    design = np.hstack([np.ones((features.shape[0], 1)), features])
    return 1.0 / (1.0 + np.exp(-np.clip(design @ beta, -30, 30)))


def serialise_size(payload: Any) -> int:
    return len(json.dumps(payload, sort_keys=True, default=str).encode())


def run_event(event: dict[str, Any], cohort: str, labels: Sequence[str], block: dict[str, Any],
              rho: float, *, dual_iterations: int = 0) -> dict[str, Any] | None:
    """One decision/audit pair, every method, and the measured truth."""

    cost_decision = standardise(event["growth_decision"], block)
    cost_audit = standardise(event["growth_audit"], block)
    decision_problem = build_problem(cost_decision, cohort, labels, block["correlation"], rho,
                                     event["decision_vintage"], "decision")
    clock_start = time.perf_counter()
    decision = solve(decision_problem)
    decision_ms = (time.perf_counter() - clock_start) * 1000.0
    if not decision.feasible or decision.dual is None:
        return None

    revisions = []
    sensitivities = []
    for index, label in enumerate(labels):
        shift = float(cost_audit[index] - cost_decision[index])
        if shift == 0.0:
            continue
        revisions.append(EvidenceRevision(
            revision_id=f"{event['period']}::{label}",
            evidence_id=event["audit_vintage"],
            input_key=label,
            delta=shift,
            available_at=f"{event['audit_vintage']}T23:59:59Z",
            effective_at=f"{event['audit_vintage']}T23:59:59Z",
            kind="linear_objective",
            source_id=f"ALFRED vintage {event['audit_vintage']}",
            version=1,
            delta_semantics="absolute",
            note="cost-vector correction relative to the decision vintage",
        ))
        effect = [0.0] * len(labels)
        effect[index] = 1.0
        sensitivities.append(InputSensitivity(label, tuple(effect)))
    if not revisions:
        return None

    clock_start = time.perf_counter()
    compilation = compile_revisions(
        decision_problem, revisions, sensitivities,
        as_of=f"{event['decision_vintage']}T23:59:59Z",
        audit_as_of=f"{event['audit_vintage']}T23:59:59Z",
        starting_vintage=event["decision_vintage"],
    )
    compile_ms = (time.perf_counter() - clock_start) * 1000.0
    if compilation.status != "applied":
        return None
    audit_problem = compilation.problem

    recorded = np.asarray(decision.weights, dtype=float)
    objective_at_decision = float(audit_problem.objective(recorded))
    clock_start = time.perf_counter()
    internal = solve(audit_problem)
    internal_ms = (time.perf_counter() - clock_start) * 1000.0
    clock_start = time.perf_counter()
    external = solve_osqp(audit_problem)
    external_ms = (time.perf_counter() - clock_start) * 1000.0
    objectives = [float(internal.objective), float(external.objective)]
    best = min(objectives)
    regret = objective_at_decision - best
    regret_conservative = objective_at_decision - max(objectives)
    resolution = abs(objectives[0] - objectives[1])

    clock_start = time.perf_counter()
    certificate = certify_revision_impact(decision_problem, recorded, compilation,
                                          decision_dual=decision.dual,
                                          dual_iterations=dual_iterations)
    certificate_ms = (time.perf_counter() - clock_start) * 1000.0
    bound = certificate.bounded["regret_upper_bound"]
    algebraic = certificate.bounded.get("regret_upper_bound_exact_arithmetic")

    clock_start = time.perf_counter()
    multipliers, _diagnostics = derive_multipliers(audit_problem, recorded)
    stable = bool(multipliers is not None and
                  verify_kkt(audit_problem, recorded, multipliers).satisfied)
    active_set_ms = (time.perf_counter() - clock_start) * 1000.0

    taylor = first_order_estimate(decision_problem.cost_vector(), audit_problem.cost_vector(),
                                  recorded)
    strong = strong_convexity_bound(audit_problem, recorded)

    # CRI-U: a worst-case bound over a set sized by the train-split revision dispersion. The centre
    # is the audit cost vector, so the set represents "the corrected costs, plus the typical
    # revision we cannot yet see"; the width is one interquartile range of |delta| per input.
    half = np.asarray(block["half_width"], dtype=float)
    uncertainty = interval_set(center=cost_audit, half_width=half, coverage="declared",
                               label="train revision dispersion")
    clock_start = time.perf_counter()
    worst = certify_worst_case(audit_problem, recorded, uncertainty, decision_dual=decision.dual,
                               dual_iterations=dual_iterations)
    worst_case_ms = (time.perf_counter() - clock_start) * 1000.0

    clock_start = time.perf_counter()
    warm = solve(audit_problem, warm_start=recorded)
    warm_ms = (time.perf_counter() - clock_start) * 1000.0

    delta_cost = np.asarray(audit_problem.cost_vector(), dtype=float) - \
        np.asarray(decision_problem.cost_vector(), dtype=float)
    radius = stability_radius(decision_problem, recorded, direction=delta_cost,
                              upper_limit=10.0) if np.any(delta_cost) else None
    lower, upper = decision_problem.bounds()
    at_bound = np.isclose(recorded, lower, atol=1e-6) | np.isclose(recorded, upper, atol=1e-6)

    audit_record = {
        "weights": [float(value) for value in recorded],
        "multipliers": [list(decision.dual.alpha), list(decision.dual.beta),
                        list(decision.dual.gamma), float(decision.dual.nu)],
        "problem_digest": decision_problem.digest(),
        "stage_of_audit": event["audit_vintage"],
        "cost_shift": delta_cost.tolist(),
    }
    return {
        "cohort": cohort,
        "period": event["period"],
        "decision_vintage": event["decision_vintage"],
        "audit_vintage": event["audit_vintage"],
        "split": event["split"],
        "category": event["category"],
        "changed_inputs": event["changed_inputs"],
        "revision_index": event["revision_index"],
        "delta_growth_l2": event["delta_growth_l2"],
        "delta_cost_l2": float(np.linalg.norm(delta_cost)),
        "delta_cost_on_decision": float(abs(delta_cost @ recorded)),
        "regret": float(regret),
        "regret_conservative": float(regret_conservative),
        "resolution": float(resolution),
        "material": bool(regret > TAU),
        "verdict": certificate.verdict,
        "bound": None if bound is None else float(bound),
        "bound_algebraic": None if algebraic is None else float(algebraic),
        "certified_immaterial": bool(bound is not None and bound <= TAU),
        "stable": stable,
        "taylor": float(taylor["estimate"]),
        "strong_convexity": None if not strong["valid"] else float(strong["bound"]),
        "worst_case": float(worst.bound) if (worst.actionable and worst.bound is not None)
        else None,
        "active_set": bool(np.all(at_bound)) if at_bound.size else False,
        "binding": int(sum(np.isclose(recorded, lower, atol=1e-6) |
                           np.isclose(recorded, upper, atol=1e-6))),
        "radius": None if radius is None else float(radius.radius),
        "condition": float(np.linalg.cond(decision_problem.matrix())),
        "weights": [float(value) for value in recorded],
        "cost_decision": cost_decision.tolist(),
        "cost_audit": cost_audit.tolist(),
        "timing": {"decision_ms": decision_ms, "compile_ms": compile_ms,
                   "certificate_ms": certificate_ms, "internal_ms": internal_ms,
                   "external_ms": external_ms, "warm_ms": warm_ms,
                   "active_set_ms": active_set_ms, "worst_case_ms": worst_case_ms,
                   "verify_warm_improved": bool(float(warm.objective) <= float(internal.objective) + 1e-12)},
        "storage": {"audit_record_bytes": serialise_size(audit_record),
                    "problem_bytes": serialise_size(audit_problem.as_dict()),
                    "certificate_bytes": serialise_size(certificate.as_dict())},
        "claims": certificate.claims.get("made", []),
    }


def method_table(rows: Sequence[dict[str, Any]], tau: float) -> dict[str, Any]:
    """Accuracy of each method's material/immaterial claim against re-solving."""

    def summarise(name: str, claims_material: list[bool | None]) -> dict[str, Any]:
        pairs = [(claim, row["material"]) for claim, row in zip(claims_material, rows)
                 if claim is not None]
        if not pairs:
            return {"method": name, "events": 0}
        correct = sum(1 for claim, truth in pairs if claim == truth)
        tp = sum(1 for claim, truth in pairs if claim and truth)
        fp = sum(1 for claim, truth in pairs if claim and not truth)
        fn = sum(1 for claim, truth in pairs if not claim and truth)
        return {"method": name, "events": len(pairs),
                "accuracy": correct / len(pairs),
                "precision_material": (tp / (tp + fp)) if (tp + fp) else None,
                "recall_material": (tp / (tp + fn)) if (tp + fn) else None,
                "false_immaterial": fn,
                "material_share": sum(1 for _, truth in pairs if truth) / len(pairs)}

    cri_claims, cri_known = [], []
    for row in rows:
        if row["bound"] is None:
            cri_claims.append(None)
            cri_known.append(None)
        else:
            cri_claims.append(bool(row["bound"] > tau))
            cri_known.append(bool(row["bound"] > tau))
    taylor_claims = [bool(abs(row["taylor"]) > tau) for row in rows]
    strong_claims = [None if row["strong_convexity"] is None
                     else bool(row["strong_convexity"] > tau) for row in rows]
    worst_claims = [None if row["worst_case"] is None
                    else bool(row["worst_case"] > tau) for row in rows]
    return {
        "cri": summarise("CRI (certificate bound)", cri_claims),
        "cri_certified_only": summarise("CRI (certified immaterial, else unknown)",
                                        [None if (row["bound"] is None or row["bound"] > tau)
                                         else False for row in rows]),
        "active_set": summarise("active-set stability (KKT holds -> immaterial)",
                                [False if row["stable"] else None for row in rows]),
        "taylor": summarise("first-order estimate", taylor_claims),
        "strong_convexity": summarise("strong-convexity bound", strong_claims),
        "worst_case": summarise("CRI-U worst case over the declared set", worst_claims),
        "no_recompute": summarise("no recomputation (assert zero regret)", [False] * len(rows)),
    }


def feature_table(rows: Sequence[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Three predictor sets: revision size alone, size plus revision metadata, then geometry.

    The middle set is what a data steward knows without solving anything (how many inputs moved, which
    release it was, whether it is a benchmark); the third adds the decision geometry the certificate
    already computes. Comparing the two answers the question the protocol asks: does metadata carry
    information beyond the size of the correction?
    """

    magnitude = np.array([[row["delta_cost_l2"]] for row in rows])
    metadata = np.array([[row["delta_cost_l2"],
                          len(row["changed_inputs"]),
                          row["revision_index"],
                          1.0 if row["category"] == "annual_benchmark_window" else 0.0,
                          row["delta_growth_l2"]] for row in rows])
    geometry = np.array([[
        row["delta_cost_l2"],
        row["delta_cost_on_decision"],
        len(row["changed_inputs"]),
        row["binding"],
        row["condition"],
        1.0 if row["radius"] is not None else 0.0,
        0.0 if row["radius"] is None else math.log1p(row["radius"]),
        row["delta_growth_l2"],
    ] for row in rows])
    return magnitude, metadata, geometry


def standardise_features(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = train.mean(axis=0)
    scale = train.std(axis=0, ddof=1)
    scale = np.where(scale > 0, scale, 1.0)
    return (train - mean) / scale, (other - mean) / scale


def analyse_cohort(cohort: dict[str, Any]) -> dict[str, Any]:
    key = cohort["cohort"]
    labels = cohort["labels"]
    events = cohort["events"]
    train = [event for event in events if event["split"] == "train"]
    pilot = [event for event in events if event["split"] == "pilot"]
    test = [event for event in events if event["split"] == "test"]
    block = calibration(train, labels)
    rho, shares = choose_rho(train, key, labels, block)
    print(f"[{key}] rho={rho} interior shares={shares}", flush=True)

    # Half-widths for the uncertainty set: one standard deviation of the train-split revision of the
    # *standardised* cost, computed from decisions to their own audit vintages.
    train_deltas = []
    for event in train:
        train_deltas.append(np.abs(standardise(event["growth_audit"], block)
                                   - standardise(event["growth_decision"], block)))
    width = np.asarray(train_deltas, dtype=float)
    block["half_width"] = width.mean(axis=0).tolist() if width.size else [0.0] * len(labels)

    rows = []
    for event in events:
        row = run_event(event, key, labels, block, rho)
        if row is not None:
            rows.append(row)
    test_rows = [row for row in rows if row["split"] == "test"]
    pilot_rows = [row for row in rows if row["split"] == "pilot"]
    train_rows = [row for row in rows if row["split"] == "train"]

    material = [row["material"] for row in test_rows]
    years = [row["decision_vintage"][:4] for row in test_rows]
    material_interval = clustered_interval([1.0 if flag else 0.0 for flag in material], years)

    certified = [1.0 if row["certified_immaterial"] else 0.0 for row in test_rows]
    certified_interval = clustered_interval(certified, years)
    nonzero = [row for row in test_rows if row["delta_cost_l2"] > 0]
    immaterial_nonzero = [row for row in nonzero if not row["material"]]
    certified_immaterial = [row for row in immaterial_nonzero if row["certified_immaterial"]]

    magnitude_train, metadata_train, geometry_train = feature_table(train_rows)
    magnitude_test, metadata_test, geometry_test = feature_table(test_rows)
    label_train = np.array([1.0 if row["material"] else 0.0 for row in train_rows])
    label_test = np.array([1.0 if row["material"] else 0.0 for row in test_rows])
    auc_magnitude = auc(magnitude_test[:, 0].tolist(), label_test.astype(bool).tolist())

    def fitted(train_features: np.ndarray, test_features: np.ndarray) -> np.ndarray | None:
        if not len(train_rows) or not len(test_rows):
            return None
        train_scaled, test_scaled = standardise_features(train_features, test_features)
        beta = logistic_fit(train_scaled, label_train)
        return logistic_score(test_scaled, beta)

    scores_magnitude = fitted(magnitude_train, magnitude_test)
    scores_metadata = fitted(metadata_train, metadata_test)
    scores_geometry = fitted(geometry_train, geometry_test)
    auc_magnitude_model = (auc(scores_magnitude.tolist(), label_test.astype(bool).tolist())
                           if scores_magnitude is not None else None)
    auc_metadata_model = (auc(scores_metadata.tolist(), label_test.astype(bool).tolist())
                          if scores_metadata is not None else None)
    auc_geometry_model = (auc(scores_geometry.tolist(), label_test.astype(bool).tolist())
                          if scores_geometry is not None else None)

    category_stats: dict[str, dict[str, Any]] = {}
    for row in test_rows:
        entry = category_stats.setdefault(row["category"], {"events": 0, "material": 0})
        entry["events"] += 1
        entry["material"] += int(row["material"])

    timing = {}
    for name in ("decision_ms", "compile_ms", "certificate_ms", "internal_ms", "external_ms",
                 "warm_ms", "active_set_ms", "worst_case_ms"):
        values = [row["timing"][name] for row in test_rows]
        timing[name] = {"median": float(np.median(values)) if values else None,
                        "mean": float(np.mean(values)) if values else None}
    storage = {}
    for name in ("audit_record_bytes", "problem_bytes", "certificate_bytes"):
        values = [row["storage"][name] for row in test_rows]
        storage[name] = {"median_bytes": float(np.median(values)) if values else None}

    return {
        "cohort": key,
        "name": cohort["name"],
        "series": cohort["series"],
        "labels": labels,
        "rho": rho,
        "rho_interior_shares": shares,
        "tau": TAU,
        "counts": {"events": len(events), "train": len(train), "pilot": len(pilot),
                   "test": len(test), "processed_test": len(test_rows),
                   "processed_train": len(train_rows),
                   "dropped": len(test) - len(test_rows)},
        "materiality": {
            "share": float(np.mean(material)) if material else None,
            "interval": material_interval,
            "material_events": int(sum(material)),
            "immaterial_events": int(len(material) - sum(material)),
            "nonzero_revision_share": (len(nonzero) / len(test_rows)) if test_rows else None,
        },
        "certification": {
            "share_certified_immaterial": float(np.mean(certified)) if certified else None,
            "interval": certified_interval,
            "immaterial_with_nonzero_revision": len(immaterial_nonzero),
            "certified_of_those": len(certified_immaterial),
            "certified_share_of_immaterial_nonzero": (
                len(certified_immaterial) / len(immaterial_nonzero)) if immaterial_nonzero else None,
        },
        "methods": method_table(test_rows, TAU),
        # Does the certificate say anything the classical active-set test does not? On this data the
        # answer is checkable directly: compare the certified set with the KKT-stable set.
        "agreement": {
            "certified_and_stable": int(sum(1 for row in test_rows
                                            if row["certified_immaterial"] and row["stable"])),
            "certified_not_stable": int(sum(1 for row in test_rows
                                             if row["certified_immaterial"] and not row["stable"])),
            "stable_not_certified": int(sum(1 for row in test_rows
                                             if row["stable"] and not row["certified_immaterial"])),
            "test_events": len(test_rows),
        },
        "tightness": {
            "median_bound_over_regret_material": (
                float(np.median([row["bound"] / row["regret"] for row in test_rows
                                 if row["material"] and row["bound"] is not None]))
                if any(row["material"] and row["bound"] is not None for row in test_rows) else None),
            "median_bound_material": (
                float(np.median([row["bound"] for row in test_rows
                                 if row["material"] and row["bound"] is not None]))
                if any(row["material"] and row["bound"] is not None for row in test_rows) else None),
            "median_bound_immaterial": (
                float(np.median([row["bound"] for row in test_rows
                                 if not row["material"] and row["bound"] is not None]))
                if any(not row["material"] and row["bound"] is not None for row in test_rows) else None),
        },
        "prediction": {
            "auc_magnitude_only": auc_magnitude,
            "auc_magnitude_model": auc_magnitude_model,
            "auc_metadata_model": auc_metadata_model,
            "auc_geometry_model": auc_geometry_model,
            "gain_metadata_over_magnitude": (None if (auc_magnitude_model is None
                                                      or auc_metadata_model is None)
                                             else auc_metadata_model - auc_magnitude_model),
            "gain_geometry_over_metadata": (None if (auc_metadata_model is None
                                                     or auc_geometry_model is None)
                                            else auc_geometry_model - auc_metadata_model),
            "auc_geometry_interval": clustered_auc_interval(
                (scores_geometry if scores_geometry is not None else np.zeros(0)).tolist(),
                label_test.astype(bool).tolist(), years),
            "train_events": len(train_rows), "test_events": len(test_rows),
            "model": ("ridge logistic regression (l2=1) fitted on the train split, scored on test; "
                      "AUC is rank-based and ties count one half"),
        },
        "categories": category_stats,
        "timing_ms": timing,
        "storage": storage,
        "pilot": {
            "events": len(pilot_rows),
            "material_share": (float(np.mean([row["material"] for row in pilot_rows]))
                               if pilot_rows else None),
        },
        "rows": rows,
    }


def sensitivity_grid(dataset: dict[str, Any]) -> dict[str, Any]:
    """Prespecified secondary grid: risk weight and materiality threshold."""

    results: dict[str, Any] = {}
    for cohort in dataset["cohorts"]:
        key = cohort["cohort"]
        labels = cohort["labels"]
        events = [event for event in cohort["events"] if event["split"] in {"train", "test"}]
        train = [event for event in events if event["split"] == "train"]
        block = calibration(train, labels)
        deltas = [np.abs(standardise(event["growth_audit"], block)
                         - standardise(event["growth_decision"], block)) for event in events]
        block["half_width"] = np.asarray(deltas).mean(axis=0).tolist()
        grid = {}
        for rho in (0.02, 0.05, 0.2, 1.0):
            rows = [run_event(event, key, labels, block, rho) for event in events]
            rows = [row for row in rows if row is not None and row["split"] == "test"]
            if not rows:
                continue
            grid[f"rho={rho:g}"] = {
                "events": len(rows),
                "materiality": {
                    f"tau={tau:g}": float(np.mean([row["regret"] > tau for row in rows]))
                    for tau in (1e-2, 1e-3, 1e-4)},
                "certified_immaterial": {
                    f"tau={tau:g}": float(np.mean([row["bound"] is not None and row["bound"] <= tau
                                                   for row in rows]))
                    for tau in (1e-2, 1e-3, 1e-4)},
            }
        results[key] = grid
    return results


def main() -> None:
    dataset = load_dataset()
    payload: dict[str, Any] = {
        "schema": "atlas.rtds.study.v1",
        "preregistration": "docs/research/rtds/PREREGISTRATION.md",
        "tau": TAU,
        "cohorts": [],
    }
    for cohort in dataset["cohorts"]:
        result = analyse_cohort(cohort)
        payload["cohorts"].append(result)
        print(f"[{cohort['cohort']}] test events={result['counts']['processed_test']} "
              f"materiality={result['materiality']['share']} "
              f"certified={result['certification']['share_certified_immaterial']}", flush=True)
    payload["sensitivity"] = sensitivity_grid(dataset)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"wrote {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
