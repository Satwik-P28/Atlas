# Certified Revision Impact: bounding the regret of decisions taken under incomplete, revised or uncertain evidence

**Technical report, second revision — research branch `review/decision-intelligence-cri`,
November 2026.**

This is a working research report, not a peer-reviewed publication. It reports what was
implemented, what was measured, and what failed. **Every number below is copied from
`artifacts/research/cri_tables.md`, which is generated from
`artifacts/research/cri_results.json` by `scripts/research/cri_experiment.py`.** The first
revision of this report quoted numbers that had drifted from the committed run; that failure
mode is now structurally prevented by rendering all tables from one source.

**This revision corrects two P0 errors found in review and withdraws two claims.** Section 1.1
lists what changed and why. The corrections were not cosmetic: one reversed inequality made the
elementary direction of the main proposition wrong, and one unvalidated input path could produce
a negative "regret bound".

---

## 1. Abstract

A decision is computed from evidence that later turns out to be incomplete. When an input is
corrected, the two usual responses are to re-run the model or to ignore the correction. For an
audit neither is adequate: re-running answers a question about *today's* model, and ignoring the
correction gives no assurance at all.

**Certified Revision Impact (CRI)** asks a third question. Given a decision recorded at time `t`
under a convex program, and evidence published by a later audit time `τ`, what can be *proved*
about the regret of that recorded decision under the corrected program, without re-solving it?

Two certificates are produced:

* an **exact** certificate, which recovers Lagrange multipliers from the recorded weights and
  verifies the KKT system of the corrected program, at the cost of a least-squares solve on the
  active set plus (30.4% of the time) a non-negative feasibility LP;
* a **bounded** certificate, which exploits the fact that the dual feasible set does not depend
  on the linear costs: the multipliers recorded with the decision remain feasible for the
  corrected program, so one Cholesky solve yields a valid upper bound on regret.

**CRI-U** extends the second certificate to a *set* of admissible corrections: it bounds
`sup_{Δc ∈ U} regret(Δc)` using the support function of the set plus a curvature term, without
re-solving any corrected program and without enumerating vertices.

Results on 598 seeded revision events, with an independent solver (OSQP) as the reference:

* no bound understated realized regret in any of the seven dual-iteration arms;
* every decision receiving the residual certificate carries a validated bound of at most
  `1.8e-17` (median `3.8e-19`, `n = 247`) against realized regret of at most `3.7e-15` — a
  numerical statement, not the exact zero the previous revision claimed;
* the free bound is loose by a factor of ~24; **five actual dual ascent steps reduce that to
  1.24, and twenty steps to 1.000** — the previously reported "1.00 at five steps" was an
  artefact of a silent 20-iteration floor;
* certification within the residual covers 41.3% of events (95% interval `[0.373, 0.453]`) and
  is a statement about *corner* solutions;
* over an interval uncertainty set, the worst-case bound was sound in **40/40 trials**, median
  1.53× the true worst case, and cost **52×** less than enumerating the 16 vertices.

The mathematical ingredients are classical: weak duality, KKT sufficiency, support functions of
convex sets, and support-set invariancy analysis. The contribution claimed is a problem
formulation, a composition that makes one certificate free and another a support-function
evaluation, and an empirical characterisation that includes the conditions under which the
method fails. No new theorem is claimed.

### 1.1 Corrections to the first revision

| Issue found in review | Severity | Resolution |
|---|---|---|
| Proposition 1 stated `f(w) − g ≤ regret(w)` — the inequality was reversed | P0 | Corrected to `regret(w) = f(w) − f* ≤ f(w) − g`. The direction is now asserted numerically, with an adversarial test that fails if it is inverted (§5.1, §9.1). |
| `dual_objective` accepted negative multipliers, and the certificate copied a recorded dual point without checking it | P0 | Sign feasibility, dimensions, finiteness and **constraint-structure identity** are now validated; an invalid point is refused with a recorded reason. The false bound it would have produced is exhibited as a test (§9.2). |
| The five-iteration arm actually ran at least twenty iterations | P0 | The floor is removed; the requested, performed, objective-evaluation and gradient-evaluation counts are recorded per call, and budgets 0/1/2/5/10/20/50/200 are tested. **The tightness claim changes: 1.238 at five steps, not 1.000** (§6.4). |
| The exact test was described as `O(n²)` linear algebra with no optimisation | P1 | Corrected: least squares on the active set, with a HiGHS non-negative feasibility LP when least squares is sign-infeasible. The LP fallback runs in **30.4%** of events and both stages are timed separately (§6.6). |
| A KKT tolerance was described as proof of exactly zero regret | P1 | Replaced by an explicit residual certificate: `regret ≤ ½ r'Q⁻¹r + slack`, proved in §5.3, computed per event (§6.5). **Second review:** the verdict still *assigned* `0.0`; it now reports the computed bound — median `3.8e-19`, maximum `1.8e-17` over the 247 certified events. |
| Reference regret was computed by the same solver under test | P1 | OSQP and Clarabel are used as references, and exhaustive active-set enumeration for small instances. Maximum disagreement over the study: `9.4e-14` (§6.7). |
| Revision compilation could double count a correction published before the decision clock | P1 | Version lineage added: every revision receives one of six categories, and a pre-decision revision is excluded with reason `already_incorporated_in_decision_vintage` unless explicitly opted in (§5.5). |
| The report claimed a 25.6× speed-up; the committed run said 18.92× | P1 | All tables now render from one JSON. The current run gives 16.8× against the project's SLSQP re-solve — and **0.15× against OSQP**, i.e. the certificate is slower. **The speed claim is withdrawn** (§6.8). |

Two further defects were found by this revision's own checks and are disclosed here:

* **The first worst-case derivation was unsound.** It treated the dual function as affine in `Δc`
  and reported a bound of `2e-17` against a true worst case of `5.1e-3`. The dual function is
  concave, not affine, because the Lagrangian minimiser moves with the cost vector. §5.6 gives
  the corrected three-term bound and the numerical check that caught the error.
* **The residual bound initially omitted the complementarity slack**, so it was smaller than the
  duality gap (`6.97e-31` against `1.39e-17`) and therefore not a bound. §5.3 gives the identity
  that fixes it.

### 1.2 Corrections required by the second independent review (`04198d2`)

The review supplied a program whose certificate can be checked by hand: `Q = I₂`, `c = (−2, 0)`,
budget 1, bounds `[0,1]`, one row `w₁ ≤ 0.8`, recorded `w = (0.5, 0.5)`, `ν = α = β = 0` and
`γ = 0.7`. Its regret is `0.510`, its dual gap `0.655`, and the routine reported `0.235`. All six
defects below were reproduced numerically before being fixed, and each has a test that fails if it
returns.

| Issue found in the second review | Severity | Resolution |
|---|---|---|
| `residual_regret_bound` **subtracted** `γ'(d−Aw)` | P0 | Sign corrected and the identity re-derived in the docstring; it is now *checked on every call* (`gap_identity_residual`) and a call whose identity fails is refused. On the review's instance the bound is `0.655`, matching the true gap, against a regret of `0.510`; OSQP, Clarabel and the internal solver all give `f* = −1.26`. §5.3, `tests/test_decision_counterexample.py`. |
| The KKT verdict assigned `regret_upper_bound = 0.0` | P0 | The verdict is now `zero_regret_within_residual` and reports the validated residual bound together with the residuals behind it. No emitted bound is a literal zero. §5.2, §6.5. |
| Supersession and withdrawal were resolved against the *archive*, not the audit clock | P0 | Resolution is cutoff-relative and recursive: a successor published after the cut-off, or withdrawn before it, cannot suppress its predecessor. `effective_at`, `withdrawn_at` and `version` are immutable fields; version order, effective order and acyclicity are enforced rather than reordered. §4.3, `tests/test_decision_properties.py`. |
| Ellipsoid membership inverted the Cholesky factor of `shape`, while the support function and the maximiser used `shape` | P0 | A single `UncertaintySet.contains` / `distance_outside` predicate now serves membership, support, argmax and the curvature envelope, matching `U = {c + S z : ‖z‖ ≤ r}`. With `S = diag(0.25, 1)`, `r = 1` and offset `(0.4, 0)`, the offset is `1.6` in normalised coordinates — outside — and is now classified as outside rather than at `0.8`. §5.6. |
| CRI-U evaluated its bound at recorded decisions that were **infeasible** for the program | P0 | Feasibility is checked before any guarantee is claimed: `objective_bound` (a fact about the numbers) is reported separately from `actionable = valid ∧ decision_feasible`, and an infeasible decision yields `valid = false` with the reason recorded. §5.6. |
| The SEC case described a conforming recast as a "restatement" | P1 | Both 10-Ks leave Item 9C (the correction-of-an-error question) unchecked, and the FY2024 filing states that royalty income was reclassified into `Total revenues` and that *"prior-period amounts have been recast to conform to the current presentation"*. The script now derives `conforming_recast` from both primary documents and records the checkbox state, the quoted disclosures and their SHA-256 digests. §7.2. |

## 2. Introduction

A point-in-time research system exists to answer "what was knowable, and when". Atlas already
enforces that for *evidence*. This branch applies the same discipline one level up, to
**decisions**.

Consider a portfolio rebalance computed on 28 June from the trailing 250 sessions, and a vendor
correction published on 2 July. Three questions are possible:

1. *What would the model allocate today?* — a re-solve. Easy, and it is not an audit.
2. *How much did the objective change at the old weights?* — the first-order estimate
   `(c_new − c_old)·w`. Widely used, and **not a bound**: §6.9 measures it understating the
   realized regret in 22.6% of events.
3. *Was the decision that was actually taken optimal given what we now know, and if not, how
   much did that cost?* — the question this report answers.

Question 3 has a property the others lack: it has a definite answer that can be certified with
linear algebra, because the decision is fixed and only the program changes.

## 3. Research question

> For a recorded decision `w` of a convex program `P(c)` solved at time `t`, and a set `U` of
> admissible corrections to the linear costs derived from evidence public at audit time `τ ≥ t`,
> can we certify an upper bound on `sup_{Δc ∈ U} [ f_{c+Δc}(w) − min_x f_{c+Δc}(x) ]` without
> re-solving `P` for each candidate correction?

For `U = {Δc}` this is the original CRI question. Four sub-questions are answered empirically:
how often the exact certificate succeeds (§6.3), how tight the cheap bound is at a stated
iteration budget (§6.4), how the guarantee fails when its premise is violated (§6.9, §6.10), and
whether the worst-case extension is sound and affordable (§6.10).

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

A revision `r` is a tuple `(evidence_id, input_key, δ, available_at, status, incorporated_in,
source_id, kind)`. It is compiled into a cost perturbation through a **declared** linear
sensitivity `s_k`:

```
c' = c + Σ_{r applied} δ_r · s_{input(r)}
```

The sensitivity is an explicit modelling assumption, not an estimate. A revision whose `kind` is
not `linear_objective` (for example a covariance revision) is **refused**, with the reason
recorded, because a risk-matrix change is a different mathematical object.

### 4.3 Two clocks, and the difference between eligibility and novelty

* `decision_as_of` — when the decision was taken.
* `audit_as_of` — when the audit is run.

Collapsing them is an error in either direction: using the decision clock as the eligibility
cutoff excludes exactly the revisions the audit exists to evaluate; using neither admits a
not-yet-public revision.

Supersession and withdrawal are resolved **against the cut-off, not against the archive**. A
successor that is published after `audit_as_of`, or withdrawn before it, cannot retroactively erase
the revision it was meant to replace: at the audit instant the earlier revision was the operative
record. The resolution is recursive, so a chain of replacements is followed only as far as the
cut-off allows, and it cannot cycle. Each revision carries an immutable `effective_at` (defaulting
to `available_at`) and, if retracted, `withdrawn_at`; a successor must carry a strictly larger
`version`, cannot take effect before its predecessor, and neither inversion is silently reordered.
An earlier version of this compiler computed the superseded set as a plain comprehension over every
supplied `supersedes` and ignored time in the withdrawal test, so a later filing suppressed an
earlier one even when it did not yet exist at the audit clock — a look-ahead leak of exactly the
kind this branch forbids in the evidence layer.

Eligibility is not novelty. A correction published *before* the decision clock is already inside
the vintage the decision was computed from, so applying it again double counts it. The compiler
therefore classifies every supplied revision into exactly one lineage category:

| Category | Meaning | Effect on `Δc` |
|---|---|---|
| `incorporated_before_decision` | public at or before the decision clock | excluded (`already_incorporated_in_decision_vintage`) |
| `pre_decision_explicitly_included` | public before the decision, included on request | applied |
| `published_after_decision` | published in `(t, τ]` | applied |
| `published_after_audit` | not public at the audit clock | excluded |
| `superseded` | replaced by a later revision that is itself live at the audit clock | excluded |
| `withdrawn` | retracted on or before the audit clock | excluded |
| `unsupported_kind` / `unmapped` | not compilable | excluded |

`starting_vintage` records which data vintage the base program represents. §7.2 shows the guard
working on a real filing.

## 5. Method

### 5.1 Weak duality, with the direction stated once and correctly

The Lagrangian dual of §4.1 is a concave quadratic in `(ν, α, β, γ)`:

```
g(ν,α,β,γ) = 0.5 · r'w − ν b + α'l − β'u − γ'd,     w = −Q⁻¹ r,
r           = c + ν1 − α + β + A'γ
```

with `α, β, γ ≥ 0`.

**Proposition 1 (weak-duality bound).** For any `α, β, γ ≥ 0`, any `ν`, any optimal value `f*`
and any feasible `w`:

```
g(ν,α,β,γ) ≤ f* ≤ f(w)        hence        0 ≤ regret(w) = f(w) − f* ≤ f(w) − g.
```

*Proof.* For feasible `w`, `g ≤ L(w,ν,α,β,γ) = f(w) + ν(1'w − b) − α'(w−l) + β'(w−u) +
γ'(Aw−d) ≤ f(w)`, using `1'w = b`, `w ≥ l`, `w ≤ u`, `Aw ≤ d` and the sign constraints. Taking
the minimum over feasible `w` gives `g ≤ f*`; the rest follows by subtracting. ∎

The final expression is an **upper** bound on regret. The first revision of this report wrote the
inequality the other way round. Because the error was in the direction of the inequality rather
than in the computation, no numerical result changes — but a reader implementing the report would
have produced a lower bound and called it a guarantee. `tests/test_decision_certification.py`
now asserts both `g ≤ f(w)` and `regret ≤ f(w) − g` explicitly.

**Proposition 2 (the dual feasible set is cost-independent).** `{(ν,α,β,γ) : α,β,γ ≥ 0}` does not
depend on `c`, so a multiplier vector recorded at time `t` is feasible for the corrected program
and its dual value is finite.

*Proof.* `c` enters `g` only through `r`, which enters only the value, not the domain. ∎

Proposition 2 is why the zero-iteration certificate costs one Cholesky solve. It is a direct
consequence of the dual's structure, not a new idea.

**Preconditions are checked, not assumed.** A multiplier vector is only a certificate if it is
dual feasible and belongs to this program. `validate_dual_point` refuses negative multipliers,
non-finite entries, wrong dimensions and a mismatched `structure_digest` (the digest of the
constraint geometry: `Q`, bounds, budget and rows, excluding costs and provenance). A cost
revision leaves the structure digest unchanged, which is exactly the reuse CRI needs; a changed
cap or an added row changes it, and the recorded multipliers are then refused.

### 5.2 Exact certificate

Given recorded weights `w`, stationarity is *linear* in the multipliers once the active set is
fixed:

```
ν1 − α + β + A'γ = −(Qw + c),    α, β, γ ≥ 0
```

The implementation solves this by least squares on the active coordinates (with `ν = ν⁺ − ν⁻`),
and, when the least-squares representative is sign-infeasible or leaves a residual, by a
non-negative feasibility LP (`scipy.optimize.linprog`, HiGHS). It then verifies the full KKT
system: primal feasibility, stationarity, dual feasibility and complementarity, each reported as
a residual against a relative tolerance.

**Proposition 3 (exactness, as a mathematical statement).** For the convex program of §4.1, KKT
is necessary and sufficient for global optimality, and linear constraints satisfy the constraint
qualification. Hence a satisfied KKT system certifies `regret(w) = 0`.

*Proof.* Standard (Boyd & Vandenberghe §5.5.3): convexity gives sufficiency, linearity gives
Abadie's constraint qualification and hence necessity. ∎

Proposition 3 is a statement about exact arithmetic. The implementation compares residuals
against a tolerance, so what it certifies is `regret ≤ ½r'Q⁻¹r + slack`, computed and reported
per event (§5.3). The report no longer says "exactly zero" about a numerical result.

The exact test is *sufficient*, not necessary: a negative answer proves nothing, and §6.3 shows
it is silent whenever the active set changes, including when the change is numerically
negligible.

### 5.3 From a residual to a quantity

Write `L` for the Lagrangian at given multipliers, `x*` for its unconstrained minimiser,
`r = Q(w − x*) = Qw + c + ν1 − α + β + A'γ`, and

```
slack = α'(w−l) + β'(u−w) + γ'(d−Aw) ≥ 0          at a feasible w.
```

Every term is **added**. The Lagrangian is `L(x) = f(x) + ν(1'x − b) + α'(l−x) + β'(x−u) +
γ'(Ax − d)`, so stationarity reads `∇f + ν1 − α + β + A'γ = 0`, and `f(w) − L(w)` collects three
non-negative products with a **plus** on the inequality one. An earlier version of this section —
and of the routine implementing it — carried a minus there. The consequence is not a looser bound
trifiable by assumption: it understates the gap whenever a row is inactive and produces a number
that is not a bound at all.

**Proposition 3b (residual certificate).** For any feasible `w` and any dual-feasible point,

```
regret(w) ≤ f(w) − g(λ) = 0.5 · r' Q⁻¹ r + slack ≤ ||r||² / (2 λ_min) + slack.
```

*Proof.* `L(w) − L(x*) = ½ r'Q⁻¹r` because `L` is quadratic with Hessian `Q`. Also
`f(w) − L(w) = α'(w−l) + β'(u−w) + γ'(d−Aw) = slack` at a feasible `w`. Adding,
`f(w) − g(λ) = ½r'Q⁻¹r + slack`; Proposition 1 finishes the argument. The second inequality uses
`Q ⪰ λ_min I`. ∎

This is an identity, not a loosening, and it holds whether or not the multipliers are
complementary. Two versions of the routine got it wrong in different ways: the first dropped
`slack` entirely (`6.97e-31` against a true gap of `1.39e-17`), and the second negated its `γ`
component, reporting `0.235` on an instance whose gap is `0.655` and whose regret is `0.510`. Both
numbers are now checked rather than argued: the routine recomputes `f(w) − g(λ)` and exposes
`gap_identity_residual`, refusing a certificate whose identity fails, and the test suite asserts
the identity to `1e-12` across five numerical scales, zero to three inequality rows and random
dual-feasible points with mass on inactive rows.

### 5.4 Bounded certificate and the measured value of an iteration

Combining Propositions 1 and 2: `bound₀ = f_{c'}(w) − g_{c'}(λ_t)` where `λ_t` are the
multipliers recorded at decision time. Running exactly `k` L-BFGS-B iterations from that point
gives `bound_k ≤ bound₀`. Because every iterate is projected onto `α, β, γ ≥ 0` before
evaluation, each intermediate value is a valid bound: a failed line search degrades tightness,
never soundness.

The iteration budget is honoured literally (`max_iter=k`), and every call records the requested
budget, the iterations performed, objective and gradient evaluations, runtime, the starting and
final dual values, and whether the budget was respected. The first version applied
`max(int(k), 20)`, which made the "five-step" measurement a lie; §6.4 reports what the correction
costs.

### 5.5 Radii

**Proposition 4 (invariance radius is an interval).** Along a ray `c(r) = c + r·d`, the set
`{r ≥ 0 : w remains optimal for P(c(r))}` is a closed interval containing `0`.

*Proof.* With `w` fixed, the KKT system of §5.2 is a finite system of linear equalities and
inequalities in `(r, multipliers)`. Its solution set is a polyhedron, whose projection onto one
coordinate is an interval; `r = 0` is feasible by assumption. ∎

**Proposition 5 (regret is convex in the radius).** `G(r) = f_{c(r)}(w) − V*(c(r))` is convex in
`r ≥ 0` with `G(0) = 0`.

*Proof.* `V*(c)` is a pointwise minimum of affine functions of `c`, hence concave; `c(r)` is
affine; `f_{c(r)}(w)` is affine in `r`. Affine minus concave is convex. ∎

### 5.6 Worst-case regret over a set of admissible corrections

The audit often cannot claim to know `Δc` exactly. Let `U` be a documented uncertainty set —
coordinate intervals, an ellipsoid, or a singleton.

**The supremum is not a convex problem and is not solved as one.** `regret(Δc)` is convex in
`Δc` (the optimal value is concave in `c`), so its maximum over a convex set sits at an extreme
point; maximising a convex quadratic over a box is NP-hard. What is tractable is the following.

**Proposition 6 (worst-case dual bound).** For any dual-feasible `λ` and any `Δc`,

```
regret(Δc) ≤ gap_c(λ) + Δc'(w − w(λ)) + 0.5 · Δc' Q⁻¹ Δc,
```

with `gap_c(λ) = f_c(w) − g_c(λ)` and `w(λ) = −Q⁻¹(c + ν1 − α + β + A'γ)`. Consequently

```
sup_{Δc ∈ U} regret(Δc) ≤ gap_c(λ) + h_U(w − w(λ)) + curv(U),
curv(U) = 0.5 · m' |Q⁻¹| m,      m_i = max_{Δc ∈ U} |Δc_i|,
```

and `h_U` is the support function: `Σ h_i|d_i| + c'd` for an interval set,
`c'd + radius·||L'd||₂` for an ellipsoid `{c + Lz : ||z|| ≤ radius}`, and `c'd` for a singleton.

**`L` is the shape matrix itself, not a factor of it.** Membership is `‖L⁻¹(Δc − c)‖ ≤ radius`,
and the support function, the maximiser `c + radius·L(L'd)/‖L'd‖` and the curvature envelope are all
built from `L`. An earlier version solved the membership test against `chol(L)`, which describes a
different set: with `L = diag(0.25, 1)`, `radius = 1` and offset `(0.4, 0)`, the offset is `1.6` in
normalised coordinates — outside — but the Cholesky reading places it at `0.8`, inside. An
out-of-set correction certified as in-set is the one failure this extension cannot have, so
membership is now a single `contains`/`distance_outside` method used by every path, including the
adversarial probe that measures out-of-set violations.

**The bound is conditional on the decision being admissible.** An objective-value bound evaluated at
weights that violate the program's constraints is a true statement about numbers and a false one
about decisions. The certificate therefore reports `objective_bound` separately from
`actionable = valid ∧ decision_feasible`, sets `valid = false` when the recorded decision is
infeasible, and records the feasibility report alongside the reason.

*Proof.* By Proposition 1, `regret(Δc) ≤ f_{c+Δc}(w) − g_{c+Δc}(λ)`. Expanding,
`f_{c+Δc}(w) = f_c(w) + Δc'w`, and the dual value moves as
`g_{c+Δc}(λ) = g_c(λ) + Δc'w(λ) − ½Δc'Q⁻¹Δc` because the minimiser shifts by `−Q⁻¹Δc`. The
first display follows. The second uses `sup (a'b + c'b) = h_U(a) + c'b`, monotonicity of the
supremum over the two remaining terms, and `|Δc_i| ≤ m_i` with `|Q⁻¹_ij| ≥ 0`. ∎

**The first version of this derivation was wrong**, and the error is instructive enough to record.
It dropped the `< ½Δc'Q⁻¹Δc` term by treating `g` as affine in `c`. On a four-asset instance with
a box of half-width `0.01`, that produced a bound of `2.05e-17` against an enumerated worst case
of `5.10e-03` — a bound that is not a bound. The curvature term is what repairs it. This is the
only error in the branch that was caught by a *proof-by-enumeration check rather than by
inspection or a unit test*, and it is the reason §6.10 compares against vertices rather than
against sampled corrections alone.

Three properties make the corrected bound usable:

1. It is sound for **any** dual-feasible `λ`, including the multipliers recorded with the original
   decision, so the free version costs one Cholesky solve and one support-function evaluation.
2. The curvature term is second order in the size of the set, so the bound is dominated by the
   first-order term for small revisions — which is what makes it informative rather than merely
   valid.
3. `min_λ bound(λ)` **is convex** even though the inner supremum is not: `gap` is convex in `λ`
   and the support term is a supremum of affine functions of `λ`. The certificate can therefore be
   optimised, and the optimised bound is never worse than the free one. This asymmetry — convex in
   the multiplier, non-convex in the uncertainty — is the methodological point of the extension.

With `U = {Δc}`, Proposition 6 reproduces the CRI bound at the same multipliers. That is asserted
as a test, because a generalisation that does not contain its special case is a parallel theory.

## 6. Experiments

### 6.1 Design

Synthetic three-factor return panel, 250-session trailing window, 120 rebalances per seed, five
seeds, 6 assets, 25% position cap, risk aversion 5, Ledoit-Wolf covariance. A revision touches one
to three inputs with magnitude drawn from `N(0, (3·s.e.)²)` where `s.e.` is the standard error of
the estimate being corrected, so the perturbation scale is statistically meaningful rather than
arbitrary. Decision clock `2024-06-28T20:30:00Z`, audit clock `2024-07-02T12:00:00Z`.

The data are **synthetic** and labelled as such in every artifact. §7 adds one real revision.

### 6.2 Trial accounting

| seed | attempted | accepted | rejected | reasons |
|---|---|---|---|---|
| 101 | 120 | 120 | 0 | none |
| 102 | 120 | 119 | 1 | `solver_status_feasible_uncertified` |
| 103 | 120 | 120 | 0 | none |
| 104 | 120 | 119 | 1 | `solver_status_feasible_uncertified` |
| 105 | 120 | 120 | 0 | none |
| **all** | **600** | **598** | **2** | |

The two exclusions are not silent any more, and they are not a random sample: both are cases where
the primal solver returned a feasible point it could not certify, which is precisely the regime
the certificate exists to handle. Excluding them therefore **removes two events where the
certificate was most needed**, which biases the reported coverage slightly upward. The effect is
two events out of 600 and is not corrected; it is disclosed instead.

### 6.3 Soundness, exactness and coverage

| arm | rate | 95% moving-block interval |
|---|---|---|
| Exact zero-regret certificate | 0.413 | [0.373, 0.453] |
| Certified or bounded within `1e-4` | 0.425 | [0.383, 0.468] |
| Warm bound (0 iterations) sound | 1.000 | [1.000, 1.000] |
| Bounds at 1, 2, 5, 10, 20, 200 iterations sound | 1.000 | [1.000, 1.000] |
| Strong-convexity bound sound | 1.000 | [1.000, 1.000] |
| First-order Taylor estimate sound | 0.774 | [0.741, 0.809] |

Realized regret of events receiving the exact certificate: **maximum `2.1e-16`**. The residual
certificate of §5.3 has median `3.8e-19` and maximum `1.8e-17` over the 247 certified events.

Realized regret is measured by two independent solvers. The maximum disagreement between them over
the whole study is **`9.4e-14`** in objective units, and 41.3% of events have regret below ten
times that spread. Those events are exactly the exactly-certified ones, whose regret is ~`1e-17`:
the comparison is at the resolution limit of double precision and is reported as such rather than
as a measured improvement.

### 6.4 Tightness at a stated iteration budget

351 events have realized regret above `1e-10` (58.7% of accepted events). Within those:

| requested iterations | median bound/regret | p90 | events |
|---|---|---|---|
| 0 | 24.138 | 162.944 | 351 |
| 1 | 12.147 | 78.878 | 351 |
| 2 | 6.070 | 36.951 | 351 |
| 5 | 1.238 | 4.466 | 351 |
| 10 | 1.010 | 1.471 | 351 |
| 20 | 1.000 | 1.000 | 351 |
| 200 | 1.000 | 1.000 | 351 |

**This table replaces a wrong claim.** The first revision reported a median ratio of `1.00` at "five
iterations". With the iteration floor removed, five actual steps give `1.238`; twenty give `1.000`.
The qualitative conclusion survives — a handful of cheap iterations converts a useless bound into a
usable one — but the quantitative claim does not, and the cost of a five-step certificate is now
measured rather than assumed. Ten steps are within 1% of the truth, which is the practical
recommendation.

The free bound at 24× is valid but not decision-useful as a number; it is useful as a *screen* (a
bound of zero proves the decision is fine) and as a warm start.

The strong-convexity competitor is valid and consistently looser. It does not vanish at a
constrained optimum, because the gradient there is balanced by multipliers rather than zero. This
is a property of the bound, not a defect in its implementation, and it is asserted as a test.

The first-order Taylor estimate is not a bound and understates realized regret in 22.6% of events.
It is included because it is a common surrogate for "impact" in reporting systems, and the
measurement is the argument against using it as one.

### 6.5 The numerical certificate and the LP fallback

* Over the **247** events carrying the residual certificate, `½r'Q⁻¹r + slack` has median
  **`3.8e-19`** and maximum **`1.8e-17`**; the largest realized regret in that same set is
  `3.7e-15`. The bound is a computed number and is never exactly zero, which is why the verdict
  records what was measured (`zero_regret_within_residual`) instead of asserting a zero. An
  earlier version of this bullet reported a maximum of `1.0e-2`, because it pooled certified
  events with `regret_bounded` ones; that was the wrong set.
* Multiplier recovery: least squares in 416 events, non-negative LP in **182 (30.4%)**. The LP
  is a HiGHS call, not `O(n²)` linear algebra, and the frequency is now measured rather than
  asserted. Both stages are timed separately in the certificate (`multiplier_recovery_ms`,
  `kkt_check_ms`, `residual_bound_ms`, `warm_dual_evaluation_ms`).

### 6.6 Where exact certification comes from

| position cap | exact certificate rate | weights changed | max regret when certified |
|---|---|---|---|
| 0.18 | 0.525 | 0.475 | 2.93e-18 |
| 0.22 | 0.400 | 0.600 | 1.08e-18 |
| 0.25 | 0.525 | 0.475 | 2.11e-16 |
| 0.35 | 0.350 | 0.650 | 8.67e-19 |
| 0.50 | 0.275 | 0.725 | 3.90e-18 |
| 1.00 | 0.425 | 0.575 | 3.96e-18 |

The pattern is not monotone and the explanation is mechanical: an interior optimum moves
continuously with the cost vector, so its exact invariance radius is zero (Proposition 4's sharp
case), while a solution pressed against caps and floors frequently does not move at all when a
coefficient changes slightly. Certification is a statement about a *corner* solution and is silent
for interior ones. The last column confirms the certificate is not being granted to near-optimal
points.

### 6.7 Reference agreement

Three independent implementations — the project's SLSQP-plus-multiplier pipeline, OSQP, and
Clarabel — agree to **`9.4e-14`** in objective value over the whole study, and exhaustive
active-set enumeration agrees with all of them to better than `1e-9` on the small instances where
it applies. A regret number below that spread is not a measurement, and 41.3% of events are in
that regime; they are the exactly-certified ones.

### 6.8 Cost — and the withdrawal of the speed claim

| n | certificate ms | dual construction ms | re-solve cold ms | re-solve warm ms | OSQP ms | ratio vs cold SLSQP | ratio vs OSQP |
|---|---|---|---|---|---|---|---|
| 8 | 1.700 | 5.359 | 5.193 | 5.024 | 0.941 | 3.06× | 0.55× |
| 16 | 2.716 | 7.293 | 7.363 | 6.464 | 0.967 | 2.71× | 0.36× |
| 32 | 5.215 | 13.766 | 13.546 | 11.634 | 1.164 | 2.60× | 0.22× |
| 64 | 13.130 | 86.577 | 75.441 | 57.356 | 2.148 | 5.75× | 0.16× |
| 128 | 51.141 | 983.571 | 857.724 | 845.089 | 7.553 | 16.77× | 0.15× |

The first revision claimed a 25.6× advantage at `n = 128` against a re-solve. Two things are wrong
with using that number as a contribution:

1. It was measured against **the project's own SLSQP pipeline**, which is not a competitive QP
   solver. The ratio reproduces here (16.8×), so the earlier number was not fabricated — but it
   was the wrong comparison.
2. Against **OSQP at tight tolerance**, the certificate costs `0.15×` to `0.55×` of the re-solve
   time, i.e. it is **1.8× to 6.7× slower**.

**The time-advantage claim is therefore withdrawn.** What remains is narrower and defensible: the
certificate is cheaper than re-running the solver Atlas already uses, it requires no solver state
and no access to the original program beyond its digest and its multiplier vector, and it produces
a *guarantee* about a fixed recorded decision rather than a new optimum. Whether that is worth
51 ms at `n = 128` is a systems question, not a mathematical one, and it is not answered here.
The dual construction column also makes an uncomfortable point explicit: producing the multipliers
in the first place costs an order of magnitude more than the certificate that reuses them, so a
workflow that must solve the primal anyway gains nothing from certification.

### 6.9 Failure under a violated premise

| declared revision as a fraction of the true revision | bound violation rate | median realized/bound |
|---|---|---|
| 1.000 | 0.000 | 0.01 |
| 0.500 | 0.050 | 0.05 |
| 0.200 | 0.225 | 0.21 |
| 0.100 | 0.450 | 0.78 |

This is the most important limitation in the report. The certificate is not "safe by default"; it
is safe *given a correct declaration*, and a system that records the declaration alongside the
decision can be audited for it.

### 6.10 Worst-case certificate over an interval set

Forty trials, four coordinates, `U` a box of half-width `|Δc_i|/2` on one coordinate, 16 vertices
enumerated per trial by re-solving each one.

| quantity | value |
|---|---|
| sound rate (bound ≥ enumerated worst case) | **1.000** |
| median bound / true worst case | 1.530 |
| p90 bound / true worst case | 2.988 |
| median bound cost | 1.448 ms |
| median enumeration cost (16 re-solves) | 78.452 ms |
| cost ratio | **51.96×** |
| out-of-set corrections violating the bound | 0.875 |

Two readings matter. The bound is **sound in every trial** against an independent enumeration of
the exact worst case, at a cost 52× below enumeration in four dimensions — a gap that grows as
`2^n` versus `O(n³)`. And it is conservative by a factor of 1.53, almost entirely from the
curvature envelope rather than the support term; that is the price of not solving the NP-hard
inner problem, and it is the honest number to quote.

The last row is not a defect: corrections drawn outside the declared set violated the bound in
87.5% of trials, which is exactly what a conditional guarantee should do. It is measured so that
the conditionality cannot be forgotten.

### 6.11 Degeneracy, hindsight and the second domain

**Degeneracy.** Two assets correlated at 0.995 give a positive-definite risk matrix and a
well-defined dual bound, but swapping half of one for the other changes the objective by only
`8.98e-06` on an objective of order `1e-2`. Both allocations receive `regret_bounded`: the value
certificate is meaningful, a *decision-identity* claim is not. With two identical assets the risk
matrix is singular (rank 3 of 4) and the dual bound does not exist, because the dual function is
unbounded; the certificate then reduces to the exact KKT test alone.

**Hindsight.** The hindsight arm audits a decision recomputed with the later evidence and then
judged against it: apparent stability 100%. The honest arm, auditing the decision actually taken,
reports 52.5%. Mean regret of the actual decision in this arm was `6.08e-04`. This is the
quantitative form of the argument for the two-clock model.

**Second domain.** The same certificate, unchanged, runs on a capacity-allocation program with
linear service floors and a group capacity cap. Across 20 margin revisions: bound sound rate
1.000, exact certificate rate 0.000, mean realized regret `1.56e-04`. Every allocation sits at a
floor or the group cap, and each revision moves it, so exact invariance never applies while the
bound remains sound. The certificate layer never sees an asset, a return or a covariance; this
demonstrates structural generality and **not** operational usefulness.

## 7. A real evidence revision

### 7.1 The revision

Pfizer's FY2023 revenue appears twice in the SEC's XBRL company-facts archive:

| | original filing | later filing |
|---|---|---|
| value (USD) | 58,496,000,000 | 59,553,000,000 |
| form | 10-K | 10-K |
| accession | `0000078003-24-000039` | `0000078003-25-000054` |
| accepted | `2024-02-22T18:17:37Z` | `2025-02-27T21:27:18Z` |
| primary document | `pfe-20231231.htm` | `pfe-20241231.htm` |

The second figure is the comparative column of the FY2024 annual report — a revision of a
previously reported number inside a later filing, not an amendment on Form 10-K/A. Relative
change: **1.807%** (`+1,057` million).

**It is not a restatement, and the case study no longer says it is.** Both annual reports leave
Item 9C — the question whether the financial statements reflect the correction of an error —
unchecked, and the FY2024 filing gives the reason the figure moved:

> In the first quarter of 2024, we reclassified royalty income … from Other
> (income)/deductions—net and began presenting Royalty revenues as a separate line item within
> Total revenues … Prior-period amounts have been recast to conform to the current presentation.

So the difference is royalty income moved into `Total revenues`, with the comparative recast to
follow: a change in presentation, not an error correction under ASC 250, and no Form 10-K/A was
filed. The script reads the checkbox state and the disclosure sentences from **both primary
documents** at run time, classifies the revision (`conforming_recast`), and records the quoted
disclosures with their digests, so the label is derived from the filings rather than asserted by
the script. A caption is only as good as the check behind it, and this one had none.

Both values, form types, accession numbers and acceptance instants are read from the archive at
run time and checked against the constants in the script; the fetched bytes are cached with their
SHA-256 digests in `artifacts/research/evidence/`.

### 7.2 Compilation and audit

The model input is the implied FY2023 revenue **growth** against FY2022 (`−41.70%` as filed,
`−40.64%` in the later filing), mapped to the first line's expected return by a declared
sensitivity of `0.1` per unit of growth. Decision clock `2024-06-30T20:00:00Z`, audit clock
`2025-03-01T12:00:00Z`.

| quantity | value |
|---|---|
| characterisation | `conforming_recast` (formal restatement: `false`) |
| temporal relationship | `revision_available_after_decision` |
| verdict | `zero_regret_within_residual` |
| bound | `7.6e-31` |
| realized regret (OSQP reference) | `0.0` |

Two controls exercise the lineage logic on the same real revision:

* re-offered for a decision taken *after* the recast was published, it is excluded with reason
  `already_incorporated_in_decision_vintage` — the double-counting defect would otherwise have
  applied a 1.8% correction that the recorded evidence already contained;
* audited at `2025-01-15`, before the recast existed, it is excluded with reason
  `not_available_at_audit` — the look-ahead defect;
* audited at `2025-03-01` while a *successor* revision is dated after the cut-off, the earlier
  record stands rather than being suppressed — the lineage defect the second review found, which
  the synthetic suite in `tests/test_decision_properties.py` exercises on both sides of the clock.

### 7.3 What this case does not show

The decision model is a **stylised three-line allocation** in which only the first coefficient is
evidence-linked; the risk matrix, the other two coefficients and the budget are model parameters.
The revenue-to-return sensitivity is declared, not estimated. A conforming recast of comparatives
is not an error correction, an enforcement action or a fraud finding, and the revised figure is
not an independent measurement of the same quantity — it includes royalty income the as-filed
figure excluded. The case demonstrates that a real, dated, identified revision can be compiled and
certified with the same eligibility rules as the synthetic
experiments. It does **not** audit a real portfolio, and it says nothing about realized returns.

## 8. What is new, and what is not

| Component | Status |
|---|---|
| Weak duality, KKT sufficiency | Classical. No claim. |
| Support-set invariancy analysis (Ghaffari Hadigheh & Terlaky 2007; Kheirfam 2010) | The ancestor of the exact test. CRI applies it to an audit question; it does not extend it. |
| Reusing a stored dual solution after a right-hand-side or cost change | Classical in parametric programming and in the MIP sensitivity literature (Dey and co-authors, Georgia Tech ISyE). Not claimed. |
| Support function of an uncertainty set inside a robust program | Classical robust optimisation (Ben-Tal & Nemirovski; Bertsimas & Sim; Bertsimas, den Hertog et al.). Not claimed. |
| **Formulation:** regret of a *recorded* decision under evidence revisions, with an evidence-eligibility layer and explicit lineage | Claimed as a formulation contribution. Cannot be shown to be unoccupied; the prior-art audit explains why it is at least not the standard framing. |
| **Composition:** the dual feasible set is cost-independent, so the recorded multipliers give a free bound; a residual-to-regret identity makes the numerical certificate quantitative | Claimed as a composition. Each ingredient is classical. |
| **CRI-U:** the worst-case bound is affine-plus-quadratic in the correction and a support-function evaluation over the set, while the *outer* problem stays convex in the multiplier | Claimed as a composition with a genuinely useful asymmetry. Not a new theorem: the derivation is two expansions and a supremum. |
| **Empirical characterisation:** coverage by active-set regime, misspecification failure curve, LP-fallback frequency, tightness-versus-iteration curve, cost against a competitive solver | Claimed as evidence. This is the part most likely to be useful to someone else, including the negative parts. |

The closest *methodological* neighbours, and why this is not a renaming of them:

* **Parametric QP sensitivity / hot starts** answer "how far can the perturbation go before the
  optimal basis changes" along a parameter path. CRI answers "what is the regret of this specific
  recorded point" for an arbitrary perturbation and, in CRI-U, for a whole set. The exact
  certificate is the support-set test restricted to one point; the set version has no counterpart
  in that literature.
* **MIP sensitivity analysis** (Dey et al.) exploits stored dual information to bound the effect
  of right-hand-side changes in mixed-integer programs. CRI is the continuous, cost-perturbation,
  *evidence-dated* case. The overlap is the reuse of dual information; the difference is the
  object bounded (regret of a fixed decision, not the optimal value change) and the audit framing.
* **Robust optimisation** replaces the decision with a robustly optimal one. CRI-U keeps the
  recorded decision and bounds how bad it can be; it is a post-hoc certificate, not a solution
  method. The support function appears in both, which is why no novelty is claimed for it.
* **Distributionally robust optimisation** requires a calibrated ambiguity set. CRI-U takes the set
  as declared and *measures* what happens when it is wrong (§6.10); it makes no coverage claim.

No claim of peer review, of a new theorem, or of a verified performance improvement is made.

## 9. Verification

### 9.1 Tests

`tests/test_decision_certification.py` (36 cases) covers the two P0 corrections and the worst-case
certificate; `tests/test_decision_program.py` and `tests/test_decision_certificate.py` (62 cases)
cover the solver, the revision compiler and the radii. The full decision layer is 98 tests. The
repository suite is run before the commit that accompanies this report and its exact count is
recorded in `docs/research/GATE_STATUS_LEDGER.md`.

The adversarial cases required by the research plan, and where they live:

| Case | Test |
|---|---|
| Negative dual multipliers | `test_negative_multiplier_is_refused_and_its_false_bound_is_exhibited` |
| Invalid / mismatched dual vectors | `test_non_finite_multipliers_are_refused`, `test_wrong_dimension_and_wrong_geometry_are_refused` |
| Infeasible recorded decision | `test_infeasible_recorded_decision_suppresses_the_bound` |
| Duplicate / already-applied revision | `test_revision_before_the_decision_clock_is_not_applied_again` |
| Withdrawn and superseded revisions | `test_withdrawn_and_superseded_revisions_are_excluded_with_reasons` |
| Ill-conditioned and singular risk matrices | `test_singular_risk_matrix_removes_the_bound_but_not_the_kkt_test`, degeneracy experiment |
| Active-set transitions and interior optima | cap sweep, radius tests |
| Corrections outside the declared set | `test_out_of_set_corrections_are_measured_not_hidden` |
| Historical look-ahead | hindsight arm, SEC `not_available_at_audit` control |
| Cross-domain failure | capacity-allocation tests and experiment |

### 9.2 Independent solvers

OSQP 1.1.3 and Clarabel 0.11.1 are used as references at declared tolerances, together with
exhaustive active-set enumeration for small instances. The reference implementations live in
`src/atlas/decision/reference.py` and are never used by the certificate.

## 10. Limitations and threats to validity

* **Synthetic data.** The 598-event study is a model of evidence correction, not a measurement of
  it. The single real revision (§7) is a pipeline demonstration, not an empirical study.
* **Declared sensitivity.** The mapping from an input revision to a cost change is asserted. §6.9
  measures the consequence of getting it wrong but does not solve it.
* **No decision-quality claim.** Nothing here shows that certification improves decisions. It
  shows that decisions can be audited.
* **The certificate is slower than OSQP.** §6.8. The remaining advantage is auditability, not time.
* **Two events were excluded** from the study, and they are the two where the solver could not
  certify its own output — the regime the certificate targets. Disclosed, not corrected.
* **The curvature envelope is conservative** by a factor of about 1.5 in four dimensions and will
  degrade as the set widens relative to the curvature of the objective.
* **Linearity of the revision effect.** A revision that changes the covariance, the feasible set or
  the budget is refused rather than approximated.
* **Five seeds, one asset count, one estimator, `n ≤ 128`.**
* **No multiple-testing correction.** Seven iteration arms and eight diagnostics are reported for
  the same events; no p-values are claimed and the intervals are descriptive.
* **Dependence.** Events share overlapping estimation windows; intervals use a moving-block
  bootstrap with block 12, and a different block length would change their width.

## 11. Reproduction

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,terminal,optimization]"
.venv/bin/python -m pip install "osqp>=1,<2" "clarabel>=0.11,<1"   # reference solvers only
.venv/bin/python -m pytest -q
.venv/bin/python scripts/research/cri_experiment.py --output artifacts/research
.venv/bin/python scripts/research/sec_evidence_case.py --output artifacts/research/evidence
```

The experiment script is deterministic: seeds are fixed in `CONFIG`, no wall-clock or environment
value enters a decision, and the dataset digest is SHA-256 over the exact float64 arrays. Wall-clock
numbers (§6.8) are machine-dependent and are the only non-reproducible values. The SEC case replays
from cached payloads when the network is unavailable; hashes are recorded either way.

Environment for the reported run: Python 3.12.3, NumPy 2.5.5, SciPy 1.18.1, OSQP 1.1.3,
Clarabel 0.11.1, Linux x86-64. Total experiment runtime 41.1 s.

## 12. References

Verified during this pass (publisher or proceedings page retrieved):

1. S. Yamao et al. *Robust Decision-Focused Learning via Worst-Case Regret Minimization.* UAI 2026,
   PMLR 337:7701–7736. https://proceedings.mlr.press/v337/yamao26a.html
2. N. Schutte, K. Postek, N. Yorke-Smith. *Robust Losses for Decision-Focused Learning.* IJCAI
   2024, 4868–4875. https://www.ijcai.org/proceedings/2024/538
3. Y. P. Patel, S. Rayan, A. Tewari. *Conformal Contextual Robust Optimization.* AISTATS 2024,
   PMLR 238:2485–2493. https://proceedings.mlr.press/v238/patel24a.html
4. A. Ghaffari Hadigheh, T. Terlaky. *Sensitivity analysis in convex quadratic optimization:
   invariant support set interval.* Algorithmic Operations Research (2007).
   https://journals.lib.unb.ca/index.php/AOR/article/view/4624
5. B. Kheirfam. *Sensitivity analysis in multi-parametric strictly convex quadratic optimization.*
   Matematički Vesnik 62(2):95–107 (2010). http://www.emis.mi.sanu.ac.rs/EMIS/journals/MV/102/mv10201.pdf
6. F. Pacaud. *Sensitivity analysis for parametric nonlinear programming: a tutorial.* 2025
   preprint. https://optimization-online.org/wp-content/uploads/2025/04/main-1.pdf
7. S. Dey et al. *Sensitivity analysis for mixed-integer programs.* Georgia Tech ISyE research
   programme. https://research.isye.gatech.edu/research/sensitivity-analysis-mixed-integer-programs
8. P. Mohajerin Esfahani, D. Kuhn. *Data-driven distributionally robust optimization using the
   Wasserstein metric.* Mathematical Programming 171:115–166 (2018).
   https://link.springer.com/article/10.1007/s10107-017-1172-1
9. D. Bertsimas, D. den Hertog, et al. *A unified theory of robust and distributionally robust
   optimization via the primal-worst-equals-dual-best principle.* Operations Research (2023).
   https://pubsonline.informs.org/doi/10.1287/opre.2021.0268
10. Z. Fan, R. Ji, M. A. Lejeune. *Distributionally robust portfolio optimization under marginal and
    copula ambiguity.* JOTA 203:2870–2907 (2024).
    https://link.springer.com/article/10.1007/s10957-024-02550-y
11. U.S. Securities and Exchange Commission. *EDGAR company facts and submissions APIs.*
    https://data.sec.gov/ (retrieved 2026-11-18; payload hashes in
    `artifacts/research/evidence/`)

Standard references cited from the literature (bibliographic details to be re-checked before
external submission):

12. A. V. Fiacco. *Introduction to Sensitivity and Stability Analysis in Nonlinear Programming.*
    Academic Press, 1983.
13. S. Boyd, L. Vandenberghe. *Convex Optimization.* Cambridge University Press, 2004.
14. A. Ben-Tal, A. Nemirovski. *Robust solutions of uncertain linear programs.* Operations Research
    Letters, 1999.
15. D. Bertsimas, D. B. Brown, C. Caramanis. *Theory and applications of robust optimization.* SIAM
    Review 53(3), 2011.
16. D. Bertsimas, M. Sim. *The price of robustness.* Operations Research 52(1), 2004.
17. H. J. Ferreau, C. Kirches, A. Potschka, H. G. Bock, M. Diehl. *qpOASES: a parametric active-set
    algorithm for quadratic programming.* Mathematical Programming Computation 6, 2014.
18. R. T. Rockafellar, S. Uryasev. *Optimization of conditional value-at-risk.* Journal of Risk
    2(3), 2000.
19. O. Ledoit, M. Wolf. *A well-conditioned estimator for large-dimensional covariance matrices.*
    Journal of Multivariate Analysis 88(2), 2004.
20. A. N. Elmachtoub, P. Grigas. *Smart "Predict, then Optimize".* Management Science 68(1), 2022.

## 13. Note on tooling

The implementation, tests, experiments and this report were produced with an AI coding assistant
operating under human direction. Every reported number is generated by the committed scripts from
fixed seeds and can be regenerated. Across the two revisions the assistant wrote code containing
at least nine defects: six sign or modelling errors in the first pass, and in the second pass a
reversed inequality in the report, unvalidated dual multipliers, a silent iteration floor, a
double-counting revision rule, an unsound worst-case derivation and a residual bound that omitted
its slack term. The two P0 errors were found by human review; the rest were found by
finite-difference checks, proof-by-enumeration, independent solvers and weak-duality assertions.
Any venue submission should disclose assistant involvement per its policy.
