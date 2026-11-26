# Phase 5 implementation — institutional research

Status: **implemented vertical slice, independently tested, browser-verified on schema 7.**
See [PHASE5_READINESS.md](PHASE5_READINESS.md) for the acceptance matrix and unsupported items.

## Delivered capabilities

| Capability | State | Evidence |
|---|---|---|
| Multi-instrument panel and membership history | Implemented for a clearly synthetic fixture | `src/atlas/institutional/universe.py`; 935 aligned active returns |
| Delisted-security representation | Implemented, not forward-filled | `SYN-DELTA` ends 2023-12-29; excluded from active return matrix |
| Rolling and expanding walk-forward | Implemented | `src/atlas/institutional/validation.py`; train/validation/test and embargo |
| Parameter search and attempt retention | Implemented | 24 attempts for two folds; `validation_attempt` |
| Multiple-testing diagnostic | Implemented | block-bootstrap p-value plus Bonferroni-adjusted warning |
| Cost sensitivity | Implemented | test interval rerun at 0, 2, 10 and 25 bps per fold |
| Parameter stability | Implemented | selected family/lookback retained per fold; descriptive only |
| U.S. Treasury curve | Implemented | official 2024 CSV, exact SHA-256, semiannual par bootstrap |
| Bond analytics | Implemented | accrued/clean/dirty price, YTM, durations, convexity, DV01, shocks |
| European option analytics | Implemented | Black-Scholes-Merton price, Greeks, parity, implied volatility |
| Portfolio risk | Implemented | aligned covariance, beta, VaR/ES, drawdown, components, sectors |
| Constrained optimization | Implemented for long-only, box, cash and target-return constraints | active-set KKT enumeration, ≤ 8 assets |
| Compiler integration | Implemented | eight typed operators in the shared FEC registry |
| Institutional API | Implemented | `/api/institutional/*`, persisted runs and applications |
| Two Lab applications | Implemented | `/lab/institutional`; fixed income and portfolio/validation tabs |
| Save, reopen, fork, compare, export | Implemented | existing research-object registry; browser-tested |
| Browser acceptance | Implemented | `web/e2e/phase5.mjs`; desktop and 390 px |

## Architecture

```
finance/curves.py      dated par curve → zero/discount/forward → bond analytics
finance/options.py     BSM price/Greeks, parity, implied volatility
finance/statistics.py  covariance, VaR/ES, beta, drawdown, linear solve
institutional/
  universe.py          deterministic synthetic instruments and aligned returns
  risk.py              covariance risk, stress, active-set optimizer
  validation.py        walk-forward partitions, selection, attempts, diagnostics
  service.py           persistence, catalog, application documents
fec/operators.py       typed pricing/risk operators
terminal/api.py        institutional HTTP contract
web/.../Institutional  the two applications inside Quant Lab
```

The Phase 4 event-driven single-instrument ledger is untouched. Phase 5 walk-forward is a
separate cross-sectional portfolio-weight engine with explicitly different semantics.

## Schema 7

Migration 007 is additive:

* `institutional_run` — kind, as-of date, data class, canonical input/result JSON,
  fingerprint, status, duration and creation time, with indexes on kind/date and fingerprint.
* `validation_attempt` — one row per candidate configuration per fold/stage, linked to the
  parent run with `ON DELETE CASCADE`, preserving losing candidates.

The live demo database was migrated from 6 to 7. `/api/health` reports
`"schema_version": 7, "supported_schema": 7, "integrity_check": "ok"`.

## Compiler operators

`discount_factor`, `bond_price`, `bond_macaulay_duration`, `option_price`,
`option_greek`, `portfolio_variance`, `portfolio_volatility`, `risk_contributions`.

They are typed through the existing FEC registry and therefore available to Model Forge
custom equations. React performs no financial mathematics.

## Verification summary

* Nine dedicated Phase 5 tests cover schema 7, every-par-node bootstrap identity, manual
  Macaulay duration, DV01 identity, BSM reference prices/parity/IV/finite-difference
  Greeks, risk-contribution reconciliation, optimizer constraints, walk-forward partition
  and attempt counts, compiler execution and the API/persistence path.
* Full backend suite: **354 passed**, including every Phase 1–4 test and the Phase 5 suite.
* Production frontend build passes.
* The fixed-income UI renders the independently requested API clean price and positive
  DV01; portfolio VaR is a positive lower-tail loss; the optimizer and validation tabs
  expose their diagnostics.
* A real browser exports a saved manifest and checks no horizontal overflow at 390 px.

## Defects found and fixed during Phase 5 verification

* Historical VaR used the 95th percentile of returns rather than the 5% lower-tail
  quantile, reporting zero loss in profitable samples. It now uses the lower tail and is
  covered by the positive-loss browser assertion.
* The optimizer labeled the optimized risk report as `original.risk`. It now computes
  separate original and optimized reports.
* The Treasury date catalog exposed `MM/DD/YYYY` values while the UI sent ISO dates, and
  the select truncated 2024 to 80 descending dates so the default June date was absent.
  The catalog is ISO and all dates are selectable.
* Re-running a built-in custom Model Forge strategy failed when the compiler's derived
  operator-registry stamp changed. Strategy reuse now compares the declaration, not that
  derived stamp, while still rejecting genuinely changed specs.

## Deliberate boundaries

* The multi-asset panel is synthetic. No claim of a real multi-security universe, market
  coverage or survivorship-bias-free research is made.
* `ATLAS_MASTER_SPEC.md` was not present in the checked-out repository. This document and
  `docs/PHASE5_CONTRACT.md` are the in-repo authority; the supplied master v1.1 document
  should be added when available.
* No QuantLib, ORE, CVXPY or SciPy is installed. The implemented analytics are pure Python
  and independently verified; no third-party engine integration is claimed.
* The optimizer does not implement turnover or sector caps and rejects those requests.
* Options are European BSM model values, not market quotes or a volatility surface.
