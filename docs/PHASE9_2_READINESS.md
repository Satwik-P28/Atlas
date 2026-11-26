# Phase 9.2 readiness

## Complete

- Schema 13, including dedicated `fr_y9c_observation` and exact source-archive bytes.
- Official FFIEC FR Y-9C snapshot: JPM top-tier RSSD 1039502, 17 observations,
  3,806-row `BHCF20241231.ZIP`.
- Parent consolidated capital is separate from the FDIC CERT 628 subsidiary.
- **Common-equity correction:** SEC total stockholders' equity less same-period SEC
  preferred stock, both GAAP. JPM **$324.708B**, GS **$108.743B**.
- Book value per common share, common net income, ending-equity ROE proxy and average common ROE are emitted and audited. Company-reported ROE is not claimed.
- Bank residual income v3 arithmetic independently audited **29/29**; free `growth` is rejected and regulatory Tier 1 leverage is marked not verified.
- Market imports are append-only across providers, idempotent on replay, revisioned on correction and rejected atomically on bad rows.
- Source/licence identities are isolated; ticker ambiguity and exchange mismatch fail closed.
- Restricted market prices imported with date alignment and excluded from reports and
  portable packages.
- Eligibility v3 and explicit FCFF-DCF rejection for banks.
- Research object save/reopen remains supported; portable package reproduces on a clean
  database with `differences={}`.
- **459 backend tests**, **4 frontend tests** and production frontend build pass.
- Phase 9.2 benchmark records import, evidence, valuation, export and package replay.

## Blocked or limited

- **Master specification:** file absent; verifier exits 1. Full acceptance is blocked.
- **Browser rerun:** Cloud browser renders the rebuilt JPM workspace, but the local
  Playwright runner crashes in Chromium 156; full A–J and 390×844 are not claimed for this
  build.
- **Point in time:** no FR Y-9C release timestamp or vintage; historical regulatory
  reconstruction is prohibited.
- **Tangible book:** parent goodwill/intangibles are not both mapped; no parent tangible
  book per share.
- **Capital headroom:** no dollar parent RWA, so only reported percentage ratios.
- **External validation:** no analyst or market valuation benchmark; contracts stop at
  arithmetic verification.
- **Market access:** Nasdaq automated collection remains unauthorized; local CSV only.
- **Platforms:** no macOS or Windows verification.

No Phase 9.3 or Phase 10 work was started.
