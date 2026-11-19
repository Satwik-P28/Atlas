# Phase 9.2.8 re-verification at the current branch head

Checkpoint date: 2026-11-19. Branch: `freebuff/41a4fd2abe41a6515dc8d5bb`.

`docs/PHASE9_2_8_ACCEPTANCE.md` is the record of the phase as it was executed on
2026-11-10. It is preserved unchanged. This document records what a fresh run of the same
gates finds **now**, at the real head of the branch, and what had to be repaired for those
gates to run at all.

## 1. The brief's premise was stale in two ways

The checkpoint brief was written against:

| Brief assumption | Actual state at the start of this run |
| --- | --- |
| Remote HEAD `cf67cdf` | Remote HEAD `486e7d0` (23 commits later) |
| `ATLAS_MASTER_SPEC.md` is v3.0.0, 289,963 bytes | v3.1.0, 333,547 bytes, dated 2026-11-11 |

Neither is a defect. Phase 9.2.8 was delivered at `cf67cdf`, and the repository then moved
on: `37142b5` (bulk market projection), `8b094eb` (v3.1 specification, ICB-49…64), `32941da`
and `0f9d686` (the workstation), `486e7d0` (Phase 9.5 financial knowledge engine, migration
014). Re-running the Phase 9.2.8 *work* would have meant reverting all of it, so this run
re-verified the Phase 9.2.8 *gates* instead.

## 2. Master specification identity — both versions verified

Reproduced independently with `git cat-file -s` and `git show <rev>:ATLAS_MASTER_SPEC.md | sha256sum`,
without trusting the script's own expectations:

| Revision | Version | Bytes | SHA-256 | Result |
| --- | --- | --- | --- | --- |
| `9e436b7`, `cf67cdf` | 3.0.0 (2026-11-09) | 289,963 | `c1228db93e66a04fb211bea85f6c978289a6040b1f655f934da76498c8c4752d` | matches the brief exactly |
| `486e7d0` (HEAD) | 3.1.0 (2026-11-11) | 333,547 | `d1800cfea35d973e2ff2b3570f8bf564fd3a7aceabca2f623ec5de17931a1111` | `python scripts/verify_master_spec.py` → `VERIFIED` |

Sections 1–61 are present in both. v3.1 keeps Sections 1–61 and their numbering and adds
Appendices A–D, which introduce ICB-49…ICB-64. The canonical file was not replaced with the
older document; the v3.0.0 bytes remain reachable at their commits.

Provenance status remains `received_integrity_verified` — identity proven, conformance not.

## 3. Registries at v3.1

| Registry | Entries | Status distribution |
| --- | --- | --- |
| `artifacts/master_spec_requirements.json` | 61 requirements, one per section, `spec_version` 3.1.0 | 30 `vision_only`, 22 `prototype_verified`, 9 `implemented_verified` |
| `artifacts/icb_registry.json` | **64** benchmarks (ICB-01…ICB-64) | 46 `vision_only`, 18 `prototype_verified` |

No ICB is `accepted`: acceptance requires the benchmark's own stated test to have been
executed and reproduced, and 46 have never been run at all. No requirement is
`production_eligible`.

Registry validation (`tests/test_phase9_2_8_master_spec_registry.py`,
`tests/test_phase9_2_8_bulk_overview.py`): **38 passed**. The validator still fails on a
duplicate id, a missing section, an outdated specification version, a status outside the
Section 60.2 vocabulary, or a referenced path that does not exist.

## 4. Gates re-run at `486e7d0`

| Gate | Result |
| --- | --- |
| Master-spec size and SHA-256 | **pass** (v3.1.0, `VERIFIED`) |
| Requirements registry + ICB registry + bulk differential tests | **38 passed** |
| Full Python backend suite | **701 passed**, 0 failures, 0 errors, 0 skipped |
| Frontend tests (`vitest run`) | **45 passed** (4 files) |
| TypeScript typecheck (`tsc -b --noEmit`) | **pass**, exit 0 |
| Production build (`vite build`) | **pass**, entry 301.37 kB / 94.34 kB gzip |
| Financial audit Phase 9.2 (`scripts/audit_phase9_2_models.py`) | **29/29 pass** |
| Financial audit Phase 9.1 (`scripts/audit_phase9_1_models.py`) | **16/16 pass** |
| Reference package reproduction (`scripts/reproduce_phase9_2.py`) | **pass**: 295.4643539226478, `"differences": {}` |
| Market overview benchmark (100 / 1,000 securities) | **reproduced**, parity `true` at both tiers |
| Desktop + mobile browser journeys | **pass** after the repairs below |
| Hosted GitHub Actions | **observed** — HEAD is not green (see §7) |

Environment note: the backend suite was installed from a clean virtualenv via
`pip install -e '.[dev,terminal,learning,columnar]'` inside this workspace, so the
"clean-install" evidence for this run is the fresh install itself rather than a separate
script.

## 5. Defects found by re-running the gates

Every one of these was latent, and none was visible from the unit suite.

### 5.1 Four browser journeys pinned an obsolete schema number

`phase9_2_market.mjs`, `phase9_2_jpm.mjs` and `phase9_3_memo.mjs` asserted
`health.schema_version === 13`; `phase8.mjs` asserted `=== 10`. Migration 014 moved the head
to 14, so all four aborted at their first statement — before rendering a page — for a reason
that has nothing to do with the interface they certify.

Repair: `web/e2e/schema.mjs` reads the migration chain from
`src/atlas/storage/migrations.py` and exports `LATEST_SCHEMA_VERSION`; the journeys compare
against that. The assertion is still exact (the served database must be at the migration
head); it just no longer hardcodes the number.
`tests/test_browser_journeys_schema_pin.py` fails if any journey reintroduces a literal.

### 5.2 The reproduction script pinned the same number

`scripts/reproduce_phase9_2.py` asserted `result["fresh_schema"] == 13` and now compares
against `LATEST_VERSION`. It reproduces the reference valuation again, on schema 14.

### 5.3 Three mobile overflows at 390×844

The journeys reached their mobile step and failed with `mobile page overflows: 431`. The
document was 41 px wider than the viewport:

| Page | Offending element | Cause | Repair |
| --- | --- | --- | --- |
| every Standard page | `.std-utilities` (evidence count, search, mode switch, theme) | the cluster could not shrink or wrap inside the header row | at ≤560 px it wraps and the search field narrows |
| `/companies` | `.company-card-tickers` | `white-space: nowrap` over a long share-class list | wraps instead of forcing width |
| `/research` | `.inline-field` company selector | the `<select>` kept its intrinsic width | field may shrink to the container |

After the repair all eleven Standard routes measure `scrollWidth == 390` at 390×844:
`/`, `/markets`, `/companies`, `/equity`, `/research`, `/filings`, `/screeners`, `/studio`,
`/workspaces`, `/watchlists`, `/lab`.

The horizontal scroll strips (primary navigation, wide tables) are intentional; they are
`overflow-x: auto` containers, not document overflow.

### 5.4 Rootless containers need a font config for Chromium

Chromium died with `FATAL:...SkFontMgr_FontConfigInterface.cpp:163] Not implemented.` when
no fontconfig configuration was present, which surfaced only as
"Target page, context or browser has been closed". The run needs the browser's shared
libraries plus `FONTCONFIG_FILE`/`FONTCONFIG_PATH` pointing at a config with a font
directory. This is documented here because it is the difference between "the app crashed"
and "the harness could not render text".

## 6. Browser and mobile acceptance (executed at this revision)

Chromium 156 headless shell, 1440×900 and 390×844, against the built front end served by
the API (`atlas serve --db var/phase9.db --web-dist web/dist`), database built from the
committed fixtures (`scripts/build_phase9_db.py`, `scripts/import_phase9_2_prices.py`,
`scripts/fetch_phase9_2_regulatory.py`, `scripts/import_fr_y9c.py`).

| Journey | Assertions | Mobile result | Console errors | Failed requests |
| --- | --- | --- | --- | --- |
| `phase9_2_market.mjs` (synthetic ATLS provenance, pin, save, replay) | **7/7** | 390/390, no clipped element | 0 | 0 |
| `phase9_2_jpm.mjs` (real JPM evidence, refusal to invent a price) | **8/8** | 390/390, 3 tables reachable, no clipped cell | 0 | 0 |

Screenshots regenerated at this revision: `artifacts/phase9_2_market_mobile.png`,
`artifacts/phase9_2_jpm_mobile.png`; evidence documents
`artifacts/phase9_2_market_browser.json`, `artifacts/phase9_2_jpm_browser.json`.

This is functional acceptance, not accessibility certification. Touch-target size, focus
order, contrast and screen-reader output were not measured.

## 7. Hosted CI — now observable, and not green

The repository is public, so the Actions API answers without credentials. That removes the
Phase 9.2.8 blocker "CI unreadable" but replaces it with a finding:

| Commit | Workflow | Conclusion |
| --- | --- | --- |
| `cf67cdf` (v3.0.0 provenance) | CI | success |
| `37142b5` (bulk projection) | CI | success |
| `0f9d686` (Phase 9.4.1) | CI | success |
| `486e7d0` (current head, Phase 9.5) | CI ×2 | **queued since 2026-11-11T20:34Z, never concluded** |

Two workflow runs for the current head are stuck in `queued`. The Phase 9.5 knowledge-engine
commit therefore has **no hosted CI result**, and the local suite cannot be substituted for
one. This remains a release blocker.

## 8. Market overview — reproduced, and the frontier unchanged

`python scripts/benchmark_market_overview.py --tiers 100,1000 --repeats 2`, artifact
`artifacts/phase9_2_8_market_overview_reverify.json`, 2 vCPU, SQLite in WAL:

| Tier | Plan | Statements | Warm median | p95 | Cold | Peak traced memory |
| --- | --- | --- | --- | --- | --- | --- |
| 100 (28,610 rows) | scalar | 1,202 | 573.4 ms | 617.7 ms | 543.4 ms | 1.24 MB |
| 100 | bulk | **9** | 559.9 ms | 569.1 ms | 452.8 ms | 0.96 MB |
| 1,000 (286,100 rows) | scalar | 12,002 | 5,194.2 ms | 5,462.9 ms | 5,689.5 ms | 3.95 MB |
| 1,000 | bulk | **9** | 4,344.9 ms | 4,353.1 ms | 5,061.3 ms | 5.05 MB |

* Statements are constant at **9** and independent of universe size; reduction 133.6× at 100
  and 1,333.6× at 1,000.
* Correctness parity `true` at both tiers, compared as whole documents, `first_mismatch: null`.
* Warm median speed-up 1.02× at 100 and 1.20× at 1,000; these are slower in absolute terms
  than the 2026-11-10 run on the same shape of machine, so the two runs are not directly
  comparable and are not presented as a regression measurement.
* **The sub-second 1,000-security target is still not met** (4.34 s). The bottleneck remains
  per-observation materialisation (~260,000 typed observations per overview), exactly as
  `docs/MARKET_OVERVIEW_SCALABILITY.md` concludes.
* Peak memory at 1,000 securities is **higher** for the bulk plan (5.05 MB vs 3.95 MB),
  reported rather than hidden.

## 9. What was not done, and why

* The brief's Sections 2–4, 11 and 12 (full 61-section analysis, complete requirement
  re-derivation, ICB re-evaluation, flagship-workflow re-mapping, research/compression plan)
  were delivered in the Phase 9.2.8 checkpoint and are current at v3.1 through
  `docs/MASTER_SPEC_TRACEABILITY.md`, `docs/MASTER_SPEC_V3_IMPLEMENTATION_GAPS.md`,
  `docs/MASTER_SPEC_V3_PRIORITY_ROADMAP.md`,
  `docs/INSTITUTIONAL_CAPABILITY_SCOREBOARD.md` and
  `docs/RESEARCH_AND_COMPRESSION_INTEGRATION.md`. They were re-validated, not rewritten:
  rewriting them without new evidence would only have produced unverifiable text.
* No API surface changed. The OpenAPI projection is unchanged and its contract test passes
  inside the suite.
* The `phase9_3_memo.mjs` and `phase8.mjs` journeys were repaired for the schema pin but not
  executed here: they need their own memo/package corpora, and this checkpoint did not
  rebuild them.

## 10. Remaining blockers

1. **Hosted CI for the current head is queued, not green** (`486e7d0`, two runs).
2. **Sub-second 1,000-security overview not achieved** (4.34 s warm median, 9 statements).
3. **ICB-01…ICB-64**: 46 `vision_only`, 18 `prototype_verified`, none accepted.
4. **Research and compression integration** is a contract only; no evaluation was run, and
   no improvement is claimed.
5. **Standing release restrictions unchanged**: restricted historical vendor bytes remain
   reachable in earlier commits (no history rewrite), the API is unauthenticated and must not
   be exposed non-loopback, external beta use is unverified, proprietary data coverage and
   several model domains remain unsupported.
6. **Accessibility not certified**; only functional layout at 390 px was measured.

## 11. Reproduce this re-verification

```bash
python scripts/verify_master_spec.py
python -m pytest -q
python -m pytest -q tests/test_phase9_2_8_master_spec_registry.py \
                    tests/test_phase9_2_8_bulk_overview.py \
                    tests/test_browser_journeys_schema_pin.py
python scripts/build_phase9_db.py --db var/phase9.db --force
python scripts/import_phase9_2_prices.py --db var/phase9.db
python scripts/fetch_phase9_2_regulatory.py --db var/phase9.db
python scripts/import_fr_y9c.py --db var/phase9.db --archive fixtures/regulatory/BHCF20241231.ZIP \
  --dictionary fixtures/regulatory/Financial_Download_Dictionary.xlsx --cik 19617 --entity REG-JPM-PARENT
python scripts/audit_phase9_2_models.py --db var/phase9.db
python scripts/audit_phase9_1_models.py --db var/phase9.db
python scripts/reproduce_phase9_2.py
python scripts/benchmark_market_overview.py --tiers 100,1000 --repeats 2 \
  --out artifacts/phase9_2_8_market_overview_reverify.json
(cd web && npm ci && npm run typecheck && npx vitest run && npm run build)
.venv/bin/atlas --db var/phase9.db serve --port 8000 --web-dist web/dist &
(cd web && ATLAS_BASE=http://127.0.0.1:8000 node e2e/phase9_2_market.mjs)
(cd web && ATLAS_BASE=http://127.0.0.1:8000 node e2e/phase9_2_jpm.mjs)
```

In a rootless container, export the browser's libraries and a fontconfig file before the two
`node e2e` commands (see §5.4).
