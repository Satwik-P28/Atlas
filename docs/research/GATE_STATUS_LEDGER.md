# Gate status ledger, second revision

Status is recorded against evidence, not against implementation. `passed` means a check ran and
produced the stated result; `partial` means the claim is narrower than the gate; `not_tested` means
nothing was measured; `blocked` means the environment could not support the check.

Branch `review/decision-intelligence-cri`, from `44cbbf3`. Second revision after the PR #5 review.

| Gate | Status | Evidence | What is missing |
|---|---|---|---|
| **A. Mathematical depth** | `passed` | Canonical convex program with an explicit KKT system. Six propositions stated with proofs: weak duality with the direction stated correctly, cost-independence of the dual feasible set, KKT sufficiency, the residual identity `regret ≤ ½r'Q⁻¹r + slack`, the invariance-interval proposition, and the worst-case bound over a set. Primal checked against exhaustive active-set enumeration, OSQP and Clarabel; dual gradient against central finite differences; weak duality asserted on every reported bound. | — |
| **B. Research originality** | `partial` | Prior art positioned explicitly against support-set invariancy analysis, parametric QP and qpOASES, Dey's MIP sensitivity programme at Georgia Tech ISyE, robust optimisation, DRO, and decision-focused learning. The claim is narrowed to formulation + composition + empirical characterisation; the support-function mechanism is disclaimed. | No external reader has confirmed the formulation is unoccupied rather than merely unusual. The most likely reviewer reading is "robust optimisation's support function applied to a dual bound", which is fair. |
| **C. Scientific evidence** | `partial` | 598 accepted events (600 attempted, 2 rejected with reasons), five seeds, moving-block bootstrap, **0 bound violations beyond the solver's resolution** across seven iteration budgets (`0.941` strict, `1.000` resolution-aware; the 35 strict exceedances are all inside the solver spread and traced to constraint violations in the lower-objective solver), three independent solvers agreeing to `1.4e-14`, one real SEC revision end to end, a 40-trial worst-case study verified against vertex enumeration. | The 598-event study is synthetic. One real revision is a pipeline demonstration, not an empirical study. |
| **D. Decision usefulness** | `partial` | Coverage (`0.413` certified within residual, 95% interval `[0.373, 0.453]`), tightness versus iteration budget (24.1 → 1.24 at five → 1.000 at twenty), separation of verified-zero / bounded / uncertified / infeasible verdicts, and a measured failure mode (hindsight 100% vs honest 52.5%). | **The time-advantage claim is withdrawn**: the certificate is 2.6–16.8× cheaper than the project's SLSQP re-solve but 1.8–6.7× *more expensive* than OSQP. No decision-quality improvement is claimed or measured. |
| **E. Generality** | `partial` | The same certificate runs unchanged on a capacity-allocation program with service floors and a group cap; bound sound rate `1.000` there. The uncertainty-set certificate is domain-agnostic by construction. | Structural transfer only. The capacity domain is synthetic and 0% of its events are exactly certifiable. |
| **F. Historical integrity** | `partial` → improved | A real revision (Pfizer FY2023 revenue, 58,496 → 59,553 USD m) compiled from SEC EDGAR with accession numbers, acceptance instants, document URLs and payload SHA-256 digests, plus both primary 10-K documents sourced for the characterisation. Lineage distinguishes six categories and resolves supersession/withdrawal against the audit clock; the double-count guard, the look-ahead guard and a post-cut-off successor are demonstrated on that revision. | One revision, one period, a conforming recast of comparatives rather than a 10-K/A amendment or an error correction. The evidence substrate is consumed, not extended. |
| **G. Engineering quality** | `passed` | Full suite **933 passed** (171 of them in the decision layer across `tests/test_decision_{program,certificate,certification,properties,counterexample,lineage}.py`). The new tests skip cleanly without the `optimization` extra, so the existing `.[dev]` packaging contract is preserved. Every failure mode is explicit: invalid dual points refused, infeasible decisions suppress the bound, negative bounds rejected rather than clamped, unsupported revision kinds refused, ambiguous or cyclic lineage refused with the offending ids named. | TypeScript typecheck and frontend build were not re-run: no frontend file changed in this revision. |
| **H. Explainability** | `partial` | Every certificate records the program digest, the constraint-structure digest, weights, multipliers and their provenance, both clocks, lineage, KKT residuals, the residual regret bound, per-stage timings, the iteration budget actually used, and a `guarantee_scope` string. | No user interface. |
| **I. Presentation** | `partial` | Technical report (second revision), generated tables from a single JSON, correction and disclosure log, novelty update, reproduction guide, architecture note, this ledger, machine-readable results, real-evidence artifacts. | No Decision Research Lab panel. Phase 7 was not implemented in this revision; see below. |
| **J. Intellectual honesty** | `passed` | Six claims withdrawn or corrected and listed as such. Nineteen defects disclosed with their detection method across four review passes, including six found by an independent review of this branch after it was first published and four by the review of `6430b5b`. The `1e-18`-bound-versus-`1e-15`-measurement discrepancy is diagnosed rather than waved through: solver error, shown by the constraint violation of the lower-objective solver, and never reported as an exact guarantee. Negative results kept: interior optima never certify, 45% violation rate under a 10× misspecification, singular risk matrices remove the bound, the free bound is 24× loose, the worst-case bound is 1.5× conservative, out-of-set corrections violate 87.5% of the time, and the certificate loses to OSQP on speed. | — |

## Verification actually run

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **`933 passed in 138.97s`** (908 before this pass; 23 new lineage tests, 2 precision tests) |
| `scripts/research/cri_experiment.py --output artifacts/research` | exit 0, `runtime_seconds = 41.08`, 12 ledger entries, 0 failures |
| `scripts/research/sec_evidence_case.py --output artifacts/research/evidence` | exit 0, verdict `zero_regret_within_residual`, characterisation `conforming_recast` (formal restatement `false`), controls excluded for the right reasons |
| Three-solver agreement over 598 events | max objective disagreement `9.4e-14` |
| Active-set enumeration vs OSQP vs Clarabel, small instances | agree to `< 1e-9` |
| Iteration budgets 0/1/2/5/10/20/50/200 | requested ≥ performed in every case; bound monotone non-increasing |
| Gap identity, 5 scales × 0–3 inequality rows × random dual points | holds within the reported forward-error estimate at every sampled instance; a gross violation refuses the certificate |
| Deterministic lineage: chains of 3 and 4, branches, cycles, withdrawn middles, version and effective-time inversions | each refused or resolved to the single operative version; no chain applies two absolute deltas |
| Two-clock eligibility: backdated, public-but-not-effective, boundary instants, after-hours | excluded with distinct `not_public_at_audit` / `not_effective_at_audit` reasons; inclusive at the exact instant |
| Bound vs independently measured regret, 598 events with a bound | `35` exceed their bound outright (`0.941` strict), **0** beyond the solver's resolution (`1.000`); among the 247 certified, worst excess `0.26×` resolution and emitted bound never below the conservative measurement beyond resolution |
| Ellipsoid geometry, diagonal and correlated shapes | support, maximiser, membership and curvature envelope agree; boundary points are members to `1e-12` |
| Temporal lineage, both sides of the cut-off | post-cut-off successor does not suppress; post-cut-off withdrawal does not unapply; version/effective inversion and cycles refused |
| Worst-case bound vs 16-vertex enumeration, 40 trials | sound `1.000`, median conservatism `1.53×` |
| Negative-multiplier adversarial case | refused; the false bound it would have produced is exhibited (`-0.0858`) |
| `scripts/verify_master_spec.py` | canonical specification unchanged (size and SHA-256 verified) |

## Explicitly not tested

* **A Decision Research Lab interface.** Not implemented in this revision. There is nothing to
  accept, no screenshot, and no responsive or accessibility check. The certificate is inspectable
  as JSON and as the generated markdown tables, which is not the same thing.
* **Multiple real revisions.** One SEC revenue reclassification; no panel of firms, no estimated
  sensitivities.
* **TypeScript / frontend build.** No frontend file changed.
* **qpOASES or a parametric-solver comparison.** Documented as the right competitor for a
  sequential-revision workflow and not run.
* **A calibrated uncertainty set.** CRI-U takes the set as declared and measures the consequence of
  that declaration; it makes no coverage claim and was not compared against a conformal set.
* **Large-scale performance.** Largest measured instance is 128 variables on CPU.

## Specification handling

`ATLAS_MASTER_SPEC.md` is **unchanged**, byte-verified by `scripts/verify_master_spec.py`. The
research requirements are additive desired state, not an amendment to the canonical document, and
the specification-change process of §24 has not been completed for them. That is one reason Gate B
remains `partial`.
