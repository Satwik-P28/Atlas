# Phase 10.7 — final publication status

Date: 2026-11-26. Scope: apply the authorised licence, rebuild and certify the exact distribution
artifacts, prepare the public repository and its release materials, and publish only where
authorisation and access both exist. **Feature freeze respected: no product feature, financial model,
research subsystem or optimisation was added in this phase.**

Final verdict: **PUBLICATION BLOCKED — ACTION REQUIRED.** Certification is complete; publication
requires GitHub administrative credentials this environment does not hold.

## What was executed

| Work | Result | Evidence |
| --- | --- | --- |
| Apache-2.0 applied | `LICENSE` (verbatim, 11,358 B), `NOTICE`, `THIRD_PARTY_NOTICES.md`, PEP 639 package metadata, `CITATION.cff`, applied-licence record | `licenses/AUTHORIZATION-RECORD.md`; wheel reports `License-Expression: Apache-2.0` and ships all three documents |
| Ownership check | 153/153 reachable commits authored by the maintainer; 4 agent-assisted commits for the same maintainer; no third-party contributor commits; no vendored source | `licenses/AUTHORIZATION-RECORD.md` |
| Artifacts rebuilt after the grant | wheel `0d546263…`, sdist `aa29c862…`, source snapshot `c2af8558…`, SBOM `51e7fb84…` | `artifacts/release/SHA256SUMS`, `dist/` |
| Reproducibility | wheel, sdist and source snapshot each rebuilt into a second directory: byte-identical | recorded in `artifacts/release/artifact_manifest.json` |
| Backend suite | **1,369 passed, 0 failed, 0 skipped** (180 s) | this phase, on the release commit |
| Frontend | unit tests pass, typecheck clean, production build succeeds | this phase |
| Real filing | 45/45 steps on Apple FY2026 10-K, answer 478,834, `citation_quality 'exact'` | `artifacts/release/acceptance_real_filing.json` |
| Packaged installation | clean venv: install, init, doctor, demo, serve health, MCP handshake | `artifacts/release/packaged_install.json` |
| Security | SQL inventory 49 sites reviewed; resource audit 8 pass / 0 fail / 1 not run; dependency scan clean (65 Python, npm 0) | `artifacts/release/{distribution_audit,resource_limits,dependency_scan}.json`, `docs/SECURITY_SQL_REVIEW.md` |
| Distribution audit | tree, wheel, sdist and snapshot free of restricted vendor data | `artifacts/release/distribution_audit.json` |
| Clean-history candidate | single commit `8e3da8fe6492`, 1,089 files, 1,185 objects, 0 restricted reachable, 5/5 self-checks pass | `.release/clean-history`, `docs/PROVENANCE_MAPPING.json` |
| Release materials | release notes, install instructions, compatibility matrix, known limitations, research-verification guide, handover runbook, Pages workflow, PyPI trusted-publishing workflow | `RELEASE_NOTES.md`, `docs/RELEASE_VERIFICATION.md`, `docs/PUBLIC_RELEASE_HANDOVER.md`, `.github/workflows/{pages,release}.yml` |
| Name availability | `Satwik-P28/Atlas-development` free (404); PyPI `atlas-quant` unregistered (404) | unauthenticated API reads, 2026-11-26 |
| Hosted CI on the release commit | run **`45883811438`**, 13/13 jobs green, including the Chromium, Firefox and WebKit certification journeys and the packaged wheel on Ubuntu, Windows and macOS | GitHub Actions, commit `1436489` |

## What was not executed, and why

| Step | Blocker |
| --- | --- |
| Back up, rename and privatise the development repository | Needs an authenticated GitHub owner; no `gh`, no token, no admin API in this environment |
| Create `Satwik-P28/Atlas` and push the clean candidate | Same. The candidate exists and is verified locally |
| Create and publish the `v0.2.0-beta.1` prerelease with the four assets | Same |
| Enable GitHub Pages | Same; the workflow is committed |
| Upload to PyPI | Needs a PyPI account/pending publisher and an actual upload; none exists, so no PyPI claim is made |
| Hosted CI on the public repository | The repository does not exist yet. The same pipeline ran green on the connected development repository for the release record (run `45883811438`), which is evidence about the code, not about a repository that has not been created |
| Independent human evaluation, external usability, adoption | No evaluators, no participants, nothing published. Reported as **NOT RUN** and no claim depends on them |

## Honest statements this phase will not make

- That Atlas is published, available on PyPI, or downloadable from a release page.
- That restricting a repository's visibility recalls copies already downloaded, forked or cached.
- That the artifacts are signed or attested. They are hashed; the release workflow adds PyPI build
  provenance only for the upload path, and only when it runs.
- That human validation, browser support beyond the tested journey, or byte identity across
  toolchains was established.

## Next action

Run [PUBLIC_RELEASE_HANDOVER.md](PUBLIC_RELEASE_HANDOVER.md) §1–§6 on a machine where `gh` is
authenticated as the repository owner, then record the resulting repository, release, Pages and CI
identifiers in [RELEASE_GATES.json](RELEASE_GATES.json) and this file. No further development phase
is opened by that step: it is publication of the certified artifacts, not new work.
