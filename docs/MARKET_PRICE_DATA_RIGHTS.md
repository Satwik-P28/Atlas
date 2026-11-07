# Market price data rights

Atlas does not bundle, redistribute or infer rights for third-party market prices.

## What is tracked

`fixtures/market/` contains **only project-authored synthetic data**:

| File | What it is | Rights |
| --- | --- | --- |
| `synthetic_prices.csv` | 10 deterministic daily bars for the fictional issuer `ATLS` | Apache-2.0, project-authored |
| `synthetic_daily_bars.json` | the same values in a vendor-shaped payload, labelled synthetic | Apache-2.0, project-authored |
| `synthetic_splits.json` / `synthetic_dividends.json` | generated corporate actions for the adjustment path | Apache-2.0, project-authored |
| `aapl_split_bars.csv` | eight illustrative bars around a 4:1 split | Apache-2.0, project-authored |

`fixtures/market/manifest.json` declares `synthetic: true` and
`contains_vendor_data: false`; `fixtures/market/synthetic_manifest.json` pins the SHA-256 of
every tracked file. A test fails if either declaration drifts.

These values are never described as observed market data, never labelled `reported`, and
never substituted for a real observation. They exist so the importer, revision, session
identity, selection and adjustment paths can run in CI without redistributing anyone's
price history.

## What was removed, and why

Phase 9.2.2 removed the Nasdaq quote-history CSVs (`nasdaq_{JPM,GS,UNH,AAPL,AMZN}.csv`)
and the archived Alpha Vantage demo responses (`ibm_{daily,dividends,splits}_alphavantage.json`).
Their manifests recorded `redistribution: restricted` for the Nasdaq series and no
established grant for the Alpha Vantage responses. A private repository is not a
redistribution licence, and neither is an accessible endpoint.

The bytes remain in Git history (they were tracked before Phase 9.2.2). No published commit
was rewritten. See `docs/DATA_RIGHTS_AUDIT.md` for the remediation recommendation.

## Importing lawfully held data

```bash
python scripts/import_phase9_2_prices.py --db var/phase9.db \
  --csv /path/to/my/licensed/series.csv \
  --ticker JPM --source-name "My licensed feed" \
  --licence "Provider agreement, internal research use, no redistribution" \
  --redistribution restricted \
  --security-id SEC-... --mic XNYS --retrieved-at 2026-01-02T21:00:00Z
```

The importer refuses to infer rights: a source name and licence are required, automated
access requires an explicit authorization basis, `public_domain` requires a basis naming the
terms, and only raw/unadjusted observations may be imported.

## Export rule

Only `public_domain` redistribution is exportable. Restricted, private and
`user_responsibility` observations stay local; research packages record the selected source
and the exact observation identity with `price_included: false`, so a user with their own
entitlement can reconnect the same revision.

## Observation identity and pinning

A price is selected by a versioned policy (`atlas.market_price.selection.v2`) that names its
basis: latest market session, latest imported revision, an explicit source, or a saved pin.
Every selected observation carries:

- security, listing MIC, interval and trading session;
- provider source id, dataset name, licence, redistribution and authorization basis;
- revision sequence, supersedes link, observation and ingestion instants;
- a content hash over the observation payload and a stable `MOB-…` observation id.

A saved research object stores the pin. Reopening it replays that exact revision; importing a
later correction does not change it. Moving to the corrected revision is an explicit act that
produces a second research-object version, and both remain inspectable. If the pinned
revision is absent, Atlas reports `exact_revision_unavailable` and returns no price — it never
substitutes the latest quote.
