# Data providers

What Atlas can ingest, what it stores, what it may redistribute, and what is not implemented. Rights are
per source; public accessibility is never treated as permission to redistribute.

## Implemented today

| Provider | Adapter | Transport | Stores | Redistribution | Requires |
|---|---|---|---|---|---|
| SEC EDGAR submissions and company facts | `atlas.ingestion.sec_client`, `sec_submissions`, `sec_companyfacts` | HTTPS JSON | derived facts, accessions, URLs, digests | derived facts and identifiers only | `ATLAS_SEC_USER_AGENT`, network |
| SEC filing primary documents | `sec_sync`, Financial Knowledge Engine | HTTPS HTML | archived bytes (local), extracted units | local retention; excerpts follow document rights | `ATLAS_SEC_USER_AGENT`, network |
| User-imported CSV market bars | `atlas.ingestion.market_csv` | local file | bars with provider, licence and redistribution class | whatever you declare and are entitled to | a CSV file |
| User-imported Parquet bars | same, `columnar` extra | local file | as above | as above | `pyarrow` |
| Alpha Vantage JSON/CSV (optional adapter) | `atlas.ingestion.market_alphavantage` | local file or API | as configured | **not permitted** for vendor data; local analysis only | your own key/terms |
| Committed demonstration fixtures | `fixtures/` | repository | synthetic series + derived public facts | see the source-rights inventory | nothing |

Every ingestion path records provider, retrieval time, availability semantics and a redistribution
class. A source whose class does not permit packaging cannot be packaged into a `.atlas` file; the
refusal is a rights decision, not a bug.

## Not implemented

These are named because they are commonly assumed to exist:

- **FRED / ALFRED**: an offline research study over a stored vintage series exists under
  `scripts/research/`, but there is no production FRED/ALFRED adapter, no release calendar and no
  scheduler.
- **Treasury, EIA, NOAA**: committed derived fixtures exist (public-domain government data). There is no
  live ingestion client.
- **FFIEC / FDIC**: regulatory fixtures are committed and used by the institutional models; there is no
  live download client.
- **Commercial market data, consensus estimates, transcripts, news**: not present, not licensed, not
  claimed. Retrieval surfaces report `unavailable` with the reason rather than substituting synthetic
  values.

## Importing your own data

```bash
atlas bars import --ticker AAPL --file my-bars.csv \
  --source-name "My Provider" --licence "Personal analysis" --redistribution local_only
atlas bars show --ticker AAPL
atlas bars validate --ticker AAPL
```

The redistribution class you declare decides whether results derived from that data can be exported or
packaged. Choose it honestly: `local_only` for licensed data you may analyse but not redistribute,
`project_authored` for series you generated.

## Data health

`atlas doctor` reports database-level health (integrity, schema, counts). Per-source freshness and
coverage are visible in the terminal's data views and in the `coverage` blocks of research results, which
name which evidence classes were available, which were absent, and why. There is no single unified data
health dashboard in this release; treat `atlas doctor`, the API's coverage blocks and the rights
inventory as the three sources of truth.

## Point-in-time semantics

- An observed availability instant is used as-is.
- A date-only filing is pinned to the end of that UTC day, never its first second, and the report says so.
- EDGAR acceptance plus a modelled publication lag is an **upper bound**, recorded with precision
  `unknown` and the model name, reported as `modeled_bound`. Intraday claims built on it are refused;
  session-level claims disclose the bound.
- Vendor price vintages are not available, so a historical price reconstruction is reported as
  `unverified` at the cutoff rather than claimed to be what the vendor had published.
