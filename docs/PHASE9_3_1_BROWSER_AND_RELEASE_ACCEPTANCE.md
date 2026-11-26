# Phase 9.3.1 — browser, export, performance and release acceptance

Checkpoint date: 2026-11-10. Development branch `freebuff/41a4fd2abe41a6515dc8d5bb`.

| Item | Value |
| --- | --- |
| Starting development commit | `1826926f4726bf9b63061187be510c3e36a60925` |
| Development remote HEAD at start | `1826926f4726bf9b63061187be510c3e36a60925` |
| `main` at start | `44a12dcb5f472aa5b1e1cfc3b4ebcc37d50d5889` |
| Relationship | `main` is an ancestor of the development branch; development is 29 commits ahead, `main` 0 ahead |
| Master specification | v3.0.0, 289,963 bytes, SHA-256 `c1228db9…c4752d`, `verify_master_spec.py` passes |
| Database schema | 13 (no migration in this phase) |
| OpenAPI | 147 routes across 133 paths (8 memo routes, additive) |

## 1. What changed in this phase

1. **Preview/save consistency guard.** `ResearchMemoService.save()` accepts
   `expected_content_hash`. When the rebuilt memo's hash differs from the hash the analyst
   reviewed, the save is refused with `memo_content_changed` and both hashes; nothing is
   persisted. The interface sends the reviewed hash and renders the mismatch as "evidence
   changed after this memo was built … build it again and review the new claims".
2. **Change detection surfaced properly.** The memo panel now shows the change status, an
   explicit `Review required: yes/no`, each finding with its category and detail, the affected
   claims with their keys and statements, and the original → replacement values with the
   revision kind.
3. **Benchmark and journey tooling.** `scripts/benchmark_research_memo.py` and
   `web/e2e/phase9_3_memo.mjs`.
4. **Regression tests** for hash determinism, the stale-preview refusal, the accepted path and
   backward compatibility when no hash is supplied.

## 2. Preview and save cannot silently diverge

`ResearchMemoService.build()` is deterministic for fixed evidence, assumptions, cutoff and
compiler version; a test asserts that two builds produce the same `content_hash`. `save()`
therefore compares the reviewed hash with the freshly built one:

| Case | Result |
| --- | --- |
| Preview hash == rebuilt hash | saved, and the stored `spec.content_hash` equals the reviewed hash |
| Evidence, assumptions, observation revision, cutoff or rights changed between preview and save | `ValidationError` `memo_content_changed`, `expected_content_hash`/`actual_content_hash` in the context, nothing persisted |
| No hash supplied (existing API clients) | unchanged behaviour, saves as before |

The invariant is checked in the browser journey too: the hash rendered in the memo panel is
compared with the hash returned by the save call, and the stored object's memo hash.

## 3. Export verification and the rights decision

Measured on the reference database (`var/phase9.db`, 26,440 evidence records):

| Issuer | Claims | Evidence dependencies | Memo hash | Redistributable |
| --- | --- | --- | --- | --- |
| JPM | 36 | 9 | `d273a259…` | **false** — `csv-import` is `user_responsibility` |
| AAPL | 48 | 12 | — | **false** — same source |

Export is therefore **refused** on the reference database, which is the designed behaviour:
the imported price source carries no redistribution grant, so no downloadable document may
carry it. The refusal names the blocked source and both the API (HTTP 422) and the panel
state it.

Successful export was measured on a dedicated demonstration database
(`var/phase9_export.db`), identical to the reference build except that `csv-import` carries an
operator-declared `permitted` grant. This is a demonstration grant for acceptance, recorded
here so it is not mistaken for a change to the real rights posture. On that database:

| Format | Bytes | Median | p95 | Independent checks |
| --- | --- | --- | --- | --- |
| Markdown | 16,168 (JPM) / 23,131 (AAPL) | 3.21 / 4.34 ms | 3.24 / 4.45 ms | heading, claim register, memo hash, no script |
| HTML | 20,897 / 30,979 | 3.31 / 4.49 ms | 3.38 / 4.62 ms | doctype, no script, no event handler, memo hash |
| JSON | 88,224 / 126,294 | 12.21 / 16.81 ms | 12.66 / 31.41 ms | manifest memo hash, evidence dependencies, claims, rights |

With the grant the API reports `redistributable: true` and `blocked_sources: []`; the exports
carry the manifest, the rights decision and the memo hash. The committed journey also asserts
the refusal path (422 and the panel disclosure) when rights do not allow export.

## 4. Memo and export performance

Environment: Python 3.12.3, Linux, 5 iterations per measurement, median and nearest-rank p95
of wall-clock milliseconds, SQL statements counted by wrapping the database helpers,
`tracemalloc` peak per iteration. Dataset: 26,440 evidence records, schema 13.

| Operation | JPM median | JPM p95 | AAPL median | AAPL p95 | SQL statements |
| --- | --- | --- | --- | --- | --- |
| Memo build (cold service) | 4,023.16 ms | 4,332.83 ms | 4,542.92 ms | 5,010.89 ms | 31,670 / 36,674 |
| Memo build (warm) | 4,130.11 ms | 4,429.58 ms | 4,423.18 ms | 4,913.41 ms | 31,586 / 35,065 |
| Save a new immutable version | 15.43 ms | 15.69 ms | 20.66 ms | 23.52 ms | 38 / 47 |
| Reopen | 2.25 ms | 2.48 ms | 3.14 ms | 3.50 ms | 22 / 28 |
| Change check | 3.04 ms | 4.71 ms | 4.25 ms | 7.06 ms | 28 / 34 |
| Markdown export | 3.21 ms | 3.24 ms | 4.34 ms | 4.45 ms | — |
| HTML export | 3.31 ms | 3.38 ms | 4.49 ms | 4.62 ms | — |
| JSON export | 12.21 ms | 12.66 ms | 16.81 ms | 31.41 ms | — |

Peak memory: 5.16 MiB for a build, 0.24–0.35 MiB for save/reopen/check. Cold and warm builds
are indistinguishable because the cost is the equity analysis plus the evidence queries, not
the memo assembly. **No speedup is claimed**: no earlier memo implementation exists to compare
against, and the bulk market overview path was not modified or re-benchmarked in this phase.

## 5. Browser acceptance

Local Chromium could not be launched in this environment:

```
chrome-headless-shell: error while loading shared libraries: libnspr4.so: cannot open shared object file
```

`sudo` is unavailable (`the "no new privileges" flag is set`), so `playwright install-deps`
cannot run. The committed journey `web/e2e/phase9_3_memo.mjs` is therefore **present and
runnable but not executed here**.

The cloud browser was used instead. It reached the served application and rendered the
Markets overview (coverage table, source-rights cards, synthetic labelling, footer policy
note). Two attempts to drive the journey through the cloud Playwright bridge failed with tool
errors (`Playwright exceeded 60s in the chat workspace` and
`The property 'options.mode' must be one of: 'strip'. Received 'transform'`), and the
viewport-based mobile pass depends on that bridge. Consequently:

* **Desktop acceptance: not certified.** The application renders; the memo journey was not
  driven end to end in a browser.
* **Mobile 390×844 acceptance: not performed.** No screenshot or layout measurement exists,
  and no claim is made about overflow, clipping or touch reachability.
* **Download bytes were not read from a browser download event.** Export bytes were read from
  the API server for this database, plus the unit tests.

These are blocked gates, not passes. The journey script is committed with `data-testid`
selectors (`equity-memo-create`, `equity-memo-save`, `equity-memo-check`,
`equity-memo-export-*`, `equity-memo-change-*`) so a browser-capable environment can run it
without editing the assertions.

## 6. End-to-end demonstration

Executed at the API level against the reference and export-database servers: select the issuer,
inspect the regulatory evidence context, generate the valuation, create the memo, verify 36
claims (12 verified, 24 non-factual), inspect integrity (decision `fail` for JPM, statistical
`not_applicable`), save on the reviewed hash, confirm the stored hash, export (refused on the
reference database, allowed on the granted one), reopen with the same hash, check for change
(`unchanged`, `review_required: false`), and create a new version while the old hash stays
fixed.

**The 13-step flow was not executed as one browser-driven run.** Steps that require the
interface were exercised only through the API and through the unit suite, so this is a
partial demonstration, recorded as partial.

## 7. Correctness review

| Risk | Finding |
| --- | --- |
| Claim-level issuer identity | Enforced; a claim citing another issuer is rejected (test) |
| Unit and currency validation | Enforced in the verifier; mismatches are `unsupported` with diagnostics |
| Historical availability | Claims after the cutoff are rejected; availability is part of the comparison |
| Model-fingerprint consistency | Verified outputs require a matching compiler version and audit pass |
| Stale preview/save race | Closed in this phase by `expected_content_hash` |
| Export tampering | Manifest hash and `verify_export()` detect it (test) |
| Source-rights enforcement | Refused export names the blocked source; demonstrated on the reference database |
| Untrusted text rendering | HTML escapes source and analyst text; no script or event handler survives |
| Immutable version persistence | Old version keeps its hash after a new save (test) |
| Change-detector false positives | Unrelated new evidence leaves the memo `unchanged` (test) |
| Missing dependency | Reported as `missing_dependency` with affected claims, never silently dropped |
| Permission boundaries | Still none: the terminal API is unauthenticated and non-loopback binding requires explicit acknowledgement |

## 8. Verification gates

| Gate | Result |
| --- | --- |
| Backend suite | **658 tests, 0 failures, 0 errors, 0 skipped** |
| Frontend tests | 4 passed |
| TypeScript typecheck / production build | clean / succeeded (2.98 s) |
| Master-spec integrity | pass |
| Requirements and ICB registry | 61 requirements, 48 ICB (18 prototype-verified, 30 vision-only) |
| Financial audits | 29/29 and 16/16 |
| Reference reproduction | `295.4643539226478` |
| OpenAPI compatibility | 147 routes / 133 paths, additive only |
| Desktop Playwright journey | **blocked** (missing Chromium system libraries) |
| Mobile 390×844 | **not performed** (same block) |
| Hosted GitHub Actions | **unobserved** |
| Performance benchmark | memo/export measured; bulk overview unchanged and not re-measured |

## 9. Release decision

| Audience | Verdict | Basis |
| --- | --- | --- |
| Internal research | **Suitable** | Evidence-grounded claims, immutable versions, deterministic change detection, green suites and audits |
| Invitation-only technical beta | **Conditional** | Requires authenticated boundary in front of the unauthenticated API, and a completed browser journey |
| Public beta | **Not suitable** | No browser certification, no authentication, incomplete proprietary coverage, standing restricted-history considerations |

The repository is not made public and no public release is published by this phase.
