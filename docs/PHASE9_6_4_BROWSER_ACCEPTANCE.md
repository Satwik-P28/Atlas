# Phase 9.6.4 — Browser Acceptance

## Readiness

- API started on `127.0.0.1:8000` against `var/phase9_6.db`; log line `Application startup
  complete.` observed before the journey.
- Vite started on `0.0.0.0:3000`; `GET /` returned 200; `/api` proxied to the API.
- Chromium headless shell installed for Playwright.

## Journey

`web/e2e/phase9_6_2_advanced.mjs`: **23/23 checks passed** — instrument list populated, issuer
selection, filing evidence with spans, cutoff enforcement (2019-06-30, 6 rows), issuer switch with
no stale rows, save/reopen with fingerprint, instrument binding persistence, single-panel desk,
390×844 with no page overflow and no clipped controls, console errors 0, failed requests 0.

## Screenshots inspected

- Desktop `artifacts/phase9_6_2_advanced_filing.png`: 3M CO desk, Document evidence panel with
  exact spans and rights, cutoff 2021-06-30, link groups A–D.
- Mobile `artifacts/phase9_6_2_advanced_filing_mobile.png`: 390×844, saved Desk 9, single panel,
  JPMorgan evidence rows, no horizontal clipping.

## Notes

The 9.6.3 timeout (`page.waitForFunction` on the instrument list) did not recur; the earlier run
had no browser binary or services, which is consistent with a harness/environment cause rather
than a product defect. This run is the certification record for 9.6.4.
