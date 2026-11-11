# Phase 9.4.1 — browser acceptance

**Status: EXECUTED and PASSING.** Chromium 156 (Playwright build 1248) now launches in this
container, and the committed journey passes every assertion at all six viewports.

## 1. How the blocker was actually removed

Phase 9.4 failed because nine shared libraries were missing and `sudo` is refused. The fix was a
rootless package index, not a manual library hunt:

```bash
mkdir -p /tmp/aptlists/partial /tmp/aptcache
apt-get -o Dir::State::Lists=/tmp/aptlists -o Dir::Cache=/tmp/aptcache update
APT="apt-get -o Dir::State::Lists=/tmp/aptlists -o Dir::Cache=/tmp/aptcache"
cd /tmp/atlas-debs2
for pkg in libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libxcomposite1 \
           libxdamage1 libxfixes3 libxrandr2 libxkbcommon0 libasound2t64 \
           libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgbm1 libxrender1 libxi6; do
  $APT download "$pkg"
done
for f in *.deb; do dpkg-deb -x "$f" ~/.local/atlas-browser-libs; done
./node_modules/.bin/playwright install chromium
```

Two further failures were diagnosed from Chromium's own stderr:

1. `FATAL:third_party/skia/.../SkFontMgr_FontConfigInterface.cpp:163] Not implemented.` — no
   fontconfig directory. Fixed by extracting `fonts-dejavu-core` to `~/.local/fonts` and writing
   `~/.config/fontconfig/fonts.conf` with that directory and a writable cache.
2. `Target page, context or browser has been closed` — the renderer needs single-process mode in
   this container. Launch flags:
   `--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu --single-process --no-zygote`.

Those flags relax isolation inside the test browser only. They are not a production change and are
not applied to the application.

## 2. Environment used

| Item | Value |
| --- | --- |
| API | `var/phase9_export.db` on `:8000` (21 issuers, 26,440 evidence, statements and metrics populated) |
| Frontend | Vite dev server on `:3000`, `/api` proxied to `:8000` |
| Browser | Chromium 156.0.8078.4 (headless shell), `LD_LIBRARY_PATH` + `FONTCONFIG_*` set |
| Command | `ATLAS_ARTIFACTS=../artifacts node e2e/phase9_4_workstation.mjs` from `web/` |
| Result | **31 assertions, 0 failures**, console and network clean |

`var/phase9.db` was rejected for acceptance because its only security is synthetic and it has no
statement periods; the journey would have "passed" against empty panels.

## 3. Viewport matrix — executed

| Viewport | Overflow | Operable | Screenshot |
| --- | --- | --- | --- |
| 1920×1080 | none | yes | `artifacts/phase9_4_advanced_1920x1080.png` |
| 1440×900 | none | yes | `artifacts/phase9_4_advanced_1440x900.png` |
| 1280×800 | none | yes | `artifacts/phase9_4_advanced_1280x800.png` |
| 1024×768 | none | yes | `artifacts/phase9_4_advanced_1024x768.png` |
| 768×1024 | none | yes | `artifacts/phase9_4_advanced_768x1024.png` |
| 390×844 | none | yes | `artifacts/phase9_4_advanced_390x844.png` |
| 390×844 (Standard) | none | yes | `artifacts/phase9_4_standard_mobile.png` |

Additional captures: `phase9_4_standard_markets.png`, `phase9_4_standard_company.png`,
`phase9_4_advanced_desk.png`, `phase9_4_advanced_desk_docked.png`, `phase9_4_advanced_evidence.png`.

## 4. What the journey exercises

Standard header and navigation; company page with statements/metrics; Advanced shell and rail;
six-panel desk; instrument selection; statements (12 rows) and metrics (24 rows) rendering for a
real issuer; command palette opening statements; unknown-symbol refusal; tab drag; splitter drag;
save (with collision-free naming); reload and reopen on the saved URL; evidence inspector
provenance; cutoff propagation to the header; six viewports with overflow and operability checks;
390×844 Standard navigation.

## 5. Reproduce from a clean container

```bash
# dependencies (see §1), then:
python -m atlas.cli --db var/phase9_export.db serve --host 0.0.0.0 --port 8000 --allow-non-loopback &
(cd web && ./node_modules/.bin/vite --host 0.0.0.0 --port 3000 --strictPort) &
export LD_LIBRARY_PATH="$HOME/.local/atlas-browser-libs/usr/lib/x86_64-linux-gnu"
export FONTCONFIG_PATH="$HOME/.config/fontconfig"
export FONTCONFIG_FILE="$HOME/.config/fontconfig/fonts.conf"
cd web && ATLAS_ARTIFACTS=../artifacts node e2e/phase9_4_workstation.mjs
```

## 6. Limits of this certification

- Desktop and mobile Chromium only. Firefox, WebKit and Safari are not exercised.
- No screen reader or forced-colours pass; keyboard resizing and tab roving are asserted by
  implementation and unit tests, not by an assistive-technology audit.
- The browser runs single-process, which is a test-environment concession.
- Export-byte verification of memos (Phase 9.3) was not re-run in this phase.
