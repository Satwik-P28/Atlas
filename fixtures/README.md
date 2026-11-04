# Fixtures and their provenance

Everything under `fixtures/` is either **archived real data** or **explicitly synthesised**
data. Nothing here is a hand-typed approximation of a real company's numbers, and nothing
synthetic is ever presented as observed.

## Real SEC data (public domain)

Retrieved from `data.sec.gov` on **2026-11-04** with
`User-Agent: AtlasQuant/0.1 hardening@example.com`, in accordance with SEC fair-access
policy (≤10 requests/second). The exact URL, byte size and SHA-256 of every retrieved
document are recorded in [`sec_multi_manifest.json`](sec_multi_manifest.json).

| Directory | Issuer | CIK | Filings stored | XBRL elements | Why this issuer |
|---|---|---|---|---|---|
| `sec/` | Apple Inc. | 0000320193 | 2,272 (1,001 recent + 1,271 archive) | 505 | large accelerated filer, long history, one class |
| `sec_msft/` | Microsoft Corp. | 0000789019 | 4,539 (1,002 + 2,005 + 1,532) | 578 | software, June fiscal year end |
| `sec_wmt/` | Walmart Inc. | 0000104169 | 4,440 (1,004 + 2,000 + 1,436) | 494 | retail, **January** fiscal year end |
| `sec_googl/` | Alphabet Inc. | 0001652044 | 2,726 (1,000 + 1,726) | 564 | **multi-class** issuer (GOOGL/GOOG/…) |

Each directory contains:

```
submissions_CIK<10 digits>.json       # filings.recent + issuer metadata
companyfacts_CIK<10 digits>.json      # every XBRL fact the registrant has reported
history/CIK…-submissions-00N.json     # the filings.files archives, verbatim
```

The history archives are kept verbatim because their layout differs from
`filings.recent`: the live files are a flat map of **parallel arrays at the top level**,
with no `filings` wrapper. `tests/test_history.py` asserts that layout against all four
issuers, so a parser that only understands `recent` cannot silently ingest nothing.

## Synthetic data (clearly labelled)

| Directory | Contents | Purpose |
|---|---|---|
| `sec_restatement/` | CIK 0001999999, "Atlas Synthetic Restatement Corp": one 10-Q and one 10-Q/A restating revenue 100M → 90M; an EUR-denominated observation; a shares-denominated observation under a monetary concept | exercise amendments, supersession, currency separation and unit-kind rejection deterministically |
| `market/aapl_split_bars.csv` | 8 daily bars around a 4:1 split; prices, volumes and dates are illustrative | split adjustment and total-return mathematics (hand-checked: 499.23/4 = 124.8075; (110+5)/100 = 1.15) |

The synthetic issuer's CIK is intentionally outside the real CIK space used by these
fixtures. Its values are round numbers so that an accidental real-world interpretation is
obvious.

## Regenerating

The real payloads are immutable archives; re-downloading is only necessary to extend the
set. Use a contact User-Agent, respect the rate limit, and update
`sec_multi_manifest.json` with the new hash. The synthetic fixtures are static,
hand-authored JSON (no generator script), with every value and its purpose documented in
the table above so their construction can be audited by reading them.

## What is not here

* No licensed market prices, ISINs, FIGIs or CUSIPs. Redistribution and licensing are not
  ours to grant.
* No XBRL instance documents (`.xml`) or Financial Report (`R`) files. Reconciliation
  therefore compares against `companyfacts`, which is SEC's own derived view. See
  `docs/VALIDATION.md` §Limits.
* No pre-1994 filings (EDGAR's submissions API does not provide them).
