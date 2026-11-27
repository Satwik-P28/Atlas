# Source-backed samples

Two real observations transcribed from the official Treasury dataset previews (reviewed 2026-11-24), not raw API responses. Monetary values are exact decimal USD strings. The currency column is added for clarity. No original publication timestamp or source payload hash was available; these samples must not be treated as point-in-time backtest evidence.

- Historical debt: https://fiscaldata.treasury.gov/datasets/historical-debt-outstanding/historical-debt-outstanding/ (2024-09-30).
- Daily debt: https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/ (2026-11-17).
- Rights: https://fiscaldata.treasury.gov/api-documentation/ explicitly permits commercial and noncommercial redistribution.

These are narrow smoke-test samples, not historical coverage claims. Use the downloader for complete current source snapshots.

## January 1990 Treasury par yields

`treasury_yields_1990_01.csv` contains the 21 daily rows (nine available maturities per date, 189 numeric yields) displayed for January 1990 in the official Treasury table: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?page=0&type=daily_treasury_yield_curve . Reviewed 2026-11-24. Values are percentage points, not fractional rates. Dates are normalized to ISO 8601. Columns unavailable for the period (N/A) are omitted, never zero-filled. This is a transcription of the published table, not the original archive bytes or a historical vintage. Credit: US Department of the Treasury. Public domain US government-produced statistics under 17 USC 105. The full nominal-yield archive is catalogued separately.
