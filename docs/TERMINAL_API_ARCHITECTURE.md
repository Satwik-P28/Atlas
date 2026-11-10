# Terminal API Architecture

**Module:** `src/atlas/terminal/api.py` (application wiring)
**Extracted router:** `src/atlas/terminal/routes/market.py`
**Contract snapshot:** `tests/fixtures/openapi_phase9_2_7.json`
**Introduced:** Phase 9.2.7

## Before

`api.py` was ~1,950 lines and held four responsibilities at once: application
configuration (CORS, body limit, exception handlers, static mount, startup), route
declarations, request models, and response construction for every domain — companies,
research, market, indicators, quant, institutional, economic, applications, models,
workspaces and system. 139 routes in one module made the market endpoints hard to find and
the market contract hard to enforce at a boundary.

## After

| Layer | Location | Responsibility |
| --- | --- | --- |
| API / application wiring | `terminal/api.py` | FastAPI construction, middleware, exception mapping, request body limits, static frontend, router inclusion, dependency (`get_db`) |
| Routers | `terminal/routes/*.py` | route declarations, request validation, HTTP status mapping for their group |
| Read models | `terminal/read_models.py` | response construction, provenance, derived metrics, unavailable states |
| Domain contracts | `market/evidence.py`, `research/*`, `evidence/kernel.py` | selection, rights, arithmetic, evidence |

The first group extracted is the market group because Phase 9.2.7 changed its semantics:

```
GET  /api/markets/overview
GET  /api/securities/{security_id}/market
POST /api/securities/{security_id}/market
GET  /api/securities/{security_id}/actions
GET  /api/securities/{security_id}/observations
POST /api/market/replay
GET  /api/market/observations/{observation_id}/replay
GET  /api/market/observations/{observation_id}
```

`build_market_router(get_db)` receives the request-scoped database dependency from the
application, so routers never construct a connection, never import the app module, and
never create a cycle: `api → routes.market → read_models → domain`. `routes.market` does
not import `api`.

Shared behaviour stays central and unchanged: `AtlasError` mapping, validation errors,
`StarletteHTTPException` mapping, CORS origins, `RequestBodyLimitMiddleware`, the static
frontend mount, `/api/health` and `/api/schema`.

## Compatibility evidence

Before the extraction, the OpenAPI document was captured per route and stored as
`tests/fixtures/openapi_phase9_2_7.json`: method, path, operation id, tags, parameters
(name, location, required, schema), request body, and responses — 139 routes across 125
paths. `test_openapi_contract_is_unchanged` regenerates the document from the refactored
application and requires equality, including the route count.

A renamed function would change the operation id, a moved parameter would change its
location, and a reordered default would change its schema; each of those fails the test.
The extraction therefore cannot silently change the public contract.

Deliberate additions made in this phase are *response fields*, not route changes:

* `market_overview` rows gain `change_basis`, `change_1d_dates`, `change_1y_dates`,
  `change_1y_target`, `change_1y_span_days`, `price_observation_id`, `series_policy`,
  `series_limitations`;
* the chart response gains `series` (the series contract summary, without points);
* `issuer_metrics` gains `market_basis` and `market_cutoff`.

Additive fields do not appear in OpenAPI (responses are typed `dict[str, Any]`), and the
frontend continues to read the existing keys.

## Remaining extraction

The next coherent groups, in order, are: companies and filings, research objects and
applications, quant and learning, economic intelligence, institutional analytics, models
and execution. Each should move only when its semantics change or when a contract test
exists, so the work stays justified rather than cosmetic. The goal is not module count: a
group that shares no dependency and no contract boundary is better left in place than split
into a file that imports the same eleven things.
