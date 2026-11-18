# Corrections and disclosures, second revision

This file is the audit trail for the second pass over the decision layer. It exists because the
preregistration's disclosure table was written before the review, and appending to a preregistered
document after the fact destroys the property that made it useful. The original
`PREREGISTRATION.md` is left exactly as registered; everything learned afterwards is recorded here.

## 1. Errors found by review (PR #5)

### 1.1 Reversed inequality in Proposition 1 — P0, mathematical

The report stated `g <= f*`, then concluded `f(w) - g <= regret(w)`. The correct conclusion is
`regret(w) = f(w) - f* <= f(w) - g`.

**Why it mattered even though no number changed.** The implementation always computed
`bound = f(w) - dual_value`, which is correct. The error was in the prose derivation, so a reader
re-implementing from the report would have produced a *lower* bound and called it a guarantee.
Every statement, test and docstring was audited; the direction is now asserted numerically in
`test_weak_duality_has_the_documented_direction`.

**Detection.** Human review. No automated check could have caught it, because the code and the
prose agreed with each other in the wrong direction — the code was right and the prose was wrong,
and nothing compared them.

### 1.2 Unvalidated dual points — P0, soundness

`qp.dual_objective` checked array shapes only. Negative multipliers were evaluated and the value
reported as a lower bound. `certificate.certify_revision_impact` copied `decision_dual` into the
corrected program without any check at all.

**Permanent adversarial test.** `alpha = c` cancels the cost vector inside the residual, driving
the dual value to `0` against a true optimum of `-0.0858`. The old path reported a "regret bound"
of `-0.0858`. The test constructs that point, asserts the corrected evaluator refuses it, and
asserts that the refused point's value exceeds the true optimum — so the test fails if the check is
ever removed, not merely if it throws the wrong exception.

**Also added.** Non-finiteness, dimension and `structure_digest` checks. The last one is the
interesting one: a multiplier vector is only a certificate for the constraint geometry it was
computed for, and a cost revision leaves that geometry unchanged, which is exactly the reuse CRI
needs.

### 1.3 Silent iteration floor — P0, experimental integrity

`maximize_dual(..., max_iter=max(int(dual_iterations), 20))`. Every "k-step" arm ran at least 20
iterations.

**Consequence, measured.** The five-step tightness claim was `1.00`. With the floor removed it is
`1.238`, and `1.000` is first reached at 20 iterations. The qualitative claim survives; the
quantitative one did not. This is the correction with the largest effect on the report's
conclusions, and it is the one that would have been most damaging if left in a submission.

**Detection.** Review found the line; the measurement is now automatic — `dual_budget` records
requested, performed, evaluated and whether the budget was respected, and a parametrised test runs
0, 1, 2, 5, 10, 20, 50 and 200.

### 1.4 Complexity claim — P1, accuracy

"`O(n²)` linear algebra; no optimisation" was wrong: `derive_multipliers` falls back to a HiGHS
non-negative feasibility LP. The fallback runs in **30.4%** of events, which is not a corner case.
Both paths are now timed and reported separately, and the certificate states which one ran.

### 1.5 "Exactly zero" from a tolerance — P1, accuracy

A KKT residual below a tolerance is a numerical statement. The report now states Proposition 3b
(`regret <= 0.5 r'Q^-1 r + slack`), computes it per event, and reports a median of `4.7e-19`
instead of claiming exact zero.

### 1.6 Self-referential reference — P1, experimental integrity

Reference regret came from the same `solve` implementation under test. OSQP and Clarabel are now
used as references, plus exhaustive active-set enumeration on small instances. Maximum disagreement
over the study: `9.4e-14`.

### 1.7 Revision double counting — P1, correctness

Every revision available by `audit_as_of` was applied, including revisions published before the
decision clock that the base program already contained. Fixed with explicit lineage: six
categories, `starting_vintage`, `incorporated_in`, `status`, and `include_pre_decision` as an
explicit opt-in for the different question ("the model missed evidence that was already public").

### 1.8 Stale numbers — P1, reporting

The report quoted 25.6× at `n = 128`; the committed artifact said 18.92×. Both came from real runs,
of different vintages. All tables now render from one JSON (`cri_tables.md`), and the prose copies
from it.

## 2. Errors found by this pass's own checks

### 2.1 Unsound worst-case derivation — P0, mathematical

The first version of the uncertainty-set bound expanded the dual function as if it were *affine* in
the correction. It is concave: the Lagrangian minimiser moves by `-Q^{-1}Δc`. The missing term is
`0.5 Δc'Q^{-1}Δc`.

**What it produced.** On a four-asset instance with a box of half-width `0.01`, a bound of
`2.05e-17` against an enumerated worst case of `5.10e-03`. A bound four orders of magnitude below
the quantity it bounds, reported as sound.

**Detection.** Proof-by-enumeration — the bound was compared against the true worst case over all
16 vertices. This is the only error in the branch caught by an enumeration check rather than by
inspection, a unit test or a finite difference, and it is why §6.10 of the report verifies against
vertices rather than against sampled points. A sampled check would very likely have missed it,
because the error is largest at the vertices.

**Fix.** Proposition 6, with the curvature term bounded by an elementwise envelope. Soundness over
40 trials: 1.000, median conservatism 1.53×.

### 2.2 Residual bound omitted its slack — P1, soundness

`0.5 r'Q^{-1}r` alone is smaller than the duality gap whenever the multipliers are not exactly
complementary at `w`: `6.97e-31` against a gap of `1.39e-17` on the first instance tested. The
identity `f(w) - g(λ) = 0.5 r'Q^{-1}r + slack` fixes it, and `slack` is now an explicit term with
its own assumption flag. The test asserts the identity to `1e-12`.

**Detection.** A probe script printed both numbers side by side while checking the new routine; they
were not equal, which the derivation said they must be.

### 2.3 Aggregation reported one seed as the pooled result — P1, reporting

The first regenerated `cri_tables.md` rendered tightness from seed 101 only (78 events) while
labelling it pooled. Fixed; the pooled table now covers 351 events.

## 3. Claims withdrawn

| Claim | Status |
|---|---|
| "Five dual ascent steps recover the exact regret (ratio 1.00)" | **Withdrawn.** 1.238 at five steps, 1.010 at ten, 1.000 at twenty. |
| "The certificate is 25.6× cheaper than a re-solve at `n = 128`" | **Withdrawn as a contribution.** 16.8× against the project's SLSQP pipeline, but **0.15×** against OSQP — slower. Auditability, not speed. |
| "The exact certificate proves regret is exactly zero" | **Narrowed.** It proves `regret ≤ 0.5 r'Q^-1 r + slack`, median `4.7e-19`. |
| "`O(n²)` linear algebra, no optimisation" | **Withdrawn.** LP fallback in 30.4% of events. |
| "598 events, 0 skipped" | **Corrected.** 600 attempted, 598 accepted, 2 rejected with recorded reasons. |

## 4. What did *not* change

The core empirical results reproduce on the corrected code: the zero-regret certificate rate
(`0.413`), the free-bound tightness (`24.138`), the Taylor understatement rate (`0.774`), the
misspecification curve (`0 / 0.05 / 0.225 / 0.45`), the hindsight gap (`0.525` vs `1.000`), and the
cross-domain bound soundness (`1.000`). The corrections changed two claims and tightened several
statements; they did not overturn the characterisation.

That is itself worth stating plainly: the defects were in *what was claimed*, not in *what the code
computed*, except for the two soundness paths (invalid dual points, worst-case derivation), which
were found before any result depended on them.
