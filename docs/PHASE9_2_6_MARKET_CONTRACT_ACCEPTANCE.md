# Phase 9.2.6 — Market Contract Acceptance Record

Checkpoint: `af4e184` → this commit, branch `freebuff/41a4fd2abe41a6515dc8d5bb`,
schema 13 (unchanged), no migration.

## 1. Baseline re-verified before any change

Branch, remote and HEAD matched `af4e184a1696889c5e811ef2cf67832983dbb2f7`, tree clean,
schema 13. The full backend suite passed, both audits passed, the reference model
reproduced `295.4643539226478` with `differences={}`, and both browser journeys had been
re-executed at that commit. Nothing below depends on an assumed baseline.

## 2. Changed modules

| Module | Change |
| --- | --- |
| `src/atlas/market/evidence.py` | **new** — `MarketObservation`, `PriceSelection`, `MarketComparison`, `select_price`, `latest_observation`, `compare_model_to_market` |
| `src/atlas/research/prices.py` | selection engine replaced by delegation; three consumers rewritten against the typed contract; `SOURCE_SELECTION_POLICY` etc. re-exported from the contract module |
| `src/atlas/terminal/read_models.py` | security summaries, batch summaries and issuer metrics use the canonical selection; derived-market metrics carry `price_observation_id` |
| `src/atlas/research/equity.py` | coverage price-source label uses the canonical selection |
| `src/atlas/applications/rights.py` | delegates classification to `research.rights`; unknown rights now permit nothing |
| `src/atlas/terminal/exposure.py` | **new** — explicit non-loopback acknowledgement policy |
| `src/atlas/cli.py` | `serve` refuses a non-loopback bind without `--allow-non-loopback` / `ATLAS_ALLOW_NON_LOOPBACK=1` |
| `src/atlas/fec/compatibility.py` | **new** — operator/model version resolution |
| `src/atlas/applications/contracts.py` | package diagnostics resolve through the compatibility module; codes and messages unchanged |
| `tests/test_phase9_2_6_market_contract.py` | **new** — 31 differential, rights, exposure and compatibility tests |
| `.github/workflows/ci.yml` | new test file added to the research-integrity job |

## 3. Duplication removed

Before: `prices._selected_row`, `BarStore.latest_close` (used by `_security_summary`,
`_batch_security_summaries` and `issuer_metrics`) and a third inline
`SELECT … FROM bar … ORDER BY b.ts_utc DESC` in `EquityResearchService._issuer_coverage`
each decided "the price". They agreed most of the time and disagreed exactly when two
providers, a correction, a second venue or a saved pin were involved.

After: one engine. `BarStore.latest_close` remains for range/coverage queries but no longer
represents "the price". `prices` exposes the policy constants and the legacy serialisation,
and nothing else selects.

## 4. Typed contracts

`atlas.market_evidence.v1`: immutable `MarketObservation` (24 fields incl. rights and
identity), `PriceSelection` (policy + version, cutoff, constraints, alternatives, rationale,
missing status, replay eligibility), `MarketComparison` (valuation date, accounting period,
model version, date gap, currency, uncertainty). Details in
`docs/MARKET_EVIDENCE_CONTRACT.md`; compatibility policy in
`docs/MODEL_VERSION_COMPATIBILITY.md`.

## 5. Numerical equivalence

- Observation ids and content hashes are unchanged: the hash still covers canonical decimal
  text, and the tests assert a recomputed hash equals the stored identity.
- Saved pins still replay exactly; a correction appends revision 2 and leaves revision 1
  replayable at its original value.
- Existing price tests (101 of them) passed unchanged after the engine swap, and the full
  suite passed unchanged after the consumer migration.
- Reference reproduction: `value_per_share = 295.4643539226478`, `differences = {}`.
- Clean install reproduction: `101.21579153430544`, `differences = {}`, `network_used:false`,
  `status: pass`.
- No persisted float is converted into an observation: `Decimal` is parsed from the stored
  decimal string; the replay payload's JSON number is recovered via `Decimal(str(...))`.

## 6. Cross-consumer differential results

The suite asserts, with two providers and one correction on the same session:

| Path | Result |
| --- | --- |
| Markets security summary | same close, session and session count as the price summary |
| Issuer metrics (X-Ray) | `price`, `price_as_of` and `price_observation_id` equal the price summary's selected observation |
| Price summary vs observation detail | identical `observation_id` |
| Explicit provider | selects that provider only; a missing `source_id` is a policy error, not a guess |
| Saved pin | replays revision 1 after revision 2 exists |
| Cutoff before any observation | `unavailable`, no points, `MISSING_NO_OBSERVATION` — never substituted |
| Two venues | each venue's observation is distinct and id-stable |
| Synthetic fixture | stays labelled `synthetic` in selection and in equity coverage |
| Restricted provider | analysable locally, `export_allowed: false`, packaging refused |

## 7. Rights

`research.rights.classify` is now the only decision contract. `applications.rights` consumes
it and maps it to per-action decisions. One behaviour changed: an **unknown** redistribution
class previously permitted `ingest`, `local_storage` and `analysis` in the applications
engine while the research engine treated it as untrusted. It now permits nothing. This is a
fail-closed correction, covered by a differential test over six declarations.

## 8. API compatibility

No response type changed. Additive fields only:

- `issuer_metrics.price_observation_id`, `issuer_metrics.price_source_selection`;
- `price_observation_id` on the eight `derived_market` metrics.

Selection dictionaries keep the exact v2 key set. Saved applications, packages and pins
continue to load; package diagnostics keep their documented codes.

## 9. Performance (measured, not inferred)

Hardware: 2 vCPU cloud VM, Linux. Database: `var/phase9.db`, 36.6 MB, 10 `bar` rows for
1 security over 10 sessions (the synthetic market evidence this repository holds). Method:
in-process `time.perf_counter()` around the public function, 5 warm-up calls, 60 runs
(20 for `issuer_metrics`), median and p95.

| Read | median | p95 |
| --- | --- | --- |
| legacy `BarStore.latest_close` | 0.017 ms | 0.021 ms |
| canonical `select_price` (joined, with source metadata) | 0.099 ms | 0.115 ms |
| `prices.price_summary` | 0.194 ms | 0.227 ms |
| `read_models._security_summary` | 0.219 ms | 0.253 ms |
| `read_models.issuer_metrics` | 0.347 ms | 0.380 ms |

The canonical path is ~0.08 ms slower per read than the bare `latest_close` query because it
joins `source`, computes the immutable identity and collects competing observations. On this
dataset that is a constant overhead below half a millisecond, and no claim of improvement is
made. The synthetic dataset is too small to characterise behaviour at scale; the identical
`idx_bar_latest_v4` ordering is used, but that is an argument, not a measurement.

## 10. Verification executed

| Gate | Result |
| --- | --- |
| Backend suite | **560 passed**, exit 0 (529 before + 31 new) |
| New market-contract suite | 31 passed |
| Frontend | `npm ci` clean, 4 tests passed, `tsc --noEmit` clean, build 2.51 s |
| Phase 9.2 audits | `status: pass`, 29/29 |
| Phase 9.1 audits | 16/16 |
| Reference reproduction | `differences = {}`, value 295.4643539226478 |
| Distributable fixtures | `status: pass`, exact replay |
| Clean install | `status: pass`, value 101.21579153430544, `differences = {}`, no network |
| Database init/migration | schema 13, unchanged; no migration added |
| Browser journeys | not re-executed in this phase (see §12) |
| GitHub Actions | not observed (see §12) |
| Master specification | blocked (see §12) |

## 11. Security findings

1. **Unauthenticated non-loopback bind** (fixed): previously a warning printed while the
   server already listened externally. Now the default is loopback-only and a non-loopback
   bind is refused with exit code 2 unless explicitly acknowledged; the acknowledgement is
   documented as *not* authentication.
2. **Unknown rights permitted local actions** (fixed): a missing or unrecognised
   redistribution class allowed ingestion and analysis in one engine and not the other. It
   now permits nothing, and the two engines are tested for identical verdicts.
3. **Silent price substitution risk** (fixed by construction): a selection can no longer
   fall back to another provider or to a later session; missing data is a reported state.
4. Remaining, documented: no authentication, no signed packages, no live vulnerability feed.
   Remote deployment still requires a separate authentication design.

## 12. Blockers reported, not worked around

- **Master specification:** absent from the workspace and from the branch; `find` returns
  nothing and `scripts/verify_master_spec.py` exits 1. No clause matrix was produced.
- **GitHub Actions:** private repository, no credential available; the API returns 404 for
  the run list of this SHA. No run is claimed.
- **Browser journeys:** the Chromium sysroot provisioned in 9.2.5 lives in `/tmp` and was not
  rebuilt for this phase; the journeys were therefore not re-executed against this commit.
  The UI surface they cover is unchanged by this phase (no component or route changed), but
  that is reasoning, not evidence. The last executed evidence remains the 9.2.5 run at
  `af4e184`: JPM 8/8 and ATLS 7/7, desktop and 390×844.
- **Historical restricted bytes** remain reachable in earlier commits; the remediation
  proposal is unchanged and no history rewrite was performed.

## 13. Remaining unsupported behaviour

- Only daily observations participate; intraday intervals are not selected.
- Provider failover does not exist, by design.
- The model-compatibility registry has no real re-implementation or retirement entries yet;
  the mechanism is exercised with an unknown operator and a stale version instead.
- Screeners and additional derived ratios were not migrated because they do not exist as
  separate price consumers in this build.
