# Phase 9 — Integrated equity research, reporting and portable applications

Phase 9 composes the existing Atlas engines into one source-grounded equity research
workflow. It does not rebuild the FEC, valuation, evidence kernel or research-object
engines, and it does not relabel their limitations.

## What was built

| Piece | Location | Responsibility |
| --- | --- | --- |
| Equity research service | `src/atlas/research/equity.py` | Coverage, workspace, deterministic report, DCF audit, portable package |
| Per-period tag resolution | `src/atlas/ingestion/sec_companyfacts.py` | Picks the highest-priority revenue/share tag **per period**, so issuers that migrate tags keep a continuous history |
| Share concept order | `src/atlas/core/concepts.py` | Point-in-time `CommonStockSharesOutstanding` before cover-page `dei` count |
| Share fallback provenance | `src/atlas/fec/valuation.py` | Records whether the denominator is period-end, weighted diluted or derived from net income / diluted EPS |
| Fiscal-year filter | `src/atlas/terminal/read_models.py` | Annual periods must be 330–400 day durations; a transition window tagged `FY` is never the trailing reference |
| Terminal API | `src/atlas/terminal/api.py` | `/api/equity/coverage`, `/{id}/workspace`, `/{id}/readiness`, `/{id}/report`, `/{id}/package`, `/{id}/package.atlas` |
| Browser surface | `web/src/pages/EquityResearch.tsx` | Coverage table, eligibility, reconciliation, DCF audit, report and package download |
| Adversarial audit | `scripts/audit_phase9_financials.py` | Re-parses raw SEC payloads, compares with Atlas, and reproduces the package from a clean database |
| Benchmark | `scripts/benchmark_phase9_equity.py` | Measures coverage, workspace, analysis, packaging, install and execution |

## Separation of coverage from valuation

The service reports four different facts that are easy to conflate:

1. **Financial coverage** — the reported statement set exists, including a share
   denominator and at least three annual periods.
2. **Valuation eligibility** — the implemented methodology is admissible for the issuer
   (non-financial SIC) and the inputs it actually consumes are present.
3. **Execution** — the compiled DCF produced outputs.
4. **Economic support** — an independent component audit reproduced every output and no
   structural finding (for example terminal-value dominance) disqualifies the result.

For the real 20-company fixture: 16 issuers have valid financial coverage, 17 are
valuation-eligible, 17 execute, 17 pass the independent arithmetic audit, and 3 are
rejected as financial institutions. No issuer is counted as institutional-quality
research because a model ran.

## Financial-institution guard

SIC 6000–6799 is refused for the unlevered FCFF DCF. Debt and deposits are operating
inputs for a bank or insurer, interest is an operating cost, and FCFF is not defined the
way it is for an operating company. The report states the refusal, the reason and the
remedy (a validated residual-income or excess-return model, neither of which is implemented
here). Packaging a valuation application for such an issuer raises a validation error.

## Independent DCF audit

`_dcf_audit` recomputes, with plain floats in a different order from the operator graph:

- the revenue forecast path,
- EBIT, tax and NOPAT,
- D&A, capex and ΔNWC,
- the FCFF path,
- PV of the explicit forecast,
- terminal value and its present value,
- enterprise value, the equity bridge and value per share.

It also records the share-denominator basis and its limitation, plus structural findings:
negative FCFF, negative enterprise or equity value, terminal-value dominance, extreme
margin, high capex intensity, low discount rate and low tax rate. Findings are reported,
never tuned away. Amazon's negative value per share is a finding about its reported capex
intensity, not a model defect.

## Determinism

A package is pinned to the latest evidence availability in its snapshot, not to wall-clock
time. Runtime timings and cache status are stripped from the packaged DCF trace. Two builds
of the same issuer therefore produce byte-identical packages, and the packaged report hash
matches the report embedded in the archive.

## What Phase 9 does not do

- It does not import `ATLAS_MASTER_SPEC.md` v1.2.0: the file is still absent, so the
  master-spec gate stays blocked.
- It does not bundle market prices, consensus estimates, guidance or qualitative business
  narrative.
- It does not value financial institutions.
- It does not claim human usability validation or macOS/Windows installation validation.
