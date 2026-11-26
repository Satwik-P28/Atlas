# Phase 2 terminal contract (specification only)

This document specifies the read contracts a future Atlas terminal may rely on. **No
terminal, HTTP server or UI is implemented in Phase 1.1.** Everything below exists today as
Python/CLI behaviour unless marked *proposed*; the point is to freeze the shapes so the
terminal can be built without changing the evidence layer.

## 1. Principles

1. The terminal is a **view**. It never writes evidence; derived values go through the
   kernel, and only via a computation that names its inputs.
2. Every number rendered must be traceable to an `evidence_id` in one interaction.
3. Time semantics are always explicit. There is no default "current" query that silently
   mixes public availability with ingestion time.
4. Missing data is rendered as missing, with the reason. No interpolation, no carry-forward,
   no placeholder zero.
5. Identity is never guessed. `ambiguous` is a terminal state, not a prompt to pick the
   most likely candidate.

## 2. Read models

### 2.1 Entity header

```json
{
  "entity": {"issuer_id": "ISS-CIK0000320193", "cik": "0000320193",
             "legal_name": "Apple Inc.", "fiscal_year_end": "0928", "sic": "3571"},
  "securities": [{"security_id": "SEC-…", "class_designation": "common stock",
                  "security_type": "common_stock", "status": "probable",
                  "tickers": [{"ticker": "AAPL", "mic": "XNAS",
                               "valid_from": "2026-11-04", "valid_to": null,
                               "status": "probable", "confidence": 0.6}]}],
  "counts": {"evidence": 5737, "filings": 2272, "bars": 0},
  "warnings": ["ticker start dates are not evidenced by SEC; historical resolution is conservative"]
}
```

Contract notes:

* `tickers[].valid_from` is the date Atlas observed the assignment, **not** the listing
  date. The terminal must not render it as "listed since" (see §5).
* `warnings` is always present (possibly empty) so adding one is not a breaking change.

### 2.2 Point-in-time facts

`EvidenceKernel.as_of(...).to_dict()` — stable fields:

```json
{
  "entity_id": "…", "as_of": "2024-06-01T00:00:00Z",
  "mode": "public_available", "mode_description": "…",
  "policy": "atlas.select.point_in_time.v2",
  "completeness": "complete_for_query",
  "excluded_not_yet_available": 1,
  "excluded_unknown_availability": 0,
  "contradictions": [{"concept": "revenue", "values": ["100", "90"],
                      "evidence_ids": ["EV-…", "EV-…"], "selected": "EV-…",
                      "time": "…", "note": "…"}],
  "notes": ["1 record(s) existed but were not available at the requested instant"],
  "truncated": false,
  "facts": [{
     "concept": "revenue", "value": "383285000000", "unit": "USD", "currency": "USD",
     "period_start": "2022-09-25", "period_end": "2023-09-30",
     "period_type": "duration", "fiscal_year": 2023, "fiscal_period": "FY",
     "evidence_id": "EV-…", "source_concept": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
     "derivation_kind": "source_observation", "derivation_rule": null,
     "quality": "verified", "verification": "source_primary",
     "availability_time": "2023-11-03T16:04:28Z", "availability_precision": "exact",
     "revision_kind": "original", "revision_count": 3,
     "superseded_versions": ["EV-…", "EV-…"], "flags": ["multiple_versions"],
     "accession_number": "0000320193-23-000106", "form_type": "10-K"
  }]
}
```

Rendering requirements:

* `completeness` and the two exclusion counts must be visible whenever either is non-zero.
* `contradictions` must be surfaced, not averaged or silently resolved.
* `flags` (`multiple_versions`, `availability_unknown`, `quality_suspect`,
  `contradictory_evidence`, `estimated_value`) are semantic; do not drop them.
* `policy` should be available in an "about this view" panel; it explains why an answer may
  differ from a later version of Atlas.

### 2.3 Provenance (Financial X-Ray)

`EvidenceKernel.provenance(evidence_id).to_dict()`: `record`, `source`, `raw_document`,
`filing`, `transformation`, `revision_chain`, `derived_inputs`, `limitations`, `narrative`.
`narrative` is ordered prose suitable for direct display; `limitations` must be shown with
the value (not hidden behind a tooltip).

### 2.4 Market series

`split_adjust(...)` / `total_return(...)` → `AdjustedSeries.to_dict()` with `mode`,
`adjustment_status`, `bars[]` (`split_factor`, `dividend`), `actions_applied`,
`actions_withheld`, `total_return_index`, `warnings`.

Non-negotiable labelling: `mode="total_return"` produces an **index** (base 1.0), not a
price. The terminal may not label it "adjusted close".

### 2.5 Reconciliation

`reconcile_companyfacts(...).to_dict()`: `ok`, `coverage`, counts (`matched`,
`mismatched_values`, `missing_from_store`, `unexpected_in_store`, `availability_issues`,
`period_issues`, `amendment_issues`) and `findings[]` with `code`/`severity`/`concept`/
`period_end`/`accession`. Suitable for a "data health" badge.

### 2.6 Dependency / impact

`DependencyIndex.impact(evidence_id).to_dict()`:

```json
{"evidence_id": "EV-…",
 "direct": [{"computation_id": "CMP-…", "rule_id": "atlas.derived.gross_profit.v1",
             "output_evidence_id": "EV-…", "output_concept": "gross_profit",
             "inputs": [{"evidence_id": "EV-…", "role": "revenue", "concept": "revenue",
                         "value": "100", "unit": "USD"}]}],
 "transitive": [{"depth": 2, "computation_id": "CMP-…", "...": "..."}],
 "stale": [{"computation_id": "CMP-…", "stale_reasons": [{"input": "EV-…",
            "reason": "input_superseded", "superseded_by": ["EV-…"]}]}],
 "affected_outputs": ["EV-…"], "notes": ["…"]}
```

## 3. Pagination and limits

* `as_of(..., limit=, offset=)` pages over a deterministic ordering:
  `(period_end, period_start, concept, unit)`. `truncated=true` means more rows exist.
* No server-side cursor exists; a terminal rendering a large history should page with a
  bounded `limit` and show the total from `stats`.
* `provenance` and `impact` are unbounded but small by construction (a revision chain and
  its dependents). Guard against pathological chains in the UI, not in the kernel.

## 4. Errors

CLI exit codes: `0` success, `1` validation/reconciliation findings, `2` usage or domain
error. Domain errors are `AtlasError` subclasses with a stable `code` and structured
`context` (`ValidationError`, `TemporalError`, `MissingDataError`, `AmbiguousResolution`,
`UnknownEntity`, `StorageError`, `ParseError`, `NotSupportedError`, `SecPolicyError`,
`ProviderPayloadError`, `ProviderRateLimited`, `ProviderUnavailable`,
`UnsupportedActionError`, `MigrationError`).

A terminal must render `ambiguous` resolution and `incomplete` reconstruction as states,
not as errors with a retry.

## 5. What the terminal must never display

1. A pinpoint number without a path to `explain`.
2. A total-return index labelled as a price, or a split-adjusted price labelled as total
   return.
3. A fact whose availability is `unknown` inside a public-availability view.
4. "Listed since <date>" derived from `ticker_assignment.valid_from`, which is the
   observation date, not an evidenced listing date.
5. An average/consensus of contradictory evidence without the contradiction visible.
6. A derived value without its rule id.
7. A comparison across currencies without an explicit conversion the user requested.

## 6. Versioning

| Contract | Current | Change rule |
|---|---|---|
| Schema | v2 | append-only migration; never edit a released one |
| Selection policy | `atlas.select.point_in_time.v2` | new id for any semantic change |
| Derived rules | `atlas.derived.<concept>.v1` | new suffix for a changed formula |
| Dependency engine | `atlas.dependencies.v1` | bump on schema/API change |
| JSON shapes above | v1 | additive fields only; removals need a new version |

## 7. Proposed (not implemented)

* A stable HTTP/RPC layer (FastAPI or Workers) exposing §2 read models.
* Streaming subscriptions ("tell me when new evidence changes this figure").
* Cached snapshot tables for sub-10 ms widgets.
* Auth, per-user watches, and audit logging of views.

None of these exist. The terminal must not be built against them.
