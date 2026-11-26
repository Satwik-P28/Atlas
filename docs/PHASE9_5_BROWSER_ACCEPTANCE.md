# Phase 9.5 — browser acceptance

**Status: EXECUTED and PASSING** on Chromium 156 (headless shell), 1440×900 and 390×844,
against `var/phase9_5.db` (6 real filings, 6,551 passages).

## 1. Command

```bash
python -m atlas.cli --db var/phase9_5.db serve --host 0.0.0.0 --port 8000 --allow-non-loopback &
(cd web && ./node_modules/.bin/vite --host 0.0.0.0 --port 3000 --strictPort) &
export LD_LIBRARY_PATH="$HOME/.local/atlas-browser-libs/usr/lib/x86_64-linux-gnu"
export FONTCONFIG_PATH="$HOME/.config/fontconfig"
export FONTCONFIG_FILE="$HOME/.config/fontconfig/fonts.conf"
cd web && ATLAS_ARTIFACTS=../artifacts node e2e/phase9_5_filings.mjs
```

## 2. Results — 9 of 9

| Check | Observed |
| --- | --- |
| Issuer list populated | 20 issuers in the selector |
| Filing passages render | 7 passages for "customer concentration risk" |
| Passage states availability and span | `0000320193-26-000026 · available 2026-11-03 (exact) · chars 44297–44465 · public_domain` |
| Opened passage discloses exact span | `Exact span 44297–44465` rendered from the unit record |
| Claim reports citations and export decision | citation count and export permission displayed |
| Unknown/unscoped request | HTTP 200 with abstention (no issuer → no results) |
| 390×844 overflow | 0 px |
| Console errors | 0 |
| Failed requests | 0 |

Screenshots: `artifacts/phase9_5_filings.png`, `artifacts/phase9_5_filings_mobile.png`.

## 3. What the browser proved that a unit test cannot

- The retrieval response can be rendered: passages, section paths, accessions, availability,
  character spans and rights all reach the screen.
- The exact span displayed by the UI matches the stored `char_start`/`char_end` of the passage.
- Claim verification round-trips through the API and renders its outcome.
- The page survives a phone viewport with no horizontal overflow and no console noise.

Two journey defects were found and fixed while getting here: a mode-switch click on an
already-selected button that re-rendered mid-click, and `waitForSelector` on `<option>` elements,
which are never "visible". Neither was an application defect, but both would have produced a
false "browser blocked" conclusion.

## 4. Not covered

- **The Advanced `filing` panel is not browser-driven in this journey.** It is registered in
  `PANEL_META`, the workspace schema and the panel renderer, typechecks, and calls the same
  `api.knowledgeSearch`; its visual and interaction behaviour is unverified in a browser. The
  Standard page is the certified surface.
- Firefox, WebKit, Safari, screen readers and forced-colours modes are not exercised.
- The journey's claim step accepts any of verified/partially verified/unsupported; the specific
  outcome for that question is asserted in the backend tests, not in the browser.
- No visual review of the filings page beyond the two screenshots was recorded in this phase.

These are stated as limits, not passes.
