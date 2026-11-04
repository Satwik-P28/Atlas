# Architecture

Phase 1 is a layered, local-first system with one hard dependency rule and one
non-negotiable invariant: **every financial number must be traceable to an immutable
evidence record that knows when it became available.**

```
                    ┌──────────────────────────────┐
                    │        atlas.cli / demo       │
                    └───────────────┬───────────────┘
        ┌───────────────┬───────────┴────────┬────────────────┐
        ▼               ▼                    ▼                ▼
  atlas.entities   atlas.evidence      atlas.market     atlas.validation
  (identity)       (kernel)            (bars/actions)   (read-only audits)
        │               │                    │                │
        └───────────────┴─────────┬──────────┴────────────────┘
                                  ▼
                            atlas.storage
                    (SQLite, migrations, sources, DQ log)
                                  │
                                  ▼
                              atlas.core
             (ids, units, temporal semantics, concepts, errors)
                                  ▲
                                  │
                          atlas.ingestion
          (SEC client/parsers, CSV import) — depends downward only
```

`atlas.core` imports nothing from Atlas. `atlas.ingestion` is the only package that
talks to the outside world, and it produces domain records rather than writing SQL
directly for evidence. That asymmetry is what makes the kernel testable without a
network and the parsers replaceable without touching storage semantics.

---

## 1. Domain contracts (`atlas.core`)

### 1.1 Identifiers

Identifiers are deterministic and derived from identity anchors, never from mutable
attributes such as a ticker:

| Kind | Form | Anchor |
|---|---|---|
| Issuer | `ISS-CIK0000320193` | SEC CIK (or `ISS-E…` digest for non-registrants) |
| Security | `SEC-<20 hex>` | uuid5(issuer id, canonical share-class key) |
| Listing | `LST-<16 hex>` | uuid5(security, venue MIC, valid_from) |
| Ticker assignment | `TKR-<16 hex>` | uuid5(listing, ticker, valid_from) |
| Evidence | `EV-<24 hex>` | uuid5(source, entity, concept, accession, period, unit, value, availability, revision kind) |
| Raw document | `DOC-<20 hex>` | uuid5(source, sha256(body)) |
| Filing | `FIL-<20 hex>` | uuid5(accession number) |

Deterministic ids make ingestion idempotent without a sequence, and let two independent
Atlas instances derive identical ids from identical inputs. The uuid5 namespace is part
of the on-disk contract (changing it invalidates stored ids).

`evidence_id` deliberately includes `period_start` **and** `period_end`, value,
availability and revision kind: an annual and a quarterly fact can share an end date,
and omitting the start collapsed them during development (caught by a test, fixed).

### 1.2 Units

`Unit` parses XBRL/vendor strings into a typed dimension:

| Kind | Example | Arithmetic allowed |
|---|---|---|
| `monetary` | `USD` | with same currency only |
| `per_share` | `USD/shares` | with same currency only |
| `shares` | `shares` | with same kind |
| `pure` | `pure` | with same kind |

`Money` and `Quantity` use `Decimal` exclusively. Binary floats are rejected at the
boundary (`ValidationError`), and stored decimals are canonicalised (`"1000.00"` →
`"1000"`) so identical economic values hash identically.

### 1.3 Time

Four distinct times are stored, never conflated:

| Column | Meaning |
|---|---|
| `period_start`, `period_end`, `period_type` | reporting period (duration or instant) |
| `valid_from`, `valid_to` | effective/event interval |
| `filed_date`, `acceptance_datetime` | filing metadata |
| `availability_time` + `availability_precision` + `availability_basis` | evidenced public availability |
| `observed_at`, `ingest_seq` | when Atlas learned it, and in what order |

`AvailabilityPrecision`:

* `exact` — an instant is documented (SEC `acceptanceDateTime`);
* `date` — only a calendar date is evidenced; pinned to **end of day UTC**, which is
  conservative and therefore safe for as-of queries;
* `unknown` — no evidence; excluded from availability queries and reported.

### 1.4 Concept registry

32 canonical concepts across income statement, balance sheet and cash flow, each with
an ordered list of acceptable XBRL tags, an expected unit kind, a period type and a
declared sign policy. Three derivations (`gross_profit`, `total_debt`, `free_cash_flow`)
with explicit rule ids. Resolution is a pure function of (concept, available tags,
issuer overrides) — no fuzzy matching, and a missing concept returns `None`.

See [CONCEPTS.md](CONCEPTS.md) for the full table and coverage measured against Apple.

---

## 2. Schema (v2, 22 tables)

| Group | Tables |
|---|---|
| Sources | `source`, `raw_document` |
| Identity | `issuer`, `security`, `venue`, `listing`, `ticker_assignment`, `security_identifier`, `entity_relationship` |
| Calendar | `trading_session` |
| Filings | `filing`, `submissions_file` |
| Evidence | `evidence`, `evidence_supersession` |
| Market | `bar`, `corporate_action` |
| Derivations | `computation`, `computation_input` |
| Operations | `data_quality_issue`, `ingestion_run`, `sync_checkpoint`, `schema_migration` |

Migration 002 added `submissions_file` (archive content hashes and coverage for
incremental history sync) and the two derivation tables (the indexed projection of
evidence lineage; see ADR 0010). Migration 001 is unchanged.

Design choices worth stating:

* **Raw documents are stored verbatim** (`raw_document.body`) with SHA-256. An evidence
  record points at the exact bytes Atlas interpreted, so a value can be re-derived.
* **Bars are keyed by revision**, `PRIMARY KEY (security, mic, interval, ts, source,
  revision_seq)`. A provider correction appends `revision_seq + 1` and sets
  `supersedes_bar`; nothing is updated in place.
* **Supersession is stored twice** (`evidence.supersedes` on the newer row and an
  `evidence_supersession` edge table) so traversal works in both directions without
  rewriting history.
* **`ingest_seq`** is a monotonic counter assigned by the kernel. It is the only honest
  tie-break when two records claim the same availability instant, and it is what makes
  "what had Atlas ingested" reproducible.
* Foreign keys are enforced (`PRAGMA foreign_keys=ON`), which is not SQLite's default.

---

## 3. Evidence ingestion algorithm

```
record = EvidenceRecord.build(...)          # validates units, period, value, availability
content_hash = sha256(identity tuple)       # idempotency key
if content_hash exists          -> DUPLICATE (no write)
if evidence_id exists w/ diff hash -> StorageError (identity collision: a real defect)
prior = same (entity, concept, unit, period, tier)
for each prior with availability <= new.availability:
    if value differs -> SUPERSEDED link (+ reason)
insert record (ingest_seq = max+1); insert supersession edges
```

Key semantics:

* **A changed value supersedes. A re-assertion of the same value does not.** Later
  filings routinely repeat prior-year comparatives. Marking those "superseded" would
  misrepresent the source history and inflate revision counts; instead both records are
  retained and selection reports the earliest evidence of the unchanged value.
* **Unknown availability can never supersede** a dated record, because it may be older
  than what Atlas holds.
* **Basis tier** keeps authority separate: a direct source observation (tier 0) always
  outranks a derived calculation (tier 2) for the same concept and period.

Validation of the graph is part of `atlas validate` (dangling edges, cycles).

---

## 4. Point-in-time selection policy

Policy id: `atlas.select.point_in_time.v2`, attached to every result so a future policy
change is visible rather than silently rewriting historical answers.

Two implementations exist — Python grouping (`EvidenceKernel`) and SQL window functions
(`evidence/selection_sql.py`) — and are proven equivalent by a differential test over
randomised histories, adversarial cases and the real payload. Python is the default
because it measured faster (155 vs 236 ms all-concept); see ADR 0009.

For a query `(entity, as_of, mode)`:

1. Filter candidates on the mode's column: `availability_time` for
   `PUBLIC_AVAILABLE`, `observed_at` for `ATLAS_INGESTED`; require `<= as_of`.
2. Fetch unknown-availability candidates under public-availability semantics so they can
   be counted and explicitly excluded. Under `ATLAS_INGESTED` semantics the observation
   time is itself evidenced, so such records are knowable and are neither excluded nor
   counted twice.
3. Group by `(concept, period_start, period_end, unit)`.
4. Within a group, keep the lowest basis tier present (source beats derived).
5. Rank by `(mode column DESC, quality ASC, ingest_seq DESC, evidence_id ASC)`; the first
   record is the current version. The ordering is stated and tested rather than implicit.
6. If several records share that instant with **different** values, report a
   contradiction (values, evidence ids and the selected id) and adjudicate by revision
   chain tip, then quality, then latest ingestion. Quality alone could otherwise discard a
   correction that arrived with the same acceptance timestamp as the original.
7. If the value is unchanged across versions, return the **earliest** evidence of that
   value, so provenance points at the document that first established it.
8. Report `excluded_not_yet_available`, `excluded_unknown_availability`, completeness
   and contradictions alongside the facts.

`completeness` is deliberately explicit:

* `complete_for_query` — every candidate had evidenced availability ≤ as_of;
* `partial: N candidate record(s) excluded …` — some history could not be placed in time;
* `incomplete: no evidenced availability for any candidate record`.

A result is never silently presented as a complete reconstruction.

---

## 5. Provenance (Financial X-Ray)

`EvidenceKernel.provenance(evidence_id)` returns a structured report and a narrative:

1. value, unit and period;
2. source id, name, licence and redistribution status;
3. original taxonomy element (`us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`);
4. filing metadata: accession, form, filed date, acceptance timestamp;
5. evidenced availability and its basis;
6. observation time and derivation kind + rule;
7. transformation steps and, for derived values, each input's evidence id;
8. the complete revision chain with supersession edges;
9. raw document id, SHA-256 prefix, size and retrieval time;
10. limitations (unevidenced availability, date precision, unvalidated quality, revision status).

Derived values store their inputs in `transformation_lineage` as JSON, so a future
compiler can rebuild the dependency graph from the same records.

---

## 6. Identity model

Strict separation:

```
issuer (legal entity, CIK-anchored)
  └── security (tradable instrument, distinguished by share class)
        └── listing (security × venue, valid_from..valid_to)
              └── ticker_assignment (symbol, valid_from..valid_to, confidence, status)
```

Consequences enforced by tests:

* one issuer → multiple share classes → multiple securities with different ids;
* a ticker change closes the previous assignment the day before the effective date;
* a reused ticker resolves to different securities depending on `as_of`, and to *no
  security* in the gap between owners;
* overlapping claims by two securities are `ambiguous`; `require_single()` raises
  `AmbiguousResolution` rather than picking one;
* delisting closes listing and ticker windows but preserves them for historical queries;
* SEC cover-page tickers are attached with `probable` (single ticker) or `unverified`
  (multiple tickers) status, because SEC submissions do not state share classes.

Conflicting identifiers (e.g. the same ISIN on two securities from different sources)
are stored side by side and reported as ambiguous.

---

## 7. SEC pipeline

```
SecClient ──► submissions.json ──► parse_submissions ──► issuer + filing rows
      │                                                        │
      └──────► companyfacts.json ──► parse_companyfacts ◄──────┘  (filing index)
                                             │
                                             ▼
                                  EvidenceRecord[] ──► EvidenceKernel
```

Client behaviour:

* **Policy gate**: a User-Agent containing a contact address is mandatory; otherwise
  `SecPolicyError` before any request.
* **Host allowlist**: only `data.sec.gov` and `www.sec.gov`.
* **Rate limit**: token bucket, default 5 req/s (SEC guidance is ≤10).
* **Retries**: exponential backoff with jitter on 429/5xx, honouring `Retry-After`;
  bounded attempts; 403 fails loudly as a policy problem.
* **Caching**: responses stored as raw documents with content hash, ETag and timestamp;
  conditional requests (`If-None-Match`) return `304` and reuse the stored bytes.

Parsing decisions:

* Availability is taken from the filing's `acceptanceDateTime` when the filing is in
  the submissions payload (`exact`), else from the fact's `filed` date pinned to
  end-of-day UTC (`date`), else `unknown`.
* Form types ending in `/A` are marked `amendment`.
* Facts whose unit **kind** does not match the concept (e.g. revenue in `shares`) are
  rejected and counted. Facts in a different **currency** are retained as separate facts
  and reported (`multi_currency_concepts`) — never converted.
* Duplicate observations inside one accession are deduplicated; genuinely conflicting
  values inside one accession mark the surviving record `suspect` and log an error.
* Elements outside the registry are counted and listed (`unmapped_tags`), never coerced.

---

## 8. Market layer

**Calendars.** Stored per venue, generated from the NYSE/Nasdaq rule set (weekends, the
nine standard holidays as a function of year, Juneteenth from 2022, 13:00 ET early
closes). Sessions store UTC open/close instants computed with `America/New_York`, so DST
is handled by the zone database rather than arithmetic. Limitation: unscheduled
closures are not known; bars on non-session dates are reported by validation.

**Bars.** Raw observations only. Duplicate ingest is a no-op; a changed value appends a
revision. Structural problems (impossible OHLC, negative volume, VWAP outside range) are
recorded as quality flags and issues, never repaired. Validation additionally reports
missing sessions, off-calendar observations and unexplained large moves.

**Corporate actions.** Splits, reverse splits, cash dividends and ticker changes are
computable; mergers, spin-offs and distributions are declared and recorded but refused
by the adjustment engine (`UnsupportedActionError`). Corrections append a new row whose
`supersedes` points at the original.

**Adjustment mathematics** (documented in `market/adjust.py`):

* split factor for a bar = product of `ratio_to / ratio_from` over splits with
  `ex_date > bar_date`;
* split-adjusted price = `raw / factor`, volume = `raw × factor`, so the reference-date
  bar is unchanged and `adjusted × factor == raw` exactly;
* total return is an **index** (base 1.0), not a price:
  `TR[t] = TR[t-1] × (adj_close[t] + div_adj[t]) / adj_close[t-1]`,
  where `div_adj = cash / split_factor(ex_date)`;
* `knowledge_as_of` filters actions by evidenced availability and reports withheld ones;
* only `raw` bars may be adjusted — asking twice raises.

---

## 9. Operations

* **Migrations** are append-only, applied in a transaction, recorded in
  `schema_migration`, and refuse to run against a newer schema than the binary supports.
* **Transactions** are explicit and nestable (SAVEPOINT for inner scopes). Ingestion of a
  company's facts happens in a single transaction, so an interruption leaves no partial
  evidence.
* **Durability**: WAL for concurrent readers, `synchronous=FULL` so a commit survives an
  OS crash (the benchmark numbers include that cost).
* **Structured failures**: every deliberate error is an `AtlasError` subclass with a
  stable `code` and a context mapping; the CLI returns exit status 2 and prints the
  serialised error.
* **Quality log**: `data_quality_issue` with stable codes and severities, deduplicated
  and resolvable.

---

## 10. Where Phase 1 stops

Phase 1 owns data, identity and evidence. It does **not** own model execution, research
workflows, a compiler, simulation or a UI. The contracts those will use are specified in
[PHASE2_CONTRACT.md](PHASE2_CONTRACT.md): typed fact views, evidence handles, dependency
lineage, knowledge-time filters, and a stable JSON shape for every result.
