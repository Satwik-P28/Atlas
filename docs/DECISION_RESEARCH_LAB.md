# Decision Research Lab

The decision layer is a convex-programming substrate with an audit trail. It answers a question
the rest of Atlas does not: *given a decision taken under the evidence available at the time, what
can be proved about it now that the evidence has changed — or turned out to be uncertain?*

The research claim and its evidence are in
[`research/ATLAS_CRI_TECHNICAL_REPORT.md`](research/ATLAS_CRI_TECHNICAL_REPORT.md); the corrections
made after review are in [`research/CORRECTIONS_AND_DISCLOSURE_V2.md`](research/CORRECTIONS_AND_DISCLOSURE_V2.md);
the current gate status is in [`research/GATE_STATUS_LEDGER.md`](research/GATE_STATUS_LEDGER.md).

## Where it sits

```
evidence kernel (four time dimensions, revisions, rights)
        │
        │  inputs: cost vector, risk matrix, feasible set, as_of, evidence ids
        ▼
┌───────────────────────────────────────────────────────────────────────┐
│ atlas.decision                                                         │
│                                                                        │
│  problem.py      canonical convex program, digests, feasibility        │
│      │           (digest() = the mathematics + provenance;            │
│      │            structure_digest() = constraint geometry only)      │
│  qp.py           primal candidate, validated dual points, KKT report,  │
│      │           residual→regret certificate, dual ascent with an      │
│      │           exact iteration budget                               │
│  revision.py     revision → declared perturbation; two clocks; lineage │
│      │  certificate.py                                                 │
│      │    ├─ exact KKT test (least squares, LP fallback)              │
│      │    ├─ duality bound from the recorded multipliers              │
│      │    └─ radii (invariance, regret tolerance)                     │
│  uncertainty.py  worst-case bound over a set of admissible corrections │
│  reference.py    OSQP, Clarabel, exhaustive active sets — verification  │
│  baselines.py    equal weight, min-variance, mean-CVaR, robust box/    │
│                  ellipsoid, strong-convexity bound, Taylor estimate    │
│  estimators.py   sample and Ledoit-Wolf covariance                     │
│  metrics.py      regret, turnover, CVaR, moving-block bootstrap        │
│  experiment.py   manifests, dataset digests, trial ledger              │
└───────────────────────────────────────────────────────────────────────┘
        │
        ▼
saved decision record: program digest, structure digest, weights,
multipliers, clocks, evidence ids, certificate, declared sensitivity
```

The layer never creates a second evidence store, a second time model or a second permission
system. Provenance comes from the existing temporal kernel; the revision compiler only *reads*
availability instants and refuses anything it cannot date.

## Why a canonical program and not a modelling language

A certificate has to be checkable. Restricting the program to a quadratic objective with linear
constraints keeps the KKT system explicit, so optimality can be verified from the weights and a
multiplier vector alone. Every reported number is a residual against a stated tolerance rather than
a solver's self-assessment — and, since the second revision, a residual converted into a *quantity*
(`0.5 r'Q^-1 r + slack`), because a tolerance is not a proof.

The same canonical form carries three domains:

| Domain | `Q` | `c` | Feasible set |
|---|---|---|---|
| Portfolio allocation | `λ · Σ_returns` | `−μ` | budget, position limits |
| Capacity allocation | `λ · Σ_demand` | `−margin` | capacity, service floors, group cap |
| Evidence-linked allocation | `λ · Σ` | `−growth · scale` | budget, position limits |

The certificate code contains no finance vocabulary, which is why the operational adapter
exercises it unchanged, and why the SEC case study could reuse it without modification.

## The six verdicts

A useful certificate has to distinguish states that a single boolean would conflate:

| verdict | meaning |
|---|---|
| `zero_regret_within_residual` | the recorded decision satisfies the KKT system of the corrected program within a declared tolerance; the verdict reports the validated residual bound (`0.5 r'Q⁻¹r + slack`) and the residuals behind it, never a literal zero |
| `regret_bounded` | a valid upper bound exists; whether it is small is a separate flag (`meets_tolerance`) against a user-declared tolerance |
| `uncertified` | no bound and no residual certificate — the honest answer when the risk matrix is singular or no dual point is available |
| `infeasible_under_revision` | the recorded decision is infeasible for the corrected program; no regret bound is claimed, because the recorded point is not a decision the auditor may take |
| `revision_already_incorporated` | everything supplied is already inside the recorded vintage; there is nothing to audit |
| `revision_not_eligible` | the revision is not public at the audit clock, or unsupported, or unmapped |

## Failure behaviour

The layer prefers to refuse rather than to substitute:

* a risk matrix that is not positive definite → the dual bound is refused with a reason, and only
  the residual KKT test is offered;
* a revision whose kind is not a linear-objective perturbation → refused, reason recorded;
* a decision with no `as_of` clock → no revision can be compiled, reason recorded;
* a recorded multiplier vector with a negative entry, a non-finite entry, the wrong dimension or a
  mismatched constraint-structure digest → refused, and the false bound it would have produced is
  *not* reported;
* a dual value above the primal (mathematically impossible) → the bound is refused and the
  inconsistency recorded, never clamped to a comfortable zero;
* a revision published before the decision clock → excluded as already incorporated, unless the
  caller explicitly asks for the different question ("the model missed public evidence");
* a correction drawn outside the declared uncertainty set → the violation is measured and reported,
  not hidden.

## Reproducing a decision record

A saved record contains the problem digest, the structure digest, the weights, the multiplier
vector, the decision and audit clocks, the evidence identifiers, the declared sensitivity, the
certificate, and the timings of each stage. The digest covers only the mathematics and the
provenance, so two records with the same program but different provenance compare equal on the
mathematics and differ on the provenance — which is the distinction an audit needs.

Exact replay requires the frozen program and the frozen multiplier vector; both are recorded, so an
audit can recompute the bound without any optimisation. Recomputing the *solution* from a data
snapshot is a separate operation and is labelled as a current-state recomputation elsewhere in
Atlas; this layer does not claim pinned replay of upstream data.

## What it costs, honestly

Against the SLSQP pipeline the rest of Atlas uses, a certificate is 2.6–16.8× cheaper than a
re-solve at matched dimensions. Against **OSQP**, it is 1.8–6.7× *slower*. The certificate's value
is that it needs only a multiplier vector and produces a guarantee about a fixed recorded decision;
it is not a fast QP solver and does not claim to be.

Producing the multipliers in the first place costs an order of magnitude more than reusing them, so
a workflow that must solve the primal anyway gains nothing from certification. The case for the
layer is audit, not throughput.

## Test strategy

* **Independent reference solvers.** The primal is checked against exhaustive active-set
  enumeration, OSQP and Clarabel. No test compares the solver to itself.
* **Finite differences.** The dual gradient is checked numerically; this is what found the sign
  defects in the first pass.
* **Weak duality as an assertion, in the correct direction.** Every reported dual value must not
  exceed the primal, and the gap must be an upper bound on regret.
* **Proof by enumeration.** The worst-case bound is checked against every vertex of the set on
  small instances. This is what found the unsound derivation described in §2.1 of the corrections
  log; a sampled check would have missed it.
* **Soundness against re-solves.** 598 events in the experiment, plus the vertex enumerations, each
  checked against an independent solver.
* **Adversarial inputs.** Negative multipliers, mismatched geometry, infeasible recorded decisions,
  withdrawn and superseded revisions, singular risk matrices, corrections outside the declared set.

## Running it

```bash
.venv/bin/python -m pip install -e ".[dev,terminal,optimization]"
.venv/bin/python -m pip install "osqp>=1,<2" "clarabel>=0.11,<1"
.venv/bin/python -m pytest -q
.venv/bin/python scripts/research/cri_experiment.py --output artifacts/research
.venv/bin/python scripts/research/sec_evidence_case.py --output artifacts/research/evidence
```

`optimization` (SciPy) is a separate extra by design: the packaging contract forbids pulling the
numerical stack into `dev`, and the decision tests skip cleanly without it. OSQP and Clarabel are
reference-only dependencies; the certificate never imports them.
