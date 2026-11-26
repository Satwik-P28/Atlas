# Valuation validation

## Independent reference

`tests/test_fec.py::reference_dcf` and `tests/test_phase3_validation.py::reference_dcf`
are separate pure-formula implementations that do not call the compiler, operator registry
or runtime. They compute:

`FCF_t = NOPAT_t + D&A_t − Capex_t − ΔNWC_t`

`PV = Σ FCF_t/(1+WACC)^t`, `TV = FCF_n(1+g)/(WACC−g)`,
`EV = PV + PV(TV)`, `Equity = EV + cash − debt`, `per share = equity / shares`.

The production canonical DCF is asserted against them to `rel=1e-10` for enterprise value,
equity value, per-share value, PV components, terminal value and the full FCFF series.
The API integration test covers end-year, mid-year and exit-multiple terminal methods.

## Covered cases

- Standard DCF arithmetic, end-year and mid-year, plus exit-multiple terminal value.
- Enterprise-to-equity bridge and per-share reconciliation.
- Reverse DCF against an independently written bisection reference.
- Scenario overrides and every sensitivity cell against a standalone reference.
- Negative forecast FCFF and a terminal growth rate very close to WACC remain finite.
- Terminal growth equal to WACC is rejected before execution.
- Currency mismatch and invalid functional types are rejected.
- Cycle, undefined dependency and duplicate dependency (a × a) handling.
- Historical cutoff metadata is part of the model/run identity; Studio’s 2024-06-01
  reconstruction renders a different value ($70.12) from the current run ($131.19).
- Incremental recomputation matches a cache-disabled full execution.
- Cache key regression test: changing `b` recomputes `a+b` and `a*b` but reuses `a²`.
- API compile/run, valuation defaults, DCF, scenarios, sensitivity, object
  execute/fork/compare/export, and run-snapshot export.
- Missing share count is rejected unless an evidenced derivation is possible.
  `net_income / eps_diluted` is labelled `derived_estimate`; a fallback of one share is
  tested and forbidden, and the valuation normaliser’s shares default is zero.

## Reverse DCF

Bounded bisection with a 21-point sign-change scan. Returns:
- no solution when the bracket has no sign change;
- multiple candidates when more than one sign change exists;
- otherwise implied value, residual and iteration count.

A market-implied assumption is documented as one point on an underdetermined inverse
problem, not a forecast or management guidance. In the independent API test, the
production solver agrees with the reference bisection to `2e-4`; with a $140 target the
Studio run solved implied terminal growth at about 2.99% and residual below $0.001.

## Limitations

- No external spreadsheet artifact is committed; independence means separate explicit
  arithmetic or bisection in the test suite, not a second vendor engine.
- No three-statement balance-sheet articulation is claimed.
- WACC is an assumption, never sourced as market evidence.
- Reverse DCF uniqueness is assessed only within the supplied bounds.
- Scenario and sensitivity cells repeat the same canonical model; the independent test
  validates their arithmetic but does not constitute a second production implementation.
