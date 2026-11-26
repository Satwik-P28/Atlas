# Phase 10.5 — release closure and launch preparation

Branch `release/v0.2.0-closeout`, based on `release/v0.2.0-beta.1-final` at
`f98220c5320e98feb05a3b23a68fed8d2d2682d7` (hosted CI run `45508943066`, all 10 jobs green).

This phase was closure work: no new financial models, no new agents, no unrelated infrastructure.
What follows is what was done, what was measured, and what is still blocked on the maintainer.

## 1. Distribution remediation

| Question | Answer |
| --- | --- |
| Restricted objects still reachable? | **Yes**, in history: nine vendor market-data files (`fixtures/market/nasdaq_*.csv`, `ibm_*_alphavantage.json`, `alphavantage_manifest.json`). They are not in the current tree — the sanitized snapshot of `HEAD` excludes **zero** paths. |
| Are they in the artifacts? | No. The wheel, sdist and sanitized source contain none of them. |
| Clean-history candidate built? | Yes: `scripts/build_clean_history_candidate.py` produced `.release/clean-history`, a single-commit repository of 1,023 files, verified with `git rev-list --objects --all` to contain no restricted path. |
| Provenance? | `docs/PROVENANCE_MAPPING.json` maps the release commit, its date, the archive hash, the sanitized commit and tree, and every excluded blob. |
| Exposure remediated in the original repository? | **No.** That needs an authorised rewrite or a visibility change. Exact commands, consequences and verification steps are in `docs/REPOSITORY_MIGRATION.md`. |

A fresh-history repository does not fix exposure in the original; the migration document says so in
its first section rather than implying otherwise.

## 2. Licensing

Staged, not applied: `licenses/Apache-2.0.txt` (verbatim, hash recorded), `licenses/NOTICE`,
`licenses/PENDING-AUTHORIZATION.md`, `docs/THIRD_PARTY_ATTRIBUTION.md`, `docs/DATA_LICENSING.md`,
and a machine-readable `docs/DEPENDENCY_LICENSES.json` covering 11 Python dependencies, 9 bundled
npm packages and 200 development-only npm packages, all with declared licences.

There is still **no `LICENSE` at the repository root**, deliberately. Apache-2.0 would cover Atlas's
own code only; it grants no right over SEC filings as documents, vendor market data, or any
dependency.

## 3. Real-world flagship demonstration

`scripts/accept_real_filing_phase10_5.py` — Apple Inc. (CIK 0000320193), the 10-K for the fiscal year
ended 2026-09-26, accession `0000320193-26-000026`, fetched live from SEC Archives with a configured
contact identity (`ATLAS_SEC_USER_AGENT`). The filing is fetched into a temporary directory and is
never committed.

**45 of 45 steps pass**, including:

- company selection through the palette, statement inspection over synced XBRL facts;
- the real 10-K parsed into **60 tables / 728 text units**, 1.65 MB, 0.2 s from local bytes;
- total net sales FY2026 = **478,834**, cited to one cell of one table;
- an independent arithmetic recomputation from the parsed unit: the segment rows (254,098 + 37,929 +
  27,929 + 35,577 + 123,301) sum to the table's own total;
- certificate verification, availability labelled `precision=unknown, estimated=true`;
- a DCF valuation (241.59 per share) and a scenario (WACC 9% → 11%: 241.59 → 181.24);
- a **justified refusal**: comparing the real issuer with the synthetic demonstration issuer is
  refused with `insufficient_coverage` / `partial_coverage`;
- memo saved, PDF exported (75,953 bytes, 19,687 extractable characters, manifest hash matches),
  44 claims in the structured export with 34/34 numeric figures present in the PDF text;
- MCP returning the same 478,834 as the HTTP certificate;
- **reproduction on a second installation**: identical value, source-table hash
  `5fc5edb8…` and document hash.

Two findings came out of this run and were fixed or exposed:

1. **Ambiguous column label.** Apple's statements place `$` in its own column, so the flattened
   header for a 2026 value reads "2025". The value and the resolved period were right; the label was
   not. The API now returns `column_label_agrees_with_period` and
   `citation_quality: ambiguous_column_label` instead of asserting the label.
2. **Gross margin cannot be recomputed from one unit** in this filing (it spans two tables), so the
   acceptance recomputes an in-table identity instead of pretending a cross-table check happened.

## 4. MCP interoperability

`tests/test_mcp_sdk_interop.py` uses the **official `mcp` Python SDK** (2.3.0, installed as a test
client only; the test skips cleanly when it is absent):

- initialize and protocol negotiation (`2024-11-05`), server info `atlas 0.2.0b1`;
- discovery of all **14 tools** with schemas;
- a typed call returning structured content with the full source-cell citation (`cell_id`, `unit_id`,
  `table_id`, `document_id`, `accession`, `row_label`, `column_label`, `raw`, `value`) and a
  reproducibility fingerprint;
- an unknown tool and an invalid enum surface as JSON-RPC errors listing the permitted values;
- a valid concept with no evidence returns a typed `not_found` result, not an exception and not a
  invented answer;
- read-only mode refuses `save_research_object` with `authorization_required`;
- clean shutdown when the client closes the session.

No commercial MCP client was tested, and none is claimed.

## 5. Browser certification

`web/e2e/phase10_5_certification.mjs` drives the release build through the workflows that matter:
shell, answer resolution, certificate build and independent verification, certificate download,
refusal state, comparison, data onboarding, command palette (focus, unknown-symbol refusal, Escape
restores focus), evidence inspection, keyboard focus rings, memo PDF export, and 1440×900 / 390×844
viewports without horizontal overflow.

| Engine | Result | Notes |
| --- | --- | --- |
| Chromium 156 (headless shell) | **19 pass, 2 fail** | Two steps (evidence-panel selector, equity memo start) could not locate their controls in this harness; the same flows are certified through the API acceptance. |
| Firefox | **NOT RUN** | The container has no root and lacks the GTK/Pango stack Firefox needs; Playwright refuses to launch it. |
| WebKit | **NOT RUN** | Same environment limitation. |

Screenshots from the release build are committed under `docs/launch/screenshots/`.

Two real defects were found and fixed by this stage:

1. **The Answers page went blank after "Build certificate."** `build()` stored the certificate
   response in the resolution state, and the next render read `resolution.question.issuer_id` from an
   object that has no `question`. The flagship certificate path was unusable in a browser before this
   fix; no API test could have caught it.
2. **The answer headline rendered `21690.00 [object Object]`**, because the unit is an object
   (`{kind, scale}`) that was interpolated as a string.

## 6. Performance

Phase 10.4 demo-workload measurements are preserved unchanged in
`artifacts/release/performance_phase10_4.json` (palette 6.5/8.3 ms p50/p95; statements 182/212 ms;
certificate 9.8/23.7 ms; comparison 7.8/13.6 ms; DCF 22.0/51.0 ms; PDF 19.1/32.8 ms; MCP 5.5/14.4 ms;
startup 1.09 s).

New measurements from this phase: a 1.65 MB real 10-K parses in 0.2 s into 60 tables and 728 units;
`atlas sec sync --no-history` for Apple completes in about 15 s including network; a full real-filing
journey (sync, parse, answer, certificate, valuation, memo, PDF, MCP) takes about two minutes.

No optimisation was attempted: no bottleneck that changes a user-facing interaction was demonstrated.
Peak memory was not instrumented, and no larger-filing campaign was run — both are recorded as
limitations rather than estimated.

## 7. Security

See `docs/SECURITY_AUDIT_PHASE10_5.md`. Summary: 22 host-header/CORS/rebinding tests pass; 0 secret
patterns in the tree or the wheel; dependency scan clean as recorded in the licence inventory;
archive extraction rejects absolute and traversing members; SQL values are parameterised with 45
identifier-interpolation sites noted for review; MCP mutations are refused in read-only mode.
Resource exhaustion under sustained load is **NOT RUN**. There is still no public deployment of the
API, and there must not be one: it is unauthenticated by design.

## 8. Launch materials

`docs/launch/`: static landing page (`index.html`, no server dependency), architecture diagram
(`ARCHITECTURE.svg`), sixty-second demo script, five-minute technical walkthrough, Show HN draft,
Reddit drafts, technical article draft, and the invitation-preview package (`BETA_PROGRAM.md`).
Also `docs/QUICKSTART.md`, `CONTRIBUTING.md` and three issue templates.

No claim of Bloomberg equivalence, institutional readiness, guaranteed performance or
hallucination-free research appears in any of them.

## 9. Installation

`scripts/verify_packaged_install.py` installs the built wheel into a clean environment, initialises a
database, runs the offline demo, exports an artifact and starts the MCP server. Hosted CI additionally
runs the packaged wheel on Ubuntu, Windows and macOS (run `45508943066`). The exact artifacts
distributed are the ones built from the final commit of this branch; hashes are in
`artifacts/release/SHA256SUMS`.

## 10. External validation

The invitation-preview package exists; **no participants have been recruited and no results exist**.
Independent human evaluation, external usability, adoption and external contributions are all
**NOT RUN**. Existing research findings remain labelled development/post-holdout results.

## 11. Final artifacts and gates

Platform coverage, artifact by artifact and engine by engine, is in
[`PLATFORM_MATRIX.md`](PLATFORM_MATRIX.md). A blank cell there is a configuration that was not run.

See `docs/RELEASE_GATES.json` for the machine-readable registry and `artifacts/release/` for the
wheel, sdist, sanitized source, checksums, SBOM, provenance and licence inventory.

- candidate commit `432290a6d02b2a92f244e41a6ea4c3e16ab346c0`
- wheel `atlas_quant-0.2.0b1-py3-none-any.whl` — 1,427,777 bytes, sha256 `d36a56b4d6bc328f82f6b4e5d0d3da5619d8e07304f44e1c7cf997fcf001fa18`
- sdist `atlas_quant-0.2.0b1.tar.gz` — 1,550,786 bytes, sha256 `9d7cbd02d82f667f3fe69c8c01475adf6c41ade100c4990f55bc8e8c3211d74e`
- sanitized source — 33,844,536 bytes, sha256 `0dbeaba5dfadc780dacac3270ca90320f1356805ec1d6820fc55992945c2dd05`
- SBOM `artifacts/release/sbom.cdx.json` (20 components), checksums in `artifacts/release/SHA256SUMS`; checksums are not signatures. Two builds of identical source produced different wheel bytes, so the checksum identifies the distribution rather than the commit alone.

## Features deferred (no release-blocking defect needs them)

Sentinel background scheduler, additional valuation models, cross-period comparison expansion, cloud
hosting, multi-user authentication, additional retrieval architectures, advanced compression, global
OSINT intelligence, automated trading, an application marketplace, and large-scale data expansion.
