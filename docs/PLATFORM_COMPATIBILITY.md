# Platform compatibility

## Verified

| Environment | Status | Evidence |
| --- | --- | --- |
| Linux x86_64 (this VM) | verified | full backend suite, audit script, package round-trip, production frontend build |
| Python 3.12 virtualenv (`.venv`) | verified | project test runner |
| SQLite (bundled) schema v10 | verified | migration and package tests |
| Chromium via Playwright | verified | Phase 8 acceptance; Phase 9 page build and API smoke |
| Node + Vite production build | verified | `npm --prefix web run build` |

## Not verified

- **macOS** and **Windows** installation, path handling and browser acceptance. No claim is
  made for either platform.
- Native ARM or musl environments.
- Any hosted or multi-tenant deployment: the terminal is a local, single-user application
  with restricted CORS and no authentication layer.

## Runtime characteristics

- Python standard library plus the pinned dependencies in `pyproject.toml`; no native
  extension is compiled by Atlas itself.
- SQLite is the only datastore; there is no server process besides the local API.
- SEC network access is required only to download new payloads. The Phase 9 fixture and all
  tests run offline.
- The research package is declarative and requires the installed Atlas runtime; it is not a
  standalone executable.
