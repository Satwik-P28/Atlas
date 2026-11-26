# Market data, provenance and rights

Atlas does not bundle or redistribute vendor market prices. The equity service works
without them and reports their absence explicitly.

## Import contract

`atlas.research.prices.import_price_series` requires:

- a resolved ticker and security identity;
- source name and licence;
- redistribution terms (`public_domain`, `user_responsibility`, `restricted`, `private`);
- adjustment semantics, currently `unadjusted` only (adjusted series are derived views, not
  imported observations);
- retrieval timestamp, stored with every row;
- ISO dates and a positive close; malformed rows are rejected, never forward-filled.

Every import also records a stable source identity, dataset, batch content hash, security,
listing MIC, currency, licence, redistribution terms, authorization basis and collection
method. A source id is derived from that provenance, not from a shared literal such as
`user-market-data`, so two providers (or the same provider under two licences) cannot
overwrite each other's rights.

## Append-only observations

- Provider A and provider B may both report the same security/session. Both rows survive.
- Replaying identical bytes is idempotent (`written=0`, `duplicates=n`).
- A changed value for the same source/session appends a new `revision_seq` and
  `supersedes_bar`; the superseded row remains inspectable.
- A malformed row rejects the whole batch before any observation is written.
- Canonical selection is explicit and versioned (`atlas.market_price.selection.v1`): use a
  requested source id, otherwise latest session, latest ingestion, then source id. Conflicts
  and all alternatives are returned.

## Identity rules

A ticker is not a security identity. The importer resolves exactly one active ticker
assignment for the stated `as_of` date. If a ticker maps to multiple securities it rejects
the import as ambiguous; callers must supply `security_id` and `mic`. No exchange is
hard-coded, and MIC, currency and listing period are checked. Historical ticker reuse does
not move earlier observations to the new security.

## Rights semantics

- `export_allowed` is true only for `public_domain` series with an authorization basis.
- Rights are immutable for existing source records. A more permissive licence creates a new
  source; it never retroactively authorizes earlier restricted observations.
- Research packages record the selected source/session policy but state
  `price_included: false` and include no price rows.
- User-imported restricted data stays in the local database and is not redistributed.

## What becomes available

With an authorised series: latest close, price/earnings, price/book, price/sales and FCF
yield, price-versus-model comparison and reverse DCF for industrial issuers. Without one:
`status: unavailable`, zero observations and an explanation. No synthetic quote is
substituted, and no feature is presented as working when the price is absent.

## Limits

- Imported closes are observed history, not a point-in-time vendor vintage.
- Accounting period and price date are not synchronised; multiples are labelled as such.
- Trading calendars and corporate actions are recorded only to the extent the importer
  declares them.
