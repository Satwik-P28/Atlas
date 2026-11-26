# Repository exposure audit (Phase 10.6, read-only)

Scope: what the **existing** `Satwik-P28/Atlas` repository exposes today, and what a clean-history
distribution candidate can and cannot remedy. Nothing here was changed: no branch was deleted, no
history was rewritten and the repository's visibility was not altered.

Observed on 2026-11-25 through the GitHub REST API (`/repos`, `/branches`, `/tags`, `/forks`,
`/pulls`) and `scripts/audit_distribution.py` run against the local clone.

| Fact | Value |
| --- | --- |
| Visibility | public (`private: false`) |
| Fork of another repository | no |
| Forks / network | 0 / 0 |
| Tags / releases | none |
| Default branch | `main` |
| Branches | 24, listed below |
| Pull requests | 8, all open, none merged; every PR head branch is also in the branch list |

Branches: `main`, `release/v0.2.0-closeout`, `release/v0.2.0-beta.1`,
`release/v0.2.0-beta.1-final`, `release/9.6.2-candidate`, `release/9.6.3-candidate`,
`release/9.6.4-candidate`, `integration/phase10.3`, `data/open-data-bootstrap`,
`docs/atlas-v3-2-research-price-intelligence`, `focus/answer-semantics`,
`focus/application-ready`, `focus/financial-answer-hardening-v1`, `focus/integration`,
`holdout/answer-semantics-prospective`, `research/real-world-revision-study`,
`review/decision-intelligence-cri`, `review/price-intelligence-v3.2`,
`review/price-intelligence-v3.2-integrity`, `review/price-intelligence-v3.2-temporal`,
`cursor/focus-priority0-827f`, `freebuff/0139b8fdada4bab1ac65bcfa`,
`freebuff/3365f99c8c30f951eb55234b`, `freebuff/41a4fd2abe41a6515dc8d5bb`.

## Restricted material reachable in history

`scripts/audit_distribution.py` walks every object reachable from every ref in the clone and
reports nine vendor market-data files that the project's own policy classifies as restricted
(Nasdaq historical series and Alpha Vantage split data), introduced by commits `6920d0a5`,
`d0e45405` and others. They are present in:

* every branch that shares the mainline history — that is, all 24 branches above;
* the pull-request head refs `refs/pull/1`–`refs/pull/8`, which GitHub serves from the same
  objects;
* any clone or archive taken from the repository, including the caches GitHub keeps for
  `refs/pull/*` until the PRs are removed.

They are **not** present in the working tree, the built wheel, the sdist or the sanitized
single-commit candidate (`restricted reachable: 0`).

The vendor terms under which the fixtures were obtained do not permit redistribution. The nine
files are small numerical series, but that does not change the classification.

## What a clean-history candidate does and does not fix

Fixes:

* the public distribution repository can be published with zero restricted objects reachable —
  verified by rebuilding the archive and re-walking every object of the candidate;
* the wheel, sdist and sanitized source archive contain no restricted material;
* research verification that depends on the public gold data still runs (see
  `docs/RELEASE_GATES.json` and the candidate suite results).

Does not fix:

* history that already exists in this repository, including PR refs, clones, forks (none today),
  and any copies already downloaded by third parties. **Restricting visibility does not recall
  copies that were already obtained**, and deleting branches does not remove objects that GitHub
  still keeps reachable through pull requests or cached views.
* Anything an external party has already indexed or mirrored.

## Recommended remediation (requires maintainer authorization)

1. Keep this repository as the restricted development archive (visibility change is an
   administrative action, not performed here).
2. Publish the clean-history candidate as a **new** repository; it shares no objects with this
   one, so this repository's history is not reachable from it.
3. Once the new repository serves the release, this repository's default branch can be reset to
   a sanitized tree, with its old history retained privately under lawful retention.
4. Optionally ask GitHub support to purge cached views after the PRs are closed; closing PRs does
   not by itself delete the objects.

Each of these is an administrative action on the maintainer's account. None was executed.
