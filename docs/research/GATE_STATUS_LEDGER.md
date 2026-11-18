# Gate status ledger, second revision

Status is recorded against evidence, not against implementation. `passed` means a check ran and
produced the stated result; `partial` means the claim is narrower than the gate; `not_tested` means
nothing was measured; `blocked` means the environment could not support the check.

Branch `review/decision-intelligence-cri`, from `44cbbf3`. Second revision after the PR #5 review.

| Gate | Status | Evidence | What is missing |
|---|---|---|---|
| **A. Mathematical depth** | `passed` | Canonical convex program with an explicit KKT system. Six propositions stated with proofs: weak duality with the direction stated correctly, cost-independence of the dual feasible set, KKT sufficiency, the residual identity `regret ≤ ½r'Q⁻¹r + slack`, the invariance-interval proposition, and the worst-case bound over a set. Primal checked against exhaustive active-set enumeration, OSQP and Clarabel; dual gradient against central finite differences; weak duality asserted on every reported bound. | — |
| **B. Research originality** | `partial` | Prior art positioned explicitly against support-set invariancy analysis, parametric QP and qpOASES, Dey's MIP sensitivity programme at Georgia Tech ISyE, robust optimisation, DRO, and decision-focused learning. The claim is narrowed to formulation + composition + empirical characterisation; the support-function mechanism is disclaimed. | No external reader has confirmed the formulation is unoccupied rather than merely unusual. The most likely reviewer reading is "robust optimisation's support function applied to a dual bound", which is fair. |
| **C. Scientific evidence** | `partial` | 598 accepted events (600 attempted, 2 rejected with reasons), five seeds, moving-block bootstrap, 0 bound violations across seven iteration budgets, three independent solvers agreeing to `9.4e-14`, one real SEC revision end to end, a 40-trial worst-case study verified against vertex enumeration. | The 598-event study is synthetic. One real revision is a pipeline demonstration, not an empirical study. |
| **D. Decision usefulness** | `partial` | Coverage (`0.413` exact), tightness versus iteration budget (24.1 → 1.24 at five → 1.000 at twenty), separation of verified-zero / bounded / uncertified / infeasible verdicts, and a measured failure mode (hindsight 100% vs honest 52.5%). | **The time-advantage claim is withdrawn**: the certificate is 2.6–16.8× cheaper than the project's SLSQP re-solve but 1.8–6.7× *more expensive* than OSQP. No decision-quality improvement is claimed or measured. |
| **E. Generality** | `partial` | The same certificate runs unchanged on a capacity-allocation program with service floors and a group cap; bound sound rate `1.000` there. The uncertainty-set certificate is domain-agnostic by construction. | Structural transfer only. The capacity domain is synthetic and 0% of its events are exactly certifiable. |
| **F. Historical integrity** | `partial` → improved | A real restatement (Pfizer FY2023 revenue, 58,496 → 59,553 USD m) compiled from SEC EDGAR with accession numbers, acceptance instants, document URLs and payload SHA-256 digests. Lineage distinguishes six categories; the double-count guard and the look-ahead guard both demonstrated on that revision. | One revision, one period, a comparative-column restatement rather than a 10-K/A amendment. The evidence substrate is consumed, not extended. |
| **G. Engineering quality** | `passed` | Full suite **860 passed** (826 pre-existing + 34 new), decision layer 98 tests. The new tests skip cleanly without the `optimization` extra, so the existing `.[dev]` packaging contract is preserved. Every failure mode is explicit: invalid dual points refused, infeasible decisions suppress the bound, negative bounds rejected rather than clamped, unsupported revision kinds refused. | TypeScript typecheck and frontend build were not re-run: no frontend file changed in this revision. |
| **H. Explainability** | `partial` | Every certificate records the program digest, the constraint-structure digest, weights, multipliers and their provenance, both clocks, lineage, KKT residuals, the residual regret bound, per-stage timings, the iteration budget actually used, and a `guarantee_scope` string. | No user interface. |
| **I. Presentation** | `partial` | Technical report (second revision), generated tables from a single JSON, correction and disclosure log, novelty update, reproduction guide, architecture note, this ledger, machine-readable results, real-evidence artifacts. | No Decision Research Lab panel. Phase 7 was not implemented in this revision; see below. |
| **J. Intellectual honesty** | `passed` | Six claims withdrawn or corrected and listed as such. Nine defects disclosed with their detection method, including two found by this pass. Negative results kept: interior optima never certify, 45% violation rate under a 10× misspecification, singular risk matrices remove the bound, the free bound is 24× loose, the worst-case bound is 1.5× conservative, out-of-set corrections violate 87.5% of the time, and the certificate loses to OSQP on speed. | — |

## Verification actually run

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest --tb=short` | **`860 passed, 195 warnings in 137.25s`** |
| `scripts/research/cri_experiment.py --output artifacts/research` | exit 0, `runtime_seconds = 41.08`, 12 ledger entries, 0 failures |
| `scripts/research/sec_evidence_case.py --output artifacts/research/evidence` | exit 0, verdict `zero_regret_certified`, controls excluded for the right reasons |
| Three-solver agreement over 598 events | max objective disagreement `9.4e-14` |
| Active-set enumeration vs OSQP vs Clarabel, small instances | agree to `< 1e-9` |
| Iteration budgets 0/1/2/5/10/20/50/200 | requested ≥ performed in every case; bound monotone non-increasing |
| Worst-case bound vs 16-vertex enumeration, 40 trials | sound `1.000`, median conservatism `1.53×` |
| Negative-multiplier adversarial case | refused; the false bound it would have produced is exhibited (`-0.0858`) |
| `scripts/verify_master_spec.py` | canonical specification unchanged (size and SHA-256 verified) |

## Explicitly not tested

* **A Decision Research Lab interface.** Not implemented in this revision. There is nothing to
  accept, no screenshot, and no responsive or accessibility check. The certificate is inspectable
  as JSON and as the generated markdown tables, which is not the same thing.
* **Multiple real revisions.** One SEC restatement; no panel of firms, no estimated sensitivities.
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
