# Phase 8 acceptance record

This record distinguishes executable evidence from claims. The master-spec import gate is not
satisfied because the genuine specification is absent.

| # | Gate | Status | Evidence |
| ---: | --- | --- | --- |
| 1 | Phase 7 interfaces preserved; no rebuilt FEC/economic engine | pass | `tests/test_phase7_economic.py`; runtime dispatch |
| 2 | Genuine master specification imported and checksummed | **blocked** | file absent; no substitute created |
| 3 | Versioned `atlas.application_package.v1` contract | pass | `applications/contracts.py`, package spec |
| 4 | Deterministic package bytes | pass | repeated-build test; fixed ZIP metadata |
| 5 | Path-safe, declarative-only archive | pass | traversal/suffix/symlink tests |
| 6 | Integrity and tamper rejection | pass | hash/content-root tests |
| 7 | Transactional install and rollback | pass | injected-failure test |
| 8 | Backend-enforced data rights | pass | restricted-source and file tests |
| 9 | Clean-database import/execute | pass | fresh DB with zero observations |
| 10 | Real 2023 economic application packaged | pass | 47,270-byte pinned fixture |
| 11 | Limitations preserved | pass | RMSE 2,956.58, R² −0.8935, hypothetical firm |
| 12 | Station conflict corrected | pass | spatial, zero logical conflicts |
| 13 | SDK and CLI | pass | scaffold/validate/test/build/install/list |
| 14 | Real declarative domain pack | pass | `energy_research_pack.json` |
| 15 | Local gallery and API lifecycle | pass | 15 backend tests; browser import/execute/fork |
| 16 | Migration backup/rollback/doctor | pass | schema 9→10 backup test |
| 17 | Supply-chain manifest and SBOM | pass | `artifacts/release_manifest.json`, `sbom.cdx.json` |
| 18 | Measured benchmarks | pass | build 23.9 ms / install 5.4 ms / execute 25.8 ms median |
| 19 | Documentation set and ADRs | pass | docs 1–16 plus ADR 0035–0039 |
| 20 | Signed/trusted marketplace and executable extensions | not implemented | explicitly out of scope |

Final verification: **387 backend tests passed**, **4 frontend tests passed**, production build
succeeded, and `web/e2e/phase8.mjs` passed desktop and 390 px browser acceptance. The browser
reproduced RMSE **2,956.58 MW** and R² **−0.8935**, verified unsigned integrity, forked the
installation and captured `artifacts/38-application-gallery.png` and
`artifacts/39-applications-mobile.png`. Machine-readable results are in
`artifacts/phase8_browser.json`.

Gate 2 remains **blocked**, not passed: the genuine master specification was never available.
