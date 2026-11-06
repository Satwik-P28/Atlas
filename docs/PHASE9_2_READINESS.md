# Phase 9.2 readiness

## Complete

- Schema 13, including dedicated `fr_y9c_observation` and exact source-archive bytes.
- Official FFIEC FR Y-9C current snapshot: JPM top-tier RSSD 1039502, 17 observations,
  3,806-row `BHCF20241231.ZIP`.
- Parent consolidated capital is separate from the FDIC CERT 628 subsidiary.
- Bank residual income v2 arithmetic independently audited 19/19.
- Restricted market prices imported with date alignment and excluded from reports and
  portable packages.
- Eligibility v3 and explicit FCFF-DCF rejection for banks.
- Browser journeys A–J at desktop and 390×844; no document overflow; 44 px controls.
- Research object save/reopen and portable package reproduction on a clean database.
- 445 backend tests, 4 frontend tests and production frontend build pass.
- Phase 9.2 benchmark records import, evidence, valuation, export and package replay.

## Blocked or limited

- **Master specification:** file absent; verifier exits 1. Full acceptance is blocked.
- **Common-equity book:** the model opens on total stockholders' equity
  ($344.758B), not common equity ($324.708B). Preferred stock is not mapped in SEC
  facts. The runtime flags this; per-share output is diagnostic only.
- **Point in time:** no FR Y-9C release timestamp or vintage; historical regulatory
  reconstruction is prohibited.
- **Tangible book:** parent goodwill/intangibles are not both mapped; no parent
  tangible book per share.
- **Capital headroom:** no dollar parent RWA, so only reported percentage ratios are
  available.
- **External validation:** no analyst or market valuation benchmark; contracts stop at
  arithmetic verification.
- **Market access:** Nasdaq automated collection remains unauthorized; local CSV only.
- **Platforms:** no macOS or Windows verification.

No Phase 9.3 or Phase 10 work was started.
