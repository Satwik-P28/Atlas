# Bank valuation v2

`atlas.bank.residual_income.v2` extends the Phase 9.1 residual-income model.

- Starting book value is **common equity**: same-period SEC `StockholdersEquity` less SEC preferred stock. Both are GAAP facts from the same filing. The model never subtracts FR Y-9C regulatory preferred from a different-basis equity value.
- JPM 2024: $344.758B total equity − $20.050B preferred = **$324.708B** common. GS 2024: $121.996B − $13.253B = **$108.743B** common.
- The output exposes total equity, preferred, common book, book value per common share, basis and status. Net income available to common and common-basis ROE drive the model.
- Earnings and share counts are reported SEC facts with evidence ids.
- Forecast book value rolls forward under clean surplus: opening + net income − distributions.
- Distributions combine the payout assumption and a buyback-yield scenario.
- Explicit residual income plus a capitalized terminal residual are discounted at the
  assumed cost of equity.
- Sensitivity covers cost of equity, ROE, terminal growth, payout and buybacks.
- JPM uses a diversified-bank consolidated ROE driver; GS uses a capital-markets driver with
  a documented 11% default cost of equity rather than 10%. Segment forecasts are **not**
  claimed because segment observations are unavailable.
- Subsidiary tangible equity = EQ − INTAN. It is displayed as subsidiary regulatory context
  and is not used for the parent per-share value.
- Regulatory stress applies NII and charge-off shocks to subsidiary equity and leverage.
- Preferred stock is a GAAP balance-sheet claim, not regulatory CET1 capital. The FR Y-9C total and preferred fields are used only as a reconciliation check.
