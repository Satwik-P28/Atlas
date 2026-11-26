# Public release handover — exact administrative sequence

Everything engineering-side is finished and certified. This file is the sequence a maintainer with
GitHub (and PyPI) administrative rights runs to publish Atlas v0.2.0-beta.1. Each step says what it
unblocks, the command, and how to check it worked. Nothing here was executed by the coding agent: it
has no administrative credentials, and repository rename, visibility change, repository creation,
release creation and Pages enablement are account-level operations.

Certified inputs (in this checkout):

| Input | Value |
| --- | --- |
| Certified source commit | `36c7ee8e09862dd9bcea6d1927a72650a7308937` |
| Clean-history candidate | `.release/clean-history` @ `8e3da8fe6492` (single commit, 1,089 files) |
| Wheel | `dist/atlas_quant-0.2.0b1-py3-none-any.whl` — `0d546263fc66288b1d3d5adc9ac9a6d6d332073f52df32910429deb10e917dac` |
| Source distribution | `dist/atlas_quant-0.2.0b1.tar.gz` — `aa29c862ffc731a4cf7b447874396617c48b568f544bfb4f58fe58b066564fe8` |
| Sanitized source snapshot | `dist/atlas-source-HEAD-sanitized.tar.gz` — `c2af8558e1ba35a8a9d9e2fd92ce37cf6af7ee88a17bf871c85580795853b186` |
| SBOM | `dist/sbom.cdx.json` — `51e7fb84abba2c06135ba2c77b0b357a00b7dd1ec1a14cb9e8f5e6f8a4a6ca6e` |
| Checksums | `artifacts/release/SHA256SUMS` |

## 0. Preconditions and name availability

Verified on 2026-11-26 by unauthenticated GitHub and PyPI API reads:

| Check | Result |
| --- | --- |
| `Satwik-P28/Atlas` exists | Yes — public, default branch `main`, 24 branches, 0 tags, 0 forks, 8 open PRs, `has_pages: false` |
| `Satwik-P28/Atlas-development` exists | **No** (HTTP 404) — the name is free |
| `atlas-quant` on PyPI | **Unregistered** (HTTP 404) — the name is free |
| GitHub CLI on the build host | **Not available** — these steps need a machine where `gh` is authenticated as the owner |

Do not rename first without the backup in §1; the rename makes the old URL redirect, and a redirect
is not a backup.

## 1. Back up the development repository (lawful retention)

```bash
# Full mirror including all refs, then verify it opens and lists every branch.
git clone --mirror https://github.com/Satwik-P28/Atlas.git Atlas-development-backup.git
cd Atlas-development-backup.git && git branch -a | wc -l && git tag | wc -l
cd .. && tar czf Atlas-development-backup-$(date -u +%Y%m%d).tar.gz Atlas-development-backup.git
sha256sum Atlas-development-backup-*.tar.gz > Atlas-development-backup.sha256
```

Store the archive on storage you control. It contains the restricted vendor blobs, so keep it private
and do not upload it anywhere public. This backup is the "complete private backup where lawful" that
precedes any visibility change.

## 2. Restrict the development repository

```bash
gh repo edit Satwik-P28/Atlas --visibility private --accept-visibility-change-consequences
gh repo view Satwik-P28/Atlas --json visibility,isPrivate
```

Expected: `"visibility":"private"`, `"isPrivate":true`.

This stops *further* exposure. It does **not** recall copies already cloned, forked, cached or
indexed, and it does not delete the objects; treat anything downloaded before this step as still out
there.

## 3. Rename it to the private archive name

```bash
gh repo rename Atlas-development --repo Satwik-P28/Atlas --yes
gh repo view Satwik-P28/Atlas-development --json name,visibility
```

Expected: `Atlas-development`, `private`. GitHub creates a redirect from the old name, which is why
the backup in §1 exists and why the public repository must get the old name in the very next step.

## 4. Push the certified clean-history candidate as the public repository

The candidate was built and verified locally; rebuild it from the certified commit if needed:

```bash
.venv/bin/python scripts/build_clean_history_candidate.py --commit 36c7ee8e09862dd9bcea6d1927a72650a7308937
# expect: PASS no_restricted_paths_in_history / clean_working_tree / single_commit / tree_matches_archive
```

Then create and push:

```bash
cd .release/clean-history
git log --oneline            # exactly one commit
git remote add origin https://github.com/Satwik-P28/Atlas.git
gh repo create Satwik-P28/Atlas --public --source . --remote origin --push \
  --description "Atlas: The Evidence-First Financial Research Operating System."
cd ../..
```

Checks that must pass before tagging:

```bash
# 1. nothing restricted is reachable in the new repository
git clone --mirror https://github.com/Satwik-P28/Atlas.git /tmp/atlas-public.git
git -C /tmp/atlas-public.git rev-list --objects --all | grep -Ei 'nasdaq_(AAPL|AMZN|GS|JPM|UNH)\.csv|alphavantage' && echo "FAIL" || echo "CLEAN"
# 2. the tree matches the certified snapshot
git -C /tmp/atlas-public.git log -1 --format='%H %T'
git -C .release/clean-history log -1 --format='%H %T'
```

The two tree ids must be identical.

## 5. Tag and publish the prerelease

```bash
cd .release/clean-history
git tag -a v0.2.0-beta.1 -m "Atlas v0.2.0-beta.1 — experimental public preview"
git push origin v0.2.0-beta.1
cd ../..

gh release create v0.2.0-beta.1 \
  dist/atlas_quant-0.2.0b1-py3-none-any.whl \
  dist/atlas_quant-0.2.0b1.tar.gz \
  dist/atlas-source-HEAD-sanitized.tar.gz \
  dist/sbom.cdx.json \
  dist/SHA256SUMS \
  --repo Satwik-P28/Atlas \
  --title "Atlas v0.2.0-beta.1 — experimental public preview" \
  --notes-file RELEASE_NOTES.md \
  --prerelease \
  --latest=false
```

Before uploading, re-verify the four files:

```bash
(cd dist && sha256sum -c SHA256SUMS)   # all four must print OK
```

The release must be marked **prerelease**. Do not use "latest". The release notes describe an
experimental public preview and state plainly that independent human validation was not performed.

Afterwards confirm the pipeline on the public repository:

```bash
gh run list --repo Satwik-P28/Atlas --limit 5
```

## 6. Landing page on GitHub Pages

The workflow is committed at `.github/workflows/pages.yml` (publishes `docs/launch/`). Enable Pages
once:

```bash
gh api -X POST repos/Satwik-P28/Atlas/pages -f 'build_type=workflow' \
  || gh api -X PUT repos/Satwik-P28/Atlas/pages -f 'build_type=workflow'
gh api repos/Satwik-P28/Atlas/pages --jq '.html_url'
```

Then re-run the workflow (`gh workflow run pages.yml --repo Satwik-P28/Atlas`) and check the URL it
reports. The page is static: no API, no server, no tracking. The unauthenticated Atlas API is never
exposed by it.

## 7. PyPI trusted publishing (optional, not a release blocker)

`atlas-quant` is unregistered. To publish via OIDC instead of a token:

```bash
# 1. Sign in to https://pypi.org/manage/account/publishing/ and add a pending publisher:
#    PyPI project name: atlas-quant
#    Owner: Satwik-P28      Repository: Atlas
#    Workflow name: release.yml      Environment: pypi
# 2. Create the GitHub environment named "pypi" (no secrets needed; OIDC is used).
gh api -X PUT repos/Satwik-P28/Atlas/environments/pypi >/dev/null
```

Publish by publishing the GitHub release (§5): `.github/workflows/release.yml` triggers on
`release: published`, downloads the wheel and sdist **attached to that release**, verifies both
against the hashes recorded in `docs/RELEASE_GATES.json`, and only then uploads exactly those bytes.
A hash mismatch fails the job, so a different build can never silently replace the certified one.

Manual fallback if trusted publishing cannot be configured:

```bash
python -m pip install twine
twine upload dist/atlas_quant-0.2.0b1-py3-none-any.whl dist/atlas_quant-0.2.0b1.tar.gz
```

Do not describe Atlas as available on PyPI until an upload actually succeeds.

## 8. Remaining exposure that no step fixes

- Copies of the development repository taken before §2 remain in the hands of whoever took them.
- GitHub may keep `refs/pull/1`–`8` objects and cached views of the old public repository. Closing
  the pull requests does not delete blobs; ask GitHub Support to purge cached views if that matters
  for the vendor terms:

  ```text
  Subject: Removal request — cached views of restricted vendor data
  Repository: Satwik-P28/Atlas-development (formerly Satwik-P28/Atlas)
  Please purge cached views and any archived copies of the former public repository, including
  refs/pull/* refs, for the nine vendor market-data paths listed in docs/REPOSITORY_MIGRATION.md.
  ```

- Search-engine and third-party caches are outside GitHub's control.

Record in the release notes which of these steps was taken. Do not state that restricting
visibility removed data that had already been downloaded.

## 9. What to report afterwards

| Field | Where to record it |
| --- | --- |
| Public repository URL | README, RELEASE_GATES.json, CITATION.cff |
| Release URL and tag | RELEASE_GATES.json, RELEASE_READINESS.md |
| Pages URL | README, `docs/launch/index.html` footer |
| CI run identifiers on the public repository | RELEASE_GATES.json `candidate_ci_run` |
| PyPI project URL, if uploaded | RELEASE_NOTES.md, README |
| Final visibility state of the archive | REPOSITORY_MIGRATION.md |
