# Final Release Report — FOCUS Integration

## Candidate

| Field | Value |
|-------|-------|
| Branch | `focus/integration` (based on PR #1 head `3f184ebcfc4524de06d61c44c770580f1135e27b`) |
| Integration commit (code + reconciled FOCUS docs) | `28ff2e88508b1a6b212aec2e57df1eda35966a8f` |
| This report | committed on top of the integration commit; the branch head at hand-off is stated in the delivery message |
| Reconciles | `cursor/focus-priority0-827f` (PR #1) and `focus/application-ready` (`bf5f6ade…`) |
| `main` | untouched at `644448d4fbb3414c9c8045f5a86030ef34bfe2df` |
| `focus/application-ready` | preserved as reference, not deleted |

## What was taken from where

| Area | Source | Decision |
|------|--------|----------|
| Certificate schema `atlas.research_certificate.v1` | PR #1 | kept |
| FinanceBench evaluator repairs | PR #1 | kept |
| Scale repair (header row, unknown scale is `None`) | PR #1 | kept |
| Typed precision, `economic_amount`, display places | PR #1 | kept |
| Source-binding validation, 13 case definitions | PR #1 + reference branch | kept, extended |
| Four verification levels | reference branch | integrated |
| Independent arithmetic vs. separate source pass | reference branch | integrated |
| 16 re-signed adversarial mutations | reference branch | integrated |
| Fail-closed demo exit contract | reference branch | fixed and integrated |
| Explicit manifest command, no silent regeneration | reference branch | integrated |
| **Circular `trusted_sources` trust model** | PR #1 | **replaced** |

The one deliberate removal: PR #1 built `trusted_sources` from
`binding.source_table_sha256` — a value carried by the certificate under test — and then compared the
certificate's hash against it. That check cannot fail. It is now rejected with `SOURCE_UNVERIFIED` and
reason `legacy_trusted_sources_insufficient`, and real verification requires a pinned manifest plus
archived bytes.

## Checks actually run at this candidate

| Check | Command | Result |
|-------|---------|--------|
| Backend suite | `pytest -q` | **812 passed** (158.10 s) |
| Certificate/level/mutation tests | `pytest tests/test_focus_certificate.py tests/test_certificate_source_limits.py` | **40 passed** |
| Frontend unit tests | `npm test -- --run` | **50 passed**, 4 files |
| TypeScript build | `npm run typecheck` | clean |
| Production web build | `npm run build` | built in 3.33 s |
| Database/migration/packaging | `pytest tests/test_packaging_contract.py tests/test_phase9_2_migrations.py tests/test_storage.py` | passed |
| Research-integrity subset | 13 CI test files | passed |
| Phase 9.2 reproduction | `scripts/reproduce_phase9_2.py` | `exit: 0`, package sha256 `3bbaca54…`, no differences |
| Clean-install reproduction | `scripts/verify_clean_install.py --demo-db var/atlas.db` | `status: pass`, `reproduced: true`, network not used |
| Distributable fixtures | `build_terminal_db.py` + `verify_distributable_fixtures.py --require-demo-db` | passed, 10,580 synthetic rows |
| Source-rights checks | restricted-fixture scan, `test_phase9_2_2_data_rights_fixtures.py` | passed, no licensed fixtures |
| Fresh-checkout FOCUS flow | `make focus-corpus` → `focus-manifest` → `focus-demo` | exit `0`, `failures: []`, `status: passed` |
| Demo negative controls | missing manifest / perturbed manifest / missing corpus | exit `2` / `1` / `2` |
| Strict certificate CLI | `atlas verify-certificate … --manifest --snapshots --strict` | `SOURCE_VERIFIED`, checks pass |
| Browser acceptance (Playwright journeys) | `node e2e/phase9_2_jpm.mjs`, `phase9_2_market.mjs` | **not run** — see blockers |
| GitHub Actions workflow | — | **not run** — see blockers |

## Demo results at this candidate

Thirteen cases: **10 answered, 3 refused**. All ten certificates verify at `SOURCE_VERIFIED` against the
pinned manifest and archived bytes; the flagship certificate passes every individual check.
**16/16** adversarial mutations refused, including input+result+fingerprint re-signing.
Contract checks: **50/50** pass.

Flagship: 3M FY2022 net sales, printed `34,229`, scale `6`, economic amount `34,229,000,000` USD
(currency derived from the `$` printed in the amount row).

Refusals: FOCUS-09 justified unanswerability (JPMorgan gross profit not presented), FOCUS-12 resolver
capability gap (3M FY2018 prints `32,765`, Atlas does not resolve it — **not** counted as answered),
FOCUS-13 historical information refusal (evidence not public at cutoff).

## Blockers

1. **GitHub Actions was not executed for this commit.** CI cannot be triggered or queried from this
   environment, so no workflow conclusions exist for `28ff2e8`. Release readiness is therefore *not*
   declared on local evidence alone.
2. **Browser acceptance was not executed.** Chromium requires `libnspr4` and related system libraries;
   installing them needs root, which this sandbox forbids. The frontend unit suite, typecheck and
   production build pass, but the two Playwright journeys are unverified locally. CI installs browser
   dependencies and is the correct place to run them.
3. **`main` contains licensed historical material** (`d8ae4f1`). A normal merge does not remove it, no
   history rewrite is authorized, and promotion to `main` is not authorized by this workstream. This
   needs an owner decision on history policy before any promotion.
4. **The trust anchor is unsigned.** `artifacts/focus_source_manifest.json` is produced by an explicit
   command and proves consistency with that snapshot only — not publication time, not financial semantic
   correctness, not manifest authenticity.

## Status

- `FOCUS_READY`: **not declared.** The unified candidate passes every check that could be run here, but
  the brief requires the full GitHub Actions workflow against the final commit, and that has not happened.
- `MAIN_PROMOTED_AND_VERIFIED`: **not authorized**, not attempted.
