# Phase 10.6 status

> **Superseded by [PHASE10_7_FINAL_STATUS.md](PHASE10_7_FINAL_STATUS.md).** The maintainer authorised
> Apache-2.0 on 2026-11-26 and it is now applied; the restricted data is absent from every artifact
> and from the verified public source candidate. This file is kept as the record of what phase 10.6
> established, including the state before that authorisation. — final release execution

Feature-frozen. This phase closed the narrow blockers Phase 10.5 left open, certified one immutable
candidate, and stopped short of publication because three administrative gates need the
maintainer's explicit authorization.

## Stages

| Stage | Result |
| --- | --- |
| 1. Citation integrity | **Closed.** Period and label come from the printed header slot sequence, not a flattened header. A column the header cannot cover is `period_column_ambiguous` with no certificate; a citation whose label contradicts its period is refused with 422 `citation_period_conflict`. Apple FY2026 10-K journey 45/45 with `citation_quality: exact`, label `2026` = period `2026`. 7 adversarial tests. |
| 2. Browser certification | **Closed.** Both failures were product defects: the sticky row-label column covered every statement value in a narrow panel, and saving an unchanged memo returned 422 so the export controls never appeared. Chromium 21/21 locally. Hosted CI ran the same journey on Chromium, Firefox and WebKit; all three exited 0. |
| 3. Security closure | **Closed.** 49 SQL interpolation sites inventoried and reviewed (`docs/SECURITY_SQL_REVIEW.md`); the four identifier splices are controlled. 9 adversarial structure tests. Bounded resource audit: 8 cases pass, 1 not run (expensive model request, no provider). Dependency scan clean. |
| 4. Historical data remediation | **Candidate built.** Single-commit sanitized candidate with 0 restricted objects reachable, verified on the candidate itself (suite 1363 passed / 4 skipped, packaged install green). Original repository's exposure audited read-only (`docs/REPOSITORY_EXPOSURE_AUDIT_PHASE10_6.md`); remediation actions not executed. |
| 5. Software licence | **Blocked on authorization.** `licenses/Apache-2.0.txt` staged; no LICENSE/NOTICE applied because ownership and grant are unconfirmed. Exact maintainer action listed in the gate registry. |
| 6. Deterministic distribution | **Improved and measured.** Two builds differed only in timestamps (zip member times; sdist PAX mtime/uid; gzip header). Artifacts are now stamped at the commit time and two builds of the candidate are byte-identical. Toolchain-specific; recorded as such. |
| 7. Final certification | **One candidate certified.** Backend 1355→1366 tests green, frontend tests/typecheck/build green, migrations, offline acceptance, real-filing acceptance, browser journey, MCP SDK, security scans, resource audit, clean-history install, packaged install. Artifact hashes in `docs/RELEASE_GATES.json`. |
| 8. Launch preparation | **Verified against the candidate.** README, walkthrough, Show HN, Reddit, beta programme and landing page checked for claims; two claims corrected (browser coverage, byte reproducibility). |
| 9. Publication | **Not performed.** No authorization for the licence, the destination, or the history remediation; and the current repository still serves restricted vendor data from published history. |
| 10. Feature freeze | **In force.** The deferred list is unchanged; no Phase 11 work started. |

## Certified candidate

* Source commit: `d649fcc9d6f4173b59e574e8a25439444f21ef21`
* Wheel `7d3c28c753eee92181c5a952c33072d01ad2d7ce7373f6c0d4446ea04a7ef586`
* sdist `132c83d1a3504dc934eae2b6146857a92e5a6733287558876b7c781373abe471`
* Sanitized source `eeed9812478023ecf2c0f2dc09f6fe6279c31a27e6ec8ddbca9efcb8b5629cfd`

The registry commit that follows the candidate is metadata-only; the artifacts above were built
from the candidate commit with a clean tree and rebuilding them reproduces the same bytes.

## Decision

**READY FOR PRIVATE RELEASE CANDIDATE.** Every engineering gate passes on these exact artifacts.
Four distribution gates stay blocked, and each needs a maintainer decision rather than more code:
licence grant, publication destination, and remediating the restricted data reachable in the
published history. Until those are authorized, publishing is prohibited by the project's own
release policy.
