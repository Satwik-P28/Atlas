# Phase 9.2 — Regulatory evidence and institution research

Phase 9.2 connects the Phase 9.1 bank and insurer arithmetic to real Call Report and
consolidated holding-company observations, dated market prices and an entity-resolution
layer.

## Delivered

- FDIC BankFind adapter and public-domain fixtures for JPMorgan Chase Bank, N.A.
  (CERT 628) and Goldman Sachs Bank USA (CERT 33124), six quarters each.
- Official FFIEC NIC FR Y-9C bulk archive for 2024-12-31, parsed for JPM top-tier
  RSSD 1039502 with exact archive bytes retained.
- `regulatory_entity`, `regulatory_observation`, `entity_reconciliation` and
  `fr_y9c_observation` tables; schema 13.
- Parent/subsidiary map: consolidated SEC registrant vs insured subsidiary, never additive.
- Parent consolidated capital and FDIC subsidiary capital displayed separately; neither
  is substituted for the other.
- Bank residual income v2 with subsidiary tangible equity, capital headroom, regulatory
  stress and an implied cost of equity, still built on the Phase 9.1 engine.
- **Common-equity correction:** same-period SEC preferred stock is mapped for JPM and GS.
  The opening book is SEC total equity less that preferred claim, with total, preferred,
  common book, book per common share, basis and status all exposed. JPM: $324.708B;
  GS: $108.743B.
- Eligibility contract v3 with method contracts and entity reconciliation.
- Restricted observed-price import and date-aligned market comparison.
- Interface controls for ROE, cost of equity, information cutoff, price import,
  save/reopen and an explicit FCFF-DCF rejection test.
- Portable package reproduction on a clean schema-13 database.
- Independent Decimal audit, Phase 9.2 tests, benchmarks and documentation.

## Preserved

The terminal, FEC, Model Forge, Quant Lab, SEC evidence kernel, research objects and
application packages were reused. No second valuation engine was created. No Phase 9.3
or Phase 10 work was started.

## Known limitations

- The bulk FR Y-9C archive has no release timestamp or vintage; point-in-time
  reconstruction is not claimed.
- Preferred stock is a GAAP balance-sheet claim, not CET1; FR Y-9C total/preferred are a
  reconciliation check, not cross-basis model inputs.
- The local Chromium runner crashes on the rebuilt SPA; Cloud browser rendering passed but
  the full A–J suite was not counted. See `PHASE9_2_FINAL_ACCEPTANCE.md`.
- Parent goodwill and other intangibles are not both mapped; no parent tangible book
  per share.
- Segment forecasts and external analyst benchmarks are unavailable.
