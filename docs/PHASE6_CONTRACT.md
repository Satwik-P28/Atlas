# Phase 6 contract

Phase 6 may extend Phase 5 only through versioned, tested interfaces. No Phase 5 result may
be retroactively relabeled as real-market evidence.

## Stable interfaces to preserve

* `atlas.institutional.universe.v1`: stable security IDs, membership, content hash,
  `data_class`, explicit survivorship flags.
* `atlas.institutional.portfolio_risk.v1`: aligned lookback, weights, covariance,
  component identities, VaR/ES method, stress method labels.
* `atlas.institutional.optimizer.v1`: objective, constraints, solver diagnostics,
  infeasibility reasons, historical-mean warning.
* `atlas.institutional.walk_forward.v1`: train/validation/test partitions, embargo,
  selection policy, attempt log, test-used-for-selection flag.
* `atlas.institutional.run.v1`: canonical input/result JSON, fingerprint, data class.
* `atlas.finance.black_scholes_merton.v1`, the Treasury curve contract and bond
  conventions.
* All Phase 1–4 contracts, especially `atlas.quant.reference.v1` next-open semantics.

## Required before stronger claims

1. **Real multi-security data** with redistribution rights, point-in-time membership,
   delisting returns, corrections and corporate actions. A surviving-ticker panel must not
   be called survivorship-bias-free.
2. **Source-byte archives** for provider datasets, with stable identifiers and retrieval
   timestamps. Model replay against a current vendor file is not archival reproduction.
3. **Estimation layer** with covariance shrinkage/robustness, parameter uncertainty and a
   proper QP backend supporting turnover and sector constraints.
4. **Fixed-income expansion** only with declared calendars, day-counts, settlement rules,
   credit curves and independent reference tests.
5. **Derivatives expansion** behind replaceable model adapters, with market-quote
   provenance and no implied complete surface from a single volatility index.
6. **Walk-forward at scale** with purged CV for overlapping labels, multiple-testing
   control appropriate to the search, and persisted failed runs.
7. **Research applications** that can diff/fork versions and export manifests without
   exposing restricted vendor bytes.
8. **Performance** measurements before any accelerator rewrite; keep a CPU-only baseline.

## Future systems compatibility

The Universal Event and Probability Engine, event-contract settlement, prediction-market
research, Causal Intelligence Graph, Decision Problem Engine and learning systems must
reuse the experiment, evidence, provenance and portfolio-risk infrastructure. They must
not become disconnected applications.

Prediction-market work, if added, is read-only research first. No real-money execution,
unauthorized scraping or riskless-arbitrage claim is authorized by this contract.

## Definition of done

Each claim needs: an independent assertion, a persisted artifact, an explicit data class,
a measured result where performance is claimed, and a stated limitation. Stubs, mock
backends and attractive charts are not capabilities.
