# Institution model audit

`scripts/audit_phase9_2_models.py` recomputes residual income, the book roll-forward,
distributions, terminal value, sensitivities, tangible equity, capital inputs, NII, credit
stress, insurance per-share arithmetic, price alignment and package reproduction with an
independent Decimal implementation.

Invalid combinations are deliberately rejected: parent plus subsidiary, and mismatched
reporting periods. The audit does not call the production residual-income operators for its
reference values.

Remaining gaps: no parent goodwill mapping, no dollar RWA, no external valuation report and
no economic review. A passing audit is arithmetic verification, not investment validation.
