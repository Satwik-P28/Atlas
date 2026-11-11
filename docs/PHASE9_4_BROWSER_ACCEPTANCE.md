# Phase 9.4 — browser acceptance

**Status: BLOCKED. No browser journey was executed. No screenshot was produced or inspected.
Browser console and network errors were not captured.** The runnable artefacts are committed, and
the blocker is an environment limitation that was investigated rather than restated.

## 1. What was tried in this phase

1. **Reinstalled Playwright's Chromium** with the project's own pin:
   `./node_modules/.bin/playwright install chromium` → *Chrome Headless Shell 156.0.8078.4
   (playwright chromium-headless-shell v1248)*, 120 MiB.
2. **Supplied NSS/NSPR without root** by extracting Ubuntu packages into a private prefix:
   `libnspr4_4.38.2-1ubuntu1_amd64.deb` and `libnss3_3.98-0ubuntu0.22.04.5_amd64.deb` via
   `dpkg-deb -x … ~/.local/atlas-browser-libs`, launched with
   `LD_LIBRARY_PATH=~/.local/atlas-browser-libs/usr/lib/x86_64-linux-gnu`. `ldd` then resolved
   NSPR/NSS.
3. **Identified the remaining gap precisely**: `ldd` on `chrome-headless-shell` still reports
   nine unresolved objects — `libatk-1.0.so.0`, `libatk-bridge-2.0.so.0`, `libatspi.so.0`,
   `libXcomposite.so.1`, `libXdamage.so.1`, `libXfixes.so.3`, `libXrandr.so.2`,
   `libxkbcommon.so.0`, `libasound.so.2`.
4. **Attempted to fetch those packages unprivileged** from `archive.ubuntu.com`. The specific
   `.deb` filenames tried returned HTTP 404, and the pool directory listings for those package
   directories returned no `.deb` entries, so an unprivileged resolver could not complete the
   set. `apt-get download` failed as well (`Unable to locate package …` for the same names,
   because the image's package index is stale relative to its 24.04 sources).
5. **Privileged install remains impossible**: `sudo` fails with *the "no new privileges" flag is
   set*, so `playwright install-deps` cannot run.

Result: `chromium.launch()` fails with *Target page, context or browser has been closed*, and the
binary itself exits with *error while loading shared libraries: libatk-1.0.so.0*.

The Phase 9.3 cloud-browser bridge was also unavailable in this session (previously:
*Playwright exceeded 60s in the chat workspace* and *The property 'options.mode' must be one of:
'strip'*). No browser automation route currently works in this VM.

## 2. What was deliberately not done

- The Chromium sandbox was not disabled to force a launch in a production configuration.
- Source rights were not altered and no assertion was weakened to make a journey "pass".
- API tests are not being presented as browser tests.

## 3. Runnable test matrix (NOT EXECUTED)

`web/e2e/phase9_4_workstation.mjs` — run with a working Chromium and the terminal on
`http://127.0.0.1:3000`:

```bash
node web/e2e/phase9_4_workstation.mjs     # ATLAS_BASE overrides the origin
```

| Viewport | Planned validation | Result |
| --- | --- | --- |
| 1920×1080 | Advanced six-panel composition | NOT EXECUTED |
| 1440×900 | Standard and Advanced | NOT EXECUTED |
| 1280×800 | Laptop layout | NOT EXECUTED |
| 1024×768 | Compact desktop / tablet | NOT EXECUTED |
| 768×1024 | Tablet portrait | NOT EXECUTED |
| 390×844 | Mobile acceptance | NOT EXECUTED |

The journey asserts: standard header and navigation, company page content, Advanced shell, four
or more panels, palette instrument selection, palette refusal of an unknown symbol, tab drag,
splitter drag, save → reload → reopen, evidence inspector provenance, cutoff propagation to the
header, per-viewport horizontal overflow, and a 390×844 standard-mode check. It writes
`artifacts/phase9_4_*.png` and fails on console errors or failed requests.

## 4. What this means for the release decision

Standard and Advanced are **not** browser-certified. The typecheck, the production build, the
unit tests and the backend suite all pass, and the layout grammar is tested from both sides, but
no one has seen the interface render. The phase 9.3 memo browser journey remains open for the same
reason. Release readiness is therefore unchanged from Phase 9.3: internal use only.
