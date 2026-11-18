# Corrections and disclosures, fourth pass

Append-only continuation of `CORRECTIONS_AND_DISCLOSURE_V2.md`, which covers the first three passes
and is left unedited. This file records what the review of `6430b5b` found and what changed.

The three defects below share a property: each is invisible at chain length one and with a single
clock. That is why the previous pass's tests — which were adversarial, but single-link — passed while
the behaviour was wrong.

## 1. A three-deep chain applied two replacements — P0, correctness

`has_live_successor` asked whether a successor was *itself terminal*. With `A → B → C` all live, B is
not terminal (C replaces it), so A's only successor was skipped and A was reported as not superseded.
The compiler then applied both A and C: `delta_cost` moved by `0.030` where the operative version's
delta was `0.010`.

**Now.** Resolution follows live successors to the single terminal of the chain and supersedes every
ancestor, including middle nodes. If a chain has more than one live terminal, the archive contradicts
itself and the compiler refuses with the candidate list rather than tie-breaking. Two further
invariants are enforced because the chain fix alone would leave them expressible:

* **replacement vs increment.** A revision declaring `supersedes` carries the corrected *value*, so
  `delta_semantics` is inferred as `absolute`; an increment may compose with other increments for the
  same input, and declaring `incremental` on a successor is refused. The inference also marks a
  revision absolute when it is *superseded*, which is what made the withdrawn-middle case visible.
* **one operative absolute revision per input.** A withdrawn middle revision plus its own surviving
  replacement leaves two absolute values for one input — a double count that the chain rule alone
  does not catch. It is refused with both revision ids named.

**Tests.** `tests/test_decision_lineage.py`: chains of length three and four, a chain with a middle
node published after the cut-off, a middle node withdrawn, a withdrawal after the cut-off, a branch,
a withdrawn middle with a live replacement, a three-cycle, a version inversion, and a no-`supersedes`
increment pair that is *meant* to sum.

## 2. Effective time could predate public availability — P0, look-ahead

`compile_revisions` used `effective_at or available_at` as its only cutoff test, and the supersession
test used the same function. A correction with `available_at = 2025-02-01` and
`effective_at = 2025-01-01` therefore entered an audit run at `2025-01-15` — a document that did not
exist yet. The same flaw let an unpublished successor suppress the revision it was meant to replace.

**Now.** `eligible_at` requires **public** (`available_at ≤ clock`) **and** effective
(`effective_at ≤ clock`), with distinct exclusion reasons `not_public_at_audit` and
`not_effective_at_audit` so the two failures are never conflated. The double-count guard uses the same
predicate at the decision clock: a revision published before the decision but effective after it is
*not* inside the vintage, so it is applied; one that is public and effective before the decision is
excluded as already incorporated.

**Tests.** Backdated correction (the review's case), public-but-not-effective, effective-before-public
successor, public-but-not-effective successor, inclusive boundary at the exact instant for both
conditions, after-hours acceptance against a noon audit and the same acceptance against a 23:00 audit,
and the two decision-clock cases.

## 3. A `1e-18` bound was presented as verified to `1e-18` — P1, reporting

`cri_tables.md` reported a maximum residual bound of `1.770e-17` among the certified events while the
largest measured reference regret in the same set was `3.732e-15`. The gap-identity checker accepted
`1e-8 · max(1,|gap|) + 1e-12` — four to six orders of magnitude looser than the number being claimed —
and the soundness tests allowed `+1e-12`. The rate was described as `1.000`, which reads as an exact
numerical guarantee.

**Investigated, not assumed.** The per-event decomposition settles the cause:

* in **185 of 247** certified events the lower-objective solver returned a point that violates a
  constraint (by up to `3.4e-11`). A feasible point cannot have an objective below the optimum, so
  that objective is spuriously low and the measured regret `f(w) − min(f_internal, f_osqp)` is
  inflated by exactly the difference;
* the excess tracks the solver spread, not the bound: worst excess `3.73e-15` against a spread of
  `3.73e-15`, and the worst excess is `0.26×` the solver's own resolution;
* against the *conservative* measurement — regret against the better of the two optima, at most
  `1.68e-17` — the emitted bound is never exceeded;
* recomputing the identity in extended precision leaves at most `2.07e-18`, so neither the certificate
  arithmetic nor summation cancellation is responsible.

So: solver error, not a certificate defect and not cancellation.

**Now.** Three numbers are reported instead of one. The *algebraic* bound is `½r'Q⁻¹r + slack`. A
forward floating-point error estimate (Higham's `γ_k`, conditioning included, headroom for the
separate dual evaluation) and the measured identity discrepancy are added to produce the *emitted*
bound, which is what a caller may quote. The identity gate is that estimate with headroom, rather
than a fixed `1e-8`. Over the certified set: algebraic median `3.8e-19` (max `1.8e-17`), emitted
median `6.4e-18` (max `4.3e-17`).

**A rejected alternative.** Gating certification on the discrepancy falling inside a tight multiple of
the estimate confiscated three valid bounds whose discrepancy overshot a 15% heuristic by 15%, and
replaced them with dual bounds of `1.7e-4`–`3.3e-3` — three orders of magnitude worse for no gain in
truth. Absorbing the discrepancy into the emitted bound is sound: the emitted value is then at least
the computed gap plus the margin plus the discrepancy.

**Wording.** Two rates are reported side by side over all 598 events that carry a bound: `0.941`
strict (35 measured regrets exceed their bound outright) and `1.000` resolution-aware (none exceed it
by more than the solver's own spread). The first shows the arithmetic has a floor; the second is the
guarantee. Neither is quoted alone, and neither is described as exact. `tests/test_decision_properties.py` asserts
the per-event reconciliation and the dominance of the emitted bound over the conservative measurement.

## 4. Stale gate text — P2, reporting

Gate G still said 860 tests and 98 decision-layer tests; Gate D still said `0.413` *exact*. Both are
regenerated from the same run as every other number in this revision (933 tests overall).

## 5. Superseded results preserved

| Artifact statement | At `6430b5b` | Now |
|---|---|---|
| Three-deep chain `A → B → C` | A and C both applied (`Δc` from `0.030`) | C only (`0.010`) |
| Backdated correction audited before publication | applied | excluded, `not_public_at_audit` |
| Certified bound (max, residual certificate) | `1.77e-17`, called verified | algebraic `1.77e-17`, emitted `4.29e-17` |
| Measured regret vs bound | unexplained `200×` gap | 35/247 exceed, all `≤ 0.26×` solver resolution, 0 beyond |
| Identity check tolerance | `1e-8·max(1,|gap|)+1e-12` | forward error estimate with headroom |
| Gate G / Gate D | `860` tests, `0.413` exact | `933` tests, `0.413` within residual |

Unchanged by this pass: the certified rate (`0.413`, 95% interval `[0.373, 0.453]`), the tightness
curve (`24.14 / 12.15 / 6.07 / 1.238 / 1.010 / 1.000` at `0/1/2/5/10/20`), the Taylor understatement
rate (`0.774`), the CRI-U soundness (`40/40`), the solver spread (`1.4e-14`), and the SEC case's
verdict and characterisation.
