# Phase 9 financial reconciliation and adversarial audit

The audit answers one question: **does the number Atlas shows equal the number the filed
SEC XBRL fact says?** It is deliberately independent of the ingestion path.

Run:

```bash
python scripts/audit_phase9_financials.py --db var/phase9.db \
  --out artifacts/phase9_financial_audit.json
```

## Method

For AAPL, GOOGL, XOM, NVDA, CAT, JPM and GS the script:

1. reads the archived `companyfacts` payload directly;
2. keeps only `10-K` / `10-K/A` observations tagged `FY` with a duration of 330–400 days;
3. resolves each period end to the most recently **filed** value, so an amendment wins over
   the original filing regardless of database insertion order;
4. resolves revenue by trying every accepted revenue tag for that one period;
5. compares revenue, net income, operating cash flow, capex (as a magnitude), total debt,
   point-in-time shares, weighted diluted shares and the fiscal-year duration with the
   Atlas evidence record at the same period end;
6. checks the historical cutoff, the share-denominator basis, the absence of prices, and
   finally builds the package twice, installs it into a freshly migrated database and
   executes it.

## Results on this checkout

- Raw comparisons: **7 / 7 issuers pass** across all compared concepts.
- Tag migration: GOOGL revenue moves from
  `RevenueFromContractWithCustomerExcludingAssessedTax` to `Revenues`; the 2025 value is
  resolved from `Revenues` while earlier periods keep their original tag. XOM, NVDA and PFE
  use `Revenues` throughout.
- Amendments and overlaps: the archive contains overlapping period/concept observations;
  the latest availability is selected, and the audit confirms the selected evidence id
  matches the independently chosen filing.
- Fiscal periods: transition or quarterly windows tagged `FY` are retained as evidence but
  never selected as the annual reference. The selected revenue fact is always 330–400 days.
- Historical cutoff: an as-of date before the latest 10-K selects an earlier annual period
  and does not leak the later filing.
- Share counts: period-end counts are compared with `CommonStockSharesOutstanding`,
  weighted diluted counts with `WeightedAverageNumberOfDilutedSharesOutstanding`. Where a
  period-end count exists it is used for the per-share denominator; the weighted average is
  used only as a labelled fallback, and a net-income/EPS derivation only when neither is
  reported.
- Debt: total debt is compared with the sum of the reported long- and short-term components.
- Prices: zero market observations; no market cap, P/E or market-implied value is produced.
- Package: deterministic, installs into a clean database, executes with `reproduced` status
  and identical outputs, and the embedded report hash matches the manifest.

## Known reconciliation limits

- One reference annual period per issuer and only unambiguous tags are compared.
- A filer that never tags `us-gaap:Liabilities` (Amazon, Coca-Cola, Walmart, Goldman Sachs
  in this archive) has incomplete statement coverage. Atlas does not derive total
  liabilities from assets minus equity, because that identity is not reliable in the
  presence of non-controlling interests or mezzanine instruments.
- Total debt cannot be recovered from a combined line item that the fixture does not retain.
- Amendments are resolved by filing date as a policy choice; that is not a claim that the
  amended economics are correct.
- XBRL sign conventions and units are taken from the source; a filer-specific extension tag
  that is not in the concept registry remains unmapped and is reported as missing.
