# Phase 8 implementation

## Architecture

`src/atlas/applications/` adds a package layer over existing subsystems:

- `contracts.py`: deterministic ZIP, manifest validation, content root, file roles, compatibility.
- `rights.py`: action-level source-rights decisions; fail-closed packaging enforcement.
- `service.py`: economic export, install/open/verify/execute/fork/export/uninstall, gallery.
- `packs.py`: declarative domain-pack contract and transactional installation.
- `sdk.py`: scaffold/source validation/build using the existing FEC compiler.
- `cli.py`: `atlas app` command implementation.

Schema migration 10 stores installations, package bytes, execution history and pack records.
`storage/safety.py` provides backup, integrity and foreign-key checks around migration. The API
adds the gallery/package lifecycle and health counts. The React `/applications` page offers install,
export, execute, verify, download, fork and uninstall without executing package code.

The economic package uses the Phase 7 `EconomicService` panel, saved analysis and FEC-backed
scenario. Its runtime reproduces `atlas.economic.weather_demand.v1` with the package panel and
recomputes the scenario through `atlas.fec.model.v1`. The report repeatedly asserts the preserved
test RMSE/R², bias, non-identification and hypothetical company.

Station claims retain both observations and the conflict row, but classify it as
`spatial_representativeness`: different point locations are not competing estimates of one truth.
The API reports `logical_conflict_count: 0`.

## Pinned fixture

`fixtures/phase8/flagship_weather_demand.atlas` (47,270 bytes, SHA-256
`92ab1bf753438a0f534a080697abca9c638da11521e13c1dc43700883c82227b`) contains six files:
application metadata, canonical panel, analysis, scenario, source rights and README. The pack
`fixtures/phase8/energy_research_pack.json` pins that hash.

## Verification

- 15 Phase 8 backend tests passed; the full suite is **387 passed**.
- Frontend tests are **4 passed**; the production build succeeds at 674.74 kB / 200.15 kB gzip.
- `web/e2e/phase8.mjs` passed against a fresh schema-10 database and the production bundle. It
  imported the pinned package, executed it, verified integrity, downloaded the exact bytes, forked
  locally and checked 1440 px and 390 px layouts for horizontal overflow.
- Browser execution reproduced test RMSE **2,956.58 MW** and test R² **−0.8935**, with causal status
  `not_identified` and the statement that package code is never imported.
- Screenshots: `artifacts/38-application-gallery.png` and `artifacts/39-applications-mobile.png`;
  machine-readable results: `artifacts/phase8_browser.json`.
- Benchmark medians: build 23.904 ms, install 5.426 ms, verify 2.526 ms, execute 25.761 ms.
- No push, deployment or external publication was performed.

The missing `ATLAS_MASTER_SPEC.md` remains the one blocked requirement. It was not fabricated.
