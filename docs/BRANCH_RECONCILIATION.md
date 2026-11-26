# Branch reconciliation — v0.2.0-beta.1

How the outstanding research lines were integrated, in what order, and what was deliberately left out.
All integration is non-destructive: merges only, no rewrite, no force-push, pull requests left untouched.

Base: `main` at `644448d4fbb3414c9c8045f5a86030ef34bfe2df` ("Restore main to the Phase 9.5 tree"). That
commit's tree is identical to `486e7d0`, the merge base of every FOCUS-lineage branch, which is why the
first integration merge changed no file content — only history.

## Ancestry and dependency map

```text
main 644448d ──┬─ release/v0.2.0-beta.1
               │      ├── merge FOCUS + financial-answer stack (c8f1769 lineage, 37 commits)
               │      ├── merge v3.2 price intelligence + temporal (44cbbf3, 11 commits)
               │      ├── merge certified revision impact (8e666a0, 7 commits)
               │      └── merge ALFRED vintage study (6bf760d, 5 commits)
               ├─ cursor/focus-priority0-827f (789d360)  ── PR #1
               │      └─ focus/answer-semantics (4c1cf10) ── PR #7
               │             └─ holdout/answer-semantics-prospective (0090573)
               │                    └─ focus/financial-answer-hardening-v1 (c8f1769)
               ├─ review/price-intelligence-v3.2 (747871b) ── PR #3
               │      └─ v3.2-integrity (5b8605e) ── PR #4
               │             └─ v3.2-temporal (44cbbf3)
               │                    └─ review/decision-intelligence-cri (8e666a0) ── PR #5
               │                           └─ research/real-world-revision-study (6bf760d) ── PR #6
               └─ docs/atlas-v3-2-research-price-intelligence (59c6df3) ── PR #2
```

## Integration order and rationale

1. **FOCUS Priority 0 → answer semantics → prospective holdout → hardening** is a single stack: each
   branch is an ancestor of the next, and the hardening head contains all of its predecessors. Merging
   the head brings the whole verified line including the certificates, the semantics work, the frozen
   holdout and the geometry-aware resolver.
2. **v3.2 price intelligence → integrity → temporal** is the second stack, based on `main`. Merged next
   because it is the largest independent surface (workstation, price explanations, spec reconciliation)
   and the later CRI/ALFRED work is built on it.
3. **Certified revision impact (CRI)** was merged after the temporal stack, because its first commits
   sit on `v3.2-temporal`; merging earlier would have duplicated history.
4. **ALFRED vintage study** was merged last, because it depends on CRI.

## Conflicts encountered and how they were resolved

| Conflict | Resolution |
|---|---|
| `README.md` (twice: CRI, ALFRED) | Both branches prepend their own research summary. Taken as "ours" and replaced by a single product README; the research content is retained in `docs/research/` and the branch history. |
| Semantic: availability model (no textual conflict) | The price-evidence resolver refused every document whose availability precision was `unknown`, which after Phase 9.6.1 is every ingested filing. Six tests failed only after integration. Resolved in code: a recognised modelled bound resolves as `modeled_bound` with an explicit upper-bound label and disclosure warning, while genuinely unknown timing still refuses. Regression test added. |
| Build interface: `Makefile` | A wrapped comment lost its `#`, making every `make` target fail with "missing separator". Repaired and pinned by a test that parses the Makefile. |
| Packaging: decision test solvers | OSQP and Clarabel were used by CRI tests but declared nowhere. Added to the `optimization` extra and installed in CI, with tests pinning both facts. |

## Deliberately excluded

| Branch | Reason |
|---|---|
| `focus/application-ready` (bf5f6ad) | Three commits ahead of the shared base with no verified superset relationship to the stack that was integrated; merging would duplicate or contradict the FOCUS line. Left for the maintainer. |
| `focus/integration` (dc932e9) | An earlier integration attempt on the same base; superseded by this branch, and merging it would replay overlapping changes. |
| `focus/semantic-integrity`, `main-restore`, `release/9.6.{2,3,4}-candidate` | Local/remote snapshots of earlier phases; their content is already in the integrated history through the FOCUS lineage or `main`. |
| `docs/atlas-v3-2-research-price-intelligence` (59c6df3) | Documentation-only branch whose content is included in the v3.2 stack that was integrated. |
| `freebuff/*` branches | Agent scratch branches; not research lines. |
| PR #7 retargeting | PRs are left as-is by design. The release branch records the integration; retargeting or merging the open PRs remains a maintainer decision. |

## Verification after integration

- Full backend suite: 1256 passed.
- Frontend: 55 unit tests, typecheck, production build.
- Hosted CI run 45292649474 on the integration head `862ad6f`: all six jobs green, including the
  deterministic application reproduction that fails on `main` and Playwright browser acceptance.

The deterministic reproduction failure on `main` was a stale expected value (`fresh_schema == 13` while
the chain reached 14), fixed inside the FOCUS lineage by pinning to `LATEST_VERSION`; this release adds
the regression test that executes the script and asserts the artifact is regenerated byte-for-byte.
