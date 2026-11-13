# Phase 9.6.1 — Advanced Browser Acceptance

**Result: 19 of 20 checks pass. One open defect (instrument binding restore). Not certified as fully accepted.**

Executed against the real API (`var/phase9_6.db`, 43 issuers, 64 filings) and Vite, with
Playwright/Chromium in the workspace (`npx playwright install chromium`, rootless libs from 9.4.1).

```
node web/e2e/phase9_6_1_advanced.mjs
```

## Passing checks

| Check | Evidence |
| --- | --- |
| Advanced workstation loads | `/workstation` shell renders |
| Instrument list populated | 43 issuers |
| Filing panel added and bound | "Document evidence" panel created from the desk |
| Historical passages render | 6 passages for 3M CO at cutoff 2021-06-30 |
| Exact character span shown | `chars 245067–245825` |
| Availability shown | `unknown availability` (the corrected temporal label) |
| Opened passage exposes precise span | "Exact span 245067–245825" |
| Cutoff change applied server-side | request cutoff `2019-06-30T23:59:59Z`, 6 rows, all `availability_time` within it |
| Issuer switch, no stale results | 0 rows carried over |
| Workspace saved | "Saved “Desk 6” · fingerprint b9ff3704dd7edfba · 3 panels" |
| Workspace listed and reopened by id | `WS-8598f95b37b8` |
| Filing panel restored | tabs: Universe, Evidence, Document evidence |
| 390×844 no page overflow | delta 0 px |
| 390×844 no header control clipped | theme, mode and inspector controls all inside the viewport |
| Console errors / failed requests | 0 / 0 |

Screenshots: `artifacts/phase9_6_1_advanced_filing.png` (desktop, 6 passages with span and
`unknown availability`) and `artifacts/phase9_6_1_advanced_filing_mobile.png`. Both were inspected.

## Open defect

**Instrument binding is not restored.** The reopened desk restores panels, but the Instrument
control reads empty, so the filing panel falls back to "No instrument selected in this link
group." Panels persist `issuer_id`/`security_id` in the workspace document (validator and migration
allow them), and `Workstation.tsx` re-selects the binding on load, but the persisted document in
this run still contains no `issuer_id`, so the write path did not capture the selection. The check
fails and is reported as a failure rather than relaxed.

## Defect found in layout handling

Closing panels down to a single panel leaves a split node that the save validator rejects
("A split needs 2 to 6 children"). Recorded, not repaired in this phase.

## 390 px theme control

The earlier clipped theme control is now reachable: the header wraps, and the check asserts every
header control's right edge is inside the viewport. The mobile screenshot confirms the header and
rail fit; panel bodies scroll in their own containers by design.
