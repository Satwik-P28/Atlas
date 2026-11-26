# Phase 9 readiness

This record separates what is verified from what is not. Phase 9 is an honest subset: the
integrated equity workflow is implemented and adversarially checked, but the master-spec
gate is still blocked and no institutional-quality claim is made.

| # | Requirement | Status | Evidence |
| ---: | --- | --- | --- |
| 1 | Integrated equity service, deterministic report, portable package | pass | `research/equity.py`, `tests/test_phase9_equity.py`, API routes |
| 2 | Independent validation of revenue, income, cash flow, capex, debt, shares | pass | `artifacts/phase9_financial_audit.json`, 7/7 representative issuers |
| 3 | Amendments, overlapping facts, fiscal periods and cutoffs | pass | audit `filings` and `historical_cutoff` sections; adversarial tests |
| 4 | Period-end versus diluted weighted-average shares | pass with limitations | basis recorded in every DCF; fallback limitation in report |
| 5 | Independent audit of every DCF component | pass | 8 component checks, 17/17 arithmetic passes |
| 6 | Reject unsupported methodology (financial institutions) | pass | JPM 6021, GS 6211, UNH 6324 refused; package blocked |
| 7 | Preserve negative valuations and incomplete data | pass | Amazon −90.62 USD/share preserved with findings; no zero filling |
| 8 | Complete source-linked report and matching application | pass | `atlas.equity_research.report.v1`, 10-file declarative package |
| 9 | Export and reproduce from a clean database | pass | deterministic SHA-256, `reproduced` execution, identical outputs |
| 10 | Adversarial regression tests | pass | tag migration, missing facts, restatements, share errors, fiscal selection, absent prices |
| 11 | Installation, browser, benchmark, rights and regression checks | pass with gaps | Linux verified; macOS/Windows and human usability not verified |
| 12 | Master specification imported and checksummed | **blocked** | `ATLAS_MASTER_SPEC.md` v1.2.0 is absent; no substitute created |
| 13 | Institutional-quality research claim | not claimed | 17 executing DCFs are not evidence of research quality |

## Coverage versus valuation

For the real 20-company fixture:

- **16** issuers have valid financial coverage.
- **17** are eligible for the implemented DCF.
- **17** execute and pass the independent arithmetic audit.
- **3** are refused as financial institutions.
- **0** have market prices.
- **8** executing valuations carry at least one finding; Amazon's value is negative and is
  reported as such.

The gap between 16 and 17 is intentional: Amazon, Coca-Cola and Walmart never tag
`us-gaap:Liabilities` in this archive, which makes statement coverage incomplete, while the
DCF itself does not consume total liabilities.

## Blocked and unverified

- Master specification import/checksum gate 2 remains blocked; full Phase 9 completion is not
  claimed.
- No market-price dataset, so market multiples, market-implied reverse DCF and price-based
  share-count validation are unavailable.
- No external user testing, no macOS/Windows validation.
- No bank or insurer valuation model exists.
