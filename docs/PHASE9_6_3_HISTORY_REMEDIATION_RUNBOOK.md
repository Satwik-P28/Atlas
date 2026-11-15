# Phase 9.6.3 — History remediation runbook (for owner approval)

**Not executed.** No shared history was rewritten in this phase.

## Option A — authorized rewrite of `main`

1. Freeze writes; announce a migration window.
2. Create immutable backups: `git branch backup/main-644448d main`,
   `git push origin backup/main-644448d`.
3. Rebuild a clean history from `486e7d0` with the reviewed tree
   (`git commit-tree <clean-tree> -p 486e7d0`) and verify file-by-file equality with the audited
   implementation.
4. `git push --force-with-lease origin <clean-commit>:main` **only after** the owner authorizes
   the force push.
5. Verify: `git merge-base --is-ancestor d8ae4f1 origin/main` must fail; tree must equal the
   reviewed tree; the full suite must pass on the rewritten branch.
6. Notify collaborators: clones must re-clone or `git fetch && git reset --hard origin/main`;
   forks keep the old objects and must be handled separately.

## Option B — approved private retention

If the owner accepts retention: document that `d8ae4f1` stays in `main`, GitHub retention and any
clones; keep the repository private; keep benchmark text out of working-tree artifacts; do not
publish or distribute the corpus. This is a policy decision, not a technical fix, and it requires
the owner's written approval.

## Current status

Neither option is authorized. `main` is unchanged since `644448d`.
