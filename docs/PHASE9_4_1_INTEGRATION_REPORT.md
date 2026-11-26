# Phase 9.4.1 — integration report

## 1. Hashes

| Ref | Commit |
| --- | --- |
| Merge base | `e0b3119fca3a97c7fe5e9acc215a8975738ce576` |
| Phase 9.4 development commit | `32941daaccde22451446e9455129270ee73f7ee0` |
| `origin/main` at reconciliation | `890144f5d62102b953a881abab50db6079945cdd` |
| Merge commit (this branch) | `ff71f4436874a158e04dd72327c1d6a51c9e6625` |

Before the merge the branches had diverged: development was 1 commit ahead of the base,
`main` was 12 ahead. `main` contained the v3.1.0 specification, its four appendices, the
ICB-01…ICB-64 registry, and three commits titled "sync v3.1 …"; development contained the
Phase 9.4 workstation. Neither was an ancestor of the other.

## 2. Method

`git merge FETCH_HEAD` after `git fetch origin main`. The merge completed with **no conflicts**
because the two lines of work touched different files: `main` changed the specification,
registries, scoreboard, traceability and the registry build scripts; development changed the
terminal workspaces, API schema advertisement, frontend and tests.

No force-push, no rebase of shared history, no commit discarded, no file selectively reverted.
The merge commit has two parents, so both histories are preserved and the fast-forward to `main`
later remains possible.

## 3. State after the merge

- `ATLAS_MASTER_SPEC.md` is v3.1.0, 333,547 bytes, SHA-256
  `d1800cfea35d973e2ff2b3570f8bf564fd3a7aceabca2f623ec5de17931a1111`.
  `scripts/verify_master_spec.py` reports **VERIFIED** (size and digest).
- 61 numbered sections are present, four `## Appendix` headings, and 64 unique ICB ids
  (ICB-01 … ICB-64).
- `artifacts/icb_registry.json` holds 64 benchmark entries, all `spec_version: 3.1.0`.
- All Phase 9.4 files are present: shells, docking engine, command registry, eight panels,
  `atlas.workspace.v2` validation, 45 frontend tests, 13 backend layout tests, the committed
  Playwright journey and the Phase 9.4 documentation set.

## 4. One stale assertion corrected

`tests/test_phase9_2_8_master_spec_registry.py::test_icb_registry_covers_all_sixty_four_benchmarks`
asserted `len(identifiers) == 64` and `len(set(identifiers)) == 48`. The second expectation is a
leftover from the 48-capability era: the registry v3.1 genuinely contains 64 **unique**
benchmark ids, and the same test's next line pins the complete `ICB-01…ICB-64` set. Corrected to
`== 64`, with a comment explaining why. This is not a weakened assertion — uniqueness is still
required, and the full-set assertion is unchanged. All 13 registry tests pass.

Independent evidence: `grep -oE 'ICB-[0-9]{2}' ATLAS_MASTER_SPEC.md | sort -u | wc -l` → 64, and
the registry JSON contains one entry per id from ICB-01 to ICB-64.

## 5. Uncommitted local state

`artifacts/phase9_1_model_audit.json` was already modified before this phase (database-path
dependent package hashes; all 16 verdicts unchanged). It is preserved untouched and remains
uncommitted, consistent with Phase 9.3.1.

## 6. Reproduce

```bash
git fetch origin main
git rev-parse FETCH_HEAD            # 890144f5d62102b953a881abab50db6079945cdd
git merge-base HEAD FETCH_HEAD      # e0b3119fca3a97c7fe5e9acc215a8975738ce576
python scripts/verify_master_spec.py
python -m pytest tests/test_phase9_2_8_master_spec_registry.py -q
wc -c ATLAS_MASTER_SPEC.md  # 333547
```
