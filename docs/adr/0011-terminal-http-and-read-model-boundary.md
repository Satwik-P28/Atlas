# ADR 0011 — Terminal read models behind a local HTTP boundary

- **Status**: accepted (Phase 2)
- **Date**: 2026-11-04

## Context

Phase 1 exposed the evidence layer through Python and a CLI. A terminal needs the same
numbers in a browser, but the browser must not be able to write evidence, run SQL, or
reimplement point-in-time selection in TypeScript. Phase 2 also has to support two
interface modes (Standard and Advanced) without letting either mode become a second
calculation engine.

## Decision

Add `atlas.terminal` with three layers and a strict dependency direction:

```
api.py            HTTP surface: validation, error mapping, static hosting
  ↓
read_models.py    every number the terminal displays, computed at read time
  ↓
Phase 1           EvidenceKernel, SecurityMaster, BarStore, ActionStore, provenance
```

Rules:

1. **Read models own presentation arithmetic.** Ratios, growth, market cap and indicator
   series are computed in `read_models`/`screener` from point-in-time reads. They are
   never stored as evidence, never mutate the database, and never re-select facts with
   their own as-of logic — they call `EvidenceKernel.as_of`, so the policy id returned to
   the client (`atlas.select.point_in_time.v2`) is the policy that actually ran.
2. **Every value carries its evidence.** Statement cells expose `evidence_id`; metrics
   expose `evidence_ids`, `formula`, `inputs` and assumptions. The only derived numbers
   without their own evidence id are explicitly labelled as ratios computed at read time.
3. **No SQL from the client.** The HTTP surface accepts typed parameters only (path ids,
   enums, bounded integers, ISO dates). There is no query language, no SQL fragment, no
   column/table name parameter, and identifiers are always resolved through the security
   master rather than interpolated.
4. **One connection per request.** `get_db` opens a SQLite connection with
   `check_same_thread=False` and closes it after the response. SQLite connections are not
   shared across threads; a pool would be premature for a local single-user tool.
5. **Structured errors.** Every failure is `{"error": {"code", "message", "context"}}`
   with a stable code (`unknown_entity`, `validation_error`, `storage_error`,
   `database_missing`, `database_needs_migration`, `invalid_request`, `ambiguous_resolution`).
   A missing database is a 503 with the command that fixes it, not a stack trace.
6. **Pagination is explicit.** List endpoints take `limit`/`offset` with server-side caps
   and return `total`; truncated result sets say so.
7. **Local defaults.** The server binds `127.0.0.1` unless `--host` is given. CORS allows
   only loopback development origins (`localhost`/`127.0.0.1` on any port), not `*`.
   Static hosting refuses path traversal and serves `index.html` for client routes.
8. **Contract is published.** `/api/schema` states the selection policy, as-of semantics,
   indicator versions, panel types and error codes; FastAPI publishes OpenAPI at
   `/api/openapi.json`.

## Alternatives considered

* **GraphQL** — would let the client choose fields, but also encourages ad-hoc joins that
  bypass the read models; overkill for a local tool with a fixed screen set.
* **Server-side rendered pages** — simple, but the chart/workspace interactions need a
  client app anyway; duplicating templates would be worse.
* **Write API for derived values** — rejected. Derived values are cheap to recompute and
  storing them would create staleness that Phase 1's dependency index would then have to
  manage for no benefit.
* **Browser-side indicator maths** — rejected (see ADR 0013): two engines would drift and
  the mode-invariance guarantee would be untestable.

## Consequences

* The terminal works entirely offline against `var/atlas.db`; no cloud dependency.
* Read-time computation costs latency (`/api/companies` and the screener are the slow
  paths; measurements are in `docs/PHASE2_IMPLEMENTATION.md`). Caching is deliberately
  absent until there is evidence it is needed.
* There is no authentication. User data rows carry `owner_id = 'local'` so a future
  multi-user deployment can scope them without a migration; until then the API is a
  loopback tool and must not be exposed publicly.
* The HTTP layer has no business logic to unit test in isolation; the tests exercise the
  real app against a real database (see `tests/test_terminal_api.py`).
