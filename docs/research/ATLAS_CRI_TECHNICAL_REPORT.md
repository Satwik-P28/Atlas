# Certified Revision Impact: bounding the regret of decisions taken under superseded evidence

**Technical report — research branch `review/decision-intelligence-cri`, November 2026.**

This is a working research report, not a peer-reviewed publication. It reports what was
implemented, what was measured, and what failed. Every number in §6 is produced by
`scripts/research/cri_experiment.py`; the machine-readable record is
`artifacts/research/cri_results.json` and the generated tables are
`artifacts/research/cri_report.md`.

---

## 1. Abstract

Financial and operational decisions are computed from evidence that later turns out to be
incomplete. When an input is corrected, the usual responses are to re-run the model or to
ignore the correction. Both are unsatisfying for an audit: re-running answers a question about
*today's* model, while ignoring the correction gives no assurance at all.

We define and implement **Certified Revision Impact (CRI)**: given a decision recorded at time
`t` under a convex program, and evidence that has become public by a later audit time `τ`, we
ask what can be *proved* about the regret of that recorded decision under the corrected
program, without re-solving it. Two certificates are produced. An **exact** certificate
recovers a Lagrange multiplier vector from the recorded weights by a non-negative feasibility
problem; if it satisfies the KKT system of the corrected program, the regret is exactly zero.
A **bounded** certificate exploits the fact that the dual feasible set does not depend on the
linear costs, so the multiplier vector recorded with the decision remains feasible for the
corrected program; one Cholesky solve then yields a valid regret bound, and a handful of dual
ascent steps tighten it.

On 598 seeded revision events, no bound ever understated realized regret; every decision that
received the exact certificate had realized regret at most `1.7e-17`; the zero-cost bound was
loose by a median factor of 24 while five dual ascent steps recovered the realized regret
exactly (ratio 1.00); and the guarantee degraded in a measurable way — 0% to 45% violations —
as the declared revision was shrunk to one tenth of the true revision. Exact certification
covered 41% of events and depended strongly on whether position limits were active.

The mathematical ingredients are classical: weak duality, KKT sufficiency, and support-set
invariancy analysis. The contribution claimed here is a problem formulation, a composition that
makes one of the certificates free, and an empirical characterisation that includes the
conditions under which the method fails. We do not claim a new theorem.

## 2. Introduction

A point-in-time research system exists to answer "what was knowable, and when". Atlas already
enforces that for *evidence*: `docs/PRICE_TEMPORAL_SEMANTICS_PASS.md` records how a filing
whose acceptance timestamp falls after the final selected session's close cannot be used to
explain that session's move. This branch applies the same discipline one level up, to
**decisions**.

Consider a portfolio rebalance computed on 28 June from the trailing 250 sessions, and a vendor
correction published on 2 July. Three questions are possible:

1. *What would the model allocate today?* — a re-solve. Easy, and it is not an audit.
2. *How much did the objective change at the old weights?* — the first-order estimate
   `(c_new − c_old)·w`. Widely used, and **not a bound**: §6.3 measures it understating the
   realized regret in 23% of events.
3. *Was the decision that was actually taken optimal given what we now know, and if not, how
   much did that cost?* — the question this report answers.

Question 3 has a property the others lack: it has a definite answer that can be certified with
linear algebra, because the decision is fixed and only the program changes.

## 3. Research question

> For a recorded decision `w` of a convex program `P(c)` solved at time `t`, and a corrected
> linear cost vector `c'` derived from evidence public at audit time `τ ≥ t`, can we certify
> `regret(w) = f_{c'}(w) − min f_{c'}` without solving `P(c')`, and can we bound it when the
> answer is no?

Three sub-questions are answered empirically: how often the exact certificate succeeds (§6.2),
how tight the cheap bound is (§6.3), and how the guarantee fails when its declared premise is
violated (§6.5).

## 4. Problem definition

### 4.1 Canonical program

```
minimize     0.5 · w' Q w + c' w
subject to   1'w = b                        dual ν  (free)
             l_i <= w_i <= u_i              duals α, β >= 0
             A_j w <= d_j                   duals γ >= 0
```

with `Q` symmetric positive semidefinite. Mean-variance allocation is the instance
`Q = λΣ`, `c = −μ`; capacity allocation is `Q = λΣ_demand`, `c = −margin`. The solver requires
`Q ≻ 0` for a finite dual bound and says so when it is not.

### 4.2 Evidence revision as a declared perturbation

A revision `r` is a tuple `(evidence_id, input_key, δ, available_at, source_id, kind)`. It is
compiled into a cost perturbation through a **declared** linear sensitivity `s_k`:

```
c' = c + Σ_{r applied} δ_r · s_{input(r)}
```

The sensitivity is an explicit modelling assumption, not an estimate. A revision whose `kind`
is not `linear_objective` (for example a covariance revision) is **refused**, with the reason
recorded, because a risk-matrix change is a different mathematical object and pretending a
linear-cost perturbation covers it would be a silent substitution.

### 4.3 Two clocks

A revision audit is a statement about a past decision evaluated with present evidence, so two
clocks are recorded:

* `decision_as_of` — when the decision was taken. Evidence later than this **could not** have
  influenced it.
* `audit_as_of` — when the audit is run. Evidence later than this **cannot** be used even in
  the corrected program.

Collapsing the two is a real error in either direction. Using the decision clock as the
eligibility cutoff excludes exactly the revisions the audit exists to evaluate; using neither
lets a not-yet-public revision into the corrected program. §6.6 measures the cost of getting
this wrong.

## 5. Method

### 5.1 The dual, and why the bound is free

The Lagrangian dual of §4.1 is a concave quadratic in `(ν, α, β, γ)`:

```
g(ν,α,β,γ) = 0.5 · r'w − ν b + α'l − β'u − γ'd,     w = −Q⁻¹ r,
r           = c + ν1 − α + β + A'γ
```

with `α, β, γ ≥ 0`. Evaluating `g` is one Cholesky solve.

**Proposition 1 (weak-duality bound).** For any `α, β, γ ≥ 0` and any `ν`,
`g(ν,α,β,γ) ≤ min f`, hence `f(w) − g ≤ regret(w)`.

*Proof.* For any feasible `w`, `g(ν,α,β,γ) ≤ L(w,ν,α,β,γ) = f(w) + ν(1'w − b) − α'(w−l) +
β'(w−u) + γ'(Aw−d) ≤ f(w)`, using `1'w = b`, `w ≥ l`, `w ≤ u`, `Aw ≤ d` and the sign
constraints. Take the minimum over feasible `w`. ∎

**Proposition 2 (the dual feasible set is cost-independent).** The set
`{(ν,α,β,γ) : α,β,γ ≥ 0}` does not depend on `c`. Therefore a multiplier vector recorded with
the decision at time `t` is feasible for the corrected program at `τ`, and its dual value is
finite.

*Proof.* `c` enters `g` only through `r`, and `r` enters only the value, not the domain. ∎

Proposition 2 is the reason the zero-iteration certificate costs one linear solve rather than
an optimisation. It is the practical core of the method, and it is a direct consequence of the
dual's structure rather than a new idea.

### 5.2 Exact certificate

Given recorded weights `w`, stationarity is *linear* in the multipliers once the active set is
fixed:

```
ν1 − α + β + A'γ = −(Qw + c),    α, β, γ ≥ 0
```

The certificate solves this as a non-negative feasibility problem (with `ν = ν⁺ − ν⁻`), then
verifies the full KKT system: primal feasibility, stationarity, dual feasibility, and
complementarity, each reported as a residual against a relative tolerance.

**Proposition 3 (exactness).** For the convex program of §4.1, KKT is necessary and sufficient
for global optimality; linear constraints satisfy the constraint qualification. Hence a
satisfied KKT report certifies `regret(w) = 0` for the specified program.

*Proof.* Standard; see Boyd & Vandenberghe, §5.5.3. Convexity gives sufficiency, and the
linearity of the constraints gives Abadie's constraint qualification, hence necessity. ∎

The exact test is `O(n²)` linear algebra with no optimisation. Its weakness is that it is a
*sufficient* test: a negative answer proves nothing, and §6.2 shows it is silent whenever the
active set changes — including when the change is numerically negligible.

### 5.3 Bounded certificate and warm start

Combining Propositions 1 and 2: `bound₀ = f_{c'}(w) − g_{c'}(ν_t, α_t, β_t, γ_t)` where the
multipliers are those recorded at decision time. This is valid with **zero** dual iterations.
Running `k` L-BFGS-B iterations from that point gives `bound_k ≤ bound₀`. Because any iterate
is projected onto `α, β, γ ≥ 0` before evaluation, every intermediate value is a valid bound —
a failed line search degrades tightness, never soundness. In `solve()` the same property makes
the solver self-certifying: the reported duality gap is an upper bound on suboptimality even
when the primal solver's status flag is `success=False`.

### 5.4 Radii

**Proposition 4 (invariance radius is an interval).** Along a ray `c(r) = c + r·d`, the set
`{r ≥ 0 : w remains optimal for P(c(r))}` is a closed interval containing `0`.

*Proof.* With `w` fixed, the KKT system of §5.2 is a finite system of linear equalities and
inequalities in `(r, multipliers)`. Its solution set is a polyhedron; the projection of a
polyhedron onto one coordinate is an interval; `r = 0` is feasible by assumption. ∎

**Proposition 5 (regret is convex in the radius).** `G(r) = f_{c(r)}(w) − V*(c(r))` is convex
in `r ≥ 0`, with `G(0) = 0`.

*Proof.* `V*(c) = min_w f_c(w)` is a pointwise minimum of affine functions of `c`, hence
concave in `c`. `c(r)` is affine in `r`, so `V*(c(r))` is concave in `r`. `f_{c(r)}(w)` is
affine in `r` for fixed `w`. Affine minus concave is convex. ∎

Proposition 5 licenses bisection for the tolerance radius `r_ε = sup{r : G(r) ≤ ε}`; without
convexity, bisection on a non-monotone function would be unjustified. Proposition 4 licenses
bisection for the exact invariance radius. Both are implemented and tested
(`tests/test_decision_certificate.py`).

## 6. Experiments

### 6.1 Design

Synthetic three-factor return panel, 250-session trailing window, 120 rebalances per seed, five
seeds, 6 assets, 25% position cap, risk aversion 5, Ledoit-Wolf covariance. A revision touches
one to three inputs with magnitude drawn from `N(0, (3·s.e.)²)` where `s.e.` is the standard
error of the estimate being corrected, so the perturbation scale is statistically meaningful
rather than arbitrary. Decision clock `2024-06-28T20:30:00Z`, audit clock
`2024-07-02T12:00:00Z`. Full parameter list: `docs/research/PREREGISTRATION.md`.

The data are **synthetic** and labelled as such in every artifact. No licensed market data is
available in this environment.

### 6.2 Soundness, exactness and coverage

598 events, 0 skipped, 0 bound violations in any arm.

| Metric | Value | 95% moving-block interval |
|---|---|---|
| Exact zero-regret certificate | 0.413 | [0.373, 0.453] |
| Certified or bounded within `1e-4` | 0.425 | [0.383, 0.468] |
| Warm bound (0 iterations) sound | 1.000 | [1.000, 1.000] |
| Warm bound (5 iterations) sound | 1.000 | [1.000, 1.000] |
| Cold bound sound | 1.000 | [1.000, 1.000] |
| Strong-convexity bound sound | 1.000 | [1.000, 1.000] |
| First-order Taylor estimate sound | 0.774 | [0.741, 0.809] |

Realized regret of events that received the exact certificate: **maximum 1.68e-17**, p95 below
`9.4e-18` in every seed. The exact certificate is therefore exact in practice, not an artifact
of a loose tolerance.

Realized regret overall: median `4.07e-05`, p95 `7.12e-04`, maximum `1.35e-03`.

### 6.3 Tightness of the bounds

Restricted to the 351 events with non-zero realized regret (a ratio against `1e-15` noise
manufactures meaningless numbers; an earlier version of the analysis did exactly that and the
correction is recorded in the preregistration disclosure).

| Bound | Median bound/regret | p90 |
|---|---|---|
| Duality, 0 dual iterations (free) | 24.14 | 162.94 |
| Duality, 5 dual iterations | 1.00 | 1.00 |
| Duality, cold start, 200 iterations | 1.00 | 1.00 |
| Strong convexity, `‖∇f‖²/(2λ_min)` | 33.08 | 357.64 |

Two readings matter. First, the free certificate is *valid but loose*: a factor of 24 is not a
useful number to report to a decision-maker, which is why the k-step variant exists. Second,
five dual ascent steps recover the exact regret. That is expected — at the dual optimum the gap
equals the regret by construction — and it means the interesting question is not "can we get a
tight bound" but "how few iterations and how little information does a useful bound require".

The strong-convexity bound is valid and consistently looser. It does not vanish at a
constrained optimum, because the gradient there is balanced by multipliers rather than zero.
This is a property of the bound, not a defect in its implementation, and it is asserted as a
test.

The first-order Taylor estimate is not a bound and understates the realized regret in 23% of
events. It is included because it is a common surrogate for "impact" in reporting systems, and
the measurement is the argument against using it as one.

### 6.4 Where exact certification comes from

Exact certification requires the active set and multipliers to survive the perturbation
unchanged.

| Position cap | Exact certificate rate | Weights changed | Max realized regret when certified |
|---|---|---|---|
| 0.18 | 0.525 | 0.475 | 1.3e-18 |
| 0.22 | 0.400 | 0.600 | 1.1e-18 |
| 0.25 | 0.525 | 0.475 | 3.9e-18 |
| 0.35 | 0.350 | 0.650 | 4.3e-19 |
| 0.50 | 0.275 | 0.725 | 3.0e-18 |
| 1.00 | 0.425 | 0.575 | 2.7e-18 |

The pattern is not monotone and the explanation is mechanical: an interior optimum moves
continuously with the cost vector, so its exact invariance radius is zero (Proposition 4's
sharp case), while a solution pressed against caps and floors frequently does not move at all
when a coefficient changes slightly. Certification is therefore a statement about a *corner*
solution, and it is silent for interior ones. The last column confirms the certificate is not
being granted to near-optimal points: the worst realized regret among certified events is
`4e-18` across every cap.

### 6.5 Failure under a violated premise

The guarantee is conditional on the declared sensitivity. Declaring a revision smaller than it
actually was should break the bound, and it does, monotonically:

| Declared revision as a fraction of the true revision | Bound violation rate | Median realized/bound |
|---|---|---|
| 1.00 | 0.000 | 0.01 |
| 0.50 | 0.050 | 0.05 |
| 0.20 | 0.225 | 0.21 |
| 0.10 | 0.450 | 0.78 |

This is the most important limitation in the report. The certificate is not "safe by default";
it is safe *given a correct declaration*, and a system that records the declaration alongside
the decision can be audited for it.

### 6.6 The provenance ablation

The hindsight arm audits a decision that was recomputed with the later evidence and then
evaluated against that same evidence. It reports apparent stability 100% of the time; the
honest arm, auditing the decision that was actually taken, reports 52.5%. Mean regret of the
actual decision in this arm was `6.08e-04`.

This is the quantitative form of the argument for the two-clock model: an evaluation that does
not fix the decision clock will certify every decision as stable, because it is measuring a
decision that was constructed to be optimal for the evidence it is judged against.

### 6.7 Degeneracy

With two assets correlated at 0.995 (risk matrix positive definite, hence a dual bound exists),
the eigen-based identifiability report says `unique`, yet swapping 50% of one for the other
changes the objective by only `8.98e-06` on an objective of order `1e-2`. Both allocations
receive `regret_bounded`.

With two *identical* assets (risk matrix singular, rank 3 of 4), the weights are genuinely
non-unique and — more importantly — the dual bound does not exist, because the dual function is
unbounded. The certificate then reduces to the exact KKT test alone. The honest statement is:
**value regret remains well defined under degeneracy, but the quantitative bound requires a
positive definite risk matrix, and decision-identity claims are meaningless when the optimum is
not unique.**

### 6.8 Second domain

The same certificate runs on a capacity-allocation program with linear service floors and a
group capacity cap. Across 20 margin revisions: bound sound rate 1.000, exact certificate rate
0.000, mean realized regret `1.56e-04`. Every allocation sits at a floor or the group cap, and
each revision moves it, so exact invariance never applies while the bound remains sound.

This demonstrates that the certificate layer is not written against portfolio vocabulary: it
never sees an asset, a return or a covariance. It does **not** demonstrate operational
usefulness.

### 6.9 Cost

Median wall-clock time per certificate versus a full re-solve, single-threaded, measured inside
the same process:

| n | Certificate (ms) | Re-solve (ms) | Ratio |
|---|---|---|---|
| 8 | 1.51 | 4.95 | 3.3× |
| 16 | 2.03 | 6.52 | 3.2× |
| 32 | 3.30 | 9.75 | 3.0× |
| 64 | 6.60 | 46.02 | 7.0× |
| 128 | 28.18 | 721.49 | 25.6× |

The certificate cost is dominated by the multiplier recovery and KKT verification: a
least-squares or LP solve plus `O(n²)` checks. The re-solve cost grows faster because it
includes a general-purpose solver. The advantage at small `n` is modest — at six to eight
assets a re-solve costs milliseconds, so the certificate's value there is **auditability, not
speed**. The advantage becomes material at 128 assets, and the trend is consistent with the
`O(n²)` versus super-quadratic cost structure, but only five sizes were measured and no
asymptotic claim is made.

## 7. Failure cases and negative results

1. **Interior optima are never exactly certified.** The invariance radius is zero, by
   Proposition 4. This is the largest coverage limitation (41% overall, and 27% at a 50% cap).
2. **A misspecified sensitivity breaks the bound**, up to 45% violations at a tenfold
   understatement. There is no way to detect this from the certificate alone.
3. **A singular risk matrix removes the bound entirely.** Rank-deficient covariance (common
   when the asset count exceeds the window) must be regularised before certification; the code
   refuses rather than silently regularising, but that is a real operational constraint.
4. **The free bound is not useful as a number** (median 24× the truth). It is useful as a valid
   *screen* — a bound of zero proves the decision is fine — and as a warm start.
5. **Degeneracy breaks identity claims, not value claims.**
6. **No real data.** The financial experiment is synthetic. This is the single largest threat
   to validity and is discussed in §8.
7. **The strong-convexity competitor is weak by construction.** Reporting it as the comparison
   would overstate the contribution; the honest comparison is the free versus 5-step dual
   bound, where the only difference is iteration count.

## 8. Limitations and threats to validity

* **Synthetic data.** No licensed price, filing or consensus archive is available in this
  environment. The revision process is a model of evidence correction, not a measurement of it.
  Real filing corrections are lumpier, rarer, and often larger relative to the estimate than
  the Gaussian perturbations used here.
* **Declared sensitivity.** The mapping from an input revision to a cost change is asserted. In
  a real system it would come from the forecast model's Jacobian, which is itself estimated.
  §6.5 measures the consequence of getting it wrong but does not solve it.
* **No decision-quality claim.** This branch measures audit coverage and bound tightness. It
  does not claim that certified stability improves portfolio performance, and it cannot: no
  out-of-sample return experiment was run.
* **Linearity of the revision effect.** A revision that changes the covariance, the feasible
  set or the budget is refused rather than approximated. The method covers a genuine but
  limited class of corrections.
* **Five seeds, one asset count, one estimator.** The rates in §6.2 are conditional on this
  design. The cap sweep is the only sensitivity analysis of the geometry, and it is
  exploratory.
* **Multiple comparisons.** Six arms are reported for the same 598 events; no p-values are
  claimed, and the interval for the Taylor arm should be read as descriptive.
* **Dependence.** Events share overlapping estimation windows. Intervals use a moving-block
  bootstrap with block 12; a different block length would widen or narrow them.
* **Scale.** Exponential-size problems are untested. The largest instance is 128 variables.

## 9. Reproduction

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,terminal,optimization]"
.venv/bin/python -m pytest -q                       # full suite
.venv/bin/python scripts/research/cri_experiment.py --output artifacts/research
```

The script is deterministic: seeds are fixed in `CONFIG`, no wall-clock or environment value
enters a decision, and the dataset digest is SHA-256 over the exact float64 arrays. Wall-clock
timings in §6.9 are machine-dependent and are the only non-reproducible numbers.

Environment for the reported run: Python 3.12.3, NumPy 2.5.5, SciPy 1.18.1, Linux x86-64.

## 10. References

Verified during this pass (publisher or proceedings page retrieved):

1. S. Yamao, K. Kobayashi, R. Matsui, S. Nagai, N. Nishimura, K. Nakata. *Robust
   Decision-Focused Learning via Worst-Case Regret Minimization.* UAI 2026, PMLR 337:7701–7736.
   https://proceedings.mlr.press/v337/yamao26a.html
2. N. Schutte, K. Postek, N. Yorke-Smith. *Robust Losses for Decision-Focused Learning.*
   IJCAI 2024, 4868–4875. https://www.ijcai.org/proceedings/2024/538
3. Y. P. Patel, S. Rayan, A. Tewari. *Conformal Contextual Robust Optimization.* AISTATS 2024,
   PMLR 238:2485–2493. https://proceedings.mlr.press/v238/patel24a.html
4. Y. Farhat et al. *On the Robustness of Decision-Focused Learning.* arXiv:2311.16487 (2025
   revision). https://arxiv.org/html/2311.16487
5. A. Ghaffari Hadigheh, T. Terlaky. *Sensitivity analysis in convex quadratic optimization:
   invariant support set interval.* Algorithmic Operations Research (2007).
   https://journals.lib.unb.ca/index.php/AOR/article/view/4624
6. B. Kheirfam. *Sensitivity analysis in multi-parametric strictly convex quadratic
   optimization.* Matematički Vesnik 62(2):95–107 (2010).
   http://www.emis.mi.sanu.ac.rs/EMIS/journals/MV/102/mv10201.pdf
7. F. Pacaud. *Sensitivity analysis for parametric nonlinear programming: a tutorial.* 2025
   preprint. https://optimization-online.org/wp-content/uploads/2025/04/main-1.pdf
8. P. Mohajerin Esfahani, D. Kuhn. *Data-driven distributionally robust optimization using the
   Wasserstein metric.* Mathematical Programming 171:115–166 (2018).
   https://link.springer.com/article/10.1007/s10107-017-1172-1
9. D. Bertsimas, D. den Hertog, et al. *A unified theory of robust and distributionally robust
   optimization via the primal-worst-equals-dual-best principle.* Operations Research (2023).
   https://pubsonline.informs.org/doi/10.1287/opre.2021.0268
10. Z. Fan, R. Ji, M. A. Lejeune. *Distributionally robust portfolio optimization under
    marginal and copula ambiguity.* JOTA 203:2870–2907 (2024).
    https://link.springer.com/article/10.1007/s10957-024-02550-y

Standard references cited from the literature (bibliographic details to be re-checked before
external submission):

11. A. V. Fiacco. *Introduction to Sensitivity and Stability Analysis in Nonlinear
    Programming.* Academic Press, 1983.
12. S. Boyd, L. Vandenberghe. *Convex Optimization.* Cambridge University Press, 2004.
13. A. Ben-Tal, A. Nemirovski. *Robust solutions of uncertain linear programs.* Operations
    Research Letters, 1999.
14. D. Bertsimas, D. B. Brown, C. Caramanis. *Theory and applications of robust optimization.*
    SIAM Review 53(3), 2011.
15. R. T. Rockafellar, S. Uryasev. *Optimization of conditional value-at-risk.* Journal of Risk
    2(3), 2000.
16. O. Ledoit, M. Wolf. *A well-conditioned estimator for large-dimensional covariance
    matrices.* Journal of Multivariate Analysis 88(2), 2004.
17. A. N. Elmachtoub, P. Grigas. *Smart "Predict, then Optimize".* Management Science 68(1),
    2022.

Internal contracts consumed by this work: `docs/PRICE_TEMPORAL_SEMANTICS_PASS.md`,
`docs/HISTORICAL_AVAILABILITY.md`, `ATLAS_MASTER_SPEC.md` §6 (UROS) and §7 (Temporal Evidence
Kernel).

## 11. Note on tooling

The implementation, tests, experiments and this report were produced with an AI coding
assistant operating under human direction. Every reported number is generated by the committed
script from fixed seeds and can be regenerated. The AI wrote code that contained at least six
sign and modelling defects during development, all of which are documented in the
preregistration disclosure; the corrections were found by finite-difference checks, independent
reference solvers, and weak-duality assertions rather than by inspection. Any venue submission
should disclose assistant involvement per its policy.
