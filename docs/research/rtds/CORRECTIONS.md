# Methodological correction log

Version 1 of this study was published on branch `research/real-world-revision-study` (commits
`c51cf32`, `6aa925d`) and reviewed on PR #6. The review found that the audit-time program was built
incorrectly, which invalidates v1's headline numbers for the model the protocol defines. This log
records every defect, how it was detected, what replaced it, and how the replacement is verified.

The superseded outputs are preserved unchanged in `artifacts/research/rtds/superseded/`
(`dataset_v1.json`, `results_v1.json`, `tables_v1.md`, `dataset_v1.md`). They are not deleted, not
regenerated and not edited: a reader must be able to see what v1 claimed.

---

## C1. Objective coefficient mapping (fatal; invalidates v1's headline results)

**Defect.** `mean_variance_problem` stores `linear_costs = -expected_returns`. The study passed the
standardised growth `z_D` as expected returns, so the decision program's linear cost was `-z_D`. The
revision compiler was then handed `delta = z_A - z_D` with a *positive* identity sensitivity, so the
audit-time program's cost vector became

    -z_D + (z_A - z_D) = z_A - 2 z_D        (v1)

instead of the intended `-z_A`. Every v1 regret, materiality fraction, certificate, bound and AUC was
therefore a statement about a program nobody asked for. The defect is not a small perturbation: the
coefficient vector of v1 differs from the corrected one term by term, and it often changes sign.

**Detection.** Reported by the independent review; reproduced here on a deterministic three-asset
instance before any correction was made (`tests/test_rtds_design.py::
test_defect_reproduction_and_corrected_mapping` asserts `cost == z_A - 2 z_D` for the old path).

**Correction.** One convention, documented once in `scripts/research/rtds_model.py`:
*a revision is a change in the program's linear cost vector, applied with a positive identity
sensitivity*. Hence `delta = c_A - c_D = (-z_A) - (-z_D) = z_D - z_A`, and the compiled audit program
satisfies `c_D + delta == -z_A`. The two representations (change in expected returns with a negative
sensitivity, or change in linear costs with a positive one) are never mixed.

**Verification (permanent).** For **every** event, the audit-time program is also constructed directly
from the audit-vintage observations and asserted equal to the compiled one across objective
coefficients, quadratic matrix, bounds, budget, inequality rows and right-hand sides, and objective
and gradient at the recorded decision plus four probe points. Maximum disagreement over all 408
processed events: **8.9e-16**. The assertion is a runtime check in `run_event` and a test
(`test_archived_events_compile_to_the_audit_vintage_program`).

**Impact.** Materiality moves from 63.2% to 73.7% (cohort A) and 47.4% to 50.0% (cohort B); certified
immateriality from 28.9% to 21.1% (A) and 42.1% to 44.7% (B). See the attribution table: with the old
audit vintages and the corrected convention (middle arm), A reads 27/38 material and 9/38 certified,
so the sign error, not the horizon, accounts for most of the difference.

## C2. CRI-U perturbation origin (fatal; invalidates v1's zero-certification reading)

**Defect.** `certify_worst_case` interprets its set as a set of *corrections* relative to the program
passed in. The study passed `center = cost_audit` (the standardised growth level, `z_A`) and applied it
to a program whose costs were `-z_A`. Two errors compounded: the centre was an absolute level rather
than a correction, and it had the wrong sign. The resulting bound was dominated by a term of order
`||z_A||`, so CRI-U certified nothing.

**Correction.** Two explicitly declared arms, both with `center = 0` because a correction is not a
level:

* **audit base** — base = the audit-time program, set = *further* corrections of typical size
  (`half_width` = train-split mean `|Δc|` per input);
* **decision base** — base = the decision-time program, set = the total correction relative to it,
  same width.

Widths are estimated on the train split only (2000–2012) and are never touched by test data.

**Verification.** `test_uncertainty_set_is_centred_on_the_base_it_declares` checks the bound against
exhaustive vertex enumeration (all `2^n` vertices, each re-solved), checks that a singleton at zero
reproduces the CRI bound exactly, and shows that a level-as-perturbation centre inflates the bound by
more than 10× — the mechanism behind v1's zero.

**Result after correction.** CRI-U still certifies **0 of 38** and **0 of 114**, on both bases. The
zero-certification result therefore stands, but for a different and now quantified reason: with
typical revisions of 0.2–0.36 in cost units and `τ = 1e-3`, a worst-case bound over such a box is
hundreds of times the tolerance. In addition, the declared box fails to contain the actual correction
for 50.0% (A) and 50.9% (B) of test events, so the guarantee is often not applicable at all. That
second number was never reported in v1.

## C3. Upper bounds read as materiality claims (serious; invalidates v1's accuracy figures)

**Defect.** v1 counted `bound > τ` as a materiality claim and reported "accuracy 92.1% / 89.5%". An
upper bound above the tolerance proves nothing about materiality; it is a failure to certify. The
"accuracy" was v1's certified share plus the base rate, dressed as a classifier.

**Correction.** Three explicit categories (`classify_regret`):

* **certified immaterial** — validated upper bound `<= τ`;
* **certified material** — an independent *lower* bound `> τ`, obtained from a feasible descent
  (budget-preserving coordinate swaps, closed-form steps, no solver): `f(x_D) - f(x_repair)` with
  `f(x_repair) >= f*`;
* **unknown** — neither.

The witness is asserted feasible and asserted not to exceed the measured regret on every event
(`run_event` raises otherwise); a test checks the same property independently, and another checks that
an immateriality certificate and a materiality witness can never both hold.

**Impact.** Reported as coverage, abstention and false-certificate counts, not accuracy. On the test
split: 94.7% of decisions certified in both cohorts, 5.3% honestly unknown, zero false certificates in
either direction.

## C4. Audit horizons (serious; changes the audit vintages)

**Defect.** The protocol says four calendar quarters (cohort A) and twelve calendar months (cohort B).
The implementation used 400 days and 366 days. 400 days is about 13 months, so nearly every quarterly
audit vintage was a later release than the protocol specifies.

**Correction.** `add_months(decision, 12)` with month-end clipping, used by both cohorts (four quarters
and twelve months are the same calendar interval). The dataset now records `audit_target`,
`horizon_months` and `horizon_days_actual`.

**Impact.** 98 of 98 paired quarterly events changed audit vintage; 2 of 294 monthly events did. The
*coefficient vectors* changed for far fewer events (3 in A, 0 in B), because an adjacent release
usually carries the same value for an old period. Materiality: A 71.1% → 73.7%, B unchanged.

## C5. The directional stability radius as a predictor (serious; changes the headline AUC)

**Defect.** v1 reported "geometry predicts materiality, AUC 0.88/0.94" using a feature set in which the
directional stability radius was one of eight inputs. That radius is not free metadata: it runs a
bracketing search of multiplier recoveries and KKT checks *along the observed revision direction*, so
it is a target-proximal diagnostic with roughly the same information content as the quantity it
predicts. Presenting the result as an independent discovery of "geometry" was misleading.

**Correction.** Five prespecified feature groups, each scored on the test split with cluster-aware
intervals, with the radius's cost charged to the group that uses it:
magnitude; metadata; geometry without the radius; geometry plus the revision projection; full geometry.

**Result.** Without the radius, AUC is 0.675 [0.489, 0.848] (A) and 0.737 [0.662, 0.823] (B). Adding
the projection barely moves it (0.686 / 0.750). Only the full set reaches 0.911 [0.779, 1.000] and
0.962 [0.948, 0.983] — at **46 ms and 28–37 KKT checks per event**, i.e. twenty times the cost of
certifying and forty times the cost of an OSQP re-solve. The large AUC is therefore a statement about a
diagnostic, not about information a data steward has, and the cost makes it unusable as triage.

## C6. The storage claim (claim withdrawn)

**Defect.** v1 reported a 366–429 byte "audit record" against a 807–1,080 byte problem. That record
omitted the multipliers (without which no bound can be evaluated) and the decision-time cost vector
(without which the revision has no base). It was not sufficient for anything, so the comparison was
between an unusable identifier record and a complete model.

**Correction.** A sufficient minimal record (weights, multipliers, decision-time linear costs, clocks,
digests) plus a per-cohort shared block (risk matrix, bounds, constraint rows, risk weight,
standardisation). `scripts/research/rtds_audit_record.py --export` writes it;
`--verify` reconstructs the certificate **in a fresh process** from that record, the shared block and
the newly available revision data only, and compares with the recorded results.

**Result.** 376 records reconstructed, 376 certificates reproduced, worst absolute bound gap **3.6e-15**.
Sizes: record 736 B (A) / 673 B (B); shared block 634 B / 390 B, amortized 6.2 B / 1.3 B per decision;
what a re-solve needs per decision once the same structure is shared is the audit cost vector only,
83 B / 63 B. So **CRI's stored state is larger than the marginal state a re-solve needs**. The storage
advantage does not exist; it is withdrawn. What remains true is narrower: the record certifies without
reconstructing the audit-time cost vector, and it is checkable by a third party.

## C7. Preregistration reconciliation (record-keeping)

The protocol was amended three times before any confirmatory computation (A1–A3: risk weight, added
metadata predictor set, AUC interval) and seven times after v1's results were observed (A4–A9 for C1–C6,
plus S1 for the later-period sample).
`PREREGISTRATION.md` §9 now separates those two blocks explicitly and marks the 2015–2024H1 sample as a
**reanalysis**: it had already been inspected before these corrections, so corrected results from it are
not a pristine confirmation. The untouched later period (2024-07-01 .. 2025-06-30) is reported
separately and is too small for cohort A (4 events) to settle anything.

---

## What this means for the contribution

The v1 numbers are invalid for the intended model and are preserved only as a record. What the corrected
study supports is narrower than v1 claimed:

* revisions do move the decision often, and now more often than v1 said (50.0% and 73.7%);
* the certificate is sound and reasonably complete, and is still *exactly* the classical active-set test
  on this data, so it remains redundant as a classifier;
* revision magnitude is still uninformative about materiality; geometry without the radius is moderately
  informative; the headline AUC was carried by a diagnostic too expensive to use;
* there is no storage advantage;
* CRI-U certifies nothing, now for a quantified and correctly specified reason.
