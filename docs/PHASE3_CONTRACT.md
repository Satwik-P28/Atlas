# Phase 3 integration contract

Phase 2 exposes a working terminal and a stable read/write contract. Phase 3 (models, the
Financial-Economic Compiler, portfolio analytics, alerts) must build on it without
reaching into tables or replacing the evidence kernel.

Everything below is implemented in Phase 2 unless marked **proposed**.

---

## 1. Versioned identifiers

| Contract | Value | Change policy |
|---|---|---|
| Terminal JSON schema | `atlas.terminal.v1` | additive fields only |
| Workspace document | `atlas.workspace.v1` | additive; unknown keys rejected |
| Selection policy | `atlas.select.point_in_time.v2` | new id for semantic change |
| SQLite schema | `3` (`schema_migration`) | append-only migrations |
| Indicator formula | `atlas.indicator.<key>.v1` | new version id for any change |
| Indicator calculation | hash(version, params, input fingerprint) | reproducible |
| Derived evidence | `atlas.derived.<concept>.v1` | Phase 1 contract |
| Error codes | fixed set in `/api/schema` | new codes are additive |

---

## 2. HTTP surface

Base: `http://127.0.0.1:8000`, OpenAPI at `/api/openapi.json`, contract summary at
`/api/schema`.

### Read

```
GET  /api/health
GET  /api/companies?q=&limit=&offset=
GET  /api/search?q=&limit=
GET  /api/companies/{issuer_id|ticker|CIK}
GET  /api/companies/{id}/statements?statement=income|balance|cashflow&period=FY|Q
                                 &as_of=<ISO>&mode=public_available|atlas_ingested
                                 &limit=&offset=
GET  /api/companies/{id}/metrics?as_of=&mode=
GET  /api/companies/{id}/filings?limit=&offset=&forms=
GET  /api/companies/{id}/events?limit=
GET  /api/companies/{id}/xray?as_of=
GET  /api/securities/{security_id}/market?range=1M|3M|6M|1Y|2Y|5Y
                                     &view=raw|split|total_return&start=&end=&as_of=
GET  /api/evidence/{evidence_id}
GET  /api/markets/overview
GET  /api/indicators
POST /api/indicators/preview
GET  /api/screeners/metrics
POST /api/screeners/run
GET  /api/watchlists
GET  /api/workspaces
GET  /api/workspaces/presets?issuer=&security=
GET  /api/settings
```

### Write (user data only)

```
POST/PATCH/DELETE /api/watchlists[/{id}]
POST/DELETE       /api/watchlists/{id}/items[/{security_id}]
PUT               /api/watchlists/{id}/order
POST/PUT/DELETE   /api/workspaces[/{id}]
PUT               /api/settings
```

No Phase 2 endpoint writes evidence. Phase 3 derived values must go through
`EvidenceKernel.ingest` with lineage and a registered source, as specified in
[PHASE2_CONTRACT.md](PHASE2_CONTRACT.md) §2.

---

## 3. Shapes Phase 3 may rely on

**Statement cell**

```json
{"value": "391035000000", "unit": "USD", "evidence_id": "EV-…", "missing": false,
 "revision_count": 1, "availability_precision": "exact"}
```

`value` is a canonical decimal string (never a float). `missing: true` means not reported;
it is never zero.

**Metric**

```json
{"key": "gross_margin", "label": "Gross margin", "value": 0.462, "unit": "fraction",
 "kind": "derived_ratio", "formula": "gross_profit / revenue",
 "inputs": [{"concept": "gross_profit", "evidence_id": "EV-…"}],
 "assumptions": [], "evidence_ids": ["EV-…"], "period_end": "2025-09-27",
 "price_as_of": "2024-12-31", "comparison_period_end": "2024-09-28"}
```

**Market series**

```json
{"view": "total_return", "adjustment_status": "total_return_index",
 "price_basis_note": "…not a price…", "data_status": "synthetic",
 "coverage": {"first": "…", "last": "…"}, "range": {"start": "…", "end": "…"},
 "range_note": "window ends at the last stored session (…), not today",
 "bars": [], "index": [{"time": "2024-12-31", "value": 1.042}],
 "actions_applied": [], "actions_withheld": [], "truncated": false,
 "indicators": [{"key": "sma", "version": "atlas.indicator.sma.v1",
                 "params": {"window": 50}, "formula": "…",
                 "calculation_id": "…", "series": [{"name": "sma", "points": []}]}]}
```

**Errors**

```json
{"error": {"code": "validation_error", "message": "…", "context": {"field": "window"}}}
```

Codes: `unknown_entity`, `ambiguous_resolution`, `validation_error`, `storage_error`,
`database_missing`, `database_needs_migration`, `invalid_request`, `not_found`.

**Pagination** — list endpoints return `items`, `count`/`total`, and honour bounded
`limit`/`offset`. Clients must not assume the default returns everything.

---

## 4. In-process reuse

Phase 3 can import the terminal read models directly (same process, same SQLite file):

```python
from atlas.terminal import read_models, screener

read_models.list_companies(db, q="Apple")
read_models.company_detail(db, "ISS-CIK0000320193")
read_models.statements(db, issuer_id, statement="income", period="FY",
                       as_of="2024-06-01T00:00:00Z", mode="public_available")
read_models.issuer_metrics(db, issuer_id, as_of=..., mode=...)
read_models.market_series(db, security_id, range_key="1Y", view="split",
                          indicators=[{"key": "sma", "params": {"window": 50}}])
screener.run_screener(db, filters=[...], match="AND", sort={...})
```

Rules: pass a request-scoped `Database`; never hold a connection across threads; treat the
returned dicts as read-only. A model that needs a new derived value writes it through the
kernel and indexes its inputs (Phase 1 dependency index), not into a read model.

---

## 5. Extension points

| Need | How | Must not |
|---|---|---|
| New indicator | add registry entry + version + tests in `indicators.py` | compute an indicator in the browser |
| New screener metric | add to `screener.METRICS` with unit/formula/missing rule | treat a missing input as 0 |
| New panel type | add to `workspaces.PANEL_TYPES` with a validator, then a renderer | accept arbitrary component names/config |
| New statement line | map the concept in Phase 1 and add it to the statement layout | compute it in the client |
| New user-data table | append a migration; scope every query by `owner_id` | store secrets in `app_setting` |
| Multi-user | pass a real subject into stores; enforce at the HTTP boundary | expose the current loopback API publicly |

---

## 6. Invariants Phase 3 must preserve

1. Every displayed number resolves to an `evidence_id` (or is explicitly a read-time ratio
   whose inputs do).
2. As-of results state completeness and exclusions; no look-ahead, no restatement leakage.
3. No currency conversion, no float money, no unit mixing.
4. Synthetic data is labelled everywhere it appears.
5. Total-return is an index, never a price; adjusted series are never re-adjusted.
6. Watchlists and workspaces reference stable security/issuer ids, not tickers.
7. No arbitrary SQL, expression evaluation or code execution from the browser.
8. `standard` and `advanced` modes return identical numbers from the same endpoints.

---

## 7. Proposed Phase 3 work

* Model runs that ingest derived evidence with lineage, a registered source, and
  dependency-index records; the terminal can render them as another metric kind.
* Portfolio/position analytics as derived evidence, with the same X-Ray trail.
* A materialised metric panel or cache for a market-wide screener (current screener is
  4 issuers and measured at ~3.3 s).
* Authentication and per-owner scoping, replacing `owner_id = 'local'`.
* Licensed market data adapter; `data_status` and source metadata already distinguish
  reported from synthetic series.
* Workspace sharing/permissions (new tables; the document schema is already portable).

---

## 8. Compatibility checklist for Phase 3

- [ ] `GET /api/schema` still reports `atlas.terminal.v1` and schema 3 (or a migrated,
      higher version with a migration path).
- [ ] Every existing endpoint keeps its shape; additions are optional fields.
- [ ] Indicator versions are unchanged or newly versioned; existing calculation ids stable.
- [ ] Existing workspace documents validate unchanged.
- [ ] `pytest -q` (299 baseline tests) still passes.
- [ ] `web` build and the 12 browser journeys still pass.
- [ ] No read endpoint writes evidence (assert evidence count before/after).
