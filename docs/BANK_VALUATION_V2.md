# Bank valuation v3

`atlas.bank.residual_income.v3` supersedes v2. Phase 9.2.1 changed the ROE basis and
removed the free `growth` assumption; v2 packages remain reproducible because their
arithmetic is unchanged, but their assumptions now carry the v3 interpretation.

- Starting book value is **common equity**: same-period SEC `StockholdersEquity` less SEC preferred stock. Both are GAAP facts from the same filing. The model never subtracts FR Y-9C regulatory preferred from a different-basis equity value.
- JPM 2024: $344.758B total equity − $20.050B preferred = **$324.708B** common. GS 2024: $121.996B − $13.253B = **$108.743B** common.
- The output exposes total equity, preferred, common book, book value per common share, basis and status. Net income available to common drives the model.
- ROE is net income available to common divided by **average common equity** (prior and current fiscal year-end SEC common equity). The ending-equity ratio is emitted separately as `ending_equity_roe_proxy`. `company_reported_roe` is `null` unless the company's own disclosure is mapped.
- Earnings and share counts are reported SEC facts with evidence ids.
- Forecast book value rolls forward under clean surplus: opening + net income − distributions.
- Distributions combine the payout assumption and a buyback-yield scenario.
- `growth` is not a free assumption. Explicit-period book growth is implied by clean surplus: `ROE × (1 − payout)`. Supplying `growth` returns a finding and leaves the value unchanged; it is never silently ignored.
- The terminal residual is capitalised at `terminal_growth`. To keep terminal clean surplus coherent, the implied terminal payout is `1 − terminal_growth / ROE`; the explicit-period payout is not silently carried into perpetuity.
- Explicit residual income plus a capitalized terminal residual are discounted at the
  assumed cost of equity.
- Sensitivity covers cost of equity, ROE, terminal growth, payout and buybacks.
- JPM uses a diversified-bank consolidated ROE driver; GS uses a capital-markets driver with
  a documented 11% default cost of equity rather than 10%. Segment forecasts are **not**
  claimed because segment observations are unavailable.
- Subsidiary tangible equity = EQ − INTAN. It is displayed as subsidiary regulatory context
  and is not used for the parent per-share value.
- Regulatory stress applies NII and charge-off shocks to subsidiary equity. It reports **GAAP equity-to-assets**, not Tier 1 leverage, and returns `regulatory_leverage_not_verified` because no Tier 1 capital numerator or regulatory exposure denominator is mapped. No Tier 1 minimum is applied to the GAAP ratio.
- Preferred stock is a GAAP balance-sheet claim, not regulatory CET1 capital. The FR Y-9C total and preferred fields are used only as a reconciliation check.
