# Phase 9.6.3 — Table geometry and provenance

## The 9.6.2 taxonomy was measuring the corpus

Sampling real filings showed that most "unparseable" cells came from tables of contents and
executive-bio tables, not financial statements. Tables are now classified as `financial`,
`non_financial` or `unknown` from caption/section signals, navigation labels ("ITEM 1"…, "Present
Position") and numeric density.

Across the documents referenced by the evaluation:

| Kind | Tables | Cells | Verified |
| --- | --- | --- | --- |
| financial | 1,221 | 43,144 | 28,693 (66.5%) |
| non_financial | 62 | 2,980 | 1,609 |
| unknown | 1,867 | 4,420 | 1,037 |

All-table verified rate is 0.62; the financial-only rate is **0.6651**.

## Geometry repair

SEC tables place `$` in its own column and leave spacer columns between periods. Reading those as
data shifted every header and made values unparseable. `extract_cells` now:

1. drops columns that are empty or symbol-only across the body,
2. right-aligns header periods onto the remaining value columns,
3. keeps the **original** column index on every emitted cell.

Regression test: a Coca-Cola-style row (`Net Operating Revenues | $ | 43,004 | | $ | 38,655`)
yields 2022 = 43,004 and 2021 = 38,655 with original columns 2 and 5, scale 6.

## Known limitation

One Coca-Cola header still leaves the 2022 column without a period while 2021/2020 resolve
(`Net Operating Revenues 43,004` has `period=None`). This is recorded, not papered over; it is
why the Coca-Cola revenue case study abstains.
