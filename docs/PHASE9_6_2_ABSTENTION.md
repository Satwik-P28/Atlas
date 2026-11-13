# Phase 9.6.2 — Abstention with balanced evidence

The lexical policy from 9.6.1 (`term_absence`, development precision 1.000, recall 0.625) is kept
for retrieval-level claims. The financial answer engine adds a stricter, structured policy: a
number is asserted only when every input is a verified cell at the requested period with
compatible units and a nonzero denominator.

## Mixed set

Fixture document, 5 answerable lookups and 7 hard negatives:

* metric not disclosed (`ebitda`)
* wrong year (2017, 2021 for a FY2020/FY2019 table)
* dash cell (shares outstanding)
* related but different concept (operating lease liability)
* prior period outside the table (cost of revenue 2018)
* future evidence (cutoff before the filing's availability time)

Result: precision 1.0, recall 1.0, false abstention 0.0, false assertion 0.0.

## Why this is not enough

The positives and negatives come from one fixture document; no untouched mixed holdout was
established. The 9.6.1 negative-only holdout (8/8) measured unanswerable recall only. Therefore
these figures demonstrate that the structured policy behaves as specified on the constructed set,
not that it generalises to arbitrary filings. This limitation is recorded in the artifact rather
than tuned away.
