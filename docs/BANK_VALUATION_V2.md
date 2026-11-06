# Bank valuation v2

`atlas.bank.residual_income.v2` extends the Phase 9.1 residual-income model.

- Starting book value and earnings come from consolidated SEC facts.
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
MMD
