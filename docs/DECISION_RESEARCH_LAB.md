# Decision Research Lab

The decision layer is a convex-programming substrate with an audit trail. It exists to answer a
question the rest of Atlas does not: *given a decision that was taken under the evidence
available at the time, what can be proved about it now that the evidence has changed?*

This document is the architecture note. The research claim and its evidence are in
[`research/ATLAS_CRI_TECHNICAL_REPORT.md`](research/ATLAS_CRI_TECHNICAL_REPORT.md); the
currently unimplemented parts are in
[`research/GATE_STATUS_LEDGER.md`](research/GATE_STATUS_LEDGER.md).

## Where it sits

```
evidence kernel (four time dimensions, revisions, rights)
        │
        │  inputs: cost vector, risk matrix, feasibility set, as_of, evidence ids
        ▼
┌──────────────────────────────────────────────────────────────┐
│ atlas.decision                                               │
│                                                              │
│  problem.py    canonical convex program + feasibility        │
│      │                                                       │
│  qp.py         primal candidate, dual bound, KKT residuals   │
│      │                                                       │
│  revision.py   revision → declared perturbation, two clocks  │
│      │                                                       │
│  certificate.py exact zero-regret test, bounded regret,      │
│                 radii, degeneracy report                     │
│      │                                                       │
│  baselines.py  equal weight, min-variance, mean-CVaR,        │
│                 robust box/ellipsoid, competing bounds       │
│  estimators.py sample and Ledoit-Wolf covariance            │
│  metrics.py    regret, turnover, CVaR, block bootstrap       │
│  experiment.py manifests, dataset digests, trial ledger      │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
saved decision record: program digest, weights, multipliers,
clocks, evidence ids, certificate, declared sensitivity
```

The layer never creates a second evidence store, a second time model or a second permission
system. Provenance comes from the existing temporal kernel; the revision compiler only *reads*
availability instants and refuses anything it cannot date.

## Why a canonical program and not a modelling language

A certificate has to be checkable. Restricting the program to a quadratic objective with linear
constraints keeps the KKT system explicit, so optimality can be verified from the weights and a
multiplier vector alone. Every reported number is a residual against a stated tolerance rather
than a solver's self-assessment.

The same canonical form carries two domains:

| Domain | `Q` | `c` | Feasible set |
|---|---|---|---|
| Portfolio allocation | `λ · Σ_returns` | `−μ` | budget, position limits |
| Capacity allocation | `λ · Σ_demand` | `−margin` | capacity, service floors, group cap |

The certificate code contains no finance vocabulary, which is why the operational adapter
exercises it unchanged. This is structural generality, not evidence of operational benefit.

## Failure behaviour

The layer prefers to refuse rather than to substitute:

* a risk matrix that is not positive definite → the dual bound is refused with a reason, and
  only the exact KKT test is offered;
* a revision whose kind is not a linear-objective perturbation → refused, reason recorded;
* a decision with no `as_of` clock → no revision can be compiled, reason recorded;
* a dual value above the primal (mathematically impossible) → the bound is refused and the
  inconsistency recorded, never clamped to a comfortable zero.

## Reproducing a decision record

A saved record contains the problem digest, the weights, the multiplier vector, the decision
and audit clocks, the evidence identifiers, the declared sensitivity, and the certificate. The
digest covers only the mathematics, so two records with the same program but different
provenance compare equal on the mathematics and differ on the provenance — which is exactly the
distinction an audit needs.

Exact replay of a decision requires the frozen program and the frozen multiplier vector; both
are recorded, so an audit can recompute the bound without any optimisation. Recomputing the
*solution* from a data snapshot is a separate operation and is labelled as a current-state
recomputation elsewhere in Atlas; this layer does not claim pinned replay of upstream data.

## Test strategy

* **Independent reference solvers.** The primal is checked against exhaustive active-set
  enumeration (exact for small `n`) and against a closed form for diagonal risk matrices. No
  test compares the solver to itself.
* **Finite differences.** The dual gradient is checked numerically; this is what found the sign
  defects documented in the preregistration.
* **Weak duality as an assertion.** Every reported dual value must not exceed the primal.
* **Soundness against re-solves.** 120 random revisions in the test suite and 598 in the
  experiment, each checked against an independent re-solve.
* **Property-based tests.** Feasibility, monotonicity and bound validity over random PSD
  problems.

## Running it

```bash
.venv/bin/python -m pip install -e ".[dev,terminal,optimization]"
.venv/bin/python -m pytest tests/test_decision_program.py tests/test_decision_certificate.py -q
.venv/bin/python scripts/research/cri_experiment.py --output artifacts/research
```

`optimization` (SciPy) is a separate extra by design: the packaging contract forbids pulling
the numerical stack into `dev`, and the decision tests skip cleanly without it.
