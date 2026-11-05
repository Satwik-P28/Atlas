# Historical availability and evidence classes

Atlas keeps two questions separate:

1. **What value was observed?**
2. **When could a researcher have known it?**

Phase 6 enforces the second question for features and labels. It does **not** claim that the
five-symbol market panel is a point-in-time historical vintage.

## Evidence classes

| Class | Meaning | Phase 6 example |
|---|---|---|
| `observed` | A real value from an identifiable source, without a verified historical display vintage | EODHD demo daily closes retrieved now |
| `historically_reconstructed` | Historical values with documented adjustments and known limitations | A raw split-window reconstruction; not used as a verified vintage |
| `point_in_time_verified` | Source records with defensible publication/availability evidence | Not achieved for vendor OHLCV in Phase 6 |
| `synthetic` | Deterministic generated test/scenario data | Phase 6 unit fixtures |
| `hypothetical` | User assumptions or modeled scenarios | Hypothetical bond terms in Phase 5 |

These labels are returned by the dataset and carried into forecast documents. They must not
be shortened to “real” in a way that erases the distinction between observed and verified.

## Feature and label timing

For session `t`:

* every selected feature uses closes/volumes at or before `t`;
* `available_at` is the end of `t`;
* the target is the `t → t+1` return;
* `target_date` is the next session;
* the target is not available at `t`, even though a row contains both fields.

The implementation records both `date` and `target_date`. Tests assert `date < target_date`
for every row. Chronological splits are formed from dates, with a two-session embargo.

## Why the demo is not point-in-time verified

The EODHD demo request returns the provider's current historical values. It does not return
what the provider displayed on 2023-06-15. Therefore:

* a split or dividend change after the historical date can alter a modern download;
* a correction can alter a previously displayed value;
* the current five symbols are selected by present-day availability;
* the dataset has no delisted names or historical index membership.

The source is still useful: the prices are real vendor observations, the sessions are real,
and formulas can be tested. It is not sufficient for a claim about what a trader could have
known at the time.

## Availability contract in the API

`GET /api/learning/dataset` returns:

```json
{
  "data_class": "observed",
  "point_in_time_verified": false,
  "coverage": {
    "start": "2023-01-03",
    "end": "2025-12-31",
    "adjustment": "raw close; corporate actions are not interpolated",
    "historical_vintage": "provider retrieval only; no displayed-vintage archive"
  }
}
```

The auditor adds a `data_vintage` warning whenever the class is not
`point_in_time_verified`. The Learning Lab displays the status without hiding it behind an
“advanced” toggle.

## Revisions and corrections

The canonical `bar` table remains immutable, but Phase 6 does not have a vendor correction
feed. A provider revision therefore has these possible outcomes:

* a new local ingestion with a different source row is visible in a new panel hash;
* an old run's stored hash no longer matches a newly built panel;
* the system does **not** automatically rewrite old runs or claim they used the new value.

This is a limitation, not a point-in-time implementation. A future correction store must
retain both the old and new observation, the provider publication time and the retrieval
time, and mark which model versions used which vintage.

## User-imported data

A CSV/Parquet import must declare:

* source and licence;
* observation date and timezone;
* whether values are raw, split-adjusted or total-return;
* whether the file is a historical vintage or a current reconstruction;
* any missing-session convention.

The importer records the declaration. It does not infer a publication timestamp from a file
modification time.

## Gate status

| Requirement | Status |
|---|---|
| Features use only information through `t` | Implemented and tested |
| Labels carry a later outcome date | Implemented and tested |
| Calibration uses validation, not test | Implemented |
| Dataset distinguishes observed/synthetic | Implemented |
| Historical display vintage | **Not implemented** |
| Corrections/vintages retained | **Not implemented** |
| Delisting/survivorship coverage | **Not implemented** |

The honest summary is: **timing-safe features, not a point-in-time market archive.**
