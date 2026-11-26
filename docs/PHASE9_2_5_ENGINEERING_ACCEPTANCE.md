# Phase 9.2.5 — engineering acceptance, transport hardening and beta preparation

Starting commit: `481cd58dd0d6254e9016131786393def663f9770` on
`freebuff/41a4fd2abe41a6515dc8d5bb`. The commit that introduces this document is reported
with the push.

This checkpoint does not begin Phase 10 and adds no financial model, asset class or
subsystem. It closes engineering gaps that were reachable without the master
specification, hardens two untrusted-input boundaries, records the repository state
honestly, and prepares an external-beta package that a non-developer can follow.

## 1. Repository state at the start

| Check | Result |
| --- | --- |
| Branch | `freebuff/41a4fd2abe41a6515dc8d5bb` |
| Local HEAD | `481cd58dd0d6254e9016131786393def663f9770` |
| Remote HEAD | same commit (`FETCH_HEAD` verified at 9.2.4) |
| Working tree | clean |
| Schema | 13 |
| Master specification | absent everywhere on the machine (see §2) |
| GitHub Actions credential | none (see §7) |

The 9.2.4 baseline was re-executed rather than assumed: backend suite, both independent
audits, the reference reproduction and the frontend gates all pass on this commit before
any change (`docs/PHASE9_2_4_FINAL_VERIFICATION.md`).

## 2. Master specification: still blocked, and provably so

`ATLAS_MASTER_SPEC.md` is not present in the checkout, in the workspace, or anywhere on
the filesystem (`find / -name 'ATLAS_MASTER_SPEC*'` returns nothing). No attachment was
supplied to this environment.

```
$ python scripts/verify_master_spec.py
BLOCKED: ATLAS_MASTER_SPEC.md is not present   (exit 1)
```

The gate therefore remains **blocked**. The file was not regenerated from a prompt, from
the hash, or from memory; a matrix built on an invented specification would be a
plausible-looking document with no evidentiary value. `docs/MASTER_SPEC_TRACEABILITY.md`
records the block and maps only requirements this repository can itself verify.

Consequently: **zero master-spec clauses are mapped**, and the 34-section review, the
clause-level matrix and the ICB-01…ICB-20 mapping are all deferred. The only ICB
identifiers that exist anywhere in the repository are ICB-04 and ICB-09, referenced in
`docs/PHASE7_READINESS.md`; the other eighteen have no local definition, so they cannot
be mapped without inventing their content.

## 3. SEC transport: strict completeness and resource bounds

Phase 9.2.4 bounded decompression *output* but left two source-level defects.

**Defect A — truncation accepted as success.** `_inflate` ended its loop when the input
was exhausted, without requiring the decompressor's end-of-stream marker:

```python
if inflater.eof:
    break
data = inflater.unconsumed_tail
if not data:
    break          # truncated stream returns partial bytes as a 200 document
```

A response cut short by a proxy or a flaky connection was therefore stored as a raw
document and parsed as if complete — exactly the failure mode a financial evidence
system must not have.

**Defect B — compressed input unbounded.** `_urllib_transport` called `response.read()`
with no limit and the deflate budget applied only after the body was in memory.

**Correction.**

* `_inflate` now requires `inflater.eof` before returning; if input ends first it raises
  `ProviderPayloadError("compressed response is truncated")`. zlib verifies the gzip
  CRC-32 and ISIZE trailer at that marker, so a corrupt trailer is refused too.
* Concatenated gzip members (RFC 1952) are decoded in order; for `deflate` (RFC 1950
  zlib framing) trailing bytes are refused; for gzip, trailing bytes that are not another
  member are refused.
* Compressed input is capped by `_MAX_COMPRESSED_BYTES` (64 MiB, matching the body cap)
  before any deflate work; output remains capped by `_MAX_BODY_BYTES` with a
  one-byte-over probe so the limit trips while decoding.
* `_read_bounded` refuses a declared `Content-Length` above the limit before reading and
  consumes the body in 64 KiB chunks, so an undeclared or understated length cannot
  exhaust memory.
* `SecClient.get` now retries `http.client.HTTPException` (`IncompleteRead` is not an
  `OSError`), turning an interrupted read into a bounded retry and then
  `ProviderUnavailable` — never a short document.

Adversarial coverage lives in `tests/test_release_security_9_2_5.py`: truncated gzip,
gzip without trailer, truncated deflate, concatenated members, trailing bytes for both
encodings, corrupt CRC, invalid header, compressed input over the limit, empty compressed
body, bounded reads (declared/undeclared/oversize), interrupted read retries, and a
truncated transport body being refused rather than returned.

## 4. Release-security review

Scope reviewed: HTTP request/response handling, archive decompression, ZIP package
parsing, path validation, source-rights enforcement, research-object serialisation, API
input validation, resource exhaustion, local database concurrency and service exposure.

| # | Area | Finding | Class | Action |
| --- | --- | --- | --- | --- |
| 1 | SEC decompression | truncated stream returned as complete; unbounded input read | **Exploitable correctness defect** (silent partial evidence) | fixed, regression tests |
| 2 | ZIP package parsing | unsupported compression method and encrypted-member `RuntimeError` escaped as unhandled exceptions; corrupt deflate could surface as a 500 | **Correctness/robustness defect** | fixed: method allowlist, broader integrity mapping, NUL-byte rejection |
| 3 | FR Y-9C archives | `archive.read()` of an externally supplied member had no expanded-size bound | **Defensive improvement** (resource exhaustion) | fixed: 512 MiB member cap, 64 MiB dictionary cap, streaming read |
| 4 | HTTP request handling | no body-size ceiling; a loopback client could make the process buffer an arbitrary document | **Defensive improvement** (resource exhaustion) | fixed: 8 MiB middleware ceiling, 413 with structured error, declared-length pre-check |
| 5 | Service exposure | `--host 0.0.0.0` silently exposes an unauthenticated read/write API | **Operational risk** | warning printed for any non-loopback bind |
| 6 | Path validation | package paths, pack paths, SPA static paths all validated (`..`, absolute, symlink, encoding) | none found | pinned by tests |
| 7 | Rights enforcement | backend fails closed; package re-evaluates declarations and data-bearing files | none found | unchanged |
| 8 | Local database | one connection per request, WAL, `busy_timeout`, explicit transactions | none found | unchanged |
| 9 | Model execution | allowlisted operator registry, no `eval`/`exec`/dynamic import on the valuation path | none found | unchanged |
| 10 | Authentication | no accounts; API is loopback-only by default | **Unsupported threat assumption** if exposed | documented, warning added |
| 11 | Signature verification | packages are unsigned; `signature_status` must be `unsigned` | known gap | documented, not implemented |

No security rewrite was performed. Every fix above is bounded to the boundary it
protects, and each has a regression test that fails on the previous code (the truncation
test is the clearest: it passed silently before).

## 5. Build hygiene

`src/atlas_quant.egg-info/` was tracked (`PKG-INFO`, `SOURCES.txt`,
`dependency_links.txt`, `entry_points.txt`, `requires.txt`, `top_level.txt`). These are
setuptools build metadata derived from `pyproject.toml` and the source tree, not source.
They are now untracked (`git rm --cached`), `*.egg-info/` is ignored, and an editable
install regenerates them locally without dirtying the tree — verified:

```
$ python -m pip install -e .
$ git status --porcelain | grep egg-info   # (nothing)
$ git check-ignore -q src/atlas_quant.egg-info && echo ignored
ignored
```

Committed evidence artifacts were reviewed and retained only where their provenance is
clear: `artifacts/phase9_2_*.png`, `artifacts/phase9_2_*.json`, the audit outputs and the
release manifest all name the database, revision or journey they came from. No database,
credential, vendor file or build cache is tracked.

## 6. Financial reproducibility (unchanged assumptions)

| Check | Result |
| --- | --- |
| Phase 9.2 bank audit (`audit_phase9_2_models.py`) | `pass`, 29/29 checks |
| Phase 9.1 model audit (`audit_phase9_1_models.py`) | `pass`, 16/16 checks |
| Reference reproduction (`reproduce_phase9_2.py`) | `differences={}`, `value_per_share=295.4643539226478` |
| Common-equity basis | SEC total stockholders' equity less same-period preferred stock |
| JPM / GS common equity | $324.708B / $108.743B (unchanged) |
| FCFF for banks | refused by policy |
| Saved-result replay | exact (`exact_replay: true`) |

No assumption, discount rate, growth rate or share-denominator basis was changed in this
checkpoint. The 9.2.4 numbers reproduce to the last digit, which is the point.

## 7. GitHub Actions: still unobserved

| Probe | Result |
| --- | --- |
| `gh auth status` | no logged-in host |
| `GITHUB_TOKEN` in environment | not set |
| `GET /repos/Satwik-P28/Atlas/actions/runs?head_sha=…` | `404` (earlier `403`) |
| Actions run URL / conclusion / job log | none obtainable |

The repository is private and the only credential available to this environment is scoped
to `git fetch`/`git push`. No hosted run, job conclusion, duration or artifact is claimed
anywhere in this checkpoint. Every command in `.github/workflows/ci.yml` was executed
locally with the same arguments, which is evidence about the commands, not about a
runner. Unblocking requires a GitHub credential with Actions read access (or a human
reading the run for the pushed SHA).

## 8. Browser acceptance (re-executed at this revision)

The workspace was restored without a browser runtime, so Playwright's Chromium and the
missing system libraries were provisioned again without root (Debian packages downloaded
with `apt-get` into a private list/cache state, extracted with `dpkg-deb -x` into
`/tmp/sysroot`, with a minimal `fonts.conf`). The application was served from
`var/phase9.db` on `127.0.0.1:3000`, and both journeys were run unmodified.

| Journey | Result | Evidence |
| --- | --- | --- |
| Scenario A — JPM research | exit 0, **8/8 assertions** | `artifacts/phase9_2_jpm_browser.json`, three screenshots |
| Scenario B — synthetic ATLS market | exit 0, **7/7 assertions** | `artifacts/phase9_2_market_browser.json`, two screenshots |

Scenario A: real JPM identity, FR Y-9C consolidated $4.00T / 15.68%, FDIC CERT 628;
price-relative analysis unavailable without an authorised observation; model
295.4600 → 287.9200; FCFF rejected for a bank; research object `URO-APP-4c54bbb5eb21`
saved and reopened at 287.9200; `equity-research.atlas` exported; all research surfaces
render; 390×844 with no overflow or clipped values (`scrollWidth == 390`).

Scenario B: `ATLS` present and explicitly labelled synthetic; provenance
`MOB-356738f0eb64cd6ecce8b2d4` with a recomputable hash; browser identity equals API
identity; exact replay with no substitution for a missing pin; pin/copy/revision/provider
inspection in the interface; `URO-DAT-c4d5f8ce4844` reopened on the pinned revision;
390×844 provenance panel fits without document overflow.

Neither journey produced a console error, page error or failed HTTP request. The report
SHA-256 remains `63c8237fd0ec419de01eb91d92e970dfbd0e796aa27e1e9ab45440ac5a82d147`.

Limitation: this is headless Chromium in a provisioned sysroot, not a real device;
mobile evidence covers layout metrics, not touch or assistive technology.

## 9. External beta package

`docs/ATLAS_BETA_USER_TEST_PLAN.md` contains the eleven-step walkthrough (clean install →
issuer → model → assumptions → provenance → save/reopen → export → second-install
reproduction), the demo-mode description, the declaration that market prices are absent
and synthetic fixtures are labelled, and the evaluation protocol with measures
(completion, time-to-result, setup friction, clarity of limitations).

No external participant has run it. The document is a protocol, not a validation claim.

## 10. Verification actually run at this checkpoint

| Gate | Result |
| --- | --- |
| Backend suite | pass, exit 0 (529 tests) |
| New adversarial suite | 29 tests, pass |
| Frontend unit tests | 4 passed |
| TypeScript typecheck | pass |
| Production build | pass (`built in 2.72s`) |
| Phase 9.2 audit | 29/29 `pass` |
| Phase 9.1 audit | 16/16 `pass` |
| Reference reproduction | `differences={}`, 295.4643539226478 |
| Clean install | `pass`, package `f1cae8fa…`, value 101.21579153430544, `differences={}` |
| Browser Scenario A | exit 0, 8/8 assertions, desktop + 390×844 |
| Browser Scenario B | exit 0, 7/7 assertions, desktop + 390×844 |
| Master-spec gate | **blocked** |
| GitHub Actions | **unobserved** |

## 11. Remaining blockers and release position

**Blockers**

1. Master specification absent → clause-level traceability, ICB mapping and 34-section
   review cannot be produced.
2. Hosted CI unobservable from this environment.
3. Restricted vendor market bytes remain reachable in earlier commits
   (`docs/HISTORICAL_DATA_REMEDIATION.md`); no history rewrite has been attempted.

**Position.** Atlas is a working local research application with verified financial
arithmetic, immutable market observations, deterministic packaging and browser evidence at
`481cd58`. It is not a completed Atlas Master Specification implementation, and no such
claim is made. Phase 10 work remains unstarted until the gates above are resolved.
