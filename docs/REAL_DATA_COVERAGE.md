# Real-data coverage

## Universe

20 large US issuers, chosen before any result was computed: AAPL, MSFT, GOOGL, AMZN, META,
NVDA, IBM, JPM, GS, JNJ, PFE, UNH, XOM, CVX, CAT, DE, KO, PEP, WMT, COST.

| Measure | Value |
| --- | ---: |
| Issuers | 20 |
| SEC filings retained | 489 |
| Evidence records | 26,296 |
| Financial coverage valid | 16 |
| Valuation eligible | 17 |
| DCF executes | 17 |
| Passes independent arithmetic audit | 17 |
| Rejected as financial institutions | 3 |
| Market observations | 0 |

## What is retained

- All annual (`10-K`) observations in the archived companyfacts payloads from 2018 onward.
- Recent sub-annual (`10-Q`) observations for the latest periods.
- The filing metadata needed to date each fact's availability.
- The real accessions, source concepts, units and payload hashes.

## What is intentionally absent

- Pre-2018 archives: the compact fixture is a research sample, not a complete SEC history.
- Full raw payloads: the fixture is trimmed to the mapped concepts; the manifest records the
  source URL and hash of the original download.
- Market prices, consensus estimates, guidance, transcripts and news. No synthetic quote is
  substituted. Market cap, P/E and market-implied reverse DCF are therefore unavailable.
- Qualitative business descriptions.

## Issuers that are not fully covered

- **Amazon, Coca-Cola, Walmart, Goldman Sachs** — the archived `companyfacts` payload does
  not tag `us-gaap:Liabilities`. Statement coverage is reported incomplete. Amazon,
  Coca-Cola and Walmart still satisfy the DCF's own input set; Goldman Sachs does not,
  because it is also a financial institution.
- **JPMorgan (6021), Goldman Sachs (6211), UnitedHealth (6324)** — financial institutions.
  The DCF is refused; no bank or insurer valuation model is implemented.
- **Goldman Sachs** additionally has no mapped revenue element in this archive, so even a
  permitted model would lack a revenue base.

## Identity

Ticker assignment is provisional for issuers whose SEC submissions list several instruments
without a share-class mapping. The coverage manifest declares one primary ticker per issuer
and the service records that provenance; it is not presented as an SEC-confirmed class map.

## Licence

SEC EDGAR facts are public-domain US government records. The fixture stores derived facts
and source identifiers, not a redistribution of a licensed market database.
