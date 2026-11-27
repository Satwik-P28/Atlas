# Release readiness — v0.2.0-beta.2

Registry decision: **READY FOR EXPERIMENTAL PUBLIC PREVIEW**.
Publication verdict: **PUBLIC RELEASE PUBLISHED — PRERELEASE, EXPERIMENTAL**.

The machine-readable registry is [RELEASE_GATES.json](RELEASE_GATES.json); this page is its
human-readable form. No readiness percentage is computed: a passing gate never compensates for a
blocking one.

This is a corrective release. `0.2.0b1` was uploaded to PyPI and then deleted, and PyPI permanently
prohibits reuse of those distribution filenames, so the same tree ships again as `0.2.0b2` with a
corrected version number and corrected CLI documentation. The v0.2.0-beta.1 GitHub release and its
certified assets remain published and untouched; its notes are preserved in
[RELEASE_NOTES_v0.2.0-beta.1.md](RELEASE_NOTES_v0.2.0-beta.1.md).

The artifacts are built from the release candidate commit recorded in
`docs/RELEASE_GATES.json` (`artifacts` note). The certification commit that follows is metadata
only: it changes `docs/` and `artifacts/release/`, neither of which is inside the wheel or the sdist.

## Gate-by-gate

| Gate | State | Evidence |
|---|---|---|
| Financial correctness | **PASS** | Apple FY2026 10-K: 45/45 acceptance steps, answer 478,834, cited column label `2026` equals the resolved period (`citation_quality 'exact'`), segment rows recompute to the table total, certificate independently verified. Unchanged from v0.2.0-beta.1. |
| Historical integrity | **PASS** | Availability precision reported honestly; modelled bounds labelled; cutoffs exclude rather than back-fill. |
| Security | **PASS** | 49 SQL interpolation sites classified and reviewed, 9 structure tests; bounded resource audit 8/8 with 1 deliberate not-run; dependency scan clean; no secrets in the tree. |
| Packaged installation | **PASS** | `scripts/verify_packaged_install.py` installs the distributed wheel into a clean venv and runs init, doctor, demo, serve health and the MCP handshake. Re-run for this release. |
| Flagship workflow | **PASS** | Full real-filing journey including memo, PDF, structured export and MCP agreement. |
| Research reproducibility | **PASS** | Second installation reproduced value, table hash and document hash exactly; 34/34 numeric claims present in the PDF. |
| Artifact integrity | **PASS** | Wheel, sdist, SBOM and source snapshot hashed and recorded; `sha256sum -c` passes on the published assets; licence metadata inside the wheel. |
| Documentation accuracy | **PASS** | The two CLI defects found by installing the published beta.1 wheel are fixed and the version is consistent everywhere; measured numbers only, and unrun validations are named as unrun. |
| MCP interoperability | **PASS** | Official `mcp` SDK: 14 tools, structured content, typed refusals, read-only enforcement. |
| Browser certification | **PASS** | 21-step certification journey on Chromium, Firefox and WebKit in hosted CI on the release candidate. |
| Performance | **PASS** | Baselines unchanged; measured 4,000-row table 0.19 s, 200k-row CSV 2.55 s, peak RSS 109 MB. |
| Data redistribution rights | **PASS** | Tree, wheel, sdist and source snapshot contain no restricted vendor data; every tracked data path has a rights entry. |
| Historical exposure remediation | **PASS** | The development repository is private and renamed `Satwik-P28/Atlas-development`; the public repository is a sanitized history with zero restricted objects reachable. Residual exposure is recorded, not claimed away. |
| Software licensing | **PASS** | Apache-2.0 applied, `Copyright 2026 Satwik Peddireddi`; LICENSE/NOTICE/THIRD_PARTY_NOTICES ship in the wheel and sdist; `License-Expression: Apache-2.0` verified. |
| Third-party notices | **PASS** | Root THIRD_PARTY_NOTICES.md covers 11 Python and 9 bundled npm dependencies, 0 missing licences; data explicitly outside the software licence. |
| Authorised publication destination | **PASS** | `Satwik-P28/Atlas` public with Pages enabled; `Satwik-P28/Atlas-development` private archive; prerelease published with certified assets; PyPI trusted publishing used for the PyPI upload. |
| Independent human evaluation | **NOT RUN** | No external evaluators; no claim depends on it. |
| External usability | **NOT RUN** | Package prepared, zero participants, no fabricated results. |
| Adoption | **NOT RUN** | Published days ago; no adoption measurement exists. |
| External contributions | **NOT APPLICABLE** | No third-party contributor commits exist. |

## Publication record

| Item | Value |
|---|---|
| Repository | <https://github.com/Satwik-P28/Atlas> |
| Release | <https://github.com/Satwik-P28/Atlas/releases/tag/v0.2.0-beta.2> |
| Landing page | <https://satwik-p28.github.io/Atlas/> |
| PyPI | <https://pypi.org/project/atlas-quant/0.2.0b2/> (trusted-publishing run `45957861894`) |
| Previous release (preserved) | <https://github.com/Satwik-P28/Atlas/releases/tag/v0.2.0-beta.1> |
| Private archive | `Satwik-P28/Atlas-development` (private) |

CI run identifiers, commit hashes and artifact hashes are in [RELEASE_GATES.json](RELEASE_GATES.json).

## What is deliberately not claimed

- Independent human validation, external usability and adoption: **not run**.
- Firefox, WebKit, Safari, Edge and mobile browsers: only the 21-step journey is exercised, on which
  Firefox and WebKit pass in hosted CI; no broader support is claimed.
- Windows and macOS real-SEC journeys: the packaged-install matrix runs there; the real filing
  journey was executed on Linux only.
- Byte identity across toolchains: reproducibility holds for the same interpreter, setuptools and
  zlib.
- Signing and attestation: the artifacts are hashed, not signed. PyPI trusted publishing identifies
  the GitHub workflow that uploaded the files; it does not sign the bytes.

## Known defects still open

- The shipped CLI has no `--version` flag. This is documented rather than added, because this
  release changes no functionality; the release version is available from `/api/health`, `pip show
  atlas-quant` and `atlas.__release_label__`.
- `docs/KNOWN_LIMITATIONS.md` lists the research and interface limitations that remain.
