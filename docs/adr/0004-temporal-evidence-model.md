# ADR 0004 — Temporal evidence model

- **Status**: accepted (Phase 1)
- **Date**: 2026-11-03

## Context

The specification calls this the most important architectural component of Phase 1 and
requires that an as-of query must never substitute a later restatement for the
information available at the requested historical date. It also requires distinguishing:

* **Question A** — what information was *publicly available* at time T?
* **Question B** — what information had *Atlas actually ingested* by time T?

Conflating event time, reporting period, publication time and ingestion time is the
canonical source of look-ahead bias in financial research.

## Decision

### 1. Evidence records are immutable assertions

One record = one source document asserting one concept for one entity over one period in
one unit. Corrections and restatements **insert**; they never update. The identity tuple
includes source, entity, concept, accession, full period, unit, value, evidenced
availability and revision kind, which makes ingestion idempotent and makes a changed
value a genuinely different record.

### 2. Four times, stored separately

Reporting period (`period_start`, `period_end`, `period_type`), effective interval
(`valid_from`, `valid_to`), publication (`filed_date`, `acceptance_datetime`,
`availability_time` + `precision` + `basis`), and system observation (`observed_at`,
`ingest_seq`).

### 3. Availability must be evidenced, and its absence is data

* `exact` — SEC `acceptanceDateTime`.
* `date` — only a filing date is known; pinned to **end of day UTC**. A query for that
  day therefore does not see the fact, which is the conservative direction.
* `unknown` — no timing evidence. Stored, excluded from availability queries by default,
  and counted in `excluded_unknown_availability` so the result is not misrepresented as
  complete.

Atlas never invents a timestamp, and never upgrades unknown to known.

### 4. Two explicit query modes, no default that hides the distinction

`AsOfMode.PUBLIC_AVAILABLE` filters on `availability_time`; `AsOfMode.ATLAS_INGESTED`
filters on `observed_at`. Both are exposed in the API and the CLI, results carry the mode
and the policy id, and tests assert they give different answers for the same instant when
publication and ingestion differ.

### 5. Supersession only on change

A later filing repeating a prior value is a new observation, not a revision. Marking it
superseded would misstate the source history. Records are linked when the **value
changes**, with a reason (`later_filing_same_period`, `amendment_of_…`, `restatement`).

### 6. Ingestion order is a first-class tie-break

Two records can share an availability instant (a correction filed with the same
acceptance second). Quality, then `ingest_seq`, then evidence id provide a deterministic
order. Without `ingest_seq`, corrected values ordered by hash — a real defect found while
testing corrections, fixed by adding the column.

### 7. Selection policy is versioned and explained

`atlas.select.point_in_time.v1` (superseded by v2 — see ADR 0009): lowest basis tier first (source beats derived), then
latest version at or before the query instant, then earliest evidence of an unchanged
value, with contradictions reported rather than averaged. Results always carry
completeness, exclusions and contradictions.

## Consequences

* Look-ahead prevention lives in the data layer, so every future backtester inherits it.
* Storage grows monotonically: a full restatement history is retained. At 5.7k facts per
  large issuer this is trivial; at whole-market scale, archival policy will be needed.
* Consumers must choose a mode. That is intentional friction: silence is how look-ahead
  bugs are born.
* Date-precision availability is deliberately pessimistic; researchers who need intraday
  precision must ingest the filing metadata that provides acceptance timestamps (Phase 1
  already does this for the filings it fetches).
