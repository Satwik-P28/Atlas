# Gate status ledger

Status is recorded against evidence, not against implementation. `passed` means a check ran
and produced the stated result; `partial` means the claim is narrower than the gate; `not_tested`
means nothing was measured; `blocked` means the environment could not support the check.

Branch: `review/decision-intelligence-cri`, created from `44cbbf3`
(`review/price-intelligence-v3.2-temporal`).

| Gate | Status | Evidence | What is missing |
|---|---|---|---|
| **A. Mathematical depth** | `passed` | Canonical convex program with explicit KKT system (`src/atlas/decision/problem.py`, `qp.py`). Propositions 1–5 stated with proofs (technical report §5). Primal checked against exhaustive active-set enumeration and a closed form. Dual gradient checked by central finite differences. Weak duality asserted on every reported bound. 64 dedicated tests. | — |
| **B. Research originality** | `partial` | Prior-art audit names the closest work (support-set invariancy sensitivity analysis; conformal contextual robust optimisation; worst-case-regret DFL) and states plainly that the mathematics is classical. The claimed difference is formulation + a free-certificate composition + an empirical failure characterisation. | No independent literature review by a second reader, and no argument that the formulation is *unoccupied* rather than merely *unaddressed in these terms*. |
| **C. Scientific evidence** | `partial` | 598 seeded revision events, 5 seeds, moving-block bootstrap intervals, 0 bound violations, exactness verified to `1.7e-17`, tightness versus three competitors, a misspecification failure curve, a cap-tightness sweep. Full manifests and an append-only trial ledger. | All data are synthetic. No real market, filing or operational series was available. |
| **D. Decision usefulness** | `partial` | Coverage (41% exact, 43% certified-or-bounded at `1e-4`), cost (3×–26× cheaper than re-solving), and a demonstrated audit failure mode (hindsight reports 100% stability against 52.5% actual). | No out-of-sample utility improvement is claimed or measured. The branch does not show that certification makes decisions *better*, only that it makes them *auditable*. |
| **E. Generality** | `partial` | The same certificate runs unchanged on a capacity-allocation program with service floors and a group cap; bound sound rate 1.000 there. | The transfer is structural. No operational benefit was measured, and the demand process is synthetic. |
| **F. Historical integrity** | `partial` | Two-clock eligibility (decision vs audit), refusal of unsupported perturbation kinds, refusal to audit without a decision clock, evidence identifiers carried on the program, hindsight arm labelled as leakage-contaminated. | No real SEC revision was compiled end-to-end in this branch; the temporal substrate it consumes is tested elsewhere in the repository. |
| **G. Engineering quality** | `passed` | Full suite **826 passed** (762 pre-existing + 64 new); the new tests skip cleanly on an install without the `optimization` extra, so the existing `.[dev]` contract is preserved; import contract test passes; failure modes are explicit rather than silently repaired; cost measured at five problem sizes. | TypeScript typecheck and frontend build were not re-run because no frontend file changed. |
| **H. Explainability** | `partial` | Every certificate records the program digest, weights, multiplier vector, both clocks, evidence identifiers, the declared sensitivity, residuals and a `guarantee_scope` string. A reader can recompute the bound from the record with linear algebra alone. | No user interface. There is no way to inspect a certificate in the terminal UI. |
| **I. Presentation** | `partial` | Prior-art audit, preregistration, technical report, architecture note, this ledger, reproducible script, machine-readable results, generated tables. | No Decision Research Lab panel, no charts, no browser acceptance. Phase 11 was not attempted. |
| **J. Intellectual honesty** | `passed` | Negative results retained (interior optima never certified; 45% violation rate under misspecification; singular risk matrices remove the bound; the free bound is 24× loose). Six implementation defects disclosed with their detection method. Citations marked as fetched or standard. No fabricated dataset, benchmark or improvement. | — |

## Verification actually run

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest --tb=no` | `826 passed, 1 warning in 134.57s` |
| `.venv/bin/python -m pytest tests/test_decision_program.py tests/test_decision_certificate.py` | `64 passed in 2.43s` |
| `.venv/bin/python scripts/research/cri_experiment.py --output artifacts/research` | exit 0, `runtime_seconds ≈ 19.6`, ledger 11 entries, 0 failures |
| Independent active-set enumeration vs solver, 5 seeds | max objective difference `< 1e-10` |
| Finite-difference dual gradient | max deviation `< 1e-8` |
| Bound soundness, 598 events × 4 bound arms | 0 violations |
| Exact certificate vs realized regret | max `1.68e-17` |

## Explicitly not tested

* **Real market or filing data.** No licensed archive is available in this environment. Every
  financial number in the report is synthetic and labelled as such.
* **Browser / UI acceptance.** Phase 11 was not implemented, so there is nothing to accept.
  No screenshot, click-through or responsive check is claimed.
* **TypeScript / frontend build.** No frontend file changed in this branch.
* **DRO, conformal and worst-case-regret DFL competitors.** These are documented as the
  correct comparators for a *calibrated uncertainty set* claim, which this branch does not
  make. They are not implemented.
* **Pinned replay of upstream data.** The certificate replays a frozen program; it does not
  replay the data snapshot that produced it.
* **Large-scale or GPU performance.** Largest measured instance is 128 variables on CPU.

## Specification handling

`ATLAS_MASTER_SPEC.md` is **unchanged**. It is byte-verified by
`scripts/verify_master_spec.py`, and the research requirements in this branch are additive
desired state, not an amendment to the canonical document. The specification-change process
required by §24 of the master specification has not been completed for these requirements,
which is one reason Gate B is `partial`.
