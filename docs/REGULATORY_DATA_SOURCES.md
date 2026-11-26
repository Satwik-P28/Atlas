# Regulatory data sources

| Source | Dataset | Entity | Rights | Status |
| --- | --- | --- | --- | --- |
| FDIC BankFind | `banks/financials` | insured bank by certificate | public domain | ingested |
| SEC EDGAR | company facts / filings | consolidated registrant | public domain | existing |
| FFIEC Call Report bulk | not ingested | — | public domain | not implemented |
| Federal Reserve FR Y-9C | not ingested | holding company | public domain | not implemented |
| CMS MLR / plan data | not ingested | plan / issuer | public | not implemented |

Only sources that support the audited bank model were connected. Connector count is not a
quality measure.

## Observation contract

Every stored field keeps legal entity, FDIC certificate, form, dataset, field definition,
unit (USD thousands or percent), period end, retrieval time, source URL, revision and
consolidation basis. FDIC revision history is not archived, so no point-in-time regulatory
vintage is claimed.
