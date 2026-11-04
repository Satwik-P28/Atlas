# Point-in-time feature engine

## Scope

`FeatureEngine` derives typed series from stored raw daily bars. It is deliberately
separate from the financial-statement model layer: Phase 4 demonstrates price/volume
features, while statement features require filing-vintage data that this dataset does not
provide. No statement feature is advertised as available.

## Definition

```json
{"name":"sma20", "kind":"sma", "window":20, "missing":"skip"}
```

Supported kinds: `price`, `return`, `sma`, `momentum`, `volatility`, `volume_zscore`.
Inputs are the raw close/volume series; windows are session-based, not calendar-based.
Output values are Decimals with 12 decimal places.

Each snapshot records:

* `cutoff` — the last session that may contribute.
* `generation` — SHA-256 of the counted/revised bar generation at the cutoff.
* per-feature definition, observation time and computation version;
* a values fingerprint;
* an explicit `availability` note.

## Availability and leakage

* A feature value assigned to session *t* uses bars at or before *t* only. There is no
  forward fill, centered window, negative lag or implicit next-bar value.
* A strategy deciding at *t*'s close fills at *t+1*'s open. It cannot use *t+1*'s bar.
* A filing-derived value is not used at all in this release; when it is added it must be
  keyed by `available_at`, not by fiscal-period end. An archival scan that sees a filing
  before its `available_at` is ignored and its evidence is recorded as unavailable.
* Vendor vintages are not silently upgraded. Bars carry their provider and retrieval
  timestamp. Unless exact source bytes were archived, a bar proves a current vendor
  observation, not what the vendor displayed in 2005. The Time Capsule marks this
  `external_provider_only`.
* A missing bar does not produce a fabricated price. Rolling windows require a full
  window of stored observations; otherwise the feature is null and a signal that needs
  it stays flat instead of trading on an imputed value.
* Calendar gaps are not filled. Sessions are the stored trading sessions; weekends do
  not create zero-volume pseudo-bars.

## Caching

`feature_snapshot` stores the canonical definition, cutoff, computed values and hash.
Recomputation compares the definition fingerprint and the bar-generation hash; a changed
window or a changed/reingested bar invalidates it. This is a correctness artifact, not a
performance claim.

## Anti-leakage tests

`tests/test_phase4_quant.py` covers: a shorter cutoff cannot see a later bar; a future
price cannot enter a rolling mean; a decision at close cannot fill at the same close; and
source bytes are content-addressed while unarchived providers are reported as
`external_provider_only` rather than fully reproducible.

## Limitations

* No financial-statement features, cross-sectional universe features, factor exposures,
  intraday bars or macro series in this dataset.
* No vendor-vintage merge engine. Archived vendors are content-addressed objects, not a
  full bitemporal price store.
* No claim that a feature is economically meaningful; the tests prove timing and
  arithmetic, not alpha.
