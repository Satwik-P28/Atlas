# Phase 5 readiness

## Acceptance matrix

| Gate | Status | Evidence / limitation |
|---|---|---|
| Existing functionality stable | **Pass** | full backend suite on schema 7; prior browser suites retained |
| Multi-instrument support | **Partial, implemented for synthetic fixture** | 935 aligned active returns; not a real universe |
| Universe coverage limitations explicit | **Pass** | `HISTORICAL_UNIVERSE_INTEGRITY.md`; `survivorship_bias_free: false` |
| Out-of-sample validation | **Pass for mechanics** | rolling/expanding, embargo, untouched test, 24-attempt log |
| Contamination safeguards | **Pass** | test never used for selection; partition tests; code review |
| Rates/bond pricing | **Pass** | official Treasury curve, par identity, manual duration, DV01 |
| Derivatives adapter | **Pass** | BSM price/Greeks/parity/IV; not a market quote |
| Portfolio risk reconciled | **Pass** | component contributions sum to volatility within 1e-10 |
| Optimization constraints | **Pass** | sum, cap, long-only, target and infeasibility tests |
| Compiler/Model Forge integration | **Pass** | eight typed operators and compiler execution test |
| Reproducibility manifests | **Partial** | stored inputs/results, hashes, export; no vendor bytes for a real universe |
| Both UI applications | **Pass** | `/lab/institutional`; save/reopen/fork/compare/export browser-tested |
| Regressions | **Pass** | full Phase 1–5 backend suite; frontend build |
| Benchmarks measured | **Pass** | `PHASE5_BENCHMARKS.md` and JSON artifact |
| Honest feature classification | **Pass** | implemented/partial/unsupported/planned below |

## Implemented

Synthetic multi-asset alignment and membership; delisted path; rolling/expanding
walk-forward with embargo; train-only parameter selection; validation family selection;
single frozen test evaluation; complete attempt log; cost sensitivity; parameter stability;
block-bootstrap and Bonferroni warning; official Treasury curve bootstrap; bond analytics
and shocks; BSM analytics; covariance risk, beta, VaR/ES, drawdown, sector exposure and
linear stress; constrained minimum-variance/target-return optimization; FEC operators;
schema 7 persistence; two Lab applications; manifest export.

## Partial

* **Multi-instrument data:** only a deterministic synthetic fixture. IBM remains the only
  real price series and is not mixed into the institutional portfolio.
* **Reproducibility:** deterministic against stored fixtures and hashes, but there is no
  provider byte archive or real delisting-return dataset.
* **Stress testing:** equity beta shocks only; rate and volatility shocks are marked
  unsupported rather than approximated with invented inputs.
* **UI application versioning:** fork creates a new research object, but there is no
  version diff/merge workflow.

## Unsupported

Callable/MBS/credit bonds, business-day calendars, inflation/swap/OIS curves, American or
stochastic-volatility options, volatility surfaces, factor models, FX, shorting, borrow,
turnover/sector optimization constraints, transaction costs in optimization, real multi-
security ingestion, live trading and order routing.

## Planned / Phase 6 dependencies

See `PHASE6_CONTRACT.md`: a real point-in-time universe with licensed data; a proper
QP/estimation layer; richer fixed-income and derivative models; event/probability research;
and a unified risk surface only after data rights and validation exist.

## Missing supplied document

`ATLAS_MASTER_SPEC.md` version 1.1 is not in the repository. This is reported rather than
silently replaced. `docs/PHASE5_CONTRACT.md` plus these implementation records are the
in-repo authority until the supplied master document is added.
