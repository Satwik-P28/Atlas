# Equity research workflow

1. **Build or open a database.** `python scripts/build_phase9_db.py --db var/phase9.db`
   builds the 20-company SEC fixture. No prices are generated.
2. **Inspect coverage.** `GET /api/equity/coverage` returns each issuer with
   `financial_coverage_valid`, `valuation_eligibility`, market observations and readiness
   counts. Open **Equity research** in the terminal for the same data.
3. **Open a workspace.** `GET /api/equity/{identifier}/workspace` returns statements,
   metrics, annual history, filings, peer context, reconciliation checks, evidence details
   and the point-in-time policy.
4. **Generate the report.** `POST /api/equity/{identifier}/report` renders the deterministic
   Markdown report, the DCF with scenarios and sensitivity, the independent component audit
   and the findings. The response carries the report SHA-256 and the valuation status.
5. **Read the eligibility section before the valuation.** An issuer can have valid
   statements and no admissible valuation model. The report says which case applies and why.
6. **Download the package.** `GET /api/equity/{identifier}/package.atlas` returns the
   portable `atlas.application_package.v1` archive. Install it under **Applications**,
   verify its integrity, execute it and compare the outputs with the packaged expectations.
7. **Inspect provenance.** Every metric links to evidence ids reachable through Financial
   X-Ray. The report name-lists missing concepts instead of inserting zeros.

## What to expect for this universe

- Apple, Alphabet, Microsoft and the other non-financial issuers execute the DCF.
- JPMorgan (SIC 6021), Goldman Sachs (6211) and UnitedHealth (6324) are refused: an
  unlevered FCFF DCF is not an admissible model for them.
- Amazon's DCF is negative because reported capex is a large share of revenue. That is the
  answer under the reported inputs, not an error to tune away.
- No price is bundled, so market multiples, market-implied reverse DCF and a price-based
  share-count cross-check are unavailable. A reverse DCF requires an explicit target price
  from the user.

## Analyst assumptions

Revenue growth, operating margin, tax, D&A, capex, working capital, WACC and terminal growth
are editable assumptions. Their defaults come from the latest reported period and are
labelled as assumptions; only revenue, cash, debt and the share count are observed inputs.
