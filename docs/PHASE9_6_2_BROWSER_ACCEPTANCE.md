# Phase 9.6.2 — Browser acceptance

Script: `web/e2e/phase9_6_2_advanced.mjs` (Chromium via Playwright, real servers: API on
`127.0.0.1:8000`, Vite on `0.0.0.0:3000`).

Result: **23/23 checks passed**, console errors 0, failed requests 0.

Covered: workstation load, 43 issuers listed, filing panel bound from the workstation, historical
passages rendered, exact character spans, availability class, cutoff change applied server-side,
issuer switch leaving no stale rows, save, saved desk listed, reload restoring the filing panel,
instrument binding equal before and after, single-panel save accepted, one-panel desk restored,
binding kept at one panel, 390x844 no overflow and no clipped header control.

Screenshots: `artifacts/phase9_6_2_advanced_filing.png`, `artifacts/phase9_6_2_mobile.png` (inspected).

Not covered: link groups B/C/D were not driven through the browser individually in this run;
their serialization is covered by the workspace validator tests and the same link-state payload.
This is recorded as a residual gap, not claimed as browser-verified.
