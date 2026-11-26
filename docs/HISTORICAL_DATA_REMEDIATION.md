# Historical restricted-data exposure — remediation proposal

**Status: proposal only. Nothing has been rewritten or force-pushed.** A history rewrite
requires separate explicit authorization because it changes every subsequent commit hash
and every clone.

## 1. What remains exposed

Restricted market-data bytes were removed from the current tree in earlier checkpoints, but
they remain reachable in earlier commits:

| Commit | Content | Source rights |
| --- | --- | --- |
| `6920d0a` | `nasdaq_*.csv` daily price files | vendor terms; automated collection unauthorized |
| `d0e4540` | Alpha Vantage manifest/series | vendor terms; API redistribution not granted |
| earlier commits | IBM Alpha Vantage blobs | same |

Anyone with read access to the repository can `git show <sha>:<path>` and recover the
bytes. Removing a file in a later commit does **not** retract it.

## 2. Data-rights assessment

- The files were obtained under terms that permit local analysis, not redistribution.
- Published Git history is distribution: it is served to every clone.
- Derived analytics from those bytes inherit the restriction, but the primary exposure is
  the raw series themselves.
- Current `fixtures/` contains no restricted vendor files; CI checks for
  `nasdaq_*`/`alphavantage` names and passes.

## 3. Option A — retain history, restrict access (no rewrite)

**Actions.** Make the repository private (it is), audit collaborators and forks, document
the exposure in the release record.

**Pros.** No hash invalidation, no coordination, no risk of losing history.

**Cons.** The exposure persists for anyone with access; cannot be published later without
either a rewrite or a rights grant. Not sufficient if the repository is ever made public.

## 4. Option B — rewrite history (requires authorization)

**Tooling.** `git filter-repo --invert-paths --path <file> …` on a mirror clone; no
force-push decided here.

**Affected objects.** All commits touching the listed paths and every descendant of those
commits. If the files were introduced in `6920d0a` and `d0e4540`, every commit after the
earliest affected one gets a new hash. Branches: `main`, every `freebuff/*` branch that
contains those commits, tags and release artifacts.

**Risks.**

- Every collaborator must re-clone; a normal `git pull` on an old clone will resurrect the
  blobs or produce a divergent history.
- Pull-request references, CI run URLs, issue links and recorded commit SHAs (including the
  revision in this and prior acceptance documents) become stale.
- Signed commits/tags are invalidated.
- A mistake during the rewrite can lose work; a mirror backup is mandatory.

**Coordination.** Freeze pushes; announce; rewrite on a mirror; validate; force-push only
with explicit approval; require re-clone by everyone; re-run CI on the rewritten tip;
re-issue release manifests with the new revision.

**Backup and rollback.** Keep a full mirror (`git clone --mirror`) plus a bundle
(`git bundle create atlas-pre-rewrite.bundle --all`) off-repository. Rollback is restoring
the mirror and re-publishing the old refs — only possible while the old objects still
exist on the server.

**Validation after remediation.**

```bash
git log --all --oneline -- nasdaq_*.csv alphavantage*    # expect empty
git rev-list --objects --all | grep -Ei 'nasdaq_|alphavantage'   # expect empty
git gc --prune=now --aggressive                          # local only, after backup
```

GitHub may retain unreachable objects in its own storage after a force-push; a support
request is required to purge cached views. That limitation must be stated to the user, not
assumed away.

## 5. Recommendation

Do not rewrite while the repository is private and no publication is planned. If a public
release, a data-provider audit, or a distribution milestone becomes likely, execute
Option B with the full coordination above. Until then, record the exposure in
`docs/DATA_RIGHTS_AND_DISTRIBUTION.md` and keep the CI guard that prevents new restricted
files from being committed.

## 6. What this checkpoint did

- Verified the current tree is clean of restricted vendor fixtures (CI guard passes).
- Added no new vendor data.
- Did **not** rewrite history, force-push, or modify shared Git configuration.
