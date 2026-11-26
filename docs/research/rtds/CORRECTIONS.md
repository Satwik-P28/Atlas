# Methodological correction log

Version 1 of this study was published on branch `research/real-world-revision-study` (commits
`c51cf32`, `6aa925d`) and reviewed on PR #6. The review found that the audit-time program was built
incorrectly, which invalidates v1's headline numbers for the model the protocol defines. This log
records every defect, how it was detected, what replaced it, and how the replacement is verified.

The superseded outputs are preserved unchanged in `artifacts/research/rtds/superseded/`
(`dataset_v1.json`, `results_v1.json`, `tables_v1.md`, `dataset_v1.md`, and from the second pass
`results_v2.json`, `tables_v2.md`). They are not deleted, not regenerated and not edited: a reader must
be able to see what each version claimed.

C1–C7 are the first correction pass (version 2). C8–C12 are the final study-only comparison pass
(version 3), which adds no platform code and changes no part of CRI's mathematical core.

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
the projection barely moves it (0.686 / 0.750). Only the full set reaches 0.911 [0.779, 1.000] and 0.962 [0.948, 0.983] — at **46 ms and 28–37 KKT checks per event** in the version-2 run (41 ms in
the version-3 run; wall-clock moves with the machine, the ordering does not), i.e. twenty times the cost of
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

*C11 supersedes the ratio.* The 736-vs-83 comparison still charged the recorded decision to one arm only,
so it was withdrawn again and replaced by a functionally equivalent comparison: 978 B vs 813 B (A) and
885 B vs 743 B (B), i.e. **1.20× and 1.19×**, with both arms carrying the same decision state, provenance
and shared block.

## C7. Preregistration reconciliation (record-keeping)

The protocol was amended three times before any confirmatory computation (A1–A3: risk weight, added
metadata predictor set, AUC interval) and seven times after v1's results were observed (A4–A9 for C1–C6,
plus S1 for the later-period sample).
`PREREGISTRATION.md` §9 now separates those two blocks explicitly and marks the 2015–2024H1 sample as a
**reanalysis**: it had already been inspected before these corrections, so corrected results from it are
not a pristine confirmation. The untouched later period (2024-07-01 .. 2025-06-30) is reported
separately and is too small for cohort A (4 events) to settle anything.

## C8. No head-to-head baseline against KKT + feasible descent (design omission; changes the headline)

**Defect.** The study reported 94.7% three-way coverage as a result about CRI. It is not one. The
material half is produced by `greedy_repair`, a feasible descent that is independent of the certificate,
and the immaterial half coincided with KKT stability — which the study noted, but without ever running
the obvious combined baseline. A reader could reasonably have read 94.7% as a property of the
certificate.

**Correction.** Five workflows are now scored side by side on their own verdict rules, coverage, errors,
abstentions and end-to-end runtime: KKT only; KKT + greedy descent; CRI only; CRI + greedy descent; and
an OSQP re-solve as the ground truth. The descent is described as *partial reoptimisation*, and it is
charged only to events whose first stage does not settle them (with a `descent always` variant also
reported). Runtime includes program compilation and the original decision solve for every workflow.

**Result.** On both cohorts the two combined workflows publish **identical verdicts on every event**: 0
disagreements, identical certified sets, 0 immaterialities and 0 materialities added by the certificate.
The certificate's incremental classification utility is zero, and it is 0.6–0.7 ms per audit slower than
KKT + descent. OSQP is faster still (0.93–0.97 ms against 1.30–2.08 ms) and settles 100% of events with
no abstentions. At these dimensions the simpler workflows dominate CRI, not merely match it; this is now
the paper's central result.

## C9. CRI-U answered one question and reported it as another (interpretation; changes what the zero means)

**Defect.** Both v2 arms were centred on zero. The decision-base arm was described as "the total
correction relative to the decision vintage", which reads as a statement about the observed revision. A
zero-centred box is not centred on an observed correction; in about half the events the observed
correction was not even inside it, so the guarantee did not apply to those events at all. Reporting 0/38
and 0/114 as a property of CRI-U on historical revisions was therefore unsupported.

**Correction.** Three arms, reported separately: (1) prospective, audit-time base, centre zero — a
*further* correction of typical size; (2) prospective, decision-time base, centre zero — the total
correction if it were any vector in a typical box; (3) post-audit, decision-time base, centre = the
**observed** cost revision — the revision is known, but wrong by a typical revision error. Widths remain
the training split's mean `|Δc|` per input. Each arm reports coverage, containment where containment is
measurable, and the guarantee conditional on containment; the audit-base arm's containment is not
measured and no rate is quoted for it.

**Result.** Zero certifications in all three arms. Containment is 19/38 and 56/114 (50.0%, 49.1%) for the
prospective decision-base arm and 100% by construction for the post-audit arm. Conditional certification
is 0% in every measurable arm, and median bounds are 0.58–1.91 against τ = 1e-3. The failure is the
tolerance against revisions of this size, not the choice of centre — and the earlier zero was neither a
general failure (the sets often did not contain the revision) nor a confirmed one (the observed-centred
arm had not been run).

## C10. Test revisions entered the sensitivity grid's uncertainty widths (implementation defect; no headline impact)

**Defect.** `sensitivity_grid` computed `block["half_width_cost"]` from events with split in
`{train, test}`, contradicting the train-only rule that `analyse_cohort` already followed. The grid does
not produce the headline materiality or certified-immaterial columns, so the reported figures were not
affected — but the pathway was a leak waiting to happen.

**Correction.** One implementation, `train_half_width(train, block)`, is used by the main analysis, the
sensitivity grid and the audit-record export. A regression test builds a cohort whose test revision is
enormous and asserts that the width the grid passes to every event equals the train-only estimate and
differs from the pooled one.

## C11. The storage comparison was not functionally equivalent (claim withdrawn; ratio 8.3× → 1.2×)

**Defect.** C6 fixed the certificate record but still compared it with a cost vector alone. A re-solve
cannot audit a recorded decision from a cost vector: it also needs the recorded weights, the
decision-time costs and the vintage/provenance metadata. Charging that state to one arm made the
certificate look 8× smaller than it is.

**Correction.** Both arms now carry the same per-decision state (weights, decision-time costs, clocks,
vintages, horizon, digests, observation digest) and the same shared block (matrix, bounds, constraints,
risk weight, standardisation, cohort provenance and manifest digest). The CRI arm adds the multipliers
and the revision delta; the re-solve arm adds the audit-time cost vector. Median per-decision sizes and
the amortized shared cost are reported for both, with the ratio.

**Result.** CRI arm 978 B vs re-solve arm 813 B (cohort A) and 885 B vs 743 B (cohort B): **1.20× and
1.19×**, larger rather than smaller. The storage advantage is still absent; it is now absent under a
comparison a reviewer cannot call apples-to-oranges.

## C12. Reanalysis labelling and the unexecuted sensitivity families (record-keeping)

**Defect.** `REPORT.md` called the 2015–2024H1 results a reanalysis in its body, but the abstract and the
generated tables still called the split "confirmatory". The unrun mapping and horizon studies were listed
in an amendment but could still be read as a caveat rather than as a limitation on generality.

**Correction.** The abstract, every table heading, the JSON (`sample_label`) and the cohort blocks now
say *post-results reanalysis*. The unexecuted mapping-variant and horizon-grid studies are reported as
**limitations, not evidence**: no claim in the paper is a test of another functional form or another
horizon, and §6 repeats this for readers who skip the sensitivity subsection.

---

## What this means for the contribution

The v1 numbers are invalid for the intended model and are preserved only as a record. What the study
supports, after two correction passes, is narrower than either earlier version claimed:

* revisions do move the decision often (50.0% and 73.7% on the reanalysed 2015–2024H1 split);
* the certificate is sound and covers 80% and 89.5% of immaterial events, and is *exactly* the classical
  active-set test on this data;
* **CRI has no measurable incremental utility over KKT + feasible descent** — identical verdicts, no
  fewer errors, and slower — and plain OSQP re-solving is faster than both combined workflows while
  settling every event;
* revision magnitude is uninformative about materiality; geometry without the radius is moderately
  informative; the headline AUC was carried by a diagnostic that costs ≈41 ms per event;
* there is no storage advantage under a functionally equivalent comparison (1.2× the re-solve record);
* CRI-U certifies nothing under any of its three questions, and the post-audit question centred on the
  observed revision had not previously been asked.
