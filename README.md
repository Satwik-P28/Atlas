# Atlas Quant — Phase 5

**A local-first financial research terminal and quantitative research lab built on a
point-in-time evidence platform.**

Phase 1 built the trustworthy layer: immutable evidence, exact availability, stable
security identity, adjustment mathematics and a reverse dependency index. Phase 2 added the
terminal. Phase 3 added the compiled financial model runtime, Model Forge, DCF and research
applications. Phase 4 added Quant Lab: point-in-time features, versioned strategies,
next-open backtests, an independently reconciled ledger, IBM real-data experiments and
Time Capsules. **Phase 5 adds institutional research:** a dated Treasury curve, independently
validated bond and European-option analytics, aligned portfolio risk, constrained
optimization, walk-forward validation with a complete attempt ledger, typed compiler
operators and two research applications inside Lab. See
[docs/PHASE5_IMPLEMENTATION.md](docs/PHASE5_IMPLEMENTATION.md).

```
5 issuers · 8 securities · 14,977 filings · 23,583 evidence records · 17,363 bars
6,793 real IBM vendor bars · 114 real IBM actions · schema v7
354 backend tests (344 through Phase 4 + 10 Phase 5/regression) · 4 frontend tests
Real SEC fundamentals for all issuers · official public 2024 U.S. Treasury curve
IBM prices REAL (Alpha Vantage demo, reported) · Phase 5 multi-asset panel SYNTHETIC
Apple/Microsoft/Walmart/Alphabet prices and actions clearly labelled SYNTHETIC
```

![Institutional fixed-income research](artifacts/29-institutional-fixed-income.png)

---

## 1. What works

### Phase 1 foundation (consumed, not rebuilt)

| Capability | Command |
|---|---|
| SEC filings + XBRL facts, recent and archive history | `atlas sec sync --cik 320193` |
| Point-in-time reconstruction, two time semantics | `atlas asof --cik 320193 --date 2024-06-01` |
| Provenance / Financial X-Ray | `atlas explain --evidence-id EV-…` |
| Entity, security, listing and ticker history | `atlas entity show --ticker FB --as-of 2021-06-01` |
| Immutable bars, splits, dividends, adjustment views | `atlas bars show … --adjustment total_return` |
| Validation, independent reconciliation, dependency index | `atlas validate`, `atlas reconcile`, `atlas deps` |

### Phase 2 terminal

| Capability | Where | Notes |
|---|---|---|
| Coverage overview | `/` | every stored security, last close, source, SYNTHETIC badge |
| Company search and profiles | `/companies` | name, ticker or CIK; ambiguous tickers are a hard stop |
| Financial statements | company → Statements | FY/quarterly, point-in-time, 14+ line items, every cell opens X-Ray |
| Metrics | company → Overview | formula, inputs, assumptions, evidence ids; missing inputs reported |
| Charts | company → Charts | candles/line/area, volume, raw / split / total-return index, action markers |
| Indicators | company → Charts | 9 server-computed, versioned indicators with formula table |
| Filings and events | company → Filings | SEC history and corporate actions; no synthetic headlines |
| Financial X-Ray | any value | value → source element → accession → document hash → narrative |
| Time machine | `/research` | reconstruct statements and metrics at a chosen instant |
| Screener | `/screeners` | 26 metrics, AND/OR, deterministic, CSV export, explicit universe |
| Watchlists | `/watchlists` | stable security ids, persisted in SQLite |
| Workspaces | `/workspaces` (Advanced) | validated JSON documents, 3 presets, resize/reorder/save/restore |
| HTTP API + OpenAPI | `/api/*` | typed validation, error envelope, pagination, source metadata |

### Phase 4 Quant Lab

| Capability | Where | Notes |
|---|---|---|
| Point-in-time features | `/lab`, `/api/quant/features` | price, return, SMA, momentum, volatility, volume z-score; cutoff enforced |
| Strategy objects | `/api/quant/strategies` | `atlas.strategy.v1` in the research-object registry |
| Event-driven backtests | `/lab`, `/api/quant/backtest` | close decision, next-open fill, costs, splits, dividends |
| Independent accounting | Lab reconciliation panel | cash/trade/commission/dividend/realized/unrealized identity |
| Buy-and-hold benchmark | every run | same bars and costs |
| Model Forge signal | Lab custom strategy | shared compiler and operator registry |
| Vectorized preview | `/api/quant/preview` | close-to-close triage, explicitly not a fill simulation |
| Experiments and Time Capsule | Lab history/capsule | save, reopen, fork, compare, replay, export |
| Source archives | `/api/research/archive` | SHA-256 bytes plus rights/retention metadata |

### Phase 5 institutional research

| Capability | Where | Notes |
|---|---|---|
| Multi-instrument panel | `/api/institutional/universe` | 935 aligned returns, 3 active synthetic names, 1 documented delisting |
| Treasury curve | `/api/institutional/curve` | official 2024 CSV, semiannual par bootstrap, exact SHA-256 |
| Bond analytics | `/api/institutional/bond` | clean/dirty price, accrued, YTM, durations, convexity, DV01, shocks |
| Option analytics | `/api/institutional/option` | BSM price/Greeks, parity, implied volatility |
| Portfolio risk | `/api/institutional/portfolio` | covariance, beta, VaR/ES, drawdown, contributions, sectors, stress |
| Optimization | `/api/institutional/optimize` | long-only, cap, cash, target return; explicit infeasibility |
| Walk-forward | `/api/institutional/validate` | rolling/expanding, embargo, frozen test, 24/36-attempt logs |
| Compiler operators | `/api/models/operators` | discount, bond, option, variance, volatility and risk contributions |
| Research applications | `/lab/institutional` | fixed income, portfolio risk, OOS validation, save/reopen/fork/export |

Reference bond (4.25% 2029, 2024-06-28 curve): clean **99.634862**, YTM **4.3294%**,
modified duration **4.461737**, DV01 **0.045422** per 100 face. BSM reference
(`S=K=100, T=1, r=5%, σ=20%`): call **10.450584**, put **5.573526**, parity residual below
`1e-12`. The 3-fold synthetic walk-forward returns **-4.18%** versus **2.33%** for equal
weight (189 test sessions); with 36 attempts, adjusted p is **1.0**. Negative results are
retained. Benchmarks and limits: [docs/PHASE5_BENCHMARKS.md](docs/PHASE5_BENCHMARKS.md).

Real IBM demonstration, 2,977 sessions (2015-01-02 → 2026-11-03), $100,000,
2 bps commission + 5 bps slippage: buy-and-hold **108.60%**, 20/100 trend **-39.49%**,
60-session momentum **16.12%**, Model Forge signal **24.17%**. Every ledger reconciled.
These are in-sample research results, not alpha claims. Full measurements:
[docs/PHASE4_BENCHMARKS.md](docs/PHASE4_BENCHMARKS.md).

### Phase 2.1 hardening and research

| Capability | Where | Notes |
|---|---|---|
| Real IBM market data | company → Charts | 6,793 Alpha Vantage bars, 114 actions, `reported`, archived with SHA-256 provenance |
| Independent validation | company → Research | recomputes margins, ratios, valuations, split adjustment and total return; IBM **233/233** |
| Financial history | company → Research | annual, evidence-linked, no interpolation |
| Peer comparison | company → Research | local universe only, medians over reporting issuers |
| Restatements / amendments | company → Research | superseded values retained and addressable |
| Research objects | `/api/research/objects` | v1 contracts for dataset/model/experiment/strategy/application; no execution |

Performance on the demo database: company list **1,341 ms → 48 ms cold / 9 ms cached**;
screener **3,285 ms → 1,604 ms**. See [docs/PHASE2_1_READINESS.md](docs/PHASE2_1_READINESS.md).

---

## 2. Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,terminal]"

# Build the demo database: real SEC fixtures + deterministic synthetic OHLCV
.venv/bin/python scripts/build_terminal_db.py --db var/atlas.db --force

# Build the terminal UI once (FastAPI serves web/dist)
cd web && npm ci && npm run build && cd ..

# Serve API + UI on loopback
.venv/bin/atlas --db var/atlas.db serve --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

Development UI with hot reload: `cd web && npm run dev` (Vite proxies `/api` to
`127.0.0.1:8000`). `make terminal-data`, `make web-build` and `make serve` wrap the same
steps. No network access is needed after the fixtures are present.

---

## 3. Two modes, one backend

**Standard** is the guided interface: overview, statements, charts, time machine, screener
and watchlists. **Advanced** adds the workspace editor, raw as-of controls and indicator
parameter inputs. Both call the same endpoints; switching modes re-renders and does not
change a single value. The browser journey captures statement text in both modes and
asserts they are identical.

![Advanced workspace](artifacts/08-workspace-advanced.png)

---

## 4. Data honesty

* Fundamentals are real, public-domain SEC EDGAR data archived in `fixtures/sec`.
* **IBM market prices are real vendor observations** from the Alpha Vantage demo source,
  registered as `reported`, with retrieval provenance and 114 corporate actions. They are
  raw observations, not proof of the vendor's 2015 display vintage; the Time Capsule reports
  `external_provider_only` because exact source bytes are not archived.
* **Other market prices are synthetic.** Apple, Microsoft, Walmart and Alphabet series are
  generated deterministically, registered as source `synthetic-demo` (kind `synthetic`),
  marked `data_status: "synthetic"` by the API, badged in every table and chart, and
  announced by a page-level banner. They are never described as exchange data.
* Apple's real 4:1 split (2020-08-28) and cash dividends are stored so raw, split-adjusted
  and total-return views can be verified against hand calculations.
* **Total return is an index (base 1.0), not a price.** Every response says so.
* **No currency conversion.** Ratios use same-currency inputs only; the dataset is USD.
* **Missing is not zero.** A missing statement input is `null` with `missing: true` and a
  visible dash; a metric that cannot be computed is listed in `missing`.
* **Screening covers the stored universe** (4 issuers) and says so explicitly; it is not a
  market-wide screen.
* **Point-in-time means point-in-time.** `as_of=2023-12-31` on Apple returns FY2023 and
  earlier, counts records that existed but were not yet public, and never leaks later
  restatements.

![Statements with X-Ray](artifacts/04-xray.png)

---

## 5. Non-negotiable guarantees

1. Evidence is immutable; restatements add records and preserve history.
2. No invented availability: unevidenced timing is excluded and counted, never assumed.
3. No ticker identity: tickers are time-bounded attributes of listings.
4. No float money and no silent unit mixing.
5. Adjusted series are never adjusted twice; a total-return index is never called a price.
6. Derived values state their rule and inputs; read-time ratios state their formula.
7. Ingestion is idempotent and transactional; restart safety is tested.
8. Filing coverage is reported; an unfetched archive is a counted gap.
9. Reconciliation re-derives facts with independent code.
10. Dependencies are indexed, not inferred.

---

## 6. Measured performance

`benchmarks/terminal_bench.py` against `atlas serve` on `var/atlas.db` (41.2 MB), 7 samples
per endpoint, Python 3.12.3, SQLite WAL. Server RSS **87.2 MB**; cold first read
(open DB + company page + statements) **1,817 ms**.

| Endpoint | Median | p95 |
|---|---|---|
| `GET /api/companies` | 1,341 ms | 1,396 ms |
| `GET /api/companies/{id}` | 205 ms | 209 ms |
| `GET /api/companies/{id}/statements` | 206 ms | 222 ms |
| `GET /api/companies/{id}/metrics` | 563 ms | 587 ms |
| `GET /api/securities/{id}/market` (1Y) | 28 ms | 30 ms |
| `POST …/market` (total return + 4 indicators) | 35 ms | 36 ms |
| `GET /api/evidence/{id}` | 2.6 ms | 2.8 ms |
| `POST /api/screeners/run` | 3,285 ms | 3,303 ms |
| `GET /api/companies/{id}/filings?limit=50` | 6.5 ms | 6.9 ms |

The company list and screener are recomputation-bound, not I/O-bound; a market-wide
universe would need caching or a materialised panel. No optimisation is claimed. Full runs
and caveats: [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

---

## 7. Verification

```bash
.venv/bin/python -m pytest -q          # 354 passed (344 through Phase 4 + 10 Phase 5/regression)
cd web && npm test -- --run            # 4 passed
cd web && npm run build                # tsc + vite
```

Browser journeys (`web/e2e/journeys.mjs`) cover the legacy terminal journeys;
`web/e2e/studio.mjs` covers 11 Phase 3 checks; `web/e2e/phase4.mjs` covers historical
reopen, buy-and-hold/trend/custom-model runs, accounting, Time Capsule replay, comparison,
JSON export and a 390px mobile viewport. `web/e2e/phase5.mjs` covers the Treasury curve,
bond pricing, saved fixed-income application, manifest download, portfolio risk,
optimization, walk-forward, comparison and a 390px viewport. Screenshots are in `artifacts/`.

---

## 8. Repository layout

```
src/atlas/
  core/        ids, units, temporal semantics, concept registry, typed errors
  storage/     SQLite engine, versioned migrations (schema v7), source registry
  evidence/    temporal evidence kernel, selection, provenance
  entities/    issuer / security / listing / ticker master and resolution
  market/      calendars, immutable bars, corporate actions, adjustments
  ingestion/   SEC client + parsers, CSV/Parquet import
  terminal/    read models, indicators, screener, user stores, workspaces, FastAPI app
  quant/       features, strategy contracts, portfolio ledger, simulator, Quant Lab
  finance/     Treasury curves, bond analytics, BSM options, statistical primitives
  institutional/ multi-asset fixture, risk, optimizer, walk-forward, persistence
  research/    research objects and content-addressed source archives
  cli.py       command line interface (incl. `serve`)
tests/         354 tests (Phase 1–5 plus terminal API/workspaces)
web/           React 19 + TypeScript + Vite terminal; Vitest and Playwright journeys
benchmarks/    Phase 1 benchmarks + terminal_bench.py
fixtures/      real SEC payloads and labelled synthetic fixtures
artifacts/     measured performance JSON and browser screenshots
docs/          architecture, ADRs, contracts, implementation record, benchmarks
```

Dependency rule: `core` depends on nothing; `terminal` may depend on everything below it,
never the reverse. The kernel does not know HTTP exists.

---

## 9. Known limitations

* IBM prices are real vendor demo observations; the other four issuers are synthetic. No
  licensed feed or survivorship-free universe is present.
* Phase 5's multi-asset panel is **synthetic**, with one delisted path. It is not a real
  market universe and is not survivorship-bias-free. IBM remains the only real security
  with price bars. No licensed multi-security history is present.
* Quant Lab supports one real instrument, long-only, raw daily bars and next-open fills. It
  does not model shorting, partial fills, market impact, intraday auctions or an order book.
* Phase 5 pricing is pure Python: no QuantLib, ORE, NumPy/SciPy, CVXPY or pandas is installed
  or claimed. Bonds are hypothetical, options are model values, and the optimizer handles
  at most eight assets with no turnover or sector caps.
* `ATLAS_MASTER_SPEC.md` v1.1 is absent from the checkout; `docs/PHASE5_CONTRACT.md` and the
  Phase 5 documents are the in-repo authority until the supplied master is added.
* No news, transcripts, estimates or analyst data; events are filings and actions only.
* Screening covers 4 issuers, not a market.
* X-Ray is reachable from statement cells, metrics and workspace evidence panels; chart
  bars are not individually clickable because bars are not evidence records.
* Workspace editing uses explicit buttons, not drag-and-drop.
* Single-user, no authentication. `owner_id = 'local'`; the server binds loopback by
  default and must not be exposed publicly.
* Frontend bundle ~525 kB (164 kB gzip); the chart library could be lazy-loaded.
* Browser verification in this container needs a workspace-local Chromium sysroot
  (`scripts/fetch_browser_libs.py`); that is test tooling, not a runtime dependency.

---

## 10. Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | module contracts, schema, ingest/selection algorithms |
| [docs/PHASE4_IMPLEMENTATION.md](docs/PHASE4_IMPLEMENTATION.md) | what Phase 4 built, real-data results, verification and limits |
| [docs/PHASE5_IMPLEMENTATION.md](docs/PHASE5_IMPLEMENTATION.md) | Phase 5 subsystems, schema 7, verification and boundaries |
| [docs/MULTI_INSTRUMENT_RESEARCH.md](docs/MULTI_INSTRUMENT_RESEARCH.md) | synthetic universe, alignment and portfolio semantics |
| [docs/HISTORICAL_UNIVERSE_INTEGRITY.md](docs/HISTORICAL_UNIVERSE_INTEGRITY.md) | membership, delisting and survivorship limits |
| [docs/WALK_FORWARD_VALIDATION.md](docs/WALK_FORWARD_VALIDATION.md) | partitions, selection protocol and attempt ledger |
| [docs/INSTITUTIONAL_PRICING_ARCHITECTURE.md](docs/INSTITUTIONAL_PRICING_ARCHITECTURE.md) | dependency audit and adapter boundary |
| [docs/YIELD_CURVE_CONTRACT.md](docs/YIELD_CURVE_CONTRACT.md) | Treasury source, bootstrap and conventions |
| [docs/BOND_PRICING_VALIDATION.md](docs/BOND_PRICING_VALIDATION.md) | bond formulas, reference values and tolerances |
| [docs/DERIVATIVES_PRICING.md](docs/DERIVATIVES_PRICING.md) | BSM model, conventions and limitations |
| [docs/PORTFOLIO_RISK.md](docs/PORTFOLIO_RISK.md) | covariance, VaR/ES, contributions and stress |
| [docs/PORTFOLIO_OPTIMIZATION.md](docs/PORTFOLIO_OPTIMIZATION.md) | constraints, solver and diagnostics |
| [docs/PHASE5_BENCHMARKS.md](docs/PHASE5_BENCHMARKS.md) | measured cold/warm research workloads |
| [docs/PHASE5_READINESS.md](docs/PHASE5_READINESS.md) | acceptance gates and unsupported scope |
| [docs/PHASE6_CONTRACT.md](docs/PHASE6_CONTRACT.md) | stable interfaces and next-phase prerequisites |
| [docs/QUANT_LAB_ARCHITECTURE.md](docs/QUANT_LAB_ARCHITECTURE.md) | Quant Lab modules, event ordering and boundaries |
| [docs/STRATEGY_CONTRACT.md](docs/STRATEGY_CONTRACT.md) | strategy schema, supported signals and rejection rules |
| [docs/FEATURE_ENGINE.md](docs/FEATURE_ENGINE.md) | features, cutoffs and anti-leakage behavior |
| [docs/PORTFOLIO_ACCOUNTING.md](docs/PORTFOLIO_ACCOUNTING.md) | ledger identities, costs, splits, dividends |
| [docs/PHASE4_VALIDATION.md](docs/PHASE4_VALIDATION.md) | acceptance matrix and test evidence |
| [docs/PHASE2_IMPLEMENTATION.md](docs/PHASE2_IMPLEMENTATION.md) | what Phase 2 built, verification ledger, measurements, defects fixed |
| [docs/PHASE3_CONTRACT.md](docs/PHASE3_CONTRACT.md) | stable API/JSON contracts and extension points for Phase 3 |
| [docs/PHASE2_CONTRACT.md](docs/PHASE2_CONTRACT.md) | Phase 1 → Phase 2 read/write interfaces |
| [docs/TERMINAL_CONTRACT.md](docs/TERMINAL_CONTRACT.md) | original read-model specification |
| [docs/CONCEPTS.md](docs/CONCEPTS.md) | canonical concept coverage and mapping policy |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | hardware, datasets, Phase 1 and Phase 2 measurements |
| [docs/VALIDATION.md](docs/VALIDATION.md) | reconciliation methodology and results |
| [docs/adr/](docs/adr/) | architecture decision records (24) |

Licence: Apache-2.0. Fixtures retain the licensing of their sources; see
[fixtures/README.md](fixtures/README.md).
