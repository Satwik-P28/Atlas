<!-- Preserved record of the v0.2.0-beta.1 release notes. The GitHub release and its
     certified assets remain published at releases/tag/v0.2.0-beta.1; its PyPI files were
     deleted by the maintainer and PyPI does not permit those filenames to be reused. -->

# Atlas v0.2.0-beta.1 — release notes

**Atlas: The Evidence-First Financial Research Operating System.**

Release label `v0.2.0-beta.1`, package version `0.2.0b1`, Apache-2.0. This is an **experimental
public preview** and a prerelease. It is a research system, not an investment product. It does not
claim institutional trading performance, parity with a commercial data terminal, or hallucination-free
answers. Read [known limitations](docs/KNOWN_LIMITATIONS.md) before using it for anything that
matters.

## What this release is

One integrated tree for the Atlas research system, plus the engineering that makes it installable and
auditable:

- point-in-time SEC evidence with explicit availability semantics (unknown / date / exact, and
  modelled bounds labelled as bounds);
- evidence certificates with four verification levels and typed refusals;
- a Financial-Economic Compiler with an independent exact-arithmetic verifier;
- geometry-aware financial answer resolution: statement scope, per-row column alignment, closed
  vocabulary concepts and definitional ambiguity, with refusals instead of guesses;
- price-movement investigation with publication-time integrity;
- declarative research application packages (`.atlas`) that never execute package code;
- certified revision impact for convex decision programs (experimental, clearly labelled);
- a local research terminal shipped inside the wheel, with answer certificates, a command palette,
  a cross-company comparison workspace that refuses incompatible figures, and guided market-data
  onboarding;
- PDF research reports rendered from the same memo object as the Markdown, HTML and JSON exports;
- a standards-compliant local MCP server (stdio, 14 tools, read-only by default).

## Install

Requires **Python 3.12+**. No Node.js, no database server, no paid data provider, no API key.

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install "atlas_quant-0.2.0b1-py3-none-any.whl[terminal]"

atlas init --db var/atlas.db         # create and migrate the database
atlas doctor --db var/atlas.db       # schema, integrity and foreign-key checks
atlas demo --db-path var/demo.db     # offline end-to-end demonstration
atlas serve --db var/atlas.db --port 8000
```

Then open <http://127.0.0.1:8000>. The API binds to loopback and refuses a non-loopback bind unless
you explicitly acknowledge it; it has **no authentication** and must not be exposed to a network.

Verify the download before installing:

```bash
sha256sum -c SHA256SUMS              # macOS: shasum -a 256 -c SHA256SUMS
```

From a source checkout: `make install`, then `make demo`, `make focus-demo`, `make test`.

## Release artifacts and hashes

Built from the release commit with a clean tree. Checksums identify the distributed files; they are
not signatures or attestations, and nothing here is signed.

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| `atlas_quant-0.2.0b1-py3-none-any.whl` | 1,436,906 | `0d546263fc66288b1d3d5adc9ac9a6d6d332073f52df32910429deb10e917dac` |
| `atlas_quant-0.2.0b1.tar.gz` | 1,543,875 | `aa29c862ffc731a4cf7b447874396617c48b568f544bfb4f58fe58b066564fe8` |
| `sbom.cdx.json` (CycloneDX) | 8,087 | `b27d7c6cb9138ccb11b702565894915d9a79346bfd918df02aa1a8049dd5c892` |
| `atlas-source-HEAD-sanitized.tar.gz` (source snapshot, no vendor data) | 33,900,611 | `c2af8558e1ba35a8a9d9e2fd92ce37cf6af7ee88a17bf871c85580795853b186` |

Two builds of this commit produce byte-identical wheel, sdist and source snapshot with the same
interpreter, setuptools and zlib. A different toolchain may produce different bytes; that is a
recorded caveat, not a claim of universal reproducibility.

## Verification performed for this release

| Check | Result |
| --- | --- |
| Backend suite on the release commit | **1,369 passed, 0 failed, 0 skipped** (180 s) |
| Frontend | unit tests pass, `tsc -b --noEmit` clean, production build succeeds |
| Real filing (Apple FY2026 10-K, accession 0000320193-26-000026) | **45/45 acceptance steps** — selection, live sync, ingestion (60 tables, 728 units), answer `478,834` million, exact cell citation with matching period label, independent certificate verification, availability contract, valuation, scenario, justified comparison refusal, memo, PDF (34/34 numeric claims present), structured export, MCP agreement, and reproduction on a second installation |
| Packaged installation of the distributed wheel | clean venv: `pip install`, `init`, `doctor`, `demo`, `serve` health, MCP handshake — all pass |
| Artifact reproducibility | wheel, sdist and sanitized source snapshot rebuilt byte-identically |
| Security | 49 SQL interpolation sites classified and reviewed; 9 structure-safety tests; bounded resource audit 8/8 pass with 1 deliberate not-run (expensive model request, no provider); dependency scan clean (65 Python packages, npm audit 0 findings); no credentials in the tree |
| Licence in the artifact | `License-Expression: Apache-2.0`, with `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` inside `dist-info/licenses/` |
| Distribution audit | current tree, wheel, sdist and source snapshot contain **no** restricted vendor data; the public source candidate is a single commit with zero restricted objects reachable |
| Hosted CI | run **`45883811438`**: 13/13 jobs green — backend and audits, frontend, database integrity, research/rights integrity, clean-checkout reproducibility, packaged wheel on Ubuntu/Windows/macOS, and the 21-step browser journey on Chromium, Firefox and WebKit |

Not performed, and not claimed: independent human evaluation, external usability testing, adoption
measurements, load testing beyond the bounded resource audit, and a commercial MCP client test.

## Research results carried forward

| Corpus | Baseline resolver | Geometry-aware resolver | False confident answers |
| --- | --- | --- | --- |
| Development corpus (22 questions) | 20/22 | 22/22 | 0 in both arms |
| Post-holdout development cohort (47 questions) | 36/47 | 41/47 | 0 in both arms |

The 47-question cohort was used for a first scoring run and is therefore **post-holdout development**,
not a fresh independent holdout. Frozen first-run results are preserved unchanged; corrections are
append-only adjudications with a sensitivity table. See
[the hardening report](docs/FINANCIAL_ANSWER_HARDENING.md) and
[the holdout report](docs/ANSWER_SEMANTICS_HOLDOUT_REPORT.md).

## Compatibility

| Platform | Status |
| --- | --- |
| Linux x86-64, Python 3.12 | Certified: packaged install, real SEC journey, browser journey |
| Ubuntu (GitHub runner), wheel | Certified in hosted CI |
| Windows (GitHub runner), wheel | Certified in hosted CI (this is why `tzdata` is a declared dependency) |
| macOS (GitHub runner), wheel | Certified in hosted CI |
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
- **Historical exposure:** the development repository's earlier history contained nine Nasdaq/Alpha
  Vantage files. They are absent from this release, from its artifacts and from the public source
  snapshot. Earlier clones of the development repository may still contain them, and no visibility
  change recalls a copy already downloaded. See
  [repository migration](docs/REPOSITORY_MIGRATION.md).

## Known limitations (the short list)

- No authentication; local single-user by design.
- No scheduler; monitoring is manual.
- Comparison covers companies already in the database, one period at a time.
- MCP is stdio-only and read-only by default; no network transport.
- Market-data onboarding is CSV only.
- Remaining answer defects are disclosed abstentions, resolution failures and one citation mismatch;
  none produces a wrong number.

Full list with impact and status: [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Research verification

Every claim in a result can be re-checked without trusting the interface that produced it:

```bash
# Re-verify an exported certificate against pinned source bytes
atlas verify-certificate --manifest artifacts/focus_source_manifest.json \
  --snapshots var/focus/snapshots --strict <certificate.json>

# Reproduce the offline FOCUS corpus: 13 real cases, certificates, 29 tampered certificates
make focus-corpus && make focus-manifest && make focus-demo

# Re-run the answer-semantics report against committed fixtures
make semantics-report
```

The walkthrough with expected output is
[research verification instructions](docs/RELEASE_VERIFICATION.md). The acceptance harness that
produced the 45-step real-filing result is
[`scripts/accept_real_filing_phase10_5.py`](scripts/accept_real_filing_phase10_5.py).

## Feedback

Beta feedback process (what to report, what not to send, and how results are recorded without
editing history): [docs/launch/BETA_PROGRAM.md](docs/launch/BETA_PROGRAM.md). Issues:
bug report and answer-quality templates are in `.github/ISSUE_TEMPLATE/`. Security reports follow
[SECURITY.md](SECURITY.md) — please do not open a public issue for a vulnerability.
