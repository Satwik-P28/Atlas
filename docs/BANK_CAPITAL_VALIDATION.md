# Bank capital validation

Reported FDIC ratios are stored as published: tier 1 leverage, total risk-based capital and
common equity tier 1. Headroom is computed in percentage points against 4.0%, 10.5% and 7.0%
reference thresholds.

FDIC does not publish dollar risk-weighted assets in this dataset. Dollar capital headroom is
therefore **not** inferred and the model does not assume unlimited distributions. The binding
constraint is reported, and the regulatory stress shows the leverage ratio after annualized
NII and charge-off shocks with a 21% tax assumption and assets held constant.

This is a subsidiary capital check, not a consolidated capital adequacy opinion.
