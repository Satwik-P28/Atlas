# Phase 9.6.2 — Final report

## 1. Hashes

* Development branch `freebuff/0139b8fdada4bab1ac65bcfa`: `2692d03` (the 9.6.2 implementation),
  preceded by `79fda10`; this report is the following commit.
* Clean release candidate `release/9.6.2-candidate`: `cf9c511e77fb8cb4e99587f3a01bf1258eec5b6e`,
  parent `486e7d0fd4b01e7c402dff1d54b463c00aefa614` (`main`). `d8ae4f1` is **not** an ancestor
  (`git merge-base --is-ancestor` exits 1). Its tree is identical to `2692d03`; the only later development change is this report.

## 2. Table-cell extraction coverage

4,255 cells across the first seven evaluation filings: 2,264 verified (53.2%). Unresolved:
unparseable 1,114, duplicate label 416, dash 372, merged period 89. Dashes are never zero and
missing cells are never zero. Footnote markers are preserved on the cell.

## 3. Verified calculations

Six hand-computed reference cases pass exactly: direct lookups (two), percentage change
(12.18%), gross margin (81.04%), ratio (2.03), component total (2000.00). Each answer records
inputs, periods, units, formula, operator version, independent recomputation and a fingerprint.

## 4. Answer correctness, coverage and abstention

* Cell localization among numeric FinanceBench questions: 1 of 7 (0.1429) — gate `>= 0.20` FAILED.
* Calculation correctness on fixtures: 6/6 (1.0).
* Abstention (balanced mixed set): precision 1.0, recall 1.0, false abstention 0.0, false
  assertion 0.0; no untouched mixed holdout exists.
* 33 of 40 sampled questions have prose or yes/no answers and are unsupported.

## 5. Original versus new methodology

9.6.0/9.6.1 measured literal answer presence in retrieved passages (`answer_presence@5` 0.1964,
failed) and remain unchanged. 9.6.2 measures document retrieval, cell localization, period
alignment, citation integrity, calculation correctness and abstention separately. It is a
different benchmark, not a retroactive pass.

## 6. Remaining unsupported question types

Multi-hop concept mapping, CAGR across missing periods, overlapping segment aggregation,
fiscal-calendar reconciliation, and questions whose answers are prose or yes/no.

## 7. Workstation persistence

Instrument binding persists (`ISS-CIK0000718877` before and after reload). The 9.6.1 failure was
a browser check that reopened the wrong desk. A saved one-panel desk is a tabs node, is accepted
by the server, and restores with its binding.

## 8. Browser certification

23/23 checks, 0 console errors, 0 failed requests, desktop and 390x844 screenshots inspected.
Link groups B/C/D are covered by serialization tests, not driven individually in the browser.

## 9. Test counts

Backend: 739 tests collected, full suite exit 0. Frontend: 50 passed. TypeScript typecheck and production build pass
(301.37 kB, 94.32 kB gzip).

## 10. Git history and rights

The development branch still contains licensed text in `d8ae4f1`. The candidate excludes it from
its ancestry but does not remove it from the development branch, GitHub retention or existing
clones. Private retention is not itself a licence violation and none is asserted; the ownership
decision on rewriting history remains open.

## 11. Release readiness and blockers

Ready as a private checkpoint: schema 15 intact, security/temporal repairs preserved, tests green,
browser certified. Blocked for promotion: cell-localization gate failed, `answer_presence@5`
remains failed, and the history/retention decision is unresolved.

## 12. Promotion

`main` was **not** promoted.

## Addendum: main branch incident

The push helper defaulted to the connected branch and briefly advanced `main` to the 9.6.2 tree
(`486e7d0..f7e90ab`), which the release policy does not authorize. No force-push was used:
`main` was restored with a forward commit (`644448d`) whose tree is exactly the Phase 9.5 tree
(`af25770`). `main` therefore carries two extra commits, but its content is Phase 9.5 again.
Promotion did not happen; the rights/history decision remains with the repository owner.
