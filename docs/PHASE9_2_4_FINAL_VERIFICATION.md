# Phase 9.2.4 — verified CI, browser acceptance and beta readiness

Starting commit: `62331e7c430c26ae4fed82184cead543bd053ba0` on
`freebuff/41a4fd2abe41a6515dc8d5bb`. The final commit of this checkpoint is the commit that
introduces this document; its SHA is reported with the push.

This checkpoint adds no financial model, asset class or subsystem. It makes the existing
platform reproducible from a clean checkout, proves it in a real browser, and states
plainly which gates still cannot be observed from this environment.

## 1. Baseline verified before any change

| Check | Result |
| --- | --- |
| HEAD / branch / remote | `62331e7`, `freebuff/41a4fd2abe41a6515dc8d5bb`, `Satwik-P28/Atlas` |
| Working tree | clean |
| Backend suite | 494 tests, `pytest -q` exit 0 |
| Frontend | 4 unit tests, typecheck, production build pass |
| Phase 9.2 audit | 29/29, `status: pass` |
| Phase 9.1 audit | 16/16, `status: pass` |
| Database schema | 13 |
| Reproduction | `differences={}`, `value_per_share=295.4643539226478` |

These matched the reported baseline. Nothing was assumed from the previous report.

## 2. The clean-runner dependency defect

Both integrity jobs installed a dependency set that cannot import the code under test:

* `database-integrity` ran `pip install -e '.[dev]'`;
* `research-integrity` ran `pip install -e '.[dev,terminal]'`.

`atlas.economic.model` imports NumPy at module scope, and `atlas.applications.service`
imports that model, so every path from the research and migration tests reaches it. NumPy
was declared only in the optional `learning` extra, which neither job installs. The two
jobs therefore failed during collection, not during a test:

```
src/atlas/economic/model.py:15: in <module>
    import numpy as np
E   ModuleNotFoundError: No module named 'numpy'
```

Reproduced from clean virtual environments with only the declared extras:

| Environment | Install | Result before the fix |
| --- | --- | --- |
| `/tmp/venv-dev` | `.[dev]` | collection error, exit 2 (`test_phase9_2_migrations.py`) |
| `/tmp/venv-term` | `.[dev,terminal]` | collection error, exit 2 (`test_phase9_2_institutions.py`, `test_phase9_1_models.py`) |
| `/tmp/venv-term` | `.[dev,terminal]` | `scripts/reproduce_phase9_2.py` exit 1, same `ModuleNotFoundError` |

**Correction.** NumPy is now a core runtime dependency in `pyproject.toml`, because a core
module imports it unconditionally; leaving it optional would describe the package
inaccurately and keep the clean-install path broken. It is removed from the `learning` extra
so it is declared once. `scipy`, `scikit-learn` and `pyarrow` remain optional and are
imported lazily.

The same two clean environments were reinstalled with only their declared extras:

| Environment | Gate | Result after the fix |
| --- | --- | --- |
| `.[dev]` | migrations + storage + packaging contract | pass, exit 0 |
| `.[dev,terminal]` | seven research/market/rights test files + packaging contract | pass, exit 0 |
| `.[dev,terminal]` | `scripts/reproduce_phase9_2.py` | `differences={}`, `value_per_share=295.4643539226478`, exit 0 |

`tests/test_packaging_contract.py` now prevents a recurrence: it parses `pyproject.toml`,
scans every `src/atlas` module for imports executed at module load, and fails when a package
that loads eagerly is not declared in the installation set that needs it. It also asserts
NumPy is declared once, in core.

## 3. GitHub Actions: what was observed, and what was not

The workflow was inspected and corrected, but **no workflow run was observed**. This is a
limitation of the environment, not a pass:

* the repository is private; an unauthenticated `GET /repos/Satwik-P28/Atlas/actions/runs`
  returns `403`, and `gh auth status` reports no logged-in host;
* the only GitHub credential available in this chat is scoped to `git fetch`/`git push` for
  the checkout, and exposes no Actions API, run log or artifact;
* therefore no run URL, job conclusion, duration or artifact listing is claimed anywhere in
  this document.

What can be stated without fabricating: the workflow file parses, every command it runs was
executed locally with the same arguments (see §8), and the dependency defect it would have
hit is fixed and demonstrated in §2. The next authorised step is to read the run for the
pushed SHA on GitHub and compare it with §8.

## 4. Browser acceptance — executed, not asserted

Both journeys ran against a production build served by `python -m atlas.cli serve` on a
freshly provisioned `var/phase9.db`, at `1440x1100` and `390x844`.

The sandbox has no root, so Chromium's shared libraries and a fontconfig file were
extracted into a user-writable sysroot (`/tmp/sysroot`, `FONTCONFIG_FILE=/tmp/fonts.conf`)
and the browser was launched with `LD_LIBRARY_PATH` pointing at it. That is a property of
this VM; the CI runner installs the same libraries with
`npx playwright install --with-deps chromium`.

First real execution exposed three defects that no static check had caught:

1. **Synthetic data was labelled as reported.** `import_price_series` registered every
   source as `market_data`, so `_source_status` classified the project-authored `ATLS`
   series as `reported` — a synthetic fixture presented as observed market data. The source
   kind is now derived from the collection method (`synthetic` for `synthetic_fixture`).
2. **An unavailable market comparison dropped its schema.** The unavailable branch of
   `market_analysis` omitted `accounting_period_end` and `price`, so a caller could not
   distinguish "no comparison happened" from a truncated payload, and the journey's
   accounting-period assertion had silently become untestable. Both fields are now present
   and explicitly `null`.
3. **Observation prices were strings, replay prices were numbers.** The browse endpoint
   serialised `close` with `canonical_decimal` while replay returned a JSON number, so an
   exact-replay comparison failed on type alone. The browse endpoint now returns a number;
   the canonical decimal text still feeds the content hash.

Two journey defects were also found and repaired without weakening an assertion: the mobile
step sampled the pin button before the panel's observation had loaded (now waits for the
action itself), and the research-object save was not idempotent against the content-addressed
store (now reopens the named existing version instead of failing on the duplicate).

### Scenario A — real JPM evidence without a bundled price

Assertions recorded in `artifacts/phase9_2_jpm_browser.json`:

| # | Verified |
| --- | --- |
| A1 | JPM legal identity, CIK 0000019617, top-tier RSSD 1039502, FR Y-9C `BHCK2170` 4.00T and `BHCAP793` 15.68%, FDIC certificate 628, consolidated vs subsidiary scope |
| A2 | No authorised price exists: the card reads "No observed price matches this issuer", `valuation.market.status === 'unavailable'`, `price === null`, `accounting_period_end === null`, and `289.91` appears nowhere |
| A3 | Residual-income value reproduced in the UI against the API: 295.4600 baseline, 287.9200 at 17% ROE / 9.5% CoE; report SHA-256 `63c8237fd0ec419de01eb91d92e970dfbd0e796aa27e1e9ab45440ac5a82d147` |
| A4 | FCFF rejected for a bank (`unsupported_methodology`), cutoff preserved |
| A5 | `URO-APP-71bf04aac955` saved and reopened at 287.9200 with cutoff, ROE and CoE intact |
| A6 | `.atlas` package downloaded (`equity-research.atlas`) |
| A7 | Eight research routes render with non-empty content |
| A8 | 390x844: no document overflow, no clipped values, regulatory tables horizontally reachable |

### Scenario B — synthetic ATLS provenance

Assertions recorded in `artifacts/phase9_2_market_browser.json`:

| # | Verified |
| --- | --- |
| B1 | `ATLS` present, `data_status === 'synthetic'`, banner denies exchange provenance |
| B2 | Observation `MOB-356738f0eb64cd6ecce8b2d4` with a recomputable SHA-256, `project_authored` rights, export allowed, raw adjustment |
| B3 | Browser identity equals the API identity; list and detail revision agree |
| B4 | Exact pin replay; a tampered pin returns `exact_revision_unavailable` with `price: null` |
| B5 | Pin, copy, revision history, provider comparison and in-panel replay work |
| B6 | `URO-DAT-c4d5f8ce4844` saved and reopened carrying the pin; replay still exact |
| B7 | 390x844 provenance panel fits, no clipped content, document width 390 |

Screenshots: `artifacts/phase9_2_jpm_desktop.png`, `phase9_2_jpm_saved.png`,
`phase9_2_jpm_mobile.png`, `phase9_2_market_desktop.png`, `phase9_2_market_mobile.png`.

The only HTTP error either journey tolerates is a documented data gap: `/api/economic/panel`
returns 422 because the reference database carries no economic observations.

## 5. Master specification — still blocked

`ATLAS_MASTER_SPEC.md` is **not present** in the checkout and no attachment is reachable from
this environment. `python scripts/verify_master_spec.py` exits 1:

```
BLOCKED: ATLAS_MASTER_SPEC.md is not present; expected 155419 bytes,
sha256 e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9
```

No file was regenerated from the prompt, and the declared size and checksum were not used to
manufacture content. `docs/MASTER_SPEC_TRACEABILITY.md` therefore records the blocked status
and inventories only what this repository actually verifies; it does not claim spec
conformance.

## 6. Independent integrity review

Scope: evidence identity, financial arithmetic, archive handling, API validation, rights and
reproducibility. Findings that changed code:

* **Decompression bomb in the SEC transport (fixed).** `gzip.decompress`/`zlib.decompress`
  expanded the entire stream before `_MAX_BODY_BYTES` was applied, so a small compressed
  response could exhaust memory before the size check ran. `_inflate` now deflates with an
  explicit output budget and raises `ProviderPayloadError` as soon as the limit is crossed.
  Seven regression tests cover gzip/deflate round-trips, identity bodies, over-limit
  rejection for both codecs, exact-limit acceptance and corrupt streams
  (`tests/test_sec_transport_limits.py`).
* **Synthetic source mislabelling (fixed, §4).** This was a rights/provenance defect, not a
  display defect: the read model would have shown a project-authored fixture as reported
  market data.
* **Archive import.** `read_package` rejects traversal components, absolute and Windows
  paths, symlinks, directory entries, encrypted entries, duplicate names, disallowed
  suffixes, executable keys, undeclared files and a manifest that disagrees with the
  archive; it caps entries, per-file size, total uncompressed size and package size.
  `unpack_to_directory` re-checks that every resolved path stays under the destination.
  These behaviours are covered by `tests/test_phase8_applications.py`
  (`test_path_traversal_tampering_and_forbidden_file_types_are_rejected`) and the package
  contract tests; no new defect was found, so no new test was invented.
* **Rights.** Package validation refuses a non-redistributable source snapshot and an
  application whose rights do not permit packaging; `rights.classify` fails closed for an
  unknown grant. Unchanged and still covered by `tests/test_phase9_2_3_acceptance.py` and
  `tests/test_phase9_2_2_data_rights_fixtures.py`.
* **Reproducibility.** The reference package and the clean-install package reproduce exactly
  (§7, §8); no saved program semantics were modified.

## 7. Reproduction and audit results

| Gate | Result |
| --- | --- |
| Phase 9.2 independent audit | 29/29, `status: pass` |
| Phase 9.1 independent audit | 16/16, `status: pass` |
| `scripts/reproduce_phase9_2.py` | exit 0, `differences={}`, `value_per_share=295.4643539226478`, package `3bbaca5447ffbd3421dce48fb833fccbd16a2977fa875e15498aae7bc4d1cfe8` |
| `scripts/verify_distributable_fixtures.py --require-demo-db` | `status: pass`, `exact_replay: true`, demo series `project_authored`, `10,580` rows |
| `scripts/verify_clean_install.py --demo-db var/atlas.db` | `status: pass`, `reproduced: true`, `differences={}`, `value_per_share=101.21579153430544`, package `38ed19e701a2f6e871133ab0c5b29f56e32a5e71ee45b27e75ac5fa316316644` |
| Backend suite | 507 tests, exit 0 |
| Frontend unit tests / typecheck / build | pass |

## 8. Clean-install rehearsal

Commands, from a checkout with no developer databases (all generated paths are ignored):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,terminal]'
cd web && npm ci && npm run build && cd ..
python scripts/build_terminal_db.py --db var/atlas.db --force
python scripts/verify_distributable_fixtures.py --require-demo-db
python scripts/verify_clean_install.py --demo-db var/atlas.db
python -m atlas.cli --db var/atlas.db serve --port 3000
```

The rehearsal installs the backend and frontend, initialises schema 13, loads only
committed fixtures, starts the terminal, values a real SEC-backed issuer (`AAPL`, no bundled
price), saves and reopens the research application, exports a package, installs it into a
second temporary database, reproduces the result exactly, and inspects the synthetic
`ATLS` provenance without presenting it as real data. No network and no private data are
required. No undocumented development state is needed for any step.

## 9. Beta readiness

Outcome: **closed technical beta**, not a public beta candidate.

| Dimension | Assessment |
| --- | --- |
| Installation | Reproducible from committed fixtures on a clean database; documented above |
| Core workflows | Company lookup, regulatory evidence, valuation, save/reopen, package export/import, provenance verification all execute in a browser |
| Correctness | 29/29 and 16/16 independent audits; exact reproduction of the reference and clean-install packages |
| Provenance | Immutable observation identity, revision chains, provider conflicts, unavailable-price disclosure; synthetic data labelled synthetic after the fix in §4 |
| Financial method | Bank residual income only where admissible; FCFF refused for banks; unavailable market analysis is explicit |
| Security | Package archive hardening verified by tests; transport bomb fixed; no new surface added |
| Licensing | Rights classes enforced at import, packaging and export; unknown fails closed |
| UI | Desktop and 390x844 mobile verified with screenshots and recorded metrics |
| Performance | Not benchmarked in this checkpoint; no claim made |
| Documentation | This report, `docs/MASTER_SPEC_TRACEABILITY.md`, README update |
| Test coverage | 507 backend tests; four frontend unit tests; two browser journeys |
| CI reliability | Workflow corrected and locally reproduced; **execution still unobserved** |

Blocking a public beta: unobserved CI execution, master-spec verification blocked, and
restricted vendor bytes remaining in published history (§10). None of these is a modelling
claim, and none is resolved by adding subsystems.

## 10. Residual restricted data in history

The tracked tree contains no vendor market fixture (`git ls-tree -r HEAD` matches only
`src/atlas/ingestion/market_alphavantage.py`, which is code). Earlier commits still contain
the removed datasets:

| Commit | Paths |
| --- | --- |
| `6920d0a` | `fixtures/market/nasdaq_{AAPL,AMZN,GS,JPM,UNH}.csv` |
| `d0e4540` | `fixtures/market/alphavantage_manifest.json` |
| earlier blobs | `fixtures/market/ibm_{daily,dividends,splits}_alphavantage.json` |

Exposure: anyone with repository access can retrieve those blobs from history. Remediation
requires a coordinated history rewrite (filter-repo or equivalent), force-push and
re-cloning by collaborators, plus a rights determination for the retained vendor data. That
is a repository-management action with destructive effects on published history and was
**not** performed: no branch was rewritten, deleted or force-pushed in this checkpoint.

## 11. Known limitations

* GitHub Actions was not executed or observed from this environment; the green statement for
  the dependency fix comes from clean local virtual environments, not from a runner.
* Browser evidence is from this VM's headless Chromium with a provisioned library sysroot; it
  is real execution, but it is not the GitHub-hosted runner and not a guarantee about other
  browsers.
* Mobile checks cover layout metrics and action visibility at 390x844, not touch gestures or
  screen-reader behaviour.
* `ATLAS_MASTER_SPEC.md` remains unavailable, so no master-spec conformance is claimed.
* Vendor bytes remain in published history until an authorised rewrite.
* The synthetic `ATLS` series has 10 sessions, below the 60-session learning minimum; the
  learning catalog now marks it ineligible rather than offering a dataset that cannot load.
