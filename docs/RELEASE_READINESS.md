# Release readiness — v0.2.0-beta.1

Registry decision: **READY FOR PRIVATE RELEASE CANDIDATE**.
Publication verdict: **PUBLICATION BLOCKED — ACTION REQUIRED**.

The machine-readable registry is [RELEASE_GATES.json](RELEASE_GATES.json); this page is its
human-readable form. No readiness percentage is computed: a passing gate never compensates for a
blocking one.

The certified source commit is `36c7ee8e09862dd9bcea6d1927a72650a7308937` on
`release/v0.2.0-closeout`; the release records live in `14364896ec005dbd83d68c938877ac692438b959`.
The artifacts were built from the certified commit with a clean working tree, after the Apache-2.0
grant was applied. Pre-licence artifact hashes are superseded and must not be published.

Hosted CI on the release commit: **run `45883811438`, 13/13 jobs green** — backend suite and audits,
frontend test/typecheck/build, database migration integrity, research and rights integrity,
clean-checkout reproducibility, the certification journey on Chromium, Firefox and WebKit, the
packaged wheel on Ubuntu, Windows and macOS, and the release wheel build.

## Gate-by-gate

| Gate | State | Evidence |
|---|---|---|
| Financial correctness | **PASS** | Apple FY2026 10-K: 45/45 acceptance steps, answer 478,834, cited column label `2026` equals the resolved period (`citation_quality 'exact'`), segment rows recompute to the table total, certificate independently verified. |
| Historical integrity | **PASS** | Availability precision reported honestly; modelled bounds labelled; cutoffs exclude rather than back-fill. |
| Security | **PASS** | 49 SQL interpolation sites classified and reviewed, 9 structure tests; bounded resource audit 8/8 with 1 deliberate not-run; dependency scan clean (Python 65 packages, npm 0 findings); no secrets in the tree. |
| Packaged installation | **PASS** | Distributed wheel installed into a clean venv: init, doctor, demo, serve health, MCP handshake all pass. |
| Flagship workflow | **PASS** | Full real-filing journey including memo, PDF, structured export and MCP agreement. |
| Research reproducibility | **PASS** | Second installation reproduced value, table hash and document hash exactly; 34/34 numeric claims present in the PDF. |
| Artifact integrity | **PASS** | Wheel, sdist and source snapshot rebuilt byte-identically; `sha256sum -c` passes on all four published assets; licence metadata inside the wheel. |
| Documentation accuracy | **PASS** | Measured numbers only; unrun validations named as unrun; publication itself not claimed. |
| MCP interoperability | **PASS** | Official `mcp` SDK: 14 tools, structured content, typed refusals, read-only enforcement. |
| Browser certification | **PASS** | Chromium 21/21 locally; the same journey on Chromium, Firefox and WebKit in hosted CI. |
| Performance | **PASS** | Baselines unchanged; measured 4,000-row table 0.19 s, 200k-row CSV 2.55 s, peak RSS 109 MB. |
| Data redistribution rights | **PASS** | Tree, wheel, sdist and source snapshot contain no restricted vendor data; every tracked data path has a rights entry. |
| Historical exposure remediation | **BLOCKED** | Clean-history candidate `8e3da8f` verified (1,089 files, 0 restricted objects reachable). Executing the rename, visibility change, repository creation and tag needs GitHub administrative credentials this environment does not hold. |
| Software licensing | **PASS** | Apache-2.0 applied, `Copyright 2026 Satwik Peddireddi`; LICENSE/NOTICE/THIRD_PARTY_NOTICES ship in the wheel and sdist; `License-Expression: Apache-2.0` verified. |
| Third-party notices | **PASS** | Root THIRD_PARTY_NOTICES.md covers 11 Python and 9 bundled npm dependencies, 0 missing licences; data explicitly outside the software licence. |
| Authorised publication destination | **BLOCKED** | Destination authorised (`Satwik-P28/Atlas` public, `Satwik-P28/Atlas-development` private archive), but no administrative access to execute it. |
| Independent human evaluation | **NOT RUN** | No external evaluators; no claim depends on it. |
| External usability | **NOT RUN** | Package prepared, zero participants, no fabricated results. |
| Adoption | **NOT RUN** | Nothing has been published. |
| External contributions | **NOT APPLICABLE** | No third-party contributor commits exist. |

## Why publication is blocked rather than claimed

Every engineering and licensing gate passes on the exact artifacts. What remains is five
administrative operations on the maintainer's GitHub account and one on PyPI:

1. back up the development repository;
2. rename `Satwik-P28/Atlas` → `Satwik-P28/Atlas-development` and make it private;
3. create `Satwik-P28/Atlas` and push the verified single-commit candidate;
4. create and publish the prerelease with the certified assets;
5. enable GitHub Pages for the landing page;
6. configure and run PyPI trusted publishing.

This environment has no GitHub administrative credentials (no `gh`, no token, and the git remote
helper pushes an existing branch only) and no PyPI credentials. Reporting "published" without those
operations would be false. The exact sequence, with the commands and the checks to run between them,
is in [PUBLIC_RELEASE_HANDOVER.md](PUBLIC_RELEASE_HANDOVER.md).

## What is deliberately not claimed

- Independent human validation, external usability and adoption: **not run**.
- Firefox, WebKit, Safari, Edge and mobile browsers: only the 21-step journey is exercised, on which
  Firefox and WebKit pass in hosted CI; no broader support is claimed.
- Windows and macOS real-SEC journeys: the packaged-install matrix runs there; the real filing
  journey was executed on Linux only.
- Byte identity across toolchains: reproducibility holds for the same interpreter, setuptools and
  zlib.
- Signing and attestation: the artifacts are hashed, not signed. GitHub build provenance attestation
  is prepared in the release workflow for the PyPI path, but no signature exists today.

## What changed in this publication phase

| Item | Before | Now |
|---|---|---|
| Software licence | Staged text, no `LICENSE` | Apache-2.0 applied with a named holder; licence metadata and notices inside the artifacts |
| Package metadata | No license field | PEP 639 `license` + `license-files`, author, project URLs |
| Artifact hashes | Pre-licence build (`7d3c28c7…`, `132c83d1…`) | Post-licence build (`0d546263…`, `aa29c862…`, source `c2af8558…`) |
| Dependency inventory | Generated before the licence existed | Regenerated against the release commit, 0 missing licences |
| Release materials | "private candidate, no licence" | Prerelease notes, install and verification instructions, compatibility matrix, handover runbook |
| Landing page | Static page with no publication path | Same page plus a Pages workflow and an explicit licence line |

## To move this to published

Execute [PUBLIC_RELEASE_HANDOVER.md](PUBLIC_RELEASE_HANDOVER.md) §2–§6 and record the resulting
repository URL, release URL, Pages URL and CI run identifiers here and in
[RELEASE_GATES.json](RELEASE_GATES.json).
