# Financial-institution models

## Bank and capital-markets residual income

Used for JPMorgan Chase (SIC 6021) and Goldman Sachs (SIC 6211).

```
Equity value = BV0 + Σ (NI_t - CoE·BV_t-1)/(1+CoE)^t + PV(terminal residual)
BV_t       = BV_t-1 + NI_t - dividends
NI_t       = sustainable ROE · BV_t-1
BV0        = SEC StockholdersEquity − same-period SEC preferred stock
```

- JPM opens on **$324.708B** common equity after deducting $20.050B preferred; GS opens on **$108.743B** after deducting $13.253B. Each bank uses its own filed SEC tag.
- Book value, preferred stock, net income and share counts are reported SEC facts with evidence ids. Preferred is GAAP, not CET1.
- Cost of equity, sustainable ROE, payout, horizon and terminal growth are explicit
  assumptions, echoed in the output and the package.
- Sensitivity covers cost of equity ±1 pp, ROE ±2 pp, terminal growth 1.5–3.5% and both
  period-end and weighted-average diluted share counts. Common-basis book value per share
  and common ROE are emitted separately from total equity.
- A negative calculated equity value is retained. `realizable_common_price` is `null`,
  with a finding explaining that a negative residual is not a tradable negative price.
- Tangible book value is **not** produced: goodwill and intangibles are not mapped, so
  book value is not silently relabelled as tangible book.
- Credit losses, net interest margin, deposit beta, regulatory capital and Call Report
  data are not modelled. Segment earnings are unavailable and not proxied.

## Health-insurance justified earnings

Used for UnitedHealth Group (SIC 6324).

```
Justified P/E = payout · (1+g) / (CoE - g)
Value/share   = diluted EPS · justified P/E
```

A single-period residual-income capitalisation is shown as a cross-check only. The result
is marked **partial** because the consolidated statements include healthcare-services
operations; no segment split is mapped. Medical loss ratio, premium revenue, medical
costs, reserves and plan-level regulatory capital are reported as
`not_available_in_fixture`, never estimated.

## What the audit proves

`scripts/audit_phase9_1_models.py` recomputes both models with an independent Decimal
implementation, checks the industrial DCF rejection, verifies that Amazon's negative DCF
is preserved, and installs and replays institution packages in a clean database. It
verifies arithmetic and packaging. It does **not** establish that the assumptions are
economically correct, and the contract therefore stops at `arithmetically_verified`.
