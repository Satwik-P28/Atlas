# Atlas v0.2.0-beta.2 — corrective release notes

**Atlas: The Evidence-First Financial Research Operating System.**

Release label `v0.2.0-beta.2`, package version `0.2.0b2`, Apache-2.0. This is an **experimental
public preview** and a prerelease. It is a research system, not an investment product. Read
[known limitations](docs/KNOWN_LIMITATIONS.md) before using it for anything that matters.

## Why this release exists

`0.2.0b1` was uploaded to PyPI and then deleted. PyPI permanently prohibits reuse of a deleted
distribution filename, so the same software cannot be re-uploaded under that version. This release
republishes the identical tree as `0.2.0b2` and fixes the documentation defects found by installing
the published `0.2.0b1` wheel.

The `v0.2.0-beta.1` GitHub release, its tag and its certified assets remain published and untouched.
Its notes are preserved verbatim in
[`docs/RELEASE_NOTES_v0.2.0-beta.1.md`](docs/RELEASE_NOTES_v0.2.0-beta.1.md).

## What changed

- **Quickstart commands that did not run.** The shipped CLI takes `--db` as a *global* option, so
  `atlas init --db var/atlas.db` fails with `unrecognized arguments: --db`, and `atlas --version`
  fails because no such flag exists. Every install instruction now uses the accepted form:
  `atlas --db PATH init|doctor|migrate`, `atlas demo|serve|mcp --db-path PATH`. Corrected in README,
  both quickstarts, the user guide, the installation, troubleshooting and verification pages, the
  landing page and the release runbook. `atlas doctor --json` is documented as the way to read the
  release version.
- **Python requirement stated consistently.** One quickstart said 3.11 or 3.12; the package requires
  3.12+, and the page now says so and marks 3.11 unsupported.
- **Install instructions lead with PyPI**, `pip install "atlas-quant[terminal]==0.2.0b2"`, with the
  release wheel kept as the verified alternative.
- **Version `0.2.0b2`** (label `v0.2.0-beta.2`) in the package attribute, the web package and the
  version-consistency test; `pyproject.toml` still reads it dynamically, so there is one source.
- **`scripts/build_sbom.py` derives the component purl from `atlas.__version__`** instead of a
  hard-coded string, so an SBOM cannot name the wrong release.

## What did not change

No research capability, data, schema, migration, fixture or configuration changed. The diff between
`v0.2.0-beta.1` and this release touches version strings, documentation, the SBOM label and the CI
branch list only. Everything described in the
[v0.2.0-beta.1 notes](docs/RELEASE_NOTES_v0.2.0-beta.1.md) — point-in-time SEC evidence, evidence
certificates, the Financial-Economic Compiler, geometry-aware answer resolution, price-movement
investigation, declarative `.atlas` packages, certified revision impact, the local terminal, PDF
memos and the local MCP server — is present unchanged.

## Install

Requires **Python 3.12+**. No Node.js, no database server, no paid data provider, no API key.

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install "atlas-quant[terminal]==0.2.0b2"

atlas --db var/atlas.db init         # create and migrate the database
atlas --db var/atlas.db doctor       # schema, integrity and foreign-key checks
atlas demo --db-path var/demo.db     # offline end-to-end demonstration
atlas serve --db-path var/atlas.db --port 8000
```

`--db` must precede the subcommand; `demo`, `serve` and `mcp` also accept `--db-path`, which
overrides it. There is no `--version` flag: `atlas --db var/atlas.db doctor --json` reports
`release_version`, and `python -c "import atlas; print(atlas.__release_label__)"` prints the label.

To install the release wheel instead, download it with `SHA256SUMS` and verify before installing:

```bash
sha256sum -c SHA256SUMS              # macOS: shasum -a 256 -c SHA256SUMS
pip install "atlas_quant-0.2.0b2-py3-none-any.whl[terminal]"
```

Then open <http://127.0.0.1:8000>. The API binds to loopback and refuses a non-loopback bind unless
you explicitly acknowledge it; it has **no authentication** and must not be exposed to a network.

From a source checkout: `make install`, then `make demo`, `make focus-demo`, `make test`.

## Artifacts

Four artifacts are attached to the release: the wheel, the sdist, a CycloneDX SBOM and the sanitized
source snapshot, with `SHA256SUMS` alongside them. Sizes and SHA-256 digests are recorded in
[`artifacts/release/SHA256SUMS`](artifacts/release/SHA256SUMS), in
[`docs/RELEASE_GATES.json`](docs/RELEASE_GATES.json) and on the release page.

Checksums identify the distributed files; they are **not** signatures or attestations, and nothing
here is signed. PyPI trusted publishing identifies the workflow that uploaded the files; it does not
sign the bytes.

## Verification performed for this release

| Check | Result |
| --- | --- |
| Backend suite on the release commit | **1,362 passed, 4 skipped**, plus one environment-specific failure: on macOS with Accelerate BLAS, `np.linalg.eigvalsh` returns `6.2e-18` for a rank-3 6×6 matrix, so `test_diagonal_loading_makes_a_singular_matrix_positive_definite` sees a positive-definite matrix. That test file and `src/atlas/decision/estimators.py` are byte-identical to v0.2.0-beta.1, and it passes on the Linux hosted runner. Reported, not worked around. |
| Frontend | 64 unit tests pass, `tsc -b --noEmit` clean, production build succeeds |
| Packaged installation of the distributed wheel | clean venv: `pip install`, `init`, `doctor`, `demo`, `serve` health and the MCP handshake all pass |
| Restricted data | tree, wheel, sdist and source snapshot contain no restricted vendor material; zero of the nine exact vendor paths reachable in any ref |
| Security | SQL interpolation inventory and structure tests unchanged; dependency scan clean; no credentials in the tree |
| Hosted CI | 13/13 jobs on the certification commit — backend and audits, frontend, database integrity, research and rights integrity, clean-checkout reproducibility, the 21-step browser journey on Chromium, Firefox and WebKit, the packaged wheel on Ubuntu, Windows and macOS, and the release wheel build. Run identifier in `docs/RELEASE_GATES.json`. |
| PyPI | `0.2.0b2` published through trusted publishing, then installed from PyPI into a fresh virtualenv and exercised through the quickstart above |

Not performed, and not claimed: independent human evaluation, external usability testing, adoption
measurements, load testing beyond the bounded resource audit, and a commercial MCP client test.

## Compatibility

| Platform | Status |
| --- | --- |
| Linux x86-64, Python 3.12 | Certified: packaged install, real SEC journey, browser journey |
| Ubuntu, Windows and macOS (GitHub runners), wheel | Certified in hosted CI |
| Python 3.11 | **Not supported.** The numerical dependency publishes no 3.11 wheel |
| Firefox / WebKit | The 21-step journey passes in hosted CI; no broader browser support is claimed |
| Safari, Edge, mobile browsers | **Not tested**; responsive layout was checked at 390×844 in Chromium only |

Full detail: [platform matrix](docs/PLATFORM_MATRIX.md).

## Licence, data rights and what this release does not grant

- **Software:** Apache-2.0, `Copyright 2026 Satwik Peddireddi`. See [LICENSE](LICENSE),
  [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md).
- **Data:** the software licence does not license third-party data. SEC-derived facts, synthetic
  fixtures and public-domain government data are inventoried per path in
  [DATA_RIGHTS_INVENTORY.json](docs/DATA_RIGHTS_INVENTORY.json). No licensed vendor market data is
  bundled in any artifact.
- **Historical exposure:** the private development archive's earlier history still contains nine
  Nasdaq/Alpha Vantage files. They are absent from this release, its artifacts and its source
  snapshot. Earlier clones may still contain them, and no visibility change recalls a copy already
  downloaded. See [repository migration](docs/REPOSITORY_MIGRATION.md).

## Known limitations (the short list)

- No authentication; local single-user by design.
- No scheduler; monitoring is manual.
- Comparison covers companies already in the database, one period at a time.
- MCP is stdio-only and read-only by default; no network transport.
- Market-data onboarding is CSV only.
- The CLI has no `--version` flag; read `release_version` from `atlas doctor --json`.

Full list with impact and status: [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Research verification

```bash
# Re-verify an exported certificate against pinned source bytes
atlas verify-certificate --manifest artifacts/focus_source_manifest.json \
  --snapshots var/focus/snapshots --strict <certificate.json>

# Reproduce the offline FOCUS corpus: 13 real cases, certificates, 29 tampered certificates
make focus-corpus && make focus-manifest && make focus-demo
```

Walkthrough with expected output: [release verification](docs/RELEASE_VERIFICATION.md).

## Feedback

Beta feedback process: [docs/launch/BETA_PROGRAM.md](docs/launch/BETA_PROGRAM.md). Issues: bug report
and answer-quality templates are in `.github/ISSUE_TEMPLATE/`. Security reports follow
[SECURITY.md](SECURITY.md) — please do not open a public issue for a vulnerability.
