# Phase 9.6.3 — Release decision

## Gates

| Gate | Result |
| --- | --- |
| backend suite (749 tests) | pass |
| frontend tests (50), typecheck, build | pass |
| schema/migrations (15) | unchanged, pass |
| historical evidence contracts | pass (sanitization guard green) |
| FEC arithmetic + independent verifier tests | pass |
| table geometry regression test | pass |
| concept resolution / cell localization | code present; 2/6 and 1/2 on the corpus |
| answer correctness | **failed** (0.50 vs 0.80 gate) |
| abstention | precision 0.9167 pass; 3 false assertions |
| real case studies | **0/12 answered — failed demonstration** |
| browser certification | **not re-certified** |
| master-spec integrity | pass (unchanged) |
| rights/history | **open** — `main` contains `d8ae4f1` |
| candidate ancestry | clean (parent `486e7d0`) |

## Decision

Ship nothing publicly. Keep the private checkpoint. Do not merge the candidate into `main` while
`main` still contains `d8ae4f1`: merging would carry the licensed-text commit forward as an
ancestor and would not remediate it.

## Distinction

A technically safe private checkpoint exists: tests pass, FEC now actually executes, independent
verification is real, and abstention is honest. A scientifically validated financial-answer
capability does **not** exist: the concept resolver cannot yet establish statement identity on real
filings, and no real case study reached an answer.

## Still required

1. Owner decision on history (remediation vs retention).
2. Statement-level identity (caption/heading capture) so consolidated tables are distinguishable.
3. Period-header recovery for tables like Coca-Cola's 2022 column.
4. A human-reviewed mixed abstention holdout.
5. Browser re-certification including link groups A–D.
