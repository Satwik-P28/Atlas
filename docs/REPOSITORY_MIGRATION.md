# Repository migration and historical exposure remediation

**Status: authorised; not executed.** The maintainer authorised on 2026-11-26 the remediation path
that keeps the development history intact: restrict the existing repository, rename it to
`Satwik-P28/Atlas-development`, and publish the verified clean-history candidate as the new public
`Satwik-P28/Atlas`. No step was executed, because rename, visibility change, repository creation and
release creation are account-level GitHub operations this environment has no credentials for. The
executable sequence, with checks between steps, is
[PUBLIC_RELEASE_HANDOVER.md](PUBLIC_RELEASE_HANDOVER.md). Section 3 below keeps the three options for
the record; Option B is the authorised one.

## 1. What is exposed, precisely

Nine vendor market-data files were committed in earlier development phases and are **not** in the
current tree (they were removed and are listed as `not_permitted` in
[`DATA_RIGHTS_INVENTORY.json`](DATA_RIGHTS_INVENTORY.json)):

| Path | Rights holder | Why it cannot be redistributed |
| --- | --- | --- |
| `fixtures/market/nasdaq_AAPL.csv` | Nasdaq (via a market-data vendor) | Vendor terms do not permit redistribution |
| `fixtures/market/nasdaq_AMZN.csv` | Nasdaq | as above |
| `fixtures/market/nasdaq_GS.csv` | Nasdaq | as above |
| `fixtures/market/nasdaq_JPM.csv` | Nasdaq | as above |
| `fixtures/market/nasdaq_UNH.csv` | Nasdaq | as above |
| `fixtures/market/ibm_daily_alphavantage.json` | Alpha Vantage | Free-tier terms do not permit redistribution |
| `fixtures/market/ibm_dividends_alphavantage.json` | Alpha Vantage | as above |
| `fixtures/market/ibm_splits_alphavantage.json` | Alpha Vantage | as above |
| `fixtures/market/alphavantage_manifest.json` | Alpha Vantage | as above |

Facts established in this phase:

- The **current tree is clean**: the sanitized snapshot of `HEAD` excludes **zero** paths, because
  the files were already removed (`docs/PROVENANCE_MAPPING.json` → `excluded_paths: []`).
- The **history is not clean**: those blobs remain reachable from the commits that added them, so
  anyone with the repository can recover the data. Removal from the tip does not remove exposure.
- A clean-history candidate now exists locally at `.release/clean-history` (single commit
  `8e3da8fe6492`, 1,089 files, 1,185 objects, provenance `docs/PROVENANCE_MAPPING.json`). It is a
  *candidate*, not a publication; every self-check passes and zero restricted objects are reachable
  from it.

Exposure therefore has one cause — published history — and it cannot be fixed by any change to the
working tree. It needs one of the three decisions in section 3.

## 2. What a fresh-history repository does and does not fix

| Property | Fresh-history candidate | Original repository |
| --- | --- | --- |
| Restricted blobs reachable | No | Yes, from historical commits |
| Existing issues, stars, forks, links preserved | No | Yes |
| Requires history rewrite | No (it is a new root commit) | Yes |
| Fixes exposure of forks and clones already taken | No | No |
| Reversible | Yes (delete the new repository) | No (rewritten SHAs are unrecoverable) |

A distribution repository does **not** resolve exposure in the original public repository. If the
original stays public, the data stays retrievable regardless of what is published elsewhere.

## 3. The three decisions, with exact commands

Pick exactly one. Each assumes `gh` or the GitHub web UI is already authenticated as the repository
owner; this document does not assume the agent has, or should have, that access.

### Option A — Rewrite history of the existing repository (most complete, most destructive)

Removes the blobs from every commit and force-updates branches. Every existing clone, fork and
reference to current commit ids breaks. Requires coordination with anyone who has a checkout.

```bash
# 0. Announce a freeze; everyone must stop pushing.
python -m pip install --user git-filter-repo

# 1. Work on a fresh mirror so the original is untouched until you are sure.
git clone --mirror https://github.com/Satwik-P28/Atlas.git atlas-rewrite.git
cd atlas-rewrite.git

# 2. Remove the nine paths from all history.
git filter-repo \
  --path fixtures/market/nasdaq_AAPL.csv --path fixtures/market/nasdaq_AMZN.csv \
  --path fixtures/market/nasdaq_GS.csv   --path fixtures/market/nasdaq_JPM.csv \
  --path fixtures/market/nasdaq_UNH.csv  --path fixtures/market/ibm_daily_alphavantage.json \
  --path fixtures/market/ibm_dividends_alphavantage.json \
  --path fixtures/market/ibm_splits_alphavantage.json \
  --path fixtures/market/alphavantage_manifest.json --invert-paths

# 3. Verify before publishing: this must print nothing.
git log --all --oneline -- fixtures/market/nasdaq_AAPL.csv fixtures/market/ibm_daily_alphavantage.json
git rev-list --objects --all | grep -Ei 'nasdaq_(AAPL|AMZN|GS|JPM|UNH)\.csv|alphavantage' || echo CLEAN

# 4. Publish (destructive; requires the owner's explicit authorisation).
git push --force --mirror https://github.com/Satwik-P28/Atlas.git
```

Afterwards: ask GitHub Support to purge cached views, and treat every previously issued archive or
fork as still containing the data.

### Option B — Make the repository private, publish the clean-history candidate publicly

Least destructive to the project's own history, and the fastest to a lawful public distribution.
The original repository keeps its history and evidence; the public repository never contained the
vendor data.

```bash
# 1. Visibility change (owner action, irreversible in the sense that public forks remain).
gh repo edit Satwik-P28/Atlas --visibility private --accept-visibility-change-consequences

# 2. Publish the verified candidate as the public distribution repository.
cd .release/clean-history
gh repo create Satwik-P28/Atlas-public --public --source . --remote origin --push
```

The candidate is reproducible from the reported release commit:

```bash
.venv/bin/python scripts/build_clean_history_candidate.py --commit <release-commit>
```

### Option C — Keep the original as-is and rely on the snapshot archive only

Publish no Git repository; distribute the sanitized source archive and the wheel/sdist. Exposure in
the original repository remains. This is only defensible if the maintainer accepts that the vendor
data stays retrievable from history, and it must be stated plainly in the release notes rather than
implied otherwise.

## 4. Evidence the maintainer should demand before authorising

1. `docs/PROVENANCE_MAPPING.json` shows `restricted_paths_reachable: []` and
   `single_commit: true` for the candidate.
2. Option A only: `git rev-list --objects --all | grep -Ei 'nasdaq_|alphavantage'` prints nothing on
   the rewritten mirror, and a `git clone` of the pushed repository reproduces that result.
3. The release notes state which option was taken, and — if A or C — that copies already taken
   remain affected.
4. `docs/DATA_RIGHTS_AND_DISTRIBUTION.md` still matches the shipped tree: derived SEC facts only, no
   vendor price data, no bundled filings with uncertain redistribution rights.

## 5. What is not affected

- **SEC-derived fixtures** (`fixtures/sec/**`, `fixtures/demo/**`): US government filings or
  project-authored synthetic filings. The rights inventory records them as derived facts and
  identifiers, not republications of a vendor's document set.
- **Treasury and regulatory fixtures**: public-domain or attribution-only, recorded per path in the
  inventory.
- **Source code, tests, documentation and the wheel**: the current tree is clean; the exposure is a
  property of history only.
