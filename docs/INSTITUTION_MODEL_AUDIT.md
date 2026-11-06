# Institution model audit

`scripts/audit_phase9_2_models.py` recomputes residual income, the book roll-forward,
distributions, terminal value, sensitivities, tangible equity, capital inputs, NII, credit
stress, insurance per-share arithmetic, price alignment and package reproduction with an
independent Decimal implementation. It independently reads the 2024 10-K evidence rows
and checks JPM **$344.758B − $20.050B = $324.708B** and GS **$121.996B − $13.253B =
$108.743B**, common book per share, common ROE, the SEC/FR Y-9C reconciliation and the
market-implied cost of equity. Result: **28/28 passed** at the 2025-06-30 cutoff.

Invalid combinations are deliberately rejected: parent plus subsidiary, and mismatched
reporting periods. The audit does not call the production residual-income operators for its
reference values.

Remaining gaps: no parent goodwill mapping, no dollar RWA, no external valuation report and
no economic review. A passing audit is arithmetic verification, not investment validation.
