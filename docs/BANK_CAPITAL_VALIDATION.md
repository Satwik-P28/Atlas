# Bank capital validation

Reported FDIC ratios are stored as published: tier 1 leverage, total risk-based capital and
common equity tier 1. Headroom is computed in percentage points against 4.0%, 10.5% and 7.0%
reference thresholds.

FDIC does not publish dollar risk-weighted assets in this dataset. Dollar capital headroom is
therefore **not** inferred and the model does not assume unlimited distributions. The binding
constraint is reported.

The Phase 9.2.1 stress is intentionally **not** called a Tier 1 leverage stress. It applies
annualized NII and charge-off shocks with a 21% tax assumption and assets held constant,
then reports `gaap_equity_to_assets_after_percent`. Tier 1 capital and the regulatory
leverage exposure denominator are not mapped, so `regulatory_leverage_after_percent` is
`null` and the status is `regulatory_leverage_not_verified`. GAAP equity/assets is not
compared with the 4% Tier 1 leverage minimum.

This is a subsidiary capital check, not a consolidated capital adequacy opinion.
