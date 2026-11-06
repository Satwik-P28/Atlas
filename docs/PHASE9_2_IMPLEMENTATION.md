# Phase 9.2 — Regulatory evidence and institution research

Phase 9.2 connects the Phase 9.1 bank and insurer arithmetic to real Call Report
observations, dated market prices and an entity-resolution layer.

## Delivered

- FDIC BankFind adapter and public-domain fixtures for JPMorgan Chase Bank, N.A.
  (CERT 628) and Goldman Sachs Bank USA (CERT 33124), six quarters each.
- `regulatory_entity`, `regulatory_observation` and `entity_reconciliation` tables.
- Parent/subsidiary map: consolidated SEC registrant vs insured subsidiary, never additive.
- Bank residual income v2 with subsidiary tangible equity, capital headroom, regulatory
  stress and an implied cost of equity, still built on the Phase 9.1 engine.
- Eligibility contract v3 with method contracts and entity reconciliation.
- Restricted observed-price import and date-aligned market comparison.
- Interface controls for ROE, cost of equity, information cutoff, price import and an
  explicit FCFF-DCF rejection test.
- Independent Decimal audit, Phase 9.2 tests and documentation.

## Preserved

The terminal, FEC, Model Forge, Quant Lab, SEC evidence kernel, research objects and
application packages were reused. No second valuation engine was created.
