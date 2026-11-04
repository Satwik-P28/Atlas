# Phase 2 implementation record

- **Status**: implemented and verified locally (2026-11-04)
- **Scope**: a local-first financial research terminal on top of the Phase 1.1 evidence
  platform, plus the HTTP contract a Phase 3 model layer will consume.

Phase 2 did not rebuild Phase 1. It consumes `EvidenceKernel`, the security master,
`BarStore`, `ActionStore`, provenance and the dependency index through their public
interfaces. No Phase 1 table is written by the terminal, and no statement, ratio or
indicator is stored as evidence.

---

## 1. What was built

| Area | Module / files | Notes |
|---|---|---|
| Read models | `src/atlas/terminal/read_models.py` | companies, detail, statements, metrics, market series, overview, filings, events, X-Ray view |
| Indicators | `src/atlas/terminal/indicators.py` | 9 indicators, registry, parameter validation, version + calculation ids |
| Screener | `src/atlas/terminal/screener.py` | 26-metric catalogue, AND/OR filters, sorting, coverage accounting |
| User data | `src/atlas/terminal/store.py` | watchlists, workspaces, settings |
| Workspace schema | `src/atlas/terminal/workspaces.py` | panel registry, validation, 3 presets, canonical fingerprint |
| HTTP API | `src/atlas/terminal/api.py` | 30+ routes, error envelope, CORS, SPA hosting, OpenAPI |
| Storage | `src/atlas/storage/migrations.py` | migration 003 → schema v3 (`watchlist`, `watchlist_item`, `workspace`, `app_setting`) |
| CLI | `src/atlas/cli.py` | `atlas serve --host/--port/--web-dist` |
| Demo database | `scripts/build_terminal_db.py` | real SEC fixtures + labelled synthetic OHLCV |
| Frontend | `web/src/**` | React 19 + Vite 7 + `lightweight-charts` 5.2.1 |
| Browser verification | `web/e2e/journeys.mjs` | the 12 required journeys, screenshots in `artifacts/` |
| Performance | `benchmarks/terminal_bench.py` | measured against a live server; writes `artifacts/perf.json` |

Documented decisions: [ADR 0011](adr/0011-terminal-http-and-read-model-boundary.md)
(HTTP/read-model boundary), [ADR 0012](adr/0012-terminal-frontend-stack.md) (frontend),
[ADR 0013](adr/0013-server-side-indicator-registry.md) (indicators),
[ADR 0014](adr/0014-terminal-user-data-and-workspace-schema.md) (user data).

---

## 2. The demo database

Built by:

```bash
.venv/bin/python scripts/build_terminal_db.py --db var/atlas.db --force
```

| Measurement | Value |
|---|---|
| Issuers / securities / listed tickers | 4 / 7 / 7 |
| Filings (recent + archive history) | 13,977 |
| Evidence records | 18,657 |
| Synthetic daily bars | 10,570 (1,510 sessions, 7 securities) |
| Corporate actions | 169 (incl. Apple's real 4:1 split on 2020-08-28 and dividends) |
| Database size | 41.2 MB |

Fundamentals are real, public-domain SEC data archived in `fixtures/sec`. Market prices
are **deterministic synthetic series** registered as source `synthetic-demo`
(kind `synthetic`), never presented as quotes: the API returns `data_status:
"synthetic"`, the UI shows a SYNTHETIC badge and a page-level banner, and every synthetic
bar carries its source id.

---

## 3. Contract behaviour worth restating

* **One selection engine.** Statements and metrics call `EvidenceKernel.as_of`; the
  response reports the policy that ran (`atlas.select.point_in_time.v2`), completeness and
  exclusion counts. The TypeScript client has no as-of logic.
* **Balance-sheet concepts are instants by definition.** The statement builder takes the
  period axis from the concept registry, so a payload that stores a zero-length window
  cannot make the balance sheet disappear.
* **Every statement cell has an `evidence_id`.** Metrics carry `formula`, `inputs`,
  `assumptions`, `evidence_ids`, comparison period and price date; a missing input is
  listed in `missing`, never zero-filled.
* **No stale-price/fresh-statement mixing.** Market cap/P/E/P/S use the last stored close
  and report `price_as_of`; the price source is stated (`synthetic` here).
* **No currency conversion.** Ratios are computed only from same-currency inputs; the
  database contains USD facts.
* **Historical views never leak backwards.** `as_of=2023-12-31` on Apple returns FY2023
  and earlier only and counts facts that existed but were not yet public
  (`excluded_not_yet_available`).
* **Total-return is an index** (base 1.0). Indicators in that view are computed on the
  index level with the session's volume; the label says it is not a price.

---

## 4. Verification ledger

### Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend | `.venv/bin/python -m pytest -q` | **299 passed**, 0 failed (offline) |
| Frontend unit | `cd web && npm test -- --run` | **4 passed** (formatting/units) |
| Frontend typecheck + build | `cd web && npm run build` | tsc clean, 67 modules, JS 524.97 kB (163.86 kB gzip), CSS 20.41 kB |
| Browser journeys | `node web/e2e/journeys.mjs` | **12/12 journeys**, 12 screenshots |

New Phase 2 tests: `tests/test_terminal_indicators.py` (16), `tests/test_terminal_api.py`
(17), `tests/test_terminal_workspaces.py` (8). They cover hand-computed indicator values,
warm-up/insufficient-data behaviour, parameter rejection, statement selection and
exclusions, metrics formulas, market views and ranges, total-return indicators, X-Ray
provenance, filings/events, screener determinism and coverage, watchlist persistence across
two app instances, workspace validation and round-trip, settings, read views never writing
evidence, and the missing-database 503.

### Required browser journeys

Run against the production build served by `atlas serve` (Chromium 156 headless,
1440×960 and 390×844):

| # | Journey | Evidence |
|---|---|---|
| 1 | Load terminal | `artifacts/01-markets-desktop.png` |
| 2 | Search "Apple" → company page | `02-company-overview.png` |
| 3 | Statements (14 line items × 7 periods) | `03-statements.png` |
| 4 | Open Financial X-Ray from a value | `04-xray.png` |
| 5 | As-of 2023-12-31 excludes FY2024+ | `05-as-of.png` |
| 6 | Chart + RSI indicator (v1 formula row) | `06-charts-indicators.png` |
| 7 | Watchlist add → reload → still there | `07-watchlist.png` |
| 8 | Advanced workspace create, resize, save, reload | `08-workspace-advanced.png` |
| 9 | Screener (3 matches of 4 issuers, coverage note) | `09-screener.png` |
| 10 | Standard vs Advanced display identical values | `10-mode-advanced.png` |
| 11 | API failure shows a degraded state, not a blank page | `11-offline-api.png` |
| 12 | 390×844 company page, no horizontal overflow | `12-company-mobile.png` |

Defects found and fixed during verification:

1. `Resolution.resolved` is a property; calling it broke ticker resolution (500).
2. Balance-sheet rows vanished when a fact's own period type was `duration`; the statement
   axis now comes from the concept registry.
3. Total-return indicators were fed index points with no OHLC keys (500); they now use the
   index level and session volume, with a regression test.
4. `/api/search` did not exist; the typeahead called it and showed a 404. Added a
   stored-universe-only search with a test.
5. Verification restarts must kill the actual port listener; the first CLI PID was a
   parent and the stale process served old bytecode.

---

## 5. Measured performance

`benchmarks/terminal_bench.py` against `atlas serve`, 7 samples per endpoint, local SSD,
Python 3.12.3, SQLite WAL. Server RSS 87.2 MB; cold first read (open DB + company page +
statements) 1,817 ms.

| Endpoint | Median | p95 |
|---|---|---|
| `GET /api/health` | 172.4 ms | 177.3 ms |
| `GET /api/companies` | **1,341.1 ms** | 1,396.3 ms |
| `GET /api/companies/{id}` | 205.0 ms | 208.9 ms |
| `GET /api/companies/{id}/statements` | 205.5 ms | 222.2 ms |
| `GET /api/companies/{id}/metrics` | 563.2 ms | 586.5 ms |
| `GET /api/securities/{id}/market` (1Y, split) | 28.2 ms | 30.2 ms |
| `POST …/market` (1Y, total return, 4 indicators) | 34.7 ms | 35.5 ms |
| `GET …/statements` as-of 2023-12-31 | 185.7 ms | 202.8 ms |
| `GET /api/evidence/{id}` | 2.6 ms | 2.8 ms |
| `POST /api/screeners/run` | **3,285.1 ms** | 3,303.1 ms |
| `GET /api/companies/{id}/filings?limit=50` | 6.5 ms | 6.9 ms |

The two slow paths are recomputation, not I/O: the company list builds per-issuer
aggregates, and the screener evaluates point-in-time metrics per issuer. They are correct
and deterministic, but a market-wide universe would need caching or a materialised panel.
No speedup is claimed.

---

## 6. Limitations

* Market prices are synthetic; there is no licensed feed. Importing real bars would make
  the same read models return `data_status: "reported"` without code changes.
* X-Ray links from the metric grid/workspace panels are implemented where a cell exists;
  market-bar values are not individually clickable (bars are not evidence records).
* Standard mode hides advanced affordances but uses the same endpoints; the workspace
  editor exists only in Advanced mode, by design.
* Screening covers the 4 stored issuers and says so; it is not a market-wide screen.
* No news, transcripts, estimates or analyst data; events are filings and corporate
  actions only.
* No authentication or sharing. `owner_id` is `'local'` on every user row; the server is a
  loopback tool and must not be exposed publicly.
* No drag-and-drop workspace editing (explicit move/resize controls only), and no
  cross-workspace panel reuse.
* Frontend bundle is ~525 kB; the chart library is a candidate for lazy loading.
* Browser verification needs a Chromium sysroot in this container
  (`scripts/fetch_browser_libs.py`); that is test tooling, not a runtime dependency.

---

## 7. Reproduction

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,terminal]"

.venv/bin/python scripts/build_terminal_db.py --db var/atlas.db --force
.venv/bin/python -m pytest -q

cd web && npm ci && npm run build && cd ..
.venv/bin/atlas --db var/atlas.db serve --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

Browser journeys (once Playwright Chromium and its libraries are available):

```bash
cd web
npx playwright install chromium
node e2e/journeys.mjs          # writes ../artifacts/*.png
```

Performance: `.venv/bin/python benchmarks/terminal_bench.py --pid <server pid>`.
