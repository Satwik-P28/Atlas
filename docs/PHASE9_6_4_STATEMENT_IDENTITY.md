# Phase 9.6.4 — Statement Identity

## Method

Section paths stop at `Item 8`/`Item 15`, which cannot distinguish consolidated from parent,
segment or note tables. The engine now reads the document text in the table's own block and up to
four preceding blocks, accepts only short non-sentence lines, and classifies them into explicit
families: `balance_sheet`, `income`, `cash_flow`, `equity`, `segment`, each with entity scope
`consolidated`, `parent`, `segment` or `unknown`.

`average`, `supplemental`, `selected financial data` and `fair value` schedules are deliberately
classified `unknown`: an average-balance note is not the balance sheet.

## Effect

- Coca-Cola: "CONSOLIDATED STATEMENTS OF INCOME" is recovered two blocks before the table, giving
  `income/consolidated` and scale `6`.
- JPMorgan: the "Consolidated average balance sheets" note no longer supplies total assets; the
  year-end balance sheet row `3,665,743` is selected instead of the note's `3,853,540`.
- 3M: the income statement titled "Consolidated Statement of Income" is recognised despite the
  singular title and despite a section path that mentions segments.

## Uncertain context

If no statement title can be established, family and scope stay `unknown`; the resolver then falls
back to section-path hints and may abstain rather than guess.
