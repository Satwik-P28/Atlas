# Financial Data Fabric v2

Status: **implemented over the Phase 1 immutable-bar kernel.** Phase 6 does not replace the
evidence or security master. It adds a dataset view that makes source identity, rights,
coverage, timing and defects inspectable before a model is trained.

## Layering

```
source registry → immutable bar → dataset view → feature panel → experiment
```

The source registry remains authoritative for licence and redistribution. `bar` remains
authoritative for the observation, its exchange timestamp, ingestion time and source. The
learning dataset is derived: it does not silently rewrite a bar, fill a missing session, or
convert raw prices into total-return prices.

`src/atlas/learning/data.py` implements:

* `catalog(db)` — only datasets that actually contain bars, never an aspirational list.
* `load_panel(db, dataset=…)` — intersected security/session panel, explicit coverage and
  quality findings.
* `panel_from_series(...)` — deterministic synthetic fixtures for adversarial tests.
* `validate_panel(panel)` — rejects malformed or misaligned panels before feature work.

The canonical dataset id is `<source_id>:all`, for example `eodhd-demo:all`.

## Time semantics

| Field | Meaning in Phase 6 |
|---|---|
| `ts_utc` | Exchange/session observation time stored on the bar. Daily demo bars use 21:00 UTC. |
| `observed_at` / provider retrieval | When Atlas obtained the record. The demo constructor records one retrieval timestamp. |
| `available_at` on feature rows | End of the feature session, `{date}T23:59:59Z`; explicitly not the target outcome date. |
| `target_date` | Next aligned session whose close determines the label. |
| `data_class` | `observed`, `historically_reconstructed`, `point_in_time_verified`, `synthetic` or `hypothetical`. |
| `historical_vintage` | States whether a displayed-vintage archive exists. The Phase 6 demo has none. |

**What is not claimed:** the phase does not reconstruct historical publication timestamps
from a modern bulk download, and it does not store a revision/correction version for each
vendor row. Those remain prerequisites for `point_in_time_verified`.

## Real demo panel

The local demonstration was built by `scripts/build_phase6_db.py` from EODHD's documented
demo entitlement. The five symbols that resolved were AAPL, MSFT, TSLA, VTI and AMZN.

| Property | Observed value |
|---|---|
| Window | 2023-01-03 → 2025-12-31 |
| Securities | 5 |
| Daily bars | 3,760 |
| Aligned sessions | 752 |
| Expected weekdays | 782 |
| Missing weekdays | 30 |
| Quality errors | 0 |
| Quality warnings | 1 (`missing_session`) |
| Price convention | Raw close, post-split window; dividends excluded |
| Panel SHA-256 | `a092e1f6df56bc9775c2b22c14a037c14462f4b6c11345dce143121c7ec0d69c` |

The 30 absent weekdays are exchange holidays, not invented observations. The database and
vendor cache live under `var/` and are not committed or redistributed.

## Data quality checks

`load_panel` reports the checks it can support from stored bars:

* duplicate security/session observations;
* nonpositive prices;
* impossible OHLC relationships (`high < max(open, close)` or `low > min(open, close)`);
* negative volume;
* missing expected weekdays;
* insufficient security overlap;
* a window that begins before a known split without an adjustment contract.

The demo window intentionally begins after the last split in the sample. This avoids
silently splicing a split discontinuity into a raw-price feature. Dividends are excluded;
no total-return claim is made.

Checks that require external reference data — cross-provider discrepancy, delisting returns,
security identity changes and historical universe membership — are listed as limitations,
not fabricated results. Survivorship bias is not measured because the five-symbol demo is
selected by current availability.

## Coverage contract

`GET /api/learning/dataset?dataset=eodhd-demo:all` returns:

* `data_class`, `rights`, `licence`, `point_in_time_verified`;
* securities, sessions, first/last date, expected weekdays and missing weekdays;
* adjustment and historical-vintage conventions;
* quality findings and the list of checks performed;
* provider catalogue and limitations;
* the panel content hash.

The UI shows the rights and the “Not point-in-time verified” badge before training. It does
not call the five names a market universe.

## Synthetic fixtures

Synthetic panels are still first-class for deterministic tests. They carry
`data_class = synthetic`, are labelled that way in API responses, and are never mixed into
the real demo panel. Synthetic fixtures test formulas, timing and failure handling; they are
not evidence of market predictive skill.

## Boundaries

* No licensed full-market feed.
* No historical index membership or delisting return series.
* No correction/vintage store for vendor rows.
* No automatic adjustment inference. A raw panel stays raw.
* No claim that a successful five-security experiment generalizes to the market.
