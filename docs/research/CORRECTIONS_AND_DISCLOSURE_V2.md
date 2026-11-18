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
| "The exact certificate proves regret is exactly zero" | **Narrowed.** It proves `regret ≤ 0.5 r'Q^-1 r + slack`: median `3.8e-19`, maximum `1.8e-17` over the 247 certified events (see §5.2). |
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

## 5. Third pass: six defects found by the second independent review

The review of commit `04198d2` was run against a program whose certificate can be checked by hand:
`Q = I₂`, `c = (−2, 0)`, budget 1, bounds `[0,1]`, one row `w₁ ≤ 0.8`, recorded `w = (0.5, 0.5)`,
`ν = α = β = 0`, `γ = 0.7`. Every defect below was reproduced numerically before it was fixed.

### 5.1 Inequality slack was subtracted, not added — P0, soundness

The Lagrangian carries `+γ'(Ax − d)`, so `f(w) − L(w) = α'(w−l) + β'(u−w) + γ'(d−Aw)`. The routine
subtracted the third term. On the review's instance that produced `0.235` where the dual gap is
`0.655` and the regret is `0.510` — a number below the quantity it claimed to bound. The first pass
had already fixed the *omission* of `slack`; this was a sign error in the same line, and the two
defects together are the clearest argument for checking an identity numerically rather than
reasoning about it in a comment.

**Why the study did not catch it.** Over 598 events the aggregate soundness rate stayed `1.000`.
The negated term only matters when a row is inactive, and at a recorded decision on a corner most
rows are active or have zero multiplier, where both conventions agree. A trend cannot distinguish a
sign error from noise; a two-variable program with a hand-computable answer can, and that is now
the regression test.

**Permanent test.** `tests/test_decision_counterexample.py` asserts `0.655`, asserts that the
negated form gives `0.235` and is therefore unsound, and asserts the identity to `1e-12` against
OSQP and Clarabel on the same instance. The routine additionally recomputes `f(w) − g(λ)` on every
call and refuses a certificate whose `gap_identity_residual` exceeds round-off.

### 5.2 The KKT verdict assigned an exact zero — P0, accuracy

The verdict `zero_regret_certified` set `regret_upper_bound = 0.0` and `bound_valid = true` on the
strength of a tolerance test. The residual bound was computed and then discarded. That is a claim
no floating-point computation supports, and it made the emitted number uncheckable.

The verdict is now `zero_regret_within_residual` and reports the computed bound with the residuals
behind it (stationarity, dual feasibility, complementarity, primal feasibility, tolerance, identity
residual). Over the certified set the bound has median `3.8e-19` and maximum `1.8e-17`; the largest
realized regret in that set is `3.7e-15`. The certified rate is unchanged at `0.413`, as it must be
— the tolerance test did not change, only what is reported about it.

**Superseded result preserved.** `artifacts/research/cri_results.json` previously carried
`"bound": 0.0` for every certified event, and the report's §7.2 printed `bound 0.0` for the SEC
case. Those entries are wrong in the same way and are retained here as the record of what was
claimed at `04198d2`: the current artifact reports the computed residual (median `3.8e-19`,
maximum `1.8e-17`) and `7.6e-31` for the SEC case.

### 5.3 Lineage was resolved against the archive, not the audit clock — P0, correctness

`superseded_ids` was a set comprehension over every supplied revision that declared a
`supersedes`, and the withdrawal test ignored time entirely. A successor published *after* the
audit cut-off therefore suppressed its predecessor, and a withdrawal dated after the cut-off
retroactively removed a revision that was live at the cut-off. Both are history leaks of exactly
the kind the branch exists to prevent — the same defect class as look-ahead in the evidence layer,
CAUGHT one level up.

**Fix.** Resolution is cutoff-relative and recursive: a successor counts only if it is itself live
at the cut-off (effective, not withdrawn, and not itself superseded). `EvidenceRevision` carries
immutable `effective_at`, `withdrawn_at` and `version` fields; a successor must carry a strictly
larger version, cannot take effect before its predecessor, and chains must be acyclic, all refused
with `ValidationError` rather than silently reordered. Adversarial tests cover a successor after
the cut-off, a successor before it, a withdrawal on either side, a successor that is itself
withdrawn, a version inversion, an effective-time inversion, a cycle, and an effective time that
differs from publication.

### 5.4 Ellipsoid membership inverted the wrong matrix — P0, mathematics

The uncertainty set is defined as `U = {c + S z : ‖z‖ ≤ r}`; the support function, the maximiser
and the curvature envelope were all built from `S`. Membership alone solved against `chol(S)`,
which describes a different set. With `S = diag(0.25, 1)`, `r = 1` and offset `(0.4, 0)`, the
offset is `1.6` in normalised coordinates — outside — but was classified inside at `0.8`. An
out-of-set correction certified as in-set is precisely the failure CRI-U must not have.

**Fix.** One `UncertaintySet.contains` / `distance_outside` predicate, used by every path including
the adversarial out-of-set probe. `contains` takes an absolute tolerance of `1e-12` in the
normalised coordinate so that a point produced by `argmax` — exactly on the boundary — is a member;
the review's counterexample is `0.6` outside, twelve orders of magnitude beyond the tolerance, so
the tolerance cannot hide a real violation. Property tests check support, argmax, membership and
curvature against each other for diagonal and correlated shape matrices.

### 5.5 CRI-U certified infeasible decisions — P0, semantics

An objective-value bound computed at a point that violates the program's constraints is a true
statement about numbers and a false statement about decisions. The certificate now reports
`objective_bound` separately from `actionable = valid ∧ decision_feasible`, sets `valid = false`
for an infeasible decision, and records the feasibility report and a reason. The 40-trial CRI-U
evaluation is unaffected because its recorded decisions are feasible; the gate matters for callers
who supply weights the solver never produced.

### 5.6 The SEC case was labelled a restatement without checking — P1, characterization

Two annual reports show different FY2023 revenue (`58,496` and `59,553` million). The case study
called the difference a restatement. Neither filing supports that: both leave Item 9C unchecked,
and the FY2024 document states that royalty income was reclassified into `Total revenues` and that
*"prior-period amounts have been recast to conform to the current presentation"*. It is a
conforming recast — a change in presentation — not an error correction under ASC 250, and no Form
10-K/A exists for FY2023.

The script now derives the characterisation from both primary documents at run time (Item 9C
checkbox state, quoted recast disclosures, SHA-256 of each document) and reports
`conforming_recast` with `formal_restatement: false`, alongside the ruling that would have been
produced had the checkbox been checked. The financial explanation and the primary-document quotes
are in `artifacts/research/evidence/sec_evidence_case.md`.

### 5.7 What did not change, and what did

Unchanged: the certified rate (`0.413`), the tightness curve (`24.1 / 12.1 / 6.1 / 1.24 / 1.01 /
1.000` at `0/1/2/5/10/20` iterations), the Taylor understatement rate (`0.774`), the
misspecification curve, the hindsight gap, the CRI-U soundness (`40/40`), the solver spread
(`9.4e-14`), and the ledger's 12 entries across 8 arms.

Changed: every certified event's emitted bound (from a literal `0.0` to its computed residual), the
SEC verdict and its bound, the SEC characterisation, and the lineage categories' temporal
semantics. The ledger is also truncated at the start of each run now: rerunning the experiment on
top of the previous file doubled every arm (12 entries became 24) while the JSON beside it
described one run.
