# Phase 9.2.2 — release integrity, exact replay and reproducibility

**Baseline:** `ed327d10695dc9981b97ae6c30e1fd070f894e93` on
`freebuff/41a4fd2abe41a6515dc8d5bb`.

**Scope:** this is a verification and hardening checkpoint. It does not reimplement the
Phase 9.2.1 corrections (append-only market evidence, immutable source rights, GAAP stress
labelling, clean-surplus growth, average common ROE). Those remain as they were.

**Status:** market-data rights, observation pinning and session identity are implemented and
tested. The master-specification gate and the GitHub Actions runs remain **unverified**; both
are reported as blockers rather than claimed.

## 1. Verified defects corrected here

| # | Defect | Correction |
| --- | --- | --- |
| 1 | Restricted vendor price histories were tracked in `fixtures/market/` (five Nasdaq CSVs; three Alpha Vantage demo responses) and used as ordinary CI fixtures. A private repository does not grant redistribution. | Removed from the tracked tree; replaced with project-authored synthetic fixtures, a synthetic hash manifest, and a user-supplied import path for licensed data. |
| 2 | Source selection recorded provider and session, but not an immutable observation identity, so a later provider correction could change what a saved analysis appeared to have used. | Added `atlas.market_observation.v1` identity (content hash + `MOB-` revision id) and `atlas.market_observation.pin.v1` pins with exact-revision replay. |
| 3 | The importer resolved a ticker at one declared `as_of` date and then applied it to every row in a multi-session batch. | Every distinct session is re-resolved; a batch whose sessions resolve to a different security is rejected; unassigned backfill sessions are reported explicitly. |
| 4 | `atlas.market_price.selection.v1` implied a single canonical quote and could silently take a different provider for a later session. | `v2` names its basis (`latest_session`, `latest_revision`, `explicit_source`, `pinned`), records the observation identity, and reports provider consistency and conflicts. |
| 5 | The independent financial audit required a restricted JPM price to pass, so CI could not run without vendor data. | The audit now accepts either a lawful observation (and then asserts cutoff safety and the implied-CoE identity) or an explicit `unavailable` status. No synthetic quote is substituted. |

## 2. Changed files

Backend:

- `src/atlas/research/observations.py` *(new)* — observation content hash, stable revision id,
  pin construction, fail-closed `resolve_pinned`.
- `src/atlas/research/prices.py` — `atlas.market_price.selection.v2`, explicit policy
  resolution, `price_for_pin`, pin payload on selections, per-session identity validation on
  import.
- `src/atlas/ingestion/market_alphavantage.py` — `load_archived` now requires caller-supplied
  filenames (no bundled vendor archive); new `load_synthetic_fixture` that refuses an
  unlabelled payload.
- `scripts/import_phase9_2_prices.py` — synthetic bootstrap by default; explicit licensed
  user import via `--csv`, with mandatory source name, licence and redistribution.
- `scripts/build_terminal_db.py` — the provider-shaped market path now uses the synthetic
  fixture under the `synthetic-demo` source.
- `scripts/audit_phase9_2_models.py` — price-dependent checks accept explicit unavailability.
- `scripts/verify_distributable_fixtures.py` *(new)*, `scripts/verify_clean_install.py`
  *(new)* — offline distributability and save/reopen/export/import verification.

Fixtures and data:

- removed: `fixtures/market/nasdaq_{JPM,GS,UNH,AAPL,AMZN}.csv`,
  `fixtures/market/ibm_{daily,dividends,splits}_alphavantage.json`,
  `fixtures/market/alphavantage_manifest.json`;
- added: `fixtures/market/synthetic_{prices.csv,daily_bars.json,splits.json,dividends.json}`,
  `fixtures/market/synthetic_manifest.json`;
- rewritten: `fixtures/market/manifest.json`, `fixtures/sec_ibm/manifest.json` (records the
  removed vendor documents and why).

Tests, CI and documentation:

- `tests/test_phase9_2_2_market_observations.py` *(new, 17 tests)*,
  `tests/test_phase9_2_2_data_rights_fixtures.py` *(new, 7 tests)*;
- `tests/test_phase9_2_1_market_integrity.py`, `tests/test_phase9_2_institutions.py` —
  policy-version constant and session-window expectations updated;
- `.github/workflows/ci.yml` — distributable-fixture job and a Playwright browser job;
- `docs/MARKET_PRICE_DATA_RIGHTS.md`, `fixtures/README.md`, `README.md`, this record.

## 3. Source-data rights findings

| Source | Terms | Decision |
| --- | --- | --- |
| SEC EDGAR submissions / companyfacts | U.S. Government public domain | retained |
| FFIEC NIC `BHCF20241231.ZIP`, FDIC institution JSON | U.S. Government public domain | retained |
| Nasdaq quote-history CSVs | manifest recorded `redistribution: restricted`; no grant | **removed** |
| Alpha Vantage demo responses | vendor terms; no redistribution grant established | **removed** |
| Atlas synthetic fixtures | project-authored (Apache-2.0) | retained, labelled synthetic |

Historical note: the removed bytes remain reachable in earlier Git commits. Rewriting
published history was not authorized, so no history was rewritten. A rights-compliant
remediation, if the maintainers want it, is a coordinated history rewrite plus a published
notice — out of scope for this checkpoint. See `docs/DATA_RIGHTS_AUDIT.md`.

## 4. Observation revision semantics

- `content_hash` = SHA-256 over security, MIC, interval, session, OHLCV, currency,
  adjustment convention and source id.
- `observation_id` = `MOB-` + SHA-256 over the content hash plus source, revision sequence and
  adjustment. Two corrections never collide; a revert is still distinguishable.
- A pin carries the identity and retrieval metadata, **not** the price value
  (`value_embedded: false`), so a portable artefact never smuggles a restricted observation.
- `resolve_pinned` returns `exact`, `exact_revision_unavailable`,
  `exact_revision_content_mismatch`, or `pin_invalid`. It never substitutes the latest price.
- A research object stores its pin inside the object document; reopening replays the pinned
  revision, and opting into a newer revision creates a second object version. Both remain
  resolvable.

## 5. Security-identity decisions

- Resolution happens at the import's declared `as_of` date, then **again per session**.
- A session resolving to a *different* security is cross-identity contamination → the whole
  batch is rejected (all-or-nothing, no partial rows).
- A session with no active assignment window is recorded in
  `session_identity.unassigned_sessions` and in `listing_validity_advisories`; it is never
  reassigned to a guessed security. This is what makes historical backfills possible without
  pretending the assignment existed then.
- Ticker text is never the identity: security, listing MIC, currency and assignment window
  decide, and an ambiguous ticker still requires an explicit `security_id` and `mic`.

## 6. Canonical selection policy

`atlas.market_price.selection.v2`:

| Basis | Ordering | Declared meaning |
| --- | --- | --- |
| `latest_session` (default) | session desc, revision desc, source id, MIC | latest market information at or before the cutoff |
| `latest_revision` | ingested_at desc, session desc, revision desc | most recently **imported** observation; not "latest market information" |
| `explicit_source` | session desc, revision desc | one provider, chosen by the caller |
| `pinned` | exact revision | reproduce a saved analysis |

Every result reports `policy`, `requested_policy`, `policy_label`, `dimensions`,
`observation_id`, `content_hash`, `revision_seq`, `alternatives`, `conflict` and
`provider_consistency`. A series is never assembled from two providers; alternatives stay
inspectable, and a later import cannot silently change which provider a saved analysis used.

## 7. Verification actually run (local, offline)

| Check | Result |
| --- | --- |
| `python -m pytest` (backend) | **479 passed** |
| Frontend unit tests (`vitest`) | **4 passed** |
| TypeScript typecheck + production build | **pass** (701.09 kB / 207.27 kB gzip) |
| CI database sequence (build → regulatory → FR Y-9C → prices) | **pass** (all exit 0) |
| Independent Phase 9.2 audit | **29/29 passed** |
| Independent Phase 9.1 audit | **16/16 passed** |
| `scripts/reproduce_phase9_2.py` | **pass**, `differences={}`, package SHA-256 `3bbaca54…` |
| `scripts/verify_distributable_fixtures.py` | **pass** (see §8) |
| `scripts/verify_clean_install.py` | **pass** — packaged AAPL research installed, reopened and reproduced on a fresh database (`differences={}`) |
| `git diff --check` | clean |

## 8. Distributable-fixture evidence

`scripts/verify_distributable_fixtures.py` confirms: no `nasdaq_*`/`ibm_*_alphavantage*`
file under `fixtures/`; every hash in `synthetic_manifest.json` matches the tracked bytes; the
market manifest declares synthetic, vendor-free, public-domain terms; and a synthetic import
plus exact pin replay works in a throwaway database. `--require-demo-db` additionally asserts
the demo database's market series is registered with `kind = synthetic`.

## 9. Browser acceptance

The workflow now runs the Phase 9.2 journeys on an Ubuntu runner with
`npx playwright install --with-deps chromium`, against a server built from committed
fixtures only, covering desktop and 390×844. Failure uploads the screenshots and both logs.

**Local execution was not obtained in this container** (the bundled Chromium has repeatedly
failed to start renderers here). No browser or mobile result is claimed for this checkpoint;
see §11.

## 10. Financial models

No model arithmetic changed. v3 remains the default bank residual-income model
(`atlas.bank.residual_income.v3`), with ending-equity ROE kept as a labelled proxy and
average common ROE driving the model. The v2 package still installs and reproduces
unchanged on a fresh schema-13 database, so historical versions remain distinct. Neither
model is promoted to `economically_reviewed` or `independently_benchmarked`: arithmetic
identity is not economic validation.

## 11. Remaining blockers and limitations

1. **Master specification.** `ATLAS_MASTER_SPEC.md` v1.2.0 is absent.
   `scripts/verify_master_spec.py` exits 1. Expected 155,419 bytes and SHA-256
   `e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9`. No substitute was
   generated, so the gate stays blocked.
2. **CI runs unobserved.** The workflow is committed and every step was reproduced locally,
   but GitHub Actions run URLs and status could not be read from this environment. CI success
   is not claimed.
3. **Browser and 390×844.** No local browser result; the CI job is the path to that evidence.
4. **Historical Git objects** still contain the removed vendor bytes. Rewriting published
   history needs separate authorization.
5. **Regulatory leverage** remains unverified (no Tier 1 numerator or leverage-exposure
   denominator); FR Y-9C point-in-time reconstruction remains prohibited without a release
   vintage.
6. **Nasdaq automated collection** is still unauthorized; imports are local files only.

## 12. Reproduction commands

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,terminal,learning,columnar]'
python -m pytest
python scripts/build_phase9_db.py --db var/phase9.db --force
python scripts/fetch_phase9_2_regulatory.py --db var/phase9.db
python scripts/import_fr_y9c.py --db var/phase9.db --cik 19617 --entity REG-JPM-PARENT \
  --retrieved-at 2026-11-06T20:00:00Z
python scripts/import_phase9_2_prices.py --db var/phase9.db
python scripts/audit_phase9_2_models.py --db var/phase9.db --out artifacts/phase9_2_model_audit.json
python scripts/audit_phase9_1_models.py --db var/phase9.db --out artifacts/phase9_1_model_audit.json
python scripts/reproduce_phase9_2.py
python scripts/verify_distributable_fixtures.py
python scripts/build_terminal_db.py --db var/atlas.db --force
python scripts/verify_clean_install.py --demo-db var/atlas.db
```

Frontend:

```bash
cd web && npm ci && npm test -- --run && npm run typecheck && npm run build
```
