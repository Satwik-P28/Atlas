# Phase 9.6.1 — Release Decision

## Decision: **not promoted to `main`**

`main` remains at `486e7d0`. All repairs are preserved on
`freebuff/0139b8fdada4bab1ac65bcfa`.

## Gate results

| Gate | Result |
| --- | --- |
| Master-spec integrity | pass (333,547 bytes, `d1800cfe…31a1111`) |
| Schema migration 015 | pass (fresh install and upgrade paths tested) |
| Full backend suite | pass (0 failures) |
| Knowledge regression suite | pass (24 tests) |
| New temporal / security / contract tests | pass (21 tests) |
| FinanceBench evaluation v9.6.1 | runs; **3 gates fail** (answer presence, abstention, none for citation/leak) |
| Citation integrity / rights tests | pass |
| Frontend unit tests / typecheck / build | pass / pass / pass |
| Advanced browser journey | **19/20** — instrument-binding restore fails |
| Git artifact exposure audit | **fail** — licensed text remains in history `d8ae4f1` |
| Clean-checkout reproduction | pass for evaluation (needs `requirements-learning.lock`) |

## Blockers

1. **Benchmark data exposure in history.** `HEAD` is clean and enforced by test, but commit
   `d8ae4f1` still contains 112 FinanceBench question/answer pairs. Release policy requires an
   authorised history rewrite or an explicit owner decision; neither exists. No force-push was
   performed.
2. **Answer construction.** `answer_presence@5 = 0.1964` against a preregistered 0.40. Atlas finds
   the filing 97% of the time and the stated value 20–24% of the time.
3. **Abstention recall.** 0.625 on the development negatives, 1.000 on the untouched negative
   holdout, against a preregistered 0.70 development threshold. Not retrofitted.
4. **Advanced workstation.** Instrument binding is not restored on a reopened desk; one panel
   layout edge case cannot be saved.

## What improved

* Licensed text removed from tracked artifacts; a test now blocks regressions.
* `@5` gates can no longer be satisfied by `@10` values; content-based fingerprint replaces
  id-only hashing.
* Availability is modelled honestly (`unknown` + model + null public instant) and the boundary
  second is inclusive after fixing a string-comparison bug.
* The Phase 6 "dependency drift" claim was disproved: the learning extra was missing. Suite green.
* Query size is bounded; corrupted passages cannot verify claims.
* The Advanced panel is exercised end to end for the first time: issuer binding, cutoffs, exact
  spans, issuer switching, save, restore, mobile layout, console cleanliness.

## What did not change

Phase 9.6.0's failed gates remain failed, with their scores unchanged in the sanitized artifact.
No threshold was relaxed and no evaluation was recomputed under a looser definition to manufacture
a pass.

## Path to promotion

1. Authorised history rewrite removing licensed text from `d8ae4f1` (or a documented owner
   decision to retain it privately), then re-push.
2. Table-cell localisation so printed values can be retrieved, and a bounded arithmetic adapter
   with unit/period/sign preservation — then re-run the answer-presence gate.
3. Calibrated abstention with a balanced, human-reviewed development set.
4. Fix desk binding persistence and the single-panel layout invariant, then reach 20/20.
