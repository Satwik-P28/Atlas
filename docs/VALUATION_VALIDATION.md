# Valuation validation

## Independent reference

`tests/test_fec.py::reference_dcf` is a pure formula implementation that does not call
the compiler, operator registry or runtime. It computes:

`FCF_t = NOPAT_t + D&A_t − Capex_t − ΔNWC_t`

`PV = Σ FCF_t/(1+WACC)^t`, `TV = FCF_n(1+g)/(WACC−g)`,
`EV = PV + PV(TV)`, `Equity = EV + cash − debt`, `per share = equity / shares`.

The production canonical DCF is asserted against it to `rel=1e-10` for enterprise value,
equity value, per-share value, PV components and the full FCFF series.

## Covered cases

- Standard DCF arithmetic.
- Mid-year discounting runs and produces a distinct, positive value.
- Terminal growth equal to WACC is rejected before execution.
- Currency mismatch and invalid functional types are rejected.
- Cycle, undefined dependency and duplicate dependency (a × a) handling.
- Historical cutoff metadata is part of the model/run identity.
- Incremental recomputation matches a cache-disabled full execution.
- Cache key regression test: changing `b` recomputes `a+b` and `a*b` but reuses `a²`.
- API compile/run, valuation defaults, DCF, sensitivity, URO execute/fork/compare/export.
- Missing share count is rejected unless an evidenced derivation is possible.
  `net_income / eps_diluted` is labelled `derived_estimate`; a fallback of one share is
  tested and forbidden.

## Reverse DCF

Bounded bisection with a 21-point sign-change scan. Returns:
- no solution when the bracket has no sign change;
- multiple candidates when more than one sign change exists;
- otherwise implied value, residual and iteration count.

A market-implied assumption is documented as one point on an underdetermined inverse
problem, not a forecast or management guidance.

## Limitations

- No external spreadsheet artifact is committed; the independent reference is explicit
  arithmetic in the test suite.
- No three-statement balance-sheet articulation is claimed.
- WACC is an assumption, never sourced as market evidence.
- Reverse DCF uniqueness is assessed only within the supplied bounds.
