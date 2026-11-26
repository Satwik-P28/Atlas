# Phase 9.6.3 — Repository history audit

Audited locally against the remote heads supplied with the phase brief and against the branch refs
in this workspace.

## Verified references

| Ref | Commit | Note |
| --- | --- | --- |
| `main` | `644448d` | tree `af25770` = the Phase 9.5 tree |
| development | `4cd3427` | Phase 9.6.2 tip |
| candidate | `cf9c511` | parent `486e7d0` |
| baseline | `486e7d0` | last clean predecessor |

## Correction to the Phase 9.6.2 report

The 9.6.2 report said `main` carried "two extra commits". That was wrong. `git rev-list --count
486e7d0..main` is **7**, and `git merge-base --is-ancestor d8ae4f1 main` **succeeds**. `main`
contains, in order: `d8ae4f1`, `efb79c9`, `6863024`, `79fda10`, `2692d03`, `f7e90ab`, `644448d`.

The tree was restored, but the history was not. Restoring a tree does not remove an ancestor.

## Consequences

* Merging `release/9.6.2-candidate` into `main` would **not** remove the licensed-text commit: it
  is already an ancestor of `main`.
* Only a rewrite of `main`, or an explicit retention decision by the owner, resolves it.
* The candidate remains clean (`cf9c511` has only `486e7d0` as parent).

## Working-tree compliance versus history

Working tree: compliant — artifacts are sanitized and the contract test
`test_committed_artifacts_contain_no_prohibited_fields` passes.
History: non-compliant until rewritten or retained by decision.
GitHub objects and existing clones: out of reach of any local operation; only the owner can decide.
