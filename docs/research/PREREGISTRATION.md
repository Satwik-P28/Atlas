# Preregistration: Certified Revision Impact (CRI)

**Status.** Parameters below were fixed in `CONFIG` in
`scripts/research/cri_experiment.py` before the reported results were produced, and were not
tuned against them. The disclosure section records exactly what changed after the first run
and why, because pretending that no implementation changed would be false.

---

## 1. Hypotheses

**H1 (soundness).** For every revision event, the duality-gap certificate computed from the
recorded decision's multiplier vector is at least the realized regret of that decision under
the corrected program.

*Falsifier:* any event where `bound + 1e-12 < realized_regret`. A single violation falsifies
the claim as stated.

**H2 (exactness).** When the exact KKT certificate reports optimality for the corrected
program, the realized regret is zero up to floating-point noise.

*Falsifier:* any certified event with realized regret above `1e-9`.

**H3 (usefulness).** A small, bounded number of dual ascent steps from the recorded
multipliers closes most of the gap between the free bound and the realized regret.

*Falsifier:* the 5-step bound's median tightness ratio is not materially closer to 1 than the
0-step bound's.

**H4 (value of provenance).** Applying revisions regardless of their publication time changes
the audit conclusion.

*Falsifier:* the hindsight arm and the honest arm produce the same stability rate.

**H5 (conditionality).** The guarantee fails when the declared sensitivity understates the
true revision, and the failure rate increases as the understatement grows.

*Falsifier:* violation rate flat at 0 across all misspecification levels.

**H6 (non-vacuity of the competitor comparison).** The strong-convexity bound is a valid but
looser competitor; a first-order Taylor estimate of the objective change is not a bound and
understates regret on a non-trivial fraction of events.

*Falsifier:* Taylor estimate sound in ≥ 99% of events.

---

## 2. Design

| Element | Fixed choice |
|---|---|
| Assets per problem | 6 |
| Return process | 3-factor linear model plus idiosyncratic noise, fixed loadings per seed |
| Estimation window | 250 trailing sessions |
| Rebalances per seed | 120 |
| Risk aversion | 5.0 |
| Position cap (primary) | 0.25 |
| Seeds | 101, 102, 103, 104, 105 |
| Estimator | Ledoit-Wolf shrinkage, analytic intensity |
| Revisions per event | 1–3 inputs, magnitude `N(0, (3·s.e.)²)` per revised input, where `s.e.` is the standard error of the trailing mean being corrected |
| Decision clock | `2024-06-28T20:30:00Z` |
| Audit clock | `2024-07-02T12:00:00Z` |
| Primary tolerance for "bounded and useful" | `1e-4` absolute objective units |
| Bootstrap | moving block, block 12, 1500 resamples, seed 424242 |
| Misspecification factors | declared revision = true revision / {1, 2, 5, 10} |
| Scaling sizes | n ∈ {8, 16, 32, 64, 128} |

Revisions are tied to the standard error of the estimate they correct rather than to an
arbitrary constant, so the perturbation scale has a statistical meaning.

## 3. Arms (all reported, including failures)

| Arm | Description |
|---|---|
| `zero_regret_certificate` | Exact KKT test on the corrected program; no optimisation |
| `bounded_within_tolerance` | Exact or duality bound ≤ `1e-4` |
| `warm_bound` | Duality bound from the recorded multipliers, **zero** dual iterations |
| `warm5_bound` | Duality bound after 5 dual ascent iterations from the recorded multipliers |
| `cold_bound` | Duality bound from a cold start, up to 200 iterations |
| `convex_bound` | `‖∇f(w)‖²/(2·λ_min(Q))`, a valid competing bound |
| `taylor_estimate` | `(c_new − c_old)·w`, a widely used *estimate*, not a bound |
| `full_recompute` | Re-solve; supplies the ground-truth regret and the cost comparator |
| `hindsight` | Audit a decision recomputed with the later evidence (leakage diagnostic) |

No arm is excluded from reporting. The append-only ledger
(`artifacts/research/cri_ledger.jsonl`) records each arm that executed.

## 4. Analysis plan

* Rates reported with moving-block bootstrap intervals over **events**, not over seeds.
* Regression and tightness never aggregated over zero-regret events with a `1e-15` floor, as
  that manufactures enormous ratios from floating-point noise; tightness is conditioned on
  `realized_regret > 1e-10`.
* No hypothesis test is used on the dependent series. Intervals are reported and the reader is
  asked to judge overlap.
* The cap sweep and the misspecification sweep are exploratory; they are labelled as such and
  were not used to select any parameter.

## 5. Disclosure of post-hoc changes

The first execution of the experiment exposed implementation defects. All were corrected
before the reported run, and each is a correctness fix rather than a change to the analysis
plan. They are listed here because a reader is entitled to know that the reported numbers come
from code that was debugged against intermediate output.

| Defect | Symptom | Correction |
|---|---|---|
| Sign of the dual ν gradient | Every dual solver terminated at iteration 0 | Finite-difference check isolated it; the gradient is `1'w − b` |
| Sign in the dual objective value | Reported dual exceeded the primal, violating weak duality | Quadratic term is `+0.5·r'w` given `w = −Q⁻¹r` |
| Sign of the β gradient | Dual ascent diverged to `-inf` by overflow | `w − upper`, not `upper − w` |
| Single-signed ν column in the multiplier recovery | Optimal corner solutions rejected as non-optimal | ν split into `ν⁺ − ν⁻`; exact-optimum recall went from 60% to 100% |
| Least-squares null-space representative | Negative multiplier at an optimal point | Non-negative feasibility LP over the stationarity system |
| Objective scaling | A 2.6e6-objective capacity program stopped with a `3e-7` budget residual and was reported infeasible | Objective divided by a positive constant, multipliers scaled back |
| Clamping a negative bound to zero | A violated bound was reported as a comfortable zero | The bound is refused and the reason recorded |

Two further corrections were conceptual rather than numerical:

* **Two clocks.** The original compiler used the decision clock as the eligibility cutoff for
  the corrected program, which excludes exactly the revisions an audit exists to evaluate. The
  compiler now takes a separate audit clock.
* **Verdict semantics.** "A bound exists" and "the bound is small" were previously conflated
  in one verdict. They are now separate (`regret_bounded` plus `meets_tolerance`).

Neither change alters a hypothesis. Both change what the code measures, so the reported run
post-dates them.

## 6. What this preregistration does not cover

* Real market data. No licensed price or filing archive is available in this environment; the
  financial experiment is synthetic and is labelled as such everywhere.
* Any claim about out-of-sample investment performance. The branch measures audit coverage and
  bound tightness, not returns.
* Hyperparameter tuning. No parameter was selected by search over the reported events.
