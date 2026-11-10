# Promotion of the verified Atlas development history to `main`

Date: 2026-11-10. Repository `Satwik-P28/Atlas` (private).

## 1. State before promotion

| Ref | Commit |
| --- | --- |
| Local development HEAD | `b453956a0c25611174bb2fb1d6dbd7690a553e3c` |
| Remote development `freebuff/41a4fd2abe41a6515dc8d5bb` | `b453956a0c25611174bb2fb1d6dbd7690a553e3c` (phase start `1826926f…`) |
| Remote `main` | `44a12dcb5f472aa5b1e1cfc3b4ebcc37d50d5889` |
| Merge base | `44a12dcb5f472aa5b1e1cfc3b4ebcc37d50d5889` |

`git merge-base --is-ancestor 44a12dcb… HEAD` succeeded, so `main` was an ancestor of the
development branch: 29 commits ahead at the phase start, 0 behind. No divergence existed to
reconcile.

## 2. Method

Fast-forward only. No force, no lease override, no history rewrite, no orphan branch, no
squash or cherry-pick, no subset selection:

```
git push origin HEAD:refs/heads/main
   44a12dc..b453956  HEAD -> main
```

The push was accepted on the first attempt, which also establishes that this repository's
`main` had no protection rule blocking a fast-forward from the verified branch at that moment.
If it had been protected, the fallback would have been a pull request, not a bypass.

## 3. What the promotion contains

Every commit from the verified development line, including Phases 1–9, the Phase 9.2 market
and evidence corrections, the market-series contract and bulk projection, the v3.0.0 master
specification, the 61 section requirements, ICB-01…ICB-48, and the Phase 9.3 claim
verification, memo, export and change-detection work with its tests and documentation.

## 4. Data-rights position

The repository is private and stays private. Earlier commits contain restricted vendor market
bytes; a fast-forward carries that history to `main` unchanged, which is acceptable only while
the repository keeps its current private visibility and access policy. Promotion does **not**
authorise making the repository public, and no public release was published. Research packages
and memo exports remain governed by their own rights decisions: the reference database refuses
export because the imported price source is `user_responsibility`.

## 5. Verification after promotion

* `origin/main` was fetched and compared with the development branch.
* Commit ancestry: `main` contains the complete development history, not a squashed copy.
* The master specification, the memo modules, the frontend changes, the tests and the
  documentation are present on `main`.
* The specification integrity script and the financial reproduction were re-run from `main`.

The exact final hashes of `origin/main` and `origin/freebuff/41a4fd2abe41a6515dc8d5bb` and the
verification output are recorded in the phase report and in the repository's remote refs; both
branches were verified equal after the final documentation commit.
