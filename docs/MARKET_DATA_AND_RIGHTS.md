# Market data, provenance and rights

Atlas does not bundle or redistribute vendor market prices. The equity service works
without them and reports their absence explicitly.

## Import contract

`atlas.research.prices.import_price_series` requires:

- a resolved ticker and security identity;
- source name and licence;
- redistribution terms (`public_domain`, `user_responsibility`, `restricted`, `private`);
- adjustment semantics (`unadjusted`, `split_adjusted`, `total_return`) per series or row;
- retrieval timestamp, stored with every row;
- ISO dates and a positive close; malformed rows are rejected, never forward-filled.

Re-importing the same security/date replaces the observation instead of duplicating it.

## Rights semantics

- `export_allowed` is true only for `public_domain` series.
- Research packages state `price_included: false` and include no price rows.
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
