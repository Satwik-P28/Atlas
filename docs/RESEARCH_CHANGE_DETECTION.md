# Research change detection

Contract: `atlas.research_change_report.v1` (`src/atlas/research/changes.py`). On demand and
deterministic: no scheduler, no background agent, no external notification, no automatic
rewrite of saved research.

## Why it exists

A saved memo is a statement about a moment. When a filing is amended or a provider corrects an
observation, the memo does not become false — it becomes *reviewable*. The report says which
claims depend on the changed object, what the original and replacement values are, and whether
a replay is possible.

## Categories

| Category | Meaning |
| --- | --- |
| `unchanged` | Every dependency still resolves and nothing newer touches it. |
| `new_relevant_evidence` | Evidence for the same issuer and concept became available after the cutoff. |
| `superseded_evidence` | A cited record has a successor; the memo keeps the original value. |
| `revised_market_observation` | A newer bar revision exists for a pinned session. |
| `missing_dependency` | A cited record is no longer present in this database. |
| `model_version_incompatible` | The memo's compiler version differs from the current implementation. |
| `rights_changed` | A cited source does not permit redistribution. |
| `requires_review` | At least one finding affects a claim. |

## What a finding contains

Original evidence id, replacement evidence id, concept, period, original and replacement
values, revision kind and availability time; the affected claim ids and their statements;
`replay_possible` and `auto_replay_performed` (always `false`).

## Rules

1. **A new filing does not invalidate unrelated analysis.** Only claims whose evidence or
   concept/period matches a finding are listed as affected.
2. **A provider correction does not rewrite a saved memo.** The stored document keeps the
   original value; the report states both values.
3. **Missing dependencies are reported, never repaired.** A record that is gone produces
   `missing_dependency` with `replay_possible: false`.
4. **Rights are re-evaluated.** If a source's class became restricted, export is refused and
   the finding names the source.
5. **The memo's own version is never bumped implicitly.** Creating a new version is a
   separate, explicit action that re-runs the analysis at a stated cutoff.

## Revision injection in the demonstration

The end-to-end demonstration injects a replacement evidence record (`revision_kind =
amendment`, `supersedes = <original id>`). This is synthetic test data, labelled as such in
the acceptance report, and it exists only in the temporary demonstration database. The
production fixture is never edited.
