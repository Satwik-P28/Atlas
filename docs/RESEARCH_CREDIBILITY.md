# Research Credibility Report

The report is generated from the stored run and experiment; it is not a marketing page
and has **no invented overall score**.

## Contents

1. **Question and hypothesis** — copied from the experiment, not inferred from the
   strategy name.
2. **Result and benchmark** — total return, benchmark total return, excess, costs.
3. **Period and data** — instrument, source, first/last session, session count.
4. **Data limitations** — raw vendor observations, no proven historical display vintage,
   missing corporate actions, no survivorship-free universe.
5. **Information timing** — signal at close, next-open fill, point-in-time feature cutoff.
6. **Universe construction** — one named instrument; no claim of a broad universe.
7. **Trading assumptions** — long-only, whole shares, no leverage/shorting.
8. **Costs** — commission and slippage in bps, total cost dollars.
9. **Performance and risk** — return, volatility, Sharpe, Sortino, drawdown, turnover,
   exposure.
10. **Validation** — in-sample only unless a walk-forward artifact exists; the report says
    so explicitly.
11. **Candidate configurations** — count of stored attempts, including failed ones when
    recorded. A single run is reported as a single attempt, not as a search.
12. **Sensitivity** — commission/slippage and parameter variants that were actually run;
    no fabricated grid.
13. **Accounting reconciliation** — the identity result and residual.
14. **Reproducibility** — fingerprint, archived-source status, engine and model versions.
15. **Unresolved concerns** — explicit list, including any missing archive or stale price.

## Interpretation

The report distinguishes:

* a **research finding** — a measured result on a stated sample;
* a **robust candidate** — survives stated costs, parameter variation and out-of-sample
  partitions;
* a **validated advantage** — requires evidence this phase does not produce.

A higher Sharpe alone never upgrades a finding. The report includes the number of
attempted configurations because selecting the best of many unreported trials is a
multiple-testing hazard. If the count is unknown, it says unknown.

## Example conclusion (IBM, 2015–2026)

Buy-and-hold returned 108.60%; the 20/100 trend rule returned -39.49%; momentum 16.12%;
the custom model signal 24.17%. All ledger reconciliations passed. The honest conclusion
is that this sample does not establish a validated advantage for any active rule, and
that the result is in-sample and single-instrument. That is the intended output of a
credibility report.
